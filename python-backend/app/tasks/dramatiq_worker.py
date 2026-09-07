"""Dramatiq 异步任务队列与 Worker 进程。

负责承接生图 (Image)、生视频 (Video)、音频合成 (Audio) 以及工作流步骤 (Workflow Step) 等重型长任务。
提供 RedisBroker / RabbitmqBroker 支持，并在未安装或未启用 Dramatiq / Redis 时自动降级至线程池与持久化 DB 队列。
"""
from __future__ import annotations

import os
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.db.session import session_scope
from app.tasks import queue_service

log = get_logger("lmd.dramatiqWorker")

# 全局 Broker 实例与就绪状态
_broker = None
_dramatiq_available = False

try:
    import dramatiq
    from dramatiq.brokers.redis import RedisBroker
    from dramatiq.brokers.stub import StubBroker

    _dramatiq_available = True
except ImportError:
    dramatiq = None  # type: ignore
    RedisBroker = None  # type: ignore
    StubBroker = None  # type: ignore


def init_dramatiq_broker(cfg: dict[str, Any] | None = None) -> Any:
    """初始化 Dramatiq Broker 连接。

    支持从配置文件读取 Redis URL（默认 redis://127.0.0.1:6379/0）。
    若环境未安装 Redis 或 Dramatiq，则使用 StubBroker 或内部内存 Broker。
    """
    global _broker
    if not _dramatiq_available:
        log.info("Dramatiq 库未安装，启用内置持久化 DB 队列运行模式")
        return None

    if _broker is not None:
        return _broker

    cfg = cfg or load_config()
    queue_cfg = (cfg.get("queue") or {}) if isinstance(cfg, dict) else {}
    redis_url = os.environ.get("LMD_REDIS_URL") or os.environ.get("REDIS_URL") or queue_cfg.get("redis_url") or "redis://127.0.0.1:6379/0"
    # 兼容 Redis 3.x/5.x（如 Windows 本地 Redis 服务不支持 RESP3 HELLO 命令）
    if "protocol=" not in redis_url:
        sep = "&" if "?" in redis_url else "?"
        redis_url = f"{redis_url}{sep}protocol=2"

    try:
        broker = RedisBroker(url=redis_url)
        dramatiq.set_broker(broker)
        _broker = broker
        log.info("Dramatiq RedisBroker 初始化成功: %s", redis_url)
    except Exception as err:
        log.warning("Dramatiq 连接 Redis 失败 (%s)，回退至 StubBroker 模拟模式", err)
        broker = StubBroker()
        dramatiq.set_broker(broker)
        _broker = broker

    return _broker


def is_dramatiq_available() -> bool:
    """检查当前环境是否已启用 Dramatiq 消息中介。"""
    return _dramatiq_available and _broker is not None


# ---------------- 核心 Worker Actor 声明 ----------------


def execute_image_generation(job_id: str, payload: dict[str, Any], db: Session | None = None) -> dict[str, Any]:
    """生图长任务 Worker 执行体。"""
    log.info("Dramatiq Worker: 开始执行生图任务 job_id=%s", job_id)
    if db is not None:
        return _do_execute_image_generation(db, job_id, payload)
    with session_scope() as session:
        try:
            result = _do_execute_image_generation(session, job_id, payload)
            queue_service.complete_job(session, job_id, result=result)
            return result
        except Exception as err:  # noqa: BLE001
            # Dramatiq 直接执行时由本层维护队列终态；DB Runner 路径则由 Runner 统一处理。
            failed = queue_service.fail_job(session, job_id, str(err), retryable=True)
            return {"status": (failed or {}).get("status") or "failed", "error": str(err)}


def _do_execute_image_generation(db: Session, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services import imageClient, taskService

    async_task_id = payload.get("async_task_id")
    if async_task_id:
        taskService.update_task_status(db, async_task_id, "processing", 20, "正在调用生图引擎...")

    # 真实生成异常必须向上抛出，由队列层进入重试或失败，禁止伪造成功媒体地址。
    prompt = payload.get("prompt") or ""
    return imageClient.call_image_api(
        db,
        log,
        {
            "prompt": prompt,
            "model": payload.get("model"),
            "size": payload.get("size") or "1024x1024",
            "reference_image_urls": payload.get("reference_image_urls"),
            **(payload.get("options") or {}),
        },
    )


def execute_video_generation(job_id: str, payload: dict[str, Any], db: Session | None = None) -> dict[str, Any]:
    """生视频长任务 Worker 执行体。"""
    log.info("Dramatiq Worker: 开始执行生视频任务 job_id=%s", job_id)
    if db is not None:
        return _do_execute_video_generation(db, job_id, payload)
    with session_scope() as session:
        try:
            result = _do_execute_video_generation(session, job_id, payload)
            queue_service.complete_job(session, job_id, result=result)
            return result
        except Exception as err:  # noqa: BLE001
            failed = queue_service.fail_job(session, job_id, str(err), retryable=True)
            return {"status": (failed or {}).get("status") or "failed", "error": str(err)}


def _do_execute_video_generation(db: Session, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services import taskService, videoClient

    async_task_id = payload.get("async_task_id")
    if async_task_id:
        taskService.update_task_status(db, async_task_id, "processing", 15, "正在向视频生成引擎提交任务...")

    # 与生图任务保持一致：调用失败交给队列重试策略处理，不能降级成假视频。
    return videoClient.call_video_api(
        db,
        log,
        {
            "prompt": payload.get("prompt") or "",
            "model": payload.get("model"),
            **(payload.get("options") or {}),
        },
    )


def execute_audio_generation(job_id: str, payload: dict[str, Any], db: Session | None = None) -> dict[str, Any]:
    """音频合成 / 配乐长任务 Worker 执行体。"""
    log.info("Dramatiq Worker: 开始执行音频合成任务 job_id=%s", job_id)
    if db is not None:
        return _do_execute_audio_generation(db, job_id, payload)
    with session_scope() as session:
        try:
            result = _do_execute_audio_generation(session, job_id, payload)
            queue_service.complete_job(session, job_id, result=result)
            return result
        except Exception as err:  # noqa: BLE001
            failed = queue_service.fail_job(session, job_id, str(err), retryable=True)
            return {"status": (failed or {}).get("status") or "failed", "error": str(err)}


def _do_execute_audio_generation(db: Session, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services import audioDesignService, taskService

    drama_id = payload.get("drama_id")
    episode_id = payload.get("episode_id")
    async_task_id = payload.get("async_task_id")

    if async_task_id:
        taskService.update_task_status(db, async_task_id, "processing", 30, "正在生成声音档案与配乐...")

    if not drama_id:
        raise ValueError("音频设计任务缺少 drama_id")
    return audioDesignService.generate_voice_music_design(
        db,
        drama_id=int(drama_id),
        episode_id=int(episode_id) if episode_id else None,
    )


def execute_workflow_step_task(job_id: str, payload: dict[str, Any], db: Session | None = None) -> dict[str, Any]:
    """工作流 DAG 节点执行体。"""
    log.info("Dramatiq Worker: 开始执行工作流节点 job_id=%s", job_id)
    if db is not None:
        return _do_execute_workflow_step_task(db, job_id, payload)
    with session_scope() as session:
        return _do_execute_workflow_step_task(session, job_id, payload)


def _do_execute_workflow_step_task(db: Session, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.tasks import worker_runner

    job = queue_service.get_queue_job(db, job_id)
    if not job:
        raise ValueError(f"Queue job {job_id} 不存在")
    return worker_runner.execute_claimed_job(db, job, auto_advance=True)


def execute_queue_job(job_id: str) -> dict[str, Any]:
    """独立 Worker 的统一执行入口，先按 ID 原子认领再调用白名单 Runner。"""
    import os
    import socket

    from app.tasks import worker_runner

    worker_id = f"dramatiq:{socket.gethostname()}:{os.getpid()}"
    with session_scope() as db:
        job = queue_service.claim_job_by_id(db, job_id, worker_id=worker_id)
        if not job:
            return {"status": "duplicate_or_unavailable", "job_id": job_id}
        # 先提交认领状态，耗时模型调用不占用数据库行锁。
        db.commit()
        return worker_runner.execute_claimed_job(db, job, auto_advance=True)


# Actor 注册前设置 RedisBroker，确保 Dramatiq CLI 与 API 投递端使用同一 Broker。
init_dramatiq_broker()

# 如果 Dramatiq 库可用，使用 @dramatiq.actor 装饰封装为分布式 Actor
# 任务状态与执行结果均直接持久化至 MySQL，Actor 无需返回值以避免触发 Dramatiq 无 Results 中间件的告警
if _dramatiq_available and dramatiq is not None:

    @dramatiq.actor(queue_name="lmd_tasks", max_retries=0, time_limit=1800000)
    def execute_queue_job_actor(job_id: str) -> None:
        execute_queue_job(job_id)

    @dramatiq.actor(queue_name="images", max_retries=3, time_limit=300000)
    def generate_image_actor(job_id: str, payload: dict[str, Any]) -> None:
        execute_image_generation(job_id, payload)

    @dramatiq.actor(queue_name="videos", max_retries=3, time_limit=600000)
    def generate_video_actor(job_id: str, payload: dict[str, Any]) -> None:
        execute_video_generation(job_id, payload)

    @dramatiq.actor(queue_name="audio", max_retries=3, time_limit=300000)
    def generate_audio_actor(job_id: str, payload: dict[str, Any]) -> None:
        execute_audio_generation(job_id, payload)

    @dramatiq.actor(queue_name="workflows", max_retries=2, time_limit=600000)
    def workflow_step_actor(job_id: str, payload: dict[str, Any]) -> None:
        execute_workflow_step_task(job_id, payload)

else:
    execute_queue_job_actor = None  # type: ignore
    generate_image_actor = None  # type: ignore
    generate_video_actor = None  # type: ignore
    generate_audio_actor = None  # type: ignore
    workflow_step_actor = None  # type: ignore


def publish_queue_job(job_id: str):
    """发布统一任务消息；业务载荷始终从 MySQL 读取，避免 Redis 与 DB 数据漂移。"""
    init_dramatiq_broker()
    if not execute_queue_job_actor:
        raise RuntimeError("Dramatiq 未安装，无法投递 Redis 队列")
    return execute_queue_job_actor.send(job_id)


def dispatch_async_task(
    task_type: str,
    job_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """统一任务分发入口。

    优先通过 Dramatiq Actor 异步派发至分布式 Worker 进程。
    若 Dramatiq 未启用或不可用，则通过后台线程或 DB 队列认领执行。
    """
    if _dramatiq_available and _broker is not None:
        try:
            if task_type in ("image.generate", "generate.image") and generate_image_actor:
                generate_image_actor.send(job_id, payload)
                return {"dispatched": True, "engine": "dramatiq", "actor": "generate_image_actor", "job_id": job_id}
            if task_type in ("video.generate", "generate.video") and generate_video_actor:
                generate_video_actor.send(job_id, payload)
                return {"dispatched": True, "engine": "dramatiq", "actor": "generate_video_actor", "job_id": job_id}
            if task_type in ("audio.generate", "generate.audio") and generate_audio_actor:
                generate_audio_actor.send(job_id, payload)
                return {"dispatched": True, "engine": "dramatiq", "actor": "generate_audio_actor", "job_id": job_id}
            if task_type.startswith("workflow.") and workflow_step_actor:
                workflow_step_actor.send(job_id, payload)
                return {"dispatched": True, "engine": "dramatiq", "actor": "workflow_step_actor", "job_id": job_id}
        except Exception as err:
            log.warning("Dramatiq 派发任务失败，降级为线程池执行: %s", err)

    # 降级分支：使用独立 Daemon 线程异步执行
    def _runner_thread():
        try:
            if task_type in ("image.generate", "generate.image"):
                execute_image_generation(job_id, payload)
            elif task_type in ("video.generate", "generate.video"):
                execute_video_generation(job_id, payload)
            elif task_type in ("audio.generate", "generate.audio"):
                execute_audio_generation(job_id, payload)
            elif task_type.startswith("workflow."):
                execute_workflow_step_task(job_id, payload)
            else:
                log.info("任务 %s 存入 DB 队列等待 worker 认领", job_id)
        except Exception as e:
            log.error("后台任务执行失败: %s", e)

    t = threading.Thread(target=_runner_thread, daemon=True)
    t.start()
    return {"dispatched": True, "engine": "thread_fallback", "job_id": job_id}
