"""Context Builder。

统一组装 Agent 所需上下文，避免每个业务服务各自拼接不同版本的剧本、角色、
场景、道具和分镜信息。后续接入向量库时，可以在这里扩展长期记忆检索。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso


def _limit_text(value: Any, limit: int = 4000) -> str:
    text_value = str(value or "")
    return text_value if len(text_value) <= limit else text_value[:limit] + "...[truncated]"


def _estimate_tokens(payload: Any) -> int:
    """粗略估算上下文 Token；中文场景下按 2 字符约 1 token 估算即可用于预警。"""
    return max(1, len(json_dumps(payload)) // 2)


def build_context(
    db: Session,
    *,
    drama_id: int | None = None,
    episode_id: int | None = None,
    storyboard_id: int | None = None,
    skill_key: str | None = None,
    include_memory: bool = True,
) -> dict[str, Any]:
    """构建一次 Agent/Prompt 可用的上下文包。"""
    sources: list[str] = []
    context: dict[str, Any] = {
        "drama": None,
        "episode": None,
        "storyboard": None,
        "characters": [],
        "scenes": [],
        "props": [],
        "nearby_storyboards": [],
        "memory_items": [],
    }

    if storyboard_id:
        sb = fetch_one(db, "SELECT * FROM storyboards WHERE id = :id AND deleted_at IS NULL", {"id": storyboard_id})
        context["storyboard"] = sb
        if sb:
            episode_id = int(sb.get("episode_id") or episode_id or 0) or episode_id
            sources.append(f"storyboards:{storyboard_id}")

    if episode_id:
        episode = fetch_one(db, "SELECT * FROM episodes WHERE id = :id AND deleted_at IS NULL", {"id": episode_id})
        context["episode"] = episode
        if episode:
            drama_id = int(episode.get("drama_id") or drama_id or 0) or drama_id
            episode["script_content"] = _limit_text(episode.get("script_content"), 12000)
            sources.append(f"episodes:{episode_id}")

        # 分镜 Agent 常需要前后镜头维持连续性，这里默认取整集分镜的轻量字段。
        context["nearby_storyboards"] = fetch_all(
            db,
            """
            SELECT id, storyboard_number, title, description, action, dialogue, narration,
                   image_prompt, video_prompt, characters, duration, status
            FROM storyboards
            WHERE episode_id = :episode_id AND deleted_at IS NULL
            ORDER BY storyboard_number ASC, id ASC
            LIMIT 200
            """,
            {"episode_id": episode_id},
        )
        if context["nearby_storyboards"]:
            sources.append(f"storyboards:episode:{episode_id}")

    if drama_id:
        context["drama"] = fetch_one(db, "SELECT * FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": drama_id})
        if context["drama"]:
            context["drama"]["metadata"] = json_loads(context["drama"].get("metadata"), {})
            sources.append(f"dramas:{drama_id}")

        context["characters"] = fetch_all(
            db,
            """
            SELECT id, name, role, description, personality, appearance, voice_style,
                   identity_anchors, style_tokens, color_palette, polished_prompt
            FROM characters
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            ORDER BY sort_order ASC, id ASC
            LIMIT 200
            """,
            {"drama_id": drama_id},
        )
        context["scenes"] = fetch_all(
            db,
            """
            SELECT id, episode_id, location, time, prompt, polished_prompt, storyboard_count, status
            FROM scenes
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            ORDER BY id ASC
            LIMIT 200
            """,
            {"drama_id": drama_id},
        )
        context["props"] = fetch_all(
            db,
            """
            SELECT id, episode_id, name, type, description, prompt
            FROM props
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            ORDER BY id ASC
            LIMIT 200
            """,
            {"drama_id": drama_id},
        )
        sources.extend([f"characters:drama:{drama_id}", f"scenes:drama:{drama_id}", f"props:drama:{drama_id}"])

        if include_memory:
            context["memory_items"] = fetch_all(
                db,
                """
                SELECT id, memory_type, scope, title, summary, keywords, source_type, source_id
                FROM memory_items
                WHERE drama_id = :drama_id AND deleted_at IS NULL
                ORDER BY updated_at DESC, id DESC
                LIMIT 50
                """,
                {"drama_id": drama_id},
            )
            if context["memory_items"]:
                sources.append(f"memory_items:drama:{drama_id}")

    return {
        "skill_key": skill_key,
        "drama_id": drama_id,
        "episode_id": episode_id,
        "storyboard_id": storyboard_id,
        "content": context,
        "source_refs": sources,
        "token_estimate": _estimate_tokens(context),
    }


def save_context_snapshot(db: Session, context_payload: dict[str, Any], workflow_run_id: str | None = None) -> dict[str, Any]:
    """保存上下文快照，保证 Prompt Run 后续可以复盘当时模型到底看到了什么。"""
    scope_type = "global"
    scope_id = None
    if context_payload.get("storyboard_id"):
        scope_type = "storyboard"
        scope_id = str(context_payload["storyboard_id"])
    elif context_payload.get("episode_id"):
        scope_type = "episode"
        scope_id = str(context_payload["episode_id"])
    elif context_payload.get("drama_id"):
        scope_type = "drama"
        scope_id = str(context_payload["drama_id"])

    res = db.execute(
        text(
            """
            INSERT INTO context_snapshots (
                scope_type, scope_id, workflow_run_id, skill_key, content,
                token_estimate, source_refs, created_at
            ) VALUES (
                :scope_type, :scope_id, :workflow_run_id, :skill_key, :content,
                :token_estimate, :source_refs, :created_at
            )
            """
        ),
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "workflow_run_id": workflow_run_id,
            "skill_key": context_payload.get("skill_key"),
            "content": json_dumps(context_payload.get("content") or {}),
            "token_estimate": context_payload.get("token_estimate") or 0,
            "source_refs": json_dumps(context_payload.get("source_refs") or []),
            "created_at": now_iso(),
        },
    )
    return result_to_dict(db.execute(text("SELECT * FROM context_snapshots WHERE id = :id"), {"id": res.lastrowid}).first())

