"""阶段 6 抽象子步骤基类定义 (Stage 6 Base Step)。

本模块定义了阶段 6 统一的子步骤抽象基类 `BaseStage6Step`。
采用模板方法模式（Template Method Pattern），标准化每个子步骤的执行流程、
前后置条件防御性校验、精确耗时度量与状态格式旗帜点亮机制。
"""
from __future__ import annotations

import abc
import logging
import time
from typing import Any

from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag

logger = logging.getLogger("lmd.stage6.steps.base")


class BaseStage6Step(abc.ABC):
    """【阶段 6 子步骤抽象基类】定义阶段 6 内部标准子步骤的接口与执行模板。

    详细说明：
        子类仅需实现具体的业务核心 `execute(ctx)` 方法。
        基类的 `run(ctx)` 模板方法负责统筹：
        1. 步骤进入前置检查与上下文状态诊断日志；
        2. 毫秒级性能计时；
        3. 步骤异常边界捕获与审计留痕；
        4. 自动激活上下文中的对应 `Stage6StepFlag` 状态旗帜；
        5. 步骤退出时产出统计指标的 Debug 摘要日志。

    Attributes:
        name (str): 子步骤的唯一名称标识（如 "Step1_ContextNormalizer"）。
        flag (Stage6StepFlag): 本步骤对应的格式旗帜位掩码。
    """

    def __init__(self, name: str, flag: Stage6StepFlag) -> None:
        """初始化阶段 6 子步骤基类。

        Args:
            name (str): 子步骤的可读名称标识。
            flag (Stage6StepFlag): 步骤完成后需点亮的状态标志。
        """
        self.name = name
        self.flag = flag

    @abc.abstractmethod
    def execute(self, ctx: Stage6StepContext) -> None:
        """【抽象方法】执行具体步骤的业务核心逻辑。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。

        Raises:
            Exception: 当发生阻断性业务错误或核心依赖缺失时抛出。
        """
        raise NotImplementedError("子类必须实现 execute 方法以完成特定步骤业务")

    def run(self, ctx: Stage6StepContext) -> None:
        """【模板方法】包装执行标准子步骤全流程（含计时、日志与标志位更新）。

        详细说明：
            统一管理步骤生命周期，执行前校验上下文合法性，执行中捕获非致命异常，
            执行后记录精确耗时，并原子更新 ctx 中的 Stage6StepFlag。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。

        Raises:
            Exception: 透传核心不可恢复的业务异常，确保工作流能够准确捕获。
        """
        start_time = time.perf_counter()
        logger.debug(
            "==================== 【阶段 6 子步骤开始】[%s] (集数: 第 %s 集) ====================",
            self.name,
            ctx.episode_number,
        )

        try:
            # 1. 核心业务分派执行
            self.execute(ctx)

            # 2. 正常完成：标记标志位
            ctx.mark_flag(self.flag)

        except Exception as exc:
            # 3. 异常边界防护：记录错误信息与失败旗帜
            logger.error(
                "【阶段 6 子步骤异常】[%s] 执行失败: %s",
                self.name,
                exc,
                exc_info=True,
            )
            ctx.errors.append(f"[{self.name}] {type(exc).__name__}: {str(exc)}")
            ctx.mark_flag(Stage6StepFlag.FAILED)
            raise

        finally:
            # 4. 耗时度量与退出审计
            duration = time.perf_counter() - start_time
            ctx.record_timing(self.name, duration)
            logger.debug(
                "-------------------- 【阶段 6 子步骤结束】[%s] 耗时: %.4fs, 当前状态标志: 0b%s --------------------",
                self.name,
                duration,
                bin(ctx.flags.value),
            )
