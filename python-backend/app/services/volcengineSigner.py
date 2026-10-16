# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.volcengine_signer."""
from app.services.volcengine_signer import *  # noqa: F401, F403
import app.services.volcengine_signer as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
