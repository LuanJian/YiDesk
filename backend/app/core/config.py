"""应用配置：config.yaml + 环境变量覆盖。

优先级：环境变量 > config.yaml > 代码默认值。

config.yaml 不存在时使用默认值并打印告警，保证首次启动即可用。

"""

from __future__ import annotations

import os

from pathlib import Path

from typing import Any

import yaml

from pydantic import BaseModel, Field

class DingTalkConfig(BaseModel):

    """钉钉企业内部应用（机器人 + 工作通知）。Stream 模式，免公网回调。"""

    enabled: bool = False

    client_id: str = ""  # 应用 AppKey（即 client_id）

    client_secret: str = ""  # 应用 AppSecret

    robot_code: str = ""  # 机器人编码，默认取 client_id

    agent_id: int = 0  # 应用的 AgentId（发工作通知必需，开发者后台-应用信息页可查）

    # 卡片平台互动卡片模板 ID（可选）：配置后通知以互动卡片发送，

    # 按钮可在卡片内直接接单/确认；未配置时退回工作通知（按钮为链接跳转）

    card_template_id: str = ""

class FeishuConfig(BaseModel):

    """飞书自建应用（机器人）。WebSocket 长连接，免公网回调。"""

    enabled: bool = False

    app_id: str = ""

    app_secret: str = ""

class MailConfig(BaseModel):

    """邮件通知渠道（SMTP）：覆盖未绑定 IM 的用户（按 User.email 匹配）。"""

    enabled: bool = False

    smtp_host: str = ""

    smtp_port: int = 465

    username: str = ""

    password: str = ""

    use_tls: bool = True  # 465 为 SSL 直连；587 STARTTLS 视服务器要求调整

    from_addr: str = ""  # 发件人，留空取 username

class WeComConfig(BaseModel):

    """企业微信自建应用。发送通知不需要公网；接收消息回调需公网 HTTPS。"""

    enabled: bool = False

    corp_id: str = ""

    agent_id: int = 0

    corp_secret: str = ""

    # 接收回调（需公网可达时开启，配合 frp 等内网穿透）

    callback_enabled: bool = False

    callback_token: str = ""

    callback_encoding_aes_key: str = ""

class SlaPriority(BaseModel):

    response_minutes: int = 60

    resolve_minutes: int = 480

class SlaConfig(BaseModel):

    """按优先级的 SLA 规则（分钟）。入库后可在管理台调整。"""

    low: SlaPriority = Field(default_factory=lambda: SlaPriority(response_minutes=480, resolve_minutes=2880))

    medium: SlaPriority = Field(default_factory=lambda: SlaPriority(response_minutes=120, resolve_minutes=960))

    high: SlaPriority = Field(default_factory=lambda: SlaPriority(response_minutes=30, resolve_minutes=240))

    urgent: SlaPriority = Field(default_factory=lambda: SlaPriority(response_minutes=10, resolve_minutes=60))

    # 超时预警阈值：按剩余时限百分比（默认剩余 20% 时预警；原固定 10 分钟模式已废弃）

    warning_percent: int = 20

    # 工作日历：enabled=false 时按 7x24 自然时间计算；enabled=true 按工作时间推进

    # workdays 用 Python weekday 约定：0=周一 … 6=周日

    # holidays：法定节假日/额外休息日（YYYY-MM-DD，视为非工作日）

    # extra_workdays：调休上班日（YYYY-MM-DD，即使是周末也视为工作日）

    work_hours: dict = Field(

        default_factory=lambda: {

            "enabled": False, "start": "09:00", "end": "18:00",

            "workdays": [0, 1, 2, 3, 4],

            "holidays": [], "extra_workdays": [],

        }

    )

class DispatchWeightConfig(BaseModel):

    """算法派单打分权重（v2.1）：score = 加权和，越大越优先。"""

    close: float = 3.0    # 完结率（解决且未被重开 / 已完结）

    speed: float = 2.0    # 速度（1 - 归一化平均解决时长）

    sat: float = 2.0      # 满意度（平均星级 / 5）

    load: float = 2.0     # 未结负载（惩罚项）

    urge: float = 1.0     # 被催率（惩罚项）

    reopen: float = 1.0   # 重开率（惩罚项）

    sla_urgent: float = 1.0  # SLA 紧迫度（惩罚项：名下最紧急单的剩余时间越少扣越多，v2.8）

class DispatchConfig(BaseModel):

    auto_assign: bool = True  # 建单后按分类规则/值班表自动指派

    sticky_same_category: bool = True  # 同类型工单优先指派同一工程师（粘性派单）

    max_open: int = 8  # 工程师未结工单上限：粘性选中的人超载则回退轮询

    # v2.1 算法派单：round_robin 轮询（默认，行为同 v2.0）| weighted 按负载+绩效加权打分

    mode: str = "round_robin"

    weights: DispatchWeightConfig = Field(default_factory=DispatchWeightConfig)

    window_days: int = 90   # 绩效统计窗口

    min_samples: int = 5    # 样本少于该值的工程师不参与加权（退回轮询，防冷启动偏差）

    # v2.4 分派按岗位路由：分类 → 岗位（remote/field）；映射未覆盖的分类不限制岗位。

    # 岗位过滤后池为空时回退不过滤（避免无对应岗位人员时死锁）

    ops_type_map: dict[str, str] = Field(

        default_factory=lambda: {

            "软件安装": "remote",

            "账号权限": "remote",

            "网络故障": "field",

            "硬件设备": "field",

            "打印设备": "field",

        }

    )

    # 扫码建单（位置码/设备码）默认派给现场运维——管理员与其他远程工程师可自行转入处理；

    # 空则不覆盖，按 ops_type_map 分类映射路由。指定派单码仍直派绑定工程师。

    qr_ops_type: str = "field"

    # 「其他问题」分类延迟分派——建单后该分钟数内不做任何指派（挂接单广场可被认领）

    # 超时由定时任务按「当前未结最少 → 全员空闲则按顺序轮询」自动分配；0 = 关闭延迟分派

    deferred_minutes: int = 15

    # v2.7 派单引擎 v2：

    #   long_task_minutes —— 预估时长 ≥ 该值的工单视为长耗时（隔离/打散依据）

    #   max_long_tasks_per_day —— 同一工程师当日被派长耗时单上限（打散）

    #   strict_duty —— 严格值班：非当日值班工程师不参与分派（池空回退全量）

    long_task_minutes: int = 30

    max_long_tasks_per_day: int = 1

    strict_duty: bool = False

class ReportConfig(BaseModel):

    """每日工单日报：推送给全部工程师/管理员；可选钉钉群机器人播报。"""

    enabled: bool = False

    time: str = "09:00"  # 每日推送时刻 HH:MM

    dingtalk_group_webhook: str = ""  # 群自定义机器人 webhook（可选，仅放行 oapi.dingtalk.com）

class LicensesConfig(BaseModel):

    """软件许可台账：到期预警。"""

    alert_days: int = 30  # 距到期 N 天内预警

class NetworkConfig(BaseModel):

    """网络设备台账：定时连通性探活。"""

    probe_enabled: bool = False  # 默认关闭，内网按需开启

    probe_interval_seconds: int = 300

    probe_timeout_seconds: int = 2

class ComplianceConfig(BaseModel):

    """终端合规巡检：代理脚本上报凭据。为空则禁用上报接口。"""

    agent_api_key: str = ""

class WebhookConfig(BaseModel):

    """开放平台 Webhook（v2.2）：默认仅 https 且拒绝内网地址（SSRF 防护）。"""

    allow_private_network: bool = False  # 内网对接（ITSM/CRM 多在内网）时开启

class AdIntegrationConfig(BaseModel):

    """AD 域操作联动（v2.2）：任务由域内代理机（AdJobRunner.ps1）拉取执行。"""

    enabled: bool = False

    api_key: str = ""       # 代理机拉取/回传令牌；留空复用 compliance.agent_api_key

    timeout_seconds: int = 600  # 代理侧执行超时提示值（仅文档化给脚本用）

class PriorityMatrixConfig(BaseModel):

    """优先级矩阵（v2.8）：影响范围 × 紧急程度 → 自动计算优先级，避免提交人主观拔高。"""

    company: dict[str, str] = Field(

        default_factory=lambda: {"critical": "urgent", "high": "urgent", "normal": "high", "low": "medium"}

    )

    department: dict[str, str] = Field(

        default_factory=lambda: {"critical": "urgent", "high": "high", "normal": "medium", "low": "low"}

    )

    individual: dict[str, str] = Field(

        default_factory=lambda: {"critical": "high", "high": "medium", "normal": "medium", "low": "low"}

    )

class AdAuthConfig(BaseModel):

    """PC 端 AD 域认证（v2.10）：本地账密验证失败时回退 LDAP 域验证，成功自动建号。"""

    enabled: bool = False

    server: str = ""       # 域控地址，如 ldap://dc.company.com 或 ldaps://

    base_dn: str = ""      # 搜索基，如 DC=company,DC=com

    domain: str = ""       # NETBIOS 域名，如 COMPANY（用于 DOMAIN\user 绑定）

class AppConfig(BaseModel):

    app_name: str = "YiDesk"

    host: str = "0.0.0.0"

    port: int = 8300

    # 对外可访问的基础地址（IM 卡片里的跳转链接用）

    public_base_url: str = "http://127.0.0.1:8300"

    database_url: str = ""  # 空则用 sqlite:///./data/helpdesk.db

    jwt_secret: str = "change-me-in-config-yaml"

    jwt_expire_minutes: int = 12 * 60

    # 旧版全局安全密钥（已废弃）：密钥现按账号存储于 users.gate_key，本字段仅为旧配置迁移兼容保留，勿手工填写

    gate_key: str = ""

    # 登录日志保留天数：定时任务每日清理超期记录，防长期膨胀（0=不清理）

    login_log_retention_days: int = 90

    # 首次启动初始化的管理员账号

    admin_username: str = "admin"

    admin_password: str = "admin123"

    admin_name: str = "系统管理员"

    # 工单分类（展示顺序即配置顺序）

    categories: list[str] = Field(

        default_factory=lambda: ["软件安装", "账号权限", "硬件设备", "打印设备", "网络故障", "其他问题"]

    )

    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)

    feishu: FeishuConfig = Field(default_factory=FeishuConfig)

    wecom: WeComConfig = Field(default_factory=WeComConfig)

    mail: MailConfig = Field(default_factory=MailConfig)

    sla: SlaConfig = Field(default_factory=SlaConfig)

    dispatch: DispatchConfig = Field(default_factory=DispatchConfig)

    report: ReportConfig = Field(default_factory=ReportConfig)

    licenses: LicensesConfig = Field(default_factory=LicensesConfig)

    network: NetworkConfig = Field(default_factory=NetworkConfig)

    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)

    webhook: WebhookConfig = Field(default_factory=WebhookConfig)

    ad_integration: AdIntegrationConfig = Field(default_factory=AdIntegrationConfig)

    ad_auth: AdAuthConfig = Field(default_factory=AdAuthConfig)

    priority_matrix: PriorityMatrixConfig = Field(default_factory=PriorityMatrixConfig)

    def resolved_database_url(self) -> str:

        if self.database_url:

            return self.database_url

        return f"sqlite:///{Path(__file__).resolve().parents[2] / 'data' / 'helpdesk.db'}"

def _deep_merge(base: dict, override: dict) -> dict:

    out = dict(base)

    for k, v in (override or {}).items():

        if isinstance(v, dict) and isinstance(out.get(k), dict):

            out[k] = _deep_merge(out[k], v)

        else:

            out[k] = v

    return out

def load_config() -> AppConfig:

    config_path = Path(os.environ.get("ITOPS_CONFIG", Path.cwd() / "config.yaml"))

    raw: dict[str, Any] = {}

    if config_path.exists():

        with config_path.open("r", encoding="utf-8") as f:

            raw = yaml.safe_load(f) or {}

    elif config_path.name == "config.yaml" and config_path.parent.joinpath("config.example.yaml").exists():

        # 尚未创建 config.yaml 时回退到示例配置，保证可启动

        with config_path.parent.joinpath("config.example.yaml").open("r", encoding="utf-8") as f:

            raw = yaml.safe_load(f) or {}

    data = AppConfig().model_dump()

    merged = _deep_merge(data, raw)

    # ITOPS_JWT_SECRET 等环境变量优先

    for env_key, field in [

        ("ITOPS_JWT_SECRET", "jwt_secret"),

        ("ITOPS_ADMIN_PASSWORD", "admin_password"),

        ("ITOPS_PUBLIC_BASE_URL", "public_base_url"),

    ]:

        val = os.environ.get(env_key)

        if val:

            merged[field] = val

    return AppConfig(**merged)

_config: AppConfig | None = None

def get_config() -> AppConfig:

    global _config

    if _config is None:

        _config = load_config()

    return _config

def reset_config() -> None:

    """测试辅助：强制下次重新加载。"""

    global _config

    _config = None
