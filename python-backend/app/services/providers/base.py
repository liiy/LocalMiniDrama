"""AI 生成 Provider 协议基类与请求/响应 Schema。
采用统一的 Provider Protocol 模式，解耦各模型厂商专有 API 格式与业务调度层。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.schemas.contracts.provider_options import (
    TaskExecutionStatus,
    ImageGenerationOptions,
    ImageGenerationResult,
    VideoGenerationOptions,
    VideoTaskResult,
    VideoPollResult,
    MusicGenerationOptions,
    MusicGenerationResult,
)


# ---------------- 抽象 Provider 接口 ----------------

class BaseImageProvider(ABC):
    """图像生成 Provider 抽象接口。"""

    protocol_name: str = "base"

    @property
    def provider_name(self) -> str:
        return self.protocol_name

    @abstractmethod
    def generate_image(self, config: dict[str, Any], log, opts: ImageGenerationOptions) -> ImageGenerationResult:
        """执行图像生成调用，返回结构化图像结果。"""
        raise NotImplementedError


class BaseVideoProvider(ABC):
    """视频生成 Provider 抽象接口。"""

    protocol_name: str = "base"

    @property
    def provider_name(self) -> str:
        return self.protocol_name

    @abstractmethod
    def create_video_task(
        self,
        config: dict[str, Any],
        log,
        opts: VideoGenerationOptions,
        post_json=None,
        db=None,
    ) -> VideoTaskResult:
        """提交视频生成异步任务。"""
        raise NotImplementedError

    @abstractmethod
    def poll_video_task(
        self,
        config: dict[str, Any],
        log,
        task_id: str,
        video_gen_id: Any = None,
        fetch_bytes=None,
    ) -> VideoPollResult:
        """轮询视频任务执行状态。"""
        raise NotImplementedError


class BaseMusicProvider(ABC):
    """音乐/配乐生成 Provider 抽象接口。"""

    protocol_name: str = "base"

    @property
    def provider_name(self) -> str:
        return self.protocol_name

    @abstractmethod
    def generate_music(self, config: dict[str, Any], log, opts: MusicGenerationOptions) -> MusicGenerationResult:
        """执行音乐/配乐生成或检索，返回结构化音频结果。"""
        raise NotImplementedError
