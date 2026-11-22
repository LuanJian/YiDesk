"""网络设备台账 API（staff 维护与查看；探活手动/定时）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, Field

from sqlalchemy import or_, select

from sqlalchemy.orm import Session

from app.core.config import get_config

from app.core.permissions import require_perm

from app.models.database import get_db

from app.models.ledger import DEVICE_TYPES, DEVICE_STATUS, NetworkDevice

from app.models.user import User, utcnow

from app.services import ledger_service

router = APIRouter()

class DeviceIn(BaseModel):

    name: str = Field(min_length=1, max_length=128)

    device_type: str = "交换机"

    vendor: str = ""

    model: str = ""

    ip: str = Field(min_length=7, max_length=64)

    mgmt_port: int | None = Field(default=None, ge=1, le=65535)

    location: str = ""

    serial_no: str = ""

    firmware: str = ""

    status: str = "备用"

    probe_enabled: bool = True

    # 统一设备台账——资产编号（唯一）与保修到期日

    asset_tag: str = ""

    expire_date: str | None = None

    notes: str = ""

def _validate(body: DeviceIn):

    if body.device_type not in DEVICE_TYPES:

        raise HTTPException(status_code=400, detail=f"设备类型必须是 {DEVICE_TYPES} 之一")

    if body.status not in DEVICE_STATUS:

        raise HTTPException(status_code=400, detail=f"状态必须是 {DEVICE_STATUS} 之一")

@router.get("")

def list_devices(

    q: str | None = None,

    device_type: str | None = None,

    status: str | None = None,

    db: Session = Depends(get_db),

    _: User = Depends(require_perm("devices.read")),

):

    stmt = select(NetworkDevice).order_by(NetworkDevice.id)

    if q:

        like = f"%{q}%"

        # 搜索扩展至 名称/IP/位置/品牌/型号/资产编号

        stmt = stmt.where(or_(

            NetworkDevice.name.contains(like), NetworkDevice.ip.contains(like), NetworkDevice.location.contains(like),

            NetworkDevice.vendor.contains(like), NetworkDevice.model.contains(like), NetworkDevice.asset_tag.contains(like),

        ))

    if device_type:

        stmt = stmt.where(NetworkDevice.device_type == device_type)

    if status:

        stmt = stmt.where(NetworkDevice.status == status)

    items = list(db.scalars(stmt).all())

    return {

        "items": [d.to_dict() for d in items],

        "total": len(items),

        "summary": ledger_service.device_summary(db),

        "device_types": DEVICE_TYPES,

        "statuses": DEVICE_STATUS,

    }

@router.post("", status_code=201)

def create_device(body: DeviceIn, db: Session = Depends(get_db), _: User = Depends(require_perm("devices.write"))):

    _validate(body)

    d = NetworkDevice(**body.model_dump())

    db.add(d)

    db.commit()

    db.refresh(d)

    return d.to_dict()

@router.patch("/{device_id}")

def update_device(device_id: int, body: DeviceIn, db: Session = Depends(get_db), _: User = Depends(require_perm("devices.write"))):

    d = db.get(NetworkDevice, device_id)

    if not d:

        raise HTTPException(status_code=404, detail="设备不存在")

    _validate(body)

    for field, val in body.model_dump().items():

        setattr(d, field, val)

    db.commit()

    db.refresh(d)

    return d.to_dict()

@router.delete("/{device_id}")

def delete_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("devices.write"))):

    d = db.get(NetworkDevice, device_id)

    if not d:

        raise HTTPException(status_code=404, detail="设备不存在")

    db.delete(d)

    db.commit()

    return {"ok": True}

@router.post("/probe-all")

def probe_all(db: Session = Depends(get_db), _: User = Depends(require_perm("devices.write"))):

    result = ledger_service.probe_all_devices(db)

    return result

@router.post("/{device_id}/probe")

def probe_one(device_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("devices.write"))):

    d = db.get(NetworkDevice, device_id)

    if not d:

        raise HTTPException(status_code=404, detail="设备不存在")

    ok = ledger_service.probe_device(d, float(get_config().network.probe_timeout_seconds))

    d.last_checked_at = utcnow()

    if ok:

        d.status = "在线"

        d.last_seen_at = d.last_checked_at

    else:

        d.status = "失联"

    db.commit()

    return {"ok": ok, "status": d.status, "ip": d.ip}
