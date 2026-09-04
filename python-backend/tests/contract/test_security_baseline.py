from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import config as cfgmod
from app.main import create_app


def test_database_url_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("LMD_DATABASE_URL", "mysql+pymysql://env-user:env-pass@127.0.0.1:3306/env_db")
    cfg = {"database": {"url": "mysql+pymysql://file-user:file-pass@127.0.0.1:3306/file_db"}}

    assert cfgmod.database_url_from_config(cfg) == "mysql+pymysql://env-user:env-pass@127.0.0.1:3306/env_db"


def test_auth_enabled_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("LMD_AUTH_ENABLED", "true")
    monkeypatch.setenv("LMD_API_TOKEN", "test-token")
    app = create_app()

    with TestClient(app) as client:
        r = client.get("/api/v1/settings/language")

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


def test_auth_enabled_accepts_bearer_token(monkeypatch):
    monkeypatch.setenv("LMD_AUTH_ENABLED", "true")
    monkeypatch.setenv("LMD_API_TOKEN", "test-token")
    app = create_app()

    with TestClient(app) as client:
        r = client.get(
            "/api/v1/settings/language",
            headers={"Authorization": "Bearer test-token", "X-Request-ID": "req-test"},
        )

    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "req-test"


def test_health_is_public_when_auth_enabled(monkeypatch):
    monkeypatch.setenv("LMD_AUTH_ENABLED", "true")
    monkeypatch.setenv("LMD_API_TOKEN", "test-token")
    app = create_app()

    with TestClient(app) as client:
        r = client.get("/health")

    assert r.status_code == 200
