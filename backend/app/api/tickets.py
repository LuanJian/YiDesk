"""工单 API：列表、详情、建单、评论、流转、派单、评价。"""
from __future__ import annotations

from fastapi import Request, APIRouter, Body, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_optional_user, require_admin
from app.models.database import create_session, get_db
from app.models.ticket import (
    STATUS_APPROVAL,
    STATUS_CLOSED,
    STATUS_CONFIRM,
    STATUS_LABELS,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_RESOLVED,
    Ticket,
    TicketEvent,
)
from app.core.config import get_config
from app.models.user import User
from app.schemas.common import (
    AssignIn,
    BatchAssignIn,
    BatchIdsIn,
    MergeIn,
    RatingIn,
    SlaSuspendIn,
    TicketCommentIn,
    TicketCreate,
    TicketEditIn,
    TicketTransitionIn,
)
from app.services import classify_service, notify_service, ticket_service

router = APIRouter()


def _page(items: list, page: int, page_size: int) -> dict:
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": [i.to_dict() for i in items[start : start + page_size]],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("")
def list_tickets(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    assignee_id: int | None = None,
    creator_id: int | None = None,
    mine: bool = False,
    followed: bool = False,
    urgent: bool = False,
    pool: bool = False,
    pool_minutes: int | None = None,
    transferred: bool = False,
    period: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Ticket).order_by(Ticket.id.desc())
    if mine:
        # v2.12 修复：「自建工单」语义统一为本人创建（此前工程师视角错用指派给我）
        stmt = stmt.where(Ticket.creator_id == user.id)
    if user.role == "employee":
        # v2.8 部门管理员（员工）：可看本部门全部工单；普通员工只看自己的
        if user.dept_admin and user.department:
            dept_ids = select(User.id).where(User.department == user.department)
            stmt = stmt.where(
                (Ticket.creator_id.in_(dept_ids)) | (Ticket.requester_id == user.id) | (Ticket.creator_id == user.id)
            )
        else:
            stmt = stmt.where(Ticket.creator_id == user.id)
    # v2.1 类目数据权限：工程师只看授权类目（管理员不限）
    # 第二十七批+：待受理未指派单不按类目过滤——「其他员工无法转给该工程师，只能由其自行转入」的认领入口
    if user.role == "engineer":
        scope = user.category_scope_list
        if scope:
            stmt = stmt.where(
                or_(Ticket.category.in_(scope), and_(Ticket.status == "pending", Ticket.assignee_id.is_(None)))
            )
    if followed:
        from app.models.ticket import TicketFollower

        stmt = stmt.where(
            Ticket.id.in_(select(TicketFollower.ticket_id).where(TicketFollower.user_id == user.id))
        )
    if urgent:
        # 加急工单池（v2.12）：他人的（含未指派）加急单，且超 30 分钟未解决（未指派恒可见）
        from app.services.ticket_service import urgent_queue_visible

        stmt = stmt.where(
            Ticket.urgent.is_(True),
            Ticket.status.in_(("pending", "processing", "pending_confirm")),
            (Ticket.assignee_id != user.id) | Ticket.assignee_id.is_(None),
        )
        rows = [t for t in db.scalars(stmt).all() if urgent_queue_visible(db, t)]
        return _page(rows, max(1, page), min(page_size, 100))
    if pool and user.role in ("admin", "engineer"):
        # v2.7 工单公海：未指派的未结工单（待审批单不属于公海，仍在审批流）
        stmt = stmt.where(
            Ticket.assignee_id.is_(None),
            Ticket.status.in_(("pending", "processing", "pending_confirm")),
        )
        if pool_minutes and pool_minutes > 0:
            # v2.11 接单广场：只展示超过 N 分钟仍未分配的工单
            from datetime import timedelta

            from app.models.user import utcnow

            stmt = stmt.where(Ticket.created_at <= utcnow() - timedelta(minutes=pool_minutes))
    if transferred:
        # v2.9 转交工单：曾被改派/认领到当前处理人名下（未关闭的单）
        stmt = stmt.where(Ticket.transferred.is_(True), Ticket.status != "closed")
    if period == "open":
        # v2.9 「待处理中」快捷页签：未结工单
        stmt = stmt.where(Ticket.status.in_(("pending", "processing", "pending_confirm")))
    elif period == "done":
        # 「完结工单」：已解决 + 已关闭
        stmt = stmt.where(Ticket.status.in_(("resolved", "closed")))
    if status:
        stmt = stmt.where(Ticket.status == status)
    if category:
        stmt = stmt.where(Ticket.category == category)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if assignee_id:
        stmt = stmt.where(Ticket.assignee_id == assignee_id)
    if creator_id and user.role in ("admin", "engineer"):
        # 第二十七批+：点击发起人查看其当前未完结工单（仅管理台角色）
        stmt = stmt.where(Ticket.creator_id == creator_id)
    if q:
        like = f"%{q}%"
        # v2.11 搜索覆盖发起人姓名/用户名（工单管理搜索框检索发起人）
        creator_ids = select(User.id).where(or_(User.name.contains(like), User.username.contains(like)))
        stmt = stmt.where(
            or_(
                Ticket.title.contains(like),
                Ticket.description.contains(like),
                Ticket.no.contains(like),
                Ticket.solution.contains(like),            # v2.7 搜索覆盖解决方案
                Ticket.custom_fields.contains(like),       # v2.7 覆盖自定义字段（JSON 文本）
                Ticket.creator_id.in_(creator_ids),
            )
        )
    tickets = list(db.scalars(stmt).all())
    return _page(tickets, max(1, page), min(page_size, 100))


@router.get("/templates/by-category")
def templates_by_category(category: str, db: Session = Depends(get_db), _: User | None = Depends(get_optional_user)):
    """按分类取启用的工单模板（建单表单动态字段用；v2.11 放宽支持匿名扫码建单）。"""
    """按分类取启用的工单模板（建单表单动态字段用，全员可读）。"""
    from app.models.system import TicketTemplate

    ts = list(
        db.scalars(
            select(TicketTemplate).where(TicketTemplate.category == category, TicketTemplate.enabled.is_(True))
        )
    )
    return {"items": [t.to_dict() for t in ts]}


_track_attempts: dict = {}
_TRACK_LIMIT = 30  # 每来源每分钟最多 30 次查询（防查询码爆破）


@router.get("/track")
def track_anonymous_ticket(
    request: Request,
    no: str = Query(..., description="工单编号"),
    code: str = Query(..., description="提交时返回的 6 位查询码"),
    db: Session = Depends(get_db),
):
    """v2.12 匿名工单跟进：凭 工单号+查询码 查询进度（公开接口，仅返回提交人可见信息）。"""
    import json as _json

    # v2.12 简单内存限流（防查询码爆破）；进程重启清零可接受
    import time as _time

    client_ip = request.client.host if request.client else "unknown"
    now_ts = _time.time()
    attempts = [t for t in _track_attempts.get(client_ip, []) if now_ts - t < 60.0]
    if len(attempts) >= _TRACK_LIMIT:
        raise HTTPException(status_code=429, detail="查询过于频繁，请稍后再试")
    attempts.append(now_ts)
    _track_attempts[client_ip] = attempts

    t = db.scalar(select(Ticket).where(Ticket.no == no.strip().upper()))
    if not t:
        raise HTTPException(status_code=404, detail="工单不存在")
    cf = _json.loads(t.custom_fields or "{}")
    if not cf.get("follow_code") or cf["follow_code"] != code.strip().upper():
        raise HTTPException(status_code=403, detail="查询码不正确")
    events = [
        {
            "type": e.type,
            "actor": (e.actor.name or e.actor.username) if e.actor else "系统",
            "content": e.content,
            "created_at": e.created_at.isoformat(),
        }
        for e in sorted(t.events, key=lambda x: x.id)
    ]
    return {
        "no": t.no,
        "title": t.title,
        "status": t.status,
        "status_label": STATUS_LABELS.get(t.status, t.status),
        "created_at": t.created_at.isoformat(),
        "events": events,
        "rating": ({"stars": t.rating.stars} if t.rating else None),
    }


@router.post("", status_code=201)
async def create_ticket(
    body: TicketCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    from app.services import qr_service, v12_service

    # v2.11 匿名扫码提交：位置码/指定派单码允许匿名
    if user is None and not body.qr_code:
        raise HTTPException(status_code=401, detail="未登录，请先登录后再提交工单")

    # 扫码建单：解析标签，覆盖 分类/资产/描述/custom_fields（防客户端伪造）
    overrides, tag = ({}, None)
    if body.qr_code:
        tag = qr_service.resolve_tag(db, body.qr_code)
        if not tag:
            raise HTTPException(status_code=400, detail="二维码无效或已停用")
        if tag.kind == "room":
            raise HTTPException(status_code=400, detail="会议室码用于预约管理，请通过扫码页预约（如需报修请描述问题后直接提交）")
        # v2.12 设备码/会议室码需登录后提交（位置码/指定派单码允许匿名）
        if user is None and tag.kind in ("device", "room"):
            raise HTTPException(status_code=401, detail="该二维码需员工登录后提交，请先登录")
        if user is None:
            user = qr_service.get_or_create_anonymous_user(db)
        overrides = qr_service.build_overrides(
            db, tag,
            category=body.category,
            description=body.description,
            custom_fields=body.custom_fields,
        )

    # v2.12 软件安装申请：从软件目录选择 → 快照进 custom_fields（服务端校验，防伪造）
    custom_fields = overrides.get("custom_fields", body.custom_fields)
    software_snapshot = None
    if body.software_id:
        from app.models.ledger import SoftwareItem

        sw = db.get(SoftwareItem, body.software_id)
        if not sw:
            raise HTTPException(status_code=400, detail="所选软件不在软件目录中")
        software_snapshot = {
            "id": sw.id, "name": sw.name, "category": sw.category,
            "license_type": sw.license_type, "source_type": sw.source_type, "source_url": sw.source_url,
        }
        custom_fields = dict(custom_fields or {})
        custom_fields["software"] = software_snapshot

    try:
        ticket = ticket_service.create_ticket(
            db, creator=user,
            title=body.title,
            description=overrides.get("description", body.description),
            category=overrides.get("category", body.category),
            priority=body.priority,
            asset_id=overrides.get("asset_id", body.asset_id),
            channel="web",
            custom_fields=custom_fields,
            requester_id=body.requester_id,
            impact=body.impact,
            urgency=body.urgency,
        )
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    # 指定派单码 → 强制指派（不可用则回退自动分派）；关键词规则命中 → 直派/改判分类；否则走智能分派
    # 第二十七批+：「其他问题」分类延迟分派——15 分钟内不做任何指派（挂接单广场可被认领），超时由定时任务按负载/顺序分配
    # 第四十批：指定派单码优先于延迟分派——用户明确指定了处理人，无论分类是否「其他问题」都直接派给该工程师
    deferred = ticket.category == "其他问题" and ticket.is_open and not (tag and tag.kind == "assignee")
    auto_name: str | None = None
    kw_rule = None
    if tag and tag.kind == "assignee":
        qr_service.apply_forced_assign(db, tag, ticket)
        auto_name = ticket.assignee.name if ticket.assignee else None
    elif deferred:
        db.add(TicketEvent(
            ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
            content="延迟分派：「其他问题」工单 15 分钟内暂不指派（已在接单广场，可被工程师认领），超时将按当前负载自动分配",
        ))
        db.commit()
    else:
        kw_rule = v12_service.match_keyword_rule(db, ticket)
        kw_engineer = None
        if kw_rule and kw_rule.target_engineer_id:
            eng = db.get(User, kw_rule.target_engineer_id)
            if eng and eng.role in ("admin", "engineer") and eng.is_active and (eng.status or "on_duty") != "leave":
                try:
                    ticket_service.assign_ticket(
                        db, ticket=ticket, actor=eng, engineer=eng,
                        reason=f"关键词命中直派：规则「{kw_rule.name or kw_rule.keywords}」",
                    )
                    kw_engineer = eng
                    db.add(TicketEvent(
                        ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
                        content=f"关键词命中直派：规则「{kw_rule.name or kw_rule.keywords}」→ {eng.name or eng.username}",
                    ))
                    db.commit()
                except ticket_service.TransitionError:
                    kw_engineer = None
            if kw_engineer is None:
                db.add(TicketEvent(
                    ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
                    content=f"关键词命中：规则「{kw_rule.name or kw_rule.keywords}」目标工程师不可用，回退智能分派",
                ))
                db.commit()
        elif kw_rule and kw_rule.target_category and ticket.category != kw_rule.target_category:
            db.add(TicketEvent(
                ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
                content=f"关键词命中改判分类：{ticket.category} → {kw_rule.target_category}（规则「{kw_rule.name}」）",
            ))
            ticket.category = kw_rule.target_category
            db.commit()
            db.refresh(ticket)
        # 第二十七批+：扫码建单（位置码/设备码）默认派给现场运维（qr_ops_type，管理员/远程工程师可自行转入）；
        # 指定派单码已 apply_forced_assign 直派绑定工程师，不经过自动分派
        qr_ops = (get_config().dispatch.qr_ops_type or None) if tag else None
        engineer = kw_engineer or v12_service.auto_assign(db, ticket, ops_override=qr_ops)
        auto_name = engineer.name if engineer else None
    # 第二十四批+：同一员工未完结的「软件安装」工单自动合并——避免多名工程师分别远程安装同一员工
    # （匿名用户除外：匿名账号共享无法区分人，自动合并会错误合并陌生人的申请）
    merged_into = None
    # 仅针对**软件安装申请**（带 software 关联：目录内 software_id 或列表外 custom_fields.software）；
    # 普通的软件故障报修（同分类但无软件关联）不参与合并
    _is_sw_apply = bool(body.software_id) or bool((body.custom_fields or {}).get("software"))
    if ticket.category == "软件安装" and _is_sw_apply and user.username != "__anonymous__" and ticket.is_open:
        open_statuses = ("pending", "processing", "pending_confirm", "pending_approval")
        open_same = db.scalar(
            select(Ticket).where(
                Ticket.creator_id == user.id,
                Ticket.category == "软件安装",
                Ticket.status.in_(open_statuses),
                Ticket.id != ticket.id,
                Ticket.merged_into_id.is_(None),
            ).order_by(Ticket.id)
        )
        if open_same:
            import json as _json

            ticket.merged_into_id = open_same.id
            # 主单追加软件清单（software_list），时间线留痕
            cf = _json.loads(open_same.custom_fields or "{}")
            lst = list(cf.get("software_list") or [])
            if cf.get("software") and cf["software"] not in lst:
                lst.append(cf["software"])
            try:
                new_cf = _json.loads(ticket.custom_fields or "{}")
                if new_cf.get("software") and new_cf["software"] not in lst:
                    lst.append(new_cf["software"])
            except Exception:
                pass
            if lst:
                cf["software_list"] = lst
            if open_same.is_open:
                # 第二十八批+：源单保持待受理，随主工单一并转出/完结（不立即关闭）
                ticket.status = "pending"
                ticket.resolved_at = None
                ticket.closed_at = None
                db.add(TicketEvent(
                    ticket_id=ticket.id, actor_id=user.id, type=TicketEvent.TYPE_SYSTEM,
                    content=f"已并入主工单 {open_same.no}（将随其一并转出与完结）",
                ))
                db.add(TicketEvent(
                    ticket_id=open_same.id, actor_id=user.id, type=TicketEvent.TYPE_SYSTEM,
                    content=f"追加软件安装申请：{ticket.title}（源单 {ticket.no} 随本单处理）",
                ))
            else:
                # 主工单已完结：源单同步关闭（无处理人可跟随）
                from datetime import datetime as _dt

                now = _dt.now()
                ticket.status = STATUS_CLOSED
                ticket.closed_at = now
                if ticket.resolved_at is None:
                    ticket.resolved_at = now
                db.add(TicketEvent(
                    ticket_id=ticket.id, actor_id=user.id, type=TicketEvent.TYPE_TRANSITION,
                    from_status="pending", to_status=STATUS_CLOSED,
                    content=f"并入 {open_same.no}（主工单已完结，同步关闭）",
                ))
                db.add(TicketEvent(
                    ticket_id=open_same.id, actor_id=user.id, type=TicketEvent.TYPE_SYSTEM,
                    content=f"追加软件安装申请：{ticket.title}（主工单已完结，源单 {ticket.no} 同步关闭）",
                ))
            open_same.custom_fields = _json.dumps(cf, ensure_ascii=False)
            db.commit()
            db.refresh(ticket)
            merged_into = {"id": open_same.id, "no": open_same.no}
    if not merged_into:
        notify_service.notify_ticket_created(db, ticket, user)
        await notify_service.flush_async()
    # v2.12 匿名提交生成 6 位查询码：提交人凭 工单号+查询码 在扫码页跟进进度
    follow_code = None
    if user.username == "__anonymous__":
        import secrets as _secrets
        import json as _json

        follow_code = "".join(_secrets.choice("23456789ABCDEFGHJKMNPQRSTUVWXYZ") for _ in range(6))
        cf = _json.loads(ticket.custom_fields or "{}")
        cf["follow_code"] = follow_code
        ticket.custom_fields = _json.dumps(cf, ensure_ascii=False)
        db.commit()
    d = ticket.to_dict()
    if follow_code:
        d["follow_code"] = follow_code
    if deferred:
        d["deferred"] = True
    if merged_into:
        d["merged_into"] = merged_into
    d["available_actions"] = _available_actions(ticket, user)
    d["auto_assigned"] = auto_name
    d["qr_code"] = tag.code if tag else None
    d["similar_tickets"] = v12_service.find_similar_tickets(db, ticket)
    # v2.10 合并提醒：同一员工 15 分钟内多次扫码提交 → 提示可合并到原工单（避免重复单）
    if tag:
        from datetime import timedelta

        from app.models.user import utcnow

        recent = db.scalar(
            select(Ticket).where(
                Ticket.creator_id == user.id,
                Ticket.id != ticket.id,
                Ticket.status.in_(("pending", "processing", "pending_confirm")),
                Ticket.created_at >= utcnow() - timedelta(minutes=15),
                func.json_extract(Ticket.custom_fields, "$.qr_code") == tag.code,
            ).order_by(Ticket.id.desc())
        )
        if recent:
            d["recent_ticket"] = {"id": recent.id, "no": recent.no, "title": recent.title}
    return d


@router.post("/batch-assign")
def batch_assign(
    body: BatchAssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """第三十七批：批量指派（工单管理页签仅管理员）。逐单复用单张指派校验，返回成功/失败明细。"""
    engineer = db.get(User, body.engineer_id)
    if not engineer or engineer.role not in ("admin", "engineer") or not engineer.is_active:
        raise HTTPException(status_code=400, detail="目标人员无效或已停用")
    ok: list[dict] = []
    failed: list[dict] = []
    for tid in body.ticket_ids:
        t = db.get(Ticket, tid)
        if not t:
            failed.append({"id": tid, "no": "", "reason": "工单不存在"})
            continue
        if t.merged_into_id:
            failed.append({"id": tid, "no": t.no, "reason": "已并入主工单，请在主工单上转出"})
            continue
        if not t.is_open:
            failed.append({"id": tid, "no": t.no, "reason": "工单已结束"})
            continue
        try:
            ticket_service.assign_ticket(db, ticket=t, actor=user, engineer=engineer, reason=body.reason)
            ok.append({"id": tid, "no": t.no})
        except ticket_service.TransitionError as exc:
            failed.append({"id": tid, "no": t.no, "reason": exc.message})
    return {"assigned": len(ok), "failed": failed}


@router.post("/batch-close")
def batch_close(
    body: BatchIdsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """第三十七批：批量关闭（管理员）。pending/resolved 可关，processing 需先受理完结；源单跳过。"""
    ok: list[dict] = []
    failed: list[dict] = []
    for tid in body.ticket_ids:
        t = db.get(Ticket, tid)
        if not t:
            failed.append({"id": tid, "no": "", "reason": "工单不存在"})
            continue
        if t.merged_into_id:
            failed.append({"id": tid, "no": t.no, "reason": "已并入主工单，随主工单完结"})
            continue
        try:
            ticket_service.apply_transition(db, ticket=t, action="close", actor=user, note="管理员批量关闭")
            ok.append({"id": tid, "no": t.no})
        except ticket_service.TransitionError as exc:
            failed.append({"id": tid, "no": t.no, "reason": exc.message})
    return {"closed": len(ok), "failed": failed}


@router.get("/classify-suggest")
def classify_suggest(
    title: str = "",
    description: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """第三十八批：智能分类建议（TF-IDF 本地方案，人工复核兜底）——Top3 分类+置信度与优先级初判。"""
    return classify_service.suggest(db, title, description)


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    d = ticket.to_dict()
    d["events"] = [e.to_dict() for e in ticket.events]
    d["rating"] = ({"stars": ticket.rating.stars, "comment": ticket.rating.comment} if ticket.rating else None)
    d["available_actions"] = _available_actions(ticket, user)
    return d


@router.patch("/{ticket_id}")
def edit_ticket(
    ticket_id: int,
    body: TicketEditIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """v2.0 编辑工单：标题/描述/优先级（发起人限待受理，工程师/管理员限未结）。"""
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    try:
        ticket_service.edit_ticket(
            db, ticket=ticket, actor=user,
            title=body.title, description=body.description, priority=body.priority,
        )
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    d = ticket.to_dict()
    d["available_actions"] = _available_actions(ticket, user)
    # 第二十七批+：完结合并组内任一工单时，提醒同组还有未完结的合并工单（避免工程师遗漏）
    if ticket.merged_into_id or ticket.status in (STATUS_RESOLVED, STATUS_CLOSED):
        root = ticket.merged_into_id or ticket.id
        members = db.scalars(
            select(Ticket).where(or_(Ticket.id == root, Ticket.merged_into_id == root))
        ).all()
        pending = [m.no for m in members if m.id != ticket.id and m.is_open]
        if pending:
            d["pending_merged"] = pending
    return d


# ---- SLA 挂起 / 解挂（v2.0，仅工程师/管理员） ----

@router.post("/{ticket_id}/sla-suspend")
async def sla_suspend(
    ticket_id: int,
    body: SlaSuspendIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    try:
        ev = ticket_service.suspend_sla(db, ticket=ticket, actor=user, note=body.note)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    notify_service.notify_transition(db, ticket, ev.content)
    await notify_service.flush_async()
    d = ticket.to_dict()
    d["available_actions"] = _available_actions(ticket, user)
    return d


@router.post("/{ticket_id}/sla-resume")
async def sla_resume(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    try:
        ev = ticket_service.resume_sla(db, ticket=ticket, actor=user)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    notify_service.notify_transition(db, ticket, ev.content)
    await notify_service.flush_async()
    d = ticket.to_dict()
    d["available_actions"] = _available_actions(ticket, user)
    return d


# ---- 工单关注（v2.0，仅工程师/管理员） ----

@router.post("/{ticket_id}/follow")
def follow(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    try:
        ticket_service.follow_ticket(db, ticket=ticket, actor=user)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    return {"ok": True}


@router.post("/{ticket_id}/unfollow")
def unfollow(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    ticket_service.unfollow_ticket(db, ticket=ticket, actor=user)
    return {"ok": True}


@router.get("/{ticket_id}/merge-candidates")
def merge_candidates(
    ticket_id: int,
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """v2.0 搜索合并候选：按关键词/工单号搜未结工单（排除自身与已并入的）。"""
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403, detail="仅工程师/管理员可以合并工单")
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    stmt = select(Ticket).where(
        Ticket.id != ticket.id,
        Ticket.merged_into_id.is_(None),
        Ticket.status.in_((STATUS_PENDING, STATUS_PROCESSING, STATUS_CONFIRM)),
    )
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Ticket.title.contains(like), Ticket.no.contains(like), Ticket.description.contains(like)))
    rows = list(db.scalars(stmt.order_by(Ticket.id.desc()).limit(10)))
    return {
        "items": [
            {"id": t.id, "no": t.no, "title": t.title, "category": t.category,
             "status": t.status, "status_label": STATUS_LABELS.get(t.status, t.status)}
            for t in rows
        ]
    }


@router.post("/{ticket_id}/escalate")
async def escalate(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """员工加急（v2.6）：推送处理人；处理人排队 >2 单时广播其他工程师（可一键转办）。"""
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    try:
        result = ticket_service.escalate_ticket(db, ticket=ticket, actor=user)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    d = ticket.to_dict()
    d["queue_ahead"] = result["queue_ahead"]
    d["broadcast"] = result["broadcast"]
    # ① 推送当前处理人
    if ticket.assignee_id:
        assignee = db.get(User, ticket.assignee_id)
        if assignee:
            notify_service.enqueue_for_user(
                db, assignee, ticket_id=ticket.id, kind="urgent",
                title=f"加急提醒 {ticket.no}",
                content=f"员工对工单「{ticket.title}」发起加急，请尽快处理。",
                url=notify_service.ticket_url(ticket.id),
            )
    # ② 排队 >2 单（或未指派）→ 广播其他工程师（可转办认领）
    if result["broadcast"]:
        targets = ticket_service.broadcast_targets(db, ticket, exclude_actor=user)
        notify_service.enqueue_for_users(
            db, targets, ticket_id=ticket.id, kind="urgent",
            title=f"加急工单可转办 {ticket.no}",
            content=f"工单「{ticket.title}」被员工加急，处理人当前排队较多，可在工单台一键转办认领。",
            url=notify_service.ticket_url(ticket.id),
        )
    await notify_service.flush_async()
    return d


@router.post("/{ticket_id}/claim")
def claim_urgent(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """一键认领（v2.7 扩展）：加急工单转办 或 接单广场（未指派）工单认领到自己名下。"""
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403, detail="仅工程师/管理员可以认领")
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    if not ticket.is_open:
        raise HTTPException(status_code=400, detail="工单已结束")
    if ticket.assignee_id == user.id:
        raise HTTPException(status_code=400, detail="该工单已在您名下")
    is_pool = ticket.assignee_id is None  # 接单广场认领（未指派）
    if not is_pool and not ticket.urgent:
        raise HTTPException(status_code=400, detail="仅加急工单或接单广场工单支持一键认领")
    # 第二十八批+：合并源单不可单独认领——认领主工单将同步全部关联工单
    if ticket.merged_into_id:
        root = db.get(Ticket, ticket.merged_into_id)
        raise HTTPException(status_code=400, detail=f"该工单已并入主工单 {root.no if root else ''}，请认领主工单（将同步全部关联工单）")
    prev_name = ticket.assignee.name or ticket.assignee.username if ticket.assignee else None
    try:
        if is_pool:
            ticket_service.assign_ticket(db, ticket=ticket, actor=user, engineer=user, reason="认领接单广场工单")
            # v2.11 接单广场认领 = 转给自己处理，与改派同样计入「转交工单」
            ticket.transferred = True
            db.commit()
            db.refresh(ticket)
            # 第二十八批+：主工单认领时，全部关联源单一并转给同一工程师
            for m in db.scalars(select(Ticket).where(Ticket.merged_into_id == ticket.id, Ticket.status != STATUS_CLOSED)).all():
                try:
                    ticket_service.assign_ticket(db, ticket=m, actor=user, engineer=user, reason=f"随主工单 {ticket.no} 一并转出")
                except ticket_service.TransitionError:
                    db.rollback()
        else:
            ticket_service.assign_ticket(
                db, ticket=ticket, actor=user, engineer=user,
                reason=(f"认领加急工单（原处理人 {prev_name}）" if prev_name else "认领加急工单"),
            )
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    # 通知发起人：工单已被接手
    if ticket.creator_id and ticket.creator_id != user.id:
        creator = db.get(User, ticket.creator_id)
        if creator:
            notify_service.enqueue_for_user(
                db, creator, ticket_id=ticket.id,
                title=f"工单已接手 {ticket.no}",
                content=f"您的工单「{ticket.title}」已由 {user.name or user.username} 认领处理。",
                url=notify_service.ticket_url(ticket.id),
            )
    notify_service.flush(db)
    d = ticket.to_dict()
    d["available_actions"] = _available_actions(ticket, user)
    return d


def _available_actions(ticket: Ticket, user: User) -> list[str]:
    """根据状态与角色计算可执行操作（前端按钮渲染依据）。"""
    staff = user.role in ("admin", "engineer")
    is_creator = user.id == ticket.creator_id
    actions: list[str] = []
    # 合并源单：转出/完结/评价全部收敛到主工单（级联同步），不提供任何单独动作
    if ticket.merged_into_id:
        return []
    s = ticket.status
    if s == STATUS_PENDING and staff:
        actions.append("accept")
    if s == STATUS_PENDING and is_creator:
        actions.append("cancel")
    if s == STATUS_APPROVAL and is_creator:
        actions.append("cancel")  # 待审批单发起人可撤回
    if s == STATUS_PROCESSING and staff:
        # v2.12 工程师处理完直接完结（解决方案+反馈处理结果一次性填写），不再单独提交方案
        actions.append("finish")
    # v2.12 接单广场操作列移除后，未指派工单的认领入口统一放详情页
    if ticket.assignee_id is None and staff and s in (STATUS_PENDING, STATUS_PROCESSING):
        actions.append("claim")
    if s == STATUS_CONFIRM and is_creator:
        actions.append("confirm_resolved")
        actions.append("reject_solution")
    # 管理员也可确认解决（创建人已含该动作时去重，避免按钮重复）
    if s == STATUS_CONFIRM and user.role == "admin" and "confirm_resolved" not in actions:
        actions.append("confirm_resolved")
    if s == STATUS_RESOLVED and (is_creator or user.role == "admin"):
        actions.append("close")  # v2.11 关单仅发起人/管理员
    if s == STATUS_PENDING and user.role == "admin":
        actions.append("close")
    if s in (STATUS_CLOSED, STATUS_RESOLVED) and (is_creator or user.role == "admin"):
        actions.append("reopen")
    if s == STATUS_APPROVAL and user.role == "admin":
        actions.append("approve")
        actions.append("reject")
    return actions


@router.post("/{ticket_id}/comment")
async def comment(
    ticket_id: int,
    body: TicketCommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    ev = ticket_service.add_comment(db, ticket=ticket, actor=user, content=body.content)
    # 评论提醒对方
    other_id = ticket.creator_id if user.id == ticket.creator_id else ticket.assignee_id
    if other_id and other_id != user.id:
        other = db.get(User, other_id)
        if other:
            notify_service.enqueue_for_user(
                db, other, ticket_id=ticket.id,
                title=f"工单 {ticket.no} 有新评论",
                content=f"{user.name or user.username}：{body.content[:200]}",
                url=notify_service.ticket_url(ticket.id),
            )
            await notify_service.flush_async()
    return ev.to_dict()


@router.patch("/{ticket_id}/comments/{event_id}")
async def edit_comment(
    ticket_id: int,
    event_id: int,
    body: TicketCommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """v2.12 编辑评论：仅评论作者或管理员；编辑后在时间线标注「已修改」。"""
    ev = db.get(TicketEvent, event_id)
    if not ev or ev.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail="评论不存在")
    if ev.type != TicketEvent.TYPE_COMMENT:
        raise HTTPException(status_code=400, detail="仅评论可以编辑")
    if user.role != "admin" and ev.actor_id != user.id:
        raise HTTPException(status_code=403, detail="只有评论作者或管理员可以编辑")
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="评论内容不能为空")
    ev.content = content[:2000]
    ev.edited = True
    db.commit()
    db.refresh(ev)
    return ev.to_dict()


@router.post("/{ticket_id}/transition")
async def transition(
    ticket_id: int,
    body: TicketTransitionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    assignee = None
    if body.action == "accept" and ticket.assignee_id and ticket.assignee_id != user.id:
        assignee = db.get(User, ticket.assignee_id)  # 已派单的单子，接单不改处理人
    # 第二十八批+：合并源单的流转统一在主工单上操作（随其转出与完结）
    if ticket.merged_into_id:
        root = db.get(Ticket, ticket.merged_into_id)
        raise HTTPException(status_code=400, detail=f"该工单已并入主工单 {root.no if root else ''}，请在主工单上操作（将同步全部关联工单）")
    try:
        ev = ticket_service.apply_transition(db, ticket=ticket, action=body.action, actor=user, note=body.note, solution=body.solution, assignee=assignee)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    notify_service.notify_transition(db, ticket, ev.content)
    # 第二十八批+：主工单完结时，全部关联源单一并完结（员工只需处理/评价一次）
    if ev.to_status in (STATUS_RESOLVED, STATUS_CLOSED):
        for m in db.scalars(select(Ticket).where(Ticket.merged_into_id == ticket.id, Ticket.status != STATUS_CLOSED)).all():
            from datetime import datetime as _dt

            m.status = STATUS_CLOSED
            m.closed_at = _dt.now()
            if m.resolved_at is None:
                m.resolved_at = m.closed_at
            db.add(TicketEvent(
                ticket_id=m.id, actor_id=user.id, type=TicketEvent.TYPE_SYSTEM,
                content=f"随主工单 {ticket.no} 完结，同步关闭",
            ))
    # 第二十七批+：合并源单不发评价卡——员工只需评价一次（在合并主工单上）
    if ev.to_status == STATUS_RESOLVED and not ticket.merged_into_id:
        notify_service.request_rating(db, ticket)
    await notify_service.flush_async()
    d = ticket.to_dict()
    d["available_actions"] = _available_actions(ticket, user)
    return d


@router.post("/{ticket_id}/assign")
async def assign(
    ticket_id: int,
    body: AssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    # 第二十八批+：合并源单不可单独转出——在主工单上转出将同步全部关联工单
    if ticket.merged_into_id:
        root = db.get(Ticket, ticket.merged_into_id)
        raise HTTPException(status_code=400, detail=f"该工单已并入主工单 {root.no if root else ''}，请在主工单上转出（将同步全部关联工单）")
    engineer = db.get(User, body.engineer_id or user.id)
    if not engineer:
        raise HTTPException(status_code=404, detail="工程师不存在")
    try:
        ticket_service.assign_ticket(db, ticket=ticket, actor=user, engineer=engineer, reason=body.reason)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    # 第二十八批+：主工单转出时，全部关联源单一并转出给同一工程师
    for m in db.scalars(select(Ticket).where(Ticket.merged_into_id == ticket.id, Ticket.status != STATUS_CLOSED)).all():
        try:
            ticket_service.assign_ticket(db, ticket=m, actor=user, engineer=engineer, reason=f"随主工单 {ticket.no} 一并转出")
        except ticket_service.TransitionError:
            db.rollback()
    notify_service.notify_transition(db, ticket, f"已指派给 {engineer.name or engineer.username}")
    await notify_service.flush_async()
    d = ticket.to_dict()
    d["available_actions"] = _available_actions(ticket, user)
    return d


@router.get("/{ticket_id}/similar")
def similar_tickets(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services import v12_service

    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    return {"items": v12_service.find_similar_tickets(db, ticket)}


@router.get("/{ticket_id}/knowledge-suggestions")
def knowledge_suggestions(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services import v12_service

    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    return {"items": v12_service.suggest_knowledge(db, ticket)}


@router.post("/{ticket_id}/merge")
async def merge_ticket(
    ticket_id: int,
    body: MergeIn,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    from app.services import qr_service, v12_service

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    target = db.get(Ticket, body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标工单不存在")
    if user is None:
        # v2.11 匿名合并：仅限系统匿名用户创建、同一二维码下的重复单（源单更晚）
        import json as _json

        def _qr_code_of(t: Ticket) -> str | None:
            try:
                return (_json.loads(t.custom_fields or "{}") or {}).get("qr_code")
            except Exception:  # noqa: BLE001
                return None

        anon = db.scalar(select(User).where(User.username == qr_service.ANON_USERNAME))
        code_src, code_tgt = _qr_code_of(ticket), _qr_code_of(target)
        if not (
            anon
            and ticket.creator_id == target.creator_id == anon.id
            and code_src
            and code_src == code_tgt
            and ticket.id > target.id
        ):
            raise HTTPException(status_code=401, detail="请先登录后再操作工单")
        user = anon  # 以系统匿名用户身份执行合并（两单共同创建人，service 权限校验可通过）
    # v2.10 员工可合并自己的重复扫码单（两单同为本人创建且目标更早）；其余仍限 IT 侧
    elif user.role not in ("admin", "engineer") and not (
        user.id == ticket.creator_id == target.creator_id and ticket.id > target.id
    ):
        raise HTTPException(status_code=403, detail="仅工程师/管理员或重复单的创建人可以合并工单")
    try:
        v12_service.merge_ticket(db, source=ticket, target=target, actor=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await notify_service.flush_async()
    return {"ok": True, "merged_into": {"id": target.id, "no": target.no}}


@router.post("/{ticket_id}/urge")
async def urge(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    try:
        ev = ticket_service.urge_ticket(db, ticket=ticket, actor=user)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    # 催办通知：处理人（未指派则通知全部工程师）
    targets = []
    if ticket.assignee_id:
        assignee = db.get(User, ticket.assignee_id)
        if assignee:
            targets.append(assignee)
    else:
        targets = notify_service.staff_users(db)
    notify_service.enqueue_for_users(
        db, targets, ticket_id=ticket.id, kind="urge",
        title=f"催办 {ticket.no}",
        content=f"工单「{ticket.title}」被催办，请尽快处理。",
        url=notify_service.ticket_url(ticket.id),
    )
    await notify_service.flush_async()
    return {"ok": True}


@router.post("/{ticket_id}/rating")
async def rating(
    ticket_id: int,
    body: RatingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或无权查看")
    # 第二十七批+：合并源单不可评价——员工只需在合并主工单评价一次
    if ticket.merged_into_id:
        raise HTTPException(status_code=400, detail="该工单已并入主工单，请在主工单中评价一次即可")
    try:
        ticket_service.rate_ticket(db, ticket=ticket, user=user, stars=body.stars, comment=body.comment)
    except ticket_service.TransitionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    await notify_service.flush_async()
    return {"ok": True}
