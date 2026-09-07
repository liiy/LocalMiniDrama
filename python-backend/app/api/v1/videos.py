"""/api/v1/videos — 契约翻译 backend-node/src/routes/videos.js（同步端点子集）。

路由顺序与 Node 完全一致：具体路径（/image/:image_gen_id、/episode/:episode_id/batch）
注册在 /{id} 之前。

已移植（不依赖外部视频生成 API）：
- GET    /videos                                      列表（分页 + drama_id/storyboard_id/status 过滤）
- GET    /videos/{id}                                 详情（404 '记录不存在'），data 为记录对象本身
- DELETE /videos/{id}                                 软删（404 '记录不存在' | { message:'删除成功' }）
- POST   /videos/image/{image_gen_id}                基于图生视频建任务（{ task_id }）
- POST   /videos/episode/{episode_id}/batch          批量历史（恒 []）

已接入真实生成链路（workerService 线程池后台执行 videoService.process_video_generation
/ resume_poll_for_video_generation，等价 Node 的 setImmediate）：
- POST   /videos                                       create
- POST   /videos/{id}/resume-poll
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import HttpError, not_found, success, success_with_pagination
from app.db.session import get_db
from app.services import videoService as svc

router = APIRouter(tags=["videos"])
log = get_logger("lmd.videos")


@router.get("/videos")
def list_videos(
    drama_id: str | None = Query(default=None),
    storyboard_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: str | None = Query(default=None),
    page_size: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        items, total, page_no, page_len = svc.list_videos(
            db,
            {
                "drama_id": drama_id,
                "storyboard_id": storyboard_id,
                "status": status,
                "page": page,
                "page_size": page_size,
            },
        )
    except Exception as e:
        log.error("videos list", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success_with_pagination(items, total, page_no, page_len)


@router.post("/videos", status_code=201)
def create_video(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """等价 videos.js create：建 video_generation 任务 + processing 记录，后台跑真实生成。"""
    try:
        item = svc.create_video(db, log, payload or {})
    except Exception as e:
        log.error("videos create", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(item)


@router.post("/videos/image/{image_gen_id}")
def from_image(image_gen_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        result = svc.create_from_image_task(db, log, image_gen_id)
    except Exception as e:
        log.error("videos fromImage", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(result)


@router.post("/videos/episode/{episode_id}/batch")
def episode_batch(episode_id: str, db: Session = Depends(get_db)) -> dict:
    return success([])


@router.get("/videos/{video_id}")
def get_video(video_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.get_video(db, video_id)
    except Exception as e:
        log.error("videos get", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not item:
        raise not_found("记录不存在")
    return success(item)


@router.post("/videos/{video_id}/resume-poll")
def resume_poll(video_id: str, db: Session = Depends(get_db)) -> dict:
    """恢复失败视频并创建持久化轮询任务，返回记录及 queue_job_id。"""
    try:
        result = svc.resume_failed_video_poll(db, log, video_id)
    except Exception as e:
        log.error("videos resumePoll", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not result.get("ok"):
        code = "NOT_FOUND" if result.get("status") == 404 else "BAD_REQUEST"
        status_code = result.get("status", 400)
        raise HttpError(status_code, code, result.get("error"))
    return success(result.get("item"))


@router.delete("/videos/{video_id}")
def delete_video(video_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        ok = svc.delete_video(db, video_id)
    except Exception as e:
        log.error("videos delete", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not ok:
        raise not_found("记录不存在")
    return success({"message": "删除成功"})
