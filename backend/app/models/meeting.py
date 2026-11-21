"""会议室预约管理（v2.12）：会议室、预约单、设备检查留痕。

扫码链路：会议室码（qr_tags.kind=room）→ 扫码页看预约状态/设备说明 → 登录员工可预约；
管理员扫码可填报设备检查结果（工作留痕：检查时间/检查人/逐项结果/备注）。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base
from app.models.user import User, iso_z, utcnow

# 固定检查项（key → 说明），后台与扫码页共用
ROOM_CHECK_ITEMS: list[tuple[str, str]] = [
    ("screen_power", "电视/显示屏正常开机"),
    ("default_cast", "默认投屏"),
    ("cables", "设备连接线完好"),
    ("auto_switch", "插入后自动切换信号"),
    ("remote_battery", "遥控器有电池"),
    ("mic", "麦克风正常使用（含电池）"),
]
ROOM_CHECK_LABELS = dict(ROOM_CHECK_ITEMS)


class MeetingRoom(Base):
    """会议室：位置、容纳人数、设备列表与使用说明（扫码可见）、维修公告、巡检周期。"""

    __tablename__ = "meeting_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    location: Mapped[str] = mapped_column(String(128), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=10)
    equipment_desc: Mapped[str] = mapped_column(Text, default="")  # 使用说明（员工扫码可见）
    # 第三十九批：会议室设备列表 JSON [{name, count, status}]（status: 正常/维修中/损坏），
    # 员工扫码判断能否满足需要，运维据此维护并标注使用情况
    equipment_list: Mapped[str] = mapped_column(Text, default="[]")
    check_cycle_days: Mapped[int] = mapped_column(Integer, default=0)  # v2.12 兼容旧值：周期天数
    # 第三十九批：巡检周期扩展——unit: day(每 N 天)/week(每 N 周)/session(每 N 场已结束预约)；value=N
    check_cycle_unit: Mapped[str] = mapped_column(String(16), default="day")
    check_cycle_value: Mapped[int] = mapped_column(Integer, default=0)
    under_maintenance: Mapped[bool] = mapped_column(Boolean, default=False)  # 重要设备维修中 → 扫码弹公告
    maintenance_notice: Mapped[str] = mapped_column(Text, default="")  # 公告内容（维修原因/预计恢复等）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def equipment_items(self) -> list[dict]:
        import json

        if not self.equipment_list:
            return []
        try:
            data = json.loads(self.equipment_list)
            return data if isinstance(data, list) else []
        except ValueError:
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "location": self.location,
            "capacity": self.capacity,
            "equipment_desc": self.equipment_desc,
            "equipment_list": self.equipment_items,
            "under_maintenance": self.under_maintenance,
            "maintenance_notice": self.maintenance_notice,
            "check_cycle_days": self.check_cycle_days,
            "check_cycle_unit": self.check_cycle_unit or "day",
            "check_cycle_value": self.check_cycle_value,
            "enabled": self.enabled,
            "created_at": iso_z(self.created_at),
        }


class MeetingBooking(Base):
    """预约单：某会议室某天的时段占用；冲突=同室同日时间区间重叠。"""

    __tablename__ = "meeting_bookings"

    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("meeting_rooms.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    title: Mapped[str] = mapped_column(String(200), default="")
    booker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE)
    reminded: Mapped[bool] = mapped_column(Boolean, default=False)  # v2.12 开始前提醒已发送
    # 第二十三批+：到场签到时间（no-show 统计依据）——预约开始后扫码/页面点击签到，已结束未签到记为爽约
    checkin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    booker: Mapped[User] = relationship(foreign_keys=[booker_id], lazy="joined")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "date": self.date.isoformat(),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "title": self.title,
            "booker": {"id": self.booker.id, "name": self.booker.name or self.booker.username} if self.booker else None,
            "status": self.status,
            "reminded": self.reminded,
            "checkin_at": iso_z(self.checkin_at) if self.checkin_at else None,
            "created_at": iso_z(self.created_at),
        }


class RoomInspection(Base):
    """设备检查留痕：检查人、检查时间、逐项结果（JSON）与备注（丢失/损坏/需报修）。"""

    __tablename__ = "room_inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("meeting_rooms.id"), index=True)
    inspector_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    results: Mapped[str] = mapped_column(Text, default="{}")  # JSON {item_key: "ok"|"fail"}
    note: Mapped[str] = mapped_column(Text, default="")  # 备注：丢失/损坏/需报修的硬件说明

    inspector: Mapped[User | None] = relationship(foreign_keys=[inspector_id], lazy="joined")

    def to_dict(self) -> dict:
        import json

        return {
            "id": self.id,
            "room_id": self.room_id,
            "inspector": ({"id": self.inspector.id, "name": self.inspector.name or self.inspector.username} if self.inspector else None),
            "inspected_at": iso_z(self.inspected_at),
            "results": json.loads(self.results or "{}"),
            "note": self.note,
        }
