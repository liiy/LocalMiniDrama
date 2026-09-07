"""单元测试：验证迭代 4 持久化任务队列与工作流 DAG 状态机。"""
from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import text

from app.tasks.queue_service import (
    queue_summary,
    stale_cutoff_iso,
)
from app.workflows.graph import (
    attach_linear_dependencies,
    detect_cycles,
    runnable_steps,
    step_dependencies,
    workflow_progress,
)
from app.workflows.queue_bridge import QUEUEABLE_STEP_KEYS, should_enqueue_step


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


def test_queue_list_api_returns_pagination_and_full_summary(unit_client, db_session):
    """验证任务中心列表返回分页总数，状态筛选不影响完整状态汇总。"""
    from app.tasks import queue_service

    pending = queue_service.enqueue_job(
        db_session,
        {"queue_name": "entities", "task_type": "legacy.character.prompt", "payload": {"character_id": 1}},
        create_async_task=False,
    )
    failed = queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "entities",
            "task_type": "legacy.character.prompt",
            "payload": {"character_id": 2},
            "status": "failed",
        },
        create_async_task=False,
    )
    db_session.commit()

    response = unit_client.get(
        "/api/v1/platform/queue/jobs",
        params={"queue_name": "entities", "status": "pending", "limit": 1, "offset": 0},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert [item["id"] for item in data["items"]] == [pending["id"]]
    assert data["summary"]["total"] == 2
    assert data["summary"]["pending"] == 1
    assert data["summary"]["failed"] == 1

    detail = unit_client.get(f"/api/v1/platform/queue/jobs/{failed['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["payload"]["character_id"] == 2

    metrics = unit_client.get(
        "/api/v1/platform/queue/metrics",
        params={"hours": 24, "queue_name": "entities"},
    )
    assert metrics.status_code == 200
    metric_data = metrics.json()["data"]
    assert metric_data["throughput"] == 1
    assert metric_data["failed"] == 1
    assert metric_data["active_count"] == 1
    assert metric_data["failure_hotspots"][0]["task_type"] == "legacy.character.prompt"


def test_queue_metrics_uses_execution_time_and_exact_active_count(db_session):
    """验证执行耗时从认领到完成计算，活动任务数量不受终态样本上限影响。"""
    from datetime import datetime, timedelta, timezone

    from app.tasks import queue_service

    completed = queue_service.enqueue_job(
        db_session,
        {"queue_name": "videos", "task_type": "legacy.video.generate", "payload": {}},
        create_async_task=False,
    )
    queue_service.enqueue_job(
        db_session,
        {"queue_name": "videos", "task_type": "legacy.video.resume_poll", "payload": {}},
        create_async_task=False,
    )
    now = datetime.now(timezone.utc)
    locked_at = now - timedelta(seconds=75)
    completed_at = now - timedelta(seconds=15)
    db_session.execute(
        text(
            "UPDATE queue_jobs SET status = 'completed', locked_at = :locked_at, "
            "completed_at = :completed_at, updated_at = :completed_at WHERE id = :id"
        ),
        {
            "id": completed["id"],
            "locked_at": locked_at.isoformat().replace("+00:00", "Z"),
            "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        },
    )
    db_session.commit()

    result = queue_service.queue_metrics(db_session, hours=24, queue_name="videos", sample_limit=100)
    assert result["throughput"] == 1
    assert result["success_rate"] == 100.0
    assert result["avg_duration_seconds"] == 60.0
    assert result["p95_duration_seconds"] == 60.0
    assert result["active_count"] == 1
    assert result["oldest_active_seconds"] >= 0


def test_queue_bridge_queueable_steps():
    """验证长耗时生成步骤可入队判断。"""
    assert {"voice_profile_generation", "music_bible_generation"} <= QUEUEABLE_STEP_KEYS
    assert should_enqueue_step({"queue": True}, "voice_profile_generation") is True
    assert should_enqueue_step({"execution_mode": "queued"}, "music_bible_generation") is True
    assert should_enqueue_step({"queue": False}, "voice_profile_generation") is False


def test_dramatiq_claim_by_id_is_idempotent(db_session):
    """验证 Redis 重复消息只能成功认领一次，不会重复执行同一任务。"""
    from app.tasks import queue_service

    job = queue_service.enqueue_job(db_session, {"task_type": "workflow.requirement_analysis"})
    first = queue_service.claim_job_by_id(db_session, job["id"], worker_id="dramatiq-test")
    second = queue_service.claim_job_by_id(db_session, job["id"], worker_id="dramatiq-test-duplicate")
    assert first["status"] == "processing"
    assert second is None


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
    # 分发测试只验证路由，不在后台线程中执行真实第三方 Provider。
    with patch("app.tasks.dramatiq_worker.threading.Thread.start"):
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

    # 成功场景必须显式模拟真实 Provider 返回，避免测试依赖生产代码伪造媒体地址。
    with patch(
        "app.services.imageClient.call_image_api",
        return_value={"status": "completed", "image_url": "/static/test/generated.png"},
    ):
        exec_result = worker_runner.execute_claimed_job(db_session, claimed_job)
    assert exec_result["status"] == "completed"
    assert exec_result["job"]["status"] == "completed"


def test_media_worker_failure_never_returns_mock_success(db_session):
    """验证 Provider 异常进入队列失败状态，且不会产生假媒体 URL。"""
    from app.tasks import queue_service, worker_runner

    job = queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "images",
            "task_type": "image.generate",
            "max_attempts": 1,
            "payload": {"prompt": "故障测试图片"},
        },
    )
    claimed = queue_service.claim_next_job(db_session, worker_id="failure-test", queue_name="images")
    assert claimed and claimed["id"] == job["id"]
    # 与正式 Runner 一致：认领后先提交，Provider 失败回滚不能删除队列任务本身。
    db_session.commit()

    with patch("app.services.imageClient.call_image_api", side_effect=RuntimeError("Provider unavailable")):
        result = worker_runner.execute_claimed_job(db_session, claimed)

    assert result["status"] == "failed"
    assert result["job"]["status"] == "failed"
    assert "Provider unavailable" in result["job"]["error"]
    assert "/static/mock/" not in str(result)


def test_main_generation_entries_enqueue_durable_jobs(db_session):
    """验证剧本、图片和视频入口只写持久化队列，并复用同一个 async_task。"""
    from app.core.logger import get_logger
    from app.platform_common import now_iso
    from app.services import (
        backgroundExtractionService,
        characterGenerationService,
        generationService,
        imageService,
        episodeStoryboardService,
        framePromptService,
        propExtractionService,
        propImageGenerationService,
        videoService,
    )
    from app.services import imageClient
    from app.tasks import queue_service

    now = now_iso()
    drama_result = db_session.execute(
        text(
            "INSERT INTO dramas (title, status, created_at, updated_at) "
            "VALUES ('队列迁移测试', 'draft', :now, :now)"
        ),
        {"now": now},
    )
    drama_id = int(drama_result.lastrowid)
    episode_result = db_session.execute(
        text(
            "INSERT INTO episodes (drama_id, episode_number, title, script_content, created_at, updated_at) "
            "VALUES (:drama_id, 1, '第一集', '编剧在雨夜电影院发现神秘胶片。', :now, :now)"
        ),
        {"drama_id": drama_id, "now": now},
    )
    episode_id = int(episode_result.lastrowid)
    storyboard_result = db_session.execute(
        text(
            "INSERT INTO storyboards (episode_id, storyboard_number, title, description, status, created_at, updated_at) "
            "VALUES (:episode_id, 1, '镜头一', '电影院外景', 'draft', :now, :now)"
        ),
        {"episode_id": episode_id, "now": now},
    )
    storyboard_id = int(storyboard_result.lastrowid)
    prop_result = db_session.execute(
        text(
            "INSERT INTO props (drama_id, episode_id, name, prompt, created_at, updated_at) "
            "VALUES (:drama_id, :episode_id, '神秘胶片', '老式电影胶片特写', :now, :now)"
        ),
        {"drama_id": drama_id, "episode_id": episode_id, "now": now},
    )
    prop_id = int(prop_result.lastrowid)
    log = get_logger("lmd.test.queueMigration")

    story_task_id = generationService.start_story_generation(
        db_session,
        log,
        {"drama_id": drama_id, "premise": "一名编剧发现自己写下的事件会成真"},
    )
    image_result = imageService.create_generation(
        db_session,
        log,
        {"drama_id": drama_id, "prompt": "雨夜中的老式电影院正门"},
    )
    video_result = videoService.create_video(
        db_session,
        log,
        {
            "drama_id": drama_id,
            "prompt": "镜头缓慢推近电影院入口",
            # 提供尾帧可跳过分镜角色引用查询，使测试聚焦队列入口。
            "last_frame_url": "/static/test/end-frame.png",
        },
    )
    character_task_id = characterGenerationService.generate_characters(
        db_session,
        None,
        log,
        {"drama_id": drama_id, "episode_id": episode_id},
    )
    scene_task_id = backgroundExtractionService.extract_backgrounds_for_episode(
        db_session,
        {},
        log,
        episode_id,
        language="zh",
    )
    prop_task_id = propExtractionService.extract_props_for_episode(
        db_session,
        log,
        episode_id,
        {},
    )
    storyboard_generation = episodeStoryboardService.generate_storyboard(
        db_session,
        log,
        episode_id,
        storyboard_count=4,
        video_duration=20,
        include_narration=True,
    )
    frame_prompt_task_id = framePromptService.generate_frame_prompt(
        db_session,
        log,
        storyboard_id,
        "panel",
        panel_count=3,
    )
    prop_image_task_id = propImageGenerationService.generate_prop_image(
        db_session,
        log,
        prop_id,
        {"style": "写实电影感"},
    )
    asset_image_result = imageClient.create_and_generate_image(
        db_session,
        log,
        {"drama_id": drama_id, "prompt": "电影院雨夜外景", "size": "1024x1024"},
    )

    jobs = queue_service.list_queue_jobs(db_session, limit=20)
    jobs_by_type = {job["task_type"]: job for job in jobs}
    expected = {
        "legacy.story.generate": story_task_id,
        "legacy.character.extract": character_task_id,
        "legacy.scene.extract": scene_task_id,
        "legacy.prop.extract": prop_task_id,
        "legacy.storyboard.generate": storyboard_generation["task_id"],
        "legacy.frame_prompt.generate": frame_prompt_task_id,
        "legacy.prop_image.generate": prop_image_task_id,
        "legacy.asset_image.generate": asset_image_result["task_id"],
        "legacy.image.generate": image_result["task_id"],
        "legacy.video.generate": video_result["task_id"],
    }
    for task_type, async_task_id in expected.items():
        job = jobs_by_type[task_type]
        assert job["status"] == "pending"
        assert job["async_task_id"] == async_task_id


def test_legacy_entity_workers_dispatch_registered_handlers(db_session):
    """验证角色、场景、道具任务分别分发到已注册处理器，并同步真实任务结果。"""
    from app.core.logger import get_logger
    from app.services import taskService
    from app.tasks import queue_service, worker_runner

    cases = [
        (
            "legacy.character.extract",
            {"request": {"drama_id": 1}},
            "app.services.characterGenerationService.process_character_generation",
        ),
        (
            "legacy.scene.extract",
            {"episode_id": 1, "language": "zh"},
            "app.services.backgroundExtractionService.process_background_extraction",
        ),
        (
            "legacy.prop.extract",
            {"episode_id": 1},
            "app.services.propExtractionService.process_prop_extraction",
        ),
        (
            "legacy.storyboard.generate",
            {"episode_id": 1, "storyboard_count": 4},
            "app.services.episodeStoryboardService.generate_storyboard",
        ),
        (
            "legacy.frame_prompt.generate",
            {"storyboard_id": 1, "frame_type": "panel", "panel_count": 3},
            "app.services.framePromptService.process_frame_prompt_generation",
        ),
        (
            "legacy.prop_image.generate",
            {"prop_id": 1, "options": {}},
            "app.services.propImageGenerationService.process_prop_image_generation",
        ),
        (
            "legacy.asset_image.generate",
            {"image_generation_id": 1, "options": {"drama_id": 1}},
            "app.services.imageClient.run_image_generation",
        ),
    ]

    for task_type, payload, processor_path in cases:
        task = taskService.create_task(db_session, get_logger("lmd.test.entityQueue"), task_type, "1")
        job = queue_service.enqueue_job(
            db_session,
            {
                "queue_name": "entities",
                "task_type": task_type,
                "async_task_id": task["id"],
                "payload": payload,
            },
            create_async_task=False,
        )
        claimed = queue_service.claim_next_job(
            db_session,
            worker_id=f"entity-test-{task_type}",
            queue_name="entities",
        )
        db_session.commit()

        def complete_task(*_args, task_id=task["id"], **_kwargs):
            taskService.update_task_result(db_session, task_id, {"handler": task_type})
            db_session.commit()

        with patch(processor_path, side_effect=complete_task) as processor:
            result = worker_runner.execute_claimed_job(db_session, claimed)

        assert processor.call_count == 1
        assert result["status"] == "completed"
        assert result["executor_result"]["handler"] == task_type
        assert queue_service.get_queue_job(db_session, job["id"])["status"] == "completed"


def test_auxiliary_entity_workers_do_not_require_async_tasks(db_session):
    """验证实体辅助任务直接由 queue_jobs 追踪，并严格分发到白名单服务。"""
    from app.tasks import queue_service, worker_runner

    cases = [
        (
            "legacy.character.prompt",
            {"character_id": 11},
            "app.services.characterLibraryService.generate_character_prompt_only",
        ),
        (
            "legacy.scene.prompt",
            {"scene_id": 12},
            "app.services.sceneService.generate_scene_prompt_only",
        ),
        (
            "legacy.prop.prompt",
            {"prop_id": 13},
            "app.services.propEntityService.generate_prop_prompt_only",
        ),
        (
            "legacy.character.four_view",
            {"character_id": 14, "model": "test-model", "style": "电影感"},
            "app.services.characterLibraryService.generate_character_four_view_image",
        ),
    ]

    for task_type, payload, processor_path in cases:
        job = queue_service.enqueue_job(
            db_session,
            {
                "queue_name": "images" if task_type.endswith("four_view") else "entities",
                "task_type": task_type,
                "payload": payload,
            },
            create_async_task=False,
        )
        claimed = queue_service.claim_next_job(
            db_session,
            worker_id=f"auxiliary-test-{task_type}",
            queue_name=job["queue_name"],
        )
        db_session.commit()

        with patch(processor_path, return_value={"ok": True, "handler": task_type}) as processor:
            result = worker_runner.execute_claimed_job(db_session, claimed)

        assert processor.call_count == 1
        assert result["status"] == "completed"
        assert result["executor_result"]["handler"] == task_type
        assert queue_service.get_queue_job(db_session, job["id"])["status"] == "completed"


def test_auxiliary_worker_converts_false_result_to_queue_failure(db_session):
    """验证旧服务返回 ok:false 时不会误报完成，而是进入队列失败终态。"""
    from app.tasks import queue_service, worker_runner

    job = queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "entities",
            "task_type": "legacy.prop.prompt",
            "payload": {"prop_id": 99},
            "max_attempts": 1,
        },
        create_async_task=False,
    )
    claimed = queue_service.claim_next_job(
        db_session,
        worker_id="auxiliary-failure-test",
        queue_name="entities",
    )
    db_session.commit()

    with patch(
        "app.services.propEntityService.generate_prop_prompt_only",
        return_value={"ok": False, "error": "AI返回内容为空"},
    ):
        result = worker_runner.execute_claimed_job(db_session, claimed)

    assert result["status"] == "failed"
    assert "AI返回内容为空" in result["error"]
    assert queue_service.get_queue_job(db_session, job["id"])["status"] == "failed"


def test_batch_character_four_view_enqueues_secret_free_jobs(db_session):
    """验证批量四视图按角色拆分持久化任务，且 payload 不包含运行时配置。"""
    from app.core.logger import get_logger
    from app.services import characterLibraryService
    from app.tasks import queue_service

    result = characterLibraryService.batch_generate_character_images(
        db_session,
        get_logger("lmd.test.characterFourViewQueue"),
        {"ai": {"api_key": "must-not-persist"}},
        [21, 22],
        "test-model",
        "电影感",
    )

    assert result["ok"] is True
    assert len(result["queue_job_ids"]) == 2
    jobs = queue_service.list_queue_jobs(db_session, task_type="legacy.character.four_view", limit=10)
    assert {job["payload"]["character_id"] for job in jobs} == {"21", "22"}
    assert all("api_key" not in str(job["payload"]) for job in jobs)


def test_video_resume_poll_reuses_active_queue_job(db_session):
    """验证重复恢复同一视频时复用活动队列任务，避免并发轮询厂商接口。"""
    from app.core.logger import get_logger
    from app.platform_common import now_iso
    from app.services import videoService
    from app.tasks import queue_service

    now = now_iso()
    inserted = db_session.execute(
        text(
            "INSERT INTO video_generations "
            "(status, provider_task_id, created_at, updated_at) "
            "VALUES ('processing', 'provider-task-1', :now, :now)"
        ),
        {"now": now},
    )
    video_id = int(inserted.lastrowid)

    first = videoService.resume_failed_video_poll(
        db_session,
        get_logger("lmd.test.videoResumeQueue"),
        video_id,
    )
    second = videoService.resume_failed_video_poll(
        db_session,
        get_logger("lmd.test.videoResumeQueue"),
        video_id,
    )

    assert first["item"]["queue_job_id"] == second["item"]["queue_job_id"]
    jobs = queue_service.list_queue_jobs(
        db_session,
        queue_name="videos",
        task_type="legacy.video.resume_poll",
        limit=10,
    )
    assert len(jobs) == 1
    assert jobs[0]["async_task_id"] is None
    assert jobs[0]["max_attempts"] == 1


def test_video_resume_worker_propagates_poll_failure(db_session):
    """验证视频轮询业务失败会同步为 queue job 失败，而不是误标 completed。"""
    from app.tasks import queue_service, worker_runner

    job = queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "videos",
            "task_type": "legacy.video.resume_poll",
            "payload": {"video_generation_id": 31},
            "max_attempts": 1,
        },
        create_async_task=False,
    )
    claimed = queue_service.claim_next_job(
        db_session,
        worker_id="video-resume-failure-test",
        queue_name="videos",
    )
    db_session.commit()

    with patch(
        "app.services.videoService.resume_poll_for_video_generation",
        return_value={"ok": False, "error": "厂商任务失败"},
    ):
        result = worker_runner.execute_claimed_job(db_session, claimed)

    assert result["status"] == "failed"
    assert "厂商任务失败" in result["error"]
    assert queue_service.get_queue_job(db_session, job["id"])["status"] == "failed"


def test_story_generation_preserves_workflow_control_context(db_session):
    """验证剧本落库不会覆盖审核标记和队列关联，并为下游绑定首集上下文。"""
    from contextlib import contextmanager

    from app.core.logger import get_logger
    from app.platform_common import now_iso
    from app.services import generationService, taskService
    from app.workflows import run_service

    now = now_iso()
    drama_result = db_session.execute(
        text(
            "INSERT INTO dramas (title, status, created_at, updated_at) "
            "VALUES ('工作流上下文测试', 'draft', :now, :now)"
        ),
        {"now": now},
    )
    drama_id = int(drama_result.lastrowid)
    workflow = run_service.create_workflow_run(
        db_session,
        {
            "type": "original_script",
            "drama_id": drama_id,
            "user_request": "悬疑短剧",
            "state": {"creative_goal": "每集结尾设置反转"},
        },
    )
    step = run_service.get_workflow_step(db_session, workflow["id"], "episode_script_generation")
    run_service.update_workflow_step(
        db_session,
        workflow["id"],
        "episode_script_generation",
        {"output_payload": {"queue_job_id": "outer-workflow-job", "agent_run_id": 9}},
    )
    task = taskService.create_task(
        db_session,
        get_logger("lmd.test.storyWorkflowContext"),
        "story_generation",
        str(drama_id),
    )
    db_session.commit()

    @contextmanager
    def same_session_scope():
        yield db_session
        db_session.commit()

    with patch.object(generationService, "session_scope", same_session_scope), patch.object(
        generationService,
        "generate_story",
        return_value={"episodes": [{"episode": 1, "title": "雨夜来客", "content": "门铃响了三次。"}]},
    ):
        generationService.process_story_generation(
            task["id"],
            {
                "drama_id": drama_id,
                "workflow_run_id": workflow["id"],
                "premise": "雨夜来客",
            },
        )

    updated_run = run_service.get_workflow_run(db_session, workflow["id"], include_steps=False)
    updated_step = run_service.get_workflow_step(db_session, workflow["id"], "episode_script_generation")
    assert updated_run["episode_id"] is not None
    assert updated_run["state"]["creative_goal"] == "每集结尾设置反转"
    assert updated_step["input_payload"]["requires_approval"] is True
    assert updated_step["input_payload"]["depends_on"] == step["input_payload"]["depends_on"]
    assert updated_step["output_payload"]["queue_job_id"] == "outer-workflow-job"
    assert updated_step["output_payload"]["agent_run_id"] == 9


def test_legacy_worker_propagates_async_task_failure(db_session):
    """验证旧业务处理器内部失败时，外层持久化任务不会被误标记为成功。"""
    from app.core.logger import get_logger
    from app.services import taskService
    from app.tasks import queue_service, worker_runner

    task = taskService.create_task(db_session, get_logger("lmd.test.legacyQueue"), "story_generation", "1")
    job = queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "stories",
            "task_type": "legacy.story.generate",
            "async_task_id": task["id"],
            "max_attempts": 1,
            "payload": {"request": {"drama_id": 1}},
        },
        create_async_task=False,
    )
    claimed = queue_service.claim_next_job(db_session, worker_id="legacy-failure-test", queue_name="stories")
    db_session.commit()

    def mark_story_failed(task_id, _request):
        taskService.update_task_error(db_session, task_id, "剧本模型调用失败")
        db_session.commit()

    with patch(
        "app.services.generationService.process_story_generation",
        side_effect=mark_story_failed,
    ):
        result = worker_runner.execute_claimed_job(db_session, claimed)

    assert result["status"] == "failed"
    assert "剧本模型调用失败" in result["error"]
    assert queue_service.get_queue_job(db_session, job["id"])["status"] == "failed"


def test_legacy_worker_rejects_unregistered_handler(db_session):
    """验证 legacy 前缀不能绕过显式处理器白名单。"""
    from app.tasks import queue_service, worker_runner

    queue_service.enqueue_job(
        db_session,
        {
            "queue_name": "stories",
            "task_type": "legacy.unknown.execute",
            "max_attempts": 1,
            "payload": {},
        },
    )
    claimed = queue_service.claim_next_job(db_session, worker_id="legacy-whitelist-test")
    db_session.commit()
    result = worker_runner.execute_claimed_job(db_session, claimed)

    assert result["status"] == "failed"
    assert "未注册的兼容队列任务类型" in result["error"]


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

    job_stream_res = unit_client.get(
        f"/api/v1/platform/queue/jobs/{job_id}/stream?interval=0.2&max_duration=1"
    )
    assert job_stream_res.status_code == 200
    assert "text/event-stream" in job_stream_res.headers.get("content-type", "")
    job_content = job_stream_res.text
    assert "job_update" in job_content or "job_finished" in job_content

