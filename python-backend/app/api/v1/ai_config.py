"""/api/v1/ai-configs/* — 契约精确翻译 backend-node/src/routes/aiConfig.js。

端点（顺序与 Node routes/index.js 一致，静态路径必须注册在 /{id} 之前）：
- GET    /ai-configs                       列表（?service_type= 过滤）
- POST   /ai-configs                       新建（锁定模式禁止 | 201）
- POST   /ai-configs/test                  连接测试
- POST   /ai-configs/jimeng2-list-assets   即梦2素材列表代理
- POST   /ai-configs/model-ark-asset       方舟私有资产库代理
- GET    /ai-configs/vendor-lock           厂商锁定状态
- PUT    /ai-configs/bulk-update-key       批量换 Key（仅锁定模式）
- GET    /ai-configs/{id}                  详情
- PUT    /ai-configs/{id}                  更新（锁定模式仅允许 api_key/default_model/is_default）
- DELETE /ai-configs/{id}                  软删
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import HttpError, bad_request, created, not_found, success
from app.db.session import get_db
from app.services import aiConfigService as svc
from app.services.jimengMaterialHubService import list_assets, normalize_material_hub_token
from app.services.modelArkAssetProxyService import call_model_ark_asset

router = APIRouter(tags=["ai-configs"])
log = get_logger("lmd.aiConfig")

# 内存态配置（等价 Node app.js 启动时 loadConfig 一次并闭包传递）
_CFG: dict[str, Any] = {}


def init_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = cfg


def _parse_id(raw: str) -> int | None:
    """等价 JS parseInt(raw, 10)：'12abc' → 12，'abc'/'' → None（NaN）。"""
    m = re.match(r"^\s*[-+]?\d+", raw or "")
    if not m:
        return None
    return int(m.group(0))


# ---------------- 列表 / 详情 ----------------


@router.get("/ai-configs")
def list_configs(service_type: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return success(svc.mask_config_secrets(svc.list_configs(db, service_type or None)))


@router.post("/ai-configs", status_code=201)
def create_config(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    if svc.get_vendor_lock_status(_CFG)["enabled"]:
        raise bad_request("当前为厂商锁定模式，不允许添加配置")
    body = payload or {}
    if not body.get("service_type") or not body.get("name") or not body.get("provider") or not body.get("base_url"):
        raise bad_request("缺少必填字段: service_type, name, provider, base_url")
    if body.get("api_key") is None:
        raise bad_request("缺少必填字段: api_key")
    try:
        model = body.get("model")
        cfg = svc.create_config(db, log, {**body, "model": model if model is not None else []})
    except Exception as e:
        log.error("Create AI config failed", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", "创建失败") from e
    return created(svc.mask_config_secret(cfg))


# ---------------- 静态路径（必须在 /{id} 之前）----------------


@router.get("/ai-configs/vendor-lock")
def get_vendor_lock() -> dict:
    return success(svc.get_vendor_lock_status(_CFG))


@router.put("/ai-configs/bulk-update-key")
def bulk_update_key(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    if not svc.get_vendor_lock_status(_CFG)["enabled"]:
        raise bad_request("批量换Key仅在厂商锁定模式下可用")
    body = payload or {}
    api_key = body.get("api_key") or ""
    if not str(api_key).strip():
        raise bad_request("请提供新的 API Key")
    try:
        count = svc.bulk_update_api_key(db, log, str(api_key).strip())
    except Exception as e:
        log.error("Bulk update api_key failed", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", "批量换Key失败") from e
    return success({"updated": count, "message": f"已更新 {count} 条配置的 API Key"})


@router.post("/ai-configs/test")
def test_connection(payload: dict = Body(default={})) -> dict:
    body = payload or {}
    if not body.get("base_url") or not body.get("api_key"):
        raise bad_request("缺少 base_url 或 api_key")
    try:
        svc.test_connection(
            {
                "base_url": body.get("base_url"),
                "api_key": body.get("api_key"),
                "model": body.get("model"),
                "provider": body.get("provider"),
                "endpoint": body.get("endpoint"),
                "service_type": body.get("service_type"),
                "settings": body.get("settings"),
            },
            log,
        )
    except Exception as e:
        log.error("AI config test connection failed", extra={"error": str(e)})
        raise bad_request("连接测试失败: " + (str(e) or "未知错误")) from e
    return success({"message": "连接测试成功"})


@router.post("/ai-configs/model-ark-asset")
def model_ark_asset(payload: dict = Body(default={})) -> dict:
    body = payload or {}
    action = str(body.get("action") or "").strip()
    try:
        data = call_model_ark_asset(
            {
                "base_url": body.get("base_url"),
                "api_key": body.get("api_key"),
                "action": action,
                "body": body.get("payload"),
                "path_mode": body.get("path_mode"),
                "http_method": body.get("http_method"),
                "api_version": body.get("api_version"),
                "auth_mode": body.get("auth_mode"),
                "access_key_id": body.get("access_key_id"),
                "secret_access_key": body.get("secret_access_key"),
                "sign_region": body.get("sign_region"),
                "sign_service": body.get("sign_service"),
                "session_token": body.get("session_token"),
                "project_name": body.get("project_name"),
            },
            log,
        )
    except Exception as e:
        log.error("model-ark-asset proxy failed", extra={"error": str(e), "action": action})
        status = getattr(e, "status", None)
        status = status if isinstance(status, int) and 400 <= status < 600 else 400
        raise HttpError(status, "MODEL_ARK_ASSET", str(e) or "请求失败", getattr(e, "payload", None)) from e
    return success(data)


@router.post("/ai-configs/jimeng2-list-assets")
def list_jimeng2_material_assets(payload: dict = Body(default={})) -> dict:
    body = payload or {}
    base_url = re.sub(r"/$", "", str(body.get("base_url") or "").strip())
    api_key = normalize_material_hub_token(body.get("api_key") or "")
    if not base_url or not api_key:
        raise bad_request("请先填写网关 URL 与 Token")
    r = list_assets(
        {"baseUrl": base_url, "token": api_key},
        {"limit": body.get("limit"), "cursor": body.get("cursor")},
        log,
    )
    if not r.get("ok"):
        raise bad_request(str(r.get("error") or "列出素材失败")[:800])
    return success(r.get("data"))


# ---------------- /{id} ----------------


@router.get("/ai-configs/{config_id}")
def get_config(config_id: str, db: Session = Depends(get_db)) -> dict:
    cid = _parse_id(config_id)
    if cid is None:
        raise bad_request("无效的配置ID")
    cfg = svc.get_config(db, cid)
    if not cfg:
        raise not_found("配置不存在")
    return success(svc.mask_config_secret(cfg))


@router.put("/ai-configs/{config_id}")
def update_config(config_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    cid = _parse_id(config_id)
    if cid is None:
        raise bad_request("无效的配置ID")

    body = dict(payload or {})
    # 锁定模式下只允许修改 api_key、default_model、is_default
    if svc.get_vendor_lock_status(_CFG)["enabled"]:
        allowed: dict[str, Any] = {}
        if "api_key" in body:
            allowed["api_key"] = body["api_key"]
        if "default_model" in body:
            allowed["default_model"] = body["default_model"]
        if "is_default" in body:
            allowed["is_default"] = body["is_default"]
        body = allowed

    cfg = svc.update_config(db, log, cid, body)
    if not cfg:
        raise not_found("配置不存在")
    return success(svc.mask_config_secret(cfg))


@router.delete("/ai-configs/{config_id}")
def delete_config(config_id: str, db: Session = Depends(get_db)) -> dict:
    if svc.get_vendor_lock_status(_CFG)["enabled"]:
        raise bad_request("当前为厂商锁定模式，不允许删除配置")
    cid = _parse_id(config_id)
    if cid is None:
        raise bad_request("无效的配置ID")
    ok = svc.delete_config(db, log, cid)
    if not ok:
        raise not_found("配置不存在")
    return success({"message": "删除成功"})
