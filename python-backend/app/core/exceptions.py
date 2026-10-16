"""Domain exception hierarchy and standard error mapping."""
from __future__ import annotations

from typing import Any

from app.core.response import HttpError


class AppException(Exception):
    """应用领域异常基类。"""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details

    def to_http_error(self) -> HttpError:
        """转换为 FastAPI 标准 HttpError 响应对象。"""
        return HttpError(
            status_code=self.status_code,
            code=self.code,
            message=self.message,
            details=self.details,
        )


class EntityNotFoundException(AppException):
    """资源不存在异常（HTTP 404）。"""

    def __init__(self, message: str = "请求的资源不存在", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=404,
            details=details,
        )


class ValidationException(AppException):
    """输入参数校验异常（HTTP 400）。"""

    def __init__(self, message: str = "参数校验失败", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="BAD_REQUEST",
            status_code=400,
            details=details,
        )


class UnauthorizedException(AppException):
    """未授权访问异常（HTTP 401）。"""

    def __init__(self, message: str = "未授权访问", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
            details=details,
        )


class ForbiddenException(AppException):
    """无权操作异常（HTTP 403）。"""

    def __init__(self, message: str = "无权访问此资源", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
            details=details,
        )


class ConflictException(AppException):
    """资源状态冲突异常（HTTP 409）。"""

    def __init__(self, message: str = "资源状态冲突", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="CONFLICT",
            status_code=409,
            details=details,
        )


class WorkflowException(AppException):
    """工作流执行异常（HTTP 500）。"""

    def __init__(self, message: str = "工作流执行异常", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="WORKFLOW_EXECUTION_ERROR",
            status_code=500,
            details=details,
        )


class AiProviderException(AppException):
    """外部 AI 服务商调用异常（HTTP 502）。"""

    def __init__(self, message: str = "AI 服务商调用失败", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="AI_PROVIDER_ERROR",
            status_code=502,
            details=details,
        )


class StorageException(AppException):
    """持久化存储层异常（HTTP 500）。"""

    def __init__(self, message: str = "存储层执行失败", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="STORAGE_ERROR",
            status_code=500,
            details=details,
        )
