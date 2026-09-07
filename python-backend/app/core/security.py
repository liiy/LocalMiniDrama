from __future__ import annotations

import os
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from typing import Any

from fastapi import Request
from starlette.responses import Response

from app.core.response import TimestampJSONResponse

_REQUEST_WINDOWS: dict[str, deque[float]] = defaultdict(deque)
_REQUEST_WINDOWS_LOCK = Lock()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def request_id_from_headers(request: Request) -> str:
    raw = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
    return raw.strip()[:128] if raw and raw.strip() else uuid.uuid4().hex


def auth_enabled(cfg: dict[str, Any]) -> bool:
    security_cfg = cfg.get("security") or {}
    val = security_cfg.get("auth_enabled", False)
    if isinstance(val, str):
        val = val.strip().lower() in {"1", "true", "yes", "on"}
    return env_bool("LMD_AUTH_ENABLED", bool(val))


def api_token(cfg: dict[str, Any]) -> str:
    security_cfg = cfg.get("security") or {}
    return str(os.environ.get("LMD_API_TOKEN") or security_cfg.get("api_token") or "").strip()


def rate_limit_per_minute(cfg: dict[str, Any]) -> int:
    security_cfg = cfg.get("security") or {}
    configured = security_cfg.get("rate_limit_per_minute", 0)
    try:
        fallback = int(configured or 0)
    except (TypeError, ValueError):
        fallback = 0
    return env_int("LMD_RATE_LIMIT_PER_MINUTE", fallback)


def is_public_path(path: str) -> bool:
    if path in {"/", "/health", "/openapi.json", "/favicon.ico"}:
        return True
    return path.startswith(("/docs", "/static", "/assets", "/api/v1/auth"))


def request_token(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token_header = (request.headers.get("x-lmd-token") or "").strip()
    if token_header:
        return token_header
    # 支持 URL Query 参数携带 token（用于 EventSource / 文件下载 / 媒体预览）
    token_query = (
        request.query_params.get("token")
        or request.query_params.get("api_token")
        or request.query_params.get("x-lmd-token")
        or ""
    )
    return token_query.strip()


def unauthorized_response(
    message: str = "鉴权失败：服务端已开启安全验证，请在请求中提供有效的 API Token (Authorization: Bearer <token> 或 x-lmd-token)",
) -> TimestampJSONResponse:
    return TimestampJSONResponse(
        status_code=401,
        content={"success": False, "error": {"code": "UNAUTHORIZED", "message": message}},
    )


def rate_limited_response() -> TimestampJSONResponse:
    return TimestampJSONResponse(
        status_code=429,
        content={"success": False, "error": {"code": "RATE_LIMITED", "message": "Too many requests"}},
    )


def check_rate_limit(request: Request, limit_per_minute: int) -> bool:
    if limit_per_minute <= 0 or not request.url.path.startswith("/api"):
        return True

    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.url.path}"
    now = time.monotonic()
    window_start = now - 60.0
    with _REQUEST_WINDOWS_LOCK:
        bucket = _REQUEST_WINDOWS[key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= limit_per_minute:
            return False
        bucket.append(now)
    return True


def build_security_middleware(initial_cfg: dict[str, Any] | None = None) -> Callable:
    from app.core.config import load_config

    async def security_middleware(request: Request, call_next) -> Response:
        cfg = load_config() if initial_cfg is None else (load_config() or initial_cfg)
        limit = rate_limit_per_minute(cfg)
        if not check_rate_limit(request, limit):
            return rate_limited_response()

        path = request.url.path
        enabled = auth_enabled(cfg)
        token = api_token(cfg)

        if enabled and path.startswith("/api") and request.method != "OPTIONS" and not is_public_path(path):
            if not token:
                return unauthorized_response(
                    message="服务端已开启安全鉴权，但尚未配置有效 API Token (LMD_API_TOKEN)，请在配置文件中设置后重试"
                )
            if request_token(request) != token:
                return unauthorized_response()

        return await call_next(request)

    return security_middleware
