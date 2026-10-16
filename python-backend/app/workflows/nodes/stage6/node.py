"""阶段 6：第二程资产准备与真理源校验业务执行节点 (Stage 6 Asset Truth Registry Node)。

严格遵循 SKILL1.md 四段式确定性寻址协议，调度逆向扫描算子、LLM 资产提纯与确定性保底工程，
汇聚单集引单并原子更新全剧视听资产真理源注册表。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Mapping

from app.context.vector_memory_service import recall_candidate_assets_for_episode
from app.db.session import session_scope
from app.schemas.script_graph_state import (
    AssetState,
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    IndustrialDramaState,
    MasterVoiceCardModel,
    NewlyGeneratedAssetModel,
    ReusedAssetModel,
    VisualAudioAssetsRegistryModel,
)
import app.workflows.nodes.stage6_asset_truth as stage6_facade
from app.tools.screenplay_feature_scanner import (
    ScreenplayScanResult,
    _extract_anchor_props_from_characters,
    is_valid_character_speaker,
    scan_screenplay_features,
)
from app.workflows.nodes.stage6.dossier_builders import (
    _build_stage2_character_dossier,
    _build_stage3_prop_dossier,
    _build_stage3_scene_dossier,
)
from app.workflows.nodes.stage6.fallback import _stage6_fallback
from app.workflows.nodes.stage6.helpers import (
    StageResult,
    _clean_name,
    _ensure_standard_asset,
    _extract_screenplay_text,
    _extract_token_from_id,
    _get_val,
    compute_asset_semantic_hash,
)
from app.workflows.nodes.stage6.normalizer import (
    AssetEntityNormalizer,
    MorphStateMachine,
    extract_pure_physical_environment_cues,
)
from app.workflows.nodes.stage6.projectors import (
    _build_candidates_from_projected_registry,
    is_character_truly_in_screenplay,
    project_characters_for_stage6,
    project_environments_props_for_stage6,
    project_registry_index_for_stage6,
    summarize_scanner_findings,
)
from app.workflows.nodes.stage6.voice_rules import (
    TIMBRE_ARCHETYPE_POOL,
    _build_default_emotion_rules,
    _select_voice_archetype,
    _strip_dialogue_brackets,
)
from app.workflows.operators.asset_trigger_operator_engine import AssetTriggerOperatorEngine
from app.workflows.prompts.master_sop_prompts import (
    STAGE6_SYSTEM_PROMPT,
    STAGE6_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetDependency, AssetProtocolHelper
from app.workflows.utils.asset_slice_enricher import AssetSliceEnricher
from app.workflows.utils.llm_bridge import call_llm_json
from app.workflows.utils.prompt_synthesizer import PromptMatrixSynthesizer, PromptSynthesizer

logger = logging.getLogger("lmd.stage6.node")


def stage6_asset_truth_node(
    state: EpisodeScopedSubState | GlobalDramaMasterState | IndustrialDramaState | Any,
) -> dict[str, Any]:
    """【规则编号: RULE-VI-06 & RULE-STAGE6-01】执行阶段 6：提纯单集资产清单并维护全剧真理源总库。"""
    ep_num = (
        _get_val(state, "episode_number")
        or _get_val(state, "current_episode")
        or _get_val(state, "current_visual_episode", 1)
        or 1
    )
    completed = _get_val(state, "completed_screenplays", {}) or {}
    script = completed.get(ep_num) or completed.get(str(ep_num)) or {}
    if not script and _get_val(state, "episodes_scripts"):
        scripts_list = _get_val(state, "episodes_scripts")
        if isinstance(scripts_list, list) and len(scripts_list) >= ep_num:
            script = scripts_list[ep_num - 1]
    if not script and _get_val(state, "episode_script"):
        script = _get_val(state, "episode_script")
    if not script and _get_val(state, "screenplay"):
        script = _get_val(state, "screenplay")
    if not script and _get_val(state, "screenplay_text"):
        script = {"body_markdown": _get_val(state, "screenplay_text"), "text": _get_val(state, "screenplay_text")}
    if hasattr(script, "model_dump"):
        script = script.model_dump()
    elif not isinstance(script, dict):
        script = {}
    chars_engine = _get_val(state, "characters_engine", None)
    if not chars_engine:
        chars_engine = _get_val(state, "character_engine", None)
    if not chars_engine and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
        chars_engine = state.__pydantic_extra__.get("character_engine") or state.__pydantic_extra__.get("characters_engine")
    if not chars_engine and hasattr(state, "characters") and getattr(state, "characters"):
        chars_engine = getattr(state, "characters")
    if not chars_engine:
        chars_engine = {}

    envs_props = _get_val(state, "environments_and_props", None)
    if not envs_props:
        envs_props = _get_val(state, "environments_props", None)
    if not envs_props and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
        envs_props = state.__pydantic_extra__.get("environments_and_props") or state.__pydantic_extra__.get("environments_props")
    if not envs_props:
        envs_props = {}

    logger.debug(f"[Stage 6 Node] [RULE-STAGE6-01] Starting asset distillation for Episode {ep_num}.")

    if isinstance(chars_engine, list):
        char_list = chars_engine
    elif isinstance(chars_engine, dict):
        char_list = chars_engine.get("characters", [])
    else:
        char_list = []

    scene_list = envs_props.get("environments") or envs_props.get("scenes") or []
    prop_list = envs_props.get("props") or []

    # 兼容单集独立切片 EpisodeScopedSubState 中的轻量桩
    if not char_list and _get_val(state, "relevant_character_stubs"):
        char_list = [
            {
                "character_id": f"CHAR_{c.character_id}" if not str(c.character_id).startswith("CHAR_") else str(c.character_id),
                "name": c.name,
                "role_type": c.archetype,
                "appearance": c.visual_token,
                "voice_style": c.core_costume_prompt,
            }
            if hasattr(c, "character_id") else c
            for c in _get_val(state, "relevant_character_stubs")
        ]
    if not scene_list and _get_val(state, "relevant_scene_stubs"):
        scene_list = [
            {
                "env_id": f"ENV_{s.scene_id}" if not str(s.scene_id).startswith("ENV_") else str(s.scene_id),
                "location_name": s.name,
                "visual_prompt": s.weathering_summary,
                "atmosphere": s.color_tone,
            }
            if hasattr(s, "scene_id") else s
            for s in _get_val(state, "relevant_scene_stubs")
        ]
    if not prop_list and _get_val(state, "relevant_prop_stubs"):
        prop_list = [
            {
                "prop_id": f"PROP_{p.prop_id}" if not str(p.prop_id).startswith("PROP_") else str(p.prop_id),
                "name": p.name,
                "type": p.level,
                "visual_prompt": p.visual_token,
            }
            if hasattr(p, "prop_id") else p
            for p in _get_val(state, "relevant_prop_stubs")
        ]

    # 【Stage 2 -> Stage 6 灵魂锚点道具桥接】将角色档案中的 carried_anchor_item / anchor_props 自动汇入 prop_list
    # 彻底打通阶段 2 随身锚点设定与阶段 6 特征扫描/资产清单之间的断层
    existing_p_names = {
        str(p.get("name") or p.get("prop_name") or "").strip()
        for p in prop_list
        if isinstance(p, dict) and (p.get("name") or p.get("prop_name"))
    }
    anchor_from_chars = _extract_anchor_props_from_characters(char_list)
    if anchor_from_chars:
        prop_list = list(prop_list)
        for cap in anchor_from_chars:
            if cap["name"] not in existing_p_names:
                existing_p_names.add(cap["name"])
                prop_list.append(cap)
                logger.debug(
                    "【阶段 6 执行节点】自动将角色 [%s] 的随身锚点道具 '%s' (%s) 注入本集已知物证列表",
                    cap.get("owner_character", ""), cap["name"], cap["prop_id"],
                )

    # 提取已锁定的 Token 白名单
    char_tokens = set(
        _get_val(state, "character_tokens")
        or (chars_engine.get("character_tokens") if isinstance(chars_engine, dict) else [])
        or [
            re.sub(r"[^A-Z0-9]+", "", c.get("character_id", "").replace("CHAR_", ""))
            for c in char_list
            if isinstance(c, dict) and c.get("character_id")
        ]
    )
    scene_tokens = set(
        _get_val(state, "scene_tokens")
        or envs_props.get("scene_tokens")
        or [
            re.sub(r"[^A-Z0-9]+", "", (e.get("env_id") or e.get("environment_id", "")).replace("ENV_", ""))
            for e in scene_list
            if isinstance(e, dict) and (e.get("env_id") or e.get("environment_id"))
        ]
    )
    prop_tokens = set(
        _get_val(state, "prop_tokens")
        or envs_props.get("prop_tokens")
        or [
            re.sub(r"[^A-Z0-9]+", "", p.get("prop_id", "").replace("PROP_", ""))
            for p in prop_list
            if isinstance(p, dict) and p.get("prop_id")
        ]
    )

    reg_raw = _get_val(state, "visual_audio_assets_registry", {}) or {}
    if hasattr(reg_raw, "to_dict"):
        registry = reg_raw.to_dict()
    elif hasattr(reg_raw, "model_dump"):
        registry = reg_raw.model_dump()
    elif isinstance(reg_raw, dict):
        registry = dict(reg_raw)
    else:
        registry = {}

    manifests = dict(_get_val(state, "episode_resource_manifests", None) or _get_val(state, "episode_manifests", {}) or {})

    # -------------------------------------------------------------------------
    # 步骤 1：上游关键依赖提取 (阶段 1 视觉规范 / 阶段 4 声音动机 / 阶段 5 单集剧本与上集物理快照)
    # -------------------------------------------------------------------------
    # 1. 提取单集悬念爆款标题 (多层级回退)
    episode_title = script.get("episode_title") or script.get("title") or ""
    if not episode_title:
        season_outlines = _get_val(state, "season_outlines") or _get_val(state, "season_outline") or {}
        if isinstance(season_outlines, dict):
            outline_ep = season_outlines.get(ep_num) or season_outlines.get(str(ep_num)) or {}
            if isinstance(outline_ep, dict):
                episode_title = outline_ep.get("title") or outline_ep.get("killer_title") or outline_ep.get("episode_title") or ""
        elif isinstance(season_outlines, list):
            for item in season_outlines:
                if isinstance(item, dict) and (item.get("episode_num") == ep_num or item.get("episode_id") == ep_num):
                    episode_title = item.get("title") or item.get("killer_title") or item.get("episode_title") or ""
                    break
    if not episode_title:
        episode_title = f"第{ep_num}集"

    # 2. 提取阶段 1 视听圣经核心参数 (画幅、视觉风格、目标视频生成引擎)
    bible = _get_val(state, "bible", {}) or {}
    if hasattr(bible, "model_dump"):
        bible = bible.model_dump()
    elif hasattr(bible, "to_dict"):
        bible = bible.to_dict()
    elif not isinstance(bible, dict):
        bible = {}

    aspect_ratio = (
        _get_val(state, "aspect_ratio")
        or bible.get("aspect_ratio")
        or "9:16"
    )
    visual_style = (
        _get_val(state, "visual_style")
        or bible.get("visual_style")
        or bible.get("tone_style")
        or "电影质感，冷调颗粒，8k超高清写实，戏剧性侧逆光"
    )
    target_video_engine = (
        _get_val(state, "target_video_engine")
        or bible.get("target_video_engine")
        or "kling_1.6_high_fidelity"
    )

    # 3. 提取上一集 0 秒物理接力快照 (用于跨集战损、创伤及核心物证状态追踪)
    screenplay_text = _extract_screenplay_text(script)
    previous_pickup = None
    if ep_num <= 1:
        # 【首集硬隔离法则】第 1 集为全剧开篇，不存在上一集的物理流出，强制置空以阻断跨轮次全局 state 脏残留
        previous_pickup = None
        logger.info("【阶段 6 执行节点】当前为第 %s 集（开篇集），强制上一集物理接力快照为 None", ep_num)
    else:
        # 【非首集精准回溯】优先取自第 ep_num - 1 集的定稿剧本交付物（单一事实真理源）
        prev_script = completed.get(ep_num - 1) or completed.get(str(ep_num - 1)) or {}
        if isinstance(prev_script, dict):
            previous_pickup = (
                prev_script.get("inter_episode_physical_snapshot")
                or prev_script.get("previous_episode_0s_pickup")
                or prev_script.get("pickup_0s")
            )
        # 仅当上一集定稿剧本未显式登记快照时，才降级读取全局流水线状态
        if not previous_pickup:
            fallback = _get_val(state, "inter_episode_physical_snapshot", None) or _get_val(state, "incoming_physical_continuity", None)
            if isinstance(fallback, dict):
                # 校验来源集数，防止误读更晚剧集残留的脏快照
                source_ep = fallback.get("source_episode") or fallback.get("episode_num") or fallback.get("inherited_from_episode")
                if source_ep is None or source_ep == ep_num - 1:
                    previous_pickup = fallback

    logger.debug(
        "【阶段 6 执行节点】上游依赖提取完成: 集数=%s, 单集标题=%s, 画幅=%s, 引擎=%s, 剧本字符数=%s, 物理快照存在=%s",
        ep_num, episode_title, aspect_ratio, target_video_engine, len(screenplay_text), bool(previous_pickup),
    )

    # -------------------------------------------------------------------------
    # 步骤 2：执行确定性剧本多维特征逆向扫描识别算子与高密度线索摘要编译
    # -------------------------------------------------------------------------
    logger.debug("【阶段 6 执行节点】开始运行确定性特征扫描算子 (角色别名、代词消解、形变动词、微距特写)...")
    _scan_fn = getattr(stage6_facade, "scan_screenplay_features", scan_screenplay_features)
    scanner_result = _scan_fn(
        screenplay_text=screenplay_text,
        previous_pickup=previous_pickup if isinstance(previous_pickup, dict) else None,
        existing_assets_registry=registry,
        known_characters=char_list,
        known_environments=scene_list,
        known_props=prop_list,
    )
    scanner_summary = summarize_scanner_findings(scanner_result)
    logger.info("【阶段 6 执行节点】第 %s 集特征预扫描与代词消解完成:\n%s", ep_num, scanner_summary)

    # -------------------------------------------------------------------------
    # 步骤 2.5：视听资产上下文轻量投影 (Audio-Visual Projection Filters)
    # -------------------------------------------------------------------------
    present_chars = scanner_result.characters_detected if scanner_result else []
    present_scenes = scanner_result.scenes_detected if scanner_result else []
    present_props = scanner_result.props_detected if scanner_result else []
    alias_map = scanner_result.character_alias_map if scanner_result else {}

    # 【前置角色白名单裁剪】
    projected_chars = project_characters_for_stage6(
        chars_engine=chars_engine,
        present_names=present_chars,
        screenplay_text=screenplay_text,
        alias_map=alias_map,
    )
    logger.info(
        "【阶段 6 前置角色过滤】已根据预扫描结果与剧本裁剪角色库: 全量 %d -> 当集精炼 %d 名: %s",
        len(chars_engine.get("characters", []) if isinstance(chars_engine, dict) else chars_engine if isinstance(chars_engine, list) else []),
        len(projected_chars),
        [c.get("name") for c in projected_chars],
    )
    projected_envs_props = project_environments_props_for_stage6(envs_props, present_scenes, present_props)
    projected_registry = project_registry_index_for_stage6(registry)

    # 统计瘦身效果与压缩指标
    raw_chars_str = json.dumps(chars_engine, ensure_ascii=False)
    raw_envs_str = json.dumps(envs_props, ensure_ascii=False)
    raw_reg_str = json.dumps(registry, ensure_ascii=False)
    raw_total_chars = len(raw_chars_str) + len(raw_envs_str) + len(raw_reg_str)

    chars_engine_json = json.dumps(projected_chars, ensure_ascii=False, indent=2)
    environments_props_json = json.dumps(projected_envs_props, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------------------
    # 步骤 2.6：动态候选资产池精准实体与语义向量混合召回 (Phase 3 动态候选池)
    # -------------------------------------------------------------------------
    candidates: list[dict[str, Any]] = []
    drama_id = _get_val(state, "drama_id") or _get_val(state, "id")
    state_db = _get_val(state, "db") or _get_val(state, "db_session")
    if drama_id:
        try:
            from app.context.vector_memory_service import recall_candidate_assets_for_episode
            if state_db is not None:
                candidates = recall_candidate_assets_for_episode(
                    db=state_db,
                    drama_id=int(drama_id),
                    screenplay_text=screenplay_text,
                    top_k=15,
                )
            else:
                from app.db.session import session_scope
                with session_scope() as db_session:
                    candidates = recall_candidate_assets_for_episode(
                        db=db_session,
                        drama_id=int(drama_id),
                        screenplay_text=screenplay_text,
                        top_k=15,
                    )
            logger.info(
                "【阶段 6 动态候选召回】成功为短剧 [%s] 第 %d 集动态召回 %d 项高置信度候选资产",
                drama_id, ep_num, len(candidates),
            )
            for c in candidates:
                logger.debug(
                    "【阶段 6 候选资产明细】key=%s, name=%s, cat=%s, score=%.2f, source=%s",
                    c.get("asset_key"), c.get("name"), c.get("category"),
                    c.get("relevance_score", 0.0), c.get("recall_source"),
                )
        except Exception as recall_err:
            logger.warning("【阶段 6 动态候选召回】向量与数据库候选检索异常 (自动启动内存索引降级): %s", recall_err)

    # 若未连接数据库/单测内存环境/召回为空，从内存投影注册表自动提取保底候选池
    if not candidates and (projected_registry or registry):
        candidates = _build_candidates_from_projected_registry(
            projected_registry=projected_registry or registry,
            screenplay_text=screenplay_text,
            top_k=15,
        )
        logger.debug("【阶段 6 候选召回保底】从内存已注册资产表提取 %d 项候选资产", len(candidates))

    reusable_candidate_assets_json = (
        json.dumps(candidates, ensure_ascii=False, indent=2)
        if candidates
        else "（无已核准历史资产，本集登场元素均属首次登场，可按需生成基准视图）"
    )

    projected_total_chars = (
        len(chars_engine_json)
        + len(environments_props_json)
        + len(reusable_candidate_assets_json)
    )
    compression_ratio = ((raw_total_chars - projected_total_chars) / max(raw_total_chars, 1)) * 100

    logger.info(
        "【阶段 6 上下文瘦身与候选池投影】上游依赖上下文瘦身完成: 原始字符数=%d -> 投影后字符数=%d (压缩率: %.1f%%, 候选资产数=%d)",
        raw_total_chars, projected_total_chars, compression_ratio, len(candidates),
    )

    # -------------------------------------------------------------------------
    # 步骤 3：组装标准化用户提示词与大模型调用 (零先验纯剧本盲抽 + 只读字典辅助模式)
    # 彻底杜绝注意力泄露与完型填空强迫症，将前置依赖作为只读语义参考词典，剧本作为唯一物理事实触发器！
    # -------------------------------------------------------------------------
    # 提取分集大纲背景
    outline_synopsis = ""
    season_outlines = (
        getattr(state, "season_outlines", {})
        or (state.get("season_outlines", {}) if isinstance(state, dict) else {})
        or {}
    )
    if isinstance(season_outlines, dict):
        ep_outline_obj = season_outlines.get(ep_num) or season_outlines.get(str(ep_num)) or {}
        if isinstance(ep_outline_obj, dict):
            outline_synopsis = str(ep_outline_obj.get("synopsis") or ep_outline_obj.get("outline") or ep_outline_obj.get("killer_title") or "")
    if not outline_synopsis:
        outline_synopsis = f"第 {ep_num} 集分集大纲：围绕当前核心戏剧冲突展开推进。"

    # 提取人物关系图谱
    char_system_raw = (
        getattr(state, "character_system", {})
        or (state.get("character_system", {}) if isinstance(state, dict) else {})
        or {}
    )
    rel_matrix_text = ""
    if isinstance(char_system_raw, dict):
        rel_data = char_system_raw.get("relationship_matrix") or char_system_raw.get("relationships") or []
        if rel_data:
            rel_matrix_text = json.dumps(rel_data, ensure_ascii=False, indent=2)
    if not rel_matrix_text:
        rel_matrix_text = "（主要人物之间存在核心戏剧对抗与身份制衡关系）"

    # 提取全局已知实体定型库 (用于只读特征词典)
    # 【核心防幻读防护】：角色仅注入当集确切在场的实体档案 (projected_chars)，杜绝未出场角色诱导大模型做完型填空
    projected_char_names = {str(c.get("name")).strip() for c in projected_chars if isinstance(c, dict) and c.get("name")}
    global_entities_dict = {
        "characters": [
            {
                "name": c.get("name"),
                "appearance": c.get("appearance"),
                "biological_dna": c.get("biological_dna"),
                "lived_in_costume": c.get("lived_in_costume"),
            }
            for c in char_list
            if isinstance(c, dict) and str(c.get("name")).strip() in projected_char_names
        ],
        "environments": [
            {
                "name": e.get("name"),
                "architectural_style": e.get("architectural_style") or e.get("appearance"),
            }
            for e in scene_list if isinstance(e, dict)
        ],
        "props": [
            {
                "name": p.get("name"),
                "material": p.get("material"),
            }
            for p in prop_list if isinstance(p, dict)
        ]
    }
    global_entities_json = json.dumps(global_entities_dict, ensure_ascii=False, indent=2)

    user_prompt = STAGE6_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        episode_title=episode_title,
        aspect_ratio=aspect_ratio,
        visual_style=visual_style,
        target_video_engine=target_video_engine,
        episode_outline_synopsis=outline_synopsis,
        character_relationship_matrix=rel_matrix_text,
        global_entities_dossiers_json=global_entities_json,
        inter_episode_physical_snapshot_json=json.dumps(previous_pickup or {}, ensure_ascii=False, indent=2) if previous_pickup else "无（本集为首集或无上一集物理接棒残留）",
        screenplay_text=screenplay_text if screenplay_text else "（无独立文学剧本文本）",
    )

    logger.debug("【阶段 6 执行节点】向大模型发送纯剧本多维高保真盲抽指令 (提示词总长度: %s 字符)...", len(user_prompt))

    _call_llm_fn = getattr(stage6_facade, "call_llm_json", call_llm_json)
    result_json = _call_llm_fn(
        user_prompt=user_prompt,
        system_prompt=STAGE6_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage6_fallback(
            episode_num=ep_num,
            script_data=script,
            characters_engine=chars_engine,
            envs_props=envs_props,
            existing_registry=registry,
            scanner_result=scanner_result,
            visual_style=visual_style,
            aspect_ratio=aspect_ratio,
            episode_title=episode_title,
            candidates=candidates,
        ),
    )

    manifest_data = (
        result_json.get("episode_resource_manifest")
        or result_json.get("manifest")
        or {}
    )

    # -------------------------------------------------------------------------
    # 步骤 3.5：提取并规范化本集发现的阶段2未登记新角色 (Stage-2 11维标准建档)
    # -------------------------------------------------------------------------
    raw_new_chars = (
        result_json.get("newly_discovered_characters")
        or manifest_data.get("newly_discovered_characters")
        or []
    )
    registered_names_node: set[str] = {
        str(c.get("name") or "").strip()
        for c in char_list
        if isinstance(c, dict) and c.get("name")
    }
    existing_char_codes_node: set[str] = {
        f"CHAR_{tok}" for tok in char_tokens if tok
    }
    used_archetypes_node: set[str] = {
        str(c.get("timbre_archetype"))
        for c in char_list
        if isinstance(c, dict) and c.get("timbre_archetype")
    }
    primary_prot_code = "CHAR_PROTAGONIST"
    primary_prot_name = "主角"
    for idx_c, c_item in enumerate(char_list):
        if isinstance(c_item, dict) and (idx_c == 0 or c_item.get("role_type") == "protagonist" or c_item.get("role") == "main"):
            if c_item.get("name"):
                primary_prot_name = str(c_item["name"])
            if c_item.get("character_id") or c_item.get("character_code"):
                raw_cc = str(c_item.get("character_code") or c_item.get("character_id"))
                primary_prot_code = raw_cc if raw_cc.startswith("CHAR_") else f"CHAR_{raw_cc}"
            break

    normalized_new_chars: list[dict[str, Any]] = []
    for nc_idx, nc_item in enumerate(raw_new_chars if isinstance(raw_new_chars, list) else [], start=1):
        if not isinstance(nc_item, dict):
            continue
        nc_name = str(nc_item.get("name") or nc_item.get("character_name") or "").strip()
        if not nc_name or nc_name in registered_names_node:
            continue
        if not is_valid_character_speaker(nc_name, known_names=registered_names_node):
            logger.debug("【阶段 6 新角色过滤】跳过大模型误报的非具名角色/舞台指令标识: %s", nc_name)
            continue
        # 使用保底11维建档器补齐缺失字段，同时保留大模型已生成的精细设定
        base_dossier = _build_stage2_character_dossier(
            char_name=nc_name,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_char_codes=existing_char_codes_node,
            used_archetypes=used_archetypes_node,
            primary_protagonist_code=primary_prot_code,
            primary_protagonist_name=primary_prot_name,
            index_hint=len(char_list) + nc_idx,
        )
        merged_dossier = {**base_dossier, **{k: v for k, v in nc_item.items() if v not in (None, "", [], {})}}
        # 确保合并后的关键 JSON 结构化字段保持 dict/list 类型
        if not isinstance(merged_dossier.get("visual_consistency_code"), dict):
            merged_dossier["visual_consistency_code"] = base_dossier["visual_consistency_code"]
        if isinstance(merged_dossier.get("identity_anchors"), str):
            raw_ia = merged_dossier["identity_anchors"].strip()
            merged_dossier["identity_anchors"] = [x.strip() for x in re.split(r"[|｜,，;；]", raw_ia) if x.strip()] or base_dossier["identity_anchors"]
        raw_cc = str(merged_dossier.get("character_code") or merged_dossier.get("character_id") or base_dossier["character_code"]).strip().upper()
        if not raw_cc.startswith("CHAR_"):
            raw_cc = f"CHAR_{re.sub(r'[^A-Z0-9]+', '', raw_cc)}"
        merged_dossier["character_code"] = raw_cc
        merged_dossier["character_id"] = raw_cc
        tok_nc = raw_cc.replace("CHAR_", "", 1)
        char_tokens.add(tok_nc)
        existing_char_codes_node.add(raw_cc)
        registered_names_node.add(nc_name)
        normalized_new_chars.append(merged_dossier)
        char_list.append(merged_dossier)
        logger.debug(
            "【阶段 6 新角色建档】已标准化第 %d 集新发现角色 [%s] (%s), 11维全息字段完备",
            ep_num, nc_name, raw_cc,
        )

    # 若扫描算子检测到未注册具名角色但大模型漏报，执行确定性补录兜底
    for det_idx, det_name in enumerate(present_chars, start=1):
        clean_det = str(det_name or "").strip()
        if not clean_det or clean_det in registered_names_node:
            continue
        if not is_valid_character_speaker(clean_det, known_names=registered_names_node):
            logger.debug("【阶段 6 新角色自动兜底过滤】跳过非具名角色/舞台指令标识: %s", clean_det)
            continue
        # 严格使用在场判定脱敏核验（防止死者如苏秀兰或案卷媒介词被兜底机制建档为新角色）
        if not is_character_truly_in_screenplay(clean_det, screenplay_text, present_chars):
            logger.debug("【阶段 6 新角色自动兜底过滤】候选人 [%s] 经脱敏核验未真实在场，放弃补录", clean_det)
            continue
        auto_dossier = _build_stage2_character_dossier(
            char_name=clean_det,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_char_codes=existing_char_codes_node,
            used_archetypes=used_archetypes_node,
            primary_protagonist_code=primary_prot_code,
            primary_protagonist_name=primary_prot_name,
            index_hint=len(char_list) + det_idx,
        )
        tok_nc = auto_dossier["character_code"].replace("CHAR_", "", 1)
        char_tokens.add(tok_nc)
        registered_names_node.add(clean_det)
        normalized_new_chars.append(auto_dossier)
        char_list.append(auto_dossier)
        logger.info(
            "【阶段 6 新角色自动兜底补录】扫描算子捕获第 %d 集未登记角色 [%s] -> 自动按阶段2标准建档 [%s]",
            ep_num, clean_det, auto_dossier["character_code"],
        )

    # -------------------------------------------------------------------------
    # 步骤 3.6：提取并规范化本集发现的阶段3未登记新场景与新道具 (Stage-3 3-Tier 标准建档)
    # -------------------------------------------------------------------------
    raw_new_scenes = (
        result_json.get("newly_discovered_scenes")
        or manifest_data.get("newly_discovered_scenes")
        or []
    )
    registered_scene_names_node: set[str] = {
        str(s.get("name") or s.get("location_name") or s.get("scene_name") or "").strip()
        for s in scene_list
        if isinstance(s, dict) and (s.get("name") or s.get("location_name") or s.get("scene_name"))
    }
    existing_scene_codes_node: set[str] = {
        str(s.get("scene_code") or s.get("env_id") or s.get("scene_id") or "").strip().upper()
        for s in scene_list
        if isinstance(s, dict) and (s.get("scene_code") or s.get("env_id") or s.get("scene_id"))
    }
    for tok in scene_tokens:
        if tok:
            existing_scene_codes_node.add(f"ENV_{tok}")

    normalized_new_scenes: list[dict[str, Any]] = []
    for ns_idx, ns_item in enumerate(raw_new_scenes if isinstance(raw_new_scenes, list) else [], start=1):
        if not isinstance(ns_item, dict):
            continue
        ns_name = str(ns_item.get("name") or ns_item.get("location_name") or ns_item.get("scene_name") or "").strip()
        if not ns_name or ns_name in registered_scene_names_node:
            continue
        # 获取扫描算子识别到的该场景子区域 (如: Z01, 卫生间, 收银台)
        detected_zones_for_scene = scanner_result.scene_zones_detected.get(ns_name, []) if scanner_result else []
        base_scene_dossier = _build_stage3_scene_dossier(
            scene_name=ns_name,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_scene_codes=existing_scene_codes_node,
            visual_style=visual_style,
            index_hint=len(scene_list) + ns_idx,
            detected_zones=detected_zones_for_scene,
        )
        merged_scene_dossier = {**base_scene_dossier, **{k: v for k, v in ns_item.items() if v not in (None, "", [], {})}}
        raw_sc = str(merged_scene_dossier.get("scene_code") or merged_scene_dossier.get("env_id") or base_scene_dossier["scene_code"]).strip().upper()
        if not raw_sc.startswith("ENV_"):
            raw_sc = f"ENV_{re.sub(r'[^A-Z0-9]+', '', raw_sc)}"
        merged_scene_dossier["scene_code"] = raw_sc
        merged_scene_dossier["env_id"] = raw_sc
        tok_ns = raw_sc.replace("ENV_", "", 1)
        scene_tokens.add(tok_ns)
        existing_scene_codes_node.add(raw_sc)
        registered_scene_names_node.add(ns_name)
        normalized_new_scenes.append(merged_scene_dossier)
        scene_list.append(merged_scene_dossier)
        logger.debug(
            "【阶段 6 新场景建档】已标准化第 %d 集新发现场景 [%s] (%s), 三级层级结构完备",
            ep_num, ns_name, raw_sc,
        )

    # 若扫描算子检测到未登记场景，执行确定性补录兜底
    for s_idx, det_sname in enumerate(present_scenes, start=1):
        clean_sname = str(det_sname or "").strip()
        if not clean_sname or clean_sname in registered_scene_names_node:
            continue
        detected_zones_for_scene = scanner_result.scene_zones_detected.get(clean_sname, []) if scanner_result else []
        auto_scene_dossier = _build_stage3_scene_dossier(
            scene_name=clean_sname,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_scene_codes=existing_scene_codes_node,
            visual_style=visual_style,
            index_hint=len(scene_list) + s_idx,
            detected_zones=detected_zones_for_scene,
        )
        tok_ns = auto_scene_dossier["scene_code"].replace("ENV_", "", 1)
        scene_tokens.add(tok_ns)
        existing_scene_codes_node.add(auto_scene_dossier["scene_code"])
        registered_scene_names_node.add(clean_sname)
        normalized_new_scenes.append(auto_scene_dossier)
        scene_list.append(auto_scene_dossier)
        logger.info(
            "【阶段 6 新场景自动兜底补录】扫描算子捕获第 %d 集未登记场景 [%s] -> 自动按阶段3标准建档 [%s]",
            ep_num, clean_sname, auto_scene_dossier["scene_code"],
        )

    # 提取并规范化本集发现的新道具
    raw_new_props = (
        result_json.get("newly_discovered_props")
        or manifest_data.get("newly_discovered_props")
        or []
    )
    registered_prop_names_node: set[str] = {
        str(p.get("name") or p.get("prop_name") or "").strip()
        for p in prop_list
        if isinstance(p, dict) and (p.get("name") or p.get("prop_name"))
    }
    existing_prop_codes_node: set[str] = {
        str(p.get("prop_code") or p.get("prop_id") or "").strip().upper()
        for p in prop_list
        if isinstance(p, dict) and (p.get("prop_code") or p.get("prop_id"))
    }
    for tok in prop_tokens:
        if tok:
            existing_prop_codes_node.add(f"PROP_{tok}")

    normalized_new_props: list[dict[str, Any]] = []
    for np_idx, np_item in enumerate(raw_new_props if isinstance(raw_new_props, list) else [], start=1):
        if not isinstance(np_item, dict):
            continue
        np_name = str(np_item.get("name") or np_item.get("prop_name") or "").strip()
        if not np_name or np_name in registered_prop_names_node:
            continue
        base_prop_dossier = _build_stage3_prop_dossier(
            prop_name=np_name,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_prop_codes=existing_prop_codes_node,
            visual_style=visual_style,
            index_hint=len(prop_list) + np_idx,
        )
        merged_prop_dossier = {**base_prop_dossier, **{k: v for k, v in np_item.items() if v not in (None, "", [], {})}}
        raw_pc = str(merged_prop_dossier.get("prop_code") or merged_prop_dossier.get("prop_id") or base_prop_dossier["prop_code"]).strip().upper()
        if not raw_pc.startswith("PROP_"):
            raw_pc = f"PROP_{re.sub(r'[^A-Z0-9]+', '', raw_pc)}"
        merged_prop_dossier["prop_code"] = raw_pc
        merged_prop_dossier["prop_id"] = raw_pc
        tok_np = raw_pc.replace("PROP_", "", 1)
        prop_tokens.add(tok_np)
        existing_prop_codes_node.add(raw_pc)
        registered_prop_names_node.add(np_name)
        normalized_new_props.append(merged_prop_dossier)
        prop_list.append(merged_prop_dossier)
        logger.debug(
            "【阶段 6 新道具建档】已标准化第 %d 集新发现道具 [%s] (%s), 三级层级结构完备",
            ep_num, np_name, raw_pc,
        )

    # 若扫描算子检测到未登记道具，执行确定性补录兜底
    for p_idx, det_pname in enumerate(present_props, start=1):
        clean_pname = str(det_pname or "").strip()
        if not clean_pname or clean_pname in registered_prop_names_node:
            continue
        auto_prop_dossier = _build_stage3_prop_dossier(
            prop_name=clean_pname,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_prop_codes=existing_prop_codes_node,
            visual_style=visual_style,
            index_hint=len(prop_list) + p_idx,
        )
        tok_np = auto_prop_dossier["prop_code"].replace("PROP_", "", 1)
        prop_tokens.add(tok_np)
        existing_prop_codes_node.add(auto_prop_dossier["prop_code"])
        registered_prop_names_node.add(clean_pname)
        normalized_new_props.append(auto_prop_dossier)
        prop_list.append(auto_prop_dossier)
        logger.info(
            "【阶段 6 新道具自动兜底补录】扫描算子捕获第 %d 集未登记道具 [%s] -> 自动按阶段3标准建档 [%s]",
            ep_num, clean_pname, auto_prop_dossier["prop_code"],
        )

    # 规范化与底图血统补齐
    raw_chars = (
        manifest_data.get("characters")
        or manifest_data.get("character_assets")
        or []
    )
    raw_envs = (
        manifest_data.get("environments")
        or manifest_data.get("scene_assets")
        or []
    )
    raw_props = (
        manifest_data.get("props")
        or manifest_data.get("prop_assets")
        or []
    )

    default_char_tok = next(iter(char_tokens)) if char_tokens else "PROTAGONIST"
    default_scene_tok = next(iter(scene_tokens)) if scene_tokens else "MAINSCENE"
    default_prop_tok = next(iter(prop_tokens)) if prop_tokens else "EVIDENCE"

    norm_chars = []
    if isinstance(raw_chars, list):
        norm_chars = [
            _ensure_standard_asset(c, "CHAR", char_tokens, default_char_tok)
            for c in raw_chars
            if isinstance(c, dict)
        ]
    elif isinstance(raw_chars, dict):
        # 嵌套格式展开
        for tier_key in ["tier1_base", "tier2_performance", "tier3_special"]:
            for item in raw_chars.get(tier_key, []):
                if isinstance(item, dict):
                    norm_chars.append(_ensure_standard_asset(item, "CHAR", char_tokens, default_char_tok))

    # 【后置硬拦截防御】：过滤掉未在本集出场的角色资产（杜绝大模型格式补全幻觉）
    present_chars_pool = set(present_chars)
    if alias_map:
        present_chars_pool.update(alias_map.keys())
        present_chars_pool.update(alias_map.values())
    for pc in projected_chars:
        if isinstance(pc, dict) and pc.get("name"):
            present_chars_pool.add(str(pc["name"]).strip())

    filtered_norm_chars: list[dict[str, Any]] = []
    for c_asset in norm_chars:
        if is_character_truly_in_screenplay(
            char_entry=c_asset,
            screenplay_text=screenplay_text,
            detected_chars=present_chars_pool,
            alias_map=alias_map,
        ):
            filtered_norm_chars.append(c_asset)
        else:
            logger.warning(
                "【阶段 6 角色后置拦截】剔除未登场角色资产: %s (%s)",
                c_asset.get("asset_id") or c_asset.get("char_id"),
                c_asset.get("name"),
            )

    norm_envs = []
    if isinstance(raw_envs, list):
        norm_envs = [
            _ensure_standard_asset(e, "ENV", scene_tokens, default_scene_tok)
            for e in raw_envs
            if isinstance(e, dict)
        ]
    elif isinstance(raw_envs, dict):
        for tier_key in ["tier1_primary", "tier2_transitional"]:
            for item in raw_envs.get(tier_key, []):
                if isinstance(item, dict):
                    norm_envs.append(_ensure_standard_asset(item, "ENV", scene_tokens, default_scene_tok))

    norm_props = []
    if isinstance(raw_props, list):
        norm_props = [
            _ensure_standard_asset(p, "PROP", prop_tokens, default_prop_tok)
            for p in raw_props
            if isinstance(p, dict)
        ]
    elif isinstance(raw_props, dict):
        for tier_key in ["tier1_hero", "tier2_anchor", "tier3_atmospheric"]:
            for item in raw_props.get(tier_key, []):
                if isinstance(item, dict):
                    norm_props.append(_ensure_standard_asset(item, "PROP", prop_tokens, default_prop_tok))

    # =========================================================================
    # 【工业级神经-符号联动】执行 AssetTriggerOperatorEngine 确定性算子引擎
    # 严格落实【A. 角色四视角/情绪/光效/手部战损】、【B. 场景景别/OTS/插镜/关键帧】、【C. 道具一二级静动/随身绑定/杂物剔除】
    # =========================================================================
    logger.info("【阶段 6 算子引擎联动】开始执行资产触发算子判定与多级按需派生...")

    # A. 角色触发算子派生
    operator_derived_chars: list[dict[str, Any]] = []
    seen_char_asset_ids: set[str] = set()

    for c_base in filtered_norm_chars:
        c_name = c_base.get("name") or c_base.get("character_name") or "CHARACTER"
        clean_cn = _clean_name(c_name)
        c_tok = AssetProtocolHelper.normalize_token(clean_cn or c_name)
        canonical_cid = f"CHAR_{c_tok}"

        # 提取阶段标识代码（如 T1/T2/T3），默认一阶基准 T1
        c_stage = c_base.get("stage_code") or c_base.get("stage") or "T1"
        if not (isinstance(c_stage, str) and c_stage.startswith("T")):
            c_stage = "T1"

        # 调取算子引擎获取动态派生资产
        triggered_char_assets = AssetTriggerOperatorEngine.evaluate_character_assets(
            character_name=c_name,
            canonical_id=canonical_cid,
            semantic_data=c_base,
            screenplay_text=screenplay_text,
            stage_code=c_stage,
        )

        for ta in triggered_char_assets:
            aid = ta["asset_key"]
            if aid in seen_char_asset_ids:
                continue
            seen_char_asset_ids.add(aid)

            # 组装符合管线标准的资产对象
            derived_c = dict(c_base)
            derived_c["asset_id"] = aid
            derived_c["char_id"] = aid
            derived_c["stage_code"] = ta.get("stage_code", c_stage)
            derived_c["tier"] = ta.get("tier", "Tier1")
            derived_c["form"] = ta.get("form", f"{c_stage}_BASE" if f"{c_stage}_BASE" in aid or "BASE_PORTRAIT" in aid else "BASE")
            derived_c["trigger_reason"] = ta.get("trigger_reason", "")
            # 严格继承算子引擎计算出的阶梯血统 DAG 属性与控制网参数 (ControlNet OpenPose / FaceID / Inpaint)
            # 铁律：唯有 CHAR_*_T1_BASE 为纯 t2i (文生图)，其余全部为 i2i / controlnet 派生
            is_pure_t1_root = (
                aid.endswith("_T1_BASE") or aid.endswith("_T1_BASE_PORTRAIT")
            )
            derived_c["generation_mode"] = "t2i" if is_pure_t1_root else ta.get("generation_mode", "i2i")
            derived_c["is_benchmark"] = 1 if is_pure_t1_root else 0
            derived_c["denoise_strength"] = 0.0 if is_pure_t1_root else ta.get("denoise_strength", 0.40)
            derived_c["parent_asset_key"] = None if is_pure_t1_root else ta.get("parent_asset_key")
            derived_c["parent_asset_id"] = None if is_pure_t1_root else ta.get("parent_asset_key")
            derived_c["input_source_image"] = None if is_pure_t1_root else ta.get("input_source_image")
            derived_c["identity_reference"] = ta.get("identity_reference")
            derived_c["control_type"] = None if is_pure_t1_root else ta.get("control_type")
            operator_derived_chars.append(derived_c)

    if operator_derived_chars:
        norm_chars = operator_derived_chars
    else:
        norm_chars = filtered_norm_chars

    # B. 场景触发算子派生
    operator_derived_envs: list[dict[str, Any]] = []
    seen_env_asset_ids: set[str] = set()

    for e_base in norm_envs:
        e_name = e_base.get("name") or e_base.get("scene_name") or "MAINSCENE"
        clean_en = _clean_name(e_name)
        e_tok = AssetProtocolHelper.normalize_token(clean_en or e_name)
        canonical_eid = f"ENV_{e_tok}"

        triggered_env_assets = AssetTriggerOperatorEngine.evaluate_environment_assets(
            scene_name=e_name,
            canonical_id=canonical_eid,
            semantic_data=e_base,
            screenplay_text=screenplay_text,
        )

        for te in triggered_env_assets:
            aid = te["asset_key"]
            if aid in seen_env_asset_ids:
                continue
            seen_env_asset_ids.add(aid)

            derived_e = dict(e_base)
            derived_e["asset_id"] = aid
            derived_e["scene_id"] = aid
            derived_e["env_id"] = aid
            derived_e["tier"] = te.get("tier", "Tier1")
            derived_e["form"] = te.get("form", "WIDE")
            derived_e["trigger_reason"] = te.get("trigger_reason", "")
            derived_e["generation_mode"] = "t2i" if ("WIDE" in aid or "BASE" in aid) else "i2i"
            if derived_e["generation_mode"] == "i2i":
                derived_e["parent_asset_id"] = f"{canonical_eid}_T1_WIDE"
                derived_e["parent_asset_key"] = f"{canonical_eid}_T1_WIDE"
                derived_e["denoise_strength"] = 0.50
            operator_derived_envs.append(derived_e)

    if operator_derived_envs:
        norm_envs = operator_derived_envs

    # 【场景子机位 Zone 动态补全】：将扫描算子捕获的 scene_zones 实体化为二级机位资产，杜绝大模型漏抽
    existing_env_asset_ids = {
        str(e.get("asset_id") or e.get("scene_id") or "").strip()
        for e in norm_envs
        if isinstance(e, dict)
    }
    if scanner_result and isinstance(scanner_result.scene_zones_detected, dict):
        for parent_sname, z_list in scanner_result.scene_zones_detected.items():
            clean_ps = _clean_name(parent_sname)
            ps_tok = AssetProtocolHelper.normalize_token(clean_ps or parent_sname)
            for z_idx, z_name in enumerate(z_list, start=1):
                z_code = f"Z{z_idx:02d}"
                zone_asset_id = f"ENV_{ps_tok}_{z_code}_ZONE"
                if zone_asset_id not in existing_env_asset_ids:
                    existing_env_asset_ids.add(zone_asset_id)
                    zone_prompt = (
                        f"cinematic photorealistic 8k architectural environment, {parent_sname} {z_name} designated area, "
                        f"35mm cinematic anamorphic lens, localized spatial framing, realistic environmental textures, "
                        f"atmospheric lighting, visual style: {visual_style} --style raw"
                    )
                    norm_envs.append({
                        "asset_id": zone_asset_id,
                        "scene_id": zone_asset_id,
                        "env_id": f"ENV_{ps_tok}_{z_code}",
                        "name": f"{parent_sname}-{z_name}",
                        "location_name": f"{parent_sname}-{z_name}",
                        "tier": "T2",
                        "zone_code": z_code,
                        "function_type": "ZONE",
                        "visual_prompt": zone_prompt,
                        "image_prompt": zone_prompt,
                        "parent_asset_id": f"ENV_{ps_tok}_T1_WIDE",
                        "parent_asset_key": f"ENV_{ps_tok}_T1_WIDE",
                        "generation_mode": "i2i",
                        "denoise_strength": 0.40,
                        "lifecycle_status": AssetState.READY.value,
                    })
                    logger.info("【阶段 6 场景机位补全】将扫描到的子区域 [%s -> %s] 实体化为机位资产: %s", parent_sname, z_name, zone_asset_id)

    # C. 道具触发算子判定（一二级静动两态、随身绑定手部、三级杂物彻底剔除）
    operator_derived_props: list[dict[str, Any]] = []
    seen_prop_asset_ids: set[str] = set()

    for p_base in norm_props:
        p_name = p_base.get("name") or p_base.get("prop_name") or "EVIDENCE"
        clean_pn = _clean_name(p_name)
        p_tok = AssetProtocolHelper.normalize_token(clean_pn or p_name)
        canonical_pid = f"PROP_{p_tok}"

        prop_decision = AssetTriggerOperatorEngine.evaluate_prop_assets(
            prop_name=p_name,
            canonical_id=canonical_pid,
            semantic_data=p_base,
            screenplay_text=screenplay_text,
        )

        decision = prop_decision.get("decision")
        if decision == "EXCLUDED_AMBIENT":
            logger.info("【阶段 6 算子引擎·杂物拦截】道具 [%s] 判定为生活环境杂物，执行零独立生图剔除", p_name)
            continue
        elif decision == "BOUND_TO_CHARACTER_MACRO":
            assoc_char = prop_decision.get("bound_character")
            logger.info("【阶段 6 算子引擎·随身物挂靠】道具 [%s] 成功挂靠角色 [%s] T3 手部微距，免除独立生图", p_name, assoc_char)
            continue

        # 一级核心物证按生成的两态（静态/破坏态）登记
        for tp in prop_decision.get("assets", []):
            aid = tp["asset_key"]
            if aid in seen_prop_asset_ids:
                continue
            seen_prop_asset_ids.add(aid)

            derived_p = dict(p_base)
            derived_p["asset_id"] = aid
            derived_p["prop_id"] = aid
            derived_p["tier"] = tp.get("tier", "Tier1")
            derived_p["form"] = tp.get("form", "STATIC")
            derived_p["function_type"] = tp.get("form", "STATIC")
            derived_p["trigger_reason"] = tp.get("trigger_reason", "")
            derived_p["generation_mode"] = "t2i" if "STATIC" in aid else "i2i"
            if derived_p["generation_mode"] == "i2i":
                derived_p["parent_asset_id"] = f"{canonical_pid}_T1_STATIC"
                derived_p["parent_asset_key"] = f"{canonical_pid}_T1_STATIC"
                derived_p["denoise_strength"] = 0.55
            operator_derived_props.append(derived_p)

    if operator_derived_props:
        norm_props = operator_derived_props

    # 【手持交互物证标准 S0 补录】：确保动宾道具与核心物证均有稳定的静态材质底模
    existing_prop_names = {
        str(p.get("name") or p.get("prop_name") or "").strip()
        for p in norm_props
        if isinstance(p, dict)
    }
    existing_prop_ids = {
        str(p.get("asset_id") or p.get("prop_id") or "").strip()
        for p in norm_props
        if isinstance(p, dict)
    }
    candidates_to_enrich: list[str] = list(present_props)
    if scanner_result and isinstance(scanner_result.props_detected, list):
        candidates_to_enrich.extend(scanner_result.props_detected)

    for p_cand in candidates_to_enrich:
        clean_p = _clean_name(p_cand)
        if not clean_p or len(clean_p) < 2:
            continue
        p_tok = AssetProtocolHelper.normalize_token(clean_p)
        static_id = f"PROP_{p_tok}_T1_STATIC"
        if clean_p not in existing_prop_names and static_id not in existing_prop_ids:
            existing_prop_names.add(clean_p)
            existing_prop_ids.add(static_id)
            prop_prompt = (
                f"cinematic photorealistic 8k hero prop, {clean_p}, isolated hero prop studio shot, "
                f"resting firmly on textured dark wooden surface, 100mm macro lens, pristine condition, "
                f"ultra-sharp tactile material texture, soft directional studio lighting, "
                f"visual style: {visual_style} --style raw"
            )
            norm_props.append({
                "asset_id": static_id,
                "prop_id": static_id,
                "name": clean_p,
                "prop_name": clean_p,
                "tier": "T1",
                "function_type": "STATIC",
                "visual_prompt": prop_prompt,
                "image_prompt": prop_prompt,
                "parent_asset_id": None,
                "parent_asset_key": None,
                "generation_mode": "t2i",
                "is_benchmark": 1,
                "lifecycle_status": AssetState.READY.value,
            })
            logger.info("【阶段 6 交互物证补全】自动为手持交互物证 [%s] 补齐标准 S0 底模资产: %s", clean_p, static_id)

    # -------------------------------------------------------------------------
    # 步骤 4：资产四段式纠偏、生命周期状态标记与语义哈希指纹计算
    # -------------------------------------------------------------------------
    logger.info("【阶段 6 真理源】开始对第 %s 集资产执行四段式协议校验、生命周期状态初始化与语义指纹计算...", ep_num)

    all_chars = dict(registry.get("characters", {}) or {})
    all_envs = dict(registry.get("environments", {}) or {})
    all_props = dict(registry.get("props", {}) or {})
    all_voices = dict(registry.get("audio_tts", {}) or {})
    reused_history = dict(registry.get("reused_assets_history", {}) or {})

    # 提取或构建全局语义指纹索引 (asset_id <-> semantic_hash)
    semantic_hashes: dict[str, str] = dict(registry.get("semantic_hashes", {}) or {})
    hash_to_asset: dict[str, str] = dict(registry.get("hash_index", {}) or {})
    # 反向构建以确保已有库中资产均可索引
    for aid, h in semantic_hashes.items():
        if h and isinstance(h, str):
            hash_to_asset[h] = aid

    # 预载历史库资产以推导缺失哈希
    for existing_pool, cat in [(all_chars, "CHAR"), (all_envs, "ENV"), (all_props, "PROP"), (all_voices, "VOICE")]:
        for aid, item in existing_pool.items():
            if isinstance(item, dict):
                cur_h = item.get("semantic_hash")
                if not cur_h:
                    cur_h = compute_asset_semantic_hash(cat, aid, item.get("visual_prompt") or item.get("image_prompt") or "", item)
                    item["semantic_hash"] = cur_h
                semantic_hashes[aid] = cur_h
                hash_to_asset[cur_h] = aid
                item.setdefault("lifecycle_status", AssetState.APPROVED.value)

    # -------------------------------------------------------------------------
    # 步骤 5：本地规则矩阵生图提示词引擎合成 (PromptMatrixSynthesizer · 毫秒级零延迟)
    # 按 P0~P4 黄金插槽装配中国人/韩国人、80年代中国建筑/红砖筒子楼、剧情战损与光学焦段，彻底消灭占位符
    # -------------------------------------------------------------------------
    from app.workflows.utils.prompt_synthesizer import PromptMatrixSynthesizer

    for c in norm_chars:
        cid = c.get("asset_id") or c.get("char_id") or ""
        c_name = c.get("name") or "CHARACTER"
        c_form = c.get("form") or "T1_BASE"
        raw_cp = c.get("visual_prompt") or c.get("image_prompt") or ""

        # 查找匹配的角色全局档案 (用于提取人种、骨相、服饰设定)
        c_prof = all_chars.get(cid)
        if not c_prof:
            for ac_k, ac_v in all_chars.items():
                if isinstance(ac_v, dict) and ac_v.get("name") == c_name:
                    c_prof = ac_v
                    break

        # 提取动态物理切片 (包含四层解耦 Anchor: P_Face / P_Body / P_Cloth / P_Motion) 并利用 AssetSliceEnricher 与阶段 2 静态档案融合补全
        raw_motion_slice = {
            "facial_dna_anchor": c.get("facial_dna_anchor") or c.get("facial_bone_structure") or c.get("bone_structure") or "",
            "physique_body_anchor": c.get("physique_body_anchor") or c.get("body_proportions") or c.get("height_and_build") or "",
            "costume_material_anchor": c.get("costume_material_anchor") or c.get("costume_and_materials") or c.get("costume") or "",
            "plot_motion_slice": c.get("plot_motion_slice") or c.get("current_motion") or c.get("action_description") or "",
            "facial_bone_structure": c.get("facial_bone_structure") or c.get("bone_structure") or "",
            "costume_and_materials": c.get("costume_and_materials") or c.get("costume") or "",
            "current_motion": c.get("current_motion") or c.get("action_description") or "",
            "physical_wounds": c.get("battle_damage") or c.get("injury_details") or c.get("physical_wounds") or "",
            "emotional_expression": c.get("emotion") or c.get("micro_expression") or "",
            "relationship_tension": c.get("relationship_tension") or c.get("tension") or "",
            "microclimate_reaction": c.get("microclimate_reaction") or "",
            "timbre_archetype": c.get("timbre_archetype") or "",
            "regional_accent": c.get("regional_accent") or "",
            "acoustic_space": c.get("acoustic_space") or "",
        }
        logger.debug(
            "【阶段 6 执行节点】角色 [%s] 提取视听四维解耦切片: p_face=%s, p_body=%s, p_cloth=%s, p_motion=%s",
            c_name, bool(raw_motion_slice["facial_dna_anchor"]), bool(raw_motion_slice["physique_body_anchor"]), bool(raw_motion_slice["costume_material_anchor"]), bool(raw_motion_slice["plot_motion_slice"]),
        )
        motion_slice = AssetSliceEnricher.enrich_character_slice(raw_motion_slice, c_prof)

        # 规则矩阵引擎按 Token 优先级装配高质量生图提示词
        matrix_prompt = PromptMatrixSynthesizer.assemble_character_prompt(
            name=c_name,
            form=c_form,
            motion_slice=motion_slice,
            char_profile=c_prof,
            visual_style=visual_style,
        )

        c["visual_prompt"] = matrix_prompt
        c["image_prompt"] = matrix_prompt
        if not c.get("semantic_hash"):
            c["semantic_hash"] = compute_asset_semantic_hash("CHAR", cid, matrix_prompt, c)
        if cid in all_chars:
            c["lifecycle_status"] = AssetState.APPROVED.value
        else:
            c.setdefault("lifecycle_status", AssetState.READY.value)
        if cid and c.get("semantic_hash"):
            semantic_hashes[cid] = c["semantic_hash"]
            hash_to_asset[c["semantic_hash"]] = cid

    for e in norm_envs:
        eid = e.get("asset_id") or e.get("scene_id") or ""
        e_name = e.get("name") or "SCENE"
        e_form = e.get("form") or "T1_WIDE"
        raw_ep = e.get("visual_prompt") or e.get("image_prompt") or ""

        e_prof = all_envs.get(eid)
        if not e_prof:
            for ae_k, ae_v in all_envs.items():
                if isinstance(ae_v, dict) and ae_v.get("name") == e_name:
                    e_prof = ae_v
                    break

        raw_env_slice = {
            "architectural_style": e.get("architectural_style") or e.get("architecture") or "",
            "sub_zone_spot": e.get("sub_zone_spot") or e.get("zone_code") or "",
            "lighting_and_atmosphere": e.get("lighting_and_atmosphere") or e.get("lighting") or "",
            "scene_traces": e.get("narrative_traces") or e.get("trace") or "",
        }
        env_slice = AssetSliceEnricher.enrich_environment_slice(raw_env_slice, e_prof)

        matrix_env_prompt = PromptMatrixSynthesizer.assemble_environment_prompt(
            name=e_name,
            form=e_form,
            env_slice=env_slice,
            env_profile=e_prof,
            visual_style=visual_style,
        )

        e["visual_prompt"] = matrix_env_prompt
        e["image_prompt"] = matrix_env_prompt
        if not e.get("semantic_hash"):
            e["semantic_hash"] = compute_asset_semantic_hash("ENV", eid, matrix_env_prompt, e)
        if eid in all_envs:
            e["lifecycle_status"] = AssetState.APPROVED.value
        else:
            e.setdefault("lifecycle_status", AssetState.READY.value)
        if eid and e.get("semantic_hash"):
            semantic_hashes[eid] = e["semantic_hash"]
            hash_to_asset[e["semantic_hash"]] = eid

    for p in norm_props:
        pid = p.get("asset_id") or p.get("prop_id") or ""
        p_name = p.get("name") or "PROP"
        p_form = p.get("form") or "S0_STATIC"
        raw_pp = p.get("visual_prompt") or p.get("image_prompt") or ""

        p_prof = all_props.get(pid)
        if not p_prof:
            for ap_k, ap_v in all_props.items():
                if isinstance(ap_v, dict) and ap_v.get("name") == p_name:
                    p_prof = ap_v
                    break

        raw_prop_slice = {
            "material_details": p.get("material_details") or p.get("material") or "",
            "placement_surface": p.get("placement_surface") or p.get("surface") or "",
            "damage_state": p.get("damage_state") or "",
            "wear_and_tear": p.get("wear_and_tear") or "",
        }
        prop_slice = AssetSliceEnricher.enrich_prop_slice(raw_prop_slice, p_prof)

        matrix_prop_prompt = PromptMatrixSynthesizer.assemble_prop_prompt(
            name=p_name,
            form=p_form,
            prop_slice=prop_slice,
            prop_profile=p_prof,
            visual_style=visual_style,
        )

        p["visual_prompt"] = matrix_prop_prompt
        p["image_prompt"] = matrix_prop_prompt
        if not p.get("semantic_hash"):
            p["semantic_hash"] = compute_asset_semantic_hash("PROP", pid, matrix_prop_prompt, p)
        if pid in all_props:
            p["lifecycle_status"] = AssetState.APPROVED.value
        else:
            p.setdefault("lifecycle_status", AssetState.READY.value)
        if pid and p.get("semantic_hash"):
            semantic_hashes[pid] = p["semantic_hash"]
            hash_to_asset[p["semantic_hash"]] = pid

    # 将规范化结果注入 manifest_data
    if isinstance(raw_chars, list):
        manifest_data["characters"] = norm_chars
    if isinstance(raw_envs, list):
        manifest_data["environments"] = norm_envs
    if isinstance(raw_props, list):
        manifest_data["props"] = norm_props
    manifest_data.setdefault("episode_num", ep_num)
    manifest_data.setdefault("episode_title", episode_title)
    manifest_data.setdefault("aspect_ratio", aspect_ratio)

    # -------------------------------------------------------------------------
    # 步骤 5：跨集语义去重与生命周期状态机驱动
    # -------------------------------------------------------------------------
    reused_list = result_json.get("reused_existing_assets") or []
    current_ep_reused: list[str] = []
    for r in reused_list:
        rid = r.get("asset_id") if isinstance(r, dict) else getattr(r, "asset_id", "")
        if rid:
            current_ep_reused.append(rid)
            if isinstance(r, dict):
                r.setdefault("lifecycle_status", AssetState.APPROVED.value)
                r.setdefault("status", "APPROVED")

    raw_newly_list = result_json.get("newly_generated_assets") or []
    # 【核心修复】：将算子引擎动态派生出的核心登场角色/场景/道具资产（尤其是 CHAR_*_T1_BASE 根基准图）
    # 严格对齐注入 raw_newly_list，避免仅大模型输出的新增清单被纳入，确保 T1_BASE 100% 纳入增量资产与落库
    seen_raw_newly_ids = {
        (n.get("asset_id") if isinstance(n, dict) else getattr(n, "asset_id", ""))
        for n in raw_newly_list
    }
    # 汇总全局资产库已存在 ID 以及当集已转入复用池的资产 ID，绝不把已有/复用资产重新塞入待生成清单
    existing_reg_ids: set[str] = set()
    if isinstance(registry, dict):
        for sub_cat in ("characters", "environments", "props", "audio_tts"):
            sub_dict = registry.get(sub_cat)
            if isinstance(sub_dict, dict):
                existing_reg_ids.update(sub_dict.keys())
        for k, v in registry.items():
            if isinstance(v, dict) and ("asset_id" in v or "tier" in v or "generation_mode" in v or "char_id" in v or "prop_id" in v or "scene_id" in v):
                existing_reg_ids.add(k)
            elif isinstance(k, str) and (k.startswith("CHAR_") or k.startswith("ENV_") or k.startswith("PROP_") or k.startswith("VOICE_")):
                existing_reg_ids.add(k)
    known_existing_or_reused = existing_reg_ids | set(current_ep_reused)

    for c_op in norm_chars:
        cid = c_op.get("asset_id") or c_op.get("char_id")
        if cid and cid not in seen_raw_newly_ids and cid not in known_existing_or_reused:
            seen_raw_newly_ids.add(cid)
            raw_newly_list.append(dict(c_op))

    for e_op in norm_envs:
        eid = e_op.get("asset_id") or e_op.get("scene_id")
        if eid and eid not in seen_raw_newly_ids and eid not in known_existing_or_reused:
            seen_raw_newly_ids.add(eid)
            raw_newly_list.append(dict(e_op))

    for p_op in norm_props:
        pid = p_op.get("asset_id") or p_op.get("prop_id")
        if pid and pid not in seen_raw_newly_ids and pid not in known_existing_or_reused:
            seen_raw_newly_ids.add(pid)
            raw_newly_list.append(dict(p_op))

    deduped_newly_list: list[dict[str, Any]] = []

    for n in raw_newly_list:
        n_dict = n if isinstance(n, dict) else n.to_dict() if hasattr(n, "to_dict") else dict(n)
        nid = n_dict.get("asset_id") or ""
        if not nid:
            continue

        cat = (
            "CHAR" if nid.startswith("CHAR_")
            else "ENV" if nid.startswith("ENV_")
            else "PROP" if nid.startswith("PROP_")
            else "VOICE" if nid.startswith("VOICE_")
            else "ASSET"
        )
        nhash = n_dict.get("semantic_hash")
        if not nhash:
            nhash = compute_asset_semantic_hash(cat, nid, n_dict.get("image_prompt") or n_dict.get("visual_prompt") or "", n_dict)
            n_dict["semantic_hash"] = nhash

        # 检查是否命中跨集语义哈希指纹去重（即相同提示词/特性的资产在历史集中已存在）
        existing_matched_id = hash_to_asset.get(nhash)
        if existing_matched_id and existing_matched_id != nid:
            logger.info(
                "【阶段 6 真理源·跨集语义去重】资产 [%s] (语义指纹 %s) 命中历史真理源已登记资产 [%s]，跳过重复生成并转入复用池",
                nid, nhash, existing_matched_id,
            )
            reused_list.append({
                "asset_id": existing_matched_id,
                "type": n_dict.get("asset_category") or "semantic_dedup_reused",
                "usage_in_current_ep": f"语义指纹 {nhash} 命中全局真理源 {existing_matched_id}，转入只读复用",
                "status": "APPROVED",
                "lifecycle_status": AssetState.APPROVED.value,
                "semantic_hash": nhash,
            })
            if existing_matched_id not in current_ep_reused:
                current_ep_reused.append(existing_matched_id)
            continue

        # 未命中跨集重复：正式作为增量生成项，初始生命周期为 READY
        n_dict.setdefault("lifecycle_status", AssetState.READY.value)

        # 补全DAG与四维提示词元数据 (强力防线：严防二阶/三阶资产退化为文生图 t2i)
        dep = AssetProtocolHelper.resolve_dependency(nid)
        cur_parsed = AssetProtocolHelper.parse_id(nid)

        if dep.generation_mode != "t2i":
            # 非一阶基准根节点：强制设为协议决定的衍生模式 (i2i / controlnet / inpaint)，绝不信任 LLM 幻觉生成的 t2i
            p_cand = n_dict.get("parent_asset_key") or n_dict.get("parent_asset_id") or dep.parent_asset_id
            if p_cand and cur_parsed and cur_parsed.category == "CHAR":
                p_parsed = AssetProtocolHelper.parse_id(p_cand)
                if p_parsed and p_parsed.category == "CHAR" and p_parsed.token != cur_parsed.token:
                    logger.warning(
                        "【阶段 6 增量资产纠偏·防跨角色污染】检测到角色资产 [%s] (token=%s) 错配父资产 [%s] (token=%s)，自动纠偏为同角色基准底模 [%s]",
                        nid, cur_parsed.token, p_cand, p_parsed.token, dep.parent_asset_id,
                    )
                    p_cand = dep.parent_asset_id
            if not p_cand:
                p_cand = dep.parent_asset_id

            # 强校验：严禁 parent_asset_key 与自身 nid 相同 (防止自循环 self-parenting)
            if p_cand == nid:
                logger.warning("【阶段 6 资产自引拦截】检测到资产 [%s] 产生 self-parenting 自引现象，重置父资产", nid)
                if cur_parsed and cur_parsed.category == "CHAR":
                    t1_root = f"CHAR_{cur_parsed.token}_T1_BASE"
                    p_cand = t1_root if nid != t1_root else None
                else:
                    p_cand = None

            # 强制覆盖，禁止 setdefault 保留非法的 t2i
            orig_mode = n_dict.get("generation_mode")
            if orig_mode == "t2i":
                logger.info("【阶段 6 资产模式纠偏】检测到二阶/三阶资产 [%s] 错误声明为 t2i，强制纠偏为 %s 并挂载父资产 [%s]", nid, dep.generation_mode, p_cand)
            n_dict["generation_mode"] = dep.generation_mode
            n_dict["parent_asset_key"] = p_cand
            n_dict["parent_asset_id"] = p_cand
            n_dict["is_benchmark"] = 0
            n_dict["denoise_strength"] = dep.recommended_denoise if n_dict.get("denoise_strength") is None else n_dict.get("denoise_strength")
        else:
            # 真正的一阶基准根节点 (T1 / Z01 / S0)
            n_dict["generation_mode"] = "t2i"
            n_dict["parent_asset_key"] = None
            n_dict["parent_asset_id"] = None
            n_dict["is_benchmark"] = 1 if dep.is_benchmark else 0
            n_dict["denoise_strength"] = dep.recommended_denoise

        n_dict.setdefault("control_type", dep.control_type)
        cat_key = "character" if nid.startswith("CHAR_") else "scene" if nid.startswith("ENV_") else "prop" if nid.startswith("PROP_") else "audio" if nid.startswith("VOICE_") else "default"
        n_dict.setdefault("negative_prompt", PromptSynthesizer.get_category_negative_prompt(cat_key))

        # 【剧情感官提示词自动化增强与去占位符】：融合当集剧本上下文，杜绝模板化套话
        # 【物理隔离防线】：对于一阶基准纯面部肖像 (is_benchmark==1 且为 CHAR 根节点)，严禁注入单集剧情动态 (战损、微表情、鞋履接地等)，保持 FaceID 纯净性
        raw_prompt = n_dict.get("image_prompt") or n_dict.get("visual_prompt") or ""
        is_pure_face_benchmark = (
            nid.startswith("CHAR_")
            and (
                bool(n_dict.get("is_benchmark"))
                or nid.endswith("_T1_BASE")
                or nid.endswith("_T1_BASE_PORTRAIT")
                or n_dict.get("form") in ("T1_BASE", "BASE_PORTRAIT", "BASE")
            )
        )
        if is_pure_face_benchmark:
            logger.debug("【阶段 6 执行节点】资产 [%s] 属于一阶纯面部基准，阻断单集剧情/战损/站姿增强注入", nid)
            enriched_prompt = raw_prompt
        else:
            narrative_ctx = {
                "emotion": n_dict.get("emotion") or n_dict.get("micro_expression"),
                "battle_damage": n_dict.get("battle_damage") or n_dict.get("injury_details"),
                "weather": n_dict.get("weather") or "",
                "time_lighting": (", ".join(scanner_result.lighting_conditions) if (scanner_result and scanner_result.lighting_conditions) else (n_dict.get("lighting") or "")) or "",
                "narrative_traces": n_dict.get("narrative_traces") or n_dict.get("trace"),
                "placement_surface": n_dict.get("placement_surface") or n_dict.get("surface"),
                "wear_and_tear": n_dict.get("wear_and_tear") or n_dict.get("damage"),
            }
            enriched_prompt = PromptSynthesizer.enrich_narrative_prompt(
                base_prompt=raw_prompt,
                category=cat_key,
                narrative_context=narrative_ctx,
                visual_style=visual_style,
            )
        n_dict["image_prompt"] = enriched_prompt
        n_dict["visual_prompt"] = enriched_prompt
        n_dict.setdefault("identity_prompt", enriched_prompt)
        n_dict.setdefault("delta_prompt", "")

        deduped_newly_list.append(n_dict)

        # 纳入全局索引与真理源库
        semantic_hashes[nid] = nhash
        hash_to_asset[nhash] = nid

        if nid.startswith("CHAR_") and nid not in all_chars:
            all_chars[nid] = n_dict
        elif nid.startswith("ENV_") and nid not in all_envs:
            all_envs[nid] = n_dict
        elif nid.startswith("PROP_") and nid not in all_props:
            all_props[nid] = n_dict

    reused_history[ep_num] = current_ep_reused

    # 兜底：同步 norm 资产项中未注册项
    for c in norm_chars:
        cid = c.get("asset_id") or c.get("char_id")
        if cid and cid not in all_chars:
            all_chars[cid] = c

    for e in norm_envs:
        eid = e.get("asset_id") or e.get("scene_id")
        if eid and eid not in all_envs:
            all_envs[eid] = e

    for p in norm_props:
        pid = p.get("asset_id") or p.get("prop_id")
        if pid and pid not in all_props:
            all_props[pid] = p

    # =========================================================================
    # 3. 新角色母音频卡片建档 (V2 精细化音色卡校验与单集登场白名单守卫)
    # =========================================================================
    # 【单集在场严格白名单守卫】：杜绝全剧未登场角色渗透进当集音色卡表 (character_voice_profiles)
    active_present_char_names: set[str] = set()
    active_present_char_codes: set[str] = set()

    for fc in filtered_norm_chars:
        if not isinstance(fc, dict):
            continue
        fc_name = str(fc.get("name") or fc.get("character_name") or "").strip()
        fc_code = str(fc.get("character_code") or fc.get("character_id") or fc.get("char_id") or fc.get("asset_id") or "").strip().upper()
        clean_fcn = _clean_name(fc_name)
        if clean_fcn:
            active_present_char_names.add(clean_fcn)
        if fc_name:
            active_present_char_names.add(fc_name)
        if fc_code:
            active_present_char_codes.add(fc_code)
            # 兼容 CHAR_ 前缀剥离匹配
            if fc_code.startswith("CHAR_"):
                active_present_char_codes.add(fc_code[5:])

    # 补充 present_chars_pool 确保包含剧本扫描器识别的角色
    for pcn in present_chars_pool:
        if pcn and str(pcn).strip():
            active_present_char_names.add(_clean_name(str(pcn).strip()))
            active_present_char_names.add(str(pcn).strip())

    logger.info(
        "【阶段 6 音色单集门禁】确立当集有效登场角色白名单: 名字集=%s, 代码集=%s",
        active_present_char_names, active_present_char_codes,
    )

    def _is_character_present_in_episode(cand_name: str, cand_code: str) -> bool:
        """判定该角色是否真实在当集登场 (白名单匹配与剧本真值校验)"""
        clean_cn = _clean_name(cand_name) if cand_name else ""
        c_code_clean = cand_code.upper().strip() if cand_code else ""
        
        # 1. 命中显式白名单
        if (clean_cn and clean_cn in active_present_char_names) or (cand_name and cand_name in active_present_char_names):
            return True
        if c_code_clean and (c_code_clean in active_present_char_codes or c_code_clean.replace("CHAR_", "") in active_present_char_codes):
            return True
            
        # 2. 备用兜底：若白名单空（极罕见），回退剧本直接文本检索
        if cand_name and is_character_truly_in_screenplay(
            char_entry={"name": cand_name, "character_code": cand_code},
            screenplay_text=screenplay_text,
            detected_chars=present_chars_pool,
            alias_map=alias_map,
        ):
            return True
        return False

    raw_voice_cards = result_json.get("new_character_master_voice_cards") or []
    voice_cards: list[dict[str, Any]] = []
    for vc_idx, vc in enumerate(raw_voice_cards, start=1):
        vc_dict = vc if isinstance(vc, dict) else vc.model_dump() if hasattr(vc, "model_dump") else dict(vc)
        vid = vc_dict.get("master_voice_id") or vc_dict.get("voice_id") or ""
        c_code = str(vc_dict.get("character_code") or vc_dict.get("character_id") or "").strip().upper()
        if not c_code and vid.startswith("VOICE_"):
            parts_v = vid.split("_")
            if len(parts_v) >= 2:
                c_code = f"CHAR_{parts_v[1]}"
        if c_code and not c_code.startswith("CHAR_"):
            c_code = f"CHAR_{re.sub(r'[^A-Z0-9]+', '', c_code)}"
        if not vid and c_code:
            vid = f"VOICE_{c_code.replace('CHAR_', '', 1)}_T1_MASTER"

        if vid:
            vc_dict["master_voice_id"] = vid
            vc_dict["character_id"] = c_code or vc_dict.get("character_id") or "CHAR_PROTAGONIST"
            vc_dict["character_code"] = vc_dict["character_id"]

            # 查找对应角色档案以补齐音色原型与名称
            matched_char_info: dict[str, Any] = {}
            for c_item in filtered_norm_chars:
                if isinstance(c_item, dict):
                    item_cc = str(c_item.get("character_code") or c_item.get("character_id") or c_item.get("char_id") or "").upper()
                    if item_cc == vc_dict["character_code"] or vc_dict["character_code"].endswith(item_cc):
                        matched_char_info = c_item
                        break

            if not vc_dict.get("character_name"):
                vc_dict["character_name"] = (
                    matched_char_info.get("name")
                    or matched_char_info.get("character_name")
                    or vc_dict["character_code"].replace("CHAR_", "")
                )

            vc_cname = str(vc_dict.get("character_name") or "").strip()
            # 【门禁拦截】：大模型输出的音色卡若属于未登场角色，坚决剔除
            if not _is_character_present_in_episode(vc_cname, vc_dict["character_code"]):
                logger.warning(
                    "【阶段 6 音色门禁拦截】剔除大模型生成的未登场角色音色卡: %s (%s, %s)",
                    vc_cname, vc_dict["character_code"], vid,
                )
                continue

            arch = _select_voice_archetype(matched_char_info or vc_dict, used_archetypes_node, index_hint=vc_idx)
            vc_dict.setdefault("timbre", matched_char_info.get("timbre") or arch["timbre"])
            vc_dict.setdefault("timbre_archetype", matched_char_info.get("timbre_archetype") or arch["timbre_archetype"])
            vc_dict.setdefault("vocal_position", arch["vocal_position"])
            vc_dict.setdefault("vocal_flaws", arch["vocal_flaws"])
            vc_dict.setdefault("speed_ratio", float(arch["speed_ratio"]))
            vc_dict.setdefault("pitch_ratio", float(arch["pitch_ratio"]))
            vc_dict.setdefault("tts_provider", "minimax")
            vc_dict.setdefault("tts_model", "speech-02-hd")
            vc_dict.setdefault("provider_voice_id", arch["provider_voice_id"])
            vc_dict.setdefault("timber_weights", arch["timber_weights"])

            raw_mono = (
                vc_dict.get("master_sample_text")
                or vc_dict.get("script_monologue_source")
                or vc_dict.get("sample_line")
                or ""
            )
            vc_dict["master_sample_text"] = _strip_dialogue_brackets(
                raw_mono, character_name=str(vc_dict.get("character_name") or "角色")
            )
            if not vc_dict.get("script_monologue_source"):
                vc_dict["script_monologue_source"] = raw_mono or vc_dict["master_sample_text"]

            if not vc_dict.get("master_tts_prompt"):
                vc_dict["master_tts_prompt"] = (
                    f"{vc_dict['timbre']}，{vc_dict['vocal_position']}，{vc_dict['vocal_flaws']}，"
                    f"语速倍率{float(vc_dict['speed_ratio']):.2f}，音高倍率{float(vc_dict['pitch_ratio']):.2f}"
                )
            if not vc_dict.get("voice_prompt"):
                vc_dict["voice_prompt"] = vc_dict["master_tts_prompt"]
            if not vc_dict.get("voice_file_path") or vc_dict["voice_file_path"].endswith(".wav"):
                vc_dict["voice_file_path"] = f"storage/audio/voices/{vid}.mp3"

            raw_emo = vc_dict.get("emotion_rules")
            if not isinstance(raw_emo, dict) or not raw_emo:
                vc_dict["emotion_rules"] = _build_default_emotion_rules()
            else:
                # 剔除混音侧链闪避污染字段 bgm_ducking_db
                vc_dict["emotion_rules"] = {
                    ek: {k: v for k, v in ev.items() if k != "bgm_ducking_db"} if isinstance(ev, dict) else ev
                    for ek, ev in raw_emo.items()
                }

            vc_hash = vc_dict.get("semantic_hash") or compute_asset_semantic_hash(
                "VOICE", vid, vc_dict.get("master_tts_prompt", ""), vc_dict
            )
            vc_dict["semantic_hash"] = vc_hash
            vc_dict.setdefault("lifecycle_status", AssetState.READY.value)
            if vid not in all_voices:
                all_voices[vid] = vc_dict
            semantic_hashes[vid] = vc_hash
            hash_to_asset[vc_hash] = vid
            voice_cards.append(vc_dict)
            logger.debug(
                "【阶段 6 音色卡建档】角色=%s (%s), 母音ID=%s, 原型=%s, 试音干声长度=%d字",
                vc_dict.get("character_name"), vc_dict.get("character_code"),
                vid, vc_dict.get("timbre_archetype"), len(vc_dict.get("master_sample_text", "")),
            )

    # 3.2 当集登场角色母音频卡 100% 全覆盖保底扫描
    # 核心保障：仅遍历经过剧本在场校验的 filtered_norm_chars，杜绝未登场角色被保底扫描暗度陈仓生成！
    covered_char_codes = {str(vc.get("character_code") or "").upper() for vc in voice_cards}
    covered_char_names = {_clean_name(str(vc.get("character_name") or "")) for vc in voice_cards}

    for c_item in filtered_norm_chars:
        if not isinstance(c_item, dict):
            continue
        c_name = str(c_item.get("name") or c_item.get("character_name") or "").strip()
        c_code = str(c_item.get("character_code") or c_item.get("character_id") or c_item.get("char_id") or "").strip().upper()
        clean_c_name = _clean_name(c_name)
        if not c_name and not c_code:
            continue

        # 检查是否已被覆盖
        if (c_code and c_code in covered_char_codes) or (clean_c_name and clean_c_name in covered_char_names):
            continue

        tok = AssetProtocolHelper.normalize_token(clean_c_name or c_code or c_name)
        auto_vid = f"VOICE_{tok}_T1_MASTER"
        if auto_vid in all_voices:
            continue

        arch = _select_voice_archetype(c_item, used_archetypes_node, index_hint=len(voice_cards) + 1)
        timbre_val = c_item.get("timbre") or c_item.get("voice_style") or arch["timbre"]
        arch_val = c_item.get("timbre_archetype") or arch["timbre_archetype"]
        sample_text_val = f"我是{c_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"

        auto_vc: dict[str, Any] = {
            "master_voice_id": auto_vid,
            "voice_id": auto_vid,
            "character_id": c_code or f"CHAR_{tok}",
            "character_code": c_code or f"CHAR_{tok}",
            "character_name": c_name or tok,
            "timbre": timbre_val,
            "timbre_archetype": arch_val,
            "vocal_position": arch["vocal_position"],
            "vocal_flaws": arch["vocal_flaws"],
            "speed_ratio": float(arch["speed_ratio"]),
            "pitch_ratio": float(arch["pitch_ratio"]),
            "tts_provider": "minimax",
            "tts_model": "speech-02-hd",
            "provider_voice_id": arch["provider_voice_id"],
            "timber_weights": arch["timber_weights"],
            "master_sample_text": sample_text_val,
            "script_monologue_source": sample_text_val,
            "master_tts_prompt": (
                f"{timbre_val}，{arch['vocal_position']}，{arch['vocal_flaws']}，"
                f"语速倍率{float(arch['speed_ratio']):.2f}，音高倍率{float(arch['pitch_ratio']):.2f}"
            ),
            "voice_file_path": f"storage/audio/voices/{auto_vid}.mp3",
            "is_master_card": True,
            "emotion_rules": _build_default_emotion_rules(),
        }
        auto_vc["voice_prompt"] = auto_vc["master_tts_prompt"]
        vc_hash = compute_asset_semantic_hash("VOICE", auto_vid, auto_vc["master_tts_prompt"], auto_vc)
        auto_vc["semantic_hash"] = vc_hash
        auto_vc["lifecycle_status"] = AssetState.READY.value

        all_voices[auto_vid] = auto_vc
        semantic_hashes[auto_vid] = vc_hash
        hash_to_asset[vc_hash] = auto_vid
        voice_cards.append(auto_vc)
        if auto_vc["character_code"]:
            covered_char_codes.add(auto_vc["character_code"])
        if clean_c_name:
            covered_char_names.add(clean_c_name)

        logger.info(
            "【阶段 6 音色卡全覆盖保底】成功为未开口/配角 [%s](%s) 补全母音卡: voice_id=%s, 音色原型=%s",
            c_name, auto_vc["character_code"], auto_vid, arch_val,
        )

    registry["characters"] = all_chars
    registry["environments"] = all_envs
    registry["props"] = all_props
    registry["audio_tts"] = all_voices
    registry["reused_assets_history"] = reused_history
    registry["semantic_hashes"] = semantic_hashes
    registry["hash_index"] = hash_to_asset

    # 规范化补齐 asset_key 并执行角色资产血统闭环纠偏
    for n_dict in deduped_newly_list:
        n_dict.setdefault("asset_key", n_dict.get("asset_id"))
        aid = n_dict.get("asset_id") or n_dict.get("asset_key")
        c_parsed = AssetProtocolHelper.parse_id(aid)
        if c_parsed and c_parsed.category == "CHAR":
            if c_parsed.function == "BASE_PORTRAIT":
                # 主肖像严格作为 t2i 根节点
                n_dict["parent_asset_id"] = None
                n_dict["parent_asset_key"] = None
                n_dict["generation_mode"] = "t2i"
            else:
                # 衍生资产强校验同实体
                p_cand = n_dict.get("parent_asset_id") or n_dict.get("parent_asset_key")
                if p_cand:
                    if p_cand == aid:
                        logger.warning(
                            "【阶段 6 资产血统闭环·自环拦截】拦截资产 [%s] 自引用父资产，置空父引用",
                            aid,
                        )
                        n_dict["parent_asset_id"] = None
                        n_dict["parent_asset_key"] = None
                    else:
                        p_parsed = AssetProtocolHelper.parse_id(p_cand)
                        if p_parsed and p_parsed.category == "CHAR" and p_parsed.token != c_parsed.token:
                            safe_parent = f"CHAR_{c_parsed.token}_{c_parsed.tier}_BASE_PORTRAIT"
                            logger.warning(
                                "【阶段 6 资产血统闭环】纠正增量资产 [%s] (token=%s) 的跨角色父资产 [%s] -> [%s]",
                                aid, c_parsed.token, p_cand, safe_parent,
                            )
                            n_dict["parent_asset_id"] = safe_parent
                            n_dict["parent_asset_key"] = safe_parent

    for r in reused_list:
        if isinstance(r, dict):
            r.setdefault("asset_key", r.get("asset_id"))

    # 提取或构建血统继承 DAG (含同角色实体闭环校验与跨角色污染拦截)
    raw_dag = result_json.get("lineage_dag") or {}
    if not isinstance(raw_dag, dict):
        raw_dag = {}
    for n_dict in deduped_newly_list:
        aid = n_dict.get("asset_id") or n_dict.get("asset_key")
        pid = n_dict.get("parent_asset_id") or n_dict.get("parent_stage_id") or n_dict.get("input_source_image")
        if aid and pid and aid != pid and aid not in raw_dag:
            raw_dag[aid] = pid

    sanitized_lineage_dag: dict[str, str] = {}
    for child_id, parent_id in raw_dag.items():
        if not child_id or not parent_id or child_id == parent_id:
            logger.warning("【阶段 6 DAG血统防线·拦截自环】检测到自引用或无效继承边: %s -> %s，予以剪枝移除", child_id, parent_id)
            continue

        child_parsed = AssetProtocolHelper.parse_id(child_id)
        parent_parsed = AssetProtocolHelper.parse_id(parent_id)

        # 1. 仅当一阶肖像基准节点 (T1) 时，才强制禁止存在父级；二阶/三阶肖像 (T2/T3) 必须保留指向 T1 基准肖像的父级边！
        # 注意：排除 BASE_COSTUME 等服装衍生节点，服装必须允许继承基准肖像
        is_pure_portrait = (
            (child_parsed.function in ("BASE_PORTRAIT", "BASE") and not child_parsed.modifier)
            or child_parsed.function_type == "BASE_PORTRAIT"
        )
        if child_parsed and child_parsed.category == "CHAR" and is_pure_portrait:
            if child_parsed.tier == "T1":
                logger.debug("【阶段 6 DAG血统防线】一阶肖像基准节点 [%s] 强制移除父级边 (原父级: %s)", child_id, parent_id)
                continue
            else:
                # T2/T3 阶段肖像：若 parent_id 为空或跨角色，强制重定向至该角色的 T1 基准肖像
                t1_benchmark = f"CHAR_{child_parsed.token}_T1_BASE_PORTRAIT"
                if not parent_id or (parent_parsed and parent_parsed.token != child_parsed.token):
                    logger.info("【阶段 6 DAG血统防线】二阶/三阶阶段肖像 [%s] 锚定至同角色 T1 基准肖像 [%s]", child_id, t1_benchmark)
                    parent_id = t1_benchmark

        # 2. 角色资产必须满足同实体血统闭环 (Child Token == Parent Token)
        if child_parsed and parent_parsed and child_parsed.category == "CHAR" and parent_parsed.category == "CHAR":
            if child_parsed.token != parent_parsed.token:
                safe_parent = f"CHAR_{child_parsed.token}_T1_BASE_PORTRAIT"
                logger.warning(
                    "【阶段 6 DAG血统防线·拦截跨角色污染】检测到非法跨角色继承边: 子资产=%s (token=%s) -> 错配父资产=%s (token=%s)! 自动重定向到同角色基准肖像 [%s]",
                    child_id, child_parsed.token, parent_id, parent_parsed.token, safe_parent,
                )
                parent_id = safe_parent

        # 3. 终极自环拦截：任何纠偏后若产生自环边，直接剔除
        if child_id == parent_id:
            logger.warning("【阶段 6 DAG血统防线·拦截自环】纠偏后产生自引用边: %s -> %s，予以剪枝移除", child_id, parent_id)
            continue

        sanitized_lineage_dag[child_id] = parent_id

    lineage_dag = sanitized_lineage_dag

    manifest_data["newly_discovered_characters"] = normalized_new_chars
    manifest_data["newly_discovered_scenes"] = normalized_new_scenes
    manifest_data["newly_discovered_props"] = normalized_new_props
    manifest_data["newly_generated_assets"] = deduped_newly_list
    manifest_data["reused_existing_assets"] = reused_list
    manifest_data["new_character_master_voice_cards"] = voice_cards
    manifest_data["lineage_dag"] = lineage_dag

    # 构建并验证本集视听资源引单
    manifest = EpisodeResourceManifest.model_validate(manifest_data)
    manifests[ep_num] = manifest

    logger.info(
        "【阶段 6 真理源】第 %s 集资产引单提纯构建完成: "
        "角色项=%s (新补录=%s), 场景项=%s (新补录=%s), 道具项=%s (新补录=%s), 音色卡=%s | 增量待生成=%s, 历史复用=%s, 累计登记指纹=%s",
        ep_num,
        len(norm_chars), len(normalized_new_chars),
        len(norm_envs), len(normalized_new_scenes),
        len(norm_props), len(normalized_new_props),
        len(voice_cards),
        len(deduped_newly_list), len(reused_list), len(semantic_hashes),
    )

    return StageResult({
        "current_stage": 6,
        "episode_id": ep_num,
        "episode_num": ep_num,
        "episode_number": ep_num,
        "episode_title": episode_title,
        "visual_audio_assets_registry": registry,
        "episode_resource_manifests": manifests,
        "episode_manifests": manifests,
        "newly_discovered_characters": normalized_new_chars,
        "newly_discovered_scenes": normalized_new_scenes,
        "newly_discovered_props": normalized_new_props,
        "reused_existing_assets": reused_list,
        "newly_generated_assets": deduped_newly_list,
        "new_character_master_voice_cards": voice_cards,
        "manifest": manifest,
        "episode_manifest": manifest,
        "episode_resource_manifest": manifest,
        "resource_manifest": manifest,
        "local_assets": norm_chars + norm_envs + norm_props,
    })

