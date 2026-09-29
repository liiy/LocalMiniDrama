"""统一日志模块：标准可读格式日志（文件/控制台）与结构化 JSON 日志。

【设计标准与特性】
1. 时区与时间戳：
   - 全面采用北京时间（UTC+8 / Asia/Shanghai），毫秒级精度（YYYY-MM-DD HH:MM:SS.mmm）。
2. 全局单例句柄池：
   - 集中在 Root Logger 配置单例 RotatingFileHandler 与 StreamHandler，消除 Windows 多句柄竞争与锁文件异常。
   - 所有子模块通过 get_logger(__name__) 或 get_logger("lmd.xxx") 继承并向上冒泡，杜绝日志遗漏。
3. 工业级标准化日志规范：
   - 文件端（logs/app.log）：默认输出标准人类可读日志格式，包含时间、级别、logger 名、进程/线程、源码文件名与行号、消息及扩展字段。
   - 控制台端（stdout）：支持清晰可读的格式化文本或 JSON 格式切换。
4. 安全脱敏与防御：
   - 深度递归过滤敏感凭证（api_key, token, secret, password 等）。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

# 北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))

_RESERVED_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_SECRET_KEY_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "authorization", "credential")

_init_lock = threading.Lock()
_is_logging_initialized = False


def _is_sensitive_key(key: str) -> bool:
    k = str(key).lower()
    return any(fragment in k for fragment in _SECRET_KEY_FRAGMENTS)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): ("***" if _is_sensitive_key(str(k)) else _json_safe(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def format_beijing_time(created: float) -> str:
    """将 Unix timestamp 转换为北京时间字符串（YYYY-MM-DD HH:MM:SS.mmm）。"""
    dt = datetime.fromtimestamp(created, tz=BEIJING_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class StandardTextFormatter(logging.Formatter):
    """工业级标准文本日志格式化器（北京时间毫秒精度 + 源码定位 + extra 字段支持）。"""

    DEFAULT_FMT = "%(asctime)s [%(levelname)s] [%(name)s] [%(process)d:%(threadName)s] [%(filename)s:%(lineno)d] %(message)s"

    def __init__(self, fmt: str | None = None) -> None:
        super().__init__(fmt=fmt or self.DEFAULT_FMT)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return format_beijing_time(record.created)

    def format(self, record: logging.LogRecord) -> str:
        base_msg = super().format(record)

        # 提取自定义 extra 业务字段并脱敏附加
        extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            extras[key] = "***" if _is_sensitive_key(key) else _json_safe(value)

        if extras:
            try:
                extra_str = json.dumps(extras, ensure_ascii=False)
                base_msg = f"{base_msg} | extra: {extra_str}"
            except Exception:
                base_msg = f"{base_msg} | extra: {extras}"

        return base_msg


# 兼容旧命名
StandardConsoleFormatter = StandardTextFormatter


class StandardJsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器（北京时间 + 元数据 + 脱敏）。"""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": format_beijing_time(record.created),
            "level": record.levelname.upper(),
            "logger": record.name,
            "msg": record.getMessage(),
            "file": record.filename,
            "func": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
        }
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)

        # 提取并脱敏用户自定义 extra 字段
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            entry[key] = "***" if _is_sensitive_key(key) else _json_safe(value)

        return json.dumps(entry, ensure_ascii=False)


# 兼容旧命名
JsonFormatter = StandardJsonFormatter


class SafeRotatingFileHandler(RotatingFileHandler):
    """Windows 多进程并发安全的滚动日志文件处理器。

    在 Windows 平台多进程环境下（例如 Dramatiq processes=2），当触发日志轮转（doRollover）时，
    其他进程可能依然持有目标文件句柄，引发 Windows 专有的 PermissionError: [WinError 32]。
    本处理器捕获该异常，放弃本次文件名重命名并重新打开追加写入流，防止多进程工作节点崩溃。
    """

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except (PermissionError, OSError) as exc:
            # 恢复 stream 打开状态，确保后续写入不丢失
            if self.stream is None or getattr(self.stream, "closed", False):
                try:
                    self.stream = self._open()
                except Exception:
                    pass
            sys.stderr.write(f"[SafeRotatingFileHandler] Rollover deferred due to file lock: {exc}\n")


_current_log_file: str | None = None
_current_file_handler: SafeRotatingFileHandler | None = None


def resolve_log_filepath(
    log_file: str | None = None,
    log_dir: str | None = None,
) -> str:
    """计算最终日志文件的绝对路径。

    优先级：
    1. 显式指定的 log_file 参数
    2. 环境变量 LMD_LOG_FILE 或 LOG_FILE
    3. 根据进程启动特征（sys.argv / 主模块）智能识别：
       - dispatcher_entry -> dispatcher.log
       - worker_entry 或 dramatiq -> worker.log
       - app.main 或 uvicorn -> api.log
       - 默认兜底 -> app.log
    """
    filename = log_file or os.environ.get("LMD_LOG_FILE") or os.environ.get("LOG_FILE")
    if not filename:
        argv_str = " ".join(sys.argv).lower()
        if "dispatcher_entry" in argv_str:
            filename = "dispatcher.log"
        elif "worker_entry" in argv_str or "dramatiq" in argv_str:
            filename = "worker.log"
        elif "app.main" in argv_str or "uvicorn" in argv_str:
            filename = "api.log"
        else:
            filename = "app.log"

    if os.path.isabs(filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        return filename

    target_log_dir = log_dir or os.environ.get("LMD_LOG_DIR") or os.environ.get("LOG_DIR")
    if not target_log_dir:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        target_log_dir = os.path.join(base_dir, "logs")

    os.makedirs(target_log_dir, exist_ok=True)
    return os.path.join(target_log_dir, filename)


def get_current_log_file() -> str | None:
    """获取当前已配置的文件日志路径。"""
    return _current_log_file


def reset_logging() -> None:
    """清理并重置全局日志状态与文件句柄（用于测试重置与优雅停机）。"""
    global _is_logging_initialized, _current_log_file, _current_file_handler
    with _init_lock:
        root_logger = logging.getLogger()
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        _current_file_handler = None
        _current_log_file = None
        _is_logging_initialized = False


def setup_logging(
    default_level: str = "INFO",
    log_dir: str | None = None,
    log_file: str | None = None,
    log_format: str = "text",
    console_format: str = "text",
    force: bool = False,
) -> None:
    """初始化全局根日志系统（线程安全单例，支持各端日志文件分流）。"""
    global _is_logging_initialized, _current_log_file, _current_file_handler
    with _init_lock:
        target_log_file = resolve_log_filepath(log_file=log_file, log_dir=log_dir)
        root_logger = logging.getLogger()

        if _is_logging_initialized and not force:
            # 若已初始化但目标文件变更，动态切换文件 Handler
            if _current_log_file != target_log_file:
                if _current_file_handler and _current_file_handler in root_logger.handlers:
                    root_logger.removeHandler(_current_file_handler)
                    try:
                        _current_file_handler.close()
                    except Exception:
                        pass
                try:
                    use_json_file = os.environ.get("LMD_LOG_FILE_FORMAT", log_format).lower() == "json"
                    file_formatter = StandardJsonFormatter() if use_json_file else StandardTextFormatter()
                    new_handler = SafeRotatingFileHandler(
                        target_log_file,
                        maxBytes=10 * 1024 * 1024,
                        backupCount=5,
                        encoding="utf-8",
                    )
                    new_handler.setFormatter(file_formatter)
                    new_handler.setLevel(logging.DEBUG)
                    root_logger.addHandler(new_handler)
                    _current_file_handler = new_handler
                    _current_log_file = target_log_file
                except Exception as e:
                    sys.stderr.write(f"Failed to switch rotating file logger to {target_log_file}: {e}\n")
            return

        level_name = os.environ.get("LMD_LOG_LEVEL", default_level).upper()
        log_level = getattr(logging, level_name, logging.INFO)

        root_logger.setLevel(log_level)

        # 清理旧 handlers 防止热重载或重复添加
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)

        # 1. 控制台 Handler (Stdout)
        use_json_console = os.environ.get("LMD_LOG_CONSOLE_FORMAT", console_format).lower() == "json"
        console_formatter = StandardJsonFormatter() if use_json_console else StandardTextFormatter()
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(console_formatter)
        stream_handler.setLevel(log_level)
        root_logger.addHandler(stream_handler)

        # 2. 滚动文件 Handler (指向 target_log_file)
        try:
            new_handler = SafeRotatingFileHandler(
                target_log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            use_json_file = os.environ.get("LMD_LOG_FILE_FORMAT", log_format).lower() == "json"
            file_formatter = StandardJsonFormatter() if use_json_file else StandardTextFormatter()
            new_handler.setFormatter(file_formatter)
            new_handler.setLevel(logging.DEBUG)  # 文件中记录全量 DEBUG+ 日志
            root_logger.addHandler(new_handler)
            _current_file_handler = new_handler
            _current_log_file = target_log_file
        except Exception as e:
            sys.stderr.write(f"Failed to initialize rotating file logger for {target_log_file}: {e}\n")

        # 3. 设置核心应用 Logger 级别并抑制第三方高频噪音
        lmd_logger = logging.getLogger("lmd")
        lmd_logger.setLevel(logging.DEBUG)
        lmd_logger.propagate = True

        # 4. 路由 Uvicorn 日志到 Root Logger
        for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            u_logger = logging.getLogger(uvicorn_logger_name)
            u_logger.handlers.clear()
            u_logger.propagate = True

        # 5. 路由 Dramatiq 日志到 Root Logger
        for dramatiq_logger_name in ("dramatiq", "dramatiq.Worker", "dramatiq.ForkProcess"):
            d_logger = logging.getLogger(dramatiq_logger_name)
            d_logger.propagate = True

        for noisy_lib in ("urllib3", "httpcore", "httpx", "asyncio", "watchfiles"):
            logging.getLogger(noisy_lib).setLevel(logging.WARNING)

        _is_logging_initialized = True


def setup_logger(name: str = "lmd") -> logging.Logger:
    """获取并配置 logger 实例（向后兼容）。"""
    if not _is_logging_initialized:
        setup_logging()
    logger = logging.getLogger(name)
    logger.propagate = True
    return logger


def get_logger(name: str = "lmd") -> logging.Logger:
    """获取全局统一标准 logger。"""
    return setup_logger(name)
