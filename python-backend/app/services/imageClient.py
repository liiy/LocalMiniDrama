"""图片生成客户端 — 契约翻译 backend-node/src/services/imageClient.js。

覆盖的 provider 协议（inferProtocol）：
  dashscope（通义万象 wan2.6-image / 通义千问 qwen-image）
  nano_banana、gemini、volcengine（doubao-seedream）、kling、agnes、openai（其余）

与 Node 的差异仅在传输层：Node 用 http/https 模块与 fetch，Python 用 httpx。
sharp 压缩改用 Pillow（质量递减策略与 Node 一致：80 → 逐次 -15 → 下限 30）。

真实调用外部 AI（敏感区 R1-R8）不在本模块 mock；测试通过注入 base_url 打桩。
"""
from __future__ import annotations

import base64
import io
import json
import math
import mimetypes
import os
import re
import time
from typing import Any

import httpx

from app.core.logger import get_logger
from app.core.response import timestamp
from app.services import aiConfigService
from app.services import storageLayout
from app.services import taskService
from app.services import uploadService
from app.utils import seedance2AssetGuards

log = get_logger("lmd.imageClient")

IMAGE_HTTP_TIMEOUT_MS = 600_000

ANTI_SPLIT_NEGATIVE_PROMPT = (
    "nsfw, nudity, naked, violence, blood, gore, sensitive content, split panels, "
    "side-by-side layout, collage, diptych, triptych, grid layout, multiple panels, "
    "comparison view, composite image, two images in one frame"
)

DASHSCOPE_MIN_PIXELS = 589_824
DASHSCOPE_MAX_PIXELS = 1_638_400
SEEDREAM_MIN_PIXELS = 3_686_400

AGNES_IMAGE_SIZE_BY_RATIO = {
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "1:1": "1024x1024",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "21:9": "1792x1024",
}

GEMINI_ASPECT_NUMERIC = [
    ("21:9", 21 / 9),
    ("16:9", 16 / 9),
    ("3:2", 3 / 2),
    ("4:3", 4 / 3),
    ("5:4", 5 / 4),
    ("1:1", 1.0),
    ("4:5", 4 / 5),
    ("3:4", 3 / 4),
    ("2:3", 2 / 3),
    ("9:16", 9 / 16),
]

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


# ---------------- 通用小工具 ----------------


def merge_negative_prompt_fragments(auto: str, user: str) -> str:
    a = (auto or "").strip()
    u = (user or "").strip()
    if a and u:
        return f"{a}, {u}"
    return a or u or ""


def resolve_asset_user_negative_for_api(explicit_model_name, stored_negative) -> str:
    """请求里显式传 model 且资产上存有负面词时才生效。"""
    has_model = explicit_model_name is not None and str(explicit_model_name).strip()
    neg = str(stored_negative).strip() if stored_negative is not None else ""
    return neg if (has_model and neg) else ""


def get_proxy_expire_hours() -> float:
    try:
        from app.core.config import load_config
        cfg = load_config()
        return float(cfg.get("image_proxy", {}).get("expire_hours") or 24)
    except Exception:
        return 24.0


def get_proxy_cache(db, cache_key: str) -> str | None:
    if not db or not cache_key:
        return None
    try:
        row = db.execute(
            text("SELECT proxy_url, created_at FROM image_proxy_cache WHERE cache_key = :k"),
            {"k": cache_key},
        ).mappings().first()
        if not row or not row.get("proxy_url"):
            return None
        created_at_raw = row.get("created_at")
        expire_seconds = get_proxy_expire_hours() * 3600
        from datetime import datetime, timezone
        created_dt = None
        if isinstance(created_at_raw, datetime):
            created_dt = created_at_raw
        elif isinstance(created_at_raw, str):
            try:
                created_dt = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            except Exception:
                pass
        if created_dt:
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            if (now_dt - created_dt).total_seconds() > expire_seconds:
                delete_proxy_cache(db, cache_key)
                return None
        return row.get("proxy_url")
    except Exception:
        return None


def delete_proxy_cache(db, cache_key: str) -> None:
    if not db or not cache_key:
        return
    try:
        db.execute(text("DELETE FROM image_proxy_cache WHERE cache_key = :k"), {"k": cache_key})
        db.commit()
    except Exception:
        pass


def is_proxy_url_alive(url: str, timeout_sec: float = 8.0) -> bool:
    if not url or not re.match(r"^https?://", url, re.I):
        return False
    import urllib.request
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status in (200, 204, 206):
                return True
            if resp.status in (405, 501):
                req2 = urllib.request.Request(url, headers={"Range": "bytes=0-0"}, method="GET")
                with urllib.request.urlopen(req2, timeout=timeout_sec) as resp2:
                    return resp2.status in (200, 206)
            return False
    except Exception:
        return False


def get_proxy_cache_validated(db, cache_key: str, log=None, tag: str = "") -> str | None:
    url = get_proxy_cache(db, cache_key)
    if not url:
        return None
    if is_proxy_url_alive(url):
        return url
    delete_proxy_cache(db, cache_key)
    if log and hasattr(log, "warning"):
        log.warning(f"[图床缓存] URL 已失效，将重新上传 tag={tag} cache_key={cache_key}")
    return None


def set_proxy_cache(db, cache_key: str, proxy_url: str) -> None:
    if not db or not cache_key or not proxy_url:
        return
    try:
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        db.execute(
            text(
                "INSERT INTO image_proxy_cache (cache_key, proxy_url, created_at) VALUES (:k, :u, :c) "
                "ON CONFLICT(cache_key) DO UPDATE SET proxy_url = excluded.proxy_url, created_at = excluded.created_at"
            ),
            {"k": cache_key, "u": proxy_url, "c": now_str},
        )
        db.commit()
    except Exception:
        pass


# CamelCase aliases for Node compatibility
getProxyCache = get_proxy_cache
deleteProxyCache = delete_proxy_cache
isProxyUrlAlive = is_proxy_url_alive
getProxyCacheValidated = get_proxy_cache_validated
setProxyCache = set_proxy_cache


def _to_int(v) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def compress_image_buffer(buffer: bytes, mime_type: str, target_kb: int = 2048, log_=None) -> tuple[bytes, str]:
    """等价 compressImageBuffer：JPEG 质量递减压缩到 ≤ target_kb（80 → 每次 -15 → 下限 30）。

    Node 用 sharp，Python 用 Pillow；sharp 不可用时 Node 直接返回原图，
    此处 Pillow 失败同样返回原图。
    """
    target_bytes = target_kb * 1024
    if len(buffer) <= target_bytes:
        return buffer, mime_type
    try:
        from PIL import Image  # noqa: PLC0415

        quality = 80
        img = Image.open(io.BytesIO(buffer))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality)
        compressed = out.getvalue()
        while len(compressed) > target_bytes and quality > 30:
            quality -= 15
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality)
            compressed = out.getvalue()
        if len(compressed) < len(buffer):
            if log_:
                log_.info("[参考图压缩] 压缩完成", extra={
                    "original_kb": round(len(buffer) / 1024),
                    "compressed_kb": round(len(compressed) / 1024),
                    "quality": quality,
                })
            return compressed, "image/jpeg"
    except Exception as e:  # noqa: BLE001
        if log_:
            log_.warn("[参考图压缩] 压缩失败，使用原图", extra={"error": str(e)})
    return buffer, mime_type


def infer_protocol(provider, model) -> str:
    p = str(provider or "").lower()
    m = str(model or "")
    if p in ("dashscope", "qwen_image"):
        return "dashscope"
    if p == "nano_banana":
        return "nano_banana"
    if p in ("gemini", "google"):
        return "gemini"
    if p in ("volces", "volcengine", "volc"):
        return "volcengine"
    if re.search(r"seedream|doubao", m or "", re.IGNORECASE):
        return "volcengine"
    if p in ("kling", "klingai"):
        return "kling"
    if re.match(r"^kling-", m or "", re.IGNORECASE):
        return "kling"
    if p == "agnes" or re.search(r"agnes-image|apihub\.agnes-ai\.com", m or "", re.IGNORECASE):
        return "agnes"
    return "openai"


def get_default_image_config(db, preferred_model=None, preferred_provider=None, image_service_type: str | None = None):
    """等价 getDefaultImageConfig：storyboard_image 无配置时回退 image。"""
    service_type = image_service_type or "image"
    configs = aiConfigService.list_configs(db, service_type)
    if not configs and service_type == "storyboard_image":
        configs = aiConfigService.list_configs(db, "image")
    active = [c for c in configs if c.get("is_active")]
    if not active:
        return None
    if preferred_provider and str(preferred_provider).strip():
        want = str(preferred_provider).strip().lower()
        by_provider = [c for c in active if str(c.get("provider") or "").lower() == want]
        if by_provider:
            active = by_provider
    if preferred_model:
        for c in active:
            models = c.get("model") if isinstance(c.get("model"), list) else ([c["model"]] if c.get("model") is not None else [])
            if preferred_model in models:
                return c
    default_one = next((c for c in active if c.get("is_default")), None)
    return default_one if default_one is not None else active[0]


def build_image_url(config: dict) -> str:
    base = re.sub(r"/$", "", config.get("base_url") or "")
    ep = config.get("endpoint") or "/images/generations"
    if not ep.startswith("/"):
        ep = "/" + ep
    return base + ep


def get_model_from_config(config: dict, preferred_model=None) -> str:
    models = config.get("model") if isinstance(config.get("model"), list) else ([config["model"]] if config.get("model") is not None else [])
    if preferred_model and preferred_model in models:
        return preferred_model
    if config.get("default_model") and config.get("default_model") in models:
        return config["default_model"]
    return models[0] if models else "dall-e-3"


def fix_seedream_size(size) -> str:
    """Doubao-Seedream-4.5 最低 3,686,400 像素，不足则等比放大并对齐 64。"""
    if not size or not isinstance(size, str):
        return "1920x1920"
    s = size.strip().lower().replace("*", "x")
    m = re.match(r"^(\d+)\s*x\s*(\d+)$", s)
    if not m:
        return "1920x1920"
    w, h = _to_int(m.group(1)), _to_int(m.group(2))
    if not w or not h:
        return "1920x1920"
    pixels = w * h
    if pixels >= SEEDREAM_MIN_PIXELS:
        return f"{w}x{h}"
    scale = math.sqrt(SEEDREAM_MIN_PIXELS / pixels)
    w = math.ceil((w * scale) / 64) * 64
    h = math.ceil((h * scale) / 64) * 64
    if w * h < SEEDREAM_MIN_PIXELS:
        w += 64
        h += 64
    return f"{w}x{h}"


def is_agnes_image_config(config: dict, model) -> bool:
    p = str(config.get("provider") or "").lower()
    m = str(model or "").lower()
    base = str(config.get("base_url") or "").lower()
    return p == "agnes" or bool(re.search(r"agnes-image", m)) or bool(re.search(r"apihub\.agnes-ai\.com", base))


def fix_agnes_image_size(size) -> str:
    """映射到 Agnes 支持的尺寸，按对数距离选最接近的宽高比。"""
    if not size or not isinstance(size, str):
        return AGNES_IMAGE_SIZE_BY_RATIO["4:3"]
    s = size.strip().lower().replace("*", "x")
    m = re.match(r"^(\d+)\s*x\s*(\d+)$", s)
    if not m:
        return AGNES_IMAGE_SIZE_BY_RATIO["4:3"]
    w, h = _to_int(m.group(1)), _to_int(m.group(2))
    if not w or not h:
        return AGNES_IMAGE_SIZE_BY_RATIO["4:3"]
    ratio = w / h
    best = AGNES_IMAGE_SIZE_BY_RATIO["16:9"]
    best_diff = float("inf")
    for sz in AGNES_IMAGE_SIZE_BY_RATIO.values():
        rw, rh = (int(x) for x in sz.split("x"))
        d = abs(math.log(ratio) - math.log(rw / rh))
        if d < best_diff:
            best_diff = d
            best = sz
    return best


def dash_scope_size(size) -> str:
    """通义万象 size："宽*高"，总像素须在 589824～1638400，超出/不足则缩放并对齐 16。"""
    if not size or not isinstance(size, str):
        return "1280*1280"
    s = str(size).strip().lower().replace("x", "*")
    m = re.match(r"^(\d+)\s*\*\s*(\d+)$", s)
    if not m:
        return "1280*1280"
    w, h = _to_int(m.group(1)), _to_int(m.group(2))
    if not w or not h:
        return "1280*1280"
    pixels = w * h
    if DASHSCOPE_MIN_PIXELS <= pixels <= DASHSCOPE_MAX_PIXELS:
        return f"{w}*{h}"
    if pixels > DASHSCOPE_MAX_PIXELS:
        scale = math.sqrt(DASHSCOPE_MAX_PIXELS / pixels)
        w = max(16, round((w * scale) / 16) * 16)
        h = max(16, round((h * scale) / 16) * 16)
        if w * h > DASHSCOPE_MAX_PIXELS:
            w = min(w, 1280)
            h = min(h, math.floor(DASHSCOPE_MAX_PIXELS / w))
            h = math.floor(h / 16) * 16
        return f"{w}*{h}"
    scale = math.sqrt(DASHSCOPE_MIN_PIXELS / pixels)
    w = max(384, round((w * scale) / 16) * 16)
    h = max(384, round((h * scale) / 16) * 16)
    return f"{w}*{h}"


def parse_dash_scope_image_url(data) -> str | None:
    """从 output.choices 中取第一张图 URL（兼容 type="image" 或仅有 image 字段）。"""
    choices = (data or {}).get("output", {}).get("choices")
    if not isinstance(choices, list):
        return None
    for c in choices:
        content = (c or {}).get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part and part.get("image") and (part.get("type") == "image" or not part.get("type")):
                return part["image"]
    return None


def closest_gemini_aspect_ratio_from_pixels(w, h) -> str:
    if not w or not h:
        return "1:1"
    r = w / h
    best, best_d = "1:1", float("inf")
    for label, tr in GEMINI_ASPECT_NUMERIC:
        d = abs(math.log(r) - math.log(tr))
        if d < best_d:
            best_d, best = d, label
    return best


def gemini_aspect_ratio(size) -> str:
    if not size or not isinstance(size, str):
        return "16:9"
    s = str(size).strip().lower().replace(" ", "")
    ratio_set = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"}
    if s in ratio_set:
        return s
    m = re.match(r"^(\d+)[x*](\d+)$", s)
    if not m:
        return "1:1"
    w, h = _to_int(m.group(1)), _to_int(m.group(2))
    return closest_gemini_aspect_ratio_from_pixels(w, h)


def parse_size_wx_h_for_gemini(size):
    m = re.match(r"^(\d+)[x*](\d+)$", str(size or "").strip().lower().replace(" ", ""))
    if not m:
        return None
    w, h = _to_int(m.group(1)), _to_int(m.group(2))
    if not w or not h:
        return None
    return {"w": w, "h": h}


def build_gemini_image_config(aspect_ratio: str, model_name, size) -> dict:
    """宽高比在 generationConfig.imageConfig.aspectRatio；imageSize 仅 gemini-3.x 支持。"""
    image_config = {"aspectRatio": aspect_ratio}
    m = str(model_name or "").lower()
    supports_image_size = ("gemini-3" in m) or ("3.1-flash-image" in m) or ("3-pro-image" in m)
    if supports_image_size:
        px = parse_size_wx_h_for_gemini(size)
        long_edge = max(px["w"], px["h"]) if px else 0
        image_config["imageSize"] = "2K" if long_edge >= 1200 else "1K"
    return image_config


def nano_banana_aspect_ratio(size) -> str:
    if not size or not isinstance(size, str):
        return "auto"
    s = str(size).strip().lower().replace(" ", "")
    ratio_set = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"}
    if s in ratio_set:
        return s
    m = re.match(r"^(\d+)[x*](\d+)$", s)
    if not m:
        return "auto"
    w, h = _to_int(m.group(1)), _to_int(m.group(2))
    if not w or not h:
        return "auto"
    return closest_gemini_aspect_ratio_from_pixels(w, h)


def kling_image_aspect_ratio(size) -> str:
    if not size:
        return "16:9"
    s = str(size).strip().lower().replace(" ", "")
    ratio_set = {"16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"}
    if s in ratio_set:
        return s
    m = re.match(r"^(\d+)[x*](\d+)$", s)
    if not m:
        return "1:1"
    w, h = _to_int(m.group(1)), _to_int(m.group(2))
    return closest_gemini_aspect_ratio_from_pixels(w, h)


def resolve_image_ref(value, files_base_url: str, storage_local_path: str) -> str | None:
    """本地路径/localhost URL → base64 data URL；公网 URL → 原样返回。"""
    if not value or not str(value).strip():
        return None
    s = str(value).strip()
    base_url = re.sub(r"/$", "", files_base_url or "")
    is_localhost_url = bool(re.search(r"localhost|127\.0\.0\.1", s, re.IGNORECASE))
    is_localhost_base = bool(base_url) and bool(re.search(r"localhost|127\.0\.0\.1", base_url, re.IGNORECASE))
    is_localhost = is_localhost_url or is_localhost_base

    def to_public_url(v) -> str | None:
        if not v or not str(v).strip():
            return None
        sv = str(v).strip()
        if sv.startswith("http://") or sv.startswith("https://"):
            return sv
        if base_url:
            return base_url + "/" + re.sub(r"^/", "", sv)
        return sv

    rel_path = None
    if s.startswith("http://") or s.startswith("https://"):
        if (not is_localhost) or (not storage_local_path):
            return s
        after_static = (
            s.split("/static/")[1] if "/static/" in s
            else (re.sub(r"^/", "", s.replace(base_url + "/", "").replace(base_url, "")) if base_url else None)
            or re.sub(r"^https?://[^/]+/", "", s)
        )
        if after_static:
            rel_path = re.sub(r"^/", "", after_static)
        else:
            return s
    elif storage_local_path:
        rel_path = re.sub(r"^/", "", s)

    if not rel_path:
        return to_public_url(s)
    file_path = os.path.join(storage_local_path, rel_path)
    try:
        if not os.path.exists(file_path):
            return to_public_url(s)
        with open(file_path, "rb") as fh:
            buf = fh.read()
        ext = os.path.splitext(file_path)[1].lower()
        mime = _MIME_BY_EXT.get(ext, "image/png")
        return "data:" + mime + ";base64," + base64.b64encode(buf).decode("ascii")
    except Exception:  # noqa: BLE001
        return to_public_url(s)


# ---------------- 传输 ----------------


def _post_json(url: str, headers: dict, body: Any, timeout_ms: int = IMAGE_HTTP_TIMEOUT_MS) -> tuple[int, str]:
    """返回 (status_code, raw_text)。网络异常抛 RuntimeError。"""
    import httpx as _httpx

    body_str = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    try:
        resp = _httpx.post(
            url, content=body_str.encode("utf-8"), headers=req_headers, timeout=timeout_ms / 1000.0
        )
    except _httpx.TimeoutException as exc:
        raise RuntimeError(f"Image generation HTTP timeout after {timeout_ms}ms") from exc
    return resp.status_code or 0, resp.text


def _fetch_bytes(url: str, headers: dict | None = None) -> tuple[int, bytes, str]:
    """GET 二进制，返回 (status, content, content_type)。"""
    import httpx as _httpx

    resp = _httpx.get(url, headers=headers or {}, timeout=60.0)
    return resp.status_code, resp.content, (resp.headers.get("content-type") or "").split(";")[0].strip()


def _err_from_http(status: int, raw: str, prefix: str) -> str:
    """统一 HTTP 错误文案：优先 JSON 的 message / error.message / error，否则截断原文。"""
    msg = f"{prefix}: {status}"
    try:
        err = json.loads(raw)
        m = None
        if isinstance(err, dict):
            m = (err.get("error") or {}).get("message") if isinstance(err.get("error"), dict) else None
            m = m or err.get("message") or err.get("error") or err.get("msg")
        if m:
            msg += " - " + (m if isinstance(m, str) else json.dumps(m, ensure_ascii=False)[:200])
    except Exception:  # noqa: BLE001
        if raw:
            msg += " - " + raw[:200]
    return msg


# ---------------- 各 provider ----------------


def call_dash_scope_image_api(config: dict, log_, opts: dict) -> dict:
    """通义万象 wan2.6-image / 通义千问 qwen-image。"""
    prompt = opts.get("prompt")
    model = opts.get("model")
    size = opts.get("size")
    image_gen_id = opts.get("image_gen_id")
    reference_image_urls = opts.get("reference_image_urls")
    files_base_url = opts.get("files_base_url")
    storage_local_path = opts.get("storage_local_path")
    negative_prompt = opts.get("negative_prompt")

    base = re.sub(r"/$", "", config.get("base_url") or "")
    url = base + (config.get("endpoint") or "/api/v1/services/aigc/multimodal-generation/generation")
    if "dashscope" not in url:
        return {"error": "通义万象 base_url 需为 https://dashscope.aliyuncs.com"}

    is_qwen_image = bool(re.search(r"^qwen-image", str(model or ""), re.IGNORECASE)) or str(
        config.get("provider") or ""
    ).lower() == "qwen_image"

    if is_qwen_image:
        text = str(prompt or "").strip()[:800]
        body: dict[str, Any] = {
            "model": model or "qwen-image-max",
            "input": {"messages": [{"role": "user", "content": [{"text": text}]}]},
            "parameters": {
                "prompt_extend": True,
                "watermark": False,
                "size": dash_scope_size(size),
            },
        }
        if negative_prompt and str(negative_prompt).strip():
            body["parameters"]["negative_prompt"] = str(negative_prompt).strip()[:500]
        log_.info("Image API request (Qwen-Image sync)", extra={"model": body["model"], "image_gen_id": image_gen_id})
        try:
            http_status, raw = _post_json(
                url, {"Authorization": "Bearer " + (config.get("api_key") or "")}, body
            )
        except Exception as e:  # noqa: BLE001
            return {"error": "图片生成网络请求失败: " + str(e)}
        if http_status < 200 or http_status >= 300:
            return {"error": _err_from_http(http_status, raw, "图片生成请求失败")}
        try:
            data = json.loads(raw)
            if data.get("code"):
                return {"error": data.get("message") or data.get("code") or "通义千问接口错误"}
            image_url = parse_dash_scope_image_url(data)
            if image_url:
                return {"image_url": image_url}
            return {"error": "未返回图片地址"}
        except Exception:  # noqa: BLE001
            return {"error": "通义千问返回格式异常"}

    refs = [r for r in (reference_image_urls or []) if r]
    content: list[dict] = [{"text": prompt or ""}]
    for ref in refs[:10]:
        img = resolve_image_ref(ref, files_base_url, storage_local_path)
        if img:
            content.append({"image": img})

    has_refs = len(content) > 1
    stream = not has_refs  # enable_interleave=false 时必须 stream=false
    body = {
        "model": model or "wan2.6-image",
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {
            "prompt_extend": True,
            "watermark": False,
            "n": 1,
            "enable_interleave": not has_refs,
            "size": dash_scope_size(size),
            "stream": stream,
            **({"negative_prompt": negative_prompt or ANTI_SPLIT_NEGATIVE_PROMPT} if has_refs
               else ({"negative_prompt": negative_prompt} if negative_prompt else {})),
        },
    }
    headers = {"Authorization": "Bearer " + (config.get("api_key") or "")}
    if stream:
        headers["X-DashScope-Sse"] = "enable"
    try:
        http_status, raw = _post_json(url, headers, body)
    except Exception as e:  # noqa: BLE001
        return {"error": "图片生成网络请求失败: " + str(e)}
    if http_status < 200 or http_status >= 300:
        return {"error": _err_from_http(http_status, raw, "图片生成请求失败")}

    if not stream:
        try:
            data = json.loads(raw)
            if data.get("code"):
                return {"error": data.get("message") or data.get("code") or "通义万象接口错误"}
            image_url = parse_dash_scope_image_url(data)
            return {"image_url": image_url} if image_url else {"error": "未返回图片地址"}
        except Exception:  # noqa: BLE001
            return {"error": "通义万象返回格式异常"}

    last_image_url = None
    lines = [ln.strip() for ln in re.split(r"\r?\n", raw) if ln.strip()]
    for line in lines:
        json_str = line
        if line.startswith("data:"):
            json_str = line[5:].strip()
            if not json_str or json_str == "[DONE]":
                continue
        try:
            data = json.loads(json_str)
            if data.get("code"):
                return {"error": data.get("message") or data.get("code") or "通义万象接口错误"}
            url_from_chunk = parse_dash_scope_image_url(data)
            if url_from_chunk:
                last_image_url = url_from_chunk
        except Exception:  # noqa: BLE001
            continue
    if last_image_url:
        return {"image_url": last_image_url}
    if lines:
        try:
            first_line = lines[0][5:].strip() if lines[0].startswith("data:") else lines[0]
            first = json.loads(first_line)
            if first.get("code"):
                return {"error": first.get("message") or first.get("code") or "通义万象接口错误"}
        except Exception:  # noqa: BLE001
            pass
    return {"error": "未返回图片地址"}


def call_nano_banana_image_api(config: dict, log_, opts: dict) -> dict:
    """NanoBanana：提交任务后轮询 record-info。"""
    prompt = opts.get("prompt")
    model = opts.get("model")
    size = opts.get("size")
    image_gen_id = opts.get("image_gen_id")
    reference_image_urls = opts.get("reference_image_urls")
    files_base_url = opts.get("files_base_url")
    storage_local_path = opts.get("storage_local_path")

    base = re.sub(r"/$", "", config.get("base_url") or "")
    submit_url = base + (config.get("endpoint") or "/api/v1/nanobanana/generate")
    m = model or "nano-banana"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + (config.get("api_key") or ""),
    }

    refs = [r for r in (reference_image_urls or []) if r]
    resolved_refs = [x for x in (resolve_image_ref(r, files_base_url, storage_local_path) for r in refs) if x]

    body: dict[str, Any] = {
        "model": m,
        "prompt": prompt or "",
        "aspectRatio": nano_banana_aspect_ratio(size),
    }
    if resolved_refs:
        body["imageUrls"] = resolved_refs
    if config.get("callBackUrl"):
        body["callBackUrl"] = config.get("callBackUrl")

    try:
        submit_status, submit_raw = _post_json(submit_url, headers, body)
    except Exception as e:  # noqa: BLE001
        return {"error": "NanoBanana 图片生成网络请求失败: " + str(e)}
    if submit_status < 200 or submit_status >= 300:
        return {"error": _err_from_http(submit_status, submit_raw, "NanoBanana 图片生成请求失败")}
    try:
        submit_data = json.loads(submit_raw)
    except Exception:  # noqa: BLE001
        return {"error": "NanoBanana 返回格式异常"}

    # 同步代理响应：直接返回图片 URL，无需轮询
    sd_images = (submit_data or {}).get("images")
    sd0 = sd_images[0] if isinstance(sd_images, list) and sd_images else None
    sd_top_first = None
    if isinstance(sd0, str) and sd0 and not re.match(r"^https?://", sd0, re.IGNORECASE) and not (isinstance(sd_images[0], dict) and sd_images[0].get("url")):
        sd_top_first = sd0 if sd0.startswith("data:") else f"data:image/png;base64,{re.sub(r'\\s', '', sd0)}"
    data = submit_data.get("data") or {}
    direct_image_url = (
        (isinstance(sd_images, list) and sd_images and isinstance(sd_images[0], dict) and sd_images[0].get("url"))
        or sd_top_first
        or (submit_data.get("image") or {}).get("url")
        or submit_data.get("image_url")
        or (data.get("url") if isinstance(data, dict) else None)
        or submit_data.get("url")
        or ((data.get("data", {}).get("images", [{}])[0].get("url")) if isinstance(data, dict) and data.get("state") == "succeeded" else None)
    )
    if direct_image_url:
        return {"image_url": direct_image_url}

    task_id = (
        (data.get("taskId") or data.get("task_id")) if isinstance(data, dict) else None
    ) or submit_data.get("request_id") or submit_data.get("taskId")
    if not task_id:
        msg = submit_data.get("msg") or submit_data.get("message") or "未返回任务ID"
        return {"error": "NanoBanana 提交失败: " + str(msg)[:200]}

    default_query_ep = "/api/v1/nanobanana/record-info"
    cfg_q_ep = config.get("query_endpoint") or ""
    if cfg_q_ep and not cfg_q_ep.startswith("/"):
        cfg_q_ep = "/" + cfg_q_ep
    use_query_ep = cfg_q_ep if (cfg_q_ep and cfg_q_ep != default_query_ep) else default_query_ep

    def build_query_url(tid) -> str:
        if re.search(r"\{(taskId|taskid|task_id|id)\}", use_query_ep, re.IGNORECASE):
            from urllib.parse import quote

            q = quote(str(tid))
            return (
                base
                + re.sub(r"\{taskId\}", q, use_query_ep, flags=re.IGNORECASE)
                .replace("{task_id}", q)
                .replace("{id}", q)
            )
        from urllib.parse import quote

        return base + use_query_ep + "?taskId=" + quote(str(tid))

    for attempt in range(60):
        time.sleep(3)
        try:
            poll_status, poll_raw_bytes, _ = _fetch_bytes(build_query_url(task_id), headers)
            poll_raw = poll_raw_bytes.decode("utf-8", "ignore")
            if poll_status < 200 or poll_status >= 300:
                continue
            try:
                query_data = json.loads(poll_raw)
            except Exception:  # noqa: BLE001
                continue
            qd = query_data.get("data") or {}
            success_flag = qd.get("successFlag")
            state = qd.get("state")
            status = qd.get("status")
            if success_flag in (1,) or state == "succeeded" or status == "3":
                resp_imgs = (qd.get("response") or {}).get("images")
                from_sd_wrapped = None
                if isinstance(resp_imgs, list) and resp_imgs and isinstance(resp_imgs[0], str) and resp_imgs[0]:
                    from_sd_wrapped = resp_imgs[0] if resp_imgs[0].startswith("data:") else f"data:image/png;base64,{re.sub(r'\\s', '', resp_imgs[0])}"
                image_url = (
                    (qd.get("response") or {}).get("resultImageUrl")
                    or (qd.get("response") or {}).get("originImageUrl")
                    or (qd.get("data", {}).get("images", [{}])[0].get("url"))
                    or from_sd_wrapped
                )
                if image_url:
                    return {"image_url": image_url}
                return {"error": "未返回图片地址"}
            if success_flag in (2, 3) or state == "failed":
                err_msg = qd.get("errorMessage") or qd.get("msg") or "任务失败"
                return {"error": "NanoBanana 生成失败: " + str(err_msg)}
        except Exception:  # noqa: BLE001
            continue
    return {"error": "NanoBanana 图片生成超时"}


def call_kling_image_api(config: dict, log_, opts: dict) -> dict:
    """可灵图生：/v1/images/generations，image 为 base64 数组。"""
    prompt = opts.get("prompt")
    model = opts.get("model")
    size = opts.get("size")
    image_gen_id = opts.get("image_gen_id")
    reference_image_urls = opts.get("reference_image_urls")
    files_base_url = opts.get("files_base_url")
    storage_local_path = opts.get("storage_local_path")

    base = re.sub(r"/$", "", config.get("base_url") or "")
    url = base + (config.get("endpoint") or "/v1/images/generations")

    refs = [r for r in (reference_image_urls or []) if r]
    resolved_refs = [x for x in (resolve_image_ref(r, files_base_url, storage_local_path) for r in refs[:6]) if x]
    b64_list = []
    for r in resolved_refs:
        if r.startswith("data:"):
            mm = re.match(r"^data:[^;]+;base64,(.*)$", r, re.DOTALL)
            if mm:
                b64_list.append(mm.group(1))
        else:
            b64_list.append(r)

    body: dict[str, Any] = {
        "model": model or "kling-v1-5",
        "prompt": prompt or "",
        "aspect_ratio": kling_image_aspect_ratio(size),
        "n": 1,
    }
    if b64_list:
        body["image"] = b64_list

    headers = {"Authorization": "Bearer " + (config.get("api_key") or "")}
    try:
        http_status, raw = _post_json(url, headers, body)
    except Exception as e:  # noqa: BLE001
        return {"error": "可灵图片生成网络请求失败: " + str(e)}
    if http_status < 200 or http_status >= 300:
        return {"error": _err_from_http(http_status, raw, "可灵图片生成请求失败")}
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"error": "可灵图片生成返回格式异常"}
    items = data.get("data") or []
    if items and isinstance(items[0], dict):
        u = items[0].get("url") or items[0].get("image_url")
        if u:
            return {"image_url": u}
    return {"error": "未返回图片地址"}


def call_gemini_image_api(db, config: dict, log_, opts: dict) -> dict:
    """Gemini：interleaved text+image parts，宽高比在 generationConfig.imageConfig。"""
    prompt = opts.get("prompt")
    model = opts.get("model")
    size = opts.get("size")
    image_gen_id = opts.get("image_gen_id")
    reference_image_urls = opts.get("reference_image_urls")
    files_base_url = opts.get("files_base_url")
    storage_local_path = opts.get("storage_local_path")
    system_prompt = opts.get("system_prompt")

    api_key = config.get("api_key") or ""
    base = re.sub(r"/$", "", config.get("base_url") or "https://generativelanguage.googleapis.com")
    model_name = model or "gemini-2.5-flash-image"
    aspect_ratio = gemini_aspect_ratio(size)
    gemini_image_config = build_gemini_image_config(aspect_ratio, model_name, size)

    raw_refs = [r for r in (reference_image_url for reference_image_url in (reference_image_urls or [])) if r]
    max_gemini_ref_images = 4

    ref_label_map: dict[int, str] = {}
    if system_prompt:
        for line in str(system_prompt).split("\n"):
            mm = re.match(r"^Image\s+(\d+):\s*(.+)", line, re.IGNORECASE)
            if mm:
                ref_label_map[int(mm.group(1)) - 1] = mm.group(2).strip()

    total_ref_limit_bytes = 10 * 1024 * 1024
    total_ref_size_bytes = 0
    ref_image_parts: list[dict] = []

    for i in range(len(raw_refs[:max_gemini_ref_images])):
        ref = raw_refs[i]
        resolved = resolve_image_ref(ref, files_base_url, storage_local_path)
        if not resolved:
            continue
        if resolved.startswith("data:"):
            mm = re.match(r"^data:([\w/]+);base64,(.+)$", resolved, re.DOTALL)
            if not mm:
                continue
            mime_type = mm.group(1)
            image_buffer = base64.b64decode(mm.group(2))
        else:
            try:
                st, image_buffer, ct = _fetch_bytes(resolved)
                if st < 200 or st >= 300:
                    continue
                mime_type = ct or "image/jpeg"
            except Exception:  # noqa: BLE001
                continue

        if len(image_buffer) > 10 * 1024 * 1024:
            continue
        if len(image_buffer) > 2 * 1024 * 1024:
            image_buffer, mime_type = compress_image_buffer(image_buffer, mime_type, 2048, log_)

        remaining = total_ref_limit_bytes - total_ref_size_bytes
        if len(image_buffer) > remaining:
            target_kb = max(200, math.floor(remaining / 1024))
            image_buffer, mime_type = compress_image_buffer(image_buffer, mime_type, target_kb, log_)
            if len(image_buffer) > remaining:
                continue
        total_ref_size_bytes += len(image_buffer)

        ref_image_parts.append({
            "label": ref_label_map.get(i),
            "imagePart": {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(image_buffer).decode("ascii")}},
        })

    parts: list[dict] = []
    if ref_image_parts:
        parts.append({"text": "The following are visual reference images. Use them ONLY to maintain character appearance and scene environment consistency. Do NOT reproduce their layout or format."})
        for i, item in enumerate(ref_image_parts):
            label = item["label"]
            parts.append({"text": f"Reference {i + 1}: {label}" if label else f"Reference {i + 1}:"})
            parts.append(item["imagePart"])
        parts.append({"text": f"Generate ONE single cinematic storyboard frame (do NOT create a grid or multi-panel layout):\n\n{prompt or ''}"})
    else:
        parts.append({"text": prompt or ""})

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
            "numberOfImages": 1,
            "imageConfig": gemini_image_config,
        },
    }
    from urllib.parse import quote

    url = f"{base}/v1beta/models/{quote(model_name, safe='')}:generateContent?key={quote(api_key, safe='')}"
    try:
        gemini_status, raw = _post_json(url, {"Content-Type": "application/json"}, body)
    except Exception as e:  # noqa: BLE001
        return {"error": "Gemini 图片生成网络请求失败: " + str(e)}
    if gemini_status < 200 or gemini_status >= 300:
        return {"error": _err_from_http(gemini_status, raw, "Gemini 图片生成请求失败")}
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"error": "Gemini 图片生成返回格式异常"}
    for candidate in data.get("candidates") or []:
        for part in ((candidate or {}).get("content") or {}).get("parts") or []:
            if (part or {}).get("inlineData", {}).get("data"):
                mime = part["inlineData"].get("mimeType") or "image/png"
                return {"image_url": f"data:{mime};base64,{part['inlineData']['data']}"}
    return {"error": "Gemini 未返回图片内容，请检查模型名称或 API Key 权限"}


# ---------------- 主入口 ----------------


def call_image_api(db, log_, opts: dict) -> dict:
    """按 api_protocol（或 provider 推断）路由到各 provider 实现。"""
    prompt = opts.get("prompt")
    preferred_model = opts.get("model")
    size = opts.get("size")
    quality = opts.get("quality")
    image_gen_id = opts.get("image_gen_id")
    image_service_type = opts.get("imageServiceType")
    reference_image_urls = opts.get("reference_image_urls")
    files_base_url = opts.get("files_base_url")
    storage_local_path = opts.get("storage_local_path")
    system_prompt = opts.get("system_prompt")
    user_negative_prompt = opts.get("user_negative_prompt")
    preferred_provider = opts.get("preferred_provider") if opts.get("preferred_provider") is not None else opts.get("preferredProvider")

    config = get_default_image_config(db, preferred_model, preferred_provider, image_service_type)
    if not config:
        raise RuntimeError("未配置图片模型，请在「AI 配置」中添加 image 类型且已启用的配置")
    model = get_model_from_config(config, preferred_model)
    provider = str(config.get("provider") or "").lower()
    protocol = str(config.get("api_protocol") or "").lower() or infer_protocol(provider, model)

    # 参考图标签注入（Gemini 走 parts 结构，不注入文字）
    effective_prompt = prompt or ""
    if protocol != "gemini" and isinstance(reference_image_urls, list) and reference_image_urls and system_prompt:
        ref_lines = [l for l in str(system_prompt).split("\n") if re.match(r"^Image\s+\d+:", l, re.IGNORECASE)]
        if ref_lines:
            ref_header = "\n".join(f"[{l} — FOR REFERENCE ONLY, DO NOT copy its layout or framing]" for l in ref_lines)
            effective_prompt = f"{ref_header}\n\n[GENERATE THIS SCENE — single continuous image, no grid, no split panels]:\n{effective_prompt}"

    ref_count = len([r for r in (reference_image_urls or []) if r])
    is_volc_or_seedream = protocol == "volcengine" or bool(re.search(r"seedream|doubao", model or "", re.IGNORECASE))
    auto_negative = ANTI_SPLIT_NEGATIVE_PROMPT if (ref_count > 1 or is_volc_or_seedream) else ""
    user_neg = str(user_negative_prompt).strip() if user_negative_prompt else ""
    merged_negative = merge_negative_prompt_fragments(auto_negative, user_neg)

    if protocol == "dashscope":
        return call_dash_scope_image_api(config, log_, {
            "prompt": effective_prompt, "model": model, "size": size, "image_gen_id": image_gen_id,
            "reference_image_urls": reference_image_urls,
            "files_base_url": files_base_url,
            "storage_local_path": storage_local_path,
            "negative_prompt": merged_negative,
        })
    if protocol == "nano_banana":
        return call_nano_banana_image_api(config, log_, {
            "prompt": effective_prompt, "model": model, "size": size, "image_gen_id": image_gen_id,
            "reference_image_urls": reference_image_urls,
            "files_base_url": files_base_url,
            "storage_local_path": storage_local_path,
        })
    if protocol == "kling":
        return call_kling_image_api(config, log_, {
            "prompt": effective_prompt, "model": model, "size": size, "image_gen_id": image_gen_id,
            "reference_image_urls": reference_image_urls,
            "files_base_url": files_base_url,
            "storage_local_path": storage_local_path,
        })
    if protocol == "gemini":
        return call_gemini_image_api(db, config, log_, {
            "prompt": prompt, "model": model, "size": size, "image_gen_id": image_gen_id,
            "reference_image_urls": reference_image_urls,
            "files_base_url": files_base_url,
            "storage_local_path": storage_local_path,
            "system_prompt": system_prompt,
        })

    url = build_image_url(config)
    is_volc = protocol == "volcengine"
    is_agnes = is_agnes_image_config(config, model)
    is_seedream = is_volc or bool(re.search(r"seedream|doubao", model or "", re.IGNORECASE))

    raw_refs = [r for r in (reference_image_urls or []) if r]
    resolved_refs = [x for x in (resolve_image_ref(r, files_base_url, storage_local_path) for r in raw_refs) if x]

    effective_size = size
    if is_seedream and size:
        effective_size = fix_seedream_size(size)
    elif is_agnes and size:
        effective_size = fix_agnes_image_size(size)

    body: dict[str, Any] = {
        "model": model,
        "prompt": effective_prompt,
        **({} if is_seedream else {"n": 1}),
        **({"size": effective_size} if effective_size else {}),
        **({"quality": quality} if quality else {}),
        **({"watermark": False} if (is_volc or is_seedream) else {}),
        **({"negative_prompt": merged_negative} if merged_negative else {}),
        **({"image": resolved_refs} if (resolved_refs and not is_agnes) else {}),
        **({"extra_body": {"image": resolved_refs, "response_format": "url"}} if (is_agnes and resolved_refs) else {}),
    }
    try:
        http_status, raw = _post_json(
            url, {"Authorization": "Bearer " + (config.get("api_key") or "")}, body
        )
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        return {"error": msg if "timeout" in msg else ("图片生成网络请求失败: " + msg)}
    if http_status < 200 or http_status >= 300:
        return {"error": _err_from_http(http_status, raw, "图片生成请求失败")}
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"error": "图片生成返回格式异常"}

    item = (data.get("data") or [None])[0] if isinstance(data.get("data"), list) else None
    image_url = (item or {}).get("url") or (item or {}).get("image_url") if isinstance(item, dict) else None
    if not image_url and isinstance(item, dict) and item.get("b64_json"):
        image_url = f"data:image/png;base64,{re.sub(r'\\s', '', str(item['b64_json']))}"
    if not image_url and isinstance(data.get("images"), list) and data["images"]:
        first = data["images"][0]
        if isinstance(first, str) and first:
            image_url = first if first.startswith("data:") else f"data:image/png;base64,{re.sub(r'\\s', '', first)}"
    if not image_url:
        return {"error": "未返回图片地址"}
    return {"image_url": image_url}


# ---------------- 记录 + 异步执行 ----------------


def create_and_generate_image(db, log_, opts: dict) -> dict:
    """建 image_generations + async_tasks 记录，返回 { image_generation_id, task_id }。

    等价 Node createAndGenerateImage：建记录后 setImmediate 触发后台生成。
    此处用 workerService 提交到线程池（语义一致：调用后立即返回）。

    后台任务在 worker 线程内自建 Session（Session 非线程安全，不能复用请求级 db）。
    """
    drama_id = opts.get("drama_id")
    character_id = opts.get("character_id")
    scene_id = opts.get("scene_id")
    image_type = opts.get("image_type")
    prompt = opts.get("prompt")
    model = opts.get("model")
    size = opts.get("size")
    quality = opts.get("quality")
    provider = opts.get("provider")
    user_negative_prompt = opts.get("user_negative_prompt")

    neg_row = str(user_negative_prompt).strip() if (user_negative_prompt and str(user_negative_prompt).strip()) else None
    now = timestamp()
    drama_id_num = _to_int(drama_id) or 0
    char_id_num = _to_int(character_id) if character_id is not None else None
    scene_id_num = _to_int(scene_id) if scene_id is not None else None

    if char_id_num is not None:
        resource_id = f"character_{char_id_num}"
    elif scene_id_num is not None:
        resource_id = f"scene_{scene_id_num}"
    else:
        resource_id = str(drama_id_num)

    task = taskService.create_task(db, log_, "image_generation", resource_id)
    task_id = task["id"] if isinstance(task, dict) else task

    from sqlalchemy import text as _text

    try:
        res = db.execute(
            _text(
                "INSERT INTO image_generations (drama_id, character_id, scene_id, provider, prompt, "
                "negative_prompt, model, size, quality, status, task_id, created_at, updated_at) "
                "VALUES (:drama_id, :character_id, :scene_id, :provider, :prompt, :negative_prompt, "
                ":model, :size, :quality, 'pending', :task_id, :created_at, :updated_at)"
            ),
            {
                "drama_id": drama_id_num, "character_id": char_id_num, "scene_id": scene_id_num,
                "provider": provider or "openai", "prompt": prompt or "", "negative_prompt": neg_row,
                "model": model, "size": size, "quality": quality, "task_id": task_id,
                "created_at": now, "updated_at": now,
            },
        )
        image_gen_id = res.lastrowid
    except Exception as e:  # noqa: BLE001
        if "scene_id" in str(e) or "character_id" in str(e):
            res = db.execute(
                _text(
                    "INSERT INTO image_generations (drama_id, provider, prompt, model, size, quality, "
                    "status, task_id, created_at, updated_at) "
                    "VALUES (:drama_id, :provider, :prompt, :model, :size, :quality, 'pending', :task_id, :created_at, :updated_at)"
                ),
                {
                    "drama_id": drama_id_num, "provider": provider or "openai", "prompt": prompt or "",
                    "model": model, "size": size, "quality": quality, "task_id": task_id,
                    "created_at": now, "updated_at": now,
                },
            )
            image_gen_id = res.lastrowid
        else:
            raise

    # 等价 Node 的 setImmediate：后台执行真实生成
    from app.core.config import load_config
    from app.services import workerService

    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001
        cfg = {}
    workerService.submit(_image_generation_job, image_gen_id, opts, cfg)

    return {"id": image_gen_id, "image_generation_id": image_gen_id, "task_id": task_id}


def _image_generation_job(image_gen_id, opts: dict, cfg: dict) -> None:
    """worker 线程入口：自建 Session 执行生成（Session 非线程安全）。"""
    from app.core.logger import get_logger
    from app.services import workerService

    log = get_logger("lmd.imageClient")
    try:
        with workerService.session_scope() as db:
            run_image_generation(db, log, image_gen_id, opts, cfg)
    except Exception as e:  # noqa: BLE001
        log.error("Image generation job failed", extra={"image_gen_id": image_gen_id, "reason": str(e)})


def run_image_generation(db, log_, image_gen_id, opts: dict, cfg: dict | None = None) -> None:
    """执行生成并回写 image_generations / characters / scenes / async_tasks。

    对应 Node createAndGenerateImage 里 setImmediate 的异步体。
    """
    from sqlalchemy import text as _text

    character_id = opts.get("character_id")
    scene_id = opts.get("scene_id")
    drama_id = opts.get("drama_id")
    char_id_num = _to_int(character_id) if character_id is not None else None
    scene_id_num = _to_int(scene_id) if scene_id is not None else None
    drama_id_num = _to_int(drama_id) or 0

    task_row = db.execute(
        _text("SELECT task_id FROM image_generations WHERE id = :id"), {"id": image_gen_id}
    ).mappings().first()
    task_id = task_row["task_id"] if task_row else None

    try:
        db.execute(
            _text("UPDATE image_generations SET status = :s WHERE id = :id"),
            {"s": "processing", "id": image_gen_id},
        )
        result = call_image_api(db, log_, {
            "prompt": opts.get("prompt"),
            "model": opts.get("model"),
            "size": opts.get("size"),
            "quality": opts.get("quality"),
            "drama_id": drama_id,
            "character_id": character_id,
            "image_type": opts.get("image_type"),
            "image_gen_id": image_gen_id,
            "user_negative_prompt": opts.get("user_negative_prompt"),
        })
        now2 = timestamp()
        if result.get("error"):
            db.execute(
                _text("UPDATE image_generations SET status = :s, error_msg = :e, updated_at = :u WHERE id = :id"),
                {"s": "failed", "e": result["error"], "u": now2, "id": image_gen_id},
            )
            if task_id:
                taskService.update_task_error(db, task_id, result["error"])
            if char_id_num is not None:
                db.execute(
                    _text("UPDATE characters SET error_msg = :e, updated_at = :u WHERE id = :id"),
                    {"e": result["error"], "u": now2, "id": char_id_num},
                )
            if scene_id_num is not None:
                db.execute(
                    _text("UPDATE scenes SET error_msg = :e, updated_at = :u WHERE id = :id"),
                    {"e": result["error"], "u": now2, "id": scene_id_num},
                )
            return

        # 落盘
        local_path = None
        try:
            cfg = cfg or {}
            raw_storage = (cfg.get("storage") or {}).get("local_path") or "./data/storage"
            storage_path = raw_storage if os.path.isabs(raw_storage) else os.path.join(os.getcwd(), raw_storage)
            category = "scenes" if scene_id_num is not None else ("characters" if char_id_num is not None else "images")
            project_subdir = storageLayout.get_project_storage_subdir(db, drama_id_num)
            local_path = uploadService.download_image_to_local(
                storage_path, result["image_url"], category, log_, "ig", project_subdir
            )
        except Exception:  # noqa: BLE001
            local_path = None

        try:
            db.execute(
                _text(
                    "UPDATE image_generations SET status = :s, image_url = :u, local_path = :lp, "
                    "completed_at = :c, updated_at = :c WHERE id = :id"
                ),
                {"s": "completed", "u": result["image_url"], "lp": local_path, "c": now2, "id": image_gen_id},
            )
        except Exception as e:  # noqa: BLE001
            if "completed_at" in str(e):
                db.execute(
                    _text(
                        "UPDATE image_generations SET status = :s, image_url = :u, local_path = :lp, "
                        "updated_at = :c WHERE id = :id"
                    ),
                    {"s": "completed", "u": result["image_url"], "lp": local_path, "c": now2, "id": image_gen_id},
                )
            else:
                raise

        if task_id:
            taskService.update_task_result(db, task_id, {
                "image_generation_id": image_gen_id,
                "image_url": result["image_url"],
                "local_path": local_path,
                "status": "completed",
            })

        if char_id_num is not None:
            old_char = db.execute(
                _text("SELECT local_path, image_url, extra_images, seedance2_asset FROM characters WHERE id = :id"),
                {"id": char_id_num},
            ).mappings().first()
            old_path = (old_char or {}).get("local_path") or (old_char or {}).get("image_url") or ""
            extras: list = []
            try:
                parsed = json.loads((old_char or {}).get("extra_images") or "[]")
                extras = parsed if isinstance(parsed, list) else []
            except Exception:  # noqa: BLE001
                extras = []
            if old_path and old_path not in extras:
                extras.append(old_path)
            extra_json = json.dumps(extras, ensure_ascii=False) if extras else None
            if old_char:
                seedance2AssetGuards.mark_stale_on_character_main_image_drift(
                    db, log_, {**old_char, "id": char_id_num},
                    {"image_url": result["image_url"], "local_path": local_path},
                )
            try:
                db.execute(
                    _text(
                        "UPDATE characters SET image_url = :u, local_path = :lp, extra_images = :ex, "
                        "updated_at = :c WHERE id = :id"
                    ),
                    {"u": result["image_url"], "lp": local_path, "ex": extra_json, "c": now2, "id": char_id_num},
                )
            except Exception as e:  # noqa: BLE001
                if "local_path" in str(e) or "extra_images" in str(e):
                    db.execute(
                        _text("UPDATE characters SET image_url = :u, updated_at = :c WHERE id = :id"),
                        {"u": result["image_url"], "c": now2, "id": char_id_num},
                    )
                else:
                    raise

        if scene_id_num is not None:
            old_scene = db.execute(
                _text("SELECT local_path, image_url, extra_images FROM scenes WHERE id = :id"),
                {"id": scene_id_num},
            ).mappings().first()
            old_path = (old_scene or {}).get("local_path") or (old_scene or {}).get("image_url") or ""
            extras = []
            try:
                parsed = json.loads((old_scene or {}).get("extra_images") or "[]")
                extras = parsed if isinstance(parsed, list) else []
            except Exception:  # noqa: BLE001
                extras = []
            if old_path and old_path not in extras:
                extras.append(old_path)
            extra_json = json.dumps(extras, ensure_ascii=False) if extras else None
            try:
                db.execute(
                    _text(
                        "UPDATE scenes SET image_url = :u, local_path = :lp, extra_images = :ex, "
                        "updated_at = :c WHERE id = :id"
                    ),
                    {"u": result["image_url"], "lp": local_path, "ex": extra_json, "c": now2, "id": scene_id_num},
                )
            except Exception as e:  # noqa: BLE001
                if "local_path" in str(e) or "extra_images" in str(e):
                    db.execute(
                        _text("UPDATE scenes SET image_url = :u, updated_at = :c WHERE id = :id"),
                        {"u": result["image_url"], "c": now2, "id": scene_id_num},
                    )
                else:
                    raise
    except Exception as err:  # noqa: BLE001
        now2 = timestamp()
        err_msg = str(err)[:500] or "Unknown error"
        try:
            db.execute(
                _text("UPDATE image_generations SET status = :s, error_msg = :e, updated_at = :u WHERE id = :id"),
                {"s": "failed", "e": err_msg, "u": now2, "id": image_gen_id},
            )
        except Exception:  # noqa: BLE001
            pass
        if task_id:
            try:
                taskService.update_task_error(db, task_id, err_msg)
            except Exception:  # noqa: BLE001
                pass
