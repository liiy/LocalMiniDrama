"""Skill Registry 服务。

Skill 是“可版本化的能力包”，不是单纯提示词。它把 Prompt、上下文策略、
模型策略、输入输出 Schema 和质量检查规则绑定到一起，供多 Agent 复用。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import compact_dict, json_dumps, json_loads, now_iso


def _decode_skill(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = compact_dict(row) or {}
    data["metadata"] = json_loads(data.get("metadata"), {})
    return data


def _decode_skill_version(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = compact_dict(row) or {}
    for key in ("input_schema", "output_schema", "context_policy", "model_policy", "quality_checks", "examples"):
        data[key] = json_loads(data.get(key), {} if key != "examples" else [])
    data["prompt_keys"] = json_loads(data.get("prompt_keys"), [])
    return data


def upsert_skill(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """创建或更新 Skill 主记录，并同步写入当前版本。"""
    skill_key = str(payload.get("skill_key") or "").strip()
    if not skill_key:
        raise ValueError("skill_key 必填")
    version = int(payload.get("version") or payload.get("current_version") or 1)
    now = now_iso()
    db.execute(
        text(
            """
            INSERT INTO skills (
                skill_key, name, domain, locale, status, current_version, description, metadata, created_at, updated_at
            ) VALUES (
                :skill_key, :name, :domain, :locale, :status, :version, :description, :metadata, :now, :now
            )
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                domain = VALUES(domain),
                locale = VALUES(locale),
                status = VALUES(status),
                current_version = VALUES(current_version),
                description = VALUES(description),
                metadata = VALUES(metadata),
                updated_at = VALUES(updated_at),
                deleted_at = NULL
            """
        ),
        {
            "skill_key": skill_key,
            "name": payload.get("name") or skill_key,
            "domain": payload.get("domain"),
            "locale": payload.get("locale") or "zh",
            "status": payload.get("status") or "draft",
            "version": version,
            "description": payload.get("description") or "",
            "metadata": json_dumps(payload.get("metadata") or {}),
            "now": now,
        },
    )
    upsert_skill_version(db, {**payload, "skill_key": skill_key, "version": version})
    return get_skill(db, skill_key) or {"skill_key": skill_key}


def upsert_skill_version(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """写入 Skill 的具体版本定义。"""
    skill_key = str(payload.get("skill_key") or "").strip()
    if not skill_key:
        raise ValueError("skill_key 必填")
    version = int(payload.get("version") or 1)
    now = now_iso()
    db.execute(
        text(
            """
            INSERT INTO skill_versions (
                skill_key, version, input_schema, output_schema, prompt_keys, context_policy,
                model_policy, quality_checks, examples, status, created_at, updated_at
            ) VALUES (
                :skill_key, :version, :input_schema, :output_schema, :prompt_keys, :context_policy,
                :model_policy, :quality_checks, :examples, :status, :now, :now
            )
            ON DUPLICATE KEY UPDATE
                input_schema = VALUES(input_schema),
                output_schema = VALUES(output_schema),
                prompt_keys = VALUES(prompt_keys),
                context_policy = VALUES(context_policy),
                model_policy = VALUES(model_policy),
                quality_checks = VALUES(quality_checks),
                examples = VALUES(examples),
                status = VALUES(status),
                updated_at = VALUES(updated_at),
                deleted_at = NULL
            """
        ),
        {
            "skill_key": skill_key,
            "version": version,
            "input_schema": json_dumps(payload.get("input_schema") or {}),
            "output_schema": json_dumps(payload.get("output_schema") or {}),
            "prompt_keys": json_dumps(payload.get("prompt_keys") or []),
            "context_policy": json_dumps(payload.get("context_policy") or {}),
            "model_policy": json_dumps(payload.get("model_policy") or {}),
            "quality_checks": json_dumps(payload.get("quality_checks") or {}),
            "examples": json_dumps(payload.get("examples") or []),
            "status": payload.get("status") or "draft",
            "now": now,
        },
    )
    return get_skill_version(db, skill_key, version) or {"skill_key": skill_key, "version": version}


def list_skills(db: Session, status: str | None = None) -> list[dict[str, Any]]:
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {}
    if status:
        where.append("status = :status")
        params["status"] = status
    rows = fetch_all(db, "SELECT * FROM skills WHERE " + " AND ".join(where) + " ORDER BY skill_key", params)
    return [_decode_skill(r) or {} for r in rows]


def get_skill(db: Session, skill_key: str) -> dict[str, Any] | None:
    row = fetch_one(db, "SELECT * FROM skills WHERE skill_key = :k AND deleted_at IS NULL", {"k": skill_key})
    skill = _decode_skill(row)
    if not skill:
        return None
    skill["version_detail"] = get_skill_version(db, skill_key, int(skill.get("current_version") or 1))
    return skill


def get_skill_version(db: Session, skill_key: str, version: int) -> dict[str, Any] | None:
    row = fetch_one(
        db,
        "SELECT * FROM skill_versions WHERE skill_key = :k AND version = :v AND deleted_at IS NULL",
        {"k": skill_key, "v": int(version)},
    )
    return _decode_skill_version(row)


def create_agent_run(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """记录一次 Agent 执行，为后续 QA、追踪和人工复盘提供证据链。"""
    now = now_iso()
    res = db.execute(
        text(
            """
            INSERT INTO agent_runs (
                workflow_run_id, workflow_step_id, agent_name, skill_key, status,
                input_payload, output_payload, memory_refs, prompt_run_id, error, latency_ms,
                created_at, updated_at
            ) VALUES (
                :workflow_run_id, :workflow_step_id, :agent_name, :skill_key, :status,
                :input_payload, :output_payload, :memory_refs, :prompt_run_id, :error, :latency_ms,
                :now, :now
            )
            """
        ),
        {
            "workflow_run_id": payload.get("workflow_run_id"),
            "workflow_step_id": payload.get("workflow_step_id"),
            "agent_name": payload.get("agent_name") or "",
            "skill_key": payload.get("skill_key"),
            "status": payload.get("status") or "completed",
            "input_payload": json_dumps(payload.get("input_payload") or {}),
            "output_payload": json_dumps(payload.get("output_payload") or {}),
            "memory_refs": json_dumps(payload.get("memory_refs") or []),
            "prompt_run_id": payload.get("prompt_run_id"),
            "error": payload.get("error"),
            "latency_ms": payload.get("latency_ms"),
            "now": now,
        },
    )
    return result_to_dict(db.execute(text("SELECT * FROM agent_runs WHERE id = :id"), {"id": res.lastrowid}).first())


def update_agent_run(db: Session, agent_run_id: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    """更新 Agent Run 状态，用于异步任务完成后回写执行结果。"""
    now = now_iso()
    updates = ["updated_at = :updated_at"]
    params: dict[str, Any] = {"id": agent_run_id, "updated_at": now}
    for key in ("status", "error", "latency_ms", "prompt_run_id"):
        if key in payload:
            updates.append(f"{key} = :{key}")
            params[key] = payload[key]
    if "output_payload" in payload:
        updates.append("output_payload = :output_payload")
        params["output_payload"] = json_dumps(payload.get("output_payload") or {})
    if "memory_refs" in payload:
        updates.append("memory_refs = :memory_refs")
        params["memory_refs"] = json_dumps(payload.get("memory_refs") or [])
    db.execute(text("UPDATE agent_runs SET " + ", ".join(updates) + " WHERE id = :id"), params)
    row = result_to_dict(db.execute(text("SELECT * FROM agent_runs WHERE id = :id"), {"id": agent_run_id}).first())
    return row
