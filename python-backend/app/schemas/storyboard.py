"""分镜与视听生成提示词 Schema (StoryboardShot, VisualPrompt, VideoPrompt)。

用于标准化分镜脚本、首尾关键帧文生图 Prompt 与图生视频运镜 Prompt。
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class VisualPrompt(BaseModel):
    """文生图生图提示词模型。"""
    prompt: str = Field(..., description="正向生图提示词（包含主体、动作、环境、光影、镜头构图）")
    negative_prompt: str = Field(
        default="ugly, deformed, disfigured, poor quality, bad anatomy, blurry, watermark",
        description="负向过滤提示词"
    )
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:3", "3:4"] = Field(
        default="9:16", description="画面画幅比例（短剧默认 9:16 竖屏）"
    )
    style_preset: str = Field(default="realistic", description="画面风格预设（realistic, anime, cinematic 等）")
    referenced_character_names: list[str] = Field(default_factory=list, description="本画面出现的角色姓名列表")
    referenced_scene_name: str = Field(default="", description="本画面引用的场景名称")
    reference_image_urls: list[str] = Field(default_factory=list, description="垫图/参考图列表（用于 IP-Adapter / ControlNet）")
    model_preference: str = Field(default="", description="推荐生图模型（如 FLUX, Midjourney, SDXL, 即梦）")


class VideoPrompt(BaseModel):
    """图生视频运镜与动态生成提示词模型。"""
    prompt: str = Field(..., description="动态动作与运镜描述（如：角色猛然抬头冷笑，眼神充满杀气，镜头迅速向前推近特写）")
    camera_movement: Literal[
        "static", "push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "tracking", "orbit", "zoom_reversal"
    ] = Field(default="push_in", description="运镜方式：静态微动、推镜、拉镜、左摇、右摇、上仰、下俯、跟镜头、环绕、希区柯克变焦")
    motion_intensity: int = Field(default=5, ge=1, le=10, description="动作与动态幅度等级（1-10，5为标准）")
    duration_seconds: float = Field(default=5.0, ge=2.0, le=15.0, description="视频生成目标时长（秒）")
    has_last_frame: bool = Field(default=False, description="是否使用首尾帧（首尾帧插值模式）")
    last_frame_prompt: str = Field(default="", description="尾帧预期状态描述（若启用首尾帧）")
    model_preference: str = Field(default="", description="推荐视频模型（如 Runway Gen3, Kling, CogVideo, Sora, Minimax, 即梦）")


class StoryboardShot(BaseModel):
    """单条分镜镜头数据模型 (Storyboard Shot)。"""
    shot_index: int = Field(..., description="分镜在当前场次/集中的序号（从1开始）")
    scene_number: int = Field(default=1, description="所属剧本场次编号")
    shot_type: Literal[
        "extreme_close_up", "close_up", "medium_close_up", "medium_shot", "medium_full_shot", "full_shot", "long_shot", "over_the_shoulder"
    ] = Field(default="medium_shot", description="景别：大特写、特写、中特写、中景、中全景、全景、远景、过肩镜头")
    camera_angle: Literal["eye_level", "low_angle", "high_angle", "dutch_angle", "birds_eye"] = Field(
        default="eye_level", description="拍摄角度：平视、仰角（凸显压迫感）、俯角、倾斜荷兰角、鸟瞰"
    )
    visual_action: str = Field(..., description="分镜画面动作与视觉调度核心内容")
    visual_prompt: VisualPrompt = Field(..., description="对应首帧/关键帧的生图 Prompt 结构")
    video_prompt: VideoPrompt = Field(..., description="对应的图生视频 Prompt 结构")
    dialogue_or_narration: str = Field(default="", description="当前镜头同步播放的台词或旁白文本")
    speaker: str = Field(default="", description="说话角色（空表示无台词或旁白）")
    sound_effect_cue: str = Field(default="", description="音效提示（如：重拳击打声、豪车轰鸣声、心跳急促音）")
    bgm_cue: str = Field(default="", description="背景音乐情绪点（如：悬疑提琴骤响、情绪爆发强音）")
    estimated_duration_seconds: float = Field(default=4.0, ge=1.0, le=30.0, description="预估分镜时长（秒）")
    status: Literal["draft", "image_ready", "video_ready", "completed", "failed"] = Field(
        default="draft", description="分镜当前生产状态"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="其他扩展数据")
