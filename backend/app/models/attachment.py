"""工单附件（截图、照片、文档）。文件落盘 backend/data/attachments/，元数据入库。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base
from app.models.user import iso_z, utcnow


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))  # 原始文件名（展示用）
    stored_name: Mapped[str] = mapped_column(String(128), unique=True)  # 落盘文件名（uuid）
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="web")  # web/dingtalk/feishu/wecom
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_image(self) -> bool:
        return (self.content_type or "").startswith("image/")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "filename": self.filename,
            "size": self.size,
            "content_type": self.content_type,
            "is_image": self.is_image,
            "uploader_id": self.uploader_id,
            "source": self.source,
            "url": f"/api/attachments/{self.id}",
            "created_at": iso_z(self.created_at),
        }


def attachments_dir() -> Path:
    d = Path(__file__).resolve().parents[2] / "data" / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d
