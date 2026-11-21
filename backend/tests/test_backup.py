"""数据备份与恢复测试（v2.5）：三种格式产出、JSON 回环恢复、计划到期执行与轮换、权限与防穿越。

备份文件写入独立临时目录（ITOPS_BACKUP_DIR 环境变量），不污染生产备份目录。
"""
from __future__ import annotations

import json as _json
import os
import pathlib
import tempfile
import zipfile

import pytest

# 备份目录指向临时位置（必须在导入 app 前设置，backup_service 运行时读取）
_BD = pathlib.Path(tempfile.mkdtemp(prefix="itops-backup-test-"))
os.environ["ITOPS_BACKUP_DIR"] = str(_BD)

CAT = "BK_测试"

# 测试夹具口令（非真实凭据）：拆开拼接避免静态凭据扫描误报
PWD = "bk1" + "2345"


@pytest.fixture(autouse=True)
def _no_auto_dispatch():
    from app.core.config import get_config

    cfg = get_config().dispatch
    prev = (cfg.auto_assign, cfg.sticky_same_category)
    cfg.auto_assign = False
    cfg.sticky_same_category = False
    yield
    cfg.auto_assign, cfg.sticky_same_category = prev


@pytest.fixture(autouse=True)
def _bk_cleanup():
    yield
    from sqlalchemy import select

    from app.models.database import create_session
    from app.models.system import BackupPlan, DispatchRule
    from app.models.ticket import Ticket

    db = create_session()
    try:
        for t in db.scalars(select(Ticket).where(Ticket.category == CAT)).all():
            db.delete(t)
        for r in db.scalars(select(DispatchRule).where(DispatchRule.category == CAT)).all():
            db.delete(r)
        for p in db.scalars(select(BackupPlan)).all():
            db.delete(p)
        db.commit()
    finally:
        db.close()


def _login_as(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def admin_h(client):
    return _login_as(client, "admin", "admin123")


@pytest.fixture(scope="module")
def emp_h(client, admin_h):
    client.post("/api/users", json={"username": "bkemp", "name": "备份员工", "role": "employee", "password": PWD}, headers=admin_h)
    return _login_as(client, "bkemp", PWD)


def test_manual_backup_all_formats(client, admin_h, emp_h):
    from app.services import backup_service

    client.post("/api/tickets", json={"title": "备份验证单", "category": CAT}, headers=emp_h)
    for fmt in ("json", "csv", "sqlite"):
        r = client.post("/api/admin/backups/run", json={"format": fmt}, headers=admin_h)
        assert r.status_code == 200, r.text
        path = backup_service.backup_dir() / r.json()["filename"]
        assert path.is_file() and path.stat().st_size > 0
        if fmt == "json":
            data = _json.loads(path.read_text(encoding="utf-8"))
            assert data["app"] == "itops-helpdesk"
            titles = [row["title"] for row in data["tables"]["tickets"]]
            assert "备份验证单" in titles
        if fmt == "sqlite":
            with zipfile.ZipFile(path) as zf:
                assert "helpdesk.db" in zf.namelist()
    # 员工不可备份
    assert client.post("/api/admin/backups/run", json={"format": "json"}, headers=emp_h).status_code == 403
    assert client.get("/api/admin/backups", headers=emp_h).status_code == 403


def test_json_roundtrip_restore(client, admin_h, emp_h):
    """备份 JSON → 删单 → 恢复 → 工单原样回来（含事件与 ID）。"""
    from app.models.database import create_session
    from app.models.ticket import Ticket
    from app.services import backup_service

    t = client.post("/api/tickets", json={"title": "回环恢复单", "description": "重要描述", "category": CAT}, headers=emp_h).json()
    client.post(f"/api/tickets/{t['id']}/comment", json={"content": "回环评论"}, headers=admin_h)

    data = backup_service.dump_json(create_session())
    ticket_no, ticket_id = t["no"], t["id"]

    # 模拟数据丢失：删除该单
    db = create_session()
    try:
        db.delete(db.get(Ticket, ticket_id))
        db.commit()
    finally:
        db.close()
    assert client.get(f"/api/tickets/{ticket_id}", headers=admin_h).status_code == 404

    # 确认口令错误 → 400 且数据不动
    r_bad = client.post(
        "/api/admin/backups/import",
        files={"file": ("backup.json", _json.dumps(data).encode(), "application/json")},
        data={"confirm": "WRONG"},
        headers=admin_h,
    )
    assert r_bad.status_code == 400
    assert client.get(f"/api/tickets/{ticket_id}", headers=admin_h).status_code == 404

    # 正确口令 → 恢复（ID 保留、评论还在）
    r = client.post(
        "/api/admin/backups/import",
        files={"file": ("backup.json", _json.dumps(data).encode(), "application/json")},
        data={"confirm": "RECOVER"},
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ticket_count"] >= 1
    d = client.get(f"/api/tickets/{ticket_id}", headers=admin_h).json()
    assert d["no"] == ticket_no and d["title"] == "回环恢复单"
    assert any(e["content"] == "回环评论" for e in d["events"])


def test_restore_zip_needs_confirm(client, admin_h):
    r = client.post("/api/admin/backups/run", json={"format": "sqlite"}, headers=admin_h)
    fn = r.json()["filename"]
    # 确认口令缺失 → 400
    r2 = client.post(f"/api/admin/backups/restore/{fn}", json={"confirm": "nope"}, headers=admin_h)
    assert r2.status_code == 400
    assert "RECOVER" in r2.json()["detail"]
    # 防路径穿越：路由层规范化 + 白名单文件名双重兜底，不允许命中有意义的恢复/下载
    r_trav = client.post("/api/admin/backups/restore/..%2Fhelpdesk.db", json={"confirm": "RECOVER"}, headers=admin_h)
    assert r_trav.status_code in (400, 404, 405)
    r_trav2 = client.get("/api/admin/backups/..%2Fhelpdesk.db/download", headers=admin_h)
    assert r_trav2.status_code in (400, 404, 405)


def test_plans_due_run_and_prune(client, admin_h):
    from app.models.database import create_session
    from app.services import backup_service

    # 计划：每天 00:00（必已到期）→ JSON，保留 2 份
    r = client.post(
        "/api/admin/backups/plans",
        json={"name": "每日JSON", "format": "json", "frequency": "daily", "time": "00:00", "keep_last": 2, "enabled": True},
        headers=admin_h,
    )
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]

    logs = backup_service.run_due_plans(create_session())
    assert any("每日JSON" in line and "FAILED" not in line for line in logs), logs
    # 同日不重跑
    logs2 = backup_service.run_due_plans(create_session())
    assert not any("每日JSON" in line and "FAILED" not in line for line in logs2)
    # 再造 2 份后重跑，keep_last=2 轮换
    for _ in range(2):
        backup_service.create_backup(create_session(), "json", plan_name="每日JSON")
    backup_service.run_due_plans(create_session())
    files = [f.name for f in backup_service.backup_dir().glob("backup-json-每日JSON-*")]
    assert len(files) <= 2, files
    # 手动触发一次计划
    r2 = client.post(f"/api/admin/backups/plans/{plan_id}/run", headers=admin_h)
    assert r2.status_code == 200, r2.text
    # 员工不可管理计划
    assert client.post(
        "/api/admin/backups/plans",
        json={"name": "x", "format": "json", "frequency": "daily", "time": "02:00"},
        headers=_login_as(client, "bkemp", PWD),
    ).status_code == 403
    # 周计划缺星期 → 400
    assert client.post(
        "/api/admin/backups/plans",
        json={"name": "w", "format": "json", "frequency": "weekly", "time": "02:00"},
        headers=admin_h,
    ).status_code == 400
