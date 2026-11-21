"""操作审计服务（v2.4.1）：把系统/流转事件分类聚合，形成管理可信的审计报表。

分类按事件内容前缀识别（与各写入点的事件文案约定对应）：
编辑工单 / 指派给·改派给 / SLA 挂起·恢复 / 合并 / 自动派单（智能分派·关键词命中·扫码指定）
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket import TicketEvent
from app.models.user import User, utcnow

AUDIT_TYPES = {
    "edit": "编辑工单",
    "assign": "指派/改派",
    "sla_suspend": "SLA 挂起",
    "sla_resume": "SLA 恢复",
    "merge": "合并",
    "dispatch": "自动派单",
}


def classify(content: str) -> str | None:
    """事件内容 → 审计类型；不匹配返回 None（如普通受理/关闭流转）。"""
    c = (content or "").strip()
    if c.startswith("编辑工单"):
        return "edit"
    if c.startswith("指派给") or c.startswith("改派给"):
        return "assign"
    if c.startswith("SLA 挂起"):
        return "sla_suspend"
    if c.startswith("SLA 恢复"):
        return "sla_resume"
    if "合并" in c[:6] or c.startswith("工单") and "并入本单" in c:
        return "merge"
    if c.startswith(("智能分派", "关键词命中", "扫码指定派单")):
        return "dispatch"
    return None


def _fetch(
    db: Session,
    *,
    start: datetime,
    end: datetime,
    actor_id: int | None,
    audit_type: str | None,
):
    rows = list(
        db.scalars(
            select(TicketEvent).where(
                TicketEvent.type.in_((TicketEvent.TYPE_SYSTEM, TicketEvent.TYPE_TRANSITION)),
                TicketEvent.created_at >= start,
                TicketEvent.created_at < end,
            )
        )
    )
    out = []
    for ev in rows:
        at = classify(ev.content)
        if not at:
            continue
        if actor_id and ev.actor_id != actor_id:
            continue
        if audit_type and at != audit_type:
            continue
        out.append((ev, at))
    return out


def events(
    db: Session,
    *,
    start: datetime,
    end: datetime,
    actor_id: int | None = None,
    audit_type: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """审计明细（分页）：第二十二批固定按时间先后（正序）排序，不再支持自定义排序。"""
    rows = _fetch(db, start=start, end=end, actor_id=actor_id, audit_type=audit_type)
    if q and q.strip():
        needle = q.strip()
        rows = [(ev, at) for ev, at in rows if needle in (ev.content or "") or (ev.ticket and needle in (ev.ticket.no or "")) or (ev.ticket and needle in (ev.ticket.title or ""))]

    # 固定按时间先后（早 → 晚）
    rows.sort(key=lambda x: (x[0].created_at or datetime.min, x[0].id))

    total = len(rows)
    start_i = (max(page, 1) - 1) * min(page_size, 100)
    page_rows = rows[start_i : start_i + min(page_size, 100)]
    return {
        "total": total,
        "items": [
            {
                "id": ev.id,
                "created_at": ev.created_at.isoformat() + "Z" if ev.created_at else None,
                "actor": (ev.actor.name or ev.actor.username) if ev.actor else "系统",
                "ticket_id": ev.ticket_id,
                "ticket_no": ev.ticket.no if ev.ticket else None,
                "ticket_title": ev.ticket.title if ev.ticket else None,
                "audit_type": at,
                "audit_label": AUDIT_TYPES.get(at, at),
                "content": ev.content,
            }
            for ev, at in page_rows
        ],
    }
