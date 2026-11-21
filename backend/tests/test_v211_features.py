"""v2.11 第二批功能测试：工程师视角分类分派、接单广场、关单权限、搜索发起人、软件列表、信息来源、在线检测、本周工单。

专用分类 V11B_*；auto_assign 用例内临时关闭并恢复。
"""
from __future__ import annotations

import pytest

CAT = "V11B_测试"


@pytest.fixture(autouse=True)
def _v11b_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.ledger import SoftwareItem
    from app.models.ticket import Ticket

    db = create_session()
    try:
        for t in db.scalars(select(Ticket).where(Ticket.category == CAT)).all():
            t.merged_into_id = None
        db.commit()
        for t in db.scalars(select(Ticket).where(Ticket.category == CAT)).all():
            db.delete(t)
        for s in db.scalars(select(SoftwareItem)).all():
            db.delete(s)
        db.commit()
    finally:
        db.close()


def _disable_auto_assign():
    cfg = None
    from app.core.config import get_config

    cfg = get_config().dispatch
    old = cfg.auto_assign
    cfg.auto_assign = False
    return cfg, old


# ---- 工程师无主动关单权限（v2.11） ----

def test_engineer_cannot_close(client, admin_headers, engineer_headers, employee_headers):
    t = client.post("/api/tickets", json={"title": "关单权限验证", "category": CAT}, headers=employee_headers).json()
    tid = t["id"]
    client.post(f"/api/tickets/{tid}/transition", json={"action": "accept"}, headers=engineer_headers)
    # v2.12 工程师直接完结（不再单独提交方案等确认）
    client.post(f"/api/tickets/{tid}/transition", json={"action": "finish", "solution": "已修复", "note": "已修复并验证"}, headers=engineer_headers)
    assert client.get(f"/api/tickets/{tid}", headers=employee_headers).json()["status"] == "resolved"
    # 工程师主动关闭 → 拒绝
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "close"}, headers=engineer_headers)
    assert r.status_code == 400
    assert "发起人或管理员" in r.json()["detail"]
    # 发起人可以关闭
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "close"}, headers=employee_headers)
    assert r.status_code == 200 and r.json()["status"] == "closed"
    # available_actions 不再给工程师 close 按钮
    d = client.get(f"/api/tickets/{tid}", headers=engineer_headers).json()
    assert "close" not in d["available_actions"]


# ---- 接单广场：超过 30 分钟未分配（v2.11） ----

def test_pool_square_30_minutes(client, admin_headers, engineer_headers, employee_headers):
    cfg, old = _disable_auto_assign()
    try:
        t = client.post("/api/tickets", json={"title": "广场-新单", "category": CAT}, headers=employee_headers).json()
        # 刚建的单（<30 分钟）不进接单广场
        r = client.get("/api/tickets?pool=true&pool_minutes=30", headers=engineer_headers)
        assert all(x["id"] != t["id"] for x in r.json()["items"])
        # 把创建时间拨回 31 分钟前 → 进入广场
        from datetime import timedelta

        from sqlalchemy import select as _select

        from app.models.database import create_session
        from app.models.ticket import Ticket
        from app.models.user import utcnow

        db = create_session()
        try:
            row = db.get(Ticket, t["id"])
            row.created_at = utcnow() - timedelta(minutes=31)
            db.commit()
        finally:
            db.close()
        r = client.get("/api/tickets?pool=true&pool_minutes=30", headers=engineer_headers).json()
        assert any(x["id"] == t["id"] for x in r["items"])
        # 工程师一键转给自己（claim 支持公海单）
        r = client.post(f"/api/tickets/{t['id']}/claim", headers=engineer_headers)
        assert r.status_code == 200, r.text
        d = client.get(f"/api/tickets/{t['id']}", headers=engineer_headers).json()
        assert d["assignee"]["id"] and d["transferred"] is True
    finally:
        cfg.auto_assign = old


# ---- 搜索覆盖发起人（v2.11） ----

def test_search_by_creator(client, admin_headers, employee_headers):
    client.post("/api/tickets", json={"title": "搜索发起人样本", "category": CAT}, headers=employee_headers).json()
    r = client.get("/api/tickets?q=员工一号", headers=admin_headers).json()
    assert any(x["title"] == "搜索发起人样本" for x in r["items"])
    # 无关姓名不命中该单
    r2 = client.get("/api/tickets?q=不存在的人名", headers=admin_headers).json()
    assert not any(x["title"] == "搜索发起人样本" for x in r2["items"])


# ---- 软件列表（v2.11 软件管理） ----

def test_software_items_crud(client, admin_headers, engineer_headers, employee_headers):
    body = {
        "name": "V11B 浏览器", "category": "办公软件", "license_type": "完全免费",
        "description": "内部标准浏览器", "departments": ["市场部", "IT部"], "positions": [], "source": "官网下载",
    }
    r = client.post("/api/softwares", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["departments"] == ["市场部", "IT部"]

    # 授权类型必须是四类之一
    bad = {**body, "name": "V11B 非法", "license_type": "收费软件"}
    assert client.post("/api/softwares", json=bad, headers=admin_headers).status_code == 400
    # 名称去重
    assert client.post("/api/softwares", json=body, headers=admin_headers).status_code == 400

    # 工程师可读（确认装软范围）；v2.12 起员工登录也可读（建单申请安装软件时选择）
    r = client.get("/api/softwares?q=V11B", headers=engineer_headers)
    assert r.status_code == 200 and r.json()["total"] == 1
    assert client.get("/api/softwares", headers=employee_headers).status_code == 200

    # 编辑与删除
    r = client.patch(f"/api/softwares/{sid}", json={**body, "license_type": "开源软件"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["license_type"] == "开源软件"
    assert client.delete(f"/api/softwares/{sid}", headers=admin_headers).status_code == 200


# ---- 常见问题信息来源（v2.11） ----

def test_knowledge_source(client, admin_headers):
    r = client.post(
        "/api/knowledge",
        json={"title": "V11B 投影仪故障排查", "content": "检查 HDMI 线", "category": "硬件设备", "tags": ["投影仪"], "source": "https://vendor.example.com/manual"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["source"].startswith("https://")
    aid = r.json()["id"]
    r = client.patch(f"/api/knowledge/{aid}", json={"title": "V11B 投影仪故障排查", "content": "x", "category": "硬件设备", "tags": [], "source": "自述经验"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["source"] == "自述经验"
    client.delete(f"/api/knowledge/{aid}", headers=admin_headers)


# ---- 资产在线检测（v2.11 设备管理） ----

def _testnet_reachable() -> bool:
    """本机代理（TUN 模式）会劫持 RFC5737 TEST-NET 地址导致 TCP 连接「成功」，此时离线断言不可靠。"""
    import socket

    for port in (80, 443):
        s = socket.socket()
        s.settimeout(0.6)
        try:
            s.connect(("203.0.113.1", port))
            return True
        except Exception:
            continue
        finally:
            s.close()
    return False


@pytest.mark.skipif(_testnet_reachable(), reason="本机网络环境（代理 TUN）劫持 TEST-NET 地址，探活离线断言不可靠")
def test_asset_detect(client, admin_headers):
    # 未登记 IP → 400
    a = client.post("/api/assets", json={"asset_tag": "V11B-PC-1", "name": "无IP资产", "category": "电脑"}, headers=admin_headers).json()
    assert client.post(f"/api/assets/{a['id']}/detect", headers=admin_headers).status_code == 400
    # 不可达测试地址（RFC5737 TEST-NET）→ 离线
    b = client.post("/api/assets", json={"asset_tag": "V11B-PC-2", "name": "探活资产", "category": "打印机", "ip_address": "203.0.113.1"}, headers=admin_headers).json()
    r = client.post(f"/api/assets/{b['id']}/detect", headers=admin_headers)
    assert r.status_code == 200 and r.json()["online"] is False
    client.delete(f"/api/assets/{a['id']}", headers=admin_headers)
    client.delete(f"/api/assets/{b['id']}", headers=admin_headers)


# ---- 大屏本周工单（v2.11） ----

def test_overview_week_created(client, admin_headers, employee_headers):
    client.post("/api/tickets", json={"title": "本周样本", "category": CAT}, headers=employee_headers).json()
    ov = client.get("/api/stats/overview", headers=admin_headers).json()
    assert "week_created" in ov and ov["week_created"] >= ov["today_created"]
    assert ov["week_created"] >= 1
