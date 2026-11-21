"""管理接口：SLA 规则、智能分派/值班表、工单模板、系统信息。"""
from __future__ import annotations

import json

import yaml

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.registry import registry
from app.core.config import get_config
from app.core.deps import require_admin, require_staff
from app.models.database import get_db
from app.models.system import DispatchRule, DutyRule, OutboxMessage, SlaRule, TicketTemplate
from app.models.ticket import PRIORITIES, Ticket
from app.models.user import User
from app.schemas.common import RuleIdsIn, SlaRuleIn, TemplateIn

router = APIRouter()


@router.get("/info")
def system_info(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cfg = get_config()
    ticket_count = db.scalar(select(Ticket.id).order_by(Ticket.id.desc()).limit(1))
    outbox = {
        "pending": db.scalar(select(OutboxMessage.id).where(OutboxMessage.status == "pending").limit(1)) is not None,
    }
    pending_count = len(list(db.scalars(select(OutboxMessage.id).where(OutboxMessage.status == OutboxMessage.STATUS_PENDING))))
    failed_count = len(list(db.scalars(select(OutboxMessage.id).where(OutboxMessage.status == OutboxMessage.STATUS_FAILED))))
    return {
        "app_name": cfg.app_name,
        "public_base_url": cfg.public_base_url,
        "database_url": cfg.resolved_database_url().split("///")[-1],
        "categories": cfg.categories,
        "channels": registry.meta() if registry.all() else _channel_meta_unconfigured(),
        "outbox": {"pending": pending_count, "failed": failed_count},
        "ticket_count": ticket_count or 0,
        "dispatch_auto_assign": cfg.dispatch.auto_assign,
        "work_hours": cfg.sla.work_hours,
        "report": {"enabled": cfg.report.enabled, "time": cfg.report.time, "group_webhook": bool(cfg.report.dingtalk_group_webhook)},
    }


def _channel_meta_unconfigured() -> list[dict]:
    return [
        {"name": "dingtalk", "display_name": "钉钉", "ready": False, "mode": "未启用"},
        {"name": "feishu", "display_name": "飞书", "ready": False, "mode": "未启用"},
        {"name": "wecom", "display_name": "企业微信", "ready": False, "mode": "未启用"},
    ]


@router.get("/sla")
def get_sla_rules(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rules = list(db.scalars(select(SlaRule).order_by(SlaRule.id)).all())
    return {"items": [r.to_dict() for r in rules]}


@router.put("/sla")
def update_sla_rules(rules: list[SlaRuleIn], db: Session = Depends(get_db), _: User = Depends(require_admin)):
    for r in rules:
        if r.priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail=f"无效的优先级: {r.priority}")
    for r in rules:
        rule = db.scalar(select(SlaRule).where(SlaRule.priority == r.priority))
        if rule:
            rule.response_minutes = r.response_minutes
            rule.resolve_minutes = r.resolve_minutes
        else:
            db.add(SlaRule(priority=r.priority, response_minutes=r.response_minutes, resolve_minutes=r.resolve_minutes))
    db.commit()
    return {"ok": True}


# ---- 智能分派规则 ----

@router.get("/dispatch-rules")
def list_dispatch_rules(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rules = list(db.scalars(select(DispatchRule).order_by(DispatchRule.id)).all())
    return {"items": [r.to_dict() for r in rules]}


@router.put("/dispatch-rules")
def upsert_dispatch_rule(body: RuleIdsIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if not body.category.strip():
        raise HTTPException(status_code=400, detail="分类不能为空")
    _validate_engineers(db, body.engineer_ids)
    rule = db.scalar(select(DispatchRule).where(DispatchRule.category == body.category.strip()))
    if rule:
        rule.engineer_ids = json.dumps(body.engineer_ids)
        rule.enabled = body.enabled
    else:
        db.add(DispatchRule(category=body.category.strip(), engineer_ids=json.dumps(body.engineer_ids), enabled=body.enabled))
    db.commit()
    return {"ok": True}


@router.delete("/dispatch-rules/{rule_id}")
def delete_dispatch_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rule = db.get(DispatchRule, rule_id)
    if rule:
        db.delete(rule)
        db.commit()
    return {"ok": True}


# ---- 值班表 ----

@router.get("/duty-rules")
def list_duty_rules(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rules = list(db.scalars(select(DutyRule).order_by(DutyRule.weekday)).all())
    return {"items": [r.to_dict() for r in rules]}


@router.put("/duty-rules")
def upsert_duty_rule(body: RuleIdsIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.weekday is None or not 0 <= body.weekday <= 6:
        raise HTTPException(status_code=400, detail="weekday 必须为 0-6（0=周一）")
    _validate_engineers(db, body.engineer_ids)
    rule = db.scalar(select(DutyRule).where(DutyRule.weekday == body.weekday))
    if rule:
        rule.engineer_ids = json.dumps(body.engineer_ids)
    else:
        db.add(DutyRule(weekday=body.weekday, engineer_ids=json.dumps(body.engineer_ids)))
    db.commit()
    return {"ok": True}


# ---- 工单模板 ----

@router.get("/templates")
def list_templates(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    ts = list(db.scalars(select(TicketTemplate).order_by(TicketTemplate.id)).all())
    return {"items": [t.to_dict() for t in ts]}


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _validate_template(body)
    t = TicketTemplate(
        name=body.name.strip(),
        category=body.category.strip(),
        priority=body.priority if body.priority in PRIORITIES else "medium",
        fields=json.dumps([f.model_dump() for f in body.fields], ensure_ascii=False),
        enabled=body.enabled,
        require_approval=body.require_approval,
        ad_script=body.ad_script.strip(),
        estimated_minutes=body.estimated_minutes,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t.to_dict()


@router.patch("/templates/{template_id}")
def update_template(template_id: int, body: TemplateIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    t = db.get(TicketTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    _validate_template(body)
    t.name = body.name.strip()
    t.category = body.category.strip()
    t.priority = body.priority if body.priority in PRIORITIES else "medium"
    t.fields = json.dumps([f.model_dump() for f in body.fields], ensure_ascii=False)
    t.enabled = body.enabled
    t.require_approval = body.require_approval
    t.ad_script = body.ad_script.strip()
    t.estimated_minutes = body.estimated_minutes
    db.commit()
    db.refresh(t)
    return t.to_dict()


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    t = db.get(TicketTemplate, template_id)
    if t:
        db.delete(t)
        db.commit()
    return {"ok": True}


def _validate_engineers(db: Session, ids: list[int]) -> None:
    for i in ids:
        u = db.get(User, i)
        if not u or u.role not in ("admin", "engineer") or not u.is_active:
            raise HTTPException(status_code=400, detail=f"用户 {i} 不是有效的在职工程师/管理员")


def _validate_template(body: TemplateIn) -> None:
    seen: set[str] = set()
    for f in body.fields:
        if not f.key.strip() or not f.label.strip():
            raise HTTPException(status_code=400, detail="模板字段 key/label 不能为空")
        if f.type not in ("text", "textarea", "select"):
            raise HTTPException(status_code=400, detail=f"不支持的字段类型: {f.type}")
        if f.type == "select" and not f.options:
            raise HTTPException(status_code=400, detail="select 字段必须提供 options")
        if f.key in seen:
            raise HTTPException(status_code=400, detail=f"字段 key 重复: {f.key}")
        seen.add(f.key)


# ---- 邮件推送配置（v2.10，仅管理员） ----

import os as _os
import smtplib
from email.header import Header as _MailHeader
from email.mime.text import MIMEText as _MIMEText


@router.get("/mail-config")
def get_mail_config(_: User = Depends(require_admin)):
    cfg = get_config().mail
    return {
        "enabled": cfg.enabled,
        "smtp_host": cfg.smtp_host,
        "smtp_port": cfg.smtp_port,
        "username": cfg.username,
        "has_password": bool(cfg.password),
        "use_tls": cfg.use_tls,
        "from_addr": cfg.from_addr,
    }


class MailConfigIn(BaseModel):
    """邮件推送配置请求体。"""

    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    username: str = ""
    password: str = ""  # 留空 = 保留原密码
    use_tls: bool = True
    from_addr: str = ""


@router.put("/mail-config")
def update_mail_config(body: MailConfigIn, _: User = Depends(require_admin)):
    """更新邮件推送配置：热更新内存。密码留空则保留原值。"""
    cfg = get_config()
    mail = cfg.mail
    mail.enabled = body.enabled
    mail.smtp_host = body.smtp_host
    mail.smtp_port = body.smtp_port
    mail.username = body.username
    if body.password:
        mail.password = body.password
    mail.use_tls = body.use_tls
    mail.from_addr = body.from_addr
    return {"ok": True, "enabled": body.enabled}


@router.post("/mail-config/test")
def send_mail_test(_: User = Depends(require_admin)):
    """发送一封测试邮件验证 SMTP 配置。"""
    cfg = get_config().mail
    if not cfg.enabled or not cfg.smtp_host:
        raise HTTPException(status_code=400, detail="邮件推送未启用或未配置 SMTP 服务器")
    try:
        msg = _MIMEText("这是一封来自 YiDesk 的测试邮件。\n\n如果您收到此邮件，说明 SMTP 配置正确。", "plain", "utf-8")
        msg["Subject"] = _MailHeader("YiDesk — 测试邮件", "utf-8")
        msg["From"] = str(_MailHeader("YiDesk", "utf-8")) + f" <{cfg.from_addr}>"
        msg["To"] = cfg.from_addr

        if cfg.use_tls:
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10)
            server.starttls()
        try:
            server.login(cfg.username, cfg.password)
            server.sendmail(cfg.from_addr, [cfg.from_addr], msg.as_string())
        finally:
            server.quit()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"发送失败：{exc}") from exc


# 后台访问安全密钥已改为每账号一枚（见 /api/users/{id}/gate-key*），全局配置版接口移除；
# 旧版 config.yaml 全局密钥由 /gate/{key} 首次访问时自动迁移给 admin 账号。
