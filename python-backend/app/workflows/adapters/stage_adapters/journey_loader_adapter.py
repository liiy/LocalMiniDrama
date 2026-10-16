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

from app.workflows.adapters.stage_adapters.stage1_adapter import persist_stage1
from app.workflows.adapters.stage_adapters.stage2_adapter import persist_stage2
from app.workflows.adapters.stage_adapters.stage3_adapter import persist_stage3
from app.workflows.adapters.stage_adapters.stage4_adapter import persist_stage4
from app.workflows.adapters.stage_adapters.stage5_adapter import persist_stage5
from app.workflows.adapters.stage_adapters.stage6_adapter import persist_stage6
from app.workflows.adapters.stage_adapters.stage7_adapter import (
    persist_stage7,
    _persist_episode_storyboards_3tables,
    _rehydrate_episode_storyboard_shots,
)
from app.workflows.adapters.stage_adapters.stage8_adapter import persist_stage8

def persist_first_journey_state(db: Session, drama_id: int, state: GlobalDramaMasterState | Any) -> None:
    """持久化第一程全部成果（阶段 1~5），并同步长期与短期工作记忆。"""
    persist_stage1(db, drama_id, state)
    persist_stage2(db, drama_id, state)
    persist_stage3(db, drama_id, state)
    persist_stage4(db, drama_id, state)
    persist_stage5(db, drama_id, state)

    now = now_iso()
    # 状态机锁定控制
    if getattr(state, "literary_journey_locked", False) or getattr(state, "lock_status", False):
        db.execute(
            text("UPDATE dramas SET lock_status = 1, pipeline_status = 'first_journey_locked', updated_at = :now WHERE id = :id"),
            {"id": drama_id, "now": now},
        )
    db.commit()
    log.info("【第一程落库】全阶段 (1~5) 成果与向量记忆同步已成功完成。")


def persist_second_journey_state(db: Session, drama_id: int, state: EpisodeScopedSubState | GlobalDramaMasterState | Any) -> None:
    """持久化第二程全部成果（阶段 6~8）。"""
    curr_ep = getattr(state, "episode_number", None) or getattr(state, "episode_num", None) or getattr(state, "current_visual_episode", 1) or 1
    persist_stage6(db, drama_id, state, curr_ep)
    persist_stage7(db, drama_id, state, curr_ep)
    persist_stage8(db, drama_id, state, curr_ep)


def persist_episode_visual_package(
    db: Session,
    drama_id: int,
    episode_num: int,
    manifest: EpisodeResourceManifest,
    storyboards: list[StoryboardShot],
    srt_export: str = "",
    audio_mastering: dict[str, Any] | None = None,
    mode_b_manifest_check: dict[str, Any] | None = None,
) -> None:
    """单集视听工程包持久化门面函数。"""
    now = now_iso()
    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": episode_num},
    )
    if not ep_row:
        db.execute(
            text("""
                INSERT INTO episodes (drama_id, episode_number, title, duration, created_at, updated_at)
                VALUES (:drama_id, :ep_num, :title, 90, :now, :now)
            """),
            {"drama_id": drama_id, "ep_num": episode_num, "title": f"第{episode_num}集", "now": now},
        )
        ep_row = fetch_one(
            db,
            "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": episode_num},
        )
    if not ep_row:
        return

    ep_id = ep_row["id"]
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    ep_ast["episode_resource_manifest"] = _dump_or_dict(manifest)
    ep_ast["srt_export"] = srt_export
    ep_ast["audio_mastering"] = audio_mastering or {}
    if mode_b_manifest_check:
        ep_ast["mode_b_manifest_check"] = mode_b_manifest_check

    db.execute(
        text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
        {"id": ep_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
    )

    normalized_shots: list[Any] = []
    for s_item in storyboards or []:
        if isinstance(s_item, dict):
            # 容错字段适配
            s_dict = dict(s_item)
            if "duration_seconds" in s_dict and "duration_sec" not in s_dict:
                s_dict["duration_sec"] = s_dict["duration_seconds"]
            if "shot_type" in s_dict and "framing" not in s_dict:
                s_dict["framing"] = s_dict["shot_type"]
            if "camera_movement" in s_dict and "camera_motion" not in s_dict:
                s_dict["camera_motion"] = s_dict["camera_movement"]
            if "mode" in s_dict and "generation_mode" not in s_dict:
                s_dict["generation_mode"] = s_dict["mode"]
            normalized_shots.append(StoryboardShot.model_validate(s_dict))
        else:
            normalized_shots.append(s_item)

    # 统一委托三表联动持久化（storyboards + storyboard_characters + storyboard_props）
    _persist_episode_storyboards_3tables(
        db=db,
        drama_id=drama_id,
        episode_id=ep_id,
        storyboards=normalized_shots,
        status="draft",
        now=str(now),
    )
    db.commit()


def load_master_state_from_db(db: Session, drama_id: int) -> GlobalDramaMasterState:
    """从数据库权威实体表和元数据中加载并重构轻量全局文学状态 (GlobalDramaMasterState < 50KB)。
    同时向下兼容保留角色全息字典与分集大纲字典供业务使用。
    """
    log.info("【状态加载】开始从数据库重构短剧 [%s] 的 GlobalDramaMasterState...", drama_id)
    drama_row = fetch_one(db, "SELECT * FROM dramas WHERE id = :id", {"id": drama_id})
    if not drama_row:
        raise ValueError(f"Drama with ID {drama_id} does not exist.")

    meta = _safe_json_loads(drama_row.get("metadata"), {})
    candidate_titles_data = meta.get("candidate_titles")
    candidate_titles = CandidateTitleMatrix.model_validate(candidate_titles_data) if candidate_titles_data else CandidateTitleMatrix()
    negative_rules_data = meta.get("negative_rules")
    negative_rules = DoubleTrackProhibitions.model_validate(negative_rules_data) if negative_rules_data else DoubleTrackProhibitions()
    audio_bible_data = meta.get("audio_bible")
    audio_bible = AudioBible.model_validate(audio_bible_data) if audio_bible_data else AudioBible()
    latest_audit_data = meta.get("latest_audit")
    latest_audit = RedBlueAuditReport.model_validate(latest_audit_data) if latest_audit_data else RedBlueAuditReport()

    selected_title = drama_row.get("name") or drama_row.get("title") or "未定名短剧"
    core_irony = drama_row.get("dramatic_irony") or meta.get("dramatic_irony") or ""
    user_idea = meta.get("user_idea") or drama_row.get("prompt") or ""

    state = GlobalDramaMasterState(
        drama_id=drama_id,
        user_idea=user_idea,
        selected_title=selected_title,
        title=selected_title,
        logline=drama_row.get("logline") or meta.get("logline") or drama_row.get("description") or "",
        dramatic_irony=core_irony,
        core_irony=core_irony,
        grand_payoff=drama_row.get("grand_payoff") or meta.get("grand_payoff") or "",
        genre=drama_row.get("genre") or "剧情",
        visual_style=meta.get("visual_style") or drama_row.get("style") or "真人电影/超写实",
        aspect_ratio=drama_row.get("aspect_ratio") or meta.get("aspect_ratio") or "9:16",
        target_duration_sec=float(drama_row.get("target_duration_sec") or meta.get("target_duration_sec") or 120.0),
        total_episodes=int(drama_row.get("total_episodes") or meta.get("total_episodes") or 12),
        current_stage=int(drama_row.get("current_stage") or meta.get("current_stage") or 1),
        journey=meta.get("journey") or "journey_1_literary",
        literary_journey_locked=bool(drama_row.get("lock_status", 0) or meta.get("literary_journey_locked", False)),
        candidate_titles=candidate_titles,
        negative_rules=negative_rules,
        audio_bible=audio_bible,
        audio_bible_summary={
            "leitmotif_names": [
                (getattr(m, "motif_id", None) or (m.get("motif_id") if isinstance(m, dict) else "") or "")
                for m in (audio_bible.leitmotifs or audio_bible.leitmotif_registry or [])
            ],
            "foley_rules_count": len(audio_bible.foley_rules) if audio_bible.foley_rules else 0,
            "theme_prompt": getattr(audio_bible, "theme_prompt", "") or "",
        },
        season_outlines=meta.get("season_outlines") or {},
        mini_arc_units=meta.get("mini_arc_units") or [],
        current_mini_arc_index=meta.get("current_mini_arc_index") or 1,
        inter_episode_physical_snapshot=meta.get("inter_episode_physical_snapshot") or {},
        character_tokens=meta.get("character_tokens") or [],
        scene_tokens=meta.get("scene_tokens") or [],
        prop_tokens=meta.get("prop_tokens") or [],
        visual_audio_assets_registry=meta.get("visual_audio_assets_registry") or {},
        latest_audit=latest_audit,
    )

    if not state.ideation_working_memory:
        try:
            from app.context.short_memory_service import WorkingMemoryCompiler
            state.ideation_working_memory = WorkingMemoryCompiler.compile_ideation_working_memory(state)
        except Exception:
            pass

    # 1. 加载角色 (含 stages 与 views 从表及 character_relationship 关系表)
    char_rows = fetch_all(db, "SELECT * FROM characters WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC", {"drama_id": drama_id})
    chars = []
    global_characters = {}
    for r in char_rows:
        char_id = r["id"]
        growth_data = _safe_json_loads(r.get("growth_chain"), {})
        status_info = _safe_json_loads(r.get("current_status"), {})
        
        stage_rows = fetch_all(db, "SELECT * FROM character_stages WHERE character_id = :cid AND deleted_at IS NULL ORDER BY start_episode ASC, id ASC", {"cid": char_id})
        st_list = []
        for s in stage_rows:
            view_rows = fetch_all(db, "SELECT * FROM character_stage_views WHERE character_stage_id = :sid AND deleted_at IS NULL", {"sid": s["id"]})
            st_list.append({
                "stage_name": s.get("stage_name"),
                "start_episode": s.get("start_episode"),
                "end_episode": s.get("end_episode"),
                "costume_description": s.get("costume_description"),
                "color_palette": s.get("color_palette"),
                "views": [dict(v) for v in view_rows],
            })

        c_name = r.get("name") or f"CHAR_{char_id}"
        char_code = r.get("character_code") or f"CHAR_{char_id}"
        
        # 兼容反序列化多模态与戏剧动力资产
        vcc_data = _safe_json_loads(r.get("visual_consistency_code"), {}) or status_info.get("visual_consistency_code", {})
        ac_data = _safe_json_loads(r.get("acoustic_persona"), {}) or status_info.get("acoustic_persona", {})
        anchor_data = _safe_json_loads(r.get("carried_anchor_item"), {}) or status_info.get("carried_anchor_item", {})
        engine_data = _safe_json_loads(r.get("drama_engine"), {}) or status_info.get("drama_engine", {})
        psych_data = _safe_json_loads(r.get("psychology_4"), {}) or growth_data.get("psychological_quad", {})
        voice_fp_data = _safe_json_loads(r.get("voice_fingerprint"), {}) or status_info.get("voice_fingerprint", {})

        char_profile = {
            "id": char_id,
            "character_code": char_code,
            "character_id": char_code,
            "name": c_name,
            "gender": r.get("gender") or "male",
            "perceived_age": r.get("perceived_age"),
            "role": r.get("role") or r.get("role_type") or "protagonist",
            "role_type": r.get("role_type") or r.get("role") or "protagonist",
            "description": r.get("description") or r.get("personality") or "",
            "personality": r.get("personality") or "",
            "appearance": r.get("appearance") or r.get("appearance_features") or "",
            "identity_anchors": _safe_json_loads(r.get("identity_anchors"), []),
            "visual_consistency_code": vcc_data,
            "voice_style": r.get("voice_style") or "",
            "acoustic_persona": ac_data,
            "psychology_4": psych_data,
            "psychological_quad": psych_data,
            "voice_fingerprint": voice_fp_data,
            "carried_anchor_item": anchor_data,
            "drama_engine": engine_data,
            "biological_dna": status_info.get("biological_dna", {}),
            "lived_in_costume": status_info.get("lived_in_costume", {}),
            "dual_track_relationships": status_info.get("dual_track_relationships", []),
            "emotional_arc_trajectories": growth_data.get("emotional_arc_trajectories", []),
            "stages": st_list,
        }
        chars.append(char_profile)
        global_characters[c_name] = {
            "character_id": char_id,
            "character_code": char_code,
            "role_type": char_profile["role_type"],
            "visual_anchor": char_profile["appearance"],
            "voice_timber": char_profile["voice_style"],
        }
        global_characters[char_code] = global_characters[c_name]

    # 加载 character_relationship 关系网
    rel_rows = fetch_all(db, "SELECT * FROM character_relationship WHERE drama_id = :drama_id ORDER BY id ASC", {"drama_id": drama_id})
    rel_matrix = []
    for rel_r in rel_rows:
        raw_obj = _safe_json_loads(rel_r.get("raw"), {}) if rel_r.get("raw") else {}
        info_gap = _safe_json_loads(rel_r.get("information_gap"), {})
        swing_pt = _safe_json_loads(rel_r.get("swing_point"), {})
        shared_pr = _safe_json_loads(rel_r.get("shared_history_props"), [])

        surface = rel_r.get("social_label") or raw_obj.get("surface_relation") or ""
        emotional = raw_obj.get("emotional_bond") or ""
        conflict = raw_obj.get("fatal_interest_conflict") or raw_obj.get("fatal_conflict") or ""
        attitude = raw_obj.get("attitude_arc") or ""

        rel_item = {
            "character_a_code": rel_r.get("character_a_code"),
            "character_b_code": rel_r.get("character_b_code"),
            "character_a": rel_r.get("character_a_code"),
            "character_b": rel_r.get("character_b_code"),
            "social_label": rel_r.get("social_label") or surface,
            "surface_relation": surface,
            "surface_identity": surface,
            "emotional_bond": emotional,
            "deep_bond": emotional,
            "fatal_interest_conflict": conflict,
            "fatal_conflict": conflict,
            "tension_index": int(rel_r.get("tension_index") or 50),
            "drama_function": rel_r.get("drama_function") or "catalyst",
            "shared_history_props": shared_pr,
            "shared_past_token": shared_pr[0] if shared_pr else "",
            "information_gap": info_gap,
            "knows_truth_initially": bool(rel_r.get("knows_truth_initially")),
            "current_belief": rel_r.get("current_belief") or info_gap.get("current_belief", ""),
            "reveal_condition": rel_r.get("reveal_condition") or info_gap.get("reveal_condition", ""),
            "can_defect": bool(rel_r.get("can_defect")),
            "defect_condition": rel_r.get("defect_condition") or swing_pt.get("defect_condition", ""),
            "attitude_arc": attitude,
            "swing_point": swing_pt,
            "raw": raw_obj,
        }
        rel_matrix.append(rel_item)

    if chars:
        state.characters = chars
        state.character_relationships = rel_matrix
        state.characters_engine = {
            "characters": chars,
            "relationship_matrix": rel_matrix,
            "dual_track_relationships": rel_matrix,
        }
        state.global_characters = global_characters

    # 2. 加载场景与道具 (含从表)
    scene_rows = fetch_all(db, "SELECT * FROM scenes WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC", {"drama_id": drama_id})
    scenes = []
    global_scenes = {}
    for s in scene_rows:
        s_id = s["id"]
        s_extra = _safe_json_loads(s.get("extra_images"), {})
        zone_rows = fetch_all(db, "SELECT * FROM scene_zones WHERE scene_id = :sid AND deleted_at IS NULL", {"sid": s_id})
        z_list = []
        for z in zone_rows:
            w_rows = fetch_all(db, "SELECT * FROM scene_weathering_views WHERE scene_zone_id = :zid AND deleted_at IS NULL", {"zid": z["id"]})
            z_list.append({
                "zone_name": z.get("zone_name"),
                "time_lighting": z.get("time_lighting"),
                "acoustic_resistance": z.get("acoustic_resistance"),
                "weathering_views": [dict(w) for w in w_rows],
            })
        wl = s_extra.get("weathering_layers", {})
        tla = s_extra.get("three_layer_aging", {})
        loc_name = s.get("name") or s.get("location") or f"SCENE_{s_id}"
        scene_profile = {
            "env_id": s_extra.get("env_id") or f"ENV_SCENE_{s_id:02d}",
            "location_name": loc_name,
            "level": s_extra.get("level", "primary_tier1"),
            "costume_resonance_check": s_extra.get("costume_resonance_check", True),
            "time_and_lighting": s.get("time"),
            "visual_prompt": s.get("prompt"),
            "atmosphere": s.get("atmosphere") or s_extra.get("atmosphere", ""),
            "three_layer_aging": tla or {
                "structure": wl.get("structural", ""),
                "lived_grime": wl.get("living", ""),
                "light_and_air": wl.get("optical", ""),
            },
            "weathering_layers": wl or {
                "structural": tla.get("structure", ""),
                "living": tla.get("lived_grime", ""),
                "optical": tla.get("light_and_air", ""),
            },
            "zones": z_list,
        }
        scenes.append(scene_profile)
        global_scenes[loc_name] = {
            "scene_id": s_id,
            "tone": scene_profile["atmosphere"],
            "acoustic_profile": s.get("time") or "",
        }

    prop_rows = fetch_all(db, "SELECT * FROM props WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC", {"drama_id": drama_id})
    props = []
    global_props = {}
    for p in prop_rows:
        p_id = p["id"]
        p_extra = _safe_json_loads(p.get("extra_images"), {})
        ds_rows = fetch_all(db, "SELECT * FROM prop_damage_states WHERE prop_id = :pid AND deleted_at IS NULL ORDER BY damage_level ASC, id ASC", {"pid": p_id})
        ds_list = []
        for ds in ds_rows:
            dv_rows = fetch_all(db, "SELECT * FROM prop_detail_views WHERE damage_state_id = :dsid AND deleted_at IS NULL", {"dsid": ds["id"]})
            ds_list.append({
                "state_label": ds.get("state_label"),
                "damage_level": ds.get("damage_level"),
                "narrative_point": ds.get("narrative_point"),
                "detail_views": [dict(dv) for dv in dv_rows],
            })
        p_name = p.get("name") or f"PROP_{p_id}"
        prop_profile = {
            "prop_id": p_extra.get("prop_id") or f"PROP_{p_id:02d}",
            "name": p_name,
            "level": p_extra.get("level", "hero_tier1"),
            "type": p.get("type"),
            "description": p.get("description"),
            "visual_prompt": p.get("prompt"),
            "physical_specs": p_extra.get("physical_specs", {}),
            "damage_scale": p_extra.get("damage_scale", ""),
            "foley_resistance": p_extra.get("foley_resistance", ""),
            "damage_states": ds_list,
        }
        props.append(prop_profile)
        global_props[p_name] = {
            "prop_id": p_id,
            "damage_levels": [d["damage_level"] for d in ds_list if "damage_level" in d],
        }

    if scenes or props:
        state.environments_and_props = {"environments": scenes, "props": props}
        state.global_scenes = global_scenes
        state.global_props = global_props

    # 2.5 加载配乐动机母库 (如果元数据中未完整包含)
    mb_rows = fetch_all(db, "SELECT * FROM music_bibles WHERE drama_id = :drama_id AND deleted_at IS NULL", {"drama_id": drama_id})
    if mb_rows and (not audio_bible.leitmotifs and not audio_bible.leitmotif_registry):
        m_items = []
        for mb in mb_rows:
            st = _safe_json_loads(mb.get("scene_types"), {})
            m_items.append(st if isinstance(st, dict) and st else {
                "leitmotif_id": mb.get("theme_name"),
                "motif_id": mb.get("theme_name"),
                "name": mb.get("theme_name"),
                "type": mb.get("style"),
                "tempo_bpm": mb.get("tempo"),
                "musical_key": mb.get("mood"),
                "instrumentation": mb.get("instrumentation"),
                "frequency_band": mb.get("frequency_range"),
            })
        audio_bible.leitmotif_registry = m_items
        audio_bible.leitmotifs = m_items
        state.audio_bible = audio_bible
        state.audio_bible_summary["leitmotif_names"] = [m.get("motif_id") or m.get("name", "") for m in m_items]

    # 2.8 优先从 episode_outlines 独立表加载全量高保真分集大纲
    outline_cols = _get_table_columns(db, "episode_outlines")
    if len(outline_cols) > 0:
        outline_rows = fetch_all(
            db,
            "SELECT * FROM episode_outlines WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY episode_number ASC",
            {"drama_id": drama_id},
        )
        for o in outline_rows:
            ep_n = o.get("episode_number")
            if not ep_n:
                continue
            raw_card = _safe_json_loads(o.get("raw_outline_card"), {})
            entry = dict(raw_card) if isinstance(raw_card, dict) else {}
            entry.update({
                "episode_number": ep_n,
                "episode_id": ep_n,
                "title": o.get("title") or entry.get("title") or f"第{ep_n}集",
                "killer_title": o.get("title") or entry.get("killer_title") or f"第{ep_n}集",
                "dual_helix_task": _safe_json_loads(o.get("dual_helix_task"), entry.get("dual_helix_task", {})),
                "subtext_matrix": _safe_json_loads(o.get("subtext_matrix"), entry.get("subtext_matrix", {})),
                "hook_3s": o.get("hook_3s") or entry.get("hook_3s") or "",
                "three_second_hook": o.get("hook_3s") or entry.get("hook_3s") or "",
                "micro_twist_45s": o.get("micro_twist_45s") or entry.get("micro_twist_45s") or "",
                "micro_turning_point_45s": o.get("micro_twist_45s") or entry.get("micro_twist_45s") or "",
                "cliffhanger_end": o.get("cliffhanger_end") or entry.get("cliffhanger_end") or "",
                "killer_cliffhanger_115s": o.get("cliffhanger_end") or entry.get("cliffhanger_end") or "",
                "target_duration_s": o.get("target_duration_s", 90),
            })
            state.season_outlines[ep_n] = entry
        if outline_rows:
            log.info("【全剧状态恢复】成功从 episode_outlines 恢复 %d 集结构化创作大纲", len(outline_rows))

    # 3. 加载分集剧本与分镜至大纲与状态
    ep_rows = fetch_all(db, "SELECT * FROM episodes WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY episode_number ASC", {"drama_id": drama_id})
    for ep in ep_rows:
        ep_num = ep.get("episode_number")
        ep_id = ep.get("id")

        # 补全或重构分集大纲条目 (规避独立落库后状态反序列化缺失)
        if ep_num and ep_num not in state.season_outlines:
            hook_data = _safe_json_loads(ep.get("hook_cliffhanger"), {})
            outline_entry = {
                "episode_number": ep_num,
                "episode_id": ep_num,
                "title": ep.get("title") or f"第{ep_num}集",
                "killer_title": ep.get("title") or f"第{ep_num}集",
                "description": ep.get("description") or "",
            }
            if isinstance(hook_data, dict):
                outline_entry.update(hook_data)
            state.season_outlines[ep_num] = outline_entry
        script_raw = ep.get("script_content")
        ep_ast = _safe_json_loads(ep.get("ast_blocks"), {})
        start_snap = _safe_json_loads(ep.get("physical_snapshot_start"), ep_ast.get("previous_episode_0s_pickup", {}))
        end_snap = _safe_json_loads(ep.get("physical_snapshot_end"), ep_ast.get("episode_end_physical_delta", {}))
        audit_rep = _safe_json_loads(ep.get("audit_report"), ep_ast.get("audit_report", {}))

        if script_raw or ep_ast.get("scenes") or ep.get("status") == "script_completed" or ep_ast.get("dramatic_rhythm_check"):
            ep_dict = None
            trimmed_raw = (script_raw or "").strip()
            if trimmed_raw.startswith("{") and trimmed_raw.endswith("}"):
                try:
                    loaded = json.loads(trimmed_raw)
                    if isinstance(loaded, dict):
                        ep_dict = loaded
                except Exception:
                    ep_dict = None

            if ep_dict is not None:
                try:
                    state.completed_screenplays[ep_num] = LiteraryScreenplayEpisodeModel.model_validate(ep_dict).model_dump()
                except Exception:
                    state.completed_screenplays[ep_num] = ep_dict
            else:
                # 遵循 SSOT 新规范：纯文本 Markdown 剧本正文与独立物理快照/自审结果无损还原
                screenplay_dict = {
                    "episode_number": ep_num,
                    "episode_num": ep_num,
                    "episode_id": ep_num,
                    "title": ep.get("title") or f"第{ep_num}集",
                    "episode_title": ep.get("title") or f"第{ep_num}集",
                    "screenplay_text": script_raw or "",
                    "body_markdown": script_raw or "",
                    "planned_duration_sec": float(ep.get("duration") or 120.0),
                    "commercial_tag": ep.get("commercial_tag") or "regular",
                    "previous_episode_0s_pickup": start_snap,
                    "episode_end_physical_delta": end_snap,
                    "outgoing_physical_snapshot": end_snap,
                    "audit_report": audit_rep,
                    "ast_data": ep_ast.get("ast_data"),
                    "scenes": ep_ast.get("scenes", []),
                    "dramatic_rhythm_check": ep_ast.get("dramatic_rhythm_check", {}),
                    "safety_guardrails_lock": ep_ast.get("safety_guardrails_lock", {}),
                    "golden_cliffhanger_hook": ep_ast.get("golden_cliffhanger_hook", {}),
                }
                try:
                    state.completed_screenplays[ep_num] = LiteraryScreenplayEpisodeModel.model_validate(screenplay_dict).model_dump()
                except Exception:
                    state.completed_screenplays[ep_num] = screenplay_dict

        ep_ast = _safe_json_loads(ep.get("ast_blocks"), {})
        if ep_ast.get("episode_resource_manifest"):
            try:
                m_obj = EpisodeResourceManifest.model_validate(ep_ast["episode_resource_manifest"])
                state.episode_manifests[ep_num] = m_obj
                state.episode_resource_manifests[ep_num] = m_obj
            except Exception:
                pass
        if ep_ast.get("srt_export"):
            state.srt_exports[ep_num] = ep_ast["srt_export"]
        if ep_ast.get("mode_b_manifest_check"):
            state.episode_mode_b_manifest_checks[ep_num] = ep_ast["mode_b_manifest_check"]
        if ep_ast.get("audio_mastering"):
            state.audio_mastering_plans[ep_num] = ep_ast["audio_mastering"]

        shot_list = _rehydrate_episode_storyboard_shots(db, drama_id, ep_id)
        if shot_list:
            state.storyboard_executions[ep_num] = shot_list

    # 防御性校准：同步已完成剧本编号集合与当前阶段
    if state.completed_screenplays:
        state.completed_episodes = sorted(list(state.completed_screenplays.keys()))
        if state.current_stage < 5 and not state.storyboard_executions:
            # 若已存在剧本产物但 current_stage 仍滞留在前序阶段，校准提升至 5
            log.info("【状态校准】检测到短剧 [%s] 已存在 %d 集定稿剧本，将 current_stage 从 %s 校准为 5",
                     drama_id, len(state.completed_screenplays), state.current_stage)
            state.current_stage = 5

    return state


# 别名映射
load_global_master_state_from_db = load_master_state_from_db


def load_first_journey_state(db: Session, drama_id: int) -> GlobalDramaMasterState:
    """加载文学故事工程状态。"""
    return load_master_state_from_db(db, drama_id)


def load_episode_visual_package(db: Session, drama_id: int, episode_num: int) -> dict[str, Any]:
    """从数据库加载指定集的视听工程包。"""
    ep_row = fetch_one(
        db,
        "SELECT * FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL",
        {"drama_id": drama_id, "ep_num": episode_num},
    )
    if not ep_row:
        return {}
    ep_id = ep_row["id"]
    ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    storyboards = _rehydrate_episode_storyboard_shots(db, drama_id, ep_id)

    return {
        "episode_number": episode_num,
        "episode_num": episode_num,
        "manifest": ast.get("episode_resource_manifest"),
        "storyboards": storyboards,
        "storyboard_shots": storyboards,
        "srt_export": ast.get("srt_export", ""),
        "mode_b_manifest_check": ast.get("mode_b_manifest_check"),
        "audio_mastering": ast.get("audio_mastering", {}),
    }


def load_episode_substate_slice(db: Session, drama_id: int, episode_number: int) -> EpisodeScopedSubState:
    """【懒水合核心】从关系型数据库毫秒级加载单集独立执行切片 (EpisodeScopedSubState)。
    
    设计理念：
    1. 彻底解耦全剧巨石状态：执行第二程单集（Stage 5~8）时，无需加载全剧全量角色图谱、全季所有集大纲与分镜。
    2. 最小必要领域投影：仅加载本集大纲卡、前后集物理连续性快照、本集登场角色/场景/道具桩，以及当前已生成分镜草稿。
    3. 极速恢复与并发：单次切片水合耗时 < 10ms，内存占用 < 100KB，支撑多集并行流水线与秒级断点恢复。
    """
    log.debug("【单集切片懒水合】开始加载剧目 [%s] 第 %s 集独立执行切片...", drama_id, episode_number)
    
    # 1. 查询单集基础数据与 AST 块
    ep_row = fetch_one(
        db,
        "SELECT * FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL",
        {"drama_id": drama_id, "ep_num": episode_number},
    )
    if not ep_row:
        raise ValueError(f"剧目 [{drama_id}] 第 {episode_number} 集数据不存在，无法执行单集水合。")

    ep_id = ep_row["id"]
    ast_blocks = _safe_json_loads(ep_row.get("ast_blocks"), {})

    # 2. 构造 SeasonOutlineCard（优先从独立分集大纲表 episode_outlines 水合完整创作蓝图）
    outline_row = None
    outline_id = ep_row.get("outline_id")
    if outline_id:
        outline_row = fetch_one(
            db,
            "SELECT * FROM episode_outlines WHERE id = :outline_id AND deleted_at IS NULL",
            {"outline_id": outline_id},
        )
    if not outline_row:
        outline_row = fetch_one(
            db,
            "SELECT * FROM episode_outlines WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            {"drama_id": drama_id, "ep_num": episode_number},
        )

    if outline_row:
        raw_card = _safe_json_loads(outline_row.get("raw_outline_card"), {})
        dual_helix = _safe_json_loads(outline_row.get("dual_helix_task"), {})
        subtext = _safe_json_loads(outline_row.get("subtext_matrix"), {})
        hook = outline_row.get("hook_3s") or raw_card.get("hook_3s") or ep_row.get("hook") or ""
        climax = outline_row.get("micro_twist_45s") or raw_card.get("micro_twist_45s") or ep_row.get("climax") or ""
        cliffhanger = outline_row.get("cliffhanger_end") or raw_card.get("cliffhanger_end") or ep_row.get("hook_cliffhanger") or ep_row.get("cliffhanger") or ""

        card_dict = dict(raw_card) if isinstance(raw_card, dict) else {}
        card_dict.update({
            "episode_number": episode_number,
            "episode_id": episode_number,
            "title": outline_row.get("title") or ep_row.get("title") or f"第{episode_number}集",
            "killer_title": outline_row.get("title") or ep_row.get("title") or f"第{episode_number}集",
            "core_conflict_task": climax or card_dict.get("core_conflict_task") or ep_row.get("description") or "",
            "hook_cliffhanger": cliffhanger or ep_row.get("hook_cliffhanger") or "",
            "hook_3s": hook,
            "three_second_hook": hook,
            "micro_twist_45s": climax,
            "micro_turning_point_45s": climax,
            "cliffhanger_end": cliffhanger,
            "killer_cliffhanger_115s": cliffhanger,
            "dual_helix_task": dual_helix or card_dict.get("dual_helix_task", {}),
            "subtext_matrix": subtext or card_dict.get("subtext_matrix", {}),
            "target_duration_s": outline_row.get("target_duration_s", 90),
        })
        task_outline = SeasonOutlineCard.model_validate(card_dict)
        log.info("【单集切片懒水合】成功从 episode_outlines 水合完整创作大纲 [outline_id=%s, ep=%s]", outline_row.get("id"), episode_number)
    else:
        # 降级兜底：历史单集记录或无独立大纲表时，从 episodes 字段降级水合
        task_outline = SeasonOutlineCard(
            episode_number=episode_number,
            title=ep_row.get("title") or f"第{episode_number}集",
            core_conflict_task=ep_row.get("climax") or ep_row.get("description") or "",
            hook_cliffhanger=ep_row.get("cliffhanger") or ep_row.get("hook") or ep_row.get("hook_cliffhanger") or "",
        )
        log.info("【单集切片懒水合】未找到独立大纲记录，从 episodes 表降级水合 [ep=%s]", episode_number)

    # 3. 构造前后集物理连续性快照（上下集时空快照链式咬合）
    # 3.1 承接开场快照 (incoming_physical_continuity)
    # 策略 1: 优先读取本集 episodes.physical_snapshot_start 物理列
    # 策略 2: 若为空且 episode_number > 1，从上一集 (episode_number - 1) 的 physical_snapshot_end 链式水合！
    # 策略 3: 若仍为空，从本集 ast_blocks["previous_episode_0s_pickup"] 读取
    # 策略 4: 第 1 集自然无前序，为 None
    start_data = _safe_json_loads(ep_row.get("physical_snapshot_start"), None)
    if not start_data and episode_number > 1:
        prev_ep_row = fetch_one(
            db,
            "SELECT physical_snapshot_end, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :prev_ep AND deleted_at IS NULL",
            {"drama_id": drama_id, "prev_ep": episode_number - 1},
        )
        if prev_ep_row:
            start_data = _safe_json_loads(prev_ep_row.get("physical_snapshot_end"), None)
            if not start_data:
                prev_ast = _safe_json_loads(prev_ep_row.get("ast_blocks"), {})
                start_data = prev_ast.get("episode_end_physical_delta") or prev_ast.get("outgoing_physical_snapshot")
            if start_data:
                log.info(
                    "【单集切片懒水合】成功从上一集 (第 %s 集) 终态链式水合开场物理快照 -> 第 %s 集 [连续性咬合就绪]",
                    episode_number - 1,
                    episode_number,
                )

    if not start_data:
        start_data = ast_blocks.get("previous_episode_0s_pickup") or {}

    inherited_continuity = (
        InterEpisodePhysicalContinuity.model_validate(start_data)
        if start_data and any(start_data.values() if isinstance(start_data, dict) else [start_data])
        else None
    )

    # 3.2 本集结尾终态快照 (outgoing_physical_continuity)
    end_data = _safe_json_loads(ep_row.get("physical_snapshot_end"), None)
    if not end_data:
        end_data = ast_blocks.get("episode_end_physical_delta") or ast_blocks.get("outgoing_physical_snapshot") or {}

    outgoing_continuity = (
        InterEpisodePhysicalContinuity.model_validate(end_data)
        if end_data and any(end_data.values() if isinstance(end_data, dict) else [end_data])
        else None
    )

    # 4. 加载本集轻量锚点桩 (CharacterAnchorStub / SceneAnchorStub / PropAnchorStub)
    char_rows = fetch_all(
        db,
        "SELECT * FROM characters WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC LIMIT 10",
        {"drama_id": drama_id},
    )
    char_stubs = [
        CharacterAnchorStub(
            character_id=str(c.get("benchmark_asset_key") or c.get("character_code") or c["id"]),
            name=c.get("name") or "",
            archetype=c.get("role_type") or c.get("role") or "配角",
            visual_token=c.get("visual_token") or c.get("appearance") or c.get("identity_anchors") or "",
            core_costume_prompt=c.get("voice_style") or "",
        )
        for c in char_rows
    ]

    scene_rows = fetch_all(
        db,
        "SELECT * FROM scenes WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC LIMIT 6",
        {"drama_id": drama_id},
    )
    scene_stubs = [
        SceneAnchorStub(
            scene_id=str(s.get("benchmark_asset_key") or s.get("scene_code") or s["id"]),
            name=s.get("name") or s.get("location") or "",
            color_tone=s.get("atmosphere") or "",
            weathering_summary=s.get("visual_prompt") or s.get("prompt") or "",
        )
        for s in scene_rows
    ]

    prop_rows = fetch_all(
        db,
        "SELECT * FROM props WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC LIMIT 8",
        {"drama_id": drama_id},
    )
    prop_stubs = [
        PropAnchorStub(
            prop_id=str(p.get("benchmark_asset_key") or p.get("prop_code") or p["id"]),
            name=p.get("name") or "",
            level=p.get("level") or p.get("type") or "hero_tier1",
            visual_token=p.get("visual_token") or p.get("prompt") or "",
        )
        for p in prop_rows
    ]

    # 5. 加载本集可变工作区 (剧本、资源引单、分镜草稿、SRT、混音工程)
    script_raw = ep_row.get("script_content")
    screenplay = None
    if script_raw:
        parsed_sc = _safe_json_loads(script_raw, None)
        if isinstance(parsed_sc, dict):
            try:
                screenplay = LiteraryScreenplayEpisodeModel.model_validate(parsed_sc)
            except Exception:
                screenplay = parsed_sc
        else:
            # 严格遵循 SSOT 纯文本 Markdown 剧本正文与解耦元数据组装
            sc_dict = {
                "episode_number": episode_number,
                "episode_num": episode_number,
                "title": ep_row.get("title") or f"第{episode_number}集",
                "screenplay_text": script_raw,
                "body_markdown": script_raw,
                "planned_duration_sec": float(ep_row.get("duration") or 120.0),
                "commercial_tag": ep_row.get("commercial_tag") or "regular",
                "previous_episode_0s_pickup": _safe_json_loads(ep_row.get("physical_snapshot_start"), ast_blocks.get("previous_episode_0s_pickup", {})),
                "episode_end_physical_delta": _safe_json_loads(ep_row.get("physical_snapshot_end"), ast_blocks.get("episode_end_physical_delta", {})),
                "outgoing_physical_snapshot": _safe_json_loads(ep_row.get("physical_snapshot_end"), ast_blocks.get("episode_end_physical_delta", {})),
                "audit_report": _safe_json_loads(ep_row.get("audit_report"), ast_blocks.get("audit_report", {})),
                "ast_data": ast_blocks.get("ast_data"),
            }
            try:
                screenplay = LiteraryScreenplayEpisodeModel.model_validate(sc_dict)
            except Exception:
                screenplay = sc_dict

    resource_manifest = ast_blocks.get("episode_resource_manifest")
    srt_content = ast_blocks.get("srt_export") or ""
    audio_mastering = ast_blocks.get("audio_mastering")
    audit_report = _safe_json_loads(ep_row.get("audit_report"), ast_blocks.get("audit_report", {}))

    # 5. 加载本集已生成分镜（从 storyboards / storyboard_characters / storyboard_props 三表全保真水合 StoryboardShot）
    storyboard_shots_hydrated: list[StoryboardShot] = _rehydrate_episode_storyboard_shots(db, drama_id, ep_id)

    # 6. 推断当前所处阶段 (Stage 5~8)
    current_stage = 5
    is_completed = False
    if audio_mastering:
        current_stage = 8
        is_completed = True
    elif storyboard_shots_hydrated:
        current_stage = 7
    elif resource_manifest:
        current_stage = 6
    elif screenplay:
        current_stage = 5

    substate = EpisodeScopedSubState(
        drama_id=drama_id,
        episode_number=episode_number,
        current_stage=current_stage,
        task_outline=task_outline,
        incoming_physical_continuity=inherited_continuity,
        inherited_physical_continuity=inherited_continuity,
        relevant_character_stubs=char_stubs,
        relevant_scene_stubs=scene_stubs,
        relevant_prop_stubs=prop_stubs,
        screenplay=screenplay,
        episode_manifest=resource_manifest,
        resource_manifest=resource_manifest,
        storyboard_shots=storyboard_shots_hydrated,
        srt_content=srt_content,
        audio_mastering=audio_mastering,
        outgoing_physical_continuity=outgoing_continuity,
        audit_report=audit_report,
        is_completed=is_completed,
    )

    log.debug(
        "【单集切片懒水合完成】剧目 [%s] 第 %s 集切片就绪: stage=%s, shots=%d, completed=%s, 承接上集快照=%s",
        drama_id,
        episode_number,
        current_stage,
        len(storyboard_shots_hydrated),
        is_completed,
        bool(inherited_continuity),
    )
    return substate


def persist_episode_substate_slice(db: Session, drama_id: int, substate: EpisodeScopedSubState) -> None:
    """【原子切片持久化】将单集独立子图的执行产物原子写回数据库实体表，严格保证纯正文与快照物理分离。"""
    ep_num = substate.episode_number
    log.info("【单集切片持久化】开始持久化剧目 [%s] 第 %s 集执行成果 (Stage %s)...", drama_id, ep_num, substate.current_stage)
    now = now_iso()

    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": ep_num},
    )
    if not ep_row:
        raise ValueError(f"剧目 [{drama_id}] 第 {ep_num} 集不存在，无法持久化切片")

    ep_id = ep_row["id"]
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})

    # 更新 AST 块中单集视听资产
    manifest = substate.episode_manifest or getattr(substate, "resource_manifest", None)
    if manifest:
        ep_ast["episode_resource_manifest"] = _dump_or_dict(manifest)
    if substate.srt_content:
        ep_ast["srt_export"] = substate.srt_content
    if substate.audio_mastering:
        ep_ast["audio_mastering"] = _dump_or_dict(substate.audio_mastering)
    continuity = substate.incoming_physical_continuity or getattr(substate, "inherited_physical_continuity", None)
    if continuity:
        ep_ast["previous_episode_0s_pickup"] = _dump_or_dict(continuity)
    if substate.outgoing_physical_continuity:
        ep_ast["episode_end_physical_delta"] = _dump_or_dict(substate.outgoing_physical_continuity)

    # 1. 更新 episodes 主表（纯文本与物理快照严格分离）
    set_clauses = ["ast_blocks = :ast_blocks", "updated_at = :now"]
    params: dict[str, Any] = {
        "id": ep_id,
        "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
        "now": now,
    }
    if substate.screenplay:
        sp_dict = _dump_or_dict(substate.screenplay)
        sc_text = (
            sp_dict.get("screenplay_text")
            or sp_dict.get("body_markdown")
            or sp_dict.get("screenplay_content")
            or sp_dict.get("text")
            or sp_dict.get("content")
            or (substate.screenplay if isinstance(substate.screenplay, str) else "")
        )
        if not sc_text and isinstance(sp_dict.get("scenes"), list):
            lines = []
            for sc in sp_dict["scenes"]:
                if isinstance(sc, dict):
                    h = sc.get("heading", "")
                    d = sc.get("dialogue", "") or sc.get("dialogue_text", "") or sc.get("content", "")
                    lines.append(f"{h}\n{d}".strip())
                elif isinstance(sc, str):
                    lines.append(sc)
            sc_text = "\n\n".join(filter(None, lines))
        if not sc_text and sp_dict:
            sc_text = json.dumps(sp_dict, ensure_ascii=False)
        if sc_text:
            set_clauses.append("script_content = :script_content")
            params["script_content"] = sc_text
    if substate.is_completed:
        set_clauses.append("status = 'completed'")

    ep_cols = _get_table_columns(db, "episodes")
    if "physical_snapshot_start" in ep_cols and continuity:
        set_clauses.append("physical_snapshot_start = :physical_snapshot_start")
        params["physical_snapshot_start"] = json.dumps(_dump_or_dict(continuity), ensure_ascii=False)
    if "physical_snapshot_end" in ep_cols and substate.outgoing_physical_continuity:
        set_clauses.append("physical_snapshot_end = :physical_snapshot_end")
        params["physical_snapshot_end"] = json.dumps(_dump_or_dict(substate.outgoing_physical_continuity), ensure_ascii=False)
    if "audit_report" in ep_cols and getattr(substate, "audit_report", None):
        set_clauses.append("audit_report = :audit_report")
        params["audit_report"] = json.dumps(_dump_or_dict(substate.audit_report), ensure_ascii=False)
    if "audit_verdict" in ep_cols and getattr(substate, "audit_report", None):
        verdict = "passed" if getattr(substate, "audit_report", {}).get("passed", True) else "need_revision"
        set_clauses.append("audit_verdict = :audit_verdict")
        params["audit_verdict"] = verdict

    db.execute(text(f"UPDATE episodes SET {', '.join(set_clauses)} WHERE id = :id"), params)
    log.info("【单集切片持久化】成功更新 episodes 容器表记录 [ep_id=%s, ep_num=%s]", ep_id, ep_num)

    # 2. 如果存在分镜，调用三表联动持久化写入 storyboards / storyboard_characters / storyboard_props
    if substate.storyboard_shots:
        _persist_episode_storyboards_3tables(
            db=db,
            drama_id=drama_id,
            episode_id=int(ep_id),
            storyboards=substate.storyboard_shots,
            status="completed" if substate.is_completed else "draft",
            now=str(now),
        )

    db.commit()

    # 3. 异步发布 CQRS 只读投影至 Redis
    try:
        publish_episode_read_projection(drama_id, ep_num, substate)
    except Exception as e:
        log.warning("【单集切片持久化】刷新 Redis 读投影失败: %s", e)

    log.info("【单集切片持久化】成功提交: drama_id=%s, ep=%s, stage=%s", drama_id, ep_num, substate.current_stage)


