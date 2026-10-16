# -*- coding: utf-8 -*-
"""兼容垫片：libraryCommon -> app.services.library_common。

保留此文件仅用于保障极少部分外部系统或老旧单测的向后兼容性。
业务逻辑与内部调用已全部迁移至规范的 snake_case 模块：`app.services.library_common`。
"""
from __future__ import annotations

from app.services.library_common import *  # noqa: F401, F403
import app.services.library_common as _target

__all__ = getattr(_target, "__all__", [k for k in dir(_target) if not k.startswith("_")])
