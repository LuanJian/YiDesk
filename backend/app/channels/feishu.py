"""飞书渠道适配：WebSocket 长连接收消息（免公网回调）+ 交互卡片推送。

前置条件（飞书开放平台，企业自建应用）：

- 应用添加「机器人」能力

- 开通 im:message（接收消息、发送消息）与 contact:user.base:readonly 权限

- 事件订阅方式选择「使用长连接接收事件」

"""

from __future__ import annotations

import json

import logging

import httpx  # noqa: F401 保留显式依赖提示

from lark_oapi.api.im.v1 import CreateMessageRequestBody, CreateMessageRequest

from app.channels.base import ChannelAdapter

from app.core.config import FeishuConfig

from app.services.intake_service import InboundDraft, handle_inbound_threadsafe

logger = logging.getLogger("channel.feishu")

class FeishuAdapter(ChannelAdapter):

    name = "feishu"

    display_name = "飞书"

    ready = False

    def __init__(self, cfg: FeishuConfig):

        self.cfg = cfg

        self._client = None  # lark.Client，_ensure_client 懒加载

    # ---- 内部工具 ----

    def _ensure_client(self):

        if self._client is None:

            import lark_oapi as lark

            self._client = (

                lark.Client.builder()

                .app_id(self.cfg.app_id)

                .app_secret(self.cfg.app_secret)

                .log_level(lark.LogLevel.WARNING)

                .build()

            )

        return self._client

    def _fetch_user_name(self, open_id: str) -> str:

        """尽力获取用户姓名（失败返回空串，不影响建单）。"""

        try:

            import lark_oapi as lark

            from lark_oapi.api.contact.v3 import GetUserRequest

            req = GetUserRequest.builder().user_id(open_id).user_id_type("open_id").build()

            resp = self._ensure_client().contact.v3.user.get(req)

            if resp.success() and resp.data and resp.data.user:

                return resp.data.user.name or ""

        except Exception:  # noqa: BLE001

            pass

        return ""

    def _download_image(self, image_key: str) -> bytes | None:

        """下载消息图片（im.v1.image.get）。失败返回 None，不影响主流程。"""

        if not image_key:

            return None

        try:

            from lark_oapi.api.im.v1 import GetImageRequest

            req = GetImageRequest.builder().image_key(image_key).build()

            resp = self._ensure_client().im.v1.image.get(req)

            if resp.success() and resp.file:

                return bytes(resp.file)

            logger.warning("飞书图片下载失败: %s %s", resp.code, resp.msg)

        except Exception:  # noqa: BLE001

            logger.exception("飞书图片下载异常 key=%s", image_key[:16])

        return None

    # ---- 收消息：长连接（后台线程） ----

    def _run(self) -> None:

        try:

            import lark_oapi as lark

        except ImportError:

            logger.error("飞书渠道启动失败：未安装 lark-oapi")

            return

        adapter = self

        def on_message(data) -> None:

            try:

                event = data.event

                msg = event.message

                sender_open_id = event.sender.sender_id.open_id if event.sender and event.sender.sender_id else ""

                if not sender_open_id:

                    return

                text = ""

                images: list[tuple[str, bytes]] = []

                mtype = msg.message_type

                if mtype == "text":

                    text = (json.loads(msg.content or "{}") or {}).get("text", "").strip()

                elif mtype == "image":

                    key = (json.loads(msg.content or "{}") or {}).get("image_key", "")

                    content_bytes = adapter._download_image(key)

                    if content_bytes:

                        images.append((f"feishu_{key[:16]}.png", content_bytes))

                elif mtype == "post":

                    # 富文本：提取文本与图片

                    post = json.loads(msg.content or "{}") or {}

                    for lang_content in post.values():

                        if not isinstance(lang_content, dict):

                            continue

                        for para in lang_content.get("content", []) or []:

                            for elem in para or []:

                                tag = elem.get("tag")

                                if tag == "text":

                                    text += elem.get("content", "")

                                elif tag == "img":

                                    key = elem.get("image_key", "")

                                    content_bytes = adapter._download_image(key)

                                    if content_bytes:

                                        images.append((f"feishu_{key[:16]}.png", content_bytes))

                if not text and not images:

                    try:

                        adapter.reply_chat(

                            msg.chat_id, "暂只支持文字与图片消息，请直接描述你的问题（可附截图）。"

                        )

                        return

                    except Exception:  # noqa: BLE001

                        return

                draft = InboundDraft(

                    channel="feishu",

                    platform_user_id=sender_open_id,

                    sender_name=adapter._fetch_user_name(sender_open_id),

                    text=text.strip(),

                    chat_id=msg.chat_id,

                    extra={"message_id": msg.message_id, "images": images},

                )

                handle_inbound_threadsafe(draft)

            except Exception:  # noqa: BLE001

                logger.exception("飞书消息处理失败")

        def on_card_action(data) -> None:

            """卡片按钮回调：value.ticket_action → 状态机。"""

            try:

                event = data.event

                operator_open_id = event.operator.open_id if event.operator else ""

                action_value = ""

                if event.action and isinstance(event.action.value, dict):

                    action_value = str(event.action.value.get("ticket_action") or "")

                if not action_value:

                    return

                from app.services.card_action_service import handle_card_action

                def _run_action():

                    from app.models.database import create_session

                    db = create_session()

                    try:

                        return handle_card_action(

                            db, channel="feishu",

                            platform_user_id=operator_open_id,

                            action_value=action_value,

                        )

                    finally:

                        db.close()

                result = _run_action()

                if operator_open_id:

                    try:

                        adapter.reply_chat(

                            operator_open_id,

                            ("✅ " if result.ok else "⚠️ ") + result.message,

                        )

                    except Exception:  # noqa: BLE001

                        pass

                logger.info("飞书卡片动作: operator=%s ok=%s", operator_open_id, result.ok)

            except Exception:  # noqa: BLE001

                logger.exception("飞书卡片动作处理失败")

        try:

            event_handler = (

                lark.EventDispatcherHandler.builder("", "")

                .register_p2_im_message_receive_v1(on_message)

                .register_p2_card_action_trigger(on_card_action)

                .build()

            )

            ws_client = lark.ws.Client(

                self.cfg.app_id,

                self.cfg.app_secret,

                event_handler=event_handler,

                log_level=lark.LogLevel.WARNING,

            )

            self.ready = True

            logger.info("飞书长连接已启动（卡片动作回调已注册）")

            ws_client.start()  # 阻塞运行，SDK 内部处理断线重连

        except Exception as exc:  # noqa: BLE001

            logger.error("飞书长连接异常退出: %s", exc)

        finally:

            self.ready = False

    # ---- 回复会话 ----

    def reply_chat(self, chat_id: str, content: str) -> None:

        req = (

            CreateMessageRequest.builder()

            .receive_id_type("chat_id")

            .request_body(

                CreateMessageRequestBody.builder()

                .receive_id(chat_id)

                .msg_type("text")

                .content(json.dumps({"text": content}, ensure_ascii=False))

                .build()

            )

            .build()

        )

        resp = self._ensure_client().im.v1.message.create(req)

        if not resp.success():

            raise RuntimeError(f"飞书回复失败: {resp.code} {resp.msg}")

    # ---- 通知卡片 ----

    def send_card(self, receiver_id: str, title: str, content: str, url: str = "", ticket_id: int | None = None) -> None:

        """交互卡片：快捷操作按钮（卡内回调，仅对工程师/管理员生效）+ 查看工单跳转。"""

        elements: list[dict] = [{"tag": "markdown", "content": content.replace("\n", "<br>")}]

        # 卡内快捷操作：动作串带工单号，回调时按点击者权限校验

        if ticket_id:

            quick = []

            for label, action in (("接单", "accept"), ("确认解决", "confirm_resolved"), ("关闭", "close"), ("重开", "reopen")):

                quick.append(

                    {

                        "tag": "button",

                        "text": {"tag": "plain_text", "content": label},

                        "value": {"ticket_action": f"ticket:{action}:{ticket_id}"},

                    }

                )

            elements.append({"tag": "action", "actions": quick})

        if url:

            elements.append(

                {

                    "tag": "action",

                    "actions": [

                        {

                            "tag": "button",

                            "text": {"tag": "plain_text", "content": "查看工单"},

                            "type": "primary",

                            "url": url,

                        }

                    ],

                }

            )

        card = {"header": {"title": {"tag": "plain_text", "content": title[:100]}, "template": "blue"}, "elements": elements}

        req = (

            CreateMessageRequest.builder()

            .receive_id_type("open_id")

            .request_body(

                CreateMessageRequestBody.builder()

                .receive_id(receiver_id)

                .msg_type("interactive")

                .content(json.dumps(card, ensure_ascii=False))

                .build()

            )

            .build()

        )

        resp = self._ensure_client().im.v1.message.create(req)

        if not resp.success():

            raise RuntimeError(f"飞书卡片发送失败: {resp.code} {resp.msg}")

    def meta(self) -> dict:

        return {

            "name": self.name,

            "display_name": self.display_name,

            "ready": self.ready,

            "mode": "WebSocket 长连接（免公网回调）",

        }
