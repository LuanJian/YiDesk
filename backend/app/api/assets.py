"""资产：轻量资产登记与检索（全员可查）+ 全生命周期操作记录（v2.7）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel

from sqlalchemy import or_, select

from sqlalchemy.exc import IntegrityError

from sqlalchemy.orm import Session

from app.core.deps import get_current_user

from app.core.permissions import require_perm

from app.models.asset_event import ACTIONS, AssetEvent

from app.models.database import get_db

from app.models.knowledge import Asset

from app.models.user import User

from app.schemas.common import AssetIn

router = APIRouter()

def _log_event(db: Session, asset_id: int, action: str, operator_id: int | None, note: str = "") -> None:

    db.add(AssetEvent(asset_id=asset_id, action=action, note=note.strip()[:500], operator_id=operator_id))

@router.get("")

def list_assets(

    q: str | None = None,

    status: str | None = None,

    category: str | None = None,

    categories: str | None = None,  # v2.12 设备管理页签过滤：逗号分隔多值，如 电脑,显示器

    db: Session = Depends(get_db),

    _: User = Depends(get_current_user),

):

    stmt = select(Asset).order_by(Asset.id.desc())

    if q:

        like = f"%{q}%"

        # 搜索扩展至 编号/名称/位置/品牌/型号

        stmt = stmt.where(or_(

            Asset.asset_tag.contains(like), Asset.name.contains(like), Asset.location.contains(like),

            Asset.vendor.contains(like), Asset.model.contains(like),

        ))

    if status:

        stmt = stmt.where(Asset.status == status)

    if category and category.strip():

        stmt = stmt.where(Asset.category == category.strip())

    if categories:

        cats = [c.strip() for c in categories.split(",") if c.strip()]

        if cats:

            stmt = stmt.where(Asset.category.in_(cats))

    assets = list(db.scalars(stmt).all())

    return {"items": [a.to_dict() for a in assets], "total": len(assets)}

@router.post("", status_code=201)

def create_asset(body: AssetIn, db: Session = Depends(get_db), operator: User = Depends(require_perm("assets.write"))):

    if db.scalar(select(Asset).where(Asset.asset_tag == body.asset_tag.strip())):

        raise HTTPException(status_code=400, detail="资产编号已存在")

    a = Asset(

        asset_tag=body.asset_tag.strip(),

        name=body.name.strip(),

        category=body.category,

        location=body.location.strip(),

        status=body.status if body.status in Asset.STATUS else "在用",

        owner_id=body.owner_id,

        note=body.note,

        ip_address=(body.ip_address or "").strip(),

        model=(body.model or "").strip(),

        vendor=(body.vendor or "").strip(),

        driver_url=(body.driver_url or "").strip(),

        expire_date=(body.expire_date or "").strip() or None,

        expire_warned=False,

    )

    db.add(a)

    db.flush()

    _log_event(db, a.id, "create", operator.id, f"登记资产（{a.status}）")

    db.commit()

    db.refresh(a)

    return a.to_dict()

@router.patch("/{asset_id}")

def update_asset(asset_id: int, body: AssetIn, db: Session = Depends(get_db), operator: User = Depends(require_perm("assets.write"))):

    a = db.get(Asset, asset_id)

    if not a:

        raise HTTPException(status_code=404, detail="资产不存在")

    changes: list[str] = []

    if a.status != (body.status if body.status in Asset.STATUS else a.status):

        changes.append(f"状态 {a.status} → {body.status}")

    if a.owner_id != body.owner_id:

        changes.append("使用人变更")

    a.asset_tag = body.asset_tag.strip()

    a.name = body.name.strip()

    a.category = body.category

    a.location = body.location.strip()

    a.status = body.status if body.status in Asset.STATUS else a.status

    a.owner_id = body.owner_id

    a.note = body.note

    a.ip_address = (body.ip_address or "").strip()

    a.model = (body.model or "").strip()

    a.vendor = (body.vendor or "").strip()

    a.driver_url = (body.driver_url or "").strip()

    # 到期日变更时重置提醒标记（改期后重新提醒一次）

    new_expire = (body.expire_date or "").strip() or None

    if a.expire_date != new_expire:

        changes.append(f"到期日 {a.expire_date or '-'} → {new_expire or '-'}")

        a.expire_date = new_expire

        a.expire_warned = False

    else:

        a.expire_date = new_expire

    _log_event(db, a.id, "update", operator.id, "；".join(changes) or "信息更新")

    db.commit()

    db.refresh(a)

    return a.to_dict()

@router.delete("/{asset_id}")

def delete_asset(asset_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("assets.write"))):

    a = db.get(Asset, asset_id)

    if not a:

        raise HTTPException(status_code=404, detail="资产不存在")

    try:

        db.delete(a)

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(status_code=400, detail="该资产已被工单关联，无法删除") from None

    return {"ok": True}

class RecoverIn(BaseModel):

    note: str = ""

@router.post("/{asset_id}/recover")

def recover_asset(

    asset_id: int,

    body: RecoverIn,

    db: Session = Depends(get_db),

    operator: User = Depends(require_perm("assets.write")),

):

    """资产回收（v2.4，现场运维）：清空使用人 → 状态改闲置 → 备注与操作记录留痕。"""

    from app.models.user import utcnow

    a = db.get(Asset, asset_id)

    if not a:

        raise HTTPException(status_code=404, detail="资产不存在")

    if a.status == "报废":

        raise HTTPException(status_code=400, detail="报废资产无需回收")

    record = (

        f"【回收】{utcnow():%Y-%m-%d %H:%M} 操作人：{operator.name or operator.username}"

        + (f"；说明：{body.note.strip()}" if body.note.strip() else "")

    )

    a.owner_id = None

    a.status = "闲置"

    a.note = ((a.note + "\n") if a.note else "") + record

    _log_event(db, a.id, "recover", operator.id, body.note)

    db.commit()

    db.refresh(a)

    return a.to_dict()

@router.post("/{asset_id}/detect")

def detect_asset(asset_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("assets.read"))):

    """v2.11 设备管理：TCP 探活资产（打印机 JetDirect 9100 / IPP 631 / Web 80·443 / SSH 22），1 秒超时。"""

    import socket

    from datetime import datetime as _dt, timezone as _tz

    a = db.get(Asset, asset_id)

    if not a:

        raise HTTPException(status_code=404, detail="资产不存在")

    if not a.ip_address.strip():

        raise HTTPException(status_code=400, detail="该资产未登记 IP 地址，无法检测")

    ip = a.ip_address.strip()

    online = False

    tried_port = None

    for port in (9100, 631, 80, 443, 22):

        tried_port = port

        try:

            with socket.create_connection((ip, port), timeout=1.0):

                online = True

                break

        except OSError:

            continue

    # 记录最近检测时间（供「最近检测」列统一展示）

    a.last_checked_at = _dt.now(_tz.utc)

    db.commit()

    return {"id": a.id, "ip": ip, "online": online, "port": tried_port if online else None}

class ActionIn(BaseModel):

    action: str  # assign / return / repair / repair_done / scrap / note

    note: str = ""

    owner_id: int | None = None

    parts: list[dict] = []  # v2.12 维修拆装部件 [{name, sn, direction: add|remove, note}]

ACTION_EFFECTS = {

    "assign": ("在用", True),     # (状态, 是否设置使用人为操作目标)

    "return": ("闲置", False),

    "repair": ("维修中", False),

    "repair_done": ("在用", False),

    "scrap": ("报废", False),

}

@router.post("/{asset_id}/action")

def asset_action(

    asset_id: int,

    body: ActionIn,

    db: Session = Depends(get_db),

    operator: User = Depends(require_perm("assets.write")),

):

    """资产生命周期动作（v2.7）：领用/归还/送修/修复完成/报废/备注，全部留痕。"""

    from app.models.asset_event import AssetEvent as _AE

    a = db.get(Asset, asset_id)

    if not a:

        raise HTTPException(status_code=404, detail="资产不存在")

    if body.action not in ACTION_EFFECTS and body.action != "note":

        raise HTTPException(status_code=400, detail="无效的操作")

    if body.action == "scrap" and a.status == "报废":

        raise HTTPException(status_code=400, detail="资产已报废")

    status, _set_owner = ACTION_EFFECTS.get(body.action, (a.status, False))

    a.status = status

    if body.action == "assign" and body.owner_id is not None:

        a.owner_id = body.owner_id

    if body.action == "scrap":

        a.owner_id = None

    # v2.12 维修拆装部件留痕：parts 里每条 {name, sn, direction: add|remove, note}

    parts = [p for p in body.parts if isinstance(p, dict) and str(p.get("name", "")).strip()]

    for p in parts:

        if p.get("direction") not in ("add", "remove"):

            raise HTTPException(status_code=400, detail="部件方向 direction 必须是 add（加装）或 remove（拆卸）")

    ev_note = body.note

    ev = AssetEvent(

        asset_id=a.id,

        action="note" if body.action == "note" else body.action,

        note=ev_note.strip()[:500],

        operator_id=operator.id,

        parts=json.dumps(parts, ensure_ascii=False) if parts else "[]",

    )

    if parts:

        ev.action = body.action if body.action in ("repair", "repair_done") else "part_change"

    db.add(ev)

    db.commit()

    db.refresh(a)

    # 设备状态变更 IM 推送——送修/修复完成/报废时通知使用人与全部 IT（管理员/工程师）

    NOTIFY_ACTIONS = {

        "repair": "已送修",

        "repair_done": "维修完成，恢复在用",

        "scrap": "已报废处置",

    }

    if body.action in NOTIFY_ACTIONS:

        from app.services import notify_service as _ns

        targets = [u for u in db.scalars(select(User).where(User.role.in_(("admin", "engineer")), User.is_active.is_(True))).all()]

        if a.owner_id:

            owner = db.get(User, a.owner_id)

            if owner and owner.is_active and all(u.id != owner.id for u in targets):

                targets.insert(0, owner)

        _ns.enqueue_for_users(

            db, targets, ticket_id=None,

            title=f"设备状态变更：{a.asset_tag} {a.name}",

            content=f"「{a.asset_tag} {a.name}」{NOTIFY_ACTIONS[body.action]}（操作人：{operator.name or operator.username}）"

                    + (f"，备注：{body.note.strip()[:100]}" if body.note.strip() else ""),

            url="",

        )

    return a.to_dict()

@router.get("/{asset_id}/events")

def asset_events(asset_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):

    """资产生命周期时间线（全员可查，建单参考设备状况）。"""

    if not db.get(Asset, asset_id):

        raise HTTPException(status_code=404, detail="资产不存在")

    rows = list(

        db.scalars(select(AssetEvent).where(AssetEvent.asset_id == asset_id).order_by(AssetEvent.id.desc())).all()

    )

    return {"items": [e.to_dict() for e in rows]}
