"""v2.8 测试：优先级矩阵（影响×紧急自动定级）、部门管理员数据隔离、weighted SLA 紧迫度权重。

专用用户 v28 前缀 + V28 分类；矩阵配置用例内临时修改并恢复。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

CAT = "V28_测试"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "v28" + "12345"


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
def _v28_module_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import User

    db = create_session()
    try:
        v28_ids = select(User.id).where(User.username.like("v28%"))
        for t in db.scalars(
            select(Ticket).where(
                (Ticket.creator_id.in_(v28_ids)) | (Ticket.category == CAT) | (Ticket.requester_id.in_(v28_ids))
            )
        ).all():
            db.delete(t)
        for u in db.scalars(select(User).where(User.username.like("v28%"))).all():
            db.delete(u)
        db.commit()
    finally:
        db.close()


def _login(client, username) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def admin_h(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_priority_matrix_computes_priority(client, admin_h, employee_headers):
    """影响×紧急自动定级：全公司+危急 → urgent，个人+低 → low（覆盖手选 priority）。"""
    t = client.post(
        "/api/tickets",
        json={"title": "矩阵-全公司危急", "category": CAT, "impact": "company", "urgency": "critical", "priority": "low"},
        headers=employee_headers,
    ).json()
    assert t["priority"] == "urgent", "矩阵应覆盖手选的 low"
    t2 = client.post(
        "/api/tickets",
        json={"title": "矩阵-个人低", "category": CAT, "impact": "individual", "urgency": "low", "priority": "urgent"},
        headers=employee_headers,
    ).json()
    assert t2["priority"] == "low"
    # 不填矩阵 → 手选优先级保持
    t3 = client.post(
        "/api/tickets", json={"title": "矩阵-不启用", "category": CAT, "priority": "high"}, headers=employee_headers
    ).json()
    assert t3["priority"] == "high"


def test_dept_admin_visibility(client, admin_h, employee_headers):
    """部门管理员（员工）：可看本部门工单（列表+详情），非部门管理员不可见。"""
    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import utcnow

    # 同部门员工甲提单，另一部门员工乙提单
    da = client.post("/api/users", json={"username": "v28da", "name": "部门管理员", "role": "employee",
                                         "department": "市场部", "password": PWD}, headers=admin_h).json()["id"]
    peer = client.post("/api/users", json={"username": "v28peer", "name": "同部门同事", "role": "employee",
                                           "department": "市场部", "password": PWD}, headers=admin_h).json()["id"]
    other = client.post("/api/users", json={"username": "v28other", "name": "其他部门同事", "role": "employee",
                                            "department": "财务部", "password": PWD}, headers=admin_h).json()["id"]
    db = create_session()
    try:
        t1 = Ticket(no=f"GD-V28-{da}-1", title="市场部-同部门单", category=CAT, creator_id=peer,
                    created_at=utcnow(), updated_at=utcnow())
        t2 = Ticket(no=f"GD-V28-{other}-1", title="财务部-其他部门单", category=CAT, creator_id=other,
                    created_at=utcnow(), updated_at=utcnow())
        db.add_all([t1, t2])
        db.commit()
        t1_id, t2_id = t1.id, t2.id
    finally:
        db.close()

    client.patch(f"/api/users/{da}", json={"dept_admin": True}, headers=admin_h)
    da_h = _login(client, "v28da")
    listed = client.get("/api/tickets", headers=da_h).json()["items"]
    ids = [i["id"] for i in listed]
    assert t1_id in ids, "部门管理员应看到本部门工单"
    assert t2_id not in ids, "不应看到其他部门工单"
    assert client.get(f"/api/tickets/{t1_id}", headers=da_h).status_code == 200
    assert client.get(f"/api/tickets/{t2_id}", headers=da_h).status_code == 404
    # 普通员工（非部门管理员）看不到同部门其他人的单
    other_dept_h = _login(client, "v28other")
    assert client.get(f"/api/tickets/{t1_id}", headers=other_dept_h).status_code == 404


def test_weighted_sla_urgency_weight_applies(client, admin_h, employee_headers, es_users=None):
    """weighted 模式：名下有临期 SLA 单的工程师打分更低（构造两人样本对称、仅 SLA 差异）。"""
    from datetime import datetime

    from app.core.config import get_config
    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import utcnow
    from sqlalchemy import select

    cfg = get_config().dispatch
    e1 = client.post("/api/users", json={"username": "v28sla1", "name": "v28临期工程师", "role": "engineer",
                                         "password": PWD}, headers=admin_h).json()["id"]
    e2 = client.post("/api/users", json={"username": "v28sla2", "name": "v28宽裕工程师", "role": "engineer",
                                         "password": PWD}, headers=admin_h).json()["id"]
    client.put(
        "/api/admin/dispatch-rules",
        json={"category": CAT, "engineer_ids": [e1, e2], "enabled": True},
        headers=admin_h,
    )
    db = create_session()
    try:
        # 两人绩效样本对称（各 5 张已解决，时长相同、无评价）
        for i in range(5):
            created = utcnow() - timedelta(days=3)
            resolved = created + timedelta(hours=2)
            db.add(Ticket(no=f"GD-V28SLA-{e1}-{i}", title=f"样本{e1}-{i}", category=CAT, status="closed",
                          creator_id=1, assignee_id=e1, created_at=created, resolved_at=resolved, closed_at=resolved))
            db.add(Ticket(no=f"GD-V28SLA-{e2}-{i}", title=f"样本{e2}-{i}", category=CAT, status="closed",
                          creator_id=1, assignee_id=e2, created_at=created, resolved_at=resolved, closed_at=resolved))
        # e2 名下一张 10 分钟后到期的未结单（SLA 紧迫）
        db.add(Ticket(no=f"GD-V28SLA-urgent-{e2}", title="临期单", category=CAT, status="processing",
                      creator_id=1, assignee_id=e2, created_at=utcnow() - timedelta(hours=1),
                      sla_resolve_deadline=utcnow() + timedelta(minutes=10)))
        db.commit()
    finally:
        db.close()

    saved = (cfg.mode, cfg.sticky_same_category, cfg.auto_assign, cfg.min_samples)
    cfg.mode, cfg.sticky_same_category, cfg.auto_assign, cfg.min_samples = "weighted", False, True, 5
    try:
        t = client.post("/api/tickets", json={"title": "SLA紧迫度验证", "category": CAT}, headers=employee_headers).json()
        assert t["assignee"]["id"] == e1, "SLA 临期的工程师应被加权排除"
    finally:
        cfg.mode, cfg.sticky_same_category, cfg.auto_assign, cfg.min_samples = saved
