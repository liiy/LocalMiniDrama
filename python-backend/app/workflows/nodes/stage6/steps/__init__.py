"""阶段 6 模块化执行步骤组件包 (Stage 6 Execution Steps Package)。

将阶段 6（资产真理源注册与引单提纯）庞大的单一函数解耦为 7 个标准子步骤处理器，
提供统一的状态格式旗帜、生命周期上下文及抽象基类接口。
"""
from __future__ import annotations

from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag
from app.workflows.nodes.stage6.steps.step1_normalize import ContextNormalizerStep
from app.workflows.nodes.stage6.steps.step2_scan import ScreenplayScannerStep
from app.workflows.nodes.stage6.steps.step3_project import ProjectionRecallStep
from app.workflows.nodes.stage6.steps.step4_distill import AssetDistillationStep
from app.workflows.nodes.stage6.steps.step5_dossier import IncrementalDossierStep
from app.workflows.nodes.stage6.steps.step6_slices import SliceDerivationStep
from app.workflows.nodes.stage6.steps.step7_converge import LineageConvergenceStep

__all__ = [
    "BaseStage6Step",
    "Stage6StepContext",
    "Stage6StepFlag",
    "ContextNormalizerStep",
    "ScreenplayScannerStep",
    "ProjectionRecallStep",
    "AssetDistillationStep",
    "IncrementalDossierStep",
    "SliceDerivationStep",
    "LineageConvergenceStep",
]
