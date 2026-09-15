"""短剧创作工坊两程九阶工业化状态存储适配器 (Drama Storage Adapter)。

严格执行数据库零破坏兼容策略 (Zero-Breaking Schema Policy)：
1. 严禁改动现有物理表结构，严禁添加不存在的列；
2. 现有表字段映射：
   - dramas: metadata (TEXT/LONG_COLUMNS) 承载全局状态与元数据；
   - characters: identity_anchors 存特征词, growth_chain 存心理四元组, current_status 存随身物与声纹；
   - scenes: extra_images (TEXT) 存三层做旧与氛围元数据；
   - props: extra_images (TEXT) 存破损尺度与阻力拟音元数据；
   - episodes: ast_blocks (TEXT) 存安全锁/节奏/物理快照/资源引单/SRT/混音工程，script_content 存剧本正文；
   - storyboards: result (TEXT) 存首尾帧/多图选型、口型动力学与全息声学；
3. 支持 SQLite 与 MySQL 双数据库双向幂等读写。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.db.session import fetch_all, fetch_one
from app.schemas.script_graph_state import (
    AudioBible,
    CandidateTitleMatrix,
    DoubleTrackProhibitions,
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
    RedBlueAuditReport,
    StoryboardShot,
)


def _safe_json_loads(data: Any, default: Any = None) -> Any:
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


def persist_first_journey_state(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """持久化第一程文学故事工程状态至数据库（阶段 1~5 成果落库）。"""
    now_iso = datetime.now(timezone.utc).isoformat()
    drama_row = fetch_one(db, "SELECT * FROM dramas WHERE id = :id", {"id": drama_id})
    if not drama_row:
        raise ValueError(f"Drama with ID {drama_id} does not exist.")

    current_meta = _safe_json_loads(drama_row.get("metadata"), {})
    
    # 阶段 1~5 核心元数据挂载到 dramas.metadata
    current_meta["candidate_titles"] = _dump_or_dict(state.candidate_titles)
    current_meta["negative_rules"] = _dump_or_dict(state.negative_rules)
    current_meta["aspect_ratio"] = state.aspect_ratio
    current_meta["target_duration_sec"] = state.target_duration_sec
    current_meta["logline"] = state.logline
    current_meta["dramatic_irony"] = state.dramatic_irony
    current_meta["grand_payoff"] = state.grand_payoff
    
    # 短期记忆便签
    current_meta["short_memory_a"] = state.short_memory_a
    current_meta["short_memory_b"] = state.short_memory_b
    current_meta["short_memory_c"] = state.short_memory_c
    current_meta["short_memory_d"] = state.short_memory_d
    
    # 阶段 4 音乐动机母库与全季大纲
    current_meta["audio_bible"] = _dump_or_dict(state.audio_bible)
    current_meta["season_outlines"] = state.season_outlines
    
    # 状态机运行位置与门控
    current_meta["current_mini_arc_index"] = state.current_mini_arc_index
    current_meta["inter_episode_physical_snapshot"] = state.inter_episode_physical_snapshot
    current_meta["literary_journey_locked"] = 1 if state.literary_journey_locked else 0
    current_meta["visual_audio_assets_registry"] = state.visual_audio_assets_registry
    current_meta["current_stage"] = state.current_stage
    current_meta["journey"] = state.journey
    current_meta["latest_audit"] = _dump_or_dict(state.latest_audit)

    pipeline_status_sql = ", pipeline_status = 'first_journey_locked'" if state.literary_journey_locked else ""
    db.execute(
        text(f"""
            UPDATE dramas 
            SET title = :title,
                style = :style,
                total_episodes = :total_episodes,
                lock_status = :lock_status,
                metadata = :metadata,
                updated_at = :updated_at{pipeline_status_sql}
            WHERE id = :id
        """),
        {
            "id": drama_id,
            "title": state.selected_title or drama_row.get("title", ""),
            "style": state.visual_style,
            "total_episodes": state.total_episodes,
            "lock_status": 1 if state.literary_journey_locked else 0,
            "metadata": json.dumps(current_meta, ensure_ascii=False),
            "updated_at": now_iso,
        },
    )

    # 阶段 2 人物写入 (利用 growth_chain 存心理四元组，current_status 存随身物与指纹)
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
        growth_chain_json = json.dumps(char.get("psychological_quad", {}), ensure_ascii=False)
        current_status_json = json.dumps({
            "voice_fingerprint": char.get("voice_fingerprint", {}),
            "carried_anchor_item": char.get("carried_anchor_item", {}),
        }, ensure_ascii=False)
        identity_anchors_json = json.dumps(char.get("identity_anchors", []), ensure_ascii=False)

        if existing_char:
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
                    "id": existing_char["id"],
                    "role": char.get("role_type", "protagonist"),
                    "personality": char.get("personality", ""),
                    "appearance": char.get("appearance", ""),
                    "identity_anchors": identity_anchors_json,
                    "voice_style": char.get("voice_style", ""),
                    "growth_chain": growth_chain_json,
                    "current_status": current_status_json,
                    "updated_at": now_iso,
                },
            )
        else:
            db.execute(
                text("""
                    INSERT INTO characters (
                        drama_id, name, role, personality, appearance, identity_anchors,
                        voice_style, growth_chain, current_status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :name, :role, :personality, :appearance, :identity_anchors,
                        :voice_style, :growth_chain, :current_status, :created_at, :updated_at
                    )
                """),
                {
                    "drama_id": drama_id,
                    "name": char_name,
                    "role": char.get("role_type", "protagonist"),
                    "personality": char.get("personality", ""),
                    "appearance": char.get("appearance", ""),
                    "identity_anchors": identity_anchors_json,
                    "voice_style": char.get("voice_style", ""),
                    "growth_chain": growth_chain_json,
                    "current_status": current_status_json,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )

    # 阶段 3 场景写入 (利用 extra_images 存三层做旧与氛围)
    env_list = state.environments_and_props.get("environments", [])
    for env in env_list:
        location = env.get("location_name")
        if not location:
            continue
        existing_scene = fetch_one(
            db,
            "SELECT id FROM scenes WHERE drama_id = :drama_id AND location = :location",
            {"drama_id": drama_id, "location": location},
        )
        scene_extra = json.dumps({
            "weathering_layers": env.get("weathering_layers", {}),
            "atmosphere": env.get("atmosphere", ""),
        }, ensure_ascii=False)

        if existing_scene:
            db.execute(
                text("""
                    UPDATE scenes
                    SET prompt = :prompt,
                        time = :time,
                        extra_images = :extra_images,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": existing_scene["id"],
                    "prompt": env.get("visual_prompt", ""),
                    "time": env.get("time_and_lighting", ""),
                    "extra_images": scene_extra,
                    "updated_at": now_iso,
                },
            )
        else:
            db.execute(
                text("""
                    INSERT INTO scenes (
                        drama_id, location, time, prompt, extra_images, created_at, updated_at
                    ) VALUES (
                        :drama_id, :location, :time, :prompt, :extra_images, :created_at, :updated_at
                    )
                """),
                {
                    "drama_id": drama_id,
                    "location": location,
                    "time": env.get("time_and_lighting", ""),
                    "prompt": env.get("visual_prompt", ""),
                    "extra_images": scene_extra,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )

    # 阶段 3 道具写入 (利用 extra_images 存破损尺度与阻力拟音)
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
                    "id": existing_prop["id"],
                    "type": prop.get("type", "narrative_reversal"),
                    "description": prop.get("description", ""),
                    "prompt": prop.get("visual_prompt", ""),
                    "extra_images": prop_extra,
                    "updated_at": now_iso,
                },
            )
        else:
            db.execute(
                text("""
                    INSERT INTO props (
                        drama_id, name, type, description, prompt, extra_images, created_at, updated_at
                    ) VALUES (
                        :drama_id, :name, :type, :description, :prompt, :extra_images, :created_at, :updated_at
                    )
                """),
                {
                    "drama_id": drama_id,
                    "name": p_name,
                    "type": prop.get("type", "narrative_reversal"),
                    "description": prop.get("description", ""),
                    "prompt": prop.get("visual_prompt", ""),
                    "extra_images": prop_extra,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )

    # 阶段 5 纯文学剧本分集落库 (利用 ast_blocks 存护栏锁/节奏/快照)
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
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": existing_ep["id"],
                    "title": ep_title,
                    "script_content": script_content_json,
                    "duration": duration,
                    "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
                    "updated_at": now_iso,
                },
            )
        else:
            db.execute(
                text("""
                    INSERT INTO episodes (
                        drama_id, episode_number, title, script_content, duration,
                        ast_blocks, created_at, updated_at
                    ) VALUES (
                        :drama_id, :ep_num, :title, :script_content, :duration,
                        :ast_blocks, :created_at, :updated_at
                    )
                """),
                {
                    "drama_id": drama_id,
                    "ep_num": ep_num,
                    "title": ep_title,
                    "script_content": script_content_json,
                    "duration": duration,
                    "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )

    # 阶段 2/3 资产沉淀到长期记忆库 (memory_items)，用于工笔剧本多轮生成与向量检索
    try:
        from app.context.memory_service import add_memory_item

        # 1. 角色长期记忆
        for char in characters_list:
            c_name = char.get("name")
            if not c_name:
                continue
            existing_mem = fetch_one(
                db,
                "SELECT id FROM memory_items WHERE drama_id = :drama_id AND memory_type = 'character_profile' AND title = :title AND deleted_at IS NULL",
                {"drama_id": drama_id, "title": f"角色档案：{c_name}"},
            )
            content = (
                f"姓名：{c_name}\n"
                f"定位：{char.get('role_type', '')}\n"
                f"性格：{char.get('personality', '')}\n"
                f"外貌：{char.get('appearance', '')}\n"
                f"声线：{char.get('voice_style', '')}\n"
                f"核心目标与身份：{json.dumps(char.get('identity_anchors', {}), ensure_ascii=False)}"
            )
            if existing_mem:
                db.execute(
                    text("""
                        UPDATE memory_items
                        SET content = :content, summary = :summary, keywords = :keywords, updated_at = :updated_at
                        WHERE id = :id
                    """),
                    {
                        "id": existing_mem["id"],
                        "content": content,
                        "summary": char.get("personality", "")[:120],
                        "keywords": json.dumps([c_name, char.get("role_type", "")], ensure_ascii=False),
                        "updated_at": now_iso,
                    },
                )
            else:
                add_memory_item(db, {
                    "drama_id": drama_id,
                    "memory_type": "character_profile",
                    "scope": "drama",
                    "title": f"角色档案：{c_name}",
                    "content": content,
                    "summary": char.get("personality", "")[:120],
                    "keywords": [c_name, char.get("role_type", "")],
                    "source_type": "stage2_character",
                    "source_id": str(char.get("id") or c_name),
                    "metadata": {"identity_anchors": char.get("identity_anchors"), "growth_chain": char.get("growth_chain")},
                })

        # 2. 空间场景世界观与做旧规则
        for env in env_list:
            loc = env.get("location_name")
            if not loc:
                continue
            existing_mem = fetch_one(
                db,
                "SELECT id FROM memory_items WHERE drama_id = :drama_id AND memory_type = 'world_rule' AND title = :title AND deleted_at IS NULL",
                {"drama_id": drama_id, "title": f"空间场景：{loc}"},
            )
            content = (
                f"场景名称：{loc}\n"
                f"时间与光影：{env.get('time_and_lighting', '')}\n"
                f"空间氛围：{env.get('atmosphere', '')}\n"
                f"三层做旧：{json.dumps(env.get('weathering_layers', {}), ensure_ascii=False)}\n"
                f"视觉提示词：{env.get('visual_prompt', '')}"
            )
            if existing_mem:
                db.execute(
                    text("""
                        UPDATE memory_items
                        SET content = :content, summary = :summary, keywords = :keywords, updated_at = :updated_at
                        WHERE id = :id
                    """),
                    {
                        "id": existing_mem["id"],
                        "content": content,
                        "summary": env.get("atmosphere", "")[:120],
                        "keywords": json.dumps([loc], ensure_ascii=False),
                        "updated_at": now_iso,
                    },
                )
            else:
                add_memory_item(db, {
                    "drama_id": drama_id,
                    "memory_type": "world_rule",
                    "scope": "drama",
                    "title": f"空间场景：{loc}",
                    "content": content,
                    "summary": env.get("atmosphere", "")[:120],
                    "keywords": [loc],
                    "source_type": "stage3_scene",
                    "source_id": loc,
                    "metadata": {"weathering_layers": env.get("weathering_layers")},
                })

        # 3. 核心物证与物理反转锚点
        for prop in prop_list:
            p_name = prop.get("name")
            if not p_name:
                continue
            existing_mem = fetch_one(
                db,
                "SELECT id FROM memory_items WHERE drama_id = :drama_id AND memory_type = 'prop_anchor' AND title = :title AND deleted_at IS NULL",
                {"drama_id": drama_id, "title": f"核心物证：{p_name}"},
            )
            content = (
                f"道具名称：{p_name}\n"
                f"类型：{prop.get('type', '')}\n"
                f"描述：{prop.get('description', '')}\n"
                f"物理反转锚点：{prop.get('narrative_reversal_anchor', '')}\n"
                f"视觉提示词：{prop.get('visual_prompt', '')}"
            )
            if existing_mem:
                db.execute(
                    text("""
                        UPDATE memory_items
                        SET content = :content, summary = :summary, keywords = :keywords, updated_at = :updated_at
                        WHERE id = :id
                    """),
                    {
                        "id": existing_mem["id"],
                        "content": content,
                        "summary": (prop.get("narrative_reversal_anchor") or prop.get("description", ""))[:120],
                        "keywords": json.dumps([p_name, prop.get("type", "")], ensure_ascii=False),
                        "updated_at": now_iso,
                    },
                )
            else:
                add_memory_item(db, {
                    "drama_id": drama_id,
                    "memory_type": "prop_anchor",
                    "scope": "drama",
                    "title": f"核心物证：{p_name}",
                    "content": content,
                    "summary": (prop.get("narrative_reversal_anchor") or prop.get("description", ""))[:120],
                    "keywords": [p_name, prop.get("type", "")],
                    "source_type": "stage3_prop",
                    "source_id": p_name,
                    "metadata": {"narrative_reversal_anchor": prop.get("narrative_reversal_anchor")},
                })
    except Exception as err:
        logger.warning("写入 memory_items 长期记忆异常(已安全跳过): %s", err)


def load_first_journey_state(db: Session, drama_id: int) -> IndustrialDramaMasterState:
    """从数据库加载并重构第一程全局状态。"""
    drama_row = fetch_one(db, "SELECT * FROM dramas WHERE id = :id", {"id": drama_id})
    if not drama_row:
        raise ValueError(f"Drama with ID {drama_id} does not exist.")

    meta = _safe_json_loads(drama_row.get("metadata"), {})
    
    # 候选片名与禁令
    candidate_titles_data = meta.get("candidate_titles")
    candidate_titles = CandidateTitleMatrix.model_validate(candidate_titles_data) if candidate_titles_data else CandidateTitleMatrix()
    negative_rules_data = meta.get("negative_rules")
    negative_rules = DoubleTrackProhibitions.model_validate(negative_rules_data) if negative_rules_data else DoubleTrackProhibitions()
    
    # 音频动机母库
    audio_bible_data = meta.get("audio_bible")
    audio_bible = AudioBible.model_validate(audio_bible_data) if audio_bible_data else AudioBible()
    
    # 审查报告
    latest_audit_data = meta.get("latest_audit")
    latest_audit = RedBlueAuditReport.model_validate(latest_audit_data) if latest_audit_data else RedBlueAuditReport()

    state = IndustrialDramaMasterState(
        drama_id=drama_id,
        journey=meta.get("journey") or "journey_1_literary",
        current_stage=meta.get("current_stage") or 1,
        selected_title=drama_row.get("title") or "短剧未命名",
        candidate_titles=candidate_titles,
        aspect_ratio=meta.get("aspect_ratio") or "9:16",
        target_duration_sec=float(meta.get("target_duration_sec") or 120.0),
        visual_style=drama_row.get("style") or meta.get("visual_style") or "真人电影/超写实",
        negative_rules=negative_rules,
        logline=meta.get("logline") or drama_row.get("description") or "",
        dramatic_irony=meta.get("dramatic_irony") or "",
        grand_payoff=meta.get("grand_payoff") or "",
        short_memory_a=meta.get("short_memory_a") or "",
        short_memory_b=meta.get("short_memory_b") or "",
        short_memory_c=meta.get("short_memory_c") or "",
        short_memory_d=meta.get("short_memory_d") or "",
        audio_bible=audio_bible,
        season_outlines=meta.get("season_outlines") or {},
        current_mini_arc_index=meta.get("current_mini_arc_index") or 1,
        total_episodes=drama_row.get("total_episodes") or 12,
        inter_episode_physical_snapshot=meta.get("inter_episode_physical_snapshot"),
        literary_journey_locked=bool(meta.get("literary_journey_locked", False)),
        visual_audio_assets_registry=meta.get("visual_audio_assets_registry") or {},
        latest_audit=latest_audit,
    )

    # 加载角色
    char_rows = fetch_all(db, "SELECT * FROM characters WHERE drama_id = :drama_id ORDER BY id ASC", {"drama_id": drama_id})
    chars = []
    for r in char_rows:
        quad = _safe_json_loads(r.get("growth_chain"), {})
        status_info = _safe_json_loads(r.get("current_status"), {})
        chars.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "role_type": r.get("role"),
            "personality": r.get("personality"),
            "appearance": r.get("appearance"),
            "identity_anchors": _safe_json_loads(r.get("identity_anchors"), []),
            "voice_style": r.get("voice_style"),
            "psychological_quad": quad,
            "voice_fingerprint": status_info.get("voice_fingerprint", {}),
            "carried_anchor_item": status_info.get("carried_anchor_item", {}),
        })
    if chars:
        state.characters_engine = {"characters": chars}

    # 加载场景与道具
    scene_rows = fetch_all(db, "SELECT * FROM scenes WHERE drama_id = :drama_id ORDER BY id ASC", {"drama_id": drama_id})
    prop_rows = fetch_all(db, "SELECT * FROM props WHERE drama_id = :drama_id ORDER BY id ASC", {"drama_id": drama_id})
    scenes = []
    for s in scene_rows:
        s_extra = _safe_json_loads(s.get("extra_images"), {})
        scenes.append({
            "location_name": s.get("location"),
            "time_and_lighting": s.get("time"),
            "visual_prompt": s.get("prompt"),
            "weathering_layers": s_extra.get("weathering_layers", {}),
            "atmosphere": s_extra.get("atmosphere", ""),
        })
    props = []
    for p in prop_rows:
        p_extra = _safe_json_loads(p.get("extra_images"), {})
        props.append({
            "name": p.get("name"),
            "type": p.get("type"),
            "description": p.get("description"),
            "visual_prompt": p.get("prompt"),
            "damage_scale": p_extra.get("damage_scale", ""),
            "foley_resistance": p_extra.get("foley_resistance", ""),
        })
    if scenes or props:
        state.environments_and_props = {"environments": scenes, "props": props}

    # 加载文学剧本
    ep_rows = fetch_all(db, "SELECT * FROM episodes WHERE drama_id = :drama_id ORDER BY episode_number ASC", {"drama_id": drama_id})
    for ep in ep_rows:
        ep_num = ep.get("episode_number")
        script_raw = ep.get("script_content")
        if script_raw:
            ep_dict = _safe_json_loads(script_raw, None)
            if isinstance(ep_dict, dict) and "scenes" in ep_dict:
                state.completed_screenplays[ep_num] = ep_dict

    return state


def persist_episode_visual_package(
    db: Session,
    drama_id: int,
    episode_num: int,
    manifest: EpisodeResourceManifest,
    storyboards: list[StoryboardShot],
    srt_export: str = "",
    audio_mastering: dict[str, Any] | None = None,
) -> None:
    """持久化第二程单集视听工程包（阶段 6~8 成果落库）。"""
    now_iso = datetime.now(timezone.utc).isoformat()
    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": episode_num},
    )
    if not ep_row:
        db.execute(
            text("""
                INSERT INTO episodes (
                    drama_id, episode_number, title, duration, created_at, updated_at
                ) VALUES (
                    :drama_id, :ep_num, :title, 90, :now, :now
                )
            """),
            {
                "drama_id": drama_id,
                "ep_num": episode_num,
                "title": f"第{episode_num}集",
                "now": now_iso,
            },
        )
        ep_row = fetch_one(
            db,
            "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": episode_num},
        )
    if not ep_row:
        raise ValueError(f"Episode {episode_num} in drama {drama_id} does not exist.")

    episode_id = ep_row["id"]
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    ep_ast["episode_resource_manifest"] = _dump_or_dict(manifest)
    ep_ast["srt_export"] = srt_export
    ep_ast["audio_mastering"] = audio_mastering or {}

    db.execute(
        text("""
            UPDATE episodes 
            SET ast_blocks = :ast_blocks, updated_at = :updated_at 
            WHERE id = :id
        """),
        {"id": episode_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "updated_at": now_iso},
    )

    # 分镜全量幂等同步：先删除旧分镜再插入新分镜
    db.execute(text("DELETE FROM storyboards WHERE episode_id = :ep_id"), {"ep_id": episode_id})

    for shot in storyboards:
        img_prompt = ""
        vid_prompt = ""
        if shot.generation_mode == "first_last_frame" and shot.first_last_config:
            img_prompt = shot.first_last_config.get("first_frame_prompt", "")
            vid_prompt = shot.first_last_config.get("video_motion_prompt", "")
        elif shot.generation_mode == "multi_image_reference" and shot.multi_image_config:
            img_prompt = shot.multi_image_config.get("video_prompt", "")
            vid_prompt = shot.multi_image_config.get("video_prompt", "")

        lipsync_val = (
            shot.lipsync_dynamics.model_dump()
            if hasattr(shot.lipsync_dynamics, "model_dump")
            else shot.lipsync_dynamics
        )
        shot_result_json = json.dumps({
            "selection_rationale": shot.selection_rationale,
            "first_last_config": shot.first_last_config,
            "multi_image_config": shot.multi_image_config,
            "audio": shot.audio,
            "lipsync_dynamics": lipsync_val,
        }, ensure_ascii=False)

        db.execute(
            text("""
                INSERT INTO storyboards (
                    episode_id, storyboard_number, duration, shot_type, movement,
                    creation_mode, image_prompt, video_prompt, dialogue, narration,
                    result, status, created_at, updated_at
                ) VALUES (
                    :episode_id, :storyboard_number, :duration, :shot_type, :movement,
                    :creation_mode, :image_prompt, :video_prompt, :dialogue, :narration,
                    :result, 'draft', :created_at, :updated_at
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
                "dialogue": shot.audio.get("dialogue", ""),
                "narration": shot.audio.get("narration", ""),
                "result": shot_result_json,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )


def load_episode_visual_package(db: Session, drama_id: int, episode_num: int) -> dict[str, Any]:
    """读取并重构单集视听工程包。"""
    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": episode_num},
    )
    if not ep_row:
        raise ValueError(f"Episode {episode_num} in drama {drama_id} does not exist.")

    episode_id = ep_row["id"]
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    
    manifest_raw = ep_ast.get("episode_resource_manifest", {})
    manifest = EpisodeResourceManifest.model_validate(manifest_raw) if manifest_raw else EpisodeResourceManifest()
    srt_export = ep_ast.get("srt_export", "")
    audio_mastering = ep_ast.get("audio_mastering", {})

    sb_rows = fetch_all(
        db,
        "SELECT * FROM storyboards WHERE episode_id = :ep_id ORDER BY storyboard_number ASC",
        {"ep_id": episode_id},
    )
    storyboards: list[StoryboardShot] = []
    for sb in sb_rows:
        res = _safe_json_loads(sb.get("result"), {})
        shot = StoryboardShot(
            shot_id=sb.get("storyboard_number", 1),
            timecode=sb.get("time") or f"00:00:00,000 --> 00:00:{int(sb.get('duration') or 3):02d},000",
            duration_sec=float(sb.get("duration") or 3.0),
            framing=sb.get("shot_type") or "MCU 中近景",
            camera_motion=sb.get("movement") or "Static",
            generation_mode=sb.get("creation_mode") or "first_last_frame",
            selection_rationale=res.get("selection_rationale", ""),
            first_last_config=res.get("first_last_config"),
            multi_image_config=res.get("multi_image_config"),
            audio=res.get("audio") or {"dialogue": sb.get("dialogue", ""), "narration": sb.get("narration", "")},
            lipsync_dynamics=res.get("lipsync_dynamics"),
        )
        storyboards.append(shot)

    return {
        "episode_id": episode_id,
        "episode_number": episode_num,
        "episode_num": episode_num,
        "manifest": manifest,
        "storyboards": storyboards,
        "srt_export": srt_export,
        "audio_mastering": audio_mastering,
    }


def persist_second_journey_state(db: Session, drama_id: int, state: IndustrialDramaMasterState) -> None:
    """持久化第二程视听分镜工程状态至数据库（阶段 6~8 成果落库）。"""
    persist_first_journey_state(db, drama_id, state)
    curr_ep = state.current_visual_episode
    if curr_ep in state.episode_manifests and curr_ep in state.storyboard_executions:
        manifest = state.episode_manifests[curr_ep]
        storyboards = state.storyboard_executions[curr_ep]
        srt_export = state.srt_exports.get(curr_ep, "")
        audio_mastering = state.audio_mastering_plans.get(curr_ep, {})
        persist_episode_visual_package(
            db,
            drama_id=drama_id,
            episode_num=curr_ep,
            manifest=manifest,
            storyboards=storyboards,
            srt_export=srt_export,
            audio_mastering=audio_mastering,
        )


def load_master_state_from_db(db: Session, drama_id: int) -> IndustrialDramaMasterState:
    """从数据库加载两程九阶完整状态。"""
    state = load_first_journey_state(db, drama_id)
    ep_rows = fetch_all(db, "SELECT episode_number FROM episodes WHERE drama_id = :did AND deleted_at IS NULL", {"did": drama_id})
    for r in ep_rows:
        ep_num = r.get("episode_number")
        if ep_num:
            try:
                pkg = load_episode_visual_package(db, drama_id, ep_num)
                if pkg.get("storyboards"):
                    state.storyboard_executions[ep_num] = pkg["storyboards"]
                if pkg.get("manifest") and (pkg["manifest"].approved_character_ids or pkg["manifest"].approved_scene_ids):
                    state.episode_manifests[ep_num] = pkg["manifest"]
                if pkg.get("srt_export"):
                    state.srt_exports[ep_num] = pkg["srt_export"]
                if pkg.get("audio_mastering"):
                    state.audio_mastering_plans[ep_num] = pkg["audio_mastering"]
            except Exception:
                pass
    return state


class DramaStorageAdapter:
    """两程九阶存储适配器门面类，同时支持依赖注入实例模式与静态门面模式。"""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db
        # 绑定实例级别的单集视听包落库方法，优先于类级 staticmethod
        self.persist_episode_visual_package = self._inst_persist_episode_visual_package

    def persist_first_journey_state(self, drama_id: int, state: IndustrialDramaMasterState) -> None:
        persist_first_journey_state(self.db, drama_id, state)

    def load_first_journey_state(self, drama_id: int) -> IndustrialDramaMasterState:
        return load_first_journey_state(self.db, drama_id)

    def _inst_persist_episode_visual_package(
        self,
        drama_id: int,
        episode_num: int,
        manifest_or_pkg: Any,
        storyboards: list[Any] | None = None,
        srt_export: str = "",
        audio_mastering: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(manifest_or_pkg, dict) and storyboards is None:
            pkg = manifest_or_pkg
            raw_manifest = pkg.get("manifest", {})
            if isinstance(raw_manifest, dict):
                manifest = EpisodeResourceManifest.model_validate(raw_manifest)
            else:
                manifest = raw_manifest
            raw_sbs = pkg.get("storyboards", [])
            sb_list: list[StoryboardShot] = []
            for s in raw_sbs:
                if isinstance(s, dict):
                    sb_list.append(StoryboardShot.model_validate(s))
                else:
                    sb_list.append(s)
            srt_exp = pkg.get("srt_export", "")
            mastering = pkg.get("audio_mastering", {})
            persist_episode_visual_package(
                self.db,
                drama_id=drama_id,
                episode_num=episode_num,
                manifest=manifest,
                storyboards=sb_list,
                srt_export=srt_exp,
                audio_mastering=mastering,
            )
        else:
            persist_episode_visual_package(
                self.db,
                drama_id=drama_id,
                episode_num=episode_num,
                manifest=manifest_or_pkg,
                storyboards=storyboards or [],
                srt_export=srt_export,
                audio_mastering=audio_mastering,
            )

    def load_episode_visual_package(self, drama_id: int, episode_num: int) -> dict[str, Any]:
        return load_episode_visual_package(self.db, drama_id, episode_num)

    def load_master_state_from_db(self, drama_id: int) -> IndustrialDramaMasterState:
        return load_master_state_from_db(self.db, drama_id)

    @staticmethod
    def persist_literary_journey(db: Session, state: IndustrialDramaMasterState) -> None:
        """持久化第一程文学故事工程状态。"""
        persist_first_journey_state(db, state.drama_id, state)

    @staticmethod
    def persist_visual_journey(db: Session, state: IndustrialDramaMasterState) -> None:
        """持久化第二程视听分镜工程状态。"""
        persist_second_journey_state(db, state.drama_id, state)

    @staticmethod
    def persist_episode_visual_package(
        db: Session,
        drama_id: int,
        episode_num: int,
        manifest: EpisodeResourceManifest,
        storyboards: list[StoryboardShot],
        srt_export: str = "",
        audio_mastering: dict[str, Any] | None = None,
    ) -> None:
        """持久化单集视听分镜工程包。"""
        persist_episode_visual_package(
            db,
            drama_id=drama_id,
            episode_num=episode_num,
            manifest=manifest,
            storyboards=storyboards,
            srt_export=srt_export,
            audio_mastering=audio_mastering,
        )

    @staticmethod
    def load_state(db: Session, drama_id: int) -> IndustrialDramaMasterState:
        """加载短剧全息工业状态。"""
        return load_master_state_from_db(db, drama_id)

    @staticmethod
    def load_visual_package(db: Session, drama_id: int, episode_num: int) -> dict[str, Any]:
        """加载单集视听工程包。"""
        return load_episode_visual_package(db, drama_id, episode_num)

