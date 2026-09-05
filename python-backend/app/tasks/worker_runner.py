"""持久化队列 Worker Runner。

Runner 只识别已注册的 task_type，不允许从数据库 payload 动态导入任意函数，
避免队列数据被篡改后执行非预期代码。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.tasks import queue_service


SUPPORTED_TASK_PREFIXES = (
    "workflow.",
    "image.generate",
    "generate.image",
    "video.generate",
    "generate.video",
    "audio.generate",
    "generate.audio",
    "story.generate",
    "dramatiq.",
)
SUPPORTED_TASK_PREFIX = SUPPORTED_TASK_PREFIXES


def run_next_job(
    db: Session,
    *,
    worker_id: str,
    queue_name: str | None = None,
    auto_advance: bool = False,
) -> dict[str, Any]:
    """认领并执行一个队列任务；没有任务时返回 idle。"""
    job = queue_service.claim_next_job(db, worker_id=worker_id, queue_name=queue_name)
    if not job:
        return {"status": "idle", "worker_id": worker_id}
    # 认领状态必须先提交，及时释放行锁；耗时 AI 调用不能一直占着认领事务。
    db.commit()
    return execute_claimed_job(db, job, auto_advance=auto_advance)


def execute_claimed_job(
    db: Session,
    job: dict[str, Any],
    *,
    auto_advance: bool = False,
) -> dict[str, Any]:
    """执行已认领任务，并把结果写回 queue_jobs。"""
    job_id = str(job.get("id") or "")
    task_type = str(job.get("task_type") or "")
    try:
        current_job = queue_service.get_queue_job(db, job_id)
        if current_job and current_job.get("status") == "cancelled":
            sync_result = _sync_workflow_job(db, current_job, auto_advance=False)
            return {"status": "cancelled", "job": current_job, "workflow_sync": sync_result}
        
        if not any(task_type.startswith(prefix) for prefix in SUPPORTED_TASK_PREFIXES):
            raise ValueError(f"不支持的队列任务类型: {task_type}")

        if task_type.startswith("workflow."):
            result = _execute_workflow_job(db, job)
        else:
            result = _execute_media_job(db, job)

        # 外部 AI 调用期间可能收到取消请求；返回后必须重新读取队列状态。
        current_job = queue_service.get_queue_job(db, job_id)
        if current_job and current_job.get("status") == "cancelled":
            sync_result = _sync_workflow_job(db, current_job, auto_advance=False)
            return {
                "status": "cancelled",
                "job": current_job,
                "executor_result": result,
                "workflow_sync": sync_result,
            }
        _rebind_workflow_step(db, job, result)
        async_task_id = _extract_child_async_task_id(result)
        if async_task_id:
            # 现有生成服务内部仍使用 async_tasks，外层队列必须等待它结束。
            # 先提交子任务和 workflow processing 状态，避免后台线程启动后读不到未提交记录。
            db.commit()
            updated_job = queue_service.mark_job_waiting_child(
                db,
                job_id,
                child_async_task_id=async_task_id,
                result={"executor_result": result},
            )
            status = str((updated_job or {}).get("status") or "waiting_child")
            sync_result = None
            if status == "cancelled":
                sync_result = _sync_workflow_job(db, updated_job, auto_advance=False)
            return {
                "status": status,
                "job": updated_job,
                "executor_result": result,
                "workflow_sync": sync_result,
            }

        completed = queue_service.complete_job(db, job_id, result)
        completed_status = str((completed or {}).get("status") or "failed")
        sync_result = _sync_workflow_job(
            db,
            completed,
            auto_advance=auto_advance if completed_status == "completed" else False,
        )
        return {
            "status": completed_status,
            "job": completed,
            "executor_result": result,
            "workflow_sync": sync_result,
        }
    except Exception as err:  # noqa: BLE001
        # SQL 或业务执行失败时先撤销未完成写入，再单独记录 queue job 的失败/重试状态。
        db.rollback()
        failed = queue_service.fail_job(db, job_id, str(err), retryable=True)
        # 只有最终 failed 才同步 workflow；retry 状态仍保留步骤 processing，等待下一次认领。
        sync_result = None
        if failed and failed.get("status") == "failed":
            sync_result = _sync_workflow_job(db, failed, auto_advance=False)
        return {
            "status": failed.get("status") if failed else "failed",
            "job": failed,
            "error": str(err),
            "workflow_sync": sync_result,
        }


def sync_waiting_jobs(
    db: Session,
    *,
    workflow_run_id: str | None = None,
    auto_advance: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """批量同步等待子任务的 queue job。"""
    jobs = queue_service.list_queue_jobs(
        db,
        status="waiting_child",
        workflow_run_id=workflow_run_id,
        limit=limit,
    )
    results: list[dict[str, Any]] = []
    for job in jobs:
        updated = queue_service.sync_waiting_child_job(db, job["id"])
        sync_result = None
        if updated and updated.get("status") in queue_service.TERMINAL_JOB_STATUSES:
            sync_result = _sync_workflow_job(db, updated, auto_advance=auto_advance)
        results.append({"job": updated, "workflow_sync": sync_result})
    return {"status": "completed", "synced": len(results), "results": results}


def recover_stale_jobs(
    db: Session,
    *,
    timeout_seconds: int = 1800,
    limit: int = 100,
) -> dict[str, Any]:
    """回收超时任务，并把最终失败同步到关联 workflow。"""
    recovered = queue_service.recover_stale_processing_jobs(
        db,
        timeout_seconds=timeout_seconds,
        limit=limit,
    )
    workflow_syncs: list[dict[str, Any]] = []
    for job in recovered.get("jobs") or []:
        if job.get("status") == "failed":
            sync_result = _sync_workflow_job(db, job, auto_advance=False)
            if sync_result:
                workflow_syncs.append(sync_result)
    return {**recovered, "workflow_syncs": workflow_syncs}


def cancel_job(db: Session, job_id: str, *, reason: str | None = None) -> dict[str, Any] | None:
    """取消队列任务，并立即把取消状态同步到关联工作流。"""
    job = queue_service.cancel_job(db, job_id, reason=reason)
    if not job:
        return None
    sync_result = None
    if job.get("status") == "cancelled":
        sync_result = _sync_workflow_job(db, job, auto_advance=False)
    return {"status": job.get("status"), "job": job, "workflow_sync": sync_result}


def _execute_workflow_job(db: Session, job: dict[str, Any]) -> dict[str, Any]:
    from app.workflows import executor

    payload = job.get("payload") or {}
    workflow_run_id = payload.get("workflow_run_id") or job.get("workflow_run_id")
    step_key = payload.get("step_key")
    if not workflow_run_id or not step_key:
        raise ValueError("workflow queue job 缺少 workflow_run_id 或 step_key")
    options = dict(payload.get("executor_options") or {})
    # 强制 direct，防止 worker 调用执行器后再次创建同类型 queue job。
    options["queue"] = False
    options["execution_mode"] = "direct"
    return executor.execute_step(db, None, str(workflow_run_id), str(step_key), options)


def _execute_media_job(db: Session, job: dict[str, Any]) -> dict[str, Any]:
    """执行多媒体生成类异步长任务（生图、生视频、音频合成等）。"""
    task_type = str(job.get("task_type") or "")
    payload = job.get("payload") or {}
    job_id = str(job.get("id") or "")
    
    from app.tasks import dramatiq_worker

    if task_type in ("image.generate", "generate.image"):
        return dramatiq_worker.execute_image_generation(job_id, payload, db=db)
    elif task_type in ("video.generate", "generate.video"):
        return dramatiq_worker.execute_video_generation(job_id, payload, db=db)
    elif task_type in ("audio.generate", "generate.audio"):
        return dramatiq_worker.execute_audio_generation(job_id, payload, db=db)
    else:
        # 通用 fallback
        return {"task_type": task_type, "status": "completed", "payload": payload}


def _extract_child_async_task_id(result: dict[str, Any] | None) -> str | None:
    if not isinstance(result, dict):
        return None
    task_id = result.get("async_task_id")
    return str(task_id) if task_id else None


def _rebind_workflow_step(db: Session, job: dict[str, Any], result: dict[str, Any]) -> None:
    """执行器可能覆盖 step.output_payload，这里重新写回 queue_job 关联信息。"""
    workflow_run_id = job.get("workflow_run_id")
    payload = job.get("payload") or {}
    step_key = payload.get("step_key")
    if not workflow_run_id or not step_key:
        return
    from app.workflows import run_service

    step = run_service.get_workflow_step(db, str(workflow_run_id), str(step_key))
    if not step:
        return
    run_service.update_workflow_step(
        db,
        str(workflow_run_id),
        str(step_key),
        {
            "output_payload": {
                **(step.get("output_payload") or {}),
                "queue_job_id": job.get("id"),
                "queue_async_task_id": job.get("async_task_id"),
                "executor_result": result,
            }
        },
    )


def _sync_workflow_job(
    db: Session,
    job: dict[str, Any] | None,
    *,
    auto_advance: bool,
) -> dict[str, Any] | None:
    if not job or not job.get("workflow_run_id"):
        return None
    payload = job.get("payload") or {}
    step_key = payload.get("step_key")
    if not step_key:
        return None
    from app.workflows import queue_bridge

    executor_options = (job.get("payload") or {}).get("executor_options") or {}
    return queue_bridge.sync_step_from_queue_job(
        db,
        str(job["workflow_run_id"]),
        str(step_key),
        {
            "auto_advance": auto_advance,
            # 自动推进仍走持久化队列，并继承本次任务是否允许真实调用 AI。
            "queue": True,
            "execution_mode": "queued",
            "execute_ai": bool(executor_options.get("execute_ai")),
        },
    )
