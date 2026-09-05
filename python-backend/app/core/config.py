"""配置加载：与原 Node 版 config/index.js 行为等价。

- load_config(): 每次调用都读取 YAML 文件（模拟 Node loadConfig 的动态读取，
  video.generation_timeout_minutes 等依赖此行为）。
- 文件搜索顺序：LMD_CONFIG_PATH 环境变量 → ./configs/config.yaml → ./config.yaml
  → ../backend-node/configs/config.yaml（兼容原仓库结构）。
"""
from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml

_CFG_PATH: Path | None = None
_ENV_EXPR = re.compile(r"^\$\{([A-Z0-9_]+)(?::([^}]*))?\}$")
_DOTENV_LOADED = False


def _load_dotenv_file() -> None:
    """自动加载 .env 文件中的环境变量（优先保证免配置开箱即用）。"""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True

    try:
        from dotenv import load_dotenv

        for candidate in (
            Path(".env"),
            Path("python-backend/.env"),
            Path(__file__).resolve().parents[2] / ".env",
            Path(__file__).resolve().parents[3] / ".env",
        ):
            if candidate.exists() and candidate.is_file():
                load_dotenv(candidate, override=False)
                return
    except ImportError:
        pass

    # 内置轻量解析器，无需强制依赖 python-dotenv 库
    for candidate in (
        Path(".env"),
        Path("python-backend/.env"),
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ):
        if candidate.exists() and candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()
                            if (val.startswith('"') and val.endswith('"')) or (
                                val.startswith("'") and val.endswith("'")
                            ):
                                val = val[1:-1]
                            if key and key not in os.environ:
                                os.environ[key] = val
                return
            except Exception:
                pass


_load_dotenv_file()


def _search_config_path() -> Path | None:
    _load_dotenv_file()
    env = os.environ.get("LMD_CONFIG_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for candidate in (
        Path("configs/config.yaml"),
        Path("config.yaml"),
        Path("../backend-node/configs/config.yaml"),
    ):
        if candidate.exists():
            return candidate
    return None


def set_config_path(path: str | os.PathLike | None) -> Path | None:
    """显式指定配置文件（供测试注入）。"""
    global _CFG_PATH
    _CFG_PATH = Path(path) if path else _search_config_path()
    return _CFG_PATH


def config_path() -> Path | None:
    global _CFG_PATH
    if _CFG_PATH is None:
        _CFG_PATH = _search_config_path()
    return _CFG_PATH


def load_config() -> dict[str, Any]:
    """读取 YAML 配置；文件缺失时返回最小默认结构。"""
    p = config_path()
    if p is None or not p.exists():
        return {"app": {"language": "zh"}, "video": {}}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("app", {})
    data.setdefault("video", {})
    data = _resolve_env_placeholders(data)
    _apply_env_overrides(data)
    return data


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(v) for v in value]
    if isinstance(value, str):
        m = _ENV_EXPR.match(value.strip())
        if m:
            return os.environ.get(m.group(1), m.group(2) or "")
    return value


def _apply_env_overrides(data: dict[str, Any]) -> None:
    data.setdefault("server", {})
    data.setdefault("database", {})
    data.setdefault("storage", {})
    data.setdefault("security", {})
    data["security"].setdefault("upload", {})

    if os.environ.get("LMD_DEBUG") is not None:
        data.setdefault("app", {})["debug"] = os.environ["LMD_DEBUG"].strip().lower() in {"1", "true", "yes", "on"}
    if os.environ.get("LMD_HOST"):
        data["server"]["host"] = os.environ["LMD_HOST"]
    if os.environ.get("LMD_PORT"):
        data["server"]["port"] = os.environ["LMD_PORT"]
    if os.environ.get("LMD_CORS_ORIGINS"):
        data["server"]["cors_origins"] = [
            item.strip() for item in os.environ["LMD_CORS_ORIGINS"].split(",") if item.strip()
        ]

    env_db = {
        "host": "LMD_DATABASE_HOST",
        "port": "LMD_DATABASE_PORT",
        "name": "LMD_DATABASE_NAME",
        "user": "LMD_DATABASE_USER",
        "password": "LMD_DATABASE_PASSWORD",
        "url": "LMD_DATABASE_URL",
        "timezone": "LMD_DATABASE_TIMEZONE",
    }
    for key, env_name in env_db.items():
        if os.environ.get(env_name):
            data["database"][key] = os.environ[env_name]

    if os.environ.get("LMD_STORAGE_LOCAL_PATH"):
        data["storage"]["local_path"] = os.environ["LMD_STORAGE_LOCAL_PATH"]
    if os.environ.get("LMD_STORAGE_BASE_URL"):
        data["storage"]["base_url"] = os.environ["LMD_STORAGE_BASE_URL"]
    if os.environ.get("LMD_AUTH_ENABLED") is not None:
        data["security"]["auth_enabled"] = os.environ["LMD_AUTH_ENABLED"].strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if os.environ.get("LMD_API_TOKEN"):
        data["security"]["api_token"] = os.environ["LMD_API_TOKEN"]


def save_config(cfg: dict[str, Any]) -> None:
    """写回 YAML（等价 Node settingsService.updateLanguage 的 yaml.dump）。"""
    p = config_path()
    if p is None:
        return
    cfg = _sanitize_config_for_save(cfg)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=float("inf"))


def _sanitize_config_for_save(cfg: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(cfg or {})
    database = data.setdefault("database", {})
    if "host" in database:
        database["host"] = "${LMD_DATABASE_HOST:127.0.0.1}"
    if "port" in database:
        database["port"] = "${LMD_DATABASE_PORT:3306}"
    if "name" in database:
        database["name"] = "${LMD_DATABASE_NAME:lmd}"
    if "user" in database:
        database["user"] = "${LMD_DATABASE_USER:lmd}"
    if "password" in database:
        database["password"] = "${LMD_DATABASE_PASSWORD:lmd}"
    if "url" in database:
        database["url"] = "${LMD_DATABASE_URL:}"
    if "timezone" in database:
        database["timezone"] = "${LMD_DATABASE_TIMEZONE:+08:00}"

    security = data.setdefault("security", {})
    if "api_token" in security:
        security["api_token"] = "${LMD_API_TOKEN:}"
    return data


def get_language(cfg: dict[str, Any]) -> str:
    return cfg.get("app", {}).get("language") or "zh"


def database_url_from_config(cfg: dict[str, Any]) -> str:
    """由配置的 database 段构造 SQLAlchemy URL。"""
    db = cfg.get("database", {})
    url = os.environ.get("LMD_DATABASE_URL") or db.get("url") or ""
    if url:
        return url
    user = quote_plus(str(db.get("user", "lmd")))
    password = quote_plus(str(db.get("password", "lmd")))
    host = db.get("host", "127.0.0.1")
    port = db.get("port", 3306)
    name = db.get("name", "lmd")
    charset = db.get("charset", "utf8mb4")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset={charset}"


def database_timezone_from_config(cfg: dict[str, Any]) -> str:
    """Return a validated MySQL session timezone offset."""
    db = cfg.get("database", {})
    value = str(os.environ.get("LMD_DATABASE_TIMEZONE") or db.get("timezone") or "+08:00").strip()
    if not re.fullmatch(r"(?:\+(?:0\d|1[0-3]):[0-5]\d|\+14:00|-(?:0\d|1[0-3]):[0-5]\d)", value):
        raise ValueError(
            "database.timezone must be a MySQL UTC offset between -13:59 and +14:00, "
            "for example +08:00"
        )
    return value


def server_port(cfg: dict[str, Any]) -> int:
    env = os.environ.get("LMD_PORT")
    if env:
        return int(env)
    return int(cfg.get("server", {}).get("port", 5679))


def server_host(cfg: dict[str, Any]) -> str:
    return str(cfg.get("server", {}).get("host", "0.0.0.0"))


def cors_origins(cfg: dict[str, Any]) -> list[str]:
    return list(cfg.get("server", {}).get("cors_origins", []))


def storage_local_path(cfg: dict[str, Any]) -> Path:
    raw = str(cfg.get("storage", {}).get("local_path", "./data/storage"))
    return Path(raw).resolve()


def storage_base_url(cfg: dict[str, Any]) -> str:
    return str(cfg.get("storage", {}).get("base_url", "http://localhost:5679/static"))


def resolve_video_generation_timeout_minutes(cfg: dict[str, Any]) -> int | float:
    """等价 Node config/videoGeneration.js。"""
    if not cfg:
        return 30
    raw = cfg.get("video", {}).get("generation_timeout_minutes")
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return 30
    return n if n > 0 else 30
