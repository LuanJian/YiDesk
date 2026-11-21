"""统计与管理接口测试。"""
from __future__ import annotations


def test_stats_overview(client, admin_headers, employee_headers):
    client.post(
        "/api/tickets",
        json={"title": "统计测试工单", "category": "软件安装", "priority": "low"},
        headers=employee_headers,
    )
    r = client.get("/api/stats/overview", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 1
    assert "待受理" in d["by_status"]

    assert client.get("/api/stats/trend", headers=admin_headers).status_code == 200
    assert client.get("/api/stats/category", headers=admin_headers).status_code == 200
    assert client.get("/api/stats/engineers", headers=admin_headers).status_code == 200
    # 员工无权看统计
    assert client.get("/api/stats/overview", headers=employee_headers).status_code == 403


def test_sla_rules_crud(client, admin_headers, employee_headers):
    r = client.get("/api/admin/sla", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 4

    r = client.put(
        "/api/admin/sla",
        json=[
            {"priority": "urgent", "response_minutes": 5, "resolve_minutes": 30},
            {"priority": "high", "response_minutes": 15, "resolve_minutes": 120},
            {"priority": "medium", "response_minutes": 60, "resolve_minutes": 480},
            {"priority": "low", "response_minutes": 240, "resolve_minutes": 1440},
        ],
        headers=admin_headers,
    )
    assert r.status_code == 200
    rules = {x["priority"]: x for x in client.get("/api/admin/sla", headers=admin_headers).json()["items"]}
    assert rules["urgent"]["response_minutes"] == 5

    # 员工无权改
    assert (
        client.put("/api/admin/sla", json=[{"priority": "low", "response_minutes": 1, "resolve_minutes": 1}], headers=employee_headers).status_code
        == 403
    )


def test_system_info(client, admin_headers):
    r = client.get("/api/admin/info", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["app_name"]
    assert isinstance(d["channels"], list)


def test_knowledge_crud(client, admin_headers, engineer_headers, employee_headers):
    r = client.post(
        "/api/knowledge",
        json={"title": "VPN 连接指南", "content": "1. 打开客户端 2. 输入账号", "tags": ["VPN", "网络"]},
        headers=engineer_headers,
    )
    assert r.status_code == 201
    aid = r.json()["id"]

    r = client.get("/api/knowledge?q=VPN", headers=employee_headers)
    assert r.status_code == 200 and r.json()["total"] >= 1

    r = client.get(f"/api/knowledge/{aid}", headers=employee_headers)
    assert r.status_code == 200  # v2.12 浏览计数已移除

    r = client.patch(f"/api/knowledge/{aid}", json={"title": "VPN 连接指南(新)", "content": "更新", "tags": [], "category": "网络"}, headers=engineer_headers)
    assert r.status_code == 200

    # 员工不能写
    assert client.post("/api/knowledge", json={"title": "x"}, headers=employee_headers).status_code == 403

    assert client.delete(f"/api/knowledge/{aid}", headers=engineer_headers).status_code == 200


def test_asset_crud(client, admin_headers, engineer_headers, employee_headers):
    # v2.4 岗位分级：资产写操作属现场运维职责（eng1 默认远程岗），此处用管理员执行
    r = client.post(
        "/api/assets",
        json={"asset_tag": "PC-0001", "name": "行政部台式机", "category": "电脑", "location": "2F-201", "status": "在用"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    aid = r.json()["id"]

    assert client.get("/api/assets?q=PC-0001", headers=employee_headers).json()["total"] == 1

    r = client.patch(f"/api/assets/{aid}", json={"asset_tag": "PC-0001", "name": "行政部台式机", "category": "电脑", "location": "3F", "status": "维修中", "owner_id": None, "note": ""}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "维修中"
    # v2.11 岗位矩阵调整：全部工程师可管理资产（远程岗也可写）；员工仍不可写
    r = client.post("/api/assets", json={"asset_tag": "PC-X", "name": "x"}, headers=engineer_headers)
    assert r.status_code == 201
    assert client.delete(f"/api/assets/{r.json()['id']}", headers=admin_headers).status_code == 200  # 用后即清
    assert client.post("/api/assets", json={"asset_tag": "PC-Y", "name": "y"}, headers=employee_headers).status_code == 403

    # 工单关联资产
    r = client.post("/api/tickets", json={"title": "电脑蓝屏", "category": "硬件设备", "priority": "high", "asset_id": aid}, headers=employee_headers)
    assert r.status_code == 201 and r.json()["asset_id"] == aid

    # 已被工单关联的资产不可删除（管理员执行，先于岗位断言）
    assert client.delete(f"/api/assets/{aid}", headers=admin_headers).status_code == 400

    # 未关联的资产可正常删除
    r = client.post(
        "/api/assets",
        json={"asset_tag": "PRN-0001", "name": "备用打印机", "category": "打印机", "location": "库房", "status": "闲置"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert client.delete(f"/api/assets/{r.json()['id']}", headers=admin_headers).status_code == 200


def test_stats_timezone_shanghai(client, admin_headers):
    """v2.12 修复：统计口径按 Asia/Shanghai——UTC 傍晚的单（上海次日凌晨）应计入「今日新建」。

    修复前 today/week 按 UTC date 计算，上海早 8 点前会把昨晚的单错分到昨天。
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import utcnow

    tz = ZoneInfo("Asia/Shanghai")
    now_sh = utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    # 构造「上海今天 01:30」的单（UTC 值 = 上海时刻 - 8h；若当前上海时刻早于 01:30，
    # 则该单落在上海昨天 17:30+，仍属 UTC 昨天傍晚——正是修复前会漏算的场景）
    sh_today = now_sh.date()
    created_utc = (datetime(sh_today.year, sh_today.month, sh_today.day, 1, 30, tzinfo=tz) - timedelta(hours=8)).replace(tzinfo=None)
    db = create_session()
    try:
        t = Ticket(
            no=f"GD-TZ-{utcnow():%H%M%S%f}", title="时区口径验证单", category="其他", status="closed",
            creator_id=1, created_at=created_utc, resolved_at=created_utc + timedelta(hours=2), closed_at=created_utc + timedelta(hours=2),
        )
        db.add(t)
        db.commit()
        tid = t.id
    finally:
        db.close()
    try:
        ov = client.get("/api/stats/overview", headers=admin_headers).json()
        assert ov["today_created"] >= 1, "上海今天 01:30 的单应计入今日新建（此前按 UTC 会漏算）"
        trend = client.get("/api/stats/trend?days=7", headers=admin_headers).json()
        today_key = now_sh.strftime("%m-%d")
        assert any(x["date"] == today_key and x["created"] >= 1 for x in trend), "trend 最新桶应包含该单"
    finally:
        db2 = create_session()
        try:
            t = db2.get(Ticket, tid)
            db2.delete(t)
            db2.commit()
        finally:
            db2.close()
