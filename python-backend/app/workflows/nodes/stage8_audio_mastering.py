"""阶段 8：全息声学混音工程与自动化避让节点 (Stage 8 Audio Mastering Node)。

严格遵循 SKILL.md：
- 对白轨 (Dialogue, 0.0dB, 压缩比 3:1) / 拟音轨 (Foley FX, 80Hz高通滤波, +2.0dB~+3.0dB 物理拟音增强) / 配乐轨 (BGM, -12dB ~ -18dB Ducking 避让)；
- 自动化避让 (Dynamic Ducking Engine)：对白区间自动触发 -12dB ~ -18dB 侧链衰减，起音 35ms，释音 300ms；
- 避让事件精确对齐：通过 SRT/分镜时间码解析，将每一句台词起止时间与 BGM 避让事件对齐；
- 严格遵循 -23 LUFS 广播级响度基准，真峰值限制在 -1.0 dBTP；
- 全流程中文注释与 debug 级日志追踪，完成后落库并推进第二程集数游标。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.prompts.master_sop_prompts import (
    STAGE8_SYSTEM_PROMPT,
    STAGE8_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage8_audio_mastering")


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


def _extract_ducking_events_from_shots(shots: list[Any]) -> list[dict[str, Any]]:
    """从分镜对白与时间码中精准对齐侧链避让 Ducking 事件。"""
    events: list[dict[str, Any]] = []
    for i, s in enumerate(shots):
        dialogue = ""
        timecode = ""
        if hasattr(s, "audio") and isinstance(s.audio, dict):
            dialogue = s.audio.get("dialogue", "")
        elif isinstance(s, dict):
            dialogue = s.get("audio", {}).get("dialogue", "") or s.get("dialogue", "")

        if hasattr(s, "timecode"):
            timecode = s.timecode
        elif isinstance(s, dict):
            timecode = s.get("timecode", "")

        if dialogue and timecode:
            interval = _parse_timecode_interval(timecode)
            if interval:
                start_s, end_s = interval
                events.append({
                    "start_sec": round(start_s, 3),
                    "end_sec": round(end_s, 3),
                    "target_track": "BGM_Leitmotif",
                    "gain_db": -18.0,
                    "description": f"分镜镜头 {getattr(s, 'shot_id', i+1)} 对白侧链避让: {dialogue[:30]}",
                })
    return events


def _stage8_fallback(
    episode_num: int,
    props: list[dict[str, Any]],
    shots: list[Any],
) -> dict[str, Any]:
    """当大模型离线或异常时的保底广播级声学混音工程与自动化避让配置工厂。"""
    logger.warning("【阶段 8 混音工程】触发第 %s 集保底声学混音与避让工程生成", episode_num)

    hero_prop = props[0].get("name", "关键反转物证") if props else "关键物证"

    # 优先从实际分镜镜头提取动态避让事件
    extracted_events = _extract_ducking_events_from_shots(shots)
    if extracted_events:
        ducking_events = extracted_events
    else:
        ducking_events = [
            {
                "start_sec": 2.5,
                "end_sec": 6.0,
                "target_track": "BGM_Leitmotif",
                "gain_db": -12.0,
                "description": "对白段落触发 BGM 侧链深度避让 (-12dB)",
            },
            {
                "start_sec": 6.0,
                "end_sec": 9.0,
                "target_track": "BGM_Leitmotif",
                "gain_db": -14.0,
                "description": "物证爆发对白段落触发 BGM 深度避让 (-14dB)",
            },
        ]

    foley_boosts = [
        {
            "item": hero_prop,
            "boost_db": 3.0,
            "reason": "工业规范：强化核心反转物证与物理碰撞的清脆质感与震颤度",
        },
        {
            "item": "枪栓上膛/动作阻力",
            "boost_db": 2.5,
            "reason": "强化开篇爆点动作物理拟音阻力",
        },
    ]

    return {
        "episode_num": episode_num,
        "mastering_config": {
            "target_lufs": -23.0,
            "peak_limit_dbtp": -1.0,
            "ducking_strategy": {
                "dialogue_trigger_attenuation_db": -12.0,
                "attack_time_ms": 35.0,
                "release_time_ms": 300.0,
            },
            "ducking_events": ducking_events,
            "foley_boost_tracks": foley_boosts,
            "tracks": [
                {"track_name": "Dialogue", "gain_db": 0.0, "compression_ratio": "3:1"},
                {"track_name": "Foley_FX", "gain_db": 2.5, "high_pass_filter_hz": 80},
                {"track_name": "BGM_Leitmotif", "gain_db": -6.0, "ducking_enabled": True},
            ],
        },
    }


def stage8_audio_mastering_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 8：全息音频工程配置、拟音强化与动态 Ducking 避让。"""
    ep_num = state.current_visual_episode or 1
    script = state.completed_screenplays.get(ep_num) or {}
    shots = state.episode_storyboards.get(ep_num) or []
    props_list = state.environments_and_props.get("props", [])

    logger.info("【阶段 8 混音工程】开始执行第 %s 集声学混音工程与动态 Ducking 避让计算...", ep_num)

    shots_summary = [
        {
            "shot_id": getattr(s, "shot_id", i + 1),
            "timecode": getattr(s, "timecode", ""),
            "mode": getattr(s, "generation_mode", "first_last_frame"),
            "audio": getattr(s, "audio", {}),
        }
        for i, s in enumerate(shots)
    ]

    user_prompt = STAGE8_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        script_json=json.dumps(script, ensure_ascii=False),
        shots_summary_json=json.dumps(shots_summary, ensure_ascii=False),
        audio_bible_json=json.dumps(
            state.audio_bible.model_dump() if hasattr(state.audio_bible, "model_dump") else state.audio_bible,
            ensure_ascii=False,
        ),
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE8_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage8_fallback(ep_num, props_list, shots),
    )

    mastering_config = result_json.get("mastering_config") or _stage8_fallback(ep_num, props_list, shots)["mastering_config"]
    if "ducking_events" not in mastering_config or not mastering_config["ducking_events"]:
        extracted = _extract_ducking_events_from_shots(shots)
        mastering_config["ducking_events"] = extracted or _stage8_fallback(ep_num, props_list, shots)["mastering_config"].get("ducking_events", [])

    logger.debug(
        "【阶段 8 混音工程】第 %s 集配置完成: 目标响度 %s LUFS, Ducking 避让事件数: %s",
        ep_num,
        mastering_config.get("target_lufs", -23.0),
        len(mastering_config.get("ducking_events", [])),
    )

    masterings = dict(state.episode_audio_masterings or {})
    masterings[ep_num] = mastering_config

    total_episodes = state.total_episodes or 5
    is_last_episode = ep_num >= total_episodes

    next_visual_ep = ep_num if is_last_episode else ep_num + 1
    next_stage = 8 if is_last_episode else 6
    next_journey = "completed" if is_last_episode else "journey_2_visual"

    logger.info(
        "【阶段 8 混音工程】第 %s 集已完成母带混音。全季状态推进 -> Journey: %s, Stage: %s, Next Ep: %s",
        ep_num,
        next_journey,
        next_stage,
        next_visual_ep,
    )

    return {
        "current_stage": next_stage,
        "current_visual_episode": next_visual_ep,
        "journey": next_journey,
        "episode_audio_masterings": masterings,
    }
