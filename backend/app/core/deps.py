"""FastAPI 依赖：数据库会话、当前用户、角色校验。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.security import decode_token

from app.models.database import get_db

from app.models.user import User

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:

    auth = request.headers.get("Authorization", "")

    if not auth.startswith("Bearer "):

        raise HTTPException(status_code=401, detail="未登录")

    payload = decode_token(auth.removeprefix("Bearer ").strip())

    if not payload:

        raise HTTPException(status_code=401, detail="登录已过期")

    user = db.get(User, int(payload["sub"]))

    if not user or not user.is_active:

        raise HTTPException(status_code=401, detail="账号不可用")

    return user

def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:

    """v2.11 扫码匿名提交：返回当前登录用户或 None（未认证不报错）。"""

    auth = request.headers.get("Authorization", "")

    if not auth.startswith("Bearer "):

        return None

    payload = decode_token(auth.removeprefix("Bearer ").strip())

    if not payload:

        return None

    user = db.get(User, int(payload["sub"]))

    if not user or not user.is_active:

        return None

    return user

def require_roles(*roles: str) -> Callable[[User], User]:

    def checker(user: User = Depends(get_current_user)) -> User:

        if user.role not in roles:

            raise HTTPException(status_code=403, detail="权限不足")

        return user

    return checker

require_admin = require_roles("admin")

require_staff = require_roles("admin", "engineer")  # 管理员或工程师

def find_user_by_platform(db: Session, channel: str, platform_id: str) -> User | None:

    col = {"dingtalk": User.dingtalk_userid, "feishu": User.feishu_open_id, "wecom": User.wecom_userid}.get(channel)

    if col is None:

        return None

    return db.scalar(select(User).where(col == platform_id))
