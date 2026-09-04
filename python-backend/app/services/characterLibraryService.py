"""角色素材库 CRUD 与 AI 生成 / 认证（等价 Node services/characterLibraryService.js）。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import urlparse
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.services import aiClient
from app.services import characterEntityService as char_svc
from app.services import imageClient
from app.services import jimengMaterialHubService
from app.services import modelArkAssetConfigService
from app.services import promptI18n
from app.services import uploadService
from app.services import workerService
from app.utils import dramaStyleMerge
from app.utils import seedance2AssetGuards as sd2
from app.services.libraryCommon import (
    find_existing_library_item,
    insert_library_item,
    list_paged,
    normalize_source_id,
    to_int_id,
    update_existing_library_item,
)

log = get_logger("lmd.character_library")

TABLE = "character_libraries"
KEYWORD_COLS = ["name", "description"]


def resolve_image_url(image_url: str | None, local_path: str | None) -> str | None:
    if image_url and not str(image_url).startswith("data:"):
        return image_url
    if local_path:
        return f"/static/{local_path}"
    return image_url or None


def character_library_fields(char_row: dict, drama_id, category, image_url: str | None, now: str) -> dict:
    return {
        "drama_id": drama_id,
        "name": char_row.get("name"),
        "category": category,
        "image_url": image_url,
        "local_path": char_row.get("local_path") or None,
        "description": char_row.get("description") or None,
        "source_type": "character",
        "source_id": normalize_source_id(char_row.get("id")),
        "updated_at": now,
    }


def apply_library_item_to_character(db: Session, log, character_id, library_item_id) -> dict:
    """等价 Node applyLibraryItemToCharacter：把角色库项应用到角色主图（纯 DB）。"""
    item = get_library_item(db, library_item_id)
    if not item:
        return {"ok": False, "error": "library item not found"}
    char_row = db.execute(
        text("SELECT id, drama_id, local_path, image_url, seedance2_asset FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(character_id)},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :did AND deleted_at IS NULL"), {"did": char_row["drama_id"]}
    ).first()
    if not drama:
        return {"ok": False, "error": "unauthorized"}
    sd2.mark_stale_on_character_main_image_drift(
        db, log, dict(char_row), {"image_url": item.get("image_url") or None, "local_path": item.get("local_path") or None}
    )
    now = timestamp()
    db.execute(
        text("UPDATE characters SET image_url = :iu, local_path = :lp, updated_at = :now WHERE id = :id"),
        {"iu": item.get("image_url") or None, "lp": item.get("local_path") or None, "now": now, "id": to_int_id(character_id)},
    )
    log.info("Library item applied to character", extra={"character_id": character_id, "library_item_id": library_item_id})
    return {"ok": True}


def upload_character_image(db: Session, log, character_id, image_url: str | None, opts: dict | None = None) -> dict:
    """等价 Node uploadCharacterImage：更新角色主图 url（纯 DB）。"""
    opts = opts or {}
    char_row = db.execute(
        text("SELECT id, drama_id, local_path, image_url, seedance2_asset FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(character_id)},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :did AND deleted_at IS NULL"), {"did": char_row["drama_id"]}
    ).first()
    if not drama:
        return {"ok": False, "error": "unauthorized"}
    if not opts.get("skipStaleMark"):
        sd2.mark_stale_on_character_main_image_drift(db, log, dict(char_row), {"image_url": image_url})
    now = timestamp()
    db.execute(
        text("UPDATE characters SET image_url = :iu, updated_at = :now WHERE id = :id"),
        {"iu": image_url or None, "now": now, "id": to_int_id(character_id)},
    )
    log.info("Character image uploaded", extra={"character_id": character_id})
    return {"ok": True}


def add_character_to_library(db: Session, log, character_id, category) -> dict:
    """等价 Node addCharacterToLibrary：加入本剧角色库（纯 DB 关联，去重）。"""
    char_row = db.execute(
        text("SELECT * FROM characters WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(character_id)}
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :did AND deleted_at IS NULL"), {"did": char_row["drama_id"]}
    ).first()
    if not drama:
        return {"ok": False, "error": "unauthorized"}
    if not char_row.get("image_url") and not char_row.get("local_path"):
        return {"ok": False, "error": "角色还没有形象图片"}
    now = timestamp()
    image_url = resolve_image_url(char_row.get("image_url"), char_row.get("local_path"))
    fields = character_library_fields(char_row, char_row["drama_id"], category, image_url, now)
    existing = find_existing_library_item(
        db, TABLE, drama_id=char_row["drama_id"], source_type="character", source_id=char_row.get("id"),
        image_url=image_url, local_path=char_row.get("local_path"),
    )
    if existing:
        update_existing_library_item(db, TABLE, existing["id"], fields)
        log.info("Character library item reused", extra={"character_id": character_id, "library_item_id": existing["id"]})
        return {"ok": True, "item": get_library_item(db, str(existing["id"])), "duplicated": True}
    info = insert_library_item(db, TABLE, {**fields, "created_at": now})
    log.info("Character added to drama library", extra={"character_id": character_id, "library_item_id": info.lastrowid})
    return {"ok": True, "item": get_library_item(db, str(info.lastrowid)), "duplicated": False}


def add_character_to_material_library(db: Session, log, character_id) -> dict:
    """等价 Node addCharacterToMaterialLibrary：加入全局素材库（drama_id=NULL）。"""
    char_row = db.execute(
        text("SELECT * FROM characters WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(character_id)}
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    if not char_row.get("image_url") and not char_row.get("local_path"):
        return {"ok": False, "error": "角色还没有形象图片"}
    now = timestamp()
    image_url = resolve_image_url(char_row.get("image_url"), char_row.get("local_path"))
    fields = character_library_fields(char_row, None, None, image_url, now)
    existing = find_existing_library_item(
        db, TABLE, drama_id=None, source_type="character", source_id=char_row.get("id"),
        image_url=image_url, local_path=char_row.get("local_path"),
    )
    if existing:
        update_existing_library_item(db, TABLE, existing["id"], fields)
        log.info("Character material library item reused", extra={"character_id": character_id, "library_item_id": existing["id"]})
        return {"ok": True, "item": get_library_item(db, str(existing["id"])), "duplicated": True}
    info = insert_library_item(db, TABLE, {**fields, "created_at": now})
    log.info("Character added to material library (global)", extra={"character_id": character_id, "library_item_id": info.lastrowid})
    return {"ok": True, "item": get_library_item(db, str(info.lastrowid)), "duplicated": False}


def row_to_item(r: dict) -> dict:
    return {
        "id": r["id"],
        "drama_id": r.get("drama_id"),
        "name": r.get("name"),
        "category": r.get("category"),
        "image_url": r.get("image_url"),
        "local_path": r.get("local_path"),
        "description": r.get("description"),
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
            "category": req.get("category"),
            "image_url": req.get("image_url") or "",
            "local_path": req.get("local_path"),
            "description": req.get("description"),
            "tags": req.get("tags"),
            "source_type": source_type,
            "source_id": normalize_source_id(req.get("source_id")) or None,
            "created_at": now,
            "updated_at": now,
        },
    )
    log.info("Library item created", extra={"item_id": info.lastrowid})
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
    if req.get("category") is not None:
        updates.append("category = :category")
        params["category"] = req["category"]
    if req.get("description") is not None:
        updates.append("description = :description")
        params["description"] = req["description"]
    if req.get("tags") is not None:
        updates.append("tags = :tags")
        params["tags"] = req["tags"]
    if req.get("image_url") is not None:
        updates.append("image_url = :image_url")
        params["image_url"] = req["image_url"]
    if req.get("local_path") is not None:
        updates.append("local_path = :local_path")
        params["local_path"] = req["local_path"]
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
    log.info("Library item updated", extra={"item_id": item_id})
    return get_library_item(db, item_id)


def delete_library_item(db: Session, item_id) -> bool:
    result = db.execute(
        text(f"UPDATE {TABLE} SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL"),
        {"now": timestamp(), "id": to_int_id(item_id)},
    )
    if result.rowcount == 0:
        return False
    log.info("Library item deleted", extra={"item_id": item_id})
    return True


# ======================================================================
# 角色实体更新 / 删除与 AI 生成 / 认证（等价 Node characterLibraryService.js）
# ======================================================================

def update_character(db: Session, log, character_id, req: dict) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, drama_id, local_path, image_url, seedance2_asset FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": cid},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :did AND deleted_at IS NULL"), {"did": char_row["drama_id"]}
    ).first()
    if not drama:
        return {"ok": False, "error": "unauthorized"}

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
        params["stages"] = req["stages"] if isinstance(req["stages"], str) else json.dumps(req["stages"])
    if "negative_prompt" in req:
        updates.append("negative_prompt = :negative_prompt")
        params["negative_prompt"] = req.get("negative_prompt")

    if not updates:
        return {"ok": True}

    if req.get("image_url") is not None or req.get("local_path") is not None:
        sd2.mark_stale_on_character_main_image_drift(
            db,
            log,
            dict(char_row),
            {
                "image_url": req["image_url"] if req.get("image_url") is not None else char_row["image_url"],
                "local_path": req["local_path"] if req.get("local_path") is not None else char_row["local_path"],
            },
        )

    params["updated_at"] = timestamp()
    params["cid"] = cid
    db.execute(text(f"UPDATE characters SET {', '.join(updates)}, updated_at = :updated_at WHERE id = :cid"), params)
    log.info("Character updated", extra={"character_id": character_id})
    return {"ok": True}


def delete_character(db: Session, log, character_id) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, drama_id FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": cid},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    drama = db.execute(
        text("SELECT id FROM dramas WHERE id = :did AND deleted_at IS NULL"), {"did": char_row["drama_id"]}
    ).first()
    if not drama:
        return {"ok": False, "error": "unauthorized"}
    now = timestamp()
    db.execute(text("UPDATE characters SET deleted_at = :now WHERE id = :id"), {"now": now, "id": cid})
    log.info("Character deleted", extra={"id": character_id})
    return {"ok": True}


def append_prompt(current: str, add: str) -> str:
    if not add or not str(add).strip():
        return current or ""
    curr = str(current or "").strip()
    ad = str(add).strip()
    if not curr:
        return ad
    if ad.lower() in curr.lower():
        return curr
    return f"{curr}, {ad}"


def generate_character_image(db: Session, log, cfg: dict, character_id, model_name=None, style=None) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, drama_id, name, appearance, description, negative_prompt FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": cid},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    drama = db.execute(
        text("SELECT id, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
        {"id": char_row["drama_id"]},
    ).mappings().first()
    if not drama:
        return {"ok": False, "error": "unauthorized"}

    from app.services.imageService import aspect_ratio_to_size

    effective_cfg = {**cfg, "style": {**(cfg.get("style") or {})}}
    try:
        raw_meta = drama.get("metadata")
        meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
        if meta and isinstance(meta, dict) and meta.get("aspect_ratio"):
            effective_cfg["style"]["default_image_ratio"] = meta["aspect_ratio"]
    except Exception:
        pass
    effective_cfg = dramaStyleMerge.merge_cfg_style_with_drama(effective_cfg, dict(drama))
    effective_cfg = dramaStyleMerge.apply_style_override_to_cfg(effective_cfg, style)

    prompt = ""
    if char_row.get("appearance") and str(char_row["appearance"]).strip():
        prompt = str(char_row["appearance"])
    elif char_row.get("description") and str(char_row["description"]).strip():
        prompt = str(char_row["description"])
    else:
        prompt = char_row.get("name") or ""

    style_cfg = effective_cfg.get("style", {}) if isinstance(effective_cfg, dict) else {}
    style_for_image = (style_cfg.get("default_style_en") or style_cfg.get("default_style") or "").strip()
    prompt = append_prompt(prompt, style_for_image)
    if not (style and str(style).strip()):
        prompt = append_prompt(prompt, style_cfg.get("default_role_style") or "")

    ratio_text = (
        str(style_cfg.get("default_role_ratio"))
        if style_cfg.get("default_role_ratio")
        else (f"image ratio: {style_cfg['default_image_ratio']}" if style_cfg.get("default_image_ratio") else "")
    )
    prompt = append_prompt(prompt, ratio_text)

    image_size = None
    try:
        raw_meta = drama.get("metadata")
        meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
        if meta and isinstance(meta, dict) and meta.get("aspect_ratio"):
            image_size = aspect_ratio_to_size(meta["aspect_ratio"])
    except Exception:
        pass
    image_size = image_size or "1920x1920"

    user_neg = imageClient.resolve_asset_user_negative_for_api(model_name, char_row.get("negative_prompt"))
    image_gen = imageClient.create_and_generate_image(db, log, {
        "drama_id": char_row["drama_id"],
        "character_id": char_row["id"],
        "prompt": prompt,
        "model": model_name or None,
        "size": image_size,
        "quality": "standard",
        "provider": "openai",
        "user_negative_prompt": user_neg or None,
    })
    return {"ok": True, "image_generation": image_gen}


def detect_gender_from_description(text_val: str | None) -> str | None:
    if not text_val:
        return None
    t = str(text_val)
    if re.search(r"男性|男生|男孩|男人|帅哥|先生", t):
        return "MALE"
    if re.search(r"女性|女生|女孩|女人|美女|小姐|女士", t):
        return "FEMALE"
    if re.search(r"哥哥|大哥|二哥|老哥|小哥|兄长|兄弟|弟弟|老弟|小弟|爸爸|父亲|老爸|爷爷|老爷|叔叔|伯伯|舅舅", t):
        return "MALE"
    if re.search(r"姐姐|大姐|二姐|老姐|小姐姐|妹妹|小妹|大妹|妈妈|母亲|老妈|奶奶|姑姑|婶婶|阿姨", t):
        return "FEMALE"
    if re.search(r"男主|男二|男三|男配|男反|男一号", t):
        return "MALE"
    if re.search(r"女主|女二|女三|女配|女反|女一号", t):
        return "FEMALE"
    if re.search(r"小明|小刚|小强|小磊|小军|小勇|小鹏|小龙|小伟|小超|小豪|小杰|小浩|小宇|小轩|小博|小远|小志|小峰|小涛|大壮|阿强|阿勇|阿明|阿刚|阿豪|老刚|老强", t):
        return "MALE"
    if re.search(r"小美|小红|小花|小丽|小燕|小芳|小英|小敏|小静|小娟|小慧|小梅|小香|小秀|小玲|小萍|小云|小雪|小莹|小晴|阿美|阿花|阿丽|阿燕|阿芳|阿英|阿梅", t):
        return "FEMALE"
    if re.search(r"[（(【「\s：:]哥[）)】」\s,，。！!]|(?:^哥[,，。])|(?:[他]哥\b)", t):
        return "MALE"
    if re.search(r"\b(male|man|boy|gentleman|he|his)\b", t, re.IGNORECASE):
        return "MALE"
    if re.search(r"\b(female|woman|girl|lady|she|her)\b", t, re.IGNORECASE):
        return "FEMALE"
    return None


def build_four_view_image_prompt(four_view_description: str, style_en: str | None = None, style_zh: str | None = None) -> str:
    image_layout_instruction = promptI18n.get_role_generate_image_prompt()
    zh = (style_zh or "").strip()
    en = (style_en or "").strip()

    style_lines = []
    if zh:
        style_lines.append(f"【画风·最高优先级】四格统一：{zh}")
    if en and en != zh:
        style_lines.append(f"MANDATORY ART STYLE (all 4 panels): {en}.")
    elif en and not zh:
        style_lines.append(f"MANDATORY ART STYLE (all 4 panels): {en}.")
    style_header = f"{chr(10).join(style_lines)}\n\n" if style_lines else ""

    gender = detect_gender_from_description(four_view_description)
    gender_enforcement = (
        "GENDER: male only — masculine build and facial features; do not feminize."
        if gender == "MALE"
        else "GENDER: female only — feminine build and facial features; do not masculinize."
        if gender == "FEMALE"
        else ""
    )

    tail_parts = []
    if gender_enforcement:
        tail_parts.append(gender_enforcement)
    if zh or en:
        tail_parts.append(f"Reiterate: same art style as above ({en or zh}).")
    tail = f"\n\n---\n\n{' '.join(tail_parts)}" if tail_parts else ""

    return f"{style_header}{image_layout_instruction}\n\n---\n\n{four_view_description}{tail}"


def generate_character_prompt_only(db: Session, log, cfg: dict, character_id, model_name=None, style=None) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, drama_id, name, appearance, description FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": cid},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}

    drama_full = db.execute(
        text("SELECT id, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
        {"id": char_row["drama_id"]},
    ).mappings().first()
    merged_cfg = dramaStyleMerge.merge_cfg_style_with_drama(cfg, dict(drama_full) if drama_full else {})
    merged_cfg = dramaStyleMerge.apply_style_override_to_cfg(merged_cfg, style)

    appearance_text = ""
    if char_row.get("appearance") and str(char_row["appearance"]).strip():
        appearance_text = str(char_row["appearance"]).strip()
    elif char_row.get("description") and str(char_row["description"]).strip():
        appearance_text = str(char_row["description"]).strip()
    else:
        appearance_text = char_row.get("name") or ""

    system_prompt = promptI18n.get_role_polish_prompt(merged_cfg)
    user_prompt = f"角色名称：{char_row.get('name')}\n\n角色描述：\n{appearance_text}"
    log.info("[四视图提示词] 生成提示词", extra={"systemPrompt": system_prompt, "userPrompt": user_prompt})
    log.info("[四视图提示词] 开始生成", extra={"character_id": character_id, "char_name": char_row.get("name")})

    try:
        four_view_description = aiClient.generate_text(
            db, log, "text", user_prompt, system_prompt,
            options={"scene_key": "role_image_polish", "model": model_name or None, "max_tokens": 4000},
        )
    except Exception as err:
        log.error("[四视图提示词] 文本AI失败，降级为外貌描述", extra={"error": str(err)})
        four_view_description = appearance_text

    style_cfg = merged_cfg.get("style", {}) if isinstance(merged_cfg, dict) else {}
    style_en = (style_cfg.get("default_style_en") or style_cfg.get("default_style") or "").strip()
    style_zh = (style_cfg.get("default_style_zh") or "").strip()
    log.info("[四视图提示词] 构建最终提示词", extra={"fourViewDescription": four_view_description, "styleEn": style_en, "styleZh": style_zh})
    polished_prompt = build_four_view_image_prompt(four_view_description, style_en, style_zh)

    now = timestamp()
    db.execute(
        text("UPDATE characters SET polished_prompt = :p, updated_at = :now WHERE id = :id"),
        {"p": polished_prompt, "now": now, "id": cid},
    )
    db.commit()

    log.info("[四视图提示词] 生成并保存完成", extra={"character_id": character_id, "length": len(polished_prompt)})
    return {"ok": True, "polished_prompt": polished_prompt}


def generate_character_four_view_image(db: Session, log, cfg: dict, character_id, model_name=None, style=None) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, drama_id, name, appearance, description, polished_prompt, negative_prompt FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": cid},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}

    drama_full = db.execute(
        text("SELECT id, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
        {"id": char_row["drama_id"]},
    ).mappings().first()
    if not drama_full:
        return {"ok": False, "error": "unauthorized"}

    merged_cfg = dramaStyleMerge.merge_cfg_style_with_drama(cfg, dict(drama_full))
    merged_cfg = dramaStyleMerge.apply_style_override_to_cfg(merged_cfg, style)

    if char_row.get("polished_prompt") and str(char_row["polished_prompt"]).strip():
        image_prompt = str(char_row["polished_prompt"]).strip()
        log.info("[四视图] 使用已保存的 polished_prompt，跳过文字AI", extra={"character_id": character_id})
    else:
        appearance_text = ""
        if char_row.get("appearance") and str(char_row["appearance"]).strip():
            appearance_text = str(char_row["appearance"]).strip()
        elif char_row.get("description") and str(char_row["description"]).strip():
            appearance_text = str(char_row["description"]).strip()
        else:
            appearance_text = char_row.get("name") or ""

        system_prompt = promptI18n.get_role_polish_prompt(merged_cfg)
        user_prompt = f"角色名称：{char_row.get('name')}\n\n角色描述：\n{appearance_text}"

        log.info("[四视图] Step1 开始生成四视图提示词", extra={"character_id": character_id, "char_name": char_row.get("name")})
        try:
            four_view_description = aiClient.generate_text(
                db, log, "text", user_prompt, system_prompt,
                options={"scene_key": "role_image_polish", "model": model_name or None, "max_tokens": 4000},
            )
        except Exception as err:
            log.error("[四视图] Step1 文本AI失败，降级为直接使用外貌描述", extra={"error": str(err)})
            four_view_description = appearance_text

        style_cfg = merged_cfg.get("style", {}) if isinstance(merged_cfg, dict) else {}
        style_en = (style_cfg.get("default_style_en") or style_cfg.get("default_style") or "").strip()
        style_zh = (style_cfg.get("default_style_zh") or "").strip()
        image_prompt = build_four_view_image_prompt(four_view_description, style_en, style_zh)

        try:
            now = timestamp()
            db.execute(
                text("UPDATE characters SET polished_prompt = :p, updated_at = :now WHERE id = :id"),
                {"p": image_prompt, "now": now, "id": cid},
            )
            db.commit()
        except Exception:
            pass

        log.info("[四视图] Step1 完成，开始Step2生图", extra={"character_id": character_id})

    user_neg = imageClient.resolve_asset_user_negative_for_api(model_name, char_row.get("negative_prompt"))
    image_gen = imageClient.create_and_generate_image(db, log, {
        "drama_id": char_row["drama_id"],
        "character_id": char_row["id"],
        "prompt": image_prompt,
        "model": model_name or None,
        "size": "1792x1024",
        "quality": "standard",
        "provider": "openai",
        "user_negative_prompt": user_neg or None,
    })

    log.info("[四视图] Step2 图片生成任务已提交", extra={"character_id": character_id, "image_gen_id": image_gen.get("id") if image_gen else None})
    return {"ok": True, "image_generation": image_gen}


def batch_generate_character_images(db: Session, log, cfg: dict, character_ids, model_name=None, style=None) -> dict:
    ids = [str(i) for i in character_ids] if isinstance(character_ids, list) else []
    if not ids:
        return {"ok": False, "error": "character_ids 不能为空"}
    if len(ids) > 10:
        return {"ok": False, "error": "单次最多生成10个角色"}

    log.info("Starting batch character four-view generation", extra={"count": len(ids), "model": model_name, "character_ids": ids})

    def _run_single(char_id: str):
        try:
            from app.core.config import load_config
            from app.db.session import session_scope
            thread_cfg = load_config()
            with session_scope() as session:
                out = generate_character_four_view_image(session, log, thread_cfg, char_id, model_name, style)
                if not out.get("ok"):
                    log.warning("Batch character four-view skip", extra={"character_id": char_id, "error": out.get("error")})
                    return
                image_gen = out.get("image_generation")
                log.info("Batch character four-view submitted", extra={"character_id": char_id, "image_gen_id": image_gen.get("id") if image_gen else None})
        except Exception as err:
            log.error("Batch character four-view failed", extra={"character_id": char_id, "error": str(err)})

    for cid in ids:
        workerService.submit(_run_single, cid)

    log.info("Batch character four-view tasks queued", extra={"total": len(ids)})
    return {"ok": True, "count": len(ids)}


def extract_appearance_from_image(db: Session, log, cfg: dict, character_id) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, name, image_url, local_path, extra_images, ref_image FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": cid},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}

    img_src = aiClient.resolve_entity_image_source(dict(char_row), cfg)
    if not img_src:
        return {"ok": False, "error": "该角色暂无参考图片，请先上传图片"}

    char_prompts = aiClient.EXTRACT_PROMPTS.get("character", {})
    system_prompt = char_prompts.get("system") or ""
    user_fn = char_prompts.get("user")
    user_prompt = user_fn(char_row.get("name")) if callable(user_fn) else str(char_row.get("name") or "")

    try:
        appearance = aiClient.generate_text_with_vision(
            db, log, "text", user_prompt, system_prompt, img_src, options={"max_tokens": 2000}
        )
    except Exception as err:
        log.error("[extractAppearanceFromImage] AI 调用失败", extra={"characterId": character_id, "error": str(err)})
        err_msg = str(err)
        if re.search(r"image|vision|visual|multimodal", err_msg, re.IGNORECASE):
            err_msg = f"AI 模型不支持图片识别，请在「AI 配置」中使用支持视觉的模型（如 GPT-4o、Gemini 1.5 等）【原始错误：{err_msg[:120]}】"
        else:
            err_msg = f"AI 分析失败：{err_msg}"
        return {"ok": False, "error": err_msg}

    if aiClient.is_refusal_response(appearance):
        log.warning("[extractAppearanceFromImage] 模型拒绝描述真人", extra={"characterId": character_id, "result": appearance})
        return {
            "ok": False,
            "error": "模型因安全策略拒绝描述图中人物面部特征。建议：①使用 Gemini 模型（限制较少）；②手动填写外貌描述；③上传卡通/插画风格的参考图。",
        }

    now = timestamp()
    db.execute(
        text("UPDATE characters SET appearance = :app, updated_at = :now WHERE id = :id"),
        {"app": appearance, "now": now, "id": cid},
    )
    db.commit()

    log.info("[extractAppearanceFromImage] 外貌提取成功", extra={"characterId": character_id, "appearance_len": len(appearance)})
    return {"ok": True, "appearance": appearance}


# ======================================================================
# Seedance 2.0 角色素材认证（即梦 Hub / 火山 ModelArk）
# ======================================================================

def build_character_public_image_url_for_hub(char_row: dict, cfg: dict) -> dict:
    img = str(char_row.get("image_url") or "").strip()
    lp = str(char_row.get("local_path") or "").strip()
    base_raw = str(((cfg or {}).get("storage") or {}).get("base_url") or "").strip()
    public_base = base_raw.rstrip("/")

    if re.match(r"^https?://", img, re.IGNORECASE):
        return {"ok": True, "url": img}
    if not public_base:
        return {
            "ok": False,
            "error": "角色主图非 http(s) 直链且未配置 storage.base_url，无法组成素材库可拉取的图片 URL（请将主图设为图床/即梦返回地址，或配置本服务静态资源公网 base_url）",
        }
    if lp:
        path_part = lp.lstrip("/")
        return {"ok": True, "url": f"{public_base}/{path_part}"}
    if img.startswith("/"):
        if public_base.endswith("/static") and img.startswith("/static/"):
            return {"ok": True, "url": public_base + img[len("/static"):]}
        m = re.match(r"^(https?://[^/]+)", public_base, re.IGNORECASE)
        if m:
            return {"ok": True, "url": m.group(1) + img}
    fallback = resolve_image_url(char_row.get("image_url"), char_row.get("local_path"))
    if fallback and re.match(r"^https?://", fallback, re.IGNORECASE):
        return {"ok": True, "url": fallback}
    return {"ok": False, "error": "角色缺少素材库可用的图片（需 http(s) 图链或 local_path + 公网 base_url）"}


def storage_root_path(cfg: dict) -> str:
    raw = str(((cfg or {}).get("storage") or {}).get("local_path") or "./data/storage")
    return raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)


def is_non_public_material_hub_url(url: str | None) -> bool:
    s = str(url or "").strip()
    if not s:
        return True
    if s.startswith("data:"):
        return True
    if not re.match(r"^https?://", s, re.IGNORECASE):
        return True
    try:
        parsed = urlparse(s)
        h = (parsed.hostname or "").lower()
        if h in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"):
            return True
        if h.startswith("192.168.") or h.startswith("10."):
            return True
        m = re.match(r"^172\.(\d+)\.", h)
        if m and 16 <= int(m.group(1)) <= 31:
            return True
    except Exception:
        return True
    return False


def material_hub_proxy_cache_key(char_row: dict, image_url: str) -> str:
    lp = str(char_row.get("local_path") or "").strip().lstrip("/")
    if lp:
        return lp
    sha = hashlib.sha256(str(image_url).encode("utf-8")).hexdigest()[:48]
    return f"sd2char:url:{sha}"


def is_hub_download_media_error(msg: str | None) -> bool:
    return bool(re.search(r"DownloadFailed|download media|accessible|拉取|下载|tos: request error|fetch-object", str(msg or ""), re.IGNORECASE))


def is_hub_auth_token_error(msg: str | None) -> bool:
    return bool(re.search(r"无效的\s*token|invalid\s*token|unauthorized|401", str(msg or ""), re.IGNORECASE))


def format_sd2_hub_error(err_msg: str | None, hub_ctx: dict) -> str:
    out = str(err_msg or "素材库创建素材失败")
    if not is_hub_auth_token_error(out):
        return out
    diag = hub_ctx.get("hubAuthDiag") or hub_ctx.get("hub_auth_diag") or {}
    parts = [
        f"即梦2素材库拒绝了当前 Token（{out}）。",
        "请在「AI 配置」→「即梦2角色认证」中重新粘贴与 curl 测试完全相同的密钥并点击保存（勿带 Bearer 前缀、勿多空格）。",
        "保存前可用「列出素材」验证；若列出成功而 SD2 仍失败，说明未保存或存在多条配置未设为默认。",
    ]
    if diag.get("db_config_id") is not None:
        cfg_name = f"「{diag['db_config_name']}」" if diag.get("db_config_name") else ""
        parts.append(f"当前读取的配置：id={diag['db_config_id']}{cfg_name}。")
    fp = diag.get("token_fingerprint") or hub_ctx.get("tokenFingerprint")
    if fp:
        parts.append(f"Token 指纹：{fp}（请与 curl 测试通过时 Bearer 密钥的首尾字符对照是否一致）。")
    return "".join(parts)


def ensure_public_register_image_url_for_material_hub(
    db: Session, log, cfg: dict, char_row: dict, image_url: str, opts: dict | None = None
) -> dict:
    opts = opts or {}
    force_local_proxy = bool(opts.get("forceLocalProxy"))
    if not force_local_proxy and not is_non_public_material_hub_url(image_url):
        return {"ok": True, "url": image_url, "via": "direct"}

    cache_key = material_hub_proxy_cache_key(char_row, image_url)
    cached = imageClient.get_proxy_cache_validated(db, cache_key, log, f"sd2_char_{char_row.get('id')}")
    if cached:
        log.info("[SD2认证] 使用图床缓存 URL", extra={"character_id": char_row.get("id"), "cache_key": cache_key})
        return {"ok": True, "url": cached, "via": "cache"}

    storage_path = storage_root_path(cfg)
    local_ref = str(char_row.get("local_path") or "").strip() or image_url
    proxy_url = uploadService.upload_local_image_to_proxy(storage_path, local_ref, log, f"sd2_char_{char_row.get('id')}", cfg)
    if not proxy_url:
        return {
            "ok": False,
            "error": "角色图为本机或内网地址，已尝试上传到中转图床失败（请确认 storage.local_path 下文件存在，且 image_proxy 配置可用）",
        }
    imageClient.set_proxy_cache(db, cache_key, proxy_url)
    log.info("[SD2认证] 已上传图床供素材库拉取", extra={"character_id": char_row.get("id"), "cache_key": cache_key})
    return {"ok": True, "url": proxy_url, "via": "upload"}


def read_seedance2_asset_json(text_val: Any) -> dict | None:
    if not text_val:
        return None
    if isinstance(text_val, dict):
        return text_val
    try:
        parsed = json.loads(text_val)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def resolve_sd2_register_provider(cfg: dict, db: Session, log) -> dict:
    hub_ctx = jimengMaterialHubService.build_hub_context(cfg, db, log)
    if hub_ctx.get("token"):
        return {"provider": "hub", "hubCtx": hub_ctx}
    ark_ctx = modelArkAssetConfigService.build_model_ark_context(db, log)
    if ark_ctx.get("ready"):
        return {"provider": "model_ark", "arkCtx": ark_ctx}
    return {"provider": None, "hubCtx": hub_ctx, "arkCtx": ark_ctx}


def sd2_config_missing_error(hub_ctx: dict | None, ark_ctx: dict | None) -> str:
    parts = [
        "未配置 SD2 认证，请在「AI 配置」中任选其一：",
        "① 添加「即梦2角色认证」（网关 URL + Token）；",
        "② 或在「SD2 资产管理」点击「保存到 AI 配置」，填写 AK/SK 与默认资产组 Id。",
    ]
    diag = (ark_ctx or {}).get("diag") or {}
    if diag.get("missing"):
        parts.append(f"（ModelArk 配置不完整：缺少 {diag['missing']}）")
    if not (hub_ctx or {}).get("token") and diag.get("db_model_ark_row_found") is False:
        parts.append("（当前未找到已保存的 ModelArk 资产库配置）")
    return "".join(parts)


def prepare_character_register_image(db: Session, log, cfg: dict, character_id) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT * FROM characters WHERE id = :id AND deleted_at IS NULL"), {"id": cid}
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    char_dict = dict(char_row)
    if not char_dict.get("image_url") and not char_dict.get("local_path"):
        return {"ok": False, "error": "角色还没有形象图片"}

    url_out = build_character_public_image_url_for_hub(char_dict, cfg)
    if not url_out.get("ok"):
        return url_out
    image_url = url_out["url"]
    if str(image_url).startswith("data:"):
        return {"ok": False, "error": "不支持 base64 图片注册，请先使用上传或外网图链"}

    pub = ensure_public_register_image_url_for_material_hub(db, log, cfg, char_dict, image_url)
    if not pub.get("ok"):
        return pub

    clean_name = re.sub(r"\s+", "", str(char_dict.get("name") or "role"))[:12] or "role"
    return {
        "ok": True,
        "charRow": char_dict,
        "imageUrl": image_url,
        "registerImageUrl": pub["url"],
        "pub": pub,
        "assetName": clean_name,
    }


def build_seedance2_base_payload(char_row: dict, asset_id: str, created: dict, register_image_url: str, sd2_provider: str) -> dict:
    now = timestamp()
    certified_lp = sd2.normalize_storage_rel_path(char_row.get("local_path") or "") or None
    certified_img = str(char_row.get("image_url") or "").strip() or None
    return {
        "hub_asset_id": asset_id,
        "asset_url": created.get("asset_url") or modelArkAssetConfigService.asset_url_for_video(created) or None,
        "status": created.get("status") or "processing",
        "source_image_url": register_image_url,
        "certified_local_path": certified_lp,
        "certified_image_url": certified_img,
        "sd2_provider": sd2_provider,
        "character_display": {
            "name": char_row.get("name") or "",
            "appearance": str(char_row.get("appearance") or "")[:500] or None,
            "description": str(char_row.get("description") or "")[:500] or None,
        },
        "updated_at": now,
    }


def register_character_via_jimeng_hub(db: Session, log, cfg: dict, character_id, hub_ctx: dict, prep: dict) -> dict:
    cid = to_int_id(character_id)
    char_row = prep["charRow"]
    image_url = prep["imageUrl"]
    register_image_url = prep["registerImageUrl"]
    pub = prep["pub"]
    asset_name = prep["assetName"]
    register_url_looks_private = is_non_public_material_hub_url(image_url)

    log.info("[SD2认证][hub] 请求参数摘要", extra={
        "character_id": cid,
        "character_name": char_row.get("name"),
        "drama_id": char_row.get("drama_id"),
        "resolved_register_image_url": str(register_image_url)[:500],
        "hub_gateway": hub_ctx.get("base_url") or hub_ctx.get("baseUrl"),
        "hub_auth_diag": hub_ctx.get("hubAuthDiag") or hub_ctx.get("hub_auth_diag"),
        "asset_name": asset_name,
        "register_url_looks_private_host": register_url_looks_private,
    })

    create_res = jimengMaterialHubService.create_image_asset(hub_ctx, {"url": register_image_url, "name": asset_name}, log)
    if not create_res.get("ok") and is_hub_download_media_error(create_res.get("error")) and pub.get("via") == "direct" and char_row.get("local_path"):
        proxy_retry = ensure_public_register_image_url_for_material_hub(db, log, cfg, char_row, image_url, {"forceLocalProxy": True})
        if proxy_retry.get("ok") and proxy_retry.get("url") and proxy_retry["url"] != register_image_url:
            register_image_url = proxy_retry["url"]
            create_res = jimengMaterialHubService.create_image_asset(hub_ctx, {"url": register_image_url, "name": asset_name}, log)

    if not create_res.get("ok"):
        err_msg = format_sd2_hub_error(create_res.get("error"), hub_ctx)
        if is_hub_download_media_error(create_res.get("error")):
            err_msg += (
                " 【说明】素材库会从云端访问你提交的「图片 URL」。火山引擎/即梦临时链常无法被网关拉取，本服务已尝试用本地图上传中转图床；若仍失败请检查 local_path 文件是否存在、图床是否可用，或换百度图床等公网直链。"
            )
        return {"ok": False, "error": err_msg}

    created = create_res.get("data") or {}
    asset_id = created.get("id")
    if not asset_id:
        return {"ok": False, "error": "素材库返回缺少素材 id"}

    base_payload = build_seedance2_base_payload(char_row, asset_id, created, register_image_url, "hub")
    db.execute(
        text("UPDATE characters SET seedance2_asset = :a, updated_at = :now WHERE id = :id"),
        {"a": json.dumps(base_payload), "now": base_payload["updated_at"], "id": cid},
    )
    db.commit()

    poll = jimengMaterialHubService.poll_asset_until_settled(hub_ctx, asset_id, {
        "maxMs": hub_ctx.get("poll_max_ms") or 120000,
        "intervalMs": hub_ctx.get("poll_interval_ms") or 2000,
        "log": log,
    })
    if not poll.get("ok"):
        return {"ok": False, "error": poll.get("error")}

    settled = poll.get("asset") or created
    next_payload = {
        **base_payload,
        "asset_url": settled.get("asset_url") if settled.get("asset_url") is not None else base_payload.get("asset_url"),
        "status": settled.get("status") or base_payload.get("status"),
        "hub_url": settled.get("url") or created.get("url") or None,
        "poll_timed_out": bool(poll.get("timedOut")),
        "updated_at": timestamp(),
    }
    db.execute(
        text("UPDATE characters SET seedance2_asset = :a, updated_at = :now WHERE id = :id"),
        {"a": json.dumps(next_payload), "now": next_payload["updated_at"], "id": cid},
    )
    db.commit()

    log.info("[SD2认证][hub] 素材已登记", extra={"characterId": cid, "hub_asset_id": asset_id, "status": next_payload.get("status")})
    return {"ok": True, "seedance2_asset": next_payload}


def register_character_via_model_ark(db: Session, log, cfg: dict, character_id, ark_ctx: dict, prep: dict) -> dict:
    cid = to_int_id(character_id)
    char_row = prep["charRow"]
    image_url = prep["imageUrl"]
    register_image_url = prep["registerImageUrl"]
    pub = prep["pub"]
    asset_name = prep["assetName"]

    log.info("[SD2认证][model_ark] 请求参数摘要", extra={
        "character_id": cid,
        "character_name": char_row.get("name"),
        "drama_id": char_row.get("drama_id"),
        "resolved_register_image_url": str(register_image_url)[:500],
        "asset_group_id": ark_ctx.get("assetGroupId") or ark_ctx.get("asset_group_id"),
        "auth_mode": (ark_ctx.get("diag") or {}).get("auth_mode"),
        "asset_name": asset_name,
    })

    create_res = modelArkAssetConfigService.create_image_asset(ark_ctx, {"url": register_image_url, "name": asset_name}, log)
    if not create_res.get("ok") and is_hub_download_media_error(create_res.get("error")) and pub.get("via") == "direct" and char_row.get("local_path"):
        proxy_retry = ensure_public_register_image_url_for_material_hub(db, log, cfg, char_row, image_url, {"forceLocalProxy": True})
        if proxy_retry.get("ok") and proxy_retry.get("url") and proxy_retry["url"] != register_image_url:
            register_image_url = proxy_retry["url"]
            create_res = modelArkAssetConfigService.create_image_asset(ark_ctx, {"url": register_image_url, "name": asset_name}, log)

    if not create_res.get("ok"):
        return {"ok": False, "error": f"ModelArk 创建资产失败：{str(create_res.get('error') or '')[:1500]}"}

    created = create_res.get("data") or {}
    asset_id = created.get("id")
    if not asset_id:
        return {"ok": False, "error": "ModelArk 返回缺少资产 Id"}

    base_payload = build_seedance2_base_payload(char_row, asset_id, created, register_image_url, "model_ark")
    db.execute(
        text("UPDATE characters SET seedance2_asset = :a, updated_at = :now WHERE id = :id"),
        {"a": json.dumps(base_payload), "now": base_payload["updated_at"], "id": cid},
    )
    db.commit()

    poll = modelArkAssetConfigService.poll_asset_until_settled(ark_ctx, asset_id, {"log": log})
    if not poll.get("ok"):
        return {"ok": False, "error": poll.get("error")}

    settled = poll.get("asset") or created
    next_payload = {
        **base_payload,
        "asset_url": settled.get("asset_url") if settled.get("asset_url") is not None else base_payload.get("asset_url"),
        "status": settled.get("status") or base_payload.get("status"),
        "poll_timed_out": bool(poll.get("timedOut")),
        "updated_at": timestamp(),
    }
    db.execute(
        text("UPDATE characters SET seedance2_asset = :a, updated_at = :now WHERE id = :id"),
        {"a": json.dumps(next_payload), "now": next_payload["updated_at"], "id": cid},
    )
    db.commit()

    log.info("[SD2认证][model_ark] 素材已登记", extra={"characterId": cid, "hub_asset_id": asset_id, "status": next_payload.get("status")})
    return {"ok": True, "seedance2_asset": next_payload}


def register_character_jimeng_material_asset(db: Session, log, cfg: dict, character_id) -> dict:
    route = resolve_sd2_register_provider(cfg, db, log)
    if not route.get("provider"):
        return {"ok": False, "error": sd2_config_missing_error(route.get("hubCtx"), route.get("arkCtx"))}
    prep = prepare_character_register_image(db, log, cfg, character_id)
    if not prep.get("ok"):
        return prep
    if route["provider"] == "hub":
        return register_character_via_jimeng_hub(db, log, cfg, character_id, route["hubCtx"], prep)
    return register_character_via_model_ark(db, log, cfg, character_id, route["arkCtx"], prep)


def refresh_character_jimeng_material_asset(db: Session, log, cfg: dict, character_id) -> dict:
    cid = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, seedance2_asset FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": cid},
    ).mappings().first()
    if not char_row:
        return {"ok": False, "error": "character not found"}
    prev = read_seedance2_asset_json(char_row.get("seedance2_asset"))
    asset_id = (prev or {}).get("hub_asset_id") if isinstance(prev, dict) else None
    if not asset_id:
        return {"ok": False, "error": "暂未取得素材 id，请先完成 SD2 认证"}

    provider = "model_ark" if str((prev or {}).get("sd2_provider") or "").lower() == "model_ark" else "hub"
    settled = None
    if provider == "model_ark":
        ark_ctx = modelArkAssetConfigService.build_model_ark_context(db, log)
        if not ark_ctx.get("ready"):
            return {"ok": False, "error": "未找到有效的 ModelArk 资产库配置，无法刷新认证状态"}
        r = modelArkAssetConfigService.get_asset(ark_ctx, asset_id, log)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        settled = r.get("data")
    else:
        hub_ctx = jimengMaterialHubService.build_hub_context(cfg, db, log)
        if not hub_ctx.get("token"):
            return {"ok": False, "error": "未配置即梦2角色认证：请在「AI 配置」中填写 Token"}
        r = jimengMaterialHubService.get_asset(hub_ctx, asset_id, log)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        settled = r.get("data")

    now = timestamp()
    next_payload = {
        **(prev if isinstance(prev, dict) else {}),
        "hub_asset_id": asset_id,
        "asset_url": settled.get("asset_url") if isinstance(settled, dict) and settled.get("asset_url") else ((prev or {}).get("asset_url") if isinstance(prev, dict) else None) or (modelArkAssetConfigService.asset_url_for_video(settled) if isinstance(settled, dict) else None),
        "status": (settled.get("status") if isinstance(settled, dict) else None) or ((prev or {}).get("status") if isinstance(prev, dict) else "processing"),
        "hub_url": (settled.get("url") if isinstance(settled, dict) else None) or ((prev or {}).get("hub_url") if isinstance(prev, dict) else None),
        "sd2_provider": provider,
        "updated_at": now,
    }
    db.execute(
        text("UPDATE characters SET seedance2_asset = :a, updated_at = :now WHERE id = :id"),
        {"a": json.dumps(next_payload), "now": now, "id": cid},
    )
    db.commit()
    return {"ok": True, "seedance2_asset": next_payload}


# Aliases for compatibility with camelCase calls
updateCharacter = update_character
deleteCharacter = delete_character
generateCharacterImage = generate_character_image
batchGenerateCharacterImages = batch_generate_character_images
generateCharacterFourViewImage = generate_character_four_view_image
generateCharacterPromptOnly = generate_character_prompt_only
extractAppearanceFromImage = extract_appearance_from_image
registerCharacterJimengMaterialAsset = register_character_jimeng_material_asset
refreshCharacterJimengMaterialAsset = refresh_character_jimeng_material_asset
buildFourViewImagePrompt = build_four_view_image_prompt
detectGenderFromDescription = detect_gender_from_description
