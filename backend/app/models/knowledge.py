"""知识库文章与资产。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.asset_event import AssetEvent  # noqa: F401 注册资产操作记录到 metadata（create_all 建表）

from app.models.database import Base

from app.models.user import User, iso_z, utcnow

class KnowledgeArticle(Base):

    __tablename__ = "knowledge_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(String(200), index=True)

    content: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[str] = mapped_column(String(32), default="常见问题")

    problem: Mapped[str] = mapped_column(Text, default="")  # v2.12 问题描述（详细说明问题现象）

    tags: Mapped[str] = mapped_column(String(200), default="")  # 逗号分隔

    source: Mapped[str] = mapped_column(String(256), default="")  # v2.11 信息来源：自述/官方文档/链接/内部 Wiki 等

    # 匿名可见——勾选后未登录员工可在登录页「常见问题」公开页看到该文章

    public_visible: Mapped[bool] = mapped_column(Boolean, default=False)

    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    author: Mapped[User | None] = relationship(lazy="joined")

    def to_dict(self, with_content: bool = True) -> dict:

        d = {

            "id": self.id,

            "title": self.title,

            "category": self.category,

            "problem": self.problem,

            "tags": [t for t in self.tags.split(",") if t],

            "source": self.source,

            "public_visible": bool(self.public_visible),

            "author": ({"id": self.author.id, "name": self.author.name} if self.author else None),

            "created_at": iso_z(self.created_at),

            "updated_at": iso_z(self.updated_at),

        }

        if with_content:

            d["content"] = self.content

        return d

class Asset(Base):

    """轻量资产登记：资产编号、类型、位置、状态、使用人；工单可关联。"""

    STATUS = ["在用", "维修中", "闲置", "报废"]

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    asset_tag: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    name: Mapped[str] = mapped_column(String(128))

    category: Mapped[str] = mapped_column(String(32), default="电脑")

    location: Mapped[str] = mapped_column(String(128), default="")

    status: Mapped[str] = mapped_column(String(16), default="在用")

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    note: Mapped[str] = mapped_column(Text, default="")

    # 设备码带入的设备信息（打印机 IP、型号等）

    ip_address: Mapped[str] = mapped_column(String(64), default="")

    model: Mapped[str] = mapped_column(String(128), default="")

    # 品牌与型号分列存储，避免「惠普 LaserJet P1108」混在型号里

    vendor: Mapped[str] = mapped_column(String(64), default="")

    driver_url: Mapped[str] = mapped_column(String(512), default="")  # v2.12 驱动下载地址

    # 资产到期（维保/租期等）YYYY-MM-DD；expire_warned 防重复提醒，改期时由服务层重置

    expire_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    expire_warned: Mapped[bool] = mapped_column(Boolean, default=False)

    # 最近一次在线检测时间（TCP 探活成功后记录，供「最近检测」列统一展示）

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User | None] = relationship(lazy="joined")

    # v2.7 资产操作记录（全生命周期留痕）：随资产删除级联清理

    events: Mapped[list["AssetEvent"]] = relationship(

        "AssetEvent", foreign_keys="AssetEvent.asset_id",

        cascade="all, delete-orphan", lazy="selectin", order_by="AssetEvent.id",

    )

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "asset_tag": self.asset_tag,

            "name": self.name,

            "category": self.category,

            "location": self.location,

            "status": self.status,

            "owner": ({"id": self.owner.id, "name": self.owner.name} if self.owner else None),

            "note": self.note,

            "ip_address": self.ip_address,

            "model": self.model,

            "vendor": self.vendor or "",

            "driver_url": self.driver_url,

            "expire_date": self.expire_date,

            "last_checked_at": iso_z(self.last_checked_at),

            "created_at": iso_z(self.created_at),

        }
