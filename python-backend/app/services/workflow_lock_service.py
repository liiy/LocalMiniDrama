"""工作流并发控制与分布式锁服务 (Workflow Lock & Pause Service)。

提供对短剧工作流执行的并发竞争保护与紧急人工暂停机制，根据方案第八节与第七节：
1. 分布式互斥锁：防止用户连续多次点击“继续/重跑”，避免多个 Worker 同时唤醒同一线程发生状态覆盖冲突 (lock:drama_exec:{drama_id})；
2. 紧急人工暂停标志：支持在 Redis 或内存中设置 pause_flag:drama_{drama_id}，使运行中的工作流安全退出；
3. 支持 Redis 与进程内内存双轨降级，确保在无外部 Redis 依赖时仍能安全运行。
"""
from __future__ import annotations

import time
import threading
from contextlib import contextmanager
from typing import Any, Generator

from app.core.config import load_config
from app.core.logger import get_logger

logger = get_logger("lmd.workflow_lock")

# Redis 客户端单例缓存
_redis_client: Any = None
_redis_checked: bool = False

# 内存降级存储 (当未配置 Redis 或 Redis 宕机时使用)
_mem_locks: dict[str, float] = {}  # key -> expire_timestamp
_mem_pause_flags: set[str] = set()
_mem_lock_guard = threading.Lock()


def _get_redis() -> Any:
    """获取 Redis 客户端，兼容 protocol=2 降级以支持各类 Redis 版本。"""
    global _redis_client, _redis_checked
    if not _redis_checked:
        _redis_checked = True
        try:
            cfg = load_config()
            redis_url = cfg.get("queue", {}).get("redis_url")
            if redis_url:
                import redis
                try:
                    _redis_client = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
                    _redis_client.ping()
                except Exception:
                    _redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
                    _redis_client.ping()
                logger.info(f"[WorkflowLock] 成功连接至 Redis 锁服务: {redis_url}")
            else:
                logger.info("[WorkflowLock] 未配置 Redis URL，将使用进程内互斥锁降级机制。")
        except Exception as e:
            logger.warning(f"[WorkflowLock] Redis 初始化失败，降级至进程内锁: {e}")
            _redis_client = None
    return _redis_client


import uuid

class LockAcquireResult(tuple):
    """互斥锁获取结果元组 (acquired: bool, token: str | None)。
    
    同时支持：
    1. 元组解包：`acquired, token = acquire_workflow_lock(...)`
    2. 布尔真值判断：`if acquired:` / `if not acquired:` (直接以 acquired 字段判断真假)
    """

    def __new__(cls, acquired: bool, token: str | None = None):
        return super().__new__(cls, (acquired, token))

    @property
    def acquired(self) -> bool:
        return self[0]

    @property
    def token(self) -> str | None:
        return self[1]

    def __bool__(self) -> bool:
        return bool(self[0])


def acquire_workflow_lock(
    drama_id: str | int,
    timeout_sec: int = 30,
    ttl_seconds: int | None = None,
) -> LockAcquireResult:
    """获取指定短剧的工作流执行互斥锁 (lock:drama_exec:{drama_id})。

    Args:
        drama_id: 短剧 ID
        timeout_sec: 锁超时时间（秒，默认 30 秒）
        ttl_seconds: 锁超时时间别名

    Returns:
        LockAcquireResult: (acquired, token)，支持布尔判断与元组解包
    """
    effective_ttl = ttl_seconds if ttl_seconds is not None else timeout_sec
    lock_key = f"lock:drama_exec:{drama_id}"
    token = str(uuid.uuid4())
    r = _get_redis()

    if r is not None:
        try:
            # 使用 SET key value NX EX timeout_sec 保证原子性
            acquired = bool(r.set(lock_key, token, nx=True, ex=effective_ttl))
            if acquired:
                logger.debug(f"[WorkflowLock] 成功获取 Redis 互斥锁: key={lock_key}, ttl={effective_ttl}s, token={token}")
                return LockAcquireResult(True, token)
            else:
                logger.warning(f"[WorkflowLock] 获取 Redis 互斥锁失败 (已存在并发执行): key={lock_key}")
                return LockAcquireResult(False, None)
        except Exception as e:
            logger.warning(f"[WorkflowLock] Redis 获取锁异常，降级至内存锁: {e}")

    # 内存降级互斥锁
    with _mem_lock_guard:
        now = time.time()
        expire_at = _mem_locks.get(lock_key, 0.0)
        if expire_at > now:
            logger.warning(f"[WorkflowLock] 内存互斥锁已存在并发执行: key={lock_key}")
            return LockAcquireResult(False, None)
        _mem_locks[lock_key] = now + effective_ttl
        logger.debug(f"[WorkflowLock] 成功获取内存互斥锁: key={lock_key}, ttl={effective_ttl}s, token={token}")
        return LockAcquireResult(True, token)


def release_workflow_lock(drama_id: str | int, token: str | None = None) -> bool:
    """释放短剧工作流执行互斥锁。

    Args:
        drama_id: 短剧 ID
        token: 可选的锁 Token，若提供则校验匹配后再删除

    Returns:
        bool: 是否成功释放
    """
    lock_key = f"lock:drama_exec:{drama_id}"
    r = _get_redis()

    if r is not None:
        try:
            if token:
                curr_val = r.get(lock_key)
                if curr_val and curr_val == token:
                    r.delete(lock_key)
                elif not curr_val:
                    pass
                else:
                    logger.warning(f"[WorkflowLock] Redis 释放锁 Token 不匹配: key={lock_key}")
                    return False
            else:
                r.delete(lock_key)
            logger.debug(f"[WorkflowLock] 释放 Redis 互斥锁完成: key={lock_key}")
            return True
        except Exception as e:
            logger.warning(f"[WorkflowLock] Redis 释放锁异常: {e}")

    with _mem_lock_guard:
        _mem_locks.pop(lock_key, None)
        logger.debug(f"[WorkflowLock] 释放内存互斥锁完成: key={lock_key}")
        return True


@contextmanager
def workflow_lock_context(
    drama_id: str | int,
    timeout_sec: int = 30,
    ttl_seconds: int | None = None,
) -> Generator[LockAcquireResult, None, None]:
    """工作流互斥锁上下文管理器。

    Usage:
        with workflow_lock_context(drama_id) as acquired:
            if not acquired:
                raise ConflictError("工作流正在执行中，请勿重复提交")
            # 业务逻辑
    """
    effective_ttl = ttl_seconds if ttl_seconds is not None else timeout_sec
    res = acquire_workflow_lock(drama_id, timeout_sec=effective_ttl)
    try:
        yield res
    finally:
        if res.acquired:
            release_workflow_lock(drama_id, res.token)


def set_pause_flag(drama_id: str | int, is_paused: bool = True, reason: str | None = None) -> bool:
    """设置或清除工作流人工紧急暂停标志 (pause_flag:drama_{drama_id})。

    Args:
        drama_id: 短剧 ID
        is_paused: True=设置暂停标志, False=清除暂停标志
        reason: 可选暂停原因说明

    Returns:
        bool: 是否操作成功
    """
    flag_key = f"pause_flag:drama_{drama_id}"
    r = _get_redis()

    if r is not None:
        try:
            if is_paused:
                # 暂停标志默认保留 24 小时
                r.set(flag_key, "1", ex=86400)
                logger.info(f"[WorkflowLock] 设置 Redis 人工暂停标志: key={flag_key}, reason={reason}")
            else:
                r.delete(flag_key)
                logger.info(f"[WorkflowLock] 清除 Redis 人工暂停标志: key={flag_key}, reason={reason}")
            return True
        except Exception as e:
            logger.warning(f"[WorkflowLock] Redis 暂停标志操作异常，降级至内存: {e}")

    with _mem_lock_guard:
        if is_paused:
            _mem_pause_flags.add(flag_key)
            logger.info(f"[WorkflowLock] 设置内存人工暂停标志: key={flag_key}, reason={reason}")
        else:
            _mem_pause_flags.discard(flag_key)
            logger.info(f"[WorkflowLock] 清除内存人工暂停标志: key={flag_key}, reason={reason}")
        return True


def clear_pause_flag(drama_id: str | int) -> bool:
    """清除工作流人工紧急暂停标志 (pause_flag:drama_{drama_id})。

    Args:
        drama_id: 短剧 ID

    Returns:
        bool: 是否操作成功
    """
    return set_pause_flag(drama_id, is_paused=False)


def is_pause_flag_set(drama_id: str | int) -> bool:
    """检查指定短剧是否被设置了人工暂停标志。

    Args:
        drama_id: 短剧 ID

    Returns:
        bool: True=已被人工暂停, False=正常运行
    """
    flag_key = f"pause_flag:drama_{drama_id}"
    r = _get_redis()

    if r is not None:
        try:
            val = r.get(flag_key)
            return val is not None and val == "1"
        except Exception as e:
            logger.warning(f"[WorkflowLock] Redis 检查暂停标志异常: {e}")

    with _mem_lock_guard:
        return flag_key in _mem_pause_flags
