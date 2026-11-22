"""二维码报修：标签管理（staff）+ 扫码页数据（全员）。

二维码内容只编码短 URL（{public_base_url}/qr/{code}），改数据不重印贴纸。

建单自动填充/指定派单逻辑在 POST /tickets 里（见 api/tickets.py）。

v2.12 新增会议室码：扫码看预约状态/设备说明，管理员扫码可填报设备检查。

"""

from __future__ import annotations

import io

from datetime import date as date_type, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from fastapi.responses import StreamingResponse

from pydantic import BaseModel, Field, field_validator

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_optional_user

from app.core.config import get_config

from app.core.permissions import require_perm

from app.models.database import get_db

from app.models.knowledge import Asset

from app.models.meeting import ROOM_CHECK_ITEMS, MeetingBooking, MeetingRoom, RoomInspection

from app.models.qr import QR_KINDS, QR_KIND_LABELS, QrTag

from app.models.user import User

from app.services import qr_service

router = APIRouter()           # 标签管理：挂载在 /qr-tags

public_router = APIRouter()    # 扫码页数据：挂载在 /qr

class QrTagIn(BaseModel):

    name: str = Field(min_length=1, max_length=128)

    kind: str = "location"

    location: str = ""

    asset_id: int | None = None

    engineer_id: int | None = None

    room_id: int | None = None  # v2.12 会议室码：关联会议室

    category: str = ""  # 扫码建单默认分类（留空用提交值）

    enabled: bool = True

    note: str = ""

    @field_validator("kind")

    @classmethod

    def _kind(cls, v: str) -> str:

        if v not in QR_KINDS:

            raise ValueError(f"kind 必须是 {QR_KINDS} 之一")

        return v

def _validate_refs(db: Session, body: QrTagIn) -> None:

    if body.kind == "device" and not body.asset_id:

        raise HTTPException(status_code=400, detail="设备码必须关联资产")

    if body.asset_id:

        if not db.get(Asset, body.asset_id):

            raise HTTPException(status_code=404, detail="关联资产不存在")

        if body.kind != "device":

            raise HTTPException(status_code=400, detail="只有设备码可关联资产")

    if body.kind == "assignee" and not body.engineer_id:

        raise HTTPException(status_code=400, detail="指定派单码必须绑定工程师")

    if body.engineer_id:

        u = db.get(User, body.engineer_id)

        if not u or u.role not in ("admin", "engineer"):

            raise HTTPException(status_code=400, detail="绑定对象必须是工程师/管理员")

    if body.kind == "room" and not body.room_id:

        raise HTTPException(status_code=400, detail="会议室码必须关联会议室")

    if body.room_id:

        if not db.get(MeetingRoom, body.room_id):

            raise HTTPException(status_code=404, detail="关联会议室不存在")

        if body.kind != "room":

            raise HTTPException(status_code=400, detail="只有会议室码可关联会议室")

def _tag_dict(db: Session, tag: QrTag) -> dict:

    item = tag.to_dict()

    item["qr_url"] = tag.qr_url

    item["engineer"] = None

    item["asset"] = None

    item["room"] = None

    if tag.engineer_id:

        u = db.get(User, tag.engineer_id)

        item["engineer"] = {"id": u.id, "name": u.name or u.username} if u else None

    if tag.asset_id:

        a = db.get(Asset, tag.asset_id)

        item["asset"] = a.to_dict() if a else None

    if tag.room_id:

        r = db.get(MeetingRoom, tag.room_id)

        item["room"] = r.to_dict() if r else None

    return item

# ---------- 标签 CRUD（staff） ----------

@router.get("")

def list_qr_tags(kind: str | None = None, category: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_perm("qr-tags"))):

    stmt = select(QrTag).order_by(QrTag.id.desc())

    if kind:

        stmt = stmt.where(QrTag.kind == kind)

    # 按默认分类筛选（空分类=未预填分类的标签，用 is null 匹配前端「未预填」选项场景）

    if category:

        stmt = stmt.where(QrTag.category == category)

    items = [_tag_dict(db, t) for t in db.scalars(stmt).all()]

    # 筛选下拉选项=全库分类去重（不受当前筛选/分页影响）

    all_categories = sorted({c for (c,) in db.query(QrTag.category).all() if c})

    return {"items": items, "total": len(items), "categories": all_categories}

@router.post("", status_code=201)

def create_qr_tag(body: QrTagIn, db: Session = Depends(get_db), user: User = Depends(require_perm("qr-tags"))):

    _validate_refs(db, body)

    tag = QrTag(

        code=qr_service.generate_code(db),

        name=body.name.strip(),

        kind=body.kind,

        location=body.location.strip(),

        asset_id=body.asset_id,

        engineer_id=body.engineer_id,

        room_id=body.room_id,

        category=body.category,

        enabled=body.enabled,

        note=body.note.strip(),

        created_by_id=user.id,

    )

    db.add(tag)

    db.commit()

    db.refresh(tag)

    return _tag_dict(db, tag)

@router.patch("/{tag_id}")

def update_qr_tag(tag_id: int, body: QrTagIn, db: Session = Depends(get_db), _: User = Depends(require_perm("qr-tags"))):

    tag = db.get(QrTag, tag_id)

    if not tag:

        raise HTTPException(status_code=404, detail="标签不存在")

    _validate_refs(db, body)

    tag.name = body.name.strip()

    tag.kind = body.kind

    tag.location = body.location.strip()

    tag.asset_id = body.asset_id

    tag.engineer_id = body.engineer_id

    tag.room_id = body.room_id

    tag.category = body.category

    tag.enabled = body.enabled

    tag.note = body.note.strip()

    db.commit()

    db.refresh(tag)

    return _tag_dict(db, tag)

@router.delete("/{tag_id}")

def delete_qr_tag(tag_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("qr-tags"))):

    tag = db.get(QrTag, tag_id)

    if not tag:

        raise HTTPException(status_code=404, detail="标签不存在")

    db.delete(tag)

    db.commit()

    return {"ok": True}

# ---------- 二维码 PNG（staff，可打印） ----------

@router.get("/{tag_id}/qr.png")

def qr_png(tag_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("qr-tags"))):

    import qrcode

    tag = db.get(QrTag, tag_id)

    if not tag:

        raise HTTPException(status_code=404, detail="标签不存在")

    img = qrcode.make(tag.qr_url, box_size=6, border=2)

    buf = io.BytesIO()

    img.save(buf, format="PNG")

    buf.seek(0)

    return StreamingResponse(

        buf, media_type="image/png",

        headers={"Content-Disposition": f"inline; filename={tag.code}.png"},

    )

# ---------- 扫码页数据（登录/匿名均可访问） ----------

@public_router.get("/{code}")

def qr_code_data(code: str, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):

    """扫码落地页数据（v2.11 支持匿名访问）：标签信息 + 此码未结工单 + 建单分类。

    v2.12 会议室码分支：会议室信息 + 未来预约 + 设备使用说明 + 维修公告 + 最近检查（管理员另可填报）。

    """

    tag = qr_service.resolve_tag(db, code)

    if not tag:

        raise HTTPException(status_code=404, detail="二维码无效或已停用")

    if tag.kind == "room":

        room = db.get(MeetingRoom, tag.room_id) if tag.room_id else None

        if not room or not room.enabled:

            raise HTTPException(status_code=404, detail="会议室不存在或已停用")

        bookings = list(

            db.scalars(

                select(MeetingBooking).where(

                    MeetingBooking.room_id == room.id,

                    MeetingBooking.status == MeetingBooking.STATUS_ACTIVE,

                    MeetingBooking.date >= date_type.today(),

                    MeetingBooking.date < date_type.today() + timedelta(days=14),

                ).order_by(MeetingBooking.date, MeetingBooking.start_time)

            )

        )

        latest = db.scalar(

            select(RoomInspection).where(RoomInspection.room_id == room.id).order_by(RoomInspection.id.desc()).limit(1)

        )

        return {

            "code": tag.code,

            "name": tag.name,

            "kind": "room",

            "kind_label": QR_KIND_LABELS["room"],

            "location": room.location or tag.location,

            "room": room.to_dict(),

            "bookings": [b.to_dict() for b in bookings],

            "latest_inspection": latest.to_dict() if latest else None,

            "check_items": ROOM_CHECK_ITEMS,

            "authenticated": user is not None,

            "is_admin": bool(user and user.role in ("admin", "engineer")),

        }

    engineer = db.get(User, tag.engineer_id) if tag.kind == "assignee" and tag.engineer_id else None

    user_id = user.id if user else None

    return {

        "code": tag.code,

        "name": tag.name,

        "kind": tag.kind,

        "kind_label": QR_KIND_LABELS.get(tag.kind, tag.kind),

        "location": tag.location,

        "device": qr_service.device_info(db, tag),

        "default_category": tag.category or None,

        "categories": get_config().categories,

        "forced_engineer": (

            {"id": engineer.id, "name": engineer.name or engineer.username}

            if engineer and engineer.is_active else None

        ),

        "open_tickets": qr_service.open_tickets_for_code(db, tag.code, user_id, include_all=tag.kind == "device"),

        "authenticated": user is not None,

        "is_admin": bool(user and user.role in ("admin", "engineer")),

    }
