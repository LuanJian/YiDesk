"""演示数据生成（第三十八批+）：各功能页面 25+ 条覆盖数据，便于浏览测试。

用法：cd backend && ./.venv/bin/python ../scripts/seed_demo_data.py
幂等性：按「演示数据」特征编号（DEMO- 前缀 / T38 已用编号）跳过已存在项，可重复执行。
"""
from __future__ import annotations

import json
import secrets


def _ri(a: int, b: int) -> int:
    """[a, b] 区间安全随机整数（替代 random.randint，Mimosa L3）"""
    return secrets.randbelow(b - a + 1) + a

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os_cwd = Path(__file__).resolve().parents[1] / "backend"
import os

os.chdir(os_cwd)

from app.core.config import get_config  # noqa: E402
from app.models.database import create_session, init_engine  # noqa: E402

init_engine(get_config().resolved_database_url())

from app.models.database import get_engine  # noqa: E402
from app.models.upgrade import ensure_columns  # noqa: E402

ensure_columns()  # 第三十九批：equipment_list/check_cycle_unit/value 等新列补齐后再造数

from app.models.asset_event import AssetEvent  # noqa: E402
from app.models.knowledge import Asset, KnowledgeArticle  # noqa: E402
from app.models.ledger import (  # noqa: E402
    ComplianceItem,
    ComplianceRecord,
    ComplianceScan,
    NetworkDevice,
    SoftwareItem,
    SoftwareLicense,
)
from app.models.login_log import LoginLog  # noqa: E402
from app.models.meeting import MeetingBooking, MeetingRoom, RoomInspection  # noqa: E402
from app.models.qr import QrTag  # noqa: E402
from app.models.system import OutboxMessage  # noqa: E402
from app.models.ticket import Ticket, TicketEvent  # noqa: E402
from app.models.user import User, utcnow  # noqa: E402
from sqlalchemy import select  # noqa: E402


PRIORITY_LEVEL = {"low": "A", "medium": "B", "high": "C", "urgent": "D"}
SH_TZ = timedelta(hours=8)
SH_TZ_HOURS = 8


def now_utc() -> datetime:
    return utcnow().replace(tzinfo=None)


def days_ago(n: int, hour: int = 9, minute: int = 30) -> datetime:
    return now_utc() - timedelta(days=n, hours=_ri(0, 6), minutes=_ri(0, 50))


def ticket_no(db, level: str, day: date) -> str:
    """按编号规则生成当日下一序号（与 create_ticket 口径一致）。"""
    prefix = f"{level}-{day.strftime('%Y%m%d')}-"
    rows = db.query(Ticket.no).filter(Ticket.no.like(f"{prefix}%")).all()
    seq = -1
    for (no,) in rows:
        try:
            seq = max(seq, int(no.rsplit("-", 1)[1]))
        except ValueError:
            continue
    return f"{prefix}{seq + 1:04d}"


def main() -> None:
    db = create_session()
    try:
        admins = list(db.query(User).filter(User.role == "admin", User.is_active.is_(True)).all())
        engineers = list(db.query(User).filter(User.role == "engineer", User.is_active.is_(True)).all())
        anon = db.query(User).filter(User.username == "__anonymous__").first()
        admin = admins[0]
        print(f"现有：管理员 {len(admins)}，工程师 {len(engineers)}")

        # ---- 1. 员工账号（各部门，供工单发起人/资产使用人） ----
        staff_seed = [
            ("demoMkt1", "陈市场", "市场部"), ("demoMkt2", "林市场", "市场部"),
            ("demoFin1", "赵财务", "财务部"), ("demoHr1", "钱人事", "人事部"),
            ("demoSale1", "孙销售", "销售部"), ("demoSale2", "周销售", "销售部"),
            ("demoRd1", "吴研发", "研发部"), ("demoRd2", "郑研发", "研发部"),
            ("demoAdm1", "王行政", "行政部"),
        ]
        from app.core.security import hash_password

        new_staff = []
        for username, name, dept in staff_seed:
            u = db.query(User).filter(User.username == username).first()
            if not u:
                u = User(username=username, name=name, role="employee", department=dept,
                         password_hash=hash_password("Demo123456"))
                db.add(u)
                db.flush()
            new_staff.append(u)
        db.commit()
        print(f"员工账号：{len(new_staff)} 人")

        # ---- 2. 工单（覆盖 6 分类 × 4 优先级 × 全状态 + 合并组 + 加急 + 匿名 + SLA 超时） ----
        existed = db.query(Ticket).filter(Ticket.title.like("【演示】%")).count()
        tickets_spec = [
            # (天数, 标题, 分类, 优先级, 状态, 描述, custom_fields)
            (28, "【演示】VPN 无法连接，居家办公受阻", "网络故障", "high", "closed", "出差在外 VPN 客户端一直报错 809", {}),
            (27, "【演示】人事系统账号被锁定", "账号权限", "medium", "resolved", "输错密码太多次被锁，请帮忙解锁", {"申请类型": "账户密码找回"}),
            (26, "【演示】申请安装 Axure RP 原型工具", "软件安装", "low", "closed", "产品岗需要画原型图", {}),
            (25, "【演示】投影仪 HDMI 接口接触不良", "硬件设备", "medium", "closed", "会议室投影时断时续", {"设备类型": "其他设备"}),
            (24, "【演示】部门打印机显示脱机", "打印设备", "high", "resolved", "3 楼打印机所有人均无法打印", {"故障类型": "连打印机"}),
            (23, "【演示】OA 系统网页打不开", "网络故障", "high", "closed", "内网 OA 地址无法访问，其他人正常", {}),
            (22, "【演示】笔记本电脑电池鼓包", "硬件设备", "urgent", "closed", "电池明显鼓起，担心安全隐患，已停用", {"设备类型": "笔记本"}),
            (21, "【演示】新入职同事申请开通邮箱", "账号权限", "low", "resolved", "研发部新人需要企业邮箱与 Git 权限", {"申请类型": "账户权限申请"}),
            (20, "【演示】财务专用打印机驱动异常", "打印设备", "medium", "resolved", "重装驱动后仍提示打印假脱机失败", {"故障类型": "打印报错"}),
            (19, "【演示】会议室 WiFi 信号弱", "网络故障", "medium", "processing", "大会议室靠窗位置几乎无信号", {}),
            (18, "【演示】显示器闪烁有水波纹", "硬件设备", "low", "pending_confirm", "换线后仍偶发闪烁", {"设备类型": "显示器"}),
            (17, "【演示】客户演示环境服务器部署协助", "其他问题", "high", "processing", "明天上午前需要部署好演示环境", {}),
            (16, "【演示】共享盘权限申请（财务凭证目录）", "账号权限", "medium", "processing", "需要读写财务凭证共享目录", {"申请类型": "账户权限申请"}),
            (15, "【演示】销售部全员企业微信登录异常", "其他问题", "urgent", "processing", "约 20 人集中反馈无法登录企微", {}),
            (14, "【演示】台式机开机风扇异响", "硬件设备", "low", "pending", "声音很大但能正常进系统", {"设备类型": "台式机"}),
            (13, "【演示】打印任务排队不出纸", "打印设备", "medium", "pending", "任务在队列里但不打印，重启无效", {"故障类型": "打印报错"}),
            (12, "【演示】研发部申请 32G 内存升级", "硬件设备", "medium", "pending", "编译任务内存不足", {"设备类型": "其他设备"}),
            (11, "【演示】外包人员门禁卡权限配置", "账号权限", "medium", "pending_approval", "外包驻场 3 个月，需要门禁与考勤绑定", {"申请类型": "账户权限申请"}),
            (10, "【演示】网站证书过期告警（内部门户）", "网络故障", "high", "pending", "浏览器提示证书已过期", {}),
            (9, "【演示】采购申请：会议拾音器 2 台", "其他问题", "low", "pending", "视频会议经常听不清发言", {}),
        ]
        created_tickets: list[Ticket] = []
        if existed == 0:
            eng_cycle = engineers or [admin]
            for i, (d, title, cat, pri, status, desc, cf) in enumerate(tickets_spec):
                day = (now_utc() + timedelta(hours=SH_TZ_HOURS)).date() - timedelta(days=d)
                level = PRIORITY_LEVEL[pri]
                no = ticket_no(db, level, day)
                created = days_ago(d)
                assignee = eng_cycle[i % len(eng_cycle)]
                creator = new_staff[i % len(new_staff)]
                t = Ticket(
                    no=no, title=title, description=desc, category=cat, priority=pri,
                    status=status, creator_id=creator.id, assignee_id=assignee.id if status != "pending" else None,
                    created_at=created, custom_fields=json.dumps(cf, ensure_ascii=False),
                )
                if status in ("resolved", "closed"):
                    t.resolved_at = created + timedelta(hours=_ri(2, 30))
                    t.first_responded_at = created + timedelta(minutes=_ri(5, 40))
                    t.sla_response_deadline = created + timedelta(days=1)
                    t.sla_resolve_deadline = created + timedelta(days=2)
                    t.sla_response_warned = True
                    t.sla_escalated = False
                if status == "closed":
                    t.closed_at = (t.resolved_at or created) + timedelta(days=1)
                if status in ("processing", "pending_confirm"):
                    t.first_responded_at = created + timedelta(minutes=_ri(5, 30))
                    t.sla_response_deadline = created + timedelta(days=1)
                    t.sla_resolve_deadline = created + timedelta(days=2, hours=_ri(-8, 20))
                if status == "pending_approval":
                    t.first_responded_at = created + timedelta(minutes=10)
                    t.sla_response_deadline = created + timedelta(days=1)
                db.add(t)
                db.flush()
                events = [TicketEvent(ticket_id=t.id, actor_id=creator.id, type="comment",
                                      content=f"提交工单：{title}", created_at=created)]
                if status != "pending":
                    events.append(TicketEvent(ticket_id=t.id, actor_id=assignee.id, type="transition",
                                              content=f"受理工单（{assignee.name or assignee.username}）", created_at=created + timedelta(minutes=15)))
                if status in ("resolved", "closed"):
                    events.append(TicketEvent(ticket_id=t.id, actor_id=assignee.id, type="transition",
                                              content="已解决并归档解决方案", created_at=t.resolved_at))
                if status == "pending_approval":
                    events.append(TicketEvent(ticket_id=t.id, actor_id=assignee.id, type="transition",
                                              content="提交审批（外包权限类需主管确认）", created_at=created + timedelta(minutes=12)))
                for ev in events:
                    db.add(ev)
                created_tickets.append(t)
            db.commit()
            print(f"工单：+{len(created_tickets)} 张（全状态/全分类覆盖）")
        else:
            created_tickets = list(db.query(Ticket).filter(Ticket.title.like("【演示】%")).all())
            print(f"工单：已存在 {len(created_tickets)} 张演示单，跳过")

        # ---- 3. 合并组（软件安装，两组形态） ----
        if not db.query(Ticket).filter(Ticket.title.like("【演示合并】%")).first():
            day = (now_utc() + timedelta(hours=SH_TZ_HOURS)).date()
            main = Ticket(
                no=ticket_no(db, "B", day), title="【演示合并】向日葵远程控制无法连接",
                description="远程控制客户端连不上设备", category="软件安装", priority="medium",
                status="processing", creator_id=new_staff[0].id, assignee_id=(engineers or [admin])[0].id,
                created_at=days_ago(2), first_responded_at=days_ago(2) + timedelta(minutes=8),
                custom_fields=json.dumps({"software": {"name": "向日葵远程控制", "category": "远程控制"}}, ensure_ascii=False),
            )
            main.first_responded_at = days_ago(2) + timedelta(minutes=8)
            main.sla_response_deadline = days_ago(2) + timedelta(days=1)
            main.sla_resolve_deadline = days_ago(2) + timedelta(days=2)
            db.add(main)
            db.flush()
            db.add(TicketEvent(ticket_id=main.id, actor_id=new_staff[0].id, type="comment", content="提交工单：向日葵无法连接", created_at=days_ago(2)))
            src_titles = ["【演示合并】向日葵装完打不开", "【演示合并】向日葵连接总是掉线"]
            for k, st in enumerate(src_titles):
                src = Ticket(
                    no=ticket_no(db, "B", day), title=st, description="与上一单同一软件问题",
                    category="软件安装", priority="medium", status="pending",
                    creator_id=new_staff[(k + 1) % len(new_staff)].id, created_at=days_ago(1) + timedelta(hours=k),
                    merged_into_id=main.id,
                    custom_fields=json.dumps({"software": {"name": "向日葵远程控制"}}, ensure_ascii=False),
                )
                db.add(src)
                db.flush()
                db.add(TicketEvent(ticket_id=src.id, actor_id=src.creator_id, type="comment",
                                   content=f"已并入主工单 {main.no}（将随其一并转出与完结）", created_at=src.created_at))
            # 已完结形态的合并组
            main2 = Ticket(
                no=ticket_no(db, "A", day), title="【演示合并】WPS 批量激活申请",
                description="市场部 5 人需要 WPS 商业版激活", category="软件安装", priority="low",
                status="closed", creator_id=new_staff[2].id, assignee_id=(engineers or [admin])[0].id,
                created_at=days_ago(8), resolved_at=days_ago(7), closed_at=days_ago(6),
                first_responded_at=days_ago(8) + timedelta(minutes=12),
                custom_fields=json.dumps({"software": {"name": "WPS Office 商业版"}}, ensure_ascii=False),
            )
            db.add(main2)
            db.flush()
            src2 = Ticket(
                no=ticket_no(db, "A", day), title="【演示合并】WPS 激活码无效",
                description="同批激活申请，码提示无效", category="软件安装", priority="low",
                status="closed", creator_id=new_staff[3].id, created_at=days_ago(8) + timedelta(hours=3),
                resolved_at=days_ago(7), closed_at=days_ago(6), merged_into_id=main2.id,
            )
            db.add(src2)
            db.flush()
            db.add(TicketEvent(ticket_id=src2.id, actor_id=admin.id, type="transition",
                               content=f"随主工单 {main2.no} 完结，同步关闭", created_at=days_ago(7)))
            db.commit()
            print("合并组：+2 组（processing 组 + closed 组）")
        else:
            print("合并组：已存在，跳过")

        # ---- 4. 加急单 + 匿名单 ----
        if not db.query(Ticket).filter(Ticket.title.like("【演示加急】%")).first():
            day = (now_utc() + timedelta(hours=SH_TZ_HOURS)).date()
            urg = Ticket(
                no=ticket_no(db, "D", day), title="【演示加急】销售直播间网络中断",
                description="直播中突然断网，影响线上活动", category="网络故障", priority="urgent",
                status="processing", creator_id=new_staff[4].id, assignee_id=(engineers or [admin])[0].id,
                urgent=True, urgent_at=now_utc() - timedelta(minutes=25),
                created_at=now_utc() - timedelta(hours=1),
            )
            urg.first_responded_at = urg.created_at + timedelta(minutes=6)
            urg.sla_response_deadline = urg.created_at + timedelta(minutes=30)
            urg.sla_resolve_deadline = urg.created_at + timedelta(hours=2)
            db.add(urg)
            db.flush()
            db.add(TicketEvent(ticket_id=urg.id, actor_id=new_staff[4].id, type="comment", content="员工发起加急：直播中断", created_at=now_utc() - timedelta(minutes=25)))
            if anon:
                ano = Ticket(
                    no=ticket_no(db, "C", day), title="【演示匿名】5 楼茶水间网口不通",
                    description="匿名扫码报修：插上网线没反应", category="网络故障", priority="medium",
                    status="pending", creator_id=anon.id, created_at=now_utc() - timedelta(hours=3),
                    custom_fields=json.dumps({"qr_code": "QR-6A5B6", "follow_code": "D38K2M"}, ensure_ascii=False),
                )
                db.add(ano)
                db.flush()
                db.add(TicketEvent(ticket_id=ano.id, actor_id=anon.id, type="comment", content="匿名扫码提交", created_at=ano.created_at))
            db.commit()
            print("加急/匿名单：+2 张")
        else:
            print("加急/匿名单：已存在，跳过")

        # ---- 5. 资产 25 台（第四十一批：品牌/型号分列） ----
        if db.query(Asset).filter(Asset.asset_tag.like("DEMO-%")).count() == 0:
            today = (now_utc() + timedelta(hours=SH_TZ_HOURS)).date()
            asset_spec = []
            # 电脑 10（品牌、名称、型号分列）
            for i in range(1, 11):
                st = "在用" if i <= 7 else ("维修中" if i <= 8 else "闲置")
                exp = None
                if i <= 3:
                    exp = (today + timedelta(days=[8, 15, 26][i - 1])).isoformat()
                elif i <= 5:
                    exp = (today - timedelta(days=[4, 12][i - 4])).isoformat()
                elif i <= 8:
                    exp = (today + timedelta(days=60 + i * 10)).isoformat()
                vendor = ['联想', '戴尔', '惠普'][i % 3]
                asset_spec.append((f"DEMO-PC-{i:03d}", f"ThinkPad {['T14', 'X1', 'E14'][i % 3]}", "电脑", st,
                                   f"{(i - 1) % 5 + 2}F-{(i * 7) % 30 + 1:03d}", exp, "i5-13500/16G/512G", vendor, "ThinkPad"))
            # 打印机 6
            for i in range(1, 7):
                st = ["在用", "在用", "维修中", "在用", "闲置", "报废"][i - 1]
                exp = (today + timedelta(days=90 + i)).isoformat() if i <= 2 else None
                vendor = ['惠普', '佳能', '兄弟'][i % 3]
                asset_spec.append((f"DEMO-PRN-{i:03d}", f"{['LaserJet M405', 'iC MF443', 'HL-2595'][i % 3]}", "打印机", st,
                                   f"{i % 5 + 2}F 打印区", exp, "黑白激光 A4", vendor, "LaserJet"))
            # 显示器 4 / 外设 3 / 其他 2
            for i in range(1, 5):
                asset_spec.append((f"DEMO-MON-{i:03d}", "27 英寸 4K 显示器", "显示器",
                                   "在用" if i <= 3 else "闲置", f"3F-{i * 11:03d}", None, "27UHD",
                                   ['戴尔', 'AOC', '飞利浦', '三星'][i - 1], "27UHD"))
            for i in range(1, 4):
                asset_spec.append((f"DEMO-PER-{i:03d}", ['罗技 MK540 键鼠套装', '华为会议音箱', '希捷 4T 移动硬盘'][i - 1], "外设",
                                   "在用", f"仓库-B{i}", None, "配件",
                                   ['罗技', '华为', '希捷'][i - 1], "配件"))
            for i in range(1, 3):
                asset_spec.append((f"DEMO-OTH-{i:03d}", ['视频会议终端', 'NAS 存储阵列'][i - 1], "其他",
                                   "在用" if i == 1 else "报废", "3F 机房", (today + timedelta(days=200)).isoformat() if i == 1 else None, "专用设备",
                                   ['华为', '群晖'][i - 1], "专用"))
            for tag, name, cat, st, loc, exp, note, vendor, model in asset_spec:
                a = Asset(
                    asset_tag=tag, name=name, category=cat, location=loc, status=st,
                    owner_id=secrets.choice(new_staff).id if st == "在用" else None,
                    note=note, expire_date=exp, expire_warned=False,
                    model=model, vendor=vendor,
                    # 第四十一批：最近检测时间（模拟此前在线检测过）
                    last_checked_at=now_utc() - timedelta(days=_ri(0, 14), hours=_ri(0, 12)) if st != "报废" else None,
                )
                db.add(a)
                db.flush()
                db.add(AssetEvent(asset_id=a.id, action="create", note=f"登记资产（{st}）", operator_id=admin.id))
            db.commit()
            print(f"资产：+{len(asset_spec)} 台（含 3 临期/2 过期/在用维修闲置报废全覆盖）")
        else:
            print("资产：演示数据已存在，跳过")

        # ---- 6. 网络设备 25 台 ----
        if db.query(NetworkDevice).filter(NetworkDevice.name.like("DEMO-%")).count() == 0:
            nd_spec = []
            for i in range(1, 11):
                nd_spec.append((f"DEMO-SW-{i:02d}", ["核心交换机", "汇聚交换机", "接入交换机"][min(i // 4, 2)], "华为", f"S{5720 + i}",
                                f"10.0.{i}.{1 + i}", "在线" if i <= 7 else ("失联" if i <= 9 else "停用"), f"{i}F 弱电间", 22))
            for i in range(1, 6):
                nd_spec.append((f"DEMO-RTR-{i:02d}", "路由器", "H3C", f"MSR{3620 + i}", f"10.1.0.{i}", "在线" if i <= 3 else "备用", "机房", 22))
            for i in range(1, 7):
                nd_spec.append((f"DEMO-AP-{i:02d}", "无线 AP", "锐捷", f"EAP{202 + i}", f"192.168.{i}.{10 + i}", "在线" if i <= 4 else "失联", f"{i % 5 + 2}F 天花板", None))
            for i in range(1, 3):
                nd_spec.append((f"DEMO-FW-{i:02d}", "防火墙", "深信服", f"AF-{1000 + i}", f"10.254.0.{i}", "在线", "机房", 443))
            for i in range(1, 3):
                nd_spec.append((f"DEMO-AC-{i:02d}", "AC 控制器", "锐捷", f"WS-{6008 + i}", f"10.253.0.{i}", "在线" if i == 1 else "停用", "机房", 22))
            for name, dtype, vendor, model, ip, st, loc, port in nd_spec:
                checked = now_utc() - timedelta(hours=_ri(1, 10))
                # 第四十一批：资产编号（与名称一致，DEMO-SW-01 等）与保修到期日（部分设备 90/150/365 天后）
                nd_exp = (today + timedelta(days=secrets.choice([90, 150, 365, 420]))).isoformat() if _ri(0, 9999) / 10000 < 0.4 else None
                db.add(NetworkDevice(
                    name=name, device_type=dtype, vendor=vendor, model=model, ip=ip,
                    mgmt_port=port, location=loc, serial_no=_ri(10 ** 8, 10 ** 9 - 1).__str__(),
                    firmware=f"v{_ri(5, 7)}.{_ri(0, 9)}", status=st,
                    probe_enabled=st in ("在线", "失联"), last_checked_at=checked,
                    last_seen_at=checked if st == "在线" else checked - timedelta(days=_ri(1, 6)),
                    asset_tag=name,
                    expire_date=nd_exp,
                    notes="演示数据",
                ))
            db.commit()
            print(f"网络设备：+{len(nd_spec)} 台（5 类型/4 状态，含编号与保修到期）")
        else:
            print("网络设备：演示数据已存在，跳过")

        # ---- 7. 软件列表 25 款 ----
        if db.query(SoftwareItem).filter(SoftwareItem.name.like("【演示】%")).count() == 0:
            sw_seed = [
                ("WPS Office 2024 商业版", "办公软件", "免费商用", "文档/表格/演示一站式办公", "市场部,行政部,人事部,财务部", "软件官网", "https://www.wps.cn"),
                ("企业微信", "通讯协作", "完全免费", "内部沟通与审批", "市场部,销售部,研发部,人事部", "软件官网", "https://work.weixin.qq.com"),
                ("钉钉", "通讯协作", "完全免费", "考勤与日志", "人事部,行政部", "软件官网", "https://www.dingtalk.com"),
                ("Visual Studio Code", "研发设计", "开源软件", "前端/脚本开发主力编辑器", "研发部", "项目地址", "https://code.visualstudio.com"),
                ("Git", "研发设计", "开源软件", "版本控制", "研发部", "软件官网", "https://git-scm.com"),
                ("Navicat Premium", "研发设计", "部分免费", "数据库管理（试用 14 天）", "研发部", "软件官网", "https://www.navicat.com.cn"),
                ("Postman", "研发设计", "免费商用", "接口调试", "研发部", "软件官网", "https://www.postman.com"),
                ("向日葵远程控制", "运维工具", "部分免费", "远程协助（个人版免费）", "市场部,销售部,研发部", "软件官网", "https://sunlogin.oray.com"),
                ("Photoshop 2024", "研发设计", "部分免费", "平面设计（需授权）", "市场部", "软件官网", "https://www.adobe.com"),
                ("Adobe Acrobat Reader", "办公软件", "完全免费", "PDF 阅读与批注", "财务部,人事部,行政部", "软件官网", "https://www.adobe.com/cn/acrobat"),
                ("7-Zip", "常用工具", "开源软件", "压缩解压", "市场部,研发部,财务部", "项目地址", "https://www.7-zip.org"),
                ("Everything", "常用工具", "完全免费", "文件秒搜", "研发部,行政部", "软件官网", "https://www.voidtools.com"),
                ("Chrome 浏览器", "常用工具", "完全免费", "默认浏览器", "市场部,销售部,研发部,财务部", "软件官网", "https://www.google.cn/chrome"),
                ("火绒安全", "系统安全", "免费商用", "终端杀毒与防护", "市场部,销售部,研发部,财务部,人事部,行政部", "软件官网", "https://www.huorong.cn"),
                ("腾讯会议", "通讯协作", "免费商用", "视频会议", "市场部,销售部,人事部", "软件官网", "https://meeting.tencent.com"),
                ("Xmind", "办公软件", "部分免费", "思维导图", "市场部,研发部", "软件官网", "https://xmind.cn"),
                ("Typora", "办公软件", "部分免费", "Markdown 写作", "研发部", "软件官网", "https://typora.io"),
                ("MySQL Workbench", "研发设计", "开源软件", "数据库设计", "研发部", "软件官网", "https://www.mysql.com"),
                ("Python 3.12", "研发设计", "开源软件", "脚本运行时", "研发部", "项目地址", "https://www.python.org"),
                ("Node.js LTS", "研发设计", "开源软件", "前端构建", "研发部", "项目地址", "https://nodejs.org"),
                ("福昕 PDF 编辑器", "办公软件", "部分免费", "PDF 编辑（比 Acrobat 轻）", "财务部", "软件官网", "https://www.foxitsoftware.cn"),
                ("迅雷极速版", "常用工具", "完全免费", "大文件下载（仅限工作资料）", "市场部", "三方网站", ""),
                ("Steam", "娱乐软件", "完全免费", "非工作用途，默认不安装", "", "软件官网", "https://store.steampowered.com"),
                ("360 安全卫士", "系统安全", "完全免费", "与火绒二选一，不推荐", "", "三方网站", ""),
                ("TeamViewer", "运维工具", "部分免费", "备选远程工具", "研发部", "软件官网", "https://www.teamviewer.com"),
            ]
            for i, (name, cat, lic, desc, depts, stype, surl) in enumerate(sw_seed):
                db.add(SoftwareItem(
                    name=f"【演示】{name}", category=cat, license_type=lic, description=desc,
                    departments=depts, source_type=stype, source_url=surl,
                    enabled=(name not in ("Steam", "360 安全卫士")),
                ))
            db.commit()
            print(f"软件列表：+{len(sw_seed)} 款（6 类型/4 授权/含 2 款停用）")
        else:
            print("软件列表：演示数据已存在，跳过")

        # ---- 8. 软件许可 25 条 ----
        if db.query(SoftwareLicense).filter(SoftwareLicense.name.like("【演示】%")).count() == 0:
            today = (now_utc() + timedelta(hours=SH_TZ_HOURS)).date()
            lic_seed = []
            for i in range(1, 11):
                lic_seed.append((f"【演示】Windows 11 Pro 批量授权 {i}", "微软", "批量授权", 50, 30 + i, None, 180, True))
            for i, (days, seats, used) in enumerate([(12, 20, 18), (25, 30, 30), (5, 10, 9), (-3, 15, 12), (-20, 10, 8), (200, 25, 10)]):
                lic_seed.append((f"【演示】Office 365 商业版（部门 {i + 1}）", "微软", "订阅制", seats, used, today + timedelta(days=days), 660, True))
            for i in range(1, 4):
                lic_seed.append((f"【演示】某财务软件 OEM 授权 {i}", "用友", "OEM", 5, 5, None, 1200, True))
            for i in range(1, 3):
                lic_seed.append((f"【演示】投影仪授控许可 {i}", "某厂商", "永久授权", 2, 1, None, 800, True))
            for i in range(1, 6):
                lic_seed.append((f"【演示】开源替代方案许可 {i}", "社区", "永久授权", 99, 10, None, 0, True))
            lic_seed.append(("【演示】停用的旧版杀毒许可", "赛门铁克", "订阅制", 40, 0, today - timedelta(days=300), 50, False))
            for name, vendor, ltype, seats, used, exp, cost, enabled in lic_seed:
                db.add(SoftwareLicense(
                    name=name, vendor=vendor, license_type=ltype,
                    license_key=f"DEMO-{_ri(10 ** 7, 10 ** 8 - 1)}-{_ri(10 ** 3, 10 ** 4 - 1)}",
                    seats_total=seats, seats_used=used,
                    purchase_date=today - timedelta(days=_ri(100, 700)),
                    expiry_date=exp, cost=cost, vendor_contact=f"供应商-{vendor} 400 电话",
                    notes="演示数据", enabled=enabled,
                ))
            db.commit()
            print(f"软件许可：+{len(lic_seed)} 条（订阅 3 临期/2 已过期/席位满/停用全覆盖）")
        else:
            print("软件许可：演示数据已存在，跳过")

        # ---- 9. 常见问题 25 篇 ----
        if db.query(KnowledgeArticle).filter(KnowledgeArticle.title.like("【演示】%")).count() == 0:
            kb_seed = [
                ("打印机显示脱机怎么办", "打印设备", ("打印机", "脱机"), "①检查打印机电源与网线；②设备和打印机里查看状态；③重启 Print Spooler 服务；④仍不行联系 IT 换 IP 重装驱动。", 6, True, "内部 Wiki"),
                ("VPN 连接报错 809 的处理", "网络问题", ("VPN", "居家办公"), "常见于路由器未放行 UDP500/4500，家庭路由开启 IPsec Passthrough 后重试。", 8, True, "官方文档"),
                ("企业邮箱密码找回流程", "账户相关", ("邮箱", "密码"), "登录页点「忘记密码」→ 手机验证码重置；未绑定手机的找管理员后台重置。", 5, True, "自述"),
                ("新电脑首次开机配置指南", "硬件维修", ("新电脑", "配置"), "①加域；②装火绒与 WPS；③配置 Outlook；④加入部门共享盘。", 3, True, "内部 Wiki"),
                ("共享盘映射失败排查", "网络问题", ("共享盘", "映射"), "检查 SMB 服务、账户锁定状态；net use 命令示例与常见报错对照。", 4, True, "内部 Wiki"),
                ("会议室外接笔记本无信号的检查顺序", "会议设备", ("投屏", "会议室"), "先确认输入源，再换 HDMI 线，最后检查转接头；会议室码背面有图示。", 4, True, "自述"),
                ("企业微信登录提示版本过低", "软件安装", ("企业微信",), "控制面板卸载后到官网重装最新版；保留聊天记录勾选本地数据。", 2, True, "官方文档"),
                ("无线网络搜不到公司 SSID", "网络问题", ("WiFi",), "确认无线开关；距离 AP 过远时到走廊重试；仍无信号报修并注明工位。", 3, True, "自述"),
                ("打印出来是乱码或空白", "打印设备", ("打印机", "驱动"), "多为驱动型号不匹配，按打印机底部型号到官网下载对应驱动重装。", 3, True, "官方文档"),
                ("申请安装非目录内软件的流程", "软件安装", ("申请", "流程"), "提交工单选「软件安装→其他」填写名称用途，IT 评估安全性与版权后安装。", 7, True, "内部 Wiki"),
                ("电脑中毒后的应急处理", "系统安全", ("安全", "中毒"), "立即断网→不要关机→打电话给 IT→配合排查；重要文件先不要操作。", 2, True, "内部 Wiki"),
                ("会议室预约后需要取消怎么办", "会议设备", ("预约", "取消"), "扫码进入我的预约点「取消」即可；开始前 15 分钟会收到提醒。", 2, True, "自述"),
                ("显示器颜色偏黄的校正方法", "硬件维修", ("显示器",), "检查 VGA/线材→系统色彩校准→仍偏色报修换线或换屏。", 1, False, "自述"),
                ("外出门禁卡失效了怎么处理", "账户相关", ("门禁",), "行政前台补登记；卡片消磁需更换（费用部门承担）。", 1, False, "自述"),
                ("笔记本接扩展坞没有网络", "网络问题", ("扩展坞", "有线网"), "扩展坞网卡驱动重装；Dock 固件升级；换 USB 口测试。", 2, False, "官方文档"),
                ("报销系统打不开附件", "软件安装", ("报销", "PDF"), "福昕/Adobe 默认程序设置；清浏览器缓存；仍不行用 Edge 打开。", 1, False, "内部 Wiki"),
                ("如何申请固定资产领用", "硬件维修", ("领用", "资产"), "OA 填固定资产领用单→部门经理→IT 登记→现场签收。", 2, False, "内部 Wiki"),
                ("会议室视频会议设备开机步骤", "会议设备", ("视频会议",), "终端遥控器开机→选「加入会议」→输入会议号；摄像头遥控有使用图示。", 3, False, "自述"),
                ("Excel 文件打开是只读怎么办", "办公软件", ("Excel",), "文件属性解除锁定；另存为新文件；检查是否被共享盘另一人占用。", 2, False, "自述"),
                ("电脑蓝屏的初步自查", "硬件维修", ("蓝屏",), "记录蓝屏代码→重启观察→最近装的软件先卸载→频繁蓝屏报修附代码。", 4, False, "内部 Wiki"),
                ("出差时如何访问内部系统", "网络问题", ("VPN", "出差"), "先连 VPN 再访问内网地址；国外出差用专线客户端（找 IT 开通）。", 2, False, "内部 Wiki"),
                ("工单的优先级是怎么定的", "其他", ("工单", "说明"), "按业务影响分 A-D 四级：D=大面积中断、C=影响多人、B=个人工作受阻、A=咨询类。", 1, False, "自述"),
                ("离职时的 IT 交接清单", "账户相关", ("离职", "交接"), "账号停用时间、资产归还、数据移交、权限回收四步；HR 会同步发起工单。", 2, False, "内部 Wiki"),
                ("会议室内线电话打不通", "会议设备", ("电话",), "先查话机线是否松脱；报修时注明房间号；IT 会测试程控交换端口。", 1, False, "自述"),
                ("扫码报修后如何查询进度", "其他", ("扫码", "进度"), "提交成功页有 6 位查询码，凭 工单编号+查询码 在扫码页随时查进度。", 5, True, "自述"),
            ]
            kb_author = admin
            for title, cat, tags, content, heat, pub, src in kb_seed:
                db.add(KnowledgeArticle(
                    title=f"【演示】{title}", content=content, category=cat,
                    problem=f"员工反馈：{title}，影响日常使用。",
                    tags=",".join(tags), source=src, public_visible=pub,
                    author_id=kb_author.id,
                    created_at=days_ago(_ri(5, 60)), updated_at=days_ago(_ri(0, 5)),
                ))
            db.commit()
            print(f"常见问题：+{len(kb_seed)} 篇（{sum(1 for s in kb_seed if s[5])} 篇匿名可见）")
        else:
            print("常见问题：演示数据已存在，跳过")

        # ---- 10. 二维码标签 25 个（依赖资产/房间/工程师） ----
        rooms_now = list(db.query(MeetingRoom).filter(MeetingRoom.name.like("【演示】%")).all())
        assets_now = list(db.query(Asset).filter(Asset.asset_tag.like("DEMO-%")).all())
        if db.query(QrTag).filter(QrTag.name.like("【演示】%")).count() == 0:
            from app.services.qr_service import generate_code

            tag_spec = []
            for i in range(1, 13):
                tag_spec.append(("location", f"【演示】{i % 5 + 2}F-{(i * 13) % 40 + 1:03d} 工位区", {"location": f"{i % 5 + 2}F 走廊 {(i * 13) % 40 + 1:03d} 附近"}, None, ["软件安装", "网络问题", "硬件维修", None][i % 4]))
            for i in range(1, 9):
                a = assets_now[i - 1] if i <= len(assets_now) else None
                tag_spec.append(("device", f"【演示】设备码 {a.name if a else i}", {"asset_id": a.id if a else None}, None, None))
            for i, room in enumerate(rooms_now[:5]):
                tag_spec.append(("room", f"【演示】会议室码 {room.name}", {"room_id": room.id}, None, None))
            for eng in (engineers or [])[:2]:
                tag_spec.append(("engineer", f"【演示】指定派单码 {eng.name or eng.username}", {"engineer_id": eng.id}, None, None))
            for kind, name, extra, _x, cat in tag_spec:
                t = QrTag(
                    code=generate_code(db), kind=kind, name=name, category=cat,
                    enabled=True, **({"location": extra.get("location", "")} if kind == "location" else {}),
                    **({"asset_id": extra["asset_id"]} if kind == "device" and extra.get("asset_id") else {}),
                    **({"room_id": extra["room_id"]} if kind == "room" and extra.get("room_id") else {}),
                    **({"engineer_id": extra["engineer_id"]} if kind == "engineer" and extra.get("engineer_id") else {}),
                )
                db.add(t)
            db.commit()
            print(f"二维码标签：+{len(tag_spec)} 个（位置 12/设备 8/会议室 {min(len(rooms_now), 5)}/指定 {min(len(engineers), 2)}）")
        else:
            print("二维码标签：演示数据已存在，跳过")

        # ---- 11. 会议室 +8 间 ----
        if db.query(MeetingRoom).filter(MeetingRoom.name.like("【演示】%")).count() == 0:
            room_seed = [
                ("【演示】大会议室", "5F-501", 30, "大屏电视+会议摄像头+全向麦", 30),
                ("【演示】中会议室 A", "4F-401", 16, "投屏器+白板", 30),
                ("【演示】中会议室 B", "4F-402", 14, "投屏器+视频终端", 30),
                ("【演示】小会议室 A", "3F-301", 6, "55 寸屏+HDMI", 60),
                ("【演示】小会议室 B", "3F-302", 6, "55 寸屏+HDMI", 60),
                ("【演示】培训室", "2F-201", 50, "双屏+吊麦+录播", 60),
                ("【演示】视频洽谈室", "5F-502", 4, "视频终端专用于面试", 0),
                ("【演示】头脑风暴室", "4F-403", 8, "白板墙+移动电视", 0),
            ]
            new_rooms = []
            for name, loc, cap, desc, cycle in room_seed:
                r = MeetingRoom(name=name, location=loc, capacity=cap, equipment_desc=desc,
                                check_cycle_days=cycle, enabled=True,
                                under_maintenance=(name == "【演示】培训室"),
                                maintenance_notice="投影灯泡更换中，预计 11-25 恢复使用" if name == "【演示】培训室" else "")
                db.add(r)
                db.flush()
                new_rooms.append(r)
            db.commit()
        else:
            new_rooms = list(db.query(MeetingRoom).filter(MeetingRoom.name.like("【演示】%")).all())
        all_rooms = list(db.query(MeetingRoom).filter(MeetingRoom.enabled.is_(True)).all())
        print(f"会议室：现有 {len(all_rooms)} 间")

        # ---- 12. 预约 28 条（过去 14 天已结束 18（签到 10/爽约 8）+ 取消 3 + 今天进行中 1 + 未来 10） ----
        if db.query(MeetingBooking).filter(MeetingBooking.title.like("【演示】%")).count() == 0:
            today = (now_utc() + timedelta(hours=SH_TZ_HOURS)).date()
            bookers = new_staff + [admin]
            n = 0
            for d_off in range(-14, 0):
                for _ in range(secrets.choice([1, 1, 2])):
                    if n >= 18:
                        break
                    room = secrets.choice(all_rooms)
                    start_h = secrets.choice([9, 10, 11, 13, 14, 15, 16])
                    b = MeetingBooking(
                        room_id=room.id, date=today - timedelta(days=-d_off),
                        start_time=f"{start_h:02d}:00", end_time=f"{start_h + 1:02d}:00",
                        title=f"【演示】{secrets.choice(['周例会', '项目评审', '需求讨论', '客户接待', '面试', '培训'])}",
                        booker_id=secrets.choice(bookers).id,
                        status=MeetingBooking.STATUS_ACTIVE,
                        created_at=now_utc() - timedelta(days=-d_off + 1),
                    )
                    if -d_off >= 1:
                        # 已结束：70% 签到，30% 爽约
                        if _ri(0, 9999) / 10000 < 0.7:
                            b.checkin_at = datetime.combine(b.date, datetime.min.time()) + timedelta(hours=start_h, minutes=_ri(0, 9)) - SH_TZ
                        n += 1
                        db.add(b)
            for i in range(3):
                room = secrets.choice(all_rooms)
                db.add(MeetingBooking(
                    room_id=room.id, date=today + timedelta(days=i + 1),
                    start_time="10:00", end_time="11:00", title="【演示】已取消的会议",
                    booker_id=secrets.choice(bookers).id, status=MeetingBooking.STATUS_CANCELLED,
                    created_at=now_utc() - timedelta(days=1),
                ))
            live_room = all_rooms[0]
            cur_h = (now_utc() + SH_TZ).hour
            db.add(MeetingBooking(
                room_id=live_room.id, date=today, start_time=f"{max(cur_h - 1, 0):02d}:00",
                end_time=f"{max(cur_h - 1, 0) + 2:02d}:00", title="【演示】进行中的项目复盘",
                booker_id=admin.id, status=MeetingBooking.STATUS_ACTIVE,
                checkin_at=now_utc() - timedelta(minutes=20), created_at=now_utc() - timedelta(days=1),
            ))
            for i in range(10):
                room = secrets.choice(all_rooms)
                start_h = secrets.choice([9, 10, 13, 14, 15, 16])
                db.add(MeetingBooking(
                    room_id=room.id, date=today + timedelta(days=i + 1),
                    start_time=f"{start_h:02d}:00", end_time=f"{start_h + 1:02d}:00",
                    title=f"【演示】{secrets.choice(['产品规划会', '跨部门协调', '技术分享', '季度复盘', '招聘面试'])}",
                    booker_id=secrets.choice(bookers).id, status=MeetingBooking.STATUS_ACTIVE,
                    created_at=now_utc() - timedelta(days=1),
                ))
            db.commit()
            print("预约：+28 条（历史签到/爽约混合、3 取消、1 进行中、10 未来）")
        else:
            print("预约：演示数据已存在，跳过")

        # ---- 13. 会议室检查记录 12 条 ----
        if db.query(RoomInspection).filter(RoomInspection.note.like("【演示】%")).count() == 0:
            from app.models.meeting import ROOM_CHECK_ITEMS

            cyc_rooms = [r for r in all_rooms if r.check_cycle_days]
            n = 0
            for r in cyc_rooms[:3]:
                for k in range(4):
                    results = {}
                    bad = secrets.choice([None, None, 2])
                    for idx, item in enumerate(ROOM_CHECK_ITEMS):
                        results[str(idx)] = "异常" if (bad is not None and idx == bad) else "正常"
                    db.add(RoomInspection(
                        room_id=r.id, inspector_id=admin.id,
                        inspected_at=now_utc() - timedelta(days=_ri(1, 45), hours=_ri(0, 8)),
                        results=json.dumps(results, ensure_ascii=False),
                        note=f"【演示】例行检查" + ("（发现投屏异常，已报修）" if bad is not None else ""),
                    ))
                    n += 1
            db.commit()
            print(f"检查记录：+{n} 条（含异常项）")
        else:
            print("检查记录：演示数据已存在，跳过")

        # ---- 14. 登录日志 30 条 ----
        if db.query(LoginLog).filter(LoginLog.name.like("【演示】%")).count() == 0:
            log_seed = []
            people = [("admin", "系统管理员")] + [(e.username, e.name or e.username) for e in engineers] + [(s.username, s.name) for s in new_staff[:5]]
            ips = ["192.168.0.113", "192.168.0.101", "192.168.0.66", "192.168.0.88", "192.168.1.45"]
            for i in range(30):
                username, name = secrets.choice(people)
                kind = _ri(0, 9999) / 10000
                if kind < 0.72:
                    log_seed.append((username, name, secrets.choice(ips), True, ""))
                elif kind < 0.94:
                    log_seed.append((username, name, secrets.choice(ips), False, "密码错误"))
                else:
                    log_seed.append((username, name, secrets.choice(ips), False, "后台准入校验未通过（安全密钥）"))
            for i, (username, name, ip, ok, reason) in enumerate(log_seed):
                db.add(LoginLog(username=username, name=f"【演示】{name}", ip=ip, success=ok,
                                reason=reason, created_at=now_utc() - timedelta(days=i % 14, hours=_ri(0, 12))))
            db.commit()
            print(f"登录日志：+{len(log_seed)} 条（成功/密码错/门禁拒绝混合）")
        else:
            print("登录日志：演示数据已存在，跳过")

        # ---- 15. 合规巡检：批次 + 记录 25 条 ----
        items = list(db.query(ComplianceItem).filter(ComplianceItem.enabled.is_(True)).all())
        if not items:
            base = [
                ("defender_updated", "Defender 病毒库 7 天内更新", "杀毒", "agent", "高"),
                ("patch_60d", "系统补丁 60 天内更新", "补丁", "agent", "高"),
                ("bitlocker_on", "BitLocker 磁盘加密", "安全基线", "agent", "中"),
                ("screensaver_lock", "屏保锁定 10 分钟", "安全基线", "manual", "低"),
                ("no_pirated_sw", "无盗版软件", "软件", "manual", "高"),
            ]
            for k, name, cat, m, sev in base:
                db.add(ComplianceItem(key=k, name=name, category=cat, method=m, severity=sev,
                                      description="演示巡检项", enabled=True))
            db.commit()
            items = list(db.query(ComplianceItem).filter(ComplianceItem.enabled.is_(True)).all())
        demo_assets = list(db.query(Asset).filter(Asset.asset_tag.like("DEMO-PC-%")).all())
        if db.query(ComplianceRecord).filter(ComplianceRecord.detail.like("【演示】%")).count() == 0:
            scan = ComplianceScan(name="【演示】11 月例行巡检", scope_note="全部在用电脑", created_by_id=admin.id)
            db.add(scan)
            db.flush()
            n = 0
            for a in demo_assets:
                sample_pool = secrets.SystemRandom().sample(items, k=min(3, len(items)))  # noqa: S311 演示造数
                for item in sample_pool:
                    result = secrets.choice(["合规"] * 6 + ["不合规"] * 3 + ["未检"])
                    detail = {
                        "合规": "【演示】检查通过，符合基线要求",
                        "不合规": f"【演示】{'病毒库 35 天未更新' if 'defender' in item.key else '检测到未授权软件 2 款' if item.key == 'no_pirated_sw' else '上次更新超期，建议立即处理'}",
                        "未检": "【演示】代理离线未上报",
                    }[result]
                    db.add(ComplianceRecord(
                        asset_id=a.id, item_id=item.id, scan_id=scan.id, result=result,
                        detail=detail, checked_by="agent" if item.method == "agent" else (admin.username),
                        checked_at=now_utc() - timedelta(days=_ri(0, 20), hours=_ri(0, 10)),
                    ))
                    n += 1
            db.commit()
            print(f"合规巡检：+批次 1 个 + 记录 {n} 条（合规/不合规/未检混合）")
        else:
            print("合规巡检：演示数据已存在，跳过")

        # ---- 16. 第三十九批补充：会议室设备列表 + 巡检周期单位 + 全时段全部门预约 ----
        import json as _json

        if db.query(MeetingRoom).filter(MeetingRoom.equipment_list == "[]").count() > 0 or db.query(MeetingBooking).filter(MeetingBooking.title.like("【演示39】%")).count() == 0:
            all_rooms2 = list(db.query(MeetingRoom).filter(MeetingRoom.enabled.is_(True)).all())
            equip_templates = [
                [{"name": "无线麦克风", "count": 2, "status": "正常"}, {"name": "激光笔", "count": 1, "status": "正常"}, {"name": "投屏遥控器", "count": 1, "status": "正常"}, {"name": "HDMI 线", "count": 2, "status": "正常"}],
                [{"name": "视频会议终端", "count": 1, "status": "正常"}, {"name": "全向麦克风", "count": 1, "status": "正常"}, {"name": "无线麦克风", "count": 2, "status": "维修中"}, {"name": "HDMI 线", "count": 1, "status": "正常"}],
                [{"name": "55 寸电视", "count": 1, "status": "正常"}, {"name": "无线投屏器", "count": 1, "status": "正常"}, {"name": "白板笔", "count": 4, "status": "正常"}, {"name": "翻页笔", "count": 1, "status": "损坏"}],
                [{"name": "投影仪", "count": 1, "status": "维修中"}, {"name": "幕布", "count": 1, "status": "正常"}, {"name": "音响", "count": 2, "status": "正常"}],
                [{"name": "电话会议机", "count": 1, "status": "正常"}, {"name": "电视", "count": 1, "status": "正常"}, {"name": "转接头套装", "count": 1, "status": "正常"}],
            ]
            unit_plan = ["day", "day", "day", "week", "week", "session", "session", None, None, None, None]
            for i, room in enumerate(all_rooms2):
                room.equipment_list = _json.dumps(equip_templates[i % len(equip_templates)], ensure_ascii=False)
                unit = unit_plan[i % len(unit_plan)]
                room.check_cycle_unit = unit or "day"
                room.check_cycle_value = {"day": 7, "week": 2, "session": 10}.get(unit, 0) if unit else 0
                room.check_cycle_days = room.check_cycle_value if unit == "day" else 0
            db.commit()
            print(f"会议室设备列表与巡检单位：{len(all_rooms2)} 间已配置")

            # 全时段全部门预约：过去 30 天每天 3-5 条覆盖 8-19 各小时
            bookers2 = new_staff + [admin] + [u for u in engineers if u.department]
            today39 = (now_utc() + timedelta(hours=SH_TZ_HOURS)).date()
            n39 = 0
            for d_off in range(30, 0, -1):
                day39 = today39 - timedelta(days=d_off)
                if day39.weekday() >= 5 and _ri(0, 9999) / 10000 < 0.6:
                    continue
                slots = secrets.SystemRandom().sample(range(8, 19), k=_ri(3, 5))  # noqa: S311 演示造数
                for h in slots:
                    room = secrets.choice(all_rooms2)
                    dur = secrets.choice([1, 1, 2])
                    db.add(MeetingBooking(
                        room_id=room.id, date=day39,
                        start_time=f"{h:02d}:00", end_time=f"{min(h + dur, 21):02d}:00",
                        title=f"【演示39】{secrets.choice(['部门周会', '客户方案沟通', '产品设计评审', '季度经营分析', '校园招聘面试', '供应商洽谈', '内部培训', '跨部门协作会'])}",
                        booker_id=secrets.choice(bookers2).id,
                        status=MeetingBooking.STATUS_ACTIVE,
                        checkin_at=datetime.combine(day39, datetime.min.time()) + timedelta(hours=h, minutes=_ri(0, 12)) - timedelta(hours=SH_TZ_HOURS) if _ri(0, 9999) / 10000 < 0.75 else None,
                        created_at=now_utc() - timedelta(days=d_off + _ri(1, 5)),
                    ))
                    n39 += 1
            for i in range(12):
                room = secrets.choice(all_rooms2)
                h = _ri(8, 18)
                db.add(MeetingBooking(
                    room_id=room.id, date=today39 + timedelta(days=i + 1),
                    start_time=f"{h:02d}:00", end_time=f"{min(h + 1, 21):02d}:00",
                    title=f"【演示39】未来会议 {i + 1}",
                    booker_id=secrets.choice(bookers2).id, status=MeetingBooking.STATUS_ACTIVE,
                    created_at=now_utc() - timedelta(days=1),
                ))
            db.commit()
            print(f"第三十九批预约：历史 +{n39} 条（全时段/全部门）+ 未来 12 条")
        else:
            print("第三十九批补充：已存在，跳过")

        # ---- 汇总 ----
        counts = {
            "工单": db.query(Ticket).count(),
            "资产": db.query(Asset).count(),
            "网络设备": db.query(NetworkDevice).count(),
            "软件列表": db.query(SoftwareItem).count(),
            "软件许可": db.query(SoftwareLicense).count(),
            "常见问题": db.query(KnowledgeArticle).count(),
            "二维码标签": db.query(QrTag).count(),
            "会议室": db.query(MeetingRoom).count(),
            "预约": db.query(MeetingBooking).count(),
            "登录日志": db.query(LoginLog).count(),
            "合规记录": db.query(ComplianceRecord).count(),
        }
        print("=== 最终数据量 ===")
        for k, v in counts.items():
            print(f"  {k}: {v}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
