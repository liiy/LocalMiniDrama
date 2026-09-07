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


def load_environment_file() -> None:
    """加载项目 .env，供应用入口与独立验收脚本复用。"""
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


load_environment_file()


def _search_config_path() -> Path | None:
    load_environment_file()
    env = os.environ.get("LMD_CONFIG_PATH")
    if env:
        for p in (
            Path(env),
            Path("python-backend") / env,
            Path(__file__).resolve().parents[2] / env,
        ):
            if p.exists() and p.is_file():
                return p
    for candidate in (
        Path("configs/config.yaml"),
        Path("python-backend/configs/config.yaml"),
        Path("config.yaml"),
        Path("../backend-node/configs/config.yaml"),
        Path(__file__).resolve().parents[2] / "configs/config.yaml",
    ):
        if candidate.exists() and candidate.is_file():
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
    """把环境变量覆盖到配置树，并保持 YAML 原字段的数据类型。"""
    data.setdefault("server", {})
    data.setdefault("database", {})
    data.setdefault("storage", {})
    data.setdefault("security", {})
    data["security"].setdefault("upload", {})
    data.setdefault("app", {})
    data.setdefault("video", {})
    data.setdefault("ai", {})
    data.setdefault("style", {})
    data.setdefault("vendor_lock", {})
    data.setdefault("queue", {})
    data["queue"].setdefault("worker", {})
    data.setdefault("image_proxy", {})
    data.setdefault("memory", {})
    data["memory"].setdefault("vector", {})

    def as_bool(raw: str) -> bool:
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def set_env(path: tuple[str, ...], env_name: str, cast=str, *, allow_empty: bool = False) -> None:
        """按路径写入环境变量；空密钥类变量只有明确允许时才覆盖。"""
        raw = os.environ.get(env_name)
        if raw is None or (not allow_empty and raw == ""):
            return
        target = data
        for key in path[:-1]:
            target = target.setdefault(key, {})
        try:
            target[path[-1]] = cast(raw)
        except (TypeError, ValueError) as err:
            raise ValueError(f"环境变量 {env_name} 的值格式无效") from err

    string_overrides = {
        ("app", "name"): "LMD_APP_NAME",
        ("app", "version"): "LMD_APP_VERSION",
        ("app", "language"): "LMD_LANGUAGE",
        ("server", "host"): "LMD_HOST",
        ("database", "type"): "LMD_DATABASE_TYPE",
        ("database", "host"): "LMD_DATABASE_HOST",
        ("database", "name"): "LMD_DATABASE_NAME",
        ("database", "user"): "LMD_DATABASE_USER",
        ("database", "charset"): "LMD_DATABASE_CHARSET",
        ("database", "timezone"): "LMD_DATABASE_TIMEZONE",
        ("database", "url"): "LMD_DATABASE_URL",
        ("storage", "type"): "LMD_STORAGE_TYPE",
        ("storage", "local_path"): "LMD_STORAGE_LOCAL_PATH",
        ("storage", "base_url"): "LMD_STORAGE_BASE_URL",
        ("ai", "default_text_provider"): "LMD_DEFAULT_TEXT_PROVIDER",
        ("ai", "default_image_provider"): "LMD_DEFAULT_IMAGE_PROVIDER",
        ("ai", "default_video_provider"): "LMD_DEFAULT_VIDEO_PROVIDER",
        ("style", "default_style"): "LMD_DEFAULT_STYLE",
        ("style", "default_role_style"): "LMD_DEFAULT_ROLE_STYLE",
        ("style", "default_scene_style"): "LMD_DEFAULT_SCENE_STYLE",
        ("style", "default_prop_style"): "LMD_DEFAULT_PROP_STYLE",
        ("style", "default_image_ratio"): "LMD_DEFAULT_IMAGE_RATIO",
        ("style", "default_video_ratio"): "LMD_DEFAULT_VIDEO_RATIO",
        ("style", "default_prop_ratio"): "LMD_DEFAULT_PROP_RATIO",
        ("style", "default_image_size"): "LMD_DEFAULT_IMAGE_SIZE",
        ("vendor_lock", "config_file"): "LMD_VENDOR_CONFIG_FILE",
        ("queue", "backend"): "LMD_QUEUE_BACKEND",
        ("queue", "redis_url"): "LMD_REDIS_URL",
        ("security", "master_key"): "LMD_MASTER_KEY",
        ("security", "master_key_file"): "LMD_MASTER_KEY_FILE",
        ("memory", "vector", "backend"): "LMD_VECTOR_MEMORY_BACKEND",
        ("memory", "vector", "collection"): "LMD_VECTOR_MEMORY_COLLECTION",
        ("memory", "vector", "url"): "LMD_QDRANT_URL",
        ("memory", "vector", "distance"): "LMD_VECTOR_DISTANCE",
    }
    for path, env_name in string_overrides.items():
        set_env(path, env_name, allow_empty=path in {("style", "default_style"), ("database", "url"), ("security", "master_key"), ("security", "master_key_file")})

    # 密码和访问令牌允许显式空值，便于开发环境关闭鉴权或使用无密码数据库。
    set_env(("database", "password"), "LMD_DATABASE_PASSWORD", allow_empty=True)
    set_env(("security", "api_token"), "LMD_API_TOKEN", allow_empty=True)
    set_env(("security", "master_key"), "LMD_MASTER_KEY", allow_empty=True)
    set_env(("security", "master_key_file"), "LMD_MASTER_KEY_FILE", allow_empty=True)
    set_env(("memory", "vector", "api_key"), "LMD_QDRANT_API_KEY", allow_empty=True)

    bool_overrides = {
        ("app", "debug"): "LMD_DEBUG",
        ("vendor_lock", "enabled"): "LMD_VENDOR_LOCK_ENABLED",
        ("queue", "worker", "enabled"): "LMD_QUEUE_WORKER_ENABLED",
        ("queue", "worker", "auto_advance"): "LMD_QUEUE_AUTO_ADVANCE",
        ("security", "auth_enabled"): "LMD_AUTH_ENABLED",
        ("image_proxy", "use_for_video"): "LMD_IMAGE_PROXY_USE_FOR_VIDEO",
        ("memory", "vector", "isolate_by_drama"): "LMD_VECTOR_ISOLATE_BY_DRAMA",
    }
    for path, env_name in bool_overrides.items():
        set_env(path, env_name, as_bool)

    int_overrides = {
        ("server", "port"): "LMD_PORT",
        ("server", "read_timeout"): "LMD_SERVER_READ_TIMEOUT",
        ("server", "write_timeout"): "LMD_SERVER_WRITE_TIMEOUT",
        ("database", "port"): "LMD_DATABASE_PORT",
        ("database", "pool_size"): "LMD_DATABASE_POOL_SIZE",
        ("database", "max_overflow"): "LMD_DATABASE_MAX_OVERFLOW",
        ("database", "pool_timeout_seconds"): "LMD_DATABASE_POOL_TIMEOUT_SECONDS",
        ("database", "pool_recycle_seconds"): "LMD_DATABASE_POOL_RECYCLE_SECONDS",
        ("database", "connect_timeout_seconds"): "LMD_DATABASE_CONNECT_TIMEOUT_SECONDS",
        ("queue", "worker", "stale_worker_seconds"): "LMD_QUEUE_STALE_WORKER_SECONDS",
        ("queue", "worker", "stale_job_seconds"): "LMD_QUEUE_STALE_JOB_SECONDS",
        ("security", "rate_limit_per_minute"): "LMD_RATE_LIMIT_PER_MINUTE",
        ("security", "upload", "max_image_bytes"): "LMD_MAX_IMAGE_BYTES",
        ("security", "upload", "max_audio_bytes"): "LMD_MAX_AUDIO_BYTES",
        ("security", "upload", "max_zip_bytes"): "LMD_MAX_ZIP_BYTES",
        ("security", "upload", "max_text_bytes"): "LMD_MAX_TEXT_BYTES",
        ("image_proxy", "expire_hours"): "LMD_IMAGE_PROXY_EXPIRE_HOURS",
        ("image_proxy", "upload_timeout_seconds"): "LMD_IMAGE_PROXY_UPLOAD_TIMEOUT_SECONDS",
        ("image_proxy", "upload_max_attempts"): "LMD_IMAGE_PROXY_UPLOAD_MAX_ATTEMPTS",
        ("memory", "vector", "vector_size"): "LMD_VECTOR_SIZE",
    }
    for path, env_name in int_overrides.items():
        set_env(path, env_name, int)

    float_overrides = {
        ("video", "generation_timeout_minutes"): "LMD_VIDEO_GENERATION_TIMEOUT_MINUTES",
        ("queue", "worker", "poll_interval_seconds"): "LMD_QUEUE_POLL_SECONDS",
        ("queue", "worker", "heartbeat_interval_seconds"): "LMD_QUEUE_HEARTBEAT_SECONDS",
        ("queue", "worker", "recovery_interval_seconds"): "LMD_QUEUE_RECOVERY_SECONDS",
        ("queue", "worker", "waiting_sync_interval_seconds"): "LMD_QUEUE_WAITING_SYNC_SECONDS",
    }
    for path, env_name in float_overrides.items():
        set_env(path, env_name, float)

    if os.environ.get("LMD_CORS_ORIGINS"):
        data["server"]["cors_origins"] = [
            item.strip() for item in os.environ["LMD_CORS_ORIGINS"].split(",") if item.strip()
        ]
    if os.environ.get("LMD_QUEUE_WORKER_QUEUES"):
        data["queue"]["worker"]["queues"] = [
            item.strip() for item in os.environ["LMD_QUEUE_WORKER_QUEUES"].split(",") if item.strip()
        ]


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
    # 连接池参数统一保留环境变量占位，避免管理端保存配置时固化部署环境容量。
    pool_env_defaults = {
        "pool_size": ("LMD_DATABASE_POOL_SIZE", "10"),
        "max_overflow": ("LMD_DATABASE_MAX_OVERFLOW", "20"),
        "pool_timeout_seconds": ("LMD_DATABASE_POOL_TIMEOUT_SECONDS", "30"),
        "pool_recycle_seconds": ("LMD_DATABASE_POOL_RECYCLE_SECONDS", "1200"),
        "connect_timeout_seconds": ("LMD_DATABASE_CONNECT_TIMEOUT_SECONDS", "10"),
    }
    for key, (env_name, default) in pool_env_defaults.items():
        if key in database:
            database[key] = f"${{{env_name}:{default}}}"

    security = data.setdefault("security", {})
    if "api_token" in security:
        security["api_token"] = "${LMD_API_TOKEN:}"
    if "master_key" in security:
        security["master_key"] = "${LMD_MASTER_KEY:}"
    if "master_key_file" in security:
        security["master_key_file"] = "${LMD_MASTER_KEY_FILE:data/.lmd_master_key}"
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


def database_pool_settings_from_config(cfg: dict[str, Any]) -> dict[str, int]:
    """读取并校验数据库连接池参数，防止错误配置耗尽进程或导致永久等待。"""
    db = cfg.get("database", {})

    def positive_int(key: str, default: int, *, minimum: int = 1) -> int:
        try:
            value = int(db.get(key, default))
        except (TypeError, ValueError) as err:
            raise ValueError(f"database.{key} 必须是整数") from err
        if value < minimum:
            raise ValueError(f"database.{key} 不能小于 {minimum}")
        return value

    return {
        "pool_size": positive_int("pool_size", 10),
        "max_overflow": positive_int("max_overflow", 20, minimum=0),
        "pool_timeout_seconds": positive_int("pool_timeout_seconds", 30),
        # 主动回收时间应小于 MySQL wait_timeout，避免取到服务端已关闭的空闲连接。
        "pool_recycle_seconds": positive_int("pool_recycle_seconds", 1200),
        "connect_timeout_seconds": positive_int("connect_timeout_seconds", 10),
    }


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
