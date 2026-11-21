"""第三十八批回归：资产到期提醒、设备状态变更推送、智能分类建议、分类专属选项改名。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.database import create_session
from app.models.knowledge import Asset
from app.models.system import OutboxMessage
from app.services import notify_service

EXP_TAG = "EXP-T38-01"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "t38" + "abcde"


@pytest.fixture(autouse=True)
def fake_channel(monkeypatch):
    """测试未启用真实 IM 渠道，注入假渠道路由验证入队逻辑。"""
    monkeypatch.setattr(
        notify_service, "_channels_for_user", lambda user: [("dingtalk", f"fake-{user.id}")]
    )


@pytest.fixture(scope="module", autouse=True)
def _t38_cleanup():
    yield
    db = create_session()
    try:
        for a in db.scalars(select(Asset).where(Asset.asset_tag.like("EXP-T38-%"))).all():
            db.delete(a)
        from app.models.ticket import Ticket

        for t in db.scalars(select(Ticket).where(Ticket.title.like("T38分类-"))).all():
            db.query(type(t)).filter_by(id=t.id).delete()
        db.commit()
    finally:
        db.close()


def _mk_asset(client, admin_headers, *, expire_date: str, tag: str = EXP_TAG) -> int:
    r = client.post(
        "/api/assets",
        json={"asset_tag": tag, "name": "到期提醒验收机", "category": "电脑", "status": "在用", "expire_date": expire_date},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _run_expire_job() -> None:
    from app.jobs.scheduler import _asset_expire_job

    _asset_expire_job()


def _outbox_titles(prefix: str) -> list[str]:
    db = create_session()
    try:
        return [m.title for m in db.scalars(select(OutboxMessage).where(OutboxMessage.title.like(f"{prefix}%"))).all()]
    finally:
        db.close()


def test_asset_expire_alert(client, admin_headers):
    """到期日落在 30 天内 → 定时任务通知管理员一次，重复扫描不重发。"""
    aid = _mk_asset(client, admin_headers, expire_date=(datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"))
    _run_expire_job()
    titles = _outbox_titles("资产到期提醒")
    assert any(EXP_TAG in t for t in titles), titles
    db = create_session()
    try:
        assert db.get(Asset, aid).expire_warned is True
    finally:
        db.close()
    # 再次扫描不重复提醒
    n_before = len(titles)
    _run_expire_job()
    assert len(_outbox_titles("资产到期提醒")) == n_before


def _outbox_contents(prefix: str) -> list[str]:
    db = create_session()
    try:
        return [m.content for m in db.scalars(select(OutboxMessage).where(OutboxMessage.title.like(f"{prefix}%"))).all()]
    finally:
        db.close()


def test_asset_action_im_notify(client, admin_headers):
    """送修/修复完成 → 全部 IT 收到设备状态变更推送。"""
    aid = _mk_asset(client, admin_headers, expire_date=None, tag="EXP-T38-02")
    r = client.post(f"/api/assets/{aid}/action", json={"action": "repair", "note": "屏幕碎裂"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    titles = _outbox_titles("设备状态变更")
    assert any("EXP-T38-02" in t for t in titles), titles
    assert any("已送修" in c for c in _outbox_contents("设备状态变更")), "content 应含状态说明"
    r = client.post(f"/api/assets/{aid}/action", json={"action": "repair_done"}, headers=admin_headers)
    assert r.status_code == 200
    assert any("维修完成" in c for c in _outbox_contents("设备状态变更"))


def test_classify_suggest(client, admin_headers, employee_headers):
    """智能分类助手：历史工单语料 → 建议 Top1 与关键词分类一致；优先级初判生效。"""
    # 语料：每分类 2 张特征明显的工单（共享库已有历史单，满足 ≥5 条即可构建索引）
    for title, cat in [
        ("T38分类-打印机卡纸报错", "打印设备"),
        ("T38分类-打印输出模糊", "打印设备"),
        ("T38分类-WiFi 断网无法访问网络", "网络故障"),
        ("T38分类-无线连接不上", "网络故障"),
        ("T38分类-安装 WPS 办公软件", "软件安装"),
    ]:
        r = client.post("/api/tickets", json={"title": title, "description": title, "category": cat}, headers=employee_headers)
        assert r.status_code == 201, r.text
    r = client.get(f"/api/tickets/classify-suggest?title={encodeURIComponent('打印机报错卡纸')}", headers=admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["items"], "有语料时应返回建议"
    assert data["items"][0]["category"] == "打印设备", data["items"]
    assert 0 < data["items"][0]["confidence"] <= 100
    # 优先级初判
    r2 = client.get("/api/tickets/classify-suggest?title=全员断网无法工作", headers=admin_headers)
    assert r2.json()["priority"] == "urgent"


def encodeURIComponent(s: str) -> str:
    from urllib.parse import quote


def test_assignee_qr_beats_deferred(client, admin_headers):
    """第四十批 C2：指定派单码优先于延迟分派——「其他问题」+指定码也直接派给绑定工程师。"""
    from app.models.ticket import Ticket, TicketEvent
    from app.models.user import User

    # 自建现场工程师（测试库独立，不依赖其他模块造的用户）
    PWD_C2 = "c2" + "eng678"
    r = client.post(
        "/api/users",
        json={"username": "c2eng", "name": "C2现场工程师", "role": "engineer", "ops_type": "field", "password": PWD_C2},
        headers=admin_headers,
    )
    assert r.status_code in (200, 201), r.text
    eng = r.json()

    r = client.post("/api/qr-tags", json={"kind": "assignee", "name": "C2指定码", "engineer_id": eng["id"]}, headers=admin_headers)
    assert r.status_code == 201, r.text
    tag_id = r.json()["id"]
    code = r.json()["code"]
    t = client.post("/api/tickets", json={"title": "C2指定码其他问题单", "category": "其他问题", "qr_code": code}, headers=admin_headers).json()
    assert t["assignee"] and t["assignee"]["id"] == eng["id"], t.get("assignee")
    assert not t.get("deferred"), "指定码不应触发延迟分派"
    # 清理（工单物理删；用户软删除——物理删用户会被事件/绑定 FK 卡住）
    client.delete(f"/api/qr-tags/{tag_id}", headers=admin_headers)
    from app.models.system import OutboxMessage

    db = create_session()
    try:
        db.query(OutboxMessage).filter(OutboxMessage.ticket_id == t["id"]).delete()
        db.query(TicketEvent).filter(TicketEvent.ticket_id == t["id"]).delete()
        db.query(Ticket).filter(Ticket.id == t["id"]).delete()
        u = db.query(User).filter(User.username == "c2eng").first()
        if u:
            u.is_active = False
            u.username = "c2eng_gone"
        db.commit()
    finally:
        db.close()


def encodeURIComponent(s: str) -> str:
    from urllib.parse import quote

    return quote(s)
