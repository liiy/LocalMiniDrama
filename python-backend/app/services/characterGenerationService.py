"""角色提取与生成服务，等价 Node services/characterGenerationService.js。

支持剧本角色提取、视觉锚点提炼、配置合并、分集角色关联及任务状态推进。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one, session_scope
from app.services import aiClient, characterLibraryService, promptI18n, taskService, workerService
from app.services.libraryCommon import to_int_id
from app.utils.dramaStyleMerge import merge_cfg_style_with_drama
from app.utils.safeJson import extract_first_array, safe_parse_ai_json

log = get_logger("lmd.characterGeneration")


def _is_mysql(db: Session) -> bool:
    try:
        bind = db.get_bind()
        return bind.dialect.name == "mysql"
    except Exception:
        return False


def _get_last_inserted_id(db: Session, res=None) -> int:
    if res is not None:
        lastrowid = getattr(res, "lastrowid", None)
        if lastrowid is not None and lastrowid > 0:
            return int(lastrowid)
    if _is_mysql(db):
        row = fetch_one(db, "SELECT LAST_INSERT_ID() AS id")
    else:
        row = fetch_one(db, "SELECT last_insert_rowid() AS id")
    if row and row.get("id") is not None:
        return int(row["id"])
    return 0


def enrich_identity_anchors(db: Session, log_, character_id: int, appearance: str | None) -> None:
    """从角色外貌描述中提炼 6 层视觉锚点，写入 characters.identity_anchors。"""
    log_ = log_ or log
    if not appearance or not str(appearance).strip():
        return
    try:
        system_prompt = promptI18n.get_identity_anchors_prompt()
        user_prompt = f"Character appearance description:\n{appearance}"
        raw = aiClient.generate_text(
            db,
            log_,
            "text",
            user_prompt,
            system_prompt,
            {
                "scene_key": "identity_anchors",
                "max_tokens": 800,
                "temperature": 0.1,
            },
        )
        anchors = safe_parse_ai_json(raw, log_)
        if not anchors or not isinstance(anchors, dict):
            return

        color_palette = None
        if anchors.get("color_anchors") and isinstance(anchors["color_anchors"], dict):
            color_palette = json.dumps(list(anchors["color_anchors"].values()), ensure_ascii=False)

        now = timestamp()
        execute(
            db,
            "UPDATE characters SET identity_anchors = :anchors, color_palette = :palette, updated_at = :now WHERE id = :id",
            {
                "anchors": json.dumps(anchors, ensure_ascii=False),
                "palette": color_palette,
                "now": now,
                "id": to_int_id(character_id),
            },
        )
        db.commit()
        log_.info("[锚点] identity_anchors 提炼完成", extra={"character_id": character_id})
    except Exception as err:
        log_.warning("[锚点] identity_anchors 提炼失败", extra={"character_id": character_id, "error": str(err)})


def _bg_enrich_and_prompt(char_id: int, appearance: str | None, cfg: dict | None) -> None:
    try:
        with session_scope() as db:
            enrich_identity_anchors(db, log, char_id, appearance)
    except Exception as e:
        log.warning("[提取角色] enrich_identity_anchors 后台任务异常", extra={"character_id": char_id, "error": str(e)})

    try:
        with session_scope() as db:
            characterLibraryService.generate_character_prompt_only(db, log, cfg or {}, char_id, None, None)
    except Exception as e:
        log.warning("[提取角色] 预生成polished_prompt失败", extra={"character_id": char_id, "error": str(e)})


def process_character_generation(task_id: str, req: dict, cfg: dict | None = None) -> None:
    with session_scope() as db:
        taskService.update_task_status(db, task_id, "processing", 0, "正在生成角色...")
        outline_text = str(req.get("outline") or "")

        drama_id = to_int_id(req.get("drama_id"))
        drama_row = fetch_one(
            db,
            "SELECT id, title, description, genre, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
            {"id": drama_id},
        )
        if not drama_row:
            taskService.update_task_status(db, task_id, "failed", 0, "剧本信息不存在")
            return

        effective_cfg = cfg or load_config()
        try:
            next_cfg = dict(effective_cfg)
            next_style = dict(next_cfg.get("style") or {})
            if drama_row.get("metadata"):
                meta = drama_row["metadata"]
                meta_dict = json.loads(meta) if isinstance(meta, str) else meta
                if isinstance(meta_dict, dict) and meta_dict.get("aspect_ratio"):
                    next_style["default_image_ratio"] = meta_dict["aspect_ratio"]
            next_cfg["style"] = next_style
            effective_cfg = merge_cfg_style_with_drama(next_cfg, dict(drama_row))
        except Exception:
            pass

        if not outline_text:
            outline_text = promptI18n.format_user_prompt(
                effective_cfg,
                "drama_info_template",
                drama_row.get("title") or "",
                drama_row.get("description") or "",
                drama_row.get("genre") or "",
            )

        user_prompt = promptI18n.format_user_prompt(effective_cfg, "character_request", outline_text)
        system_prompt = promptI18n.get_character_extraction_prompt(effective_cfg)
        temp_val = req.get("temperature")
        temperature = float(temp_val) if temp_val is not None else 0.7
        max_tokens_for_chars = 6000

        try:
            text_out = aiClient.generate_text(
                db,
                log,
                "text",
                user_prompt,
                system_prompt,
                {
                    "scene_key": "role_extraction",
                    "model": req.get("model") or None,
                    "temperature": temperature,
                    "max_tokens": max_tokens_for_chars,
                },
            )
        except Exception as err:
            log.error("Character generation AI failed", extra={"error": str(err), "task_id": task_id})
            taskService.update_task_status(db, task_id, "failed", 0, f"AI生成失败: {err}")
            return

        try:
            parsed = safe_parse_ai_json(text_out, log)
            result = extract_first_array(parsed) or []
        except Exception as err:
            log.error("Character generation parse failed", extra={"error": str(err), "task_id": task_id})
            taskService.update_task_status(db, task_id, "failed", 0, "解析AI返回结果失败")
            return

        now = timestamp()

        # 再次「从剧本提取角色」时先清空本集已关联角色，避免与旧数据累加；仅软删除不再被任何分集引用的角色行
        episode_id_raw = req.get("episode_id")
        if episode_id_raw:
            episode_id = to_int_id(episode_id_raw)
            linked_rows = fetch_all(
                db,
                "SELECT character_id FROM episode_characters WHERE episode_id = :eid",
                {"eid": episode_id},
            )
            for row in linked_rows:
                cid = to_int_id(row["character_id"])
                other = fetch_one(
                    db,
                    "SELECT COUNT(*) AS n FROM episode_characters WHERE character_id = :cid AND episode_id != :eid",
                    {"cid": cid, "eid": episode_id},
                )
                if other and int(other.get("n") or 0) == 0:
                    execute(
                        db,
                        "UPDATE characters SET deleted_at = :now WHERE id = :id AND drama_id = :did AND deleted_at IS NULL",
                        {"now": now, "id": cid, "did": drama_id},
                    )
            execute(
                db,
                "DELETE FROM episode_characters WHERE episode_id = :eid",
                {"eid": episode_id},
            )
            db.commit()

        characters: list[dict[str, Any]] = []

        for char in result:
            if not isinstance(char, dict):
                continue
            name = str(char.get("name") or "").strip()
            if not name:
                continue

            existing = fetch_one(
                db,
                "SELECT id, name FROM characters WHERE drama_id = :did AND name = :name AND deleted_at IS NULL",
                {"did": drama_id, "name": name},
            )
            if existing:
                characters.append({
                    "id": existing["id"],
                    "drama_id": drama_id,
                    "name": existing["name"],
                    "role": None,
                    "description": None,
                    "personality": None,
                    "appearance": None,
                    "voice_style": None,
                })
                continue

            insert_sql = """
                INSERT INTO characters (drama_id, name, role, description, personality, appearance, voice_style, sort_order, created_at, updated_at)
                VALUES (:drama_id, :name, :role, :description, :personality, :appearance, :voice_style, 0, :created_at, :updated_at)
            """
            res = execute(
                db,
                insert_sql,
                {
                    "drama_id": drama_id,
                    "name": name,
                    "role": char.get("role"),
                    "description": char.get("description"),
                    "personality": char.get("personality"),
                    "appearance": char.get("appearance"),
                    "voice_style": char.get("voice_style"),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            new_char_id = _get_last_inserted_id(db, res)
            db.commit()

            appearance = char.get("appearance")
            if appearance:
                workerService.submit(_bg_enrich_and_prompt, new_char_id, str(appearance), effective_cfg)

            characters.append({
                "id": new_char_id,
                "drama_id": drama_id,
                "name": name,
                "role": char.get("role"),
                "description": char.get("description"),
                "personality": char.get("personality"),
                "appearance": char.get("appearance"),
                "voice_style": char.get("voice_style"),
            })

        if episode_id_raw and characters:
            episode_id = to_int_id(episode_id_raw)
            insert_link_sql = (
                "INSERT IGNORE INTO episode_characters (episode_id, character_id) VALUES (:eid, :cid)"
                if _is_mysql(db)
                else "INSERT OR IGNORE INTO episode_characters (episode_id, character_id) VALUES (:eid, :cid)"
            )
            for c in characters:
                try:
                    execute(db, insert_link_sql, {"eid": episode_id, "cid": c["id"]})
                except Exception:
                    pass
            db.commit()

        taskService.update_task_result(db, task_id, {"characters": characters, "count": len(characters)})
        log.info(
            "Character generation completed",
            extra={"task_id": task_id, "drama_id": drama_id, "character_count": len(characters)},
        )


def generate_characters(db: Session, cfg: dict | None, log_, req: dict) -> str:
    drama_id = str(req.get("drama_id") or "")
    if not drama_id:
        raise ValueError("drama_id 必填")
    task = taskService.create_task(db, log_, "character_generation", drama_id)
    task_id = task["id"] if isinstance(task, dict) else str(task)

    worker_payload = {
        "drama_id": req.get("drama_id"),
        "episode_id": req.get("episode_id"),
        "outline": req.get("outline"),
        "temperature": req.get("temperature"),
        "model": req.get("model"),
    }
    workerService.submit(process_character_generation, task_id, worker_payload, cfg)
    return task_id
