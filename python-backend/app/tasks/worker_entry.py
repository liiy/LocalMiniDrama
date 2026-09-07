"""独立 Dramatiq Worker 模块入口。

启动命令：
  - 单一通用 Worker（推荐）：
    dramatiq app.tasks.worker_entry --queues lmd_tasks --processes 2 --threads 4
  - 全量多队列 Worker：
    dramatiq app.tasks.worker_entry --queues lmd_tasks images videos audio workflows --processes 2 --threads 4
"""
from app.tasks.dramatiq_worker import (
    execute_queue_job_actor,
    generate_audio_actor,
    generate_image_actor,
    generate_video_actor,
    workflow_step_actor,
)

# 导出 Actor 供 Dramatiq CLI 扫描；业务代码不应从本模块直接调用。
__all__ = [
    "execute_queue_job_actor",
    "generate_image_actor",
    "generate_video_actor",
    "generate_audio_actor",
    "workflow_step_actor",
]
