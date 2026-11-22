"""数据备份与恢复 API（v2.5，仅管理员）。

备份列表/立即备份/下载/删除、定时计划 CRUD、SQLite zip 恢复、JSON 上传导入。

危险操作（恢复/导入）需要确认口令 RECOVER。

"""

from __future__ import annotations

import json as _json

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.deps import require_admin

from app.models.database import get_db

from app.models.system import BackupPlan

from app.models.user import User

from app.services import backup_service

router = APIRouter()

MAX_UPLOAD = 200 * 1024 * 1024  # 200MB

def _validate_plan(b: dict) -> None:

    b = b or {}

    if b.get("format") not in ("sqlite", "json", "csv"):

        raise HTTPException(status_code=400, detail="format 必须是 sqlite/json/csv")

    if b.get("frequency") not in ("daily", "weekly", "monthly"):

        raise HTTPException(status_code=400, detail="frequency 必须是 daily/weekly/monthly")

    hh, mm = (b.get("time") or "").split(":")[:2]

    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):

        raise HTTPException(status_code=400, detail="time 格式应为 HH:MM")

    if b.get("frequency") == "weekly" and not (b.get("weekday") is not None and 0 <= b.get("weekday") <= 6):

        raise HTTPException(status_code=400, detail="weekly 需选择星期（0=周一…6=周日）")

    if b.get("frequency") == "monthly" and not (b.get("month_day") and 1 <= b.get("month_day") <= 28):

        raise HTTPException(status_code=400, detail="monthly 需选择每月几号（1-28）")

@router.get("")

def list_all(db: Session = Depends(get_db), _: User = Depends(require_admin)):

    plans = list(db.scalars(select(BackupPlan).order_by(BackupPlan.id)))

    from app.services.backup_service import next_run_hint

    return {

        "files": backup_service.list_backups(),

        "plans": [

            {**p.to_dict(), "next_run": next_run_hint(p)}

            for p in plans

        ],

    }

@router.post("/run")

def run_backup(

    body: dict,

    db: Session = Depends(get_db),

    _: User = Depends(require_admin),

):

    fmt = (body or {}).get("format", "json")

    if fmt not in ("sqlite", "json", "csv"):

        raise HTTPException(status_code=400, detail="format 必须是 sqlite/json/csv")

    try:

        info = backup_service.create_backup(db, fmt)

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, **info}

@router.get("/{filename}/download")

def download_backup(filename: str, _: User = Depends(require_admin)):

    from fastapi.responses import FileResponse

    try:

        path = backup_service.safe_name(filename)

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not path.is_file():

        raise HTTPException(status_code=404, detail="备份文件不存在")

    return FileResponse(path, filename=filename)

@router.delete("/{filename}")

def delete_backup(filename: str, _: User = Depends(require_admin)):

    try:

        path = backup_service.safe_name(filename)

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if path.is_file():

        path.unlink()

    return {"ok": True}

@router.post("/restore/{filename}")

def restore_backup(

    filename: str,

    body: dict,

    db: Session = Depends(get_db),

    _: User = Depends(require_admin),

):

    """从备份列表恢复：sqlite zip（覆盖库文件+附件，需重启）或 json（在线重建）。"""

    try:

        path = backup_service.safe_name(filename)

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not path.is_file():

        raise HTTPException(status_code=404, detail="备份文件不存在")

    confirm = (body or {}).get("confirm", "")

    try:

        if path.suffix == ".zip":

            result = backup_service.restore_sqlite_zip(path, confirm)

        elif path.suffix == ".json":

            data = _json.loads(path.read_text(encoding="utf-8"))

            result = backup_service.import_json(db, data, confirm)

        else:

            raise HTTPException(status_code=400, detail="csv 备份仅用于报表留档，不支持恢复")

        return result

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/import")

async def import_backup(

    file: UploadFile,

    confirm: str = Form(""),

    db: Session = Depends(get_db),

    _: User = Depends(require_admin),

):

    """上传备份文件恢复：.json 在线重建；.zip 覆盖库文件（需重启）。"""

    raw = await file.read()

    if len(raw) > MAX_UPLOAD:

        raise HTTPException(status_code=400, detail="备份文件超过 200MB 限制")

    name = file.filename or ""

    confirm = confirm or ""

    try:

        if name.endswith(".json"):

            data = _json.loads(raw.decode("utf-8"))

            return backup_service.import_json(db, data, confirm)

        if name.endswith(".zip"):

            tmp = backup_service.backup_dir() / "restore-tmp-upload.zip"

            tmp.write_bytes(raw)

            try:

                return backup_service.restore_sqlite_zip(tmp, confirm)

            finally:

                if tmp.exists():

                    tmp.unlink()

        raise HTTPException(status_code=400, detail="仅支持 .json 或 .zip 备份文件")

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

# ---- 定时计划 CRUD ----

@router.post("/plans", status_code=201)

def create_plan(body: dict, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    _validate_plan(body)

    plan = BackupPlan(

        name=(body.get("name") or "未命名").strip()[:64],

        format=body["format"],

        frequency=body["frequency"],

        time=body["time"],

        weekday=body.get("weekday"),

        month_day=body.get("month_day"),

        keep_last=body.get("keep_last", 10),

        enabled=body.get("enabled", True),

    )

    db.add(plan)

    db.commit()

    db.refresh(plan)

    return plan.to_dict()

@router.patch("/plans/{plan_id}")

def update_plan(plan_id: int, body: dict, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    plan = db.get(BackupPlan, plan_id)

    if not plan:

        raise HTTPException(status_code=404, detail="计划不存在")

    _validate_plan({**plan.to_dict(), **(body or {})})

    for f in ("name", "format", "frequency", "time", "weekday", "month_day", "keep_last", "enabled"):

        if (body or {}).get(f) is not None:

            setattr(plan, f, body[f])

    db.commit()

    db.refresh(plan)

    return plan.to_dict()

@router.delete("/plans/{plan_id}")

def delete_plan(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    plan = db.get(BackupPlan, plan_id)

    if not plan:

        raise HTTPException(status_code=404, detail="计划不存在")

    db.delete(plan)

    db.commit()

    return {"ok": True}

@router.post("/plans/{plan_id}/run")

def run_plan_now(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):

    """手动触发一次计划（使用计划的格式/轮换设置；当日计划不再重复自动执行）。"""

    plan = db.get(BackupPlan, plan_id)

    if not plan:

        raise HTTPException(status_code=404, detail="计划不存在")

    from app.models.user import utcnow

    try:

        info = backup_service.create_backup(db, plan.format, plan_name=plan.name)

        backup_service.prune(plan.format, plan.name, plan.keep_last)

        plan.last_run_at = utcnow()

        plan.last_run_date = datetime.now(backup_service.LOCAL_TZ).strftime("%Y-%m-%d")

        plan.last_error = ""

        db.commit()

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, **info}
