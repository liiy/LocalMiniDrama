"""可灵官方 OpenAPI JWT — 契约翻译 backend-node/src/services/klingJwt.js。

Header:  alg=HS256, typ=JWT
Payload: iss=AccessKey, exp, nbf（nbf 默认 now-300s 以容忍本机时钟快于服务端，避免 1003）

Node 用 jsonwebtoken 库；此处用标准库 hmac + base64 直接实现 HS256，
不引入新依赖，且输出与 Node 逐段一致（header 为 {"alg":"HS256","typ":"JWT"}，
payload 为 {"iss","exp","nbf"} 且 noTimestamp，即不含 iat）。
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import time
from hashlib import sha256
from typing import Any

# 客户端时钟快于服务端时，nbf 过「新」会触发 1003；默认放宽到 5 分钟
def _default_nbf_skew_sec() -> int:
    try:
        n = int(os.environ.get("KLING_JWT_NBF_SKEW_SECONDS", "").strip())
    except (TypeError, ValueError):
        return 300
    return n if n >= 0 else 300


DEFAULT_NBF_SKEW_SEC = _default_nbf_skew_sec()

_ZERO_WIDTH = re.compile(r"[\u200B-\u200D\uFEFF]")


def normalize_kling_credential(s) -> str:
    """去掉 BOM、零宽字符与首尾空白（避免复制密钥时签名校验失败）。"""
    t = "" if s is None else str(s)
    if t.startswith("\ufeff"):
        t = t[1:]
    return _ZERO_WIDTH.sub("", t).strip()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def sign_kling_official_jwt(access_key, secret_key, opts: Any = None) -> str:
    """生成 HS256 JWT。opts 可为 dict（ttlSeconds / secretEncoding）或 int（旧式 ttl）。"""
    if isinstance(opts, (int, float)) and not isinstance(opts, bool):
        options = {"ttlSeconds": int(opts)}
    elif isinstance(opts, dict):
        options = dict(opts)
    else:
        options = {}

    ttl_seconds = options.get("ttlSeconds")
    ttl_seconds = 1800 if ttl_seconds is None else int(ttl_seconds)
    secret_encoding = "base64" if options.get("secretEncoding") == "base64" else "utf8"

    ak = normalize_kling_credential(access_key)
    sk = normalize_kling_credential(secret_key)
    if not ak or not sk:
        raise ValueError("AccessKey 与 SecretKey 不能为空")

    if secret_encoding == "base64":
        signing_secret = base64.b64decode(sk)
        if not signing_secret:
            raise ValueError("SecretKey 按 Base64 解码后为空，请检查是否勾选错误或粘贴内容")
    else:
        signing_secret = sk.encode("utf-8")

    now = int(time.time())
    payload = {"iss": ak, "exp": now + ttl_seconds, "nbf": now - DEFAULT_NBF_SKEW_SEC}

    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    p = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("ascii")
    sig = hmac.new(signing_secret, signing_input, sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def unsafe_decode_kling_jwt_payload(token) -> dict | None:
    """仅解码 payload，不校验签名（用于调试，勿记录完整 token）。"""
    try:
        parts = str(token or "").split(".")
        if len(parts) != 3:
            return None
        return json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def jwt_part_lengths(token) -> dict | None:
    """JWT 三段 base64url 长度，用于对照是否截断。"""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return {"invalid": True, "part_count": len(parts)}
    return {
        "header": len(parts[0]),
        "payload": len(parts[1]),
        "signature": len(parts[2]),
    }
