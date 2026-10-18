"""阶段 6 统管媒体素材库、向量同步与全局真理源状态更新组件 (Stage 6 Asset & Memory Persister)。

严格维持资产 DAG 血统关系、跨集资产去重复用、Qdrant 向量空间同步以及全剧阶段跃迁。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.type_utils import safe_int
from app.context import vector_memory_service
from app.core.logger import get_logger
from app.workflows.adapters.stage_adapters.common import (
    _dump_or_dict,
    _safe_json_loads,
    fetch_all,
    fetch_one,
    persist_audit_report,
    sync_stage_memories_to_vector_db,
)
from app.workflows.adapters.stage_adapters.stage6.helpers import (
    clean_character_name,
    extract_character_tokens,
    parse_character_view_type,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

log = get_logger("lmd.storage_adapter.stage6.asset")


def persist_stage6_assets(
    db: Session,
    drama_id: int,
    curr_ep: int,
    episode_id: int | None,
    now: str,
    manifest_dict: dict[str, Any],
    newly_generated_assets: list[dict[str, Any]],
    reused_assets_data: list[dict[str, Any]],
    characters_manifest: list[dict[str, Any]],
    lineage_dag_data: dict[str, Any],
    raw_sem_hashes: dict[str, Any],
    canonical_map: dict[str, Any],
    stage_db_ids_by_code: dict[str, Any],
    asset_character_meta_map: dict[str, Any],
    newly_discovered_characters: list[dict[str, Any]],
    state: Any,
    voice_cards: list[dict[str, Any]] | None = None,
) -> None:
    """持久化统管 assets 记录、向量记忆同步并提交短剧事务。

    【核心职责与事务安全】：
    1. 汇总多模态资产：收拢新生成视听素材、角色各阶段切片视图、母音卡音频资产，统一执行协议校验；
    2. DAG 拓扑防退化：严禁非一阶资产退化为纯文生图 (t2i)，孤儿资产基于协议规则自动挂载至标准根基准；
    3. 全局反向挂载：为 assets 记录注入精准的 character_id、character_stage_id、view_type 及 is_master_portrait；
    4. 向量空间同步：将新增与变更资产异步同步至专属向量集合 (lmd_assets_drama_{id})，支持语义检索；
    5. 全局真理源推进：合并 asset_lineage_dag 与全局角色档案，原子推进 dramas.current_stage 至 6 并提交事务。

    Args:
        db (Session): 数据库会话对象。
        drama_id (int): 所属剧集全局 ID。
        curr_ep (int): 当前分集集数 (1-based)。
        episode_id (int | None): 当前分集在 episodes 表中的主键 ID。
        now (str): ISO 8601 标准当前时间戳。
        manifest_dict (dict[str, Any]): 阶段 6 资源引单全景字典。
        newly_generated_assets (list[dict[str, Any]]): 阶段 6 调度生成的全部新增资产字典列表。
        reused_assets_data (list[dict[str, Any]]): 跨集复用的资产字典列表。
        characters_manifest (list[dict[str, Any]]): 角色清单。
        lineage_dag_data (dict[str, Any]): 阶段 6 资产依赖拓扑有向无环图。
        raw_sem_hashes (dict[str, Any]): 资产语义指纹字典。
        canonical_map (dict[str, Any]): 规范化角色实体映射字典。
        stage_db_ids_by_code (dict[str, Any]): 造型代号到数据库主键的映射字典。
        asset_character_meta_map (dict[str, Any]): 资产键到角色层次元数据的反向映射。
        newly_discovered_characters (list[dict[str, Any]]): 阶段 6 增量建档的未登记角色列表。
        state (Any): 当前 LangGraph / 节点执行上下文状态对象。
        voice_cards (list[dict[str, Any]] | None, optional): 角色母音卡列表。默认为 None。

    Returns:
        None
    """
    if voice_cards is None:
        voice_cards = []
    log.info("【阶段 6 落库】[步骤 5.5/6 统管素材] 开始将多模态资产与母音卡写入 assets 统管表...")
    all_raw_assets_to_persist: list[dict[str, Any]] = []

    # 1. 收集新生成的多模态视听资产
    seen_persist_keys: set[str] = set()
    for na in newly_generated_assets:
        nad = _dump_or_dict(na)
        if isinstance(nad, dict):
            raw_ak = str(nad.get("asset_key") or nad.get("asset_id") or "").strip()
            ak = AssetProtocolHelper.normalize_id(raw_ak) if raw_ak.startswith("CHAR_") else raw_ak
            if ak:
                if ak in seen_persist_keys:
                    continue
                seen_persist_keys.add(ak)
                # 更新字典内的 asset_key 与 asset_id
                nad["asset_key"] = ak
                nad["asset_id"] = ak
            all_raw_assets_to_persist.append(nad)

    # 1.1 补充 characters_manifest 中可能未显式在 newly_generated_assets 登记的角色资产 (统一归一化为四段式)
    for cm in characters_manifest:
        cmd = _dump_or_dict(cm)
        if isinstance(cmd, dict):
            # 兼容多种字段可能存放的资产键名
            ak_candidates = [
                str(cmd.get("char_id") or "").strip(),
                str(cmd.get("asset_key") or "").strip(),
                str(cmd.get("asset_id") or "").strip(),
                str(cmd.get("benchmark_asset_key") or "").strip(),
            ]
            for ak in ak_candidates:
                if ak and ak.startswith("CHAR_"):
                    # 强行将 CHAR_*_T1_BASE 归一化为 CHAR_*_T1_BASE_PORTRAIT
                    norm_ak = AssetProtocolHelper.normalize_id(ak)
                    if norm_ak and norm_ak not in seen_persist_keys:
                        seen_persist_keys.add(norm_ak)
                        c_name = str(cmd.get("character_name") or cmd.get("name") or cmd.get("char_name") or norm_ak).strip()
                        is_bench_port = norm_ak.endswith("_T1_BASE_PORTRAIT")
                        all_raw_assets_to_persist.append({
                            "asset_id": norm_ak,
                            "asset_key": norm_ak,
                            "name": f"{c_name}_初始面容基准" if is_bench_port else c_name,
                            "category": "character",
                            "type": "image",
                            "prompt": str(cmd.get("visual_prompt") or cmd.get("prompt") or cmd.get("appearance") or "").strip(),
                            "negative_prompt": str(cmd.get("negative_prompt") or "").strip(),
                            "parent_asset_key": None if is_bench_port else (cmd.get("parent_asset_key") or cmd.get("parent_asset_id")),
                            "parent_asset_id": None if is_bench_port else (cmd.get("parent_asset_key") or cmd.get("parent_asset_id")),
                            "generation_mode": "t2i" if is_bench_port else cmd.get("generation_mode", "i2i"),
                            "denoise_strength": 0.0 if is_bench_port else cmd.get("denoise_strength", 0.40),
                            "control_type": cmd.get("control_type"),
                            "is_benchmark": 1 if is_bench_port or cmd.get("is_benchmark") == 1 else 0,
                            "lifecycle_status": "READY",
                        })

    # 1.2 从 canonical_map 聚合阶段视图中提取尚未持久化的 asset_keys
    for ent in canonical_map.values():
        c_code = ent.get("char_code") or ent.get("character_code") or ""
        c_nm = ent.get("char_name") or ent.get("name") or c_code
        for st_code, st_info in ent.get("stages", {}).items():
            for v_type, v_info in st_info.get("views", {}).items():
                for ak in v_info.get("asset_keys", []):
                    raw_ak = str(ak).strip()
                    ak_str = AssetProtocolHelper.normalize_id(raw_ak) if raw_ak.startswith("CHAR_") else raw_ak
                    if ak_str and ak_str not in seen_persist_keys:
                        seen_persist_keys.add(ak_str)
                        all_raw_assets_to_persist.append({
                            "asset_id": ak_str,
                            "asset_key": ak_str,
                            "name": f"{c_nm}_{st_code}_{v_type}",
                            "category": "character",
                            "type": "image",
                            "prompt": v_info.get("image_prompt") or "",
                            "negative_prompt": v_info.get("negative_prompt") or "",
                            "parent_asset_key": v_info.get("parent_asset_key"),
                            "parent_asset_id": v_info.get("parent_asset_key"),
                            "generation_mode": v_info.get("generation_mode", "t2i" if ("BASE" in ak_str and "COSTUME" not in ak_str) else "i2i"),
                            "denoise_strength": v_info.get("denoise_strength", 0.0 if ("BASE" in ak_str and "COSTUME" not in ak_str) else 0.40),
                            "control_type": v_info.get("control_type"),
                            "is_benchmark": 1 if (v_info.get("is_benchmark") == 1 or ("BASE" in ak_str and "COSTUME" not in ak_str and v_type == "main_portrait")) else 0,
                            "lifecycle_status": "READY",
                        })

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


