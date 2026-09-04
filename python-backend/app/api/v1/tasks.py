"""/api/v1/tasks/* — 契约精确翻译 backend-node/src/routes/task.js。

端点：
- GET  /tasks/{task_id}          任务详情（404 '任务不存在'）
- POST /tasks/{task_id}/cancel   取消任务（404 | 已完成/失败时返回原任务，不报错）
- GET  /tasks?resource_id=       按资源列任务（400 '缺少resource_id参数'）
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import HttpError, bad_request, not_found, success
from app.db.session import get_db
from app.services import taskService as svc

router = APIRouter(tags=["tasks"])
log = get_logger("lmd.tasks")


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str, db: Session = Depends(get_db)) -> dict:
    task = svc.get_task(db, task_id)
    if not task:
        raise not_found("任务不存在")
    return success(task)


@router.post("/tasks/{task_id}/cancel")
def cancel_task_status(task_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        result = svc.cancel_task(db, log, task_id, (payload or {}).get("reason"))
    except Exception as e:
        log.error("Cancel task failed", extra={"error": str(e), "task_id": task_id})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    if not result.get("ok") and result.get("reason") == "not_found":
        raise not_found("任务不存在")
    return success(result.get("task") or {"id": task_id})


@router.get("/tasks")
def get_resource_tasks(resource_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    if not resource_id:
        raise bad_request("缺少resource_id参数")
    try:
        tasks = svc.get_tasks_by_resource(db, resource_id)
    except Exception as e:
        log.error("Get resource tasks failed", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e)) from e
    return success(tasks)
