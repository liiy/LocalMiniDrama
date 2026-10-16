# -*- coding: utf-8 -*-
"""兼容垫片：storageLayout -> app.services.storage_layout。

保留此文件仅用于保障极少部分外部系统或老旧单测的向后兼容性。
业务逻辑与内部调用已全部迁移至规范的 snake_case 模块：`app.services.storage_layout`。
"""
from __future__ import annotations

from app.services.storage_layout import *  # noqa: F401, F403
import app.services.storage_layout as _target

__all__ = getattr(_target, "__all__", [k for k in dir(_target) if not k.startswith("_")])
