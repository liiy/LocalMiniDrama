"""场景提取服务（background_extraction）— 与 backend-node/src/services/backgroundExtractionService.js 1:1 对齐。

包含 extract_backgrounds_for_episode（任务创建与去重）以及 process_background_extraction（AI 提取、翻译、场景持久化与异步预生成）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.db.session import fetch_one, session_scope
from app.services import aiClient, promptI18n, sceneService, taskService, workerService
from app.utils.dramaStyleMerge import merge_cfg_style_with_drama
from app.utils.safeJson import extract_first_array, safe_parse_ai_json

log = get_logger("lmd.backgroundExtraction")


def normalize_language(language: Any) -> str:
    lang = str(language or "").strip().lower()
    return lang if lang in ("zh", "en") else ""


def has_chinese(text: str | None) -> bool:
    if not text:
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def with_language(cfg: dict | None, language: str) -> dict:
    if not language:
        return cfg or {}
    base = dict(cfg or {})
    app_cfg = dict(base.get("app") or {})
    app_cfg["language"] = language
    base["app"] = app_cfg
    return base


def translate_prompt_to_chinese(db: Session, log_, model: str | None, prompt: str) -> str:
    user_prompt = (
        "请将以下场景图像提示词翻译为中文，保留风格词或比例（如 realistic、16:9）原样，直接返回翻译后的中文提示词，不要解释：\n"
        + prompt
    )
    text = aiClient.generate_text(
        db,
        log_,
        "text",
        user_prompt,
        "",
        {
            "scene_key": "scene_extraction",
            "model": model or None,
            "temperature": 0.2,
            "max_tokens": 400,
        },
    )
    return str(text or "").strip()


def extract_backgrounds_from_script(
    db: Session,
    cfg: dict,
    log_,
    script_content: str,
    drama_id: Any,
    model: str | None,
    style: str | None,
) -> list[dict[str, Any]]:
    if not script_content or not script_content.strip():
        return []
    system_prompt = promptI18n.get_scene_extraction_prompt(cfg, style)
    prompt = ("[Script Content]\n" if promptI18n.get_language(cfg) == "en" else "【剧本内容】\n") + script_content
    text = aiClient.generate_text(
        db,
        log_,
        "text",
        prompt,
        system_prompt,
        {"scene_key": "scene_extraction", "model": model or None, "temperature": 0.7},
    )
    try:
        parsed = safe_parse_ai_json(text, log_)
        parsed_list = extract_first_array(parsed) or []
    except Exception:
        parsed_list = []

    result: list[dict[str, Any]] = []
    for b in parsed_list:
        if isinstance(b, dict):
            result.append(
                {
                    "location": b.get("location") or "",
                    "time": b.get("time") or "",
                    "prompt": b.get("prompt") or "",
                    "atmosphere": b.get("atmosphere"),
                }
            )
    return result


def _bg_generate_scene_prompt(scene_id: int, captured_style: Any, effective_cfg: dict) -> None:
    try:
        with session_scope() as db_worker:
            sceneService.generate_scene_prompt_only(db_worker, log, effective_cfg, scene_id, None, captured_style)
    except Exception as err:
        log.warning("[提取场景] 预生成polished_prompt失败", extra={"scene_id": scene_id, "error": str(err)})


def process_background_extraction(
    task_id: str,
    episode_id: Any,
    model: str | None = None,
    style: str | None = None,
    language: str | None = None,
    cfg: dict | None = None,
) -> None:
    try:
        with session_scope() as db:
            taskService.update_task_status(db, task_id, "processing", 0, "正在提取场景信息...")
            episode = fetch_one(
                db,
                "SELECT id, drama_id, script_content FROM episodes WHERE id = :id AND deleted_at IS NULL",
                {"id": int(episode_id)},
            )
            if not episode:
                taskService.update_task_status(db, task_id, "failed", 0, "剧集信息不存在")
                return
            script_content = episode.get("script_content")
            if not script_content or not str(script_content).strip():
                taskService.update_task_status(db, task_id, "failed", 0, "剧本内容为空")
                return

            cfg = cfg or {}
            effective_cfg = dict(cfg)
            try:
                drama_row = fetch_one(
                    db,
                    "SELECT style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
                    {"id": episode["drama_id"]},
                )
                param_style = str(style or "").strip()
                next_cfg = {**cfg, "style": dict(cfg.get("style") or {})}
                if drama_row and drama_row.get("metadata"):
                    meta_raw = drama_row["metadata"]
                    meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                    if isinstance(meta, dict) and meta.get("aspect_ratio"):
                        next_cfg["style"]["default_image_ratio"] = meta["aspect_ratio"]
                if param_style:
                    next_cfg["style"]["default_style_zh"] = param_style
                    next_cfg["style"]["default_style_en"] = param_style
                    next_cfg["style"]["default_style"] = param_style
                    effective_cfg = next_cfg
                else:
                    effective_cfg = merge_cfg_style_with_drama(next_cfg, drama_row or {})
                style = (
                    param_style
                    or (effective_cfg.get("style") or {}).get("default_style_en")
                    or (effective_cfg.get("style") or {}).get("default_style")
                    or style
                )
            except Exception:
                pass

            req_lang = normalize_language(language)
            cfg_lang = normalize_language(promptI18n.get_language(effective_cfg))
            effective_lang = req_lang or cfg_lang
            if not req_lang and effective_lang == "en" and has_chinese(str(script_content)):
                effective_lang = "zh"
            cfg_for_prompt = with_language(effective_cfg, effective_lang)

            try:
                backgrounds_info = extract_backgrounds_from_script(
                    db, cfg_for_prompt, log, str(script_content), episode["drama_id"], model, style
                )
            except Exception as err:
                log.error("Background extraction AI failed", extra={"error": str(err), "task_id": task_id})
                taskService.update_task_status(db, task_id, "failed", 0, f"AI提取场景失败: {err}")
                return

            if effective_lang == "zh":
                translated = []
                for bg in backgrounds_info or []:
                    orig = str(bg.get("prompt") or "").strip()
                    if not orig or has_chinese(orig):
                        translated.append(bg)
                        continue
                    try:
                        trans = translate_prompt_to_chinese(db, log, model, orig)
                        if trans:
                            bg["prompt"] = trans
                    except Exception as err:
                        log.warning("Background prompt translate failed", extra={"error": str(err), "task_id": task_id})
                    translated.append(bg)
                backgrounds_info = translated

            sceneService.delete_scenes_by_episode_id(db, log, episode_id)
            scenes: list[dict[str, Any]] = []
            for bg in backgrounds_info:
                scene = sceneService.create_scene_for_episode(
                    db,
                    log,
                    episode["drama_id"],
                    episode_id,
                    {"location": bg.get("location"), "time": bg.get("time"), "prompt": bg.get("prompt")},
                )
                if scene:
                    scenes.append(scene)
                    if effective_cfg:
                        captured_style = style
                        workerService.submit(_bg_generate_scene_prompt, scene["id"], captured_style, effective_cfg)

            taskService.update_task_result(
                db,
                task_id,
                {
                    "scenes": scenes,
                    "count": len(scenes),
                    "episode_id": episode_id,
                    "drama_id": episode["drama_id"],
                },
            )
            log.info(
                "Background extraction completed",
                extra={"task_id": task_id, "episode_id": episode_id, "count": len(scenes)},
            )
    except Exception as fatal_err:
        log.error("processBackgroundExtraction fatal", extra={"error": str(fatal_err), "task_id": task_id})
        with session_scope() as db_err:
            taskService.update_task_error(db_err, task_id, str(fatal_err) or "场景提取失败")


def extract_backgrounds_for_episode(
    db: Session,
    cfg: dict[str, Any],
    log_,
    episode_id: Any,
    model: Optional[str] = None,
    style: Optional[str] = None,
    language: Optional[str] = None,
) -> Any:
    """提取剧集场景背景，返回 task_id 并异步启动处理。"""
    ep = fetch_one(
        db,
        "SELECT id, drama_id, script_content FROM episodes WHERE id = :id AND deleted_at IS NULL",
        {"id": int(episode_id)},
    )
    if not ep:
        raise ValueError("episode not found")
    if not (ep.get("script_content") or "").strip():
        raise ValueError("episode has no script content")

    run_cfg = dict(cfg or {})
    if ep.get("drama_id"):
        try:
            drama_row = fetch_one(
                db,
                "SELECT metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
                {"id": ep["drama_id"]},
            )
            meta = None
            if drama_row and drama_row.get("metadata"):
                raw = drama_row["metadata"]
                if isinstance(raw, str):
                    try:
                        meta = json.loads(raw)
                    except Exception:
                        meta = None
                else:
                    meta = raw
            if isinstance(meta, dict) and meta.get("aspect_ratio"):
                style_cfg = dict((cfg or {}).get("style") or {})
                style_cfg["default_image_ratio"] = meta["aspect_ratio"]
                run_cfg = {**(cfg or {}), "style": style_cfg}
        except Exception:
            pass

    existing = fetch_one(
        db,
        """
        SELECT id FROM async_tasks
        WHERE resource_id = :rid AND type = 'background_extraction'
          AND status IN ('pending', 'processing') AND deleted_at IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        {"rid": str(episode_id)},
    )
    if existing:
        log.info("Background extraction already running", extra={"task_id": existing["id"], "episode_id": episode_id})
        return existing["id"]

    task = taskService.create_task(db, log_, "background_extraction", str(episode_id))
    task_id = task["id"] if isinstance(task, dict) else str(task)

    workerService.submit(
        process_background_extraction,
        task_id,
        episode_id,
        model=model,
        style=style,
        language=language,
        cfg=run_cfg,
    )
    return task_id


# 驼峰别名与 Node 兼容
extractBackgroundsForEpisode = extract_backgrounds_for_episode
processBackgroundExtraction = process_background_extraction
