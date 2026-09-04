"""全能片段用户消息构建 — 契约翻译 backend-node/src/services/universalSegmentPromptBundle.js。

纯 DB + 字符串逻辑（无 AI），完整移植以便校验分支与 Node 完全一致：
- not_found: 分镜不存在
- bad_request: 无参考图槽位（且未强制无图）
- bad_request: 分镜中暂无可用信息

调用方（端点）在 built.ok 后接 AI，AI 部分未移植。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one

_SB_COLUMNS = """
    id, episode_id, storyboard_number, scene_id, title, description, location, time,
    action, dialogue, narration, result, atmosphere,
    image_prompt, polished_prompt, video_prompt, universal_segment_text,
    shot_type, angle, angle_h, angle_v, angle_s, movement, lighting_style, depth_of_field,
    characters, local_path, duration, segment_index, segment_title
"""


def _chunk(k: str, v: Any) -> Optional[str]:
    s = str(v).strip() if v is not None and str(v).strip() else ""
    return f"{k}: {s}" if s else None


def _has_media_ref(row: Optional[dict]) -> bool:
    if not row:
        return False
    return str(row.get("local_path") or "").strip() != "" or str(row.get("image_url") or "").strip() != ""


def _clamp_sec(raw: Any, default: float) -> float:
    try:
        v = float(raw) if raw is not None else float("nan")
    except (TypeError, ValueError):
        v = float("nan")
    if v != v:  # NaN
        return default
    if v <= 0:
        return default
    return min(120.0, max(1.0, v))


def build_universal_segment_user_prompt_bundle(
    db: Session,
    sb_id: Any,
    req_body: Optional[dict] = None,
    opts: Optional[dict] = None,
    cfg: Optional[dict] = None,
) -> dict:
    body_in = req_body if isinstance(req_body, dict) else {}
    opts = opts or {}
    cfg = cfg or {}
    force_without_reference_images = bool(body_in.get("force_without_reference_images"))

    try:
        sid = int(sb_id)
    except (TypeError, ValueError):
        sid = -1
    sb = fetch_one(
        db,
        f"SELECT {_SB_COLUMNS} FROM storyboards WHERE id = :id AND deleted_at IS NULL",
        {"id": sid},
    )
    if not sb:
        return {"ok": False, "code": "not_found", "message": "分镜不存在"}

    # ── drama 元数据（风格/时长）──
    drama_row: Optional[dict] = None
    try:
        ep_row = fetch_one(
            db,
            "SELECT drama_id FROM episodes WHERE id = :id AND deleted_at IS NULL",
            {"id": sb.get("episode_id")},
        )
        if ep_row and ep_row.get("drama_id"):
            drama_row = fetch_one(
                db,
                "SELECT title, genre, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
                {"id": ep_row["drama_id"]},
            )
    except Exception:
        drama_row = None

    style_zh = ""
    style_en = ""
    try:
        st = dict((cfg.get("style") or {}))
        if drama_row and drama_row.get("style"):
            try:
                dstyle = json.loads(drama_row["style"]) if isinstance(drama_row["style"], str) else drama_row["style"]
                if isinstance(dstyle, dict):
                    st.update({k: v for k, v in dstyle.items() if v not in (None, "")})
            except Exception:
                pass
        style_en = str(st.get("default_style_en") or st.get("default_style") or "").strip()
        style_zh = str(st.get("default_style_zh") or "").strip()
    except Exception:
        pass

    universal_for_line = (
        opts["universalSegmentOverride"]
        if opts.get("universalSegmentOverride") is not None
        else sb.get("universal_segment_text")
    )

    lines = [
        _chunk("TITLE", sb.get("title")),
        _chunk("DESCRIPTION", sb.get("description")),
        _chunk("LOCATION", sb.get("location")),
        _chunk("TIME", sb.get("time")),
        _chunk("ACTION", sb.get("action")),
        _chunk("DIALOGUE", sb.get("dialogue")),
        _chunk("NARRATION", sb.get("narration")),
        _chunk("RESULT", sb.get("result")),
        _chunk("ATMOSPHERE", sb.get("atmosphere")),
        _chunk("IMAGE_PROMPT", sb.get("image_prompt")),
        _chunk("POLISHED_IMAGE_PROMPT", sb.get("polished_prompt")),
        _chunk("VIDEO_PROMPT", sb.get("video_prompt")),
        _chunk("SHOT_TYPE", sb.get("shot_type")),
        _chunk("ANGLE", sb.get("angle")),
        _chunk("ANGLE_H", sb.get("angle_h")),
        _chunk("ANGLE_V", sb.get("angle_v")),
        _chunk("ANGLE_S", sb.get("angle_s")),
        _chunk("MOVEMENT", sb.get("movement")),
        _chunk("LIGHTING", sb.get("lighting_style")),
        _chunk("DEPTH_OF_FIELD", sb.get("depth_of_field")),
        _chunk("CURRENT_UNIVERSAL_SEGMENT", universal_for_line),
    ]
    lines = [x for x in lines if x]

    # ── 场景块 ──
    scene_row: Optional[dict] = None
    scene_block = ""
    if sb.get("scene_id"):
        try:
            scene_row = fetch_one(
                db,
                "SELECT location, time, prompt, image_url, local_path FROM scenes WHERE id = :id AND deleted_at IS NULL",
                {"id": sb.get("scene_id")},
            )
            if scene_row:
                sc_bits = [
                    _chunk("SCENE_LOCATION", scene_row.get("location")),
                    _chunk("SCENE_TIME", scene_row.get("time")),
                    _chunk("SCENE_PROMPT", scene_row.get("prompt")),
                    "SCENE_HAS_REFERENCE_IMAGE: yes" if _has_media_ref(scene_row) else "SCENE_HAS_REFERENCE_IMAGE: no",
                ]
                scene_block = "\n".join([x for x in sc_bits if x])
        except Exception:
            scene_row = None

    # ── 角色顺序（drama: 来自分镜 characters JSON；否则 lib: 来自 storyboard_characters）──
    char_order_entries: list = []
    char_key_seen = set()

    def push_char_entry(key, name_hint):
        if not key or key in char_key_seen:
            return
        char_key_seen.add(key)
        char_order_entries.append(
            {"key": key, "nameHint": str(name_hint).strip() if name_hint is not None and str(name_hint).strip() else ""}
        )

    char_order_from_drama_json = False
    try:
        if sb.get("characters"):
            parsed = json.loads(sb["characters"]) if isinstance(sb["characters"], str) else sb["characters"]
            if isinstance(parsed, list):
                for item in parsed:
                    cid = item.get("id") if isinstance(item, dict) else item
                    try:
                        id_num = float(cid)
                    except (TypeError, ValueError):
                        continue
                    if id_num != id_num or id_num in (float("inf"), float("-inf")):
                        continue
                    nm = ""
                    if isinstance(item, dict) and item.get("name") is not None:
                        nm = str(item["name"]).strip()
                    push_char_entry(f"drama:{int(id_num)}", nm)
                if char_order_entries:
                    char_order_from_drama_json = True
        if not char_order_from_drama_json:
            lib_links = fetch_all(
                db,
                "SELECT character_id FROM storyboard_characters WHERE storyboard_id = :sid ORDER BY id ASC",
                {"sid": sid},
            )
            for link in lib_links:
                try:
                    lid = float(link.get("character_id"))
                except (TypeError, ValueError):
                    continue
                if lid != lid or lid in (float("inf"), float("-inf")):
                    continue
                push_char_entry(f"lib:{int(lid)}", "")
    except Exception:
        pass

    char_names_ordered: list = []
    name_seen = set()
    for ent in char_order_entries:
        row = None
        if ent["key"].startswith("drama:"):
            row = fetch_one(
                db,
                "SELECT name FROM characters WHERE id = :id AND deleted_at IS NULL",
                {"id": int(ent["key"][6:])},
            )
        elif ent["key"].startswith("lib:"):
            row = fetch_one(
                db,
                "SELECT name FROM character_libraries WHERE id = :id AND deleted_at IS NULL",
                {"id": int(ent["key"][4:])},
            )
        nm = str((row or {}).get("name") or ent["nameHint"] or "").strip()
        if nm and nm not in name_seen:
            name_seen.add(nm)
            char_names_ordered.append(nm)
    char_names = ", ".join(char_names_ordered)

    # ── 道具 ──
    prop_rows: list = []
    try:
        prop_rows = fetch_all(
            db,
            """
            SELECT p.id, p.name, p.local_path, p.image_url FROM storyboard_props sp
            JOIN props p ON p.id = sp.prop_id AND p.deleted_at IS NULL
            WHERE sp.storyboard_id = :sid
            ORDER BY sp.prop_id ASC
            """,
            {"sid": sid},
        ) or []
    except Exception:
        prop_rows = []

    prop_names_ordered: list = []
    prop_seen = set()
    for r in prop_rows:
        n = str(r.get("name")).strip() if r.get("name") is not None and str(r.get("name")).strip() else ""
        if n and n not in prop_seen:
            prop_seen.add(n)
            prop_names_ordered.append(n)

    # ── 邻镜简述 ──
    prev_desc = "(first shot)"
    next_desc = "(last shot)"
    if sb.get("episode_id") is not None and sb.get("storyboard_number") is not None:
        prev_shot = fetch_one(
            db,
            "SELECT action, location, time FROM storyboards WHERE episode_id = :e AND storyboard_number < :n AND deleted_at IS NULL ORDER BY storyboard_number DESC LIMIT 1",
            {"e": sb.get("episode_id"), "n": sb.get("storyboard_number")},
        )
        next_shot = fetch_one(
            db,
            "SELECT action, location, time FROM storyboards WHERE episode_id = :e AND storyboard_number > :n AND deleted_at IS NULL ORDER BY storyboard_number ASC LIMIT 1",
            {"e": sb.get("episode_id"), "n": sb.get("storyboard_number")},
        )
        if prev_shot:
            prev_desc = (
                (prev_shot.get("action") or " ".join([x for x in [prev_shot.get("location"), prev_shot.get("time")] if x]))
                [:160].strip()
                or "(first shot)"
            )
        if next_shot:
            next_desc = (
                (next_shot.get("action") or " ".join([x for x in [next_shot.get("location"), next_shot.get("time")] if x]))
                [:160].strip()
                or "(last shot)"
            )

    # ── 参考图槽位 ──
    slots: list = []

    def push_slot(kind, summary):
        num = len(slots) + 1
        brief = str(summary or "").strip() or kind
        slots.append({"num": num, "tag": f"@图片{num}", "kind": kind, "summary": brief})

    if scene_row and _has_media_ref(scene_row):
        push_slot("场景", str(scene_row.get("location") or "").strip() or "场景环境")
    for ent in char_order_entries:
        row = None
        if ent["key"].startswith("drama:"):
            row = fetch_one(
                db,
                "SELECT name, local_path, image_url FROM characters WHERE id = :id AND deleted_at IS NULL",
                {"id": int(ent["key"][6:])},
            )
        elif ent["key"].startswith("lib:"):
            row = fetch_one(
                db,
                "SELECT name, local_path, image_url FROM character_libraries WHERE id = :id AND deleted_at IS NULL",
                {"id": int(ent["key"][4:])},
            )
        if not _has_media_ref(row):
            continue
        push_slot("角色", str(row.get("name") or ent["nameHint"] or "角色").strip())
    for pr in prop_rows:
        if not _has_media_ref(pr):
            continue
        push_slot("道具", str(pr.get("name") or "道具").strip())

    # ── 校验分支 1：无参考图槽位 ──
    if not slots and not force_without_reference_images:
        return {
            "ok": False,
            "code": "bad_request",
            "message": "请至少为场景、角色或道具上传一张参考图后再生成，以便对应 @图片1、@图片2 与 API 参考顺序一致",
        }

    # ── 时长 ──
    project_clip_sec = 5.0
    try:
        meta = (drama_row or {}).get("metadata")
        if meta:
            m = json.loads(meta) if isinstance(meta, str) else meta
            if isinstance(m, dict):
                v = m.get("video_clip_duration")
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    fv = float("nan")
                if fv == fv and fv > 0:
                    project_clip_sec = min(120.0, max(1.0, fv))
    except Exception:
        pass

    body_dur = body_in.get("duration")
    sb_dur = sb.get("duration")
    if body_dur is not None and str(body_dur).strip() != "":
        duration_sec = _clamp_sec(body_dur, project_clip_sec)
    elif sb_dur is not None:
        duration_sec = _clamp_sec(sb_dur, project_clip_sec)
    else:
        duration_sec = project_clip_sec
    duration_label = str(int(duration_sec)) if float(duration_sec).is_integer() else str(round(duration_sec * 10) / 10)

    # ── 校验分支 2：无任何可用信息 ──
    if not lines and not scene_block and not char_names and not prop_names_ordered:
        return {
            "ok": False,
            "code": "bad_request",
            "message": "分镜中暂无可用信息，请先填写动作、对白、视频提示词或绑定场景/角色等",
        }

    return {
        "ok": True,
        "userPrompt": "",
        "durationLabel": duration_label,
        "durationSec": duration_sec,
        "sbId": sid,
        "episodeId": int(sb.get("episode_id") or 0),
        "storyboardNumber": int(sb.get("storyboard_number") or 0),
    }
