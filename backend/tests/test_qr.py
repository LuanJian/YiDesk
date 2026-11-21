"""二维码报修测试：标签 CRUD、三种码建单、扫码页位次、粘性派单、PNG。

工程师与工单分类一律用专用值（qr 前缀用户名、QR_* 分类），并在每个测试后
清理专用分类的工单与派单规则，避免污染共享会话库（test_qr 按字母序先于
test_v11/test_v12 执行）。
"""
from __future__ import annotations

import pytest

# 专用分类（仅本文件使用，清理夹具据此清扫）
CAT_SW = "QR_软件"
CAT_GEN = "QR_通用"

CLEANUP_CATS = [CAT_SW, CAT_GEN]


@pytest.fixture(autouse=True)
def _qr_cleanup():
    """每个测试后清掉专用分类的工单与派单规则，恢复会话库原状。

    merged_into_id 自引用需先解除再删，否则先删目标单时 FK 失败。
    """
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.system import DispatchRule
    from app.models.ticket import Ticket

    db = create_session()
    try:
        tickets = db.scalars(select(Ticket).where(Ticket.category.in_(CLEANUP_CATS))).all()
        for t in tickets:
            t.merged_into_id = None
        db.commit()
        for t in tickets:
            db.delete(t)
        for r in db.scalars(select(DispatchRule).where(DispatchRule.category.in_(CLEANUP_CATS))).all():
            db.delete(r)
        db.commit()
    finally:
        db.close()


def _mk_engineer(client, admin_headers, username: str, name: str) -> int:
    r = client.post(
        "/api/users",
        json={"username": username, "name": name, "role": "engineer", "password": "eng12345"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mk_asset(client, admin_headers, suffix: str, **kw) -> dict:
    r = client.post(
        "/api/assets",
        json={
            "asset_tag": f"PRN-{suffix}",
            "name": kw.get("name", "打印机"),
            "ip_address": kw.get("ip", "192.168.1.66"),
            "model": kw.get("model", "惠普 P1108"),
            "location": kw.get("location", "3 层"),
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _mk_tag(client, headers, **kw) -> dict:
    r = client.post("/api/qr-tags", json=kw, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---- 标签 CRUD 与权限 ----

def test_qr_tags_staff_only(client, admin_headers, employee_headers):
    assert client.get("/api/qr-tags", headers=employee_headers).status_code == 403
    r = client.post("/api/qr-tags", json={"name": "3 层工位", "kind": "location", "location": "3 层"}, headers=employee_headers)
    assert r.status_code == 403


def test_qr_tag_crud_and_png(client, admin_headers):
    tag = _mk_tag(client, admin_headers, name="3 层工位", kind="location", location="3 层 A 区 07 工位")
    assert tag["code"].startswith("QR-")
    assert tag["kind_label"] == "位置码"

    items = client.get("/api/qr-tags", headers=admin_headers).json()["items"]
    assert any(i["id"] == tag["id"] for i in items)

    # 二维码 PNG（可打印）
    r = client.get(f"/api/qr-tags/{tag['id']}/qr.png", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:4] == b"\x89PNG"

    # 改绑为设备码
    asset = _mk_asset(client, admin_headers, "07")
    r = client.patch(
        f"/api/qr-tags/{tag['id']}",
        json={"name": "3 层", "kind": "device", "asset_id": asset["id"], "category": CAT_GEN},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "device"
    assert r.json()["asset"]["ip_address"] == "192.168.1.66"

    # 校验：设备码无资产 400；非设备码带资产 400
    assert client.post("/api/qr-tags", json={"name": "坏设备码", "kind": "device"}, headers=admin_headers).status_code == 400
    assert client.post(
        "/api/qr-tags", json={"name": "位置码带资产", "kind": "location", "asset_id": asset["id"]}, headers=admin_headers
    ).status_code == 400

    client.delete(f"/api/qr-tags/{tag['id']}", headers=admin_headers)
    assert client.get(f"/api/qr/{tag['code']}", headers=admin_headers).status_code == 404  # 删除后扫码无效


# ---- 三种码建单 ----

def test_create_with_location_tag(client, admin_headers, employee_headers):
    tag = _mk_tag(client, admin_headers, name="5 层工位", kind="location", location="5 层 B 区 12 工位", category=CAT_GEN)
    r = client.post(
        "/api/tickets",
        json={"title": "空调不制冷", "description": "下午 3 点开始不凉", "qr_code": tag["code"]},
        headers=employee_headers,
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["qr_code"] == tag["code"]
    assert t["category"] == CAT_GEN  # 标签默认分类
    assert "位置：5 层 B 区 12 工位" in t["description"]
    assert t["custom_fields"]["qr_code"] == tag["code"]
    assert t["custom_fields"]["location"] == "5 层 B 区 12 工位"


def test_create_with_device_tag(client, admin_headers, employee_headers):
    asset = _mk_asset(client, admin_headers, "02")
    tag = _mk_tag(
        client, admin_headers,
        name="3 层打印机", kind="device", asset_id=asset["id"], category=CAT_GEN, location="3 层",
    )
    r = client.post(
        "/api/tickets",
        json={"title": "打印机卡纸", "description": "双面卡纸", "qr_code": tag["code"]},
        headers=employee_headers,
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["asset_id"] == asset["id"]
    assert t["category"] == CAT_GEN
    # v2.11 设备信息不再拼进描述（详情页由独立单元格展示），custom_fields.device 保留完整信息
    assert t["description"] == "双面卡纸"
    cf = t["custom_fields"]["device"]
    assert cf["ip"] == "192.168.1.66" and cf["model"] == "惠普 P1108" and cf["name"] == "打印机"
    assert t["custom_fields"]["device"]["asset_tag"] == asset["asset_tag"]

    # 无效 code 拒绝
    assert client.post(
        "/api/tickets", json={"title": "坏码建单", "qr_code": "QR-XXXXX"}, headers=employee_headers
    ).status_code == 400


def test_create_with_assignee_tag(client, admin_headers, employee_headers):
    eng = _mk_engineer(client, admin_headers, "qrassign", "指定派单工程师")
    tag = _mk_tag(client, admin_headers, name="网段专线", kind="assignee", engineer_id=eng, category=CAT_GEN)

    r = client.post("/api/tickets", json={"title": "网线接口松动", "qr_code": tag["code"]}, headers=employee_headers)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["assignee"] and t["assignee"]["id"] == eng
    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()
    assert any("扫码指定派单" in e["content"] for e in detail["events"])

    # 指定对象停用 → 回退自动分派
    client.patch(f"/api/users/{eng}", json={"is_active": False}, headers=admin_headers)
    try:
        r2 = client.post("/api/tickets", json={"title": "停用后扫码建单", "qr_code": tag["code"]}, headers=employee_headers)
        assert r2.status_code == 201, r2.text
        detail2 = client.get(f"/api/tickets/{r2.json()['id']}", headers=admin_headers).json()
        assert any("已回退自动分派" in e["content"] for e in detail2["events"])
    finally:
        client.patch(f"/api/users/{eng}", json={"is_active": True}, headers=admin_headers)


# ---- 扫码页与位次 ----

def test_qr_code_page_and_queue(client, admin_headers, employee_headers):
    eng = _mk_engineer(client, admin_headers, "qrqueue", "排队专用工程师")
    tag = _mk_tag(client, admin_headers, name="排队工程师码", kind="assignee", engineer_id=eng, category=CAT_GEN)

    for title in ("排队第 1 单", "排队第 2 单"):
        r = client.post("/api/tickets", json={"title": title, "qr_code": tag["code"]}, headers=employee_headers)
        assert r.status_code == 201, r.text

    data = client.get(f"/api/qr/{tag['code']}", headers=employee_headers).json()
    assert data["forced_engineer"]["id"] == eng
    opens = data["open_tickets"]
    assert len(opens) == 2  # 该专用工程师名下只有这 2 张
    assert all(o["assignee"]["id"] == eng for o in opens)
    assert opens[0]["queue_ahead"] == 0
    assert opens[1]["queue_ahead"] == 1  # 第 2 张前还有 1 张

    # 无效 code
    assert client.get("/api/qr/QR-NOPE", headers=employee_headers).status_code == 404


# ---- 粘性派单（同分类归同一人 + 超载回退） ----

def test_sticky_same_category_dispatch(client, admin_headers, employee_headers):
    from app.core.config import get_config

    cfg = get_config().dispatch
    e1 = _mk_engineer(client, admin_headers, "qrst1", "粘性甲")
    e2 = _mk_engineer(client, admin_headers, "qrst2", "粘性乙")
    r = client.put(
        "/api/admin/dispatch-rules",
        json={"category": CAT_SW, "engineer_ids": [e1, e2], "enabled": True},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text

    sticky = cfg.sticky_same_category
    cfg.sticky_same_category = True
    try:
        # 第一张：无同类种子 → 轮询（落点 e1/e2 之一）
        t1 = client.post("/api/tickets", json={"title": "软件 A 卡顿", "category": CAT_SW}, headers=employee_headers).json()
        first = t1["assignee"]["id"]
        assert first in (e1, e2)
        # 第二张（同类）：粘性继续给第一张的处理人
        t2 = client.post("/api/tickets", json={"title": "软件 B 打不开", "category": CAT_SW}, headers=employee_headers).json()
        assert t2["assignee"]["id"] == first, "同类工单应粘性指派给同一工程师"

        # 开关关闭 → 纯轮询：连续两张槽位交替，两人各派一张
        cfg.sticky_same_category = False
        picks = [
            client.post("/api/tickets", json={"title": f"软件 C{i} 闪退", "category": CAT_SW}, headers=employee_headers).json()["assignee"]["id"]
            for i in range(2)
        ]
        assert set(picks) == {e1, e2}
    finally:
        cfg.sticky_same_category = sticky


def test_sticky_overload_fallback(client, admin_headers, employee_headers):
    """粘性人选超载（未结 > dispatch.max_open）时回退轮询，不粘。"""
    from app.core.config import get_config
    from app.models.database import create_session
    from app.models.ticket import STATUS_PROCESSING, Ticket
    from app.models.user import utcnow

    cfg = get_config().dispatch
    e1 = _mk_engineer(client, admin_headers, "qrload1", "负载甲")
    e2 = _mk_engineer(client, admin_headers, "qrload2", "负载乙")
    r = client.put(
        "/api/admin/dispatch-rules",
        json={"category": CAT_SW, "engineer_ids": [e1, e2], "enabled": True},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text

    db = create_session()
    try:
        # 给 e1 造 3 张 CAT_SW 处理中单作为粘性种子
        for i in range(3):
            db.add(Ticket(
                no=f"GD-MANUAL-{i:02d}", title=f"负载底单 {i}", category=CAT_SW,
                status=STATUS_PROCESSING, creator_id=e1, assignee_id=e1,
                created_at=utcnow(), updated_at=utcnow(),
            ))
        db.commit()

        sticky, max_open = cfg.sticky_same_category, cfg.max_open
        cfg.sticky_same_category = True
        cfg.max_open = 8
        try:
            created = [
                client.post("/api/tickets", json={"title": f"超载对照 {i}", "category": CAT_SW}, headers=employee_headers).json()
                for i in range(2)
            ]
            assert all(t["assignee"]["id"] == e1 for t in created), "未超载时粘性应持续归 e1"

            cfg.max_open = 2  # e1 未结 5 > 2 → 粘性失效，回退轮询
            picks = [
                client.post("/api/tickets", json={"title": f"超载单 {i}", "category": CAT_SW}, headers=employee_headers).json()["assignee"]["id"]
                for i in range(2)
            ]
            assert set(picks) == {e1, e2}, "超载后粘性失效，应回退轮询"
        finally:
            cfg.sticky_same_category = sticky
            cfg.max_open = max_open
    finally:
        db.close()


# ---- v2.11 匿名扫码提交 ----

def test_anonymous_scan_page_and_submit(client, admin_headers):
    """未登录扫码：落地页匿名可访问、建单记到匿名用户名下；无码匿名建单 401；匿名合并成功。"""
    tag = _mk_tag(client, admin_headers, name="前台打印机", kind="location", location="1 层前台", category=CAT_GEN)

    # 扫码落地页匿名可访问，分类随扫码数据下发（匿名拿不到 admin 接口）
    r = client.get(f"/api/qr/{tag['code']}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["authenticated"] is False
    assert d["categories"]
    assert d["open_tickets"] == []

    # 匿名建单（带 qr_code）→ 201，创建人为系统匿名用户
    r = client.post("/api/tickets", json={"title": "打印机卡纸", "category": CAT_GEN, "qr_code": tag["code"]})
    assert r.status_code == 201, r.text
    t1 = r.json()
    assert t1["creator"]["name"] == "匿名用户"
    anon_tid = t1["id"]

    # 无码匿名建单 → 401（匿名仅限扫码入口）
    assert client.post("/api/tickets", json={"title": "直接建单", "category": CAT_GEN}).status_code == 401

    # 扫码页展示该码全部未结工单（匿名无身份过滤），并带提交人
    d = client.get(f"/api/qr/{tag['code']}").json()
    assert [x["id"] for x in d["open_tickets"]] == [anon_tid]
    assert d["open_tickets"][0]["creator"] == "匿名用户"

    # 15 分钟内重复提交 → recent_ticket 提示 → 匿名合并到原单成功
    r2 = client.post("/api/tickets", json={"title": "还是卡纸", "category": CAT_GEN, "qr_code": tag["code"]})
    assert r2.status_code == 201, r2.text
    t2 = r2.json()
    assert t2["recent_ticket"]["id"] == anon_tid
    r = client.post(f"/api/tickets/{t2['id']}/merge", json={"target_id": anon_tid})
    assert r.status_code == 200, r.text

    # 已合并关闭的源单不再出现在未结列表
    d = client.get(f"/api/qr/{tag['code']}").json()
    assert [x["id"] for x in d["open_tickets"]] == [anon_tid]


def test_device_code_shows_all_tickets(client, admin_headers, employee_headers):
    """设备码：所有人的未结工单对扫码者全员可见（避免同一问题多名员工重复提交）。"""
    asset = _mk_asset(client, admin_headers, "V21A")
    tag = _mk_tag(client, admin_headers, name="会议室投影", kind="device", asset_id=asset["id"], category=CAT_GEN)

    r1 = client.post("/api/tickets", json={"title": "投影无信号", "category": CAT_GEN, "qr_code": tag["code"]}, headers=employee_headers)
    assert r1.status_code == 201, r1.text
    emp_tid = r1.json()["id"]
    r2 = client.post("/api/tickets", json={"title": "投影打不开", "category": CAT_GEN, "qr_code": tag["code"]}, headers=admin_headers)
    assert r2.status_code == 201, r2.text
    admin_tid = r2.json()["id"]

    # 员工扫码 → 能看到管理员提交的那一单（include_all）
    d = client.get(f"/api/qr/{tag['code']}", headers=employee_headers).json()
    ids = {x["id"] for x in d["open_tickets"]}
    assert {emp_tid, admin_tid} <= ids
    assert all(x["creator"] for x in d["open_tickets"])  # 多人提交时展示提交人

    # 匿名同样全员可见
    d = client.get(f"/api/qr/{tag['code']}").json()
    ids = {x["id"] for x in d["open_tickets"]}
    assert {emp_tid, admin_tid} <= ids

    # 位置码（非设备码）：登录用户只看自己的
    loc = _mk_tag(client, admin_headers, name="位置对照码", kind="location", location="1层", category=CAT_GEN)
    r3 = client.post("/api/tickets", json={"title": "位置码对照单", "category": CAT_GEN, "qr_code": loc["code"]}, headers=admin_headers)
    assert r3.status_code == 201, r3.text
    d = client.get(f"/api/qr/{loc['code']}", headers=employee_headers).json()
    assert d["open_tickets"] == []  # emp 看不到 admin 在位置码下的单
