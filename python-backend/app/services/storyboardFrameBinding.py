# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.storyboard_frame_binding."""
from app.services.storyboard_frame_binding import *  # noqa: F401, F403
import app.services.storyboard_frame_binding as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
