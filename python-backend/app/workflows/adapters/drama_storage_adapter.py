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

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

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
from app.tools.screenplay_feature_scanner import is_valid_character_speaker
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


def _ensure_valid_json_str(
    val: Any,
    default_json: str = "{}",
    wrap_key: str | None = None,
) -> str:
    """确保输出的字符串是 100% 合法的 MySQL JSON 列文本（杜绝 Error 3140 Invalid JSON text）。"""
    if val is None or val == "":
        return default_json
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, (int, float, bool)):
        if default_json == "[]":
            return json.dumps([val], ensure_ascii=False)
        if wrap_key:
            return json.dumps({wrap_key: val}, ensure_ascii=False)
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return default_json
        try:
            parsed = json.loads(s)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass
        if default_json == "[]":
            items = [x.strip() for x in re.split(r"[|｜,，;；\n]+", s) if x.strip()]
            return json.dumps(items or [s], ensure_ascii=False)
        if wrap_key:
            return json.dumps({wrap_key: s}, ensure_ascii=False)
        return json.dumps({"summary": s}, ensure_ascii=False)
    return default_json


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


def _flatten_asset_collection(raw: Any, default_name_prefix: str = "ASSET") -> list[dict[str, Any]]:
    """递归解构并将可能为分层字典（tier 字典）、映射字典、列表、Pydantic 对象或字符串的资产集合，
    安全规范化为纯 dict 列表。确保下游任何迭代均可安全执行 .get()，彻底杜绝 AttributeError。
    """
    if raw is None:
        return []

    # 若为 Pydantic 模型，先转为原生结构
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "dict"):
        raw = raw.dict()

    results: list[dict[str, Any]] = []

    if isinstance(raw, list):
        for item in raw:
            results.extend(_flatten_asset_collection(item, default_name_prefix))
    elif isinstance(raw, dict):
        # 常见单实体特征字段
        entity_keys = {
            "name", "character_name", "char_name", "character_code", "char_id",
            "scene_name", "location", "location_name", "env_id", "scene_id",
            "prop_name", "item_name", "prop_id",
            "voice_id", "master_voice_id", "timbre", "voice_prompt",
            "asset_id", "visual_prompt", "appearance", "static_asset",
        }
        # 容器键特征 (包含分层 tier 或按类别嵌套的容器)
        container_keys = {
            "tier1_base", "tier2_performance", "tier3_special", "tier_1", "tier_2", "tier_3",
            "tier1_primary", "tier2_transitional", "primary", "transitional",
            "tier1_hero", "tier2_anchor", "tier3_atmospheric", "hero", "anchor", "atmospheric",
            "characters", "environments", "props",
            "characters_in_scene", "scenes_in_use", "props_in_use",
        }

        has_entity_field = any(k in raw for k in entity_keys)
        has_container_field = any(k in raw for k in container_keys)

        if has_container_field:
            # 包含子资产或层级的容器字典，递归解构其所有子项
            for sub_val in raw.values():
                results.extend(_flatten_asset_collection(sub_val, default_name_prefix))
        elif has_entity_field:
            # 单一实体字典
            results.append(raw)
        else:
            # 既没有明确保留字段也没有明确容器字段，可能是一个以 asset_id 为 key 的字典
            is_map_of_dicts = all(isinstance(v, (dict, list)) for v in raw.values()) if raw else False
            if is_map_of_dicts and raw:
                for k, v in raw.items():
                    if isinstance(v, dict):
                        d = dict(v)
                        if "asset_id" not in d and "id" not in d:
                            d["asset_id"] = str(k)
                        results.append(d)
                    else:
                        results.extend(_flatten_asset_collection(v, default_name_prefix))
            else:
                # 保守策略：作为单个字典实体保留
                results.append(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if s:
            results.append({
                "name": s,
                "asset_id": s,
                "character_name": s,
                "character_code": s,
                "location": s,
                "prop_name": s,
                "voice_id": s,
            })
    return results


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

    # 1. 提取角色列表 (兼容 dict、GlobalDramaMasterState 与 IndustrialDramaState，以及 character_dossiers 字典)
    if isinstance(state, dict):
        characters_list = state.get("characters") or []
        if not characters_list and isinstance(state.get("character_dossiers"), dict):
            characters_list = list(state["character_dossiers"].values())
        if not characters_list and isinstance(state.get("characters_engine"), dict):
            characters_list = state["characters_engine"].get("characters") or []
    elif hasattr(state, "characters") and state.characters:
        characters_list = state.characters
    elif hasattr(state, "character_dossiers") and getattr(state, "character_dossiers", None):
        cd = getattr(state, "character_dossiers")
        characters_list = list(cd.values()) if isinstance(cd, dict) else list(cd)
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

        # 序列化 JSON 字段 (确保任何上游传入的纯字符串均安全包装为合法 JSON 文本，杜绝 MySQL Error 3140)
        identity_anchors_json = _ensure_valid_json_str(char.get("identity_anchors"), "[]")
        visual_consistency_code_json = _ensure_valid_json_str(char.get("visual_consistency_code"), "{}", wrap_key="base_face_lock")
        acoustic_persona_json = _ensure_valid_json_str(char.get("acoustic_persona"), "{}", wrap_key="tone")
        psychology_4_json = _ensure_valid_json_str(char.get("psychology_4") or char.get("psychological_quad"), "{}", wrap_key="summary")
        voice_fingerprint_json = _ensure_valid_json_str(char.get("voice_fingerprint") or char.get("linguistic_fingerprint"), "{}", wrap_key="catchphrase")
        carried_anchor_item_json = _ensure_valid_json_str(char.get("carried_anchor_item"), "{}", wrap_key="item_name")
        drama_engine_json = _ensure_valid_json_str(char.get("drama_engine"), "{}", wrap_key="core_motivation")

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

        # 级联写入从表 1.5：character_voice_profiles (阶段 2 初始化 V2 母音卡基线，状态 pending)
        tok = AssetProtocolHelper.normalize_token(char_code or char_name)
        master_v_key = f"VOICE_{tok}_T1_MASTER"
        existing_vp = fetch_one(
            db,
            "SELECT id FROM character_voice_profiles WHERE drama_id = :drama_id AND (character_id = :cid OR master_voice_key = :m_key OR voice_id = :m_key) AND deleted_at IS NULL",
            {"drama_id": drama_id, "cid": char_id, "m_key": master_v_key},
        )
        synth_vp = synthesize_voice_prompt(
            char_name=char_name,
            gender=gender,
            perceived_age=perceived_age,
            role=role,
            personality=personality,
            timbre=voice_style,
            voice_style=voice_style,
            acoustic_persona=_safe_json_loads(acoustic_persona_json, None),
        )
        ap_parsed = _safe_json_loads(acoustic_persona_json, {}) if acoustic_persona_json else {}
        if not isinstance(ap_parsed, dict):
            ap_parsed = {}
        vf_parsed = _safe_json_loads(voice_fingerprint_json, {}) if voice_fingerprint_json else {}
        if not isinstance(vf_parsed, dict):
            vf_parsed = {}
        extracted_vocal_pos = str(ap_parsed.get("vocal_position") or "胸腔与口腔平衡共鸣").strip()
        extracted_vocal_flaws = str(ap_parsed.get("vocal_flaws") or "句尾带真实微弱换气呼吸音").strip()
        catchphrase_str = str(vf_parsed.get("catchphrase") or "").strip()
        defensive_str = str(vf_parsed.get("defensive_phrase") or "").strip()
        if catchphrase_str or defensive_str:
            default_sample_text = f"{catchphrase_str} {defensive_str}".strip()
            if len(default_sample_text) < 20:
                default_sample_text = f"我是{char_name}。{default_sample_text} 有些账，终究要亲手算个清楚。"
        else:
            default_sample_text = f"我是{char_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
        default_provider_vid = "female-yujie" if gender == "female" else "male-qn-qingse"
        default_tw_json = json.dumps([{"voice_id": default_provider_vid, "weight": 100}], ensure_ascii=False)
        default_rules_json = json.dumps({
            "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
            "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
            "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
            "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
            "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
            "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
        }, ensure_ascii=False)
        vp_hash = hashlib.sha256(f"{master_v_key}|{synth_vp}|{default_sample_text}".encode("utf-8")).hexdigest()[:16]
        if not existing_vp:
            db.execute(
                text("""
                    INSERT INTO character_voice_profiles (
                        character_id, drama_id, character_code, character_name,
                        voice_id, master_voice_key, voice_prompt, master_tts_prompt,
                        master_sample_text, script_monologue_source,
                        timbre, timbre_archetype, vocal_position, vocal_flaws,
                        tts_provider, tts_model, provider_voice_id, timber_weights_json,
                        speed_ratio, pitch_ratio, emotion_rules,
                        is_master_card, synthesis_status, semantic_hash,
                        status, created_at, updated_at
                    ) VALUES (
                        :cid, :drama_id, :char_code, :char_name,
                        :m_key, :m_key, :v_prompt, :v_prompt,
                        :sample_text, :sample_text,
                        :timbre, :timbre_archetype, :vocal_position, :vocal_flaws,
                        'minimax', 'speech-02-hd', :provider_vid, :tw_json,
                        1.0, 1.0, :emotion_rules,
                        1, 'pending', :semantic_hash,
                        'active', :now, :now
                    )
                """),
                {
                    "cid": char_id,
                    "drama_id": drama_id,
                    "char_code": char_code,
                    "char_name": char_name,
                    "m_key": master_v_key,
                    "v_prompt": synth_vp,
                    "sample_text": default_sample_text,
                    "timbre": voice_style or "自然原声",
                    "timbre_archetype": voice_style or "沉稳磁性声线",
                    "vocal_position": extracted_vocal_pos,
                    "vocal_flaws": extracted_vocal_flaws,
                    "provider_vid": default_provider_vid,
                    "tw_json": default_tw_json,
                    "emotion_rules": default_rules_json,
                    "semantic_hash": vp_hash,
                    "now": now,
                },
            )
            log.debug("【阶段 2 落库】[DEBUG 音色卡基线] 已为角色 [%s(%s)] 初始化 V2 母音卡: %s", char_name, char_code, master_v_key)

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
            if not existing_dv:
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
                            0, 1, 0, :now, :now
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
        if not sc_text and ep_dict.get("scenes"):
            # 兼容场景结构：从场景序列合成基础视听 Markdown 剧本正文
            scene_blocks = []
            for sc in ep_dict["scenes"]:
                if isinstance(sc, dict):
                    loc = sc.get("location") or ""
                    idx = sc.get("scene_index", 1)
                    scene_blocks.append(f"### 场景 {idx}: {loc}".strip())
                    for act in sc.get("action_and_dialogue") or []:
                        scene_blocks.append(str(act))
            sc_text = "\n\n".join(scene_blocks)
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
            "script_content = :script_content",
            "duration = :duration",
            "ast_blocks = :ast_blocks",
            "status = 'script_completed'",
            "updated_at = :updated_at",
        ]
        params: dict[str, Any] = {
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
# 阶段 6 角色领域三层模型清洗与切片推断辅助函数
# =========================================================================

def clean_character_name(raw_name: str) -> str:
    """从原始角色名或切片描述名中剥离括号形态标注及常见切片后缀，还原自然人本名。
    例如:
      '沈炼(全身定妆照)' -> '沈炼'
      '沈炼（飞鱼服）' -> '沈炼'
      '沈炼[四阿哥常服]' -> '沈炼'
      '沈炼(0号肖像)' -> '沈炼'
      '沈炼_特写' -> '沈炼'
    """
    if not raw_name:
        return ""
    # 1. 剔除括号及其内部说明 (支持中英文括号、中括号)
    name = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", raw_name).strip()
    # 2. 剥离常见切片下划线/破折号后缀
    name = re.sub(r"[_—\-](全身|肖像|特写|四视图|三视图|手部|面部|常服|战损).*$", "", name).strip()
    return name if name else raw_name.strip()


def extract_character_tokens(asset_or_char_id: str) -> tuple[str, str, str]:
    """从四段式或多段式/两段式 asset_key / char_id 中解析出: (角色Code, 阶段Token, 切片Token)。
    标准模式: CHAR_<CODE>_<STAGE>_<VIEW>
    支持复合多段角色名（如 CHAR_ZHOU_LAO_SI_T1_PORTRAIT，避免被简单按首个下划线截断为 ZHOU）。
    例如:
      CHAR_SHENLIAN_T1_FULL_BODY -> ('SHENLIAN', 'T1', 'FULL_BODY')
      CHAR_ZHOU_LAO_SI_T1_PORTRAIT -> ('ZHOU_LAO_SI', 'T1', 'PORTRAIT')
      CHAR_ZHOU_LAO_SI_T1 -> ('ZHOU_LAO_SI', 'T1', '')
      CHAR_ZHOU_LAO_SI -> ('ZHOU_LAO_SI', '', '')
      CHAR_SHENLIAN -> ('SHENLIAN', '', '')
    """
    if not asset_or_char_id or not str(asset_or_char_id).startswith("CHAR_"):
        return ("", "", "")
    raw_str = str(asset_or_char_id).strip()
    parts = raw_str.split("_")
    # parts: ['CHAR', ...]
    if len(parts) < 2:
        return ("", "", "")

    # 策略 1: 优先寻找形态阶段锚点 (例如 T1, T2, S1, S2, Z1, BASE, DEFAULT, ORIGIN)
    # 形态锚点一般出现在角色代号之后，前面至少需要有角色代号段 (即 i >= 2)
    stage_idx = -1
    for i in range(2, len(parts)):
        segment = parts[i].upper()
        if re.match(r"^[TSZ]\d+$", segment, re.IGNORECASE) or segment in ("BASE", "DEFAULT", "ORIGIN"):
            stage_idx = i
            break

    if stage_idx != -1:
        # 成功通过阶段标记锚定边界
        code = "_".join(parts[1:stage_idx]).upper()
        stage_token = parts[stage_idx].upper()
        view_token = "_".join(parts[stage_idx + 1:]).upper() if stage_idx + 1 < len(parts) else ""
        log.debug(
            "【阶段 6 角色令牌解析·阶段锚点模式】输入=%s -> 角色代号=%s, 形态阶段=%s, 视图切片=%s",
            raw_str, code, stage_token, view_token
        )
        return (code, stage_token, view_token)

    # 策略 2: 若未找到显式 T1/T2 形态锚点，通过常见视图切片关键词从后向前反向识别边界
    known_view_keywords = {
        "PORTRAIT", "BASE_PORTRAIT", "MAIN_PORTRAIT", "FULL_BODY", "FULLBODY",
        "BASE_COSTUME", "FRONT", "SIDE", "BACK", "THREE_QUARTER", "4V_FRONT",
        "4V_SIDE", "4V_BACK", "4V_3Q", "MACRO_FACE", "MACRO_HAND", "FACIAL_MACRO",
        "HANDS_DETAIL", "FOUR_VIEW"
    }
    view_start_idx = -1
    for i in range(len(parts) - 1, 1, -1):
        test_view = "_".join(parts[i:]).upper()
        if test_view in known_view_keywords or parts[i].upper() in known_view_keywords:
            view_start_idx = i
            break

    if view_start_idx != -1:
        code = "_".join(parts[1:view_start_idx]).upper()
        stage_token = "T1"  # 默认基准形态
        view_token = "_".join(parts[view_start_idx:]).upper()
        log.debug(
            "【阶段 6 角色令牌解析·视图后缀模式】输入=%s -> 角色代号=%s, 默认形态=%s, 视图切片=%s",
            raw_str, code, stage_token, view_token
        )
        return (code, stage_token, view_token)

    # 策略 3: 若均无形态与视图段，整体作为纯角色代号 (例如 CHAR_ZHOU_LAO_SI 或 CHAR_SHENLIAN)
    code = "_".join(parts[1:]).upper()
    log.debug(
        "【阶段 6 角色令牌解析·纯角色代号模式】输入=%s -> 角色代号=%s (无形态与视图后缀)",
        raw_str, code
    )
    return (code, "", "")


def find_canonical_entity(
    query_key: str,
    canonical_map: dict[str, dict[str, Any]],
    canonical_by_name: dict[str, dict[str, Any]],
    canonical_by_code: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """在规范化实体集合中按多维凭证高精度检索角色实体 (Tier 1 Entity)。
    支持通过: 中文名、清洗后中文名、小写名、带 CHAR_ 代号、去 CHAR_ 代号、归一化 Token 等任意维度检索。
    """
    if not query_key:
        return None
    q = str(query_key).strip()

    # 1. 尝试原始代码及名称精确检索
    if q in canonical_by_name:
        return canonical_by_name[q]
    if q in canonical_by_code:
        return canonical_by_code[q]

    # 2. 尝试清洗后的中文名检索
    q_clean = clean_character_name(q)
    if q_clean and q_clean in canonical_by_name:
        return canonical_by_name[q_clean]

    # 3. 尝试大小写不敏感的小写名称检索
    q_lower = q.lower()
    if q_lower in canonical_map:
        return canonical_map[q_lower]
    if q_clean and q_clean.lower() in canonical_map:
        return canonical_map[q_clean.lower()]

    # 4. 尝试代号变体检索 (大写、带/不带 CHAR_)
    q_upper = q.upper()
    if q_upper in canonical_by_code:
        return canonical_by_code[q_upper]
    if not q_upper.startswith("CHAR_") and f"CHAR_{q_upper}" in canonical_by_code:
        return canonical_by_code[f"CHAR_{q_upper}"]
    if q_upper.startswith("CHAR_") and q_upper.replace("CHAR_", "", 1) in canonical_by_code:
        return canonical_by_code[q_upper.replace("CHAR_", "", 1)]

    # 5. 尝试归一化 Token 匹配
    norm_tok = AssetProtocolHelper.normalize_token(q)
    if norm_tok in canonical_by_code:
        return canonical_by_code[norm_tok]
    if f"CHAR_{norm_tok}" in canonical_by_code:
        return canonical_by_code[f"CHAR_{norm_tok}"]

    # 6. 从四段式 asset_key 中解析出角色 token 再次检索
    if q_upper.startswith("CHAR_"):
        c_tok, _, _ = extract_character_tokens(q_upper)
        if c_tok and c_tok in canonical_by_code:
            return canonical_by_code[c_tok]
        if c_tok and f"CHAR_{c_tok}" in canonical_by_code:
            return canonical_by_code[f"CHAR_{c_tok}"]

    return None


def parse_character_view_type(token: str, explicit_label: str = "") -> tuple[str, str, int]:
    """根据切片标识符/名称推断标准化切片类型、中文标签与是否主视觉基准:
    返回: (view_type, view_label, is_primary)
    标准 view_type:
      'main_portrait'      (is_primary=1)
      'full_body'          (is_primary=0)
      'front_view'         (is_primary=0, 单张正立面四视图)
      'side_view'          (is_primary=0, 单张侧立面四视图)
      'back_view'          (is_primary=0, 单张背立面四视图)
      'three_quarter_view' (is_primary=0, 单张3/4侧面四视图)
      'four_view'          (is_primary=0, 传统复合多角度)
      'facial_macro'       (is_primary=0)
      'hands_detail'       (is_primary=0)
    """
    combined = f"{token} {explicit_label}".upper()
    # 1. 优先识别单张四视图具体视角 (严禁四宫格合并)
    if any(k in combined for k in ("4V_FRONT", "FRONT_VIEW", "正立面", "正视图", "正面视角", "FRONT_FULL")) and not any(k in combined for k in ("FOUR_VIEW", "四视图")):
        return ("front_view", explicit_label or "正面定妆视角", 0)
    if any(k in combined for k in ("4V_SIDE", "SIDE_VIEW", "4V_PROFILE", "PROFILE", "侧立面", "侧视图", "侧面视角")):
        return ("side_view", explicit_label or "侧面定妆视角", 0)
    if any(k in combined for k in ("4V_BACK", "BACK_VIEW", "REAR", "背立面", "背视图", "背面视角")):
        return ("back_view", explicit_label or "背面定妆视角", 0)
    if any(k in combined for k in ("4V_3Q", "4V_THREE_QUARTER", "THREE_QUARTER", "3Q", "四分之三侧面", "半侧面")):
        return ("three_quarter_view", explicit_label or "3/4侧面定妆视角", 0)
    # 2. 传统/复合多角度工程切片 (four_view, is_primary=0)
    if any(k in combined for k in (
        "FOUR_VIEW", "THREE_VIEW", "4V", "3V", "SHEET", "四视图", "三视图",
        "多角度", "工程视图", "工程切片", "正侧背"
    )):
        return ("four_view", explicit_label or "角色多角度工程视图", 0)
    # 3. 全身定妆立绘 (full_body, is_primary=0)
    if any(k in combined for k in ("FULL_BODY", "FULLBODY", "BASE_COSTUME", "全身", "立绘")):
        return ("full_body", explicit_label or "全身定妆立绘", 0)
    # 4. 面部微距/特写 (facial_macro, is_primary=0)
    if any(k in combined for k in ("MACRO_FACE", "FACIAL_MACRO", "MACRO", "CLOSEUP", "FACE", "FACIAL", "面部特写", "微距", "五官")):
        return ("facial_macro", explicit_label or "面部五官超清微距切片", 0)
    # 5. 手部细节与道具交互切片 (hands_detail, is_primary=0)
    if any(k in combined for k in ("MACRO_HAND", "HANDS_DETAIL", "HAND", "HANDS", "手部", "手部特写")):
        return ("hands_detail", explicit_label or "手部与握持动作精细切片", 0)
    # 6. 默认/主视觉肖像 (main_portrait, is_primary=1)
    return ("main_portrait", explicit_label or "主视觉肖像", 1)


def extract_natural_appearance(raw_prompt: str, char_name: str = "") -> str:
    """从可能包含工程切片或视图标签的描述中，清洗提取自然人生理外貌与气质核心描述，
    避免工程切片技术词（如纯白背景、4V多角度、中性无表情、T-pose等）污染 characters 表主外貌字段。
    """
    if not raw_prompt:
        return ""
    text_clean = str(raw_prompt).strip()
    engineering_patterns = [
        r"[【\[\(（]?(?:4V|3V|四视图|三视图|正侧背|工程切片|多角度工程视图)[】\]\)）]?",
        r"(?:纯白背景|白底|中性灰色背景|T-pose|A-pose|中性站姿|无动态表情|标准工程渲染图)[，,、\s]*",
        r"(?:正面、侧面、背面、四分之三侧面)[，,、\s]*",
        r"(?:正脸主肖像|全身定妆立绘|面部特写|手部特写)[：:\s]*",
    ]
    for pat in engineering_patterns:
        text_clean = re.sub(pat, "", text_clean, flags=re.IGNORECASE)
    text_clean = re.sub(r"^[，,、；;\s]+|[，,、；;\s]+$", "", text_clean)
    return text_clean.strip() or raw_prompt.strip()


def synthesize_character_literary_defaults(
    char_name: str,
    gender: str = "male",
    role: str = "supporting",
    appearance: str = "",
    perceived_age: int | None = None,
    curr_ep: int = 1,
) -> dict[str, Any]:
    """为阶段 6 新增/偶发梳理出的角色自动合成完整文学画像、心理动力学四元组与声音配置，
    避免 characters 核心元数据字段出现 NULL 或空串。
    """
    age_str = f"{perceived_age}岁" if perceived_age else "青年"
    gender_cn = "女性" if gender == "female" else ("男性" if gender == "male" else "角色")

    # 1. 角色描述 (description)
    desc = f"第{curr_ep}集登场的重要{gender_cn}角色（定位：{role}），在当前短剧剧情发展中承担戏剧推动与矛盾推进职能。"

    # 2. 性格特质 (personality) 与 心理动力学四元组 (psychology_4)
    if role in ("protagonist", "主角"):
        personality = "意志坚韧，行动果敢，在重重危机与两难抉择中展现强烈的目标感与隐忍克制。"
        want = "打破当前困境，查明核心真相并保护关键目标"
        need = "直面内心潜藏的脆弱与执念，完成自我人格救赎"
        the_lie = "唯有完全依靠自身算计与武力方能生存"
        the_ghost = "过往惨痛的背叛或重大失败阴影"
    elif role in ("antagonist", "反派"):
        personality = "城府深沉，手段狠辣，拥有极强控制欲，为达成目的不择手段。"
        want = "彻底掌控局势并铲除一切阻碍自身计划的对手"
        need = "认知自身欲望背后的虚妄，突破毁灭性偏执"
        the_lie = "权势与绝对威慑是世间唯一的通行法则"
        the_ghost = "曾被践踏屈辱所铸就的极度不安全感"
    else:
        personality = "机警敏锐，行事沉稳，对局势变化具备精准洞察力，恪守自身处世原则。"
        want = "在动荡交锋中坚守职责底线并保障自身立场"
        need = "超越独善其身，在关键抉择时刻勇于担当"
        the_lie = "只要置身事外便能远离风暴中心的漩涡"
        the_ghost = "曾因无能为力而未能挽回的遗憾往事"

    psychology_4 = {
        "want": want,
        "need": need,
        "the_lie": the_lie,
        "the_ghost": the_ghost,
    }

    # 3. 自然人基础外貌 (appearance)
    if not appearance:
        appearance = f"外表气质硬朗鲜明，约{age_str}左右，面容轮廓分明，眼神锐利且富于情绪表现力，身形体态端正。"

    # 4. 声音演播风格 (voice_style)
    if gender == "female":
        voice_style = "清亮从容，吐字清晰，语速平稳适中，情绪起伏富有层次感与张力"
        timbre = "清雅女声，中频温润自然"
    else:
        voice_style = "沉稳有力，中气饱满，语速沉着张弛有度，尾音平稳坚定"
        timbre = "低沉磁性男音，厚度与穿透力兼备"

    # 5. 声学人格 (acoustic_persona)
    acoustic_persona = {
        "timbre": timbre,
        "speed_ratio": 1.0,
        "pitch_ratio": 1.0,
        "cadence": "沉着稳健",
        "dramatic_subtext": f"{char_name}在交锋与对话中保持高度克制与防备",
    }

    # 6. 声学指纹 (voice_fingerprint)
    fp_hash = hashlib.md5(f"{char_name}_{timbre}".encode("utf-8")).hexdigest()[:8].upper()
    voice_fingerprint = {
        "fingerprint_id": f"VF_{fp_hash}",
        "acoustic_color": timbre,
        "delivery_dynamics": voice_style,
    }

    return {
        "description": desc,
        "personality": personality,
        "psychology_4": psychology_4,
        "appearance": appearance,
        "voice_style": voice_style,
        "acoustic_persona": acoustic_persona,
        "voice_fingerprint": voice_fingerprint,
    }


def synthesize_voice_prompt(
    char_name: str,
    timbre: str = "",
    role: str = "supporting",
    personality: str = "",
    gender: str = "male",
    monologue_source: str = "",
    perceived_age: str | int | None = None,
    voice_style: str = "",
    acoustic_persona: dict[str, Any] | None = None,
) -> str:
    """合成专业级广播剧/影视配音 TTS 声音生成提示词，
    覆盖【音色基调】、【发音与节奏】、【戏剧潜台词与语调】、【多维情绪演绎规范】与【声音质感】五大维度。
    """
    clean_name = clean_character_name(char_name) or "角色"
    if not timbre and voice_style:
        timbre = voice_style
    if not timbre:
        age_str = f"{perceived_age}岁" if perceived_age else ""
        timbre = f"清雅知性{age_str}女声，中高频温润通透" if gender == "female" else f"低沉磁性{age_str}成熟男声，胸腔共鸣浑厚"

    role_desc = "核心主角" if role in ("protagonist", "主角") else ("主要反派对手" if role in ("antagonist", "反派") else "关键推动角色")
    subtext = f"言辞间透露出{personality or '内敛克制'}的心理底色，字句咬合沉稳而有锋芒"

    prompt_lines = [
        f"【音色基调】：{timbre}，声音辨识度极高，音质纯净自然，中频富有饱满度与故事叙事厚度。",
        "【发音与节奏】：标准普通话发音，咬字清晰利落，平均语速约每分钟210字，重音抑扬顿挫，停顿呼吸真实自然。",
        f"【戏剧潜台词与语调】：紧密契合“{clean_name}”的{role_desc}身份，{subtext}。",
        "【多维情绪演绎规范】：",
        "- 常态对话：冷静自持，声调平稳，句尾微收，不疾不徐；",
        "- 戏剧冲突：声压增强，节奏骤紧，爆发力十足但破而不破，富有情绪穿透力；",
        "- 独白思考：压低共鸣腔，微弱气声自然融入，显露潜意识复杂波澜。",
        "【声音质感】：专业录音棚广播剧电影级声学混音，平直频响无失真，空间混响干净，杜绝电音及机械金属感。",
    ]
    if isinstance(acoustic_persona, dict) and acoustic_persona:
        acou_notes = []
        if acoustic_persona.get("pitch_base"):
            acou_notes.append(f"基础音高: {acoustic_persona['pitch_base']}")
        if acoustic_persona.get("formant_focus"):
            acou_notes.append(f"共鸣焦点: {acoustic_persona['formant_focus']}")
        if acoustic_persona.get("texture_detail"):
            acou_notes.append(f"质感细节: {acoustic_persona['texture_detail']}")
        if acou_notes:
            prompt_lines.append(f"【声学特征细节】：{', '.join(acou_notes)}")
    if monologue_source:
        prompt_lines.append(f"【参考台词示范】：“{monologue_source}”")

    return "\n".join(prompt_lines)


# =========================================================================
# 阶段 6：单集视听资源引单与资产校验持久化
# =========================================================================

def persist_stage6(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 6 深度原子落库：
    1. 单集 AST 结构化清单写入 episodes.ast_blocks['episode_resource_manifest']；
    2. 增量角色自动建档 characters，补全新出场角色基础属性；
    3. 角色各集外观服化道与主视切片写入 character_stages 与 character_stage_views；
    4. 当前集登场角色与集数映射落库 episode_characters 关联表；
    5. 角色专属音色卡片与母音同步写入 character_voice_profiles；
    6. 增量发生场景及气候做旧图层写入 scenes, scene_zones, scene_weathering_views；
    7. 增量关键道具及其剧情战损演进形态写入 props, prop_damage_states；
    8. 视听多模态资产全景注册表更新至 dramas.metadata，同步向量记忆库。
    """
    curr_ep = (
        episode_num
        or getattr(state, "episode_number", None)
        or getattr(state, "episode_num", None)
        or getattr(state, "current_visual_episode", None)
        or (state.get("episode_number") if isinstance(state, dict) else None)
        or (state.get("episode_num") if isinstance(state, dict) else None)
        or (state.get("current_visual_episode") if isinstance(state, dict) else None)
        or 1
    )
    log.info("【阶段 6 落库】开始持久化短剧 [%s] 第 %s 集的视听资源引单与关系表资产...", drama_id, curr_ep)
    now = now_iso()

    # -------------------------------------------------------------------------
    # 0. 鲁棒提取 manifest 资源引单数据
    # -------------------------------------------------------------------------
    manifest = (
        getattr(state, "manifest", None)
        or getattr(state, "resource_manifest", None)
        or getattr(state, "episode_manifest", None)
        or getattr(state, "episode_resource_manifest", None)
    )
    if not manifest and isinstance(state, dict):
        manifest = (
            state.get("manifest")
            or state.get("resource_manifest")
            or state.get("episode_manifest")
            or state.get("episode_resource_manifest")
        )
    if not manifest and hasattr(state, "episode_manifests") and isinstance(state.episode_manifests, dict):
        manifest = state.episode_manifests.get(curr_ep)
    if not manifest and hasattr(state, "episode_resource_manifests") and isinstance(state.episode_resource_manifests, dict):
        manifest = state.episode_resource_manifests.get(curr_ep)
    if not manifest and isinstance(state, dict):
        if isinstance(state.get("episode_manifests"), dict):
            manifest = state["episode_manifests"].get(curr_ep)
        elif isinstance(state.get("episode_resource_manifests"), dict):
            manifest = state["episode_resource_manifests"].get(curr_ep)
    if not manifest and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
        extra = state.__pydantic_extra__
        m_extra = extra.get("episode_manifests") or extra.get("episode_resource_manifests")
        if isinstance(m_extra, dict):
            manifest = m_extra.get(curr_ep)

    manifest_dict = _dump_or_dict(manifest) if manifest else {}

    # 提取角色、环境、道具、音频及增量卡片清单并规范化解构为字典列表
    raw_chars = (
        manifest_dict.get("characters")
        or manifest_dict.get("characters_in_scene")
        or manifest_dict.get("characters_tier_1")
        or []
    )
    characters_manifest = _flatten_asset_collection(raw_chars, "CHAR")

    raw_envs = (
        manifest_dict.get("environments")
        or manifest_dict.get("scenes_in_use")
        or []
    )
    environments_manifest = _flatten_asset_collection(raw_envs, "ENV")

    raw_props = (
        manifest_dict.get("props")
        or manifest_dict.get("props_in_use")
        or []
    )
    props_manifest = _flatten_asset_collection(raw_props, "PROP")

    extra_dict = getattr(state, "__pydantic_extra__", None) or {}
    raw_vc = (
        getattr(state, "new_character_master_voice_cards", None)
        or (state.get("new_character_master_voice_cards") if isinstance(state, dict) else None)
        or getattr(state, "voice_cards", None)
        or (state.get("voice_cards") if isinstance(state, dict) else None)
        or extra_dict.get("new_character_master_voice_cards")
        or extra_dict.get("voice_cards")
        or manifest_dict.get("new_character_master_voice_cards")
        or manifest_dict.get("voice_cards")
        or manifest_dict.get("voice_profiles")
        or []
    )
    voice_cards = _flatten_asset_collection(raw_vc, "VOICE")

    # 提取第 6 阶段增量发掘的未登记新角色全息档案 (Stage 2 11 维建档规格)
    raw_new_chars = (
        getattr(state, "newly_discovered_characters", None)
        or (state.get("newly_discovered_characters") if isinstance(state, dict) else None)
        or extra_dict.get("newly_discovered_characters")
        or manifest_dict.get("newly_discovered_characters")
        or []
    )
    newly_discovered_characters: list[dict[str, Any]] = []
    if isinstance(raw_new_chars, list):
        for nc in raw_new_chars:
            nc_dict = _dump_or_dict(nc)
            if isinstance(nc_dict, dict):
                newly_discovered_characters.append(nc_dict)
    log.debug(
        "【阶段 6 落库】[DEBUG 增量角色发现] 接收到 newly_discovered_characters 数量=%d",
        len(newly_discovered_characters),
    )

    # 提取第 6 阶段增量发掘的未登记新场景全息档案 (Stage 3 建档规格)
    raw_new_scenes = (
        getattr(state, "newly_discovered_scenes", None)
        or (state.get("newly_discovered_scenes") if isinstance(state, dict) else None)
        or extra_dict.get("newly_discovered_scenes")
        or manifest_dict.get("newly_discovered_scenes")
        or []
    )
    newly_discovered_scenes: list[dict[str, Any]] = []
    if isinstance(raw_new_scenes, list):
        for ns in raw_new_scenes:
            ns_dict = _dump_or_dict(ns)
            if isinstance(ns_dict, dict):
                newly_discovered_scenes.append(ns_dict)
    log.debug(
        "【阶段 6 落库】[DEBUG 增量场景发现] 接收到 newly_discovered_scenes 数量=%d",
        len(newly_discovered_scenes),
    )

    # 提取第 6 阶段增量发掘的未登记新道具全息档案 (Stage 3 建档规格)
    raw_new_props = (
        getattr(state, "newly_discovered_props", None)
        or (state.get("newly_discovered_props") if isinstance(state, dict) else None)
        or extra_dict.get("newly_discovered_props")
        or manifest_dict.get("newly_discovered_props")
        or []
    )
    newly_discovered_props: list[dict[str, Any]] = []
    if isinstance(raw_new_props, list):
        for np in raw_new_props:
            np_dict = _dump_or_dict(np)
            if isinstance(np_dict, dict):
                newly_discovered_props.append(np_dict)
    log.debug(
        "【阶段 6 落库】[DEBUG 增量道具发现] 接收到 newly_discovered_props 数量=%d",
        len(newly_discovered_props),
    )

    raw_new_assets = (
        getattr(state, "newly_generated_assets", None)
        or (state.get("newly_generated_assets") if isinstance(state, dict) else None)
        or extra_dict.get("newly_generated_assets")
        or manifest_dict.get("newly_generated_assets")
        or []
    )
    newly_generated_assets = _flatten_asset_collection(raw_new_assets, "ASSET")

    raw_reused_assets = (
        getattr(state, "reused_existing_assets", None)
        or (state.get("reused_existing_assets") if isinstance(state, dict) else None)
        or extra_dict.get("reused_existing_assets")
        or manifest_dict.get("reused_existing_assets")
        or []
    )
    reused_assets_data = _flatten_asset_collection(raw_reused_assets, "REUSED")

    raw_lineage_dag = (
        getattr(state, "lineage_dag", None)
        or (state.get("lineage_dag") if isinstance(state, dict) else None)
        or extra_dict.get("lineage_dag")
        or manifest_dict.get("lineage_dag")
        or {}
    )
    lineage_dag_data = _dump_or_dict(raw_lineage_dag) if isinstance(raw_lineage_dag, dict) else {}

    raw_sem_hashes = (
        getattr(state, "semantic_hashes", None)
        or (state.get("semantic_hashes") if isinstance(state, dict) else None)
        or (
            state.visual_audio_assets_registry.get("semantic_hashes")
            if hasattr(state, "visual_audio_assets_registry") and isinstance(getattr(state, "visual_audio_assets_registry"), dict)
            else (
                state.get("visual_audio_assets_registry", {}).get("semantic_hashes")
                if isinstance(state, dict) and isinstance(state.get("visual_audio_assets_registry"), dict)
                else None
            )
        )
        or manifest_dict.get("semantic_hashes")
        or {}
    )

    # -------------------------------------------------------------------------
    # 1. 查询并更新单集 AST 结构化块 (episodes 表)
    # -------------------------------------------------------------------------
    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": curr_ep},
    )
    episode_id = ep_row["id"] if ep_row else None

    # 确保 manifest_dict 完整保留血缘 DAG、复用资产和新生成资产及语义指纹
    if lineage_dag_data:
        manifest_dict["lineage_dag"] = lineage_dag_data
    if reused_assets_data:
        manifest_dict["reused_existing_assets"] = reused_assets_data
    if newly_generated_assets:
        manifest_dict["newly_generated_assets"] = newly_generated_assets
    if raw_sem_hashes:
        manifest_dict["semantic_hashes"] = raw_sem_hashes

    if ep_row and manifest_dict:
        ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
        ep_ast["episode_resource_manifest"] = manifest_dict
        db.execute(
            text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
            {"id": episode_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
        )
        log.info(
            "【阶段 6 落库】[步骤 1/6] 单集 AST 更新完成: drama_id=%s, episode_id=%s, ep_num=%s",
            drama_id, episode_id, curr_ep,
        )
        log.debug(
            "【阶段 6 落库】[DEBUG 单集 AST] episode_resource_manifest 内容快照: keys=%s, lineage_dag 项数=%d, 复用资产数=%d",
            list(manifest_dict.keys()), len(lineage_dag_data), len(reused_assets_data),
        )
    else:
        log.warning(
            "【阶段 6 落库】[步骤 1/6] 未找到短剧 [%s] 第 %s 集 episodes 记录或引单为空",
            drama_id, curr_ep,
        )

    # -------------------------------------------------------------------------
    # 2. 角色领域三层模型深度原子落库 (characters, character_stages, character_stage_views, episode_characters)
    #    Tier 1: 自然人角色核心实体 (characters, 1 人 1 条, 聚合所有造型与切片，杜绝空字段)
    #    Tier 2: 角色生命周期服化道/形态阶段 (character_stages, 演化树 parent_stage_id)
    #    Tier 3: 角色各形态切片基准视图 (character_stage_views, 正面肖像/全身/四视图/微距)
    #    Relation: 单集登场关联绑定 (episode_characters, 仅绑定自然人实体)
    # -------------------------------------------------------------------------
    # 2.1 汇集所有角色候选源 (引单 + 生成资产 + 引擎状态池)
    raw_character_candidates: list[dict[str, Any]] = []
    seen_candidate_keys: set[str] = set()

    # 提取上游各阶段注入的文学画像状态池 (characters_engine, character_engine, characters, newly_discovered_characters)
    engine_char_pool: dict[str, dict[str, Any]] = {}
    raw_pools: list[Any] = []
    for attr in ("characters_engine", "character_engine", "characters"):
        val = getattr(state, attr, None)
        if isinstance(val, dict):
            raw_pools.extend(val.get("characters") or val.get("character_profiles") or [])
        elif isinstance(val, list):
            raw_pools.extend(val)
    if newly_discovered_characters:
        raw_pools.extend(newly_discovered_characters)

    for item in raw_pools:
        item_dict = _dump_or_dict(item)
        if not isinstance(item_dict, dict):
            continue
        c_name = str(item_dict.get("name") or item_dict.get("character_name") or "").strip()
        c_code = str(item_dict.get("character_code") or item_dict.get("char_id") or "").strip()
        clean_n = clean_character_name(c_name)
        if c_name:
            engine_char_pool[c_name] = item_dict
            engine_char_pool[c_name.lower()] = item_dict
        if clean_n:
            engine_char_pool[clean_n] = item_dict
            engine_char_pool[clean_n.lower()] = item_dict
        if c_code:
            engine_char_pool[c_code] = item_dict
            engine_char_pool[c_code.upper()] = item_dict
            stripped = c_code.replace("CHAR_", "")
            engine_char_pool[stripped] = item_dict
            engine_char_pool[f"CHAR_{stripped}"] = item_dict

    log.debug(
        "【阶段 6 落库】[Tier 1 状态池检索] 预装载上游角色文学引擎档案索引项数: %s (含本集新发现未登记角色: %d)",
        len(engine_char_pool), len(newly_discovered_characters),
    )

    # 优先装填本集新发现未登记角色 (确保 11 维全息字段优先确立 canonical_map 实体)
    for ndc in newly_discovered_characters:
        if isinstance(ndc, dict):
            k = str(ndc.get("character_code") or ndc.get("char_id") or ndc.get("name") or "").strip()
            if k:
                seen_candidate_keys.add(k)
            raw_character_candidates.append(ndc)

    for c_raw in characters_manifest:
        c = _dump_or_dict(c_raw)
        if isinstance(c, dict):
            k = str(c.get("char_id") or c.get("asset_id") or c.get("asset_key") or c.get("character_code") or c.get("name") or "").strip()
            if k:
                seen_candidate_keys.add(k)
            raw_character_candidates.append(c)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or n_dict.get("asset_key") or "")
        if (cat == "character" or aid.startswith("CHAR_")):
            if aid not in seen_candidate_keys:
                seen_candidate_keys.add(aid)
                raw_character_candidates.append(n_dict)

    for ec in raw_pools:
        ec_dict = _dump_or_dict(ec)
        if isinstance(ec_dict, dict):
            k = str(ec_dict.get("character_code") or ec_dict.get("char_id") or ec_dict.get("name") or "").strip()
            if k and k not in seen_candidate_keys:
                seen_candidate_keys.add(k)
                raw_character_candidates.append(ec_dict)

    # 2.2 预查已登记角色库构建内存索引（包含阶段 2 的 11 维全息字段）
    existing_chars_in_db = fetch_all(
        db,
        """
        SELECT id, character_code, name, appearance, voice_style, role, description,
               personality, gender, perceived_age, identity_anchors,
               visual_consistency_code, carried_anchor_item, drama_engine,
               growth_chain, current_status,
               psychology_4, acoustic_persona, voice_fingerprint
        FROM characters
        WHERE drama_id = :drama_id
        """,
        {"drama_id": drama_id},
    )
    db_char_by_name: dict[str, dict[str, Any]] = {row["name"]: row for row in existing_chars_in_db if row.get("name")}
    db_char_by_code: dict[str, dict[str, Any]] = {row["character_code"]: row for row in existing_chars_in_db if row.get("character_code")}
    db_char_by_stripped_code: dict[str, dict[str, Any]] = {
        row["character_code"].replace("CHAR_", ""): row
        for row in existing_chars_in_db if row.get("character_code")
    }

    # 2.3 内存三层模型规范化归纳聚合 (Canonical Entity Aggregation)
    canonical_map: dict[str, dict[str, Any]] = {}

    for c in raw_character_candidates:
        raw_name = str(c.get("character_name") or c.get("name") or "").strip()
        raw_code = str(c.get("character_code") or c.get("char_id") or c.get("asset_id") or c.get("asset_key") or "").strip()
        if not raw_name and not raw_code:
            continue

        parsed_code, parsed_stage, parsed_view = extract_character_tokens(raw_code)
        clean_name = clean_character_name(raw_name)

        # 匹配既有数据库角色
        matched_db = None
        if clean_name and clean_name in db_char_by_name:
            matched_db = db_char_by_name[clean_name]
        elif raw_name and raw_name in db_char_by_name:
            matched_db = db_char_by_name[raw_name]
        elif raw_code and raw_code in db_char_by_code:
            matched_db = db_char_by_code[raw_code]
        elif parsed_code and parsed_code in db_char_by_stripped_code:
            matched_db = db_char_by_stripped_code[parsed_code]
        elif parsed_code and f"CHAR_{parsed_code}" in db_char_by_code:
            matched_db = db_char_by_code[f"CHAR_{parsed_code}"]

        # 匹配上游引擎画像 (characters_engine / character_engine / characters)
        matched_engine = (
            engine_char_pool.get(clean_name)
            or engine_char_pool.get(clean_name.lower())
            or engine_char_pool.get(raw_name)
            or engine_char_pool.get(raw_name.lower())
            or engine_char_pool.get(raw_code)
            or engine_char_pool.get(raw_code.upper())
            or (engine_char_pool.get(parsed_code) if parsed_code else None)
        )

        # 确立规范化自然人属性 (Tier 1 Entity)
        if matched_db:
            char_name = matched_db["name"]
            char_code = matched_db["character_code"]
            existing_db_id = matched_db["id"]
        elif matched_engine:
            char_name = matched_engine.get("name") or clean_name or raw_name or "未命名角色"
            char_code = matched_engine.get("character_code") or (f"CHAR_{parsed_code}" if parsed_code else (raw_code if raw_code.startswith("CHAR_") else f"CHAR_{char_name}"))
            existing_db_id = None
        else:
            char_name = clean_name or (parsed_code if parsed_code else (raw_code if raw_code else "未命名角色"))
            char_code = f"CHAR_{parsed_code}" if parsed_code else (raw_code if raw_code.startswith("CHAR_") else f"CHAR_{char_name}")
            existing_db_id = None

        # 对未在数据库登记的新角色候选进行合法性守卫：拦截声学/舞台指令或括号残片（如 "[声学行为"）
        if not matched_db and raw_name and not is_valid_character_speaker(clean_name or raw_name, known_names=set(db_char_by_name.keys())):
            log.warning(
                "【阶段 6 落库·脏数据拦截】跳过非法角色名/舞台指令候选: raw_name=%s, clean_name=%s, raw_code=%s",
                raw_name, clean_name, raw_code,
            )
            continue

        entity_key = char_name.lower()
        visual_prompt = str(c.get("visual_prompt") or c.get("appearance") or c.get("prompt") or "").strip()
        cleaned_bio_appearance = extract_natural_appearance(visual_prompt, char_name)

        if entity_key not in canonical_map:
            raw_g = str(
                c.get("gender")
                or (matched_engine.get("gender") if matched_engine else "")
                or (matched_db.get("gender") if matched_db else "")
                or ""
            ).strip().lower()
            if raw_g in ("女", "female", "f"):
                gender = "female"
            elif raw_g in ("男", "male", "m"):
                gender = "male"
            elif raw_g == "other":
                gender = "other"
            else:
                gender = "female" if any(kw in (visual_prompt + char_name) for kw in ("女", "母", "姐", "妹", "妻", "妃", "后", "裙")) else "male"

            raw_age = (
                c.get("perceived_age")
                or (matched_engine.get("perceived_age") if matched_engine else None)
                or (matched_db.get("perceived_age") if matched_db else None)
            )
            if isinstance(raw_age, (int, float)):
                perceived_age = int(raw_age)
            elif raw_age:
                m_age = re.search(r"\d+", str(raw_age))
                perceived_age = int(m_age.group()) if m_age else None
            else:
                perceived_age = None

            role = str(
                c.get("role")
                or (matched_engine.get("role") if matched_engine else "")
                or (matched_db.get("role") if matched_db else "")
                or "supporting"
            ).strip()

            desc = str(
                c.get("description")
                or (matched_engine.get("description") if matched_engine else "")
                or (matched_db.get("description") if matched_db else "")
                or ""
            ).strip()

            personality = str(
                c.get("personality")
                or (matched_engine.get("personality") if matched_engine else "")
                or (matched_db.get("personality") if matched_db else "")
                or ""
            ).strip()

            appearance = (
                (matched_engine.get("appearance") if matched_engine else "")
                or (matched_db.get("appearance") if matched_db else "")
                or cleaned_bio_appearance
            ).strip()

            voice_style = str(
                c.get("voice_style")
                or (matched_engine.get("voice_style") if matched_engine else "")
                or (matched_db.get("voice_style") if matched_db else "")
                or ""
            ).strip()

            psychology_4 = (
                c.get("psychology_4") or c.get("psychological_quad")
                or (matched_engine.get("psychology_4") or matched_engine.get("psychological_quad") if matched_engine else None)
                or (matched_db.get("psychology_4") if matched_db else None)
            )

            acoustic_persona = (
                c.get("acoustic_persona")
                or (matched_engine.get("acoustic_persona") if matched_engine else None)
                or (matched_db.get("acoustic_persona") if matched_db else None)
            )

            voice_fingerprint = (
                c.get("voice_fingerprint")
                or (matched_engine.get("voice_fingerprint") if matched_engine else None)
                or (matched_db.get("voice_fingerprint") if matched_db else None)
            )

            identity_anchors = (
                c.get("identity_anchors")
                or (matched_engine.get("identity_anchors") if matched_engine else None)
                or (matched_db.get("identity_anchors") if matched_db else None)
            )

            visual_consistency_code = (
                c.get("visual_consistency_code")
                or (matched_engine.get("visual_consistency_code") if matched_engine else None)
                or (matched_db.get("visual_consistency_code") if matched_db else None)
            )
            carried_anchor_item = (
                c.get("carried_anchor_item")
                or (matched_engine.get("carried_anchor_item") if matched_engine else None)
                or (matched_db.get("carried_anchor_item") if matched_db else None)
            )
            drama_engine = (
                c.get("drama_engine")
                or (matched_engine.get("drama_engine") if matched_engine else None)
                or (matched_db.get("drama_engine") if matched_db else None)
            )
            growth_chain = (
                c.get("growth_chain")
                or (matched_engine.get("growth_chain") if matched_engine else None)
                or (matched_db.get("growth_chain") if matched_db else None)
            )
            current_status = (
                c.get("current_status")
                or (matched_engine.get("current_status") if matched_engine else None)
                or (matched_db.get("current_status") if matched_db else None)
            )
            new_relationships = (
                c.get("new_relationships")
                or (matched_engine.get("new_relationships") if matched_engine else None)
                or []
            )

            # 智能合成保底文学/心理/声音画像（防止字段出现 NULL 或空值，完全对齐阶段 2 11 维建档规格）
            lit_defaults = synthesize_character_literary_defaults(
                char_name=char_name,
                gender=gender,
                role=role,
                appearance=appearance,
                perceived_age=perceived_age,
                curr_ep=curr_ep,
            )
            if not desc or desc == f"第{curr_ep}集登场角色":
                desc = lit_defaults["description"]
            if not personality:
                personality = lit_defaults["personality"]
            if not appearance:
                appearance = lit_defaults["appearance"]
            if not psychology_4 or psychology_4 == {} or psychology_4 == "{}":
                psychology_4 = lit_defaults["psychology_4"]
            if not voice_style:
                voice_style = lit_defaults["voice_style"]
            if not acoustic_persona or acoustic_persona == {} or acoustic_persona == "{}":
                acoustic_persona = lit_defaults["acoustic_persona"]
            if not voice_fingerprint or voice_fingerprint == {} or voice_fingerprint == "{}":
                voice_fingerprint = lit_defaults["voice_fingerprint"]
            if not identity_anchors:
                identity_anchors = [appearance[:60] or f"{char_name}面部与装造生理锚点"]
            if not visual_consistency_code:
                visual_consistency_code = {
                    "base_face_lock": appearance[:80] or f"{char_name}面部骨骼特征锚定",
                    "default_costume_lock": f"第{curr_ep}集标准日常造型",
                    "skin_texture": "真实微瑕皮肤，清晰毛孔与自然高光，杜绝磨皮塑料感",
                }
            if not carried_anchor_item:
                carried_anchor_item = {
                    "item_name": f"{char_name}随身信物",
                    "visual_detail": "带有岁月摩挲痕迹与剧情线索的贴身小物件",
                }
            if not drama_engine:
                drama_engine = {
                    "core_motivation": f"在第{curr_ep}集冲突中守护核心利益并推动剧情转折",
                    "fatal_weakness": "对关键秘密或人际软肋的隐瞒",
                }
            if not growth_chain:
                growth_chain = [{
                    "episode": curr_ep,
                    "phase": f"第{curr_ep}集初登场建档",
                    "state": "卷入当前集核心戏剧冲突",
                }]
            if not current_status:
                current_status = {
                    "onboarded_at_episode": curr_ep,
                    "physical_state": "normal",
                    "emotional_state": "alert",
                }

            identity_anchors_str = _ensure_valid_json_str(identity_anchors, "[]")
            visual_consistency_code_str = _ensure_valid_json_str(
                visual_consistency_code,
                "{}",
                wrap_key="base_face_lock",
            )
            carried_anchor_item_str = _ensure_valid_json_str(
                carried_anchor_item,
                "{}",
                wrap_key="item_name",
            )
            drama_engine_str = _ensure_valid_json_str(
                drama_engine,
                "{}",
                wrap_key="core_motivation",
            )
            growth_chain_str = _ensure_valid_json_str(growth_chain, "[]")
            current_status_str = _ensure_valid_json_str(
                current_status,
                "{}",
                wrap_key="state",
            )
            psychology_4_str = _ensure_valid_json_str(
                psychology_4,
                "{}",
                wrap_key="summary",
            )
            acoustic_persona_str = _ensure_valid_json_str(
                acoustic_persona,
                "{}",
                wrap_key="tone",
            )
            voice_fingerprint_str = _ensure_valid_json_str(
                voice_fingerprint,
                "{}",
                wrap_key="catchphrase",
            )

            canonical_map[entity_key] = {
                "db_id": existing_db_id,
                "char_name": char_name,
                "char_code": char_code,
                "gender": gender,
                "perceived_age": perceived_age,
                "role": role,
                "description": desc,
                "personality": personality,
                "appearance": appearance,
                "identity_anchors": identity_anchors_str,
                "visual_consistency_code": visual_consistency_code_str,
                "carried_anchor_item": carried_anchor_item_str,
                "drama_engine": drama_engine_str,
                "growth_chain": growth_chain_str,
                "current_status": current_status_str,
                "voice_style": voice_style,
                "psychology_4": psychology_4_str,
                "acoustic_persona": acoustic_persona_str,
                "voice_fingerprint": voice_fingerprint_str,
                "new_relationships": new_relationships if isinstance(new_relationships, list) else [],
                "stages": {},
            }
            log.debug(
                "【阶段 6 落库】[Tier 1 规范化归纳] 登记 11 维实体 [%s]: 代号=%s, 性别=%s, 定位=%s, 外貌字数=%s, 心理画像状态=%s, 新增关系数=%d",
                char_name, char_code, gender, role, len(appearance), "已具备" if psychology_4_str else "无",
                len(new_relationships) if isinstance(new_relationships, list) else 0,
            )
        else:
            ent = canonical_map[entity_key]
            if ent.get("perceived_age") is None:
                r_age = c.get("perceived_age") or (matched_engine.get("perceived_age") if matched_engine else None)
                if isinstance(r_age, (int, float)):
                    ent["perceived_age"] = int(r_age)
                elif r_age:
                    m_age = re.search(r"\d+", str(r_age))
                    if m_age:
                        ent["perceived_age"] = int(m_age.group())
            if (not ent.get("appearance") or len(ent.get("appearance")) < 5) and cleaned_bio_appearance:
                ent["appearance"] = cleaned_bio_appearance
            if not ent.get("voice_style"):
                vs = str(c.get("voice_style") or (matched_engine.get("voice_style") if matched_engine else "") or "").strip()
                if vs:
                    ent["voice_style"] = vs
            if not ent.get("personality"):
                p = str(c.get("personality") or (matched_engine.get("personality") if matched_engine else "") or "").strip()
                if p:
                    ent["personality"] = p
            if not ent.get("description"):
                d = str(c.get("description") or (matched_engine.get("description") if matched_engine else "") or "").strip()
                if d:
                    ent["description"] = d

        # 确立二级形态阶段 (Tier 2 Stage)
        stage_code = str(
            c.get("stage_code")
            or c.get("tier")
            or parsed_stage
            or ("T1" if "_T1_" in raw_code or "BASE" in raw_code else "")
        ).strip()
        if not stage_code:
            st_m = re.search(r"_(T\d+)_", raw_code)
            stage_code = st_m.group(1).upper() if st_m else "T1"
        else:
            if re.match(r"^[ts]\d+", stage_code, re.IGNORECASE):
                stage_code = stage_code.upper()

        stage_name = str(c.get("stage_name") or c.get("appearance_variant") or c.get("outfit") or "").strip()
        if not stage_name:
            b_m = re.search(r"[\(（\[【]([^\)）\]】]+)[\)）\]】]", raw_name)
            if b_m:
                b_val = b_m.group(1).strip()
                if not any(k in b_val for k in ("定妆", "肖像", "特写", "视图", "切片", "微距", "立绘")):
                    stage_name = b_val
        if not stage_name:
            stage_name = f"{char_name}_{stage_code}造型" if stage_code not in ("T1", "BASE") else f"第{curr_ep}集造型"

        parent_ref = c.get("parent_stage_id") or c.get("parent_asset_id") or c.get("parent_stage_code") or c.get("parent_stage_name") or ""
        costume_desc = str(c.get("costume_description") or c.get("visual_prompt") or c.get("appearance") or c.get("prompt") or "").strip()
        color_palette = c.get("color_palette")
        color_palette_str = json.dumps(color_palette, ensure_ascii=False) if isinstance(color_palette, (dict, list)) else (str(color_palette) if color_palette else None)

        stages_dict = canonical_map[entity_key]["stages"]
        if stage_code not in stages_dict:
            stages_dict[stage_code] = {
                "stage_code": stage_code,
                "stage_name": stage_name,
                "parent_stage_ref": parent_ref,
                "costume_description": costume_desc,
                "color_palette": color_palette_str,
                "views": {},
            }
        else:
            st_data = stages_dict[stage_code]
            if not st_data.get("parent_stage_ref") and parent_ref:
                st_data["parent_stage_ref"] = parent_ref
            if not st_data.get("costume_description") and costume_desc:
                st_data["costume_description"] = costume_desc

        # 确立三级切片视图 (Tier 3 Slices)
        token = parsed_view or c.get("function_type") or c.get("view_type") or raw_code
        explicit_label = c.get("view_label") or c.get("slice_name") or raw_name
        view_type, default_label, is_primary = parse_character_view_type(token, explicit_label)

        if c.get("view_type"):
            view_type = str(c["view_type"]).strip()
            is_primary = 1 if view_type == "main_portrait" else 0

        view_prompt = str(c.get("prompt") or c.get("image_prompt") or c.get("visual_prompt") or c.get("appearance") or "").strip()
        neg_prompt = str(c.get("negative_prompt") or "").strip() or None
        image_url = str(c.get("image_url") or c.get("url") or "").strip() or None
        local_path = str(c.get("local_path") or "").strip() or None
        seedance2_id = str(c.get("seedance2_asset_id") or "").strip() or None
        asset_key = str(c.get("asset_key") or c.get("asset_id") or raw_code or "").strip()
        c_parent_key = c.get("parent_asset_key") or c.get("parent_asset_id")
        c_gen_mode = c.get("generation_mode")
        c_denoise = c.get("denoise_strength") if c.get("denoise_strength") is not None else c.get("recommended_denoise")
        c_ctrl_type = c.get("control_type")
        c_is_bench = c.get("is_benchmark")

        st_views = stages_dict[stage_code]["views"]
        if view_type not in st_views:
            st_views[view_type] = {
                "view_type": view_type,
                "view_label": explicit_label or default_label,
                "image_prompt": view_prompt,
                "negative_prompt": neg_prompt,
                "image_url": image_url,
                "local_path": local_path,
                "seedance2_asset_id": seedance2_id,
                "is_primary": is_primary,
                "asset_keys": [asset_key] if asset_key else [],
                "parent_asset_key": c_parent_key,
                "generation_mode": c_gen_mode,
                "denoise_strength": c_denoise,
                "control_type": c_ctrl_type,
                "is_benchmark": c_is_bench,
            }
        else:
            v_entry = st_views[view_type]
            if not v_entry.get("image_prompt") and view_prompt:
                v_entry["image_prompt"] = view_prompt
            if not v_entry.get("image_url") and image_url:
                v_entry["image_url"] = image_url
            if not v_entry.get("local_path") and local_path:
                v_entry["local_path"] = local_path
            if asset_key and asset_key not in v_entry["asset_keys"]:
                v_entry["asset_keys"].append(asset_key)
            if not v_entry.get("parent_asset_key") and c_parent_key:
                v_entry["parent_asset_key"] = c_parent_key
            if not v_entry.get("generation_mode") and c_gen_mode:
                v_entry["generation_mode"] = c_gen_mode
            if v_entry.get("denoise_strength") is None and c_denoise is not None:
                v_entry["denoise_strength"] = c_denoise
            if not v_entry.get("control_type") and c_ctrl_type:
                v_entry["control_type"] = c_ctrl_type

        # 兼容 Table 6 嵌套双字段 (base_portrait / base_costume)
        bp_ref = str(c.get("base_portrait") or "").strip()
        if bp_ref:
            if "main_portrait" not in st_views:
                st_views["main_portrait"] = {
                    "view_type": "main_portrait",
                    "view_label": "正面主视觉基准切片",
                    "image_prompt": view_prompt,
                    "negative_prompt": neg_prompt,
                    "image_url": image_url,
                    "local_path": local_path,
                    "seedance2_asset_id": seedance2_id,
                    "is_primary": 1,
                    "asset_keys": [bp_ref],
                    "parent_asset_key": None,
                    "generation_mode": "t2i",
                    "is_benchmark": 1,
                }
            elif bp_ref not in st_views["main_portrait"]["asset_keys"]:
                st_views["main_portrait"]["asset_keys"].append(bp_ref)

        bc_ref = str(c.get("base_costume") or "").strip()
        if bc_ref:
            if "full_body" not in st_views:
                st_views["full_body"] = {
                    "view_type": "full_body",
                    "view_label": "全身定妆立绘",
                    "image_prompt": costume_desc or view_prompt,
                    "negative_prompt": neg_prompt,
                    "image_url": image_url,
                    "local_path": local_path,
                    "seedance2_asset_id": seedance2_id,
                    "is_primary": 0,
                    "asset_keys": [bc_ref],
                    "parent_asset_key": bp_ref or None,
                    "generation_mode": "i2i",
                    "denoise_strength": 0.45,
                    "is_benchmark": 0,
                }
            elif bc_ref not in st_views["full_body"]["asset_keys"]:
                st_views["full_body"]["asset_keys"].append(bc_ref)

    # 规范化阶段视图：确保每阶段有且仅有一个 is_primary=1 主视觉锚点
    for ent in canonical_map.values():
        for st_code, st_info in ent["stages"].items():
            st_views = st_info["views"]
            if not st_views:
                st_views["main_portrait"] = {
                    "view_type": "main_portrait",
                    "view_label": "正面主视觉基准切片",
                    "image_prompt": st_info.get("costume_description") or ent.get("appearance") or "",
                    "negative_prompt": None,
                    "image_url": None,
                    "local_path": None,
                    "seedance2_asset_id": None,
                    "is_primary": 1,
                    "asset_keys": [],
                }
            elif "main_portrait" in st_views:
                st_views["main_portrait"]["is_primary"] = 1
                for vt, vi in st_views.items():
                    if vt != "main_portrait":
                        vi["is_primary"] = 0
            else:
                has_prim = any(vi.get("is_primary") == 1 for vi in st_views.values())
                if not has_prim:
                    first_k = next(iter(st_views.keys()))
                    st_views[first_k]["is_primary"] = 1

    # 构建全局多维双向索引，支持任意凭证（中文名、代号、去前缀、归一化Token）快速索引实体
    canonical_by_name: dict[str, dict[str, Any]] = {}
    canonical_by_code: dict[str, dict[str, Any]] = {}

    for ent in canonical_map.values():
        c_name = ent["char_name"]
        c_clean_name = clean_character_name(c_name)
        c_code = ent["char_code"]
        c_code_stripped = c_code.replace("CHAR_", "", 1) if c_code.startswith("CHAR_") else c_code
        c_norm_tok = AssetProtocolHelper.normalize_token(c_code or c_name)

        if c_name:
            canonical_by_name[c_name] = ent
            canonical_by_name[c_name.lower()] = ent
        if c_clean_name:
            canonical_by_name[c_clean_name] = ent
            canonical_by_name[c_clean_name.lower()] = ent

        if c_code:
            canonical_by_code[c_code] = ent
            canonical_by_code[c_code.upper()] = ent
        if c_code_stripped:
            canonical_by_code[c_code_stripped] = ent
            canonical_by_code[c_code_stripped.upper()] = ent
        if c_norm_tok:
            canonical_by_code[c_norm_tok] = ent
            canonical_by_code[f"CHAR_{c_norm_tok}"] = ent

    log.debug(
        "【阶段 6 落库·双向索引初始化】已为 %d 位角色构建多维查找索引 (name_keys=%d, code_keys=%d)",
        len(canonical_map), len(canonical_by_name), len(canonical_by_code),
    )

    # 2.4 层级式物理落库 (Tier 1 -> Tier 2 -> Tier 3 + 集关联绑定)
    active_char_db_ids: list[int] = []
    stage_db_ids_by_code: dict[str, int] = {}
    stage_db_ids_by_name: dict[str, int] = {}
    asset_character_meta_map: dict[str, dict[str, Any]] = {}
    unresolved_stage_parents: list[dict[str, Any]] = []

    for ent_key, ent in canonical_map.items():
        char_name = ent["char_name"]
        char_code = ent["char_code"]
        char_id = ent.get("db_id")
        bench_char_key = AssetProtocolHelper.get_benchmark_key_for_character(char_code)

        # 序列化高级心理学四象限与声学画像
        psychology_4_json = _ensure_valid_json_str(ent.get("psychology_4"), "{}", wrap_key="summary")
        acoustic_persona_json = _ensure_valid_json_str(ent.get("acoustic_persona"), "{}", wrap_key="tone")
        voice_fingerprint_json = _ensure_valid_json_str(ent.get("voice_fingerprint"), "{}", wrap_key="catchphrase")

        if char_id:
            active_char_db_ids.append(char_id)
            db.execute(
                text("""
                    UPDATE characters
                    SET appearance = CASE WHEN appearance IS NULL OR appearance = '' THEN :appearance ELSE appearance END,
                        voice_style = CASE WHEN voice_style IS NULL OR voice_style = '' THEN :voice_style ELSE voice_style END,
                        personality = CASE WHEN personality IS NULL OR personality = '' THEN :personality ELSE personality END,
                        description = CASE WHEN description IS NULL OR description = '' THEN :description ELSE description END,
                        identity_anchors = CASE WHEN identity_anchors IS NULL OR identity_anchors = '' THEN :identity_anchors ELSE identity_anchors END,
                        visual_consistency_code = CASE WHEN visual_consistency_code IS NULL OR visual_consistency_code = '' OR visual_consistency_code = '{}' THEN :visual_consistency_code ELSE visual_consistency_code END,
                        carried_anchor_item = CASE WHEN carried_anchor_item IS NULL OR carried_anchor_item = '' OR carried_anchor_item = '{}' THEN :carried_anchor_item ELSE carried_anchor_item END,
                        drama_engine = CASE WHEN drama_engine IS NULL OR drama_engine = '' OR drama_engine = '{}' THEN :drama_engine ELSE drama_engine END,
                        growth_chain = CASE WHEN growth_chain IS NULL OR growth_chain = '' OR growth_chain = '[]' THEN :growth_chain ELSE growth_chain END,
                        current_status = CASE WHEN current_status IS NULL OR current_status = '' OR current_status = '{}' THEN :current_status ELSE current_status END,
                        psychology_4 = CASE WHEN psychology_4 IS NULL OR psychology_4 = '' OR psychology_4 = '{}' THEN :psychology_4 ELSE psychology_4 END,
                        acoustic_persona = CASE WHEN acoustic_persona IS NULL OR acoustic_persona = '' OR acoustic_persona = '{}' THEN :acoustic_persona ELSE acoustic_persona END,
                        voice_fingerprint = CASE WHEN voice_fingerprint IS NULL OR voice_fingerprint = '' OR voice_fingerprint = '{}' THEN :voice_fingerprint ELSE voice_fingerprint END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :benchmark_asset_key != '' THEN :benchmark_asset_key ELSE benchmark_asset_key END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": char_id,
                    "appearance": ent.get("appearance") or "",
                    "voice_style": ent.get("voice_style") or "",
                    "personality": ent.get("personality") or "",
                    "description": ent.get("description") or "",
                    "identity_anchors": ent.get("identity_anchors"),
                    "visual_consistency_code": ent.get("visual_consistency_code") or "{}",
                    "carried_anchor_item": ent.get("carried_anchor_item") or "{}",
                    "drama_engine": ent.get("drama_engine") or "{}",
                    "growth_chain": ent.get("growth_chain") or "[]",
                    "current_status": ent.get("current_status") or "{}",
                    "psychology_4": psychology_4_json,
                    "acoustic_persona": acoustic_persona_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "benchmark_asset_key": bench_char_key,
                    "now": now,
                },
            )
            log.debug(
                "【阶段 6 落库】[Tier 1 角色实体] 识别并更新已登记自然人角色: ID=%s, 代号=%s, 姓名=%s, 基准键=%s",
                char_id, char_code, char_name, bench_char_key,
            )
        else:
            c_ins = db.execute(
                text("""
                    INSERT INTO characters (
                        drama_id, character_code, name, gender, perceived_age,
                        role, description, personality, appearance,
                        identity_anchors, visual_consistency_code,
                        carried_anchor_item, drama_engine, growth_chain, current_status,
                        voice_style, acoustic_persona,
                        psychology_4, voice_fingerprint, benchmark_asset_key, created_at, updated_at
                    ) VALUES (
                        :drama_id, :character_code, :name, :gender, :perceived_age,
                        :role, :description, :personality, :appearance,
                        :identity_anchors, :visual_consistency_code,
                        :carried_anchor_item, :drama_engine, :growth_chain, :current_status,
                        :voice_style, :acoustic_persona,
                        :psychology_4, :voice_fingerprint, :benchmark_asset_key, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "character_code": char_code,
                    "name": char_name,
                    "gender": ent.get("gender") or "male",
                    "perceived_age": ent.get("perceived_age"),
                    "role": ent.get("role") or "supporting",
                    "description": ent.get("description") or f"第{curr_ep}集登场角色",
                    "personality": ent.get("personality") or "",
                    "appearance": ent.get("appearance") or "",
                    "identity_anchors": ent.get("identity_anchors"),
                    "visual_consistency_code": ent.get("visual_consistency_code") or "{}",
                    "carried_anchor_item": ent.get("carried_anchor_item") or "{}",
                    "drama_engine": ent.get("drama_engine") or "{}",
                    "growth_chain": ent.get("growth_chain") or "[]",
                    "current_status": ent.get("current_status") or "{}",
                    "voice_style": ent.get("voice_style") or "",
                    "acoustic_persona": acoustic_persona_json,
                    "psychology_4": psychology_4_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "benchmark_asset_key": bench_char_key,
                    "now": now,
                },
            )
            char_id = getattr(c_ins, "lastrowid", None) or 1
            ent["db_id"] = char_id
            active_char_db_ids.append(char_id)
            db_char_by_name[char_name] = {"id": char_id, "character_code": char_code, "name": char_name}
            db_char_by_code[char_code] = {"id": char_id, "character_code": char_code, "name": char_name}
            log.info(
                "【阶段 6 落库】[Tier 1 角色实体] 增量角色按阶段 2 11 维标准自动建档入库: ID=%s, 代号=%s, 姓名=%s, 基准键=%s",
                char_id, char_code, char_name, bench_char_key,
            )

        # 级联落库新角色双轨关系矩阵 (character_relationship)
        for rel_raw in ent.get("new_relationships") or []:
            rel = _dump_or_dict(rel_raw)
            if not isinstance(rel, dict):
                continue
            char_a_code = str(
                rel.get("character_a_code")
                or rel.get("character_a")
                or rel.get("source_code")
                or char_code
            ).strip()
            char_b_code = str(
                rel.get("character_b_code")
                or rel.get("character_b")
                or rel.get("target_character_code")
                or rel.get("target_code")
                or ""
            ).strip()
            target_name_val = rel.get("target_character_name") or rel.get("target_name")
            if not char_b_code and target_name_val:
                t_name = str(target_name_val).strip()
                if t_name in db_char_by_name:
                    char_b_code = db_char_by_name[t_name]["character_code"]
                else:
                    char_b_code = f"CHAR_{AssetProtocolHelper.normalize_token(t_name)}"
            if not char_a_code or not char_b_code or char_a_code == char_b_code:
                continue

            social_label = str(
                rel.get("social_label")
                or rel.get("surface_relation")
                or rel.get("relation_type")
                or "分集交互博弈关系"
            ).strip()
            tension_index = int(rel.get("tension_index") or rel.get("tension_level") or 65)
            drama_func = str(rel.get("drama_function") or "catalyst").strip()
            shared_props = rel.get("shared_history_props") or []
            shared_props_json = json.dumps(shared_props if isinstance(shared_props, list) else [str(shared_props)], ensure_ascii=False)
            raw_gap = rel.get("information_gap") or {"knows_truth_initially": False, "current_belief": f"第{curr_ep}集交锋认知", "reveal_condition": "剧情冲突揭晓"}
            gap_dict = raw_gap if isinstance(raw_gap, dict) else {"current_belief": str(raw_gap)}
            gap_json = json.dumps(gap_dict, ensure_ascii=False)
            knows_truth_initially = 1 if gap_dict.get("knows_truth_initially") else 0
            current_belief = str(gap_dict.get("current_belief") or "").strip()
            reveal_condition = str(gap_dict.get("reveal_condition") or "").strip()
            raw_swing = rel.get("swing_point") or {"can_defect": False, "defect_condition": None}
            swing_dict = raw_swing if isinstance(raw_swing, dict) else {"can_defect": False, "defect_condition": str(raw_swing)}
            swing_json = json.dumps(swing_dict, ensure_ascii=False)
            can_defect = 1 if swing_dict.get("can_defect") else 0
            defect_condition = str(swing_dict.get("defect_condition") or "").strip()

            existing_rel = fetch_one(
                db,
                "SELECT id FROM character_relationship WHERE drama_id = :drama_id AND character_a_code = :a_code AND character_b_code = :b_code",
                {"drama_id": drama_id, "a_code": char_a_code, "b_code": char_b_code},
            )
            if not existing_rel:
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
                        "raw": json.dumps(rel, ensure_ascii=False),
                        "now": now,
                    },
                )
                log.debug(
                    "【阶段 6 落库】[DEBUG 增量关系对] 成功建立增量角色双轨关系: %s -> %s (%s)",
                    char_a_code, char_b_code, social_label,
                )

        # 单集登场关联绑定 (episode_characters): 仅绑定自然人实体
        if episode_id and char_id:
            existing_ec = fetch_one(
                db,
                "SELECT 1 FROM episode_characters WHERE episode_id = :eid AND character_id = :cid",
                {"eid": episode_id, "cid": char_id},
            )
            if not existing_ec:
                db.execute(
                    text("INSERT INTO episode_characters (episode_id, character_id) VALUES (:eid, :cid)"),
                    {"eid": episode_id, "cid": char_id},
                )
                log.info(
                    "【阶段 6 落库】[步骤 2/6 集-角色绑定] 成功绑定第 %s 集与自然人角色: episode_id=%s, character_id=%s, 角色名=%s",
                    curr_ep, episode_id, char_id, char_name,
                )

        # Tier 2: 角色多形态生命周期造型从表 (character_stages)
        for st_code, st_data in ent["stages"].items():
            stage_name = st_data["stage_name"]
            parent_ref = st_data.get("parent_stage_ref")

            parent_stage_id = 0
            if isinstance(parent_ref, int) and parent_ref > 0:
                parent_stage_id = parent_ref
            elif isinstance(parent_ref, str) and parent_ref.strip():
                ref_str = parent_ref.strip()
                if ref_str in stage_db_ids_by_code:
                    parent_stage_id = stage_db_ids_by_code[ref_str]
                elif ref_str in stage_db_ids_by_name:
                    parent_stage_id = stage_db_ids_by_name[ref_str]
                else:
                    parent_row = fetch_one(
                        db,
                        """
                        SELECT id FROM character_stages
                        WHERE drama_id = :drama_id AND (stage_code = :ref OR stage_name = :ref)
                        """,
                        {"drama_id": drama_id, "ref": ref_str},
                    )
                    if parent_row:
                        parent_stage_id = parent_row["id"]
                    else:
                        unresolved_stage_parents.append({
                            "stage_code": st_code,
                            "parent_ref": ref_str,
                        })

            existing_stage = fetch_one(
                db,
                """
                SELECT id, stage_code, parent_stage_id
                FROM character_stages
                WHERE character_id = :char_id AND (
                    (stage_code IS NOT NULL AND stage_code != '' AND stage_code = :s_code)
                    OR stage_name = :s_name
                )
                """,
                {"char_id": char_id, "s_name": stage_name, "s_code": st_code},
            )

            if existing_stage:
                stage_db_id = existing_stage["id"]
                db.execute(
                    text("""
                        UPDATE character_stages
                        SET end_episode = CASE WHEN end_episode < :curr_ep THEN :curr_ep ELSE end_episode END,
                            stage_code = CASE WHEN (stage_code IS NULL OR stage_code = '') AND :stage_code != '' THEN :stage_code ELSE stage_code END,
                            parent_stage_id = CASE WHEN (parent_stage_id IS NULL OR parent_stage_id = 0) AND :parent_stage_id > 0 THEN :parent_stage_id ELSE parent_stage_id END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": stage_db_id,
                        "curr_ep": curr_ep,
                        "stage_code": st_code,
                        "parent_stage_id": parent_stage_id,
                        "now": now,
                    },
                )
            else:
                costume_desc = st_data.get("costume_description") or ""
                color_pal = st_data.get("color_palette")
                st_ins = db.execute(
                    text("""
                        INSERT INTO character_stages (
                            character_id, drama_id, stage_name, stage_code, parent_stage_id,
                            start_episode, end_episode, costume_description, color_palette,
                            is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :character_id, :drama_id, :stage_name, :stage_code, :parent_stage_id,
                            :start_episode, :end_episode, :costume_description, :color_palette,
                            1, :now, :now
                        )
                    """),
                    {
                        "character_id": char_id,
                        "drama_id": drama_id,
                        "stage_name": stage_name,
                        "stage_code": st_code,
                        "parent_stage_id": parent_stage_id,
                        "start_episode": curr_ep,
                        "end_episode": curr_ep,
                        "costume_description": costume_desc,
                        "color_palette": color_pal,
                        "now": now,
                    },
                )
                stage_db_id = getattr(st_ins, "lastrowid", None) or 1
                log.info(
                    "【阶段 6 落库】[Tier 2 角色形态从表] 建立角色 [%s] 造型形态: stage_id=%s, stage_code=%s, stage_name=%s, parent_stage_id=%s",
                    char_name, stage_db_id, st_code, stage_name, parent_stage_id,
                )

            stage_db_ids_by_code[st_code] = stage_db_id
            stage_db_ids_by_name[stage_name] = stage_db_id

            # Tier 3: 角色各形态切片视图从表 (character_stage_views)
            for v_type, v_info in st_data["views"].items():
                v_label = v_info.get("view_label") or v_type
                v_url = v_info.get("image_url")
                v_local_path = v_info.get("local_path")
                v_seedance = v_info.get("seedance2_asset_id")
                is_prim = v_info.get("is_primary", 1 if v_type == "main_portrait" else 0)

                # 阶段 6 资产拓扑图与四维提示词解构
                cur_v_key = AssetProtocolHelper.build_character_asset_key(char_code, st_code, v_type)
                dep = AssetProtocolHelper.get_dependency_rule(cur_v_key)

                # 提取当前角色自然人的归一化令牌，用于同一实体约束校验
                curr_char_token = AssetProtocolHelper.normalize_token(char_code or char_name)

                # -------------------------------------------------------------
                # 血统防污染守卫 (Same-Entity Lineage Guard):
                # 1. 仅当一阶主视觉肖像 (main_portrait 且 st_code in ('T1', 'STAGE_1')) 为自然人第一基准，
                #    锁定为文生图 (t2i)，父级必为 None，is_benchmark 为 1
                # 2. 二阶/三阶换装主肖像 (main_portrait 且 st_code 不在 ('T1', 'STAGE_1')) 必须是图生图 (i2i)，
                #    父级严格锚定至同角色 T1 主肖像，denoise_strength 为 0.35，is_benchmark 为 0
                # 3. 衍生切片 (full_body/4v_front/side/back/macro) 必须严格继承自同角色的基准肖像，
                #    若传入异构角色资产（如角色 B 的视图错误指向角色 A 的肖像），立即拦截纠偏！
                # -------------------------------------------------------------
                candidate_parent = v_info.get("parent_asset_key")
                parent_asset_key = None

                if v_type == "main_portrait" and st_code in ("T1", "STAGE_1"):
                    # 仅一阶基准肖像无父级，为文生图根节点
                    parent_asset_key = None
                    gen_mode = "t2i"
                    denoise_str = 0.0
                    log.debug(
                        "【阶段 6 视图血缘·一阶基准肖像锁定】角色 [%s](%s) 阶段 %s 视图 main_portrait 锁定为文生图根节点 (parent=None, gen_mode=t2i)",
                        char_name, char_code, st_code,
                    )
                else:
                    # 衍生视图 或 二阶/三阶换装主肖像：进行同实体血缘一致性强校验
                    if candidate_parent:
                        p_code, _, _ = extract_character_tokens(str(candidate_parent).strip())
                        parent_char_token = AssetProtocolHelper.normalize_token(p_code) if p_code else ""
                        if parent_char_token and parent_char_token == curr_char_token:
                            # 验证通过：父级资产确实归属于当前同一角色
                            parent_asset_key = candidate_parent
                            log.debug(
                                "【阶段 6 视图血缘·同角色校验通过】角色 [%s] 阶段 %s 视图 %s 成功关联同源父级: %s (token=%s)",
                                char_name, st_code, v_type, parent_asset_key, curr_char_token,
                            )
                        else:
                            # 发生跨角色资产张冠李戴污染，立即拦截纠偏
                            log.warning(
                                "【阶段 6 视图血缘·跨角色污染拦截】角色 [%s](token=%s) 阶段 %s 视图 %s 试图绑定异构父资产 [%s](parent_token=%s)，触发强制纠偏剔除！",
                                char_name, curr_char_token, st_code, v_type, candidate_parent, parent_char_token,
                            )

                    # 若未提供父级或因跨角色污染被剔除，基于 AssetProtocolHelper 进行同角色安全回退
                    if not parent_asset_key:
                        if v_type == "main_portrait":
                            # 二阶/三阶换装肖像回退到同角色 T1 主肖像
                            parent_asset_key = AssetProtocolHelper.build_character_asset_key(char_code, "T1", "main_portrait")
                        elif dep and dep.parent_asset_key:
                            parent_asset_key = dep.parent_asset_key
                        else:
                            parent_asset_key = AssetProtocolHelper.build_character_asset_key(char_code, st_code, "main_portrait")
                        log.debug(
                            "【阶段 6 视图血缘·安全回退生效】角色 [%s] 阶段 %s 视图 %s 自动回退为同角色标准底模: %s",
                            char_name, st_code, v_type, parent_asset_key,
                        )

                    gen_mode = v_info.get("generation_mode") or (dep.generation_mode if dep else "i2i")
                    if gen_mode == "t2i":
                        # 衍生视图与二阶/三阶换装肖像不可为纯文生图，修正为 i2i
                        gen_mode = "i2i" if (not dep or dep.generation_mode == "t2i") else dep.generation_mode

                    raw_denoise = v_info.get("denoise_strength")
                    if raw_denoise is None and dep:
                        raw_denoise = dep.denoise_strength
                    if raw_denoise is None or float(raw_denoise) == 0.0:
                        raw_denoise = 0.35 if v_type == "main_portrait" else 0.45
                    denoise_str = float(raw_denoise)

                ctrl_type = v_info.get("control_type") or (dep.control_type if dep else None)
                is_bench = 1 if (v_type == "main_portrait" and st_code in ("T1", "STAGE_1")) else 0

                raw_app = ent.get("appearance") or ""
                costume_desc = st_data.get("costume_description") or ""
                id_prompt = v_info.get("identity_prompt") or PromptSynthesizer.extract_identity_face_anchor(raw_app)
                delta_prompt = v_info.get("delta_prompt") or (f"{costume_desc}, {v_label}" if costume_desc else v_label)
                v_neg_prompt = v_info.get("negative_prompt") or PromptSynthesizer.get_negative_prompt("character")
                if v_info.get("image_prompt"):
                    v_prompt = str(v_info["image_prompt"])
                else:
                    syn = PromptSynthesizer.synthesize_character_view_prompt(
                        id_prompt,
                        view_type=v_type,
                        costume_prompt=costume_desc,
                    )
                    v_prompt = syn.visual_prompt
                    if not v_info.get("delta_prompt"):
                        delta_prompt = syn.delta_prompt

                v_info["parent_asset_key"] = parent_asset_key
                v_info["generation_mode"] = gen_mode
                v_info["denoise_strength"] = denoise_str
                v_info["control_type"] = ctrl_type
                v_info["is_benchmark"] = is_bench
                v_info["identity_prompt"] = id_prompt
                v_info["delta_prompt"] = delta_prompt
                v_info["negative_prompt"] = v_neg_prompt
                v_info["image_prompt"] = v_prompt
                v_info.setdefault("asset_keys", [])
                if cur_v_key not in v_info["asset_keys"]:
                    v_info["asset_keys"].append(cur_v_key)

                existing_view = fetch_one(
                    db,
                    """
                    SELECT id FROM character_stage_views
                    WHERE character_stage_id = :st_id AND view_type = :v_type
                    """,
                    {"st_id": stage_db_id, "v_type": v_type},
                )

                if existing_view:
                    view_db_id = existing_view["id"]
                    db.execute(
                        text("""
                            UPDATE character_stage_views
                            SET asset_key = CASE WHEN :asset_key IS NOT NULL AND :asset_key != '' THEN :asset_key ELSE asset_key END,
                                view_label = :view_label,
                                parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                                generation_mode = CASE WHEN :generation_mode IS NOT NULL AND :generation_mode != '' THEN :generation_mode ELSE generation_mode END,
                                denoise_strength = CASE WHEN :denoise_strength IS NOT NULL THEN :denoise_strength ELSE denoise_strength END,
                                control_type = CASE WHEN :control_type IS NOT NULL AND :control_type != '' THEN :control_type ELSE control_type END,
                                is_benchmark = CASE WHEN :is_benchmark = 1 THEN 1 ELSE is_benchmark END,
                                identity_prompt = CASE WHEN (identity_prompt IS NULL OR identity_prompt = '') AND :identity_prompt != '' THEN :identity_prompt ELSE identity_prompt END,
                                delta_prompt = CASE WHEN (delta_prompt IS NULL OR delta_prompt = '') AND :delta_prompt != '' THEN :delta_prompt ELSE delta_prompt END,
                                image_prompt = CASE WHEN (image_prompt IS NULL OR image_prompt = '') AND :prompt != '' THEN :prompt ELSE image_prompt END,
                                negative_prompt = CASE WHEN negative_prompt IS NULL AND :neg_prompt IS NOT NULL THEN :neg_prompt ELSE negative_prompt END,
                                image_url = CASE WHEN image_url IS NULL AND :image_url IS NOT NULL THEN :image_url ELSE image_url END,
                                local_path = CASE WHEN local_path IS NULL AND :local_path IS NOT NULL THEN :local_path ELSE local_path END,
                                seedance2_asset_id = CASE WHEN seedance2_asset_id IS NULL AND :seedance IS NOT NULL THEN :seedance ELSE seedance2_asset_id END,
                                is_primary = :is_primary,
                                updated_at = :now
                            WHERE id = :id
                        """),
                        {
                            "id": view_db_id,
                            "asset_key": cur_v_key,
                            "view_label": v_label,
                            "parent_asset_key": parent_asset_key,
                            "generation_mode": gen_mode,
                            "denoise_strength": denoise_str,
                            "control_type": ctrl_type,
                            "is_benchmark": is_bench,
                            "identity_prompt": id_prompt,
                            "delta_prompt": delta_prompt,
                            "prompt": v_prompt,
                            "neg_prompt": v_neg_prompt,
                            "image_url": v_url,
                            "local_path": v_local_path,
                            "seedance": v_seedance,
                            "is_primary": is_prim,
                            "now": now,
                        },
                    )
                else:
                    vw_ins = db.execute(
                        text("""
                            INSERT INTO character_stage_views (
                                character_stage_id, asset_key, view_type, view_label,
                                parent_asset_key, generation_mode, denoise_strength, control_type, is_benchmark,
                                identity_prompt, delta_prompt, image_prompt, negative_prompt,
                                image_url, local_path, seedance2_asset_id,
                                is_primary, created_at, updated_at
                            ) VALUES (
                                :st_id, :asset_key, :v_type, :view_label,
                                :parent_asset_key, :generation_mode, :denoise_strength, :control_type, :is_benchmark,
                                :identity_prompt, :delta_prompt, :prompt, :neg_prompt,
                                :image_url, :local_path, :seedance,
                                :is_primary, :now, :now
                            )
                        """),
                        {
                            "st_id": stage_db_id,
                            "asset_key": cur_v_key,
                            "v_type": v_type,
                            "view_label": v_label,
                            "parent_asset_key": parent_asset_key,
                            "generation_mode": gen_mode,
                            "denoise_strength": denoise_str,
                            "control_type": ctrl_type,
                            "is_benchmark": is_bench,
                            "identity_prompt": id_prompt,
                            "delta_prompt": delta_prompt,
                            "prompt": v_prompt,
                            "neg_prompt": v_neg_prompt,
                            "image_url": v_url,
                            "local_path": v_local_path,
                            "seedance": v_seedance,
                            "is_primary": is_prim,
                            "now": now,
                        },
                    )
                    view_db_id = getattr(vw_ins, "lastrowid", None) or 1
                    log.info(
                        "【阶段 6 落库】[Tier 3 角色切片视图] 写入形态切片: view_id=%s, stage_id=%s, view_type=%s, is_benchmark=%s, is_primary=%s",
                        view_db_id, stage_db_id, v_type, is_bench, is_prim,
                    )

                # 记录 asset_key 到实体/阶段/切片的元数据反向映射
                for ak in v_info.get("asset_keys", []):
                    if ak:
                        asset_character_meta_map[ak] = {
                            "character_id": char_id,
                            "character_name": char_name,
                            "character_stage_id": stage_db_id,
                            "stage_code": st_code,
                            "view_type": v_type,
                            "is_master_portrait": (is_prim == 1),
                        }

    # 二次遍历解析可能因先后次序未解析的 parent_stage_id（避免 MySQL 1093 同表更新子查询限制）
    for item in unresolved_stage_parents:
        s_code = item["stage_code"]
        p_ref = item["parent_ref"]
        p_row = fetch_one(
            db,
            """
            SELECT id FROM character_stages
            WHERE drama_id = :drama_id AND (stage_code = :p_ref OR stage_name = :p_ref)
            LIMIT 1
            """,
            {"drama_id": drama_id, "p_ref": p_ref},
        )
        if p_row and p_row.get("id"):
            db.execute(
                text("""
                    UPDATE character_stages
                    SET parent_stage_id = :parent_id
                    WHERE drama_id = :drama_id AND stage_code = :s_code AND (parent_stage_id IS NULL OR parent_stage_id = 0)
                """),
                {"drama_id": drama_id, "s_code": s_code, "parent_id": p_row["id"]},
            )
            log.debug("【阶段 6 落库】[DEBUG 角色造型二次解析] 关联 parent_stage_id: stage_code=%s, parent_ref=%s, parent_id=%s", s_code, p_ref, p_row["id"])

    # -------------------------------------------------------------------------
    # 3. 角色母音频卡片与专属音色配置同步 (character_voice_profiles 表)
    # -------------------------------------------------------------------------
    all_voice_entries: list[dict[str, Any]] = []

    # 3.1 聚合所有来源的既有音色资产 (显式入参 voice_cards + newly_generated_assets + reused_assets_data)
    for vc in voice_cards:
        d = _dump_or_dict(vc)
        if isinstance(d, dict):
            all_voice_entries.append(d)

    for item in newly_generated_assets:
        d = _dump_or_dict(item)
        if isinstance(d, dict):
            aid = str(d.get("asset_id") or d.get("asset_key") or "").upper()
            cat = str(d.get("type") or d.get("category") or "").lower()
            if aid.startswith("VOICE_") or cat in ("voice", "audio"):
                all_voice_entries.append(d)

    for item in reused_assets_data:
        d = _dump_or_dict(item)
        if isinstance(d, dict):
            aid = str(d.get("asset_id") or d.get("asset_key") or "").upper()
            cat = str(d.get("type") or d.get("category") or "").lower()
            if aid.startswith("VOICE_") or cat in ("voice", "audio"):
                all_voice_entries.append(d)

    # 3.2 识别并标记已覆盖音色卡的角色实体 (使用 find_canonical_entity 精确多维归属)
    covered_char_keys: set[str] = set()
    for v_entry in all_voice_entries:
        if not isinstance(v_entry, dict):
            continue
        v_name = str(v_entry.get("character_name") or v_entry.get("name") or "").strip()
        v_code = str(v_entry.get("character_code") or v_entry.get("character_id") or v_entry.get("char_id") or "").strip()
        vid = str(v_entry.get("master_voice_id") or v_entry.get("voice_id") or v_entry.get("asset_id") or "").strip()

        matched_ent = (
            find_canonical_entity(v_name, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(v_code, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(vid, canonical_map, canonical_by_name, canonical_by_code)
        )
        if matched_ent:
            covered_char_keys.add(matched_ent["char_name"].lower())
            covered_char_keys.add(matched_ent["char_code"].upper())
            # 回填标准规范角色名与角色代码，避免后续处理遗失
            v_entry.setdefault("character_name", matched_ent["char_name"])
            v_entry.setdefault("character_code", matched_ent["char_code"])
            log.debug(
                "【阶段 6 落库·音色实体映射】既有音色卡归属成功: 角色=%s (%s), voice_id=%s",
                matched_ent["char_name"], matched_ent["char_code"], vid,
            )

    # 3.3 全角色 100% 覆盖差集保底构建 (Full Character Voice Card Guarantee)
    # 核心目标：解决出场配角/小角色/未开口角色在主音色母卡抽取中被遗漏的问题
    missing_voice_characters: list[dict[str, Any]] = []
    for ent in canonical_map.values():
        c_name = ent["char_name"]
        c_code = ent["char_code"]
        if c_name.lower() not in covered_char_keys and c_code.upper() not in covered_char_keys:
            missing_voice_characters.append(ent)

    if missing_voice_characters:
        log.info(
            "【阶段 6 落库·全角色音色保底】发现 %d 位本集出场/建档角色缺失主音色母卡，开始全自动合成广播级 11 维母音卡...",
            len(missing_voice_characters),
        )
        default_emotion_rules_dict = {
            "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
            "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
            "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
            "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
            "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
            "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
        }
        for ent in missing_voice_characters:
            c_name = ent["char_name"]
            c_code = ent["char_code"]
            tok = AssetProtocolHelper.normalize_token(c_code or c_name)
            master_voice_id = f"VOICE_{tok}_T1_MASTER"
            timbre = ent.get("voice_style") or "中性沉稳自然原声"

            # 基于角色 11 维人设自动生成广播级 5 维 TTS 提示词
            char_acou = ent.get("acoustic_persona")
            if isinstance(char_acou, str) and char_acou.strip():
                try:
                    char_acou = json.loads(char_acou)
                except Exception:
                    char_acou = None

            synth_tts_prompt = synthesize_voice_prompt(
                char_name=c_name,
                gender=str(ent.get("gender") or "male"),
                perceived_age=str(ent.get("perceived_age") or "30岁"),
                role=str(ent.get("role") or "配角"),
                personality=str(ent.get("personality") or ""),
                timbre=timbre,
                voice_style=timbre,
                acoustic_persona=char_acou,
            )
            # 生成原型纯净示范台词
            sample_line = f"我是{c_name}。在这局棋盘上，没有人能置身事外。"

            synth_card = {
                "character_code": c_code,
                "character_name": c_name,
                "character_id": c_code,
                "master_voice_id": master_voice_id,
                "master_voice_key": master_voice_id,
                "timbre": timbre,
                "timbre_archetype": timbre or "沉稳磁性声线",
                "master_tts_prompt": synth_tts_prompt,
                "voice_prompt": synth_tts_prompt,
                "master_sample_text": sample_line,
                "script_monologue_source": sample_line,
                "speed_ratio": 1.0,
                "pitch_ratio": 1.0,
                "is_master_card": 1,
                "synthesis_status": "pending",
                "emotion_rules": default_emotion_rules_dict,
            }
            all_voice_entries.append(synth_card)
            log.info(
                "【阶段 6 落库·全角色音色保底】已为出场配角/未开口角色 [%s](%s) 合成母音卡: voice_id=%s, 音色=%s",
                c_name, c_code, master_voice_id, timbre,
            )

    log.info(
        "【阶段 6 落库·声音档案总计】本集待持久化音色卡总数=%d (出场角色总数=%d, 达到 100%% 覆盖)",
        len(all_voice_entries), len(canonical_map),
    )

    for v_entry in all_voice_entries:
        if not isinstance(v_entry, dict):
            continue
        raw_name = str(v_entry.get("character_name") or v_entry.get("name") or "").strip()
        v_name = clean_character_name(raw_name) or raw_name
        v_code = str(v_entry.get("character_code") or v_entry.get("char_id") or "").strip()
        voice_id_val = str(v_entry.get("master_voice_id") or v_entry.get("voice_id") or v_entry.get("asset_id") or "").strip()
        timbre = str(v_entry.get("timbre") or "").strip()
        v_prompt = str(v_entry.get("master_tts_prompt") or v_entry.get("voice_prompt") or v_entry.get("visual_grounding_quote") or v_entry.get("description") or "").strip()
        voice_file_path = str(v_entry.get("voice_file_path") or "").strip()

        # 查找对应角色自然人 ID 及文学实体配置
        target_char_id = None
        target_char_ent = (
            find_canonical_entity(v_code, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(v_name, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(voice_id_val, canonical_map, canonical_by_name, canonical_by_code)
        )

        # 1) 若从 canonical_map 内存中精确命中
        if target_char_ent:
            target_char_id = target_char_ent.get("db_id")
            if not v_name:
                v_name = target_char_ent["char_name"]
            if not v_code:
                v_code = target_char_ent["char_code"]
            log.debug(
                "【阶段 6 声音落库·内存命中】音色卡 [%s] 命中实体: 姓名=%s, ID=%s, 代号=%s",
                voice_id_val, v_name, target_char_id, v_code,
            )

        # 2) 若在 canonical_map 中未直接命中，从 DB 角色缓存或数据库实时查询
        if not target_char_id and (v_name or v_code):
            clean_v_name = clean_character_name(v_name)
            char_row = fetch_one(
                db,
                """
                SELECT id, name, character_code, gender, perceived_age, role, personality, appearance, voice_style, acoustic_persona
                FROM characters
                WHERE drama_id = :drama_id AND (
                    name = :name OR character_code = :code
                    OR name = :c_name OR character_code = :c_name
                )
                LIMIT 1
                """,
                {"drama_id": drama_id, "name": v_name, "code": v_code or v_name, "c_name": clean_v_name or v_name},
            )
            if char_row:
                target_char_id = char_row["id"]
                if not v_name:
                    v_name = char_row["name"]
                if not target_char_ent:
                    target_char_ent = dict(char_row)
                log.debug(
                    "【阶段 6 声音落库·DB实时命中】音色卡 [%s] 从DB命中实体: 姓名=%s, ID=%s",
                    voice_id_val, v_name, target_char_id,
                )

        # 3) 若音色 (timbre) 为空，尝试从关联角色中回填 voice_style
        if not timbre and target_char_ent:
            timbre = str(target_char_ent.get("voice_style") or "").strip()
        if not timbre:
            timbre = "中性沉稳自然原声"

        # 4) 生成或补全声音生成提示词 (voice_prompt / master_tts_prompt)
        # 若传入的提示词为空，或过短（缺乏具体参数），自动调用 synthesize_voice_prompt 生成 5 维广播级 TTS 提示词
        if not v_prompt or len(v_prompt) < 25 or "【" not in v_prompt:
            char_gender = target_char_ent.get("gender") if target_char_ent else "male"
            char_age = target_char_ent.get("perceived_age") if target_char_ent else "30岁"
            char_role = target_char_ent.get("role") if target_char_ent else "配角"
            char_pers = target_char_ent.get("personality") if target_char_ent else ""
            char_acou = target_char_ent.get("acoustic_persona") if target_char_ent else None
            if isinstance(char_acou, str) and char_acou.strip():
                try:
                    char_acou = json.loads(char_acou)
                except Exception:
                    char_acou = None

            synth_vp = synthesize_voice_prompt(
                char_name=v_name,
                gender=str(char_gender or "male"),
                perceived_age=str(char_age or "30岁"),
                role=str(char_role or "配角"),
                personality=str(char_pers or ""),
                timbre=timbre,
                voice_style=str(target_char_ent.get("voice_style") or "") if target_char_ent else "",
                acoustic_persona=char_acou,
            )
            if v_prompt and v_prompt != synth_vp:
                v_prompt = f"{synth_vp} 【台词语气参考】{v_prompt}"
            else:
                v_prompt = synth_vp

        # 5) 判断是否为全剧母音卡 (is_master_card: 1)
        if not voice_id_val:
            tok = AssetProtocolHelper.normalize_token(v_code or v_name)
            voice_id_val = f"VOICE_{tok}_T1_MASTER"

        master_voice_key = str(v_entry.get("master_voice_key") or v_entry.get("master_voice_id") or voice_id_val).strip()
        character_code_val = str(
            v_code
            or (target_char_ent.get("char_code") or target_char_ent.get("character_code") if target_char_ent else "")
            or f"CHAR_{AssetProtocolHelper.normalize_token(v_name)}"
        ).strip()

        raw_sample_text = str(
            v_entry.get("master_sample_text")
            or v_entry.get("script_monologue_source")
            or ""
        ).strip()
        # 剥离剧本舞台提示括号，保证 TTS 母音朗读样本绝对纯净
        clean_sample_text = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", raw_sample_text).strip()
        if not clean_sample_text:
            clean_sample_text = f"我是{v_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
        script_monologue_source = str(v_entry.get("script_monologue_source") or clean_sample_text).strip()

        timbre_archetype = str(v_entry.get("timbre_archetype") or timbre or "沉稳磁性声线").strip()
        vocal_position = str(v_entry.get("vocal_position") or "胸腔与口腔平衡共鸣").strip()
        vocal_flaws = str(v_entry.get("vocal_flaws") or "句尾带真实微弱换气呼吸音").strip()
        tts_provider = str(v_entry.get("tts_provider") or "minimax").strip()
        tts_model = str(v_entry.get("tts_model") or "speech-02-hd").strip()
        provider_voice_id = str(v_entry.get("provider_voice_id") or "male-qn-qingse").strip()

        raw_tw = v_entry.get("timber_weights") or v_entry.get("timber_weights_json")
        if isinstance(raw_tw, (list, dict)):
            timber_weights_json = json.dumps(raw_tw, ensure_ascii=False)
        elif isinstance(raw_tw, str) and raw_tw.strip():
            timber_weights_json = raw_tw.strip()
        else:
            timber_weights_json = json.dumps([{"voice_id": provider_voice_id, "weight": 100}], ensure_ascii=False)

        sample_audio_path = str(v_entry.get("sample_audio_path") or "").strip()
        sample_audio_url = str(v_entry.get("sample_audio_url") or v_entry.get("reference_audio_url") or "").strip()
        try:
            sample_duration_sec = float(v_entry.get("sample_duration_sec") or 0.0)
        except (ValueError, TypeError):
            sample_duration_sec = 0.0
        synthesis_status = str(v_entry.get("synthesis_status") or ("CERTIFIED" if sample_audio_url else "pending")).strip()
        semantic_hash_val = str(
            v_entry.get("semantic_hash")
            or hashlib.sha256(f"{master_voice_key}|{v_prompt}|{clean_sample_text}".encode("utf-8")).hexdigest()[:16]
        ).strip()

        is_master_card = 1 if (
            v_entry.get("is_master_card") in (1, True, "1", "true")
            or "master_voice_id" in v_entry
            or ("VOICE_" in voice_id_val and "_MASTER" in voice_id_val)
            or any(str(vc.get("master_voice_id") or vc.get("voice_id")) == voice_id_val for vc in voice_cards)
            or (target_char_id and not fetch_one(
                db,
                "SELECT 1 FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 1 AND deleted_at IS NULL",
                {"cid": target_char_id},
            ))
        ) else 0

        try:
            speed_ratio = float(v_entry.get("speed_ratio") or 1.0)
        except (ValueError, TypeError):
            speed_ratio = 1.0

        try:
            pitch_ratio = float(v_entry.get("pitch_ratio") or 1.0)
        except (ValueError, TypeError):
            pitch_ratio = 1.0

        raw_rules = v_entry.get("emotion_rules")
        if isinstance(raw_rules, (list, dict)):
            emotion_rules_json = json.dumps(raw_rules, ensure_ascii=False)
        elif raw_rules:
            emotion_rules_json = _ensure_valid_json_str(raw_rules, "{}", wrap_key="default")
        else:
            emotion_rules_json = json.dumps({
                "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
                "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
                "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
                "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
                "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
                "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
            }, ensure_ascii=False)

        # 检查是否已有声音档案: 优先按 voice_id / master_voice_key 精确匹配；若未匹配到则按 (character_id/name + is_master_card) 匹配
        existing_vp = None
        if voice_id_val:
            existing_vp = fetch_one(
                db,
                "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND (voice_id = :v_id OR master_voice_key = :m_key) AND deleted_at IS NULL",
                {"drama_id": drama_id, "v_id": voice_id_val, "m_key": master_voice_key},
            )
        if not existing_vp and is_master_card == 1:
            if target_char_id:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 1 AND deleted_at IS NULL",
                    {"cid": target_char_id},
                )
            if not existing_vp and v_name:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND character_name = :v_name AND is_master_card = 1 AND deleted_at IS NULL",
                    {"drama_id": drama_id, "v_name": v_name},
                )
        elif not existing_vp and is_master_card == 0 and not voice_id_val:
            if target_char_id:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 0 AND deleted_at IS NULL",
                    {"cid": target_char_id},
                )
            if not existing_vp and v_name:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND character_name = :v_name AND is_master_card = 0 AND deleted_at IS NULL",
                    {"drama_id": drama_id, "v_name": v_name},
                )

        if existing_vp:
            vp_id = existing_vp["id"]
            db.execute(
                text("""
                    UPDATE character_voice_profiles
                    SET character_id = COALESCE(:cid, character_id),
                        character_code = CASE WHEN :char_code != '' THEN :char_code ELSE character_code END,
                        character_name = CASE WHEN :v_name != '' THEN :v_name ELSE character_name END,
                        voice_id = CASE WHEN :v_id != '' THEN :v_id ELSE voice_id END,
                        master_voice_key = CASE WHEN :m_key != '' THEN :m_key ELSE master_voice_key END,
                        timbre = CASE WHEN :timbre != '' THEN :timbre ELSE timbre END,
                        timbre_archetype = CASE WHEN :timbre_archetype != '' THEN :timbre_archetype ELSE timbre_archetype END,
                        vocal_position = CASE WHEN :vocal_position != '' THEN :vocal_position ELSE vocal_position END,
                        vocal_flaws = CASE WHEN :vocal_flaws != '' THEN :vocal_flaws ELSE vocal_flaws END,
                        voice_prompt = CASE WHEN :v_prompt != '' THEN :v_prompt ELSE voice_prompt END,
                        master_tts_prompt = CASE WHEN :v_prompt != '' THEN :v_prompt ELSE master_tts_prompt END,
                        master_sample_text = CASE WHEN :sample_text != '' THEN :sample_text ELSE master_sample_text END,
                        script_monologue_source = CASE WHEN :mono_source != '' THEN :mono_source ELSE script_monologue_source END,
                        tts_provider = CASE WHEN :tts_provider != '' THEN :tts_provider ELSE tts_provider END,
                        tts_model = CASE WHEN :tts_model != '' THEN :tts_model ELSE tts_model END,
                        provider_voice_id = CASE WHEN :provider_voice_id != '' THEN :provider_voice_id ELSE provider_voice_id END,
                        timber_weights_json = CASE WHEN :timber_weights_json != '' THEN :timber_weights_json ELSE timber_weights_json END,
                        speed_ratio = :speed_ratio,
                        pitch_ratio = :pitch_ratio,
                        emotion_rules = CASE WHEN :emotion_rules != '[]' THEN :emotion_rules ELSE emotion_rules END,
                        is_master_card = CASE WHEN :is_master_card = 1 THEN 1 ELSE is_master_card END,
                        reference_audio_url = CASE WHEN :sample_audio_url != '' THEN :sample_audio_url ELSE reference_audio_url END,
                        sample_audio_path = CASE WHEN :sample_audio_path != '' THEN :sample_audio_path ELSE sample_audio_path END,
                        sample_audio_url = CASE WHEN :sample_audio_url != '' THEN :sample_audio_url ELSE sample_audio_url END,
                        sample_duration_sec = CASE WHEN :sample_duration_sec > 0 THEN :sample_duration_sec ELSE sample_duration_sec END,
                        synthesis_status = CASE WHEN :sample_audio_url != '' THEN 'CERTIFIED' ELSE COALESCE(synthesis_status, :synthesis_status) END,
                        semantic_hash = CASE WHEN :semantic_hash != '' THEN :semantic_hash ELSE semantic_hash END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": vp_id,
                    "cid": target_char_id,
                    "char_code": character_code_val,
                    "v_name": v_name,
                    "v_id": voice_id_val,
                    "m_key": master_voice_key,
                    "timbre": timbre,
                    "timbre_archetype": timbre_archetype,
                    "vocal_position": vocal_position,
                    "vocal_flaws": vocal_flaws,
                    "v_prompt": v_prompt,
                    "sample_text": clean_sample_text,
                    "mono_source": script_monologue_source,
                    "tts_provider": tts_provider,
                    "tts_model": tts_model,
                    "provider_voice_id": provider_voice_id,
                    "timber_weights_json": timber_weights_json,
                    "speed_ratio": speed_ratio,
                    "pitch_ratio": pitch_ratio,
                    "emotion_rules": emotion_rules_json,
                    "is_master_card": is_master_card,
                    "sample_audio_path": sample_audio_path,
                    "sample_audio_url": sample_audio_url,
                    "sample_duration_sec": sample_duration_sec,
                    "synthesis_status": synthesis_status,
                    "semantic_hash": semantic_hash_val,
                    "now": now,
                },
            )
            log.info(
                "【阶段 6 落库】[步骤 3/6 声音档案] 更新角色 [%s] V2 声音档案: profile_id=%s, master_voice_key=%s, 音色原型=%s, 状态=%s",
                v_name, vp_id, master_voice_key, timbre_archetype, synthesis_status,
            )
            log.debug(
                "【阶段 6 落库】[DEBUG 音色卡 V2] 更新详情: char_code=%s, provider=%s/%s(%s), 试音台词=%s",
                character_code_val, tts_provider, tts_model, provider_voice_id, clean_sample_text[:30],
            )
        else:
            ins_vp = db.execute(
                text("""
                    INSERT INTO character_voice_profiles (
                        character_id, drama_id, character_code, character_name,
                        voice_id, master_voice_key, voice_prompt, master_tts_prompt,
                        master_sample_text, script_monologue_source,
                        timbre, timbre_archetype, vocal_position, vocal_flaws,
                        tts_provider, tts_model, provider_voice_id, timber_weights_json,
                        speed_ratio, pitch_ratio, emotion_rules,
                        is_master_card, reference_audio_url,
                        sample_audio_path, sample_audio_url, sample_duration_sec,
                        synthesis_status, semantic_hash,
                        status, created_at, updated_at
                    ) VALUES (
                        :cid, :drama_id, :char_code, :v_name,
                        :v_id, :m_key, :v_prompt, :v_prompt,
                        :sample_text, :mono_source,
                        :timbre, :timbre_archetype, :vocal_position, :vocal_flaws,
                        :tts_provider, :tts_model, :provider_voice_id, :timber_weights_json,
                        :speed_ratio, :pitch_ratio, :emotion_rules,
                        :is_master_card, :sample_audio_url,
                        :sample_audio_path, :sample_audio_url, :sample_duration_sec,
                        :synthesis_status, :semantic_hash,
                        'active', :now, :now
                    )
                """),
                {
                    "cid": target_char_id,
                    "drama_id": drama_id,
                    "char_code": character_code_val,
                    "v_name": v_name,
                    "v_id": voice_id_val,
                    "m_key": master_voice_key,
                    "v_prompt": v_prompt,
                    "sample_text": clean_sample_text,
                    "mono_source": script_monologue_source,
                    "timbre": timbre,
                    "timbre_archetype": timbre_archetype,
                    "vocal_position": vocal_position,
                    "vocal_flaws": vocal_flaws,
                    "tts_provider": tts_provider,
                    "tts_model": tts_model,
                    "provider_voice_id": provider_voice_id,
                    "timber_weights_json": timber_weights_json,
                    "speed_ratio": speed_ratio,
                    "pitch_ratio": pitch_ratio,
                    "emotion_rules": emotion_rules_json,
                    "is_master_card": is_master_card,
                    "sample_audio_path": sample_audio_path,
                    "sample_audio_url": sample_audio_url,
                    "sample_duration_sec": sample_duration_sec,
                    "synthesis_status": synthesis_status,
                    "semantic_hash": semantic_hash_val,
                    "now": now,
                },
            )
            log.info(
                "【阶段 6 落库】[步骤 3/6 声音档案] 新增角色 [%s] V2 声音母卡入库: profile_id=%s, master_voice_key=%s, 音色原型=%s",
                v_name, getattr(ins_vp, "lastrowid", None), master_voice_key, timbre_archetype,
            )
            log.debug(
                "【阶段 6 落库】[DEBUG 音色卡 V2] 新增详情: char_code=%s, provider=%s/%s(%s), 试音台词=%s",
                character_code_val, tts_provider, tts_model, provider_voice_id, clean_sample_text[:30],
            )

        # 同时确保 characters 表中该角色的 voice_style 不为空
        if target_char_id and timbre:
            db.execute(
                text("""
                    UPDATE characters
                    SET voice_style = CASE WHEN voice_style IS NULL OR voice_style = '' THEN :timbre ELSE voice_style END,
                        updated_at = :now
                    WHERE id = :cid
                """),
                {"cid": target_char_id, "timbre": timbre, "now": now},
            )

    # -------------------------------------------------------------------------
    # 4. 空间场景与气候做旧层增量对齐 (scenes, scene_zones, scene_weathering_views)
    # -------------------------------------------------------------------------
    # 合并新发现场景项与新生成资产中的场景项
    for new_scene in newly_discovered_scenes:
        ns_dict = _dump_or_dict(new_scene)
        if isinstance(ns_dict, dict) and ns_dict not in environments_manifest:
            environments_manifest.append(ns_dict)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or "")
        if (cat in ("environment", "scene") or aid.startswith("ENV_")) and n_dict not in environments_manifest:
            environments_manifest.append(n_dict)

    for env_raw in environments_manifest:
        env = _dump_or_dict(env_raw)
        if not isinstance(env, dict):
            continue
        loc = str(env.get("scene_name") or env.get("location") or env.get("location_name") or "").strip()
        if not loc:
            continue

        raw_s_code = str(env.get("scene_code") or env.get("code") or "").strip()
        s_code = raw_s_code if raw_s_code else AssetProtocolHelper.normalize_token(loc)
        bench_scene_key = env.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_scene(s_code)
        time_lighting = str(env.get("time_lighting") or env.get("time_and_lighting") or "").strip()
        acoustic_resistance = str(env.get("acoustic_resistance") or "").strip()

        existing_scene = fetch_one(
            db,
            "SELECT id FROM scenes WHERE drama_id = :drama_id AND (scene_code = :s_code OR location = :loc)",
            {"drama_id": drama_id, "s_code": s_code, "loc": loc},
        )
        if existing_scene:
            scene_id = existing_scene["id"]
            db.execute(
                text("""
                    UPDATE scenes
                    SET scene_code = CASE WHEN (scene_code IS NULL OR scene_code = '') AND :s_code != '' THEN :s_code ELSE scene_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {"id": scene_id, "s_code": s_code, "bench_key": bench_scene_key, "now": now},
            )
        else:
            scene_ins = db.execute(
                text("""
                    INSERT INTO scenes (
                        drama_id, episode_id, scene_code, benchmark_asset_key, location, time, prompt,
                        status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :episode_id, :scene_code, :benchmark_asset_key, :location, :time, :prompt,
                        'draft', :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "episode_id": episode_id,
                    "scene_code": s_code,
                    "benchmark_asset_key": bench_scene_key,
                    "location": loc,
                    "time": time_lighting,
                    "prompt": env.get("visual_prompt") or "",
                    "now": now,
                },
            )
            scene_id = getattr(scene_ins, "lastrowid", None) or 1
            log.info(
                "【阶段 6 落库】[步骤 4/6 场景] 登记第 %s 集新场景: scene_id=%s, 代号=%s, 地点=%s, 基准键=%s",
                curr_ep, scene_id, s_code, loc, bench_scene_key,
            )

        # 4.1 动态提取与规范化场景子空间区域 (Tier 2 scene_zones)
        zones_data: list[dict[str, Any]] = []
        raw_zones = env.get("zones") or env.get("sub_zones")
        if isinstance(raw_zones, list) and raw_zones:
            for z_idx, z_val in enumerate(raw_zones, start=1):
                if isinstance(z_val, dict):
                    z_code = str(z_val.get("zone_code") or (f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}")).strip().upper()
                    z_name = str(z_val.get("zone_name") or z_val.get("name") or f"{loc}子区域{z_idx}").strip()
                    z_tl = str(z_val.get("time_lighting") or time_lighting).strip()
                    z_ar = str(z_val.get("acoustic_resistance") or acoustic_resistance).strip()
                    zones_data.append({
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                    })
                elif isinstance(z_val, str) and z_val.strip():
                    z_name = z_val.strip()
                    z_code = f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}"
                    zones_data.append({
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": time_lighting,
                        "acoustic_resistance": acoustic_resistance,
                    })
        elif isinstance(raw_zones, dict):
            for z_idx, (z_k, z_v) in enumerate(raw_zones.items(), start=1):
                z_name = str(z_k).strip()
                z_code = f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}"
                zones_data.append({
                    "zone_code": z_code,
                    "zone_name": z_name,
                    "time_lighting": str(z_v).strip() if isinstance(z_v, str) else time_lighting,
                    "acoustic_resistance": acoustic_resistance,
                })

        # 若未提供显式子区域列表，优先提取 zone_name，兜底保持向后兼容（杜绝无条件写死）
        if not zones_data:
            dyn_z_name = str(env.get("zone_name") or "核心主活动区").strip()
            dyn_z_code = str(env.get("zone_code") or "Z01").strip().upper()
            zones_data.append({
                "zone_code": dyn_z_code,
                "zone_name": dyn_z_name,
                "time_lighting": time_lighting,
                "acoustic_resistance": acoustic_resistance,
            })

        primary_zone_id: Optional[int] = None
        for z_entry in zones_data:
            z_code = z_entry["zone_code"]
            z_name = z_entry["zone_name"]
            z_tl = z_entry["time_lighting"]
            z_ar = z_entry["acoustic_resistance"]

            existing_zone = fetch_one(
                db,
                "SELECT id, zone_code FROM scene_zones WHERE scene_id = :scene_id AND (zone_code = :z_code OR zone_name = :z_name)",
                {"scene_id": scene_id, "z_code": z_code, "z_name": z_name},
            )
            if existing_zone:
                zone_id = existing_zone["id"]
                db.execute(
                    text("""
                        UPDATE scene_zones
                        SET zone_code = CASE WHEN (zone_code IS NULL OR zone_code = '') AND :z_code != '' THEN :z_code ELSE zone_code END,
                            zone_name = CASE WHEN (zone_name IS NULL OR zone_name = '') AND :z_name != '' THEN :z_name ELSE zone_name END,
                            time_lighting = CASE WHEN :time_lighting != '' THEN :time_lighting ELSE time_lighting END,
                            acoustic_resistance = CASE WHEN :acoustic_resistance != '' THEN :acoustic_resistance ELSE acoustic_resistance END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": zone_id,
                        "z_code": z_code,
                        "z_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                        "now": now,
                    },
                )
            else:
                z_ins = db.execute(
                    text("""
                        INSERT INTO scene_zones (
                            scene_id, drama_id, zone_code, zone_name, time_lighting,
                            acoustic_resistance, created_at, updated_at
                        ) VALUES (
                            :scene_id, :drama_id, :zone_code, :zone_name, :time_lighting,
                            :acoustic_resistance, :now, :now
                        )
                    """),
                    {
                        "scene_id": scene_id,
                        "drama_id": drama_id,
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                        "now": now,
                    },
                )
                zone_id = getattr(z_ins, "lastrowid", None) or 1
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景子区域] 登记第 %s 集空间子区域: zone_id=%s, scene_id=%s, 代号=%s, 名称=%s",
                    curr_ep, zone_id, scene_id, z_code, z_name,
                )

            if primary_zone_id is None:
                primary_zone_id = zone_id

        target_zone_id = primary_zone_id or 1

        # 4.2 写入本集气候做旧图层 (scene_weathering_views)
        weathering_list = env.get("weathering_applied") or env.get("weathering_layers") or []
        if isinstance(weathering_list, str):
            weathering_list = [weathering_list]
        elif isinstance(weathering_list, dict):
            weathering_list = [f"{k}: {v}" for k, v in weathering_list.items()]

        for w_item in weathering_list:
            w_desc = str(w_item).strip()
            if not w_desc:
                continue

            existing_w = fetch_one(
                db,
                "SELECT id FROM scene_weathering_views WHERE scene_zone_id = :z_id AND description = :desc",
                {"z_id": target_zone_id, "desc": w_desc},
            )
            w_delta_prompt, w_full_prompt = PromptSynthesizer.synthesize_scene_view_prompt(
                env.get("visual_prompt") or loc,
                view_type="STATE",
                weathering_prompt=w_desc,
                atmosphere_prompt=time_lighting,
            )
            w_neg_prompt = PromptSynthesizer.get_negative_prompt("environment")
            w_asset_key = f"{bench_scene_key}_W{curr_ep}"

            if not existing_w:
                db.execute(
                    text("""
                        INSERT INTO scene_weathering_views (
                            scene_zone_id, layer_type, description,
                            asset_key, parent_asset_key, generation_mode, denoise_strength,
                            visual_prompt, negative_prompt, is_benchmark, is_primary,
                            is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :scene_zone_id, 'episode_weathering', :description,
                            :asset_key, :parent_asset_key, 'i2i', 0.45,
                            :visual_prompt, :negative_prompt, 0, 0,
                            1, :now, :now
                        )
                    """),
                    {
                        "scene_zone_id": target_zone_id,
                        "description": w_desc,
                        "asset_key": w_asset_key,
                        "parent_asset_key": bench_scene_key,
                        "visual_prompt": w_full_prompt,
                        "negative_prompt": w_neg_prompt,
                        "now": now,
                    },
                )
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景做旧] 记录第 %s 集场景做旧图层: scene_id=%s, zone_id=%s, 图层=%s, 父资产键=%s",
                    curr_ep, scene_id, target_zone_id, w_desc, bench_scene_key,
                )
            else:
                db.execute(
                    text("""
                        UPDATE scene_weathering_views
                        SET asset_key = CASE WHEN (asset_key IS NULL OR asset_key = '') THEN :asset_key ELSE asset_key END,
                            parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                            generation_mode = 'i2i',
                            denoise_strength = CASE WHEN (denoise_strength IS NULL OR denoise_strength = 0) THEN 0.45 ELSE denoise_strength END,
                            visual_prompt = CASE WHEN (visual_prompt IS NULL OR visual_prompt = '') THEN :visual_prompt ELSE visual_prompt END,
                            negative_prompt = CASE WHEN (negative_prompt IS NULL OR negative_prompt = '') THEN :negative_prompt ELSE negative_prompt END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_w["id"],
                        "asset_key": w_asset_key,
                        "parent_asset_key": bench_scene_key,
                        "visual_prompt": w_full_prompt,
                        "negative_prompt": w_neg_prompt,
                        "now": now,
                    },
                )

    # -------------------------------------------------------------------------
    # 5. 核心道具资产与剧情损坏形态演进 (props, prop_damage_states)
    # -------------------------------------------------------------------------
    # 合并新发现道具项与新生成资产中的道具项
    for new_prop in newly_discovered_props:
        np_dict = _dump_or_dict(new_prop)
        if isinstance(np_dict, dict) and np_dict not in props_manifest:
            props_manifest.append(np_dict)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or "")
        if (cat == "prop" or aid.startswith("PROP_")) and n_dict not in props_manifest:
            props_manifest.append(n_dict)

    for prop_raw in props_manifest:
        prop = _dump_or_dict(prop_raw)
        if not isinstance(prop, dict):
            continue
        p_name = str(prop.get("prop_name") or prop.get("name") or "").strip()
        if not p_name:
            continue

        raw_p_code = str(prop.get("prop_code") or prop.get("code") or "").strip()
        p_code = raw_p_code if raw_p_code else AssetProtocolHelper.normalize_token(p_name)
        bench_prop_key = prop.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_prop(p_code)

        existing_prop = fetch_one(
            db,
            "SELECT id FROM props WHERE drama_id = :drama_id AND (prop_code = :p_code OR name = :name)",
            {"drama_id": drama_id, "p_code": p_code, "name": p_name},
        )
        if existing_prop:
            prop_id = existing_prop["id"]
            db.execute(
                text("""
                    UPDATE props
                    SET prop_code = CASE WHEN (prop_code IS NULL OR prop_code = '') AND :p_code != '' THEN :p_code ELSE prop_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {"id": prop_id, "p_code": p_code, "bench_key": bench_prop_key, "now": now},
            )
        else:
            p_ins = db.execute(
                text("""
                    INSERT INTO props (
                        drama_id, prop_code, benchmark_asset_key, name, type, description, prompt, created_at, updated_at
                    ) VALUES (
                        :drama_id, :prop_code, :benchmark_asset_key, :name, :type, :description, :prompt, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "prop_code": p_code,
                    "benchmark_asset_key": bench_prop_key,
                    "name": p_name,
                    "type": prop.get("type", "narrative_reversal"),
                    "description": prop.get("description") or f"第{curr_ep}集关键叙事道具",
                    "prompt": prop.get("visual_prompt") or "",
                    "now": now,
                },
            )
            prop_id = getattr(p_ins, "lastrowid", None) or 1
            log.info(
                "【阶段 6 落库】[步骤 5/6 道具] 登记第 %s 集新道具: prop_id=%s, 代号=%s, 名称=%s, 基准键=%s",
                curr_ep, prop_id, p_code, p_name, bench_prop_key,
            )

        # 写入道具破坏与战损演进状态 (prop_damage_states)
        d_states: list[dict[str, Any]] = []
        raw_ds = prop.get("damage_states") or prop.get("damage_state_views")
        if raw_ds:
            if isinstance(raw_ds, list):
                for item in raw_ds:
                    if isinstance(item, dict):
                        d_states.append(item)
                    elif isinstance(item, str) and item.strip():
                        d_states.append({"state_label": item.strip()})
            elif isinstance(raw_ds, dict):
                for k, v in raw_ds.items():
                    d_states.append({"state_label": str(k), "narrative_point": str(v)})
            elif isinstance(raw_ds, str) and raw_ds.strip():
                d_states.append({"state_label": raw_ds.strip()})

        single_state = str(prop.get("damage_state") or prop.get("state_label") or "").strip()
        if single_state and not any(ds.get("state_label") == single_state for ds in d_states):
            d_states.append({
                "state_label": single_state,
                "damage_level": prop.get("damage_level", 1),
                "parent_state_id": prop.get("parent_state_id"),
                "parent_state_label": prop.get("parent_state_label"),
                "narrative_point": prop.get("narrative_point"),
                "visual_prompt": prop.get("visual_prompt"),
            })

        # 若未提供显式战损形态（例如初始完整物证），自动为其建立 S0 初始完整形态，确保 3 层体系完整闭环
        if not d_states:
            d_states.append({
                "state_code": "S0",
                "state_label": "初始完整形态",
                "damage_level": 0,
                "narrative_point": prop.get("description") or f"第{curr_ep}集初始物证形态",
                "visual_prompt": prop.get("visual_prompt"),
            })

        prev_ds_id = 0
        for s_idx, ds_item in enumerate(d_states):
            s_label = str(ds_item.get("state_label") or "").strip()
            if not s_label or not prop_id:
                continue

            has_explicit_code = bool(ds_item.get("state_code"))
            if has_explicit_code:
                state_code = str(ds_item.get("state_code")).strip().upper()
                if state_code.isdigit():
                    state_code = f"S{state_code}"
            else:
                c_row = fetch_one(db, "SELECT count(id) as cnt FROM prop_damage_states WHERE prop_id = :prop_id", {"prop_id": prop_id})
                c_cnt = int(c_row.get("cnt", 0)) if c_row else s_idx
                state_code = f"S{c_cnt}"

            parent_state_ref = ds_item.get("parent_state_id") or ds_item.get("parent_state_label") or ""
            parent_state_id = 0
            if isinstance(parent_state_ref, int):
                parent_state_id = parent_state_ref
            elif isinstance(parent_state_ref, str) and parent_state_ref.strip():
                p_label = parent_state_ref.strip()
                parent_pds_row = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND (state_label = :p_label OR state_code = :p_label)",
                    {"prop_id": prop_id, "p_label": p_label},
                )
                if parent_pds_row:
                    parent_state_id = parent_pds_row["id"]
                    log.debug("【阶段 6 落库】[DEBUG 道具状态] 成功解析父级战损形态 ID: prop_id=%s, state_label=%s -> parent_state_id=%s", prop_id, s_label, parent_state_id)

            # 若未显式指定父级形态且非首个形态，自动绑定上一损伤形态作为演进母本
            if parent_state_id == 0:
                if prev_ds_id > 0:
                    parent_state_id = prev_ds_id
                else:
                    raw_cur_lvl = ds_item.get("damage_level", 0)
                    try:
                        cur_lvl = int(raw_cur_lvl)
                    except (ValueError, TypeError):
                        cur_lvl = 0
                    if cur_lvl > 0:
                        prev_row = fetch_one(
                            db,
                            "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND damage_level < :cur_lvl ORDER BY damage_level DESC, id DESC LIMIT 1",
                            {"prop_id": prop_id, "cur_lvl": cur_lvl},
                        )
                        if prev_row:
                            parent_state_id = prev_row["id"]

            p_id_prompt = PromptSynthesizer.extract_identity_face_anchor(prop.get("visual_prompt") or p_name)
            p_delta_prompt = f"damage state: {s_label}, level: {ds_item.get('damage_level', 1)}"
            p_neg_prompt = PromptSynthesizer.get_negative_prompt("prop")
            p_synth = PromptSynthesizer.synthesize_prop_view_prompt(p_id_prompt, view_type="STATIC", state_prompt=p_delta_prompt)
            p_full_prompt = p_synth.visual_prompt

            if has_explicit_code:
                existing_ds = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND (state_label = :s_label OR state_code = :s_code)",
                    {"prop_id": prop_id, "s_label": s_label, "s_code": state_code},
                )
            else:
                existing_ds = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND state_label = :s_label",
                    {"prop_id": prop_id, "s_label": s_label},
                )
            if existing_ds:
                db.execute(
                    text("""
                        UPDATE prop_damage_states
                        SET state_code = CASE WHEN (state_code IS NULL OR state_code = '') THEN :state_code ELSE state_code END,
                            parent_state_id = CASE WHEN (parent_state_id IS NULL OR parent_state_id = 0) AND :parent_state_id > 0 THEN :parent_state_id ELSE parent_state_id END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_ds["id"],
                        "state_code": state_code,
                        "parent_state_id": parent_state_id,
                        "now": now,
                    },
                )
                ds_id = existing_ds["id"]
            else:
                raw_d_level = ds_item.get("damage_level", prop.get("damage_level", 1))
                try:
                    damage_level = int(raw_d_level)
                except (ValueError, TypeError):
                    damage_level = 1

                narrative_point = str(ds_item.get("narrative_point") or prop.get("narrative_point") or f"第{curr_ep}集剧情触发物证形态演进: {s_label}")
                visual_prompt = str(ds_item.get("visual_prompt") or prop.get("visual_prompt") or p_full_prompt)

                ins_ds = db.execute(
                    text("""
                        INSERT INTO prop_damage_states (
                            prop_id, drama_id, state_code, state_label, damage_level,
                            narrative_point, parent_state_id, created_at, updated_at
                        ) VALUES (
                            :prop_id, :drama_id, :state_code, :state_label, :damage_level,
                            :narrative_point, :parent_state_id, :now, :now
                        )
                    """),
                    {
                        "prop_id": prop_id,
                        "drama_id": drama_id,
                        "state_code": state_code,
                        "state_label": s_label,
                        "damage_level": damage_level,
                        "narrative_point": narrative_point,
                        "parent_state_id": parent_state_id,
                        "now": now,
                    },
                )
                ds_id = getattr(ins_ds, "lastrowid", None) or 1

            prev_ds_id = ds_id

            macro_asset_key = f"{bench_prop_key}_{state_code}_DETAIL"
            macro_delta = f"macro close-up feature of {s_label}"
            
            # 兼容从上游 manifest 传入的自定义 detail_views 特写描述
            custom_detail_desc = ""
            raw_dvs = ds_item.get("detail_views") or prop.get("detail_views") or []
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

            macro_synth = PromptSynthesizer.synthesize_prop_view_prompt(p_id_prompt, view_type="DETAIL", state_prompt=macro_delta)
            macro_prompt_str = macro_synth.visual_prompt

            existing_dv = fetch_one(
                db,
                "SELECT id FROM prop_detail_views WHERE damage_state_id = :ds_id AND view_type = 'macro_feature'",
                {"ds_id": ds_id},
            )
            if existing_dv:
                db.execute(
                    text("""
                        UPDATE prop_detail_views
                        SET asset_key = CASE WHEN (asset_key IS NULL OR asset_key = '') THEN :asset_key ELSE asset_key END,
                            parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                            generation_mode = CASE WHEN (generation_mode IS NULL OR generation_mode = '' OR generation_mode = 't2i') THEN 'crop_macro' ELSE generation_mode END,
                            denoise_strength = CASE WHEN (denoise_strength IS NULL OR denoise_strength = 0) THEN 0.45 ELSE denoise_strength END,
                            visual_prompt = CASE WHEN (visual_prompt IS NULL OR visual_prompt = '') THEN :visual_prompt ELSE visual_prompt END,
                            negative_prompt = CASE WHEN (negative_prompt IS NULL OR negative_prompt = '') THEN :negative_prompt ELSE negative_prompt END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_dv["id"],
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_prompt_str,
                        "negative_prompt": p_neg_prompt,
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
                        "damage_state_id": ds_id,
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_prompt_str,
                        "negative_prompt": p_neg_prompt,
                        "now": now,
                    },
                )
            log.info(
                "【阶段 6 落库】[步骤 5/6 道具形态] 记录道具 [%s] 战损演进状态: 形态=%s(%s), 父基准键=%s, 剧集=%s",
                p_name, s_label, state_code, bench_prop_key, curr_ep,
            )

    # 二次遍历解析可能因先后次序未解析的 parent_state_id
    for prop_raw in props_manifest:
        prop = _dump_or_dict(prop_raw)
        if not isinstance(prop, dict):
            continue
        p_name = str(prop.get("prop_name") or prop.get("name") or "").strip()
        p_row = fetch_one(db, "SELECT id FROM props WHERE drama_id = :drama_id AND name = :name", {"drama_id": drama_id, "name": p_name})
        if not p_row:
            continue
        pid = p_row["id"]
        raw_ds = prop.get("damage_states") or prop.get("damage_state_views") or []
        if isinstance(raw_ds, dict):
            raw_ds = [{"state_label": k, "narrative_point": v} for k, v in raw_ds.items()]
        elif not isinstance(raw_ds, list):
            raw_ds = []
        if prop.get("damage_state") or prop.get("parent_state_label"):
            raw_ds.append(prop)
        for ds_it in raw_ds:
            if not isinstance(ds_it, dict):
                continue
            s_lbl = str(ds_it.get("state_label") or ds_it.get("damage_state") or "").strip()
            p_lbl = str(ds_it.get("parent_state_label") or "").strip()
            if s_lbl and p_lbl:
                p_ds_row = fetch_one(
                    db,
                    """
                    SELECT id FROM prop_damage_states
                    WHERE prop_id = :pid AND state_label = :p_lbl
                    LIMIT 1
                    """,
                    {"pid": pid, "p_lbl": p_lbl},
                )
                if p_ds_row and p_ds_row.get("id"):
                    db.execute(
                        text("""
                            UPDATE prop_damage_states
                            SET parent_state_id = :parent_id
                            WHERE prop_id = :pid AND state_label = :s_lbl AND (parent_state_id IS NULL OR parent_state_id = 0)
                        """),
                        {"pid": pid, "s_lbl": s_lbl, "parent_id": p_ds_row["id"]},
                    )
                    log.debug("【阶段 6 落库】[DEBUG 道具状态二次解析] 关联 parent_state_id: prop_id=%s, state_label=%s, parent_label=%s, parent_id=%s", pid, s_lbl, p_lbl, p_ds_row["id"])

    # -------------------------------------------------------------------------
    # 5.5 统管媒体素材库原子落库 (assets 表全字段写入与元数据关联)
    # -------------------------------------------------------------------------
    log.info("【阶段 6 落库】[步骤 5.5/6 统管素材] 开始将多模态资产与母音卡写入 assets 统管表...")
    all_raw_assets_to_persist: list[dict[str, Any]] = []

    # 1. 收集新生成的多模态视听资产
    for na in newly_generated_assets:
        nad = _dump_or_dict(na)
        if isinstance(nad, dict):
            all_raw_assets_to_persist.append(nad)

    # 2. 收集角色母音卡作为音频资产
    for vc in voice_cards:
        vcd = _dump_or_dict(vc)
        if isinstance(vcd, dict):
            v_key = str(vcd.get("master_voice_id") or vcd.get("voice_id") or "").strip()
            if v_key and not any(str(a.get("asset_id") or a.get("asset_key")) == v_key for a in all_raw_assets_to_persist):
                all_raw_assets_to_persist.append({
                    "asset_id": v_key,
                    "asset_key": v_key,
                    "name": str(vcd.get("character_name") or "") + "母音卡",
                    "category": "voice",
                    "type": "audio",
                    "prompt": str(vcd.get("master_tts_prompt") or vcd.get("voice_prompt") or ""),
                    "negative_prompt": "",
                    "timbre": vcd.get("timbre"),
                    "speed_ratio": vcd.get("speed_ratio", 1.0),
                    "pitch_ratio": vcd.get("pitch_ratio", 1.0),
                    "semantic_hash": vcd.get("semantic_hash"),
                    "voice_file_path": vcd.get("voice_file_path"),
                    "character_id": vcd.get("character_id"),
                    "character_name": vcd.get("character_name"),
                    "is_master_card": 1,
                    "lifecycle_status": vcd.get("lifecycle_status", "READY"),
                })

    for a_item in all_raw_assets_to_persist:
        asset_key = str(a_item.get("asset_key") or a_item.get("asset_id") or "").strip()
        if not asset_key:
            continue

        a_name = str(a_item.get("name") or a_item.get("asset_name") or asset_key).strip()
        cat = str(a_item.get("category") or "").lower()
        if not cat:
            if asset_key.startswith("CHAR_"):
                cat = "character"
            elif asset_key.startswith("ENV_"):
                cat = "environment"
            elif asset_key.startswith("PROP_"):
                cat = "prop"
            elif asset_key.startswith("VOICE_"):
                cat = "voice"
            else:
                cat = "misc"

        a_type = str(a_item.get("type") or "").lower()
        if not a_type:
            a_type = "audio" if (cat == "voice" or asset_key.startswith("VOICE_")) else "image"

        prompt = str(a_item.get("prompt") or a_item.get("visual_prompt") or a_item.get("master_tts_prompt") or "").strip()
        neg_prompt = str(a_item.get("negative_prompt") or "").strip()

        # 构造 params 参数 JSON
        params_dict: dict[str, Any] = {}
        for pk in (
            "generation_method", "aspect_ratio", "input_source_image",
            "denoising_strength", "semantic_hash", "timbre",
            "speed_ratio", "pitch_ratio", "seed", "steps", "cfg_scale", "lora"
        ):
            if pk in a_item and a_item[pk] is not None:
                params_dict[pk] = a_item[pk]

        # 若 lineage_dag 中存在该资产的父级底图，且当前没有 input_source_image，则自动补齐
        if "input_source_image" not in params_dict and asset_key in lineage_dag_data:
            params_dict["input_source_image"] = lineage_dag_data[asset_key]

        # 构造 metadata 元数据 JSON
        meta_dict: dict[str, Any] = {}
        parent_id = a_item.get("parent_asset_id") or lineage_dag_data.get(asset_key) or params_dict.get("input_source_image")
        if parent_id:
            meta_dict["parent_asset_id"] = parent_id
        meta_dict["episode_num"] = curr_ep
        meta_dict["lifecycle_status"] = a_item.get("lifecycle_status", "READY")
        for mk in ("character_id", "character_name", "is_master_card", "voice_file_path", "stage_code", "damage_state"):
            if mk in a_item and a_item[mk] is not None:
                meta_dict[mk] = a_item[mk]

        # 角色领域三层模型反向回溯挂载 (注入 character_id, character_stage_id, view_type, is_master_portrait)
        if asset_key in asset_character_meta_map:
            for ak_k, ak_v in asset_character_meta_map[asset_key].items():
                meta_dict[ak_k] = ak_v
        elif cat == "character" or asset_key.startswith("CHAR_"):
            cand_p_code, cand_st_code, cand_v_tok = extract_character_tokens(asset_key)
            clean_aname = clean_character_name(a_name)
            matched_ent = canonical_map.get(clean_aname.lower())
            if matched_ent:
                meta_dict["character_id"] = matched_ent.get("db_id")
                meta_dict["character_name"] = matched_ent.get("char_name")
                st_key = cand_st_code or "T1"
                if st_key in stage_db_ids_by_code:
                    meta_dict["character_stage_id"] = stage_db_ids_by_code[st_key]
                    meta_dict["stage_code"] = st_key
                v_type, _, is_prim = parse_character_view_type(cand_v_tok, a_name)
                meta_dict["view_type"] = v_type
                meta_dict["is_master_portrait"] = (is_prim == 1)

        # 提取 DAG 关系与四维提示词元数据 (全系统防退化总关口)
        dep_rule = AssetProtocolHelper.get_dependency_rule(asset_key)
        rule_mode = (dep_rule.get("generation_mode") if isinstance(dep_rule, dict) else getattr(dep_rule, "generation_mode", "t2i")) or "t2i"
        rule_parent = (dep_rule.get("parent_asset_id") if isinstance(dep_rule, dict) else (getattr(dep_rule, "parent_asset_id", None) or getattr(dep_rule, "parent_asset_key", None)))
        rule_denoise = (dep_rule.get("recommended_denoise") if isinstance(dep_rule, dict) else getattr(dep_rule, "recommended_denoise", 0.45))

        a_parent_key = a_item.get("parent_asset_key") or a_item.get("parent_asset_id") or rule_parent
        a_gen_mode = a_item.get("generation_mode") or rule_mode

        if rule_mode != "t2i":
            # 非一阶根节点资产：严禁退化为文生图 t2i，且严禁父级引用丢失
            if a_gen_mode == "t2i":
                log.warning("【阶段 6 落库·防退化拦截】资产 [%s] (预期模式=%s) 企图以 t2i 落库，强制纠偏为 %s", asset_key, rule_mode, rule_mode)
                a_gen_mode = rule_mode
            if not a_parent_key:
                a_parent_key = rule_parent
                log.warning("【阶段 6 落库·孤儿资产救援】资产 [%s] (mode=%s) 缺少父级引用，自动挂载至标准根基准 [%s]", asset_key, a_gen_mode, a_parent_key)
            a_is_bench = 0
            raw_denoise = a_item.get("denoise_strength")
            try:
                if raw_denoise is None or float(raw_denoise) == 0.0:
                    a_denoise_flt = float(rule_denoise if rule_denoise is not None else 0.45)
                else:
                    a_denoise_flt = float(raw_denoise)
            except (ValueError, TypeError):
                a_denoise_flt = 0.45
        else:
            # 真正的一阶基准根节点 (T1 / Z01 / S0)
            a_gen_mode = "t2i"
            a_parent_key = None
            a_is_bench = 1
            a_denoise_flt = 0.0

        a_ctrl_type = a_item.get("control_type") or (
            dep_rule.get("control_type") if isinstance(dep_rule, dict) else getattr(dep_rule, "control_type", None)
        )

        a_id_prompt = a_item.get("identity_prompt") or PromptSynthesizer.extract_identity_face_anchor(prompt or a_name)
        a_delta_prompt = a_item.get("delta_prompt") or (prompt if prompt != a_id_prompt else "")
        if not neg_prompt:
            neg_prompt = PromptSynthesizer.get_negative_prompt(cat)

        existing_asset = fetch_one(
            db,
            "SELECT id FROM assets WHERE drama_id = :drama_id AND asset_key = :asset_key",
            {"drama_id": drama_id, "asset_key": asset_key},
        )
        if existing_asset:
            db.execute(
                text("""
                    UPDATE assets
                    SET name = :name,
                        type = :type,
                        category = :category,
                        parent_asset_id = :parent_asset_id,
                        generation_mode = :generation_mode,
                        denoise_strength = :denoise_strength,
                        is_benchmark = :is_benchmark,
                        prompt = :prompt,
                        negative_prompt = :negative_prompt,
                        params = :params,
                        metadata = :metadata,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": existing_asset["id"],
                    "name": a_name,
                    "type": a_type,
                    "category": cat,
                    "parent_asset_id": a_parent_key,
                    "generation_mode": a_gen_mode,
                    "denoise_strength": a_denoise_flt,
                    "is_benchmark": a_is_bench,
                    "prompt": prompt,
                    "negative_prompt": neg_prompt,
                    "params": json.dumps(params_dict, ensure_ascii=False),
                    "metadata": json.dumps(meta_dict, ensure_ascii=False),
                    "now": now,
                },
            )
            log.debug("【阶段 6 落库】[DEBUG 统管素材] 更新已有资产: asset_key=%s, id=%s", asset_key, existing_asset["id"])
        else:
            ins_a = db.execute(
                text("""
                    INSERT INTO assets (
                        drama_id, asset_key, name, type, category,
                        parent_asset_id, generation_mode, denoise_strength, is_benchmark,
                        prompt, negative_prompt,
                        params, metadata, created_at, updated_at
                    ) VALUES (
                        :drama_id, :asset_key, :name, :type, :category,
                        :parent_asset_id, :generation_mode, :denoise_strength, :is_benchmark,
                        :prompt, :negative_prompt,
                        :params, :metadata, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "asset_key": asset_key,
                    "name": a_name,
                    "type": a_type,
                    "category": cat,
                    "parent_asset_id": a_parent_key,
                    "generation_mode": a_gen_mode,
                    "denoise_strength": a_denoise_flt,
                    "is_benchmark": a_is_bench,
                    "prompt": prompt,
                    "negative_prompt": neg_prompt,
                    "params": json.dumps(params_dict, ensure_ascii=False),
                    "metadata": json.dumps(meta_dict, ensure_ascii=False),
                    "now": now,
                },
            )
            log.info("【阶段 6 落库】[步骤 5.5/6 统管素材] 新增资产成功入库: asset_key=%s, id=%s, is_benchmark=%s", asset_key, getattr(ins_a, "lastrowid", None), a_is_bench)

    # 步骤 5.6: 自动同步本集增量资产到专属向量集合 lmd_assets_drama_{drama_id}
    try:
        synced_count = vector_memory_service.sync_assets_to_vector_db(
            drama_id=drama_id,
            assets=all_raw_assets_to_persist,
        )
        log.info("【阶段 6 落库】[步骤 5.6 向量同步] 增量资产已成功同步至向量库专属集合: %d 项", synced_count)
    except Exception as v_err:
        log.warning("【阶段 6 落库】资产向量集合同步异常 (容灾降级，不阻断主事务): %s", v_err)

    # -------------------------------------------------------------------------
    # 6. 长期记忆自动入库与向量化
    # -------------------------------------------------------------------------
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
    try:
        sync_stage_memories_to_vector_db(db, drama_id, 6, stage6_memories)
        log.info("【阶段 6 落库】向量数据库同步成功完成")
    except Exception as e:
        log.warning("【阶段 6 落库】向量数据库同步出现非阻塞异常 (已隔离保护): %s", e)

    # -------------------------------------------------------------------------
    # 7. 全局资产注册表更新与短剧阶段跃迁
    # -------------------------------------------------------------------------
    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    if getattr(state, "visual_audio_assets_registry", None):
        current_meta["visual_audio_assets_registry"] = _dump_or_dict(state.visual_audio_assets_registry)
    elif isinstance(state, dict) and state.get("visual_audio_assets_registry"):
        current_meta["visual_audio_assets_registry"] = _dump_or_dict(state["visual_audio_assets_registry"])

    # 聚合全局 asset_lineage_dag
    existing_lineage_dag = current_meta.get("asset_lineage_dag") or {}
    if not isinstance(existing_lineage_dag, dict):
        existing_lineage_dag = {}
    if lineage_dag_data and isinstance(lineage_dag_data, dict):
        existing_lineage_dag.update(lineage_dag_data)
    current_meta["asset_lineage_dag"] = existing_lineage_dag
    log.debug("【阶段 6 落库】[DEBUG 全局元数据] asset_lineage_dag 合并后项数: %d", len(existing_lineage_dag))

    # 同步本集新入册角色的 11 维档案至 dramas.metadata["character_tokens"]，确保跨集长线一致
    existing_char_tokens = current_meta.get("character_tokens") or []
    if not isinstance(existing_char_tokens, list):
        existing_char_tokens = []
    known_token_codes = {
        str(ct.get("character_code") or ct.get("char_id") or "").strip()
        for ct in existing_char_tokens if isinstance(ct, dict)
    }
    known_token_names = {
        clean_character_name(str(ct.get("name") or ct.get("character_name") or ""))
        for ct in existing_char_tokens if isinstance(ct, dict)
    }
    for ndc in newly_discovered_characters:
        ndc_dict = _dump_or_dict(ndc)
        if not isinstance(ndc_dict, dict):
            continue
        ndc_code = str(ndc_dict.get("character_code") or "").strip()
        ndc_name = clean_character_name(str(ndc_dict.get("name") or ndc_dict.get("character_name") or ""))
        if ndc_code and ndc_code not in known_token_codes and ndc_name not in known_token_names:
            existing_char_tokens.append(ndc_dict)
            known_token_codes.add(ndc_code)
            if ndc_name:
                known_token_names.add(ndc_name)
            log.debug("【阶段 6 落库】[DEBUG 全局角色同步] 已将阶段 6 补建角色 [%s(%s)] 合并至 dramas.metadata.character_tokens", ndc_name, ndc_code)
    current_meta["character_tokens"] = existing_char_tokens

    db.execute(
        text("UPDATE dramas SET current_stage = 6, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 6, state.latest_audit)

    db.commit()
    log.info("【阶段 6 落库】短剧 [%s] 第 %s 集全部资产与关系表持久化完成并已提交事务。", drama_id, curr_ep)


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

