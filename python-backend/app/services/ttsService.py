"""TTS 语音合成服务 — 契约翻译 backend-node/src/services/ttsService.js。

支持的 provider：
- minimax：MiniMax T2A v2，POST https://api.minimax.chat/v1/t2a_v2?GroupId=…，
  响应 { base_resp: { status_code, status_msg }, data: { audio: "<hex>" } }
- openai（或有 base_url 的任意兼容端点）：POST {base_url}/audio/speech

配置来源：aiConfigService.listConfigs(db, 'tts') 中 is_active 的
默认项（is_default）或第一条。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.services import aiConfigService

_MINIMAX_URL = "https://api.minimax.chat/v1/t2a_v2"
_OPENAI_TIMEOUT = 120.0
_MINIMAX_TIMEOUT = 60.0


def _parse_settings(raw: Any) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def synthesize_with_minimax(text: str, voice_id: str, api_key: str, group_id: str, model: str) -> bytes:
    body = json.dumps(
        {
            "model": model or "speech-02-hd",
            "text": text,
            "stream": False,
            "voice_setting": {"voice_id": voice_id or "female-shaonv", "speed": 1.0, "vol": 1.0, "pitch": 0},
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        },
        ensure_ascii=False,
    )
    url = f"{_MINIMAX_URL}?GroupId={group_id}"
    res = httpx.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        content=body,
        timeout=_MINIMAX_TIMEOUT,
    )
    if res.status_code != 200:
        raise ValueError(f"MiniMax TTS HTTP {res.status_code}: {res.text}")

    data = res.json()
    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code") != 0:
        raise ValueError(f"MiniMax TTS error: {base_resp.get('status_msg') or 'unknown'}")

    audio_hex = (data.get("data") or {}).get("audio")
    if not audio_hex:
        raise ValueError("MiniMax TTS 未返回音频")
    try:
        return bytes.fromhex(audio_hex)
    except ValueError as e:
        raise ValueError("MiniMax TTS 返回的音频不是合法十六进制") from e


def synthesize_with_openai(text: str, voice: str, api_key: str, base_url: str, model: str, speed: Any) -> bytes:
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/audio/speech"
    body = json.dumps(
        {
            "model": model or "tts-1",
            "input": text,
            "voice": voice or "alloy",
            "response_format": "mp3",
            "speed": speed or 1.0,
        },
        ensure_ascii=False,
    )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    res = httpx.post(url, headers=headers, content=body, timeout=_OPENAI_TIMEOUT)
    if not (200 <= res.status_code < 300):
        raise ValueError(f"OpenAI TTS HTTP {res.status_code}: {res.text[:500]}")
    return res.content


def _pick_tts_config(db) -> dict | None:
    """等价 Node：is_active 中取 is_default，否则取第一条。"""
    configs = aiConfigService.list_configs(db, "tts")
    active = [c for c in configs if c.get("is_active")]
    return next((c for c in active if c.get("is_default")), active[0] if active else None)


def synthesize(db, log, opts: dict) -> dict:
    """合成 TTS 并保存到本地文件。

    opts: { text, storyboard_id, config, storage_base, voice_id, speed }
    @returns { local_path }
    """
    text = opts.get("text")
    if not text or not str(text).strip():
        raise ValueError("text 不能为空")

    tts_config = opts.get("config") or _pick_tts_config(db)
    if not tts_config:
        raise ValueError("未配置 TTS 模型，请在「AI 配置」中添加 service_type=tts 的配置")

    provider = str(tts_config.get("provider") or "").lower()
    tts_settings = _parse_settings(tts_config.get("settings"))

    # 外部传入的 voice_id / speed 优先（海外化场景），否则取配置值
    voice_id = opts.get("voice_id") or tts_config.get("voice_id") or tts_settings.get("voice_id") or ""
    group_id = tts_config.get("group_id") or tts_settings.get("group_id") or ""
    model_list = tts_config.get("model")
    model = (
        tts_config.get("default_model")
        or (model_list[0] if isinstance(model_list, list) and model_list else model_list)
        or ""
    )
    final_speed = opts.get("speed") or tts_settings.get("speed") or 1.0

    if provider == "minimax":
        audio_buffer = synthesize_with_minimax(
            text, voice_id or "female-shaonv", tts_config.get("api_key"), group_id, model or "speech-02-hd"
        )
    elif provider == "openai" or tts_config.get("base_url"):
        audio_buffer = synthesize_with_openai(
            text, voice_id or "alloy", tts_config.get("api_key"), tts_config.get("base_url"),
            model or "tts-1", final_speed,
        )
    else:
        raise ValueError(f"不支持的 TTS provider: {provider}，目前支持 openai、minimax")

    audio_dir = Path(opts["storage_base"]) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    sb_id = opts.get("storyboard_id") or "x"
    filename = f"tts_sb{sb_id}_{uuid.uuid4().hex[:8]}.mp3"
    with open(audio_dir / filename, "wb") as f:
        f.write(audio_buffer)

    local_path = f"audio/{filename}"
    log.info("[TTS] 合成完成", extra={"storyboard_id": opts.get("storyboard_id"), "local_path": local_path, "provider": provider})
    return {"local_path": local_path}
