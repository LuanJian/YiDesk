"""渠道层测试：企微加解密回环、钉钉 webhook 域名校验、IM 入站自动注册与建单。"""
from __future__ import annotations

import base64
import os

from app.channels import wecom_crypto
from app.channels.dingtalk import _is_official_webhook
from app.models.database import create_session
from app.models.ticket import Ticket
from app.models.user import User
from app.services.intake_service import InboundDraft, handle_inbound

# ---- 企微回调加解密 ----

AES_KEY_B64 = base64.b64encode(os.urandom(32)).decode().rstrip("=")[:43] + "="


def test_wecom_signature():
    token, ts, nonce, enc = "t", "1700000000", "n", "abc"
    sig = wecom_crypto.signature(token, ts, nonce, enc)
    assert sig == wecom_crypto.signature(token, ts, nonce, enc)  # 确定性
    assert sig != wecom_crypto.signature(token, ts, "other", enc)
    assert wecom_crypto.verify_callback_signature(token, ts, nonce, enc, sig)
    assert not wecom_crypto.verify_callback_signature(token, ts, nonce, enc, "bad")


def test_wecom_encrypt_decrypt_roundtrip():
    corp_id = "ww1234567890"
    plain = "<xml><Content><![CDATA[打印机坏了]]></Content></xml>"
    enc = wecom_crypto.encrypt(AES_KEY_B64, plain, corp_id)
    assert wecom_crypto.decrypt(AES_KEY_B64, enc, corp_id) == plain


def test_wecom_decrypt_rejects_wrong_corp():
    enc = wecom_crypto.encrypt(AES_KEY_B64, "<xml>x</xml>", "ww_right")
    try:
        wecom_crypto.decrypt(AES_KEY_B64, enc, "ww_wrong")
        assert False, "应当拒绝错误 corp_id"
    except ValueError:
        pass


def test_wecom_parse_message():
    xml = "<xml><FromUserName><![CDATA[zhangsan]]></FromUserName><Content><![CDATA[ 电脑蓝屏了 ]]></Content></xml>"
    from_user, content = wecom_crypto.parse_text_message(xml)
    assert from_user == "zhangsan"
    assert content == "电脑蓝屏了"


# ---- 钉钉 webhook 校验（SSRF 防护） ----

def test_dingtalk_webhook_allowlist():
    assert _is_official_webhook("https://oapi.dingtalk.com/robot/send?access_token=x")
    assert _is_official_webhook("https://dingtalk.com/x")
    assert not _is_official_webhook("http://oapi.dingtalk.com/robot/send")  # 必须 https
    assert not _is_official_webhook("https://evil.example.com/robot/send")
    assert not _is_official_webhook("https://dingtalk.com.evil.com/x")
    assert not _is_official_webhook("")


# ---- IM 入站：自动注册 + 建单 + 命令 ----

def test_intake_auto_register_and_create(client):
    db = create_session()
    try:
        draft = InboundDraft("dingtalk", "dd-user-001", "张三", "会议室投影仪没信号")
        handle_inbound(db, draft)
        user = db.query(User).filter(User.dingtalk_userid == "dd-user-001").one()
        assert user.role == "employee"
        assert user.name == "张三"
        ticket = db.query(Ticket).filter(Ticket.creator_id == user.id).one()
        assert ticket.title.startswith("会议室投影仪没信号")
        assert ticket.channel == "dingtalk"
    finally:
        db.close()


def test_intake_commands_do_not_create_tickets(client):
    db = create_session()
    try:
        before = db.query(Ticket).count()
        handle_inbound(db, InboundDraft("feishu", "fs-user-001", "李四", "帮助"))
        handle_inbound(db, InboundDraft("feishu", "fs-user-001", "李四", "我的工单"))
        assert db.query(Ticket).count() == before
        user = db.query(User).filter(User.feishu_open_id == "fs-user-001").one()
        assert user.username.startswith("feishu_")
    finally:
        db.close()


def test_intake_second_message_binds_same_user(client):
    db = create_session()
    try:
        handle_inbound(db, InboundDraft("wecom", "wx-user-001", "王五", "VPN 连不上"))
        handle_inbound(db, InboundDraft("wecom", "wx-user-001", "王五", "邮箱打不开"))
        users = db.query(User).filter(User.wecom_userid == "wx-user-001").all()
        assert len(users) == 1
        assert db.query(Ticket).filter(Ticket.creator_id == users[0].id).count() == 2
    finally:
        db.close()
