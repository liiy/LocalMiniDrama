"""内嵌常驻队列 Worker。

是否启用由配置或环境变量决定。执行循环和心跳循环使用独立线程、独立数据库 Session，
避免一次耗时 AI 调用阻塞 worker 心跳。
"""
from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import load_config
from app.core.logger import get_logger
from app.db.session import session_scope
from app.tasks import queue_service, worker_runner

log = get_logger("lmd.queueWorker")


@dataclass(frozen=True)
class WorkerSettings:
    enabled: bool
    worker_id: str
    queues: tuple[str, ...]
    poll_interval_seconds: float
    heartbeat_interval_seconds: float
    stale_worker_seconds: int
    stale_job_seconds: int
    recovery_interval_seconds: float
    waiting_sync_interval_seconds: float
    auto_advance: bool


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any, default: float, minimum: float = 0.1) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _parse_queues(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
    return tuple(dict.fromkeys(items or ["workflow"]))


def load_worker_settings(cfg: dict[str, Any] | None = None) -> WorkerSettings:
    """从 YAML 和环境变量加载 worker 配置，环境变量优先。"""
    cfg = cfg or load_config()
    raw = ((cfg.get("queue") or {}).get("worker") or {}) if isinstance(cfg, dict) else {}
    default_worker_id = f"{socket.gethostname()}:{os.getpid()}"
    return WorkerSettings(
        enabled=_as_bool(os.environ.get("LMD_QUEUE_WORKER_ENABLED", raw.get("enabled")), False),
        worker_id=str(os.environ.get("LMD_QUEUE_WORKER_ID") or raw.get("worker_id") or default_worker_id),
        queues=_parse_queues(os.environ.get("LMD_QUEUE_WORKER_QUEUES") or raw.get("queues")),
        poll_interval_seconds=_as_float(
            os.environ.get("LMD_QUEUE_POLL_SECONDS") or raw.get("poll_interval_seconds"),
            1.0,
        ),
        heartbeat_interval_seconds=_as_float(
            os.environ.get("LMD_QUEUE_HEARTBEAT_SECONDS") or raw.get("heartbeat_interval_seconds"),
            10.0,
        ),
        stale_worker_seconds=_as_int(
            os.environ.get("LMD_QUEUE_STALE_WORKER_SECONDS") or raw.get("stale_worker_seconds"),
            90,
        ),
        stale_job_seconds=_as_int(
            os.environ.get("LMD_QUEUE_STALE_JOB_SECONDS") or raw.get("stale_job_seconds"),
            1800,
        ),
        recovery_interval_seconds=_as_float(
            os.environ.get("LMD_QUEUE_RECOVERY_SECONDS") or raw.get("recovery_interval_seconds"),
            60.0,
        ),
        waiting_sync_interval_seconds=_as_float(
            os.environ.get("LMD_QUEUE_WAITING_SYNC_SECONDS") or raw.get("waiting_sync_interval_seconds"),
            2.0,
        ),
        auto_advance=_as_bool(os.environ.get("LMD_QUEUE_AUTO_ADVANCE", raw.get("auto_advance")), True),
    )


class WorkerRuntime:
    """管理常驻执行线程、心跳线程和优雅关闭。"""

    def __init__(self, settings: WorkerSettings):
        self.settings = settings
        self._stop_event = threading.Event()
        self._run_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._next_queue_index = 0
        self._state: dict[str, Any] = {
            "status": "disabled" if not settings.enabled else "created",
            "processed_jobs": 0,
            "last_result": None,
            "last_error": None,
        }

    def start(self) -> bool:
        if not self.settings.enabled:
            return False
        if self._run_thread and self._run_thread.is_alive():
            return True
        self._stop_event.clear()
        with session_scope() as db:
            queue_service.register_worker(
                db,
                worker_id=self.settings.worker_id,
                queues=list(self.settings.queues),
                hostname=socket.gethostname(),
                process_id=os.getpid(),
                metadata={"runtime": "embedded", "auto_advance": self.settings.auto_advance},
            )
            # 进程启动时先回收上一个 worker 遗留的超时 processing 任务，
            # 并通过 Runner 同步最终失败任务对应的工作流步骤状态。
            worker_runner.recover_stale_jobs(
                db,
                timeout_seconds=self.settings.stale_job_seconds,
            )
        self._set_state(status="running", last_error=None)
        self._run_thread = threading.Thread(
            target=self._run_loop,
            name=f"lmd-queue-runner-{self.settings.worker_id}",
            daemon=True,
        )
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"lmd-queue-heartbeat-{self.settings.worker_id}",
            daemon=True,
        )
        self._run_thread.start()
        self._heartbeat_thread.start()
        log.info("Queue worker started", extra={"worker_id": self.settings.worker_id, "queues": self.settings.queues})
        return True

    def stop(self, wait_seconds: float = 10.0) -> None:
        """请求停止并等待当前循环收尾；不会强行中断正在进行的外部 AI 请求。"""
        if not self.settings.enabled:
            self._set_state(status="disabled")
            return
        self._set_state(status="stopping")
        self._stop_event.set()
        deadline = time.monotonic() + max(0.0, wait_seconds)
        for thread in (self._run_thread, self._heartbeat_thread):
            if thread and thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if not self._run_thread or not self._run_thread.is_alive():
            self._mark_offline()
            self._set_state(status="stopped")

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            state = dict(self._state)
        return {
            **state,
            "settings": asdict(self.settings),
            "run_thread_alive": bool(self._run_thread and self._run_thread.is_alive()),
            "heartbeat_thread_alive": bool(self._heartbeat_thread and self._heartbeat_thread.is_alive()),
        }

    def _run_loop(self) -> None:
        last_recovery = 0.0
        last_waiting_sync = 0.0
        try:
            while not self._stop_event.is_set():
                try:
                    now = time.monotonic()
                    if now - last_recovery >= self.settings.recovery_interval_seconds:
                        self._recover_stale_state()
                        last_recovery = now
                    if now - last_waiting_sync >= self.settings.waiting_sync_interval_seconds:
                        self._sync_waiting_jobs()
                        last_waiting_sync = now

                    result = self._run_one_from_queues()
                    self._set_state(status="running", last_result=result, last_error=None)
                    if result.get("status") != "idle":
                        self._increment_processed()
                        # 连续消费时短暂让出 CPU，同时保持较高吞吐。
                        self._stop_event.wait(0.05)
                    else:
                        self._stop_event.wait(self.settings.poll_interval_seconds)
                except Exception as err:  # noqa: BLE001
                    # 临时数据库或网络错误只影响当前轮，不应让常驻 worker 永久退出。
                    self._set_state(status="degraded", last_error=str(err))
                    log.error(
                        "Queue worker iteration failed",
                        extra={"worker_id": self.settings.worker_id, "reason": str(err)},
                    )
                    self._stop_event.wait(self.settings.poll_interval_seconds)
        finally:
            self._mark_offline()

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with session_scope() as db:
                    worker = queue_service.heartbeat_worker(db, self.settings.worker_id)
                    if not worker:
                        queue_service.register_worker(
                            db,
                            worker_id=self.settings.worker_id,
                            queues=list(self.settings.queues),
                            hostname=socket.gethostname(),
                            process_id=os.getpid(),
                        )
            except Exception as err:  # noqa: BLE001
                self._set_state(last_error=str(err))
                log.warning(
                    "Queue worker heartbeat failed",
                    extra={"worker_id": self.settings.worker_id, "reason": str(err)},
                )
            self._stop_event.wait(self.settings.heartbeat_interval_seconds)

    def _run_one_from_queues(self) -> dict[str, Any]:
        queue_count = len(self.settings.queues)
        if not queue_count:
            return {"status": "idle", "worker_id": self.settings.worker_id}

        start_index = self._next_queue_index % queue_count
        for offset in range(queue_count):
            queue_index = (start_index + offset) % queue_count
            queue_name = self.settings.queues[queue_index]
            with session_scope() as db:
                result = worker_runner.run_next_job(
                    db,
                    worker_id=self.settings.worker_id,
                    queue_name=queue_name,
                    auto_advance=self.settings.auto_advance,
                )
            if result.get("status") != "idle":
                # 下一轮从本次命中队列的后一个开始，防止高流量队列长期饿死其他队列。
                self._next_queue_index = (queue_index + 1) % queue_count
                return result
        # 全部空闲时也轮换起点，让同时到达的任务获得公平认领机会。
        self._next_queue_index = (start_index + 1) % queue_count
        return {"status": "idle", "worker_id": self.settings.worker_id}

    def _sync_waiting_jobs(self) -> None:
        with session_scope() as db:
            worker_runner.sync_waiting_jobs(db, auto_advance=self.settings.auto_advance)

    def _recover_stale_state(self) -> None:
        with session_scope() as db:
            queue_service.mark_stale_workers_offline(
                db,
                timeout_seconds=self.settings.stale_worker_seconds,
            )
            worker_runner.recover_stale_jobs(
                db,
                timeout_seconds=self.settings.stale_job_seconds,
            )

    def _mark_offline(self) -> None:
        try:
            with session_scope() as db:
                queue_service.stop_worker(db, self.settings.worker_id)
        except Exception as err:  # noqa: BLE001
            log.warning(
                "Queue worker offline update failed",
                extra={"worker_id": self.settings.worker_id, "reason": str(err)},
            )

    def _set_state(self, **updates: Any) -> None:
        with self._state_lock:
            self._state.update(updates)

    def _increment_processed(self) -> None:
        with self._state_lock:
            self._state["processed_jobs"] = int(self._state.get("processed_jobs") or 0) + 1


_runtime_lock = threading.Lock()
_runtime: WorkerRuntime | None = None


def start_embedded_worker(cfg: dict[str, Any] | None = None) -> WorkerRuntime:
    """按配置启动全局内嵌 worker；重复调用不会创建重复线程。"""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = WorkerRuntime(load_worker_settings(cfg))
        _runtime.start()
        return _runtime


def stop_embedded_worker(wait_seconds: float = 10.0) -> None:
    global _runtime
    with _runtime_lock:
        runtime = _runtime
    if runtime:
        runtime.stop(wait_seconds=wait_seconds)


def embedded_worker_status() -> dict[str, Any]:
    with _runtime_lock:
        runtime = _runtime
    if not runtime:
        return {"status": "not_initialized"}
    return runtime.status()
