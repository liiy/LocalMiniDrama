"""Workflow Run 服务。

这是后续 LangGraph / Dramatiq 接入前的持久化底座：先把工作流、步骤、
Agent 运行和 Prompt Run 串起来，保证任何一次剧本生成或小说改编都可追踪、可恢复。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso
from app.workflows import graph as workflow_graph
from app.workflows.blueprints import get_workflow_blueprint


VALID_WORKFLOW_TYPES = {
    "original_script",
    "novel_adaptation",
    "entity_extraction",
    "storyboard_generation",
    "asset_generation",
    "voice_music_generation",
    "video_production",
}


def create_workflow_run(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """创建工作流运行记录。

    workflow_runs 是短期记忆的主索引：它保存当前状态，并把每个 step、agent_run、
    prompt_run 串成一条可恢复的生产流水线。
    """
    workflow_type = str(payload.get("type") or "").strip()
    if workflow_type not in VALID_WORKFLOW_TYPES:
        raise ValueError(f"type 必须是以下之一：{', '.join(sorted(VALID_WORKFLOW_TYPES))}")
    run_id = str(payload.get("id") or uuid.uuid4())
    now = now_iso()
    db.execute(
        text(
            """
            INSERT INTO workflow_runs (
                id, type, status, drama_id, episode_id, user_request,
                input_payload, state, result, error, created_at, updated_at
            ) VALUES (
                :id, :type, :status, :drama_id, :episode_id, :user_request,
                :input_payload, :state, :result, :error, :now, :now
            )
            """
        ),
        {
            "id": run_id,
            "type": workflow_type,
            "status": payload.get("status") or "pending",
            "drama_id": payload.get("drama_id"),
            "episode_id": payload.get("episode_id"),
            "user_request": payload.get("user_request"),
            "input_payload": json_dumps(_normalize_step_input_payload(payload)),
            "state": json_dumps(payload.get("state") or {}),
            "result": json_dumps(payload.get("result") or {}),
            "error": payload.get("error"),
            "now": now,
        },
    )
    if payload.get("seed_steps", True):
        _seed_workflow_steps(db, run_id, workflow_type)
    return get_workflow_run(db, run_id) or {"id": run_id}


def _seed_workflow_steps(db: Session, workflow_run_id: str, workflow_type: str) -> None:
    """按蓝图初始化步骤。

    步骤只负责描述编排状态，不在这里执行 AI。这样工作流可以先被创建、审核、
    暂停或局部重试，后续再由 Worker/Agent Runtime 消费这些 step。
    """
    steps = get_workflow_blueprint(workflow_type)
    for step in steps:
        add_workflow_step(
            db,
            workflow_run_id,
            {
                "step_key": step["step_key"],
                "agent_name": step.get("agent_name"),
                "skill_key": step.get("skill_key"),
                "status": "pending",
                "input_payload": {
                    "title": step.get("title") or step["step_key"],
                    # 依赖关系保存在 input_payload，兼容现有表结构，后续可直接迁移到独立 DAG 表。
                    "depends_on": step.get("depends_on") or [],
                },
            },
        )


def _normalize_step_input_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """统一整理 step 输入，把 depends_on 放进 input_payload 便于任务图读取。"""
    input_payload = dict(payload.get("input_payload") or {})
    if "depends_on" in payload and "depends_on" not in input_payload:
        input_payload["depends_on"] = payload.get("depends_on") or []
    return input_payload


def add_workflow_step(db: Session, workflow_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """追加一个工作流步骤，供编排器逐步推进。"""
    if not fetch_one(db, "SELECT id FROM workflow_runs WHERE id = :id AND deleted_at IS NULL", {"id": workflow_run_id}):
        raise ValueError("workflow_run 不存在")
    step_key = str(payload.get("step_key") or "").strip()
    if not step_key:
        raise ValueError("step_key 必填")
    now = now_iso()
    res = db.execute(
        text(
            """
            INSERT INTO workflow_steps (
                workflow_run_id, step_key, agent_name, skill_key, status,
                input_payload, output_payload, error, retry_count,
                started_at, completed_at, created_at, updated_at
            ) VALUES (
                :workflow_run_id, :step_key, :agent_name, :skill_key, :status,
                :input_payload, :output_payload, :error, :retry_count,
                :started_at, :completed_at, :now, :now
            )
            """
        ),
        {
            "workflow_run_id": workflow_run_id,
            "step_key": step_key,
            "agent_name": payload.get("agent_name"),
            "skill_key": payload.get("skill_key"),
            "status": payload.get("status") or "pending",
            "input_payload": json_dumps(payload.get("input_payload") or {}),
            "output_payload": json_dumps(payload.get("output_payload") or {}),
            "error": payload.get("error"),
            "retry_count": int(payload.get("retry_count") or 0),
            "started_at": payload.get("started_at"),
            "completed_at": payload.get("completed_at"),
            "now": now,
        },
    )
    return result_to_dict(db.execute(text("SELECT * FROM workflow_steps WHERE id = :id"), {"id": res.lastrowid}).first())


def update_workflow_step(db: Session, workflow_run_id: str, step_key: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """按 step_key 更新工作流步骤状态。

    旧服务逐步接入编排时通常只知道“当前在跑哪个业务步骤”，不一定知道 step_id。
    因此这里使用 workflow_run_id + step_key 定位最新一条步骤记录。
    """
    rows = fetch_all(
        db,
        """
        SELECT id FROM workflow_steps
        WHERE workflow_run_id = :workflow_run_id AND step_key = :step_key AND deleted_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        {"workflow_run_id": workflow_run_id, "step_key": step_key},
    )
    if not row:
        return None

    status = payload.get("status")
    now = now_iso()
    updates: list[str] = ["updated_at = :updated_at"]
    params: dict[str, Any] = {"id": row["id"], "updated_at": now}
    for key in ("agent_name", "skill_key", "status", "error"):
        if key in payload:
            updates.append(f"{key} = :{key}")
            params[key] = payload[key]
    if "input_payload" in payload:
        updates.append("input_payload = :input_payload")
        params["input_payload"] = json_dumps(payload.get("input_payload") or {})
    if "output_payload" in payload:
        updates.append("output_payload = :output_payload")
        params["output_payload"] = json_dumps(payload.get("output_payload") or {})
    if "retry_count" in payload:
        updates.append("retry_count = :retry_count")
        params["retry_count"] = int(payload.get("retry_count") or 0)
    if payload.get("started_at") or status == "processing":
        updates.append("started_at = COALESCE(started_at, :started_at)")
        params["started_at"] = payload.get("started_at") or now
    if payload.get("completed_at") or status in (workflow_graph.COMPLETED_STATUSES | workflow_graph.FAILED_STATUSES):
        updates.append("completed_at = :completed_at")
        params["completed_at"] = payload.get("completed_at") or now

    db.execute(text("UPDATE workflow_steps SET " + ", ".join(updates) + " WHERE id = :id"), params)
    return result_to_dict(db.execute(text("SELECT * FROM workflow_steps WHERE id = :id"), {"id": row["id"]}).first())


def get_workflow_step(db: Session, workflow_run_id: str, step_key: str) -> dict[str, Any] | None:
    """读取工作流中的指定步骤。"""
    row = fetch_one(
        db,
        """
        SELECT * FROM workflow_steps
        WHERE workflow_run_id = :workflow_run_id AND step_key = :step_key AND deleted_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        {"workflow_run_id": workflow_run_id, "step_key": step_key},
    )
    if not row:
        return None
    row["input_payload"] = json_loads(row.get("input_payload"), {})
    row["output_payload"] = json_loads(row.get("output_payload"), {})
    return row


def get_next_pending_step(db: Session, workflow_run_id: str) -> dict[str, Any] | None:
    """获取下一个待执行步骤。"""
    rows = fetch_all(
        db,
        """
        SELECT * FROM workflow_steps
        WHERE workflow_run_id = :workflow_run_id
          AND deleted_at IS NULL
        ORDER BY id ASC
        """,
        {"workflow_run_id": workflow_run_id},
    )
    for row in rows:
        row["input_payload"] = json_loads(row.get("input_payload"), {})
        row["output_payload"] = json_loads(row.get("output_payload"), {})
        row["depends_on"] = workflow_graph.step_dependencies(row)
    ready = workflow_graph.runnable_steps(rows)
    if not ready:
        return None
    return ready[0]


def get_workflow_execution_state(db: Session, workflow_run_id: str) -> dict[str, Any]:
    """返回 workflow 的任务图状态，供执行器和前端判断下一步。"""
    steps = fetch_all(
        db,
        """
        SELECT * FROM workflow_steps
        WHERE workflow_run_id = :workflow_run_id AND deleted_at IS NULL
        ORDER BY id ASC
        """,
        {"workflow_run_id": workflow_run_id},
    )
    for step in steps:
        step["input_payload"] = json_loads(step.get("input_payload"), {})
        step["output_payload"] = json_loads(step.get("output_payload"), {})
        step["depends_on"] = workflow_graph.step_dependencies(step)
    runnable = workflow_graph.runnable_steps(steps)
    progress = workflow_graph.workflow_progress(steps)
    return {
        "workflow_run_id": workflow_run_id,
        "progress": progress,
        "runnable_steps": runnable,
        "blocked_steps": [
            step for step in steps if step.get("status") in workflow_graph.READY_STATUSES and step not in runnable
        ],
        "steps": steps,
    }


def merge_workflow_state(db: Session, workflow_run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """合并短期状态，避免步骤同步时覆盖其他 Agent 已写入的上下文。"""
    workflow = get_workflow_run(db, workflow_run_id, include_steps=False) or {"state": {}}
    state = dict(workflow.get("state") or {})
    state.update(patch)
    return update_workflow_run(db, workflow_run_id, {"state": state})


def reconcile_workflow_after_step(
    db: Session,
    workflow_run_id: str,
    *,
    last_completed_step: str | None = None,
) -> dict[str, Any]:
    """按整个任务图重算 workflow 状态，避免并行分支过早宣告完成。"""
    execution_state = get_workflow_execution_state(db, workflow_run_id)
    progress = execution_state.get("progress") or {}
    runnable = execution_state.get("runnable_steps") or []
    if progress.get("failed"):
        status = "failed"
    elif progress.get("total") == progress.get("completed"):
        status = "completed"
    else:
        status = "processing"
    workflow = get_workflow_run(db, workflow_run_id, include_steps=False) or {"state": {}}
    state = dict(workflow.get("state") or {})
    if last_completed_step:
        state["last_completed_step"] = last_completed_step
    state["next_step"] = runnable[0].get("step_key") if runnable else None
    payload: dict[str, Any] = {"status": status, "state": state}
    if status == "completed":
        payload["completed_at"] = now_iso()
    updated = update_workflow_run(db, workflow_run_id, payload)
    return {
        "workflow": updated,
        "execution_state": execution_state,
        "next_step": runnable[0] if runnable else None,
    }


def update_workflow_run(db: Session, workflow_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新工作流状态；失败、暂停、完成都走这里。"""
    allowed = {"status", "state", "result", "error", "completed_at"}
    sets: list[str] = []
    params: dict[str, Any] = {"id": workflow_run_id, "updated_at": now_iso()}
    for key in allowed:
        if key not in payload:
            continue
        sets.append(f"{key} = :{key}")
        params[key] = json_dumps(payload[key]) if key in {"state", "result"} else payload[key]
    if not sets:
        return get_workflow_run(db, workflow_run_id) or {"id": workflow_run_id}
    sets.append("updated_at = :updated_at")
    db.execute(text("UPDATE workflow_runs SET " + ", ".join(sets) + " WHERE id = :id"), params)
    return get_workflow_run(db, workflow_run_id) or {"id": workflow_run_id}


def get_workflow_run(db: Session, workflow_run_id: str, include_steps: bool = True) -> dict[str, Any] | None:
    row = fetch_one(db, "SELECT * FROM workflow_runs WHERE id = :id AND deleted_at IS NULL", {"id": workflow_run_id})
    if not row:
        return None
    for key in ("input_payload", "state", "result"):
        row[key] = json_loads(row.get(key), {})
    if include_steps:
        steps = fetch_all(
            db,
            "SELECT * FROM workflow_steps WHERE workflow_run_id = :id AND deleted_at IS NULL ORDER BY id ASC",
            {"id": workflow_run_id},
        )
        for step in steps:
            step["input_payload"] = json_loads(step.get("input_payload"), {})
            step["output_payload"] = json_loads(step.get("output_payload"), {})
        row["steps"] = steps
    return row


def list_workflow_runs(
    db: Session,
    *,
    drama_id: int | None = None,
    status: str | None = None,
    workflow_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 50), 100))}
    if drama_id:
        where.append("drama_id = :drama_id")
        params["drama_id"] = drama_id
    if status:
        where.append("status = :status")
        params["status"] = status
    if workflow_type:
        where.append("type = :type")
        params["type"] = workflow_type
    rows = fetch_all(
        db,
        "SELECT * FROM workflow_runs WHERE " + " AND ".join(where) + " ORDER BY created_at DESC LIMIT :limit",
        params,
    )
    for row in rows:
        row["input_payload"] = json_loads(row.get("input_payload"), {})
        row["state"] = json_loads(row.get("state"), {})
        row["result"] = json_loads(row.get("result"), {})
    return rows
