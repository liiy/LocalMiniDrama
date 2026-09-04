"""素材库 CRUD — 契约翻译 backend-node/src/services/assetService.js。

注意：Node 的 update() 白名单包含 description / thumbnail_url / is_favorite，
但 assets 表（migrations/01_init.sql）并无这三列，传入会触发 SQL 错误 → 路由返回 500。
此处保持同样的白名单以维持契约等价（不擅自补列，否则 Python 200 / Node 500 会产生分歧）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one
from app.services.libraryCommon import js_parse_int, to_int_id

# update() 允许改写的字段（与 Node 逐字一致）
UPDATABLE_FIELDS = (
    "name",
    "description",
    "type",
    "category",
    "url",
    "local_path",
    "thumbnail_url",
    "file_size",
    "mime_type",
    "width",
    "height",
    "duration",
    "is_favorite",
)


def _now() -> str:
    return timestamp()


def row_to_item(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "drama_id": r.get("drama_id"),
        "name": r.get("name"),
        "type": r.get("type"),
        "category": r.get("category"),
        "url": r.get("url"),
        "local_path": r.get("local_path"),
        "duration": r.get("duration"),
        "image_gen_id": r.get("image_gen_id"),
        "video_gen_id": r.get("video_gen_id"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_assets(db: Session, query: dict | None = None) -> tuple[list[dict], int, int, int]:
    query = query or {}
    where = "FROM assets WHERE deleted_at IS NULL"
    params: dict[str, Any] = {}
    drama_id = query.get("drama_id")
    if drama_id is not None and str(drama_id).strip() != "":
        where += " AND drama_id = :drama_id"
        params["drama_id"] = js_parse_int(drama_id, 0)
    asset_type = query.get("type")
    if asset_type is not None and str(asset_type).strip() != "":
        where += " AND type = :type"
        params["type"] = str(asset_type)

    total = db.execute(text(f"SELECT COUNT(*) AS total {where}"), params).scalar() or 0
    page = max(1, js_parse_int(query.get("page"), 1))
    page_size = min(100, max(1, js_parse_int(query.get("page_size"), 20)))
    offset = (page - 1) * page_size
    p = dict(params)
    p["_limit"] = page_size
    p["_offset"] = offset
    rows = fetch_all(
        db,
        f"SELECT * {where} ORDER BY created_at DESC, id DESC LIMIT :_limit OFFSET :_offset",
        p,
    )
    return [row_to_item(r) for r in rows], total, page, page_size


def get_by_id(db: Session, asset_id: Any) -> dict | None:
    row = fetch_one(
        db,
        "SELECT * FROM assets WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(asset_id)},
    )
    return row_to_item(row) if row else None


def create(db: Session, log, req: dict) -> dict:
    now = _now()
    res = execute(
        db,
        "INSERT INTO assets "
        "(drama_id, name, type, category, url, local_path, file_size, mime_type, width, height, "
        " duration, image_gen_id, video_gen_id, created_at, updated_at) "
        "VALUES (:drama_id, :name, :type, :category, :url, :local_path, :file_size, :mime_type, "
        "        :width, :height, :duration, :image_gen_id, :video_gen_id, :created_at, :updated_at)",
        {
            "drama_id": req.get("drama_id") if req.get("drama_id") is not None else None,
            "name": req.get("name") or "未命名",
            "type": req.get("type") or "image",
            "category": req.get("category") if req.get("category") is not None else None,
            "url": req.get("url") or "",
            "local_path": req.get("local_path") if req.get("local_path") is not None else None,
            "file_size": req.get("file_size") if req.get("file_size") is not None else None,
            "mime_type": req.get("mime_type") if req.get("mime_type") is not None else None,
            "width": req.get("width") if req.get("width") is not None else None,
            "height": req.get("height") if req.get("height") is not None else None,
            "duration": req.get("duration") if req.get("duration") is not None else None,
            "image_gen_id": req.get("image_gen_id") if req.get("image_gen_id") is not None else None,
            "video_gen_id": req.get("video_gen_id") if req.get("video_gen_id") is not None else None,
            "created_at": now,
            "updated_at": now,
        },
    )
    return get_by_id(db, res.lastrowid)


def update(db: Session, log, asset_id: Any, req: dict) -> dict | None:
    row = fetch_one(
        db,
        "SELECT id FROM assets WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(asset_id)},
    )
    if not row:
        return None

    updates: list[str] = []
    params: dict[str, Any] = {}
    for key in UPDATABLE_FIELDS:
        if key in req:  # Node 用 !== undefined
            updates.append(f"{key} = :{key}")
            params[key] = req[key]

    if not updates:
        return get_by_id(db, asset_id)

    params["updated_at"] = _now()
    params["id"] = to_int_id(asset_id)
    execute(
        db,
        "UPDATE assets SET " + ", ".join(updates) + ", updated_at = :updated_at WHERE id = :id",
        params,
    )
    return get_by_id(db, asset_id)


def delete_by_id(db: Session, log, asset_id: Any) -> bool:
    res = execute(
        db,
        "UPDATE assets SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL",
        {"now": _now(), "id": to_int_id(asset_id)},
    )
    return res.rowcount > 0


def import_from_image(db: Session, log, image_gen_id: Any) -> dict | None:
    img = fetch_one(
        db,
        "SELECT * FROM image_generations WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(image_gen_id)},
    )
    if not img:
        return None
    return create(
        db,
        log,
        {
            "drama_id": img.get("drama_id"),
            "name": f"图片 {image_gen_id}",
            "type": "image",
            "url": img.get("image_url") or "",
            "local_path": img.get("local_path"),
            "image_gen_id": img.get("id"),
        },
    )


def import_from_video(db: Session, log, video_gen_id: Any) -> dict | None:
    vid = fetch_one(
        db,
        "SELECT * FROM video_generations WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(video_gen_id)},
    )
    if not vid:
        return None
    return create(
        db,
        log,
        {
            "drama_id": vid.get("drama_id"),
            "name": f"视频 {video_gen_id}",
            "type": "video",
            "url": vid.get("video_url") or "",
            "local_path": vid.get("local_path"),
            "video_gen_id": vid.get("id"),
        },
    )
