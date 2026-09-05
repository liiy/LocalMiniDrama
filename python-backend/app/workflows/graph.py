"""Workflow 任务图工具。

这里先实现轻量级 DAG 编排能力：识别步骤依赖、判断可运行节点、生成进度摘要。
后续接 LangGraph/Celery/Dramatiq 时，可以复用这些 step_key 和依赖元数据。
"""
from __future__ import annotations

from typing import Any


READY_STATUSES = {"pending", "retry"}
WAITING_APPROVAL_STATUSES = {"waiting_approval"}
COMPLETED_STATUSES = {
    "completed",
    "completed_with_parse_warning",
    "completed_with_apply_warning",
    "completed_with_approval",
}
BLOCKING_STATUSES = {"processing", "waiting_approval"}
FAILED_STATUSES = {"failed", "cancelled", "rejected"}


def step_dependencies(step: dict[str, Any]) -> list[str]:
    """从 step 记录中读取依赖。

    依赖优先放在 input_payload.depends_on，兼容数据库已有字段，不额外扩表。
    """
    payload = step.get("input_payload") or {}
    raw = step.get("depends_on") or payload.get("depends_on") or []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def attach_linear_dependencies(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给未声明依赖的蓝图补线性依赖，保证旧蓝图也能按顺序执行。"""
    result: list[dict[str, Any]] = []
    previous_key = ""
    for step in steps:
        item = dict(step)
        if previous_key and "depends_on" not in item:
            item["depends_on"] = [previous_key]
        result.append(item)
        previous_key = str(item.get("step_key") or "")
    return result


def runnable_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回当前可以执行的 pending/retry 步骤。

    不存在于当前 workflow 的依赖会被忽略，用于支持局部 workflow，例如只跑分镜或只跑视频生产。
    """
    by_key = {step.get("step_key"): step for step in steps if step.get("step_key")}
    ready: list[dict[str, Any]] = []
    for step in steps:
        if step.get("status") not in READY_STATUSES:
            continue
        deps = [dep for dep in step_dependencies(step) if dep in by_key]
        if all(by_key[dep].get("status") in COMPLETED_STATUSES for dep in deps):
            ready.append(step)
    return ready


def workflow_progress(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """生成任务图进度摘要，便于 API 和前端判断是完成、阻塞、等待人工审核还是处理中。"""
    total = len(steps)
    completed = sum(1 for step in steps if step.get("status") in COMPLETED_STATUSES)
    processing = sum(1 for step in steps if step.get("status") == "processing")
    waiting_approval = sum(1 for step in steps if step.get("status") in WAITING_APPROVAL_STATUSES)
    failed = sum(1 for step in steps if step.get("status") in FAILED_STATUSES)
    ready = runnable_steps(steps)
    pending = sum(1 for step in steps if step.get("status") in READY_STATUSES)
    waiting = max(0, pending - len(ready))
    return {
        "total": total,
        "completed": completed,
        "processing": processing,
        "waiting_approval": waiting_approval,
        "failed": failed,
        "pending": pending,
        "waiting": waiting,
        "runnable": len(ready),
        "percent": 100 if total == 0 else round(completed * 100 / total, 2),
    }


def detect_cycles(steps: list[dict[str, Any]]) -> list[list[str]]:
    """检测蓝图依赖环，防止任务图永远无法推进。"""
    graph = {step.get("step_key"): step_dependencies(step) for step in steps if step.get("step_key")}
    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str, path: list[str]) -> None:
        if key in visiting:
            start = path.index(key) if key in path else 0
            cycles.append(path[start:] + [key])
            return
        if key in visited:
            return
        visiting.add(key)
        for dep in graph.get(key, []):
            if dep in graph:
                visit(dep, path + [dep])
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key, [key])
    return cycles
