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

def persist_stage8(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 8 原子落库：写入 audio_generations 与 episodes.ast_blocks 的 audio_mastering。"""
    curr_ep = episode_num or getattr(state, "episode_number", None) or getattr(state, "episode_num", None) or getattr(state, "current_visual_episode", 1) or 1
    log.info("【阶段 8 落库】开始持久化短剧 [%s] 第 %s 集的声学混音工程...", drama_id, curr_ep)
    now = now_iso()

    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": curr_ep},
    )
    if hasattr(state, "audio_mastering") and state.audio_mastering:
        mastering_plan = _dump_or_dict(state.audio_mastering)
    else:
        mastering_plan = getattr(state, "audio_mastering_plans", {}).get(curr_ep, {})
    if ep_row:
        ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
        ep_ast["audio_mastering"] = mastering_plan
        db.execute(
            text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
            {"id": ep_row["id"], "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
        )

    # 长期记忆自动入库与向量化（全息混音与压限母带）
    if mastering_plan:
        stage8_memories = [
            {
                "title": f"第{curr_ep}集全息声学混音与动态压限母带方案",
                "content": f"第{curr_ep}集混音工程:\n母带动态压限(Ducking): 对白触发时音乐降低 -18dB\n音效轨道数: {len(mastering_plan.get('sfx_tracks', []))}\n配乐轨道数: {len(mastering_plan.get('music_tracks', []))}",
                "summary": f"第{curr_ep}集音频混音母带已完成",
                "keywords": [f"第{curr_ep}集", "音频母带", "混音", "Ducking"],
                "memory_type": "audio_mastering",
                "source_type": "stage8_mastering",
                "source_id": f"ep_audio_mastering_{curr_ep}",
            }
        ]
        sync_stage_memories_to_vector_db(db, drama_id, 8, stage8_memories)

    db.execute(
        text("UPDATE dramas SET current_stage = 8, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 8, state.latest_audit)

    db.commit()
    log.info("【阶段 8 落库】成功完成并已提交事务。")


# =========================================================================
# 兼容性包装函数与全量加载/持久化门面
# =========================================================================

