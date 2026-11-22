"""公开只读接口（无需登录）：

- 软件列表：员工未登录时浏览允许安装的软件（登录页入口）

- 常见问题：员工自行查阅可自助处理的问题（登录页入口）

- 通用提单码：PC 端无实体码时惰性生成一个通用位置码，跳转 /qr/{code} 提单

"""

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.deps import get_db

from app.models.knowledge import KnowledgeArticle

from app.models.ledger import SoftwareItem

from app.models.qr import QrTag

from app.services.qr_service import generate_code

router = APIRouter()

# 登录页入口的通用报修码名称（同名校验保证复用同一条标签）

GENERAL_QR_NAME = "通用报修入口"

def _software_dict(s: SoftwareItem) -> dict:

    """匿名公开字段：不含来源（source_type/source_url 仅供工程师在管理台查看下载地址）。"""

    return {

        "id": s.id,

        "name": s.name,

        "category": s.category,

        "license_type": s.license_type,

        "description": s.description,

        "departments": [d for d in (s.departments or "").split(",") if d],

    }

@router.get("/softwares")

def public_softwares(db: Session = Depends(get_db)):

    """允许安装的软件列表（仅启用项，不含任何凭据字段）。"""

    items = db.scalars(

        select(SoftwareItem).where(SoftwareItem.enabled.is_(True)).order_by(SoftwareItem.category, SoftwareItem.name)

    ).all()

    return {"items": [_software_dict(s) for s in items], "total": len(items)}

@router.get("/knowledge")

def public_knowledge(db: Session = Depends(get_db)):

    """常见问题列表（标题/分类/标签，正文点详情查看）。"""

    articles = list(db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.public_visible.is_(True)).order_by(KnowledgeArticle.category, KnowledgeArticle.updated_at.desc())).all())

    items = [a.to_dict(with_content=False) for a in articles]

    return {"items": items, "total": len(items)}

@router.get("/knowledge/search")

def public_knowledge_search(title: str = "", description: str = "", db: Session = Depends(get_db)):

    """建单时推荐相关常见问题（匿名可见范围内，2-gram 相似度 Top3，无需登录）。"""

    import re as _re

    def _grams(text: str) -> set:

        cleaned = _re.sub(r"\s", "", (text or "").lower())

        if len(cleaned) < 2:

            return set()

        return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}

    query_grams = _grams(title) | _grams(description)

    if len(query_grams) < 2:

        return {"items": []}

    articles = list(db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.public_visible.is_(True))).all())

    scored = []

    for a in articles:

        hay = (a.title or "") + " " + (a.problem or "") + " " + (a.tags or "")

        score = len(query_grams & _grams(hay))

        if score >= 2:

            scored.append((score, a))

    scored.sort(key=lambda x: -x[0])

    items = []

    for score, a in scored[:3]:

        d = a.to_dict(with_content=False)

        d["score"] = score

        items.append(d)

    return {"items": items, "total": len(items)}

@router.get("/knowledge-images/{name}")

def public_knowledge_image(name: str):

    """知识库正文配图（公开只读，供匿名 FAQ 与登录态文章共同加载）。

    文件名由服务端生成（uuid + 白名单扩展名），此处再校验字符防路径穿越。

    """

    import re as _re

    if not _re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp)", name):

        raise HTTPException(status_code=404, detail="Not Found")

    from pathlib import Path

    from fastapi.responses import FileResponse

    from app.services.knowledge_service import knowledge_images_dir

    path = (knowledge_images_dir() / name).resolve()

    if not path.is_file() or str(path).startswith(str(knowledge_images_dir().resolve())) is False:

        raise HTTPException(status_code=404, detail="Not Found")

    media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}[name.rsplit(".", 1)[1]]

    return FileResponse(path, media_type=media)

@router.get("/knowledge/{article_id}")

def public_knowledge_detail(article_id: int, db: Session = Depends(get_db)):

    """常见问题详情（问题描述 + 解决方法 + 来源）。"""

    a = db.get(KnowledgeArticle, article_id)

    if not a or not a.public_visible:

        raise HTTPException(404, "文章不存在")

    return a.to_dict(with_content=True)

@router.get("/general-qr")

def general_qr(db: Session = Depends(get_db)):

    """PC 端「扫码提单」入口：返回（必要时惰性创建）通用位置码，前端跳 /qr/{code} 提单。"""

    tag = db.scalar(select(QrTag).where(QrTag.kind == "location", QrTag.name == GENERAL_QR_NAME, QrTag.enabled.is_(True)))

    if not tag:

        tag = QrTag(

            code=generate_code(db),

            name=GENERAL_QR_NAME,

            kind="location",

            location="办公区（PC 端提交）",

            enabled=True,

        )

        db.add(tag)

        try:

            db.commit()

        except Exception:

            db.rollback()

            tag = db.scalar(select(QrTag).where(QrTag.kind == "location", QrTag.name == GENERAL_QR_NAME))

            if not tag:

                raise HTTPException(500, "通用提单码生成失败，请重试")

    return {"code": tag.code, "name": tag.name}
