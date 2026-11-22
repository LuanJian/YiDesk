"""派单引擎 v2 API（v2.7，仅管理员）：关键词规则库 + 组织架构路由 + 部门/严格值班配置。"""

from __future__ import annotations

import json as _json

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, Field

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.deps import require_admin

from app.models.database import get_db

from app.models.system import DeptRoute, DispatchRule, KeywordRule

from app.models.user import User

router = APIRouter()

class KeywordRuleIn(BaseModel):

    name: str = Field(default="", max_length=64)

    keywords: list[str] = Field(min_length=1)

    target_engineer_id: int | None = None

    target_category: str | None = None

    priority: int = 100

    enabled: bool = True

    note: str = ""

class DeptRouteIn(BaseModel):

    department: str = Field(min_length=1, max_length=64)

    engineer_ids: list[int] = Field(min_length=1)

    enabled: bool = True

def _kr_dict(db: Session, r: KeywordRule) -> dict:

    d = r.to_dict()

    if r.target_engineer_id:

        u = db.get(User, r.target_engineer_id)

        d["target_engineer_name"] = (u.name or u.username) if u else None

    return d

def _validate_kr(db: Session, body: KeywordRuleIn) -> None:

    if not [k for k in (kw.strip() for kw in body.keywords) if k]:

        raise HTTPException(status_code=400, detail="关键词不能为空")

    if not body.target_engineer_id and not body.target_category:

        raise HTTPException(status_code=400, detail="必须指定目标工程师或目标分类（二选一）")

    if body.target_engineer_id:

        u = db.get(User, body.target_engineer_id)

        if not u or u.role not in ("admin", "engineer"):

            raise HTTPException(status_code=400, detail="目标工程师不存在或非 IT 侧人员")

    from app.core.config import get_config

    if body.target_category and body.target_category not in get_config().categories:

        raise HTTPException(status_code=400, detail="目标分类不在系统分类列表中")

@router.get("/keyword-rules")

def list_keyword_rules(db: Session = Depends(get_db), _: User = Depends(require_admin)):

    rows = list(db.scalars(select(KeywordRule).order_by(KeywordRule.priority, KeywordRule.id)))

    return {"items": [_kr_dict(db, r) for r in rows]}

@router.post("/keyword-rules", status_code=201)

def create_keyword_rule(body: KeywordRuleIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    _validate_kr(db, body)

    rule = KeywordRule(

        name=body.name.strip(),

        keywords=",".join(k.strip() for k in body.keywords if k.strip()),

        target_engineer_id=body.target_engineer_id,

        target_category=body.target_category or "",

        priority=body.priority,

        enabled=body.enabled,

        note=body.note.strip(),

    )

    db.add(rule)

    db.commit()

    db.refresh(rule)

    return _kr_dict(db, rule)

@router.patch("/keyword-rules/{rule_id}")

def update_keyword_rule(rule_id: int, body: KeywordRuleIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    rule = db.get(KeywordRule, rule_id)

    if not rule:

        raise HTTPException(status_code=404, detail="规则不存在")

    _validate_kr(db, body)

    rule.name = body.name.strip()

    rule.keywords = ",".join(k.strip() for k in body.keywords if k.strip())

    rule.target_engineer_id = body.target_engineer_id

    rule.target_category = body.target_category or ""

    rule.priority = body.priority

    rule.enabled = body.enabled

    rule.note = body.note.strip()

    db.commit()

    db.refresh(rule)

    return _kr_dict(db, rule)

@router.delete("/keyword-rules/{rule_id}")

def delete_keyword_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    rule = db.get(KeywordRule, rule_id)

    if not rule:

        raise HTTPException(status_code=404, detail="规则不存在")

    db.delete(rule)

    db.commit()

    return {"ok": True}

# ---- 分类分派规则·工程师视角（v2.11）：选工程师勾选其负责的分类，同步到底层 DispatchRule ----

class EngineerCategoriesIn(BaseModel):

    engineer_id: int

    categories: list[str] = Field(default_factory=list)  # 勾选的分类；空列表 = 该工程师不接任何分类

@router.put("/category-rules")

def set_engineer_categories(body: EngineerCategoriesIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    """把某工程师勾选的分类同步到分类规则库：勾选=加入该分类轮询池（规则自动启用），取消=移出（池空则删规则）。"""

    from app.core.config import get_config

    eng = db.get(User, body.engineer_id)

    if not eng or eng.role not in ("admin", "engineer") or not eng.is_active:

        raise HTTPException(status_code=400, detail="目标不是有效的在职工程师/管理员")

    cats = [c.strip() for c in body.categories if c.strip()]

    valid = set(get_config().categories)

    unknown = [c for c in cats if c not in valid]

    if unknown:

        raise HTTPException(status_code=400, detail=f"分类不存在: {', '.join(unknown)}")

    if len(cats) != len(set(cats)):

        raise HTTPException(status_code=400, detail="分类不能重复")

    rules = list(db.scalars(select(DispatchRule)).all())

    for cat in cats:

        rule = next((r for r in rules if r.category == cat), None)

        if rule:

            ids = _json.loads(rule.engineer_ids)

            if body.engineer_id not in ids:

                ids.append(body.engineer_id)

                rule.engineer_ids = _json.dumps(ids)

            rule.enabled = True  # 勾选即启用该分类的自动分派

        else:

            db.add(DispatchRule(category=cat, engineer_ids=_json.dumps([body.engineer_id]), enabled=True))

    for rule in rules:

        if rule.category in cats:

            continue

        ids = _json.loads(rule.engineer_ids)

        if body.engineer_id in ids:

            ids.remove(body.engineer_id)

            if ids:

                rule.engineer_ids = _json.dumps(ids)

            else:

                db.delete(rule)  # 没有工程师负责的分类规则不再保留

    db.commit()

    return {"ok": True, "engineer_id": body.engineer_id, "categories": cats}

# ---- 组织架构路由（部门 → 工程师池） ----

def _validate_route(db: Session, body: DeptRouteIn) -> None:

    if not body.department.strip():

        raise HTTPException(status_code=400, detail="部门不能为空")

@router.get("/dept-routes")

def list_dept_routes(db: Session = Depends(get_db), _: User = Depends(require_admin)):

    rows = list(db.scalars(select(DeptRoute).order_by(DeptRoute.id)))

    return {"items": [r.to_dict() for r in rows]}

@router.post("/dept-routes", status_code=201)

def create_dept_route(body: DeptRouteIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    _validate_route(db, body)

    exists = db.scalar(select(DeptRoute).where(DeptRoute.department == body.department.strip()))

    if exists:

        raise HTTPException(status_code=400, detail="该部门已有路由，请直接编辑")

    ids = [i for i in body.engineer_ids if db.get(User, i) and db.get(User, i).role in ("admin", "engineer")]

    if not ids:

        raise HTTPException(status_code=400, detail="至少选择一名有效工程师")

    import json as _json

    route = DeptRoute(department=body.department.strip(), engineer_ids=_json.dumps(ids), enabled=body.enabled)

    db.add(route)

    db.commit()

    db.refresh(route)

    return route.to_dict()

@router.patch("/dept-routes/{route_id}")

def update_dept_route(route_id: int, body: DeptRouteIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    route = db.get(DeptRoute, route_id)

    if not route:

        raise HTTPException(status_code=404, detail="路由不存在")

    ids = [i for i in body.engineer_ids if db.get(User, i) and db.get(User, i).role in ("admin", "engineer")]

    if not ids:

        raise HTTPException(status_code=400, detail="至少选择一名有效工程师")

    import json as _json

    route.engineer_ids = _json.dumps(ids)

    route.enabled = body.enabled

    db.commit()

    db.refresh(route)

    return route.to_dict()

@router.delete("/dept-routes/{route_id}")

def delete_dept_route(route_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    route = db.get(DeptRoute, route_id)

    if not route:

        raise HTTPException(status_code=404, detail="路由不存在")

    db.delete(route)

    db.commit()

    return {"ok": True}
