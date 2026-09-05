"""AI 厂商协议抽象与 Provider 体系（统一支持图像、视频、音频/音乐）。
包含:
- base: Provider 基础协议定义与请求响应 Schema
- image_providers: 图像生成 Provider 实现
- video_providers: 视频生成 Provider 实现
- music_providers: 音乐/配乐生成 Provider 实现
- registry: 统一注册中心与路由分发
"""
from app.services.providers.base import (
    BaseImageProvider,
    BaseVideoProvider,
    BaseMusicProvider,
    ImageGenerationOptions,
    ImageGenerationResult,
    VideoGenerationOptions,
    VideoTaskResult,
    VideoPollResult,
    MusicGenerationOptions,
    MusicGenerationResult,
)
from app.services.providers.registry import (
    ImageProviderRegistry,
    VideoProviderRegistry,
    MusicProviderRegistry,
    get_image_provider,
    get_video_provider,
    get_music_provider,
)

__all__ = [
    "BaseImageProvider",
    "BaseVideoProvider",
    "BaseMusicProvider",
    "ImageGenerationOptions",
    "ImageGenerationResult",
    "VideoGenerationOptions",
    "VideoTaskResult",
    "VideoPollResult",
    "MusicGenerationOptions",
    "MusicGenerationResult",
    "ImageProviderRegistry",
    "VideoProviderRegistry",
    "MusicProviderRegistry",
    "get_image_provider",
    "get_video_provider",
    "get_music_provider",
]
