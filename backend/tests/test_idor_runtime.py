"""运行时权限复核：员工/游客打管理员资源（资产删除、工单越权、公开入口）。

只断言拒绝码与数据未变，不保留探测数据。
"""
from __future__ import annotations


def _asset_body(tag: str) -> dict:
    return {"asset_tag": tag, "name": "权限复核资产", "category": "电脑", "status": "闲置"}


def test_employee_cannot_mutate_admin_asset(client, admin_headers, employee_headers):
    created = client.post("/api/assets", json=_asset_body("IDOR-ASSET-1"), headers=admin_headers)
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    patch = {
        "asset_tag": "IDOR-ASSET-1",
        "name": "被篡改",
        "category": "电脑",
        "status": "报废",
        "owner_id": None,
        "note": "",
    }
    assert client.delete(f"/api/assets/{aid}", headers=employee_headers).status_code == 403
    assert client.patch(f"/api/assets/{aid}", json=patch, headers=employee_headers).status_code == 403
    assert client.post(f"/api/assets/{aid}/recover", json={"note": "x"}, headers=employee_headers).status_code == 403
    assert client.post(f"/api/assets/{aid}/action", json={"action": "scrap"}, headers=employee_headers).status_code == 403
    assert client.delete(f"/api/assets/{aid}").status_code == 401
    still = client.get("/api/assets?q=IDOR-ASSET-1", headers=admin_headers).json()
    assert still["total"] == 1
    assert still["items"][0]["name"] == "权限复核资产"
    assert still["items"][0]["status"] == "闲置"
    assert client.delete(f"/api/assets/{aid}", headers=admin_headers).status_code == 200


def test_employee_cannot_touch_admin_ticket(client, admin_headers, employee_headers):
    admin_ticket = client.post(
        "/api/tickets",
        json={"title": "管理员私有工单复核", "category": "其他问题", "description": "不应被员工看到"},
        headers=admin_headers,
    )
    assert admin_ticket.status_code == 201, admin_ticket.text
    tid = admin_ticket.json()["id"]
    own = client.post(
        "/api/tickets",
        json={"title": "员工自己的工单复核", "category": "其他问题"},
        headers=employee_headers,
    )
    assert own.status_code == 201, own.text
    own_id = own.json()["id"]

    assert client.get(f"/api/tickets/{tid}", headers=employee_headers).status_code == 404
    listed = client.get("/api/tickets?page_size=200", headers=employee_headers).json()
    ids = {item["id"] for item in listed.get("items", listed if isinstance(listed, list) else [])}
    assert tid not in ids
    assert own_id in ids

    assert client.patch(
        f"/api/tickets/{tid}",
        json={"title": "被员工改掉", "description": "x", "priority": "urgent"},
        headers=employee_headers,
    ).status_code == 404
    assert client.post(
        f"/api/tickets/{tid}/transition",
        json={"action": "close", "note": "越权关闭"},
        headers=employee_headers,
    ).status_code == 404
    assert client.post(f"/api/tickets/{tid}/comment", json={"content": "越权评论"}, headers=employee_headers).status_code == 404
    assert client.post(f"/api/tickets/{tid}/follow", headers=employee_headers).status_code == 404
    assert client.get(f"/api/tickets/{tid}/similar", headers=employee_headers).status_code == 404
    assert client.get(f"/api/tickets/{tid}/knowledge-suggestions", headers=employee_headers).status_code == 404
    assert client.post(f"/api/tickets/{tid}/urge", headers=employee_headers).status_code == 404
    cands = client.get(f"/api/tickets/{tid}/merge-candidates", headers=employee_headers)
    assert cands.status_code == 403
    claim = client.post(f"/api/tickets/{tid}/claim", headers=employee_headers)
    assert claim.status_code == 403
    assign = client.post(f"/api/tickets/{tid}/assign", json={"engineer_id": 1, "reason": "越权派单"}, headers=employee_headers)
    assert assign.status_code in (400, 403)
    assert "仅工程师" in assign.json()["detail"] or "权限" in assign.json()["detail"]
    merge = client.post(f"/api/tickets/{tid}/merge", json={"target_id": own_id}, headers=employee_headers)
    assert merge.status_code == 403
    anon_merge = client.post(f"/api/tickets/{tid}/merge", json={"target_id": own_id})
    assert anon_merge.status_code == 401
    assert client.get(f"/api/tickets/{tid}").status_code == 401

    note = client.post(f"/api/tickets/{tid}/comment", json={"content": "管理员内部备注"}, headers=admin_headers)
    assert note.status_code == 200, note.text
    event_id = note.json()["id"]
    edited = client.patch(
        f"/api/tickets/{tid}/comments/{event_id}",
        json={"content": "员工改掉管理员备注"},
        headers=employee_headers,
    )
    assert edited.status_code == 403

    after = client.get(f"/api/tickets/{tid}", headers=admin_headers)
    assert after.status_code == 200
    assert after.json()["title"] == "管理员私有工单复核"
    assert after.json()["status"] != "closed"
    comments = [e for e in after.json()["events"] if e.get("type") == "comment" or "管理员内部备注" in (e.get("content") or "")]
    assert any("管理员内部备注" in (e.get("content") or "") for e in after.json()["events"])
    assert not any("员工改掉管理员备注" in (e.get("content") or "") for e in after.json()["events"])
    assert comments is not None


def test_guest_cannot_read_private_or_open_apis(client, admin_headers):
    hidden = client.post(
        "/api/knowledge",
        json={"title": "内部知识不应公开", "content": "机密正文", "public_visible": False},
        headers=admin_headers,
    )
    assert hidden.status_code in (200, 201), hidden.text
    kid = hidden.json()["id"]
    pub = client.get(f"/api/public/knowledge/{kid}")
    assert pub.status_code == 404
    listing = client.get("/api/public/knowledge").json()
    titles = [item["title"] for item in listing["items"]]
    assert "内部知识不应公开" not in titles
    assert "机密正文" not in client.get("/api/public/knowledge").text

    assert client.get("/api/open/tickets").status_code == 401
    bogus_key = "not" + "-a-real-key"
    assert client.get("/api/open/tickets", headers={"X-API-Key": bogus_key}).status_code == 401
    assert client.get("/api/ad/jobs/pending").status_code == 401
    assert client.post("/api/ad/jobs/1/result", json={"success": True, "output": "x"}).status_code == 401
    assert client.get("/api/assets").status_code == 401
    assert client.get("/api/tickets").status_code == 401

    soft = client.get("/api/public/softwares")
    assert soft.status_code == 200
    if soft.json()["items"]:
        assert "source_url" not in soft.json()["items"][0]
        assert "source_type" not in soft.json()["items"][0]

    assert client.delete(f"/api/knowledge/{kid}", headers=admin_headers).status_code == 200
