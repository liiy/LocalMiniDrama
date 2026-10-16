# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.background_extraction_service."""
from app.services.background_extraction_service import *  # noqa: F401, F403
import app.services.background_extraction_service as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
