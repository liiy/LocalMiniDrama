# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.deepseek_config."""
from app.services.deepseek_config import *  # noqa: F401, F403
import app.services.deepseek_config as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
