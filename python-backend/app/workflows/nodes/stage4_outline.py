"""阶段 4：全季大纲与钩子架构节点 (Stage 4 Outline & Hook Architecture Node)。"""
from __future__ import annotations

from typing import Any

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.prompts.master_sop_prompts import (
    STAGE4_SYSTEM_PROMPT,
    STAGE4_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json


def _stage4_fallback(title: str, total_episodes: int) -> dict[str, Any]:
    episodes_outline = []
    for ep in range(1, total_episodes + 1):
        episodes_outline.append({
            "episode_number": ep,
            "title": f"第{ep}集：{'生死逆袭' if ep == 1 else '暗流涌动' if ep == 2 else '致命绝杀'}",
            "mini_arc_id": f"Arc_{(ep - 1) // 3 + 1}",
            "three_second_hook": f"开局0-3秒：特写冰冷枪口抵住主角额头，倒计时心跳声轰鸣",
            "plot_summary": f"第{ep}集故事推进：主角在绝境中寻找生机，揭开关键线索",
            "a_plot": f"主线对抗：与反派周旋，争取解密U盘的关键时间",
            "b_plot": f"暗线心理：内心对当年背叛真相的痛苦挣扎与心结",
            "climax_reversal": f"第{ep}集爆发点：原本以为的安全屋突然被重兵包围",
            "cliffhanger": f"片尾卡点钩子：突然从黑暗中传来死者的熟悉声音",
            "hook_density_score": 9.2,
        })

    return {
        "season_outline": {
            "total_episodes": total_episodes,
            "core_conflict": "在72小时内粉碎假死复仇陷阱并夺回控制权",
            "rhythm_pacing_curve": "3波次递增结构，每3集完成一次生死反转小高潮",
            "episodes": episodes_outline,
        },
        "short_memory_d": f"【短期记忆便签 D】全季共{total_episodes}集大纲架构就绪; 严格贯彻3秒抓手与生死断钩; 准备交付第一程蓝军硬指标自检",
    }


def stage4_outline_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 4：全季分集大纲与钩子密度架构。"""
    user_prompt = STAGE4_USER_PROMPT_TEMPLATE.format(
        title=state.selected_title or "都市悬疑短剧",
        total_episodes=state.total_episodes or 12,
        logline=state.logline or "主角追查真相逆风翻盘",
        dramatic_irony=state.dramatic_irony or "越想掩盖越会暴露",
        characters_summary=str(state.characters_engine),
        environments_props_summary=str(state.environments_and_props),
        short_memory_c=state.short_memory_c,
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE4_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage4_fallback(state.selected_title, state.total_episodes or 5),
    )

    raw_outlines = result_json.get("season_outlines")
    season_outlines: dict[int, dict[str, Any]] = {}
    if isinstance(raw_outlines, dict):
        for k, v in raw_outlines.items():
            try:
                ep_num = int(k)
                if isinstance(v, dict):
                    v["episode_number"] = ep_num
                season_outlines[ep_num] = v
            except (ValueError, TypeError):
                continue
    elif isinstance(raw_outlines, list):
        for idx, ep in enumerate(raw_outlines, start=1):
            ep_num = int(ep.get("episode_number") or idx) if isinstance(ep, dict) else idx
            season_outlines[ep_num] = ep if isinstance(ep, dict) else {"content": ep}
    else:
        season_outline = result_json.get("season_outline") or {}
        episodes = season_outline.get("episodes") or []
        for idx, ep in enumerate(episodes, start=1):
            ep_num = int(ep.get("episode_number") or idx) if isinstance(ep, dict) else idx
            season_outlines[ep_num] = ep

    audio_bible = result_json.get("audio_bible") or {}
    short_mem_d = result_json.get("short_memory_d") or f"【短期记忆便签 D】分集大纲规划完毕"

    return {
        "current_stage": 4,
        "season_outlines": season_outlines,
        "audio_bible": audio_bible,
        "short_memory_d": short_mem_d,
    }
