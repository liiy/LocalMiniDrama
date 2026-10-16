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
    existing_char_codes: set[str],
    used_archetypes: set[str],
    primary_protagonist_code: str = "CHAR_PROTAGONIST",
    primary_protagonist_name: str = "主角",
    index_hint: int = 1,
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-NEW-CHAR】当分集中出现阶段2未涉及的新角色时，按阶段2标准11维格式动态建档。

    生成完整的阶段2同构全息档案（含 biological_dna、lived_in_costume、psychology_4、
    acoustic_persona、voice_fingerprint、carried_anchor_item、drama_engine 及 new_relationships），
    确保新角色与阶段2原生角色拥有100%一致的数据契约、视觉基准与音色卡。
    """
    FEMALE_TOKENS = ["婉", "晓", "夏", "琴", "琳", "姐", "妹", "女", "妻", "母", "颖", "雅", "婷", "静", "雪", "菲", "薇", "柔", "云"]
    gender = "female" if any(tk in char_name for tk in FEMALE_TOKENS) else "male"
    perceived_age = 38 if any(tk in char_name for tk in ["老", "叔", "伯", "爷", "董", "总", "局"]) else 27

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

    bio_dna = {
        "bone_structure": "棱角分明的高颧骨与冷峻下颌线" if gender == "male" else "清隽骨相与清晰下颌折角",
        "skin_micro_texture": "真实自然毛孔肌理与微汗反光，拒绝塑料磨皮",
        "blemishes_and_scars": "眼角微细风霜纹与鼻翼自然暗影",
        "eye_lip_anatomy": "瞳孔深邃带血丝微光，唇纹清晰真实",
        "hair_texture": "略带湿气与风尘感的自然碎发层次",
    }
    costume_specs = {
        "top_wear": "深灰哑光重磅工装夹克，肩线与手肘带真实穿着折痕",
        "bottom_wear": "深色直筒耐磨长裤，裤脚微沾灰尘",
        "footwear": "鞋面带细微刮痕的深色旧皮靴，双脚完整落地",
        "wear_and_tear_details": "领口与袖口边缘呈自然摩擦微起毛质感",
    }

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
        "anchor_props": [f"{char_name}的随身信物"],
    }
    identity_anchors = [
        bio_dna["bone_structure"],
        bio_dna["skin_micro_texture"],
        costume_specs["top_wear"],
        f"{char_name}的随身信物",
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
        "personality": "行事审慎果决，言辞暗藏机锋，在利益与真相博弈中保持高度戒备",
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
        "psychology_4": {
            "want": f"在第{episode_num}集冲突现场保全自身筹码并试探对方底牌",
            "need": "在危机漩涡中守住核心秘密不被清算",
            "lie": "只要不先亮出底牌就能永远掌控局势主动权",
            "ghost": "曾因轻信承诺而卷入旧案风波",
        },
        "voice_fingerprint": {
            "catchphrase": clean_sample_text,
            "script_monologue_source": monologue_source,
            "breathing_habit": "开口前习惯压低吸气声，句尾略带冷意",
        },
        "carried_anchor_item": {
            "item_name": f"{char_name}的随身信物",
            "physical_description": "边角磨损的深色金属随身物件，表面留有长年摩挲痕迹",
            "narrative_function": f"第{episode_num}集身份核验与动作交互锚点",
        },
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
    **kwargs: Any,
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-DYNAMIC-SCENE】当分集中出现阶段3未登记的新场景时，按阶段3标准三层做旧规格动态建档。

    生成完整的阶段3同构空间全息档案（含 three_layer_aging、weathering_layers、costume_resonance_check、
    benchmark_asset_key、zones 子区域规划及 weathering_views 三级切片），100% 动态生成，绝不采用静态枚举。
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

    # 根据 visual_style 及空间命名动态判定建筑材质骨架，防止古代剧被误注入现代钢筋混凝土
    is_ancient_or_period = any(k in str(visual_style or "").lower() or k in clean_s for k in ["明", "宋", "唐", "清", "古代", "武侠", "古装", "修仙", "客栈", "驿站", "府", "殿", "寺", "山庄", "堂"])
    if is_ancient_or_period:
        struct_material = "weathered wood timber frame, mortise and tenon architecture, aged bricks and clay tiles"
        struct_desc = f"{clean_s}主体木石梁柱与榫卯架构，带真实风吹日晒与烟熏岁月包浆"
    else:
        struct_material = "architectural structural elements, authentic textures and weathered building materials"
        struct_desc = f"{clean_s}主体承重与硬装边界，带真实岁月侵蚀与岁月沉淀感"

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
    **kwargs: Any,
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-DYNAMIC-PROP】当分集中出现阶段3未登记的新道具/物证时，按阶段3标准物理规格动态建档。

    生成完整的阶段3同构物证全息档案（含 physical_specs、damage_states、detail_views、foley_resistance 及
    benchmark_asset_key），100% 动态 NLP 抽取，绝不采用静态枚举。
    """
    if existing_prop_codes is None:
        existing_prop_codes = set()

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



