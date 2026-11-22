"""渠道适配统一接口。

所有 IM 渠道实现同一套能力：

- start()/stop()：后台线程启动/停止长连接（收消息）

- reply_chat()：回复建单会话（建单确认、命令应答）

- send_card()：主动推送通知卡片（OutboxMessage 投递入口）

"""

from __future__ import annotations

import threading

from abc import ABC, abstractmethod

class ChannelAdapter(ABC):

    name: str = "base"

    display_name: str = "未命名渠道"

    ready: bool = False

    def start(self) -> None:

        """在后台线程中启动长连接。"""

        t = threading.Thread(target=self._run, name=f"channel-{self.name}", daemon=True)

        t.start()

    # ---- 生命周期 ----

    @abstractmethod

    def _run(self) -> None:

        """阻塞式长连接主循环（子类实现，内部处理断线重连）。"""

    def stop(self) -> None:  # pragma: no cover - 各渠道按需实现优雅退出

        self.ready = False

    # ---- 发送能力 ----

    @abstractmethod

    def send_card(self, receiver_id: str, title: str, content: str, url: str = "", ticket_id: int | None = None) -> None:

        """主动推送通知卡片。失败抛异常（由 Outbox 重试机制兜底）。

        ticket_id 用于渠道构造卡片内快捷操作按钮（卡内回调）。

        """

    @abstractmethod

    def reply_chat(self, chat_id: str, content: str) -> None:

        """回复建单会话（纯文本）。"""

    def meta(self) -> dict:

        return {"name": self.name, "display_name": self.display_name, "ready": self.ready}
