"""图像生成 Provider 具体协议实现。
对接 DashScope（通义万象/千问）、NanoBanana、可灵（Kling）、Gemini、火山引擎（Doubao/Seedream）、Agnes 以及通用 OpenAI Compatible 格式。
"""
from __future__ import annotations

from typing import Any
from app.services.providers.base import (
    BaseImageProvider,
    ImageGenerationOptions,
    ImageGenerationResult,
)


class DashScopeImageProvider(BaseImageProvider):
    """通义万象 / 千问图像 Provider。"""
    protocol_name = "dashscope"

    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        from app.services import imageClient
        res = imageClient.call_dash_scope_image_api(config, log, opts.model_dump())
        return ImageGenerationResult(
            image_url=res.get("image_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )


class NanoBananaImageProvider(BaseImageProvider):
    """NanoBanana 图像 Provider。"""
    protocol_name = "nano_banana"

    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        from app.services import imageClient
        res = imageClient.call_nano_banana_image_api(config, log, opts.model_dump())
        return ImageGenerationResult(
            image_url=res.get("image_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )


class KlingImageProvider(BaseImageProvider):
    """可灵 AI 图像 Provider。"""
    protocol_name = "kling"

    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        from app.services import imageClient
        res = imageClient.call_kling_image_api(config, log, opts.model_dump())
        return ImageGenerationResult(
            image_url=res.get("image_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )


class GeminiImageProvider(BaseImageProvider):
    """Google Gemini 图像 Provider。"""
    protocol_name = "gemini"

    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        from app.services import imageClient
        # opts dict
        opts_dict = opts.model_dump()
        res = imageClient.call_gemini_image_api(None, config, log, opts_dict)
        return ImageGenerationResult(
            image_url=res.get("image_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )


class VolcengineImageProvider(BaseImageProvider):
    """火山引擎 / 豆包 Seedream 图像 Provider。"""
    protocol_name = "volcengine"

    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        from app.services import imageClient
        # Volcengine 默认走通用 imageClient.call_image_api
        res = imageClient.call_image_api(None, log, {**opts.model_dump(), "config": config})
        return ImageGenerationResult(
            image_url=res.get("image_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )


class AgnesImageProvider(BaseImageProvider):
    """Agnes 图像 Provider。"""
    protocol_name = "agnes"

    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        from app.services import imageClient
        res = imageClient.call_image_api(None, log, {**opts.model_dump(), "config": config})
        return ImageGenerationResult(
            image_url=res.get("image_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )


class OpenAIImageProvider(BaseImageProvider):
    """OpenAI / 通用 HTTP 图像 Provider。"""
    protocol_name = "openai"

    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        from app.services import imageClient
        res = imageClient.call_image_api(None, log, {**opts.model_dump(), "config": config})
        return ImageGenerationResult(
            image_url=res.get("image_url"),
            error=res.get("error"),
            raw_data=res.get("raw_data") or res,
        )
