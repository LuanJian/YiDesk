"""新功能测试：软件许可台账、网络设备台账与探活、终端合规巡检。"""
from __future__ import annotations

import socket
import threading
import uuid

from app.models.database import create_session
from app.models.ledger import ComplianceRecord, SoftwareLicense


# ---- 软件许可 ----

def test_license_crud_and_masking(client, admin_headers, engineer_headers, employee_headers):
    r = client.post(
        "/api/licenses",
        json={
            "name": "Office 365 E3", "vendor": "Microsoft", "license_type": "订阅制",
            "license_key": "ABCD-1234-EFGH-5678", "seats_total": 50, "seats_used": 48,
            "expiry_date": "2027-01-01", "cost": 60000, "vendor_contact": "ms@partner.cn",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    lid = r.json()["id"]

    # 工程师可读但密钥脱敏
    lst = client.get("/api/licenses", headers=engineer_headers).json()
    item = next(x for x in lst["items"] if x["id"] == lid)
    assert "ABCD" not in item["license_key_masked"]
    assert "license_key" not in item
    assert item["seats_used"] == 48

    assert lst["summary"]["total"] >= 1

    # admin 详情可见完整密钥
    detail = client.get(f"/api/licenses/{lid}", headers=admin_headers).json()
    assert detail["license_key"] == "ABCD-1234-EFGH-5678"

    # 员工 403；工程师写 403
    assert client.get("/api/licenses", headers=employee_headers).status_code == 403
    assert client.post("/api/licenses", json={"name": "x"}, headers=engineer_headers).status_code == 403


def test_license_expiry_fields(client, admin_headers):
    from datetime import timedelta

    from app.models.user import utcnow

    soon = (utcnow() + timedelta(days=10)).date().isoformat()
    past = (utcnow() - timedelta(days=5)).date().isoformat()
    r1 = client.post("/api/licenses", json={"name": "即将到期", "license_type": "订阅制", "expiry_date": soon}, headers=admin_headers).json()
    r2 = client.post("/api/licenses", json={"name": "已过期", "license_type": "订阅制", "expiry_date": past}, headers=admin_headers).json()
    assert r1["expiring"] is True and r1["expired"] is False and r1["days_to_expiry"] == 10
    assert r2["expired"] is True

    summary = client.get("/api/licenses", headers=admin_headers).json()["summary"]
    assert summary["expiring_30"] >= 1 and summary["expired"] >= 1

    # 预警扫描可执行（10 天/5 天不在提醒点位，仅验证不报错）
    from app.services.ledger_service import scan_license_alerts

    db = create_session()
    try:
        logs = scan_license_alerts(db)
        assert isinstance(logs, list)
    finally:
        db.close()


# ---- 网络设备 ----

def test_device_crud_and_probe(client, admin_headers, employee_headers):
    r = client.post(
        "/api/network-devices",
        json={"name": "5F 接入交换机", "device_type": "交换机", "vendor": "H3C", "model": "S5130",
              "ip": "127.0.0.1", "location": "5F 弱电间", "status": "备用"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    # 探活：本机临时 TCP 监听 → 在线
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=srv.accept, daemon=True).start()
    client.patch(
        f"/api/network-devices/{did}",
        json={"name": "5F 接入交换机", "device_type": "交换机", "ip": "127.0.0.1", "mgmt_port": port, "status": "备用"},
        headers=admin_headers,
    )
    r = client.post(f"/api/network-devices/{did}/probe", headers=admin_headers)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["status"] == "在线"

    # 监听关闭 → 失联
    srv.close()
    client.patch(
        f"/api/network-devices/{did}",
        json={"name": "5F 接入交换机", "device_type": "交换机", "ip": "127.0.0.1", "mgmt_port": port, "status": "在线"},
        headers=admin_headers,
    )
    r = client.post(f"/api/network-devices/{did}/probe", headers=admin_headers)
    assert r.json()["ok"] is False and r.json()["status"] == "失联"

    assert client.get("/api/network-devices", headers=employee_headers).status_code == 403


# ---- 终端合规巡检 ----

def _mk_asset(client, admin_headers, tag: str) -> int:
    return client.post(
        "/api/assets",
        json={"asset_tag": tag, "name": f"终端 {tag}", "category": "电脑", "location": "3F"},
        headers=admin_headers,
    ).json()["id"]


def test_compliance_items_seeded(client, admin_headers):
    items = client.get("/api/compliance/items", headers=admin_headers).json()["items"]
    assert len(items) >= 5
    keys = {i["key"] for i in items}
    assert {"antivirus", "patch", "bitlocker"} <= keys


def test_agent_report_flow(client, admin_headers, engineer_headers):
    asset_id = _mk_asset(client, admin_headers, "PC-CM-001")
    items = {i["key"]: i["id"] for i in client.get("/api/compliance/items", headers=admin_headers).json()["items"]}

    # 未配置 API Key → 403
    r = client.post(
        "/api/compliance/agent-report",
        json={"asset_tag": "PC-CM-001", "results": [{"key": "antivirus", "result": "合规"}]},
    )
    assert r.status_code == 403

    # API Key 测试动态生成，避免硬编码凭据
    from app.core.config import get_config

    agent_key = uuid.uuid4().hex
    get_config().compliance.agent_api_key = agent_key

    # 错误 token → 401
    r = client.post(
        "/api/compliance/agent-report",
        json={"asset_tag": "PC-CM-001", "results": [{"key": "antivirus", "result": "合规"}]},
        headers={"X-API-Token": "wrong"},
    )
    assert r.status_code == 401

    # 正确上报（未知 key 应被忽略）
    r = client.post(
        "/api/compliance/agent-report",
        json={
            "asset_tag": "PC-CM-001",
            "results": [
                {"key": "antivirus", "result": "合规", "detail": "Defender 正常"},
                {"key": "patch", "result": "不合规", "detail": "90 天未更新"},
                {"key": "unknown_key", "result": "合规"},
            ],
        },
        headers={"X-API-Token": agent_key},
    )
    assert r.status_code == 200 and r.json()["accepted"] == 2, r.text

    # 未登记资产 → 404
    r = client.post(
        "/api/compliance/agent-report",
        json={"asset_tag": "NO-SUCH", "results": [{"key": "antivirus", "result": "合规"}]},
        headers={"X-API-Token": agent_key},
    )
    assert r.status_code == 404

    # 汇总
    s = client.get("/api/compliance/summary", headers=admin_headers).json()
    assert s["overall_rate"] is not None
    assert any(n["asset_tag"] == "PC-CM-001" for n in s["noncompliant"])

    # 整改建单
    db = create_session()
    try:
        from sqlalchemy import select

        from app.models.ledger import ComplianceItem

        patch_item = db.scalar(select(ComplianceItem).where(ComplianceItem.key == "patch"))
        rec = db.scalar(
            select(ComplianceRecord).where(
                ComplianceRecord.asset_id == asset_id, ComplianceRecord.item_id == patch_item.id
            )
        )
        rec_id = rec.id
    finally:
        db.close()

    # v2.4 岗位分级后合规整改属现场职责：把 eng1 临时调为现场运维再走整改/手工登记
    eng1_id = client.get("/api/auth/me", headers=engineer_headers).json()["id"]
    client.patch(f"/api/users/{eng1_id}", json={"ops_type": "field"}, headers=admin_headers)
    r = client.post(
        "/api/compliance/remediation-ticket",
        json={"asset_id": asset_id, "record_ids": [rec_id]},
        headers=engineer_headers,
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"].startswith("合规整改：PC-CM-001")
    assert t["asset_id"] == asset_id and t["priority"] == "high"

    # 手工登记（manual 巡检项）
    r = client.post(
        "/api/compliance/records/manual",
        json={"asset_id": asset_id, "item_id": items["illegal_software"], "result": "合规", "detail": "现场检查无盗版"},
        headers=engineer_headers,
    )
    assert r.status_code == 201
    assert r.json()["checked_by"] == "eng1"
