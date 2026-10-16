# -*- coding: utf-8 -*-
"""剧本工坊至视听工坊的跨模块标准化交付契约 (Visual Bridge Contracts)。

遵循《详细设计说明书（V2.0 工业增强版）》第 2.6 节设计规范：
实现剧本创作工坊 (Script Studio) 与视听生产工坊 (Visual Studio) 的解耦与工业化交付。
1. 剧本锁定保护：当单集剧本经质检定稿锁定 (`lock_status = 1`) 后，通过 Bridge 契约流转生成只读标准快照；
2. 契约提取与转换：从剧本 AST、角色档案、大纲中提取规范化的分镜镜头列表、场景映射、道具流向与提示词；
3. 算力流幂等指纹：计算每个分镜的 `task_fingerprint` (基于 prompt + 角色锚点 + 场景 + 参数)，避免下游重复算力消耗。
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.platform_common import now_iso


class VisualStoryboardItem(BaseModel):
    """Bridge 交付契约中的单分镜标准化结构。

    详细描述交付给下游视听生产工坊渲染的单个分镜镜头定义。
    """
    model_config = ConfigDict(populate_by_name=True)

    storyboard_number: int = Field(
        ...,
        description="分镜序号 (从 1 开始严格递增，对应剧本镜头顺序)"
    )
    title: str = Field(
        default="",
        description="分镜动作/台词简述或画面小标题"
    )
    shot_type: str = Field(
        default="特写",
        description="景别分类：大特写 / 特写 / 近景 / 中景 / 全景 / 大远景"
    )
    camera_movement: str = Field(
        default="推镜头",
        description="运镜方式：固定镜头 / 慢推镜头 / 拉远镜头 / 摇移镜头 / 跟拍镜头"
    )
    aspect_ratio: str = Field(
        default="9:16",
        description="画面画幅比例，竖屏短剧工业标准默认 9:16"
    )
    characters: list[str] = Field(
        default_factory=list,
        description="本分镜画面中出场的角色姓名列表"
    )
    dialogue: str = Field(
        default="",
        description="分镜对应的台词文本（包括对白、旁白、内心独白 OS）"
    )
    visual_prompt: str = Field(
        ...,
        description="文生图核心正向提示词 (融合角色外观锚点、场景环境、光影色调与机位)"
    )
    task_fingerprint: str = Field(
        default="",
        description="算力渲染幂等防重指纹 (由 prompt + 角色 + 场景等要素计算出的 SHA-256 哈希)"
    )


class ScriptToVisualContract(BaseModel):
    """剧本工坊交付至视听工坊的标准化交付契约快照。

    作为剧本定稿锁定的不可变快照凭证，封装单集生产全流程所需的静态资产与分镜序列。
    """
    model_config = ConfigDict(populate_by_name=True)

    drama_id: int = Field(
        ...,
        description="所属短剧项目唯一标识 ID"
    )
    version_cursor: int = Field(
        default=1,
        description="剧本定稿版本游标 (每次定稿重新交付递增)"
    )
    episode_num: int = Field(
        ...,
        description="交付分集序号 (1..N)"
    )
    episode_title: str = Field(
        default="",
        description="交付分集标题"
    )
    characters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="本集出场人物资产标准档案列表 (包含面部基因特征与定妆阶段)"
    )
    scenes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="本集涉及场景空间资产标准档案列表 (包含全景基准与光影基调)"
    )
    storyboards: list[VisualStoryboardItem] = Field(
        default_factory=list,
        description="按顺序排列的本集标准化分镜镜头契约列表"
    )
    created_at: str = Field(
        default_factory=now_iso,
        description="契约快照生成时间 (ISO-8601 标准时间字符串)"
    )


__all__ = [
    "VisualStoryboardItem",
    "ScriptToVisualContract",
]
