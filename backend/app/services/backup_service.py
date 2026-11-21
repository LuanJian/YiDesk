"""数据备份与恢复服务（v2.5）。

三种备份格式：
- sqlite：整库快照（SQLite backup API 保证一致性）+ 附件目录，zip 打包——恢复后重启即完整还原
- json：全量业务表数据包（可读、可跨库迁移；不含附件文件，附件文件仅随 sqlite 备份）
- csv：工单业务报表（留档/分析用，不作为恢复源）

恢复：仅支持 sqlite zip 与 json 数据包；两者均要求管理员 + 确认口令。
定时计划由调度器每 5 分钟扫描一次（公司时区 Asia/Shanghai）。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.models.database import Base, get_engine
from app.models.system import BackupPlan
from app.models.ticket import Ticket
from app.models.user import utcnow

BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SAFE_NAME = re.compile(r"^backup-[\w-]+\.(zip|json|csv)$")
JSON_VERSION = 1


def safe_plan_name(name: str) -> str:
    """计划名进入文件名前的白名单清洗（中文保留，其余折叠为下划线）。"""
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name or "").strip("_") or "plan"


def backup_dir() -> Path:
    # 测试可用 ITOPS_BACKUP_DIR 重定向备份目录
    d = Path(os.environ.get("ITOPS_BACKUP_DIR") or BACKUP_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    url = get_config().resolved_database_url()
    if not url.startswith("sqlite:///"):
        raise ValueError("仅 SQLite 部署支持整库备份；请使用 json/csv 备份")
    return Path(url.removeprefix("sqlite:///"))


def attachments_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "attachments"


# ---- 备份文件列表 / 清理 ----

def list_backups() -> list[dict]:
    out = []
    for f in sorted(backup_dir().glob("backup-*"), key=lambda p: p.name, reverse=True):
        if not f.is_file():
            continue
        out.append({
            "filename": f.name,
            "size": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, LOCAL_TZ).isoformat(),
            "format": "sqlite" if f.name.endswith(".zip") else ("json" if f.name.endswith(".json") else "csv"),
        })
    return out


def safe_name(name: str) -> Path:
    """防路径穿越：只允许 backup- 前缀的白名单文件名。"""
    if not SAFE_NAME.match(name or ""):
        raise ValueError("非法的备份文件名")
    return backup_dir() / name


def prune(format: str, plan_name: str, keep_last: int) -> int:
    """按「格式+计划名」轮换，保留最近 keep_last 份；返回删除数。"""
    if keep_last <= 0:
        return 0
    prefix = f"backup-{format}-{safe_plan_name(plan_name)}-"
    pat = re.compile(re.escape(prefix) + r"\d{8}-\d{6}\.(zip|json|csv)$")
    files = sorted(
        [f for f in backup_dir().glob("backup-*") if f.is_file() and pat.match(f.name)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for f in files[keep_last:]:
        f.unlink()
        removed += 1
    return removed


# ---- 备份产出 ----

def create_backup(db: Session, format: str, plan_name: str = "") -> dict:
    """立即产出一份备份文件，返回文件信息。"""
    ts = utcnow().strftime("%Y%m%d-%H%M%S")
    prefix = f"{safe_plan_name(plan_name)}-" if plan_name else ""
    if format == "sqlite":
        path = _backup_sqlite(backup_dir() / f"backup-sqlite-{prefix}{ts}.zip")
    elif format == "json":
        path = _backup_json(db, backup_dir() / f"backup-json-{prefix}{ts}.json")
    elif format == "csv":
        path = _backup_csv(db, backup_dir() / f"backup-csv-{prefix}{ts}.csv")
    else:
        raise ValueError("format 必须是 sqlite/json/csv")
    return {"filename": path.name, "size": path.stat().st_size, "format": format}


def _backup_sqlite(target: Path) -> Path:
    src_path = db_path()
    import sqlite3

    # SQLite backup API：在线一致性快照（避免直接复制正在写入的库文件）
    src = sqlite3.connect(str(src_path))
    tmp = target.with_suffix(".tmp.db")
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp, "helpdesk.db")
        att = attachments_dir()
        if att.is_dir():
            for f in att.rglob("*"):
                if f.is_file():
                    zf.write(f, f"attachments/{f.relative_to(att)}")
    tmp.unlink()
    return target


def _serialize_value(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _table_rows(db: Session, table) -> list[dict]:
    cols = [c.name for c in table.columns]
    rows = db.execute(select(table)).all()
    return [{c: _serialize_value(v) for c, v in zip(cols, row)} for row in rows]


def dump_json(db: Session) -> dict:
    tables = {}
    for t in Base.metadata.sorted_tables:
        tables[t.name] = _table_rows(db, t)
    return {
        "version": JSON_VERSION,
        "created_at": utcnow().isoformat() + "Z",
        "app": "itops-helpdesk",
        "tables": tables,
    }


def _backup_json(db: Session, target: Path) -> Path:
    target.write_text(json.dumps(dump_json(db), ensure_ascii=False), encoding="utf-8")
    return target


def _backup_csv(db: Session, target: Path) -> Path:
    from app.api.export import HEADERS

    tickets = list(db.scalars(select(Ticket)).all())
    from app.models.ticket import Rating

    ratings = {r.ticket_id: r.stars for r in db.scalars(select(Rating)).all()}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    for t in tickets:
        writer.writerow([
            t.no, t.title, t.category, t.priority, t.status,
            (t.creator.name or t.creator.username) if t.creator else "",
            (t.assignee.name or t.assignee.username) if t.assignee else "",
            t.channel, _fmt_dt(t.created_at), _fmt_dt(t.first_responded_at), _fmt_dt(t.resolved_at),
        ])
    target.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))
    return target


def _fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def import_json(db: Session, data: dict, confirm: str) -> dict:
    """整库覆盖式导入 JSON 数据包：按依赖序清空后重建（保留原 ID）。"""
    from app.models.ticket import Ticket

    if confirm != "RECOVER":
        raise ValueError("请输入确认口令 RECOVER")
    if not isinstance(data, dict) or data.get("app") != "itops-helpdesk" or not isinstance(data.get("tables"), dict):
        raise ValueError("不是有效的本系统 JSON 备份文件")
    if Ticket.__tablename__ not in data["tables"]:
        raise ValueError("备份缺少工单数据（tickets 表）")

    # 表名 → ORM 类映射（declarative registry），用 ORM API 清空与重建
    mappers = {m.local_table.name: m.class_ for m in Base.registry.mappers if m.local_table is not None}
    from datetime import datetime as _dt

    # 依赖序逆序清空，再正序重建；外键约束默认关闭（SQLite），顺序保证 MySQL 迁移同样安全。
    # 显式 id 插入后，SQLite（无 AUTOINCREMENT）/MySQL 的自增都会自动取 max(id)+1，无需处理序列表
    for t in reversed(Base.metadata.sorted_tables):
        cls = mappers.get(t.name)
        if cls is None:
            continue
        db.query(cls).delete(synchronize_session=False)
    inserted = {}
    for t in Base.metadata.sorted_tables:
        cls = mappers.get(t.name)
        rows = data["tables"].get(t.name) or []
        if cls is None:
            continue
        if not rows:
            inserted[t.name] = 0
            continue
        # 列类型还原：DateTime 列的 ISO 字符串 → datetime 对象
        dt_cols = {c.name for c in t.columns if c.type.python_type is _dt}
        for row in rows:
            clean = {}
            for k, v in row.items():
                if k in dt_cols and isinstance(v, str) and v:
                    v = _dt.fromisoformat(v.replace("Z", ""))
                clean[k] = v
            db.add(cls(**clean))
        db.flush()
        inserted[t.name] = len(rows)
    db.commit()
    return {"restored": inserted, "ticket_count": inserted.get(Ticket.__tablename__, 0)}


def restore_sqlite_zip(zip_path: Path, confirm: str) -> dict:
    """从 SQLite zip 备份恢复：覆盖库文件与附件目录，需重启服务生效。

    解压先落在独立临时目录，最后才 dispose 引擎并原子替换——绝不直接
    往 data/ 目录解压覆盖正在使用的活库。
    """
    if confirm != "RECOVER":
        raise ValueError("请输入确认口令 RECOVER")
    src_path = db_path()
    import tempfile as _tmpmod

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if "helpdesk.db" not in names:
            raise ValueError("备份包缺少 helpdesk.db")
        bad = [n for n in names if n.startswith("/") or ".." in n]
        if bad:
            raise ValueError("备份包含不安全的路径条目")
        work = Path(_tmpmod.mkdtemp(prefix="itops-restore-"))
        try:
            zf.extract("helpdesk.db", work)  # 解压到临时目录，不触碰 data/
            staged = work / "helpdesk.db"
            if staged.stat().st_size <= 0:
                raise ValueError("备份中的数据库文件为空")
            get_engine().dispose()  # 释放连接后原子替换库文件
            shutil.move(str(staged), str(src_path))
            # 附件目录：清空后按备份还原
            att = attachments_dir()
            if att.is_dir():
                for f in att.iterdir():
                    if f.is_file():
                        f.unlink()
            att.mkdir(parents=True, exist_ok=True)
            for n in names:
                if n.startswith("attachments/") and not n.endswith("/"):
                    data = zf.read(n)
                    out = att / n.removeprefix("attachments/")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "restart_required": True}


# ---- 定时计划 ----

def run_due_plans(db: Session) -> list[str]:
    """扫描到期计划并执行（调度器每 5 分钟调用一次）；返回动作日志。"""
    now_local = datetime.now(LOCAL_TZ)
    logs: list[str] = []
    for plan in db.scalars(select(BackupPlan).where(BackupPlan.enabled.is_(True))).all():
        try:
            if not _plan_due(plan, now_local):
                continue
            info = create_backup(db, plan.format, plan_name=plan.name)
            removed = prune(plan.format, plan.name, plan.keep_last)
            plan.last_run_at = utcnow()
            plan.last_run_date = now_local.strftime("%Y-%m-%d")
            plan.last_error = ""
            db.commit()
            logs.append(f"{plan.name}: {info['filename']}（清理 {removed} 份旧备份）")
        except Exception as exc:  # noqa: BLE001 记录失败继续
            plan.last_error = f"{type(exc).__name__}: {exc}"[:500]
            db.commit()
            logs.append(f"{plan.name}: FAILED {plan.last_error}")
    return logs


def _plan_due(plan: BackupPlan, now_local: datetime) -> bool:
    if plan.last_run_date == now_local.strftime("%Y-%m-%d"):
        return False  # 当日已跑
    if plan.frequency == "weekly":
        if now_local.weekday() != (plan.weekday if plan.weekday is not None else 0):
            return False
    if plan.frequency == "monthly":
        md = plan.month_day or 1
        if now_local.day != min(md, 28):
            return False
    hh, mm = (plan.time or "02:00").split(":")[:2]
    scheduled = now_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    return now_local >= scheduled


def next_run_hint(plan: BackupPlan) -> str:
    """展示用：下次可触发时间（今天计划时点或下一个匹配日）。"""
    now_local = datetime.now(LOCAL_TZ)
    d = now_local
    for _ in range(400):
        if plan.frequency == "weekly" and d.weekday() != (plan.weekday if plan.weekday is not None else 0):
            d += timedelta(days=1)
            continue
        if plan.frequency == "monthly" and d.day != min(plan.month_day or 1, 28):
            d = (d.replace(day=min(plan.month_day or 1, 28)) + timedelta(days=1))
            d = d.replace(day=1) + timedelta(days=32)
            d = d.replace(day=min(plan.month_day or 1, 28))
            continue
        cand = d.replace(hour=int((plan.time or "02:00").split(":")[0]), minute=int((plan.time or "02:00").split(":")[1]), second=0, microsecond=0)
        if cand > now_local:
            return cand.strftime("%Y-%m-%d %H:%M")
        d += timedelta(days=1)
    return ""
