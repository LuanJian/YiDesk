"""会议室预约管理 API（v2.12）。

- 会议室 CRUD：管理员
- 预约：登录员工可预约（冲突校验），取消限本人或管理员
- 设备检查留痕：管理员填报（逐项结果 + 备注），后台可查历史
- 会议管理总览：管理员（各会议室 + 当日/未来预约 + 最近检查）
"""
from __future__ import annotations

import json
from datetime import date as date_type, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin, require_staff
from app.models.database import get_db
from app.models.meeting import ROOM_CHECK_ITEMS, ROOM_CHECK_LABELS, MeetingBooking, MeetingRoom, RoomInspection
from app.models.ticket import Ticket
from app.models.user import User, utcnow
from app.services import ticket_service

router = APIRouter()

TIME_PATTERN = "%H:%M"


class RoomEquipmentIn(BaseModel):
    """第三十九批：会议室设备条目（员工扫码可见，运维维护标注）。"""

    name: str = Field(min_length=1, max_length=64)
    count: int = Field(default=1, ge=1, le=999)
    status: str = "正常"  # 正常/维修中/损坏


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    location: str = ""
    capacity: int = Field(default=10, ge=1, le=999)
    equipment_desc: str = ""
    equipment_list: list[RoomEquipmentIn] = []  # 第三十九批：设备列表
    check_cycle_days: int = Field(default=0, ge=0, le=365)  # v2.12 兼容旧字段（周期天数）
    # 第三十九批：巡检周期扩展——unit day/week/session + value（每 N 天/周/场次）
    check_cycle_unit: str = Field(default="day", pattern="^(day|week|session)$")
    check_cycle_value: int = Field(default=0, ge=0, le=999)
    under_maintenance: bool = False
    maintenance_notice: str = ""
    enabled: bool = True


class BookingIn(BaseModel):
    room_id: int
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    title: str = Field(default="", max_length=200)


class InspectionIn(BaseModel):
    results: dict[str, str] = {}  # {item_key: "ok"|"fail"}
    note: str = ""


def _parse_time(v: str, field: str) -> str:
    try:
        datetime.strptime(v, TIME_PATTERN)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} 格式应为 HH:MM") from exc
    return v


def _room_dict(db: Session, room: MeetingRoom) -> dict:
    d = room.to_dict()
    # 今日与未来有效预约数（后台概览用）
    d["upcoming_count"] = len(
        list(
            db.scalars(
                select(MeetingBooking.id).where(
                    MeetingBooking.room_id == room.id,
                    MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
                    MeetingBooking.date >= date_type.today(),
                )
            )
        )
    )
    latest = db.scalar(
        select(RoomInspection).where(RoomInspection.room_id == room.id).order_by(RoomInspection.id.desc()).limit(1)
    )
    d["latest_inspection"] = latest.to_dict() if latest else None
    # v2.12 巡检周期超期信息（天）；第三十九批扩展 unit：day/week/session
    d["check_cycle_days"] = room.check_cycle_days
    d["check_cycle_unit"] = room.check_cycle_unit or "day"
    d["check_cycle_value"] = room.check_cycle_value
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    now_sh = _dt.now(ZoneInfo("Asia/Shanghai"))
    d["inspection_due_days"] = (
        (now_sh.date() - latest.inspected_at.astimezone(ZoneInfo("Asia/Shanghai")).date()).days
        if latest and latest.inspected_at else None
    )
    # session 模式：上次检查之后已结束的预约场次（第四十批改按会议实际日期 date 计，不再按预约创建时间）
    d["sessions_since_inspection"] = (
        db.query(MeetingBooking).filter(
            MeetingBooking.room_id == room.id,
            MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
            MeetingBooking.date < now_sh.date(),
            MeetingBooking.date > (latest.inspected_at.astimezone(ZoneInfo("Asia/Shanghai")).date() if latest and latest.inspected_at else date_type.min),
        ).count()
        if (room.check_cycle_unit or "day") == "session" and room.check_cycle_value > 0 else None
    )
    return d


# ---- 会议室 CRUD（管理员） ----

@router.get("/rooms")
def list_rooms(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rooms = list(db.scalars(select(MeetingRoom).order_by(MeetingRoom.id)).all())
    return {"items": [_room_dict(db, r) for r in rooms], "check_items": ROOM_CHECK_ITEMS}


def _equipment_json(body: RoomIn) -> str:
    """设备列表序列化（过滤空名称，状态白名单）。"""
    import json as _json

    rows = [
        {"name": e.name.strip(), "count": e.count, "status": e.status if e.status in ("正常", "维修中", "损坏") else "正常"}
        for e in body.equipment_list
        if e.name.strip()
    ]
    return _json.dumps(rows, ensure_ascii=False)


@router.post("/rooms", status_code=201)
def create_room(body: RoomIn, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    dup = db.scalar(select(MeetingRoom).where(MeetingRoom.name == body.name.strip()))
    if dup:
        raise HTTPException(status_code=400, detail="同名会议室已存在")
    room = MeetingRoom(
        name=body.name.strip(),
        location=body.location.strip(),
        capacity=body.capacity,
        equipment_desc=body.equipment_desc.strip(),
        equipment_list=_equipment_json(body),
        check_cycle_days=body.check_cycle_days,
        check_cycle_unit=body.check_cycle_unit,
        check_cycle_value=body.check_cycle_value,
        under_maintenance=body.under_maintenance,
        maintenance_notice=body.maintenance_notice.strip(),
        enabled=body.enabled,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return _room_dict(db, room)


@router.patch("/rooms/{room_id}")
def update_room(room_id: int, body: RoomIn, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    room = db.get(MeetingRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")
    dup = db.scalar(select(MeetingRoom).where(MeetingRoom.name == body.name.strip(), MeetingRoom.id != room_id))
    if dup:
        raise HTTPException(status_code=400, detail="同名会议室已存在")
    room.name = body.name.strip()
    room.location = body.location.strip()
    room.capacity = body.capacity
    room.equipment_desc = body.equipment_desc.strip()
    room.equipment_list = _equipment_json(body)
    room.check_cycle_days = body.check_cycle_days
    room.check_cycle_unit = body.check_cycle_unit
    room.check_cycle_value = body.check_cycle_value
    room.under_maintenance = body.under_maintenance
    room.maintenance_notice = body.maintenance_notice.strip()
    room.enabled = body.enabled
    db.commit()
    db.refresh(room)
    return _room_dict(db, room)


@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    room = db.get(MeetingRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")
    leftovers = db.scalar(
        select(MeetingBooking.id).where(
            MeetingBooking.room_id == room_id,
            MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
            MeetingBooking.date >= date_type.today(),
        ).limit(1)
    )
    if leftovers:
        raise HTTPException(status_code=400, detail="该会议室存在未开始的预约，请先处理后再删除")
    from app.models.qr import QrTag

    tag_ref = db.scalar(select(QrTag.id).where(QrTag.room_id == room_id).limit(1))
    if tag_ref:
        raise HTTPException(status_code=400, detail="请先在标签制作中删除关联的会议室码")
    # 连同历史/已取消的预约与检查记录一并清理（分阶段提交保证 FK 顺序）
    for b in db.scalars(select(MeetingBooking).where(MeetingBooking.room_id == room_id)).all():
        db.delete(b)
    db.commit()
    for ins in db.scalars(select(RoomInspection).where(RoomInspection.room_id == room_id)).all():
        db.delete(ins)
    db.commit()
    db.delete(room)
    db.commit()
    return {"ok": True}


# ---- 预约（登录员工） ----

@router.get("/bookings")
def list_bookings(
    room_id: int,
    start: str | None = None,  # YYYY-MM-DD，默认今天
    days: int = 14,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """某会议室未来 N 天的预约（后台与扫码页共用；扫码页匿名数据由 /qr/{code} 内嵌下发）。"""
    room = db.get(MeetingRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")
    try:
        start_d = datetime.strptime(start, "%Y-%m-%d").date() if start else date_type.today()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    rows = list(
        db.scalars(
            select(MeetingBooking).where(
                MeetingBooking.room_id == room_id,
                MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
                MeetingBooking.date >= start_d,
                MeetingBooking.date < start_d + timedelta(days=max(1, min(days, 60))),
            ).order_by(MeetingBooking.date, MeetingBooking.start_time)
        )
    )
    return {"items": [b.to_dict() for b in rows], "room": room.to_dict()}


@router.get("/available")
def available_rooms(
    date: str,
    start_time: str,
    end_time: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """查询某天某时段空闲的会议室（v2.12 扫码预约冲突时推荐其他可约会议室）。"""
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    start = _parse_time(start_time, "开始时间")
    end = _parse_time(end_time, "结束时间")
    if start >= end:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
    rooms = list(db.scalars(select(MeetingRoom).where(MeetingRoom.enabled.is_(True))).all())
    busy_ids = {
        b.room_id
        for b in db.scalars(
            select(MeetingBooking).where(
                MeetingBooking.date == d,
                MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
                MeetingBooking.start_time < end,
                MeetingBooking.end_time > start,
            )
        ).all()
    }
    out = []
    for r in rooms:
        if r.id in busy_ids or r.under_maintenance:
            continue
        out.append(r.to_dict())
    return {"items": out, "date": d.isoformat(), "start_time": start, "end_time": end}


def _booking_core(db: Session, user: User, *, room_id: int, d: date_type, start: str, end: str, title: str) -> MeetingBooking:
    """预约创建核心校验（单场次），供单次与周期性预约共用；失败抛 HTTPException。"""
    room = db.get(MeetingRoom, room_id)
    if not room or not room.enabled:
        raise HTTPException(status_code=404, detail="会议室不存在或已停用")
    if room.under_maintenance:
        raise HTTPException(status_code=400, detail="该会议室设备维修中，暂停预约")
    if start >= end:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
    if d < date_type.today():
        raise HTTPException(status_code=400, detail="不能预约过去的日期")
    if d == date_type.today() and start <= datetime.now().strftime(TIME_PATTERN):
        raise HTTPException(status_code=400, detail="不能预约今天已开始的时段")
    # 冲突：同室同日 active 且区间重叠（start < other.end and end > other.start）
    overlapping = db.scalars(
        select(MeetingBooking).where(
            MeetingBooking.room_id == room_id,
            MeetingBooking.date == d,
            MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
            MeetingBooking.start_time < end,
            MeetingBooking.end_time > start,
        )
    ).first()
    if overlapping:
        raise HTTPException(
            status_code=400,
            detail=f"预约冲突：该时段已被「{overlapping.title or overlapping.booker.name}」（{overlapping.start_time}-{overlapping.end_time}）预约",
        )
    booking = MeetingBooking(
        room_id=room_id,
        date=d,
        start_time=start,
        end_time=end,
        title=title,
        booker_id=user.id,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    # v2.12 并发兜底：预检（读）不互斥，两请求可同时通过；插入后复查，
    # 同室同时段多条则保留最早一条、回滚其余
    overlapping = db.scalars(
        select(MeetingBooking).where(
            MeetingBooking.room_id == room_id,
            MeetingBooking.date == d,
            MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,
            MeetingBooking.start_time < end,
            MeetingBooking.end_time > start,
        ).order_by(MeetingBooking.id)
    ).all()
    if len(overlapping) > 1:
        keep = overlapping[0]
        for b in overlapping[1:]:
            db.delete(b)
        db.commit()
        if booking.id != keep.id:
            raise HTTPException(
                status_code=400,
                detail=f"预约冲突：该时段已被「{keep.title or keep.booker.name}」（{keep.start_time}-{keep.end_time}）预约",
            )
    return booking


@router.post("/bookings", status_code=201)
def create_booking(body: BookingIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """预约会议室：同室同日时间区间重叠即冲突；当天已过时段不可预约。"""
    try:
        d = datetime.strptime(body.date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    start = _parse_time(body.start_time, "开始时间")
    end = _parse_time(body.end_time, "结束时间")
    booking = _booking_core(db, user, room_id=body.room_id, d=d, start=start, end=end, title=body.title.strip())
    return booking.to_dict()


class RecurringIn(BaseModel):
    room_id: int
    start_date: str  # 首次日期 YYYY-MM-DD
    weeks: int = Field(default=4, ge=1, le=12)  # 连续周数（含首次）
    start_time: str
    end_time: str
    title: str = Field(default="", max_length=200)


@router.post("/bookings/recurring", status_code=201)
def create_recurring_bookings(body: RecurringIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """周期性会议预约（v2.12）：从开始日期起每周同时段创建 weeks 场；冲突场次自动跳过并汇报。"""
    try:
        first = datetime.strptime(body.start_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    start = _parse_time(body.start_time, "开始时间")
    end = _parse_time(body.end_time, "结束时间")
    title = body.title.strip()
    created: list[dict] = []
    skipped: list[dict] = []
    for i in range(body.weeks):
        d = first + timedelta(weeks=i)
        try:
            b = _booking_core(db, user, room_id=body.room_id, d=d, start=start, end=end, title=title)
            created.append(b.to_dict())
        except HTTPException as exc:
            skipped.append({"date": d.isoformat(), "reason": exc.detail})
    if not created and skipped:
        # 一场都没建成功时把首个失败原因直接抛回，避免静默空结果
        raise HTTPException(status_code=400, detail=f"全部场次均未创建成功：{skipped[0]['date']} {skipped[0]['reason']}")
    return {
        "created": created,
        "skipped": skipped,
        "message": f"已创建 {len(created)} 场预约" + (f"，跳过 {len(skipped)} 场冲突场次" if skipped else ""),
    }


@router.get("/stats")
def meeting_stats(days: int = Query(default=30, ge=7, le=90), db: Session = Depends(get_db), _: User = Depends(require_staff)):
    """会议室使用率统计（v2.12，仅管理员）：近 N 天按工作时段 08:00-20:00 折算占用率。"""
    from datetime import datetime as _dt

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    today = _dt.now(tz).date()
    start_d = today - timedelta(days=days - 1)
    rooms = list(db.scalars(select(MeetingRoom).order_by(MeetingRoom.id)).all())
    all_bookings = list(db.scalars(select(MeetingBooking)).all())
    work_minutes = days * 12 * 60  # 每天 08:00-20:00 共 12 小时
    # 第二十三批+：爽约统计基线（签到功能上线日）——仅上线后创建的预约参与 no-show 判定
    CHECKIN_FEATURE_DATE = date_type(2026, 11, 18)
    rows = []
    for r in rooms:
        mine = [b for b in all_bookings if b.room_id == r.id]
        active = [b for b in mine if b.status == MeetingBooking.STATUS_ACTIVE]
        past = [b for b in active if start_d <= b.date <= today]
        upcoming = [b for b in active if b.date > today]
        cancelled = len([b for b in mine if b.status == MeetingBooking.STATUS_CANCELLED and start_d <= b.date <= today])
        minutes = sum(
            (int(b.end_time[:2]) * 60 + int(b.end_time[3:])) - (int(b.start_time[:2]) * 60 + int(b.start_time[3:]))
            for b in past
        )
        # 爽约：签到功能上线后创建、已结束（或已过预约时段）且从未签到的预约
        ended_after = [b for b in past if b.created_at and b.created_at.date() >= CHECKIN_FEATURE_DATE and b.date <= today]
        no_show = len([
            b for b in ended_after
            if not b.checkin_at and (b.date < today or (b.date == today and b.end_time <= _dt.now(tz).strftime("%H:%M")))
        ])
        total_planned = len(past) + cancelled
        rows.append({
            "room_id": r.id,
            "name": r.name,
            "location": r.location,
            "bookings_30": len(past),
            "cancelled_30": cancelled,
            "cancel_rate": round(100 * cancelled / total_planned, 1) if total_planned else 0,
            "avg_minutes": round(minutes / len(past)) if past else 0,
            "no_show_30": no_show,
            "hours_30": round(minutes / 60, 1),
            "upcoming": len(upcoming),
            "utilization": round(100 * minutes / work_minutes, 1) if work_minutes else 0,
        })
    rows.sort(key=lambda x: -x["hours_30"])
    # v2.12 高峰时段（近 N 天预约按开始小时分布）与各部门使用频次
    hour_dist: dict[int, int] = defaultdict(int)
    dept_freq: dict[str, int] = defaultdict(int)
    for b in all_bookings:
        if b.status != MeetingBooking.STATUS_ACTIVE or not (start_d <= b.date <= today):
            continue
        hour_dist[int(b.start_time[:2])] += 1
        dept = (b.booker.department if b.booker and b.booker.department else "未填写") or "未填写"
        dept_freq[dept] += 1
    # 第三十九批：全量返回（左右布局后空间充足），覆盖更多时段与部门
    peak_hours = sorted(hour_dist.items(), key=lambda x: -x[1])

    # 第二十三批+：部门人数（在职）→ 人均预约次数；时段热力图（星期 × 小时）；下周预约趋势
    from app.models.user import User as _User

    dept_heads: dict[str, int] = defaultdict(int)
    # SQLAlchemy ORM 聚合：条件与分组全部通过列表达式构造，生成参数化 SQL，无字符串拼接
    for dep, cnt in (
        db.query(_User.department, func.count(_User.id))
        .filter(_User.is_active.is_(True))
        .filter(_User.department != "")
        .group_by(_User.department)
        .all()
    ):
        if dep:
            dept_heads[dep] = cnt

    # 热力图：星期一~日 × 08-20 时段（近 N 天有效预约）；第四十批：next_week_trend 已随前端面板移除而删除
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    heatmap = [[0 for _ in range(12)] for _ in range(7)]  # [weekday][hour-8]
    for b in all_bookings:
        if b.status != MeetingBooking.STATUS_ACTIVE:
            continue
        if start_d <= b.date <= today:
            h = int(b.start_time[:2])
            if 8 <= h < 20:
                heatmap[b.date.weekday()][h - 8] += 1

    return {
        "days": days,
        "items": rows,
        "work_minutes_per_day": 720,
        # 第四十一批：peak_hours 冗余字段删除（与 peak_top 同数据，前端只用 peak_top）
        "peak_top": [{"hour": f"{h:02d}:00-{h + 1:02d}:00", "count": c} for h, c in peak_hours],
        "dept_freq": [
            {"department": d, "count": c, "headcount": dept_heads.get(d, 0), "per_capita": round(c / dept_heads[d], 1) if dept_heads.get(d) else None}
            for d, c in sorted(dept_freq.items(), key=lambda x: -x[1])
        ],
        "weekday_names": weekday_names,
        "heatmap": heatmap,
        "heatmap_max": max((max(row) for row in heatmap), default=0),
        "checkin_feature_date": CHECKIN_FEATURE_DATE.isoformat(),
    }


@router.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """取消预约：本人或管理员。"""
    b = db.get(MeetingBooking, booking_id)
    if not b or b.status != MeetingBooking.STATUS_ACTIVE:
        raise HTTPException(status_code=404, detail="预约不存在或已取消")
    if user.role != "admin" and b.booker_id != user.id:
        raise HTTPException(status_code=403, detail="只有预约人或管理员可以取消预约")
    b.status = MeetingBooking.STATUS_CANCELLED
    db.commit()
    return {"ok": True}


@router.post("/bookings/{booking_id}/end")
def end_booking_early(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """提前结束：进行中的预约把结束时间改为当前时刻，立即释放会议室（v2.12 预约人扫码可操作）。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    b = db.get(MeetingBooking, booking_id)
    if not b or b.status != MeetingBooking.STATUS_ACTIVE:
        raise HTTPException(status_code=404, detail="预约不存在或已取消")
    if user.role != "admin" and b.booker_id != user.id:
        raise HTTPException(status_code=403, detail="只有预约人或管理员可以提前结束")
    now_local = _dt.now(ZoneInfo("Asia/Shanghai"))
    now_hm = now_local.strftime(TIME_PATTERN)
    today_local = now_local.date()
    if not (b.date == today_local and b.start_time <= now_hm < b.end_time):
        raise HTTPException(status_code=400, detail="仅进行中的预约可以提前结束（未开始的请直接取消，已结束的无需操作）")
    b.end_time = now_hm
    db.commit()
    return {"ok": True, "end_time": now_hm}


@router.post("/bookings/{booking_id}/checkin")
def checkin_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """到场签到（第二十三批+，no-show 统计依据）：预约开始后当天任意时刻可签到；预约人本人或管理员。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    b = db.get(MeetingBooking, booking_id)
    if not b or b.status != MeetingBooking.STATUS_ACTIVE:
        raise HTTPException(status_code=404, detail="预约不存在或已取消")
    if user.role != "admin" and b.booker_id != user.id:
        raise HTTPException(status_code=403, detail="只有预约人或管理员可以签到")
    if b.checkin_at:
        return {"ok": True, "checkin_at": b.checkin_at.isoformat(), "already": True}
    now_local = _dt.now(ZoneInfo("Asia/Shanghai"))
    if b.date != now_local.date():
        raise HTTPException(status_code=400, detail="仅预约当天可以签到")
    b.checkin_at = utcnow()
    db.commit()
    return {"ok": True, "checkin_at": b.checkin_at.isoformat()}


# ---- 设备检查留痕（管理员填报） ----

@router.post("/rooms/{room_id}/inspections", status_code=201)
def create_inspection(room_id: int, body: InspectionIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    room = db.get(MeetingRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")
    valid_keys = {k for k, _ in ROOM_CHECK_ITEMS}
    unknown = [k for k in body.results if k not in valid_keys]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知检查项: {', '.join(unknown)}")
    bad = [v for v in body.results.values() if v not in ("ok", "fail")]
    if bad:
        raise HTTPException(status_code=400, detail="检查结果只能是 ok/fail")
    ins = RoomInspection(
        room_id=room_id,
        inspector_id=user.id,
        results=json.dumps(body.results, ensure_ascii=False),
        note=body.note.strip(),
    )
    db.add(ins)
    db.commit()
    db.refresh(ins)
    return ins.to_dict()


@router.get("/rooms/{room_id}/inspections")
def list_inspections(room_id: int, limit: int = Query(default=50, le=200), db: Session = Depends(get_db), _: User = Depends(require_staff)):
    room = db.get(MeetingRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")
    rows = list(
        db.scalars(select(RoomInspection).where(RoomInspection.room_id == room_id).order_by(RoomInspection.id.desc()).limit(limit))
    )
    return {"items": [r.to_dict() for r in rows], "check_labels": ROOM_CHECK_LABELS}


# ---- 第四十五批：手动发起会议室巡检（工单）——巡检类型下拉枚举，避免自由文本不一致 ----
INSPECTION_TYPES = ("定期巡检", "手动报修")


class InspectIn(BaseModel):
    inspect_type: str = Field(description="巡检类型：定期巡检/手动报修")
    note: str = ""


@router.post("/rooms/{room_id}/inspect", status_code=201)
def create_inspection_ticket(room_id: int, body: InspectIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    """手动发起该会议室的巡检工单（不替代周期扫描；防重复=同房间未结巡检单按 meeting_room_id JSON 匹配）。"""
    if body.inspect_type not in INSPECTION_TYPES:
        raise HTTPException(status_code=400, detail=f"巡检类型只能是 {'/'.join(INSPECTION_TYPES)}")
    room = db.get(MeetingRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")
    admins = [u for u in db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all()]
    if not admins:
        raise HTTPException(status_code=400, detail="无可用管理员账号，无法生成巡检工单")
    from sqlalchemy import func as _func

    open_same = db.query(Ticket).filter(
        or_(
            _func.json_extract(Ticket.custom_fields, "$.meeting_room_id") == room.id,
            Ticket.title.like(f"会议室巡检：{room.name}%"),
        ),
        Ticket.status.in_(("pending", "processing", "pending_confirm")),
    ).first()
    if open_same:
        raise HTTPException(status_code=400, detail=f"该会议室已有未结巡检工单 {open_same.no}，请先处理后再发起")
    equip_bad = [e["name"] for e in room.equipment_items if e.get("status") in ("维修中", "损坏")]
    reason = "管理员手动发起" + ("（手动报修）" if body.inspect_type == "手动报修" else "（定期巡检）")
    desc = (
        f"巡检原因：{reason}。\n"
        f"请到 {room.location or '会议室'} 现场检查设备状态并在会议室码完成检查填报。"
        + (f"\n已知异常设备：{'、'.join(equip_bad)}。" if equip_bad else "")
        + (f"\n备注：{body.note.strip()}" if body.note.strip() else "")
    )
    ticket = ticket_service.create_ticket(
        db,
        creator=admins[0],
        title=f"会议室巡检：{room.name}",
        description=desc,
        category="其他问题",
        priority="medium" if body.inspect_type == "手动报修" else "low",
        custom_fields={"meeting_room_id": room.id, "meeting_room": room.name, "巡检类型": body.inspect_type},
        validate_fields=False,
    )
    db.commit()
    return {"ticket": ticket.to_dict(), "inspect_type": body.inspect_type}
