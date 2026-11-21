"""组织数据（v2.12）：公司部门与岗位的全局字典，供软件目录适用范围、用户管理等引用。

数据在系统设置「部门与岗位」页签维护；软件目录保存时用到的未收录标签会自动沉淀进来。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base
from app.models.user import iso_z, utcnow

ORG_TYPES = ["dept", "position"]
ORG_TYPE_LABELS = {"dept": "部门", "position": "岗位"}


class OrgTag(Base):
    """部门/岗位字典：type=dept|position，同类型下名称唯一。"""

    __tablename__ = "org_tags"
    __table_args__ = (UniqueConstraint("type", "name", name="uq_org_tag_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), index=True)  # dept / position
    name: Mapped[str] = mapped_column(String(64))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "type_label": ORG_TYPE_LABELS.get(self.type, self.type),
            "name": self.name,
            "sort": self.sort,
            "created_at": iso_z(self.created_at),
        }
