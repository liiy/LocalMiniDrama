"""Context Builder 上下文统一组装与快照归档服务。

【架构定位与职责】
1. 统一构建 Agent 与 Prompt 的上下文输入包：
   - 汇集全剧大纲（Drama Bible）、单集剧本（Episode Script）、角色人设库（Character Profiles）、场景库（Scene Profiles）、道具库（Prop Profiles）、前后分镜连续性镜头（Nearby Storyboards）；
   - 汇集小说章节切片（Novel Slices）与世界观设定（Worldview & Memory Items）等长期记忆，确保第 N 集创作时角色关系、道具设定与原著名场面依然保持强一致性。
2. 上下文 Token 预估与裁剪：
   - 估算拼装上下文的 Token 消耗，防止超出大模型上下文窗口或产生不必要的 Token 计费。
3. 上下文快照归档（Context Snapshots）：
   - 将组装后的上下文输入固化落库到 `context_snapshots` 表中，与 `prompt_runs` 和 `workflow_runs` 关联，形成可追溯、可复现、可审计的数据链路。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import compact_dict, json_dumps, json_loads, now_iso


def _limit_text(value: Any, limit: int = 4000) -> str:
    """对超长文本做安全截断，防止单字段爆出超大 Token。"""
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
    query: str | None = None,
) -> dict[str, Any]:
    """构建一次 Agent/Prompt 可用的统一上下文包。

    参数说明：
    - drama_id: 短剧项目 ID
    - episode_id: 当前单集 ID（可选）
    - storyboard_id: 当前分镜镜头 ID（可选）
    - skill_key: 消费该上下文的能力技能标识（可选）
    - include_memory: 是否拉取长期记忆与小说切片（默认 True）
    - query: 针对长期记忆检索的关键词或语义查询（可选）
    """
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
        "novel_slices": [],
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

        # 分镜 Agent 常需要前后镜头维持视觉/情节连续性，默认取整集分镜的轻量字段
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
            # 提取常规记忆项（设定、伏笔、重要事件）
            m_items = fetch_all(
                db,
                """
                SELECT id, memory_type, scope, title, summary, keywords, source_type, source_id
                FROM memory_items
                WHERE drama_id = :drama_id AND memory_type != 'novel_slice' AND deleted_at IS NULL
                ORDER BY updated_at DESC, id DESC
                LIMIT 50
                """,
                {"drama_id": drama_id},
            )
            for m in m_items:
                m["keywords"] = json_loads(m.get("keywords"), [])
            context["memory_items"] = m_items

            # 提取小说章节切片长期记忆（保持原著名场面一致性）
            n_slices = fetch_all(
                db,
                """
                SELECT id, title, summary, content, keywords, metadata
                FROM memory_items
                WHERE drama_id = :drama_id AND memory_type = 'novel_slice' AND deleted_at IS NULL
                ORDER BY id ASC
                LIMIT 100
                """,
                {"drama_id": drama_id},
            )
            for sl in n_slices:
                sl["keywords"] = json_loads(sl.get("keywords"), [])
                sl["metadata"] = json_loads(sl.get("metadata"), {})
            context["novel_slices"] = n_slices

            if context["memory_items"] or context["novel_slices"]:
                sources.append(f"memory_items:drama:{drama_id}")

    return {
        "skill_key": skill_key,
        "drama_id": drama_id,
        "episode_id": episode_id,
        "storyboard_id": storyboard_id,
        "content": context,
        "source_refs": sources,
        "token_estimate": _estimate_tokens(context),
        "novel_slices": context.get("novel_slices", []),
        "memory_items": context.get("memory_items", []),
    }


def save_context_snapshot(
    db: Session, context_payload: dict[str, Any], workflow_run_id: str | None = None
) -> dict[str, Any]:
    """保存上下文快照，保证 Prompt Run 与 Workflow 审计后续可以复盘当时模型看到的全部环境数据。"""
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
    row = result_to_dict(db.execute(text("SELECT * FROM context_snapshots WHERE id = :id"), {"id": res.lastrowid}).first())
    if row:
        row["content"] = json_loads(row.get("content"), {})
        row["source_refs"] = json_loads(row.get("source_refs"), [])
    return row or {}


def get_context_snapshot(db: Session, snapshot_id: int) -> dict[str, Any] | None:
    """获取单个上下文快照的详细内容。"""
    row = fetch_one(db, "SELECT * FROM context_snapshots WHERE id = :id", {"id": int(snapshot_id)})
    if not row:
        return None
    data = compact_dict(row) or {}
    data["content"] = json_loads(data.get("content"), {})
    data["source_refs"] = json_loads(data.get("source_refs"), [])
    return data


