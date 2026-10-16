# 项目导入服务：解析 ZIP，还原剧集数据和媒体文件
from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import execute, fetch_all, fetch_one
from app.services import storageLayout


def get_storage_path(cfg: dict | None) -> str:
    raw = (cfg or {}).get("storage", {}).get("local_path") or "./data/storage"
    return os.path.abspath(raw)


def ensure_dir(path_str: str) -> None:
    os.makedirs(path_str, exist_ok=True)


def parse_zip(zip_buffer: bytes) -> tuple[dict, dict[str, bytes]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_buffer))
    except Exception:
        raise ValueError("ZIP 文件损坏，无法解析")

    namelist = zf.namelist()
    if "project.json" not in namelist:
        raise ValueError("ZIP 格式不正确：缺少 project.json")

    try:
        raw_json = zf.read("project.json").decode("utf-8")
        data = json.loads(raw_json)
    except Exception:
        raise ValueError("project.json 格式错误，无法解析 JSON")

    if not isinstance(data, dict) or not data.get("drama") or not (data.get("drama") or {}).get("title"):
        raise ValueError("project.json 格式不正确：缺少 drama.title 字段")

    files: dict[str, bytes] = {}
    for name in namelist:
        if not name.endswith("/") and name != "project.json":
            files[name] = zf.read(name)

    return data, files


def resolve_title(db: Session, base_title: str) -> str:
    rows = fetch_all(db, "SELECT title FROM dramas WHERE deleted_at IS NULL")
    existing = {r["title"] for r in rows if r.get("title")}
    if base_title not in existing:
        return base_title
    i = 1
    while f"{base_title} 导入{i}" in existing:
        i += 1
    return f"{base_title} 导入{i}"


def save_media_file(
    storage_path: str,
    project_dir: str,
    category: str,
    files: dict[str, bytes],
    zip_path: str | None,
    prefix: str,
) -> str | None:
    if not zip_path or zip_path not in files:
        return None
    buf = files[zip_path]
    _, ext = os.path.splitext(zip_path)
    if not ext:
        ext = ".jpg"
    category_path = os.path.join(storage_path, project_dir, category)
    ensure_dir(category_path)
    name = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
    abs_path = os.path.join(category_path, name)
    with open(abs_path, "wb") as f:
        f.write(buf)
    return f"{project_dir}/{category}/{name}".replace("\\", "/")


def save_extra_images(
    storage_path: str,
    project_dir: str,
    category: str,
    files: dict[str, bytes],
    zip_paths: list[str] | None,
    prefix: str,
) -> str | None:
    if not isinstance(zip_paths, list) or not zip_paths:
        return None
    local_paths = []
    for zp in zip_paths:
        lp = save_media_file(storage_path, project_dir, category, files, zp, prefix)
        if lp:
            local_paths.append(lp)
    return json.dumps(local_paths, ensure_ascii=False) if local_paths else None


IMPORT_FIRST_FRAME_TYPES = ("storyboard_first", "first", "first_frame")
IMPORT_LAST_FRAME_TYPES = ("storyboard_last", "last", "tail", "last_frame")


def restore_frame_prompts_from_image_gens(db: Session, sb_id: int, now: str, log=None) -> None:
    for types, frame_type in [(IMPORT_FIRST_FRAME_TYPES, "first"), (IMPORT_LAST_FRAME_TYPES, "last")]:
        has = fetch_one(
            db,
            "SELECT id FROM frame_prompts WHERE storyboard_id = :sb_id AND frame_type = :ft",
            {"sb_id": sb_id, "ft": frame_type},
        )
        if has:
            continue
        ph_clause = ", ".join(f":t{i}" for i in range(len(types)))
        params: dict[str, Any] = {"sb_id": sb_id}
        for i, t in enumerate(types):
            params[f"t{i}"] = t
        ig = fetch_one(
            db,
            f"""SELECT prompt FROM image_generations WHERE storyboard_id = :sb_id AND deleted_at IS NULL
                AND frame_type IN ({ph_clause}) AND prompt IS NOT NULL AND TRIM(prompt) != ''
                ORDER BY created_at DESC LIMIT 1""",
            params,
        )
        prompt_val = (ig.get("prompt") or "").strip() if ig else ""
        if prompt_val:
            execute(
                db,
                """INSERT INTO frame_prompts (storyboard_id, frame_type, prompt, description, layout, created_at, updated_at)
                   VALUES (:sb_id, :ft, :prompt, NULL, NULL, :now, :now)""",
                {"sb_id": sb_id, "ft": frame_type, "prompt": prompt_val, "now": now},
            )
            if log:
                try:
                    log.info("[导入] 从分镜图历史恢复帧提示词", extra={"storyboard_id": sb_id, "frame_type": frame_type})
                except Exception:
                    pass


def import_drama(db: Session, cfg: dict, log, zip_buffer: bytes) -> dict:
    storage_path = get_storage_path(cfg)
    data, files = parse_zip(zip_buffer)

    d = data.get("drama", {})
    title = resolve_title(db, d.get("title") or "导入项目")
    now = datetime.now(timezone.utc).isoformat()

    metadata = d.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}

    metadata["storage_folder_label"] = storageLayout.sanitize_folder_label(title)
    meta_str = json.dumps(metadata, ensure_ascii=False)

    return _do_import(db, storage_path, files, data, d, title, meta_str, now, log)


def _do_import(db: Session, storage_path: str, files: dict[str, bytes], data: dict, d: dict, title: str, meta_str: str, now: str, log=None) -> dict:
    # 1. 创建 drama
    res = execute(
        db,
        """INSERT INTO dramas (title, description, genre, style, status, tags, metadata, created_at, updated_at)
           VALUES (:title, :description, :genre, :style, :status, :tags, :metadata, :created_at, :updated_at)""",
        {
            "title": title,
            "description": d.get("description"),
            "genre": d.get("genre"),
            "style": d.get("style"),
            "status": d.get("status") or "draft",
            "tags": d.get("tags"),
            "metadata": meta_str,
            "created_at": now,
            "updated_at": now,
        },
    )
    drama_id = res.lastrowid
    project_dir = storageLayout.build_project_relative_dir({
        "id": drama_id,
        "title": title,
        "created_at": now,
        "metadata": meta_str,
    })

    # 2. 导入角色
    char_new_ids: list[int | None] = []
    for i, c in enumerate(data.get("characters") or []):
        if not c.get("name"):
            char_new_ids.append(None)
            continue
        local_path = save_media_file(storage_path, project_dir, "characters", files, c.get("image_file"), "char_imp")
        extra_images_json = save_extra_images(storage_path, project_dir, "characters", files, c.get("extra_image_files"), "char_extra_imp")
        c_res = execute(
            db,
            """INSERT INTO characters (drama_id, name, role, description, personality, appearance, voice_style, polished_prompt, local_path, extra_images, sort_order, created_at, updated_at)
               VALUES (:drama_id, :name, :role, :description, :personality, :appearance, :voice_style, :polished_prompt, :local_path, :extra_images, :sort_order, :created_at, :updated_at)""",
            {
                "drama_id": drama_id,
                "name": c.get("name"),
                "role": c.get("role"),
                "description": c.get("description"),
                "personality": c.get("personality"),
                "appearance": c.get("appearance"),
                "voice_style": c.get("voice_style"),
                "polished_prompt": c.get("polished_prompt"),
                "local_path": local_path,
                "extra_images": extra_images_json,
                "sort_order": i,
                "created_at": now,
                "updated_at": now,
            },
        )
        char_new_ids.append(c_res.lastrowid)

    # 3. 导入剧集
    episode_id_list: list[int] = []
    for ep in data.get("episodes") or []:
        ep_res = execute(
            db,
            """INSERT INTO episodes (drama_id, episode_number, title, description, script_content, duration, created_at, updated_at)
               VALUES (:drama_id, :episode_number, :title, :description, :script_content, :duration, :created_at, :updated_at)""",
            {
                "drama_id": drama_id,
                "episode_number": ep.get("episode_number") or 1,
                "title": ep.get("title") or f"第{ep.get('episode_number') or 1}集",
                "description": ep.get("description"),
                "script_content": ep.get("script_content"),
                "duration": ep.get("duration") or 0,
                "created_at": now,
                "updated_at": now,
            },
        )
        episode_id_list.append(ep_res.lastrowid)

    # 关联角色到所有集（episode_characters）
    if char_new_ids and episode_id_list:
        for char_id in char_new_ids:
            if not char_id:
                continue
            for ep_id in episode_id_list:
                try:
                    execute(
                        db,
                        "INSERT IGNORE INTO episode_characters (episode_id, character_id) VALUES (:ep_id, :char_id)",
                        {"ep_id": ep_id, "char_id": char_id},
                    )
                except Exception:
                    pass

    # 4. 导入场景（按 location + time 去重）
    scene_new_ids: list[int | None] = []
    scene_dedupe_map: dict[str, int] = {}
    for s in data.get("scenes") or []:
        loc = (s.get("location") or "").strip()
        tm = (s.get("time") or "").strip()
        dedupe_key = f"{loc}|{tm}"
        if dedupe_key in scene_dedupe_map:
            scene_new_ids.append(scene_dedupe_map[dedupe_key])
            continue

        ep_idx = s.get("episode_index")
        ep_id = episode_id_list[ep_idx] if (ep_idx is not None and 0 <= ep_idx < len(episode_id_list)) else (episode_id_list[0] if episode_id_list else None)
        local_path = save_media_file(storage_path, project_dir, "scenes", files, s.get("image_file"), "scene_imp")
        extra_images_json = save_extra_images(storage_path, project_dir, "scenes", files, s.get("extra_image_files"), "scene_extra_imp")

        s_res = execute(
            db,
            """INSERT INTO scenes (drama_id, episode_id, location, time, prompt, polished_prompt, local_path, extra_images, created_at, updated_at)
               VALUES (:drama_id, :episode_id, :location, :time, :prompt, :polished_prompt, :local_path, :extra_images, :created_at, :updated_at)""",
            {
                "drama_id": drama_id,
                "episode_id": ep_id,
                "location": s.get("location") or "",
                "time": s.get("time") or "",
                "prompt": s.get("prompt") or "",
                "polished_prompt": s.get("polished_prompt"),
                "local_path": local_path,
                "extra_images": extra_images_json,
                "created_at": now,
                "updated_at": now,
            },
        )
        new_sid = s_res.lastrowid
        scene_new_ids.append(new_sid)
        scene_dedupe_map[dedupe_key] = new_sid

    # 5. 导入道具
    prop_new_ids: list[int | None] = []
    for p in data.get("props") or []:
        if not p.get("name"):
            prop_new_ids.append(None)
            continue
        ep_idx = p.get("episode_index")
        ep_id = episode_id_list[ep_idx] if (ep_idx is not None and 0 <= ep_idx < len(episode_id_list)) else (episode_id_list[0] if episode_id_list else None)
        local_path = save_media_file(storage_path, project_dir, "props", files, p.get("image_file"), "prop_imp")
        extra_images_json = save_extra_images(storage_path, project_dir, "props", files, p.get("extra_image_files"), "prop_extra_imp")

        p_res = execute(
            db,
            """INSERT INTO props (drama_id, episode_id, name, type, description, prompt, local_path, extra_images, created_at, updated_at)
               VALUES (:drama_id, :episode_id, :name, :type, :description, :prompt, :local_path, :extra_images, :created_at, :updated_at)""",
            {
                "drama_id": drama_id,
                "episode_id": ep_id,
                "name": p.get("name"),
                "type": p.get("type"),
                "description": p.get("description"),
                "prompt": p.get("prompt"),
                "local_path": local_path,
                "extra_images": extra_images_json,
                "created_at": now,
                "updated_at": now,
            },
        )
        prop_new_ids.append(p_res.lastrowid)

    # 6. 导入分镜
    for ep_idx, ep in enumerate(data.get("episodes") or []):
        if ep_idx >= len(episode_id_list):
            continue
        episode_id = episode_id_list[ep_idx]

        for sb in ep.get("storyboards") or []:
            sb_audio_path = save_media_file(storage_path, project_dir, "audio", files, sb.get("audio_file"), "sb_audio_imp")
            sb_narr_path = save_media_file(storage_path, project_dir, "audio", files, sb.get("narration_audio_file"), "sb_narr_audio_imp")

            # 还原 characters
            char_indices = sb.get("character_indices") if isinstance(sb.get("character_indices"), list) else []
            sb_char_ids = [char_new_ids[idx] for idx in char_indices if 0 <= idx < len(char_new_ids) and char_new_ids[idx] is not None]
            characters_json = json.dumps(sb_char_ids)

            # 还原 scene_id
            scene_idx = sb.get("scene_index")
            sb_scene_id = scene_new_ids[scene_idx] if (scene_idx is not None and 0 <= scene_idx < len(scene_new_ids)) else None

            # 还原 prop_ids
            prop_indices = sb.get("prop_indices") if isinstance(sb.get("prop_indices"), list) else []
            sb_prop_new_ids = [prop_new_ids[idx] for idx in prop_indices if 0 <= idx < len(prop_new_ids) and prop_new_ids[idx] is not None]

            sb_res = execute(
                db,
                """INSERT INTO storyboards (
                    episode_id, scene_id, storyboard_number, title, description, location, time,
                    dialogue, narration, action, atmosphere, result, shot_type, angle, angle_h, angle_v, angle_s,
                    movement, lighting_style, depth_of_field, image_prompt, polished_prompt, video_prompt, duration,
                    emotion, emotion_intensity, segment_index, segment_title, continuity_snapshot, creation_mode,
                    universal_segment_text, layout_description, first_frame_image_id, last_frame_image_id,
                    last_frame_image_url, last_frame_local_path, image_url, local_path, characters,
                    audio_local_path, narration_audio_local_path, created_at, updated_at
                ) VALUES (
                    :episode_id, :scene_id, :storyboard_number, :title, :description, :location, :time,
                    :dialogue, :narration, :action, :atmosphere, :result, :shot_type, :angle, :angle_h, :angle_v, :angle_s,
                    :movement, :lighting_style, :depth_of_field, :image_prompt, :polished_prompt, :video_prompt, :duration,
                    :emotion, :emotion_intensity, :segment_index, :segment_title, :continuity_snapshot, :creation_mode,
                    :universal_segment_text, :layout_description, NULL, NULL,
                    :last_frame_image_url, :last_frame_local_path, NULL, NULL, :characters,
                    :audio_local_path, :narration_audio_local_path, :created_at, :updated_at
                )""",
                {
                    "episode_id": episode_id,
                    "scene_id": sb_scene_id,
                    "storyboard_number": sb.get("storyboard_number") or 1,
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
                    "duration": sb.get("duration") or 0,
                    "emotion": sb.get("emotion"),
                    "emotion_intensity": sb.get("emotion_intensity"),
                    "segment_index": sb.get("segment_index", 0),
                    "segment_title": sb.get("segment_title"),
                    "continuity_snapshot": sb.get("continuity_snapshot"),
                    "creation_mode": "universal" if sb.get("creation_mode") == "universal" else "classic",
                    "universal_segment_text": sb.get("universal_segment_text"),
                    "layout_description": sb.get("layout_description"),
                    "last_frame_image_url": sb.get("last_frame_image_url"),
                    "last_frame_local_path": sb.get("last_frame_local_path"),
                    "characters": characters_json,
                    "audio_local_path": sb_audio_path,
                    "narration_audio_local_path": sb_narr_path,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            sb_id = sb_res.lastrowid

            # 还原 storyboard_props
            for pid in sb_prop_new_ids:
                try:
                    execute(
                        db,
                        "INSERT IGNORE INTO storyboard_props (storyboard_id, prop_id) VALUES (:sb_id, :pid)",
                        {"sb_id": sb_id, "pid": pid},
                    )
                except Exception:
                    pass

            # 还原 frame_prompts
            for fp in sb.get("frame_prompts") or []:
                execute(
                    db,
                    """INSERT INTO frame_prompts (storyboard_id, frame_type, prompt, description, layout, created_at, updated_at)
                       VALUES (:sb_id, :frame_type, :prompt, :description, :layout, :created_at, :updated_at)""",
                    {
                        "sb_id": sb_id,
                        "frame_type": fp.get("frame_type") or "first",
                        "prompt": fp.get("prompt") or "",
                        "description": fp.get("description"),
                        "layout": fp.get("layout"),
                        "created_at": fp.get("created_at") or now,
                        "updated_at": fp.get("updated_at") or now,
                    },
                )

            # 导入分镜图片完整历史
            gen_old_to_new: dict[int, dict] = {}
            if sb.get("image_generations"):
                for gen in sb["image_generations"]:
                    zp = gen.get("zip_file") or gen.get("file")
                    gen_local_path = save_media_file(storage_path, project_dir, "images", files, zp, "sb_imp_gen")
                    if gen_local_path:
                        gen_res = execute(
                            db,
                            """INSERT INTO image_generations (
                                drama_id, storyboard_id, provider, prompt, negative_prompt, model, frame_type, size, quality,
                                status, error_msg, local_path, created_at, updated_at, completed_at
                            ) VALUES (
                                :drama_id, :storyboard_id, :provider, :prompt, :negative_prompt, :model, :frame_type, :size, :quality,
                                :status, :error_msg, :local_path, :created_at, :updated_at, :completed_at
                            )""",
                            {
                                "drama_id": drama_id,
                                "storyboard_id": sb_id,
                                "provider": gen.get("provider") or "imported",
                                "prompt": gen.get("prompt") or sb.get("image_prompt") or "",
                                "negative_prompt": gen.get("negative_prompt"),
                                "model": gen.get("model"),
                                "frame_type": gen.get("frame_type"),
                                "size": gen.get("size"),
                                "quality": gen.get("quality"),
                                "status": gen.get("status") or "completed",
                                "error_msg": gen.get("error_msg"),
                                "local_path": gen_local_path,
                                "created_at": gen.get("created_at") or now,
                                "updated_at": now,
                                "completed_at": gen.get("completed_at") or now,
                            },
                        )
                        new_gen_id = gen_res.lastrowid
                        orig_id = gen.get("original_id")
                        if orig_id is not None:
                            try:
                                gen_old_to_new[int(orig_id)] = {"new_id": new_gen_id, "local_path": gen_local_path}
                            except (ValueError, TypeError):
                                pass
            elif sb.get("image_file"):
                sb_image_path = save_media_file(storage_path, project_dir, "images", files, sb.get("image_file"), "sb_imp")
                if sb_image_path:
                    execute(
                        db,
                        """INSERT INTO image_generations (drama_id, storyboard_id, provider, prompt, status, local_path, created_at, updated_at)
                           VALUES (:drama_id, :storyboard_id, 'imported', :prompt, 'completed', :local_path, :created_at, :updated_at)""",
                        {
                            "drama_id": drama_id,
                            "storyboard_id": sb_id,
                            "prompt": sb.get("image_prompt") or "",
                            "local_path": sb_image_path,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )

            # 导入视频
            if sb.get("video_file"):
                video_local_path = save_media_file(storage_path, project_dir, "videos", files, sb.get("video_file"), "vid_imp")
                if video_local_path:
                    execute(
                        db,
                        """INSERT INTO video_generations (drama_id, storyboard_id, provider, prompt, status, local_path, created_at, updated_at)
                           VALUES (:drama_id, :storyboard_id, 'imported', :prompt, 'completed', :local_path, :created_at, :updated_at)""",
                        {
                            "drama_id": drama_id,
                            "storyboard_id": sb_id,
                            "prompt": sb.get("video_prompt") or "",
                            "local_path": video_local_path,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )

            # 绑定首尾帧
            now2 = datetime.now(timezone.utc).isoformat()
            first_old = sb.get("first_frame_image_original_id") if sb.get("first_frame_image_original_id") is not None else sb.get("first_frame_image_id")
            last_old = sb.get("last_frame_image_original_id") if sb.get("last_frame_image_original_id") is not None else sb.get("last_frame_image_id")

            if first_old is not None:
                try:
                    f_oid = int(first_old)
                    if f_oid in gen_old_to_new:
                        binding = gen_old_to_new[f_oid]
                        execute(
                            db,
                            """UPDATE storyboards
                               SET image_url = NULL, local_path = :lp, first_frame_image_id = :gid, updated_at = :now
                               WHERE id = :id AND deleted_at IS NULL""",
                            {"lp": binding["local_path"], "gid": binding["new_id"], "now": now2, "id": sb_id},
                        )
                except (ValueError, TypeError):
                    pass

            if last_old is not None:
                try:
                    l_oid = int(last_old)
                    if l_oid in gen_old_to_new:
                        binding = gen_old_to_new[l_oid]
                        execute(
                            db,
                            """UPDATE storyboards
                               SET last_frame_image_url = NULL, last_frame_local_path = :lp, last_frame_image_id = :gid, updated_at = :now
                               WHERE id = :id AND deleted_at IS NULL""",
                            {"lp": binding["local_path"], "gid": binding["new_id"], "now": now2, "id": sb_id},
                        )
                except (ValueError, TypeError):
                    pass

            # 兼容老工程补全 frame_prompts
            restore_frame_prompts_from_image_gens(db, sb_id, now2, log)

    if log:
        log.info("Drama imported", extra={"drama_id": drama_id, "title": title})
    return {"drama_id": drama_id, "title": title}
