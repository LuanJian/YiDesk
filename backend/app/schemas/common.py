"""请求/响应 Pydantic 模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.ticket import PRIORITIES

# ---- Auth ----

class LoginIn(BaseModel):
    username: str
    password: str
    # 后台访问安全密钥（管理员/工程师登录时随 URL 准入携带；员工登录无需）
    gate_key: str | None = None


class PasswordChangeIn(BaseModel):
    old_password: str = ""
    new_password: str = Field(min_length=6, max_length=64)


# ---- Users ----

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    name: str
    role: str = "employee"
    department: str = ""
    email: str = ""
    phone: str = ""
    password: str = Field(default="", max_length=64)
    # v2.4 岗位（仅 engineer 生效）
    ops_type: str = "remote"
    # 第二十七批+：类目权限（仅 engineer 生效；空 = 全部分类）
    category_scope: list[str] | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    password: str | None = None  # 管理员重置
    category_scope: list[str] | None = None  # v2.1 类目数据权限（空数组=全部）
    ops_type: str | None = None  # v2.4 岗位：remote/field/other
    status: str | None = None  # v2.7 在岗状态：on_duty/leave
    dept_admin: bool | None = None  # v2.8 部门管理员（员工）：可看本部门工单


# ---- Tickets ----

class TicketCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = ""
    category: str = "其他"
    priority: str = "medium"
    asset_id: int | None = None
    custom_fields: dict = Field(default_factory=dict)
    # 扫码建单：二维码标签 code（服务端解析标签，防客户端伪造位置/设备）
    qr_code: str | None = None
    # v2.0 提出者（代报修）：creator 是提交人，requester 是实际报修人
    requester_id: int | None = None
    # v2.8 优先级矩阵：影响范围 × 紧急程度（两者都填时自动计算 priority，覆盖手选值）
    impact: str | None = None   # individual / department / company
    urgency: str | None = None  # low / normal / high / critical
    # v2.12 软件安装申请：从软件目录选择，快照进 custom_fields（服务端校验，防伪造）
    software_id: int | None = None

    @field_validator("priority")
    @classmethod
    def _priority(cls, v: str) -> str:
        if v not in PRIORITIES:
            raise ValueError(f"优先级必须是 {PRIORITIES} 之一")
        return v


class TicketEditIn(BaseModel):
    """v2.0 工单编辑：标题/描述/优先级（留空 = 不修改）。"""

    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    priority: str | None = None

    @field_validator("priority")
    @classmethod
    def _priority(cls, v: str | None) -> str | None:
        if v is not None and v not in PRIORITIES:
            raise ValueError(f"优先级必须是 {PRIORITIES} 之一")
        return v


class MergeIn(BaseModel):
    target_id: int


class TicketCommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class TicketTransitionIn(BaseModel):
    action: str
    note: str = ""
    solution: str = ""  # v2.12 完结（确认已解决）时的解决方案（内部归档）


class SlaSuspendIn(BaseModel):
    """SLA 挂起备注（体可整体省略为 {}）。"""

    note: str = ""


class AssignIn(BaseModel):
    engineer_id: int | None = None  # 缺省 = 当前用户（接单）
    reason: str = ""  # v2.4.1 改派必填原因（首派/自动派无需）


class BatchIdsIn(BaseModel):
    """第三十七批：批量操作工单 id 列表。"""

    ticket_ids: list[int]


class BatchAssignIn(BatchIdsIn):
    engineer_id: int
    reason: str = ""  # 改派原因（对已有处理人的单必填由 assign_ticket 校验）


class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str = ""


# ---- Knowledge / Asset ----

class KnowledgeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""  # 解决方法
    problem: str = ""  # v2.12 问题描述
    category: str = "常见问题"
    tags: list[str] = []
    source: str = ""  # v2.11 信息来源（自述/官方文档/链接等）
    public_visible: bool = False  # 第二十二批：匿名可见（勾选后出现在登录页公开 FAQ）


class AssetIn(BaseModel):
    asset_tag: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    category: str = "电脑"
    location: str = ""
    status: str = "在用"
    owner_id: int | None = None
    note: str = ""
    ip_address: str = ""
    model: str = ""
    vendor: str = ""  # 第四十一批：品牌（与型号分列存储）
    driver_url: str = ""  # v2.12 驱动下载地址（打印机等设备）
    expire_date: str | None = None  # 第三十八批：到期日期 YYYY-MM-DD（维保/租期）


# ---- Admin ----

class SlaRuleIn(BaseModel):
    priority: str
    response_minutes: int = Field(ge=1)
    resolve_minutes: int = Field(ge=1)


class RuleIdsIn(BaseModel):
    """分类分派规则 / 值班表通用结构。"""

    category: str = ""  # 值班表为空
    weekday: int | None = None  # 值班表 0-6
    engineer_ids: list[int] = []
    enabled: bool = True


class TemplateFieldIn(BaseModel):
    key: str
    label: str
    type: str = "text"  # text / textarea / select
    options: list[str] = []
    required: bool = False
    # v2.1 字段级联：{"field": "other_key", "in": ["值1"]} —— 参照字段值在 in 内才显示
    visible_if: dict | None = None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    category: str
    priority: str = "medium"
    fields: list[TemplateFieldIn] = []
    enabled: bool = True
    # v2.2 审批节点 + AD 联动
    require_approval: bool = False
    ad_script: str = ""
    # v2.7 预估处理时长（分钟）：长耗时隔离/打散依据
    estimated_minutes: int = Field(default=0, ge=0, le=24 * 60)


# ---- 开放平台（v2.2） ----

class WebhookIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    secret: str = Field(min_length=8, max_length=128)
    events: list[str] = []
    enabled: bool = True


class WebhookUpdateIn(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=500)
    secret: str | None = Field(default=None, min_length=8, max_length=128)
    events: list[str] | None = None
    enabled: bool | None = None


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class AdJobResultIn(BaseModel):
    """AD 代理机回传执行结果。"""

    success: bool
    output: str = ""
