"""/api/v1/auth/* 认证鉴权相关 HTTP 请求 DTO 模型。"""
from __future__ import annotations

from pydantic import Field
from app.schemas.requests.base import BaseApiRequest


class LoginRequest(BaseApiRequest):
    """用户登录/鉴权请求载荷。"""

    token: str = Field(
        default="",
        description="服务端配置的安全访问令牌 (API Token)。当服务端开启鉴权时必填，空值将导致鉴权失败。",
        examples=["sk-drama-admin-secret-2026"],
    )
