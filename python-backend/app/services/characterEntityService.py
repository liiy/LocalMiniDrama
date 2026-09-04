"""角色实体（characters 表）操作，等价 characterLibraryService 中的 updateCharacter/deleteCharacter。

注意与 characterLibraryService（character_libraries 素材库）区分：
本模块操作的是 dramas 下的角色实体。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.utils import seedance2AssetGuards as sd2

log = get_logger("lmd.character")


def to_int_id(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def update_character(db: Session, character_id, req: dict) -> tuple[bool, str | None]:
    """等价 Node characterLibraryService.updateCharacter。

    返回 (ok, error)；error 为 'character not found' | 'unauthorized'。
    """
    row = db.execute(
        text(
            "SELECT id, drama_id, local_path, image_url, seedance2_asset FROM characters "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": to_int_id(character_id)},
    ).mappings().first()
    if not row:
        return False, "character not found"

    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :did AND deleted_at IS NULL"), {"did": row["drama_id"]}
    ).first()
    if not drama:
        return False, "unauthorized"

    updates: list[str] = []
    params: dict = {}
    if req.get("name") is not None:
        updates.append("name = :name")
        params["name"] = req["name"]
    if req.get("role") is not None:
        updates.append("role = :role")
        params["role"] = req["role"]
    if req.get("appearance") is not None:
        updates.append("appearance = :appearance")
        params["appearance"] = req["appearance"]
    if req.get("personality") is not None:
        updates.append("personality = :personality")
        params["personality"] = req["personality"]
    if req.get("description") is not None:
        updates.append("description = :description")
        params["description"] = req["description"]
    if req.get("image_url") is not None:
        updates.append("image_url = :image_url")
        params["image_url"] = req["image_url"]
    if req.get("local_path") is not None:
        updates.append("local_path = :local_path")
        params["local_path"] = req["local_path"]
    if req.get("polished_prompt") is not None:
        updates.append("polished_prompt = :polished_prompt")
        params["polished_prompt"] = req["polished_prompt"]
    if req.get("stages") is not None:
        updates.append("stages = :stages")
        import json

        params["stages"] = req["stages"] if isinstance(req["stages"], str) else json.dumps(req["stages"])
    if "negative_prompt" in req:
        updates.append("negative_prompt = :negative_prompt")
        params["negative_prompt"] = req.get("negative_prompt")

    if not updates:
        return True, None

    if req.get("image_url") is not None or req.get("local_path") is not None:
        sd2.mark_stale_on_character_main_image_drift(
            db,
            log,
            dict(row),
            {
                "image_url": req["image_url"] if req.get("image_url") is not None else row["image_url"],
                "local_path": req["local_path"] if req.get("local_path") is not None else row["local_path"],
            },
        )

    params["updated_at"] = timestamp()
    params["cid"] = to_int_id(character_id)
    db.execute(text(f"UPDATE characters SET {', '.join(updates)}, updated_at = :updated_at WHERE id = :cid"), params)
    log.info("Character updated", extra={"character_id": character_id})
    return True, None


def delete_character(db: Session, character_id) -> tuple[bool, str | None]:
    """等价 Node characterLibraryService.deleteCharacter。"""
    row = db.execute(
        text("SELECT id, drama_id FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(character_id)},
    ).mappings().first()
    if not row:
        return False, "character not found"
    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :did AND deleted_at IS NULL"), {"did": row["drama_id"]}
    ).first()
    if not drama:
        return False, "unauthorized"
    db.execute(
        text("UPDATE characters SET deleted_at = :now WHERE id = :id"),
        {"now": timestamp(), "id": to_int_id(character_id)},
    )
    log.info("Character deleted", extra={"id": character_id})
    return True, None
