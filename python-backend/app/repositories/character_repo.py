"""Character repository for characters table access."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one
from app.repositories.base_repo import BaseRepository


class CharacterRepository(BaseRepository):
    """Repository handling data access for characters."""

    def list_by_drama(self, db: Session, drama_id: int) -> list[dict[str, Any]]:
        """获取短剧关联的全部角色，按 sort_order 与 id 排序。"""
        sql = """
            SELECT id, drama_id, name, role, description, personality, appearance,
                   image_url, local_path, voice_style, identity_anchors, stages,
                   current_status, growth_chain, sort_order
            FROM characters
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            ORDER BY sort_order ASC, id ASC
        """
        return fetch_all(db, sql, {"drama_id": drama_id})

    def get_by_name(self, db: Session, drama_id: int, name: str) -> dict[str, Any] | None:
        """根据短剧 ID 与角色名称获取角色。"""
        sql = """
            SELECT * FROM characters
            WHERE drama_id = :drama_id AND name = :name AND deleted_at IS NULL
            LIMIT 1
        """
        return fetch_one(db, sql, {"drama_id": drama_id, "name": name})


character_repo = CharacterRepository()
