"""阶段 6 声学音色原型池与情绪规则分配模块 (Stage 6 Voice Rules & Timbre Allocator)。

提供跨角色防撞声学音色池、戏剧状态声学偏移矩阵以及纯净母音频试音台本清洗算法。
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("lmd.stage6.voice_rules")


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



