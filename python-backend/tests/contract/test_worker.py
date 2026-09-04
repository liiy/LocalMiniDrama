"""测试 workerService 的线程池、在途去重与后台执行语义。"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services import workerService as w  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_pool():
    """每个用例后重置线程池与在途集合，避免相互干扰。"""
    yield
    w.shutdown(wait=False)
    with w._inflight_lock:
        w._inflight.clear()


def test_submit_runs_in_background():
    done = threading.Event()
    w.submit(lambda: done.set())
    assert done.wait(5), "后台任务应在 worker 线程执行"


def test_submit_passes_args():
    got = threading.Event()
    box = {}

    def job(a, b, c=None):
        box.update(a=a, b=b, c=c)
        got.set()

    w.submit(job, 1, 2, c=3)
    assert got.wait(5)
    assert box == {"a": 1, "b": 2, "c": 3}


def test_submit_exception_does_not_raise():
    """等价于 Node setImmediate 里的未捕获异常：只记录日志，不影响调用方。"""
    boom_done = threading.Event()
    after_done = threading.Event()

    def boom():
        boom_done.set()
        raise RuntimeError("kaboom")

    def after():
        after_done.set()

    w.submit(boom)
    w.submit(after)
    assert boom_done.wait(5)
    assert after_done.wait(5), "单个任务失败不应影响后续任务"


def test_submit_returns_future():
    fut = w.submit(lambda: 42)
    assert fut.result(timeout=5) == 42


def test_begin_end_dedup():
    assert w.begin("video_gen", 1) is True
    assert w.begin("video_gen", 1) is False, "同一 (kind,key) 不应重复进入"
    assert w.begin("video_gen", 2) is True, "不同 key 互不干扰"
    assert w.begin("video_poll", 1) is True, "不同 kind 互不干扰"

    w.end("video_gen", 1)
    assert w.begin("video_gen", 1) is True, "end 之后可再次进入"


def test_inflight_count():
    assert w.inflight_count() == 0
    w.begin("k", 1)
    w.begin("k", 2)
    assert w.inflight_count() == 2
    w.end("k", 1)
    assert w.inflight_count() == 1


def test_shutdown_is_idempotent():
    w.submit(lambda: None)
    w.shutdown(wait=True)
    w.shutdown(wait=True)  # 不应抛异常


def test_executor_is_singleton():
    a = w.get_executor()
    b = w.get_executor()
    assert a is b


def test_max_workers_env(monkeypatch):
    monkeypatch.setenv("WORKER_MAX_THREADS", "3")
    w.shutdown(wait=False)
    assert w._max_workers() == 3
    ex = w.get_executor()
    assert ex._max_workers == 3


def test_max_workers_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("WORKER_MAX_THREADS", "not-a-number")
    w.shutdown(wait=False)
    assert w._max_workers() == w._DEFAULT_WORKERS


def test_max_workers_env_clamped(monkeypatch):
    monkeypatch.setenv("WORKER_MAX_THREADS", "9999")
    w.shutdown(wait=False)
    assert w._max_workers() == 64


def test_concurrent_jobs_all_run():
    """并发提交多个任务，全部应执行完成。"""
    n = 20
    counter = {"v": 0}
    lock = threading.Lock()
    done = threading.Event()

    def job():
        with lock:
            counter["v"] += 1
            if counter["v"] == n:
                done.set()
        time.sleep(0.01)

    for _ in range(n):
        w.submit(job)
    assert done.wait(10), f"仅完成 {counter['v']}/{n}"
