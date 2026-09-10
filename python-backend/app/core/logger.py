"""日志：结构化为 JSON 单行（近似 Node 端 log 行为，便于检索）。"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

_RESERVED_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_SECRET_KEY_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "authorization", "credential")


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(fragment in k for fragment in _SECRET_KEY_FRAGMENTS)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): ("***" if _is_sensitive_key(str(k)) else _json_safe(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            entry[key] = "***" if _is_sensitive_key(key) else _json_safe(value)
        return json.dumps(entry, ensure_ascii=False)


def setup_logger(name: str = "lmd") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        formatter = JsonFormatter()
        
        # 控制台输出
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        # 写入日志文件 (支持滚动，每个文件 10MB，保留 5 个备份)
        try:
            log_dir = os.environ.get("LMD_LOG_DIR")
            if not log_dir:
                # 默认存放在 python-backend/logs/ 目录下
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                log_dir = os.path.join(base_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "app.log")
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            sys.stderr.write(f"Failed to initialize file logger: {e}\n")

        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger


def get_logger(name: str = "lmd") -> logging.Logger:
    return setup_logger(name)
