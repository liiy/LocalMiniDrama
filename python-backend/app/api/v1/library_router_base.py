"""三个素材库路由的公共工厂（character/scene/prop library）。

Node 端三个路由文件（routes/{character,scene,prop}Library.js）结构完全一致，
仅 service 与「X库项不存在」文案不同，故用工厂生成，保证契约一字不差。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.response import created, not_found, success, success_with_pagination
from app.db.session import get_db


def make_library_router(path: str, tag: str, service, missing_message: str) -> APIRouter:
    router = APIRouter(tags=[tag])

    def _query(page, page_size, drama_id, global_, category, source_type, source_id, source_ids, keyword) -> dict:
        return {
            "page": page,
            "page_size": page_size,
            "drama_id": drama_id,
            "global": global_,
            "category": category,
            "source_type": source_type,
            "source_id": source_id,
            "source_ids": source_ids,
            "keyword": keyword,
        }

    @router.get(path)
    def list_items(
        page: str | None = None,
        page_size: str | None = None,
        drama_id: str | None = None,
        global_: str | None = Query(default=None, alias="global"),
        category: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        source_ids: list[str] | None = Query(default=None),
        keyword: str | None = None,
        db: Session = Depends(get_db),
    ) -> dict:
        query = _query(page, page_size, drama_id, global_, category, source_type, source_id, source_ids, keyword)
        items, total, page_no, page_len = service.list_library_items(db, query)
        return success_with_pagination(items, total, page_no, page_len)

    @router.post(path, status_code=201)
    def create_item(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
        item = service.create_library_item(db, payload)
        return created(item)

    @router.get(f"{path}/{{item_id}}")
    def get_item(item_id: str, db: Session = Depends(get_db)) -> dict:
        item = service.get_library_item(db, item_id)
        if not item:
            raise not_found(missing_message)
        return success(item)

    @router.put(f"{path}/{{item_id}}")
    def update_item(item_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
        item = service.update_library_item(db, item_id, payload)
        if not item:
            raise not_found(missing_message)
        return success(item)

    @router.delete(f"{path}/{{item_id}}")
    def delete_item(item_id: str, db: Session = Depends(get_db)) -> dict:
        ok = service.delete_library_item(db, item_id)
        if not ok:
            raise not_found(missing_message)
        return success({"message": "删除成功"})

    return router
