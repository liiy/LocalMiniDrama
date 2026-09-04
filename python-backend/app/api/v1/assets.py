"""/api/v1/assets/* — 契约精确翻译 backend-node/src/routes/assets.js。

端点（import 路径须注册在 /{id} 之前）：
- GET    /assets                              列表（分页 + drama_id/type 过滤）
- POST   /assets                              新建（201）
- POST   /assets/import/image/{image_gen_id}  从图片生成记录导入（404 '图片生成记录不存在' | 201）
- POST   /assets/import/video/{video_gen_id}  从视频生成记录导入（404 '视频生成记录不存在' | 201）
- GET    /assets/{id}                         详情（404 '资源不存在'）
- PUT    /assets/{id}                         更新（404 | 200）
- DELETE /assets/{id}                         软删（404 | { message: '删除成功' }）
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import HttpError, created, not_found, success, success_with_pagination
from app.db.session import get_db
from app.services import assetService as svc

router = APIRouter(tags=["assets"])
log = get_logger("lmd.assets")


@router.get("/assets")
def list_assets(
    drama_id: str | None = Query(default=None),
    type: str | None = Query(default=None),
    page: str | None = Query(default=None),
    page_size: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        items, total, page_no, page_len = svc.list_assets(
            db, {"drama_id": drama_id, "type": type, "page": page, "page_size": page_size}
        )
    except Exception as e:
        log.error("assets list", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success_with_pagination(items, total, page_no, page_len)


@router.post("/assets", status_code=201)
def create_asset(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.create(db, log, payload or {})
    except Exception as e:
        log.error("assets create", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return created(item)


@router.post("/assets/import/image/{image_gen_id}", status_code=201)
def import_image(image_gen_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.import_from_image(db, log, image_gen_id)
    except Exception as e:
        log.error("assets import image", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not item:
        raise not_found("图片生成记录不存在")
    return created(item)


@router.post("/assets/import/video/{video_gen_id}", status_code=201)
def import_video(video_gen_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.import_from_video(db, log, video_gen_id)
    except Exception as e:
        log.error("assets import video", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not item:
        raise not_found("视频生成记录不存在")
    return created(item)


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.get_by_id(db, asset_id)
    except Exception as e:
        log.error("assets get", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not item:
        raise not_found("资源不存在")
    return success(item)


@router.put("/assets/{asset_id}")
def update_asset(asset_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = svc.update(db, log, asset_id, payload or {})
    except Exception as e:
        log.error("assets update", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not item:
        raise not_found("资源不存在")
    return success(item)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        ok = svc.delete_by_id(db, log, asset_id)
    except Exception as e:
        log.error("assets delete", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not ok:
        raise not_found("资源不存在")
    return success({"message": "删除成功"})
