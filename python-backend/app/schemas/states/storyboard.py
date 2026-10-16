# -*- coding: utf-8 -*-
"""分镜头脚本、音画同步与视觉资产契约。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.storyboard")

from app.schemas.states.audio import ShotAudioConfig


class LipsyncDynamics(BaseModel):
    """阶段 7 口型动力学与微表情参数。"""
    model_config = ConfigDict(extra="allow")
    speaker: str = Field(default="", description="说话角色")
    jaw_open_scale: float = Field(default=0.6, description="下颌开度比例 (0.0~1.0)")
    mouth_tension: str = Field(default="", description="嘴角张力描述")
    head_subtle_motion: str = Field(default="", description="头部微动描述")

    @property
    def jaw_open(self) -> float:
        return self.jaw_open_scale

    @jaw_open.setter
    def jaw_open(self, value: float) -> None:
        self.jaw_open_scale = value

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class StoryboardShot(BaseModel):
    """阶段 7：单镜头工业执行表单项契约（对齐单帧图像生成与音视频动态指令）。"""
    model_config = ConfigDict(extra="allow")
    shot_id: int = Field(..., description="镜号")
    timecode: str = Field(default="00:00:00,000 --> 00:00:02,500", description="时间码（如：00:00:00,000 --> 00:00:02,500）")
    duration_sec: float = Field(default=3.0, description="单镜时长（严格整秒 2.0, 3.0, 4.0, 5.0, 6.0, 7.0）")
    framing: str = Field(default="MCU 中近景", description="景别")
    camera_motion: str = Field(default="Static", description="运镜方式（推/拉/摇/移/跟随/升降/静止）")
    image_prompt: str = Field(default="", description="单帧视觉画面生图提示词 (Prompt)")
    video_prompt: str = Field(default="", description="视频运动与动态演变提示词")
    generation_mode: str = Field(
        default="single_frame_dynamic",
        description="分镜生成模式：single_frame_dynamic(单帧图像+运镜), first_last_frame(首尾帧), multi_image_reference(多图参考)"
    )
    character_asset_ids: list[str] = Field(default_factory=list, description="本镜头涉及的角色资产ID列表")
    scene_asset_id: str = Field(default="", description="本镜头涉及的场景资产ID")
    prop_asset_ids: list[str] = Field(default_factory=list, description="本镜头涉及的道具资产ID列表")
    srt_text: str = Field(default="", description="对白/旁白字幕文本")
    srt_timing: str = Field(default="", description="字幕精准时间戳（如 00:00:00,200 --> 00:00:02,100）")
    dynamic_cue: str = Field(default="", description="镜头动态与视听动效指令")
    music_cue: str = Field(default="", description="背景音乐动机与情绪标签")
    foley_cue: str = Field(default="", description="拟音/物理音效指令 (+3dB 规范)")
    selection_rationale: str = Field(default="", description="选型依据决策解释")
    first_last_config: dict[str, Any] | None = Field(default=None, description="首尾帧配置（向下兼容）")
    multi_image_config: dict[str, Any] | None = Field(default=None, description="多图参考配置（向下兼容）")
    audio: dict[str, Any] = Field(default_factory=dict, description="全息声学提示词（对白/旁白/拟音Foley/TTS腔体共鸣/闭环状态）")
    lipsync_dynamics: LipsyncDynamics | dict[str, Any] | None = Field(default=None, description="口型动力学（下颌开度jaw_open_scale/嘴角张力/头部微动）")

    target_engine: str | None = Field(default="wan3.0", description="目标生成模型 (wan3.0/seedance2.5/minimax_h3)")
    rationale: str = Field(default="", description="算子1+2景别与时长累加推导依据")
    first_last_frame_config: dict[str, Any] | None = Field(default=None, description="首尾帧Prompt配置")
    speech_inpoint_sec: float | None = Field(default=None, description="台词入点时间码偏移秒数")
    contextual_tts_prompt: str | None = Field(default="", description="腔体与情绪 TTS 提示词")
    is_dialogue_complete_in_shot: bool = Field(default=True, description="台词是否在镜头内完整闭环说完")

    # 大对象外挂指针（严禁在 State 中内嵌 Base64，通过 URI / local_path 关联）
    image_url: str = Field(default="", description="单帧画面或首帧图像存储 URL/URI（大对象外挂）")
    local_path: str = Field(default="", description="单帧画面或首帧图像本地持久化路径")
    video_url: str = Field(default="", description="生成的视频切片存储 URL/URI（大对象外挂）")
    video_local_path: str = Field(default="", description="生成的视频切片本地持久化路径")
    audio_url: str = Field(default="", description="合成音频/TTS 存储 URL/URI")

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (bool(self.model_extra) and key in self.model_extra)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "StoryboardShot":
        if isinstance(obj, dict):
            obj = dict(obj)
            # 兼容字段别名 (Framing / Camera Motion / Mode / Duration)
            if "shot_type" in obj and "framing" not in obj:
                obj["framing"] = obj["shot_type"]
            if "camera_movement" in obj and "camera_motion" not in obj:
                obj["camera_motion"] = obj["camera_movement"]
            elif "movement" in obj and "camera_motion" not in obj:
                obj["camera_motion"] = obj["movement"]
            if "mode" in obj and "generation_mode" not in obj:
                obj["generation_mode"] = obj["mode"]
            elif "creation_mode" in obj and "generation_mode" not in obj:
                obj["generation_mode"] = obj["creation_mode"]
            if "duration_seconds" in obj and "duration_sec" not in obj:
                obj["duration_sec"] = obj["duration_seconds"]
            elif "duration" in obj and "duration_sec" not in obj:
                obj["duration_sec"] = obj["duration"]

            if "lipsync_dynamics" in obj and isinstance(obj["lipsync_dynamics"], dict):
                dyn = dict(obj["lipsync_dynamics"])
                if "jaw_open" in dyn and "jaw_open_scale" not in dyn:
                    dyn["jaw_open_scale"] = dyn["jaw_open"]
                obj["lipsync_dynamics"] = LipsyncDynamics.model_validate(dyn)
            if "first_last_config" in obj and "first_last_frame_config" not in obj:
                obj["first_last_frame_config"] = obj["first_last_config"]
            elif "first_last_frame_config" in obj and "first_last_config" not in obj:
                obj["first_last_config"] = obj["first_last_frame_config"]
            if "multi_image_config" in obj and isinstance(obj["multi_image_config"], dict):
                mic = dict(obj["multi_image_config"])
                if "reference_assets" in mic and "reference_asset_ids" not in mic:
                    mic["reference_asset_ids"] = mic["reference_assets"]
                elif "reference_asset_ids" in mic and "reference_assets" not in mic:
                    mic["reference_assets"] = mic["reference_asset_ids"]
                obj["multi_image_config"] = mic
            audio_data = obj.get("audio")
            if isinstance(audio_data, dict):
                audio_dict = dict(audio_data)
                if "is_dialogue_complete_in_shot" in audio_dict:
                    obj.setdefault("is_dialogue_complete_in_shot", audio_dict["is_dialogue_complete_in_shot"])
                elif "is_dialogue_complete_in_shot" in obj:
                    audio_dict["is_dialogue_complete_in_shot"] = obj["is_dialogue_complete_in_shot"]
                if "speech_inpoint_sec" in audio_dict:
                    obj.setdefault("speech_inpoint_sec", audio_dict["speech_inpoint_sec"])
                elif "speech_inpoint_sec" in obj:
                    audio_dict["speech_inpoint_sec"] = obj["speech_inpoint_sec"]
                if "contextual_tts_prompt" in audio_dict:
                    obj.setdefault("contextual_tts_prompt", audio_dict["contextual_tts_prompt"])
                elif "contextual_tts_prompt" in obj:
                    audio_dict["contextual_tts_prompt"] = obj["contextual_tts_prompt"]
                obj["audio"] = audio_dict
        return super().model_validate(obj, *args, **kwargs)

    @property
    def shot_number(self) -> int:
        """向下兼容 StoryboardShotStub 的 shot_number 属性。"""
        if self.model_extra and "shot_number" in self.model_extra:
            return int(self.model_extra["shot_number"] or self.shot_id)
        return self.shot_id

    @property
    def visual_description(self) -> str:
        """向下兼容 StoryboardShotStub 的 visual_description 属性。"""
        if self.model_extra and self.model_extra.get("visual_description"):
            return str(self.model_extra["visual_description"])
        return self.image_prompt

    @property
    def dialogue_text(self) -> str:
        """向下兼容 StoryboardShotStub 的 dialogue_text 属性。"""
        if self.model_extra and self.model_extra.get("dialogue_text"):
            return str(self.model_extra["dialogue_text"])
        return self.srt_text

    @property
    def keyframe_image_ref(self) -> str:
        """向下兼容 StoryboardShotStub 的 keyframe_image_ref 属性。"""
        if self.model_extra and self.model_extra.get("keyframe_image_ref"):
            return str(self.model_extra["keyframe_image_ref"])
        return self.image_url or self.image_prompt


class StoryboardShotStub(BaseModel):
    """【轻量分镜桩】单镜头轻量索引（仅保留机位元数据与资产 URI 指针，严禁内联 Base64）。"""
    model_config = ConfigDict(extra="allow")
    shot_id: int = Field(description="镜头序号 (1..NN)")
    shot_type: str = Field(default="特写", description="景别机位")
    camera_movement: str = Field(default="慢速推进", description="运镜方式")
    duration_sec: float = Field(default=3.0, description="镜头时长秒数")
    screen_description: str = Field(default="", description="画面内容与视觉描述")
    image_uri: str = Field(default="", description="外挂图像存储 URI 指针 (如 storage://ep01/shot_03.png)")
    audio_summary: str = Field(default="", description="对白及声效配置摘要")


class FirstLastFrameConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 模式 A 首尾帧 Prompt 配置。"""
    first_frame_asset_ref: str
    first_frame_asset_id: str
    first_frame_prompt: str
    last_frame_asset_ref: str
    last_frame_asset_id: str
    last_frame_prompt: str
    video_motion_prompt: str


class MediaImageItem(TypedDict, total=False):
    """【规则编号: RULE-VI-07】模式 B 多模态图片编号素材项。"""
    symbol: str  # 图1, 图2...
    asset_id: str
    role: str


class MediaAudioItem(TypedDict, total=False):
    """【规则编号: RULE-VI-07】模式 B 多模态音频编号素材项。"""
    symbol: str  # 音频1, 音频2...
    voice_id: str
    role: str


class MediaManifestDict(TypedDict, total=False):
    """【规则编号: RULE-VI-07】模式 B 先排后编多模态映射表。"""
    images: list[MediaImageItem]
    audios: list[MediaAudioItem]


class MultiImageReferenceConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 模式 B 多图参考配置。"""
    media_manifest: MediaManifestDict
    reference_assets: list[str]
    reference_asset_ids: list[str]
    video_prompt: str
    target_engine: str
    audit: Literal["PASS_9"] | str


class ModeBManifestCheckDict(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 模式 B 多图参考集末 9 项自审清单。"""
    episode_num: int
    total_mode_b_shots: int
    max_images_under_limit: bool
    scene_unique_and_first: bool
    character_numbered_from_two: bool
    audio_independent_order: bool
    spatial_constraint_front: bool
    temporal_order_forward: bool
    target_engine_compliant: bool
    no_forbidden_prompt_words: bool
    all_pass_9_signed: bool
    verdict: Literal["PASS", "FAIL"] | str
    issues: list[str]


class LipSyncDynamicsConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】离线口型动力学静默元数据。"""
    jaw_open_scale: float | None


class StoryboardShotDict(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 单镜头工业执行表单项字典 (sb_XX.json)。"""
    shot_id: int
    duration_sec: float  # 严格整秒 (2.0, 3.0, 4.0, 5.0, 6.0, 7.0)
    timecode: str  # HH:MM:SS,mmm --> HH:MM:SS,mmm
    rationale: str
    generation_mode: Literal["first_last_frame", "multi_image_reference"]
    selection_rationale: str
    target_engine: Literal["wan3.0", "seedance2.5", "minimax_h3"] | str
    first_last_frame_config: FirstLastFrameConfig | None
    multi_image_config: MultiImageReferenceConfig | None
    audio: ShotAudioConfig
    lipsync_dynamics: LipSyncDynamicsConfig | None


__all__ = [
    "LipsyncDynamics",
    "StoryboardShot",
    "StoryboardShotStub",
    "FirstLastFrameConfig",
    "MediaImageItem",
    "MediaAudioItem",
    "MediaManifestDict",
    "MultiImageReferenceConfig",
    "ModeBManifestCheckDict",
    "LipSyncDynamicsConfig",
    "StoryboardShotDict",
]
