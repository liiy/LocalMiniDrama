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

def persist_stage3(db: Session, drama_id: int, state: GlobalDramaMasterState | Any) -> None:
    """阶段 3 原子落库：写入 scenes / scene_zones / scene_weathering_views 及 props / prop_damage_states / prop_detail_views。"""
    log.info("【阶段 3 落库】开始持久化短剧 [%s] 的空间场景与核心道具资产...", drama_id)
    now = now_iso()

    # 1. 场景主表与从表
    ep = getattr(state, "environments_and_props", None) or getattr(state, "environment_and_props_system", None) or {}
    if isinstance(ep, dict):
        env_list = ep.get("environments", []) or ep.get("scenes", [])
    elif hasattr(state, "scenes") and isinstance(state.scenes, list):
        env_list = state.scenes
    else:
        env_list = []
    if not env_list and hasattr(state, "new_scene_dossiers") and state.new_scene_dossiers:
        env_list = state.new_scene_dossiers

    for env in env_list:
        location = env.get("location_name") or env.get("name") or env.get("location") or env.get("scene_name")
        if not location:
            continue

        existing_scene = fetch_one(
            db,
            "SELECT id FROM scenes WHERE drama_id = :drama_id AND location = :loc",
            {"drama_id": drama_id, "loc": location},
        )
        scene_extra = json.dumps({
            "env_id": env.get("env_id", ""),
            "level": env.get("level", ""),
            "costume_resonance_check": env.get("costume_resonance_check", True),
            "three_layer_aging": env.get("three_layer_aging", {}),
            "weathering_layers": env.get("weathering_layers", {}),
            "atmosphere": env.get("atmosphere", ""),
            "spatial_layout": env.get("spatial_layout", ""),
        }, ensure_ascii=False)

        raw_s_code = str(env.get("scene_code") or env.get("code") or "").strip()
        s_code = raw_s_code if raw_s_code else AssetProtocolHelper.normalize_token(location)
        bench_scene_key = env.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_scene(s_code)

        if existing_scene:
            scene_id = existing_scene["id"]
            db.execute(
                text("""
                    UPDATE scenes
                    SET scene_code = CASE WHEN (scene_code IS NULL OR scene_code = '') AND :s_code != '' THEN :s_code ELSE scene_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        location = :location,
                        time = :time,
                        prompt = :prompt,
                        extra_images = :extra_images,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": scene_id,
                    "s_code": s_code,
                    "bench_key": bench_scene_key,
                    "location": location,
                    "time": env.get("time_and_lighting", ""),
                    "prompt": env.get("visual_prompt", ""),
                    "extra_images": scene_extra,
                    "updated_at": now,
                },
            )
        else:
            ins = db.execute(
                text("""
                    INSERT INTO scenes (
                        drama_id, scene_code, benchmark_asset_key, location, time, prompt,
                        extra_images, created_at, updated_at
                    ) VALUES (
                        :drama_id, :s_code, :bench_key, :location, :time, :prompt,
                        :extra_images, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "s_code": s_code,
                    "bench_key": bench_scene_key,
                    "location": location,
                    "time": env.get("time_and_lighting", ""),
                    "prompt": env.get("visual_prompt", ""),
                    "extra_images": scene_extra,
                    "now": now,
                },
            )
            scene_id = ins.lastrowid

        # 级联写入场景从表 1：scene_zones (子功能区域)
        zones_data = env.get("zones") or [{"zone_name": "核心主活动区", "time_lighting": env.get("time_and_lighting", "")}]
        for z_item in zones_data:
            z_name = z_item.get("zone_name", "主活动区")
            existing_zone = fetch_one(
                db,
                "SELECT id FROM scene_zones WHERE scene_id = :scene_id AND zone_name = :z_name",
                {"scene_id": scene_id, "z_name": z_name},
            )
            if not existing_zone:
                z_ins = db.execute(
                    text("""
                        INSERT INTO scene_zones (
                            scene_id, drama_id, zone_name, time_lighting,
                            acoustic_resistance, created_at, updated_at
                        ) VALUES (
                            :scene_id, :drama_id, :zone_name, :time_lighting,
                            :acoustic_resistance, :now, :now
                        )
                    """),
                    {
                        "scene_id": scene_id,
                        "drama_id": drama_id,
                        "zone_name": z_name,
                        "time_lighting": z_item.get("time_lighting") or env.get("time_and_lighting", ""),
                        "acoustic_resistance": z_item.get("acoustic_resistance", ""),
                        "now": now,
                    },
                )
                zone_db_id = z_ins.lastrowid
            else:
                zone_db_id = existing_zone["id"]

            # 级联写入场景从表 2：scene_weathering_views (气候做旧图层)
            w_layers = env.get("weathering_layers", {})
            if isinstance(w_layers, dict):
                scene_code = env.get("scene_code") or AssetProtocolHelper.normalize_token(env.get("code") or location)
                bench_scene_key = AssetProtocolHelper.get_benchmark_key_for_scene(scene_code)
                for layer_type, layer_desc in w_layers.items():
                    existing_w = fetch_one(
                        db,
                        "SELECT id FROM scene_weathering_views WHERE scene_zone_id = :z_id AND layer_type = :l_type",
                        {"z_id": zone_db_id, "l_type": str(layer_type)},
                    )
                    layer_tok = AssetProtocolHelper.normalize_token(str(layer_type))
                    w_asset_key = f"{bench_scene_key}_{layer_tok}"
                    w_delta, w_full = PromptSynthesizer.synthesize_scene_view_prompt(
                        env.get("visual_prompt") or location,
                        view_type="STATE",
                        weathering_prompt=str(layer_desc),
                        atmosphere_prompt=env.get("time_and_lighting", ""),
                    )
                    w_neg = PromptSynthesizer.get_negative_prompt("environment")
                    if not existing_w:
                        db.execute(
                            text("""
                                INSERT INTO scene_weathering_views (
                                    scene_zone_id, layer_type, description,
                                    asset_key, parent_asset_key, generation_mode, denoise_strength,
                                    visual_prompt, negative_prompt, is_benchmark, is_primary,
                                    is_locked_truth, created_at, updated_at
                                ) VALUES (
                                    :scene_zone_id, :layer_type, :description,
                                    :asset_key, :parent_asset_key, 'i2i', 0.45,
                                    :visual_prompt, :negative_prompt, 0, 0,
                                    0, :now, :now
                                )
                            """),
                            {
                                "scene_zone_id": zone_db_id,
                                "layer_type": str(layer_type),
                                "description": str(layer_desc),
                                "asset_key": w_asset_key,
                                "parent_asset_key": bench_scene_key,
                                "visual_prompt": w_full,
                                "negative_prompt": w_neg,
                                "now": now,
                            },
                        )

    # 2. 道具主表与从表
    if isinstance(ep, dict):
        prop_list = ep.get("props", [])
    elif hasattr(state, "props") and isinstance(state.props, list):
        prop_list = state.props
    else:
        prop_list = []
    if not prop_list and hasattr(state, "new_prop_dossiers") and state.new_prop_dossiers:
        prop_list = state.new_prop_dossiers

    for prop in prop_list:
        p_name = prop.get("name") or prop.get("prop_name")
        if not p_name:
            continue

        raw_p_code = str(prop.get("prop_code") or prop.get("code") or "").strip()
        p_code = raw_p_code if raw_p_code else AssetProtocolHelper.normalize_token(p_name)
        bench_prop_key = prop.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_prop(p_code)

        existing_prop = fetch_one(
            db,
            "SELECT id FROM props WHERE drama_id = :drama_id AND (name = :name OR prop_code = :p_code)",
            {"drama_id": drama_id, "name": p_name, "p_code": p_code},
        )
        prop_extra = json.dumps({
            "prop_id": prop.get("prop_id", ""),
            "level": prop.get("level", ""),
            "physical_specs": prop.get("physical_specs", {}),
            "damage_scale": prop.get("damage_scale", ""),
            "foley_resistance": prop.get("foley_resistance", ""),
        }, ensure_ascii=False)

        if existing_prop:
            prop_id = existing_prop["id"]
            db.execute(
                text("""
                    UPDATE props
                    SET prop_code = CASE WHEN (prop_code IS NULL OR prop_code = '') AND :p_code != '' THEN :p_code ELSE prop_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        type = :type,
                        description = :description,
                        prompt = :prompt,
                        extra_images = :extra_images,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": prop_id,
                    "p_code": p_code,
                    "bench_key": bench_prop_key,
                    "type": prop.get("type", "narrative_reversal"),
                    "description": prop.get("description", ""),
                    "prompt": prop.get("visual_prompt", ""),
                    "extra_images": prop_extra,
                    "updated_at": now,
                },
            )
        else:
            p_ins = db.execute(
                text("""
                    INSERT INTO props (
                        drama_id, prop_code, benchmark_asset_key, name, type, description, prompt, extra_images, created_at, updated_at
                    ) VALUES (
                        :drama_id, :p_code, :bench_key, :name, :type, :description, :prompt, :extra_images, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "p_code": p_code,
                    "bench_key": bench_prop_key,
                    "name": p_name,
                    "type": prop.get("type", "narrative_reversal"),
                    "description": prop.get("description", ""),
                    "prompt": prop.get("visual_prompt", ""),
                    "extra_images": prop_extra,
                    "now": now,
                },
            )
            prop_id = p_ins.lastrowid

        # 级联写入道具从表 1：prop_damage_states (损坏形态)
        d_states = prop.get("damage_states") or [{"state_label": "初始完整形态", "damage_desc": prop.get("description", "")}]
        p_code = AssetProtocolHelper.normalize_token(prop.get("prop_code") or prop.get("code") or p_name)
        bench_prop_key = AssetProtocolHelper.get_benchmark_key_for_prop(p_code)
        for idx, d_item in enumerate(d_states, start=1):
            s_label = d_item.get("state_label", f"形态_{idx}")
            state_code = f"S{idx-1}"
            existing_ds = fetch_one(
                db,
                "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND state_label = :s_label",
                {"prop_id": prop_id, "s_label": s_label},
            )
            if not existing_ds:
                ds_ins = db.execute(
                    text("""
                        INSERT INTO prop_damage_states (
                            prop_id, drama_id, state_code, state_label, damage_level,
                            narrative_point, created_at, updated_at
                        ) VALUES (
                            :prop_id, :drama_id, :state_code, :state_label, :damage_level,
                            :narrative_point, :now, :now
                        )
                    """),
                    {
                        "prop_id": prop_id,
                        "drama_id": drama_id,
                        "state_code": state_code,
                        "state_label": s_label,
                        "damage_level": d_item.get("damage_level", idx - 1),
                        "narrative_point": d_item.get("narrative_point") or d_item.get("damage_desc", ""),
                        "now": now,
                    },
                )
                ds_db_id = ds_ins.lastrowid
            else:
                ds_db_id = existing_ds["id"]
                db.execute(
                    text("""
                        UPDATE prop_damage_states
                        SET damage_level = :damage_level,
                            narrative_point = :narrative_point,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": ds_db_id,
                        "damage_level": d_item.get("damage_level", idx - 1),
                        "narrative_point": d_item.get("narrative_point") or d_item.get("damage_desc", ""),
                        "now": now,
                    },
                )

            # 级联写入道具从表 2：prop_detail_views (微距特写)
            existing_dv = fetch_one(
                db,
                "SELECT id FROM prop_detail_views WHERE damage_state_id = :ds_id AND view_type = 'macro_feature'",
                {"ds_id": ds_db_id},
            )
            macro_asset_key = f"{bench_prop_key}_{state_code}_DETAIL"
            p_id_prompt = PromptSynthesizer.extract_identity_face_anchor(prop.get("visual_prompt") or p_name)
            macro_delta = f"macro close-up feature of {s_label}"
            custom_detail_desc = ""
            raw_dvs = d_item.get("detail_views") or prop.get("detail_views") or []
            if isinstance(raw_dvs, list):
                for dv_item in raw_dvs:
                    if isinstance(dv_item, dict):
                        custom_detail_desc = dv_item.get("visual_prompt") or dv_item.get("description") or ""
                        if custom_detail_desc:
                            break
                    elif isinstance(dv_item, str) and dv_item.strip():
                        custom_detail_desc = dv_item.strip()
                        break
            if custom_detail_desc:
                macro_delta = f"{macro_delta}, {custom_detail_desc}"
            macro_synth = PromptSynthesizer.synthesize_prop_view_prompt(
                p_id_prompt,
                view_type="DETAIL",
                state_prompt=macro_delta,
            )
            p_neg = PromptSynthesizer.get_negative_prompt("prop")
            if existing_dv:
                db.execute(
                    text("""
                        UPDATE prop_detail_views
                        SET asset_key = :asset_key,
                            parent_asset_key = :parent_asset_key,
                            visual_prompt = :visual_prompt,
                            negative_prompt = :negative_prompt,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_dv["id"],
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_synth.visual_prompt,
                        "negative_prompt": p_neg,
                        "now": now,
                    },
                )
            else:
                db.execute(
                    text("""
                        INSERT INTO prop_detail_views (
                            damage_state_id, asset_key, view_type,
                            parent_asset_key, generation_mode, denoise_strength,
                            visual_prompt, negative_prompt,
                            is_benchmark, is_primary, is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :damage_state_id, :asset_key, 'macro_feature',
                            :parent_asset_key, 'crop_macro', 0.45,
                            :visual_prompt, :negative_prompt,
                            0, 1, 1, :now, :now
                        )
                    """),
                    {
                        "damage_state_id": ds_db_id,
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_synth.visual_prompt,
                        "negative_prompt": p_neg,
                        "now": now,
                    },
                )

    # 长期记忆自动入库与向量化（空间场景与叙事物证道具）
    stage3_memories = []
    for env in env_list:
        loc = env.get("location_name") or env.get("name")
        if not loc:
            continue
        stage3_memories.append({
            "title": f"空间场景三层设定: {loc}",
            "content": f"场景: {loc}\n光影与时段: {env.get('time_and_lighting', '')}\n视觉生图Prompt: {env.get('visual_prompt', '')}\n气候做旧图层: {json.dumps(env.get('weathering_layers', {}), ensure_ascii=False)}\n空间布局: {env.get('spatial_layout', '')}",
            "summary": f"场景 {loc}: {env.get('atmosphere', '')}",
            "keywords": [loc, "场景", "空间世界观", "三层做旧"],
            "memory_type": "world_rule",
            "source_type": "stage3_scene",
            "source_id": f"scene_{loc}",
        })
    for prop in prop_list:
        p_name = prop.get("name")
        if not p_name:
            continue
        stage3_memories.append({
            "title": f"叙事物证道具档案: {p_name}",
            "content": f"道具名: {p_name}\n叙事反转功能: {prop.get('type', '')}\n物理外观描述: {prop.get('description', '')}\n视觉提示词: {prop.get('visual_prompt', '')}\n损毁形态演进: {json.dumps(prop.get('damage_states', []), ensure_ascii=False)}",
            "summary": f"道具 {p_name}: {prop.get('description', '')}",
            "keywords": [p_name, "道具", "物证", "拟音"],
            "memory_type": "prop_anchor",
            "source_type": "stage3_prop",
            "source_id": f"prop_{p_name}",
        })
    sync_stage_memories_to_vector_db(db, drama_id, 3, stage3_memories)

    # 更新主表状态及元数据命名空间
    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    if state.scene_tokens:
        current_meta["scene_tokens"] = state.scene_tokens
    if state.prop_tokens:
        current_meta["prop_tokens"] = state.prop_tokens
    db.execute(
        text("UPDATE dramas SET current_stage = 3, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 3, state.latest_audit)

    db.commit()
    log.info("【阶段 3 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 4：全季大纲与音频动机母库持久化
# =========================================================================

