"""/api/v1/images — 契约翻译 backend-node/src/routes/images.js（同步端点子集）。

backend-node 的 /images 实际读写 image_generations 表。路由顺序与 Node 完全一致：
具体路径（/upload、/scene/:scene_id、/episode/:episode_id/backgrounds、
/episode/:episode_id/batch）必须注册在 /{id} 之前。

已移植（不依赖外部图像生成 API）：
- GET    /images                                      列表（分页 + drama_id/storyboard_id/frame_type/status 过滤）
- GET    /images/{id}                                 详情（404 '记录不存在'），data 为记录对象本身
- DELETE /images/{id}                                 软删（404 '记录不存在' | { message:'删除成功' }）
- POST   /images/upload                               新建记录（201，不入队真实生成），data 为记录对象
- GET    /images/episode/{episode_id}/backgrounds     该集分镜背景图（data 为 scenes 行数组）
- POST   /images/scene/{scene_id}                     建 image_generation 任务（{ task_id }）
- POST   /images/episode/{episode_id}/batch           批量历史（恒 []）

已接入真实生成链路（workerService 线程池后台执行 imageService.process_image_generation）：
- POST   /images                                       create（异步生成）

未移植（需 backgroundExtractionService 走真实 AI 提取）：
- POST   /images/episode/{episode_id}/backgrounds/extract
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import HttpError, not_found, success, success_with_pagination
from app.db.session import get_db
from app.services import imageService as svc
from app.services import backgroundExtractionService as bgSvc

router = APIRouter(tags=["images"])
log = get_logger("lmd.images")

# 内存态配置（与 upload.py 一致，等价 Node app.js 启动时 loadConfig 一次并闭包传递）
_CFG: dict = {}


def init_config(cfg: dict) -> None:
    global _CFG
    _CFG = cfg


@router.get("/images")
def list_images(
    drama_id: str | None = Query(default=None),
    storyboard_id: str | None = Query(default=None),
    frame_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: str | None = Query(default=None),
    page_size: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        items, total, page_no, page_len = svc.list_images(
            db,
            {
                "drama_id": drama_id,
                "storyboard_id": storyboard_id,
                "frame_type": frame_type,
                "status": status,
                "page": page,
                "page_size": page_size,
            },
        )
    except Exception as e:
        log.error("images list", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success_with_pagination(items, total, page_no, page_len)


@router.post("/images", status_code=201)
def create_image(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """等价 images.js create：建 image_generation 任务 + pending 记录，后台跑真实生成。"""
    try:
        rec = svc.create_generation(db, log, payload or {})
    except Exception as e:
        log.error("images create", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(rec)


@router.post("/images/upload", status_code=201)
def upload_image(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.create_record(db, payload or {})
    except Exception as e:
        log.error("images upload", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(item)


@router.get("/images/episode/{episode_id}/backgrounds")
def get_episode_backgrounds(episode_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        backgrounds = svc.get_backgrounds_for_episode(db, episode_id)
    except Exception as e:
        log.error("images episode backgrounds", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(backgrounds)


@router.post("/images/scene/{scene_id}")
def create_scene_image_task(scene_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        result = svc.create_scene_task(db, log, scene_id)
    except Exception as e:
        log.error("images scene task", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(result)


@router.post("/images/episode/{episode_id}/batch")
def episode_batch(episode_id: str, db: Session = Depends(get_db)) -> dict:
    return success([])


@router.post("/images/episode/{episode_id}/backgrounds/extract")
def extract_backgrounds(episode_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """创建可恢复的 background_extraction 队列任务。"""
    body = payload or {}
    try:
        task_id = bgSvc.extract_backgrounds_for_episode(
            db, _CFG, log, episode_id,
            body.get("model"), body.get("style"), body.get("language"),
        )
    except ValueError as e:
        msg = str(e)
        raise HttpError(400, "BAD_REQUEST", msg)
    except Exception as e:
        log.error("images episode backgrounds extract", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e) or "任务创建失败") from e
    return success({"task_id": task_id, "status": "pending", "message": "场景提取任务已创建，正在后台处理..."})


@router.get("/images/{image_id}")
def get_image(image_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.get_image(db, image_id)
    except Exception as e:
        log.error("images get", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not item:
        raise not_found("记录不存在")
    return success(item)


@router.delete("/images/{image_id}")
def delete_image(image_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        ok = svc.delete_image(db, image_id)
    except Exception as e:
        log.error("images delete", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not ok:
        raise not_found("记录不存在")
    return success({"message": "删除成功"})
