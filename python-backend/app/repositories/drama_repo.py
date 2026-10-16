"""Drama repository for dramas table access."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one
from app.repositories.base_repo import BaseRepository


class DramaRepository(BaseRepository):
    """Repository handling data access for dramas."""

    def get_by_id(self, db: Session, drama_id: int) -> dict[str, Any] | None:
        """根据 ID 获取未删除的短剧记录。"""
        sql = """
            SELECT id, title, description, genre, total_episodes, metadata, lock_status, locked_at
            FROM dramas
            WHERE id = :id AND deleted_at IS NULL
        """
        return fetch_one(db, sql, {"id": drama_id})

    def get_full_by_id(self, db: Session, drama_id: int) -> dict[str, Any] | None:
        """获取短剧完整信息。"""
        sql = "SELECT * FROM dramas WHERE id = :id AND deleted_at IS NULL"
        return fetch_one(db, sql, {"id": drama_id})

    def update_metadata(self, db: Session, drama_id: int, metadata_json: str) -> None:
        """更新短剧 metadata 字段。"""
        sql = "UPDATE dramas SET metadata = :metadata WHERE id = :id"
        db.execute(text(sql), {"id": drama_id, "metadata": metadata_json})

    def update_lock_status(
        self, db: Session, drama_id: int, lock_status: str, locked_at: str | None = None
    ) -> None:
        """更新短剧定稿锁状态与锁定时间。"""
        if locked_at:
            sql = "UPDATE dramas SET lock_status = :lock_status, locked_at = :locked_at WHERE id = :id"
            db.execute(text(sql), {"id": drama_id, "lock_status": lock_status, "locked_at": locked_at})
        else:
            sql = "UPDATE dramas SET lock_status = :lock_status WHERE id = :id"
            db.execute(text(sql), {"id": drama_id, "lock_status": lock_status})

    def list_all_active(self, db: Session) -> list[dict[str, Any]]:
        """获取所有未删除的短剧列表。"""
        sql = "SELECT id, title, genre, total_episodes, lock_status FROM dramas WHERE deleted_at IS NULL ORDER BY id DESC"
        return fetch_all(db, sql)


drama_repo = DramaRepository()
