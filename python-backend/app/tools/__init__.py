"""确定性纯函数工具箱 (Deterministic Pure Function Tools Package)。

对齐《AI 原创连续剧短剧工业管线标准作业程序 (SKILL1.md v10.0.0)》：
- screenplay_feature_scanner: 剧本多维特征逆向扫描识别引擎 (Stage 6)
- shot_duration_calculator: 复合时序单镜整秒时长倒逼与自适应拆镜算子 (Stage 7)
- audio_mastering_engine: 多轨智能音频混音调度与毫秒级 SRT 排版引擎 (Stage 7 & Stage 8)
"""

from app.tools.screenplay_feature_scanner import (
    scan_screenplay_features,
    ScreenplayScanResult,
)
from app.tools.shot_duration_calculator import (
    calculate_shot_duration,
    check_episode_duration_tolerance,
    format_timecode_ms,
    format_timecode_range,
    ShotDurationResult,
)
from app.tools.audio_mastering_engine import (
    generate_srt_content,
    generate_mastering_schedule,
    generate_bgm_master_prompt,
    get_nle_mixing_guidelines,
)


class ScreenplayFeatureScanner:
    """剧本多维特征逆向扫描识别类门面。"""
    scan = staticmethod(scan_screenplay_features)


class ShotDurationCalculator:
    """镜头整秒时长倒逼与自适应拆镜算子类门面。"""
    calculate = staticmethod(calculate_shot_duration)
    check_tolerance = staticmethod(check_episode_duration_tolerance)
    format_ms = staticmethod(format_timecode_ms)
    format_range = staticmethod(format_timecode_range)


class AudioMasteringEngine:
    """多轨智能混音工程与毫秒级 SRT 算子类门面。"""
    generate_srt = staticmethod(generate_srt_content)
    generate_schedule = staticmethod(generate_mastering_schedule)
    generate_bgm_prompt = staticmethod(generate_bgm_master_prompt)
    get_guidelines = staticmethod(get_nle_mixing_guidelines)


__all__ = [
    "scan_screenplay_features",
    "ScreenplayScanResult",
    "ScreenplayFeatureScanner",
    "calculate_shot_duration",
    "check_episode_duration_tolerance",
    "format_timecode_ms",
    "format_timecode_range",
    "ShotDurationResult",
    "ShotDurationCalculator",
    "generate_srt_content",
    "generate_mastering_schedule",
    "generate_bgm_master_prompt",
    "get_nle_mixing_guidelines",
    "AudioMasteringEngine",
]
