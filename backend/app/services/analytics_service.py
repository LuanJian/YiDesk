"""数据看板聚合服务（v2.3）：日期区间 + 日/月/年粒度的工单分析。

沿用「Python 内存聚合」模式（内网数据量小）；口径：
- 新建按 created_at、解决按 resolved_at 归属区间
- 解决时长剔除 SLA 挂起累计（sla_suspended_total），待审批单不计入时效分母
- 满意度仅已评价单；环比 = 上一等长区间
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket import PRIORITY_LABELS, Rating, Ticket, TicketEvent
from app.models.user import User, utcnow

# 高频关键词的通用停用词（保守清单，保留设备/业务名词）
STOPWORDS = {
    "工单", "问题", "处理", "解决", "使用", "人员", "希望", "麻烦", "一下", "现在",
    "今天", "老师", "领导", "同事", "帮忙", "出现", "进行", "可以", "需要", "情况",
}


def _parse_day(s: str | None, fallback_days: int, bound: str) -> datetime:
    """YYYY-MM-DD → 当日 00:00（start）或次日 00:00（end）datetime；缺省回退近 N 天。

    日期口径按公司时区 Asia/Shanghai（库内时间为 UTC），否则早 8 点前默认区间会错分昨天。
    返回值必须是 datetime——summary 筛选与 t.resolved_at 等 datetime 比较，返回 date 会 TypeError。
    """
    from fastapi import HTTPException

    from zoneinfo import ZoneInfo

    try:
        d = datetime.strptime(s, "%Y-%m-%d") if s else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式应为 YYYY-MM-DD：{s}") from exc
    if not d:
        today = utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Shanghai")).date()
        d = datetime(today.year, today.month, today.day) - timedelta(days=fallback_days - 1) if bound == "start" else datetime(today.year, today.month, today.day)
    d0 = d if bound == "start" else d + timedelta(days=1)
    return datetime(d0.year, d0.month, d0.day)


def bucket_key(dt: datetime, granularity: str) -> str:
    """UTC 库内时间 → Asia/Shanghai 本地日期分桶（与导出口径一致）。

    week 用 ISO 周（周一起算），key 形如 2026-W46。
    """
    from zoneinfo import ZoneInfo

    if dt:
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Shanghai"))
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "year":
        return dt.strftime("%Y")
    if granularity == "week":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return dt.strftime("%Y-%m-%d")


def bucket_list(start: datetime, end: datetime, granularity: str) -> list[str]:
    """枚举区间内的所有桶（保证空桶也有 0 值）。"""
    out: list[str] = []
    if granularity == "year":
        for y in range(start.year, end.year + 1):
            out.append(f"{y}")
    elif granularity == "month":
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            out.append(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                y, m = y + 1, 1
    elif granularity == "week":
        cur = start.date()
        while cur <= end.date():
            k = bucket_key(datetime(cur.year, cur.month, cur.day), "week")
            if not out or out[-1] != k:
                out.append(k)
            cur += timedelta(days=1)
    else:
        cur = start.date()
        while cur <= end.date():
            out.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
    return out


def _pct(cur: float | None, prev: float | None) -> float | None:
    if prev in (None, 0) or cur is None:
        return None
    return round((cur - prev) / prev * 100, 1)


def _shift_month(d: datetime, months: int) -> datetime:
    """月份平移（跨年/月末天数自动裁剪）：1月31日 -1 月 → 去年 12 月 31 日；3月31日 -1 月 → 2月28日。"""
    import calendar

    y, m = d.year, d.month + months
    if m <= 0:
        y, m = y - 1, m + 12
    if m > 12:
        y, m = y + 1, m - 12
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def _with_prev(value, prev):
    change = None
    if isinstance(value, (int, float)) and isinstance(prev, (int, float)):
        change = _pct(value, prev)
    return {"value": value, "prev": prev, "change": change}


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _resolve_minutes(t: Ticket) -> float | None:
    """v2.12 接入工作日历：解决时长剔除非工作时间，再减 SLA 挂起时长。"""
    if not t.resolved_at or not t.created_at:
        return None
    from app.services.business_time import business_minutes_between

    minutes = float(business_minutes_between(t.created_at, t.resolved_at))
    return max(0.0, minutes - (t.sla_suspended_total or 0))


def _scope_ok(user: User, category: str) -> bool:
    if user.role != "engineer":
        return True
    scope = user.category_scope_list
    return not scope or category in scope


def dashboard(
    db: Session,
    *,
    user: User,
    start: datetime,
    end: datetime,
    granularity: str = "day",
    category: str | None = None,
    engineer_id: int | None = None,
    department: str | None = None,
) -> dict:
    span = end - start
    prev_start, prev_end = start - span, start

    def load(s: datetime, e: datetime, field: str = "created_at") -> list[Ticket]:
        """按归属字段（created_at/resolved_at）加载区间工单并套用筛选。"""
        col = Ticket.created_at if field == "created_at" else Ticket.resolved_at
        tickets = list(
            db.scalars(select(Ticket).where(col >= s, col < e, col.is_not(None)))
        )
        if category:
            tickets = [t for t in tickets if t.category == category]
        if engineer_id:
            tickets = [t for t in tickets if t.assignee_id == engineer_id]
        if department:
            tickets = [t for t in tickets if t.creator and t.creator.department == department]
        # v2.1 类目数据权限：工程师只能看授权类目范围
        return [t for t in tickets if _scope_ok(user, t.category)]

    tickets = load(start, end)                 # 新建口径（新建量/未结/超期/响应）
    resolved_tickets = load(start, end, "resolved_at")   # 解决口径（解决量/解决时效/SLA 达标）
    prev_tickets = load(prev_start, prev_end)
    prev_resolved = load(prev_start, prev_end, "resolved_at")
    ratings_all = {r.ticket_id: r for r in db.scalars(select(Rating))}

    now = utcnow()

    # ---- summary（含环比） ----
    def _summary_block(ts_created: list[Ticket], ts_resolved: list[Ticket], s: datetime, e: datetime, ratings_map) -> dict:
        resolved = [t for t in ts_resolved if t.resolved_at and s <= t.resolved_at < e]
        from app.services.business_time import business_minutes_between

        resp = [float(business_minutes_between(t.created_at, t.first_responded_at)) for t in ts_created
                if t.first_responded_at and t.created_at and t.status != "pending_approval"]
        res = [_resolve_minutes(t) for t in resolved if t.status != "pending_approval"]
        res = [v for v in res if v is not None]
        resp_breach = sum(1 for t in resolved if t.sla_response_deadline and t.first_responded_at and t.first_responded_at > t.sla_response_deadline)
        res_breach = sum(1 for t in resolved if t.sla_resolve_deadline and t.resolved_at > t.sla_resolve_deadline)
        rs = [ratings_map[t.id].stars for t in resolved if t.id in ratings_map]
        return {
            "created": len(ts_created),
            "resolved": len(resolved),
            "open": sum(1 for t in ts_created if t.is_open),
            "overdue": sum(1 for t in ts_created if t.is_open and t.sla_resolve_deadline and t.sla_resolve_deadline < now),
            "avg_response_minutes": _avg(resp),
            "avg_resolution_minutes": _avg(res),
            "response_sla_rate": round(100 * (1 - resp_breach / len(resolved)), 1) if resolved else None,
            "resolution_sla_rate": round(100 * (1 - res_breach / len(resolved)), 1) if resolved else None,
            "rating_avg": round(sum(rs) / len(rs), 2) if rs else None,
            "rating_count": len(rs),
        }

    cur_sum = _summary_block(tickets, resolved_tickets, start, end, ratings_all)
    prev_sum = _summary_block(prev_tickets, prev_resolved, prev_start, prev_end, ratings_all)
    # 第三十七批：同比对比——day/week 对上周同位置，month 对上一自然月同日起，year 对去年同月
    if granularity == "year":
        yoy_start = start.replace(year=start.year - 1)
    elif granularity == "month":
        yoy_start = _shift_month(start, -1)
    else:
        yoy_start = start - timedelta(days=7)
    yoy_end = yoy_start + (end - start)
    yoy_tickets = load(yoy_start, yoy_end)
    yoy_resolved = load(yoy_start, yoy_end, "resolved_at")
    yoy_sum = _summary_block(yoy_tickets, yoy_resolved, yoy_start, yoy_end, ratings_all)
    summary = {}
    for k, v in cur_sum.items():
        item = _with_prev(v, prev_sum[k])
        item["yoy"] = yoy_sum[k]
        item["yoy_change"] = _pct(v, yoy_sum[k]) if isinstance(v, (int, float)) and isinstance(yoy_sum[k], (int, float)) else None
        summary[k] = item

    # ---- trend（按粒度分桶） ----
    keys = bucket_list(start, end, granularity)
    created_b: dict[str, int] = defaultdict(int)
    resolved_b: dict[str, int] = defaultdict(int)
    res_minutes_b: dict[str, list[float]] = defaultdict(list)
    stars_b: dict[str, list[int]] = defaultdict(list)
    for t in tickets:
        if t.created_at:
            created_b[bucket_key(t.created_at, granularity)] += 1
    for t in resolved_tickets:
        k = bucket_key(t.resolved_at, granularity)
        resolved_b[k] += 1
        m = _resolve_minutes(t)
        if m is not None:
            res_minutes_b[k].append(m)
        if t.id in ratings_all:
            stars_b[k].append(ratings_all[t.id].stars)
    trend = [
        {
            "bucket": k,
            "created": created_b.get(k, 0),
            "resolved": resolved_b.get(k, 0),
            "avg_resolution_minutes": _avg(res_minutes_b.get(k, [])),
            "avg_stars": round(sum(stars_b[k]) / len(stars_b[k]), 2) if stars_b.get(k) else None,
        }
        for k in keys
    ]

    # ---- engineers（处理人工作量/时效/达标/满意度/重开率） ----
    def _reopen_count(t: Ticket) -> int:
        return sum(1 for e in t.events if e.from_status in ("resolved", "closed") and e.to_status == "processing")

    engineers_rows: dict[int, dict] = {}
    # 处理人行：新建口径（受理/未结）∪ 解决口径（解决/时效/满意度）——跨期解决的单也要计入
    for t in tickets:
        if not t.assignee_id:
            continue
        row = engineers_rows.setdefault(t.assignee_id, {
            "id": t.assignee_id, "name": t.assignee.name or t.assignee.username,
            "assigned": 0, "resolved": 0, "open": 0,
            "resp": [], "res": [], "stars": [], "reopened": 0, "resp_breach": 0, "res_breach": 0,
        })
        row["assigned"] += 1
        if t.is_open:
            row["open"] += 1
    for t in resolved_tickets:
        if not t.assignee_id:
            continue
        row = engineers_rows.setdefault(t.assignee_id, {
            "id": t.assignee_id, "name": t.assignee.name or t.assignee.username,
            "assigned": 0, "resolved": 0, "open": 0,
            "resp": [], "res": [], "stars": [], "reopened": 0, "resp_breach": 0, "res_breach": 0,
        })
        row["resolved"] += 1
        if t.first_responded_at and t.created_at:
            row["resp"].append((t.first_responded_at - t.created_at).total_seconds() / 60)
        if t.sla_response_deadline and t.first_responded_at and t.first_responded_at > t.sla_response_deadline:
            row["resp_breach"] += 1
        m = _resolve_minutes(t)
        if m is not None:
            row["res"].append(m)
        if t.sla_resolve_deadline and t.resolved_at > t.sla_resolve_deadline:
            row["res_breach"] += 1
        if t.id in ratings_all:
            row["stars"].append(ratings_all[t.id].stars)
        row["reopened"] += _reopen_count(t)
    engineers = []
    for row in engineers_rows.values():
        resolved_n = row["resolved"]
        engineers.append({
            "id": row["id"], "name": row["name"],
            "assigned": row["assigned"], "resolved": resolved_n, "open": row["open"],
            "avg_response_minutes": _avg(row["resp"]),
            "avg_resolution_minutes": _avg(row["res"]),
            "response_sla_rate": round(100 * (1 - row["resp_breach"] / resolved_n), 1) if resolved_n else None,
            "resolution_sla_rate": round(100 * (1 - row["res_breach"] / resolved_n), 1) if resolved_n else None,
            "avg_stars": round(sum(row["stars"]) / len(row["stars"]), 2) if row["stars"] else None,
            "rating_count": len(row["stars"]),
            "reopen_rate": round(100 * row["reopened"] / resolved_n, 1) if resolved_n else None,
        })
    engineers.sort(key=lambda x: -x["resolved"])

    # ---- satisfaction（星级分布 + 低分明细） ----
    dist = {str(i): 0 for i in range(1, 6)}
    low_list: list[dict] = []
    rated = [(t, ratings_all[t.id]) for t in resolved_tickets if t.id in ratings_all]
    for t, r in rated:
        dist[str(r.stars)] = dist.get(str(r.stars), 0) + 1
        if r.stars <= 2:
            low_list.append({
                "ticket_id": t.id, "no": t.no, "title": t.title, "stars": r.stars,
                "comment": r.comment, "assignee": (t.assignee.name or t.assignee.username) if t.assignee else None,
                "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
            })
    low_list.sort(key=lambda x: (x["stars"], x["no"]))
    satisfaction = {"distribution": dist, "total": len(rated), "low_list": low_list[:20]}

    # ---- hot_issues（分类占比 + 关键词 Top） ----
    cat_counter: dict[str, int] = defaultdict(int)
    for t in tickets:
        cat_counter[t.category] += 1
    total_created = len(tickets) or 1
    categories = [
        {"name": k, "value": v, "pct": round(100 * v / total_created, 1)}
        for k, v in sorted(cat_counter.items(), key=lambda x: -x[1])
    ]
    from app.services.v12_service import _keywords

    kw_counter: dict[str, int] = defaultdict(int)
    kw_samples: dict[str, list[int]] = defaultdict(list)
    for t in tickets:
        for w in _keywords(t.title):
            # 停用词过滤；丢弃 ≥4 字的全串（等价于整句标题，无聚类价值），保留 2-3 字窗口
            if w in STOPWORDS or len(w) > 3:
                continue
            kw_counter[w] += 1
            if len(kw_samples[w]) < 5:
                kw_samples[w].append(t.id)
    keywords = [
        {"keyword": w, "count": c, "pct": round(100 * c / total_created, 1), "sample_ids": kw_samples[w]}
        for w, c in sorted(kw_counter.items(), key=lambda x: -x[1])[:15]
    ]
    hot_issues = {"total": len(tickets), "categories": categories, "keywords": keywords}

    # ---- engineer_mix（处理人 × 分类构成，按解决量，含跨期解决单） ----
    mix: dict[int, dict] = {}
    for t in resolved_tickets:
        if not t.assignee_id:
            continue
        m = mix.setdefault(t.assignee_id, {"name": engineers_rows[t.assignee_id]["name"], "total": 0, "parts": defaultdict(int)})
        m["total"] += 1
        m["parts"][t.category] += 1
    engineer_mix = [
        {
            "id": eid, "name": m["name"], "total": m["total"],
            "parts": [{"category": c, "count": n, "pct": round(100 * n / m["total"], 1)} for c, n in sorted(m["parts"].items(), key=lambda x: -x[1])],
        }
        for eid, m in sorted(mix.items(), key=lambda kv: -kv[1]["total"])
    ]

    # ---- submitters（提单员工 Top10 + 部门汇总） ----
    emp_counter: dict[int, dict] = {}
    dept_counter: dict[str, int] = defaultdict(int)
    for t in tickets:
        c = emp_counter.setdefault(t.creator_id, {
            "id": t.creator_id, "name": t.creator.name or t.creator.username,
            "department": t.creator.department or "", "count": 0,
        })
        c["count"] += 1
        dept_counter[t.creator.department or "未填写"] += 1
    submitters = {
        "employees": sorted(emp_counter.values(), key=lambda x: -x["count"])[:10],
        "departments": [{"department": k, "count": v, "pct": round(100 * v / total_created, 1)}
                        for k, v in sorted(dept_counter.items(), key=lambda x: -x[1])[:10]],
    }

    return {
        "range": {"start": start.strftime("%Y-%m-%d"), "end": (end - timedelta(days=1)).strftime("%Y-%m-%d")},
        "granularity": granularity,
        "summary": summary,
        "trend": trend,
        "engineers": engineers,
        "satisfaction": satisfaction,
        "hot_issues": hot_issues,
        "engineer_mix": engineer_mix,
        "submitters": submitters,
        "priority_mix": [
            {"name": PRIORITY_LABELS.get(p, p), "value": sum(1 for t in tickets if t.priority == p)}
            for p in PRIORITY_LABELS
        ],
    }
