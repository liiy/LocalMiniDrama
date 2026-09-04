"""/api/v1/upload/* 鈥?濂戠害绮剧‘缈昏瘧 backend-node/src/routes/upload.js銆?
绔偣锛?- POST /upload/image   multipart/form-data锛屽瓧娈靛悕 file锛涘彲閫夎〃鍗曞瓧娈?drama_id

Node 渚х殑閿欒璇箟锛堢敱 multer + Express 鍏ㄥ眬閿欒澶勭悊鍏卞悓鍐冲畾锛屾澶勯€愭潯澶嶅埢锛夛細
- 鏈彁渚涙枃浠?             鈫?400 BAD_REQUEST '璇烽€夋嫨鏂囦欢'
- mimetype 涓嶅湪鐧藉悕鍗?    鈫?500 INTERNAL_ERROR '鍙敮鎸佸浘鐗囨牸寮?(jpg, png, gif, webp)'
                            锛坢ulter fileFilter 鎶涢敊钀藉埌閫氱敤閿欒澶勭悊锛屾晠鏄?500 鑰岄潪 400锛?- 瓒呰繃 16MB              鈫?413 FILE_TOO_LARGE '鍥剧墖澶у皬涓嶈兘瓒呰繃 16MB锛岃鍘嬬缉鍚庨噸璇?

鏍￠獙椤哄簭涓?Node 涓€鑷达細mimetype 鍏堜簬浣撶Н锛坢ulter 鍦ㄨВ鏋愬埌鏂囦欢澶存椂鍗宠皟鐢?fileFilter锛夈€?"""
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
MAX_IMAGE_SIZE = 16 * 1024 * 1024  # 16MB锛屽崟寮犲浘鐗囦笂闄?_CHUNK = 1024 * 1024

# 鍐呭瓨鎬侀厤缃紙绛変环 Node app.js 鍚姩鏃?loadConfig 涓€娆″苟闂寘浼犻€掞級
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
    if did != did or did <= 0:  # NaN 鎴?<= 0
        return None
    return storageLayout.get_project_storage_subdir(db, did)


@router.post("/upload/image")
async def upload_image(
    file: UploadFile | None = File(default=None),
    drama_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if file is None:
        raise bad_request("璇烽€夋嫨鏂囦欢")

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
        raise HttpError(500, "INTERNAL_ERROR", str(e) or "涓婁紶澶辫触") from e

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
        raise bad_request("缂哄皯 image_url")
    if entity_type not in ("character", "scene", "prop"):
        raise bad_request("entity_type 闇€涓?character/scene/prop")

    try:
        out = aiClient.extract_description_from_image(
            db, log, entity_type, image_url, entity_name
        )
        if not out or not out.get("ok"):
            err_msg = (out.get("error") if isinstance(out, dict) else None) or "鎻愬彇鎻忚堪澶辫触"
            raise bad_request(err_msg)
        return success({"description": out.get("description")})
    except HttpError:
        raise
    except Exception as err:
        log.error("extract-description-from-image: %s", err)
        raise internal_error(str(err))
