"""剧本道具提取服务，等价 Node services/propExtractionService.js。

从剧集剧本中提取道具实体，支持异步任务、配置合并、去重更新及提示词自动预生成。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import session_scope
from app.services import aiClient, promptI18n, propEntityService, taskService, workerService
from app.utils.dramaStyleMerge import merge_cfg_style_with_drama
from app.utils.safeJson import extract_first_array, safe_parse_ai_json

log = get_logger("lmd.propExtractionService")


def _bg_gen_prompt(prop_id: int, cfg: dict) -> None:
    try:
        with session_scope() as db:
            propEntityService.generate_prop_prompt_only(db, log, cfg, prop_id)
    except Exception as err:
        log.warn("[提取道具] 预生成提示词失败", extra={"prop_id": prop_id, "error": str(err)})


def process_prop_extraction(task_id: str, episode_id: Any, cfg: dict | None = None) -> None:
    with session_scope() as db:
        taskService.update_task_status(db, task_id, "processing", 0, "正在分析剧本...")

        episode = db.execute(
            text("SELECT id, drama_id, script_content FROM episodes WHERE id = :id AND deleted_at IS NULL"),
            {"id": propEntityService.to_int_id(episode_id)},
        ).mappings().first()

        if not episode:
            taskService.update_task_error(db, task_id, "剧集不存在")
            return

        script_content = episode.get("script_content")
        if not script_content or not str(script_content).strip():
            taskService.update_task_error(db, task_id, "剧本内容为空")
            return

        runtime_cfg = cfg or load_config()
        try:
            drama_row = db.execute(
                text("SELECT style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
                {"id": episode["drama_id"]},
            ).mappings().first()
            if drama_row:
                next_cfg = dict(runtime_cfg)
                style_dict = dict(next_cfg.get("style") or {})
                style_dict["default_prop_style"] = ""
                if drama_row.get("metadata"):
                    meta = drama_row["metadata"]
                    meta_dict = json.loads(meta) if isinstance(meta, str) else meta
                    if isinstance(meta_dict, dict) and meta_dict.get("aspect_ratio"):
                        style_dict["default_prop_ratio"] = meta_dict["aspect_ratio"]
                        style_dict["default_image_ratio"] = meta_dict["aspect_ratio"]
                next_cfg["style"] = style_dict
                runtime_cfg = merge_cfg_style_with_drama(next_cfg, dict(drama_row))
        except Exception:
            pass

        system_prompt = promptI18n.get_prop_extraction_prompt(runtime_cfg)
        content_label = "[Script Content]\n" if promptI18n.is_english(runtime_cfg) else "【剧本内容】\n"
        prompt = content_label + str(script_content).strip()

        try:
            response = aiClient.generate_text(
                db,
                log,
                "text",
                prompt,
                system_prompt,
                {
                    "scene_key": "prop_extraction",
                    "max_tokens": 2000,
                    "temperature": 0.3,
                },
            )
        except Exception as err:
            log.error("Prop extraction AI failed", extra={"error": str(err), "task_id": task_id})
            taskService.update_task_error(db, task_id, f"AI 提取失败: {err}")
            return

        try:
            parsed = safe_parse_ai_json(response, log)
            extracted_props = extract_first_array(parsed) or []
        except Exception:
            taskService.update_task_error(db, task_id, "解析 AI 返回的 JSON 失败")
            return

        taskService.update_task_status(db, task_id, "processing", 50, "正在保存道具...")

        propEntityService.soft_delete_props_by_episode_id(db, log, episode_id)

        drama_id = episode["drama_id"]
        created_props: list[dict] = []
        for p in extracted_props:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name") or "").strip()
            if not name:
                continue

            existing = db.execute(
                text("SELECT id FROM props WHERE drama_id = :did AND name = :name AND deleted_at IS NULL"),
                {"did": drama_id, "name": name},
            ).mappings().first()

            if existing:
                now = timestamp()
                db.execute(
                    text(
                        "UPDATE props SET type = :type, description = :desc, prompt = :prompt, "
                        "updated_at = :now WHERE id = :id"
                    ),
                    {
                        "type": str(p.get("type")).strip() if p.get("type") else None,
                        "desc": str(p.get("description")).strip() if p.get("description") else None,
                        "prompt": str(p.get("image_prompt")).strip() if p.get("image_prompt") else None,
                        "now": now,
                        "id": existing["id"],
                    },
                )
                updated = propEntityService.get_by_id(db, existing["id"])
                if updated:
                    created_props.append(updated)
                continue

            prop = propEntityService.create(
                db,
                {
                    "drama_id": drama_id,
                    "episode_id": episode_id,
                    "name": name,
                    "type": str(p.get("type")).strip() if p.get("type") else None,
                    "description": str(p.get("description")).strip() if p.get("description") else None,
                    "prompt": str(p.get("image_prompt")).strip() if p.get("image_prompt") else None,
                },
            )
            if prop:
                created_props.append(prop)
                if not prop.get("prompt") and runtime_cfg:
                    workerService.submit(
                        f"prop_pre_gen_{prop['id']}",
                        _bg_gen_prompt,
                        prop["id"],
                        runtime_cfg,
                    )

        taskService.update_task_result(
            db,
            task_id,
            {
                "props": created_props,
                "count": len(created_props),
                "episode_id": episode_id,
                "drama_id": drama_id,
            },
        )
        log.info(
            "Prop extraction completed",
            extra={"task_id": task_id, "episode_id": episode_id, "count": len(created_props)},
        )


def extract_props_for_episode(db: Session, log_, episode_id: Any, cfg: dict | None = None) -> str:
    episode = db.execute(
        text("SELECT id, drama_id, script_content FROM episodes WHERE id = :id AND deleted_at IS NULL"),
        {"id": propEntityService.to_int_id(episode_id)},
    ).mappings().first()

    if not episode:
        raise ValueError("episode not found")
    if not episode.get("script_content") or not str(episode["script_content"]).strip():
        raise ValueError("剧集剧本内容为空，无法提取道具")

    task = taskService.create_task(db, log_, "prop_extraction", str(episode_id))
    workerService.submit(
        f"prop_extract_{task['id']}",
        process_prop_extraction,
        task["id"],
        episode_id,
        cfg,
    )
    return task["id"]


# 驼峰别名与 Node 兼容
extractPropsForEpisode = extract_props_for_episode
processPropExtraction = process_prop_extraction
