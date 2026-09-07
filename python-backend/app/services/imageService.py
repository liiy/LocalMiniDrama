"""图片库同步端点服务 — 契约翻译 backend-node/src/services/imageService.js（同步端点子集）。

backend-node 的 /images 路由实际读写的是 image_generations 表（不是 images 表）。
仅覆盖不依赖外部图像生成 API 的同步端点：
- list / get / delete / upload（upload 仅建记录，不入队真实生成）
- get_backgrounds_for_episode（仅联表查询 scenes/storyboards）
- create_scene_task（仅建 async_tasks，不入队真实生成）

`create`（POST /images）已接入真实生成链路：建记录后写入 queue_jobs，
由独立 Worker 执行 process_image_generation，服务重启后仍可恢复任务。
`episodeBackgroundsExtract` 仍需 backgroundExtractionService 走真实 AI 提取，未移植。
"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one
from app.services import taskService
from app.services.libraryCommon import js_parse_int, to_int_id


def _now() -> str:
    return timestamp()


def row_to_item(r: dict) -> dict:
    item = {
        "id": r.get("id"),
        "storyboard_id": r.get("storyboard_id"),
        "drama_id": r.get("drama_id"),
        "scene_id": r.get("scene_id"),
        "character_id": r.get("character_id"),
        "provider": r.get("provider"),
        "prompt": r.get("prompt"),
        "model": r.get("model"),
        "image_url": r.get("image_url"),
        "local_path": r.get("local_path"),
        "status": r.get("status"),
        "task_id": r.get("task_id"),
        "error_msg": r.get("error_msg"),
        "frame_type": r.get("frame_type"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "completed_at": r.get("completed_at"),
    }
    if item.get("scene_id") is None:
        item.pop("scene_id", None)
    if item.get("frame_type") is None:
        item.pop("frame_type", None)
    return item


def list_images(db: Session, query: dict | None = None) -> tuple[list[dict], int, int, int]:
    query = query or {}
    where = "FROM image_generations WHERE deleted_at IS NULL"
    params: dict[str, Any] = {}
    if query.get("drama_id"):
        where += " AND drama_id = :drama_id"
        params["drama_id"] = query["drama_id"]
    if query.get("storyboard_id"):
        where += " AND storyboard_id = :storyboard_id"
        params["storyboard_id"] = query["storyboard_id"]
    if query.get("frame_type"):
        where += " AND frame_type = :frame_type"
        params["frame_type"] = query["frame_type"]
    if query.get("status"):
        where += " AND status = :status"
        params["status"] = query["status"]

    total = db.execute(
        __import__("sqlalchemy").text(f"SELECT COUNT(*) AS total {where}"), params
    ).scalar() or 0
    page = max(1, js_parse_int(query.get("page"), 1))
    page_size = min(100, max(1, js_parse_int(query.get("page_size"), 20)))
    offset = (page - 1) * page_size
    p = dict(params)
    p["_limit"] = page_size
    p["_offset"] = offset
    rows = fetch_all(
        db,
        f"SELECT * {where} ORDER BY created_at DESC LIMIT :_limit OFFSET :_offset",
        p,
    )
    return [row_to_item(r) for r in rows], total, page, page_size


def get_image(db: Session, image_id: Any) -> dict | None:
    row = fetch_one(
        db,
        "SELECT * FROM image_generations WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(image_id)},
    )
    return row_to_item(row) if row else None


def delete_image(db: Session, image_id: Any) -> bool:
    """等价 deleteById：软删 image_generations，并解除 storyboards 上的首/尾帧绑定（避免悬空）。"""
    num_id = to_int_id(image_id)
    now = _now()
    try:
        row = fetch_one(
            db,
            "SELECT storyboard_id FROM image_generations WHERE id = :id AND deleted_at IS NULL",
            {"id": num_id},
        )
        if row and row.get("storyboard_id") is not None:
            sid = int(row["storyboard_id"])
            execute(
                db,
                "UPDATE storyboards SET first_frame_image_id = NULL, image_url = NULL, local_path = NULL, updated_at = :now "
                "WHERE id = :sid AND first_frame_image_id = :id",
                {"now": now, "sid": sid, "id": num_id},
            )
            execute(
                db,
                "UPDATE storyboards SET last_frame_image_id = NULL, last_frame_image_url = NULL, last_frame_local_path = NULL, updated_at = :now "
                "WHERE id = :sid AND last_frame_image_id = :id",
                {"now": now, "sid": sid, "id": num_id},
            )
    except Exception:  # noqa: BLE001
        pass

    res = execute(
        db,
        "UPDATE image_generations SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL",
        {"now": now, "id": num_id},
    )
    return res.rowcount > 0


def create_record(db: Session, req: dict) -> dict:
    """等价 upload：仅建 image_generations 记录（status='completed'），并绑定到分镜首尾帧。"""
    now = _now()
    cols = [
        "storyboard_id", "drama_id", "provider", "prompt", "image_url",
        "local_path", "frame_type",
    ]
    col_sql = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    params: dict[str, Any] = {
        "storyboard_id": req.get("storyboard_id"),
        "drama_id": req.get("drama_id") if req.get("drama_id") is not None else 0,
        "provider": req.get("provider") or "upload",
        "prompt": req.get("prompt") or "",
        "image_url": req.get("image_url") or "",
        "local_path": req.get("local_path"),
        "frame_type": req.get("frame_type"),
        "status": "completed",
        "created_at": now,
        "updated_at": now,
    }
    res = execute(
        db,
        f"INSERT INTO image_generations ({col_sql}, status, created_at, updated_at) "
        f"VALUES ({placeholders}, :status, :created_at, :updated_at)",
        params,
    )
    item = get_image(db, res.lastrowid)
    if item and item.get("storyboard_id"):
        try:
            from app.services.storyboardFrameBinding import bind_storyboard_frame_image
            bind_storyboard_frame_image(
                db,
                item["storyboard_id"],
                item.get("frame_type"),
                item["id"],
                item.get("image_url"),
                item.get("local_path"),
            )
        except Exception:  # noqa: BLE001
            pass
    return item


def get_backgrounds_for_episode(db: Session, episode_id: Any) -> list[dict]:
    """等价 getBackgroundsForEpisode：返回 storyboards 关联的 scenes 行（数组，直接作为响应 data）。"""
    ep_id = to_int_id(episode_id)
    return fetch_all(
        db,
        "SELECT s.id as scene_id, s.location, s.time, s.prompt, s.image_url, s.local_path, s.status "
        "FROM storyboards sb "
        "JOIN scenes s ON s.id = sb.scene_id AND s.deleted_at IS NULL "
        "WHERE sb.episode_id = :ep AND sb.deleted_at IS NULL "
        "ORDER BY sb.storyboard_number",
        {"ep": ep_id},
    )


def create_scene_task(db: Session, log, resource_id: Any = None) -> dict:
    """等价 images.js scene 端点：仅建 image_generation 任务，不入队真实生成。返回 { task_id }。"""
    task = taskService.create_task(db, log, "image_generation", resource_id)
    return {"task_id": task["id"]}


# ── create（POST /images）：建任务 + 插入 pending 记录，随后后台跑真实生成 ──

_ASPECT_SIZE_MAP: dict[str, str] = {
    "16:9": "2560x1440",
    "9:16": "1440x2560",
    "1:1": "1920x1920",
    "4:3": "2240x1680",
    "3:4": "1680x2240",
    "21:9": "2940x1260",
}

_LAST_FRAME_TYPES = {"last", "storyboard_last", "tail", "last_frame"}


def _merge_prompt_with_style(prompt: Any, style: Any) -> str:
    base = str(prompt or "").strip()
    style_text = str(style or "").strip()
    if not style_text:
        return base
    if not base:
        return style_text
    if style_text.lower() in base.lower():
        return base
    return base + ", " + style_text


def _aspect_ratio_to_size(aspect_ratio: Any) -> str | None:
    return _ASPECT_SIZE_MAP.get(str(aspect_ratio)) or None


aspect_ratio_to_size = _aspect_ratio_to_size
aspectRatioToSize = _aspect_ratio_to_size


def _is_last_frame_type(frame_type: Any) -> bool:
    if frame_type is None or frame_type == "":
        return False
    return str(frame_type).lower() in _LAST_FRAME_TYPES


def _resolve_use_first_frame_layout_lock(req: dict, frame_type: Any) -> int | None:
    if not _is_last_frame_type(frame_type):
        return None
    v = req.get("use_first_frame_layout_lock")
    if v is False or v == 0 or v == "0":
        return 0
    if v is True or v == 1 or v == "1":
        return 1
    return 1


def create_generation(db: Session, log, req: dict) -> dict:
    """等价 imageService.create：建 image_generation 任务 + 插入 pending 记录。

    返回 { id, task_id, status:'pending', **get_image() }（与 Node 的展开顺序一致）。
    """
    now = _now()
    task = taskService.create_task(db, log, "image_generation", str(req.get("drama_id") or ""))
    task_id = task["id"]
    frame_type = req.get("frame_type")
    scene_id = req.get("scene_id")
    scene_id = to_int_id(scene_id) if scene_id is not None else None
    ref = req.get("reference_images")
    ref_images_json = json.dumps(ref[:10]) if isinstance(ref, list) else None
    merged_prompt = _merge_prompt_with_style(req.get("prompt") or "", req.get("style"))
    req_size = req.get("size") or None
    if not req_size and req.get("aspect_ratio"):
        req_size = _aspect_ratio_to_size(req.get("aspect_ratio"))
    lock = _resolve_use_first_frame_layout_lock(req, frame_type)
    res = execute(
        db,
        """
        INSERT INTO image_generations (
            storyboard_id, drama_id, scene_id, provider, prompt, negative_prompt, model,
            frame_type, reference_images, use_first_frame_layout_lock, size, status, task_id,
            created_at, updated_at
        ) VALUES (
            :storyboard_id, :drama_id, :scene_id, :provider, :prompt, :negative_prompt, :model,
            :frame_type, :reference_images, :lock, :size, 'pending', :task_id,
            :created_at, :updated_at
        )
        """,
        {
            "storyboard_id": req.get("storyboard_id"),
            "drama_id": js_parse_int(req.get("drama_id"), 0) or 0,
            "scene_id": scene_id,
            "provider": req.get("provider") or "openai",
            "prompt": merged_prompt,
            "negative_prompt": req.get("negative_prompt"),
            "model": req.get("model"),
            "frame_type": frame_type,
            "reference_images": ref_images_json,
            "lock": lock,
            "size": req_size,
            "task_id": task_id,
            "created_at": now,
            "updated_at": now,
        },
    )
    image_gen_id = res.lastrowid
    if not image_gen_id:
        raise ValueError("insert failed")
    item = get_image(db, image_gen_id) or {}

    from app.tasks import queue_service

    # 图片业务处理器需要完整 image_generation 记录，因此队列只保存记录 ID，避免复制大段 Prompt。
    queue_service.enqueue_job(
        db,
        {
            "queue_name": "images",
            "task_type": "legacy.image.generate",
            "async_task_id": task_id,
            "resource_id": str(req.get("drama_id") or ""),
            "payload": {"image_generation_id": image_gen_id},
        },
        create_async_task=False,
    )
    # Worker 使用独立 Session，提交后才能看到生成记录与关联任务。
    db.commit()
    return {"id": image_gen_id, "task_id": task_id, "status": "pending", **item}


# ── processImageGeneration：真实图生链路（等价 Node setImmediate 的异步体）──


def resolve_image_size(db: Session, row: dict, cfg: dict | None = None) -> str | None:
    """等价 Node Step3 尺寸：row.size → drama metadata.aspect_ratio → cfg.style.default_image_ratio。"""
    size = row.get("size")
    if size:
        return str(size)

    drama_id = row.get("drama_id")
    if drama_id:
        try:
            drama_row = fetch_one(
                db,
                "SELECT metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
                {"id": to_int_id(drama_id)},
            )
        except Exception:  # noqa: BLE001
            drama_row = None
        meta = (drama_row or {}).get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:  # noqa: BLE001
                meta = None
        if isinstance(meta, dict) and meta.get("aspect_ratio"):
            converted = _aspect_ratio_to_size(meta["aspect_ratio"])
            if converted:
                return converted

    ratio = ((cfg or {}).get("style") or {}).get("default_image_ratio")
    if ratio:
        return _aspect_ratio_to_size(ratio)
    return None


def _parse_reference_images(raw: Any) -> list | None:
    """解析 image_generations.reference_images（JSON 数组字符串 / 已是数组）。"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        return raw or None
    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    return parsed if isinstance(parsed, list) and parsed else None


def _mark_image_failed(db: Session, image_gen_id: Any, err_msg: Any, now: str) -> None:
    """等价 Node 失败分支：无 error_msg 列时降级只更新 status/updated_at。"""
    try:
        execute(
            db,
            "UPDATE image_generations SET status = :s, error_msg = :e, updated_at = :t WHERE id = :id",
            {"s": "failed", "e": str(err_msg or "")[:500], "t": now, "id": image_gen_id},
        )
    except Exception as e:  # noqa: BLE001
        if "error_msg" in str(e):
            execute(
                db,
                "UPDATE image_generations SET status = :s, updated_at = :t WHERE id = :id",
                {"s": "failed", "t": now, "id": image_gen_id},
            )
        else:
            raise


def _mark_image_completed(db: Session, image_gen_id: Any, image_url: Any, local_path: Any, now: str) -> None:
    """等价 Node Step6：无 completed_at 列时降级不写该列。"""
    try:
        execute(
            db,
            "UPDATE image_generations SET status = :s, image_url = :u, local_path = :lp, "
            "completed_at = :c, updated_at = :c WHERE id = :id",
            {"s": "completed", "u": image_url, "lp": local_path, "c": now, "id": image_gen_id},
        )
    except Exception as e:  # noqa: BLE001
        if "completed_at" in str(e):
            execute(
                db,
                "UPDATE image_generations SET status = :s, image_url = :u, local_path = :lp, "
                "updated_at = :c WHERE id = :id",
                {"s": "completed", "u": image_url, "lp": local_path, "c": now, "id": image_gen_id},
            )
        else:
            raise


def _sync_scene_image(db: Session, row: dict, image_url: Any, local_path: Any, now: str) -> None:
    """等价 Node Step6 场景回写：旧主图追加到 extra_images，无该列时降级。"""
    scene_id = row.get("scene_id")
    old = fetch_one(
        db,
        "SELECT local_path, image_url, extra_images FROM scenes WHERE id = :id",
        {"id": scene_id},
    )
    old_path = (old or {}).get("local_path") or (old or {}).get("image_url") or ""
    extras: list = []
    try:
        parsed = json.loads((old or {}).get("extra_images") or "[]")
        extras = parsed if isinstance(parsed, list) else []
    except Exception:  # noqa: BLE001
        extras = []
    if old_path and old_path not in extras:
        extras.append(old_path)
    extra_json = json.dumps(extras, ensure_ascii=False) if extras else None
    try:
        execute(
            db,
            "UPDATE scenes SET image_url = :u, local_path = :lp, extra_images = :ex, "
            "status = 'generated', updated_at = :t WHERE id = :id",
            {"u": image_url, "lp": local_path, "ex": extra_json, "t": now, "id": scene_id},
        )
    except Exception as e:  # noqa: BLE001
        if "extra_images" in str(e):
            execute(
                db,
                "UPDATE scenes SET image_url = :u, local_path = :lp, status = 'generated', "
                "updated_at = :t WHERE id = :id",
                {"u": image_url, "lp": local_path, "t": now, "id": scene_id},
            )
        else:
            raise


def _propagate_image_error(db: Session, row: dict, err_msg: Any, now: str) -> None:
    """等价 Node 失败分支：把错误同步到 scenes / storyboards（失败不影响主流程）。"""
    if row.get("scene_id") is not None:
        try:
            execute(
                db,
                "UPDATE scenes SET error_msg = :e, updated_at = :t WHERE id = :id",
                {"e": str(err_msg or "")[:500], "t": now, "id": row["scene_id"]},
            )
        except Exception:  # noqa: BLE001
            pass
    if row.get("storyboard_id") is not None:
        try:
            execute(
                db,
                "UPDATE storyboards SET error_msg = :e, updated_at = :t WHERE id = :id",
                {"e": str(err_msg or "")[:500], "t": now, "id": row["storyboard_id"]},
            )
        except Exception:  # noqa: BLE001
            pass


def process_image_generation(db: Session, log, image_gen_id: Any) -> None:
    """等价 Node imageService.processImageGeneration：真实图生链路。

    由持久化队列 Worker 触发，也可在测试里直接同步调用。
    """
    from app.core.config import load_config
    from app.services import imageClient, storageLayout, uploadService, workerService

    row: dict | None = None
    if not workerService.begin("image_gen", image_gen_id):
        log.info("[图生] 已在生成中，跳过重复提交", extra={"id": image_gen_id})
        return

    try:
        row = fetch_one(
            db,
            "SELECT * FROM image_generations WHERE id = :id AND deleted_at IS NULL",
            {"id": to_int_id(image_gen_id)},
        )
        if not row:
            log.error("[图生] 记录不存在", extra={"id": image_gen_id})
            return
        if row.get("status") != "pending":
            log.info("[图生] 已被处理，跳过", extra={"id": image_gen_id, "status": row.get("status")})
            return

        now = _now()
        execute(
            db,
            "UPDATE image_generations SET status = :s, updated_at = :t WHERE id = :id",
            {"s": "processing", "t": now, "id": image_gen_id},
        )
        db.commit()

        cfg = load_config()
        storage_cfg = cfg.get("storage") or {}
        files_base_url = str(storage_cfg.get("base_url") or "").rstrip("/")
        raw_storage = storage_cfg.get("local_path") or "./data/storage"
        storage_local_path = raw_storage if os.path.isabs(raw_storage) else os.path.join(os.getcwd(), raw_storage)

        image_service_type = "storyboard_image" if row.get("storyboard_id") else "image"
        image_size = resolve_image_size(db, row, cfg)
        reference_urls = _parse_reference_images(row.get("reference_images"))

        final_prompt = row.get("prompt") or ""
        frame_type_str = str(row.get("frame_type") or "").lower()
        if (
            frame_type_str in ("first", "last", "key", "storyboard_first", "storyboard_last")
            and row.get("storyboard_id")
            and final_prompt
        ):
            try:
                from app.services import framePromptService
                from app.utils.framePromptSanitize import parse_names_from_anchor_lines, sanitize_frame_prompt

                anchors = framePromptService.load_storyboard_character_names(db, row["storyboard_id"])
                allowed = parse_names_from_anchor_lines(anchors)
                all_drama = framePromptService.load_drama_character_names_for_storyboard(db, row["storyboard_id"])
                sanitized = sanitize_frame_prompt(
                    final_prompt,
                    allowed,
                    all_drama,
                    {
                        "log": log,
                        "source": "image_generation",
                        "storyboard_id": row["storyboard_id"],
                        "frame_kind": row.get("frame_type"),
                        "image_gen_id": image_gen_id,
                    },
                )
                if sanitized:
                    final_prompt = sanitized
            except Exception as sanitize_err:
                log.warn("[图生] 首尾帧 prompt 清洗跳过", extra={"id": image_gen_id, "error": str(sanitize_err)})

        log.info("[图生] 开始", extra={
            "id": image_gen_id,
            "image_service_type": image_service_type,
            "size": image_size,
            "refs": len(reference_urls or []),
        })

        result = imageClient.call_image_api(db, log, {
            "prompt": final_prompt,
            "model": row.get("model"),
            "size": image_size,
            "quality": row.get("quality"),
            "drama_id": row.get("drama_id"),
            "character_id": row.get("character_id"),
            "image_gen_id": image_gen_id,
            "imageServiceType": image_service_type,
            "reference_image_urls": reference_urls,
            "files_base_url": files_base_url,
            "storage_local_path": storage_local_path,
            "user_negative_prompt": row.get("negative_prompt"),
        })

        now2 = _now()
        if result.get("error"):
            _mark_image_failed(db, image_gen_id, result["error"], now2)
            if row.get("task_id"):
                taskService.update_task_error(db, row["task_id"], result["error"])
            _propagate_image_error(db, row, result["error"], now2)
            db.commit()
            log.error("[图生] API返回错误", extra={"id": image_gen_id, "error": result["error"]})
            return

        local_path = None
        try:
            category = (
                "scenes" if row.get("scene_id") is not None
                else "characters" if row.get("character_id") is not None
                else "images"
            )
            project_subdir = storageLayout.get_project_storage_subdir(db, row.get("drama_id"))
            local_path = uploadService.download_image_to_local(
                storage_local_path, result.get("image_url"), category, log, "ig", project_subdir
            )
        except Exception as e:  # noqa: BLE001
            log.warn("[图生] 保存失败（不影响结果）", extra={"id": image_gen_id, "reason": str(e)})

        # 入库的 image_url 优先指向本地静态路径，避免前端仍用厂商返回的 data URL
        persisted_url = f"/static/{str(local_path).lstrip('/')}" if local_path else result.get("image_url")

        _mark_image_completed(db, image_gen_id, persisted_url, local_path, now2)
        if row.get("task_id"):
            taskService.update_task_result(db, row["task_id"], {
                "image_generation_id": image_gen_id,
                "image_url": persisted_url,
                "local_path": local_path,
                "status": "completed",
            })
        if row.get("scene_id") is not None and row.get("storyboard_id") is None:
            _sync_scene_image(db, row, persisted_url, local_path, now2)

        if row.get("storyboard_id") and row.get("frame_type") not in ("quad_grid", "nine_grid"):
            try:
                from app.services.storyboardFrameBinding import bind_storyboard_frame_image

                bind_storyboard_frame_image(
                    db,
                    row["storyboard_id"],
                    row.get("frame_type"),
                    image_gen_id,
                    persisted_url,
                    local_path,
                )
            except Exception as bind_err:
                log.warn("[图生] 分镜首尾帧绑定失败", extra={"id": image_gen_id, "error": str(bind_err)})

        db.commit()
        log.info("[图生] 完成", extra={"id": image_gen_id, "local_path": local_path})
    except Exception as e:  # noqa: BLE001
        db.rollback()
        err_msg = str(e)[:500] or "Unknown error"
        try:
            _mark_image_failed(db, image_gen_id, err_msg, _now())
            if row and row.get("task_id"):
                taskService.update_task_error(db, row["task_id"], err_msg)
            if row:
                _propagate_image_error(db, row, err_msg, _now())
            db.commit()
        except Exception:  # noqa: BLE001
            pass
        log.error("[图生] 异常", extra={"id": image_gen_id, "error": err_msg})
    finally:
        workerService.end("image_gen", image_gen_id)


def _process_image_job(image_gen_id) -> None:
    """worker 线程入口：自建 Session 执行图生（Session 非线程安全）。"""
    from app.core.logger import get_logger
    from app.services import workerService

    log = get_logger("lmd.imageService")
    try:
        with workerService.session_scope() as db:
            process_image_generation(db, log, image_gen_id)
    except Exception as e:  # noqa: BLE001
        log.error("Image generation job failed", extra={"image_gen_id": image_gen_id, "reason": str(e)})
