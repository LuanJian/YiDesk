"""通知服务：写 OutboxMessage 落库 → 投递到对应 IM 渠道（失败重试）。

调用方只负责 enqueue；实际投递：
- API 路由里通过 flush_async()（线程池）立即尝试
- 后台任务每 60 秒重试 pending 消息（最多 5 次）
"""
from __future__ import annotations

from datetime import timedelta

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.registry import registry
from app.core.config import get_config
from app.models.system import OutboxMessage
from app.models.ticket import STATUS_LABELS, Ticket
from app.models.user import User, utcnow

MAX_ATTEMPTS = 5


def ticket_url(ticket_id: int) -> str:
    return f"{get_config().public_base_url.rstrip('/')}/tickets/{ticket_id}"


def _channels_for_user(user: User) -> list[tuple[str, str]]:
    """返回 (渠道名, 接收标识)，只包含已启用且有绑定的渠道。"""
    cfg = get_config()
    out: list[tuple[str, str]] = []
    if cfg.dingtalk.enabled and user.dingtalk_userid:
        out.append(("dingtalk", user.dingtalk_userid))
    if cfg.feishu.enabled and user.feishu_open_id:
        out.append(("feishu", user.feishu_open_id))
    if cfg.wecom.enabled and user.wecom_userid:
        out.append(("wecom", user.wecom_userid))
    if cfg.mail.enabled and user.email:
        out.append(("mail", user.email))
    return out


def enqueue_for_user(
    db: Session, user: User, *, ticket_id: int | None, title: str, content: str, url: str = "",
    kind: str = "",
) -> None:
    # 第三十七批：个人通知偏好——kind 标注通知类型（status_change/urge/urgent），用户显式关闭该类则跳过
    if kind and not user.notify_enabled(kind):
        return
    for channel, receiver in _channels_for_user(user):
        db.add(
            OutboxMessage(
                channel=channel, receiver_id=receiver, ticket_id=ticket_id,
                title=title[:200], content=content[:2000], url=url[:500],
            )
        )
    db.commit()


def enqueue_for_users(db: Session, users: list[User], **kwargs) -> None:
    for u in users:
        enqueue_for_user(db, u, **kwargs)


def staff_users(db: Session) -> list[User]:
    return list(
        db.scalars(select(User).where(User.role.in_(("admin", "engineer")), User.is_active.is_(True))).all()
    )


# ---- 业务通知 ----

def notify_ticket_created(db: Session, ticket: Ticket, actor: User) -> None:
    users = [u for u in staff_users(db) if u.id != actor.id]
    title = f"新工单 {ticket.no}｜{ticket.title}"
    via = f"{actor.name or actor.username} 提交了"
    if ticket.requester_id and ticket.requester_id != actor.id:
        requester = db.get(User, ticket.requester_id)
        if requester:
            via += f"（提出者：{requester.name or requester.username}）"
            if requester.id != actor.id:
                # 代报修：实际报修人同样收到建单通知
                enqueue_for_user(
                    db, requester, ticket_id=ticket.id, title=title,
                    content=f"{via}「{ticket.category}」工单\n优先级：{ticket.priority}\n{ticket.description[:200]}",
                    url=ticket_url(ticket.id),
                )
    content = f"{via}「{ticket.category}」工单\n优先级：{ticket.priority}\n{ticket.description[:200]}"
    enqueue_for_users(db, users, ticket_id=ticket.id, title=title, content=content, url=ticket_url(ticket.id))


def notify_transition(db: Session, ticket: Ticket, event_desc: str) -> None:
    """状态变更：通知发起人（处理人是操作者时）与处理人；关注者同样订阅（v2.0）。"""
    title = f"工单 {ticket.no}｜{STATUS_LABELS.get(ticket.status, ticket.status)}"
    content = f"{ticket.title}\n{event_desc}"
    url = ticket_url(ticket.id)
    actor_id = None
    if ticket.events:
        actor_id = ticket.events[-1].actor_id
    to_notify: list[User] = []
    if ticket.creator_id != actor_id:
        creator = db.get(User, ticket.creator_id)
        if creator:
            to_notify.append(creator)
    if ticket.requester_id and ticket.requester_id not in (actor_id, ticket.creator_id):
        requester = db.get(User, ticket.requester_id)
        if requester:
            to_notify.append(requester)
    if ticket.assignee_id and ticket.assignee_id != actor_id:
        assignee = db.get(User, ticket.assignee_id)
        if assignee and all(u.id != assignee.id for u in to_notify):
            to_notify.append(assignee)
    # 关注者（工程师跟单/主管盯单）订阅同一事件，去重后合并
    from app.services import ticket_service

    for f in ticket_service.follower_users(db, ticket):
        if f.id != actor_id and f.is_active and all(u.id != f.id for u in to_notify):
            to_notify.append(f)
    enqueue_for_users(db, to_notify, ticket_id=ticket.id, title=title, content=content, url=url, kind="status_change")


def request_rating(db: Session, ticket: Ticket) -> None:
    creator = db.get(User, ticket.creator_id)
    if not creator:
        return
    title = f"请评价工单 {ticket.no}"
    content = f"您的工单「{ticket.title}」已标记为已解决，欢迎评价本次服务。"
    enqueue_for_user(db, creator, ticket_id=ticket.id, title=title, content=content, url=ticket_url(ticket.id))


# ---- 投递 ----

def flush(db: Session, limit: int = 50) -> int:
    """投递 pending 消息，返回成功条数。线程上下文里调用（同步阻塞 IO）。"""
    msgs = list(
        db.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.status == OutboxMessage.STATUS_PENDING, OutboxMessage.attempts < MAX_ATTEMPTS)
            .order_by(OutboxMessage.id)
            .limit(limit)
        )
    )
    ok = 0
    for m in msgs:
        adapter = registry.get(m.channel)
        if adapter is None or not adapter.ready:
            continue  # 渠道未启用/未就绪，保留等待
        m.attempts += 1
        try:
            adapter.send_card(m.receiver_id, m.title, m.content, m.url, m.ticket_id)
            m.status = OutboxMessage.STATUS_SENT
            m.sent_at = utcnow()
            m.last_error = ""
            ok += 1
        except Exception as exc:  # noqa: BLE001 记录后继续
            m.last_error = f"{type(exc).__name__}: {exc}"[:500]
            if m.attempts >= MAX_ATTEMPTS:
                m.status = OutboxMessage.STATUS_FAILED
    db.commit()
    return ok


async def flush_async() -> None:
    """API 路由里调用：线程池里跑一次投递，不阻塞事件循环。"""
    from app.models.database import create_session

    def _run() -> None:
        db = create_session()
        try:
            flush(db)
        finally:
            db.close()

    await run_in_threadpool(_run)
