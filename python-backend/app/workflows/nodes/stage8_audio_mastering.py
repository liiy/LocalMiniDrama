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

from app.context.short_memory_service import (
    publish_drama_event,
    publish_episode_read_projection,
    set_episode_physical_snapshot,
)
from app.schemas.script_graph_state import (
    AudioMasteringConfig,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    IndustrialDramaState,
)
from app.tools.audio_mastering_engine import (
    AudioMasteringEngine,
    MasteringScheduleItem,
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
                    "gain_db": -20.0,
                    "description": f"分镜镜头 {getattr(s, 'shot_id', i+1)} 对白侧链避让 (-20dB): {dialogue[:30]}",
                })
    return events


def _build_mastering_schedule(shots: list[Any], total_duration_sec: float) -> list[dict[str, Any]]:
    """【规则编号: Skill规则表-Stage8-03-Ducking调度表】调用纯算子引擎构建广播级精准分贝调度表。
    
    包含动作区 (-12.0dB)、对白开口区 (-20.0dB)、断崖静音 (-999.0dB) 与尾部平滑淡出骤停。
    """
    shots_dicts: list[dict[str, Any]] = []
    for s in shots:
        if hasattr(s, "model_dump"):
            shots_dicts.append(s.model_dump())
        elif isinstance(s, dict):
            shots_dicts.append(dict(s))
        elif hasattr(s, "__dict__"):
            shots_dicts.append(dict(s.__dict__))
        else:
            shots_dicts.append({})

    engine_items: list[MasteringScheduleItem] = AudioMasteringEngine.generate_schedule(
        storyboard_shots=shots_dicts,
        total_duration_sec=total_duration_sec,
    )

    schedule: list[dict[str, Any]] = []
    for item in engine_items:
        schedule.append({
            "time_start_sec": item.time_start_sec,
            "time_end_sec": item.time_end_sec,
            "start_sec": item.time_start_sec,
            "end_sec": item.time_end_sec,
            "timecode_range": item.timecode_range,
            "action_type": (
                "speech_ducking"
                if item.speech_ducking_active
                else (
                    "cliffhanger_silence"
                    if item.target_bgm_volume_db <= -900.0
                    else ("fade_out_stop" if item.target_bgm_volume_db <= -22.0 else "action_bed")
                )
            ),
            "target_bgm_volume_db": item.target_bgm_volume_db,
            "gain_db": item.target_bgm_volume_db,
            "speech_ducking_active": item.speech_ducking_active,
            "event_description": item.event_description,
            "description": item.event_description,
        })

    # 若引擎未产生调度或缺失 45s 断崖静音/片尾硬切，实施安全增强兜底
    has_silence = any(item.get("target_bgm_volume_db", 0.0) <= -900.0 for item in schedule)
    if not has_silence and total_duration_sec >= 45.0:
        schedule.append({
            "time_start_sec": 45.0,
            "time_end_sec": 48.0,
            "start_sec": 45.0,
            "end_sec": 48.0,
            "timecode_range": "00:00:45,000 --> 00:00:48,000",
            "action_type": "cliffhanger_silence",
            "target_bgm_volume_db": -999.0,
            "gain_db": -999.0,
            "speech_ducking_active": False,
            "event_description": "剧作第45秒高潮断崖静音3秒，消除BGM营造绝对窒息压迫感",
            "description": "剧作第45秒高潮断崖静音3秒，消除BGM营造绝对窒息压迫感",
        })

    has_outro = any(
        item.get("action_type") == "fade_out_stop" or "平滑淡出" in str(item.get("event_description", ""))
        for item in schedule
    )
    if not has_outro:
        fade_start = max(0.0, total_duration_sec - 2.0)
        schedule.append({
            "time_start_sec": fade_start,
            "time_end_sec": total_duration_sec,
            "start_sec": fade_start,
            "end_sec": total_duration_sec,
            "timecode_range": f"{fade_start:.1f}s --> {total_duration_sec:.1f}s",
            "action_type": "fade_out_stop",
            "target_bgm_volume_db": -999.0,
            "gain_db": -999.0,
            "speech_ducking_active": False,
            "event_description": "集尾最后2秒平滑淡出并硬切骤停，杜绝视频黑屏后BGM多播拖音",
            "description": "集尾最后2秒平滑淡出并硬切骤停，杜绝视频黑屏后BGM多播拖音",
        })

    return schedule


def _stage8_fallback(
    episode_num: int,
    props: list[dict[str, Any]],
    shots: list[Any],
    audio_bible_dict: dict[str, Any] | None = None,
    dramatic_cues: dict[str, Any] | None = None,
    worldview_summary: str | None = None,
    planned_duration_sec: float = 120.0,
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

    leitmotif_str = (
        (audio_bible_dict or {}).get("leitmotif_name")
        or (audio_bible_dict or {}).get("primary_leitmotif")
        or "LEITMOTIF_01_SUSPENSE 阴郁大提琴单音震音与管道回响"
    )

    full_master_prompt = AudioMasteringEngine.generate_bgm_prompt(
        genre="悬疑/黑帮犯罪",
        visual_style="Cinematic noir gritty contrast",
        actual_duration_sec=t_actual,
        leitmotif_name=leitmotif_str,
        bpm=84,
        musical_key="D minor",
        episode_id=episode_num,
    )

    cues_str = "开篇前3秒物理危机，45秒断崖静音卡点，片尾绝杀定格"
    if isinstance(dramatic_cues, dict):
        cues_str = f"开篇: {dramatic_cues.get('opening_hook', '物理危机')}, 卡点: {dramatic_cues.get('cliffhanger_hook', '45秒断崖')}, 结尾: {dramatic_cues.get('ending_hook', '绝杀定格')}"

    nle_guidelines = AudioMasteringEngine.get_guidelines()

    return {
        "episode_num": episode_num,
        "mastering_config": {
            "broadcast_loudness_standard": "-23 LUFS",
            "target_lufs": -23.0,
            "peak_limit_dbtp": -1.0,
            "acoustic_traceability": {
                "stage_4_leitmotif_basis": leitmotif_str,
                "stage_1_worldview_basis": worldview_summary or "冷硬工业黑帮题材，压抑克制且具爆发张力",
                "stage_7_timecode_basis": f"对齐阶段 7 镜头总时长 {t_actual}s 与台词发声入点偏移",
                "stage_5_dramatic_cues": cues_str,
            },
            "bgm_generation": {
                "full_master_prompt": full_master_prompt,
                "planned_duration_sec": t_actual,
                "actual_duration_sec": t_actual,
                "bpm": 84,
                "musical_key": "D minor",
                "target_lufs": -23.0,
            },
            "ducking_strategy": {
                "action_bed_db": -12.0,
                "dialogue_trigger_attenuation_db": -12.0,
                "dialogue_ducking_level_db": -20.0,
                "cliff_silence_db": -999.0,
                "attack_time_ms": 15.0,
                "release_time_ms": 300.0,
            },
            "ducking_events": ducking_events,
            "mastering_schedule": mastering_sched,
            "foley_boost_tracks": foley_boosts,
            "nle_mixing_guidelines": nle_guidelines,
            "tracks": [
                {"track_name": "Dialogue", "gain_db": 0.0, "compression_ratio": "3:1"},
                {"track_name": "Foley_FX", "gain_db": 3.0, "high_pass_filter_hz": 80},
                {"track_name": "BGM_Leitmotif", "gain_db": -12.0, "ducking_enabled": True},
            ],
        },
    }


def stage8_audio_mastering_node(
    state: EpisodeScopedSubState | GlobalDramaMasterState | IndustrialDramaState | Any,
) -> dict[str, Any]:
    """【规则编号: Skill规则表-Stage8-01~05】执行阶段 8：全息音频工程配置、拟音强化与动态 Ducking 避让。
    
    统一入参 state (TypedDict 或 MasterState 对象)，内部严禁业务分支跳转，仅输出增量状态更新。
    集数推进与单集循环交由独立路由函数 route_stage8_audit 与 route_episode_loop 执行。
    """
    ep_num = _get_val(state, "episode_number") or _get_val(state, "current_visual_episode", 1) or 1
    screenplays = _get_val(state, "completed_screenplays", {}) or {}
    script = screenplays.get(ep_num) or {}
    if not script and _get_val(state, "screenplay"):
        script = _get_val(state, "screenplay")
    if not script and _get_val(state, "screenplay_text"):
        script = {"title": f"第{ep_num}集", "body_markdown": _get_val(state, "screenplay_text")}
    if hasattr(script, "model_dump"):
        script = script.model_dump()
    elif not isinstance(script, dict):
        script = {}
    storyboards = _get_val(state, "episode_storyboards", {}) or {}
    shots = storyboards.get(ep_num) or _get_val(state, "storyboard_shots") or []
    if not isinstance(shots, list):
        shots = list(shots.values()) if isinstance(shots, dict) else []
    outlines = _get_val(state, "completed_outlines", {}) or {}
    ep_outline = outlines.get(ep_num) or _get_val(state, "task_outline") or {}
    env_props = _get_val(state, "environments_and_props", {}) or {}
    props_list = env_props.get("props", []) if isinstance(env_props, dict) else []
    if not props_list and _get_val(state, "relevant_prop_stubs"):
        props_list = [
            {"prop_id": f"PROP_{p.prop_id}", "name": p.name, "type": p.level}
            if hasattr(p, "prop_id") else p
            for p in _get_val(state, "relevant_prop_stubs")
        ]

    logger.info(f"【阶段 8 混音工程】开始执行第 {ep_num} 集声学混音工程与动态 Ducking 避让计算...")

    audio_bible = _get_val(state, "audio_bible", {})
    audio_bible_dict = (
        audio_bible.model_dump()
        if hasattr(audio_bible, "model_dump")
        else (audio_bible if isinstance(audio_bible, dict) else {})
    )

    project_meta = _get_val(state, "project_metadata", {})
    planned_dur = 120.0
    if hasattr(project_meta, "duration_sec_per_ep"):
        planned_dur = float(project_meta.duration_sec_per_ep or 120.0)
    elif isinstance(project_meta, dict):
        planned_dur = float(project_meta.get("duration_sec_per_ep") or 120.0)

    t_actual = _calculate_total_duration_from_shots(shots)

    dramatic_cues = {
        "opening_hook": (
            ep_outline.get("opening_hook")
            if isinstance(ep_outline, dict)
            else getattr(ep_outline, "opening_hook", "前3秒强节奏物理危机爆发")
        ) or "前3秒强节奏物理危机爆发",
        "cliffhanger_hook": (
            ep_outline.get("cliffhanger_hook")
            if isinstance(ep_outline, dict)
            else getattr(ep_outline, "cliffhanger_hook", "第45秒高潮断崖悬念反转与静音点")
        ) or "第45秒高潮断崖悬念反转与静音点",
        "ending_hook": (
            ep_outline.get("cliffhanger")
            if isinstance(ep_outline, dict)
            else getattr(ep_outline, "cliffhanger", "集尾生死悬念扣与硬切骤停")
        ) or "集尾生死悬念扣与硬切骤停",
        "dramatic_arc": (
            ep_outline.get("dramatic_arc")
            if isinstance(ep_outline, dict)
            else getattr(ep_outline, "dramatic_arc", "张力持续攀升并在45秒经历窒息下沉后爆发")
        ) or "张力持续攀升并在45秒经历窒息下沉后爆发",
    }

    worldview = str(_get_val(state, "topic", "") or _get_val(state, "concept_design", ""))

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
        planned_duration_sec=planned_dur,
        actual_total_sec=t_actual,
        script_json=json.dumps(script, ensure_ascii=False),
        dramatic_cues_json=json.dumps(dramatic_cues, ensure_ascii=False),
        shots_summary_json=json.dumps(shots_summary, ensure_ascii=False),
        audio_bible_json=json.dumps(audio_bible_dict, ensure_ascii=False),
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE8_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage8_fallback(
            episode_num=ep_num,
            props=props_list,
            shots=shots,
            audio_bible_dict=audio_bible_dict,
            dramatic_cues=dramatic_cues,
            worldview_summary=worldview,
            planned_duration_sec=planned_dur,
        ),
    )

    mastering_config = result_json.get("mastering_config") or _stage8_fallback(
        episode_num=ep_num,
        props=props_list,
        shots=shots,
        audio_bible_dict=audio_bible_dict,
        dramatic_cues=dramatic_cues,
        worldview_summary=worldview,
        planned_duration_sec=planned_dur,
    )["mastering_config"]

    # 规范化强化字段，确保符合《Skill规则表》Stage 8 数据契约与广播级标准
    if "broadcast_loudness_standard" not in mastering_config or mastering_config["broadcast_loudness_standard"] != "-23 LUFS":
        mastering_config["broadcast_loudness_standard"] = "-23 LUFS"
    if mastering_config.get("target_lufs") != -23.0:
        mastering_config["target_lufs"] = -23.0
    if float(mastering_config.get("peak_limit_dbtp", -1.0)) > -1.0:
        mastering_config["peak_limit_dbtp"] = -1.0

    # 强化溯源
    if "acoustic_traceability" not in mastering_config or not isinstance(mastering_config["acoustic_traceability"], dict):
        fallback_cfg = _stage8_fallback(ep_num, props_list, shots, audio_bible_dict, dramatic_cues, worldview, planned_dur)["mastering_config"]
        mastering_config["acoustic_traceability"] = fallback_cfg["acoustic_traceability"]
    else:
        trace = mastering_config["acoustic_traceability"]
        if not trace.get("stage_7_timecode_basis"):
            trace["stage_7_timecode_basis"] = f"对齐阶段 7 镜头总时长 {t_actual}s 与台词发声入点偏移"
        if not trace.get("stage_4_leitmotif_basis"):
            trace["stage_4_leitmotif_basis"] = (audio_bible_dict or {}).get("leitmotif_name") or "LEITMOTIF_01_SUSPENSE 阴郁大提琴单音震音与管道回响"
        if not trace.get("stage_1_worldview_basis"):
            trace["stage_1_worldview_basis"] = worldview or "冷硬工业黑帮题材，压抑克制且具爆发张力"
        if not trace.get("stage_5_dramatic_cues"):
            trace["stage_5_dramatic_cues"] = "开篇前3秒物理危机，45秒断崖静音卡点，片尾绝杀定格"

    # 强化 BGM 生成规范
    if "bgm_generation" not in mastering_config or not isinstance(mastering_config["bgm_generation"], dict):
        mastering_config["bgm_generation"] = {
            "full_master_prompt": AudioMasteringEngine.generate_bgm_prompt(
                genre="悬疑/黑帮犯罪",
                visual_style="Cinematic noir gritty contrast",
                actual_duration_sec=t_actual,
                episode_id=ep_num,
            ),
            "planned_duration_sec": t_actual,
            "actual_duration_sec": t_actual,
            "target_lufs": -23.0,
            "bpm": 84,
        }
    else:
        bgm_gen = mastering_config["bgm_generation"]
        bgm_gen["actual_duration_sec"] = t_actual
        if not bgm_gen.get("planned_duration_sec"):
            bgm_gen["planned_duration_sec"] = t_actual
        if not bgm_gen.get("target_lufs"):
            bgm_gen["target_lufs"] = -23.0
        if not bgm_gen.get("full_master_prompt") or f"{int(round(t_actual))}s" not in str(bgm_gen.get("full_master_prompt")):
            bgm_gen["full_master_prompt"] = AudioMasteringEngine.generate_bgm_prompt(
                genre="悬疑/黑帮犯罪",
                visual_style="Cinematic noir gritty contrast",
                actual_duration_sec=t_actual,
                episode_id=ep_num,
            )

    # 强化避让参数双向兼容
    if "ducking_strategy" not in mastering_config or not isinstance(mastering_config["ducking_strategy"], dict):
        mastering_config["ducking_strategy"] = {
            "action_bed_db": -12.0,
            "dialogue_trigger_attenuation_db": -12.0,
            "dialogue_ducking_level_db": -20.0,
            "cliff_silence_db": -999.0,
            "attack_time_ms": 15.0,
            "release_time_ms": 300.0,
        }
    else:
        ds = mastering_config["ducking_strategy"]
        ds["action_bed_db"] = -12.0
        ds["dialogue_trigger_attenuation_db"] = -12.0
        ds["dialogue_ducking_level_db"] = -20.0
        ds.setdefault("cliff_silence_db", -999.0)
        ds.setdefault("attack_time_ms", 15.0)
        ds.setdefault("release_time_ms", 300.0)

    # 强化避让调度表与事件
    if "ducking_events" not in mastering_config or not mastering_config["ducking_events"]:
        mastering_config["ducking_events"] = _extract_ducking_events_from_shots(shots) or _stage8_fallback(
            ep_num, props_list, shots, audio_bible_dict, dramatic_cues, worldview, planned_dur
        )["mastering_config"].get("ducking_events", [])

    if "mastering_schedule" not in mastering_config or not mastering_config["mastering_schedule"]:
        mastering_config["mastering_schedule"] = _build_mastering_schedule(shots, t_actual)
    else:
        # 确保 schedule 中有 45s 断崖静音与集尾硬切
        sched = mastering_config["mastering_schedule"]
        has_cliff_silence = any(
            item.get("target_bgm_volume_db", 0.0) <= -900.0 or item.get("action_type") == "cliffhanger_silence"
            for item in sched
            if isinstance(item, dict)
        )
        if not has_cliff_silence:
            c_start = 45.0 if t_actual >= 48.0 else round(max(1.0, t_actual * 0.6), 1)
            c_end = round(min(c_start + 3.0, t_actual - 0.5), 1) if t_actual >= 48.0 else round(min(c_start + 2.0, t_actual), 1)
            if c_end <= c_start:
                c_end = round(c_start + 0.5, 1)
            sched.append({
                "start_sec": c_start,
                "end_sec": c_end,
                "time_start_sec": c_start,
                "time_end_sec": c_end,
                "action_type": "cliffhanger_silence",
                "target_bgm_volume_db": -999.0,
                "gain_db": -999.0,
                "speech_ducking_active": False,
                "event_description": f"剧作高潮断崖静音，消除BGM营造绝对窒息压迫感 ({c_start}s~{c_end}s)",
                "description": f"剧作高潮断崖静音，消除BGM营造绝对窒息压迫感 ({c_start}s~{c_end}s)",
            })

    # 强化 NLE 4 轨参数指南
    if "nle_mixing_guidelines" not in mastering_config or not mastering_config["nle_mixing_guidelines"]:
        mastering_config["nle_mixing_guidelines"] = AudioMasteringEngine.get_guidelines()

    # 通过强类型 Pydantic 模型校验并标准化
    try:
        validated = AudioMasteringConfig.model_validate(mastering_config)
        mastering_config = validated.model_dump()
    except Exception as exc:
        logger.warning(f"[Stage 8 Node] Pydantic validation warning, retaining dict: {exc}")

    logger.debug(
        f"[Stage 8 Node] Episode {ep_num} audio mastering complete: "
        f"loudness={mastering_config.get('broadcast_loudness_standard')}, "
        f"target_lufs={mastering_config.get('target_lufs')}, "
        f"ducking_events_count={len(mastering_config.get('ducking_events', []))}, "
        f"schedule_items_count={len(mastering_config.get('mastering_schedule', []))}"
    )

    masterings = dict(_get_val(state, "episode_audio_masterings", {}) or {})
    masterings[ep_num] = mastering_config

    logger.info(f"【阶段 8 混音工程】第 {ep_num} 集母带混音工程配置已成功生成并落库。")

    # 构造剧集连续性物理快照
    last_shot = shots[-1] if shots else {}
    ending_scene_val = last_shot.get("scene_number", 1) if isinstance(last_shot, dict) else getattr(last_shot, "scene_number", 1)
    ending_shot_val = last_shot.get("shot_number", 1) if isinstance(last_shot, dict) else getattr(last_shot, "shot_number", 1)
    outgoing_physical_continuity = {
        "episode_number": ep_num,
        "ending_scene": ending_scene_val,
        "last_scene": ending_scene_val,
        "ending_shot": ending_shot_val,
        "last_shot": ending_shot_val,
        "character_positions": last_shot.get("character_positions", {}) if isinstance(last_shot, dict) else getattr(last_shot, "character_positions", {}),
        "lighting_continuity": last_shot.get("lighting_continuity", "集尾光照延续") if isinstance(last_shot, dict) else getattr(last_shot, "lighting_continuity", "集尾光照延续"),
        "key_props_held": last_shot.get("props_in_hand", []) if isinstance(last_shot, dict) else getattr(last_shot, "props_in_hand", []),
        "cliffhanger_context": (
            ep_outline.get("cliffhanger", "集尾悬念")
            if hasattr(ep_outline, "get")
            else getattr(ep_outline, "cliffhanger", getattr(ep_outline, "hook_cliffhanger", "集尾悬念"))
        ),
    }

    # 异步投影与事件发布
    drama_id = _get_val(state, "drama_id") or "default_drama"
    set_episode_physical_snapshot(drama_id, ep_num, outgoing_physical_continuity)
    publish_episode_read_projection(
        drama_id,
        ep_num,
        {
            "audio_mastering": mastering_config,
            "outgoing_physical_continuity": outgoing_physical_continuity,
        },
    )
    publish_drama_event(
        drama_id,
        "stage8_completed",
        {
            "episode_number": ep_num,
            "actual_duration_seconds": mastering_config.get("actual_duration_seconds", 0),
            "ducking_events_count": len(mastering_config.get("ducking_events", [])),
        },
    )

    is_scoped = "episode_number" in state if isinstance(state, dict) else hasattr(state, "episode_number")

    # 严格遵循公共约束：节点函数内部严禁包含业务分支跳转，仅输出增量状态更新
    res = {
        "current_stage": 8,
        "episode_audio_masterings": masterings,
        "inter_episode_physical_snapshot": outgoing_physical_continuity,
        "outgoing_physical_continuity": outgoing_physical_continuity,
    }
    if is_scoped:
        res["audio_mastering"] = mastering_config
        res["is_completed"] = True
    return res
