"""v1.1 新功能测试：附件、催单、导出、免登入口、卡片动作分发。"""
from __future__ import annotations

import io

from app.models.database import create_session
from app.models.user import User
from app.services.card_action_service import handle_card_action, parse_action
from app.services.intake_service import InboundDraft, handle_inbound

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082"
)


def _create(client, headers, **kw) -> dict:
    payload = {"title": kw.get("title", "v11 测试工单"), "category": "软件安装", "priority": "medium", **kw}
    r = client.post("/api/tickets", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---- 附件 ----

def test_attachment_roundtrip(client, admin_headers, employee_headers):
    t = _create(client, employee_headers, title="带附件的工单")
    tid = t["id"]

    r = client.post(
        f"/api/tickets/{tid}/attachments",
        files={"file": ("截图.png", io.BytesIO(PNG_1PX), "image/png")},
        headers=employee_headers,
    )
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["filename"] == "截图.png" and att["is_image"] and att["source"] == "web"

    # 详情带附件列表
    detail = client.get(f"/api/tickets/{tid}", headers=employee_headers).json()
    assert len(detail["attachments"]) == 1

    # 下载内容一致
    r = client.get(att["url"], headers=admin_headers)
    assert r.status_code == 200 and r.content == PNG_1PX

    # 其他员工不可见
    r = client.post("/api/auth/login", json={"username": "emp2", "password": "emp22222"})
    other = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get(att["url"], headers=other).status_code == 404


def test_attachment_rejections(client, employee_headers):
    t = _create(client, employee_headers, title="附件校验工单")
    tid = t["id"]

    # 非法扩展名
    r = client.post(
        f"/api/tickets/{tid}/attachments",
        files={"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/x-msdownload")},
        headers=employee_headers,
    )
    assert r.status_code == 400

    # 超过 10MB
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post(
        f"/api/tickets/{tid}/attachments",
        files={"file": ("big.txt", io.BytesIO(big), "text/plain")},
        headers=employee_headers,
    )
    assert r.status_code == 400


# ---- IM 图片建单 ----

def test_intake_image_creates_ticket_with_attachment(client):
    db = create_session()
    try:
        draft = InboundDraft(
            "dingtalk", "dd-img-user-1", "王五", "",
            extra={"images": [("dingtalk_1.png", PNG_1PX)]},
        )
        handle_inbound(db, draft)
    finally:
        db.close()
    # 重新查库断言（避免 lazy load 会话过期问题）
    db = create_session()
    try:
        from sqlalchemy import select

        from app.models.attachment import Attachment
        from app.models.ticket import Ticket

        user = db.scalar(select(User).where(User.dingtalk_userid == "dd-img-user-1"))
        ticket = db.scalar(select(Ticket).where(Ticket.creator_id == user.id).order_by(Ticket.id.desc()))
        assert ticket.title == "（图片报修）"
        atts = list(db.scalars(select(Attachment).where(Attachment.ticket_id == ticket.id)))
        assert len(atts) == 1 and atts[0].source == "dingtalk" and atts[0].size == len(PNG_1PX)
    finally:
        db.close()


def test_intake_text_with_images(client):
    db = create_session()
    try:
        draft = InboundDraft(
            "feishu", "fs-img-user-1", "赵六", "投影仪不亮，见截图",
            extra={"images": [("feishu_a.png", PNG_1PX)]},
        )
        handle_inbound(db, draft)
        from sqlalchemy import select

        from app.models.attachment import Attachment
        from app.models.ticket import Ticket

        user = db.scalar(select(User).where(User.feishu_open_id == "fs-img-user-1"))
        ticket = db.scalar(select(Ticket).where(Ticket.creator_id == user.id).order_by(Ticket.id.desc()))
        assert "投影仪不亮" in ticket.title
        atts = list(db.scalars(select(Attachment).where(Attachment.ticket_id == ticket.id)))
        assert len(atts) == 1 and atts[0].source == "feishu"
    finally:
        db.close()


# ---- 催单 ----

def test_urge_flow(client, admin_headers, employee_headers):
    t = _create(client, employee_headers, title="催单测试")
    tid = t["id"]

    # 工程师不能替别人催单
    r = client.post(f"/api/tickets/{tid}/urge", headers={"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": "eng1", "password": "eng12345"}).json()["token"]})
    assert r.status_code == 400

    # 发起人催单成功，30 分钟内重复被拒
    assert client.post(f"/api/tickets/{tid}/urge", headers=employee_headers).status_code == 200
    assert client.post(f"/api/tickets/{tid}/urge", headers=employee_headers).status_code == 400

    # 管理员视角详情里有催办记录
    detail = client.get(f"/api/tickets/{tid}", headers=admin_headers).json()
    assert any(ev["type"] == "urge" for ev in detail["events"])


# ---- 导出 ----

def test_export_csv(client, admin_headers, employee_headers):
    _create(client, employee_headers, title="导出测试工单A")
    r = client.get("/api/export/tickets", headers=admin_headers)
    assert r.status_code == 200
    body = r.content
    assert body.startswith(b"\xef\xbb\xbf")  # BOM
    text = body.decode("utf-8-sig")
    assert "工单编号" in text and "问题概述" in text and "导出测试工单A" in text

    # 员工无权导出
    assert client.get("/api/export/tickets", headers=employee_headers).status_code == 403


# ---- 免登入口（渠道未启用时的降级） ----

def test_oauth_endpoints_disabled(client):
    r = client.post("/api/auth/dingtalk-code", json={"code": "x"})
    assert r.status_code == 400 and "未启用" in r.json()["detail"]
    r = client.post("/api/auth/feishu-code", json={"code": "x", "redirect_uri": "http://x"})
    assert r.status_code == 400
    r = client.post("/api/auth/wecom-code", json={"code": "x"})
    assert r.status_code == 400


# ---- 卡片动作分发 ----

def test_card_action_parse():
    assert parse_action("ticket:accept:12") == ("accept", 12)
    assert parse_action(" ticket:close:3 ") == ("close", 3)
    assert parse_action("ticket:hack:1") is None
    assert parse_action("") is None


def test_card_action_permission_flow(client, admin_headers):
    # 准备一个绑定钉钉 ID 的工程师与员工
    r = client.post("/api/users", json={"username": "cardeng", "name": "卡片工程师", "role": "engineer", "password": "card12345"}, headers=admin_headers)
    assert r.status_code == 201
    r = client.post("/api/users", json={"username": "cardemp", "name": "卡片员工", "role": "employee", "password": "card22345"}, headers=admin_headers)
    assert r.status_code == 201

    db = create_session()
    try:
        eng = db.query(User).filter(User.username == "cardeng").one()
        emp = db.query(User).filter(User.username == "cardemp").one()
        eng.dingtalk_userid = "card-eng-dd"
        emp.dingtalk_userid = "card-emp-dd"
        db.commit()

        # 员工建单
        t = _create(client, {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": "cardemp", "password": "card22345"}).json()["token"]}, title="卡片流转工单")
        tid = t["id"]
    finally:
        db.close()

    # 员工点「接单」→ 无权限
    db = create_session()
    try:
        res = handle_card_action(db, channel="dingtalk", platform_user_id="card-emp-dd", action_value=f"ticket:accept:{tid}")
        assert not res.ok
    finally:
        db.close()

    # 工程师接单成功；重复接单被状态机拒绝
    db = create_session()
    try:
        res = handle_card_action(db, channel="dingtalk", platform_user_id="card-eng-dd", action_value=f"ticket:accept:{tid}")
        assert res.ok, res.message
        res2 = handle_card_action(db, channel="dingtalk", platform_user_id="card-eng-dd", action_value=f"ticket:accept:{tid}")
        assert not res2.ok  # processing 状态不允许 accept
    finally:
        db.close()
