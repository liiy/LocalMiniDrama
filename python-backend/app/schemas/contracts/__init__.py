# -*- coding: utf-8 -*-
"""跨模块系统契约与载荷模型包 (Contracts Package)。

提供全系统的跨域与服务边界协议对象：
- visual_bridge: 剧本工坊至视听工坊的交付契约与标准化分镜
- worker_payloads: 流程引擎并发 Worker 任务载荷与质检输出结果
- provider_options: 多模态底层 AI 厂商调用的标准请求选项与执行响应
"""
from __future__ import annotations

from app.schemas.contracts.visual_bridge import (
    VisualStoryboardItem,
    ScriptToVisualContract,
)
from app.schemas.contracts.worker_payloads import (
    EpisodeWorkerPayload,
    EpisodeWorkerResult,
)
from app.schemas.contracts.provider_options import (
    TaskExecutionStatus,
    ImageGenerationOptions,
    ImageGenerationResult,
    VideoGenerationOptions,
    VideoTaskResult,
    VideoPollResult,
    MusicGenerationOptions,
    MusicGenerationResult,
)

__all__ = [
    # Visual Bridge
    "VisualStoryboardItem",
    "ScriptToVisualContract",
    # Worker Payloads
    "EpisodeWorkerPayload",
    "EpisodeWorkerResult",
    # Provider Options
    "TaskExecutionStatus",
    "ImageGenerationOptions",
    "ImageGenerationResult",
    "VideoGenerationOptions",
    "VideoTaskResult",
    "VideoPollResult",
    "MusicGenerationOptions",
    "MusicGenerationResult",
]
