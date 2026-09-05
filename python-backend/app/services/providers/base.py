"""AI 生成 Provider 协议基类与请求/响应 Schema。
采用统一的 Provider Protocol 模式，解耦各模型厂商专有 API 格式与业务调度层。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------------- 图像生成 Schema ----------------

class ImageGenerationOptions(BaseModel):
    """图像生成统一入参。"""
    prompt: str = Field(default="", description="正面提示词")
    negative_prompt: Optional[str] = Field(default=None, description="负面提示词")
    model: Optional[str] = Field(default=None, description="模型名称")
    size: Optional[str] = Field(default=None, description="图像分辨率或比例")
    quality: Optional[str] = Field(default=None, description="画质")
    reference_images: Optional[list[str]] = Field(default=None, description="参考图标识或路径")
    reference_image_urls: Optional[list[str]] = Field(default=None, description="参考图 HTTP URL 列表")
    files_base_url: Optional[str] = Field(default=None, description="文件基础服务 URL")
    storage_local_path: Optional[str] = Field(default=None, description="本地存储路径")
    image_gen_id: Optional[int] = Field(default=None, description="关联图像生成记录 ID")
    width: Optional[int] = Field(default=None, description="指定宽度")
    height: Optional[int] = Field(default=None, description="指定高度")
    extra_options: dict[str, Any] = Field(default_factory=dict, description="厂商扩展选项")
    config: dict[str, Any] = Field(default_factory=dict, description="AI 服务配置信息")


class ImageGenerationResult(BaseModel):
    """图像生成统一出参。"""
    image_url: Optional[str] = Field(default=None, description="生成的图片 URL 或 base64 数据")
    local_path: Optional[str] = Field(default=None, description="本地落盘相对路径")
    width: Optional[int] = Field(default=None, description="实际宽度")
    height: Optional[int] = Field(default=None, description="实际高度")
    mime_type: Optional[str] = Field(default=None, description="MIME 类型")
    raw_data: Optional[dict[str, Any]] = Field(default=None, description="厂商原始响应数据")
    error: Optional[str] = Field(default=None, description="错误信息（若失败）")


# ---------------- 视频生成 Schema ----------------

class VideoGenerationOptions(BaseModel):
    """视频生成统一入参。"""
    prompt: str = Field(default="", description="视频提示词")
    model: Optional[str] = Field(default=None, description="视频模型名称")
    duration: Optional[float] = Field(default=5.0, description="时长（秒）")
    aspect_ratio: Optional[str] = Field(default="16:9", description="画面宽高比")
    resolution: Optional[str] = Field(default="720p", description="分辨率")
    seed: Optional[int] = Field(default=None, description="随机种子")
    camera_fixed: Optional[bool] = Field(default=False, description="是否固定机位")
    watermark: Optional[bool] = Field(default=False, description="是否包含水印")
    first_frame_url: Optional[str] = Field(default=None, description="首帧图片地址")
    last_frame_url: Optional[str] = Field(default=None, description="尾帧图片地址")
    reference_image_urls: Optional[list[str]] = Field(default=None, description="参考图片列表")
    files_base_url: Optional[str] = Field(default=None, description="文件基础 URL")
    storage_local_path: Optional[str] = Field(default=None, description="本地存储根路径")
    video_gen_id: Optional[int] = Field(default=None, description="关联视频生成记录 ID")
    scene_id: Optional[int] = Field(default=None, description="关联场景 ID")
    storyboard_id: Optional[int] = Field(default=None, description="关联分镜 ID")
    drama_id: Optional[int] = Field(default=None, description="关联短剧 ID")
    extra_options: dict[str, Any] = Field(default_factory=dict, description="厂商扩展参数")
    config: dict[str, Any] = Field(default_factory=dict, description="AI 服务配置信息")


class VideoTaskResult(BaseModel):
    """异步创建视频任务响应。"""
    task_id: Optional[str] = Field(default=None, description="平台任务 ID 或轮询 ID")
    provider_task_id: Optional[str] = Field(default=None, description="供应商远程任务 ID")
    status: str = Field(default="pending", description="初始状态: pending / processing / succeeded / failed")
    video_url: Optional[str] = Field(default=None, description="若为同步生成直接返回的视频地址")
    error: Optional[str] = Field(default=None, description="错误信息")
    raw_data: Optional[dict[str, Any]] = Field(default=None, description="厂商原始响应")


class VideoPollResult(BaseModel):
    """视频任务轮询响应。"""
    task_id: str = Field(description="轮询任务 ID")
    status: str = Field(description="当前状态: pending / processing / succeeded / failed")
    video_url: Optional[str] = Field(default=None, description="生成的视频 URL")
    local_path: Optional[str] = Field(default=None, description="下载落盘路径")
    duration: Optional[float] = Field(default=None, description="视频时长")
    error_msg: Optional[str] = Field(default=None, description="失败原因")
    raw_data: Optional[dict[str, Any]] = Field(default=None, description="厂商原始数据")


# ---------------- 音乐/配乐生成 Schema ----------------

class MusicGenerationOptions(BaseModel):
    """音乐生成统一入参。"""
    prompt: str = Field(default="", description="音乐风格/旋律描述提示词")
    style: Optional[str] = Field(default=None, description="风格流派（如: 史诗管弦、暗黑悬疑、快节奏电子）")
    mood: Optional[str] = Field(default=None, description="情绪氛围（如: 紧张、悲壮、喜悦）")
    title: Optional[str] = Field(default="", description="曲目标题")
    bpm: Optional[int] = Field(default=None, description="目标 BPM")
    duration_seconds: Optional[int] = Field(default=30, description="生成时长（秒）")
    instrumental: bool = Field(default=True, description="是否纯器乐伴奏（无真人人声）")
    tags: Optional[list[str]] = Field(default=None, description="风格标签列表")
    reference_audio_url: Optional[str] = Field(default=None, description="参考音频 URL")
    extra_options: dict[str, Any] = Field(default_factory=dict, description="扩展参数")
    config: dict[str, Any] = Field(default_factory=dict, description="AI 服务配置信息")


class MusicGenerationResult(BaseModel):
    """音乐生成统一出参。"""
    audio_url: Optional[str] = Field(default=None, description="音频 URL")
    local_path: Optional[str] = Field(default=None, description="本地落盘路径")
    title: Optional[str] = Field(default=None, description="曲目标题")
    duration_seconds: Optional[float] = Field(default=None, description="音频时长")
    tags: Optional[list[str]] = Field(default=None, description="风格标签")
    error: Optional[str] = Field(default=None, description="错误信息")
    raw_data: Optional[dict[str, Any]] = Field(default=None, description="厂商原始数据")


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
