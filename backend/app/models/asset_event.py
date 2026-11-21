"""资产操作记录（v2.7 资产全生命周期）：领用/归还/回收/维修/报废等动作留痕。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base
from app.models.user import User, iso_z, utcnow

ACTIONS = {
    "create": "登记",
    "assign": "领用",
    "return": "归还",
    "recover": "回收",
    "repair": "送修",
    "repair_done": "修复完成",
    "scrap": "报废",
    "update": "信息变更",
    "part_change": "部件变更",  # v2.12 维修拆装部件留痕
}


class AssetEvent(Base):
    __tablename__ = "asset_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # ACTIONS 键
    note: Mapped[str] = mapped_column(Text, default="")
    parts: Mapped[str] = mapped_column(Text, default="")  # v2.12 维修拆装部件 JSON [{name, sn, direction, note}]
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    asset: Mapped["Asset"] = relationship(foreign_keys=[asset_id], back_populates="events")  # noqa: F821
    operator: Mapped[Optional[User]] = relationship(foreign_keys=[operator_id], lazy="joined")

    def to_dict(self) -> dict:
        import json

        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "action": self.action,
            "action_label": ACTIONS.get(self.action, self.action),
            "note": self.note,
            "parts": json.loads(self.parts or "[]"),
            "operator": (self.operator.name or self.operator.username) if self.operator else "系统",
            "created_at": iso_z(self.created_at),
        }
