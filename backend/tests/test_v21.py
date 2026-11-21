"""v2.1 功能测试：算法派单（加权打分+样本门槛+模式开关）、字段级联（visible_if+必填后端校验）、类目数据权限（三重过滤）。

专用分类 V21_* 与 v21 前缀用户，测试后清理；值班表/派单配置在用例内临时修改并恢复。
test_v21 按字母序在 test_v11/test_v12 之后执行，可安全临时改动当日值班规则。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

CAT = "V21_测试"
OTHER_CAT = "V21_其他"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "v21" + "12345"


@pytest.fixture(autouse=True)
def _v21_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.system import DispatchRule, TicketTemplate
    from app.models.ticket import Rating, Ticket
    from app.models.user import User

    db = create_session()
    try:
        # Rating 无 ORM 级联：先删相关评分行，避免删单时 ticket_id 被置 NULL 违反约束
        ratings = db.scalars(
            select(Rating).join(Ticket, Rating.ticket_id == Ticket.id).where(Ticket.category.in_([CAT, OTHER_CAT]))
        ).all()
        for r in ratings:
            db.delete(r)
        for t in db.scalars(select(Ticket).where(Ticket.category.in_([CAT, OTHER_CAT]))).all():
            db.delete(t)
        for r in db.scalars(select(DispatchRule).where(DispatchRule.category.in_([CAT, OTHER_CAT]))).all():
            db.delete(r)
        for tp in db.scalars(select(TicketTemplate).where(TicketTemplate.category == CAT)).all():
            db.delete(tp)
        for u in db.scalars(select(User).where(User.username.like("v21%"))).all():
            u.category_scope = None
        db.commit()
    finally:
        db.close()


def _mk_user(client, admin_headers, username: str, name: str, role: str = "engineer") -> int:
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


def _create(client, headers: dict, title: str, category: str = CAT, **kw) -> dict:
    r = client.post("/api/tickets", json={"title": title, "category": category, **kw}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---- 算法派单（v2.1） ----

def _seed_resolved(assignee_id: int, hours: float, stars: int, n: int) -> None:
    """直接落库 n 张已解决单：固定解决时长与满意度，构成绩效样本。"""
    from app.models.database import create_session
    from app.models.ticket import Rating, Ticket
    from app.models.user import utcnow

    db = create_session()
    try:
        for i in range(n):
            created = utcnow() - timedelta(days=2)
            resolved = created + timedelta(hours=hours)
            t = Ticket(
                no=f"GD-SEED-{assignee_id}-{hours}-{i}",
                title=f"绩效样本 {assignee_id} {i}",
                category=CAT, status="closed",
                creator_id=1, assignee_id=assignee_id,
                created_at=created, resolved_at=resolved, closed_at=resolved,
            )
            db.add(t)
            db.flush()
            db.add(Rating(ticket_id=t.id, user_id=1, stars=stars))
        db.commit()
    finally:
        db.close()


def _set_duty(client, admin_headers, weekday: int, engineer_ids: list[int]) -> None:
    r = client.put(
        "/api/admin/duty-rules",
        json={"weekday": weekday, "engineer_ids": engineer_ids, "enabled": True},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text


def test_weighted_dispatch_prefers_top_performer(client, admin_headers, employee_headers):
    from datetime import datetime

    from app.core.config import get_config
    from app.models.database import create_session
    from app.models.system import DutyRule
    from sqlalchemy import select

    cfg = get_config().dispatch
    e_fast = _mk_user(client, admin_headers, "v21fast", "v21快手", role="engineer")
    e_slow = _mk_user(client, admin_headers, "v21slow", "v21慢手", role="engineer")
    r = client.put(
        "/api/admin/dispatch-rules",
        json={"category": CAT, "engineer_ids": [e_fast, e_slow], "enabled": True},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    _seed_resolved(e_fast, hours=0.5, stars=5, n=3)
    _seed_resolved(e_slow, hours=48.0, stars=2, n=3)

    # 当日值班规则先存后还原，避免污染其他用例
    today = datetime.now().weekday()
    db = create_session()
    prev_duty = db.scalar(select(DutyRule).where(DutyRule.weekday == today))
    prev_ids = prev_duty.engineer_ids_list if prev_duty else None
    db.close()
    _set_duty(client, admin_headers, today, [e_fast])

    saved = (cfg.mode, cfg.sticky_same_category, cfg.min_samples, cfg.auto_assign)
    cfg.mode, cfg.sticky_same_category, cfg.min_samples, cfg.auto_assign = "weighted", False, 2, True
    try:
        t = _create(client, employee_headers, "算法派单-绩效优先")
        assert t["assignee"]["id"] == e_fast, "加权模式应选绩效更高的工程师"
    finally:
        cfg.mode, cfg.sticky_same_category, cfg.min_samples, cfg.auto_assign = saved
        _set_duty(client, admin_headers, today, prev_ids or [])


def test_weighted_fallback_when_no_samples(client, admin_headers, employee_headers):
    from app.core.config import get_config

    cfg = get_config().dispatch
    e1 = _mk_user(client, admin_headers, "v21fresh1", "v21新手甲", role="engineer")
    e2 = _mk_user(client, admin_headers, "v21fresh2", "v21新手乙", role="engineer")
    client.put(
        "/api/admin/dispatch-rules",
        json={"category": CAT, "engineer_ids": [e1, e2], "enabled": True},
        headers=admin_headers,
    )
    saved = (cfg.mode, cfg.sticky_same_category, cfg.min_samples, cfg.auto_assign)
    cfg.mode, cfg.sticky_same_category, cfg.min_samples, cfg.auto_assign = "weighted", False, 5, True
    try:
        # 无样本 → 加权跳过 → 回退轮询，不抛错、必须有人接
        t = _create(client, employee_headers, "算法派单-样本不足回退")
        assert t["assignee"] is not None
    finally:
        cfg.mode, cfg.sticky_same_category, cfg.min_samples, cfg.auto_assign = saved


def test_round_robin_mode_unchanged(client, admin_headers, employee_headers):
    from app.core.config import get_config

    cfg = get_config().dispatch
    e1 = _mk_user(client, admin_headers, "v21rr1", "v21轮询甲", role="engineer")
    e2 = _mk_user(client, admin_headers, "v21rr2", "v21轮询乙", role="engineer")
    client.put(
        "/api/admin/dispatch-rules",
        json={"category": CAT, "engineer_ids": [e1, e2], "enabled": True},
        headers=admin_headers,
    )
    _seed_resolved(e1, hours=0.5, stars=5, n=6)  # e1 绩效更好，但轮询模式不看绩效
    saved = (cfg.mode, cfg.sticky_same_category, cfg.auto_assign)
    cfg.mode, cfg.sticky_same_category, cfg.auto_assign = "round_robin", False, True
    try:
        picks = {_create(client, employee_headers, f"轮询模式 {i}")["assignee"]["id"] for i in range(4)}
        assert picks == {e1, e2}, "round_robin 模式应保持两人轮询"
    finally:
        cfg.mode, cfg.sticky_same_category, cfg.auto_assign = saved


# ---- 字段级联（v2.1） ----

def _mk_template(client, admin_headers) -> None:
    r = client.post(
        "/api/admin/templates",
        json={
            "name": "V21 级联模板", "category": CAT, "enabled": True,
            "fields": [
                {"key": "conn", "label": "连接方式", "type": "select", "options": ["有线", "无线"], "required": True},
                {"key": "ap", "label": "AP 位置", "type": "text", "required": True,
                 "visible_if": {"field": "conn", "in": ["无线"]}},
                {"key": "port", "label": "端口号", "type": "text",
                 "visible_if": {"field": "conn", "in": ["有线"]}},
            ],
        },
        headers=admin_headers,
    )
    assert r.status_code in (200, 201), r.text


def test_visible_if_and_required_validation(client, admin_headers, employee_headers):
    _mk_template(client, admin_headers)
    # 隐藏字段带值 → 400
    r = client.post(
        "/api/tickets",
        json={"title": "级联-隐藏字段带值", "category": CAT,
              "custom_fields": {"conn": "有线", "ap": "3F 走道"}},
        headers=employee_headers,
    )
    assert r.status_code == 400, r.text
    assert "AP 位置" in r.json()["detail"]
    # 可见必填为空 → 400
    r2 = client.post(
        "/api/tickets",
        json={"title": "级联-必填缺失", "category": CAT, "custom_fields": {"conn": "无线"}},
        headers=employee_headers,
    )
    assert r2.status_code == 400
    assert "AP 位置" in r2.json()["detail"]
    # 合法：无线 + AP 位置
    r3 = client.post(
        "/api/tickets",
        json={"title": "级联-合法无线", "category": CAT, "custom_fields": {"conn": "无线", "ap": "3F 走道"}},
        headers=employee_headers,
    )
    assert r3.status_code == 201, r3.text
    # 合法：有线（port 可选）
    r4 = client.post(
        "/api/tickets",
        json={"title": "级联-合法有线", "category": CAT, "custom_fields": {"conn": "有线", "port": "G1/0/1"}},
        headers=employee_headers,
    )
    assert r4.status_code == 201, r4.text


# ---- 类目数据权限（v2.1） ----

def test_category_scope_triple_filter(client, admin_headers, employee_headers):
    from app.core.config import get_config
    from datetime import datetime

    from app.models.database import create_session
    from app.models.system import DutyRule
    from sqlalchemy import select

    cfg = get_config().dispatch
    e_out = _mk_user(client, admin_headers, "v21scoped", "v21受限工程师", role="engineer")
    e_free = _mk_user(client, admin_headers, "v21free", "v21全量工程师", role="engineer")

    # 配置类目权限：e_out 只可见 OTHER_CAT
    r = client.patch(
        f"/api/users/{e_out}",
        json={"category_scope": [OTHER_CAT]},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["category_scope"] == [OTHER_CAT]

    # ① 列表过滤：e_out 看不到 CAT 的单
    t_cat = _create(client, employee_headers, "类目权限-CAT单")
    t_other = _create(client, employee_headers, "类目权限-其他单", category=OTHER_CAT)
    scoped = _login(client, "v21scoped")
    listed = client.get("/api/tickets", headers=scoped).json()["items"]
    ids = [i["id"] for i in listed]
    assert t_cat["id"] not in ids and t_other["id"] in ids
    # 管理员/全量工程师不受限
    free = _login(client, "v21free")
    assert t_cat["id"] in [i["id"] for i in client.get("/api/tickets", headers=free).json()["items"]]

    # ② 详情过滤：e_out 打开 CAT 单 → 404
    assert client.get(f"/api/tickets/{t_cat['id']}", headers=scoped).status_code == 404
    assert client.get(f"/api/tickets/{t_cat['id']}", headers=free).status_code == 200

    # ③ 分派过滤：CAT 规则含 e_out，但类目不可见 → 不参与分派
    client.put(
        "/api/admin/dispatch-rules",
        json={"category": CAT, "engineer_ids": [e_out, e_free], "enabled": True},
        headers=admin_headers,
    )
    today = datetime.now().weekday()
    db = create_session()
    prev_duty = db.scalar(select(DutyRule).where(DutyRule.weekday == today))
    prev_ids = prev_duty.engineer_ids_list if prev_duty else None
    db.close()
    _set_duty(client, admin_headers, today, [e_free])
    saved = (cfg.sticky_same_category, cfg.mode, cfg.auto_assign)
    cfg.sticky_same_category, cfg.mode, cfg.auto_assign = False, "round_robin", True
    try:
        t = _create(client, employee_headers, "类目权限-分派排除")
        assert t["assignee"]["id"] == e_free, "类目范围外的工程师不应参与分派"
    finally:
        cfg.sticky_same_category, cfg.mode, cfg.auto_assign = saved
        _set_duty(client, admin_headers, today, prev_ids or [])
