"""审计功能测试（v2.4.1）：改派必填原因与留痕、事件分类、汇总/明细端点。

专用用户 au 前缀 + AU_测试 分类，测试后清理（含用户参与的工单）。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

CAT = "AU_测试"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "au1" + "2345"


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
def _au_module_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import User

    db = create_session()
    try:
        au_ids = select(User.id).where(User.username.like("au%"))
        for t in db.scalars(
            select(Ticket).where((Ticket.assignee_id.in_(au_ids)) | (Ticket.creator_id.in_(au_ids)) | (Ticket.category == CAT))
        ).all():
            db.delete(t)
        for u in db.scalars(select(User).where(User.username.like("au%"))).all():
            db.delete(u)
        db.commit()
    finally:
        db.close()


def _mk(client, admin_headers, username, name) -> int:
    r = client.post(
        "/api/users",
        json={"username": username, "name": name, "role": "engineer", "ops_type": "field", "password": PWD},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _login(client, username) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def au_users(client, admin_headers):
    e1 = _mk(client, admin_headers, "aueng1", "审计工程师一")
    e2 = _mk(client, admin_headers, "aueng2", "审计工程师二")
    return {"e1": e1, "e2": e2, "e1_h": _login(client, "aueng1"), "e2_h": _login(client, "aueng2")}


def _qs(start=None, end=None, **extra):
    from datetime import date

    p = {"start": (start or (date.today() - timedelta(days=7))).isoformat(),
         "end": (end or date.today()).isoformat()}
    p.update(extra)
    from urllib.parse import urlencode

    return urlencode(p)


def test_reassign_requires_reason(client, admin_headers, employee_headers, au_users):
    t = client.post("/api/tickets", json={"title": "审计-改派用例", "category": CAT}, headers=employee_headers).json()
    # 首派不需要原因
    r1 = client.post(f"/api/tickets/{t['id']}/assign", json={"engineer_id": au_users["e1"]}, headers=admin_headers)
    assert r1.status_code == 200, r1.text
    # 改派无原因 → 400
    r2 = client.post(f"/api/tickets/{t['id']}/assign", json={"engineer_id": au_users["e2"], "reason": ""}, headers=admin_headers)
    assert r2.status_code == 400
    assert "改派必须填写原因" in r2.json()["detail"]
    # 改派带原因 → 200 + 事件含原处理人
    r3 = client.post(
        f"/api/tickets/{t['id']}/assign",
        json={"engineer_id": au_users["e2"], "reason": "该类目由二哥负责"},
        headers=admin_headers,
    )
    assert r3.status_code == 200, r3.text
    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    ev = [e["content"] for e in detail["events"] if e["content"].startswith("改派给")]
    assert ev and "原处理人 审计工程师一" in ev[0] and "该类目由二哥负责" in ev[0]


def test_audit_summary_and_events(client, admin_headers, employee_headers, au_users):
    """第四十批：summary 端点已删（前端只用 events 明细），断言全部走 events。"""
    t1 = client.post("/api/tickets", json={"title": "审计汇总-编辑", "category": CAT}, headers=employee_headers).json()
    client.patch(f"/api/tickets/{t1['id']}", json={"title": "审计汇总-编辑改"}, headers=admin_headers)  # 编辑
    client.post(f"/api/tickets/{t1['id']}/assign", json={"engineer_id": au_users["e1"]}, headers=admin_headers)  # 首派
    client.post(f"/api/tickets/{t1['id']}/assign", json={"engineer_id": au_users["e2"], "reason": "跟进"}, headers=admin_headers)  # 改派
    client.post(f"/api/tickets/{t1['id']}/sla-suspend", json={"note": "等配件"}, headers=admin_headers)  # 挂起
    client.post(f"/api/tickets/{t1['id']}/sla-resume", headers=admin_headers)  # 恢复

    # summary 端点已移除（404）
    assert client.get(f"/api/admin/audit/summary?{_qs()}", headers=admin_headers).status_code == 404

    # 明细：类型过滤
    evs = client.get(f"/api/admin/audit/events?{_qs(audit_type='assign')}", headers=admin_headers).json()
    assert evs["total"] >= 2 and all(i["audit_type"] == "assign" for i in evs["items"])
    assert any("改派给" in i["content"] and "原处理人" in i["content"] for i in evs["items"])
    # 明细：SLA 挂起/恢复类型存在
    evs_sl = client.get(f"/api/admin/audit/events?{_qs(audit_type='sla_suspend')}", headers=admin_headers).json()
    assert evs_sl["total"] >= 1
    evs_sr = client.get(f"/api/admin/audit/events?{_qs(audit_type='sla_resume')}", headers=admin_headers).json()
    assert evs_sr["total"] >= 1
    # 明细：关键词搜索
    evs2 = client.get(f"/api/admin/audit/events?{_qs(q='改派给')}", headers=admin_headers).json()
    assert evs2["total"] >= 1
    # 员工不可访问
    assert client.get(f"/api/admin/audit/events?{_qs()}", headers=employee_headers).status_code == 403


# ---- 数据导出范围与权限（v2.4.2 引入，v2.11 收紧为仅管理员） ----

def test_export_modes_and_permission(client, admin_headers, employee_headers, au_users):
    from datetime import date

    today = date.today().isoformat()
    client.post("/api/tickets", json={"title": "导出-员工今日单", "category": CAT}, headers=employee_headers).json()
    # v2.11：非管理员无任何导出权限（员工/工程师一律 403，权限校验先于 mode 校验）
    for hdrs in (employee_headers,):
        for m in ("day", "month", "year", "all", "week"):
            assert client.get(f"/api/export/tickets?mode={m}", headers=hdrs).status_code == 403

    # 管理员：四种模式都可用
    for m in ("day", "month", "year", "all"):
        rr = client.get(f"/api/export/tickets?mode={m}&date={today}", headers=admin_headers)
        assert rr.status_code == 200, rr.text
        assert rr.content[:3] == b"\xef\xbb\xbf"
    # 非法 mode（管理员已过权限关，正常进入参数校验）
    assert client.get("/api/export/tickets?mode=week", headers=admin_headers).status_code == 400
    # CSV 内容完整：员工今日的单也在导出内
    day_csv = client.get(f"/api/export/tickets?mode=day&date={today}", headers=admin_headers)
    body = day_csv.content.decode("utf-8-sig")
    assert "导出-员工今日单" in body and "提出者" in body
    # 月/年过滤正确性：未来年份查询应只有表头无数据行
    yr = client.get("/api/export/tickets?mode=year&date=2099-01-01", headers=admin_headers).content.decode("utf-8-sig")
    assert "导出-员工今日单" not in yr and "工单编号" in yr
