"""/api/v1/upload/* — 契约精确翻译 backend-node/src/routes/upload.js。

端点：
- POST /upload/image   multipart/form-data，字段名 file；可选表单字段 drama_id

Node 侧的错误语义（由 multer + Express 全局错误处理共同决定，此处逐条复刻）：
- 未提供文件             -> 400 BAD_REQUEST '请选择文件'
- mimetype 不在白名单    -> 500 INTERNAL_ERROR '只支持图片格式 (jpg, png, gif, webp)'
                            （multer fileFilter 抛错落到通用错误处理，故是 500 而非 400）
- 超过 16MB              -> 413 FILE_TOO_LARGE '图片大小不能超过 16MB，请压缩后重试'

校验顺序与 Node 一致：mimetype 先于体积（multer 在解析到文件头时即调用 fileFilter）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core import config as cfgmod
from app.core.logger import get_logger
from app.core.response import HttpError, bad_request, internal_error, success
from app.core.upload_validation import read_upload_limited, validate_image_type, verify_image_payload
from app.db.session import get_db
from app.services import aiClient, storageLayout
from app.services.uploadService import upload_file

router = APIRouter(tags=["upload"])
log = get_logger("lmd.upload")

ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp")
MAX_IMAGE_SIZE = 16 * 1024 * 1024  # 16MB，单张图片上限
_CHUNK = 1024 * 1024

# 内存态配置（等价 Node app.js 启动时 loadConfig 一次并闭包传递）
_CFG: dict[str, Any] = {}


def init_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = cfg


def _resolve_project_subdir(db: Session, raw_drama_id: Any) -> str | None:
    """Resolve drama_id to a project storage subdirectory when it is a positive number."""
    if raw_drama_id is None:
        return None
    s = str(raw_drama_id).strip()
    if s == "":
        return None
    try:
        did = float(s)
    except (TypeError, ValueError):
        return None
    if did != did or did <= 0:  # NaN 或 <= 0
        return None
    return storageLayout.get_project_storage_subdir(db, did)


@router.post("/upload/image")
async def upload_image(
    file: UploadFile | None = File(default=None),
    drama_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if file is None:
        raise bad_request("请选择文件")

    clean_filename = validate_image_type(file.filename or "image.png", file.content_type)
    buf = await read_upload_limited(
        file,
        MAX_IMAGE_SIZE,
        "Image size cannot exceed 16MB. Please compress and retry.",
    )
    verify_image_payload(buf)

    try:
        project_subdir = _resolve_project_subdir(db, drama_id)
        result = upload_file(
            cfgmod.storage_local_path(_CFG),
            cfgmod.storage_base_url(_CFG),
            log,
            buf,
            clean_filename,
            file.content_type,
            "uploads",
            project_subdir,
        )
    except HttpError:
        raise
    except Exception as e:
        log.error("upload image", extra={"error": str(e)})
        raise HttpError(500, "INTERNAL_ERROR", str(e) or "上传失败") from e

    return success(
        {
            "url": result["url"],
            "path": result["local_path"],
            "local_path": result["local_path"],
            "filename": clean_filename,
            "size": len(buf),
        }
    )

@router.post("/extract-description-from-image")
def extract_description_from_image_endpoint(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload or {}
    image_url = body.get("image_url") or body.get("imageUrl")
    entity_type = body.get("entity_type") or body.get("entityType")
    entity_name = body.get("entity_name") or body.get("entityName")

    if not image_url:
        raise bad_request("缺少 image_url")
    if entity_type not in ("character", "scene", "prop"):
        raise bad_request("entity_type 需为 character/scene/prop")

    try:
        out = aiClient.extract_description_from_image(
            db, log, entity_type, image_url, entity_name
        )
        if not out or not out.get("ok"):
            err_msg = (out.get("error") if isinstance(out, dict) else None) or "提取描述失败"
            raise bad_request(err_msg)
        return success({"description": out.get("description")})
    except HttpError:
        raise
    except Exception as err:
        log.error("extract-description-from-image: %s", err)
        raise internal_error(str(err))
