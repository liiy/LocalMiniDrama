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


def mark_downstream_episodes_stale(
    db: Session,
    drama_id: int,
    modified_episode_num: int,
    reason: str = "upstream_script_modified",
) -> dict[str, Any]:
    """当第 N 集大纲或正文修改时，级联将 N+1 集及其下游视听资产全部标记为 stale。

    严格遵循《详细设计说明书（V2.0 工业增强版）》：
    - 修改第 N 集后，N+1 至最后一集的 episode 记录将被标记 is_active=0 或 status='stale'；
    - 其关联的 storyboards 被标记为 stale；
    - 短剧全局版本游标 version_cursor 自增 +1。
    """
    now = timestamp()

    # 1. 查询所有后续集数
    ep_rows = fetch_all(
        db,
        """
        SELECT id, episode_number FROM episodes
        WHERE drama_id = :did AND episode_number > :ep_num AND deleted_at IS NULL
        ORDER BY episode_number ASC
        """,
        {"did": drama_id, "ep_num": modified_episode_num},
    )
    affected_ep_ids = [r["id"] for r in ep_rows]
    affected_ep_nums = [r["episode_number"] for r in ep_rows]

    if not affected_ep_ids:
        return {
            "drama_id": drama_id,
            "modified_episode_num": modified_episode_num,
            "affected_episodes": [],
            "affected_storyboards": 0,
            "new_version_cursor": None,
        }

    # 2. 标记下游分集与分镜为 stale
    placeholders = ", ".join(f":ep_{i}" for i in range(len(affected_ep_ids)))
    params = {f"ep_{i}": eid for i, eid in enumerate(affected_ep_ids)}
    params["now"] = now
    params["reason"] = f"{reason}_ep{modified_episode_num}"

    db.execute(
        text(
            f"""
            UPDATE episodes
            SET status = 'stale', updated_at = :now
            WHERE id IN ({placeholders}) AND deleted_at IS NULL
            """
        ),
        params,
    )

    sb_res = db.execute(
        text(
            f"""
            UPDATE storyboards
            SET status = 'stale', updated_at = :now,
                error_msg = CASE WHEN error_msg IS NULL OR error_msg = '' THEN :reason ELSE error_msg || ';' || :reason END
            WHERE episode_id IN ({placeholders}) AND deleted_at IS NULL
            """
        ),
        params,
    )

    # 3. 自增短剧项目的 version_cursor
    db.execute(
        text(
            """
            UPDATE dramas
            SET version_cursor = COALESCE(version_cursor, 1) + 1, updated_at = :now
            WHERE id = :did
            """
        ),
        {"did": drama_id, "now": now},
    )

    drama_row = fetch_one(db, "SELECT version_cursor FROM dramas WHERE id = :did", {"did": drama_id})
    new_cursor = drama_row.get("version_cursor") if drama_row else 2

    log.info(
        f"[Cascade] Upstream episode {modified_episode_num} modified in drama {drama_id}. "
        f"Marked downstream episodes {affected_ep_nums} and storyboards as stale. New cursor: {new_cursor}"
    )

    return {
        "drama_id": drama_id,
        "modified_episode_num": modified_episode_num,
        "affected_episodes_count": len(affected_ep_nums),
        "affected_episodes": affected_ep_nums,
        "affected_episode_ids": affected_ep_ids,
        "new_version_cursor": new_cursor,
        "status": "cascade_invalidated",
    }

