"""Workflow 与 queue_jobs 的桥接层。

这一层只处理“步骤入队”和“队列结果同步回工作流”，不直接执行具体 AI 任务。
后续无论底层使用线程池、Celery 还是 Dramatiq，都可以继续复用这里的 workflow 语义。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.skills import registry_service as skill_registry
from app.tasks import queue_service
from app.workflows import run_service


QUEUEABLE_STEP_KEYS = {
    "episode_script_generation",
    "character_extraction",
    "scene_extraction",
    "prop_extraction",
    "storyboard_generation",
    "frame_prompt_generation",
    "video_prompt_generation",
    "voice_profile_generation",
    "music_bible_generation",
    "requirement_analysis",
    "drama_bible_generation",
    "adaptation_plan_generation",
    "creative_quality_review",
}


def should_enqueue_step(options: dict[str, Any] | None, step_key: str) -> bool:
    """判断当前 step 是否走队列。

    兼容两种参数：queue=true 或 execution_mode='queued'。
    """
    options = options or {}
    if step_key not in QUEUEABLE_STEP_KEYS:
        return False
    return bool(options.get("queue")) or options.get("execution_mode") == "queued"


def enqueue_workflow_step(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    snapshot: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 workflow step 转成持久化队列任务。

    workflow step 保持 processing；queue job 的完成/失败由 sync-step 拉回。
    """
    options = options or {}
    workflow_run_id = run["id"]
    step_key = step["step_key"]
    job = queue_service.enqueue_job(
        db,
        {
            "queue_name": options.get("queue_name") or "workflow",
            "task_type": f"workflow.{step_key}",
            "resource_id": workflow_run_id,
            "priority": options.get("priority") or 0,
            "max_attempts": options.get("max_attempts") or 3,
            "workflow_run_id": workflow_run_id,
            "workflow_step_id": str(step["id"]),
            "payload": {
                "workflow_run_id": workflow_run_id,
                "workflow_step_id": str(step["id"]),
                "step_key": step_key,
                "execute_ai": bool(options.get("execute_ai")),
                "context_snapshot_id": snapshot.get("id"),
                "input_payload": options.get("input_payload") or {},
                # worker 真正执行时必须关闭 queue，避免同一个 step 被重复入队。
                "executor_options": {**options, "queue": False, "execution_mode": "direct"},
            },
        },
    )
    updated_step = run_service.update_workflow_step(
        db,
        workflow_run_id,
        step_key,
        {
            "status": "processing",
            "output_payload": {
                **(step.get("output_payload") or {}),
                "queue_job_id": job.get("id"),
                "async_task_id": job.get("async_task_id"),
                "context_snapshot_id": snapshot.get("id"),
            },
        },
    )
    return {"status": "queued", "queue_job": job, "step": updated_step}


def sync_step_from_queue_job(
    db: Session,
    workflow_run_id: str,
    step_key: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """如果 step 绑定了 queue_job，则把队列状态同步回 workflow。

    返回 None 表示该 step 没走队列，调用方可以继续按 async_task 旧逻辑处理。
    """
    options = options or {}
    step = run_service.get_workflow_step(db, workflow_run_id, step_key)
    if not step:
        raise ValueError("Workflow Step 不存在")
    output_payload = step.get("output_payload") or {}
    queue_job_id = output_payload.get("queue_job_id")
    if not queue_job_id:
        return None

    job = queue_service.get_queue_job(db, queue_job_id)
    if not job:
        return {"status": "skipped", "message": "queue_job 不存在", "queue_job_id": queue_job_id, "step": step}
    if job.get("status") in queue_service.ACTIVE_JOB_STATUSES:
        return {"status": "processing", "queue_job": job, "step": step}

    agent_run_id = output_payload.get("agent_run_id")
    if job.get("status") == "completed":
        payload = step.get("input_payload") or {}
        requires_approval = bool(payload.get("requires_approval", False))
        if options.get("skip_approvals"):
            requires_approval = False
        elif options.get("approval_required_steps"):
            requires_approval = step_key in options["approval_required_steps"]

        target_status = "waiting_approval" if requires_approval else "completed"
        updated_step = run_service.update_workflow_step(
            db,
            workflow_run_id,
            step_key,
            {
                "status": target_status,
                "output_payload": {**output_payload, "queue_job": job, "queue_result": job.get("result") or {}},
            },
        )
        if agent_run_id:
            skill_registry.update_agent_run(
                db,
                agent_run_id,
                {"status": "completed", "output_payload": {"queue_job": job, "queue_result": job.get("result") or {}}},
            )
        reconciled = run_service.reconcile_workflow_after_step(
            db,
            workflow_run_id,
            last_completed_step=step_key if target_status == "completed" else None,
        )
        next_step = reconciled.get("next_step")
        result = {"status": target_status, "queue_job": job, "step": updated_step, "next_step": next_step}
        if target_status == "completed" and options.get("auto_advance") and next_step:
            from app.workflows import executor

            result["auto_advance"] = executor.run_until_blocked(db, None, workflow_run_id, options)
        return result

    is_cancelled = job.get("status") == "cancelled"
    terminal_status = "cancelled" if is_cancelled else "failed"
    error = job.get("error") or ("队列任务已取消" if is_cancelled else "队列任务失败")
    updated_step = run_service.update_workflow_step(
        db,
        workflow_run_id,
        step_key,
        {"status": terminal_status, "error": error, "output_payload": {**output_payload, "queue_job": job}},
    )
    if agent_run_id:
        skill_registry.update_agent_run(
            db,
            agent_run_id,
            {"status": terminal_status, "error": error, "output_payload": {"queue_job": job}},
        )
    run_service.update_workflow_run(db, workflow_run_id, {"status": terminal_status, "error": error})
    return {"status": terminal_status, "queue_job": job, "step": updated_step}
