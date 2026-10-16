"""后台任务 worker — 替代 backend-node 的 setImmediate。

Node 版用 `setImmediate(() => { ... })` 把生成/轮询丢到下一个事件循环 tick，
其局限是：进程重启即丢失，且并发无上限。Python 版改用线程池，语义保持一致
（调用后立即返回，后台执行），同时获得并发上限与可测试性。

关键约束：SQLAlchemy Session **不是线程安全的**，且请求级 Session 在响应后即关闭。
因此后台任务必须在 worker 线程内**自建 Session**，不能复用请求的 db。

用法：
    from app.services import workerService
    workerService.submit(my_job, arg1, arg2)     # 等价于 setImmediate(() => my_job(arg1, arg2))

重复提交保护（对应 Node 的 activeVideoPolls / 各类 in-flight 集合）：
    if workerService.begin("video_poll", video_id):
        try:    ...
        finally: workerService.end("video_poll", video_id)
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from app.core.logger import get_logger

log = get_logger("lmd.worker")

_DEFAULT_WORKERS = 8

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()

# 在途任务去重：{(kind, key)}
_inflight: set[tuple[str, Any]] = set()
_inflight_lock = threading.Lock()


def _max_workers() -> int:
    raw = str(os.environ.get("WORKER_MAX_THREADS") or "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n > 0:
            return min(n, 64)
    return _DEFAULT_WORKERS


def get_executor() -> ThreadPoolExecutor:
    """惰性创建线程池（单例）。"""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=_max_workers(), thread_name_prefix="lmd-worker"
                )
                log.info("Worker thread pool started", extra={"max_workers": _max_workers()})
    return _executor


def submit(fn: Any, *args: Any, **kwargs: Any) -> Future:
    """等价 setImmediate：提交后台任务，立即返回 Future。

    支持两种调用签名：
      1. workerService.submit(fn, *args, **kwargs)
      2. workerService.submit("job_label", fn, *args, **kwargs)
    fn 抛出的异常不会传播到调用方，仅记录日志（与 Node 的 unhandled 行为对齐）。
    """
    executor = get_executor()

    if isinstance(fn, str) and args and callable(args[0]):
        job_label = fn
        actual_fn = args[0]
        actual_args = args[1:]
    else:
        actual_fn = fn
        actual_args = args
        job_label = getattr(actual_fn, "__name__", repr(actual_fn))

    def _run() -> Any:
        try:
            return actual_fn(*actual_args, **kwargs)
        except Exception as e:  # noqa: BLE001
            log.error("Worker job failed", extra={
                "job": job_label, "reason": str(e),
            })
            return None

    return executor.submit(_run)


def begin(kind: str, key: Any) -> bool:
    """标记 (kind, key) 进入在途；已在途返回 False（调用方应跳过）。"""
    with _inflight_lock:
        token = (kind, key)
        if token in _inflight:
            return False
        _inflight.add(token)
        return True


def end(kind: str, key: Any) -> None:
    """清除在途标记（应放在 finally 中）。"""
    with _inflight_lock:
        _inflight.discard((kind, key))


def inflight_count() -> int:
    with _inflight_lock:
        return len(_inflight)


def shutdown(wait: bool = False) -> None:
    """关闭线程池（测试与优雅退出用）。"""
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=wait)
            _executor = None
            with _inflight_lock:
                _inflight.clear()
            log.info("Worker thread pool stopped")


def session_scope():
    """worker 线程内自建 Session 的上下文管理器。

    Session 非线程安全，后台任务不能复用请求级 db，必须各自开一个。
    用法：
        with workerService.session_scope() as db:
            ...
    """
    from contextlib import contextmanager

    from app.db.session import SessionLocal, init_engine

    @contextmanager
    def _scope():
        if SessionLocal is None:
            init_engine()
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _scope()
