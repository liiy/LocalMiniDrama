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


def setup_logging(
    default_level: str = "INFO",
    log_dir: str | None = None,
    log_format: str = "text",
    console_format: str = "text",
) -> None:
    """初始化全局根日志系统（线程安全单例）。"""
    global _is_logging_initialized
    with _init_lock:
        if _is_logging_initialized:
            return

        level_name = os.environ.get("LMD_LOG_LEVEL", default_level).upper()
        log_level = getattr(logging, level_name, logging.INFO)

        root_logger = logging.getLogger()
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

        # 2. 滚动文件 Handler (logs/app.log)
        try:
            target_log_dir = log_dir or os.environ.get("LMD_LOG_DIR") or os.environ.get("LOG_DIR")
            if not target_log_dir:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                target_log_dir = os.path.join(base_dir, "logs")

            os.makedirs(target_log_dir, exist_ok=True)
            log_file = os.path.join(target_log_dir, "app.log")

            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            use_json_file = os.environ.get("LMD_LOG_FILE_FORMAT", log_format).lower() == "json"
            file_formatter = StandardJsonFormatter() if use_json_file else StandardTextFormatter()
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(logging.DEBUG)  # 文件中记录全量 DEBUG+ 日志
            root_logger.addHandler(file_handler)
        except Exception as e:
            sys.stderr.write(f"Failed to initialize rotating file logger: {e}\n")

        # 3. 设置核心应用 Logger 级别并抑制第三方高频噪音
        lmd_logger = logging.getLogger("lmd")
        lmd_logger.setLevel(logging.DEBUG)
        lmd_logger.propagate = True

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
