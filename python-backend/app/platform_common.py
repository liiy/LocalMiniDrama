"""平台化改造通用工具（已重构并代理至 app.common 包，保持 100% 向后兼容）。

这些工具服务于 Prompt / Skill / Workflow / Memory 底座，避免每个服务重复处理
JSON 序列化、时间戳、字典清洗等样板代码。
"""
from __future__ import annotations

from app.common.file_utils import compact_dict, ensure_dir, safe_filename
from app.common.json_utils import (
    ensure_valid_json_str,
    json_dumps,
    json_loads,
    safe_json_dumps,
    safe_json_loads,
)
from app.common.template_utils import SafeFormatDict, render_template_text
from app.common.time_utils import (
    BEIJING_TZ,
    beijing_now,
    now_beijing_str,
    now_iso,
    timestamp,
)

__all__ = [
    "BEIJING_TZ",
    "beijing_now",
    "now_iso",
    "now_beijing_str",
    "timestamp",
    "json_dumps",
    "json_loads",
    "safe_json_dumps",
    "safe_json_loads",
    "ensure_valid_json_str",
    "SafeFormatDict",
    "render_template_text",
    "compact_dict",
    "ensure_dir",
    "safe_filename",
]

