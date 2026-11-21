"""SLA 扫描测试：构造超期工单 → 断言预警/升级通知入队且只触发一次。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.database import create_session
from app.models.system import OutboxMessage
from app.models.ticket import Ticket
from app.models.user import utcnow
from app.services import notify_service, sla_service


@pytest.fixture(autouse=True)
def fake_channel(monkeypatch):
    """测试配置未启用真实 IM 渠道，注入假的渠道路由以便验证入队逻辑。"""
    monkeypatch.setattr(
        notify_service, "_channels_for_user", lambda user: [("dingtalk", f"fake-{user.id}")]
    )


def _make_overdue_ticket(client, employee_headers, priority: str = "urgent") -> int:
    r = client.post(
        "/api/tickets",
        json={"title": "核心交换机故障", "description": "全员断网", "category": "网络故障", "priority": priority},
        headers=employee_headers,
    )
    assert r.status_code == 201
    tid = r.json()["id"]
    db = create_session()
    try:
        t = db.get(Ticket, tid)
        now = utcnow()
        t.sla_response_deadline = now - timedelta(minutes=30)
        t.sla_resolve_deadline = now - timedelta(minutes=5)
        t.created_at = now - timedelta(minutes=60)
        db.commit()
    finally:
        db.close()
    return tid


def _outbox_titles(ticket_id: int | None = None) -> list[str]:
    db = create_session()
    try:
        stmt = select(OutboxMessage)
        if ticket_id is not None:
            stmt = stmt.where(OutboxMessage.ticket_id == ticket_id)
        return [m.title for m in db.scalars(stmt).all()]
    finally:
        db.close()


def test_sla_scan_warn_and_escalate_once(client, employee_headers):
    tid = _make_overdue_ticket(client, employee_headers)

    logs = sla_service.scan(create_session())
    titles = _outbox_titles(tid)
    assert any("响应预警" in t for t in titles), logs
    assert any("响应超时升级" in t for t in titles), logs
    assert any("解决超时" in t for t in titles), logs

    db = create_session()
    try:
        t = db.get(Ticket, tid)
        assert t.sla_response_warned and t.sla_escalated and t.sla_resolve_warned
    finally:
        db.close()

    # 第二次扫描不重复催办
    before = len(_outbox_titles(tid))
    sla_service.scan(create_session())
    assert len(_outbox_titles(tid)) == before


def test_sla_scan_no_false_alarm_for_fresh_ticket(client, employee_headers):
    r = client.post(
        "/api/tickets",
        json={"title": "新买的显示器色差", "category": "硬件设备", "priority": "low"},
        headers=employee_headers,
    )
    tid = r.json()["id"]
    before = len(_outbox_titles(tid))
    logs = sla_service.scan(create_session())
    # 新工单不应触发任何 SLA 动作（建单通知不计入）
    assert logs == []
    assert len(_outbox_titles(tid)) == before
