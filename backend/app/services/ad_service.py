"""AD 域操作联动（v2.2）：审批通过的工单生成 AD 任务，由域内代理机执行并回写结果。

架构与「终端合规巡检」代理一致：服务端只负责「生成任务 / 校验令牌 / 记录结果」，
真正的 PowerShell 执行发生在域内代理机（scripts/AdJobRunner.ps1 拉取-执行-回传），
服务端不做任何进程执行（无命令注入面；域操作也只在装有 AD 模块的域内机器上有意义）。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.core.config import get_config
from app.models.system import AdJob, TicketTemplate
from app.models.ticket import Ticket, TicketEvent
from app.models.user import User, utcnow


def enqueue_for_ticket(db, *, ticket: Ticket, template: TicketTemplate) -> bool:
    """审批通过后按模板配置生成 AD 任务；返回是否生成了任务。

    模板需配置 ad_script（名称，限授权目录内的 .ps1）；任务由代理机执行。
    """
    if not template.ad_script:
        return False
    job = AdJob(
        ticket_id=ticket.id,
        script=template.ad_script,
        payload=json.dumps(
            {
                "ticket_no": ticket.no,
                "title": ticket.title,
                "custom_fields": json.loads(ticket.custom_fields or "{}"),
            },
            ensure_ascii=False,
        ),
    )
    db.add(job)
    db.add(TicketEvent(
        ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
        content=f"AD 联动：已生成执行任务（脚本 {template.ad_script}），等待域内代理执行",
    ))
    db.commit()
    return True


def pending_jobs(db, limit: int = 10) -> list[AdJob]:
    """代理拉取待执行任务（调用方先校验令牌）；取走即标记 running。"""
    jobs = list(db.scalars(select(AdJob).where(AdJob.status == "pending").order_by(AdJob.id).limit(limit)))
    for j in jobs:
        j.status = "running"
    db.commit()
    return jobs


def record_result(db, *, job: AdJob, success: bool, output: str) -> None:
    """代理回写结果：落任务状态并写工单事件（输出截断入库）。"""
    job.status = "done" if success else "failed"
    job.result = (output or "")[:2000]
    db.add(TicketEvent(
        ticket_id=job.ticket_id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
        content=("AD 联动执行成功：" if success else "AD 联动执行失败：") + (output or "")[:800],
    ))
    db.commit()


def verify_agent_token(token: str) -> bool:
    """代理机鉴权：优先 ad_integration.api_key，缺省复用合规巡检的 X-API-Token。"""
    if not token:
        return False
    cfg = get_config()
    expected = cfg.ad_integration.api_key or cfg.compliance.agent_api_key
    return bool(expected) and token == expected
