"""持久化任务队列服务。

queue_jobs 是对 async_tasks 的增强层：async_tasks 继续面向前端展示进度；
queue_jobs 负责排队、认领、重试、workflow 关联和后续 Worker/队列框架迁移。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.db.session import fetch_all, fetch_one
from app.platform_common import json_dumps, json_loads, now_iso
from app.services import taskService

log = get_logger("lmd.queue")

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_JOB_STATUSES = {"pending", "retry", "processing", "waiting_child"}


def decode_queue_job(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    data["payload"] = json_loads(data.get("payload"), {})
    data["result"] = json_loads(data.get("result"), {})
    return data


def enqueue_job(db: Session, payload: dict[str, Any], *, create_async_task: bool = True) -> dict[str, Any]:
    """创建队列任务。

    默认同步创建 async_task，保证老前端仍可通过 /tasks/{id} 轮询任务进度。
    真正执行由独立 worker claim 后完成，避免请求线程直接执行耗时 AI 任务。
    """
    task_type = str(payload.get("task_type") or payload.get("type") or "").strip()
    if not task_type:
        raise ValueError("task_type 必填")
    queue_name = str(payload.get("queue_name") or "default").strip() or "default"
    job_id = str(payload.get("id") or uuid.uuid4())
    async_task_id = payload.get("async_task_id")
    if create_async_task and not async_task_id:
        async_task = taskService.create_task(db, log, task_type, payload.get("resource_id") or job_id)
        async_task_id = async_task.get("id")

    now = now_iso()
    db.execute(
        text(
            """
            INSERT INTO queue_jobs (
                id, async_task_id, queue_name, task_type, status, priority, payload,
                attempts, max_attempts, run_after, workflow_run_id, workflow_step_id,
                created_at, updated_at
            ) VALUES (
                :id, :async_task_id, :queue_name, :task_type, :status, :priority, :payload,
                :attempts, :max_attempts, :run_after, :workflow_run_id, :workflow_step_id,
                :now, :now
            )
            """
        ),
        {
            "id": job_id,
            "async_task_id": async_task_id,
            "queue_name": queue_name,
            "task_type": task_type,
            "status": payload.get("status") or "pending",
            "priority": int(payload.get("priority") or 0),
            "payload": json_dumps(payload.get("payload") or {}),
            "attempts": int(payload.get("attempts") or 0),
            "max_attempts": int(payload.get("max_attempts") or 3),
            "run_after": payload.get("run_after"),
            "workflow_run_id": payload.get("workflow_run_id"),
            "workflow_step_id": payload.get("workflow_step_id"),
            "now": now,
        },
    )
    return get_queue_job(db, job_id) or {"id": job_id}


def get_queue_job(db: Session, job_id: str) -> dict[str, Any] | None:
    row = fetch_one(db, "SELECT * FROM queue_jobs WHERE id = :id AND deleted_at IS NULL", {"id": job_id})
    return decode_queue_job(row)


def list_queue_jobs(
    db: Session,
    *,
    queue_name: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    workflow_run_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 50), 100))}
    if queue_name:
        where.append("queue_name = :queue_name")
        params["queue_name"] = queue_name
    if status:
        where.append("status = :status")
        params["status"] = status
    if task_type:
        where.append("task_type = :task_type")
        params["task_type"] = task_type
    if workflow_run_id:
        where.append("workflow_run_id = :workflow_run_id")
        params["workflow_run_id"] = workflow_run_id
    rows = fetch_all(
        db,
        "SELECT * FROM queue_jobs WHERE "
        + " AND ".join(where)
        + " ORDER BY priority DESC, created_at ASC LIMIT :limit",
        params,
    )
    return [decode_queue_job(row) or {} for row in rows]


def claim_next_job(db: Session, *, worker_id: str, queue_name: str | None = None) -> dict[str, Any] | None:
    """认领下一个可执行任务。

    当前使用数据库行状态做轻量锁；未来替换 Redis/Celery 时保留这个服务接口即可。
    """
    where = ["deleted_at IS NULL", "status IN ('pending', 'retry')", "(run_after IS NULL OR run_after <= :now)"]
    params: dict[str, Any] = {"now": now_iso()}
    if queue_name:
        where.append("queue_name = :queue_name")
        params["queue_name"] = queue_name
    row = fetch_one(
        db,
        "SELECT * FROM queue_jobs WHERE "
        + " AND ".join(where)
        + " ORDER BY priority DESC, created_at ASC LIMIT 1",
        params,
    )
    if not row:
        return None
    attempts = int(row.get("attempts") or 0) + 1
    now = now_iso()
    claimed = db.execute(
        text(
            """
            UPDATE queue_jobs
            SET status = 'processing', attempts = :attempts, locked_by = :worker_id,
                locked_at = :now, updated_at = :now
            WHERE id = :id AND status IN ('pending', 'retry')
            """
        ),
        {"id": row["id"], "attempts": attempts, "worker_id": worker_id, "now": now},
    )
    if not claimed.rowcount:
        # 其他 worker 已抢先认领，同一任务不能重复执行。
        return None
    if row.get("async_task_id"):
        taskService.update_task_status(db, row["async_task_id"], "processing", 1, "任务已被 worker 认领")
    return get_queue_job(db, row["id"])


def complete_job(db: Session, job_id: str, result: Any | None = None) -> dict[str, Any] | None:
    now = now_iso()
    updated = db.execute(
        text(
            """
            UPDATE queue_jobs
            SET status = 'completed', result = :result, error = NULL,
                completed_at = :now, locked_by = NULL, locked_at = NULL, updated_at = :now
            WHERE id = :id
              AND status IN ('pending', 'retry', 'processing', 'waiting_child')
              AND deleted_at IS NULL
            """
        ),
        {"id": job_id, "result": json_dumps(result or {}), "now": now},
    )
    job = get_queue_job(db, job_id)
    # 已取消或已进入其他终态的任务不能被迟到的 Worker 结果覆盖。
    if updated.rowcount and job and job.get("async_task_id"):
        taskService.update_task_result(db, job["async_task_id"], result or {})
    return job


def mark_job_waiting_child(
    db: Session,
    job_id: str,
    *,
    child_async_task_id: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """标记队列任务正在等待旧 async_task 子任务完成。"""
    job = get_queue_job(db, job_id)
    if not job:
        return None
    payload = {**(result or {}), "child_async_task_id": child_async_task_id}
    now = now_iso()
    updated = db.execute(
        text(
            """
            UPDATE queue_jobs
            SET status = 'waiting_child', result = :result, error = NULL,
                locked_by = NULL, locked_at = NULL, updated_at = :now
            WHERE id = :id AND status = 'processing' AND deleted_at IS NULL
            """
        ),
        {"id": job_id, "result": json_dumps(payload), "now": now},
    )
    if updated.rowcount and job.get("async_task_id"):
        taskService.update_task_status(db, job["async_task_id"], "processing", 50, "等待子任务完成")
    return get_queue_job(db, job_id)


def sync_waiting_child_job(db: Session, job_id: str) -> dict[str, Any] | None:
    """同步 waiting_child 队列任务。

    子 async_task 完成后，外层 queue_job 才算完成；这样 workflow step 不会过早进入 completed。
    """
    job = get_queue_job(db, job_id)
    if not job:
        return None
    if job.get("status") != "waiting_child":
        return job
    child_task_id = (job.get("result") or {}).get("child_async_task_id")
    if not child_task_id:
        return fail_job(db, job_id, "waiting_child 缺少 child_async_task_id", retryable=False)
    child_task = taskService.get_task(db, child_task_id)
    if not child_task:
        return fail_job(db, job_id, "子 async_task 不存在", retryable=False)
    if child_task.get("status") == "completed":
        child_result = json_loads(child_task.get("result"), {})
        return complete_job(
            db,
            job_id,
            {**(job.get("result") or {}), "child_async_task": child_task, "child_result": child_result},
        )
    if child_task.get("status") in {"failed", "cancelled"}:
        error = child_task.get("error") or child_task.get("message") or "子 async_task 失败"
        return fail_job(db, job_id, error, retryable=False)
    return job


def fail_job(db: Session, job_id: str, error: str, *, retryable: bool = True) -> dict[str, Any] | None:
    """标记任务失败；可重试任务会回到 retry 状态。"""
    job = get_queue_job(db, job_id)
    if not job:
        return None
    if job.get("status") in TERMINAL_JOB_STATUSES:
        # 终态不可被迟到的异常处理覆盖，尤其要保留用户主动取消状态。
        return job
    attempts = int(job.get("attempts") or 0)
    max_attempts = int(job.get("max_attempts") or 1)
    next_status = "retry" if retryable and attempts < max_attempts else "failed"
    now = now_iso()
    updated = db.execute(
        text(
            """
            UPDATE queue_jobs
            SET status = :status, error = :error, locked_by = NULL, locked_at = NULL,
                completed_at = :completed_at, updated_at = :now
            WHERE id = :id
              AND status IN ('pending', 'retry', 'processing', 'waiting_child')
              AND deleted_at IS NULL
            """
        ),
        {
            "id": job_id,
            "status": next_status,
            "error": error or "",
            "completed_at": now if next_status == "failed" else None,
            "now": now,
        },
    )
    if updated.rowcount and job.get("async_task_id"):
        if next_status == "failed":
            taskService.update_task_error(db, job["async_task_id"], error)
        else:
            taskService.update_task_status(db, job["async_task_id"], "pending", 0, "任务等待重试")
    return get_queue_job(db, job_id)


def cancel_job(db: Session, job_id: str, *, reason: str | None = None) -> dict[str, Any] | None:
    """协作式取消队列任务，并阻止 Worker 完成后继续推进工作流。

    已经发出的外部 AI 请求无法被通用方式强制中断，但队列状态会立即进入 cancelled；
    Worker 返回时通过条件更新识别该终态，不再覆盖结果或触发下游步骤。
    """
    job = get_queue_job(db, job_id)
    if not job:
        return None
    if job.get("status") in TERMINAL_JOB_STATUSES:
        return job

    message = str(reason or "用户已取消队列任务").strip() or "用户已取消队列任务"
    now = now_iso()
    updated = db.execute(
        text(
            """
            UPDATE queue_jobs
            SET status = 'cancelled', error = :error, locked_by = NULL, locked_at = NULL,
                completed_at = :now, updated_at = :now
            WHERE id = :id
              AND status IN ('pending', 'retry', 'processing', 'waiting_child')
              AND deleted_at IS NULL
            """
        ),
        {"id": job_id, "error": message, "now": now},
    )
    if updated.rowcount and job.get("async_task_id"):
        # 旧前端仍通过 async_tasks 轮询；沿用其“取消映射为 failed”的兼容语义。
        taskService.update_task_error(db, job["async_task_id"], message)
    return get_queue_job(db, job_id)


def retry_job(db: Session, job_id: str, *, run_after: str | None = None) -> dict[str, Any] | None:
    """人工重试失败任务，保留 attempts 作为审计信息。"""
    now = now_iso()
    db.execute(
        text(
            """
            UPDATE queue_jobs
            SET status = 'retry', error = NULL, locked_by = NULL, locked_at = NULL,
                run_after = :run_after, completed_at = NULL, updated_at = :now
            WHERE id = :id AND deleted_at IS NULL
            """
        ),
        {"id": job_id, "run_after": run_after, "now": now},
    )
    job = get_queue_job(db, job_id)
    if job and job.get("async_task_id"):
        taskService.update_task_status(db, job["async_task_id"], "pending", 0, "任务已重新入队")
    return job


def decode_worker_node(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    data["queues"] = json_loads(data.get("queues"), [])
    data["metadata"] = json_loads(data.get("metadata"), {})
    return data


def register_worker(
    db: Session,
    *,
    worker_id: str,
    queues: list[str] | None = None,
    hostname: str | None = None,
    process_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """注册 worker；同一 worker_id 重启时复用原记录并恢复 online。"""
    worker_id = str(worker_id or "").strip()
    if not worker_id:
        raise ValueError("worker_id 必填")
    now = now_iso()
    db.execute(
        text(
            """
            INSERT INTO worker_nodes (
                id, worker_id, status, queues, hostname, process_id, heartbeat_at,
                started_at, metadata, created_at, updated_at
            ) VALUES (
                :id, :worker_id, 'online', :queues, :hostname, :process_id, :now,
                :now, :metadata, :now, :now
            )
            ON DUPLICATE KEY UPDATE
                status = 'online',
                queues = VALUES(queues),
                hostname = VALUES(hostname),
                process_id = VALUES(process_id),
                heartbeat_at = VALUES(heartbeat_at),
                started_at = VALUES(started_at),
                stopped_at = NULL,
                metadata = VALUES(metadata),
                updated_at = VALUES(updated_at),
                deleted_at = NULL
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "worker_id": worker_id,
            "queues": json_dumps(queues or []),
            "hostname": hostname,
            "process_id": process_id,
            "metadata": json_dumps(metadata or {}),
            "now": now,
        },
    )
    row = fetch_one(db, "SELECT * FROM worker_nodes WHERE worker_id = :worker_id", {"worker_id": worker_id})
    return decode_worker_node(row) or {"worker_id": worker_id}


def heartbeat_worker(db: Session, worker_id: str) -> dict[str, Any] | None:
    """更新 worker 心跳；心跳线程使用独立 Session，不与耗时任务共享事务。"""
    now = now_iso()
    db.execute(
        text(
            """
            UPDATE worker_nodes
            SET status = 'online', heartbeat_at = :now, updated_at = :now
            WHERE worker_id = :worker_id AND deleted_at IS NULL
            """
        ),
        {"worker_id": worker_id, "now": now},
    )
    row = fetch_one(
        db,
        "SELECT * FROM worker_nodes WHERE worker_id = :worker_id AND deleted_at IS NULL",
        {"worker_id": worker_id},
    )
    return decode_worker_node(row)


def stop_worker(db: Session, worker_id: str) -> dict[str, Any] | None:
    """优雅关闭时把 worker 标记为 offline，保留最后心跳和停止时间。"""
    now = now_iso()
    db.execute(
        text(
            """
            UPDATE worker_nodes
            SET status = 'offline', stopped_at = :now, updated_at = :now
            WHERE worker_id = :worker_id AND deleted_at IS NULL
            """
        ),
        {"worker_id": worker_id, "now": now},
    )
    row = fetch_one(
        db,
        "SELECT * FROM worker_nodes WHERE worker_id = :worker_id AND deleted_at IS NULL",
        {"worker_id": worker_id},
    )
    return decode_worker_node(row)


def list_worker_nodes(db: Session, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 100), 200))}
    if status:
        where.append("status = :status")
        params["status"] = status
    rows = fetch_all(
        db,
        "SELECT * FROM worker_nodes WHERE "
        + " AND ".join(where)
        + " ORDER BY heartbeat_at DESC, worker_id ASC LIMIT :limit",
        params,
    )
    return [decode_worker_node(row) or {} for row in rows]


def stale_cutoff_iso(timeout_seconds: int, now: datetime | None = None) -> str:
    """生成 UTC 超时边界，ISO 字符串可直接与当前 TEXT 时间字段比较。"""
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(seconds=max(1, int(timeout_seconds or 1)))
    return f"{cutoff.strftime('%Y-%m-%dT%H:%M:%S')}.{cutoff.microsecond // 1000:03d}Z"


def recover_stale_processing_jobs(db: Session, *, timeout_seconds: int = 1800, limit: int = 100) -> dict[str, Any]:
    """回收长时间没有完成的 processing job。

    可重试任务回到 retry；超过 max_attempts 的任务进入 failed。
    """
    cutoff = stale_cutoff_iso(timeout_seconds)
    rows = fetch_all(
        db,
        """
        SELECT * FROM queue_jobs
        WHERE status = 'processing'
          AND (locked_at IS NULL OR locked_at < :cutoff)
          AND deleted_at IS NULL
        ORDER BY locked_at ASC, created_at ASC
        LIMIT :limit
        """,
        {"cutoff": cutoff, "limit": max(1, min(int(limit or 100), 500))},
    )
    recovered: list[dict[str, Any]] = []
    for row in rows:
        updated = fail_job(db, row["id"], "worker 执行超时，任务已回收", retryable=True)
        if updated:
            recovered.append(updated)
    return {"cutoff": cutoff, "count": len(recovered), "jobs": recovered}


def mark_stale_workers_offline(db: Session, *, timeout_seconds: int = 90) -> int:
    """把超过心跳阈值的 online worker 标记为 stale。"""
    cutoff = stale_cutoff_iso(timeout_seconds)
    result = db.execute(
        text(
            """
            UPDATE worker_nodes
            SET status = 'stale', updated_at = :now
            WHERE status = 'online'
              AND (heartbeat_at IS NULL OR heartbeat_at < :cutoff)
              AND deleted_at IS NULL
            """
        ),
        {"cutoff": cutoff, "now": now_iso()},
    )
    return int(result.rowcount or 0)


def queue_summary(jobs: list[dict[str, Any]]) -> dict[str, int]:
    """按状态汇总队列，供前端仪表盘展示。"""
    summary = {
        "total": len(jobs),
        "pending": 0,
        "retry": 0,
        "processing": 0,
        "waiting_child": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    for job in jobs:
        status = str(job.get("status") or "")
        if status in summary:
            summary[status] += 1
    return summary
