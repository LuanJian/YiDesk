"""IM 入站消息处理：自动注册绑定、命令识别、建单、会话回复。

渠道长连接线程收到消息 → 归一化为 InboundDraft → 这里统一处理。

"""

from __future__ import annotations

import re

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.deps import find_user_by_platform

from app.models.database import create_session

from app.models.ticket import STATUS_LABELS, Ticket

from app.models.user import User, utcnow

from app.services import attachment_service, notify_service, ticket_service, v12_service

HELP_TEXT = (

    "我可以帮你提交 IT 报修工单：\n"

    "1. 直接发送问题描述（如「打印机坏了」）即可自动建单\n"

    "2. 发送「我的工单」查看最近工单进度\n"

    "3. 紧急问题请在工单里备注，或直接致电 IT 服务台"

)

class InboundDraft:

    """归一化后的入站消息。"""

    __slots__ = ("channel", "platform_user_id", "sender_name", "text", "chat_id", "extra")

    def __init__(self, channel: str, platform_user_id: str, sender_name: str, text: str, chat_id: str | None = None, extra: dict | None = None):

        self.channel = channel

        self.platform_user_id = platform_user_id

        self.sender_name = sender_name

        self.text = (text or "").strip()

        self.chat_id = chat_id

        self.extra = extra or {}

def auto_register(db: Session, draft: InboundDraft) -> User:

    """首次 IM 建单：自动创建员工账号并绑定平台 ID。"""

    username = f"{draft.channel}_{re.sub(r'[^A-Za-z0-9_-]', '', draft.platform_user_id)[:40]}" or f"{draft.channel}_user_{utcnow():%H%M%S}"

    user = User(

        username=username,

        name=(draft.sender_name or f"{draft.channel}用户")[:64],

        role="employee",

        password_hash=None,  # 无法 Web 登录，管理员可在设置里重置密码

    )

    setattr(user, {"dingtalk": "dingtalk_userid", "feishu": "feishu_open_id", "wecom": "wecom_userid"}[draft.channel], draft.platform_user_id)

    db.add(user)

    db.commit()

    db.refresh(user)

    return user

def _reply(draft: InboundDraft, text: str) -> None:

    from app.channels.registry import registry

    adapter = registry.get(draft.channel)

    if adapter and draft.chat_id:

        try:

            adapter.reply_chat(draft.chat_id, text)

        except Exception:  # noqa: BLE001 回复失败不影响主流程

            pass

def _list_my_tickets(db: Session, user: User) -> str:

    tickets = list(

        db.scalars(select(Ticket).where(Ticket.creator_id == user.id).order_by(Ticket.id.desc()).limit(5))

    )

    if not tickets:

        return "你还没有提交过工单，直接发送问题描述即可建单。"

    lines = [f"{t.no} [{STATUS_LABELS.get(t.status)}] {t.title}" for t in tickets]

    return "你最近的工单：\n" + "\n".join(lines)

def _ticket_progress(db: Session, user: User, no: str) -> str:

    """查指定工单号进度（发起人/提出者/IT 侧可查）。"""

    t = db.scalar(select(Ticket).where(Ticket.no == no))

    if not t:

        return f"未找到工单 {no}"

    if not (user.role in ("admin", "engineer") or t.creator_id == user.id or t.requester_id == user.id):

        return "该工单不属于你，无权查看进度"

    lines = [f"{t.no} [{STATUS_LABELS.get(t.status)}] {t.title}", f"处理人：{(t.assignee.name or t.assignee.username) if t.assignee else '未指派'}"]

    if t.urgent:

        lines.append("⚠️ 已被员工加急")

    last_events = sorted(t.events, key=lambda e: e.id)[-3:]

    for e in last_events:

        actor = (e.actor.name or e.actor.username) if e.actor else "系统"

        lines.append(f"· {e.created_at:%m-%d %H:%M} {actor}：{e.content}")

    return "\n".join(lines)

def _guess_image_type(filename: str) -> str:

    lower = filename.lower()

    for ext, mime in (

        (".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"),

        (".gif", "image/gif"), (".webp", "image/webp"), (".bmp", "image/bmp"),

    ):

        if lower.endswith(ext):

            return mime

    return "image/png"

def handle_inbound(db: Session, draft: InboundDraft) -> None:

    """处理一条 IM 消息（在渠道长连接线程里调用）。"""

    if not draft.platform_user_id:

        return

    user = find_user_by_platform(db, draft.channel, draft.platform_user_id)

    if not user:

        user = auto_register(db, draft)

    text = draft.text

    images = draft.extra.get("images") or []  # [(filename, bytes)]

    # 图片且无文字 → 直接以图片报修建单

    if images and not text:

        text = "（图片报修）"

    if not text and not images:

        _reply(draft, "暂只支持文字与图片消息，请直接描述你的问题。")

        return

    if text in ("帮助", "help", "菜单", "Help", "HELP"):

        _reply(draft, HELP_TEXT)

        return

    if text.startswith(("我的工单", "查询", "进度")):

        _reply(draft, _list_my_tickets(db, user))

        return

    # v2.7 群内工单进度查询：发「查 GD-20261112-0001」返回该单进度（发起人/被代报/IT 侧可查）

    # 兼容新编号（A-D 级别前缀）与旧编号（GD- 前缀）

    m_cmd = re.match(r"^查\s*([A-D]-\d{8}-\d{3,6}|GD-\d{8}-\d{3,6})$", text)

    if m_cmd:

        _reply(draft, _ticket_progress(db, user, m_cmd.group(1)))

        return

    # 其余一律视为报修描述 → 建单（可携带图片附件）

    title = text if len(text) <= 40 else text[:38] + "…"

    try:

        ticket = ticket_service.create_ticket(

            db, creator=user, title=title, description=text,

            channel=draft.channel, chat_id=draft.chat_id,

            validate_fields=False,  # IM 无结构化表单，跳过模板必填校验

        )

        for fname, content in images:

            attachment_service.save_attachment(

                db, ticket=ticket, filename=fname, content=content,

                content_type=_guess_image_type(fname), uploader=user, source=draft.channel,

            )

        # 智能分派（与 Web 建单行为一致）

        v12_service.auto_assign(db, ticket)

    except ticket_service.TransitionError as exc:

        _reply(draft, f"建单失败：{exc.message}")

        return

    reply_text = f"✅ 已创建工单 {ticket.no}\n标题：{ticket.title}\n状态：{STATUS_LABELS.get(ticket.status, ticket.status)}"

    if ticket.status == "pending_approval":

        reply_text += "（需主管审批，通过后工程师开始处理）"

    else:

        reply_text += "\n工程师会尽快处理，进展会在这里通知你。"

    if ticket.assignee:

        reply_text = reply_text.replace("工程师会尽快处理", f"已指派给 {ticket.assignee.name or ticket.assignee.username}，会尽快处理")

    if images:

        img_note = f"已收到 {len(images)} 张图片"

        reply_text = reply_text.replace("标题：" + ticket.title, "标题：" + ticket.title + "\n" + img_note)

    # 相似工单提示（重复报修识别，IM 渠道同样生效）

    similar = v12_service.find_similar_tickets(db, ticket)

    if similar:

        reply_text += "\n\n⚠️ 发现疑似重复工单：" + "、".join(s["no"] for s in similar) + "（如重复可联系工程师合并）"

    _reply(draft, reply_text)

    notify_service.notify_ticket_created(db, ticket, user)

    notify_service.flush(db)

def handle_inbound_threadsafe(draft: InboundDraft) -> None:

    """长连接线程入口：自建会话。"""

    db = create_session()

    try:

        handle_inbound(db, draft)

    finally:

        db.close()
