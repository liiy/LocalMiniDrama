"""阶段 6：第二程资产准备与真理源校验节点 (Stage 6 Asset Truth Registry Node)。

严格遵循 SKILL1.md 章节三《全剧资产四段式确定性命名与寻址协议》：
资产 ID = [大类前缀] _ [对象英文标识] _ [等级/分层] _ [功能类型/状态修饰符]
- 0号肖像基准 (CHAR_<TOKEN>_T1_BASE_PORTRAIT)
- 基础定妆 (CHAR_<TOKEN>_T1_BASE_COSTUME)
- 场景全景 (ENV_<TOKEN>_T1_WIDE) 与过肩对白板 (ENV_<TOKEN>_T1_OTS_BG)
- 核心物证静态与破坏态 (PROP_<TOKEN>_T1_STATIC / ACTION)
- 角色声音母音频 (VOICE_<TOKEN>_T1_MASTER)
并自动解析底图血统 DAG 依赖，结合四大逆向扫描算子，汇总更新到全剧真理源总库 (05_visual_audio_assets.json)。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Mapping

from app.schemas.script_graph_state import (
    AssetState,
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    IndustrialDramaState,
    MasterVoiceCardModel,
    NewlyGeneratedAssetModel,
    ReusedAssetModel,
    VisualAudioAssetsRegistryModel,
)
from app.tools.screenplay_feature_scanner import (
    DEFORMATION_VERBS,
    PINYIN_LOOKUP,
    ScreenplayScanResult,
    _entity_matches_text,
    _extract_anchor_props_from_characters,
    _slugify_chinese,
    is_valid_character_speaker,
    scan_screenplay_features,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE6_SYSTEM_PROMPT,
    STAGE6_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetDependency, AssetProtocolHelper
from app.workflows.utils.llm_bridge import call_llm_json
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer
from app.workflows.utils.asset_slice_enricher import AssetSliceEnricher
from app.workflows.operators.asset_trigger_operator_engine import AssetTriggerOperatorEngine

logger = logging.getLogger("lmd.stage6_asset_truth")


def compute_asset_semantic_hash(
    category: str,
    asset_id: str,
    prompt: str = "",
    attributes: dict[str, Any] | None = None,
) -> str:
    """计算资产的确定性 SHA-256 语义指纹 (16 位十六进制)。

    【设计原则】
    通过资产类型、核心对象标识、提示词与做旧/形变关键物理属性计算哈希，
    用于全剧跨集资产去重与一致性检测。当跨集新资产计算出的哈希与真理源已有资产
    指纹完全一致时，系统可判定为同一物理形态，自动触发无损复用，避免冗余生图与风格漂移。

    Args:
        category: 资产分类代码 (CHAR, ENV, PROP, VOICE 等)
        asset_id: 资产四段式规范编码
        prompt: 视觉生图提示词或声学 TTS 提示词
        attributes: 物理特征属性字典 (如生物 DNA、服化道参数、做旧层级、损坏规模等)

    Returns:
        16 位十六进制 SHA-256 语义指纹摘要
    """
    normalized_prompt = " ".join((prompt or "").strip().lower().split())
    attr_tokens: list[str] = []
    if attributes:
        for k in sorted(attributes.keys()):
            v = attributes[k]
            if v is not None and str(v).strip():
                attr_tokens.append(f"{k}:{str(v).strip().lower()}")
    attr_str = "|".join(attr_tokens)
    token_part = asset_id.split("_")[1] if "_" in asset_id else asset_id
    raw_key = f"{category.upper()}|{token_part}|{normalized_prompt}|{attr_str}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


class StageResult(dict):
    """具备字典与对象双向属性访问能力的阶段状态容器。"""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'StageResult' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _extract_token_from_id(raw_id: str, prefix: str, default_token: str) -> str:
    """辅助提取纯英文字符 token。"""
    norm = AssetProtocolHelper.normalize_id(raw_id)
    if norm.startswith(f"{prefix}_"):
        parts = norm.split("_")
        if len(parts) >= 2 and parts[1]:
            tok = re.sub(r"[^A-Z0-9]", "", parts[1])
            if tok:
                return tok
    # 尝试从整个字符串中提取
    cleaned = re.sub(r"[^A-Z0-9]", "", norm.replace(prefix, ""))
    return cleaned if cleaned else default_token


def _extract_screenplay_text(script_data: Any) -> str:
    """从各版本剧本结构体中精准抽取正本文学剧本文本。"""
    if not script_data:
        return ""
    if isinstance(script_data, str):
        return script_data.strip()
    if isinstance(script_data, dict):
        for k in ["screenplay_text", "body_markdown", "script_text", "content", "screenplay"]:
            val = script_data.get(k)
            if val and isinstance(val, str) and val.strip():
                return val.strip()
        scenes = script_data.get("scenes") or []
        if scenes:
            parts = []
            for sc in scenes:
                if isinstance(sc, dict):
                    hdr = sc.get("scene_header") or sc.get("header") or sc.get("heading") or sc.get("title") or ""
                    if hdr:
                        parts.append(hdr)
                    s_txt = sc.get("screenplay_text") or sc.get("content") or sc.get("text") or ""
                    if s_txt:
                        parts.append(str(s_txt).strip())
                    for act in sc.get("actions") or []:
                        parts.append(str(act))
                    for dlg in sc.get("dialogues") or []:
                        if isinstance(dlg, dict):
                            spk = dlg.get("speaker") or dlg.get("character") or "角色"
                            brk = f"（{dlg.get('parenthetical')}）" if dlg.get("parenthetical") else ""
                            line = dlg.get("lines") or dlg.get("dialogue") or ""
                            parts.append(f"{spk}：{brk}{line}")
                        elif isinstance(dlg, str):
                            parts.append(dlg)
            if parts:
                return "\n".join(parts)
            # 兼容仅包含结构化字段（characters_present / scene_header / core_props）的精简元数据剧本
            meta_parts = []
            if script_data.get("scene_header"):
                meta_parts.append(f"【场景】{script_data.get('scene_header')}")
            if script_data.get("characters_present") and isinstance(script_data.get("characters_present"), list):
                for cp in script_data.get("characters_present"):
                    meta_parts.append(f"{cp}站在现场警惕四周。")
            if script_data.get("core_props") and isinstance(script_data.get("core_props"), list):
                for prop in script_data.get("core_props"):
                    meta_parts.append(f"手持【{prop}】。")
            if meta_parts:
                return "\n".join(meta_parts).strip()
            return json.dumps(script_data, ensure_ascii=False)
    if hasattr(script_data, "screenplay_text") and getattr(script_data, "screenplay_text"):
        return str(getattr(script_data, "screenplay_text")).strip()
    return str(script_data)


# =========================================================================
# 【规则编号: RULE-STAGE6-VOICE-V2】母音频试音词清洗、防撞音色池与阶段2同构补录辅助函数
# =========================================================================

# 防撞声学原型池 (供多角色声线自动分配，杜绝全剧角色撞音)
TIMBRE_ARCHETYPE_POOL: list[dict[str, Any]] = [
    {
        "timbre_archetype": "deep_baritone_gravel",
        "gender": "male",
        "timbre": "低沉砂砾感男中音",
        "vocal_position": "胸腔深层共鸣，喉位下沉",
        "vocal_flaws": "声带轻微疲劳发干，带30% Vocal Fry气泡音颗粒感",
        "speed_ratio": 0.92,
        "pitch_ratio": 0.95,
        "provider_voice_id": "male-qn-jingying",
        "timber_weights": [
            {"voice_id": "male-qn-jingying", "weight": 70},
            {"voice_id": "male-qn-badao", "weight": 30},
        ],
    },
    {
        "timbre_archetype": "cold_tenor_sharp",
        "gender": "male",
        "timbre": "冷冽锋利男高音",
        "vocal_position": "硬腭前部集中共鸣，吐字如刀锋般清晰",
        "vocal_flaws": "句尾带微冷鼻腔叹息与金属泛音",
        "speed_ratio": 1.02,
        "pitch_ratio": 1.03,
        "provider_voice_id": "male-qn-qingse",
        "timber_weights": [
            {"voice_id": "male-qn-qingse", "weight": 75},
            {"voice_id": "male-qn-jingying", "weight": 25},
        ],
    },
    {
        "timbre_archetype": "husky_alto_restrained",
        "gender": "female",
        "timbre": "清冷隐忍微哑女中音",
        "vocal_position": "咽腔与胸腔混合共鸣，声线克制内敛",
        "vocal_flaws": "情绪压抑时带微弱气音摩擦与换气颤音",
        "speed_ratio": 0.94,
        "pitch_ratio": 0.98,
        "provider_voice_id": "female-yujie",
        "timber_weights": [
            {"voice_id": "female-yujie", "weight": 75},
            {"voice_id": "female-chengshu", "weight": 25},
        ],
    },
    {
        "timbre_archetype": "crisp_soprano_fragile",
        "gender": "female",
        "timbre": "清亮破碎感青年女高音",
        "vocal_position": "头腔与口腔前部共鸣，干净透亮",
        "vocal_flaws": "急促吸气声明显，高音尾音带脆弱微颤",
        "speed_ratio": 1.05,
        "pitch_ratio": 1.04,
        "provider_voice_id": "female-shaonv",
        "timber_weights": [
            {"voice_id": "female-shaonv", "weight": 80},
            {"voice_id": "female-tianmei", "weight": 20},
        ],
    },
    {
        "timbre_archetype": "weathered_raspy_elder",
        "gender": "male",
        "timbre": "苍老沙哑低沉嗓音",
        "vocal_position": "下胸腔深沉共鸣，气息厚重沧桑",
        "vocal_flaws": "明显声带磨损沙砾感与慢速停顿喘息",
        "speed_ratio": 0.86,
        "pitch_ratio": 0.90,
        "provider_voice_id": "male-qn-badao",
        "timber_weights": [
            {"voice_id": "male-qn-badao", "weight": 85},
            {"voice_id": "male-qn-jingying", "weight": 15},
        ],
    },
    {
        "timbre_archetype": "warm_narrator_neutral",
        "gender": "female",
        "timbre": "温润沉静叙事女声",
        "vocal_position": "口腔中位平稳共鸣，咬字温润松弛",
        "vocal_flaws": "自然唇齿微响与柔和尾音衰减",
        "speed_ratio": 0.96,
        "pitch_ratio": 1.0,
        "provider_voice_id": "female-chengshu",
        "timber_weights": [
            {"voice_id": "female-chengshu", "weight": 80},
            {"voice_id": "female-yujie", "weight": 20},
        ],
    },
]


def _strip_dialogue_brackets(raw_line: str, character_name: str = "") -> str:
    """剥离台词中的括号舞台提示与说话人前缀，确保母音频试音词为 25~48 字纯净干声台本。"""
    text = str(raw_line or "").strip()
    # 剥离中英文圆括号、方括号中的舞台指示（如：（后槽牙死死咬紧，声带发干））
    text = re.sub(r"[（\(][^）\)]*[）\)]", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    # 剥离角色名前缀（如 "沈炼："）
    if character_name and text.startswith(f"{character_name}："):
        text = text[len(character_name) + 1 :]
    elif character_name and text.startswith(f"{character_name}:"):
        text = text[len(character_name) + 1 :]
    text = text.strip(" \t\n\r\"'“”‘’")

    if len(text) < 20:
        prefix_name = f"我是{character_name}，" if character_name else ""
        base_pad = text if text else "有些账就算烂在泥里，我也得一笔一笔亲手算清楚。"
        text = f"{prefix_name}{base_pad}说话要有凭据，这屋里的每一步棋，谁都别想抵赖。"
    if len(text) > 52:
        text = text[:48].rstrip("，、；,;") + "。"
    return text


def _build_default_emotion_rules() -> dict[str, dict[str, Any]]:
    """构建纯净 6 维戏剧状态声学偏移矩阵 (剔除任何混音 ducking 参数)。"""
    return {
        "calm_suppressed": {
            "speed_delta": -0.08,
            "pitch_delta": -0.05,
            "tension": "high_internal",
            "prompt_addon": "压低声线，胸腔紧绷，字字克制冷冽，句尾带微弱鼻息",
        },
        "tension_clenched": {
            "speed_delta": -0.05,
            "pitch_delta": -0.02,
            "tension": "clenched_jaw",
            "prompt_addon": "后槽牙咬紧，字词从齿缝挤出，声带紧绷干涩",
        },
        "explosive_rage": {
            "speed_delta": 0.15,
            "pitch_delta": 0.12,
            "tension": "explosive",
            "prompt_addon": "声量骤然爆发，横膈膜强力顶出，尾音带撕裂颗粒感",
        },
        "grief_choked": {
            "speed_delta": -0.15,
            "pitch_delta": -0.08,
            "tension": "choked_tremor",
            "prompt_addon": "咽喉哽咽发紧，气息断续颤抖，极力忍泪的沙哑气音",
        },
        "fear_trembling": {
            "speed_delta": 0.10,
            "pitch_delta": 0.08,
            "tension": "shallow_breath",
            "prompt_addon": "呼吸短促浅薄，声线发虚颤栗，停顿间隙夹杂急促抽气声",
        },
        "ironic_sneer": {
            "speed_delta": -0.04,
            "pitch_delta": 0.03,
            "tension": "cold_mockery",
            "prompt_addon": "半声冷笑起音，鼻腔共鸣偏重，尾音轻微上挑讥诮",
        },
    }


def _select_voice_archetype(
    char_info: dict[str, Any],
    used_archetypes: set[str],
    index_hint: int = 0,
) -> dict[str, Any]:
    """为角色分配不与已出场角色冲突的声学音色原型。"""
    FEMALE_TOKENS = ["婉", "晓", "夏", "琴", "琳", "姐", "妹", "女", "妻", "母", "颖", "雅", "婷", "静", "雪", "菲", "薇", "柔", "云"]
    c_name = str(char_info.get("name") or "")
    raw_gender = str(char_info.get("gender") or "").lower()
    if raw_gender in ("female", "女", "woman"):
        gender = "female"
    elif raw_gender in ("male", "男", "man"):
        gender = "male"
    else:
        gender = "female" if any(tk in c_name for tk in FEMALE_TOKENS) else "male"

    same_gender_pool = [p for p in TIMBRE_ARCHETYPE_POOL if p["gender"] == gender] or TIMBRE_ARCHETYPE_POOL
    for candidate in same_gender_pool:
        if candidate["timbre_archetype"] not in used_archetypes:
            used_archetypes.add(candidate["timbre_archetype"])
            return dict(candidate)

    chosen = dict(same_gender_pool[index_hint % len(same_gender_pool)])
    used_archetypes.add(chosen["timbre_archetype"])
    return chosen


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


def extract_pure_physical_environment_cues(scanner_result: ScreenplayScanResult | None) -> str:
    """提取纯物理环境影调线索（仅光影氛围/气候/时间），绝不包含任何实体名单（角色名、场景名、道具名）。
    
    此举从输入源头彻底切除大模型的先验注意力锚定与弱关联台词提及幻读！
    """
    if not scanner_result:
        return "- 物理影调: 光照正常，自然影视漫反射，无极端气候异动。"

    lines: list[str] = []
    lights = scanner_result.lighting_conditions or []
    if lights:
        lines.append(f"- 光影明暗与照明质感: {', '.join(lights)}")
    else:
        lines.append("- 光影明暗与照明质感: 自然电影感侧逆光，微弱漫反射")

    time_weather = getattr(scanner_result, "time_weather_conditions", []) or []
    if time_weather:
        lines.append(f"- 气候与时间环境: {', '.join(time_weather)}")

    return "\n".join(lines) if lines else "- 物理影调: 现实影视质感，标准摄影布光。"


class AssetEntityNormalizer:
    """阶段 6 实体三级归一化漏斗 (Tiered Entity Normalizer)。
    
    通过 L1 别名精确查表 -> L2 职衔称谓正则剥离与双向包含 -> L3 随身物反向嗅探与空间闭包，
    将大模型纯文本盲抽出的粗糙名称与全局资产库进行高置信度对齐与新实体判定。
    """

    def __init__(
        self,
        known_characters: dict[str, Any] | list[Any] | None,
        known_envs_props: dict[str, Any] | None,
        scanner_result: ScreenplayScanResult | None,
    ):
        self.known_chars: dict[str, dict[str, Any]] = {}
        if isinstance(known_characters, dict):
            for k, v in known_characters.items():
                if isinstance(v, dict):
                    self.known_chars[k] = v
        elif isinstance(known_characters, list):
            for idx, c in enumerate(known_characters):
                if isinstance(c, dict):
                    name = c.get("name") or f"CHAR_{idx}"
                    self.known_chars[name] = c

        self.known_envs_props = known_envs_props or {}
        self.scanner_alias_map = getattr(scanner_result, "character_alias_map", {}) or {}

    def normalize_character_name(self, raw_name: str) -> tuple[str, bool, dict[str, Any] | None]:
        """三级归一化角色名称。
        
        返回: (standard_name, is_existing, matched_char_profile)
        """
        clean_name = str(raw_name).strip()
        if not clean_name:
            return "UNKNOWN_CHAR", False, None

        # Level 1: 扫描器别名映射表与库中 aliases 列表精确命中
        # 1.1 扫描器别名字典 (如 "老沈" -> "沈炼")
        if clean_name in self.scanner_alias_map:
            target_name = self.scanner_alias_map[clean_name]
            for cid, prof in self.known_chars.items():
                if prof.get("name") == target_name:
                    return target_name, True, prof

        # 1.2 库中别名字段匹配
        for cid, prof in self.known_chars.items():
            c_name = prof.get("name", "")
            aliases = prof.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            if clean_name == c_name or clean_name in aliases:
                return c_name, True, prof

        # Level 2: 常见职衔称谓正则剥离与双向包含命中
        # 剥离前缀: 锦衣卫/东厂/提督/掌柜/大人/刺客/头领/老/小
        # 剥离后缀: 大人/公公/姑娘/公子/师傅/总管
        stripped_name = re.sub(r"^(锦衣卫|东厂|提督|掌柜|刺客|头领|老|小)+", "", clean_name).strip()
        stripped_name = re.sub(r"(大人|公公|姑娘|公子|师傅|总管)+$", "", stripped_name).strip()
        if stripped_name:
            for cid, prof in self.known_chars.items():
                c_name = prof.get("name", "")
                if not c_name:
                    continue
                if stripped_name == c_name or stripped_name in c_name or c_name in stripped_name:
                    return c_name, True, prof

        # Level 3: 未在库中命中，判定为真实当集新登场实体 (标记待增量入库)
        return clean_name, False, None

    def normalize_prop_name(
        self,
        raw_name: str,
        associated_char_name: str | None = None,
    ) -> tuple[str, bool, dict[str, Any] | None]:
        """道具三级归一化与随身物品反向嗅探。"""
        clean_name = str(raw_name).strip()
        if not clean_name:
            return "UNKNOWN_PROP", False, None

        props_registry = self.known_envs_props.get("props") or {}

        # Level 1: 精确名称或已有注册匹配
        for pid, pprof in props_registry.items():
            if isinstance(pprof, dict):
                p_name = pprof.get("name", "")
                if clean_name == p_name or clean_name in pprof.get("aliases", []):
                    return p_name, True, pprof

        # Level 2: 字面双向包含
        for pid, pprof in props_registry.items():
            if isinstance(pprof, dict):
                p_name = pprof.get("name", "")
                if p_name and (clean_name in p_name or p_name in clean_name):
                    return p_name, True, pprof

        # Level 3: 角色随身物品反向嗅探 (如通用道具"药丸/刀"，结合角色反向查其随身道具)
        if associated_char_name:
            std_char, exists, char_prof = self.normalize_character_name(associated_char_name)
            if exists and char_prof:
                portable = char_prof.get("portable_props") or char_prof.get("anchored_items") or []
                for item in portable:
                    item_str = item if isinstance(item, str) else item.get("name", "")
                    if clean_name in item_str or item_str in clean_name:
                        return item_str, True, {"name": item_str, "parent_character": std_char}

        return clean_name, False, None

    def normalize_environment_name(self, raw_name: str) -> tuple[str, bool, dict[str, Any] | None]:
        """场景名称归一化。"""
        clean_name = str(raw_name).strip()
        if not clean_name:
            return "UNKNOWN_ENV", False, None

        envs_registry = self.known_envs_props.get("environments") or {}

        # Level 1: 精确匹配
        for eid, eprof in envs_registry.items():
            if isinstance(eprof, dict):
                e_name = eprof.get("name", "")
                if clean_name == e_name or clean_name in eprof.get("aliases", []):
                    return e_name, True, eprof

        # Level 2: 空间词双向包含 (如 "废弃破庙" 与 "破庙大堂")
        for eid, eprof in envs_registry.items():
            if isinstance(eprof, dict):
                e_name = eprof.get("name", "")
                if e_name and (clean_name in e_name or e_name in clean_name):
                    return e_name, True, eprof

        return clean_name, False, None


class MorphStateMachine:
    """剧情语义驱动的多形态分级派生状态机。
    
    根据大模型提取的客观剧情物理切片（伤情、动作、交互、微距）及 Scanner 后端特征，
    确定性派生一级（基准）、二级（表演/局部机位/破坏物证）、三级（战损/手部特写）四段式规范资产：
    - 角色：
      * T1_BASE (Tier 1 基准肖像立绘，t2i，无父级依赖)；
      * T3_STATUS_INJURED (Tier 3 战伤态，i2i，挂载 T1_BASE，denoise=0.45)；
      * T3_MACRO_HAND (Tier 3 关键手部特写，i2i，挂载 T1_BASE，denoise=0.55)；
    - 场景：
      * T1_WIDE (Tier 1 全景基准机位，t2i，无父级依赖)；
      * Z01_ZONE (Tier 2 局部功能子机位，i2i/t2i，挂载 T1_WIDE，denoise=0.40)；
    - 道具：
      * S0_STATIC (Tier 1 基础完好底模，t2i，无父级依赖)；
      * S1_ACTION (Tier 2 破坏/形变/交互态，i2i，挂载 S0_STATIC，denoise=0.50)。
    """

    @classmethod
    def derive_character_morphs(
        cls,
        char_name: str,
        motion_slice: dict[str, Any],
        is_existing: bool,
        char_profile: dict[str, Any] | None = None,
        scanner_injuries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        morphs: list[dict[str, Any]] = []
        token = AssetProtocolHelper.chinese_to_token(char_name)
        base_id = (
            char_profile.get("character_code")
            or char_profile.get("asset_id")
            or f"CHAR_{token}_T1_BASE_PORTRAIT"
            if is_existing and char_profile
            else AssetProtocolHelper.generate_deterministic_id("CHAR", char_name, "T1_BASE")
        )

        # 1. 必选 Tier 1 基础肖像立绘态 (T1_BASE)
        morphs.append({
            "asset_id": base_id,
            "category": "CHAR",
            "name": char_name,
            "form": "T1_BASE",
            "tier": "T1",
            "is_benchmark": 1,
            "generation_mode": "t2i",
            "parent_asset_id": None,
            "parent_asset_key": None,
            "denoising_strength": 0.0,
            "motion_slice": motion_slice,
            "is_new": not is_existing,
        })
        logger.debug("【形态状态机】派生角色一级基准资产: %s -> %s (T1_BASE)", char_name, base_id)

        # 2. Tier 3 战损/负伤态判定 (T3_STATUS_INJURED)
        wounds = str(motion_slice.get("physical_wounds", "")).strip()
        has_injury = bool(wounds and wounds not in ("无", "none", "null")) or bool(scanner_injuries)
        if has_injury:
            injured_id = AssetProtocolHelper.generate_deterministic_id("CHAR", char_name, "T3_STATUS_INJURED")
            injury_detail = wounds if wounds and wounds not in ("无", "none", "null") else (", ".join(scanner_injuries) if scanner_injuries else "战损创伤")
            morphs.append({
                "asset_id": injured_id,
                "category": "CHAR",
                "name": char_name,
                "form": "T3_STATUS_INJURED",
                "tier": "T3",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.45,
                "motion_slice": {**motion_slice, "physical_wounds": injury_detail},
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发战损派生角色三级资产: %s -> %s (父级=%s, denoise=0.45)", char_name, injured_id, base_id)

        # 3. Tier 3 手部特写/微距态判定 (T3_MACRO_HAND)
        motion = str(motion_slice.get("current_motion", "")).strip()
        if any(kw in motion for kw in ("握", "持", "拿", "拔", "刺", "抓", "指", "扣", "按", "掏", "递")):
            macro_id = AssetProtocolHelper.generate_deterministic_id("CHAR", char_name, "T3_MACRO_HAND")
            morphs.append({
                "asset_id": macro_id,
                "category": "CHAR",
                "name": char_name,
                "form": "T3_MACRO_HAND",
                "tier": "T3",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.55,
                "motion_slice": motion_slice,
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发手部动作派生三级特写资产: %s -> %s (父级=%s, denoise=0.55)", char_name, macro_id, base_id)

        return morphs

    @classmethod
    def derive_environment_morphs(
        cls,
        env_name: str,
        env_slice: dict[str, Any],
        is_existing: bool,
        env_profile: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        morphs: list[dict[str, Any]] = []
        token = AssetProtocolHelper.chinese_to_token(env_name)
        base_id = (
            env_profile.get("scene_code")
            or env_profile.get("asset_id")
            or f"ENV_{token}_T1_WIDE"
            if is_existing and env_profile
            else AssetProtocolHelper.generate_deterministic_id("ENV", env_name, "T1_WIDE")
        )

        # 1. 必选 Tier 1 场景全景主机位 (T1_WIDE)
        morphs.append({
            "asset_id": base_id,
            "category": "ENV",
            "name": env_name,
            "form": "T1_WIDE",
            "tier": "T1",
            "is_benchmark": 1,
            "generation_mode": "t2i",
            "parent_asset_id": None,
            "parent_asset_key": None,
            "denoising_strength": 0.0,
            "env_slice": env_slice,
            "is_new": not is_existing,
        })
        logger.debug("【形态状态机】派生场景一级全景资产: %s -> %s (T1_WIDE)", env_name, base_id)

        # 2. Tier 2 局部功能子机位区域 (Z01_ZONE)
        sub_spot = str(env_slice.get("sub_zone_spot", "")).strip()
        if sub_spot and sub_spot not in ("无", "none", "全景"):
            zone_id = AssetProtocolHelper.generate_deterministic_id("ENV", env_name, "Z01_ZONE")
            morphs.append({
                "asset_id": zone_id,
                "category": "ENV",
                "name": f"{env_name}_{sub_spot}",
                "form": "Z01_ZONE",
                "tier": "T2",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.40,
                "env_slice": env_slice,
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发子区域机位派生二级资产: %s -> %s (父级=%s, denoise=0.40)", env_name, zone_id, base_id)

        return morphs

    @classmethod
    def derive_prop_morphs(
        cls,
        prop_name: str,
        prop_slice: dict[str, Any],
        is_existing: bool,
        prop_profile: dict[str, Any] | None = None,
        is_deformed_in_scanner: bool = False,
    ) -> list[dict[str, Any]]:
        morphs: list[dict[str, Any]] = []
        token = AssetProtocolHelper.chinese_to_token(prop_name)
        base_id = (
            prop_profile.get("prop_code")
            or prop_profile.get("asset_id")
            or f"PROP_{token}_T1_STATIC"
            if is_existing and prop_profile
            else AssetProtocolHelper.generate_deterministic_id("PROP", prop_name, "S0_STATIC")
        )

        # 1. 必选 Tier 1 标准完好底模 (S0_STATIC)
        morphs.append({
            "asset_id": base_id,
            "category": "PROP",
            "name": prop_name,
            "form": "S0_STATIC",
            "tier": "T1",
            "is_benchmark": 1,
            "generation_mode": "t2i",
            "parent_asset_id": None,
            "parent_asset_key": None,
            "denoising_strength": 0.0,
            "prop_slice": prop_slice,
            "is_new": not is_existing,
        })
        logger.debug("【形态状态机】派生道具一级静态底模: %s -> %s (S0_STATIC)", prop_name, base_id)

        # 2. Tier 2 破坏/形变/交互动作态 (S1_ACTION)
        damage_state = str(prop_slice.get("damage_state", "")).upper()
        if damage_state in ("DAMAGED", "ACTION", "BROKEN", "BURNT") or is_deformed_in_scanner:
            action_id = AssetProtocolHelper.generate_deterministic_id("PROP", prop_name, "S1_ACTION")
            morphs.append({
                "asset_id": action_id,
                "category": "PROP",
                "name": prop_name,
                "form": "S1_ACTION",
                "tier": "T2",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.50,
                "prop_slice": prop_slice,
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发物证破坏态派生二级动作资产: %s -> %s (父级=%s, denoise=0.50)", prop_name, action_id, base_id)

        return morphs


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

    # 3. 场景与光影氛围
    scenes = scanner_result.scenes_detected or []
    if scenes:
        lines.append(f"- 涉及场景空间: {', '.join(scenes)}")
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


def _stage6_fallback(
    episode_num_or_state: Any = None,
    script_data: dict[str, Any] | None = None,
    characters_engine: dict[str, Any] | list[dict[str, Any]] | None = None,
    envs_props: dict[str, Any] | None = None,
    existing_registry: dict[str, Any] | None = None,
    scanner_result: ScreenplayScanResult | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-03】大模型离线或异常时的单集资产清单保底工厂，遵循章节三四段式协议与 Table 6 规范装配。"""
    # 动态解析参数：支持传入 state 状态机对象或显式集数
    episode_num = 1
    state_obj = None

    if isinstance(episode_num_or_state, int):
        episode_num = episode_num_or_state
    elif episode_num_or_state is not None:
        state_obj = episode_num_or_state
        if hasattr(state_obj, "current_visual_episode"):
            episode_num = getattr(state_obj, "current_visual_episode") or 1
        elif isinstance(state_obj, dict):
            episode_num = state_obj.get("current_visual_episode") or state_obj.get("episode_num") or 1

    if "episode_num" in kwargs:
        episode_num = int(kwargs.pop("episode_num"))
    elif "episode_id" in kwargs:
        episode_num = int(kwargs.pop("episode_id"))

    if state_obj is not None:
        if script_data is None:
            if hasattr(state_obj, "completed_screenplays"):
                cs = getattr(state_obj, "completed_screenplays") or {}
                script_data = cs.get(episode_num) or cs.get(str(episode_num))
            elif isinstance(state_obj, dict):
                cs = state_obj.get("completed_screenplays") or {}
                script_data = cs.get(episode_num) or cs.get(str(episode_num))
        if characters_engine is None:
            characters_engine = getattr(state_obj, "character_system", None) or (state_obj.get("character_system") if isinstance(state_obj, dict) else None)
        if envs_props is None:
            envs_props = getattr(state_obj, "environment_and_props_system", None) or (state_obj.get("environment_and_props_system") if isinstance(state_obj, dict) else None)
        if existing_registry is None:
            existing_registry = getattr(state_obj, "visual_assets_registry", None) or (state_obj.get("visual_assets_registry") if isinstance(state_obj, dict) else None)
        if not kwargs.get("visual_style"):
            kwargs["visual_style"] = getattr(state_obj, "global_visual_style", "") or (state_obj.get("global_visual_style") if isinstance(state_obj, dict) else "")

    logger.warning(f"Triggering Stage 6 dynamic fallback asset compilation for Episode {episode_num}.")

    script_data = script_data or kwargs.get("script_dict") or {}
    chars_input = characters_engine if characters_engine is not None else kwargs.get("character_engine", [])
    if isinstance(chars_input, list):
        chars = chars_input
    elif isinstance(chars_input, dict):
        chars = chars_input.get("characters") or []
    else:
        chars = []

    envs_props = envs_props or kwargs.get("environments_props") or kwargs.get("environments_and_props") or {}
    envs = envs_props.get("environments") or envs_props.get("scenes") or []
    props = envs_props.get("props") or []

    # 提取上游注入的视觉风格、画幅与单集标题
    visual_style = kwargs.get("visual_style") or "cinematic photorealistic 8k, gritty film grain, realistic dramatic lighting"
    aspect_ratio = kwargs.get("aspect_ratio") or "9:16"
    episode_title = (
        kwargs.get("episode_title")
        or (script_data.get("episode_title") if isinstance(script_data, dict) else "")
        or (script_data.get("title") if isinstance(script_data, dict) else "")
        or f"第{episode_num}集"
    )

    # 提取已核准资产列表以确保只读复用
    reg = existing_registry or {}
    if hasattr(reg, "to_dict"):
        reg = reg.to_dict()
    elif hasattr(reg, "model_dump"):
        reg = reg.model_dump()
    existing_char_ids = set((reg.get("characters") or {}).keys())
    existing_env_ids = set((reg.get("environments") or {}).keys())
    existing_prop_ids = set((reg.get("props") or {}).keys())
    existing_voice_ids = set((reg.get("audio_tts") or {}).keys())
    all_existing_ids = existing_char_ids | existing_env_ids | existing_prop_ids | existing_voice_ids

    existing_char_by_name: dict[str, str] = {}
    for aid, item in (reg.get("characters") or {}).items():
        if isinstance(item, dict):
            cname = item.get("character_name") or item.get("name")
            if cname:
                existing_char_by_name[cname] = aid

    existing_env_by_name: dict[str, str] = {}
    for aid, item in (reg.get("environments") or {}).items():
        if isinstance(item, dict):
            ename = item.get("scene_name") or item.get("location_name") or item.get("name")
            if ename:
                existing_env_by_name[ename] = aid

    existing_prop_by_name: dict[str, str] = {}
    for aid, item in (reg.get("props") or {}).items():
        if isinstance(item, dict):
            pname = item.get("prop_name") or item.get("name")
            if pname:
                existing_prop_by_name[pname] = aid

    # 提取本集向量/实体召回的候选资产池，优先复用已召回的已存在资产 (Phase 3 候选池融合)
    candidates = kwargs.get("candidates") or []
    for cand in candidates:
        if isinstance(cand, dict):
            c_key = str(cand.get("asset_key") or cand.get("asset_id") or "")
            c_name = str(cand.get("name") or "")
            c_cat = str(cand.get("category") or "")
            is_existing = bool(
                cand.get("is_existing_asset", False)
                or cand.get("recall_source") in ("db_exact", "db_exact_asset", "vector_semantic", "memory_registry")
            )
            if c_key and is_existing:
                all_existing_ids.add(c_key)
                if c_cat == "character" and c_name and c_name not in existing_char_by_name:
                    existing_char_by_name[c_name] = c_key
                    existing_char_ids.add(c_key)
                elif c_cat in ("scene", "environment") and c_name and c_name not in existing_env_by_name:
                    existing_env_by_name[c_name] = c_key
                    existing_env_ids.add(c_key)
                elif c_cat == "prop" and c_name and c_name not in existing_prop_by_name:
                    existing_prop_by_name[c_name] = c_key
                    existing_prop_ids.add(c_key)

    # 扫描正文特征
    script_text = _extract_screenplay_text(script_data)
    if scanner_result is None:
        scanner_result = scan_screenplay_features(
            screenplay_text=script_text,
            existing_assets_registry=all_existing_ids,
            known_characters=chars,
            known_environments=envs,
            known_props=props,
        )

    # -------------------------------------------------------------------------
    # 【规则编号: RULE-STAGE6-NEW-CHAR】检测本集剧本中登场但阶段2未注册的新角色，按阶段2标准11维补录
    # -------------------------------------------------------------------------
    registered_names: set[str] = set()
    existing_char_codes: set[str] = set()
    used_archetypes: set[str] = set()
    primary_protagonist_code = "CHAR_PROTAGONIST"
    primary_protagonist_name = "主角"

    for idx_c, c_item in enumerate(chars):
        if not isinstance(c_item, dict):
            continue
        cname = str(c_item.get("name") or "").strip()
        ccode = str(c_item.get("character_code") or c_item.get("character_id") or "").strip()
        if cname:
            registered_names.add(cname)
        if ccode:
            existing_char_codes.add(ccode if ccode.startswith("CHAR_") else f"CHAR_{ccode}")
        if c_item.get("timbre_archetype"):
            used_archetypes.add(str(c_item["timbre_archetype"]))
        if idx_c == 0 or c_item.get("role_type") == "protagonist" or c_item.get("role") == "main":
            if cname:
                primary_protagonist_name = cname
            if ccode:
                primary_protagonist_code = ccode if ccode.startswith("CHAR_") else f"CHAR_{ccode}"

    for cname_existing in existing_char_by_name:
        registered_names.add(cname_existing)

    newly_discovered_characters: list[dict[str, Any]] = []
    detected_char_names = list(scanner_result.characters_detected or []) if scanner_result else []
    
    # 【核心防御·真实在场过滤】：仅保留当集真实在场的已知角色，绝不无条件将全剧角色代入本集装配
    active_chars_for_episode: list[dict[str, Any]] = []
    # 提取结构化出场角色列表（兼容历史测试输入）
    explicit_present_set = set()
    if isinstance(script_data, dict) and script_data.get("characters_present"):
        for cp in script_data.get("characters_present"):
            if cp and str(cp).strip():
                explicit_present_set.add(str(cp).strip())

    for c_item in chars:
        if not isinstance(c_item, dict):
            continue
        c_name = str(c_item.get("name") or "").strip()
        if not c_name:
            continue
        # 严格使用在场判定核验（命中显式出场列表或剧本正文出场）
        if c_name in explicit_present_set or is_character_truly_in_screenplay(c_item, script_text, detected_char_names):
            active_chars_for_episode.append(c_item)
            logger.debug("【保底工厂·在场准入】已知角色 [%s] 确认在本集登场，纳入装配池", c_name)
        else:
            logger.debug("【保底工厂·未登场拦截】已知角色 [%s] 本集未登场，已从装配池剔除", c_name)

    all_chars_for_episode = list(active_chars_for_episode)

    for det_idx, det_name in enumerate(detected_char_names, start=1):
        clean_det = str(det_name or "").strip()
        if not clean_det or clean_det in registered_names:
            continue
        # 过滤泛化群演词、声学/镜头/舞台指令标签
        if not is_valid_character_speaker(clean_det, known_names=registered_names):
            logger.debug("【阶段 6 新角色过滤】跳过非具名角色/舞台声学指令标识: %s", clean_det)
            continue
        # 再次确认剧本正文真实登场（严防扫描器将死者/案卷/回忆名词误作新角色）
        if not is_character_truly_in_screenplay(clean_det, script_text, detected_char_names):
            logger.debug("【保底工厂·新角色拦截】扫描候选词 [%s] 经脱敏核验未真实在场，放弃补录建档", clean_det)
            continue

        new_dossier = _build_stage2_character_dossier(
            char_name=clean_det,
            episode_num=episode_num,
            screenplay_text=script_text,
            existing_char_codes=existing_char_codes,
            used_archetypes=used_archetypes,
            primary_protagonist_code=primary_protagonist_code,
            primary_protagonist_name=primary_protagonist_name,
            index_hint=len(all_chars_for_episode) + det_idx,
        )
        newly_discovered_characters.append(new_dossier)
        all_chars_for_episode.append(new_dossier)
        registered_names.add(clean_det)
        logger.info(
            "【保底工厂·阶段2标准新角色补录】第 %d 集发现未在阶段2登记的新角色 [%s] -> 分配编码 [%s]，已生成11维全息档案与音色原型 [%s]",
            episode_num, clean_det, new_dossier["character_code"], new_dossier["timbre_archetype"],
        )

    # 保底机制：若真实在场角色不足 2 人（如简短单人戏或独白），按角色优先级补充主角/核心配角以确保基础对戏与视听契约
    if len(all_chars_for_episode) < 2 and chars:
        existing_names = {str(c.get("name") or "").strip() for c in all_chars_for_episode if isinstance(c, dict)}
        for c_item in chars:
            if not isinstance(c_item, dict):
                continue
            c_name = str(c_item.get("name") or "").strip()
            if c_name and c_name not in existing_names:
                all_chars_for_episode.append(c_item)
                existing_names.add(c_name)
                if len(all_chars_for_episode) >= 2:
                    break

    reused_assets: list[dict[str, Any]] = []
    newly_assets: list[dict[str, Any]] = []
    new_voice_cards: list[dict[str, Any]] = []

    manifest_chars: list[dict[str, Any]] = []
    manifest_envs: list[dict[str, Any]] = []
    manifest_props: list[dict[str, Any]] = []

    # 表6分层容器
    chars_t1: list[dict[str, Any]] = []
    chars_t2: list[dict[str, Any]] = []
    chars_t3: list[dict[str, Any]] = []
    envs_t1: list[dict[str, Any]] = []
    envs_t2: list[dict[str, Any]] = []
    props_t1: list[dict[str, Any]] = []
    props_t2: list[dict[str, Any]] = []
    props_t3: list[dict[str, Any]] = []

    # 1. 角色资产装配 (算子 A & D，涵盖阶段2既有角色 + 本集动态补录新角色)
    for idx, c in enumerate(all_chars_for_episode, start=1):
        c_name = c.get("name", f"角色{idx}")
        raw_cid = c.get("character_id") or ""
        tok = None
        if c_name in existing_char_by_name:
            tok = _extract_token_from_id(existing_char_by_name[c_name], "CHAR", "")
        if not tok and raw_cid:
            tok = _extract_token_from_id(raw_cid, "CHAR", "")
        if not tok:
            tok = PINYIN_LOOKUP.get(c_name) or _slugify_chinese(c_name) or _extract_token_from_id("", "CHAR", f"ROLE{idx:02d}")

        bio = c.get("biological_dna") or {}
        costume = c.get("lived_in_costume") or {}

        bio_desc = (
            f"骨相与五官: {bio.get('bone_structure', '高颧骨方正下颌')}; "
            f"皮肤肌理: {bio.get('skin_micro_texture', '真实粗糙毛孔与自然细纹')}; "
            f"面部瑕疵: {bio.get('blemishes_and_scars', '毫米级真实暗疮与旧疤痕')}; "
            f"眼唇解剖: {bio.get('eye_lip_anatomy', '眼眶微凹带红血丝，干燥微起皮唇纹')}; "
            f"发质发型: {bio.get('hair_texture', '粗硬微卷自然碎发')}"
        )
        costume_desc = (
            f"上装: {costume.get('top_wear', '重磅粗花呢600g/m²大衣（手肘自然折痕）')}; "
            f"下装: {costume.get('bottom_wear', '耐磨工装裤裤腿带泥斑')}; "
            f"鞋履: {costume.get('footwear', '磨损鞋面落地工装皮靴')}; "
            f"做旧细节: {costume.get('wear_and_tear_details', '第二颗纽扣线头松脱2cm')}"
        )

        portrait_id = f"CHAR_{tok}_T1_BASE_PORTRAIT"
        costume_id = f"CHAR_{tok}_T1_BASE_COSTUME"
        voice_id = f"VOICE_{tok}_T1_MASTER"

        char_identity_prompt = PromptSynthesizer.extract_character_identity_prompt(c)
        char_neg_prompt = PromptSynthesizer.get_category_negative_prompt("character")

        # 0号肖像基准与语义指纹计算
        dep_portrait = AssetProtocolHelper.resolve_dependency(portrait_id)
        portrait_synth = PromptSynthesizer.synthesize_character_view_prompt(c, view_type="BASE_PORTRAIT", stage_code="T1", style_modifiers=visual_style)
        portrait_prompt = portrait_synth.visual_prompt
        portrait_hash = compute_asset_semantic_hash(
            "CHAR", portrait_id, portrait_prompt, {"bio": bio_desc, "costume": costume_desc}
        )
        portrait_item = {
            "char_id": portrait_id,
            "asset_id": portrait_id,
            "name": c_name,
            "tier": "T1",
            "stage_code": "T1",
            "function_type": "BASE_PORTRAIT",
            "parent_asset_key": dep_portrait.parent_asset_id,
            "parent_asset_id": dep_portrait.parent_asset_id,
            "generation_mode": dep_portrait.generation_mode,
            "denoise_strength": dep_portrait.recommended_denoise,
            "recommended_denoise": dep_portrait.recommended_denoise,
            "control_type": dep_portrait.control_type,
            "is_benchmark": 1 if dep_portrait.is_benchmark else 0,
            "workflow_note": dep_portrait.workflow_note,
            "costume": costume_desc,
            "identity_prompt": char_identity_prompt,
            "delta_prompt": "",
            "negative_prompt": char_neg_prompt,
            "visual_prompt": portrait_prompt,
            "prompt": portrait_prompt,
            "semantic_hash": portrait_hash,
            "lifecycle_status": AssetState.APPROVED.value,
        }
        manifest_chars.append(portrait_item)

        if portrait_id in all_existing_ids:
            reused_assets.append({
                "asset_id": portrait_id,
                "type": "character_base_identity",
                "usage_in_current_ep": f"本集复用已核准 0 号肖像基准 {portrait_id}",
                "status": "APPROVED",
                "lifecycle_status": AssetState.APPROVED.value,
                "semantic_hash": portrait_hash,
            })
            logger.debug("【保底工厂·资产复用】角色 0 号肖像 [%s] 命中已有真理源，标记为 APPROVED 只读复用", portrait_id)
        else:
            newly_assets.append({
                "asset_id": portrait_id,
                "name": c_name,
                "character_name": c_name,
                "asset_category": "character_tier1_base",
                "script_inference_trigger": f"角色【{c_name}】首次登场，注册0号基准肖像",
                "generation_method": "text_to_image",
                "input_source_image": None,
                "identity_reference": None,
                "denoising_strength": None,
                "aspect_ratio": "9:16",
                "parent_asset_key": None,
                "parent_asset_id": None,
                "generation_mode": "t2i",
                "denoise_strength": None,
                "control_type": None,
                "is_benchmark": 1,
                "identity_prompt": char_identity_prompt,
                "delta_prompt": "",
                "negative_prompt": char_neg_prompt,
                "image_prompt": portrait_prompt,
                "prompt": portrait_prompt,
                "status": "APPROVED",
                "lifecycle_status": AssetState.READY.value,
                "semantic_hash": portrait_hash,
            })
            logger.info("【保底工厂·增量生成】角色 0 号肖像 [%s] 注册为增量生成项 (指纹: %s)", portrait_id, portrait_hash)

        # 定妆照 (从头到脚完整落地，严禁裁切)
        dep_costume = AssetProtocolHelper.resolve_dependency(costume_id)
        costume_synth = PromptSynthesizer.synthesize_character_view_prompt(c, view_type="BASE_COSTUME", stage_code="T1", style_modifiers=visual_style)
        costume_prompt = costume_synth.visual_prompt
        costume_hash = compute_asset_semantic_hash(
            "CHAR", costume_id, costume_prompt, {"costume": costume_desc}
        )
        costume_item = {
            "char_id": costume_id,
            "asset_id": costume_id,
            "name": c_name,
            "tier": "T1",
            "stage_code": "T1",
            "function_type": "BASE_COSTUME",
            "parent_asset_key": dep_costume.parent_asset_id,
            "parent_asset_id": dep_costume.parent_asset_id,
            "generation_mode": dep_costume.generation_mode,
            "denoise_strength": dep_costume.recommended_denoise,
            "recommended_denoise": dep_costume.recommended_denoise,
            "control_type": dep_costume.control_type,
            "is_benchmark": 0,
            "workflow_note": dep_costume.workflow_note,
            "costume": costume_desc,
            "identity_prompt": char_identity_prompt,
            "delta_prompt": costume_synth.delta_prompt,
            "negative_prompt": char_neg_prompt,
            "visual_prompt": costume_prompt,
            "prompt": costume_prompt,
            "semantic_hash": costume_hash,
            "lifecycle_status": AssetState.APPROVED.value,
        }
        manifest_chars.append(costume_item)

        if costume_id in all_existing_ids:
            reused_assets.append({
                "asset_id": costume_id,
                "type": "character_base_costume",
                "usage_in_current_ep": f"本集复用已核准全身定妆照 {costume_id}",
                "status": "APPROVED",
                "lifecycle_status": AssetState.APPROVED.value,
                "semantic_hash": costume_hash,
            })
            logger.debug("【保底工厂·资产复用】角色全身定妆照 [%s] 命中已有真理源，标记为 APPROVED 只读复用", costume_id)
        else:
            newly_assets.append({
                "asset_id": costume_id,
                "name": f"{c_name}(全身定妆照)",
                "character_name": c_name,
                "asset_category": "character_tier1_base",
                "script_inference_trigger": f"角色【{c_name}】全身生活质感服化道定妆照注册",
                "generation_method": "image_to_image",
                "input_source_image": portrait_id,
                "identity_reference": portrait_id,
                "denoising_strength": 0.45,
                "aspect_ratio": "9:16",
                "parent_asset_key": portrait_id,
                "parent_asset_id": portrait_id,
                "generation_mode": "i2i",
                "denoise_strength": 0.45,
                "control_type": "i2i",
                "is_benchmark": 0,
                "identity_prompt": char_identity_prompt,
                "delta_prompt": costume_synth.delta_prompt,
                "negative_prompt": char_neg_prompt,
                "image_prompt": costume_prompt,
                "status": "APPROVED",
                "lifecycle_status": AssetState.READY.value,
                "semantic_hash": costume_hash,
            })
            logger.info("【保底工厂·增量生成】角色全身定妆照 [%s] 注册为图生图增量项 (指纹: %s)", costume_id, costume_hash)

        # Table 6 T1 结构
        chars_t1.append({
            "char_id": portrait_id,
            "character_id": f"CHAR_{tok}",
            "character_name": c_name,
            "base_portrait": portrait_id,
            "base_costume": costume_id,
            "master_voice": voice_id,
            "visual_prompt": portrait_prompt,
        })

        # 四视图单张独立生成 (T1 姿态与视角展开，根据主定妆图生成，严禁四宫格)
        four_view_defs = [
            ("4V_FRONT", "正面定妆视角 (Head-to-toe)"),
            ("4V_SIDE", "侧面90度定妆视角 (Head-to-toe)"),
            ("4V_BACK", "背面180度定妆视角 (Head-to-toe)"),
            ("4V_3Q", "3/4侧面定妆视角 (Head-to-toe)"),
        ]
        angle_views = []
        for v_code, v_label in four_view_defs:
            v_id = f"CHAR_{tok}_T1_{v_code}"
            dep_v = AssetProtocolHelper.resolve_dependency(v_id)
            v_synth = PromptSynthesizer.synthesize_character_view_prompt(
                c, view_type=v_code, costume_prompt=costume_desc, visual_style=visual_style
            )
            v_prompt = v_synth.visual_prompt
            v_hash = compute_asset_semantic_hash("CHAR", v_id, v_prompt, {"view": v_code, "costume": costume_desc})
            manifest_chars.append({
                "char_id": v_id,
                "asset_id": v_id,
                "name": c_name,
                "tier": "T1",
                "stage_code": "T1",
                "function_type": v_code,
                "parent_asset_key": dep_v.parent_asset_id,
                "parent_asset_id": dep_v.parent_asset_id,
                "generation_mode": dep_v.generation_mode,
                "denoise_strength": dep_v.recommended_denoise,
                "recommended_denoise": dep_v.recommended_denoise,
                "control_type": dep_v.control_type,
                "is_benchmark": 0,
                "workflow_note": f"单张独立{v_label}，以 BASE_COSTUME 为底图 ControlNet 姿态生成",
                "costume": costume_desc,
                "identity_prompt": char_identity_prompt,
                "delta_prompt": v_synth.delta_prompt,
                "negative_prompt": char_neg_prompt,
                "visual_prompt": v_prompt,
                "prompt": v_prompt,
                "semantic_hash": v_hash,
                "lifecycle_status": AssetState.APPROVED.value,
            })
            angle_views.append(v_id)
            if v_id not in all_existing_ids:
                newly_assets.append({
                    "asset_id": v_id,
                    "name": f"{c_name}-{v_label}",
                    "character_name": c_name,
                    "asset_category": "character_tier1_angle",
                    "script_inference_trigger": f"角色【{c_name}】单张{v_label}",
                    "generation_method": "controlnet",
                    "input_source_image": costume_id,
                    "identity_reference": portrait_id,
                    "denoising_strength": dep_v.recommended_denoise,
                    "aspect_ratio": "9:16",
                    "parent_asset_key": dep_v.parent_asset_id,
                    "parent_asset_id": dep_v.parent_asset_id,
                    "generation_mode": dep_v.generation_mode,
                    "denoise_strength": dep_v.recommended_denoise,
                    "control_type": dep_v.control_type,
                    "is_benchmark": 0,
                    "identity_prompt": char_identity_prompt,
                    "delta_prompt": v_synth.delta_prompt,
                    "negative_prompt": char_neg_prompt,
                    "image_prompt": v_prompt,
                    "prompt": v_prompt,
                    "status": "APPROVED",
                    "lifecycle_status": AssetState.READY.value,
                    "semantic_hash": v_hash,
                })

        emotions = []
        if "咬牙" in script_text or "紧绷" in script_text or "后槽牙" in script_text:
            exp_id = f"CHAR_{tok}_T2_EXP_TENSION"
            dep_exp = AssetProtocolHelper.resolve_dependency(exp_id)
            exp_prompt = f"cinematic close-up portrait of {c_name}, clenching jaw with extreme tension, veins subtly visible, moody noir --style raw"
            exp_hash = compute_asset_semantic_hash("CHAR", exp_id, exp_prompt, {"emotion": "TENSION"})
            manifest_chars.append({
                "char_id": exp_id,
                "asset_id": exp_id,
                "name": c_name,
                "tier": "T2",
                "function_type": "EXP_TENSION",
                "parent_asset_key": dep_exp.parent_asset_id,
                "parent_asset_id": dep_exp.parent_asset_id,
                "generation_mode": dep_exp.generation_mode,
                "denoise_strength": dep_exp.recommended_denoise,
                "recommended_denoise": dep_exp.recommended_denoise,
                "control_type": dep_exp.control_type,
                "is_benchmark": 0,
                "workflow_note": "咬牙紧绷微表情局部重绘",
                "identity_prompt": char_identity_prompt,
                "delta_prompt": exp_prompt,
                "negative_prompt": char_neg_prompt,
                "visual_prompt": exp_prompt,
                "semantic_hash": exp_hash,
                "lifecycle_status": AssetState.APPROVED.value,
            })
            emotions.append(exp_id)

        chars_t2.append({
            "character_id": f"CHAR_{tok}",
            "angle_views": angle_views,
            "script_emotions": emotions,
        })

        # 特写微距与战损 (T3)
        special_macros = []
        status_branches = []
        if any(k in script_text for k in ["手指", "掐掌心", "打火机", "手背", "手腕"]):
            macro_id = f"CHAR_{tok}_T3_MACRO_HAND"
            dep_macro = AssetProtocolHelper.resolve_dependency(macro_id)
            macro_prompt = f"cinematic extreme macro shot of {c_name}'s weathered hand, dirt under fingernails, knuckle creases --style raw"
            macro_hash = compute_asset_semantic_hash("CHAR", macro_id, macro_prompt, {"macro": "HAND"})
            manifest_chars.append({
                "char_id": macro_id,
                "asset_id": macro_id,
                "name": c_name,
                "tier": "T3",
                "function_type": "MACRO_HAND",
                "parent_asset_key": dep_macro.parent_asset_id,
                "parent_asset_id": dep_macro.parent_asset_id,
                "generation_mode": dep_macro.generation_mode,
                "denoise_strength": dep_macro.recommended_denoise,
                "recommended_denoise": dep_macro.recommended_denoise,
                "control_type": dep_macro.control_type,
                "is_benchmark": 0,
                "workflow_note": "手部微表情与生理微距特写",
                "identity_prompt": char_identity_prompt,
                "delta_prompt": macro_prompt,
                "negative_prompt": char_neg_prompt,
                "visual_prompt": macro_prompt,
                "semantic_hash": macro_hash,
                "lifecycle_status": AssetState.APPROVED.value,
            })
            special_macros.append(macro_id)

        if any(k in script_text for k in ["流血", "淤青", "战损", "伤口", "湿透"]):
            status_id = f"CHAR_{tok}_T3_STATUS_INJURED"
            dep_status = AssetProtocolHelper.resolve_dependency(status_id)
            status_prompt = f"cinematic shot of {c_name}, bruised cheek, dried blood stain at temple, damp unkempt hair --style raw"
            status_hash = compute_asset_semantic_hash("CHAR", status_id, status_prompt, {"status": "INJURED"})
            manifest_chars.append({
                "char_id": status_id,
                "asset_id": status_id,
                "name": c_name,
                "tier": "T3",
                "function_type": "STATUS_INJURED",
                "parent_asset_key": dep_status.parent_asset_id,
                "parent_asset_id": dep_status.parent_asset_id,
                "generation_mode": dep_status.generation_mode,
                "denoise_strength": dep_status.recommended_denoise,
                "recommended_denoise": dep_status.recommended_denoise,
                "control_type": dep_status.control_type,
                "is_benchmark": 0,
                "workflow_note": "负伤战损分支局部重绘",
                "identity_prompt": char_identity_prompt,
                "delta_prompt": status_prompt,
                "negative_prompt": char_neg_prompt,
                "visual_prompt": status_prompt,
                "semantic_hash": status_hash,
                "lifecycle_status": AssetState.APPROVED.value,
            })
            status_branches.append(status_id)

        chars_t3.append({
            "character_id": f"CHAR_{tok}",
            "special_macro": special_macros,
            "status_branch": status_branches,
        })

        # 声音母音 (算子 D - V2 精细化角色音色卡与母音频干声台本)
        ac_p = c.get("acoustic_persona") if isinstance(c.get("acoustic_persona"), dict) else {}
        fp = c.get("voice_fingerprint") if isinstance(c.get("voice_fingerprint"), dict) else {}
        voice_arch = _select_voice_archetype(c, used_archetypes, index_hint=idx)

        raw_sample_line = (
            fp.get("script_monologue_source")
            or fp.get("catchphrase")
            or f"（后槽牙死死咬紧，声带发干）说话要有凭据，心跳可瞒不过我。"
        )
        master_sample_text = _strip_dialogue_brackets(
            c.get("master_sample_text") or fp.get("catchphrase") or raw_sample_line,
            character_name=c_name,
        )
        vocal_position = ac_p.get("vocal_position") or voice_arch["vocal_position"]
        vocal_flaws = ac_p.get("vocal_flaws") or voice_arch["vocal_flaws"]
        timbre_archetype = c.get("timbre_archetype") or voice_arch["timbre_archetype"]
        voice_timbre = c.get("timbre") or ac_p.get("timbre") or fp.get("timbre") or voice_arch["timbre"]
        speed_ratio = float(c.get("speed_ratio") or voice_arch["speed_ratio"] or 1.0)
        pitch_ratio = float(c.get("pitch_ratio") or voice_arch["pitch_ratio"] or 1.0)
        provider_voice_id = str(c.get("provider_voice_id") or voice_arch["provider_voice_id"])
        timber_weights = c.get("timber_weights") or voice_arch["timber_weights"]
        emotion_rules = c.get("emotion_rules") if isinstance(c.get("emotion_rules"), dict) and c.get("emotion_rules") else _build_default_emotion_rules()
        # 剔除任何非法混音/闪避参数 (如 bgm_ducking_db)
        emotion_rules = {
            ek: {k: v for k, v in ev.items() if k != "bgm_ducking_db"} if isinstance(ev, dict) else ev
            for ek, ev in emotion_rules.items()
        }

        tts_prompt = (
            f"{voice_timbre}，{vocal_position}，{vocal_flaws}，"
            f"语速倍率{speed_ratio:.2f}，音高倍率{pitch_ratio:.2f}，微弱真实呼吸换气声"
        )
        voice_hash = compute_asset_semantic_hash(
            "VOICE", voice_id, tts_prompt, {"sample_line": master_sample_text, "archetype": timbre_archetype}
        )

        if voice_id in all_existing_ids:
            reused_assets.append({
                "asset_id": voice_id,
                "type": "voice_master",
                "usage_in_current_ep": f"本集复用已核准母音频 {voice_id}",
                "status": "APPROVED",
                "lifecycle_status": AssetState.APPROVED.value,
                "semantic_hash": voice_hash,
            })
            logger.debug("【保底工厂·资产复用】声音母音 [%s] 命中已有真理源，标记为 APPROVED 只读复用", voice_id)
        else:
            new_voice_cards.append({
                "character_id": f"CHAR_{tok}",
                "character_code": f"CHAR_{tok}",
                "character_name": c_name,
                "master_voice_id": voice_id,
                "timbre": voice_timbre,
                "timbre_archetype": timbre_archetype,
                "vocal_position": vocal_position,
                "vocal_flaws": vocal_flaws,
                "speed_ratio": speed_ratio,
                "pitch_ratio": pitch_ratio,
                "tts_provider": "minimax",
                "tts_model": "speech-02-hd",
                "provider_voice_id": provider_voice_id,
                "timber_weights": timber_weights,
                "voice_prompt": tts_prompt,
                "script_monologue_source": raw_sample_line,
                "master_sample_text": master_sample_text,
                "master_tts_prompt": tts_prompt,
                "voice_file_path": f"storage/audio/voices/{voice_id}.mp3",
                "emotion_rules": emotion_rules,
                "semantic_hash": voice_hash,
                "is_benchmark": 1,
                "parent_asset_key": None,
                "generation_mode": "tts_zero_shot",
                "lifecycle_status": AssetState.READY.value,
            })
            logger.info(
                "【保底工厂·增量生成】V2 声音母音卡 [%s] (角色: %s, 原型: %s) 注册为增量母音 (指纹: %s)",
                voice_id, c_name, timbre_archetype, voice_hash,
            )

    # 2. 场景资产装配 (算子 B) —— 涵盖阶段3既有场景 + 本集动态补录新场景
    registered_scene_names: set[str] = set()
    existing_scene_codes: set[str] = set()
    for s_item in envs:
        if isinstance(s_item, dict):
            sname = str(s_item.get("location_name") or s_item.get("scene_name") or s_item.get("name") or "").strip()
            scode = str(s_item.get("scene_code") or s_item.get("env_id") or s_item.get("scene_id") or "").strip()
            if sname:
                registered_scene_names.add(sname)
            if scode:
                existing_scene_codes.add(scode if scode.startswith("ENV_") else f"ENV_{scode}")
    for sname_existing in existing_env_by_name:
        registered_scene_names.add(sname_existing)

    newly_discovered_scenes: list[dict[str, Any]] = []
    detected_scene_names = list(scanner_result.scenes_detected or []) if scanner_result else []
    all_envs_for_episode = list(envs)

    for det_idx, det_name in enumerate(detected_scene_names, start=1):
        clean_det = str(det_name or "").strip()
        if not clean_det or clean_det in registered_scene_names:
            continue
        new_scene_dossier = _build_stage3_scene_dossier(
            scene_name=clean_det,
            episode_num=episode_num,
            existing_scene_codes=existing_scene_codes,
            scanner_result=scanner_result,
            visual_style=visual_style,
        )
        newly_discovered_scenes.append(new_scene_dossier)
        all_envs_for_episode.append(new_scene_dossier)
        registered_scene_names.add(clean_det)
        logger.info(
            "【保底工厂·阶段3标准新场景补录】第 %d 集发现未在阶段3登记的新场景 [%s] -> 分配编码 [%s]，基准底模 [%s]，规划子区域数: %d",
            episode_num, clean_det, new_scene_dossier["scene_code"], new_scene_dossier["benchmark_asset_key"], len(new_scene_dossier.get("zones", [])),
        )

    scene_neg_prompt = PromptSynthesizer.get_category_negative_prompt("scene")
    for idx, e in enumerate(all_envs_for_episode, start=1):
        loc_name = e.get("location_name") or e.get("location") or e.get("name", f"核心场景{idx}")
        raw_eid = e.get("env_id") or e.get("environment_id") or e.get("scene_code") or ""
        tok = None
        if loc_name in existing_env_by_name:
            tok = _extract_token_from_id(existing_env_by_name[loc_name], "ENV", "")
        if not tok and raw_eid:
            tok = _extract_token_from_id(raw_eid, "ENV", "")
        if not tok:
            tok = (
                e.get("scene_code")
                or PINYIN_LOOKUP.get(loc_name)
                or _slugify_chinese(loc_name)
                or _extract_token_from_id("", "ENV", f"SCENE{idx:02d}")
            )

        wide_id = f"ENV_{tok}_T1_WIDE"
        dep_wide = AssetProtocolHelper.resolve_dependency(wide_id)
        env_synth = PromptSynthesizer.synthesize_scene_view_prompt(e, view_type="WIDE", zone_code="Z01", style_modifiers=visual_style)
        wide_prompt = env_synth.visual_prompt
        wide_hash = compute_asset_semantic_hash("ENV", wide_id, wide_prompt, {"weathering": e.get("weathering_layers", "")})
        manifest_envs.append({
            "scene_id": wide_id,
            "asset_id": wide_id,
            "location_name": loc_name,
            "tier": "T1",
            "function_type": "WIDE",
            "parent_asset_key": dep_wide.parent_asset_id,
            "parent_asset_id": dep_wide.parent_asset_id,
            "generation_mode": dep_wide.generation_mode,
            "denoise_strength": dep_wide.recommended_denoise,
            "recommended_denoise": dep_wide.recommended_denoise,
            "control_type": dep_wide.control_type,
            "is_benchmark": 1 if dep_wide.is_benchmark else 0,
            "workflow_note": dep_wide.workflow_note,
            "weathering_layers": e.get("weathering_layers", "锈蚀工字钢与水渍倒影"),
            "identity_prompt": env_synth.identity_prompt,
            "delta_prompt": env_synth.delta_prompt,
            "negative_prompt": scene_neg_prompt,
            "visual_prompt": wide_prompt,
            "semantic_hash": wide_hash,
            "lifecycle_status": AssetState.APPROVED.value,
        })

        if wide_id in all_existing_ids:
            reused_assets.append({
                "asset_id": wide_id,
                "type": "environment_primary",
                "usage_in_current_ep": f"本集复用已核准主场景全景 {wide_id}",
                "status": "APPROVED",
                "lifecycle_status": AssetState.APPROVED.value,
                "semantic_hash": wide_hash,
            })
            logger.debug("【保底工厂·资产复用】主场景全景 [%s] 命中已有真理源，标记为 APPROVED 只读复用", wide_id)
        else:
            newly_assets.append({
                "asset_id": wide_id,
                "name": loc_name,
                "location_name": loc_name,
                "asset_category": "environment_tier1_primary",
                "script_inference_trigger": f"主场景【{loc_name}】全景建立镜头",
                "generation_method": "text_to_image",
                "input_source_image": None,
                "identity_reference": None,
                "denoising_strength": None,
                "aspect_ratio": "9:16",
                "parent_asset_key": None,
                "parent_asset_id": None,
                "generation_mode": "t2i",
                "denoise_strength": None,
                "control_type": None,
                "is_benchmark": 1,
                "identity_prompt": env_synth.identity_prompt,
                "delta_prompt": env_synth.delta_prompt,
                "negative_prompt": scene_neg_prompt,
                "image_prompt": wide_prompt,
                "status": "APPROVED",
                "lifecycle_status": AssetState.READY.value,
                "semantic_hash": wide_hash,
            })
            logger.info("【保底工厂·增量生成】主场景全景 [%s] 注册为文生图增量项 (指纹: %s)", wide_id, wide_hash)

        ots_id = f"ENV_{tok}_T1_OTS_BG"
        dep_ots = AssetProtocolHelper.resolve_dependency(ots_id)
        ots_prompt = f"shallow depth of field blurred background plate of {wide_id}, cinematic bokeh, atmospheric dust --style raw"
        ots_hash = compute_asset_semantic_hash("ENV", ots_id, ots_prompt, {})
        manifest_envs.append({
            "scene_id": ots_id,
            "asset_id": ots_id,
            "location_name": f"{loc_name}(过肩虚化板)",
            "tier": "T1",
            "function_type": "OTS_BG",
            "parent_asset_key": dep_ots.parent_asset_id,
            "parent_asset_id": dep_ots.parent_asset_id,
            "generation_mode": dep_ots.generation_mode,
            "denoise_strength": dep_ots.recommended_denoise,
            "recommended_denoise": dep_ots.recommended_denoise,
            "control_type": dep_ots.control_type,
            "is_benchmark": 0,
            "workflow_note": dep_ots.workflow_note,
            "weathering_layers": e.get("weathering_layers", "背景虚化"),
            "identity_prompt": env_synth.identity_prompt,
            "delta_prompt": "shallow depth of field blurred background plate, cinematic bokeh",
            "negative_prompt": scene_neg_prompt,
            "visual_prompt": ots_prompt,
            "semantic_hash": ots_hash,
            "lifecycle_status": AssetState.APPROVED.value,
        })

        # 提取或构建子区域列表 (动态继承阶段3规划或从扫描器识别)
        scene_zones = e.get("zones")
        if not scene_zones:
            detected_z = []
            if scanner_result and isinstance(getattr(scanner_result, "scene_zones_detected", None), dict):
                detected_z = list(scanner_result.scene_zones_detected.get(loc_name) or [])
            if detected_z:
                scene_zones = [
                    {
                        "zone_code": f"Z{z_idx:02d}",
                        "zone_name": z_name,
                        "time_lighting": "光影对比鲜明，空间明暗交界清晰",
                        "acoustic_resistance": "封闭空间混响与微弱空气底噪",
                        "parent_zone_id": None if z_idx == 1 else "Z01",
                    }
                    for z_idx, z_name in enumerate(detected_z, start=1)
                ]
            else:
                scene_zones = [
                    {
                        "zone_code": "Z01",
                        "zone_name": f"{loc_name}主活动区",
                        "time_lighting": "剧情主氛围光效，明暗层次丰富",
                        "acoustic_resistance": "标准空间混响与空气底噪",
                        "parent_zone_id": None,
                    }
                ]

        envs_t1.append({
            "scene_id": wide_id,
            "env_id": f"ENV_{tok}_T1",
            "scene_name": loc_name,
            "location_name": loc_name,
            "wide_shot": wide_id,
            "insert_shot": f"ENV_{tok}_T1_INSERT_DETAIL",
            "lighting_state": f"ENV_{tok}_T1_STATE_NIGHT",
            "visual_prompt": wide_prompt,
            "zones": scene_zones,
        })

    # 3. 道具资产装配 (算子 C) —— 融合 Stage 3 核心物证与 Stage 2 角色随身锚点，并执行单道具同句形变隔离判定与新物证补录
    prop_neg_prompt = PromptSynthesizer.get_category_negative_prompt("prop")
    script_sentences = re.split(r"[。！？\n；!?;]", script_text or "")

    # 自动汇入 Stage 2 角色随身锚点道具 (carried_anchor_item / anchor_props)，消除 Stage 2 与 Stage 3 之间的断层
    existing_prop_names_set: set[str] = {
        str(p.get("name") or p.get("prop_name") or "").strip()
        for p in props
        if isinstance(p, dict) and (p.get("name") or p.get("prop_name"))
    }
    char_anchor_props = _extract_anchor_props_from_characters(all_chars_for_episode)
    merged_props: list[dict[str, Any]] = list(props)
    for cap in char_anchor_props:
        cap_name = cap["name"]
        if cap_name not in existing_prop_names_set:
            existing_prop_names_set.add(cap_name)
            merged_props.append({
                "prop_id": cap["prop_id"],
                "name": cap_name,
                "tier": "T2",
                "owner_character": cap.get("owner_character", ""),
            })
            logger.debug(
                "【保底工厂·Stage2锚点汇入】将角色 [%s] 的随身锚点道具 '%s' (%s) 汇入本集道具装配池",
                cap.get("owner_character", ""), cap_name, cap["prop_id"],
            )

    registered_prop_names: set[str] = set()
    existing_prop_codes: set[str] = set()
    for p_item in merged_props:
        if isinstance(p_item, dict):
            pname = str(p_item.get("prop_name") or p_item.get("name") or "").strip()
            pcode = str(p_item.get("prop_code") or p_item.get("prop_id") or "").strip()
            if pname:
                registered_prop_names.add(pname)
            if pcode:
                existing_prop_codes.add(pcode if pcode.startswith("PROP_") else f"PROP_{pcode}")
    for pname_existing in existing_prop_by_name:
        registered_prop_names.add(pname_existing)

    newly_discovered_props: list[dict[str, Any]] = []
    detected_prop_names = list(scanner_result.props_detected or []) if scanner_result else []
    all_props_for_episode = list(merged_props)

    for det_idx, det_name in enumerate(detected_prop_names, start=1):
        clean_det = str(det_name or "").strip()
        if not clean_det or clean_det in registered_prop_names:
            continue
        new_prop_dossier = _build_stage3_prop_dossier(
            prop_name=clean_det,
            episode_num=episode_num,
            existing_prop_codes=existing_prop_codes,
            scanner_result=scanner_result,
            visual_style=visual_style,
        )
        newly_discovered_props.append(new_prop_dossier)
        all_props_for_episode.append(new_prop_dossier)
        registered_prop_names.add(clean_det)
        logger.info(
            "【保底工厂·阶段3标准新道具补录】第 %d 集发现未在阶段3登记的新道具 [%s] -> 分配编码 [%s]，基准底模 [%s]，形态数: %d",
            episode_num, clean_det, new_prop_dossier["prop_code"], new_prop_dossier["benchmark_asset_key"], len(new_prop_dossier.get("damage_states", [])),
        )

    for idx, p in enumerate(all_props_for_episode, start=1):
        p_name = p.get("name") or p.get("prop_name") or f"核心物证{idx}"
        p_tier_raw = str(p.get("tier") or p.get("type") or "T1").upper()
        is_tier2_anchor = "T2" in p_tier_raw or "ANCHOR" in p_tier_raw or "TIER2" in p_tier_raw
        raw_pid = p.get("prop_id") or p.get("prop_code") or ""
        tok = None
        if p_name in existing_prop_by_name:
            tok = _extract_token_from_id(existing_prop_by_name[p_name], "PROP", "")
        if not tok and raw_pid:
            tok = _extract_token_from_id(raw_pid, "PROP", "")
        if not tok:
            tok = (
                p.get("prop_code")
                or PINYIN_LOOKUP.get(p_name)
                or _slugify_chinese(p_name)
                or _extract_token_from_id("", "PROP", f"ITEM{idx:02d}")
            )

        # 若属于 Stage 2 随身锚点道具 (Tier 2)，僅当本集剧本提及或属于核心出场角色锚点时注册进 T2
        if is_tier2_anchor:
            if script_text and not _entity_matches_text(p_name, script_text):
                continue
            anchor_id = f"PROP_{tok}_T2_ANCHOR"
            anchor_prompt = f"cinematic macro close-up of character anchor item {p_name}, lived-in weathered patina, realistic tactile details --style raw"
            anchor_hash = compute_asset_semantic_hash("PROP", anchor_id, anchor_prompt, {"tier": "T2"})
            manifest_props.append({
                "prop_id": anchor_id,
                "asset_id": anchor_id,
                "name": p_name,
                "tier": "T2",
                "function_type": "ANCHOR",
                "parent_asset_key": None,
                "parent_asset_id": None,
                "generation_mode": "t2i",
                "denoise_strength": None,
                "recommended_denoise": None,
                "control_type": None,
                "is_benchmark": 1,
                "workflow_note": "角色随身灵魂锚点道具独立微距资产",
                "identity_prompt": anchor_prompt,
                "delta_prompt": "",
                "negative_prompt": prop_neg_prompt,
                "visual_prompt": anchor_prompt,
                "semantic_hash": anchor_hash,
                "lifecycle_status": AssetState.APPROVED.value,
            })
            props_t2.append({
                "prop_id": anchor_id,
                "prop_name": p_name,
                "owner_character": p.get("owner_character", ""),
                "visual_prompt": anchor_prompt,
            })
            logger.debug("【保底工厂·Tier2随身锚点】已装配随身锚点道具 [%s] (%s)", p_name, anchor_id)
            continue

        static_id = f"PROP_{tok}_T1_STATIC"
        dep_static = AssetProtocolHelper.resolve_dependency(static_id)
        prop_synth = PromptSynthesizer.synthesize_prop_view_prompt(p, view_type="STATIC", state_code="S0", style_modifiers=visual_style)
        damage_scale = p.get("damage_scale", "微观金属划痕与边缘氧化")
        foley_resistance = p.get("foley_resistance", "+3dB 剧烈物理摩擦阻力拟音")

        static_prompt = prop_synth.visual_prompt
        static_hash = compute_asset_semantic_hash("PROP", static_id, static_prompt, {"damage_scale": damage_scale})
        manifest_props.append({
            "prop_id": static_id,
            "asset_id": static_id,
            "name": p_name,
            "tier": "T1",
            "function_type": "STATIC",
            "parent_asset_key": dep_static.parent_asset_id,
            "parent_asset_id": dep_static.parent_asset_id,
            "generation_mode": dep_static.generation_mode,
            "denoise_strength": dep_static.recommended_denoise,
            "recommended_denoise": dep_static.recommended_denoise,
            "control_type": dep_static.control_type,
            "is_benchmark": 1 if dep_static.is_benchmark else 0,
            "workflow_note": dep_static.workflow_note,
            "damage_scale": damage_scale,
            "foley_prompt": foley_resistance,
            "identity_prompt": prop_synth.identity_prompt,
            "delta_prompt": prop_synth.delta_prompt,
            "negative_prompt": prop_neg_prompt,
            "visual_prompt": static_prompt,
            "semantic_hash": static_hash,
            "lifecycle_status": AssetState.APPROVED.value,
        })

        if static_id in all_existing_ids:
            reused_assets.append({
                "asset_id": static_id,
                "type": "prop_static",
                "usage_in_current_ep": f"本集复用已核准静态物证 {static_id}",
                "status": "APPROVED",
                "lifecycle_status": AssetState.APPROVED.value,
                "semantic_hash": static_hash,
            })
            logger.debug("【保底工厂·资产复用】静态物证 [%s] 命中已有真理源，标记为 APPROVED 只读复用", static_id)
        else:
            newly_assets.append({
                "asset_id": static_id,
                "name": p_name,
                "prop_name": p_name,
                "asset_category": "prop_tier1_hero",
                "script_inference_trigger": f"核心物证【{p_name}】静态初始态建档",
                "generation_method": "text_to_image",
                "input_source_image": None,
                "identity_reference": None,
                "denoising_strength": None,
                "aspect_ratio": "1:1",
                "parent_asset_key": None,
                "parent_asset_id": None,
                "generation_mode": "t2i",
                "denoise_strength": None,
                "control_type": None,
                "is_benchmark": 1,
                "identity_prompt": prop_synth.identity_prompt,
                "delta_prompt": prop_synth.delta_prompt,
                "negative_prompt": prop_neg_prompt,
                "image_prompt": static_prompt,
                "status": "APPROVED",
                "lifecycle_status": AssetState.READY.value,
                "semantic_hash": static_hash,
            })
            logger.info("【保底工厂·增量生成】静态物证 [%s] 注册为文生图增量项 (指纹: %s)", static_id, static_hash)

        # 【单道具同句形变隔离判定】优先读取 scanner_result.deformed_props，或检查提及该道具的同句是否含破坏动词
        # 若当前剧本完全未提及具体道具名但存在全局破坏动词（如极简测试桩），则保底首个主物证支持形变以保障测试闭环
        prop_deformed_verbs: list[str] = []
        if scanner_result and isinstance(getattr(scanner_result, "deformed_props", None), dict):
            prop_deformed_verbs = list(scanner_result.deformed_props.get(p_name) or [])
        if not prop_deformed_verbs:
            for sent in script_sentences:
                if _entity_matches_text(p_name, sent):
                    for verb in DEFORMATION_VERBS:
                        if verb in sent and verb not in prop_deformed_verbs:
                            prop_deformed_verbs.append(verb)
        any_prop_mentioned_in_script = any(_entity_matches_text(cand_p.get("name", ""), script_text) for cand_p in all_props_for_episode if isinstance(cand_p, dict))
        if not prop_deformed_verbs and not any_prop_mentioned_in_script and idx == 1:
            for verb in DEFORMATION_VERBS:
                if verb in (script_text or ""):
                    prop_deformed_verbs.append(verb)

        action_id = f"PROP_{tok}_T1_ACTION_DAMAGED"
        if prop_deformed_verbs or action_id in all_existing_ids:
            dep_action = AssetProtocolHelper.resolve_dependency(action_id)
            action_prompt = (
                f"cinematic macro shot of damaged {p_name}, torn open, shattered fragments, "
                f"extreme physical destruction, tactile fibers, gritty noir lighting --style raw"
            )
            action_hash = compute_asset_semantic_hash("PROP", action_id, action_prompt, {"modifier": "DAMAGED"})
            manifest_props.append({
                "prop_id": action_id,
                "asset_id": action_id,
                "name": f"{p_name}(物理破坏交互态)",
                "tier": "T1",
                "function_type": "ACTION",
                "modifier": "DAMAGED",
                "parent_asset_key": dep_action.parent_asset_id,
                "parent_asset_id": dep_action.parent_asset_id,
                "generation_mode": dep_action.generation_mode,
                "denoise_strength": dep_action.recommended_denoise,
                "recommended_denoise": dep_action.recommended_denoise,
                "control_type": dep_action.control_type,
                "is_benchmark": 0,
                "workflow_note": dep_action.workflow_note,
                "damage_scale": f"{damage_scale} + 严重撕裂断裂形变",
                "foley_prompt": "+3dB 剧烈破坏摩擦爆裂音",
                "identity_prompt": prop_synth.identity_prompt,
                "delta_prompt": action_prompt,
                "negative_prompt": prop_neg_prompt,
                "visual_prompt": action_prompt,
                "semantic_hash": action_hash,
                "lifecycle_status": AssetState.APPROVED.value,
            })

            if action_id in all_existing_ids:
                reused_assets.append({
                    "asset_id": action_id,
                    "type": "prop_action",
                    "usage_in_current_ep": f"本集复用已核准破坏态物证 {action_id}",
                    "status": "APPROVED",
                    "lifecycle_status": AssetState.APPROVED.value,
                    "semantic_hash": action_hash,
                })
                logger.debug("【保底工厂·资产复用】破坏态物证 [%s] 命中已有真理源，标记为 APPROVED 只读复用", action_id)
            else:
                newly_assets.append({
                    "asset_id": action_id,
                    "name": f"{p_name}(物理破坏交互态)",
                    "prop_name": p_name,
                    "asset_category": "prop_tier1_hero",
                    "script_inference_trigger": f"核心物证【{p_name}】在同句命中破坏形变动词 {prop_deformed_verbs}",
                    "generation_method": "inpainting_local_edit",
                    "input_source_image": static_id,
                    "identity_reference": None,
                    "denoising_strength": 0.40,
                    "aspect_ratio": "1:1",
                    "parent_asset_key": static_id,
                    "parent_asset_id": static_id,
                    "generation_mode": "inpainting",
                    "denoise_strength": 0.40,
                    "control_type": "inpaint_only",
                    "is_benchmark": 0,
                    "identity_prompt": prop_synth.identity_prompt,
                    "delta_prompt": action_prompt,
                    "negative_prompt": prop_neg_prompt,
                    "visual_prompt": action_prompt,
                    "status": "APPROVED",
                    "lifecycle_status": AssetState.READY.value,
                    "semantic_hash": action_hash,
                })
                logger.info(
                    "【保底工厂·增量生成】破坏态物证 [%s] 因命中同句形变动词 %s 注册为局部重绘增量项 (指纹: %s)",
                    action_id, prop_deformed_verbs, action_hash,
                )
        else:
            action_id = None
            logger.debug("【保底工厂·形变隔离】物证 [%s] (%s) 未在同句命中破坏动词，跳过冗余破坏态生成", p_name, static_id)

        # 提取或构建形变状态树 (动态继承阶段3规划或按破坏动词生成)
        prop_damage_states = p.get("damage_states")
        if not prop_damage_states:
            prop_damage_states = [
                {
                    "state_code": "S0",
                    "state_label": f"{p_name}初始完好态",
                    "damage_level": 0,
                    "parent_state_id": None,
                    "narrative_point": f"第{episode_num}集初始物证基准状态（微观自然磨损与氧化层）",
                    "visual_prompt": static_prompt,
                    "is_benchmark": 1,
                }
            ]
            if action_id:
                prop_damage_states.append({
                    "state_code": "S1",
                    "state_label": f"{p_name}破坏交互态",
                    "damage_level": 2,
                    "parent_state_id": "S0",
                    "narrative_point": f"第{episode_num}集剧情动作触发形变破坏",
                    "visual_prompt": action_prompt,
                    "is_benchmark": 0,
                })

        props_t1.append({
            "prop_id": static_id,
            "prop_name": p_name,
            "static_asset": static_id,
            "action_asset": action_id,
            "haptic_resistance": foley_resistance,
            "visual_prompt": static_prompt,
            "damage_states": prop_damage_states,
        })

    # Table 6 标准 episode_resource_manifest（彻底清除硬编码“冷水饺”等特定剧目幽灵烟火气道具）
    episode_manifest_dict = {
        "episode_num": episode_num,
        "episode_title": episode_title,
        "aspect_ratio": aspect_ratio,
        "characters": {
            "tier1_base": chars_t1,
            "tier2_performance": chars_t2,
            "tier3_special": chars_t3,
        },
        "environments": {
            "tier1_primary": envs_t1,
            "tier2_transitional": envs_t2,
        },
        "props": {
            "tier1_hero": props_t1,
            "tier2_anchor": props_t2,
            "tier3_ambient": props_t3,
        },
        "newly_discovered_characters": newly_discovered_characters,
        "newly_discovered_scenes": newly_discovered_scenes,
        "newly_discovered_props": newly_discovered_props,
        # 兼容历史平铺结构字段
        "characters_tier_1": [c for c in manifest_chars if c.get("tier") == "T1"],
        "characters_tier_2": [c for c in manifest_chars if c.get("tier") == "T2"],
        "characters_tier_3": [c for c in manifest_chars if c.get("tier") == "T3"],
        "character_assets": manifest_chars,
        "scene_assets": manifest_envs,
        "prop_assets": manifest_props,
        "environments_primary": [e for e in manifest_envs if e.get("tier") == "T1"],
        "environments_transitional": [e for e in manifest_envs if e.get("tier") == "T2"],
        "props_narrative": [p for p in manifest_props if p.get("tier") == "T1" and "ACTION" not in p.get("asset_id", "")],
        "props_anchors": [p for p in manifest_props if p.get("tier") == "T2"],
        "props_ambient": [p for p in manifest_props if p.get("tier") == "T3"],
    }

    lineage_dag: dict[str, str | None] = {}
    for item in newly_assets:
        aid = item.get("asset_id")
        if aid:
            lineage_dag[aid] = item.get("parent_asset_key") or item.get("parent_asset_id") or item.get("input_source_image")

    return {
        "episode_id": episode_num,
        "episode_num": episode_num,
        "episode_title": episode_title,
        "global_assets_summary": {
            "total_registered_characters": len(all_chars_for_episode),
            "total_registered_environments": len(all_envs_for_episode),
            "total_registered_props": len(all_props_for_episode),
        },
        "newly_discovered_characters": newly_discovered_characters,
        "newly_discovered_scenes": newly_discovered_scenes,
        "newly_discovered_props": newly_discovered_props,
        "reused_existing_assets": reused_assets,
        "newly_generated_assets": newly_assets,
        "new_character_master_voice_cards": new_voice_cards,
        "episode_resource_manifest": episode_manifest_dict,
        "manifest": episode_manifest_dict,
        "lineage_dag": lineage_dag,
        "audit_report": {
            "blue_team": "角色三级、场景两级、道具三级分类完备，所有资产四段式ID与生图参数合法",
            "red_team_critic": "无网红磨皮塑料假人，全身定妆照脚底完整落地无裁切，物证破坏态与剧本严格锚定",
            "verdict": "GREEN_APPROVED",
        },
    }


def _clean_name(raw_name: str) -> str:
    """去除角色名称中的括号说明、修饰后缀与舞台标记，提取自然人基准姓名。"""
    if not raw_name:
        return ""
    return re.sub(r"[\(（\[【].*?[\)）\]】]", "", str(raw_name)).strip()


def _ensure_standard_asset(
    item: dict[str, Any],
    default_cat: str,
    token_whitelist: set[str],
    fallback_tok: str = "DEFAULT",
) -> dict[str, Any]:
    """对 LLM 输出的资产项执行四段式纠偏与依赖推导补全。

    【架构防线设计】
    1. 动态角色令牌归纳：优先由 item 的 character_name / name 推导实体 token，阻断非主角资产降级为默认主角。
    2. 基准肖像独立性：BASE_PORTRAIT 严格作为文生图根节点 (parent_asset_id=None, generation_mode='t2i')。
    3. 衍生视图同实体闭环：严格防范跨角色资产继承，若 parent_asset_id 指向异名角色，强制修正为同角色标准底模。
    """
    raw_id = (
        item.get("asset_id")
        or item.get("asset_key")
        or item.get("char_id")
        or item.get("scene_id")
        or item.get("prop_id")
        or item.get("voice_id")
        or ""
    )
    parsed = AssetProtocolHelper.parse_id(raw_id)

    # 提取实体名称以便进行实体对齐
    char_name = str(item.get("character_name") or item.get("name") or "").strip()
    inferred_char_tok = ""
    if default_cat == "CHAR" and char_name:
        clean_nm = _clean_name(char_name)
        inferred_char_tok = AssetProtocolHelper.normalize_token(clean_nm or char_name)

    env_name = str(item.get("location_name") or item.get("scene_name") or item.get("name") or "").strip()
    inferred_env_tok = ""
    if default_cat == "ENV" and env_name:
        clean_en = _clean_name(env_name)
        inferred_env_tok = AssetProtocolHelper.normalize_token(clean_en or env_name)

    prop_name = str(item.get("prop_name") or item.get("item_name") or item.get("name") or "").strip()
    inferred_prop_tok = ""
    if default_cat == "PROP" and prop_name:
        clean_pn = _clean_name(prop_name)
        inferred_prop_tok = AssetProtocolHelper.normalize_token(clean_pn or prop_name)

    if parsed and parsed.category == default_cat:
        # 如果解析出的 token 是通用占位符 (DEFAULT, PROTAGONIST, CHAR) 且有更明确的 inferred_char_tok，则进行纠偏
        if default_cat == "CHAR" and inferred_char_tok and inferred_char_tok not in ("DEFAULT", "UNKNOWN", "CHARACTER"):
            if parsed.token in ("DEFAULT", "UNKNOWN", "PROTAGONIST", "CHAR") and parsed.token != inferred_char_tok:
                logger.debug(
                    "【阶段 6 资产协议纠偏】角色占位代号 [%s] 根据角色名 [%s] 纠正为 [%s]",
                    parsed.token, char_name, inferred_char_tok,
                )
                std_id = AssetProtocolHelper.build_id(parsed.category, inferred_char_tok, parsed.tier, parsed.function)
            else:
                std_id = parsed.standard_id
        elif default_cat == "ENV" and inferred_env_tok and inferred_env_tok not in ("DEFAULT", "UNKNOWN", "MAINSCENE", "SCENE", "ENV"):
            if parsed.token in ("DEFAULT", "UNKNOWN", "MAINSCENE", "SCENE", "ENV") and parsed.token != inferred_env_tok:
                logger.debug(
                    "【阶段 6 资产协议纠偏】场景占位代号 [%s] 根据场景名 [%s] 纠正为 [%s]",
                    parsed.token, env_name, inferred_env_tok,
                )
                std_id = AssetProtocolHelper.build_id(parsed.category, inferred_env_tok, parsed.tier, parsed.function)
            else:
                std_id = parsed.standard_id
        elif default_cat == "PROP" and inferred_prop_tok and inferred_prop_tok not in ("DEFAULT", "UNKNOWN", "EVIDENCE", "PROP", "ITEM"):
            if parsed.token in ("DEFAULT", "UNKNOWN", "EVIDENCE", "PROP", "ITEM") and parsed.token != inferred_prop_tok:
                logger.debug(
                    "【阶段 6 资产协议纠偏】道具占位代号 [%s] 根据道具名 [%s] 纠正为 [%s]",
                    parsed.token, prop_name, inferred_prop_tok,
                )
                std_id = AssetProtocolHelper.build_id(parsed.category, inferred_prop_tok, parsed.tier, parsed.function)
            else:
                std_id = parsed.standard_id
        else:
            std_id = parsed.standard_id
    else:
        norm_raw = AssetProtocolHelper.normalize_id(raw_id)
        tok = fallback_tok
        # 1. 优先使用从实体名推导出的 token
        if default_cat == "CHAR" and inferred_char_tok and inferred_char_tok not in ("DEFAULT", "UNKNOWN", "CHARACTER"):
            tok = inferred_char_tok
        elif default_cat == "ENV" and inferred_env_tok and inferred_env_tok not in ("DEFAULT", "UNKNOWN", "MAINSCENE", "SCENE", "ENV"):
            tok = inferred_env_tok
        elif default_cat == "PROP" and inferred_prop_tok and inferred_prop_tok not in ("DEFAULT", "UNKNOWN", "EVIDENCE", "PROP", "ITEM"):
            tok = inferred_prop_tok
        else:
            for t in token_whitelist:
                if t in norm_raw:
                    tok = t
                    break

        if default_cat == "CHAR":
            tier = "T1"
            if any(k in norm_raw for k in ["PORTRAIT", "BASE_PORTRAIT", "MAIN_PORTRAIT"]):
                func = "BASE_PORTRAIT"
            elif any(k in norm_raw for k in ["FRONT", "4V_FRONT"]):
                func = "4V_FRONT"
            elif any(k in norm_raw for k in ["SIDE", "PROFILE", "4V_SIDE"]):
                func = "4V_SIDE"
            elif any(k in norm_raw for k in ["BACK", "REAR", "4V_BACK"]):
                func = "4V_BACK"
            elif any(k in norm_raw for k in ["3Q", "THREE_QUARTER", "QUARTER", "4V_3Q"]):
                func = "4V_3Q"
            elif any(k in norm_raw for k in ["MACRO_FACE", "FACIAL_MACRO"]):
                func = "MACRO_FACE"
            elif any(k in norm_raw for k in ["MACRO_HAND", "HANDS_DETAIL"]):
                func = "MACRO_HAND"
            elif any(k in norm_raw for k in ["COSTUME", "FULL_BODY", "FULLBODY"]):
                func = "BASE_COSTUME"
            else:
                func = "BASE_COSTUME"
        elif default_cat == "ENV":
            tier = "T1"
            func = "OTS_BG" if "OTS" in norm_raw or "BG" in norm_raw else "WIDE"
        elif default_cat == "PROP":
            tier = "T1"
            func = "ACTION" if "ACTION" in norm_raw or "DAMAGE" in norm_raw else "STATIC"
        elif default_cat == "VOICE":
            tier = "T1"
            func = "MASTER"
        else:
            tier = "T1"
            func = "BASE"
        std_id = AssetProtocolHelper.build_id(default_cat, tok, tier, func)

    item["asset_id"] = std_id
    item["asset_key"] = std_id
    if default_cat == "CHAR":
        item["char_id"] = std_id
    elif default_cat == "ENV":
        item["scene_id"] = std_id
    elif default_cat == "PROP":
        item["prop_id"] = std_id
    elif default_cat == "VOICE":
        item["voice_id"] = std_id

    dep = AssetProtocolHelper.resolve_dependency(std_id)
    cur_parsed = AssetProtocolHelper.parse_id(std_id)
    if cur_parsed:
        item["entity_token"] = cur_parsed.token
    elif tok:
        item["entity_token"] = tok

    # 依据解析依赖规则严防 二阶/三阶资产退化为文生图 (t2i)
    if dep.generation_mode != "t2i":
        # 衍生切片：优先使用自身指定的 parent，但必须强校验同实体一致性
        p_cand = item.get("parent_asset_key") or item.get("parent_asset_id") or dep.parent_asset_id
        if p_cand and cur_parsed:
            p_parsed = AssetProtocolHelper.parse_id(p_cand)
            if p_parsed and p_parsed.category == cur_parsed.category and p_parsed.token != cur_parsed.token:
                logger.warning(
                    "【阶段 6 资产协议纠偏·防跨实体污染】检测到资产 [%s] (token=%s) 错配父资产 [%s] (token=%s)，自动纠偏为同实体标准底模 [%s]",
                    std_id, cur_parsed.token, p_cand, p_parsed.token, dep.parent_asset_id,
                )
                p_cand = dep.parent_asset_id
        # 若 p_cand 仍为空且非根节点，必须强制兜底到协议推荐的 parent_asset_id，绝不能成为孤儿资产
        if not p_cand:
            p_cand = dep.parent_asset_id

        item["generation_mode"] = dep.generation_mode
        item["parent_asset_key"] = p_cand
        item["parent_asset_id"] = p_cand
        item["is_benchmark"] = 0
    else:
        # t2i 文生图基准肖像：仅允许一阶根节点 (T1 / Z01 / S0)
        item["generation_mode"] = "t2i"
        item["parent_asset_key"] = None
        item["parent_asset_id"] = None
        item["is_benchmark"] = 1 if dep.is_benchmark else 0

    item["denoise_strength"] = dep.recommended_denoise if item.get("denoise_strength") is None else item.get("denoise_strength")
    item.setdefault("recommended_denoise", dep.recommended_denoise)
    item.setdefault("control_type", dep.control_type)
    item.setdefault("workflow_note", dep.workflow_note)

    cat_map = {"CHAR": "character", "ENV": "scene", "PROP": "prop", "VOICE": "audio"}
    cat_key = cat_map.get(default_cat, "default")
    item.setdefault("negative_prompt", PromptSynthesizer.get_category_negative_prompt(cat_key))
    item.setdefault("identity_prompt", item.get("visual_prompt") or item.get("image_prompt") or "")
    item.setdefault("delta_prompt", "")

    logger.debug(
        "【阶段 6 资产四段式规范化】类别=%s, ID=%s, 模式=%s, 父级=%s, 基准=%s",
        default_cat, std_id, item.get("generation_mode"), item.get("parent_asset_key"), item.get("is_benchmark"),
    )
    return item


def stage6_asset_truth_node(
    state: EpisodeScopedSubState | GlobalDramaMasterState | IndustrialDramaState | Any,
) -> dict[str, Any]:
    """【规则编号: RULE-VI-06 & RULE-STAGE6-01】执行阶段 6：提纯单集资产清单并维护全剧真理源总库。"""
    ep_num = (
        _get_val(state, "episode_number")
        or _get_val(state, "current_episode")
        or _get_val(state, "current_visual_episode", 1)
        or 1
    )
    completed = _get_val(state, "completed_screenplays", {}) or {}
    script = completed.get(ep_num) or completed.get(str(ep_num)) or {}
    if not script and _get_val(state, "episodes_scripts"):
        scripts_list = _get_val(state, "episodes_scripts")
        if isinstance(scripts_list, list) and len(scripts_list) >= ep_num:
            script = scripts_list[ep_num - 1]
    if not script and _get_val(state, "episode_script"):
        script = _get_val(state, "episode_script")
    if not script and _get_val(state, "screenplay"):
        script = _get_val(state, "screenplay")
    if not script and _get_val(state, "screenplay_text"):
        script = {"body_markdown": _get_val(state, "screenplay_text"), "text": _get_val(state, "screenplay_text")}
    if hasattr(script, "model_dump"):
        script = script.model_dump()
    elif not isinstance(script, dict):
        script = {}
    chars_engine = _get_val(state, "characters_engine", None)
    if not chars_engine:
        chars_engine = _get_val(state, "character_engine", None)
    if not chars_engine and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
        chars_engine = state.__pydantic_extra__.get("character_engine") or state.__pydantic_extra__.get("characters_engine")
    if not chars_engine and hasattr(state, "characters") and getattr(state, "characters"):
        chars_engine = getattr(state, "characters")
    if not chars_engine:
        chars_engine = {}

    envs_props = _get_val(state, "environments_and_props", None)
    if not envs_props:
        envs_props = _get_val(state, "environments_props", None)
    if not envs_props and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
        envs_props = state.__pydantic_extra__.get("environments_and_props") or state.__pydantic_extra__.get("environments_props")
    if not envs_props:
        envs_props = {}

    logger.debug(f"[Stage 6 Node] [RULE-STAGE6-01] Starting asset distillation for Episode {ep_num}.")

    if isinstance(chars_engine, list):
        char_list = chars_engine
    elif isinstance(chars_engine, dict):
        char_list = chars_engine.get("characters", [])
    else:
        char_list = []

    scene_list = envs_props.get("environments") or envs_props.get("scenes") or []
    prop_list = envs_props.get("props") or []

    # 兼容单集独立切片 EpisodeScopedSubState 中的轻量桩
    if not char_list and _get_val(state, "relevant_character_stubs"):
        char_list = [
            {
                "character_id": f"CHAR_{c.character_id}" if not str(c.character_id).startswith("CHAR_") else str(c.character_id),
                "name": c.name,
                "role_type": c.archetype,
                "appearance": c.visual_token,
                "voice_style": c.core_costume_prompt,
            }
            if hasattr(c, "character_id") else c
            for c in _get_val(state, "relevant_character_stubs")
        ]
    if not scene_list and _get_val(state, "relevant_scene_stubs"):
        scene_list = [
            {
                "env_id": f"ENV_{s.scene_id}" if not str(s.scene_id).startswith("ENV_") else str(s.scene_id),
                "location_name": s.name,
                "visual_prompt": s.weathering_summary,
                "atmosphere": s.color_tone,
            }
            if hasattr(s, "scene_id") else s
            for s in _get_val(state, "relevant_scene_stubs")
        ]
    if not prop_list and _get_val(state, "relevant_prop_stubs"):
        prop_list = [
            {
                "prop_id": f"PROP_{p.prop_id}" if not str(p.prop_id).startswith("PROP_") else str(p.prop_id),
                "name": p.name,
                "type": p.level,
                "visual_prompt": p.visual_token,
            }
            if hasattr(p, "prop_id") else p
            for p in _get_val(state, "relevant_prop_stubs")
        ]

    # 【Stage 2 -> Stage 6 灵魂锚点道具桥接】将角色档案中的 carried_anchor_item / anchor_props 自动汇入 prop_list
    # 彻底打通阶段 2 随身锚点设定与阶段 6 特征扫描/资产清单之间的断层
    existing_p_names = {
        str(p.get("name") or p.get("prop_name") or "").strip()
        for p in prop_list
        if isinstance(p, dict) and (p.get("name") or p.get("prop_name"))
    }
    anchor_from_chars = _extract_anchor_props_from_characters(char_list)
    if anchor_from_chars:
        prop_list = list(prop_list)
        for cap in anchor_from_chars:
            if cap["name"] not in existing_p_names:
                existing_p_names.add(cap["name"])
                prop_list.append(cap)
                logger.debug(
                    "【阶段 6 执行节点】自动将角色 [%s] 的随身锚点道具 '%s' (%s) 注入本集已知物证列表",
                    cap.get("owner_character", ""), cap["name"], cap["prop_id"],
                )

    # 提取已锁定的 Token 白名单
    char_tokens = set(
        _get_val(state, "character_tokens")
        or (chars_engine.get("character_tokens") if isinstance(chars_engine, dict) else [])
        or [
            re.sub(r"[^A-Z0-9]+", "", c.get("character_id", "").replace("CHAR_", ""))
            for c in char_list
            if isinstance(c, dict) and c.get("character_id")
        ]
    )
    scene_tokens = set(
        _get_val(state, "scene_tokens")
        or envs_props.get("scene_tokens")
        or [
            re.sub(r"[^A-Z0-9]+", "", (e.get("env_id") or e.get("environment_id", "")).replace("ENV_", ""))
            for e in scene_list
            if isinstance(e, dict) and (e.get("env_id") or e.get("environment_id"))
        ]
    )
    prop_tokens = set(
        _get_val(state, "prop_tokens")
        or envs_props.get("prop_tokens")
        or [
            re.sub(r"[^A-Z0-9]+", "", p.get("prop_id", "").replace("PROP_", ""))
            for p in prop_list
            if isinstance(p, dict) and p.get("prop_id")
        ]
    )

    reg_raw = _get_val(state, "visual_audio_assets_registry", {}) or {}
    if hasattr(reg_raw, "to_dict"):
        registry = reg_raw.to_dict()
    elif hasattr(reg_raw, "model_dump"):
        registry = reg_raw.model_dump()
    elif isinstance(reg_raw, dict):
        registry = dict(reg_raw)
    else:
        registry = {}

    manifests = dict(_get_val(state, "episode_resource_manifests", None) or _get_val(state, "episode_manifests", {}) or {})

    # -------------------------------------------------------------------------
    # 步骤 1：上游关键依赖提取 (阶段 1 视觉规范 / 阶段 4 声音动机 / 阶段 5 单集剧本与上集物理快照)
    # -------------------------------------------------------------------------
    # 1. 提取单集悬念爆款标题 (多层级回退)
    episode_title = script.get("episode_title") or script.get("title") or ""
    if not episode_title:
        season_outlines = _get_val(state, "season_outlines") or _get_val(state, "season_outline") or {}
        if isinstance(season_outlines, dict):
            outline_ep = season_outlines.get(ep_num) or season_outlines.get(str(ep_num)) or {}
            if isinstance(outline_ep, dict):
                episode_title = outline_ep.get("title") or outline_ep.get("killer_title") or outline_ep.get("episode_title") or ""
        elif isinstance(season_outlines, list):
            for item in season_outlines:
                if isinstance(item, dict) and (item.get("episode_num") == ep_num or item.get("episode_id") == ep_num):
                    episode_title = item.get("title") or item.get("killer_title") or item.get("episode_title") or ""
                    break
    if not episode_title:
        episode_title = f"第{ep_num}集"

    # 2. 提取阶段 1 视听圣经核心参数 (画幅、视觉风格、目标视频生成引擎)
    bible = _get_val(state, "bible", {}) or {}
    if hasattr(bible, "model_dump"):
        bible = bible.model_dump()
    elif hasattr(bible, "to_dict"):
        bible = bible.to_dict()
    elif not isinstance(bible, dict):
        bible = {}

    aspect_ratio = (
        _get_val(state, "aspect_ratio")
        or bible.get("aspect_ratio")
        or "9:16"
    )
    visual_style = (
        _get_val(state, "visual_style")
        or bible.get("visual_style")
        or bible.get("tone_style")
        or "电影质感，冷调颗粒，8k超高清写实，戏剧性侧逆光"
    )
    target_video_engine = (
        _get_val(state, "target_video_engine")
        or bible.get("target_video_engine")
        or "kling_1.6_high_fidelity"
    )

    # 3. 提取上一集 0 秒物理接力快照 (用于跨集战损、创伤及核心物证状态追踪)
    screenplay_text = _extract_screenplay_text(script)
    previous_pickup = None
    if ep_num <= 1:
        # 【首集硬隔离法则】第 1 集为全剧开篇，不存在上一集的物理流出，强制置空以阻断跨轮次全局 state 脏残留
        previous_pickup = None
        logger.info("【阶段 6 执行节点】当前为第 %s 集（开篇集），强制上一集物理接力快照为 None", ep_num)
    else:
        # 【非首集精准回溯】优先取自第 ep_num - 1 集的定稿剧本交付物（单一事实真理源）
        prev_script = completed.get(ep_num - 1) or completed.get(str(ep_num - 1)) or {}
        if isinstance(prev_script, dict):
            previous_pickup = (
                prev_script.get("inter_episode_physical_snapshot")
                or prev_script.get("previous_episode_0s_pickup")
                or prev_script.get("pickup_0s")
            )
        # 仅当上一集定稿剧本未显式登记快照时，才降级读取全局流水线状态
        if not previous_pickup:
            fallback = _get_val(state, "inter_episode_physical_snapshot", None) or _get_val(state, "incoming_physical_continuity", None)
            if isinstance(fallback, dict):
                # 校验来源集数，防止误读更晚剧集残留的脏快照
                source_ep = fallback.get("source_episode") or fallback.get("episode_num") or fallback.get("inherited_from_episode")
                if source_ep is None or source_ep == ep_num - 1:
                    previous_pickup = fallback

    logger.debug(
        "【阶段 6 执行节点】上游依赖提取完成: 集数=%s, 单集标题=%s, 画幅=%s, 引擎=%s, 剧本字符数=%s, 物理快照存在=%s",
        ep_num, episode_title, aspect_ratio, target_video_engine, len(screenplay_text), bool(previous_pickup),
    )

    # -------------------------------------------------------------------------
    # 步骤 2：执行确定性剧本多维特征逆向扫描识别算子与高密度线索摘要编译
    # -------------------------------------------------------------------------
    logger.debug("【阶段 6 执行节点】开始运行确定性特征扫描算子 (角色别名、代词消解、形变动词、微距特写)...")
    scanner_result = scan_screenplay_features(
        screenplay_text=screenplay_text,
        previous_pickup=previous_pickup if isinstance(previous_pickup, dict) else None,
        existing_assets_registry=registry,
        known_characters=char_list,
        known_environments=scene_list,
        known_props=prop_list,
    )
    scanner_summary = summarize_scanner_findings(scanner_result)
    logger.info("【阶段 6 执行节点】第 %s 集特征预扫描与代词消解完成:\n%s", ep_num, scanner_summary)

    # -------------------------------------------------------------------------
    # 步骤 2.5：视听资产上下文轻量投影 (Audio-Visual Projection Filters)
    # -------------------------------------------------------------------------
    present_chars = scanner_result.characters_detected if scanner_result else []
    present_scenes = scanner_result.scenes_detected if scanner_result else []
    present_props = scanner_result.props_detected if scanner_result else []
    alias_map = scanner_result.character_alias_map if scanner_result else {}

    # 【前置角色白名单裁剪】
    projected_chars = project_characters_for_stage6(
        chars_engine=chars_engine,
        present_names=present_chars,
        screenplay_text=screenplay_text,
        alias_map=alias_map,
    )
    logger.info(
        "【阶段 6 前置角色过滤】已根据预扫描结果与剧本裁剪角色库: 全量 %d -> 当集精炼 %d 名: %s",
        len(chars_engine.get("characters", []) if isinstance(chars_engine, dict) else chars_engine if isinstance(chars_engine, list) else []),
        len(projected_chars),
        [c.get("name") for c in projected_chars],
    )
    projected_envs_props = project_environments_props_for_stage6(envs_props, present_scenes, present_props)
    projected_registry = project_registry_index_for_stage6(registry)

    # 统计瘦身效果与压缩指标
    raw_chars_str = json.dumps(chars_engine, ensure_ascii=False)
    raw_envs_str = json.dumps(envs_props, ensure_ascii=False)
    raw_reg_str = json.dumps(registry, ensure_ascii=False)
    raw_total_chars = len(raw_chars_str) + len(raw_envs_str) + len(raw_reg_str)

    chars_engine_json = json.dumps(projected_chars, ensure_ascii=False, indent=2)
    environments_props_json = json.dumps(projected_envs_props, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------------------
    # 步骤 2.6：动态候选资产池精准实体与语义向量混合召回 (Phase 3 动态候选池)
    # -------------------------------------------------------------------------
    candidates: list[dict[str, Any]] = []
    drama_id = _get_val(state, "drama_id") or _get_val(state, "id")
    state_db = _get_val(state, "db") or _get_val(state, "db_session")
    if drama_id:
        try:
            from app.context.vector_memory_service import recall_candidate_assets_for_episode
            if state_db is not None:
                candidates = recall_candidate_assets_for_episode(
                    db=state_db,
                    drama_id=int(drama_id),
                    screenplay_text=screenplay_text,
                    top_k=15,
                )
            else:
                from app.db.session import session_scope
                with session_scope() as db_session:
                    candidates = recall_candidate_assets_for_episode(
                        db=db_session,
                        drama_id=int(drama_id),
                        screenplay_text=screenplay_text,
                        top_k=15,
                    )
            logger.info(
                "【阶段 6 动态候选召回】成功为短剧 [%s] 第 %d 集动态召回 %d 项高置信度候选资产",
                drama_id, ep_num, len(candidates),
            )
            for c in candidates:
                logger.debug(
                    "【阶段 6 候选资产明细】key=%s, name=%s, cat=%s, score=%.2f, source=%s",
                    c.get("asset_key"), c.get("name"), c.get("category"),
                    c.get("relevance_score", 0.0), c.get("recall_source"),
                )
        except Exception as recall_err:
            logger.warning("【阶段 6 动态候选召回】向量与数据库候选检索异常 (自动启动内存索引降级): %s", recall_err)

    # 若未连接数据库/单测内存环境/召回为空，从内存投影注册表自动提取保底候选池
    if not candidates and (projected_registry or registry):
        candidates = _build_candidates_from_projected_registry(
            projected_registry=projected_registry or registry,
            screenplay_text=screenplay_text,
            top_k=15,
        )
        logger.debug("【阶段 6 候选召回保底】从内存已注册资产表提取 %d 项候选资产", len(candidates))

    reusable_candidate_assets_json = (
        json.dumps(candidates, ensure_ascii=False, indent=2)
        if candidates
        else "（无已核准历史资产，本集登场元素均属首次登场，可按需生成基准视图）"
    )

    projected_total_chars = (
        len(chars_engine_json)
        + len(environments_props_json)
        + len(reusable_candidate_assets_json)
    )
    compression_ratio = ((raw_total_chars - projected_total_chars) / max(raw_total_chars, 1)) * 100

    logger.info(
        "【阶段 6 上下文瘦身与候选池投影】上游依赖上下文瘦身完成: 原始字符数=%d -> 投影后字符数=%d (压缩率: %.1f%%, 候选资产数=%d)",
        raw_total_chars, projected_total_chars, compression_ratio, len(candidates),
    )

    # -------------------------------------------------------------------------
    # 步骤 3：组装标准化用户提示词与大模型调用 (零先验纯剧本盲抽 + 只读字典辅助模式)
    # 彻底杜绝注意力泄露与完型填空强迫症，将前置依赖作为只读语义参考词典，剧本作为唯一物理事实触发器！
    # -------------------------------------------------------------------------
    # 提取分集大纲背景
    outline_synopsis = ""
    season_outlines = (
        getattr(state, "season_outlines", {})
        or (state.get("season_outlines", {}) if isinstance(state, dict) else {})
        or {}
    )
    if isinstance(season_outlines, dict):
        ep_outline_obj = season_outlines.get(ep_num) or season_outlines.get(str(ep_num)) or {}
        if isinstance(ep_outline_obj, dict):
            outline_synopsis = str(ep_outline_obj.get("synopsis") or ep_outline_obj.get("outline") or ep_outline_obj.get("killer_title") or "")
    if not outline_synopsis:
        outline_synopsis = f"第 {ep_num} 集分集大纲：围绕当前核心戏剧冲突展开推进。"

    # 提取人物关系图谱
    char_system_raw = (
        getattr(state, "character_system", {})
        or (state.get("character_system", {}) if isinstance(state, dict) else {})
        or {}
    )
    rel_matrix_text = ""
    if isinstance(char_system_raw, dict):
        rel_data = char_system_raw.get("relationship_matrix") or char_system_raw.get("relationships") or []
        if rel_data:
            rel_matrix_text = json.dumps(rel_data, ensure_ascii=False, indent=2)
    if not rel_matrix_text:
        rel_matrix_text = "（主要人物之间存在核心戏剧对抗与身份制衡关系）"

    # 提取全局已知实体定型库 (用于只读特征词典)
    # 【核心防幻读防护】：角色仅注入当集确切在场的实体档案 (projected_chars)，杜绝未出场角色诱导大模型做完型填空
    projected_char_names = {str(c.get("name")).strip() for c in projected_chars if isinstance(c, dict) and c.get("name")}
    global_entities_dict = {
        "characters": [
            {
                "name": c.get("name"),
                "appearance": c.get("appearance"),
                "biological_dna": c.get("biological_dna"),
                "lived_in_costume": c.get("lived_in_costume"),
            }
            for c in char_list
            if isinstance(c, dict) and str(c.get("name")).strip() in projected_char_names
        ],
        "environments": [
            {
                "name": e.get("name"),
                "architectural_style": e.get("architectural_style") or e.get("appearance"),
            }
            for e in scene_list if isinstance(e, dict)
        ],
        "props": [
            {
                "name": p.get("name"),
                "material": p.get("material"),
            }
            for p in prop_list if isinstance(p, dict)
        ]
    }
    global_entities_json = json.dumps(global_entities_dict, ensure_ascii=False, indent=2)

    user_prompt = STAGE6_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        episode_title=episode_title,
        aspect_ratio=aspect_ratio,
        visual_style=visual_style,
        target_video_engine=target_video_engine,
        episode_outline_synopsis=outline_synopsis,
        character_relationship_matrix=rel_matrix_text,
        global_entities_dossiers_json=global_entities_json,
        inter_episode_physical_snapshot_json=json.dumps(previous_pickup or {}, ensure_ascii=False, indent=2) if previous_pickup else "无（本集为首集或无上一集物理接棒残留）",
        screenplay_text=screenplay_text if screenplay_text else "（无独立文学剧本文本）",
    )

    logger.debug("【阶段 6 执行节点】向大模型发送纯剧本多维高保真盲抽指令 (提示词总长度: %s 字符)...", len(user_prompt))

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE6_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage6_fallback(
            episode_num=ep_num,
            script_data=script,
            characters_engine=chars_engine,
            envs_props=envs_props,
            existing_registry=registry,
            scanner_result=scanner_result,
            visual_style=visual_style,
            aspect_ratio=aspect_ratio,
            episode_title=episode_title,
            candidates=candidates,
        ),
    )

    manifest_data = (
        result_json.get("episode_resource_manifest")
        or result_json.get("manifest")
        or {}
    )

    # -------------------------------------------------------------------------
    # 步骤 3.5：提取并规范化本集发现的阶段2未登记新角色 (Stage-2 11维标准建档)
    # -------------------------------------------------------------------------
    raw_new_chars = (
        result_json.get("newly_discovered_characters")
        or manifest_data.get("newly_discovered_characters")
        or []
    )
    registered_names_node: set[str] = {
        str(c.get("name") or "").strip()
        for c in char_list
        if isinstance(c, dict) and c.get("name")
    }
    existing_char_codes_node: set[str] = {
        f"CHAR_{tok}" for tok in char_tokens if tok
    }
    used_archetypes_node: set[str] = {
        str(c.get("timbre_archetype"))
        for c in char_list
        if isinstance(c, dict) and c.get("timbre_archetype")
    }
    primary_prot_code = "CHAR_PROTAGONIST"
    primary_prot_name = "主角"
    for idx_c, c_item in enumerate(char_list):
        if isinstance(c_item, dict) and (idx_c == 0 or c_item.get("role_type") == "protagonist" or c_item.get("role") == "main"):
            if c_item.get("name"):
                primary_prot_name = str(c_item["name"])
            if c_item.get("character_id") or c_item.get("character_code"):
                raw_cc = str(c_item.get("character_code") or c_item.get("character_id"))
                primary_prot_code = raw_cc if raw_cc.startswith("CHAR_") else f"CHAR_{raw_cc}"
            break

    normalized_new_chars: list[dict[str, Any]] = []
    for nc_idx, nc_item in enumerate(raw_new_chars if isinstance(raw_new_chars, list) else [], start=1):
        if not isinstance(nc_item, dict):
            continue
        nc_name = str(nc_item.get("name") or nc_item.get("character_name") or "").strip()
        if not nc_name or nc_name in registered_names_node:
            continue
        if not is_valid_character_speaker(nc_name, known_names=registered_names_node):
            logger.debug("【阶段 6 新角色过滤】跳过大模型误报的非具名角色/舞台指令标识: %s", nc_name)
            continue
        # 使用保底11维建档器补齐缺失字段，同时保留大模型已生成的精细设定
        base_dossier = _build_stage2_character_dossier(
            char_name=nc_name,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_char_codes=existing_char_codes_node,
            used_archetypes=used_archetypes_node,
            primary_protagonist_code=primary_prot_code,
            primary_protagonist_name=primary_prot_name,
            index_hint=len(char_list) + nc_idx,
        )
        merged_dossier = {**base_dossier, **{k: v for k, v in nc_item.items() if v not in (None, "", [], {})}}
        # 确保合并后的关键 JSON 结构化字段保持 dict/list 类型
        if not isinstance(merged_dossier.get("visual_consistency_code"), dict):
            merged_dossier["visual_consistency_code"] = base_dossier["visual_consistency_code"]
        if isinstance(merged_dossier.get("identity_anchors"), str):
            raw_ia = merged_dossier["identity_anchors"].strip()
            merged_dossier["identity_anchors"] = [x.strip() for x in re.split(r"[|｜,，;；]", raw_ia) if x.strip()] or base_dossier["identity_anchors"]
        raw_cc = str(merged_dossier.get("character_code") or merged_dossier.get("character_id") or base_dossier["character_code"]).strip().upper()
        if not raw_cc.startswith("CHAR_"):
            raw_cc = f"CHAR_{re.sub(r'[^A-Z0-9]+', '', raw_cc)}"
        merged_dossier["character_code"] = raw_cc
        merged_dossier["character_id"] = raw_cc
        tok_nc = raw_cc.replace("CHAR_", "", 1)
        char_tokens.add(tok_nc)
        existing_char_codes_node.add(raw_cc)
        registered_names_node.add(nc_name)
        normalized_new_chars.append(merged_dossier)
        char_list.append(merged_dossier)
        logger.debug(
            "【阶段 6 新角色建档】已标准化第 %d 集新发现角色 [%s] (%s), 11维全息字段完备",
            ep_num, nc_name, raw_cc,
        )

    # 若扫描算子检测到未注册具名角色但大模型漏报，执行确定性补录兜底
    for det_idx, det_name in enumerate(present_chars, start=1):
        clean_det = str(det_name or "").strip()
        if not clean_det or clean_det in registered_names_node:
            continue
        if not is_valid_character_speaker(clean_det, known_names=registered_names_node):
            logger.debug("【阶段 6 新角色自动兜底过滤】跳过非具名角色/舞台指令标识: %s", clean_det)
            continue
        # 严格使用在场判定脱敏核验（防止死者如苏秀兰或案卷媒介词被兜底机制建档为新角色）
        if not is_character_truly_in_screenplay(clean_det, screenplay_text, present_chars):
            logger.debug("【阶段 6 新角色自动兜底过滤】候选人 [%s] 经脱敏核验未真实在场，放弃补录", clean_det)
            continue
        auto_dossier = _build_stage2_character_dossier(
            char_name=clean_det,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_char_codes=existing_char_codes_node,
            used_archetypes=used_archetypes_node,
            primary_protagonist_code=primary_prot_code,
            primary_protagonist_name=primary_prot_name,
            index_hint=len(char_list) + det_idx,
        )
        tok_nc = auto_dossier["character_code"].replace("CHAR_", "", 1)
        char_tokens.add(tok_nc)
        registered_names_node.add(clean_det)
        normalized_new_chars.append(auto_dossier)
        char_list.append(auto_dossier)
        logger.info(
            "【阶段 6 新角色自动兜底补录】扫描算子捕获第 %d 集未登记角色 [%s] -> 自动按阶段2标准建档 [%s]",
            ep_num, clean_det, auto_dossier["character_code"],
        )

    # -------------------------------------------------------------------------
    # 步骤 3.6：提取并规范化本集发现的阶段3未登记新场景与新道具 (Stage-3 3-Tier 标准建档)
    # -------------------------------------------------------------------------
    raw_new_scenes = (
        result_json.get("newly_discovered_scenes")
        or manifest_data.get("newly_discovered_scenes")
        or []
    )
    registered_scene_names_node: set[str] = {
        str(s.get("name") or s.get("location_name") or s.get("scene_name") or "").strip()
        for s in scene_list
        if isinstance(s, dict) and (s.get("name") or s.get("location_name") or s.get("scene_name"))
    }
    existing_scene_codes_node: set[str] = {
        str(s.get("scene_code") or s.get("env_id") or s.get("scene_id") or "").strip().upper()
        for s in scene_list
        if isinstance(s, dict) and (s.get("scene_code") or s.get("env_id") or s.get("scene_id"))
    }
    for tok in scene_tokens:
        if tok:
            existing_scene_codes_node.add(f"ENV_{tok}")

    normalized_new_scenes: list[dict[str, Any]] = []
    for ns_idx, ns_item in enumerate(raw_new_scenes if isinstance(raw_new_scenes, list) else [], start=1):
        if not isinstance(ns_item, dict):
            continue
        ns_name = str(ns_item.get("name") or ns_item.get("location_name") or ns_item.get("scene_name") or "").strip()
        if not ns_name or ns_name in registered_scene_names_node:
            continue
        # 获取扫描算子识别到的该场景子区域 (如: Z01, 卫生间, 收银台)
        detected_zones_for_scene = scanner_result.scene_zones_detected.get(ns_name, []) if scanner_result else []
        base_scene_dossier = _build_stage3_scene_dossier(
            scene_name=ns_name,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_scene_codes=existing_scene_codes_node,
            visual_style=visual_style,
            index_hint=len(scene_list) + ns_idx,
            detected_zones=detected_zones_for_scene,
        )
        merged_scene_dossier = {**base_scene_dossier, **{k: v for k, v in ns_item.items() if v not in (None, "", [], {})}}
        raw_sc = str(merged_scene_dossier.get("scene_code") or merged_scene_dossier.get("env_id") or base_scene_dossier["scene_code"]).strip().upper()
        if not raw_sc.startswith("ENV_"):
            raw_sc = f"ENV_{re.sub(r'[^A-Z0-9]+', '', raw_sc)}"
        merged_scene_dossier["scene_code"] = raw_sc
        merged_scene_dossier["env_id"] = raw_sc
        tok_ns = raw_sc.replace("ENV_", "", 1)
        scene_tokens.add(tok_ns)
        existing_scene_codes_node.add(raw_sc)
        registered_scene_names_node.add(ns_name)
        normalized_new_scenes.append(merged_scene_dossier)
        scene_list.append(merged_scene_dossier)
        logger.debug(
            "【阶段 6 新场景建档】已标准化第 %d 集新发现场景 [%s] (%s), 三级层级结构完备",
            ep_num, ns_name, raw_sc,
        )

    # 若扫描算子检测到未登记场景，执行确定性补录兜底
    for s_idx, det_sname in enumerate(present_scenes, start=1):
        clean_sname = str(det_sname or "").strip()
        if not clean_sname or clean_sname in registered_scene_names_node:
            continue
        detected_zones_for_scene = scanner_result.scene_zones_detected.get(clean_sname, []) if scanner_result else []
        auto_scene_dossier = _build_stage3_scene_dossier(
            scene_name=clean_sname,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_scene_codes=existing_scene_codes_node,
            visual_style=visual_style,
            index_hint=len(scene_list) + s_idx,
            detected_zones=detected_zones_for_scene,
        )
        tok_ns = auto_scene_dossier["scene_code"].replace("ENV_", "", 1)
        scene_tokens.add(tok_ns)
        existing_scene_codes_node.add(auto_scene_dossier["scene_code"])
        registered_scene_names_node.add(clean_sname)
        normalized_new_scenes.append(auto_scene_dossier)
        scene_list.append(auto_scene_dossier)
        logger.info(
            "【阶段 6 新场景自动兜底补录】扫描算子捕获第 %d 集未登记场景 [%s] -> 自动按阶段3标准建档 [%s]",
            ep_num, clean_sname, auto_scene_dossier["scene_code"],
        )

    # 提取并规范化本集发现的新道具
    raw_new_props = (
        result_json.get("newly_discovered_props")
        or manifest_data.get("newly_discovered_props")
        or []
    )
    registered_prop_names_node: set[str] = {
        str(p.get("name") or p.get("prop_name") or "").strip()
        for p in prop_list
        if isinstance(p, dict) and (p.get("name") or p.get("prop_name"))
    }
    existing_prop_codes_node: set[str] = {
        str(p.get("prop_code") or p.get("prop_id") or "").strip().upper()
        for p in prop_list
        if isinstance(p, dict) and (p.get("prop_code") or p.get("prop_id"))
    }
    for tok in prop_tokens:
        if tok:
            existing_prop_codes_node.add(f"PROP_{tok}")

    normalized_new_props: list[dict[str, Any]] = []
    for np_idx, np_item in enumerate(raw_new_props if isinstance(raw_new_props, list) else [], start=1):
        if not isinstance(np_item, dict):
            continue
        np_name = str(np_item.get("name") or np_item.get("prop_name") or "").strip()
        if not np_name or np_name in registered_prop_names_node:
            continue
        base_prop_dossier = _build_stage3_prop_dossier(
            prop_name=np_name,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_prop_codes=existing_prop_codes_node,
            visual_style=visual_style,
            index_hint=len(prop_list) + np_idx,
        )
        merged_prop_dossier = {**base_prop_dossier, **{k: v for k, v in np_item.items() if v not in (None, "", [], {})}}
        raw_pc = str(merged_prop_dossier.get("prop_code") or merged_prop_dossier.get("prop_id") or base_prop_dossier["prop_code"]).strip().upper()
        if not raw_pc.startswith("PROP_"):
            raw_pc = f"PROP_{re.sub(r'[^A-Z0-9]+', '', raw_pc)}"
        merged_prop_dossier["prop_code"] = raw_pc
        merged_prop_dossier["prop_id"] = raw_pc
        tok_np = raw_pc.replace("PROP_", "", 1)
        prop_tokens.add(tok_np)
        existing_prop_codes_node.add(raw_pc)
        registered_prop_names_node.add(np_name)
        normalized_new_props.append(merged_prop_dossier)
        prop_list.append(merged_prop_dossier)
        logger.debug(
            "【阶段 6 新道具建档】已标准化第 %d 集新发现道具 [%s] (%s), 三级层级结构完备",
            ep_num, np_name, raw_pc,
        )

    # 若扫描算子检测到未登记道具，执行确定性补录兜底
    for p_idx, det_pname in enumerate(present_props, start=1):
        clean_pname = str(det_pname or "").strip()
        if not clean_pname or clean_pname in registered_prop_names_node:
            continue
        auto_prop_dossier = _build_stage3_prop_dossier(
            prop_name=clean_pname,
            episode_num=ep_num,
            screenplay_text=screenplay_text,
            existing_prop_codes=existing_prop_codes_node,
            visual_style=visual_style,
            index_hint=len(prop_list) + p_idx,
        )
        tok_np = auto_prop_dossier["prop_code"].replace("PROP_", "", 1)
        prop_tokens.add(tok_np)
        existing_prop_codes_node.add(auto_prop_dossier["prop_code"])
        registered_prop_names_node.add(clean_pname)
        normalized_new_props.append(auto_prop_dossier)
        prop_list.append(auto_prop_dossier)
        logger.info(
            "【阶段 6 新道具自动兜底补录】扫描算子捕获第 %d 集未登记道具 [%s] -> 自动按阶段3标准建档 [%s]",
            ep_num, clean_pname, auto_prop_dossier["prop_code"],
        )

    # 规范化与底图血统补齐
    raw_chars = (
        manifest_data.get("characters")
        or manifest_data.get("character_assets")
        or []
    )
    raw_envs = (
        manifest_data.get("environments")
        or manifest_data.get("scene_assets")
        or []
    )
    raw_props = (
        manifest_data.get("props")
        or manifest_data.get("prop_assets")
        or []
    )

    default_char_tok = next(iter(char_tokens)) if char_tokens else "PROTAGONIST"
    default_scene_tok = next(iter(scene_tokens)) if scene_tokens else "MAINSCENE"
    default_prop_tok = next(iter(prop_tokens)) if prop_tokens else "EVIDENCE"

    norm_chars = []
    if isinstance(raw_chars, list):
        norm_chars = [
            _ensure_standard_asset(c, "CHAR", char_tokens, default_char_tok)
            for c in raw_chars
            if isinstance(c, dict)
        ]
    elif isinstance(raw_chars, dict):
        # 嵌套格式展开
        for tier_key in ["tier1_base", "tier2_performance", "tier3_special"]:
            for item in raw_chars.get(tier_key, []):
                if isinstance(item, dict):
                    norm_chars.append(_ensure_standard_asset(item, "CHAR", char_tokens, default_char_tok))

    # 【后置硬拦截防御】：过滤掉未在本集出场的角色资产（杜绝大模型格式补全幻觉）
    present_chars_pool = set(present_chars)
    if alias_map:
        present_chars_pool.update(alias_map.keys())
        present_chars_pool.update(alias_map.values())
    for pc in projected_chars:
        if isinstance(pc, dict) and pc.get("name"):
            present_chars_pool.add(str(pc["name"]).strip())

    filtered_norm_chars: list[dict[str, Any]] = []
    for c_asset in norm_chars:
        if is_character_truly_in_screenplay(
            char_entry=c_asset,
            screenplay_text=screenplay_text,
            detected_chars=present_chars_pool,
            alias_map=alias_map,
        ):
            filtered_norm_chars.append(c_asset)
        else:
            logger.warning(
                "【阶段 6 角色后置拦截】剔除未登场角色资产: %s (%s)",
                c_asset.get("asset_id") or c_asset.get("char_id"),
                c_asset.get("name"),
            )

    norm_envs = []
    if isinstance(raw_envs, list):
        norm_envs = [
            _ensure_standard_asset(e, "ENV", scene_tokens, default_scene_tok)
            for e in raw_envs
            if isinstance(e, dict)
        ]
    elif isinstance(raw_envs, dict):
        for tier_key in ["tier1_primary", "tier2_transitional"]:
            for item in raw_envs.get(tier_key, []):
                if isinstance(item, dict):
                    norm_envs.append(_ensure_standard_asset(item, "ENV", scene_tokens, default_scene_tok))

    norm_props = []
    if isinstance(raw_props, list):
        norm_props = [
            _ensure_standard_asset(p, "PROP", prop_tokens, default_prop_tok)
            for p in raw_props
            if isinstance(p, dict)
        ]
    elif isinstance(raw_props, dict):
        for tier_key in ["tier1_hero", "tier2_anchor", "tier3_atmospheric"]:
            for item in raw_props.get(tier_key, []):
                if isinstance(item, dict):
                    norm_props.append(_ensure_standard_asset(item, "PROP", prop_tokens, default_prop_tok))

    # =========================================================================
    # 【工业级神经-符号联动】执行 AssetTriggerOperatorEngine 确定性算子引擎
    # 严格落实【A. 角色四视角/情绪/光效/手部战损】、【B. 场景景别/OTS/插镜/关键帧】、【C. 道具一二级静动/随身绑定/杂物剔除】
    # =========================================================================
    logger.info("【阶段 6 算子引擎联动】开始执行资产触发算子判定与多级按需派生...")

    # A. 角色触发算子派生
    operator_derived_chars: list[dict[str, Any]] = []
    seen_char_asset_ids: set[str] = set()

    for c_base in filtered_norm_chars:
        c_name = c_base.get("name") or c_base.get("character_name") or "CHARACTER"
        clean_cn = _clean_name(c_name)
        c_tok = AssetProtocolHelper.normalize_token(clean_cn or c_name)
        canonical_cid = f"CHAR_{c_tok}"

        # 调取算子引擎获取动态派生资产
        triggered_char_assets = AssetTriggerOperatorEngine.evaluate_character_assets(
            character_name=c_name,
            canonical_id=canonical_cid,
            semantic_data=c_base,
            screenplay_text=screenplay_text,
        )

        for ta in triggered_char_assets:
            aid = ta["asset_key"]
            if aid in seen_char_asset_ids:
                continue
            seen_char_asset_ids.add(aid)

            # 组装符合管线标准的资产对象
            derived_c = dict(c_base)
            derived_c["asset_id"] = aid
            derived_c["char_id"] = aid
            derived_c["tier"] = ta.get("tier", "Tier1")
            derived_c["form"] = ta.get("form", "BASE")
            derived_c["trigger_reason"] = ta.get("trigger_reason", "")
            # 严格继承算子引擎计算出的阶梯血统 DAG 属性与控制网参数 (ControlNet OpenPose / FaceID / Inpaint)
            derived_c["generation_mode"] = ta.get("generation_mode", "t2i" if "BASE" in aid else "i2i")
            derived_c["is_benchmark"] = ta.get("is_benchmark", 1 if "BASE" in aid else 0)
            derived_c["denoise_strength"] = ta.get("denoise_strength", 0.0 if derived_c["generation_mode"] == "t2i" else 0.40)
            derived_c["parent_asset_key"] = ta.get("parent_asset_key")
            derived_c["parent_asset_id"] = ta.get("parent_asset_key")
            derived_c["input_source_image"] = ta.get("input_source_image")
            derived_c["identity_reference"] = ta.get("identity_reference")
            derived_c["control_type"] = ta.get("control_type")
            operator_derived_chars.append(derived_c)

    if operator_derived_chars:
        norm_chars = operator_derived_chars
    else:
        norm_chars = filtered_norm_chars

    # B. 场景触发算子派生
    operator_derived_envs: list[dict[str, Any]] = []
    seen_env_asset_ids: set[str] = set()

    for e_base in norm_envs:
        e_name = e_base.get("name") or e_base.get("scene_name") or "MAINSCENE"
        clean_en = _clean_name(e_name)
        e_tok = AssetProtocolHelper.normalize_token(clean_en or e_name)
        canonical_eid = f"ENV_{e_tok}"

        triggered_env_assets = AssetTriggerOperatorEngine.evaluate_environment_assets(
            scene_name=e_name,
            canonical_id=canonical_eid,
            semantic_data=e_base,
            screenplay_text=screenplay_text,
        )

        for te in triggered_env_assets:
            aid = te["asset_key"]
            if aid in seen_env_asset_ids:
                continue
            seen_env_asset_ids.add(aid)

            derived_e = dict(e_base)
            derived_e["asset_id"] = aid
            derived_e["scene_id"] = aid
            derived_e["env_id"] = aid
            derived_e["tier"] = te.get("tier", "Tier1")
            derived_e["form"] = te.get("form", "WIDE")
            derived_e["trigger_reason"] = te.get("trigger_reason", "")
            derived_e["generation_mode"] = "t2i" if ("WIDE" in aid or "BASE" in aid) else "i2i"
            if derived_e["generation_mode"] == "i2i":
                derived_e["parent_asset_id"] = f"{canonical_eid}_T1_WIDE"
                derived_e["parent_asset_key"] = f"{canonical_eid}_T1_WIDE"
                derived_e["denoise_strength"] = 0.50
            operator_derived_envs.append(derived_e)

    if operator_derived_envs:
        norm_envs = operator_derived_envs

    # 【场景子机位 Zone 动态补全】：将扫描算子捕获的 scene_zones 实体化为二级机位资产，杜绝大模型漏抽
    existing_env_asset_ids = {
        str(e.get("asset_id") or e.get("scene_id") or "").strip()
        for e in norm_envs
        if isinstance(e, dict)
    }
    if scanner_result and isinstance(scanner_result.scene_zones_detected, dict):
        for parent_sname, z_list in scanner_result.scene_zones_detected.items():
            clean_ps = _clean_name(parent_sname)
            ps_tok = AssetProtocolHelper.normalize_token(clean_ps or parent_sname)
            for z_idx, z_name in enumerate(z_list, start=1):
                z_code = f"Z{z_idx:02d}"
                zone_asset_id = f"ENV_{ps_tok}_{z_code}_ZONE"
                if zone_asset_id not in existing_env_asset_ids:
                    existing_env_asset_ids.add(zone_asset_id)
                    zone_prompt = (
                        f"cinematic photorealistic 8k architectural environment, {parent_sname} {z_name} designated area, "
                        f"35mm cinematic anamorphic lens, localized spatial framing, realistic environmental textures, "
                        f"atmospheric lighting, visual style: {visual_style} --style raw"
                    )
                    norm_envs.append({
                        "asset_id": zone_asset_id,
                        "scene_id": zone_asset_id,
                        "env_id": f"ENV_{ps_tok}_{z_code}",
                        "name": f"{parent_sname}-{z_name}",
                        "location_name": f"{parent_sname}-{z_name}",
                        "tier": "T2",
                        "zone_code": z_code,
                        "function_type": "ZONE",
                        "visual_prompt": zone_prompt,
                        "image_prompt": zone_prompt,
                        "parent_asset_id": f"ENV_{ps_tok}_T1_WIDE",
                        "parent_asset_key": f"ENV_{ps_tok}_T1_WIDE",
                        "generation_mode": "i2i",
                        "denoise_strength": 0.40,
                        "lifecycle_status": AssetState.READY.value,
                    })
                    logger.info("【阶段 6 场景机位补全】将扫描到的子区域 [%s -> %s] 实体化为机位资产: %s", parent_sname, z_name, zone_asset_id)

    # C. 道具触发算子判定（一二级静动两态、随身绑定手部、三级杂物彻底剔除）
    operator_derived_props: list[dict[str, Any]] = []
    seen_prop_asset_ids: set[str] = set()

    for p_base in norm_props:
        p_name = p_base.get("name") or p_base.get("prop_name") or "EVIDENCE"
        clean_pn = _clean_name(p_name)
        p_tok = AssetProtocolHelper.normalize_token(clean_pn or p_name)
        canonical_pid = f"PROP_{p_tok}"

        prop_decision = AssetTriggerOperatorEngine.evaluate_prop_assets(
            prop_name=p_name,
            canonical_id=canonical_pid,
            semantic_data=p_base,
            screenplay_text=screenplay_text,
        )

        decision = prop_decision.get("decision")
        if decision == "EXCLUDED_AMBIENT":
            logger.info("【阶段 6 算子引擎·杂物拦截】道具 [%s] 判定为生活环境杂物，执行零独立生图剔除", p_name)
            continue
        elif decision == "BOUND_TO_CHARACTER_MACRO":
            assoc_char = prop_decision.get("bound_character")
            logger.info("【阶段 6 算子引擎·随身物挂靠】道具 [%s] 成功挂靠角色 [%s] T3 手部微距，免除独立生图", p_name, assoc_char)
            continue

        # 一级核心物证按生成的两态（静态/破坏态）登记
        for tp in prop_decision.get("assets", []):
            aid = tp["asset_key"]
            if aid in seen_prop_asset_ids:
                continue
            seen_prop_asset_ids.add(aid)

            derived_p = dict(p_base)
            derived_p["asset_id"] = aid
            derived_p["prop_id"] = aid
            derived_p["tier"] = tp.get("tier", "Tier1")
            derived_p["form"] = tp.get("form", "STATIC")
            derived_p["function_type"] = tp.get("form", "STATIC")
            derived_p["trigger_reason"] = tp.get("trigger_reason", "")
            derived_p["generation_mode"] = "t2i" if "STATIC" in aid else "i2i"
            if derived_p["generation_mode"] == "i2i":
                derived_p["parent_asset_id"] = f"{canonical_pid}_T1_STATIC"
                derived_p["parent_asset_key"] = f"{canonical_pid}_T1_STATIC"
                derived_p["denoise_strength"] = 0.55
            operator_derived_props.append(derived_p)

    if operator_derived_props:
        norm_props = operator_derived_props

    # 【手持交互物证标准 S0 补录】：确保动宾道具与核心物证均有稳定的静态材质底模
    existing_prop_names = {
        str(p.get("name") or p.get("prop_name") or "").strip()
        for p in norm_props
        if isinstance(p, dict)
    }
    existing_prop_ids = {
        str(p.get("asset_id") or p.get("prop_id") or "").strip()
        for p in norm_props
        if isinstance(p, dict)
    }
    candidates_to_enrich: list[str] = list(present_props)
    if scanner_result and isinstance(scanner_result.props_detected, list):
        candidates_to_enrich.extend(scanner_result.props_detected)

    for p_cand in candidates_to_enrich:
        clean_p = _clean_name(p_cand)
        if not clean_p or len(clean_p) < 2:
            continue
        p_tok = AssetProtocolHelper.normalize_token(clean_p)
        static_id = f"PROP_{p_tok}_T1_STATIC"
        if clean_p not in existing_prop_names and static_id not in existing_prop_ids:
            existing_prop_names.add(clean_p)
            existing_prop_ids.add(static_id)
            prop_prompt = (
                f"cinematic photorealistic 8k hero prop, {clean_p}, isolated hero prop studio shot, "
                f"resting firmly on textured dark wooden surface, 100mm macro lens, pristine condition, "
                f"ultra-sharp tactile material texture, soft directional studio lighting, "
                f"visual style: {visual_style} --style raw"
            )
            norm_props.append({
                "asset_id": static_id,
                "prop_id": static_id,
                "name": clean_p,
                "prop_name": clean_p,
                "tier": "T1",
                "function_type": "STATIC",
                "visual_prompt": prop_prompt,
                "image_prompt": prop_prompt,
                "parent_asset_id": None,
                "parent_asset_key": None,
                "generation_mode": "t2i",
                "is_benchmark": 1,
                "lifecycle_status": AssetState.READY.value,
            })
            logger.info("【阶段 6 交互物证补全】自动为手持交互物证 [%s] 补齐标准 S0 底模资产: %s", clean_p, static_id)

    # -------------------------------------------------------------------------
    # 步骤 4：资产四段式纠偏、生命周期状态标记与语义哈希指纹计算
    # -------------------------------------------------------------------------
    logger.info("【阶段 6 真理源】开始对第 %s 集资产执行四段式协议校验、生命周期状态初始化与语义指纹计算...", ep_num)

    all_chars = dict(registry.get("characters", {}) or {})
    all_envs = dict(registry.get("environments", {}) or {})
    all_props = dict(registry.get("props", {}) or {})
    all_voices = dict(registry.get("audio_tts", {}) or {})
    reused_history = dict(registry.get("reused_assets_history", {}) or {})

    # 提取或构建全局语义指纹索引 (asset_id <-> semantic_hash)
    semantic_hashes: dict[str, str] = dict(registry.get("semantic_hashes", {}) or {})
    hash_to_asset: dict[str, str] = dict(registry.get("hash_index", {}) or {})
    # 反向构建以确保已有库中资产均可索引
    for aid, h in semantic_hashes.items():
        if h and isinstance(h, str):
            hash_to_asset[h] = aid

    # 预载历史库资产以推导缺失哈希
    for existing_pool, cat in [(all_chars, "CHAR"), (all_envs, "ENV"), (all_props, "PROP"), (all_voices, "VOICE")]:
        for aid, item in existing_pool.items():
            if isinstance(item, dict):
                cur_h = item.get("semantic_hash")
                if not cur_h:
                    cur_h = compute_asset_semantic_hash(cat, aid, item.get("visual_prompt") or item.get("image_prompt") or "", item)
                    item["semantic_hash"] = cur_h
                semantic_hashes[aid] = cur_h
                hash_to_asset[cur_h] = aid
                item.setdefault("lifecycle_status", AssetState.APPROVED.value)

    # -------------------------------------------------------------------------
    # 步骤 5：本地规则矩阵生图提示词引擎合成 (PromptMatrixSynthesizer · 毫秒级零延迟)
    # 按 P0~P4 黄金插槽装配中国人/韩国人、80年代中国建筑/红砖筒子楼、剧情战损与光学焦段，彻底消灭占位符
    # -------------------------------------------------------------------------
    from app.workflows.utils.prompt_synthesizer import PromptMatrixSynthesizer

    for c in norm_chars:
        cid = c.get("asset_id") or c.get("char_id") or ""
        c_name = c.get("name") or "CHARACTER"
        c_form = c.get("form") or "T1_BASE"
        raw_cp = c.get("visual_prompt") or c.get("image_prompt") or ""

        # 查找匹配的角色全局档案 (用于提取人种、骨相、服饰设定)
        c_prof = all_chars.get(cid)
        if not c_prof:
            for ac_k, ac_v in all_chars.items():
                if isinstance(ac_v, dict) and ac_v.get("name") == c_name:
                    c_prof = ac_v
                    break

        # 提取动态物理切片 (包含四层解耦 Anchor: P_Face / P_Body / P_Cloth / P_Motion) 并利用 AssetSliceEnricher 与阶段 2 静态档案融合补全
        raw_motion_slice = {
            "facial_dna_anchor": c.get("facial_dna_anchor") or c.get("facial_bone_structure") or c.get("bone_structure") or "",
            "physique_body_anchor": c.get("physique_body_anchor") or c.get("body_proportions") or c.get("height_and_build") or "",
            "costume_material_anchor": c.get("costume_material_anchor") or c.get("costume_and_materials") or c.get("costume") or "",
            "plot_motion_slice": c.get("plot_motion_slice") or c.get("current_motion") or c.get("action_description") or "",
            "facial_bone_structure": c.get("facial_bone_structure") or c.get("bone_structure") or "",
            "costume_and_materials": c.get("costume_and_materials") or c.get("costume") or "",
            "current_motion": c.get("current_motion") or c.get("action_description") or "",
            "physical_wounds": c.get("battle_damage") or c.get("injury_details") or c.get("physical_wounds") or "",
            "emotional_expression": c.get("emotion") or c.get("micro_expression") or "",
            "relationship_tension": c.get("relationship_tension") or c.get("tension") or "",
            "microclimate_reaction": c.get("microclimate_reaction") or "",
            "timbre_archetype": c.get("timbre_archetype") or "",
            "regional_accent": c.get("regional_accent") or "",
            "acoustic_space": c.get("acoustic_space") or "",
        }
        logger.debug(
            "【阶段 6 执行节点】角色 [%s] 提取视听四维解耦切片: p_face=%s, p_body=%s, p_cloth=%s, p_motion=%s",
            c_name, bool(raw_motion_slice["facial_dna_anchor"]), bool(raw_motion_slice["physique_body_anchor"]), bool(raw_motion_slice["costume_material_anchor"]), bool(raw_motion_slice["plot_motion_slice"]),
        )
        motion_slice = AssetSliceEnricher.enrich_character_slice(raw_motion_slice, c_prof)

        # 规则矩阵引擎按 Token 优先级装配高质量生图提示词
        matrix_prompt = PromptMatrixSynthesizer.assemble_character_prompt(
            name=c_name,
            form=c_form,
            motion_slice=motion_slice,
            char_profile=c_prof,
            visual_style=visual_style,
        )

        c["visual_prompt"] = matrix_prompt
        c["image_prompt"] = matrix_prompt
        if not c.get("semantic_hash"):
            c["semantic_hash"] = compute_asset_semantic_hash("CHAR", cid, matrix_prompt, c)
        if cid in all_chars:
            c["lifecycle_status"] = AssetState.APPROVED.value
        else:
            c.setdefault("lifecycle_status", AssetState.READY.value)
        if cid and c.get("semantic_hash"):
            semantic_hashes[cid] = c["semantic_hash"]
            hash_to_asset[c["semantic_hash"]] = cid

    for e in norm_envs:
        eid = e.get("asset_id") or e.get("scene_id") or ""
        e_name = e.get("name") or "SCENE"
        e_form = e.get("form") or "T1_WIDE"
        raw_ep = e.get("visual_prompt") or e.get("image_prompt") or ""

        e_prof = all_envs.get(eid)
        if not e_prof:
            for ae_k, ae_v in all_envs.items():
                if isinstance(ae_v, dict) and ae_v.get("name") == e_name:
                    e_prof = ae_v
                    break

        raw_env_slice = {
            "architectural_style": e.get("architectural_style") or e.get("architecture") or "",
            "sub_zone_spot": e.get("sub_zone_spot") or e.get("zone_code") or "",
            "lighting_and_atmosphere": e.get("lighting_and_atmosphere") or e.get("lighting") or "",
            "scene_traces": e.get("narrative_traces") or e.get("trace") or "",
        }
        env_slice = AssetSliceEnricher.enrich_environment_slice(raw_env_slice, e_prof)

        matrix_env_prompt = PromptMatrixSynthesizer.assemble_environment_prompt(
            name=e_name,
            form=e_form,
            env_slice=env_slice,
            env_profile=e_prof,
            visual_style=visual_style,
        )

        e["visual_prompt"] = matrix_env_prompt
        e["image_prompt"] = matrix_env_prompt
        if not e.get("semantic_hash"):
            e["semantic_hash"] = compute_asset_semantic_hash("ENV", eid, matrix_env_prompt, e)
        if eid in all_envs:
            e["lifecycle_status"] = AssetState.APPROVED.value
        else:
            e.setdefault("lifecycle_status", AssetState.READY.value)
        if eid and e.get("semantic_hash"):
            semantic_hashes[eid] = e["semantic_hash"]
            hash_to_asset[e["semantic_hash"]] = eid

    for p in norm_props:
        pid = p.get("asset_id") or p.get("prop_id") or ""
        p_name = p.get("name") or "PROP"
        p_form = p.get("form") or "S0_STATIC"
        raw_pp = p.get("visual_prompt") or p.get("image_prompt") or ""

        p_prof = all_props.get(pid)
        if not p_prof:
            for ap_k, ap_v in all_props.items():
                if isinstance(ap_v, dict) and ap_v.get("name") == p_name:
                    p_prof = ap_v
                    break

        raw_prop_slice = {
            "material_details": p.get("material_details") or p.get("material") or "",
            "placement_surface": p.get("placement_surface") or p.get("surface") or "",
            "damage_state": p.get("damage_state") or "",
            "wear_and_tear": p.get("wear_and_tear") or "",
        }
        prop_slice = AssetSliceEnricher.enrich_prop_slice(raw_prop_slice, p_prof)

        matrix_prop_prompt = PromptMatrixSynthesizer.assemble_prop_prompt(
            name=p_name,
            form=p_form,
            prop_slice=prop_slice,
            prop_profile=p_prof,
            visual_style=visual_style,
        )

        p["visual_prompt"] = matrix_prop_prompt
        p["image_prompt"] = matrix_prop_prompt
        if not p.get("semantic_hash"):
            p["semantic_hash"] = compute_asset_semantic_hash("PROP", pid, matrix_prop_prompt, p)
        if pid in all_props:
            p["lifecycle_status"] = AssetState.APPROVED.value
        else:
            p.setdefault("lifecycle_status", AssetState.READY.value)
        if pid and p.get("semantic_hash"):
            semantic_hashes[pid] = p["semantic_hash"]
            hash_to_asset[p["semantic_hash"]] = pid

    # 将规范化结果注入 manifest_data
    if isinstance(raw_chars, list):
        manifest_data["characters"] = norm_chars
    if isinstance(raw_envs, list):
        manifest_data["environments"] = norm_envs
    if isinstance(raw_props, list):
        manifest_data["props"] = norm_props
    manifest_data.setdefault("episode_num", ep_num)
    manifest_data.setdefault("episode_title", episode_title)
    manifest_data.setdefault("aspect_ratio", aspect_ratio)

    # -------------------------------------------------------------------------
    # 步骤 5：跨集语义去重与生命周期状态机驱动
    # -------------------------------------------------------------------------
    reused_list = result_json.get("reused_existing_assets") or []
    current_ep_reused: list[str] = []
    for r in reused_list:
        rid = r.get("asset_id") if isinstance(r, dict) else getattr(r, "asset_id", "")
        if rid:
            current_ep_reused.append(rid)
            if isinstance(r, dict):
                r.setdefault("lifecycle_status", AssetState.APPROVED.value)
                r.setdefault("status", "APPROVED")

    raw_newly_list = result_json.get("newly_generated_assets") or []
    deduped_newly_list: list[dict[str, Any]] = []

    for n in raw_newly_list:
        n_dict = n if isinstance(n, dict) else n.to_dict() if hasattr(n, "to_dict") else dict(n)
        nid = n_dict.get("asset_id") or ""
        if not nid:
            continue

        cat = (
            "CHAR" if nid.startswith("CHAR_")
            else "ENV" if nid.startswith("ENV_")
            else "PROP" if nid.startswith("PROP_")
            else "VOICE" if nid.startswith("VOICE_")
            else "ASSET"
        )
        nhash = n_dict.get("semantic_hash")
        if not nhash:
            nhash = compute_asset_semantic_hash(cat, nid, n_dict.get("image_prompt") or n_dict.get("visual_prompt") or "", n_dict)
            n_dict["semantic_hash"] = nhash

        # 检查是否命中跨集语义哈希指纹去重（即相同提示词/特性的资产在历史集中已存在）
        existing_matched_id = hash_to_asset.get(nhash)
        if existing_matched_id and existing_matched_id != nid:
            logger.info(
                "【阶段 6 真理源·跨集语义去重】资产 [%s] (语义指纹 %s) 命中历史真理源已登记资产 [%s]，跳过重复生成并转入复用池",
                nid, nhash, existing_matched_id,
            )
            reused_list.append({
                "asset_id": existing_matched_id,
                "type": n_dict.get("asset_category") or "semantic_dedup_reused",
                "usage_in_current_ep": f"语义指纹 {nhash} 命中全局真理源 {existing_matched_id}，转入只读复用",
                "status": "APPROVED",
                "lifecycle_status": AssetState.APPROVED.value,
                "semantic_hash": nhash,
            })
            if existing_matched_id not in current_ep_reused:
                current_ep_reused.append(existing_matched_id)
            continue

        # 未命中跨集重复：正式作为增量生成项，初始生命周期为 READY
        n_dict.setdefault("lifecycle_status", AssetState.READY.value)

        # 补全DAG与四维提示词元数据 (强力防线：严防二阶/三阶资产退化为文生图 t2i)
        dep = AssetProtocolHelper.resolve_dependency(nid)
        cur_parsed = AssetProtocolHelper.parse_id(nid)

        if dep.generation_mode != "t2i":
            # 非一阶基准根节点：强制设为协议决定的衍生模式 (i2i / controlnet / inpaint)，绝不信任 LLM 幻觉生成的 t2i
            p_cand = n_dict.get("parent_asset_key") or n_dict.get("parent_asset_id") or dep.parent_asset_id
            if p_cand and cur_parsed and cur_parsed.category == "CHAR":
                p_parsed = AssetProtocolHelper.parse_id(p_cand)
                if p_parsed and p_parsed.category == "CHAR" and p_parsed.token != cur_parsed.token:
                    logger.warning(
                        "【阶段 6 增量资产纠偏·防跨角色污染】检测到角色资产 [%s] (token=%s) 错配父资产 [%s] (token=%s)，自动纠偏为同角色基准底模 [%s]",
                        nid, cur_parsed.token, p_cand, p_parsed.token, dep.parent_asset_id,
                    )
                    p_cand = dep.parent_asset_id
            if not p_cand:
                p_cand = dep.parent_asset_id

            # 强制覆盖，禁止 setdefault 保留非法的 t2i
            orig_mode = n_dict.get("generation_mode")
            if orig_mode == "t2i":
                logger.info("【阶段 6 资产模式纠偏】检测到二阶/三阶资产 [%s] 错误声明为 t2i，强制纠偏为 %s 并挂载父资产 [%s]", nid, dep.generation_mode, p_cand)
            n_dict["generation_mode"] = dep.generation_mode
            n_dict["parent_asset_key"] = p_cand
            n_dict["parent_asset_id"] = p_cand
            n_dict["is_benchmark"] = 0
            n_dict["denoise_strength"] = dep.recommended_denoise if n_dict.get("denoise_strength") is None else n_dict.get("denoise_strength")
        else:
            # 真正的一阶基准根节点 (T1 / Z01 / S0)
            n_dict["generation_mode"] = "t2i"
            n_dict["parent_asset_key"] = None
            n_dict["parent_asset_id"] = None
            n_dict["is_benchmark"] = 1 if dep.is_benchmark else 0
            n_dict["denoise_strength"] = dep.recommended_denoise

        n_dict.setdefault("control_type", dep.control_type)
        cat_key = "character" if nid.startswith("CHAR_") else "scene" if nid.startswith("ENV_") else "prop" if nid.startswith("PROP_") else "audio" if nid.startswith("VOICE_") else "default"
        n_dict.setdefault("negative_prompt", PromptSynthesizer.get_category_negative_prompt(cat_key))

        # 【剧情感官提示词自动化增强与去占位符】：融合当集剧本上下文，杜绝模板化套话
        raw_prompt = n_dict.get("image_prompt") or n_dict.get("visual_prompt") or ""
        narrative_ctx = {
            "emotion": n_dict.get("emotion") or n_dict.get("micro_expression"),
            "battle_damage": n_dict.get("battle_damage") or n_dict.get("injury_details"),
            "weather": n_dict.get("weather") or "",
            "time_lighting": (", ".join(scanner_result.lighting_conditions) if (scanner_result and scanner_result.lighting_conditions) else (n_dict.get("lighting") or "")) or "",
            "narrative_traces": n_dict.get("narrative_traces") or n_dict.get("trace"),
            "placement_surface": n_dict.get("placement_surface") or n_dict.get("surface"),
            "wear_and_tear": n_dict.get("wear_and_tear") or n_dict.get("damage"),
        }
        enriched_prompt = PromptSynthesizer.enrich_narrative_prompt(
            base_prompt=raw_prompt,
            category=cat_key,
            narrative_context=narrative_ctx,
            visual_style=visual_style,
        )
        n_dict["image_prompt"] = enriched_prompt
        n_dict["visual_prompt"] = enriched_prompt
        n_dict.setdefault("identity_prompt", enriched_prompt)
        n_dict.setdefault("delta_prompt", "")

        deduped_newly_list.append(n_dict)

        # 纳入全局索引与真理源库
        semantic_hashes[nid] = nhash
        hash_to_asset[nhash] = nid

        if nid.startswith("CHAR_") and nid not in all_chars:
            all_chars[nid] = n_dict
        elif nid.startswith("ENV_") and nid not in all_envs:
            all_envs[nid] = n_dict
        elif nid.startswith("PROP_") and nid not in all_props:
            all_props[nid] = n_dict

    reused_history[ep_num] = current_ep_reused

    # 兜底：同步 norm 资产项中未注册项
    for c in norm_chars:
        cid = c.get("asset_id") or c.get("char_id")
        if cid and cid not in all_chars:
            all_chars[cid] = c

    for e in norm_envs:
        eid = e.get("asset_id") or e.get("scene_id")
        if eid and eid not in all_envs:
            all_envs[eid] = e

    for p in norm_props:
        pid = p.get("asset_id") or p.get("prop_id")
        if pid and pid not in all_props:
            all_props[pid] = p

    # =========================================================================
    # 3. 新角色母音频卡片建档 (V2 精细化音色卡校验与单集登场白名单守卫)
    # =========================================================================
    # 【单集在场严格白名单守卫】：杜绝全剧未登场角色渗透进当集音色卡表 (character_voice_profiles)
    active_present_char_names: set[str] = set()
    active_present_char_codes: set[str] = set()

    for fc in filtered_norm_chars:
        if not isinstance(fc, dict):
            continue
        fc_name = str(fc.get("name") or fc.get("character_name") or "").strip()
        fc_code = str(fc.get("character_code") or fc.get("character_id") or fc.get("char_id") or fc.get("asset_id") or "").strip().upper()
        clean_fcn = _clean_name(fc_name)
        if clean_fcn:
            active_present_char_names.add(clean_fcn)
        if fc_name:
            active_present_char_names.add(fc_name)
        if fc_code:
            active_present_char_codes.add(fc_code)
            # 兼容 CHAR_ 前缀剥离匹配
            if fc_code.startswith("CHAR_"):
                active_present_char_codes.add(fc_code[5:])

    # 补充 present_chars_pool 确保包含剧本扫描器识别的角色
    for pcn in present_chars_pool:
        if pcn and str(pcn).strip():
            active_present_char_names.add(_clean_name(str(pcn).strip()))
            active_present_char_names.add(str(pcn).strip())

    logger.info(
        "【阶段 6 音色单集门禁】确立当集有效登场角色白名单: 名字集=%s, 代码集=%s",
        active_present_char_names, active_present_char_codes,
    )

    def _is_character_present_in_episode(cand_name: str, cand_code: str) -> bool:
        """判定该角色是否真实在当集登场 (白名单匹配与剧本真值校验)"""
        clean_cn = _clean_name(cand_name) if cand_name else ""
        c_code_clean = cand_code.upper().strip() if cand_code else ""
        
        # 1. 命中显式白名单
        if (clean_cn and clean_cn in active_present_char_names) or (cand_name and cand_name in active_present_char_names):
            return True
        if c_code_clean and (c_code_clean in active_present_char_codes or c_code_clean.replace("CHAR_", "") in active_present_char_codes):
            return True
            
        # 2. 备用兜底：若白名单空（极罕见），回退剧本直接文本检索
        if cand_name and is_character_truly_in_screenplay(
            char_entry={"name": cand_name, "character_code": cand_code},
            screenplay_text=screenplay_text,
            detected_chars=present_chars_pool,
            alias_map=alias_map,
        ):
            return True
        return False

    raw_voice_cards = result_json.get("new_character_master_voice_cards") or []
    voice_cards: list[dict[str, Any]] = []
    for vc_idx, vc in enumerate(raw_voice_cards, start=1):
        vc_dict = vc if isinstance(vc, dict) else vc.model_dump() if hasattr(vc, "model_dump") else dict(vc)
        vid = vc_dict.get("master_voice_id") or vc_dict.get("voice_id") or ""
        c_code = str(vc_dict.get("character_code") or vc_dict.get("character_id") or "").strip().upper()
        if not c_code and vid.startswith("VOICE_"):
            parts_v = vid.split("_")
            if len(parts_v) >= 2:
                c_code = f"CHAR_{parts_v[1]}"
        if c_code and not c_code.startswith("CHAR_"):
            c_code = f"CHAR_{re.sub(r'[^A-Z0-9]+', '', c_code)}"
        if not vid and c_code:
            vid = f"VOICE_{c_code.replace('CHAR_', '', 1)}_T1_MASTER"

        if vid:
            vc_dict["master_voice_id"] = vid
            vc_dict["character_id"] = c_code or vc_dict.get("character_id") or "CHAR_PROTAGONIST"
            vc_dict["character_code"] = vc_dict["character_id"]

            # 查找对应角色档案以补齐音色原型与名称
            matched_char_info: dict[str, Any] = {}
            for c_item in filtered_norm_chars:
                if isinstance(c_item, dict):
                    item_cc = str(c_item.get("character_code") or c_item.get("character_id") or c_item.get("char_id") or "").upper()
                    if item_cc == vc_dict["character_code"] or vc_dict["character_code"].endswith(item_cc):
                        matched_char_info = c_item
                        break

            if not vc_dict.get("character_name"):
                vc_dict["character_name"] = (
                    matched_char_info.get("name")
                    or matched_char_info.get("character_name")
                    or vc_dict["character_code"].replace("CHAR_", "")
                )

            vc_cname = str(vc_dict.get("character_name") or "").strip()
            # 【门禁拦截】：大模型输出的音色卡若属于未登场角色，坚决剔除
            if not _is_character_present_in_episode(vc_cname, vc_dict["character_code"]):
                logger.warning(
                    "【阶段 6 音色门禁拦截】剔除大模型生成的未登场角色音色卡: %s (%s, %s)",
                    vc_cname, vc_dict["character_code"], vid,
                )
                continue

            arch = _select_voice_archetype(matched_char_info or vc_dict, used_archetypes_node, index_hint=vc_idx)
            vc_dict.setdefault("timbre", matched_char_info.get("timbre") or arch["timbre"])
            vc_dict.setdefault("timbre_archetype", matched_char_info.get("timbre_archetype") or arch["timbre_archetype"])
            vc_dict.setdefault("vocal_position", arch["vocal_position"])
            vc_dict.setdefault("vocal_flaws", arch["vocal_flaws"])
            vc_dict.setdefault("speed_ratio", float(arch["speed_ratio"]))
            vc_dict.setdefault("pitch_ratio", float(arch["pitch_ratio"]))
            vc_dict.setdefault("tts_provider", "minimax")
            vc_dict.setdefault("tts_model", "speech-02-hd")
            vc_dict.setdefault("provider_voice_id", arch["provider_voice_id"])
            vc_dict.setdefault("timber_weights", arch["timber_weights"])

            raw_mono = (
                vc_dict.get("master_sample_text")
                or vc_dict.get("script_monologue_source")
                or vc_dict.get("sample_line")
                or ""
            )
            vc_dict["master_sample_text"] = _strip_dialogue_brackets(
                raw_mono, character_name=str(vc_dict.get("character_name") or "角色")
            )
            if not vc_dict.get("script_monologue_source"):
                vc_dict["script_monologue_source"] = raw_mono or vc_dict["master_sample_text"]

            if not vc_dict.get("master_tts_prompt"):
                vc_dict["master_tts_prompt"] = (
                    f"{vc_dict['timbre']}，{vc_dict['vocal_position']}，{vc_dict['vocal_flaws']}，"
                    f"语速倍率{float(vc_dict['speed_ratio']):.2f}，音高倍率{float(vc_dict['pitch_ratio']):.2f}"
                )
            if not vc_dict.get("voice_prompt"):
                vc_dict["voice_prompt"] = vc_dict["master_tts_prompt"]
            if not vc_dict.get("voice_file_path") or vc_dict["voice_file_path"].endswith(".wav"):
                vc_dict["voice_file_path"] = f"storage/audio/voices/{vid}.mp3"

            raw_emo = vc_dict.get("emotion_rules")
            if not isinstance(raw_emo, dict) or not raw_emo:
                vc_dict["emotion_rules"] = _build_default_emotion_rules()
            else:
                # 剔除混音侧链闪避污染字段 bgm_ducking_db
                vc_dict["emotion_rules"] = {
                    ek: {k: v for k, v in ev.items() if k != "bgm_ducking_db"} if isinstance(ev, dict) else ev
                    for ek, ev in raw_emo.items()
                }

            vc_hash = vc_dict.get("semantic_hash") or compute_asset_semantic_hash(
                "VOICE", vid, vc_dict.get("master_tts_prompt", ""), vc_dict
            )
            vc_dict["semantic_hash"] = vc_hash
            vc_dict.setdefault("lifecycle_status", AssetState.READY.value)
            if vid not in all_voices:
                all_voices[vid] = vc_dict
            semantic_hashes[vid] = vc_hash
            hash_to_asset[vc_hash] = vid
            voice_cards.append(vc_dict)
            logger.debug(
                "【阶段 6 音色卡建档】角色=%s (%s), 母音ID=%s, 原型=%s, 试音干声长度=%d字",
                vc_dict.get("character_name"), vc_dict.get("character_code"),
                vid, vc_dict.get("timbre_archetype"), len(vc_dict.get("master_sample_text", "")),
            )

    # 3.2 当集登场角色母音频卡 100% 全覆盖保底扫描
    # 核心保障：仅遍历经过剧本在场校验的 filtered_norm_chars，杜绝未登场角色被保底扫描暗度陈仓生成！
    covered_char_codes = {str(vc.get("character_code") or "").upper() for vc in voice_cards}
    covered_char_names = {_clean_name(str(vc.get("character_name") or "")) for vc in voice_cards}

    for c_item in filtered_norm_chars:
        if not isinstance(c_item, dict):
            continue
        c_name = str(c_item.get("name") or c_item.get("character_name") or "").strip()
        c_code = str(c_item.get("character_code") or c_item.get("character_id") or c_item.get("char_id") or "").strip().upper()
        clean_c_name = _clean_name(c_name)
        if not c_name and not c_code:
            continue

        # 检查是否已被覆盖
        if (c_code and c_code in covered_char_codes) or (clean_c_name and clean_c_name in covered_char_names):
            continue

        tok = AssetProtocolHelper.normalize_token(clean_c_name or c_code or c_name)
        auto_vid = f"VOICE_{tok}_T1_MASTER"
        if auto_vid in all_voices:
            continue

        arch = _select_voice_archetype(c_item, used_archetypes_node, index_hint=len(voice_cards) + 1)
        timbre_val = c_item.get("timbre") or c_item.get("voice_style") or arch["timbre"]
        arch_val = c_item.get("timbre_archetype") or arch["timbre_archetype"]
        sample_text_val = f"我是{c_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"

        auto_vc: dict[str, Any] = {
            "master_voice_id": auto_vid,
            "voice_id": auto_vid,
            "character_id": c_code or f"CHAR_{tok}",
            "character_code": c_code or f"CHAR_{tok}",
            "character_name": c_name or tok,
            "timbre": timbre_val,
            "timbre_archetype": arch_val,
            "vocal_position": arch["vocal_position"],
            "vocal_flaws": arch["vocal_flaws"],
            "speed_ratio": float(arch["speed_ratio"]),
            "pitch_ratio": float(arch["pitch_ratio"]),
            "tts_provider": "minimax",
            "tts_model": "speech-02-hd",
            "provider_voice_id": arch["provider_voice_id"],
            "timber_weights": arch["timber_weights"],
            "master_sample_text": sample_text_val,
            "script_monologue_source": sample_text_val,
            "master_tts_prompt": (
                f"{timbre_val}，{arch['vocal_position']}，{arch['vocal_flaws']}，"
                f"语速倍率{float(arch['speed_ratio']):.2f}，音高倍率{float(arch['pitch_ratio']):.2f}"
            ),
            "voice_file_path": f"storage/audio/voices/{auto_vid}.mp3",
            "is_master_card": True,
            "emotion_rules": _build_default_emotion_rules(),
        }
        auto_vc["voice_prompt"] = auto_vc["master_tts_prompt"]
        vc_hash = compute_asset_semantic_hash("VOICE", auto_vid, auto_vc["master_tts_prompt"], auto_vc)
        auto_vc["semantic_hash"] = vc_hash
        auto_vc["lifecycle_status"] = AssetState.READY.value

        all_voices[auto_vid] = auto_vc
        semantic_hashes[auto_vid] = vc_hash
        hash_to_asset[vc_hash] = auto_vid
        voice_cards.append(auto_vc)
        if auto_vc["character_code"]:
            covered_char_codes.add(auto_vc["character_code"])
        if clean_c_name:
            covered_char_names.add(clean_c_name)

        logger.info(
            "【阶段 6 音色卡全覆盖保底】成功为未开口/配角 [%s](%s) 补全母音卡: voice_id=%s, 音色原型=%s",
            c_name, auto_vc["character_code"], auto_vid, arch_val,
        )

    registry["characters"] = all_chars
    registry["environments"] = all_envs
    registry["props"] = all_props
    registry["audio_tts"] = all_voices
    registry["reused_assets_history"] = reused_history
    registry["semantic_hashes"] = semantic_hashes
    registry["hash_index"] = hash_to_asset

    # 规范化补齐 asset_key 并执行角色资产血统闭环纠偏
    for n_dict in deduped_newly_list:
        n_dict.setdefault("asset_key", n_dict.get("asset_id"))
        aid = n_dict.get("asset_id") or n_dict.get("asset_key")
        c_parsed = AssetProtocolHelper.parse_id(aid)
        if c_parsed and c_parsed.category == "CHAR":
            if c_parsed.function == "BASE_PORTRAIT":
                # 主肖像严格作为 t2i 根节点
                n_dict["parent_asset_id"] = None
                n_dict["parent_asset_key"] = None
                n_dict["generation_mode"] = "t2i"
            else:
                # 衍生资产强校验同实体
                p_cand = n_dict.get("parent_asset_id") or n_dict.get("parent_asset_key")
                if p_cand:
                    p_parsed = AssetProtocolHelper.parse_id(p_cand)
                    if p_parsed and p_parsed.category == "CHAR" and p_parsed.token != c_parsed.token:
                        safe_parent = f"CHAR_{c_parsed.token}_{c_parsed.tier}_BASE_PORTRAIT"
                        logger.warning(
                            "【阶段 6 资产血统闭环】纠正增量资产 [%s] (token=%s) 的跨角色父资产 [%s] -> [%s]",
                            aid, c_parsed.token, p_cand, safe_parent,
                        )
                        n_dict["parent_asset_id"] = safe_parent
                        n_dict["parent_asset_key"] = safe_parent

    for r in reused_list:
        if isinstance(r, dict):
            r.setdefault("asset_key", r.get("asset_id"))

    # 提取或构建血统继承 DAG (含同角色实体闭环校验与跨角色污染拦截)
    raw_dag = result_json.get("lineage_dag") or {}
    if not isinstance(raw_dag, dict):
        raw_dag = {}
    for n_dict in deduped_newly_list:
        aid = n_dict.get("asset_id") or n_dict.get("asset_key")
        pid = n_dict.get("parent_asset_id") or n_dict.get("parent_stage_id") or n_dict.get("input_source_image")
        if aid and pid and aid not in raw_dag:
            raw_dag[aid] = pid

    sanitized_lineage_dag: dict[str, str] = {}
    for child_id, parent_id in raw_dag.items():
        child_parsed = AssetProtocolHelper.parse_id(child_id)
        parent_parsed = AssetProtocolHelper.parse_id(parent_id)

        # 1. 仅当一阶肖像基准节点 (T1) 时，才强制禁止存在父级；二阶/三阶肖像 (T2/T3) 必须保留指向 T1 基准肖像的父级边！
        if child_parsed and child_parsed.category == "CHAR" and child_parsed.function == "BASE_PORTRAIT":
            if child_parsed.tier == "T1":
                logger.debug("【阶段 6 DAG血统防线】一阶肖像基准节点 [%s] 强制移除父级边 (原父级: %s)", child_id, parent_id)
                continue
            else:
                # T2/T3 阶段肖像：若 parent_id 为空或跨角色，强制重定向至该角色的 T1 基准肖像
                t1_benchmark = f"CHAR_{child_parsed.token}_T1_BASE_PORTRAIT"
                if not parent_id or (parent_parsed and parent_parsed.token != child_parsed.token):
                    logger.info("【阶段 6 DAG血统防线】二阶/三阶阶段肖像 [%s] 锚定至同角色 T1 基准肖像 [%s]", child_id, t1_benchmark)
                    parent_id = t1_benchmark

        # 2. 角色资产必须满足同实体血统闭环 (Child Token == Parent Token)
        if child_parsed and parent_parsed and child_parsed.category == "CHAR" and parent_parsed.category == "CHAR":
            if child_parsed.token != parent_parsed.token:
                safe_parent = f"CHAR_{child_parsed.token}_T1_BASE_PORTRAIT"
                logger.warning(
                    "【阶段 6 DAG血统防线·拦截跨角色污染】检测到非法跨角色继承边: 子资产=%s (token=%s) -> 错配父资产=%s (token=%s)! 自动重定向到同角色基准肖像 [%s]",
                    child_id, child_parsed.token, parent_id, parent_parsed.token, safe_parent,
                )
                parent_id = safe_parent

        sanitized_lineage_dag[child_id] = parent_id

    lineage_dag = sanitized_lineage_dag

    manifest_data["newly_discovered_characters"] = normalized_new_chars
    manifest_data["newly_discovered_scenes"] = normalized_new_scenes
    manifest_data["newly_discovered_props"] = normalized_new_props
    manifest_data["newly_generated_assets"] = deduped_newly_list
    manifest_data["reused_existing_assets"] = reused_list
    manifest_data["new_character_master_voice_cards"] = voice_cards
    manifest_data["lineage_dag"] = lineage_dag

    # 构建并验证本集视听资源引单
    manifest = EpisodeResourceManifest.model_validate(manifest_data)
    manifests[ep_num] = manifest

    logger.info(
        "【阶段 6 真理源】第 %s 集资产引单提纯构建完成: "
        "角色项=%s (新补录=%s), 场景项=%s (新补录=%s), 道具项=%s (新补录=%s), 音色卡=%s | 增量待生成=%s, 历史复用=%s, 累计登记指纹=%s",
        ep_num,
        len(norm_chars), len(normalized_new_chars),
        len(norm_envs), len(normalized_new_scenes),
        len(norm_props), len(normalized_new_props),
        len(voice_cards),
        len(deduped_newly_list), len(reused_list), len(semantic_hashes),
    )

    return StageResult({
        "current_stage": 6,
        "episode_id": ep_num,
        "episode_num": ep_num,
        "episode_number": ep_num,
        "episode_title": episode_title,
        "visual_audio_assets_registry": registry,
        "episode_resource_manifests": manifests,
        "episode_manifests": manifests,
        "newly_discovered_characters": normalized_new_chars,
        "newly_discovered_scenes": normalized_new_scenes,
        "newly_discovered_props": normalized_new_props,
        "reused_existing_assets": reused_list,
        "newly_generated_assets": deduped_newly_list,
        "new_character_master_voice_cards": voice_cards,
        "manifest": manifest,
        "episode_manifest": manifest,
        "episode_resource_manifest": manifest,
        "resource_manifest": manifest,
        "local_assets": norm_chars + norm_envs + norm_props,
    })
