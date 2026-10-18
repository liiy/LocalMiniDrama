"""阶段 6 持久化调度协调器 (Stage 6 Persistence Orchestrator)。

按序协调单集 AST 清单写入、角色三层模型落库、专属音色卡同步、场景与做旧层对齐、道具受损态演进及媒体库与向量化统管。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.platform_common import now_iso
from app.schemas.script_graph_state import (
    EpisodeScopedSubState,
    GlobalDramaMasterState,
)
from app.workflows.adapters.stage_adapters.common import (
    _dump_or_dict,
    _flatten_asset_collection,
    _safe_json_loads,
    fetch_one,
)
from app.workflows.adapters.stage_adapters.stage6.asset_persister import persist_stage6_assets
from app.workflows.adapters.stage_adapters.stage6.character_persister import persist_stage6_characters
from app.workflows.adapters.stage_adapters.stage6.prop_persister import persist_stage6_props
from app.workflows.adapters.stage_adapters.stage6.scene_persister import persist_stage6_scenes
from app.workflows.adapters.stage_adapters.stage6.voice_persister import persist_stage6_voices

log = get_logger("lmd.storage_adapter.stage6")


def persist_stage6(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 6 深度原子落库总协调函数 (Stage 6 Persistence Orchestration)。

    【落库业务链路与阶段 6 规约】：
    1. 单集 AST 结构化清单写入 episodes.ast_blocks['episode_resource_manifest']；
    2. 增量角色自动建档 characters (Tier 1)，补全新出场角色基础 11 维属性；
    3. 角色各集外观服化道与主视切片写入 character_stages (Tier 2) 与 character_stage_views (Tier 3)；
       - 强制保证每个造型形态有且仅有一个 is_primary=1 的主视觉锚点；
       - 唯有一阶主肖像为文生图根节点 (is_benchmark=1, t2i)，其余皆由 DAG 拓扑衍生；
    4. 当前集登场角色与集数映射落库 episode_characters 关联表；
    5. 角色专属音色卡片与母音同步写入 character_voice_profiles，实施全角色 100% 覆盖差集兜底；
    6. 增量发生场景及气候做旧图层写入 scenes, scene_zones, scene_weathering_views；
    7. 增量关键道具及其剧情战损演进形态写入 props, prop_damage_states；
    8. 视听多模态资产全景注册表更新至 assets 统管表并同步向量记忆库，推进剧集阶段跃迁。

    Args:
        db (Session): SQLAlchemy 数据库持久化连接会话。
        drama_id (int): 所属剧集全局唯一主键 ID。
        state (EpisodeScopedSubState | GlobalDramaMasterState | Any): 阶段 6 产出的管线状态字典或 Pydantic 模型。
        episode_num (int | None, optional): 显式指定的目标分集集数 (1-based)。若为空则从 state 自动解析。

    Returns:
        None
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
    # 2. 角色领域三层模型深度原子落库
    # -------------------------------------------------------------------------
    (
        canonical_map,
        canonical_by_code,
        canonical_by_name,
        stage_db_ids_by_code,
        asset_character_meta_map,
    ) = persist_stage6_characters(
        db=db,
        drama_id=drama_id,
        curr_ep=curr_ep,
        episode_id=episode_id,
        now=now,
        characters_manifest=characters_manifest,
        newly_discovered_characters=newly_discovered_characters,
        newly_generated_assets=newly_generated_assets,
        reused_assets_data=reused_assets_data,
        manifest_dict=manifest_dict,
        state=state,
    )

    # -------------------------------------------------------------------------
    # 3. 角色母音频卡片与专属音色配置同步
    # -------------------------------------------------------------------------
    persist_stage6_voices(
        db=db,
        drama_id=drama_id,
        curr_ep=curr_ep,
        now=now,
        voice_cards=voice_cards,
        newly_generated_assets=newly_generated_assets,
        reused_assets_data=reused_assets_data,
        canonical_map=canonical_map,
        canonical_by_code=canonical_by_code,
        canonical_by_name=canonical_by_name,
        state=state,
    )

    # -------------------------------------------------------------------------
    # 4. 空间场景与气候做旧层增量对齐
    # -------------------------------------------------------------------------
    persist_stage6_scenes(
        db=db,
        drama_id=drama_id,
        curr_ep=curr_ep,
        episode_id=episode_id,
        now=now,
        environments_manifest=environments_manifest,
        newly_discovered_scenes=newly_discovered_scenes,
        newly_generated_assets=newly_generated_assets,
        state=state,
    )

    # -------------------------------------------------------------------------
    # 5. 核心道具资产与剧情损坏形态演进
    # -------------------------------------------------------------------------
    persist_stage6_props(
        db=db,
        drama_id=drama_id,
        curr_ep=curr_ep,
        episode_id=episode_id,
        now=now,
        props_manifest=props_manifest,
        newly_discovered_props=newly_discovered_props,
        newly_generated_assets=newly_generated_assets,
        state=state,
    )

    # -------------------------------------------------------------------------
    # 5.5, 6, 7. 统管媒体素材库原子落库、向量同步与全局真理源跃迁
    # -------------------------------------------------------------------------
    persist_stage6_assets(
        db=db,
        drama_id=drama_id,
        curr_ep=curr_ep,
        episode_id=episode_id,
        now=now,
        manifest_dict=manifest_dict,
        newly_generated_assets=newly_generated_assets,
        reused_assets_data=reused_assets_data,
        characters_manifest=characters_manifest,
        lineage_dag_data=lineage_dag_data,
        raw_sem_hashes=raw_sem_hashes,
        canonical_map=canonical_map,
        stage_db_ids_by_code=stage_db_ids_by_code,
        asset_character_meta_map=asset_character_meta_map,
        newly_discovered_characters=newly_discovered_characters,
        state=state,
        voice_cards=voice_cards,
    )
