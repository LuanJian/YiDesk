"""组织数据 API（v2.12）：公司部门与岗位字典，系统设置维护，软件目录/建单表单引用。

首次访问时惰性 seed：从用户表部门、软件目录适用标签聚合初始化，减少手工录入。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.models.database import get_db
from app.models.org import ORG_TYPES, OrgTag
from app.models.user import User

router = APIRouter()


class OrgTagIn(BaseModel):
    type: str  # dept / position
    name: str = Field(min_length=1, max_length=64)
    sort: int = 0


def _seed_once(db: Session) -> None:
    """org_tags 为空时，从用户部门与软件目录适用标签聚合并初始化一次。"""
    if db.scalar(select(OrgTag.id).limit(1)):
        return
    from app.models.knowledge import Asset  # noqa: F401 确认 metadata
    from app.models.ledger import SoftwareItem
    from app.models.user import User

    seen: set[tuple[str, str]] = set()
    for d in db.scalars(select(User.department).distinct()).all():
        if d and d.strip():
            seen.add(("dept", d.strip()))
    for sw in db.scalars(select(SoftwareItem)).all():
        for d in (sw.departments or "").split(","):
            if d.strip():
                seen.add(("dept", d.strip()))
        for p in (sw.positions or "").split(","):
            if p.strip():
                seen.add(("position", p.strip()))
    for i, (t, name) in enumerate(sorted(seen, key=lambda x: (x[0], x[1]))):
        try:
            db.add(OrgTag(type=t, name=name, sort=i))
            db.commit()
        except Exception:  # noqa: BLE001 并发首次访问可能重复 seed，唯一约束冲突直接跳过
            db.rollback()


@router.get("")
def list_org_tags(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """部门与岗位字典（登录可读：软件目录筛选、建单表单引用）。"""
    _seed_once(db)
    rows = list(db.scalars(select(OrgTag).where(OrgTag.type == "dept").order_by(OrgTag.sort, OrgTag.id)).all())
    return {
        "items": [r.to_dict() for r in rows],
        "depts": [r.name for r in rows],
    }


@router.post("", status_code=201)
def create_org_tag(body: OrgTagIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.type not in ORG_TYPES:
        raise HTTPException(status_code=400, detail=f"type 必须是 {ORG_TYPES} 之一")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    dup = db.scalar(select(OrgTag).where(OrgTag.type == body.type, OrgTag.name == name))
    if dup:
        raise HTTPException(status_code=400, detail=f"{name} 已存在")
    tag = OrgTag(type=body.type, name=name, sort=body.sort)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag.to_dict()


@router.patch("/{tag_id}")
def update_org_tag(tag_id: int, body: OrgTagIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    tag = db.get(OrgTag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="条目不存在")
    if body.type not in ORG_TYPES:
        raise HTTPException(status_code=400, detail=f"type 必须是 {ORG_TYPES} 之一")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    dup = db.scalar(select(OrgTag).where(OrgTag.type == body.type, OrgTag.name == name, OrgTag.id != tag_id))
    if dup:
        raise HTTPException(status_code=400, detail=f"{name} 已存在")
    tag.type = body.type
    tag.name = name
    tag.sort = body.sort
    db.commit()
    db.refresh(tag)
    return tag.to_dict()


@router.delete("/{tag_id}")
def delete_org_tag(tag_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    tag = db.get(OrgTag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="条目不存在")
    db.delete(tag)
    db.commit()
    return {"ok": True}
