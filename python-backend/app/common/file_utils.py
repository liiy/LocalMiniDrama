"""File and dictionary helper utilities."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def ensure_dir(path: Path | str) -> Path:
    """确保目录存在，不存在则自动创建递归目录。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    """将字符串转换为安全的文件名，移除危险的非法路径字符。"""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name)
    return cleaned.strip(" .") or "file"


def compact_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """去掉数据库行中的软删除字段空值，保持 API 返回简洁。"""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not (k == "deleted_at" and not v)}
