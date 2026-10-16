"""提示词覆盖：DB CRUD（等价 Node services/promptOverridesService.js）。

Node 用 SQLite 的 INSERT OR REPLACE；MySQL 等价为 INSERT ... ON DUPLICATE KEY UPDATE
（UNIQUE(key) 存在，效果一致：key 已存在则覆盖 content/updated_at）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one


def list_overrides(db: Session) -> list[dict]:
    return fetch_all(db, "SELECT `key`, content, updated_at FROM prompt_overrides ORDER BY `key`")


def get_override(db: Session, key: str) -> str | None:
    row = fetch_one(db, "SELECT content FROM prompt_overrides WHERE `key` = :key", {"key": key})
    return row["content"] if row else None


def set_override(db: Session, key: str, content: str) -> None:
    now = timestamp()
    execute(
        db,
        """
        INSERT INTO prompt_overrides (`key`, content, updated_at) VALUES (:key, :content, :updated_at)
        ON DUPLICATE KEY UPDATE content = :content, updated_at = :updated_at
        """,
        {"key": key, "content": content, "updated_at": now},
    )


def delete_override(db: Session, key: str) -> None:
    execute(db, "DELETE FROM prompt_overrides WHERE `key` = :key", {"key": key})
