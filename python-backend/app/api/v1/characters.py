"""/api/v1/characters — 契约翻译 backend-node/src/routes/characters.js（P2 纯 CRUD）。

- GET    /characters/:id  → 404 '角色不存在' | { character: {...固定字段集...} }
- PUT    /characters/:id  → 404 | 400 (unauthorized 等) | { message: '保存成功' }
- DELETE /characters/:id  → 404 | 400 | { message: '删除成功' }

GET 的字段集是 Node 里硬编码的 SELECT 列，与 dramaService.rowToCharacter 不同。
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Body, Depends, File, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import bad_request, not_found, success, timestamp
from app.core.upload_validation import (
    DEFAULT_MAX_AUDIO_BYTES,
    DEFAULT_MAX_IMAGE_BYTES,
    read_upload_limited,
    validate_audio_type,
    validate_image_type,
    verify_image_payload,
)
from app.db.session import get_db, session_scope
from app.services import characterEntityService as svc
from app.services import characterGenerationService as char_gen_svc
from app.services import characterLibraryService as lib_svc
from app.services import storageLayout
from app.services import uploadService
from app.services import workerService
from app.utils import seedance2AssetGuards as sd2

router = APIRouter(tags=["characters"])
log = get_logger("lmd.characters")

# 内存态配置（等价 Node routes(db, cfg, log, uploadService) 闭包持有 cfg）
_CFG: dict = {}


def init_config(cfg: dict) -> None:
    global _CFG
    _CFG = cfg or {}


def _get_cfg() -> dict:
    from app.core.config import load_config
    return _CFG if _CFG else load_config()


def _storage_root() -> str:
    raw = (_get_cfg().get("storage") or {}).get("local_path") or "./data/storage"
    return raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)


def _storage_base_url() -> str:
    return (_get_cfg().get("storage") or {}).get("base_url") or ""

# Node routes/characters.js getOne 中硬编码的 SELECT 列
_SELECT_COLS = (
    "id, drama_id, name, role, appearance, description, personality, voice_style, image_url, local_path, "
    "polished_prompt, four_view_image_url, identity_anchors, seedance2_asset, seedance2_voice_asset, "
    "negative_prompt, updated_at"
)


def to_int_id(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


@router.get("/characters/{character_id}")
def get_one(character_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.execute(
        text(f"SELECT {_SELECT_COLS} FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(character_id)},
    ).mappings().first()
    if not row:
        raise not_found("角色不存在")
    character = dict(row)
    for key in ("seedance2_asset", "seedance2_voice_asset"):
        raw = character.get(key)
        if raw:
            try:
                character[key] = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                character[key] = None
        else:
            character[key] = None
    return success({"character": character})


@router.put("/characters/{character_id}")
def update(character_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    ok, err = svc.update_character(db, character_id, payload or {})
    if not ok:
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "保存失败")
    return success({"message": "保存成功"})


@router.delete("/characters/{character_id}")
def delete(character_id: str, db: Session = Depends(get_db)) -> dict:
    ok, err = svc.delete_character(db, character_id)
    if not ok:
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "删除失败")
    return success({"message": "删除成功"})


@router.post("/characters/batch-generate-images")
def batch_generate_images(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    character_ids = body.get("character_ids")
    log.info("batch-generate-images request", extra={"character_ids": character_ids, "model": body.get("model"), "style": body.get("style")})
    if not isinstance(character_ids, list) or len(character_ids) == 0:
        raise bad_request("character_ids 不能为空")
    if len(character_ids) > 10:
        raise bad_request("单次最多生成10个角色")
    out = lib_svc.batch_generate_character_images(
        db, log, _get_cfg(), character_ids, body.get("model"), body.get("style")
    )
    if not out.get("ok"):
        raise bad_request(out.get("error") or "批量生成失败")
    return success({
        "message": "批量生成任务已提交",
        "count": out.get("count"),
    })


@router.post("/characters/{character_id}/generate-image")
def generate_image(character_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    out = lib_svc.generate_character_four_view_image(
        db, log, _get_cfg(), character_id, body.get("model"), body.get("style")
    )
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        if err == "unauthorized":
            raise not_found("剧集不存在或无权限")
        raise bad_request(err or "角色四视图生成失败")
    return success({
        "message": "角色四视图生成任务已提交",
        "image_generation": out.get("image_generation"),
    })


@router.post("/characters/{character_id}/generate-four-view-image")
def generate_four_view_image(character_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    model_name = body.get("model_name") or body.get("model") or None
    style = body.get("style") or None
    out = lib_svc.generate_character_four_view_image(
        db, log, _get_cfg(), character_id, model_name, style
    )
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        if err == "unauthorized":
            raise not_found("剧集不存在或无权限")
        raise bad_request(err or "四视图生成失败")
    return success({
        "message": "四视图生成任务已提交",
        "image_generation": out.get("image_generation"),
    })


@router.post("/characters/{character_id}/generate-prompt")
def generate_prompt(character_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    model_name = body.get("model_name") or body.get("model") or None
    style = body.get("style") or None
    out = lib_svc.generate_character_prompt_only(
        db, log, _get_cfg(), character_id, model_name, style
    )
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "提示词生成失败")
    return success({
        "message": "提示词已生成",
        "polished_prompt": out.get("polished_prompt"),
    })


@router.post("/characters/{character_id}/extract-from-image")
def extract_from_image(character_id: str, db: Session = Depends(get_db)) -> dict:
    out = lib_svc.extract_appearance_from_image(db, log, _get_cfg(), character_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "外貌提取失败")
    return success({
        "message": "外貌描述已提取",
        "appearance": out.get("appearance"),
    })


@router.post("/characters/{character_id}/sd2-certify")
def sd2_certify(character_id: str, db: Session = Depends(get_db)) -> dict:
    out = lib_svc.register_character_jimeng_material_asset(db, log, _get_cfg(), character_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "SD2 素材认证失败")
    return success({
        "message": "SD2 素材认证已更新",
        "seedance2_asset": out.get("seedance2_asset"),
    })


@router.post("/characters/{character_id}/sd2-certify/refresh")
def sd2_certify_refresh(character_id: str, db: Session = Depends(get_db)) -> dict:
    out = lib_svc.refresh_character_jimeng_material_asset(db, log, _get_cfg(), character_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "认证状态刷新失败")
    return success({
        "message": "认证状态已刷新",
        "seedance2_asset": out.get("seedance2_asset"),
    })


@router.put("/characters/{character_id}/image-from-library")
def image_from_library(character_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    library_id = (payload or {}).get("library_id")
    if library_id is None:
        raise bad_request("缺少 library_id")
    out = lib_svc.apply_library_item_to_character(db, log, character_id, library_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "library item not found":
            raise not_found("角色库项不存在")
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "应用失败")
    return success({"message": "应用成功"})


@router.post("/characters/{character_id}/add-to-library")
def add_to_library(character_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    category = (payload or {}).get("category")
    out = lib_svc.add_character_to_library(db, log, character_id, category)
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "加入库失败")
    return success({"message": "已加入本剧角色库", "item": out["item"]})


@router.post("/characters/{character_id}/add-to-material-library")
def add_to_material_library(character_id: str, db: Session = Depends(get_db)) -> dict:
    out = lib_svc.add_character_to_material_library(db, log, character_id)
    if not out.get("ok"):
        err = out.get("error")
        if err == "character not found":
            raise not_found("角色不存在")
        raise bad_request(err or "加入素材库失败")
    return success({"message": "已加入全局素材库", "item": out["item"]})


@router.put("/characters/{character_id}/image")
def put_image(character_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    char_id = to_int_id(character_id)
    prev = db.execute(
        text("SELECT id, local_path, image_url, seedance2_asset FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": char_id},
    ).mappings().first()
    if not prev:
        raise not_found("角色不存在")
    next_img = body["image_url"] if body.get("image_url") is not None else prev["image_url"]
    next_lp = body["local_path"] if body.get("local_path") is not None else prev["local_path"]
    sd2.mark_stale_on_character_main_image_drift(db, log, dict(prev), {"image_url": next_img, "local_path": next_lp})
    if body.get("image_url") is not None:
        out = lib_svc.upload_character_image(db, log, character_id, body["image_url"], {"skipStaleMark": True})
        if not out.get("ok"):
            if out.get("error") == "character not found":
                raise not_found("角色不存在")
            raise bad_request(out.get("error") or "保存失败")
    extra_fields = []
    extra_params: dict = {}
    if body.get("local_path") is not None:
        extra_fields.append("local_path = :local_path")
        extra_params["local_path"] = body["local_path"]
    if body.get("extra_images") is not None:
        extra_fields.append("extra_images = :extra_images")
        extra_params["extra_images"] = body["extra_images"]
    if body.get("ref_image") is not None:
        extra_fields.append("ref_image = :ref_image")
        extra_params["ref_image"] = body["ref_image"]
    if extra_fields:
        extra_params["updated_at"] = timestamp()
        extra_params["cid"] = char_id
        db.execute(
            text(f"UPDATE characters SET {', '.join(extra_fields)}, updated_at = :updated_at WHERE id = :cid"),
            extra_params,
        )
    return success({"message": "保存成功"})


def _run_enrich_anchors(char_id: int, appearance: str) -> None:
    try:
        with session_scope() as db_worker:
            char_gen_svc.enrich_identity_anchors(db_worker, log, char_id, appearance)
    except Exception as err:
        log.warning("[锚点] 后台提炼异常", extra={"character_id": char_id, "error": str(err)})


@router.post("/characters/{character_id}/extract-anchors")
def extract_anchors(character_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 Node extractAnchors：校验外貌是否存在，存在则后台异步提炼锚点并返回已启动。"""
    row = db.execute(
        text("SELECT id, appearance, identity_anchors FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(character_id)},
    ).mappings().first()
    if not row:
        raise not_found("角色不存在")
    if not row.get("appearance"):
        raise bad_request("角色缺少外貌描述，无法提炼锚点")
    workerService.submit(_run_enrich_anchors, int(row["id"]), str(row["appearance"]))
    return success({"message": "锚点提炼已启动，请稍后刷新查看"})


@router.post("/characters/{character_id}/upload-image")
async def upload_image(character_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    if not file or not file.file:
        raise bad_request("请选择文件")
    clean_filename = validate_image_type(file.filename or "image.png", file.content_type)
    char_id = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, drama_id FROM characters WHERE id = :id AND deleted_at IS NULL"), {"id": char_id}
    ).mappings().first()
    if not char_row:
        raise not_found("角色不存在")
    project_subdir = storageLayout.get_project_storage_subdir(db, char_row["drama_id"])
    buffer = await read_upload_limited(
        file,
        DEFAULT_MAX_IMAGE_BYTES,
        "图片大小不能超过 16MB，请压缩后重试",
    )
    verify_image_payload(buffer)
    result = uploadService.upload_file(
        _storage_root(), _storage_base_url(), log, buffer, clean_filename,
        file.content_type, "characters", project_subdir,
    )
    out = lib_svc.upload_character_image(db, log, character_id, result["url"])
    if not out.get("ok"):
        if out.get("error") == "character not found":
            raise not_found("角色不存在")
        raise bad_request(out.get("error") or "上传失败")
    return success({
        "message": "上传成功", "url": result["url"], "local_path": result["local_path"],
        "filename": clean_filename, "size": len(buffer),
    })


@router.post("/characters/{character_id}/sd2-voice-upload")
async def sd2_voice_upload(character_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    if not file or not file.file:
        raise bad_request("请上传音频文件")
    clean_filename = validate_audio_type(file.filename or "voice.mp3")
    ext = os.path.splitext(clean_filename)[1].lower()
    char_id = to_int_id(character_id)
    char_row = db.execute(
        text("SELECT id, drama_id FROM characters WHERE id = :id AND deleted_at IS NULL"), {"id": char_id}
    ).mappings().first()
    if not char_row:
        raise not_found("角色不存在")
    storage_root = _storage_root()
    rel_dir = f"drama_{char_row['drama_id']}/characters/voice"
    abs_dir = os.path.join(storage_root, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    safe_name = f"char_{char_id}_voice_{int(__import__('time').time() * 1000)}{ext}"
    abs_path = os.path.join(abs_dir, safe_name)
    buffer = await read_upload_limited(
        file,
        DEFAULT_MAX_AUDIO_BYTES,
        "音频大小不能超过 32MB，请压缩后重试",
    )
    with open(abs_path, "wb") as f:
        f.write(buffer)
    public_url = f"/static/{rel_dir}/{safe_name}"
    now = timestamp()
    payload = {
        "status": "active",
        "url": public_url,
        "local_path": f"{rel_dir}/{safe_name}",
        "certified_at": now,
        "duration": None,
        "format": ext.lstrip("."),
    }
    db.execute(
        text("UPDATE characters SET seedance2_voice_asset = :a, updated_at = :now WHERE id = :id"),
        {"a": json.dumps(payload), "now": now, "id": char_id},
    )
    return success({"message": "Seedance 2.0 音色参考已保存", "seedance2_voice_asset": payload})


@router.post("/characters/{character_id}/sd2-voice-refresh")
def sd2_voice_refresh(character_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.execute(
        text("SELECT seedance2_voice_asset FROM characters WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(character_id)},
    ).mappings().first()
    if not row:
        raise not_found("角色不存在")
    raw = row.get("seedance2_voice_asset")
    asset = None
    if raw:
        try:
            asset = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            asset = None
    return success({"message": "状态已刷新", "seedance2_voice_asset": asset})
