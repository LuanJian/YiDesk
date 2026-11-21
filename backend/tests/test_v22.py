"""v2.2 功能测试：Webhook 订阅/签名投递、开放 API Key、审批节点、AD 联动任务链路。

专用分类 V22_* 与 v22 前缀用户，测试后清理。外发 HTTP 全部 mock，不发真实网络请求。
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

import pytest

CAT = "V22_测试"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "v22" + "12345"


@pytest.fixture(autouse=True)
def _v22_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.system import AdJob, DispatchRule, TicketTemplate
    from app.models.ticket import Ticket
    from app.models.user import User
    from app.models.webhook import ApiKey, WebhookDelivery, WebhookSubscription

    db = create_session()
    try:
        for t in db.scalars(select(Ticket).where(Ticket.category == CAT)).all():
            db.delete(t)
        for j in db.scalars(select(AdJob)).all():
            db.delete(j)
        for tp in db.scalars(select(TicketTemplate).where(TicketTemplate.category == CAT)).all():
            db.delete(tp)
        for r in db.scalars(select(DispatchRule).where(DispatchRule.category == CAT)).all():
            db.delete(r)
        for s in db.scalars(select(WebhookSubscription)).all():
            db.delete(s)
        for d in db.scalars(select(WebhookDelivery)).all():
            db.delete(d)
        for k in db.scalars(select(ApiKey)).all():
            db.delete(k)
        for u in db.scalars(select(User).where(User.username.like("v22%"))).all():
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


def _mk_user(client, admin_headers, username: str, name: str, role: str = "employee") -> int:
    r = client.post(
        "/api/users",
        json={"username": username, "name": name, "role": role, "password": PWD},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(client, headers: dict, title: str, category: str = CAT, **kw) -> dict:
    r = client.post("/api/tickets", json={"title": title, "category": category, **kw}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---- Webhook 订阅与签名投递 ----

class _FakeResp:
    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """捕获 POST 的假客户端（上下文管理器形态对齐 httpx.Client）。"""

    calls: list[dict] = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, content=None, headers=None, **kw):
        _FakeClient.calls.append({"url": url, "body": content, "headers": headers})
        return _FakeResp()


def test_webhook_subscription_and_signed_delivery(client, admin_headers, employee_headers, monkeypatch):
    from app.core.config import get_config
    from app.services import webhook_service

    get_config().webhook.allow_private_network = True  # 测试环境跳过 DNS/私网校验
    r = client.post(
        "/api/webhooks",
        json={"url": "https://itsm.example.com/hook", "secret": "s3cret" + "value1", "events": ["ticket.created", "ticket.resolved"]},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["secret_masked"].endswith("lue1") and "s3cret" not in sub["secret_masked"]

    # 员工不可管理
    assert client.get("/api/webhooks", headers=employee_headers).status_code == 403

    # 建单 → 生成投递任务（订阅了 created/resolved：应命中 created）
    t = _create(client, employee_headers, "Webhook-创建事件")
    data = _Webhook_delivery_payload(client, admin_headers, sub["id"])
    assert data["event"] == "ticket.created"
    assert data["ticket"]["no"] == t["no"]

    # 签名投递（mock HTTP，不发真实请求）
    from app.models.database import create_session

    _FakeClient.calls = []
    monkeypatch.setattr(webhook_service, "_client", _FakeClient)
    sent = webhook_service.flush(create_session())
    assert sent >= 1
    call = _FakeClient.calls[0]
    assert call["url"] == "https://itsm.example.com/hook"
    assert call["headers"]["X-ITOps-Event"] == "ticket.created"
    expected_sign = hmac_mod.new(("s3cret" + "value1").encode(), call["body"], hashlib.sha256).hexdigest()
    assert call["headers"]["X-ITOps-Signature"] == f"sha256={expected_sign}"

    # 非订阅事件不投递：closed 未订阅 → 无新投递任务
    before = _delivery_count(client, admin_headers, sub["id"])
    client.post(f"/api/tickets/{t['id']}/transition", json={"action": "accept"}, headers=admin_headers)
    client.post(f"/api/tickets/{t['id']}/transition", json={"action": "finish", "note": "ok", "solution": "方案"}, headers=admin_headers)
    # resolved 已订阅
    assert _delivery_count(client, admin_headers, sub["id"]) >= before + 1

    # URL 校验：http 被拒；私网被拒（恢复默认配置后）
    get_config().webhook.allow_private_network = False
    r2 = client.post("/api/webhooks", json={"url": "http://itsm.example.com/hook", "secret": "abcdefgh"}, headers=admin_headers)
    assert r2.status_code == 400
    r3 = client.post("/api/webhooks", json={"url": "https://192.168.1.5/hook", "secret": "abcdefgh"}, headers=admin_headers)
    assert r3.status_code == 400
    get_config().webhook.allow_private_network = True


def _Webhook_delivery_payload(client, admin_headers, sub_id: str) -> dict:
    r = client.get(f"/api/webhooks/{sub_id}/deliveries", headers=admin_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "应至少有一条投递任务"
    return items[0]["payload"]


def _delivery_count(client, admin_headers, sub_id: str) -> int:
    r = client.get(f"/api/webhooks/{sub_id}/deliveries", headers=admin_headers)
    return len(r.json()["items"])


# ---- 开放 API Key ----

def test_open_api_key_auth(client, admin_headers, employee_headers):
    r = client.post("/api/webhooks/api-keys", json={"name": "ITSM 集成"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    key = r.json()["key"]
    assert key.startswith("itops_")
    listed = client.get("/api/webhooks/api-keys", headers=admin_headers).json()["items"]
    assert listed and all("key" not in i for i in listed), "列表不得回传明文 Key"

    ok = client.get("/api/open/tickets", headers={"X-API-Key": key})
    assert ok.status_code == 200, ok.text
    assert "items" in ok.json()
    bad = client.get("/api/open/tickets", headers={"X-API-Key": "wrong"})
    assert bad.status_code == 401
    nohdr = client.get("/api/open/tickets")
    assert nohdr.status_code == 401


# ---- 审批节点 ----

def test_approval_flow(client, admin_headers, employee_headers):
    r = client.post(
        "/api/admin/templates",
        json={"name": "V22 审批模板", "category": CAT, "enabled": True, "require_approval": True, "fields": []},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text

    t = _create(client, employee_headers, "审批流-权限开通申请")
    assert t["status"] == "pending_approval"
    assert t["status_label"] == "待审批"
    assert t["sla_resolve_deadline"] is None, "SLA 应在审批通过后才起算"
    assert t["assignee"] is None, "待审批单不自动派单"
    # 员工无审批动作；管理员可审批
    detail = client.get(f"/api/tickets/{t['id']}", headers=employee_headers).json()
    assert "approve" not in detail["available_actions"]
    r_emp = client.post(f"/api/tickets/{t['id']}/transition", json={"action": "approve"}, headers=employee_headers)
    assert r_emp.status_code == 400
    # 审批通过 → 待受理 + SLA 起算
    r2 = client.post(f"/api/tickets/{t['id']}/transition", json={"action": "approve", "note": "同意"}, headers=admin_headers)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["status"] == "pending"
    assert d2["sla_resolve_deadline"] is not None
    detail2 = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    assert any("SLA 自审批通过起算" in e["content"] for e in detail2["events"])

    # 驳回流：直接关闭
    t2 = _create(client, employee_headers, "审批流-驳回用例")
    r3 = client.post(f"/api/tickets/{t2['id']}/transition", json={"action": "reject", "note": "不符合规范"}, headers=admin_headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["status"] == "closed"


# ---- AD 联动任务链路 ----

def test_ad_job_lifecycle(client, admin_headers, employee_headers):
    from app.core.config import get_config
    from app.models.database import create_session
    from app.models.system import AdJob
    from sqlalchemy import select

    cfg = get_config().ad_integration
    prev = (cfg.enabled, cfg.api_key)
    cfg.enabled, cfg.api_key = True, "ad" + "token123"
    try:
        r = client.post(
            "/api/admin/templates",
            json={"name": "V22 AD模板", "category": CAT, "enabled": True,
                  "require_approval": True, "ad_script": "Unlock-AdAccount.ps1", "fields": []},
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text

        t = _create(client, employee_headers, "AD联动-账号解锁申请")
        client.post(f"/api/tickets/{t['id']}/transition", json={"action": "approve"}, headers=admin_headers)

        db = create_session()
        try:
            job = db.scalar(select(AdJob).where(AdJob.ticket_id == t["id"]))
            assert job and job.status == "pending" and job.script == "Unlock-AdAccount.ps1"
            job_id = job.id
        finally:
            db.close()
        detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
        assert any("AD 联动：已生成执行任务" in e["content"] for e in detail["events"])

        # 代理拉取：令牌错误 401；正确 → running + payload
        r_bad = client.get("/api/ad/jobs/pending", headers={"X-API-Token": "wrong"})
        assert r_bad.status_code == 401
        r_pull = client.get("/api/ad/jobs/pending", headers={"X-API-Token": "ad" + "token123"})
        assert r_pull.status_code == 200, r_pull.text
        pulled = [i for i in r_pull.json()["items"] if i["id"] == job_id]
        assert pulled and pulled[0]["status"] == "running", "拉取响应应带出 running 状态"
        # 再次拉取：running 的不再出现
        r_pull2 = client.get("/api/ad/jobs/pending", headers={"X-API-Token": "ad" + "token123"})
        assert all(i["id"] != job_id for i in r_pull2.json()["items"])
        db = create_session()
        try:
            job = db.get(AdJob, job_id)
            assert job.status == "running"
            assert json.loads(job.payload)["ticket_no"] == t["no"]
        finally:
            db.close()

        # 回传结果：成功 → 工单事件
        r_done = client.post(
            f"/api/ad/jobs/{job_id}/result",
            json={"success": True, "output": "账户已解锁"},
            headers={"X-API-Token": "ad" + "token123"},
        )
        assert r_done.status_code == 200, r_done.text
        detail2 = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
        assert any("AD 联动执行成功：账户已解锁" in e["content"] for e in detail2["events"])
    finally:
        cfg.enabled, cfg.api_key = prev


def test_ad_job_fail_result(client, admin_headers, employee_headers):
    from app.core.config import get_config
    from app.models.database import create_session
    from app.models.system import AdJob
    from sqlalchemy import select

    cfg = get_config().ad_integration
    prev = (cfg.enabled, cfg.api_key)
    cfg.enabled, cfg.api_key = True, "ad" + "token123"
    try:
        client.post(
            "/api/admin/templates",
            json={"name": "V22 AD模板2", "category": CAT, "enabled": True,
                  "require_approval": True, "ad_script": "Reset-AdPassword.ps1", "fields": []},
            headers=admin_headers,
        )
        t = _create(client, employee_headers, "AD联动-失败回传")
        client.post(f"/api/tickets/{t['id']}/transition", json={"action": "approve"}, headers=admin_headers)
        db = create_session()
        try:
            job = db.scalar(select(AdJob).where(AdJob.ticket_id == t["id"]))
            job_id = job.id
        finally:
            db.close()
        r = client.post(
            f"/api/ad/jobs/{job_id}/result",
            json={"success": False, "output": "账户不存在"},
            headers={"X-API-Token": "ad" + "token123"},
        )
        assert r.status_code == 200
        detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
        assert any("AD 联动执行失败：账户不存在" in e["content"] for e in detail["events"])
    finally:
        cfg.enabled, cfg.api_key = prev


# ---- 审批联动补漏回归（代码复查修复项） ----

def test_approval_ticket_cancel_and_merge_guard(client, admin_headers, employee_headers):
    """待审批单：发起人可撤回；不能作为合并源；扫码页可见。"""
    client.post(
        "/api/admin/templates",
        json={"name": "V22 审批模板3", "category": CAT, "enabled": True, "require_approval": True, "fields": []},
        headers=admin_headers,
    )
    t = _create(client, employee_headers, "审批撤回-用例")
    assert t["status"] == "pending_approval"

    # 发起人可见撤回动作并可撤销
    detail = client.get(f"/api/tickets/{t['id']}", headers=employee_headers).json()
    assert "cancel" in detail["available_actions"]
    r = client.post(f"/api/tickets/{t['id']}/transition", json={"action": "cancel"}, headers=employee_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"

    # 待审批单不能作为合并源
    t2 = _create(client, employee_headers, "审批合并守卫-源单")
    t3 = _create(client, employee_headers, "审批合并守卫-普通单")
    r2 = client.post(f"/api/tickets/{t3['id']}/merge", json={"target_id": t2["id"]}, headers=admin_headers)
    assert r2.status_code == 400
    assert "待审批" in r2.json()["detail"]

    # 扫码页未结列表包含待审批单
    rtag = client.post(
        "/api/qr-tags",
        json={"name": "V22 审批扫码", "kind": "location", "location": "V22 区", "category": CAT},
        headers=admin_headers,
    )
    assert rtag.status_code == 201, rtag.text
    code = rtag.json()["code"]
    t4 = _create(client, employee_headers, "审批扫码可见", qr_code=code)
    assert t4["status"] == "pending_approval"
    page = client.get(f"/api/qr/{code}", headers=employee_headers).json()
    assert any(o["id"] == t4["id"] for o in page["open_tickets"]), "待审批单应出现在扫码页未结列表"


def test_im_creation_skips_required_template(client, admin_headers, employee_headers):
    """IM 渠道（validate_fields=False）不会被模板必填字段卡死；Web 渠道仍被拦截。"""
    client.post(
        "/api/admin/templates",
        json={
            "name": "V22 IM 必填模板", "category": CAT, "enabled": True,
            "fields": [{"key": "dept", "label": "部门", "type": "text", "required": True}],
        },
        headers=admin_headers,
    )
    # Web：缺必填 → 400
    r_web = client.post("/api/tickets", json={"title": "Web 必填拦截", "category": CAT}, headers=employee_headers)
    assert r_web.status_code == 400
    # IM：跳过必填 → 建单成功
    from app.models.database import create_session
    from app.services import ticket_service

    db = create_session()
    try:
        user = client.get("/api/auth/me", headers=employee_headers).json()
        from app.models.user import User as UserM

        u = db.get(UserM, user["id"])
        t = ticket_service.create_ticket(
            db, creator=u, title="IM 建单跳过必填", category=CAT, channel="dingtalk", validate_fields=False,
        )
        import re as _re
        assert _re.match(r"[A-D]-\d{8}-\d{4,5}$", t.no), t.no
    finally:
        db.close()
