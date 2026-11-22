"""开放平台 API（v2.2）：

- /api/webhooks：Webhook 订阅管理（admin）+ 投递记录 + 测试投递

- /api/admin/api-keys：只读开放 API 的 Key 管理（明文仅创建时返回一次）

- /api/open/tickets：X-API-Key 鉴权的只读工单拉取（ITSM/CRM 对接）

- /api/ad/jobs：AD 联动任务的域内代理拉取/回传（X-API-Token）

"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin

from app.models.database import get_db

from app.models.system import AdJob

from app.models.ticket import STATUS_LABELS, Ticket

from app.models.user import User

from app.models.webhook import ApiKey, WebhookDelivery, WebhookSubscription

from app.schemas.common import AdJobResultIn, ApiKeyIn, WebhookIn, WebhookUpdateIn

from app.services import ad_service, webhook_service

router = APIRouter()        # 挂载 /api/webhooks

open_router = APIRouter()   # 挂载 /api/open

ad_router = APIRouter()     # 挂载 /api/ad

# ---- Webhook 订阅管理（admin） ----

@router.get("")

def list_webhooks(db: Session = Depends(get_db), _: User = Depends(require_admin)):

    items = list(db.scalars(select(WebhookSubscription).order_by(WebhookSubscription.id.desc())))

    return {"items": [s.to_dict() for s in items]}

@router.post("", status_code=201)

def create_webhook(body: WebhookIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    try:

        sub = webhook_service.create_subscription(db, url=body.url, secret=body.secret, events=body.events)

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return sub.to_dict()

@router.patch("/{sub_id}")

def update_webhook(sub_id: int, body: WebhookUpdateIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    sub = db.get(WebhookSubscription, sub_id)

    if not sub:

        raise HTTPException(status_code=404, detail="订阅不存在")

    if body.url is not None:

        try:

            webhook_service.assert_safe_url(body.url)

        except ValueError as exc:

            raise HTTPException(status_code=400, detail=str(exc)) from exc

        sub.url = body.url.strip()

    if body.secret is not None:

        sub.secret = body.secret.strip()

    if body.events is not None:

        bad = [e for e in body.events if e not in webhook_service.WEBHOOK_EVENTS]

        if bad:

            raise HTTPException(status_code=400, detail=f"不支持的事件：{bad}")

        sub.events = json.dumps(body.events or webhook_service.WEBHOOK_EVENTS)

    if body.enabled is not None:

        sub.enabled = body.enabled

    db.commit()

    db.refresh(sub)

    return sub.to_dict()

@router.delete("/{sub_id}")

def delete_webhook(sub_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    sub = db.get(WebhookSubscription, sub_id)

    if not sub:

        raise HTTPException(status_code=404, detail="订阅不存在")

    db.delete(sub)

    db.commit()

    return {"ok": True}

@router.post("/{sub_id}/test")

async def test_webhook(sub_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    """用最近一张工单触发一次测试投递（pending → flush 立即尝试）。"""

    sub = db.get(WebhookSubscription, sub_id)

    if not sub:

        raise HTTPException(status_code=404, detail="订阅不存在")

    ticket = db.scalar(select(Ticket).order_by(Ticket.id.desc()).limit(1))

    if not ticket:

        raise HTTPException(status_code=400, detail="系统中还没有工单，无法测试")

    # 仅向该订阅发一条测试投递（ticket.updated 或其订阅列表里的第一个事件）

    event = "ticket.updated" if "ticket.updated" in sub.events_list else (sub.events_list[0] if sub.events_list else "ticket.updated")

    webhook_service.emit_event(db, event, ticket, only_subscription_id=sub.id)

    d = db.scalar(

        select(WebhookDelivery)

        .where(WebhookDelivery.subscription_id == sub_id, WebhookDelivery.status == "pending")

        .order_by(WebhookDelivery.id.desc())

        .limit(1)

    )

    sent = await _flush_now(db)

    return {"ok": True, "delivery_id": d.id if d else None, "sent": sent, "event": event}

async def _flush_now(db: Session) -> int:

    from fastapi.concurrency import run_in_threadpool

    return await run_in_threadpool(webhook_service.flush, db)

@router.get("/{sub_id}/deliveries")

def webhook_deliveries(sub_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    rows = list(

        db.scalars(

            select(WebhookDelivery)

            .where(WebhookDelivery.subscription_id == sub_id)

            .order_by(WebhookDelivery.id.desc())

            .limit(20)

        )

    )

    return {"items": [d.to_dict() for d in rows]}

# ---- API Key 管理（admin） ----

@router.get("/api-keys")

def list_api_keys(db: Session = Depends(get_db), _: User = Depends(require_admin)):

    items = list(db.scalars(select(ApiKey).order_by(ApiKey.id.desc())))

    return {"items": [k.to_dict() for k in items]}

@router.post("/api-keys", status_code=201)

def create_api_key(body: ApiKeyIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    key, plaintext = webhook_service.new_api_key(db, body.name)

    d = key.to_dict()

    d["key"] = plaintext  # 明文仅此一次返回

    return d

@router.delete("/api-keys/{key_id}")

def delete_api_key(key_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    row = db.get(ApiKey, key_id)

    if not row:

        raise HTTPException(status_code=404, detail="Key 不存在")

    db.delete(row)

    db.commit()

    return {"ok": True}

# ---- 只读开放 API（X-API-Key） ----

@open_router.get("/tickets")

def open_tickets(

    x_api_key: str = Header(default=""),

    status: str | None = None,

    category: str | None = None,

    page: int = 1,

    page_size: int = 50,

    db: Session = Depends(get_db),

):

    """ITSM/CRM 只读拉取：X-API-Key 鉴权；仅返回工单基础与状态字段。"""

    if not webhook_service.verify_api_key(db, x_api_key):

        raise HTTPException(status_code=401, detail="无效的 API Key")

    stmt = select(Ticket).order_by(Ticket.id.desc())

    if status:

        stmt = stmt.where(Ticket.status == status)

    if category:

        stmt = stmt.where(Ticket.category == category)

    rows = list(db.scalars(stmt.limit(min(page_size, 200)).offset((max(page, 1) - 1) * min(page_size, 200))))

    return {

        "items": [

            {

                "no": t.no, "title": t.title, "category": t.category, "priority": t.priority,

                "status": t.status, "status_label": STATUS_LABELS.get(t.status, t.status),

                "created_at": t.created_at.isoformat() + "Z",

                "resolved_at": t.resolved_at.isoformat() + "Z" if t.resolved_at else None,

                "closed_at": t.closed_at.isoformat() + "Z" if t.closed_at else None,

            }

            for t in rows

        ]

    }

# ---- AD 联动任务（X-API-Token，域内代理机调用） ----

@ad_router.get("/jobs/pending")

def ad_pending_jobs(x_api_token: str = Header(default=""), db: Session = Depends(get_db)):

    if not ad_service.verify_agent_token(x_api_token):

        raise HTTPException(status_code=401, detail="无效的代理令牌")

    jobs = ad_service.pending_jobs(db)

    return {"items": [j.to_dict() for j in jobs]}

@ad_router.post("/jobs/{job_id}/result")

def ad_job_result(

    job_id: int,

    body: AdJobResultIn,

    x_api_token: str = Header(default=""),

    db: Session = Depends(get_db),

):

    if not ad_service.verify_agent_token(x_api_token):

        raise HTTPException(status_code=401, detail="无效的代理令牌")

    job = db.get(AdJob, job_id)

    if not job:

        raise HTTPException(status_code=404, detail="任务不存在")

    ad_service.record_result(db, job=job, success=body.success, output=body.output)

    return {"ok": True}
