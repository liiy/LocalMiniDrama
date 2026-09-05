"""资产版本树与级联失效服务（Asset Cascade & Stale Management）。
实现：
1. 角色外观/Prompt、场景 Prompt 发生变更时，自动定位依赖该角色/场景的下游分镜与视频生成记录；
2. 自动将其标记为“已失效 (stale)”状态；
3. 提供一键增量重跑 (incremental rerun) 接口，仅重新生成被标记为 stale 的分镜图像与视频。
"""
from __future__ import annotations

from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import fetch_all, fetch_one, result_to_dict

log = get_logger("lmd.cascade")


def mark_storyboards_stale_for_character(
    db: Session,
    character_id: int,
    reason: str = "character_appearance_changed",
) -> dict[str, Any]:
    """当角色形象/Prompt改变时，级联将关联的分镜图与视频标记为 stale。"""
    now = timestamp()
    # 查找角色名称
    char_row = fetch_one(db, "SELECT name, drama_id FROM characters WHERE id = :cid", {"cid": character_id})
    char_name = (char_row.get("name") if char_row else "") or ""

    # 查找关联此角色的分镜（通过 characters JSON/文本匹配 ID 或 角色名）
    rows = fetch_all(
        db,
        """
        SELECT s.id, s.episode_id, s.storyboard_number, s.title, s.status, s.image_url, s.video_url
        FROM storyboards s
        WHERE (s.characters LIKE :cid_like OR (:cname <> '' AND s.characters LIKE :cname_like))
          AND s.deleted_at IS NULL
        """,
        {
            "cid_like": f"%{character_id}%",
            "cname": char_name,
            "cname_like": f"%{char_name}%" if char_name else "___NONE___",
        },
    )
    storyboard_ids = list({r["id"] for r in rows})
    if not storyboard_ids:
        return {"affected_storyboards": 0, "affected_images": 0, "affected_videos": 0, "storyboard_ids": []}

    # 标记 storyboards 表为 stale
    placeholders = ", ".join(f":s_{i}" for i in range(len(storyboard_ids)))
    params = {f"s_{i}": sid for i, sid in enumerate(storyboard_ids)}
    params["now"] = now
    params["reason"] = reason

    db.execute(
        text(
            f"""
            UPDATE storyboards
            SET status = 'stale', updated_at = :now,
                error_msg = CASE WHEN error_msg IS NULL OR error_msg = '' THEN :reason ELSE error_msg || ';' || :reason END
            WHERE id IN ({placeholders})
            """
        ),
        params,
    )

    # 标记 image_generations
    db.execute(
        text(
            f"""
            UPDATE image_generations
            SET status = 'stale', updated_at = :now
            WHERE storyboard_id IN ({placeholders}) AND status = 'completed'
            """
        ),
        params,
    )

    # 标记 video_generations
    db.execute(
        text(
            f"""
            UPDATE video_generations
            SET status = 'stale', updated_at = :now
            WHERE storyboard_id IN ({placeholders}) AND status = 'completed'
            """
        ),
        params,
    )

    log.info(
        f"[Cascade] Marked {len(storyboard_ids)} storyboards stale due to character {character_id} drift"
    )
    return {
        "affected_storyboards": len(storyboard_ids),
        "storyboard_ids": storyboard_ids,
        "reason": reason,
    }


def mark_storyboards_stale_for_scene(
    db: Session,
    scene_id: int,
    reason: str = "scene_prompt_changed",
) -> dict[str, Any]:
    """当场景 Prompt 改变时，级联将属于该场景的分镜图与视频标记为 stale。"""
    now = timestamp()
    rows = fetch_all(
        db,
        "SELECT id FROM storyboards WHERE scene_id = :sid AND deleted_at IS NULL",
        {"sid": scene_id},
    )
    storyboard_ids = [r["id"] for r in rows]
    if not storyboard_ids:
        return {"affected_storyboards": 0, "storyboard_ids": []}

    placeholders = ", ".join(f":s_{i}" for i in range(len(storyboard_ids)))
    params = {f"s_{i}": sid for i, sid in enumerate(storyboard_ids)}
    params["now"] = now
    params["reason"] = reason

    db.execute(
        text(
            f"""
            UPDATE storyboards
            SET status = 'stale', updated_at = :now,
                error_msg = CASE WHEN error_msg IS NULL OR error_msg = '' THEN :reason ELSE error_msg || ';' || :reason END
            WHERE id IN ({placeholders})
            """
        ),
        params,
    )

    db.execute(
        text(
            f"""
            UPDATE image_generations
            SET status = 'stale', updated_at = :now
            WHERE storyboard_id IN ({placeholders}) AND status = 'completed'
            """
        ),
        params,
    )

    db.execute(
        text(
            f"""
            UPDATE video_generations
            SET status = 'stale', updated_at = :now
            WHERE storyboard_id IN ({placeholders}) AND status = 'completed'
            """
        ),
        params,
    )

    log.info(f"[Cascade] Marked {len(storyboard_ids)} storyboards stale due to scene {scene_id} drift")
    return {
        "affected_storyboards": len(storyboard_ids),
        "storyboard_ids": storyboard_ids,
        "reason": reason,
    }


def get_stale_assets_summary(db: Session, drama_id: int) -> dict[str, Any]:
    """获取指定剧集中所有标记为失效（stale）的资产统计与分镜列表。"""
    rows = fetch_all(
        db,
        """
        SELECT s.id, s.episode_id, s.scene_id, s.storyboard_number, s.title, s.status, s.image_url, s.video_url, s.error_msg
        FROM storyboards s
        JOIN episodes e ON s.episode_id = e.id
        WHERE e.drama_id = :did AND s.status = 'stale' AND s.deleted_at IS NULL
        ORDER BY s.episode_id ASC, s.storyboard_number ASC
        """,
        {"did": drama_id},
    )
    return {
        "drama_id": drama_id,
        "stale_count": len(rows),
        "stale_storyboards": rows,
    }


def rerun_stale_assets(db: Session, drama_id: int, asset_type: str = "all") -> dict[str, Any]:
    """一键增量重跑：将处于 stale 状态的分镜重置为 pending，以便工作流或批处理重新调度。"""
    now = timestamp()
    rows = fetch_all(
        db,
        """
        SELECT s.id
        FROM storyboards s
        JOIN episodes e ON s.episode_id = e.id
        WHERE e.drama_id = :did AND s.status = 'stale' AND s.deleted_at IS NULL
        """,
        {"did": drama_id},
    )
    storyboard_ids = [r["id"] for r in rows]
    if not storyboard_ids:
        return {"requeued_count": 0, "storyboard_ids": []}

    placeholders = ", ".join(f":s_{i}" for i in range(len(storyboard_ids)))
    params = {f"s_{i}": sid for i, sid in enumerate(storyboard_ids)}
    params["now"] = now

    db.execute(
        text(
            f"""
            UPDATE storyboards
            SET status = 'pending', updated_at = :now, error_msg = NULL
            WHERE id IN ({placeholders})
            """
        ),
        params,
    )

    return {
        "requeued_count": len(storyboard_ids),
        "storyboard_ids": storyboard_ids,
        "status": "requeued",
    }
