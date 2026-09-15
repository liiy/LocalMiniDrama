"""阶段 5：全季文学剧本工笔生成与波次推进节点 (Stage 5 Screenplay Node)。"""
from __future__ import annotations

import json
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


def _stage5_fallback_episode(
    episode_num: int,
    outline: dict[str, Any],
    incoming_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    title = outline.get("title") or f"第{episode_num}集：破局前夜"
    hook = outline.get("hook_3s") or outline.get("three_second_hook") or "特写：雨夜中闪过一道惨白闪电，枪口顶在主角额头，冰冷水珠顺着金属滑落。"
    cliff = outline.get("killer_cliffhanger_115s") or outline.get("cliffhanger") or "定格：主角突然在后视镜里看到已故三年的导师正面无表情地注视着他。"

    body = f"""### 【场景】滨海旧码头7号废弃仓库 - 夜 - 暴雨

【动作】生锈的铁皮大门被狂风狠狠拍打，发出刺耳的金属摩擦声。
陆沉背靠立柱，左臂渗着血，右手紧扣着那枚带血的钛合金加密U盘。

**韩泰**（缓步从阴影中走出，金丝眼镜反射着惨白闪电）：
陆沉，三年了，你以为靠这枚小小的U盘就能推翻整个韩氏集团？

**陆沉**（嘴角勾起一抹讥诮的冷笑，拇指缓缓摩挲着怀表表面）：
韩董，你手上转着的沉香手串，第三颗珠子上的凹痕...当年杀我师父时，就是掐着它动的手吧？

**韩泰**（脸色骤变，拨动佛珠的手猛地一顿）：
你找死！

【动作】四名黑衣保镖瞬间拔枪，红外激光瞄准线瞬间锁死陆沉的胸口！
"""

    outgoing_snapshot = {
        "episode_index": episode_num,
        "location": "7号废弃仓库核心集装箱区",
        "character_states": {
            "陆沉": "左臂受伤，右手握紧加密U盘，眼神狠厉决绝",
            "韩泰": "佛珠停滞，眼神露出杀机",
        },
        "prop_possession": {
            "染血加密U盘钥匙扣": "陆沉右手紧握",
            "百年老山檀沉香手串": "韩泰左手捏紧",
        },
        "environmental_state": "闪电雷鸣，红外激光线交织密布",
        "freeze_frame_desc": cliff,
    }

    return {
        "episode_num": episode_num,
        "title": title,
        "commercial_tag": "paywall_climax" if episode_num in [3, 6, 9] else "regular",
        "scene_header": "夜 内 滨海旧码头7号废弃仓库",
        "characters_present": ["陆沉", "韩泰"],
        "core_props": ["染血的加密U盘钥匙扣", "百年老山檀沉香手串"],
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
    
    # 获取或初始化上一集 0 秒物理快照
    if episode_num == 1:
        chars_list = state.characters_engine.get("characters", [])
        envs_list = state.environments_and_props.get("environments", [])
        props_list = state.environments_and_props.get("props", [])
        incoming_snapshot = PhysicalContinuityEngine.extract_initial_snapshot(
            chars_list, envs_list, props_list
        )
    else:
        incoming_snapshot = state.inter_episode_physical_snapshot

    # 长期记忆检索注入 (从 memory_items 表检索前置角色小传、空间规则与核心道具)
    long_term_memories_str = "无特定长期记忆约束"
    if getattr(state, "drama_id", None):
        try:
            from app.db.session import get_db
            from app.context.memory_service import search_memory_items
            with get_db() as db:
                mem_items = search_memory_items(db, drama_id=state.drama_id, limit=10)
                if mem_items:
                    lines = [
                        f"- [{m.get('memory_type', 'note')}] {m.get('title', '')}: {m.get('content', '')}"
                        for m in mem_items
                    ]
                    long_term_memories_str = "\n".join(lines)
        except Exception:
            pass

    user_prompt = STAGE5_USER_PROMPT_TEMPLATE.format(
        episode_num=episode_num,
        total_episodes=state.total_episodes or 12,
        episode_outline=json.dumps(outline, ensure_ascii=False),
        incoming_physical_snapshot=json.dumps(incoming_snapshot or {}, ensure_ascii=False),
        long_term_memories=long_term_memories_str,
        characters_summary=json.dumps(state.characters_engine, ensure_ascii=False),
        environments_props_summary=json.dumps(state.environments_and_props, ensure_ascii=False),
        forbidden_rules=json.dumps(state.negative_rules.model_dump(), ensure_ascii=False) if hasattr(state, "negative_rules") else "严格遵守双轨禁令",
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE5_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage5_fallback_episode(episode_num, outline, incoming_snapshot),
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

    # 确定本批次需要生成的集数（例如支持增量或全量，默认依次推进尚未生成的集数）
    next_ep = len(completed) + 1
    batch_size = 3  # 每波次 3 集 Mini-Arc
    target_end = min(total, next_ep + batch_size - 1)

    for ep in range(next_ep, target_end + 1):
        res = generate_single_episode(state, ep)
        completed[ep] = res["script"]
        current_snapshot = res["outgoing_snapshot"]
        state.inter_episode_physical_snapshot = current_snapshot

    return {
        "current_stage": 5,
        "completed_screenplays": completed,
        "inter_episode_physical_snapshot": current_snapshot,
        "literary_journey_locked": len(completed) >= total,
    }
