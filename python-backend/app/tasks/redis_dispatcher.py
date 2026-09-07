"""MySQL Outbox 到 Redis/Dramatiq 的可靠投递器。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.db.session import fetch_all, session_scope
from app.platform_common import now_iso

log = get_logger("lmd.redisDispatcher")


def is_dramatiq_backend_enabled() -> bool:
    """只有显式选择 dramatiq 时才向 Redis 投递。"""
    return str((load_config().get("queue") or {}).get("backend") or "db").lower() == "dramatiq"


def schedule_job_after_commit(db: Session, job_id: str) -> None:
    """注册一次 after_commit 回调，防止未提交任务被 Worker 提前消费。"""
    if not is_dramatiq_backend_enabled():
        return

    def publish_after_commit(_session: Session) -> None:
        def publish() -> None:
            try:
                dispatch_job(job_id)
            except Exception as err:  # noqa: BLE001
                # 投递失败保持 DB pending，由独立 Dispatcher 后续补发。
                log.warning("提交后投递 Redis 失败: job=%s error=%s", job_id, err)

        # Redis 暂时不可用时不能拖慢 API 提交；补偿进程保证最终仍会投递。
        threading.Thread(target=publish, name=f"lmd-dispatch-{job_id[:8]}", daemon=True).start()

    event.listen(db, "after_commit", publish_after_commit, once=True)


def dispatch_job(job_id: str) -> dict[str, Any]:
    """向 Dramatiq 发布任务 ID，并把 Broker 消息 ID 回写 MySQL。"""
    from app.tasks.dramatiq_worker import publish_queue_job

    message = publish_queue_job(job_id)
    message_id = str(getattr(message, "message_id", "") or "")
    with session_scope() as db:
        db.execute(
            text("UPDATE queue_jobs SET dispatched_at = :now, broker_message_id = :message_id, updated_at = :now "
                 "WHERE id = :id AND status IN ('pending', 'retry') AND deleted_at IS NULL"),
            {"id": job_id, "message_id": message_id, "now": now_iso()},
        )
    return {"status": "dispatched", "job_id": job_id, "broker_message_id": message_id}


def dispatch_pending_jobs_once(*, limit: int = 100, redispatch_after_seconds: int = 60) -> dict[str, Any]:
    """补投未发送或长时间未被认领的任务；重复消息由 DB 原子认领去重。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(10, redispatch_after_seconds))).isoformat()
    with session_scope() as db:
        rows = fetch_all(
            db,
            "SELECT id FROM queue_jobs WHERE deleted_at IS NULL AND status IN ('pending', 'retry') "
            "AND (run_after IS NULL OR run_after <= :now) "
            "AND (dispatched_at IS NULL OR dispatched_at < :cutoff) "
            "ORDER BY priority DESC, created_at ASC LIMIT :limit",
            {"now": now_iso(), "cutoff": cutoff, "limit": max(1, min(int(limit), 500))},
        )
    results = []
    for row in rows:
        try:
            results.append(dispatch_job(str(row["id"])))
        except Exception as err:  # noqa: BLE001
            results.append({"status": "failed", "job_id": row["id"], "error": str(err)})
    return {"status": "completed", "count": len(results), "results": results}
