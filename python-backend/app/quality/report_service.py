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
