"""多端日志分流隔离与并发滚动安全单元测试。"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core import logger as logmod


def test_resolve_log_filepath_explicit():
    path = logmod.resolve_log_filepath(log_file="custom.log", log_dir="/tmp/test_logs")
    assert path.endswith("custom.log")
    assert "/tmp/test_logs" in path or "\\tmp\\test_logs" in path


def test_resolve_log_filepath_env_var(monkeypatch):
    monkeypatch.setenv("LMD_LOG_FILE", "env_override.log")
    path = logmod.resolve_log_filepath()
    assert path.endswith("env_override.log")


def test_resolve_log_filepath_argv_detection(monkeypatch):
    monkeypatch.delenv("LMD_LOG_FILE", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)

    with patch.object(sys, "argv", ["python", "-m", "app.tasks.dispatcher_entry"]):
        path = logmod.resolve_log_filepath()
        assert path.endswith("dispatcher.log")

    with patch.object(sys, "argv", ["dramatiq", "app.tasks.worker_entry", "--queues", "lmd_tasks"]):
        path = logmod.resolve_log_filepath()
        assert path.endswith("worker.log")

    with patch.object(sys, "argv", ["python", "-m", "app.main"]):
        path = logmod.resolve_log_filepath()
        assert path.endswith("api.log")

    with patch.object(sys, "argv", ["python", "some_script.py"]):
        path = logmod.resolve_log_filepath()
        assert path.endswith("app.log")


def test_setup_logging_switch_destination():
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            # 1. 初始化为 dispatcher.log
            logmod.setup_logging(log_file="dispatcher.log", log_dir=tmp_dir, force=True)
            current = logmod.get_current_log_file()
            assert current is not None
            assert current.endswith("dispatcher.log")

            logger = logmod.get_logger("test.dispatcher")
            logger.info("Dispatcher message 1")

            # 检查 dispatcher.log 内容
            dispatcher_file = Path(current)
            assert dispatcher_file.exists()
            content = dispatcher_file.read_text(encoding="utf-8")
            assert "Dispatcher message 1" in content

            # 2. 切换为 worker.log
            logmod.setup_logging(log_file="worker.log", log_dir=tmp_dir)
            current_worker = logmod.get_current_log_file()
            assert current_worker is not None
            assert current_worker.endswith("worker.log")

            logger_worker = logmod.get_logger("test.worker")
            logger_worker.info("Worker message 1")

            worker_file = Path(current_worker)
            assert worker_file.exists()
            worker_content = worker_file.read_text(encoding="utf-8")
            assert "Worker message 1" in worker_content

            # 验证 worker 的消息没有写入 dispatcher.log
            content_after = dispatcher_file.read_text(encoding="utf-8")
            assert "Worker message 1" not in content_after

            # 3. 切换为 api.log
            logmod.setup_logging(log_file="api.log", log_dir=tmp_dir)
            current_api = logmod.get_current_log_file()
            assert current_api is not None
            assert current_api.endswith("api.log")

            logger_api = logmod.get_logger("test.api")
            logger_api.info("API request 1")

            api_file = Path(current_api)
            assert api_file.exists()
            api_content = api_file.read_text(encoding="utf-8")
            assert "API request 1" in api_content
    finally:
        logmod.reset_logging()


def test_safe_rotating_file_handler_rollover_resilience():
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = Path(tmp_dir) / "safe_test.log"
        handler = logmod.SafeRotatingFileHandler(
            str(log_path),
            maxBytes=50,
            backupCount=2,
            encoding="utf-8",
        )
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Small message for testing safe rollover",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        assert log_path.exists()

        # 模拟 Windows 文件句柄占用导致的 PermissionError
        with patch.object(handler, "rotate", side_effect=PermissionError(13, "Permission denied")):
            # doRollover 不应该抛出异常崩溃，而是捕获后保留可用 stream
            handler.doRollover()
            assert handler.stream is not None
            assert not handler.stream.closed

        handler.close()
