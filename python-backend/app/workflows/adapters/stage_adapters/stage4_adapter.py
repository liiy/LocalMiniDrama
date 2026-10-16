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

def persist_stage4(db: Session, drama_id: int, state: GlobalDramaMasterState | Any) -> None:
    """阶段 4 原子落库：写入 music_bibles / episodes (分集大纲与断点钩子)。"""
    log.info("【阶段 4 落库】开始持久化短剧 [%s] 的全季大纲与音乐动机母库...", drama_id)
    now = now_iso()

    def _state_val(key: str, default: Any = None) -> Any:
        if isinstance(state, dict):
            return state.get(key, default)
        return getattr(state, key, default)

    # 1. 写入 music_bibles 表
    audio_bible_dict = _dump_or_dict(_state_val("audio_bible") or _state_val("audio_bible_summary", {}))
    motifs = audio_bible_dict.get("leitmotif_registry") or audio_bible_dict.get("leitmotifs", []) or audio_bible_dict.get("leitmotif_names", [])
    motifs_json = json.dumps(motifs, ensure_ascii=False)
    foley_rules_json = json.dumps(audio_bible_dict.get("foley_rules", {}), ensure_ascii=False)

    existing_mb = fetch_one(db, "SELECT id FROM music_bibles WHERE drama_id = :drama_id", {"drama_id": drama_id})
    visual_style = _state_val("visual_style", "") or (_state_val("world_building_working_memory", {}) or {}).get("visual_tone", "")
    if existing_mb:
        db.execute(
            text("""
                UPDATE music_bibles
                SET overall_style = :style,
                    theme_prompt = :theme_prompt,
                    instruments = :instruments,
                    mixing_rules = :mixing_rules,
                    updated_at = :updated_at
                WHERE id = :id
            """),
            {
                "id": existing_mb["id"],
                "style": visual_style,
                "theme_prompt": motifs_json,
                "instruments": motifs_json,
                "mixing_rules": foley_rules_json,
                "updated_at": now,
            },
        )
    else:
        db.execute(
            text("""
                INSERT INTO music_bibles (
                    drama_id, overall_style, theme_prompt, instruments,
                    mixing_rules, status, created_at, updated_at
                ) VALUES (
                    :drama_id, :style, :theme_prompt, :instruments,
                    :mixing_rules, 'completed', :now, :now
                )
            """),
            {
                "drama_id": drama_id,
                "style": visual_style,
                "theme_prompt": motifs_json,
                "instruments": motifs_json,
                "mixing_rules": foley_rules_json,
                "now": now,
            },
        )

    # 2. 写入分集大纲至独立的 episode_outlines 表（蓝图设计），并建立 episodes 关联（生产容器）
    season_outlines = _state_val("season_outlines", {}) or {}
    if isinstance(season_outlines, dict) and "episodes" in season_outlines:
        ep_items = season_outlines.get("episodes") or []
    elif isinstance(season_outlines, dict):
        def _sort_key(item: tuple[Any, Any]) -> int:
            k, v = item
            if isinstance(v, dict) and (v.get("episode_id") or v.get("episode_number")):
                try:
                    return int(v.get("episode_id") or v.get("episode_number"))
                except Exception:
                    pass
            try:
                return int(k)
            except (ValueError, TypeError):
                return 0
        sorted_pairs = sorted(season_outlines.items(), key=_sort_key)
        ep_items = [v for _, v in sorted_pairs if isinstance(v, dict)]
    elif isinstance(season_outlines, list):
        ep_items = season_outlines
    else:
        ep_items = []

    ep_cols = _get_table_columns(db, "episodes")
    outline_cols = _get_table_columns(db, "episode_outlines")
    has_outline_table = len(outline_cols) > 0
    has_outline_id_col = "outline_id" in ep_cols
    has_desc_col = "description" in ep_cols
    has_hook_col = "hook" in ep_cols
    has_climax_col = "climax" in ep_cols
    has_cliff_col = "cliffhanger" in ep_cols
    has_hook_cliff_col = "hook_cliffhanger" in ep_cols

    log.info(
        "【阶段4持久化】开始持久化分集大纲 (共 %d 集)... (独立大纲表状态: %s, episodes.outline_id: %s, episodes.description: %s)",
        len(ep_items),
        "已就绪" if has_outline_table else "未就绪(将降级存储)",
        "支持" if has_outline_id_col else "不支持",
        "存在(兼容旧表)" if has_desc_col else "已剔除(SSOT单一事实源)",
    )

    for idx, ep_info in enumerate(ep_items, start=1):
        try:
            ep_num = int(ep_info.get("episode_id") or ep_info.get("episode_number") or ep_info.get("episode_num") or idx)
        except Exception:
            ep_num = idx
        ep_title = ep_info.get("killer_title") or ep_info.get("title") or f"第{ep_num}集"
        hook = (
            ep_info.get("hook_3s")
            or ep_info.get("three_second_hook")
            or ep_info.get("hook")
            or ep_info.get("core_action", "")
        )
        climax = (
            ep_info.get("micro_twist_45s")
            or ep_info.get("micro_turning_point_45s")
            or ep_info.get("climax")
            or ep_info.get("core_resistance", "")
        )
        cliffhanger = (
            ep_info.get("cliffhanger_end")
            or ep_info.get("killer_cliffhanger_115s")
            or ep_info.get("cliffhanger")
            or ep_info.get("ending_cliffhanger", "")
        )
        desc = (
            ep_info.get("description")
            or f"【第{ep_num}集大纲】{ep_title}\n前3s抓手: {hook}\n45s微反转: {climax}\n集末断点: {cliffhanger}"
        )

        target_dur = int(getattr(state, "target_duration_sec", 120) or 120)
        dual_helix_raw = ep_info.get("dual_helix_task")
        dual_helix_json = json.dumps(dual_helix_raw, ensure_ascii=False) if isinstance(dual_helix_raw, (dict, list)) else (str(dual_helix_raw) if dual_helix_raw is not None else "{}")
        subtext_raw = ep_info.get("subtext_matrix")
        subtext_json = json.dumps(subtext_raw, ensure_ascii=False) if isinstance(subtext_raw, (dict, list)) else (str(subtext_raw) if subtext_raw is not None else "{}")
        raw_card_json = json.dumps(ep_info, ensure_ascii=False)

        outline_id: int | None = None

        # 2.1 写入/更新独立创作大纲表 (episode_outlines)
        if has_outline_table:
            existing_outline = fetch_one(
                db,
                "SELECT id FROM episode_outlines WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL",
                {"drama_id": drama_id, "ep_num": ep_num},
            )
            if existing_outline:
                outline_id = existing_outline["id"]
                db.execute(
                    text("""
                        UPDATE episode_outlines
                        SET title = :title,
                            dual_helix_task = :dual_helix_task,
                            subtext_matrix = :subtext_matrix,
                            hook_3s = :hook_3s,
                            micro_twist_45s = :micro_twist_45s,
                            cliffhanger_end = :cliffhanger_end,
                            target_duration_s = :target_duration_s,
                            raw_outline_card = :raw_outline_card,
                            updated_at = :updated_at
                        WHERE id = :id
                    """),
                    {
                        "id": outline_id,
                        "title": ep_title,
                        "dual_helix_task": dual_helix_json,
                        "subtext_matrix": subtext_json,
                        "hook_3s": hook,
                        "micro_twist_45s": climax,
                        "cliffhanger_end": cliffhanger,
                        "target_duration_s": target_dur,
                        "raw_outline_card": raw_card_json,
                        "updated_at": now,
                    },
                )
                log.info("【阶段4持久化】更新独立大纲表成功 -> 短剧[%s] 第%s集 [outline_id=%s]", drama_id, ep_num, outline_id)
            else:
                db.execute(
                    text("""
                        INSERT INTO episode_outlines (
                            drama_id, episode_number, title, dual_helix_task, subtext_matrix,
                            hook_3s, micro_twist_45s, cliffhanger_end, target_duration_s,
                            raw_outline_card, created_at, updated_at
                        ) VALUES (
                            :drama_id, :ep_num, :title, :dual_helix_task, :subtext_matrix,
                            :hook_3s, :micro_twist_45s, :cliffhanger_end, :target_duration_s,
                            :raw_outline_card, :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "ep_num": ep_num,
                        "title": ep_title,
                        "dual_helix_task": dual_helix_json,
                        "subtext_matrix": subtext_json,
                        "hook_3s": hook,
                        "micro_twist_45s": climax,
                        "cliffhanger_end": cliffhanger,
                        "target_duration_s": target_dur,
                        "raw_outline_card": raw_card_json,
                        "now": now,
                    },
                )
                new_outline = fetch_one(
                    db,
                    "SELECT id FROM episode_outlines WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
                    {"drama_id": drama_id, "ep_num": ep_num},
                )
                outline_id = new_outline["id"] if new_outline else None
                log.info("【阶段4持久化】新建独立大纲记录成功 -> 短剧[%s] 第%s集 [outline_id=%s]", drama_id, ep_num, outline_id)

        # 2.2 同步更新分集执行容器表 (episodes) 并绑定 outline_id（遵循 SSOT，大纲字段不重复存储）
        existing_ep = fetch_one(
            db,
            "SELECT id FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": ep_num},
        )
        if existing_ep:
            set_clauses = ["title = :title", "updated_at = :updated_at"]
            params: dict[str, Any] = {
                "id": existing_ep["id"],
                "title": ep_title,
                "updated_at": now,
            }
            if has_desc_col:
                set_clauses.append("description = :desc")
                params["desc"] = desc
            if has_outline_id_col and outline_id is not None:
                set_clauses.append("outline_id = :outline_id")
                params["outline_id"] = outline_id
            if has_hook_col:
                set_clauses.append("hook = :hook")
                params["hook"] = hook
            if has_climax_col:
                set_clauses.append("climax = :climax")
                params["climax"] = climax
            if has_cliff_col:
                set_clauses.append("cliffhanger = :cliffhanger")
                params["cliffhanger"] = cliffhanger
            if has_hook_cliff_col:
                set_clauses.append("hook_cliffhanger = :hook_cliffhanger")
                params["hook_cliffhanger"] = cliffhanger

            db.execute(
                text(f"UPDATE episodes SET {', '.join(set_clauses)} WHERE id = :id"),
                params,
            )
            log.info("【阶段4持久化】更新 episodes 容器记录 -> 短剧[%s] 第%s集 [ep_id=%s, outline_id=%s]", drama_id, ep_num, existing_ep["id"], outline_id)
        else:
            col_names = ["drama_id", "episode_number", "title", "duration", "status", "created_at", "updated_at"]
            val_names = [":drama_id", ":ep_num", ":title", ":duration", "'outline_completed'", ":now", ":now"]
            params = {
                "drama_id": drama_id,
                "ep_num": ep_num,
                "title": ep_title,
                "duration": target_dur,
                "now": now,
            }
            if has_desc_col:
                col_names.append("description")
                val_names.append(":desc")
                params["desc"] = desc
            if has_outline_id_col and outline_id is not None:
                col_names.append("outline_id")
                val_names.append(":outline_id")
                params["outline_id"] = outline_id
            if has_hook_col:
                col_names.append("hook")
                val_names.append(":hook")
                params["hook"] = hook
            if has_climax_col:
                col_names.append("climax")
                val_names.append(":climax")
                params["climax"] = climax
            if has_cliff_col:
                col_names.append("cliffhanger")
                val_names.append(":cliffhanger")
                params["cliffhanger"] = cliffhanger
            if has_hook_cliff_col:
                col_names.append("hook_cliffhanger")
                val_names.append(":hook_cliffhanger")
                params["hook_cliffhanger"] = cliffhanger

            db.execute(
                text(f"INSERT INTO episodes ({', '.join(col_names)}) VALUES ({', '.join(val_names)})"),
                params,
            )
            log.info("【阶段4持久化】新建 episodes 容器记录 -> 短剧[%s] 第%s集 [outline_id=%s]", drama_id, ep_num, outline_id)

    # 长期记忆自动入库与向量化（音频大纲与全季分集大纲骨架）
    stage4_memories = [
        {
            "title": "全剧配乐动机母库 (Audio Bible)",
            "content": f"全剧视听基调: {visual_style}\n主导动机主题: {motifs_json}\n动效拟音混音规则: {foley_rules_json}",
            "summary": f"音频母库: {len(motifs)}个动机主题",
            "keywords": ["音频母库", "BGM", "音效", "Leitmotif"],
            "memory_type": "audio_bible",
            "source_type": "stage4_audio_bible",
            "source_id": f"drama_{drama_id}_audio_bible",
        }
    ]
    for idx, ep_info in enumerate(ep_items, start=1):
        try:
            ep_num = int(ep_info.get("episode_id") or ep_info.get("episode_number") or ep_info.get("episode_num") or idx)
        except Exception:
            ep_num = idx
        ep_title = ep_info.get("killer_title") or ep_info.get("title") or f"第{ep_num}集"
        hook = (
            ep_info.get("hook_3s")
            or ep_info.get("three_second_hook")
            or ep_info.get("hook")
            or ep_info.get("core_action", "")
        )
        climax = (
            ep_info.get("micro_twist_45s")
            or ep_info.get("micro_turning_point_45s")
            or ep_info.get("climax")
            or ep_info.get("core_resistance", "")
        )
        cliffhanger = (
            ep_info.get("cliffhanger_end")
            or ep_info.get("killer_cliffhanger_115s")
            or ep_info.get("cliffhanger")
            or ep_info.get("ending_cliffhanger", "")
        )
        stage4_memories.append({
            "title": f"第{ep_num}集大纲与断点钩子: {ep_title}",
            "content": f"第{ep_num}集: {ep_title}\n开篇前3s抓手: {hook}\n核心微反转: {climax}\n集末绝杀断点: {cliffhanger}",
            "summary": f"第{ep_num}集: 抓手[{hook[:20]}] 断点[{cliffhanger[:20]}]",
            "keywords": [f"第{ep_num}集", "分集大纲", "断点钩子", ep_title],
            "episode_id": None,
            "memory_type": "episode_outline",
            "source_type": "stage4_outline",
            "source_id": f"ep_outline_{ep_num}",
        })
    sync_stage_memories_to_vector_db(db, drama_id, 4, stage4_memories)

    # 更新主表大纲与元数据
    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    current_meta["season_outlines"] = _dump_or_dict(_state_val("season_outlines", {}))
    current_meta["audio_bible"] = audio_bible_dict
    mini_arc = _state_val("mini_arc_units", None)
    if mini_arc:
        current_meta["mini_arc_units"] = mini_arc
    current_meta["current_stage"] = 4

    db.execute(
        text("UPDATE dramas SET current_stage = 4, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    latest_audit = _state_val("latest_audit", None)
    if latest_audit:
        persist_audit_report(db, drama_id, 4, latest_audit)

    db.commit()
    log.info("【阶段 4 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 5：Mini-Arc 工笔文学剧本波次生成持久化
# =========================================================================

