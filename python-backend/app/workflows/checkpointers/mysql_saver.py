# -*- coding: utf-8 -*-
"""基于 MySQL / SQLite 的 LangGraph 工业级状态机持久化 CheckpointSaver。

【核心设计目标】
1. 继承标准 BaseCheckpointSaver 协议，完美替换默认的 MemorySaver；
2. 支持进程重启或崩溃后通过 thread_id 精准秒级恢复执行（Resume from Checkpoint），避免昂贵的前序 Token 重复消耗；
3. 支持多集并行执行时的独立线程状态隔离与版本回溯；
4. 采用 Base64 载荷封装，彻底规避数据库字符编码引起的乱码与截断问题；
5. 提供关键调试日志与同步/异步双模支持。
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import logging
import threading
from typing import Any, AsyncIterator, Iterator, Sequence

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    RunnableConfig,
    WRITES_IDX_MAP,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import engine as global_engine, session_scope

logger = logging.getLogger("app.workflows.checkpointers.mysql_saver")


class MySQLCheckpointSaver(BaseCheckpointSaver):
    """MySQL / SQLite 统一持久化状态机检查点保存器。"""

    def __init__(
        self,
        engine: Engine | None = None,
        session_factory: sessionmaker | None = None,
        serde: Any = None,
    ) -> None:
        super().__init__(serde=serde)
        self._engine = engine
        self._session_factory = session_factory
        self._lock = threading.RLock()
        logger.info("【Checkpointer 初始化】MySQLCheckpointSaver 实例已构建")

    def _get_session(self) -> Session:
        """获取数据库 Session。"""
        if self._session_factory is not None:
            return self._session_factory()
        if self._engine is not None:
            return Session(bind=self._engine)
        # 兜底使用全局数据库引擎
        from app.db.session import get_session_factory
        return get_session_factory()()

    def setup(self) -> None:
        """确保检查点所需的三张核心表结构已存在。"""
        import re
        logger.debug("【Checkpointer setup】检查并初始化 workflow_checkpoints 相关数据表")
        from app.db.schema import TABLES, build_create_sql
        
        target_tables = ["workflow_checkpoints", "workflow_checkpoint_blobs", "workflow_checkpoint_writes", "drama_checkpoint_index"]
        sqls = [build_create_sql(t) for t in TABLES if t.name in target_tables]
        
        with self._lock:
            with self._get_session() as session:
                is_sqlite = session.bind and session.bind.dialect.name == "sqlite"
                for sql in sqls:
                    if is_sqlite:
                        sql_sqlite = re.sub(r"\)\s*ENGINE=InnoDB.*$", ")", sql, flags=re.MULTILINE)
                        sql_sqlite = re.sub(r"BIGINT\s+NOT\s+NULL\s+AUTO_INCREMENT\s+PRIMARY\s+KEY", "INTEGER PRIMARY KEY AUTOINCREMENT", sql_sqlite)
                        sql_sqlite = re.sub(r"MEDIUMTEXT", "TEXT", sql_sqlite)
                        sql_sqlite = re.sub(r"\s+COMMENT\s+'(?:''|[^'])*'", "", sql_sqlite)
                        session.execute(text(sql_sqlite))
                    else:
                        session.execute(text(sql))
                session.commit()
        logger.debug("【Checkpointer setup 完成】持久化表结构就绪")

    # =========================================================================
    # 同步协议实现 (put, get_tuple, list, put_writes)
    # =========================================================================

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """持久化保存检查点快照与通道版本数据。"""
        thread_id: str = str(config["configurable"]["thread_id"])
        checkpoint_ns: str = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id: str = str(checkpoint["id"])
        parent_checkpoint_id: str | None = config["configurable"].get("checkpoint_id")
        
        logger.debug(
            "【Checkpointer put】开始持久化检查点: thread_id=%s, ns=%s, id=%s, parent_id=%s",
            thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id
        )

        c = checkpoint.copy()
        channel_values: dict[str, Any] = c.pop("channel_values", {})
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            with self._get_session() as session:
                # 1. 批量保存或更新变更通道的最新数据版本 (workflow_checkpoint_blobs)
                for channel, version in new_versions.items():
                    if channel in channel_values:
                        type_str, blob_bytes = self.serde.dumps_typed(channel_values[channel])
                    else:
                        type_str, blob_bytes = "empty", b""
                    
                    b64_payload = base64.b64encode(blob_bytes).decode("ascii")
                    
                    # 使用 UPSERT 语义插入或更新通道快照
                    upsert_blob_sql = text("""
                        INSERT INTO `workflow_checkpoint_blobs` 
                            (`thread_id`, `checkpoint_ns`, `channel`, `version`, `type`, `blob`, `created_at`)
                        VALUES 
                            (:thread_id, :checkpoint_ns, :channel, :version, :type, :blob, :created_at)
                        ON CONFLICT(`thread_id`, `checkpoint_ns`, `channel`, `version`) 
                        DO UPDATE SET `type`=excluded.`type`, `blob`=excluded.`blob`
                    """) if session.bind and session.bind.dialect.name == "sqlite" else text("""
                        INSERT INTO `workflow_checkpoint_blobs` 
                            (`thread_id`, `checkpoint_ns`, `channel`, `version`, `type`, `blob`, `created_at`)
                        VALUES 
                            (:thread_id, :checkpoint_ns, :channel, :version, :type, :blob, :created_at)
                        ON DUPLICATE KEY UPDATE 
                            `type`=VALUES(`type`), `blob`=VALUES(`blob`)
                    """)
                    
                    session.execute(upsert_blob_sql, {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "channel": channel,
                        "version": str(version),
                        "type": type_str,
                        "blob": b64_payload,
                        "created_at": now_iso,
                    })

                # 2. 持久化检查点主记录 (workflow_checkpoints)
                ckpt_type, ckpt_bytes = self.serde.dumps_typed(c)
                ckpt_b64 = base64.b64encode(ckpt_bytes).decode("ascii")

                meta_obj = get_checkpoint_metadata(config, metadata)
                meta_type, meta_bytes = self.serde.dumps_typed(meta_obj)
                meta_b64 = base64.b64encode(meta_bytes).decode("ascii")

                upsert_ckpt_sql = text("""
                    INSERT INTO `workflow_checkpoints` 
                        (`thread_id`, `checkpoint_ns`, `checkpoint_id`, `parent_checkpoint_id`, `type`, `checkpoint`, `metadata`, `created_at`, `updated_at`)
                    VALUES 
                        (:thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id, :type, :checkpoint, :metadata, :created_at, :updated_at)
                    ON CONFLICT(`thread_id`, `checkpoint_ns`, `checkpoint_id`) 
                    DO UPDATE SET 
                        `parent_checkpoint_id`=excluded.`parent_checkpoint_id`,
                        `type`=excluded.`type`,
                        `checkpoint`=excluded.`checkpoint`,
                        `metadata`=excluded.`metadata`,
                        `updated_at`=excluded.`updated_at`
                """) if session.bind and session.bind.dialect.name == "sqlite" else text("""
                    INSERT INTO `workflow_checkpoints` 
                        (`thread_id`, `checkpoint_ns`, `checkpoint_id`, `parent_checkpoint_id`, `type`, `checkpoint`, `metadata`, `created_at`, `updated_at`)
                    VALUES 
                        (:thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id, :type, :checkpoint, :metadata, :created_at, :updated_at)
                    ON DUPLICATE KEY UPDATE 
                        `parent_checkpoint_id`=VALUES(`parent_checkpoint_id`),
                        `type`=VALUES(`type`),
                        `checkpoint`=VALUES(`checkpoint`),
                        `metadata`=VALUES(`metadata`),
                        `updated_at`=VALUES(`updated_at`)
                """)

                session.execute(upsert_ckpt_sql, {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "parent_checkpoint_id": parent_checkpoint_id,
                    "type": ckpt_type,
                    "checkpoint": ckpt_b64,
                    "metadata": meta_b64,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                })
                session.commit()

        logger.info("【Checkpointer put 成功】检查点已落库: thread_id=%s, checkpoint_id=%s", thread_id, checkpoint_id)
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """持久化保存节点执行产生的 pending writes 通道写入记录。"""
        thread_id: str = str(config["configurable"]["thread_id"])
        checkpoint_ns: str = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id: str = str(config["configurable"]["checkpoint_id"])
        now_iso = datetime.now(timezone.utc).isoformat()

        logger.debug(
            "【Checkpointer put_writes】记录中间通道写入: thread_id=%s, checkpoint_id=%s, task_id=%s, 条数=%d",
            thread_id, checkpoint_id, task_id, len(writes)
        )

        with self._lock:
            with self._get_session() as session:
                for idx, (channel, val) in enumerate(writes):
                    write_idx = WRITES_IDX_MAP.get(channel, idx)
                    type_str, blob_bytes = self.serde.dumps_typed(val)
                    b64_payload = base64.b64encode(blob_bytes).decode("ascii")

                    upsert_write_sql = text("""
                        INSERT INTO `workflow_checkpoint_writes` 
                            (`thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`, `idx`, `channel`, `type`, `blob`, `task_path`, `created_at`)
                        VALUES 
                            (:thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :blob, :task_path, :created_at)
                        ON CONFLICT(`thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`, `idx`)
                        DO UPDATE SET `type`=excluded.`type`, `blob`=excluded.`blob`, `task_path`=excluded.`task_path`
                    """) if session.bind and session.bind.dialect.name == "sqlite" else text("""
                        INSERT INTO `workflow_checkpoint_writes` 
                            (`thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`, `idx`, `channel`, `type`, `blob`, `task_path`, `created_at`)
                        VALUES 
                            (:thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :blob, :task_path, :created_at)
                        ON DUPLICATE KEY UPDATE 
                            `type`=VALUES(`type`), `blob`=VALUES(`blob`), `task_path`=VALUES(`task_path`)
                    """)

                    session.execute(upsert_write_sql, {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "idx": write_idx,
                        "channel": channel,
                        "type": type_str,
                        "blob": b64_payload,
                        "task_path": task_path,
                        "created_at": now_iso,
                    })
                session.commit()

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """根据配置获取对应的检查点快照元组 (包含通道值与未决写入)。"""
        thread_id: str = str(config["configurable"]["thread_id"])
        checkpoint_ns: str = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id: str | None = get_checkpoint_id(config)

        logger.debug(
            "【Checkpointer get_tuple】读取检查点: thread_id=%s, ns=%s, 指定 checkpoint_id=%s",
            thread_id, checkpoint_ns, checkpoint_id
        )

        with self._lock:
            with self._get_session() as session:
                # 1. 查询目标检查点（指定 ID 或获取最新）
                if checkpoint_id:
                    query_sql = text("""
                        SELECT `checkpoint_id`, `parent_checkpoint_id`, `type`, `checkpoint`, `metadata`
                        FROM `workflow_checkpoints`
                        WHERE `thread_id` = :thread_id AND `checkpoint_ns` = :checkpoint_ns AND `checkpoint_id` = :checkpoint_id
                    """)
                    row = session.execute(query_sql, {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id
                    }).fetchone()
                else:
                    query_sql = text("""
                        SELECT `checkpoint_id`, `parent_checkpoint_id`, `type`, `checkpoint`, `metadata`
                        FROM `workflow_checkpoints`
                        WHERE `thread_id` = :thread_id AND `checkpoint_ns` = :checkpoint_ns
                        ORDER BY `checkpoint_id` DESC
                        LIMIT 1
                    """)
                    row = session.execute(query_sql, {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns
                    }).fetchone()

                if not row:
                    logger.debug("【Checkpointer get_tuple】未找到匹配检查点")
                    return None

                found_id, parent_id, ckpt_type, ckpt_b64, meta_b64 = row
                ckpt_bytes = base64.b64decode(ckpt_b64.encode("ascii"))
                checkpoint_: Checkpoint = self.serde.loads_typed((ckpt_type, ckpt_bytes))
                
                meta_obj: CheckpointMetadata = {}
                if meta_b64:
                    meta_bytes = base64.b64decode(meta_b64.encode("ascii"))
                    meta_obj = self.serde.loads_typed((ckpt_type, meta_bytes))

                # 2. 水合通道版本数据 (channel_values)
                channel_versions: ChannelVersions = checkpoint_.get("channel_versions", {})
                channel_values: dict[str, Any] = {}
                
                if channel_versions:
                    # 批量读取该 thread_id 下指定版本的 blobs
                    blob_sql = text("""
                        SELECT `channel`, `version`, `type`, `blob`
                        FROM `workflow_checkpoint_blobs`
                        WHERE `thread_id` = :thread_id AND `checkpoint_ns` = :checkpoint_ns
                    """)
                    blob_rows = session.execute(blob_sql, {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns
                    }).fetchall()
                    
                    blobs_map: dict[tuple[str, str], tuple[str, bytes]] = {}
                    for ch, ver, b_type, b_data in blob_rows:
                        blobs_map[(ch, str(ver))] = (b_type, base64.b64decode(b_data.encode("ascii")))

                    for ch, ver in channel_versions.items():
                        key = (ch, str(ver))
                        if key in blobs_map:
                            b_type, b_bytes = blobs_map[key]
                            if b_type != "empty":
                                channel_values[ch] = self.serde.loads_typed((b_type, b_bytes))

                # 3. 读取该检查点下关联的 pending writes
                writes_sql = text("""
                    SELECT `task_id`, `channel`, `type`, `blob`
                    FROM `workflow_checkpoint_writes`
                    WHERE `thread_id` = :thread_id AND `checkpoint_ns` = :checkpoint_ns AND `checkpoint_id` = :checkpoint_id
                    ORDER BY `idx` ASC
                """)
                write_rows = session.execute(writes_sql, {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": found_id
                }).fetchall()

                pending_writes: list[PendingWrite] = []
                for t_id, ch, w_type, w_b64 in write_rows:
                    w_bytes = base64.b64decode(w_b64.encode("ascii"))
                    val = self.serde.loads_typed((w_type, w_bytes))
                    pending_writes.append((t_id, ch, val))

                logger.info("【Checkpointer get_tuple 命中】成功获取检查点: thread_id=%s, id=%s", thread_id, found_id)
                return CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": found_id,
                        }
                    },
                    checkpoint={
                        **checkpoint_,
                        "channel_values": channel_values,
                    },
                    metadata=meta_obj,
                    parent_config=(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": parent_id,
                            }
                        }
                        if parent_id
                        else None
                    ),
                    pending_writes=pending_writes,
                )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """按条件遍历与搜索检查点历史序列。"""
        if not config:
            return

        thread_id: str = str(config["configurable"]["thread_id"])
        checkpoint_ns: str = str(config["configurable"].get("checkpoint_ns", ""))
        before_id: str | None = get_checkpoint_id(before) if before else None

        logger.debug(
            "【Checkpointer list】列举检查点: thread_id=%s, ns=%s, before_id=%s, limit=%s",
            thread_id, checkpoint_ns, before_id, limit
        )

        with self._lock:
            with self._get_session() as session:
                sql = """
                    SELECT `checkpoint_id`
                    FROM `workflow_checkpoints`
                    WHERE `thread_id` = :thread_id AND `checkpoint_ns` = :checkpoint_ns
                """
                params: dict[str, Any] = {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns
                }
                if before_id:
                    sql += " AND `checkpoint_id` < :before_id"
                    params["before_id"] = before_id

                sql += " ORDER BY `checkpoint_id` DESC"
                if limit is not None and limit > 0:
                    sql += f" LIMIT {limit}"

                rows = session.execute(text(sql), params).fetchall()

        for (c_id,) in rows:
            cfg: RunnableConfig = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": c_id,
                }
            }
            ckpt_tuple = self.get_tuple(cfg)
            if ckpt_tuple is not None:
                if filter:
                    meta = ckpt_tuple.metadata or {}
                    if not all(meta.get(k) == v for k, v in filter.items()):
                        continue
                yield ckpt_tuple

    # =========================================================================
    # 异步协议实现 (通过 asyncio.to_thread 优雅桥接)
    # =========================================================================

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """异步保存检查点。"""
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """异步保存 pending writes。"""
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """异步获取检查点元组。"""
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """异步列举检查点历史。"""
        tuples = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for t in tuples:
            yield t


_DEFAULT_CHECKPOINTER: MySQLCheckpointSaver | None = None


def get_default_checkpointer() -> MySQLCheckpointSaver:
    """获取全局默认的 MySQLCheckpointSaver 实例（延迟绑定数据库引擎）。"""
    global _DEFAULT_CHECKPOINTER
    if _DEFAULT_CHECKPOINTER is None:
        _DEFAULT_CHECKPOINTER = MySQLCheckpointSaver()
    return _DEFAULT_CHECKPOINTER

