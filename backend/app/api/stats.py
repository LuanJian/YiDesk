"""统计看板 API（工程师/管理员）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_staff
from app.models.database import get_db
from app.models.user import User
from app.services import stats_service

router = APIRouter()


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return stats_service.overview(db)


@router.get("/trend")
def trend(days: int = Query(default=30, ge=7, le=90), db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return stats_service.trend(db, days)


@router.get("/category")
def by_category(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return stats_service.by_category(db)


@router.get("/priority")
def by_priority(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return stats_service.by_priority(db)


@router.get("/engineers")
def by_engineer(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return stats_service.by_engineer(db)
