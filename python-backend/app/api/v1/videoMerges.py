# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.api.v1.video_merges."""
from app.api.v1.video_merges import *  # noqa: F401, F403
import app.api.v1.video_merges as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
