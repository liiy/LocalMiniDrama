"""阶段 6 步骤 5：全新未登记实体全息标准化建档 (Step 5 Incremental Dossier)。

本模块实现 `IncrementalDossierStep`：
1. 提取并规范化当前集新发现的阶段 2 未登记新角色（执行 11 维标准建档与代词消歧）；
2. 调度在场真实性脱敏核验（`is_character_truly_in_screenplay`），杜绝案卷提及或追忆死者被误建档；
3. 提取并规范化当前集新发现的阶段 3 未登记新场景（三级层级建档与子区域 Zones 挂载）；
4. 提取并规范化当前集新发现的阶段 3 未登记新道具（三级重要性定级与破坏特征绑定）；
5. 自动扩充与同步上下文中的角色、场景、道具实体列表与 Token 白名单集合。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.tools.screenplay_feature_scanner import is_valid_character_speaker
from app.workflows.nodes.stage6.cinematic_reasoner import CinematicSetDressingReasoner
from app.workflows.nodes.stage6.dossier_builders import (
    _build_stage2_character_dossier,
    _build_stage3_prop_dossier,
    _build_stage3_scene_dossier,
)
from app.workflows.nodes.stage6.normalizer import AssetEntityNormalizer
from app.workflows.nodes.stage6.projectors import is_character_truly_in_screenplay
from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

logger = logging.getLogger("lmd.stage6.step5_dossier")


class IncrementalDossierStep(BaseStage6Step):
    """【步骤 5 处理器】全新未登记实体全息标准化建档。

    详细说明：
        短剧创作过程中常出现未在早期企划（Stage 2/3）登记但本集剧情强依赖的新角色、
        新环境与关键证物。本步骤通过“大模型上报优先 + 逆向扫描算子确定性兜底”双重防漏机制，
        自动补齐 11 维角色全息设定与场景/道具三级架构，并执行实体脱敏阻断。
    """

    def __init__(self) -> None:
        """初始化步骤 5 建档处理器，绑定 DOSSIER_BUILT 状态旗帜。"""
        super().__init__(
            name="Step5_IncrementalDossier",
            flag=Stage6StepFlag.DOSSIER_BUILT,
        )

    def execute(self, ctx: Stage6StepContext) -> None:
        """【执行契约】运行实体建档流水线并同步上下文白名单。

        业务逻辑：
            1. 解析大模型提取结果中的新角色、新场景、新道具清单；
            2. 对比已知已注册实体，执行防重复过滤与演讲者合法性校验；
            3. 执行 11 维角色建档与声音原型防撞分配；
            4. 运行扫描算子兜底补录并经过 `is_character_truly_in_screenplay` 脱敏；
            5. 对新场景、新道具执行三级架构建档；
            6. 更新并同步 `ctx.char_list`, `ctx.scene_list`, `ctx.prop_list` 及相关 Tokens。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。
        """
        logger.debug(
            "【阶段 6 步骤 5】开始执行分集全新实体全息建档 (集数: 第 %s 集)...",
            ctx.episode_number,
        )

        result_json = ctx.extracted_assets_raw or ctx.raw_llm_json or {}
        manifest_data = (
            result_json.get("episode_resource_manifest")
            or result_json.get("manifest")
            or {}
        )
        ep_num = ctx.episode_number
        screenplay_text = ctx.screenplay_text
        scanner_result = ctx.scanner_result

        char_list = ctx.char_list
        scene_list = ctx.scene_list
        prop_list = ctx.prop_list

        char_tokens = ctx.char_tokens
        scene_tokens = ctx.scene_tokens
        prop_tokens = ctx.prop_tokens

        present_chars = scanner_result.characters_detected if scanner_result else []
        present_scenes = scanner_result.scenes_detected if scanner_result else []
        present_props = scanner_result.props_detected if scanner_result else []

        # =====================================================================
        # 1. 提取并规范化本集发现的阶段 2 未登记新角色 (Stage-2 11 维标准建档)
        # 核心改造：大模型提示词契约已统一为 manifest.characters，废除对已剔除的 newly_discovered_* 的依赖
        # 采用内存集合差集运算：识别 characters 中不在 registered_names_node 的新登场实体
        # =====================================================================
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

        # 候选新角色池：优先聚合大模型 characters 中未在阶段 2 注册的新增实体
        model_characters = manifest_data.get("characters") or result_json.get("characters") or []
        raw_new_chars: list[dict[str, Any]] = []
        seen_new_char_names: set[str] = set()

        if isinstance(model_characters, list):
            for mc in model_characters:
                if not isinstance(mc, dict):
                    continue
                mc_name = str(mc.get("character_name") or mc.get("name") or "").strip()
                if mc_name and mc_name not in registered_names_node and mc_name not in seen_new_char_names:
                    raw_new_chars.append(mc)
                    seen_new_char_names.add(mc_name)

        # 兼容老旧单元测试/历史 Mock 显式注入的 newly_discovered_characters 字段
        legacy_new_chars = result_json.get("newly_discovered_characters") or manifest_data.get("newly_discovered_characters") or []
        if isinstance(legacy_new_chars, list):
            for lnc in legacy_new_chars:
                if not isinstance(lnc, dict):
                    continue
                lnc_name = str(lnc.get("name") or lnc.get("character_name") or "").strip()
                if lnc_name and lnc_name not in registered_names_node and lnc_name not in seen_new_char_names:
                    raw_new_chars.append(lnc)
                    seen_new_char_names.add(lnc_name)

        primary_prot_code = "CHAR_PROTAGONIST"
        primary_prot_name = "主角"
        for idx_c, c_item in enumerate(char_list):
            if isinstance(c_item, dict) and (
                idx_c == 0
                or c_item.get("role_type") == "protagonist"
                or c_item.get("role") == "main"
            ):
                if c_item.get("name"):
                    primary_prot_name = str(c_item["name"])
                if c_item.get("character_id") or c_item.get("character_code"):
                    raw_cc = str(c_item.get("character_code") or c_item.get("character_id"))
                    primary_prot_code = raw_cc if raw_cc.startswith("CHAR_") else f"CHAR_{raw_cc}"
                break

        alias_map = scanner_result.character_alias_map if scanner_result else {}

        normalized_new_chars: list[dict[str, Any]] = []
        for nc_idx, nc_item in enumerate(raw_new_chars, start=1):
            if not isinstance(nc_item, dict):
                continue
            nc_name = str(nc_item.get("name") or nc_item.get("character_name") or "").strip()
            if not nc_name or nc_name in registered_names_node:
                continue
            if not is_valid_character_speaker(nc_name, known_names=registered_names_node):
                logger.debug("【阶段 6 新角色过滤】跳过大模型误报的非具名角色/舞台指令: %s", nc_name)
                continue

            # 【防御机制：角色全称与别名/职衔/爱称归一化探测】
            # 杜绝大模型将“周队/老周/晚晚”作为全新角色立项，防范多套音色卡与档案漂移穿帮
            normalized_cname = AssetEntityNormalizer.resolve_character_name(
                candidate_name=nc_name,
                existing_char_names=registered_names_node,
                alias_map=alias_map,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
            )
            if normalized_cname in registered_names_node and normalized_cname != nc_name:
                # 成功归纳至母角色（且避开了同姓歧义熔断），将简写别名挂载至母角色档案并跳过建档
                for ec in char_list:
                    if isinstance(ec, dict) and str(ec.get("name") or ec.get("character_name") or "").strip() == normalized_cname:
                        ec_aliases = ec.setdefault("aliases", [])
                        if isinstance(ec_aliases, list) and nc_name not in ec_aliases:
                            ec_aliases.append(nc_name)
                        break
                registered_names_node.add(nc_name)
                logger.info(
                    "【阶段 6 角色消歧归一】候选新角色 [%s] 成功归纳为既有角色 [%s] 的简写/别名，挂入别名列表，跳过重复建档",
                    nc_name,
                    normalized_cname,
                )
                continue

            # 提取大模型阶段 6 提示词契约输出的性别与预估年龄（0 额外网络开销，第 1 级）
            llm_gender = str(nc_item.get("gender") or "").strip().lower()
            llm_age = nc_item.get("perceived_age")
            parsed_age = int(llm_age) if isinstance(llm_age, (int, float)) and 1 <= int(llm_age) <= 120 else None

            base_dossier = _build_stage2_character_dossier(
                char_name=nc_name,
                episode_num=ep_num,
                screenplay_text=screenplay_text,
                existing_char_codes=existing_char_codes_node,
                used_archetypes=used_archetypes_node,
                primary_protagonist_code=primary_prot_code,
                primary_protagonist_name=primary_prot_name,
                index_hint=len(char_list) + nc_idx,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
                visual_style=ctx.visual_style,
                gender=llm_gender if llm_gender in ("male", "female") else None,
                perceived_age=parsed_age,
            )
            merged_dossier = {**base_dossier, **{k: v for k, v in nc_item.items() if v not in (None, "", [], {})}}
            if not isinstance(merged_dossier.get("visual_consistency_code"), dict):
                merged_dossier["visual_consistency_code"] = base_dossier["visual_consistency_code"]
            if isinstance(merged_dossier.get("identity_anchors"), str):
                raw_ia = merged_dossier["identity_anchors"].strip()
                merged_dossier["identity_anchors"] = [
                    x.strip() for x in re.split(r"[|｜,，;；]", raw_ia) if x.strip()
                ] or base_dossier["identity_anchors"]

            raw_cc = str(
                merged_dossier.get("character_code")
                or merged_dossier.get("character_id")
                or base_dossier["character_code"]
            ).strip().upper()
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
                "【阶段 6 新角色建档】已标准化第 %d 集新角色 [%s] (%s), 11维字段完备",
                ep_num,
                nc_name,
                raw_cc,
            )

        # 扫描算子捕获未登记具名角色的确定性自动兜底
        for det_idx, det_name in enumerate(present_chars, start=1):
            clean_det = str(det_name or "").strip()
            if not clean_det or clean_det in registered_names_node:
                continue
            if not is_valid_character_speaker(clean_det, known_names=registered_names_node):
                logger.debug("【阶段 6 新角色自动兜底过滤】跳过非具名角色/舞台指令: %s", clean_det)
                continue

            # 【防御机制：扫描算子兜底实体归一化探测】
            normalized_cname = AssetEntityNormalizer.resolve_character_name(
                candidate_name=clean_det,
                existing_char_names=registered_names_node,
                alias_map=alias_map,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
            )
            if normalized_cname in registered_names_node and normalized_cname != clean_det:
                for ec in char_list:
                    if isinstance(ec, dict) and str(ec.get("name") or ec.get("character_name") or "").strip() == normalized_cname:
                        ec_aliases = ec.setdefault("aliases", [])
                        if isinstance(ec_aliases, list) and clean_det not in ec_aliases:
                            ec_aliases.append(clean_det)
                        break
                registered_names_node.add(clean_det)
                logger.info(
                    "【阶段 6 角色扫描兜底消歧】扫描角色 [%s] 归纳为既有角色 [%s] 的别名，跳过重复建档",
                    clean_det,
                    normalized_cname,
                )
                continue

            # 严格使用在场判定脱敏核验（防止案卷媒介或提及词被兜底建档为新实体）
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
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
                visual_style=ctx.visual_style,
            )
            tok_nc = auto_dossier["character_code"].replace("CHAR_", "", 1)
            char_tokens.add(tok_nc)
            registered_names_node.add(clean_det)
            normalized_new_chars.append(auto_dossier)
            char_list.append(auto_dossier)
            logger.info(
                "【阶段 6 新角色自动兜底补录】扫描算子捕获第 %d 集未登记角色 [%s] -> 自动按阶段2标准建档 [%s]",
                ep_num,
                clean_det,
                auto_dossier["character_code"],
            )

        ctx.dossier_new_chars = normalized_new_chars

        # =====================================================================
        # 2. 提取并规范化本集发现的阶段 3 未登记新场景 (Stage-3 3-Tier 标准建档)
        # 核心改造：基于 manifest.environments 集合差集自动识别当集新场景，消除对死代码 key 的依赖
        # =====================================================================
        registered_scene_names_node: set[str] = {
            AssetProtocolHelper.sanitize_scene_location(str(s.get("name") or s.get("location_name") or s.get("scene_name") or "").strip())
            for s in scene_list
            if isinstance(s, dict) and (s.get("name") or s.get("location_name") or s.get("scene_name"))
        }
        # 同时保留原名称映射，避免遗漏
        for s in scene_list:
            if isinstance(s, dict):
                orig_sn = str(s.get("name") or s.get("location_name") or s.get("scene_name") or "").strip()
                if orig_sn:
                    registered_scene_names_node.add(orig_sn)

        existing_scene_codes_node: set[str] = {
            str(s.get("scene_code") or s.get("env_id") or s.get("scene_id") or "").strip().upper()
            for s in scene_list
            if isinstance(s, dict) and (s.get("scene_code") or s.get("env_id") or s.get("scene_id"))
        }
        for tok in scene_tokens:
            if tok:
                existing_scene_codes_node.add(f"ENV_{tok}")

        model_scenes = (
            manifest_data.get("environments")
            or result_json.get("environments")
            or manifest_data.get("scenes")
            or result_json.get("scenes")
            or []
        )
        raw_new_scenes: list[dict[str, Any]] = []
        seen_new_scene_names: set[str] = set()

        if isinstance(model_scenes, list):
            for ms in model_scenes:
                if not isinstance(ms, dict):
                    continue
                raw_ms_name = str(ms.get("scene_name") or ms.get("location_name") or ms.get("name") or "").strip()
                ms_name = AssetProtocolHelper.sanitize_scene_location(raw_ms_name)
                if ms_name and ms_name not in registered_scene_names_node and ms_name not in seen_new_scene_names:
                    raw_new_scenes.append(ms)
                    seen_new_scene_names.add(ms_name)

        legacy_new_scenes = (
            result_json.get("newly_discovered_scenes")
            or manifest_data.get("newly_discovered_scenes")
            or []
        )
        if isinstance(legacy_new_scenes, list):
            for lns in legacy_new_scenes:
                if not isinstance(lns, dict):
                    continue
                raw_lns_name = str(lns.get("name") or lns.get("scene_name") or lns.get("location_name") or "").strip()
                lns_name = AssetProtocolHelper.sanitize_scene_location(raw_lns_name)
                if lns_name and lns_name not in registered_scene_names_node and lns_name not in seen_new_scene_names:
                    raw_new_scenes.append(lns)
                    seen_new_scene_names.add(lns_name)

        normalized_new_scenes: list[dict[str, Any]] = []
        for ns_idx, ns_item in enumerate(raw_new_scenes, start=1):
            if not isinstance(ns_item, dict):
                continue
            raw_ns_name = str(ns_item.get("name") or ns_item.get("location_name") or ns_item.get("scene_name") or "").strip()
            ns_name = AssetProtocolHelper.sanitize_scene_location(raw_ns_name)
            if not ns_name or ns_name in registered_scene_names_node:
                continue
            detected_zones_for_scene = scanner_result.scene_zones_detected.get(ns_name, []) if scanner_result else []
            base_scene_dossier = _build_stage3_scene_dossier(
                scene_name=ns_name,
                episode_num=ep_num,
                screenplay_text=screenplay_text,
                existing_scene_codes=existing_scene_codes_node,
                visual_style=ctx.visual_style,
                index_hint=len(scene_list) + ns_idx,
                detected_zones=detected_zones_for_scene,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
            )
            merged_scene_dossier = {**base_scene_dossier, **{k: v for k, v in ns_item.items() if v not in (None, "", [], {})}}
            merged_scene_dossier["name"] = ns_name
            merged_scene_dossier["location_name"] = ns_name
            merged_scene_dossier["scene_name"] = ns_name

            # 若上游大模型产出的 visual_prompt 过于简陋（缺少纵深置景陈设），强制采用四大支柱与 3D 纵深置景重新组装
            ns_vp = str(ns_item.get("visual_prompt") or "").strip()
            if not ns_vp or "in the midground:" not in ns_vp:
                merged_scene_dossier["visual_prompt"] = PromptSynthesizer.assemble_environment_prompt(
                    name=ns_name,
                    form="WIDE",
                    env_slice=merged_scene_dossier,
                    env_profile=merged_scene_dossier,
                    visual_style=ctx.visual_style,
                )
            raw_sc = str(
                merged_scene_dossier.get("scene_code")
                or merged_scene_dossier.get("env_id")
                or base_scene_dossier["scene_code"]
            ).strip().upper()
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
                ep_num,
                ns_name,
                raw_sc,
            )

        # 扫描算子捕获未登记场景的确定性兜底补录
        for s_idx, det_sname in enumerate(present_scenes, start=1):
            clean_sname = AssetProtocolHelper.sanitize_scene_location(str(det_sname or "").strip())
            if not clean_sname or clean_sname in registered_scene_names_node:
                continue
            detected_zones_for_scene = scanner_result.scene_zones_detected.get(clean_sname, []) if scanner_result else []
            auto_scene_dossier = _build_stage3_scene_dossier(
                scene_name=clean_sname,
                episode_num=ep_num,
                screenplay_text=screenplay_text,
                existing_scene_codes=existing_scene_codes_node,
                visual_style=ctx.visual_style,
                index_hint=len(scene_list) + s_idx,
                detected_zones=detected_zones_for_scene,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
            )
            tok_ns = auto_scene_dossier["scene_code"].replace("ENV_", "", 1)
            scene_tokens.add(tok_ns)
            existing_scene_codes_node.add(auto_scene_dossier["scene_code"])
            registered_scene_names_node.add(clean_sname)
            normalized_new_scenes.append(auto_scene_dossier)
            scene_list.append(auto_scene_dossier)
            logger.info(
                "【阶段 6 新场景自动兜底补录】扫描算子捕获第 %d 集未登记场景 [%s] -> 自动按阶段3标准建档 [%s]",
                ep_num,
                clean_sname,
                auto_scene_dossier["scene_code"],
            )

        ctx.dossier_new_scenes = normalized_new_scenes

        # =====================================================================
        # 3. 提取并规范化本集发现的新道具 (Stage-3 3-Tier 标准建档)
        # 核心改造：基于 manifest.props 集合差集自动识别当集新道具，消除对死代码 key 的依赖
        # =====================================================================
        registered_prop_names_node: set[str] = {
            str(p.get("name") or p.get("prop_name") or p.get("raw_name") or "").strip()
            for p in prop_list
            if isinstance(p, dict) and (p.get("name") or p.get("prop_name") or p.get("raw_name"))
        }
        existing_prop_codes_node: set[str] = {
            str(p.get("prop_code") or p.get("prop_id") or "").strip().upper()
            for p in prop_list
            if isinstance(p, dict) and (p.get("prop_code") or p.get("prop_id"))
        }
        for tok in prop_tokens:
            if tok:
                existing_prop_codes_node.add(f"PROP_{tok}")

        model_props = manifest_data.get("props") or result_json.get("props") or []
        raw_new_props: list[dict[str, Any]] = []
        seen_new_prop_names: set[str] = set()

        if isinstance(model_props, list):
            for mp in model_props:
                if not isinstance(mp, dict):
                    continue
                mp_name = str(mp.get("prop_name") or mp.get("raw_name") or mp.get("name") or "").strip()
                if mp_name and mp_name not in registered_prop_names_node and mp_name not in seen_new_prop_names:
                    raw_new_props.append(mp)
                    seen_new_prop_names.add(mp_name)

        legacy_new_props = (
            result_json.get("newly_discovered_props")
            or manifest_data.get("newly_discovered_props")
            or []
        )
        if isinstance(legacy_new_props, list):
            for lnp in legacy_new_props:
                if not isinstance(lnp, dict):
                    continue
                lnp_name = str(lnp.get("name") or lnp.get("prop_name") or lnp.get("raw_name") or "").strip()
                if lnp_name and lnp_name not in registered_prop_names_node and lnp_name not in seen_new_prop_names:
                    raw_new_props.append(lnp)
                    seen_new_prop_names.add(lnp_name)

        # 【特殊画中人/遗像双态解耦引擎】
        # 扫描剧本与场景中的黑白遗像/肖像，将其从场景固定陈设中解耦派生为独立物证道具卡
        for s_item in scene_list:
            if not isinstance(s_item, dict):
                continue
            s_name = str(s_item.get("name") or s_item.get("scene_name") or "").strip()
            decoupled_portraits = CinematicSetDressingReasoner.detect_and_decouple_portrait_elements(
                screenplay_text=screenplay_text,
                scene_name=s_name,
                known_characters=char_list,
                episode_num=ep_num,
            )
            for dp in decoupled_portraits:
                dp_name = str(dp.get("name") or "").strip()
                if dp_name and dp_name not in registered_prop_names_node and dp_name not in seen_new_prop_names:
                    raw_new_props.append(dp)
                    seen_new_prop_names.add(dp_name)

        # 优先按道具名称长度降序排列：确保信息密度最高的全称实体（如【带血的牛皮纸信封】）优先建立母物证档案，
        # 后续遍历到的简写词（如【信封】）即可精准命中母物证词干漏斗并执行语料冒泡
        raw_new_props.sort(
            key=lambda p: len(str(p.get("name") or p.get("prop_name") or p.get("raw_name") or "")),
            reverse=True,
        )

        normalized_new_props: list[dict[str, Any]] = []
        for np_idx, np_item in enumerate(raw_new_props, start=1):
            if not isinstance(np_item, dict):
                continue
            np_name = str(np_item.get("name") or np_item.get("prop_name") or "").strip()
            if not np_name or np_name in registered_prop_names_node:
                continue

            # 【防御机制：道具词干指代消歧与动作语料冒泡合并 (Action Corpus Bubbling)】
            # 解决剧本中【带血的牛皮纸信封】与后文动作简写“信封”被拆分为两个独立物证道具的问题
            canonical_target = AssetEntityNormalizer.resolve_prop_name(
                candidate_name=np_name,
                existing_prop_names=registered_prop_names_node,
                screenplay_text=screenplay_text,
            )
            if canonical_target in registered_prop_names_node and canonical_target != np_name:
                # 命中既有母道具，将其挂载为母道具别名，并将其动作证据与形变破坏动词冒泡回传合并
                for ep in prop_list:
                    ep_name = str(ep.get("name") or ep.get("prop_name") or ep.get("raw_name") or "").strip()
                    if ep_name == canonical_target:
                        ep_aliases = ep.setdefault("aliases", [])
                        if isinstance(ep_aliases, list) and np_name not in ep_aliases:
                            ep_aliases.append(np_name)
                        # 动作证据冒泡合并
                        ev_to_merge = np_item.get("screenplay_evidence") or np_item.get("in_screenplay_evidence") or ""
                        if ev_to_merge:
                            orig_ev = ep.get("screenplay_evidence") or ep.get("in_screenplay_evidence") or ""
                            if ev_to_merge not in orig_ev:
                                ep["screenplay_evidence"] = f"{orig_ev}；{ev_to_merge}".strip("；")
                        # 动作破坏动词冒泡合并
                        verbs_to_merge = np_item.get("deformation_verbs") or []
                        if isinstance(verbs_to_merge, list):
                            ep_verbs = ep.setdefault("deformation_verbs", [])
                            for vb in verbs_to_merge:
                                if vb not in ep_verbs:
                                    ep_verbs.append(vb)
                        break
                registered_prop_names_node.add(np_name)
                logger.info(
                    "【阶段 6 道具消歧归一】候选道具 [%s] 识别为母物证 [%s] 的词干简写，完成语料冒泡合并并跳过重复建档",
                    np_name,
                    canonical_target,
                )
                continue

            base_prop_dossier = _build_stage3_prop_dossier(
                prop_name=np_name,
                episode_num=ep_num,
                screenplay_text=screenplay_text,
                existing_prop_codes=existing_prop_codes_node,
                visual_style=ctx.visual_style,
                index_hint=len(prop_list) + np_idx,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
            )
            merged_prop_dossier = {**base_prop_dossier, **{k: v for k, v in np_item.items() if v not in (None, "", [], {})}}
            raw_pc = str(
                merged_prop_dossier.get("prop_code")
                or merged_prop_dossier.get("prop_id")
                or base_prop_dossier["prop_code"]
            ).strip().upper()
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
                ep_num,
                np_name,
                raw_pc,
            )

        # 扫描算子捕获未登记道具的确定性兜底补录
        for p_idx, det_pname in enumerate(present_props, start=1):
            clean_pname = str(det_pname or "").strip()
            if not clean_pname or clean_pname in registered_prop_names_node:
                continue

            # 【防御机制：扫描算子兜底道具归一化探测】
            canonical_target = AssetEntityNormalizer.resolve_prop_name(
                candidate_name=clean_pname,
                existing_prop_names=registered_prop_names_node,
                screenplay_text=screenplay_text,
            )
            if canonical_target in registered_prop_names_node and canonical_target != clean_pname:
                for ep in prop_list:
                    ep_name = str(ep.get("name") or ep.get("prop_name") or ep.get("raw_name") or "").strip()
                    if ep_name == canonical_target:
                        ep_aliases = ep.setdefault("aliases", [])
                        if isinstance(ep_aliases, list) and clean_pname not in ep_aliases:
                            ep_aliases.append(clean_pname)
                        break
                registered_prop_names_node.add(clean_pname)
                logger.info(
                    "【阶段 6 道具扫描兜底消歧】扫描道具 [%s] 归并至母物证 [%s]，跳过重复建档",
                    clean_pname,
                    canonical_target,
                )
                continue

            auto_prop_dossier = _build_stage3_prop_dossier(
                prop_name=clean_pname,
                episode_num=ep_num,
                screenplay_text=screenplay_text,
                existing_prop_codes=existing_prop_codes_node,
                visual_style=ctx.visual_style,
                index_hint=len(prop_list) + p_idx,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
            )
            tok_np = auto_prop_dossier["prop_code"].replace("PROP_", "", 1)
            prop_tokens.add(tok_np)
            existing_prop_codes_node.add(auto_prop_dossier["prop_code"])
            registered_prop_names_node.add(clean_pname)
            normalized_new_props.append(auto_prop_dossier)
            prop_list.append(auto_prop_dossier)
            logger.info(
                "【阶段 6 新道具自动兜底补录】扫描算子捕获第 %d 集未登记道具 [%s] -> 自动按阶段3标准建档 [%s]",
                ep_num,
                clean_pname,
                auto_prop_dossier["prop_code"],
            )

        ctx.dossier_new_props = normalized_new_props

        logger.debug(
            "【阶段 6 步骤 5 完成】分集实体建档完毕: 新增角色=%d 个, 新增场景=%d 个, 新增道具=%d 个; 全局累计: 角色=%d, 场景=%d, 道具=%d",
            len(ctx.dossier_new_chars),
            len(ctx.dossier_new_scenes),
            len(ctx.dossier_new_props),
            len(ctx.char_list),
            len(ctx.scene_list),
            len(ctx.prop_list),
        )
