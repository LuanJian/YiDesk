"""工单领域服务：建单、状态机流转、评论、评价。

所有状态变更必须走 apply_transition，保证事件留痕与权限校验一致。

"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from sqlalchemy.orm import Session

from app.core.config import get_config

from app.models.system import SlaRule

from app.models.ticket import (

    ACTIONS,

    PRIORITIES,

    PRIORITY_LABELS,

    STATUS_CLOSED,

    STATUS_LABELS,

    STATUS_PENDING,

    STATUS_PROCESSING,

    STATUS_RESOLVED,

    Rating,

    Ticket,

    TicketEvent,

)

from app.models.user import User, utcnow

ACTION_LABELS = {

    "accept": "受理",

    "cancel": "撤销",

    "reject_solution": "退回",

    "confirm_resolved": "确认解决",

    "finish": "完结工单",

    "close": "关闭",

    "reopen": "重开",

    "approve": "审批通过",

    "reject": "审批驳回",

}

class TransitionError(Exception):

    """非法流转，message 直接展示给用户。"""

    def __init__(self, message: str):

        super().__init__(message)

        self.message = message

def get_sla_minutes(db: Session, priority: str) -> tuple[int, int]:

    """优先级对应 (响应时限, 解决时限)，单位分钟；无配置时回退 config 默认。"""

    rule = db.scalar(select(SlaRule).where(SlaRule.priority == priority))

    if rule:

        return rule.response_minutes, rule.resolve_minutes

    cfg = get_config().sla

    p = getattr(cfg, priority, None)

    return p.response_minutes, p.resolve_minutes

def validate_custom_fields(db: Session, category: str, custom_fields: dict) -> None:

    """v2.1 模板字段校验：可见性级联 + 必填（后端强制，防绕过前端）。

    隐藏字段带了值 → 400；可见的必填字段为空 → 400。无模板的分类跳过。

    """

    from app.models.system import TicketTemplate

    tpl = db.scalar(

        select(TicketTemplate).where(TicketTemplate.category == category, TicketTemplate.enabled.is_(True))

    )

    if not tpl:

        return

    import json as _json

    fields = _json.loads(tpl.fields or "[]")

    for f in fields:

        key = f.get("key")

        if not key:

            continue

        rule = f.get("visible_if") or {}

        ref_field, allowed = rule.get("field"), rule.get("in")

        visible = True

        if ref_field and isinstance(allowed, list):

            visible = custom_fields.get(ref_field) in allowed

        value = str(custom_fields.get(key) or "").strip()

        if not visible and value:

            raise TransitionError(f"字段「{f.get('label', key)}」在当前选择下不可见，不能提交其值")

        if visible and f.get("required") and not value:

            raise TransitionError(f"请填写「{f.get('label', key)}」")

def create_ticket(

    db: Session,

    *,

    creator: User,

    title: str,

    description: str = "",

    category: str = "其他",

    priority: str = "medium",

    asset_id: int | None = None,

    channel: str = "web",

    chat_id: str | None = None,

    custom_fields: dict | None = None,

    requester_id: int | None = None,

    validate_fields: bool = True,

    impact: str | None = None,

    urgency: str | None = None,

) -> Ticket:

    import json

    from app.services.business_time import add_business_minutes

    if priority not in PRIORITIES:

        raise TransitionError("无效的优先级")

    # v2.8 优先级矩阵：影响范围 × 紧急程度 → 自动计算优先级（覆盖手选值，防主观拔高）

    if impact and urgency:

        matrix = get_config().priority_matrix

        row = getattr(matrix, impact, None) if impact in ("company", "department", "individual") else None

        computed = (row or {}).get(urgency)

        if computed in PRIORITIES:

            priority = computed

    # v2.1 模板字段校验：级联可见性 + 必填（防绕过前端）；

    # IM 等无结构化表单的渠道传 validate_fields=False（无法填自定义字段，不做必填拦截）

    if validate_fields:

        validate_custom_fields(db, category or "其他", custom_fields or {})

    # v2.0 提出者：代报修时记录实际报修人（自己报自己 = 不设）

    requester: User | None = None

    if requester_id and requester_id != creator.id:

        requester = db.get(User, requester_id)

        if not requester:

            raise TransitionError("提出者用户不存在")

    now = utcnow()

    t = Ticket(

        title=title.strip(),

        description=description.strip(),

        category=category or "其他",

        priority=priority,

        creator_id=creator.id,

        requester_id=requester.id if requester else None,

        asset_id=asset_id,

        channel=channel,

        channel_chat_id=chat_id,

        custom_fields=json.dumps(custom_fields or {}, ensure_ascii=False),

        created_at=now,

        updated_at=now,

    )

    resp_m, res_m = get_sla_minutes(db, t.priority)

    # v2.2 审批节点：模板开启审批时先挂起在「待审批」，SLA 自审批通过起算

    from app.models.system import TicketTemplate

    from app.models.ticket import STATUS_APPROVAL

    tpl = db.scalar(

        select(TicketTemplate).where(TicketTemplate.category == t.category, TicketTemplate.enabled.is_(True))

    )

    needs_approval = bool(tpl and tpl.require_approval)

    if not needs_approval:

        t.sla_response_deadline = add_business_minutes(now, resp_m)

        t.sla_resolve_deadline = add_business_minutes(now, res_m)

    else:

        t.status = STATUS_APPROVAL

    # v2.7 预估时长快照（模板配置，长耗时隔离/打散依据）

    t.estimated_minutes = max(0, tpl.estimated_minutes or 0) if tpl else 0

    db.add(t)

    db.flush()

    # 编号格式 {级别}-{日期}-{序号}——A 低 / B 中 / C 高 / D 危急（按优先级）；

    # 序号 = 当日全局序（id - 当日首单 id，0000 起，id 单调无竞态）；超 9999 自动 5 位扩展

    _LEVEL = {"low": "A", "medium": "B", "high": "C", "urgent": "D"}

    from datetime import timezone as _tz_module

    from zoneinfo import ZoneInfo as _ZoneInfo

    _sh = _ZoneInfo("Asia/Shanghai")

    _day_start = now.replace(tzinfo=_tz_module.utc).astimezone(_sh).replace(hour=0, minute=0, second=0, microsecond=0)

    _day_start_utc = _day_start.astimezone(_tz_module.utc).replace(tzinfo=None)

    _first_id = db.scalar(select(func.min(Ticket.id)).where(Ticket.created_at >= _day_start_utc))

    _seq = t.id - (_first_id or t.id)

    # 日期统一取上海日期（与序号日界、统计口径一致）

    _now_sh = now.replace(tzinfo=_tz_module.utc).astimezone(_sh)

    # 编号查重重试——历史数据回拨 created_at 时公式序号可能撞号（如演示数据/迁移数据），递增避开

    for _ in range(50):

        _fmt = "05d" if _seq >= 10000 else "04d"

        candidate = f"{_LEVEL.get(t.priority, 'B')}-{_now_sh:%Y%m%d}-{_seq:{_fmt}}"

        if not db.scalar(select(Ticket.id).where(Ticket.no == candidate)):

            t.no = candidate

            break

        _seq += 1

    else:

        t.no = f"{_LEVEL.get(t.priority, 'B')}-{_now_sh:%Y%m%d}-{t.id}"  # 极端兜底：用 id 保证唯一

    content = "创建工单" + (f"（代 {requester.name or requester.username} 报修）" if requester else "")

    if needs_approval:

        content += "，等待主管审批"

    db.add(

        TicketEvent(

            ticket_id=t.id, actor_id=creator.id, type=TicketEvent.TYPE_CREATE,

            to_status=t.status, content=content,

        )

    )

    db.commit()

    db.refresh(t)

    _emit_webhook(db, "ticket.created", t)

    return t

def _emit_webhook(db: Session, event: str, ticket: Ticket) -> None:

    """v2.2 Webhook 事件出口：失败不影响主流程。"""

    try:

        from app.services import webhook_service

        webhook_service.emit_event(db, event, ticket)

    except Exception:  # noqa: BLE001

        import logging

        logging.getLogger("services.ticket").exception("webhook 事件发射失败 %s", event)

def edit_ticket(

    db: Session,

    *,

    ticket: Ticket,

    actor: User,

    title: str | None = None,

    description: str | None = None,

    priority: str | None = None,

) -> Ticket:

    """v2.0 工单编辑：员工可在受理前改自己的单，工程师/管理员随时可改未结单。

    逐字段留痕；优先级变化按新优先级重算 SLA 时限（从当前时刻起）。

    """

    staff = actor.role in ("admin", "engineer")

    if not staff and not (actor.id == ticket.creator_id and ticket.status == STATUS_PENDING):

        raise TransitionError("发起人只能在待受理状态下编辑自己的工单")

    if not ticket.is_open:

        raise TransitionError("已结束的工单不能编辑")

    changes: list[str] = []

    if title is not None and title.strip() and title.strip() != ticket.title:

        changes.append(f"标题「{ticket.title}」→「{title.strip()}」")

        ticket.title = title.strip()

    if description is not None and description.strip() != ticket.description:

        changes.append("更新了问题描述")

        ticket.description = description.strip()

    if priority is not None and priority in PRIORITIES and priority != ticket.priority:

        changes.append(f"优先级 {PRIORITY_LABELS.get(ticket.priority, ticket.priority)} → {PRIORITY_LABELS.get(priority, priority)}")

        ticket.priority = priority

        from app.services.business_time import add_business_minutes

        resp_m, res_m = get_sla_minutes(db, priority)

        now = utcnow()

        ticket.sla_response_deadline = add_business_minutes(now, resp_m)

        ticket.sla_resolve_deadline = add_business_minutes(now, res_m)

        ticket.sla_response_warned = False

        ticket.sla_resolve_warned = False

        ticket.sla_escalated = False

    if not changes:

        raise TransitionError("没有需要修改的内容")

    db.add(TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_SYSTEM,

        content="编辑工单：" + "；".join(changes),

    ))

    db.commit()

    db.refresh(ticket)

    _emit_webhook(db, "ticket.updated", ticket)

    return ticket

# ---- SLA 挂起 / 解挂（v2.0） ----

def suspend_sla(db: Session, *, ticket: Ticket, actor: User, note: str = "") -> TicketEvent:

    """挂起 SLA：快照剩余工作分钟，扫描/催单暂停；解挂时按剩余时间顺延。"""

    from app.services.business_time import business_minutes_between

    if actor.role not in ("admin", "engineer"):

        raise TransitionError("仅工程师/管理员可以挂起 SLA")

    if not ticket.is_open:

        raise TransitionError("已结束的工单无需挂起")

    if ticket.sla_suspended_at:

        raise TransitionError("工单已处于挂起状态")

    now = utcnow()

    ticket.sla_suspended_at = now

    ticket.sla_response_remaining = (

        business_minutes_between(now, ticket.sla_response_deadline)

        if ticket.sla_response_deadline and not ticket.first_responded_at else None

    )

    ticket.sla_resolve_remaining = (

        business_minutes_between(now, ticket.sla_resolve_deadline)

        if ticket.sla_resolve_deadline and not ticket.resolved_at else None

    )

    parts = []

    if ticket.sla_response_remaining is not None:

        parts.append(f"响应剩余 {ticket.sla_response_remaining} 分钟")

    if ticket.sla_resolve_remaining is not None:

        parts.append(f"解决剩余 {ticket.sla_resolve_remaining} 分钟")

    content = "SLA 挂起：暂停计时" + (f"（{'，'.join(parts)}）" if parts else "") + (f"：{note.strip()}" if note.strip() else "")

    ev = TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_SYSTEM, content=content,

    )

    db.add(ev)

    db.commit()

    db.refresh(ticket)

    return ev

def resume_sla(db: Session, *, ticket: Ticket, actor: User) -> TicketEvent:

    """解挂：按挂起时快照的剩余分钟，从当前时刻重算截止时间。"""

    from app.services.business_time import add_business_minutes

    if actor.role not in ("admin", "engineer"):

        raise TransitionError("仅工程师/管理员可以恢复 SLA")

    if not ticket.sla_suspended_at:

        raise TransitionError("工单未处于挂起状态")

    now = utcnow()

    if ticket.sla_response_remaining is not None:

        ticket.sla_response_deadline = add_business_minutes(now, ticket.sla_response_remaining)

    if ticket.sla_resolve_remaining is not None:

        ticket.sla_resolve_deadline = add_business_minutes(now, ticket.sla_resolve_remaining)

    # 累计挂起时长（自然分钟），供算法派单统计真实解决时长时剔除

    ticket.sla_suspended_total = (ticket.sla_suspended_total or 0) + int(

        (now - ticket.sla_suspended_at).total_seconds() // 60

    )

    ticket.sla_suspended_at = None

    ticket.sla_response_remaining = None

    ticket.sla_resolve_remaining = None

    ticket.sla_response_warned = False

    ticket.sla_resolve_warned = False

    ticket.sla_escalated = False

    ev = TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_SYSTEM,

        content="SLA 恢复：按剩余时间重新计时",

    )

    db.add(ev)

    db.commit()

    db.refresh(ticket)

    return ev

# ---- 工单关注（v2.0） ----

def follow_ticket(db: Session, *, ticket: Ticket, actor: User) -> None:

    if actor.role not in ("admin", "engineer"):

        raise TransitionError("仅工程师/管理员可以关注工单")

    from app.models.ticket import TicketFollower

    exists = db.scalar(

        select(TicketFollower.id).where(TicketFollower.ticket_id == ticket.id, TicketFollower.user_id == actor.id)

    )

    if exists:

        return  # 幂等

    db.add(TicketFollower(ticket_id=ticket.id, user_id=actor.id))

    db.commit()

def unfollow_ticket(db: Session, *, ticket: Ticket, actor: User) -> None:

    from app.models.ticket import TicketFollower

    row = db.scalar(

        select(TicketFollower).where(TicketFollower.ticket_id == ticket.id, TicketFollower.user_id == actor.id)

    )

    if row:

        db.delete(row)

        db.commit()

def follower_users(db: Session, ticket: Ticket) -> list[User]:

    from app.models.ticket import TicketFollower

    return [f.user for f in ticket.followers if f.user]

def _check_permission(action: str, ticket: Ticket, actor: User) -> None:

    staff = actor.role in ("admin", "engineer")

    is_creator = actor.id == ticket.creator_id

    if action == "accept" and not staff:

        raise TransitionError("仅工程师/管理员可以执行该操作")

    if action in ("approve", "reject") and actor.role != "admin":

        raise TransitionError("仅管理员可以审批")

    if action == "cancel" and not is_creator:

        raise TransitionError("只有发起人可以撤销工单")

    if action == "reject_solution" and not is_creator:

        raise TransitionError("只有发起人可以退回解决方案")

    if action == "confirm_resolved" and not (is_creator or actor.role == "admin"):

        raise TransitionError("只有发起人可以确认解决")

    if action == "close":

        # v2.11：关闭工单仅限发起人或管理员（工程师无主动关单权限）

        if not (is_creator or actor.role == "admin"):

            raise TransitionError("关闭工单仅限发起人或管理员")

        if is_creator and not staff and ticket.status == STATUS_PENDING:

            raise TransitionError("待受理工单请联系管理员或工程师关闭，或直接撤销")

    if action == "finish":

        # v2.12 工程师直接完结：处理完问题一次性归档解决方案并反馈提交人

        if not staff:

            raise TransitionError("仅工程师/管理员可以完结工单")

    if action == "reopen" and not (is_creator or staff):

        raise TransitionError("只有发起人或管理员可以重开工单")

def apply_transition(

    db: Session,

    *,

    ticket: Ticket,

    action: str,

    actor: User,

    note: str = "",

    solution: str = "",

    assignee: User | None = None,

) -> TicketEvent:

    mapping = ACTIONS.get(action)

    if not mapping:

        raise TransitionError(f"未知的操作: {action}")

    to_status = mapping.get(ticket.status)

    if to_status is None:

        raise TransitionError(f"当前状态「{STATUS_LABELS.get(ticket.status)}」不允许「{ACTION_LABELS.get(action, action)}」")

    _check_permission(action, ticket, actor)

    from_status = ticket.status

    ticket.status = to_status

    now = utcnow()

    approve_extra = ""

    if action == "accept":

        ticket.assignee_id = assignee.id if assignee else actor.id

        if ticket.first_responded_at is None:

            ticket.first_responded_at = now

    elif action in ("finish", "confirm_resolved"):

        # v2.12 完结留痕：解决方案**追加式归档**（管理员/工程师只能在已有内容上补充【补充】段，

        # 不能改写他人/前次内容）；反馈处理结果写入事件展示给提交人并随通知发送。

        # 耗时分级必填（自创建时间起算）：>1h 两项必填；30min~1h 反馈必填；30min 内均选填。

        if solution.strip():

            ticket.solution = (ticket.solution + "\n【补充】" + solution.strip()) if ticket.solution else solution.strip()

        elapsed_min = ((now - ticket.created_at).total_seconds() / 60) if ticket.created_at else 0

        has_solution = bool((ticket.solution or "").strip())

        if elapsed_min > 60:

            if not has_solution:

                raise TransitionError("完结耗时已超过 1 小时：请填写解决方案（内部归档）")

            if not note.strip():

                raise TransitionError("完结耗时已超过 1 小时：请填写反馈处理结果（将展示给提交人）")

        elif elapsed_min > 30 and not note.strip():

            raise TransitionError("完结耗时超过 30 分钟：请填写反馈处理结果")

        ticket.resolved_at = now

        ticket.urgent = False  # 已解决即解除加急

    elif action == "approve":

        # v2.2 审批通过：SLA 从此刻起算；按模板配置触发 AD 联动任务

        from app.services.business_time import add_business_minutes

        resp_m, res_m = get_sla_minutes(db, ticket.priority)

        ticket.sla_response_deadline = add_business_minutes(now, resp_m)

        ticket.sla_resolve_deadline = add_business_minutes(now, res_m)

        approve_extra = "（SLA 自审批通过起算）" + (f"：{note.strip()}" if note.strip() else "")

        try:

            from app.models.system import TicketTemplate

            tpl = db.scalar(

                select(TicketTemplate).where(TicketTemplate.category == ticket.category, TicketTemplate.enabled.is_(True))

            )

            if tpl and tpl.ad_script:

                from app.services import ad_service

                ad_service.enqueue_for_ticket(db, ticket=ticket, template=tpl)

        except Exception:  # noqa: BLE001 联动失败不阻塞审批

            import logging

            logging.getLogger("services.ticket").exception("AD 联动任务生成失败")

    elif action == "reopen":

        # 重开：重置解决 SLA 窗口（按工作日历重新计算），清空完成时间

        from app.services.business_time import add_business_minutes

        _, res_m = get_sla_minutes(db, ticket.priority)

        ticket.sla_resolve_deadline = add_business_minutes(now, res_m)

        ticket.sla_resolve_warned = False

        ticket.sla_escalated = False

        ticket.resolved_at = None

        ticket.closed_at = None

        if ticket.assignee_id is None:

            ticket.assignee_id = actor.id

    elif action == "close":

        ticket.closed_at = now

        if ticket.resolved_at is None:

            ticket.resolved_at = now  # 直接关闭视同完成

    content = ACTION_LABELS.get(action, action)

    if action == "approve":

        content += approve_extra

    elif note:

        content += f"：{note.strip()}"

    ev = TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_TRANSITION,

        from_status=from_status, to_status=to_status, content=content,

    )

    db.add(ev)

    db.commit()

    db.refresh(ticket)

    _emit_webhook(db, "ticket.updated", ticket)

    if to_status == STATUS_RESOLVED:

        _emit_webhook(db, "ticket.resolved", ticket)

    if to_status == STATUS_CLOSED:

        _emit_webhook(db, "ticket.closed", ticket)

    return ev

def assign_ticket(

    db: Session,

    *,

    ticket: Ticket,

    actor: User,

    engineer: User,

    reason: str = "",

    skip_scope_check: bool = False,

) -> TicketEvent:

    if actor.role not in ("admin", "engineer"):

        raise TransitionError("仅工程师/管理员可以派单")

    if engineer.role not in ("admin", "engineer"):

        raise TransitionError("只能指派给工程师/管理员")

    if (engineer.status or "on_duty") == "leave":

        raise TransitionError("该工程师已请假，无法指派")

    # 类目权限语义——非本人指派（他人转派）不得超出目标工程师类目权限；

    # 工程师自行转入（actor 即本人，接单广场认领/指定派单码接收）不受限；

    # skip_scope_check=True 供系统内部行为使用（巡检工单轮询派发）

    if (

        not skip_scope_check

        and actor.id != engineer.id

        and engineer.role == "engineer"

        and engineer.category_scope_list

        and ticket.category not in engineer.category_scope_list

    ):

        raise TransitionError(

            f"该工程师的类目权限仅限 {'、'.join(engineer.category_scope_list)}，"

            f"「{ticket.category}」类目问题无法直接指派（可在接单广场由其自行转入处理）"

        )

    is_reassign = bool(ticket.assignee_id and ticket.assignee_id != engineer.id)

    if is_reassign and not reason.strip():

        # v2.4.1 改派必填原因（留痕审计）

        raise TransitionError("改派必须填写原因，便于审计追溯")

    prev_name = ticket.assignee.name or ticket.assignee.username if ticket.assignee else None

    ticket.assignee_id = engineer.id

    ticket.urgent = False  # 重新指派（含认领转办）即视为已接管，清除加急标记

    if is_reassign:

        ticket.transferred = True  # v2.9 转交标记（改派/认领）

    if ticket.status == STATUS_PENDING:

        ticket.status = STATUS_PROCESSING

        if ticket.first_responded_at is None:

            ticket.first_responded_at = utcnow()

    if is_reassign:

        content = f"改派给 {engineer.name or engineer.username}（原处理人 {prev_name}）：{reason.strip()}"

    else:

        content = f"指派给 {engineer.name or engineer.username}"

    ev = TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_TRANSITION,

        to_status=ticket.status, content=content,

    )

    db.add(ev)

    db.commit()

    db.refresh(ticket)

    return ev

def add_comment(db: Session, *, ticket: Ticket, actor: User, content: str) -> TicketEvent:

    if actor.role == "employee" and actor.id != ticket.creator_id:

        raise TransitionError("只有工单相关人可以评论")

    ev = TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_COMMENT, content=content.strip()

    )

    db.add(ev)

    db.commit()

    db.refresh(ev)

    return ev

URGE_COOLDOWN = timedelta(minutes=30)

def _assignee_queue_ahead(db: Session, ticket: Ticket) -> int | None:

    """该工单在其处理人名下的排队位次（前面还有几单）；未指派返回 None。"""

    if not ticket.assignee_id:

        return None

    from sqlalchemy import func

    return (

        db.scalar(

            select(func.count(Ticket.id)).where(

                Ticket.assignee_id == ticket.assignee_id,

                Ticket.status.in_(("pending", "processing", "pending_confirm")),

                Ticket.id < ticket.id,

            )

        )

        or 0

    )

def escalate_ticket(db: Session, *, ticket: Ticket, actor: User) -> dict:

    """员工加急（v2.6）：标记加急 + 推送处理人；处理人排队 >2 单时广播其他工程师可转办。

    与催单共用 30 分钟频控（同一 URGE 事件序列）；未指派工单直接广播认领。

    返回 {queue_ahead, broadcast}。

    """

    if not (actor.id in (ticket.creator_id, ticket.requester_id) or actor.role == "admin"):

        raise TransitionError("只有发起人可以加急")

    if ticket.merged_into_id:

        raise TransitionError("该工单已并入主工单，请在主工单上加急（将同步全部关联工单）")

    if not ticket.is_open:

        raise TransitionError("工单已结束，无需加急")

    if ticket.status == "pending_approval":

        raise TransitionError("工单待主管审批，审批通过后如需加急再操作")

    if ticket.sla_suspended_at:

        raise TransitionError("工单 SLA 已挂起，请先联系工程师恢复后再加急")

    last_urge = db.scalar(

        select(TicketEvent.id)

        .where(TicketEvent.ticket_id == ticket.id, TicketEvent.type == TicketEvent.TYPE_URGE)

        .order_by(TicketEvent.id.desc())

        .limit(1)

    )

    if last_urge:

        last_ev = db.get(TicketEvent, last_urge)

        if last_ev and last_ev.created_at and utcnow() - last_ev.created_at < URGE_COOLDOWN:

            raise TransitionError("已加急过，请稍后再试（30 分钟内仅一次）")

    # v2.12 统一加急逻辑：30 分钟内仅催当前工程师；超过 30 分钟广播其他工程师协助；

    # 未指派直接广播认领（不再按处理人排队数判断）。

    elapsed_min = ((utcnow() - ticket.created_at).total_seconds() / 60) if ticket.created_at else 0

    queue_ahead = _assignee_queue_ahead(db, ticket)

    ticket.urgent = True

    ticket.urgent_at = utcnow()

    if queue_ahead is None:

        broadcast = True

        content = "工单加急：未指派，等待工程师认领"

    elif elapsed_min > 30:

        broadcast = True

        content = "工单已超过 30 分钟未解决：已广播其他工程师协助处理"

    else:

        broadcast = False

        content = "工单加急：已提醒处理人尽快处理"

    db.add(TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_URGE, content=content,

    ))

    db.commit()

    db.refresh(ticket)

    return {"queue_ahead": queue_ahead, "broadcast": broadcast, "content": content}

def urgent_queue_visible(db: Session, ticket: Ticket) -> bool:

    """加急单是否对其他工程师可见可转办（v2.12）：超 30 分钟未解决或未指派即可见。"""

    if not ticket.urgent or not ticket.is_open:

        return False

    if ticket.assignee_id is None:

        return True

    # 超 30 分钟未解决（按创建时间起算）→ 广播可见

    from zoneinfo import ZoneInfo

    elapsed_min = ((utcnow() - ticket.created_at).total_seconds() / 60) if ticket.created_at else 0

    return elapsed_min > 30

def broadcast_targets(db: Session, ticket: Ticket, exclude_actor: User) -> list[User]:

    """加急广播目标：除发起人与当前处理人外的全部 IT 侧人员。"""

    targets = [

        u

        for u in db.scalars(select(User).where(User.role.in_(("admin", "engineer")), User.is_active.is_(True))).all()

        if u.id not in (ticket.assignee_id, exclude_actor.id)

    ]

    return targets

def urge_ticket(db: Session, *, ticket: Ticket, actor: User) -> TicketEvent:

    """催单：发起人（或管理员）对未结工单催办，30 分钟内只算一次。"""

    if not (actor.id == ticket.creator_id or actor.role == "admin"):

        raise TransitionError("只有发起人可以催单")

    if not ticket.is_open:

        raise TransitionError("工单已结束，无需催单")

    if ticket.sla_suspended_at:

        raise TransitionError("工单 SLA 已挂起，请先联系工程师恢复后再催办")

    last_urge = (

        db.scalar(

            select(TicketEvent.id)

            .where(TicketEvent.ticket_id == ticket.id, TicketEvent.type == TicketEvent.TYPE_URGE)

            .order_by(TicketEvent.id.desc())

            .limit(1)

        )

    )

    if last_urge:

        last_ev = db.get(TicketEvent, last_urge)

        if last_ev and last_ev.created_at and utcnow() - last_ev.created_at < URGE_COOLDOWN:

            raise TransitionError("已催办过，请稍后再试（30 分钟内仅一次）")

    ev = TicketEvent(

        ticket_id=ticket.id, actor_id=actor.id, type=TicketEvent.TYPE_URGE,

        content="催办：请尽快处理",

    )

    db.add(ev)

    db.commit()

    db.refresh(ticket)

    return ev

def rate_ticket(db: Session, *, ticket: Ticket, user: User, stars: int, comment: str = "") -> Rating:

    if ticket.status not in (STATUS_RESOLVED, STATUS_CLOSED):

        raise TransitionError("工单解决后才能评价")

    if user.id != ticket.creator_id and user.role != "admin":

        raise TransitionError("只有发起人可以评价")

    existing = db.scalar(select(Rating).where(Rating.ticket_id == ticket.id))

    if existing:

        raise TransitionError("该工单已评价过")

    r = Rating(ticket_id=ticket.id, user_id=user.id, stars=stars, comment=comment.strip()[:500])

    db.add(r)

    db.add(

        TicketEvent(

            ticket_id=ticket.id, actor_id=user.id, type=TicketEvent.TYPE_COMMENT,

            content=f"满意度评价：{'★' * stars}{'☆' * (5 - stars)}" + (f"（{comment.strip()}）" if comment.strip() else ""),

        )

    )

    db.commit()

    db.refresh(r)

    return r

def my_accessible_ticket(db: Session, ticket_id: int, user: User) -> Ticket | None:

    """工单可见性：员工看自己/被代报的；部门管理员（v2.8）可看本部门；工程师按类目权限过滤；管理员全量。"""

    t = db.get(Ticket, ticket_id)

    if not t:

        return None

    if t.creator_id == user.id or t.requester_id == user.id:

        return t

    if user.role == "admin":

        return t

    # v2.8 部门管理员（员工）：本部门工单可见

    if user.role == "employee" and user.dept_admin and user.department:

        if t.creator and t.creator.department == user.department:

            return t

    # 待受理未指派单放行（工程师可查看后自行转入）；已指派给自己的也放行

    if user.role == "engineer" and (

        (t.status == "pending" and t.assignee_id is None) or t.assignee_id == user.id or user.in_category_scope(t.category)

    ):

        return t

    return None

def status_label(s: str) -> str:

    return STATUS_LABELS.get(s, s)

def priority_label(p: str) -> str:

    return PRIORITY_LABELS.get(p, p)
