"""开放平台：Webhook 订阅与投递队列、只读 API Key（v2.2）。

事件先落 webhook_deliveries 再投递（与 Outbox 同思路），失败自动重试；

签名 HMAC-SHA256；目标 URL 仅允许 https 且默认拒绝私网地址（SSRF 防护）。

"""

from __future__ import annotations

import json

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

from app.models.user import iso_z, utcnow

WEBHOOK_EVENTS = ["ticket.created", "ticket.updated", "ticket.resolved", "ticket.closed"]

class WebhookSubscription(Base):

    __tablename__ = "webhook_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    url: Mapped[str] = mapped_column(String(500))

    secret: Mapped[str] = mapped_column(String(128))  # HMAC-SHA256 签名密钥

    events: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deliveries: Mapped[list["WebhookDelivery"]] = relationship(

        back_populates="subscription", cascade="all, delete-orphan", lazy="selectin"

    )

    @property

    def events_list(self) -> list[str]:

        import json

        try:

            data = json.loads(self.events or "[]")

            return data if isinstance(data, list) else []

        except ValueError:

            return []

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "url": self.url,

            "secret_masked": (self.secret[:2] + "****" + self.secret[-4:]) if len(self.secret) > 6 else "****",

            "events": self.events_list,

            "enabled": self.enabled,

            "created_at": iso_z(self.created_at),

        }

class WebhookDelivery(Base):

    __tablename__ = "webhook_deliveries"

    STATUS_PENDING = "pending"

    STATUS_SENT = "sent"

    STATUS_FAILED = "failed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    subscription_id: Mapped[int] = mapped_column(ForeignKey("webhook_subscriptions.id"), index=True)

    event: Mapped[str] = mapped_column(String(32))

    ticket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON 请求体

    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0)

    last_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subscription: Mapped[WebhookSubscription] = relationship(back_populates="deliveries")

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "subscription_id": self.subscription_id,

            "event": self.event,

            "ticket_id": self.ticket_id,

            "payload": json.loads(self.payload or "{}"),

            "status": self.status,

            "attempts": self.attempts,

            "last_error": self.last_error,

            "created_at": iso_z(self.created_at),

            "sent_at": iso_z(self.sent_at),

        }

class ApiKey(Base):

    """只读开放 API 的调用凭据：仅存 SHA-256 摘要，明文只在创建时返回一次。"""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(64))

    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "name": self.name,

            "key_masked": self.key_hash[:8] + "…",

            "enabled": self.enabled,

            "created_at": iso_z(self.created_at),

        }
