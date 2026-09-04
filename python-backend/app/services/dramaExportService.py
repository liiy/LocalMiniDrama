# 项目导出服务：将剧集所有数据和媒体文件打包为 ZIP
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one

EXPORT_VERSION = "1.4"


def get_storage_path(cfg: dict | None) -> str:
    raw = (cfg or {}).get("storage", {}).get("local_path") or "./data/storage"
    return os.path.abspath(raw)


def safe_read_file(file_path: str | None) -> bytes | None:
    if not file_path:
        return None
    try:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None


def local_path_to_abs(storage_path: str, rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    # 规整化路径
    clean = str(rel_path).replace("\\", "/").lstrip("/")
    return os.path.join(storage_path, clean)


def ext_of(rel_path: str | None) -> str:
    if not rel_path:
        return ".jpg"
    _, ext = os.path.splitext(rel_path)
    return ext or ".jpg"


def parse_extra_images(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        arr = json.loads(raw) if isinstance(raw, str) else raw
        return [str(x) for x in arr if x] if isinstance(arr, list) else []
    except Exception:
        return []


EXPORT_FIRST_FRAME_TYPES = ("storyboard_first", "first", "first_frame")
EXPORT_LAST_FRAME_TYPES = ("storyboard_last", "last", "tail", "last_frame")


def supplement_frame_prompts_from_image_gens(db: Session, sb_id: int, fps: list[dict]) -> list[dict]:
    out = list(fps) if isinstance(fps, list) else []
    has_type = lambda t: any(f and f.get("frame_type") == t for f in out)

    def pick_prompt(types: tuple[str, ...]) -> str:
        ph_clause = ", ".join(f":t{i}" for i in range(len(types)))
        params = {"sb_id": sb_id}
        for i, t in enumerate(types):
            params[f"t{i}"] = t
        row = fetch_one(
            db,
            f"""SELECT prompt FROM image_generations
                WHERE storyboard_id = :sb_id AND deleted_at IS NULL
                AND frame_type IN ({ph_clause}) AND prompt IS NOT NULL AND TRIM(prompt) != ''
                ORDER BY created_at DESC LIMIT 1""",
            params,
        )
        return (row.get("prompt") or "").strip() if row else ""

    now = datetime.now(timezone.utc).isoformat()
    if not has_type("first"):
        p = pick_prompt(EXPORT_FIRST_FRAME_TYPES)
        if p:
            out.append({"frame_type": "first", "prompt": p, "description": None, "layout": None, "created_at": now, "updated_at": now})
    if not has_type("last"):
        p = pick_prompt(EXPORT_LAST_FRAME_TYPES)
        if p:
            out.append({"frame_type": "last", "prompt": p, "description": None, "layout": None, "created_at": now, "updated_at": now})
    return out


def parse_sb_chars(raw: Any) -> list[int]:
    if not raw:
        return []
    try:
        arr = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(arr, list):
            res = []
            for item in arr:
                try:
                    val = int(item.get("id") if isinstance(item, dict) else item)
                    res.append(val)
                except (ValueError, TypeError):
                    pass
            return res
    except Exception:
        pass
    return []


def export_drama(db: Session, cfg: dict, log, drama_id: int | str) -> tuple[bytes, str]:
    storage_path = get_storage_path(cfg)
    did = int(drama_id)

    # 1. 读取 drama 基本信息
    drama = fetch_one(db, "SELECT * FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": did})
    if not drama:
        raise RuntimeError("剧本不存在")

    metadata = {}
    if drama.get("metadata"):
        try:
            raw_meta = drama["metadata"]
            metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
            if not isinstance(metadata, dict):
                metadata = {}
        except Exception:
            metadata = {}

    # 2. 读取所有剧集
    episodes = fetch_all(
        db,
        "SELECT * FROM episodes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY episode_number",
        {"did": did},
    )

    # 3. 读取各集分镜
    episode_ids = [e["id"] for e in episodes]
    storyboards_by_ep: dict[int, list[dict]] = {}
    for ep in episodes:
        storyboards_by_ep[ep["id"]] = fetch_all(
            db,
            "SELECT * FROM storyboards WHERE episode_id = :epid AND deleted_at IS NULL ORDER BY storyboard_number",
            {"epid": ep["id"]},
        )

    # 4. 读取分镜图和视频
    all_sbs = [sb for sbs in storyboards_by_ep.values() for sb in sbs]
    all_sb_ids = [sb["id"] for sb in all_sbs]

    all_images_by_sb: dict[int, list[dict]] = {}
    videos_by_sb: dict[int, dict] = {}
    for sb_id in all_sb_ids:
        igs = fetch_all(
            db,
            "SELECT * FROM image_generations WHERE storyboard_id = :sb_id AND deleted_at IS NULL ORDER BY created_at ASC",
            {"sb_id": sb_id},
        )
        all_images_by_sb[sb_id] = [ig for ig in igs if ig.get("local_path")]

        vg = fetch_one(
            db,
            """SELECT video_url, local_path FROM video_generations
               WHERE storyboard_id = :sb_id AND status = 'completed' AND deleted_at IS NULL
               ORDER BY created_at DESC LIMIT 1""",
            {"sb_id": sb_id},
        )
        if vg:
            videos_by_sb[sb_id] = vg

    image_files_to_pack: list[dict[str, str]] = []
    for sb_id, igs in all_images_by_sb.items():
        for ig in igs:
            lp = ig.get("local_path")
            if not lp:
                continue
            zip_path = f"media/storyboards/sb_{sb_id}_gen_{ig['id']}{ext_of(lp)}"
            image_files_to_pack.append({"local_rel_path": lp, "zip_path": zip_path})

    frame_prompts_by_sb: dict[int, list[dict]] = {}
    for sb_id in all_sb_ids:
        try:
            fps = fetch_all(
                db,
                """SELECT frame_type, prompt, description, layout, created_at, updated_at
                   FROM frame_prompts WHERE storyboard_id = :sb_id ORDER BY created_at ASC""",
                {"sb_id": sb_id},
            )
            frame_prompts_by_sb[sb_id] = supplement_frame_prompts_from_image_gens(db, sb_id, fps)
        except Exception:
            frame_prompts_by_sb[sb_id] = []

    # 5. 读取角色
    characters = fetch_all(
        db,
        "SELECT * FROM characters WHERE drama_id = :did AND deleted_at IS NULL ORDER BY sort_order, id",
        {"did": did},
    )

    # 6. 读取场景
    scenes = fetch_all(
        db,
        "SELECT * FROM scenes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id",
        {"did": did},
    )

    # 7. 读取道具
    props = fetch_all(
        db,
        "SELECT * FROM props WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id",
        {"did": did},
    )

    # 场景去重 (location | time)
    seen_scene_keys = set()
    deduped_scenes: list[dict] = []
    for s in scenes:
        key = f"{(s.get('location') or '').strip()}|{(s.get('time') or '').strip()}"
        if key in seen_scene_keys:
            continue
        seen_scene_keys.add(key)
        deduped_scenes.append(s)

    scene_dedupe_id_map: dict[int, int] = {}
    for s in scenes:
        key = f"{(s.get('location') or '').strip()}|{(s.get('time') or '').strip()}"
        kept = next((d for d in deduped_scenes if f"{(d.get('location') or '').strip()}|{(d.get('time') or '').strip()}" == key), None)
        if kept:
            scene_dedupe_id_map[s["id"]] = kept["id"]

    # 构建 ID -> 导出列表下标映射
    char_id_to_index = {c["id"]: idx for idx, c in enumerate(characters)}
    scene_id_to_index = {s["id"]: idx for idx, s in enumerate(deduped_scenes)}
    for orig_id, kept_id in scene_dedupe_id_map.items():
        if orig_id not in scene_id_to_index and kept_id in scene_id_to_index:
            scene_id_to_index[orig_id] = scene_id_to_index[kept_id]
    prop_id_to_index = {p["id"]: idx for idx, p in enumerate(props)}

    # 读取 storyboard_props
    sb_prop_ids: dict[int, list[int]] = {}
    if all_sb_ids:
        ph_clause = ", ".join(f":s{i}" for i in range(len(all_sb_ids)))
        params = {f"s{i}": sid for i, sid in enumerate(all_sb_ids)}
        sp_rows = fetch_all(
            db,
            f"SELECT storyboard_id, prop_id FROM storyboard_props WHERE storyboard_id IN ({ph_clause})",
            params,
        )
        for row in sp_rows:
            sb_prop_ids.setdefault(row["storyboard_id"], []).append(row["prop_id"])

    extra_files_to_pack: list[dict[str, str]] = []

    # 组装 project.json 数据
    exported_episodes = []
    for ep in episodes:
        sbs = storyboards_by_ep.get(ep["id"], [])
        exported_sbs = []
        for sb in sbs:
            igs_for_this = all_images_by_sb.get(sb["id"], [])
            main_ig = next((g for g in igs_for_this if g["id"] == sb.get("first_frame_image_id")), None)
            if not main_ig and igs_for_this:
                main_ig = igs_for_this[-1]

            sb_image_file = f"media/storyboards/sb_{sb['id']}_gen_{main_ig['id']}{ext_of(main_ig['local_path'])}" if main_ig and main_ig.get("local_path") else None
            vg = videos_by_sb.get(sb["id"])
            sb_video_file = f"media/videos/sb_{sb['id']}{ext_of(vg['local_path'])}" if vg and vg.get("local_path") else None
            sb_audio_file = f"media/audio/sb_{sb['id']}{ext_of(sb['audio_local_path'])}" if sb.get("audio_local_path") else None
            sb_narr_file = f"media/audio/sb_{sb['id']}_narration{ext_of(sb['narration_audio_local_path'])}" if sb.get("narration_audio_local_path") else None

            char_ids = parse_sb_chars(sb.get("characters"))
            char_indices = [char_id_to_index[cid] for cid in char_ids if cid in char_id_to_index]
            scene_index = scene_id_to_index.get(sb["scene_id"]) if sb.get("scene_id") is not None else None
            p_ids = sb_prop_ids.get(sb["id"], [])
            prop_indices = [prop_id_to_index[pid] for pid in p_ids if pid in prop_id_to_index]

            exported_sbs.append({
                "storyboard_number": sb.get("storyboard_number"),
                "title": sb.get("title"),
                "description": sb.get("description"),
                "location": sb.get("location"),
                "time": sb.get("time"),
                "dialogue": sb.get("dialogue"),
                "narration": sb.get("narration"),
                "action": sb.get("action"),
                "atmosphere": sb.get("atmosphere"),
                "result": sb.get("result"),
                "shot_type": sb.get("shot_type"),
                "angle": sb.get("angle"),
                "angle_h": sb.get("angle_h"),
                "angle_v": sb.get("angle_v"),
                "angle_s": sb.get("angle_s"),
                "movement": sb.get("movement"),
                "lighting_style": sb.get("lighting_style"),
                "depth_of_field": sb.get("depth_of_field"),
                "image_prompt": sb.get("image_prompt"),
                "polished_prompt": sb.get("polished_prompt"),
                "video_prompt": sb.get("video_prompt"),
                "duration": sb.get("duration"),
                "emotion": sb.get("emotion"),
                "emotion_intensity": sb.get("emotion_intensity"),
                "segment_index": sb.get("segment_index", 0),
                "segment_title": sb.get("segment_title"),
                "continuity_snapshot": sb.get("continuity_snapshot"),
                "creation_mode": "universal" if sb.get("creation_mode") == "universal" else "classic",
                "universal_segment_text": sb.get("universal_segment_text"),
                "layout_description": sb.get("layout_description"),
                "first_frame_image_original_id": sb.get("first_frame_image_id"),
                "last_frame_image_original_id": sb.get("last_frame_image_id"),
                "last_frame_image_url": sb.get("last_frame_image_url"),
                "last_frame_local_path": sb.get("last_frame_local_path"),
                "character_indices": char_indices,
                "scene_index": scene_index,
                "prop_indices": prop_indices,
                "image_file": sb_image_file,
                "video_file": sb_video_file,
                "audio_file": sb_audio_file,
                "narration_audio_file": sb_narr_file,
                "image_generations": [
                    {
                        "original_id": ig["id"],
                        "provider": ig.get("provider") or "imported",
                        "prompt": ig.get("prompt"),
                        "negative_prompt": ig.get("negative_prompt"),
                        "model": ig.get("model"),
                        "frame_type": ig.get("frame_type"),
                        "size": ig.get("size"),
                        "quality": ig.get("quality"),
                        "status": ig.get("status") or "completed",
                        "error_msg": ig.get("error_msg"),
                        "created_at": str(ig.get("created_at") or ""),
                        "updated_at": str(ig.get("updated_at") or ""),
                        "completed_at": str(ig.get("completed_at") or ""),
                        "zip_file": f"media/storyboards/sb_{sb['id']}_gen_{ig['id']}{ext_of(ig.get('local_path'))}",
                    }
                    for ig in igs_for_this
                ],
                "frame_prompts": frame_prompts_by_sb.get(sb["id"], []),
            })

        exported_episodes.append({
            "episode_number": ep.get("episode_number"),
            "title": ep.get("title"),
            "description": ep.get("description"),
            "script_content": ep.get("script_content"),
            "duration": ep.get("duration"),
            "storyboards": exported_sbs,
        })

    exported_characters = []
    for c in characters:
        extras = parse_extra_images(c.get("extra_images"))
        extra_files = []
        for i, rel_path in enumerate(extras):
            zp = f"media/characters/extra_char_{c['id']}_{i}{ext_of(rel_path)}"
            extra_files_to_pack.append({"local_rel_path": rel_path, "zip_path": zp})
            extra_files.append(zp)
        exported_characters.append({
            "name": c.get("name"),
            "role": c.get("role"),
            "description": c.get("description"),
            "personality": c.get("personality"),
            "appearance": c.get("appearance"),
            "voice_style": c.get("voice_style"),
            "polished_prompt": c.get("polished_prompt"),
            "image_file": f"media/characters/char_{c['id']}{ext_of(c['local_path'])}" if c.get("local_path") else None,
            "extra_image_files": extra_files,
        })

    exported_scenes = []
    for s in deduped_scenes:
        ep_idx = episode_ids.index(s["episode_id"]) if s.get("episode_id") in episode_ids else None
        extras = parse_extra_images(s.get("extra_images"))
        extra_files = []
        for i, rel_path in enumerate(extras):
            zp = f"media/scenes/extra_scene_{s['id']}_{i}{ext_of(rel_path)}"
            extra_files_to_pack.append({"local_rel_path": rel_path, "zip_path": zp})
            extra_files.append(zp)
        exported_scenes.append({
            "location": s.get("location"),
            "time": s.get("time"),
            "prompt": s.get("prompt"),
            "polished_prompt": s.get("polished_prompt"),
            "episode_index": ep_idx,
            "image_file": f"media/scenes/scene_{s['id']}{ext_of(s['local_path'])}" if s.get("local_path") else None,
            "extra_image_files": extra_files,
        })

    exported_props = []
    for p in props:
        ep_idx = episode_ids.index(p["episode_id"]) if p.get("episode_id") in episode_ids else None
        extras = parse_extra_images(p.get("extra_images"))
        extra_files = []
        for i, rel_path in enumerate(extras):
            zp = f"media/props/extra_prop_{p['id']}_{i}{ext_of(rel_path)}"
            extra_files_to_pack.append({"local_rel_path": rel_path, "zip_path": zp})
            extra_files.append(zp)
        exported_props.append({
            "name": p.get("name"),
            "type": p.get("type"),
            "description": p.get("description"),
            "prompt": p.get("prompt"),
            "episode_index": ep_idx,
            "image_file": f"media/props/prop_{p['id']}{ext_of(p['local_path'])}" if p.get("local_path") else None,
            "extra_image_files": extra_files,
        })

    now_iso = datetime.now(timezone.utc).isoformat()
    zip_data = {
        "version": EXPORT_VERSION,
        "exported_at": now_iso,
        "drama": {
            "title": drama.get("title"),
            "description": drama.get("description"),
            "genre": drama.get("genre"),
            "style": drama.get("style"),
            "status": drama.get("status"),
            "tags": drama.get("tags"),
            "metadata": metadata,
        },
        "episodes": exported_episodes,
        "characters": exported_characters,
        "scenes": exported_scenes,
        "props": exported_props,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(zip_data, ensure_ascii=False, indent=2).encode("utf-8"))

        for item in image_files_to_pack:
            abs_p = local_path_to_abs(storage_path, item["local_rel_path"])
            b = safe_read_file(abs_p)
            if b:
                zf.writestr(item["zip_path"], b)

        for sb_id, vg in videos_by_sb.items():
            lp = vg.get("local_path")
            if lp:
                abs_p = local_path_to_abs(storage_path, lp)
                b = safe_read_file(abs_p)
                if b:
                    zf.writestr(f"media/videos/sb_{sb_id}{ext_of(lp)}", b)

        for ep in episodes:
            for sb in storyboards_by_ep.get(ep["id"], []):
                if sb.get("audio_local_path"):
                    abs_p = local_path_to_abs(storage_path, sb["audio_local_path"])
                    b = safe_read_file(abs_p)
                    if b:
                        zf.writestr(f"media/audio/sb_{sb['id']}{ext_of(sb['audio_local_path'])}", b)
                if sb.get("narration_audio_local_path"):
                    abs_p = local_path_to_abs(storage_path, sb["narration_audio_local_path"])
                    b = safe_read_file(abs_p)
                    if b:
                        zf.writestr(f"media/audio/sb_{sb['id']}_narration{ext_of(sb['narration_audio_local_path'])}", b)

        for c in characters:
            if c.get("local_path"):
                abs_p = local_path_to_abs(storage_path, c["local_path"])
                b = safe_read_file(abs_p)
                if b:
                    zf.writestr(f"media/characters/char_{c['id']}{ext_of(c['local_path'])}", b)

        for s in deduped_scenes:
            if s.get("local_path"):
                abs_p = local_path_to_abs(storage_path, s["local_path"])
                b = safe_read_file(abs_p)
                if b:
                    zf.writestr(f"media/scenes/scene_{s['id']}{ext_of(s['local_path'])}", b)

        for p in props:
            if p.get("local_path"):
                abs_p = local_path_to_abs(storage_path, p["local_path"])
                b = safe_read_file(abs_p)
                if b:
                    zf.writestr(f"media/props/prop_{p['id']}{ext_of(p['local_path'])}", b)

        for item in extra_files_to_pack:
            abs_p = local_path_to_abs(storage_path, item["local_rel_path"])
            b = safe_read_file(abs_p)
            if b:
                zf.writestr(item["zip_path"], b)

    if log:
        log.info("Drama exported", extra={"drama_id": did, "title": drama.get("title")})
    return buf.getvalue(), drama.get("title") or "drama"
