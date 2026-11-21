"""钉钉渠道适配：Stream 模式收消息（免公网回调）+ 工作通知发卡片。

前置条件（钉钉开放平台，企业内部应用）：
- 应用开启「机器人」能力并启用 Stream 模式推送
- 应用具有「企业内部应用-工作通知」权限

安全说明：入站消息携带的 sessionWebhook 属于外部输入，使用前强制校验
协议与域名（仅允许 https://*.dingtalk.com），避免 SSRF。
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import threading
import time
from urllib.parse import urlparse

import httpx

from app.channels.base import ChannelAdapter
from app.core.config import DingTalkConfig
from app.services.intake_service import InboundDraft, handle_inbound_threadsafe

logger = logging.getLogger("channel.dingtalk")

OAPI = "https://oapi.dingtalk.com"  # 固定官方域名
DINGTALK_API = "https://api.dingtalk.com"  # 固定官方域名
MAX_IMAGES_PER_MESSAGE = 5


def _is_official_webhook(url: str) -> bool:
    """仅放行 https://*.dingtalk.com，阻断 SSRF。"""
    try:
        p = urlparse(url)
        host = p.hostname or ""
        return p.scheme == "https" and (host == "dingtalk.com" or host.endswith(".dingtalk.com"))
    except Exception:  # noqa: BLE001
        return False


def _guard_official_url(request: httpx.Request) -> None:
    """httpx 请求钩子：每个跳转 hop 上校验协议、域名白名单与解析 IP（防 DNS rebinding）。"""
    u = urlparse(str(request.url))
    host = u.hostname or ""
    if u.scheme != "https" or not (host == "dingtalk.com" or host.endswith(".dingtalk.com")):
        raise httpx.RequestError(f"SSRF guard: blocked non-official host {host}")
    try:
        infos = socket.getaddrinfo(host, u.port or 443)
    except OSError as exc:
        raise httpx.RequestError(f"SSRF guard: resolve failed {host}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise httpx.RequestError(f"SSRF guard: {host} resolved to non-public address {ip}")


def _safe_download_client() -> httpx.Client:
    """下载钉钉消息文件用的受控客户端：校验每个 hop 的 URL 与解析 IP。"""
    return httpx.Client(follow_redirects=True, event_hooks={"request": [_guard_official_url]}, timeout=30)


class DingTalkAdapter(ChannelAdapter):
    name = "dingtalk"
    display_name = "钉钉"
    ready = False

    def __init__(self, cfg: DingTalkConfig):
        self.cfg = cfg
        self.robot_code = cfg.robot_code or cfg.client_id
        self._token: tuple[float, str] = (0.0, "")
        self._webhooks: dict[str, str] = {}  # chat_id -> 最新 sessionWebhook（已通过域名校验）
        self._lock = threading.Lock()

    # ---- 收消息：Stream 长连接（后台线程） ----

    def _run(self) -> None:
        try:
            import dingtalk_stream
        except ImportError:
            logger.error("钉钉渠道启动失败：未安装 dingtalk-stream")
            return

        adapter = self

        class Handler(dingtalk_stream.ChatbotHandler):
            async def process(self, callback: dingtalk_stream.CallbackMessage):
                try:
                    incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
                    text = (incoming.text.content or "").strip() if incoming.text else ""

                    # 图片/富文本里的图片 → 域名+解析 IP 双重校验后下载
                    images: list[tuple[str, bytes]] = []
                    for idx, download_code in enumerate((incoming.get_image_list() or [])[:MAX_IMAGES_PER_MESSAGE]):
                        try:
                            url = self.get_image_download_url(download_code)
                            if not url or not _is_official_webhook(url):
                                logger.warning("钉钉图片下载地址非官方域名，已跳过")
                                continue
                            with _safe_download_client() as dl:
                                resp = dl.get(url)
                                resp.raise_for_status()
                            images.append((f"dingtalk_{int(time.time())}_{idx + 1}.png", resp.content))
                        except Exception:  # noqa: BLE001 单图失败不影响其余
                            logger.exception("钉钉图片下载失败 downloadCode=%s", download_code[:20])

                    platform_id = incoming.sender_staff_id or incoming.sender_id
                    chat_id = incoming.conversation_id
                    with adapter._lock:
                        if incoming.session_webhook and _is_official_webhook(incoming.session_webhook):
                            adapter._webhooks[chat_id] = incoming.session_webhook
                            if len(adapter._webhooks) > 500:  # 防止无限增长
                                adapter._webhooks.pop(next(iter(adapter._webhooks)))
                    draft = InboundDraft(
                        channel="dingtalk",
                        platform_user_id=platform_id or "",
                        sender_name=incoming.sender_nick or "",
                        text=text,
                        chat_id=chat_id,
                        extra={
                            "session_webhook": incoming.session_webhook,
                            "conversation_type": incoming.conversation_type,
                            "images": images,
                        },
                    )
                    await asyncio.to_thread(handle_inbound_threadsafe, draft)
                except Exception:  # noqa: BLE001
                    logger.exception("钉钉消息处理失败")
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

        class CardHandler(dingtalk_stream.CallbackHandler):
            """卡片平台互动卡片按钮回调（模板 ID 见 config.dingtalk.card_template_id）。"""

            async def process(self, callback: dingtalk_stream.CallbackMessage):
                try:
                    card_msg = dingtalk_stream.CardCallbackMessage.from_dict(callback.data)
                    content = card_msg.content or {}
                    value = content.get("ticket_action") or content.get("actionValue") or content.get("value") or ""
                    if isinstance(value, dict):
                        value = value.get("ticket_action") or ""
                    if value:
                        from app.models.database import create_session
                        from app.services.card_action_service import handle_card_action

                        def _run_action():
                            db = create_session()
                            try:
                                return handle_card_action(
                                    db, channel="dingtalk",
                                    platform_user_id=card_msg.user_id or "",
                                    action_value=str(value),
                                )
                            finally:
                                db.close()

                        result = await asyncio.to_thread(_run_action)
                        logger.info("钉钉卡片回调: user=%s ok=%s msg=%s", card_msg.user_id, result.ok, result.message)
                except Exception:  # noqa: BLE001
                    logger.exception("钉钉卡片回调处理失败")
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

        try:
            credential = dingtalk_stream.Credential(self.cfg.client_id, self.cfg.client_secret)
            client = dingtalk_stream.DingTalkStreamClient(credential)
            client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, Handler())
            client.register_callback_handler(dingtalk_stream.Card_Callback_Router_Topic, CardHandler())
            self.ready = True
            logger.info("钉钉 Stream 长连接已启动（卡片回调已注册）")
            client.start_forever()
        except Exception as exc:  # noqa: BLE001
            logger.error("钉钉 Stream 连接异常退出: %s", exc)
        finally:
            self.ready = False

    # ---- 回复会话 ----

    def reply_chat(self, chat_id: str, content: str) -> None:
        webhook = self._webhooks.get(chat_id)
        if webhook:
            resp = httpx.post(
                webhook,
                json={"msgtype": "text", "text": {"content": content}},
                timeout=10,
            )
            resp.raise_for_status()
            return
        self._send_robot_single(chat_id, content)

    def _send_robot_single(self, user_id: str, content: str) -> None:
        """无 sessionWebhook 时退化为机器人单聊消息（oToMessages）。"""
        token = self._get_token()
        resp = httpx.post(
            f"{DINGTALK_API}/v1.0/robot/oToMessages/batchSend?access_token={token}",
            json={
                "robotCode": self.robot_code,
                "userIds": [user_id],
                "msgKey": "sampleText",
                "msgParam": json.dumps({"content": content}, ensure_ascii=False),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") is False:
            raise RuntimeError(f"钉钉机器人单聊发送失败: {data}")

    # ---- 通知卡片：工作通知 ----

    def _get_token(self) -> str:
        ts, token = self._token
        if token and time.time() - ts < 7000:
            return token
        resp = httpx.get(
            f"{OAPI}/gettoken",
            params={"appkey": self.cfg.client_id, "appsecret": self.cfg.client_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"钉钉 gettoken 失败: {data}")
        self._token = (time.time(), data["access_token"])
        return data["access_token"]

    def send_card(self, receiver_id: str, title: str, content: str, url: str = "", ticket_id: int | None = None) -> None:
        if not self.cfg.agent_id:
            raise RuntimeError("钉钉未配置 agent_id，无法发送工作通知")
        token = self._get_token()
        card = {
            "title": title[:200],
            "markdown": f"### {title}\n\n" + content.replace("\n", "\n> "),
        }
        if url:
            card["single_title"] = "查看工单"
            card["single_url"] = url
        body = {
            "agent_id": self.cfg.agent_id,
            "userid_list": receiver_id,
            "msg": {"msgtype": "action_card", "action_card": card},
        }
        resp = httpx.post(
            f"{OAPI}/topapi/message/corpconversation/asyncsend_v2?access_token={token}",
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"钉钉工作通知发送失败: {data}")

    def meta(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "ready": self.ready,
            "mode": "Stream 长连接（免公网回调）",
            "agent_id": self.cfg.agent_id,
        }
