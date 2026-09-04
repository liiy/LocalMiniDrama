"""ModelArk 官方资产库配置解析与操作 — 契约翻译 backend-node/src/services/modelArkAssetConfigService.js。"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from sqlalchemy import text

from app.services.modelArkAssetProxyService import call_model_ark_asset


def load_model_ark_asset_row(db) -> dict | None:
    if not db:
        return None
    try:
        row = db.execute(
            text(
                "SELECT id, name, base_url, api_key, settings FROM ai_service_configs "
                "WHERE deleted_at IS NULL AND service_type = :st AND is_active = 1 "
                "ORDER BY is_default DESC, priority DESC, id ASC LIMIT 1"
            ),
            {"st": "model_ark_asset"},
        ).mappings().first()
        return dict(row) if row else None
    except Exception:
        return None


def parse_settings_json(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def build_model_ark_context(db, log=None) -> dict:
    row = load_model_ark_asset_row(db)
    if not row:
        return {"ready": False, "diag": {"db_model_ark_row_found": False}}
    settings = parse_settings_json(row.get("settings"))
    auth_mode = str(settings.get("auth_mode") or "volc_sign")
    base_url = str(row.get("base_url") or "").strip()
    asset_group_id = str(settings.get("asset_group_id") or "").strip()

    call_opts: dict[str, Any] = {
        "base_url": base_url,
        "path_mode": settings.get("path_mode") or "open_api_query",
        "api_version": settings.get("api_version") or "2024-01-01",
        "auth_mode": auth_mode,
        "project_name": settings.get("project_name") or None,
    }

    if auth_mode == "bearer":
        call_opts["api_key"] = str(row.get("api_key") or "").strip()
        if not base_url or not call_opts["api_key"]:
            return {
                "ready": False,
                "row": row,
                "settings": settings,
                "diag": {"db_model_ark_row_found": True, "missing": "base_url 或 api_key"},
            }
    else:
        call_opts["access_key_id"] = str(settings.get("access_key_id") or "").strip()
        call_opts["secret_access_key"] = str(settings.get("secret_access_key") or "").strip()
        if settings.get("sign_region"):
            call_opts["sign_region"] = settings["sign_region"]
        if not base_url or not call_opts["access_key_id"] or not call_opts["secret_access_key"]:
            return {
                "ready": False,
                "row": row,
                "settings": settings,
                "diag": {"db_model_ark_row_found": True, "missing": "base_url 或 AK/SK"},
            }

    if not asset_group_id:
        return {
            "ready": False,
            "row": row,
            "settings": settings,
            "call_opts": call_opts,
            "diag": {"db_model_ark_row_found": True, "missing": "asset_group_id（默认资产组 Id）"},
        }

    diag = {
        "db_model_ark_row_found": True,
        "db_config_id": row.get("id"),
        "db_config_name": row.get("name"),
        "auth_mode": auth_mode,
        "asset_group_id": asset_group_id,
    }
    if log and hasattr(log, "info"):
        log.info("[ModelArkAsset] buildModelArkContext", extra=diag)

    return {
        "ready": True,
        "row": row,
        "settings": settings,
        "call_opts": call_opts,
        "callOpts": call_opts,
        "assetGroupId": asset_group_id,
        "asset_group_id": asset_group_id,
        "billingModel": str(settings.get("billing_model") or "").strip(),
        "diag": diag,
    }


def pick_id(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    val = obj.get("Id") or obj.get("id") or obj.get("AssetId") or obj.get("asset_id")
    return str(val).strip() if val is not None else ""


def looks_like_asset(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    return bool(pick_id(obj))


def normalize_model_ark_asset_status(raw: Any) -> str:
    st = str(raw or "").strip().lower()
    if not st:
        return "processing"
    if st in ("active", "available", "success", "succeeded", "ready", "completed", "complete", "done"):
        return "active"
    if st in ("failed", "error", "fail", "invalid"):
        return "failed"
    return "processing"


def asset_url_for_video(asset: Any) -> str | None:
    if not asset:
        return None
    direct = str((asset.get("asset_url") if isinstance(asset, dict) else "") or "").strip()
    if direct.startswith("asset://"):
        return direct
    if direct.startswith("asset-"):
        return f"asset://{direct}"
    aid = pick_id(asset)
    if not aid:
        return None
    if aid.startswith("asset://"):
        return aid
    if aid.startswith("asset-"):
        return f"asset://{aid}"
    return f"asset://{aid.lstrip('/')}"


def unwrap_model_ark_asset_view(payload: Any, depth: int = 0) -> dict | None:
    if depth > 6 or payload is None or not isinstance(payload, (dict, list)):
        return None
    if looks_like_asset(payload):
        aid = pick_id(payload)
        status_raw = payload.get("Status") or payload.get("status") or payload.get("State") or payload.get("state")
        asset_url = payload.get("AssetUrl") or payload.get("asset_url") or payload.get("Url") or payload.get("url") or None
        return {
            "id": aid,
            "name": payload.get("Name") or payload.get("name") or None,
            "status": normalize_model_ark_asset_status(status_raw),
            "asset_url": asset_url,
            "raw_status": str(status_raw) if status_raw is not None else None,
        }
    if isinstance(payload, list):
        for item in payload:
            found = unwrap_model_ark_asset_view(item, depth + 1)
            if found:
                return found
        return None
    for key in ("Result", "result", "Asset", "asset", "Data", "data", "Item", "item"):
        if payload.get(key) is not None:
            found = unwrap_model_ark_asset_view(payload[key], depth + 1)
            if found:
                return found
    return None


def create_image_asset(ctx: dict, params: dict, log=None) -> dict:
    call_opts = ctx.get("call_opts") or ctx.get("callOpts") or {}
    asset_group_id = ctx.get("asset_group_id") or ctx.get("assetGroupId")
    billing_model = ctx.get("billingModel")
    name = re.sub(r"\s+", "", str(params.get("name") or "role"))[:32] or "role"
    payload = {
        "GroupId": asset_group_id,
        "Name": name,
        "AssetType": "Image",
        "URL": params.get("url"),
    }
    if billing_model:
        payload["model"] = billing_model

    try:
        data = call_model_ark_asset({**call_opts, "action": "CreateAsset", "body": payload}, log)
    except Exception as err:
        return {"ok": False, "error": str(err)[:2000]}

    asset = unwrap_model_ark_asset_view(data)
    if not asset or not asset.get("id"):
        keys = ", ".join(data.keys()) if isinstance(data, dict) else str(type(data))
        return {"ok": False, "error": f"ModelArk 未返回资产 Id（响应字段：{keys or '空'}）"}
    if not asset.get("asset_url"):
        asset["asset_url"] = asset_url_for_video(asset)
    return {"ok": True, "data": asset}


def get_asset(ctx: dict, asset_id: Any, log=None) -> dict:
    aid = str(asset_id or "").strip()
    if not aid:
        return {"ok": False, "error": "缺少 asset id"}
    call_opts = ctx.get("call_opts") or ctx.get("callOpts") or {}
    try:
        data = call_model_ark_asset({**call_opts, "action": "GetAsset", "body": {"Id": aid}}, log)
    except Exception as err:
        return {"ok": False, "error": str(err)[:2000]}
    asset = unwrap_model_ark_asset_view(data)
    if asset and asset.get("id"):
        if not asset.get("asset_url"):
            asset["asset_url"] = asset_url_for_video(asset)
        return {"ok": True, "data": asset}
    return {"ok": True, "data": {"id": aid, "status": "processing", "asset_url": asset_url_for_video({"id": aid})}}


def poll_asset_until_settled(ctx: dict, asset_id: Any, options: dict | None = None) -> dict:
    opts = options or {}
    max_ms = opts.get("maxMs") or 120000
    interval_ms = opts.get("intervalMs") or 2000
    log = opts.get("log")
    deadline = time.time() + (max_ms / 1000.0)
    last = None
    while time.time() < deadline:
        r = get_asset(ctx, asset_id, log)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        last = r.get("data")
        st = str((last.get("status") if isinstance(last, dict) else "") or "").lower()
        if st in ("active", "failed"):
            return {"ok": True, "asset": last}
        time.sleep(interval_ms / 1000.0)
    return {"ok": True, "asset": last, "timedOut": True}
