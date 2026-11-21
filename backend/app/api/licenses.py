"""软件许可台账 API（staff 可读，admin 维护；许可密钥仅 admin 可见完整值）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.permissions import require_perm
from app.models.database import get_db
from app.models.ledger import LICENSE_TYPES, SoftwareLicense
from app.models.user import User
from app.services import ledger_service

router = APIRouter()


class LicenseIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    vendor: str = ""
    license_type: str = "永久授权"
    license_key: str = ""
    seats_total: int = Field(default=1, ge=1)
    seats_used: int = Field(default=0, ge=0)
    purchase_date: str | None = None  # YYYY-MM-DD
    expiry_date: str | None = None
    cost: int = 0
    vendor_contact: str = ""
    notes: str = ""
    enabled: bool = True


def _parse_date(s: str | None):
    from datetime import date

    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"日期格式应为 YYYY-MM-DD: {s}") from None


@router.get("")
def list_licenses(
    q: str | None = None,
    license_type: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_perm("licenses.read")),
):
    stmt = select(SoftwareLicense).order_by(SoftwareLicense.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(SoftwareLicense.name.contains(like), SoftwareLicense.vendor.contains(like)))
    if license_type:
        stmt = stmt.where(SoftwareLicense.license_type == license_type)
    items = list(db.scalars(stmt).all())
    return {
        "items": [l.to_dict(show_key=False) for l in items],
        "total": len(items),
        "summary": ledger_service.license_summary(db),
        "license_types": LICENSE_TYPES,
    }


@router.get("/{license_id}")
def get_license(license_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    lic = db.get(SoftwareLicense, license_id)
    if not lic:
        raise HTTPException(status_code=404, detail="许可不存在")
    return lic.to_dict(show_key=True)


@router.post("", status_code=201)
def create_license(body: LicenseIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.license_type not in LICENSE_TYPES:
        raise HTTPException(status_code=400, detail=f"许可类型必须是 {LICENSE_TYPES} 之一")
    lic = SoftwareLicense(
        name=body.name.strip(), vendor=body.vendor.strip(), license_type=body.license_type,
        license_key=body.license_key.strip(), seats_total=body.seats_total, seats_used=body.seats_used,
        purchase_date=_parse_date(body.purchase_date), expiry_date=_parse_date(body.expiry_date),
        cost=body.cost, vendor_contact=body.vendor_contact.strip(), notes=body.notes, enabled=body.enabled,
    )
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return lic.to_dict(show_key=True)


@router.patch("/{license_id}")
def update_license(license_id: int, body: LicenseIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    lic = db.get(SoftwareLicense, license_id)
    if not lic:
        raise HTTPException(status_code=404, detail="许可不存在")
    if body.license_type not in LICENSE_TYPES:
        raise HTTPException(status_code=400, detail=f"许可类型必须是 {LICENSE_TYPES} 之一")
    lic.name = body.name.strip()
    lic.vendor = body.vendor.strip()
    lic.license_type = body.license_type
    if body.license_key:  # 留空则不覆盖密钥
        lic.license_key = body.license_key.strip()
    lic.seats_total = body.seats_total
    lic.seats_used = body.seats_used
    lic.purchase_date = _parse_date(body.purchase_date)
    lic.expiry_date = _parse_date(body.expiry_date)
    lic.cost = body.cost
    lic.vendor_contact = body.vendor_contact.strip()
    lic.notes = body.notes
    lic.enabled = body.enabled
    db.commit()
    db.refresh(lic)
    return lic.to_dict(show_key=True)


@router.delete("/{license_id}")
def delete_license(license_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    lic = db.get(SoftwareLicense, license_id)
    if not lic:
        raise HTTPException(status_code=404, detail="许可不存在")
    db.delete(lic)
    db.commit()
    return {"ok": True}
