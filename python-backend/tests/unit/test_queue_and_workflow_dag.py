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


def test_workflow_lifecycle_controls(db_session):
    """验证工作流暂停、恢复、取消与局部步骤重试功能。"""
    from app.workflows.run_service import (
        cancel_workflow_run,
        create_workflow_run,
        get_workflow_run,
        pause_workflow_run,
        resume_workflow_run,
        retry_workflow_step,
        update_workflow_step,
    )

    wf = create_workflow_run(
        db_session,
        {
            "type": "original_script",
            "user_request": "都市神豪爽剧",
            "status": "processing",
        },
    )
    run_id = wf["id"]

    # 1. 暂停工作流
    paused = pause_workflow_run(db_session, run_id)
    assert paused["status"] == "paused"

    # 2. 恢复工作流
    resumed = resume_workflow_run(db_session, run_id)
    assert resumed["status"] == "processing"

    # 3. 模拟步骤失败与单步重试
    update_workflow_step(db_session, run_id, "requirement_analysis", {"status": "failed", "error": "AI超时"})
    retried_step = retry_workflow_step(db_session, run_id, "requirement_analysis")
    assert retried_step["status"] == "pending"
    assert retried_step["retry_count"] >= 1

    # 4. 取消工作流
    cancelled = cancel_workflow_run(db_session, run_id, reason="用户取消")
    assert cancelled["status"] == "cancelled"
    wf_after = get_workflow_run(db_session, run_id)
    assert wf_after["status"] == "cancelled"


def test_dramatiq_worker_dispatch_and_execution(db_session):
    """验证 Dramatiq 统一任务分发器与多媒体长任务 Worker 执行。"""
    from app.tasks import dramatiq_worker, queue_service, worker_runner

    # 1. 任务分发测试（降级与多引擎兼容）
    dispatch_res = dramatiq_worker.dispatch_async_task(
        task_type="image.generate",
        job_id="test-job-img-001",
        payload={"prompt": "现代豪华都市豪宅全景", "options": {"aspect_ratio": "16:9"}},
    )
    assert dispatch_res["dispatched"] is True
    assert "engine" in dispatch_res

    # 2. Worker 认领并执行多媒体任务测试
    job = queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "images",
            "task_type": "image.generate",
            "payload": {"prompt": "科技感男主角特写", "options": {}},
        },
    )
    assert job["id"] is not None

    claimed_job = queue_service.claim_next_job(db_session, worker_id="test-worker", queue_name="images")
    assert claimed_job is not None
    assert claimed_job["id"] == job["id"]

    exec_result = worker_runner.execute_claimed_job(db_session, claimed_job)
    assert exec_result["status"] == "completed"
    assert exec_result["job"]["status"] == "completed"


def test_sse_streaming_endpoints(unit_client, db_session):
    """验证工作流与队列任务的 SSE (Server-Sent Events) 实时推流端点。"""
    from app.tasks import queue_service
    from app.workflows.run_service import create_workflow_run

    # 1. 测试工作流 SSE 端点
    wf = create_workflow_run(
        db_session,
        {
            "type": "original_script",
            "user_request": "古风悬疑探案剧",
            "status": "completed",
        },
    )
    wf_id = wf["id"]
    response = unit_client.get(f"/api/v1/platform/workflows/{wf_id}/stream?interval=0.2&max_duration=1")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    content = response.text
    assert "workflow_state" in content or "workflow_finished" in content

    # 2. 测试队列任务 SSE 端点
    job = queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "videos",
            "task_type": "video.generate",
            "payload": {"prompt": "雨夜追逐打斗"},
        },
    )
    job_id = job["id"]
    queue_service.complete_job(db_session, job_id, result={"video_url": "http://example.com/v.mp4"})
    
    job_stream_res = unit_client.get(f"/api/v1/platform/queue/jobs/{job_id}/stream?interval=0.2&max_duration=1")
    assert job_stream_res.status_code == 200
    assert "text/event-stream" in job_stream_res.headers.get("content-type", "")
    job_content = job_stream_res.text
    assert "job_update" in job_content or "job_finished" in job_content

