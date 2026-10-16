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
import struct
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.logger import get_logger
from app.services import ai_config_service as aiConfigService

logger = get_logger("lmd.tts_service")

_MINIMAX_URL = "https://api.minimax.chat/v1/t2a_v2"
_OPENAI_TIMEOUT = 120.0
_MINIMAX_TIMEOUT = 60.0


def _parse_settings(raw: Any) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_minimal_wav_bytes(duration_sec: float = 3.5, sample_rate: int = 16000) -> bytes:
    """生成最小合法单声道 PCM WAV 二进制流（用于无外部 Key 时的本地开发/测试母音频回退）。"""
    num_samples = max(int(duration_sec * sample_rate), 1600)
    data_size = num_samples * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        data_size,
    )
    return header + (b"\x00\x00" * num_samples)


def synthesize_with_minimax(
    text: str,
    voice_id: str,
    api_key: str,
    group_id: str,
    model: str,
    *,
    speed: float = 1.0,
    pitch: int = 0,
    timber_weights: list[dict[str, Any]] | None = None,
) -> bytes:
    """调用 MiniMax T2A v2 合成语音，支持多音色混合权重 (timber_weights) 与语速/音高微调。"""
    voice_setting: dict[str, Any] = {
        "voice_id": voice_id or "female-shaonv",
        "speed": float(speed or 1.0),
        "vol": 1.0,
        "pitch": int(pitch or 0),
    }
    payload_dict: dict[str, Any] = {
        "model": model or "speech-02-hd",
        "text": text,
        "stream": False,
        "voice_setting": voice_setting,
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    if timber_weights and isinstance(timber_weights, list):
        payload_dict["timber_weights"] = timber_weights

    logger.debug(
        "【TTS MiniMax 合成】[DEBUG 请求参数] model=%s, voice_id=%s, speed=%s, pitch=%s, timber_weights=%s, text_len=%d",
        payload_dict["model"],
        voice_setting["voice_id"],
        voice_setting["speed"],
        voice_setting["pitch"],
        json.dumps(timber_weights, ensure_ascii=False) if timber_weights else "None",
        len(text),
    )

    body = json.dumps(payload_dict, ensure_ascii=False)
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


def synthesize_with_openai(
    text: str,
    voice: str,
    api_key: str,
    base_url: str,
    model: str,
    speed: Any,
    *,
    instructions: str | None = None,
) -> bytes:
    """调用 OpenAI / 兼容端点合成语音，支持 gpt-4o-mini-tts 的声学演绎指令 (instructions)。"""
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/audio/speech"
    payload_dict: dict[str, Any] = {
        "model": model or "tts-1",
        "input": text,
        "voice": voice or "alloy",
        "response_format": "mp3",
        "speed": speed or 1.0,
    }
    if instructions and str(instructions).strip():
        payload_dict["instructions"] = str(instructions).strip()

    logger.debug(
        "【TTS OpenAI 合成】[DEBUG 请求参数] url=%s, model=%s, voice=%s, speed=%s, has_instructions=%s, text_len=%d",
        url,
        payload_dict["model"],
        payload_dict["voice"],
        payload_dict["speed"],
        bool(instructions),
        len(text),
    )

    body = json.dumps(payload_dict, ensure_ascii=False)
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

    opts: {
        text, storyboard_id, config, storage_base, voice_id, speed, pitch,
        timber_weights, instructions, custom_rel_path, allow_mock_fallback
    }
    @returns { local_path, provider, model, duration_sec }
    """
    text = opts.get("text")
    if not text or not str(text).strip():
        raise ValueError("text 不能为空")
    clean_text = str(text).strip()

    # 估算语音时长（中文基准约 4.2 字/秒，限制在 2.0s ~ 18.0s 之间）
    est_duration_sec = round(max(2.0, min(18.0, len(clean_text) / 4.2)), 2)

    tts_config = opts.get("config") or _pick_tts_config(db)
    allow_mock = bool(opts.get("allow_mock_fallback", False))

    if not tts_config and not allow_mock:
        raise ValueError("未配置 TTS 模型，请在「AI 配置」中添加 service_type=tts 的配置")

    provider = str((tts_config or {}).get("provider") or ("local_mock" if allow_mock else "")).lower()
    tts_settings = _parse_settings((tts_config or {}).get("settings"))

    # 外部传入的 voice_id / speed / pitch / timber_weights 优先，否则取配置值
    voice_id = opts.get("voice_id") or (tts_config or {}).get("voice_id") or tts_settings.get("voice_id") or ""
    group_id = (tts_config or {}).get("group_id") or tts_settings.get("group_id") or ""
    model_list = (tts_config or {}).get("model")
    model = (
        opts.get("model")
        or (tts_config or {}).get("default_model")
        or (model_list[0] if isinstance(model_list, list) and model_list else model_list)
        or ""
    )
    final_speed = float(opts.get("speed") or tts_settings.get("speed") or 1.0)
    final_pitch = int(opts.get("pitch") or tts_settings.get("pitch") or 0)
    timber_weights = opts.get("timber_weights")
    instructions = opts.get("instructions")

    logger.debug(
        "【TTS 合成入口】[DEBUG] provider=%s, model=%s, voice_id=%s, speed=%.2f, pitch=%d, custom_rel_path=%s, allow_mock=%s",
        provider,
        model,
        voice_id,
        final_speed,
        final_pitch,
        opts.get("custom_rel_path"),
        allow_mock,
    )

    if provider == "minimax" and (tts_config or {}).get("api_key"):
        audio_buffer = synthesize_with_minimax(
            clean_text,
            voice_id or "female-shaonv",
            tts_config.get("api_key"),
            group_id,
            model or "speech-02-hd",
            speed=final_speed,
            pitch=final_pitch,
            timber_weights=timber_weights,
        )
    elif (provider == "openai" or (tts_config or {}).get("base_url")) and (tts_config or {}).get("api_key", True):
        if not (tts_config or {}).get("api_key") and not (tts_config or {}).get("base_url") and allow_mock:
            audio_buffer = _build_minimal_wav_bytes(est_duration_sec)
        else:
            audio_buffer = synthesize_with_openai(
                clean_text,
                voice_id or "alloy",
                (tts_config or {}).get("api_key"),
                (tts_config or {}).get("base_url"),
                model or "tts-1",
                final_speed,
                instructions=instructions,
            )
    elif allow_mock or provider in ("local", "local_mock", "mock"):
        logger.debug("【TTS 合成入口】[DEBUG 本地降级] 未配置外部 TTS 密钥，启用本地参考音频生成回退 (时长=%.2fs)", est_duration_sec)
        audio_buffer = _build_minimal_wav_bytes(est_duration_sec)
        provider = provider or "local_mock"
        model = model or "speech-02-hd-mock"
    else:
        raise ValueError(f"不支持的 TTS provider: {provider}，目前支持 openai、minimax")

    storage_base = Path(opts["storage_base"])
    custom_rel_path = opts.get("custom_rel_path")
    if custom_rel_path:
        local_path = str(custom_rel_path).replace("\\", "/").lstrip("/")
        full_file_path = storage_base / local_path
        full_file_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        audio_dir = storage_base / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        sb_id = opts.get("storyboard_id") or "x"
        filename = f"tts_sb{sb_id}_{uuid.uuid4().hex[:8]}.mp3"
        local_path = f"audio/{filename}"
        full_file_path = audio_dir / filename

    with open(full_file_path, "wb") as f:
        f.write(audio_buffer)

    if log:
        log.info(
            "[TTS] 合成完成",
            extra={
                "storyboard_id": opts.get("storyboard_id"),
                "local_path": local_path,
                "provider": provider,
                "duration_sec": est_duration_sec,
            },
        )
    logger.debug("【TTS 合成完成】[DEBUG] 落盘路径=%s, 字节数=%d, 估算时长=%.2fs", full_file_path, len(audio_buffer), est_duration_sec)
    return {
        "local_path": local_path,
        "provider": provider,
        "model": model or "speech-02-hd",
        "duration_sec": est_duration_sec,
    }
