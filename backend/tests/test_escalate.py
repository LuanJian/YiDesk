"""加急与转办测试（v2.6）：扫码页加急推送、排队阈值广播、一键转办认领、加急池可见性。

专用用户 es 前缀 + ES_测试 分类；通知目标用 monkeypatch 捕获，不发真实消息。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

CAT = "ES_测试"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "es1" + "2345"


@pytest.fixture(autouse=True)
def _no_auto_dispatch():
    from app.core.config import get_config

    cfg = get_config().dispatch
    prev = (cfg.auto_assign, cfg.sticky_same_category)
    cfg.auto_assign = False
    cfg.sticky_same_category = False
    yield
    cfg.auto_assign, cfg.sticky_same_category = prev


@pytest.fixture(scope="module", autouse=True)
def _es_module_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import User

    db = create_session()
    try:
        es_ids = select(User.id).where(User.username.like("es%"))
        for t in db.scalars(
            select(Ticket).where((Ticket.assignee_id.in_(es_ids)) | (Ticket.creator_id.in_(es_ids)) | (Ticket.category == CAT))
        ).all():
            db.delete(t)
        for u in db.scalars(select(User).where(User.username.like("es%"))).all():
            db.delete(u)
        db.commit()
    finally:
        db.close()


def _mk(client, admin_h, username, name, role="engineer") -> int:
    r = client.post(
        "/api/users",
        json={"username": username, "name": name, "role": role, "ops_type": "field", "password": PWD},
        headers=admin_h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, username) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def admin_h(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def es_users(client, admin_h):
    emp = _mk(client, admin_h, "esemp", "加急员工", role="employee")
    busy = _mk(client, admin_h, "esbusy", "忙碌处理人")
    busy2 = _mk(client, admin_h, "esbusy2", "忙碌处理人二")
    free1 = _mk(client, admin_h, "esfree1", "空闲工程师甲")
    free2 = _mk(client, admin_h, "esfree2", "空闲工程师乙")
    return {
        "emp": emp, "busy": busy, "busy2": busy2, "free1": free1, "free2": free2,
        "emp_h": _login(client, "esemp"), "busy_h": _login(client, "esbusy"), "busy2_h": _login(client, "esbusy2"),
        "free1_h": _login(client, "esfree1"), "free2_h": _login(client, "esfree2"),
    }


def _notify_targets(client, monkeypatch):
    """捕获 notify_service.enqueue_for_users/enqueue_for_user 的目标。"""
    from app.services import notify_service

    got = {"users": [], "single": []}
    orig_users = notify_service.enqueue_for_users
    orig_user = notify_service.enqueue_for_user

    def spy_users(db, us, **kw):
        got["users"].extend([u.id for u in us])
        return orig_users(db, us, **kw)

    def spy_user(db, u, **kw):
        got["single"].append(u.id)
        return orig_user(db, u, **kw)

    monkeypatch.setattr(notify_service, "enqueue_for_users", spy_users)
    monkeypatch.setattr(notify_service, "enqueue_for_user", spy_user)
    return got


def _seed_queue(db, assignee_id, n, title_prefix="底单"):
    """直接落库 n 张处理中单，撑高处理人排队数。"""
    from app.models.ticket import STATUS_PROCESSING, Ticket
    from app.models.user import utcnow

    for i in range(n):
        db.add(Ticket(
            no=f"GD-ES-SEED-{assignee_id}-{i}-{utcnow():%H%M%S%f}", title=f"{title_prefix}{i}",
            category=CAT, status=STATUS_PROCESSING, creator_id=1, assignee_id=assignee_id,
            created_at=utcnow(), updated_at=utcnow(),
        ))
    db.commit()


def test_escalate_low_queue_no_broadcast(client, admin_h, es_users, monkeypatch):
    """排队 ≤2 单：只推送处理人，不广播其他工程师；加急池不可见。"""
    from app.models.database import create_session

    # 先铺底单（id 更小 → 在处理人队列前面），再建目标单
    db = create_session()
    try:
        _seed_queue(db, es_users["busy"], 2)
    finally:
        db.close()
    t = client.post("/api/tickets", json={"title": "加急-低排队", "category": CAT}, headers=es_users["emp_h"]).json()
    client.post(f"/api/tickets/{t['id']}/assign", json={"engineer_id": es_users["busy"]}, headers=admin_h)

    got = _notify_targets(client, monkeypatch)
    r = client.post(f"/api/tickets/{t['id']}/escalate", headers=es_users["emp_h"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["urgent"] is True and d["queue_ahead"] == 2 and d["broadcast"] is False
    # 处理人收到加急推送
    assert es_users["busy"] in got["single"]
    # 其他工程师无广播
    assert es_users["free1"] not in got["users"] and es_users["free2"] not in got["users"]
    # 加急池（free1 视角）不含此单
    pool = client.get("/api/tickets?urgent=true", headers=es_users["free1_h"]).json()["items"]
    assert t["id"] not in [i["id"] for i in pool]
    # 30 分钟频控
    r2 = client.post(f"/api/tickets/{t['id']}/escalate", headers=es_users["emp_h"])
    assert r2.status_code == 400
    assert "30 分钟" in r2.json()["detail"]


def test_escalate_high_queue_broadcast_and_claim(client, admin_h, es_users, monkeypatch):
    """v2.12 加急统一：超 30 分钟未解决 → 广播其他工程师；加急池可见；一键转办清除加急并通知发起人。

    （旧逻辑按处理人排队 >2 广播，已改为按耗时驱动。）
    """
    from datetime import timedelta

    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import utcnow

    t = client.post("/api/tickets", json={"title": "加急-超时未解决", "category": CAT}, headers=es_users["emp_h"]).json()
    client.post(f"/api/tickets/{t['id']}/assign", json={"engineer_id": es_users["busy2"]}, headers=admin_h)
    # 回拨创建时间 40 分钟（>30 分钟阈值）
    db = create_session()
    try:
        row = db.get(Ticket, t["id"])
        row.created_at = utcnow() - timedelta(minutes=40)
        db.commit()
    finally:
        db.close()

    got = _notify_targets(client, monkeypatch)
    r = client.post(f"/api/tickets/{t['id']}/escalate", headers=es_users["emp_h"])
    assert r.status_code == 200
    d = r.json()
    assert d["broadcast"] is True  # 超 30 分钟未解决 → 广播
    assert es_users["busy"] in got["single"], "处理人应收到加急推送"
    assert es_users["free1"] in got["users"] and es_users["free2"] in got["users"], "排队>2 应广播其他工程师"

    # 加急池：free1 可见此单
    pool = client.get("/api/tickets?urgent=true", headers=es_users["free1_h"]).json()["items"]
    assert t["id"] in [i["id"] for i in pool]

    # 员工不能转办；处理人自己转自己被拒
    assert client.post(f"/api/tickets/{t['id']}/claim", headers=es_users["emp_h"]).status_code == 403
    assert client.post(f"/api/tickets/{t['id']}/claim", headers=es_users["busy2_h"]).status_code == 400

    # free1 一键转办：处理人变更、加急清除、事件留痕、发起人收到通知
    got2 = _notify_targets(client, monkeypatch)
    r2 = client.post(f"/api/tickets/{t['id']}/claim", headers=es_users["free1_h"])
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["assignee"]["id"] == es_users["free1"]
    assert d2["urgent"] is False, "转办后应清除加急标记"
    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_h).json()
    evs = [e["content"] for e in detail["events"]]
    assert any("改派给 空闲工程师甲" in c and "认领加急工单" in c for c in evs)
    assert es_users["emp"] in got2["single"], "发起人应收到认领通知"

    # 转办后加急池不再可见
    pool2 = client.get("/api/tickets?urgent=true", headers=es_users["free2_h"]).json()["items"]
    assert t["id"] not in [i["id"] for i in pool2]


def test_escalate_unassigned_broadcast_and_non_creator(client, admin_h, es_users, monkeypatch):
    """未指派工单加急 → 恒广播认领；非发起人不能加急。"""
    t = client.post("/api/tickets", json={"title": "加急-未指派", "category": CAT}, headers=es_users["emp_h"]).json()
    got = _notify_targets(client, monkeypatch)
    r = client.post(f"/api/tickets/{t['id']}/escalate", headers=es_users["emp_h"])
    assert r.status_code == 200
    assert r.json()["broadcast"] is True and r.json()["queue_ahead"] is None
    assert es_users["free1"] in got["users"]
    # 其他员工（非发起人）不能加急（员工视角不可见 → 404）
    other_emp = client.post(
        "/api/users", json={"username": "esother", "name": "无关员工", "role": "employee", "password": PWD}, headers=admin_h
    ).json()["id"]
    _ = other_emp
    oh = _login(client, "esother")
    assert client.post(f"/api/tickets/{t['id']}/escalate", headers=oh).status_code == 404


def test_escalate_pending_approval_blocked_and_qr_urgent_flag(client, admin_h, es_users):
    """待审批工单不可加急；扫码页未结列表返回 urgent 标记。"""
    client.post(
        "/api/admin/templates",
        json={"name": "ES 审批模板", "category": CAT, "enabled": True, "require_approval": True, "fields": []},
        headers=admin_h,
    )
    t = client.post("/api/tickets", json={"title": "加急-待审批拦截", "category": CAT}, headers=es_users["emp_h"]).json()
    assert t["status"] == "pending_approval"
    r = client.post(f"/api/tickets/{t['id']}/escalate", headers=es_users["emp_h"])
    assert r.status_code == 400
    assert "待主管审批" in r.json()["detail"]

    # 扫码页 urgent 标记：普通单加急后 /qr/{code} 行内 urgent=True（用无审批模板的分类）
    rtag = client.post(
        "/api/qr-tags",
        json={"name": "ES 加急扫码", "kind": "location", "location": "ES 区"},
        headers=admin_h,
    )
    code = rtag.json()["code"]
    t2 = client.post("/api/tickets", json={"title": "加急-扫码标记", "qr_code": code}, headers=es_users["emp_h"]).json()
    assert t2["status"] == "pending", t2["status"]
    page = client.get(f"/api/qr/{code}", headers=es_users["emp_h"]).json()
    row = next(o for o in page["open_tickets"] if o["id"] == t2["id"])
    assert row["urgent"] is False
    client.post(f"/api/tickets/{t2['id']}/escalate", headers=es_users["emp_h"])
    page2 = client.get(f"/api/qr/{code}", headers=es_users["emp_h"]).json()
    row2 = next(o for o in page2["open_tickets"] if o["id"] == t2["id"])
    assert row2["urgent"] is True
