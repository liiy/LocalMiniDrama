# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.media_aspect_ratio_spec."""
from app.services.media_aspect_ratio_spec import *  # noqa: F401, F403
import app.services.media_aspect_ratio_spec as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
