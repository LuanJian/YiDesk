"""操作审计 API（v2.4.1，仅管理员）：编辑/指派/挂起/合并/自动派单的统计与明细。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.models.database import get_db
from app.models.user import User
from app.services import audit_service

router = APIRouter()


def _range(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    try:
        s = datetime.strptime(start, "%Y-%m-%d") if start else datetime.utcnow() - timedelta(days=30)
        e = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1) if end else datetime.utcnow()
        return s, e
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc


@router.get("/events")
def audit_events(
    start: str | None = None,
    end: str | None = None,
    actor_id: int | None = None,
    audit_type: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    s, e = _range(start, end)
    return audit_service.events(
        db,
        start=s.replace(tzinfo=None),
        end=e.replace(tzinfo=None),
        actor_id=actor_id,
        audit_type=audit_type,
        q=q,
        page=page,
        page_size=page_size,
    )
