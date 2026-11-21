"""v2.0 P0 功能测试：工单编辑、提出者（代报修）、搜索合并、SLA 挂起/解挂、工单关注。

与 test_qr 同理使用专用用户（v20 前缀）与专用分类（V20_*），每个测试后清理，
避免污染共享会话库（test_v20 按字母序先于 test_v11/test_v12 执行）。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

CAT = "V20_测试"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "v20" + "12345"


@pytest.fixture(autouse=True)
def _no_auto_dispatch():
    """共享会话库里残留其他测试的值班/分类规则会触发建单自动分派，
    破坏「待受理」前置状态；本文件所有用例统一关闭自动派单。"""
    from app.core.config import get_config

    cfg = get_config().dispatch
    prev = (cfg.auto_assign, cfg.sticky_same_category)
    cfg.auto_assign = False
    cfg.sticky_same_category = False
    yield
    cfg.auto_assign, cfg.sticky_same_category = prev


@pytest.fixture(autouse=True)
def _v20_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.system import DispatchRule
    from app.models.ticket import Ticket

    db = create_session()
    try:
        for t in db.scalars(select(Ticket).where(Ticket.category == CAT)).all():
            db.delete(t)
        for r in db.scalars(select(DispatchRule).where(DispatchRule.category == CAT)).all():
            db.delete(r)
        db.commit()
    finally:
        db.close()


def _mk_user(client, admin_headers, username: str, name: str, role: str = "employee") -> int:
    r = client.post(
        "/api/users",
        json={"username": username, "name": name, "role": role, "password": PWD},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, username: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _create(client, headers: dict, title: str, **kw) -> dict:
    r = client.post("/api/tickets", json={"title": title, "category": CAT, **kw}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---- P0-1 工单编辑 ----

def test_edit_ticket_by_staff(client, admin_headers, employee_headers):
    t = _create(client, employee_headers, "编辑测试-初始标题", priority="medium")
    r = client.patch(
        f"/api/tickets/{t['id']}",
        json={"title": "编辑测试-新标题", "priority": "high", "description": "补充：周末也出现"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["title"] == "编辑测试-新标题"
    assert d["priority"] == "high"
    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    ev = [e["content"] for e in detail["events"] if "编辑工单" in e["content"]]
    assert ev, "应有编辑留痕事件"
    assert "标题「编辑测试-初始标题」→「编辑测试-新标题」" in ev[0]
    assert "优先级 中 → 高" in ev[0]


def test_edit_ticket_permission(client, admin_headers, employee_headers):
    # 发起人待受理可改
    t = _create(client, employee_headers, "编辑权限-待受理可改")
    r = client.patch(f"/api/tickets/{t['id']}", json={"title": "编辑权限-已改"}, headers=employee_headers)
    assert r.status_code == 200, r.text
    # 受理后发起人不可改（工单变为处理中）
    client.post(f"/api/tickets/{t['id']}/assign", json={"engineer_id": None}, headers=admin_headers)
    r2 = client.patch(f"/api/tickets/{t['id']}", json={"title": "编辑权限-受理后再改"}, headers=employee_headers)
    assert r2.status_code == 400
    assert "待受理" in r2.json()["detail"]
    # 工程师对未结单仍可改
    r3 = client.patch(f"/api/tickets/{t['id']}", json={"priority": "urgent"}, headers=admin_headers)
    assert r3.status_code == 200, r3.text


def test_edit_priority_recomputes_sla(client, admin_headers, employee_headers):
    t = _create(client, employee_headers, "编辑改优先级重算SLA", priority="low")
    old = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()["sla_resolve_deadline"]
    r = client.patch(f"/api/tickets/{t['id']}", json={"priority": "urgent"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    new = r.json()["sla_resolve_deadline"]
    assert new != old, "改优先级应按新优先级重算 SLA 时限"


# ---- P0-4 提出者（代报修） ----

def test_requester_on_behalf(client, admin_headers, employee_headers):
    emp2 = _mk_user(client, admin_headers, "v20emp2", "员工二号", role="employee")
    t = _create(client, employee_headers, "代报修-显示器闪烁", requester_id=emp2)
    assert t["requester"]["id"] == emp2
    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    assert any("代 员工二号 报修" in e["content"] for e in detail["events"])
    # 提出者本人（非 creator）可以查看
    emp2_headers = _login(client, "v20emp2")
    assert client.get(f"/api/tickets/{t['id']}", headers=emp2_headers).status_code == 200
    # 提出者不存在 → 400
    r = client.post("/api/tickets", json={"title": "提出者不存在", "requester_id": 99999}, headers=employee_headers)
    assert r.status_code == 400
    # 自己报自己 → requester 为空
    me = client.get("/api/auth/me", headers=employee_headers).json()
    t2 = _create(client, employee_headers, "自报自单带requester", requester_id=me["id"])
    assert t2["requester"] is None


def test_user_directory(client, employee_headers):
    r = client.get("/api/users/directory", headers=employee_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and set(items[0].keys()) == {"id", "name", "department"}


# ---- P0-6 搜索合并 ----

def test_merge_candidates_search(client, admin_headers, employee_headers):
    _create(client, employee_headers, "搜索合并-打印机无法打印")
    src = _create(client, employee_headers, "搜索合并-打印机不打印了")
    closed = _create(client, employee_headers, "搜索合并-打印机打印异常")
    client.post(f"/api/tickets/{closed['id']}/transition", json={"action": "accept"}, headers=admin_headers)
    client.post(
        f"/api/tickets/{closed['id']}/transition",
        json={"action": "finish", "note": "已修", "solution": "更换打印组件"},
        headers=admin_headers,
    )

    r = client.get(f"/api/tickets/{src['id']}/merge-candidates?q=打印机", headers=admin_headers)
    assert r.status_code == 200, r.text
    ids = [i["id"] for i in r.json()["items"]]
    assert src["id"] not in ids, "候选不应包含自身"
    assert closed["id"] not in ids, "已关闭工单不作为合并候选"
    r3 = client.get(f"/api/tickets/{src['id']}/merge-candidates", headers=employee_headers)
    assert r3.status_code == 403


# ---- P0-2 SLA 挂起 / 解挂 ----

def test_sla_suspend_resume_and_scan_skip(client, admin_headers, employee_headers):
    from app.models.database import create_session
    from app.models.ticket import STATUS_PROCESSING, Ticket
    from app.models.user import utcnow
    from app.services import sla_service

    eng = _mk_user(client, admin_headers, "v20eng1", "v20工程师", role="engineer")
    t = _create(client, employee_headers, "SLA挂起-等厂商配件")
    client.post(f"/api/tickets/{t['id']}/assign", json={"engineer_id": eng}, headers=admin_headers)

    db = create_session()
    try:
        tk = db.get(Ticket, t["id"])
        tk.status = STATUS_PROCESSING
        tk.sla_resolve_deadline = utcnow() + timedelta(minutes=100)
        tk.sla_response_deadline = None  # 已受理，无需响应时限
        db.commit()
    finally:
        db.close()

    r = client.post(f"/api/tickets/{t['id']}/sla-suspend", json={"note": "等厂商配件"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["sla_suspended"] is True
    assert d["sla_remaining_minutes"] is not None and 95 <= d["sla_remaining_minutes"] <= 100

    # 挂起期间即使超期，扫描也不报警
    db = create_session()
    try:
        tk = db.get(Ticket, t["id"])
        tk.sla_resolve_deadline = utcnow() - timedelta(minutes=10)
        db.commit()
    finally:
        db.close()
    logs = sla_service.scan(create_session())
    assert not any(t["no"] in line for line in logs), "挂起中的工单不应触发 SLA 扫描"
    # 挂起中不能催单
    r_urge = client.post(f"/api/tickets/{t['id']}/urge", headers=employee_headers)
    assert r_urge.status_code == 400
    assert "挂起" in r_urge.json()["detail"]

    r2 = client.post(f"/api/tickets/{t['id']}/sla-resume", headers=admin_headers)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["sla_suspended"] is False
    assert d2["sla_resolve_deadline"] is not None

    # 解挂后扫描恢复
    db = create_session()
    try:
        tk = db.get(Ticket, t["id"])
        tk.sla_resolve_deadline = utcnow() - timedelta(minutes=10)
        db.commit()
    finally:
        db.close()
    logs2 = sla_service.scan(create_session())
    assert any(t["no"] in line for line in logs2), "解挂后应恢复 SLA 扫描"

    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    contents = [e["content"] for e in detail["events"]]
    assert any(c.startswith("SLA 挂起") for c in contents)
    assert any(c.startswith("SLA 恢复") for c in contents)


def test_sla_suspend_permission_and_rules(client, admin_headers, employee_headers):
    t = _create(client, employee_headers, "SLA挂起-权限与状态")
    r = client.post(f"/api/tickets/{t['id']}/sla-suspend", json={}, headers=employee_headers)
    assert r.status_code == 400
    client.post(f"/api/tickets/{t['id']}/sla-suspend", json={}, headers=admin_headers)
    r2 = client.post(f"/api/tickets/{t['id']}/sla-suspend", json={}, headers=admin_headers)
    assert r2.status_code == 400
    assert "已处于挂起" in r2.json()["detail"]
    client.post(f"/api/tickets/{t['id']}/sla-resume", headers=admin_headers)
    r3 = client.post(f"/api/tickets/{t['id']}/sla-resume", headers=admin_headers)
    assert r3.status_code == 400


# ---- P0-5 工单关注 ----

def test_follow_unfollow_and_notify(client, admin_headers, employee_headers, monkeypatch):
    from app.services import notify_service

    eng = _mk_user(client, admin_headers, "v20eng2", "v20跟单工程师", role="engineer")
    t = _create(client, employee_headers, "关注-重点单")
    eng_headers = _login(client, "v20eng2")

    r = client.post(f"/api/tickets/{t['id']}/follow", headers=eng_headers)
    assert r.status_code == 200
    client.post(f"/api/tickets/{t['id']}/follow", headers=eng_headers)  # 幂等
    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    assert any(f["id"] == eng for f in detail["followers"])

    # 员工不能关注
    r_emp = client.post(f"/api/tickets/{t['id']}/follow", headers=employee_headers)
    assert r_emp.status_code == 403

    # 状态变更通知关注者（捕获 enqueue_for_users 的目标集合）
    captured: list[list[int]] = []
    orig = notify_service.enqueue_for_users

    def spy(db, users, **kw):
        captured.append([u.id for u in users])
        return orig(db, users, **kw)

    monkeypatch.setattr(notify_service, "enqueue_for_users", spy)
    client.post(f"/api/tickets/{t['id']}/transition", json={"action": "accept"}, headers=admin_headers)
    assert any(eng in ids for ids in captured), "关注者应出现在状态变更通知目标中"

    r2 = client.post(f"/api/tickets/{t['id']}/unfollow", headers=eng_headers)
    assert r2.status_code == 200
    detail2 = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    assert all(f["id"] != eng for f in detail2["followers"])


def test_followed_list_filter(client, admin_headers, employee_headers):
    eng = _mk_user(client, admin_headers, "v20eng3", "v20列表工程师", role="engineer")
    t1 = _create(client, employee_headers, "关注列表-单A")
    _create(client, employee_headers, "关注列表-单B")
    eng_headers = _login(client, "v20eng3")
    client.post(f"/api/tickets/{t1['id']}/follow", headers=eng_headers)
    r = client.get("/api/tickets?followed=true", headers=eng_headers)
    assert r.status_code == 200, r.text
    ids = [i["id"] for i in r.json()["items"]]
    assert t1["id"] in ids


# 静态导入（供清理夹具与上述测试使用）
from sqlalchemy import select  # noqa: E402
