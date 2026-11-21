"""台账模型：软件许可、网络设备、终端合规巡检。"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base
from app.models.user import iso_z, utcnow

LICENSE_TYPES = ["永久授权", "订阅制", "OEM", "批量授权", "免费/开源"]
DEVICE_TYPES = ["交换机", "路由器", "无线 AP", "防火墙", "AC 控制器", "其他"]
DEVICE_STATUS = ["在线", "失联", "停用", "备用"]
COMPLIANCE_RESULTS = ["合规", "不合规", "未检"]


class SoftwareLicense(Base):
    """软件许可：类型、席位、到期、成本；许可密钥仅管理员可见（列表脱敏）。"""

    __tablename__ = "software_licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    vendor: Mapped[str] = mapped_column(String(128), default="")
    license_type: Mapped[str] = mapped_column(String(32), default="永久授权")
    license_key: Mapped[str] = mapped_column(String(256), default="")
    seats_total: Mapped[int] = mapped_column(Integer, default=1)
    seats_used: Mapped[int] = mapped_column(Integer, default=0)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 永久授权可空
    cost: Mapped[int] = mapped_column(Integer, default=0)  # 元
    vendor_contact: Mapped[str] = mapped_column(String(128), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def days_to_expiry(self) -> int | None:
        if not self.expiry_date:
            return None
        return (self.expiry_date - utcnow().date()).days

    def to_dict(self, show_key: bool = False) -> dict:
        key = self.license_key or ""
        # 仅保留末 4 位便于人工比对，其余脱敏
        masked = ("••••" + key[-4:]) if len(key) >= 4 else ("••••" if key else "")
        d = {
            "id": self.id,
            "name": self.name,
            "vendor": self.vendor,
            "license_type": self.license_type,
            "license_key_masked": masked,
            "seats_total": self.seats_total,
            "seats_used": self.seats_used,
            "seats_low": self.seats_used >= self.seats_total,
            "purchase_date": self.purchase_date.isoformat() if self.purchase_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "days_to_expiry": self.days_to_expiry,
            "expiring": bool(self.days_to_expiry is not None and 0 <= self.days_to_expiry <= 30),
            "expired": bool(self.days_to_expiry is not None and self.days_to_expiry < 0),
            "cost": self.cost,
            "vendor_contact": self.vendor_contact,
            "notes": self.notes,
            "enabled": self.enabled,
            "created_at": iso_z(self.created_at),
        }
        if show_key:
            d["license_key"] = key
        return d


class NetworkDevice(Base):
    """网络设备台账：连通性探活状态由定时任务/手动检测维护。"""

    __tablename__ = "network_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    device_type: Mapped[str] = mapped_column(String(32), default="交换机")
    vendor: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    ip: Mapped[str] = mapped_column(String(64), index=True)
    mgmt_port: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 探测端口（SSH/HTTPS）
    location: Mapped[str] = mapped_column(String(128), default="")
    serial_no: Mapped[str] = mapped_column(String(128), default="")
    firmware: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="备用")  # 在线/失联/停用/备用
    probe_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 第四十一批：统一设备台账字段——资产编号与保修到期日
    asset_tag: Mapped[str] = mapped_column(String(64), unique=True, index=True, default="")
    expire_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "vendor": self.vendor,
            "model": self.model,
            "ip": self.ip,
            "mgmt_port": self.mgmt_port,
            "location": self.location,
            "serial_no": self.serial_no,
            "firmware": self.firmware,
            "status": self.status,
            "probe_enabled": self.probe_enabled,
            "last_checked_at": iso_z(self.last_checked_at),
            "last_seen_at": iso_z(self.last_seen_at),
            "asset_tag": self.asset_tag or "",
            "expire_date": self.expire_date,
            "notes": self.notes,
        }


class ComplianceItem(Base):
    """合规巡检项：method=agent 由终端代理脚本上报；manual 由工程师登记。"""

    __tablename__ = "compliance_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # agent 上报用的标识
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32), default="安全基线")  # 安全基线/补丁/杀毒/软件/配置
    method: Mapped[str] = mapped_column(String(16), default="agent")  # agent/manual
    severity: Mapped[str] = mapped_column(String(16), default="中")  # 高/中/低
    description: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "category": self.category,
            "method": self.method,
            "severity": self.severity,
            "description": self.description,
            "enabled": self.enabled,
        }


class ComplianceScan(Base):
    """巡检批次：一次指定范围的巡检任务。"""

    __tablename__ = "compliance_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    scope_note: Mapped[str] = mapped_column(String(255), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scope_note": self.scope_note,
            "created_at": iso_z(self.created_at),
        }


class ComplianceRecord(Base):
    """巡检记录：终端 × 巡检项的历次结果（汇总取最新一条）。"""

    __tablename__ = "compliance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("compliance_items.id"), index=True)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("compliance_scans.id"), nullable=True, index=True)
    result: Mapped[str] = mapped_column(String(16), default="未检")  # 合规/不合规/未检
    detail: Mapped[str] = mapped_column(Text, default="")
    checked_by: Mapped[str] = mapped_column(String(64), default="")  # 用户名或 "agent"
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "item_id": self.item_id,
            "scan_id": self.scan_id,
            "result": self.result,
            "detail": self.detail,
            "checked_by": self.checked_by,
            "checked_at": iso_z(self.checked_at),
        }


class SoftwareItem(Base):
    """v2.11 软件列表：公司允许安装的软件目录（软件管理页），供工程师确认装软范围。

    授权类型：完全免费 / 部分免费 / 开源软件 / 免费商用；
    来源分三类（软件官网/项目地址/三方网站）+ 可点击跳转的 URL（v2.12 结构化）。
    """

    LICENSE_TYPES = ["完全免费", "部分免费", "开源软件", "免费商用"]
    SOURCE_TYPES = ["软件官网", "项目地址", "三方网站"]

    __tablename__ = "software_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(32), default="办公软件")  # 软件类型：办公/研发/设计/安全…
    license_type: Mapped[str] = mapped_column(String(16), default="完全免费")
    description: Mapped[str] = mapped_column(Text, default="")  # 软件描述与用途
    departments: Mapped[str] = mapped_column(String(256), default="")  # 适用部门（逗号分隔，空=全部）
    positions: Mapped[str] = mapped_column(String(256), default="")  # 适用岗位（逗号分隔，空=全部）
    source_type: Mapped[str] = mapped_column(String(16), default="软件官网")  # v2.12 来源类型
    source_url: Mapped[str] = mapped_column(String(512), default="")  # v2.12 来源地址（扫码可点击跳转）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "license_type": self.license_type,
            "description": self.description,
            "departments": [d for d in self.departments.split(",") if d],
            "positions": [p for p in self.positions.split(",") if p],
            "source_type": self.source_type,
            "source_url": self.source_url,
            "enabled": self.enabled,
            "created_at": iso_z(self.created_at),
            "updated_at": iso_z(self.updated_at),
        }
