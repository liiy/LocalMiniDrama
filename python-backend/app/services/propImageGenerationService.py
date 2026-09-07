"""道具图片生成服务，等价 Node services/propImageGenerationService.js。

生成道具参考图，支持异步任务、配置合并、落盘下载及多图历史记录。
"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import session_scope
from app.services import imageClient, propEntityService, storageLayout, taskService, uploadService
from app.services.imageService import aspect_ratio_to_size
from app.utils.dramaStyleMerge import merge_cfg_style_with_drama

log = get_logger("lmd.propImageGenerationService")


def append_prompt(base: str, extra: str) -> str:
    add = (extra or "").strip()
    if not add:
        return (base or "").strip()
    current = (base or "").strip()
    if not current:
        return add
    if add.lower() in current.lower():
        return current
    return f"{current}, {add}"


def process_prop_image_generation(task_id: str, prop_id: int, opts: dict | None = None) -> None:
    opts = opts or {}
    with session_scope() as db:
        taskService.update_task_status(db, task_id, "processing", 0, "正在生成图片...")

        prop = propEntityService.get_by_id(db, prop_id)
        if not prop:
            taskService.update_task_error(db, task_id, "道具不存在")
            return
        if not prop.get("prompt") or not str(prop["prompt"]).strip():
            taskService.update_task_error(db, task_id, "道具没有图片提示词")
            return

        cfg = load_config()
        if prop.get("drama_id"):
            try:
                dr = db.execute(
                    text("SELECT style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
                    {"id": prop["drama_id"]},
                ).mappings().first()
                if dr:
                    cfg = merge_cfg_style_with_drama(cfg, dict(dr))
            except Exception:
                pass

        style_override = str(opts.get("style") or "").strip()
        base_style = style_override or (
            (cfg.get("style") or {}).get("default_style_en")
            or (cfg.get("style") or {}).get("default_style")
            or ""
        )
        style = append_prompt("", base_style)
        if not style_override:
            style = append_prompt(style, (cfg.get("style") or {}).get("default_prop_style") or "")

        image_size = None
        if prop.get("drama_id"):
            try:
                drama_row = db.execute(
                    text("SELECT metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
                    {"id": prop["drama_id"]},
                ).mappings().first()
                if drama_row and drama_row.get("metadata"):
                    meta = drama_row["metadata"]
                    meta_dict = json.loads(meta) if isinstance(meta, str) else meta
                    if isinstance(meta_dict, dict) and meta_dict.get("aspect_ratio"):
                        image_size = aspect_ratio_to_size(meta_dict["aspect_ratio"])
            except Exception:
                pass

        if not image_size:
            image_size = (cfg.get("style") or {}).get("default_image_size") or "1920x1920"

        full_prompt = append_prompt(str(prop["prompt"]).strip(), style)
        model = str(opts.get("model") or "").strip() or None
        preferred_provider = None if model else (cfg.get("ai") or {}).get("default_image_provider")
        user_neg = imageClient.resolve_asset_user_negative_for_api(model, prop.get("negative_prompt"))

        try:
            result = imageClient.call_image_api(
                db,
                log,
                {
                    "prompt": full_prompt,
                    "size": image_size,
                    "drama_id": prop.get("drama_id"),
                    "model": model or None,
                    "preferred_provider": preferred_provider or None,
                    "user_negative_prompt": user_neg or None,
                },
            )
        except Exception as err:
            err_msg = f"图片生成请求失败: {err}"
            log.error("Prop image API failed", extra={"prop_id": prop_id, "error": str(err)})
            taskService.update_task_error(db, task_id, err_msg)
            try:
                db.execute(
                    text("UPDATE props SET error_msg = :msg, updated_at = :now WHERE id = :id"),
                    {"msg": err_msg, "now": timestamp(), "id": prop_id},
                )
            except Exception:
                pass
            return

        if result.get("error"):
            taskService.update_task_error(db, task_id, result["error"])
            try:
                db.execute(
                    text("UPDATE props SET error_msg = :msg, updated_at = :now WHERE id = :id"),
                    {"msg": result["error"], "now": timestamp(), "id": prop_id},
                )
            except Exception:
                pass
            return

        image_url = result.get("image_url")
        if not image_url:
            err_msg = "未返回图片地址"
            taskService.update_task_error(db, task_id, err_msg)
            try:
                db.execute(
                    text("UPDATE props SET error_msg = :msg, updated_at = :now WHERE id = :id"),
                    {"msg": err_msg, "now": timestamp(), "id": prop_id},
                )
            except Exception:
                pass
            return

        taskService.update_task_status(db, task_id, "processing", 80, "正在保存图片...")

        local_path = None
        try:
            raw_sp = (cfg.get("storage") or {}).get("local_path") or "./data/storage"
            storage_path = raw_sp if os.path.isabs(raw_sp) else os.path.join(os.getcwd(), raw_sp)
            project_subdir = storageLayout.get_project_storage_subdir(db, prop.get("drama_id"))
            local_path = uploadService.download_image_to_local(
                storage_path,
                image_url,
                "props",
                log,
                f"prop_{prop_id}",
                project_subdir,
            )
        except Exception as e:
            log.warn("Failed to download prop image to local", extra={"error": str(e)})

        now = timestamp()
        old_prop = db.execute(
            text("SELECT local_path, image_url, extra_images FROM props WHERE id = :id"),
            {"id": prop_id},
        ).mappings().first()
        old_path = (old_prop.get("local_path") or old_prop.get("image_url") or "") if old_prop else ""

        extras = []
        if old_prop and old_prop.get("extra_images"):
            try:
                extras = json.loads(old_prop["extra_images"])
                if not isinstance(extras, list):
                    extras = []
            except Exception:
                extras = []
        if old_path and old_path not in extras:
            extras.append(old_path)
        extra_json = json.dumps(extras, ensure_ascii=False) if extras else None

        try:
            db.execute(
                text(
                    "UPDATE props SET image_url = :url, local_path = :lp, extra_images = :extra, updated_at = :now "
                    "WHERE id = :id"
                ),
                {"url": image_url, "lp": local_path, "extra": extra_json, "now": now, "id": prop_id},
            )
        except Exception as e:
            if "extra_images" in str(e):
                db.execute(
                    text(
                        "UPDATE props SET image_url = :url, local_path = :lp, updated_at = :now WHERE id = :id"
                    ),
                    {"url": image_url, "lp": local_path, "now": now, "id": prop_id},
                )
            else:
                raise

        taskService.update_task_result(
            db,
            task_id,
            {
                "image_url": image_url,
                "local_path": local_path,
                "prop_id": prop_id,
            },
        )
        log.info(
            "Prop image generation completed",
            extra={"prop_id": prop_id, "image_url": image_url, "local_path": local_path},
        )


def generate_prop_image(db: Session, log_, prop_id: int, opts: dict | None = None) -> str:
    prop = propEntityService.get_by_id(db, prop_id)
    if not prop:
        raise ValueError("道具不存在")
    if not prop.get("prompt") or not str(prop["prompt"]).strip():
        raise ValueError("道具没有图片提示词")

    task = taskService.create_task(db, log_, "prop_image_generation", str(prop_id))
    from app.tasks import queue_service

    queue_service.enqueue_job(
        db,
        {
            "queue_name": "images",
            "task_type": "legacy.prop_image.generate",
            "async_task_id": task["id"],
            "resource_id": str(prop_id),
            "payload": {"prop_id": prop_id, "options": opts or {}},
        },
        create_async_task=False,
    )
    db.commit()
    return task["id"]


# 驼峰别名与 Node 兼容
generatePropImage = generate_prop_image
processPropImageGeneration = process_prop_image_generation
