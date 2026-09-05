"""音乐/配乐 Provider 具体实现。
包含:
- SunoMusicProvider: Suno 风格 AI 配乐生成
- UdioMusicProvider: Udio 风格 AI 音乐生成
- LocalLibraryMusicProvider: 本地预设配乐与音效库检索匹配
"""
from __future__ import annotations

import os
import json
import httpx
from typing import Any
from app.services.providers.base import (
    BaseMusicProvider,
    MusicGenerationOptions,
    MusicGenerationResult,
)


class SunoMusicProvider(BaseMusicProvider):
    """Suno 配乐生成 Provider。"""
    protocol_name = "suno"

    def generate_music(self, config: dict[str, Any], log, opts: MusicGenerationOptions) -> MusicGenerationResult:
        base_url = (config.get("base_url") or "").rstrip("/")
        api_key = config.get("api_key") or ""
        endpoint = config.get("endpoint") or "/api/v1/suno/generate"
        url = f"{base_url}{endpoint}" if base_url else endpoint

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
        }

        body = {
            "prompt": opts.prompt or f"{opts.style or ''} {opts.mood or ''} 纯伴奏短剧配乐".strip(),
            "make_instrumental": opts.instrumental,
            "title": opts.title or "短剧配乐",
            "tags": " ".join(opts.tags or [opts.style or "soundtrack", opts.mood or "dramatic"]),
        }

        if not base_url:
            # 离线/测试环境默认返回模拟结构
            return MusicGenerationResult(
                audio_url=f"/static/audio/mock_suno_{opts.mood or 'theme'}.mp3",
                title=opts.title or "Suno 生成配乐",
                duration_seconds=float(opts.duration_seconds or 30),
                tags=opts.tags or [opts.style or "cinematic"],
                raw_data={"status": "mock_generated", "provider": "suno"},
            )

        try:
            with httpx.Client(timeout=60.0) as client:
                res = client.post(url, headers=headers, json=body)
                if res.status_code >= 400:
                    return MusicGenerationResult(error=f"Suno 接口调用失败: HTTP {res.status_code} - {res.text[:200]}")
                data = res.json()
                # 兼容不同 Suno API 代理返回结构
                audio_url = (
                    data.get("audio_url")
                    or (data.get("data") and data["data"][0].get("audio_url"))
                    or (data.get("clips") and data["clips"][0].get("audio_url"))
                )
                return MusicGenerationResult(
                    audio_url=audio_url,
                    title=opts.title or data.get("title") or "Suno 生成配乐",
                    duration_seconds=float(opts.duration_seconds or 30),
                    tags=opts.tags,
                    raw_data=data,
                )
        except Exception as e:
            if log:
                log.error("Suno music generation failed: %s", e)
            return MusicGenerationResult(error=f"Suno 音乐生成异常: {str(e)}")


class UdioMusicProvider(BaseMusicProvider):
    """Udio 配乐生成 Provider。"""
    protocol_name = "udio"

    def generate_music(self, config: dict[str, Any], log, opts: MusicGenerationOptions) -> MusicGenerationResult:
        base_url = (config.get("base_url") or "").rstrip("/")
        api_key = config.get("api_key") or ""
        endpoint = config.get("endpoint") or "/api/v1/udio/generate"
        url = f"{base_url}{endpoint}" if base_url else endpoint

        if not base_url:
            return MusicGenerationResult(
                audio_url=f"/static/audio/mock_udio_{opts.mood or 'ambient'}.mp3",
                title=opts.title or "Udio 生成配乐",
                duration_seconds=float(opts.duration_seconds or 30),
                tags=opts.tags or [opts.style or "cinematic"],
                raw_data={"status": "mock_generated", "provider": "udio"},
            )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
        }
        body = {
            "prompt": opts.prompt,
            "style": opts.style,
            "instrumental": opts.instrumental,
            "duration": opts.duration_seconds,
        }
        try:
            with httpx.Client(timeout=60.0) as client:
                res = client.post(url, headers=headers, json=body)
                if res.status_code >= 400:
                    return MusicGenerationResult(error=f"Udio 接口错误: HTTP {res.status_code}")
                data = res.json()
                audio_url = data.get("audio_url") or (data.get("data") and data["data"][0].get("audio_url"))
                return MusicGenerationResult(
                    audio_url=audio_url,
                    title=opts.title or "Udio 配乐",
                    duration_seconds=float(opts.duration_seconds or 30),
                    tags=opts.tags,
                    raw_data=data,
                )
        except Exception as e:
            return MusicGenerationResult(error=f"Udio 音乐生成异常: {str(e)}")


class LocalLibraryMusicProvider(BaseMusicProvider):
    """本地配乐库检索 Provider。根据情绪、流派与标签从本地素材库匹配最优 BGM。"""
    protocol_name = "local"

    # 内置预设本地音乐库索引
    PRESET_LIBRARY = [
        {"title": "紧张悬疑铺垫", "mood": "紧张", "style": "悬疑", "bpm": 110, "url": "/static/audio/bgm/suspense_tension.mp3", "tags": ["紧张", "反转", "暗黑"]},
        {"title": "反转打脸爆发", "mood": "反转", "style": "史诗", "bpm": 128, "url": "/static/audio/bgm/epic_climax.mp3", "tags": ["反转", "爆发", "打脸", "胜利"]},
        {"title": "温情回忆与悲伤", "mood": "悲伤", "style": "抒情", "bpm": 85, "url": "/static/audio/bgm/emotional_piano.mp3", "tags": ["悲伤", "情感", "回忆"]},
        {"title": "日常轻松诙谐", "mood": "轻松", "style": "喜剧", "bpm": 100, "url": "/static/audio/bgm/comedy_light.mp3", "tags": ["轻松", "幽默", "日常"]},
        {"title": "动作追逐对峙", "mood": "热血", "style": "电子", "bpm": 135, "url": "/static/audio/bgm/action_chase.mp3", "tags": ["热血", "打斗", "追逐"]},
    ]

    def generate_music(self, config: dict[str, Any], log, opts: MusicGenerationOptions) -> MusicGenerationResult:
        query_mood = str(opts.mood or "").strip()
        query_style = str(opts.style or "").strip()
        query_tags = set(opts.tags or [])
        if query_mood:
            query_tags.add(query_mood)
        if query_style:
            query_tags.add(query_style)

        best_match = None
        best_score = -1

        for item in self.PRESET_LIBRARY:
            score = 0
            if query_mood and query_mood in item["mood"]:
                score += 3
            if query_style and query_style in item["style"]:
                score += 2
            for tag in query_tags:
                if tag in item["tags"]:
                    score += 1
            if score > best_score:
                best_score = score
                best_match = item

        chosen = best_match or self.PRESET_LIBRARY[0]
        return MusicGenerationResult(
            audio_url=chosen["url"],
            title=chosen["title"],
            duration_seconds=float(opts.duration_seconds or 30),
            tags=chosen["tags"],
            raw_data={"matched_preset": chosen, "score": best_score, "provider": "local"},
        )
