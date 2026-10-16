# -*- coding: utf-8 -*-
"""状态机基础枚举与元类型契约。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.base")


class AssetState(str, Enum):
    """【阶段 6】资产生命周期状态枚举 (Asset Lifecycle State)。

    遵循工业化短剧生产管线全生命周期：
    - DRAFT: 剧本初提草稿态，由剧本扫描器或LLM初步提取，待进一步补全
    - READY: 经特征归一化、四段式纠偏与Prompt工程补全后的就绪态，具备渲染能力
    - QUEUED: 提交排队渲染中
    - RENDERED: 已完成生图或生音渲染并获得落地文件
    - APPROVED: 经核准锁定的全剧真理源资产 (跨集100%只读复用)
    - REJECTED: 质检未通过或废弃
    """
    DRAFT = "DRAFT"
    READY = "READY"
    MODIFIED = "MODIFIED"
    QUEUED = "QUEUED"
    RENDERED = "RENDERED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AssetGenerationMode(str, Enum):
    """资产生成管线模式枚举。"""
    T2I = "t2i"
    I2I = "i2i"
    CONTROLNET = "controlnet"
    INPAINT = "inpaint"
    DEPTH_BLUR = "depth_blur"
    TTS_MASTER = "tts_master"
    RELIGHTING = "relighting"
    CROP_MACRO = "crop_macro"
    CROP_INSERT = "crop_insert"
    CONTROLNET_WEATHER = "controlnet_weather"


__all__ = [
    "AssetState",
    "AssetGenerationMode",
]
