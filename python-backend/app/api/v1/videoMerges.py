"""/api/v1/video-merges — 契约翻译 backend-node/src/routes/videoMerges.js（同步端点子集）。

- GET    /video-merges              列表（data 为数组，按 episode_id/drama_id 过滤）
- POST   /video-merges              新建合成任务（建记录 + async_tasks，status=pending），data 展开为记录对象
- GET    /video-merges/{merge_id}   详情（404 '记录不存在'），data 为记录对象本身
- DELETE /video-merges/{merge_id}   软删（404 '记录不存在' | { message:'删除成功' }）
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import HttpError, not_found, success
from app.db.session import get_db
from app.services import videoMergeService as svc

router = APIRouter(tags=["video-merges"])
log = get_logger("lmd.video_merges")


@router.get("/video-merges")
def list_merges(
    episode_id: str | None = Query(default=None),
    drama_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        items = svc.list_merges(db, {"episode_id": episode_id, "drama_id": drama_id})
    except Exception as e:
        log.error("video-merges list", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(items)


@router.post("/video-merges")
def create_merge(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.create_merge(db, log, payload or {})
    except Exception as e:
        log.error("video-merges create", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(item)


@router.get("/video-merges/{merge_id}")
def get_merge(merge_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.get_merge(db, merge_id)
    except Exception as e:
        log.error("video-merges get", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not item:
        raise not_found("记录不存在")
    return success(item)


@router.delete("/video-merges/{merge_id}")
def delete_merge(merge_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        ok = svc.delete_merge(db, log, merge_id)
    except Exception as e:
        log.error("video-merges delete", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not ok:
        raise not_found("记录不存在")
    return success({"message": "删除成功"})
