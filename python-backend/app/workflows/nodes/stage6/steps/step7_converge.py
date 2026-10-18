"""阶段 6 步骤 7：语义指纹去重、音色卡兜底与真理源汇聚 (Step 7 Lineage Convergence & Manifest Generation)。

本模块实现 `LineageConvergenceStep`：
1. 聚合全局真理源 ID 库，对齐算子派生出的增量项（CHAR_*_T1_BASE 根基准图等 100% 纳入待生池）；
2. 运行跨集语义哈希指纹去重，命中历史资产的自动转入只读复用池（`reused_existing_assets`）；
3. 严格遵循资产四段式协议与 DAG 依赖图，纠偏非法 t2i 模式与跨角色血统污染，强制阻断自引用（self-parenting）；
4. 执行一阶纯面部基准图与剧情切片的情感战损隔离防御；
5. 执行音色卡当集登场白名单门禁与未开口/配角 100% 全覆盖保底扫描（Minimax Speech-02-HD）；
6. 汇聚更新全局真理源注册表（`registry`），构建强类型本集视听资源引单（`EpisodeResourceManifest`）。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.schemas.script_graph_state import (
    AssetState,
    EpisodeResourceManifest,
)
from app.workflows.nodes.stage6.helpers import (
    _clean_name,
    compute_asset_semantic_hash,
)
from app.workflows.nodes.stage6.projectors import is_character_truly_in_screenplay
from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag
from app.workflows.nodes.stage6.voice_rules import (
    _build_default_emotion_rules,
    _select_voice_archetype,
    _strip_dialogue_brackets,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

logger = logging.getLogger("lmd.stage6.step7_converge")


class LineageConvergenceStep(BaseStage6Step):
    """【步骤 7 处理器】语义去重、音色卡门禁、血统纠偏与真理源汇聚。

    详细说明：
        作为阶段 6 的终点整合器，本步骤执行终极血统闭环校验。
        杜绝资产 DAG 出现自环或跨角色错配，保障母音卡 100% 覆盖真实登场角色，
        并生成符合 Pydantic 规范的 `EpisodeResourceManifest` 引单对象。
    """

    def __init__(self) -> None:
        """初始化步骤 7 汇聚处理器，绑定 CONVERGED 状态旗帜。"""
        super().__init__(
            name="Step7_LineageConvergence",
            flag=Stage6StepFlag.CONVERGED,
        )

    def execute(self, ctx: Stage6StepContext) -> None:
        """【执行契约】执行跨集语义去重、血统纠偏、音色建档与 Manifest 汇聚。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。
        """
        logger.debug(
            "【阶段 6 步骤 7】开始执行血统闭环、语义去重与真理源汇聚 (第 %s 集)...",
            ctx.episode_number,
        )

        ep_num = ctx.episode_number
        episode_title = ctx.episode_title
        aspect_ratio = ctx.aspect_ratio
        visual_style = ctx.visual_style
        screenplay_text = ctx.screenplay_text
        scanner_result = ctx.scanner_result
        alias_map = scanner_result.character_alias_map if scanner_result else {}

        # 从 Context 提取中间结果与注册表
        registry = ctx.registry
        all_chars = registry.setdefault("characters", {})
        all_envs = registry.setdefault("environments", {})
        all_props = registry.setdefault("props", {})
        all_voices = registry.setdefault("audio_tts", {})
        reused_history = registry.setdefault("reused_assets_history", {})
        semantic_hashes = registry.setdefault("semantic_hashes", {})
        hash_to_asset = registry.setdefault("hash_index", {})

        result_json = ctx.extracted_assets_raw or ctx.raw_llm_json or {}
        manifest_data = (
            result_json.get("episode_resource_manifest")
            or result_json.get("manifest")
            or {}
        )

        # 提取步骤 6 挂载的规范化数据
        norm_chars: list[dict[str, Any]] = ctx.stats.get("_norm_chars", [])
        norm_envs: list[dict[str, Any]] = ctx.stats.get("_norm_envs", [])
        norm_props: list[dict[str, Any]] = ctx.stats.get("_norm_props", [])
        filtered_norm_chars: list[dict[str, Any]] = ctx.stats.get("_filtered_norm_chars", [])
        present_chars_pool: set[str] = ctx.stats.get("_present_chars_pool", set())

        # 挂载规范化基础清单至 manifest_data
        manifest_data["characters"] = norm_chars
        manifest_data["environments"] = norm_envs
        manifest_data["props"] = norm_props
        manifest_data.setdefault("episode_num", ep_num)
        manifest_data.setdefault("episode_title", episode_title)
        manifest_data.setdefault("aspect_ratio", aspect_ratio)

        # ---------------------------------------------------------------------
        # 1. 跨集语义去重与生命周期状态机驱动
        # ---------------------------------------------------------------------
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
        # 将算子引擎派生的核心登场资产严格注入 raw_newly_list，保障 100% 纳入增量生成
        seen_raw_newly_ids = {
            (n.get("asset_id") if isinstance(n, dict) else getattr(n, "asset_id", ""))
            for n in raw_newly_list
        }

        # 汇总全局资产库已存在 ID 及当集复用池 ID，严禁已有/复用资产重新塞入增量待生清单
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

            # 检查是否命中跨集语义哈希指纹去重
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

            # 未命中跨集重复：正式作为增量生成项
            n_dict.setdefault("lifecycle_status", AssetState.READY.value)

            # 补全 DAG 与四维提示词元数据 (防二阶/三阶资产退化为文生图 t2i)
            dep = AssetProtocolHelper.resolve_dependency(nid)
            cur_parsed = AssetProtocolHelper.parse_id(nid)

            if dep.generation_mode != "t2i":
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

                # 强校验：严禁 parent_asset_key 与自身 nid 相同 (防止自引用)
                if p_cand == nid:
                    logger.warning("【阶段 6 资产自引拦截】检测到资产 [%s] 产生 self-parenting 自引现象，重置父资产", nid)
                    if cur_parsed and cur_parsed.category == "CHAR":
                        t1_root = f"CHAR_{cur_parsed.token}_T1_BASE_PORTRAIT"
                        p_cand = t1_root if nid != t1_root else None
                    else:
                        p_cand = None

                orig_mode = n_dict.get("generation_mode")
                if orig_mode == "t2i":
                    logger.info("【阶段 6 资产模式纠偏】检测到二阶/三阶资产 [%s] 错误声明为 t2i，强制纠偏为 %s 并挂载父资产 [%s]", nid, dep.generation_mode, p_cand)
                n_dict["generation_mode"] = dep.generation_mode
                n_dict["parent_asset_key"] = p_cand
                n_dict["parent_asset_id"] = p_cand
                n_dict["is_benchmark"] = 0
                n_dict["denoise_strength"] = dep.recommended_denoise if n_dict.get("denoise_strength") is None else n_dict.get("denoise_strength")
            else:
                n_dict["generation_mode"] = "t2i"
                n_dict["parent_asset_key"] = None
                n_dict["parent_asset_id"] = None
                n_dict["is_benchmark"] = 1 if dep.is_benchmark else 0
                n_dict["denoise_strength"] = dep.recommended_denoise

            n_dict.setdefault("control_type", dep.control_type)
            cat_key = "character" if nid.startswith("CHAR_") else "scene" if nid.startswith("ENV_") else "prop" if nid.startswith("PROP_") else "audio" if nid.startswith("VOICE_") else "default"
            n_dict.setdefault("negative_prompt", PromptSynthesizer.get_category_negative_prompt(cat_key))

            # 剧情感官提示词增强与去占位符（一阶基准肖像物理隔离纯净性）
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

            semantic_hashes[nid] = nhash
            hash_to_asset[nhash] = nid

            if nid.startswith("CHAR_") and nid not in all_chars:
                all_chars[nid] = n_dict
            elif nid.startswith("ENV_") and nid not in all_envs:
                all_envs[nid] = n_dict
            elif nid.startswith("PROP_") and nid not in all_props:
                all_props[nid] = n_dict

        reused_history[ep_num] = current_ep_reused

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

        # ---------------------------------------------------------------------
        # 2. 新角色母音频卡片建档 (单集登场白名单守卫与全覆盖保底)
        # ---------------------------------------------------------------------
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
                if fc_code.startswith("CHAR_"):
                    active_present_char_codes.add(fc_code[5:])

        for pcn in present_chars_pool:
            if pcn and str(pcn).strip():
                active_present_char_names.add(_clean_name(str(pcn).strip()))
                active_present_char_names.add(str(pcn).strip())

        def _is_character_present_in_episode(cand_name: str, cand_code: str) -> bool:
            clean_cn = _clean_name(cand_name) if cand_name else ""
            c_code_clean = cand_code.upper().strip() if cand_code else ""
            if (clean_cn and clean_cn in active_present_char_names) or (cand_name and cand_name in active_present_char_names):
                return True
            if c_code_clean and (c_code_clean in active_present_char_codes or c_code_clean.replace("CHAR_", "") in active_present_char_codes):
                return True
            if cand_name and is_character_truly_in_screenplay(
                char_entry={"name": cand_name, "character_code": cand_code},
                screenplay_text=screenplay_text,
                detected_chars=present_chars_pool,
                alias_map=alias_map,
            ):
                return True
            return False

        used_archetypes_node: set[str] = set()
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
                # 门禁拦截未登场角色音色卡
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

        # 音色卡 100% 全覆盖保底扫描
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

            if (c_code and c_code in covered_char_codes) or (clean_c_name and clean_c_name in covered_char_names):
                continue

            tok = AssetProtocolHelper.normalize_token(clean_c_name or c_name)
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

        # ---------------------------------------------------------------------
        # 3. 资产血统纠偏与 DAG 构建
        # ---------------------------------------------------------------------
        for n_dict in deduped_newly_list:
            n_dict.setdefault("asset_key", n_dict.get("asset_id"))
            aid = n_dict.get("asset_id") or n_dict.get("asset_key")
            c_parsed = AssetProtocolHelper.parse_id(aid)
            if c_parsed and c_parsed.category == "CHAR":
                if c_parsed.function == "BASE_PORTRAIT":
                    n_dict["parent_asset_id"] = None
                    n_dict["parent_asset_key"] = None
                    n_dict["generation_mode"] = "t2i"
                else:
                    p_cand = n_dict.get("parent_asset_id") or n_dict.get("parent_asset_key")
                    if p_cand:
                        if p_cand == aid:
                            logger.warning("【阶段 6 资产血统闭环·自环拦截】拦截资产 [%s] 自引用父资产，置空父引用", aid)
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

        # 提取构建血统继承 DAG
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

            is_pure_portrait = (
                (child_parsed.function in ("BASE_PORTRAIT", "BASE") and not child_parsed.modifier)
                or child_parsed.function_type == "BASE_PORTRAIT"
            )
            if child_parsed and child_parsed.category == "CHAR" and is_pure_portrait:
                if child_parsed.tier == "T1":
                    logger.debug("【阶段 6 DAG血统防线】一阶肖像基准节点 [%s] 强制移除父级边 (原父级: %s)", child_id, parent_id)
                    continue
                else:
                    t1_benchmark = f"CHAR_{child_parsed.token}_T1_BASE_PORTRAIT"
                    if not parent_id or (parent_parsed and parent_parsed.token != child_parsed.token):
                        logger.info("【阶段 6 DAG血统防线】二阶/三阶阶段肖像 [%s] 锚定至同角色 T1 基准肖像 [%s]", child_id, t1_benchmark)
                        parent_id = t1_benchmark

            if child_parsed and parent_parsed and child_parsed.category == "CHAR" and parent_parsed.category == "CHAR":
                if child_parsed.token != parent_parsed.token:
                    safe_parent = f"CHAR_{child_parsed.token}_T1_BASE_PORTRAIT"
                    logger.warning(
                        "【阶段 6 DAG血统防线·拦截跨角色污染】检测到非法跨角色继承边: 子资产=%s (token=%s) -> 错配父资产=%s (token=%s)! 自动重定向到同角色基准肖像 [%s]",
                        child_id, child_parsed.token, parent_id, parent_parsed.token, safe_parent,
                    )
                    parent_id = safe_parent

            if child_id == parent_id:
                logger.warning("【阶段 6 DAG血统防线·拦截自环】纠偏后产生自引用边: %s -> %s，予以剪枝移除", child_id, parent_id)
                continue

            sanitized_lineage_dag[child_id] = parent_id

        # ---------------------------------------------------------------------
        # 4. 组装 EpisodeResourceManifest 并保存
        # ---------------------------------------------------------------------
        manifest_data["newly_discovered_characters"] = ctx.dossier_new_chars
        manifest_data["newly_discovered_scenes"] = ctx.dossier_new_scenes
        manifest_data["newly_discovered_props"] = ctx.dossier_new_props
        manifest_data["newly_generated_assets"] = deduped_newly_list
        manifest_data["reused_existing_assets"] = reused_list
        manifest_data["new_character_master_voice_cards"] = voice_cards
        manifest_data["lineage_dag"] = sanitized_lineage_dag

        manifest = EpisodeResourceManifest.model_validate(manifest_data)
        ctx.manifest = manifest
        ctx.manifests[ep_num] = manifest
        ctx.manifests[str(ep_num)] = manifest

        # 封装装配好的最终 StageResult 结果容器（兼具字典与属性访问能力）
        from app.workflows.nodes.stage6.helpers import StageResult
        ctx.output = StageResult({
            "current_stage": 6,
            "episode_id": ep_num,
            "episode_num": ep_num,
            "episode_number": ep_num,
            "episode_title": episode_title,
            "visual_audio_assets_registry": registry,
            "episode_resource_manifests": ctx.manifests,
            "episode_manifests": ctx.manifests,
            "newly_discovered_characters": ctx.dossier_new_chars,
            "newly_discovered_scenes": ctx.dossier_new_scenes,
            "newly_discovered_props": ctx.dossier_new_props,
            "reused_existing_assets": reused_list,
            "newly_generated_assets": deduped_newly_list,
            "new_character_master_voice_cards": voice_cards,
            "manifest": manifest,
            "episode_manifest": manifest,
            "episode_resource_manifest": manifest,
            "resource_manifest": manifest,
            "local_assets": norm_chars + norm_envs + norm_props,
        })

        logger.info(
            "【阶段 6 步骤 7 完成】第 %s 集资产引单汇聚成功: "
            "角色项=%d (新补录=%d), 场景项=%d (新补录=%d), 道具项=%d (新补录=%d), 音色卡=%d | 待生成=%d, 历史复用=%d, 登记指纹=%d",
            ep_num,
            len(norm_chars), len(ctx.dossier_new_chars),
            len(norm_envs), len(ctx.dossier_new_scenes),
            len(norm_props), len(ctx.dossier_new_props),
            len(voice_cards),
            len(deduped_newly_list), len(reused_list), len(semantic_hashes),
        )
