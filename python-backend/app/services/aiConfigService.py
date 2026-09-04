"""AI 配置 CRUD — 契约翻译 backend-node/src/services/aiConfigService.js。

对齐要点：
- 表 ai_service_configs，软删除（deleted_at）
- model 列为 JSON 字符串，读出时还原为数组
- 每种 service_type 只保留一个 is_default
- testConnection 按 provider / service_type 分支发最小探针请求
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one
from app.services.deepseekConfig import apply_deepseek_connectivity_options
from app.services.jimengMaterialHubService import normalize_material_hub_token

_TIMEOUT = 30.0
MASKED_SECRET_VALUE = "********"

# ensureSingleDefaultPerType 覆盖的服务类型
SERVICE_TYPES = (
    "text",
    "image",
    "storyboard_image",
    "video",
    "tts",
    "jimeng2_character_auth",
    "model_ark_asset",
)


# ---------------- 工具函数 ----------------


def _now() -> str:
    """等价 new Date().toISOString()。"""
    return timestamp()


def normalize_api_key_for_service(service_type: Any, api_key: Any) -> Any:
    if service_type == "jimeng2_character_auth" and api_key is not None:
        return normalize_material_hub_token(api_key)
    return api_key


def model_to_db(model: Any) -> str | None:
    if model is None:
        return None
    if isinstance(model, (list, tuple, set)):
        return json.dumps([str(v).strip() for v in model if str(v).strip()], ensure_ascii=False)
    if isinstance(model, str):
        parts = [p.strip() for p in model.split(",") if p.strip()]
        return json.dumps(parts, ensure_ascii=False)
    return json.dumps([], ensure_ascii=False)


def model_from_db(val: Any) -> list:
    if val is None or val == "":
        return []
    if isinstance(val, list):
        return [str(v) for v in val if str(v).strip()]
    if isinstance(val, tuple):
        return [str(v) for v in val if str(v).strip()]
    try:
        arr = json.loads(val)
    except Exception:
        return [str(val)]
    if isinstance(arr, list):
        return [str(v) for v in arr if str(v).strip()]
    return [str(arr)]


def row_to_config(r: dict) -> dict:
    cfg = {
        "id": r.get("id"),
        "service_type": r.get("service_type"),
        "provider": r.get("provider"),
        "api_protocol": r.get("api_protocol") or "",
        "name": r.get("name"),
        "base_url": r.get("base_url"),
        "api_key": r.get("api_key"),
        "model": model_from_db(r.get("model")),
        "default_model": str(r["default_model"]).strip() if r.get("default_model") else None,
        "endpoint": r.get("endpoint"),
        "query_endpoint": r.get("query_endpoint"),
        "priority": r.get("priority") if r.get("priority") is not None else 0,
        "is_default": bool(r.get("is_default")),
        "is_active": True if r.get("is_active") is None else bool(r.get("is_active")),
        "settings": r.get("settings"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }
    # TTS 配置：从 settings JSON 展开 voice_id / group_id 供 ttsService 直接读取
    if r.get("service_type") == "tts" and r.get("settings"):
        try:
            s = json.loads(r["settings"])
            if isinstance(s, dict):
                if s.get("voice_id"):
                    cfg["voice_id"] = s["voice_id"]
                if s.get("group_id"):
                    cfg["group_id"] = s["group_id"]
        except Exception:
            pass
    return cfg


def mask_config_secret(cfg: dict | None) -> dict | None:
    if cfg is None:
        return None
    out = dict(cfg)
    has_api_key = bool(str(out.get("api_key") or "").strip())
    out["has_api_key"] = has_api_key
    out["api_key_masked"] = MASKED_SECRET_VALUE if has_api_key else ""
    out["api_key"] = MASKED_SECRET_VALUE if has_api_key else ""
    return out


def mask_config_secrets(configs: list[dict]) -> list[dict]:
    return [mask_config_secret(c) for c in configs]


# ---------------- 默认配置互斥 ----------------


def ensure_single_default_per_type(db: Session) -> None:
    """每种服务类型只保留一个默认：保留优先级最高（同优先级取 id 最小）的那条。"""
    for st in SERVICE_TYPES:
        rows = fetch_all(
            db,
            "SELECT id, priority FROM ai_service_configs "
            "WHERE deleted_at IS NULL AND service_type = :st AND is_default = 1 "
            "ORDER BY priority DESC, id ASC",
            {"st": st},
        )
        if len(rows) <= 1:
            continue
        keep_id = rows[0]["id"]
        execute(
            db,
            "UPDATE ai_service_configs SET is_default = 0 "
            "WHERE deleted_at IS NULL AND service_type = :st AND id != :keep_id",
            {"st": st, "keep_id": keep_id},
        )


def clear_other_default(db: Session, service_type: Any, except_id: Any) -> None:
    execute(
        db,
        "UPDATE ai_service_configs SET is_default = 0 "
        "WHERE deleted_at IS NULL AND service_type = :st AND id != :except_id",
        {"st": service_type, "except_id": except_id},
    )


# ---------------- CRUD ----------------


def list_configs(db: Session, service_type: str | None = None) -> list[dict]:
    ensure_single_default_per_type(db)
    order = "ORDER BY is_default DESC, priority DESC, created_at DESC"
    if service_type:
        sql = (
            "SELECT * FROM ai_service_configs WHERE deleted_at IS NULL AND service_type = :service_type " + order
        )
        rows = fetch_all(db, sql, {"service_type": service_type})
    else:
        sql = "SELECT * FROM ai_service_configs WHERE deleted_at IS NULL " + order
        rows = fetch_all(db, sql)
    return [row_to_config(r) for r in rows]


def get_config(db: Session, config_id: Any) -> dict | None:
    row = fetch_one(
        db,
        "SELECT * FROM ai_service_configs WHERE id = :id AND deleted_at IS NULL",
        {"id": config_id},
    )
    return row_to_config(row) if row else None


def _infer_endpoints(provider_raw: Any, service_type_raw: Any) -> tuple[str, str]:
    """按 provider + service_type 推断 endpoint / query_endpoint（无 endpoint 时使用）。"""
    endpoint = ""
    query_endpoint = ""
    p = str(provider_raw or "").lower()
    st = str(service_type_raw or "text").lower()

    if p == "openai":
        if st == "text":
            endpoint = "/chat/completions"
        elif st == "image":
            endpoint = "/images/generations"
        elif st == "video":
            endpoint = "/videos"
            query_endpoint = "/videos/{taskId}"
    elif p in ("gemini", "google"):
        endpoint = "/v1beta/models/{model}:generateContent"
    elif p in ("dashscope", "qwen_image"):
        if st in ("image", "storyboard_image"):
            endpoint = "/api/v1/services/aigc/multimodal-generation/generation"
        elif st == "video" and p == "dashscope":
            endpoint = "/api/v1/services/aigc/image2video/video-synthesis"
            query_endpoint = "/api/v1/tasks/{taskId}"
    elif p in ("volces", "volcengine", "volc"):
        if st == "video":
            endpoint = "/contents/generations/tasks"
            query_endpoint = "/contents/generations/tasks/{taskId}"
        elif st in ("image", "storyboard_image"):
            endpoint = "/images/generations"
    elif p == "nano_banana":
        if st in ("image", "storyboard_image"):
            endpoint = "/api/v1/nanobanana/generate-2"
            query_endpoint = "/api/v1/nanobanana/record-info"
    elif p == "agnes":
        if st == "text":
            endpoint = "/chat/completions"
        elif st in ("image", "storyboard_image"):
            endpoint = "/images/generations"
        elif st == "video":
            endpoint = "/videos"
            query_endpoint = "/videos/{taskId}"

    return endpoint, query_endpoint


def create_config(db: Session, log, req: dict) -> dict:
    now = _now()
    model = model_to_db(req.get("model"))

    endpoint = req.get("endpoint") or ""
    query_endpoint = req.get("query_endpoint") or ""
    if not endpoint and req.get("provider"):
        endpoint, query_endpoint = _infer_endpoints(req.get("provider"), req.get("service_type"))

    default_model = str(req["default_model"]).strip() or None if req.get("default_model") is not None else None
    service_type = req.get("service_type") or "text"

    res = execute(
        db,
        "INSERT INTO ai_service_configs "
        "(service_type, provider, api_protocol, name, base_url, api_key, model, default_model, "
        " endpoint, query_endpoint, priority, is_default, is_active, settings, created_at, updated_at) "
        "VALUES (:service_type, :provider, :api_protocol, :name, :base_url, :api_key, :model, :default_model, "
        "        :endpoint, :query_endpoint, :priority, :is_default, 1, :settings, :created_at, :updated_at)",
        {
            "service_type": service_type,
            "provider": req.get("provider") or "",
            "api_protocol": req.get("api_protocol") or "",
            "name": req.get("name") or "",
            "base_url": req.get("base_url") or "",
            "api_key": normalize_api_key_for_service(service_type, req.get("api_key") or ""),
            "model": model,
            "default_model": default_model,
            "endpoint": endpoint,
            "query_endpoint": query_endpoint,
            "priority": req.get("priority") if req.get("priority") is not None else 0,
            "is_default": 1 if req.get("is_default") else 0,
            "settings": req.get("settings") or None,
            "created_at": now,
            "updated_at": now,
        },
    )
    new_id = res.lastrowid
    log.info("AI config created", extra={"config_id": new_id, "provider": req.get("provider")})
    if req.get("is_default"):
        clear_other_default(db, service_type, new_id)
    return get_config(db, new_id)


def update_config(db: Session, log, config_id: Any, req: dict) -> dict | None:
    existing = get_config(db, config_id)
    if not existing:
        return None
    if req.get("api_key") == MASKED_SECRET_VALUE:
        req = dict(req)
        req.pop("api_key", None)

    updates: list[str] = []
    params: dict[str, Any] = {}

    if req.get("name") is not None:
        updates.append("name = :name")
        params["name"] = req["name"]
    if req.get("provider") is not None:
        updates.append("provider = :provider")
        params["provider"] = req["provider"]
    if req.get("api_protocol") is not None:
        updates.append("api_protocol = :api_protocol")
        params["api_protocol"] = req["api_protocol"]
    if req.get("base_url") is not None:
        updates.append("base_url = :base_url")
        params["base_url"] = req["base_url"]
    if req.get("api_key") is not None:
        updates.append("api_key = :api_key")
        st = req["service_type"] if req.get("service_type") is not None else existing["service_type"]
        params["api_key"] = normalize_api_key_for_service(st, req["api_key"])
    if req.get("model") is not None:
        updates.append("model = :model")
        params["model"] = model_to_db(req["model"])
    if "default_model" in req:
        updates.append("default_model = :default_model")
        params["default_model"] = (
            str(req["default_model"]).strip() or None if req.get("default_model") is not None else None
        )
    if req.get("priority") is not None:
        updates.append("priority = :priority")
        params["priority"] = req["priority"]
    if "endpoint" in req:
        updates.append("endpoint = :endpoint")
        params["endpoint"] = req.get("endpoint") or ""
    if "query_endpoint" in req:
        updates.append("query_endpoint = :query_endpoint")
        params["query_endpoint"] = req.get("query_endpoint") or ""
    if req.get("settings") is not None:
        updates.append("settings = :settings")
        params["settings"] = req["settings"]
    if isinstance(req.get("is_default"), bool):
        updates.append("is_default = :is_default")
        params["is_default"] = 1 if req["is_default"] else 0
    if isinstance(req.get("is_active"), bool):
        updates.append("is_active = :is_active")
        params["is_active"] = 1 if req["is_active"] else 0

    if not updates:
        return existing

    params["updated_at"] = _now()
    params["id"] = config_id
    execute(
        db,
        "UPDATE ai_service_configs SET " + ", ".join(updates) + ", updated_at = :updated_at WHERE id = :id",
        params,
    )
    if req.get("is_default") is True:
        clear_other_default(db, existing["service_type"], config_id)
    log.info("AI config updated", extra={"config_id": config_id})
    return get_config(db, config_id)


def delete_config(db: Session, log, config_id: Any) -> bool:
    res = execute(
        db,
        "UPDATE ai_service_configs SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL",
        {"now": _now(), "id": config_id},
    )
    if res.rowcount == 0:
        return False
    log.info("AI config deleted", extra={"config_id": config_id})
    return True


# ---------------- 厂商锁定 ----------------


def get_vendor_lock_status(cfg: dict | None) -> dict:
    lock = (cfg or {}).get("vendor_lock") or {}
    return {
        "enabled": bool(lock.get("enabled")),
        "config_file": lock.get("config_file") or "",
    }


def apply_vendor_lock(db: Session, log, cfg: dict) -> None:
    """启动时同步 vendor_lock 指定的配置文件到数据库（软删全部后按文件重新导入）。"""
    import os

    status = get_vendor_lock_status(cfg)
    if not status["enabled"]:
        return

    config_file = status["config_file"]
    if not config_file:
        log.warning("vendor_lock enabled but config_file is empty")
        return

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(os.getcwd(), "configs", config_file),
        os.path.join(here, "..", "configs", config_file),
    ]
    raw = None
    for p in candidates:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = f.read()
            break
    if raw is None:
        log.warning("[vendor_lock] config file not found: %s", config_file)
        return

    try:
        configs = json.loads(raw)
        if not isinstance(configs, list):
            raise ValueError("config file must be a JSON array")
    except Exception as e:
        log.error("[vendor_lock] failed to parse config file: %s", e)
        return

    existing = fetch_all(
        db, "SELECT service_type, provider, api_key FROM ai_service_configs WHERE deleted_at IS NULL"
    )
    saved_keys = {f"{r['service_type']}:{r['provider']}": r["api_key"] for r in existing}

    now = _now()
    execute(db, "UPDATE ai_service_configs SET deleted_at = :now WHERE deleted_at IS NULL", {"now": now})

    for item in configs:
        map_key = f"{item.get('service_type')}:{item.get('provider')}"
        api_key = saved_keys.get(map_key, item.get("api_key") or "")
        m = item.get("model")
        if isinstance(m, list):
            model = json.dumps(m, ensure_ascii=False)
        elif m:
            model = json.dumps([m], ensure_ascii=False)
        else:
            model = "[]"
        execute(
            db,
            "INSERT INTO ai_service_configs "
            "(service_type, provider, api_protocol, name, base_url, api_key, model, default_model, "
            " endpoint, query_endpoint, priority, is_default, is_active, settings, created_at, updated_at) "
            "VALUES (:service_type, :provider, :api_protocol, :name, :base_url, :api_key, :model, :default_model, "
            "        :endpoint, :query_endpoint, :priority, :is_default, 1, :settings, :created_at, :updated_at)",
            {
                "service_type": item.get("service_type") or "text",
                "provider": item.get("provider") or "",
                "api_protocol": item.get("api_protocol") or "",
                "name": item.get("name") or "",
                "base_url": item.get("base_url") or "",
                "api_key": api_key,
                "model": model,
                "default_model": item.get("default_model") or None,
                "endpoint": item.get("endpoint") or "",
                "query_endpoint": item.get("query_endpoint") or "",
                "priority": item.get("priority") if item.get("priority") is not None else 0,
                "is_default": 1 if item.get("is_default") else 0,
                "settings": item.get("settings") or None,
                "created_at": now,
                "updated_at": now,
            },
        )
    log.info("[vendor_lock] synced %s configs from %s", len(configs), config_file)


def bulk_update_api_key(db: Session, log, new_key: str) -> int:
    res = execute(
        db,
        "UPDATE ai_service_configs SET api_key = :key, updated_at = :now WHERE deleted_at IS NULL",
        {"key": new_key, "now": _now()},
    )
    log.info("Bulk update api_key", extra={"updated": res.rowcount})
    return res.rowcount


# ---------------- 连接测试 ----------------


def _auth_error_message(res: httpx.Response, fallback: str) -> str:
    """401/403 时按 Node 的取值顺序提取上游错误信息。

    Node 各分支的取值顺序并集：
    base_resp.status_msg（MiniMax T2A）→ error.message → msg（NanoBanana）→ message
    """
    text = res.text or ""
    err_msg = fallback
    try:
        j = json.loads(text) if text else None
    except Exception:
        j = None
    if not isinstance(j, dict):
        return err_msg

    candidates: list[Any] = []
    base_resp = j.get("base_resp")
    if isinstance(base_resp, dict):
        candidates.append(base_resp.get("status_msg"))
    err = j.get("error")
    if isinstance(err, dict):
        candidates.append(err.get("message"))
    elif err is not None:
        candidates.append(err)
    candidates.append(j.get("msg"))
    candidates.append(j.get("message"))

    for c in candidates:
        if c:
            return str(c)
    return err_msg


def test_connection(opts: dict, log=None) -> None:
    """按 provider / service_type 发最小请求验证 base_url + api_key。失败抛异常。"""
    base = re.sub(r"/$", "", str(opts.get("base_url") or ""))
    if not base:
        raise ValueError("base_url 必填")
    if not opts.get("api_key"):
        raise ValueError("api_key 必填")

    model_raw = opts.get("model")
    if isinstance(model_raw, list):
        models = model_raw
    elif model_raw is not None:
        models = [model_raw]
    else:
        models = []
    model = models[0] if models else ""
    if not isinstance(model, str):
        model = str(model) if model is not None else ""

    provider = str(opts.get("provider") or "openai").lower()
    service_type = str(opts.get("service_type") or "").lower()
    endpoint = opts.get("endpoint") or ""

    if not model and provider in ("gemini", "google"):
        raise ValueError("model 必填")

    api_key = opts.get("api_key") or ""

    # --- NanoBanana ---
    if provider == "nano_banana":
        # 用 record-info 查询一个不存在的 taskId：401/403=key 无效，404=key 有效已联通
        url = base + "/api/v1/nanobanana/record-info?taskId=test-connectivity"
        res = httpx.get(url, headers={"Authorization": "Bearer " + str(api_key)}, timeout=_TIMEOUT)
        if res.status_code in (401, 403):
            raise ValueError(_auth_error_message(res, f"API Key 无效 ({res.status_code})"))
        return

    # --- Gemini ---
    if provider in ("gemini", "google"):
        endpoint = endpoint or "/v1beta/models/{model}:generateContent"
        path = endpoint.replace("{model}", model or "gemini-pro")
        url = base + (path if path.startswith("/") else "/" + path) + "?key=" + _pct(api_key)
        res = httpx.post(
            url,
            headers={"Content-Type": "application/json"},
            content=json.dumps({"contents": [{"parts": [{"text": "Hello"}]}]}),
            timeout=_TIMEOUT,
        )
        if not (200 <= res.status_code < 300):
            raise ValueError(f"请求失败: {res.status_code} {(res.text or '')[:200]}")
        try:
            data = json.loads(res.text) if res.text else {}
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("candidates") is None and data.get("error") is not None:
            err = data["error"]
            raise ValueError((err.get("message") if isinstance(err, dict) else None) or err or "Gemini 返回错误")
        return

    # --- TTS 语音合成 ---
    if service_type == "tts":
        probe_url = base + "/text_to_speech"
        res = httpx.post(
            probe_url,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + str(api_key)},
            content=json.dumps({"model": model or "speech-02-hd", "text": "hi", "stream": False}),
            timeout=_TIMEOUT,
        )
        if res.status_code in (401, 403):
            raise ValueError(_auth_error_message(res, f"API Key 无效 ({res.status_code})"))
        # 其他状态（400 缺参数、404 端点不对等）说明网络通、key 疑似有效
        return

    is_image_service = service_type in ("image", "storyboard_image")
    is_video_service = service_type == "video"
    has_image_endpoint = bool(endpoint and "/images/" in endpoint)

    is_dashscope = provider in ("dashscope", "qwen_image")
    is_volcengine = provider in ("volces", "volcengine", "volc")
    model_lower = model.lower()

    looks_like_image_model = bool(
        re.search(
            r"seedream|image2video|text2image|img2img|wanx|wan\d|flux|stable.?diff|dall.?e|imagen|agnes-image|-image$",
            model_lower,
            re.IGNORECASE,
        )
    ) or (is_volcengine and bool(re.search(r"seedream|vision|image", model_lower, re.IGNORECASE)))
    looks_like_video_model = bool(
        re.search(r"seedance|video.?gen|video2video|kf2v|cogvideo|sora|kling|agnes-video", model_lower, re.IGNORECASE)
    )
    is_dashscope_non_chat_endpoint = is_dashscope and bool(
        endpoint and ("aigc" in endpoint or "multimodal" in endpoint or "video" in endpoint)
    )

    treat_as_image = (
        is_image_service
        or has_image_endpoint
        or is_dashscope_non_chat_endpoint
        or looks_like_image_model
        or (is_volcengine and not service_type and not endpoint)
    )

    # --- DashScope 图片 / 视频 / 分镜：用 compatible-mode chat 验证 key ---
    if is_dashscope and (
        is_image_service
        or is_video_service
        or looks_like_image_model
        or looks_like_video_model
        or is_dashscope_non_chat_endpoint
    ):
        chat_url = re.sub(r"/(api/v1|compatible-mode)/.*$", "", base) + "/compatible-mode/v1/chat/completions"
        res = httpx.post(
            chat_url,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + str(api_key)},
            content=json.dumps(
                {"model": "qwen-turbo", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
            ),
            timeout=_TIMEOUT,
        )
        if log is not None:
            log.info(
                "[testConnection] DashScope 非文本服务，用 compatible chat 验证 key",
                extra={"chatUrl": chat_url, "serviceType": service_type, "model": model},
            )
        if res.status_code in (401, 403):
            raise ValueError(_auth_error_message(res, f"API Key 无效 ({res.status_code})"))
        return

    # --- 视频生成服务（非 DashScope）：通过 chat/completions 验证 key 合法性 ---
    if is_video_service or looks_like_video_model:
        url = base + "/chat/completions"
        res = httpx.post(
            url,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + str(api_key)},
            content=json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}),
            timeout=_TIMEOUT,
        )
        if log is not None:
            log.info(
                "[testConnection] 视频服务，用 chat/completions 验证 key",
                extra={"url": url, "serviceType": service_type, "model": model},
            )
        if res.status_code in (401, 403):
            raise ValueError(_auth_error_message(res, f"API Key 无效 ({res.status_code})"))
        return

    # --- OpenAI 兼容图片生成 ---
    if treat_as_image:
        endpoint = endpoint or "/images/generations"
        path = endpoint if endpoint.startswith("/") else "/" + endpoint
        url = base + path
        res = httpx.post(
            url,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + str(api_key)},
            content=json.dumps({"model": model, "prompt": "test connectivity", "n": 1}),
            timeout=_TIMEOUT,
        )
        if log is not None:
            log.info(
                "[testConnection] 图片服务",
                extra={"url": url, "serviceType": service_type, "model": model},
            )
        if res.status_code in (401, 403):
            raise ValueError(_auth_error_message(res, f"API Key 无效 ({res.status_code})"))
        if not (200 <= res.status_code < 300):
            text = res.text or ""
            parsed = None
            try:
                parsed = json.loads(text) if text else None
            except Exception:
                parsed = None
            err = parsed.get("error") if isinstance(parsed, dict) else None
            msg = ""
            if isinstance(err, dict) and err.get("message"):
                msg = str(err["message"])
            elif isinstance(parsed, dict) and parsed.get("message"):
                msg = str(parsed["message"])
            lmsg = msg.lower()
            is_auth_err = any(
                k in lmsg for k in ("unauthorized", "invalid api key", "authentication", "forbidden")
            )
            if is_auth_err:
                raise ValueError(f"API Key 无效: {msg or res.status_code}")
            # 其他错误说明网络通、key 有效
            return
        return

    # --- OpenAI / 默认：chat completions ---
    endpoint = endpoint or "/chat/completions"
    path = endpoint if endpoint.startswith("/") else "/" + endpoint
    url = base + path
    body = {
        "model": model or "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 5,
    }
    body = apply_deepseek_connectivity_options(
        {"provider": provider, "base_url": base, "settings": opts.get("settings")},
        body,
    )
    if log is not None:
        log.info(
            "[testConnection] 文本/chat 服务",
            extra={"url": url, "serviceType": service_type, "model": model},
        )
    res = httpx.post(
        url,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + str(api_key)},
        content=json.dumps(body),
        timeout=_TIMEOUT,
    )
    if not (200 <= res.status_code < 300):
        text = res.text or ""
        err_msg = f"请求失败: {res.status_code}"
        try:
            j = json.loads(text) if text else None
        except Exception:
            j = None
        if isinstance(j, dict):
            err = j.get("error")
            detail = err.get("message") if isinstance(err, dict) else err
            err_msg += " - " + str(detail or j.get("message") or text[:150])
        elif text:
            err_msg += " - " + text[:150]
        raise ValueError(err_msg)

    try:
        data = json.loads(res.text) if res.text else {}
    except Exception:
        data = {}
    if isinstance(data, dict) and data.get("choices") is None and data.get("error") is not None:
        err = data["error"]
        raise ValueError((err.get("message") if isinstance(err, dict) else None) or err or "接口返回错误")


def _pct(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")
