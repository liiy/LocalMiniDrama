# -*- coding: utf-8 -*-
"""兼容垫片：generationStylePresets -> app.constants.generation_style_presets。

保留此文件仅用于保障极少部分外部系统或老旧单测的向后兼容性。
业务逻辑与内部调用已全部迁移至规范的 snake_case 模块：`app.constants.generation_style_presets`。
"""
from __future__ import annotations

from app.constants.generation_style_presets import *  # noqa: F401, F403
import app.constants.generation_style_presets as _target

__all__ = getattr(_target, "__all__", [k for k in dir(_target) if not k.startswith("_")])
