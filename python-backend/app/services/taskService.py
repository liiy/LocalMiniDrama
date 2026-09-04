"""异步任务服务 — 契约翻译 backend-node/src/services/taskService.js。

async_tasks 表：id 为 UUID 字符串主键，软删除（deleted_at）。

要点：
- create_task 插入 status='pending'、progress=0、message=''
- update_task_status 在 completed/failed 时写入 completed_at
- update_task_error 依赖 error 列；若表结构缺失该列则回退为仅更新 status
- cancel_task 对已完成/失败的任务返回 already_done，不重复写库
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one

ORPHAN_ASYNC_TASK_MSG = "服务重启后任务中断，请重新操作"
USER_CANCEL_TASK_MSG = "用户已取消"


def _now() -> str:
    """等价 new Date().toISOString()。"""
    return timestamp()


def row_to_task(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "type": r.get("type"),
        "status": r.get("status"),
        "progress": r.get("progress") if r.get("progress") is not None else 0,
        "message": r.get("message"),
        "error": r.get("error"),
        "result": r.get("result"),
        "resource_id": r.get("resource_id"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "completed_at": r.get("completed_at"),
    }


def create_task(db: Session, log, task_type: Any, resource_id: Any) -> dict:
    task_id = str(uuid.uuid4())
    now = _now()
    rid = resource_id if resource_id is not None else ""
    execute(
        db,
        "INSERT INTO async_tasks (id, type, status, progress, message, resource_id, created_at, updated_at) "
        "VALUES (:id, :type, 'pending', 0, '', :resource_id, :created_at, :updated_at)",
        {"id": task_id, "type": task_type, "resource_id": rid, "created_at": now, "updated_at": now},
    )
    log.info("Task created", extra={"task_id": task_id, "type": task_type, "resource_id": resource_id})
    task = get_task(db, task_id)
    if task:
        return task
    return {
        "id": task_id,
        "type": task_type,
        "status": "pending",
        "progress": 0,
        "message": "",
        "resource_id": rid,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }


def get_task(db: Session, task_id: Any) -> dict | None:
    row = fetch_one(
        db,
        "SELECT * FROM async_tasks WHERE id = :id AND deleted_at IS NULL",
        {"id": task_id},
    )
    return row_to_task(row) if row else None


def get_tasks_by_resource(db: Session, resource_id: Any) -> list[dict]:
    rows = fetch_all(
        db,
        "SELECT * FROM async_tasks WHERE resource_id = :resource_id AND deleted_at IS NULL "
        "ORDER BY created_at DESC",
        {"resource_id": resource_id},
    )
    return [row_to_task(r) for r in rows]


def update_task_status(db: Session, task_id: Any, status: Any, progress: Any = None, message: Any = None) -> None:
    now = _now()
    completed_at = now if status in ("completed", "failed") else None
    execute(
        db,
        "UPDATE async_tasks SET status = :status, progress = :progress, message = :message, "
        "updated_at = :updated_at, completed_at = :completed_at WHERE id = :id",
        {
            "status": status,
            "progress": progress if progress is not None else 0,
            "message": message or "",
            "updated_at": now,
            "completed_at": completed_at,
            "id": task_id,
        },
    )


def update_task_error(db: Session, task_id: Any, err_msg: Any = None) -> None:
    now = _now()
    try:
        execute(
            db,
            "UPDATE async_tasks SET status = 'failed', error = :error, progress = 0, "
            "completed_at = :completed_at, updated_at = :updated_at WHERE id = :id",
            {"error": err_msg or "", "completed_at": now, "updated_at": now, "id": task_id},
        )
    except Exception as e:
        # 老库缺 error 列时回退为仅更新 status（与 Node 的 message.includes('error') 判定一致）
        if "error" in str(e):
            update_task_status(db, task_id, "failed", 0, err_msg or "任务失败")
        else:
            raise


def update_task_result(db: Session, task_id: Any, result: Any) -> None:
    now = _now()
    result_str = result if isinstance(result, str) else json.dumps(result or {}, ensure_ascii=False)
    execute(
        db,
        "UPDATE async_tasks SET status = 'completed', progress = 100, result = :result, "
        "completed_at = :completed_at, updated_at = :updated_at WHERE id = :id",
        {"result": result_str, "completed_at": now, "updated_at": now, "id": task_id},
    )


def cancel_task(db: Session, log, task_id: Any, reason: Any = None) -> dict:
    """用户主动取消进行中的异步任务。

    无法中断已在执行的 AI 调用，但会停止前端轮询并防止恢复。
    返回 { ok, task } / { ok, already_done, task } / { ok: False, reason: 'not_found' }。
    """
    task = get_task(db, task_id)
    if not task:
        return {"ok": False, "reason": "not_found"}
    if task["status"] in ("completed", "failed"):
        return {"ok": True, "already_done": True, "task": task}

    msg = str(reason or USER_CANCEL_TASK_MSG).strip() or USER_CANCEL_TASK_MSG
    update_task_error(db, task_id, msg)
    log.info("Task cancelled by user", extra={"task_id": task_id, "type": task["type"]})
    return {"ok": True, "task": get_task(db, task_id)}


def fail_orphaned_async_tasks_on_startup(db: Session, log) -> int:
    """进程内任务在重启后会丢失；启动时将遗留的 pending/processing 标为失败，避免前端无限轮询。"""
    rows = fetch_all(
        db,
        "SELECT id, type, status, resource_id FROM async_tasks "
        "WHERE status IN ('pending', 'processing') AND deleted_at IS NULL",
    )
    if not rows:
        return 0
    log.warning("Failing orphaned async tasks after startup", extra={"count": len(rows)})
    for row in rows:
        update_task_error(db, row["id"], ORPHAN_ASYNC_TASK_MSG)
        log.info(
            "Orphaned async task marked failed",
            extra={
                "task_id": row["id"],
                "type": row["type"],
                "resource_id": row["resource_id"],
                "previous_status": row["status"],
            },
        )
    return len(rows)
