"""二维码报修标签：位置码 / 设备码 / 指定派单码。

二维码只编码短 URL（{public_base_url}/qr/{code}），位置/设备/指派关系全部存在本表：

改数据不用重印贴纸。

"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text

from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

from app.models.meeting import MeetingRoom  # noqa: F401 确保 meeting_rooms 先注册到 metadata（FK 依赖）

from app.models.user import iso_z, utcnow

QR_KINDS = ["location", "device", "assignee", "room"]

QR_KIND_LABELS = {"location": "位置码", "device": "设备码", "assignee": "指定派单码", "room": "会议室码"}

class QrTag(Base):

    __tablename__ = "qr_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # QR-XXXX，二维码内容里的标识

    name: Mapped[str] = mapped_column(String(128))

    kind: Mapped[str] = mapped_column(String(16), default="location")

    location: Mapped[str] = mapped_column(String(128), default="")  # 位置码：地点描述

    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)  # 设备码：关联资产

    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # 指定派单码

    room_id: Mapped[int | None] = mapped_column(ForeignKey("meeting_rooms.id"), nullable=True)  # v2.12 会议室码

    category: Mapped[str] = mapped_column(String(32), default="")  # 扫码建单默认分类（设备码建议选「打印设备」等）

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    note: Mapped[str] = mapped_column(Text, default="")

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property

    def qr_url(self) -> str:

        from app.core.config import get_config

        return f"{get_config().public_base_url.rstrip('/')}/qr/{self.code}"

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "code": self.code,

            "name": self.name,

            "kind": self.kind,

            "kind_label": QR_KIND_LABELS.get(self.kind, "未知类型"),

            "location": self.location,

            "asset_id": self.asset_id,

            "engineer_id": self.engineer_id,

            "room_id": self.room_id,

            "category": self.category,

            "enabled": self.enabled,

            "note": self.note,

            "created_at": iso_z(self.created_at),

        }
