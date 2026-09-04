"""/api/v1/settings/* — 契约精确翻译 backend-node/src/routes/settings.js。

行为要点（与 Node 逐条对齐）：
- GET /settings/language 读内存配置 app.language
- PUT /settings/language 校验 zh/en → 写内存 + 写回 config.yaml
- GET /settings/generation 读 global_settings 表；timeout 每次动态读 config.yaml
- PUT /settings/generation 用 Number() 语义校验（字符串 "5" 可通过，null/"" → 0 失败）
"""
from __future__ import annotations

import math
import os
from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core import config as cfgmod
from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import bad_request, success
from app.db.session import get_db
from app.services import globalSettingsService as gss

router = APIRouter(tags=["settings"])
log = get_logger("lmd.settings")

# 内存态配置（等价 Node app.js 启动时 loadConfig 一次并闭包传递）
_CFG: dict[str, Any] = {"app": {"language": "zh"}, "video": {}}


def init_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = cfg


def _to_number(v: Any) -> float:
    """等价 JS Number(v)。"""
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _is_positive_int(n: float) -> bool:
    return not math.isnan(n) and n == int(n) and 1 <= int(n) <= 20


# ---------------- language ----------------

@router.get("/settings/language")
def get_language() -> dict:
    return success({"language": cfgmod.get_language(_CFG)})


@router.put("/settings/language")
def update_language(payload: dict = Body(default={})) -> dict:
    lang = payload.get("language")
    if lang not in ("zh", "en"):
        raise bad_request("语言参数错误，只支持 zh 或 en")
    _CFG.setdefault("app", {})["language"] = lang
    try:
        cfgmod.save_config(_CFG)
    except Exception as e:  # 写盘失败不影响响应（与 Node try/catch 一致）
        log.warning("Failed to write config file", extra={"error": str(e)})
    message = "Language switched to English" if lang == "en" else "语言已切换为中文"
    return success({"message": message, "language": lang})


# ---------------- generation ----------------

@router.get("/settings/generation")
def get_generation_settings(db: Session = Depends(get_db)) -> dict:
    concurrency = gss.get_global_setting(db, "pipeline_concurrency", 3)
    video_concurrency = gss.get_global_setting(db, "pipeline_video_concurrency", 3)
    timeout = cfgmod.resolve_video_generation_timeout_minutes(load_config())
    return success(
        {
            "concurrency": concurrency,
            "video_concurrency": video_concurrency,
            "video_generation_timeout_minutes": timeout,
        }
    )


@router.put("/settings/generation")
def update_generation_settings(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    if "concurrency" in payload:
        n = _to_number(payload["concurrency"])
        if not _is_positive_int(n):
            raise bad_request("图片并发数需为 1-20 之间的整数")
        gss.set_global_setting(db, "pipeline_concurrency", int(n))
    if "video_concurrency" in payload:
        n = _to_number(payload["video_concurrency"])
        if not _is_positive_int(n):
            raise bad_request("视频并发数需为 1-20 之间的整数")
        gss.set_global_setting(db, "pipeline_video_concurrency", int(n))
    saved = gss.get_global_setting(db, "pipeline_concurrency", 3)
    saved_video = gss.get_global_setting(db, "pipeline_video_concurrency", 3)
    timeout = cfgmod.resolve_video_generation_timeout_minutes(load_config())
    return success(
        {
            "concurrency": saved,
            "video_concurrency": saved_video,
            "video_generation_timeout_minutes": timeout,
        }
    )
