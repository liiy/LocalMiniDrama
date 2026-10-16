# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.constants.generation_style_presets."""
from app.constants.generation_style_presets import *  # noqa: F401, F403
import app.constants.generation_style_presets as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
