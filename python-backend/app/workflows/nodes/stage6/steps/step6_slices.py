"""阶段 6 步骤 6：算子多级切片派生与本地提示词规则矩阵合成 (Step 6 Slice Derivation & Prompt Matrix Synthesis)。

本模块实现 `SliceDerivationStep`：
1. 规范化并对齐上游大模型/保底提取的原始资产（角、景、物）；
2. 执行后置在场硬拦截防御（剔除未真实登场的角色资产，杜绝大模型格式补全幻觉）；
3. 调度工业级神经-符号联动算子引擎（`AssetTriggerOperatorEngine`）：
   - 角色：派生四视角、情绪表象、光效反差、手部微距与战损伤残，锁定 ControlNet 控制网与纯 T1 根节点；
   - 场景：派生广角全景、中景机位，动态实体化扫描捕获的子区域机位（Zone Codes）；
   - 道具：执行一二级静动两态判定、随身物手部挂靠免除独立生图、生活环境杂物彻底拦截剔除；
4. 调度本地规则矩阵生图提示词合成引擎（`PromptMatrixSynthesizer`），装配高清提示词并执行纯面部肖像隔离。
"""
from __future__ import annotations

import logging
from typing import Any

from app.schemas.script_graph_state import AssetState
from app.workflows.nodes.stage6.helpers import (
    _clean_name,
    _ensure_standard_asset,
    compute_asset_semantic_hash,
)
from app.workflows.nodes.stage6.normalizer import AssetEntityNormalizer
from app.workflows.nodes.stage6.projectors import is_character_truly_in_screenplay
from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag
from app.workflows.operators.asset_trigger_operator_engine import AssetTriggerOperatorEngine
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.asset_slice_enricher import AssetSliceEnricher
from app.workflows.utils.prompt_synthesizer import PromptMatrixSynthesizer

logger = logging.getLogger("lmd.stage6.step6_slices")


class SliceDerivationStep(BaseStage6Step):
    """【步骤 6 处理器】算子多级切片派生与本地提示词规则矩阵合成。

    详细说明：
        实现阶段 6“提示词纯净、血统严谨、按需派生”的核心工艺。
        通过算子引擎对角色、场景与道具进行视听物理状态切片（Slices），
        严密阻断非 T1 根节点的文生图（t2i）退化，并由规则矩阵引擎合成工业级生图提示词。
    """

    def __init__(self) -> None:
        """初始化步骤 6 切片派生处理器，绑定 SLICES_DERIVED 状态旗帜。"""
        super().__init__(
            name="Step6_SliceDerivation",
            flag=Stage6StepFlag.SLICES_DERIVED,
        )

    def execute(self, ctx: Stage6StepContext) -> None:
        """【执行契约】运行算子触发判定、切片派生与提示词矩阵组装。

        业务逻辑：
            1. 从 ctx.extracted_assets_raw 解析角/景/物原始清单并补齐标准 ID 结构；
            2. 运行后置角色硬拦截防御，剔除未在场角色的虚假资产；
            3. 调用 AssetTriggerOperatorEngine 派生角色多视角与微距手部切片；
            4. 派生场景景别机位与子区域机位补全；
            5. 判定道具静动两态、手持挂靠与杂物剔除；
            6. 调度 PromptMatrixSynthesizer 组装高质量生图提示词；
            7. 将标准规范化资产暂存入上下文供步骤 7 汇聚。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。
        """
        logger.debug(
            "【阶段 6 步骤 6】开始执行算子触发判定与提示词矩阵合成 (集数: 第 %s 集)...",
            ctx.episode_number,
        )

        result_json = ctx.extracted_assets_raw or {}
        manifest_data = (
            result_json.get("episode_resource_manifest")
            or result_json.get("manifest")
            or {}
        )
        screenplay_text = ctx.screenplay_text
        scanner_result = ctx.scanner_result
        visual_style = ctx.visual_style
        char_tokens = ctx.char_tokens
        scene_tokens = ctx.scene_tokens
        prop_tokens = ctx.prop_tokens
        alias_map = scanner_result.character_alias_map if scanner_result else {}
        present_chars = scanner_result.characters_detected if scanner_result else []
        present_props = scanner_result.props_detected if scanner_result else []

        # ---------------------------------------------------------------------
        # 1. 规范化与底图血统补齐
        # ---------------------------------------------------------------------
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
            for tier_key in ["tier1_base", "tier2_performance", "tier3_special"]:
                for item in raw_chars.get(tier_key, []):
                    if isinstance(item, dict):
                        norm_chars.append(_ensure_standard_asset(item, "CHAR", char_tokens, default_char_tok))

        # ---------------------------------------------------------------------
        # 2. 【后置硬拦截防御】：过滤掉未在本集出场的角色资产 (防大模型幻觉)
        # ---------------------------------------------------------------------
        # 构建 token 到角色中文名映射，对缺失 name 的角色资产进行对齐补全
        token_to_char_name: dict[str, str] = {}
        for c in (ctx.char_list or []):
            if isinstance(c, dict):
                nm = str(c.get("name") or c.get("character_name") or "").strip()
                tok = str(c.get("character_token") or "").upper().strip()
                cid = str(c.get("character_id") or c.get("id") or "")
                if nm:
                    if tok:
                        token_to_char_name[tok] = nm
                    p = AssetProtocolHelper.parse_id(cid)
                    if p and p.token:
                        token_to_char_name[p.token] = nm
                    cln = _clean_name(nm)
                    if cln:
                        token_to_char_name[AssetProtocolHelper.normalize_token(cln)] = nm
        for pc in (ctx.projected_chars or []):
            if isinstance(pc, dict):
                nm = str(pc.get("name") or "").strip()
                cid = str(pc.get("character_id") or pc.get("character_code") or "")
                if nm:
                    p = AssetProtocolHelper.parse_id(cid)
                    if p and p.token:
                        token_to_char_name[p.token] = nm
                    cln = _clean_name(nm)
                    if cln:
                        token_to_char_name[AssetProtocolHelper.normalize_token(cln)] = nm

        present_chars_pool = set(present_chars)
        if alias_map:
            present_chars_pool.update(alias_map.keys())
            present_chars_pool.update(alias_map.values())
        for pc in ctx.projected_chars:
            if isinstance(pc, dict) and pc.get("name"):
                present_chars_pool.add(str(pc["name"]).strip())

        filtered_norm_chars: list[dict[str, Any]] = []
        for c_asset in norm_chars:
            if not c_asset.get("name") and not c_asset.get("character_name"):
                cand_tok = c_asset.get("entity_token") or ""
                if not cand_tok and c_asset.get("asset_id"):
                    parsed_aid = AssetProtocolHelper.parse_id(c_asset["asset_id"])
                    if parsed_aid:
                        cand_tok = parsed_aid.token
                if cand_tok and cand_tok in token_to_char_name:
                    c_asset["name"] = token_to_char_name[cand_tok]

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

        # ---------------------------------------------------------------------
        # 3. 调度 AssetTriggerOperatorEngine 确定性算子引擎
        # ---------------------------------------------------------------------
        logger.info("【阶段 6 算子引擎联动】开始执行资产触发算子判定与多级按需派生...")

        # A. 角色触发算子派生
        # 【核心工艺】：合并原始过滤资产与当前集已建档新角色档案，确保新发现角色也能派生出 T1_BASE / 多视角切片
        chars_for_operator: list[dict[str, Any]] = list(filtered_norm_chars)
        seen_char_ids = {
            str(c.get("asset_id") or c.get("char_id") or c.get("character_id") or "").strip()
            for c in chars_for_operator
        }
        for ndc in ctx.dossier_new_chars:
            if isinstance(ndc, dict):
                cid = str(ndc.get("character_code") or ndc.get("character_id") or ndc.get("char_id") or "").strip()
                if cid and cid not in seen_char_ids:
                    seen_char_ids.add(cid)
                    chars_for_operator.append(ndc)

        # 【防御机制：角色算子派生前实体归纳消歧】
        # 杜绝同一角色的简写/别名（如“晚晚”、“周队”）在算子引擎中二次派生出整套重复的人脸底图与切片
        consolidated_chars_for_op: list[dict[str, Any]] = []
        op_char_names: set[str] = set()
        for c_item in chars_for_operator:
            c_raw_name = str(c_item.get("name") or c_item.get("character_name") or "").strip()
            if not c_raw_name:
                continue
            norm_name = AssetEntityNormalizer.resolve_character_name(
                candidate_name=c_raw_name,
                existing_char_names=op_char_names,
                alias_map=alias_map,
                genre_pack=ctx.genre_pack,
                drama_genre=ctx.drama_genre,
            )
            if norm_name in op_char_names and norm_name != c_raw_name:
                for parent_c in consolidated_chars_for_op:
                    parent_name = str(parent_c.get("name") or parent_c.get("character_name") or "").strip()
                    if parent_name == norm_name:
                        aliases = parent_c.setdefault("aliases", [])
                        if isinstance(aliases, list) and c_raw_name not in aliases:
                            aliases.append(c_raw_name)
                        break
                logger.debug("【阶段 6 角色算子收敛】角色别名 [%s] 归入主条目 [%s]，跳过独立切片派生", c_raw_name, norm_name)
                continue
            op_char_names.add(c_raw_name)
            consolidated_chars_for_op.append(c_item)

        chars_for_operator = consolidated_chars_for_op

        operator_derived_chars: list[dict[str, Any]] = []
        seen_char_asset_ids: set[str] = set()

        for c_base in chars_for_operator:
            c_name = c_base.get("name") or c_base.get("character_name") or "CHARACTER"
            clean_cn = _clean_name(c_name)
            c_tok = AssetProtocolHelper.normalize_token(clean_cn or c_name)
            canonical_cid = f"CHAR_{c_tok}"

            c_stage = c_base.get("stage_code") or c_base.get("stage") or "T1"
            if not (isinstance(c_stage, str) and c_stage.startswith("T")):
                c_stage = "T1"

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

                derived_c = dict(c_base)
                derived_c["asset_id"] = aid
                derived_c["char_id"] = aid
                derived_c["stage_code"] = ta.get("stage_code", c_stage)
                derived_c["tier"] = ta.get("tier", "Tier1")
                derived_c["form"] = ta.get("form", f"{c_stage}_BASE" if f"{c_stage}_BASE" in aid or "BASE_PORTRAIT" in aid else "BASE")
                derived_c["trigger_reason"] = ta.get("trigger_reason", "")
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
        # 合并原始场景与当前集已建档新场景
        envs_for_operator: list[dict[str, Any]] = list(norm_envs)
        seen_env_ids = {
            str(e.get("asset_id") or e.get("scene_id") or e.get("env_id") or "").strip()
            for e in envs_for_operator
        }
        for nde in ctx.dossier_new_scenes:
            if isinstance(nde, dict):
                eid = str(nde.get("scene_code") or nde.get("scene_id") or nde.get("env_id") or "").strip()
                if eid and eid not in seen_env_ids:
                    seen_env_ids.add(eid)
                    envs_for_operator.append(nde)

        operator_derived_envs: list[dict[str, Any]] = []
        seen_env_asset_ids: set[str] = set()

        for e_base in envs_for_operator:
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

        # 场景子机位 Zone 动态补全
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

        # C. 道具触发算子判定（静动两态、手部挂靠、杂物剔除）
        # 合并原始道具与当前集已建档新道具
        props_for_operator: list[dict[str, Any]] = list(norm_props)
        seen_prop_ids = {
            str(p.get("asset_id") or p.get("prop_id") or p.get("prop_code") or "").strip()
            for p in props_for_operator
        }
        for ndp in ctx.dossier_new_props:
            if isinstance(ndp, dict):
                pid = str(ndp.get("prop_code") or ndp.get("prop_id") or "").strip()
                if pid and pid not in seen_prop_ids:
                    seen_prop_ids.add(pid)
                    props_for_operator.append(ndp)

        # 【防御机制：道具高密度全称收敛与词干别名归并 (Visual Baseline Retention)】
        # 确保：
        # 1. 优先按名称长度降序，最长、最高信息密度的全称实体（如【带血的牛皮纸信封】）作为唯一的 Visual Baseline 主条目保留；
        # 2. 短词/动作简写（如“信封”）的动作证据与形变破坏动词合并冒泡至母物证条目；
        # 3. 拦截简写条目独立进入算子引擎派生切片，杜绝派生出 PROP_XINFENG 系列残缺无视觉特征资产。
        sorted_props = sorted(
            props_for_operator,
            key=lambda p: len(str(p.get("name") or p.get("prop_name") or "")),
            reverse=True,
        )
        consolidated_props_for_op: list[dict[str, Any]] = []
        op_prop_names: set[str] = set()

        for p_item in sorted_props:
            p_raw_name = str(p_item.get("name") or p_item.get("prop_name") or "").strip()
            if not p_raw_name:
                continue
            canonical_target = AssetEntityNormalizer.resolve_prop_name(
                candidate_name=p_raw_name,
                existing_prop_names=op_prop_names,
                screenplay_text=screenplay_text,
            )
            if canonical_target in op_prop_names and canonical_target != p_raw_name:
                # 命中既有母道具，将其挂载为母道具别名，并冒泡合并动作语料与动词
                for parent_p in consolidated_props_for_op:
                    parent_name = str(parent_p.get("name") or parent_p.get("prop_name") or "").strip()
                    if parent_name == canonical_target:
                        aliases = parent_p.setdefault("aliases", [])
                        if isinstance(aliases, list) and p_raw_name not in aliases:
                            aliases.append(p_raw_name)
                        ev_to_merge = p_item.get("screenplay_evidence") or p_item.get("in_screenplay_evidence") or ""
                        if ev_to_merge:
                            orig_ev = parent_p.get("screenplay_evidence") or parent_p.get("in_screenplay_evidence") or ""
                            if ev_to_merge not in orig_ev:
                                parent_p["screenplay_evidence"] = f"{orig_ev}；{ev_to_merge}".strip("；")
                        verbs_to_merge = p_item.get("deformation_verbs") or []
                        if isinstance(verbs_to_merge, list):
                            parent_verbs = parent_p.setdefault("deformation_verbs", [])
                            for vb in verbs_to_merge:
                                if vb not in parent_verbs:
                                    parent_verbs.append(vb)
                        break
                logger.info(
                    "【阶段 6 道具切片派生收敛】简写道具 [%s] 归并至母物证 [%s]，完成语料冒泡合并，阻断残缺切片派生",
                    p_raw_name,
                    canonical_target,
                )
                continue
            op_prop_names.add(p_raw_name)
            consolidated_props_for_op.append(p_item)

        props_for_operator = consolidated_props_for_op

        operator_derived_props: list[dict[str, Any]] = []
        seen_prop_asset_ids: set[str] = set()

        for p_base in props_for_operator:
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

        # 手持交互物证标准 S0 补录
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

            # 【防御机制：S0 补录消歧拦截】
            # 若扫描出的交互物证（如“信封”）实际为已有母物证（如“带血的牛皮纸信封”）的简写或词干，严禁生成残缺独立 S0 资产
            canonical_p = AssetEntityNormalizer.resolve_prop_name(
                candidate_name=clean_p,
                existing_prop_names=existing_prop_names,
                screenplay_text=screenplay_text,
            )
            if canonical_p in existing_prop_names and canonical_p != clean_p:
                logger.debug(
                    "【阶段 6 S0 补录消歧】扫描词 [%s] 归属于母物证 [%s]，跳过生成独立裸词 S0 资产",
                    clean_p,
                    canonical_p,
                )
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

        # ---------------------------------------------------------------------
        # 4. PromptMatrixSynthesizer 提示词装配
        # ---------------------------------------------------------------------
        all_chars = dict(ctx.registry.get("characters", {}) or {})
        all_envs = dict(ctx.registry.get("environments", {}) or {})
        all_props = dict(ctx.registry.get("props", {}) or {})

        for c in norm_chars:
            cid = c.get("asset_id") or c.get("char_id") or ""
            c_name = c.get("name") or "CHARACTER"
            c_form = c.get("form") or "T1_BASE"

            c_prof = all_chars.get(cid)
            if not c_prof:
                for ac_k, ac_v in all_chars.items():
                    if isinstance(ac_v, dict) and ac_v.get("name") == c_name:
                        c_prof = ac_v
                        break

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
            motion_slice = AssetSliceEnricher.enrich_character_slice(raw_motion_slice, c_prof)

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

        for e in norm_envs:
            eid = e.get("asset_id") or e.get("scene_id") or ""
            e_name = e.get("name") or "SCENE"
            e_form = e.get("form") or "T1_WIDE"

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

        for p in norm_props:
            pid = p.get("asset_id") or p.get("prop_id") or ""
            p_name = p.get("name") or "PROP"
            p_form = p.get("form") or "S0_STATIC"

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

        # ---------------------------------------------------------------------
        # 5. 回填中间资产至 Context
        # ---------------------------------------------------------------------
        ctx.derived_slices = norm_chars + norm_envs + norm_props
        ctx.stats["norm_chars_count"] = len(norm_chars)
        ctx.stats["norm_envs_count"] = len(norm_envs)
        ctx.stats["norm_props_count"] = len(norm_props)
        ctx.stats["filtered_norm_chars_count"] = len(filtered_norm_chars)

        # 挂载临时数据至 ctx 供步骤 7 消费
        ctx.stats["_norm_chars"] = norm_chars
        ctx.stats["_norm_envs"] = norm_envs
        ctx.stats["_norm_props"] = norm_props
        ctx.stats["_filtered_norm_chars"] = filtered_norm_chars
        ctx.stats["_present_chars_pool"] = present_chars_pool

        logger.debug(
            "【阶段 6 步骤 6 完成】切片派生完成: 角色切片=%d, 场景切片=%d, 道具切片=%d, 提示词全部生成完毕",
            len(norm_chars),
            len(norm_envs),
            len(norm_props),
        )
