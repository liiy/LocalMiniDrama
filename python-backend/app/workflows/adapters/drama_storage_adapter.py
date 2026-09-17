"""短剧创作工坊两程九阶工业化状态存储适配器 (Drama Storage Adapter)。

【核心设计原则与架构】
1. 阶段化原子落库 (Per-Stage Atomic Persistence)：
   - 解决以往短剧项目主表没有更新、阶段结果未能及时写入数据库实体表的问题。
   - 每一个阶段（Stage 1 ~ Stage 8）均配备独立的原子持久化函数，并在操作完成时立即执行 `db.commit()`。
2. 实体表主字段 + 扩展元数据双轨映射：
   - dramas 表主字段（name, theme, drama_type, genre, target_audience, core_selling_points, logline,
     dramatic_irony, grand_payoff, aspect_ratio, target_duration_sec, emotional_tone, market_analysis,
     world_view, status, stage_status, pipeline_status 等）直接更新；
   - 扩展配置统一存入 metadata JSON 字段；
3. 多级资产层级落库 (Multi-Tier Asset Hierarchy)：
   - 角色：characters (一级身份) -> character_stages (二级生命周期阶段) -> character_stage_views (三级多视角/特写)
   - 场景：scenes (一级核心主场景) -> scene_zones (二级子功能区域) -> scene_weathering_views (三级气候做旧图层)
   - 道具：props (一级核心叙事物证) -> prop_damage_states (二级损坏演进形态) -> prop_detail_views (三级微距特写)
4. 短期工作记忆与 Redis 解耦 (Short-Term Memory in Redis with DB Fallback)：
   - 阶段运行时产生的即时工作记忆便签（Pad A/B/C/D）实时同步至 Redis（7天 TTL），并支持数据库 Cache-Aside 重建。
5. 红蓝对抗质量报告归档 (Quality Reports)：
   - 蓝军客观合规审查得分与红军尖锐魔鬼挑刺意见结构化持久化至 `quality_reports` 表。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.context import memory_service, vector_memory_service
from app.context.short_memory_service import set_short_memories, get_short_memories
from app.core.logger import get_logger
from app.db.session import fetch_all, fetch_one
from app.platform_common import now_iso
from app.schemas.script_graph_state import (
    AudioBible,
    CandidateTitleMatrix,
    DoubleTrackProhibitions,
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
    RedBlueAuditReport,
    StoryboardShot,
)

log = get_logger("lmd.storage_adapter")


def _safe_json_loads(data: Any, default: Any = None) -> Any:
    """安全反序列化 JSON 数据。"""
    if data is None:
        return default if default is not None else {}
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, str):
        trimmed = data.strip()
        if not trimmed:
            return default if default is not None else {}
        try:
            return json.loads(trimmed)
        except Exception:
            return default if default is not None else {}
    return default if default is not None else {}


def _dump_or_dict(val: Any) -> Any:
    """安全提取 Pydantic Model 字典或原生 dict。"""
    if val is None:
        return {}
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, dict):
        return val
    return val


def sync_stage_memories_to_vector_db(
    db: Session,
    drama_id: int,
    stage_id: int,
    items: list[dict[str, Any]],
) -> None:
    """将流水线阶段产生的核心结构化长期记忆同步落库至 memory_items 表并构建 Qdrant 向量索引。
    
    【工业级保障】
    1. 幂等性：基于 (drama_id, source_type, source_id) 查重，避免重复落库导致数据冗余；
    2. 自动向量化：自动生成 1536 维特征向量并写入剧目隔离的 Qdrant 向量集合；
    3. 容灾隔离：向量库异常或未部署时不阻断主关系型数据库事务，保证业务 100% 可用。
    """
    if not items or not drama_id:
        return
    log.debug("【长期记忆同步】开始为短剧 [%s] 阶段 %s 同步 %d 条核心长期记忆...", drama_id, stage_id, len(items))
    for item_data in items:
        try:
            source_type = item_data.get("source_type") or f"stage{stage_id}"
            source_id = str(item_data.get("source_id") or "")
            existing = None
            if source_id:
                existing = fetch_one(
                    db,
                    "SELECT id FROM memory_items WHERE drama_id = :did AND source_type = :st AND source_id = :sid AND deleted_at IS NULL",
                    {"did": drama_id, "st": source_type, "sid": source_id},
                )
            if existing:
                memory_service.update_memory_item(
                    db,
                    int(existing["id"]),
                    {
                        "title": item_data.get("title"),
                        "content": item_data.get("content"),
                        "summary": item_data.get("summary"),
                        "keywords": item_data.get("keywords"),
                        "status": "active",
                    },
                    editor=f"stage{stage_id}_auto_pipeline",
                )
                row = fetch_one(db, "SELECT * FROM memory_items WHERE id = :id", {"id": existing["id"]})
                if row:
                    vector_memory_service.index_memory_item(db, dict(row))
            else:
                payload = {
                    "drama_id": drama_id,
                    "episode_id": item_data.get("episode_id"),
                    "memory_type": item_data.get("memory_type") or "world_bible",
                    "scope": item_data.get("scope") or "drama",
                    "title": item_data.get("title") or f"Stage {stage_id} 关键记忆",
                    "content": item_data.get("content"),
                    "summary": item_data.get("summary"),
                    "keywords": item_data.get("keywords") or [],
                    "source_type": source_type,
                    "source_id": source_id,
                    "metadata": item_data.get("metadata") or {"stage": stage_id},
                    "status": "active",
                }
                memory_service.add_memory_item(db, payload)
        except Exception as exc:
            log.warning("【长期记忆同步】同步阶段记忆项失败 (%s): %s", item_data.get("title"), exc)


def persist_audit_report(
    db: Session,
    drama_id: int,
    stage_id: int,
    audit: RedBlueAuditReport | dict[str, Any] | None,
    episode_id: int | None = None,
) -> None:
    """将红蓝对抗独立质检报告持久化至 quality_reports 数据库表。"""
    if not audit:
        return

    log.debug("【质检落库】开始持久化剧目 [%s] 阶段 %s 的红蓝对抗报告...", drama_id, stage_id)
    now = now_iso()
    audit_dict = _dump_or_dict(audit)
    
    # 提取判定结果与各方审查数据
    verdict = audit_dict.get("verdict", "GREEN_APPROVED")
    blue_compliance = audit_dict.get("blue_team_compliance") or audit_dict.get("blue_checks") or {}
    red_criticism = audit_dict.get("red_team_criticism") or audit_dict.get("red_complaints") or {}
    blocking_issues = audit_dict.get("blocking_issues") or []
    warning_suggestions = audit_dict.get("warning_suggestions") or []
    
    # 计算综合分值
    score = 95.0 if verdict == "GREEN_APPROVED" else (80.0 if verdict == "YELLOW_WARNING" else 50.0)
    passed = 1 if verdict in ("GREEN_APPROVED", "YELLOW_WARNING") else 0

    try:
        db.execute(
            text("""
                INSERT INTO quality_reports (
                    drama_id, episode_id, stage_id, report_type, status,
                    score, passed, patch_applied, radar_scores, issues,
                    suggestions, raw_report, blue_compliance_score, blue_checklist,
                    red_sharp_critiques, anti_degrade_alerts, created_at, updated_at
                ) VALUES (
                    :drama_id, :episode_id, :stage_id, 'red_blue_audit', 'open',
                    :score, :passed, 0, :radar_scores, :issues,
                    :suggestions, :raw_report, :blue_score, :blue_checklist,
                    :red_critiques, :anti_degrade, :now, :now
                )
            """),
            {
                "drama_id": drama_id,
                "episode_id": episode_id,
                "stage_id": stage_id,
                "score": score,
                "passed": passed,
                "radar_scores": json.dumps({"overall": score}, ensure_ascii=False),
                "issues": json.dumps(blocking_issues, ensure_ascii=False),
                "suggestions": json.dumps(warning_suggestions, ensure_ascii=False),
                "raw_report": json.dumps(audit_dict, ensure_ascii=False),
                "blue_score": 100.0 if passed else 60.0,
                "blue_checklist": json.dumps(blue_compliance, ensure_ascii=False),
                "red_critiques": json.dumps(red_criticism, ensure_ascii=False),
                "anti_degrade": json.dumps(blocking_issues, ensure_ascii=False),
                "now": now,
            },
        )
    except Exception as e:
        log.warning("【质检落库】写入 quality_reports 表异常: %s", e)


# =========================================================================
# 阶段 1：题材立项、双轨禁令与高概念持久化
# =========================================================================

def persist_stage1(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """阶段 1 原子落库：更新短剧主表核心字段、高概念设定与短期记忆便签 A。"""
    log.info("【阶段 1 落库】开始持久化短剧 [%s] 的题材立项与高概念信息...", drama_id)
    now = now_iso()
    drama_row = fetch_one(db, "SELECT * FROM dramas WHERE id = :id", {"id": drama_id})
    if not drama_row:
        raise ValueError(f"Drama with ID {drama_id} does not exist.")

    current_meta = _safe_json_loads(drama_row.get("metadata"), {})
    
    # 同步阶段 1 核心元数据
    current_meta["candidate_titles"] = _dump_or_dict(state.candidate_titles)
    current_meta["negative_rules"] = _dump_or_dict(state.negative_rules)
    current_meta["aspect_ratio"] = state.aspect_ratio
    current_meta["target_duration_sec"] = state.target_duration_sec
    current_meta["visual_style"] = state.visual_style
    current_meta["logline"] = state.logline
    current_meta["dramatic_irony"] = state.dramatic_irony
    current_meta["grand_payoff"] = state.grand_payoff
    current_meta["current_stage"] = 1
    current_meta["journey"] = "journey_1_literary"
    current_meta["latest_audit"] = _dump_or_dict(state.latest_audit)

    title_val = state.selected_title or drama_row.get("name") or drama_row.get("title") or "未定名短剧"

    # 更新 dramas 主表独立列与 metadata JSON 列
    db.execute(
        text("""
            UPDATE dramas
            SET title = :title,
                description = :description,
                genre = :genre,
                style = :style,
                candidate_titles = :candidate_titles,
                negative_rules = :negative_rules,
                dramatic_irony = :dramatic_irony,
                grand_payoff = :grand_payoff,
                aspect_ratio = :aspect_ratio,
                target_duration_sec = :target_duration_sec,
                total_episodes = :total_episodes,
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
            "genre": state.genre or "悬疑",
            "style": state.visual_style or "realistic",
            "candidate_titles": json.dumps(state.candidate_titles.model_dump() if hasattr(state.candidate_titles, "model_dump") else (state.candidate_titles or {}), ensure_ascii=False),
            "negative_rules": json.dumps(state.negative_rules.model_dump() if hasattr(state.negative_rules, "model_dump") else (state.negative_rules or {}), ensure_ascii=False),
            "dramatic_irony": state.dramatic_irony or "",
            "grand_payoff": state.grand_payoff or "",
            "aspect_ratio": state.aspect_ratio or "9:16",
            "target_duration_sec": float(state.target_duration_sec or 120.0),
            "total_episodes": int(state.total_episodes or 1),
            "metadata": json.dumps(current_meta, ensure_ascii=False),
            "updated_at": now,
        },
    )

    # 长期记忆自动入库与向量化（剧目立项与高概念）
    stage1_memories = [
        {
            "title": f"剧目立项高概念: {title_val}",
            "content": f"剧名: {title_val}\n题材: {state.genre}\n视觉风格: {state.visual_style}\n一句话梗概: {state.logline}\n核心讽刺/戏剧反差: {state.dramatic_irony}\n大结局终局释放: {state.grand_payoff}",
            "summary": f"{state.genre}题材，{state.logline}",
            "keywords": [state.genre or "短剧", state.visual_style or "现实", "高概念", "立项"],
            "memory_type": "world_bible",
            "source_type": "stage1_high_concept",
            "source_id": f"drama_{drama_id}_high_concept",
        }
    ]
    sync_stage_memories_to_vector_db(db, drama_id, 1, stage1_memories)

    # 同步短期记忆便签 A 与物理快照至 Redis
    if not state.short_memory_a:
        state.short_memory_a = f"【题材】{state.genre} | 【风格】{state.visual_style} | 【核心讽刺】{state.dramatic_irony} | 【终局核爆】{state.grand_payoff}"
    
    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": state.short_memory_d,
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
        },
        stage_name="stage1_ideation",
    )

    # 记录质检报告
    if state.latest_audit:
        persist_audit_report(db, drama_id, 1, state.latest_audit)

    db.commit()
    log.info("【阶段 1 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 2：角色引擎、心理四元组与三级角色资产持久化
# =========================================================================

def persist_stage2(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """阶段 2 原子落库：写入 characters 主表、从表 (character_stages / character_stage_views) 及短期记忆 B。"""
    log.info("【阶段 2 落库】开始持久化短剧 [%s] 的角色全息资产与多级形态...", drama_id)
    now = now_iso()
    characters_list = state.characters_engine.get("characters", [])

    for char in characters_list:
        char_name = char.get("name")
        if not char_name:
            continue

        existing_char = fetch_one(
            db,
            "SELECT id FROM characters WHERE drama_id = :drama_id AND name = :name",
            {"drama_id": drama_id, "name": char_name},
        )

        growth_chain_json = json.dumps({
            "psychological_quad": char.get("psychological_quad", {}),
            "emotional_arc_trajectories": char.get("emotional_arc_trajectories", []),
            "growth_chain": char.get("growth_chain", []),
        }, ensure_ascii=False)

        current_status_json = json.dumps({
            "voice_fingerprint": char.get("voice_fingerprint", {}),
            "carried_anchor_item": char.get("carried_anchor_item", {}),
            "biological_dna": char.get("biological_dna", {}),
            "lived_in_costume": char.get("lived_in_costume", {}),
            "dual_track_relationships": char.get("dual_track_relationships", []),
        }, ensure_ascii=False)

        identity_anchors_json = json.dumps(char.get("identity_anchors", []), ensure_ascii=False)

        if existing_char:
            char_id = existing_char["id"]
            db.execute(
                text("""
                    UPDATE characters
                    SET role = :role,
                        personality = :personality,
                        appearance = :appearance,
                        identity_anchors = :identity_anchors,
                        voice_style = :voice_style,
                        growth_chain = :growth_chain,
                        current_status = :current_status,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": char_id,
                    "role": char.get("role_type") or char.get("role") or "protagonist",
                    "personality": char.get("personality", ""),
                    "appearance": char.get("appearance", "") or char.get("visual_anchor", ""),
                    "identity_anchors": identity_anchors_json,
                    "voice_style": char.get("voice_style", ""),
                    "growth_chain": growth_chain_json,
                    "current_status": current_status_json,
                    "updated_at": now,
                },
            )
        else:
            insert_res = db.execute(
                text("""
                    INSERT INTO characters (
                        drama_id, name, role, personality, appearance,
                        identity_anchors, voice_style,
                        growth_chain, current_status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :name, :role, :personality, :appearance,
                        :identity_anchors, :voice_style,
                        :growth_chain, :current_status, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "name": char_name,
                    "role": char.get("role_type") or char.get("role") or "protagonist",
                    "personality": char.get("personality", ""),
                    "appearance": char.get("appearance", "") or char.get("visual_anchor", ""),
                    "identity_anchors": identity_anchors_json,
                    "voice_style": char.get("voice_style", ""),
                    "growth_chain": growth_chain_json,
                    "current_status": current_status_json,
                    "now": now,
                },
            )
            char_id = insert_res.lastrowid

        # 级联写入从表 1：character_stages (角色生命周期阶段)
        stages_data = char.get("stages") or char.get("character_stages") or []
        if not stages_data:
            stages_data = [{
                "stage_name": "初始基线形态",
                "start_episode": 1,
                "end_episode": 100,
                "costume_description": char.get("lived_in_costume", {}).get("outerwear", "") if isinstance(char.get("lived_in_costume"), dict) else "",
                "color_palette": json.dumps(char.get("color_palette", {}), ensure_ascii=False) if isinstance(char.get("color_palette"), dict) else "",
            }]

        for idx, st_item in enumerate(stages_data, start=1):
            s_name = st_item.get("stage_name", f"阶段_{idx}")
            existing_stage = fetch_one(
                db,
                "SELECT id FROM character_stages WHERE character_id = :char_id AND stage_name = :s_name",
                {"char_id": char_id, "s_name": s_name},
            )
            c_palette = st_item.get("color_palette")
            if isinstance(c_palette, (dict, list)):
                c_palette = json.dumps(c_palette, ensure_ascii=False)

            costume_desc = st_item.get("costume_description") or st_item.get("costume_desc", "")
            start_ep = st_item.get("start_episode", idx)
            end_ep = st_item.get("end_episode", 100)

            if existing_stage:
                stage_db_id = existing_stage["id"]
                db.execute(
                    text("""
                        UPDATE character_stages
                        SET start_episode = :start_episode,
                            end_episode = :end_episode,
                            costume_description = :costume_description,
                            color_palette = :color_palette,
                            updated_at = :updated_at
                        WHERE id = :id
                    """),
                    {
                        "id": stage_db_id,
                        "start_episode": start_ep,
                        "end_episode": end_ep,
                        "costume_description": costume_desc,
                        "color_palette": str(c_palette or ""),
                        "updated_at": now,
                    },
                )
            else:
                s_ins = db.execute(
                    text("""
                        INSERT INTO character_stages (
                            character_id, drama_id, stage_name, start_episode, end_episode,
                            costume_description, color_palette, is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :character_id, :drama_id, :stage_name, :start_episode, :end_episode,
                            :costume_description, :color_palette, 0, :now, :now
                        )
                    """),
                    {
                        "character_id": char_id,
                        "drama_id": drama_id,
                        "stage_name": s_name,
                        "start_episode": start_ep,
                        "end_episode": end_ep,
                        "costume_description": costume_desc,
                        "color_palette": str(c_palette or ""),
                        "now": now,
                    },
                )
                stage_db_id = s_ins.lastrowid

            # 级联写入从表 2：character_stage_views (三级多视角资产)
            views_data = st_item.get("views") or []
            if not views_data:
                views_data = [{"view_type": "main_portrait", "image_prompt": char.get("visual_prompt", "")}]
            for v_item in views_data:
                v_type = v_item.get("view_type", "main_portrait")
                existing_view = fetch_one(
                    db,
                    "SELECT id FROM character_stage_views WHERE character_stage_id = :st_id AND view_type = :v_type",
                    {"st_id": stage_db_id, "v_type": v_type},
                )
                if not existing_view:
                    db.execute(
                        text("""
                            INSERT INTO character_stage_views (
                                character_stage_id, view_type, view_label,
                                image_prompt, negative_prompt, is_primary, created_at, updated_at
                            ) VALUES (
                                :character_stage_id, :view_type, :view_label,
                                :image_prompt, :negative_prompt, 0, :now, :now
                            )
                        """),
                        {
                            "character_stage_id": stage_db_id,
                            "view_type": v_type,
                            "view_label": v_item.get("view_label", v_type),
                            "image_prompt": v_item.get("image_prompt") or v_item.get("prompt", ""),
                            "negative_prompt": v_item.get("negative_prompt", ""),
                            "now": now,
                        },
                    )

    # 长期记忆自动入库与向量化（角色全息档案与心理四元组）
    stage2_memories = []
    for char in characters_list:
        c_name = char.get("name")
        if not c_name:
            continue
        c_quad = char.get("psychological_quad") or {}
        c_arc = char.get("emotional_arc_trajectories") or []
        stage2_memories.append({
            "title": f"角色全息档案: {c_name} ({char.get('role_type', '主要角色')})",
            "content": f"角色名: {c_name}\n定位: {char.get('role_type', '主要角色')}\n性格特征: {char.get('personality', '')}\n外貌装造锚点: {char.get('appearance') or char.get('lived_in_costume', {})}\n心理四元组: {json.dumps(c_quad, ensure_ascii=False)}\n人物弧光: {json.dumps(c_arc, ensure_ascii=False)}\n声纹特征: {json.dumps(char.get('voice_fingerprint', {}), ensure_ascii=False)}",
            "summary": f"{c_name}: {char.get('role_type', '')}, {char.get('personality', '')}",
            "keywords": [c_name, char.get("role_type", "角色"), "人物档案", "角色引擎"],
            "memory_type": "character_profile",
            "source_type": "stage2_character",
            "source_id": f"char_{c_name}",
        })
    sync_stage_memories_to_vector_db(db, drama_id, 2, stage2_memories)

    # 更新主表状态
    db.execute(
        text("UPDATE dramas SET current_stage = 2, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "now": now},
    )

    # 同步短期记忆便签 B 与物理状态至 Redis
    if not state.short_memory_b:
        chars_summary = [f"{c.get('name')}({c.get('role_type')})" for c in characters_list]
        state.short_memory_b = f"【核心人物】: {', '.join(chars_summary)}"
    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": state.short_memory_d,
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
        },
        stage_name="stage2_character",
    )

    if state.latest_audit:
        persist_audit_report(db, drama_id, 2, state.latest_audit)

    db.commit()
    log.info("【阶段 2 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 3：空间三层做旧、场景区域与物证拟音持久化
# =========================================================================

def persist_stage3(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """阶段 3 原子落库：写入 scenes / scene_zones / scene_weathering_views 及 props / prop_damage_states / prop_detail_views。"""
    log.info("【阶段 3 落库】开始持久化短剧 [%s] 的空间场景与核心道具资产...", drama_id)
    now = now_iso()

    # 1. 场景主表与从表
    env_list = state.environments_and_props.get("environments", [])
    for env in env_list:
        location = env.get("location_name") or env.get("name")
        if not location:
            continue

        existing_scene = fetch_one(
            db,
            "SELECT id FROM scenes WHERE drama_id = :drama_id AND location = :loc",
            {"drama_id": drama_id, "loc": location},
        )
        scene_extra = json.dumps({
            "weathering_layers": env.get("weathering_layers", {}),
            "atmosphere": env.get("atmosphere", ""),
            "spatial_layout": env.get("spatial_layout", ""),
        }, ensure_ascii=False)

        if existing_scene:
            scene_id = existing_scene["id"]
            db.execute(
                text("""
                    UPDATE scenes
                    SET location = :location,
                        time = :time,
                        prompt = :prompt,
                        extra_images = :extra_images,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": scene_id,
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
                        drama_id, location, time, prompt,
                        extra_images, created_at, updated_at
                    ) VALUES (
                        :drama_id, :location, :time, :prompt,
                        :extra_images, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
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
                for layer_type, layer_desc in w_layers.items():
                    existing_w = fetch_one(
                        db,
                        "SELECT id FROM scene_weathering_views WHERE scene_zone_id = :z_id AND layer_type = :l_type",
                        {"z_id": zone_db_id, "l_type": str(layer_type)},
                    )
                    if not existing_w:
                        db.execute(
                            text("""
                                INSERT INTO scene_weathering_views (
                                    scene_zone_id, layer_type, description, visual_prompt,
                                    is_locked_truth, created_at, updated_at
                                ) VALUES (
                                    :scene_zone_id, :layer_type, :description, :visual_prompt,
                                    0, :now, :now
                                )
                            """),
                            {
                                "scene_zone_id": zone_db_id,
                                "layer_type": str(layer_type),
                                "description": str(layer_desc),
                                "visual_prompt": f"{env.get('visual_prompt', '')} [{layer_desc}]",
                                "now": now,
                            },
                        )

    # 2. 道具主表与从表
    prop_list = state.environments_and_props.get("props", [])
    for prop in prop_list:
        p_name = prop.get("name")
        if not p_name:
            continue

        existing_prop = fetch_one(
            db,
            "SELECT id FROM props WHERE drama_id = :drama_id AND name = :name",
            {"drama_id": drama_id, "name": p_name},
        )
        prop_extra = json.dumps({
            "damage_scale": prop.get("damage_scale", ""),
            "foley_resistance": prop.get("foley_resistance", ""),
        }, ensure_ascii=False)

        if existing_prop:
            prop_id = existing_prop["id"]
            db.execute(
                text("""
                    UPDATE props
                    SET type = :type,
                        description = :description,
                        prompt = :prompt,
                        extra_images = :extra_images,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": prop_id,
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
                        drama_id, name, type, description, prompt, extra_images, created_at, updated_at
                    ) VALUES (
                        :drama_id, :name, :type, :description, :prompt, :extra_images, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
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
        for idx, d_item in enumerate(d_states, start=1):
            s_label = d_item.get("state_label", f"形态_{idx}")
            existing_ds = fetch_one(
                db,
                "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND state_label = :s_label",
                {"prop_id": prop_id, "s_label": s_label},
            )
            if not existing_ds:
                ds_ins = db.execute(
                    text("""
                        INSERT INTO prop_damage_states (
                            prop_id, drama_id, state_label, damage_level,
                            narrative_point, created_at, updated_at
                        ) VALUES (
                            :prop_id, :drama_id, :state_label, :damage_level,
                            :narrative_point, :now, :now
                        )
                    """),
                    {
                        "prop_id": prop_id,
                        "drama_id": drama_id,
                        "state_label": s_label,
                        "damage_level": d_item.get("damage_level", idx - 1),
                        "narrative_point": d_item.get("narrative_point") or d_item.get("damage_desc", ""),
                        "now": now,
                    },
                )
                ds_db_id = ds_ins.lastrowid
            else:
                ds_db_id = existing_ds["id"]

            # 级联写入道具从表 2：prop_detail_views (微距特写)
            existing_dv = fetch_one(
                db,
                "SELECT id FROM prop_detail_views WHERE damage_state_id = :ds_id AND view_type = 'macro_feature'",
                {"ds_id": ds_db_id},
            )
            if not existing_dv:
                db.execute(
                    text("""
                        INSERT INTO prop_detail_views (
                            damage_state_id, view_type, visual_prompt,
                            is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :damage_state_id, 'macro_feature', :visual_prompt,
                            0, :now, :now
                        )
                    """),
                    {
                        "damage_state_id": ds_db_id,
                        "visual_prompt": prop.get("visual_prompt", ""),
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

    db.execute(
        text("UPDATE dramas SET current_stage = 3, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "now": now},
    )

    # 同步短期记忆便签 C 与物理状态至 Redis
    if not state.short_memory_c:
        scenes_str = ", ".join([s.get("location_name") or s.get("name") or "" for s in env_list])
        props_str = ", ".join([p.get("name") or "" for p in prop_list])
        state.short_memory_c = f"【空间场景】: {scenes_str} | 【关键道具】: {props_str}"
    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": state.short_memory_d,
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
        },
        stage_name="stage3_environment_prop",
    )

    if state.latest_audit:
        persist_audit_report(db, drama_id, 3, state.latest_audit)

    db.commit()
    log.info("【阶段 3 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 4：全季大纲与音频动机母库持久化
# =========================================================================

def persist_stage4(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """阶段 4 原子落库：写入 music_bibles / episodes (分集大纲与断点钩子)。"""
    log.info("【阶段 4 落库】开始持久化短剧 [%s] 的全季大纲与音乐动机母库...", drama_id)
    now = now_iso()

    # 1. 写入 music_bibles 表
    audio_bible_dict = _dump_or_dict(state.audio_bible)
    motifs = audio_bible_dict.get("leitmotifs", [])
    motifs_json = json.dumps(motifs, ensure_ascii=False)
    foley_rules_json = json.dumps(audio_bible_dict.get("foley_rules", {}), ensure_ascii=False)

    existing_mb = fetch_one(db, "SELECT id FROM music_bibles WHERE drama_id = :drama_id", {"drama_id": drama_id})
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
                "style": state.visual_style,
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
                "style": state.visual_style,
                "theme_prompt": motifs_json,
                "instruments": motifs_json,
                "mixing_rules": foley_rules_json,
                "now": now,
            },
        )

    # 2. 写入分集大纲骨架至 episodes 表
    season_outlines = state.season_outlines or {}
    ep_items = season_outlines.get("episodes") or []
    for idx, ep_info in enumerate(ep_items, start=1):
        ep_num = ep_info.get("episode_number") or ep_info.get("episode_num") or idx
        ep_title = ep_info.get("title", f"第{ep_num}集")
        hook = ep_info.get("hook") or ep_info.get("core_action", "")
        climax = ep_info.get("climax") or ep_info.get("core_resistance", "")
        cliffhanger = ep_info.get("cliffhanger") or ep_info.get("ending_cliffhanger", "")

        existing_ep = fetch_one(
            db,
            "SELECT id FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": ep_num},
        )
        if existing_ep:
            db.execute(
                text("""
                    UPDATE episodes
                    SET title = :title,
                        hook = :hook,
                        climax = :climax,
                        cliffhanger = :cliffhanger,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": existing_ep["id"],
                    "title": ep_title,
                    "hook": hook,
                    "climax": climax,
                    "cliffhanger": cliffhanger,
                    "updated_at": now,
                },
            )
        else:
            db.execute(
                text("""
                    INSERT INTO episodes (
                        drama_id, episode_number, title, hook, climax,
                        cliffhanger, duration, status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :ep_num, :title, :hook, :climax,
                        :cliffhanger, :duration, 'outline_completed', :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "ep_num": ep_num,
                    "title": ep_title,
                    "hook": hook,
                    "climax": climax,
                    "cliffhanger": cliffhanger,
                    "duration": int(state.target_duration_sec),
                    "now": now,
                },
            )

    # 长期记忆自动入库与向量化（音频大纲与全季分集大纲骨架）
    stage4_memories = [
        {
            "title": "全剧配乐动机母库 (Audio Bible)",
            "content": f"全剧视听基调: {state.visual_style}\n主导动机主题: {motifs_json}\n动效拟音混音规则: {foley_rules_json}",
            "summary": f"音频母库: {len(motifs)}个动机主题",
            "keywords": ["音频母库", "BGM", "音效", "Leitmotif"],
            "memory_type": "audio_bible",
            "source_type": "stage4_audio_bible",
            "source_id": f"drama_{drama_id}_audio_bible",
        }
    ]
    for idx, ep_info in enumerate(ep_items, start=1):
        ep_num = ep_info.get("episode_number") or ep_info.get("episode_num") or idx
        ep_title = ep_info.get("title", f"第{ep_num}集")
        stage4_memories.append({
            "title": f"第{ep_num}集大纲与断点钩子: {ep_title}",
            "content": f"第{ep_num}集: {ep_title}\n开篇钩子: {ep_info.get('hook', '')}\n核心对抗/高潮: {ep_info.get('climax', '')}\n集末断点/生死悬念: {ep_info.get('cliffhanger', '')}",
            "summary": f"第{ep_num}集: 钩子[{ep_info.get('hook', '')[:20]}] 断点[{ep_info.get('cliffhanger', '')[:20]}]",
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
    current_meta["season_outlines"] = state.season_outlines
    current_meta["audio_bible"] = _dump_or_dict(state.audio_bible)
    current_meta["current_stage"] = 4

    db.execute(
        text("UPDATE dramas SET current_stage = 4, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    # 同步短期记忆便签 D
    if not state.short_memory_d:
        state.short_memory_d = f"【全季大纲已就绪】总集数: {state.total_episodes}，音乐主题动机数: {len(motifs)}"
    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": state.short_memory_d,
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
        },
        stage_name="stage4_outline",
    )

    if state.latest_audit:
        persist_audit_report(db, drama_id, 4, state.latest_audit)

    db.commit()
    log.info("【阶段 4 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 5：Mini-Arc 工笔文学剧本波次生成持久化
# =========================================================================

def persist_stage5(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """阶段 5 原子落库：写入 episodes 正文内容、AST 分块、节奏自检与定稿锁定状态。"""
    log.info("【阶段 5 落库】开始持久化短剧 [%s] 的全季文学剧本工笔正文...", drama_id)
    now = now_iso()

    stage5_memories = []
    for ep_num, ep_data in state.completed_screenplays.items():
        existing_ep = fetch_one(
            db,
            "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": ep_num},
        )
        ep_ast = _safe_json_loads(existing_ep.get("ast_blocks") if existing_ep else None, {})
        ep_ast["safety_guardrails_lock"] = ep_data.get("safety_guardrails_lock", {})
        ep_ast["dramatic_rhythm_check"] = ep_data.get("dramatic_rhythm_check", {})
        ep_ast["episode_end_physical_delta"] = ep_data.get("episode_end_physical_delta", {})
        ep_ast["previous_episode_physical_pickup"] = ep_data.get("previous_episode_physical_pickup", {})

        script_content_json = json.dumps(ep_data, ensure_ascii=False)
        ep_title = ep_data.get("title", f"第{ep_num}集")
        duration = int(ep_data.get("duration_seconds", state.target_duration_sec))

        if existing_ep:
            db.execute(
                text("""
                    UPDATE episodes
                    SET title = :title,
                        script_content = :script_content,
                        duration = :duration,
                        ast_blocks = :ast_blocks,
                        status = 'script_completed',
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": existing_ep["id"],
                    "title": ep_title,
                    "script_content": script_content_json,
                    "duration": duration,
                    "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
                    "updated_at": now,
                },
            )
        else:
            db.execute(
                text("""
                    INSERT INTO episodes (
                        drama_id, episode_number, title, script_content, duration,
                        ast_blocks, status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :ep_num, :title, :script_content, :duration,
                        :ast_blocks, 'script_completed', :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "ep_num": ep_num,
                    "title": ep_title,
                    "script_content": script_content_json,
                    "duration": duration,
                    "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
                    "now": now,
                },
            )

        sc_text = ep_data.get("screenplay_content") or script_content_json
        stage5_memories.append({
            "title": f"第{ep_num}集定稿文学剧本: {ep_title}",
            "content": f"第{ep_num}集剧本文学正文 (节选前1500字):\n{str(sc_text)[:1500]}\n物理状态承接: {json.dumps(ep_data.get('previous_episode_physical_pickup', {}), ensure_ascii=False)}\n集末物理位移: {json.dumps(ep_data.get('episode_end_physical_delta', {}), ensure_ascii=False)}",
            "summary": f"第{ep_num}集定稿剧本: {ep_title}",
            "keywords": [f"第{ep_num}集", "文学剧本", ep_title, "定稿剧本"],
            "memory_type": "screenplay",
            "source_type": "stage5_screenplay",
            "source_id": f"ep_screenplay_{ep_num}",
        })

    # 长期记忆自动入库与向量化（全季定稿文学剧本）
    sync_stage_memories_to_vector_db(db, drama_id, 5, stage5_memories)

    lock_val = 1 if state.literary_journey_locked else 0
    p_status = "first_journey_locked" if state.literary_journey_locked else "running"

    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    current_meta["inter_episode_physical_snapshot"] = state.inter_episode_physical_snapshot
    current_meta["literary_journey_locked"] = state.literary_journey_locked
    current_meta["current_mini_arc_index"] = state.current_mini_arc_index
    current_meta["current_stage"] = 5

    db.execute(
        text("""
            UPDATE dramas
            SET lock_status = :lock_status,
                pipeline_status = :p_status,
                current_stage = 5,
                metadata = :metadata,
                updated_at = :now
            WHERE id = :id
        """),
        {"id": drama_id, "lock_status": lock_val, "p_status": p_status, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": f"【文学剧本全季交付】已完成集数: {len(state.completed_screenplays)}/{state.total_episodes}",
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
        },
        stage_name="stage5_screenplay",
    )

    if state.latest_audit:
        persist_audit_report(db, drama_id, 5, state.latest_audit)

    db.commit()
    log.info("【阶段 5 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 6：单集视听资源引单与资产校验持久化
# =========================================================================

def persist_stage6(
    db: Session,
    drama_id: int,
    state: IndustrialDramaMasterState,
    episode_num: int | None = None,
) -> None:
    """阶段 6 原子落库：写入 episodes.ast_blocks 的 episode_resource_manifest。"""
    curr_ep = episode_num or state.current_visual_episode
    log.info("【阶段 6 落库】开始持久化短剧 [%s] 第 %s 集的视听资源引单...", drama_id, curr_ep)
    now = now_iso()

    manifest = state.episode_manifests.get(curr_ep)
    if manifest:
        manifest_dict = _dump_or_dict(manifest)
        ep_row = fetch_one(
            db,
            "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": curr_ep},
        )
        if ep_row:
            ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
            ep_ast["episode_resource_manifest"] = manifest_dict
            db.execute(
                text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
                {"id": ep_row["id"], "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
            )

        # 长期记忆自动入库与向量化（单集资源清单）
        stage6_memories = [
            {
                "title": f"第{curr_ep}集视听资源清单与登场资产",
                "content": f"第{curr_ep}集多模态引单:\n登场角色变体: {json.dumps(manifest_dict.get('characters_in_scene', []), ensure_ascii=False)}\n发生场景与做旧层: {json.dumps(manifest_dict.get('scenes_in_use', []), ensure_ascii=False)}\n关键叙事道具: {json.dumps(manifest_dict.get('props_in_use', []), ensure_ascii=False)}",
                "summary": f"第{curr_ep}集视听资源引单",
                "keywords": [f"第{curr_ep}集", "视听资源引单", "资产校验"],
                "memory_type": "visual_manifest",
                "source_type": "stage6_manifest",
                "source_id": f"ep_manifest_{curr_ep}",
            }
        ]
        sync_stage_memories_to_vector_db(db, drama_id, 6, stage6_memories)

    db.execute(
        text("UPDATE dramas SET current_stage = 6, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "now": now},
    )

    # 同步短期记忆
    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": f"第{curr_ep}集视听资源引单已校验",
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
            "current_resource_manifest": _dump_or_dict(manifest) if manifest else {},
        },
        stage_name="stage6_resource_manifest",
    )

    if state.latest_audit:
        persist_audit_report(db, drama_id, 6, state.latest_audit)

    db.commit()
    log.info("【阶段 6 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 7：单帧分镜提示词、运镜与精准 SRT 轴测持久化
# =========================================================================

def persist_stage7(
    db: Session,
    drama_id: int,
    state: IndustrialDramaMasterState,
    episode_num: int | None = None,
) -> None:
    """阶段 7 原子落库：写入 storyboards 表（单帧生图 Prompt、运镜、字幕时间戳、音效 Cues）与 SRT 导出。"""
    curr_ep = episode_num or state.current_visual_episode
    log.info("【阶段 7 落库】开始持久化短剧 [%s] 第 %s 集的单帧分镜镜头与 SRT...", drama_id, curr_ep)
    now = now_iso()

    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": curr_ep},
    )
    if not ep_row:
        log.warning("【阶段 7 落库】未找到第 %s 集，跳过分镜写入", curr_ep)
        return

    episode_id = ep_row["id"]
    storyboards = state.storyboard_executions.get(curr_ep, [])
    srt_export = state.srt_exports.get(curr_ep, "")

    # 更新 episodes 的 srt_export
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    ep_ast["srt_export"] = srt_export
    db.execute(
        text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
        {"id": episode_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
    )

    # 幂等清空旧分镜后重写
    db.execute(text("DELETE FROM storyboards WHERE episode_id = :ep_id"), {"ep_id": episode_id})

    for shot in storyboards:
        lipsync_val = _dump_or_dict(shot.lipsync_dynamics)
        audio_val = shot.audio or {}

        img_prompt = shot.image_prompt or ""
        vid_prompt = shot.video_prompt or ""
        
        if not img_prompt:
            if shot.generation_mode == "first_last_frame" and shot.first_last_config:
                img_prompt = shot.first_last_config.get("first_frame_prompt", "")
                vid_prompt = vid_prompt or shot.first_last_config.get("video_motion_prompt", "")
            elif shot.multi_image_config:
                img_prompt = shot.multi_image_config.get("video_prompt", "")
                vid_prompt = vid_prompt or shot.multi_image_config.get("video_prompt", "")

        shot_result_json = json.dumps({
            "selection_rationale": shot.selection_rationale,
            "first_last_config": shot.first_last_config,
            "multi_image_config": shot.multi_image_config,
            "audio": audio_val,
            "lipsync_dynamics": lipsync_val,
            "srt_timing": shot.srt_timing,
            "dynamic_cue": shot.dynamic_cue,
            "music_cue": shot.music_cue,
            "foley_cue": shot.foley_cue,
        }, ensure_ascii=False)

        db.execute(
            text("""
                INSERT INTO storyboards (
                    episode_id, storyboard_number, duration, shot_type, movement,
                    creation_mode, image_prompt, video_prompt, dialogue, narration,
                    action, atmosphere, result, status, created_at, updated_at
                ) VALUES (
                    :episode_id, :storyboard_number, :duration, :shot_type, :movement,
                    :creation_mode, :image_prompt, :video_prompt, :dialogue, :narration,
                    :action, :atmosphere, :result, 'draft', :now, :now
                )
            """),
            {
                "episode_id": episode_id,
                "storyboard_number": shot.shot_id,
                "duration": shot.duration_sec,
                "shot_type": shot.framing,
                "movement": shot.camera_motion,
                "creation_mode": shot.generation_mode,
                "image_prompt": img_prompt,
                "video_prompt": vid_prompt,
                "dialogue": audio_val.get("dialogue", shot.srt_text or ""),
                "narration": audio_val.get("narration", ""),
                "action": shot.dynamic_cue or "",
                "atmosphere": shot.foley_cue or "",
                "result": shot_result_json,
                "now": now,
            },
        )

    # 长期记忆自动入库与向量化（分镜视听指导与精确SRT）
    if storyboards:
        sb_summary_lines = []
        for s in storyboards[:15]:
            sb_summary_lines.append(f"镜头{s.shot_id} [{s.framing} / {s.camera_motion}]: 画面[{s.image_prompt[:60]}...] 台词[{s.srt_text or ''}]")
        stage7_memories = [
            {
                "title": f"第{curr_ep}集单帧分镜视听指导与精确SRT",
                "content": f"第{curr_ep}集分镜概况(共{len(storyboards)}镜):\n" + "\n".join(sb_summary_lines),
                "summary": f"第{curr_ep}集分镜共{len(storyboards)}镜，已生成精准SRT字幕",
                "keywords": [f"第{curr_ep}集", "分镜提示词", "运镜", "SRT字幕"],
                "memory_type": "storyboard_spec",
                "source_type": "stage7_storyboards",
                "source_id": f"ep_storyboards_{curr_ep}",
            }
        ]
        sync_stage_memories_to_vector_db(db, drama_id, 7, stage7_memories)

    db.execute(
        text("UPDATE dramas SET current_stage = 7, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "now": now},
    )

    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": f"第{curr_ep}集分镜与SRT已完成 (共{len(storyboards)}镜)",
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
            "current_resource_manifest": {"storyboards_count": len(storyboards), "episode_num": curr_ep},
        },
        stage_name="stage7_storyboard_srt",
    )

    if state.latest_audit:
        persist_audit_report(db, drama_id, 7, state.latest_audit)

    db.commit()
    log.info("【阶段 7 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 8：全息声学混音工程持久化
# =========================================================================

def persist_stage8(
    db: Session,
    drama_id: int,
    state: IndustrialDramaMasterState,
    episode_num: int | None = None,
) -> None:
    """阶段 8 原子落库：写入 audio_generations 与 episodes.ast_blocks 的 audio_mastering。"""
    curr_ep = episode_num or state.current_visual_episode
    log.info("【阶段 8 落库】开始持久化短剧 [%s] 第 %s 集的声学混音工程...", drama_id, curr_ep)
    now = now_iso()

    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": curr_ep},
    )
    mastering_plan = state.audio_mastering_plans.get(curr_ep, {})
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

    set_short_memories(
        drama_id,
        {
            "pad_a": state.short_memory_a,
            "pad_b": state.short_memory_b,
            "pad_c": state.short_memory_c,
            "pad_d": f"第{curr_ep}集声学混音工程与母带已落库",
            "inter_episode_physical_snapshot": state.inter_episode_physical_snapshot,
            "current_resource_manifest": {"mastering_status": "completed", "episode_num": curr_ep},
        },
        stage_name="stage8_audio_mastering",
    )

    if state.latest_audit:
        persist_audit_report(db, drama_id, 8, state.latest_audit)

    db.commit()
    log.info("【阶段 8 落库】成功完成并已提交事务。")


# =========================================================================
# 兼容性包装函数与全量加载/持久化门面
# =========================================================================

def persist_first_journey_state(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """持久化第一程全部成果（阶段 1~5），并同步长期与短期工作记忆。"""
    persist_stage1(db, drama_id, state)
    persist_stage2(db, drama_id, state)
    persist_stage3(db, drama_id, state)
    persist_stage4(db, drama_id, state)
    persist_stage5(db, drama_id, state)

    now = now_iso()
    # 状态机锁定控制
    if state.literary_journey_locked or getattr(state, "lock_status", False):
        db.execute(
            text("UPDATE dramas SET lock_status = 1, pipeline_status = 'first_journey_locked', updated_at = :now WHERE id = :id"),
            {"id": drama_id, "now": now},
        )
    db.commit()
    log.info("【第一程落库】全阶段 (1~5) 成果与向量记忆同步已成功完成。")


def persist_second_journey_state(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """持久化第二程全部成果（阶段 6~8）。"""
    curr_ep = state.current_visual_episode
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

    db.execute(
        text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
        {"id": ep_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
    )

    db.execute(text("DELETE FROM storyboards WHERE episode_id = :ep_id"), {"ep_id": ep_id})
    for s_item in storyboards:
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
            shot = StoryboardShot.model_validate(s_dict)
        else:
            shot = s_item

        lipsync_val = _dump_or_dict(shot.lipsync_dynamics)
        audio_val = shot.audio or {}
        img_p = shot.image_prompt or ""
        vid_p = shot.video_prompt or ""
        shot_res = json.dumps({
            "selection_rationale": shot.selection_rationale,
            "first_last_config": shot.first_last_config,
            "multi_image_config": shot.multi_image_config,
            "audio": audio_val,
            "lipsync_dynamics": lipsync_val,
            "srt_timing": shot.srt_timing,
            "dynamic_cue": shot.dynamic_cue,
            "music_cue": shot.music_cue,
            "foley_cue": shot.foley_cue,
        }, ensure_ascii=False)

        db.execute(
            text("""
                INSERT INTO storyboards (
                    episode_id, storyboard_number, duration, shot_type, movement,
                    creation_mode, image_prompt, video_prompt, dialogue, narration,
                    action, atmosphere, result, status, created_at, updated_at
                ) VALUES (
                    :episode_id, :storyboard_number, :duration, :shot_type, :movement,
                    :creation_mode, :image_prompt, :video_prompt, :dialogue, :narration,
                    :action, :atmosphere, :result, 'draft', :now, :now
                )
            """),
            {
                "episode_id": ep_id,
                "storyboard_number": shot.shot_id,
                "duration": shot.duration_sec,
                "shot_type": shot.framing,
                "movement": shot.camera_motion,
                "creation_mode": shot.generation_mode,
                "image_prompt": img_p,
                "video_prompt": vid_p,
                "dialogue": audio_val.get("dialogue", shot.srt_text or ""),
                "narration": audio_val.get("narration", ""),
                "action": shot.dynamic_cue or "",
                "atmosphere": shot.foley_cue or "",
                "result": shot_res,
                "now": now,
            },
        )
    db.commit()


def load_master_state_from_db(db: Session, drama_id: int) -> IndustrialDramaMasterState:
    """从数据库权威实体表和 Redis 短期记忆中加载并重构两程九阶完整状态。"""
    log.info("【状态加载】开始从数据库重构短剧 [%s] 的 MasterState...", drama_id)
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

    state = IndustrialDramaMasterState(
        drama_id=drama_id,
        journey=meta.get("journey") or "journey_1_literary",
        current_stage=meta.get("current_stage") or 1,
        selected_title=drama_row.get("name") or drama_row.get("title") or "未定名短剧",
        candidate_titles=candidate_titles,
        aspect_ratio=drama_row.get("aspect_ratio") or meta.get("aspect_ratio") or "9:16",
        target_duration_sec=float(drama_row.get("target_duration_sec") or meta.get("target_duration_sec") or 120.0),
        genre=drama_row.get("genre") or "剧情",
        visual_style=drama_row.get("style") or meta.get("visual_style") or "真人电影/超写实",
        negative_rules=negative_rules,
        logline=drama_row.get("logline") or meta.get("logline") or drama_row.get("description") or "",
        dramatic_irony=drama_row.get("dramatic_irony") or meta.get("dramatic_irony") or "",
        grand_payoff=drama_row.get("grand_payoff") or meta.get("grand_payoff") or "",
        short_memory_a=meta.get("short_memory_a") or "",
        short_memory_b=meta.get("short_memory_b") or "",
        short_memory_c=meta.get("short_memory_c") or "",
        short_memory_d=meta.get("short_memory_d") or "",
        audio_bible=audio_bible,
        season_outlines=meta.get("season_outlines") or {},
        current_mini_arc_index=meta.get("current_mini_arc_index") or 1,
        total_episodes=drama_row.get("total_episodes") or 12,
        inter_episode_physical_snapshot=meta.get("inter_episode_physical_snapshot"),
        literary_journey_locked=bool(drama_row.get("lock_status", 0) or meta.get("literary_journey_locked", False)),
        visual_audio_assets_registry=meta.get("visual_audio_assets_registry") or {},
        latest_audit=latest_audit,
    )

    # 1. 加载角色 (含 stages 与 views 从表)
    char_rows = fetch_all(db, "SELECT * FROM characters WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC", {"drama_id": drama_id})
    chars = []
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

        chars.append({
            "id": char_id,
            "name": r.get("name"),
            "role_type": r.get("role_type") or r.get("role"),
            "personality": r.get("personality"),
            "appearance": r.get("appearance") or r.get("appearance_features"),
            "identity_anchors": _safe_json_loads(r.get("identity_anchors"), []),
            "voice_style": r.get("voice_style"),
            "biological_dna": status_info.get("biological_dna", {}),
            "lived_in_costume": status_info.get("lived_in_costume", {}),
            "psychological_quad": growth_data.get("psychological_quad", {}),
            "voice_fingerprint": status_info.get("voice_fingerprint", {}),
            "carried_anchor_item": status_info.get("carried_anchor_item", {}),
            "dual_track_relationships": status_info.get("dual_track_relationships", []),
            "emotional_arc_trajectories": growth_data.get("emotional_arc_trajectories", []),
            "stages": st_list,
        })
    if chars:
        state.characters_engine = {"characters": chars}

    # 2. 加载场景与道具 (含从表)
    scene_rows = fetch_all(db, "SELECT * FROM scenes WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC", {"drama_id": drama_id})
    scenes = []
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
        scenes.append({
            "location_name": s.get("name") or s.get("location"),
            "time_and_lighting": s.get("time"),
            "visual_prompt": s.get("prompt"),
            "atmosphere": s.get("atmosphere") or s_extra.get("atmosphere", ""),
            "weathering_layers": s_extra.get("weathering_layers", {}),
            "zones": z_list,
        })

    prop_rows = fetch_all(db, "SELECT * FROM props WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC", {"drama_id": drama_id})
    props = []
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
        props.append({
            "name": p.get("name"),
            "type": p.get("type"),
            "description": p.get("description"),
            "visual_prompt": p.get("prompt"),
            "damage_scale": p_extra.get("damage_scale", ""),
            "foley_resistance": p_extra.get("foley_resistance", ""),
            "damage_states": ds_list,
        })

    if scenes or props:
        state.environments_and_props = {"environments": scenes, "props": props}

    # 3. 加载分集剧本与分镜
    ep_rows = fetch_all(db, "SELECT * FROM episodes WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY episode_number ASC", {"drama_id": drama_id})
    for ep in ep_rows:
        ep_num = ep.get("episode_number")
        ep_id = ep.get("id")
        script_raw = ep.get("script_content")
        if script_raw:
            ep_dict = _safe_json_loads(script_raw, None)
            if isinstance(ep_dict, dict):
                state.completed_screenplays[ep_num] = ep_dict

        ep_ast = _safe_json_loads(ep.get("ast_blocks"), {})
        if ep_ast.get("episode_resource_manifest"):
            try:
                state.episode_manifests[ep_num] = EpisodeResourceManifest.model_validate(ep_ast["episode_resource_manifest"])
            except Exception:
                pass
        if ep_ast.get("srt_export"):
            state.srt_exports[ep_num] = ep_ast["srt_export"]
        if ep_ast.get("audio_mastering"):
            state.audio_mastering_plans[ep_num] = ep_ast["audio_mastering"]

        sb_rows = fetch_all(db, "SELECT * FROM storyboards WHERE episode_id = :epid AND deleted_at IS NULL ORDER BY storyboard_number ASC", {"epid": ep_id})
        if sb_rows:
            shot_list = []
            for sb in sb_rows:
                res = _safe_json_loads(sb.get("result"), {})
                shot = StoryboardShot(
                    shot_id=sb.get("storyboard_number", 1),
                    timecode=sb.get("srt_timing") or sb.get("time") or f"00:00:00,000 --> 00:00:{int(sb.get('duration') or 3):02d},000",
                    duration_sec=float(sb.get("duration") or 3.0),
                    framing=sb.get("shot_type") or "MCU 中近景",
                    camera_motion=sb.get("movement") or "Static",
                    generation_mode=sb.get("creation_mode") or "single_frame_dynamic",
                    image_prompt=sb.get("image_prompt") or "",
                    video_prompt=sb.get("video_prompt") or "",
                    srt_text=sb.get("srt_text") or sb.get("dialogue") or "",
                    srt_timing=sb.get("srt_timing") or "",
                    dynamic_cue=sb.get("dynamic_cue") or res.get("dynamic_cue", ""),
                    music_cue=sb.get("music_cue") or res.get("music_cue", ""),
                    foley_cue=sb.get("foley_cue") or res.get("foley_cue", ""),
                    selection_rationale=res.get("selection_rationale", ""),
                    audio=res.get("audio") or {"dialogue": sb.get("dialogue", ""), "narration": sb.get("narration", "")},
                    lipsync_dynamics=res.get("lipsync_dynamics"),
                )
                shot_list.append(shot)
            state.storyboard_executions[ep_num] = shot_list

    return state


def load_first_journey_state(db: Session, drama_id: int) -> IndustrialDramaMasterState:
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

    sb_rows = fetch_all(
        db,
        "SELECT * FROM storyboards WHERE episode_id = :epid AND deleted_at IS NULL ORDER BY storyboard_number ASC",
        {"epid": ep_id},
    )
    storyboards = []
    for sb in sb_rows:
        res = _safe_json_loads(sb.get("result"), {})
        shot = StoryboardShot(
            shot_id=sb.get("storyboard_number", 1),
            timecode=res.get("srt_timing") or sb.get("time") or f"00:00:00,000 --> 00:00:{int(sb.get('duration') or 3):02d},000",
            duration_sec=float(sb.get("duration") or 3.0),
            framing=sb.get("shot_type") or "MCU 中近景",
            camera_motion=sb.get("movement") or "Static",
            generation_mode=sb.get("creation_mode") or "single_frame_dynamic",
            image_prompt=sb.get("image_prompt") or "",
            video_prompt=sb.get("video_prompt") or "",
            srt_text=res.get("srt_text") or sb.get("dialogue") or "",
            srt_timing=res.get("srt_timing") or "",
            dynamic_cue=res.get("dynamic_cue") or sb.get("action") or "",
            music_cue=res.get("music_cue") or "",
            foley_cue=res.get("foley_cue") or sb.get("atmosphere") or "",
            selection_rationale=res.get("selection_rationale", ""),
            first_last_config=res.get("first_last_config"),
            multi_image_config=res.get("multi_image_config"),
            audio=res.get("audio") or {"dialogue": sb.get("dialogue", ""), "narration": sb.get("narration", "")},
            lipsync_dynamics=res.get("lipsync_dynamics"),
        )
        storyboards.append(shot)

    return {
        "episode_number": episode_num,
        "episode_num": episode_num,
        "manifest": ast.get("episode_resource_manifest"),
        "storyboards": storyboards,
        "srt_export": ast.get("srt_export", ""),
        "audio_mastering": ast.get("audio_mastering", {}),
    }


def _resolve_session_and_args_helper(cls_or_self: Any, *args: Any, **kwargs: Any) -> tuple[Session, list[Any], dict[str, Any]]:
    """统一解析 Session 对象与剩余参数的辅助函数。"""
    arg_list = list(args)
    kw = dict(kwargs)
    db = None

    if hasattr(cls_or_self, "execute") and hasattr(cls_or_self, "commit"):
        db = cls_or_self
    elif getattr(cls_or_self, "db", None) is not None and hasattr(cls_or_self.db, "execute"):
        db = cls_or_self.db
    elif "db" in kw:
        db = kw.pop("db")
    elif "session" in kw:
        db = kw.pop("session")
    elif arg_list and hasattr(arg_list[0], "execute") and hasattr(arg_list[0], "commit"):
        db = arg_list.pop(0)

    # 如果 cls_or_self 既不是 Adapter 也不是 Session，说明是首个业务参数（如 drama_id）
    if not isinstance(cls_or_self, DramaStorageAdapter) and not (hasattr(cls_or_self, "execute") and hasattr(cls_or_self, "commit")):
        arg_list.insert(0, cls_or_self)

    if db is None:
        raise ValueError(f"DramaStorageAdapter 无法识别有效的数据库 Session: cls_or_self={cls_or_self}, args={args}")

    return db, arg_list, kw


class DramaStorageAdapter:
    """两程九阶存储适配器统一门面类，同时支持实例方法与类/静态方法调用。"""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def _resolve_session_and_args(self, *args: Any, **kwargs: Any) -> tuple[Session, list[Any], dict[str, Any]]:
        return _resolve_session_and_args_helper(self, *args, **kwargs)

    @classmethod
    def _extract_drama_id_and_state(cls, args: list[Any], kwargs: dict[str, Any]) -> tuple[int, IndustrialDramaMasterState]:
        drama_id = kwargs.get("drama_id")
        state = kwargs.get("state")
        
        if len(args) == 1:
            if hasattr(args[0], "drama_id"):
                state = args[0]
                drama_id = state.drama_id
            elif isinstance(args[0], int):
                drama_id = args[0]
        elif len(args) >= 2:
            if isinstance(args[0], int):
                drama_id = args[0]
                state = args[1]
            elif hasattr(args[0], "drama_id"):
                state = args[0]
                drama_id = state.drama_id

        if drama_id is None and state and hasattr(state, "drama_id"):
            drama_id = state.drama_id

        if drama_id is None or state is None:
            raise ValueError(f"无法解析 drama_id 或 state 参数 (args={args}, kwargs={kwargs})")

        return int(drama_id), state

    def persist_stage1(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage1(session, drama_id, state)

    def persist_stage2(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage2(session, drama_id, state)

    def persist_stage3(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage3(session, drama_id, state)

    def persist_stage4(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage4(session, drama_id, state)

    def persist_stage5(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage5(session, drama_id, state)

    def persist_stage6(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        episode_num = remaining_kwargs.get("episode_num")
        if len(remaining_args) >= 3 and isinstance(remaining_args[2], int):
            episode_num = remaining_args.pop(2)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage6(session, drama_id, state, episode_num)

    def persist_stage7(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        episode_num = remaining_kwargs.get("episode_num")
        if len(remaining_args) >= 3 and isinstance(remaining_args[2], int):
            episode_num = remaining_args.pop(2)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage7(session, drama_id, state, episode_num)

    def persist_stage8(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        episode_num = remaining_kwargs.get("episode_num")
        if len(remaining_args) >= 3 and isinstance(remaining_args[2], int):
            episode_num = remaining_args.pop(2)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage8(session, drama_id, state, episode_num)

    def persist_literary_journey(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_first_journey_state(session, drama_id, state)

    def persist_visual_journey(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_second_journey_state(session, drama_id, state)

    def persist_first_journey_state(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_first_journey_state(session, drama_id, state)

    def persist_second_journey_state(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_second_journey_state(session, drama_id, state)

    def persist_episode_visual_package(
        cls_or_self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_num = remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        manifest = remaining_kwargs.get("manifest") or (remaining_args[2] if len(remaining_args) > 2 else {})
        storyboards = remaining_kwargs.get("storyboards") or (remaining_args[3] if len(remaining_args) > 3 else None)
        srt_export = remaining_kwargs.get("srt_export") or (remaining_args[4] if len(remaining_args) > 4 else "")
        audio_mastering = remaining_kwargs.get("audio_mastering") or (remaining_args[5] if len(remaining_args) > 5 else None)

        if isinstance(manifest, dict) and storyboards is None:
            pkg = manifest
            m_obj = EpisodeResourceManifest.model_validate(pkg.get("manifest", {}))
            sb_list = pkg.get("storyboards", [])
            srt_str = pkg.get("srt_export", "")
            am_dict = pkg.get("audio_mastering", {})
            persist_episode_visual_package(session, drama_id, episode_num, m_obj, sb_list, srt_str, am_dict)
        else:
            persist_episode_visual_package(session, drama_id, episode_num, manifest, storyboards or [], srt_export, audio_mastering)

    def load_state(cls_or_self, *args: Any, **kwargs: Any) -> IndustrialDramaMasterState:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

    def load_master_state_from_db(cls_or_self, *args: Any, **kwargs: Any) -> IndustrialDramaMasterState:
        """从数据库全量加载两程九阶状态（load_state 别名）。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

    def load_first_journey_state(cls_or_self, *args: Any, **kwargs: Any) -> IndustrialDramaMasterState:
        """加载第一程文学故事工程状态。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_first_journey_state(session, int(drama_id))

    def load_episode_visual_package(cls_or_self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """加载单集视听工程包。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_num = remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        return load_episode_visual_package(session, int(drama_id), int(episode_num))

    def load_visual_package(cls_or_self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """加载单集视听工程包（load_episode_visual_package 别名）。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_num = remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        return load_episode_visual_package(session, int(drama_id), int(episode_num))

