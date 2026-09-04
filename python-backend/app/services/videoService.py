"""视频生成端点服务 — 契约翻译 backend-node/src/services/videoService.js。

backend-node 的 /videos 读写 video_generations 表。
同步端点：list / get / delete / from_image / episode_batch。

`create` 与 `resumePoll` 已接入真实生成链路：写库后通过 workerService 线程池后台执行
process_video_generation / resume_poll_for_video_generation（等价 Node 的 setImmediate）。
worker 线程用独立 Session，故入队前必须先 db.commit()（Node 的 better-sqlite3 是语句级
自动提交，Python 的请求级 Session 不是）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one
from app.services import taskService
from app.services.libraryCommon import js_parse_int, to_int_id


def _now() -> str:
    return timestamp()


def _has_provider_task_id(r: dict) -> bool:
    v = r.get("provider_task_id")
    return bool(v and str(v).strip())


def row_to_item(r: dict) -> dict:
    item = {
        "id": r.get("id"),
        "storyboard_id": r.get("storyboard_id"),
        "drama_id": r.get("drama_id"),
        "provider": r.get("provider"),
        "prompt": r.get("prompt"),
        "model": r.get("model"),
        "image_url": r.get("image_url"),
        "video_url": r.get("video_url"),
        "local_path": r.get("local_path"),
        "status": r.get("status"),
        "task_id": r.get("task_id"),
        "error_msg": r.get("error_msg"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "completed_at": r.get("completed_at"),
        "can_resume_poll": r.get("status") == "failed" and _has_provider_task_id(r),
    }
    return item


def list_videos(db: Session, query: dict | None = None) -> tuple[list[dict], int, int, int]:
    query = query or {}
    where = "FROM video_generations WHERE deleted_at IS NULL"
    params: dict[str, Any] = {}
    if query.get("drama_id"):
        where += " AND drama_id = :drama_id"
        params["drama_id"] = query["drama_id"]
    if query.get("storyboard_id"):
        where += " AND storyboard_id = :storyboard_id"
        params["storyboard_id"] = query["storyboard_id"]
    if query.get("status") == "processing":
        recent_cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).strftime("%Y-%m-%dT%H:%M:%S")
        where += (
            " AND (status = 'processing' OR (status IN ('completed','failed') "
            "AND updated_at >= :recent_cutoff))"
        )
        params["recent_cutoff"] = recent_cutoff
    elif query.get("status"):
        where += " AND status = :status"
        params["status"] = query["status"]

    total = db.execute(
        __import__("sqlalchemy").text(f"SELECT COUNT(*) AS total {where}"), params
    ).scalar() or 0
    page = max(1, js_parse_int(query.get("page"), 1))
    page_size = min(100, max(1, js_parse_int(query.get("page_size"), 20)))
    offset = (page - 1) * page_size
    p = dict(params)
    p["_limit"] = page_size
    p["_offset"] = offset
    rows = fetch_all(
        db,
        f"SELECT * {where} ORDER BY created_at DESC LIMIT :_limit OFFSET :_offset",
        p,
    )
    return [row_to_item(r) for r in rows], total, page, page_size


def get_video(db: Session, video_id: Any) -> dict | None:
    row = fetch_one(
        db,
        "SELECT * FROM video_generations WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(video_id)},
    )
    return row_to_item(row) if row else None


def delete_video(db: Session, video_id: Any) -> bool:
    res = execute(
        db,
        "UPDATE video_generations SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL",
        {"now": _now(), "id": to_int_id(video_id)},
    )
    return res.rowcount > 0


def create_from_image_task(db: Session, log, image_gen_id: Any) -> dict:
    """等价 videos.js fromImage：仅建 video_generation 任务，返回 { task_id }。"""
    task = taskService.create_task(db, log, "video_generation", image_gen_id)
    return {"task_id": task["id"]}


def resume_failed_video_poll(db: Session, log, video_id: Any) -> dict:
    """等价 videoService.resumeFailedVideoPoll：同步置回 processing 并返回记录。

    真正的上游轮询交给 workerService 后台执行（_resume_job），此处只做 Node 的同步部分：
    - 404 '记录不存在'
    - processing + 有 provider_task_id → 直接返回（Node 会 reattach 轮询）
    - 非 failed → 400 '仅失败的视频任务可继续查询'
    - 无 provider_task_id → 400 '缺少厂商任务 ID，无法继续查询，请重新生成'
    - 否则：status='processing'/error_msg=''、补建 task、updateTaskStatus(processing,10)、清空 error
    """
    vid = to_int_id(video_id)
    if not vid:
        return {"ok": False, "status": 404, "error": "记录不存在"}
    row = fetch_one(
        db,
        "SELECT * FROM video_generations WHERE id = :id AND deleted_at IS NULL",
        {"id": vid},
    )
    if not row:
        return {"ok": False, "status": 404, "error": "记录不存在"}

    now = _now()
    if row.get("status") == "processing" and _has_provider_task_id(row):
        # Node 在此 reattach 轮询；等价提交后台任务（先提交，worker 用独立 Session）
        db.commit()
        from app.services import workerService

        workerService.submit(_resume_job, vid)
        return {"ok": True, "item": row_to_item(row)}
    if row.get("status") != "failed":
        return {"ok": False, "status": 400, "error": "仅失败的视频任务可继续查询"}
    if not _has_provider_task_id(row):
        return {"ok": False, "status": 400, "error": "缺少厂商任务 ID，无法继续查询，请重新生成"}

    try:
        execute(
            db,
            "UPDATE video_generations SET status = :s, error_msg = :e, updated_at = :t WHERE id = :id",
            {"s": "processing", "e": "", "t": now, "id": vid},
        )
    except Exception as e:  # noqa: BLE001
        if "error_msg" in str(e):
            execute(
                db,
                "UPDATE video_generations SET status = :s, updated_at = :t WHERE id = :id",
                {"s": "processing", "t": now, "id": vid},
            )
        else:
            raise

    task_id = row.get("task_id")
    if not task_id:
        task = taskService.create_task(db, log, "video_generation", str(row.get("drama_id") or ""))
        task_id = task["id"]
        execute(
            db,
            "UPDATE video_generations SET task_id = :tid, updated_at = :t WHERE id = :id",
            {"tid": task_id, "t": now, "id": vid},
        )
    taskService.update_task_status(db, task_id, "processing", 10, "继续查询上游任务…")
    try:
        execute(db, "UPDATE async_tasks SET error = NULL WHERE id = :id", {"id": task_id})
    except Exception:  # noqa: BLE001
        pass

    log.info("Resume failed video poll requested", extra={
        "video_gen_id": vid, "provider_task_id": str(row.get("provider_task_id") or "").strip(),
        "task_id": task_id,
    })
    # Node 在此 setImmediate(resumePollForVideoGeneration)；先提交，worker 用独立 Session
    db.commit()
    from app.services import workerService

    workerService.submit(_resume_job, vid)

    item = get_video(db, vid)
    return {"ok": True, "item": item or row_to_item(row)}


# ── create（POST /videos）：建任务 + 插入 processing 记录，随后后台跑真实生成 ──

_KLING_OMNI_ASPECT_RATIOS = {"9:16", "16:9", "1:1", "4:3", "3:4", "3:2", "2:3"}
_ASPECT_ALIASES = {
    "portrait": "9:16",
    "landscape": "16:9",
    "square": "1:1",
    "vertical": "9:16",
    "horizontal": "16:9",
}


def normalize_aspect_ratio_for_api(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().replace("\uff1a", ":")
    for ch in ("\u00d7", "x", "X", "\uff0a", "*"):
        s = s.replace(ch, ":")
    s = re.sub(r"\s+", "", s)
    if not s:
        return None
    s = _ASPECT_ALIASES.get(s.lower(), s)
    return s if s in _KLING_OMNI_ASPECT_RATIOS else None


def extract_ids(raw: Any) -> list:
    """等价 videoService.extractIds：解析 characters JSON，对象取 id，过滤非有限数。"""
    if not raw:
        return []
    try:
        arr = json.loads(raw)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for c in arr:
        v = c.get("id") if isinstance(c, dict) else c
        try:
            n = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            continue
        if math.isfinite(n):
            out.append(v)
    return out


def _drama_aspect_ratio(db: Session, drama_id: Any) -> str | None:
    row = fetch_one(
        db,
        "SELECT metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
        {"id": drama_id},
    )
    if not row or not row.get("metadata"):
        return None
    meta = row["metadata"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            return None
    if isinstance(meta, dict) and meta.get("aspect_ratio"):
        return normalize_aspect_ratio_for_api(meta["aspect_ratio"])
    return None


def create_video(db: Session, log, body: dict) -> dict:
    """等价 videos.js create：建 video_generation 任务 + 插入 processing 记录。

    返回 get_video(item)（或 { id, task_id, status:'processing' } 兜底）。
    """
    now = _now()
    task = taskService.create_task(db, log, "video_generation", str(body.get("drama_id") or ""))
    drama_id = js_parse_int(body.get("drama_id"), 0) or 0
    sb_raw = body.get("storyboard_id")
    storyboard_id = to_int_id(sb_raw) if sb_raw is not None else None
    provider = body.get("provider") or "chatfire"

    prompt = body.get("prompt") or ""
    style = str(body.get("style") or "").strip()
    if style:
        if style.lower() not in str(prompt).lower():
            prompt = f"{prompt}. Style: {style}" if prompt else f"Style: {style}"

    model = body.get("model")
    duration = body.get("duration")

    aspect_ratio = None
    ar = body.get("aspect_ratio")
    if ar is not None and str(ar).strip() != "":
        aspect_ratio = normalize_aspect_ratio_for_api(ar)
    if not aspect_ratio and drama_id:
        try:
            aspect_ratio = _drama_aspect_ratio(db, drama_id)
        except Exception:
            aspect_ratio = None

    resolution = body.get("resolution")
    seed_raw = body.get("seed")
    seed = js_parse_int(seed_raw, None) if seed_raw is not None else None
    camera_raw = body.get("camera_fixed")
    camera_fixed = (1 if camera_raw else 0) if camera_raw is not None else None
    watermark_raw = body.get("watermark")
    watermark = (1 if watermark_raw else 0) if watermark_raw is not None else 0
    image_url = body.get("image_url")
    first_frame_url = body.get("first_frame_url") or body.get("first_frame_local_path")
    last_frame_url = body.get("last_frame_url") or body.get("last_frame_local_path")

    ref_images: list = []
    if not last_frame_url:
        boards_row = fetch_one(
            db,
            "SELECT characters FROM storyboards WHERE id = :id",
            {"id": storyboard_id},
        )
        if not boards_row:
            # Node 此处直接读 boardsRow.characters 会抛 TypeError，由路由 catch 转 500
            raise ValueError("storyboard not found for reference images")
        ids = extract_ids(boards_row.get("characters"))
        if ids:
            ph = ", ".join(":id" + str(i) for i in range(len(ids)))
            p = {f"id{i}": v for i, v in enumerate(ids)}
            char_rows = fetch_all(
                db, f"SELECT id, local_path FROM characters WHERE id IN ({ph})", p
            )
            path_map = {int(r["id"]): r.get("local_path") for r in char_rows}
            ref_images = [path_map.get(int(i)) for i in ids]
            ref_images = [x for x in ref_images if x]
        prop_rows = fetch_all(
            db,
            "SELECT prop_id FROM storyboard_props WHERE storyboard_id = :sid",
            {"sid": storyboard_id},
        )
        prop_ids = [r["prop_id"] for r in prop_rows]
        if prop_ids:
            ph = ", ".join(":pid" + str(i) for i in range(len(prop_ids)))
            p = {f"pid{i}": v for i, v in enumerate(prop_ids)}
            prop_imgs = fetch_all(
                db, f"SELECT id, local_path FROM props WHERE id IN ({ph})", p
            )
            prop_map = {int(r["id"]): r.get("local_path") for r in prop_imgs}
            ordered = [prop_map.get(int(i)) for i in prop_ids]
            ref_images.extend([x for x in ordered if x])

    body_refs = body.get("reference_image_urls")
    reference_image_urls = list(body_refs if isinstance(body_refs, list) else []) + list(ref_images)
    reference_image_urls = reference_image_urls[:10]
    ref_images_json = json.dumps(reference_image_urls)

    res = execute(
        db,
        """
        INSERT INTO video_generations (
            drama_id, storyboard_id, provider, prompt, model, duration, aspect_ratio,
            resolution, seed, camera_fixed, watermark, image_url, first_frame_url,
            last_frame_url, reference_image_urls, status, task_id, created_at, updated_at
        ) VALUES (
            :drama_id, :storyboard_id, :provider, :prompt, :model, :duration, :aspect_ratio,
            :resolution, :seed, :camera_fixed, :watermark, :image_url, :first_frame_url,
            :last_frame_url, :reference_image_urls, 'processing', :task_id, :created_at, :updated_at
        )
        """,
        {
            "drama_id": drama_id,
            "storyboard_id": storyboard_id,
            "provider": provider,
            "prompt": prompt,
            "model": model,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "seed": seed,
            "camera_fixed": camera_fixed,
            "watermark": watermark,
            "image_url": image_url,
            "first_frame_url": first_frame_url,
            "last_frame_url": last_frame_url,
            "reference_image_urls": ref_images_json,
            "task_id": task["id"],
            "created_at": now,
            "updated_at": now,
        },
    )
    video_gen_id = res.lastrowid
    item = get_video(db, video_gen_id)
    result = item or {"id": video_gen_id, "task_id": task["id"], "status": "processing"}

    # 等价 Node createVideo 末尾的 setImmediate(processVideoGeneration)。
    # 先提交：worker 线程用独立 Session，未提交的行它对不可见。
    db.commit()
    from app.services import workerService

    workerService.submit(process_video_generation, video_gen_id)
    return result


# ── 后台生成链路（等价 Node videoService 的 processVideoGeneration 及下游）──

_VIDEO_EXT_RE = re.compile(r"\.(mp4|webm|mov)$", re.IGNORECASE)

_TARGET_VIDEO_PIXELS = {
    "16:9": (2560, 1440),
    "9:16": (1440, 2560),
    "1:1": (1920, 1920),
    "4:3": (1920, 1440),
    "3:4": (1440, 1920),
    "3:2": (2560, 1708),
    "2:3": (1708, 2560),
    "21:9": (2560, 1080),
}


def resolve_remote_video_url(video_url, fallback_error=None) -> dict:
    """等价 resolveRemoteVideoUrl：校验 http(s) 视频地址，否则给出错误文案。"""
    from app.services import videoClient

    if video_url and videoClient.is_plausible_http_video_url(video_url):
        return {"ok": True, "video_url": str(video_url).strip()}
    if video_url:
        return {"ok": False, "error": str(fallback_error or video_url)[:500]}
    return {"ok": False, "error": str(fallback_error or "超时或失败")[:500]}


def set_video_gen_failed(db: Session, video_gen_id, error_msg, now: str) -> None:
    """等价 setVideoGenFailed：无 error_msg 列时降级只更新 status/updated_at。"""
    try:
        execute(
            db,
            "UPDATE video_generations SET status = :s, error_msg = :e, updated_at = :t WHERE id = :id",
            {"s": "failed", "e": str(error_msg or "")[:500], "t": now, "id": video_gen_id},
        )
    except Exception as e:  # noqa: BLE001
        if "error_msg" in str(e):
            execute(
                db,
                "UPDATE video_generations SET status = :s, updated_at = :t WHERE id = :id",
                {"s": "failed", "t": now, "id": video_gen_id},
            )
        else:
            raise


def resolve_storage_path(cfg: dict) -> str:
    """等价 resolveStoragePath。"""
    raw = (cfg.get("storage") or {}).get("local_path") or "./data/storage"
    return raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)


def _resolve_videos_dir(storage_path: str, project_subdir):
    sub = str(project_subdir).strip() if project_subdir else ""
    if sub:
        return os.path.join(storage_path, sub, "videos"), f"{sub.replace(os.sep, '/')}/videos"
    return os.path.join(storage_path, "videos"), "videos"


def download_video_to_local(storage_path: str, video_url, video_gen_id, log, project_subdir=None) -> str | None:
    """等价 downloadVideoToLocal：返回相对 storage 根的路径，失败返回 None。"""
    import uuid

    if not video_url or not isinstance(video_url, str):
        return None
    directory, rel_prefix = _resolve_videos_dir(storage_path, project_subdir)
    try:
        os.makedirs(directory, exist_ok=True)
        m = _VIDEO_EXT_RE.search(str(video_url).split("?")[0])
        ext = (m.group(1) if m else "mp4").lower()
        name = f"vg_{video_gen_id}_{uuid.uuid4().hex[:8]}.{ext}"
        file_path = os.path.join(directory, name)
        status, buf, _ = _http_get_bytes(video_url)
        if not (200 <= status < 300):
            log.warn("Download video failed", extra={"status": status, "video_gen_id": video_gen_id})
            return None
        with open(file_path, "wb") as fh:
            fh.write(buf)
        relative_path = f"{rel_prefix}/{name}".replace("\\", "/")
        log.info("Video saved to local", extra={
            "video_gen_id": video_gen_id, "local_path": relative_path,
            "project_subdir": project_subdir or "(root)",
        })
        return relative_path
    except Exception as e:  # noqa: BLE001
        log.warn("Download video error", extra={"video_gen_id": video_gen_id, "reason": str(e)})
        return None


def _http_get_bytes(url: str) -> tuple[int, bytes, str]:
    import httpx

    resp = httpx.get(url, timeout=300.0, follow_redirects=True)
    return resp.status_code, resp.content, (resp.headers.get("content-type") or "").split(";")[0].strip()


def target_video_pixels_for_aspect(aspect_ratio) -> tuple[int, int]:
    """等价 targetVideoPixelsForAspect：偶数像素，便于 H.264。"""
    r = str(aspect_ratio or "16:9").strip()
    if r in _TARGET_VIDEO_PIXELS:
        return _TARGET_VIDEO_PIXELS[r]
    m = re.match(r"^(\d+)\s*:\s*(\d+)$", r)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0 and a != b:
            if a > b:
                w = 2560
                return w, max(2, round((w * b) / a / 2) * 2)
            h = 2560
            return max(2, round((h * a) / b / 2) * 2), h
    return 1280, 720


def normalize_video_file_to_target_pixels(abs_path, target_w, target_h, log, video_gen_id) -> bool:
    """等价 normalizeVideoFileToTargetPixels：ffmpeg 缩放+黑边；无 ffmpeg 则跳过。"""
    import subprocess
    import uuid
    from app.utils.ffmpegPath import get_ffmpeg_path, has_local_ffmpeg

    if not abs_path or not target_w or not target_h or not os.path.exists(abs_path):
        return False
    if not has_local_ffmpeg():
        log.info("[视频] 未找到 ffmpeg，跳过画幅归一化", extra={"video_gen_id": video_gen_id})
        return False
    ffmpeg = get_ffmpeg_path()
    vf = (f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
          f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black")
    tmp_out = abs_path + ".norm-" + uuid.uuid4().hex[:8] + (os.path.splitext(abs_path)[1] or ".mp4")
    base_args = [ffmpeg, "-y", "-i", abs_path, "-vf", vf, "-c:v", "libx264", "-preset", "fast",
                 "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    try:
        r = subprocess.run(base_args + ["-c:a", "copy", tmp_out], capture_output=True)
        if r.returncode != 0:
            r = subprocess.run(base_args + ["-an", tmp_out], capture_output=True)
        if r.returncode != 0:
            log.warn("[视频] 画幅归一化失败（保留原文件）", extra={
                "video_gen_id": video_gen_id, "stderr": (r.stderr or b"")[-500:].decode("utf-8", "ignore"),
            })
            _safe_unlink(tmp_out)
            return False
        os.unlink(abs_path)
        os.rename(tmp_out, abs_path)
        log.info("[视频] 已统一画幅尺寸", extra={"video_gen_id": video_gen_id, "w": target_w, "h": target_h})
        return True
    except Exception as e:  # noqa: BLE001
        log.warn("[视频] 画幅归一化异常", extra={"video_gen_id": video_gen_id, "reason": str(e)})
        _safe_unlink(tmp_out)
        return False


def _safe_unlink(p) -> None:
    try:
        if p and os.path.exists(p):
            os.unlink(p)
    except OSError:
        pass


def maybe_normalize_video_after_download(storage_path, local_path, row, video_gen_id, log) -> None:
    if not local_path:
        return
    abs_path = os.path.join(storage_path, local_path)
    if not os.path.exists(abs_path):
        return
    target_w, target_h = target_video_pixels_for_aspect(row.get("aspect_ratio"))
    normalize_video_file_to_target_pixels(abs_path, target_w, target_h, log, video_gen_id)


def finalize_successful_video(db: Session, log, video_gen_id, row, row_for_aspect, video_url, log_label="") -> None:
    """等价 finalizeSuccessfulVideo：落盘 → 归一化 → 回写 video_generations / storyboards / task。"""
    now = _now()
    local_path = None
    try:
        from app.core.config import load_config

        from app.services import storageLayout

        cfg = load_config()
        storage_path = resolve_storage_path(cfg)
        project_subdir = storageLayout.get_project_storage_subdir(db, row.get("drama_id"))
        local_path = download_video_to_local(storage_path, video_url, video_gen_id, log, project_subdir)
        maybe_normalize_video_after_download(storage_path, local_path, row_for_aspect, video_gen_id, log)
    except Exception as e:  # noqa: BLE001
        log.warn("finalizeSuccessfulVideo 落盘失败", extra={"video_gen_id": video_gen_id, "reason": str(e)})

    try:
        execute(
            db,
            "UPDATE video_generations SET status = :s, video_url = :u, local_path = :lp, "
            "completed_at = :c, updated_at = :c WHERE id = :id",
            {"s": "completed", "u": video_url, "lp": local_path, "c": now, "id": video_gen_id},
        )
    except Exception as e:  # noqa: BLE001
        if "completed_at" in str(e):
            execute(
                db,
                "UPDATE video_generations SET status = :s, video_url = :u, local_path = :lp, "
                "updated_at = :c WHERE id = :id",
                {"s": "completed", "u": video_url, "lp": local_path, "c": now, "id": video_gen_id},
            )
        else:
            raise

    if row.get("storyboard_id"):
        try:
            execute(
                db,
                "UPDATE storyboards SET video_url = :u, local_path = :lp, updated_at = :c WHERE id = :id",
                {"u": video_url, "lp": local_path, "c": now, "id": row["storyboard_id"]},
            )
            log.info("Updated storyboard video" + (f" ({log_label})" if log_label else ""), extra={
                "storyboard_id": row["storyboard_id"], "video_url": video_url,
            })
        except Exception:  # noqa: BLE001
            pass

    if row.get("task_id"):
        taskService.update_task_result(db, row["task_id"], {
            "video_generation_id": video_gen_id,
            "video_url": video_url,
            "status": "completed",
        })
    log.info("Video generation completed" + (f" ({log_label})" if log_label else ""), extra={
        "id": video_gen_id, "video_url": video_url, "local_path": local_path,
    })


def poll_provider_task_and_finalize(db: Session, log, video_gen_id, row, row_for_aspect, provider_task_id, config) -> None:
    """等价 pollProviderTaskAndFinalize。"""
    from app.core.config import load_config

    from app.services import videoClient

    cfg = load_config()
    poll_interval_ms = 10_000
    gen_cfg = (cfg.get("video_generation") or {})
    timeout_minutes = _to_float(gen_cfg.get("timeout_minutes"), 10)
    poll_max_attempts = max(1, math.ceil((timeout_minutes * 60 * 1000) / poll_interval_ms))

    poll_result = videoClient.poll_video_task(
        log, video_gen_id, provider_task_id, config, poll_max_attempts, poll_interval_ms
    )
    now = _now()
    polled = resolve_remote_video_url(poll_result.get("video_url"), poll_result.get("error"))
    if polled["ok"]:
        finalize_successful_video(db, log, video_gen_id, row, row_for_aspect, polled["video_url"], "after poll")
    else:
        set_video_gen_failed(db, video_gen_id, polled["error"], now)
        if row.get("task_id"):
            taskService.update_task_error(db, row["task_id"], polled["error"])
        log.error("Video generation failed (after poll)", extra={"id": video_gen_id, "error": polled["error"]})


def resume_poll_for_video_generation(db: Session, log, video_gen_id) -> None:
    """等价 resumePollForVideoGeneration：轮询前须先将记录置为 processing。"""
    from app.services import videoClient
    from app.services import workerService

    row = fetch_one(
        db,
        "SELECT * FROM video_generations WHERE id = :id AND deleted_at IS NULL",
        {"id": to_int_id(video_gen_id)},
    )
    if not row or row.get("status") != "processing":
        return
    provider_task_id = str(row.get("provider_task_id") or "").strip()
    if not provider_task_id:
        return

    config = videoClient.get_default_video_config(db, row.get("model"))
    if not config:
        now = _now()
        set_video_gen_failed(db, video_gen_id, "未配置视频模型", now)
        if row.get("task_id"):
            taskService.update_task_error(db, row["task_id"], "未配置视频模型")
        return

    if not workerService.begin("video_poll", video_gen_id):
        return
    log.info("Resuming video generation poll", extra={
        "video_gen_id": video_gen_id, "provider_task_id": provider_task_id,
    })
    try:
        aspect = row.get("aspect_ratio")
        normalized = normalize_aspect_ratio_for_api(aspect) if aspect else None
        row_for_aspect = {**row, "aspect_ratio": normalized or row.get("aspect_ratio")}
        poll_provider_task_and_finalize(db, log, video_gen_id, row, row_for_aspect, provider_task_id, config)
    except Exception as e:  # noqa: BLE001
        now = _now()
        set_video_gen_failed(db, video_gen_id, str(e), now)
        if row.get("task_id"):
            taskService.update_task_error(db, row["task_id"], str(e))
        log.error("Video generation resume poll error", extra={"id": video_gen_id, "reason": str(e)})
    finally:
        workerService.end("video_poll", video_gen_id)


def resume_processing_video_generations(db: Session, log) -> None:
    """等价 resumeProcessingVideoGenerations：启动时恢复。

    - 无 provider_task_id 的 processing → 判为中断，标 failed
    - 有 provider_task_id 的 → 重新挂上轮询
    """
    from app.services import workerService

    stuck = fetch_all(
        db,
        "SELECT id, task_id FROM video_generations WHERE status = 'processing' AND deleted_at IS NULL "
        "AND (provider_task_id IS NULL OR TRIM(provider_task_id) = '')",
    )
    stuck_msg = "服务重启后无法恢复轮询（缺少厂商任务 ID），请重新生成"
    for s in stuck:
        now = _now()
        set_video_gen_failed(db, s["id"], stuck_msg, now)
        if s.get("task_id"):
            taskService.update_task_error(db, s["task_id"], stuck_msg)
        log.warn("Marked interrupted video generation as failed", extra={"video_gen_id": s["id"]})

    resumable = fetch_all(
        db,
        "SELECT id FROM video_generations WHERE status = 'processing' AND deleted_at IS NULL "
        "AND provider_task_id IS NOT NULL AND TRIM(provider_task_id) != ''",
    )
    if resumable:
        log.info("Resuming video generation polls", extra={"count": len(resumable)})
    for r in resumable:
        workerService.submit(_resume_job, r["id"])


def _resume_job(video_gen_id) -> None:
    """worker 线程内执行 resume（自建 Session）。"""
    from app.core.logger import get_logger
    from app.services import workerService

    log = get_logger("lmd.videoService")
    try:
        with workerService.session_scope() as db:
            resume_poll_for_video_generation(db, log, video_gen_id)
    except Exception as e:  # noqa: BLE001
        log.error("Resume poll job failed", extra={"video_gen_id": video_gen_id, "reason": str(e)})


def process_video_generation(video_gen_id) -> None:
    """等价 processVideoGeneration：worker 线程内执行，自建 Session。

    调用方（create_video / 启动恢复）用 workerService.submit 触发，
    对应 Node 的 setImmediate(processVideoGeneration)。
    """
    from app.core.config import load_config
    from app.core.logger import get_logger
    from app.db.session import SessionLocal, init_engine
    from app.services import videoClient
    from app.services import workerService

    log = get_logger("lmd.videoService")
    if not workerService.begin("video_gen", video_gen_id):
        log.info("Video generation already in progress, skip duplicate", extra={"video_gen_id": video_gen_id})
        return

    if SessionLocal is None:
        init_engine()
    db = SessionLocal()
    try:
        log.info("processVideoGeneration started", extra={"video_gen_id": video_gen_id})
        row = fetch_one(
            db,
            "SELECT * FROM video_generations WHERE id = :id AND deleted_at IS NULL",
            {"id": to_int_id(video_gen_id)},
        )
        if not row:
            log.error("Video generation not found", extra={"id": video_gen_id})
            return

        now = _now()
        execute(
            db,
            "UPDATE video_generations SET status = :s, updated_at = :t WHERE id = :id",
            {"s": "processing", "t": now, "id": video_gen_id},
        )
        db.commit()

        cfg = load_config()
        storage_cfg = cfg.get("storage") or {}
        files_base_url = str(storage_cfg.get("base_url") or "").rstrip("/")
        storage_local_path = resolve_storage_path(cfg)

        config = videoClient.get_default_video_config(db, row.get("model"))
        if not config:
            set_video_gen_failed(db, video_gen_id, "未配置视频模型", now)
            if row.get("task_id"):
                taskService.update_task_error(db, row["task_id"], "未配置视频模型")
            db.commit()
            return

        reference_urls = None
        if row.get("reference_image_urls"):
            try:
                parsed = json.loads(row["reference_image_urls"])
                reference_urls = parsed if isinstance(parsed, list) else None
            except Exception:  # noqa: BLE001
                reference_urls = None

        # 优先用分镜自身的镜头时长
        effective_duration = row.get("duration")
        if row.get("storyboard_id"):
            sb = fetch_one(
                db, "SELECT duration FROM storyboards WHERE id = :id", {"id": row["storyboard_id"]}
            )
            if sb and _to_float(sb.get("duration"), 0) > 0:
                effective_duration = sb["duration"]
                log.info("使用分镜镜头时长", extra={
                    "storyboard_id": row["storyboard_id"], "duration": effective_duration,
                    "video_gen_id": video_gen_id,
                })

        aspect_for_video = row.get("aspect_ratio")
        if aspect_for_video:
            normalized = normalize_aspect_ratio_for_api(aspect_for_video)
            if normalized:
                aspect_for_video = normalized
        if not aspect_for_video and row.get("drama_id"):
            try:
                aspect_for_video = _drama_aspect_ratio(db, row["drama_id"])
            except Exception:  # noqa: BLE001
                aspect_for_video = None
        row_for_aspect = {**row, "aspect_ratio": aspect_for_video or row.get("aspect_ratio")}

        has_omni_refs = bool(reference_urls)
        if row.get("task_id") and has_omni_refs:
            taskService.update_task_status(
                db, row["task_id"], "processing", 5, f"正在上传 {len(reference_urls)} 张参考图到图床…"
            )

        result = videoClient.call_video_api(db, log, {
            "prompt": row.get("prompt"),
            "model": row.get("model"),
            "duration": effective_duration,
            "aspect_ratio": row_for_aspect["aspect_ratio"],
            "resolution": row.get("resolution"),
            "seed": row.get("seed"),
            "camera_fixed": row.get("camera_fixed"),
            "watermark": row.get("watermark"),
            "provider": row.get("provider"),
            "drama_id": row.get("drama_id"),
            "storyboard_id": row.get("storyboard_id"),
            "image_url": None if has_omni_refs else row.get("image_url"),
            "first_frame_url": None if has_omni_refs else row.get("first_frame_url"),
            "last_frame_url": None if has_omni_refs else row.get("last_frame_url"),
            "reference_urls": reference_urls,
            "files_base_url": files_base_url,
            "storage_local_path": storage_local_path,
            "video_gen_id": video_gen_id,
        })

        now2 = _now()
        if result.get("error"):
            set_video_gen_failed(db, video_gen_id, result["error"], now2)
            if row.get("task_id"):
                taskService.update_task_error(db, row["task_id"], result["error"])
            log.error("Video generation failed", extra={"id": video_gen_id, "error": result["error"]})
            db.commit()
            return

        direct = resolve_remote_video_url(result.get("video_url"), result.get("error"))
        if direct["ok"]:
            finalize_successful_video(db, log, video_gen_id, row, row_for_aspect, direct["video_url"])
            db.commit()
            return
        if result.get("video_url"):
            set_video_gen_failed(db, video_gen_id, direct["error"], now2)
            if row.get("task_id"):
                taskService.update_task_error(db, row["task_id"], direct["error"])
            log.error("Video generation failed", extra={"id": video_gen_id, "error": direct["error"]})
            db.commit()
            return
        if result.get("task_id"):
            execute(
                db,
                "UPDATE video_generations SET status = :s, provider_task_id = :p, updated_at = :t WHERE id = :id",
                {"s": "processing", "p": result["task_id"], "t": now2, "id": video_gen_id},
            )
            db.commit()
            poll_provider_task_and_finalize(
                db, log, video_gen_id, row, row_for_aspect, result["task_id"], config
            )
            db.commit()
            return

        set_video_gen_failed(db, video_gen_id, "未返回 task_id 或 video_url", now2)
        if row.get("task_id"):
            taskService.update_task_error(db, row["task_id"], "未返回 task_id 或 video_url")
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.error("Video generation error", extra={"id": video_gen_id, "reason": str(e)})
        try:
            now2 = _now()
            set_video_gen_failed(db, video_gen_id, str(e), now2)
            db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        workerService.end("video_gen", video_gen_id)
        db.close()


def _to_float(v, default: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return n if n == n and n not in (float("inf"), float("-inf")) else default
