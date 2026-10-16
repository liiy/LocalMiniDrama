# -*- coding: utf-8 -*-
"""Backward compatibility shim for app.services.merged_episode_post_process."""
from app.services.merged_episode_post_process import *  # noqa: F401, F403
import app.services.merged_episode_post_process as _target_module

for _k, _v in _target_module.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v
