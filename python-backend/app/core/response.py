"""统一响应层：与 Node 版 src/response.js 严格等价。

Node 实现（逐条对齐）：
- send(): 所有响应体追加 timestamp = new Date().toISOString()
- success(data): 200 { success: true, data }
- created(data): 201 { success: true, data }
- successWithPagination: 200 { success:true, data:{ items, pagination:{page, page_size, total, total_pages} } }
  totalPages = Math.ceil(total / pageSize) || 0
- error(status, code, message, details): 仅当 details 为 truthy 时附加
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class TimestampJSONResponse(JSONResponse):
    """所有 JSON 响应自动注入 timestamp（等价 Node response.send）。

    在 render() 阶段注入，避免中间件读取流式响应体的兼容问题。
    """

    def render(self, content):
        if isinstance(content, dict) and "timestamp" not in content:
            content = dict(content)
            content["timestamp"] = timestamp()
        return super().render(content)


def timestamp() -> str:
    dt = datetime.now(timezone.utc)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"


# ---------- 成功响应 ----------

def success(data: Any) -> dict:
    return {"success": True, "data": data}


def created(data: Any) -> dict:
    return {"success": True, "data": data}


def success_with_pagination(items: list, total: int, page: int, page_size: int) -> dict:
    total_pages = math.ceil(total / page_size) if page_size > 0 else 0
    return {
        "success": True,
        "data": {
            "items": items,
            "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": total_pages},
        },
    }


# ---------- 错误响应（抛异常，由全局 handler 渲染） ----------

class HttpError(HTTPException):
    """对应 Node response.error(status, code, message, details)。"""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(status_code=status_code)
        self.code = code
        self.message = message
        self.details = details

    def payload(self) -> dict:
        body: dict[str, Any] = {"success": False, "error": {"code": self.code, "message": self.message}}
        if self.details:  # Node 用 ...(details && { details })，仅 truthy 时附加
            body["error"]["details"] = self.details
        return body


def bad_request(message: str) -> HttpError:
    return HttpError(400, "BAD_REQUEST", message)


def unauthorized(message: str = "未授权访问") -> HttpError:
    return HttpError(401, "UNAUTHORIZED", message)


def not_found(message: str) -> HttpError:
    return HttpError(404, "NOT_FOUND", message)


def forbidden(message: str) -> HttpError:
    return HttpError(403, "FORBIDDEN", message)


def internal_error(message: str | None = None) -> HttpError:
    return HttpError(500, "INTERNAL_ERROR", message or "服务器错误")
