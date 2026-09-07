"""短期/长期记忆服务。

当前先用 MySQL 做结构化记忆落库和 LIKE 检索；后续接 Qdrant/Chroma 时，
保留 memory_items 作为权威元数据表，embedding_ref 指向向量库记录。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso
from app.context import vector_memory_service


def _decode_memory(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """统一反序列化记忆 JSON 字段。"""
    if not row:
        return None
    item = dict(row)
    item["keywords"] = json_loads(item.get("keywords"), [])
    item["metadata"] = json_loads(item.get("metadata"), {})
    return item


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
                embedding_ref, source_type, source_id, metadata, status, expires_at,
                conflict_group_id, confidence, revision, manually_edited_at, created_at, updated_at
            ) VALUES (
                :drama_id, :episode_id, :memory_type, :scope, :title, :content, :summary, :keywords,
                :embedding_ref, :source_type, :source_id, :metadata, :status, :expires_at,
                :conflict_group_id, :confidence, 1, :manually_edited_at, :now, :now
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
            "status": payload.get("status") or "active",
            "expires_at": payload.get("expires_at"),
            "conflict_group_id": payload.get("conflict_group_id"),
            "confidence": max(0.0, min(float(payload.get("confidence", 1.0)), 1.0)),
            "manually_edited_at": payload.get("manually_edited_at"),
            "now": now,
        },
    )
    row = _decode_memory(result_to_dict(db.execute(text("SELECT * FROM memory_items WHERE id = :id"), {"id": res.lastrowid}).first())) or {}
    try:
        # 向量索引只是增强检索能力，失败不能影响 memory_items 这条权威记忆落库。
        index_result = vector_memory_service.index_memory_item(db, row, embedding=payload.get("embedding"))
    except Exception as err:  # noqa: BLE001
        index_result = {"status": "failed", "reason": str(err)}
    row["vector_index"] = index_result
    if index_result.get("embedding_ref"):
        row["embedding_ref"] = index_result["embedding_ref"]
    # 每次新增后做同剧小范围冲突检测，让冲突治理默认自动发生。
    conflict_result = detect_memory_conflicts(db, drama_id=row.get("drama_id"))
    refreshed = _decode_memory(fetch_one(db, "SELECT * FROM memory_items WHERE id = :id", {"id": row["id"]})) or row
    refreshed["vector_index"] = index_result
    refreshed["conflict_detection"] = conflict_result
    return refreshed


def search_memory_items(
    db: Session,
    *,
    drama_id: int | None = None,
    episode_id: int | None = None,
    query: str | None = None,
    query_vector: list[float] | None = None,
    memory_type: str | None = None,
    status: str | None = "active",
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
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 20), 100)), "now": now_iso()}
    if drama_id:
        where.append("drama_id = :drama_id")
        params["drama_id"] = drama_id
    if episode_id:
        where.append("(episode_id = :episode_id OR episode_id IS NULL)")
        params["episode_id"] = episode_id
    if memory_type:
        where.append("memory_type = :memory_type")
        params["memory_type"] = memory_type
    if status and status != "all":
        where.append("status = :status")
        params["status"] = status
        if status == "active":
            where.append("(expires_at IS NULL OR expires_at = '' OR expires_at > :now)")
    if query:
        where.append("(title LIKE :q OR content LIKE :q OR summary LIKE :q OR keywords LIKE :q)")
        params["q"] = f"%{query}%"
    rows = fetch_all(
        db,
        "SELECT * FROM memory_items WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC, id DESC LIMIT :limit",
        params,
    )
    return [_decode_memory(row) or {} for row in rows]


def _fetch_memory_items_by_ids(db: Session, ids: list[Any]) -> list[dict[str, Any]]:
    """按向量库召回的 id 回表读取，保证 API 返回的是 MySQL 中的权威元数据。"""
    clean_ids = [item for item in ids if item not in (None, "")]
    if not clean_ids:
        return []
    params = {f"id_{idx}": item for idx, item in enumerate(clean_ids)}
    placeholders = ", ".join(f":id_{idx}" for idx in range(len(clean_ids)))
    rows = fetch_all(
        db,
        f"SELECT * FROM memory_items WHERE id IN ({placeholders}) AND deleted_at IS NULL "
        "AND status = 'active' AND (expires_at IS NULL OR expires_at = '' OR expires_at > :now)",
        {**params, "now": now_iso()},
    )
    order = {str(item): idx for idx, item in enumerate(clean_ids)}
    rows.sort(key=lambda row: order.get(str(row.get("id")), len(order)))
    return [_decode_memory(row) or {} for row in rows]


def update_memory_item(db: Session, memory_id: int, payload: dict[str, Any], *, editor: str = "human") -> dict[str, Any] | None:
    """人工修订记忆，并递增版本号、记录修订者和时间。"""
    current = fetch_one(db, "SELECT * FROM memory_items WHERE id = :id AND deleted_at IS NULL", {"id": memory_id})
    if not current:
        return None
    allowed = {"title", "content", "summary", "memory_type", "scope", "status", "expires_at", "confidence"}
    updates = {key: payload.get(key) for key in allowed if key in payload}
    if "content" in updates and not str(updates["content"] or "").strip():
        raise ValueError("content 不能为空")
    if "confidence" in updates:
        updates["confidence"] = max(0.0, min(float(updates["confidence"]), 1.0))
    if "keywords" in payload:
        updates["keywords"] = json_dumps(payload.get("keywords") or [])
    conflict_group_id = current.get("conflict_group_id")
    if conflict_group_id and payload.get("status") == "active":
        # 人工选中当前事实即完成冲突裁决，其余候选保留但退出召回。
        db.execute(
            text("UPDATE memory_items SET status = 'disabled', updated_at = :now "
                 "WHERE conflict_group_id = :group_id AND id != :id AND deleted_at IS NULL"),
            {"group_id": conflict_group_id, "id": memory_id, "now": now_iso()},
        )
        updates["conflict_group_id"] = None
    metadata = json_loads(current.get("metadata"), {}) or {}
    metadata["last_editor"] = editor
    metadata["manual_revision_note"] = str(payload.get("revision_note") or "")
    updates.update({"metadata": json_dumps(metadata), "revision": int(current.get("revision") or 1) + 1, "manually_edited_at": now_iso(), "updated_at": now_iso()})
    # 内容变化后旧向量已失效，清空引用等待异步重建。
    if any(key in payload for key in ("content", "summary", "keywords", "title")):
        updates["embedding_ref"] = None
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    db.execute(text(f"UPDATE memory_items SET {assignments} WHERE id = :id"), {**updates, "id": memory_id})
    return _decode_memory(fetch_one(db, "SELECT * FROM memory_items WHERE id = :id", {"id": memory_id}))


def distill_memory_items(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """从原始文本或已有记忆自动提炼一条高密度长期记忆。"""
    source_ids = [int(item) for item in payload.get("source_ids") or []]
    sources = _fetch_memory_items_by_ids(db, source_ids) if source_ids else []
    raw_text = str(payload.get("content") or "").strip() or "\n".join(str(item.get("content") or "") for item in sources)
    if not raw_text:
        raise ValueError("content 或 source_ids 至少提供一项")
    compact = re.sub(r"\s+", " ", raw_text).strip()
    sentences = [item.strip() for item in re.split(r"(?<=[。！？!?])", compact) if item.strip()]
    summary = "".join(sentences[:3])[:500]
    keywords = payload.get("keywords") or list(dict.fromkeys(re.findall(r"[\u4e00-\u9fff]{2,6}", summary)))[:12]
    item = add_memory_item(db, {
        **payload,
        "content": compact,
        "summary": payload.get("summary") or summary,
        "keywords": keywords,
        "memory_type": payload.get("memory_type") or "distilled",
        "source_type": payload.get("source_type") or "auto_distillation",
        "metadata": {**(payload.get("metadata") or {}), "source_memory_ids": source_ids, "distillation_method": "extractive_v1"},
        "confidence": payload.get("confidence", 0.8),
    })
    return {"status": "created", "item": item, "source_count": len(sources)}


def detect_memory_conflicts(db: Session, *, drama_id: int | None = None) -> dict[str, Any]:
    """检测同一作用域和标题下内容不一致的活跃记忆，并写入冲突组。"""
    where = "deleted_at IS NULL AND status IN ('active', 'conflict')"
    params: dict[str, Any] = {}
    if drama_id:
        where += " AND drama_id = :drama_id"
        params["drama_id"] = drama_id
    rows = fetch_all(db, f"SELECT * FROM memory_items WHERE {where} ORDER BY id", params)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row.get("drama_id"), row.get("episode_id"), row.get("memory_type"), row.get("scope"), str(row.get("title") or "").strip())
        groups.setdefault(key, []).append(row)
    conflicts = []
    for key, items in groups.items():
        normalized = {re.sub(r"\s+", "", str(item.get("content") or "")) for item in items}
        if len(items) < 2 or len(normalized) < 2:
            continue
        group_id = next((item.get("conflict_group_id") for item in items if item.get("conflict_group_id")), None) or f"memconf_{uuid.uuid4().hex[:16]}"
        ids = [int(item["id"]) for item in items]
        placeholders = ",".join(f":id{i}" for i in range(len(ids)))
        db.execute(text(f"UPDATE memory_items SET status = 'conflict', conflict_group_id = :group_id, updated_at = :now WHERE id IN ({placeholders})"), {"group_id": group_id, "now": now_iso(), **{f"id{i}": value for i, value in enumerate(ids)}})
        conflicts.append({"conflict_group_id": group_id, "memory_ids": ids, "key": list(key)})
    return {"status": "completed", "conflict_count": len(conflicts), "groups": conflicts}


def expire_memory_items(db: Session, *, as_of: str | None = None) -> dict[str, Any]:
    """把达到过期时间的活跃记忆标记为 expired，保留审计记录。"""
    cutoff = as_of or datetime.now(timezone.utc).isoformat()
    result = db.execute(text("UPDATE memory_items SET status = 'expired', updated_at = :now WHERE deleted_at IS NULL AND status = 'active' AND expires_at IS NOT NULL AND expires_at != '' AND expires_at <= :cutoff"), {"cutoff": cutoff, "now": now_iso()})
    return {"status": "completed", "expired_count": int(result.rowcount or 0), "as_of": cutoff}


def evaluate_retrieval(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """用期望记忆 ID 评估一次向量或关键词召回的 Precision、Recall 与 MRR。"""
    expected = [str(item) for item in payload.get("expected_ids") or []]
    if not expected:
        raise ValueError("expected_ids 必填")
    results = search_memory_items(db, drama_id=payload.get("drama_id"), episode_id=payload.get("episode_id"), query=payload.get("query"), query_vector=payload.get("query_vector"), memory_type=payload.get("memory_type"), limit=payload.get("limit") or 20)
    retrieved = [str(item.get("id")) for item in results]
    hits = [item for item in retrieved if item in set(expected)]
    first_rank = next((index + 1 for index, item in enumerate(retrieved) if item in set(expected)), None)
    return {"retrieved_ids": retrieved, "expected_ids": expected, "hit_count": len(hits), "precision": round(len(hits) / len(retrieved), 4) if retrieved else 0.0, "recall": round(len(hits) / len(expected), 4), "mrr": round(1 / first_rank, 4) if first_rank else 0.0}
