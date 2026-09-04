"""/api/v1/generation — 契约翻译 backend-node/src/routes/index.js 的 generation 路由组。

- POST /generation/characters  → 400 'drama_id 必填' | { task_id, status: 'pending' } | 500
- POST /generation/story       → 有 drama_id：走 startStoryGeneration（纯 DB）
                                 无 drama_id：走 generateStory（纯 AI → 500）

两条路由的 catch 均按 Node 规则分流：错误信息含 未配置/必填/不存在 → 400，其余 → 500。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import bad_request, success
from app.db.session import get_db
from app.services import generationService as gen_svc

router = APIRouter(tags=["generation"])
log = get_logger("lmd.generation")


def _is_bad_request(msg: str) -> bool:
    """等价 Node：命中 未配置 / 必填 / 不存在 时返回 400。"""
    return any(k in (msg or "") for k in gen_svc.BAD_REQUEST_KEYWORDS)


def _error_response(status: int, msg: str) -> JSONResponse:
    code = "BAD_REQUEST" if status == 400 else "INTERNAL_ERROR"
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": {"code": code, "message": msg}},
    )


@router.post("/generation/characters")
def generation_characters(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    if not body.get("drama_id"):
        raise bad_request("drama_id 必填")
    try:
        task_id = gen_svc.generate_characters(db, log, body)
        return success({"task_id": task_id, "status": "pending"})
    except Exception as e:  # noqa: BLE001
        log.error("generation/characters", extra={"error": str(e)})
        return _error_response(500, str(e) or "创建任务失败")


@router.post("/generation/story")
def generation_story(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    try:
        if body.get("drama_id"):
            task_id = gen_svc.start_story_generation(db, log, body)
            return success({"task_id": task_id, "status": "pending"})
        result = gen_svc.generate_story(db, log, body)
        return success(result)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        log.error("generation/story", extra={"error": msg})
        return _error_response(400 if _is_bad_request(msg) else 500, msg or "故事生成失败")
