"""平台化改造通用工具。

这些工具服务于 Prompt / Skill / Workflow / Memory 底座，避免每个服务重复处理
JSON 序列化、时间戳、字典清洗等样板代码。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from string import Formatter
from typing import Any

# 北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))

# 匹配合法的 Python 标识符占位符 {variable_name}，避免误伤 JSON Schema 结构（如 { name: string, type: '内景' }）
_VARIABLE_PATTERN = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")


def beijing_now() -> datetime:
    """获取当前北京时间（UTC+8）datetime 对象。"""
    return datetime.now(BEIJING_TZ)


def now_iso() -> str:
    """生成北京时间（UTC+8）的 ISO-8601 时间字符串（如 2026-09-11T16:30:00.123+08:00）。"""
    return datetime.now(BEIJING_TZ).isoformat(timespec="milliseconds")


def now_beijing_str() -> str:
    """生成北京时间格式化字符串（如 2026-09-11 16:30:00）。"""
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


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
    except json.JSONDecodeError:
        return default


class SafeFormatDict(dict):
    """Prompt 渲染专用字典：缺失变量原样保留，方便调试模板缺口。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template_text(template: str, variables: dict[str, Any] | None = None) -> str:
    """渲染 Prompt 模板中的 {variable} 占位符。

    设计规则：
    1. 仅将符合 Python 标识符规范的 `{var_name}` 进行变量替换；
    2. 若 `var_name` 在 `variables` 中存在，则替换为对应值（None 转为空字符串）；
    3. 若 `var_name` 缺失，则原样保留 `{var_name}`，方便暴露模板缺口；
    4. 模板中包含的 JSON Schema 或示例（如 `{ name: string, type: '内景' }` 等含冒号/换行/空格的大括号）
       将被严格视为普通文本保留，彻底杜绝标准 `str.format` 因 `format_spec` 解析而抛出 `Invalid format specifier` 异常。
    """
    if not template:
        return ""
    vars_dict = variables or {}

    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in vars_dict:
            val = vars_dict[key]
            return "" if val is None else str(val)
        return match.group(0)

    return _VARIABLE_PATTERN.sub(_replacer, template)


def compact_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """去掉数据库行中的软删除字段空值，保持 API 返回简洁。"""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not (k == "deleted_at" and not v)}
