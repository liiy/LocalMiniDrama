"""道具素材库 CRUD（等价 Node services/propLibraryService.js 的纯 CRUD 部分）。

P2 阶段只翻译库表自身的增删改查；从道具同步入库等流程留到 P4。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.services import propEntityService as prop_svc
from app.services.libraryCommon import (
    find_existing_library_item,
    insert_library_item,
    list_paged,
    normalize_source_id,
    to_int_id,
    update_existing_library_item,
)

log = get_logger("lmd.prop_library")

TABLE = "prop_libraries"
KEYWORD_COLS = ["name", "description", "prompt"]


def resolve_image_url(image_url: str | None, local_path: str | None) -> str | None:
    """等价 Node resolveImageUrl：data: 直接返回；有 local_path 时拼 /static/；否则原样。"""
    if image_url and not str(image_url).startswith("data:"):
        return image_url
    if local_path:
        return f"/static/{local_path}"
    return image_url or None


def prop_library_fields(prop: dict, drama_id, image_url: str | None, now: str) -> dict:
    """等价 Node propLibraryFields：组装写入 prop_libraries 的字段。"""
    return {
        "drama_id": drama_id,
        "name": prop.get("name") or "",
        "description": prop.get("description") or None,
        "prompt": prop.get("prompt") or None,
        "image_url": image_url,
        "local_path": prop.get("local_path") or None,
        "source_type": "prop",
        "source_id": normalize_source_id(prop.get("id")),
        "updated_at": now,
    }


def add_prop_to_library(db: Session, log, prop_id) -> dict:
    """等价 Node addPropToLibrary：把道具同步进本剧素材库（纯 DB 关联，无 AI）。

    返回 { ok, item?, error? }；item 含 duplicated 标记（命中去重复用）。
    """
    prop = prop_svc.get_by_id(db, to_int_id(prop_id))
    if not prop:
        return {"ok": False, "error": "prop not found"}
    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :id AND deleted_at IS NULL"), {"id": prop.get("drama_id")}
    ).mappings().first()
    if not drama:
        return {"ok": False, "error": "unauthorized"}
    if not prop.get("image_url") and not prop.get("local_path"):
        return {"ok": False, "error": "道具还没有形象图片"}
    now = timestamp()
    image_url = resolve_image_url(prop.get("image_url"), prop.get("local_path"))
    fields = prop_library_fields(prop, prop.get("drama_id"), image_url, now)
    existing = find_existing_library_item(
        db, TABLE,
        drama_id=prop.get("drama_id"), source_type="prop", source_id=prop.get("id"),
        image_url=image_url, local_path=prop.get("local_path"),
    )
    if existing:
        update_existing_library_item(db, TABLE, existing["id"], fields)
        log.info("Prop library item reused", extra={"prop_id": prop_id, "library_item_id": existing["id"]})
        return {"ok": True, "item": get_library_item(db, str(existing["id"])), "duplicated": True}
    info = insert_library_item(db, TABLE, {**fields, "created_at": now})
    log.info("Prop added to drama library", extra={"prop_id": prop_id, "library_item_id": info.lastrowid})
    return {"ok": True, "item": get_library_item(db, str(info.lastrowid)), "duplicated": False}


def add_prop_to_material_library(db: Session, log, prop_id) -> dict:
    """等价 Node addPropToMaterialLibrary：把道具同步进全局素材库（drama_id=NULL）。"""
    prop = prop_svc.get_by_id(db, to_int_id(prop_id))
    if not prop:
        return {"ok": False, "error": "prop not found"}
    if not prop.get("image_url") and not prop.get("local_path"):
        return {"ok": False, "error": "道具还没有形象图片"}
    now = timestamp()
    image_url = resolve_image_url(prop.get("image_url"), prop.get("local_path"))
    fields = prop_library_fields(prop, None, image_url, now)
    existing = find_existing_library_item(
        db, TABLE,
        drama_id=None, source_type="prop", source_id=prop.get("id"),
        image_url=image_url, local_path=prop.get("local_path"),
    )
    if existing:
        update_existing_library_item(db, TABLE, existing["id"], fields)
        log.info("Prop material library item reused", extra={"prop_id": prop_id, "library_item_id": existing["id"]})
        return {"ok": True, "item": get_library_item(db, str(existing["id"])), "duplicated": True}
    info = insert_library_item(db, TABLE, {**fields, "created_at": now})
    log.info("Prop added to material library (global)", extra={"prop_id": prop_id, "library_item_id": info.lastrowid})
    return {"ok": True, "item": get_library_item(db, str(info.lastrowid)), "duplicated": False}


def row_to_item(r: dict) -> dict:
    return {
        "id": r["id"],
        "drama_id": r.get("drama_id"),
        "name": r.get("name"),
        "description": r.get("description"),
        "prompt": r.get("prompt"),
        "image_url": r.get("image_url"),
        "local_path": r.get("local_path"),
        "category": r.get("category"),
        "tags": r.get("tags"),
        "source_type": r.get("source_type") or "generated",
        "source_id": r.get("source_id") or None,
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_library_items(db: Session, query: dict) -> tuple[list, int, int, int]:
    return list_paged(db, TABLE, KEYWORD_COLS, query, row_to_item)


def create_library_item(db: Session, req: dict) -> dict:
    now = timestamp()
    source_type = req.get("source_type") or "generated"
    info = insert_library_item(
        db,
        TABLE,
        {
            "drama_id": req.get("drama_id"),
            "name": req.get("name") or "",
            "description": req.get("description"),
            "prompt": req.get("prompt"),
            "image_url": req.get("image_url") or "",
            "local_path": req.get("local_path"),
            "category": req.get("category"),
            "tags": req.get("tags"),
            "source_type": source_type,
            "source_id": normalize_source_id(req.get("source_id")) or None,
            "created_at": now,
            "updated_at": now,
        },
    )
    log.info("Prop library item created", extra={"item_id": info.lastrowid})
    return get_library_item(db, str(info.lastrowid))


def get_library_item(db: Session, item_id) -> dict | None:
    row = db.execute(
        text(f"SELECT * FROM {TABLE} WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(item_id)}
    ).mappings().first()
    return row_to_item(dict(row)) if row else None


def update_library_item(db: Session, item_id, req: dict) -> dict | None:
    row = db.execute(
        text(f"SELECT id FROM {TABLE} WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(item_id)}
    ).first()
    if not row:
        return None

    updates: list[str] = []
    params: dict = {}
    if req.get("name") is not None:
        updates.append("name = :name")
        params["name"] = req["name"]
    if req.get("description") is not None:
        updates.append("description = :description")
        params["description"] = req["description"]
    if req.get("prompt") is not None:
        updates.append("prompt = :prompt")
        params["prompt"] = req["prompt"]
    if req.get("image_url") is not None:
        updates.append("image_url = :image_url")
        params["image_url"] = req["image_url"]
    if req.get("local_path") is not None:
        updates.append("local_path = :local_path")
        params["local_path"] = req["local_path"]
    if req.get("category") is not None:
        updates.append("category = :category")
        params["category"] = req["category"]
    if req.get("tags") is not None:
        updates.append("tags = :tags")
        params["tags"] = req["tags"]
    if req.get("source_type") is not None:
        updates.append("source_type = :source_type")
        params["source_type"] = req["source_type"]
    if req.get("source_id") is not None:
        updates.append("source_id = :source_id")
        params["source_id"] = normalize_source_id(req["source_id"])

    if not updates:
        return get_library_item(db, item_id)

    params["updated_at"] = timestamp()
    params["id"] = to_int_id(item_id)
    db.execute(text(f"UPDATE {TABLE} SET {', '.join(updates)}, updated_at = :updated_at WHERE id = :id"), params)
    log.info("Prop library item updated", extra={"item_id": item_id})
    return get_library_item(db, item_id)


def delete_library_item(db: Session, item_id) -> bool:
    result = db.execute(
        text(f"UPDATE {TABLE} SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL"),
        {"now": timestamp(), "id": to_int_id(item_id)},
    )
    if result.rowcount == 0:
        return False
    log.info("Prop library item deleted", extra={"item_id": item_id})
    return True
