"""阶段 6：第二程资产准备与真理源校验业务执行节点 (Stage 6 Asset Truth Registry Node)。

本模块作为阶段 6 统一对外调度中枢与责任链编排器。
通过标准化 pipeline 调度 7 个原子子步骤：
  Step 1: ContextNormalizerStep - 上游关键依赖提取与单集物理上下文归一化
  Step 2: ScreenplayScannerStep - 剧本特征逆向扫描与代词消歧摘要编译
  Step 3: ProjectionRecallStep - 轻量化资产在场裁剪与动态向量候选混合召回
  Step 4: AssetDistillationStep - 大模型资产提纯与确定性保底工程
  Step 5: IncrementalDossierStep - 全新未登记实体全息标准化建档
  Step 6: SliceDerivationStep - 算子多级切片派生与本地提示词规则矩阵合成
  Step 7: LineageConvergenceStep - 语义去重、音色卡门禁、血统纠偏与真理源汇聚
"""
from __future__ import annotations

import logging
from typing import Any

from app.schemas.script_graph_state import (
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    IndustrialDramaState,
)
from app.workflows.nodes.stage6.steps import (
    AssetDistillationStep,
    ContextNormalizerStep,
    IncrementalDossierStep,
    LineageConvergenceStep,
    ProjectionRecallStep,
    ScreenplayScannerStep,
    SliceDerivationStep,
    Stage6StepContext,
    Stage6StepFlag,
)

logger = logging.getLogger("lmd.stage6.node")


def _get_stage6_facade():
    """安全获取 stage6_asset_truth 门面模块，彻底解开循环导入环。"""
    import sys
    return sys.modules.get("app.workflows.nodes.stage6_asset_truth")


def stage6_asset_truth_node(
    state: EpisodeScopedSubState | GlobalDramaMasterState | IndustrialDramaState | Any,
) -> dict[str, Any]:
    """【规则编号: RULE-VI-06 & RULE-STAGE6-01】执行阶段 6：提纯单集资产清单并维护全剧真理源总库。

    详细说明：
        本函数采用责任链/管道架构（Pipeline），统筹调度 7 个原子子步骤。
        各子步骤通过统一的上下文容器 `Stage6StepContext` 进行状态流转，
        并在步骤完成时原子点亮格式旗帜 `Stage6StepFlag`。
        严格保持原有的出参模型与业务行为完全兼容。

    Args:
        state: 工作流状态输入，兼容全局主状态与单集独立子状态切片。

    Returns:
        dict[str, Any]: 阶段 6 产出的单集资源引单及全局资产真理源更新结果。
    """
    logger.info("【阶段 6 真理源】启动管道化资产准备与真理源校验流程...")

    ctx = Stage6StepContext(state=state)

    pipeline = [
        ContextNormalizerStep(),
        ScreenplayScannerStep(),
        ProjectionRecallStep(),
        AssetDistillationStep(),
        IncrementalDossierStep(),
        SliceDerivationStep(),
        LineageConvergenceStep(),
    ]

    for step in pipeline:
        logger.debug(
            "【阶段 6 调度中枢】即将运行步骤: %s (前置旗帜位: 0b%s)",
            step.name,
            bin(ctx.flags.value),
        )
        step.run(ctx)

    logger.info(
        "【阶段 6 真理源】管道全流程执行完成! 最终状态旗帜: 0b%s, 总耗时明细: %s",
        bin(ctx.flags.value),
        ctx.step_timings,
    )

    return ctx.output
