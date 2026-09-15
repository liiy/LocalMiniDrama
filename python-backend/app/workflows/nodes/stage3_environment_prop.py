"""阶段 3：空间物证与声学物理节点 (Stage 3 Environments & Props Node)。"""
from __future__ import annotations

from typing import Any

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.prompts.master_sop_prompts import (
    STAGE3_SYSTEM_PROMPT,
    STAGE3_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json


def _stage3_fallback(title: str) -> dict[str, Any]:
    return {
        "environments": [
            {
                "location_name": "滨海旧码头7号废弃保税仓库",
                "time_and_lighting": "午夜23点，暴雨雷鸣，高窗透入惨白闪电与昏黄钠灯对冲",
                "visual_prompt": "废弃潮湿集装箱仓库，生锈铁皮屋顶，地面雨水倒影，电影胶片暗黑悬疑感",
                "weathering_layers": {
                    "structural": "锈蚀斑驳的工字钢立柱，剥落红砖墙",
                    "living": "散落的湿透防雨布、带泥脚印与揉烂的万宝路烟盒",
                    "optical": "暴风雨水汽在昏黄钠灯下形成弥漫雾气与丁达尔光束",
                },
                "atmosphere": "死寂、极度压抑、杀机暗伏",
            },
            {
                "location_name": "韩氏集团顶层董事长办公室",
                "time_and_lighting": "傍晚黄昏，血红晚霞穿透整面落地玻璃窗，室内未开大灯",
                "visual_prompt": "极简奢华顶层大平层办公室，全景落地窗映照血红晚霞，冷色大理石地面",
                "weathering_layers": {
                    "structural": "极简冷灰钛金边框与黑白大理石",
                    "living": "雪茄烟灰缸里只余半截古巴雪茄，细微的指甲刮痕在红木办公桌角",
                    "optical": "夕阳逆光将人影拉长如刀锋，明暗高反差阴影",
                },
                "atmosphere": "权力窒息、居高临下的审判感",
            },
        ],
        "props": [
            {
                "name": "染血的加密U盘钥匙扣",
                "type": "narrative_reversal",
                "description": "钛合金军工级加密U盘，伪装成钥匙扣，表面有干涸呈暗褐色的指纹血迹",
                "visual_prompt": "金属微距特写，冷光下的磨砂钛金属U盘，钥匙环处带有一抹刺目暗褐血迹",
                "damage_scale": "USB金属插口处有一道被硬物暴力撬过的微小凹痕，芯片引脚微变形",
                "foley_resistance": "金属与钥匙环剧烈碰撞的清脆撞击声 (+3dB)，插入机箱的阻尼卡嗒声",
            }
        ],
        "short_memory_c": "【短期记忆便签 C】主场景:7号废弃仓库(三层做旧水汽); 核心物证:染血加密U盘(+3dB金属撞击拟音); 物证与空间就绪",
    }


def stage3_environment_prop_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 3：空间三层做旧与核心反转物证设计。"""
    chars_list = state.characters_engine.get("characters", [])
    chars_summary = "; ".join([
        f"{c.get('name')}({c.get('role_type')}, 随身物:{c.get('carried_anchor_item', {}).get('item_name', '无')})"
        for c in chars_list
    ]) or "主角与反派"

    user_prompt = STAGE3_USER_PROMPT_TEMPLATE.format(
        title=state.selected_title,
        logline=state.logline,
        characters_summary=chars_summary,
        short_memory_b=state.short_memory_b,
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE3_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage3_fallback(state.selected_title),
    )

    envs = result_json.get("environments") or []
    props = result_json.get("props") or []
    short_mem_c = result_json.get("short_memory_c") or f"【短期记忆便签 C】空间与物证已配置完毕"

    return {
        "current_stage": 3,
        "environments_and_props": {"environments": envs, "props": props},
        "short_memory_c": short_mem_c,
    }
