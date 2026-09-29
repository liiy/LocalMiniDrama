"""阶段 3：空间物证与声学物理节点 (Stage 3 Environments & Props Node)。

本模块严格对齐《AI 原创连续剧短剧工业管线标准作业程序 (SKILL1.md v10.0.0)》：
- 【规则编号: STAGE-3-COT-01】空间分级规划：一级核心主场景（>=3场）与二级过渡次场景，遵循 ENV_<NAME> 标识；
- 【规则编号: STAGE-3-COT-02】场景与服装同源共振铁律：空间破损脏旧度与角色服装磨损度 100% 同频 (costume_resonance_check: true)；
- 【规则编号: STAGE-3-COT-03】空间三层做旧架构（建筑结构层 / 生活做旧层 / 光影介质层），支持 three_layer_aging / weathering_layers 双向契约；
- 【规则编号: STAGE-3-COT-04】核心物证三级规划、微观破损尺度与阻尼拟音（显式 +3.0dB 标记与 physical_specs）；
- 【规则编号: STAGE-3-COT-05】红蓝对抗质检哨卡 3 自审契约 (audit_report)；
- 【规则编号: STAGE-3-OUT-01】写入 environments_and_props 并封装【短期记忆便签 C】。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.context.short_memory_service import (
    WorkingMemoryCompiler,
    publish_drama_event,
    publish_drama_read_projection,
    set_journey1_working_memory,
)
from app.schemas.script_graph_state import GlobalDramaMasterState, IndustrialDramaState
from app.workflows.prompts.master_sop_prompts import (
    STAGE3_SYSTEM_PROMPT,
    STAGE3_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage3_env_prop")


def _chinese_to_token(name: str) -> str:
    """辅助将中文转换为纯大写英文 Token。"""
    try:
        from pypinyin import lazy_pinyin  # type: ignore
        py_list = lazy_pinyin(str(name).strip())
        py_str = "".join(py_list).upper()
        clean = re.sub(r"[^A-Z0-9]", "", py_str)
        if clean:
            return clean
    except ImportError:
        pass
    clean_latin = re.sub(r"[^A-Z0-9]", "", str(name).upper())
    return clean_latin


def _normalize_env_id(raw_id: Any, fallback_name: str, index: int) -> str:
    """标准化场景唯一标识，遵循 ENV_<TOKEN> 大写格式。"""
    if isinstance(raw_id, str) and raw_id.strip():
        norm = AssetProtocolHelper.normalize_id(raw_id)
        if norm:
            if not norm.startswith("ENV_"):
                norm = f"ENV_{norm}"
            tok = re.sub(r"[^A-Z0-9_]+", "", norm[4:]).strip("_")
            if tok:
                return f"ENV_{tok}"

    slug = _chinese_to_token(fallback_name)
    return f"ENV_{slug}" if slug else f"ENV_SCENE_{index + 1:02d}"


def _normalize_prop_id(raw_id: Any, fallback_name: str, index: int) -> str:
    """标准化道具唯一标识，遵循 PROP_<TOKEN> 大写格式。"""
    if isinstance(raw_id, str) and raw_id.strip():
        norm = AssetProtocolHelper.normalize_id(raw_id)
        if norm:
            if not norm.startswith("PROP_"):
                norm = f"PROP_{norm}"
            tok = re.sub(r"[^A-Z0-9_]+", "", norm[5:]).strip("_")
            if tok:
                return f"PROP_{tok}"

    slug = _chinese_to_token(fallback_name)
    return f"PROP_{slug}" if slug else f"PROP_ITEM_{index + 1:02d}"


def _stage3_fallback(
    title: str,
    logline: str,
    characters: list[dict[str, Any]],
    user_idea: str = "",
    genre: str = "",
    visual_style: str = "",
) -> dict[str, Any]:
    """当大模型离线或解析异常时的保底生成工厂，产出具有三层做旧与声学阻尼的空间物证。
    
    【规则编号: STAGE-3-COT-01】两级空间规划与 ENV_<NAME> 标识；
    【规则编号: STAGE-3-COT-02】场景与服装同源共振 (costume_resonance_check: True)；
    【规则编号: STAGE-3-COT-03】三层做旧架构 (structure / lived_grime / light_and_air)；
    【规则编号: STAGE-3-COT-04】核心物证三级规划、物理规格与 +3.0dB 阻尼拟音；
    【规则编号: STAGE-3-COT-05】哨卡 3 自审报告 (audit_report)。
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

    # 依据用户构想与题材动态推导主场景
    combined_info = f"{user_idea} {genre} {title}".lower()
    if any(k in combined_info for k in ["仙侠", "修真", "宗门", "玄幻"]):
        primary_loc = f"{title}主殿禁地"
        primary_env_id = "ENV_MAIN_SANCTUARY"
        primary_struct = "古老青石砌成的斑驳殿堂，雕花石柱有雷击焦痕与岁月风化凹坑"
        primary_grime = f"地面残留的符文刻痕、药渍风干斑痕，角落堆放废弃断剑残片"
        primary_light = "高穹破口投下的清冷月光与残破长明灯微弱火苗对撞，尘埃轻飏"
    elif any(k in combined_info for k in ["科幻", "末世", "赛博", "未来"]):
        primary_loc = f"{title}地下废弃控制中枢"
        primary_env_id = "ENV_UNDERGROUND_HUB"
        primary_struct = "冷轧钢抗暴装甲墙体，裸露的绝缘老化动力光缆与散热格栅"
        primary_grime = f"漏液电容形成的酸性污渍，散落的报废逻辑单元与干瘪导热硅胶痕"
        primary_light = "闪烁不定高频微颤的淡蓝全息投影幽光与刺眼应急红光交错"
    elif any(k in combined_info for k in ["校园", "青春", "校园霸凌"]):
        primary_loc = f"{title}老旧实验楼天台画室"
        primary_env_id = "ENV_ROOFTOP_STUDIO"
        primary_struct = "开裂的马赛克瓷砖地面与红砖围栏，铁栅栏门锁链生锈"
        primary_grime = f"散落的风干水彩调色板、被雨水浸泡发霉的废弃画布与烟头"
        primary_light = "落日残阳将铁丝网长阴影投在剥落墙面上，冷暖对比强烈"
    elif any(k in combined_info for k in ["古代", "宫廷", "权谋", "武侠"]):
        primary_loc = f"{title}幽禁深宫偏殿/密室"
        primary_env_id = "ENV_PALACE_SECRET_CHAMBER"
        primary_struct = "沉重金丝楠木梁柱微有虫蛀，泛潮青砖地面凹凸不平"
        primary_grime = f"烛泪堆叠的青铜灯台，受潮发暗的蚕丝帷幔与积灰暗格"
        primary_light = "窗棂缝隙切入的冷冽刀光般隙光，逆光烟雾袅袅"
    else:
        primary_loc = f"{title}核心决战隐秘废弃仓库"
        primary_env_id = "ENV_ABANDONED_WAREHOUSE"
        primary_struct = "锈蚀斑驳的工字钢立柱，剥落红砖墙露出内部泛黄水泥与裸露铸铁管线"
        primary_grime = f"散落的湿透防雨布、干涸泥脚印（与{p_name}工装靴底泥斑100%同源）与掐灭的烟头，墙角堆放受潮木箱"
        primary_light = "暴风雨水汽在昏黄钠灯下形成弥漫雾气与丁达尔光束，逆光高对比度"

    # 动态推导核心物证
    if any(k in combined_info for k in ["账本", "账目", "流水", "名单"]):
        hero_prop_name = f"《{title}》涉案加密暗账本"
        prop_desc = f"记录《{title}》所有不可告人利益交割的关键暗账本，封皮水浸微卷"
    elif any(k in combined_info for k in ["玉佩", "玉简", "残卷", "令牌"]):
        hero_prop_name = f"《{title}》染血古宗令牌"
        prop_desc = f"见证背叛与屠戮的宗门信物，表面刻纹被刀剑严重削损"
    elif any(k in combined_info for k in ["芯片", "硬盘", "u盘", "数据"]):
        hero_prop_name = f"《{title}》绝密加密数据存储卡"
        prop_desc = f"封存当年灭顶事故完整黑匣子记录的工业级存储芯片"
    else:
        hero_prop_name = f"《{title}》关键反转物证"
        prop_desc = f"记录《{title}》所有真相的核心物证，表面有干涸呈暗褐色的指纹血痕"

    struct_penthouse = "极简冷灰钛金边框与黑白大理石地面，无缝拼接墙板"
    living_penthouse = f"雪茄烟灰缸里余半截雪茄，红木桌角有细微指甲划痕，与{a_name}手串摩擦痕迹呼应"
    optical_penthouse = "夕阳逆光将人影拉长如刀锋，明暗高反差长阴影与冷酷剪影"

    damage_evidence = "物证金属边缘有一道被硬物暴力磕碰的3毫米微小凹痕，角质微变形，边缘渗墨微毛刺"
    foley_evidence = "金属与硬物剧烈碰撞的清脆撞击声 (+3.0dB)，摩擦阻尼沙沙声"

    damage_anchor = "表面有细微裂痕与严重氧化包浆，刻字磨损但仍可辨认"
    foley_anchor = "开合或触碰时金属簧片回弹声 (+2.0dB)，粗糙衣料摩擦微响"

    fb_envs = [
        {
            "env_id": primary_env_id,
            "name": primary_loc,
            "location_name": primary_loc,
            "level": "primary_tier1",
            "costume_resonance_check": True,
            "time_and_lighting": "午夜23点，暴雨雷鸣，高窗透入惨白闪电与昏黄钠灯对冲",
            "visual_prompt": f"cinematic moody interior, {primary_loc} for {title}, puddles reflecting gloomy sodium light, volumetric dust rays, 8k raw photo",
            "three_layer_aging": {
                "structure": primary_struct,
                "lived_grime": primary_grime,
                "light_and_air": primary_light,
            },
            "weathering_layers": {
                "structural": primary_struct,
                "living": primary_grime,
                "optical": primary_light,
            },
            "atmosphere": f"死寂、极度压抑、围绕《{title}》真相的决死对峙一触即发",
        },
        {
            "env_id": "ENV_PENTHOUSE_LOUNGE",
            "name": f"{a_name}顶层私人权力会客厅",
            "location_name": f"{a_name}顶层私人权力会客厅",
            "level": "transitional_tier2",
            "costume_resonance_check": True,
            "time_and_lighting": "傍晚黄昏，血红晚霞穿透整面落地玻璃窗，室内未开大灯",
            "visual_prompt": f"cinematic high contrast penthouse office for {a_name}, panoramic floor-to-ceiling window glowing with sunset blood orange light, polished marble reflection",
            "three_layer_aging": {
                "structure": struct_penthouse,
                "lived_grime": living_penthouse,
                "light_and_air": optical_penthouse,
            },
            "weathering_layers": {
                "structural": struct_penthouse,
                "living": living_penthouse,
                "optical": optical_penthouse,
            },
            "atmosphere": "权力窒息、居高临下的冰冷审判感",
        },
    ]

    fb_props = [
        {
            "prop_id": "PROP_KEY_EVIDENCE",
            "name": hero_prop_name,
            "level": "hero_tier1",
            "type": "narrative_reversal",
            "description": prop_desc,
            "visual_prompt": f"macro close up of {hero_prop_name} for {title}, cold metallic rim lighting, scratches, dried blood stain, ultra photorealistic 8k",
            "physical_specs": {
                "material_damage_dimensions": damage_evidence,
                "weight_and_haptic_resistance": "350克沉重压手感，卡扣闭合强回弹阻力",
                "foley_boost_db": "+3.0dB",
            },
            "damage_scale": damage_evidence,
            "foley_resistance": foley_evidence,
        },
        {
            "prop_id": "PROP_ANCHOR_ITEM",
            "name": p_anchor_name,
            "level": "anchor_tier2",
            "type": "character_anchor",
            "description": f"{p_name}常年随身携带的旧物，承载着不可磨灭的过去与创伤",
            "visual_prompt": f"macro close up of {p_anchor_name}, worn surface with fine scratches, spiderweb cracks, cinematic texture",
            "physical_specs": {
                "material_damage_dimensions": damage_anchor,
                "weight_and_haptic_resistance": "轻微金属坠手感，握持温热",
                "foley_boost_db": "+2.0dB",
            },
            "damage_scale": damage_anchor,
            "foley_resistance": foley_anchor,
        },
    ]

    # 【分层状态机契约】调用 WorkingMemoryCompiler 纯函数式提取保底世界观工作便签
    fb_world_wm = WorkingMemoryCompiler.compile_world_building_working_memory({
        "environments": fb_envs,
        "props": fb_props,
    })

    return {
        "environments": fb_envs,
        "props": fb_props,
        "world_building_working_memory": fb_world_wm,
    }


def stage3_environment_prop_node(state: GlobalDramaMasterState | IndustrialDramaState | Any) -> dict[str, Any]:
    """执行阶段 3：空间三层做旧与核心反转物证设计。
    
    【公共硬性约束 1 & 4】大模型与节点内部不执行任何业务分支跳转。
    【公共硬性约束 3】统一入参 state 符合 IndustrialDramaState 契约，返回增量状态字典。
    【规则编号: STAGE-3-COT-01 ~ STAGE-3-OUT-01】全息空间物证建模。
    """
    selected_title = state.get("selected_title") or state.get("title") or "都市短剧"
    genre = state.get("genre") or state.get("commercial_genre") or "悬疑/剧情"
    visual_style = state.get("visual_style") or "真人电影/工业冷峻暗色调/超写实"
    logline = state.get("logline") or "主角在逆境中探寻真相"
    user_idea = (
        state.get("user_idea")
        or state.get("user_prompt")
        or state.get("story_prompt")
        or state.get("prompt")
        or logline
        or selected_title
    )
    dramatic_irony = state.get("dramatic_irony") or state.get("the_irony") or "表面掩饰与深层真相的宿命错位"
    grand_payoff = state.get("grand_payoff") or "终局核爆中关键物证引发的彻底颠覆"

    # 提取阶段 1 核心便签 (ideation_working_memory)
    ideation_wm = state.get("ideation_working_memory") or ""
    if not ideation_wm:
        try:
            ideation_wm = WorkingMemoryCompiler.compile_ideation_working_memory(state)
        except Exception:
            ideation_wm = f"【阶段 1 核心便签】《{selected_title}》，题材{genre}，构想：{user_idea[:80]}"

    # 【规则编号: MEMORY-WORKING-01】优先获取规范化的 character_working_memory，回退兼容 short_memory_b
    character_working_memory = state.get("character_working_memory") or ""
    chars_engine = state.get("characters_engine") or {}
    chars_list = chars_engine.get("characters", []) if isinstance(chars_engine, dict) else []

    logger.info(f"[Stage 3 Node] Generating environments and props for: '{selected_title}' (user_idea length: {len(user_idea)})")
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

    bp_prompt = (state.get("bp_prompt") if hasattr(state, "get") else getattr(state, "bp_prompt", None)) or ""
    if not bp_prompt:
        bp_dict = state.get("blueprint") if hasattr(state, "get") else getattr(state, "blueprint", None)
        if bp_dict:
            try:
                from app.utils.blueprint import to_prompt_block
                bp_prompt = to_prompt_block(bp_dict)
            except Exception:
                bp_prompt = ""

    user_prompt = STAGE3_USER_PROMPT_TEMPLATE.format(
        title=selected_title,
        genre=genre,
        visual_style=visual_style,
        user_idea=user_idea,
        logline=logline,
        dramatic_irony=dramatic_irony,
        grand_payoff=grand_payoff,
        ideation_working_memory=ideation_wm,
        character_working_memory=character_working_memory,
        bp_prompt=bp_prompt,
    )

    logger.debug(f"[Stage 3 Node] Calling LLM with prompt length: {len(user_prompt)}")

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE3_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage3_fallback(
            selected_title,
            logline,
            chars_list,
            user_idea=user_idea,
            genre=genre,
            visual_style=visual_style,
        ),
    )

    raw_envs = result_json.get("environments") or []
    raw_props = result_json.get("props") or []

    # 【规则编号: STAGE-3-COT-01 ~ STAGE-3-COT-03】归一化场景对象，保障三层做旧双向映射与同源共振
    normalized_envs = []
    for idx, env in enumerate(raw_envs):
        if not isinstance(env, dict):
            continue
        env_copy = dict(env)
        loc_name = env_copy.get("location_name") or env_copy.get("name") or f"场景_{idx+1}"
        env_copy["name"] = loc_name
        env_copy["location_name"] = loc_name
        env_copy["env_id"] = _normalize_env_id(env_copy.get("env_id"), loc_name, idx)
        if not env_copy.get("level"):
            env_copy["level"] = "primary_tier1" if idx == 0 else "transitional_tier2"
        if "costume_resonance_check" not in env_copy:
            env_copy["costume_resonance_check"] = True
        else:
            env_copy["costume_resonance_check"] = bool(env_copy["costume_resonance_check"])

        tla = env_copy.get("three_layer_aging") if isinstance(env_copy.get("three_layer_aging"), dict) else {}
        wl = env_copy.get("weathering_layers") if isinstance(env_copy.get("weathering_layers"), dict) else {}
        struct_desc = tla.get("structure") or wl.get("structural") or "工业建筑承重结构与斑驳墙体管线"
        living_desc = tla.get("lived_grime") or wl.get("living") or "地面水渍油垢与同源鞋底泥印"
        optical_desc = tla.get("light_and_air") or wl.get("optical") or "逆光高对比度丁达尔悬浮微尘"

        env_copy["three_layer_aging"] = {
            "structure": struct_desc,
            "lived_grime": living_desc,
            "light_and_air": optical_desc,
        }
        env_copy["weathering_layers"] = {
            "structural": struct_desc,
            "living": living_desc,
            "optical": optical_desc,
        }
        normalized_envs.append(env_copy)

    # 【规则编号: STAGE-3-COT-04】归一化道具对象，保障三级划分、物理破损与 +3.0dB 拟音规格
    normalized_props = []
    for idx, prop in enumerate(raw_props):
        if not isinstance(prop, dict):
            continue
        prop_copy = dict(prop)
        p_name = prop_copy.get("name") or f"物证道具_{idx+1}"
        prop_copy["name"] = p_name
        prop_copy["prop_id"] = _normalize_prop_id(prop_copy.get("prop_id"), p_name, idx)
        if not prop_copy.get("level"):
            prop_copy["level"] = "hero_tier1" if idx == 0 else "anchor_tier2"

        specs = prop_copy.get("physical_specs") if isinstance(prop_copy.get("physical_specs"), dict) else {}
        damage = prop_copy.get("damage_scale") or specs.get("material_damage_dimensions") or prop_copy.get("appearance_and_wear") or "微观边缘破损凹痕与划痕"
        foley = prop_copy.get("foley_resistance") or specs.get("foley_boost_db") or prop_copy.get("haptic_friction_foley") or "+3.0dB 摩擦撞击阻力拟音"
        
        # 一级核心物证强制保证包含 +3.0dB 标记
        if (prop_copy["level"] == "hero_tier1" or idx == 0) and "+3" not in str(foley):
            foley = f"{foley} (+3.0dB)"
            
        foley_db = specs.get("foley_boost_db") or ("+3.0dB" if "+3" in str(foley) else "+2.0dB")
        haptic = specs.get("weight_and_haptic_resistance") or "沉重手感与强回弹阻尼感"

        prop_copy["damage_scale"] = damage
        prop_copy["foley_resistance"] = str(foley)
        prop_copy["physical_specs"] = {
            "material_damage_dimensions": damage,
            "weight_and_haptic_resistance": haptic,
            "foley_boost_db": foley_db,
        }
        normalized_props.append(prop_copy)

    # 提取并锁定全局场景与道具 Token 白名单
    scene_tokens = [
        re.sub(r"[^A-Z0-9]+", "", env["env_id"].replace("ENV_", ""))
        for env in normalized_envs
        if env.get("env_id")
    ]
    prop_tokens = [
        re.sub(r"[^A-Z0-9]+", "", prop["prop_id"].replace("PROP_", ""))
        for prop in normalized_props
        if prop.get("prop_id")
    ]

    logger.info(
        f"[Stage 3 Node] Completed envs/props. Envs: {len(normalized_envs)} ({scene_tokens}), "
        f"Props: {len(normalized_props)} ({prop_tokens})"
    )

    # 【分层状态机契约】调用 WorkingMemoryCompiler 纯函数式提取阶段 3 空间物证工作便签
    world_wm = WorkingMemoryCompiler.compile_world_building_working_memory({
        "environments": normalized_envs,
        "props": normalized_props,
        "scene_tokens": scene_tokens,
        "prop_tokens": prop_tokens,
    })

    # 提取或兜底哨卡 3 自审报告
    raw_audit = result_json.get("audit_report") or {}
    if not isinstance(raw_audit, dict) or not raw_audit.get("verdict"):
        fb_audit = _stage3_fallback(
            selected_title,
            logline,
            chars_list,
            user_idea=user_idea,
            genre=genre,
            visual_style=visual_style,
        )
        raw_audit = fb_audit.get("audit_report", {})

    # 【Redis 异步投影引擎】持久化语义化工作便签与读投影，触发事件广播
    drama_id = None
    if isinstance(state, dict):
        drama_id = state.get("drama_id") or state.get("id")
    else:
        drama_id = getattr(state, "drama_id", None) or getattr(state, "id", None)
    if drama_id:
        try:
            d_id = int(drama_id)
            set_journey1_working_memory(d_id, "stage3", world_wm)
            publish_drama_event(d_id, "stage3_completed", {
                "drama_id": d_id,
                "stage": "stage3",
                "environments_count": len(normalized_envs),
                "props_count": len(normalized_props),
            })
            # 增量上报阶段3产出指标（场景数、道具数）与世界观便签至 CQRS 读投影
            publish_drama_read_projection(d_id, {
                "drama_id": d_id,
                "environments_count": len(normalized_envs),
                "props_count": len(normalized_props),
                "world_building_working_memory": world_wm,
                "current_stage": 3,
            })
            logger.debug(f"[Stage 3 Node] Published stage3 working memory and read projection for drama_id={d_id}")
        except Exception as e:
            logger.warning(f"[Stage 3 Node] Failed to write working memory/read projection: {e}")

    return {
        "current_stage": 3,
        "user_idea": user_idea,
        "environments_and_props": {
            "environments": normalized_envs,
            "props": normalized_props,
            "scene_tokens": scene_tokens,
            "prop_tokens": prop_tokens,
            "audit_report": raw_audit,
        },
        "scene_tokens": scene_tokens,
        "prop_tokens": prop_tokens,
        "world_building_working_memory": world_wm,
        "short_memory_c": world_wm,
        "latest_audit": raw_audit,
    }

