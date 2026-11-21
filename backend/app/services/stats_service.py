"""统计服务：看板数据聚合（公司内网数据量小，直接 Python 聚合，简单可靠）。"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket import PRIORITY_LABELS, STATUS_LABELS, Rating, Ticket
from app.models.user import User, utcnow


def _minutes(a, b) -> float | None:
    """v2.12 接入工作日历：响应/解决时长剔除非工作时间（夜间/节假日不计入）。"""
    if not a or not b:
        return None
    from app.services.business_time import business_minutes_between

    return max(0.0, float(business_minutes_between(a, b)))


def overview(db: Session) -> dict:
    tickets = list(db.scalars(select(Ticket)))
    ratings = list(db.scalars(select(Rating)))
    by_status: dict[str, int] = defaultdict(int)
    for t in tickets:
        by_status[t.status] += 1

    resp_times = [_minutes(t.created_at, t.first_responded_at) for t in tickets if t.first_responded_at]
    res_times = [_minutes(t.created_at, t.resolved_at) for t in tickets if t.resolved_at]
    resolved = [t for t in tickets if t.resolved_at]
    resp_breach = sum(
        1 for t in resolved if t.sla_response_deadline and t.first_responded_at and t.first_responded_at > t.sla_response_deadline
    )
    res_breach = sum(1 for t in resolved if t.sla_resolve_deadline and t.resolved_at > t.sla_resolve_deadline)

    stars = [r.stars for r in ratings]
    # v2.7 实时大屏补充：今日新建/解决；v2.11 补充：本周工单（周一零点起）
    # 库内时间为 UTC，业务口径按公司时区（Asia/Shanghai）取日期，否则早 8 点前会错分昨天/今天
    from zoneinfo import ZoneInfo

    now_local = utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Shanghai"))
    today = now_local.date()
    week_start = today - timedelta(days=today.weekday())
    to_local = lambda dt: dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Shanghai")) if dt else None
    today_created = sum(1 for t in tickets if t.created_at and to_local(t.created_at).date() == today)
    today_resolved = sum(1 for t in tickets if t.resolved_at and to_local(t.resolved_at).date() == today)
    week_created = sum(1 for t in tickets if t.created_at and to_local(t.created_at).date() >= week_start)
    return {
        "total": len(tickets),
        "open": sum(by_status[s] for s in ("pending", "processing", "pending_confirm")),
        "by_status": {STATUS_LABELS[s]: by_status.get(s, 0) for s in STATUS_LABELS},
        "avg_first_response_minutes": round(sum(resp_times) / len(resp_times), 1) if resp_times else None,
        "avg_resolution_minutes": round(sum(res_times) / len(res_times), 1) if res_times else None,
        "response_sla_rate": round(100 * (1 - resp_breach / len(resolved)), 1) if resolved else None,
        "resolution_sla_rate": round(100 * (1 - res_breach / len(resolved)), 1) if resolved else None,
        "rating_avg": round(sum(stars) / len(stars), 2) if stars else None,
        "rating_count": len(ratings),
        "today_created": today_created,
        "today_resolved": today_resolved,
        "week_created": week_created,
    }


def trend(db: Session, days: int = 30) -> list[dict]:
    tickets = list(db.scalars(select(Ticket)))
    ratings = list(db.scalars(select(Rating)))
    # 日期口径与 overview 一致：按 Asia/Shanghai 取本地日期（库内为 UTC）
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    to_local = lambda dt: dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz) if dt else None
    start = (to_local(utcnow()) - timedelta(days=days - 1)).date()
    created: dict[str, int] = defaultdict(int)
    resolved: dict[str, int] = defaultdict(int)
    bad_rated: dict[str, int] = defaultdict(int)
    for t in tickets:
        lc = to_local(t.created_at)
        lr = to_local(t.resolved_at)
        if lc and lc.date() >= start:
            created[lc.strftime("%m-%d")] += 1
        if lr and lr.date() >= start:
            resolved[lr.strftime("%m-%d")] += 1
    rating_by_ticket = {r.ticket_id: r for r in ratings}
    for t in tickets:
        r = rating_by_ticket.get(t.id)
        # 差评（≤2 星）按工单解决日期归桶
        if r and r.stars <= 2 and t.resolved_at:
            lr = to_local(t.resolved_at)
            if lr and lr.date() >= start:
                bad_rated[lr.strftime("%m-%d")] += 1
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%m-%d")
        out.append({
            "date": d,
            "created": created.get(d, 0),
            "resolved": resolved.get(d, 0),
            "bad_rated": bad_rated.get(d, 0),  # v2.12 差评数
        })
    return out


def by_category(db: Session) -> list[dict]:
    counter: dict[str, int] = defaultdict(int)
    for t in db.scalars(select(Ticket)):
        counter[t.category] += 1
    return [{"name": k, "value": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])]


def by_priority(db: Session) -> list[dict]:
    counter: dict[str, int] = defaultdict(int)
    for t in db.scalars(select(Ticket)):
        counter[t.priority] += 1
    return [{"name": PRIORITY_LABELS.get(p, p), "value": counter.get(p, 0)} for p in PRIORITY_LABELS]


def by_engineer(db: Session) -> list[dict]:
    engineers = list(db.scalars(select(User).where(User.role.in_(("admin", "engineer")))))
    tickets = list(db.scalars(select(Ticket)))
    ratings = {r.ticket_id: r.stars for r in db.scalars(select(Rating))}
    out = []
    for e in engineers:
        mine = [t for t in tickets if t.assignee_id == e.id]
        resolved = [t for t in mine if t.resolved_at]
        resp = [_minutes(t.created_at, t.first_responded_at) for t in mine if t.first_responded_at]
        res = [_minutes(t.created_at, t.resolved_at) for t in resolved]
        star_list = [ratings[t.id] for t in resolved if t.id in ratings]
        out.append(
            {
                "id": e.id,
                "name": e.name or e.username,
                "assigned": len(mine),
                "open": sum(1 for t in mine if t.status in ("pending", "processing", "pending_confirm")),
                "resolved": len(resolved),
                "avg_response_minutes": round(sum(resp) / len(resp), 1) if resp else None,
                "avg_resolution_minutes": round(sum(res) / len(res), 1) if res else None,
                "avg_stars": round(sum(star_list) / len(star_list), 2) if star_list else None,
            }
        )
    return sorted(out, key=lambda x: -x["resolved"])
