"""短期/长期记忆服务。

当前先用 MySQL 做结构化记忆落库和 LIKE 检索；后续接 Qdrant/Chroma 时，
保留 memory_items 作为权威元数据表，embedding_ref 指向向量库记录。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso
from app.context import vector_memory_service


def add_memory_item(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ValueError("content 必填")
    now = now_iso()
    res = db.execute(
        text(
            """
            INSERT INTO memory_items (
                drama_id, episode_id, memory_type, scope, title, content, summary, keywords,
                embedding_ref, source_type, source_id, metadata, created_at, updated_at
            ) VALUES (
                :drama_id, :episode_id, :memory_type, :scope, :title, :content, :summary, :keywords,
                :embedding_ref, :source_type, :source_id, :metadata, :now, :now
            )
            """
        ),
        {
            "drama_id": payload.get("drama_id"),
            "episode_id": payload.get("episode_id"),
            "memory_type": payload.get("memory_type") or "note",
            "scope": payload.get("scope") or "drama",
            "title": payload.get("title"),
            "content": content,
            "summary": payload.get("summary"),
            "keywords": json_dumps(payload.get("keywords") or []),
            "embedding_ref": payload.get("embedding_ref"),
            "source_type": payload.get("source_type"),
            "source_id": payload.get("source_id"),
            "metadata": json_dumps(payload.get("metadata") or {}),
            "now": now,
        },
    )
    row = result_to_dict(db.execute(text("SELECT * FROM memory_items WHERE id = :id"), {"id": res.lastrowid}).first())
    try:
        # 向量索引只是增强检索能力，失败不能影响 memory_items 这条权威记忆落库。
        index_result = vector_memory_service.index_memory_item(db, row, embedding=payload.get("embedding"))
    except Exception as err:  # noqa: BLE001
        index_result = {"status": "failed", "reason": str(err)}
    row["vector_index"] = index_result
    if index_result.get("embedding_ref"):
        row["embedding_ref"] = index_result["embedding_ref"]
    return row


def search_memory_items(
    db: Session,
    *,
    drama_id: int | None = None,
    episode_id: int | None = None,
    query: str | None = None,
    query_vector: list[float] | None = None,
    memory_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """基础记忆检索；向量检索接入前先保证业务链路能跑通。"""
    if query_vector:
        vector_result = vector_memory_service.search_memory_by_vector(
            query_vector=query_vector,
            limit=limit,
            filters={"drama_id": drama_id, "episode_id": episode_id, "memory_type": memory_type},
        )
        if vector_result.get("status") == "ok":
            return _fetch_memory_items_by_ids(db, vector_result.get("ids") or [])

    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 20), 100))}
    if drama_id:
        where.append("drama_id = :drama_id")
        params["drama_id"] = drama_id
    if episode_id:
        where.append("(episode_id = :episode_id OR episode_id IS NULL)")
        params["episode_id"] = episode_id
    if memory_type:
        where.append("memory_type = :memory_type")
        params["memory_type"] = memory_type
    if query:
        where.append("(title LIKE :q OR content LIKE :q OR summary LIKE :q OR keywords LIKE :q)")
        params["q"] = f"%{query}%"
    rows = fetch_all(
        db,
        "SELECT * FROM memory_items WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC, id DESC LIMIT :limit",
        params,
    )
    for row in rows:
        row["keywords"] = json_loads(row.get("keywords"), [])
        row["metadata"] = json_loads(row.get("metadata"), {})
    return rows


def _fetch_memory_items_by_ids(db: Session, ids: list[Any]) -> list[dict[str, Any]]:
    """按向量库召回的 id 回表读取，保证 API 返回的是 MySQL 中的权威元数据。"""
    clean_ids = [item for item in ids if item not in (None, "")]
    if not clean_ids:
        return []
    params = {f"id_{idx}": item for idx, item in enumerate(clean_ids)}
    placeholders = ", ".join(f":id_{idx}" for idx in range(len(clean_ids)))
    rows = fetch_all(
        db,
        f"SELECT * FROM memory_items WHERE id IN ({placeholders}) AND deleted_at IS NULL",
        params,
    )
    order = {str(item): idx for idx, item in enumerate(clean_ids)}
    rows.sort(key=lambda row: order.get(str(row.get("id")), len(order)))
    for row in rows:
        row["keywords"] = json_loads(row.get("keywords"), [])
        row["metadata"] = json_loads(row.get("metadata"), {})
    return rows
