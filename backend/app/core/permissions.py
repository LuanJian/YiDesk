"""岗位权限分级（v2.4）：角色（admin/engineer/employee）× 岗位（ops_type）双维度。

- 岗位仅对 engineer 生效：admin 恒为全量，employee 无 staff 权限
- 岗位取值：remote 远程运维 / field 现场运维 / other 其他
- 权限矩阵在此一处定义（PERM_MATRIX），后端是唯一执行点，前端依据
  /auth/me 返回的 perms 列表控制菜单/按钮显隐
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.models.user import User

OPS_TYPES = ("remote", "field", "other")
OPS_TYPE_LABELS = {"remote": "远程运维", "field": "现场运维", "other": "其他"}

# 全部权限键（矩阵之外不存在隐式权限）
PERM_ALL = "assets.read assets.write licenses.read licenses.write devices.read devices.write compliance qr-tags analytics"
PERM_KEYS = set(PERM_ALL.split())

# 岗位 → 权限矩阵（工单侧能力三类一致，范围隔离走 category_scope）
# v2.11：全部工程师可管理资产、查看软件许可与网络设备；差异仅保留设备写/合规/二维码标签（现场专属）
_PERM_ENGINEER_BASE = {"assets.read", "assets.write", "licenses.read", "devices.read", "analytics"}
PERM_MATRIX: dict[str, set[str]] = {
    "remote": set(_PERM_ENGINEER_BASE),
    "field": _PERM_ENGINEER_BASE | {"devices.write", "compliance", "qr-tags"},
    "other": set(_PERM_ENGINEER_BASE),
}


def effective_perms(user: User) -> set[str]:
    """用户的有效权限集合。admin 全量；engineer 按岗位矩阵；employee 空。"""
    if user.role == "admin":
        return set(PERM_KEYS)
    if user.role == "engineer":
        return set(PERM_MATRIX.get(user.ops_type or "other", set()))
    return set()


def user_has_perm(user: User, perm: str) -> bool:
    return perm in effective_perms(user)


def require_perm(perm: str):
    """端点依赖：staff 且持有指定权限（管理员恒通过）。"""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if not user_has_perm(user, perm):
            raise HTTPException(status_code=403, detail="当前岗位无此操作权限")
        return user

    return _checker
