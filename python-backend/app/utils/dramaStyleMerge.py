# -*- coding: utf-8 -*-
"""兼容垫片：dramaStyleMerge -> app.utils.drama_style_merge。

保留此文件仅用于保障极少部分外部系统或老旧单测的向后兼容性。
业务逻辑与内部调用已全部迁移至规范的 snake_case 模块：`app.utils.drama_style_merge`。
"""
from __future__ import annotations

from app.utils.drama_style_merge import *  # noqa: F401, F403
import app.utils.drama_style_merge as _target

__all__ = getattr(_target, "__all__", [k for k in dir(_target) if not k.startswith("_")])
