"""数据库会话（MySQL + SQLAlchemy 同步）。

Node 版是 better-sqlite3 全局单例；此处每请求一个 Session。
为降低翻译成本，业务层使用轻量 row-returning 模式（TextClause 查询），
配合 result_to_dict 转为 dict，与 Node 的 db.prepare(...).all()/get() 语义对齐。
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import (
    database_pool_settings_from_config,
    database_timezone_from_config,
    database_url_from_config,
    load_config,
)

engine = None
SessionLocal: sessionmaker | None = None


def init_engine(url: str | None = None) -> None:
    global engine, SessionLocal
    if engine is not None:
        return
    cfg = load_config()
    url = url or database_url_from_config(cfg)
    pool_settings = database_pool_settings_from_config(cfg)
    connect_args: dict[str, Any] = {}
    if make_url(url).get_backend_name() == "mysql":
        timezone_offset = database_timezone_from_config(cfg)
        # PyMySQL 会在每条新建或断线后重建的物理连接上执行初始化命令。
        connect_args["init_command"] = f"SET time_zone = '{timezone_offset}'"
        connect_args["connect_timeout"] = pool_settings["connect_timeout_seconds"]
        connect_args["read_timeout"] = max(pool_settings.get("read_timeout_seconds", 300), 300)
        connect_args["write_timeout"] = max(pool_settings.get("write_timeout_seconds", 300), 300)
    engine = create_engine(
        url,
        connect_args=connect_args,
        # 每次从池中借出连接前执行探活；失效连接会被废弃并自动重建。
        pool_pre_ping=True,
        pool_size=pool_settings["pool_size"],
        max_overflow=pool_settings["max_overflow"],
        pool_timeout=pool_settings["pool_timeout_seconds"],
        pool_recycle=pool_settings["pool_recycle_seconds"],
        # 优先复用最近使用的连接，让长期空闲连接自然进入回收，降低断链概率。
        pool_use_lifo=True,
        pool_reset_on_return="rollback",
        future=True,
    )
    if make_url(url).get_backend_name() == "mysql":
        import socket
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _set_socket_keepalive(dbapi_connection: Any, connection_record: Any) -> None:
            """在 PyMySQL 建立的底层 socket 上设置 TCP KeepAlive。"""
            sock = getattr(dbapi_connection, "sock", None) or getattr(dbapi_connection, "_sock", None)
            if sock is not None and hasattr(sock, "setsockopt"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                except OSError:
                    pass
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session_factory() -> sessionmaker:
    """获取或初始化全局 SessionLocal 工厂。"""
    global SessionLocal
    if SessionLocal is None:
        init_engine()
    if SessionLocal is None:
        raise RuntimeError("数据库 SessionLocal 初始化失败")
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    """请求级会话：正常路径提交（对齐 Node better-sqlite3 语句级自动持久化）。"""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """后台任务级上下文：发生异常时 rollback，正常退出时 commit，退出后关闭。"""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_engine() -> None:
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    engine = None
    SessionLocal = None


def result_to_dict(row: Any) -> dict[str, Any]:
    """把 SQLAlchemy Row 转为 dict（近似 better-sqlite3 的 .get() 返回对象）。"""
    if row is None:
        return None
    return dict(row._mapping)


def rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [result_to_dict(r) for r in rows]


def scalar(db: Session, sql: str, params: dict | None = None) -> Any:
    """执行 SELECT 取首行首列（近似 db.prepare(...).pluck().get()）。"""
    row = db.execute(text(sql), params or {}).first()
    return row[0] if row else None


def _is_disconnect_error(exc: Exception) -> bool:
    """判断是否为底层数据库连接断开或超时错误。"""
    err_msg = str(exc).lower()
    return any(
        kw in err_msg
        for kw in (
            "lost connection",
            "gone away",
            "winerror 10060",
            "winerror 10054",
            "broken pipe",
            "connection reset",
            "closed connection",
            "can't connect to mysql server",
        )
    )


def fetch_one(db: Session, sql: str, params: dict | None = None) -> dict[str, Any] | None:
    try:
        row = db.execute(text(sql), params or {}).first()
        return result_to_dict(row)
    except Exception as e:
        if _is_disconnect_error(e):
            db.rollback()
            row = db.execute(text(sql), params or {}).first()
            return result_to_dict(row)
        raise


def fetch_all(db: Session, sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    try:
        return rows_to_dicts(db.execute(text(sql), params or {}).all())
    except Exception as e:
        if _is_disconnect_error(e):
            db.rollback()
            return rows_to_dicts(db.execute(text(sql), params or {}).all())
        raise


def execute(db: Session, sql: str, params: dict | None = None) -> Any:
    try:
        return db.execute(text(sql), params or {})
    except Exception as e:
        if _is_disconnect_error(e):
            db.rollback()
            return db.execute(text(sql), params or {})
        raise
