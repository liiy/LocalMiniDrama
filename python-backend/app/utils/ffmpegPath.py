# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.utils.ffmpeg_path."""
from app.utils.ffmpeg_path import *  # noqa: F401, F403
import app.utils.ffmpeg_path as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
