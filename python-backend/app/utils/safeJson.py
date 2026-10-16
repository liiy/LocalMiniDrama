# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.utils.safe_json."""
from app.utils.safe_json import *  # noqa: F401, F403
import app.utils.safe_json as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
