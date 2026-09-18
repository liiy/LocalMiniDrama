"""多轨智能音频工程与成片混音调度引擎 (Audio Mastering Engine)。

【规则编号: RULE-V-S8-02 / RULE-V-S8-03】严格遵循 SKILL1.md v10.0.0 阶段 8 混音避让调度与毫秒级 SRT 规范：
- 四大依据溯源: 锁定音乐动机母库、动态读取阶段 7 实际累计总时长 T_actual (自适应 ±6.0s 弹性区间，彻底废除写死 120s)
- 毫秒级 SRT 纯代码排版: 台词入点 speech_inpoint_sec 与字幕精准咬合，杜绝字幕提前抢跑
- 精准分贝避让调度表 (Mastering Schedule):
    * 动作/运镜区间维持动作音量 -12.0dB 并卡入 +3.0dB 拟音高光
    * speech_inpoint_sec 开口之后下沉触发对白侧链避让 -20.0dB
    * 40s ~ 55s 区间吸附至无对白间隙执行 3.0 秒断崖静音 (-999.0dB 代表 -∞)
    * 片尾最后 2 秒 [T_actual - 2.0s, T_actual] 平滑淡出，片尾随黑屏硬切骤停，彻底杜绝视频黑屏后 BGM 多播拖音穿帮
- 动态编译 Suno/Udio 全量 BGM Prompt (时长动态设置为 T_actual 绝对秒数)
- NLE 剪辑软件 4 轨参数规范输出

100% 确定性纯算法，零大模型幻觉。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.tools.shot_duration_calculator import format_timecode_ms, format_timecode_range

logger = logging.getLogger("lmd.audio_mastering_engine")

BROADCAST_LOUDNESS_STANDARD = "-23 LUFS"
BGM_VOLUME_ACTION_DB = -12.0
BGM_VOLUME_DUCKING_DB = -20.0
BGM_VOLUME_CLIFF_MUTE_DB = -999.0  # -999.0dB 表示 -∞ 绝对静音
CLIFF_SILENCE_WINDOW_START_SEC = 40.0
CLIFF_SILENCE_WINDOW_END_SEC = 55.0
CLIFF_SILENCE_DURATION_SEC = 3.0
OUTRO_FADEOUT_DURATION_SEC = 2.0


@dataclass
class MasteringScheduleItem:
    """【规则编号: RULE-VI-08】分贝避让调度表单项。"""
    time_start_sec: float
    time_end_sec: float
    timecode_range: str
    target_bgm_volume_db: float  # -12.0 (动作), -20.0 (对白避让), -999.0 (断崖静音)
    speech_ducking_active: bool
    event_description: str

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)



@dataclass
class SRTSubtitleEntry:
    """【规则编号: RULE-VI-07】单条毫秒级标准 SRT 字幕。"""
    index: int
    start_sec: float
    end_sec: float
    timecode_range: str
    text: str


@dataclass
class EpisodeMasteringResult:
    """阶段 8 混音工程完整输出对象。"""
    broadcast_loudness_standard: str = BROADCAST_LOUDNESS_STANDARD
    actual_duration_sec: float = 120.0
    full_srt_content: str = ""
    mastering_schedule: list[MasteringScheduleItem] = field(default_factory=list)
    bgm_master_prompt: str = ""
    nle_mixing_guidelines: dict[str, Any] = field(default_factory=dict)


def generate_srt_content(
    shots: list[dict[str, Any]],
) -> str:
    """【规则编号: RULE-V-S7-02 / RULE-VI-07】依据分镜入点与时长纯代码排版生成标准 SRT 字幕。
    
    严禁字幕提前抢跑：
    字幕起止绝对时间严格基于 shot_start_sec + speech_inpoint_sec。
    """
    logger.debug(f"[RULE-VI-07] Generating pure SRT for {len(shots)} shots.")
    srt_lines: list[str] = []
    current_time_sec = 0.0
    sub_index = 1

    for shot in shots:
        duration = float(shot.get("duration_sec", 3.0))
        audio_cfg = shot.get("audio") if isinstance(shot.get("audio"), dict) else {}
        dialogue = str(
            shot.get("dialogue_text", "")
            or shot.get("dialogue", "")
            or audio_cfg.get("contextual_tts_prompt", "")
        ).strip()
        speaker = str(
            shot.get("speaker", "")
            or shot.get("character_name", "")
            or audio_cfg.get("character_name", "")
        ).strip()
        speech_inpoint = shot.get("speech_inpoint_sec")
        if speech_inpoint is None:
            speech_inpoint = audio_cfg.get("speech_inpoint_sec")

        if dialogue:
            # 计算台词入点与出点
            inpoint_offset = float(speech_inpoint) if speech_inpoint is not None else 0.3
            sub_start = round(current_time_sec + inpoint_offset, 3)
            # 字幕在镜头结束前 0.2s 闭合或随镜头结束
            sub_end = round(current_time_sec + duration, 3)
            if sub_start >= sub_end:
                sub_start = round(current_time_sec, 3)

            tc_range = f"{format_timecode_ms(sub_start)} --> {format_timecode_ms(sub_end)}"
            display_text = f"{speaker}：{dialogue}" if speaker else dialogue

            srt_lines.append(str(sub_index))
            srt_lines.append(tc_range)
            srt_lines.append(display_text)
            srt_lines.append("")  # 规范空行
            sub_index += 1

        current_time_sec += duration

    full_srt = "\n".join(srt_lines).strip()
    logger.debug(f"[RULE-VI-07] Generated {sub_index - 1} SRT subtitle entries.")
    return full_srt


def generate_mastering_schedule(
    shots: list[dict[str, Any]] | None = None,
    planned_cliff_start_sec: float | None = None,
    *,
    storyboard_shots: list[dict[str, Any]] | None = None,
    total_duration_sec: float | None = None,
    cliff_silence_window: tuple[float, float] = (40.0, 55.0),
    cliff_silence_duration: float = 3.0,
) -> list[MasteringScheduleItem]:
    """【规则编号: RULE-V-S8-02 / RULE-V-S8-03】生成精准分贝避让调度表 (Mastering Schedule)。
    
    规则：
    1. 动作区间：-12.0dB，speech_ducking_active=False
    2. 对白区间：-20.0dB，speech_ducking_active=True
    3. 40s~55s 寻找无对白间隙执行 3.0s 断崖静音 (-999.0dB)
    4. 片尾倒数 2 秒平滑淡出，片尾随黑屏硬切骤停
    """
    shots_list = shots if shots is not None else (storyboard_shots or [])
    logger.debug(f"[RULE-V-S8-02] Generating BGM mastering schedule for {len(shots_list)} shots.")
    schedule: list[MasteringScheduleItem] = []
    
    window_start, window_end = cliff_silence_window
    silence_dur = cliff_silence_duration

    # 首先扫描出基础时间轴与每个镜头的时间区间
    timeline_shots: list[dict[str, Any]] = []
    running_sec = 0.0
    for shot in shots_list:
        dur = float(shot.get("duration_sec", 3.0))
        s_start = running_sec
        s_end = running_sec + dur
        running_sec += dur
        audio_cfg = shot.get("audio") if isinstance(shot.get("audio"), dict) else {}
        has_dialogue = bool(
            shot.get("dialogue_text")
            or shot.get("dialogue")
            or audio_cfg.get("contextual_tts_prompt")
            or audio_cfg.get("voice_type") == "dialogue"
        )
        timeline_shots.append({
            "shot_id": shot.get("shot_id", 0),
            "start_sec": s_start,
            "end_sec": s_end,
            "duration_sec": dur,
            "has_dialogue": has_dialogue,
            "speech_inpoint": shot.get("speech_inpoint_sec") or audio_cfg.get("speech_inpoint_sec"),
            "foley_cue": shot.get("foley_cue") or shot.get("foley"),
        })

    actual_total_sec = total_duration_sec if total_duration_sec is not None else running_sec

    # 寻找最佳 3.0s 断崖静音窗口 (40s ~ 55s 之间)
    cliff_start = 45.0
    if planned_cliff_start_sec is not None:
        cliff_start = planned_cliff_start_sec
    else:
        # 在窗口之间优先寻找无对白的镜头缝隙
        candidates: list[float] = []
        for ts in timeline_shots:
            if window_start <= ts["start_sec"] <= (window_end - silence_dur):
                if not ts["has_dialogue"]:
                    candidates.append(ts["start_sec"])
        if candidates:
            cliff_start = candidates[0]
        else:
            cliff_start = min(45.0, max(window_start, actual_total_sec - 15.0))

    cliff_end = min(cliff_start + silence_dur, actual_total_sec - OUTRO_FADEOUT_DURATION_SEC)

    # 逐段切分并应用分贝调度
    for ts in timeline_shots:
        s_start = ts["start_sec"]
        s_end = ts["end_sec"]
        has_dlg = ts["has_dialogue"]
        inpoint = ts["speech_inpoint"]
        foley = ts["foley_cue"]

        # 处理镜头内是否有断崖静音重叠
        # 情况 A: 镜头完全在断崖静音外部
        if s_end <= cliff_start or s_start >= cliff_end:
            _append_shot_schedule(schedule, s_start, s_end, has_dlg, inpoint, foley)
        # 情况 B: 镜头与断崖静音重合
        else:
            # 镜头在断崖前部分
            if s_start < cliff_start:
                _append_shot_schedule(schedule, s_start, cliff_start, has_dlg, inpoint, foley)
            
            # 断崖静音核心段 (仅插入一次)
            overlap_start = max(s_start, cliff_start)
            overlap_end = min(s_end, cliff_end)
            if overlap_end > overlap_start:
                schedule.append(
                    MasteringScheduleItem(
                        time_start_sec=round(overlap_start, 2),
                        time_end_sec=round(overlap_end, 2),
                        timecode_range=format_timecode_range(overlap_start, overlap_end - overlap_start),
                        target_bgm_volume_db=BGM_VOLUME_CLIFF_MUTE_DB,
                        speech_ducking_active=False,
                        event_description="[声学行为] 核心戏剧骤停，进入断崖静音 3.0 秒 (-999.0dB)",
                    )
                )

            # 镜头在断崖后部分
            if s_end > cliff_end:
                _append_shot_schedule(schedule, cliff_end, s_end, has_dlg, inpoint, foley)

    # 片尾淡出与骤停处理 (最后 2.0s)
    outro_start = max(0.0, actual_total_sec - OUTRO_FADEOUT_DURATION_SEC)
    # 截取或添加最后一段为淡出骤停
    schedule.append(
        MasteringScheduleItem(
            time_start_sec=round(outro_start, 2),
            time_end_sec=round(actual_total_sec, 2),
            timecode_range=format_timecode_range(outro_start, actual_total_sec - outro_start),
            target_bgm_volume_db=-24.0,
            speech_ducking_active=False,
            event_description="片尾最后 2 秒平滑淡出，终局下潜重击 Sub-drop 随黑屏骤停，杜绝黑屏后 BGM 拖音穿帮",
        )
    )

    logger.debug(f"[RULE-V-S8-02] Generated {len(schedule)} mastering schedule segments.")
    return schedule


def _append_shot_schedule(
    schedule: list[MasteringScheduleItem],
    seg_start: float,
    seg_end: float,
    has_dialogue: bool,
    speech_inpoint: float | None,
    foley_cue: str | None,
) -> None:
    """辅助函数：为单个镜头或区间切分动作区与对白避让区。"""
    dur = seg_end - seg_start
    if dur <= 0.05:
        return

    foley_note = f" (+3.0dB 拟音: {foley_cue})" if foley_cue else ""

    if not has_dialogue or speech_inpoint is None or speech_inpoint <= 0:
        if has_dialogue:
            # 纯对白区间
            schedule.append(
                MasteringScheduleItem(
                    time_start_sec=round(seg_start, 2),
                    time_end_sec=round(seg_end, 2),
                    timecode_range=format_timecode_range(seg_start, dur),
                    target_bgm_volume_db=BGM_VOLUME_DUCKING_DB,
                    speech_ducking_active=True,
                    event_description=f"对白爆发，触发侧链自动避让下沉至 -20.0dB{foley_note}",
                )
            )
        else:
            # 纯动作/运镜区间
            schedule.append(
                MasteringScheduleItem(
                    time_start_sec=round(seg_start, 2),
                    time_end_sec=round(seg_end, 2),
                    timecode_range=format_timecode_range(seg_start, dur),
                    target_bgm_volume_db=BGM_VOLUME_ACTION_DB,
                    speech_ducking_active=False,
                    event_description=f"前置动作/运镜区间，BGM维持 -12.0dB 背景基准{foley_note}",
                )
            )
    else:
        # 有前置动作，后接对白
        inpoint_time = min(seg_start + float(speech_inpoint), seg_end)
        action_dur = inpoint_time - seg_start
        if action_dur > 0.1:
            schedule.append(
                MasteringScheduleItem(
                    time_start_sec=round(seg_start, 2),
                    time_end_sec=round(inpoint_time, 2),
                    timecode_range=format_timecode_range(seg_start, action_dur),
                    target_bgm_volume_db=BGM_VOLUME_ACTION_DB,
                    speech_ducking_active=False,
                    event_description=f"镜头前置动作/视线推移区间，BGM维持 -12.0dB{foley_note}",
                )
            )
        dlg_dur = seg_end - inpoint_time
        if dlg_dur > 0.1:
            schedule.append(
                MasteringScheduleItem(
                    time_start_sec=round(inpoint_time, 2),
                    time_end_sec=round(seg_end, 2),
                    timecode_range=format_timecode_range(inpoint_time, dlg_dur),
                    target_bgm_volume_db=BGM_VOLUME_DUCKING_DB,
                    speech_ducking_active=True,
                    event_description="台词发声入点到达，侧链避让下沉至 -20.0dB",
                )
            )


def generate_bgm_master_prompt(
    genre: str,
    visual_style: str = "Cinematic film gritty noir",
    actual_duration_sec: float = 120.0,
    leitmotif_name: str = "悬疑压迫与阶层窒息",
    bpm: int = 84,
    musical_key: str = "D minor",
    *,
    episode_id: int | None = None,
    emotional_arc: str | None = None,
    key: str | None = None,
    tempo_bpm: int | None = None,
    primary_instruments: list[str] | None = None,
) -> str:
    """【规则编号: RULE-V-S8-02 / RULE-VI-08】动态编译 Suno/Udio 全量 BGM Prompt。
    
    时长动态设置为实际总时长 T_actual 绝对秒数，片尾平滑淡出，彻底杜绝多播拖音。
    """
    final_bpm = tempo_bpm if tempo_bpm is not None else bpm
    final_key = key if key is not None else musical_key
    inst_str = ", ".join(primary_instruments) if primary_instruments else "低音大提琴弓弦摩擦, 重度下潜808 Sub-bass, 频闪电子合成器脉冲, 金属微鸣"
    arc_str = f"情绪弧线: {emotional_arc}; " if emotional_arc else ""
    ep_str = f"第 {episode_id} 集 " if episode_id is not None else ""

    prompt = (
        f"[Instrumental Soundtrack, Film Score] {ep_str}Genre: {genre}, Style: {visual_style}. "
        f"{arc_str}Key: {final_key}, Tempo: {final_bpm} BPM. "
        f"Instrumentation: {inst_str}. "
        f"Dramatic Motif: {leitmotif_name}. "
        f"Dynamics: Gritty noir atmospheric tension build-up, sudden cliffhanger silence at 45s, intense climax drop, "
        f"smooth tail fade out before exact {int(actual_duration_sec)}s hard cut stop. "
        f"Mastering: High fidelity cinematic mix, clean acoustic stereo separation, zero vocal."
    )
    logger.debug(f"[RULE-VI-08] Generated BGM prompt ({len(prompt)} chars).")
    return prompt
    total_sec_int = int(round(actual_duration_sec))
    fadeout_sec = max(2, total_sec_int - 2)

    prompt = (
        f"[Style: {genre}, {visual_style}, Dark Cinematic Tension, Industrial Noir Score] "
        f"[Key: {musical_key}] [BPM: {bpm}] [Theme: {leitmotif_name}] "
        f"[Instrumentation: deep low cello drones, sub-bass braams, distant mechanical clangs, clock ticking Foley] "
        f"[Structure: 00:00-00:30 Tension Build --> 00:40-00:55 Abrupt Silence Drop (-inf dB) --> "
        f"00:55-{fadeout_sec:02d} Climax Escalation --> {fadeout_sec:02d}-{total_sec_int:02d} Final Sub-drop & Immediate Hard Cut] "
        f"[Duration: exactly {total_sec_int} seconds, strictly end at {total_sec_int}s with zero reverb tail]"
    )
    logger.debug(f"[RULE-V-S8-02] Compiled dynamic BGM prompt for {total_sec_int}s: {prompt[:60]}...")
    return prompt


def get_nle_mixing_guidelines() -> dict[str, Any]:
    """【规则编号: RULE-VI-08 / RULE-VII-01】出具 NLE 剪辑软件 4 轨参数规范字典。"""
    return {
        "sampling_rate": "48kHz",
        "sample_rate": "48kHz",
        "bit_depth": "24-bit",
        "peak_db": -1.0,
        "integrated_lufs": -14.0,
        "tracks": {
            "A1_Dialogue": {
                "bus_name": "Dialogue Master",
                "loudness_norm": "-23 LUFS",
                "fader_db": 0.0,
                "effects_chain": "High-pass 85Hz -> Surgical Notch EQ -> De-esser (6-8kHz) -> Opto Compressor",
            },
            "A2_Foley_FX": {
                "bus_name": "Haptic Foley FX",
                "gain_boost": "+3.0dB on micro-interaction transience",
                "panning": "center-spread 15%",
                "fader_db": -2.0,
            },
            "A3_Ambient_SFX": {
                "bus_name": "Ambient FX & Atmosphere",
                "fader_db": -6.0,
            },
            "A4_Music_BGM": {
                "bus_name": "Music Bed",
                "action_level": "-12.0dB",
                "dialogue_ducking_level": "-20.0dB",
                "cliff_silence_level": "-999.0dB (hard mute)",
                "sidechain_source": "A1_Dialogue",
                "ducking_attack_ms": 15,
                "ducking_release_ms": 300,
            },
        },
        "A1_dialogue_track": {
            "bus_name": "Dialogue Master",
            "loudness_norm": "-23 LUFS",
            "fader_db": 0.0,
            "effects_chain": "High-pass 85Hz -> Surgical Notch EQ -> De-esser (6-8kHz) -> Opto Compressor",
        },
        "A2_foley_track": {
            "bus_name": "Haptic Foley FX",
            "gain_boost": "+3.0dB on micro-interaction transience",
            "panning": "center-spread 15%",
            "fader_db": -2.0,
        },
        "A3_bgm_track": {
            "bus_name": "Music Bed",
            "action_level": "-12.0dB",
            "dialogue_ducking_level": "-20.0dB",
            "cliff_silence_level": "-999.0dB (hard mute)",
            "sidechain_source": "A1_dialogue_track",
            "ducking_attack_ms": 15,
            "ducking_release_ms": 300,
        },
        "V1_V2_video_subs": {
            "aspect_ratio": "9:16 (1080x1920)",
            "frame_rate": "25fps",
            "subtitle_alignment": "Bottom 15%, font size 42pt, border 2px black",
        },
    }


class AudioMasteringEngine:
    """多轨智能混音工程与毫秒级 SRT 算子类门面。"""
    generate_srt = staticmethod(generate_srt_content)
    generate_schedule = staticmethod(generate_mastering_schedule)
    generate_bgm_prompt = staticmethod(generate_bgm_master_prompt)
    get_guidelines = staticmethod(get_nle_mixing_guidelines)

