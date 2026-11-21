"""认证：账号密码登录、当前用户、修改密码。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.config import get_config
from app.core.security import create_access_token, hash_password, verify_password
from app.services import notify_service
from app.models.database import get_db
from app.models.user import User
from app.schemas.common import LoginIn, PasswordChangeIn
from app.services.platform_auth import (
    PlatformAuthError,
    login_by_dingtalk_code,
    login_by_feishu_code,
    login_by_wecom_code,
)

router = APIRouter()


# ---- 登录限流（v2.7）：按用户名+来源 IP 计失败次数，连错 5 次锁 15 分钟 ----
import time as _time

_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_SECONDS = 15 * 60
_login_fails: dict[str, tuple[int, float]] = {}  # key -> (失败次数, 首次失败时间戳)


def _login_key(username: str, ip: str) -> str:
    return f"{username}|{ip}"


def _login_blocked(key: str) -> int:
    """返回剩余锁定秒数；0 = 未锁定。"""
    rec = _login_fails.get(key)
    if not rec:
        return 0
    fails, first_ts = rec
    if _time.time() - first_ts > _LOGIN_LOCK_SECONDS:
        _login_fails.pop(key, None)
        return 0
    if fails >= _LOGIN_MAX_FAILS:
        return int(_LOGIN_LOCK_SECONDS - (_time.time() - first_ts)) + 1
    return 0


def _record_fail(key: str) -> None:
    rec = _login_fails.get(key)
    if rec and _time.time() - rec[1] <= _LOGIN_LOCK_SECONDS:
        _login_fails[key] = (rec[0] + 1, rec[1])
    else:
        _login_fails[key] = (1, _time.time())


FREEZE_AFTER_FAILS = 3  # 工程师连续密码错误冻结阈值（第二十八批+）


def _consecutive_fails(db: Session, username: str) -> int:
    """该账号最近连续失败次数（从最新一条往前数，成功即打断）。"""
    from app.models.login_log import LoginLog

    logs = list(db.scalars(select(LoginLog).where(LoginLog.username == username).order_by(LoginLog.id.desc()).limit(FREEZE_AFTER_FAILS)).all())
    return sum(1 for lg in logs if not lg.success)


def _freeze_engineer_if_needed(db: Session, user: User, ip: str) -> None:
    """工程师连续 FREEZE_AFTER_FAILS 次密码错误 → 冻结账户（is_active=False），仅管理员可解冻；通知全部管理员。"""
    if user.role != "engineer" or not user.is_active:
        return
    if _consecutive_fails(db, user.username) >= FREEZE_AFTER_FAILS:
        user.is_active = False
        reason = f"连续 {FREEZE_AFTER_FAILS} 次密码错误，账户已自动冻结"
        _write_login_log(db, user.username, ip, False, reason, user.name or "")
        admins = list(db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all())
        from app.services import notify_service as _ns

        _ns.enqueue_for_users(
            db, admins, ticket_id=None, title=f"工程师账户已冻结：{user.name or user.username}",
            content=f"工程师 {user.name or user.username}（@{user.username}）连续 {FREEZE_AFTER_FAILS} 次密码错误，账户已自动冻结。"
                    f"来源 IP {ip}。请核实后到 系统设置→用户管理 中「启用」解冻。",
        )
        db.commit()


def _write_login_log(db: Session, username: str, ip: str, success: bool, reason: str = "", name: str = "") -> None:
    """登录日志持久化（第二十八批+）：成功/失败均记录。"""
    try:
        from app.models.login_log import LoginLog

        db.add(LoginLog(username=username[:64], name=(name or "")[:64], ip=ip[:64], success=success, reason=(reason or "")[:200]))
        db.commit()
    except Exception:
        db.rollback()


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "-"
    key = _login_key(body.username.strip(), ip)
    locked = _login_blocked(key)
    if locked:
        _write_login_log(db, body.username.strip(), ip, False, "账号临时锁定中")
        raise HTTPException(status_code=429, detail=f"失败次数过多，账号已临时锁定，请 {max(locked // 60, 1)} 分钟后再试")
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if user and not user.is_active and verify_password(body.password, user.password_hash):
        # 第二十八批+：密码正确但账户已冻结/停用——明确提示（避免工程师误以为密码错误）
        _write_login_log(db, user.username, ip, False, "账户已冻结或停用")
        raise HTTPException(status_code=401, detail="账户已冻结或已停用，请联系管理员解除")
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        # v2.10 AD 域认证回退：本地账密不符时，若启用 AD 域则尝试域验证并自动建号
        ad_user = _try_ad_login(db, body.username.strip(), body.password)
        if ad_user:
            _login_fails.pop(key, None)
            _write_login_log(db, ad_user.username, ip, True, "", ad_user.name or "")
            return {"token": create_access_token(ad_user.id, ad_user.role), "user": ad_user.to_dict()}
        _record_fail(key)
        remain = _LOGIN_MAX_FAILS - _login_fails[key][0]
        detail = "用户名或密码错误"
        if remain <= 2:
            detail += f"（再错 {remain} 次将临时锁定 15 分钟）"
        _write_login_log(db, body.username.strip(), ip, False, "用户名或密码错误")
        if user and user.is_active and not ad_user:
            # 第二十八批+：工程师连续 3 次密码错误 → 冻结账户（仅管理员解冻）
            _freeze_engineer_if_needed(db, user, ip)
            if not user.is_active:
                detail = "账户已冻结（连续密码错误），请联系管理员解除"
        raise HTTPException(status_code=401, detail=detail)
    # 第二十八批+：安全密钥门禁校验（已启用账号需持密钥）
    try:
        _check_gate(user, body.gate_key, request)
    except HTTPException as exc:
        _write_login_log(db, user.username, ip, False, f"安全密钥校验未通过：{exc.detail}")
        raise
    _login_fails.pop(key, None)  # 登录成功清零
    _write_login_log(db, user.username, ip, True, "", user.name or "")
    return {"token": create_access_token(user.id, user.role), "user": user.to_dict()}


def _check_gate(user: User, body_key: str | None, request: Request) -> None:
    """后台访问安全密钥：每账号一枚（User.gate_key）。已生成密钥的管理员/工程师登录必须持密钥
    （URL 准入 Cookie 或请求携带），员工与未生成密钥的账号不受影响。"""
    import hashlib

    if user.role not in ("admin", "engineer") or not user.gate_key:
        return
    cookie_value = request.cookies.get("itops_gate") or ""
    expected = hashlib.sha256(user.gate_key.encode()).hexdigest()
    if body_key != user.gate_key and cookie_value != expected:
        raise HTTPException(status_code=403, detail="该账号已启用安全密钥，请通过管理员分发的准入链接访问后台")


def _try_ad_login(db: Session, username: str, password: str) -> User | None:
    """v2.10 AD 域认证：LDAP 绑定验证域账密，成功后按域账号自动建号（employee）。

    仅在本地账密验证失败且 ad_auth.enabled 时触发；域验证失败一律返回 None
    （调用方回退本地错误提示），不泄露域内账号信息。
    """
    from app.core.config import get_config

    cfg = get_config().ad_auth
    if not cfg.enabled or not cfg.server or not username or not password:
        return None
    try:
        import ldap3
    except ImportError:
        return None
    try:
        server = ldap3.Server(cfg.server, get_info=ldap3.NONE, connect_timeout=5)
        user_dn = f"{cfg.domain}\\{username}" if cfg.domain else username
        conn = ldap3.Connection(server, user=user_dn, password=password, authentication=ldap3.SIMPLE, auto_bind=True)
        try:
            conn.search(cfg.base_dn, f"(sAMAccountName={username})", attributes=["displayName", "mail"])
            display = ""
            if conn.entries:
                display = str(conn.entries[0].displayName) if conn.entries[0].displayName else ""
        finally:
            conn.unbind()
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            user = User(username=username, name=display or username, role="employee")
            db.add(user)
            db.commit()
            db.refresh(user)
        elif not user.is_active:
            return None
        return user
    except Exception:  # noqa: BLE001 域验证失败一律回退本地错误提示
        return None


# ---- IM 免登（OAuth 授权码换 JWT）----

@router.get("/platform-info")
def platform_info():
    """免登页用：哪些渠道启用 + OAuth 需要的公开标识（corp_id/app_id 本就出现在授权 URL 中）。"""
    cfg = get_config()
    return {
        "ad_auth": {"enabled": cfg.ad_auth.enabled},
        "dingtalk": {"enabled": cfg.dingtalk.enabled, "corp_id": cfg.dingtalk.client_id},
        "feishu": {"enabled": cfg.feishu.enabled, "app_id": cfg.feishu.app_id},
        "wecom": {"enabled": cfg.wecom.enabled, "corp_id": cfg.wecom.corp_id, "agent_id": cfg.wecom.agent_id},
    }


@router.post("/dingtalk-code")
def dingtalk_code_login(body: dict, db: Session = Depends(get_db)):
    code = (body or {}).get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    try:
        user = login_by_dingtalk_code(db, code)
    except PlatformAuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"token": create_access_token(user.id, user.role), "user": user.to_dict()}


@router.post("/feishu-code")
def feishu_code_login(body: dict, db: Session = Depends(get_db)):
    code = (body or {}).get("code", "")
    redirect_uri = (body or {}).get("redirect_uri", "")
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    try:
        user = login_by_feishu_code(db, code, redirect_uri)
    except PlatformAuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"token": create_access_token(user.id, user.role), "user": user.to_dict()}


@router.post("/wecom-code")
def wecom_code_login(body: dict, db: Session = Depends(get_db)):
    code = (body or {}).get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    try:
        user = login_by_wecom_code(db, code)
    except PlatformAuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"token": create_access_token(user.id, user.role), "user": user.to_dict()}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    from app.core.permissions import effective_perms

    d = user.to_dict()
    d["perms"] = sorted(effective_perms(user))
    return d


@router.post("/change-password")
def change_password(body: PasswordChangeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.password_hash and not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}
