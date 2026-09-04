"""Prompt Registry 提示词统一管理与运行链路追踪服务。

【架构定位与职责】
1. 统一管理 Prompt 模板：
   - 避免提示词硬编码散落在各个 Agent 或业务服务中，实现版本控制、灰度上线与一键回滚。
   - 维护输入参数规范（input_schema）、输出结构规范（output_schema）及关联的技能包（skill_key）。
2. 动态模板渲染引擎：
   - 将 Context Builder 构建的动态上下文和变量安全插值注入到模板中，生成确定性的 final_prompt。
3. 提示词运行全链路审计（Prompt Runs）：
   - 记录每一次 LLM 调用的 prompt 版本、输入变量、上下文快照、实际请求文本、原始输出、结构化解析产物、耗时与 Token 开销。
   - 提供版本对比（Diff）、效果复盘与成本分析能力。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import compact_dict, json_dumps, json_loads, now_iso, render_template_text


def _decode_prompt_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """反序列化数据库中的 Prompt 模板 JSON 字段。"""
    if not row:
        return None
    data = compact_dict(row) or {}
    for key in ("input_schema", "output_schema", "metadata"):
        data[key] = json_loads(data.get(key), {} if key != "metadata" else {})
    data["tags"] = json_loads(data.get("tags"), [])
    if "template" in data and "template_body" not in data:
        data["template_body"] = data["template"]
    return data


def _decode_prompt_run_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """反序列化数据库中的 Prompt 运行追踪 JSON 字段。"""
    if not row:
        return None
    data = compact_dict(row) or {}
    for key in ("variables", "context_snapshot", "parsed_output"):
        data[key] = json_loads(data.get(key), {})
    return data


def create_prompt_template(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """创建或更新指定版本的 Prompt 模板。

    参数说明：
    - prompt_key: 提示词全局唯一标识（如 story.expansion / storyboard.shot_writer）
    - version: 版本号（递增正整数，默认为 1）
    - template: 提示词模板内容（支持 {{variable}} 语法）
    - agent_name: 消费该提示词的领域 Agent 名称
    - skill_key: 归属的能力包标识
    - status: active (正式激活) / draft (草稿测试) / deprecated (已废弃)
    """
    prompt_key = str(payload.get("prompt_key") or "").strip()
    template = str(payload.get("template") or payload.get("template_body") or "").strip()
    if not prompt_key:
        raise ValueError("prompt_key 必填")
    if not template:
        raise ValueError("template 必填")

    version_val = payload.get("version")
    if version_val is None:
        max_ver = db.execute(
            text("SELECT MAX(version) FROM prompt_templates WHERE prompt_key = :k AND deleted_at IS NULL"),
            {"k": prompt_key},
        ).scalar()
        version = int(max_ver or 0) + 1
    else:
        version = int(version_val)
    status = payload.get("status") or "active"

    # 如果新版本设为 active，则将旧的 active 版本自动降级为 deprecated 或保留
    if status == "active":
        db.execute(
            text(
                "UPDATE prompt_templates SET status = 'deprecated', updated_at = :now "
                "WHERE prompt_key = :k AND version != :v AND status = 'active' AND deleted_at IS NULL"
            ),
            {"k": prompt_key, "v": version, "now": now_iso()},
        )

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
        "status": status,
        "tags": json_dumps(payload.get("tags") or []),
        "metadata": json_dumps(payload.get("metadata") or {}),
        "now": now,
    }
    existing_id = db.execute(
        text("SELECT id FROM prompt_templates WHERE prompt_key = :prompt_key AND version = :version"),
        {"prompt_key": prompt_key, "version": version},
    ).scalar()
    if existing_id:
        db.execute(
            text(
                """
                UPDATE prompt_templates SET
                    name = :name,
                    agent_name = :agent_name,
                    skill_key = :skill_key,
                    locale = :locale,
                    model_family = :model_family,
                    template = :template,
                    input_schema = :input_schema,
                    output_schema = :output_schema,
                    status = :status,
                    tags = :tags,
                    metadata = :metadata,
                    updated_at = :now,
                    deleted_at = NULL
                WHERE id = :id
                """
            ),
            {**params, "id": existing_id},
        )
    else:
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
                """
            ),
            params,
        )
    return get_prompt_template(db, prompt_key, version) or {"prompt_key": prompt_key, "version": version}


def list_prompt_templates(db: Session, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """查询 Prompt 模板列表，支持按 prompt_key、skill_key、agent_name 和 status 过滤。"""
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
    """读取指定 Prompt；未传 version 时优先获取最新 active 版本，其次获取最新任何版本。"""
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


def get_prompt_template_history(db: Session, prompt_key: str) -> list[dict[str, Any]]:
    """获取指定 Prompt 的全部历史版本演进记录。"""
    rows = fetch_all(
        db,
        "SELECT * FROM prompt_templates WHERE prompt_key = :k AND deleted_at IS NULL ORDER BY version DESC",
        {"k": prompt_key},
    )
    return [_decode_prompt_row(r) or {} for r in rows]


def rollback_prompt_template(db: Session, prompt_key: str, target_version: int) -> dict[str, Any]:
    """将指定的历史版本 Prompt 激活回滚为最新版本。

    实现逻辑：
    1. 查询 target_version 对应的模板；
    2. 计算当前库中该 prompt_key 的最大版本号 max_version；
    3. 创建一个版本号为 max_version + 1 的新版本，内容完全复制 target_version，并将 status 设为 active；
    4. 将历史版本的 active 状态取消，保证仅有一个 active 版本。
    """
    target = get_prompt_template(db, prompt_key, target_version)
    if not target:
        raise ValueError(f"目标版本不存在：{prompt_key} v{target_version}")

    max_row = fetch_one(
        db,
        "SELECT MAX(version) as max_v FROM prompt_templates WHERE prompt_key = :k AND deleted_at IS NULL",
        {"k": prompt_key},
    )
    new_version = int((max_row.get("max_v") if max_row else 0) or 0) + 1

    payload = {
        "prompt_key": prompt_key,
        "version": new_version,
        "name": target.get("name"),
        "agent_name": target.get("agent_name"),
        "skill_key": target.get("skill_key"),
        "locale": target.get("locale"),
        "model_family": target.get("model_family"),
        "template": target.get("template"),
        "input_schema": target.get("input_schema"),
        "output_schema": target.get("output_schema"),
        "status": "active",
        "tags": [*list(target.get("tags") or []), f"rollback_from_v{target_version}"],
        "metadata": {**(target.get("metadata") or {}), "rollback_from": target_version},
    }
    return create_prompt_template(db, payload)


def compare_prompt_templates(
    db: Session, prompt_key: str, version_a: int, version_b: int
) -> dict[str, Any]:
    """对比同一个 Prompt 的两个版本差异（模板正文、元数据、所属 Agent 与 Schema）。"""
    tpl_a = get_prompt_template(db, prompt_key, version_a)
    if not tpl_a:
        raise ValueError(f"版本 A 不存在：v{version_a}")
    tpl_b = get_prompt_template(db, prompt_key, version_b)
    if not tpl_b:
        raise ValueError(f"版本 B 不存在：v{version_b}")

    body_diff = tpl_a.get("template") != tpl_b.get("template")
    return {
        "prompt_key": prompt_key,
        "version_a": tpl_a,
        "version_b": tpl_b,
        "v1": tpl_a,
        "v2": tpl_b,
        "is_template_identical": not body_diff,
        "is_status_identical": tpl_a.get("status") == tpl_b.get("status"),
        "diff": {
            "body_changed": body_diff,
            "status_changed": tpl_a.get("status") != tpl_b.get("status"),
        },
    }


def render_prompt(
    db: Session, prompt_key: str, variables: dict[str, Any] | None = None, version: int | None = None
) -> dict[str, Any]:
    """渲染最终 Prompt，并返回模板版本信息。

    这个函数是 Context Builder 与 Agent Runtime 的交汇点：
    Context Builder 负责收集并提供上下文变量，Prompt Registry 负责稳定地完成变量替换。
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
    return _decode_prompt_run_row(
        result_to_dict(db.execute(text("SELECT * FROM prompt_runs WHERE id = :id"), {"id": run_id}).first())
    ) or {"id": run_id}


def list_prompt_runs(
    db: Session,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """分页查询 Prompt 调用运行快照，支持按 prompt_key、workflow_run_id、agent_name 和 status 筛选。"""
    filters = filters or {}
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 50), 200)), "offset": max(0, int(offset or 0))}

    for key in ("prompt_key", "skill_key", "agent_name", "workflow_run_id", "status", "model"):
        if filters.get(key):
            where.append(f"{key} = :{key}")
            params[key] = filters[key]

    where_sql = " AND ".join(where)
    total_row = fetch_one(db, f"SELECT COUNT(*) as cnt FROM prompt_runs WHERE {where_sql}", params)
    total = int((total_row.get("cnt") if total_row else 0) or 0)

    rows = fetch_all(
        db,
        f"SELECT * FROM prompt_runs WHERE {where_sql} ORDER BY id DESC LIMIT :limit OFFSET :offset",
        params,
    )
    return {
        "items": [_decode_prompt_run_row(r) or {} for r in rows],
        "total": total,
        "limit": params["limit"],
        "offset": params["offset"],
    }


def get_prompt_run(db: Session, run_id: int) -> dict[str, Any] | None:
    """获取单次 Prompt 调用的完整快照详情。"""
    row = fetch_one(db, "SELECT * FROM prompt_runs WHERE id = :id AND deleted_at IS NULL", {"id": int(run_id)})
    return _decode_prompt_run_row(row)

