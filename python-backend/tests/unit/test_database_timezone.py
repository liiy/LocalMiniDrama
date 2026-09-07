from __future__ import annotations

import pytest

from app.core.config import database_pool_settings_from_config, database_timezone_from_config
from app.db import session as db_session


def test_database_timezone_defaults_to_china_standard_time(monkeypatch):
    monkeypatch.delenv("LMD_DATABASE_TIMEZONE", raising=False)

    assert database_timezone_from_config({"database": {}}) == "+08:00"


def test_database_timezone_environment_overrides_config(monkeypatch):
    monkeypatch.setenv("LMD_DATABASE_TIMEZONE", "+09:30")

    assert database_timezone_from_config({"database": {"timezone": "+08:00"}}) == "+09:30"


def test_database_timezone_rejects_sql_and_named_timezones(monkeypatch):
    monkeypatch.delenv("LMD_DATABASE_TIMEZONE", raising=False)

    with pytest.raises(ValueError, match="database.timezone"):
        database_timezone_from_config({"database": {"timezone": "Asia/Shanghai"}})


def test_mysql_engine_sets_timezone_for_every_physical_connection(monkeypatch):
    captured: dict = {}
    sentinel_engine = object()

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return sentinel_engine

    monkeypatch.setattr(db_session, "engine", None)
    monkeypatch.setattr(db_session, "SessionLocal", None)
    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)
    monkeypatch.setattr(db_session, "load_config", lambda: {"database": {"timezone": "+08:00"}})

    db_session.init_engine("mysql+pymysql://user:pass@127.0.0.1/lmd")

    assert captured["connect_args"] == {
        "init_command": "SET time_zone = '+08:00'",
        "connect_timeout": 10,
    }
    assert captured["pool_pre_ping"] is True
    assert captured["pool_size"] == 10
    assert captured["max_overflow"] == 20
    assert captured["pool_timeout"] == 30
    assert captured["pool_recycle"] == 1200
    assert captured["pool_use_lifo"] is True
    assert captured["pool_reset_on_return"] == "rollback"
    assert db_session.engine is sentinel_engine


def test_database_pool_settings_support_custom_values():
    settings = database_pool_settings_from_config(
        {
            "database": {
                "pool_size": 16,
                "max_overflow": 8,
                "pool_timeout_seconds": 12,
                "pool_recycle_seconds": 600,
                "connect_timeout_seconds": 5,
            }
        }
    )

    assert settings == {
        "pool_size": 16,
        "max_overflow": 8,
        "pool_timeout_seconds": 12,
        "pool_recycle_seconds": 600,
        "connect_timeout_seconds": 5,
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [("pool_size", 0), ("max_overflow", -1), ("pool_recycle_seconds", "invalid")],
)
def test_database_pool_settings_reject_invalid_values(key, value):
    with pytest.raises(ValueError, match=f"database.{key}"):
        database_pool_settings_from_config({"database": {key: value}})
