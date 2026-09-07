"""创作质量报告服务。

QA Agent 的输出不直接混入普通日志，而是进入 quality_reports。
后续可以在这里扩展人工审核、返工派单和质量趋势统计。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one
from app.platform_common import json_dumps, json_loads, now_iso


def _decode_report(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    # issues/suggestions/raw_report 使用 JSON 存储，API 层统一返回结构化对象。
    data["issues"] = json_loads(data.get("issues"), [])
    data["suggestions"] = json_loads(data.get("suggestions"), [])
    data["raw_report"] = json_loads(data.get("raw_report"), {})
    return data


def list_quality_reports(
    db: Session,
    *,
    workflow_run_id: str | None = None,
    drama_id: int | None = None,
    episode_id: int | None = None,
    status: str | None = None,
    report_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询 QA 报告列表，供前端质量面板和运营排查使用。"""
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 50), 100))}
    if workflow_run_id:
        where.append("workflow_run_id = :workflow_run_id")
        params["workflow_run_id"] = workflow_run_id
    if drama_id:
        where.append("drama_id = :drama_id")
        params["drama_id"] = drama_id
    if episode_id:
        where.append("episode_id = :episode_id")
        params["episode_id"] = episode_id
    if status:
        where.append("status = :status")
        params["status"] = status
    if report_type:
        where.append("report_type = :report_type")
        params["report_type"] = report_type

    rows = fetch_all(
        db,
        "SELECT * FROM quality_reports WHERE "
        + " AND ".join(where)
        + " ORDER BY updated_at DESC, id DESC LIMIT :limit",
        params,
    )
    return [_decode_report(row) or {} for row in rows]


def get_quality_report(db: Session, report_id: int) -> dict[str, Any] | None:
    row = fetch_one(db, "SELECT * FROM quality_reports WHERE id = :id AND deleted_at IS NULL", {"id": report_id})
    return _decode_report(row)


def update_quality_report(db: Session, report_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    """更新质检报告状态。

    当前只开放少量字段，避免前端误改 workflow 归属；人工处理返工时主要修改 status 和建议。
    """
    allowed = {"status", "score", "issues", "suggestions", "raw_report"}
    updates: list[str] = ["updated_at = :updated_at"]
    params: dict[str, Any] = {"id": report_id, "updated_at": now_iso()}
    for key in allowed:
        if key not in payload:
            continue
        updates.append(f"{key} = :{key}")
        if key in {"issues", "suggestions", "raw_report"}:
            params[key] = json_dumps(payload.get(key) or ([] if key != "raw_report" else {}))
        else:
            params[key] = payload.get(key)
    if len(updates) == 1:
        return get_quality_report(db, report_id)
    db.execute(text("UPDATE quality_reports SET " + ", ".join(updates) + " WHERE id = :id"), params)
    return get_quality_report(db, report_id)


def create_quality_report(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """创建并保存一条创作质量评估报告。"""
    now = now_iso()
    score = payload.get("score")
    if score is not None:
        score = float(score)
    res = db.execute(
        text(
            """
            INSERT INTO quality_reports (
                workflow_run_id, drama_id, episode_id, report_type,
                score, status, issues, suggestions, raw_report,
                created_at, updated_at
            ) VALUES (
                :workflow_run_id, :drama_id, :episode_id, :report_type,
                :score, :status, :issues, :suggestions, :raw_report,
                :now, :now
            )
            """
        ),
        {
            "workflow_run_id": payload.get("workflow_run_id"),
            "drama_id": payload.get("drama_id"),
            "episode_id": payload.get("episode_id"),
            "report_type": payload.get("report_type") or "script_coherence",
            "score": score,
            "status": payload.get("status") or "passed",
            "issues": json_dumps(payload.get("issues") or []),
            "suggestions": json_dumps(payload.get("suggestions") or []),
            "raw_report": json_dumps(payload.get("raw_report") or {}),
            "now": now,
        },
    )
    return get_quality_report(db, res.lastrowid) or {}


def get_observability_metrics(db: Session) -> dict[str, Any]:
    """统计系统全链路可观测性指标 (Token 消耗、延迟、调用量、QA 质量评分)。"""
    # 1. 统计 prompt_runs
    prompt_stats = fetch_one(
        db,
        """
        SELECT
            COUNT(*) as total_calls,
            SUM(CASE WHEN status IN ('success', 'completed', 'completed_with_parse_warning') THEN 1 ELSE 0 END) as success_calls,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_calls,
            SUM(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)) as total_tokens,
            SUM(COALESCE(cost, 0)) as total_cost,
            AVG(latency_ms) as avg_latency_ms
        FROM prompt_runs
        WHERE deleted_at IS NULL
        """,
    ) or {}

    # 成本明细按模型和 Agent 聚合，前端可直接定位高消耗环节。
    cost_breakdown = fetch_all(
        db,
        """
        SELECT model, agent_name, COUNT(*) AS calls,
               SUM(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)) AS total_tokens,
               SUM(COALESCE(cost, 0)) AS total_cost
        FROM prompt_runs
        WHERE deleted_at IS NULL
        GROUP BY model, agent_name
        ORDER BY total_cost DESC, total_tokens DESC
        LIMIT 50
        """,
    )

    # 2. 统计 quality_reports 均分
    qa_stats = fetch_one(
        db,
        """
        SELECT
            COUNT(*) as total_reports,
            AVG(score) as avg_score,
            SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END) as passed_reports,
            SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END) as review_needed_reports
        FROM quality_reports
        WHERE deleted_at IS NULL
        """,
    ) or {}

    # 3. 统计 workflow_runs
    wf_stats = fetch_one(
        db,
        """
        SELECT
            COUNT(*) as total_workflows,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_workflows,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_workflows,
            SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as running_workflows
        FROM workflow_runs
        WHERE deleted_at IS NULL
        """,
    ) or {}

    total_calls = prompt_stats.get("total_calls") or 0
    success_calls = prompt_stats.get("success_calls") or 0
    call_success_rate = (success_calls / total_calls * 100.0) if total_calls > 0 else 100.0

    return {
        "prompts": {
            "total_calls": total_calls,
            "success_calls": success_calls,
            "failed_calls": prompt_stats.get("failed_calls") or 0,
            "success_rate": round(call_success_rate, 2),
            "total_tokens": prompt_stats.get("total_tokens") or 0,
            "total_cost": round(float(prompt_stats.get("total_cost") or 0), 6),
            "avg_latency_ms": round(float(prompt_stats.get("avg_latency_ms") or 0), 2),
            "cost_breakdown": [
                {
                    **row,
                    "total_tokens": int(row.get("total_tokens") or 0),
                    "total_cost": round(float(row.get("total_cost") or 0), 6),
                }
                for row in cost_breakdown
            ],
        },
        "quality": {
            "total_reports": qa_stats.get("total_reports") or 0,
            "avg_score": round(float(qa_stats.get("avg_score") or 0), 2),
            "passed_reports": qa_stats.get("passed_reports") or 0,
            "review_needed_reports": qa_stats.get("review_needed_reports") or 0,
        },
        "workflows": {
            "total_workflows": wf_stats.get("total_workflows") or 0,
            "completed_workflows": wf_stats.get("completed_workflows") or 0,
            "failed_workflows": wf_stats.get("failed_workflows") or 0,
            "running_workflows": wf_stats.get("running_workflows") or 0,
        },
    }
