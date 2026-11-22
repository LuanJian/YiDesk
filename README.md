# YiDesk

对接**钉钉 / 飞书 / 企业微信**的企业内部 IT 工单台。员工在 IM 里发一条消息即可报修，IT 团队在 Web 管理台受理、流转、闭环，配套 SLA 超时催办、满意度评价、统计看板、知识库与轻量资产关联。

## 关于 YiDesk（命名含义）

**YiDesk = 驿（Yì）+ Desk（服务台）**。驿，取自「驿站」——中国古代传递官方文书的节点：文书抵达驿站，登记、分拣、派送、回执归档，全程留痕可查。工单亦是如此：员工的问题送达 YiDesk，在此受理、指派、处理、评价、归档——一座连接员工与 IT 团队的数字驿站。界面与产品名统一使用 **YiDesk**，中文语境下亦可直接称「驿站」。

> 面向场景：公司内部 IT 服务台。纯内网部署可用（钉钉/飞书免公网回调），单进程单端口即可运行。
>
> **本文是项目唯一完整说明**：功能总览、架构、部署与三平台开通、各功能配置与使用、设计存档、API、测试、路线图与常见问题都在这里。

---

## 目录

- [功能总览](#功能总览)
- [系统亮点](#系统亮点)
- [系统架构](#系统架构)
- [快速开始](#快速开始本机开发)
- [部署手册](#部署手册生产)
- [三平台接入指引](#三平台接入指引)
- [各功能配置与使用](#各功能配置与使用)
- [工单派单规则总览](#工单派单规则总览)
- [API 概览](#api-概览)
- [目录结构](#目录结构与模块实现逻辑)
- [MySQL 迁移](#mysql-迁移演练指南上线前必做)
- [压力测试与容量](#压力测试与容量建议实测)
- [测试](#测试)
- [安全设计要点](#安全设计要点)
- [开发路线图](#开发路线图)
- [常见问题](#常见问题)
- [许可证](#许可证license)
- [变更历史](CHANGELOG.md)

---

## 界面预览

| 工单列表 | 数据看板 |
|---|---|
| ![工单列表](docs/screenshots/tickets.png) | ![数据看板](docs/screenshots/analytics.png) |
| **工单详情** | **会议管理** |
| ![工单详情](docs/screenshots/ticket-detail.png) | ![会议管理](docs/screenshots/meetings.png) |

## 功能总览

| 模块 | 功能点 |
|---|---|
| **智能分派** | 按「分类规则 → 值班表」自动指派：命中分类规则在该规则工程师内轮询（当班者优先），未命中按当日值班轮询；**同分类粘性**——同类工单优先派给当前持有该类单最多的工程师（超过未结上限自动回退轮询）；**岗位路由**（软件→远程、设备→现场，可配）；管理台可视化配置 |
| **派单引擎 v2（v2.7）** | **关键词规则库**（标题/描述命中 → 直派工程师或改判分类，优先级+回退留痕）；**长耗时隔离/打散**（模板预估时长 ≥ 阈值的单暂出候选池、当日长耗时派单上限）；**严格值班 + 在岗状态**（请假一键切换，请假者所有候选池剔除）；**工单公海**（未指派单池 + 一键认领）；**组织架构路由**（提单部门 → 工程师池，优先于分类规则） |
| **二维码报修** | 位置码 / 设备码 / 指定派单码三种贴纸：员工扫码建单自动带位置或设备信息（型号/IP），IT 可到工位现场处理；指定码工单直接派给绑定工程师；员工再扫码可看每单的处理人与排队位次（前面还有几单），也可继续提交其他问题；**匿名提交（v2.11）**——扫码无需登录，IM 容器内自动带员工身份，浏览器/微信一律按匿名提交；设备码工单全员可见（避免同一问题重复提交）；15 分钟内重复提交提示合并；**v2.11 设备信息独立展示**——设备码工单的设备/位置/IP 在详情页独立单元格显示，不挤占问题描述。改绑定信息不用重印贴纸 |
| **工单模板** | 按分类定义自定义字段（文本/多行/下拉、必填），建单动态渲染、详情展示 |
| **重复识别与合并** | 建单时标题相似度识别疑似重复（≥60%），工程师一键合并到主单（源单关闭留痕） |
| **知识库联动** | 工单详情自动推荐相关知识文章；已解决工单一键沉淀为知识库 |
| **SLA 工作日历** | 可选工作时间（如 9:00-18:00、周一至五）内推进 SLA 时限，支持法定节假日与调休日配置，默认 7×24 |
| **每日日报** | 定时汇总昨日新建/解决、未结/超期、满意度，推送全部 IT 人员，可选钉钉群机器人播报 |
| **数据备份与恢复（v2.5）** | 三种备份：整库 zip（SQLite 快照+附件）/ JSON 全量数据包 / 工单 CSV；多条定时计划（每天/每周/每月+时间+保留份数轮换）；备份列表下载/删除；恢复=SQLite zip 覆盖库文件（需重启）或 JSON 在线重建（保留原 ID）；支持上传备份文件恢复；双重确认口令 RECOVER + 防路径穿越 |
| **工单闭环** | 待受理 → 处理中 → 待确认 → 已解决 → 已关闭；支持退回、重开、撤销、改派；全流程事件留痕（时间线） |
| **工单编辑（v2.0）** | 标题/描述/优先级可改：发起人限待受理、工程师限未结；逐字段留痕，优先级变化按新规则重算 SLA |
| **改派留痕+操作审计（v2.4.1）** | 改派必填原因（后端强制，事件记录原处理人）；管理台「操作审计」页：编辑/指派改派/SLA挂起恢复/合并/自动派单 分类统计 + 按操作人汇总 + 明细检索 |
| **SLA 挂起/解挂（v2.0）** | 「等用户回复/等配件」暂停计时：快照剩余分钟，超时扫描与催单自动暂停，恢复后按剩余时间顺延 |
| **提出者·代报修（v2.0）** | 建单可选「代谁报修」，提出者可见工单并同收通知；全员通讯录接口支撑 |
| **工单关注（v2.0）** | 工程师/主管跟单：关注后状态变更/评论同收通知；列表「我关注的」一键过滤 |
| **搜索合并（v2.0）** | 合并弹窗支持关键词/工单号搜索任意未结工单并入，解决相似度算法认不出的改写场景 |
| **算法派单（v2.1）** | `dispatch.mode: weighted`：池内按「完结率+速度+满意度 − 未结负载−被催率−重开率」加权打分选人，权重/统计窗口/最少样本可配，样本不足自动退回轮询；统计剔除 SLA 挂起时长 |
| **字段级联（v2.1）** | 模板字段带 `visible_if` 显示条件（如选「无线」才显示 AP 位置），前后端双重校验（隐藏字段带值/可见必填为空 → 400 防绕过），模板管理台可视化配置 |
| **类目数据权限（v2.1）** | 工程师可配 `category_scope`：列表/详情/分派三重过滤，超出范围的类目不可见也不参与派单 |
| **岗位权限分级（v2.4，v2.11 调整）** | 岗位维度：**全部工程师**可管理资产、查看软件许可与网络设备；现场运维额外拥有设备写、合规巡检、二维码标签；管理员全量；菜单/按钮按岗位裁剪；分派按岗位路由（ops_type_map 可配）；新增资产回收动作 |
| **开放 API + Webhook（v2.2）** | 工单事件 HMAC-SHA256 签名 POST 到订阅地址，失败自动重试；默认仅 https 且拒绝内网地址（SSRF）；只读 `GET /api/open/tickets`（X-API-Key）供 ITSM/CRM 拉取；管理台「开放平台」页可视化管理 |
| **审批节点（v2.2）** | 模板可开「主管审批」：建单先入「待审批」，管理员通过才进入待受理（SLA 从通过起算），驳回即关闭，发起人可撤回 |
| **AD 域操作联动（v2.2）** | 审批通过按模板配置生成 AD 任务，域内代理机（`scripts/AdJobRunner.ps1`）执行脚本并回写工单事件；服务端零进程执行 |
| **附件** | 截图/照片/文档上传（≤10MB，Web 端）；**IM 发图片自动作为附件建单**（钉钉/飞书） |
| **卡片内交互** | 飞书通知卡片直接「接单/确认解决/关闭/重开」（卡内回调）；钉钉支持卡片平台互动卡片回调 |
| **IM 免登** | 钉钉 JSAPI 一键登录；飞书/企微 OAuth 免登（客户端与浏览器均可） |
| **催单与加急（v2.6）** | 扫码页一键**加急处理**：推送处理人；处理人排队 >2 单时同时广播其他工程师（工单台「加急工单」池可见，**一键转办**认领到自己名下并通知发起人）；排队 ≤2 单只推送处理人不广播；与催单共用 30 分钟频控 |
| **邮件通知** | SMTP 渠道，覆盖未绑定 IM 但有邮箱的用户 |
| **导出** | 工单 CSV（UTF-8 BOM）：**按日/按月/按年/全部**四种范围（v2.4.2），带当前筛选条件；**v2.11 起导出仅管理员可用**（非管理员无任何导出权限，数据看板 CSV 同） |
| **IM 建单** | 钉钉（Stream 模式）/ 飞书（WebSocket 长连接）免公网回调；企微应用消息免公网、接收回调可开关 |
| **IM 命令** | 直接发问题描述建单；`我的工单` 查进度；`帮助` 看用法 |
| **身份打通** | 首次 IM 建单按平台 userid 自动注册绑定，管理台可维护；无需员工预先建号 |
| **通知** | 状态变更推送到发起人/处理人/关注者/提出者；Outbox 落库 + 失败自动重试（最多 5 次） |
| **SLA** | 按优先级配置响应/解决时限；剩余时限低于 20% 自动预警（`sla.warning_percent` 可配）、超时升级管理员；重开自动重新计时 |
| **满意度** | 工单解决后向发起人推送评价（1–5 星），纳入工程师统计 |
| **实时大屏（v2.7）** | 深色全屏监控页（v2.11 起独立路由全屏显示：无侧边栏/顶栏、背景铺满零留白、任意分辨率单页无滚动，「返回管理」回工单列表；**仅管理员可见**；**v2.11 刷新间隔可调** 5~60 秒/手动）：指标卡两行（**本周工单**/当前未结/今日新建/今日解决 + 平均响应/平均解决/解决达标率/满意度）+ 左侧**工单列表**（未结编号红色、已完结绿色，点击单号直达详情）+ 右侧近 30 天新建/解决柱状图 |
| **数据看板（v2.3）** | 全量快照（累计/状态分布/历史满意度）+ 日期区间与日/月/年粒度分析（工单量/时效剔除挂起/满意度分布与低分明细/高频问题 Top 占比/处理人×分类构成/提单员工部门 Top），全部指标带环比；类目权限生效；CSV 导出 |
| **知识库** | 文章 CRUD + 全文搜索，常见问题自助；**v2.11 信息来源**——每篇可登记解决出处（自述/官方文档/链接可点击），方便工程师追溯学习；**第二十批公开 Wiki**——未登录员工可经登录页入口访问公开常见问题页（问题描述+解决方法自助查阅） |
| **设备管理（v2.12 重构定位）** | **仅作设备信息登记与状态查询**（非资产归属/财务流程）：办公电脑 / 打印机 / 网络设备三页签；登记（编号/类型/位置/状态/使用人/型号/IP）、工单关联、设备码贴纸引用；**全生命周期留痕**（登记/领用/归还/回收/送修/报废时间线）；**v2.11 TCP 在线检测**；**v2.12 维修拆装部件溯源**——送修/修复完成登记时记录加装的硬盘/内存等与拆卸部件（名称+序列号+方向），时间线永久可查；维修操作仅限持有 assets.write 权限的登录工程师/管理员 |
| **软件许可台账** | 许可类型/席位/到期/成本管理，密钥脱敏（完整值仅管理员），到期与席位用满自动预警 |
| **软件列表（v2.11，v2.12 增强）** | 公司允许安装的软件目录：列序为 状态/软件名称/软件类型/授权类型/软件来源/软件描述（描述占最大宽度）；来源分 **软件官网 / 项目地址 / 三方网站** 三类标注，标签可点击新标签页直达来源地址；适用部门筛选下拉（岗位维度已移除）；员工建单选「软件应用」可从目录**申请安装**形成闭环；工程师可据此确认装软范围；管理员维护，与软件许可同页（**菜单「软件管理」**） |
| **网络设备台账** | 交换机/AP/防火墙等登记，**定时 TCP 探活**+手动检测，探活开关可配 |
| **终端合规巡检** | 巡检项可配，**PowerShell 代理脚本自动上报**（API Token 鉴权），合规率汇总，不合规**一键生成整改工单** |
| **会议室数据指标（第二十四批）** | 综合区：质量指标（平均会议时长/取消率/爽约数）+ **时段热力图**（星期×小时色块矩阵）+ **下周预约趋势**（未来 7 天柱状）+ 部门频次附 **人均场次**（按在职部门人数折算）；会议室卡片直接显示 预约/取消率/爽约/平均时长/占用/使用率 六项；no-show 依赖**到场签到**（预约人/管理员在预约开始后当天扫码页签到，未签到且已结束计为爽约，仅统计上线后预约） |
| **会议室预约管理（v2.12）** | 会议室台账（位置/容量/**设备使用说明**/维修公告）；**标签制作生成会议室码**，扫码即进预约页：全员可见预约状态（未来 14 天）与设备说明，登录员工可预约（**同时段冲突校验**，取消限本人/管理员）；**重要设备维修中扫码弹公告**并暂停预约；管理员扫码可填报**设备检查留痕**（开机/默认投屏/连接线/自动切信号/遥控器电池/麦克风六项逐项 正常/异常 + 丢失损坏报修备注，记录检查人与时间）；后台「会议管理」页查看各室预约情况与检查历史 |
| **权限** | 管理员 / 工程师 / 普通员工三角色 + 岗位分级（远程/现场/其他），JWT 登录 + **登录失败限流**（连错 5 次锁 15 分钟，v2.7）；员工只能看自己的工单 |
| **后台访问安全密钥（第二十一批，第二十二批改为每账号）** | 防止弱密码被猜测：**每个管理员/工程师账号一枚唯一密钥**（系统随机生成、不可指定不可编辑、仅可重置，入口在用户列表「操作」列「密钥」按钮）；已启用账号登录后台必须经准入链接 `http://服务器IP:8300/gate/{自己的密钥}`（30 天 HttpOnly Cookie）或登录携带；员工登录仅需访问 IP；未生成密钥的账号不受限；重置仅影响该账号 |
| **游客服务入口（第二十批）** | 登录页底部「无需登录，自助服务」三入口：**可安装软件**（公开页浏览允许安装的软件目录）、**常见问题**（公开 Wiki 自助查阅问题描述+解决方法）、**提交工单**（PC 端无实体码时经通用报修码直达匿名提单页）；公开页无侧边栏独立呈现，接口只读且不含凭据字段 |
| **工单列表增强（v2.7，v2.11 调整）** | 列字段自选显示（localStorage 偏好）；**接单广场**（超过 30 分钟未分配的工单池，工程师一键「转给我」认领并计入转交工单，v2.11）；**搜索覆盖发起人姓名/用户名**（v2.11）；标记列移除（加急由编号红色着色表达）；**关闭工单仅发起人或管理员**（工程师无主动关单权限，v2.11）；IM/群内发「查 GD-xxx」查任意工单进度 |

## 系统亮点

> 为什么选这套系统，而不是直接买一个 SaaS 工单产品——

- **一个进程跑完整套系统**：uvicorn 单进程承载 API + 钉钉 Stream/飞书长连接 + 定时任务 + 前端静态托管，一个端口部署完，纯内网可用，钉钉/飞书免公网回调——不需要公网服务器、不需要域名证书
- **一个 YAML 配置全部行为**：分类、派单权重、优先级矩阵、SLA 日历、渠道凭据、岗位映射全部集中在 `config.yaml`，改配置不改代码；旧库自动补列迁移，升级不断数据
- **成本几乎为零**：SQLite 起步（SQLAlchemy 全程 ORM，迁移 MySQL 只是换连接串），无消息队列、无 Redis、无外部中间件；通知可靠性靠 Outbox 落库重试实现，不丢消息
- **权限体系贴合真实 IT 团队**：角色（管理员/工程师/员工）× 岗位（远程/现场/其他）双维度，矩阵单一文件一处定义；管理员全量、工程师按岗位裁剪、员工只看自己，部门管理员可看本部门——菜单按钮到数据行三层隔离
- **工单全生命周期可追溯**：状态机双层校验（API 依赖 + 服务层）、每次流转/编辑/改派/SLA 挂起全留痕，改派必填原因、操作审计报表可按人按类型回溯；关单、审批、导出等敏感动作明确到人
- **派单引擎贴合作息与责任**：关键词规则 → 分类规则/部门路由 → 值班表 → 加权算法（绩效+负载+SLA 紧迫度）四级链路，粘性同类工单、长耗时隔离、请假剔除、公海接单广场——工程师少盯着屏幕抢单
- **员工触达零门槛**：IM 发消息即建单、扫码免登录匿名报修、设备码全员可见避免重复提交、会议室扫码即预约/即检查——员工不需要培训就会用
- **管理与运维场景全覆盖**：软件许可预警、资产全生命周期、设备在线探活、终端合规巡检自动生成整改单、会议室预约+设备检查留痕、实时大屏值守——桌面运维的日常都在一个系统里
- **质量有底**：125 项 pytest 覆盖状态机越权、SLA 边界、渠道加解密回环、SSRF 防护、权限矩阵、备份恢复回环等关键路径；关键接口全部服务端鉴权，密钥/许可值脱敏

## 系统架构

```
┌────────────────────────── 单进程 (uvicorn :8300) ──────────────────────────┐
│                                                                            │
│  ┌─────────┐   ┌──────────────┐   ┌──────────────────────────────────┐    │
│  │ Vue3 前端│   │  FastAPI API │──▶│  渠道适配层 channels/             │    │
│  │ dist/静态│   │  /api/*      │   │  dingtalk  Stream 长连接(收)      │    │
│  └─────────┘   └──────┬───────┘   │  feishu    WebSocket 长连接(收)   │    │
│                       │           │  wecom     REST 推送(发) + 回调   │    │
│                       ▼           └────────────┬─────────────────────┘    │
│  ┌──────────────────────────────┐              │                          │
│  │ services/ 领域服务            │◀─────────────┘                          │
│  │  状态机/SLA/通知/分派/审计      │         ┌────────────────────┐         │
│  │  看板/备份/加急/开放平台        │         │ jobs/ APScheduler  │         │
│  └──────────────┬───────────────┘         │  SLA扫描/Outbox重试 │         │
│                 ▼                         │  Webhook投递/备份扫描│         │
│  ┌──────────────────────────────┐         └────────────────────┘         │
│  │ SQLite (可迁 MySQL) + 附件    │                                        │
│  └──────────────────────────────┘                                        │
└────────────────────────────────────────────────────────────────────────────┘
```

**一次 IM 报修的完整数据流：**

```
员工在钉钉/飞书发「打印机坏了」
  → 渠道长连接收到消息，归一化为 InboundDraft
  → intake_service：按 userid 找到/自动注册用户 → 识别命令或建单
  → create_ticket：生成工单号 GD-yyyyMMdd-NNNN，按优先级写入 SLA 截止时间
  → 会话内回复「✅ 已创建工单 GD-xxx」
  → notify_ticket_created：给全部工程师/管理员入队 OutboxMessage → 推送工作通知/卡片
  → 工程师在管理台接单 → 状态机流转 → 通知发起人
  → 提交方案 → 发起人确认 → 关闭 → 推送评价卡片
  → SLA 扫描任务每分钟检查未结工单，超时预警/升级
```

## 快速开始（本机开发）

### 后端

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 配置（不创建 config.yaml 也可用默认值启动）
cp ../config.example.yaml ../config.yaml && vi ../config.yaml
```

### 前端

```bash
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run build        # 产物 dist/ 由后端自动托管
```

### 启动（项目根目录）

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8300 --app-dir backend
# 浏览器打开 http://127.0.0.1:8300，默认 admin / admin123（首启自动创建，请立即改密）
```

> ⚠️ 务必**单 worker** 启动（不加 `--workers N`）：渠道长连接与定时任务都挂在进程内。

## 部署手册（生产）

### 1. 环境与安装

- Python ≥ 3.11（生产建议 3.11/3.12）
- （可选）Node.js ≥ 18：仅重新构建前端时需要，可直接使用仓库内 `frontend/dist/` 产物

```bash
# 上传整个 itops-helpdesk 目录到服务器，如 /opt/itops-helpdesk
cd /opt/itops-helpdesk/backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 配置
cd /opt/itops-helpdesk
cp config.example.yaml config.yaml
vi config.yaml
```

`config.yaml` 必改项：

| 配置 | 说明 |
|---|---|
| `public_base_url` | 内网实际访问地址，如 `http://192.168.1.100:8300`（IM 卡片跳转 + 二维码贴纸链接用） |
| `jwt_secret` | 改成随机长字符串：`python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `admin_password` | 初始管理员密码 |
| `dingtalk/feishu/wecom` | 按下文各平台指引填入凭据并把 `enabled` 改为 `true` |

### 2. 启动与常驻运行

```bash
cd /opt/itops-helpdesk
nohup backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300 --app-dir backend > helpdesk.log 2>&1 &
```

- 访问 `http://<服务器IP>:8300` 登录管理台
- **务必单 worker**（不要加 `--workers N`）：渠道长连接、SLA 定时器都在该进程内
- SQLite 数据库在 `backend/data/helpdesk.db`，附件在 `backend/data/attachments/`，备份在 `backend/data/backups/`

systemd 常驻示例：

```ini
# /etc/systemd/system/itops-helpdesk.service
[Unit]
Description=IT Ops Helpdesk
After=network.target

[Service]
WorkingDirectory=/opt/itops-helpdesk
ExecStart=/opt/itops-helpdesk/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300 --app-dir backend
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now itops-helpdesk
```

### 3. 前端更新

```bash
cd frontend && npm install && npm run build
# dist/ 产物由后端自动托管，重启后端即可生效
```

### 4. 部署验证清单

部署完成后逐项确认：

- [ ] 管理台可登录，`admin` 改密
- [ ] 系统设置 → 渠道与系统：目标平台显示 **已连接**
- [ ] 在 IM 里给机器人发「打印机坏了」→ 收到「已创建工单 GD-xxx」回复
- [ ] 管理台工单台出现该单；受理后 IM 收到状态通知
- [ ] 提交解决方案 → 发起人确认 → 关闭 → IM 收到评价提醒
- [ ] 数据看板数据正常
- [ ] 二维码：生成一个位置码 → 打印 → 手机扫码登录 → 提交工单 → 详情里能看到「扫码位置」，提交结果里能看到分派的工程师
- [ ] 把一张工单留到超时，确认收到 SLA 预警/升级通知（可临时把响应时限调成 1 分钟验证）
- [ ] 立即做一次「整库 zip」备份并下载异地保存
- [ ] （建议）系统设置 → 用户管理 → 后台访问安全密钥：**生成密钥**，并把准入链接 `http://服务器IP:8300/gate/{密钥}` 分发给全部管理员/工程师；员工登录入口 `http://服务器IP:8300/login` 无需密钥

### 5. Docker 部署方案（可选，与 systemd 方案二选一）

Docker 方式更新回滚方便、环境隔离；systemd 更轻量。数据（SQLite/附件/备份）全部落在宿主机 `./data` 目录，两种方案可平滑切换（停旧 → 拷贝 data 与 config.yaml → 起新）。

**① 构建前端产物**（镜像内只含后端，前端 dist 需宿主机先构建）：

```bash
cd frontend && npm install && npm run build && cd ..
```

**② 准备配置**：

```bash
cp config.example.yaml config.yaml && vi config.yaml
```

必改三项：`jwt_secret`（随机长字符串）、`admin_password`（首次启动后立即改密）、`public_base_url`（准入链接与二维码指向）。

**③ 构建镜像并启动**：

```bash
docker build -t itops-helpdesk .
docker compose up -d
docker compose logs -f helpdesk   # 观察启动日志（渠道连接/定时任务注册）
```

**关键点说明**：

| 项 | 说明 |
|---|---|
| 单 worker | 镜像内 CMD 固定 uvicorn 单进程——钉钉 Stream/飞书长连接与 APScheduler 全在进程内，**禁止多副本/多 worker**（会重复消费与重复调度） |
| 数据持久化 | `./data` 挂载到容器 `backend/data`：helpdesk.db + attachments/ + backups/；升级镜像数据不受影响 |
| 配置 | `./config.yaml` 只读挂载；改配置需 `docker compose restart` |
| 时区 | 镜像内置 `TZ=Asia/Shanghai`，依赖包含 `tzdata`（slim 镜像无系统时区数据，ZoneInfo 必需）——统计口径/签到/提醒/编号日期均已按上海时区计算 |
| 健康检查 | compose 自带 healthcheck（每 60s 探测首页），`docker compose ps` 查看 healthy |
| 环境变量覆盖 | 支持 `ITOPS_JWT_SECRET`、`ITOPS_ADMIN_PASSWORD`、`ITOPS_CONFIG` 等（环境变量优先于 yaml） |

**④ 升级流程**：

```bash
cd frontend && npm install && npm run build && cd ..
git pull                              # 或同步代码
docker compose build && docker compose up -d
# 旧库自动补列/数据迁移在启动时执行（upgrade.ensure_columns + 分类更名迁移），无需手工干预
```

**⑤ 备份**：数据卷内 `./data/backups/` 已含定时备份产物；建议宿主机 cron 调用 `scripts/backup-sync.sh` 异地同步，或停止容器后直接备份整个 `./data` 目录。

**⑥ 常见问题**：
- 端口占用：compose 中改映射端口（如 `"8301:8300"`），`public_base_url` 同步修改
- data 目录权限：Linux 宿主机以非 root 运行容器时需对齐 `./data` 目录属主（默认 root）
- 首次启动：自动创建 admin 账号（密码取 config），登录后立即改密并为管理员/工程师生成安全密钥

## 三平台接入指引

| 平台 | 收消息方式 | 需要公网？ | 关键权限 |
|---|---|---|---|
| 钉钉 | Stream 模式（SDK 长连接） | ❌ | 机器人 + 工作通知 + AgentId |
| 飞书 | WebSocket 长连接 | ❌ | 机器人 + im:message + 通讯录读取 |
| 企业微信 | HTTP 回调（发送不需要） | 接收✅ 发送❌ | 自建应用 + 消息推送 |

### 钉钉开通（Stream 模式，免公网回调）

1. 登录[钉钉开放平台](https://open.dingtalk.com/) → **应用开发** → **创建应用**（企业内部应用 / H5 微应用均可）
2. **应用凭据**页：记录 `AppKey`（= `client_id`）、`AppSecret`（= `client_secret`）、`AgentId`
3. **添加应用能力 → 机器人**：消息接收模式选择 **Stream 模式**（无需公网地址）；记录机器人编码 `robotCode`（一般与 AppKey 相同）
4. **权限管理**：开通「企业内部应用-工作通知」，用于给工程师推送新工单通知
5. **版本管理与发布**：发布应用（企业内部应用发布后成员可见）
6. 使用方式：**单聊**直接给机器人发消息 → 自动建单；**群聊**把机器人拉进群，**@机器人** 说「打印机坏了」→ 自动建单
7. `config.yaml` 填写：

```yaml
dingtalk:
  enabled: true
  client_id: "dingXXXXXXXX"
  client_secret: "xxxxxxxx"
  agent_id: 123456789
  robot_code: ""      # 留空默认取 client_id
```

重启服务，管理台「系统设置 → 渠道与系统」应显示钉钉 **已连接**。

### 飞书开通（WebSocket 长连接，免公网回调）

1. 登录[飞书开放平台](https://open.feishu.cn/) → **开发者后台** → **创建企业自建应用**
2. **凭证与基础信息**：记录 `App ID`、`App Secret`
3. **添加应用能力 → 机器人**
4. **权限管理**开通：`im:message`（收发消息）、`im:message.group_at_msg:readonly`（群内 @机器人 建单）、`contact:user.base:readonly`（读取姓名用于自动注册显示名）
5. **事件与回调 → 事件配置**：订阅方式选择 **使用长连接接收事件**，添加事件 `接收消息 im.message.receive_v1`
6. **版本管理与发布**：创建版本并发布，管理员审核通过
7. `config.yaml`：

```yaml
feishu:
  enabled: true
  app_id: "cli_xxxxxxxx"
  app_secret: "xxxxxxxx"
```

使用方式同钉钉：单聊直接发，群里需 @机器人。

### 企业微信开通

**发送通知（免公网，开箱即用）：**

1. 登录[企业微信管理后台](https://work.weixin.qq.com/) → **应用管理** → **自建** → **创建应用**
2. 记录 `AgentId`、`Secret`；**我的企业 → 企业信息** 记录 `企业ID`（corp_id）
3. `config.yaml`：

```yaml
wecom:
  enabled: true
  corp_id: "wwXXXXXXXX"
  agent_id: 1000002
  corp_secret: "xxxxxxxx"
```

重启后即可收到工单通知（textcard 卡片，点击跳转管理台）。员工在企微侧「发消息建单」需要下面的回调配置。

**接收回调（需公网 HTTPS 地址，可后置）：**

企微的接收消息必须配置公网可达的 HTTPS 回调 URL。纯内网用 frp 内网穿透示例：

```ini
# frpc.ini（公网机器跑 frps，内网跑 frpc）
[itops-helpdesk]
type = https
local_ip = 127.0.0.1
local_port = 8300
custom_domains = helpdesk.example.com   # 需备案域名
```

企微管理后台 → 自建应用 → **接收消息** → 设置 API 接收：URL 填 `https://helpdesk.example.com/api/callbacks/wecom`，Token / EncodingAESKey 随机生成并**同时填入 config.yaml**；先打开开关再点企微「保存」（保存时会立刻回调验证）：

```yaml
wecom:
  callback_enabled: true
  callback_token: "企微后台生成的Token"
  callback_encoding_aes_key: "43位EncodingAESKey"
```

也可以保持 `callback_enabled: false`，一期仅用企微收通知，员工报修走钉钉/飞书或 Web。

## 各功能配置与使用

### 卡片内交互（v1.1）

- **飞书**：通知卡片自带「接单/确认解决/关闭/重开」按钮，走卡内回调（免公网）。仅需确认事件订阅为**长连接方式**。点击按钮按角色校验权限（员工点「接单」会收到无权限回复）
- **钉钉**：机器人「工作通知」的按钮是链接跳转。要在卡内直接操作：钉钉开放平台 → **卡片平台** → 创建互动卡片模板（按钮动作自定义参数需传 `ticket_action`，值为 `ticket:accept:<工单ID>` 形式），模板 ID 填入 `dingtalk.card_template_id`

### 邮件通知（v1.1）

管理台「系统设置 → 消息推送 → 邮件推送」可视化配置（写入 config.yaml，热更新）；也可直接编辑：

```yaml
mail:
  enabled: true
  smtp_host: "smtp.company.com"
  smtp_port: 465
  username: "it-helpdesk@company.com"
  password: "授权码/密码"
  use_tls: true
  from_addr: "it-helpdesk@company.com"
```

- 发件账号 = SMTP 登录账号；发件地址（From）留空自动回退账号
- **未绑定 IM 的用户**通过 SMTP 邮箱接收通知（IM 绑定与邮件并存）
- 配置后点击「发送测试」验证连通性

「用户管理」里填了邮箱的用户，通知会同时发邮件（IM 绑定与邮件并存）。

### IM 免登（v1.1）

- **飞书 / 企微**：无需额外配置，登录页自动出现 OAuth 登录按钮。飞书需在「安全设置」把 `http://<IP>:8300/login` 加入重定向白名单；企微需配置可信域名
- **钉钉**：把应用发布为**工作台应用**（首页地址填 `http://<IP>:8300`），员工在钉钉工作台打开即自动免登

### 附件（v1.1）

无需配置。文件落盘 `backend/data/attachments/`（纳入备份）；单文件 ≤10MB。

### 智能分派与值班表（v1.2，v2.11 交互调整）

系统设置 → 智能分派：**分类分派规则**（v2.11 起按工程师视角配置——选择工程师 → 勾选其负责的分类，保存后该工程师进入这些分类的轮询池；取消勾选=退出池，某分类无人负责时自动删除该规则回退值班表；下方汇总表展示每人负责的分类）；**值班表**（周一~周日各配值班工程师，未命中分类规则时按当日值班轮询）。总开关 `dispatch.auto_assign`（默认开启）。完整派单链路与各规则优先级见上文「**工单派单规则总览**」章节。

### 部门管理（v2.12 部门字典）

系统设置 → 部门管理：公司部门的**全局字典**——软件目录「适用部门」下拉、用户管理、数据看板部门筛选等组织相关引用均来自此处。登记软件时用到的新部门会**自动沉淀**进字典，也可在此手动增删；员工档案（User.department）与部门路由（DeptRoute）以此为口径。

### SLA 工作日历（v1.2）

### SLA 工作日历（v1.2）

```yaml
sla:
  work_hours:
    enabled: true          # true=按工作时间推进 SLA；false（默认）=7x24
    start: "09:00"
    end: "18:00"
    workdays: [0, 1, 2, 3, 4]   # 0=周一 … 6=周日
    holidays: ["2026-10-01"]        # 法定节假日
    extra_workdays: ["2026-09-26"]  # 调休上班日
```

启用后 SLA 截止时间只累计工作时间内分钟（跨班次顺延、跳节假日、计调休）。重开工单按日历重算。

### 每日工单日报（v1.2）

```yaml
report:
  enabled: true
  time: "09:00"
  dingtalk_group_webhook: "https://oapi.dingtalk.com/robot/send?access_token=xxx"  # 可选群播报
```

内容：昨日新建/解决、当前未结与超期、最集中分类、满意度。群播报仅放行 `oapi.dingtalk.com` 官方域名。

### 工单模板 / 相似合并 / 字段级联（v1.2 + v2.1）

- 模板：系统设置 → 工单模板，按分类配字段（文本/多行/下拉、必填），建单表单自动渲染
- 字段级联：字段可配 `visible_if` 显示条件（模板编辑表格内「显示条件」列），前后端双重校验
- 相似识别与合并：标题相似度 ≥60% 自动提示；详情页可搜索合并（v2.0）

### 台账与合规巡检（v1.3）

- **软件许可**：菜单直接使用；到期预警每日 09:30 扫描，`licenses.alert_days: 30`；密钥脱敏显示
- **网络设备**：登记后可手动探活；定时探活 `network.probe_enabled: true`（默认 300 秒，自动尝试 22/443/80/8443/8080）
- **终端合规巡检**：
  1. `compliance.agent_api_key` 配置随机串并重启
  2. 终端在「资产管理」登记（资产编号 = 上报 asset_tag）
  3. `scripts/ComplianceAgent.ps1` 分发到 Windows 终端配计划任务：

  ```
  powershell -ExecutionPolicy Bypass -File ComplianceAgent.ps1 -Server "http://工单台IP:8300" -ApiKey "你的APIKey" -AssetTag "PC-0001"
  ```

  自动检查 Defender/补丁/BitLocker；人工项由工程师登记；不合规一键「整改建单」关联资产

### 二维码报修（v2.3 前已支持，工位/设备贴纸）

**前置确认**：贴纸链接基于 `public_base_url`——先改成员工手机可访问的地址再打印；之后修改该地址需重印。手机需与服务器同内网。

管理台「二维码标签」→ 生成二维码，三选一：

| 类型 | 用途 | 关键项 |
|---|---|---|
| 位置码 | 贴工位 | 位置描述（如「5 层 B 区 12 工位」） |
| 设备码 | 贴打印机等设备 | 关联资产（先补全型号、IP） |
| 指定派单码 | 专人响应位置 | 绑定工程师；扫码提交直接派给他（离职/停用自动回退智能分派并留痕） |

三者都可配「默认分类」。弹窗内「打印贴纸」输出带名称、短码、链接的打印页。后台改绑定**不用重印**（贴纸只编码短链 `/qr/{code}`）。

员工体验：扫码 → 提交工单（位置/设备自动附上）→ 立即看到分给谁；再次扫码可见此码未结单的状态、处理人、**排队位次**，可继续提交其他问题，可**一键加急**（见下）。扫码页 v2.11 起为独立页面（无管理台侧边栏）。

### 匿名扫码提交（v2.11）

- **扫码免登录**：`/qr/{code}` 落地页公开访问，浏览器/微信扫码未登录也可提交工单；钉钉/飞书/企微容器内打开仍自动免登带员工身份
- **匿名落库**：未登录提交的工单统一记到系统用户「匿名用户」（`__anonymous__`，不可登录），工单编号/时间线/通知与正常工单一致，IT 侧完全可受理；无码的普通建单接口仍要求登录
- **设备码全员可见**：设备码下的未结工单对所有扫码者（含匿名）可见并展示提交人，避免同一设备问题被多名员工重复提交；位置码/指定码仍只显示登录用户自己的单
- **匿名合并**：匿名访客 15 分钟内重复提交同一码，弹窗提示后可直接合并到原单（仅限同码重复单）
- **匿名限制**：匿名状态不能看工单详情/留言/加急（页面提示登录后可用）；登录后恢复完整功能
- **四类码样式统一（第二十批）**：位置/设备/指定派单码与会议室码一致——顶部不再显示匿名提示条，登录引导统一为底部 `el-result` 卡片（圆图标+标题+说明+员工登录按钮）：位置码/指定派单码底部引导「登录后可跟踪进度」（匿名提交保留）、设备码提交卡内引导「登录后可提交工单」（设备码需登录提交）

### 加急与转办（v2.6）

- 员工在扫码页对未结单点「加急处理」（30 分钟频控）：处理人收到加急推送
- 处理人**排队 >2 单**（或未指派）时，同时广播其他全部 IT 人员——工单台范围筛选「加急工单」池可见，有余量的工程师点「转给我」一键认领到自己名下（自动改派留痕），发起人收到接手通知
- 排队 **≤2 单**时只推送处理人，不广播其他工程师

### 数据看板（v2.3）

管理台「数据看板」：日期区间（今天/近 7 天/近 30 天/本月/本年/自定义）+ 日/月/年粒度，全部指标带环比；含全量快照条、趋势、高频问题 Top（占总数百分比）、分类/优先级/满意度分布、处理人×分类构成、处理人明细、提单员工/部门 Top、低分单列表；CSV 导出。

**指标口径**（设计存档）：

- 新建按 `created_at`、解决按 `resolved_at` 归属区间——**上月创建本月解决的单计入本月解决量**
- 解决时长 = `resolved_at − created_at − sla_suspended_total`（剔除挂起）；待审批单不计入时效分母
- 满意度按评价计入；高频关键词过滤停用词、丢弃 ≥4 字全串，取 2-3 字窗口 Top15，百分比按区间新建总数
- 工程师只能看 `category_scope` 范围内的数据

### 岗位权限分级（v2.4，v2.11 调整）

角色（admin/engineer/employee）不变，新增**岗位维度**（仅 engineer 生效，admin 恒全量）：管理台「用户管理」编辑工程师时选择岗位。矩阵定义于 `backend/app/core/permissions.py`（单一事实源），前端按 `/auth/me` 返回的 `perms` 控制菜单/按钮显隐。

| 模块 / 操作 | admin | 远程运维 remote | 现场运维 field | 其他 other |
|---|---|---|---|---|
| 工单台 / 详情 / 流转 / 评论 / 加急 | ✓ | ✓ | ✓ | ✓ |
| 指派/改派/合并/挂起/关注/搜索合并 | ✓ | ✓ | ✓ | ✓ |
| 资产管理-查看/管理（v2.11 全工程师） | ✓ | ✓ | ✓ | ✓ |
| 软件许可-查看 / 管理（v2.11 全工程师可看） | ✓ / ✓ | ✓ / ✗ | ✓ / ✗ | ✓ / ✗ |
| 网络设备-查看 / 管理·探活（v2.11 全工程师可看） | ✓ / ✓ | ✓ / ✗ | ✓ / ✓ | ✓ / ✗ |
| 合规巡检 | ✓ | ✗ | ✓ | ✗ |
| 二维码标签管理 | ✓ | ✗ | ✓ | ✗ |
| 统计看板 / 数据看板 | ✓ | ✓（类目范围裁剪） | ✓（同左） | ✓（同左） |
| 实时大屏（v2.11 仅管理员） | ✓ | ✗ | ✗ | ✗ |
| 数据导出（v2.11 仅管理员） | ✓ | ✗ | ✗ | ✗ |
| 知识库 | ✓ | ✓ | ✓ | ✓ |
| 系统设置 / 审批 / 开放平台 / AD 联动 | ✓ | ✗ | ✗ | ✗ |

工单范围隔离由类目数据权限（category_scope）承担；分派按岗位路由在 `config.yaml`：

```yaml
dispatch:
  ops_type_map:
    软件应用: remote
    硬件设备: field
    打印设备: field
```

存量工程师升级后默认「远程运维」，请按实际分工调整。

### 开放平台与审批 + AD 联动（v2.2）

**Webhook**：系统设置 → 开放平台 → 新建订阅（https 地址 + 签名密钥 + 事件勾选）。事件 `POST` JSON 推送，带 `X-ITOps-Signature: sha256=<HMAC>` 供外部验签，失败自动重试最多 5 次。默认仅 https 且拒内网地址；内网对接放开：

```yaml
webhook:
  allow_private_network: true
```

**只读开放 API**：「开放平台」页新建 API Key（明文只显示一次，服务端仅存 SHA-256 摘要），外部以 `X-API-Key` 头调用 `GET /api/open/tickets?status=&category=&page=`。

**审批节点**：工单模板开「主管审批」（可配 AD 脚本名）→ 该分类建单先入「待审批」→ 管理员审批通过/驳回（SLA 自通过起算，驳回即关闭，发起人可撤回）。

**AD 域联动**：审批通过生成任务 → 域内机器（装 RSAT/AD 模块）部署代理并配计划任务：

```
powershell -ExecutionPolicy Bypass -File AdJobRunner.ps1 -Server "http://工单台IP:8300" -ApiKey "你的令牌" -ScriptDir "C:\itops-ad-scripts"
```

代理拉取任务 → 在 ScriptDir 执行同名 .ps1（参数 -TicketNo/-CustomFields）→ 结果回写工单事件。代理令牌用 `ad_integration.api_key`（留空复用 `compliance.agent_api_key`），`config.yaml` 开启 `ad_integration.enabled: true`。

### 数据备份与恢复（v2.5）

系统设置 → 数据备份：**立即备份**（整库 zip / JSON / CSV 三选一）、**定时计划**（多条，每天/每周/每月+时间+保留份数自动轮换）、**备份文件列表**（下载/删除/恢复）、**上传备份恢复**（.json 在线重建；.zip 覆盖整库与附件，需重启）。

- 恢复为覆盖式操作，需输入确认口令 **RECOVER**
- JSON 数据包不含附件文件（附件仅随整库 zip）；CSV 仅报表留档不作为恢复源
- 建议组合：每天凌晨整库 zip 保留 7 份 + 每周 JSON 保留 4 份；上线后立即备份一次并异地保存

### 数据导出（v2.4.2，v2.11 收紧为仅管理员）

工单台「导出」（仅管理员可见）→ 弹窗选范围：**按日 / 按月 / 按年 / 全部**（带当前列表筛选条件）；数据看板处理人 CSV 同样仅管理员。员工与工程师无任何导出权限。

### 后台访问安全密钥（第二十一批引入，第二十二批改为每账号一枚）

**作用**：防止管理员/工程师弱密码被外网猜测——**每个管理员/工程师账号持有唯一安全密钥**，已生成密钥的账号登录后台必须持密钥；普通员工登录仅需访问 `http://服务器IP:8300/login`，不受任何影响。

**生成与分发**：系统设置 → 用户管理 → 目标账号「操作」列点 **「密钥」** → 「生成密钥」。系统随机生成（`secrets.token_urlsafe(24)`，**不可指定、不可编辑**），弹窗显示密钥与该账号专属准入链接，复制发给该账号使用者：

```
http://服务器IP:8300/gate/{该账号的密钥}
```

访问链接 302 跳登录页并种准入 Cookie（HttpOnly，30 天）——期间该设备直接访问 IP 登录即可；也可在登录页 URL 追加 `?k={密钥}` 随登录提交。

**重置**：同一弹窗「重置密钥」→ **旧密钥与该账号已准入设备立即失效**（其他账号不受影响），重新分发新链接。未生成密钥的账号可直接登录（渐进启用，避免管理员锁死）。

**忘记密钥被锁的应急恢复（第五十三批补）**：
1. 本机仍在准入期（Cookie 30 天内）→ 右上角「安全密钥」自助重置；
2. 系统内还有其他管理员 → 请其在「用户管理 → 密钥」为你重置并分发新链接；
3. 唯一管理员且所有设备均被锁 → 在服务器上取回（密钥明文存储）：`sqlite3 backend/data/helpdesk.db "SELECT gate_key FROM users WHERE username='admin'"`，访问 `/gate/{取回的密钥}` 完成准入；或直接清空绕过：`UPDATE users SET gate_key=NULL WHERE username='admin'`（清空后该账号不受门禁限制，可重新启用）。

**迁移说明（第二十一批→第二十二批）**：旧版为全局单密钥（config.yaml `gate_key`）；升级后首次访问 `/gate/{旧密钥}` 自动迁移为 admin 账号的密钥并清除全局配置——旧准入链接不断。密钥仅管理员可见；错误密钥 404 不暴露门禁；与登录失败限流构成双层防护。

### 登录页游客服务入口（第二十批）

登录页底部「无需登录，自助服务」三入口，面向未登录员工：

| 入口 | 页面 | 说明 |
|---|---|---|
| 可安装软件 | `/public/softwares` | 浏览公司允许安装的软件目录（名称/类型/授权类型/适用部门/描述），仅启用项、不含任何凭据字段 |
| 常见问题 | `/public/knowledge` | Wiki 式自助查阅：左侧文章列表（可搜索标题/标签）+ 右侧详情（问题描述 + 解决方法），无法解决再提单 |
| 提交工单 | 自动跳转 `/qr/{通用码}` | PC 端无实体二维码也能提单：系统自动使用「通用报修入口」位置码进入匿名提单页，体验与扫码一致 |

公开页为独立页面（无管理台侧边栏，深色顶栏 + 返回登录按钮），对应只读接口挂在 `/api/public/*`，无需认证。

## 工单派单规则总览

> 本模块按当前代码实现梳理（2026-11-20，第三十八批后口径），一张图看懂一张工单从提交到落到处理人手里的完整决策链。实现位置：`app/api/tickets.py`（create 建单分支）、`app/services/v12_service.py`（pick_assignee / auto_assign / assign_deferred）、`app/services/qr_service.py`（指定派单码直派）、`app/jobs/scheduler.py`（延迟分派定时任务）。

### 1. 派单入口与总决策链

工单来源：管理台建单、员工扫码（位置码/设备码/指定派单码）、IM 消息建单（钉钉/飞书/企微）、登录页匿名提单。所有来源共用同一条决策链，**按以下优先级从上到下，命中即停**：

```
建单
 ├─ ① 「其他问题」分类 → 延迟分派：15 分钟内不指派，挂接单广场等认领；
 │     超时由定时任务按「未结最少→全员空闲则按顺序轮询」分配（deferred_minutes，0=关闭）
 ├─ ② 指定派单码（二维码绑定具体工程师）→ 强制直派该工程师
 │     （目标停用/请假 → 不指派、不回退，工单挂接单广场可被认领）
 └─ ③ 自动派单链（dispatch.auto_assign=true 时）：
       关键词规则 → 智能分派 pick_assignee
       （dispatch.auto_assign=false 或派单失败 → 不指派，挂接单广场可被认领）
```

### 2. 关键词规则（v2.7 KeywordRule，优先级最高的自动规则）

- 匹配范围：工单**标题 + 描述**包含规则关键词即命中；多条规则命中取 **priority 数值最小（最优先）** 的一条
- 规则动作二选一：
  - **直派**（target_engineer_id）：直接指派目标工程师；目标请假/停用/类目权限不符 → 留痕「回退智能分派」
  - **改判分类**（target_category）：把工单分类改成规则指定分类后，再走智能分派（改判后的分类参与岗位路由/粘性统计）
- 留痕：命中/回退/改判全部写系统事件，时间线可追溯

### 3. 智能分派候选池构建（pick_assignee）

```
候选池 = 分类规则工程师池 ∪ 当日值班工程师
   ↓ 过滤：在职（is_active）+ 非请假（status != leave）+ 类目权限（category_scope）
   ↓ 岗位路由：扫码单强制 qr_ops_type（默认 field 现场运维）优先；
     否则按 ops_type_map 分类映射（软件安装/账号权限→remote，网络/硬件/打印→field）；
     过滤后池空 → 回退不限岗位
   ↓ 严格值班（strict_duty，默认关）：非当日值班剔除；池空 → 回退全量
   ↓ 长耗时隔离/打散（long_task_minutes=30）：
     隔离 = 名下已有未结长耗时单的工程师暂出池；
     打散 = 当日已被派长耗时单达 max_long_tasks_per_day(1) 不再接；
     全员被隔离 → 回退不过滤（避免任务滞留）
```

- 分类规则 vs 部门路由：**部门路由优先**——提单部门命中 DeptRoute（启用中）时按部门路由的工程师池，未命中才查分类规则 DispatchRule
- 候选池为空（规则/值班都未配置或全员不可用）→ 不指派，工单挂**接单广场**由工程师自行认领

### 4. 选人算法（池内三选一，按序尝试）

| 顺序 | 算法 | 规则 | 失败回退 |
|---|---|---|---|
| ① | **同类粘性**（sticky_same_category，默认开） | 池内「同分类未结工单最多」的工程师优先——同类问题积累经验；但未结总数超过 max_open（默认 8）则放弃 | 超载 → 下一步 |
| ② | **加权算法**（dispatch.mode="weighted"，默认 round_robin 不启用） | 90 天窗口绩效打分，样本 ≥ min_samples（5）才参与：<br>`score = 3×完结率 + 2×速度 + 2×满意度 − 2×未结负载 − 1×被催率 − 1×重开率 − 1×SLA紧迫度` | 全员样本不足 → 下一步 |
| ③ | **轮询兜底** | 规则池顺序内按 `工单id % 池大小` 取人；当班工程师排在非当班之前 | 池空 → 不指派挂公海 |

### 5. 延迟分派（「其他问题」专用）

- 建单后 `deferred_minutes`（默认 15 分钟）内不做任何指派（含关键词规则也不触发），事件留痕；期间工单在**接单广场**可被任何工程师主动认领
- 超时后定时任务（每分钟扫描）调用 `assign_deferred`：
  - **全员无未结工单** → 按工程师顺序（id）依次轮询分配
  - **否则** → 派给当前未结工单最少的工程师（并列取 id 小者）
  - 候选 = 在职 + 在岗（不含请假，不筛岗位/类目权限——保证兜底必达）

### 6. 手动指派与约束

- **指派/改派**（详情页或批量操作）：管理员与工程师均可；**改派必须填写原因**（留痕「改派给 X（原处理人 Y）：原因」）
- **类目权限**：非本人指派时，目标工程师的 category_scope 不含工单分类 → 400 拦截；**自行转入不受限**（接单广场认领/指定派单码接收/关键词直派均视为本人接收）
- **批量操作**：工单管理页签勾选批量指派（合并源单与已结单自动跳过并逐单说明原因）/批量关闭
- **合并组级联**：主工单转出（指派/认领）时，全部合并源单**自动跟随转给同一工程师**——源单不可单独指派（400 提示在主工单上操作）
- **待审批工单**：审批通过（回 pending）后才进入自动派单

### 7. 配置项速查（config.yaml → dispatch 节）

| 配置 | 默认 | 说明 |
|---|---|---|
| `auto_assign` | true | 建单后自动指派总开关（关=全部挂接单广场） |
| `sticky_same_category` | true | 同类粘性派单开关 |
| `max_open` | 8 | 工程师未结上限：粘性选中者超载则回退轮询 |
| `mode` | round_robin | round_robin 轮询 / weighted 加权打分 |
| `weights.*` | close 3 / speed 2 / sat 2 / load 2 / urge 1 / reopen 1 / sla_urgent 1 | 加权打分权重 |
| `window_days` / `min_samples` | 90 / 5 | 绩效窗口 / 加权参与最低样本数 |
| `ops_type_map` | 软件安装·账号权限→remote；网络·硬件·打印→field | 分类→岗位路由（未映射不限岗位） |
| `qr_ops_type` | field | 扫码单（位置/设备码）强制岗位 |
| `deferred_minutes` | 15 | 「其他问题」延迟分派分钟数（0=关闭） |
| `long_task_minutes` / `max_long_tasks_per_day` | 30 / 1 | 长耗时阈值 / 当日长耗时打散上限 |
| `strict_duty` | false | 严格值班（非当班不参与分派） |

### 8. 设计原则：逐级回退，绝不滞留

自动派单的每一层过滤（岗位 → 严格值班 → 长耗时）与每一步选人（粘性超载 → weighted 样本不足 → 轮询池空）**失败时都回退上一级**，最坏情况不指派而挂接单广场——保证任何工单都能被工程师看到并认领，不会因规则配置错误而丢失。

## API 概览

统一前缀 `/api`，认证方式 `Authorization: Bearer <JWT>`。

| 分组 | 端点 | 说明 |
|---|---|---|
| 认证 | `POST /auth/login`（已启用密钥的账号需持自己的安全密钥：准入 Cookie 或 body `gate_key`）、`GET /auth/me`（含 perms）、`POST /auth/change-password` | 登录 / 当前用户 / 改密 |
| 用户 | `GET/POST /users`、`PATCH/DELETE /users/{id}`、`GET /users/directory` | 管理员维护；directory 全员可查（代报修选人） |
| 工单 | `GET/POST /tickets`、`GET /tickets/{id}`、`PATCH /tickets/{id}` | 列表（筛选/分页/搜索/urgent）、详情、编辑 |
| 工单流转 | `POST /tickets/{id}/transition` | accept / cancel / submit_solution / reject_solution / confirm_resolved / close / reopen / approve / reject |
| 工单协作 | `POST /tickets/{id}/comment`、`/assign`（改派必填 reason）、`/rating` | 评论、派单、评价 |
| 加急转办 | `POST /tickets/{id}/escalate`、`POST /tickets/{id}/claim`、`GET /tickets?urgent=true` | 发起人加急；工程师转办认领（v2.6） |
| SLA 挂起 | `POST /tickets/{id}/sla-suspend`、`/sla-resume` | 暂停/恢复计时（staff） |
| 工单关注 | `POST /tickets/{id}/follow`、`/unfollow`、`GET /tickets?followed=true` | 关注/取关/我关注的 |
| 合并 | `GET /tickets/{id}/merge-candidates?q=`、`POST /tickets/{id}/merge` | 搜索候选与合并 |
| 附件 | `POST /tickets/{id}/attachments` 等 | 上传/下载/预览 |
| 统计/看板 | `GET /stats/*`、`GET /analytics/dashboard`、`/analytics/export` | 快览与区间分析（staff） |
| 知识库 | `GET/POST/PATCH/DELETE /knowledge` | 全员可读，staff 可写 |
| 资产 | `GET/POST/PATCH/DELETE /assets`、`POST /assets/{id}/recover` | 读取全员；写限现场运维/管理员；回收留痕 |
| 许可/设备/合规 | `/licenses`、`/network-devices`、`/compliance` | 按岗位权限分级 |
| 二维码 | `/qr-tags` CRUD、`/qr-tags/{id}/qr.png`、`GET /qr/{code}` | 管理与扫码页数据 |
| 操作审计 | `GET /admin/audit/summary`、`/admin/audit/events` | 仅管理员 |
| 数据备份 | `GET/POST /admin/backups`、`/plans` CRUD、`/{file}/download`、`/restore/{file}`、`/import` | 仅管理员；RECOVER 口令 |
| 开放平台 | `/webhooks` CRUD、`/webhooks/api-keys`、`GET /open/tickets`、`/ad/jobs/*` | 订阅/Key/只读拉取/AD 代理 |
| 管理 | `GET /admin/info`、SLA/分派/值班/模板/渠道配置、`/callbacks/wecom` | 管理与回调 |
| 安全密钥 | `GET/POST /users/{id}/gate-key[/reset]` | 每账号一枚：查看 / 随机生成重置（仅管理员，重置即旧密钥失效）；仅限管理员/工程师账号 |
| 公开接口 | `GET /public/softwares`、`GET /public/knowledge[/{id}]`、`GET /public/general-qr` | 无需认证：软件目录 / FAQ 列表与详情 / 通用提单码（PC 端提单入口） |
| 页面准入 | `GET /gate/{key}`（非 /api 前缀） | 安全密钥准入：匹配任一账号密钥则 302 登录页 + HttpOnly Cookie（30 天），错误 404 |

## 目录结构与模块实现逻辑

```
itops-helpdesk/
├── backend/
│   ├── app/
│   │   ├── main.py          # 入口：初始化 DB（create_all + ensure_columns 补列）、挂路由、启动渠道与定时任务、托管前端
│   │   ├── core/
│   │   │   ├── config.py    # pydantic-settings 加载 config.yaml（全部配置项 + 默认值）
│   │   │   ├── security.py  # JWT 签发/验证、bcrypt 密码哈希
│   │   │   ├── deps.py      # get_current_user / require_staff / require_admin 依赖
│   │   │   └── permissions.py # 岗位权限矩阵（PERM_MATRIX：remote/field/other → 权限集合），require_perm 工厂
│   │   ├── models/
│   │   │   ├── user.py      # User（角色+岗位+类目权限+在岗状态）、三方身份绑定
│   │   │   ├── ticket.py    # Ticket（状态机 ACTIONS 字典 + SLA 字段 + 加急/转交标记）、TicketEvent（时间线）、TicketFollower
│   │   │   ├── system.py    # SlaRule/DispatchRule/DutyRule/TicketTemplate(审批+AD)/KeywordRule/DeptRoute/AdJob/OutboxMessage/BackupPlan
│   │   │   ├── knowledge.py # KnowledgeArticle + Asset（含 IP/型号）
│   │   │   ├── qr.py        # QrTag（位置码/设备码/指定派单码）
│   │   │   ├── webhook.py   # WebhookSubscription + WebhookDelivery（HMAC 签名投递）
│   │   │   └── ...
│   │   ├── schemas/         # Pydantic 请求/响应模型
│   │   ├── api/             # 路由层（见 API 概览）：含 public.py 公开只读接口（软件目录/FAQ/通用提单码）与 gate 准入
│   │   ├── services/
│   │   │   ├── ticket_service.py    # 工单状态机（apply_transition）+ 建单（审批/矩阵/关键词/字段校验）+ SLA 挂起恢复 + 加急
│   │   │   ├── v12_service.py       # 智能分派（粘性→加权→轮询 + 岗位路由 + 长耗时隔离 + 严格值班 + 部门路由）+ 相似识别 + 日报
│   │   │   ├── sla_service.py       # SLA 扫描：预警→升级→解决超时（跳过挂起中工单）
│   │   │   ├── notify_service.py    # Outbox 通知（IM/邮件）+ 关注者/提出者/部门管理员通知扇出
│   │   │   ├── intake_service.py    # IM 消息→建单（关键词/自动注册/审批跳过必填/进度查询）
│   │   │   ├── qr_service.py        # 扫码标签解析/建单覆盖/排队位次
│   │   │   ├── analytics_service.py # 数据看板聚合（区间+粒度分桶+环比）
│   │   │   ├── webhook_service.py   # Webhook HMAC 签名投递 + SSRF 防护 + 重试
│   │   │   ├── backup_service.py    # 三格式备份 + 恢复/导入 + 轮换
│   │   │   └── ad_service.py        # AD 联动任务管理（域内代理拉取-执行-回传）
│   │   ├── channels/        # 渠道适配：dingtalk(Stream)/feishu(WS)/wecom(回调+推送)/mail(SMTP)
│   │   └── jobs/            # APScheduler：SLA扫描(60s)/Outbox重试(60s)/Webhook投递(60s)/备份扫描(5min)/日报/探活/许可预警
│   ├── tests/               # pytest 135 例（全功能覆盖，含权限矩阵/回环/跨期/审计/安全密钥门禁）
│   ├── data/                # helpdesk.db + attachments/ + backups/
│   └── requirements.txt
├── frontend/                # Vue3 + TS + Element Plus + ECharts + Pinia
│   └── src/views/           # Login(含游客服务入口)/TicketList(工单列表)/TicketDetail/QrView(扫码报修+预约)/QrTag(标签制作)/Screen(实时大屏)/Analytics(数据看板)/Knowledge(常见问题)/PublicSoftwares(公开软件页)/PublicKnowledge(公开FAQ页)/MeetingManage(会议管理)/Audit(操作审计)/Asset/License/Device/Compliance/NetworkDevice/Settings
├── scripts/                 # ComplianceAgent.ps1（合规代理）、AdJobRunner.ps1（AD 联动代理）、backup-sync.sh（备份同步）
├── Dockerfile + docker-compose.yml  # 容器化部署
├── config.example.yaml      # 配置模板（含全部注释）
└── README.md                # 本文档（唯一完整说明）
```

### 核心模块实现逻辑

| 模块 | 实现逻辑 |
|---|---|
| **工单状态机** | `ACTIONS` 字典定义合法流转（from→to），`apply_transition` 统一入口：权限校验→状态变更→事件留痕→Webhook 发射→通知扇出。所有变更必经此入口 |
| **智能分派** | `pick_assignee` 四段链路：①关键词规则直派（建单时匹配）→ ②同类粘性（池内同类未结最多者，超 max_open 回退）→ ③weighted 算法（绩效打分，样本不足退回）→ ④轮询（当班优先）。池经过：请假过滤+类目权限+岗位路由+长耗时隔离+严格值班 五重过滤，每级池空自动回退上一级 |
| **SLA 引擎** | 建单按优先级写入截止时间（工作日历可选）；扫描任务每 60s 检查：预警→升级管理员→解决超时。挂起时快照剩余分钟并跳过扫描，恢复后按剩余时间顺延 |
| **岗位权限** | `PERM_MATRIX` 矩阵定义岗位→权限集合映射；`require_perm` 依赖注入到端点；前端按 `/auth/me` 的 perms 显隐菜单/按钮。后端为唯一执行点 |
| **优先级矩阵** | config `priority_matrix` 定义影响范围×紧急程度→优先级映射；建单时两者都填则自动计算覆盖手选值 |
| **审批节点** | 模板 `require_approval` → 建单入 `pending_approval` → admin 通过（SLA 起算+可触发 AD 任务）或驳回关闭 |
| **数据备份** | `BackupPlan` 定时计划 → `backup_service.run_due_plans` 每 5 分钟扫描 → 产出 zip/json/csv → keep_last 轮换；恢复走 RECOVER 确认+白名单文件名 |
| **Webhook** | 事件先落 `webhook_deliveries` → 投递带 HMAC 签名 → 失败重试 5 次 → SSRF 防护（https+拒内网） |
| **数据看板** | `analytics_service.dashboard` 一次返回全部块（区间+粒度分桶+环比），解决类指标按 resolved_at 归属、时效剔除挂起、满意度按评价计入；权限按 category_scope 裁剪 |
| **安全密钥门禁** | 每账号一枚（`User.gate_key`，空=该账号未启用）。登录校验 `_check_gate`：已启用账号必须满足（Cookie `itops_gate` == SHA256(该账号密钥) 或 body `gate_key` 匹配）否则 403；准入 `/gate/{key}` 按用户表匹配后 302 种 HttpOnly Cookie（30 天）；重置接口 `secrets.token_urlsafe(24)` 写入用户行，重置仅影响该账号；旧版全局密钥首次访问 /gate 时自动迁移给 admin |

## MySQL 迁移演练指南（上线前必做）

1. **演练环境**：MySQL 8.x 建库 `itops_helpdesk`（charset utf8mb4）；`config.yaml` 填
   `database_url: "mysql+pymysql://user:password@127.0.0.1:3306/itops_helpdesk?charset=utf8mb4"` 并
   `pip install pymysql`
2. **建表**：直接以 MySQL 配置启动一次服务——`Base.metadata.create_all` 自动建全部表；
   `ensure_columns` 仅对 SQLite 生效（MySQL 建表即最新结构，无需补列）
3. **数据迁移**：管理台「数据备份」导出 **JSON 数据包** → 切换 MySQL 配置 → 「上传备份恢复」导入
   （JSON 与数据库无关，ID 全量保留；附件文件需手工拷贝 `backend/data/attachments/`）
4. **验证**：登录/建单/流转/看板数据抽查；对比 JSON 备份里的工单数与库内 count
5. **回退**：`config.yaml` 改回 SQLite 配置重启即可

### MySQL 连接池配置（已内置）

连接池参数在 `backend/app/models/database.py` 中统一配置（SQLite 与 MySQL 同口径）：

| 参数 | 值 | 说明 |
|---|---|---|
| `pool_size` | 20 | 常驻连接数 |
| `max_overflow` | 30 | 高峰临时连接上限（合计峰值 50 连接） |
| `pool_recycle` | 3600 | 连接回收周期（秒），需小于 MySQL `wait_timeout` |
| `pool_timeout` | 30 | 借出等待超时（秒），超时抛 TimeoutError |
| `pool_pre_ping` | MySQL 开启 | 每次借出前探活，断连自动重建 |

调整建议：MySQL 侧 `max_connections` 应 ≥ 60（50 连接 + 管理余量）；连接数对应**并发数据库操作数**而非在线用户数（SQLAlchemy 按需借还）。

## 压力测试与容量建议（2026-11-17 实测）

单进程部署（uvicorn + SQLite）实测数据，压测工具为 100/200/500 线程并发 HTTP 建单：

| 场景 | 结果 | 说明 |
|---|---|---|
| 100 并发建单 | ✅ 100/100 成功 | 总耗时 1.0s，p50=454ms / p95=930ms |
| 200 并发建单 | ✅ 200/200 成功 | 总耗时 3.8s，无锁错误 |
| 50 混合并发（30 评论+20 受理） | ✅ 50/50 成功 | 总耗时 194ms |
| 500 瞬发（同一毫秒） | ⚠️ 483 成功 / 217 超时 | 客户端 OS 连接层限制，服务端数据零损坏 |
| **持续到达 500 单**（25 并发 × 20 批） | ✅ **500/500 成功** | 总耗时 34.7s（约 14 单/秒），每批稳定 1.4~2.1s |

**已落地的并发优化**：SQLite 写锁等待 30s、WAL 模式（读写不互斥）、会议室预约并发竞态兜底、track 接口限流。

### 容量建议

- **SQLite（默认，百人级团队推荐）**：稳态吞吐约 **14 单/秒**（持续到达），瞬时并发建议控制在 **25 以内**；500 人公司日常高峰（早高峰 30 分钟内 50~100 单）完全可承载；数据库文件放本地 SSD
- **MySQL（千人级或更高并发推荐）**：迁移后连接池峰值 50 并发数据库操作，配合 `max_connections ≥ 60`；吞吐远高于 SQLite，建议压测后再定峰值
- **通用建议**：高峰期（如周一早晨集中报修）如出现明显变慢，优先检查服务器 CPU 与磁盘 IO

## 测试

```bash
cd backend && python -m pytest     # 148 passed
```

覆盖：工单全生命周期流转与越权拒绝、SLA 预警/升级/挂起/解挂幂等、企微回调加解密回环、钉钉 webhook 域名白名单（SSRF）、IM 自动注册与命令识别（含审批分类跳过必填）、统计与管理接口、数据看板（粒度分桶/区间环比/挂起剔除/关键词占比/类目权限/跨期解决）、二维码三种码建单/排队位次/粘性派单与超载回退/**匿名扫码提交与设备码全员可见**、工单编辑/代报修/搜索合并/关注订阅、算法派单/字段级联/类目权限、Webhook 签名投递/开放 API/审批节点（含撤回与合并守卫）/AD 任务链路、岗位权限矩阵（403 矩阵/me.perms/资产回收/分派岗位路由）、改派必填原因与操作审计、导出仅管理员（非管理员一律 403）、数据备份与恢复（三格式/定时计划/JSON 回环/防穿越）、扫码加急与一键转办（广播阈值/频控/池可见性）、**会议室预约冲突/取消与提前结束/维修拦截/检查留痕/会议室码扫码数据（v2.12）**、**统计时区口径（上海凌晨单计入今日新建，v2.12 修复回归）**、**完结留痕分级必填（>1h 双必填/30min~1h 反馈必填/<30min 选填）**、**后台访问安全密钥（test_gate_key.py：staff 无密钥 403/带密钥 200/员工放行/gate 302+HttpOnly Cookie/更换后旧密钥与旧 Cookie 双失效）**。

## 安全设计要点

- 密码 bcrypt 哈希；JWT 签名；角色权限在服务层双重校验（API 依赖 + 状态机）；岗位权限矩阵单一事实源（`core/permissions.py`）
- 钉钉 sessionWebhook 仅放行 `https://*.dingtalk.com`；Webhook 目标默认 https + 拒内网（SSRF 防护，含 DNS rebinding 校验）
- 企微回调验签 + AES 解密按官方协议实现；不可信 XML 用 defusedxml 解析（防实体攻击）
- 出站通知与 Webhook 事件先落库再投递，失败重试，不丢消息
- 备份/恢复：RECOVER 确认口令 + 白名单文件名防穿越 + 解压走临时目录（不覆盖活库）；API Key 仅存摘要；备份文件含敏感信息需妥善保管
- 改派必填原因 + 全量操作事件留痕（时间线），支持审计报表追溯
- **后台访问安全密钥（每账号一枚）**：管理员/工程师各自持有唯一密钥，已启用账号登录需经 `/gate/{key}` 准入（HttpOnly Cookie 30 天）或登录携带；员工与未启用账号不受影响；密钥随机生成不可编辑、重置仅影响该账号；错误密钥 404 不暴露门禁；与登录失败限流（5 次/15 分钟锁 15 分钟）构成双层防爆破
- **公开 FAQ 按匿名可见过滤**：知识库文章勾选「匿名可见」（public_visible）后才出现在登录页公开常见问题页，默认不公开
- 公开接口（`/api/public/*`）只读且不含凭据/密钥字段：软件目录（仅启用项）、FAQ 正文、通用提单码；匿名工单走独立系统用户，track 查询接口限流 30 次/分钟/IP

## 常见问题

| 现象 | 处理 |
|---|---|
| 钉钉/飞书显示未连接 | 核对凭据；钉钉确认开启 Stream 模式，飞书确认选择长连接订阅并发布版本 |
| 通知发不出去 | 管理台「渠道与系统」看通知队列失败数；钉钉查 AgentId 与工作通知权限，飞书查 im:message 发送权限 |
| 企微卡片点开 404 | `public_base_url` 未改成员工可访问的地址 |
| 扫码页打不开/建单 404 | 手机与服务器是否同内网；`public_base_url` 是否正确；标签是否被停用或删除 |
| 扫码没带位置/设备信息 | 位置码需填位置；设备码需关联资产且资产里型号/IP 已填 |
| Webhook 报「解析到内网地址」 | 目标系统在内网属正常，开启 `webhook.allow_private_network` |
| AD 任务一直 pending | 域内代理未部署或令牌不对；检查 AdJobRunner.ps1 计划任务与 `ad_integration` 配置 |
| IM 建单用户名不对 | 自动注册取平台昵称，管理台「用户管理」可改；企微回调暂不含姓名 |
| 时间显示差 8 小时 | 接口返回 UTC（带 Z 后缀），前端按本地时区渲染；直查数据库请按 UTC 理解 |
| 忘记管理员密码 | 删除 `backend/data/helpdesk.db` 重启（测试环境），或用 ITOPS_ADMIN_PASSWORD 环境变量重置首启密码 |
| 忘记安全密钥被锁在门外 | 见「后台访问安全密钥」章节的应急恢复三条路径（自助重置 / 其他管理员重置 / 服务器查库取回） |

## 开发路线图

**已完成里程碑**（详细历程见 [CHANGELOG.md](CHANGELOG.md)）：

- **v1.0 工单核心**：状态机 / 附件 / 催单 / 邮件 / CSV 导出 / 三平台免登 / 卡片交互
- **v1.1-v1.3 运维效率**：智能分派 / 工单模板与合并 / SLA 工作日历 / 台账与合规巡检
- **v2.x 深化**：算法派单与公海 / 开放 API 与 Webhook / 审批与 AD 联动 / 会议室预约 / 实时大屏 / 数据看板与月报 / 安全密钥门禁 / 二维码四类码 / 智能分类助手

**待办**（按优先级）：WebSocket 实时推送、向量知识库问答、工单收藏、低分单闭环、多节点审批流；详见 CHANGELOG.md 中的待办清单。

## 许可证（License）

本项目以 [MIT License](LICENSE) 开源。第三方依赖沿用各自许可：FastAPI / SQLAlchemy / Pydantic / Element Plus / Vue — MIT，ECharts — Apache-2.0，uvicorn / httpx — BSD-3-Clause，qrcode — BSD-3-Clause，fpdf2 / ldap3 — LGPL-3.0（以各包官方元数据为准，发布前建议 `pip list --format=json` 逐包复核）。英文项目简介见 [README.en.md](README.en.md)。
