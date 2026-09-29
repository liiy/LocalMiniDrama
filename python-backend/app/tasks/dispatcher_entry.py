"""独立 Redis 投递补偿进程入口。"""
from __future__ import annotations

import os
import signal
import time

# 确保 Redis Dispatcher 端日志定向写入 dispatcher.log
os.environ.setdefault("LMD_LOG_FILE", "dispatcher.log")
from app.core.logger import get_logger, setup_logging
from app.db import session as dbmod
from app.tasks.redis_dispatcher import dispatch_pending_jobs_once

setup_logging(log_file="dispatcher.log")
log = get_logger("lmd.dispatcher")
_stopping = False


def _stop(*_args) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    """持续扫描 MySQL Outbox，弥补 API 提交后进程崩溃造成的漏投。"""
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    dbmod.init_engine()
    log.info("Redis queue dispatcher started")
    while not _stopping:
        result = dispatch_pending_jobs_once(limit=200)
        if not result.get("count"):
            time.sleep(1.0)
    dbmod.reset_engine()


if __name__ == "__main__":
    main()
