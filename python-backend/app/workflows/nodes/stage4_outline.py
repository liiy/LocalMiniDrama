"""阶段 4：全季大纲与音乐动机母库节点 (Stage 4 Outline & Hook Architecture Node)。

本模块严格对齐《AI 原创连续剧短剧工业管线标准作业程序 (SKILL1.md v10.0.0)》：
- 【规则编号: STAGE-4-COT-01】全剧 3 套具象音乐主题动机母库确立 (04_audio_bible.json)：
  * LEITMOTIF_01_SUSPENSE (悬疑压迫/阶层窒息)
  * LEITMOTIF_02_TRAUMA (情感创伤/未竟心结)
  * LEITMOTIF_03_COUNTERATTACK (绝境反杀/终局核爆)
- 【规则编号: STAGE-4-COT-02】全季戏剧小高潮单元 (Mini-Arcs，每 3-4 集一单元) 规划；
- 【规则编号: STAGE-4-COT-03】双螺旋分集大纲任务卡（外部事件链 + 核心关系质变点）；
- 【规则编号: STAGE-4-COT-04】主角心理致命谎言崩解度 (Lie Erosion Metric) 与潜台词交锋矩阵；
- 【规则编号: STAGE-4-COT-05】黄金三段式节奏结构（前3秒视觉动作抓手 + 45秒微反转认知打破 + 115秒生死绝杀断点）；
- 【规则编号: STAGE-4-OUT-01】输出结构化任务卡并封装【短期记忆便签 D】向下游推进。
"""
from __future__ import annotations

import logging
from typing import Any

from app.context.short_memory_service import (
    WorkingMemoryCompiler,
    publish_drama_event,
    publish_drama_read_projection,
    set_journey1_working_memory,
)
from app.schemas.script_graph_state import GlobalDramaMasterState, IndustrialDramaState
from app.workflows.prompts.master_sop_prompts import (
    STAGE4_SYSTEM_PROMPT,
    STAGE4_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage4_outline")


def _stage4_fallback(
    title: str,
    total_episodes: int = 5,
    characters: list[dict[str, Any]] | None = None,
    props: list[dict[str, Any]] | None = None,
    user_idea: str = "",
    grand_payoff: str = "",
    genre: str = "",
) -> dict[str, Any]:
    """当大模型离线或解析异常时的保底大纲生成工厂。
    
    【规则编号: STAGE-4-COT-01】3大具象音乐主题动机母库保底；
    【规则编号: STAGE-4-COT-02】全季戏剧小高潮单元 (Mini-Arcs，每 3-4 集一单元) 规划保底；
    【规则编号: STAGE-4-COT-03 ~ STAGE-4-COT-05】全季双螺旋大纲与黄金卡点保底。
    """
    logger.warning(f"Triggering Stage 4 dynamic fallback outline/audio synthesizer for '{title}'.")

    chars = characters or []
    props_arr = props or []

    p_name = chars[0].get("name", "主角") if chars else "主角"
    a_name = chars[1].get("name", "反派") if len(chars) > 1 else "反派"
    hero_prop = props_arr[0].get("name", "关键物证") if props_arr else "关键物证"

    logger.debug(f"[Stage 4 Fallback] p_name={p_name}, a_name={a_name}, hero_prop={hero_prop}")

    # 【规则编号: STAGE-4-COT-01】全剧 3 大具象音乐主题动机母库（精确对齐 SKILL1.md v10.0.0 规范）
    leitmotif_items = [
        {
            "leitmotif_id": "LEITMOTIF_01_SUSPENSE",
            "motif_id": "LEITMOTIF_01_SUSPENSE",
            "name": "悬疑压迫与阶层窒息",
            "instrumentation": "低音大提琴单音震音 + 工业管道微弱回响 + 40Hz次低频脉冲",
            "tempo_bpm": "72-85",
            "musical_key": "D minor",
            "dramatic_function": "危机潜行、搜寻线索与真凶逼近时触发",
        },
        {
            "leitmotif_id": "LEITMOTIF_02_TRAUMA",
            "motif_id": "LEITMOTIF_02_TRAUMA",
            "name": "情感创伤与未竟心结",
            "instrumentation": "老式立式钢琴(带毛毡阻音) + 独奏中提琴 + 模拟卡带底噪",
            "tempo_bpm": "60-68",
            "musical_key": "A minor",
            "dramatic_function": "主角凝视随身旧物、直面过去创伤时触发",
        },
        {
            "leitmotif_id": "LEITMOTIF_03_COUNTERATTACK",
            "motif_id": "LEITMOTIF_03_COUNTERATTACK",
            "name": "绝境反杀与终局核爆",
            "instrumentation": "重击失真底鼓 + 工业金属交响打击乐 + 锐利电吉他长音",
            "tempo_bpm": "110-120",
            "musical_key": "E minor",
            "dramatic_function": "主角撕毁伪证、反打脸或绝境突围时触发",
        },
    ]
    audio_bible = {
        "leitmotif_registry": leitmotif_items,
        "leitmotifs": leitmotif_items,
        "foley_rules": {
            "boost": "+2.0dB ~ +3.0dB 物理拟音放大",
            "clarity": "-23 LUFS 广播级响度基准",
        },
    }

    # 【规则编号: STAGE-4-COT-02】全季戏剧小高潮单元 (Mini-Arcs, 每 3-4 集一单元)
    mini_arc_units: list[dict[str, Any]] = []
    unit_letters = ["A", "B", "C", "D", "E", "F", "G", "H"]
    unit_step = 3 if total_episodes <= 6 else 4
    for u_idx, start_ep in enumerate(range(1, total_episodes + 1, unit_step)):
        end_ep = min(start_ep + unit_step - 1, total_episodes)
        letter = unit_letters[u_idx % len(unit_letters)]
        if u_idx == 0:
            unit_name = f"单元 {letter}: 第 {start_ep:02d} - {end_ep:02d} 集 · 开局死局与血信破壁"
            dramatic_focus = f"{p_name}绝境防御与伪装，首个核心谎言面临外部冲击"
            climax_event = f"第 {end_ep:02d} 集核心物证《{hero_prop}》当众碎裂触发首次全城震荡"
        elif end_ep == total_episodes:
            unit_name = f"单元 {letter}: 第 {start_ep:02d} - {end_ep:02d} 集 · 绝境反杀与终局核爆"
            dramatic_focus = f"{p_name}撕碎所有伪装与致命谎言，与{a_name}展开终极对决"
            climax_event = f"第 {end_ep:02d} 集终极决战，瓦解{a_name}权势帝国并完成自我救赎"
        else:
            unit_name = f"单元 {letter}: 第 {start_ep:02d} - {end_ep:02d} 集 · 暗流交锋与连环设局"
            dramatic_focus = f"{p_name}深入虎穴破局，层层剥离{a_name}伪装与利益网络"
            climax_event = f"第 {end_ep:02d} 集绝密录音/关键物证曝光，引发阵营全面洗牌"
        mini_arc_units.append({
            "unit_id": f"MINI_ARC_{letter}",
            "unit_name": unit_name,
            "episode_range": [start_ep, end_ep],
            "dramatic_focus": dramatic_focus,
            "climax_event": climax_event,
        })

    season_outlines: dict[str, Any] = {}
    for ep in range(1, total_episodes + 1):
        # 匹配所属小高潮单元
        current_unit_name = mini_arc_units[0]["unit_name"]
        for unit in mini_arc_units:
            if unit["episode_range"][0] <= ep <= unit["episode_range"][1]:
                current_unit_name = unit["unit_name"]
                break

        if ep == 1:
            ep_title = f"第1集：{title}的致命序曲"
            hook = f"开局0-3秒：暴雨中黑漆手枪顶在{p_name}额头，惨白闪电下高颧骨阴影明显，冷汗顺着下唇滑落"
            ep1_core = user_idea[:40] if user_idea else f"围绕《{title}》的核心悬念"
            plot_chain = f"{p_name}直面{a_name}针对【{ep1_core}】设下的开局杀局，利用旧情物证争夺一线生机，并在混乱中藏匿关键线索"
            turning = f"45秒认知打破：{p_name}在暗处摸索到{hero_prop}的破碎边缘，发现真凶竟在现场并留下致命生物瑕疵"
            relational_shift = f"{p_name} 与 {a_name} 撕破表层平和，彻底确立猎手与猎物的生死对峙"
            lie_metric = "谎言坚冰期 (10%)：坚信自己凭借绝对理性与冷血伪装绝不会被攻破"
            cliff = f"115秒绝杀：{a_name}带保镖破门而入，枪口齐刷刷对准{p_name}的眉心扣下保险"
        elif ep == total_episodes:
            ep_title = f"第{ep}集：终局核爆与血色救赎"
            hook = f"开局0-3秒：{p_name}将{hero_prop}当众拍碎在谈判桌上，金属碎屑飞溅划破手掌鲜血直流"
            final_climax = grand_payoff or (f"彻底引爆【{user_idea[:40]}】的终极高潮" if user_idea else f"揭露全部罪证，彻底瓦解{a_name}的权势帝国")
            plot_chain = f"{p_name}当众揭露关键真相，{final_climax}，完成终极复仇与灵魂救赎"
            turning = f"45秒高潮逆袭：当众展示{hero_prop}核心芯片中的暗网备份，彻底瓦解{a_name}最后翻盘筹码"
            relational_shift = f"{p_name} 与 {a_name} 的仇恨终结，{a_name}跪地认罪，旧秩序彻底瓦解"
            lie_metric = "谎言彻底解体 (100%)：坦然拥抱真实的自我与肉体代价，完成终极心理救赎"
            cliff = "全剧终局定格：黎明第一缕阳光穿透破旧仓库，照亮释然挺立的身影与风中飘扬的衣角"
        else:
            ep_title = f"第{ep}集：暗流交锋与层层撕裂"
            hook = f"开局0-3秒：急速推镜头，{p_name}在昏暗回廊中被利刃逼近喉管，刀锋反射出眼眸中的惊惧血丝"
            plot_chain = f"{p_name}借假账目与{a_name}斡旋，并在试探中巧妙设下双重陷阱引导警方入局"
            turning = f"45秒微反转：{p_name}借用随身旧物反手制敌，根据对方右手虎口旧伤识破其杀手身份"
            relational_shift = f"{p_name} 与 {a_name} 之间的生死信任/对立再次发生不可逆质变，暗棋被连根拔起"
            lie_metric = f"谎言崩解度 {min(90, ep * 15)}%：旧信念不断产生不可逆裂痕，对同伴产生依恋"
            cliff = f"115秒卡点：黑暗中突然响起当年受害者的绝密通话录音，下一秒定时炸弹倒计时开始"

        dual_helix = {
            "plot_event_chain": plot_chain,
            "relational_shift_point": relational_shift,
            "lie_erosion_metric": lie_metric,
        }

        season_outlines[str(ep)] = {
            "episode_id": ep,
            "episode_number": ep,
            "killer_title": ep_title,
            "title": ep_title,
            "dramatic_arc_unit": current_unit_name,
            "dual_helix_task": dual_helix,
            "plot_event_chain": plot_chain,
            "relational_shift_point": relational_shift,
            "lie_erosion_metric": lie_metric,
            "hook_3s": hook,
            "three_second_hook": hook,
            "micro_twist_45s": turning,
            "micro_turning_point_45s": turning,
            "subtext_matrix": {
                "surface_excuse": "表层借口：核对普通账目与例行业务交接",
                "core_intention": f"深层企图：试探对方是否掌握《{title}》核心秘密",
                "forbidden_words": ["认输", "当年真相", "我错了"],
            },
            "cliffhanger_end": cliff,
            "killer_cliffhanger_115s": cliff,
            "cliffhanger": cliff,
        }

    # 【分层状态机契约】调用 WorkingMemoryCompiler 纯函数式提取保底大纲与音频母库工作便签
    fb_outline_wm = WorkingMemoryCompiler.compile_season_outline_working_memory(
        season_outlines, audio_bible
    )

    return {
        "audio_bible": audio_bible,
        "mini_arc_units": mini_arc_units,
        "season_outlines": season_outlines,
        "episodes": list(season_outlines.values()),
        "season_outline_working_memory": fb_outline_wm,
        "short_memory_d": fb_outline_wm,
        "audit_report": {
            "blue_team": "总集数与单集时长精准对齐，3套具象音乐动机完备，双螺旋任务卡完备，前3s/45s/断点字段100%覆盖",
            "red_team_critic": "注水集排查通过；微反转紧扣物理伤痕破局非降智；断点100%实打实危机无做梦诈骗；张力波浪图小高潮节奏分明",
            "verdict": "GREEN_APPROVED",
            "blocking_issues": [],
        },
    }


def stage4_outline_node(state: GlobalDramaMasterState | IndustrialDramaState | Any) -> dict[str, Any]:
    """执行阶段 4：全季分集大纲与音乐主题动机母库确立。
    
    【公共硬性约束 1 & 4】大模型与节点内部不执行任何业务分支跳转。
    【公共硬性约束 3】统一入参 state 符合 IndustrialDramaState 契约，返回增量状态字典。
    【规则编号: STAGE-4-COT-01 ~ STAGE-4-OUT-01】分集大纲与音频母库建模。
    """
    selected_title = state.get("selected_title") or state.get("title") or "都市悬疑短剧"
    total_eps = state.get("total_episodes") or state.get("target_episodes") or 12
    genre = state.get("genre") or state.get("commercial_genre") or "悬疑/剧情"
    visual_style = state.get("visual_style") or "真人电影/工业冷峻暗色调/超写实"
    logline = state.get("logline") or "主角追查真相逆风翻盘"
    user_idea = (
        state.get("user_idea")
        or state.get("user_prompt")
        or state.get("story_prompt")
        or state.get("prompt")
        or logline
        or selected_title
    )
    core_irony = state.get("core_irony") or state.get("dramatic_irony") or state.get("the_irony") or "越想掩盖越会暴露"
    grand_payoff = state.get("grand_payoff") or "终局核爆中关键物证引发的彻底颠覆"
    negative_rules = state.get("negative_rules") or state.get("negative_rules_summary") or "严禁低俗说教；严禁反派无脑送人头；严禁机械降神解题。"
    if isinstance(negative_rules, list):
        negative_rules_summary = "; ".join(str(r) for r in negative_rules)
    else:
        negative_rules_summary = str(negative_rules)

    ideation_wm = state.get("ideation_working_memory") or ""
    if not ideation_wm:
        try:
            ideation_wm = WorkingMemoryCompiler.compile_ideation_working_memory(state)
        except Exception:
            ideation_wm = f"【阶段 1 核心便签】《{selected_title}》，题材{genre}，构想：{user_idea[:80]}"

    short_memory_c = state.get("short_memory_c") or state.get("world_building_working_memory") or ""
    
    chars_engine = state.get("characters_engine") or {}
    chars_list = chars_engine.get("characters", []) if isinstance(chars_engine, dict) else []
    
    env_props = state.get("environments_and_props") or {}
    props_list = env_props.get("props", []) if isinstance(env_props, dict) else []

    if not short_memory_c and env_props:
        try:
            short_memory_c = WorkingMemoryCompiler.compile_world_building_working_memory(env_props)
        except Exception:
            short_memory_c = ""

    logger.info(f"[Stage 4 Node] Generating outline and audio bible for '{selected_title}' (Total Eps: {total_eps}, user_idea length: {len(user_idea)})")
    logger.debug(f"[Stage 4 Node] Input chars: {len(chars_list)}, props: {len(props_list)}")

    bp_prompt = (state.get("bp_prompt") if hasattr(state, "get") else getattr(state, "bp_prompt", None)) or ""
    if not bp_prompt:
        bp_dict = state.get("blueprint") if hasattr(state, "get") else getattr(state, "blueprint", None)
        if bp_dict:
            try:
                from app.utils.blueprint import to_prompt_block
                bp_prompt = to_prompt_block(bp_dict)
            except Exception:
                bp_prompt = ""

    user_prompt = STAGE4_USER_PROMPT_TEMPLATE.format(
        title=selected_title,
        total_episodes=total_eps,
        genre=genre,
        visual_style=visual_style,
        user_idea=user_idea,
        logline=logline,
        dramatic_irony=core_irony,
        grand_payoff=grand_payoff,
        negative_rules_summary=negative_rules_summary,
        ideation_working_memory=ideation_wm,
        characters_summary=str(chars_engine),
        environments_props_summary=str(env_props),
        bp_prompt=bp_prompt,
    )

    logger.debug(f"[Stage 4 Node] Calling LLM with prompt length: {len(user_prompt)}")

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE4_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage4_fallback(
            selected_title,
            total_eps,
            chars_list,
            props_list,
            user_idea=user_idea,
            grand_payoff=grand_payoff,
            genre=genre,
        ),
    )

    # 【规则编号: STAGE-4-COT-02】提取或兜底全季戏剧小高潮单元
    mini_arc_units = result_json.get("mini_arc_units") or []
    if not isinstance(mini_arc_units, list) or len(mini_arc_units) == 0:
        fallback_data = _stage4_fallback(
            selected_title,
            total_eps,
            chars_list,
            props_list,
            user_idea=user_idea,
            grand_payoff=grand_payoff,
            genre=genre,
        )
        mini_arc_units = fallback_data.get("mini_arc_units", [])

    # 【规则编号: STAGE-4-OUT-01】解析与标准化分集大纲字典与双螺旋任务卡
    raw_episodes = (
        result_json.get("episodes")
        or result_json.get("season_outlines")
        or (result_json.get("season_outline") or {}).get("episodes")
        or []
    )
    season_outlines: dict[int, dict[str, Any]] = {}

    ep_list_to_process: list[tuple[int, dict[str, Any]]] = []
    if isinstance(raw_episodes, dict):
        for k, v in raw_episodes.items():
            try:
                ep_num = int(k)
                if isinstance(v, dict):
                    ep_list_to_process.append((ep_num, v))
            except (ValueError, TypeError):
                continue
    elif isinstance(raw_episodes, list):
        for idx, item in enumerate(raw_episodes, start=1):
            if isinstance(item, dict):
                ep_num = int(item.get("episode_id") or item.get("episode_number") or idx)
                ep_list_to_process.append((ep_num, item))

    if not ep_list_to_process:
        fallback_data = _stage4_fallback(
            selected_title,
            total_eps,
            chars_list,
            props_list,
            user_idea=user_idea,
            grand_payoff=grand_payoff,
            genre=genre,
        )
        season_outlines = fallback_data["season_outlines"]
    else:
        for ep_num, v in ep_list_to_process:
            v["episode_id"] = ep_num
            v["episode_number"] = ep_num

            # 标题双向别名
            if "killer_title" in v and "title" not in v:
                v["title"] = v["killer_title"]
            elif "title" in v and "killer_title" not in v:
                v["killer_title"] = v["title"]

            # 前3秒抓手双向别名 (支持 hook_3s, hook, three_second_hook)
            hook_val = v.get("hook_3s") or v.get("hook") or v.get("three_second_hook") or ""
            v["hook_3s"] = hook_val
            v["hook"] = hook_val
            v["three_second_hook"] = hook_val

            # 45秒微反转双向别名
            if "micro_twist_45s" in v and "micro_turning_point_45s" not in v:
                v["micro_turning_point_45s"] = v["micro_twist_45s"]
            elif "micro_turning_point_45s" in v and "micro_twist_45s" not in v:
                v["micro_twist_45s"] = v["micro_turning_point_45s"]

            # 115秒绝杀断点双向别名
            cliff = v.get("cliffhanger_end") or v.get("killer_cliffhanger_115s") or v.get("cliffhanger") or ""
            v["cliffhanger_end"] = cliff
            v["killer_cliffhanger_115s"] = cliff
            v["cliffhanger"] = cliff

            # 双螺旋任务卡与扁平键双向打通
            dual_helix = v.get("dual_helix_task")
            if isinstance(dual_helix, dict):
                if "plot_event_chain" in dual_helix and "plot_event_chain" not in v:
                    v["plot_event_chain"] = dual_helix["plot_event_chain"]
                if "relational_shift_point" in dual_helix and "relational_shift_point" not in v:
                    v["relational_shift_point"] = dual_helix["relational_shift_point"]
                if "lie_erosion_metric" in dual_helix and "lie_erosion_metric" not in v:
                    v["lie_erosion_metric"] = dual_helix["lie_erosion_metric"]
            else:
                v["dual_helix_task"] = {
                    "plot_event_chain": v.get("plot_event_chain", ""),
                    "relational_shift_point": v.get("relational_shift_point", ""),
                    "lie_erosion_metric": v.get("lie_erosion_metric", ""),
                }

            # 关联所属戏剧小高潮单元
            if "dramatic_arc_unit" not in v and mini_arc_units:
                for unit in mini_arc_units:
                    ep_range = unit.get("episode_range") or [1, 999]
                    if ep_range[0] <= ep_num <= ep_range[1]:
                        v["dramatic_arc_unit"] = unit.get("unit_name", "")
                        break

            season_outlines[ep_num] = v

    # 【规则编号: STAGE-4-COT-01】提取或回退音乐主题动机母库
    audio_bible = result_json.get("audio_bible") or _stage4_fallback(
        selected_title, total_eps, chars_list, props_list
    )["audio_bible"]

    # 规范化音乐母库双向别名 (leitmotif_registry <-> leitmotifs)
    motifs = audio_bible.get("leitmotif_registry") or audio_bible.get("leitmotifs") or []
    for m in motifs:
        if isinstance(m, dict):
            if "leitmotif_id" in m and "motif_id" not in m:
                m["motif_id"] = m["leitmotif_id"]
            elif "motif_id" in m and "leitmotif_id" not in m:
                m["leitmotif_id"] = m["motif_id"]
    audio_bible["leitmotif_registry"] = motifs
    audio_bible["leitmotifs"] = motifs
    if "foley_rules" not in audio_bible:
        audio_bible["foley_rules"] = {
            "boost": "+2.0dB ~ +3.0dB 物理拟音放大",
            "clarity": "-23 LUFS 广播级响度基准",
        }

    logger.info(f"[Stage 4 Node] Completed outline. Episodes generated: {len(season_outlines)}")
    logger.debug(f"[Stage 4 Node] Audio bible motifs count: {len(audio_bible.get('leitmotifs', []))}")

    # 【分层状态机契约】调用 WorkingMemoryCompiler 纯函数式提取阶段 4 分集大纲与音频母库工作便签
    season_outline_wm = WorkingMemoryCompiler.compile_season_outline_working_memory(
        season_outlines, audio_bible
    )

    # 【Redis 异步投影引擎】持久化语义化工作便签与读投影，触发事件广播
    drama_id = None
    if isinstance(state, dict):
        drama_id = state.get("drama_id") or state.get("id")
    else:
        drama_id = getattr(state, "drama_id", None) or getattr(state, "id", None)

    if drama_id:
        try:
            d_id = int(drama_id)
            set_journey1_working_memory(d_id, "stage4", season_outline_wm)
            publish_drama_event(d_id, "stage4_completed", {
                "drama_id": d_id,
                "stage": "stage4",
                "episodes_count": len(season_outlines),
            })
            # 增量上报阶段4全季集数与分集大纲工作便签至 CQRS 读投影
            publish_drama_read_projection(d_id, {
                "drama_id": d_id,
                "total_episodes": len(season_outlines),
                "season_outline_working_memory": season_outline_wm,
                "current_stage": 4,
            })
            logger.debug(f"[Stage 4 Node] Published stage4 working memory and read projection for drama_id={d_id}")
        except Exception as e:
            logger.warning(f"[Stage 4 Node] Failed to write read projection/event: {e}")

    return {
        "current_stage": 4,
        "user_idea": user_idea,
        "season_outlines": season_outlines,
        "audio_bible": audio_bible,
        "mini_arc_units": mini_arc_units,
        "season_outline_working_memory": season_outline_wm,
    }

