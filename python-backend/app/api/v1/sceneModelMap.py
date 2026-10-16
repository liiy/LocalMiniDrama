# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.api.v1.scene_model_map."""
from app.api.v1.scene_model_map import *  # noqa: F401, F403
import app.api.v1.scene_model_map as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
