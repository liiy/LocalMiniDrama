# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.library_common."""
from app.services.library_common import *  # noqa: F401, F403
import app.services.library_common as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
