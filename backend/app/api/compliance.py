"""终端合规巡检 API：巡检项配置、批次创建、人工登记、代理脚本上报、汇总与整改建单。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from pydantic import BaseModel, Field

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.config import get_config

from app.core.deps import get_current_user, require_admin

from app.core.permissions import require_perm

from app.models.database import get_db

from app.models.knowledge import Asset

from app.models.ledger import ComplianceItem, ComplianceRecord, ComplianceScan

from app.models.user import User

from app.services import ledger_service, ticket_service

router = APIRouter()

DEFAULT_ITEMS = [

    {"key": "antivirus", "name": "杀毒软件已安装且病毒库 7 天内更新", "category": "杀毒", "method": "agent", "severity": "高"},

    {"key": "patch", "name": "系统补丁 60 天内更新", "category": "补丁", "method": "agent", "severity": "中"},

    {"key": "bitlocker", "name": "系统盘 BitLocker 加密", "category": "安全基线", "method": "agent", "severity": "高"},

    {"key": "screen_lock", "name": "屏保 10 分钟内自动锁定", "category": "配置", "method": "manual", "severity": "低"},

    {"key": "illegal_software", "name": "无未授权/盗版软件", "category": "软件", "method": "manual", "severity": "高"},

]

def _seed_items(db: Session) -> None:

    if db.scalar(select(ComplianceItem).limit(1)) is None:

        for it in DEFAULT_ITEMS:

            db.add(ComplianceItem(**it))

        db.commit()

@router.get("/items")

def list_items(db: Session = Depends(get_db), _: User = Depends(require_perm("compliance"))):

    _seed_items(db)

    items = list(db.scalars(select(ComplianceItem).order_by(ComplianceItem.id)).all())

    return {"items": [i.to_dict() for i in items], "total": len(items)}

class ItemIn(BaseModel):

    key: str = Field(min_length=1, max_length=64)

    name: str = Field(min_length=1, max_length=128)

    category: str = "安全基线"

    method: str = "agent"

    severity: str = "中"

    description: str = ""

    enabled: bool = True

@router.post("/items", status_code=201)

def create_item(body: ItemIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    if db.scalar(select(ComplianceItem).where(ComplianceItem.key == body.key)):

        raise HTTPException(status_code=400, detail="巡检项 key 已存在")

    if body.method not in ("agent", "manual"):

        raise HTTPException(status_code=400, detail="method 必须为 agent/manual")

    item = ComplianceItem(**body.model_dump())

    db.add(item)

    db.commit()

    db.refresh(item)

    return item.to_dict()

@router.patch("/items/{item_id}")

def update_item(item_id: int, body: ItemIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    item = db.get(ComplianceItem, item_id)

    if not item:

        raise HTTPException(status_code=404, detail="巡检项不存在")

    for field, val in body.model_dump().items():

        setattr(item, field, val)

    db.commit()

    db.refresh(item)

    return item.to_dict()

@router.delete("/items/{item_id}")

def delete_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    item = db.get(ComplianceItem, item_id)

    if item:

        db.delete(item)

        db.commit()

    return {"ok": True}

# ---- 批次 ----

class ScanIn(BaseModel):

    name: str = Field(min_length=1, max_length=128)

    scope_note: str = ""

    asset_ids: list[int] = []

@router.post("/scans", status_code=201)

def create_scan(body: ScanIn, db: Session = Depends(get_db), user: User = Depends(require_perm("compliance"))):

    scan = ComplianceScan(name=body.name.strip(), scope_note=body.scope_note.strip(), created_by_id=user.id)

    db.add(scan)

    db.commit()

    db.refresh(scan)

    return scan.to_dict()

@router.get("/scans")

def list_scans(db: Session = Depends(get_db), _: User = Depends(require_perm("compliance"))):

    scans = list(db.scalars(select(ComplianceScan).order_by(ComplianceScan.id.desc())).all())

    return {"items": [s.to_dict() for s in scans], "total": len(scans)}

# ---- 记录 ----

@router.get("/records")

def list_records(

    asset_id: int | None = None,

    item_id: int | None = None,

    scan_id: int | None = None,

    result: str | None = None,

    db: Session = Depends(get_db),

    _: User = Depends(require_perm("compliance")),

):

    stmt = select(ComplianceRecord).order_by(ComplianceRecord.id.desc())

    if asset_id:

        stmt = stmt.where(ComplianceRecord.asset_id == asset_id)

    if item_id:

        stmt = stmt.where(ComplianceRecord.item_id == item_id)

    if scan_id:

        stmt = stmt.where(ComplianceRecord.scan_id == scan_id)

    if result:

        stmt = stmt.where(ComplianceRecord.result == result)

    records = list(db.scalars(stmt).all())

    return {"items": [r.to_dict() for r in records], "total": len(records)}

class ManualRecordIn(BaseModel):

    asset_id: int

    item_id: int

    result: str

    detail: str = ""

    scan_id: int | None = None

@router.post("/records/manual", status_code=201)

def add_manual_record(body: ManualRecordIn, db: Session = Depends(get_db), user: User = Depends(require_perm("compliance"))):

    if body.result not in ("合规", "不合规", "未检"):

        raise HTTPException(status_code=400, detail="result 必须为 合规/不合规/未检")

    if not db.get(Asset, body.asset_id):

        raise HTTPException(status_code=404, detail="终端（资产）不存在")

    if not db.get(ComplianceItem, body.item_id):

        raise HTTPException(status_code=404, detail="巡检项不存在")

    rec = ComplianceRecord(

        asset_id=body.asset_id, item_id=body.item_id, scan_id=body.scan_id,

        result=body.result, detail=body.detail, checked_by=user.username,

    )

    db.add(rec)

    db.commit()

    db.refresh(rec)

    return rec.to_dict()

# ---- 代理脚本上报（X-API-Token 鉴权） ----

class AgentResultIn(BaseModel):

    key: str

    result: str

    detail: str = ""

class AgentReportIn(BaseModel):

    asset_tag: str = Field(min_length=1)

    scan_id: int | None = None

    results: list[AgentResultIn] = Field(min_length=1)

@router.post("/agent-report")

def agent_report(

    body: AgentReportIn,

    x_api_token: str = Header(default=""),

    db: Session = Depends(get_db),

):

    api_key = get_config().compliance.agent_api_key

    if not api_key:

        raise HTTPException(status_code=403, detail="未配置 compliance.agent_api_key，代理上报已禁用")

    if x_api_token != api_key:

        raise HTTPException(status_code=401, detail="API Token 无效")

    asset = db.scalar(select(Asset).where(Asset.asset_tag == body.asset_tag.strip()))

    if not asset:

        raise HTTPException(status_code=404, detail=f"终端资产 {body.asset_tag} 未登记，请先在资产管理中登记")

    count = ledger_service.upsert_agent_records(db, asset, [r.model_dump() for r in body.results], body.scan_id)

    return {"ok": True, "asset_tag": asset.asset_tag, "accepted": count}

# ---- 汇总与整改建单 ----

@router.get("/summary")

def summary(db: Session = Depends(get_db), _: User = Depends(require_perm("compliance"))):

    return ledger_service.compliance_summary(db)

class RemediationIn(BaseModel):

    asset_id: int

    record_ids: list[int] = Field(min_length=1)

@router.post("/remediation-ticket", status_code=201)

def remediation_ticket(body: RemediationIn, db: Session = Depends(get_db), user: User = Depends(require_perm("compliance"))):

    asset = db.get(Asset, body.asset_id)

    if not asset:

        raise HTTPException(status_code=404, detail="终端（资产）不存在")

    records = [db.get(ComplianceRecord, rid) for rid in body.record_ids]

    records = [r for r in records if r and r.asset_id == asset.id]

    if not records:

        raise HTTPException(status_code=400, detail="没有有效的巡检记录")

    items_info = []

    for r in records:

        item = db.get(ComplianceItem, r.item_id)

        if item:

            items_info.append(f"- [{item.severity}] {item.name}：{r.detail or '不合规'}")

    ticket = ticket_service.create_ticket(

        db, creator=user,

        title=f"合规整改：{asset.asset_tag} {asset.name}",

        description="以下巡检项不合规，请处理：\n" + "\n".join(items_info),

        category="安全合规", priority="high", asset_id=asset.id, channel="web",

    )

    return ticket.to_dict()
