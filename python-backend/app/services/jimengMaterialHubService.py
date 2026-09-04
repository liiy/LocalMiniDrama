"""即梦2角色认证「素材管理」HTTP API — 契约翻译 backend-node/src/services/jimengMaterialHubService.js。

仅翻译 aiConfig 路由所需的最小子集：
- normalize_material_hub_token（存库/环境变量里若含「Bearer 」前缀，hubJson 会再拼 Bearer，需先去重）
- list_assets（GET {base}/api/business/v1/assets?limit=&cursor=）
- hub_business_error_message（网关在拉取图片失败时仍返回 HTTP 200 + { error: "..." }）
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

_TIMEOUT = 30.0

# 与 routes/aiConfig.js listJimeng2MaterialAssets 的缺省网关地址保持一致
DEFAULT_BASE_URL = "https://silvamux.tingyutech.com"

_INVISIBLE_RE = re.compile(r"[\r\n\t\u200b-\u200d\ufeff]")
_BEARER_RE = re.compile(r"^bearer\s+", re.IGNORECASE)


def normalize_material_hub_token(raw: Any) -> str:
    """去掉 Bearer 前缀 / 多余引号 / 不可见空白。"""
    s = str(raw or "").strip()
    s = _BEARER_RE.sub("", s).strip()
    # 兼容误填为 "token" / 'token' 的场景
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    # 去除不可见空白，避免网关把 header 判定为无效
    s = _INVISIBLE_RE.sub("", s).strip()
    # 全角空格等
    s = s.replace("\u00a0", " ").strip()
    return s


def token_fingerprint(tok: Any) -> str:
    """日志/报错用：首尾片段，便于与 curl 测试密钥对照（不含完整密钥）。"""
    s = str(tok or "").strip()
    if not s:
        return ""
    if len(s) <= 12:
        return "(过短)"
    return f"{s[:7]}…{s[-4:]}"


def hub_business_error_message(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    err = data.get("error", data.get("Error"))
    if isinstance(err, str) and err.strip():
        return err.strip()
    if data.get("success") is False:
        return str(data.get("message") or data.get("msg") or data.get("detail") or "网关业务失败")[:2000]
    return None


def hub_json(path: str, ctx: dict, *, method: str | None = None, body: dict | None = None, log=None) -> dict:
    """返回 { ok, data, status } 或 { ok: False, error, status }。"""
    base = str(ctx.get("baseUrl") or "").rstrip("/")
    token = ctx.get("token") or ""
    if not token:
        return {
            "ok": False,
            "error": (
                "未配置即梦2角色认证：请在「AI 配置」中添加类型为「即梦2角色认证」的一条配置，"
                "填写网关 URL 与 Token（或设置环境变量 JIMENG2_CHARACTER_AUTH_*；兼容旧 config / SILVAMUX_*）"
            ),
        }

    url = f"{base}/api/business/v1{path}"
    verb = (method or "GET").upper()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body)

    if log is not None:
        log.info(
            "[JimengMaterialHub] %s %s",
            verb,
            path.split("?")[0],
            extra={"hub_gateway": base, "bearer_token_payload_chars": len(token)},
        )

    try:
        res = httpx.request(verb, url, headers=headers, content=payload, timeout=_TIMEOUT, follow_redirects=False)
    except Exception as e:
        return {"ok": False, "error": f"请求素材网关失败: {e}"}

    text = res.text or ""
    try:
        data = json.loads(text) if text else {}
    except Exception:
        data = {"_raw": text}

    if not (200 <= res.status_code < 300):
        detail = (
            (data.get("detail") if isinstance(data, dict) else None)
            or (data.get("title") if isinstance(data, dict) else None)
            or (data.get("message") if isinstance(data, dict) else None)
            or text
            or res.reason_phrase
            or ""
        )
        detail_str = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        if log is not None:
            log.warning(
                "[JimengMaterialHub] HTTP 错误",
                extra={
                    "path": path,
                    "method": verb,
                    "httpStatus": res.status_code,
                    "hub_gateway": base,
                    "response_preview": detail_str[:2000],
                },
            )
        return {"ok": False, "status": res.status_code, "error": detail_str}

    biz_err = hub_business_error_message(data)
    if biz_err:
        if log is not None:
            log.warning(
                "[JimengMaterialHub] HTTP 200 但业务失败（常见于图片 URL 无法被网关拉取）",
                extra={
                    "path": path,
                    "method": verb,
                    "httpStatus": res.status_code,
                    "hub_gateway": base,
                    "response_preview": biz_err[:2000],
                },
            )
        return {"ok": False, "status": res.status_code, "error": biz_err}

    return {"ok": True, "data": data, "status": res.status_code}


def list_assets(ctx: dict, opts: dict | None = None, log=None) -> dict:
    """列出组织下素材（分页）。"""
    opts = opts or {}
    raw_limit = opts.get("limit")
    try:
        limit_raw = float(raw_limit) if raw_limit is not None else 20.0
    except (TypeError, ValueError):
        limit_raw = 20.0
    if limit_raw != limit_raw:  # NaN
        limit_raw = 20.0
    limit = int(min(100, max(1, limit_raw)))

    from urllib.parse import urlencode

    q: dict[str, str] = {"limit": str(limit)}
    if opts.get("cursor"):
        q["cursor"] = str(opts["cursor"])
    path = f"/assets?{urlencode(q)}"
    return hub_json(path, ctx, method="GET", log=log)


def load_ai_jimeng2_auth_row(db) -> dict | None:
    if not db:
        return None
    try:
        from sqlalchemy import text
        row = db.execute(
            text(
                "SELECT id, name, base_url, api_key FROM ai_service_configs "
                "WHERE deleted_at IS NULL AND service_type = :st AND is_active = 1 "
                "ORDER BY is_default DESC, priority DESC, id ASC LIMIT 1"
            ),
            {"st": "jimeng2_character_auth"},
        ).mappings().first()
        return dict(row) if row else None
    except Exception:
        return None


def build_hub_context(cfg: dict | None = None, db=None, log=None) -> dict:
    import os
    cfg = cfg or {}
    row = load_ai_jimeng2_auth_row(db)
    base_url = str(row.get("base_url") or "").strip() if row else ""
    token = str(row.get("api_key") or "").strip() if row else ""
    poll_max_ms = None
    poll_interval_ms = None

    if not base_url or not token:
        y = cfg.get("jimeng_material_hub") or cfg.get("silvamux_hub") or {}
        if not base_url:
            base_url = str(y.get("base_url") or "").strip()
        if not token:
            token = str(y.get("token") or "").strip()
        if poll_max_ms is None and y.get("poll_max_ms") is not None:
            poll_max_ms = int(y["poll_max_ms"])
        if poll_interval_ms is None and y.get("poll_interval_ms") is not None:
            poll_interval_ms = int(y["poll_interval_ms"])

    base_url_env = (
        os.environ.get("JIMENG2_CHARACTER_AUTH_URL")
        or base_url
        or os.environ.get("JIMENG_MATERIAL_HUB_BASE_URL")
        or os.environ.get("SILVAMUX_HUB_BASE_URL")
        or DEFAULT_BASE_URL
    ).strip().rstrip("/")

    raw_tok_joined = (
        os.environ.get("JIMENG2_CHARACTER_AUTH_TOKEN")
        or token
        or os.environ.get("JIMENG_MATERIAL_HUB_TOKEN")
        or os.environ.get("SILVAMUX_HUB_TOKEN")
        or os.environ.get("HUB_TOKEN")
        or ""
    ).strip()

    tok = normalize_material_hub_token(raw_tok_joined)

    ctx = {
        "baseUrl": base_url_env,
        "token": tok,
        "poll_max_ms": poll_max_ms,
        "poll_interval_ms": poll_interval_ms,
        "tokenFingerprint": token_fingerprint(tok),
    }
    return ctx


def _pick_asset_id(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    val = obj.get("id") or obj.get("asset_id") or obj.get("assetId")
    return str(val).strip() if val is not None else ""


def _looks_like_asset_view(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    aid = _pick_asset_id(obj)
    if not aid:
        return False
    return any(
        obj.get(k) is not None
        for k in ("status", "asset_url", "asset_type", "url", "name")
    )


def unwrap_material_hub_asset_view(payload: Any, depth: int = 0) -> dict | None:
    if depth > 5 or payload is None or not isinstance(payload, (dict, list)):
        return None
    if _looks_like_asset_view(payload):
        aid = _pick_asset_id(payload)
        return {
            **payload,
            "id": aid,
            "asset_url": payload.get("asset_url") or payload.get("assetUrl") or None,
            "status": payload.get("status") or None,
        }
    if isinstance(payload, list):
        for item in payload:
            found = unwrap_material_hub_asset_view(item, depth + 1)
            if found:
                return found
        return None
    for key in ("data", "result", "asset", "item", "record", "body", "payload"):
        if payload.get(key) is not None:
            found = unwrap_material_hub_asset_view(payload[key], depth + 1)
            if found:
                return found
    if isinstance(payload.get("items"), list) and len(payload["items"]) == 1:
        found = unwrap_material_hub_asset_view(payload["items"][0], depth + 1)
        if found:
            return found
    return None


def create_image_asset(ctx: dict, params: dict, log=None) -> dict:
    name = re.sub(r"\s+", "", str(params.get("name") or "c"))[:12] or "c"
    r = hub_json("/assets", ctx, method="POST", body={"url": params.get("url"), "asset_type": "Image", "name": name}, log=log)
    if not r.get("ok"):
        return r
    asset = unwrap_material_hub_asset_view(r.get("data"))
    if asset and asset.get("id"):
        return {"ok": True, "data": asset, "status": r.get("status")}
    return {"ok": False, "status": r.get("status"), "error": "素材库未返回素材 id"}


def get_asset(ctx: dict, asset_id: Any, log=None) -> dict:
    from urllib.parse import quote
    aid = quote(str(asset_id or "").strip())
    if not aid:
        return {"ok": False, "error": "缺少 asset id"}
    r = hub_json(f"/assets/{aid}", ctx, method="GET", log=log)
    if not r.get("ok"):
        return r
    asset = unwrap_material_hub_asset_view(r.get("data"))
    if asset and asset.get("id"):
        return {"ok": True, "data": asset, "status": r.get("status")}
    return {"ok": True, "data": r.get("data"), "status": r.get("status")}


def poll_asset_until_settled(ctx: dict, asset_id: Any, options: dict | None = None) -> dict:
    import time
    opts = options or {}
    max_ms = opts.get("maxMs") or 120000
    interval_ms = opts.get("intervalMs") or 2000
    log = opts.get("log")
    deadline = time.time() + (max_ms / 1000.0)
    last = None
    while time.time() < deadline:
        r = get_asset(ctx, asset_id, log=log)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        last = r.get("data")
        st = (last.get("status") if isinstance(last, dict) else "") or ""
        if st in ("active", "failed"):
            return {"ok": True, "asset": last}
        time.sleep(interval_ms / 1000.0)
    return {"ok": True, "asset": last, "timedOut": True}

