"""剧本聚合服务（等价 Node services/dramaService.js 的纯 CRUD 部分）。

P2 已翻译：
- createDrama / getDramaById / getDrama / listDramas / updateDrama / deleteDrama / getDramaStats
- saveOutline / getCharacters / saveCharacters / saveEpisodes / saveProgress / saveCanvasLayout
- rowToDrama / rowToEpisode / rowToStoryboard / rowToCharacter / rowToScene / rowToProp

P4/P5 待翻译：generateStoryboard、finalizeEpisode、downloadEpisodeVideo、导入导出。
"""
from __future__ import annotations

import json
import math

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.constants.generationStylePresets import resolve_style_preset
from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one
from app.services import videoMergeService as vm_svc
from app.services.libraryCommon import js_parse_int
from app.services.storageLayout import parse_metadata, sanitize_folder_label
from app.utils import seedance2AssetGuards as sd2

log = get_logger("lmd.drama")


# ---------------- 通用工具 ----------------


def sanitize_image_url(url):
    """base64 data URL 不透传（避免响应体膨胀）。"""
    if not url:
        return None
    if str(url).startswith("data:"):
        return None
    return url


def parse_json_column(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def to_int_id(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


# ---------------- row → dict ----------------


def row_to_drama(r: dict) -> dict:
    meta = r.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return {
        "id": r.get("id"),
        "title": r.get("title"),
        "description": r.get("description"),
        "genre": r.get("genre"),
        "style": r.get("style") or "realistic",
        "total_episodes": r.get("total_episodes") if r.get("total_episodes") is not None else 1,
        "total_duration": r.get("total_duration") if r.get("total_duration") is not None else 0,
        "status": r.get("status") or "draft",
        "thumbnail": r.get("thumbnail"),
        "tags": r.get("tags"),
        "metadata": meta or {},
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def row_to_episode(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "drama_id": r.get("drama_id"),
        "episode_number": r.get("episode_number"),
        "title": r.get("title"),
        "script_content": r.get("script_content"),
        "description": r.get("description"),
        "duration": r.get("duration") if r.get("duration") is not None else 0,
        "status": r.get("status") or "draft",
        "video_url": r.get("video_url"),
        "thumbnail": r.get("thumbnail"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def parse_storyboard_characters(characters_str) -> list:
    if not characters_str or not isinstance(characters_str, str):
        return []
    try:
        parsed = json.loads(characters_str)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out = []
    for c in parsed:
        n = c.get("id") if isinstance(c, dict) and c is not None else c
        try:
            f = float(n)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(int(f))
    return out


def row_to_storyboard(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "episode_id": r.get("episode_id"),
        "scene_id": r.get("scene_id"),
        "storyboard_number": r.get("storyboard_number"),
        "title": r.get("title"),
        "description": r.get("description"),
        "location": r.get("location"),
        "time": r.get("time"),
        "duration": r.get("duration") if r.get("duration") is not None else 0,
        "dialogue": r.get("dialogue"),
        "narration": r.get("narration"),
        "action": r.get("action"),
        "result": r.get("result"),
        "atmosphere": r.get("atmosphere"),
        "image_prompt": r.get("image_prompt"),
        "polished_prompt": r.get("polished_prompt"),
        "continuity_snapshot": r.get("continuity_snapshot"),
        "video_prompt": r.get("video_prompt"),
        "shot_type": r.get("shot_type"),
        "angle": r.get("angle"),
        "angle_h": r.get("angle_h"),
        "angle_v": r.get("angle_v"),
        "angle_s": r.get("angle_s"),
        "movement": r.get("movement"),
        "lighting_style": r.get("lighting_style"),
        "depth_of_field": r.get("depth_of_field"),
        "segment_index": r.get("segment_index") if r.get("segment_index") is not None else 0,
        "segment_title": r.get("segment_title"),
        "creation_mode": "universal" if r.get("creation_mode") == "universal" else "classic",
        "universal_segment_text": r.get("universal_segment_text"),
        "first_frame_image_id": r.get("first_frame_image_id"),
        "last_frame_image_id": r.get("last_frame_image_id"),
        "last_frame_image_url": sanitize_image_url(r.get("last_frame_image_url")),
        "last_frame_local_path": r.get("last_frame_local_path"),
        "characters": parse_storyboard_characters(r.get("characters")),
        "composed_image": r.get("composed_image"),
        "image_url": sanitize_image_url(r.get("image_url")),
        "local_path": r.get("local_path"),
        "main_panel_idx": int(r["main_panel_idx"]) if r.get("main_panel_idx") is not None else None,
        "video_url": r.get("video_url"),
        "audio_local_path": r.get("audio_local_path"),
        "narration_audio_local_path": r.get("narration_audio_local_path"),
        "status": r.get("status") or "pending",
        "error_msg": r.get("error_msg"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def row_to_character(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "drama_id": r.get("drama_id"),
        "name": r.get("name"),
        "role": r.get("role"),
        "description": r.get("description"),
        "appearance": r.get("appearance"),
        "personality": r.get("personality"),
        "voice_style": r.get("voice_style"),
        "image_url": sanitize_image_url(r.get("image_url")),
        "local_path": r.get("local_path"),
        "extra_images": r.get("extra_images") or None,
        "ref_image": r.get("ref_image") or None,
        # 注：reference_images / seed_value 在 Node 的 characters 表中并不存在（rowToCharacter
        # 取到 undefined，序列化时键被丢弃）。Python 侧若输出 null 会导致契约不等价，故整键剔除。
        "sort_order": r.get("sort_order") if r.get("sort_order") is not None else 0,
        "error_msg": r.get("error_msg"),
        "polished_prompt": r.get("polished_prompt") or None,
        "negative_prompt": r.get("negative_prompt") or None,
        "four_view_image_url": r.get("four_view_image_url") or None,
        "seedance2_asset": parse_json_column(r.get("seedance2_asset")),
        "seedance2_voice_asset": parse_json_column(r.get("seedance2_voice_asset")),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def row_to_scene(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "drama_id": r.get("drama_id"),
        "location": r.get("location"),
        "time": r.get("time"),
        "prompt": r.get("prompt"),
        "polished_prompt": r.get("polished_prompt") or None,
        # 注：Node 库中 scenes 无 polished_prompt_single 列，rowToScene 取到 undefined
        # 会被 JSON.stringify 丢弃；Python 侧须整键剔除才能契约等价（check_column_drift 检出）
        "negative_prompt": r.get("negative_prompt") or None,
        "storyboard_count": r.get("storyboard_count") if r.get("storyboard_count") is not None else 1,
        "image_url": sanitize_image_url(r.get("image_url")),
        "local_path": r.get("local_path"),
        "extra_images": r.get("extra_images") or None,
        "ref_image": r.get("ref_image") or None,
        "status": r.get("status") or "pending",
        "error_msg": r.get("error_msg"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def row_to_prop(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "drama_id": r.get("drama_id"),
        "name": r.get("name"),
        "type": r.get("type"),
        "description": r.get("description"),
        "prompt": r.get("prompt"),
        "image_url": sanitize_image_url(r.get("image_url")),
        "local_path": r.get("local_path"),
        "extra_images": r.get("extra_images") or None,
        "ref_image": r.get("ref_image") or None,
        "negative_prompt": r.get("negative_prompt") or None,
        "error_msg": r.get("error_msg"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


# ---------------- 分镜去重（等价 episodeStoryboardService.dedupeStoryboardRowsByNumber） ----------------


def normalize_storyboard_shot_number(raw_or_sb) -> int:
    raw = raw_or_sb if not isinstance(raw_or_sb, dict) else (raw_or_sb.get("shot_number") or raw_or_sb.get("storyboard_number"))
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return 0
    return math.floor(n) if math.isfinite(n) and n > 0 else 0


def dedupe_storyboard_rows_by_number(rows: list[dict]) -> list[dict]:
    by_num: dict[int, dict] = {}
    extras: list[dict] = []
    for r in rows or []:
        num = normalize_storyboard_shot_number(r.get("storyboard_number") if isinstance(r, dict) else r)
        if num > 0:
            prev = by_num.get(num)
            if not prev or int(r["id"]) > int(prev["id"]):
                by_num[num] = r
        else:
            extras.append(r)
    merged = list(by_num.values()) + extras
    merged.sort(
        key=lambda a: (
            normalize_storyboard_shot_number(a.get("storyboard_number")),
            int(a.get("id") or 0),
        )
    )
    return merged


def _attach_storyboard_prop_ids(db: Session, storyboards: list[dict]) -> None:
    """批量附加 prop_ids（Node 用 try/catch 包住，storyboard_props 缺表时不抛错）。"""
    sb_ids = [s["id"] for s in storyboards]
    if not sb_ids:
        return
    try:
        names = ", ".join(f":id{i}" for i in range(len(sb_ids)))
        params = {f"id{i}": v for i, v in enumerate(sb_ids)}
        rows = db.execute(
            text(f"SELECT storyboard_id, prop_id FROM storyboard_props WHERE storyboard_id IN ({names})"), params
        ).mappings().all()
        sp_map: dict[int, list] = {}
        for row in rows:
            sp_map.setdefault(row["storyboard_id"], []).append(row["prop_id"])
        for sb in storyboards:
            sb["prop_ids"] = sp_map.get(sb["id"], [])
    except Exception:
        pass


# ---------------- CRUD ----------------


def create_drama(db: Session, req: dict) -> dict:
    now = timestamp()
    meta = {}
    if req.get("metadata"):
        try:
            meta = json.loads(req["metadata"]) if isinstance(req["metadata"], str) else dict(req["metadata"])
        except Exception:
            meta = {}
    if not meta.get("storage_folder_label"):
        meta["storage_folder_label"] = sanitize_folder_label(req.get("title") or "")
    metadata_str = json.dumps(meta) if meta else None

    res = db.execute(
        text(
            """
            INSERT INTO dramas (title, description, genre, style, metadata, status, created_at, updated_at)
            VALUES (:title, :description, :genre, :style, :metadata, 'draft', :created_at, :updated_at)
            """
        ),
        {
            "title": req.get("title") or "",
            "description": req.get("description") or None,
            "genre": req.get("genre") or None,
            "style": req.get("style") or "realistic",
            "metadata": metadata_str,
            "created_at": now,
            "updated_at": now,
        },
    )
    log.info("Drama created", extra={"drama_id": res.lastrowid})
    return get_drama_by_id(db, res.lastrowid)


def get_drama_by_id(db: Session, drama_id) -> dict | None:
    row = db.execute(
        text("SELECT * FROM dramas WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(drama_id)}
    ).mappings().first()
    return row_to_drama(dict(row)) if row else None


def _load_episode_extras(db: Session, ep: dict) -> None:
    """加载分集的分镜/角色/场景/道具（与 Node getDrama 内循环一致）。"""
    sb_rows = db.execute(
        text(
            "SELECT * FROM storyboards WHERE episode_id = :ep AND deleted_at IS NULL "
            "ORDER BY storyboard_number ASC, id ASC"
        ),
        {"ep": ep["id"]},
    ).mappings().all()
    storyboards = [row_to_storyboard(dict(r)) for r in sb_rows]
    storyboards = dedupe_storyboard_rows_by_number(storyboards)
    ep["storyboards"] = storyboards
    _attach_storyboard_prop_ids(db, storyboards)

    ep["duration"] = sum((s.get("duration") or 0) for s in storyboards)
    if ep["duration"] > 0:
        ep["duration"] = math.ceil(ep["duration"] / 60)

    try:
        chars = db.execute(
            text(
                "SELECT c.* FROM characters c INNER JOIN episode_characters ec ON c.id = ec.character_id "
                "WHERE ec.episode_id = :ep AND c.deleted_at IS NULL ORDER BY c.sort_order ASC, c.name ASC"
            ),
            {"ep": ep["id"]},
        ).mappings().all()
        ep["characters"] = [row_to_character(dict(c)) for c in chars]
    except Exception:
        ep["characters"] = []

    try:
        scenes = db.execute(
            text("SELECT * FROM scenes WHERE episode_id = :ep AND deleted_at IS NULL ORDER BY id ASC"),
            {"ep": ep["id"]},
        ).mappings().all()
        ep["scenes"] = [row_to_scene(dict(s)) for s in scenes]
    except Exception:
        ep["scenes"] = []

    try:
        by_episode = db.execute(
            text("SELECT * FROM props WHERE episode_id = :ep AND deleted_at IS NULL ORDER BY id ASC"),
            {"ep": ep["id"]},
        ).mappings().all()
        by_storyboard = db.execute(
            text(
                "SELECT DISTINCT p.* FROM props p INNER JOIN storyboard_props sp ON p.id = sp.prop_id "
                "INNER JOIN storyboards sb ON sb.id = sp.storyboard_id AND sb.episode_id = :ep AND sb.deleted_at IS NULL "
                "WHERE p.deleted_at IS NULL ORDER BY p.id ASC"
            ),
            {"ep": ep["id"]},
        ).mappings().all()
        seen: set = set()
        props: list[dict] = []
        for p in list(by_episode) + list(by_storyboard):
            d = dict(p)
            if d["id"] not in seen:
                seen.add(d["id"])
                props.append(row_to_prop(d))
        props.sort(key=lambda x: x["id"])
        ep["props"] = props
    except Exception:
        ep["props"] = []


def get_drama(db: Session, drama_id) -> dict | None:
    drama = get_drama_by_id(db, drama_id)
    if not drama:
        return None
    episodes = db.execute(
        text("SELECT * FROM episodes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY episode_number ASC"),
        {"did": drama["id"]},
    ).mappings().all()
    drama["episodes"] = [row_to_episode(dict(e)) for e in episodes]
    for ep in drama["episodes"]:
        _load_episode_extras(db, ep)

    chars = db.execute(
        text("SELECT * FROM characters WHERE drama_id = :did AND deleted_at IS NULL ORDER BY sort_order ASC, name ASC"),
        {"did": drama["id"]},
    ).mappings().all()
    drama["characters"] = [row_to_character(dict(c)) for c in chars]
    scenes = db.execute(
        text("SELECT * FROM scenes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC"),
        {"did": drama["id"]},
    ).mappings().all()
    drama["scenes"] = [row_to_scene(dict(s)) for s in scenes]
    props = db.execute(
        text("SELECT * FROM props WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC"),
        {"did": drama["id"]},
    ).mappings().all()
    drama["props"] = [row_to_prop(dict(p)) for p in props]
    return drama


def list_dramas(db: Session, query: dict) -> tuple[list, int, int, int]:
    where = "FROM dramas WHERE deleted_at IS NULL"
    params: dict = {}
    if query.get("status"):
        where += " AND status = :status"
        params["status"] = query["status"]
    if query.get("genre"):
        where += " AND genre = :genre"
        params["genre"] = query["genre"]
    if query.get("keyword"):
        where += " AND (title LIKE :kw1 OR description LIKE :kw2)"
        k = f"%{query['keyword']}%"
        params["kw1"] = k
        params["kw2"] = k

    total = db.execute(text(f"SELECT COUNT(*) AS total {where}"), params).scalar() or 0
    page = max(1, js_parse_int(query.get("page"), 1))
    page_size = min(100, max(1, js_parse_int(query.get("page_size"), 20)))
    offset = (page - 1) * page_size
    p = dict(params)
    p["_limit"] = page_size
    p["_offset"] = offset
    rows = db.execute(text(f"SELECT * {where} ORDER BY updated_at DESC LIMIT :_limit OFFSET :_offset"), p).mappings().all()
    dramas = [row_to_drama(dict(r)) for r in rows]

    for d in dramas:
        eps = db.execute(
            text("SELECT * FROM episodes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY episode_number ASC"),
            {"did": d["id"]},
        ).mappings().all()
        ep_list = []
        for e in eps:
            ep = row_to_episode(dict(e))
            sbs = db.execute(
                text(
                    "SELECT * FROM storyboards WHERE episode_id = :ep AND deleted_at IS NULL "
                    "ORDER BY storyboard_number ASC, id ASC"
                ),
                {"ep": ep["id"]},
            ).mappings().all()
            storyboards = dedupe_storyboard_rows_by_number([row_to_storyboard(dict(s)) for s in sbs])
            ep["storyboards"] = storyboards
            _attach_storyboard_prop_ids(db, storyboards)
            ep["duration"] = sum((s.get("duration") or 0) for s in storyboards)
            if ep["duration"] > 0:
                ep["duration"] = math.ceil(ep["duration"] / 60)
            ep_list.append(ep)
        d["episodes"] = ep_list
    return dramas, total, page, page_size


def update_drama(db: Session, drama_id, req: dict) -> dict | None:
    drama = get_drama_by_id(db, drama_id)
    if not drama:
        return None
    updates: list[str] = []
    params: dict = {}
    if req.get("title") is not None:
        updates.append("title = :title")
        params["title"] = req["title"]
    if req.get("description") is not None:
        updates.append("description = :description")
        params["description"] = req["description"] or None
    if req.get("genre") is not None:
        updates.append("genre = :genre")
        params["genre"] = req["genre"] or None
    if req.get("status") is not None:
        updates.append("status = :status")
        params["status"] = req["status"]
    if not updates:
        return drama
    params["updated_at"] = timestamp()
    params["id"] = to_int_id(drama_id)
    db.execute(text(f"UPDATE dramas SET {', '.join(updates)}, updated_at = :updated_at WHERE id = :id"), params)
    log.info("Drama updated", extra={"drama_id": drama_id})
    return get_drama_by_id(db, drama_id)


def delete_drama(db: Session, drama_id) -> bool:
    result = db.execute(
        text("UPDATE dramas SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL"),
        {"now": timestamp(), "id": to_int_id(drama_id)},
    )
    if result.rowcount == 0:
        return False
    log.info("Drama deleted", extra={"drama_id": drama_id})
    return True


def get_drama_stats(db: Session) -> dict:
    total = db.execute(text("SELECT COUNT(*) AS c FROM dramas WHERE deleted_at IS NULL")).scalar() or 0
    rows = db.execute(
        text("SELECT status, COUNT(*) AS count FROM dramas WHERE deleted_at IS NULL GROUP BY status")
    ).mappings().all()
    return {"total": total, "by_status": [dict(r) for r in rows]}


# ---------------- 保存类操作 ----------------


def save_outline(db: Session, drama_id, req: dict) -> bool:
    drama = get_drama_by_id(db, drama_id)
    if not drama:
        return False
    now = timestamp()
    tags_str = json.dumps(req["tags"]) if isinstance(req.get("tags"), list) else None

    existing_metadata = parse_metadata(drama.get("metadata"))
    new_metadata = parse_metadata(req.get("metadata")) if req.get("metadata") else {}
    merged = {**existing_metadata, **new_metadata}

    if req.get("style") is not None:
        style_val = str(req.get("style") or "").strip()
        has_explicit = (
            isinstance(req.get("metadata"), dict)
            and not isinstance(req.get("metadata"), list)
            and ("style_prompt_zh" in req["metadata"] or "style_prompt_en" in req["metadata"])
        )
        if not has_explicit and style_val:
            preset = resolve_style_preset(style_val)
            if preset:
                merged["style_prompt_zh"] = preset["zh"]
                merged["style_prompt_en"] = preset["en"]

    db.execute(
        text(
            "UPDATE dramas SET title = :title, description = :description, genre = :genre, tags = :tags, "
            "style = :style, metadata = :metadata, updated_at = :updated_at WHERE id = :id"
        ),
        {
            "title": req.get("title") or drama["title"],
            "description": req["summary"] if req.get("summary") is not None else drama["description"],
            "genre": req["genre"] if req.get("genre") is not None else drama["genre"],
            "tags": tags_str,
            "style": req["style"] if req.get("style") is not None else drama["style"],
            "metadata": json.dumps(merged),
            "updated_at": now,
            "id": to_int_id(drama_id),
        },
    )
    log.info("Outline saved", extra={"drama_id": drama_id})
    return True


def get_characters(db: Session, drama_id, episode_id=None):
    did = to_int_id(drama_id)
    drama = get_drama_by_id(db, did)
    if not drama:
        return None
    if episode_id:
        exists = db.execute(
            text("SELECT 1 FROM episodes WHERE id = :eid AND drama_id = :did"), {"eid": episode_id, "did": did}
        ).first()
        if not exists:
            return None
        rows = db.execute(
            text(
                "SELECT c.* FROM characters c INNER JOIN episode_characters ec ON ec.character_id = c.id "
                "WHERE ec.episode_id = :eid AND c.deleted_at IS NULL ORDER BY c.sort_order ASC, c.name ASC"
            ),
            {"eid": episode_id},
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                "SELECT * FROM characters WHERE drama_id = :did AND deleted_at IS NULL "
                "ORDER BY sort_order ASC, name ASC"
            ),
            {"did": did},
        ).mappings().all()

    characters = [row_to_character(dict(r)) for r in rows]
    for c in characters:
        img = db.execute(
            text(
                "SELECT status, error_msg FROM image_generations WHERE character_id = :cid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"cid": c["id"]},
        ).mappings().first()
        if img and img["status"] in ("pending", "processing", "failed"):
            c["image_generation_status"] = img["status"]
            if img["error_msg"]:
                c["image_generation_error"] = img["error_msg"]
    return characters


def save_characters(db: Session, drama_id, req: dict) -> bool:
    did = to_int_id(drama_id)
    drama = get_drama_by_id(db, did)
    if not drama:
        return False
    if req.get("episode_id"):
        ep = db.execute(
            text("SELECT 1 FROM episodes WHERE id = :eid AND drama_id = :did"),
            {"eid": req["episode_id"], "did": did},
        ).first()
        if not ep:
            return False

    now = timestamp()
    character_ids: list[int] = []
    for char in req.get("characters") or []:
        if char.get("id"):
            ex = db.execute(
                text("SELECT id FROM characters WHERE id = :cid AND drama_id = :did"),
                {"cid": char["id"], "did": did},
            ).mappings().first()
            if ex:
                character_ids.append(ex["id"])
                img_fields: list[str] = []
                img_params: dict = {}
                if "image_url" in char:
                    img_fields.append("image_url = :image_url")
                    img_params["image_url"] = char.get("image_url")
                if "local_path" in char:
                    img_fields.append("local_path = :local_path")
                    img_params["local_path"] = char.get("local_path")
                if img_fields:
                    prev = db.execute(
                        text(
                            "SELECT id, local_path, image_url, seedance2_asset FROM characters "
                            "WHERE id = :cid AND deleted_at IS NULL"
                        ),
                        {"cid": char["id"]},
                    ).mappings().first()
                    if prev:
                        sd2.mark_stale_on_character_main_image_drift(
                            db,
                            log,
                            dict(prev),
                            {
                                "image_url": char.get("image_url") if "image_url" in char else prev["image_url"],
                                "local_path": char.get("local_path") if "local_path" in char else prev["local_path"],
                            },
                        )
                img_sql = (", " + ", ".join(img_fields)) if img_fields else ""
                set_core = "name = :name, role = :role, description = :description, personality = :personality, appearance = :appearance"
                core_params = {
                    "name": char.get("name"),
                    "role": char.get("role"),
                    "description": char.get("description"),
                    "personality": char.get("personality"),
                    "appearance": char.get("appearance"),
                }
                if "negative_prompt" in char:
                    set_core += ", negative_prompt = :negative_prompt"
                    core_params["negative_prompt"] = char.get("negative_prompt")
                params = {**core_params, **img_params, "updated_at": now, "cid": char["id"]}
                db.execute(text(f"UPDATE characters SET {set_core}{img_sql}, updated_at = :updated_at WHERE id = :cid"), params)
                continue

        by_name = db.execute(
            text("SELECT id FROM characters WHERE drama_id = :did AND name = :name"),
            {"did": did, "name": char.get("name")},
        ).mappings().first()
        if by_name:
            character_ids.append(by_name["id"])
            img_fields = []
            img_params = {}
            if "image_url" in char:
                img_fields.append("image_url = :image_url")
                img_params["image_url"] = char.get("image_url")
            if "local_path" in char:
                img_fields.append("local_path = :local_path")
                img_params["local_path"] = char.get("local_path")
            if img_fields:
                prev = db.execute(
                    text("SELECT id, local_path, image_url, seedance2_asset FROM characters WHERE id = :cid"),
                    {"cid": by_name["id"]},
                ).mappings().first()
                if prev:
                    sd2.mark_stale_on_character_main_image_drift(
                        db,
                        log,
                        dict(prev),
                        {
                            "image_url": char.get("image_url") if "image_url" in char else prev["image_url"],
                            "local_path": char.get("local_path") if "local_path" in char else prev["local_path"],
                        },
                    )
            img_sql = (", " + ", ".join(img_fields)) if img_fields else ""
            set_core = "role = :role, description = :description, personality = :personality, appearance = :appearance"
            core_params = {
                "role": char.get("role"),
                "description": char.get("description"),
                "personality": char.get("personality"),
                "appearance": char.get("appearance"),
            }
            if "negative_prompt" in char:
                set_core += ", negative_prompt = :negative_prompt"
                core_params["negative_prompt"] = char.get("negative_prompt")
            params = {**core_params, **img_params, "updated_at": now, "cid": by_name["id"]}
            db.execute(
                text(f"UPDATE characters SET {set_core}{img_sql}, updated_at = :updated_at, deleted_at = NULL WHERE id = :cid"),
                params,
            )
            continue

        res = db.execute(
            text(
                "INSERT INTO characters (drama_id, name, role, description, personality, appearance, image_url, "
                "local_path, negative_prompt, sort_order, created_at, updated_at) "
                "VALUES (:did, :name, :role, :description, :personality, :appearance, :image_url, :local_path, "
                ":negative_prompt, 0, :created_at, :updated_at)"
            ),
            {
                "did": did,
                "name": char.get("name"),
                "role": char.get("role"),
                "description": char.get("description"),
                "personality": char.get("personality"),
                "appearance": char.get("appearance"),
                "image_url": char.get("image_url"),
                "local_path": char.get("local_path"),
                "negative_prompt": char.get("negative_prompt"),
                "created_at": now,
                "updated_at": now,
            },
        )
        character_ids.append(res.lastrowid)

    if req.get("episode_id") and character_ids:
        eid = req["episode_id"]
        db.execute(text("DELETE FROM episode_characters WHERE episode_id = :eid"), {"eid": eid})
        for cid in character_ids:
            db.execute(
                text("INSERT IGNORE INTO episode_characters (episode_id, character_id) VALUES (:eid, :cid)"),
                {"eid": eid, "cid": cid},
            )

    db.execute(
        text("UPDATE dramas SET updated_at = :now WHERE id = :id"), {"now": now, "id": did}
    )
    log.info("Characters saved", extra={"drama_id": drama_id})
    return True


def save_episodes(db: Session, drama_id, req: dict) -> bool:
    did = to_int_id(drama_id)
    drama = get_drama_by_id(db, did)
    if not drama:
        return False
    episodes = req.get("episodes") or []
    now = timestamp()

    kept_numbers = set()
    for ep in episodes:
        num = ep.get("episode_number") if ep.get("episode_number") is not None else 0
        kept_numbers.add(num)
        existing = db.execute(
            text(
                "SELECT id FROM episodes WHERE drama_id = :did AND episode_number = :num "
                "ORDER BY deleted_at IS NOT NULL ASC, id ASC LIMIT 1"
            ),
            {"did": did, "num": num},
        ).mappings().first()
        if existing:
            db.execute(
                text(
                    "UPDATE episodes SET title = :title, script_content = :script_content, description = :description, "
                    "duration = :duration, deleted_at = NULL, updated_at = :updated_at WHERE id = :id"
                ),
                {
                    "title": ep.get("title") or "",
                    "script_content": ep.get("script_content"),
                    "description": ep.get("description"),
                    "duration": ep.get("duration") if ep.get("duration") is not None else 0,
                    "updated_at": now,
                    "id": existing["id"],
                },
            )
        else:
            db.execute(
                text(
                    "INSERT INTO episodes (drama_id, episode_number, title, script_content, description, duration, "
                    "status, created_at, updated_at) VALUES (:did, :num, :title, :script_content, :description, "
                    ":duration, 'draft', :created_at, :updated_at)"
                ),
                {
                    "did": did,
                    "num": num,
                    "title": ep.get("title") or "",
                    "script_content": ep.get("script_content"),
                    "description": ep.get("description"),
                    "duration": ep.get("duration") if ep.get("duration") is not None else 0,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    live = db.execute(
        text("SELECT id, episode_number FROM episodes WHERE drama_id = :did AND deleted_at IS NULL"), {"did": did}
    ).mappings().all()
    for row in live:
        if row["episode_number"] not in kept_numbers:
            db.execute(text("UPDATE episodes SET deleted_at = :now WHERE id = :id"), {"now": now, "id": row["id"]})

    db.execute(text("UPDATE dramas SET updated_at = :now WHERE id = :id"), {"now": now, "id": did})
    log.info("Episodes saved", extra={"drama_id": drama_id})
    return True


def save_progress(db: Session, drama_id, req: dict) -> bool:
    drama = get_drama_by_id(db, drama_id)
    if not drama:
        return False
    meta = parse_metadata(drama.get("metadata"))
    meta["current_step"] = req.get("current_step")
    if req.get("step_data") is not None:
        meta["step_data"] = req["step_data"]
    now = timestamp()
    db.execute(
        text("UPDATE dramas SET metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"metadata": json.dumps(meta), "now": now, "id": to_int_id(drama_id)},
    )
    log.info("Progress saved", extra={"drama_id": drama_id})
    return True


def save_canvas_layout(db: Session, drama_id, req: dict):
    drama = get_drama_by_id(db, drama_id)
    if not drama:
        return None
    layout = req.get("canvas_layout")
    # Node 用 === undefined 判断「未传」：显式 null 与缺失语义不同，需区分键存在性
    has_workflow_groups = "workflow_groups" in req
    workflow_groups = req.get("workflow_groups")

    def bad(msg: str) -> Exception:
        e = ValueError(msg)
        e.code = "BAD_REQUEST"  # type: ignore[attr-defined]
        return e

    layout_invalid = layout is None or not isinstance(layout, dict)
    if layout_invalid and not has_workflow_groups:
        raise bad("请提供 canvas_layout 或 workflow_groups")
    if layout is not None and not isinstance(layout, dict):
        raise bad("canvas_layout 必须为对象")
    if has_workflow_groups and not isinstance(workflow_groups, list):
        raise bad("workflow_groups 必须为数组")

    meta = parse_metadata(drama.get("metadata"))
    if layout is not None:
        meta["canvas_layout"] = layout
    if has_workflow_groups:
        meta["workflow_groups"] = workflow_groups
    now = timestamp()
    db.execute(
        text("UPDATE dramas SET metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"metadata": json.dumps(meta), "now": now, "id": to_int_id(drama_id)},
    )
    log.info("Canvas state saved", extra={"drama_id": drama_id})
    return get_drama(db, drama_id)


# ---------------- P4/P5：合成 / 下载 / 纯 AI 占位 ----------------


def get_video_url_for_storyboard(db: Session, storyboard_id: int, base_url: str) -> str | None:
    """等价 Node getVideoUrlForStoryboard：优先本地路径，比较时间取最新。"""
    sb = fetch_one(
        db,
        "SELECT video_url, local_path, updated_at FROM storyboards WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(storyboard_id)},
    )
    vg = fetch_one(
        db,
        "SELECT video_url, local_path, completed_at, updated_at, created_at FROM video_generations "
        "WHERE storyboard_id = :sid AND status = 'completed' AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1",
        {"sid": to_int_id(storyboard_id)},
    )

    def build_url(video_url, local_path):
        if local_path and str(local_path).strip() and base_url:
            base = (base_url or "").rstrip("/")
            p = str(local_path).lstrip("/")
            return base + "/" + p if p else None
        if video_url and str(video_url).strip():
            return video_url
        return None

    sb_url = build_url(sb.get("video_url") if sb else None, sb.get("local_path") if sb else None)
    vg_url = build_url(vg.get("video_url") if vg else None, vg.get("local_path") if vg else None)

    if sb_url and not vg_url:
        return sb_url
    if not sb_url and vg_url:
        return vg_url
    if not sb_url and not vg_url:
        return None

    sb_time = (sb.get("updated_at") if sb else None) or "1970-01-01"
    vg_time = (
        vg.get("completed_at") or vg.get("updated_at") or vg.get("created_at") or "1970-01-01"
    ) if vg else "1970-01-01"

    if vg_time > sb_time:
        return vg_url
    return sb_url


def finalize_episode(
    db: Session, log, episode_id: str, base_url: str, body: dict | None = None, storage_root: str = ""
) -> dict | None:
    """等价 Node finalizeEpisode。返回 null 表示剧集不存在；其余返回合成任务信息。

    Node 在返回前用 setImmediate 触发 processVideoMerge（后台完成合成并写 episodes.video_url）。
    此处等价调用 vm_svc.process_video_merge（同步执行，保证契约可见的 episodes.video_url 一致）。
    """
    body = body or {}
    ep = fetch_one(
        db,
        "SELECT id, drama_id, episode_number FROM episodes WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(episode_id)},
    )
    if not ep:
        return None
    drama = fetch_one(
        db,
        "SELECT title FROM dramas WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(ep["drama_id"])},
    )
    storyboards = fetch_all(
        db,
        "SELECT id, storyboard_number, duration, local_path FROM storyboards WHERE episode_id = :eid "
        "AND deleted_at IS NULL ORDER BY storyboard_number ASC",
        {"eid": to_int_id(episode_id)},
    )
    scenes = []
    for i, sb in enumerate(storyboards):
        video_url = get_video_url_for_storyboard(db, sb["id"], base_url)
        if not video_url:
            log.warning("Finalize skip storyboard (no video)", extra={"storyboard_id": sb["id"]})
            continue
        scenes.append({
            "scene_id": sb["id"],
            "video_url": video_url,
            "local_path": sb.get("local_path"),
            "duration": float(sb["duration"]) if sb.get("duration") is not None else 5,
            "order": i,
        })
    if len(scenes) == 0:
        log.warning("Finalize no scenes with video", extra={"episode_id": episode_id})
        return {
            "message": "本集没有可合成的视频片段",
            "merge_id": None,
            "episode_id": episode_id,
            "scenes_count": 0,
            "task_id": None,
        }
    title = f"{drama['title']} - 第{ep.get('episode_number') or episode_id}集" if drama and drama.get("title") else None
    merge_req = {
        "episode_id": episode_id,
        "drama_id": ep["drama_id"],
        "title": title,
        "scenes": scenes,
        "provider": "ffmpeg",
        "merge_options": {
            "burn_narration_subtitles": bool(body.get("burn_narration_subtitles")),
            "burn_dialogue_audio": bool(body.get("burn_dialogue_audio")),
            "watermark_text": str(body["watermark_text"]).strip()[:200]
            if body.get("watermark_text") is not None else "",
        },
    }
    created = vm_svc.create_merge(db, log, merge_req)
    merge_id = created.get("merge_id") or created.get("id")
    db.execute(
        text("UPDATE episodes SET status = :status WHERE id = :id"),
        {"status": "processing", "id": to_int_id(episode_id)},
    )
    # 等价 Node setImmediate(processVideoMerge)：完成后写 episodes.video_url / status='completed'
    try:
        vm_svc.process_video_merge(db, log, merge_id, storage_root)
    except Exception as e:  # noqa: BLE001
        log.warning("Finalize process merge failed", extra={"error": str(e), "merge_id": merge_id})
    return {
        "message": "视频合成任务已创建，正在后台处理",
        "merge_id": merge_id,
        "episode_id": episode_id,
        "scenes_count": len(scenes),
        "task_id": created.get("task_id"),
    }


def download_episode_video(db: Session, episode_id: str) -> dict | None:
    """等价 Node downloadEpisodeVideo。返回 null=剧集不存在；{error}=无视频。"""
    ep = fetch_one(
        db,
        "SELECT id, title, episode_number, video_url FROM episodes WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(episode_id)},
    )
    if not ep:
        return None
    if not ep.get("video_url"):
        return {"error": "该剧集还没有生成视频"}
    return {
        "video_url": ep["video_url"],
        "title": ep["title"],
        "episode_number": ep["episode_number"],
    }


def generate_storyboard(db: Session, log, episode_id: str, options: dict) -> dict:
    from app.services import episodeStoryboardService

    opts = options or {}
    model = opts.get("model")
    style = opts.get("style")
    storyboard_count = opts.get("storyboard_count")
    video_duration = opts.get("video_duration")
    aspect_ratio = opts.get("aspect_ratio")
    include_narration = opts.get("include_narration")
    universal_omni_storyboard = opts.get("universal_omni_storyboard")

    count = int(storyboard_count) if storyboard_count is not None and str(storyboard_count).strip() else None
    duration = int(video_duration) if video_duration is not None and str(video_duration).strip() else None

    return episodeStoryboardService.generate_storyboard(
        db,
        log,
        episode_id,
        model=model or None,
        style=style,
        storyboard_count=count,
        video_duration=duration,
        aspect_ratio=aspect_ratio,
        include_narration=include_narration,
        universal_omni=universal_omni_storyboard,
    )
