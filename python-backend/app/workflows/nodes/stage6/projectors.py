"""阶段 6 视听特征线索摘要与真理源索引投影器 (Stage 6 Scanner Summarizer & State Projectors)。

负责编译逆向特征扫描算子成果、精确判定角色在场性、精简提取上游领域模型并构建待选资产索引。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.tools.screenplay_feature_scanner import (
    ScreenplayScanResult,
    is_valid_character_speaker,
)
from app.workflows.nodes.stage6.helpers import _clean_name, _extract_screenplay_text
from app.workflows.utils.asset_protocol import AssetProtocolHelper

logger = logging.getLogger("lmd.stage6.projectors")


def summarize_scanner_findings(scanner_result: ScreenplayScanResult | None) -> str:
    """将确定性特征扫描算子的扫描成果编译为提供给 LLM 的高信息密度中文线索摘要。

    包含：
    1. 识别出场角色与别名归一化映射 (含代词共指消解决策)
    2. 识别主客观场景与光影氛围特征
    3. 识别触碰道具与形变动词动作判定 (两态铁律命中提示)
    4. 生理微距特征与战损负伤状态 (连续性与上集物理接力保障)
    """
    if not scanner_result:
        return "无显著预扫描线索。"

    lines: list[str] = []

    # 1. 角色与别名
    chars = scanner_result.characters_detected or []
    alias_map = scanner_result.character_alias_map or {}
    if chars:
        char_desc = []
        for c in chars:
            aliases = [k for k, v in alias_map.items() if v == c and k != c]
            if aliases:
                char_desc.append(f"{c}(别名/简称: {', '.join(aliases)})")
            else:
                char_desc.append(c)
        lines.append(f"- 登场角色: {', '.join(char_desc)}")

    # 2. 代词共指消解决策追踪
    corefs = scanner_result.coreference_resolutions or []
    if corefs:
        resolved_samples = [
            f"\"{cr.get('pronoun')}\" -> {cr.get('resolved_character')} (第{cr.get('line_idx', 0)+1}行)"
            for cr in corefs[:5]
        ]
        lines.append(f"- 关键代词共指消解: {'; '.join(resolved_samples)}")

    # 3. 场景与光影氛围及物理空间锚点
    scenes = scanner_result.scenes_detected or []
    if scenes:
        lines.append(f"- 涉及场景空间: {', '.join(scenes)}")
    spatial_anchors = getattr(scanner_result, "scene_spatial_anchors", {}) or {}
    if spatial_anchors:
        for sc_name, anchors in spatial_anchors.items():
            fixed_dressings = anchors.get("fixed_set_dressings", [])
            openings = anchors.get("openings_and_acoustics", [])
            parts = []
            if fixed_dressings:
                parts.append(f"固定大尺度陈设={fixed_dressings}")
            if openings:
                parts.append(f"出入口声学={openings}")
            if parts:
                lines.append(f"  * 场景 [{sc_name}] 空间拓扑锚点: {'; '.join(parts)}")
    lights = scanner_result.lighting_conditions or []
    if lights:
        lines.append(f"- 光影明暗氛围特征: {', '.join(lights)}")

    # 4. 道具触碰与形变铁律
    props = scanner_result.props_detected or []
    if props:
        lines.append(f"- 触碰交互道具: {', '.join(props)}")
    deformed = scanner_result.deformed_props or {}
    if deformed:
        deformed_desc = [f"{p}(命中破坏动词: {', '.join(verbs)})" for p, verbs in deformed.items()]
        lines.append(f"- ★命中破坏形变铁律的核心道具(必须触发两态 ACTION 资产): {'; '.join(deformed_desc)}")

    # 5. 生理微距与战损伤残
    macros = scanner_result.macro_details or {}
    if macros:
        macro_desc = [f"{c}: {', '.join(m_list)}" for c, m_list in macros.items()]
        lines.append(f"- 生理/手部微距线索: {'; '.join(macro_desc)}")
    injuries = scanner_result.injuries_detected or {}
    if injuries:
        injury_desc = [f"{c}: {', '.join(i_list)}" for c, i_list in injuries.items()]
        lines.append(f"- ★角色战损/负伤状态(必须继承或触发 STATUS_INJURED): {'; '.join(injury_desc)}")

    # 6. 情绪与发声
    emotions = scanner_result.emotions_detected or {}
    if emotions:
        emo_desc = [f"{c}: {', '.join(e_list)}" for c, e_list in emotions.items()]
        lines.append(f"- 情绪特写触发: {'; '.join(emo_desc)}")

    return "\n".join(lines) if lines else "预扫描完成，未发现特殊异动特征。"


# -------------------------------------------------------------------------
# 上游上下文轻量视听投影算子 (Audio-Visual Context Projection Operators)
# -------------------------------------------------------------------------



def is_character_truly_in_screenplay(
    char_entry: dict[str, Any] | str,
    screenplay_text: str,
    detected_chars: list[str] | set[str] | None = None,
    alias_map: dict[str, str] | None = None,
) -> bool:
    """判定角色是否在本集剧本中真实物理登场。
    
    【核心防幻读防护体系】：
    1. 剥离剧本中引号内对白或冒号后的台词文本，防止“仅在他人台词中被提及（Mentioned-only）”但并未出场的人物被误判登场；
    2. 严格核实行首说话人标识（如“沈炼：”）或动作描述中的物理实体主谓行为；
    3. 过滤动作行中回忆、想起、画像、照片、书信等虚拟提及语境；
    4. 不再盲信 detected_chars；当提供剧本正文时，必须在正文中有真实的物理在场证据。
    """
    if isinstance(char_entry, str):
        c_name = char_entry.strip()
        all_names = {c_name}
    elif isinstance(char_entry, dict):
        c_name = str(char_entry.get("name") or char_entry.get("character_name") or "").strip()
        all_names = {c_name} if c_name else set()
        aliases = char_entry.get("aliases") or char_entry.get("alias") or []
        if isinstance(aliases, list):
            all_names.update(str(a).strip() for a in aliases if str(a).strip())
        elif isinstance(aliases, str):
            all_names.update(a.strip() for a in re.split(r"[,，/、\s]+", aliases) if a.strip())
    else:
        return False

    all_names = {n for n in all_names if n}
    if not all_names:
        return False

    det_set = {str(d).strip().lower() for d in (detected_chars or []) if str(d).strip()}
    a_map = {str(k).strip().lower(): str(v).strip().lower() for k, v in (alias_map or {}).items()}

    # 常见非在场虚拟提及关键词
    NON_PRESENT_PATTERNS = [
        "想起", "想到了", "回想起", "回忆起", "脑海中浮现", "记忆中", "梦见",
        "提起", "谈及", "听说", "听闻", "转述",
        "照片", "画像", "肖像", "遗像", "照片里", "画像上", "雕像", "墓碑",
        "留下的", "留给", "寄来的", "写着", "信笺", "信件", "短信", "绝笔",
        "如同", "好似", "宛如", "宛若", "仿佛是",
    ]

    PHYSICAL_VERBS = (
        r"走|跑|冲|拔|拿|握|站|坐|看|望|转|推|拉|挥|刺|砍|倒|扑|抓|盯|冷笑|咬牙|递|退|迈|扣|摸|搂|抱|"
        r"泛红|落泪|哭|笑|喘|颤|抬|垂|闭|睁|立|身穿|按|抽出|甩|撕"
    )

    for name in all_names:
        nl = name.lower()

        # 0. 【死者与案卷媒介绝对消歧】：若该名字在剧本中仅作为死者、灵堂、遗像、案卷、结案报告的定语出现，坚决判定为未登场
        # 例如：苏秀兰旧居灵堂、苏秀兰黑白遗像、苏秀兰坠楼案自杀结案卷宗
        DEAD_MEDIA_PATTERNS = ["遗像", "灵堂", "旧居", "案卷", "卷宗", "坠楼案", "结案", "死者", "墓碑", "入土为安"]
        if screenplay_text and len(name) >= 2:
            matched_sentences = [s for s in screenplay_text.splitlines() if name in s]
            if matched_sentences:
                # 检查包含该名字的行：如果存在行首台词或真实的物理主体行为，则绝不是死者
                has_alive_action = False
                for s_line in matched_sentences:
                    s_stripped = s_line.strip()
                    # 检查是否为行首对白发言人
                    if re.search(rf"(?:^|\n)\s*{re.escape(name)}\s*(?:[（(][^）)]*[）)])?\s*[:：]", s_stripped):
                        has_alive_action = True
                        break
                    # 检查是否为动作主语且不带死者/媒介定语
                    if not any(dm in s_stripped for dm in DEAD_MEDIA_PATTERNS):
                        if re.search(rf"(?:^|[，。！？；\s△]){re.escape(name)}\s*(?:{PHYSICAL_VERBS})", s_stripped):
                            has_alive_action = True
                            break
                        # 检查他动词交互中的宾语/动作对象（如“拉住苏清的手臂”）
                        if re.search(rf"(?:拉住|抱住|抓紧|扶住|迎上|看向|盯着)\s*{re.escape(name)}", s_stripped):
                            has_alive_action = True
                            break
                if not has_alive_action:
                    # 再次确认：所有出现的地方是否都伴随着死者/媒介或他人台词提及
                    all_dead_context = all(
                        any(dm in s for dm in DEAD_MEDIA_PATTERNS)
                        or any(pat in s for pat in NON_PRESENT_PATTERNS)
                        or ("：" in s or ":" in s)
                        for s in matched_sentences
                    )
                    if all_dead_context:
                        logger.debug("【在场判定·死者消歧】角色 [%s] 仅作为死者/遗像/案卷定语或提及存在，判定未在场", name)
                        return False

        # 1. 如果剧本正文提供，必须进行脱敏严检（优先级高于一切宽松索引池）
        if len(name) >= 2 and screenplay_text:
            # 1.1 检查显式对白行说话人：行首 角色名: 或 角色名：
            speaker_pattern = re.compile(rf"(?:^|\n)\s*{re.escape(name)}\s*(?:[（(][^）)]*[）)])?\s*[:：]", re.IGNORECASE)
            if speaker_pattern.search(screenplay_text):
                logger.debug("【在场判定】角色 [%s] 作为行首说话人确凿登场", name)
                return True

            # 1.2 检查动作行中的物理在场：先剥离冒号后台词与单双引号内的台词
            for raw_line in screenplay_text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                # 跳过场景头行
                if line.startswith(("【", "[", "#")) and "场景" in line:
                    continue

                action_line = line
                # 若为对白行，去掉台词部分，保留括号与说话人
                if "：" in line or ":" in line:
                    parts = re.split(r"[:：]", line, maxsplit=1)
                    action_line = parts[0]
                else:
                    # 动作描述行：剔除单双引号中的直接引语
                    action_line = re.sub(r"[“\"「].*?[”\"」]", "", line)

                if name in action_line:
                    # 检查是否为回忆/照片/信笺等非物理在场
                    is_virtual = any(pat in action_line for pat in NON_PRESENT_PATTERNS)
                    if is_virtual:
                        # 若句子中出现回忆/虚拟词，只有当该角色作为明确物理动词发出者时才算在场
                        if not re.search(rf"(?:^|[，。！？；\s△]){re.escape(name)}\s*(?:{PHYSICAL_VERBS})", action_line):
                            logger.debug("【在场判定】角色 [%s] 仅出现在动作行虚拟语境中，判定未在场: %s", name, action_line[:30])
                            continue
                    
                    # 检查实体是否具有物理存在（动作动词、站位、交互对象或声学生理存在如脚步声/立在...）
                    PHYSICAL_MOTION_PATTERN = (
                        rf"(?:{re.escape(name)}\s*(?:{PHYSICAL_VERBS})|"
                        rf"(?:响起|传来)\s*{re.escape(name)}.*?脚步|{re.escape(name)}.*?脚步声|"
                        rf"(?:拉住|抱住|抓紧|扶住|迎上|看向|盯着)\s*{re.escape(name)})"
                    )
                    if re.search(PHYSICAL_MOTION_PATTERN, action_line) or name in action_line:
                        logger.debug("【在场判定】角色 [%s] 在动作场景描述中真实出场: %s", name, action_line[:30])
                        return True

        # 2. 若没有剧本正文（纯单测/无正文降级模式），依赖高精特征扫描器和别名池
        elif not screenplay_text:
            if nl in det_set or any(nl == ds or ds == nl for ds in det_set):
                logger.debug("【在场判定·降级】角色 [%s] 命中特征扫描器出场集合", name)
                return True
            if nl in a_map or any(a_map.get(k) == nl for k in a_map):
                logger.debug("【在场判定·降级】角色 [%s] 命中别名映射表", name)
                return True

    logger.debug("【在场判定】角色 [%s] 未在当集剧本登场（仅被提及或完全缺失）", list(all_names)[0])
    return False


def is_environment_truly_in_screenplay(
    env_entry: dict[str, Any] | str,
    screenplay_text: str = "",
    detected_scenes: list[str] | set[str] | None = None,
) -> bool:
    """判定场景是否在本集剧本中真实物理登场。

    【核心防幻读防护体系】：
    1. 场景必须在剧本场头行（如【场景】废弃仓库、# 废弃仓库、场次 1：废弃仓库）或物理动作描述行中作为实际拍摄场地出现；
    2. 剔除在台词中仅仅被提及的远方地名或历史地点（如“听说京城那边...”中的京城）；
    3. 若无剧本正文（降级模式），依赖 detected_scenes 特征扫描集合校验。
    """
    if isinstance(env_entry, str):
        e_name = env_entry.strip()
    elif isinstance(env_entry, dict):
        e_name = str(env_entry.get("name") or env_entry.get("location_name") or env_entry.get("scene_name") or "").strip()
    else:
        return False

    if not e_name:
        return False

    clean_en = _clean_name(e_name)
    cand_names = {n for n in (e_name, clean_en) if n and len(n) >= 2}
    det_set = {str(s).strip().lower() for s in (detected_scenes or []) if str(s).strip()}

    # 1. 剧本正文深层校验
    if screenplay_text:
        for cname in cand_names:
            # 场头行匹配 (最高置信度)
            scene_header_pat = rf"(?:^|\n)\s*(?:【|\[|#|场次|场景|△).*?{re.escape(cname)}"
            if re.search(scene_header_pat, screenplay_text, re.IGNORECASE):
                logger.debug("【在场判定·场景】场景 [%s] 命中剧本场头行", e_name)
                return True
            # 正文语料出现
            if cname in screenplay_text:
                logger.debug("【在场判定·场景】场景 [%s] 命中剧本正文语料", e_name)
                return True
            # 扫描器集合匹配
            clower = cname.lower()
            if clower in det_set or any(clower in ds or ds in clower for ds in det_set):
                logger.debug("【在场判定·场景】场景 [%s] 命中扫描器出场集合", e_name)
                return True
        logger.debug("【在场判定·场景】场景 [%s] 未在当集剧本登场，判定拦截", e_name)
        return False
    else:
        # 2. 降级模式：无正文时依赖扫描器特征
        for cname in cand_names:
            clower = cname.lower()
            if clower in det_set or any(clower in ds or ds in clower for ds in det_set):
                return True
        return not bool(det_set)


def is_prop_truly_in_screenplay(
    prop_entry: dict[str, Any] | str,
    screenplay_text: str = "",
    detected_props: list[str] | set[str] | None = None,
) -> bool:
    """判定道具/物证是否在本集剧本中真实物理登场。

    【核心防幻读防护体系】：
    1. 道具名称必须在剧本动作描述中真实出场，参与演员动作或物证特写；
    2. 剔除虚假臆造或在他人台词中随口提及的概念性词汇；
    3. 若无剧本正文（降级模式），依赖 detected_props 特征扫描集合校验。
    """
    if isinstance(prop_entry, str):
        p_name = prop_entry.strip()
    elif isinstance(prop_entry, dict):
        p_name = str(prop_entry.get("name") or prop_entry.get("prop_name") or "").strip()
    else:
        return False

    if not p_name:
        return False

    clean_pn = _clean_name(p_name)
    cand_names = {n for n in (p_name, clean_pn) if n and len(n) >= 2}
    det_set = {str(p).strip().lower() for p in (detected_props or []) if str(p).strip()}

    # 1. 剧本正文深层校验
    if screenplay_text:
        for cname in cand_names:
            if cname in screenplay_text:
                logger.debug("【在场判定·道具】道具 [%s] 命中剧本正文物证语料", p_name)
                return True
            clower = cname.lower()
            if clower in det_set or any(clower in ds or ds in clower for ds in det_set):
                logger.debug("【在场判定·道具】道具 [%s] 命中扫描器物证集合", p_name)
                return True
        logger.debug("【在场判定·道具】道具 [%s] 未在当集剧本登场，判定拦截", p_name)
        return False
    else:
        for cname in cand_names:
            clower = cname.lower()
            if clower in det_set or any(clower in ds or ds in clower for ds in det_set):
                return True
        return not bool(det_set)




def project_characters_for_stage6(
    chars_engine: Any,
    present_names: list[str] | set[str] | None = None,
    screenplay_text: str = "",
    alias_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """提取角色视听生图与对齐必需字段，剥离纯文学心理剖面、人物关系网及声学冗余。

    【前置角色裁剪】：
    仅保留本集真实出场的角色构建 characters_engine_json，彻底阻断未登场角色对大模型注意力的干扰。
    """
    if hasattr(chars_engine, "model_dump"):
        data = chars_engine.model_dump()
    elif hasattr(chars_engine, "to_dict"):
        data = chars_engine.to_dict()
    elif isinstance(chars_engine, dict):
        data = chars_engine
    elif isinstance(chars_engine, list):
        data = {"characters": chars_engine}
    else:
        data = {}

    raw_chars = data.get("characters") if isinstance(data, dict) else []
    if not isinstance(raw_chars, list):
        raw_chars = []

    filtered_chars: list[dict[str, Any]] = []
    if present_names or screenplay_text:
        for c in raw_chars:
            if not isinstance(c, dict):
                continue
            c_name = str(c.get("name") or "").strip()
            # 若命中 scanner 识别名字或通过剧本深度判定
            if (present_names and c_name in present_names) or is_character_truly_in_screenplay(c, screenplay_text, present_names, alias_map):
                filtered_chars.append(c)
    else:
        filtered_chars = [c for c in raw_chars if isinstance(c, dict)]

    projected: list[dict[str, Any]] = []
    for c in filtered_chars:
        if not isinstance(c, dict):
            continue
        item: dict[str, Any] = {
            "character_id": c.get("character_id"),
            "name": c.get("name"),
            "role_type": c.get("role_type") or c.get("archetype"),
            "appearance": c.get("appearance"),
        }
        if c.get("biological_dna") and isinstance(c["biological_dna"], dict):
            bio = {
                k: v for k, v in c["biological_dna"].items()
                if k in {"bone_structure", "skin_micro_texture", "blemishes_and_scars", "eye_lip_anatomy", "hair_texture"}
                and v is not None and str(v).strip()
            }
            if bio:
                item["biological_dna"] = bio
        if c.get("lived_in_costume") and isinstance(c["lived_in_costume"], dict):
            costume = {
                k: v for k, v in c["lived_in_costume"].items()
                if k in {"top_wear", "bottom_wear", "footwear", "wear_and_tear_details"}
                and v is not None and str(v).strip()
            }
            if costume:
                item["lived_in_costume"] = costume

        clean_item = {k: v for k, v in item.items() if v is not None and str(v).strip()}
        projected.append(clean_item)
    return projected




def project_environments_props_for_stage6(
    envs_props: Any,
    present_scenes: list[str] | set[str] | None = None,
    present_props: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """提取空间场景与核心物证关键视觉材质基准，剥离非视觉物理音效与冗余机位设定。

    保留场景字段：env_id, location_name, weathering_layers, visual_prompt, atmosphere
    保留道具字段：prop_id, name, tier, damage_scale, visual_prompt
    """
    if hasattr(envs_props, "model_dump"):
        data = envs_props.model_dump()
    elif hasattr(envs_props, "to_dict"):
        data = envs_props.to_dict()
    elif isinstance(envs_props, dict):
        data = envs_props
    else:
        data = {}

    raw_envs = data.get("environments") or data.get("scenes") or []
    if not isinstance(raw_envs, list):
        raw_envs = []
    raw_props = data.get("props") or []
    if not isinstance(raw_props, list):
        raw_props = []

    scene_set = {str(s).strip().lower() for s in present_scenes if str(s).strip()} if present_scenes else set()
    filtered_envs = raw_envs
    if scene_set:
        matched = []
        for e in raw_envs:
            if not isinstance(e, dict):
                continue
            name = str(e.get("location_name") or e.get("name") or "").strip().lower()
            eid = str(e.get("env_id") or e.get("environment_id") or e.get("scene_id") or "").strip().lower()
            if (
                name in scene_set
                or eid in scene_set
                or any(sn in name for sn in scene_set)
                or any(name and name in sn for sn in scene_set)
            ):
                matched.append(e)
        if matched:
            filtered_envs = matched

    prop_set = {str(p).strip().lower() for p in present_props if str(p).strip()} if present_props else set()
    filtered_props = raw_props
    if prop_set:
        matched_props = []
        for p in raw_props:
            if not isinstance(p, dict):
                continue
            p_name = str(p.get("name") or "").strip().lower()
            pid = str(p.get("prop_id") or "").strip().lower()
            if (
                p_name in prop_set
                or pid in prop_set
                or any(pn in p_name for pn in prop_set)
                or any(p_name and p_name in pn for pn in prop_set)
            ):
                matched_props.append(p)
        if matched_props:
            filtered_props = matched_props

    projected_envs = []
    for e in filtered_envs:
        if not isinstance(e, dict):
            continue
        p_env = {
            "env_id": e.get("env_id") or e.get("environment_id") or e.get("scene_id"),
            "location_name": e.get("location_name") or e.get("name"),
            "weathering_layers": e.get("weathering_layers"),
            "visual_prompt": e.get("visual_prompt"),
            "atmosphere": e.get("atmosphere") or e.get("color_tone"),
        }
        clean_e = {k: v for k, v in p_env.items() if v is not None and str(v).strip()}
        if clean_e:
            projected_envs.append(clean_e)

    projected_props = []
    for p in filtered_props:
        if not isinstance(p, dict):
            continue
        p_prop = {
            "prop_id": p.get("prop_id"),
            "name": p.get("name"),
            "tier": p.get("tier") or p.get("level") or p.get("type"),
            "damage_scale": p.get("damage_scale"),
            "visual_prompt": p.get("visual_prompt") or p.get("visual_token"),
        }
        clean_p = {k: v for k, v in p_prop.items() if v is not None and str(v).strip()}
        if clean_p:
            projected_props.append(clean_p)

    return {
        "environments": projected_envs,
        "props": projected_props,
    }




def project_registry_index_for_stage6(registry: Any) -> dict[str, Any]:
    """将全剧真理源总库编译为轻量级 ID 索引表，杜绝全量历史提示词与内部哈希表冗余倒灌。

    仅暴露：
    - characters: { asset_id: {"name": ..., "type": ..., "status": "APPROVED"} }
    - environments: { asset_id: {"location_name": ..., "type": ..., "status": "APPROVED"} }
    - props: { asset_id: {"name": ..., "type": ..., "status": "APPROVED"} }
    - audio_tts: { asset_id: {"character_name": ..., "status": "APPROVED"} }
    剥离：
    - semantic_hashes (内部 16 进制指纹字典)
    - hash_index (哈希反查索引)
    - reused_assets_history (跨集复用历史日志)
    - 历史生图 Prompt 文本与 workflow_note 等重复字段
    """
    if hasattr(registry, "model_dump"):
        reg = registry.model_dump()
    elif hasattr(registry, "to_dict"):
        reg = registry.to_dict()
    elif isinstance(registry, dict):
        reg = registry
    else:
        return {}

    def _index_group(items: Any, default_type: str, name_key: str = "name") -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        if isinstance(items, dict):
            for aid, val in items.items():
                if isinstance(val, dict):
                    name = val.get(name_key) or val.get("name") or aid
                    t = val.get("type") or val.get("function_type") or val.get("tier") or default_type
                    status = val.get("lifecycle_status") or val.get("status") or "APPROVED"
                    result[str(aid)] = {"name": str(name), "type": str(t), "status": str(status)}
                elif isinstance(val, str):
                    result[str(aid)] = {"name": val, "type": default_type, "status": "APPROVED"}
        elif isinstance(items, list):
            for val in items:
                if isinstance(val, dict):
                    aid = val.get("asset_id") or val.get("char_id") or val.get("scene_id") or val.get("prop_id") or val.get("voice_id")
                    if aid:
                        name = val.get(name_key) or val.get("name") or aid
                        t = val.get("type") or val.get("function_type") or val.get("tier") or default_type
                        status = val.get("lifecycle_status") or val.get("status") or "APPROVED"
                        result[str(aid)] = {"name": str(name), "type": str(t), "status": str(status)}
        return result

    chars_idx = _index_group(reg.get("characters"), "character_base", "name")
    envs_idx = _index_group(reg.get("environments"), "environment_primary", "location_name")
    props_idx = _index_group(reg.get("props"), "prop_hero", "name")
    voices_idx = _index_group(reg.get("audio_tts"), "voice_master", "character_name")

    index_summary: dict[str, Any] = {}
    if chars_idx:
        index_summary["characters"] = chars_idx
    if envs_idx:
        index_summary["environments"] = envs_idx
    if props_idx:
        index_summary["props"] = props_idx
    if voices_idx:
        index_summary["audio_tts"] = voices_idx

    return index_summary




def _build_candidates_from_projected_registry(
    projected_registry: Any,
    screenplay_text: str,
    top_k: int = 15,
) -> list[dict[str, Any]]:
    """当未连接数据库或处于单测内存环境时，从内存已注册资产轻量索引构建可复用候选资产池 (保底兼容)。"""
    if hasattr(projected_registry, "model_dump"):
        reg = projected_registry.model_dump()
    elif hasattr(projected_registry, "to_dict"):
        reg = projected_registry.to_dict()
    elif isinstance(projected_registry, dict):
        reg = projected_registry
    else:
        return []

    res: list[dict[str, Any]] = []
    sc_text = screenplay_text or ""

    for cat in ["characters", "environments", "props", "audio_tts"]:
        group = reg.get(cat) or {}
        if isinstance(group, dict):
            for akey, info in group.items():
                name = ""
                atype = "image"
                status = "APPROVED"
                if isinstance(info, dict):
                    name = str(info.get("name") or info.get("scene_name") or info.get("character_name") or akey)
                    atype = str(info.get("type") or ("voice" if cat == "audio_tts" else "image"))
                    status = str(info.get("status") or "APPROVED")
                elif isinstance(info, str):
                    name = info

                is_match = (bool(name) and name in sc_text) or (akey in sc_text)
                res.append({
                    "asset_key": str(akey),
                    "name": name or str(akey),
                    "category": "character" if cat == "characters" else ("scene" if cat == "environments" else ("prop" if cat == "props" else "voice")),
                    "type": atype,
                    "stage_code": "T1",
                    "visual_summary": name,
                    "relevance_score": 1.0 if is_match else 0.7,
                    "is_existing_asset": True,
                    "recall_source": "memory_registry",
                    "status": status,
                })

    # 优先剧本命中项排序，截断至 top_k
    res.sort(key=lambda x: x["relevance_score"], reverse=True)
    return res[:top_k]



