"""generation/* 端点服务 — 契约翻译 backend-node。

- characterGenerationService.generateCharacters：建 async_tasks（type='character_generation'）
  后异步触发 AI 并保存角色与锚点。
- storyGenerationService.startStoryGeneration：校验项目 → 复用进行中的任务 → 否则建任务
  （type='story_generation'）并异步生成剧本并保存 episodes / outline。
- storyGenerationService.generateStory：直接同步调用文本 AI 扩展剧本。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.db.session import fetch_one, session_scope
from app.schemas.drama import CharacterGenerationRequest, StoryGenerationRequest
from app.schemas.parser import extract_first_json_payload
from app.services import aiClient, characterGenerationService, dramaService as drama_svc
from app.services import promptI18n, taskService, workerService
from app.services.libraryCommon import to_int_id
from app.workflows import run_service as workflow_runs

log = get_logger("lmd.generationService")

# Node routes/index.js：命中这些关键字时返回 400，其余返回 500
BAD_REQUEST_KEYWORDS = ("未配置", "必填", "不存在")


def generate_characters(db: Session, log_, req: dict | CharacterGenerationRequest, cfg: dict | None = None) -> str:
    """等价 characterGenerationService.generateCharacters。"""
    req_dict = req.model_dump(exclude_unset=True) if isinstance(req, CharacterGenerationRequest) else (req or {})
    return characterGenerationService.generate_characters(db, cfg, log_, req_dict)


def process_story_generation(task_id: str, req: dict | StoryGenerationRequest) -> None:
    req_dict = req.model_dump(exclude_unset=True) if isinstance(req, StoryGenerationRequest) else (req or {})
    try:
        with session_scope() as db:
            workflow_run_id = str(req_dict.get("workflow_run_id") or "").strip()
            if workflow_run_id:
                # 兼容式接入：旧剧本生成任务仍按 async_tasks 跑，新工作流只同步状态。
                workflow_runs.update_workflow_run(
                    db,
                    workflow_run_id,
                    {"status": "processing", "state": {"async_task_id": task_id}},
                )
                workflow_runs.update_workflow_step(
                    db,
                    workflow_run_id,
                    "episode_script_generation",
                    {"status": "processing", "input_payload": req_dict},
                )
            taskService.update_task_status(db, task_id, "processing", 10, "正在生成剧本...")
            result = generate_story(db, log, req_dict)
            episodes = (result or {}).get("episodes") or []
            if not episodes:
                if workflow_run_id:
                    workflow_runs.update_workflow_step(
                        db,
                        workflow_run_id,
                        "episode_script_generation",
                        {"status": "failed", "error": "AI 未能生成剧本"},
                    )
                    workflow_runs.update_workflow_run(db, workflow_run_id, {"status": "failed", "error": "AI 未能生成剧本"})
                taskService.update_task_error(db, task_id, "AI 未能生成剧本")
                return

            drama_id = to_int_id(req_dict.get("drama_id"))
            taskService.update_task_status(db, task_id, "processing", 75, "正在保存剧本...")

            saved = drama_svc.save_episodes(
                db,
                drama_id,
                {
                    "episodes": [
                        {
                            "episode_number": ep.get("episode") if ep.get("episode") is not None else i + 1,
                            "title": ep.get("title") or f"第{ep.get('episode') if ep.get('episode') is not None else i + 1}集",
                            "script_content": ep.get("content") or "",
                        }
                        for i, ep in enumerate(episodes)
                    ]
                },
            )
            if not saved:
                if workflow_run_id:
                    workflow_runs.update_workflow_step(
                        db,
                        workflow_run_id,
                        "episode_script_generation",
                        {"status": "failed", "error": "保存剧本失败：项目不存在"},
                    )
                    workflow_runs.update_workflow_run(
                        db,
                        workflow_run_id,
                        {"status": "failed", "error": "保存剧本失败：项目不存在"},
                    )
                taskService.update_task_error(db, task_id, "保存剧本失败：项目不存在")
                return

            if any(req_dict.get(k) for k in ("summary", "genre", "drama_style", "metadata", "title")):
                drama_svc.save_outline(
                    db,
                    drama_id,
                    {
                        "title": req_dict.get("title"),
                        "summary": req_dict.get("summary"),
                        "genre": req_dict.get("genre"),
                        "style": req_dict.get("drama_style"),
                        "metadata": req_dict.get("metadata"),
                    },
                )

            taskService.update_task_result(
                db,
                task_id,
                {
                    "drama_id": drama_id,
                    "episode_count": len(episodes),
                },
            )
            if workflow_run_id:
                workflow_runs.update_workflow_step(
                    db,
                    workflow_run_id,
                    "episode_script_generation",
                    {
                        "status": "completed",
                        "output_payload": {"drama_id": drama_id, "episode_count": len(episodes)},
                    },
                )
                workflow_runs.update_workflow_run(
                    db,
                    workflow_run_id,
                    {
                        "status": "processing",
                        "state": {
                            "async_task_id": task_id,
                            "last_completed_step": "episode_script_generation",
                            "next_step": "continuity_check",
                        },
                    },
                )
            log.info(
                "Story generation completed and saved",
                extra={"task_id": task_id, "drama_id": drama_id, "episode_count": len(episodes)},
            )
    except Exception as fatal_err:
        log.error("processStoryGeneration fatal", extra={"task_id": task_id, "error": str(fatal_err)})
        with session_scope() as db_err:
            workflow_run_id = str(req_dict.get("workflow_run_id") or "").strip()
            if workflow_run_id:
                workflow_runs.update_workflow_step(
                    db_err,
                    workflow_run_id,
                    "episode_script_generation",
                    {"status": "failed", "error": str(fatal_err)},
                )
                workflow_runs.update_workflow_run(db_err, workflow_run_id, {"status": "failed", "error": str(fatal_err)})
            taskService.update_task_error(db_err, task_id, str(fatal_err) or "故事生成失败")


def start_story_generation(db: Session, log_, req: dict | StoryGenerationRequest) -> str:
    """等价 storyGenerationService.startStoryGeneration。"""
    req_dict = req.model_dump(exclude_unset=True) if isinstance(req, StoryGenerationRequest) else (req or {})
    drama_id = str(req_dict.get("drama_id") or "")
    if not drama_id:
        raise ValueError("drama_id 必填")
    if not drama_svc.get_drama_by_id(db, to_int_id(drama_id)):
        raise ValueError("项目不存在")

    existing = fetch_one(
        db,
        "SELECT id FROM async_tasks WHERE resource_id = :r AND type = 'story_generation' "
        "AND status IN ('pending', 'processing') AND deleted_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        {"r": drama_id},
    )
    if existing:
        log_.info("Story generation already running", extra={"task_id": existing["id"], "drama_id": drama_id})
        return existing["id"]

    task = taskService.create_task(db, log_, "story_generation", drama_id)
    task_id = task["id"] if isinstance(task, dict) else str(task)
    workerService.submit(process_story_generation, task_id, req_dict)
    return task_id


def generate_story(db: Session, log, req: dict | StoryGenerationRequest) -> dict:
    """等价 storyGenerationService.generateStory 的同步校验分支。

    Node 在无 premise 时抛 '请提供故事梗概'（不含 400 关键字 → 路由返回 500）；
    有 premise 时进入 AI 调用。"""
    req_dict = req.model_dump(exclude_unset=True) if isinstance(req, StoryGenerationRequest) else (req or {})
    premise = str(req_dict.get("premise") or req_dict.get("prompt") or req_dict.get("text") or "").strip()
    if not premise:
        raise ValueError("请提供故事梗概")

    cfg = getattr(__import__("app.core.config", fromlist=["load_config"]), "load_config")()
    style = req_dict.get("style") or req_dict.get("genre") or None
    type_ = req_dict.get("type") or None
    episode_count = max(1, int(float(req_dict.get("episode_count") or 1)))

    system_prompt = promptI18n.get_story_expansion_system_prompt(cfg, episode_count)
    user_prompt = promptI18n.build_story_expansion_user_prompt(cfg, premise, style, type_, episode_count)

    ai_options: dict[str, Any] = {
        "scene_key": "story_generation",
        "model": req.get("model"),
        "temperature": 0.8,
        "min_max_tokens": max(2000, episode_count * 2200),
    }
    if req.get("workflow_run_id"):
        # 只有进入新工作流时才写 Prompt Run，避免旧接口默认产生额外落库压力。
        ai_options.update(
            {
                "prompt_key": req.get("prompt_key") or "story.expansion",
                "skill_key": req.get("skill_key") or "episode_script_writing",
                "agent_name": req.get("agent_name") or "script_writer",
                "workflow_run_id": req.get("workflow_run_id"),
                "workflow_step_id": req.get("workflow_step_id"),
                "prompt_variables": {
                    "premise": premise,
                    "style": style,
                    "type": type_,
                    "episode_count": episode_count,
                },
            }
        )

    raw_text = aiClient.generate_text(
        db,
        log,
        "text",
        user_prompt,
        system_prompt,
        ai_options,
    )

    # 【阶段一改造升级：鲁棒 JSON 提取与容错解析】
    # 使用 extract_first_json_payload 自动处理 Markdown 代码块、尾随逗号、未闭合截断等问题
    parsed = extract_first_json_payload(raw_text)
    if parsed is None:
        try:
            cleaned = promptI18n._clean_ai_json_text(raw_text)
            if cleaned:
                parsed = json.loads(cleaned)
        except Exception:
            parsed = None

    if isinstance(parsed, list):
        episode_list = parsed
    elif isinstance(parsed, dict):
        keys = [k for k, v in parsed.items() if isinstance(v, list)]
        arr_key = next(iter(keys), None)
        if arr_key:
            episode_list = parsed[arr_key]
        elif parsed.get("content") or parsed.get("episode") is not None:
            episode_list = [parsed]
        else:
            episode_list = []
    else:
        episode_list = []

    if not episode_list:
        fallback_content = raw_text.strip()
        return {"episodes": [{"episode": 1, "title": "第1集", "content": fallback_content}]}

    result = []
    for i, ep in enumerate(episode_list):
        if not isinstance(ep, dict):
            continue
        episode_num = int(ep.get("episode") or (i + 1))
        title = str(ep.get("title") or f"第{episode_num}集").strip()
        content = str(ep.get("content") or ep.get("script") or ep.get("text") or ep.get("body") or "").strip()
        if content:
            result.append({"episode": episode_num, "title": title, "content": content})
    if result:
        return {"episodes": result}

    fallback_content = raw_text.strip()
    return {"episodes": [{"episode": 1, "title": "第1集", "content": fallback_content}]}
