"""SLA 服务：超时预警扫描与催办。

策略（每次扫描对每张未关闭工单）：
1. 响应预警：未首响应且距响应截止 <10 分钟（或已超）→ 提醒处理人（未指派则提醒全部工程师）一次
2. 响应超时：超过响应截止 → 通知管理员升级一次（sla_escalated 标记，重开后复位）
3. 解决超时：超过解决截止 → 提醒处理人 + 管理员一次（sla_resolve_warned）
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket import STATUS_CONFIRM, STATUS_PENDING, STATUS_PROCESSING, Ticket
from app.models.user import User, utcnow
from app.services import notify_service

OPEN_STATUSES = (STATUS_PENDING, STATUS_PROCESSING, STATUS_CONFIRM)


def _warn_point(created_at, deadline, percent: int):
    """预警时间点：距截止的剩余时长降到总时限的 percent%（第三十七批，原固定 10 分钟模式废弃）。

    created_at 缺失或窗口异常时退化为「截止前 10 分钟」，保证预警不失效。
    """
    try:
        window = deadline - created_at
        if window > timedelta(0):
            return deadline - window * (percent / 100.0)
    except (TypeError, ValueError):
        pass
    return deadline - timedelta(minutes=10)


def scan(db: Session) -> list[str]:
    """执行一次扫描，返回动作日志（便于测试断言）。挂起中的工单跳过（SLA 计时已暂停）。"""
    from app.core.config import get_config

    warn_percent = max(1, min(100, get_config().sla.warning_percent))
    now = utcnow()
    logs: list[str] = []
    tickets = list(
        db.scalars(
            select(Ticket).where(
                Ticket.status.in_(OPEN_STATUSES),
                Ticket.sla_suspended_at.is_(None),
                # 第二十九批：合并源单的 SLA 随主工单承载（避免源单超时预警/升级噪音）
                Ticket.merged_into_id.is_(None),
            )
        )
    )
    admins = list(db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))))
    staff = notify_service.staff_users(db)

    for t in tickets:
        assignee = db.get(User, t.assignee_id) if t.assignee_id else None

        # 1. 响应预警：剩余时限降到总时限的 warn_percent% 时提醒一次
        if (
            t.sla_response_deadline
            and not t.first_responded_at
            and not t.sla_response_warned
            and now >= _warn_point(t.created_at, t.sla_response_deadline, warn_percent)
        ):
            t.sla_response_warned = True
            targets = [assignee] if assignee else staff
            notify_service.enqueue_for_users(
                db, targets, ticket_id=t.id,
                title=f"响应预警 {t.no}",
                content=f"工单「{t.title}」即将/已经超过响应时限，请尽快受理。",
                url=notify_service.ticket_url(t.id),
            )
            logs.append(f"{t.no}: response warn")

        # 2. 响应超时升级
        if t.sla_response_deadline and not t.first_responded_at and not t.sla_escalated and now >= t.sla_response_deadline:
            t.sla_escalated = True
            notify_service.enqueue_for_users(
                db, admins, ticket_id=t.id,
                title=f"响应超时升级 {t.no}",
                content=f"工单「{t.title}」已超过响应时限仍未受理，请关注。",
                url=notify_service.ticket_url(t.id),
            )
            logs.append(f"{t.no}: response escalate")

        # 3. 解决超时
        if t.sla_resolve_deadline and now >= t.sla_resolve_deadline and not t.sla_resolve_warned:
            t.sla_resolve_warned = True
            targets = ([assignee] if assignee else []) + admins
            seen: set[int] = set()
            unique: list[User] = []
            for u in targets:
                if u and u.id not in seen:
                    seen.add(u.id)
                    unique.append(u)
            notify_service.enqueue_for_users(
                db, unique, ticket_id=t.id,
                title=f"解决超时 {t.no}",
                content=f"工单「{t.title}」已超过解决时限，请加快处理或与发起人沟通。",
                url=notify_service.ticket_url(t.id),
            )
            logs.append(f"{t.no}: resolve warn")

    db.commit()
    return logs
