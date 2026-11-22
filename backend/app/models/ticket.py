"""工单、流转事件、满意度评价。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

from app.models.attachment import Attachment  # noqa: F401 供 mapper 解析关系

from app.models.user import User, iso_z, utcnow

# ---- 状态机 ----

STATUS_PENDING = "pending"          # 待受理

STATUS_PROCESSING = "processing"    # 处理中

STATUS_CONFIRM = "pending_confirm"  # 待确认（已提交解决方案，等待发起人确认）

STATUS_RESOLVED = "resolved"        # 已解决

STATUS_CLOSED = "closed"            # 已关闭

STATUS_APPROVAL = "pending_approval"  # v2.2 待审批（模板开启审批节点，主管通过后才受理）

STATUS_LABELS = {

    STATUS_PENDING: "待受理",

    STATUS_PROCESSING: "处理中",

    STATUS_CONFIRM: "待确认",

    STATUS_RESOLVED: "已解决",

    STATUS_CLOSED: "已关闭",

    STATUS_APPROVAL: "待审批",

}

PRIORITIES = ["low", "medium", "high", "urgent"]

PRIORITY_LABELS = {"low": "低", "medium": "中", "high": "高", "urgent": "紧急"}

CHANNELS = ["web", "dingtalk", "feishu", "wecom"]

# 动作 -> (from 状态集合, to 状态)

ACTIONS = {

    "accept": {STATUS_PENDING: STATUS_PROCESSING},                 # 工程师接单

    "cancel": {STATUS_PENDING: STATUS_CLOSED, STATUS_APPROVAL: STATUS_CLOSED},  # 发起人撤销（待审批单也可撤回）

    "reject_solution": {STATUS_CONFIRM: STATUS_PROCESSING},        # 发起人退回

    "confirm_resolved": {STATUS_CONFIRM: STATUS_RESOLVED},         # 发起人确认解决

    # v2.12 工程师直接完结：处理完问题一次性填解决方案（内部归档）与反馈处理结果

    "finish": {STATUS_PROCESSING: STATUS_RESOLVED, STATUS_CONFIRM: STATUS_RESOLVED},

    "close": {STATUS_RESOLVED: STATUS_CLOSED, STATUS_PENDING: STATUS_CLOSED},  # 关单

    "reopen": {STATUS_CLOSED: STATUS_PROCESSING, STATUS_RESOLVED: STATUS_PROCESSING},  # 重开

    # v2.2 审批节点

    "approve": {STATUS_APPROVAL: STATUS_PENDING},   # 主管审批通过 → 进入待受理（SLA 从此刻起算）

    "reject": {STATUS_APPROVAL: STATUS_CLOSED},     # 主管驳回 → 关闭

}

class Ticket(Base):

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    no: Mapped[str] = mapped_column(String(32), unique=True, index=True, default="")

    title: Mapped[str] = mapped_column(String(200))

    description: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[str] = mapped_column(String(32), default="其他")

    priority: Mapped[str] = mapped_column(String(16), default="medium")

    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)

    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # v2.0 提出者（代报修）：creator 是提交人，requester 是实际报修人

    requester_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)

    # v1.2：模板自定义字段（JSON 对象）与合并目标

    custom_fields: Mapped[str] = mapped_column(Text, default="{}")

    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)

    channel: Mapped[str] = mapped_column(String(16), default="web")  # web/dingtalk/feishu/wecom

    channel_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    solution: Mapped[str] = mapped_column(Text, default="")

    # SLA

    sla_response_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sla_resolve_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    first_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sla_response_warned: Mapped[bool] = mapped_column(Boolean, default=False)

    sla_resolve_warned: Mapped[bool] = mapped_column(Boolean, default=False)

    sla_escalated: Mapped[bool] = mapped_column(Boolean, default=False)

    # v2.0 SLA 挂起：挂起时快照剩余分钟，解挂时按工作日历顺延重算

    sla_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sla_response_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sla_resolve_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sla_suspended_total: Mapped[int] = mapped_column(Integer, default=0)  # 累计挂起分钟（v2.1 统计用）

    # v2.6 加急：员工扫码页一键加急；处理人队列 >2 单时对其他工程师可见可转办

    urgent: Mapped[bool] = mapped_column(Boolean, default=False)

    urgent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # v2.7 预估处理时长（建单时从模板快照）：长耗时隔离/打散依据

    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)

    # v2.9 转交标记：工单曾被改派/认领到当前处理人名下（「转交工单」筛选依据）

    transferred: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    creator: Mapped[User] = relationship(foreign_keys=[creator_id], lazy="joined")

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")

    requester: Mapped[User | None] = relationship(foreign_keys=[requester_id], lazy="joined")

    followers: Mapped[list["TicketFollower"]] = relationship(

        cascade="all, delete-orphan", lazy="selectin", order_by="TicketFollower.id"

    )

    events: Mapped[list["TicketEvent"]] = relationship(

        back_populates="ticket", cascade="all, delete-orphan", lazy="selectin",

        order_by="TicketEvent.id",

    )

    rating: Mapped["Rating | None"] = relationship(back_populates="ticket", lazy="selectin", uselist=False)

    attachments: Mapped[list["Attachment"]] = relationship(

        cascade="all, delete-orphan", lazy="selectin", order_by="Attachment.id"

    )

    @property

    def is_open(self) -> bool:

        return self.status in (STATUS_PENDING, STATUS_PROCESSING, STATUS_CONFIRM, STATUS_APPROVAL)

    def to_dict(self) -> dict:

        import json

        suspended = self.sla_suspended_at is not None

        return {

            "id": self.id,

            "no": self.no,

            "title": self.title,

            "description": self.description,

            "category": self.category,

            "priority": self.priority,

            "status": self.status,

            "status_label": STATUS_LABELS.get(self.status, self.status),

            "priority_label": PRIORITY_LABELS.get(self.priority, self.priority),

            "creator": {"id": self.creator.id, "name": self.creator.name or self.creator.username} if self.creator else None,

            "assignee": ({"id": self.assignee.id, "name": self.assignee.name or self.assignee.username} if self.assignee else None),

            "requester": ({"id": self.requester.id, "name": self.requester.name or self.requester.username} if self.requester else None),

            "followers": [{"id": f.user_id, "name": (f.user.name or f.user.username) if f.user else "?"} for f in self.followers],

            "asset_id": self.asset_id,

            "channel": self.channel,

            "solution": self.solution,

            "custom_fields": json.loads(self.custom_fields or "{}"),

            "merged_into_id": self.merged_into_id,

            "urgent": bool(self.urgent),

            "transferred": bool(self.transferred),

            "estimated_minutes": self.estimated_minutes or 0,

            "attachments": [a.to_dict() for a in self.attachments],

            "sla_response_deadline": iso_z(self.sla_response_deadline),

            "sla_resolve_deadline": iso_z(self.sla_resolve_deadline),

            "sla_suspended": suspended,

            "sla_remaining_minutes": self.sla_resolve_remaining if suspended else None,

            "first_responded_at": iso_z(self.first_responded_at),

            "resolved_at": iso_z(self.resolved_at),

            "closed_at": iso_z(self.closed_at),

            # 挂起期间 SLA 计时暂停，不产生超时状态

            "response_breached": bool(

                not suspended

                and self.sla_response_deadline

                and not self.first_responded_at

                and self.sla_response_deadline < utcnow()

            ),

            "resolve_breached": bool(

                not suspended

                and self.sla_resolve_deadline and self.sla_resolve_deadline < utcnow() and not self.resolved_at

            ),

            "created_at": iso_z(self.created_at),

            "updated_at": iso_z(self.updated_at),

        }

class TicketEvent(Base):

    """流转/评论/系统事件，全链路追溯。"""

    TYPE_CREATE = "create"

    TYPE_COMMENT = "comment"

    TYPE_TRANSITION = "transition"

    TYPE_SYSTEM = "system"

    TYPE_URGE = "urge"

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)

    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    type: Mapped[str] = mapped_column(String(20))

    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    content: Mapped[str] = mapped_column(Text, default="")

    edited: Mapped[bool] = mapped_column(Boolean, default=False)  # v2.12 评论编辑标记

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="events")

    actor: Mapped[User | None] = relationship(lazy="joined")

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "type": self.type,

            "actor": ({"id": self.actor.id, "name": self.actor.name or self.actor.username} if self.actor else None),

            "from_status": self.from_status,

            "to_status": self.to_status,

            "content": self.content,

            "edited": self.edited,

            "created_at": iso_z(self.created_at),

        }

class TicketFollower(Base):

    """v2.0 工单关注：工程师/主管跟单，状态变更与评论时收到通知。"""

    __tablename__ = "ticket_followers"

    __table_args__ = (UniqueConstraint("ticket_id", "user_id", name="uq_ticket_follower"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="followers")

    user: Mapped[User | None] = relationship(lazy="joined")

class Rating(Base):

    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), unique=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    stars: Mapped[int] = mapped_column(Integer)  # 1-5

    comment: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="rating")
