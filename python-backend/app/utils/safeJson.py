"""安全解析 AI 生成的 JSON 输出，等价 Node utils/safeJson.js。

支持：
- 剥离 markdown 代码块（```json ... ```）
- 控制字符过滤与字符串内未转义换行符转义
- 括号匹配提取 JSON 候选串
- 截断 JSON 数组修复
- 提取首个数组 extract_first_array
"""
from __future__ import annotations

import json
import re
from typing import Any


def sanitize_control_chars(s: str) -> str:
    # 移除 0x00–0x08, 0x0B, 0x0C, 0x0E–0x1F 控制字符，保留 \t, \n, \r
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)


def escape_newlines_in_strings(s: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    for c in s:
        if in_string:
            if escape:
                escape = False
                result.append(c)
                continue
            if c == "\\":
                escape = True
                result.append(c)
                continue
            if c == '"':
                in_string = False
                result.append(c)
                continue
            if c == "\n":
                result.append("\\n")
                continue
            if c == "\r":
                result.append("\\r")
                continue
            if c == "\t":
                result.append("\\t")
                continue
            result.append(c)
        else:
            if c == '"':
                in_string = True
            result.append(c)
    return "".join(result)


def extract_json_candidate(text: str) -> str:
    start = -1
    for i, c in enumerate(text):
        if c in ("{", "["):
            start = i
            break
    if start == -1:
        return ""

    stack: list[str] = []
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_string:
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = False
            continue

        if c == '"':
            in_string = True
            continue
        if c in ("{", "["):
            stack.append(c)
        elif c in ("}", "]"):
            if stack:
                stack.pop()
                if not stack:
                    return text[start : i + 1]

    return text[start:]


def repair_truncated_json_array(text: str) -> str | None:
    trimmed = text.lstrip()
    if not trimmed.startswith("["):
        return None

    depth = 0
    in_string = False
    escape = False
    last_complete_pos = -1

    for i, c in enumerate(trimmed):
        if in_string:
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = False
            continue

        if c == '"':
            in_string = True
            continue
        if c in ("{", "["):
            depth += 1
        elif c in ("}", "]"):
            depth -= 1
            if depth == 1:
                last_complete_pos = i + 1
            elif depth == 0:
                return trimmed[: i + 1]

    if last_complete_pos == -1:
        # 尝试按最后一个 } 截断修复
        last_brace = trimmed.rfind("}")
        if last_brace != -1:
            cut = trimmed[: last_brace + 1].rstrip()
            cut = re.sub(r",\s*$", "", cut)
            return cut + "]"
        return None

    return trimmed[:last_complete_pos] + "]"


def extract_wrapped_array_str(text: str) -> str | None:
    trimmed = text.lstrip()
    if trimmed.startswith("["):
        return None
    in_string = False
    escape = False
    for i, c in enumerate(trimmed):
        if in_string:
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c == "[":
            return trimmed[i:]
    return None


def extract_first_array(obj: Any) -> list | None:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list):
                return v
    return None


def safe_parse_ai_json(ai_response: str, log=None, out_meta: dict | None = None) -> Any:
    if not ai_response or not isinstance(ai_response, str):
        raise ValueError("AI返回内容为空")

    cleaned = sanitize_control_chars(ai_response).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    cleaned = escape_newlines_in_strings(cleaned)

    json_str = extract_json_candidate(cleaned)
    if not json_str:
        raise ValueError("响应中未找到有效的JSON对象或数组")

    # 1. 直接尝试解析
    try:
        return json.loads(json_str)
    except Exception:
        pass

    # 2. 尝试修复外层或内层数组截断
    inner_array_str = extract_wrapped_array_str(json_str)
    candidate_strs = [json_str]
    if inner_array_str:
        candidate_strs.insert(0, inner_array_str)

    for cand in candidate_strs:
        repaired = repair_truncated_json_array(cand)
        if repaired:
            try:
                res = json.loads(repaired)
                if out_meta is not None:
                    out_meta["truncated"] = True
                return res
            except Exception:
                pass

    # 3. 终极兜底：调用 app.schemas.parser 的深度容错与截断闭合解析引擎
    try:
        from app.schemas.parser import extract_first_json_payload
        deep_parsed = extract_first_json_payload(ai_response)
        if deep_parsed is not None:
            if out_meta is not None:
                out_meta["repaired_by_parser"] = True
            return deep_parsed
    except Exception:
        pass

    raise ValueError("解析 AI 返回的 JSON 失败")


# 驼峰别名与 Node 兼容
safeParseAIJSON = safe_parse_ai_json
extractFirstArray = extract_first_array
