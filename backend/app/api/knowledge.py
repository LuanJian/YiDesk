"""知识库：文章 CRUD、正文配图上传与搜索（工程师维护，全员可读）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from sqlalchemy import or_, select

from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_staff

from app.models.database import get_db

from app.models.knowledge import KnowledgeArticle

from app.models.user import User

from app.schemas.common import KnowledgeIn

from app.services import knowledge_service

router = APIRouter()

@router.get("")

def list_articles(

    q: str | None = None,

    category: str | None = None,

    sort: str = "updated",  # updated（默认）/ heat（按关联工单数热度降序，v2.9）

    db: Session = Depends(get_db),

    _: User = Depends(get_current_user),

):

    stmt = select(KnowledgeArticle).order_by(KnowledgeArticle.updated_at.desc())

    if q:

        like = f"%{q}%"

        stmt = stmt.where(

            or_(

                KnowledgeArticle.title.contains(like),

                KnowledgeArticle.content.contains(like),

                KnowledgeArticle.tags.contains(like),

            )

        )

    if category:

        stmt = stmt.where(KnowledgeArticle.category == category)

    articles = list(db.scalars(stmt).all())

    items = [a.to_dict(with_content=False) for a in articles]

    if sort == "heat":

        # v2.9 热度：与历史工单标题匹配的工单数量（文章标题/标签词命中工单标题计 1 次）

        from app.models.ticket import Ticket

        ticket_titles = [row[0] for row in db.execute(select(Ticket.title)).all()]

        heat: dict[int, int] = {}

        for a in articles:

            words = [w.strip() for w in (a.tags or "").replace("，", ",").split(",") if w.strip()]

            if a.title:

                words.append(a.title)

            hit = sum(1 for t_title in ticket_titles if any(w and w in t_title for w in words))

            heat[a.id] = hit

        for item in items:

            item["heat"] = heat.get(item["id"], 0)

        items.sort(key=lambda x: -x["heat"])

    return {"items": items, "total": len(items)}

@router.get("/{article_id}")

def get_article(article_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):

    a = db.get(KnowledgeArticle, article_id)

    if not a:

        raise HTTPException(status_code=404, detail="文章不存在")

    return a.to_dict()

@router.post("", status_code=201)

def create_article(body: KnowledgeIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):

    a = KnowledgeArticle(

        title=body.title.strip(),

        content=body.content,

        category=body.category or "常见问题",

        problem=body.problem.strip(),

        tags=",".join(t.strip() for t in body.tags if t.strip()),

        source=body.source.strip(),

        public_visible=body.public_visible,

        author_id=user.id,

    )

    db.add(a)

    db.commit()

    db.refresh(a)

    return a.to_dict()

@router.patch("/{article_id}")

def update_article(article_id: int, body: KnowledgeIn, db: Session = Depends(get_db), _: User = Depends(require_staff)):

    a = db.get(KnowledgeArticle, article_id)

    if not a:

        raise HTTPException(status_code=404, detail="文章不存在")

    a.title = body.title.strip()

    a.content = body.content

    a.category = body.category or a.category

    a.problem = body.problem.strip()

    a.tags = ",".join(t.strip() for t in body.tags if t.strip())

    a.source = body.source.strip()

    a.public_visible = body.public_visible

    db.commit()

    db.refresh(a)

    return a.to_dict()

@router.post("/images")

async def upload_article_image(file: UploadFile = File(...), user: User = Depends(require_staff)):

    """知识库正文配图上传（工程师/管理员）。返回公开 URL，正文按行引用。"""

    content = await file.read()

    try:

        name = knowledge_service.save_knowledge_image(content, file.content_type or "")

    except knowledge_service.KnowledgeImageError as exc:

        raise HTTPException(status_code=400, detail=exc.message) from exc

    return {"url": f"/api/public/knowledge-images/{name}", "name": name}

@router.delete("/{article_id}")

def delete_article(article_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):

    a = db.get(KnowledgeArticle, article_id)

    if not a:

        raise HTTPException(status_code=404, detail="文章不存在")

    db.delete(a)

    db.commit()

    return {"ok": True}
