from __future__ import annotations

import pytest

from app.core.config import database_timezone_from_config
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

    assert captured["connect_args"] == {"init_command": "SET time_zone = '+08:00'"}
    assert db_session.engine is sentinel_engine
