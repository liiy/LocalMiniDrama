"""DeepSeek 官方站专有请求参数 — 契约翻译 backend-node/src/services/deepseekConfig.js。

用途：testConnection 对 DeepSeek 官方端点发最小探针时，必须带上 thinking / reasoning_effort
等参数，否则官方会直接返回错误。
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

OFFICIAL_HOST_RE = re.compile(r"(^|\.)api\.deepseek\.com$", re.IGNORECASE)

LEGACY_MODEL_OPTIONS = {
    "deepseek-chat": {"model": "deepseek-v4-flash", "thinking": "disabled"},
    "deepseek-reasoner": {"model": "deepseek-v4-flash", "thinking": "enabled"},
}


def parse_settings(settings: Any) -> dict:
    if not settings:
        return {}
    if isinstance(settings, dict):
        return settings
    try:
        parsed = json.loads(settings)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_deepseek_official_config(config: dict | None = None) -> bool:
    config = config or {}
    provider = str(config.get("provider") or "").strip().lower()
    if provider == "deepseek":
        return True

    raw_base = str(config.get("base_url") or "").strip()
    if not raw_base:
        return False
    host = ""
    try:
        host = urlparse(raw_base).hostname or ""
    except Exception:
        host = ""
    if host:
        return OFFICIAL_HOST_RE.search(host) is not None
    return "api.deepseek.com" in raw_base.lower()


def _is_nullish_or_empty(v: Any) -> bool:
    """等价 JS `value == null || value === ''`（额外吸收 0，与 JS `0 == ''` 一致）。"""
    if v is None:
        return True
    if isinstance(v, str):
        return v == ""
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v == 0
    return False


def _nullish(*values: Any) -> Any:
    """等价 JS 的 ?? 链：返回第一个非 None 的值。"""
    for v in values:
        if v is not None:
            return v
    return None


def normalize_thinking(value: Any) -> str | None:
    if _is_nullish_or_empty(value):
        return None
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    v = str(value).strip().lower()
    if v in ("enabled", "enable", "on", "true", "thinking"):
        return "enabled"
    if v in ("disabled", "disable", "off", "false", "non-thinking"):
        return "disabled"
    return None


def normalize_reasoning_effort(value: Any) -> str | None:
    if _is_nullish_or_empty(value):
        return None
    v = str(value).strip().lower()
    if v in ("max", "xhigh"):
        return "max"
    if v in ("high", "medium", "low"):
        return "high"
    return None


def resolve_deepseek_options(config: dict | None = None, model: Any = None) -> dict:
    config = config or {}
    model_name = str(model or "").strip()
    legacy = LEGACY_MODEL_OPTIONS.get(model_name.lower())
    settings = parse_settings(config.get("settings"))
    nested = settings.get("deepseek") if isinstance(settings.get("deepseek"), dict) else {}

    explicit_thinking = normalize_thinking(
        _nullish(
            settings.get("deepseek_thinking"),
            settings.get("thinking"),
            nested.get("thinking"),
            nested.get("type"),
        )
    )
    reasoning_effort = normalize_reasoning_effort(
        _nullish(
            settings.get("deepseek_reasoning_effort"),
            settings.get("reasoning_effort"),
            nested.get("reasoning_effort"),
            nested.get("effort"),
        )
    )

    return {
        "model": legacy["model"] if legacy else model_name,
        "thinking": explicit_thinking or (legacy["thinking"] if legacy else None),
        "reasoning_effort": reasoning_effort,
    }


def apply_deepseek_chat_options(config: dict, body: dict | None) -> dict:
    body = body or {}
    if not is_deepseek_official_config(config):
        return body

    opts = resolve_deepseek_options(config, body.get("model"))
    nxt = {**body, "model": opts["model"] or body.get("model")}

    if opts["thinking"]:
        nxt["thinking"] = {"type": opts["thinking"]}

    if opts["thinking"] == "enabled":
        if opts["reasoning_effort"]:
            nxt["reasoning_effort"] = opts["reasoning_effort"]
        nxt.pop("temperature", None)
    else:
        nxt.pop("reasoning_effort", None)

    return nxt


def apply_deepseek_connectivity_options(config: dict, body: dict | None) -> dict:
    """连通性测试专用：非官方配置原样返回；官方配置补齐 thinking 并去掉 reasoning_effort。"""
    body = body or {}
    if not is_deepseek_official_config(config):
        return body
    nxt = apply_deepseek_chat_options(config, body)
    if not nxt.get("thinking"):
        nxt["thinking"] = {"type": "disabled"}
    nxt.pop("reasoning_effort", None)
    return nxt
