"""本地存储写入 + 中转图床 — 契约翻译 backend-node/src/services/uploadService.js。

- upload_file / resolve_category_paths：/upload/image 落盘
- download_image_to_local：AI 生成结果落盘
- upload_to_image_proxy / upload_local_image_to_proxy：中转图床（供 videoClient、
  imageClient 的 Gemini/即梦、characterLibrary 的即梦素材库等多处复用）
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _safe_storage_path(storage_path, *parts: str) -> Path:
    root = Path(storage_path).resolve()
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Invalid storage path")
    return target


def _safe_extension(original_name: str | None, default: str = ".png") -> str:
    ext = os.path.splitext(Path(original_name or "").name)[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext or ""):
        return default
    return ext


def resolve_category_paths(storage_path, category: str, project_subdir: str | None) -> tuple[Path, str]:
    """@returns (dir, relPrefix)"""
    safe_category = Path(str(category or "")).name
    if not safe_category:
        raise ValueError("Invalid storage category")
    sub = str(project_subdir).strip() if project_subdir else ""
    if sub:
        rel_prefix = f"{sub.replace(chr(92), '/')}/{safe_category}"
        return _safe_storage_path(storage_path, sub, safe_category), rel_prefix
    return _safe_storage_path(storage_path, safe_category), safe_category


def _timestamp_part() -> str:
    """等价 Node：new Date().toISOString().replace(/[-:]/g,'').slice(0,15) → 20260829T045448"""
    dt = datetime.now(timezone.utc)
    iso = f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"
    return iso.replace("-", "").replace(":", "")[:15]


def upload_file(
    storage_path,
    base_url: str,
    log,
    file_buffer: bytes,
    original_name: str,
    mime_type: str | None,
    category: str,
    project_subdir: str | None = None,
) -> dict:
    """写入本地存储，返回 { url, local_path }（local_path 为相对 storage 根的路径）。"""
    category_path, rel_prefix = resolve_category_paths(storage_path, category, project_subdir)
    category_path.mkdir(parents=True, exist_ok=True)

    ext = _safe_extension(original_name)
    name = f"{_timestamp_part()}_{uuid.uuid4()}{ext}"
    file_path = category_path / name
    with open(file_path, "wb") as f:
        f.write(file_buffer)

    relative_path = f"{rel_prefix}/{name}".replace("\\", "/")
    url = f"{base_url.rstrip('/')}/{relative_path}" if base_url else f"/static/{relative_path}"
    log.info("File uploaded", extra={"path": str(file_path), "url": url})
    return {"url": url, "local_path": relative_path}


def download_image_to_local(
    storage_path,
    image_url: str,
    category: str,
    log,
    prefix: str = "img",
    project_subdir: str | None = None,
) -> str | None:
    """等价 uploadService.downloadImageToLocal：下载图片到本地存储，返回相对路径。

    支持 http(s) URL 与 data URL（base64）。失败返回 None。
    """
    import base64
    import re
    import urllib.request

    if not image_url:
        return None
    try:
        if str(image_url).startswith("data:"):
            m = re.match(r"^data:([^;]+);base64,(.*)$", str(image_url), re.DOTALL)
            if not m:
                return None
            mime_type = m.group(1)
            content = base64.b64decode(m.group(2))
        else:
            req = urllib.request.Request(str(image_url), headers={"User-Agent": "LocalMiniDrama/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                content = resp.read()
                mime_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
                if not mime_type:
                    mime_type = "image/png"

        ext_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/bmp": ".bmp",
        }
        ext = ext_map.get(mime_type, ".png")

        category_path, rel_prefix = resolve_category_paths(storage_path, category, project_subdir)
        category_path.mkdir(parents=True, exist_ok=True)
        name = f"{prefix}_{_timestamp_part()}_{uuid.uuid4()}{ext}"
        file_path = category_path / name
        with open(file_path, "wb") as f:
            f.write(content)

        relative_path = f"{rel_prefix}/{name}".replace("\\", "/")
        log.info("Image downloaded to local", extra={"path": str(file_path), "bytes": len(content)})
        return relative_path
    except Exception as e:  # noqa: BLE001
        log.warning("downloadImageToLocal failed", extra={"error": str(e), "url": str(image_url)[:120]})
        return None


# ---------------- 中转图床 ----------------

_PROXY_EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

_PROXY_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _is_number(v) -> bool:
    """配置值是否为可参与算术的数字（bool 排除：True 会被当成 1）。"""
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, (int, float)):
        return v == v and v not in (float("inf"), float("-inf"))
    try:
        float(v)
    except (TypeError, ValueError):
        return False
    return True


def _clamp_int(v, lo: int, hi: int, default: int) -> int:
    """把配置值安全转为 [lo, hi] 内的 int；非法值（含 float 转换失败）返回 default。"""
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def get_image_proxy_upload_settings(cfg: dict | None = None) -> dict:
    """等价 getImageProxyUploadSettings：读 config.yaml 的 image_proxy 段。"""
    if cfg is None:
        try:
            from app.core.config import load_config

            cfg = load_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    ip = (cfg or {}).get("image_proxy") or {}
    return {
        "uploadUrl": str(ip.get("upload_url") or "https://imageproxy.zhongzhuan.chat/api/upload").strip(),
        "timeoutMs": max(5000, _clamp_int(
            (float(ip["upload_timeout_seconds"]) * 1000)
            if _is_number(ip.get("upload_timeout_seconds")) else None,
            5000, 10 ** 9, 45000)),
        "maxAttempts": _clamp_int(ip.get("upload_max_attempts"), 1, 5, 2),
    }


def upload_to_image_proxy(image_buffer: bytes, mime_type: str, log, tag, cfg: dict | None = None) -> str | None:
    """等价 uploadToImageProxy：multipart 上传到中转图床，返回公网 URL，失败返回 None。

    Node 用手拼 multipart body + fetch；此处用 httpx 的 files= 构造等价的
    multipart/form-data（字段名 file、原始 filename 与 Content-Type 一致）。
    """
    import time

    import httpx

    s = get_image_proxy_upload_settings(cfg)
    upload_url, timeout_ms, max_attempts = s["uploadUrl"], s["timeoutMs"], s["maxAttempts"]
    ext = _PROXY_EXT_BY_MIME.get(mime_type, "jpg")
    filename = f"ref_{int(time.time() * 1000)}.{ext}"
    # 注意：extra 的键不能是 LogRecord 保留属性（filename / msg / message 等），
    # 否则会抛 KeyError: Attempt to overwrite ... in LogRecord。故此处用 file_name。
    log.info("[图床上传] ▶ 开始", extra={
        "tag": tag, "file_name": filename, "size_kb": round(len(image_buffer) / 1024),
        "upload_url": upload_url, "timeout_sec": round(timeout_ms / 1000), "max_attempts": max_attempts,
    })

    for attempt in range(1, max_attempts + 1):
        t0 = time.time()
        try:
            resp = httpx.post(
                upload_url,
                files={"file": (filename, image_buffer, mime_type)},
                timeout=timeout_ms / 1000.0,
            )
            raw = resp.text
            ms = int((time.time() - t0) * 1000)
            if resp.status_code < 200 or resp.status_code >= 300:
                log.warning("[图床上传] 失败", extra={
                    "tag": tag, "attempt": attempt, "status": resp.status_code, "ms": ms,
                    "body": raw[:200],
                })
                if attempt < max_attempts:
                    continue
                return None
            try:
                data = json.loads(raw)
            except Exception:  # noqa: BLE001
                log.warning("[图床上传] 响应非 JSON", extra={"tag": tag, "attempt": attempt, "ms": ms,
                                                            "body": raw[:200]})
                if attempt < max_attempts:
                    continue
                return None
            url = data.get("url") if isinstance(data, dict) else None
            if url:
                log.info("[图床上传] ✓ 成功", extra={"tag": tag, "attempt": attempt, "url": url, "ms": ms})
                return url
            log.warning("[图床上传] 响应无 url 字段", extra={"tag": tag, "attempt": attempt, "ms": ms,
                                                            "body": raw[:200]})
            if attempt < max_attempts:
                continue
            return None
        except Exception as e:  # noqa: BLE001
            ms = int((time.time() - t0) * 1000)
            err = f"请求超时（{round(timeout_ms / 1000)}s）" if isinstance(e, httpx.TimeoutException) else str(e)
            log.warning("[图床上传] 请求异常", extra={"tag": tag, "attempt": attempt, "ms": ms, "reason": err})
            if attempt < max_attempts:
                continue
            return None
    return None


def upload_local_image_to_proxy(storage_path, local_path_or_url, log, tag, cfg: dict | None = None) -> str | None:
    """等价 uploadLocalImageToProxy：本地相对路径或 localhost URL → 图床 URL。"""
    try:
        s = str(local_path_or_url or "")
        file_path = None
        if s.startswith("http"):
            after_static = s.split("/static/")[1] if "/static/" in s else None
            if after_static and storage_path:
                file_path = Path(storage_path) / after_static.replace("/", os.sep).lstrip(os.sep)
        elif s and storage_path:
            file_path = (
                Path(s) if os.path.isabs(s)
                else Path(storage_path) / s.replace("/", os.sep).lstrip(os.sep)
            )
        if not file_path or not file_path.exists():
            log.warning("[图床上传] 本地文件不存在", extra={"tag": tag, "path": str(file_path)})
            return None
        mime = _PROXY_MIME_BY_EXT.get(file_path.suffix.lower(), "image/jpeg")
        with open(file_path, "rb") as fh:
            buf = fh.read()
        return upload_to_image_proxy(buf, mime, log, tag, cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("[图床上传] uploadLocalImageToProxy 异常", extra={"tag": tag, "reason": str(e)})
        return None
