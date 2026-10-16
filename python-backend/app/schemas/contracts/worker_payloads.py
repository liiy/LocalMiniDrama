# -*- coding: utf-8 -*-
"""LangGraph 调度流水线工作节点载荷契约 (Worker Payloads & Results)。

定义并发分集生成 Worker (Send API) 的输入载荷与产出质检结果契约，支撑工业级高并发剧本并行生产与质量管控。
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.states.core import (
    EpisodeOutlineItem,
    EpisodeScript,
    QAReport,
)


class EpisodeWorkerPayload(BaseModel):
    """Send API 分发给单集生成 Worker 的入参载荷契约。

    包含单集编写所需的项目上下文、对应集数的大纲切片、前置三层记忆剧情摘要以及人物状态镜像。
    """
    model_config = ConfigDict(populate_by_name=True)

    drama_id: int = Field(
        default=0,
        description="所属短剧项目唯一标识 ID"
    )
    version_cursor: int = Field(
        default=1,
        description="流水线版本游标"
    )
    episode_num: int = Field(
        ...,
        description="目标分集序号 (1..N)"
    )
    title: str = Field(
        default="",
        description="目标分集标题"
    )
    outline: EpisodeOutlineItem = Field(
        ...,
        description="本集三级微观节拍大纲切片（包含开场抓手、反转卡点、钩子悬念）"
    )
    previous_summary: str = Field(
        default="",
        description="前置剧情连续性摘要（由三层记忆模型提供）"
    )
    character_states: dict[str, Any] = Field(
        default_factory=dict,
        description="本集出场人物当前物理/情绪状态映射表"
    )
    high_concept_summary: str = Field(
        default="",
        description="全剧核心高概念与核心卖点摘要"
    )


class EpisodeWorkerResult(BaseModel):
    """单集 Worker 生成与质检修补后的输出结果契约。

    作为单集并行分支汇聚 (Join) 节点的标准输入契约。
    """
    model_config = ConfigDict(populate_by_name=True)

    episode_num: int = Field(
        ...,
        description="分集序号"
    )
    episode: EpisodeScript = Field(
        ...,
        description="已完成文学排版与结构化解析的单集剧本文档"
    )
    qa_report: QAReport = Field(
        ...,
        description="包含红蓝对抗与规范检查的集质检审计报告"
    )
    character_updates: dict[str, Any] = Field(
        default_factory=dict,
        description="本集引发的人物关系与物理状态增量变更字典"
    )
    unresolved_clues: list[str] = Field(
        default_factory=list,
        description="本集抛出但未回收的悬念/伏笔伏线标识列表"
    )


__all__ = [
    "EpisodeWorkerPayload",
    "EpisodeWorkerResult",
]
