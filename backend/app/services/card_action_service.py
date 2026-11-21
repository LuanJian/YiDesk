"""卡片动作分发服务：IM 卡片按钮回调 → 权限校验 → 状态机流转。

动作串格式：ticket:<action>:<ticket_id>，如 ticket:accept:12。
供钉钉卡片回调与飞书卡片动作回调共用；评价继续走链接跳转（星星交互复杂）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.deps import find_user_by_platform
from app.models.ticket import Ticket
from app.models.user import User
from app.services import ticket_service

logger = logging.getLogger("card_action")

ACTION_RE = re.compile(r"^ticket:(accept|confirm_resolved|close|reopen):(\d+)$")

ACTION_RESULT_TEXT = {
    "accept": "已接单受理，处理进展会通知发起人",
    "confirm_resolved": "已确认解决，感谢反馈",
    "close": "工单已关闭",
    "reopen": "工单已重开，重新进入处理队列",
}


@dataclass
class CardActionResult:
    ok: bool
    message: str
    ticket_id: int | None = None
    action: str | None = None


def parse_action(value: str) -> tuple[str, int] | None:
    m = ACTION_RE.match((value or "").strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def handle_card_action(
    db: Session,
    *,
    channel: str,
    platform_user_id: str,
    action_value: str,
) -> CardActionResult:
    parsed = parse_action(action_value)
    if not parsed:
        return CardActionResult(ok=False, message=f"无法识别的卡片动作: {(action_value or '')[:50]}")
    action, ticket_id = parsed

    user = find_user_by_platform(db, channel, platform_user_id)
    if not user:
        return CardActionResult(ok=False, message="未找到对应用户，请先在 IM 里给机器人发条消息完成注册")

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        return CardActionResult(ok=False, message=f"工单 {ticket_id} 不存在")

    try:
        ticket_service.apply_transition(
            db, ticket=ticket, action=action, actor=user, note="（IM 卡片内操作）"
        )
    except ticket_service.TransitionError as exc:
        return CardActionResult(ok=False, message=exc.message, ticket_id=ticket_id, action=action)

    logger.info("卡片动作成功: %s %s by %s", ticket.no, action, user.username)
    return CardActionResult(ok=True, message=ACTION_RESULT_TEXT.get(action, "操作成功"), ticket_id=ticket_id, action=action)
