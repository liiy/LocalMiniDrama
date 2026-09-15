"""阶段 2：角色人物建模与四元心理节点 (Stage 2 Character Node)。"""
from __future__ import annotations

from typing import Any

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.prompts.master_sop_prompts import (
    STAGE2_SYSTEM_PROMPT,
    STAGE2_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json


def _stage2_fallback(title: str, logline: str) -> dict[str, Any]:
    return {
        "characters": [
            {
                "name": "陆沉",
                "role_type": "protagonist",
                "personality": "敏锐隐忍，极度自律但负罪感深重",
                "appearance": "三十八岁，剑眉下压，右侧额角有浅淡旧伤痕，常穿深灰羊绒大衣，眼神凌厉而疲惫",
                "identity_anchors": ["额角浅旧伤", "深灰羊绒大衣", "深邃双眼"],
                "voice_style": "低沉磁性，咬字克制而清晰，语速中偏慢",
                "psychological_quad": {
                    "want": "亲手挖出当年构陷案真凶，洗清师父冤屈",
                    "need": "直面当年的懦弱选择，接纳不完美的自我并完成自我救赎",
                    "lie": "只要掌控绝对理性和铁证，正义就绝不会被权势玷污",
                    "ghost": "七年前因自己迟到五分钟，导致恩师当场坠亡且现场罪证被毁",
                },
                "voice_fingerprint": {
                    "catchphrase": "说话要有凭据，心跳可瞒不过我。",
                    "defensive_phrase": "这跟我没有任何关系，看报告说话。",
                    "forbidden_words": ["认命", "算了", "对不起"],
                },
                "carried_anchor_item": {
                    "item_name": "停摆的机械怀表",
                    "physical_trace": "表盖右侧有严重凹陷撞痕，指针永远停在23点17分",
                    "emotional_significance": "恩师临终前攥在手心的信物",
                },
            },
            {
                "name": "韩泰",
                "role_type": "antagonist",
                "personality": "表面儒雅慈善，实则冷酷毒辣，视人命为数字筹码",
                "appearance": "五十岁出头，金丝眼镜，银灰三件套定制西装，手腕戴沉香木佛珠",
                "identity_anchors": ["金丝眼镜", "银灰定制西服", "沉香佛珠"],
                "voice_style": "温和谦逊甚至带笑意，却令人不寒而栗",
                "psychological_quad": {
                    "want": "保住集团上市和百亿身家，彻底斩草除根",
                    "need": "承认自己内心的卑怯与贪婪",
                    "lie": "成大事者不拘小节，弱肉强食是世界唯一法则",
                    "ghost": "早年靠窃取死者成果起家的卑微出身",
                },
                "voice_fingerprint": {
                    "catchphrase": "年轻人，时代不欠任何人体面。",
                    "defensive_phrase": "做人要懂大局，别给脸不要脸。",
                    "forbidden_words": ["当年", "小作坊", "偷"],
                },
                "carried_anchor_item": {
                    "item_name": "百年老山檀沉香手串",
                    "physical_trace": "第三颗佛珠有一道被指甲反复抠掐的深痕",
                    "emotional_significance": "每次动杀心时下意识转动的遮羞布",
                },
            },
        ],
        "short_memory_b": f"【短期记忆便签 B】主角陆沉(怀表停摆23:17, 致命愧疚); 反派韩泰(金丝眼镜+佛珠深痕, 伪善大鳄); 冲突核:证据与权势的生死较量",
    }


def stage2_character_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 2：角色心理四元组、语言指纹与随身物设计。"""
    user_prompt = STAGE2_USER_PROMPT_TEMPLATE.format(
        title=state.selected_title,
        logline=state.logline,
        dramatic_irony=state.dramatic_irony,
        grand_payoff=state.grand_payoff,
        visual_style=state.visual_style,
        short_memory_a=state.short_memory_a,
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE2_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage2_fallback(state.selected_title, state.logline),
    )

    chars = result_json.get("characters") or []
    norm_chars = []
    for c in chars:
        v_fp = c.get("voice_fingerprint") or c.get("linguistic_fingerprint") or {}
        c["voice_fingerprint"] = v_fp
        c["linguistic_fingerprint"] = v_fp
        norm_chars.append(c)

    short_mem_b = result_json.get("short_memory_b") or f"【短期记忆便签 B】主角与反派人设已锁定，进入空间道具物证规划"

    return {
        "current_stage": 2,
        "characters_engine": {"characters": norm_chars},
        "short_memory_b": short_mem_b,
    }
