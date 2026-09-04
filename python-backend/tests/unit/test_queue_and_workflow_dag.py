"""单元测试：验证迭代 4 持久化任务队列与工作流 DAG 状态机。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.tasks.queue_service import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    queue_summary,
    stale_cutoff_iso,
)
from app.workflows.blueprints import get_workflow_blueprint
from app.workflows.graph import (
    attach_linear_dependencies,
    detect_cycles,
    runnable_steps,
    step_dependencies,
    workflow_progress,
)
from app.workflows.queue_bridge import QUEUEABLE_STEP_KEYS, should_enqueue_step
from app.workflows.task_bridge import TERMINAL_TASK_STATUSES


def test_dag_linear_dependencies_and_step_dependencies():
    """验证未指定依赖时的线性流水线自动推导与 step_dependencies 提取。"""
    raw_steps = [
        {"step_key": "step_a"},
        {"step_key": "step_b"},
        {"step_key": "step_c", "depends_on": ["step_a"]},
    ]
    linear = attach_linear_dependencies(raw_steps)
    assert linear[0].get("depends_on") is None
    assert linear[1]["depends_on"] == ["step_a"]
    assert linear[2]["depends_on"] == ["step_a"]

    assert step_dependencies({"input_payload": {"depends_on": ["step_x", "step_y"]}}) == ["step_x", "step_y"]
    assert step_dependencies({"depends_on": "step_m, step_n"}) == ["step_m", "step_n"]


def test_dag_runnable_steps_and_progress_tracking():
    """验证只有上游步骤全部 completed 时，下游步骤才进入 runnable 集合。"""
    steps = [
        {"step_key": "step_1", "status": "completed", "depends_on": []},
        {"step_key": "step_2", "status": "pending", "depends_on": ["step_1"]},
        {"step_key": "step_3", "status": "pending", "depends_on": ["step_2"]},
    ]
    ready = runnable_steps(steps)
    assert len(ready) == 1
    assert ready[0]["step_key"] == "step_2"

    prog = workflow_progress(steps)
    assert prog["total"] == 3
    assert prog["completed"] == 1
    assert prog["pending"] == 2
    assert prog["runnable"] == 1
    assert prog["waiting"] == 1
    assert prog["percent"] == 33.33


def test_dag_detect_cycles_identifies_deadlocks():
    """验证 DAG 依赖成环检测。"""
    acyclic_steps = [
        {"step_key": "a", "depends_on": []},
        {"step_key": "b", "depends_on": ["a"]},
        {"step_key": "c", "depends_on": ["b"]},
    ]
    assert len(detect_cycles(acyclic_steps)) == 0

    cyclic_steps = [
        {"step_key": "a", "depends_on": ["c"]},
        {"step_key": "b", "depends_on": ["a"]},
        {"step_key": "c", "depends_on": ["b"]},
    ]
    cycles = detect_cycles(cyclic_steps)
    assert len(cycles) > 0


def test_queue_summary_and_stale_cutoff():
    """验证任务队列状态聚合与心跳超时时间计算。"""
    jobs = [
        {"status": "pending"},
        {"status": "processing"},
        {"status": "completed"},
        {"status": "failed"},
    ]
    summary = queue_summary(jobs)
    assert summary["total"] == 4
    assert summary["pending"] == 1
    assert summary["processing"] == 1
    assert summary["completed"] == 1
    assert summary["failed"] == 1

    cutoff = stale_cutoff_iso(timeout_seconds=300)
    assert "T" in cutoff


def test_queue_bridge_queueable_steps():
    """验证长耗时生成步骤可入队判断。"""
    assert "voice_music_generation" in QUEUEABLE_STEP_KEYS
    assert should_enqueue_step({"queue": True}, "voice_music_generation") is True
    assert should_enqueue_step({"execution_mode": "queued"}, "voice_music_generation") is True
    assert should_enqueue_step({"queue": False}, "voice_music_generation") is False
