"""应用入口：初始化数据库、挂载 API、启动渠道长连接与定时任务、托管前端静态文件。

单进程部署：uvicorn app.main:app --host 0.0.0.0 --port 8300（务必单 worker，
渠道长连接与调度器都挂在进程内）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.api.gate import migrate_legacy_gate, router as gate_router  # 第四十六批：/gate 准入抽取为独立模块
from app.channels.registry import registry
from app.core.config import get_config
from app.models.database import Base, create_session, get_engine, init_engine
from app.models.user import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _seed(db) -> None:
    """首启初始化：管理员账号、SLA 规则。"""
    from sqlalchemy import func, select

    from app.core.security import hash_password
    from app.models.system import SlaRule

    if not db.scalar(select(func.count()).select_from(User)):
        cfg = get_config()
        db.add(
            User(
                username=cfg.admin_username,
                name=cfg.admin_name,
                role="admin",
                password_hash=hash_password(cfg.admin_password),
            )
        )
        logger.info("已创建初始管理员: %s", cfg.admin_username)
    if not db.scalar(select(func.count()).select_from(SlaRule)):
        cfg = get_config().sla
        for p in ("low", "medium", "high", "urgent"):
            rule = getattr(cfg, p)
            db.add(SlaRule(priority=p, response_minutes=rule.response_minutes, resolve_minutes=rule.resolve_minutes))
    db.commit()


def _build_adapters() -> None:
    cfg = get_config()
    if cfg.dingtalk.enabled:
        from app.channels.dingtalk import DingTalkAdapter

        registry.register(DingTalkAdapter(cfg.dingtalk))
        logger.info("钉钉渠道已启用（Stream 模式）")
    if cfg.feishu.enabled:
        from app.channels.feishu import FeishuAdapter

        registry.register(FeishuAdapter(cfg.feishu))
        logger.info("飞书渠道已启用（长连接模式）")
    if cfg.wecom.enabled:
        from app.channels.wecom import WeComAdapter

        registry.register(WeComAdapter(cfg.wecom))
        logger.info("企业微信渠道已启用（应用消息）")
    if cfg.mail.enabled:
        from app.channels.mail import MailAdapter

        registry.register(MailAdapter(cfg.mail))
        logger.info("邮件通知渠道已启用（SMTP %s）", cfg.mail.smtp_host)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.jobs import scheduler as jobs

    db = create_session()
    try:
        _seed(db)
    finally:
        db.close()
    _build_adapters()
    registry.start_all()
    jobs.start()
    logger.info("%s 启动完成", get_config().app_name)
    yield
    jobs.shutdown()
    registry.stop_all()


def create_app() -> FastAPI:
    cfg = get_config()
    init_engine(cfg.resolved_database_url())
    from app.models.meeting import MeetingBooking, MeetingRoom, RoomInspection  # noqa: F401 注册会议室三表到 metadata
    from app.models.qr import QrTag  # noqa: F401 注册 qr_tags 到 metadata（create_all 建表）
    from app.models.login_log import LoginLog  # noqa: F401 注册登录日志到 metadata（create_all 建表）
    from app.models.upgrade import ensure_columns

    Base.metadata.create_all(get_engine())
    ensure_columns()  # 旧库升级：assets 补 ip_address/model 列

    app = FastAPI(title=cfg.app_name, lifespan=lifespan)
    app.include_router(api_router, prefix="/api")

    # 第四十六批：/gate/{key} 准入路由与旧版全局密钥迁移抽取至 app/api/gate.py；
    # 准入路由挂根路径（不带 /api 前缀，准入链接印在贴纸上须稳定）；迁移为一次性动作移到启动时执行
    app.include_router(gate_router)
    migrate_legacy_gate()


    # 前端构建产物托管（SPA 回退到 index.html）
    if (FRONTEND_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):  # noqa: ANN202
            if full_path.startswith(("api/", "docs", "openapi.json", "redoc")):
                return FileResponse(FRONTEND_DIST / "index.html", status_code=404)
            candidate = (FRONTEND_DIST / full_path).resolve()
            if full_path and candidate.is_file() and str(candidate).startswith(str(FRONTEND_DIST)):
                return FileResponse(candidate)
            # index.html 不缓存：版本更新后 hash chunk 引用立即生效，避免旧缓存白屏
            return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
