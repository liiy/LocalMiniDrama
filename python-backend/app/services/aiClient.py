"""AI 文本/视觉客户端 — 契约翻译 backend-node/src/services/aiClient.js。

覆盖：
- post_json_non_stream / post_json_with_timeout / post_json_stream（SSE 增量累积）
- get_default_config / get_config_for_model / get_config_from_model_map
- build_chat_url / get_model_from_config
- generate_text / stream_generate_text / generate_text_with_vision
- resolve_entity_image_source / extract_description_from_image / is_refusal_response

与 Node 的差异仅在传输层：Node 用 http/https 模块手搓 SSE，Python 用 httpx 的流式读取。
超时语义保持一致——post_json_stream 的 silence_ms 对应 httpx 的 read timeout（每次读取
独立计时，等价于 Node"每收到数据就重置静默计时器"）。

敏感区（R1-R8：真实外部 AI 调用）不在此 mock；本模块是真实实现，测试时通过注入 base_url 打桩。
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Callable

import httpx

from app.core.logger import get_logger
from app.services import aiConfigService
from app.services.deepseekConfig import apply_deepseek_chat_options

log = get_logger("lmd.aiClient")

# 视觉请求默认超时（毫秒）
VISION_TIMEOUT_MS = 120_000
# 图生等长耗时 JSON POST 默认超时（毫秒）
POST_JSON_TIMEOUT_MS = 600_000
# 流式默认静默超时（毫秒）
STREAM_SILENCE_MS = 60_000
# stream_generate_text 默认静默超时（毫秒）
STREAM_GEN_SILENCE_MS = 120_000

_REFUSAL_PATTERNS = [
    re.compile(r"无法识别.*人物"),
    re.compile(r"无法.*识别.*特征"),
    re.compile(r"无法.*分析.*人物"),
    re.compile(r"无法.*描述.*人物"),
    re.compile(r"抱歉.*无法.*识别"),
    re.compile(r"cannot identify", re.IGNORECASE),
    re.compile(r"can't identify", re.IGNORECASE),
    re.compile(r"unable to identify", re.IGNORECASE),
]

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


# ---------------- 传输层 ----------------


def post_json_non_stream(
    url: str, headers: dict, body: Any, timeout_ms: int = VISION_TIMEOUT_MS
) -> dict:
    """等价 postJSONNonStream：完整响应后返回 { status, body, raw }。

    body 取 choices[0].message.content，兼容推理模型的 reasoning_content。
    """
    body_str = json.dumps(body, ensure_ascii=False)
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    try:
        resp = httpx.post(
            url, content=body_str.encode("utf-8"), headers=req_headers,
            timeout=timeout_ms / 1000.0,
        )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Vision request timeout after {timeout_ms}ms") from exc

    raw = resp.text
    if resp.status_code < 200 or resp.status_code >= 300:
        raise RuntimeError(f"HTTP {resp.status_code}: {raw[:500]}")

    content = None
    try:
        parsed = json.loads(raw)
        choices = parsed.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or msg.get("reasoning_content") or None
    except Exception:
        content = None
    return {"status": resp.status_code, "body": content, "raw": raw}


def post_json_with_timeout(
    url: str, headers: dict, body: Any, timeout_ms: int = POST_JSON_TIMEOUT_MS
) -> dict:
    """等价 postJSONWithTimeout：返回 { statusCode, raw }（不做 JSON 解析）。"""
    body_str = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    try:
        resp = httpx.post(
            url, content=body_str.encode("utf-8"), headers=req_headers,
            timeout=timeout_ms / 1000.0,
        )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Image generation HTTP timeout after {timeout_ms}ms") from exc
    return {"statusCode": resp.status_code or 0, "raw": resp.text}


def post_json_stream(
    url: str,
    headers: dict,
    body: Any,
    silence_timeout_ms: int = STREAM_SILENCE_MS,
    on_progress: Callable[[int, str | None, str], None] | None = None,
) -> dict:
    """等价 postJSONStream：强制 stream=true，按 SSE 行解析 delta 并累积。

    on_progress 签名与 Node 一致：(received_len, event, accumulated)，
    首个 token 时以 (0, 'first_token', '') 回调一次。
    """
    stream_body = {**(body or {}), "stream": True}
    body_str = json.dumps(stream_body, ensure_ascii=False)
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    timeout = httpx.Timeout(
        connect=30.0, read=silence_timeout_ms / 1000.0, write=30.0, pool=30.0
    )

    accumulated = ""
    sse_buffer = ""
    first_token = True
    status_code = 0

    try:
        with httpx.stream(
            "POST", url, content=body_str.encode("utf-8"), headers=req_headers, timeout=timeout
        ) as resp:
            status_code = resp.status_code
            if status_code < 200 or status_code >= 300:
                err_raw = b"".join(resp.iter_bytes()).decode("utf-8", "ignore")
                raise RuntimeError(f"HTTP {status_code}: {err_raw[:500]}")

            for chunk in resp.iter_text():
                sse_buffer += chunk
                lines = sse_buffer.split("\n")
                sse_buffer = lines.pop()  # 保留不完整的最后一行
                for line in lines:
                    trimmed = line.strip()
                    if not trimmed.startswith("data:"):
                        continue
                    data = trimmed[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        evt = json.loads(data)
                    except Exception:
                        continue
                    choices = evt.get("choices") or []
                    delta = (choices[0].get("delta") or {}).get("content") if choices else None
                    if not delta:
                        continue
                    if first_token:
                        first_token = False
                        if on_progress:
                            on_progress(0, "first_token", "")
                    accumulated += delta
                    if on_progress:
                        on_progress(len(accumulated), None, accumulated)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"AI stream silence timeout after {silence_timeout_ms}ms") from exc

    return {"status": status_code, "body": accumulated}


# ---------------- 配置查找 ----------------


def get_default_config(db, service_type: str) -> dict | None:
    """等价 getDefaultConfig：list_configs 已按 is_default DESC, priority DESC 排序。"""
    configs = aiConfigService.list_configs(db, service_type)
    active = [c for c in configs if c.get("is_active")]
    if not active:
        return None
    default_one = next((c for c in active if c.get("is_default")), None)
    return default_one if default_one is not None else active[0]


def get_config_for_model(db, service_type: str, model_name: str) -> dict | None:
    """等价 getConfigForModel：按 model 列表匹配，只考虑启用配置。"""
    for config in aiConfigService.list_configs(db, service_type):
        if not config.get("is_active"):
            continue
        models = config.get("model") if isinstance(config.get("model"), list) else [config.get("model")]
        if model_name in models:
            return config
    return None


def build_chat_url(config: dict) -> str:
    base = re.sub(r"/$", "", config.get("base_url") or "")
    ep = config.get("endpoint") or "/chat/completions"
    if not ep.startswith("/"):
        ep = "/" + ep
    return base + ep


def get_model_from_config(config: dict, preferred_model: Any = None) -> str:
    raw_models = config.get("model")
    if isinstance(raw_models, list):
        models = raw_models
    elif raw_models is not None:
        models = [raw_models]
    else:
        models = []
    if preferred_model and preferred_model in models:
        return preferred_model
    if config.get("default_model") and config.get("default_model") in models:
        return config["default_model"]
    return models[0] if models else "gpt-3.5-turbo"


def get_config_from_model_map(db, scene_key: str) -> dict | None:
    """等价 getConfigFromModelMap：从 ai_model_map 查场景 → 配置路由。"""
    from app.db.session import fetch_one

    try:
        row = fetch_one(db, "SELECT * FROM ai_model_map WHERE `key` = :k", {"k": scene_key})
        if not row:
            return None
        configs = aiConfigService.list_configs(db, row.get("service_type") or "text")
        config = None
        if row.get("config_id"):
            config = next(
                (c for c in configs if c.get("id") == row.get("config_id") and c.get("is_active")),
                None,
            )
        if not config:
            config = (
                next((c for c in configs if c.get("is_active") and c.get("is_default")), None)
                or next((c for c in configs if c.get("is_active")), None)
                or None
            )
        return {"config": config, "modelOverride": row.get("model_override") or None} if config else None
    except Exception:
        return None


def _settings_max_tokens(config: dict) -> int | None:
    """解析 config.settings 里的 max_tokens 上限。"""
    try:
        raw = config.get("settings")
        if not raw:
            return None
        s = json.loads(raw) if isinstance(raw, str) else raw
        v = s.get("max_tokens") if isinstance(s, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return int(v)
    except Exception:
        pass
    return None


def _resolve_final_max_tokens(
    log, config: dict, options: dict, tag: str
) -> int | None:
    """等价 generateText/streamGenerateText 里的 max_tokens 三段式决策。"""
    settings_max = _settings_max_tokens(config)
    model = get_model_from_config(config)

    final = None
    if options.get("max_tokens") is not None:
        final = int(options["max_tokens"])
        if settings_max is not None and final > settings_max:
            log.warn(f"AI {tag}: max_tokens 超过配置上限，已截断", {
                "requested": final, "capped_to": settings_max, "model": model,
            })
            final = settings_max
    elif settings_max is not None:
        final = settings_max

    min_max = options.get("min_max_tokens")
    if min_max is not None:
        min_val = int(min_max)
        if final is None or final < min_val:
            if final is not None:
                log.warn(f"AI {tag}: max_tokens 低于任务最低需求，已提升", {
                    "was": final, "raised_to": min_val, "model": model,
                })
            final = min_val
    return final


# ---------------- 文本生成 ----------------


def _record_text_prompt_run(
    db,
    options: dict[str, Any],
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    status: str,
    raw_output: str | None = None,
    error: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """按需记录文本模型 Prompt Run。

    兼容式接入原则：只有调用方传入 prompt_key / skill_key / workflow_run_id
    或显式 record_prompt_run=True 时才落库，避免一次改造让所有旧流程产生大量新记录。
    """
    if not (
        options.get("record_prompt_run")
        or options.get("prompt_key")
        or options.get("skill_key")
        or options.get("workflow_run_id")
    ):
        return
    try:
        from app.prompts import registry_service as prompt_registry

        final_prompt = f"[system]\n{system_prompt or ''}\n\n[user]\n{user_prompt or ''}"
        prompt_registry.record_prompt_run(
            db,
            {
                "prompt_key": options.get("prompt_key") or options.get("scene_key") or "legacy.generate_text",
                "prompt_version": options.get("prompt_version") or 0,
                "skill_key": options.get("skill_key"),
                "agent_name": options.get("agent_name"),
                "workflow_run_id": options.get("workflow_run_id"),
                "workflow_step_id": options.get("workflow_step_id"),
                "model": model,
                "variables": options.get("prompt_variables") or {},
                "context_snapshot": options.get("context_snapshot") or {},
                "final_prompt": final_prompt,
                "raw_output": raw_output,
                "status": status,
                "error": error,
                "latency_ms": latency_ms,
            },
        )
    except Exception as record_err:  # noqa: BLE001
        # 追踪落库不能反向影响创作主链路；失败只写日志，后续由迁移/表结构排查。
        log.warning("Prompt run record skipped", extra={"error": str(record_err), "status": status})


def generate_text(db, log, service_type: str, user_prompt: str, system_prompt: str, options: dict | None = None) -> str:
    """等价 generateText：流式请求模型，返回拼接后的完整文本。"""
    options = options or {}
    preferred_model = options.get("model")
    temperature = options.get("temperature", 0.7)
    json_mode = options.get("json_mode", False)
    min_max_tokens = options.get("min_max_tokens")
    stream_callback = options.get("streamCallback")
    scene_key = options.get("scene_key")

    config = None
    routed_model_override = None
    if scene_key:
        mapped = get_config_from_model_map(db, scene_key)
        if mapped:
            config = mapped["config"]
            routed_model_override = mapped["modelOverride"]
            log.info("AI generateText: scene_key routing", {
                "scene_key": scene_key, "config_id": config.get("id"),
                "model_override": routed_model_override,
            })

    if not config:
        config = (
            get_config_for_model(db, service_type, preferred_model)
            if preferred_model
            else get_default_config(db, service_type)
        )
    if not config and preferred_model is None:
        config = get_default_config(db, "text")
    if not config:
        raise RuntimeError(f"未配置文本模型，请在「AI 配置」中添加 {service_type} 类型 且已启用的配置")

    model = get_model_from_config(config, routed_model_override or preferred_model)
    url = build_chat_url(config)
    final_max_tokens = _resolve_final_max_tokens(log, config, options, "generateText")

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            *([{"role": "system", "content": system_prompt}] if system_prompt else []),
            {"role": "user", "content": user_prompt},
        ],
        "temperature": float(temperature),
        **({"max_tokens": final_max_tokens} if final_max_tokens is not None else {}),
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
    }
    body = apply_deepseek_chat_options(config, body)

    log.info("AI generateText request", {
        "url": url[:60], "model": model,
        "max_tokens": final_max_tokens if final_max_tokens is not None else "(model default)",
        "json_mode": json_mode, "stream": True,
    })

    import time

    start_ms = time.time() * 1000

    def _on_progress(received_len: int, event: str | None, accumulated: str) -> None:
        if event == "first_token":
            log.info("AI stream first token", {"model": model, "ttft_ms": int(time.time() * 1000 - start_ms)})
        elif received_len > 0 and received_len % 500 < 20:
            log.info("AI stream progress", {
                "model": model, "received_chars": received_len,
                "elapsed_ms": int(time.time() * 1000 - start_ms),
            })
        if stream_callback and accumulated:
            stream_callback(accumulated)

    try:
        res = post_json_stream(
            url,
            {"Authorization": "Bearer " + (config.get("api_key") or "")},
            body,
            STREAM_SILENCE_MS,
            _on_progress,
        )
    except Exception as err:
        _record_text_prompt_run(
            db,
            options,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            status="failed",
            error=str(err),
            latency_ms=int(time.time() * 1000 - start_ms),
        )
        raise
    content = res["body"]
    if not content:
        _record_text_prompt_run(
            db,
            options,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            status="failed",
            error="AI 返回内容为空",
            latency_ms=int(time.time() * 1000 - start_ms),
        )
        raise RuntimeError("AI 返回内容为空")
    log.info("AI raw response received", {
        "model": model, "text_length": len(content),
        "elapsed_ms": int(time.time() * 1000 - start_ms), "text_preview": content[:200],
    })
    _record_text_prompt_run(
        db,
        options,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        status="completed",
        raw_output=content,
        latency_ms=int(time.time() * 1000 - start_ms),
    )
    return content


def stream_generate_text(
    db, log, service_type: str, user_prompt: str, system_prompt: str,
    options: dict | None = None, on_delta: Callable[[str], None] | None = None,
) -> str:
    """等价 streamGenerateText：把增量 delta 回调给调用方，返回完整拼接文本。"""
    options = options or {}
    preferred_model = options.get("model")
    temperature = options.get("temperature", 0.7)
    json_mode = options.get("json_mode", False)
    scene_key = options.get("scene_key")

    config = None
    routed_model_override = None
    if scene_key:
        mapped = get_config_from_model_map(db, scene_key)
        if mapped:
            config = mapped["config"]
            routed_model_override = mapped["modelOverride"]
            log.info("AI streamGenerateText: scene_key routing", {
                "scene_key": scene_key, "config_id": config.get("id"),
                "model_override": routed_model_override,
            })

    if not config:
        config = (
            get_config_for_model(db, service_type, preferred_model)
            if preferred_model
            else get_default_config(db, service_type)
        )
    if not config and preferred_model is None:
        config = get_default_config(db, "text")
    if not config:
        raise RuntimeError(f"未配置文本模型，请在「AI 配置」中添加 {service_type} 类型 且已启用的配置")

    model = get_model_from_config(config, routed_model_override or preferred_model)
    url = build_chat_url(config)
    final_max_tokens = _resolve_final_max_tokens(log, config, options, "streamGenerateText")

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            *([{"role": "system", "content": system_prompt}] if system_prompt else []),
            {"role": "user", "content": user_prompt},
        ],
        "temperature": float(temperature),
        **({"max_tokens": final_max_tokens} if final_max_tokens is not None else {}),
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
    }
    body = apply_deepseek_chat_options(config, body)

    silence_ms = int(options["silence_timeout_ms"]) if options.get("silence_timeout_ms") is not None else STREAM_GEN_SILENCE_MS
    log.info("AI streamGenerateText request", {
        "url": url[:60], "model": model,
        "max_tokens": final_max_tokens if final_max_tokens is not None else "(model default)",
        "json_mode": json_mode, "stream": True,
    })

    import time

    start_ms = time.time() * 1000
    state = {"last_len": 0}

    def _on_progress(received_len: int, event: str | None, accumulated: str) -> None:
        if event == "first_token":
            log.info("AI stream first token", {"model": model, "ttft_ms": int(time.time() * 1000 - start_ms)})
        if not accumulated or len(accumulated) <= state["last_len"]:
            return
        delta = accumulated[state["last_len"]:]
        state["last_len"] = len(accumulated)
        if on_delta and delta:
            on_delta(delta)

    res = post_json_stream(
        url,
        {"Authorization": "Bearer " + (config.get("api_key") or "")},
        body,
        silence_ms,
        _on_progress,
    )
    content = res["body"]
    if not content:
        raise RuntimeError("AI 返回内容为空")
    log.info("AI streamGenerateText done", {
        "model": model, "text_length": len(content),
        "elapsed_ms": int(time.time() * 1000 - start_ms),
    })
    return content


# ---------------- 视觉 ----------------


def resolve_entity_image_source(entity: dict, cfg: dict | None = None) -> dict | None:
    """等价 resolveEntityImageSource：ref_image → local_path → image_url → extra_images[0]。"""
    raw = ((cfg or {}).get("storage") or {}).get("local_path") or "./data/storage"
    storage_path = raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)

    ref = entity.get("ref_image")
    if ref:
        ref_s = str(ref)
        if ref_s.startswith("http"):
            return {"imageUrl": ref_s, "isLocal": False}
        return {"localAbsPath": os.path.join(storage_path, ref_s), "isLocal": True}

    if entity.get("local_path"):
        return {"localAbsPath": os.path.join(storage_path, str(entity["local_path"])), "isLocal": True}

    image_url = entity.get("image_url")
    if image_url and str(image_url).startswith("http"):
        return {"imageUrl": str(image_url), "isLocal": False}

    try:
        raw_extras = entity.get("extra_images")
        extras: list = []
        if raw_extras:
            parsed = json.loads(raw_extras) if isinstance(raw_extras, str) else raw_extras
            if isinstance(parsed, list):
                extras = parsed
        if extras and extras[0]:
            first = str(extras[0])
            if first.startswith("http"):
                return {"imageUrl": first, "isLocal": False}
            return {"localAbsPath": os.path.join(storage_path, first), "isLocal": True}
    except Exception:
        pass
    return None


def generate_text_with_vision(
    db, log, service_type: str, user_prompt: str, system_prompt: str,
    image_source: dict, options: dict | None = None,
) -> str:
    """等价 generateTextWithVision：OpenAI vision 消息格式，非流式请求。"""
    options = options or {}
    image_url_for_api: str
    image_log_info: dict = {}

    if image_source.get("imageUrl"):
        image_url_for_api = image_source["imageUrl"]
        if image_url_for_api.startswith("data:"):
            mime_match = re.match(r"^data:([^;]+);base64,", image_url_for_api)
            mime = mime_match.group(1) if mime_match else "unknown"
            b64_len = len(image_url_for_api) - (len(mime_match.group(0)) if mime_match else 0)
            image_log_info = {
                "image_type": "base64", "image_mime": mime,
                "image_size_kb": round(b64_len * 0.75 / 1024),
            }
        else:
            image_log_info = {"image_type": "url", "image_url": image_url_for_api[:100]}
    elif image_source.get("localAbsPath"):
        local_abs = image_source["localAbsPath"]
        if not os.path.exists(local_abs):
            raise RuntimeError(f"图片文件不存在：{local_abs}")
        with open(local_abs, "rb") as fh:
            buf = fh.read()
        ext = os.path.splitext(local_abs)[1].lower()
        mime = _MIME_BY_EXT.get(ext, "image/jpeg")
        image_url_for_api = f"data:{mime};base64," + base64.b64encode(buf).decode("ascii")
        image_log_info = {
            "image_type": "local_file", "image_path": local_abs,
            "image_size_kb": round(len(buf) / 1024), "image_mime": mime,
        }
    else:
        raise RuntimeError("imageSource 必须包含 imageUrl 或 localAbsPath")

    preferred_model = options.get("model")
    temperature = options.get("temperature", 0.3)
    max_tokens = options.get("max_tokens", 500)

    config = (
        get_config_for_model(db, service_type, preferred_model)
        if preferred_model
        else get_default_config(db, service_type)
    )
    if not config:
        config = get_default_config(db, "text")
    if not config:
        raise RuntimeError(f"未配置文本模型，请在「AI 配置」中添加 {service_type} 类型的配置")

    model = get_model_from_config(config, preferred_model)
    url = build_chat_url(config)

    log.info("[Vision] 开始请求", {
        "config_id": config.get("id"), "config_name": config.get("name"),
        "api_protocol": config.get("api_protocol") or "openai",
        "base_url": config.get("base_url"), "model": model,
        "is_reasoning_model": bool(re.match(r"^o\d", model, re.IGNORECASE)),
        "max_tokens": int(max_tokens), **image_log_info,
    })

    max_tok = int(max_tokens)
    is_reasoning_model = bool(re.match(r"^o\d", model, re.IGNORECASE))
    system_role = "developer" if is_reasoning_model else "system"
    merged_user_text = f"{system_prompt}\n\n{user_prompt}" if (system_prompt and is_reasoning_model) else user_prompt

    body = {
        "model": model,
        "messages": [
            *([{"role": system_role, "content": system_prompt}] if (system_prompt and not is_reasoning_model) else []),
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": merged_user_text},
                    {"type": "image_url", "image_url": {"url": image_url_for_api}},
                ],
            },
        ],
        **({"max_completion_tokens": max_tok} if is_reasoning_model else {"max_tokens": max_tok}),
        **({} if is_reasoning_model else {"temperature": float(temperature)}),
    }

    try:
        res = post_json_non_stream(
            url, {"Authorization": "Bearer " + (config.get("api_key") or "")}, body, VISION_TIMEOUT_MS
        )
    except Exception as http_err:
        log.error("[Vision] HTTP 请求失败", {"model": model, "url": url[:80], "error": str(http_err)})
        raise

    content = res["body"]
    if not content:
        log.error("[Vision] 返回内容为空", {
            "model": model, "status": res["status"], "raw_response": (res["raw"] or "")[:300],
        })
        raise RuntimeError(
            f"AI vision 返回内容为空（HTTP {res['status']}），原始响应：{(res['raw'] or '')[:200]}"
        )
    log.info("[Vision] 请求成功", {
        "model": model, "result_len": len(content), "result_preview": content[:100],
    })
    return content.strip()


def _quoted(name: str | None) -> str:
    """等价 JS 模板 `${name ? '"' + name + '"' : ''}`。"""
    return f'"{name}"' if name else ""


EXTRACT_PROMPTS = {
    "character": {
        "system": (
            "你是一位专业的影视/动漫角色美术设计师，正在处理一批角色造型参考素材。\n"
            "你收到的图片是用于角色设计的造型参考图（cosplay 造型图、服装搭配参考图或角色概念图），"
            "图中展示的是虚构角色的视觉造型，不涉及任何真实人物身份。\n\n"
            "你的任务：从视觉设计角度，提取图中可见的造型要素，撰写一份角色设定文案，供 AI 图像生成使用。\n\n"
            "请描述以下内容（只描述人物本身，忽略背景）：\n"
            "- 发型：发色（如深棕、黑色、浅金等）、发质感、发型款式（长短、层次、刘海、发尾走向）\n"
            "- 五官：脸型轮廓（瓜子/方/圆/椭圆）、眉形、眼型与眼距、鼻型、唇型与唇色、整体肤色\n"
            "- 体型：身形比例（高挑/中等/娇小）、体型特征（纤细/匀称/壮实）\n"
            "- 服装：款式、颜色、材质、层次搭配\n\n"
            "注意：如果你无法看清某些细节，请根据可见信息做合理推断，不要拒绝或道歉。\n"
            "输出要求：150-250字，直接输出描述，不加标题序号，像一份角色设定稿。"
        ),
        "user": lambda name: (
            f"这是角色{_quoted(name)}的造型参考图，"
            "请提取图中的造型视觉要素，生成角色外貌设定文案（忽略背景）。"
        ),
    },
    "scene": {
        "system": (
            "你是一位专业的影视场景美术设计师，擅长将参考图转化为 AI 图像生成所需的场景描述。"
            "请用中文描述图中的视觉元素：地点类型、光线色调、时间氛围、环境细节、空间构成。"
            "80-150字，直接输出描述，不要加标题或前缀。"
        ),
        "user": lambda name: (
            f"这是场景{_quoted(name)}的参考图，"
            "请提取图中的场景视觉特征，生成可用于 AI 图生的场景描述文字。"
        ),
    },
    "prop": {
        "system": (
            "你是一位专业的道具/产品视觉描述师，擅长将参考图转化为 AI 图像生成所需的道具描述。"
            "请用中文描述图中物品的视觉特征：类型、形状、颜色、材质质感、细节特征。"
            "80-150字，直接输出描述，不要加标题或前缀。"
        ),
        "user": lambda name: (
            f"这是道具{_quoted(name)}的参考图，"
            "请提取图中物品的视觉特征，生成可用于 AI 图生的道具描述文字。"
        ),
    },
}


def is_refusal_response(text: str) -> bool:
    """等价 isRefusalResponse：检测模型因安全策略拒绝描述。"""
    if not text:
        return False
    return any(p.search(text) for p in _REFUSAL_PATTERNS)


def extract_description_from_image(
    db, log, entity_type: str, image_url: str, entity_name: str | None = None
) -> dict:
    """等价 extractDescriptionFromImage：返回 { ok, description } 或 { ok: False, error }。"""
    prompts = EXTRACT_PROMPTS.get(entity_type)
    if not prompts:
        raise RuntimeError(f"不支持的实体类型：{entity_type}")

    if not (image_url and (image_url.startswith("http") or image_url.startswith("data:"))):
        raise RuntimeError("imageUrl 必须是 http URL 或 base64 data URL")

    try:
        result = generate_text_with_vision(
            db, log, "text",
            prompts["user"](entity_name),
            prompts["system"],
            {"imageUrl": image_url},
            {"max_tokens": 2000},
        )
        if is_refusal_response(result):
            log.warn("[Vision] 模型拒绝描述，可能因真实人物照片触发安全策略", {
                "entity_type": entity_type, "result": result,
            })
            return {
                "ok": False,
                "error": (
                    "模型因安全策略拒绝描述图中人物面部特征。建议：①使用 Gemini 模型（限制较少）；"
                    "②手动填写外貌描述；③上传卡通/插画风格的参考图。"
                ),
            }
        return {"ok": True, "description": result}
    except Exception as err:
        log.error("[Vision] extractDescriptionFromImage 失败", {
            "entity_type": entity_type, "raw_error": str(err),
        })
        msg = str(err)
        if re.search(r"image|vision|visual|multimodal", msg, re.IGNORECASE):
            return {
                "ok": False,
                "error": (
                    "AI 模型不支持图片识别，请在「AI 配置」中使用支持视觉的模型"
                    f"（如 GPT-4o、Gemini 1.5 等）【原始错误：{msg[:120]}】"
                ),
            }
        return {"ok": False, "error": f"AI 分析失败：{msg}"}
