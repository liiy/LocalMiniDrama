"""尾帧衔接服务 — 契约翻译 backend-node/src/services/tailFrameLinkService.js。

提取当前分镜最新已完成视频的最后一帧，写入图片库（image_generations），
并将该帧设为下一个分镜的首帧（first_frame_image_id）。

依赖 ffmpeg（外部二进制）与真实视频文件，无法走契约对拍，但逻辑保持与 Node 一致。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import execute, fetch_one
from app.services import imageService
from app.utils.ffmpegPath import get_ffmpeg_path, get_ffprobe_path, has_local_ffmpeg

log = get_logger("lmd.tailFrameLink")


def _has_local_ffmpeg() -> bool:
    return has_local_ffmpeg()


def _get_ffmpeg_path() -> str:
    return get_ffmpeg_path()


def _get_ffprobe_path() -> str | None:
    return get_ffprobe_path()


def _resolve_storage_base(cfg: dict[str, Any]) -> Path:
    raw = str(cfg.get("storage", {}).get("local_path", "./data/storage"))
    p = Path(raw)
    return p if p.is_absolute() else Path(Path.cwd() / raw).resolve()


def link_tail_frame(db: Session, cfg: dict[str, Any], storyboard_id: int, drama_id: int) -> dict:
    """提取尾帧并衔接到下一个分镜。返回响应体字典（调用方负责包装状态码）。"""
    # 1. 获取当前分镜最新已完成视频
    video = fetch_one(
        db,
        """
        SELECT id, local_path, video_url FROM video_generations
        WHERE storyboard_id = :sb AND status = 'completed' AND deleted_at IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        {"sb": storyboard_id},
    )
    if not video or not video.get("local_path"):
        raise ValueError("当前分镜没有可用的本地视频文件")

    # 2. 找到下一个分镜
    current_sb = fetch_one(
        db, "SELECT episode_id, storyboard_number FROM storyboards WHERE id = :id",
        {"id": storyboard_id},
    )
    if not current_sb:
        raise KeyError("分镜不存在")

    next_sb = fetch_one(
        db,
        """
        SELECT id, storyboard_number FROM storyboards
        WHERE episode_id = :ep AND storyboard_number > :num AND deleted_at IS NULL
        ORDER BY storyboard_number ASC LIMIT 1
        """,
        {"ep": current_sb["episode_id"], "num": current_sb.get("storyboard_number") or 0},
    )
    if not next_sb:
        raise ValueError("没有下一个分镜可供衔接")

    # 3. 检查 ffmpeg 是否可用
    if not _has_local_ffmpeg():
        raise RuntimeError("服务器未安装 ffmpeg，无法提取视频帧")

    ffmpeg = _get_ffmpeg_path()

    # 4. 构建视频文件绝对路径
    storage_base = _resolve_storage_base(cfg)
    local_path = video["local_path"]
    video_abs = (
        Path(local_path)
        if Path(local_path).is_absolute()
        else storage_base / str(local_path).lstrip("/")
    )
    if not video_abs.exists():
        raise ValueError(f"视频文件不存在: {local_path}")

    # 5. 准备输出图片路径
    import time
    ts = int(time.time() * 1000)
    output_file_name = f"tailframe_{storyboard_id}_to_{next_sb['id']}_{ts}.jpg"
    images_dir = storage_base / "media" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    output_abs = images_dir / output_file_name
    output_rel = f"media/images/{output_file_name}"

    log.info("[尾帧衔接] 开始提取", {"from": local_path, "to": output_rel})

    # 6. 使用 ffmpeg 提取最后一帧
    result = subprocess.run(
        [
            ffmpeg, "-sseof", "-1", "-i", str(video_abs),
            "-update", "1", "-q:v", "2", "-frames:v", "1", "-y", str(output_abs),
        ],
        capture_output=True, text=True, timeout=60000,
    )
    if result.returncode != 0 or not output_abs.exists():
        log.error("[尾帧衔接] ffmpeg 失败", {"stderr": (result.stderr or "")[-500:]})
        raise RuntimeError("ffmpeg 提取帧失败: " + (result.stderr or result.stderr or "未知错误"))

    # 7. 获取图片尺寸（可选）
    width = None
    height = None
    ffprobe = _get_ffprobe_path()
    if ffprobe:
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(output_abs)],
                capture_output=True, text=True, timeout=60000,
            )
            if probe.stdout:
                parts = probe.stdout.strip().split("x")
                width = int(parts[0]) if parts and parts[0] else None
                height = int(parts[1]) if len(parts) > 1 and parts[1] else None
        except Exception:
            pass

    # 8. 在 image_generations 表创建记录
    now = timestamp()
    prompt = f"尾帧衔接：从分镜 #{current_sb.get('storyboard_number') or storyboard_id} 视频提取的最后一帧"
    files_base = str(cfg.get("files", {}).get("base_url", "") or "")
    image_url = f"{files_base.rstrip('/')}/{output_rel}" if files_base else None

    res = execute(
        db,
        """
        INSERT INTO image_generations (
            drama_id, episode_id, storyboard_id, prompt, provider, model, status,
            image_url, local_path, width, height, created_at, updated_at, completed_at
        ) VALUES (
            :drama_id, :episode_id, :storyboard_id, :prompt, :provider, :model, :status,
            :image_url, :local_path, :width, :height, :created_at, :updated_at, :completed_at
        )
        """,
        {
            "drama_id": drama_id,
            "episode_id": current_sb["episode_id"],
            "storyboard_id": next_sb["id"],
            "prompt": prompt,
            "provider": "tail-frame",
            "model": "tail-frame-extract",
            "status": "completed",
            "image_url": image_url,
            "local_path": output_rel,
            "width": width,
            "height": height,
            "created_at": now,
            "updated_at": now,
            "completed_at": now,
        },
    )
    new_image_id = res.lastrowid

    # 9. 更新下一个分镜的 first_frame_image_id
    execute(
        db,
        """
        UPDATE storyboards
        SET first_frame_image_id = :fid, image_url = :image_url,
            local_path = :local_path, updated_at = :updated_at
        WHERE id = :id
        """,
        {
            "fid": new_image_id, "image_url": image_url, "local_path": output_rel,
            "updated_at": now, "id": next_sb["id"],
        },
    )

    log.info("[尾帧衔接] 完成", {
        "from_storyboard": storyboard_id, "to_storyboard": next_sb["id"],
        "new_image_id": new_image_id,
    })

    return {
        "success": True,
        "message": "尾帧衔接成功",
        "next_storyboard_id": next_sb["id"],
        "new_first_frame_image_id": new_image_id,
        "image_url": image_url,
        "local_path": output_rel,
    }
