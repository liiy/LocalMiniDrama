"""平台化改造通用工具。

这些工具服务于 Prompt / Skill / Workflow / Memory 底座，避免每个服务重复处理
JSON 序列化、时间戳、字典清洗等样板代码。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from string import Formatter
from typing import Any


def now_iso() -> str:
    """生成与现有接口一致的 UTC ISO 时间字符串。"""
    dt = datetime.now(timezone.utc)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"


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
    """使用 Python format 语法渲染 Prompt 模板。

    这里刻意保留缺失变量，而不是直接抛错。原因是 Prompt 模板经常分版本迭代，
    保留 `{missing}` 能让测试和运行日志清楚暴露缺口，同时不中断低风险预览。
    """
    safe_vars = SafeFormatDict({k: "" if v is None else v for k, v in (variables or {}).items()})
    return Formatter().vformat(template or "", (), safe_vars)


def compact_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """去掉数据库行中的软删除字段空值，保持 API 返回简洁。"""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not (k == "deleted_at" and not v)}
