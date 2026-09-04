"""/api/v1/auth/* — 身份认证与安全鉴权路由。

功能：
- GET /auth/status: 查询服务端是否开启安全鉴权及当前 Token 是否有效
- POST /auth/login: 使用 API Token 进行鉴权登录
- POST /auth/logout: 退出登录
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel

from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import bad_request, success, unauthorized
from app.core.security import api_token, auth_enabled, request_token

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("lmd.auth")


class LoginRequest(BaseModel):
    token: str = ""


@router.get("/status")
def get_auth_status(request: Request) -> dict[str, Any]:
    """获取当前服务鉴权状态。"""
    cfg = load_config()
    enabled = auth_enabled(cfg)
    server_token = api_token(cfg)

    if not enabled:
        return success({
            "auth_enabled": False,
            "authenticated": True,
            "has_token_configured": bool(server_token),
        })

    # 服务端开启了鉴权，校验客户端带来的 token
    client_token = request_token(request)
    is_authenticated = bool(server_token and client_token == server_token)

    return success({
        "auth_enabled": True,
        "authenticated": is_authenticated,
        "has_token_configured": bool(server_token),
    })


@router.post("/login")
def login(request: Request, body: LoginRequest = Body(default_factory=LoginRequest)) -> dict[str, Any]:
    """提交 API Token 进行验证登录。"""
    cfg = load_config()
    enabled = auth_enabled(cfg)
    server_token = api_token(cfg)

    if not enabled:
        return success({
            "token": "",
            "message": "服务端未开启安全鉴权，已自动进入系统",
        })

    if not server_token:
        raise bad_request("服务端开启了安全鉴权，但未在配置文件或环境变量中设定 LMD_API_TOKEN，请管理员先配置 Token")

    input_token = body.token.strip()
    if not input_token:
        # 也尝试从请求头提取
        input_token = request_token(request)

    if not input_token:
        raise unauthorized("请输入 API Token / 访问密钥")

    if input_token != server_token:
        log.warning("Login failed: invalid token provided")
        raise unauthorized("API Token 验证失败：密码错误或密钥不匹配")

    log.info("User authenticated successfully via token")
    return success({
        "token": server_token,
        "message": "身份验证通过",
    })


@router.post("/logout")
def logout() -> dict[str, Any]:
    """退出当前登录会话。"""
    return success({"message": "已成功退出登录"})
