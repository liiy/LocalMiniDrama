"""阶段 3：空间物证与声学物理节点 (Stage 3 Environments & Props Node)。

本模块严格对齐《AI 原创连续剧短剧工业管线标准作业程序 (SKILL1.md v10.0.0)》：
- 【规则编号: STAGE-3-COT-01】空间分级规划：一级核心主场景（>=3场）与二级过渡次场景；
- 【规则编号: STAGE-3-COT-02】场景与服装同源共振铁律：空间破损脏旧度与角色服装磨损度 100% 同频；
- 【规则编号: STAGE-3-COT-03】空间三层做旧架构（建筑结构层 / 生活做旧层 / 光影介质层）；
- 【规则编号: STAGE-3-COT-04】核心物证微观破损尺度与阻尼拟音（显式 +2.0dB ~ +3.0dB 标记）；
- 【规则编号: STAGE-3-OUT-01】写入 environments_and_props 并封装【短期记忆便签 C】。
"""
from __future__ import annotations

import logging
from typing import Any

from app.schemas.script_graph_state import IndustrialDramaState
from app.workflows.prompts.master_sop_prompts import (
    STAGE3_SYSTEM_PROMPT,
    STAGE3_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage3_env_prop")


def _stage3_fallback(
    title: str,
    logline: str,
    characters: list[dict[str, Any]],
) -> dict[str, Any]:
    """当大模型离线或解析异常时的保底生成工厂，产出具有三层做旧与声学阻尼的空间物证。
    
    【规则编号: STAGE-3-COT-03】三层做旧架构；
    【规则编号: STAGE-3-COT-04】核心物证破损尺度与 +3.0dB 阻尼拟音。
    """
    logger.warning(f"Triggering Stage 3 dynamic fallback env/prop synthesizer for '{title}'.")
    
    p_name = "主角"
    a_name = "反派"
    p_anchor_name = "刻有划痕的旧信物"
    a_anchor_name = "百年沉香手串"

    if characters:
        for c in characters:
            if c.get("role_type") == "protagonist":
                p_name = c.get("name", "主角")
                p_anchor_name = c.get("carried_anchor_item", {}).get("item_name") or p_anchor_name
            elif c.get("role_type") == "antagonist":
                a_name = c.get("name", "反派")
                a_anchor_name = c.get("carried_anchor_item", {}).get("item_name") or a_anchor_name

    logger.debug(f"[Stage 3 Fallback] p_name={p_name}, a_name={a_name}, anchor={p_anchor_name}")

    return {
        "environments": [
            {
                "location_name": f"{title}核心决战隐秘废弃仓库",
                "time_and_lighting": "午夜23点，暴雨雷鸣，高窗透入惨白闪电与昏黄钠灯对冲",
                "visual_prompt": f"cinematic moody interior, weathered industrial brick and steel warehouse for {title}, puddles reflecting gloomy sodium light, volumetric dust rays, 8k raw photo",
                "weathering_layers": {
                    "structural": "锈蚀斑驳的工字钢立柱，剥落红砖墙露出内部泛黄水泥",
                    "living": f"散落的湿透防雨布、带泥脚印（与{p_name}工装靴底泥斑100%同源）与掐灭的烟头，墙角堆放受潮木箱",
                    "optical": "暴风雨水汽在昏黄钠灯下形成弥漫雾气与丁达尔光束，逆光高对比度",
                },
                "atmosphere": f"死寂、极度压抑、围绕《{title}》真相的决死对峙一触即发",
            },
            {
                "location_name": f"{a_name}顶层集团私人会客厅",
                "time_and_lighting": "傍晚黄昏，血红晚霞穿透整面落地玻璃窗，室内未开大灯",
                "visual_prompt": f"cinematic high contrast penthouse office for {a_name}, panoramic floor-to-ceiling window glowing with sunset blood orange light, polished marble reflection",
                "weathering_layers": {
                    "structural": "极简冷灰钛金边框与黑白大理石地面，无缝拼接墙板",
                    "living": f"雪茄烟灰缸里余半截雪茄，红木桌角有细微指甲划痕，与{a_name}手串摩擦痕迹呼应",
                    "optical": "夕阳逆光将人影拉长如刀锋，明暗高反差长阴影与冷酷剪影",
                },
                "atmosphere": "权力窒息、居高临下的冰冷审判感",
            },
        ],
        "props": [
            {
                "name": f"《{title}》关键反转物证",
                "type": "narrative_reversal",
                "description": f"记录《{title}》所有真相的核心物证，表面有干涸呈暗褐色的指纹血痕",
                "visual_prompt": f"macro close up of key evidence for {title}, cold metallic rim lighting, scratches, dark brown dried blood stain, ultra photorealistic 8k",
                "damage_scale": "物证边缘有一道被硬物暴力磕碰的微小凹痕，角质微变形",
                "foley_resistance": "金属与硬物剧烈碰撞的清脆撞击声 (+3.0dB)，摩擦阻尼沙沙声",
            },
            {
                "name": p_anchor_name,
                "type": "emotional_cipher",
                "description": f"{p_name}常年随身携带的旧物，承载着不可磨灭的过去与创伤",
                "visual_prompt": f"macro close up of {p_anchor_name}, worn surface with fine scratches, spiderweb cracks, cinematic texture",
                "damage_scale": "表面有细微裂痕与严重氧化包浆",
                "foley_resistance": "开合或触碰时金属簧片回弹声 (+2.0dB)，衣料摩擦微响",
            },
        ],
        "short_memory_c": (
            f"【短期记忆便签 C】主场景:{title}核心决战隐秘废弃仓库(三层做旧水汽+与{p_name}服装泥斑同源); "
            f"核心物证:《{title}》关键反转物证(+3.0dB金属撞击拟音)+{p_anchor_name}(旧情密码); 空间与物证就绪"
        ),
    }


def stage3_environment_prop_node(state: Any) -> dict[str, Any]:
    """执行阶段 3：空间三层做旧与核心反转物证设计。
    
    【公共硬性约束 1 & 4】大模型与节点内部不执行任何业务分支跳转。
    【公共硬性约束 3】统一入参 state 符合 IndustrialDramaState 契约，返回增量状态字典。
    【规则编号: STAGE-3-COT-01 ~ STAGE-3-OUT-01】全息空间物证建模。
    """
    selected_title = state.get("selected_title") or "都市短剧"
    logline = state.get("logline") or "主角在逆境中探寻真相"
    short_memory_b = state.get("short_memory_b") or ""
    chars_engine = state.get("characters_engine") or {}
    chars_list = chars_engine.get("characters", []) if isinstance(chars_engine, dict) else []

    logger.info(f"[Stage 3 Node] Generating environments and props for: '{selected_title}'")
    logger.debug(f"[Stage 3 Node] Input state characters count: {len(chars_list)}")
    
    # 【规则编号: STAGE-3-COT-02】提取角色服装与随身物，为场景与服装同源共振提供输入基准
    chars_summary_items = []
    for c in chars_list:
        c_name = c.get("name", "未命名")
        c_role = c.get("role_type", "角色")
        c_anchor = c.get("carried_anchor_item", {}).get("item_name", "无")
        c_costume = c.get("lived_in_costume", {}).get("top_wear", "无")
        chars_summary_items.append(f"{c_name}({c_role}, 随身物:{c_anchor}, 服装:{c_costume})")
    
    chars_summary = "; ".join(chars_summary_items) or "主角与反派"
    logger.debug(f"[Stage 3 Node] Prepared characters summary: {chars_summary}")

    user_prompt = STAGE3_USER_PROMPT_TEMPLATE.format(
        title=selected_title,
        logline=logline,
        characters_summary=chars_summary,
        short_memory_b=short_memory_b,
    )

    logger.debug(f"[Stage 3 Node] Calling LLM with prompt length: {len(user_prompt)}")

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE3_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage3_fallback(
            selected_title, logline, chars_list
        ),
    )

    # 【规则编号: STAGE-3-OUT-01】提取并组装阶段 3 标准输出
    envs = result_json.get("environments") or []
    props = result_json.get("props") or []
    short_mem_c = result_json.get("short_memory_c") or f"【短期记忆便签 C】空间与物证已配置完毕"

    logger.info(f"[Stage 3 Node] Completed envs/props. Envs: {len(envs)}, Props: {len(props)}")
    logger.debug(f"[Stage 3 Node] Short memory C: {short_mem_c}")

    return {
        "current_stage": 3,
        "environments_and_props": {"environments": envs, "props": props},
        "short_memory_c": short_mem_c,
    }

