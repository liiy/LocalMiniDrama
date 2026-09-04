"""分镜（storyboards 表）CRUD，等价 Node services/storyboardService.js 的纯 CRUD 部分。

P2 翻译：getStoryboardById / createStoryboard / updateStoryboard / insertBeforeStoryboard / deleteStoryboard。
AI 相关（帧提示词生成、润色流式）留到 P4。
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp

log = get_logger("lmd.storyboard")

# Node updateStoryboard 的白名单字段（顺序一致）
ALLOWED_UPDATE_FIELDS = [
    "title", "description", "location", "time", "duration", "dialogue", "narration", "action",
    "result", "atmosphere", "image_prompt", "polished_prompt", "video_prompt", "scene_id",
    "characters", "composed_image", "image_url", "local_path", "main_panel_idx", "video_url",
    "audio_local_path", "narration_audio_local_path", "status", "shot_type", "angle",
    "angle_h", "angle_v", "angle_s", "movement", "segment_index", "segment_title",
    "creation_mode", "universal_segment_text", "layout_description", "first_frame_image_id",
    "last_frame_image_id", "last_frame_image_url", "last_frame_local_path",
]


def to_int_id(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def parse_drama_character_ids(characters_value):
    """等价 Node parseDramaCharacterIds：返回 id 列表或 None（undefined/null 时）。"""
    if characters_value is None:
        return None
    if isinstance(characters_value, list):
        out = []
        for x in characters_value:
            v = x["id"] if isinstance(x, dict) else x
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f == f and f not in (float("inf"), float("-inf")):
                out.append(f)
        return out
    if isinstance(characters_value, str):
        try:
            arr = json.loads(characters_value)
        except Exception:
            return []
        if not isinstance(arr, list):
            return []
        out = []
        for x in arr:
            v = x["id"] if isinstance(x, dict) else x
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f == f and f not in (float("inf"), float("-inf")):
                out.append(f)
        return out
    return []


def get_storyboard_by_id(db: Session, storyboard_id):
    r = db.execute(
        text("SELECT * FROM storyboards WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(storyboard_id)}
    ).mappings().first()
    if not r:
        return None
    characters: list = []
    if r["characters"]:
        if isinstance(r["characters"], str):
            try:
                characters = json.loads(r["characters"])
            except Exception:
                characters = []
        elif isinstance(r["characters"], list):
            characters = r["characters"]
    prop_ids: list = []
    try:
        links = db.execute(
            text("SELECT prop_id FROM storyboard_props WHERE storyboard_id = :id"), {"id": to_int_id(storyboard_id)}
        ).mappings().all()
        prop_ids = [p["prop_id"] for p in links]
    except Exception:
        pass

    return {
        "id": r["id"],
        "episode_id": r["episode_id"],
        "scene_id": r["scene_id"],
        "storyboard_number": r["storyboard_number"],
        "title": r["title"],
        "description": r["description"],
        "location": r["location"],
        "time": r["time"],
        "duration": r["duration"] if r["duration"] is not None else 0,
        "dialogue": r["dialogue"],
        "narration": r["narration"],
        "action": r["action"],
        "result": r["result"],
        "atmosphere": r["atmosphere"],
        "image_prompt": r["image_prompt"],
        "polished_prompt": r["polished_prompt"],
        "video_prompt": r["video_prompt"],
        "shot_type": r["shot_type"],
        "angle": r["angle"],
        "angle_h": r["angle_h"],
        "angle_v": r["angle_v"],
        "angle_s": r["angle_s"],
        "movement": r["movement"],
        "segment_index": r["segment_index"] if r["segment_index"] is not None else 0,
        "segment_title": r["segment_title"],
        "creation_mode": "universal" if r["creation_mode"] == "universal" else "classic",
        "universal_segment_text": r["universal_segment_text"],
        "layout_description": r["layout_description"],
        "first_frame_image_id": r["first_frame_image_id"],
        "last_frame_image_id": r["last_frame_image_id"],
        "last_frame_image_url": r["last_frame_image_url"],
        "last_frame_local_path": r["last_frame_local_path"],
        "characters": characters,
        "prop_ids": prop_ids,
        "composed_image": r["composed_image"],
        "image_url": r["image_url"],
        "local_path": r["local_path"],
        "main_panel_idx": int(r["main_panel_idx"]) if r["main_panel_idx"] is not None else None,
        "video_url": r["video_url"],
        "audio_local_path": r["audio_local_path"],
        "narration_audio_local_path": r["narration_audio_local_path"],
        "status": r["status"] or "pending",
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def create_storyboard(db: Session, req: dict):
    now = timestamp()
    res = db.execute(
        text(
            """
            INSERT INTO storyboards (episode_id, scene_id, storyboard_number, title, description, location,
                time, duration, dialogue, action, result, atmosphere, image_prompt, video_prompt, status,
                created_at, updated_at)
            VALUES (:episode_id, :scene_id, :storyboard_number, :title, :description, :location, :time,
                :duration, :dialogue, :action, :result, :atmosphere, :image_prompt, :video_prompt, 'pending',
                :created_at, :updated_at)
            """
        ),
        {
            "episode_id": to_int_id(req["episode_id"]) if req.get("episode_id") is not None else 0,
            "scene_id": req.get("scene_id"),
            "storyboard_number": req.get("storyboard_number") or 0,
            "title": req.get("title"),
            "description": req.get("description"),
            "location": req.get("location"),
            "time": req.get("time"),
            "duration": req.get("duration") if req.get("duration") is not None else 0,
            "dialogue": req.get("dialogue"),
            "action": req.get("action"),
            "result": req.get("result"),
            "atmosphere": req.get("atmosphere"),
            "image_prompt": req.get("image_prompt"),
            "video_prompt": req.get("video_prompt"),
            "created_at": now,
            "updated_at": now,
        },
    )
    log.info("Storyboard created", extra={"id": res.lastrowid, "episode_id": req.get("episode_id")})
    return get_storyboard_by_id(db, res.lastrowid)


def sync_storyboard_character_links(db: Session, storyboard_id, drama_character_ids) -> None:
    """等价 Node syncStoryboardCharacterLinks：按角色名匹配 character_libraries 后写入关联。"""
    sid = to_int_id(storyboard_id)
    db.execute(text("DELETE FROM storyboard_characters WHERE storyboard_id = :sid"), {"sid": sid})
    if not isinstance(drama_character_ids, list):
        return
    ids = [n for n in (float(x) if x is not None else float("nan") for x in drama_character_ids) if n == n]
    if not ids:
        return
    sb = db.execute(
        text(
            "SELECT e.drama_id FROM storyboards s JOIN episodes e ON e.id = s.episode_id "
            "WHERE s.id = :sid AND s.deleted_at IS NULL"
        ),
        {"sid": sid},
    ).mappings().first()
    drama_id = int(sb["drama_id"]) if sb and sb["drama_id"] is not None else None
    now = timestamp()
    for cid in ids[:20]:
        crow = db.execute(
            text("SELECT name FROM characters WHERE id = :cid AND deleted_at IS NULL"), {"cid": int(cid)}
        ).mappings().first()
        name = (crow["name"] or "").strip() if crow else ""
        if not name:
            continue
        lib = None
        if drama_id:
            lib = db.execute(
                text(
                    "SELECT id FROM character_libraries WHERE deleted_at IS NULL AND drama_id = :did "
                    "AND TRIM(name) = :name LIMIT 1"
                ),
                {"did": drama_id, "name": name},
            ).mappings().first()
        if not lib:
            lib = db.execute(
                text(
                    "SELECT id FROM character_libraries WHERE deleted_at IS NULL AND drama_id IS NULL "
                    "AND TRIM(name) = :name LIMIT 1"
                ),
                {"name": name},
            ).mappings().first()
        if lib:
            db.execute(
                text(
                    "INSERT IGNORE INTO storyboard_characters (storyboard_id, character_id, created_at) "
                    "VALUES (:sid, :cid, :now)"
                ),
                {"sid": sid, "cid": lib["id"], "now": now},
            )


def update_storyboard(db: Session, storyboard_id, req: dict):
    sid = to_int_id(storyboard_id)
    exists = db.execute(
        text("SELECT id FROM storyboards WHERE id = :id AND deleted_at IS NULL"), {"id": sid}
    ).first()
    if not exists:
        return None

    updates: list[str] = []
    params: dict = {}
    # 前端可能传 character_ids，与 characters 统一：存为 JSON 字符串
    characters_value = req["character_ids"] if "character_ids" in req else req.get("characters")
    parsed_ids = None
    if "character_ids" in req or "characters" in req:
        updates.append("characters = :characters")
        if isinstance(characters_value, list):
            json_str = json.dumps(characters_value)
        elif isinstance(characters_value, str):
            json_str = characters_value
        else:
            json_str = "[]"
        params["characters"] = json_str
        parsed_ids = parse_drama_character_ids(characters_value) or []

    for key in ALLOWED_UPDATE_FIELDS:
        if key == "characters":
            continue
        if key in req:
            updates.append(f"{key} = :f_{key}")
            params[f"f_{key}"] = req[key]

    if not updates and "prop_ids" not in req:
        return get_storyboard_by_id(db, sid)

    if updates:
        params["updated_at"] = timestamp()
        params["sid"] = sid
        db.execute(
            text(f"UPDATE storyboards SET {', '.join(updates)}, updated_at = :updated_at WHERE id = :sid"), params
        )

    if parsed_ids is not None:
        try:
            sync_storyboard_character_links(db, sid, parsed_ids)
        except Exception as e:
            # 注意：extra 的键不能用 message/msg——它们是 LogRecord 保留属性，会抛
            # KeyError: Attempt to overwrite 'message' in LogRecord，导致异常处理器自身崩溃。
            log.warning("syncStoryboardCharacterLinks failed", extra={"id": sid, "reason": str(e)})

    if "prop_ids" in req:
        prop_ids = req["prop_ids"] if isinstance(req["prop_ids"], list) else []
        db.execute(text("DELETE FROM storyboard_props WHERE storyboard_id = :sid"), {"sid": sid})
        for pid in prop_ids:
            db.execute(
                text("INSERT IGNORE INTO storyboard_props (storyboard_id, prop_id) VALUES (:sid, :pid)"),
                {"sid": sid, "pid": to_int_id(pid)},
            )

    log.info("Storyboard updated", extra={"id": sid})
    return get_storyboard_by_id(db, sid)


def insert_before_storyboard(db: Session, target_id):
    target = db.execute(
        text(
            "SELECT id, episode_id, storyboard_number, segment_index, segment_title FROM storyboards "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": to_int_id(target_id)},
    ).mappings().first()
    if not target:
        return None
    db.execute(
        text(
            "UPDATE storyboards SET storyboard_number = storyboard_number + 1, updated_at = :now "
            "WHERE episode_id = :ep AND storyboard_number >= :num AND deleted_at IS NULL"
        ),
        {"now": timestamp(), "ep": target["episode_id"], "num": target["storyboard_number"]},
    )
    now = timestamp()
    res = db.execute(
        text(
            """
            INSERT INTO storyboards (episode_id, storyboard_number, segment_index, segment_title, status,
                created_at, updated_at)
            VALUES (:ep, :num, :seg_idx, :seg_title, 'pending', :created_at, :updated_at)
            """
        ),
        {
            "ep": target["episode_id"],
            "num": target["storyboard_number"],
            "seg_idx": target["segment_index"],
            "seg_title": target["segment_title"],
            "created_at": now,
            "updated_at": now,
        },
    )
    log.info("Storyboard inserted before", extra={"new_id": res.lastrowid, "before_id": target_id})
    return get_storyboard_by_id(db, res.lastrowid)


def delete_storyboard(db: Session, storyboard_id) -> bool:
    res = db.execute(
        text("UPDATE storyboards SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL"),
        {"now": timestamp(), "id": to_int_id(storyboard_id)},
    )
    if res.rowcount == 0:
        return False
    log.info("Storyboard deleted", extra={"id": storyboard_id})
    return True


# ---------------- 剧集维度：等价 Node episodeStoryboardService.getStoryboardsForEpisode ----------------


def normalize_storyboard_shot_number(raw) -> int:
    """等价 Node normalizeStoryboardShotNumber：非正数/非数字统一为 0。"""
    try:
        n = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    if n != n or n in (float("inf"), float("-inf")):
        return 0
    return int(n) if n > 0 else 0


def normalize_duration(v) -> int:
    """等价 Node normalizeDuration：'5s'→5，非法→0。"""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(round(v)) if v == v and v not in (float("inf"), float("-inf")) else 0
    s = str(v).strip()
    if s.lower().endswith("s"):
        s = s[:-1]
    try:
        n = float(s)
    except (TypeError, ValueError):
        return 0
    return int(round(n)) if n == n and n >= 0 else 0


def _dedupe_storyboard_rows_by_number(rows: list) -> list:
    """等价 Node dedupeStoryboardRowsByNumber：同号保留 id 最大者，0/非法号置末尾。"""
    by_num: dict = {}
    extras: list = []
    for r in rows or []:
        num = normalize_storyboard_shot_number(r.get("storyboard_number"))
        if num > 0:
            prev = by_num.get(num)
            if prev is None or int(r["id"]) > int(prev["id"]):
                by_num[num] = r
        else:
            extras.append(r)
    merged = list(by_num.values()) + extras
    merged.sort(
        key=lambda r: (
            normalize_storyboard_shot_number(r.get("storyboard_number")),
            int(r["id"]),
        )
    )
    return merged


def _row_to_scene(r) -> dict:
    """等价 Node episodeStoryboardService.rowToScene（注意与 sceneService.getSceneById 字段不同）。"""
    if not r:
        return None
    return {
        "id": r["id"],
        "drama_id": r["drama_id"],
        "location": r["location"],
        "time": r["time"],
        "prompt": r["prompt"],
        "storyboard_count": r["storyboard_count"] if r["storyboard_count"] is not None else 1,
        "image_url": r["image_url"],
        "local_path": r["local_path"],
        "status": r["status"] or "pending",
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def get_storyboards_for_episode(db: Session, episode_id) -> list:
    """等价 Node getStoryboardsForEpisode：去重 + normalizeDuration + 内联 background 场景。"""
    rows = db.execute(
        text("SELECT * FROM storyboards WHERE episode_id = :eid AND deleted_at IS NULL "
             "ORDER BY storyboard_number ASC, id ASC"),
        {"eid": to_int_id(episode_id)},
    ).mappings().all()
    out = []
    for r in _dedupe_storyboard_rows_by_number(list(rows)):
        background = None
        if r.get("scene_id") is not None:
            scene_row = db.execute(
                text("SELECT * FROM scenes WHERE id = :id AND deleted_at IS NULL"),
                {"id": to_int_id(r["scene_id"])},
            ).mappings().first()
            if scene_row:
                background = _row_to_scene(scene_row)
        characters: list = []
        raw_chars = r.get("characters")
        if raw_chars:
            if isinstance(raw_chars, str):
                try:
                    parsed = json.loads(raw_chars)
                    characters = parsed if isinstance(parsed, list) else []
                except Exception:
                    characters = []
            elif isinstance(raw_chars, list):
                characters = raw_chars
        out.append({
            "id": r["id"],
            "episode_id": r["episode_id"],
            "scene_id": r["scene_id"],
            "storyboard_number": r["storyboard_number"],
            "title": r["title"],
            "description": r["description"],
            "location": r["location"],
            "time": r["time"],
            "duration": normalize_duration(r["duration"]),
            "dialogue": r["dialogue"],
            "narration": r["narration"],
            "action": r["action"],
            "result": r["result"],
            "atmosphere": r["atmosphere"],
            "image_prompt": r["image_prompt"],
            "video_prompt": r["video_prompt"],
            "shot_type": r["shot_type"],
            "angle": r["angle"],
            "angle_h": r["angle_h"],
            "angle_v": r["angle_v"],
            "angle_s": r["angle_s"],
            "movement": r["movement"],
            "segment_index": r["segment_index"] if r["segment_index"] is not None else 0,
            "segment_title": r["segment_title"],
            "creation_mode": "universal" if r["creation_mode"] == "universal" else "classic",
            "universal_segment_text": r["universal_segment_text"],
            "characters": characters,
            "composed_image": r["composed_image"],
            "video_url": r["video_url"],
            "audio_local_path": r["audio_local_path"],
            "narration_audio_local_path": r["narration_audio_local_path"],
            "status": r["status"] or "pending",
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "background": background,
        })
    return out
