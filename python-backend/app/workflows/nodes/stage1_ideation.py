"""阶段 1：题材破壁与工业化立项节点 (Stage 1 Ideation Node)。

严格遵循《AI 原创短剧工业全息 SOP 标准》(SKILL.md)：
1. 四大商业维度候选片名矩阵（身份反差、悬念钩子、物证讽刺、心理反杀）；
2. 30-45 字工业级 Logline（具象人物 + 危机 + 对抗 + 动作手段）；
3. 核心戏剧讽刺 (The Dramatic Irony) 与 终局核爆点 (Grand Payoff)；
4. 针对本剧推演的 10 大绝对禁止俗套 + 3 大廉价爽点双轨禁令；
5. 封装沉淀【短期记忆便签 A】并下传阶段 2。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.schemas.script_graph_state import (
    CandidateTitleMatrix,
    DoubleTrackProhibitions,
    IndustrialDramaMasterState,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE1_SYSTEM_PROMPT,
    STAGE1_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage1_ideation")


def _stage1_fallback(user_idea: str, genre: str, total_eps: int) -> dict[str, Any]:
    """大模型解析异常或离线时的动态保底工厂，基于用户输入动态提纯立项资产。"""
    logger.warning("Triggering Stage 1 dynamic fallback ideation synthesizer.")
    # 动态提取关键词
    clean_idea = (user_idea or "都市悬疑生死对决").strip()
    words = re.findall(r"[\u4e00-\u9fa5]{2,6}", clean_idea)
    key_subject = words[0] if words else "绝命对决"
    key_object = words[1] if len(words) > 1 else "神秘物证"

    base_title = f"{key_subject}之局" if len(key_subject) <= 4 else key_subject

    return {
        "selected_title": base_title,
        "candidate_titles": {
            "identity_contrast": [f"{key_subject}：上位法则", f"逆流而上的{key_subject}"],
            "extreme_suspense": [f"第7封{key_object}", f"{key_subject}的生死48小时"],
            "prop_irony": [f"带血的{key_object}", f"破碎的{key_object}"],
            "dark_psychology": [f"第3个假面", f"{key_subject}的向死而生"],
        },
        "visual_style": "真人电影/工业冷峻暗色调/超写实胶片质感",
        "aspect_ratio": "9:16",
        "target_duration_sec": 120.0,
        "total_episodes": total_eps or 12,
        "logline": f"围绕{key_subject}与{key_object}展开的生死智斗，主角在绝境迷局中撕破谎言逆风翻盘。",
        "dramatic_irony": f"观众预知{key_object}背后的致命暗线，反派在自鸣得意中一步步踏入早已布好的天罗地网。",
        "grand_payoff": f"在全剧终局决战场景，主角当众引爆{key_object}的核心铁证，让背叛者付出不可承受的代价。",
        "negative_rules": {
            "forbidden_cliches": [
                f"1. 严禁出现关于{key_object}的关键证据刚好被雨水淋湿或损坏的低级巧合",
                "2. 严禁关键录音设备在关键时刻突然没电的降智设定",
                "3. 严禁核心反派在毫无逻辑支撑下当众自曝罪行",
                "4. 严禁主角依赖机械降神式的天降富豪或突发背景解围",
                "5. 严禁青梅竹马或至亲无脑包庇反派、强行制造家庭伦理狗血",
                "6. 严禁反派在掌握绝对优势时强行废话给主角留逃跑破绽",
                "7. 严禁主角在遭受重创后毫无生理阻力与肉体代价瞬间开挂",
                "8. 严禁毫无因果铺垫的突发车祸失忆老套桥段",
                "9. 严禁警方或执法人员降智配合反派打压主角",
                "10. 严禁以'一切都只是一场梦'或精神分裂作为廉价反转",
            ],
            "forbidden_cheap_pleasures": [
                "1. 严禁一键打脸的无脑狂暴爽，必须经历严密的因果博弈与肉体/情感代价",
                "2. 严禁脸谱化小丑反派下跪求饶的低幼短视情绪垃圾",
                "3. 严禁脱离现实物理法则的凌空飞踢或超自然夸张动作",
            ],
            "persona_redlines": [
                f"1. 严禁将主角塑造为全知全能的伟光正或无脑龙傲天，必须具备致命性格缺陷(Lie)与创伤幽灵(Ghost)",
                f"2. 严禁将核心反派塑造为无脑作恶的脸谱化工具人，反派必须具备逻辑自洽的利益防御体系",
                f"3. 严禁配角沦为推进剧情的降智传话筒，所有出场人物必须有独立欲望与代价计算",
            ],
        },
        "short_memory_a": (
            f"【短期记忆便签 A】主剧名:{base_title}; 核心讽刺:全知视角已知真凶与{key_object}暗线; "
            f"人设红线:拒绝无代价开挂与脸谱化反派; 严格遵守针对本剧推演的双轨禁令清单"
        ),
    }


def stage1_ideation_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 1：题材破壁、四大商业维度片名矩阵与双轨禁令确立。"""
    user_idea = state.logline or state.selected_title or "都市悬疑反转短剧"
    total_eps = state.total_episodes or 12
    logger.info(f"[Stage 1 Node] Starting ideation for: {user_idea[:30]}... (Total Eps: {total_eps})")

    user_prompt = STAGE1_USER_PROMPT_TEMPLATE.format(
        user_idea=user_idea,
        genre=state.genre or "悬疑/复仇",
        total_episodes=total_eps,
        target_duration_sec=state.target_duration_sec or 120.0,
        visual_style=state.visual_style or "真人电影/工业冷峻暗色调/超写实",
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE1_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage1_fallback(user_idea, state.genre or "悬疑", total_eps),
    )

    candidate_matrix_data = result_json.get("candidate_titles") or {}
    candidate_titles = (
        CandidateTitleMatrix.model_validate(candidate_matrix_data)
        if candidate_matrix_data
        else CandidateTitleMatrix()
    )

    neg_data = result_json.get("negative_rules") or {}
    negative_rules = (
        DoubleTrackProhibitions.model_validate(neg_data)
        if neg_data
        else DoubleTrackProhibitions()
    )

    selected_title = result_json.get("selected_title") or state.selected_title or "未命名项目"
    short_mem_a = result_json.get("short_memory_a") or (
        f"【短期记忆便签 A】主剧名:{selected_title}; 核心讽刺:{result_json.get('dramatic_irony', state.dramatic_irony)}; "
        f"人设红线:拒绝无代价开挂与脸谱化反派; 严格遵守双轨禁令"
    )

    logger.info(f"[Stage 1 Node] Completed ideation. Selected Title: '{selected_title}'")

    return {
        "current_stage": 1,
        "journey": "journey_1_literary",
        "selected_title": selected_title,
        "candidate_titles": candidate_titles,
        "visual_style": result_json.get("visual_style") or state.visual_style or "真人电影/工业冷峻暗色调/超写实",
        "aspect_ratio": result_json.get("aspect_ratio") or state.aspect_ratio or "9:16",
        "target_duration_sec": float(result_json.get("target_duration_sec") or state.target_duration_sec or 120.0),
        "total_episodes": int(result_json.get("total_episodes") or total_eps),
        "logline": result_json.get("logline") or state.logline,
        "dramatic_irony": result_json.get("dramatic_irony") or state.dramatic_irony,
        "grand_payoff": result_json.get("grand_payoff") or state.grand_payoff,
        "negative_rules": negative_rules,
        "short_memory_a": short_mem_a,
    }
