from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.platform_common import now_iso
from app.tools.screenplay_feature_scanner import is_valid_character_speaker
from app.tools.shot_duration_calculator import clean_dialogue_text
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer
from app.schemas.script_graph_state import (
    AudioBible,
    CandidateTitleMatrix,
    CharacterAnchorStub,
    DoubleTrackProhibitions,
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    InterEpisodePhysicalContinuity,
    LiteraryScreenplayEpisodeModel,
    PropAnchorStub,
    RedBlueAuditReport,
    SceneAnchorStub,
    SeasonOutlineCard,
    StoryboardShot,
    StoryboardShotStub,
)
from app.workflows.adapters.stage_adapters.common import (
    _safe_json_loads,
    _ensure_valid_json_str,
    _dump_or_dict,
    _flatten_asset_collection,
    _get_table_columns,
    sync_stage_memories_to_vector_db,
    persist_audit_report,
    fetch_all,
    fetch_one,
    get_short_memories,
    publish_drama_event,
    publish_drama_read_projection,
    publish_episode_read_projection,
    set_short_memories,
)

log = get_logger("lmd.storage_adapter")

# =========================================================================
# 阶段 1：题材立项、双轨禁令与高概念持久化
# =========================================================================

def persist_stage1(db: Session, drama_id: int, state: GlobalDramaMasterState | Any) -> None:
    """阶段 1 原子落库：更新短剧主表核心字段、高概念设定与短期记忆便签 A。"""
    log.info("【阶段 1 落库】开始持久化短剧 [%s] 的题材立项与高概念信息...", drama_id)
    now = now_iso()
    drama_row = fetch_one(db, "SELECT * FROM dramas WHERE id = :id", {"id": drama_id})
    if not drama_row:
        raise ValueError(f"Drama with ID {drama_id} does not exist.")

    current_meta = _safe_json_loads(drama_row.get("metadata"), {})
    
    # 同步阶段 1 核心元数据
    candidate_titles_val = getattr(state, "candidate_titles", None)
    negative_rules_val = getattr(state, "negative_rules", None)
    latest_audit_val = getattr(state, "latest_audit", None)
    user_idea_val = (
        getattr(state, "user_idea", "")
        or (state.get("user_idea") if hasattr(state, "get") else "")
        or (state.get("user_prompt") if hasattr(state, "get") else "")
        or ""
    )
    
    current_meta["user_idea"] = user_idea_val
    current_meta["candidate_titles"] = _dump_or_dict(candidate_titles_val) if candidate_titles_val else {}
    current_meta["negative_rules"] = _dump_or_dict(negative_rules_val) if negative_rules_val else {}
    current_meta["aspect_ratio"] = getattr(state, "aspect_ratio", "9:16")
    current_meta["target_duration_sec"] = getattr(state, "target_duration_sec", 120.0)
    current_meta["visual_style"] = getattr(state, "visual_style", "")
    current_meta["logline"] = getattr(state, "logline", "")
    current_meta["mechanism"] = getattr(state, "mechanism", "")
    current_meta["arc_type"] = getattr(state, "arc_type", "")
    current_meta["derivation"] = getattr(state, "derivation", None)
    current_meta["dramatic_irony"] = getattr(state, "dramatic_irony", "") or getattr(state, "core_irony", "")
    current_meta["grand_payoff"] = getattr(state, "grand_payoff", "")
    current_meta["current_stage"] = 1
    current_meta["journey"] = "journey_1_literary"
    current_meta["latest_audit"] = _dump_or_dict(latest_audit_val) if latest_audit_val else {}
    current_meta["blueprint"] = getattr(state, "blueprint", None)

    title_val = getattr(state, "selected_title", "") or getattr(state, "title", "") or drama_row.get("name") or drama_row.get("title") or "未定名短剧"

    # 更新 dramas 主表独立列与 metadata JSON 列
    db.execute(
        text("""
            UPDATE dramas
            SET title = :title,
                description = :description,
                candidate_titles = :candidate_titles,
                negative_rules = :negative_rules,
                dramatic_irony = :dramatic_irony,
                grand_payoff = :grand_payoff,
                current_stage = 1,
                pipeline_status = 'running',
                metadata = :metadata,
                updated_at = :updated_at
            WHERE id = :id
        """),
        {
            "id": drama_id,
            "title": title_val,
            "description": state.logline or "",
            "candidate_titles": json.dumps(state.candidate_titles.model_dump() if hasattr(state.candidate_titles, "model_dump") else (state.candidate_titles or {}), ensure_ascii=False),
            "negative_rules": json.dumps(state.negative_rules.model_dump() if hasattr(state.negative_rules, "model_dump") else (state.negative_rules or {}), ensure_ascii=False),
            "dramatic_irony": state.dramatic_irony or "",
            "grand_payoff": state.grand_payoff or "",
            "metadata": json.dumps(current_meta, ensure_ascii=False),
            "updated_at": now,
        },
    )

    # 长期记忆自动入库与向量化（剧目立项与高概念）
    stage1_memories = [
        {
            "title": f"剧目立项高概念: {title_val}",
            "content": f"剧名: {title_val}\n题材: {state.genre}\n视觉风格: {state.visual_style}\n用户核心构想: {user_idea_val}\n一句话梗概: {state.logline}\n核心讽刺/戏剧反差: {state.dramatic_irony}\n大结局终局释放: {state.grand_payoff}",
            "summary": f"{state.genre}题材，{state.logline}",
            "keywords": [state.genre or "短剧", state.visual_style or "现实", "高概念", "立项"],
            "memory_type": "world_bible",
            "source_type": "stage1_high_concept",
            "source_id": f"drama_{drama_id}_high_concept",
        }
    ]
    sync_stage_memories_to_vector_db(db, drama_id, 1, stage1_memories)

    # 记录质检报告
    if state.latest_audit:
        persist_audit_report(db, drama_id, 1, state.latest_audit)

    db.commit()
    log.info("【阶段 1 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 2：角色引擎、心理四元组与全覆盖双轨关系网持久化
# =========================================================================

