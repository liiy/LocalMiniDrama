"""阶段 4：全季大纲与音乐动机母库节点 (Stage 4 Outline & Hook Architecture Node)。

严格遵循 SKILL.md：
1. 输出 3 套具象音乐主题动机母库 (04_audio_bible.json)：
   - LEITMOTIF_01_SUSPENSE (悬疑压迫/阶层窒息)
   - LEITMOTIF_02_TRAUMA (情感创伤/未竟心结)
   - LEITMOTIF_03_COUNTERATTACK (绝境反杀/终局核爆)
2. 工笔级分集任务卡（前3秒视觉动作抓手 + 45秒微反转认知打破 + 主角谎言崩解度 + 115秒生死绝杀断点）；
3. 封装【短期记忆便签 D】并向下游波次推进。
"""
from __future__ import annotations

import logging
from typing import Any

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.prompts.master_sop_prompts import (
    STAGE4_SYSTEM_PROMPT,
    STAGE4_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage4_outline")


def _stage4_fallback(
    title: str,
    total_episodes: int,
    characters: list[dict[str, Any]],
    props: list[dict[str, Any]],
) -> dict[str, Any]:
    """当大模型离线或解析异常时的保底大纲生成工厂。"""
    logger.warning(f"Triggering Stage 4 dynamic fallback outline/audio synthesizer for '{title}'.")

    p_name = characters[0].get("name", "主角") if characters else "主角"
    a_name = characters[1].get("name", "反派") if len(characters) > 1 else "反派"
    hero_prop = props[0].get("name", "关键物证") if props else "关键物证"

    audio_bible = {
        "leitmotifs": [
            {
                "motif_id": "LEITMOTIF_01_SUSPENSE",
                "name": "悬疑压迫与阶层窒息",
                "instrumentation": "低音大提琴单音震音 + 工业管道微弱回响 + 40Hz次低频脉冲",
                "tempo_bpm": "72-85",
                "musical_key": "D minor",
                "dramatic_function": "危机潜行、搜寻线索与真凶逼近时触发",
            },
            {
                "motif_id": "LEITMOTIF_02_TRAUMA",
                "name": "情感创伤与未竟心结",
                "instrumentation": "老式立式钢琴(带毛毡阻音) + 独奏中提琴 + 模拟卡带底噪",
                "tempo_bpm": "60-68",
                "musical_key": "A minor",
                "dramatic_function": "主角凝视随身旧物、直面过去创伤时触发",
            },
            {
                "motif_id": "LEITMOTIF_03_COUNTERATTACK",
                "name": "绝境反杀与终局核爆",
                "instrumentation": "重击失真底鼓 + 工业金属交响打击乐 + 锐利电吉他长音",
                "tempo_bpm": "110-120",
                "musical_key": "E minor",
                "dramatic_function": "主角撕毁伪证、反打脸或绝境突围时触发",
            },
        ],
        "foley_rules": {
            "boost": "+2.0dB ~ +3.0dB 物理拟音放大",
            "clarity": "-23 LUFS 广播级响度基准",
        },
    }

    season_outlines: dict[str, Any] = {}
    for ep in range(1, total_episodes + 1):
        if ep == 1:
            ep_title = f"第1集：{title}的致命序曲"
            hook = f"开局0-3秒：暴雨中黑漆手枪顶在{p_name}额头，惨白闪电下高颧骨阴影明显，冷汗顺着下唇滑落"
            turning = f"45秒认知打破：{p_name}在暗处摸索到{hero_prop}的破碎边缘，发现真凶竟在现场"
            lie_metric = "谎言坚冰期：坚信自己绝不会动摇理性防线"
            cliff = f"115秒绝杀：{a_name}带保镖破门而入，枪口齐刷刷对准{p_name}的眉心"
        elif ep == total_episodes:
            ep_title = f"第{ep}集：终局核爆与血色救赎"
            hook = f"开局0-3秒：{p_name}将{hero_prop}当众拍碎在谈判桌上，金属碎屑飞溅"
            turning = f"45秒高潮逆袭：当众揭露三十年前全部罪证，彻底瓦解{a_name}的权势帝国"
            lie_metric = "谎言彻底解体：坦然拥抱真实的自我与代价，完成终极救赎"
            cliff = "全剧终局定格：黎明第一缕阳光穿透破旧仓库，照亮释然挺立的身影"
        else:
            ep_title = f"第{ep}集：暗流交锋与层层撕裂"
            hook = f"开局0-3秒：急速推镜头，{p_name}在昏暗回廊中被利刃逼近喉管"
            turning = f"45秒微反转：{p_name}借用随身旧物反手制敌，逼问出下一道关键线索"
            lie_metric = f"谎言崩解度 {ep * 20}%：旧信念不断产生裂痕"
            cliff = f"115秒卡点：黑暗中突然响起当年受害者的绝密通话录音"

        season_outlines[str(ep)] = {
            "title": ep_title,
            "episode_number": ep,
            "hook_3s": hook,
            "three_second_hook": hook,
            "micro_turning_point_45s": turning,
            "relational_shift_point": f"{p_name} 与 {a_name} 之间的生死信任/对立再次发生不可逆质变",
            "lie_erosion_metric": lie_metric,
            "subtext_matrix": {
                "surface_excuse": "表层借口：核对普通账目与例行业务交接",
                "core_intention": f"深层企图：试探对方是否掌握《{title}》核心秘密",
                "forbidden_words": ["认输", "当年真相", "我错了"],
            },
            "killer_cliffhanger_115s": cliff,
            "cliffhanger": cliff,
        }

    return {
        "audio_bible": audio_bible,
        "season_outlines": season_outlines,
        "short_memory_d": (
            f"【短期记忆便签 D】全季共{total_episodes}集大纲架构就绪; 3大音乐动机已锁死; "
            f"严格贯彻前3s抓手与115s生死断钩; 准备进入阶段 5 Mini-Arc 波次生成"
        ),
    }


def stage4_outline_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 4：全季分集大纲与音乐主题动机母库确立。"""
    total_eps = state.total_episodes or 12
    logger.info(f"[Stage 4 Node] Generating outline and audio bible for '{state.selected_title}' (Total Eps: {total_eps})")

    chars_list = state.characters_engine.get("characters", [])
    props_list = state.environments_and_props.get("props", [])

    user_prompt = STAGE4_USER_PROMPT_TEMPLATE.format(
        title=state.selected_title or "都市悬疑短剧",
        total_episodes=total_eps,
        logline=state.logline or "主角追查真相逆风翻盘",
        dramatic_irony=state.dramatic_irony or "越想掩盖越会暴露",
        characters_summary=str(state.characters_engine),
        environments_props_summary=str(state.environments_and_props),
        short_memory_c=state.short_memory_c,
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE4_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage4_fallback(
            state.selected_title or "绝密之局", total_eps, chars_list, props_list
        ),
    )

    raw_outlines = result_json.get("season_outlines")
    season_outlines: dict[int, dict[str, Any]] = {}
    if isinstance(raw_outlines, dict):
        for k, v in raw_outlines.items():
            try:
                ep_num = int(k)
                if isinstance(v, dict):
                    v["episode_number"] = ep_num
                    if "hook_3s" in v and "three_second_hook" not in v:
                        v["three_second_hook"] = v["hook_3s"]
                    elif "three_second_hook" in v and "hook_3s" not in v:
                        v["hook_3s"] = v["three_second_hook"]
                    if "killer_cliffhanger_115s" in v and "cliffhanger" not in v:
                        v["cliffhanger"] = v["killer_cliffhanger_115s"]
                    elif "cliffhanger" in v and "killer_cliffhanger_115s" not in v:
                        v["killer_cliffhanger_115s"] = v["cliffhanger"]
                season_outlines[ep_num] = v
            except (ValueError, TypeError):
                continue
    elif isinstance(raw_outlines, list):
        for idx, ep in enumerate(raw_outlines, start=1):
            ep_num = int(ep.get("episode_number") or idx) if isinstance(ep, dict) else idx
            if isinstance(ep, dict):
                if "hook_3s" in ep and "three_second_hook" not in ep:
                    ep["three_second_hook"] = ep["hook_3s"]
                elif "three_second_hook" in ep and "hook_3s" not in ep:
                    ep["hook_3s"] = ep["three_second_hook"]
                if "killer_cliffhanger_115s" in ep and "cliffhanger" not in ep:
                    ep["cliffhanger"] = ep["killer_cliffhanger_115s"]
                elif "cliffhanger" in ep and "killer_cliffhanger_115s" not in ep:
                    ep["killer_cliffhanger_115s"] = ep["cliffhanger"]
            season_outlines[ep_num] = ep if isinstance(ep, dict) else {"content": ep}
    else:
        season_outline = result_json.get("season_outline") or {}
        episodes = season_outline.get("episodes") or []
        for idx, ep in enumerate(episodes, start=1):
            ep_num = int(ep.get("episode_number") or idx) if isinstance(ep, dict) else idx
            if isinstance(ep, dict):
                if "hook_3s" in ep and "three_second_hook" not in ep:
                    ep["three_second_hook"] = ep["hook_3s"]
                elif "three_second_hook" in ep and "hook_3s" not in ep:
                    ep["hook_3s"] = ep["three_second_hook"]
                if "killer_cliffhanger_115s" in ep and "cliffhanger" not in ep:
                    ep["cliffhanger"] = ep["killer_cliffhanger_115s"]
                elif "cliffhanger" in ep and "killer_cliffhanger_115s" not in ep:
                    ep["killer_cliffhanger_115s"] = ep["cliffhanger"]
            season_outlines[ep_num] = ep

    audio_bible = result_json.get("audio_bible") or _stage4_fallback(
        state.selected_title or "绝密之局", total_eps, chars_list, props_list
    )["audio_bible"]
    
    short_mem_d = result_json.get("short_memory_d") or (
        f"【短期记忆便签 D】全季共{len(season_outlines)}集分集大纲规划完毕; 3大动机已锁死; 进入阶段 5"
    )

    logger.info(f"[Stage 4 Node] Completed outline. Episodes generated: {len(season_outlines)}")

    return {
        "current_stage": 4,
        "season_outlines": season_outlines,
        "audio_bible": audio_bible,
        "short_memory_d": short_mem_d,
    }
