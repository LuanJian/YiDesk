"""后台访问安全密钥准入（第二十一批引入，第四十六批从 main.py 抽取为独立模块）。

密钥按账号存储（User.gate_key），管理员/工程师在「我的安全密钥」自助生成；
访问 /gate/{key} 换取准入 Cookie（HttpOnly，30 天），之后即可正常登录后台。
旧版 config.yaml 全局密钥在启动时一次性迁移给首位 admin 后清除（旧准入链接不失效）。

注意：本路由挂载在根路径（/gate/{key}，不带 /api 前缀）——准入链接会印在贴纸/弹窗上，
路径必须稳定简短；main.py 中单独 include_router(gate_router)。
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.core.config import get_config
from app.models.database import create_session
from app.models.user import User

logger = logging.getLogger("api.gate")

router = APIRouter()


def _config_path() -> Path:
    """与 config.load_config 同源：ITOPS_CONFIG 环境变量优先，默认 cwd 下 config.yaml。"""
    return Path(os.environ.get("ITOPS_CONFIG", Path.cwd() / "config.yaml"))


def migrate_legacy_gate() -> None:
    """旧版全局密钥迁移：config.yaml 仍保留 gate_key 且首位在职 admin 未设密钥时迁移过去，
    随后清除配置项（内存 + YAML 文件），旧准入链接不失效。

    第四十六批：由每次 /gate/{key} 请求时执行改为启动时执行一次（一次性数据迁移
    不应挂在请求路径上）；迁移失败仅记录日志，不阻塞启动。
    """
    cfg = get_config()
    legacy = getattr(cfg, "gate_key", "")
    if not legacy:
        return
    try:
        s = create_session()
        admin_user = s.scalar(
            select(User).where(User.role == "admin", User.is_active.is_(True)).order_by(User.id)
        )
        if admin_user and not admin_user.gate_key:
            admin_user.gate_key = legacy
            s.commit()
        s.close()
        cfg.gate_key = ""
        gate_path = _config_path()
        if gate_path.exists():
            raw = yaml.safe_load(gate_path.read_text(encoding="utf-8")) or {}
            if "gate_key" in raw:
                raw.pop("gate_key")
                gate_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        logger.info("旧版全局密钥已迁移给首位 admin 并从 config.yaml 清除")
    except Exception:  # noqa: BLE001
        logger.exception("旧版全局密钥迁移失败（跳过，不影响启动）")


@router.get("/gate/{key}", include_in_schema=False)
def gate_entry(key: str):  # noqa: ANN202
    """准入链接：密钥命中未停用的 admin/engineer 账号时签发 30 天准入 Cookie 并跳登录页；
    未命中一律 404（不暴露密钥是否存在）。"""
    s = create_session()
    user = s.scalar(select(User).where(User.gate_key == key, User.is_active.is_(True)))
    logger.info("gate 准入: key=%s... 命中=%s", key[:10], user.username if user else "无（密钥不匹配或已重置）")
    if not user or user.role not in ("admin", "engineer"):
        s.close()
        raise HTTPException(status_code=404, detail="Not Found")
    resp = RedirectResponse("/login", status_code=302)
    resp.set_cookie(
        "itops_gate",
        hashlib.sha256((user.gate_key or "").encode()).hexdigest(),
        max_age=30 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    s.close()
    return resp
