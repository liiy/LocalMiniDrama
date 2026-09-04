from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.response import HttpError, bad_request

DEFAULT_MAX_IMAGE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_AUDIO_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_ZIP_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_TEXT_BYTES = 10 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/jpg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/gif": {".gif"},
    "image/webp": {".webp"},
}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}
ALLOWED_ZIP_EXTENSIONS = {".zip"}
ALLOWED_TEXT_EXTENSIONS = {".txt", ".md", ".text"}


def upload_limits(cfg: dict[str, Any] | None) -> dict[str, int]:
    sec = (cfg or {}).get("security") or {}
    upload = sec.get("upload") or {}

    def _int(name: str, env_name: str, default: int) -> int:
        raw = os.environ.get(env_name, upload.get(name, default))
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return default
        return n if n > 0 else default

    return {
        "image": _int("max_image_bytes", "LMD_MAX_IMAGE_BYTES", DEFAULT_MAX_IMAGE_BYTES),
        "audio": _int("max_audio_bytes", "LMD_MAX_AUDIO_BYTES", DEFAULT_MAX_AUDIO_BYTES),
        "zip": _int("max_zip_bytes", "LMD_MAX_ZIP_BYTES", DEFAULT_MAX_ZIP_BYTES),
        "text": _int("max_text_bytes", "LMD_MAX_TEXT_BYTES", DEFAULT_MAX_TEXT_BYTES),
    }


def validate_upload_filename(filename: str | None, allowed_extensions: set[str], label: str) -> str:
    clean = Path(filename or "").name
    if not clean or clean in {".", ".."}:
        raise bad_request(f"Invalid {label} filename")
    if clean != filename or "/" in filename or "\\" in filename:
        raise bad_request(f"Invalid {label} filename")
    ext = Path(clean).suffix.lower()
    if ext not in allowed_extensions:
        raise bad_request(f"Unsupported {label} file type")
    return clean


def validate_image_type(filename: str | None, content_type: str | None) -> str:
    clean = validate_upload_filename(
        filename,
        {ext for exts in ALLOWED_IMAGE_TYPES.values() for ext in exts},
        "image",
    )
    mime = content_type or "application/octet-stream"
    allowed_exts = ALLOWED_IMAGE_TYPES.get(mime)
    if not allowed_exts or Path(clean).suffix.lower() not in allowed_exts:
        raise HttpError(400, "UNSUPPORTED_FILE_TYPE", "Only jpg, png, gif and webp images are supported")
    return clean


def validate_audio_type(filename: str | None) -> str:
    return validate_upload_filename(filename, ALLOWED_AUDIO_EXTENSIONS, "audio")


def validate_zip_type(filename: str | None) -> str:
    return validate_upload_filename(filename, ALLOWED_ZIP_EXTENSIONS, "zip")


def validate_text_type(filename: str | None) -> str:
    return validate_upload_filename(filename, ALLOWED_TEXT_EXTENSIONS, "text")


async def read_upload_limited(file: UploadFile, max_bytes: int, error_message: str, code: str = "FILE_TOO_LARGE") -> bytes:
    buf = bytearray()
    while True:
        chunk = await file.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HttpError(413, code, error_message)
    return bytes(buf)


def verify_image_payload(buf: bytes) -> None:
    if not buf:
        raise bad_request("Empty image file")
    try:
        with Image.open(BytesIO(buf)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HttpError(400, "INVALID_IMAGE", "Invalid or corrupted image file") from exc
