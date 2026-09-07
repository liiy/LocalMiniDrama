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
    "legacy.",
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
        elif task_type.startswith("legacy."):
            result = _execute_legacy_job(db, job)
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
    raise ValueError(f"未注册的媒体队列任务类型: {task_type}")


def _task_result_or_raise(db: Session, async_task_id: str) -> dict[str, Any]:
    """读取兼容 async_task 的真实终态，阻止内部失败被外层队列误判为成功。"""
    from app.platform_common import json_loads
    from app.services import taskService

    task = taskService.get_task(db, async_task_id)
    if not task:
        raise ValueError(f"关联异步任务不存在: {async_task_id}")
    if task.get("status") != "completed":
        error = task.get("error") or task.get("message") or f"异步任务状态异常: {task.get('status')}"
        raise RuntimeError(str(error))
    return json_loads(task.get("result"), {})


def _execute_legacy_job(db: Session, job: dict[str, Any]) -> dict[str, Any]:
    """执行从进程内线程池迁移来的显式白名单业务处理器。"""
    task_type = str(job.get("task_type") or "")
    payload = job.get("payload") or {}
    # 实体预处理任务不创建旧 async_task，执行结果直接由 queue_jobs 追踪。
    auxiliary_result = _execute_auxiliary_legacy_job(db, task_type, payload)
    if auxiliary_result is not None:
        return auxiliary_result

    async_task_id = str(job.get("async_task_id") or "")
    if not async_task_id:
        raise ValueError("兼容队列任务缺少 async_task_id")

    if task_type == "legacy.story.generate":    
        from app.services import generationService

        # 旧处理器自建 Session；先结束当前读取事务，确保执行后能读到最新终态。
        db.commit()
        generationService.process_story_generation(async_task_id, payload.get("request") or {})
    elif task_type == "legacy.character.extract":
        from app.services import characterGenerationService

        db.commit()
        characterGenerationService.process_character_generation(
            async_task_id,
            payload.get("request") or {},
        )
    elif task_type == "legacy.scene.extract":
        from app.core.config import load_config
        from app.services import backgroundExtractionService

        episode_id = payload.get("episode_id")
        if not episode_id:
            raise ValueError("场景提取队列任务缺少 episode_id")
        db.commit()
        backgroundExtractionService.process_background_extraction(
            async_task_id,
            episode_id,
            model=payload.get("model"),
            style=payload.get("style"),
            language=payload.get("language"),
            cfg=load_config(),
        )
    elif task_type == "legacy.prop.extract":
        from app.core.config import load_config
        from app.services import propExtractionService

        episode_id = payload.get("episode_id")
        if not episode_id:
            raise ValueError("道具提取队列任务缺少 episode_id")
        db.commit()
        propExtractionService.process_prop_extraction(
            async_task_id,
            episode_id,
            load_config(),
        )
    elif task_type == "legacy.storyboard.generate":
        from app.services import episodeStoryboardService

        episode_id = payload.get("episode_id")
        if not episode_id:
            raise ValueError("分镜生成队列任务缺少 episode_id")
        episodeStoryboardService.generate_storyboard(
            db,
            episodeStoryboardService.log,
            episode_id,
            model=payload.get("model"),
            style=payload.get("style"),
            storyboard_count=payload.get("storyboard_count"),
            video_duration=payload.get("video_duration"),
            aspect_ratio=payload.get("aspect_ratio"),
            include_narration=payload.get("include_narration"),
            universal_omni=payload.get("universal_omni"),
            _existing_task_id=async_task_id,
        )
    elif task_type == "legacy.frame_prompt.generate":
        from app.services import framePromptService

        storyboard_id = payload.get("storyboard_id")
        if not storyboard_id:
            raise ValueError("帧提示词队列任务缺少 storyboard_id")
        db.commit()
        framePromptService.process_frame_prompt_generation(
            async_task_id,
            int(storyboard_id),
            str(payload.get("frame_type") or "panel"),
            int(payload.get("panel_count") or 0),
            payload.get("model"),
        )
    elif task_type == "legacy.prop_image.generate":
        from app.services import propImageGenerationService

        prop_id = payload.get("prop_id")
        if not prop_id:
            raise ValueError("道具图片队列任务缺少 prop_id")
        db.commit()
        propImageGenerationService.process_prop_image_generation(
            async_task_id,
            int(prop_id),
            payload.get("options") or {},
        )
    elif task_type == "legacy.asset_image.generate":
        from app.core.config import load_config
        from app.core.logger import get_logger
        from app.services import imageClient

        image_generation_id = payload.get("image_generation_id")
        if not image_generation_id:
            raise ValueError("资产图片队列任务缺少 image_generation_id")
        imageClient.run_image_generation(
            db,
            get_logger("lmd.assetImageQueue"),
            int(image_generation_id),
            payload.get("options") or {},
            load_config(),
        )
    elif task_type == "legacy.image.generate":
        from app.core.logger import get_logger
        from app.services import imageService

        image_generation_id = payload.get("image_generation_id")
        if not image_generation_id:
            raise ValueError("图片队列任务缺少 image_generation_id")
        imageService.process_image_generation(
            db,
            get_logger("lmd.imageQueue"),
            image_generation_id,
        )
    elif task_type == "legacy.video.generate":
        from app.services import videoService

        video_generation_id = payload.get("video_generation_id")
        if not video_generation_id:
            raise ValueError("视频队列任务缺少 video_generation_id")
        db.commit()
        videoService.process_video_generation(video_generation_id)
    else:
        raise ValueError(f"未注册的兼容队列任务类型: {task_type}")

    return _task_result_or_raise(db, async_task_id)


def _require_ok(result: dict[str, Any] | None, operation: str) -> dict[str, Any]:
    """把旧服务的 ok:false 结果转换为异常，让队列进入重试或失败状态。"""
    if not isinstance(result, dict) or not result.get("ok"):
        error = result.get("error") if isinstance(result, dict) else None
        raise RuntimeError(str(error or f"{operation}失败"))
    return result


def _execute_auxiliary_legacy_job(
    db: Session,
    task_type: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """执行无需 async_task 的实体辅助任务；未知类型返回 None 交给旧任务分发器。"""
    from app.core.config import load_config

    if task_type == "legacy.character.enrich":
        from sqlalchemy import text

        from app.core.logger import get_logger
        from app.services import characterGenerationService

        character_id = payload.get("character_id")
        if not character_id:
            raise ValueError("角色锚点任务缺少 character_id")
        row = db.execute(
            text("SELECT appearance FROM characters WHERE id = :id AND deleted_at IS NULL"),
            {"id": int(character_id)},
        ).mappings().first()
        if not row:
            raise ValueError("角色不存在")
        return characterGenerationService.enrich_identity_anchors(
            db,
            get_logger("lmd.characterAnchorQueue"),
            int(character_id),
            row.get("appearance"),
        )
    if task_type == "legacy.character.prompt":
        from app.core.logger import get_logger
        from app.services import characterLibraryService

        character_id = payload.get("character_id")
        if not character_id:
            raise ValueError("角色提示词任务缺少 character_id")
        result = characterLibraryService.generate_character_prompt_only(
            db,
            get_logger("lmd.characterPromptQueue"),
            load_config(),
            character_id,
            payload.get("model"),
            payload.get("style"),
        )
        return _require_ok(result, "角色提示词生成")
    if task_type == "legacy.scene.prompt":
        from app.core.logger import get_logger
        from app.services import sceneService

        scene_id = payload.get("scene_id")
        if not scene_id:
            raise ValueError("场景提示词任务缺少 scene_id")
        result = sceneService.generate_scene_prompt_only(
            db,
            get_logger("lmd.scenePromptQueue"),
            load_config(),
            scene_id,
            payload.get("model"),
            payload.get("style"),
        )
        return _require_ok(result, "场景提示词生成")
    if task_type == "legacy.prop.prompt":
        from app.core.logger import get_logger
        from app.services import propEntityService

        prop_id = payload.get("prop_id")
        if not prop_id:
            raise ValueError("道具提示词任务缺少 prop_id")
        result = propEntityService.generate_prop_prompt_only(
            db,
            get_logger("lmd.propPromptQueue"),
            load_config(),
            prop_id,
            payload.get("model"),
            payload.get("style"),
        )
        return _require_ok(result, "道具提示词生成")
    if task_type == "legacy.character.four_view":
        from app.core.logger import get_logger
        from app.services import characterLibraryService

        character_id = payload.get("character_id")
        if not character_id:
            raise ValueError("角色四视图任务缺少 character_id")
        result = characterLibraryService.generate_character_four_view_image(
            db,
            get_logger("lmd.characterFourViewQueue"),
            load_config(),
            character_id,
            payload.get("model"),
            payload.get("style"),
        )
        return _require_ok(result, "角色四视图生成")
    if task_type == "legacy.video.resume_poll":
        from app.core.logger import get_logger
        from app.services import videoService

        video_generation_id = payload.get("video_generation_id")
        if not video_generation_id:
            raise ValueError("视频恢复轮询任务缺少 video_generation_id")
        result = videoService.resume_poll_for_video_generation(
            db,
            get_logger("lmd.videoResumeQueue"),
            video_generation_id,
        )
        return _require_ok(result, "视频恢复轮询")
    return None


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
