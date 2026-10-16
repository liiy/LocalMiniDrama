"""Episode repository for episodes table access."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one
from app.repositories.base_repo import BaseRepository


class EpisodeRepository(BaseRepository):
    """Repository handling data access for episodes."""

    def get_by_number(self, db: Session, drama_id: int, episode_number: int) -> dict[str, Any] | None:
        """根据剧本 ID 和集号获取未删除的单集记录。"""
        sql = """
            SELECT id, drama_id, episode_number, title, content, word_count,
                   commercial_tag, script_state, ast_blocks, metadata
            FROM episodes
            WHERE drama_id = :did AND episode_number = :enum AND deleted_at IS NULL
        """
        return fetch_one(db, sql, {"did": drama_id, "enum": episode_number})

    def list_by_drama(self, db: Session, drama_id: int) -> list[dict[str, Any]]:
        """获取剧本下的所有单集（按集号递增排序）。"""
        sql = """
            SELECT id, drama_id, episode_number, title, content, word_count,
                   commercial_tag, script_state, ast_blocks, metadata
            FROM episodes
            WHERE drama_id = :did AND deleted_at IS NULL
            ORDER BY episode_number ASC
        """
        return fetch_all(db, sql, {"did": drama_id})

    def get_max_episode_number(self, db: Session, drama_id: int) -> int:
        """获取剧本已存在的最大集号。"""
        sql = "SELECT MAX(episode_number) as max_num FROM episodes WHERE drama_id = :did AND deleted_at IS NULL"
        row = fetch_one(db, sql, {"did": drama_id})
        return int(row["max_num"]) if row and row.get("max_num") is not None else 0

    def update_script_state(self, db: Session, drama_id: int, episode_number: int, script_state: str) -> None:
        """更新单集的剧本生成/锁定状态。"""
        sql = """
            UPDATE episodes
            SET script_state = :script_state
            WHERE drama_id = :did AND episode_number = :enum
        """
        db.execute(text(sql), {"did": drama_id, "enum": episode_number, "script_state": script_state})

    def update_content_and_ast(
        self,
        db: Session,
        drama_id: int,
        episode_number: int,
        content: str,
        word_count: int,
        ast_blocks_json: str | None = None,
        script_state: str | None = None,
    ) -> None:
        """更新单集的文本内容及解析后的 AST 块。"""
        updates = ["content = :content", "word_count = :word_count"]
        params: dict[str, Any] = {
            "did": drama_id,
            "enum": episode_number,
            "content": content,
            "word_count": word_count,
        }
        if ast_blocks_json is not None:
            updates.append("ast_blocks = :ast_blocks")
            params["ast_blocks"] = ast_blocks_json
        if script_state is not None:
            updates.append("script_state = :script_state")
            params["script_state"] = script_state

        sql = f"UPDATE episodes SET {', '.join(updates)} WHERE drama_id = :did AND episode_number = :enum"
        db.execute(text(sql), params)


episode_repo = EpisodeRepository()
