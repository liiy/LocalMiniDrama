"""阶段 5：全季文学剧本工笔生成与波次推进节点 (Stage 5 Screenplay Node)。

严格遵循 SKILL.md：
1. 事前三道安全锁 (Poka-Yoke Rules)：
   - 锁一：场面潜台词错位矩阵 (subtext_matrix) —— 表面掩饰行动 vs 真实企图，切除嘴替说白；
   - 锁二：代价与现实毛刺前置锁 (friction_and_cost_preset) —— 肉体/利益代价与偶发物理阻力；
   - 锁三：工笔级任务卡承接 (detailed_causal_task) —— 承接阶段 4 分集大纲；
2. 0 秒物理快照咬合 (Inter-Episode Physical Continuity)：上一集结尾状态与本集开头严格咬合；
3. 生物骨相、生活质感服化道与语言指纹深度融入正文；
4. 4 分块 AST 解析验证 (ScriptASTParser)。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.script_ast_parser import ScriptASTParser
from app.schemas.script_graph_state import (
    EpisodeScriptV2,
    IndustrialDramaMasterState,
)
from app.workflows.nodes.physical_continuity import PhysicalContinuityEngine
from app.workflows.prompts.master_sop_prompts import (
    STAGE5_SYSTEM_PROMPT,
    STAGE5_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage5_screenplay")


def _stage5_fallback_episode(
    episode_num: int,
    outline: dict[str, Any],
    incoming_snapshot: dict[str, Any] | None,
    characters: list[dict[str, Any]],
    environments: list[dict[str, Any]],
    props: list[dict[str, Any]],
) -> dict[str, Any]:
    """当大模型离线或解析异常时的保底单集剧本工笔生成工厂。"""
    logger.warning(f"Triggering Stage 5 dynamic fallback screenplay for Episode {episode_num}.")

    p_char = characters[0] if characters else {"name": "主角"}
    a_char = characters[1] if len(characters) > 1 else {"name": "反派"}
    p_name = p_char.get("name", "主角")
    a_name = a_char.get("name", "反派")

    p_stress = p_char.get("voice_fingerprint", {}).get("stress_action", "下颌紧绷，食指关节轻叩掌心")
    a_stress = a_char.get("voice_fingerprint", {}).get("stress_action", "手指疯狂抠掐手串深痕")

    env_name = environments[0].get("location_name", "核心隐秘决战场景") if environments else "核心隐秘场景"
    hero_prop = props[0].get("name", "关键反转物证") if props else "关键物证"
    anchor_prop = p_char.get("carried_anchor_item", {}).get("item_name", "随身旧物信物")

    title = outline.get("title") or f"第{episode_num}集：破局交锋"
    hook = (
        outline.get("hook_3s")
        or outline.get("three_second_hook")
        or f"特写：雨夜中惨白闪电划破黑暗，冰冷枪口死死顶在{p_name}额头，水珠顺着金属枪管滴落。"
    )
    cliff = (
        outline.get("killer_cliffhanger_115s")
        or outline.get("cliffhanger")
        or f"定格：{a_name}的笑意瞬间凝固在嘴角，{p_name}当众撕开暗袋，亮出最后一封绝密铁证！"
    )

    body = f"""### 【场景】{env_name} - 夜 - 暴雨

【动作】生锈的铁皮大门被狂风狠狠拍打，发出刺耳的金属摩擦声。
{p_name}背靠斑驳工字钢立柱，粗花呢大衣下摆沾满暗黄泥斑，右手死死扣紧{hero_prop}。

**{a_name}**（缓步从阴影中走出，金丝眼镜折射着惨白闪电，嘴角挂着居高临下的假笑）：
{p_name}，这么多年了，你以为靠这件所谓的铁证，就能推翻整个棋局？

**{p_name}**（{p_stress}，眼神如鹰隼般死死锁死对方）：
你手上转着的手串第三颗珠子...当年害死至亲时，你就是这么掐着它动的手吧？

**{a_name}**（脸色骤变，{a_stress}，假笑彻底僵死）：
你找死！

【动作】四名保镖瞬间拔枪，红外激光瞄准线瞬间交叉锁死{p_name}的胸口！
"""

    outgoing_snapshot = {
        "episode_index": episode_num,
        "location": env_name,
        "character_states": {
            p_name: f"背靠立柱，粗花呢大衣沾染泥斑，右手握紧{hero_prop}，眼神狠厉决绝",
            a_name: "手串停滞，脸色铁青，眼底杀机毕露",
        },
        "prop_possession": {
            hero_prop: f"{p_name}右手紧握",
            anchor_prop: f"{p_name}大衣内袋",
        },
        "environmental_state": "暴雨雷鸣，红外激光线交织密布，地面积水倒映冷光",
        "freeze_frame_desc": cliff,
        "last_scene": f"夜 内 {env_name}",
    }

    return {
        "episode_num": episode_num,
        "title": title,
        "commercial_tag": "paywall_climax" if episode_num in [3, 6, 9] else "regular",
        "scene_header": f"夜 内 {env_name}",
        "characters_present": [p_name, a_name],
        "core_props": [hero_prop, anchor_prop],
        "hook_3s": hook,
        "body_markdown": body,
        "ending_cliffhanger": cliff,
        "outgoing_physical_snapshot": outgoing_snapshot,
    }


def generate_single_episode(
    state: IndustrialDramaMasterState,
    episode_num: int,
) -> dict[str, Any]:
    """工笔生成指定单集文学剧本并执行 AST 分块与物理咬合。"""
    outline = state.season_outlines.get(episode_num) or {}
    chars_list = state.characters_engine.get("characters", [])
    envs_list = state.environments_and_props.get("environments", [])
    props_list = state.environments_and_props.get("props", [])
    
    # 获取或初始化上一集 0 秒物理快照
    if episode_num == 1:
        incoming_snapshot = PhysicalContinuityEngine.extract_initial_snapshot(
            chars_list, envs_list, props_list
        )
    else:
        incoming_snapshot = state.inter_episode_physical_snapshot

    # 长期记忆 RAG 动态召回：基于本集大纲标题、悬念钩子、关键物证与角色名称进行语义向量 + 关系数据库混合检索
    rag_query_parts = []
    if outline.get("title"):
        rag_query_parts.append(str(outline.get("title")))
    if outline.get("hook_3s"):
        rag_query_parts.append(str(outline.get("hook_3s")))
    if outline.get("killer_cliffhanger_115s"):
        rag_query_parts.append(str(outline.get("killer_cliffhanger_115s")))
    for c in chars_list:
        if isinstance(c, dict) and c.get("name"):
            rag_query_parts.append(c["name"])
    for p in props_list:
        if isinstance(p, dict) and p.get("name"):
            rag_query_parts.append(p["name"])

    rag_query = " ".join(rag_query_parts).strip() or f"第{episode_num}集 剧本大纲与核心冲突"
    logger.debug(f"【阶段 5 剧本 RAG】为第 {episode_num} 集构建混合检索 Query: {rag_query}")

    long_term_memories_str = "无特定长期记忆约束"
    if getattr(state, "drama_id", None):
        try:
            from app.db.session import session_scope
            from app.context.memory_service import search_memory_items
            with session_scope() as db:
                mem_items = search_memory_items(db, drama_id=state.drama_id, query=rag_query, limit=10)
                if mem_items:
                    lines = []
                    for m in mem_items:
                        m_type = m.get("memory_type", "note")
                        m_title = m.get("title", "未命名记忆")
                        m_content = m.get("content") or m.get("summary") or ""
                        # 压缩过长的 json 字符串为紧凑展示
                        if len(m_content) > 300:
                            m_content = m_content[:300] + "...(省略)"
                        lines.append(f"- [{m_type}] {m_title}: {m_content}")
                    long_term_memories_str = "\n".join(lines)
                    logger.info(f"【阶段 5 剧本 RAG】第 {episode_num} 集成功召回 {len(mem_items)} 条高相关长期记忆条目")
                else:
                    logger.debug(f"【阶段 5 剧本 RAG】第 {episode_num} 集未检索到匹配的长期记忆条目，使用基线设定")
        except Exception as e:
            logger.warning(f"【阶段 5 剧本 RAG】第 {episode_num} 集长期记忆检索异常，降级处理: {e}")

    user_prompt = STAGE5_USER_PROMPT_TEMPLATE.format(
        episode_num=episode_num,
        total_episodes=state.total_episodes or 12,
        episode_outline=json.dumps(outline, ensure_ascii=False),
        incoming_physical_snapshot=json.dumps(incoming_snapshot or {}, ensure_ascii=False),
        long_term_memories=long_term_memories_str,
        characters_summary=json.dumps(state.characters_engine, ensure_ascii=False),
        environments_props_summary=json.dumps(state.environments_and_props, ensure_ascii=False),
        forbidden_rules=(
            json.dumps(state.negative_rules.model_dump(), ensure_ascii=False)
            if hasattr(state, "negative_rules") and hasattr(state.negative_rules, "model_dump")
            else "严格遵守双轨禁令"
        ),
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE5_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage5_fallback_episode(
            episode_num, outline, incoming_snapshot, chars_list, envs_list, props_list
        ),
    )

    # 结构化校验与 AST 分块解析
    hook = result_json.get("hook_3s") or outline.get("hook_3s") or "特写前3秒爆点动作"
    cliff = result_json.get("ending_cliffhanger") or outline.get("killer_cliffhanger_115s") or "片尾生死绝杀断点"
    body = result_json.get("body_markdown") or ""

    full_markdown = f"### 开场特写（前3秒）\n{hook}\n\n### 视听正文\n{body}\n\n### 片尾定格与悬念钩子\n{cliff}"
    
    # 调用系统既有的 ScriptASTParser 构建 4 个 AST 标准分块
    ast_tree = ScriptASTParser.parse(episode_num=episode_num, markdown_text=full_markdown)

    script_record = {
        "episode_num": episode_num,
        "title": result_json.get("title") or f"第{episode_num}集",
        "commercial_tag": result_json.get("commercial_tag") or "regular",
        "scene_header": result_json.get("scene_header") or "日 内 核心场景",
        "characters_present": result_json.get("characters_present") or [],
        "core_props": result_json.get("core_props") or [],
        "hook_3s": hook,
        "body_markdown": body,
        "ending_cliffhanger": cliff,
        "ast_data": ast_tree.model_dump() if ast_tree else None,
    }

    outgoing_snapshot = result_json.get("outgoing_physical_snapshot") or {
        "episode_index": episode_num,
        "location": script_record["scene_header"],
        "freeze_frame_desc": cliff,
    }
    if "last_scene" not in outgoing_snapshot:
        outgoing_snapshot["last_scene"] = outgoing_snapshot.get("location") or script_record["scene_header"]

    return {
        "script": script_record,
        "outgoing_snapshot": outgoing_snapshot,
    }


def stage5_screenplay_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 5：生成全季剧本或推进当前 Mini-Arc 批次。"""
    total = state.total_episodes or 5
    completed = dict(state.completed_screenplays or {})
    current_snapshot = state.inter_episode_physical_snapshot

    next_ep = len(completed) + 1
    batch_size = 3  # 每波次 3 集 Mini-Arc
    target_end = min(total, next_ep + batch_size - 1)

    logger.info(f"[Stage 5 Node] Generating screenplays from Ep {next_ep} to Ep {target_end} (Total: {total})")

    for ep in range(next_ep, target_end + 1):
        res = generate_single_episode(state, ep)
        completed[ep] = res["script"]
        current_snapshot = res["outgoing_snapshot"]
        state.inter_episode_physical_snapshot = current_snapshot

    logger.info(f"[Stage 5 Node] Screenplays progress: {len(completed)}/{total} episodes completed.")

    return {
        "current_stage": 5,
        "completed_screenplays": completed,
        "inter_episode_physical_snapshot": current_snapshot,
        "literary_journey_locked": len(completed) >= total,
    }
