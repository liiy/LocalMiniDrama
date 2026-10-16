# -*- coding: utf-8 -*-
"""兼容垫片：safeJson -> app.utils.safe_json。

保留此文件仅用于保障极少部分外部系统或老旧单测的向后兼容性。
业务逻辑与内部调用已全部迁移至规范的 snake_case 模块：`app.utils.safe_json`。
"""
from __future__ import annotations

from app.utils.safe_json import *  # noqa: F401, F403
import app.utils.safe_json as _target

__all__ = getattr(_target, "__all__", [k for k in dir(_target) if not k.startswith("_")])
