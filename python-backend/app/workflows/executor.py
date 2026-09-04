"""工作流执行器。

当前是最小可用执行器：负责推进步骤、构建上下文快照、记录 Agent Run。
外部 AI 调用默认关闭，只有显式 execute_ai=true 时才调用现有生成服务，降低误触发成本。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents import output_applier
from app.agents import runtime as agent_runtime
from app.context import builder as context_builder
from app.core.logger import get_logger
from app.platform_common import now_iso
from app.skills import registry_service as skill_registry
from app.workflows import queue_bridge
from app.workflows import run_service


AI_BACKED_STEPS = {
    "episode_script_generation",
    "character_extraction",
    "scene_extraction",
    "prop_extraction",
    "storyboard_generation",
    "frame_prompt_generation",
    "video_prompt_generation",
    "voice_music_generation",
}


def execute_next_step(db: Session, log, workflow_run_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行下一个 pending/retry 步骤。"""
    step = _select_next_step_or_control(db, workflow_run_id)
    if not step:
        run = run_service.update_workflow_run(db, workflow_run_id, {"status": "completed", "completed_at": now_iso()})
        return {"status": "completed", "message": "没有待执行步骤", "workflow": run}
    return _dispatch_selected_step(db, log, workflow_run_id, step, options or {})


def _select_next_step_or_control(db: Session, workflow_run_id: str) -> dict[str, Any] | None:
    """选择下一个可运行节点；无可运行节点时返回控制状态。"""
    execution_state = run_service.get_workflow_execution_state(db, workflow_run_id)
    runnable = execution_state.get("runnable_steps") or []
    if runnable:
        return runnable[0]
    progress = execution_state.get("progress") or {}
    # 任务图没有 runnable 时，不能直接判完成，需要先判断是否在等异步任务或依赖。
    if progress.get("processing"):
        return {"_control_status": "processing", "message": "存在异步步骤正在执行", "execution_state": execution_state}
    if progress.get("failed"):
        run = run_service.update_workflow_run(db, workflow_run_id, {"status": "failed"})
        return {
            "_control_status": "failed",
            "message": "存在失败步骤，工作流已停止",
            "workflow": run,
            "execution_state": execution_state,
        }
    if progress.get("pending"):
        return {"_control_status": "blocked", "message": "没有满足依赖的可运行步骤", "execution_state": execution_state}
    return None


def _dispatch_selected_step(
    db: Session,
    log,
    workflow_run_id: str,
    step: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    """执行真实步骤，或返回任务图控制状态。"""
    if step.get("_control_status"):
        return {
            "status": step["_control_status"],
            "message": step.get("message"),
            "workflow": step.get("workflow"),
            "execution_state": step.get("execution_state"),
        }
    return execute_step(db, log, workflow_run_id, step["step_key"], options)


def run_until_blocked(db: Session, log, workflow_run_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """连续执行步骤，直到遇到异步 processing、失败或没有待执行步骤。

    这个函数是自动编排的最小策略：同步步骤可以连续推进；一旦某步创建了异步任务，
    工作流停在 processing，等待前端/定时器调用 sync-step 或 sync-all 后再继续。
    """
    options = options or {}
    max_steps = max(1, min(int(options.get("max_steps") or 20), 100))
    executed: list[dict[str, Any]] = []

    for _ in range(max_steps):
        result = execute_next_step(db, log, workflow_run_id, options)
        executed.append(result)
        if result.get("status") in {"queued", "waiting_child", "processing", "blocked", "failed"}:
            return {"status": result["status"], "executed_count": len(executed), "results": executed}
        if result.get("status") == "completed" and result.get("message") == "没有待执行步骤":
            return {"status": "completed", "executed_count": len(executed), "results": executed}

    # 达到保护上限时主动停下，避免一次请求占用过长时间。
    return {"status": "paused", "message": "达到单次自动推进步数上限", "executed_count": len(executed), "results": executed}


def execute_step(
    db: Session,
    log,
    workflow_run_id: str,
    step_key: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行指定步骤。

    dry-run 模式会完成步骤但不调用外部 AI，适合先联调前端流程、检查上下文和 Agent 记录。
    真实生成需要调用方显式传入 execute_ai=true。
    """
    options = options or {}
    log = log or get_logger("lmd.workflowExecutor")
    run = run_service.get_workflow_run(db, workflow_run_id, include_steps=False)
    if not run:
        raise ValueError("Workflow 不存在")
    step = run_service.get_workflow_step(db, workflow_run_id, step_key)
    if not step:
        raise ValueError("Workflow Step 不存在")

    run_service.update_workflow_run(db, workflow_run_id, {"status": "processing"})
    run_service.update_workflow_step(db, workflow_run_id, step_key, {"status": "processing"})

    context_payload = context_builder.build_context(
        db,
        drama_id=run.get("drama_id"),
        episode_id=run.get("episode_id"),
        skill_key=step.get("skill_key"),
        include_memory=True,
    )
    snapshot = context_builder.save_context_snapshot(db, context_payload, workflow_run_id)

    if queue_bridge.should_enqueue_step(options, step_key):
        # 耗时步骤可先进入持久化队列；worker 完成 queue_job 后再由 sync-step 回写 workflow。
        return queue_bridge.enqueue_workflow_step(db, run, step, snapshot, options)

    execute_ai = bool(options.get("execute_ai", False))
    if execute_ai and step_key in AI_BACKED_STEPS:
        return _execute_ai_backed_step(db, log, run, step, snapshot, options)
    if execute_ai and step_key in agent_runtime.AGENT_RUNTIME_STEPS:
        result = agent_runtime.run_text_agent(
            db,
            log,
            run=run,
            step=step,
            context_payload=context_payload,
            options={**options, "context_snapshot_id": snapshot["id"]},
        )
        apply_result = None
        try:
            # Agent Runtime 只负责产出；统一落库放在 output_applier，避免多个 Agent 分散写业务表。
            apply_result = output_applier.apply_agent_output(db, run, step, result)
        except Exception as err:  # noqa: BLE001
            # 落库失败时仍保留模型原始结果，方便人工复核或后续单独重试该步骤。
            log.warning("Agent 输出落库失败: workflow=%s step=%s error=%s", workflow_run_id, step_key, err)
            apply_result = {"status": "failed", "error": str(err)}
        updated_step = run_service.update_workflow_step(
            db,
            workflow_run_id,
            step_key,
            {
                "status": _agent_step_status(result, apply_result),
                "output_payload": {**result, "apply_result": apply_result},
            },
        )
        return {"status": updated_step.get("status"), "step": updated_step, "agent_result": result}

    # 默认 dry-run：记录一次 Agent Run，说明该步骤已经通过编排器完成联调，但未消耗模型。
    agent_run = skill_registry.create_agent_run(
        db,
        {
            "workflow_run_id": workflow_run_id,
            "workflow_step_id": str(step["id"]),
            "agent_name": step.get("agent_name") or "producer",
            "skill_key": step.get("skill_key"),
            "status": "completed",
            "input_payload": {
                "dry_run": True,
                "context_snapshot_id": snapshot["id"],
                "execute_ai": False,
            },
            "output_payload": {
                "message": "dry-run 已完成，未调用外部 AI",
                "source_refs": context_payload.get("source_refs") or [],
                "token_estimate": context_payload.get("token_estimate") or 0,
            },
        },
    )
    updated_step = run_service.update_workflow_step(
        db,
        workflow_run_id,
        step_key,
        {
            "status": "completed",
            "output_payload": {
                "dry_run": True,
                "agent_run_id": agent_run["id"],
                "context_snapshot_id": snapshot["id"],
            },
        },
    )
    return {"status": "completed", "step": updated_step, "agent_run": agent_run}


def _execute_ai_backed_step(
    db: Session,
    log,
    run: dict[str, Any],
    step: dict[str, Any],
    snapshot: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    """调用已有业务服务执行可落地的 AI 步骤。

    这里接入的是已有异步服务的“发起任务”能力。任务完成后的精细回写可以继续在
    各 process_* 函数中补充，避免一次性改动过多后台执行逻辑。
    """
    workflow_run_id = run["id"]
    step_key = step["step_key"]
    input_payload = dict(run.get("input_payload") or {})
    input_payload.update(options.get("input_payload") or {})
    input_payload["workflow_run_id"] = workflow_run_id
    input_payload["workflow_step_id"] = str(step["id"])

    if step_key == "episode_script_generation":
        if not run.get("drama_id"):
            raise ValueError("执行剧本生成需要 workflow_run 绑定 drama_id")
        from app.services import generationService

        input_payload["drama_id"] = run["drama_id"]
        input_payload.setdefault("premise", input_payload.get("core_theme") or input_payload.get("user_request") or run.get("user_request"))
        task_id = generationService.start_story_generation(db, log, input_payload)
        agent_run = skill_registry.create_agent_run(
            db,
            {
                "workflow_run_id": workflow_run_id,
                "workflow_step_id": str(step["id"]),
                "agent_name": step.get("agent_name") or "script_writer",
                "skill_key": step.get("skill_key"),
                "status": "processing",
                "input_payload": {"async_task_id": task_id, "context_snapshot_id": snapshot["id"]},
            },
        )
        run_service.update_workflow_step(
            db,
            workflow_run_id,
            step_key,
            {"status": "processing", "output_payload": {"async_task_id": task_id, "agent_run_id": agent_run["id"]}},
        )
        return {"status": "processing", "async_task_id": task_id, "agent_run": agent_run}

    if step_key == "character_extraction":
        if not run.get("drama_id"):
            raise ValueError("执行角色提取需要 workflow_run 绑定 drama_id")
        from app.services import generationService

        input_payload["drama_id"] = run["drama_id"]
        task_id = generationService.generate_characters(db, log, input_payload)
        agent_run = skill_registry.create_agent_run(
            db,
            {
                "workflow_run_id": workflow_run_id,
                "workflow_step_id": str(step["id"]),
                "agent_name": step.get("agent_name") or "character",
                "skill_key": step.get("skill_key"),
                "status": "processing",
                "input_payload": {"async_task_id": task_id, "context_snapshot_id": snapshot["id"]},
            },
        )
        run_service.update_workflow_step(
            db,
            workflow_run_id,
            step_key,
            {"status": "processing", "output_payload": {"async_task_id": task_id, "agent_run_id": agent_run["id"]}},
        )
        return {"status": "processing", "async_task_id": task_id, "agent_run": agent_run}

    if step_key == "scene_extraction":
        if not run.get("episode_id"):
            raise ValueError("执行场景提取需要 workflow_run 绑定 episode_id")
        from app.core.config import load_config
        from app.services import backgroundExtractionService

        task_id = backgroundExtractionService.extract_backgrounds_for_episode(
            db,
            load_config(),
            log,
            run["episode_id"],
            model=input_payload.get("model"),
            style=input_payload.get("style"),
            language=input_payload.get("language"),
        )
        return _mark_async_step_processing(db, workflow_run_id, step, snapshot, task_id, "scene")

    if step_key == "prop_extraction":
        if not run.get("episode_id"):
            raise ValueError("执行道具提取需要 workflow_run 绑定 episode_id")
        from app.core.config import load_config
        from app.services import propExtractionService

        task_id = propExtractionService.extract_props_for_episode(db, log, run["episode_id"], load_config())
        return _mark_async_step_processing(db, workflow_run_id, step, snapshot, task_id, "prop")

    if step_key == "storyboard_generation":
        if not run.get("episode_id"):
            raise ValueError("执行分镜生成需要 workflow_run 绑定 episode_id")
        from app.services import episodeStoryboardService

        result = episodeStoryboardService.generate_storyboard(
            db,
            log,
            run["episode_id"],
            model=input_payload.get("model"),
            style=input_payload.get("style"),
            storyboard_count=input_payload.get("storyboard_count"),
            video_duration=input_payload.get("video_duration"),
            aspect_ratio=input_payload.get("aspect_ratio"),
            include_narration=input_payload.get("include_narration"),
            universal_omni=input_payload.get("universal_omni"),
        )
        task_id = result.get("task_id") if isinstance(result, dict) else None
        return _mark_async_step_processing(db, workflow_run_id, step, snapshot, task_id, "storyboard", result)

    if step_key == "frame_prompt_generation":
        storyboard_id = input_payload.get("storyboard_id")
        if not storyboard_id:
            raise ValueError("执行帧提示词生成需要 input_payload.storyboard_id")
        from app.services import framePromptService

        task_id = framePromptService.generate_frame_prompt(
            db,
            log,
            int(storyboard_id),
            input_payload.get("frame_type") or "panel",
            panel_count=int(input_payload.get("panel_count") or 3),
            model=input_payload.get("model"),
        )
        return _mark_async_step_processing(db, workflow_run_id, step, snapshot, task_id, "visual_director")

    if step_key == "video_prompt_generation":
        storyboard_id = input_payload.get("storyboard_id")
        if not storyboard_id:
            raise ValueError("执行视频提示词生成需要 input_payload.storyboard_id")
        from app.services import episodeStoryboardService

        # 视频提示词重建是同步操作：直接完成步骤并写入最新 storyboard。
        storyboard = episodeStoryboardService.rebuild_video_prompt_for_storyboard(db, log, storyboard_id)
        if not storyboard:
            raise ValueError("分镜不存在，无法重建视频提示词")
        agent_run = skill_registry.create_agent_run(
            db,
            {
                "workflow_run_id": workflow_run_id,
                "workflow_step_id": str(step["id"]),
                "agent_name": step.get("agent_name") or "video_director",
                "skill_key": step.get("skill_key"),
                "status": "completed",
                "input_payload": {"storyboard_id": storyboard_id, "context_snapshot_id": snapshot["id"]},
                "output_payload": {"storyboard": storyboard},
            },
        )
        updated_step = run_service.update_workflow_step(
            db,
            workflow_run_id,
            step_key,
            {"status": "completed", "output_payload": {"agent_run_id": agent_run["id"], "storyboard": storyboard}},
        )
        return {"status": "completed", "step": updated_step, "agent_run": agent_run}

    if step_key == "voice_music_generation":
        if not run.get("drama_id"):
            raise ValueError("执行声音音乐设计需要 workflow_run 绑定 drama_id")
        from app.services import audioDesignService

        result = audioDesignService.generate_voice_music_design(db, int(run["drama_id"]), run.get("episode_id"))
        agent_run = skill_registry.create_agent_run(
            db,
            {
                "workflow_run_id": workflow_run_id,
                "workflow_step_id": str(step["id"]),
                "agent_name": step.get("agent_name") or "voice",
                "skill_key": step.get("skill_key"),
                "status": "completed",
                "input_payload": {"context_snapshot_id": snapshot["id"]},
                "output_payload": {
                    "voice_profile_count": len(result.get("voice_profiles") or []),
                    "music_cue_count": len(result.get("music_cues") or []),
                },
            },
        )
        updated_step = run_service.update_workflow_step(
            db,
            workflow_run_id,
            step_key,
            {"status": "completed", "output_payload": {"agent_run_id": agent_run["id"], "result": result}},
        )
        return {"status": "completed", "step": updated_step, "agent_run": agent_run, "result": result}

    raise ValueError(f"暂不支持真实执行步骤：{step_key}")


def _mark_async_step_processing(
    db: Session,
    workflow_run_id: str,
    step: dict[str, Any],
    snapshot: dict[str, Any],
    task_id: str | None,
    agent_fallback_name: str,
    raw_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一记录异步任务型步骤的 processing 状态。"""
    agent_run = skill_registry.create_agent_run(
        db,
        {
            "workflow_run_id": workflow_run_id,
            "workflow_step_id": str(step["id"]),
            "agent_name": step.get("agent_name") or agent_fallback_name,
            "skill_key": step.get("skill_key"),
            "status": "processing",
            "input_payload": {"async_task_id": task_id, "context_snapshot_id": snapshot["id"]},
            "output_payload": raw_result or {},
        },
    )
    updated_step = run_service.update_workflow_step(
        db,
        workflow_run_id,
        step["step_key"],
        {
            "status": "processing",
            "output_payload": {
                "async_task_id": task_id,
                "agent_run_id": agent_run["id"],
                "context_snapshot_id": snapshot["id"],
                "raw_result": raw_result or {},
            },
        },
    )
    return {"status": "processing", "async_task_id": task_id, "step": updated_step, "agent_run": agent_run}


def _agent_step_status(agent_result: dict[str, Any], apply_result: dict[str, Any] | None) -> str:
    """统一计算文本 Agent 步骤状态，区分 JSON 解析告警和业务落库告警。"""
    if apply_result and apply_result.get("status") == "failed":
        return "completed_with_apply_warning"
    if agent_result.get("parse_error"):
        return "completed_with_parse_warning"
    return "completed"
