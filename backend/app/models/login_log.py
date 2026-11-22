"""登录日志：登录成功/失败持久化记录，供安全审计查询。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String

from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

from app.models.user import iso_z, utcnow

class LoginLog(Base):

    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    username: Mapped[str] = mapped_column(String(64), index=True)

    name: Mapped[str] = mapped_column(String(64), default="")

    ip: Mapped[str] = mapped_column(String(64), default="")

    success: Mapped[bool] = mapped_column(Boolean, default=False)

    reason: Mapped[str] = mapped_column(String(200), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "username": self.username,

            "name": self.name,

            "ip": self.ip,

            "success": self.success,

            "reason": self.reason,

            "created_at": iso_z(self.created_at),

        }
