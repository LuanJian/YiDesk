"""v1.2 服务集：智能分派、相似识别与合并、知识库推荐、每日日报。"""
from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.models.knowledge import KnowledgeArticle
from app.models.system import DeptRoute, DispatchRule, DutyRule, KeywordRule
from app.models.ticket import STATUS_CLOSED, Ticket, TicketEvent
from app.models.user import User, utcnow

logger = logging.getLogger("services.v12")

# ---------- 智能分派 ----------

def _duty_engineer_ids(db: Session) -> list[int]:
    # 值班表按服务器本地日历（公司时区），不用 UTC
    today = datetime.now().weekday()
    rule = db.scalar(select(DutyRule).where(DutyRule.weekday == today))
    return rule.engineer_ids_list if rule else []


def _rule_engineer_ids(db: Session, ticket: Ticket) -> list[int]:
    """分类规则工程师（v2.7：组织架构路由优先——提单部门命中 DeptRoute 时以部门路由为准）。"""
    from zoneinfo import ZoneInfo  # noqa: F401 占位避免顶层循环导入

    if ticket.creator_id and ticket.creator and ticket.creator.department:
        route = db.scalar(
            select(DeptRoute).where(
                DeptRoute.department == ticket.creator.department, DeptRoute.enabled.is_(True)
            )
        )
        if route and route.engineer_ids_list:
            return route.engineer_ids_list

    rule = db.scalar(select(DispatchRule).where(DispatchRule.category == ticket.category, DispatchRule.enabled.is_(True)))
    if rule:
        return rule.engineer_ids_list
    return []


def match_keyword_rule(db: Session, ticket: Ticket):
    """关键词规则匹配（v2.7）：标题/描述命中启用规则关键词 → 按 priority 取最优先一条。"""
    rules = list(
        db.scalars(select(KeywordRule).where(KeywordRule.enabled.is_(True)).order_by(KeywordRule.priority, KeywordRule.id))
    )
    if not rules:
        return None
    haystack = f"{ticket.title or ''}\n{ticket.description or ''}"
    for rule in rules:
        for kw in rule.keyword_list:
            if kw and kw in haystack:
                return rule
    return None


def _long_task_ok(db: Session, engineer_id: int, ticket: Ticket) -> bool:
    """长耗时隔离 + 打散（v2.7）。非长耗时工单恒通过。

    - 隔离：该工程师名下有「未结且预估时长 ≥ long_task_minutes」的工单 → 暂出候选池
    - 打散：当日已被派长耗时单达 max_long_tasks_per_day → 不再接长耗时单
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    cfg = get_config().dispatch
    if not ticket.estimated_minutes or ticket.estimated_minutes < cfg.long_task_minutes:
        return True
    busy = db.scalar(
        select(Ticket.id).where(
            Ticket.assignee_id == engineer_id,
            Ticket.status.in_(("pending", "processing", "pending_confirm")),
            Ticket.estimated_minutes >= cfg.long_task_minutes,
        )
    )
    if busy:
        return False
    today_start = _dt.now(_ZI("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0)
    utc_start = today_start.astimezone(_ZI("UTC")).replace(tzinfo=None)
    long_today = db.scalar(
        select(Ticket.id).where(
            Ticket.assignee_id == engineer_id,
            Ticket.estimated_minutes >= cfg.long_task_minutes,
            Ticket.created_at >= utc_start,
        )
    )
    if long_today:
        return False
    return True


def _open_counts_by_assignee(db: Session) -> dict[int, int]:
    """每个处理人当前未结工单数（负载），供粘性派单超载判断。"""
    rows = list(
        db.scalars(
            select(Ticket.assignee_id).where(
                Ticket.status.in_(("pending", "processing", "pending_confirm")),
                Ticket.assignee_id.is_not(None),
            )
        )
    )
    counts: dict[int, int] = {}
    for a in rows:
        if a:
            counts[a] = counts.get(a, 0) + 1
    return counts


def _open_counts_by_category(db: Session, category: str) -> dict[int, int]:
    """该分类下各处理人未结单数（粘性选人只看同类目负载）。"""
    rows = list(
        db.scalars(
            select(Ticket.assignee_id).where(
                Ticket.category == category,
                Ticket.status.in_(("pending", "processing", "pending_confirm")),
                Ticket.assignee_id.is_not(None),
            )
        )
    )
    counts: dict[int, int] = {}
    for a in rows:
        if a:
            counts[a] = counts.get(a, 0) + 1
    return counts


def _norm(values: dict[int, float]) -> dict[int, float]:
    """池内 min-max 归一化到 [0,1]；全相等或单元素 → 全 0。"""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi <= lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def _engineer_metrics(db: Session, engineer_ids: list[int], window_days: int) -> dict[int, dict]:
    """近 N 天绩效样本：样本数、平均解决小时（剔除挂起）、满意度、被催率、重开率。"""
    from datetime import timedelta

    from sqlalchemy import func

    from app.models.ticket import Rating, TicketEvent
    from app.models.user import utcnow

    ids = [i for i in engineer_ids if i]
    if not ids:
        return {}
    since = utcnow() - timedelta(days=window_days)
    metrics: dict[int, dict] = {i: {"samples": 0, "avg_hours": 0.0, "sat": 0.0, "urge_rate": 0.0, "reopen_rate": 0.0} for i in ids}
    tickets = list(
        db.scalars(
            select(Ticket).where(
                Ticket.assignee_id.in_(ids),
                Ticket.created_at >= since,
                Ticket.status.in_((STATUS_CLOSED, "resolved")),
            )
        )
    )
    # 结案总数（分母）与完成质量（分子）
    done_count: dict[int, int] = {i: 0 for i in ids}
    ok_count: dict[int, int] = {i: 0 for i in ids}
    hours: dict[int, list[float]] = {i: [] for i in ids}
    star_sum: dict[int, float] = {i: 0.0 for i in ids}
    star_cnt: dict[int, int] = {i: 0 for i in ids}
    urge_cnt: dict[int, int] = {i: 0 for i in ids}
    reopen_cnt: dict[int, int] = {i: 0 for i in ids}

    for t in tickets:
        a = t.assignee_id
        done_count[a] = done_count.get(a, 0) + 1
        # 重开过的单：存在「已解决/已关闭 → 处理中」的流转
        reopened = any(
            e.from_status in ("resolved", "closed") and e.to_status == "processing"
            for e in t.events
        )
        if reopened:
            reopen_cnt[a] = reopen_cnt.get(a, 0) + 1
        else:
            ok_count[a] = ok_count.get(a, 0) + 1
        if t.resolved_at and t.created_at:
            total_min = (t.resolved_at - t.created_at).total_seconds() / 60
            total_min -= (t.sla_suspended_total or 0)  # 剔除挂起时长
            hours[a].append(max(total_min, 0) / 60.0)
        if t.rating:
            star_sum[a] += t.rating.stars
            star_cnt[a] += 1
        urge_cnt[a] += sum(1 for e in t.events if e.type == TicketEvent.TYPE_URGE)

    for i in ids:
        m = metrics[i]
        m["samples"] = done_count.get(i, 0)
        m["avg_hours"] = (sum(hours[i]) / len(hours[i])) if hours.get(i) else 0.0
        m["sat"] = (star_sum[i] / star_cnt[i]) if star_cnt.get(i) else 0.0
        m["urge_rate"] = (urge_cnt[i] / done_count[i]) if done_count.get(i) else 0.0
        m["reopen_rate"] = (reopen_cnt[i] / done_count[i]) if done_count.get(i) else 0.0
    return metrics


def _pick_weighted(db: Session, pool: set[int], open_counts: dict[int, int]) -> User | None:
    """算法派单（v2.1）：池内样本充足的工程师按负载+绩效加权打分，取最高分。

    score = W_close*完结率 + W_speed*(1-归一化时长) + W_sat*(满意度/5)
            - W_load*归一化未结 - W_urge*归一化被催率 - W_reopen*归一化重开率
    样本 < min_samples 的工程师不参与（全员样本不足则返回 None 退回轮询）。
    """
    cfg = get_config().dispatch
    metrics = _engineer_metrics(db, list(pool), cfg.window_days)
    eligible = [i for i, m in metrics.items() if m["samples"] >= cfg.min_samples]
    if not eligible:
        return None
    w = cfg.weights
    avg_hours = _norm({i: metrics[i]["avg_hours"] for i in eligible})
    loads = _norm({i: float(open_counts.get(i, 0)) for i in eligible})
    urges = _norm({i: metrics[i]["urge_rate"] for i in eligible})
    reopens = _norm({i: metrics[i]["reopen_rate"] for i in eligible})
    # v2.8 SLA 紧迫度：处理人名下未结单的最小剩余解决时间（分钟，越少越紧急）
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    sla_urgent_min: dict[int, float] = {}
    for i in eligible:
        remaining = [
            (t.sla_resolve_deadline - utcnow()).total_seconds() / 60
            for t in db.scalars(
                select(Ticket).where(
                    Ticket.assignee_id == i,
                    Ticket.status.in_(("pending", "processing", "pending_confirm")),
                    Ticket.sla_resolve_deadline.is_not(None),
                )
            )
        ]
        positive = [r for r in remaining if r > 0]
        sla_urgent_min[i] = min(positive) if positive else 60 * 24 * 7  # 无紧迫单视为一周后
    sla_norm = _norm(sla_urgent_min)
    scores: dict[int, float] = {}
    for i in eligible:
        m = metrics[i]
        scores[i] = (
            w.close * (1.0 - m["reopen_rate"])  # 完结率=未重开占比
            + w.speed * (1.0 - avg_hours[i])
            + w.sat * (m["sat"] / 5.0)
            - w.load * loads[i]
            - w.urge * urges[i]
            - w.reopen * reopens[i]
            - w.sla_urgent * sla_norm[i]  # 名下 SLA 越紧迫，扣越多
        )
    top = max(scores, key=lambda k: scores[k])
    engineer = db.get(User, top)
    if engineer and engineer.role in ("admin", "engineer") and engineer.is_active:
        return engineer
    return None


def pick_assignee(db: Session, ticket: Ticket, ops_override: str | None = None) -> User | None:
    """自动指派选人（v2.7 完整链路，ops_override=扫码单强制岗位覆盖分类映射）：

    候选池构建：分类规则/部门路由 ∪ 当日值班
      → 请假过滤 → 类目权限过滤 → 岗位路由过滤 → 长耗时隔离/打散过滤
      → 严格值班模式（非当班剔除，池空回退全量）
    选人顺序：同类粘性（池内）→ 算法加权（weighted 模式）→ 轮询（当班优先）。
    各级过滤后池空则自动回退上一级，绝不因过滤导致无单可派。
    """
    cfg = get_config().dispatch
    ids = _rule_engineer_ids(db, ticket)
    if not ids:
        ids = _duty_engineer_ids(db)
    duty = set(_duty_engineer_ids(db))
    pool = set(ids) | duty
    # v2.1 类目数据权限 + v2.7 请假过滤
    pool = {
        i
        for i in pool
        if (u := db.get(User, i))
        and u.role in ("admin", "engineer")
        and u.is_active
        and (u.status or "on_duty") != "leave"
        and u.in_category_scope(ticket.category)
    }
    if not pool:
        return None
    # v2.4 岗位路由：映射命中的分类只派对应岗位（池空回退不限岗位）
    # 第二十七批+：扫码建单强制岗位（qr_ops_type）优先于分类映射
    mapped_type = ops_override or cfg.ops_type_map.get(ticket.category)
    if mapped_type:
        scoped = {i for i in pool if (db.get(User, i).ops_type or "other") == mapped_type}
        pool = scoped or pool
    # v2.7 严格值班：非当班剔除（池空回退全量）
    if cfg.strict_duty and duty:
        on_duty_pool = pool & duty
        if on_duty_pool:
            pool = on_duty_pool

    # v2.7 长耗时隔离/打散：先筛出可用候选，全被隔离则回退不过滤（避免任务滞留）
    long_ok = {i for i in pool if _long_task_ok(db, i, ticket)}
    pool_for_pick = long_ok or pool

    if cfg.sticky_same_category:
        per_cat = _open_counts_by_category(db, ticket.category)
        cand = {e: per_cat.get(e, 0) for e in pool_for_pick if per_cat.get(e, 0) > 0}
        if cand:
            top = max(cand, key=lambda k: cand[k])
            if _open_counts_by_assignee(db).get(top, 0) <= cfg.max_open:
                engineer = db.get(User, top)
                if engineer and engineer.role in ("admin", "engineer") and engineer.is_active:
                    return engineer

    open_counts = _open_counts_by_assignee(db)
    if cfg.mode == "weighted":
        engineer = _pick_weighted(db, pool_for_pick, open_counts)
        if engineer:
            return engineer

    ordered = [i for i in ids if i in pool_for_pick]
    if not ordered:
        ordered = sorted(pool_for_pick)
    if not ordered:
        return None
    ordered = [i for i in ordered if i in duty] + [i for i in ordered if i not in duty]
    target_id = ordered[ticket.id % len(ordered)]
    engineer = db.get(User, target_id)
    if engineer and engineer.role in ("admin", "engineer") and engineer.is_active:
        return engineer
    return None


def auto_assign(db: Session, ticket: Ticket, ops_override: str | None = None) -> User | None:
    """建单后自动指派（dispatch.auto_assign 开启且尚未指派时；待审批单不派）。

    ops_override：扫码建单（位置码/设备码）强制岗位，覆盖分类映射（第二十七批+）。"""
    from app.models.ticket import STATUS_APPROVAL

    cfg = get_config().dispatch
    if not cfg.auto_assign or ticket.assignee_id or not ticket.is_open or ticket.status == STATUS_APPROVAL:
        return None
    engineer = pick_assignee(db, ticket, ops_override)
    if not engineer:
        return None
    from app.services import ticket_service

    # 系统自动行为：以指派对象本人为 actor，绕过"仅工程师可派单"的入口校验
    ticket_service.assign_ticket(db, ticket=ticket, actor=engineer, engineer=engineer)
    # 事件标注为智能分派（assign_ticket 已写指派事件，这里补充来源说明）
    ev = TicketEvent(
        ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
        content=f"智能分派：按分类规则/值班表自动指派给 {engineer.name or engineer.username}",
    )
    db.add(ev)
    db.commit()
    db.refresh(ticket)
    return engineer


# ---------- 相似识别与合并 ----------

def find_similar_tickets(db: Session, ticket: Ticket, limit: int = 3) -> list[dict]:
    """开放状态、同分类、标题相似的工单（difflib 相似度 > 0.6）。"""
    if not ticket.title:
        return []
    candidates = list(
        db.scalars(
            select(Ticket).where(
                Ticket.category == ticket.category,
                Ticket.status.in_(("pending", "processing", "pending_confirm")),
            )
        )
    )
    out = []
    for t in candidates:
        if t.id == ticket.id:
            continue
        ratio = difflib.SequenceMatcher(None, ticket.title, t.title).ratio()
        if ratio >= 0.6:
            out.append((ratio, t))
    out.sort(key=lambda x: -x[0])
    return [
        {"id": t.id, "no": t.no, "title": t.title, "status": t.status, "similarity": round(r, 2)}
        for r, t in out[:limit]
    ]


def assign_deferred(db: Session, ticket: Ticket) -> User | None:
    """「其他问题」延迟分派（第二十七批+）：

    建单 15 分钟内不做任何指派（挂接单广场，工程师可主动认领）；
    超时由定时任务调用本函数：
      - 若所有在职工程师均无未结工单 → 按工程师顺序（id）依次轮询分配；
      - 否则派给当前未结工单最少的工程师（并列取顺序靠前者）。
    """
    from app.services import ticket_service

    engineers = [
        u for u in db.scalars(
            select(User).where(
                User.role == "engineer",
                User.is_active.is_(True),
                User.status == "on_duty",
            ).order_by(User.id)
        ).all()
    ]
    if not engineers:
        return None
    loads: dict[int, int] = {}
    for e in engineers:
        loads[e.id] = db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assignee_id == e.id,
                Ticket.status.in_(("pending", "processing", "pending_confirm", "pending_approval")),
            )
        ) or 0
    if all(v == 0 for v in loads.values()):
        # 全员空闲：按工程师顺序依次逐个分配
        target = engineers[ticket.id % len(engineers)]
    else:
        target = min(engineers, key=lambda e: (loads[e.id], e.id))
    # 系统行为：以指派对象本人为 actor
    ticket_service.assign_ticket(db, ticket=ticket, actor=target, engineer=target)
    db.add(TicketEvent(
        ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
        content=f"延迟分派：「其他问题」工单超时未认领，按当前负载自动指派给 {target.name or target.username}（当前未结 {loads[target.id]} 单）",
    ))
    db.commit()
    db.refresh(ticket)
    return target


def merge_ticket(db: Session, *, source: Ticket, target: Ticket, actor: User) -> None:
    """把 source 并入 target：source 关闭并标记 merged_into_id。"""
    if actor.role not in ("admin", "engineer"):
        # v2.10 员工合并自己的重复扫码单：必须是两单的共同创建人，且目标单更早
        if not (
            actor.id == source.creator_id == target.creator_id
            and source.id > target.id
        ):
            raise ValueError("仅工程师/管理员或重复单的创建人可以合并工单")
    if source.id == target.id:
        raise ValueError("不能合并到自身")
    if not source.is_open:
        raise ValueError("源工单已关闭，无需合并")
    from app.models.ticket import STATUS_APPROVAL

    if source.status == STATUS_APPROVAL:
        raise ValueError("待审批工单不能合并，请先完成审批")
    if target.merged_into_id:
        raise ValueError("目标工单自身已被合并，请合并到主工单")

    now = utcnow()
    source.status = STATUS_CLOSED
    source.merged_into_id = target.id
    source.closed_at = now
    if source.resolved_at is None:
        source.resolved_at = now
    db.add(TicketEvent(
        ticket_id=source.id, actor_id=actor.id, type=TicketEvent.TYPE_TRANSITION,
        from_status="pending", to_status=STATUS_CLOSED,
        content=f"合并至 {target.no}（{target.title}）",
    ))
    db.add(TicketEvent(
        ticket_id=target.id, actor_id=actor.id, type=TicketEvent.TYPE_SYSTEM,
        content=f"工单 {source.no}（{source.title}）并入本单",
    ))
    db.commit()
    db.refresh(source)


# ---------- 知识库推荐 ----------

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}")


def _keywords(title: str) -> list[str]:
    """朴素关键词：连续中文 2+ 字串与英文数字词（重叠切分 2/3 字窗口，控制数量）。"""
    raw = _TOKEN_RE.findall(title or "")
    words: list[str] = []
    for seg in raw:
        words.append(seg)
        if len(seg) > 2 and not seg.isascii():
            words += [seg[i : i + 2] for i in range(len(seg) - 1)]
    seen: list[str] = []
    for w in words:
        if w not in seen and len(w) >= 2:
            seen.append(w)
    return seen[:12]


def suggest_knowledge(db: Session, ticket: Ticket, limit: int = 3) -> list[dict]:
    """按标题关键词命中知识库标题/标签，返回推荐文章。"""
    kws = _keywords(ticket.title)
    if not kws:
        return []
    articles = list(db.scalars(select(KnowledgeArticle)).all())
    scored = []
    for a in articles:
        haystack = f"{a.title} {a.tags}"
        hit = sum(1 for w in kws if w in haystack)
        if hit:
            scored.append((hit, a))
    scored.sort(key=lambda x: -x[0])
    return [{"id": a.id, "title": a.title, "category": a.category} for _, a in scored[:limit]]


# ---------- 每日日报 ----------

def build_daily_report(db: Session) -> str:
    from sqlalchemy import func

    from app.models.ticket import Rating

    now = utcnow()
    yesterday = (now - timedelta(days=1)).date()
    tickets = list(db.scalars(select(Ticket)).all())

    created = [t for t in tickets if t.created_at and t.created_at.date() == yesterday]
    resolved = [t for t in tickets if t.resolved_at and t.resolved_at.date() == yesterday]
    open_now = [t for t in tickets if t.is_open]
    overdue = [t for t in open_now if t.sla_resolve_deadline and t.sla_resolve_deadline < now]

    cat_count: dict[str, int] = {}
    for t in created:
        cat_count[t.category] = cat_count.get(t.category, 0) + 1
    top_cat = max(cat_count.items(), key=lambda x: x[1])[0] if cat_count else "无"

    stars = [r.stars for r in db.scalars(select(Rating)).all() if r.created_at and r.created_at.date() == yesterday]
    rating_txt = f"{sum(stars) / len(stars):.1f} 星（{len(stars)} 条评价）" if stars else "暂无"

    lines = [
        "📊 IT 工单日报",
        f"日期：{yesterday:%Y-%m-%d}",
        f"昨日新建 {len(created)} 单 / 解决 {len(resolved)} 单",
        f"当前未结 {len(open_now)} 单（其中超期 {len(overdue)} 单）",
        f"昨日最集中分类：{top_cat}",
        f"昨日满意度：{rating_txt}",
    ]
    return "\n".join(lines)


def send_daily_report(db: Session) -> None:
    from app.services import notify_service

    text = build_daily_report(db)
    staff = notify_service.staff_users(db)
    for u in staff:
        notify_service.enqueue_for_user(
            db, u, ticket_id=None, title="每日工单日报", content=text,
            url=f"{get_config().public_base_url.rstrip('/')}/dashboard",
        )
    notify_service.flush(db)

    webhook = get_config().report.dingtalk_group_webhook
    if webhook:
        _post_group_webhook(webhook, text)


def _post_group_webhook(webhook: str, text: str) -> None:
    """钉钉群机器人播报（仅放行官方域名，防 SSRF）。"""
    from urllib.parse import urlparse

    p = urlparse(webhook)
    host = p.hostname or ""
    if p.scheme != "https" or not (host == "dingtalk.com" or host.endswith(".dingtalk.com")):
        logger.warning("日报群播报 webhook 非官方域名，已跳过")
        return
    try:
        resp = httpx.post(
            webhook, json={"msgtype": "markdown",
                           "markdown": {"title": "IT 工单日报", "text": text.replace("\n", "\n\n")}},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        logger.exception("日报群播报失败")
