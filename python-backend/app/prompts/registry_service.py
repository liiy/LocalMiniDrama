"""Prompt Registry 服务。

负责管理 Prompt 模板版本、渲染最终 Prompt，以及记录每次模型调用的运行快照。
后续多 Agent 接入时，Agent 只需要声明 prompt_key / skill_key，不再自己散落拼接大段提示词。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import compact_dict, json_dumps, json_loads, now_iso, render_template_text


def _decode_prompt_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = compact_dict(row) or {}
    for key in ("input_schema", "output_schema", "metadata"):
        data[key] = json_loads(data.get(key), {} if key != "metadata" else {})
    data["tags"] = json_loads(data.get("tags"), [])
    return data


def create_prompt_template(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """创建或更新一个 Prompt 模板版本。"""
    prompt_key = str(payload.get("prompt_key") or "").strip()
    template = str(payload.get("template") or "").strip()
    if not prompt_key:
        raise ValueError("prompt_key 必填")
    if not template:
        raise ValueError("template 必填")

    version = int(payload.get("version") or 1)
    now = now_iso()
    params = {
        "prompt_key": prompt_key,
        "version": version,
        "name": payload.get("name") or prompt_key,
        "agent_name": payload.get("agent_name"),
        "skill_key": payload.get("skill_key"),
        "locale": payload.get("locale") or "zh",
        "model_family": payload.get("model_family"),
        "template": template,
        "input_schema": json_dumps(payload.get("input_schema") or {}),
        "output_schema": json_dumps(payload.get("output_schema") or {}),
        "status": payload.get("status") or "draft",
        "tags": json_dumps(payload.get("tags") or []),
        "metadata": json_dumps(payload.get("metadata") or {}),
        "now": now,
    }
    db.execute(
        text(
            """
            INSERT INTO prompt_templates (
                prompt_key, version, name, agent_name, skill_key, locale, model_family, template,
                input_schema, output_schema, status, tags, metadata, created_at, updated_at
            ) VALUES (
                :prompt_key, :version, :name, :agent_name, :skill_key, :locale, :model_family, :template,
                :input_schema, :output_schema, :status, :tags, :metadata, :now, :now
            )
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                agent_name = VALUES(agent_name),
                skill_key = VALUES(skill_key),
                locale = VALUES(locale),
                model_family = VALUES(model_family),
                template = VALUES(template),
                input_schema = VALUES(input_schema),
                output_schema = VALUES(output_schema),
                status = VALUES(status),
                tags = VALUES(tags),
                metadata = VALUES(metadata),
                updated_at = VALUES(updated_at),
                deleted_at = NULL
            """
        ),
        params,
    )
    return get_prompt_template(db, prompt_key, version) or {"prompt_key": prompt_key, "version": version}


def list_prompt_templates(db: Session, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    filters = filters or {}
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {}
    for key in ("prompt_key", "skill_key", "agent_name", "status"):
        if filters.get(key):
            where.append(f"{key} = :{key}")
            params[key] = filters[key]
    rows = fetch_all(
        db,
        "SELECT * FROM prompt_templates WHERE " + " AND ".join(where) + " ORDER BY prompt_key, version DESC",
        params,
    )
    return [_decode_prompt_row(r) or {} for r in rows]


def get_prompt_template(db: Session, prompt_key: str, version: int | None = None) -> dict[str, Any] | None:
    """读取指定 Prompt；未传 version 时取最新 active，其次取最新任意版本。"""
    if version is not None:
        row = fetch_one(
            db,
            "SELECT * FROM prompt_templates WHERE prompt_key = :k AND version = :v AND deleted_at IS NULL",
            {"k": prompt_key, "v": int(version)},
        )
        return _decode_prompt_row(row)

    row = fetch_one(
        db,
        "SELECT * FROM prompt_templates WHERE prompt_key = :k AND status = 'active' AND deleted_at IS NULL "
        "ORDER BY version DESC LIMIT 1",
        {"k": prompt_key},
    ) or fetch_one(
        db,
        "SELECT * FROM prompt_templates WHERE prompt_key = :k AND deleted_at IS NULL ORDER BY version DESC LIMIT 1",
        {"k": prompt_key},
    )
    return _decode_prompt_row(row)


def render_prompt(db: Session, prompt_key: str, variables: dict[str, Any] | None = None, version: int | None = None) -> dict[str, Any]:
    """渲染最终 Prompt，并返回模板版本信息。

    这个函数是后续 Context Builder 与 Agent Runtime 的交汇点：Context Builder 负责准备变量，
    Prompt Registry 只负责稳定地把变量写入模板。
    """
    tpl = get_prompt_template(db, prompt_key, version)
    if not tpl:
        raise ValueError(f"Prompt 不存在：{prompt_key}")
    final_prompt = render_template_text(str(tpl.get("template") or ""), variables or {})
    return {
        "prompt_key": tpl["prompt_key"],
        "version": tpl["version"],
        "skill_key": tpl.get("skill_key"),
        "agent_name": tpl.get("agent_name"),
        "final_prompt": final_prompt,
    }


def record_prompt_run(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """记录一次 AI Prompt 调用快照，便于回放、成本统计和质量评估。"""
    now = now_iso()
    params = {
        "prompt_key": payload.get("prompt_key") or "",
        "prompt_version": int(payload.get("prompt_version") or payload.get("version") or 0),
        "skill_key": payload.get("skill_key"),
        "agent_name": payload.get("agent_name"),
        "workflow_run_id": payload.get("workflow_run_id"),
        "workflow_step_id": payload.get("workflow_step_id"),
        "model": payload.get("model"),
        "variables": json_dumps(payload.get("variables") or {}),
        "context_snapshot": json_dumps(payload.get("context_snapshot") or {}),
        "final_prompt": payload.get("final_prompt"),
        "raw_output": payload.get("raw_output"),
        "parsed_output": json_dumps(payload.get("parsed_output") or {}),
        "status": payload.get("status") or "completed",
        "error": payload.get("error"),
        "latency_ms": payload.get("latency_ms"),
        "prompt_tokens": payload.get("prompt_tokens"),
        "completion_tokens": payload.get("completion_tokens"),
        "cost": payload.get("cost"),
        "now": now,
    }
    res = db.execute(
        text(
            """
            INSERT INTO prompt_runs (
                prompt_key, prompt_version, skill_key, agent_name, workflow_run_id, workflow_step_id,
                model, variables, context_snapshot, final_prompt, raw_output, parsed_output,
                status, error, latency_ms, prompt_tokens, completion_tokens, cost, created_at, updated_at
            ) VALUES (
                :prompt_key, :prompt_version, :skill_key, :agent_name, :workflow_run_id, :workflow_step_id,
                :model, :variables, :context_snapshot, :final_prompt, :raw_output, :parsed_output,
                :status, :error, :latency_ms, :prompt_tokens, :completion_tokens, :cost, :now, :now
            )
            """
        ),
        params,
    )
    run_id = res.lastrowid
    return result_to_dict(db.execute(text("SELECT * FROM prompt_runs WHERE id = :id"), {"id": run_id}).first())
