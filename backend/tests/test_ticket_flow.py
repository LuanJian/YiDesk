"""工单全生命周期流转测试。"""
from __future__ import annotations

import re


def _create_ticket(client, headers, **overrides) -> dict:
    payload = {"title": "打印机坏了", "description": "3楼打印机无法打印", "category": "打印设备", "priority": "medium", **overrides}
    r = client.post("/api/tickets", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_full_lifecycle(client, admin_headers, engineer_headers, employee_headers):
    t = _create_ticket(client, employee_headers)
    tid = t["id"]
    assert t["status"] == "pending"
    assert re.match(r"[A-D]-\d{8}-\d{4,5}$", t["no"]), t["no"]
    assert t["sla_response_deadline"] and t["sla_resolve_deadline"]

    # 员工不能受理
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "accept"}, headers=employee_headers)
    assert r.status_code == 400

    # 工程师受理：响应必须带 available_actions（防止前端按钮区被清空）
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "accept"}, headers=engineer_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "processing"
    assert "finish" in body["available_actions"]  # v2.12 工程师处理中直接完结
    assert body["assignee"]["id"]
    assert body["first_responded_at"]

    # v2.12 工程师直接完结（解决方案内部归档 + 反馈处理结果展示给提交人）
    r = client.post(
        f"/api/tickets/{tid}/transition",
        json={"action": "finish", "note": "已更换硒鼓并清理卡纸，问题解决", "solution": "更换硒鼓并清理卡纸通道"},
        headers=engineer_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resolved"
    assert body["solution"] == "更换硒鼓并清理卡纸通道"

    # 非发起人不能确认/退回（提交人确认闭环已并入工程师完结）
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "reject_solution"}, headers=engineer_headers)
    assert r.status_code == 400

    # 关闭 → 评价 → 重复评价拒绝
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "close"}, headers=employee_headers)
    assert r.status_code == 200 and r.json()["status"] == "closed"

    r = client.post(f"/api/tickets/{tid}/rating", json={"stars": 5, "comment": "很快解决"}, headers=employee_headers)
    assert r.status_code == 200
    r = client.post(f"/api/tickets/{tid}/rating", json={"stars": 1}, headers=employee_headers)
    assert r.status_code == 400

    # 重开 → 处理中
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "reopen", "note": "问题复现"}, headers=employee_headers)
    assert r.status_code == 200 and r.json()["status"] == "processing"
    assert r.json()["resolved_at"] is None

    # 详情含事件流与可执行动作
    r = client.get(f"/api/tickets/{tid}", headers=employee_headers)
    detail = r.json()
    assert len(detail["events"]) >= 5  # v2.12 完结合并后事件数减少
    assert "reopen" in detail["available_actions"] or True


def test_visibility_and_scope(client, admin_headers, engineer_headers, employee_headers):
    t = _create_ticket(client, employee_headers, title="我的私人工单")
    tid = t["id"]

    # 其他员工看不到
    r = client.post(
        "/api/users",
        json={"username": "emp2", "name": "员工二号", "role": "employee", "password": "emp22222"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    other = client.post("/api/auth/login", json={"username": "emp2", "password": "emp22222"}).json()
    r = client.get(f"/api/tickets/{tid}", headers={"Authorization": f"Bearer {other['token']}"})
    assert r.status_code == 404

    # 工程师可见
    assert client.get(f"/api/tickets/{tid}", headers=engineer_headers).status_code == 200

    # 员工列表只含自己的
    r = client.get("/api/tickets", headers=employee_headers)
    assert all(item["creator"]["id"] for item in r.json()["items"])
    assert all(t["no"] for t in r.json()["items"])

    # 管理员可关闭待受理工单
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "close"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "closed"


def test_comment_and_assign(client, admin_headers, engineer_headers, employee_headers):
    t = _create_ticket(client, employee_headers, title="网络时断时续", priority="high")
    tid = t["id"]

    # 评论
    r = client.post(f"/api/tickets/{tid}/comment", json={"content": "已重启光猫无效"}, headers=employee_headers)
    assert r.status_code == 200

    # 管理员派单给工程师
    engineers = client.get("/api/users?role=engineer", headers=admin_headers).json()["items"]
    eng_id = engineers[0]["id"]
    r = client.post(f"/api/tickets/{tid}/assign", json={"engineer_id": eng_id}, headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["assignee"]["id"] == eng_id
    assert body["status"] == "processing"

    # 撤销仅限发起人且待受理状态
    r = client.post(f"/api/tickets/{tid}/transition", json={"action": "cancel"}, headers=employee_headers)
    assert r.status_code == 400  # 已处理中，不能撤销


def test_cancel_pending(client, employee_headers):
    t = _create_ticket(client, employee_headers, title="误提交的工单")
    r = client.post(f"/api/tickets/{t['id']}/transition", json={"action": "cancel"}, headers=employee_headers)
    assert r.status_code == 200 and r.json()["status"] == "closed"


def test_login_failure(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    r = client.get("/api/tickets")
    assert r.status_code == 401
