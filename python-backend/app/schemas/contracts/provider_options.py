# -*- coding: utf-8 -*-
"""AI 生成 Provider 协议入参及出参标准化契约 (Provider Options & Results)。

采用统一的 Provider Protocol 模式，定义多模态 AI (图像、视频、音频/音乐) 厂商调用的标准请求入参及响应结果结构，
彻底解耦各底层模型厂商（即梦、Minimax、Runway、Kling、Sora 等）专有 API 格式与上层业务调度层。
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


# =====================================================================
# 1. 任务状态枚举定义
# =====================================================================

class TaskExecutionStatus(StrEnum):
    """异步多模态任务执行状态枚举。"""
    PENDING = "pending"          # 任务已提交排队等待中
    PROCESSING = "processing"    # 厂商算力渲染执行中
    SUCCEEDED = "succeeded"      # 任务生成完成且已成功获取媒体结果
    FAILED = "failed"            # 任务执行失败


# =====================================================================
# 2. 图像生成契约 (Image Generation Options & Results)
# =====================================================================

class ImageGenerationOptions(BaseModel):
    """多模态图像生成统一入参选项契约。"""
    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(
        default="",
        description="正向提示词 (描述画面主体、角色锚点、光影构图与画风)"
    )
    negative_prompt: Optional[str] = Field(
        default=None,
        description="反向提示词 (排除畸变、劣质、水印、低清等不良特征)"
    )
    model: Optional[str] = Field(
        default=None,
        description="底层生图模型名称或服务标识 (如 jimeng-v2.1, flux-dev, midjourney-v6)"
    )
    size: Optional[str] = Field(
        default=None,
        description="目标分辨率或画幅比例规格描述 (如 1024x1792, 9:16)"
    )
    quality: Optional[str] = Field(
        default=None,
        description="画质等级预设 (如 standard, hd, ultra)"
    )
    reference_images: Optional[list[str]] = Field(
        default=None,
        description="参考图本地路径或唯一资产标识列表 (用于一致性垫图/IP-Adapter)"
    )
    reference_image_urls: Optional[list[str]] = Field(
        default=None,
        description="参考图网络 HTTP/HTTPS URL 列表"
    )
    files_base_url: Optional[str] = Field(
        default=None,
        description="文件静态资源基础服务 URL"
    )
    storage_local_path: Optional[str] = Field(
        default=None,
        description="生成图像下载落盘的本地文件系统绝对或相对路径"
    )
    image_gen_id: Optional[int] = Field(
        default=None,
        description="关联数据库图像生成任务记录唯一主键 ID"
    )
    width: Optional[int] = Field(
        default=None,
        description="指定目标图像像素宽度"
    )
    height: Optional[int] = Field(
        default=None,
        description="指定目标图像像素高度"
    )
    extra_options: dict[str, Any] = Field(
        default_factory=dict,
        description="厂商专有底层扩展参数 (透传至各模型厂商 API)"
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="AI 服务连接凭据与端点配置信息 (API Key, Base URL 等)"
    )


class ImageGenerationResult(BaseModel):
    """多模态图像生成统一出参结果契约。"""
    model_config = ConfigDict(populate_by_name=True)

    image_url: Optional[str] = Field(
        default=None,
        description="生成的图片在线访问 URL 或 Base64 编码数据"
    )
    local_path: Optional[str] = Field(
        default=None,
        description="本地持久化落盘后的相对或绝对路径"
    )
    width: Optional[int] = Field(
        default=None,
        description="产出图片的实际像素宽度"
    )
    height: Optional[int] = Field(
        default=None,
        description="产出图片的实际像素高度"
    )
    mime_type: Optional[str] = Field(
        default=None,
        description="图片 MIME 媒体类型 (如 image/png, image/jpeg, image/webp)"
    )
    raw_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="模型厂商原始响应 JSON 数据体"
    )
    error: Optional[str] = Field(
        default=None,
        description="生成失败时的错误摘要描述或异常堆栈信息"
    )


# =====================================================================
# 3. 视频生成契约 (Video Generation Options & Results)
# =====================================================================

class VideoGenerationOptions(BaseModel):
    """多模态视频生成统一入参选项契约。"""
    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(
        default="",
        description="视频运镜与动态行为动作提示词"
    )
    model: Optional[str] = Field(
        default=None,
        description="目标视频生成模型名称 (如 kling-v1.5, gen3a_turbo, hailuo)"
    )
    duration: Optional[float] = Field(
        default=5.0,
        description="视频目标生成时长 (秒)"
    )
    aspect_ratio: Optional[str] = Field(
        default="16:9",
        description="视频画幅比例 (如 9:16 竖屏, 16:9 横屏)"
    )
    resolution: Optional[str] = Field(
        default="720p",
        description="视频清晰度分辨率规格 (如 720p, 1080p, 4k)"
    )
    seed: Optional[int] = Field(
        default=None,
        description="渲染随机数种子 (用于复现确定性镜头动态)"
    )
    camera_fixed: Optional[bool] = Field(
        default=False,
        description="是否强制固定机位 (无运镜平移摇晃)"
    )
    watermark: Optional[bool] = Field(
        default=False,
        description="是否包含官方水印标志"
    )
    first_frame_url: Optional[str] = Field(
        default=None,
        description="图生视频首帧基准图片网络访问地址"
    )
    last_frame_url: Optional[str] = Field(
        default=None,
        description="首尾帧插值生成的尾帧图片网络访问地址"
    )
    reference_image_urls: Optional[list[str]] = Field(
        default=None,
        description="参考多视角或人物/环境垫图列表"
    )
    files_base_url: Optional[str] = Field(
        default=None,
        description="文件服务前缀 URL"
    )
    storage_local_path: Optional[str] = Field(
        default=None,
        description="生成视频下载落盘的本地存储根目录路径"
    )
    video_gen_id: Optional[int] = Field(
        default=None,
        description="关联数据库视频生成记录唯一主键 ID"
    )
    scene_id: Optional[int] = Field(
        default=None,
        description="所属分场编号唯一标识 ID"
    )
    storyboard_id: Optional[int] = Field(
        default=None,
        description="所属分镜镜头唯一标识 ID"
    )
    drama_id: Optional[int] = Field(
        default=None,
        description="所属短剧项目唯一标识 ID"
    )
    extra_options: dict[str, Any] = Field(
        default_factory=dict,
        description="厂商专有底层视频扩展参数"
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="AI 服务连接凭据与端点配置信息"
    )


class VideoTaskResult(BaseModel):
    """异步创建视频任务响应契约。"""
    model_config = ConfigDict(populate_by_name=True)

    task_id: Optional[str] = Field(
        default=None,
        description="平台内部生成任务 ID 或轮询追踪 ID"
    )
    provider_task_id: Optional[str] = Field(
        default=None,
        description="远程模型厂商平台返回的任务唯一追踪 ID"
    )
    status: str = Field(
        default="pending",
        description="任务初始状态: pending (排队中) / processing (渲染中) / succeeded (成功) / failed (失败)"
    )
    video_url: Optional[str] = Field(
        default=None,
        description="若为同步生成直接返回的最终视频在线播放 URL"
    )
    error: Optional[str] = Field(
        default=None,
        description="异步创建失败时的错误信息说明"
    )
    raw_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="模型厂商创建任务时的原始响应数据"
    )


class VideoPollResult(BaseModel):
    """视频异步任务轮询结果契约。"""
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(
        description="当前轮询的目标任务唯一标识 ID"
    )
    status: str = Field(
        description="任务当前最新执行状态: pending / processing / succeeded / failed"
    )
    video_url: Optional[str] = Field(
        default=None,
        description="渲染完成的视频在线访问 URL"
    )
    local_path: Optional[str] = Field(
        default=None,
        description="自动转存下载到本地文件系统的相对/绝对路径"
    )
    duration: Optional[float] = Field(
        default=None,
        description="生成的视频实际时长 (秒)"
    )
    error_msg: Optional[str] = Field(
        default=None,
        description="轮询发现失败时的具体错误原因描述"
    )
    raw_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="模型厂商轮询接口返回的原始数据字典"
    )


# =====================================================================
# 4. 音乐/音频生成契约 (Music Generation Options & Results)
# =====================================================================

class MusicGenerationOptions(BaseModel):
    """音乐与配乐生成统一入参选项契约。"""
    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(
        default="",
        description="音乐风格、乐器配置、情感走势与旋律描述提示词"
    )
    style: Optional[str] = Field(
        default=None,
        description="音乐风格流派（如: 史诗管弦、暗黑悬疑、快节奏电子、古风仙侠）"
    )
    mood: Optional[str] = Field(
        default=None,
        description="情绪氛围基调（如: 紧迫紧张、热血沸腾、悲壮凄凉、轻快喜悦）"
    )
    title: Optional[str] = Field(
        default="",
        description="生成的曲目自定义标题"
    )
    bpm: Optional[int] = Field(
        default=None,
        description="目标节拍速度 BPM (Beats Per Minute)"
    )
    duration_seconds: Optional[int] = Field(
        default=30,
        description="生成目标音频时长 (秒)"
    )
    instrumental: bool = Field(
        default=True,
        description="是否纯器乐伴奏（True 为纯音乐无真人人声演唱）"
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="风格与配器标签列表"
    )
    reference_audio_url: Optional[str] = Field(
        default=None,
        description="用于参考音色或曲风风格的参考音频 URL"
    )
    extra_options: dict[str, Any] = Field(
        default_factory=dict,
        description="厂商专有底层音频生成参数"
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="AI 服务凭据与配置信息"
    )


class MusicGenerationResult(BaseModel):
    """音乐与配乐生成统一出参结果契约。"""
    model_config = ConfigDict(populate_by_name=True)

    audio_url: Optional[str] = Field(
        default=None,
        description="生成的音频文件在线播放 URL"
    )
    local_path: Optional[str] = Field(
        default=None,
        description="下载保存到本地文件系统的文件路径"
    )
    title: Optional[str] = Field(
        default=None,
        description="音频曲目标题"
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        description="音频实际播放时长 (秒)"
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="厂商返回或提取的音乐风格标签列表"
    )
    error: Optional[str] = Field(
        default=None,
        description="生成失败时的错误原因信息"
    )
    raw_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="模型厂商原始返回结果"
    )


__all__ = [
    "TaskExecutionStatus",
    "ImageGenerationOptions",
    "ImageGenerationResult",
    "VideoGenerationOptions",
    "VideoTaskResult",
    "VideoPollResult",
    "MusicGenerationOptions",
    "MusicGenerationResult",
]
