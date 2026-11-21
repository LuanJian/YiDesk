"""SQLAlchemy 引擎与会话。SQLite 起步，URL 可配置以迁移 MySQL/PostgreSQL。"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    pass


def init_engine(database_url: str) -> None:
    global _engine, _SessionLocal
    if database_url.startswith("sqlite"):
        db_file = database_url.split("///", 1)[-1]
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            database_url,
            # v2.12 高峰并发：写锁等待 30s（默认 5s 在工单提交高峰+扫描任务并存时易抛 database is locked）
            connect_args={"check_same_thread": False, "timeout": 30},
            # 连接池（v2.12 500 并发压测后显式化）：池内 20 + 溢出 30 = 峰值 50 连接；
            # 连接回收 1 小时，借出等待 30 秒
            pool_size=20,
            max_overflow=30,
            pool_recycle=3600,
            pool_timeout=30,
        )
        # SQLite 外键开关 + WAL 模式（v2.12 高峰并发：WAL 读写不互斥、写吞吐提升，
        # 500 并发建单压测下默认回滚日志模式会出现连接超时）
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    else:
        # v2.12 MySQL 连接池：池内 20 + 溢出 30 = 峰值 50 连接；
        # pool_recycle 3600s 防 MySQL wait_timeout 断连（需小于 MySQL 侧 wait_timeout）；
        # pool_pre_ping 每次借出前探活，断连自动重建
        _engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=30,
            pool_recycle=3600,
            pool_timeout=30,
        )
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def get_engine():
    if _engine is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_engine()")
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_engine()")
    return _SessionLocal


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def create_session() -> Session:
    """供后台线程（渠道长连接、定时任务）使用的一次性会话。"""
    return session_factory()()
