# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.universal_segment_prompt_bundle."""
from app.services.universal_segment_prompt_bundle import *  # noqa: F401, F403
import app.services.universal_segment_prompt_bundle as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
