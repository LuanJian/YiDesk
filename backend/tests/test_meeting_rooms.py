"""会议室预约管理测试（v2.12）：会议室 CRUD、预约冲突校验、取消权限、检查留痕、会议室码扫码数据。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest


def _join(base: str, suffix: str | int) -> str:
    """拼接 API 路径（测试辅助）。"""
    return f"{base}/{suffix}"


def _future_slot() -> tuple[str, str, str]:
    """返回 (date, start, end)：约 1 小时后的整点时段；时段或「紧接其后一小时」会跨午夜（22 点后）→ 明天上午。"""
    from datetime import datetime

    now = datetime.now()
    start = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    if start.hour >= 22 or start.date() != now.date():
        d = (now + timedelta(days=1)).date()
        return d.isoformat(), "09:00", "10:00"
    return start.date().isoformat(), start.strftime("%H:%M"), (start + timedelta(hours=1)).strftime("%H:%M")


def _hm(base: str, offset_minutes: int) -> str:
    """HH:MM 加减分钟（跨午夜回绕，避免夜间时段算出「25:xx」非法格式）。"""
    h, m = (int(x) for x in base.split(":"))
    total = (h * 60 + m + offset_minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


@pytest.fixture(scope="module", autouse=True)
def _mt_users(client, admin_headers):
    """创建会议测试专用员工（模块级，结束后软删除）。"""
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.user import User

    db = create_session()
    try:
        r = client.post(
            "/api/users",
            json={"username": "mtemp", "name": "会议员工", "role": "employee", "password": "mt123456", "department": "业务部"},
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text
        yield {"emp_id": r.json()["id"]}
        for u in db.scalars(select(User).where(User.username.like("mt%"))).all():
            u.username = f"_disabled_{u.id}_{u.username}"
            u.is_active = False
        db.commit()
    finally:
        db.close()


def _emp_login(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "mtemp", "password": "mt123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def _mt_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.meeting import MeetingBooking, MeetingRoom, RoomInspection
    from app.models.qr import QrTag

    db = create_session()
    try:
        # 分阶段删除并各自 commit：跨表 FK（无 relationship）在同一次 flush 里
        # 的删除顺序不可靠，必须先删引用方、提交后再删被引用方
        for ins in db.scalars(select(RoomInspection)).all():
            db.delete(ins)
        db.commit()
        for b in db.scalars(select(MeetingBooking)).all():
            db.delete(b)
        db.commit()
        for t in db.scalars(select(QrTag).where(QrTag.kind == "room")).all():
            db.delete(t)
        db.commit()
        for r in db.scalars(select(MeetingRoom)).all():
            db.delete(r)
        db.commit()
        from app.models.knowledge import Asset

        for a in db.scalars(select(Asset).where(Asset.asset_tag.like("MT-%"))).all():
            db.delete(a)
        db.commit()
    finally:
        db.close()


def _mk_room(client, admin_headers, name="大会议室", **kw) -> dict:
    body = {"name": name, "location": "3F", "capacity": 12, "equipment_desc": "投屏：遥控器选 HDMI1"}
    body.update(kw)
    r = client.post("/api/meetings/rooms", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_room_crud_admin_only(client, admin_headers, employee_headers):
    # 员工无权管理会议室
    assert client.post("/api/meetings/rooms", json={"name": "x"}, headers=employee_headers).status_code == 403
    room = _mk_room(client, admin_headers)
    assert room["capacity"] == 12 and room["enabled"] is True

    items = client.get("/api/meetings/rooms", headers=admin_headers).json()["items"]
    assert any(r["id"] == room["id"] for r in items)

    upd = {"name": "大会议室", "location": "5F", "capacity": 20, "equipment_desc": "更新说明",
           "under_maintenance": True, "maintenance_notice": "投影仪维修中，预计周五恢复"}
    r = client.patch(_join("/api/meetings/rooms", room["id"]), json=upd, headers=admin_headers)
    assert r.status_code == 200 and r.json()["under_maintenance"] is True and r.json()["capacity"] == 20

    # 删除：无未来预约时可删
    assert client.delete(_join("/api/meetings/rooms", room["id"]), headers=admin_headers).status_code == 200


def test_room_delete_blocked_with_bookings(client, admin_headers):
    room = _mk_room(client, admin_headers, "删除保护室")
    emp = _emp_login(client)
    d, s, e = _future_slot()
    body = {"room_id": room["id"], "date": d, "start_time": s, "end_time": e, "title": "周会"}
    r = client.post("/api/meetings/bookings", json=body, headers=emp)
    assert r.status_code == 201, r.text
    r = client.delete(_join("/api/meetings/rooms", room["id"]), headers=admin_headers)
    assert r.status_code == 400
    # 取消预约后可删
    bid = client.get(f"/api/meetings/bookings?room_id={room['id']}", headers=admin_headers).json()["items"][0]["id"]
    client.delete(_join("/api/meetings/bookings", bid), headers=admin_headers)
    assert client.delete(_join("/api/meetings/rooms", room["id"]), headers=admin_headers).status_code == 200


def test_booking_and_conflict(client, admin_headers, employee_headers):
    room = _mk_room(client, admin_headers, "冲突测试室")
    emp = _emp_login(client)
    d, s, e = _future_slot()
    rid = room["id"]

    r = client.post("/api/meetings/bookings", json={"room_id": rid, "date": d, "start_time": s, "end_time": e, "title": "项目例会"}, headers=emp)
    assert r.status_code == 201, r.text
    assert r.json()["booker"]["name"] == "会议员工"

    # 重叠冲突：完全重叠 / 前半 / 后半（起点都 >= 原单起点，确保未开始）
    for off_s, off_e in ((0, 60), (0, 30), (30, 90)):
        body = {"room_id": rid, "date": d, "start_time": _hm(s, off_s), "end_time": _hm(s, off_e), "title": "冲突"}
        r = client.post("/api/meetings/bookings", json=body, headers=employee_headers)
        assert r.status_code == 400, r.text
        assert "预约冲突" in r.json()["detail"]

    # 相邻时段不冲突（紧接其后一小时）
    body = {"room_id": rid, "date": d, "start_time": e, "end_time": _hm(e, 60), "title": "紧接"}
    r = client.post("/api/meetings/bookings", json=body, headers=employee_headers)
    assert r.status_code == 201, r.text

    # 非法参数：时间格式 / 起止颠倒 / 过去日期
    bad_time = {"room_id": rid, "date": d, "start_time": "9点", "end_time": e}
    assert client.post("/api/meetings/bookings", json=bad_time, headers=emp).status_code == 400
    reversed_time = {"room_id": rid, "date": d, "start_time": _hm(s, 120), "end_time": s}
    assert client.post("/api/meetings/bookings", json=reversed_time, headers=emp).status_code == 400
    past = {"room_id": rid, "date": "2020-01-01", "start_time": "10:00", "end_time": "11:00"}
    assert client.post("/api/meetings/bookings", json=past, headers=emp).status_code == 400

    # 取消权限：他人不可取消、本人可、管理员可
    bids = client.get(f"/api/meetings/bookings?room_id={rid}", headers=admin_headers).json()["items"]
    first, second = bids[0], bids[1]
    assert client.delete(_join("/api/meetings/bookings", first["id"]), headers=employee_headers).status_code == 403  # 非本人
    assert client.delete(_join("/api/meetings/bookings", first["id"]), headers=emp).status_code == 200  # 本人
    assert client.delete(_join("/api/meetings/bookings", second["id"]), headers=admin_headers).status_code == 200  # 管理员
    # 取消后时段释放，可重新预约
    body = {"room_id": rid, "date": d, "start_time": s, "end_time": e, "title": "复用"}
    r = client.post("/api/meetings/bookings", json=body, headers=emp)
    assert r.status_code == 201, r.text


def test_maintenance_blocks_booking(client, admin_headers, employee_headers):
    room = _mk_room(client, admin_headers, "维修会议室", under_maintenance=True, maintenance_notice="电视维修中")
    emp = _emp_login(client)
    d, s, e = _future_slot()
    body = {"room_id": room["id"], "date": d, "start_time": s, "end_time": e}
    r = client.post("/api/meetings/bookings", json=body, headers=emp)
    assert r.status_code == 400 and "维修" in r.json()["detail"]


def test_end_booking_early(client, admin_headers, employee_headers):
    """v2.12 提前结束：进行中的预约可把结束时间改为当前时刻释放会议室；仅预约人/管理员。"""
    room = _mk_room(client, admin_headers, "提前结束测试室")
    emp = _emp_login(client)
    today = date.today().isoformat()
    # 造一条「进行中」预约：开始 30 分钟前、结束 30 分钟后
    from datetime import timedelta

    from sqlalchemy import select as _select

    from app.models.database import create_session
    from app.models.meeting import MeetingBooking
    from app.models.user import utcnow

    slot = _future_slot()
    body = {"room_id": room["id"], "date": slot[0], "start_time": slot[1], "end_time": slot[2], "title": "全天会"}
    r = client.post("/api/meetings/bookings", json=body, headers=emp)
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    db = create_session()
    try:
        # 用本地时间（服务器按 Asia/Shanghai 解释 date/time）构造「进行中」时段
        from datetime import datetime as _dt

        b = db.get(MeetingBooking, bid)
        b.date = date.today()
        b.start_time = (_dt.now() - timedelta(minutes=30)).strftime("%H:%M")
        # 跨午夜保护：结束时刻若跨日则用 23:59（保持「进行中」且 end > start）
        end_dt = _dt.now() + timedelta(minutes=30)
        b.end_time = end_dt.strftime("%H:%M") if end_dt.date() == date.today() else "23:59"
        db.commit()
    finally:
        db.close()
    # 非预约人（其他员工）不能提前结束
    r = client.post(_join("/api/meetings/bookings", bid) + "/end", headers=employee_headers)
    assert r.status_code == 403
    # 预约人提前结束 → end_time 变为当前时刻，且早于原结束时间
    r = client.post(_join("/api/meetings/bookings", bid) + "/end", headers=emp)
    assert r.status_code == 200, r.text
    assert r.json()["end_time"] < "23:59"
    # 再次结束 → 已不在进行中，400
    r = client.post(_join("/api/meetings/bookings", bid) + "/end", headers=emp)
    assert r.status_code == 400


def test_inspection_flow(client, admin_headers, engineer_headers, employee_headers):
    room = _mk_room(client, admin_headers, "检查测试室")
    results = {
        "screen_power": "ok", "default_cast": "ok", "cables": "fail", "auto_switch": "ok",
        "remote_battery": "fail", "mic": "ok",
    }
    # 管理员填报（检查留痕：检查人/时间/检查项结果/备注）
    body = {"results": results, "note": "遥控器电池耗尽待换；HDMI 线外皮破损需报修"}
    r = client.post(_join("/api/meetings/rooms", room["id"]) + "/inspections", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    ins = r.json()
    assert ins["inspector"]["name"] and ins["results"]["cables"] == "fail" and "报修" in ins["note"]

    # 校验：未知检查项 / 非法结果值
    assert client.post(_join("/api/meetings/rooms", room["id"]) + "/inspections", json={"results": {"bad_key": "ok"}}, headers=admin_headers).status_code == 400
    assert client.post(_join("/api/meetings/rooms", room["id"]) + "/inspections", json={"results": {"cables": "好"}}, headers=admin_headers).status_code == 400
    # 第二十七批+：员工无权填报；工程师已开放（现场检查填报）
    assert client.post(_join("/api/meetings/rooms", room["id"]) + "/inspections", json={"results": {}}, headers=employee_headers).status_code == 403
    assert client.post(_join("/api/meetings/rooms", room["id"]) + "/inspections", json={"results": {}}, headers=engineer_headers).status_code in (200, 201)

    # 后台查历史（管理员 + 工程师各填报一条 → 共 2 条）
    items = client.get(_join("/api/meetings/rooms", room["id"]) + "/inspections", headers=admin_headers).json()
    assert len(items["items"]) == 2 and "遥控器有电池" in items["check_labels"]["remote_battery"]
    # rooms 概览带最近检查
    overview = client.get("/api/meetings/rooms", headers=admin_headers).json()["items"]
    mine = next(r for r in overview if r["id"] == room["id"])
    assert mine["latest_inspection"] is not None


def test_room_qr_scan_data(client, admin_headers, employee_headers):
    room = _mk_room(client, admin_headers, "扫码会议室", equipment_desc="投屏步骤：1 插线 2 选 HDMI", under_maintenance=True, maintenance_notice="麦克风维修中")
    emp = _emp_login(client)
    # 会议室码：staff 在标签制作生成
    tag = client.post("/api/qr-tags", json={"name": "扫码会议室码", "kind": "room", "room_id": room["id"]}, headers=admin_headers)
    assert tag.status_code == 201, tag.text
    assert tag.json()["kind_label"] == "会议室码" and tag.json()["room"]["name"] == "扫码会议室"
    code = tag.json()["code"]

    # 校验：会议室码必须绑定会议室
    assert client.post("/api/qr-tags", json={"name": "坏码", "kind": "room"}, headers=admin_headers).status_code == 400

    # 匿名扫码：会议室信息 + 预约列表 + 维修公告 + 使用说明
    d = client.get(_join("/api/qr", code)).json()
    assert d["kind"] == "room" and d["room"]["equipment_desc"].startswith("投屏步骤")
    assert d["room"]["under_maintenance"] is True and d["room"]["maintenance_notice"] == "麦克风维修中"
    assert d["authenticated"] is False and d["is_admin"] is False
    assert d["latest_inspection"] is None

    # 员工登录扫码 → 可预约；管理员扫码 → is_admin
    d = client.get(_join("/api/qr", code), headers=emp).json()
    assert d["authenticated"] is True and d["is_admin"] is False
    d = client.get(_join("/api/qr", code), headers=admin_headers).json()
    assert d["is_admin"] is True

    # 维修房间先解除维修（同时验证 PATCH）→ 预约后扫码页可见
    upd = {"name": "扫码会议室", "location": "3F", "capacity": 12, "equipment_desc": "投屏步骤：1 插线 2 选 HDMI",
           "under_maintenance": False, "maintenance_notice": ""}
    assert client.patch(_join("/api/meetings/rooms", room["id"]), json=upd, headers=admin_headers).status_code == 200
    d, s, e = _future_slot()
    body = {"room_id": room["id"], "date": d, "start_time": s, "end_time": e, "title": "评审会"}
    r = client.post("/api/meetings/bookings", json=body, headers=emp)
    assert r.status_code == 201, r.text
    d = client.get(_join("/api/qr", code)).json()
    assert any(b["title"] == "评审会" for b in d["bookings"])

    # 会议室码不能用于报修建单
    body = {"title": "xx", "description": "测试", "category": "其他问题", "qr_code": code}
    r = client.post("/api/tickets", json=body, headers=employee_headers)
    assert r.status_code == 400 and "预约" in r.json()["detail"]


def test_recurring_bookings_and_stats(client, admin_headers, employee_headers):
    """v2.12 周期性预约（冲突跳过汇报）+ 会议室使用率统计。"""
    room_a = _mk_room(client, admin_headers, "周期 A")
    emp = _emp_login(client)
    d, s, e = _future_slot()

    # 占用 room_a 首场 → 周期预约 room_a 首场被跳过、其余创建
    body = {"room_id": room_a["id"], "date": d, "start_time": s, "end_time": e, "title": "占位"}
    assert client.post("/api/meetings/bookings", json=body, headers=admin_headers).status_code == 201
    rec = {
        "room_id": room_a["id"], "start_date": d, "weeks": 4,
        "start_time": s, "end_time": e, "title": "每周例会",
    }
    r = client.post("/api/meetings/bookings/recurring", json=rec, headers=emp)
    assert r.status_code == 201, r.text
    res = r.json()
    assert len(res["created"]) == 3 and len(res["skipped"]) == 1
    assert res["skipped"][0]["date"] == d
    assert "跳过 1 场" in res["message"]

    # 全部失败（维修中房间）→ 400 汇总首个原因
    maint = _mk_room(client, admin_headers, "周期维修室", under_maintenance=True)
    rec3 = {**rec, "room_id": maint["id"], "weeks": 1}
    r = client.post("/api/meetings/bookings/recurring", json=rec3, headers=emp)
    assert r.status_code == 400 and "全部场次均未创建成功" in r.json()["detail"]

    # stats：使用率统计含房间、占用时长>0、维修中房间也可统计
    st = client.get("/api/meetings/stats?days=30", headers=admin_headers).json()
    names = {x["name"]: x for x in st["items"]}
    # 周期场次全在未来 → upcoming 计数；stats 只统计过去 30 天占用
    assert "周期 A" in names and names["周期 A"]["upcoming"] >= 3
    assert names["周期维修室"]["bookings_30"] == 0


def test_available_rooms_and_asset_parts(client, admin_headers, employee_headers):
    """v2.12 扫码冲突推荐：available 接口排除已约/维修中房间；维修部件留痕溯源。"""
    from datetime import timedelta as _td

    from sqlalchemy import select as _select

    from app.models.asset_event import AssetEvent
    from app.models.database import create_session
    from app.models.knowledge import Asset

    # ---- available：占用/维修中的房间不在列表 ----
    r1 = _mk_room(client, admin_headers, "可约推荐 A")
    r2 = _mk_room(client, admin_headers, "被占用 B")
    r3 = _mk_room(client, admin_headers, "维修中 C", under_maintenance=True)
    emp = _emp_login(client)
    d, s, e = _future_slot()
    body = {"room_id": r2["id"], "date": d, "start_time": s, "end_time": e, "title": "占用测试"}
    assert client.post("/api/meetings/bookings", json=body, headers=emp).status_code == 201
    res = client.get(f"/api/meetings/available?date={d}&start_time={s}&end_time={e}", headers=admin_headers).json()
    names = [r["name"] for r in res["items"]]
    assert "可约推荐 A" in names and "被占用 B" not in names and "维修中 C" not in names

    # ---- 维修部件留痕：送修记录加装/拆卸部件（SN 溯源） ----
    a = client.post("/api/assets", json={"asset_tag": "MT-PC-1", "name": "部件溯源电脑", "category": "电脑"}, headers=admin_headers).json()
    body = {
        "action": "repair", "note": "硬盘异响",
        "parts": [
            {"name": "机械硬盘 1T", "sn": "SN-OLD-1", "direction": "remove"},
            {"name": "固态硬盘 512G", "sn": "SN-NEW-9", "direction": "add"},
            {"name": "", "sn": "", "direction": "add"},  # 空部件行应被忽略
        ],
    }
    r = client.post("/api/assets/" + str(a["id"]) + "/action", json=body, headers=admin_headers)
    assert r.status_code == 200, r.text
    db = create_session()
    try:
        evs = db.scalars(_select(AssetEvent).where(AssetEvent.asset_id == a["id"])).all()
        repair = next(e for e in evs if e.action == "repair")
        import json as _json

        parts = _json.loads(repair.parts)
        assert len(parts) == 2 and parts[0]["direction"] == "remove" and parts[1]["sn"] == "SN-NEW-9"
    finally:
        db.close()
    # 历史接口返回 parts
    ev = client.get("/api/assets/" + str(a["id"]) + "/events", headers=admin_headers).json()["items"][0]
    assert len(ev["parts"]) == 2
    # 非法 direction 拒绝
    bad = {"action": "repair", "parts": [{"name": "x", "direction": "swap"}]}
    assert client.post("/api/assets/" + str(a["id"]) + "/action", json=bad, headers=admin_headers).status_code == 400
    # ---- 资产类别多值过滤（设备管理页签） ----
    client.post("/api/assets", json={"asset_tag": "MT-PRN-1", "name": "部件测试打印机", "category": "打印机"}, headers=admin_headers)
    res = client.get("/api/assets?categories=打印机", headers=admin_headers).json()
    assert any(x["asset_tag"] == "MT-PRN-1" for x in res["items"])
    assert not any(x["asset_tag"] == "MT-PC-1" for x in res["items"])


def test_org_tags_and_software_source_link(client, admin_headers, employee_headers):
    """v2.12 组织字典：CRUD、seed、来源结构化校验、部门筛选联动。"""
    from app.models.database import create_session
    from app.models.org import OrgTag
    from app.models.user import User
    from sqlalchemy import select as _select

    # seed：首次 GET org-tags 时从用户部门聚合初始化（惰性触发）
    res = client.get("/api/org-tags", headers=admin_headers)
    assert res.status_code == 200, res.text
    db = create_session()
    try:
        seeded = db.scalars(_select(OrgTag)).all()
        types = {t.type for t in seeded}
        names = {t.name for t in seeded}
        assert types <= {"dept", "position"}
        assert names, "用户表部门应被聚合进来"
        assert any("部" in n for n in names), "应包含用户表的部门（如业务部/IT部）"
    finally:
        db.close()

    # CRUD：员工只读、管理员增删
    assert client.get("/api/org-tags", headers=employee_headers).status_code == 200
    r = client.post("/api/org-tags", json={"type": "dept", "name": "MT 研发部"}, headers=employee_headers)
    assert r.status_code == 403
    r = client.post("/api/org-tags", json={"type": "dept", "name": "MT 研发部"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert client.post("/api/org-tags", json={"type": "dept", "name": "MT 研发部"}, headers=admin_headers).status_code == 400

    # 来源结构化校验：非法类型/URL 拒绝
    bad = {"name": "MT 来源软件", "source_type": "未知来源"}
    assert client.post("/api/softwares", json=bad, headers=admin_headers).status_code == 400
    bad = {"name": "MT 来源软件", "source_type": "软件官网", "source_url": "javascript:alert(1)"}
    assert client.post("/api/softwares", json=bad, headers=admin_headers).status_code == 400
    ok = {"name": "MT 来源软件", "source_type": "项目地址", "source_url": "https://git.example.com/proj"}
    r = client.post("/api/softwares", json=ok, headers=admin_headers)
    assert r.status_code == 201 and r.json()["source_type"] == "项目地址" and r.json()["source_url"].startswith("https://")

    # 部门筛选：限定该部门的软件命中
    sw = client.post(
        "/api/softwares",
        json={"name": "MT 部门专用软件", "source_type": "软件官网", "departments": ["MT 研发部"]},
        headers=admin_headers,
    ).json()
    res = client.get("/api/softwares?dept=MT%20研发部", headers=admin_headers).json()
    assert any(x["id"] == sw["id"] for x in res["items"])
    assert "MT 研发部" in res["dept_options"]  # 选项来自组织字典

    # 清理
    db = create_session()
    try:
        for t in db.scalars(_select(OrgTag).where(OrgTag.name.like("MT %"))).all():
            db.delete(t)
        from app.models.ledger import SoftwareItem

        for s in db.scalars(_select(SoftwareItem).where(SoftwareItem.name.like("MT %"))).all():
            db.delete(s)
        db.commit()
    finally:
        db.close()


def test_software_request_in_ticket(client, admin_headers, employee_headers):
    """v2.12 软件安装申请闭环：员工建单从软件目录选择 → 快照进工单；目录登录即可读。"""
    sw = client.post(
        "/api/softwares",
        json={"name": "MT-BP 平板投屏", "category": "办公软件", "license_type": "免费商用", "description": "会议室投屏工具", "source_type": "软件官网", "source_url": "https://mt.example.com"},
        headers=admin_headers,
    ).json()
    sid = sw["id"]
    assert sw["source_type"] == "软件官网" and sw["source_url"] == "https://mt.example.com"
    # 员工可读目录（建单选择用）
    assert client.get("/api/softwares", headers=employee_headers).status_code == 200
    # 员工建单带 software_id → 快照进 custom_fields
    body = {"title": "申请安装投屏工具", "description": "会议室使用", "category": "软件安装", "software_id": sid}
    r = client.post("/api/tickets", json=body, headers=employee_headers)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    cf = r.json()["custom_fields"]["software"]
    assert cf["name"] == "MT-BP 平板投屏" and cf["license_type"] == "免费商用"
    # 无效 software_id → 400
    bad = {"title": "坏软件ID", "description": "x", "category": "软件安装", "software_id": 999999}
    assert client.post("/api/tickets", json=bad, headers=employee_headers).status_code == 400
    # 详情可见（软件安装申请闭环）
    d = client.get("/api/tickets/" + str(tid), headers=employee_headers).json()
    assert d["custom_fields"]["software"]["id"] == sid


def _mk_ticket_at(client, admin_headers, minutes_before: int, preset_solution: bool = False) -> int:
    """建一张受理并提交过方案的工单，创建时间回拨 minutes_before 分钟（完结耗时分级测试用）。"""
    r = client.post("/api/tickets", json={"title": f"完结留痕 {minutes_before}", "description": "x", "category": "其他问题"}, headers=admin_headers)
    tid = r.json()["id"]
    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.models.user import utcnow

    db = create_session()
    try:
        t = db.get(Ticket, tid)
        t.created_at = utcnow() - timedelta(minutes=minutes_before)
        db.commit()
    finally:
        db.close()
    return tid


def _cleanup_ticket(tid: int) -> None:
    from app.models.database import create_session
    from app.models.ticket import Ticket

    db = create_session()
    try:
        t = db.get(Ticket, tid)
        t.no = "_del_" + t.no
        t.status = "closed"
        t.merged_into_id = None
        db.commit()
        db.delete(t)
        db.commit()
    finally:
        db.close()


def test_finish_by_engineer_and_comment_edit(client, admin_headers, employee_headers):
    """v2.12 工程师完结（finish）：直接 processing→resolved、solution 追加式；评论编辑与已修改标记。"""
    # 工程师处理中 → 直接完结（不经过待确认）
    r = client.post("/api/tickets", json={"title": "完结测试-处理中", "description": "x", "category": "其他问题"}, headers=employee_headers)
    tid = r.json()["id"]
    assert client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "accept"}, headers=admin_headers).status_code == 200
    d = client.get("/api/tickets/" + str(tid), headers=admin_headers).json()
    assert "finish" in d["available_actions"] and "submit_solution" not in d["available_actions"]
    # 员工不能完结
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "solution": "x", "note": "y"}, headers=employee_headers)
    assert r.status_code == 400
    # 完结：追加式方案 + 反馈
    body = {"action": "finish", "solution": "更换内存条", "note": "已更换内存并测试通过"}
    r = client.post("/api/tickets/" + str(tid) + "/transition", json=body, headers=admin_headers)
    assert r.status_code == 200, r.text
    d = client.get("/api/tickets/" + str(tid), headers=admin_headers).json()
    assert d["status"] == "resolved" and d["solution"] == "更换内存条"
    # resolved 状态下再次 finish → 不允许
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "solution": "追加"}, headers=admin_headers)
    assert r.status_code == 400
    # 评论编辑：管理员可改员工评论、edited 标记
    cid = client.post("/api/tickets/" + str(tid) + "/comment", json={"content": "原始评论"}, headers=employee_headers).json()["id"]
    ev = client.get("/api/tickets/" + str(tid), headers=admin_headers).json()["events"]
    cev = next(e for e in ev if e["id"] == cid)
    assert cev["edited"] is False
    r = client.patch("/api/tickets/" + str(tid) + "/comments/" + str(cid), json={"content": "管理员修正后的评论"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["edited"] is True
    d = client.get("/api/tickets/" + str(tid), headers=admin_headers).json()
    cev2 = next(e for e in d["events"] if e["id"] == cid)
    assert cev2["content"] == "管理员修正后的评论" and cev2["edited"] is True
    _cleanup_ticket(tid)


def test_finish_feedback_required(client, admin_headers, employee_headers):
    """v2.12 完结留痕分级（finish 动作）：耗时 >1h 两项必填；30min~1h 反馈必填；<30min 均选填；方案追加式。"""

    def _accept(tid):
        client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "accept"}, headers=admin_headers)

    # >1h：缺方案 → 拒；缺反馈 → 拒；齐全 → 通过归档
    tid = _mk_ticket_at(client, admin_headers, 90)
    _accept(tid)
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "反馈", "solution": ""}, headers=admin_headers)
    assert r.status_code == 400 and "解决方案" in r.json()["detail"]
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "", "solution": "更换主板"}, headers=admin_headers)
    assert r.status_code == 400 and "反馈处理结果" in r.json()["detail"]
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "已上门修复并验证", "solution": "更换主板后恢复"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    d = client.get("/api/tickets/" + str(tid), headers=admin_headers).json()
    assert d["solution"] == "更换主板后恢复" and d["status"] == "resolved"
    _cleanup_ticket(tid)

    # >1h 且已有方案：再次完结走追加式（新方案追加【补充】，不改写原内容）；反馈仍必填
    tid = _mk_ticket_at(client, admin_headers, 90)
    _accept(tid)
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "首次处理完成", "solution": "首次方案"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "reopen", "note": "问题复现"}, headers=admin_headers)
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "", "solution": "补充：加装散热支架"}, headers=admin_headers)
    assert r.status_code == 400 and "反馈处理结果" in r.json()["detail"]
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "复现问题已处理", "solution": "加装散热支架"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    d = client.get("/api/tickets/" + str(tid), headers=admin_headers).json()
    assert d["solution"] == "首次方案\n【补充】加装散热支架"
    _cleanup_ticket(tid)

    # 30min~1h：反馈缺 → 拒绝；补反馈 → 通过
    tid = _mk_ticket_at(client, admin_headers, 45)
    _accept(tid)
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "", "solution": ""}, headers=admin_headers)
    assert r.status_code == 400 and "反馈处理结果" in r.json()["detail"]
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "远程指导解决", "solution": ""}, headers=admin_headers)
    assert r.status_code == 200, r.text
    _cleanup_ticket(tid)

    # <30min：均选填直接通过
    tid = _mk_ticket_at(client, admin_headers, 10)
    _accept(tid)
    r = client.post("/api/tickets/" + str(tid) + "/transition", json={"action": "finish", "note": "", "solution": ""}, headers=admin_headers)
    assert r.status_code == 200, r.text
    _cleanup_ticket(tid)
