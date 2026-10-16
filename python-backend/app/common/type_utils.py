# -*- coding: utf-8 -*-
"""通用类型转换与数值安全处理工具。

提供类型安全的转换函数（如 safe_int, safe_float, safe_bool, safe_round），
消除散落在各业务模块中的 JS 兼容仿造逻辑（如 _to_num, _safe_round, js_parse_int 等），
统一异常捕获与调试日志记录，确保业务逻辑在应对脏数据时具备高鲁棒性。
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Sequence

logger = logging.getLogger("app.common.type_utils")

# 预编译整数匹配正则表达式，支持可选正负号
_INT_RE = re.compile(r"^[+-]?\d+")


def is_finite(n: Any) -> bool:
    """判断给定的数值是否为有效有限数值（排除 NaN, +inf, -inf）。

    Args:
        n: 待判断的数值或任意对象。

    Returns:
        若为有限数值返回 True，否则返回 False。
    """
    if not isinstance(n, (int, float)):
        return False
    return not (math.isnan(n) or math.isinf(n))


def safe_int(value: Any, default: int = 0) -> int:
    """安全地将输入转换为整数。

    支持 int, float, str, bool 等输入。遇到 None、空串或无法转换的数据时，
    安全记录 DEBUG 级别日志并返回指定的默认值，防止抛出 ValueError/TypeError。

    Args:
        value: 待转换的值。
        default: 转换失败或遇到空值时的兜底默认值，默认为 0。

    Returns:
        转换后的整数。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not is_finite(value):
            logger.debug("safe_int 遇到非法浮点数 %r，回退到默认值 %s", value, default)
            return default
        return int(value)
    
    val_str = str(value).strip()
    if not val_str:
        return default

    try:
        # 兼容 "123" 以及 "123.45" 字符串转 int
        if "." in val_str:
            return int(float(val_str))
        return int(val_str)
    except (ValueError, TypeError) as err:
        logger.debug("safe_int 无法解析 %r (%s)，回退到默认值 %s", value, err, default)
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """安全地将输入转换为浮点数。

    支持 int, float, str, bool 等输入。对于空值或非法输入安全回退到默认值，
    若解析出 NaN 或 Inf 也会被拦截并返回默认值。

    Args:
        value: 待转换的值。
        default: 转换失败或遇到空值时的兜底默认值，默认为 0.0。

    Returns:
        转换后的有效有限浮点数。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if not is_finite(value):
            logger.debug("safe_float 遇到非有限浮点数 %r，回退到默认值 %s", value, default)
            return default
        return float(value)

    val_str = str(value).strip()
    if not val_str:
        return default

    try:
        parsed = float(val_str)
        if not is_finite(parsed):
            logger.debug("safe_float 解析结果非有限数 %r，回退到默认值 %s", parsed, default)
            return default
        return parsed
    except (ValueError, TypeError) as err:
        logger.debug("safe_float 无法解析 %r (%s)，回退到默认值 %s", value, err, default)
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    """安全地将输入转换为布尔值。

    支持对 'true', '1', 'yes', 't', 'y', 'on' 等字符串表示的布尔值识别。

    Args:
        value: 待转换的值。
        default: 无法确定时的默认值，默认为 False。

    Returns:
        转换后的布尔值。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0

    val_str = str(value).strip().lower()
    if val_str in ("true", "1", "yes", "y", "t", "on"):
        return True
    if val_str in ("false", "0", "no", "n", "f", "off", ""):
        return False

    logger.debug("safe_bool 无法明确识别 %r，回退到默认值 %s", value, default)
    return default


def safe_round(n: Any, ndigits: int = 0, default: int | float = 0) -> int | float:
    """安全四舍五入。

    解决 Python 内置 round() 在偶数逢五时的银行家舍入行为（向偶数舍入），
    提供符合日常业务预期的算术四舍五入（>= 0.5 向上入，< 0.5 舍去）。
    同时对 NaN、Inf、非法输入等做兜底保护。

    Args:
        n: 待舍入的数值。
        ndigits: 小数保留位数，默认为 0（返回 int 或 float）。
        default: 遇到非法输入时的默认返回值，默认为 0。

    Returns:
        四舍五入后的整数（ndigits=0 时）或浮点数。
    """
    num = safe_float(n, default=float("nan"))
    if not is_finite(num):
        logger.debug("safe_round 遇到非数值 %r，使用兜底值 %s", n, default)
        return default

    if ndigits <= 0:
        # 算术四舍五入整数
        if num >= 0:
            return int(math.floor(num + 0.5))
        return -int(math.floor(-num + 0.5))

    factor = 10 ** ndigits
    scaled = num * factor
    if scaled >= 0:
        rounded = math.floor(scaled + 0.5) / factor
    else:
        rounded = -math.floor(-scaled + 0.5) / factor
    return rounded


def to_int_id(value: Any, default: int = -1) -> int:
    """用于数据库主键/外键 ID 的安全整数转换。

    通常用于 WHERE id = ? 查询。如果解析失败或 ID 非法，返回 -1（确保不匹配任何正整数主键）。

    Args:
        value: 待转换的 ID 值。
        default: 解析失败时的默认值，默认为 -1。

    Returns:
        主键整数。
    """
    if value is None:
        return default
    val_str = str(value).strip()
    if not val_str:
        return default
    try:
        parsed = int(val_str)
        return parsed
    except (ValueError, TypeError):
        logger.debug("to_int_id 无法将 %r 转换为合法 ID，使用默认值 %s", value, default)
        return default


def js_parse_int(value: Any, default: int = 0) -> int:
    """兼容旧系统 JavaScript parseInt(v, 10) 语义的前缀数字提取函数。

    例如：
        "120px" -> 120
        "-42abc" -> -42
        "abc" -> default

    Args:
        value: 待解析的值。
        default: 匹配失败时的默认值。

    Returns:
        解析出的首部整数。
    """
    if value is None:
        return default
    val_str = str(value).strip()
    match = _INT_RE.match(val_str)
    if not match:
        logger.debug("js_parse_int 无法从 %r 中匹配整数前缀，使用默认值 %s", value, default)
        return default
    try:
        return int(match.group(0))
    except (ValueError, TypeError):
        return default


def normalize_str(value: Any, default: str = "") -> str:
    """标准化字符串去除首尾空格。

    Args:
        value: 输入对象。
        default: 值为 None 时的默认值。

    Returns:
        修剪后的字符串。
    """
    if value is None:
        return default
    return str(value).strip()


def parse_comma_list(value: Any) -> list[str]:
    """安全解析逗号分隔的字符串列表或数组。

    支持对数组逐项 strip，或对逗号分隔的字符串切分并过滤空项。

    Args:
        value: 列表、元组或逗号分隔的字符串。

    Returns:
        过滤空字符串后的字符串列表。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [s for item in value if (s := normalize_str(item))]
    return [s for part in str(value).split(",") if (s := part.strip())]
