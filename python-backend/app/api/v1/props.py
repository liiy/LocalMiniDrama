"""/api/v1/props — 契约翻译 backend-node/src/routes/prop.js（P2 纯 CRUD）。

- GET    /props/:id            → 400 '无效的ID' | 404 '道具不存在' | { prop }
- POST   /props                → 400 'drama_id 和 name 必填' | 500 '创建失败' | 201 prop
- PUT    /props/:id            → 400 | 404 | prop
- DELETE /props/:id            → 400 | 404 | { message: '删除成功' }
- POST   /props/:id/props 关联在 storyboards 侧（/storyboards/:id/props）
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import bad_request, created, forbidden, internal_error, not_found, success
from app.db.session import get_db
from app.services import propEntityService as svc
from app.services import propImageGenerationService as prop_img_svc
from app.services import propLibraryService as lib_svc

router = APIRouter(tags=["props"])
log = get_logger("lmd.props")

# 内存态配置（等价 Node routes(db, log, cfg) 闭包持有 cfg）
_CFG: dict = {}


def init_config(cfg: dict) -> None:
    global _CFG
    _CFG = cfg or {}


def _get_cfg() -> dict:
    from app.core.config import load_config
    return _CFG if _CFG else load_config()


def parse_int_id(raw: str) -> int | None:
    """等价 JS parseInt(id, 10)；NaN 时返回 None。"""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@router.get("/props/{prop_id}")
def get_prop_by_id(prop_id: str, db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    prop = svc.get_by_id(db, pid)
    if not prop:
        raise not_found("道具不存在")
    return success({"prop": prop})


@router.post("/props", status_code=201)
def create_prop(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    if not body.get("drama_id") or not body.get("name"):
        raise bad_request("drama_id 和 name 必填")
    return created(svc.create(db, body))


@router.put("/props/{prop_id}")
def update_prop(prop_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    prop = svc.update(db, pid, payload or {})
    if not prop:
        raise not_found("道具不存在")
    return success(prop)


@router.delete("/props/{prop_id}")
def delete_prop(prop_id: str, db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    if not svc.delete_by_id(db, pid):
        raise not_found("道具不存在")
    return success({"message": "删除成功"})


@router.post("/props/{prop_id}/add-to-library")
def add_prop_to_library(prop_id: str, db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    out = lib_svc.add_prop_to_library(db, log, pid)
    if not out.get("ok"):
        err = out.get("error")
        if err == "prop not found":
            raise not_found("道具不存在")
        if err == "unauthorized":
            raise forbidden("无权限")
        raise bad_request(err or "加入库失败")
    return success({"message": "已加入本剧道具库", "item": out["item"]})


@router.post("/props/{prop_id}/add-to-material-library")
def add_prop_to_material_library(prop_id: str, db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    out = lib_svc.add_prop_to_material_library(db, log, pid)
    if not out.get("ok"):
        err = out.get("error")
        if err == "prop not found":
            raise not_found("道具不存在")
        raise bad_request(err or "加入素材库失败")
    return success({"message": "已加入全局素材库", "item": out["item"]})


@router.post("/props/{prop_id}/generate")
def generate_image(prop_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    body = payload or {}
    model = str(body.get("model") or "").strip() or None
    style = str(body.get("style") or "").strip() or None
    try:
        task_id = prop_img_svc.generate_prop_image(db, log, pid, {"model": model, "style": style})
        return success({"task_id": task_id})
    except ValueError as err:
        err_msg = str(err)
        if err_msg == "道具不存在":
            raise not_found(err_msg)
        if err_msg == "道具没有图片提示词":
            raise bad_request(err_msg)
        log.error("generatePropImage failed", extra={"error": err_msg})
        raise internal_error(err_msg or "生成失败")
    except Exception as err:
        log.error("generatePropImage failed", extra={"error": str(err)})
        raise internal_error(str(err) or "生成失败")


@router.post("/props/{prop_id}/generate-prompt")
def generate_prop_prompt(prop_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    body = payload or {}
    model = body.get("model") or None
    style = body.get("style") or None
    out = svc.generate_prop_prompt_only(db, log, _get_cfg(), pid, model, style)
    if not out.get("ok"):
        err = out.get("error")
        if err == "prop not found":
            raise not_found("道具不存在")
        raise bad_request(err or "生成提示词失败")
    return success({"message": "提示词已生成", "prompt": out.get("prompt")})


@router.post("/props/{prop_id}/extract-from-image")
def extract_prop_from_image(prop_id: str, db: Session = Depends(get_db)) -> dict:
    pid = parse_int_id(prop_id)
    if pid is None:
        raise bad_request("无效的ID")
    out = svc.extract_prop_from_image(db, log, _get_cfg(), pid)
    if not out.get("ok"):
        err = out.get("error")
        if err == "prop not found":
            raise not_found("道具不存在")
        raise bad_request(err or "提取道具描述失败")
    return success({"message": "道具描述已提取", "description": out.get("description")})

