"""二维码报修服务：标签解析、建单自动填充与指定派单、未结工单与排队位次。"""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import Asset
from app.models.qr import QrTag
from app.models.ticket import STATUS_LABELS, Ticket
from app.models.user import User


class QrError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


ANON_USERNAME = "__anonymous__"  # v2.11 扫码匿名提交的载体用户


def get_or_create_anonymous_user(db: Session) -> User:
    """获取或创建系统匿名用户（未登录扫码建单统一记到它名下，留痕可追溯）。"""
    from app.core.security import hash_password

    anon = db.scalar(select(User).where(User.username == ANON_USERNAME))
    if not anon:
        anon = User(
            username=ANON_USERNAME,
            name="匿名用户",
            role="employee",
            password_hash=hash_password(secrets.token_urlsafe(24)),  # 不可登录的随机密码
        )
        db.add(anon)
        db.commit()
        db.refresh(anon)
    return anon


def generate_code(db: Session) -> str:
    """唯一短码：QR-XXXXX（5 位大写字母数字）。"""
    for _ in range(5):
        code = "QR-" + secrets.token_hex(3).upper().replace("0", "A")[:5]
        if not db.scalar(select(QrTag.id).where(QrTag.code == code)):
            return code
    raise QrError("短码生成冲突，请重试")


def resolve_tag(db: Session, code: str) -> QrTag | None:
    """按 code 取启用的标签；不存在/停用返回 None。"""
    return db.scalar(select(QrTag).where(QrTag.code == (code or "").strip(), QrTag.enabled.is_(True)))


def device_info(db: Session, tag: QrTag) -> dict | None:
    """设备码的资产信息（型号/IP/位置），资产被删则返回 None。"""
    if tag.kind != "device" or not tag.asset_id:
        return None
    a = db.get(Asset, tag.asset_id)
    if not a:
        return None
    return {
        "id": a.id,
        "name": a.name,
        "model": a.model,
        "ip": a.ip_address,
        "location": a.location,
        "asset_tag": a.asset_tag,
    }


def build_overrides(db: Session, tag: QrTag, *, category: str, description: str, custom_fields: dict) -> dict:
    """标签 → 建单参数覆盖：默认分类/资产/custom_fields 记录来源。

    v2.11：设备信息不再拼进描述（详情页由「扫码设备/设备位置/设备 IP」独立单元格展示，避免重复拥挤）；
    位置码/指定码的位置仍追加到描述尾部（无独立设备上下文）。

    返回 {"category", "asset_id", "description", "custom_fields"}。
    """
    out = {
        "category": tag.category or category,  # 标签可配默认分类，留空用提交值
        "asset_id": None,
        "description": description,
        "custom_fields": dict(custom_fields),
    }
    out["custom_fields"]["qr_code"] = tag.code
    segments: list[str] = []

    if tag.kind == "device":
        dev = device_info(db, tag)
        if dev:
            out["asset_id"] = dev["id"]
            out["custom_fields"]["device"] = dev  # 详情页独立展示：设备/位置/IP
    elif tag.kind == "location" and tag.location:
        segments.append(f"位置：{tag.location}")
        out["custom_fields"]["location"] = tag.location
    elif tag.kind == "assignee" and tag.location:
        segments.append(f"位置：{tag.location}")
        out["custom_fields"]["location"] = tag.location

    if segments:
        out["description"] = (description + "\n" if description else "") + "\n".join(segments)
    return out


def apply_forced_assign(db: Session, tag: QrTag, ticket: Ticket) -> None:
    """指定派单码：直接指派给标签绑定的工程师；离职/停用则回退自动分派并留痕。

    非指定码（或无绑定工程师）不做任何事。
    """
    from app.models.ticket import TicketEvent
    from app.services import ticket_service, v12_service

    if tag.kind != "assignee" or not tag.engineer_id:
        return
    engineer = db.get(User, tag.engineer_id)
    if (
        engineer
        and engineer.role in ("admin", "engineer")
        and engineer.is_active
        and (engineer.status or "on_duty") != "leave"
    ):
        ticket_service.assign_ticket(db, ticket=ticket, actor=engineer, engineer=engineer)
        db.add(TicketEvent(
            ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
            content=f"扫码指定派单：{tag.name} → {engineer.name or engineer.username}",
        ))
        db.commit()
        return
    # 指定对象不可用（不存在/停用/请假）：回退智能分派
    v12_service.auto_assign(db, ticket)
    reason = "不存在" if not engineer else ("已请假" if (engineer.status or "on_duty") == "leave" else "已停用")
    db.add(TicketEvent(
        ticket_id=ticket.id, actor_id=None, type=TicketEvent.TYPE_SYSTEM,
        content=f"扫码指定派单：{tag.name}（指定对象{reason}，已回退自动分派）",
    ))
    db.commit()


def open_tickets_for_code(db: Session, code: str, user_id: int | None = None, include_all: bool = False) -> list[dict]:
    """该标签下的未结工单 + 排队位次（处理人名下更早且未结的单数）。

    - 设备码（include_all=True）：显示所有人提交的未结工单，扫码者一眼看到「已有人报过」
    - 登录用户 + 非设备码：只看自己的
    - 匿名（user_id=None）：无身份可过滤，显示全部未结工单
    标签来源用 SQLite/MySQL 通用的 json_extract($.qr_code) 精确匹配。
    """
    from sqlalchemy import func

    stmt = select(Ticket).where(
        Ticket.status.in_(("pending", "processing", "pending_confirm", "pending_approval")),
        func.json_extract(Ticket.custom_fields, "$.qr_code") == code,
    )
    if not include_all and user_id:
        stmt = stmt.where(Ticket.creator_id == user_id)
    tickets = list(db.scalars(stmt).all())
    tickets.sort(key=lambda t: t.id)
    out = []
    for t in tickets:
        ahead = None
        if t.assignee_id:
            ahead = len(
                list(
                    db.scalars(
                        select(Ticket.id).where(
                            Ticket.assignee_id == t.assignee_id,
                            Ticket.status.in_(("pending", "processing", "pending_confirm")),
                            Ticket.id < t.id,
                        )
                    )
                )
            )
        out.append(
            {
                "id": t.id,
                "no": t.no,
                "title": t.title,
                "status": t.status,
                "status_label": STATUS_LABELS.get(t.status, t.status),
                "urgent": bool(t.urgent),
                "creator": (t.creator.name or t.creator.username) if t.creator else None,
                "assignee": (
                    {"id": t.assignee.id, "name": t.assignee.name or t.assignee.username}
                    if t.assignee else None
                ),
                "queue_ahead": ahead,
            }
        )
    return out
