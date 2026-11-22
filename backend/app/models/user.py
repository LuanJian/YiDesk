"""用户与身份绑定。IM 建单时按平台 userid 自动注册员工账号。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String

from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

def utcnow() -> datetime:

    """统一 naive UTC（SQLite 无时区，存取一致；序列化时补 Z 标记）。"""

    return datetime.now(timezone.utc).replace(tzinfo=None)

def iso_z(dt: datetime | None) -> str | None:

    """序列化为 ISO8601，UTC 时间补 Z 后缀，前端可正确转本地时区。"""

    if dt is None:

        return None

    return dt.isoformat() + ("Z" if dt.tzinfo is None else "")

class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    name: Mapped[str] = mapped_column(String(64), default="")

    role: Mapped[str] = mapped_column(String(16), default="employee")  # admin/engineer/employee

    department: Mapped[str] = mapped_column(String(64), default="")

    email: Mapped[str] = mapped_column(String(128), default="")

    phone: Mapped[str] = mapped_column(String(32), default="")

    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # v2.1 类目数据权限：JSON 字符串数组，空 = 全部分类可见（仅约束工程师）

    category_scope: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # v2.4 岗位（仅 engineer 生效）：remote 远程运维 / field 现场运维 / other 综合处理

    ops_type: Mapped[str] = mapped_column(String(16), default="remote")

    # v2.7 在岗状态：on_duty 在岗 / leave 请假（请假者从所有分派候选池剔除）

    status: Mapped[str] = mapped_column(String(16), default="on_duty")

    # v2.8 部门管理员：可查看本部门全部工单（creator 部门 = 自己部门）

    dept_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # 后台访问安全密钥（每账号一枚，管理员在用户列表生成/重置）。

    # 空 = 该账号未启用密钥门禁；生成后该账号登录后台必须持密钥（准入链接或登录携带）

    gate_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    # 个人通知偏好 JSON（{"status_change":true,"urge":true,"urgent":true}）；空 = 全部开启

    notify_prefs: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 三平台身份绑定（首次 IM 建单自动写入）

    dingtalk_userid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    feishu_open_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    wecom_userid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "username": self.username,

            "name": self.name,

            "role": self.role,

            "department": self.department,

            "email": self.email,

            "phone": self.phone,

            "is_active": self.is_active,

            "has_password": self.password_hash is not None,

            "category_scope": self.category_scope_list,

            "ops_type": self.ops_type or "other",

            "dept_admin": bool(self.dept_admin),

            "status": self.status or "on_duty",

            "notify_prefs": self.notify_pref_map,

            "dingtalk_userid": self.dingtalk_userid,

            "feishu_open_id": self.feishu_open_id,

            "wecom_userid": self.wecom_userid,

            "created_at": iso_z(self.created_at),

        }

    @property

    def notify_pref_map(self) -> dict:

        """通知偏好字典；未设置或缺项均视为开启（仅显式 false 才关闭）。"""

        import json

        if not self.notify_prefs:

            return {}

        try:

            data = json.loads(self.notify_prefs)

            return data if isinstance(data, dict) else {}

        except (ValueError, TypeError):

            return {}

    def notify_enabled(self, kind: str) -> bool:

        return self.notify_pref_map.get(kind, True) is not False

    @property

    def category_scope_list(self) -> list[str]:

        """类目数据权限列表；空列表 = 全部分类。"""

        import json

        if not self.category_scope:

            return []

        try:

            data = json.loads(self.category_scope)

            return data if isinstance(data, list) else []

        except ValueError:

            return []

    def in_category_scope(self, category: str) -> bool:

        """该工程师是否可见此分类（管理员调用方自行放行）。"""

        scope = self.category_scope_list

        return not scope or category in scope
