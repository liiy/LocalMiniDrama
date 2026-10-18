"""阶段 6 增量实体全息档案构建器 (Stage 6 Dossier Builders)。

遵循阶段 2/3 标准数据规格，为分集剧本中新发掘的角色、空间场景与关键物证动态合成全息档案。
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from app.tools.screenplay_feature_scanner import (
    DEFORMATION_VERBS,
    PINYIN_LOOKUP,
    ScreenplayScanResult,
    _slugify_chinese,
)
from app.workflows.nodes.stage6.genre_packs import BaseGenrePack, get_genre_pack
from app.workflows.nodes.stage6.voice_rules import (
    _build_default_emotion_rules,
    _select_voice_archetype,
    _strip_dialogue_brackets,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

logger = logging.getLogger("lmd.stage6.dossier_builders")


def _build_stage2_character_dossier(
    char_name: str,
    episode_num: int,
    screenplay_text: str,
    existing_char_codes: set[str] | None = None,
    used_archetypes: set[str] | None = None,
    primary_protagonist_code: str = "CHAR_PROTAGONIST",
    primary_protagonist_name: str = "主角",
    index_hint: int = 1,
    genre_pack: BaseGenrePack | None = None,
    drama_genre: str = "",
    visual_style: str = "",
    gender: str | None = None,
    perceived_age: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-NEW-CHAR】当分集中出现阶段2未涉及的新角色时，按阶段2标准11维格式动态建档。

    详细说明：
        【重要执行边界】：本方法 100% 专用于阶段 2 顶层尚未建档、在当集剧本中全新登场的分集新角色。
        阶段 2 已登记的已知角色在进入建档循环前即被上游白名单完全过滤，不经过本方法。
        
        为新角色生成完整的阶段 2 同构全息档案（含 biological_dna、lived_in_costume、psychology_4、
        acoustic_persona、voice_fingerprint、carried_anchor_item、drama_engine 及 new_relationships），
        采用【三级渐进式性别与年龄推断架构】彻底消除静态硬编码：
          - 第 1 级（主通道 · 0 额外网络开销）：大模型在单次阶段 6 提示词抽取中显式返回的 gender 与 perceived_age；
          - 第 2 级（剧本上下文代词反查）：从剧本文本角色前后文中通过第三人称代词（'她' vs '他'）正则快速消歧；
          - 第 3 级（题材预设包动态兜底）：委托给当前剧目对应的 GenrePack 自适应兜底。

    Args:
        char_name (str): 新角色中文名（如 '周老四', '苏仙子'）。
        episode_num (int): 当前分集集数。
        screenplay_text (str): 分集剧本正文。
        existing_char_codes (set[str] | None): 已分配角色代号集合，用于唯一标识碰撞检测。若为 None 则自动初始化空集。
        used_archetypes (set[str] | None): 已占用音色原型标识集合，用于音色指纹去重。若为 None 则自动初始化空集。
        primary_protagonist_code (str): 本剧第一主角代号，用于构建初始人际关系矩阵。
        primary_protagonist_name (str): 本剧第一主角姓名。
        index_hint (int): 索引序号提示，用于保证角色出场排序稳定性。
        genre_pack (BaseGenrePack | None): 题材预设包实例 (若为 None 则自适应探测)。
        drama_genre (str): 剧目题材类型描述（如 '现代悬疑/犯罪', '古装玄幻/仙侠'）。
        visual_style (str): 视觉基准风格描述。
        gender (str | None): 显式传入的角色性别（"male"|"female"），若提供则优先采纳。
        perceived_age (int | None): 显式传入的角色视听生理年龄（如 28, 45），若提供则优先采纳。

    Returns:
        dict[str, Any]: 阶段 2 标准 11 维全息角色档案字典。
    """
    if existing_char_codes is None:
        existing_char_codes = set()
    if used_archetypes is None:
        used_archetypes = set()

    if genre_pack is None:
        genre_pack = get_genre_pack(
            drama_genre=drama_genre or kwargs.get("genre", ""),
            visual_style=visual_style,
            screenplay_text=screenplay_text,
        )

    # =========================================================================
    # 三级渐进式性别与年龄推断架构 (3-Tier Gender & Age Resolution Pipeline)
    # =========================================================================
    raw_g = str(gender or kwargs.get("gender") or kwargs.get("explicit_gender") or "").strip().lower()
    raw_a = perceived_age if perceived_age is not None else (kwargs.get("perceived_age") if kwargs.get("perceived_age") is not None else kwargs.get("explicit_age"))

    final_gender: str = raw_g if raw_g in ("male", "female") else ""
    final_age: int | None = None
    if isinstance(raw_a, (int, float)) and 1 <= int(raw_a) <= 120:
        final_age = int(raw_a)

    resolution_tier = "unknown"
    if final_gender and final_age:
        # 第 1 级完全命中：LLM 单次提取已完备给出性别与年龄
        resolution_tier = "Tier-1 (LLM Explicit Contract)"
        logger.debug(
            "【阶段 6 新角色属性建档】角色 [%s] 命中 %s: gender=%s, age=%d",
            char_name, resolution_tier, final_gender, final_age,
        )
    else:
        # 截取角色在剧本文本中的上下文窗口（前后 100 字符），用于代词反查与题材包消歧
        char_ctx_snippets: list[str] = []
        if screenplay_text and char_name in screenplay_text:
            for match in re.finditer(re.escape(char_name), screenplay_text):
                start_idx = max(0, match.start() - 100)
                end_idx = min(len(screenplay_text), match.end() + 100)
                char_ctx_snippets.append(screenplay_text[start_idx:end_idx])
        char_context_text = "\n".join(char_ctx_snippets[:5])

        # 第 2 级：从上下文文本中反查代词
        inferred_gender_t2 = ""
        if not final_gender and char_context_text:
            she_cnt = char_context_text.count("她")
            he_cnt = char_context_text.count("他")
            if she_cnt > he_cnt:
                inferred_gender_t2 = "female"
            elif he_cnt > she_cnt:
                inferred_gender_t2 = "male"

        # 第 3 级：题材预设包动态推断兜底
        pack_gender, pack_age = genre_pack.infer_character_gender_and_age(
            char_name=char_name,
            screenplay_context=char_context_text,
        )

        if not final_gender:
            if inferred_gender_t2:
                final_gender = inferred_gender_t2
                resolution_tier = "Tier-2 (Screenplay Context Pronoun Regex)"
            else:
                final_gender = pack_gender
                resolution_tier = "Tier-3 (GenrePack Dynamic Fallback)"
        else:
            resolution_tier = "Tier-1 (Partial LLM Gender)"

        if final_age is None:
            final_age = pack_age

        logger.debug(
            "【阶段 6 新角色属性建档完成】角色 [%s] 经 %s 判定: gender=%s, age=%d",
            char_name, resolution_tier, final_gender, final_age,
        )

    # 规范化命名引用于下游逻辑
    gender = final_gender
    perceived_age = final_age

    slug = PINYIN_LOOKUP.get(char_name)
    if not slug:
        # 优先使用动态拼音转换生成可读大写英文 Token，杜绝中文残留与无意义哈希回退
        slug = _slugify_chinese(char_name)
        if not slug or slug == "UNKNOWN":
            digest = hashlib.md5(char_name.encode("utf-8")).hexdigest()[:6].upper()
            slug = f"EP{episode_num}C{digest}"
        logger.debug("【阶段 6 新角色动态编码】角色 '%s' 生成规范英文 Token: [%s]", char_name, slug)

    char_code = f"CHAR_{slug}"
    suffix_idx = 2
    while char_code in existing_char_codes:
        char_code = f"CHAR_{slug}{suffix_idx}"
        suffix_idx += 1
    existing_char_codes.add(char_code)

    tok = char_code.replace("CHAR_", "")
    portrait_key = f"CHAR_{tok}_T1_BASE_PORTRAIT"

    # 从剧本文本抓取该角色的首句原声对白与上下文动作
    sample_raw_dialogue = ""
    sample_bracket = ""
    dlg_pattern = re.compile(
        rf"^{re.escape(char_name)}\s*(?:[（(]([^）)]*)[）)])?\s*[：:]\s*(?:[（(]([^）)]*)[）)])?\s*[“\"]?([^”\"\n]+)[”\"]?",
        re.MULTILINE,
    )
    m = dlg_pattern.search(screenplay_text or "")
    if m:
        sample_bracket = (m.group(1) or m.group(2) or "").strip()
        sample_raw_dialogue = (m.group(3) or "").strip()

    clean_sample_text = _strip_dialogue_brackets(sample_raw_dialogue, char_name)
    monologue_source = (
        f"（{sample_bracket or '目光审视，压低声线'}）{sample_raw_dialogue}"
        if sample_raw_dialogue
        else f"（眼神警觉，指节微扣）{clean_sample_text}"
    )

    voice_arch = _select_voice_archetype(
        {"name": char_name, "gender": gender},
        used_archetypes=used_archetypes,
        index_hint=index_hint,
    )

    # 动态通过题材预设包自适应构建生理特征、服装规范、信物与心理四维
    bio_dna = genre_pack.get_character_bio(char_name, gender, perceived_age)
    costume_specs = genre_pack.get_character_costume(char_name, gender, perceived_age)
    carried_anchor_item = genre_pack.get_character_anchor_item(char_name, episode_num)
    psychology_4 = genre_pack.get_character_psychology(char_name, episode_num)
    personality = genre_pack.get_character_personality(char_name)

    anchor_name = carried_anchor_item.get("item_name") or f"{char_name}的随身信物"

    appearance_text = (
        f"{perceived_age}岁{'女性' if gender == 'female' else '男性'}，"
        f"{bio_dna['bone_structure']}，{bio_dna['skin_micro_texture']}；"
        f"身穿{costume_specs['top_wear']}，搭配{costume_specs['bottom_wear']}与{costume_specs['footwear']}"
    )
    visual_consistency_code = {
        "facial_signature": bio_dna["bone_structure"],
        "facial_bone_structure": bio_dna["bone_structure"],
        "skin_and_texture": bio_dna["skin_micro_texture"],
        "skin_texture": bio_dna["skin_micro_texture"],
        "signature_marks": bio_dna["blemishes_and_scars"],
        "signature_feature": bio_dna["blemishes_and_scars"],
        "hair": bio_dna["hair_texture"],
        "costume_wear_code": f"{costume_specs['top_wear']}，{costume_specs['bottom_wear']}，{costume_specs['footwear']}",
        "stage_a_clothing": f"{costume_specs['top_wear']}，{costume_specs['bottom_wear']}",
        "anchor_props": [anchor_name],
    }
    identity_anchors = [
        bio_dna["bone_structure"],
        bio_dna["skin_micro_texture"],
        costume_specs["top_wear"],
        anchor_name,
    ]

    dossier: dict[str, Any] = {
        "character_id": char_code,
        "character_code": char_code,
        "name": char_name,
        "gender": gender,
        "perceived_age": perceived_age,
        "role": "supporting",
        "role_type": "supporter",
        "first_appearance_episode": episode_num,
        "discovered_in_stage": 6,
        "benchmark_asset_key": portrait_key,
        "description": f"第{episode_num}集新登场关键互动角色【{char_name}】，掌握局部剧情关键线索或推动当集冲突升级。",
        "personality": personality,
        "appearance": appearance_text,
        "identity_anchors": identity_anchors,
        "visual_consistency_code": visual_consistency_code,
        "biological_dna": bio_dna,
        "lived_in_costume": costume_specs,
        "voice_style": f"{voice_arch['timbre']}，{voice_arch['vocal_position']}",
        "timbre": voice_arch["timbre"],
        "timbre_archetype": voice_arch["timbre_archetype"],
        "speed_ratio": voice_arch["speed_ratio"],
        "pitch_ratio": voice_arch["pitch_ratio"],
        "provider_voice_id": voice_arch["provider_voice_id"],
        "timber_weights": voice_arch["timber_weights"],
        "emotion_rules": _build_default_emotion_rules(),
        "acoustic_persona": {
            "vocal_position": voice_arch["vocal_position"],
            "vocal_flaws": voice_arch["vocal_flaws"],
            "pitch_range": "中低频稳定叙事音区",
            "speech_rhythm": "短句顿挫有力，关键处刻意停顿半拍",
            "tone": voice_arch["timbre"],
            "subtext_pattern": "话留三分，习惯以反问或动作暗示真实意图",
        },
        "psychology_4": psychology_4,
        "voice_fingerprint": {
            "catchphrase": clean_sample_text,
            "script_monologue_source": monologue_source,
            "breathing_habit": "开口前习惯压低吸气声，句尾略带冷意",
        },
        "carried_anchor_item": carried_anchor_item,
        "drama_engine": {
            "core_conflict_role": f"第{episode_num}集局部冲突催化剂与关键证词/阻力提供者",
            "information_gap": {
                "knows_truth_initially": False,
                "current_belief": "以为现场各方仍在按旧规则博弈",
                "reveal_condition": "核心物证当场亮出或利害关系破裂时吐露实情",
            },
            "swing_point": {
                "can_defect": True,
                "defect_condition": "当自身安全或核心筹码受到直接威胁时立场松动",
            },
        },
        "new_relationships": [
            {
                "source_code": char_code,
                "source_name": char_name,
                "target_code": primary_protagonist_code,
                "target_name": primary_protagonist_name,
                "relation_type": "试探对峙/线索交锋",
                "tension_level": 78,
                "summary": f"第{episode_num}集【{char_name}】与【{primary_protagonist_name}】正面对峙或产生关键线索交集",
            }
        ],
    }
    logger.debug(
        "【阶段 6 新角色动态建档】成功按照阶段 2 标准 11 维规格构建新角色 [%s (%s)]: 音色原型=%s, 试音词='%s'",
        char_name, char_code, voice_arch["timbre_archetype"], clean_sample_text,
    )
    return dossier




def _build_stage3_scene_dossier(
    scene_name: str,
    episode_num: int = 1,
    existing_scene_codes: set[str] | None = None,
    scanner_result: ScreenplayScanResult | None = None,
    visual_style: str = "",
    screenplay_text: str = "",
    index_hint: int = 1,
    detected_zones: list[str] | None = None,
    genre_pack: BaseGenrePack | None = None,
    drama_genre: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-DYNAMIC-SCENE】当分集中出现阶段3未登记的新场景时，按阶段3标准三层做旧规格动态建档。

    生成完整的阶段3同构空间全息档案（含 three_layer_aging、weathering_layers、costume_resonance_check、
    benchmark_asset_key、zones 子区域规划及 weathering_views 三级切片），支持多题材自适应注入。
    """
    if existing_scene_codes is None:
        existing_scene_codes = set()

    clean_s = str(scene_name or "").strip()
    slug = PINYIN_LOOKUP.get(clean_s)
    if not slug:
        slug = _slugify_chinese(clean_s)
        if not slug or slug == "UNKNOWN":
            digest = hashlib.md5(clean_s.encode("utf-8")).hexdigest()[:6].upper()
            slug = f"EP{episode_num}S{digest}"
        logger.debug("【阶段 6 新场景动态编码】场景 '%s' 生成规范英文 Token: [%s]", clean_s, slug)

    scene_code = f"ENV_{slug}"
    suffix_idx = 2
    while scene_code in existing_scene_codes:
        scene_code = f"ENV_{slug}{suffix_idx}"
        suffix_idx += 1
    existing_scene_codes.add(scene_code)

    tok = scene_code.replace("ENV_", "")
    benchmark_key = f"ENV_{tok}_Z01_WIDE"

    # 从扫描结果或显式传入中获取识别出的子区域，若无则动态生成核心主活动区
    actual_detected_zones: list[str] = []
    if detected_zones:
        actual_detected_zones = list(detected_zones)
    elif scanner_result and isinstance(getattr(scanner_result, "scene_zones_detected", None), dict):
        actual_detected_zones = list(scanner_result.scene_zones_detected.get(clean_s) or [])

    zones_list: list[dict[str, Any]] = []
    if actual_detected_zones:
        for z_idx, z_name in enumerate(actual_detected_zones, start=1):
            z_code = f"Z{z_idx:02d}"
            zones_list.append({
                "zone_code": z_code,
                "zone_name": z_name,
                "time_lighting": kwargs.get("time_lighting") or "光影对比鲜明，空间明暗交界清晰",
                "acoustic_resistance": "封闭空间混响与微弱空气底噪",
                "parent_zone_id": None if z_idx == 1 else "Z01",
            })
    else:
        zones_list.append({
            "zone_code": "Z01",
            "zone_name": f"{clean_s}主活动区",
            "time_lighting": kwargs.get("time_lighting") or "剧情主氛围光效，明暗层次丰富",
            "acoustic_resistance": "标准空间混响与空气底噪",
            "parent_zone_id": None,
        })

    # 通过题材预设包自适应判定建筑材质骨架，防止古代剧被误注入现代钢筋混凝土，科幻剧缺少未来合金
    if genre_pack is None:
        genre_pack = get_genre_pack(
            drama_genre=drama_genre or kwargs.get("genre", ""),
            visual_style=visual_style,
            screenplay_text=screenplay_text,
        )
    struct_material, struct_desc = genre_pack.get_scene_weathering_elements(clean_s)

    lived_grime = f"{clean_s}高频活动痕迹，地面与台面有自然灰尘与生活水渍污斑，与角色磨损同频"
    light_air = f"{clean_s}空间介质漫反射光，微小悬浮颗粒在侧逆光下形成丁达尔光束"

    weathering_views: list[dict[str, Any]] = [
        {
            "layer_type": "structural",
            "asset_key": f"{scene_code}_Z01_L1_STRUCT",
            "parent_asset_key": benchmark_key,
            "generation_mode": "i2i",
            "denoise_strength": 0.35,
            "description": struct_desc,
            "image_prompt": f"{clean_s}, structural architecture, {struct_material}, realistic patina, 8k raw photo",
            "is_benchmark": 0,
        },
        {
            "layer_type": "living",
            "asset_key": f"{scene_code}_Z01_L2_LIVING",
            "parent_asset_key": benchmark_key,
            "generation_mode": "i2i",
            "denoise_strength": 0.38,
            "description": lived_grime,
            "image_prompt": f"{clean_s}, high traffic wear, grime, lived-in stains, realistic patina, 8k raw photo",
            "is_benchmark": 0,
        },
        {
            "layer_type": "optical",
            "asset_key": f"{scene_code}_Z01_L3_OPTICAL",
            "parent_asset_key": benchmark_key,
            "generation_mode": "i2i",
            "denoise_strength": 0.30,
            "description": light_air,
            "image_prompt": f"{clean_s}, volumetric light beams, airborne dust particles, atmospheric haze, 8k raw photo",
            "is_benchmark": 0,
        },
    ]

    dossier: dict[str, Any] = {
        "env_id": scene_code,
        "scene_id": scene_code,
        "scene_code": scene_code,
        "name": clean_s,
        "location_name": clean_s,
        "level": "primary_tier1",
        "first_appearance_episode": episode_num,
        "discovered_in_stage": 6,
        "benchmark_asset_key": benchmark_key,
        "costume_resonance_check": True,
        "description": f"第{episode_num}集新登场关键叙事空间【{clean_s}】，承载当集核心冲突或情节点转折。",
        "time_and_lighting": kwargs.get("time_lighting") or "光影对比鲜明，层次丰富",
        "visual_prompt": f"cinematic moody interior/exterior, {clean_s}, volumetric light, realistic weathering, 8k raw photo",
        "three_layer_aging": {
            "structure": struct_desc,
            "lived_grime": lived_grime,
            "light_and_air": light_air,
        },
        "weathering_layers": {
            "structural": struct_desc,
            "living": lived_grime,
            "optical": light_air,
        },
        "zones": zones_list,
        "weathering_views": weathering_views,
        "atmosphere": "戏剧冲突紧绷，真实生活粗粝质感",
    }
    logger.debug(
        "【阶段 6 新场景动态建档】成功构建场景 [%s (%s)]: 基准底模=%s, 规划子区域数=%d, 风化切片数=%d",
        clean_s, scene_code, benchmark_key, len(zones_list), len(weathering_views),
    )
    return dossier




def _build_stage3_prop_dossier(
    prop_name: str,
    episode_num: int = 1,
    existing_prop_codes: set[str] | None = None,
    scanner_result: ScreenplayScanResult | None = None,
    visual_style: str = "",
    screenplay_text: str = "",
    index_hint: int = 1,
    deformed_verbs: list[str] | None = None,
    genre_pack: BaseGenrePack | None = None,
    drama_genre: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-DYNAMIC-PROP】当分集中出现阶段3未登记的新道具/物证时，按阶段3标准物理规格动态建档。

    生成完整的阶段3同构物证全息档案（含 physical_specs、damage_states、detail_views、foley_resistance 及
    benchmark_asset_key），支持多题材自适应注入。
    """
    if existing_prop_codes is None:
        existing_prop_codes = set()

    if genre_pack is None:
        genre_pack = get_genre_pack(
            drama_genre=drama_genre or kwargs.get("genre", ""),
            visual_style=visual_style,
            screenplay_text=screenplay_text,
        )

    clean_p = str(prop_name or "").strip()
    slug = PINYIN_LOOKUP.get(clean_p)
    if not slug:
        slug = _slugify_chinese(clean_p)
        if not slug or slug == "UNKNOWN":
            digest = hashlib.md5(clean_p.encode("utf-8")).hexdigest()[:6].upper()
            slug = f"EP{episode_num}P{digest}"
        logger.debug("【阶段 6 新道具动态编码】道具 '%s' 生成规范英文 Token: [%s]", clean_p, slug)

    prop_code = f"PROP_{slug}"
    suffix_idx = 2
    while prop_code in existing_prop_codes:
        prop_code = f"PROP_{slug}{suffix_idx}"
        suffix_idx += 1
    existing_prop_codes.add(prop_code)

    tok = prop_code.replace("PROP_", "")
    benchmark_key = f"PROP_{tok}_S0_STATIC"

    # 检测是否有破坏形变动词
    actual_deformed_verbs: list[str] = []
    if deformed_verbs:
        actual_deformed_verbs = list(deformed_verbs)
    elif scanner_result and isinstance(getattr(scanner_result, "deformed_props", None), dict):
        actual_deformed_verbs = list(scanner_result.deformed_props.get(clean_p) or [])

    damage_states: list[dict[str, Any]] = [
        {
            "state_code": f"{prop_code}_S0",
            "state_label": f"{clean_p}初始完好态",
            "damage_level": 0,
            "parent_state_id": None,
            "narrative_point": f"第{episode_num}集初始物证基准状态（微观自然磨损与氧化层）",
            "visual_prompt": f"cinematic macro close up of {clean_p}, resting on a solid surface with natural light, realistic material texture, pristine with subtle surface micro-scratches, authentic patina",
            "is_benchmark": 1,
        }
    ]
    if actual_deformed_verbs:
        v_str = "/".join(actual_deformed_verbs)
        damage_states.append({
            "state_code": f"{prop_code}_S1",
            "state_label": f"{clean_p}破坏交互态({v_str})",
            "damage_level": 2,
            "parent_state_id": f"{prop_code}_S0",
            "narrative_point": f"第{episode_num}集剧情动作触发形变破坏（命中动词：{v_str}）",
            "visual_prompt": f"cinematic macro close up of damaged {clean_p}, {v_str}, resting on textured surface with tactile debris fragments, severe fracture and deformation, realistic drama lighting",
            "is_benchmark": 0,
        })

    detail_views: list[dict[str, Any]] = [
        {
            "view_type": "macro_detail",
            "view_label": f"{clean_p}表面微距特写",
            "asset_key": f"{prop_code}_S0_DETAIL",
            "parent_asset_key": benchmark_key,
            "generation_mode": "t2i",
            "denoise_strength": 0.0,
            "image_prompt": f"extreme macro close up of {clean_p}, pristine texture, sharp focus, 8k",
            "is_benchmark": 1,
            "is_primary": 1,
        },
        {
            "view_type": "surface_texture",
            "view_label": f"{clean_p}材质包浆特写",
            "asset_key": f"{prop_code}_S0_TEXTURE",
            "parent_asset_key": benchmark_key,
            "generation_mode": "i2i",
            "denoise_strength": 0.35,
            "image_prompt": f"tactile surface texture of {clean_p}, lived-in patina, micro scratches, 8k",
            "is_benchmark": 0,
            "is_primary": 0,
        },
    ]
    if actual_deformed_verbs:
        v_str = "/".join(actual_deformed_verbs)
        detail_views.append({
            "view_type": "destruction_closeup",
            "view_label": f"{clean_p}破坏断面特写",
            "asset_key": f"{prop_code}_S1_ACTION",
            "parent_asset_key": benchmark_key,
            "generation_mode": "inpaint",
            "denoise_strength": 0.45,
            "image_prompt": f"extreme macro close up of broken damaged {clean_p}, {v_str}, shattered fracture, 8k",
            "is_benchmark": 0,
            "is_primary": 1,
        })

    damage_dim = f"{clean_p}边缘与接触面有微观自然划痕与氧化包浆"
    foley_resistance = f"+3.0dB {clean_p}接触与操作时物理摩擦阻尼拟音"

    dossier: dict[str, Any] = {
        "prop_id": prop_code,
        "prop_code": prop_code,
        "name": clean_p,
        "prop_name": clean_p,
        "level": "hero_tier1",
        "type": "narrative_reversal",
        "first_appearance_episode": episode_num,
        "discovered_in_stage": 6,
        "benchmark_asset_key": benchmark_key,
        "description": f"第{episode_num}集新登场关键剧情物证【{clean_p}】，推动核心叙事悬念或动作交互。",
        "visual_prompt": f"macro close up of {clean_p}, dramatic rim lighting, tactile surface detail, ultra photorealistic 8k",
        "physical_specs": {
            "material_damage_dimensions": damage_dim,
            "weight_and_haptic_resistance": "握持质感扎实，具备明显阻尼物理回馈",
            "foley_boost_db": "+3.0dB",
        },
        "damage_scale": damage_dim,
        "foley_resistance": foley_resistance,
        "damage_states": damage_states,
        "detail_views": detail_views,
    }
    logger.debug(
        "【阶段 6 新道具动态建档】成功构建道具 [%s (%s)]: 基准底模=%s, 破坏形态分支数=%d, 微距切片数=%d",
        clean_p, prop_code, benchmark_key, len(damage_states), len(detail_views),
    )
    return dossier



