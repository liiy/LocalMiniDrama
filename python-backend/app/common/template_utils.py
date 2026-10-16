"""Prompt template formatting and text processing utilities."""
from __future__ import annotations

import re
from typing import Any

# 匹配合法的 Python 标识符占位符 {variable_name}，避免误伤 JSON Schema 结构（如 { name: string, type: '内景' }）
_VARIABLE_PATTERN = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")


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
