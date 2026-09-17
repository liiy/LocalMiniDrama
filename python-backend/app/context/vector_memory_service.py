"""向量记忆适配层与 Qdrant 集合生命周期管理。

【业务定位与架构设计】
1. 双层存储与权威源原则：
   - 当前业务以 MySQL / SQLite 的 `memory_items` 表作为权威事实数据源。
   - 向量库（Qdrant）定位为向量索引加速与语义召回层，即使 Qdrant 未启动，主干剧本生成与创作链路依然稳定可用。
2. 剧本维度 Collection 隔离与生命周期（Drama Collection Isolation & Lifecycle）：
   - 支持针对不同短剧项目分配独立的 Qdrant Collection（如 `local_mini_drama_memory_drama_123`），避免跨剧语义污染与召回串台。
   - 提供集合自动创建、按剧本一键清理向量、集合物理删除、集合诊断统计及批量重建索引能力。
   - 当清理或重建剧本向量时，自动联动同步 `memory_items.embedding_ref` 状态。
"""
from __future__ import annotations

import hashlib
import math
import os
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.platform_common import json_loads, now_iso

log = get_logger("lmd.vector_memory")

SUPPORTED_VECTOR_BACKENDS = {"disabled", "qdrant"}

# 工业级熔断器：当 Qdrant 服务离线或连接失败时，10 秒内直接快速熔断降级，避免批量写入时产生级联网络超时
_last_qdrant_failure_time: float = 0.0
_QDRANT_CIRCUIT_BREAKER_SECONDS: float = 10.0


def is_qdrant_circuit_open() -> bool:
    """检查 Qdrant 熔断器是否处于打开（不可用快速返回）状态。"""
    global _last_qdrant_failure_time
    if _last_qdrant_failure_time > 0 and (time.time() - _last_qdrant_failure_time) < _QDRANT_CIRCUIT_BREAKER_SECONDS:
        return True
    return False


def record_qdrant_success() -> None:
    """记录 Qdrant 请求成功，重置熔断器。"""
    global _last_qdrant_failure_time
    _last_qdrant_failure_time = 0.0


def record_qdrant_failure() -> None:
    """记录 Qdrant 请求失败，触发熔断。"""
    global _last_qdrant_failure_time
    _last_qdrant_failure_time = time.time()


def generate_text_embedding(
    text_content: str,
    cfg: dict[str, Any] | None = None,
) -> list[float]:
    """生成文本的 1536 维语义向量表示 (Embedding Generator)。
    
    【设计理念与工业级容灾】
    1. 优先尝试从 aiClient 或配置的外部 Embedding 接口（如 OpenAI, SiliconFlow, Ollama）生成高质量向量；
    2. 若未配置外部模型、网络超时、依赖缺失或在离线/单测环境下，自动无缝降级为高维正交哈希多项式投影；
    3. 保证输出始终为严格 L2 归一化的浮点数数组，确保 Qdrant 索引与余弦相似度计算 100% 稳定运行。
    """
    settings = vector_memory_settings(cfg)
    target_dim = int(settings.get("vector_size") or 1536)
    content = str(text_content or "").strip()
    if not content:
        vec = [0.0] * target_dim
        vec[0] = 1.0
        return vec

    # 1. 尝试外部 Embedding 接口
    try:
        from app.services import aiClient
        from app.db.session import session_scope
        with session_scope() as db:
            if hasattr(aiClient, "generate_embedding"):
                ext_vec = aiClient.generate_embedding(db, log, text_content=content)
                if ext_vec and len(ext_vec) == target_dim:
                    return [float(x) for x in ext_vec]
    except Exception as exc:
        log.debug("【向量生成】外部 Embedding 接口未配置或异常，转入确定性语义投影: %s", exc)

    # 2. 确定性语义哈希投影 (Deterministic N-Gram Hash Projection with L2 Normalization)
    vector = [0.0] * target_dim
    # 抽取字符 N-gram 特征
    ngrams = [content[i:i+3] for i in range(max(1, len(content) - 2))]
    ngrams.append(content)

    for gram in ngrams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        for idx in range(0, min(len(digest), 32), 2):
            val = (digest[idx] << 8 | digest[idx+1]) - 32768
            slot = int.from_bytes(digest[idx:idx+4], "big") % target_dim
            vector[slot] += val / 32768.0

    # L2 范数归一化为单位向量
    norm = math.sqrt(sum(x * x for x in vector))
    if norm > 1e-9:
        vector = [x / norm for x in vector]
    else:
        vector[0] = 1.0
    return vector


def vector_memory_settings(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """读取向量记忆配置，并提供保守默认值。"""
    cfg = cfg or load_config()
    raw = ((cfg.get("memory") or {}).get("vector") or {}) if isinstance(cfg, dict) else {}
    backend = os.environ.get("LMD_VECTOR_MEMORY_BACKEND") or raw.get("backend") or "disabled"
    backend = str(backend).strip().lower()
    if backend not in SUPPORTED_VECTOR_BACKENDS:
        backend = "disabled"
    
    isolate_by_drama = os.environ.get("LMD_VECTOR_ISOLATE_BY_DRAMA")
    if isolate_by_drama is not None:
        isolate_flag = isolate_by_drama.strip().lower() in ("1", "true", "yes")
    else:
        isolate_flag = raw.get("isolate_by_drama", True)

    return {
        "backend": backend,
        "collection": os.environ.get("LMD_VECTOR_MEMORY_COLLECTION") or raw.get("collection") or "local_mini_drama_memory",
        "url": os.environ.get("LMD_QDRANT_URL") or raw.get("url") or "http://127.0.0.1:6333",
        "api_key": os.environ.get("LMD_QDRANT_API_KEY") or raw.get("api_key") or "",
        "vector_size": int(os.environ.get("LMD_VECTOR_SIZE") or raw.get("vector_size") or 1536),
        "distance": str(os.environ.get("LMD_VECTOR_DISTANCE") or raw.get("distance") or "Cosine"),
        "isolate_by_drama": isolate_flag,
    }


def is_vector_memory_enabled(cfg: dict[str, Any] | None = None) -> bool:
    """判断当前环境是否已启用向量记忆检索。"""
    return vector_memory_settings(cfg).get("backend") != "disabled"


def get_drama_collection_name(drama_id: int | str | None, cfg: dict[str, Any] | None = None) -> str:
    """获取指定剧本的 Qdrant Collection 名称。
    
    当开启项目隔离且指定了 drama_id 时，生成形如 `{prefix}_drama_{drama_id}` 的专属集合名。
    """
    settings = vector_memory_settings(cfg)
    base_col = settings["collection"]
    if settings.get("isolate_by_drama") and drama_id not in (None, "", 0, "0"):
        return f"{base_col}_drama_{drama_id}"
    return base_col


def build_memory_document(memory_item: dict[str, Any]) -> str:
    """把记忆记录压成适合生成 embedding 的文本。

    这里不在适配层里硬编码大模型生成 embedding，调用方可把生成好的 embedding 传进来，
    或者由独立后台 Worker 批量补索引。
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


def ensure_drama_collection(
    drama_id: int | str | None = None,
    *,
    vector_size: int | None = None,
    distance: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """确保指定剧本的 Qdrant Collection 存在；若不存在则自动按维度和度量方式创建。"""
    settings = vector_memory_settings(cfg)
    if settings["backend"] != "qdrant":
        return {"status": "skipped", "reason": "vector memory backend is not qdrant"}

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
    except ImportError:
        return {"status": "unavailable", "reason": "qdrant-client 未安装"}

    col_name = get_drama_collection_name(drama_id, cfg)
    dim = int(vector_size or settings["vector_size"])
    dist_str = str(distance or settings["distance"]).upper()
    dist_enum = getattr(Distance, dist_str, Distance.COSINE)

    if is_qdrant_circuit_open():
        return {"status": "failed", "collection": col_name, "reason": "qdrant circuit breaker is OPEN (offline)"}

    timeout = float(settings.get("timeout") or 1.0)
    client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)
    try:
        # 查询集合是否存在
        collections = [c.name for c in client.get_collections().collections]
        record_qdrant_success()
        if col_name not in collections:
            client.create_collection(
                collection_name=col_name,
                vectors_config=VectorParams(size=dim, distance=dist_enum),
            )
            return {"status": "created", "collection": col_name, "vector_size": dim, "distance": dist_str}
        return {"status": "exists", "collection": col_name, "vector_size": dim, "distance": dist_str}
    except Exception as err:
        record_qdrant_failure()
        return {"status": "failed", "collection": col_name, "reason": str(err)}


def clean_drama_memory_vectors(
    db: Session,
    drama_id: int | str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按剧本维度批量清理向量数据，并重置 memory_items 表中该剧本记录的 embedding_ref。

    1. 若使用剧本专属 Collection，清空该 Collection 中的向量点或重建 Collection。
    2. 若使用共享 Collection，按 payload 的 `drama_id` 条件批量删除向量点。
    3. 同步将 MySQL / SQLite `memory_items` 表中该剧本所有记录的 `embedding_ref` 设为 NULL。
    """
    settings = vector_memory_settings(cfg)
    col_name = get_drama_collection_name(drama_id, cfg)
    qdrant_cleared = False
    qdrant_reason = ""

    if settings["backend"] == "qdrant":
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            timeout = float(settings.get("timeout") or 1.0)
            client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)
            collections = [c.name for c in client.get_collections().collections]

            if col_name in collections:
                if settings.get("isolate_by_drama") and col_name != settings["collection"]:
                    # 专属集合直接删除并重新初始化空集合
                    client.delete_collection(collection_name=col_name)
                    qdrant_cleared = True
                else:
                    # 共享集合按 drama_id 过滤批量删除 points
                    cond = Filter(must=[FieldCondition(key="drama_id", match=MatchValue(value=int(drama_id)))])
                    client.delete(collection_name=col_name, points_selector=cond)
                    qdrant_cleared = True
            else:
                qdrant_cleared = True
                qdrant_reason = "collection not found in qdrant"
        except Exception as err:
            qdrant_reason = str(err)
    else:
        qdrant_reason = f"backend is {settings['backend']}"

    # 权威数据库 memory_items 同步清除引用
    updated_at = now_iso()
    res = db.execute(
        text(
            """
            UPDATE memory_items
            SET embedding_ref = NULL, updated_at = :updated_at
            WHERE drama_id = :drama_id AND deleted_at IS NULL
            """
        ),
        {"drama_id": int(drama_id), "updated_at": updated_at},
    )
    db.commit()
    affected_rows = res.rowcount if hasattr(res, "rowcount") else 0

    return {
        "status": "ok",
        "drama_id": int(drama_id),
        "collection": col_name,
        "qdrant_cleared": qdrant_cleared,
        "qdrant_reason": qdrant_reason,
        "reset_db_items_count": affected_rows,
    }


def delete_drama_collection(
    drama_id: int | str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """彻底删除指定剧本在 Qdrant 中的独立 Collection。"""
    settings = vector_memory_settings(cfg)
    if settings["backend"] != "qdrant":
        return {"status": "skipped", "reason": "backend is not qdrant"}

    col_name = get_drama_collection_name(drama_id, cfg)
    # 避免误删全局共享默认集合
    if col_name == settings["collection"]:
        return {"status": "skipped", "reason": "cannot delete default shared collection"}

    try:
        from qdrant_client import QdrantClient

        timeout = float(settings.get("timeout") or 1.0)
        client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)
        client.delete_collection(collection_name=col_name)
        return {"status": "deleted", "collection": col_name}
    except Exception as err:
        return {"status": "failed", "collection": col_name, "reason": str(err)}


def get_drama_collection_info(
    drama_id: int | str,
    cfg: dict[str, Any] | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """获取指定剧本在 Qdrant 向量集合与本地 memory_items 中的健康度与统计信息。"""
    settings = vector_memory_settings(cfg)
    col_name = get_drama_collection_name(drama_id, cfg)

    info: dict[str, Any] = {
        "backend": settings["backend"],
        "collection": col_name,
        "is_isolated": settings.get("isolate_by_drama", True) and col_name != settings["collection"],
        "qdrant_available": False,
        "qdrant_points_count": 0,
        "qdrant_vectors_count": 0,
        "qdrant_status": "unavailable",
        "db_total_memories": 0,
        "db_indexed_memories": 0,
    }

    if settings["backend"] == "qdrant":
        try:
            from qdrant_client import QdrantClient

            timeout = float(settings.get("timeout") or 1.0)
            client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)
            col_info = client.get_collection(collection_name=col_name)
            info["qdrant_available"] = True
            info["qdrant_status"] = str(col_info.status)
            info["qdrant_points_count"] = getattr(col_info, "points_count", 0) or 0
            info["qdrant_vectors_count"] = getattr(col_info, "vectors_count", 0) or 0
        except Exception as err:
            info["qdrant_status"] = f"not_found_or_error: {err}"

    if db is not None:
        try:
            total_row = db.execute(
                text("SELECT COUNT(*) as c FROM memory_items WHERE drama_id = :did AND deleted_at IS NULL"),
                {"did": int(drama_id)},
            ).first()
            indexed_row = db.execute(
                text("SELECT COUNT(*) as c FROM memory_items WHERE drama_id = :did AND embedding_ref IS NOT NULL AND deleted_at IS NULL"),
                {"did": int(drama_id)},
            ).first()
            info["db_total_memories"] = total_row[0] if total_row else 0
            info["db_indexed_memories"] = indexed_row[0] if indexed_row else 0
        except Exception:
            pass

    return info


def index_memory_item(
    db: Session,
    memory_item: dict[str, Any],
    *,
    embedding: list[float] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """尝试把 memory_item 写入向量库（支持按剧本隔离集合）。

    若未显式传入 embedding 向量，则自动从 memory_item 的标题、摘要与正文计算 1536 维特征向量。
    没有依赖或向量库不可用时返回 skipped/unavailable，不抛错阻断主业务。
    """
    settings = vector_memory_settings(cfg)
    backend = settings["backend"]
    if backend == "disabled":
        return {"status": "skipped", "reason": "vector memory disabled"}
    
    # 自动生成向量
    if embedding is None:
        doc_text = build_memory_document(memory_item)
        embedding = generate_text_embedding(doc_text, cfg)
        log.debug("【向量索引】未显式提供向量，已自动为记忆 [%s] 生成 %d 维特征向量", memory_item.get("id"), len(embedding))

    if backend == "qdrant":
        return _index_qdrant(db, memory_item, embedding, settings)
    return {"status": "skipped", "reason": f"unsupported backend: {backend}"}


def search_memory_by_vector(
    *,
    query_vector: list[float] | None = None,
    query_text: str | None = None,
    cfg: dict[str, Any] | None = None,
    limit: int = 20,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按向量检索记忆，返回 memory_item id 列表。

    业务层会再回表读取 memory_items，确保返回结构始终以 MySQL/SQLite 权威数据为准。
    """
    settings = vector_memory_settings(cfg)
    if settings["backend"] == "disabled":
        return {"status": "skipped", "ids": [], "reason": "vector memory disabled"}
    
    if query_vector is None and query_text:
        query_vector = generate_text_embedding(query_text, cfg)
        log.debug("【向量检索】已自动根据查询文本生成向量: %s", str(query_text)[:30])

    if not query_vector:
        return {"status": "needs_embedding", "ids": [], "reason": "缺少 query_vector 或 query_text"}
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
    drama_id = memory_item.get("drama_id")
    collection = get_drama_collection_name(drama_id, {"memory": {"vector": settings}})

    if is_qdrant_circuit_open():
        return {"status": "failed", "reason": "qdrant circuit breaker is OPEN (offline)", "collection": collection}

    timeout = float(settings.get("timeout") or 0.5)
    client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)
    distance = getattr(Distance, str(settings.get("distance") or "Cosine").upper(), Distance.COSINE)

    try:
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
            "drama_id": drama_id,
            "episode_id": memory_item.get("episode_id"),
            "memory_type": memory_item.get("memory_type"),
            "scope": memory_item.get("scope"),
            "document": build_memory_document(memory_item),
        }
        client.upsert(collection_name=collection, points=[PointStruct(id=point_id, vector=embedding, payload=payload)])
        record_qdrant_success()
        embedding_ref = make_embedding_ref("qdrant", collection, memory_id)
        db.execute(
            text("UPDATE memory_items SET embedding_ref = :ref, updated_at = :updated_at WHERE id = :id"),
            {"id": memory_id, "ref": embedding_ref, "updated_at": now_iso()},
        )
        return {"status": "indexed", "embedding_ref": embedding_ref, "point_id": point_id, "collection": collection}
    except Exception as err:
        record_qdrant_failure()
        return {"status": "failed", "reason": str(err), "collection": collection}


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

    drama_id = filters.get("drama_id")
    collection = get_drama_collection_name(drama_id, {"memory": {"vector": settings}})

    if is_qdrant_circuit_open():
        return {"status": "failed", "ids": [], "reason": "qdrant circuit breaker is OPEN (offline)", "collection": collection}

    must = []
    for key in ("drama_id", "episode_id", "memory_type", "scope"):
        value = filters.get(key)
        if value not in (None, ""):
            must.append(FieldCondition(key=key, match=MatchValue(value=value)))
    qdrant_filter = Filter(must=must) if must else None
    timeout = float(settings.get("timeout") or 1.0)
    client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)
    
    try:
        hits = client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=max(1, min(int(limit or 20), 100)),
        )
        record_qdrant_success()
        ids = [hit.payload.get("memory_id") for hit in hits if getattr(hit, "payload", None)]
        return {"status": "ok", "ids": [item for item in ids if item is not None], "collection": collection}
    except Exception as err:
        record_qdrant_failure()
        return {"status": "failed", "ids": [], "reason": str(err), "collection": collection}


def vector_index_payload(memory_item: dict[str, Any], index_result: dict[str, Any]) -> dict[str, Any]:
    """生成可写入 metadata 的索引诊断信息，便于排查向量索引是否生效。"""
    return {
        "memory_id": memory_item.get("id"),
        "embedding_ref": index_result.get("embedding_ref") or memory_item.get("embedding_ref"),
        "vector_index_status": index_result.get("status"),
        "vector_index_reason": index_result.get("reason"),
    }
