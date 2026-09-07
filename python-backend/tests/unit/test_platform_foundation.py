"""单元测试：验证平台化改造底座的纯函数与 DDL 注册。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.registry import get_agent, list_agents
from app.agents.output_applier import OUTPUT_APPLIER_STEPS, normalize_agent_payload
from app.agents.runtime import AGENT_RUNTIME_STEPS, build_prompt_variables
from app.context.vector_memory_service import build_memory_document, is_vector_memory_enabled, vector_memory_settings
from app.db.schema import all_ddl
from app.platform_common import json_dumps, json_loads, render_template_text
from app.skills.defaults import DEFAULT_PROMPTS, DEFAULT_SKILLS
from app.tasks.queue_service import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES, queue_summary, stale_cutoff_iso
from app.tasks.worker_runner import SUPPORTED_TASK_PREFIX, _extract_child_async_task_id
from app.tasks.worker_runtime import WorkerRuntime, load_worker_settings
from app.workflows.blueprints import get_workflow_blueprint
from app.workflows.executor import AI_BACKED_STEPS, run_until_blocked
from app.agents.runtime import AGENT_RUNTIME_STEPS
from app.workflows.graph import detect_cycles, runnable_steps, workflow_progress
from app.workflows.queue_bridge import QUEUEABLE_STEP_KEYS, should_enqueue_step
from app.workflows.run_service import VALID_WORKFLOW_TYPES
from app.workflows.task_bridge import TERMINAL_TASK_STATUSES


def test_platform_tables_are_registered_in_schema():
    ddl = "\n".join(all_ddl())
    for table_name in (
        "prompt_templates",
        "prompt_runs",
        "skills",
        "skill_versions",
        "context_snapshots",
        "workflow_runs",
        "workflow_steps",
        "queue_jobs",
        "worker_nodes",
        "agent_runs",
        "memory_items",
        "character_voice_profiles",
        "music_bibles",
        "music_cues",
        "audio_generations",
        "quality_reports",
    ):
        assert f"CREATE TABLE IF NOT EXISTS `{table_name}`" in ddl


def test_render_template_text_keeps_missing_variables_visible():
    rendered = render_template_text("角色：{character_name}\n场景：{scene_name}", {"character_name": "顾凌霄"})

    assert "顾凌霄" in rendered
    assert "{scene_name}" in rendered


def test_json_helpers_roundtrip_chinese_payload():
    payload = {"角色": ["顾凌霄"], "音乐": {"风格": "暗黑史诗管弦"}}
    encoded = json_dumps(payload)

    assert "\\u89d2" not in encoded
    assert json_loads(encoded) == payload


def test_workflow_types_cover_two_script_entrypoints_and_downstream():
    assert "original_script" in VALID_WORKFLOW_TYPES
    assert "novel_adaptation" in VALID_WORKFLOW_TYPES
    assert "storyboard_generation" in VALID_WORKFLOW_TYPES
    assert "voice_music_generation" in VALID_WORKFLOW_TYPES


def test_default_agents_cover_creative_pipeline():
    names = {item["agent_name"] for item in list_agents()}

    assert {"producer", "novel_adapter", "script_writer", "storyboard_director", "voice", "music_director", "qa"} <= names
    assert get_agent("visual_director")["display_name"] == "视觉导演 Agent"


def test_workflow_blueprints_split_two_script_entrypoints_then_share_downstream():
    original_steps = [step["step_key"] for step in get_workflow_blueprint("original_script")]
    novel_steps = [step["step_key"] for step in get_workflow_blueprint("novel_adaptation")]
    original_by_key = {step["step_key"]: step for step in get_workflow_blueprint("original_script")}

    assert original_steps[:2] == ["requirement_analysis", "drama_bible_generation"]
    assert novel_steps[:3] == ["novel_ingestion", "chapter_slicing", "long_memory_indexing"]
    assert "character_extraction" in original_steps
    assert "character_extraction" in novel_steps
    assert original_by_key["drama_bible_generation"]["depends_on"] == ["requirement_analysis"]
    assert original_by_key["character_extraction"]["depends_on"] == ["continuity_check"]
    assert set(original_by_key["creative_quality_review"]["depends_on"]) == {
        "video_prompt_generation",
        "voice_profile_generation",
        "music_bible_generation",
    }
    assert original_steps[-1] == "creative_quality_review"
    assert novel_steps[-1] == "creative_quality_review"


def test_platform_routes_expose_blueprints_and_agents():
    from app.main import app

    paths = {route.path for route in app.routes}

    assert "/api/v1/platform/agents" in paths
    assert "/api/v1/platform/bootstrap/defaults" in paths
    assert "/api/v1/platform/workflows/blueprints" in paths
    assert "/api/v1/platform/workflows/original-script" in paths
    assert "/api/v1/platform/workflows/novel-adaptation" in paths
    assert "/api/v1/platform/workflows/{workflow_run_id}/execute-next" in paths
    assert "/api/v1/platform/workflows/{workflow_run_id}/execute-until-blocked" in paths
    assert "/api/v1/platform/workflows/{workflow_run_id}/execute-step/{step_key}" in paths
    assert "/api/v1/platform/workflows/{workflow_run_id}/graph" in paths
    assert "/api/v1/platform/workflows/{workflow_run_id}/sync-step/{step_key}" in paths
    assert "/api/v1/platform/workflows/{workflow_run_id}/sync-all" in paths
    assert "/api/v1/platform/workflows/{workflow_run_id}/steps/{step_key}" in paths
    assert "/api/v1/platform/memory/search" in paths
    assert "/api/v1/platform/memory/vector-settings" in paths
    assert "/api/v1/platform/quality-reports" in paths
    assert "/api/v1/platform/quality-reports/{report_id}" in paths
    assert "/api/v1/platform/queue/jobs" in paths
    assert "/api/v1/platform/queue/jobs/{job_id}" in paths
    assert "/api/v1/platform/queue/workers" in paths
    assert "/api/v1/platform/queue/runtime" in paths
    assert "/api/v1/platform/queue/metrics" in paths
    assert "/api/v1/platform/queue/recover-stale" in paths
    assert "/api/v1/platform/queue/jobs/{job_id}/cancel" in paths
    assert "/api/v1/platform/queue/claim-next" in paths
    assert "/api/v1/platform/queue/run-next" in paths
    assert "/api/v1/platform/queue/sync-waiting" in paths
    assert "/api/v1/platform/queue/jobs/{job_id}/complete" in paths
    assert "/api/v1/platform/queue/jobs/{job_id}/fail" in paths
    assert "/api/v1/platform/queue/jobs/{job_id}/retry" in paths
    assert "/api/v1/platform/prompt-runs" in paths
    assert "/api/v1/platform/memory/{memory_id}" in paths
    assert "/api/v1/platform/memory/distill" in paths
    assert "/api/v1/platform/memory/conflicts/detect" in paths
    assert "/api/v1/platform/memory/expire" in paths
    assert "/api/v1/platform/memory/retrieval-evaluations" in paths


def test_executor_ai_backed_steps_are_explicit():
    # 所有生成型步骤必须由统一 Agent Runtime 接管，不能再回落到旧业务分支。
    assert AI_BACKED_STEPS == AGENT_RUNTIME_STEPS


def test_task_bridge_terminal_statuses_are_explicit():
    assert TERMINAL_TASK_STATUSES == {"completed", "failed", "cancelled"}


def test_executor_exposes_run_until_blocked_strategy():
    assert callable(run_until_blocked)


def test_workflow_graph_resolves_parallel_runnable_steps():
    steps = [
        {"step_key": "continuity_check", "status": "completed", "input_payload": {}},
        {"step_key": "character_extraction", "status": "pending", "input_payload": {"depends_on": ["continuity_check"]}},
        {"step_key": "scene_extraction", "status": "pending", "input_payload": {"depends_on": ["continuity_check"]}},
        {"step_key": "visual_prompt_generation", "status": "pending", "input_payload": {"depends_on": ["character_extraction"]}},
    ]

    ready = {step["step_key"] for step in runnable_steps(steps)}

    assert ready == {"character_extraction", "scene_extraction"}
    assert workflow_progress(steps)["runnable"] == 2


def test_workflow_graph_detects_dependency_cycles():
    cycles = detect_cycles(
        [
            {"step_key": "a", "input_payload": {"depends_on": ["b"]}},
            {"step_key": "b", "input_payload": {"depends_on": ["a"]}},
        ]
    )

    assert cycles


def test_queue_job_statuses_and_summary_are_explicit():
    assert TERMINAL_JOB_STATUSES == {"completed", "failed", "cancelled"}
    assert ACTIVE_JOB_STATUSES == {"pending", "retry", "processing", "waiting_child"}

    summary = queue_summary(
        [
            {"status": "pending"},
            {"status": "processing"},
            {"status": "waiting_child"},
            {"status": "completed"},
        ]
    )

    assert summary["total"] == 4
    assert summary["pending"] == 1
    assert summary["processing"] == 1
    assert summary["waiting_child"] == 1
    assert summary["completed"] == 1


def test_workflow_queue_bridge_only_enqueues_supported_steps():
    assert "episode_script_generation" in QUEUEABLE_STEP_KEYS
    assert "creative_quality_review" in QUEUEABLE_STEP_KEYS
    assert should_enqueue_step({"queue": True}, "episode_script_generation") is True
    assert should_enqueue_step({"execution_mode": "queued"}, "creative_quality_review") is True
    assert should_enqueue_step({"queue": True}, "novel_ingestion") is False


def test_worker_runner_recognizes_workflow_jobs_and_child_tasks():
    assert "workflow." in SUPPORTED_TASK_PREFIX
    assert _extract_child_async_task_id({"status": "processing", "async_task_id": "task-1"}) == "task-1"
    assert _extract_child_async_task_id({"status": "completed"}) is None


def test_worker_runtime_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("LMD_QUEUE_WORKER_ENABLED", raising=False)
    monkeypatch.delenv("LMD_QUEUE_WORKER_QUEUES", raising=False)
    settings = load_worker_settings(
        {
            "queue": {
                "worker": {
                    "enabled": False,
                    "worker_id": "unit-worker",
                    "queues": ["workflow", "media"],
                }
            }
        }
    )
    runtime = WorkerRuntime(settings)

    assert settings.enabled is False
    assert settings.queues == ("workflow", "media")
    assert runtime.start() is False
    assert runtime.status()["status"] == "disabled"


def test_worker_runtime_parses_story_and_media_queues(monkeypatch):
    """验证生产队列环境变量能覆盖 YAML，并去除重复队列名称。"""
    monkeypatch.delenv("LMD_QUEUE_WORKER_ENABLED", raising=False)
    monkeypatch.setenv(
        "LMD_QUEUE_WORKER_QUEUES",
        "workflow,stories,entities,storyboards,images,videos,audio,stories",
    )

    settings = load_worker_settings({"queue": {"worker": {"enabled": True}}})

    assert settings.enabled is True
    assert settings.queues == (
        "workflow",
        "stories",
        "entities",
        "storyboards",
        "images",
        "videos",
        "audio",
    )


def test_worker_runtime_rotates_queue_start_position(monkeypatch):
    """验证连续消费时采用轮询起点，避免首个繁忙队列长期占用 Worker。"""
    from contextlib import contextmanager

    from app.tasks import worker_runtime

    # 测试显式配置应与开发机 .env 隔离。
    monkeypatch.delenv("LMD_QUEUE_WORKER_QUEUES", raising=False)
    monkeypatch.delenv("LMD_QUEUE_WORKER_ENABLED", raising=False)
    settings = load_worker_settings(
        {
            "queue": {
                "worker": {
                    "enabled": True,
                    "worker_id": "fair-worker",
                    "queues": ["workflow", "stories", "entities"],
                }
            }
        }
    )
    runtime = WorkerRuntime(settings)
    visited: list[str] = []

    @contextmanager
    def fake_session_scope():
        yield object()

    def complete_first_queue(_db, *, worker_id, queue_name, auto_advance):
        visited.append(queue_name)
        return {"status": "completed", "worker_id": worker_id, "auto_advance": auto_advance}

    monkeypatch.setattr(worker_runtime, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker_runtime.worker_runner, "run_next_job", complete_first_queue)

    runtime._run_one_from_queues()
    runtime._run_one_from_queues()
    runtime._run_one_from_queues()

    assert visited == ["workflow", "stories", "entities"]


def test_env_example_covers_all_application_environment_variables():
    """保证代码新增 LMD 环境变量时必须同步维护 env.example。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in (root / "app").rglob("*.py"))
    used = set(re.findall(r"LMD_[A-Z0-9_]+", source_text))
    example_text = (root / ".env.example").read_text(encoding="utf-8")
    declared = set(re.findall(r"(?m)^(LMD_[A-Z0-9_]+)=", example_text))
    assert used <= declared


def test_stale_cutoff_uses_utc_iso_format():
    cutoff = stale_cutoff_iso(
        60,
        datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert cutoff == "2026-09-04T11:59:00.000Z"


def test_worker_startup_recovery_uses_runner(monkeypatch):
    """启动恢复必须经过 Runner，保证最终失败能够同步到工作流。"""
    from contextlib import contextmanager

    from app.tasks import worker_runtime

    calls: list[tuple[str, int]] = []

    @contextmanager
    def fake_session_scope():
        yield object()

    def record_recovery(_db, *, timeout_seconds):
        calls.append(("recover", timeout_seconds))
        return {"count": 0}

    monkeypatch.delenv("LMD_QUEUE_WORKER_ENABLED", raising=False)
    monkeypatch.delenv("LMD_QUEUE_WORKER_ID", raising=False)
    settings = load_worker_settings(
        {
            "queue": {
                "worker": {
                    "enabled": True,
                    "worker_id": "unit-worker",
                    "queues": ["workflow"],
                }
            }
        }
    )
    runtime = WorkerRuntime(settings)
    monkeypatch.setattr(worker_runtime, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        worker_runtime.queue_service,
        "register_worker",
        lambda _db, **_kwargs: {"worker_id": "unit-worker"},
    )
    monkeypatch.setattr(
        worker_runtime.worker_runner,
        "recover_stale_jobs",
        record_recovery,
    )
    # 避免单元测试真正启动常驻线程，只验证启动阶段的调用链。
    monkeypatch.setattr(worker_runtime.threading.Thread, "start", lambda _self: None)

    runtime.start()

    assert calls == [("recover", settings.stale_job_seconds)]


def test_worker_preserves_cancellation_after_executor_returns(monkeypatch):
    """耗时调用期间发生取消时，不得再完成任务或推进下游。"""
    from app.tasks import worker_runner

    states = iter(
        [
            {"id": "job-1", "status": "processing"},
            {"id": "job-1", "status": "cancelled", "workflow_run_id": "run-1"},
        ]
    )
    completed_jobs: list[str] = []
    rebound_steps: list[str] = []
    monkeypatch.setattr(
        worker_runner.queue_service,
        "get_queue_job",
        lambda _db, _job_id: next(states),
    )
    monkeypatch.setattr(
        worker_runner,
        "_execute_workflow_job",
        lambda _db, _job: {"content": "late result"},
    )
    monkeypatch.setattr(
        worker_runner,
        "_sync_workflow_job",
        lambda _db, _job, **_kwargs: {"status": "cancelled"},
    )
    monkeypatch.setattr(
        worker_runner,
        "_rebind_workflow_step",
        lambda _db, _job, _result: rebound_steps.append("rebound"),
    )
    monkeypatch.setattr(
        worker_runner.queue_service,
        "complete_job",
        lambda _db, job_id, _result: completed_jobs.append(job_id),
    )

    result = worker_runner.execute_claimed_job(
        object(),
        {"id": "job-1", "task_type": "workflow.episode_script_generation"},
        auto_advance=True,
    )

    assert result["status"] == "cancelled"
    assert completed_jobs == []
    assert rebound_steps == []


def test_get_next_pending_step_reads_all_dag_steps(monkeypatch):
    """下一步选择必须读取完整 DAG，不能只读取第一行。"""
    from app.workflows import run_service

    monkeypatch.setattr(
        run_service,
        "fetch_all",
        lambda *_args, **_kwargs: [
            {
                "step_key": "first",
                "status": "completed",
                "input_payload": "{}",
                "output_payload": "{}",
            },
            {
                "step_key": "second",
                "status": "pending",
                "input_payload": '{"depends_on":["first"]}',
                "output_payload": "{}",
            },
        ],
    )

    step = run_service.get_next_pending_step(object(), "run-1")

    assert step and step["step_key"] == "second"


def test_default_skills_and_prompts_cover_workflow_steps():
    skill_keys = {item["skill_key"] for item in DEFAULT_SKILLS}
    prompt_keys = {item["prompt_key"] for item in DEFAULT_PROMPTS}

    for required_skill in (
        "script_requirement_analysis",
        "episode_script_writing",
        "novel_to_script_adaptation",
        "character_extraction",
        "scene_extraction",
        "prop_extraction",
        "storyboard_generation",
        "frame_prompt_generation",
        "video_prompt_generation",
        "voice_profile_generation",
        "music_bible_generation",
        "creative_quality_review",
    ):
        assert required_skill in skill_keys

    assert "script.episode.write" in prompt_keys
    assert "audio.voice_profile" in prompt_keys
    assert "qa.creative_review" in prompt_keys


def test_agent_runtime_steps_are_explicit():
    assert {
        "requirement_analysis",
        "drama_bible_generation",
        "adaptation_plan_generation",
        "creative_quality_review",
        "character_extraction",
        "scene_extraction",
        "prop_extraction",
        "storyboard_generation",
    }.issubset(AGENT_RUNTIME_STEPS)


def test_agent_output_applier_steps_are_explicit():
    assert {
        "requirement_analysis",
        "drama_bible_generation",
        "adaptation_plan_generation",
        "creative_quality_review",
        "character_extraction",
        "scene_extraction",
        "prop_extraction",
        "storyboard_generation",
    }.issubset(OUTPUT_APPLIER_STEPS)


def test_agent_output_applier_normalizes_model_payloads():
    assert normalize_agent_payload({"parsed_output": {"score": 90}}) == {"score": 90}
    assert normalize_agent_payload({"parsed_output": ["a", "b"]}) == {"items": ["a", "b"]}
    assert normalize_agent_payload({"raw_output": "not-json", "parse_error": "bad json"}) == {
        "raw_output": "not-json",
        "parse_error": "bad json",
    }


def test_vector_memory_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("LMD_VECTOR_MEMORY_BACKEND", raising=False)

    settings = vector_memory_settings({"memory": {"vector": {"backend": "disabled"}}})

    assert settings["backend"] == "disabled"
    assert is_vector_memory_enabled({"memory": {"vector": {"backend": "disabled"}}}) is False


def test_vector_memory_can_be_enabled_by_environment(monkeypatch):
    monkeypatch.setenv("LMD_VECTOR_MEMORY_BACKEND", "qdrant")
    monkeypatch.setenv("LMD_VECTOR_MEMORY_COLLECTION", "drama_memory_test")

    settings = vector_memory_settings({})

    assert settings["backend"] == "qdrant"
    assert settings["collection"] == "drama_memory_test"


def test_vector_memory_builds_embedding_document_from_memory_item():
    document = build_memory_document(
        {
            "title": "女主身份伏笔",
            "summary": "她小时候见过反派",
            "content": "第三集揭示项链来源。",
            "keywords": ["伏笔", "项链"],
        }
    )

    assert "女主身份伏笔" in document
    assert "第三集揭示项链来源" in document
    assert "伏笔" in document


def test_agent_runtime_builds_prompt_variables_from_context():
    variables = build_prompt_variables(
        {"id": "run-1", "user_request": "写一部都市逆袭短剧", "input_payload": {"genre": "都市爽剧"}},
        {"id": 10, "step_key": "creative_quality_review", "skill_key": "creative_quality_review"},
        {
            "content": {
                "drama": {"title": "归来", "genre": "都市逆袭", "metadata": {"visual_tone": "写实"}},
                "episode": {"script_content": "第一场：主角归来。"},
                "characters": [{"name": "顾凌霄"}],
                "memory_items": [{"summary": "主角三年前被陷害"}],
            }
        },
    )

    assert variables["user_request"] == "写一部都市逆袭短剧"
    assert variables["genre"] == "都市逆袭"
    assert "第一场" in variables["script_content"]
    assert "顾凌霄" in variables["characters"]


def test_ai_client_records_prompt_run_only_when_metadata_present(monkeypatch):
    from app.prompts import registry_service
    from app.services.aiClient import _record_text_prompt_run

    calls = []
    monkeypatch.setattr(registry_service, "record_prompt_run", lambda db, payload: calls.append(payload))

    _record_text_prompt_run(
        object(),
        {},
        model="test-model",
        system_prompt="系统",
        user_prompt="用户",
        status="completed",
        raw_output="结果",
        latency_ms=12,
    )
    assert calls == []

    _record_text_prompt_run(
        object(),
        {"prompt_key": "story.write", "skill_key": "original_script"},
        model="test-model",
        system_prompt="系统",
        user_prompt="用户",
        status="completed",
        raw_output="结果",
        latency_ms=12,
    )
    assert calls[0]["prompt_key"] == "story.write"
    assert calls[0]["skill_key"] == "original_script"
    assert "[system]" in calls[0]["final_prompt"]
