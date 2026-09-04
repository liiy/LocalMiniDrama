"""Agent Runtime。

把 Skill、Prompt、Context 和模型调用串起来，是后续 Multi-Agent 真正执行的核心入口。
当前 Runtime 只负责通用文本 Agent：渲染 Prompt、调用文本模型、解析 JSON、记录运行证据。
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.platform_common import json_dumps
from app.prompts import registry_service as prompt_registry
from app.schemas.parser import extract_first_json_payload
from app.services import aiClient
from app.skills import registry_service as skill_registry


AGENT_RUNTIME_STEPS = {
    "requirement_analysis",
    "drama_bible_generation",
    "adaptation_plan_generation",
    "creative_quality_review",
}


def build_prompt_variables(
    run: dict[str, Any],
    step: dict[str, Any],
    context_payload: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把工作流输入和上下文压成 Prompt 模板变量。

    模板变量统一在 Runtime 构建，Agent 不再到处读取数据库或拼接上下文。
    """
    options = options or {}
    content = context_payload.get("content") or {}
    episode = content.get("episode") or {}
    drama = content.get("drama") or {}
    input_payload = dict(run.get("input_payload") or {})
    input_payload.update(options.get("input_payload") or {})

    return {
        **input_payload,
        "workflow_run_id": run.get("id"),
        "step_key": step.get("step_key"),
        "skill_key": step.get("skill_key"),
        "user_request": input_payload.get("user_request") or run.get("user_request") or "",
        "context": json_dumps(content),
        "memory": json_dumps(content.get("memory_items") or []),
        "drama_bible": json_dumps(drama.get("metadata") or {}),
        "episode_outline": input_payload.get("episode_outline") or "",
        "script_content": episode.get("script_content") or input_payload.get("script_content") or "",
        "characters": json_dumps(content.get("characters") or []),
        "scenes": json_dumps(content.get("scenes") or []),
        "props": json_dumps(content.get("props") or []),
        "storyboard": json_dumps(content.get("storyboard") or {}),
        "scene": json_dumps((content.get("scenes") or [{}])[0] if content.get("scenes") else {}),
        "visual_prompt": input_payload.get("visual_prompt") or "",
        "frame_type": input_payload.get("frame_type") or "key",
        "title": drama.get("title") or input_payload.get("title") or "",
        "genre": drama.get("genre") or input_payload.get("genre") or "",
        "synopsis": drama.get("description") or input_payload.get("synopsis") or "",
        "novel_title": input_payload.get("novel_title") or "",
        "chapter_summaries": input_payload.get("chapter_summaries") or "",
    }


def run_text_agent(
    db: Session,
    log,
    *,
    run: dict[str, Any],
    step: dict[str, Any],
    context_payload: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行一次通用文本 Agent。

    外部 AI 调用只发生在这里；调用前后都会写入 agent_runs / prompt_runs，保证可复盘。
    """
    options = options or {}
    skill_key = step.get("skill_key")
    if not skill_key:
        raise ValueError("当前步骤未绑定 skill_key")

    skill = skill_registry.get_skill(db, skill_key)
    if not skill:
        raise ValueError(f"Skill 不存在或尚未 bootstrap：{skill_key}")
    version_detail = skill.get("version_detail") or {}
    prompt_keys = version_detail.get("prompt_keys") or []
    if not prompt_keys:
        raise ValueError(f"Skill 未绑定 prompt_keys：{skill_key}")

    prompt_key = options.get("prompt_key") or prompt_keys[0]
    variables = build_prompt_variables(run, step, context_payload, options)
    rendered = prompt_registry.render_prompt(db, prompt_key, variables, options.get("prompt_version"))

    agent_run = skill_registry.create_agent_run(
        db,
        {
            "workflow_run_id": run.get("id"),
            "workflow_step_id": str(step["id"]),
            "agent_name": step.get("agent_name") or rendered.get("agent_name") or "agent",
            "skill_key": skill_key,
            "status": "processing",
            "input_payload": {
                "prompt_key": prompt_key,
                "prompt_version": rendered.get("version"),
                "context_snapshot_id": options.get("context_snapshot_id"),
            },
        },
    )

    system_prompt = options.get("system_prompt") or "你是 LocalMiniDrama 的专业创作 Agent。请严格按用户要求输出，优先输出可解析 JSON。"
    start = time.perf_counter()
    try:
        raw_output = aiClient.generate_text(
            db,
            log,
            "text",
            rendered["final_prompt"],
            system_prompt,
            {
                "model": options.get("model"),
                "temperature": options.get("temperature", 0.7),
                "json_mode": options.get("json_mode", True),
            },
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        parsed_output: Any = None
        parse_error = ""
        if options.get("parse_json", True):
            try:
                parsed_output = extract_first_json_payload(raw_output)
            except Exception as err:  # noqa: BLE001
                # 解析失败不直接丢弃原文，QA/人工审核仍可以查看 raw_output。
                parse_error = str(err)

        prompt_run = prompt_registry.record_prompt_run(
            db,
            {
                "prompt_key": prompt_key,
                "prompt_version": rendered.get("version"),
                "skill_key": skill_key,
                "agent_name": step.get("agent_name"),
                "workflow_run_id": run.get("id"),
                "workflow_step_id": str(step["id"]),
                "model": options.get("model"),
                "variables": variables,
                "context_snapshot": context_payload,
                "final_prompt": rendered["final_prompt"],
                "raw_output": raw_output,
                "parsed_output": parsed_output or {},
                "status": "completed" if not parse_error else "completed_with_parse_warning",
                "error": parse_error,
                "latency_ms": latency_ms,
            },
        )
        skill_registry.update_agent_run(
            db,
            agent_run["id"],
            {
                "status": "completed" if not parse_error else "completed_with_parse_warning",
                "prompt_run_id": str(prompt_run.get("id")),
                "output_payload": {"raw_output": raw_output, "parsed_output": parsed_output, "parse_error": parse_error},
                "latency_ms": latency_ms,
            },
        )
        return {
            "agent_run_id": agent_run["id"],
            "prompt_run_id": prompt_run.get("id"),
            "raw_output": raw_output,
            "parsed_output": parsed_output,
            "parse_error": parse_error,
        }
    except Exception as err:
        latency_ms = int((time.perf_counter() - start) * 1000)
        skill_registry.update_agent_run(
            db,
            agent_run["id"],
            {"status": "failed", "error": str(err), "latency_ms": latency_ms},
        )
        prompt_registry.record_prompt_run(
            db,
            {
                "prompt_key": prompt_key,
                "prompt_version": rendered.get("version"),
                "skill_key": skill_key,
                "agent_name": step.get("agent_name"),
                "workflow_run_id": run.get("id"),
                "workflow_step_id": str(step["id"]),
                "model": options.get("model"),
                "variables": variables,
                "context_snapshot": context_payload,
                "final_prompt": rendered["final_prompt"],
                "status": "failed",
                "error": str(err),
                "latency_ms": latency_ms,
            },
        )
        raise
