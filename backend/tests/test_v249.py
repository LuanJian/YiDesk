"""第四十九批回归：手动巡检端点（枚举校验 / JSON 防重复）+ 登录日志 reason_stats 归类统计。

测试库独立（conftest 注入临时 config），所需用户自建；结束时按依赖序清理。
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models.database import create_session
from app.models.login_log import LoginLog
from app.models.meeting import MeetingRoom
from app.models.system import OutboxMessage
from app.models.ticket import Ticket, TicketEvent

INSPECT_TYPES = ("定期巡检", "手动报修")


@pytest.fixture(scope="module", autouse=True)
def _t49_env():
    """自建会议室与登录日志（共享测试库，前缀隔离），结束后清理。"""
    db = create_session()
    room_id: int | None = None
    try:
        room = MeetingRoom(
            name="T49 巡检测试会议室",
            location="测试楼 4 层",
            capacity=8,
            equipment_desc="投屏/白板",
            equipment_list=json.dumps([{"name": "翻页笔", "count": 1, "status": "正常"}], ensure_ascii=False),
        )
        db.add(room)
        db.commit()
        db.refresh(room)
        room_id = room.id
        # 造登录日志：成功/密码错误/门禁未通过/冻结
        db.add_all([
            LoginLog(username="t49u", name="T49 用户", ip="10.0.0.49", success=True, reason=""),
            LoginLog(username="t49u", name="T49 用户", ip="10.0.0.49", success=False, reason="用户名或密码错误"),
            LoginLog(username="t49u", name="T49 用户", ip="10.0.0.49", success=False, reason="安全密钥校验未通过：该账号已启用安全密钥，请通过管理员分发的准入链接访问后台"),
            LoginLog(username="t49u", name="T49 日志", ip="10.0.0.49", success=False, reason="账户已冻结或停用"),
        ])
        db.commit()
        yield room_id
    finally:
        # 清理：巡检工单（含事件/通知）→ 登录日志 → 会议室
        tickets = list(db.scalars(select(Ticket).where(Ticket.title.like("会议室巡检：T49%"))).all())
        for t in tickets:
            db.query(TicketEvent).filter(TicketEvent.ticket_id == t.id).delete()
            db.query(OutboxMessage).filter(OutboxMessage.ticket_id == t.id).delete()
            db.query(type(t)).filter_by(id=t.id).delete()
        db.query(LoginLog).filter(LoginLog.username == "t49u").delete()
        if room_id:
            r = db.get(MeetingRoom, room_id)
            if r:
                db.delete(r)
        db.commit()
        db.close()


def _login(client, admin_headers):
    """用 admin 会话直接调用（conftest 已含 admin 账号）。"""
    return client, admin_headers


def test_inspect_rejects_invalid_type(client, admin_headers):
    r = client.post(
        "/api/meetings/rooms/999999/inspect",
        json={"inspect_type": "自由文本"},
        headers=admin_headers,
    )
    assert r.status_code == 400
    assert "巡检类型" in r.json()["detail"]


def test_inspect_rejects_unknown_room(client, admin_headers):
    r = client.post(
        "/api/meetings/rooms/999999/inspect",
        json={"inspect_type": "定期巡检"},
        headers=admin_headers,
    )
    assert r.status_code == 404


def test_inspect_creates_and_dedupes(client, admin_headers, _t49_env):
    room_id = _t49_env
    # 1) 正常创建（定期巡检）
    r = client.post(
        f"/api/meetings/rooms/{room_id}/inspect",
        json={"inspect_type": "定期巡检"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["inspect_type"] == "定期巡检"
    fields = json.loads(data["ticket"]["custom_fields"]) if isinstance(data["ticket"]["custom_fields"], str) else data["ticket"]["custom_fields"]
    assert fields["巡检类型"] == "定期巡检"
    assert fields["meeting_room_id"] == room_id
    no = data["ticket"]["no"]

    # 2) 重复创建 → JSON 防重复拦截（改名也不影响：按 meeting_room_id 匹配）
    r2 = client.post(
        f"/api/meetings/rooms/{room_id}/inspect",
        json={"inspect_type": "手动报修"},
        headers=admin_headers,
    )
    assert r2.status_code == 400
    assert no in r2.json()["detail"]


def test_login_logs_reason_stats(client, admin_headers):
    """登录日志按 原因+结果 聚合返回；前端归类映射可正确分组。"""
    r = client.get("/api/users/login-logs?page_size=50", headers=admin_headers)
    assert r.status_code == 200
    stats = r.json().get("reason_stats")
    assert stats is not None, "响应应包含 reason_stats 字段"
    pairs = {(x["reason"], x["success"]) for x in stats}
    assert ("", True) in pairs, "应含成功记录聚合"
    assert ("用户名或密码错误", False) in pairs
    assert any("安全密钥" in x["reason"] and not x["success"] for x in stats)
    assert any("冻结" in x["reason"] and not x["success"] for x in stats)
