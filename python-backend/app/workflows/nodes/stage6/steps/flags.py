"""阶段 6 步骤状态与执行格式旗帜定义 (Stage 6 Step Flags)。

本模块定义了阶段 6（第二程资产准备与真理源校验）全生命周期中各子步骤的执行状态位掩码。
采用标准库 enum.Flag 实现，支持按位与（&）、按位或（|）等组合运算，
用于高可靠状态机流转控制、断点重试与执行审计。
"""
from __future__ import annotations

import enum


class Stage6StepFlag(enum.Flag):
    """【阶段 6 步骤执行格式旗帜】表示各核心子步骤完成状态的位掩码枚举。

    详细说明：
        阶段 6 包含从上游依赖解析到最终视听资产真理源更新的 7 个核心流水线步骤。
        每个步骤成功执行后，会在 Stage6StepContext 中点亮对应的标志位，
        方便调度器实时校验前置依赖、定位异常中断位置并输出精准的审计调试日志。
    """

    # 初始状态：未执行任何步骤
    NONE = 0

    # 步骤 1 完成：上游关键依赖提取与单集物理快照接力已归一化
    NORMALIZED = 1 << 0

    # 步骤 2 完成：确定性剧本多维特征逆向扫描识别与线索摘要编译已完成
    SCANNED = 1 << 1

    # 步骤 3 完成：视听资产上下文轻量投影与动态向量候选资产混合召回已完成
    PROJECTED = 1 << 2

    # 步骤 4 完成：零先验大模型结构化盲抽或确定性兜底提纯已完成
    DISTILLED = 1 << 3

    # 步骤 5 完成：全新未登记实体（角色/场景/道具）的全息标准化建档已完成
    DOSSIER_BUILT = 1 << 4

    # 步骤 6 完成：算子多级切片（视角/微距/风化/破坏态）派生与提示词合成已完成
    SLICES_DERIVED = 1 << 5

    # 步骤 7 完成：DAG 拓扑血统纠偏、全局真理源合并与单集资源引单编译已完成
    CONVERGED = 1 << 6

    # 数据库持久化完成（用于与适配器层 orchestrator 联通）
    PERSISTED = 1 << 7

    # 执行失败标志位
    FAILED = 1 << 8

    # 阶段 6 核心流水线全量完成组合态 (步骤 1 到 步骤 7 全部点亮)
    ALL_CORE_COMPLETED = (
        NORMALIZED
        | SCANNED
        | PROJECTED
        | DISTILLED
        | DOSSIER_BUILT
        | SLICES_DERIVED
        | CONVERGED
    )
