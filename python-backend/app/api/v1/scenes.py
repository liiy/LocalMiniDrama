"""/api/v1/scenes — 契约翻译 backend-node/src/routes/scenes.js（P2 纯 CRUD）。

- GET    /scenes/:id           → 404 '场景不存在' | { scene }
- POST   /scenes               → 400 '缺少 drama_id' | 201 scene
- PUT    /scenes/:id           → 404 | { message: '保存成功' }
- PUT    /scenes/:id/prompt    → 404 | { message: '场景提示词已更新' }
- DELETE /scenes/:id           → 404 | { message: '场景已删除' }
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import bad_request, created, forbidden, not_found, success
from app.db.session import get_db
from app.services import sceneEntityService as svc
from app.services import sceneLibraryService as lib_svc

router = APIRouter(tags=["scenes"])
log = get_logger("lmd.scenes")

# 内存态配置（等价 Node routes(db, cfg, log) 闭包持有 cfg）
_CFG: dict = {}


def init_config(cfg: dict) -> None:
    global _CFG
    _CFG = cfg or {}


def _get_cfg() -> dict:
    from app.core.config import load_config
    return _CFG if _CFG else load_config()


@router.post("/scenes/generate-image")
def generate_image(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    scene_id = body.get("scene_id")
    if scene_id is None:
        raise bad_request("缺少 scene_id")
    model = body.get("model")
    style = body.get("style")
    use_quad_grid = bool(body.get("use_quad_grid"))
    if use_quad_grid:
        out = svc.generate_scene_four_view_image(db, log, _get_cfg(), scene_id, model, style)
    else:
        out = svc.generate_scene_single_image(db, log, _get_cfg(), scene_id, model, style)

    if not out.get("ok"):
        err = out.get("error")
        if err == "scene not found":
            raise not_found("场景不存在")
        if err == "unauthorized":
            raise not_found("剧集不存在或无权限")
        raise bad_request(err or "生成场景图片失败")
    return success({"message": "场景视图生成任务已提交", "image_generation": out.get("image_generation")})


@router.get("/scenes/{scene_id}")
def get_one(scene_id: str, db: Session = Depends(get_db)) -> dict:
    scene = svc.get_scene_by_id(db, scene_id)
    if not scene:
        raise not_found("场景不存在")
    return success({"scene": scene})


@router.post("/scenes", status_code=201)
def create(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    if body.get("drama_id") is None:
        raise bad_request("缺少 drama_id")
    return created(svc.create_scene(db, body["drama_id"], body))


@router.put("/scenes/{scene_id}")
def update(scene_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    if not svc.update_scene(db, scene_id, payload or {}):
        raise not_found("场景不存在")
    return success({"message": "保存成功"})


@router.put("/scenes/{scene_id}/prompt")
def update_prompt(scene_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    if not svc.update_scene_prompt(db, scene_id, payload or {}):
        raise not_found("场景不存在")
    return success({"message": "场景提示词已更新"})


@router.delete("/scenes/{scene_id}")
def delete(scene_id: str, db: Session = Depends(get_db)) -> dict:
    if not svc.delete_scene(db, scene_id):
        raise not_found("场景不存在")
    return success({"message": "场景已删除"})


@router.post("/scenes/{scene_id}/add-to-library")
def add_to_library(scene_id: str, db: Session = Depends(get_db)) -> dict:
    out = lib_svc.add_scene_to_library(db, log, scene_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "scene not found":
            raise not_found("场景不存在")
        if err == "unauthorized":
            raise forbidden("无权限")
        raise bad_request(err or "加入库失败")
    return success({"message": "已加入本剧场景库", "item": out["item"]})


@router.post("/scenes/{scene_id}/add-to-material-library")
def add_to_material_library(scene_id: str, db: Session = Depends(get_db)) -> dict:
    out = lib_svc.add_scene_to_material_library(db, log, scene_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "scene not found":
            raise not_found("场景不存在")
        raise bad_request(err or "加入素材库失败")
    return success({"message": "已加入全局素材库", "item": out["item"]})


@router.post("/scenes/{scene_id}/generate-prompt")
def generate_prompt(scene_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    mode = body.get("mode")
    model = body.get("model")
    style = body.get("style")
    if mode == "single":
        log.info("Generating single scene prompt", extra={"scene_id": scene_id})
        out = svc.generate_scene_single_prompt_only(db, log, _get_cfg(), scene_id, model, style)
    else:
        log.info("Generating scene prompt", extra={"scene_id": scene_id})
        out = svc.generate_scene_prompt_only(db, log, _get_cfg(), scene_id, model, style)

    if not out.get("ok"):
        err = out.get("error")
        if err == "scene not found":
            raise not_found("场景不存在")
        raise bad_request(err or "生成提示词失败")
    prompt_key = "polished_prompt_single" if mode == "single" else "polished_prompt"
    return success({"message": "提示词已生成", prompt_key: out.get(prompt_key)})


@router.post("/scenes/{scene_id}/extract-from-image")
def extract_from_image(scene_id: str, db: Session = Depends(get_db)) -> dict:
    out = svc.extract_scene_from_image(db, log, _get_cfg(), scene_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "scene not found":
            raise not_found("场景不存在")
        raise bad_request(err or "提取场景失败")
    return success({"message": "场景描述已提取", "prompt": out.get("prompt")})


@router.post("/scenes/{scene_id}/generate-four-view-image")
def generate_four_view_image(scene_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    model_name = body.get("model_name") or body.get("model")
    style = body.get("style")
    out = svc.generate_scene_four_view_image(db, log, _get_cfg(), scene_id, model_name, style)
    if not out.get("ok"):
        err = out.get("error")
        if err == "scene not found":
            raise not_found("场景不存在")
        if err == "unauthorized":
            raise not_found("剧集不存在或无权限")
        raise bad_request(err or "生成场景四视图失败")
    return success({"message": "场景四视图生成任务已提交", "image_generation": out.get("image_generation")})

