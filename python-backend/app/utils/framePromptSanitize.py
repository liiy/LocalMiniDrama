# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.utils.frame_prompt_sanitize."""
from app.utils.frame_prompt_sanitize import *  # noqa: F401, F403
import app.utils.frame_prompt_sanitize as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
