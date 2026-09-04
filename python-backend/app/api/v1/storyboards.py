"""/api/v1/storyboards — 契约翻译 backend-node/src/routes/storyboards.js（P2 纯 CRUD）。

- POST   /storyboards                  → 500 err.message | 201 sb
- POST   /storyboards/:id/insert-before→ 404 '目标分镜不存在' | 201 sb
- GET    /storyboards/:id              → 404 '分镜不存在' | sb
- PUT    /storyboards/:id              → 404 | sb
- DELETE /storyboards/:id              → 404 | { message: '删除成功' }
- POST   /storyboards/:id/props        → { message: '关联成功' }
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import created, not_found, success, timestamp
from app.db.session import execute, get_db, fetch_all, fetch_one
from app.services import propEntityService as propSvc
from app.services import storyboardEntityService as svc
from app.services import tailFrameLinkService as tailSvc
from app.services import angleService as angleSvc
from app.services import framePromptService as framePromptSvc
from app.services import taskService as taskSvc
from app.services import universalSegmentPromptBundle as uniSegBundle
from app.services import aiClient, promptI18n
from app.services.universalSegmentDurationNormalize import (
    normalize_universal_segment_at_image_spacing,
    normalize_universal_segment_shot_durations,
)
from app.services.libraryCommon import to_int_id

# 内存态配置（与 upload.py 一致，等价 Node app.js 启动时 loadConfig 一次并闭包传递）
_CFG: dict[str, Any] = {}


def init_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = cfg

router = APIRouter(tags=["storyboards"])
log = get_logger("lmd.storyboards")


@router.post("/storyboards", status_code=201)
def create(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    return created(svc.create_storyboard(db, payload or {}))


@router.post("/storyboards/{storyboard_id}/insert-before", status_code=201)
def insert_before(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    sb = svc.insert_before_storyboard(db, storyboard_id)
    if not sb:
        raise not_found("目标分镜不存在")
    return created(sb)


@router.get("/storyboards/{storyboard_id}")
def get_one(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    sb = svc.get_storyboard_by_id(db, storyboard_id)
    if not sb:
        raise not_found("分镜不存在")
    return success(sb)


@router.put("/storyboards/{storyboard_id}")
def update(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    sb = svc.update_storyboard(db, storyboard_id, payload or {})
    if not sb:
        raise not_found("分镜不存在")
    return success(sb)


@router.delete("/storyboards/{storyboard_id}")
def delete(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    if not svc.delete_storyboard(db, storyboard_id):
        raise not_found("分镜不存在")
    return success({"message": "删除成功"})


@router.post("/storyboards/{storyboard_id}/props")
def associate_props(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    prop_ids = body["prop_ids"] if isinstance(body.get("prop_ids"), list) else []
    propSvc.associate_with_storyboard(db, storyboard_id, prop_ids)
    return success({"message": "关联成功"})


@router.post("/storyboards/batch-infer-params")
def batch_infer_params(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    episode_id = body.get("episode_id") or body.get("episodeId")
    overwrite = bool(body.get("overwrite"))
    if not episode_id:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "episode_id 必填"}})

    rows = fetch_all(
        db,
        """
        SELECT id, angle_s, shot_type, atmosphere, time, description, action, movement,
               lighting_style, depth_of_field
        FROM storyboards WHERE episode_id = :ep AND deleted_at IS NULL
        ORDER BY storyboard_number ASC
        """,
        {"ep": int(episode_id)},
    )

    now = timestamp()
    updated = 0
    for row in rows:
        inferred = angleSvc.infer_photography_params(row)
        if overwrite:
            if inferred["movement"] or inferred["lighting_style"] or inferred["depth_of_field"]:
                execute(
                    db,
                    """
                    UPDATE storyboards
                    SET movement = :m, lighting_style = :l, depth_of_field = :d, updated_at = :t
                    WHERE id = :id
                    """,
                    {"m": inferred["movement"], "l": inferred["lighting_style"],
                     "d": inferred["depth_of_field"], "t": now, "id": row["id"]},
                )
                updated += 1
        else:
            new_movement = inferred["movement"] if not row.get("movement") else None
            new_lighting = inferred["lighting_style"] if not row.get("lighting_style") else None
            new_dof = inferred["depth_of_field"] if not row.get("depth_of_field") else None
            if new_movement or new_lighting or new_dof:
                execute(
                    db,
                    """
                    UPDATE storyboards
                    SET movement = COALESCE(:m, movement),
                        lighting_style = COALESCE(:l, lighting_style),
                        depth_of_field = COALESCE(:d, depth_of_field),
                        updated_at = :t
                    WHERE id = :id
                    """,
                    {"m": new_movement, "l": new_lighting, "d": new_dof, "t": now, "id": row["id"]},
                )
                updated += 1

    return success({"total": len(rows), "updated": updated})


@router.post("/storyboards/{storyboard_id}/link-tail-frame")
def link_tail_frame(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    sb_id = to_int_id(storyboard_id)
    drama_id = body.get("drama_id")
    if not sb_id or not drama_id:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少必要参数"}})

    try:
        result = tailSvc.link_tail_frame(db, _CFG, sb_id, drama_id)
        return success(result)
    except KeyError:
        return JSONResponse(status_code=404, content={"error": "分镜不存在"})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except RuntimeError as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        log.error("storyboards link-tail-frame", {"error": str(e)})
        return JSONResponse(status_code=500, content={"error": str(e) or "尾帧衔接失败"})


@router.get("/storyboards/{storyboard_id}/frame-prompts")
def get_frame_prompts(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少分镜 id"}})
    try:
        rows = framePromptSvc.get_frame_prompts(db, sb_id)
        return success({"frame_prompts": rows})
    except Exception as e:  # noqa: BLE001
        log.error("storyboards frame-prompts get", {"error": str(e)})
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.put("/storyboards/{storyboard_id}/frame-prompts/{frame_type}")
def save_frame_prompt(storyboard_id: str, frame_type: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少分镜 id"}})
    valid_types = ["first", "key", "last", "panel", "action"]
    if frame_type not in valid_types:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "不支持的 frame_type"}})
    body = payload or {}
    prompt = body["prompt"] if isinstance(body.get("prompt"), str) else ""
    description = body["description"] if isinstance(body.get("description"), str) else None
    layout = body["layout"] if isinstance(body.get("layout"), str) else None
    if not (prompt or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "prompt 不能为空"}})
    try:
        framePromptSvc.save_frame_prompt(db, sb_id, frame_type, prompt, description, layout)
        return success({"message": "保存成功", "frame_type": frame_type})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": str(e)}})
    except Exception as e:  # noqa: BLE001
        log.error("storyboards frame-prompt-save", {"error": str(e)})
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/storyboards/{storyboard_id}/frame-prompt")
def generate_frame_prompt(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少分镜 id"}})
    body = payload or {}
    frame_type = body.get("frame_type") or "first"
    # 分镜存在性校验（与 Node generateFramePrompt 顺序一致：先校验分镜再校验 frame_type）
    sb = fetch_one(db, "SELECT id FROM storyboards WHERE id = :id AND deleted_at IS NULL", {"id": sb_id})
    if not sb:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "分镜不存在"}})
    if frame_type not in ["first", "key", "last", "panel", "action"]:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "不支持的 frame_type"}})
    try:
        task_id = framePromptSvc.generate_frame_prompt(
            db,
            log,
            sb_id,
            frame_type,
            body.get("panel_count") or 0,
            body.get("model"),
        )
        return success({
            "task_id": task_id,
            "status": "pending",
            "message": "帧提示词生成任务已创建，正在后台处理...",
        })
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": str(e)}})
    except Exception as e:  # noqa: BLE001
        log.error("storyboards frame-prompt", {"error": str(e)})
        return JSONResponse(status_code=500, content={"error": str(e)})


def _do_episode_storyboards_generate(episode_id: str, payload: dict, db: Session) -> dict:
    ep_id = to_int_id(episode_id)
    if not ep_id:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少剧集 id"}})
    body = payload or {}
    ep = fetch_one(
        db,
        "SELECT id, script_content, description, drama_id FROM episodes WHERE id = :id AND deleted_at IS NULL",
        {"id": ep_id},
    )
    if not ep:
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "剧集不存在或无权限访问"}})
    script_content = (ep.get("script_content") or "").strip() or (ep.get("description") or "").strip()
    if not script_content:
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "剧本内容为空，请先生成剧集内容"}})
    try:
        from app.services import episodeStoryboardService
        res = episodeStoryboardService.generate_storyboard(
            db,
            log,
            ep_id,
            model=body.get("model"),
            style=body.get("style"),
            storyboard_count=body.get("storyboard_count"),
            video_duration=body.get("video_duration"),
            aspect_ratio=body.get("aspect_ratio"),
            include_narration=body.get("include_narration"),
            universal_omni=body.get("universal_omni"),
        )
        return success(res)
    except Exception as e:  # noqa: BLE001
        log.error("storyboards episode-generate", {"error": str(e)})
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e) or "分镜生成失败"}})


@router.post("/storyboards/episode/{episode_id}/generate")
def episode_storyboards_generate(episode_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    return _do_episode_storyboards_generate(episode_id, payload or {}, db)


@router.get("/storyboards/episode/{episode_id}/generate")
def episode_storyboards_generate_get(
    episode_id: str,
    model: str | None = None,
    style: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return _do_episode_storyboards_generate(episode_id, {"model": model, "style": style}, db)


@router.post("/storyboards/{storyboard_id}/universal-segment-polish-stream")
def universal_segment_polish_stream(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js polishUniversalSegmentStream 的同步校验分支。

    - draft_universal_segment_text 为空 → 400 '请先填写或生成全能片段描述后再润色（编辑器内容不能为空）'

    之后为 AI 流式（NDJSON）返回，未移植。
    """
    body = payload or {}
    sb_id = to_int_id(storyboard_id)
    draft_raw = body.get("draft_universal_segment_text")
    draft = str(draft_raw).strip() if draft_raw is not None else ""
    if not draft:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "请先填写或生成全能片段描述后再润色（编辑器内容不能为空）",
                },
            },
        )
    built = uniSegBundle.build_universal_segment_user_prompt_bundle(
        db, sb_id, body, {"universalSegmentOverride": draft_raw}, _CFG
    )
    if not built.get("ok"):
        if built.get("code") == "not_found":
            return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": built["message"]}})
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": built["message"]}})
    return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "AI 流式润色未移植"}})


def _universal_segment_generate(storyboard_id: str, body: dict, db: Session) -> dict:
    """generateUniversalSegmentPrompt / Stream 共用的同步校验与全能生成。"""
    sb_id = to_int_id(storyboard_id)
    built = uniSegBundle.build_universal_segment_user_prompt_bundle(db, sb_id, body or {}, {}, _CFG)
    if not built.get("ok"):
        if built.get("code") == "not_found":
            return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": built["message"]}})
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": built["message"]}})

    user_prompt = built["userPrompt"]
    duration_label = built["durationLabel"]
    duration_sec = built["durationSec"]

    try:
        out = aiClient.generate_text(
            db,
            log,
            "text",
            user_prompt,
            promptI18n.get_universal_omni_segment_prompt(),
            {"scene_key": "image_polish", "max_tokens": 2400, "temperature": 0.28},
        )
        if not out or len(str(out).strip()) < 20:
            return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "AI 返回内容过短，请检查文本模型配置"}})
        text = str(out).strip()
        text = normalize_universal_segment_shot_durations(text, duration_label, duration_sec)
        text = normalize_universal_segment_at_image_spacing(text)
        now_iso = timestamp()
        execute(
            db,
            "UPDATE storyboards SET universal_segment_text = :text, updated_at = :now WHERE id = :id AND deleted_at IS NULL",
            {"text": text, "now": now_iso, "id": sb_id},
        )
        log.info("[分镜] generateUniversalSegmentPrompt 完成", {"id": sb_id, "len": len(text), "duration_sec": duration_sec})
        return success({"universal_segment_text": text})
    except Exception as e:
        log.error("storyboards generateUniversalSegmentPrompt", {"error": str(e)})
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e)}})


@router.post("/storyboards/{storyboard_id}/universal-segment-prompt")
def generate_universal_segment_prompt(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    return _universal_segment_generate(storyboard_id, payload, db)


@router.post("/storyboards/{storyboard_id}/universal-segment-prompt-stream")
def generate_universal_segment_stream(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    sb_id = to_int_id(storyboard_id)
    built = uniSegBundle.build_universal_segment_user_prompt_bundle(db, sb_id, payload or {}, {}, _CFG)
    if not built.get("ok"):
        if built.get("code") == "not_found":
            return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": built["message"]}})
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": built["message"]}})
    return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "AI 流式生成未移植"}})


@router.post("/storyboards/{storyboard_id}/classic-video-prompt-polish-stream")
def classic_video_prompt_polish_stream(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js polishClassicVideoPromptStream 的同步校验分支。

    - 分镜不存在 → 404 '分镜不存在'
    - creation_mode === 'universal' → 400 '当前为全能模式，请使用「润色全能提示词」'

    之后为 AI 流式（NDJSON）返回，未移植。
    """
    sb_id = to_int_id(storyboard_id)
    row = fetch_one(
        db,
        "SELECT id, creation_mode FROM storyboards WHERE id = :id AND deleted_at IS NULL",
        {"id": sb_id} if sb_id else {"id": -1},
    )
    if not row:
        return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": "分镜不存在"}})
    if row.get("creation_mode") == "universal":
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "当前为全能模式，请使用「润色全能提示词」",
                },
            },
        )
    return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "AI 流式润色未移植"}})


@router.post("/storyboards/{storyboard_id}/polish-prompt")
def polish_prompt(storyboard_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js polishPrompt 的同步校验分支。

    - 分镜不存在 → 404 '分镜不存在'
    - image_prompt / action / dialogue 均为空 → 400 '该分镜暂无可优化的内容（image_prompt / action / dialogue 均为空）'

    之后的 AI 优化（runChat）未移植：Python 侧直接返回 500 INTERNAL_ERROR，
    对拍只覆盖上述两个确定性分支。
    """
    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": "分镜不存在"}})
    row = fetch_one(
        db,
        "SELECT id, image_prompt, action, dialogue FROM storyboards WHERE id = :id AND deleted_at IS NULL",
        {"id": sb_id},
    )
    if not row:
        return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": "分镜不存在"}})
    if not row.get("image_prompt") and not row.get("action") and not row.get("dialogue"):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "该分镜暂无可优化的内容（image_prompt / action / dialogue 均为空）",
                },
            },
        )
    return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "AI 优化未移植"}})


def _resolve_storyboard_image_local_path(db: Session, storage_base: str, storyboard_id: int, sb_row: dict) -> str | None:
    """等价 resolveStoryboardImageLocalPath：按磁盘存在性解析 storage 相对路径。"""
    def try_rel(rel):
        r = (str(rel).strip().lstrip("/")) if rel and str(rel).strip() else ""
        if not r:
            return None
        return r if os.path.exists(os.path.join(storage_base, r)) else None

    from_sb = try_rel((sb_row or {}).get("local_path"))
    if from_sb:
        return from_sb
    ig = fetch_one(
        db,
        """
        SELECT local_path FROM image_generations
        WHERE storyboard_id = :sid AND status = 'completed' AND deleted_at IS NULL
          AND local_path IS NOT NULL AND TRIM(local_path) != ''
        ORDER BY id DESC LIMIT 1
        """,
        {"sid": storyboard_id},
    )
    return try_rel(ig.get("local_path") if ig else None)


def _storage_base() -> str:
    raw = str((_CFG or {}).get("storage", {}).get("local_path") or "./data/storage")
    return raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)


@router.post("/storyboards/{storyboard_id}/upscale")
def upscale(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js upscale：解析本地图 → 2x 超分。

    Node 依赖 sharp；Python 侧用 Pillow 等价实现（lanczos 2x）。
    无本地图 → 400 '分镜没有本地图片，无法超分'；无 sharp/PIL → 400 'sharp 模块不可用，无法超分'。
    """
    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": "分镜不存在"}})
    row = fetch_one(
        db,
        "SELECT id, local_path, image_url FROM storyboards WHERE id = :id AND deleted_at IS NULL",
        {"id": sb_id},
    )
    if not row:
        return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": "分镜不存在"}})
    try:
        storage_base = _storage_base()
        local_path = _resolve_storyboard_image_local_path(db, storage_base, sb_id, row)
        if not local_path:
            return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "分镜没有本地图片，无法超分"}})
        try:
            from PIL import Image  # noqa: PLC0415
        except Exception:
            return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "sharp 模块不可用，无法超分"}})
        src_file = os.path.join(storage_base, local_path)
        with Image.open(src_file) as img:
            width, height = img.size
        scale = 2
        new_w = (width or 512) * scale
        new_h = (height or 512) * scale
        ext = os.path.splitext(local_path)[1] or ".jpg"
        base_name = os.path.basename(local_path)[: -len(ext)] if ext and local_path.endswith(ext) else os.path.basename(local_path)
        dir_name = os.path.dirname(local_path)
        new_rel = os.path.join(dir_name, base_name + "_2x" + ext).replace("\\", "/")
        new_file = os.path.join(storage_base, new_rel)
        with Image.open(src_file) as img:
            img.resize((new_w, new_h), Image.LANCZOS).save(new_file)
        now = timestamp()
        execute(
            db,
            "UPDATE storyboards SET local_path = :p, updated_at = :t WHERE id = :id",
            {"p": new_rel, "t": now, "id": sb_id},
        )
        log.info("storyboard upscale done", {"id": sb_id, "newRelPath": new_rel})
        return success({"local_path": new_rel, "width": new_w, "height": new_h})
    except Exception as e:  # noqa: BLE001
        log.error("storyboards upscale", {"error": str(e)})
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e)}})


@router.post("/storyboards/{storyboard_id}/regenerate-layout-description")
def regenerate_layout_description(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js regenerateLayoutDescription。

    与 Node 一致：非法 id → 400；合法 id 一律进入服务（含分镜存在性校验与 AI 文本生成），
    AI 文本生成（framePromptService.regenerate_layout_description）尚未移植 → 抛 NotImplementedError → 500。
    注意 Node 在 catch 中统一以 500 返回，不区分 ValueError→404，故 Python 也不返回 404。
    """
    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少分镜 id"}})
    try:
        new_layout = framePromptSvc.regenerate_layout_description(db, sb_id)
        return success({"layout_description": new_layout, "message": "布局描述已由 AI 重新生成并保存"})
    except Exception as e:  # noqa: BLE001
        log.error("storyboards regenerateLayoutDescription", {"error": str(e), "id": sb_id})
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e) or "重新生成布局描述失败"}})


@router.post("/storyboards/{storyboard_id}/rebuild-video-prompt")
def rebuild_video_prompt(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js rebuildVideoPrompt。"""
    from app.services import episodeStoryboardService

    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少分镜 id"}})
    try:
        sb = episodeStoryboardService.rebuild_video_prompt_for_storyboard(db, log, sb_id)
        if not sb:
            return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": "分镜不存在"}})
        res_payload = dict(sb)
        res_payload["message"] = "视频提示词已按最新规则重建并保存"
        return success(res_payload)
    except Exception as err:
        log.error("storyboards rebuildVideoPrompt", {"error": str(err), "id": sb_id})
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(err) or "重建视频提示词失败"}})


@router.post("/storyboards/{storyboard_id}/split-by-audio")
def split_by_audio(storyboard_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js splitByAudio。"""
    from app.services import episodeStoryboardService

    sb_id = to_int_id(storyboard_id)
    if sb_id is None or sb_id <= 0:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": "缺少分镜 id"}})
    try:
        result = episodeStoryboardService.split_storyboard_by_audio(db, log, sb_id)
        res_payload = dict(result)
        res_payload["message"] = f"已拆成 {len(result['storyboard_ids'])} 条分镜（新增 {result['created_count']} 条）"
        return success(res_payload)
    except ValueError as err:
        msg = str(err)
        if msg == "分镜不存在":
            return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": msg}})
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": "BAD_REQUEST", "message": msg}})
    except Exception as err:
        log.error("storyboards splitByAudio", {"error": str(err), "id": sb_id})
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(err) or "拆镜失败"}})
