"""/api/v1/scene-model-map — 契约精确翻译 backend-node/src/routes/sceneModelMap.js。

行为要点（与 Node 逐条对齐）：
- GET    /scene-model-map        → SELECT * ORDER BY key
- GET    /scene-model-map/:key   → 404 '场景模型映射不存在'
- POST   /scene-model-map        → 400 '缺少必填字段: key' | 400 '场景键已存在' | 201 row
- PUT    /scene-model-map/:key   → 404 | 200 row（字段用 !== undefined 语义，非 || 语义）
- DELETE /scene-model-map/:key   → 404 | 200 { message: '删除成功' }
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import bad_request, created, not_found, success, timestamp
from app.db.session import execute, fetch_all, fetch_one, get_db

router = APIRouter(tags=["sceneModelMap"])
log = get_logger("lmd.scene_model_map")

_SELECT = "SELECT * FROM ai_model_map"


@router.get("/scene-model-map")
def list_map(db: Session = Depends(get_db)) -> dict:
    return success(fetch_all(db, f"{_SELECT} ORDER BY `key`"))


@router.get("/scene-model-map/{key}")
def get_map(key: str, db: Session = Depends(get_db)) -> dict:
    row = fetch_one(db, f"{_SELECT} WHERE `key` = :key", {"key": key})
    if not row:
        raise not_found("场景模型映射不存在")
    return success(row)


@router.post("/scene-model-map", status_code=201)
def create_map(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    key = payload.get("key")
    if not key:
        raise bad_request("缺少必填字段: key")
    service_type = payload.get("service_type", "text")
    config_id = payload.get("config_id") or None
    model_override = payload.get("model_override") or None
    description = payload.get("description") or ""

    existing = fetch_one(db, "SELECT id FROM ai_model_map WHERE `key` = :key", {"key": key})
    if existing:
        raise bad_request("场景键已存在")

    now = timestamp()
    res = execute(
        db,
        """
        INSERT INTO ai_model_map
            (`key`, service_type, config_id, model_override, description, created_at, updated_at)
        VALUES (:key, :service_type, :config_id, :model_override, :description, :created_at, :updated_at)
        """,
        {
            "key": key,
            "service_type": service_type,
            "config_id": config_id,
            "model_override": model_override,
            "description": description,
            "created_at": now,
            "updated_at": now,
        },
    )
    row = fetch_one(db, f"{_SELECT} WHERE id = :id", {"id": res.lastrowid})
    return created(row)


@router.put("/scene-model-map/{key}")
def update_map(key: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    existing = fetch_one(db, "SELECT id FROM ai_model_map WHERE `key` = :key", {"key": key})
    if not existing:
        raise not_found("场景模型映射不存在")

    service_type = payload.get("service_type") or "text"
    config_id = payload["config_id"] if "config_id" in payload else None
    model_override = payload["model_override"] if "model_override" in payload else None
    description = payload["description"] if "description" in payload else ""

    execute(
        db,
        """
        UPDATE ai_model_map SET service_type = :service_type, config_id = :config_id,
            model_override = :model_override, description = :description, updated_at = :updated_at
        WHERE `key` = :key
        """,
        {
            "service_type": service_type,
            "config_id": config_id,
            "model_override": model_override,
            "description": description,
            "updated_at": timestamp(),
            "key": key,
        },
    )
    return success(fetch_one(db, f"{_SELECT} WHERE `key` = :key", {"key": key}))


@router.delete("/scene-model-map/{key}")
def delete_map(key: str, db: Session = Depends(get_db)) -> dict:
    existing = fetch_one(db, "SELECT id FROM ai_model_map WHERE `key` = :key", {"key": key})
    if not existing:
        raise not_found("场景模型映射不存在")
    execute(db, "DELETE FROM ai_model_map WHERE `key` = :key", {"key": key})
    return success({"message": "删除成功"})
