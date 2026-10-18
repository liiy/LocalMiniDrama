"""阶段 6 步骤 3：视听资产上下文轻量投影与动态向量候选资产混合召回 (Step 3 Projection & Recall)。

本模块实现 `ProjectionRecallStep`：
1. 视听资产前置白名单裁剪（剔除本集未出场角色，裁剪冗余依赖）；
2. 场景与物证上下文轻量投影；
3. 动态候选资产混合召回（通过向量检索与关系数据库召回历史高置信度资产，若数据库离线则自动启动内存投影注册表降级）；
4. 上下文 Token 瘦身指标与压缩率统计。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.db.session import session_scope
from app.workflows.nodes.stage6.helpers import _get_val
from app.workflows.nodes.stage6.projectors import (
    _build_candidates_from_projected_registry,
    project_characters_for_stage6,
    project_environments_props_for_stage6,
    project_registry_index_for_stage6,
)
from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag

logger = logging.getLogger("lmd.stage6.step3_project")


class ProjectionRecallStep(BaseStage6Step):
    """【步骤 3 处理器】视听资产上下文轻量投影与动态向量候选资产混合召回。

    详细说明：
        杜绝将全剧庞大的上百个角色/场景/道具全量喂入 LLM 上下文导致的注意力涣散与幻觉，
        根据步骤 2 扫描出的实体登场清单，实施精细化的前置白名单裁剪，
        并将历史可复用资产通过向量召回机制注入只读参考候选池。
    """

    def __init__(self) -> None:
        """初始化步骤 3 投影与召回处理器，绑定 PROJECTED 状态旗帜。"""
        super().__init__(
            name="Step3_ProjectionRecall",
            flag=Stage6StepFlag.PROJECTED,
        )

    def execute(self, ctx: Stage6StepContext) -> None:
        """【执行契约】运行实体白名单过滤、轻量投影与向量候选池召回。

        业务逻辑：
            1. 提取步骤 2 扫描到的出场角色、场景、物证名录及别名映射；
            2. 调用 `project_characters_for_stage6` 精准过滤在场角色；
            3. 调用 `project_environments_props_for_stage6` 投影场景与道具；
            4. 调用 `project_registry_index_for_stage6` 提取紧凑注册表索引；
            5. 执行动态候选资产混合召回（优先向量数据库，异常或离线时内存投影兜底）；
            6. 计算上下文瘦身压缩率并记录详细 Debug 指标。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。
        """
        logger.debug("【阶段 6 步骤 3】开始执行视听资产上下文轻量投影与动态候选召回...")

        scanner_result = ctx.scanner_result
        present_chars = scanner_result.characters_detected if scanner_result else []
        present_scenes = scanner_result.scenes_detected if scanner_result else []
        present_props = scanner_result.props_detected if scanner_result else []
        alias_map = scanner_result.character_alias_map if scanner_result else {}

        # ---------------------------------------------------------------------
        # 1. 前置角色白名单裁剪 (过滤未在场角色)
        # ---------------------------------------------------------------------
        chars_engine = ctx.characters_engine
        projected_chars = project_characters_for_stage6(
            chars_engine=chars_engine,
            present_names=present_chars,
            screenplay_text=ctx.screenplay_text,
            alias_map=alias_map,
        )
        ctx.projected_chars = projected_chars

        all_chars_count = len(
            chars_engine.get("characters", [])
            if isinstance(chars_engine, dict)
            else chars_engine
            if isinstance(chars_engine, list)
            else []
        )
        logger.info(
            "【阶段 6 步骤 3 角色过滤】已裁剪角色库: 全量 %d -> 当集精炼 %d 名: %s",
            all_chars_count,
            len(projected_chars),
            [c.get("name") for c in projected_chars],
        )

        # ---------------------------------------------------------------------
        # 2. 场景与道具投影及紧凑注册表索引
        # ---------------------------------------------------------------------
        envs_props = ctx.environments_and_props
        projected_envs_props = project_environments_props_for_stage6(
            envs_props=envs_props,
            present_scenes=present_scenes,
            present_props=present_props,
        )
        ctx.projected_envs = projected_envs_props.get("environments", [])
        ctx.projected_props = projected_envs_props.get("props", [])

        projected_registry = project_registry_index_for_stage6(ctx.registry)

        # ---------------------------------------------------------------------
        # 3. 统计瘦身效果与压缩指标
        # ---------------------------------------------------------------------
        raw_chars_str = json.dumps(chars_engine, ensure_ascii=False)
        raw_envs_str = json.dumps(envs_props, ensure_ascii=False)
        raw_reg_str = json.dumps(ctx.registry, ensure_ascii=False)
        raw_total_chars = len(raw_chars_str) + len(raw_envs_str) + len(raw_reg_str)

        chars_engine_json = json.dumps(projected_chars, ensure_ascii=False, indent=2)
        environments_props_json = json.dumps(projected_envs_props, ensure_ascii=False, indent=2)

        # ---------------------------------------------------------------------
        # 4. 动态候选资产池精准实体与语义向量混合召回
        # ---------------------------------------------------------------------
        candidates: list[dict[str, Any]] = []
        state = ctx.state
        drama_id = _get_val(state, "drama_id") or _get_val(state, "id")
        state_db = _get_val(state, "db") or _get_val(state, "db_session")

        if drama_id:
            try:
                from app.context.vector_memory_service import recall_candidate_assets_for_episode
                if state_db is not None:
                    candidates = recall_candidate_assets_for_episode(
                        db=state_db,
                        drama_id=int(drama_id),
                        screenplay_text=ctx.screenplay_text,
                        top_k=15,
                    )
                else:
                    with session_scope() as db_session:
                        candidates = recall_candidate_assets_for_episode(
                            db=db_session,
                            drama_id=int(drama_id),
                            screenplay_text=ctx.screenplay_text,
                            top_k=15,
                        )
                logger.info(
                    "【阶段 6 步骤 3 向量召回】成功为短剧 [%s] 第 %d 集动态召回 %d 项高置信度候选资产",
                    drama_id,
                    ctx.episode_number,
                    len(candidates),
                )
                for c in candidates:
                    logger.debug(
                        "【阶段 6 候选资产明细】key=%s, name=%s, cat=%s, score=%.2f, source=%s",
                        c.get("asset_key"),
                        c.get("name"),
                        c.get("category"),
                        c.get("relevance_score", 0.0),
                        c.get("recall_source"),
                    )
            except Exception as recall_err:
                logger.warning(
                    "【阶段 6 步骤 3 向量召回降级】向量/DB检索异常 (自动启动内存索引降级): %s",
                    recall_err,
                )

        # 若未连接数据库/单测内存环境/召回为空，从内存投影注册表自动提取保底候选池
        if not candidates and (projected_registry or ctx.registry):
            candidates = _build_candidates_from_projected_registry(
                projected_registry=projected_registry or ctx.registry,
                screenplay_text=ctx.screenplay_text,
                top_k=15,
            )
            logger.debug(
                "【阶段 6 候选召回保底】从内存已注册资产表提取 %d 项候选资产",
                len(candidates),
            )

        ctx.vector_candidates = candidates

        # ---------------------------------------------------------------------
        # 5. 上下文压缩率审计
        # ---------------------------------------------------------------------
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

        ctx.stats["raw_total_chars"] = raw_total_chars
        ctx.stats["projected_total_chars"] = projected_total_chars
        ctx.stats["compression_ratio"] = compression_ratio
        ctx.stats["candidate_count"] = len(candidates)

        logger.info(
            "【阶段 6 步骤 3 完成】依赖瘦身与候选池就绪: 原始字符数=%d -> 投影后字符数=%d (压缩率: %.1f%%, 候选资产数=%d)",
            raw_total_chars,
            projected_total_chars,
            compression_ratio,
            len(candidates),
        )
