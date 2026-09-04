"""结构化输出与 JSON 鲁棒解析器 (Robust JSON Parser & Pydantic Validator)。

提供对大语言模型返回文本的工业级容错提取、截断修复、格式修正与 Pydantic 强类型校验。
"""
from __future__ import annotations

import json
import re
from typing import Any, TypeVar, get_args, get_origin
from pydantic import BaseModel, ValidationError

from app.core.logger import get_logger

log = get_logger("lmd.schemas.parser")

T = TypeVar("T", bound=BaseModel)


def clean_markdown_fences(text: str) -> str:
    """去除 Markdown ```json ... ``` 代码块标记。"""
    s = text.strip()
    # 匹配 ```json ... ``` 或 ``` ... ```
    pattern = r"^```(?:json|JSON)?\s*\n?([\s\S]*?)\n?```$"
    match = re.match(pattern, s)
    if match:
        return match.group(1).strip()
    # 如果前后有多余的文字，尝试定位第一个 ```json ... ``` 块
    block_match = re.search(r"```(?:json|JSON)?\s*\n?([\s\S]*?)\n?```", s)
    if block_match:
        return block_match.group(1).strip()
    return s


def fix_trailing_commas(json_str: str) -> str:
    """修复 JSON 中对象或数组末尾多余的逗号 (如 `{"a": 1,}` 或 `[1, 2,]`)。"""
    # 处理对象末尾多余逗号
    json_str = re.sub(r",\s*\}", "}", json_str)
    # 处理数组末尾多余逗号
    json_str = re.sub(r",\s*\]", "]", json_str)
    return json_str


def sanitize_raw_string(s: str) -> str:
    """过滤危险控制字符，保留正常排版空白。"""
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)


def repair_truncated_json(text: str) -> str:
    """尝试自动补齐因输出 Token 耗尽而导致括号/引号未闭合的截断 JSON。"""
    cleaned = text.strip()
    if not cleaned:
        return ""

    stack: list[str] = []
    in_string = False
    escape = False

    for c in cleaned:
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c in ("{", "["):
                stack.append(c)
            elif c == "}" and stack and stack[-1] == "{":
                stack.pop()
            elif c == "]" and stack and stack[-1] == "[":
                stack.pop()

    repaired = cleaned
    # 如果处于未闭合的字符串中，先闭合引号
    if in_string:
        repaired += '"'

    # 倒序闭合未封闭的大括号/中括号
    while stack:
        top = stack.pop()
        if top == "{":
            repaired += "}"
        elif top == "[":
            repaired += "]"

    return fix_trailing_commas(repaired)


def extract_first_json_payload(text: str) -> Any:
    """从任意混合文本中提取首个有效的 JSON 载荷（Dict 或 List）。"""
    text = clean_markdown_fences(text)
    text = sanitize_raw_string(text)

    # 1. 尝试直接标准解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 尝试修复多余逗号后解析
    try:
        return json.loads(fix_trailing_commas(text))
    except json.JSONDecodeError:
        pass

    # 3. 寻找最外层 { ... } 或 [ ... ]
    start_brace = text.find("{")
    start_bracket = text.find("[")

    start_idx = -1
    target_type = None

    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        start_idx = start_brace
        target_type = "object"
    elif start_bracket != -1:
        start_idx = start_bracket
        target_type = "array"

    if start_idx == -1:
        raise ValueError("在返回内容中未找到任何有效的 JSON 起始标记 ('{' 或 '[')")

    candidate = text[start_idx:]
    
    # 4. 尝试截断修复
    repaired = repair_truncated_json(candidate)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        log.warning("JSON repair failed", extra={"error": str(e), "raw_snippet": candidate[:200]})
        raise ValueError(f"无法将文本解析为有效 JSON: {e.msg} (位置: {e.pos})") from e


def parse_structured_output(raw_text: str, model_cls: type[T]) -> T:
    """将 LLM 原始文本输出解析并强类型校验为指定的 Pydantic 模型。

    Args:
        raw_text: 模型输出的原文字符串
        model_cls: 目标 Pydantic 模型类（如 ScriptSpec, DramaBible 等）

    Returns:
        解析并校验通过的 Pydantic 实例

    Raises:
        ValueError: JSON 提取失败或字段结构不满足 Schema 要求
    """
    payload = extract_first_json_payload(raw_text)
    if not isinstance(payload, dict):
        raise ValueError(f"期望得到 JSON 对象 (dict)，实际得到: {type(payload).__name__}")

    try:
        return model_cls.model_validate(payload)
    except ValidationError as e:
        log.warning("Pydantic validation failed", extra={"model": model_cls.__name__, "errors": e.errors()})
        raise ValueError(f"数据结构不符合 {model_cls.__name__} 规范: {e}") from e


def parse_structured_list(raw_text: str, model_cls: type[T]) -> list[T]:
    """将 LLM 原始文本输出解析并校验为指定 Pydantic 模型列表。

    Args:
        raw_text: 模型输出的原文字符串
        model_cls: 列表项的 Pydantic 模型类（如 StoryboardShot, CharacterProfile 等）

    Returns:
        解析并校验通过的 Pydantic 模型列表
    """
    payload = extract_first_json_payload(raw_text)
    
    # 兼容 payload 顶层是 {"items": [...]} 或 {"data": [...]} 或 {"shots": [...]} 等情况
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("items", "data", "list", "shots", "characters", "scenes", "props", "episodes"):
            if key in payload and isinstance(payload[key], list):
                items = payload[key]
                break
        if not items:
            # 单个对象包装为单个列表项
            items = [payload]

    results: list[T] = []
    errors: list[str] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            results.append(model_cls.model_validate(item))
        except ValidationError as e:
            errors.append(f"第 {idx + 1} 项验证失败: {e.errors()}")

    if errors and not results:
        raise ValueError(f"所有列表项均未通过 {model_cls.__name__} 校验: {'; '.join(errors[:3])}")

    return results
