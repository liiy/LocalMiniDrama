"""阶段 1：题材破壁与工业化立项节点 (Stage 1 Ideation Node)。"""
from __future__ import annotations

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


def _stage1_fallback(user_idea: str, genre: str, total_eps: int) -> dict[str, Any]:
    base_title = user_idea[:8] if user_idea else "致命真相"
    return {
        "selected_title": f"{base_title}之局",
        "candidate_titles": {
            "identity_contrast": [f"{base_title}之局", "反转人生"],
            "extreme_suspense": ["深渊倒计时", "404熔炉"],
            "prop_irony": ["带血的证据", "破碎的工牌"],
            "dark_psychology": ["第三个假面", "无声暗涌"],
        },
        "visual_style": "真人电影/工业冷峻暗色调/超写实",
        "aspect_ratio": "9:16",
        "target_duration_sec": 120.0,
        "total_episodes": total_eps or 12,
        "logline": f"围绕{base_title}展开的生死智斗与真相逆袭。",
        "dramatic_irony": "观众预知暗桩背叛，主角一步步逼近陷阱却在绝境完成致命反杀。",
        "grand_payoff": "在终局熔炉火光下彻底撕碎十五年伪证，揭露最高上位者的罪证。",
        "negative_rules": {
            "forbidden_cliches": DoubleTrackProhibitions().forbidden_cliches,
            "forbidden_cheap_pleasures": DoubleTrackProhibitions().forbidden_cheap_pleasures,
        },
        "short_memory_a": f"【短期记忆便签 A】主剧名:{base_title}之局; 风格:冷峻暗色调; 核心讽刺:全知视角已知真凶; 严格坚守双轨禁令",
    }


def stage1_ideation_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 1：题材破壁、四大商业维度片名矩阵与双轨禁令确立。"""
    user_idea = state.logline or state.selected_title or "都市悬疑反转短剧"
    user_prompt = STAGE1_USER_PROMPT_TEMPLATE.format(
        user_idea=user_idea,
        genre="悬疑/犯罪/商业反转",
        total_episodes=state.total_episodes or 12,
        target_duration_sec=state.target_duration_sec or 120.0,
        visual_style=state.visual_style or "真人电影/工业冷峻暗色调/超写实",
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE1_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage1_fallback(user_idea, "悬疑", state.total_episodes or 12),
    )

    candidate_matrix_data = result_json.get("candidate_titles") or {}
    candidate_titles = CandidateTitleMatrix.model_validate(candidate_matrix_data) if candidate_matrix_data else CandidateTitleMatrix()

    neg_data = result_json.get("negative_rules") or {}
    negative_rules = DoubleTrackProhibitions.model_validate(neg_data) if neg_data else DoubleTrackProhibitions()

    return {
        "current_stage": 1,
        "journey": "journey_1_literary",
        "selected_title": result_json.get("selected_title") or state.selected_title or "未命名项目",
        "candidate_titles": candidate_titles,
        "visual_style": result_json.get("visual_style") or state.visual_style,
        "aspect_ratio": result_json.get("aspect_ratio") or state.aspect_ratio,
        "target_duration_sec": float(result_json.get("target_duration_sec") or state.target_duration_sec or 120.0),
        "total_episodes": int(result_json.get("total_episodes") or state.total_episodes or 12),
        "logline": result_json.get("logline") or state.logline,
        "dramatic_irony": result_json.get("dramatic_irony") or state.dramatic_irony,
        "grand_payoff": result_json.get("grand_payoff") or state.grand_payoff,
        "negative_rules": negative_rules,
        "short_memory_a": result_json.get("short_memory_a") or f"【短期记忆便签 A】已确立双轨禁令与核心讽刺: {state.dramatic_irony}",
    }
