"""AI Provider 注册中心与调度路由。
负责管理 ImageProvider / VideoProvider / MusicProvider 的实例化、协议匹配与按优先级路由。
"""
from __future__ import annotations

from typing import Any, Optional
from app.services.providers.base import (
    BaseImageProvider,
    BaseVideoProvider,
    BaseMusicProvider,
)
from app.services.providers.image_providers import (
    DashScopeImageProvider,
    NanoBananaImageProvider,
    KlingImageProvider,
    GeminiImageProvider,
    VolcengineImageProvider,
    AgnesImageProvider,
    OpenAIImageProvider,
)
from app.services.providers.video_providers import (
    VolcengineVideoProvider,
    KlingVideoProvider,
    DashScopeVideoProvider,
    MinimaxH3VideoProvider,
    AgnesVideoProvider,
    ViduVideoProvider,
    JimengVideoProvider,
    Veo3VideoProvider,
    SoraVideoProvider,
)
from app.services.providers.music_providers import (
    SunoMusicProvider,
    UdioMusicProvider,
    LocalLibraryMusicProvider,
)


class ImageProviderRegistry:
    """图像生成 Provider 注册中心。"""

    def __init__(self):
        self._providers: dict[str, BaseImageProvider] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(DashScopeImageProvider())
        self.register(NanoBananaImageProvider())
        self.register(KlingImageProvider())
        self.register(GeminiImageProvider())
        self.register(VolcengineImageProvider())
        self.register(AgnesImageProvider())
        self.register(OpenAIImageProvider())

    def register(self, provider: BaseImageProvider) -> None:
        self._providers[provider.protocol_name.lower()] = provider

    def get(self, protocol_or_provider: str) -> Optional[BaseImageProvider]:
        key = (protocol_or_provider or "").lower().strip()
        if key in self._providers:
            return self._providers[key]
        # 兼容性别名
        if "dashscope" in key or "wanx" in key or "qwen" in key:
            return self._providers.get("dashscope")
        if "kling" in key:
            return self._providers.get("kling")
        if "gemini" in key:
            return self._providers.get("gemini")
        if "volc" in key or "seedream" in key or "doubao" in key:
            return self._providers.get("volcengine")
        if "nano" in key or "banana" in key:
            return self._providers.get("nano_banana")
        if "agnes" in key:
            return self._providers.get("agnes")
        return self._providers.get("openai")


class VideoProviderRegistry:
    """视频生成 Provider 注册中心。"""

    def __init__(self):
        self._providers: dict[str, BaseVideoProvider] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(VolcengineVideoProvider())
        self.register(KlingVideoProvider())
        self.register(DashScopeVideoProvider())
        self.register(MinimaxH3VideoProvider())
        self.register(AgnesVideoProvider())
        self.register(ViduVideoProvider())
        self.register(JimengVideoProvider())
        self.register(Veo3VideoProvider())
        self.register(SoraVideoProvider())

    def register(self, provider: BaseVideoProvider) -> None:
        self._providers[provider.protocol_name.lower()] = provider

    def get(self, protocol_or_provider: str) -> Optional[BaseVideoProvider]:
        key = (protocol_or_provider or "").lower().strip()
        if key in self._providers:
            return self._providers[key]
        if "volc" in key or "seedance" in key or "doubao" in key:
            return self._providers.get("volcengine")
        if "kling" in key:
            return self._providers.get("kling")
        if "dashscope" in key or "wanx" in key:
            return self._providers.get("dashscope")
        if "minimax" in key:
            return self._providers.get("minimax_h3")
        if "vidu" in key:
            return self._providers.get("vidu")
        if "jimeng" in key:
            return self._providers.get("jimeng")
        if "veo" in key:
            return self._providers.get("veo3")
        if "sora" in key:
            return self._providers.get("sora")
        if "agnes" in key:
            return self._providers.get("agnes")
        return self._providers.get("volcengine")


class MusicProviderRegistry:
    """配乐/音乐 Provider 注册中心。"""

    def __init__(self):
        self._providers: dict[str, BaseMusicProvider] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(SunoMusicProvider())
        self.register(UdioMusicProvider())
        self.register(LocalLibraryMusicProvider())

    def register(self, provider: BaseMusicProvider) -> None:
        self._providers[provider.protocol_name.lower()] = provider

    def get(self, protocol_or_provider: str) -> Optional[BaseMusicProvider]:
        key = (protocol_or_provider or "").lower().strip()
        if key in self._providers:
            return self._providers[key]
        if "suno" in key:
            return self._providers.get("suno")
        if "udio" in key:
            return self._providers.get("udio")
        return self._providers.get("local")


# 全局单例注册中心
_image_registry = ImageProviderRegistry()
_video_registry = VideoProviderRegistry()
_music_registry = MusicProviderRegistry()


def get_image_provider(protocol_or_provider: str) -> BaseImageProvider:
    return _image_registry.get(protocol_or_provider) or OpenAIImageProvider()


def get_video_provider(protocol_or_provider: str) -> BaseVideoProvider:
    return _video_registry.get(protocol_or_provider) or VolcengineVideoProvider()


def get_music_provider(protocol_or_provider: str) -> BaseMusicProvider:
    return _music_registry.get(protocol_or_provider) or LocalLibraryMusicProvider()
