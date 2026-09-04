"""Agent 输出落库适配器。

Agent Runtime 只负责调用模型并解析结构化结果；这里负责把结果写回业务表。
这样可以避免每个 Agent 自己拼 SQL，也方便后续统一加审核、回滚和版本控制。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.context import memory_service
from app.db.session import fetch_one, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso
from app.skills import registry_service as skill_registry
from app.workflows import run_service


OUTPUT_APPLIER_STEPS = {
    "requirement_analysis",
    "drama_bible_generation",
    "adaptation_plan_generation",
    "creative_quality_review",
}


def normalize_agent_payload(agent_result: dict[str, Any] | None) -> dict[str, Any]:
    """把模型输出统一整理成 dict，便于后续写入数据库。

    模型可能输出 JSON object、JSON array，也可能 JSON 解析失败只剩原文。
    落库层不假设模型一定完美，而是尽量保留可追溯的原始结果。
    """
    agent_result = agent_result or {}
    parsed = agent_result.get("parsed_output")
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"items": parsed}
    if parsed not in (None, ""):
        return {"value": parsed}
    return {"raw_output": agent_result.get("raw_output") or "", "parse_error": agent_result.get("parse_error") or ""}


def apply_agent_output(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """按 workflow step 类型应用 Agent 结果。

    短期状态写入 workflow_runs.state；可长期复用的创作决策写入 memory_items；
    质量检查结果写入 quality_reports，避免混在普通 step output 中不好检索。
    """
    step_key = step.get("step_key")
    if step_key not in OUTPUT_APPLIER_STEPS:
        return {"status": "skipped", "reason": "当前步骤无需业务落库"}

    payload = normalize_agent_payload(agent_result)
    if step_key == "requirement_analysis":
        return _apply_requirement_analysis(db, run, payload)
    if step_key == "drama_bible_generation":
        return _apply_drama_bible(db, run, payload)
    if step_key == "adaptation_plan_generation":
        return _apply_adaptation_plan(db, run, step, agent_result, payload)
    if step_key == "creative_quality_review":
        return _apply_quality_review(db, run, step, payload, agent_result)
    return {"status": "skipped", "reason": "未匹配到落库策略"}


def _apply_requirement_analysis(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """需求分析属于短期生产状态，写入 workflow state 供后续步骤读取。"""
    workflow = _merge_workflow_state(db, run["id"], {"requirement_analysis": payload})
    return {"status": "applied", "target": "workflow_runs.state", "workflow_run_id": workflow.get("id")}


def _apply_drama_bible(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """剧集 Bible 是全剧长期设定，优先写入 dramas.metadata，并同步到 workflow state。"""
    targets = ["workflow_runs.state"]
    _merge_workflow_state(db, run["id"], {"drama_bible": payload})
    drama_id = run.get("drama_id")
    if drama_id:
        updated = _merge_drama_metadata(
            db,
            int(drama_id),
            {
                "drama_bible": payload,
                "agent_outputs": {
                    "drama_bible_generation": {
                        "workflow_run_id": run.get("id"),
                        "updated_at": now_iso(),
                    }
                },
            },
        )
        if updated:
            targets.append("dramas.metadata")
    return {"status": "applied", "target": targets, "drama_id": drama_id}


def _apply_adaptation_plan(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    agent_result: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """小说改编计划既写入短期状态，也沉淀为长期记忆，后续分集改编可检索复用。"""
    _merge_workflow_state(db, run["id"], {"adaptation_plan": payload})
    drama_id = run.get("drama_id")
    if not drama_id:
        return {"status": "applied", "target": "workflow_runs.state", "memory_item_id": None}

    memory = memory_service.add_memory_item(
        db,
        {
            "drama_id": int(drama_id),
            "episode_id": run.get("episode_id"),
            "memory_type": "adaptation_plan",
            "scope": "drama",
            "title": _pick_text(payload, ("title", "name")) or "小说改编计划",
            "content": json_dumps(payload),
            "summary": _pick_text(payload, ("summary", "strategy", "adaptation_strategy", "logline")),
            "keywords": _extract_keywords(payload),
            "source_type": "workflow_step",
            "source_id": str(step.get("id")),
            "metadata": {
                "workflow_run_id": run.get("id"),
                "agent_run_id": agent_result.get("agent_run_id"),
                "prompt_run_id": agent_result.get("prompt_run_id"),
            },
        },
    )
    if agent_result.get("agent_run_id"):
        # 把新增长期记忆反挂到 agent_run，方便排查这次 Agent 影响了哪些上下文。
        skill_registry.update_agent_run(db, agent_result["agent_run_id"], {"memory_refs": [memory["id"]]})
    return {"status": "applied", "target": ["workflow_runs.state", "memory_items"], "memory_item_id": memory["id"]}


def _apply_quality_review(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    payload: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """创意质检单独入表，便于后续做人工确认、返工队列和质量趋势统计。"""
    report = _insert_quality_report(db, run, step, payload)
    _merge_workflow_state(
        db,
        run["id"],
        {
            "latest_quality_report_id": report.get("id"),
            "latest_quality_review": {
                "score": report.get("score"),
                "status": report.get("status"),
                "prompt_run_id": agent_result.get("prompt_run_id"),
            },
        },
    )
    return {"status": "applied", "target": ["quality_reports", "workflow_runs.state"], "quality_report_id": report["id"]}


def _merge_workflow_state(db: Session, workflow_run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    current = run_service.get_workflow_run(db, workflow_run_id, include_steps=False) or {"state": {}}
    state = dict(current.get("state") or {})
    _deep_merge(state, patch)
    return run_service.update_workflow_run(db, workflow_run_id, {"state": state})


def _merge_drama_metadata(db: Session, drama_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
    row = fetch_one(db, "SELECT id, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": drama_id})
    if not row:
        return None
    metadata = json_loads(row.get("metadata"), {}) or {}
    if not isinstance(metadata, dict):
        metadata = {"legacy_metadata": metadata}
    _deep_merge(metadata, patch)
    db.execute(
        text("UPDATE dramas SET metadata = :metadata, updated_at = :updated_at WHERE id = :id"),
        {"id": drama_id, "metadata": json_dumps(metadata), "updated_at": now_iso()},
    )
    return {"id": drama_id, "metadata": metadata}


def _insert_quality_report(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = now_iso()
    issues = payload.get("issues") or payload.get("missing_fields") or payload.get("continuity_risks") or []
    suggestions = payload.get("suggestions") or []
    score = _to_float(payload.get("score") or payload.get("overall_score"))
    status = "open" if issues or suggestions else "passed"
    res = db.execute(
        text(
            """
            INSERT INTO quality_reports (
                workflow_run_id, workflow_step_id, drama_id, episode_id, report_type, status,
                score, issues, suggestions, raw_report, created_at, updated_at
            ) VALUES (
                :workflow_run_id, :workflow_step_id, :drama_id, :episode_id, :report_type, :status,
                :score, :issues, :suggestions, :raw_report, :now, :now
            )
            """
        ),
        {
            "workflow_run_id": run.get("id"),
            "workflow_step_id": str(step.get("id")) if step.get("id") is not None else None,
            "drama_id": run.get("drama_id"),
            "episode_id": run.get("episode_id"),
            "report_type": "creative_review",
            "status": status,
            "score": score,
            "issues": json_dumps(issues),
            "suggestions": json_dumps(suggestions),
            "raw_report": json_dumps(payload),
            "now": now,
        },
    )
    row = db.execute(text("SELECT * FROM quality_reports WHERE id = :id"), {"id": res.lastrowid}).first()
    return result_to_dict(row)


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """只合并 dict，列表和标量整体替换，避免把剧本段落数组误拼接。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _pick_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_keywords(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("keywords") or payload.get("tags") or payload.get("themes") or []
    if isinstance(raw, str):
        return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
