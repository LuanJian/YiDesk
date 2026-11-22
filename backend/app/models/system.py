"""SLA 规则、智能分派/值班/模板配置与出站消息队列（可靠投递 + 重试）。"""

from __future__ import annotations

import json

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text

from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

from app.models.ticket import PRIORITY_LABELS

from app.models.user import iso_z, utcnow

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

def _loads_ids(raw: str | None) -> list[int]:

    try:

        return [int(x) for x in json.loads(raw or "[]")]

    except (ValueError, TypeError):

        return []

class SlaRule(Base):

    __tablename__ = "sla_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    priority: Mapped[str] = mapped_column(String(16), unique=True)  # low/medium/high/urgent

    response_minutes: Mapped[int] = mapped_column(Integer)

    resolve_minutes: Mapped[int] = mapped_column(Integer)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "priority": self.priority,

            "priority_label": PRIORITY_LABELS.get(self.priority, self.priority),

            "response_minutes": self.response_minutes,

            "resolve_minutes": self.resolve_minutes,

        }

class DispatchRule(Base):

    """智能分派：分类 → 工程师列表（按工单 ID 取模轮询）。"""

    __tablename__ = "dispatch_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    category: Mapped[str] = mapped_column(String(32), unique=True)

    engineer_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON [int]

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    @property

    def engineer_ids_list(self) -> list[int]:

        return _loads_ids(self.engineer_ids)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "category": self.category,

            "engineer_ids": _loads_ids(self.engineer_ids),

            "enabled": self.enabled,

        }

class DutyRule(Base):

    """值班表：weekday → 工程师列表（0=周一 … 6=周日）。"""

    __tablename__ = "duty_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    weekday: Mapped[int] = mapped_column(Integer, unique=True)  # 0-6

    engineer_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON [int]

    @property

    def engineer_ids_list(self) -> list[int]:

        return _loads_ids(self.engineer_ids)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "weekday": self.weekday,

            "weekday_label": WEEKDAY_LABELS[self.weekday],

            "engineer_ids": _loads_ids(self.engineer_ids),

        }

class KeywordRule(Base):

    """关键词派单规则（v2.7）：标题/描述命中关键词 → 直派指定工程师或改判指定分类。

    priority 数值越小越先匹配；target_engineer_id 与 target_category 二选一。

    """

    __tablename__ = "keyword_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(64), default="")

    keywords: Mapped[str] = mapped_column(Text, default="")  # 逗号/顿号分隔

    target_engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    target_category: Mapped[str] = mapped_column(String(32), default="")

    priority: Mapped[int] = mapped_column(Integer, default=100)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property

    def keyword_list(self) -> list[str]:

        return [k.strip() for k in self.keywords.replace("，", ",").split(",") if k.strip()]

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "name": self.name,

            "keywords": self.keyword_list,

            "target_engineer_id": self.target_engineer_id,

            "target_category": self.target_category or None,

            "priority": self.priority,

            "enabled": self.enabled,

            "note": self.note,

            "created_at": iso_z(self.created_at),

        }

class DeptRoute(Base):

    """组织架构路由（v2.7）：提单部门 → 工程师列表（部门内轮询/加权），优先于分类规则。"""

    __tablename__ = "dept_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    department: Mapped[str] = mapped_column(String(64), unique=True)

    engineer_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON [int]

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    @property

    def engineer_ids_list(self) -> list[int]:

        return _loads_ids(self.engineer_ids)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "department": self.department,

            "engineer_ids": _loads_ids(self.engineer_ids),

            "enabled": self.enabled,

        }

class TicketTemplate(Base):

    """工单模板：分类对应的自定义字段定义。fields JSON: [{key,label,type,options,required,visible_if}]"""

    __tablename__ = "ticket_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(64))

    category: Mapped[str] = mapped_column(String(32), index=True)

    priority: Mapped[str] = mapped_column(String(16), default="medium")

    fields: Mapped[str] = mapped_column(Text, default="[]")  # JSON

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # v2.2 审批节点：提交后需主管审批，通过才进入待受理

    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    # v2.2 AD 联动：审批通过后触发的脚本名（限授权目录内 .ps1，由域内代理执行）

    ad_script: Mapped[str] = mapped_column(String(128), default="")

    # v2.7 预估处理时长（分钟）：长耗时隔离/打散依据；0 = 未设置

    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "name": self.name,

            "category": self.category,

            "priority": self.priority,

            "fields": json.loads(self.fields or "[]"),

            "enabled": self.enabled,

            "require_approval": self.require_approval,

            "ad_script": self.ad_script,

            "estimated_minutes": self.estimated_minutes,

        }

class AdJob(Base):

    """AD 联动任务（v2.2）：审批通过生成，域内代理机拉取执行并回传结果。"""

    __tablename__ = "ad_jobs"

    STATUS_PENDING = "pending"

    STATUS_RUNNING = "running"

    STATUS_DONE = "done"

    STATUS_FAILED = "failed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)

    script: Mapped[str] = mapped_column(String(128))

    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON：ticket_no/title/custom_fields

    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)

    result: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "ticket_id": self.ticket_id,

            "script": self.script,

            "payload": json.loads(self.payload or "{}"),

            "status": self.status,

            "result": self.result,

            "created_at": iso_z(self.created_at),

            "finished_at": iso_z(self.finished_at),

        }

class OutboxMessage(Base):

    """出站通知：先落库再投递，失败自动重试（后台任务每分钟扫一次）。"""

    STATUS_PENDING = "pending"

    STATUS_SENT = "sent"

    STATUS_FAILED = "failed"

    __tablename__ = "outbox_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    channel: Mapped[str] = mapped_column(String(16))  # dingtalk/feishu/wecom

    receiver_id: Mapped[str] = mapped_column(String(128))  # 平台侧 userid/open_id

    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(200), default="")

    content: Mapped[str] = mapped_column(Text, default="")

    url: Mapped[str] = mapped_column(String(500), default="")  # 卡片跳转链接

    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0)

    last_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "channel": self.channel,

            "receiver_id": self.receiver_id,

            "ticket_id": self.ticket_id,

            "title": self.title,

            "content": self.content,

            "status": self.status,

            "attempts": self.attempts,

            "last_error": self.last_error,

            "created_at": iso_z(self.created_at),

        }

class BackupPlan(Base):

    """备份定时计划（v2.5）：多条并存，按频率/时间自动产出备份文件并按 keep_last 轮换。"""

    __tablename__ = "backup_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(64))

    format: Mapped[str] = mapped_column(String(16), default="sqlite")  # sqlite/json/csv

    frequency: Mapped[str] = mapped_column(String(16), default="daily")  # daily/weekly/monthly

    time: Mapped[str] = mapped_column(String(5), default="02:00")  # HH:MM（公司时区）

    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # weekly：0=周一…6=周日

    month_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # monthly：1-28

    keep_last: Mapped[int] = mapped_column(Integer, default=10)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_run_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 当地日期，防同日重跑

    last_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "name": self.name,

            "format": self.format,

            "frequency": self.frequency,

            "time": self.time,

            "weekday": self.weekday,

            "month_day": self.month_day,

            "keep_last": self.keep_last,

            "enabled": self.enabled,

            "last_run_at": iso_z(self.last_run_at),

            "last_run_date": self.last_run_date,

            "last_error": self.last_error,

            "created_at": iso_z(self.created_at),

        }
