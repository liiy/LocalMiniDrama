"""全局键值设置服务：等价 Node services/settingsService.js 的 get/setGlobalSetting。

- 读：SELECT value，JSON.parse 成功返回解析值，失败返回原字符串
- 写：JSON.stringify 后 UPSERT
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_one


def get_global_setting(db: Session, key: str, default: Any = None) -> Any:
    row = fetch_one(db, "SELECT value FROM global_settings WHERE `key` = :key", {"key": key})
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def set_global_setting(db: Session, key: str, value: Any) -> None:
    now = timestamp()
    s = json.dumps(value)
    execute(
        db,
        """
        INSERT INTO global_settings (`key`, value, updated_at) VALUES (:key, :value, :updated_at)
        ON DUPLICATE KEY UPDATE value = :value, updated_at = :updated_at
        """,
        {"key": key, "value": s, "updated_at": now},
    )
