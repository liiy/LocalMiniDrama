"""向量记忆适配层。

当前业务仍以 memory_items 表作为权威数据源；向量库只是检索加速和语义召回层。
这样即使 Qdrant/Chroma 未部署，剧本生产链路也不会被外部基础设施阻塞。
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.platform_common import json_loads, now_iso


SUPPORTED_VECTOR_BACKENDS = {"disabled", "qdrant"}


def vector_memory_settings(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """读取向量记忆配置，并提供保守默认值。"""
    cfg = cfg or load_config()
    raw = ((cfg.get("memory") or {}).get("vector") or {}) if isinstance(cfg, dict) else {}
    backend = os.environ.get("LMD_VECTOR_MEMORY_BACKEND") or raw.get("backend") or "disabled"
    backend = str(backend).strip().lower()
    if backend not in SUPPORTED_VECTOR_BACKENDS:
        backend = "disabled"
    return {
        "backend": backend,
        "collection": os.environ.get("LMD_VECTOR_MEMORY_COLLECTION") or raw.get("collection") or "local_mini_drama_memory",
        "url": os.environ.get("LMD_QDRANT_URL") or raw.get("url") or "http://127.0.0.1:6333",
        "api_key": os.environ.get("LMD_QDRANT_API_KEY") or raw.get("api_key") or "",
        "vector_size": int(os.environ.get("LMD_VECTOR_SIZE") or raw.get("vector_size") or 1536),
        "distance": str(os.environ.get("LMD_VECTOR_DISTANCE") or raw.get("distance") or "Cosine"),
    }


def is_vector_memory_enabled(cfg: dict[str, Any] | None = None) -> bool:
    return vector_memory_settings(cfg).get("backend") != "disabled"


def build_memory_document(memory_item: dict[str, Any]) -> str:
    """把记忆记录压成适合生成 embedding 的文本。

    这里不在适配层里调用大模型生成 embedding，原因是不同项目可能使用不同 embedding 模型；
    调用方可以把生成好的 embedding 传进来，或者后续由独立 worker 批量补索引。
    """
    keywords = memory_item.get("keywords")
    if isinstance(keywords, str):
        keywords = json_loads(keywords, []) or keywords
    if isinstance(keywords, list):
        keyword_text = "，".join(str(item) for item in keywords if item)
    else:
        keyword_text = str(keywords or "")
    parts = [
        str(memory_item.get("title") or ""),
        str(memory_item.get("summary") or ""),
        str(memory_item.get("content") or ""),
        keyword_text,
    ]
    return "\n".join(part for part in parts if part.strip())


def make_embedding_ref(backend: str, collection: str, memory_id: Any) -> str:
    """生成稳定引用，保存到 memory_items.embedding_ref。"""
    return f"{backend}:{collection}:{memory_id}"


def index_memory_item(
    db: Session,
    memory_item: dict[str, Any],
    *,
    embedding: list[float] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """尝试把 memory_item 写入向量库。

    没有 embedding、没有依赖或向量库不可用时返回 skipped/unavailable，不抛错阻断主业务。
    """
    settings = vector_memory_settings(cfg)
    backend = settings["backend"]
    if backend == "disabled":
        return {"status": "skipped", "reason": "vector memory disabled"}
    if not embedding:
        return {"status": "needs_embedding", "reason": "调用方未提供 embedding 向量"}
    if backend == "qdrant":
        return _index_qdrant(db, memory_item, embedding, settings)
    return {"status": "skipped", "reason": f"unsupported backend: {backend}"}


def search_memory_by_vector(
    *,
    query_vector: list[float] | None,
    cfg: dict[str, Any] | None = None,
    limit: int = 20,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按向量检索记忆，返回 memory_item id 列表。

    业务层会再回表读取 memory_items，确保返回结构始终以 MySQL 元数据为准。
    """
    settings = vector_memory_settings(cfg)
    if settings["backend"] == "disabled":
        return {"status": "skipped", "ids": [], "reason": "vector memory disabled"}
    if not query_vector:
        return {"status": "needs_embedding", "ids": [], "reason": "缺少 query_vector"}
    if settings["backend"] == "qdrant":
        return _search_qdrant(query_vector, settings, limit=limit, filters=filters or {})
    return {"status": "skipped", "ids": [], "reason": f"unsupported backend: {settings['backend']}"}


def _index_qdrant(
    db: Session,
    memory_item: dict[str, Any],
    embedding: list[float],
    settings: dict[str, Any],
) -> dict[str, Any]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError:
        return {"status": "unavailable", "reason": "qdrant-client 未安装"}

    memory_id = memory_item.get("id")
    collection = settings["collection"]
    client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None)
    distance = getattr(Distance, str(settings.get("distance") or "Cosine").upper(), Distance.COSINE)
    # collection 不存在时自动创建；已存在时忽略异常，由 Qdrant 自身校验维度一致性。
    try:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=len(embedding), distance=distance),
        )
    except Exception:
        pass

    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lmd-memory:{memory_id}"))
    payload = {
        "memory_id": memory_id,
        "drama_id": memory_item.get("drama_id"),
        "episode_id": memory_item.get("episode_id"),
        "memory_type": memory_item.get("memory_type"),
        "scope": memory_item.get("scope"),
        "document": build_memory_document(memory_item),
    }
    client.upsert(collection_name=collection, points=[PointStruct(id=point_id, vector=embedding, payload=payload)])
    embedding_ref = make_embedding_ref("qdrant", collection, memory_id)
    db.execute(
        text("UPDATE memory_items SET embedding_ref = :ref, updated_at = :updated_at WHERE id = :id"),
        {"id": memory_id, "ref": embedding_ref, "updated_at": now_iso()},
    )
    return {"status": "indexed", "embedding_ref": embedding_ref, "point_id": point_id}


def _search_qdrant(
    query_vector: list[float],
    settings: dict[str, Any],
    *,
    limit: int,
    filters: dict[str, Any],
) -> dict[str, Any]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue
    except ImportError:
        return {"status": "unavailable", "ids": [], "reason": "qdrant-client 未安装"}

    must = []
    for key in ("drama_id", "episode_id", "memory_type", "scope"):
        value = filters.get(key)
        if value not in (None, ""):
            must.append(FieldCondition(key=key, match=MatchValue(value=value)))
    qdrant_filter = Filter(must=must) if must else None
    client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None)
    hits = client.search(
        collection_name=settings["collection"],
        query_vector=query_vector,
        query_filter=qdrant_filter,
        limit=max(1, min(int(limit or 20), 100)),
    )
    ids = [hit.payload.get("memory_id") for hit in hits if getattr(hit, "payload", None)]
    return {"status": "ok", "ids": [item for item in ids if item is not None]}


def vector_index_payload(memory_item: dict[str, Any], index_result: dict[str, Any]) -> dict[str, Any]:
    """生成可写入 metadata 的索引诊断信息，便于排查向量索引是否生效。"""
    return {
        "memory_id": memory_item.get("id"),
        "embedding_ref": index_result.get("embedding_ref") or memory_item.get("embedding_ref"),
        "vector_index_status": index_result.get("status"),
        "vector_index_reason": index_result.get("reason"),
    }
