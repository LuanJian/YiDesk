"""用户管理：员工/工程师账号 CRUD（管理员）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin, require_staff
from app.core.security import hash_password
from app.models.database import get_db
from app.models.user import User
from app.schemas.common import UserCreate, UserUpdate

router = APIRouter()


@router.get("")
def list_users(role: str | None = None, q: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    # v2.12 排序：管理员/工程师置顶，员工靠后（同级别按 id）
    stmt = select(User).order_by(
        (User.role == "employee"),  # employee=False(0) 在前
        User.id,
    )
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.username.contains(like)) | (User.name.contains(like)) | (User.department.contains(like)))
    users = list(db.scalars(stmt).all())
    return {"items": [u.to_dict() for u in users], "total": len(users)}


@router.get("/directory")
def user_directory(q: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """全员通讯录（v2.0 代报修用）：仅返回 id/姓名/部门，全员可查。"""
    stmt = select(User).where(User.is_active.is_(True)).order_by(User.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((User.name.contains(like)) | (User.department.contains(like)))
    users = list(db.scalars(stmt.limit(100)).all())
    return {"items": [{"id": u.id, "name": u.name or u.username, "department": u.department} for u in users]}


@router.post("", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.scalar(select(func.count()).select_from(User).where(User.username == body.username.strip())):
        raise HTTPException(status_code=400, detail="用户名已存在")
    if body.role not in ("admin", "engineer", "employee"):
        raise HTTPException(status_code=400, detail="无效的角色")
    if body.ops_type not in ("remote", "field", "other"):
        raise HTTPException(status_code=400, detail="无效的岗位")
    user = User(
        username=body.username.strip(),
        name=body.name.strip(),
        role=body.role,
        department=body.department.strip(),
        email=body.email.strip(),
        phone=body.phone.strip(),
        password_hash=hash_password(body.password) if body.password else None,
        ops_type=body.ops_type if body.role == "engineer" else "other",
        category_scope=(_json.dumps(body.category_scope, ensure_ascii=False) if body.category_scope and body.role == "engineer" else None),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.role and body.role not in ("admin", "engineer", "employee"):
        raise HTTPException(status_code=400, detail="无效的角色")
    # 第二十二批+：管理员账号不可停用（避免误操作导致系统失去管理入口且其他账号无权恢复）
    if user.role == "admin" and body.is_active is False:
        raise HTTPException(status_code=400, detail="管理员账号不可停用")
    for field in ("name", "role", "department", "email", "phone", "is_active", "dept_admin"):
        val = getattr(body, field)
        if val is not None:
            setattr(user, field, val)
    if body.ops_type is not None:
        if body.ops_type not in ("remote", "field", "other"):
            raise HTTPException(status_code=400, detail="无效的岗位")
        # 岗位仅对工程师生效（admin 恒全量，employee 无 staff 权限）
        user.ops_type = body.ops_type if user.role == "engineer" else "other"
    if body.password:
        user.password_hash = hash_password(body.password)
    if body.category_scope is not None:
        import json as _json

        # 管理员不受类目权限约束，设置仅对工程师生效
        user.category_scope = (
            _json.dumps(body.category_scope, ensure_ascii=False) if user.role == "engineer" else None
        )
    if body.status is not None:
        if body.status not in ("on_duty", "leave"):
            raise HTTPException(status_code=400, detail="无效的在岗状态")
        user.status = body.status
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    user.is_active = False  # 软删除，保留工单历史关联
    db.commit()
    return {"ok": True}


# ---- 后台访问安全密钥（第二十一批+：每账号一枚，随机生成、不可指定、仅可重置） ----

GATE_KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"  # 排除易混字符 0/O/1/l/I（第二十九批）


def generate_gate_key() -> str:
    """随机生成准入密钥：32 位、排除易混字符（0/O/1/l/I），避免人工转录错误。"""
    import secrets

    return "".join(secrets.choice(GATE_KEY_ALPHABET) for _ in range(32))


def _gate_link(key: str) -> str:
    from app.core.config import get_config

    base = get_config().public_base_url or ""
    return f"{base}/gate/{key}" if base else f"/gate/{key}"


@router.get("/me/notify-prefs")
def get_my_notify_prefs(user: User = Depends(get_current_user)):
    """第三十七批：自助查看个人通知偏好（缺项视为开启）。"""
    return {"prefs": user.notify_pref_map or {}}


@router.patch("/me/notify-prefs")
def update_my_notify_prefs(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """第三十七批：自助设置个人通知偏好（仅接受 status_change/urge/urgent 三个键）。"""
    allowed = ("status_change", "urge", "urgent")
    prefs = {k: bool(body.get(k, True)) for k in allowed}
    user.notify_prefs = json.dumps(prefs, ensure_ascii=False)
    db.commit()
    return {"prefs": user.notify_pref_map}


@router.get("/me/gate-key")
def get_my_gate_key(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """自助查看自己的安全密钥（右上角菜单入口）。"""
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=400, detail="员工账号不使用安全密钥")
    return {"enabled": bool(user.gate_key), "key": user.gate_key or "", "gate_url": _gate_link(user.gate_key or "")}


@router.post("/me/gate-key/reset")
def reset_my_gate_key(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """自助重置自己的安全密钥：随机生成不可指定；重置后旧密钥与本人已准入设备立即失效（需用新链接重新准入）。"""
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=400, detail="员工账号不使用安全密钥")
    key = generate_gate_key()
    while db.scalar(select(User.id).where(User.gate_key == key)):
        key = generate_gate_key()
    user.gate_key = key
    db.commit()
    return {"enabled": True, "key": key, "gate_url": _gate_link(key)}


@router.get("/login-logs")
def list_login_logs(
    username: str | None = None,
    start: str | None = None,
    end: str | None = None,
    success: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """登录日志（第二十八批+）：成功/失败记录，仅管理员可查。

    第四十一批：支持 账号（模糊）/日期范围/结果（成功/失败）多条件筛选。
    """
    from datetime import datetime, timedelta

    from app.models.login_log import LoginLog

    stmt = select(LoginLog).order_by(LoginLog.id.desc())
    filters = []
    if username and username.strip():
        filters.append(LoginLog.username.contains(username.strip()))
    if start or end:
        try:
            s = datetime.strptime(start, "%Y-%m-%d") if start else None
            e = datetime.strptime(end, "%Y-%m-%d") if end else None
            if s:
                filters.append(LoginLog.created_at >= s)
            if e:
                filters.append(LoginLog.created_at < e + timedelta(days=1))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    if success == "1":
        filters.append(LoginLog.success.is_(True))
    elif success == "0":
        filters.append(LoginLog.success.is_(False))
    stmt = stmt.where(*filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(db.scalars(stmt.offset((max(page, 1) - 1) * page_size).limit(page_size)).all())
    # 第四十五批：失败原因归类统计（同筛选条件按 原因+结果 聚合，前端映射展示）
    reason_stats = [
        {"reason": reason or "", "success": bool(succ), "count": count}
        for reason, succ, count in db.execute(
            select(LoginLog.reason, LoginLog.success, func.count())
            .where(*filters)
            .group_by(LoginLog.reason, LoginLog.success)
        ).all()
    ]
    return {"items": [x.to_dict() for x in items], "total": total, "reason_stats": reason_stats}


@router.get("/{user_id}/gate-key")
def get_user_gate_key(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """查看某账号的安全密钥（仅管理员）。"""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"enabled": bool(user.gate_key), "key": user.gate_key or "", "gate_url": _gate_link(user.gate_key or "")}


@router.post("/{user_id}/gate-key/reset")
def reset_user_gate_key(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """生成/重置某账号的安全密钥：系统随机生成不可指定；重置后旧密钥与该账号已准入设备立即失效。"""
    import secrets

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=400, detail="仅管理员/工程师账号使用安全密钥")
    for _ in range(5):
        key = secrets.token_urlsafe(24)
        if not db.scalar(select(User.id).where(User.gate_key == key)):
            break
    else:
        raise HTTPException(status_code=500, detail="密钥生成冲突，请重试")
    user.gate_key = key
    db.commit()
    return {"enabled": True, "key": key, "gate_url": _gate_link(key)}
