"""声音与音乐系统 Schema (VoiceProfile, MusicBible, MusicCue)。

用于管理角色声音跨集一致性、整剧音乐基调（Music Bible）与单分镜/单场景音效及 BGM 提示。
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class VoiceProfile(BaseModel):
    """角色声音档案 (Voice Profile)。

    根据角色人设生成，确保跨集配音的一致性与辨识度。
    """
    character_name: str = Field(..., description="对应角色名称")
    timbre_description: str = Field(
        ..., description="音色与质感特征（如：低沉磁性、冷硬威严、温润如玉、娇媚狠戾、沙哑阴冷）"
    )
    gender_age_category: str = Field(default="青年男性", description="声音性别与年龄段属性")
    speaking_speed_ratio: float = Field(default=1.0, ge=0.5, le=2.0, description="默认语速倍率（1.0 为正常，快节奏通常 1.1~1.2）")
    pitch_adjustment: float = Field(default=1.0, ge=0.5, le=1.5, description="音调微调比例")
    emotional_range: list[str] = Field(
        default_factory=list,
        description="角色典型情绪表达范围（如：冷酷戏谑、暴怒咆哮、压抑哽咽）"
    )
    dialogue_style_rules: str = Field(
        default="咬字清晰短促，句尾微沉，充满压迫感", description="台词发音与停顿风格规范"
    )
    tts_provider: str = Field(default="volcengine", description="推荐 TTS 语音供应商（如 volcengine, azure, openai, cosyvoice, fish_audio）")
    voice_id: str = Field(default="", description="供应商预设或克隆语音 ID / Voice ID")
    reference_audio_url: str = Field(default="", description="声音音色参考试听音频 URL")
    negative_voice_traits: list[str] = Field(
        default_factory=lambda: ["机械电音感", "语调平淡无起伏", "过度油腻"],
        description="声音生成需避免的负面特征"
    )


class MusicBible(BaseModel):
    """整剧音乐设计圣经 (Music Bible)。

    统筹整部短剧的配乐风格、配器方向、节奏区间与主题动机。
    """
    overall_music_genre: str = Field(
        default="现代影视管弦 + 悬疑张力电子", description="全剧整体配乐风格类型"
    )
    lead_instruments: list[str] = Field(
        default_factory=lambda: ["大提琴", "重低音合成器 (Sub Bass)", "弦乐急促重奏", "冲击重音打击乐 (Hits/Braams)"],
        description="主导核心乐器与音色配置"
    )
    tempo_bpm_range: str = Field(default="90 - 135 BPM", description="音乐节奏速度区间")
    theme_leitmotifs: dict[str, str] = Field(
        default_factory=dict,
        description="核心角色或主题动机配乐描述（如：主角归来时使用激昂电吉他重奏）"
    )
    emotional_palette: list[str] = Field(
        default_factory=lambda: ["紧迫压抑", "高潮逆袭", "悬疑密谋", "温情释怀", "绝望反噬"],
        description="核心情绪标签库"
    )
    mixing_rules: str = Field(
        default="BGM 音量严格控制在对白音量 -14dB 以下，冲突高潮点随台词停顿释放爆发",
        description="对白与 BGM 基础混音规则"
    )


class MusicCue(BaseModel):
    """单场景/单分镜音乐与音效提示 (Music & SFX Cue)。"""
    cue_id: str = Field(default="", description="Cue 标识符")
    scene_number: int = Field(default=1, description="关联场次编号")
    shot_index: int | None = Field(default=None, description="关联具体分镜序号（若针对特定镜头）")
    timing_offset_seconds: float = Field(default=0.0, ge=0.0, description="在场次/镜头中的起播时间偏移（秒）")
    emotion_category: str = Field(default="紧张", description="情绪类型标签")
    bgm_prompt: str = Field(..., description="BGM 音乐风格/提示描述（如：急促提琴拉弦骤起，充满命悬一线的压迫感）")
    sfx_prompt: str = Field(default="", description="关键音效描述（如：耳光爆裂击打声、豪车急速刹车摩擦声、心电图蜂鸣声）")
    target_volume: float = Field(default=0.7, ge=0.0, le=1.0, description="目标混音音量 (0.0 - 1.0)")
    fade_in_seconds: float = Field(default=0.5, ge=0.0, description="淡入时长（秒）")
    fade_out_seconds: float = Field(default=1.0, ge=0.0, description="淡出时长（秒）")
