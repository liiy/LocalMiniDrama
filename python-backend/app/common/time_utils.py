"""Time and timezone utility functions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> datetime:
    """获取当前北京时间（UTC+8）datetime 对象。"""
    return datetime.now(BEIJING_TZ)


def now_iso() -> str:
    """生成北京时间（UTC+8）的 ISO-8601 时间字符串（如 2026-09-11T16:30:00.123+08:00）。"""
    return datetime.now(BEIJING_TZ).isoformat(timespec="milliseconds")


def now_beijing_str() -> str:
    """生成北京时间格式化字符串（如 2026-09-11 16:30:00）。"""
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def timestamp() -> str:
    """生成全局统一时间戳字符串（对齐 Node response.send 行为）。"""
    return now_iso()
