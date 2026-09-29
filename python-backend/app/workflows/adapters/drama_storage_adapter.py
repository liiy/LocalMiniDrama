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
from app.context.short_memory_service import (
    publish_episode_read_projection,
    publish_drama_read_projection,
    publish_drama_event,
    set_short_memories,
    get_short_memories,
)
from app.core.logger import get_logger
from app.db.session import fetch_all, fetch_one
from app.platform_common import now_iso
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
    """安全提取 Pydantic Model 字典或原生 dict，支持嵌套递归转换。"""
    if val is None:
        return {}
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, dict):
        return {k: _dump_or_dict(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_dump_or_dict(x) for x in val]
    return val


def _get_table_columns(db: Session, table_name: str) -> set[str]:
    """安全获取指定表的物理列集合（统一兼容 SQLite 与 MySQL）。"""
    try:
        from sqlalchemy import inspect
        bind = db.get_bind()
        inspector = inspect(bind)
        cols = inspector.get_columns(table_name)
        return {c["name"] for c in cols}
    except Exception:
        try:
            rows = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            return {r[1] for r in rows}
        except Exception:
            return set()


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

def persist_stage2(db: Session, drama_id: int, state: GlobalDramaMasterState | Any) -> None:
    """阶段 2 原子落库：写入 characters 主表、character_relationship 关系表、从表 (character_stages) 及短期记忆 B。
    
    业务逻辑：
    1. 从 state 中智能提取 characters 列表与 character_relationships/relationship_matrix 列表；
    2. 遍历 characters 列表，更新或插入 characters 主表，全量落库 11 个一等公民字段：
       - character_code, name, gender, perceived_age, role, description, personality, appearance,
       - identity_anchors, visual_consistency_code, voice_style, acoustic_persona, psychology_4,
       - voice_fingerprint, carried_anchor_item, drama_engine, growth_chain, current_status；
    3. 遍历 relationship_matrix 列表，写入或更新 character_relationship 关系表：
       - drama_id, character_a_code, character_b_code, surface_relation, emotional_bond,
       - fatal_interest_conflict, shared_history_props, drama_function, information_gap,
       - attitude_arc, swing_point；
    4. 级联写入 character_stages 从表；
    5. 向量化索引多模态角色全息档案与心理四元组；
    6. 更新 dramas 主表 current_stage=2 与 metadata.character_tokens，提交事务。
    """
    log.info("【阶段 2 落库】开始持久化短剧 [%s] 的角色全息资产与双轨关系网...", drama_id)
    now = now_iso()

    # 1. 提取角色列表 (兼容 dict、GlobalDramaMasterState 与 IndustrialDramaState)
    if isinstance(state, dict):
        characters_list = state.get("characters") or []
        if not characters_list and isinstance(state.get("characters_engine"), dict):
            characters_list = state["characters_engine"].get("characters") or []
    elif hasattr(state, "characters") and state.characters:
        characters_list = state.characters
    else:
        ce = getattr(state, "characters_engine", {})
        if isinstance(ce, dict):
            characters_list = ce.get("characters", []) or ce.get("character_profiles", [])
        elif isinstance(ce, list):
            characters_list = ce
        else:
            characters_list = []

    # 2. 提取关系网列表 (兼容 relationship_matrix 与 character_relationships)
    if isinstance(state, dict):
        relationships_list = (
            state.get("character_relationships")
            or state.get("relationship_matrix")
            or state.get("dual_track_relationships")
            or []
        )
        if not relationships_list and isinstance(state.get("characters_engine"), dict):
            ce_dict = state["characters_engine"]
            relationships_list = (
                ce_dict.get("relationship_matrix")
                or ce_dict.get("character_relationships")
                or ce_dict.get("dual_track_relationships")
                or []
            )
    else:
        relationships_list = (
            getattr(state, "character_relationships", None)
            or getattr(state, "relationship_matrix", None)
            or getattr(state, "dual_track_relationships", None)
            or []
        )
        if not relationships_list:
            ce = getattr(state, "characters_engine", {})
            if isinstance(ce, dict):
                relationships_list = (
                    ce.get("relationship_matrix")
                    or ce.get("character_relationships")
                    or ce.get("dual_track_relationships")
                    or []
                )

    log.debug(
        "【阶段 2 落库】已解析待落库数据集: 角色数=%d, 关系对数=%d",
        len(characters_list),
        len(relationships_list),
    )

    # 3. 逐个角色写入或更新 characters 表
    for idx, char_raw in enumerate(characters_list, start=1):
        char = _dump_or_dict(char_raw)
        char_name = str(char.get("name") or "").strip()
        if not char_name:
            log.warning("【阶段 2 落库】第 %d 个角色缺少 name 字段，跳过", idx)
            continue

        char_code = str(char.get("character_code") or char.get("character_id") or f"CHAR_{idx}").strip()
        gender = str(char.get("gender") or char.get("biological_sex") or "male").strip().lower()
        if gender not in ("male", "female", "other"):
            gender = "female" if any(kw in str(char.get("appearance", "")) for kw in ("女", "裙", "发卡")) else "male"

        raw_age = char.get("perceived_age")
        if isinstance(raw_age, (int, float)):
            perceived_age = int(raw_age)
        elif raw_age and str(raw_age).strip().isdigit():
            perceived_age = int(str(raw_age).strip())
        else:
            perceived_age = None

        role = str(char.get("role") or char.get("role_type") or "protagonist").strip()
        description = str(char.get("description") or char.get("personality") or "").strip()
        personality = str(char.get("personality") or "").strip()
        appearance = str(char.get("appearance") or char.get("visual_anchor") or "").strip()
        voice_style = str(char.get("voice_style") or "").strip()

        # 序列化 JSON 字段
        identity_anchors_json = json.dumps(char.get("identity_anchors") or [], ensure_ascii=False)
        visual_consistency_code_json = json.dumps(char.get("visual_consistency_code") or {}, ensure_ascii=False)
        acoustic_persona_json = json.dumps(char.get("acoustic_persona") or {}, ensure_ascii=False)
        psychology_4_json = json.dumps(char.get("psychology_4") or char.get("psychological_quad") or {}, ensure_ascii=False)
        voice_fingerprint_json = json.dumps(char.get("voice_fingerprint") or char.get("linguistic_fingerprint") or {}, ensure_ascii=False)
        carried_anchor_item_json = json.dumps(char.get("carried_anchor_item") or {}, ensure_ascii=False)
        drama_engine_json = json.dumps(char.get("drama_engine") or {}, ensure_ascii=False)

        # 兼容历史 JSON 字段
        growth_chain_json = json.dumps({
            "psychological_quad": char.get("psychological_quad") or char.get("psychology_4") or {},
            "emotional_arc_trajectories": char.get("emotional_arc_trajectories") or [],
            "growth_chain": char.get("growth_chain") or [],
        }, ensure_ascii=False)

        current_status_json = json.dumps({
            "voice_fingerprint": char.get("voice_fingerprint") or {},
            "carried_anchor_item": char.get("carried_anchor_item") or {},
            "biological_dna": char.get("biological_dna") or {},
            "lived_in_costume": char.get("lived_in_costume") or {},
            "dual_track_relationships": char.get("dual_track_relationships") or [],
            "visual_consistency_code": char.get("visual_consistency_code") or {},
            "acoustic_persona": char.get("acoustic_persona") or {},
            "drama_engine": char.get("drama_engine") or {},
        }, ensure_ascii=False)

        # 检查是否已存在 (以 drama_id 与 (character_code 或 name) 联合排重)
        existing_char = fetch_one(
            db,
            "SELECT id FROM characters WHERE drama_id = :drama_id AND (character_code = :code OR name = :name)",
            {"drama_id": drama_id, "code": char_code, "name": char_name},
        )

        if existing_char:
            char_id = existing_char["id"]
            log.debug(
                "【阶段 2 落库】更新现有角色 [ID=%s, 代号=%s, 姓名=%s, 定位=%s]",
                char_id, char_code, char_name, role,
            )
            db.execute(
                text("""
                    UPDATE characters
                    SET character_code = :character_code,
                        gender = :gender,
                        perceived_age = :perceived_age,
                        role = :role,
                        description = :description,
                        personality = :personality,
                        appearance = :appearance,
                        identity_anchors = :identity_anchors,
                        visual_consistency_code = :visual_consistency_code,
                        voice_style = :voice_style,
                        acoustic_persona = :acoustic_persona,
                        psychology_4 = :psychology_4,
                        voice_fingerprint = :voice_fingerprint,
                        carried_anchor_item = :carried_anchor_item,
                        drama_engine = :drama_engine,
                        growth_chain = :growth_chain,
                        current_status = :current_status,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": char_id,
                    "character_code": char_code,
                    "gender": gender,
                    "perceived_age": perceived_age,
                    "role": role,
                    "description": description,
                    "personality": personality,
                    "appearance": appearance,
                    "identity_anchors": identity_anchors_json,
                    "visual_consistency_code": visual_consistency_code_json,
                    "voice_style": voice_style,
                    "acoustic_persona": acoustic_persona_json,
                    "psychology_4": psychology_4_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "carried_anchor_item": carried_anchor_item_json,
                    "drama_engine": drama_engine_json,
                    "growth_chain": growth_chain_json,
                    "current_status": current_status_json,
                    "updated_at": now,
                },
            )
        else:
            log.debug(
                "【阶段 2 落库】新增角色 [代号=%s, 姓名=%s, 定位=%s, 视觉年龄=%s]",
                char_code, char_name, role, perceived_age,
            )
            insert_res = db.execute(
                text("""
                    INSERT INTO characters (
                        drama_id, character_code, name, gender, perceived_age,
                        role, description, personality, appearance,
                        identity_anchors, visual_consistency_code, voice_style,
                        acoustic_persona, psychology_4, voice_fingerprint,
                        carried_anchor_item, drama_engine,
                        growth_chain, current_status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :character_code, :name, :gender, :perceived_age,
                        :role, :description, :personality, :appearance,
                        :identity_anchors, :visual_consistency_code, :voice_style,
                        :acoustic_persona, :psychology_4, :voice_fingerprint,
                        :carried_anchor_item, :drama_engine,
                        :growth_chain, :current_status, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "character_code": char_code,
                    "name": char_name,
                    "gender": gender,
                    "perceived_age": perceived_age,
                    "role": role,
                    "description": description,
                    "personality": personality,
                    "appearance": appearance,
                    "identity_anchors": identity_anchors_json,
                    "visual_consistency_code": visual_consistency_code_json,
                    "voice_style": voice_style,
                    "acoustic_persona": acoustic_persona_json,
                    "psychology_4": psychology_4_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "carried_anchor_item": carried_anchor_item_json,
                    "drama_engine": drama_engine_json,
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

        for s_idx, st_item in enumerate(stages_data, start=1):
            s_name = st_item.get("stage_name", f"阶段_{s_idx}")
            existing_stage = fetch_one(
                db,
                "SELECT id FROM character_stages WHERE character_id = :char_id AND stage_name = :s_name",
                {"char_id": char_id, "s_name": s_name},
            )
            c_palette = st_item.get("color_palette")
            if isinstance(c_palette, (dict, list)):
                c_palette = json.dumps(c_palette, ensure_ascii=False)

            costume_desc = st_item.get("costume_description") or st_item.get("costume_desc", "")
            start_ep = st_item.get("start_episode", s_idx)
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
                db.execute(
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

    # 4. 级联写入人物关系表：character_relationship (双轨对抗与关系矩阵)
    log.debug("【阶段 2 落库】开始持久化短剧 [%s] 的角色双轨关系矩阵，待处理条数: %d", drama_id, len(relationships_list))
    for r_idx, rel_item in enumerate(relationships_list, start=1):
        rel = _dump_or_dict(rel_item)
        char_a_code = str(rel.get("character_a_code") or rel.get("character_a") or "").strip()
        char_b_code = str(rel.get("character_b_code") or rel.get("character_b") or "").strip()
        if not char_a_code or not char_b_code or char_a_code == char_b_code:
            log.debug("【阶段 2 落库】跳过无效或自环关系对: %s <-> %s", char_a_code, char_b_code)
            continue

        social_label = str(rel.get("social_label") or rel.get("surface_relation") or rel.get("surface_identity") or "表层社会关系").strip()
        tension_index = int(rel.get("tension_index") or 50)
        drama_func = str(rel.get("drama_function") or ("catalyst" if r_idx == 1 else "obstacle")).strip()

        shared_props = rel.get("shared_history_props") or rel.get("shared_past_token")
        if isinstance(shared_props, list):
            shared_props_list = [str(p).strip() for p in shared_props if str(p).strip()]
        elif shared_props:
            shared_props_list = [str(shared_props).strip()]
        else:
            shared_props_list = []
        shared_props_json = json.dumps(shared_props_list, ensure_ascii=False)

        raw_gap = rel.get("information_gap")
        if isinstance(raw_gap, dict):
            gap_dict = raw_gap
            gap_json = json.dumps(raw_gap, ensure_ascii=False)
        elif raw_gap:
            gap_dict = {"current_belief": str(raw_gap)}
            gap_json = json.dumps(gap_dict, ensure_ascii=False)
        else:
            gap_dict = {"knows_truth_initially": False, "current_belief": "受表象蒙蔽"}
            gap_json = json.dumps(gap_dict, ensure_ascii=False)

        knows_truth_initially = 1 if gap_dict.get("knows_truth_initially") or rel.get("knows_truth_initially") else 0
        current_belief = str(gap_dict.get("current_belief") or rel.get("current_belief") or "").strip()
        reveal_condition = str(gap_dict.get("reveal_condition") or rel.get("reveal_condition") or "").strip()

        raw_swing = rel.get("swing_point")
        if isinstance(raw_swing, dict):
            swing_dict = raw_swing
            swing_json = json.dumps(raw_swing, ensure_ascii=False)
        else:
            swing_dict = {"can_defect": False, "defect_condition": None}
            swing_json = json.dumps(swing_dict, ensure_ascii=False)

        can_defect = 1 if swing_dict.get("can_defect") or rel.get("can_defect") else 0
        defect_condition = str(swing_dict.get("defect_condition") or rel.get("defect_condition") or "").strip()

        raw_json = json.dumps(rel, ensure_ascii=False)

        existing_rel = fetch_one(
            db,
            "SELECT id FROM character_relationship WHERE drama_id = :drama_id AND character_a_code = :a_code AND character_b_code = :b_code",
            {"drama_id": drama_id, "a_code": char_a_code, "b_code": char_b_code},
        )

        if existing_rel:
            log.debug("【阶段 2 落库】更新现有角色关系对 (ID=%s): %s -> %s", existing_rel["id"], char_a_code, char_b_code)
            db.execute(
                text("""
                    UPDATE character_relationship
                    SET social_label = :social_label,
                        tension_index = :tension_index,
                        drama_function = :drama_function,
                        shared_history_props = :shared_history_props,
                        information_gap = :information_gap,
                        knows_truth_initially = :knows_truth_initially,
                        current_belief = :current_belief,
                        reveal_condition = :reveal_condition,
                        can_defect = :can_defect,
                        defect_condition = :defect_condition,
                        swing_point = :swing_point,
                        raw = :raw,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": existing_rel["id"],
                    "social_label": social_label,
                    "tension_index": tension_index,
                    "drama_function": drama_func,
                    "shared_history_props": shared_props_json,
                    "information_gap": gap_json,
                    "knows_truth_initially": knows_truth_initially,
                    "current_belief": current_belief,
                    "reveal_condition": reveal_condition,
                    "can_defect": can_defect,
                    "defect_condition": defect_condition,
                    "swing_point": swing_json,
                    "raw": raw_json,
                    "updated_at": now,
                },
            )
        else:
            log.debug("【阶段 2 落库】新增角色关系对: %s -> %s", char_a_code, char_b_code)
            db.execute(
                text("""
                    INSERT INTO character_relationship (
                        drama_id, character_a_code, character_b_code,
                        social_label, tension_index, drama_function,
                        shared_history_props, information_gap,
                        knows_truth_initially, current_belief, reveal_condition,
                        can_defect, defect_condition, swing_point, raw,
                        created_at, updated_at
                    ) VALUES (
                        :drama_id, :character_a_code, :character_b_code,
                        :social_label, :tension_index, :drama_function,
                        :shared_history_props, :information_gap,
                        :knows_truth_initially, :current_belief, :reveal_condition,
                        :can_defect, :defect_condition, :swing_point, :raw,
                        :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "character_a_code": char_a_code,
                    "character_b_code": char_b_code,
                    "social_label": social_label,
                    "tension_index": tension_index,
                    "drama_function": drama_func,
                    "shared_history_props": shared_props_json,
                    "information_gap": gap_json,
                    "knows_truth_initially": knows_truth_initially,
                    "current_belief": current_belief,
                    "reveal_condition": reveal_condition,
                    "can_defect": can_defect,
                    "defect_condition": defect_condition,
                    "swing_point": swing_json,
                    "raw": raw_json,
                    "now": now,
                },
            )

    # 5. 长期记忆自动入库与向量化（角色全息档案与心理四元组）
    stage2_memories = []
    for char_item in characters_list:
        char = _dump_or_dict(char_item)
        c_name = char.get("name")
        if not c_name:
            continue
        c_code = char.get("character_code") or char.get("character_id") or ""
        c_role = char.get("role") or char.get("role_type") or "主要角色"
        c_quad = char.get("psychology_4") or char.get("psychological_quad") or {}
        c_arc = char.get("emotional_arc_trajectories") or []
        c_vcc = char.get("visual_consistency_code") or {}
        c_anchor = char.get("carried_anchor_item") or {}
        c_engine = char.get("drama_engine") or {}
        stage2_memories.append({
            "title": f"角色全息档案: {c_name} [{c_code}] ({c_role})",
            "content": (
                f"角色名: {c_name} (代号: {c_code})\n"
                f"角色定位: {c_role}\n"
                f"视觉年龄: {char.get('perceived_age', '未知')}\n"
                f"性格特征: {char.get('personality', '')}\n"
                f"外貌装造锚点: {char.get('appearance') or char.get('lived_in_costume', {})}\n"
                f"锁脸与服饰一致性代码: {json.dumps(c_vcc, ensure_ascii=False)}\n"
                f"随身锚定旧物: {json.dumps(c_anchor, ensure_ascii=False)}\n"
                f"戏剧引擎动力: {json.dumps(c_engine, ensure_ascii=False)}\n"
                f"心理四元组: {json.dumps(c_quad, ensure_ascii=False)}\n"
                f"人物弧光: {json.dumps(c_arc, ensure_ascii=False)}\n"
                f"声纹与行为指纹: {json.dumps(char.get('voice_fingerprint', {}), ensure_ascii=False)}"
            ),
            "summary": f"{c_name} [{c_code}]: {c_role}, {char.get('personality', '')}",
            "keywords": [c_name, c_code, c_role, "人物档案", "角色引擎"],
            "memory_type": "character_profile",
            "source_type": "stage2_character",
            "source_id": f"char_{c_code or c_name}",
        })
    sync_stage_memories_to_vector_db(db, drama_id, 2, stage2_memories)

    # 6. 更新主表状态及元数据命名空间
    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    tokens = getattr(state, "character_tokens", None) if not isinstance(state, dict) else state.get("character_tokens")
    if tokens:
        current_meta["character_tokens"] = tokens
    db.execute(
        text("UPDATE dramas SET current_stage = 2, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    audit = (
        getattr(state, "latest_audit", None)
        or getattr(state, "audit_report", None)
        if not isinstance(state, dict)
        else (state.get("latest_audit") or state.get("audit_report"))
    )
    if audit:
        persist_audit_report(db, drama_id, 2, audit)

    db.commit()
    log.info("【阶段 2 落库】短剧 [%s] 角色全息资产与双轨关系网持久化成功并已提交事务。", drama_id)


# =========================================================================
# 阶段 3：空间三层做旧、场景区域与物证拟音持久化
# =========================================================================

def persist_stage3(db: Session, drama_id: int, state: GlobalDramaMasterState | Any) -> None:
    """阶段 3 原子落库：写入 scenes / scene_zones / scene_weathering_views 及 props / prop_damage_states / prop_detail_views。"""
    log.info("【阶段 3 落库】开始持久化短剧 [%s] 的空间场景与核心道具资产...", drama_id)
    now = now_iso()

    # 1. 场景主表与从表
    ep = getattr(state, "environments_and_props", {})
    if isinstance(ep, dict):
        env_list = ep.get("environments", []) or ep.get("scenes", [])
    elif hasattr(state, "scenes") and isinstance(state.scenes, list):
        env_list = state.scenes
    else:
        env_list = []
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
            "env_id": env.get("env_id", ""),
            "level": env.get("level", ""),
            "costume_resonance_check": env.get("costume_resonance_check", True),
            "three_layer_aging": env.get("three_layer_aging", {}),
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
    if isinstance(ep, dict):
        prop_list = ep.get("props", [])
    elif hasattr(state, "props") and isinstance(state.props, list):
        prop_list = state.props
    else:
        prop_list = []
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

def persist_stage5(db: Session, drama_id: int, state: EpisodeScopedSubState | GlobalDramaMasterState | Any) -> None:
    """阶段 5 原子落库：写入 episodes 正文内容、AST 分块、节奏自检与定稿锁定状态。
    严格遵循单一事实源 (SSOT) 与物理分离原则：
    1. script_content 仅存储纯视听 Markdown 文本，绝不混杂元数据与 JSON 序列化；
    2. ast_blocks 存储语法树及视听节点分块；
    3. physical_snapshot_start / physical_snapshot_end 独立存储上下集时空连续性快照；
    4. audit_verdict / audit_report 独立存储剧本自检与质检合规数据；
    5. outline_id 关联分集大纲表，杜绝在 episodes 表重复存储大纲描述与悬念字段。
    """
    log.info("【阶段 5 落库】开始持久化短剧 [%s] 的文学剧本工笔正文...", drama_id)
    now = now_iso()

    def _state_val(key: str, default: Any = None) -> Any:
        if isinstance(state, dict):
            return state.get(key, default)
        return getattr(state, key, default)

    # 解析剧本字典：兼容 GlobalDramaMasterState, EpisodeScopedSubState 及 dict 结构
    screenplays: dict[int, Any] = {}
    completed_sc = _state_val("completed_screenplays", {}) or {}
    single_sc = _state_val("screenplay", None)
    if completed_sc:
        screenplays = completed_sc
    elif single_sc:
        ep_no = _state_val("episode_number", None) or _state_val("episode_num", 1)
        screenplays = {int(ep_no): single_sc}

    ep_cols = _get_table_columns(db, "episodes")
    has_audit_verdict = "audit_verdict" in ep_cols
    has_audit_report = "audit_report" in ep_cols
    has_snap_start = "physical_snapshot_start" in ep_cols
    has_snap_end = "physical_snapshot_end" in ep_cols
    has_commercial_tag = "commercial_tag" in ep_cols
    has_outline_id = "outline_id" in ep_cols

    stage5_memories = []
    latest_end_snapshot: dict[str, Any] = {}

    for ep_num, ep_data in screenplays.items():
        if hasattr(ep_data, "to_dict"):
            ep_dict = ep_data.to_dict()
        elif hasattr(ep_data, "model_dump"):
            ep_dict = ep_data.model_dump()
        elif isinstance(ep_data, dict):
            ep_dict = ep_data
        else:
            ep_dict = dict(ep_data)

        # 1. 提取纯视听 Markdown 剧本正文（严格解耦，杜绝 JSON 序列化污染文本正文）
        sc_text = (
            ep_dict.get("screenplay_text")
            or ep_dict.get("body_markdown")
            or ep_dict.get("screenplay_content")
            or ep_dict.get("text")
            or ""
        )
        if not sc_text and isinstance(ep_data, str):
            sc_text = ep_data
        # 若 sc_text 意外被传为 JSON 字符串，尝试解析恢复纯文本正文
        if isinstance(sc_text, str) and sc_text.strip().startswith("{") and sc_text.strip().endswith("}"):
            parsed_sc = _safe_json_loads(sc_text, None)
            if isinstance(parsed_sc, dict):
                sc_text = (
                    parsed_sc.get("screenplay_text")
                    or parsed_sc.get("body_markdown")
                    or parsed_sc.get("screenplay_content")
                    or parsed_sc.get("text")
                    or sc_text
                )

        # 2. 提取跨集 0 秒物理咬合快照（时空连续性链条）
        start_snap_raw = (
            ep_dict.get("previous_episode_0s_pickup")
            or ep_dict.get("previous_episode_physical_pickup")
            or ep_dict.get("incoming_physical_snapshot")
            or (getattr(state, "incoming_physical_continuity", None).model_dump() if hasattr(getattr(state, "incoming_physical_continuity", None), "model_dump") else getattr(state, "incoming_physical_continuity", None))
            or {}
        )
        start_snapshot = start_snap_raw if isinstance(start_snap_raw, dict) else _safe_json_loads(start_snap_raw, {})

        end_snap_raw = (
            ep_dict.get("episode_end_physical_delta")
            or ep_dict.get("outgoing_physical_snapshot")
            or ep_dict.get("outgoing_physical_continuity")
            or (getattr(state, "outgoing_physical_continuity", None).model_dump() if hasattr(getattr(state, "outgoing_physical_continuity", None), "model_dump") else getattr(state, "outgoing_physical_continuity", None))
            or {}
        )
        end_snapshot = end_snap_raw if isinstance(end_snap_raw, dict) else _safe_json_loads(end_snap_raw, {})
        if end_snapshot:
            latest_end_snapshot = end_snapshot

        # 3. 提取 AST 结构化块与视听节点（执行 SSOT 数据治理与冗余清洗）
        existing_ep = fetch_one(
            db,
            "SELECT id, outline_id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": ep_num},
        )
        ep_ast = _safe_json_loads(existing_ep.get("ast_blocks") if existing_ep else None, {})
        ep_ast["safety_guardrails_lock"] = ep_dict.get("safety_guardrails_lock", {})
        ep_ast["dramatic_rhythm_check"] = ep_dict.get("dramatic_rhythm_check", {})
        ep_ast["golden_cliffhanger_hook"] = ep_dict.get("golden_cliffhanger_hook", {})
        if ep_dict.get("ast_data"):
            ep_ast["ast_data"] = ep_dict["ast_data"]
        if ep_dict.get("scenes"):
            ep_ast["scenes"] = ep_dict["scenes"]

        # SSOT 治理：清理 ast_blocks 中残留的大纲冗余字段，大纲数据由 episode_outlines 独家纳管
        for outline_redundant_key in ("hook_3s", "three_second_hook", "micro_twist_45s", "micro_turning_point_45s", "cliffhanger_end", "killer_cliffhanger_115s", "raw_outline_card", "subtext_matrix", "dual_helix_task"):
            ep_ast.pop(outline_redundant_key, None)
            if isinstance(ep_ast.get("ast_data"), dict):
                ep_ast["ast_data"].pop(outline_redundant_key, None)

        # SSOT 治理：若 episodes 表具备 physical_snapshot_start / physical_snapshot_end 独立物理列，
        # 则绝不在 ast_blocks 中重复存储快照全量对象，避免存储膨胀与时序不一致；仅在无独立列时作为向后兼容兜底
        if has_snap_start:
            ep_ast.pop("previous_episode_0s_pickup", None)
        else:
            ep_ast["previous_episode_0s_pickup"] = start_snapshot

        if has_snap_end:
            ep_ast.pop("episode_end_physical_delta", None)
        else:
            ep_ast["episode_end_physical_delta"] = end_snapshot

        # 4. 提取质检自审报告与结论
        audit_rep_raw = (
            ep_dict.get("audit_report")
            or (getattr(state, "latest_audit", None).model_dump() if hasattr(getattr(state, "latest_audit", None), "model_dump") else getattr(state, "latest_audit", None))
            or {}
        )
        audit_report = audit_rep_raw if isinstance(audit_rep_raw, dict) else _safe_json_loads(audit_rep_raw, {})
        audit_verdict = ep_dict.get("audit_verdict") or ("passed" if audit_report else "pending")
        if isinstance(audit_report, dict) and audit_report.get("passed") is False:
            audit_verdict = "need_revision"

        # 5. 商业定位标签与集数基本属性
        comm_tag = ep_dict.get("commercial_tag") or ("paywall_climax" if int(ep_num) in [3, 6, 9] else "regular")
        ep_title = ep_dict.get("episode_title") or ep_dict.get("title") or f"第{ep_num}集"
        duration = int(ep_dict.get("planned_duration_sec") or ep_dict.get("duration_seconds") or getattr(state, "target_duration_sec", 120) or 120)

        # 6. 查询并绑定独立创作大纲 outline_id（SSOT原则）
        outline_id = existing_ep.get("outline_id") if existing_ep else None
        if not outline_id and has_outline_id:
            outline_row = fetch_one(
                db,
                "SELECT id FROM episode_outlines WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
                {"drama_id": drama_id, "ep_num": ep_num},
            )
            if outline_row:
                outline_id = outline_row["id"]

        if outline_id:
            log.info("【阶段 5 落库】第 %s 集成功绑定大纲单一事实源 outline_id=%s", ep_num, outline_id)
        else:
            log.warning("【阶段 5 落库】第 %s 集未找到关联的 episode_outlines 记录，outline_id 为空", ep_num)

        # 7. 动态执行 UPDATE 或 INSERT 写入（零冗余：不写入 description / hook_cliffhanger）
        set_clauses = [
            "title = :title",
            "script_content = :script_content",
            "duration = :duration",
            "ast_blocks = :ast_blocks",
            "status = 'script_completed'",
            "updated_at = :updated_at",
        ]
        params: dict[str, Any] = {
            "title": ep_title,
            "script_content": sc_text,
            "duration": duration,
            "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
            "updated_at": now,
        }
        if has_snap_start:
            set_clauses.append("physical_snapshot_start = :physical_snapshot_start")
            params["physical_snapshot_start"] = json.dumps(start_snapshot, ensure_ascii=False)
        if has_snap_end:
            set_clauses.append("physical_snapshot_end = :physical_snapshot_end")
            params["physical_snapshot_end"] = json.dumps(end_snapshot, ensure_ascii=False)
        if has_audit_verdict:
            set_clauses.append("audit_verdict = :audit_verdict")
            params["audit_verdict"] = audit_verdict
        if has_audit_report:
            set_clauses.append("audit_report = :audit_report")
            params["audit_report"] = json.dumps(audit_report, ensure_ascii=False)
        if has_commercial_tag:
            set_clauses.append("commercial_tag = :commercial_tag")
            params["commercial_tag"] = comm_tag
        if has_outline_id and outline_id is not None:
            set_clauses.append("outline_id = :outline_id")
            params["outline_id"] = outline_id

        if existing_ep:
            params["id"] = existing_ep["id"]
            db.execute(
                text(f"UPDATE episodes SET {', '.join(set_clauses)} WHERE id = :id"),
                params,
            )
            log.info(
                "【阶段 5 落库】成功更新第 %s 集剧本 [id=%s, 正文字数=%d, outline_id=%s, 终态快照=%s, 自审结论=%s]",
                ep_num,
                existing_ep["id"],
                len(sc_text),
                outline_id,
                bool(end_snapshot),
                audit_verdict,
            )
        else:
            col_names = ["drama_id", "episode_number", "title", "script_content", "duration", "ast_blocks", "status", "created_at", "updated_at"]
            val_names = [":drama_id", ":ep_num", ":title", ":script_content", ":duration", ":ast_blocks", "'script_completed'", ":now", ":now"]
            insert_params = {
                "drama_id": drama_id,
                "ep_num": ep_num,
                "title": ep_title,
                "script_content": sc_text,
                "duration": duration,
                "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
                "now": now,
            }
            if has_snap_start:
                col_names.append("physical_snapshot_start")
                val_names.append(":physical_snapshot_start")
                insert_params["physical_snapshot_start"] = json.dumps(start_snapshot, ensure_ascii=False)
            if has_snap_end:
                col_names.append("physical_snapshot_end")
                val_names.append(":physical_snapshot_end")
                insert_params["physical_snapshot_end"] = json.dumps(end_snapshot, ensure_ascii=False)
            if has_audit_verdict:
                col_names.append("audit_verdict")
                val_names.append(":audit_verdict")
                insert_params["audit_verdict"] = audit_verdict
            if has_audit_report:
                col_names.append("audit_report")
                val_names.append(":audit_report")
                insert_params["audit_report"] = json.dumps(audit_report, ensure_ascii=False)
            if has_commercial_tag:
                col_names.append("commercial_tag")
                val_names.append(":commercial_tag")
                insert_params["commercial_tag"] = comm_tag
            if has_outline_id and outline_id is not None:
                col_names.append("outline_id")
                val_names.append(":outline_id")
                insert_params["outline_id"] = outline_id

            db.execute(
                text(f"INSERT INTO episodes ({', '.join(col_names)}) VALUES ({', '.join(val_names)})"),
                insert_params,
            )
            log.info(
                "【阶段 5 落库】新建第 %s 集剧本记录 [正文字数=%d, outline_id=%s, 终态快照=%s, 自审结论=%s]",
                ep_num,
                len(sc_text),
                outline_id,
                bool(end_snapshot),
                audit_verdict,
            )

        stage5_memories.append({
            "title": f"第{ep_num}集定稿文学剧本: {ep_title}",
            "content": f"第{ep_num}集剧本文学正文 (节选前1500字):\n{str(sc_text)[:1500]}\n0秒物理接棒: {json.dumps(start_snapshot, ensure_ascii=False)}\n集末物理位移: {json.dumps(end_snapshot, ensure_ascii=False)}",
            "summary": f"第{ep_num}集定稿剧本: {ep_title}",
            "keywords": [f"第{ep_num}集", "文学剧本", ep_title, "定稿剧本"],
            "memory_type": "screenplay",
            "source_type": "stage5_screenplay",
            "source_id": f"ep_screenplay_{ep_num}",
        })

    is_locked = getattr(state, "literary_journey_locked", False)
    lock_val = 1 if is_locked else 0
    p_status = "first_journey_locked" if is_locked else "running"

    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    current_meta["inter_episode_physical_snapshot"] = latest_end_snapshot or getattr(state, "inter_episode_physical_snapshot", {})
    current_meta["literary_journey_locked"] = is_locked
    current_meta["current_mini_arc_index"] = getattr(state, "current_mini_arc_index", 0)
    current_meta["current_stage"] = 5

    # 更新 dramas 主表状态与阶段号为 5
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

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 5, state.latest_audit)

    # 1. 核心架构保障：关系型数据库主事务立即提交（事务隔离），确保阶段 5 数据 100% 持久化成功，绝不受后续非核心外部调用影响
    db.commit()
    log.info("【阶段 5 落库】关系型数据库主事务成功提交 (drama_id=%s, current_stage=5, lock_status=%s)", drama_id, lock_val)

    # 2. CQRS 读模型闭环刷新：立即向 Redis 发布最新全剧投影与 STAGE_PROGRESS 事件，彻底消除前端轮询感知时差
    try:
        completed_ep_nums = sorted(list(screenplays.keys()))
        total_eps = int(_state_val("total_episodes") or len(screenplays) or 1)
        projection_payload = {
            "drama_id": drama_id,
            "current_stage": 5,
            "journey": "journey_1_literary",
            "lock_status": lock_val,
            "pipeline_status": p_status,
            "completed_episodes": completed_ep_nums,
            "total_episodes": total_eps,
            "literary_journey_locked": is_locked,
        }
        publish_drama_read_projection(drama_id, projection_payload)
        publish_drama_event(drama_id, "STAGE_PROGRESS", {
            "stage": 5,
            "stage_name": "文学剧本波次生成",
            "journey": "journey_1_literary",
            "status": "completed" if (len(completed_ep_nums) >= total_eps) else "in_progress",
            "current_stage": 5,
            "completed_screenplays": len(completed_ep_nums),
            "total_episodes": total_eps,
            "lock_status": lock_val,
        })
        log.info("【阶段 5 落库】成功发布 CQRS 读模型投影与 STAGE_PROGRESS 事件 (drama_id=%s, current_stage=5, 进度=%d/%d)", drama_id, len(completed_ep_nums), total_eps)
    except Exception as e:
        log.warning("【阶段 5 落库】发布 CQRS 读模型或事件出现非致命异常 (不影响数据库主记录): %s", e)

    # 3. 外部依赖隔离：长期记忆写入向量数据库（Chroma）采用独立 try-except 保护，若向量库离线/拒绝连接绝不触发事务回滚
    if stage5_memories:
        try:
            log.info("【阶段 5 落库】开始同步 %d 条文学剧本长期记忆至向量数据库...", len(stage5_memories))
            sync_stage_memories_to_vector_db(db, drama_id, 5, stage5_memories)
            log.info("【阶段 5 落库】向量数据库同步成功完成")
        except Exception as e:
            log.warning("【阶段 5 落库】向量数据库同步出现非阻塞异常 (已隔离保护，主数据库持久化不受影响): %s", e)


# =========================================================================
# 阶段 6：单集视听资源引单与资产校验持久化
# =========================================================================

def persist_stage6(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 6 原子落库：写入 episodes.ast_blocks 的 episode_resource_manifest。"""
    curr_ep = episode_num or getattr(state, "episode_number", None) or getattr(state, "episode_num", None) or getattr(state, "current_visual_episode", 1) or 1
    log.info("【阶段 6 落库】开始持久化短剧 [%s] 第 %s 集的视听资源引单...", drama_id, curr_ep)
    now = now_iso()

    manifest = getattr(state, "manifest", None) or getattr(state, "resource_manifest", None)
    if not manifest and hasattr(state, "episode_manifests") and isinstance(state.episode_manifests, dict):
        manifest = state.episode_manifests.get(curr_ep)
    if not manifest and hasattr(state, "episode_resource_manifests") and isinstance(state.episode_resource_manifests, dict):
        manifest = state.episode_resource_manifests.get(curr_ep)
    if not manifest and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
        extra = state.__pydantic_extra__
        m_extra = extra.get("episode_manifests") or extra.get("episode_resource_manifests")
        if isinstance(m_extra, dict):
            manifest = m_extra.get(curr_ep)
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
        chars_summary = manifest_dict.get("characters_in_scene") or manifest_dict.get("characters") or []
        scenes_summary = manifest_dict.get("scenes_in_use") or manifest_dict.get("environments") or []
        props_summary = manifest_dict.get("props_in_use") or manifest_dict.get("props") or []
        stage6_memories = [
            {
                "title": f"第{curr_ep}集视听资源清单与登场资产",
                "content": f"第{curr_ep}集多模态引单:\n登场角色变体: {json.dumps(chars_summary, ensure_ascii=False)}\n发生场景与做旧层: {json.dumps(scenes_summary, ensure_ascii=False)}\n关键叙事道具: {json.dumps(props_summary, ensure_ascii=False)}",
                "summary": f"第{curr_ep}集视听资源引单",
                "keywords": [f"第{curr_ep}集", "视听资源引单", "资产校验"],
                "memory_type": "visual_manifest",
                "source_type": "stage6_manifest",
                "source_id": f"ep_manifest_{curr_ep}",
            }
        ]
        sync_stage_memories_to_vector_db(db, drama_id, 6, stage6_memories)

    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    if getattr(state, "visual_audio_assets_registry", None):
        current_meta["visual_audio_assets_registry"] = _dump_or_dict(state.visual_audio_assets_registry)
    db.execute(
        text("UPDATE dramas SET current_stage = 6, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 6, state.latest_audit)

    db.commit()
    log.info("【阶段 6 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 7：单帧分镜提示词、运镜与精准 SRT 轴测持久化
# =========================================================================

def persist_stage7(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 7 原子落库：写入 storyboards 表（单帧生图 Prompt、运镜、字幕时间戳、音效 Cues）与 SRT 导出。"""
    curr_ep = episode_num or getattr(state, "episode_number", None) or getattr(state, "episode_num", None) or getattr(state, "current_visual_episode", 1) or 1
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
    storyboards: list[Any] = []
    if hasattr(state, "storyboard_shots") and isinstance(state.storyboard_shots, list):
        storyboards = state.storyboard_shots
    elif isinstance(getattr(state, "storyboards", None), list):
        storyboards = state.storyboards
    elif isinstance(getattr(state, "storyboards", None), dict):
        storyboards = state.storyboards.get(curr_ep, [])
    elif hasattr(state, "episode_storyboards") and isinstance(state.episode_storyboards, dict):
        storyboards = state.episode_storyboards.get(curr_ep, [])
    elif hasattr(state, "storyboard_executions") and isinstance(state.storyboard_executions, dict):
        storyboards = state.storyboard_executions.get(curr_ep, [])

    if hasattr(state, "srt_script") and state.srt_script:
        srt_export = state.srt_script
    else:
        srt_export = getattr(state, "srt_exports", {}).get(curr_ep, "")

    # 更新 episodes 的 srt_export 与 mode_b_manifest_check
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    ep_ast["srt_export"] = srt_export
    mode_b_checks = getattr(state, "episode_mode_b_manifest_checks", {}) or getattr(state, "mode_b_manifest_checks", {})
    if mode_b_checks and curr_ep in mode_b_checks:
        ep_ast["mode_b_manifest_check"] = mode_b_checks[curr_ep]
    db.execute(
        text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
        {"id": episode_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
    )

    # 幂等清空旧分镜后重写
    db.execute(text("DELETE FROM storyboards WHERE episode_id = :ep_id"), {"ep_id": episode_id})

    def _s_get(s: Any, key: str, default: Any = None) -> Any:
        if isinstance(s, dict):
            return s.get(key, default)
        return getattr(s, key, default)

    for idx, shot in enumerate(storyboards, start=1):
        lipsync_val = _dump_or_dict(_s_get(shot, "lipsync_dynamics"))
        audio_val = _s_get(shot, "audio") or {}

        img_prompt = _s_get(shot, "image_prompt") or ""
        vid_prompt = _s_get(shot, "video_prompt") or ""
        gen_mode = _s_get(shot, "generation_mode") or _s_get(shot, "creation_mode") or "single_frame"
        first_last_cfg = _s_get(shot, "first_last_config")
        multi_img_cfg = _s_get(shot, "multi_image_config")
        
        if not img_prompt:
            if gen_mode == "first_last_frame" and first_last_cfg:
                img_prompt = first_last_cfg.get("first_frame_prompt", "")
                vid_prompt = vid_prompt or first_last_cfg.get("video_motion_prompt", "")
            elif multi_img_cfg:
                img_prompt = multi_img_cfg.get("video_prompt", "")
                vid_prompt = vid_prompt or multi_img_cfg.get("video_prompt", "")

        shot_result_json = json.dumps({
            "selection_rationale": _s_get(shot, "selection_rationale"),
            "target_engine": _s_get(shot, "target_engine"),
            "rationale": _s_get(shot, "rationale"),
            "first_last_config": first_last_cfg,
            "multi_image_config": multi_img_cfg,
            "audio": audio_val,
            "lipsync_dynamics": lipsync_val,
            "speech_inpoint_sec": _s_get(shot, "speech_inpoint_sec"),
            "contextual_tts_prompt": _s_get(shot, "contextual_tts_prompt"),
            "is_dialogue_complete_in_shot": _s_get(shot, "is_dialogue_complete_in_shot"),
            "srt_timing": _s_get(shot, "srt_timing"),
            "dynamic_cue": _s_get(shot, "dynamic_cue"),
            "music_cue": _s_get(shot, "music_cue"),
            "foley_cue": _s_get(shot, "foley_cue"),
        }, ensure_ascii=False)

        shot_num = _s_get(shot, "shot_id") or _s_get(shot, "storyboard_number") or idx
        shot_dur = float(_s_get(shot, "duration_sec") or _s_get(shot, "duration") or 4.0)
        shot_type = _s_get(shot, "framing") or _s_get(shot, "shot_type") or "CU 特写"
        movement = _s_get(shot, "camera_motion") or _s_get(shot, "movement") or "推镜"
        dialogue = audio_val.get("dialogue", _s_get(shot, "dialogue") or _s_get(shot, "srt_text") or "")
        narration = audio_val.get("narration", _s_get(shot, "narration") or "")
        action = _s_get(shot, "dynamic_cue") or _s_get(shot, "action") or ""
        atmosphere = _s_get(shot, "foley_cue") or _s_get(shot, "atmosphere") or ""

        db.execute(
            text("""
                INSERT INTO storyboards (
                    episode_id, storyboard_number, duration, shot_type, movement,
                    creation_mode, image_prompt, video_prompt, dialogue, narration,
                    action, atmosphere, result, status, created_at, updated_at
                ) VALUES (
                    :episode_id, :storyboard_number, :duration, :shot_type, :movement,
                    :creation_mode, :image_prompt, :video_prompt, :dialogue, :narration,
                    :action, :atmosphere, :result, 'draft', :created_at, :updated_at
                )
            """),
            {
                "episode_id": episode_id,
                "storyboard_number": shot_num,
                "duration": shot_dur,
                "shot_type": shot_type,
                "movement": movement,
                "creation_mode": gen_mode,
                "image_prompt": img_prompt,
                "video_prompt": vid_prompt,
                "dialogue": dialogue,
                "narration": narration,
                "action": action,
                "atmosphere": atmosphere,
                "result": shot_result_json,
                "created_at": str(now),
                "updated_at": str(now),
            },
        )

    # 长期记忆自动入库与向量化（分镜视听指导与精确SRT）
    if storyboards:
        sb_summary_lines = []
        for s in storyboards[:15]:
            s_num = _s_get(s, "shot_id") or _s_get(s, "storyboard_number") or ""
            s_frame = _s_get(s, "framing") or _s_get(s, "shot_type") or ""
            s_motion = _s_get(s, "camera_motion") or _s_get(s, "movement") or ""
            s_prompt = str(_s_get(s, "image_prompt") or "")[:60]
            s_srt = _s_get(s, "srt_text") or _s_get(s, "dialogue") or ""
            sb_summary_lines.append(f"镜头{s_num} [{s_frame} / {s_motion}]: 画面[{s_prompt}...] 台词[{s_srt}]")
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

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 7, state.latest_audit)

    db.commit()
    log.info("【阶段 7 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 8：全息声学混音工程持久化
# =========================================================================

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
            "target_engine": shot.target_engine,
            "rationale": shot.rationale,
            "first_last_config": shot.first_last_config,
            "multi_image_config": shot.multi_image_config,
            "audio": audio_val,
            "lipsync_dynamics": lipsync_val,
            "speech_inpoint_sec": shot.speech_inpoint_sec,
            "contextual_tts_prompt": shot.contextual_tts_prompt,
            "is_dialogue_complete_in_shot": shot.is_dialogue_complete_in_shot,
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

        if script_raw:
            ep_dict = None
            trimmed_raw = script_raw.strip()
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
                    "title": ep.get("title") or f"第{ep_num}集",
                    "screenplay_text": script_raw,
                    "body_markdown": script_raw,
                    "planned_duration_sec": float(ep.get("duration") or 120.0),
                    "commercial_tag": ep.get("commercial_tag") or "regular",
                    "previous_episode_0s_pickup": start_snap,
                    "episode_end_physical_delta": end_snap,
                    "outgoing_physical_snapshot": end_snap,
                    "audit_report": audit_rep,
                    "ast_data": ep_ast.get("ast_data"),
                }
                try:
                    state.completed_screenplays[ep_num] = LiteraryScreenplayEpisodeModel.model_validate(screenplay_dict).model_dump()
                except Exception:
                    state.completed_screenplays[ep_num] = screenplay_dict

        ep_ast = _safe_json_loads(ep.get("ast_blocks"), {})
        if ep_ast.get("episode_resource_manifest"):
            try:
                state.episode_manifests[ep_num] = EpisodeResourceManifest.model_validate(ep_ast["episode_resource_manifest"])
            except Exception:
                pass
        if ep_ast.get("srt_export"):
            state.srt_exports[ep_num] = ep_ast["srt_export"]
        if ep_ast.get("mode_b_manifest_check"):
            state.episode_mode_b_manifest_checks[ep_num] = ep_ast["mode_b_manifest_check"]
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
                    target_engine=res.get("target_engine", "wan3.0"),
                    rationale=res.get("rationale", ""),
                    first_last_config=res.get("first_last_config"),
                    multi_image_config=res.get("multi_image_config"),
                    audio=res.get("audio") or {"dialogue": sb.get("dialogue", ""), "narration": sb.get("narration", "")},
                    lipsync_dynamics=res.get("lipsync_dynamics"),
                    speech_inpoint_sec=res.get("speech_inpoint_sec"),
                    contextual_tts_prompt=res.get("contextual_tts_prompt"),
                    is_dialogue_complete_in_shot=res.get("is_dialogue_complete_in_shot", True),
                )
                shot_list.append(shot)
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
            target_engine=res.get("target_engine", "wan3.0"),
            rationale=res.get("rationale", ""),
            first_last_config=res.get("first_last_config"),
            multi_image_config=res.get("multi_image_config"),
            audio=res.get("audio") or {"dialogue": sb.get("dialogue", ""), "narration": sb.get("narration", "")},
            lipsync_dynamics=res.get("lipsync_dynamics"),
            speech_inpoint_sec=res.get("speech_inpoint_sec"),
            contextual_tts_prompt=res.get("contextual_tts_prompt"),
            is_dialogue_complete_in_shot=res.get("is_dialogue_complete_in_shot", True),
        )
        storyboards.append(shot)

    return {
        "episode_number": episode_num,
        "episode_num": episode_num,
        "manifest": ast.get("episode_resource_manifest"),
        "storyboards": storyboards,
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
            character_id=str(c["id"]),
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
            scene_id=str(s["id"]),
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
            prop_id=str(p["id"]),
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

    sb_rows = fetch_all(
        db,
        "SELECT * FROM storyboards WHERE episode_id = :epid AND deleted_at IS NULL ORDER BY storyboard_number ASC",
        {"epid": ep_id},
    )
    storyboard_stubs: list[StoryboardShotStub] = []
    for sb in sb_rows:
        res = _safe_json_loads(sb.get("result"), {})
        storyboard_stubs.append(
            StoryboardShotStub(
                shot_id=sb.get("storyboard_number", 1),
                shot_number=sb.get("storyboard_number", 1),
                visual_description=sb.get("image_prompt") or sb.get("action") or "",
                duration_sec=float(sb.get("duration") or 3.0),
                framing=sb.get("shot_type") or "MCU",
                camera_motion=sb.get("movement") or "Static",
                generation_mode=sb.get("creation_mode") or "single_frame_dynamic",
                keyframe_image_ref=res.get("image_ref") or sb.get("image_prompt") or "",
                dialogue_text=sb.get("dialogue") or sb.get("srt_text") or "",
            )
        )

    # 6. 推断当前所处阶段 (Stage 5~8)
    current_stage = 5
    is_completed = False
    if audio_mastering:
        current_stage = 8
        is_completed = True
    elif storyboard_stubs:
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
        storyboard_shots=storyboard_stubs,
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
        len(storyboard_stubs),
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
            or (substate.screenplay if isinstance(substate.screenplay, str) else "")
        )
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

    # 2. 如果存在分镜草稿，同步写入 storyboards 表
    if substate.storyboard_shots:
        db.execute(text("DELETE FROM storyboards WHERE episode_id = :ep_id"), {"ep_id": ep_id})
        for shot in substate.storyboard_shots:
            shot_dict = _dump_or_dict(shot)
            shot_num = int(shot_dict.get("shot_number") or shot_dict.get("shot_id") or 1)
            visual_desc = str(shot_dict.get("visual_description") or shot_dict.get("image_prompt") or shot_dict.get("action") or "")
            framing = str(shot_dict.get("framing") or shot_dict.get("shot_type") or "MCU")
            camera_motion = str(shot_dict.get("camera_motion") or shot_dict.get("movement") or "Static")
            creation_mode = str(shot_dict.get("generation_mode") or shot_dict.get("creation_mode") or "single_frame_dynamic")
            dialogue = str(shot_dict.get("dialogue_text") or shot_dict.get("dialogue") or shot_dict.get("srt_text") or "")
            duration_val = float(shot_dict.get("duration_sec", 3.0) or 3.0)
            res_val = json.dumps(shot_dict, ensure_ascii=False) if isinstance(shot_dict, dict) else str(shot_dict or "{}")

            db.execute(
                text("""
                    INSERT INTO storyboards (
                        episode_id, storyboard_number, duration, shot_type, movement,
                        creation_mode, image_prompt, dialogue, result, status,
                        created_at, updated_at
                    ) VALUES (
                        :episode_id, :sb_num, :duration, :shot_type, :movement,
                        :creation_mode, :image_prompt, :dialogue, :result, 'completed',
                        :created_at, :updated_at
                    )
                """),
                {
                    "episode_id": int(ep_id),
                    "sb_num": shot_num,
                    "duration": duration_val,
                    "shot_type": framing,
                    "movement": camera_motion,
                    "creation_mode": creation_mode,
                    "image_prompt": visual_desc,
                    "dialogue": dialogue,
                    "result": res_val,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    db.commit()

    # 3. 异步发布 CQRS 只读投影至 Redis
    try:
        publish_episode_read_projection(drama_id, ep_num, substate)
    except Exception as e:
        log.warning("【单集切片持久化】刷新 Redis 读投影失败: %s", e)

    log.info("【单集切片持久化】成功提交: drama_id=%s, ep=%s, stage=%s", drama_id, ep_num, substate.current_stage)


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
    def _extract_drama_id_and_state(cls, args: list[Any], kwargs: dict[str, Any]) -> tuple[int, Any]:
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

    def load_state(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

    def load_master_state_from_db(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        """从数据库全量加载全局文学状态（load_state 别名）。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

    def load_first_journey_state(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        """加载第一程文学故事工程状态。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_first_journey_state(session, int(drama_id))

    def load_global_master_state(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        """加载全局文学母状态。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

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

    def load_episode_substate_slice(cls_or_self, *args: Any, **kwargs: Any) -> EpisodeScopedSubState:
        """【懒水合】从数据库毫秒级加载单集独立执行切片。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_number = remaining_kwargs.get("episode_number") or remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        return load_episode_substate_slice(session, int(drama_id), int(episode_number))

    def persist_episode_substate_slice(cls_or_self, *args: Any, **kwargs: Any) -> None:
        """【原子切片持久化】持久化单集独立执行产物并刷新 Redis 只读投影。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id")
        substate = remaining_kwargs.get("substate")
        if len(remaining_args) >= 2:
            drama_id = remaining_args[0]
            substate = remaining_args[1]
        elif len(remaining_args) == 1:
            if hasattr(remaining_args[0], "drama_id"):
                substate = remaining_args[0]
                drama_id = substate.drama_id
        if drama_id is None or substate is None:
            raise ValueError(f"无法解析 drama_id 或 substate 参数 (args={args}, kwargs={kwargs})")
        persist_episode_substate_slice(session, int(drama_id), substate)

