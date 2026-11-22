"""企业微信渠道适配：应用消息推送（免公网）+ 回调接收（需公网时启用）。

发送：cgi-bin/message/send（textcard），不需要公网地址。

接收：回调 URL 验证（GET echostr）与消息解密（POST），见 api/callbacks.py，

      需在企微后台配置可信域名/回调地址，纯内网时配合 frp 等穿透使用。

"""

from __future__ import annotations

import logging

import threading

import time

import httpx

from app.channels.base import ChannelAdapter

from app.core.config import WeComConfig

logger = logging.getLogger("channel.wecom")

QYAPI = "https://qyapi.weixin.qq.com"  # 固定官方域名

class WeComAdapter(ChannelAdapter):

    name = "wecom"

    display_name = "企业微信"

    ready = False

    def __init__(self, cfg: WeComConfig):

        self.cfg = cfg

        self._token: tuple[float, str] = (0.0, "")

        self._stop_event = threading.Event()

    def _run(self) -> None:

        """发送型渠道无长连接：标记就绪后挂起，等待 stop。"""

        self.ready = True

        self._stop_event.wait()

    def stop(self) -> None:

        self.ready = False

        self._stop_event.set()

    # ---- token ----

    def _get_token(self) -> str:

        ts, token = self._token

        if token and time.time() - ts < 7000:

            return token

        resp = httpx.get(

            f"{QYAPI}/cgi-bin/gettoken",

            params={"corpid": self.cfg.corp_id, "corpsecret": self.cfg.corp_secret},

            timeout=10,

        )

        resp.raise_for_status()

        data = resp.json()

        if data.get("errcode") != 0:

            raise RuntimeError(f"企微 gettoken 失败: {data}")

        self._token = (time.time(), data["access_token"])

        return data["access_token"]

    # ---- 回复会话：企微无 sessionWebhook，退化为应用消息 ----

    def reply_chat(self, chat_id: str, content: str) -> None:

        # chat_id 即 wecom_userid，走应用消息文本

        self.send_card(chat_id, "工单助手", content, url="")

    def send_card(self, receiver_id: str, title: str, content: str, url: str = "", ticket_id: int | None = None) -> None:

        token = self._get_token()

        if url:

            body = {

                "touser": receiver_id,

                "msgtype": "textcard",

                "agentid": self.cfg.agent_id,

                "textcard": {

                    "title": title[:100],

                    "description": content[:500],

                    "url": url,

                    "btntxt": "查看工单",

                },

            }

        else:

            body = {

                "touser": receiver_id,

                "msgtype": "text",

                "agentid": self.cfg.agent_id,

                "text": {"content": f"{title}\n{content}"[:2000]},

            }

        resp = httpx.post(f"{QYAPI}/cgi-bin/message/send?access_token={token}", json=body, timeout=10)

        resp.raise_for_status()

        data = resp.json()

        if data.get("errcode") != 0:

            raise RuntimeError(f"企微消息发送失败: {data}")

    def meta(self) -> dict:

        return {

            "name": self.name,

            "display_name": self.display_name,

            "ready": self.ready,

            "mode": "应用消息推送（免公网）；接收回调需公网 HTTPS",

            "callback_enabled": self.cfg.callback_enabled,

        }
