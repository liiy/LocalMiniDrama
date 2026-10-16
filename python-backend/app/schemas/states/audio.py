# -*- coding: utf-8 -*-
"""音频圣经、声音动机与声音母带规范状态契约。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.audio")

from app.schemas.states.base import AssetState


class AudioMotifItem(BaseModel):
    """阶段 4：全剧核心音乐主题动机母库单项 (Leitmotif)。"""
    motif_id: str = Field(..., description="动机 ID，如 LEITMOTIF_01_SUSPENSE")
    leitmotif_id: str = Field(default="", description="标准契约别名")
    name: str = Field(..., description="主题动机名称（如：悬疑压迫与阶层窒息）")
    instrumentation: str = Field(default="", description="核心配器说明")
    tempo_bpm: str = Field(default="86", description="速度区间与节拍")
    musical_key: str = Field(default="D minor", description="调性")
    dramatic_function: str = Field(default="", description="戏剧功能定位与触发场景")

    @model_validator(mode="before")
    @classmethod
    def _coerce_motif_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            m_id = data.get("motif_id") or data.get("leitmotif_id") or ""
            if m_id:
                data["motif_id"] = m_id
                data["leitmotif_id"] = m_id
        return data


class AudioBible(BaseModel):
    """阶段 4 长期资产：全剧音乐动机母库 (04_audio_bible.json)。"""
    leitmotifs: list[AudioMotifItem] = Field(default_factory=list, description="全剧 3 个贯穿始终的具象音乐主题动机")
    leitmotif_registry: list[AudioMotifItem] = Field(default_factory=list, description="标准契约别名")
    foley_rules: dict[str, str] = Field(
        default_factory=lambda: {"boost": "+2.0dB ~ +3.0dB", "clarity": "-23 LUFS"},
        description="拟音放大与混音规范"
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_registry(cls, data: Any) -> Any:
        if isinstance(data, dict):
            motifs = data.get("leitmotif_registry") or data.get("leitmotifs") or []
            data["leitmotifs"] = motifs
            data["leitmotif_registry"] = motifs
        return data

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


class MasterVoiceCardModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 角色母音频卡片模型 (V2 精细化)。"""
    model_config = ConfigDict(extra="allow")

    character_id: str = Field(..., description="角色唯一ID (如 CHAR_LINWAN)")
    character_code: str = Field(default="", description="角色唯一标准编码 (如 CHAR_LINWAN)")
    character_name: str = Field(default="", description="角色标准姓名")
    master_voice_id: str = Field(..., description="母音频唯一标识 (如 VOICE_LINWAN_T1_MASTER)")
    timbre: str = Field(default="", description="音色定位描述")
    timbre_archetype: str = Field(default="deep_baritone_gravel", description="标准音色枚举原型 (防撞音色分配依据)")
    vocal_position: str = Field(default="", description="发声共鸣腔体位置")
    vocal_flaws: str = Field(default="", description="声带颗粒度与气泡音特征")
    speed_ratio: float = Field(default=1.0, description="基准语速比例")
    pitch_ratio: float = Field(default=1.0, description="基准音高比例")
    voice_prompt: str = Field(default="", description="中文 TTS 声音生成提示词")
    master_tts_prompt: str = Field(default="", description="英文跨平台 TTS 提示词")
    master_sample_text: str = Field(default="", description="25~48字剥离括号动作的纯净干声试音台本")
    script_monologue_source: str = Field(default="", description="从文学剧本抓取的灵魂示范台词（含发声括注）")
    tts_provider: str = Field(default="minimax", description="TTS 引擎供应商")
    tts_model: str = Field(default="speech-02-hd", description="TTS 合成模型名")
    provider_voice_id: str = Field(default="", description="底层引擎预设或克隆音色 ID")
    timber_weights: list[dict[str, Any]] = Field(default_factory=list, description="多音色混合捏脸权重列表")
    emotion_rules: dict[str, Any] = Field(default_factory=dict, description="纯净6维戏剧状态声学偏移矩阵")
    voice_file_path: str = Field(default="", description="标准音频路径 (storage/audio/voices/VOICE_[ID]_T1_MASTER.mp3)")
    lifecycle_status: AssetState | str = Field(default=AssetState.READY, description="母音频生命周期状态")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


class AcousticTraceability(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 四大依据溯源契约。"""
    model_config = ConfigDict(extra="allow")
    stage_4_leitmotif_basis: str = Field(default="", description="阶段 4 主题音乐动机依据 (A/B/C)")
    stage_1_worldview_basis: str = Field(default="", description="阶段 1 世界观与题材风格依据")
    stage_7_timecode_basis: str = Field(default="", description="阶段 7 镜头总时长与台词入点时间码依据")
    stage_5_dramatic_cues: str = Field(default="", description="阶段 5 开篇动作/45s断崖/集尾断钩戏剧点依据")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class BgmGenerationConfig(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 动态生乐 Prompt 契约。"""
    model_config = ConfigDict(extra="allow")
    full_master_prompt: str = Field(default="", description="Suno/Udio 动态生乐全量 Prompt (包含 T_actual 绝对秒数与淡出硬切)")
    planned_duration_sec: float = Field(default=120.0, description="实际总时长 T_actual")
    bpm: int = Field(default=85, description="节奏速度 (BPM)")
    musical_key: str = Field(default="D minor", description="调性")
    leitmotif_name: str = Field(default="", description="动机标识")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class MasteringScheduleItemModel(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 精准分贝避让调度表单项。"""
    model_config = ConfigDict(extra="allow")
    time_start_sec: float = Field(default=0.0, description="开始秒数")
    time_end_sec: float = Field(default=0.0, description="结束秒数")
    timecode_range: str = Field(default="", description="时间码区间 (如 00:00:00,000 --> 00:00:02,500)")
    target_bgm_volume_db: float = Field(default=-12.0, description="目标 BGM 音量 (动作 -12.0dB, 对白避让 -20.0dB, 断崖静音 -999.0dB)")
    speech_ducking_active: bool = Field(default=False, description="是否激活侧链对白避让")
    event_description: str = Field(default="", description="声学事件描述")
    action_type: str = Field(default="", description="动作类别 (action_intro/speech_ducking/cliffhanger_silence/fade_out_stop)")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "MasteringScheduleItemModel":
        if isinstance(obj, dict):
            obj = dict(obj)
            if "start_sec" in obj and "time_start_sec" not in obj:
                obj["time_start_sec"] = obj["start_sec"]
            if "end_sec" in obj and "time_end_sec" not in obj:
                obj["time_end_sec"] = obj["end_sec"]
            if "gain_db" in obj and "target_bgm_volume_db" not in obj:
                obj["target_bgm_volume_db"] = obj["gain_db"]
            if "description" in obj and "event_description" not in obj:
                obj["event_description"] = obj["description"]
        return super().model_validate(obj, *args, **kwargs)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class NleMixingGuidelines(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 NLE 剪辑软件多轨混音导入参数指南。"""
    model_config = ConfigDict(extra="allow")
    broadcast_loudness_standard: str = Field(default="-23 LUFS", description="广播级响度标准")
    sampling_rate: str = Field(default="48kHz", description="采样率")
    bit_depth: str = Field(default="24-bit", description="位深")
    peak_db: float = Field(default=-1.0, description="真峰值限制 (dBTP)")
    peak_limit_dbtp: float = Field(default=-1.0, description="真峰值限制 (dBTP)")
    integrated_lufs: float = Field(default=-23.0, description="综合响度标准 (LUFS)")
    track_a1_dialogue: str | dict[str, Any] = Field(default="0.0dB, 压缩比 3:1, -23 LUFS 标准", description="Track A1 对白轨参数")
    track_a2_foley: str | dict[str, Any] = Field(default="+3.0dB, 80Hz 高通滤波", description="Track A2 拟音轨参数")
    track_a3_bgm: str | dict[str, Any] = Field(default="动作区 -12.0dB, 对白区 -20.0dB Ducking 避让, 45s断崖静音 -999.0dB", description="Track A3 BGM 轨参数")
    track_v1_video: str | dict[str, Any] = Field(default="V1 视频切片, V2 SRT 字幕文本", description="Track V1/V2 视频与字幕")
    tracks: dict[str, Any] = Field(default_factory=dict, description="轨道详细参数字典")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class AudioMasteringConfig(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 单集多轨智能音频工程与混音调度模型。"""
    model_config = ConfigDict(extra="allow")
    broadcast_loudness_standard: str = Field(default="-23 LUFS", description="广播级响度标准 (固定锁定 -23 LUFS)")
    target_lufs: float = Field(default=-23.0, description="目标响度数值 (-23.0)")
    peak_limit_dbtp: float = Field(default=-1.0, description="真峰值限制 (-1.0 dBTP)")
    acoustic_traceability: AcousticTraceability = Field(default_factory=AcousticTraceability, description="四大依据溯源")
    bgm_generation: BgmGenerationConfig = Field(default_factory=BgmGenerationConfig, description="BGM 动态生乐 Prompt 配置")
    mastering_schedule: list[MasteringScheduleItemModel] = Field(default_factory=list, description="精准分贝避让调度表")
    nle_mixing_guidelines: NleMixingGuidelines | dict[str, Any] = Field(default_factory=NleMixingGuidelines, description="NLE 多轨参数指南")
    ducking_strategy: dict[str, Any] = Field(default_factory=dict, description="侧链避让策略")
    ducking_events: list[dict[str, Any]] = Field(default_factory=list, description="侧链避让事件列表")
    foley_boost_tracks: list[dict[str, Any]] = Field(default_factory=list, description="拟音高光增强列表 (+3.0dB)")
    tracks: list[dict[str, Any]] = Field(default_factory=list, description="多轨总线参数")
    full_srt_content: str = Field(default="", description="毫秒级广播级 SRT 内容")
    actual_duration_sec: float = Field(default=120.0, description="阶段 7 实际总秒数 T_actual")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "AudioMasteringConfig":
        if isinstance(obj, dict):
            obj = dict(obj)
            # 自动提取或推导 broadcast_loudness_standard / target_lufs
            if "broadcast_loudness_standard" not in obj or not obj["broadcast_loudness_standard"]:
                obj["broadcast_loudness_standard"] = "-23 LUFS"
            if "target_lufs" not in obj:
                obj["target_lufs"] = -23.0
            if "peak_limit_dbtp" not in obj:
                obj["peak_limit_dbtp"] = -1.0
            if "acoustic_traceability" in obj and isinstance(obj["acoustic_traceability"], dict):
                obj["acoustic_traceability"] = AcousticTraceability.model_validate(obj["acoustic_traceability"])
            if "bgm_generation" in obj and isinstance(obj["bgm_generation"], dict):
                obj["bgm_generation"] = BgmGenerationConfig.model_validate(obj["bgm_generation"])
            if "mastering_schedule" in obj and isinstance(obj["mastering_schedule"], list):
                obj["mastering_schedule"] = [
                    MasteringScheduleItemModel.model_validate(item) if isinstance(item, dict) else item
                    for item in obj["mastering_schedule"]
                ]
            if "nle_mixing_guidelines" in obj and isinstance(obj["nle_mixing_guidelines"], dict):
                obj["nle_mixing_guidelines"] = NleMixingGuidelines.model_validate(obj["nle_mixing_guidelines"])
        return super().model_validate(obj, *args, **kwargs)

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


class AudioBibleSummary(BaseModel):
    """【轻量全局锚点】音乐母法典概要索引。"""
    model_config = ConfigDict(extra="allow")
    overall_style: str = Field(default="悬疑反转/重型低频", description="全剧整体声学基调")
    leitmotif_registry: list[dict[str, Any]] = Field(default_factory=list, description="主导动机简表 (包含 motif_id, name, tempo_bpm, musical_key)")
    leitmotifs: list[dict[str, Any]] = Field(default_factory=list, description="主导动机别名列表")
    leitmotif_names: list[str] = Field(default_factory=list, description="动机名称索引列表")
    foley_rules_count: int = Field(default=0, description="拟音规则数量")
    theme_prompt: str = Field(default="", description="主旋律 Prompt")

    @model_validator(mode="before")
    @classmethod
    def _normalize_leitmotifs(cls, values: Any) -> Any:
        if isinstance(values, dict):
            reg = values.get("leitmotif_registry")
            motifs = values.get("leitmotifs")
            if reg and not motifs:
                values["leitmotifs"] = reg
            elif motifs and not reg:
                values["leitmotif_registry"] = motifs
        return values

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        return self.__dict__.get(item)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item) or item in self.__dict__

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class AudioMotifItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-04】阶段 4 音乐主题动机母库项。"""
    motif_id: str
    leitmotif_id: str
    name: str
    instrumentation: str
    tempo_bpm: str
    musical_key: str
    dramatic_function: str


class AudioBibleDict(TypedDict, total=False):
    """【规则编号: RULE-VI-04】阶段 4 音乐动机母库 (04_audio_bible.json)。"""
    leitmotifs: list[AudioMotifItemDict]
    leitmotif_registry: list[AudioMotifItemDict]
    foley_rules: dict[str, str]


class MasterVoiceCardItem(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 角色母音频卡片项。"""
    character_id: str
    master_voice_id: str
    script_monologue_source: str
    master_tts_prompt: str
    voice_file_path: str


class ShotAudioConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】单镜全息声音配置。"""
    voice_type: str | None
    speech_inpoint_sec: float | None
    is_dialogue_complete_in_shot: bool
    contextual_tts_prompt: str | None


class MasteringScheduleItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-08】阶段 8 精准分贝避让调度表单项。"""
    time_start_sec: float
    time_end_sec: float
    timecode_range: str
    target_bgm_volume_db: float  # -12.0, -20.0, -999.0
    speech_ducking_active: bool
    event_description: str


class EpisodeAudioSpecDict(TypedDict, total=False):
    """【规则编号: RULE-VI-08】阶段 8 结构化音频工程规范字典 (ep_XX_audio_spec.json)。"""
    audio_specs: dict[str, str]
    acoustic_traceability: dict[str, str]
    bgm_generation: dict[str, Any]
    mastering_schedule: list[MasteringScheduleItemDict]
    nle_mixing_guidelines: dict[str, Any]


EpisodeAudioMasteringPlan = AudioMasteringConfig


__all__ = [
    "AudioMotifItem",
    "AudioBible",
    "MasterVoiceCardModel",
    "AcousticTraceability",
    "BgmGenerationConfig",
    "MasteringScheduleItemModel",
    "NleMixingGuidelines",
    "AudioMasteringConfig",
    "AudioBibleSummary",
    "AudioMotifItemDict",
    "AudioBibleDict",
    "MasterVoiceCardItem",
    "ShotAudioConfig",
    "MasteringScheduleItemDict",
    "EpisodeAudioSpecDict",
    "EpisodeAudioMasteringPlan",
]
