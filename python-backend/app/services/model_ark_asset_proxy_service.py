"""ModelArk / 方舟「私有资产库」代理 — 契约翻译 backend-node/src/services/modelArkAssetProxyService.js。

- open_api_query：POST {base}?Action=…&Version=…，JSON body。
  控制面接口须使用 auth_mode=volc_sign（Access Key 签名），推理用的 ARK API Key + Bearer 会报 Invalid Authorization。
- asset_subpath / flat：部分中转仍可用 Bearer。
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from app.services.volcengineSigner import Signer

_TIMEOUT = 60.0

ALLOWED_ACTIONS = frozenset(
    {
        "CreateAssetGroup",
        "CreateAsset",
        "ListAssetGroups",
        "ListAssets",
        "GetAsset",
        "GetAssetGroup",
        "UpdateAssetGroup",
        "UpdateAsset",
        "DeleteAsset",
        "DeleteAssetGroup",
    }
)


class ModelArkAssetError(Exception):
    """上游错误：携带 HTTP status 与原始 payload（供路由透传给前端）。"""

    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def normalize_base_url(raw: Any) -> str:
    s = re.sub(r"/$", "", str(raw or "").strip())
    if not s:
        raise ModelArkAssetError("缺少 base_url")
    if not re.match(r"^https?://", s, re.IGNORECASE):
        raise ModelArkAssetError("base_url 须以 http:// 或 https:// 开头")
    return s


def ensure_ark_open_api_base_path(raw: Any) -> str:
    """仅主机、无路径时补全 /api/v3，与控制台 OpenAPI 一致。"""
    s0 = str(raw or "").strip()
    if not s0:
        return s0
    try:
        u = urlparse(re.sub(r"/+$", "", s0))
        if not u.scheme or not u.netloc:
            return s0
    except Exception:
        return s0

    path = re.sub(r"/+$", "", u.path or "/") or "/"
    host = (u.netloc or "").lower()
    looks_ark = (
        re.search(r"(^|\.)ark\.", host) is not None or "byteplus" in host or "volces.com" in host
    )
    if looks_ark and path in ("", "/"):
        u = u._replace(path="/api/v3")
        return re.sub(r"/+$", "", urlunparse(u))
    return re.sub(r"/+$", "", s0)


def normalize_bearer_token(raw: Any) -> str:
    k = str(raw or "").strip()
    if not k:
        return ""
    return re.sub(r"^bearer\s+", "", k, flags=re.IGNORECASE).strip()


def infer_sign_region(host: Any, explicit: Any = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    h = str(host or "").lower()
    if "bytepluses" in h or "byteplus" in h:
        return "ap-southeast-1"
    if "ap-southeast" in h:
        return "ap-southeast-1"
    if "cn-beijing" in h or "volces.com" in h:
        return "cn-beijing"
    return "cn-beijing"


def build_request_url(base: str, path_mode: str, act: str, api_version: Any, project_name: Any) -> str:
    ver = str(api_version or "2024-01-01").strip() or "2024-01-01"
    if path_mode == "flat":
        return f"{base}/{_quote(act)}"
    if path_mode == "asset_subpath":
        return f"{base}/asset/{_quote(act)}"

    try:
        u = urlparse(base)
        if not u.scheme or not u.netloc:
            raise ValueError("bad url")
    except Exception as e:
        raise ModelArkAssetError("base_url 不是合法 URL") from e

    query = dict(_parse_query(u.query))
    query["Action"] = act
    query["Version"] = ver
    pn = str(project_name or "").strip()
    if pn:
        query["ProjectName"] = pn
    return urlunparse(u._replace(query=urlencode(query)))


def _quote(s: str) -> str:
    from urllib.parse import quote

    return quote(str(s), safe="")


def _parse_query(q: str) -> dict:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(q, keep_blank_values=True))


def extract_upstream_message(data: Any, text: str) -> str:
    if isinstance(data, dict):
        meta = data.get("ResponseMetadata")
        if isinstance(meta, dict):
            err = meta.get("Error")
            if isinstance(err, dict) and err.get("Message"):
                return str(err["Message"])
        if data.get("message"):
            return str(data["message"])
        if data.get("Message"):
            return str(data["Message"])
    return f"HTTP 错误: {text[:500] if text else ''}"


def parse_signed_open_api_url(base: str) -> tuple[str, str, str]:
    u = urlparse(base)
    protocol = u.scheme or "https"
    host = u.netloc
    pathname = u.path or "/"
    if not pathname:
        pathname = "/"
    return protocol, host, pathname


def fetch_signed_open_api(
    *,
    base: str,
    action: str,
    api_version: Any,
    body_obj: Any,
    access_key_id: str,
    secret_key: str,
    session_token: Any = None,
    sign_region: Any = None,
    sign_service: Any = None,
    project_name: Any = None,
) -> httpx.Response:
    ver = str(api_version or "2024-01-01").strip() or "2024-01-01"
    protocol, host, pathname = parse_signed_open_api_url(base)
    body_str = json.dumps(body_obj if isinstance(body_obj, dict) else {}, ensure_ascii=False)

    params: dict[str, str] = {"Action": action, "Version": ver}
    pn = str(project_name or "").strip()
    if pn:
        params["ProjectName"] = pn

    request = {
        "region": infer_sign_region(host, sign_region),
        "method": "POST",
        "pathname": pathname,
        "params": params,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": body_str,
    }

    signer = Signer(request, str(sign_service or "ark").strip() or "ark")
    signer.add_authorization(
        {
            "accessKeyId": access_key_id.strip(),
            "secretKey": secret_key.strip(),
            "sessionToken": str(session_token or "").strip(),
        }
    )

    url = f"{protocol}://{host}{pathname}?{urlencode(request['params'])}"
    return httpx.post(url, headers=request["headers"], content=body_str, timeout=_TIMEOUT, follow_redirects=False)


def fetch_bearer(url: str, method: str, token: str, body_obj: Any) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"}
    verb = str(method or "POST").upper()
    payload = None
    if verb not in ("GET", "HEAD"):
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body_obj if isinstance(body_obj, dict) else {}, ensure_ascii=False)
    return httpx.request(verb, url, headers=headers, content=payload, timeout=_TIMEOUT, follow_redirects=False)


def call_model_ark_asset(opts: dict, log=None) -> Any:
    action = opts.get("action")
    if not action or not isinstance(action, str):
        raise ModelArkAssetError("缺少 action")
    act = action.strip()
    if act not in ALLOWED_ACTIONS:
        raise ModelArkAssetError("不支持的 action: " + act)

    base = normalize_base_url(ensure_ark_open_api_base_path(opts.get("base_url")))
    path_mode = str(opts.get("path_mode") or "open_api_query")
    mode_auth = str(opts.get("auth_mode") or "bearer")

    method = str(opts.get("http_method") or "POST").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ModelArkAssetError("不支持的 http_method")

    pn_scope = str(opts.get("project_name") or "").strip()
    body_obj = dict(opts["body"]) if isinstance(opts.get("body"), dict) else {}
    if pn_scope and body_obj.get("ProjectName") is None:
        body_obj["ProjectName"] = pn_scope

    if mode_auth == "volc_sign":
        ak = str(opts.get("access_key_id") or "").strip()
        sk = str(opts.get("secret_access_key") or "").strip()
        if not ak or not sk:
            raise ModelArkAssetError(
                "控制面 OpenAPI 须填写 Access Key ID 与 Secret Access Key（控制台 IAM 密钥，非推理 API Key）"
            )
        if path_mode != "open_api_query":
            raise ModelArkAssetError("AK/SK 签名仅支持与「官方 OpenAPI」路径模式（Query 中带 Action）一起使用")
        res = fetch_signed_open_api(
            base=base,
            action=act,
            api_version=opts.get("api_version"),
            body_obj=body_obj,
            access_key_id=ak,
            secret_key=sk,
            session_token=opts.get("session_token"),
            sign_region=opts.get("sign_region"),
            sign_service=opts.get("sign_service"),
            project_name=pn_scope,
        )
    else:
        token = normalize_bearer_token(opts.get("api_key"))
        if not token:
            raise ModelArkAssetError("缺少 api_key")
        url = build_request_url(base, path_mode, act, opts.get("api_version"), pn_scope)
        res = fetch_bearer(url, method, token, body_obj)

    text = res.text or ""
    try:
        data = json.loads(text) if text else None
    except Exception:
        data = {"_raw": text}

    if not (200 <= res.status_code < 300):
        msg = extract_upstream_message(data, text) or f"HTTP {res.status_code}"
        if log is not None:
            log.warning("modelArkAsset proxy upstream error", extra={"action": act, "status": res.status_code})
        raise ModelArkAssetError(str(msg)[:2000], status=res.status_code, payload=data)

    return data
