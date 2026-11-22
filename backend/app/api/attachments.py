"""附件 API：上传（建单人/工程师）与下载（工单可见者）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from fastapi.responses import FileResponse

from sqlalchemy.orm import Session

from app.core.deps import get_current_user

from app.models.database import get_db

from app.models.user import User

from app.services import attachment_service, ticket_service

router = APIRouter()

@router.post("/tickets/{ticket_id}/attachments", status_code=201)

async def upload_attachment(

    ticket_id: int,

    file: UploadFile = File(...),

    db: Session = Depends(get_db),

    user: User = Depends(get_current_user),

):

    ticket = ticket_service.my_accessible_ticket(db, ticket_id, user)

    if not ticket:

        raise HTTPException(status_code=404, detail="工单不存在或无权查看")

    content = await file.read()

    try:

        att = attachment_service.save_attachment(

            db, ticket=ticket, filename=file.filename or "file",

            content=content, content_type=file.content_type or "",

            uploader=user, source="web",

        )

    except attachment_service.AttachmentError as exc:

        raise HTTPException(status_code=400, detail=exc.message) from exc

    return att.to_dict()

@router.get("/attachments/{attachment_id}")

def download_attachment(attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):

    from app.models.attachment import Attachment

    att = db.get(Attachment, attachment_id)

    if not att:

        raise HTTPException(status_code=404, detail="附件不存在")

    ticket = ticket_service.my_accessible_ticket(db, att.ticket_id, user)

    if not ticket:

        raise HTTPException(status_code=404, detail="附件不存在")

    try:

        path = attachment_service.read_attachment_file(att)

    except FileNotFoundError as exc:

        raise HTTPException(status_code=404, detail="附件文件已丢失") from exc

    return FileResponse(

        path, media_type=att.content_type or "application/octet-stream",

        filename=att.filename,

    )
