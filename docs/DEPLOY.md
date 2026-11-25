# YiDesk 部署手册

> 本文覆盖本机开发、生产部署（systemd / Docker）与钉钉/飞书/企业微信三平台接入。功能与配置说明见主 [README.md](../README.md)。

## 目录

- [快速开始（本机开发）](#快速开始本机开发)
- [部署手册（生产）](#部署手册生产)
- [三平台接入指引](#三平台接入指引)

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
# 上传整个 YiDesk 目录到服务器，如 /opt/yidesk
cd /opt/yidesk/backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 配置
cd /opt/yidesk
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
cd /opt/yidesk
nohup backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300 --app-dir backend > helpdesk.log 2>&1 &
```

- 访问 `http://<服务器IP>:8300` 登录管理台
- **务必单 worker**（不要加 `--workers N`）：渠道长连接、SLA 定时器都在该进程内
- SQLite 数据库在 `backend/data/helpdesk.db`，附件在 `backend/data/attachments/`，备份在 `backend/data/backups/`

systemd 常驻示例：

```ini
# /etc/systemd/system/yidesk.service
[Unit]
Description=YiDesk Helpdesk
After=network.target

[Service]
WorkingDirectory=/opt/yidesk
ExecStart=/opt/yidesk/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300 --app-dir backend
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now yidesk
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
docker build -t yidesk .
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
[yidesk]
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
