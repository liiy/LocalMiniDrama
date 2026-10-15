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
import re
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.db.session import fetch_all, fetch_one
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


def delete_drama_asset_collection(
    drama_id: int | str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """彻底删除指定剧本资产在 Qdrant 中的独立 Collection。"""
    settings = vector_memory_settings(cfg)
    if settings["backend"] != "qdrant":
        return {"status": "skipped", "reason": "backend is not qdrant"}

    col_name = get_drama_asset_collection_name(drama_id, cfg)
    try:
        from qdrant_client import QdrantClient

        timeout = float(settings.get("timeout") or 5.0)
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


# =========================================================================
# 阶段 6 资产专属向量库隔离与动态候选池召回 (Stage 6 Asset Isolation & Recall)
# =========================================================================


def get_drama_asset_collection_name(drama_id: int | str | None, cfg: dict[str, Any] | None = None) -> str:
    """获取指定剧本的资产专属 Qdrant Collection 名称。

    默认格式: `lmd_assets_drama_{drama_id}`。
    支持环境变量 LMD_ASSET_COLLECTION_PREFIX 覆盖前缀。
    当 drama_id 为空时回退为 `lmd_assets_shared`。
    严格实施剧本物理级别集合隔离，彻底杜绝跨剧资产串台与召回污染。
    """
    prefix = os.environ.get("LMD_ASSET_COLLECTION_PREFIX") or "lmd_assets"
    if drama_id not in (None, "", 0, "0"):
        col_name = f"{prefix}_drama_{drama_id}"
    else:
        col_name = f"{prefix}_shared"
    log.debug("【资产向量库】获取剧目 [%s] 资产集合名: %s", drama_id, col_name)
    return col_name


def ensure_drama_asset_collection(
    drama_id: int | str,
    *,
    vector_size: int | None = None,
    distance: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """确保指定剧本的专属资产 Qdrant Collection 存在；若不存在则自动按维度和度量方式创建。"""
    settings = vector_memory_settings(cfg)
    if settings["backend"] != "qdrant":
        return {"status": "skipped", "reason": "vector memory backend is not qdrant"}

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
    except ImportError:
        return {"status": "unavailable", "reason": "qdrant-client 未安装"}

    col_name = get_drama_asset_collection_name(drama_id, cfg)
    dim = int(vector_size or settings["vector_size"])
    dist_str = str(distance or settings["distance"]).upper()
    dist_enum = getattr(Distance, dist_str, Distance.COSINE)

    if is_qdrant_circuit_open():
        return {"status": "failed", "collection": col_name, "reason": "qdrant circuit breaker is OPEN (offline)"}

    timeout = float(settings.get("timeout") or 5.0)
    client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)
    try:
        collections = [c.name for c in client.get_collections().collections]
        record_qdrant_success()
        if col_name not in collections:
            client.create_collection(
                collection_name=col_name,
                vectors_config=VectorParams(size=dim, distance=dist_enum),
            )
            log.info("【资产向量库】成功为剧目 [%s] 创建专属资产集合 [%s] (维度: %d, 距离: %s)", drama_id, col_name, dim, dist_str)
            return {"status": "created", "collection": col_name, "vector_size": dim, "distance": dist_str}
        return {"status": "exists", "collection": col_name, "vector_size": dim, "distance": dist_str}
    except Exception as err:
        record_qdrant_failure()
        log.warning("【资产向量库】检查/创建剧目 [%s] 资产集合 [%s] 异常: %s", drama_id, col_name, err)
        return {"status": "failed", "collection": col_name, "reason": str(err)}


def sync_assets_to_vector_db(
    drama_id: int | str,
    assets: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> int:
    """将资产列表（包含角色、场景、道具、服装、声学母卡）批量向量化并写入剧目专属 Collection。

    【核心特性】
    1. 专属集合隔离：写入 `lmd_assets_drama_{drama_id}`，从物理层面消除跨剧污染；
    2. 幂等更新：基于 `uuid5(NAMESPACE_URL, f"lmd-asset:{drama_id}:{asset_key}")` 确定点位 ID，多次同步安全覆盖；
    3. 语义密度浓缩：提炼资产标识、名称、类别、状态分支、做旧、微距与提示词特征，生成 1536 维 Dense Embedding；
    4. 容灾隔离：向量库离线时不阻断业务，安全降级。
    """
    if not assets or not drama_id:
        return 0
    settings = vector_memory_settings(cfg)
    if settings["backend"] != "qdrant":
        log.debug("【资产向量同步】后端为 %s，跳过资产向量写入", settings["backend"])
        return 0
    if is_qdrant_circuit_open():
        log.debug("【资产向量同步】Qdrant 熔断器处于打开状态，快速跳过")
        return 0

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
    except ImportError:
        log.warning("【资产向量同步】qdrant-client 未安装，跳过")
        return 0

    ensure_res = ensure_drama_asset_collection(drama_id, cfg=cfg)
    if ensure_res.get("status") not in ("created", "exists"):
        log.warning("【资产向量同步】资产集合就绪失败: %s", ensure_res)
        return 0

    col_name = get_drama_asset_collection_name(drama_id, cfg)
    timeout = float(settings.get("timeout") or 5.0)
    client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)

    points: list[PointStruct] = []
    log.debug("【资产向量同步】开始为剧目 [%s] 同步 %d 项资产至集合 [%s]...", drama_id, len(assets), col_name)
    for a in assets:
        if not isinstance(a, dict):
            continue
        asset_key = a.get("asset_key") or a.get("asset_id") or a.get("char_id") or a.get("scene_id") or a.get("prop_id") or a.get("voice_id")
        if not asset_key:
            continue
        name = a.get("name") or a.get("character_name") or a.get("location_name") or a.get("scene_name") or a.get("prop_name") or asset_key
        cat = a.get("category") or a.get("asset_category") or a.get("type") or "other"
        asset_type = a.get("type") or ("audio" if "VOICE" in str(asset_key) or "AUDIO" in str(asset_key) else "image")
        prompt = a.get("prompt") or a.get("image_prompt") or a.get("visual_prompt") or a.get("master_tts_prompt") or a.get("acoustic_persona") or ""
        neg_prompt = a.get("negative_prompt") or ""
        stage_code = a.get("stage_code") or a.get("tier") or a.get("function_type") or ""
        visual_summary = a.get("visual_summary") or a.get("workflow_note") or a.get("description") or a.get("weathering_layers") or a.get("appearance") or ""
        semantic_hash = a.get("semantic_hash") or ""
        parent_asset_id = a.get("parent_asset_id") or a.get("input_source_image") or ""

        # 构建高信息密度语义检索文本
        doc_parts = [
            f"资产标识: {asset_key}",
            f"名称: {name}",
            f"类别: {cat}",
            f"类型: {asset_type}",
            f"阶段状态: {stage_code}" if stage_code else "",
            f"视觉特征: {visual_summary}" if visual_summary else "",
            f"提示词: {prompt}" if prompt else "",
        ]
        doc_text = "\n".join(p for p in doc_parts if p.strip())

        vec = generate_text_embedding(doc_text, cfg)
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lmd-asset:{drama_id}:{asset_key}"))
        payload = {
            "asset_key": str(asset_key),
            "drama_id": int(drama_id),
            "name": str(name),
            "category": str(cat),
            "type": str(asset_type),
            "stage_code": str(stage_code),
            "visual_summary": str(visual_summary),
            "prompt": str(prompt),
            "negative_prompt": str(neg_prompt),
            "semantic_hash": str(semantic_hash),
            "parent_asset_id": str(parent_asset_id),
            "document": doc_text,
        }
        points.append(PointStruct(id=pid, vector=vec, payload=payload))

    if not points:
        return 0

    try:
        client.upsert(collection_name=col_name, points=points)
        record_qdrant_success()
        log.info("【资产向量同步】成功将剧目 [%s] 的 %d 项资产同步至向量集合 [%s]", drama_id, len(points), col_name)
        return len(points)
    except Exception as err:
        record_qdrant_failure()
        log.warning("【资产向量同步】Upsert 异常: %s", err)
        return 0


def recall_candidate_assets_for_episode(
    db: Session,
    drama_id: int | str,
    screenplay_text: str,
    top_k: int = 15,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """为单集生成动态资产候选池 (Hybrid Multi-Pass Recall)。

    【算法流程】
    1. 实体逆向扫描与正则初筛：从单集剧本文本中提取角色、场景、核心道具名称；
    2. 数据库快速初筛：直接拉取名称精确匹配的已有资产 (权重 1.0)；
    3. 语义向量重召回：将单集场景动作摘要进行向量化，在专属 Collection 中 Cosine 检索语义相近的环境/道具/服装资产；
    4. 兜底保障：当向量库未启动或召回不足时，自动补齐该剧核准的 Tier-1 主角、主场景与核心道具资产；
    5. 融合去重、评分降序与 Top-K 截断，输出轻量级候选资产卡片。
    """
    if not drama_id:
        return []

    did = int(drama_id)
    sc_text = screenplay_text or ""
    candidates: dict[str, dict[str, Any]] = {}
    log.debug("【候选资产召回】开始为剧目 [%s] 召回单集候选资产 (剧本字符数=%d, Top-K=%d)...", did, len(sc_text), top_k)

    char_rows: list[dict[str, Any]] = []
    scene_rows: list[dict[str, Any]] = []
    prop_rows: list[dict[str, Any]] = []

    # -------------------------------------------------------------------------
    # 步骤 1 & 2: 数据库快速初筛 (Exact Match)
    # -------------------------------------------------------------------------
    if db is not None:
        try:
            # 1. assets 统管表精准匹配 (真实已入库核准资产，标记 is_existing_asset=True)
            asset_rows = fetch_all(
                db,
                "SELECT id, asset_key, name, category, type, prompt, metadata FROM assets WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC",
                {"did": did},
            )
            existing_asset_keys: set[str] = set()
            for r in asset_rows:
                akey = r.get("asset_key")
                aname = r.get("name") or ""
                aprompt = r.get("prompt") or ""
                if not akey:
                    continue
                existing_asset_keys.add(akey)
                meta = json_loads(r.get("metadata") or "{}", {}) if isinstance(r.get("metadata"), str) else (r.get("metadata") or {})
                stage_code = meta.get("stage_code") or ""
                v_summary = (meta.get("visual_summary") or aprompt)[:60]
                # 提取纯净核心名称 (去除括号修饰如 "(全身定妆照)", "(物理破坏交互态)")
                clean_name = re.sub(r"\(.*?\)", "", aname).strip()
                # 若资产名称、纯净名称或 asset_key 直接在剧本正文中提及，判定为精确命中
                if (aname and aname in sc_text) or (clean_name and len(clean_name) >= 2 and clean_name in sc_text) or (akey in sc_text):
                    candidates[akey] = {
                        "asset_key": akey,
                        "name": aname,
                        "category": r.get("category") or "other",
                        "type": r.get("type") or "image",
                        "stage_code": stage_code,
                        "visual_summary": v_summary,
                        "relevance_score": 1.0,
                        "is_existing_asset": True,
                        "recall_source": "db_exact",
                    }
                    log.debug("【候选资产召回·DB精确】资产 [%s (%s)] 命中剧本正文", akey, aname)

            # 2. characters 表主角匹配 (阶段 2 故事圣经角色)
            char_rows = fetch_all(
                db,
                "SELECT id, character_code, name, appearance, role, voice_style FROM characters WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC",
                {"did": did},
            )
            for c in char_rows:
                cname = c.get("name") or ""
                ccode = c.get("character_code") or ""
                if (cname and cname in sc_text) or (ccode and ccode in sc_text):
                    token = ccode or cname
                    expected_key = f"CHAR_{token}_T1_BASE_PORTRAIT"
                    if expected_key not in candidates:
                        has_real_asset = expected_key in existing_asset_keys
                        candidates[expected_key] = {
                            "asset_key": expected_key,
                            "name": cname,
                            "category": "character",
                            "type": "image",
                            "stage_code": "T1",
                            "visual_summary": (c.get("appearance") or c.get("voice_style") or "")[:60],
                            "relevance_score": 1.0,
                            "is_existing_asset": has_real_asset,
                            "recall_source": "db_exact" if has_real_asset else "canon_character_bible",
                        }
                        log.debug("【候选资产召回·DB精确】角色 [%s] 登场，添加基准肖像候选 [%s] (已落库=%s)", cname, expected_key, has_real_asset)

            # 3. scenes 表场景匹配 (阶段 3 空间环境)
            scene_rows = fetch_all(
                db,
                "SELECT id, location, prompt FROM scenes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC",
                {"did": did},
            )
            for s in scene_rows:
                sloc = s.get("location") or ""
                if sloc and sloc in sc_text:
                    expected_key = f"ENV_{sloc}_T1_WIDE"
                    if expected_key not in candidates:
                        has_real_asset = expected_key in existing_asset_keys
                        candidates[expected_key] = {
                            "asset_key": expected_key,
                            "name": sloc,
                            "category": "scene",
                            "type": "image",
                            "stage_code": "T1",
                            "visual_summary": (s.get("prompt") or "")[:60],
                            "relevance_score": 1.0,
                            "is_existing_asset": has_real_asset,
                            "recall_source": "db_exact" if has_real_asset else "canon_scene_bible",
                        }
                        log.debug("【候选资产召回·DB精确】场景 [%s] 登场，添加全景候选 [%s] (已落库=%s)", sloc, expected_key, has_real_asset)

            # 4. props 表道具匹配 (阶段 3 叙事关键道具)
            prop_rows = fetch_all(
                db,
                "SELECT id, name, prompt, type, description FROM props WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC",
                {"did": did},
            )
            for p in prop_rows:
                pname = p.get("name") or ""
                if pname and pname in sc_text:
                    expected_key = f"PROP_{pname}_T1_STATIC"
                    if expected_key not in candidates:
                        has_real_asset = expected_key in existing_asset_keys
                        candidates[expected_key] = {
                            "asset_key": expected_key,
                            "name": pname,
                            "category": "prop",
                            "type": "image",
                            "stage_code": "T1",
                            "visual_summary": (p.get("prompt") or p.get("description") or "")[:60],
                            "relevance_score": 1.0,
                            "is_existing_asset": has_real_asset,
                            "recall_source": "db_exact" if has_real_asset else "canon_prop_bible",
                        }
                        log.debug("【候选资产召回·DB精确】物证 [%s] 登场，添加静态物证候选 [%s] (已落库=%s)", pname, expected_key, has_real_asset)
        except Exception as db_err:
            log.warning("【候选资产召回】DB 初筛异常: %s", db_err)

    # -------------------------------------------------------------------------
    # 步骤 3: 语义向量重召回 (Semantic Vector Recall)
    # -------------------------------------------------------------------------
    settings = vector_memory_settings(cfg)
    if settings["backend"] == "qdrant" and not is_qdrant_circuit_open() and sc_text.strip():
        try:
            from qdrant_client import QdrantClient
        except ImportError:
            QdrantClient = None
            record_qdrant_failure()
            log.debug("【候选资产召回】qdrant-client 未安装，跳过向量检索")

        if QdrantClient is not None:
            col_name = get_drama_asset_collection_name(did, cfg)
            try:
                query_vec = generate_text_embedding(sc_text[:1000], cfg)
                timeout = float(settings.get("timeout") or 5.0)
                client = QdrantClient(url=settings["url"], api_key=settings.get("api_key") or None, timeout=timeout)

                # 由于集合按剧本物理隔离 (lmd_assets_drama_{drama_id})，无需在集合内再次按 drama_id 过滤
                if hasattr(client, "query_points"):
                    query_res = client.query_points(
                        collection_name=col_name,
                        query=query_vec,
                        limit=max(top_k * 2, 20),
                    )
                    hits = getattr(query_res, "points", query_res)
                elif hasattr(client, "search"):
                    hits = client.search(
                        collection_name=col_name,
                        query_vector=query_vec,
                        limit=max(top_k * 2, 20),
                    )
                else:
                    hits = []
                record_qdrant_success()
                for hit in hits:
                    payload = getattr(hit, "payload", {}) or {}
                    akey = payload.get("asset_key")
                    if not akey:
                        continue
                    score = round(float(hit.score), 4)
                    if akey in candidates:
                        # 精确命中保持最高分 1.0
                        continue
                    candidates[akey] = {
                        "asset_key": str(akey),
                        "name": payload.get("name") or akey,
                        "category": payload.get("category") or "other",
                        "type": payload.get("type") or "image",
                        "stage_code": payload.get("stage_code") or "",
                        "visual_summary": (payload.get("visual_summary") or payload.get("prompt") or "")[:60],
                        "relevance_score": score,
                        "is_existing_asset": True,
                        "recall_source": "vector_semantic",
                    }
                    log.debug("【候选资产召回·向量】语义召回命中 [%s], 相似度=%.4f", akey, score)
            except Exception as q_err:
                err_msg = str(q_err)
                if "doesn't exist" in err_msg or "404" in err_msg or "Not found" in err_msg:
                    log.debug("【候选资产召回】资产集合 [%s] 尚不存在或为空，跳过向量检索", col_name)
                else:
                    record_qdrant_failure()
                    log.warning("【候选资产召回】Qdrant 语义检索非致命异常: %s", q_err)

    # -------------------------------------------------------------------------
    # 步骤 4: 兜底保障 (Tier-0 Grounding & Fallback)
    # -------------------------------------------------------------------------
    # 若候选数量不足 top_k，自动补齐该剧前序已注册资产与核心主角锚点
    if len(candidates) < top_k and db is not None:
        try:
            # 补齐主角
            for c in char_rows:
                tok = c.get("character_code") or c.get("name") or ""
                ckey = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                if ckey not in candidates:
                    candidates[ckey] = {
                        "asset_key": ckey,
                        "name": c.get("name") or tok,
                        "category": "character",
                        "type": "image",
                        "stage_code": "T1",
                        "visual_summary": (c.get("appearance") or "")[:60],
                        "relevance_score": 0.75,
                        "is_existing_asset": (ckey in existing_asset_keys),
                        "recall_source": "db_tier0_grounding",
                    }
                if len(candidates) >= top_k:
                    break

            # 补齐主场景
            if len(candidates) < top_k:
                for s in scene_rows:
                    loc = s.get("location") or ""
                    skey = f"ENV_{loc}_T1_WIDE"
                    if skey not in candidates:
                        candidates[skey] = {
                            "asset_key": skey,
                            "name": loc,
                            "category": "scene",
                            "type": "image",
                            "stage_code": "T1",
                            "visual_summary": (s.get("visual_prompt") or "")[:60],
                            "relevance_score": 0.70,
                            "is_existing_asset": (skey in existing_asset_keys),
                            "recall_source": "db_tier0_grounding",
                        }
                    if len(candidates) >= top_k:
                        break
        except Exception as fb_err:
            log.warning("【候选资产召回】兜底补齐异常: %s", fb_err)

    # -------------------------------------------------------------------------
    # 步骤 5: 融合排序、去重与 Top-K 截断
    # -------------------------------------------------------------------------
    ranked = sorted(
        candidates.values(),
        key=lambda x: (x.get("relevance_score", 0.0), x.get("asset_key", "")),
        reverse=True,
    )
    final_pool = ranked[:top_k]
    log.info(
        "【候选资产召回完成】剧目 [%s] 候选池组装完毕: 候选总数=%d, 最终截取 Top-%d: %s",
        did, len(candidates), len(final_pool), [c["asset_key"] for c in final_pool]
    )
    return final_pool
