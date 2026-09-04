"""视频合成同步端点服务 — 契约翻译 backend-node/src/services/videoMergeService.js（同步端点子集）。

videoMerges 路由：list / create / get / delete。create 仅建记录（status='pending'）+ 建
async_tasks，不在此触发 ffmpeg 真实合并（processVideoMerge 由后台调度执行），故可契约对拍。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one
from app.services import storageLayout
from app.services import taskService
from app.services.libraryCommon import to_int_id
from app.utils.ffmpegPath import get_ffmpeg_path, has_local_ffmpeg


def row_to_item(r: dict) -> dict:
    item: dict[str, Any] = {
        "id": r.get("id"),
        "episode_id": r.get("episode_id"),
        "drama_id": r.get("drama_id"),
        "title": r.get("title"),
        "provider": r.get("provider"),
        "status": r.get("status"),
        "merged_url": r.get("merged_url"),
        "task_id": r.get("task_id"),
        "created_at": r.get("created_at"),
        "completed_at": r.get("completed_at"),
    }
    if r.get("duration") is not None:
        item["duration"] = r.get("duration")
    if r.get("error_msg") is not None:
        item["error_msg"] = r.get("error_msg")
    return item


def list_merges(db: Session, query: dict | None = None) -> list[dict]:
    query = query or {}
    where = "FROM video_merges WHERE deleted_at IS NULL"
    params: dict[str, Any] = {}
    if query.get("episode_id"):
        where += " AND episode_id = :episode_id"
        params["episode_id"] = query["episode_id"]
    if query.get("drama_id"):
        where += " AND drama_id = :drama_id"
        params["drama_id"] = query["drama_id"]
    rows = fetch_all(db, f"SELECT * {where} ORDER BY created_at DESC", params)
    return [row_to_item(r) for r in rows]


def get_merge(db: Session, merge_id: Any) -> dict | None:
    row = fetch_one(
        db,
        "SELECT * FROM video_merges WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(merge_id)},
    )
    return row_to_item(row) if row else None


def create_merge(db: Session, log, req: dict) -> dict:
    now = timestamp()
    task = taskService.create_task(db, log, "video_merge", str(req.get("episode_id") or ""))
    merge_options = req.get("merge_options")
    merge_options_json = merge_options if isinstance(merge_options, str) else (
        __import__("json").dumps(merge_options) if isinstance(merge_options, dict) else "{}"
    )
    scenes = req.get("scenes")
    scenes_json = __import__("json").dumps(scenes) if isinstance(scenes, (list, dict)) else "[]"
    res = execute(
        db,
        "INSERT INTO video_merges (episode_id, drama_id, title, provider, model, status, scenes, "
        "merge_options, task_id, created_at) VALUES (:episode_id, :drama_id, :title, :provider, "
        ":model, 'pending', :scenes, :merge_options, :task_id, :created_at)",
        {
            "episode_id": req.get("episode_id") if req.get("episode_id") is not None else 0,
            "drama_id": req.get("drama_id") if req.get("drama_id") is not None else 0,
            "title": req.get("title"),
            "provider": req.get("provider") or "ffmpeg",
            "model": req.get("model"),
            "scenes": scenes_json,
            "merge_options": merge_options_json,
            "task_id": task["id"],
            "created_at": now,
        },
    )
    return {"merge_id": res.lastrowid, "task_id": task["id"], **get_merge(db, res.lastrowid)}


def delete_merge(db: Session, log, merge_id: Any) -> bool:
    res = execute(
        db,
        "UPDATE video_merges SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL",
        {"now": timestamp(), "id": to_int_id(merge_id)},
    )
    return res.rowcount > 0


# ---------------- 异步合成处理 ----------------


def _has_local_ffmpeg() -> bool:
    """等价 Node hasLocalFfmpeg()：按优先级解析可执行文件。"""
    return has_local_ffmpeg()


def _run_ffmpeg_concat(local_paths: list, output_path: str, log) -> bool:
    """等价 Node runFfmpegConcat：用 concat demuxer 拼接。失败返回 False。"""
    if not local_paths:
        return False
    list_file = f"{output_path}.concat.txt"
    try:
        with open(list_file, "w", encoding="utf-8") as fh:
            for p in local_paths:
                safe = str(p).replace("'", "'\\''")
                fh.write(f"file '{safe}'\n")
        bin_path = get_ffmpeg_path()
        proc = subprocess.run(
            [bin_path, "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output_path],
            capture_output=True,
        )
        if proc.returncode != 0:
            log.warn("Video merge: ffmpeg failed", {"stderr": (proc.stderr or b"")[-500:].decode("utf-8", "ignore")})
            return False
        return True
    except FileNotFoundError:
        log.warn("Video merge: ffmpeg not found")
        return False
    except Exception as e:  # noqa: BLE001
        log.warn("Video merge: ffmpeg spawn error", {"error": str(e)})
        return False
    finally:
        try:
            if os.path.exists(list_file):
                os.unlink(list_file)
        except OSError:
            pass


def process_video_merge(db: Session, log, merge_id: Any, storage_root: str = "") -> None:
    """等价 Node processVideoMerge（同步版）。

    优先用 ffmpeg 真正合并；无 ffmpeg / 无本地文件时用首段 video_url 作为 merged_url（fallback）。
    完成后更新 video_merges / episodes.video_url / async_tasks 结果。
    """
    r = fetch_one(
        db,
        "SELECT * FROM video_merges WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(merge_id)},
    )
    if not r:
        return
    task_id = r.get("task_id")
    episode_id = r.get("episode_id")
    scenes: list = []
    try:
        parsed = json.loads(r.get("scenes") or "[]")
        if isinstance(parsed, list):
            scenes = parsed
    except Exception:  # noqa: BLE001
        log.warn("video merge parse scenes failed", {"merge_id": merge_id})

    now = timestamp()
    execute(db, "UPDATE video_merges SET status = :s WHERE id = :id", {"s": "processing", "id": r["id"]})

    if len(scenes) == 0:
        execute(
            db,
            "UPDATE video_merges SET status = :s, error_msg = :e WHERE id = :id",
            {"s": "failed", "e": "无有效视频片段", "id": r["id"]},
        )
        if task_id:
            taskService.update_task_error(db, task_id, "无有效视频片段")
        return

    first = scenes[0]
    merged_url_fallback = (first or {}).get("video_url") if isinstance(first, dict) else None
    if not merged_url_fallback:
        execute(
            db,
            "UPDATE video_merges SET status = :s, error_msg = :e WHERE id = :id",
            {"s": "failed", "e": "首段无视频地址", "id": r["id"]},
        )
        if task_id:
            taskService.update_task_error(db, task_id, "首段无视频地址")
        return

    total_duration = 0.0
    for s in scenes:
        try:
            total_duration += float((s or {}).get("duration") or 0)
        except (TypeError, ValueError):
            pass

    merged_relative_path = None
    # 仅当全部片段都有本地文件且 ffmpeg 可用时才真正 concat；否则保留 fallback。
    local_paths = []
    if storage_root and _has_local_ffmpeg():
        for s in scenes:
            lp = (s or {}).get("local_path")
            if lp:
                abs_p = os.path.join(storage_root, str(lp).replace("/", os.sep))
                if os.path.exists(abs_p):
                    local_paths.append(abs_p)
    if local_paths and len(local_paths) <= 100:
        sub = ""
        try:
            sub = storageLayout.get_project_storage_subdir(db, r.get("drama_id")) or ""
        except Exception:  # noqa: BLE001
            sub = ""
        merged_dir = os.path.join(storage_root, sub, "videos", "merged") if sub and sub.strip() else os.path.join(
            storage_root, "videos", "merged"
        )
        try:
            os.makedirs(merged_dir, exist_ok=True)
        except OSError:
            merged_dir = ""
        if merged_dir:
            output_name = f"merged_{int(time.time() * 1000)}.mp4"
            output_path = os.path.join(merged_dir, output_name)
            if _run_ffmpeg_concat(local_paths, output_path, log) and os.path.exists(output_path):
                merged_relative_path = (
                    os.path.join(sub, "videos", "merged", output_name) if sub and sub.strip()
                    else os.path.join("videos", "merged", output_name)
                ).replace(os.sep, "/")
                log.info("Video merge completed (ffmpeg)", {"merge_id": merge_id, "episode_id": episode_id, "output": merged_relative_path})

    merge_opts = {}
    try:
        merge_opts = json.loads(r.get("merge_options") or "{}")
    except Exception:
        merge_opts = {}

    post_need = (
        bool(merge_opts.get("burn_narration_subtitles"))
        or bool(merge_opts.get("burn_dialogue_audio"))
        or bool((merge_opts.get("watermark_text") or "").strip())
    )

    if merged_relative_path and _has_local_ffmpeg() and post_need:
        merged_abs_path = os.path.join(storage_root, str(merged_relative_path).replace("/", os.sep))
        if os.path.exists(merged_abs_path):
            from app.services import mergedEpisodePostProcess
            post = mergedEpisodePostProcess.run_merged_episode_post_process(db, log, {
                "mergedAbsPath": merged_abs_path,
                "storageRoot": storage_root,
                "scenes": scenes,
                "episodeId": episode_id,
                "mergeOpts": merge_opts,
            })
            if post.get("ok") and post.get("relativePath"):
                merged_relative_path = post.get("relativePath")
                log.info("Video merge: merged episode post-process", {"merge_id": merge_id, "out": merged_relative_path})
            elif post.get("error") and post.get("error") != "NO_POST_OPTS":
                log.warn("Video merge: post-process skipped", {"merge_id": merge_id, "err": post.get("error")})

    final_merged_url = merged_relative_path or merged_url_fallback
    execute(
        db,
        "UPDATE video_merges SET status = :s, merged_url = :u, duration = :d, completed_at = :c, error_msg = :e "
        "WHERE id = :id",
        {"s": "completed", "u": final_merged_url, "d": int(round(total_duration)) or None,
         "c": now, "e": None, "id": r["id"]},
    )
    execute(
        db,
        "UPDATE episodes SET video_url = :u, status = :s, updated_at = :c WHERE id = :id",
        {"u": final_merged_url, "s": "completed", "c": now, "id": to_int_id(episode_id)},
    )
    if task_id:
        taskService.update_task_result(
            db, task_id,
            {"merge_id": r["id"], "video_url": final_merged_url, "duration": int(round(total_duration))},
        )
    if not merged_relative_path:
        log.info("Video merge completed (first-clip fallback)", {"merge_id": merge_id, "episode_id": episode_id})
