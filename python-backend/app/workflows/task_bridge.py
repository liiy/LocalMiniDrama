"""Workflow 与 async_tasks 的同步桥。

现有系统大量长任务仍由 async_tasks + workerService 承载。这个桥接层负责把旧任务状态
同步回新工作流，不要求一次性改写所有后台任务实现。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.platform_common import json_loads
from app.services import taskService
from app.skills import registry_service as skill_registry
from app.workflows import queue_bridge
from app.workflows import run_service


TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}


def sync_step_from_async_task(
    db: Session,
    workflow_run_id: str,
    step_key: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据 step.output_payload.async_task_id 同步单个步骤。"""
    options = options or {}
    step = run_service.get_workflow_step(db, workflow_run_id, step_key)
    if not step:
        raise ValueError("Workflow Step 不存在")
    queue_result = queue_bridge.sync_step_from_queue_job(db, workflow_run_id, step_key, options)
    if queue_result is not None:
        return queue_result
    output_payload = step.get("output_payload") or {}
    task_id = output_payload.get("async_task_id")
    if not task_id:
        return {"status": "skipped", "message": "该步骤没有绑定 async_task_id", "step": step}

    task = taskService.get_task(db, task_id)
    if not task:
        return {"status": "skipped", "message": "async_task 不存在", "async_task_id": task_id, "step": step}

    task_status = str(task.get("status") or "")
    if task_status not in TERMINAL_TASK_STATUSES:
        return {"status": "processing", "async_task": task, "step": step}

    task_result = json_loads(task.get("result"), {})
    agent_run_id = output_payload.get("agent_run_id")
    if task_status == "completed":
        updated_step = run_service.update_workflow_step(
            db,
            workflow_run_id,
            step_key,
            {
                "status": "completed",
                "output_payload": {
                    **output_payload,
                    "async_task": task,
                    "task_result": task_result,
                },
            },
        )
        if agent_run_id:
            skill_registry.update_agent_run(
                db,
                agent_run_id,
                {"status": "completed", "output_payload": {"async_task": task, "task_result": task_result}},
            )
        reconciled = run_service.reconcile_workflow_after_step(
            db,
            workflow_run_id,
            last_completed_step=step_key,
        )
        next_step = reconciled.get("next_step")
        result = {"status": "completed", "async_task": task, "step": updated_step, "next_step": next_step}
        if options.get("auto_advance") and next_step:
            # 自动推进只在当前异步任务已经完成后触发；遇到下一步异步 processing 会自然停下。
            from app.workflows import executor

            result["auto_advance"] = executor.run_until_blocked(db, None, workflow_run_id, options)
        return result

    error = task.get("error") or task.get("message") or "异步任务失败"
    updated_step = run_service.update_workflow_step(
        db,
        workflow_run_id,
        step_key,
        {"status": "failed", "error": error, "output_payload": {**output_payload, "async_task": task}},
    )
    if agent_run_id:
        skill_registry.update_agent_run(db, agent_run_id, {"status": "failed", "error": error, "output_payload": {"async_task": task}})
    run_service.update_workflow_run(db, workflow_run_id, {"status": "failed", "error": error})
    return {"status": "failed", "async_task": task, "step": updated_step}


def sync_all_processing_steps(
    db: Session,
    workflow_run_id: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """同步一个工作流下所有 processing 状态的异步步骤。"""
    options = options or {}
    workflow = run_service.get_workflow_run(db, workflow_run_id)
    if not workflow:
        raise ValueError("Workflow 不存在")
    results = []
    for step in workflow.get("steps") or []:
        if step.get("status") == "processing":
            results.append(sync_step_from_async_task(db, workflow_run_id, step["step_key"], options))

    auto_advance = None
    if options.get("auto_advance") and results and all(r.get("status") != "processing" for r in results):
        from app.workflows import executor

        auto_advance = executor.run_until_blocked(db, None, workflow_run_id, options)
    return {"workflow_run_id": workflow_run_id, "synced": len(results), "results": results, "auto_advance": auto_advance}
