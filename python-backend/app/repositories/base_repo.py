"""数据访问仓储层基类，统一封装数据库 Session 查询与执行操作。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, scalar


class BaseRepository:
    """数据仓储基类，统一提供单行、多行、聚合标量以及原生 SQL 执行辅助方法。"""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    def fetch_one(self, db: Session, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """执行查询并返回单行字典结果。"""
        return fetch_one(db, sql, params)

    def fetch_all(self, db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """执行查询并返回多行字典列表结果。"""
        return fetch_all(db, sql, params)

    def scalar(self, db: Session, sql: str, params: dict[str, Any] | None = None) -> Any:
        """执行聚合或单一标量值查询。"""
        return scalar(db, sql, params)

    def execute(self, db: Session, sql: str, params: dict[str, Any] | None = None) -> Any:
        """执行 DML 变更（INSERT / UPDATE / DELETE）。"""
        return db.execute(text(sql), params or {})
