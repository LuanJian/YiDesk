"""邮件通知渠道：SMTP 适配器。覆盖未绑定 IM、但填了邮箱的用户。"""
from __future__ import annotations

import logging
import smtplib
import threading
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from app.channels.base import ChannelAdapter
from app.core.config import MailConfig

logger = logging.getLogger("channel.mail")


class MailAdapter(ChannelAdapter):
    name = "mail"
    display_name = "邮件"
    ready = False

    def __init__(self, cfg: MailConfig):
        self.cfg = cfg
        self._stop_event = threading.Event()

    def _run(self) -> None:
        """无长连接：标记就绪后挂起等待 stop。"""
        self.ready = True
        self._stop_event.wait()

    def stop(self) -> None:
        self.ready = False
        self._stop_event.set()

    def send_card(self, receiver_id: str, title: str, content: str, url: str = "", ticket_id: int | None = None) -> None:
        """receiver_id 即收件邮箱地址。失败抛异常由 Outbox 重试。"""
        msg = MIMEMultipart()
        msg["Subject"] = Header(title[:120], "utf-8")
        from_addr = self.cfg.from_addr or self.cfg.username
        msg["From"] = formataddr((str(Header("YiDesk", "utf-8")), from_addr))
        msg["To"] = receiver_id
        body = content.replace("\n", "<br>")
        if url:
            body += f'<br><br><a href="{url}">查看工单</a>'
        msg.attach(MIMEText(body, "html", "utf-8"))

        if self.cfg.use_tls:
            client = smtplib.SMTP_SSL(self.cfg.smtp_host, self.cfg.smtp_port, timeout=15)
        else:
            client = smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=15)
        try:
            if self.cfg.username and self.cfg.password:
                client.login(self.cfg.username, self.cfg.password)
            client.sendmail(from_addr, [receiver_id], msg.as_string())
        finally:
            try:
                client.quit()
            except Exception:  # noqa: BLE001
                pass

    def reply_chat(self, chat_id: str, content: str) -> None:
        # 邮件没有「会话」，等价于发一封邮件
        self.send_card(chat_id, "工单通知", content, url="")

    def meta(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "ready": self.ready,
            "mode": f"SMTP {self.cfg.smtp_host}:{self.cfg.smtp_port}",
        }
