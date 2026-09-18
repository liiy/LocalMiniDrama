"""阶段 8：全息声学混音工程与自动化避让节点 (Stage 8 Audio Mastering Node)。

严格遵循《Skill规则表》v10.0.0 与公共硬性约束：
- 【Skill规则表-Stage8-01-四大依据溯源】锁定母动机库/世界观基调/阶段7实际时间轴/阶段5戏剧点；
- 【Skill规则表-Stage8-02-BGM生乐Prompt】动态读取阶段7实际累计时长 T_actual，编译 Suno/Udio 全量 Prompt，片尾最后2秒平滑淡出并硬切骤停；
- 【Skill规则表-Stage8-03-Ducking调度表】精准分贝避让调度表 (Mastering Schedule)：动作区 -12.0dB，对白开口区下沉至 -20.0dB，第45秒断崖静音3秒 (-999.0dB)，集尾 Sub-drop；
- 【Skill规则表-Stage8-04-NLE多轨指南】出具 A1对白轨(0dB)/A2拟音轨(+3dB)/A3配乐轨(-14dB)/V1-V2视频字幕轨的导入参数指南；
- 【Skill规则表-Stage8-05-广播级响度】人声响度锁定 -23 LUFS，真峰值限制在 -1.0 dBTP；
- 节点函数统一入参 state，内部严禁业务分支跳转（集数递增与微循环交由独立路由函数处理），仅输出增量状态更新；
- 全流程中文注释与 debug 级日志追踪。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from app.schemas.script_graph_state import (
    IndustrialDramaMasterState,
    IndustrialDramaState,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE8_SYSTEM_PROMPT,
    STAGE8_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage8_audio_mastering")


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _parse_timecode_interval(timecode: str) -> tuple[float, float] | None:
    """解析 SRT 时间码字符串为 (start_sec, end_sec) 浮点数区间。

    支持 '00:00:02,500 --> 00:00:06,000' 或 '00:02.500 --> 00:06.000' 等格式。
    """
    try:
        parts = timecode.split("-->")
        if len(parts) != 2:
            return None

        def _to_sec(s: str) -> float:
            s = s.strip().replace(",", ".")
            tokens = s.split(":")
            if len(tokens) == 3:
                return float(tokens[0]) * 3600 + float(tokens[1]) * 60 + float(tokens[2])
            elif len(tokens) == 2:
                return float(tokens[0]) * 60 + float(tokens[1])
            return float(s)

        start_s = _to_sec(parts[0])
        end_s = _to_sec(parts[1])
        return (start_s, end_s)
    except Exception:
        return None


def _calculate_total_duration_from_shots(shots: list[Any]) -> float:
    """计算分镜镜头累加的实际总秒数 T_actual。"""
    total = 0.0
    for s in shots:
        dur = 0.0
        if hasattr(s, "duration_sec"):
            dur = float(s.duration_sec or 0.0)
        elif isinstance(s, dict):
            dur = float(s.get("duration_sec") or s.get("duration_seconds") or 0.0)
        total += dur
    return round(total, 1) if total > 0 else 120.0


def _extract_ducking_events_from_shots(shots: list[Any]) -> list[dict[str, Any]]:
    """【规则编号: Skill规则表-Stage8-03-Ducking调度表】从分镜对白与时间码中精准对齐侧链避让 Ducking 事件。"""
    events: list[dict[str, Any]] = []
    for i, s in enumerate(shots):
        dialogue = ""
        timecode = ""
        speech_inpoint = None
        if hasattr(s, "audio") and isinstance(s.audio, dict):
            dialogue = s.audio.get("dialogue", "")
            speech_inpoint = s.audio.get("speech_inpoint_sec")
        elif isinstance(s, dict):
            dialogue = s.get("audio", {}).get("dialogue", "") or s.get("dialogue", "")
            speech_inpoint = s.get("audio", {}).get("speech_inpoint_sec") or s.get("speech_inpoint_sec")

        if hasattr(s, "timecode"):
            timecode = s.timecode
        elif isinstance(s, dict):
            timecode = s.get("timecode", "")

        if dialogue and timecode:
            interval = _parse_timecode_interval(timecode)
            if interval:
                start_s, end_s = interval
                offset = float(speech_inpoint) if speech_inpoint is not None else 0.0
                effective_start = round(start_s + offset, 3)
                events.append({
                    "start_sec": effective_start,
                    "end_sec": round(end_s, 3),
                    "target_track": "BGM_Leitmotif",
                    "gain_db": -18.0,
                    "description": f"分镜镜头 {getattr(s, 'shot_id', i+1)} 对白侧链避让 (-18dB): {dialogue[:30]}",
                })
    return events


def _build_mastering_schedule(shots: list[Any], total_duration_sec: float) -> list[dict[str, Any]]:
    """【规则编号: Skill规则表-Stage8-03-Ducking调度表】构建广播级精准分贝调度表。
    
    包含动作区 (-12.0dB)、对白开口区 (-20.0dB)、断崖静音 (-999.0dB) 与尾部平滑淡出。
    """
    schedule: list[dict[str, Any]] = []

    # 1. 基础动作与氛围区间
    schedule.append({
        "start_sec": 0.0,
        "end_sec": min(total_duration_sec, 2.5),
        "action_type": "action_intro",
        "target_bgm_volume_db": -12.0,
        "speech_ducking_active": False,
        "description": "开局动作爆发与物理拟音铺底，维持动作音量 -12dB",
    })

    # 2. 对白区间避让
    ducking_evs = _extract_ducking_events_from_shots(shots)
    for ev in ducking_evs:
        schedule.append({
            "start_sec": ev["start_sec"],
            "end_sec": ev["end_sec"],
            "action_type": "speech_ducking",
            "target_bgm_volume_db": -20.0,
            "speech_ducking_active": True,
            "description": ev["description"],
        })

    # 3. 黄金卡点：45秒处 3 秒断崖绝对静音 (若全长超过 50 秒)
    if total_duration_sec >= 50.0:
        schedule.append({
            "start_sec": 45.0,
            "end_sec": 48.0,
            "action_type": "cliffhanger_silence",
            "target_bgm_volume_db": -999.0,
            "speech_ducking_active": False,
            "description": "剧作第45秒高潮断崖静音3秒，消除BGM营造绝对窒息压迫感",
        })

    # 4. 集尾最后 2 秒平滑淡出
    fade_start = max(0.0, total_duration_sec - 2.0)
    schedule.append({
        "start_sec": fade_start,
        "end_sec": total_duration_sec,
        "action_type": "fade_out_stop",
        "target_bgm_volume_db": -999.0,
        "speech_ducking_active": False,
        "description": "集尾最后2秒平滑淡出并硬切骤停，杜绝视频黑屏后BGM多播拖音",
    })

    return schedule


def _stage8_fallback(
    episode_num: int,
    props: list[dict[str, Any]],
    shots: list[Any],
    audio_bible_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """当大模型离线或异常时的保底广播级声学混音工程与自动化避让配置工厂。"""
    logger.warning(f"[Stage 8 Node] Triggering fallback audio mastering for Episode {episode_num}.")

    hero_prop = props[0].get("name", "关键反转物证") if props else "关键物证"
    t_actual = _calculate_total_duration_from_shots(shots)

    ducking_events = _extract_ducking_events_from_shots(shots)
    if not ducking_events:
        ducking_events = [
            {
                "start_sec": 3.0,
                "end_sec": 7.0,
                "target_track": "BGM_Leitmotif",
                "gain_db": -20.0,
                "description": "对白段落触发 BGM 侧链深度避让 (-20dB)",
            },
            {
                "start_sec": 7.8,
                "end_sec": 10.0,
                "target_track": "BGM_Leitmotif",
                "gain_db": -20.0,
                "description": "物证爆发对白段落触发 BGM 深度避让 (-20dB)",
            },
        ]

    foley_boosts = [
        {
            "item": hero_prop,
            "boost_db": 3.0,
            "reason": "【Skill规则表-Stage8-04】强化核心反转物证物理碰撞清脆质感与震颤度 (+3.0dB)",
        },
        {
            "item": "枪栓上膛/物理动作阻力",
            "boost_db": 2.5,
            "reason": "强化开篇动作物理拟音阻力 (+2.5dB)",
        },
    ]

    mastering_sched = _build_mastering_schedule(shots, t_actual)

    full_master_prompt = (
        f"Cinematic Industrial Drama Soundtrack, suspenseful dark cello arpeggio, deep sub-bass pulses, "
        f"tense string tremolo, 85 BPM, dark brooding mood, duration {t_actual} seconds exact, "
        f"sudden cliffhanger cut at {t_actual}s, professional broadcast mixing, mastering for film noir"
    )

    return {
        "episode_num": episode_num,
        "mastering_config": {
            "broadcast_loudness_standard": "-23 LUFS",
            "target_lufs": -23.0,
            "peak_limit_dbtp": -1.0,
            "acoustic_traceability": {
                "stage_4_leitmotif_basis": "LEITMOTIF_01_SUSPENSE 阴郁大提琴单音震音与管道回响",
                "stage_1_worldview_basis": "冷硬工业黑帮题材，压抑克制且具爆发张力",
                "stage_7_timecode_basis": f"对齐阶段 7 镜头总时长 {t_actual}s 与台词发声入点偏移",
                "stage_5_dramatic_cues": "开篇前3秒物理危机，45秒悬疑卡点，片尾绝杀定格",
            },
            "bgm_generation": {
                "full_master_prompt": full_master_prompt,
                "planned_duration_sec": t_actual,
                "bpm": 85,
            },
            "ducking_strategy": {
                "dialogue_trigger_attenuation_db": -12.0,
                "attack_time_ms": 35.0,
                "release_time_ms": 300.0,
            },
            "ducking_events": ducking_events,
            "mastering_schedule": mastering_sched,
            "foley_boost_tracks": foley_boosts,
            "nle_mixing_guidelines": {
                "track_a1_dialogue": "0.0dB, 压缩比 3:1, -23 LUFS 标准",
                "track_a2_foley": "+3.0dB, 80Hz 高通滤波",
                "track_a3_bgm": "动作区 -12.0dB, 对白区 -20.0dB Ducking 避让, 45s断崖静音 -999.0dB",
                "track_v1_video": "V1 视频切片, V2 SRT 字幕文本",
            },
            "tracks": [
                {"track_name": "Dialogue", "gain_db": 0.0, "compression_ratio": "3:1"},
                {"track_name": "Foley_FX", "gain_db": 3.0, "high_pass_filter_hz": 80},
                {"track_name": "BGM_Leitmotif", "gain_db": -12.0, "ducking_enabled": True},
            ],
        },
    }


def stage8_audio_mastering_node(state: IndustrialDramaState | IndustrialDramaMasterState) -> dict[str, Any]:
    """【规则编号: Skill规则表-Stage8-01~05】执行阶段 8：全息音频工程配置、拟音强化与动态 Ducking 避让。
    
    统一入参 state (TypedDict 或 MasterState 对象)，内部严禁业务分支跳转，仅输出增量状态更新。
    集数推进与单集循环交由独立路由函数 route_stage8_audit 与 route_episode_loop 执行。
    """
    ep_num = _get_val(state, "current_visual_episode", 1) or 1
    screenplays = _get_val(state, "completed_screenplays", {}) or {}
    script = screenplays.get(ep_num) or {}
    storyboards = _get_val(state, "episode_storyboards", {}) or {}
    shots = storyboards.get(ep_num) or []
    env_props = _get_val(state, "environments_and_props", {}) or {}
    props_list = env_props.get("props", []) if isinstance(env_props, dict) else []

    logger.info(f"【阶段 8 混音工程】开始执行第 {ep_num} 集声学混音工程与动态 Ducking 避让计算...")

    audio_bible = _get_val(state, "audio_bible", {})
    audio_bible_dict = audio_bible.model_dump() if hasattr(audio_bible, "model_dump") else audio_bible if isinstance(audio_bible, dict) else {}

    t_actual = _calculate_total_duration_from_shots(shots)

    shots_summary = [
        {
            "shot_id": getattr(s, "shot_id", i + 1),
            "timecode": getattr(s, "timecode", ""),
            "mode": getattr(s, "generation_mode", "first_last_frame"),
            "audio": getattr(s, "audio", {}),
            "duration_sec": getattr(s, "duration_sec", 3.0),
        }
        for i, s in enumerate(shots)
    ]

    user_prompt = STAGE8_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        script_json=json.dumps(script, ensure_ascii=False),
        shots_summary_json=json.dumps(shots_summary, ensure_ascii=False),
        audio_bible_json=json.dumps(audio_bible_dict, ensure_ascii=False),
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE8_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage8_fallback(ep_num, props_list, shots, audio_bible_dict),
    )

    mastering_config = result_json.get("mastering_config") or _stage8_fallback(
        ep_num, props_list, shots, audio_bible_dict
    )["mastering_config"]

    # 规范化强化字段，确保符合《Skill规则表》Stage 8 数据契约
    if "broadcast_loudness_standard" not in mastering_config:
        mastering_config["broadcast_loudness_standard"] = "-23 LUFS"
    if "ducking_events" not in mastering_config or not mastering_config["ducking_events"]:
        mastering_config["ducking_events"] = _extract_ducking_events_from_shots(shots) or _stage8_fallback(
            ep_num, props_list, shots, audio_bible_dict
        )["mastering_config"].get("ducking_events", [])
    if "mastering_schedule" not in mastering_config or not mastering_config["mastering_schedule"]:
        mastering_config["mastering_schedule"] = _build_mastering_schedule(shots, t_actual)
    if "bgm_generation" not in mastering_config or not mastering_config["bgm_generation"]:
        mastering_config["bgm_generation"] = {
            "full_master_prompt": f"Cinematic soundtrack duration {t_actual}s, broadcast mix",
            "planned_duration_sec": t_actual,
        }

    logger.debug(
        f"[Stage 8 Node] Episode {ep_num} audio mastering complete: "
        f"loudness={mastering_config.get('broadcast_loudness_standard')}, "
        f"ducking_events_count={len(mastering_config.get('ducking_events', []))}, "
        f"schedule_items_count={len(mastering_config.get('mastering_schedule', []))}"
    )

    masterings = dict(_get_val(state, "episode_audio_masterings", {}) or {})
    masterings[ep_num] = mastering_config

    logger.info(f"【阶段 8 混音工程】第 {ep_num} 集母带混音工程配置已成功生成并落库。")

    # 严格遵循公共约束：节点函数内部严禁包含业务分支跳转，仅输出增量状态更新
    return {
        "current_stage": 8,
        "episode_audio_masterings": masterings,
    }
