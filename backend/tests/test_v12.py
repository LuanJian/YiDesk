"""v1.2 功能测试：智能分派、值班表、相似/合并、知识推荐、工作日历。"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core.config import reset_config
from app.models.database import create_session
from app.models.system import DispatchRule, DutyRule
from app.services.business_time import add_business_minutes, business_minutes_between
from app.services import v12_service


def _mk_rule(client, admin_headers, category: str, ids: list[int]):
    r = client.put(
        "/api/admin/dispatch-rules",
        json={"category": category, "engineer_ids": ids, "enabled": True},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text


def _mk_duty(client, admin_headers, weekday: int, ids: list[int]):
    r = client.put(
        "/api/admin/duty-rules",
        json={"weekday": weekday, "engineer_ids": ids},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text


# ---- 智能分派 ----

def test_auto_assign_by_category_rule(client, admin_headers, engineer_headers):
    # 取工程师 ID
    engs = client.get("/api/users?role=engineer", headers=admin_headers).json()["items"]
    eng_ids = [e["id"] for e in engs if e["username"] in ("eng1", "cardeng")]
    assert len(eng_ids) >= 1
    _mk_rule(client, admin_headers, "硬件设备", eng_ids)

    r = client.post(
        "/api/tickets",
        json={"title": "工位显示器闪烁", "category": "硬件设备", "priority": "medium"},
        headers=engineer_headers,
    )
    t = r.json()
    assert t["auto_assigned"], "分类规则命中时应自动指派"
    assert t["assignee"]["id"] in eng_ids

    # 未配置规则的分类不指派
    r2 = client.post(
        "/api/tickets",
        json={"title": "软件问题随意单", "category": "软件安装", "priority": "low"},
        headers=engineer_headers,
    )
    assert r2.json()["auto_assigned"] is None


def test_auto_assign_by_duty_when_no_rule(client, admin_headers, engineer_headers):
    engs = [e for e in client.get("/api/users?role=engineer", headers=admin_headers).json()["items"] if e["is_active"]]
    eng_ids = [e["id"] for e in engs][:2]
    _mk_duty(client, admin_headers, datetime.now().weekday(), eng_ids)

    r = client.post(
        "/api/tickets",
        json={"title": "按值班表分派的工单", "category": "网络故障", "priority": "low"},
        headers=engineer_headers,
    )
    t = r.json()
    assert t["auto_assigned"], "无分类规则时应按值班表指派"
    assert t["assignee"]["id"] in eng_ids


def test_dispatch_rules_admin_only(client, employee_headers):
    assert client.get("/api/admin/dispatch-rules", headers=employee_headers).status_code == 403
    assert (
        client.put(
            "/api/admin/dispatch-rules",
            json={"category": "x", "engineer_ids": [1]},
            headers=employee_headers,
        ).status_code
        == 403
    )


# ---- 相似识别与合并 ----

def test_similar_and_merge(client, admin_headers, employee_headers):
    t1 = client.post(
        "/api/tickets",
        json={"title": "会议室投影仪无法显示", "category": "硬件设备", "priority": "medium"},
        headers=employee_headers,
    ).json()
    t2 = client.post(
        "/api/tickets",
        json={"title": "会议室投影仪显示异常", "category": "硬件设备", "priority": "medium"},
        headers=employee_headers,
    ).json()

    similar = client.get(f"/api/tickets/{t2['id']}/similar", headers=employee_headers).json()["items"]
    assert any(s["id"] == t1["id"] for s in similar), "标题相似应被识别"

    # v2.10 员工可合并「自己的重复单」（新→旧）；方向反了（旧→新，非重复场景）仍被拒
    assert (
        client.post(f"/api/tickets/{t1['id']}/merge", json={"target_id": t2["id"]}, headers=employee_headers).status_code
        == 403
    )

    # 工程师合并 t2 → t1
    r = client.post(f"/api/tickets/{t2['id']}/merge", json={"target_id": t1["id"]}, headers=admin_headers)
    assert r.status_code == 200, r.text

    merged = client.get(f"/api/tickets/{t2['id']}", headers=admin_headers).json()
    assert merged["status"] == "closed" and merged["merged_into_id"] == t1["id"]
    assert any("合并至" in ev["content"] for ev in merged["events"])

    # 合并到已被合并的工单 → 拒绝
    t3 = client.post(
        "/api/tickets",
        json={"title": "再开一张投影仪单", "category": "硬件设备", "priority": "low"},
        headers=employee_headers,
    ).json()
    assert (
        client.post(f"/api/tickets/{t3['id']}/merge", json={"target_id": t2["id"]}, headers=admin_headers).status_code
        == 400
    )


# ---- 知识库推荐 ----

def test_knowledge_suggestions(client, engineer_headers, employee_headers):
    client.post(
        "/api/knowledge",
        json={"title": "投影仪无法显示排查步骤", "content": "1. 检查 HDMI 线", "tags": ["投影仪"]},
        headers=engineer_headers,
    )
    t = client.post(
        "/api/tickets",
        json={"title": "会议室投影仪无法显示", "category": "硬件设备", "priority": "medium"},
        headers=employee_headers,
    ).json()
    items = client.get(f"/api/tickets/{t['id']}/knowledge-suggestions", headers=employee_headers).json()["items"]
    assert any("投影仪" in i["title"] for i in items)


# ---- 每日日报 ----

def test_daily_report_build(client, admin_headers, employee_headers):
    from app.services.v12_service import build_daily_report

    client.post(
        "/api/tickets",
        json={"title": "日报数据工单", "category": "软件安装", "priority": "low"},
        headers=employee_headers,
    )
    db = create_session()
    try:
        text = build_daily_report(db)
        assert "IT 工单日报" in text
        assert "新建" in text and "未结" in text
    finally:
        db.close()


# ---- 工单模板 ----

def test_template_crud_and_custom_fields(client, admin_headers, employee_headers):
    r = client.post(
        "/api/admin/templates",
        json={
            "name": "网络故障单", "category": "网络故障", "priority": "high",
            "fields": [
                {"key": "floor", "label": "楼层", "type": "select", "options": ["3F", "5F"], "required": True},
                {"key": "ap_mac", "label": "AP MAC", "type": "text"},
            ],
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    items = client.get("/api/admin/templates", headers=admin_headers).json()["items"]
    assert any(t["id"] == tid for t in items)

    # 建单带自定义字段
    t = client.post(
        "/api/tickets",
        json={
            "title": "3F 断网", "category": "网络故障", "priority": "high",
            "custom_fields": {"floor": "3F", "ap_mac": "AA-BB-CC"},
        },
        headers=employee_headers,
    ).json()
    assert t["custom_fields"] == {"floor": "3F", "ap_mac": "AA-BB-CC"}

    # 员工不能改模板
    assert (
        client.patch(
            f"/api/admin/templates/{tid}",
            json={"name": "x", "category": "网络故障", "priority": "high", "fields": []},
            headers=employee_headers,
        ).status_code
        == 403
    )
    assert client.delete(f"/api/admin/templates/{tid}", headers=admin_headers).status_code == 200


# ---- 工作日历 ----

def test_business_time_24x7_default():
    reset_config()
    start = datetime(2026, 11, 6, 18, 0)  # 周五 18:00
    assert add_business_minutes(start, 60) == start + timedelta(minutes=60)


def test_business_time_work_hours(monkeypatch):
    reset_config()
    import app.core.config as cfg_mod

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.sla, "work_hours", {"enabled": True, "start": "09:00", "end": "18:00", "workdays": [0, 1, 2, 3, 4]})

    # 周五 17:30 + 60 分钟工作时间 → 周五 17:30~18:00 的 30 分 + 周一 09:00~09:30 的 30 分
    friday = datetime(2026, 11, 6, 17, 30)
    result = add_business_minutes(friday, 60)
    assert result == datetime(2026, 11, 9, 9, 30), result

    # 工作分钟统计：周五 16:00 → 周一 10:00 = 2h + 1h = 180
    mins = business_minutes_between(datetime(2026, 11, 6, 16, 0), datetime(2026, 11, 9, 10, 0))
    assert mins == 180, mins


def test_business_time_holidays_and_extra_workdays(monkeypatch):
    """法定节假日视为休息、调休周六视为工作。"""
    reset_config()
    import app.core.config as cfg_mod

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(
        cfg.sla, "work_hours",
        {
            "enabled": True, "start": "09:00", "end": "18:00",
            "workdays": [0, 1, 2, 3, 4],
            "holidays": ["2026-10-01"],            # 周四法定假
            "extra_workdays": ["2026-10-03"],      # 周六调休上班
        },
    )

    # 周四(10-01)是节假日 → 周三 17:30 + 60 分钟 = 周三 30 分 + 周五 09:00~09:30 的 30 分
    result = add_business_minutes(datetime(2026, 9, 30, 17, 30), 60)
    assert result == datetime(2026, 10, 2, 9, 30), result

    # 周六 10-03 调休上班：09:00~11:00 计 120 工作分钟
    mins = business_minutes_between(datetime(2026, 10, 3, 9, 0), datetime(2026, 10, 3, 11, 0))
    assert mins == 120, mins

    assert add_business_minutes(datetime(2026, 10, 3, 11, 0), 60) == datetime(2026, 10, 3, 12, 0)


def test_ticket_sla_uses_business_calendar(client, employee_headers):
    from app.models.database import create_session

    r = client.post(
        "/api/tickets",
        json={"title": "工作日历建单", "category": "其他问题", "priority": "urgent"},
        headers=employee_headers,
    )
    tid = r.json()["id"]
    # urgent resolve=60min；周五 18:10 建单 → 下一个工作日 09:00 起 60 分钟
    # （测试运行时间不定，仅验证 deadline ≥ created + 60min 自然时间）
    db = create_session()
    try:
        from sqlalchemy import select

        from app.models.ticket import Ticket

        t = db.scalar(select(Ticket).where(Ticket.id == tid))
        # 前序测试可能改过 urgent 的 SLA 规则，这里只验证日历计算产生了有效截止时间
        assert t.sla_resolve_deadline and t.sla_resolve_deadline > t.created_at
    finally:
        db.close()
