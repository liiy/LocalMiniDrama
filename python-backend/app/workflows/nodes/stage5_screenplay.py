"""【规则编号: RULE-VI-05】阶段 5：全季文学剧本工笔生成与波次推进节点 (Stage 5 Screenplay Node)。

严格遵循 SKILL.md v10.0.0 工业标准：
1. 【规则编号: STAGE-5-COT-01】事前三道安全护栏锁 (潜台词交锋错位、全场禁词与现实代价毛刺)；
2. 【规则编号: STAGE-5-COT-02】单集必须规划 2 ~ 4 个标准时空场景标头 (【场景 01】...)；
3. 【规则编号: STAGE-5-COT-03】0 秒动作接力 (第 2 集及之后开篇承接 previous_episode_0s_pickup)；
4. 【规则编号: STAGE-5-COT-04】正文末尾强制以三位一体黄金悬念钩子 (golden_cliffhanger_hook) 收尾；
5. 【规则编号: STAGE-5-COT-05】结尾强制生成集尾物理快照 (episode_end_physical_delta) 自动接力下一集；
6. 【公共硬性约束 1 & 4】大模型严禁参与业务分支判断，节点内不包含状态机流转 if/elif，业务分支全抽离至 independent routers。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.script_ast_parser import ScriptASTParser
from app.schemas.script_graph_state import (
    EpisodeScriptV2,
    IndustrialDramaMasterState,
    IndustrialDramaState,
    LiteraryScreenplayEpisode,
    PreviousEpisodePickup,
    GoldenCliffhangerHook,
    EpisodeEndPhysicalDelta,
)
from app.workflows.nodes.physical_continuity import PhysicalContinuityEngine
from app.workflows.prompts.master_sop_prompts import (
    STAGE5_SYSTEM_PROMPT,
    STAGE5_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage5_screenplay")


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """安全读取字典或 Pydantic/TypedDict 对象字段值。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stage5_fallback_episode(
    episode_num: int,
    outline: dict[str, Any],
    incoming_snapshot: dict[str, Any] | None,
    characters: list[dict[str, Any]],
    environments: list[dict[str, Any]],
    props: list[dict[str, Any]],
) -> dict[str, Any]:
    """【规则编号: STAGE-5-COT-01 ~ 05】大模型离线或解析异常时的保底单集文学剧本工笔生成工厂。"""
    logger.warning(f"[Stage 5 Fallback] Generating deterministic LiteraryScreenplayEpisode for Episode {episode_num}.")

    p_char = characters[0] if characters else {"name": "林晚"}
    a_char = characters[1] if len(characters) > 1 else {"name": "周衍"}
    p_name = p_char.get("name", "林晚")
    a_name = a_char.get("name", "周衍")

    p_stress = p_char.get("voice_fingerprint", {}).get("stress_action", "下颌骨死死咬紧，右手大拇指反复掐入食指指甲缝")
    a_stress = a_char.get("voice_fingerprint", {}).get("stress_action", "手指急促转动磨砂打火机，喉结剧烈滚动")

    env_name = environments[0].get("location_name", "老火车站废弃站台") if environments else "老火车站废弃站台"
    hero_prop = props[0].get("name", "生锈手术刀与带血日记") if props else "带血日记"
    anchor_prop = p_char.get("carried_anchor_item", {}).get("item_name", "黑色大衣内袋钥匙")

    title = outline.get("title") or outline.get("episode_title") or f"第{episode_num:02d}集：破局交锋"
    hook = (
        outline.get("hook_3s")
        or outline.get("three_second_hook")
        or f"雨夜特写：冰冷泥水顺着黑风衣下摆滴落，{p_name}右手死死攥住{hero_prop}，闪电撕裂夜空。"
    )
    cliff = (
        outline.get("killer_cliffhanger_115s")
        or outline.get("cliffhanger")
        or f"定格：{p_name}反手将{hero_prop}抵在{a_name}咽喉，{a_name}金丝眼镜滑落，眼底杀机彻底撕破伪装！"
    )

    # 构造接力上一集的 0 秒物理快照描述
    if episode_num >= 2:
        pickup_desc = (
            incoming_snapshot.get("freeze_frame_desc")
            if isinstance(incoming_snapshot, dict) and incoming_snapshot.get("freeze_frame_desc")
            else f"{p_name}半跪在{env_name}泥水里，右手握紧{hero_prop}，黑色大衣下摆干结盐水泥斑。"
        )
        pickup_data = {
            "inherited_from_episode": episode_num - 1,
            "pickup_state_description": pickup_desc,
        }
        pickup_opening_action = f"承接第 {episode_num - 1} 集终态，{p_name}在泥水中缓缓撑起身躯，风衣下摆干结的盐水与泥斑混在一起。左手紧紧扣在胸口内袋。"
    else:
        pickup_data = None
        pickup_opening_action = f"{p_name}独自站在阴暗的站台角落，黑色大衣领口高高竖起，冷雨不断从帽檐滑落。"

    # 【规则编号: STAGE-5-COT-02】规范 2 ~ 4 个标准时空场景标头与声学行为
    screenplay_text = f"""【场景 01】外景. {env_name}外围货运铁轨 - 晨 - 暴雨
灰蒙蒙的雾气裹着刺鼻的煤焦油与柴油味。寒风在废弃工字钢立柱间呼啸穿梭。
[声学行为: 开场突发重击 Braam Hit]
{pickup_opening_action}
远处蒸汽机车发出一声沉闷刺耳的汽笛长鸣，伴随金属轮对尖锐的摩擦制动声。
{p_name}抬手抹了一把脸上的冰雨，指尖碰触到额头渗血的旧伤口，疼得倒吸一口冷气。

{a_name}
（缓步从阴影中踱出，黑色长柄伞面雨珠飞溅，声音在风雨中显得极平极冷）
东西交出来。这不是你能碰的局。

{p_name}
（{p_stress}，冷笑一声将手伸入风衣内袋，声音压低至沙哑声带摩擦）
当年你带走遗物的时候，是不是也撑着这把黑伞？

【场景 02】内景. {env_name}尽头扳道工值班室 - 晨 - 昏暗
破损的木门被狂风狠狠拍打，发出“哐当、哐当”的疲倦回响。
[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]
地面积水倒映着窗外惨白的闪电。两名黑衣保镖瞬间从门后包抄，黑洞洞的枪口抬起。
{a_name}停住脚步，{a_stress}，伞尖在水泥地面划出刺耳的尖音。

{a_name}
（语气陡然阴沉，金丝眼镜后闪过致命戾气）
你真的以为...你今天能活着走出这条货运线？

【动作】{p_name}猛地后撤半步，左肩借力狠撞向生锈铁架，铁架上的工具箱轰然砸落！
{p_name}右手在半空中反切，一道寒光撕裂昏暗空气，生锈手术刀锋死死架在{a_name}颈侧动脉！
四柄枪口瞬间红外激光交错锁死{p_name}胸膛！"""

    # 【规则编号: STAGE-5-COT-04】三位一体黄金悬念绝杀钩子
    golden_cliff = {
        "hook_action": f"{p_name}右手反手将{hero_prop}死死抵住{a_name}颈动脉，右手指缝渗出血珠，四道红外激光穿透昏暗雨丝交叉锁定心口",
        "hook_dialogue": f"{p_name}（声音冷得发颤）：开枪啊！看是你的子弹快，还是我的刀先割断你的大动脉！",
        "hook_audio_braam": "主观声学重击，警笛与雷鸣混合下潜，定格于心跳监护仪刺耳长鸣与重金属低音下潜。",
    }

    # 【规则编号: STAGE-5-COT-05】集尾物理快照
    delta = {
        "episode_index": episode_num,
        "location": f"{env_name}扳道室",
        "last_scene": f"{env_name}扳道室",
        "timeline_progress_sec": 120.0,
        "posture_and_injuries": f"{p_name}右手持刀抵紧{a_name}咽喉，左肩挫伤渗血；{a_name}背贴冰冷墙面僵硬不敢动弹",
        "carried_props_status": f"{hero_prop}处于刺入预备态，{anchor_prop}安全藏于大衣内袋",
        "weather_and_light": "暴雨雷阵雨，扳道室窗玻璃碎裂漏风，惨白闪电间歇投射硬阴影",
        "freeze_frame_desc": cliff,
    }

    # 兼容 legacy 字段与新工业 TypedDict
    return {
        "episode_id": episode_num,
        "episode_num": episode_num,
        "episode_title": title,
        "title": title,
        "planned_duration_sec": 120.0,
        "dramatic_arc_unit": f"单元 {(episode_num - 1) // 3 + 1} (第 {((episode_num - 1) // 3) * 3 + 1:02d} - {((episode_num - 1) // 3 + 1) * 3:02d} 集)",
        "core_dramatic_task": outline.get("core_dramatic_task") or outline.get("core_conflict_task") or f"第{episode_num}集核心交锋突围",
        "previous_episode_0s_pickup": pickup_data,
        "screenplay_text": screenplay_text,
        "body_markdown": screenplay_text,
        "hook_3s": hook,
        "ending_cliffhanger": cliff,
        "golden_cliffhanger_hook": golden_cliff,
        "episode_end_physical_delta": delta,
        "outgoing_physical_snapshot": delta,
        "scene_header": f"内景. {env_name}扳道室 - 晨",
        "characters_present": [p_name, a_name],
        "core_props": [hero_prop, anchor_prop],
    }


def generate_single_episode(
    state: IndustrialDramaState | IndustrialDramaMasterState | Any,
    episode_num: int,
    incoming_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """【规则编号: RULE-VI-05 & STAGE-5-COT-01 ~ 05】工笔生成指定单集文学剧本并执行 AST 分块与物理咬合。"""
    logger.debug(f"[generate_single_episode] Processing Episode {episode_num}.")
    outlines = _get_val(state, "season_outlines", {}) or {}
    outline = outlines.get(episode_num) or outlines.get(str(episode_num)) or {}
    chars_engine = _get_val(state, "characters_engine", {}) or {}
    chars_list = chars_engine.get("characters", []) if isinstance(chars_engine, dict) else []
    envs_props = _get_val(state, "environments_and_props", {}) or {}
    envs_list = envs_props.get("environments", []) if isinstance(envs_props, dict) else []
    props_list = envs_props.get("props", []) if isinstance(envs_props, dict) else []

    # 获取或初始化上一集 0 秒物理快照
    if incoming_snapshot is None:
        if episode_num == 1:
            incoming_snapshot = PhysicalContinuityEngine.extract_initial_snapshot(
                chars_list, envs_list, props_list
            )
        else:
            incoming_snapshot = _get_val(state, "inter_episode_physical_snapshot", None)

    # 长期记忆 RAG 动态召回：基于本集大纲标题、悬念钩子、关键物证与角色名称进行检索
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
    logger.debug(f"[Stage 5 RAG] Building RAG Query for Ep {episode_num}: {rag_query}")

    long_term_memories_str = "无特定长期记忆约束"
    drama_id = _get_val(state, "drama_id", None)
    if drama_id:
        try:
            from app.db.session import session_scope
            from app.context.memory_service import search_memory_items
            with session_scope() as db:
                mem_items = search_memory_items(db, drama_id=drama_id, query=rag_query, limit=10)
                if mem_items:
                    lines = []
                    for m in mem_items:
                        m_type = m.get("memory_type", "note")
                        m_title = m.get("title", "未命名记忆")
                        m_content = m.get("content") or m.get("summary") or ""
                        if len(m_content) > 300:
                            m_content = m_content[:300] + "...(省略)"
                        lines.append(f"- [{m_type}] {m_title}: {m_content}")
                    long_term_memories_str = "\n".join(lines)
                    logger.debug(f"[Stage 5 RAG] Retrieved {len(mem_items)} long-term memory items for Ep {episode_num}")
        except Exception as e:
            logger.warning(f"[Stage 5 RAG] Memory retrieval error for Ep {episode_num}: {e}")

    total_episodes = _get_val(state, "total_episodes", None) or _get_val(state, "target_episodes", 12)
    neg_rules = _get_val(state, "negative_rules", None)
    if hasattr(neg_rules, "model_dump"):
        forbidden_rules_str = json.dumps(neg_rules.model_dump(), ensure_ascii=False)
    elif isinstance(neg_rules, dict):
        forbidden_rules_str = json.dumps(neg_rules, ensure_ascii=False)
    else:
        forbidden_rules_str = "严格遵守双轨禁令"

    user_prompt = STAGE5_USER_PROMPT_TEMPLATE.format(
        episode_num=episode_num,
        total_episodes=total_episodes,
        episode_outline=json.dumps(outline, ensure_ascii=False),
        incoming_physical_snapshot=json.dumps(incoming_snapshot or {}, ensure_ascii=False),
        long_term_memories=long_term_memories_str,
        characters_summary=json.dumps(chars_engine, ensure_ascii=False),
        environments_props_summary=json.dumps(envs_props, ensure_ascii=False),
        forbidden_rules=forbidden_rules_str,
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
    body = result_json.get("screenplay_text") or result_json.get("body_markdown") or ""

    full_markdown = f"### 开场特写（前3秒）\n{hook}\n\n### 视听正文\n{body}\n\n### 片尾定格与悬念钩子\n{cliff}"
    
    # 调用系统既有的 ScriptASTParser 构建 4 个 AST 标准分块
    ast_tree = ScriptASTParser.parse(episode_num=episode_num, markdown_text=full_markdown)

    # 封装三位一体黄金悬念钩子
    golden_hook = result_json.get("golden_cliffhanger_hook") or {
        "hook_action": cliff,
        "hook_dialogue": "绝杀对白",
        "hook_audio_braam": "主观声学重击下潜",
    }

    # 封装集尾物理快照
    outgoing_snapshot = result_json.get("episode_end_physical_delta") or result_json.get("outgoing_physical_snapshot") or {}
    if not isinstance(outgoing_snapshot, dict):
        outgoing_snapshot = {}
    outgoing_snapshot.setdefault("episode_index", episode_num)
    outgoing_snapshot.setdefault("location", result_json.get("scene_header") or "核心场景")
    outgoing_snapshot.setdefault("last_scene", outgoing_snapshot.get("location") or "核心场景")
    outgoing_snapshot.setdefault("freeze_frame_desc", cliff)
    outgoing_snapshot.setdefault("timeline_progress_sec", 120.0)

    title_val = result_json.get("title") or result_json.get("episode_title") or f"第{episode_num:02d}集"

    script_record: dict[str, Any] = {
        "episode_id": episode_num,
        "episode_num": episode_num,
        "episode_title": title_val,
        "title": title_val,
        "planned_duration_sec": float(result_json.get("planned_duration_sec") or 120.0),
        "dramatic_arc_unit": result_json.get("dramatic_arc_unit") or f"单元 {(episode_num - 1) // 3 + 1}",
        "core_dramatic_task": result_json.get("core_dramatic_task") or outline.get("core_conflict_task") or f"第{episode_num}集核心交锋",
        "previous_episode_0s_pickup": result_json.get("previous_episode_0s_pickup") or (
            {"inherited_from_episode": episode_num - 1, "pickup_state_description": incoming_snapshot.get("freeze_frame_desc", "")}
            if episode_num >= 2 and isinstance(incoming_snapshot, dict) else None
        ),
        "screenplay_text": body,
        "body_markdown": body,
        "hook_3s": hook,
        "ending_cliffhanger": cliff,
        "golden_cliffhanger_hook": golden_hook,
        "episode_end_physical_delta": outgoing_snapshot,
        "outgoing_physical_snapshot": outgoing_snapshot,
        "commercial_tag": result_json.get("commercial_tag") or ("paywall_climax" if episode_num in [3, 6, 9] else "regular"),
        "scene_header": result_json.get("scene_header") or "日 内 核心场景",
        "characters_present": result_json.get("characters_present") or [c.get("name") for c in chars_list[:2]],
        "core_props": result_json.get("core_props") or [p.get("name") for p in props_list[:2]],
        "ast_data": ast_tree.model_dump() if ast_tree else None,
    }

    return {
        "script": script_record,
        "outgoing_snapshot": outgoing_snapshot,
    }


def stage5_screenplay_node(state: Any) -> dict[str, Any]:
    """【规则编号: RULE-VI-05】执行阶段 5：生成全季剧本或推进当前 Mini-Arc 批次。
    
    遵循公共硬性约束：
    - 入参为标准 state（支持 IndustrialDramaState 契约），返回增量字典；
    - 纯业务节点，不含流转 if/elif 分支逻辑（分支全部由 router 判定）。
    """
    total = _get_val(state, "total_episodes", None) or _get_val(state, "target_episodes", 5)
    completed = dict(_get_val(state, "completed_screenplays", {}) or {})
    current_snapshot = _get_val(state, "inter_episode_physical_snapshot", None)

    next_ep = len(completed) + 1
    batch_size = 3  # 每波次 3 集 Mini-Arc
    target_end = min(total, next_ep + batch_size - 1)

    logger.info(f"[Stage 5 Node] Generating screenplays from Ep {next_ep} to Ep {target_end} (Total: {total})")

    for ep in range(next_ep, target_end + 1):
        res = generate_single_episode(state, ep, incoming_snapshot=current_snapshot)
        completed[ep] = res["script"]
        current_snapshot = res["outgoing_snapshot"]

    logger.info(f"[Stage 5 Node] Screenplays progress: {len(completed)}/{total} episodes completed.")

    return {
        "current_stage": 5,
        "completed_screenplays": completed,
        "inter_episode_physical_snapshot": current_snapshot,
        "current_mini_arc_index": (len(completed) - 1) // 3 + 1,
        "literary_journey_locked": len(completed) >= total,
    }
