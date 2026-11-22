"""附件服务：保存与读取，文件名消毒 + 大小限制。"""

from __future__ import annotations

import re

import uuid

from pathlib import Path

from sqlalchemy.orm import Session

from app.models.attachment import Attachment, attachments_dir

from app.models.user import User

MAX_SIZE = 10 * 1024 * 1024  # 10MB

ALLOWED_EXT = {

    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",

    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",

    ".txt", ".md", ".csv", ".log", ".zip", ".7z", ".rar",

}

class AttachmentError(Exception):

    def __init__(self, message: str):

        super().__init__(message)

        self.message = message

def sanitize_filename(name: str) -> str:

    """去掉路径分隔与控制字符，限制长度，保留扩展名。"""

    name = Path(name or "file").name

    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip("._ ") or "file"

    stem, ext = Path(name).stem[:180], Path(name).suffix.lower()

    return stem + ext

def save_attachment(

    db: Session,

    *,

    ticket: Ticket,

    filename: str,

    content: bytes,

    content_type: str = "",

    uploader: User | None = None,

    source: str = "web",

) -> Attachment:

    from app.models.ticket import Ticket, TicketEvent  # 延迟导入避免循环依赖

    filename = sanitize_filename(filename)

    ext = Path(filename).suffix.lower()

    if ext and ext not in ALLOWED_EXT:

        raise AttachmentError(f"不支持的文件类型: {ext}")

    if not content:

        raise AttachmentError("空文件")

    if len(content) > MAX_SIZE:

        raise AttachmentError("附件不能超过 10MB")

    stored_name = f"{uuid.uuid4().hex}{ext}"

    path = attachments_dir() / stored_name

    path.write_bytes(content)

    att = Attachment(

        ticket_id=ticket.id,

        filename=filename,

        stored_name=stored_name,

        size=len(content),

        content_type=content_type or _guess_type(ext),

        uploader_id=uploader.id if uploader else None,

        source=source,

    )

    db.add(att)

    db.add(

        TicketEvent(

            ticket_id=ticket.id,

            actor_id=uploader.id if uploader else None,

            type=TicketEvent.TYPE_SYSTEM,

            content=f"上传附件 {filename}（{len(content) // 1024 + 1}KB，来自 {source}）",

        )

    )

    db.commit()

    db.refresh(att)

    return att

def read_attachment_file(att: Attachment) -> Path:

    path = attachments_dir() / att.stored_name

    # 防目录穿越：落盘名由服务端生成（uuid），这里再兜底校验

    if not path.is_file() or path.parent != attachments_dir():

        raise FileNotFoundError(att.stored_name)

    return path

def _guess_type(ext: str) -> str:

    return {

        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",

        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",

        ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",

        ".csv": "text/csv", ".log": "text/plain", ".zip": "application/zip",

    }.get(ext, "application/octet-stream")
