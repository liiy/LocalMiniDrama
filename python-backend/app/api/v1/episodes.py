"""/api/v1/episodes — 契约翻译 backend-node/src/routes/index.js 的 episodes 路由组。

Node 中本组路由均为**别名**，指向 drama / storyboards / prop / stub 的 handler：

- GET    /episodes/:episode_id/storyboards       → storyboards.episodeStoryboardsGet（纯 DB）
- POST   /episodes/:episode_id/storyboards       → drama.generateStoryboard（纯 AI → 500）
- POST   /episodes/:episode_id/props/extract     → prop.extractProps（纯 AI → 500）
- POST   /episodes/:episode_id/characters/extract→ stub.episodeCharactersExtract（建任务，纯 DB）
- POST   /episodes/:episode_id/finalize          → drama.finalizeEpisode（纯 DB）
- GET    /episodes/:episode_id/download          → drama.downloadEpisodeVideo（纯 DB）
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.v1.drama import svc as drama_svc
from app.api.v1.storyboards import to_int_id
from app.core.logger import get_logger
from app.core.response import bad_request, internal_error, not_found, success
from app.db.session import get_db
from app.services import storyboardEntityService as sb_svc
from app.services import taskService as task_svc

router = APIRouter(tags=["episodes"])
log = get_logger("lmd.episodes")


@router.get("/episodes/{episode_id}/storyboards")
def episode_storyboards_get(episode_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 storyboards.js episodeStoryboardsGet：返回 { storyboards, total }。

    Node 在 try/catch 中，异常 → 500；正常 → success({ storyboards: list, total: len })。
    """
    try:
        lst = sb_svc.get_storyboards_for_episode(db, episode_id)
        return success({"storyboards": lst, "total": len(lst)})
    except Exception as e:  # noqa: BLE001
        log.error("episodes storyboards get", {"error": str(e), "episode_id": episode_id})
        return internal_error_response(str(e))


@router.post("/episodes/{episode_id}/storyboards")
def episode_storyboards_generate(
    episode_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)
) -> dict:
    """等价 drama.generateStoryboard。"""
    if not episode_id:
        raise bad_request("缺少 episode_id")
    body = payload or {}
    model = str(body["model"]).strip() if body.get("model") and str(body["model"]).strip() else None
    try:
        res_data = drama_svc.generate_storyboard(
            db,
            log,
            episode_id,
            {
                "model": model,
                "style": body.get("style"),
                "storyboard_count": body.get("storyboard_count"),
                "video_duration": body.get("video_duration"),
                "aspect_ratio": body.get("aspect_ratio"),
                "include_narration": body.get("include_narration"),
                "universal_omni_storyboard": body.get("universal_omni_storyboard"),
            },
        )
        return success(res_data)
    except NotImplementedError as e:
        return internal_error_response(str(e) or "分镜头生成尚未接入")
    except Exception as e:  # noqa: BLE001
        log.error("episodes storyboards generate", {"error": str(e), "episode_id": episode_id})
        return internal_error_response(str(e) or "生成分镜失败")


@router.post("/episodes/{episode_id}/props/extract")
def episode_props_extract(
    episode_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)
) -> dict:
    if not episode_id:
        raise bad_request("缺少 episode_id")
    try:
        from app.core.config import load_config
        from app.services import propExtractionService as prop_extract_svc

        task_id = prop_extract_svc.extract_props_for_episode(db, log, episode_id, load_config())
        return success({"task_id": task_id})
    except ValueError as err:
        err_msg = str(err)
        if err_msg == "episode not found" or "剧本内容为空" in err_msg:
            raise bad_request(err_msg)
        log.error("episodes props extract failed", extra={"error": err_msg, "episode_id": episode_id})
        raise internal_error(err_msg or "提取失败")
    except Exception as err:
        log.error("episodes props extract failed", extra={"error": str(err), "episode_id": episode_id})
        raise internal_error(str(err) or "提取失败")


@router.post("/episodes/{episode_id}/characters/extract")
def episode_characters_extract(episode_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 stub.js episodeCharactersExtract：建任务 → 后台置空结果 → 返回 { task_id }。

    Node 用 setTimeout(100ms) 写入结果；此处等价用 daemon 线程延迟 0.1s 写入。
    """
    task = task_svc.create_task(db, log, "character_extraction", episode_id)
    task_id = task["id"] if isinstance(task, dict) else task

    def _finish() -> None:
        try:
            task_svc.update_task_result(db, task_id, {"characters": [], "count": 0})
        except Exception as e:  # noqa: BLE001
            log.error("episodes characters extract finish", {"error": str(e), "task_id": task_id})

    threading.Timer(0.1, _finish).start()
    return success({"task_id": task_id})


@router.post("/episodes/{episode_id}/finalize")
def episode_finalize(
    episode_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)
) -> dict:
    """等价 drama.finalizeEpisode（纯 DB）：剧集不存在 → 404。"""
    if not episode_id:
        raise bad_request("episode_id不能为空")
    base_url = _storage_base_url()
    result = drama_svc.finalize_episode(db, log, episode_id, base_url, payload or {}, _storage_root())
    if not result:
        raise not_found("剧集不存在")
    return success(result)


@router.get("/episodes/{episode_id}/download")
def episode_download(episode_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 drama.downloadEpisodeVideo（纯 DB）：不存在 → 404；无视频 → 400。"""
    result = drama_svc.download_episode_video(db, episode_id)
    if result is None:
        raise not_found("剧集不存在")
    if result.get("error"):
        raise bad_request(result["error"])
    return success(result)


# ---------------- 内部工具 ----------------

_CFG: dict = {}


def init_config(cfg: dict) -> None:
    global _CFG
    _CFG = cfg or {}


def _storage_base_url() -> str:
    return (_CFG.get("storage") or {}).get("base_url") or ""


def _storage_root() -> str:
    return (_CFG.get("storage") or {}).get("local_path") or ""


def internal_error_response(message: str):
    """构造与 Node response.internalError 一致的 500 响应。"""
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=500,
        content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": message}},
    )
