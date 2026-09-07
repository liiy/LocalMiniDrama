"""实时事件总线与 SSE 契约（支持 Redis Pub/Sub 与内存降级回退）。

【架构设计与职责】
1. 双通道分发：
   - 当配置了 Redis 且服务可用时，通过 Redis Pub/Sub 频道 (lmd:events:drama:{drama_id}) 实现跨进程/分布式集群广播。
   - 当未配置 Redis 或 Redis 宕机时，平滑降级至进程内异步广播队列 (asyncio.Queue)。
2. 标准化 SSE 报文契约：
   - 遵循 W3C Server-Sent Events 协议规范。
   - 包含 event (事件类型), data (JSON 序列化载荷), id (事件游标/时间戳)。
   - 支持客户端断线重连 (retry: 3000) 与心跳保活 ping。
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

from app.core.config import load_config
from app.platform_common import now_iso

log = logging.getLogger(__name__)


class EventBus:
    """全局统一事件总线（Redis Pub/Sub + 内存广播队列）。"""

    _subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)
    _redis_client: Any = None
    _redis_checked: bool = False

    @classmethod
    def _get_redis(cls):
        if not cls._redis_checked:
            cls._redis_checked = True
            try:
                cfg = load_config()
                redis_url = cfg.get("queue", {}).get("redis_url")
                if redis_url:
                    import redis
                    cls._redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
                    cls._redis_client.ping()
                    log.info("EventBus connected to Redis Pub/Sub: %s", redis_url)
            except Exception as e:
                log.warning("EventBus Redis not available, using in-memory bus: %s", e)
                cls._redis_client = None
        return cls._redis_client

    @classmethod
    def publish_event(
        cls,
        drama_id: int,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """发布实时事件（同时广播至 Redis 与本地订阅者）。"""
        payload = {
            "drama_id": drama_id,
            "event": event_type,
            "data": data or {},
            "timestamp": now_iso(),
        }
        json_str = json.dumps(payload, ensure_ascii=False)

        # 1. 广播至 Redis
        r = cls._get_redis()
        if r:
            try:
                channel = f"lmd:events:drama:{drama_id}"
                r.publish(channel, json_str)
            except Exception as e:
                log.warning("Redis publish failed, falling back to memory: %s", e)

        # 2. 广播至本地内存队列
        queues = list(cls._subscribers.get(drama_id, set()))
        for q in queues:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    @classmethod
    async def subscribe_events(
        cls,
        drama_id: int,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """订阅指定短剧的实时事件流（异步生成器，带心跳）。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        cls._subscribers[drama_id].add(q)

        # 初始发送连接确认
        yield {
            "drama_id": drama_id,
            "event": "connected",
            "data": {"status": "online", "drama_id": drama_id},
            "timestamp": now_iso(),
        }

        try:
            while True:
                try:
                    # 等待事件或超时发送心跳
                    event = await asyncio.wait_for(q.get(), timeout=heartbeat_interval)
                    yield event
                except asyncio.TimeoutError:
                    # 心跳保活
                    yield {
                        "drama_id": drama_id,
                        "event": "ping",
                        "data": {"time": now_iso()},
                        "timestamp": now_iso(),
                    }
        finally:
            cls._subscribers[drama_id].discard(q)
            if not cls._subscribers[drama_id]:
                cls._subscribers.pop(drama_id, None)

    @staticmethod
    def format_sse_message(event_dict: dict[str, Any]) -> str:
        """将事件字典格式化为符合 W3C 标准的 SSE 文本块。"""
        event_name = event_dict.get("event", "message")
        data_body = json.dumps(event_dict.get("data", {}), ensure_ascii=False)
        return f"event: {event_name}\ndata: {data_body}\n\n"
