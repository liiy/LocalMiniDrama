"""阶段 6 步骤 4：零先验大模型结构化盲抽与 Fallback 资产提纯 (Step 4 Asset Distillation)。

本模块实现 `AssetDistillationStep`：
1. 组装标准化用户提示词（含分集大纲背景、人物关系网络、投影实体档案只读词典与上一集物理快照）；
2. 调度大语言模型执行零先验纯剧本盲抽；
3. 配置确定性资产合成兜底工厂（Fallback Factory），确保弱网或模型返回破损时 100% 优雅降级；
4. 解析大模型返回的结构化 JSON 引单。
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.workflows.nodes.stage6.fallback import _stage6_fallback
from app.workflows.prompts.master_sop_prompts import (
    STAGE6_SYSTEM_PROMPT,
    STAGE6_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json
from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag

logger = logging.getLogger("lmd.stage6.step4_distill")


def _get_stage6_facade():
    """安全获取 stage6_asset_truth 门面模块，支持测试桩 Mock 与防循环导入。"""
    return sys.modules.get("app.workflows.nodes.stage6_asset_truth")


class AssetDistillationStep(BaseStage6Step):
    """【步骤 4 处理器】零先验大模型结构化盲抽与 Fallback 资产提纯。

    详细说明：
        杜绝注意力泄露与完型填空强迫症，将前置依赖作为只读语义参考词典，
        以文学剧本为唯一事实源，调用大模型提取本集所需的具象视听资产，
        并在网络震荡或模型幻觉破损时，由确定性保底工程合成标准资产清单。
    """

    def __init__(self) -> None:
        """初始化步骤 4 提纯处理器，绑定 DISTILLED 状态旗帜。"""
        super().__init__(
            name="Step4_AssetDistillation",
            flag=Stage6StepFlag.DISTILLED,
        )

    def execute(self, ctx: Stage6StepContext) -> None:
        """【执行契约】组装提示词并调用大模型提取单集结构化资产清单。

        业务逻辑：
            1. 从全局状态提取分集大纲概况 (outline_synopsis) 与人物关系矩阵；
            2. 构建全局实体档案字典 (仅注入当前在场实体以杜绝注意力幻觉)；
            3. 根据模板组装标准化 STAGE6_USER_PROMPT；
            4. 优先通过门面模块调用 `call_llm_json`（注入确定性保底 fallback_factory）；
            5. 将大模型提取出的原始 JSON 字典保存到 `ctx.extracted_assets_raw`；
            6. 输出提纯完成的 Debug 审计日志。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。
        """
        logger.debug(
            "【阶段 6 步骤 4】开始组装提示词并执行大模型零先验资产提纯 (集数: 第 %s 集)...",
            ctx.episode_number,
        )

        state = ctx.state
        ep_num = ctx.episode_number

        # ---------------------------------------------------------------------
        # 1. 提取分集大纲背景 (outline_synopsis)
        # ---------------------------------------------------------------------
        outline_synopsis = ""
        season_outlines = (
            getattr(state, "season_outlines", {})
            or (state.get("season_outlines", {}) if isinstance(state, dict) else {})
            or {}
        )
        if isinstance(season_outlines, dict):
            ep_outline_obj = season_outlines.get(ep_num) or season_outlines.get(str(ep_num)) or {}
            if isinstance(ep_outline_obj, dict):
                outline_synopsis = str(
                    ep_outline_obj.get("synopsis")
                    or ep_outline_obj.get("outline")
                    or ep_outline_obj.get("killer_title")
                    or ""
                )
        if not outline_synopsis:
            outline_synopsis = f"第 {ep_num} 集分集大纲：围绕当前核心戏剧冲突展开推进。"

        # ---------------------------------------------------------------------
        # 2. 提取人物关系图谱
        # ---------------------------------------------------------------------
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

        # ---------------------------------------------------------------------
        # 3. 提取全局已知实体定型库 (防幻读防护: 仅注入当集确切在场的实体)
        # ---------------------------------------------------------------------
        projected_chars = ctx.projected_chars
        projected_char_names = {
            str(c.get("name")).strip()
            for c in projected_chars
            if isinstance(c, dict) and c.get("name")
        }
        global_entities_dict = {
            "characters": [
                {
                    "name": c.get("name"),
                    "appearance": c.get("appearance"),
                    "biological_dna": c.get("biological_dna"),
                    "lived_in_costume": c.get("lived_in_costume"),
                }
                for c in ctx.char_list
                if isinstance(c, dict) and str(c.get("name")).strip() in projected_char_names
            ],
            "environments": [
                {
                    "name": e.get("name"),
                    "architectural_style": e.get("architectural_style") or e.get("appearance"),
                }
                for e in ctx.scene_list
                if isinstance(e, dict)
            ],
            "props": [
                {
                    "name": p.get("name"),
                    "material": p.get("material"),
                }
                for p in ctx.prop_list
                if isinstance(p, dict)
            ],
        }
        global_entities_json = json.dumps(global_entities_dict, ensure_ascii=False, indent=2)

        # ---------------------------------------------------------------------
        # 4. 组装标准化用户提示词
        # ---------------------------------------------------------------------
        user_prompt = STAGE6_USER_PROMPT_TEMPLATE.format(
            episode_num=ep_num,
            episode_title=ctx.episode_title,
            aspect_ratio=ctx.aspect_ratio,
            visual_style=ctx.visual_style,
            target_video_engine=ctx.target_video_engine,
            episode_outline_synopsis=outline_synopsis,
            character_relationship_matrix=rel_matrix_text,
            global_entities_dossiers_json=global_entities_json,
            inter_episode_physical_snapshot_json=(
                json.dumps(ctx.previous_pickup or {}, ensure_ascii=False, indent=2)
                if ctx.previous_pickup
                else "无（本集为首集或无上一集物理接棒残留）"
            ),
            screenplay_text=ctx.screenplay_text if ctx.screenplay_text else "（无独立文学剧本文本）",
        )

        logger.debug(
            "【阶段 6 步骤 4 提示词】向大模型发送纯剧本高保真盲抽指令 (提示词长度: %d 字符)...",
            len(user_prompt),
        )

        # ---------------------------------------------------------------------
        # 5. 调度大模型与 Fallback 确定性保底工厂
        # ---------------------------------------------------------------------
        facade = _get_stage6_facade()
        _call_llm_fn = getattr(facade, "call_llm_json", call_llm_json) if facade else call_llm_json

        result_json = _call_llm_fn(
            user_prompt=user_prompt,
            system_prompt=STAGE6_SYSTEM_PROMPT,
            fallback_factory=lambda: _stage6_fallback(
                episode_num=ep_num,
                script_data=ctx.script,
                characters_engine=ctx.characters_engine,
                envs_props=ctx.environments_and_props,
                existing_registry=ctx.registry,
                scanner_result=ctx.scanner_result,
                visual_style=ctx.visual_style,
                aspect_ratio=ctx.aspect_ratio,
                episode_title=ctx.episode_title,
                candidates=ctx.vector_candidates,
            ),
        )

        if not isinstance(result_json, dict):
            logger.warning("【阶段 6 步骤 4 警告】大模型返回非字典结构，启动空字典保底")
            result_json = {}

        ctx.extracted_assets_raw = result_json

        manifest_data = (
            result_json.get("episode_resource_manifest")
            or result_json.get("manifest")
            or {}
        )
        ctx.stats["distill_keys_count"] = len(result_json)
        ctx.stats["has_manifest_in_distill"] = bool(manifest_data)

        logger.debug(
            "【阶段 6 步骤 4 完成】第 %s 集资产盲抽提纯完成 (包含键: %s)",
            ep_num,
            list(result_json.keys()),
        )
