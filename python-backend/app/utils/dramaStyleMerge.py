# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.utils.drama_style_merge."""
from app.utils.drama_style_merge import *  # noqa: F401, F403
import app.utils.drama_style_merge as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
