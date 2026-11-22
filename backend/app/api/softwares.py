"""软件列表 API（v2.11 软件管理页）：公司允许安装的软件目录。

登录即可读（员工建单申请安装软件时需选择）；管理员维护。

v2.12 来源结构化：source_type（软件官网/项目地址/三方网站）+ source_url（点击新标签页打开）；

支持按适用部门/适用岗位筛选（留空=全部部门的软件同样命中）。

"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, Field

from sqlalchemy import or_, select

from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin

from app.models.database import get_db

from app.models.ledger import SoftwareItem

from app.models.user import User

router = APIRouter()

class SoftwareIn(BaseModel):

    name: str = Field(min_length=1, max_length=128)

    category: str = "办公软件"

    license_type: str = "完全免费"

    description: str = ""

    departments: list[str] = []

    positions: list[str] = []

    source_type: str = "软件官网"  # 软件官网 / 项目地址 / 三方网站

    source_url: str = ""  # 来源地址，可点击跳转

    enabled: bool = True

def _validate(body: SoftwareIn) -> None:

    if body.license_type not in SoftwareItem.LICENSE_TYPES:

        raise HTTPException(status_code=400, detail=f"授权类型必须是 {SoftwareItem.LICENSE_TYPES} 之一")

    if body.source_type not in SoftwareItem.SOURCE_TYPES:

        raise HTTPException(status_code=400, detail=f"来源类型必须是 {SoftwareItem.SOURCE_TYPES} 之一")

    url = body.source_url.strip()

    if url and not url.startswith(("http://", "https://")):

        raise HTTPException(status_code=400, detail="来源地址需以 http:// 或 https:// 开头")

    if not body.name.strip():

        raise HTTPException(status_code=400, detail="软件名称不能为空")

def _apply(body: SoftwareIn, s: SoftwareItem) -> None:

    s.name = body.name.strip()

    s.category = body.category.strip() or "办公软件"

    s.license_type = body.license_type

    s.description = body.description.strip()

    s.departments = ",".join(d.strip() for d in body.departments if d.strip())

    s.positions = ",".join(p.strip() for p in body.positions if p.strip())

    s.source_type = body.source_type

    s.source_url = body.source_url.strip()

    s.enabled = body.enabled

def _match_tag(tags: list[str], value: str) -> bool:

    """适用部门/岗位过滤：软件未限定（空列表=全部）则命中；限定了则需包含所选值。"""

    return not tags or value in tags

@router.get("")

def list_softwares(

    q: str | None = None,

    category: str | None = None,

    license_type: str | None = None,

    dept: str | None = None,  # v2.12 适用部门筛选

    position: str | None = None,  # v2.12 适用岗位筛选

    db: Session = Depends(get_db),

    _: User = Depends(get_current_user),

):

    """软件目录列表：登录即可读；dept/position 过滤时「未限定部门/岗位」的软件同样命中。"""

    stmt = select(SoftwareItem).order_by(SoftwareItem.name)

    if q:

        like = f"%{q}%"

        stmt = stmt.where(

            or_(

                SoftwareItem.name.contains(like),

                SoftwareItem.description.contains(like),

                SoftwareItem.category.contains(like),

            )

        )

    if category:

        stmt = stmt.where(SoftwareItem.category == category)

    if license_type:

        stmt = stmt.where(SoftwareItem.license_type == license_type)

    rows = [s.to_dict() for s in db.scalars(stmt).all()]

    # 部门/岗位筛选在 Python 侧精确匹配逗号分隔标签（避免 LIKE 子串误配）

    if dept:

        rows = [r for r in rows if _match_tag(r["departments"], dept)]

    if position:

        rows = [r for r in rows if _match_tag(r["positions"], position)]

    # 下拉选项：组织字典为主，软件目录中出现的未收录标签并入

    from app.models.org import OrgTag

    org_depts = [t.name for t in db.scalars(select(OrgTag).where(OrgTag.type == "dept")).all()]

    org_positions = [t.name for t in db.scalars(select(OrgTag).where(OrgTag.type == "position")).all()]

    all_rows = [s.to_dict() for s in db.scalars(select(SoftwareItem)).all()]

    dept_options = sorted(set(org_depts) | {d for r in all_rows for d in r["departments"]})

    position_options = sorted(set(org_positions) | {p for r in all_rows for p in r["positions"]})

    categories = sorted({c for c in db.scalars(select(SoftwareItem.category)).all() if c})

    # 统计卡：总数 / 各授权类型数量（全量口径；last_updated 用 ISO 串可直接比较）

    by_type = {t: 0 for t in SoftwareItem.LICENSE_TYPES}

    last_updated = None

    for r in all_rows:

        if r["license_type"] in by_type:

            by_type[r["license_type"]] += 1

        if r["updated_at"] and (last_updated is None or r["updated_at"] > last_updated):

            last_updated = r["updated_at"]

    summary = {

        "total": len(all_rows),

        "by_license_type": by_type,

        "last_updated": last_updated,

    }

    return {

        "items": rows,

        "total": len(rows),

        "categories": categories,

        "dept_options": dept_options,

        "position_options": position_options,

        "summary": summary,

    }

@router.post("", status_code=201)

def create_software(body: SoftwareIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    _validate(body)

    dup = db.scalar(select(SoftwareItem).where(SoftwareItem.name == body.name.strip()))

    if dup:

        raise HTTPException(status_code=400, detail="该软件已在目录中")

    s = SoftwareItem()

    _apply(body, s)

    db.add(s)

    db.commit()

    db.refresh(s)

    return s.to_dict()

@router.patch("/{item_id}")

def update_software(item_id: int, body: SoftwareIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    s = db.get(SoftwareItem, item_id)

    if not s:

        raise HTTPException(status_code=404, detail="软件不存在")

    _validate(body)

    dup = db.scalar(select(SoftwareItem).where(SoftwareItem.name == body.name.strip(), SoftwareItem.id != item_id))

    if dup:

        raise HTTPException(status_code=400, detail="该软件已在目录中")

    _apply(body, s)

    db.commit()

    db.refresh(s)

    return s.to_dict()

@router.delete("/{item_id}")

def delete_software(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    s = db.get(SoftwareItem, item_id)

    if not s:

        raise HTTPException(status_code=404, detail="软件不存在")

    db.delete(s)

    db.commit()

    return {"ok": True}
