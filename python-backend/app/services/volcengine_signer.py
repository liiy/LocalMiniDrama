"""火山引擎 OpenAPI V4 签名 — 契约翻译 @volcengine/openapi/lib/base/sign.js。

签名流程（与 Node 逐条对齐）：
1. X-Date = ISO8601(UTC) 去掉毫秒与分隔符 → `20240101T000000Z`
2. canonicalString = method \n pathname \n queryString \n canonicalHeaders \n \n signedHeaders \n bodyHash
3. stringToSign  = "HMAC-SHA256" \n X-Date \n {date}/{region}/{service}/request \n sha256(canonicalString)
4. signingKey    = HMAC(HMAC(HMAC(HMAC(secretKey, date), region), service), "request")
5. Authorization = HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={...}, Signature={hex}

request 结构（与 Node Signer 一致）：
    { region, method, pathname, params, headers, body }
add_authorization 会就地写入 X-Date / X-Security-Token / X-Content-Sha256 / Authorization。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

ALGORITHM = "HMAC-SHA256"
V4_IDENTIFIER = "request"
DATE_HEADER = "X-Date"
TOKEN_HEADER = "X-Security-Token"
CONTENT_SHA256_HEADER = "X-Content-Sha256"
NOT_SIGN_BODY = "X-NotSignBody"
K_DATE_PREFIX = ""

# content-type 等在 Node 侧被排除出签名头（见 unsignableHeaders）
UNSIGNABLE_HEADERS = (
    "authorization",
    "content-type",
    "content-length",
    "user-agent",
    "presigned-expires",
    "expect",
)


def uri_escape(value: Any) -> str:
    """等价 Node uriEscape：encodeURIComponent 后再转义 ! ' ( ) *。

    Python quote(safe="-_.~") 与 encodeURIComponent 保留集一致（字母数字 + -_.~），
    其余字符均转义为大写十六进制，与 Node 最终产物相同。
    """
    try:
        s = quote(str(value), safe="-_.~")
    except Exception:
        return ""
    # 双保险：确保 ! ' ( ) * 已被转义（Node 通过 escape() + 额外 replace 达成）
    for ch, enc in (("!", "%21"), ("'", "%27"), ("(", "%28"), (")", "%29"), ("*", "%2A")):
        s = s.replace(ch, enc)
    return s


def query_params_to_string(params: dict | None) -> str:
    """等价 Node queryParamsToString（数组值排序后展开为重复 key）。"""
    if not params:
        return ""
    parts: list[str] = []
    for key in params:
        val = params[key]
        if val is None:
            continue
        escaped_key = uri_escape(key)
        if not escaped_key:
            continue
        if isinstance(val, (list, tuple)):
            vals = sorted(uri_escape(v) for v in val)
            parts.append("&".join(f"{escaped_key}={v}" for v in vals))
        else:
            parts.append(f"{escaped_key}={uri_escape(val)}")
    return "&".join(parts)


def _hmac_raw(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sha256_hex(data: Any) -> str:
    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(str(data).encode("utf-8")).hexdigest()


class Signer:
    """火山引擎 V4 签名器。"""

    def __init__(self, request: dict, service_name: str, options: dict | None = None):
        self.request = request
        self.request.setdefault("headers", {})
        self.service_name = service_name
        options = options or {}
        self.body_sha256 = options.get("bodySha256")
        self.request["params"] = self.sort_params(self.request.get("params"))

    # ---------- params ----------

    @staticmethod
    def sort_params(params: dict | None) -> dict:
        if not params:
            return {}
        return {k: params[k] for k in sorted(params) if params[k] is not None}

    # ---------- date ----------

    @staticmethod
    def iso8601(date: datetime | None = None) -> str:
        dt = date or datetime.now(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def get_datetime(self, date: datetime | None = None) -> str:
        dt = date or datetime.now(timezone.utc)
        return dt.strftime("%Y%m%dT%H%M%SZ")

    # ---------- headers ----------

    @staticmethod
    def canonical_header_values(values: str) -> str:
        return re.sub(r"\s+", " ", str(values)).strip()

    @staticmethod
    def is_signable_header(key: str) -> bool:
        return str(key).lower() not in UNSIGNABLE_HEADERS

    def canonical_headers(self) -> str:
        pairs = sorted(self.request["headers"].items(), key=lambda kv: kv[0].lower())
        parts = []
        for key, value in pairs:
            low = str(key).lower()
            if not self.is_signable_header(low):
                continue
            if value is None:
                raise ValueError(f"Header {low} contains invalid value")
            parts.append(f"{low}:{self.canonical_header_values(str(value))}")
        return "\n".join(parts)

    def signed_headers(self) -> str:
        keys = [str(k).lower() for k in self.request["headers"] if self.is_signable_header(str(k).lower())]
        return ";".join(sorted(keys))

    def hex_encoded_body_hash(self) -> str:
        headers = self.request.get("headers") or {}
        if headers.get(CONTENT_SHA256_HEADER):
            return headers[CONTENT_SHA256_HEADER]
        if self.request.get("body"):
            return sha256_hex(query_params_to_string(self.request["body"]))
        return sha256_hex("")

    def add_headers(self, credentials: dict, datetime_str: str) -> None:
        headers = self.request["headers"]
        headers[DATE_HEADER] = datetime_str
        if credentials.get("sessionToken"):
            headers[TOKEN_HEADER] = credentials["sessionToken"]
        if self.request.get("body"):
            body = self.request["body"]
            if not isinstance(body, (str, bytes)):
                body = json.dumps(body, separators=(",", ":"))
            headers[CONTENT_SHA256_HEADER] = self.body_sha256 or sha256_hex(body)

    # ---------- signature ----------

    def create_scope(self, date: str, region: str, service_name: str) -> str:
        return "/".join([date[:8], region, service_name, V4_IDENTIFIER])

    def credential_string(self, datetime_str: str) -> str:
        return self.create_scope(datetime_str[:8], self.request.get("region", ""), self.service_name)

    def get_signing_key(self, credentials: dict, date: str, region: str, service: str) -> bytes:
        k_date = _hmac_raw(f"{K_DATE_PREFIX}{credentials['secretKey']}".encode("utf-8"), date)
        k_region = _hmac_raw(k_date, region)
        k_service = _hmac_raw(k_region, service)
        return _hmac_raw(k_service, V4_IDENTIFIER)

    def canonical_string(self) -> str:
        parts = [
            str(self.request.get("method", "GET")).upper(),
            self.request.get("pathname") or "/",
            query_params_to_string(self.request.get("params")) or "",
            f"{self.canonical_headers()}\n",
            self.signed_headers(),
            self.hex_encoded_body_hash(),
        ]
        return "\n".join(parts)

    def string_to_sign(self, datetime_str: str) -> str:
        return "\n".join(
            [
                ALGORITHM,
                datetime_str,
                self.credential_string(datetime_str),
                sha256_hex(self.canonical_string()),
            ]
        )

    def signature(self, credentials: dict, datetime_str: str) -> str:
        signing_key = self.get_signing_key(
            credentials, datetime_str[:8], self.request.get("region", ""), self.service_name
        )
        return hmac.new(signing_key, self.string_to_sign(datetime_str).encode("utf-8"), hashlib.sha256).hexdigest()

    def authorization(self, credentials: dict, datetime_str: str) -> str:
        return ", ".join(
            [
                f"{ALGORITHM} Credential={credentials['accessKeyId']}/{self.credential_string(datetime_str)}",
                f"SignedHeaders={self.signed_headers()}",
                f"Signature={self.signature(credentials, datetime_str)}",
            ]
        )

    def add_authorization(self, credentials: dict, date: datetime | None = None) -> None:
        datetime_str = self.get_datetime(date)
        self.add_headers(credentials, datetime_str)
        self.request["headers"]["Authorization"] = self.authorization(credentials, datetime_str)
