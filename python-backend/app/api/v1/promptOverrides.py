# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.api.v1.prompt_overrides."""
from app.api.v1.prompt_overrides import *  # noqa: F401, F403
import app.api.v1.prompt_overrides as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
