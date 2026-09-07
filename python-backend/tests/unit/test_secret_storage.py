"""AI 配置敏感字段加密存储测试。"""
from __future__ import annotations

import logging

from app.core.secret_store import SECRET_PREFIX
from app.db.session import execute, fetch_one
from app.services import aiConfigService


def _config_payload(api_key: str) -> dict:
    return {
        "service_type": "text",
        "provider": "openai",
        "name": "加密测试配置",
        "base_url": "https://example.invalid/v1",
        "api_key": api_key,
        "model": ["test-model"],
    }


def test_ai_config_api_key_is_encrypted_at_rest(db_session):
    """服务层返回可用明文，但数据库原始字段不得出现明文 Key。"""
    item = aiConfigService.create_config(
        db_session,
        logging.getLogger("test.secret"),
        _config_payload("sk-private-value"),
    )
    raw = fetch_one(db_session, "SELECT api_key FROM ai_service_configs WHERE id = :id", {"id": item["id"]})

    assert item["api_key"] == "sk-private-value"
    assert raw["api_key"].startswith(SECRET_PREFIX)
    assert "sk-private-value" not in raw["api_key"]


def test_plaintext_ai_key_migration_preserves_runtime_value(db_session):
    """历史明文升级为密文后，现有 Provider 读取契约保持不变。"""
    item = aiConfigService.create_config(
        db_session,
        logging.getLogger("test.secret"),
        _config_payload("temporary-key"),
    )
    execute(
        db_session,
        "UPDATE ai_service_configs SET api_key = :api_key WHERE id = :id",
        {"api_key": "legacy-plain-key", "id": item["id"]},
    )

    migrated = aiConfigService.migrate_plaintext_api_keys(
        db_session,
        logging.getLogger("test.secret"),
    )
    raw = fetch_one(db_session, "SELECT api_key FROM ai_service_configs WHERE id = :id", {"id": item["id"]})
    loaded = aiConfigService.get_config(db_session, item["id"])

    assert migrated == 1
    assert raw["api_key"].startswith(SECRET_PREFIX)
    assert loaded["api_key"] == "legacy-plain-key"
