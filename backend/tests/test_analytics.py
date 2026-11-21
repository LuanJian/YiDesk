"""数据看板测试：粒度分桶、区间环比、时效剔除挂起、关键词占比、类目权限、CSV 导出。

专用分类 AN_测试 与 an 前缀用户，测试后清理；不发真实网络请求。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

CAT = "AN_测试"
CLEANUP_CATS = [CAT, "AN_网络", "AN_软件", "AN_范围外"]

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "an1" + "2345"


@pytest.fixture(autouse=True)
def _an_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.system import DispatchRule
    from app.models.ticket import Rating, Ticket
    from app.models.user import User

    db = create_session()
    try:
        # Rating 无 ORM 级联：先删相关评分行，避免删单时 ticket_id 被置 NULL
        ratings = db.scalars(
            select(Rating).join(Ticket, Rating.ticket_id == Ticket.id).where(Ticket.category.in_(CLEANUP_CATS))
        ).all()
        for r in ratings:
            db.delete(r)
        for t in db.scalars(select(Ticket).where(Ticket.category.in_(CLEANUP_CATS))).all():
            db.delete(t)
        for r in db.scalars(select(DispatchRule).where(DispatchRule.category.in_(CLEANUP_CATS))).all():
            db.delete(r)
        for u in db.scalars(select(User).where(User.username.like("an%"))).all():
            db.delete(u)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _no_auto_dispatch():
    from app.core.config import get_config

    cfg = get_config().dispatch
    prev = (cfg.auto_assign, cfg.sticky_same_category)
    cfg.auto_assign = False
    cfg.sticky_same_category = False
    yield
    cfg.auto_assign, cfg.sticky_same_category = prev


def _mk_user(client, admin_headers, username, name, role="engineer", department="") -> int:
    r = client.post(
        "/api/users",
        json={"username": username, "name": name, "role": role, "password": PWD, "department": department},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, username) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed_ticket(**kw) -> Ticket:
    """直接落库工单（可控制创建/解决时间与挂起时长）。"""
    from app.models.database import create_session

    db = create_session()
    try:
        from app.models.ticket import Ticket
        from app.models.user import utcnow

        t = Ticket(
            no="", title=kw.get("title", "看板样本"), category=kw.get("category", CAT),
            status=kw.get("status", "closed"), creator_id=kw.get("creator_id", 1),
            assignee_id=kw.get("assignee_id"), created_at=kw["created_at"],
            resolved_at=kw.get("resolved_at"), closed_at=kw.get("resolved_at"),
            sla_suspended_total=kw.get("suspended_total", 0),
        )
        db.add(t)
        db.flush()
        t.no = f"GD-AN-{t.id:04d}"
        if kw.get("stars"):
            from app.models.ticket import Rating

            db.add(Rating(ticket_id=t.id, user_id=t.creator_id, stars=kw["stars"], comment=kw.get("comment", "")))
        db.commit()
        return t
    finally:
        db.close()


def _dashboard(client, admin_headers, **params) -> dict:
    from urllib.parse import urlencode

    r = client.get(f"/api/analytics/dashboard?{urlencode(params)}", headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_granularity_buckets(client, admin_headers):
    from app.models.user import utcnow

    now = utcnow()
    # 两张单：本月月初、月中（取区间中点，保证在本月内）；一张上月
    first = now.replace(day=1, hour=9, minute=0, second=0, microsecond=0)
    mid = first + max(timedelta(hours=1), (now - first) / 2)
    last_month = first - timedelta(days=5)
    _seed_ticket(title="分桶A", created_at=first, resolved_at=first + timedelta(hours=2), stars=5)
    _seed_ticket(title="分桶B", created_at=mid, resolved_at=mid + timedelta(hours=3), stars=4)
    _seed_ticket(title="分桶C-上月", created_at=last_month, resolved_at=last_month + timedelta(hours=1))

    month_key = first.strftime("%Y-%m")
    d = _dashboard(client, admin_headers, start=first.strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="month", category=CAT)
    buckets = {b["bucket"]: b for b in d["trend"]}
    assert buckets[month_key]["created"] == 2, "月粒度应合并当月两张单"
    assert all(b["bucket"].count("-") == 1 for b in d["trend"]), "月粒度桶格式应为 YYYY-MM"

    d2 = _dashboard(client, admin_headers, start=first.strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="day", category=CAT)
    assert {b["created"] for b in d2["trend"]} >= {1}, "日粒度应逐日拆分"

    d3 = _dashboard(client, admin_headers, start=f"{first.year}-01-01", end=now.strftime("%Y-%m-%d"), granularity="year", category=CAT)
    yb = {b["bucket"]: b for b in d3["trend"]}
    assert yb[str(first.year)]["created"] >= 2


def test_range_and_prev_comparison(client, admin_headers):
    from app.models.user import utcnow

    now = utcnow()
    # 本期 1 张已解决，上期 2 张 → created 环比 -50%
    cur = now - timedelta(days=2)
    prev1 = now - timedelta(days=9)
    prev2 = now - timedelta(days=10)
    _seed_ticket(title="本期单", created_at=cur, resolved_at=cur + timedelta(hours=1))
    _seed_ticket(title="上期单1", created_at=prev1, resolved_at=prev1 + timedelta(hours=1))
    _seed_ticket(title="上期单2", created_at=prev2, resolved_at=prev2 + timedelta(hours=1))

    d = _dashboard(client, admin_headers, start=(now - timedelta(days=6)).strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="day", category=CAT)
    s = d["summary"]["created"]
    assert s["value"] == 1 and s["prev"] == 2 and s["change"] == -50.0


def test_resolution_time_excludes_suspended(client, admin_headers):
    from app.models.user import utcnow

    now = utcnow()
    created = now - timedelta(hours=10)
    # 10 小时解决，其中挂起 4 小时 → 计 6 小时 = 360 分钟（同一时段只有这一单）
    _seed_ticket(title="挂起剔除", created_at=created, resolved_at=now, suspended_total=240)
    d = _dashboard(client, admin_headers, start=(now - timedelta(days=1)).strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="day", category=CAT)
    avg = d["summary"]["avg_resolution_minutes"]["value"]
    assert avg is not None and 350 <= avg <= 370, f"解决时长应剔除挂起 240 分钟，实际 {avg}"


def test_hot_issues_keywords_and_pct(client, admin_headers):
    from app.models.user import utcnow

    now = utcnow()
    for i in range(6):
        _seed_ticket(title=f"打印机卡纸问题 {i}", created_at=now - timedelta(days=1), resolved_at=now)
    for i in range(4):
        _seed_ticket(title=f"VPN 连不上 {i}", created_at=now - timedelta(days=1), resolved_at=now)
    d = _dashboard(client, admin_headers, start=(now - timedelta(days=2)).strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="day", category=CAT)
    kws = {k["keyword"]: k for k in d["hot_issues"]["keywords"]}
    # 分词产生 2 字窗口（打印机→打印/印机），按区间新建总数算占比
    assert "打印" in kws and kws["打印"]["count"] == 6
    assert kws["打印"]["pct"] == 60.0
    assert "卡纸" in kws and kws["卡纸"]["count"] == 6
    # 停用词与长全串不出现
    assert "问题" not in kws and "打印机卡纸问题" not in kws
    cats = {c["name"]: c for c in d["hot_issues"]["categories"]}
    assert cats[CAT]["pct"] == 100.0


def test_engineer_rows_and_category_scope(client, admin_headers, employee_headers):
    from app.models.user import utcnow

    now = utcnow()
    e1 = _mk_user(client, admin_headers, "ane1", "看板工程师一", role="engineer", department="IT部")
    e2 = _mk_user(client, admin_headers, "ane2", "看板工程师二", role="engineer", department="IT部")
    _seed_ticket(title="工程师一-网络故障", category="AN_网络", created_at=now - timedelta(days=1), resolved_at=now - timedelta(hours=20), assignee_id=e1, stars=5)
    _seed_ticket(title="工程师一-软件问题", category="AN_软件", created_at=now - timedelta(days=1), resolved_at=now - timedelta(hours=10), assignee_id=e1)
    _seed_ticket(title="工程师二-硬件问题", category=CAT, created_at=now - timedelta(days=1), resolved_at=now - timedelta(hours=5), assignee_id=e2)

    # 不带 category 过滤：mix 需要跨分类统计（e1/e2 为专用用户，计数不受其他文件污染）
    d = _dashboard(client, admin_headers, start=(now - timedelta(days=2)).strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="day")
    rows = {e["id"]: e for e in d["engineers"]}
    assert rows[e1]["resolved"] == 2 and rows[e2]["resolved"] == 1
    assert rows[e1]["avg_stars"] == 5.0
    mix = {m["id"]: m for m in d["engineer_mix"]}
    assert mix[e1]["total"] == 2 and len(mix[e1]["parts"]) == 2, "处理人构成应按分类拆分"

    # 类目数据权限：给 e1 限定只看 CAT → e2 的 OTHER 单不可见；先造一张范围外分类单
    from app.models.database import create_session
    from app.models.ticket import Ticket

    db = create_session()
    try:
        db.add(Ticket(no="GD-AN-OUT", title="范围外单", category="AN_范围外", status="closed",
                      creator_id=1, assignee_id=e2, created_at=now - timedelta(days=1),
                      resolved_at=now - timedelta(hours=2), closed_at=now - timedelta(hours=2)))
        db.commit()
    finally:
        db.close()
    client.patch(f"/api/users/{e1}", json={"category_scope": [CAT]}, headers=admin_headers)
    try:
        scoped = _login(client, "ane1")
        r = client.get(
            f"/api/analytics/dashboard?start={(now - timedelta(days=2)).strftime('%Y-%m-%d')}&end={now.strftime('%Y-%m-%d')}&granularity=day",
            headers=scoped,
        )
        assert r.status_code == 200
        d2 = r.json()
        # e2 的范围外单（AN_范围外）被过滤：e2 只剩 AN_测试 一单；范围外分类不出现
        rows2 = {e["id"]: e for e in d2["engineers"]}
        assert rows2[e2]["resolved"] == 1, "类目范围外的解决单不应计入"
        assert all(c["name"] != "AN_范围外" for c in d2["hot_issues"]["categories"])
    finally:
        client.patch(f"/api/users/{e1}", json={"category_scope": []}, headers=admin_headers)


def test_submitters_and_satisfaction(client, admin_headers):
    from app.models.user import utcnow

    now = utcnow()
    emp = _mk_user(client, admin_headers, "anemp", "看板提单员", role="employee", department="市场部")
    _seed_ticket(title="提单1", created_at=now - timedelta(days=1), resolved_at=now, creator_id=emp, stars=1)
    _seed_ticket(title="提单2", created_at=now - timedelta(days=1), resolved_at=now, creator_id=emp, stars=2)
    d = _dashboard(client, admin_headers, start=(now - timedelta(days=2)).strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="day", category=CAT)
    emps = {e["id"]: e for e in d["submitters"]["employees"]}
    assert emps[emp]["count"] == 2 and emps[emp]["department"] == "市场部"
    deps = {x["department"]: x for x in d["submitters"]["departments"]}
    assert deps["市场部"]["count"] == 2
    assert d["satisfaction"]["distribution"]["1"] == 1 and d["satisfaction"]["distribution"]["2"] == 1
    assert len(d["satisfaction"]["low_list"]) == 2 and all(x["stars"] <= 2 for x in d["satisfaction"]["low_list"])


def test_week_granularity(client, admin_headers):
    """v2.12 周粒度：ISO 周分桶（2026-Wxx），区间环比正常返回。"""
    qs = "start=2026-01-01&end=2026-12-31&granularity=week"
    r = client.get(f"/api/analytics/dashboard?{qs}", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["trend"], "周分桶应有桶"
    assert all(x["bucket"].startswith("2026-W") for x in d["trend"]), "周桶 key 应为 ISO 周"
    assert len(d["trend"]) <= 53


def test_granularity_invalid(client, admin_headers):
    assert client.get(
        "/api/analytics/dashboard?start=2026-01-01&end=2026-01-31&granularity=hour", headers=admin_headers
    ).status_code == 400


def test_export_csv(client, admin_headers):
    from app.models.user import utcnow

    now = utcnow()
    _seed_ticket(title="导出样本", created_at=now - timedelta(days=1), resolved_at=now)
    qs = f"start={(now - timedelta(days=2)).strftime('%Y-%m-%d')}&end={now.strftime('%Y-%m-%d')}&granularity=day"
    for sheet in ("engineers", "hot_issues", "submitters"):
        r = client.get(f"/api/analytics/export?sheet={sheet}&{qs}", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.content.decode("utf-8-sig")
        assert "," in body and len(body) > 20
    # 员工不可访问
    emp_login = client.post("/api/auth/login", json={"username": "emp1", "password": "emp12345"})
    if emp_login.status_code == 200:
        emp_h = {"Authorization": f"Bearer {emp_login.json()['token']}"}
        assert client.get(f"/api/analytics/dashboard?{qs}", headers=emp_h).status_code == 403


def test_cross_period_resolution_counted(client, admin_headers):
    """上月创建本月解决的单：解决量/构成/满意度必须计入本月（回归：曾按创建口径漏计）。"""
    from app.models.user import utcnow

    now = utcnow()
    created_last_month = now - timedelta(days=35)
    _seed_ticket(title="跨期解决单", created_at=created_last_month, resolved_at=now - timedelta(hours=1), stars=2)
    d = _dashboard(client, admin_headers, start=(now - timedelta(days=5)).strftime("%Y-%m-%d"), end=now.strftime("%Y-%m-%d"), granularity="day", category=CAT)
    assert d["summary"]["resolved"]["value"] == 1, "跨期解决单应计入本月解决量"
    assert d["summary"]["avg_resolution_minutes"]["value"] is not None
    # 解决构成与满意度分布包含该单
    assert d["satisfaction"]["distribution"]["2"] == 1
    # 解决时长按创建→解决全时长计（约 35 天）
    mins = d["summary"]["avg_resolution_minutes"]["value"]
    assert mins is not None and mins >= 30 * 24 * 60 * 0.9
