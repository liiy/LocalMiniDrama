"""阶段 8：全息声学混音工程与自动化避让节点 (Stage 8 Audio Mastering Node)。

严格遵循 SKILL.md：
- 对白轨 (Dialogue) / 拟音轨 (Foley FX, +2.0dB~+3.0dB) / 配乐轨 (BGM, -12dB Ducking 避让)；
- 严格遵循 -23 LUFS 广播级响度基准，真峰值限制在 -1.0 dBTP；
- 完成后落库并推进第二程集数游标。
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.prompts.master_sop_prompts import STAGE8_SYSTEM_PROMPT
from app.workflows.utils.llm_bridge import call_llm_json


def _stage8_fallback(episode_num: int) -> dict[str, Any]:
    return {
        "episode_num": episode_num,
        "mastering_config": {
            "target_lufs": -23.0,
            "peak_limit_dbtp": -1.0,
            "ducking_strategy": {
                "dialogue_trigger_attenuation_db": -12.0,
                "attack_time_ms": 35.0,
                "release_time_ms": 250.0,
            },
            "ducking_events": [
                {
                    "start_sec": 2.5,
                    "end_sec": 6.0,
                    "target_track": "BGM_Leitmotif",
                    "gain_db": -12.0,
                    "description": "对白段落侧链避让",
                },
                {
                    "start_sec": 6.0,
                    "end_sec": 9.0,
                    "target_track": "BGM_Leitmotif",
                    "gain_db": -14.0,
                    "description": "物证对白段落深度避让",
                },
            ],
            "foley_boost_tracks": [
                {
                    "item": "染血加密U盘钥匙扣",
                    "boost_db": 3.0,
                    "reason": "工业规范：强化核心反转物证与金属碰撞清脆质感",
                },
                {
                    "item": "手枪枪栓上膛",
                    "boost_db": 2.5,
                    "reason": "强化开篇3秒杀机动作阻力拟音",
                },
            ],
            "tracks": [
                {"track_name": "Dialogue", "gain_db": 0.0, "compression_ratio": "3:1"},
                {"track_name": "Foley_FX", "gain_db": 2.5, "high_pass_filter_hz": 80},
                {"track_name": "BGM_Leitmotif", "gain_db": -6.0, "ducking_enabled": True},
            ],
        },
    }


def stage8_audio_mastering_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 8：全息音频工程配置与响度避让。"""
    ep_num = state.current_visual_episode or 1
    script = state.completed_screenplays.get(ep_num) or {}
    shots = state.episode_storyboards.get(ep_num) or []
    shots_summary = [
        {"shot_id": s.shot_id, "mode": s.generation_mode, "audio": s.audio}
        for s in shots
    ]

    user_prompt = f"""【当前视听集数】第 {ep_num} 集
【单集文学剧本】
{json.dumps(script, ensure_ascii=False)}

【单集分镜音频标注】
{json.dumps(shots_summary, ensure_ascii=False)}

【阶段 4 音乐主题动机库】
{json.dumps(state.audio_bible.model_dump() if hasattr(state, 'audio_bible') else {}, ensure_ascii=False)}

请输出阶段 8 混音母带工程、拟音强化与 -12dB 避让配置纯 JSON 结构体："""

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE8_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage8_fallback(ep_num),
    )

    mastering_config = result_json.get("mastering_config") or _stage8_fallback(ep_num)["mastering_config"]
    if "ducking_events" not in mastering_config:
        mastering_config["ducking_events"] = _stage8_fallback(ep_num)["mastering_config"].get("ducking_events", [])

    masterings = dict(state.episode_audio_masterings or {})
    masterings[ep_num] = mastering_config

    total_episodes = state.total_episodes or 5
    is_last_episode = ep_num >= total_episodes

    next_visual_ep = ep_num if is_last_episode else ep_num + 1
    next_stage = 8 if is_last_episode else 6
    next_journey = "completed" if is_last_episode else "journey_2_visual"

    return {
        "current_stage": next_stage,
        "current_visual_episode": next_visual_ep,
        "journey": next_journey,
        "episode_audio_masterings": masterings,
    }
