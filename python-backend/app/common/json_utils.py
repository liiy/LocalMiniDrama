"""JSON serialization and deserialization utility functions."""
from __future__ import annotations

import json
from typing import Any


def json_dumps(value: Any) -> str:
    """统一把结构化对象保存为 JSON 字符串，便于 MySQL TEXT/MEDIUMTEXT 存储。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: Any, default: Any = None) -> Any:
    """从数据库文本字段恢复 JSON；解析失败时返回默认值，避免影响主流程。"""
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


# 别名，提高可读性
safe_json_dumps = json_dumps
safe_json_loads = json_loads


def ensure_valid_json_str(value: Any, fallback: str = "{}") -> str:
    """确保返回有效的 JSON 字符串。"""
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return json_dumps(value)
    if isinstance(value, str):
        val = value.strip()
        if not val:
            return fallback
        try:
            json.loads(val)
            return val
        except Exception:
            return fallback
    return fallback
