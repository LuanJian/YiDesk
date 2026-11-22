"""知识库正文配图：落盘 backend/data/knowledge_images/，URL 经公开端点加载。

文件名由服务端生成（uuid4 hex + 白名单扩展名），杜绝路径穿越与任意上传名。

"""

from __future__ import annotations

import uuid

from pathlib import Path

ALLOWED_IMAGE_TYPES = {

    "image/png": "png",

    "image/jpeg": "jpg",

    "image/gif": "gif",

    "image/webp": "webp",

}

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB

class KnowledgeImageError(Exception):

    def __init__(self, message: str):

        super().__init__(message)

        self.message = message

def knowledge_images_dir() -> Path:

    d = Path(__file__).resolve().parents[2] / "data" / "knowledge_images"

    d.mkdir(parents=True, exist_ok=True)

    return d

def save_knowledge_image(content: bytes, content_type: str) -> str:

    """保存正文配图，返回文件名（供 /api/public/knowledge-images/{name} 加载）。"""

    ext = ALLOWED_IMAGE_TYPES.get((content_type or "").lower().split(";")[0].strip())

    if not ext:

        raise KnowledgeImageError("仅支持 png/jpg/gif/webp 图片")

    if len(content) > MAX_IMAGE_SIZE:

        raise KnowledgeImageError("图片不能超过 10MB")

    name = uuid.uuid4().hex + "." + ext

    (knowledge_images_dir() / name).write_bytes(content)

    return name
