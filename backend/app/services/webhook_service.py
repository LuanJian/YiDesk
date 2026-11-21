"""Webhook 事件订阅服务（v2.2）：事件落库 → 带签名投递 → 失败重试。

安全：目标 URL 仅允许 https；默认拒绝私网/环回地址（SSRF，防 DNS rebinding 用
httpx 请求钩子在每一跳校验）；投递带 HMAC-SHA256 签名头供外部系统验签。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import socket
from urllib.parse import urlparse

import httpx
import ipaddress
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.models.user import utcnow
from app.models.webhook import WEBHOOK_EVENTS, ApiKey, WebhookDelivery, WebhookSubscription

logger = logging.getLogger("services.webhook")

MAX_ATTEMPTS = 5
TIMEOUT = 10


# ---- 订阅管理 ----

def assert_safe_url(url: str) -> None:
    """订阅 URL 基本校验：https + 非私网解析（私网放行需 config.webhook.allow_private_network）。"""
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        raise ValueError("Webhook 地址必须是 https://")
    if get_config().webhook.allow_private_network:
        return
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443)
    except OSError as exc:
        raise ValueError(f"域名解析失败：{p.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"{p.hostname} 解析到内网地址 {ip}，已拒绝（如需内网对接请开启 webhook.allow_private_network）")


def create_subscription(db: Session, *, url: str, secret: str, events: list[str]) -> WebhookSubscription:
    assert_safe_url(url)
    bad = [e for e in events if e not in WEBHOOK_EVENTS]
    if bad:
        raise ValueError(f"不支持的事件类型：{bad}（可选 {WEBHOOK_EVENTS}）")
    if not events:
        events = list(WEBHOOK_EVENTS)
    sub = WebhookSubscription(url=url.strip(), secret=secret.strip(), events=json.dumps(events))
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def verify_api_key(db: Session, key: str) -> bool:
    """开放 API 鉴权：SHA-256 摘要比对（未启用/未知 key 一律拒绝）。"""
    if not key:
        return False
    digest = hashlib.sha256(key.encode()).hexdigest()
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.enabled.is_(True)))
    return row is not None


def new_api_key(db: Session, name: str) -> tuple[ApiKey, str]:
    """生成 API Key：明文仅本次返回，库存 SHA-256 摘要。"""
    import secrets

    plaintext = "itops_" + secrets.token_urlsafe(32)
    row = ApiKey(name=name.strip() or "未命名", key_hash=hashlib.sha256(plaintext.encode()).hexdigest())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plaintext


# ---- 事件发射 ----

def emit_event(db: Session, event: str, ticket, only_subscription_id: int | None = None) -> None:
    """工单事件 → 为每个订阅该事件的启用订阅生成一条投递任务（落库待发）。

    only_subscription_id 用于「测试投递」只发指定订阅，不影响其他订阅方。
    """
    if event not in WEBHOOK_EVENTS:
        return
    stmt = select(WebhookSubscription).where(WebhookSubscription.enabled.is_(True))
    if only_subscription_id:
        stmt = stmt.where(WebhookSubscription.id == only_subscription_id)
    subs = list(db.scalars(stmt))
    payload = json.dumps(
        {
            "event": event,
            "timestamp": utcnow().isoformat() + "Z",
            "ticket": ticket.to_dict(),
        },
        ensure_ascii=False,
        default=str,
    )
    for sub in subs:
        if event not in sub.events_list:
            continue
        db.add(WebhookDelivery(subscription_id=sub.id, event=event, ticket_id=ticket.id, payload=payload))
    db.commit()


# ---- 投递 ----

def _guard_private_hop(request: httpx.Request) -> None:
    """每个跳转 hop 校验解析 IP（允许私网时跳过；防 DNS rebinding）。"""
    if get_config().webhook.allow_private_network:
        return
    u = urlparse(str(request.url))
    host = u.hostname or ""
    try:
        infos = socket.getaddrinfo(host, u.port or 443)
    except OSError as exc:
        raise httpx.RequestError(f"resolve failed {host}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise httpx.RequestError(f"SSRF guard: {host} resolved to non-public address {ip}")


def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, event_hooks={"request": [_guard_private_hop]}, timeout=TIMEOUT)


def flush(db: Session, limit: int = 50) -> int:
    """投递 pending 任务，返回成功条数；失败重试至 MAX_ATTEMPTS 后标记失败。"""
    rows = list(
        db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.status == WebhookDelivery.STATUS_PENDING, WebhookDelivery.attempts < MAX_ATTEMPTS)
            .order_by(WebhookDelivery.id)
            .limit(limit)
        )
    )
    ok = 0
    for d in rows:
        sub = db.get(WebhookSubscription, d.subscription_id)
        if not sub or not sub.enabled:
            continue  # 订阅被删/停用：保留任务，待订阅恢复或人工处理
        d.attempts += 1
        body = d.payload.encode()
        sign = hmac.new(sub.secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            with _client() as client:
                resp = client.post(
                    sub.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-ITOps-Event": d.event,
                        "X-ITOps-Signature": f"sha256={sign}",
                        "X-ITOps-Delivery": str(d.id),
                    },
                )
                resp.raise_for_status()
            d.status = WebhookDelivery.STATUS_SENT
            d.sent_at = utcnow()
            d.last_error = ""
            ok += 1
        except Exception as exc:  # noqa: BLE001 记录后继续
            d.last_error = f"{type(exc).__name__}: {exc}"[:500]
            if d.attempts >= MAX_ATTEMPTS:
                d.status = WebhookDelivery.STATUS_FAILED
            logger.warning("webhook 投递失败 #%s %s: %s", d.id, sub.url, d.last_error)
    db.commit()
    return ok
