"""阶段 1：题材破壁与工业化立项节点 (Stage 1 Ideation Node)。

严格遵循《AI 原创短剧工业全息 SOP 标准》(SKILL.md)：
1. 【规则编号: STAGE-1-COT-01】针对本题材穷举推演 10 大绝对禁止俗套因果 + 3 大廉价打脸爽点双轨禁令；
2. 【规则编号: STAGE-1-COT-02】30-45 字工业级 Logline（具象人物 + 危机 + 对抗 + 动作手段）与核心戏剧讽刺 (The Dramatic Irony)、终局核爆点 (Grand Payoff)；
3. 【规则编号: STAGE-1-COT-03】四大商业维度（身份反差、悬念钩子、物证讽刺、心理反杀）6-8 个候选片名矩阵；
4. 【规则编号: STAGE-1-OUT-01】封装沉淀【短期记忆便签 A】并下传阶段 2。

【公共硬性约束遵守说明】：
- 节点入参统一为 state (IndustrialDramaState TypedDict 契约)，返回状态增量字典；
- 节点内部绝无业务分支跳转，所有流转完全交由独立条件路由函数处理；
- 关键节点添加丰富 debug 日志。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from app.context.short_memory_service import (
    WorkingMemoryCompiler,
    publish_drama_event,
    publish_drama_read_projection,
    set_journey1_working_memory,
)
from app.schemas.script_graph_state import (
    CandidateTitleMatrix,
    DoubleTrackProhibitions,
    GlobalDramaMasterState,
    IndustrialDramaState,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE1_SYSTEM_PROMPT,
    STAGE1_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json
from app.utils.blueprint import (
    build_blueprint, 
    to_prompt_block
)

logger = logging.getLogger("lmd.stage1_ideation")


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _stage1_fallback(
    user_idea: str,
    genre: str,
    total_eps: int,
    aspect_ratio: str = "9:16",
    target_engine: str = "wan3.0",
    target_dur: float = 120.0,
    visual_style: str = "真人电影/工业冷峻暗色调/超写实胶片质感",
) -> dict[str, Any]:
    """【规则编号: STAGE-1-COT-01 ~ STAGE-1-COT-03】大模型解析异常或离线时的动态保底工厂。"""
    logger.debug(f"[Stage 1 Fallback] Synthesizing dynamic fallback assets for idea: '{user_idea[:30]}'")
    clean_idea = (user_idea or "都市悬疑生死对决").strip()
    words = re.findall(r"[\u4e00-\u9fa5]{2,6}", clean_idea)
    key_subject = words[0] if words else "绝命对决"
    key_object = words[1] if len(words) > 1 else "神秘物证"

    base_title = f"{key_subject}之局" if len(key_subject) <= 4 else key_subject
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", clean_idea[:20]).lower().strip("_") or "drama_project"

    # 【规则编号: STAGE-1-COT-01】10 大老套因果与 3 大廉价爽点
    forbidden_cliches = [
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
    ]
    forbidden_cheap = [
        "1. 严禁一键打脸的无脑狂暴爽，必须经历严密的因果博弈与肉体/情感代价",
        "2. 严禁脸谱化小丑反派下跪求饶的低幼短视情绪垃圾",
        "3. 严禁脱离现实物理法则的凌空飞踢或超自然夸张动作",
    ]
    persona_redlines = [
        f"1. 严禁将主角塑造为全知全能的伟光正或无脑龙傲天，必须具备致命性格缺陷(Lie)与创伤幽灵(Ghost)",
        f"2. 严禁将核心反派塑造为无脑作恶的脸谱化工具人，反派必须具备逻辑自洽的利益防御体系",
        f"3. 严禁配角沦为推进剧情的降智传话筒，所有出场人物必须有独立欲望与代价计算",
    ]

    # 【规则编号: STAGE-1-COT-03】四大商业维度 6-8 个候选片名矩阵
    candidate_titles = {
        "identity_contrast": [f"{key_subject}：上位法则", f"逆流而上的{key_subject}"],
        "extreme_suspense": [f"第7封{key_object}", f"{key_subject}的生死48小时"],
        "prop_irony": [f"带血的{key_object}", f"破碎的{key_object}"],
        "dark_psychology": [f"第3个假面", f"{key_subject}的向死而生"],
    }

    # 【规则编号: STAGE-1-COT-02】工业 Logline（突发危机+致命缺陷+阻碍+倒计时+毁灭代价）、核心戏剧讽刺与终局核爆点
    logline = f"围绕{key_subject}与{key_object}展开的生死智斗，主角因盲目自负(Flaw)深陷死局，在72小时极限倒计时中跨越重重杀局，以惨烈代价撕破伪善假面。"
    dramatic_irony = f"观众预知{key_object}背后的致命暗线，反派在自鸣得意中一步步踏入早已布好的天罗地网。"
    grand_payoff = f"在全剧终局决战场景，主角当众引爆{key_object}的核心铁证，让背叛者付出不可承受的代价。"

    return {
        "slug": slug,
        "title": base_title,
        "selected_title": base_title,
        "candidate_titles": candidate_titles,
        "visual_style": visual_style,
        "aspect_ratio": aspect_ratio,
        "target_duration_sec": float(target_dur),
        "duration_sec_per_ep": int(target_dur),
        "total_episodes": total_eps or 12,
        "target_episodes": total_eps or 12,
        "target_video_engine": target_engine,
        "arc_type": "revenge",
        "mechanism": "identity_hidden",
        "logline": logline,
        "dramatic_irony": dramatic_irony,
        "core_irony": dramatic_irony,
        "grand_payoff": grand_payoff,
        "forbidden_cliches_10": forbidden_cliches,
        "forbidden_cheap_tropes_3": forbidden_cheap,
        "negative_rules": {
            "forbidden_cliches": forbidden_cliches,
            "forbidden_cheap_pleasures": forbidden_cheap,
            "persona_redlines": persona_redlines,
        },
    }


class CandidateTitlesDict(dict):
    """支持字典访问与属性访问的候选片名矩阵容器。"""
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'CandidateTitlesDict' object has no attribute '{name}'")


def stage1_ideation_node(state: GlobalDramaMasterState | IndustrialDramaState | Any) -> dict[str, Any]:
    """【规则编号: STAGE-1-COT-01 ~ STAGE-1-OUT-01】执行阶段 1：题材破壁与工业立项。"""
    user_idea = (
        _get_val(state, "user_idea")
        or _get_val(state, "user_prompt")
        or _get_val(state, "story_prompt")
        or _get_val(state, "prompt")
        or _get_val(state, "logline")
        or _get_val(state, "selected_title")
        or _get_val(state, "title")
        or "都市悬疑反转短剧"
    )
    total_eps = _get_val(state, "total_episodes") or _get_val(state, "target_episodes") or 12
    genre = _get_val(state, "genre", "悬疑/复仇")
    target_dur = float(_get_val(state, "target_duration_sec") or _get_val(state, "duration_sec_per_ep") or 120.0)
    aspect_ratio = _get_val(state, "aspect_ratio", "9:16")
    visual_style = _get_val(state, "visual_style", "真人电影/工业冷峻暗色调/超写实")
    target_engine = _get_val(state, "target_video_engine", "wan3.0")

    logger.debug(
        f"[Stage 1 Node] Executing ideation: idea='{user_idea[:30]}...', genre='{genre}', "
        f"aspect_ratio='{aspect_ratio}', total_episodes={total_eps}, duration={target_dur}s, engine='{target_engine}'"
    )

    user_prompt = STAGE1_USER_PROMPT_TEMPLATE.format(
        user_idea=user_idea,
        genre=genre,
        aspect_ratio=aspect_ratio,
        total_episodes=total_eps,
        target_duration_sec=target_dur,
        visual_style=visual_style,
        target_video_engine=target_engine,
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE1_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage1_fallback(
            user_idea=user_idea,
            genre=genre,
            total_eps=total_eps,
            aspect_ratio=aspect_ratio,
            target_engine=target_engine,
            target_dur=target_dur,
            visual_style=visual_style,
        ),
    )

    # 【规则编号: STAGE-1-COT-03】片名矩阵格式化
    candidate_matrix_data = result_json.get("candidate_titles") or {}
    candidate_titles = (
        CandidateTitleMatrix.model_validate(candidate_matrix_data)
        if candidate_matrix_data and not isinstance(candidate_matrix_data, CandidateTitleMatrix)
        else candidate_matrix_data
    )

    # 【规则编号: STAGE-1-COT-01】双轨禁令总母集推演
    neg_data = result_json.get("negative_rules") or {}
    negative_rules = (
        DoubleTrackProhibitions.model_validate(neg_data)
        if neg_data and not isinstance(neg_data, DoubleTrackProhibitions)
        else neg_data
    )

    cliches = neg_data.get("forbidden_cliches", [])
    cheap = neg_data.get("forbidden_cheap_pleasures", [])

    # 【规则编号: STAGE-1-COT-02】Logline 与终局核爆点对称
    selected_title = result_json.get("title") or result_json.get("selected_title") or _get_val(state, "title") or _get_val(state, "selected_title") or "绝密之局"
    slug = result_json.get("slug") or _get_val(state, "slug") or re.sub(r"[^a-zA-Z0-9_]+", "_", selected_title).lower().strip("_") or "drama_project"
    core_irony = result_json.get("core_irony") or result_json.get("dramatic_irony") or _get_val(state, "core_irony") or _get_val(state, "dramatic_irony") or "观众全知视角锁定暗线"
    grand_payoff = result_json.get("grand_payoff") or _get_val(state, "grand_payoff") or "终局引爆核心铁证逆风翻盘"
    logline = result_json.get("logline") or _get_val(state, "logline") or user_idea

    logger.debug(
        f"[Stage 1 Node] Ideation complete: slug='{slug}', selected_title='{selected_title}', "
        f"cliches_count={len(cliches or [])}, cheap_count={len(cheap or [])}"
    )

    titles_dict = (
        candidate_titles.model_dump()
        if hasattr(candidate_titles, "model_dump")
        else (candidate_titles if isinstance(candidate_titles, dict) else {})
    )
    titles_dict = CandidateTitlesDict(titles_dict)

    final_dur = float(result_json.get("duration_sec_per_ep") or result_json.get("target_duration_sec") or target_dur)
    final_eps = int(result_json.get("target_episodes") or result_json.get("total_episodes") or total_eps)

    # 计算蓝图
    arc_type_val = result_json.get("arc_type") or _get_val(state, "arc_type") or "revenge"
    mechanism_val = result_json.get("mechanism") or _get_val(state, "mechanism")
    bp = None
    bp_prompt = ""
    try:
        bp = build_blueprint(
            total_episodes=total_eps,
            arc_type=arc_type_val,
            mechanism=mechanism_val,
            duration_sec=final_dur,
            segment_strategy='balanced',
        )
        bp_prompt = to_prompt_block(bp=bp)
        logger.info(f"构建项目蓝图：{bp_prompt}")
    except Exception as e:
        logger.warning(f"构建项目蓝图跳过或降级 (total_episodes={total_eps}): {e}")

    # 【分层状态机契约】调用 WorkingMemoryCompiler 纯函数式提取阶段 1 工作便签
    ideation_wm = WorkingMemoryCompiler.compile_ideation_working_memory({
        "user_idea": user_idea,
        "selected_title": selected_title,
        "title": selected_title,
        "genre": genre,
        "total_episodes": total_eps,
        "target_dur": target_dur,
        "visual_style": visual_style,
        "logline": logline,
        "dramatic_irony": core_irony,
        "core_irony": core_irony,
        "grand_payoff": grand_payoff,
        "mechanism": result_json.get("mechanism"),
        "arc_type": result_json.get("arc_type"),
        "negative_rules": negative_rules,
    })

    # 【Redis 异步投影引擎】持久化语义化工作便签与读投影，触发事件广播
    drama_id = _get_val(state, "drama_id") or _get_val(state, "id")
    if drama_id:
        try:
            d_id = int(drama_id)
            set_journey1_working_memory(d_id, "stage1", ideation_wm)
            publish_drama_event(d_id, "stage1_completed", {
                "drama_id": d_id,
                "stage": "stage1",
                "title": selected_title,
                "slug": slug,
            })
            publish_drama_read_projection(d_id, {
                "id": d_id,
                "title": selected_title,
                "slug": slug,
                "genre": genre,
                "journey": "journey_1_literary",
                "total_episodes": final_eps,
                "user_idea": user_idea,
                "ideation_working_memory": ideation_wm,
                "visual_style": visual_style,
                "logline": logline,
                "core_irony": core_irony,
                "grand_payoff": grand_payoff,
                "current_stage": 1,
                "mechanism": result_json.get("mechanism"),
                "arc_type": result_json.get("arc_type"),
                "blueprint": bp,
            })
            logger.debug(f"[Stage 1 Node] Published stage1 working memory and read projection for drama_id={d_id}")
        except Exception as e:
            logger.warning(f"[Stage 1 Node] Failed to write working memory/read projection: {e}")

    return {
        "current_stage": 1,
        "journey": "journey_1_literary",
        "user_idea": user_idea,
        "slug": slug,
        "title": selected_title,
        "selected_title": selected_title,
        "candidate_titles": titles_dict,
        "visual_style": result_json.get("visual_style") or visual_style,
        "aspect_ratio": result_json.get("aspect_ratio") or aspect_ratio,
        "target_duration_sec": final_dur,
        "duration_sec_per_ep": int(final_dur),
        "total_episodes": final_eps,
        "target_episodes": final_eps,
        "target_video_engine": result_json.get("target_video_engine") or target_engine,
        "logline": logline,
        "core_irony": core_irony,
        "dramatic_irony": core_irony,
        "grand_payoff": grand_payoff,
        "mechanism": result_json.get("mechanism"),
        "arc_type": result_json.get("arc_type"),
        "derivation": result_json.get("derivation"),
        "blueprint": bp,
        "bp_prompt": bp_prompt,
        "forbidden_cliches_10": cliches or [],
        "forbidden_cheap_tropes_3": cheap or [],
        "negative_rules": negative_rules,
        "ideation_working_memory": ideation_wm,
    }
