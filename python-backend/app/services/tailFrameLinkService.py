# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.tail_frame_link_service."""
from app.services.tail_frame_link_service import *  # noqa: F401, F403
import app.services.tail_frame_link_service as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
