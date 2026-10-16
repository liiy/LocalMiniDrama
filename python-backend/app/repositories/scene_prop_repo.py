"""Repository for scenes, props, and music bible database access."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one
from app.repositories.base_repo import BaseRepository


class SceneRepository(BaseRepository):
    """Repository handling data access for scenes."""

    def list_by_drama(self, db: Session, drama_id: int) -> list[dict[str, Any]]:
        """获取短剧关联的全部场景。"""
        sql = """
            SELECT id, drama_id, name, location_type, description, prompt,
                   image_url, local_path, atmosphere, lighting
            FROM scenes
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            ORDER BY id ASC
        """
        return fetch_all(db, sql, {"drama_id": drama_id})


class PropRepository(BaseRepository):
    """Repository handling data access for props."""

    def list_by_drama(self, db: Session, drama_id: int) -> list[dict[str, Any]]:
        """获取短剧关联的全部道具。"""
        sql = """
            SELECT id, drama_id, name, type, description, prompt, appearance,
                   image_url, local_path, significance
            FROM props
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            ORDER BY id ASC
        """
        return fetch_all(db, sql, {"drama_id": drama_id})


class MusicBibleRepository(BaseRepository):
    """Repository handling data access for music_bibles."""

    def get_latest_by_drama(self, db: Session, drama_id: int) -> dict[str, Any] | None:
        """获取短剧最新的配乐设计圣经。"""
        sql = """
            SELECT id, drama_id, overall_style, theme_prompt, instruments,
                   bpm_range, emotional_palette, mixing_rules, status
            FROM music_bibles
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            ORDER BY id DESC LIMIT 1
        """
        return fetch_one(db, sql, {"drama_id": drama_id})


scene_repo = SceneRepository()
prop_repo = PropRepository()
music_bible_repo = MusicBibleRepository()
