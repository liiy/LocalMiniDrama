"""阶段 6 步骤 2：确定性剧本多维特征逆向扫描识别与线索摘要编译 (Step 2 Screenplay Scanner)。

本模块实现 `ScreenplayScannerStep`，调度无模型特征扫描引擎：
1. 逆向扫描单集剧本文本中的角色、场景、物证出现频率与显式上下文；
2. 执行代词消解（将“他/她/其”与最近主语角色关联绑定）；
3. 识别道具形变破坏动词（如“摔碎/撕裂/被雨淋湿”等）与身体伤残/微距特写；
4. 编译高密度视听线索摘要，供后续轻量投影与模型结构化提纯使用。
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from app.tools.screenplay_feature_scanner import (
    ScreenplayScanResult,
    scan_screenplay_features,
)
from app.workflows.nodes.stage6.projectors import summarize_scanner_findings
from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag

logger = logging.getLogger("lmd.stage6.step2_scan")


def _get_stage6_facade():
    """安全获取 stage6_asset_truth 门面模块，支持测试桩 Mock 与防循环导入。"""
    return sys.modules.get("app.workflows.nodes.stage6_asset_truth")


class ScreenplayScannerStep(BaseStage6Step):
    """【步骤 2 处理器】确定性剧本多维特征逆向扫描识别与线索摘要编译。

    详细说明：
        在进入高昂开销的大语言模型之前，通过确定性规则引擎与正则表达式，
        对剧本进行零温度扫描，挖掘角色视听动作、面部/手部微距、破损道具状态，
        锁定实体登场白名单，并生成高密度线索摘要注入提示词。
    """

    def __init__(self) -> None:
        """初始化步骤 2 扫描处理器，绑定 SCANNED 状态旗帜。"""
        super().__init__(
            name="Step2_ScreenplayScanner",
            flag=Stage6StepFlag.SCANNED,
        )

    def execute(self, ctx: Stage6StepContext) -> None:
        """【执行契约】运行逆向扫描引擎并生成高密度线索摘要。

        业务逻辑：
            1. 校验 ctx.screenplay_text；若为空文本则优雅降级为保底空结果；
            2. 动态检索外部门面 `scan_screenplay_features`（兼容单测动态 monkeypatch）；
            3. 调用逆向扫描器，传入已知实体及上一集 0 秒物理快照；
            4. 将扫描产物存储至 `ctx.scanner_result`；
            5. 调用 `summarize_scanner_findings` 生成线索摘要至 `ctx.summary_findings`；
            6. 输出结构化扫描统计的 Debug 调试日志。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。
        """
        logger.debug(
            "【阶段 6 步骤 2】开始运行确定性特征扫描算子 (集数: 第 %s 集, 剧本长度: %d 字符)...",
            ctx.episode_number,
            len(ctx.screenplay_text),
        )

        # ---------------------------------------------------------------------
        # 1. 兼容单测与门面 Mock: 优先从 sys.modules 获取被 patch 的扫描函数
        # ---------------------------------------------------------------------
        facade = _get_stage6_facade()
        _scan_fn = getattr(facade, "scan_screenplay_features", scan_screenplay_features) if facade else scan_screenplay_features

        # ---------------------------------------------------------------------
        # 2. 执行确定性扫描算子
        # ---------------------------------------------------------------------
        scanner_result = _scan_fn(
            screenplay_text=ctx.screenplay_text,
            previous_pickup=ctx.previous_pickup if isinstance(ctx.previous_pickup, dict) else None,
            existing_assets_registry=ctx.registry,
            known_characters=ctx.char_list,
            known_environments=ctx.scene_list,
            known_props=ctx.prop_list,
            genre_pack=ctx.genre_pack,
            drama_genre=ctx.drama_genre,
        )

        ctx.scanner_result = scanner_result

        # ---------------------------------------------------------------------
        # 3. 编译视听动线与高密度线索摘要
        # ---------------------------------------------------------------------
        scanner_summary = summarize_scanner_findings(scanner_result)
        ctx.summary_findings = scanner_summary

        # ---------------------------------------------------------------------
        # 4. 统计指标与 Debug 调试日志输出
        # ---------------------------------------------------------------------
        chars_detected = getattr(scanner_result, "characters_detected", []) if scanner_result else []
        scenes_detected = getattr(scanner_result, "scenes_detected", []) if scanner_result else []
        props_detected = getattr(scanner_result, "props_detected", []) if scanner_result else []
        deformations = getattr(scanner_result, "prop_deformations", []) if scanner_result else []

        logger.debug(
            "【阶段 6 步骤 2 统计】第 %s 集剧本扫描完毕: 识别出场角色=%d 个 %s, 物理场景=%d 个, 道具物证=%d 个, 破坏动词=%d 个",
            ctx.episode_number,
            len(chars_detected),
            chars_detected,
            len(scenes_detected),
            len(props_detected),
            len(deformations),
        )
        logger.info(
            "【阶段 6 步骤 2 完成】第 %s 集特征预扫描与代词消解摘要:\n%s",
            ctx.episode_number,
            scanner_summary,
        )
