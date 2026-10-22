from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.platform_common import now_iso
from app.tools.screenplay_feature_scanner import is_valid_character_speaker
from app.tools.shot_duration_calculator import clean_dialogue_text
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer
from app.schemas.script_graph_state import (
    AudioBible,
    CandidateTitleMatrix,
    CharacterAnchorStub,
    DoubleTrackProhibitions,
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    InterEpisodePhysicalContinuity,
    LiteraryScreenplayEpisodeModel,
    PropAnchorStub,
    RedBlueAuditReport,
    SceneAnchorStub,
    SeasonOutlineCard,
    StoryboardShot,
    StoryboardShotStub,
)
from app.workflows.adapters.stage_adapters.common import (
    _safe_json_loads,
    _ensure_valid_json_str,
    _dump_or_dict,
    _flatten_asset_collection,
    _get_table_columns,
    sync_stage_memories_to_vector_db,
    persist_audit_report,
    fetch_all,
    fetch_one,
    get_short_memories,
    publish_drama_event,
    publish_drama_read_projection,
    publish_episode_read_projection,
    set_short_memories,
)

log = get_logger("lmd.storage_adapter")

def _normalize_asset_lookup_token(raw_token: Any) -> str:
    """将资产引用字符串归一化为无特殊符号的大写检索 Token。"""
    if raw_token is None:
        return ""
    s = str(raw_token).strip().upper()
    return re.sub(r"[^A-Z0-9\u4e00-\u9fa5_]", "", s)


_GENERIC_ASSET_SEGMENTS = {
    "CHAR", "PROP", "ENV", "SCENE", "VOICE", "SFX", "BGM", "AUDIO",
    "T1", "T2", "T3", "S0", "S1", "S2", "S3", "Z01", "Z02", "Z03",
    "BASE", "PORTRAIT", "STATIC", "ACTION", "WIDE", "MACRO", "FRONT", "4V",
}


def _extract_core_asset_prefixes(token: str) -> list[str]:
    """从四段式资产 ID（如 CHAR_LUCHEN_T1_BASE_PORTRAIT）提取候选匹配前缀与核心 Token。"""
    norm = _normalize_asset_lookup_token(token)
    if not norm:
        return []
    candidates = [norm]
    parts = [p for p in norm.split("_") if p]
    if len(parts) >= 2 and parts[0] in ("CHAR", "ENV", "SCENE", "PROP"):
        # 例如 CHAR_LUCHEN、ENV_WAREHOUSE、PROP_JADE
        prefix_two = f"{parts[0]}_{parts[1]}"
        if prefix_two not in candidates:
            candidates.append(prefix_two)
        # 若存在复合英文名（如 PROP_BRONZE_KEY_T1_STATIC -> PROP_BRONZE_KEY / BRONZE_KEY）
        core_segs: list[str] = []
        for seg in parts[1:]:
            if seg in _GENERIC_ASSET_SEGMENTS or re.match(r"^[TSZ]\d+$", seg):
                break
            core_segs.append(seg)
        if len(core_segs) >= 2:
            compound_tok = "_".join(core_segs)
            compound_pref = f"{parts[0]}_{compound_tok}"
            if compound_pref not in candidates:
                candidates.append(compound_pref)
            if compound_tok not in candidates:
                candidates.append(compound_tok)
        if parts[1] not in candidates and not parts[1].isdigit():
            candidates.append(parts[1])
        # 若前缀为 SCENE_xxx，同时兼容 ENV_xxx
        if parts[0] == "SCENE":
            env_alias = f"ENV_{parts[1]}"
            if env_alias not in candidates:
                candidates.append(env_alias)
        elif parts[0] == "ENV":
            scene_alias = f"SCENE_{parts[1]}"
            if scene_alias not in candidates:
                candidates.append(scene_alias)
    return candidates


def _extract_pure_dialogue_and_action(
    raw_dialogue: str,
    raw_action: str = "",
) -> tuple[str, str, str, str, list[str]]:
    """严谨分离说话人名称、纯净对白文本、语音合成文本、影视动作以及提取的表演指示。

    解决短剧分镜中常见的台词格式污染问题：
    例如："沈墨：（冷笑，拔枪质问）你以为能逃得出废弃仓库？"
    应当精确解析出：
    - speaker_name: "沈墨"
    - pure_dialogue: "你以为能逃得出废弃仓库？"（保留问号、感叹号等自然标点，用于屏幕字幕展示）
    - clean_phonetic: "你以为能逃得出废弃仓库"（送入TTS引擎的发音文本，无动作括号）
    - combined_action: 原动作 + "（冷笑，拔枪质问）"（影视动作与戏剧表演融合）
    - acting_cues: ["冷笑，拔枪质问"]（微表情与动作指示列表，供角色情绪覆盖）

    Returns:
        tuple[speaker_name, pure_dialogue, clean_phonetic, combined_action, acting_cues]
    """
    raw_dlg = str(raw_dialogue or "").strip()
    raw_act = str(raw_action or "").strip()
    speaker_name = ""
    acting_cues: list[str] = []

    # 1. 提取说话人前缀（支持中英文冒号）
    dlg_body = raw_dlg
    if "：" in dlg_body or ":" in dlg_body:
        sep = "：" if "：" in dlg_body else ":"
        candidate_spk, remainder = dlg_body.split(sep, 1)
        candidate_spk = candidate_spk.strip()
        # 提取并剔除说话人内部括号修饰，如 "沈墨(冷笑)" -> "沈墨"
        for sp in re.findall(r"[（\(](.*?)[）\)]", candidate_spk):
            if sp.strip():
                acting_cues.append(sp.strip())
        candidate_spk = re.sub(r"[（\(].*?[）\)]", "", candidate_spk).strip()
        if candidate_spk and len(candidate_spk) <= 12:
            speaker_name = candidate_spk
            dlg_body = remainder.strip()

    # 2. 从台词主体中提取括号内的舞台动作与心理指示（中英文括号）
    for ep in re.findall(r"[（\(](.*?)[）\)]", dlg_body):
        if ep.strip():
            acting_cues.append(ep.strip())

    # 剔除台词正文中的括号指示，保留真实台词文字与标点符号
    pure_dialogue = re.sub(r"[（\(].*?[）\)]", "", dlg_body).strip()
    pure_dialogue = pure_dialogue.lstrip("：: ").strip()

    # 3. 构造纯语音发音文本（供 TTS 引擎）
    clean_phonetic = clean_dialogue_text(pure_dialogue) if pure_dialogue else ""

    # 4. 融合动作指示（如果台词中含有舞台动作且原动作未体现，将其融合）
    combined_action = raw_act
    if acting_cues:
        merged_cues = "，".join(acting_cues)
        if not combined_action:
            combined_action = f"（{merged_cues}）"
        elif merged_cues not in combined_action:
            combined_action = f"{combined_action}（{merged_cues}）"

    return speaker_name, pure_dialogue, clean_phonetic, combined_action, acting_cues


def _sanitize_storyboard_time(
    raw_time: str,
    scene_time_fallback: str = "日景/白天",
) -> str:
    """清理分镜的 time 字段，坚决阻断 timecode 或 srt 时码对时段字段的污染。

    合法时段例如："日景", "白天", "深夜", "暴雨夜", "黄昏", "清晨", "深夜暴雨"。
    严禁出现类似 "00:00:03,000 --> 00:00:06,000"、"00:03,000"、"3.5s"、纯数字等时码。
    """
    candidate = str(raw_time or "").strip()
    if "-->" in candidate:
        candidate = ""
    if re.search(r"\d{1,2}:\d{2}", candidate):
        candidate = ""
    if re.match(r"^\d+(\.\d+)?(s|秒|ms)?$", candidate, re.IGNORECASE):
        candidate = ""

    if not candidate:
        candidate = str(scene_time_fallback or "").strip()

    if not candidate or "-->" in candidate or re.search(r"\d{1,2}:\d{2}", candidate):
        candidate = "日景/白天"

    return candidate


def _extract_prop_aliases_and_keywords(prop_name: str) -> list[str]:
    """提取道具的核心实体别名、剥离修饰词与视听同义词扩展。

    例如：
    - "苏秀兰遗像" -> ["遗像", "遗照", "相框"]
    - "带血的牛皮纸信封" -> ["牛皮纸信封", "信封", "信件", "密信"]
    - "老旧桃木剑" -> ["桃木剑", "木剑"]
    """
    if not prop_name:
        return []
    pname = str(prop_name).strip()
    aliases: list[str] = []

    # 1. 剥离定语/修饰词与前缀
    stripped = re.sub(r"^(带血的|染血的|老旧的|破旧的|神秘的|泛黄的|精致的|古旧的|锈蚀的|纯金|纯银)", "", pname).strip()
    if stripped and stripped != pname:
        aliases.append(stripped)

    # 剥离前缀人名（例如苏秀兰遗像 -> 遗像）
    core_suffixes = [
        "遗像", "遗照", "相框", "信封", "信件", "木剑", "佩剑", "长剑", "短刀", "匕首",
        "玉佩", "玉镯", "戒指", "项链", "手镯", "账本", "日记", "圣旨", "令牌", "拂尘",
        "拂子", "药瓶", "茶杯", "酒杯", "锦囊", "香囊", "火折子", "油灯"
    ]
    for suf in core_suffixes:
        if pname.endswith(suf) and len(pname) > len(suf):
            aliases.append(suf)
        if stripped and stripped.endswith(suf) and len(stripped) > len(suf):
            aliases.append(suf)

    # 2. 视听等价同义词派生
    synonym_map = {
        "遗像": ["遗照", "相框", "黑白照"],
        "遗照": ["遗像", "相框"],
        "相框": ["遗像", "遗照"],
        "信封": ["信件", "信纸", "密信", "书信"],
        "信件": ["信封", "书信"],
        "令牌": ["令旗", "铁牌", "铜牌"],
        "短刀": ["匕首", "小刀"],
        "匕首": ["短刀", "利刃"],
        "玉佩": ["玉饰", "吊坠"],
        "木剑": ["桃木剑", "短剑"],
        "火折子": ["火折", "火把"],
    }
    expanded: list[str] = []
    for item in [pname, stripped] + aliases:
        for k, syns in synonym_map.items():
            if k in item:
                expanded.extend(syns)

    result: list[str] = []
    for a in [stripped] + aliases + expanded:
        a_clean = a.strip()
        if a_clean and a_clean != pname and len(a_clean) >= 2 and a_clean not in result:
            result.append(a_clean)
    return result


def _deduce_prop_interaction_role(
    prop_name: str,
    action_text: str = "",
    shot_type: str = "",
) -> str:
    """根据动作文本与景别推导道具在当前镜头中的交互定位 (interaction_role)。

    可选枚举值：
    - 'foreground': 前景/微距特写（如特写镜头中作为构图焦点）
    - 'primary': 核心交互（角色手持、持握、拔出、递交等主动物理交互）
    - 'ambient': 环境陈设（空间背景道具、背景陈列）
    """
    s_type = (shot_type or "").upper()
    act = action_text or ""
    p_name = prop_name or ""

    is_close_up = any(k in s_type for k in ("特写", "大特写", "极特写", "CU", "ECU", "MACRO", "微距", "POV"))
    is_wide = any(k in s_type for k in ("远景", "全景", "大全景", "WIDE", "ESTABLISH", "WS", "FS", "EWS"))

    active_verbs = (
        "握", "持", "拔", "掏", "拿", "递", "戴", "饮", "端", "摔", "扔", "刺", "夺", "抓", "捡", "紧握",
        "举起", "触碰", "撕开", "拆开", "翻开", "抚摸", "把玩", "端详", "拾起", "佩戴", "紧攥"
    )
    has_active_verb = any(v in act for v in active_verbs)

    if is_close_up:
        return "foreground"
    if is_wide:
        # 在广角/远景/建立镜头中，除非有极其明确的手部交互动词，否则一律归为环境背景陈设
        return "primary" if has_active_verb else "ambient"
    if has_active_verb:
        return "primary"
    return "ambient"


def _calculate_subtitle_duration_ms(
    text: str,
    inpoint_sec: float,
    shot_dur_sec: float,
) -> tuple[int, int, int]:
    """计算单句字幕在全局镜头内的起止毫秒与持续时长。

    遵循影视汉语语速（4.0-5.0字/秒，约 220ms/字）并计入标点停顿：
    - 逗号/分号停顿约 150ms
    - 句号/感叹号/问号停顿约 300ms
    - 省略号停顿约 400ms

    确保字幕持续时间合理且严格不超越当前镜头的持续时间。
    """
    in_s = max(0.0, float(inpoint_sec or 0.0))
    s_dur = max(0.5, float(shot_dur_sec or 3.0))

    clean_chars = [c for c in text if c not in " ，。！？；：、“”‘’()（）《》\n\r\t"]
    char_count = len(clean_chars)

    base_ms = max(800, int(char_count * 220))
    comma_count = text.count("，") + text.count(",") + text.count("；") + text.count(";")
    sentence_end_count = (
        text.count("。") + text.count(".") + text.count("！") + text.count("!") + text.count("？") + text.count("?")
    )
    ellipsis_count = text.count("……") + text.count("...")

    pause_ms = comma_count * 150 + sentence_end_count * 300 + ellipsis_count * 400
    total_est_ms = base_ms + pause_ms

    in_ms = int(in_s * 1000)
    shot_total_ms = int(s_dur * 1000)

    available_ms = max(500, shot_total_ms - in_ms - 150)
    final_dur_ms = min(total_est_ms, available_ms)
    out_ms = in_ms + final_dur_ms

    return in_ms, out_ms, final_dur_ms


def _select_character_stage_and_view(
    char_info: dict[str, Any],
    char_views: list[dict[str, Any]] | None,
    shot_type: str = "",
    action: str = "",
    raw_ref: str = "",
) -> dict[str, Any]:
    """根据分镜景别、肢体动作与引用代号，精确定位角色二级阶段造型与三级切片视图。

    解决角色切片千篇一律为 CHAR_*_T1_BASE_PORTRAIT 的问题：
    1. raw_ref 显式包含具体切片视图 Token (如 FULL_BODY, 4V, MACRO, HANDS, 极特写, 全身立绘)；
    2. 分镜景别 (framing/shot_type) 智能映射：
       - 远景/全景/全身 (EWS, WS, FS, 全景, 远景, 全身): 优先 full_body / four_view；
       - 极特写/微距 (ECU, 极特写, 微距, 瞳孔, 咬肌, 额头, 汗水): 优先 facial_macro 或 hands_detail；
       - 手部交互 (撕开, 递过, 抓向, 指尖, 握紧): 优先 hands_detail；
       - 中景/中近景/特写/半身 (MCU, MS, CU, 特写, 中景): 优先 main_portrait；
    3. 基石回退 (is_benchmark=1 / is_primary=1 / 默认主肖像)。
    """
    default_res = {
        "character_stage_id": char_info.get("character_stage_id"),
        "stage_view_id": char_info.get("stage_view_id"),
        "asset_key": char_info.get("benchmark_asset_key") or "",
        "view_type": "main_portrait",
    }
    if not char_views:
        return default_res

    ref_upper = (raw_ref or "").upper()
    shot_upper = (shot_type or "").upper()
    action_text = action or ""

    # 1. 检查 raw_ref 是否显式精确匹配某一切片的 asset_key
    for cv in char_views:
        v_key = str(cv.get("asset_key") or "").upper()
        if v_key and (v_key == ref_upper or ref_upper in v_key):
            return {
                "character_stage_id": cv.get("stage_id"),
                "stage_view_id": cv.get("view_id"),
                "asset_key": cv.get("asset_key") or default_res["asset_key"],
                "view_type": cv.get("view_type") or "main_portrait",
            }

    # 2. 检查 raw_ref 是否显式包含视角类型标记
    if any(k in ref_upper for k in ("FULL_BODY", "4V", "FOUR_VIEW", "全身")):
        for cv in char_views:
            if cv.get("view_type") in ("full_body", "four_view", "4v_front"):
                return {
                    "character_stage_id": cv.get("stage_id"),
                    "stage_view_id": cv.get("view_id"),
                    "asset_key": cv.get("asset_key"),
                    "view_type": cv.get("view_type"),
                }
    if any(k in ref_upper for k in ("MACRO", "FACIAL", "极特写", "微距")):
        for cv in char_views:
            if cv.get("view_type") in ("facial_macro", "macro"):
                return {
                    "character_stage_id": cv.get("stage_id"),
                    "stage_view_id": cv.get("view_id"),
                    "asset_key": cv.get("asset_key"),
                    "view_type": cv.get("view_type"),
                }
    if any(k in ref_upper for k in ("HAND", "HANDS", "手部")):
        for cv in char_views:
            if cv.get("view_type") in ("hands_detail", "hand"):
                return {
                    "character_stage_id": cv.get("stage_id"),
                    "stage_view_id": cv.get("view_id"),
                    "asset_key": cv.get("asset_key"),
                    "view_type": cv.get("view_type"),
                }

    # 3. 根据分镜景别 (framing/shot_type) 与动作行为智能推导
    is_wide = any(k in shot_upper for k in ("FS", "WS", "EWS", "WIDE", "FULL")) or any(k in shot_type for k in ("全景", "远景", "大全景", "全身"))
    is_wide = is_wide or any(k in action_text for k in ("跨步", "退后", "站立", "后撤", "奔跑", "走廊", "穿过", "立在"))

    is_macro = any(k in shot_upper for k in ("ECU", "EXTREME", "MACRO")) or any(k in shot_type for k in ("极特写", "微距"))
    is_macro = is_macro or any(k in action_text for k in ("瞳孔骤", "咬肌", "齿缝", "指节发白", "汗水", "双眼瞳孔"))

    is_hand = any(k in action_text for k in ("撕开", "指尖", "递过", "推向", "抓向", "死扣", "右手腕", "握紧保温杯"))

    if is_hand:
        for cv in char_views:
            if cv.get("view_type") in ("hands_detail", "hand"):
                return {
                    "character_stage_id": cv.get("stage_id"),
                    "stage_view_id": cv.get("view_id"),
                    "asset_key": cv.get("asset_key"),
                    "view_type": cv.get("view_type"),
                }

    if is_macro:
        for cv in char_views:
            if cv.get("view_type") in ("facial_macro", "macro"):
                return {
                    "character_stage_id": cv.get("stage_id"),
                    "stage_view_id": cv.get("view_id"),
                    "asset_key": cv.get("asset_key"),
                    "view_type": cv.get("view_type"),
                }

    if is_wide:
        for cv in char_views:
            if cv.get("view_type") in ("full_body", "four_view", "4v_front"):
                return {
                    "character_stage_id": cv.get("stage_id"),
                    "stage_view_id": cv.get("view_id"),
                    "asset_key": cv.get("asset_key"),
                    "view_type": cv.get("view_type"),
                }

    # 4. 常规中景/特写/正视或默认回退: 优先 main_portrait / benchmark
    for cv in char_views:
        if cv.get("view_type") == "main_portrait":
            return {
                "character_stage_id": cv.get("stage_id"),
                "stage_view_id": cv.get("view_id"),
                "asset_key": cv.get("asset_key"),
                "view_type": cv.get("view_type"),
            }

    # 5. 保底返回首个视图
    first_v = char_views[0]
    return {
        "character_stage_id": first_v.get("stage_id"),
        "stage_view_id": first_v.get("view_id"),
        "asset_key": first_v.get("asset_key") or default_res["asset_key"],
        "view_type": first_v.get("view_type") or "main_portrait",
    }


def _select_prop_damage_and_view(
    prop_info: dict[str, Any],
    prop_views: list[dict[str, Any]] | None,
    shot_type: str = "",
    action: str = "",
    raw_ref: str = "",
) -> dict[str, Any]:
    """根据分镜剧情动作中道具的物理损坏/形态演进及微距特征，定位二级状态与三级切片。"""
    default_res = {
        "damage_state_id": prop_info.get("damage_state_id"),
        "prop_detail_view_id": prop_info.get("prop_detail_view_id"),
        "asset_key": prop_info.get("benchmark_asset_key") or "",
        "view_type": "macro_feature",
    }
    if not prop_views:
        return default_res

    ref_upper = (raw_ref or "").upper()
    action_text = action or ""

    # 1. 检查 raw_ref 是否显式精确匹配某一切片 asset_key
    for pv in prop_views:
        p_key = str(pv.get("asset_key") or "").upper()
        if p_key and (p_key == ref_upper or ref_upper in p_key):
            return {
                "damage_state_id": pv.get("damage_state_id"),
                "prop_detail_view_id": pv.get("detail_view_id"),
                "asset_key": pv.get("asset_key") or default_res["asset_key"],
                "view_type": pv.get("view_type") or "macro_feature",
            }

    # 2. 检查动作是否触发战损/破坏状态 (S1_CRACKED, S2_BROKEN, 裂纹, 撕开, 鲜红血印, 脱漆)
    is_damaged = any(k in action_text for k in ("裂纹", "细裂", "撕开", "血指印", "泛黄", "脱漆", "摔碎", "血字", "破损", "开裂", "生锈")) or any(k in ref_upper for k in ("DAMAGED", "CRACKED", "BROKEN", "S1", "S2"))

    if is_damaged:
        for pv in prop_views:
            scode = str(pv.get("state_code") or "").upper()
            slabel = str(pv.get("state_label") or "")
            if any(k in scode for k in ("S1", "S2", "CRACK", "BROKEN", "DAMAGE")) or any(k in slabel for k in ("裂", "损", "伤", "撕", "血", "锈")):
                return {
                    "damage_state_id": pv.get("damage_state_id"),
                    "prop_detail_view_id": pv.get("detail_view_id"),
                    "asset_key": pv.get("asset_key"),
                    "view_type": pv.get("view_type") or "macro_feature",
                }

    # 3. 初始完好或基准状态
    for pv in prop_views:
        scode = str(pv.get("state_code") or "").upper()
        if "S0" in scode or "PRISTINE" in scode or pv.get("is_benchmark") == 1:
            return {
                "damage_state_id": pv.get("damage_state_id"),
                "prop_detail_view_id": pv.get("detail_view_id"),
                "asset_key": pv.get("asset_key"),
                "view_type": pv.get("view_type") or "macro_feature",
            }

    first_pv = prop_views[0]
    return {
        "damage_state_id": first_pv.get("damage_state_id"),
        "prop_detail_view_id": first_pv.get("detail_view_id"),
        "asset_key": first_pv.get("asset_key") or default_res["asset_key"],
        "view_type": first_pv.get("view_type") or "macro_feature",
    }


def _select_scene_zone_and_view(
    scene_info: dict[str, Any],
    scene_views: list[dict[str, Any]] | None,
    shot_type: str = "",
    action: str = "",
    raw_ref: str = "",
) -> dict[str, Any]:
    """根据分镜景别、空间描述与引用代号，精确定位场景二级空间机位 (scene_zones) 与三级切片视图 (scene_weathering_views)。

    实现场景二级机位与三级做旧切片视图的精准只读匹配，支持极简按需收敛（单建立镜头合法为 NULL）：
    1. raw_ref 显式包含具体切片视图 Token (如 Z01, Z02, T1_WIDE, T2_STRUCT, T3, 广角, 空间结构)；
    2. 分镜景别 (framing/shot_type) 与动作智能映射：
       - 远景/全景/大全景 (EWS, WS, FS, 全景, 远景, 大全景): 优先 layer_type="T1_WIDE"；
       - 中景/中近景/特写/局部 (MS, MCU, CU, 特写, 局部): 优先 layer_type="T2_STRUCT_VIEW"；
    3. 基石回退：首选 scene_info 自带的 scene_zone_id 与 scene_weathering_view_id，若仍为空则取候选列表首项。
    """
    default_res = {
        "scene_zone_id": scene_info.get("scene_zone_id"),
        "scene_weathering_view_id": scene_info.get("scene_weathering_view_id"),
        "asset_key": scene_info.get("benchmark_asset_key") or "",
        "layer_type": "T1_WIDE",
    }
    if not scene_views:
        return default_res

    ref_upper = (raw_ref or "").upper()
    shot_upper = (shot_type or "").upper()
    act_text = action or ""

    # 1. 检查 raw_ref 是否显式精确匹配某一切片的 asset_key 或 zone_code
    for sv in scene_views:
        v_key = str(sv.get("view_asset_key") or "").upper()
        z_code = str(sv.get("zone_code") or "").upper()
        if v_key and (v_key == ref_upper or ref_upper in v_key):
            return {
                "scene_zone_id": sv.get("zone_id") or default_res["scene_zone_id"],
                "scene_weathering_view_id": sv.get("view_id") or default_res["scene_weathering_view_id"],
                "asset_key": sv.get("view_asset_key") or default_res["asset_key"],
                "layer_type": sv.get("layer_type") or "T1_WIDE",
            }
        if z_code and (z_code == ref_upper or ref_upper in z_code):
            return {
                "scene_zone_id": sv.get("zone_id") or default_res["scene_zone_id"],
                "scene_weathering_view_id": sv.get("view_id") or default_res["scene_weathering_view_id"],
                "asset_key": sv.get("view_asset_key") or default_res["asset_key"],
                "layer_type": sv.get("layer_type") or "T1_WIDE",
            }

    # 2. 检查景别与空间结构
    is_wide = (
        any(k in shot_upper for k in ("FS", "WS", "EWS", "WIDE", "FULL"))
        or any(k in shot_type for k in ("全景", "远景", "大全景"))
        or any(k in act_text for k in ("环视", "全景", "空镜", "大厅", "走廊尽头"))
    )
    if is_wide:
        for sv in scene_views:
            if sv.get("layer_type") == "T1_WIDE" and sv.get("view_id"):
                return {
                    "scene_zone_id": sv.get("zone_id") or default_res["scene_zone_id"],
                    "scene_weathering_view_id": sv.get("view_id") or default_res["scene_weathering_view_id"],
                    "asset_key": sv.get("view_asset_key") or default_res["asset_key"],
                    "layer_type": "T1_WIDE",
                }

    is_struct = (
        any(k in shot_upper for k in ("MS", "MCU", "CU"))
        or any(k in shot_type for k in ("中景", "特写", "近景"))
        or any(k in act_text for k in ("局部", "门前", "桌前", "角落", "窗边"))
    )
    if is_struct:
        for sv in scene_views:
            if sv.get("layer_type") == "T2_STRUCT_VIEW" and sv.get("view_id"):
                return {
                    "scene_zone_id": sv.get("zone_id") or default_res["scene_zone_id"],
                    "scene_weathering_view_id": sv.get("view_id") or default_res["scene_weathering_view_id"],
                    "asset_key": sv.get("view_asset_key") or default_res["asset_key"],
                    "layer_type": "T2_STRUCT_VIEW",
                }

    # 3. 候选视图中优先选用同时具备 zone_id 与 view_id 的基准记录
    for sv in scene_views:
        if sv.get("zone_id") and sv.get("view_id"):
            return {
                "scene_zone_id": sv.get("zone_id"),
                "scene_weathering_view_id": sv.get("view_id"),
                "asset_key": sv.get("view_asset_key") or default_res["asset_key"],
                "layer_type": sv.get("layer_type") or "T1_WIDE",
            }

    # 4. 保底返回首个视图或默认基准
    first_sv = scene_views[0]
    return {
        "scene_zone_id": first_sv.get("zone_id") or default_res["scene_zone_id"],
        "scene_weathering_view_id": first_sv.get("view_id") or default_res["scene_weathering_view_id"],
        "asset_key": first_sv.get("view_asset_key") or default_res["asset_key"],
        "layer_type": first_sv.get("layer_type") or "T1_WIDE",
    }


def _load_stage6_asset_lookup_maps(
    db: Session,
    drama_id: int,
    episode_id: int | None = None,
) -> dict[str, Any]:
    """加载 Stage 6 权威资产真值表映射字典（scenes / characters / props 三级体系 + voice_profiles）。

    【核心职责与三级实体穿透规范】
    1. 严格限定 `WHERE drama_id = :drama_id AND deleted_at IS NULL`，杜绝跨剧本资产串库污染。
    2. 场景三级映射 (Tier 1: scenes -> Tier 2: scene_zones -> Tier 3: scene_weathering_views):
       - 支持反解出 scene_id, scene_zone_id, scene_weathering_view_id，以及场景全景资产 Token。
    3. 角色三级映射 (Tier 1: characters & character_libraries -> Tier 2: character_stages -> Tier 3: character_stage_views):
       - 同时支持通过人物名、阶段 Code (如 T1_BASE)、三级切片 Key (如 CHAR_LUCHEN_T1_4V_FRONT) 精准反解出
         character_id, character_lib_id, character_stage_id, stage_view_id。
    4. 道具三级映射 (Tier 1: props -> Tier 2: prop_damage_states -> Tier 3: prop_detail_views):
       - 支持通过道具名、破坏状态 Code (如 S1_CRACKED)、三级微距切片 Key (如 PROP_JADE_S1_ACTION) 精准反解出
         prop_id, damage_state_id, prop_detail_view_id。
    5. 角色母音档案映射：加载 character_voice_profiles，供 storyboard_audios 自动绑定 voice_profile_id。
    """
    scene_map: dict[str, dict[str, Any]] = {}
    char_map: dict[str, dict[str, Any]] = {}
    prop_map: dict[str, dict[str, Any]] = {}
    voice_by_char_id: dict[int, dict[str, Any]] = {}
    scene_by_id: dict[int, dict[str, Any]] = {}
    char_by_id: dict[int, dict[str, Any]] = {}
    char_by_lib_id: dict[int, dict[str, Any]] = {}
    prop_by_id: dict[int, dict[str, Any]] = {}
    default_scene: dict[str, Any] | None = None

    now = now_iso()
    log.debug("【Stage7资产字典】开始加载 drama_id=%s (episode_id=%s) 三级资产映射树...", drama_id, episode_id)

    # 1. 加载 scenes 主表 (Tier-1) + scene_zones 二级表 (Tier-2) + scene_weathering_views 三级切片表 (Tier-3)
    try:
        scene_rows = fetch_all(
            db,
            "SELECT * FROM scenes WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 scenes 表异常（可能处于 Mock 环境）: %s", exc)
        scene_rows = []

    for r in scene_rows or []:
        if not isinstance(r, dict) or not isinstance(r.get("id"), int):
            continue
        sid = int(r["id"])
        loc = str(r.get("location") or "").strip()
        clean_loc = AssetProtocolHelper.sanitize_scene_location(loc)
        s_time = str(r.get("time") or "").strip()
        s_code = str(r.get("scene_code") or f"ENV_{sid}").strip()
        b_key = str(r.get("benchmark_asset_key") or s_code).strip()
        s_info = {
            "scene_id": sid,
            "scene_zone_id": None,
            "scene_weathering_view_id": None,
            "location": loc,
            "clean_location": clean_loc,
            "time": s_time,
            "scene_code": s_code,
            "benchmark_asset_key": b_key,
            "episode_id": r.get("episode_id"),
        }
        scene_by_id[sid] = s_info
        if default_scene is None:
            default_scene = s_info
        elif episode_id is not None and r.get("episode_id") == episode_id:
            default_scene = s_info

        loc_tok = AssetProtocolHelper.chinese_to_token(loc) if loc else ""
        clean_tok = AssetProtocolHelper.chinese_to_token(clean_loc) if clean_loc else ""
        raw_scene_keys = [str(sid), f"ENV_{sid}", f"SCENE_{sid}", s_code, b_key, loc, f"{loc}_{s_time}"]
        if clean_loc and clean_loc != loc:
            raw_scene_keys.extend([clean_loc, f"{clean_loc}_{s_time}"])
        if loc_tok:
            raw_scene_keys.extend([loc_tok, f"ENV_{loc_tok}", f"SCENE_{loc_tok}"])
        if clean_tok and clean_tok != loc_tok:
            raw_scene_keys.extend([clean_tok, f"ENV_{clean_tok}", f"SCENE_{clean_tok}"])
        for raw_k in raw_scene_keys:
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    scene_map.setdefault(cand, s_info)

    # 级联加载 scene_zones 二级子空间与 scene_weathering_views 三级做旧切片
    scene_views_by_scene_id: dict[int, list[dict[str, Any]]] = {}
    try:
        sz_rows = fetch_all(
            db,
            """
            SELECT sz.id AS zone_id, sz.scene_id, sz.zone_code, sz.zone_name,
                   swv.id AS view_id, swv.asset_key AS view_asset_key, swv.layer_type
            FROM scene_zones sz
            LEFT JOIN scene_weathering_views swv ON swv.scene_zone_id = sz.id AND swv.deleted_at IS NULL
            WHERE sz.drama_id = :drama_id AND sz.deleted_at IS NULL
            ORDER BY sz.id ASC, swv.is_benchmark DESC, swv.is_primary DESC, swv.id ASC
            """,
            {"drama_id": drama_id},
        )
        for szr in sz_rows or []:
            if not isinstance(szr, dict):
                continue
            sid = szr.get("scene_id")
            zid = szr.get("zone_id")
            vid = szr.get("view_id")
            if isinstance(sid, int) and sid in scene_by_id:
                base_s_info = scene_by_id[sid]
                # 记录该机位/切片视图
                if isinstance(zid, int):
                    sv_entry = {
                        "zone_id": int(zid),
                        "zone_code": str(szr.get("zone_code") or ""),
                        "zone_name": str(szr.get("zone_name") or ""),
                        "view_id": int(vid) if isinstance(vid, int) else None,
                        "view_asset_key": str(szr.get("view_asset_key") or ""),
                        "layer_type": str(szr.get("layer_type") or "T1_WIDE"),
                    }
                    scene_views_by_scene_id.setdefault(sid, []).append(sv_entry)

                # 构造包含二级与三级切片外键的精细场景字典
                refined_s_info = {
                    **base_s_info,
                    "scene_zone_id": int(zid) if isinstance(zid, int) else None,
                    "scene_weathering_view_id": int(vid) if isinstance(vid, int) else None,
                    "benchmark_asset_key": str(szr.get("view_asset_key") or base_s_info.get("benchmark_asset_key") or ""),
                }
                # 如果主表还未确定二级 zone，默认由首个 zone_id 回填；三级 view_id 同理回填
                if base_s_info.get("scene_zone_id") is None and isinstance(zid, int):
                    base_s_info["scene_zone_id"] = zid
                if base_s_info.get("scene_weathering_view_id") is None and isinstance(vid, int):
                    base_s_info["scene_weathering_view_id"] = vid

                for rk in (szr.get("zone_code"), szr.get("zone_name"), szr.get("view_asset_key")):
                    if rk:
                        for cand in _extract_core_asset_prefixes(str(rk)):
                            if cand:
                                scene_map.setdefault(cand, refined_s_info)
    except Exception as exc:
        log.debug("【Stage7资产字典】加载 scene_zones / scene_weathering_views 异常: %s", exc)

    # 杜绝虚假自愈：若阶段 6 场景只有单一建立镜头（即无 scene_zones 记录），
    # 则 scene_zone_id 与 scene_weathering_view_id 保持为 None，严禁伪造虚拟外键或向阶段 6 资产库自动插入假数据
    for sid, sinfo in scene_by_id.items():
        existing_sz = scene_views_by_scene_id.get(sid) or []
        if existing_sz:
            first_sz = existing_sz[0]
            if sinfo.get("scene_zone_id") is None:
                sinfo["scene_zone_id"] = first_sz.get("zone_id")
            if sinfo.get("scene_weathering_view_id") is None:
                sinfo["scene_weathering_view_id"] = first_sz.get("view_id")

        s_loc = sinfo.get("location") or f"场景_{sid}"
        s_time = sinfo.get("time") or "日景"
        s_code = sinfo.get("scene_code") or f"ENV_{sid}"
        b_key = sinfo.get("benchmark_asset_key") or s_code
        for cand in [str(sid), f"ENV_{sid}", f"SCENE_{sid}", s_code, b_key, s_loc, f"{s_loc}_{s_time}"]:
            if cand:
                for c in _extract_core_asset_prefixes(str(cand)):
                    if c:
                        scene_map.setdefault(c, sinfo)

    # 2. 加载 character_libraries 与 characters 表，确保严格对齐本剧 characters.id
    lib_by_source_id: dict[int, int] = {}
    lib_by_name: dict[str, int] = {}
    try:
        lib_rows = fetch_all(
            db,
            "SELECT * FROM character_libraries WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception:
        lib_rows = []

    for lr in lib_rows or []:
        if not isinstance(lr, dict) or not isinstance(lr.get("id"), int):
            continue
        lid = int(lr["id"])
        lname = str(lr.get("name") or "").strip()
        raw_src_id = lr.get("source_id")
        parsed_src_id: int | None = None
        if isinstance(raw_src_id, int):
            parsed_src_id = raw_src_id
        elif isinstance(raw_src_id, str) and raw_src_id.strip().isdigit():
            parsed_src_id = int(raw_src_id.strip())
        if parsed_src_id is not None and parsed_src_id > 0:
            lib_by_source_id[parsed_src_id] = lid
        if lname:
            lib_by_name[lname.upper()] = lid

        effective_char_id = parsed_src_id if (parsed_src_id is not None and parsed_src_id > 0) else lid
        c_tok = AssetProtocolHelper.chinese_to_token(lname) if lname else f"{effective_char_id}"
        c_info = {
            "character_lib_id": lid,
            "character_id": effective_char_id,
            "character_stage_id": None,
            "stage_view_id": None,
            "name": lname or f"CHAR_{effective_char_id}",
            "character_code": f"CHAR_{c_tok}",
            "benchmark_asset_key": f"CHAR_{c_tok}_T1_BASE_PORTRAIT",
        }
        char_by_lib_id[lid] = c_info
        char_by_id.setdefault(effective_char_id, c_info)
        for raw_k in (str(lid), str(effective_char_id), f"CHAR_{lid}", f"CHAR_{effective_char_id}", f"CHAR_{c_tok}", lname):
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    char_map.setdefault(cand, c_info)

    try:
        char_rows = fetch_all(
            db,
            "SELECT * FROM characters WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 characters 表异常（可能处于 Mock 环境）: %s", exc)
        char_rows = []

    for cr in char_rows or []:
        if not isinstance(cr, dict) or not isinstance(cr.get("id"), int):
            continue
        cid = int(cr["id"])
        cname = str(cr.get("name") or f"CHAR_{cid}").strip()
        ccode = str(cr.get("character_code") or f"CHAR_{cid}").strip()
        b_key = str(cr.get("benchmark_asset_key") or ccode).strip()
        cn_tok = AssetProtocolHelper.chinese_to_token(cname) if cname else ""

        # 查找或自动同步创建对应的 character_libraries 记录（兼容旧表关联与双 ID 对齐）
        lib_id = lib_by_source_id.get(cid) or lib_by_name.get(cname.upper())
        if lib_id is None:
            try:
                ins_lib = db.execute(
                    text("""
                        INSERT INTO character_libraries (
                            drama_id, name, description, appearance,
                            source_type, source_id, created_at, updated_at
                        ) VALUES (
                            :drama_id, :name, :description, :appearance,
                            'stage6_character', :source_id, :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "name": cname,
                        "description": str(cr.get("description") or cr.get("personality") or ""),
                        "appearance": str(cr.get("appearance") or ""),
                        "source_id": str(cid),
                        "now": str(now),
                    },
                )
                raw_lid = getattr(ins_lib, "lastrowid", None)
                if isinstance(raw_lid, int) and raw_lid > 0:
                    lib_id = raw_lid
                    lib_by_source_id[cid] = lib_id
                    lib_by_name[cname.upper()] = lib_id
            except Exception as exc:
                log.debug("【Stage7资产字典】自动补齐 character_libraries 失败，回退使用 characters.id=%s: %s", cid, exc)
        if not isinstance(lib_id, int) or lib_id <= 0:
            lib_id = cid

        c_info = {
            "character_lib_id": lib_id,
            "character_id": cid,
            "character_stage_id": None,
            "stage_view_id": None,
            "name": cname,
            "character_code": ccode,
            "benchmark_asset_key": b_key,
        }
        char_by_id[cid] = c_info
        char_by_lib_id[lib_id] = c_info
        char_by_lib_id.setdefault(cid, c_info)

        raw_char_keys = [str(cid), str(lib_id), f"CHAR_{cid}", f"CHAR_{lib_id}", ccode, b_key, cname]
        if cn_tok:
            raw_char_keys.extend([cn_tok, f"CHAR_{cn_tok}", f"CHAR_{cn_tok}_T1_BASE_PORTRAIT"])
        for raw_k in raw_char_keys:
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    # 权威本剧 characters 表记录最高优先级覆盖
                    char_map[cand] = c_info

    # 级联加载 character_stages (Tier-2) 与 character_stage_views (Tier-3) 切片 Key 映射回本剧角色
    char_views_by_char_id: dict[int, list[dict[str, Any]]] = {}
    char_views_by_lib_id: dict[int, list[dict[str, Any]]] = {}
    try:
        csv_rows = fetch_all(
            db,
            """
            SELECT cs.id AS stage_id, cs.character_id, cs.stage_code, cs.stage_name,
                   csv.id AS view_id, csv.asset_key, csv.view_type, csv.is_benchmark, csv.is_primary
            FROM character_stages cs
            LEFT JOIN character_stage_views csv ON csv.character_stage_id = cs.id AND csv.deleted_at IS NULL
            WHERE cs.drama_id = :drama_id AND cs.deleted_at IS NULL
            ORDER BY cs.id ASC, csv.is_benchmark DESC, csv.id ASC
            """,
            {"drama_id": drama_id},
        )
        for csvr in csv_rows or []:
            if not isinstance(csvr, dict):
                continue
            cid = csvr.get("character_id")
            stid = csvr.get("stage_id")
            vid = csvr.get("view_id")
            # 兼容 characters.id 与 character_libraries.id 关联
            target_c_info = None
            if isinstance(cid, int):
                target_c_info = char_by_id.get(cid) or char_by_lib_id.get(cid)
            if target_c_info:
                base_c_info = target_c_info
                # 记录角色当前默认阶段 ID
                if base_c_info.get("character_stage_id") is None and isinstance(stid, int):
                    base_c_info["character_stage_id"] = stid
                if base_c_info.get("stage_view_id") is None and isinstance(vid, int):
                    base_c_info["stage_view_id"] = vid

                if isinstance(vid, int):
                    v_item = {
                        "stage_id": int(stid) if isinstance(stid, int) else None,
                        "stage_code": str(csvr.get("stage_code") or ""),
                        "stage_name": str(csvr.get("stage_name") or ""),
                        "view_id": int(vid),
                        "view_type": str(csvr.get("view_type") or "main_portrait"),
                        "asset_key": str(csvr.get("asset_key") or ""),
                        "is_benchmark": int(csvr.get("is_benchmark") or 0),
                        "is_primary": int(csvr.get("is_primary") or 0),
                    }
                    if isinstance(cid, int):
                        char_views_by_char_id.setdefault(cid, []).append(v_item)
                    if isinstance(target_c_info.get("character_lib_id"), int):
                        char_views_by_lib_id.setdefault(target_c_info["character_lib_id"], []).append(v_item)

                slice_c_info = {
                    **base_c_info,
                    "character_stage_id": int(stid) if isinstance(stid, int) else None,
                    "stage_view_id": int(vid) if isinstance(vid, int) else None,
                    "benchmark_asset_key": str(csvr.get("asset_key") or base_c_info.get("benchmark_asset_key") or ""),
                }
                for rk in (csvr.get("stage_code"), csvr.get("stage_name"), csvr.get("asset_key")):
                    if rk:
                        norm_rk = _normalize_asset_lookup_token(str(rk))
                        if norm_rk:
                            char_map[norm_rk] = slice_c_info
                        for cand in _extract_core_asset_prefixes(str(rk)):
                            if cand:
                                char_map[cand] = slice_c_info
    except Exception as exc:
        log.debug("【Stage7资产字典】加载 character_stages / character_stage_views 异常: %s", exc)

    # 杜绝虚假自愈：若阶段 6 角色未生成 character_stages 或 views，保持 None，严禁伪造虚拟外键或向阶段 6 资产库自动插入假数据
    for cid, cinfo in char_by_id.items():
        c_views = char_views_by_char_id.get(cid) or []
        if c_views:
            first_v = c_views[0]
            if cinfo.get("character_stage_id") is None:
                cinfo["character_stage_id"] = first_v.get("stage_id")
            if cinfo.get("stage_view_id") is None:
                cinfo["stage_view_id"] = first_v.get("view_id")

    # 补充加载 character_voice_profiles（供 storyboard_audios 绑定角色音色档案）
    voice_by_name: dict[str, dict[str, Any]] = {}
    default_narrator_voice: dict[str, Any] | None = None
    try:
        vp_rows = fetch_all(
            db,
            "SELECT * FROM character_voice_profiles WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY is_master_card DESC, id ASC",
            {"drama_id": drama_id},
        )
        for vpr in vp_rows or []:
            if not isinstance(vpr, dict) or not isinstance(vpr.get("id"), int):
                continue
            vp_cid = vpr.get("character_id")
            if isinstance(vp_cid, int) and vp_cid not in voice_by_char_id:
                voice_by_char_id[vp_cid] = vpr
                if vp_cid in char_by_id:
                    cname = char_by_id[vp_cid].get("name", "")
                    if cname:
                        voice_by_name[cname.strip().upper()] = vpr
            # 记录旁白母音
            m_key = str(vpr.get("master_voice_key") or "").upper()
            if "NARRATOR" in m_key or "旁白" in str(vpr.get("voice_label") or ""):
                if default_narrator_voice is None:
                    default_narrator_voice = vpr
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 character_voice_profiles 表异常: %s", exc)

    # 3. 加载 props 主表（Tier-1）+ prop_damage_states（Tier-2）+ prop_detail_views（Tier-3）+ assets 道具记录
    try:
        prop_rows = fetch_all(
            db,
            "SELECT * FROM props WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 props 表异常（可能处于 Mock 环境）: %s", exc)
        prop_rows = []

    for pr in prop_rows or []:
        if not isinstance(pr, dict) or not isinstance(pr.get("id"), int):
            continue
        pid = int(pr["id"])
        pname = str(pr.get("name") or f"PROP_{pid}").strip()
        pcode = str(pr.get("prop_code") or f"PROP_{pid}").strip()
        b_key = str(pr.get("benchmark_asset_key") or pcode).strip()
        pn_tok = AssetProtocolHelper.chinese_to_token(pname) if pname else ""
        p_aliases = _extract_prop_aliases_and_keywords(pname)
        p_info = {
            "prop_id": pid,
            "damage_state_id": None,
            "prop_detail_view_id": None,
            "name": pname,
            "prop_code": pcode,
            "benchmark_asset_key": b_key,
            "aliases": p_aliases,
        }
        prop_by_id[pid] = p_info
        raw_prop_keys = [str(pid), f"PROP_{pid}", pcode, f"PROP_{pcode}", b_key, pname]
        if pn_tok:
            raw_prop_keys.extend([pn_tok, f"PROP_{pn_tok}", f"PROP_{pn_tok}_S0_STATIC", f"PROP_{pn_tok}_T1_STATIC"])
        for a_tok in p_aliases:
            if a_tok not in raw_prop_keys:
                raw_prop_keys.append(a_tok)
        for raw_k in raw_prop_keys:
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    prop_map.setdefault(cand, p_info)

    # 级联加载 Tier-2 prop_damage_states 与 Tier-3 prop_detail_views，映射切片 Key 到父级 prop_id + damage_state_id + prop_detail_view_id
    prop_views_by_prop_id: dict[int, list[dict[str, Any]]] = {}
    try:
        pds_rows = fetch_all(
            db,
            """
            SELECT pds.id AS damage_state_id, pds.prop_id, pds.state_code, pds.state_label,
                   pdv.id AS detail_view_id, pdv.asset_key, pdv.view_type, pdv.visual_prompt
            FROM prop_damage_states pds
            LEFT JOIN prop_detail_views pdv ON pdv.damage_state_id = pds.id AND pdv.deleted_at IS NULL
            WHERE pds.drama_id = :drama_id AND pds.deleted_at IS NULL
            ORDER BY pds.id ASC, pdv.is_benchmark DESC, pdv.id ASC
            """,
            {"drama_id": drama_id},
        )
        for pdsr in pds_rows or []:
            if not isinstance(pdsr, dict):
                continue
            pid = pdsr.get("prop_id")
            ds_id = pdsr.get("damage_state_id")
            dvid = pdsr.get("detail_view_id")
            if isinstance(pid, int) and pid in prop_by_id:
                base_p = prop_by_id[pid]
                if base_p.get("damage_state_id") is None and isinstance(ds_id, int):
                    base_p["damage_state_id"] = ds_id
                if base_p.get("prop_detail_view_id") is None and isinstance(dvid, int):
                    base_p["prop_detail_view_id"] = dvid

                pv_item = {
                    "damage_state_id": int(ds_id) if isinstance(ds_id, int) else None,
                    "state_code": str(pdsr.get("state_code") or ""),
                    "state_label": str(pdsr.get("state_label") or ""),
                    "detail_view_id": int(dvid) if isinstance(dvid, int) else None,
                    "asset_key": str(pdsr.get("asset_key") or ""),
                    "view_type": str(pdsr.get("view_type") or "macro_feature"),
                    "visual_prompt": str(pdsr.get("visual_prompt") or ""),
                }
                prop_views_by_prop_id.setdefault(pid, []).append(pv_item)

                slice_p_info = {
                    **base_p,
                    "damage_state_id": int(ds_id) if isinstance(ds_id, int) else None,
                    "prop_detail_view_id": int(dvid) if isinstance(dvid, int) else None,
                    "benchmark_asset_key": str(pdsr.get("asset_key") or base_p.get("benchmark_asset_key") or ""),
                }
                for rk in (pdsr.get("state_code"), pdsr.get("state_label"), pdsr.get("asset_key")):
                    if rk:
                        norm_rk = _normalize_asset_lookup_token(str(rk))
                        if norm_rk:
                            prop_map[norm_rk] = slice_p_info
                        for cand in _extract_core_asset_prefixes(str(rk)):
                            if cand:
                                prop_map[cand] = slice_p_info
    except Exception as exc:
        log.warning("【Stage7资产字典】加载 prop_damage_states / prop_detail_views 异常: %s", exc)

    # 杜绝虚假自愈：若阶段 6 道具未生成 damage_states 或 detail_views（短剧中绝大部分道具为完好形态），
    # damage_state_id 与 prop_detail_view_id 保持为 None，严禁伪造虚拟外键或向阶段 6 资产库自动插入假数据
    for pid, pinfo in prop_by_id.items():
        p_views = prop_views_by_prop_id.get(pid) or []
        if p_views:
            first_pv = p_views[0]
            if pinfo.get("damage_state_id") is None:
                pinfo["damage_state_id"] = first_pv.get("damage_state_id")
            if pinfo.get("prop_detail_view_id") is None:
                pinfo["prop_detail_view_id"] = first_pv.get("detail_view_id")

    # 加载 assets 表中 category='prop' 的资产索引（覆盖仅在 assets 注册过 asset_key 的道具）
    try:
        asset_prop_rows = fetch_all(
            db,
            "SELECT name, asset_key FROM assets WHERE drama_id = :drama_id AND category = 'prop' AND deleted_at IS NULL",
            {"drama_id": drama_id},
        )
        for apr in asset_prop_rows or []:
            if not isinstance(apr, dict):
                continue
            a_name = str(apr.get("name") or "").strip()
            a_key = str(apr.get("asset_key") or "").strip()
            matched_p = _resolve_asset_from_map(a_name, prop_map) or _resolve_asset_from_map(a_key, prop_map)
            if matched_p and a_key:
                for cand in _extract_core_asset_prefixes(a_key):
                    if cand:
                        prop_map.setdefault(cand, matched_p)
    except Exception:
        pass

    log.debug(
        "【Stage7资产字典加载完成】drama_id=%s, episode_id=%s -> scenes=%d(索引键=%d), chars=%d(索引键=%d), props=%d(索引键=%d), voices=%d",
        drama_id,
        episode_id,
        len(scene_by_id),
        len(scene_map),
        len(char_by_id),
        len(char_map),
        len(prop_by_id),
        len(prop_map),
        len(voice_by_char_id),
    )
    return {
        "scene_map": scene_map,
        "char_map": char_map,
        "prop_map": prop_map,
        "voice_by_char_id": voice_by_char_id,
        "voice_by_name": voice_by_name,
        "default_narrator_voice": default_narrator_voice,
        "scene_by_id": scene_by_id,
        "scene_views_by_scene_id": scene_views_by_scene_id,
        "char_by_id": char_by_id,
        "char_by_lib_id": char_by_lib_id,
        "char_views_by_char_id": char_views_by_char_id,
        "prop_views_by_prop_id": prop_views_by_prop_id,
        "prop_by_id": prop_by_id,
        "default_scene": default_scene,
    }


def _resolve_asset_from_map(raw_ref: Any, lookup_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """在 Stage 6 资产映射字典中执行「精确匹配 -> 核心前缀匹配 -> 安全词元边界匹配 -> 中文名称包含」四级检索。

    【防串库与防碰撞保障】
    彻底废除原先 `len(k) >= 2 and (k in norm_full or norm_full in k)` 的无边界短字符串子串包含匹配，
    杜绝 `CHAR_1` 错误命中 `CHAR_10_T1_BASE` 或短编号跨角色误连。
    """
    if not raw_ref or not lookup_map:
        return None
    raw_str = str(raw_ref).strip()
    if not raw_str:
        return None
    candidates = _extract_core_asset_prefixes(raw_str)
    # 1. 精确候选键匹配（全名 Token -> 二段式前缀 -> 核心实体 Token）
    for cand in candidates:
        if cand in lookup_map:
            return lookup_map[cand]

    # 2. 尝试将中文引用转为标准英文拼音 Token 后再次精确匹配
    if re.search(r"[\u4e00-\u9fa5]", raw_str):
        cn_tok = AssetProtocolHelper.chinese_to_token(raw_str)
        if cn_tok and cn_tok != "UNKNOWN":
            for prefix in (cn_tok, f"CHAR_{cn_tok}", f"PROP_{cn_tok}", f"ENV_{cn_tok}", f"SCENE_{cn_tok}"):
                if prefix in lookup_map:
                    return lookup_map[prefix]

    # 3. 安全词元边界匹配（按下划线分词后比对非通用核心词元，绝不匹配纯数字或通用前缀）
    norm_full = candidates[0] if candidates else ""
    norm_parts = [
        p for p in norm_full.split("_")
        if len(p) >= 3 and not p.isdigit() and p not in _GENERIC_ASSET_SEGMENTS
    ]
    if norm_parts:
        for k, info in lookup_map.items():
            if k.isdigit() or k in _GENERIC_ASSET_SEGMENTS:
                continue
            k_parts = [
                kp for kp in k.split("_")
                if len(kp) >= 3 and not kp.isdigit() and kp not in _GENERIC_ASSET_SEGMENTS
            ]
            if k_parts and any(np == kp for np in norm_parts for kp in k_parts):
                return info

    # 4. 中文实体名称安全包含匹配（仅针对长度 >= 2 的中文实体名称，不针对英文/数字编号）
    if re.search(r"[\u4e00-\u9fa5]{2,}", norm_full):
        for k, info in lookup_map.items():
            if re.search(r"[\u4e00-\u9fa5]{2,}", k) and (k in norm_full or norm_full in k):
                return info
    return None


def _cascade_delete_episode_storyboards(db: Session, episode_id: int) -> None:
    """幂等级联清理指定集的分镜六表记录，确保重跑时 100% 覆盖。

    采用两阶段精准清理：
    1. 显式查出属于该集的全部旧 storyboard_id 列表；
    2. 使用具体 ID 集合精准清空 5 张从表（解除外键与主表依赖）；
    3. 彻底删除主表镜头，并校验主表残留行数必须为 0。
    """
    # 阶段 1：精准获取当前集存在的所有旧分镜 ID
    old_sb_rows = db.execute(
        text("SELECT id FROM storyboards WHERE episode_id = :ep_id"),
        {"ep_id": episode_id},
    ).fetchall()
    old_sb_ids = [r[0] for r in old_sb_rows if r[0] is not None]

    log.info(
        "【Stage7六表级联清理】准备清理 episode_id=%s 的旧分镜数据，探测到旧分镜数: %s (IDs: %s)",
        episode_id,
        len(old_sb_ids),
        old_sb_ids[:10] if len(old_sb_ids) > 10 else old_sb_ids,
    )

    # 阶段 2：如果存在旧分镜，先精确清除所有从表数据（先从后主，解除外键与引用依赖）
    if old_sb_ids:
        # 分批处理防止极端情况下 SQL 占位符超限，通常单集镜头数为 10~100
        batch_size = 500
        for i in range(0, len(old_sb_ids), batch_size):
            chunk = old_sb_ids[i : i + batch_size]
            id_in_clause = ",".join(str(int(sid)) for sid in chunk)

            # 0. 清理分镜字幕从表 storyboard_subtitles
            db.execute(
                text(f"""
                    DELETE FROM storyboard_subtitles
                    WHERE episode_id = :ep_id
                       OR storyboard_id IN ({id_in_clause})
                """),
                {"ep_id": episode_id},
            )
            # 1. 清理分镜音频轨从表 storyboard_audios
            db.execute(
                text(f"""
                    DELETE FROM storyboard_audios
                    WHERE episode_id = :ep_id
                       OR storyboard_id IN ({id_in_clause})
                """),
                {"ep_id": episode_id},
            )
            # 2. 清理分镜关键帧提示词从表 frame_prompts
            db.execute(
                text(f"DELETE FROM frame_prompts WHERE storyboard_id IN ({id_in_clause})"),
                {},
            )
            # 3. 清理分镜角色关联从表 storyboard_characters
            db.execute(
                text(f"DELETE FROM storyboard_characters WHERE storyboard_id IN ({id_in_clause})"),
                {},
            )
            # 4. 清理分镜道具关联从表 storyboard_props
            db.execute(
                text(f"DELETE FROM storyboard_props WHERE storyboard_id IN ({id_in_clause})"),
                {},
            )
    else:
        # 兜底清理可能残留孤儿数据的从表（仅根据 episode_id）
        db.execute(text("DELETE FROM storyboard_subtitles WHERE episode_id = :ep_id"), {"ep_id": episode_id})
        db.execute(text("DELETE FROM storyboard_audios WHERE episode_id = :ep_id"), {"ep_id": episode_id})

    # 阶段 3：清理分镜主表 storyboards
    db.execute(text("DELETE FROM storyboards WHERE episode_id = :ep_id"), {"ep_id": episode_id})

    # 阶段 4：清零断言验证（确保该集分镜主表在物理上已经 100% 清空，防止未成功删除导致追加）
    remaining = db.execute(
        text("SELECT COUNT(*) FROM storyboards WHERE episode_id = :ep_id"),
        {"ep_id": episode_id},
    ).scalar()
    if isinstance(remaining, int) and remaining > 0:
        raise RuntimeError(
            f"【Stage7六表级联清理失败】清理后 episode_id={episode_id} 仍残留 {remaining} 条主分镜记录，未成功清零，拒绝写入以防追加数据！"
        )
    log.info("【Stage7六表级联清理】episode_id=%s 旧分镜及全部关联从表已彻底物理清零。", episode_id)


def _persist_episode_storyboards_3tables(
    db: Session,
    drama_id: int,
    episode_id: int,
    storyboards: list[Any],
    status: str = "draft",
    now: str | None = None,
) -> dict[str, int]:
    """核心六表联动持久化函数：原子写入 storyboards 主表、frame_prompts 关键帧表、
    storyboard_characters 角色表、storyboard_props 道具表、storyboard_audios 音频表与 storyboard_subtitles 字幕表。
    """
    now_str = str(now or now_iso())
    _cascade_delete_episode_storyboards(db, episode_id)

    if not storyboards:
        log.debug("【Stage7六表落库】episode_id=%s 分镜列表为空，仅完成清理。", episode_id)
        return {
            "storyboards": 0,
            "frame_prompts": 0,
            "storyboard_characters": 0,
            "storyboard_props": 0,
            "storyboard_audios": 0,
            "storyboard_subtitles": 0,
        }

    log.info(
        "【Stage7六表落库】episode_id=%s 级联清理完毕，准备写入最新分镜数: %d",
        episode_id,
        len(storyboards),
    )

    asset_maps = _load_stage6_asset_lookup_maps(db, drama_id, episode_id=episode_id)
    scene_map = asset_maps["scene_map"]
    char_map = asset_maps["char_map"]
    prop_map = asset_maps["prop_map"]
    voice_by_char_id = asset_maps.get("voice_by_char_id", {})
    voice_by_name = asset_maps.get("voice_by_name", {})
    default_narrator_voice = asset_maps.get("default_narrator_voice")
    default_scene = asset_maps["default_scene"]
    scene_views_by_scene_id = asset_maps.get("scene_views_by_scene_id", {})
    scene_by_id = asset_maps.get("scene_by_id", {})
    char_by_id = asset_maps.get("char_by_id", {})
    char_views_by_char_id = asset_maps.get("char_views_by_char_id", {})
    prop_by_id = asset_maps.get("prop_by_id", {})
    prop_views_by_prop_id = asset_maps.get("prop_views_by_prop_id", {})

    # 物理资产门禁 (Asset Gatekeeper) 白名单集合：严格只读校验，杜绝任何悬空与伪造外键
    valid_scene_ids = set(scene_by_id.keys())
    valid_scene_zone_ids = {
        sv["zone_id"]
        for s_views in scene_views_by_scene_id.values()
        for sv in s_views
        if sv.get("zone_id") is not None
    }
    valid_scene_weathering_view_ids = {
        sv["view_id"]
        for s_views in scene_views_by_scene_id.values()
        for sv in s_views
        if sv.get("view_id") is not None
    }
    valid_char_ids = set(char_by_id.keys())
    valid_char_stage_ids = {
        cv["stage_id"]
        for c_views in char_views_by_char_id.values()
        for cv in c_views
        if cv.get("stage_id") is not None
    }
    valid_char_stage_view_ids = {
        cv["view_id"]
        for c_views in char_views_by_char_id.values()
        for cv in c_views
        if cv.get("view_id") is not None
    }
    valid_prop_ids = set(prop_by_id.keys())
    valid_prop_damage_state_ids = {
        pv["damage_state_id"]
        for p_views in prop_views_by_prop_id.values()
        for pv in p_views
        if pv.get("damage_state_id") is not None
    }
    valid_prop_detail_view_ids = {
        pv["detail_view_id"]
        for p_views in prop_views_by_prop_id.values()
        for pv in p_views
        if pv.get("detail_view_id") is not None
    }

    def _s_get(s: Any, key: str, default: Any = None) -> Any:
        if isinstance(s, dict):
            return s.get(key, default)
        return getattr(s, key, default)

    sb_count = 0
    fp_count = 0
    sb_char_count = 0
    sb_prop_count = 0
    sb_audio_count = 0
    sb_sub_count = 0
    global_seq_order = 1
    current_timeline_ms = 0

    # 阶段6与阶段7资产衔接门禁审计指标收集器
    audit_total_shots = len(storyboards)
    audit_scene_closed_count = 0
    audit_scene_zone_closed_count = 0
    audit_scene_view_closed_count = 0
    audit_char_slot_count = 0
    audit_char_tier3_closed_count = 0
    audit_prop_slot_count = 0
    audit_prop_tier3_closed_count = 0
    audit_dialogue_shots_count = 0
    audit_voice_bound_count = 0

    for idx, shot in enumerate(storyboards, start=1):
        lipsync_val = _dump_or_dict(_s_get(shot, "lipsync_dynamics"))
        audio_val = _s_get(shot, "audio") or {}
        if not isinstance(audio_val, dict):
            audio_val = _dump_or_dict(audio_val) or {}

        img_prompt = str(_s_get(shot, "image_prompt") or _s_get(shot, "visual_description") or "")
        vid_prompt = str(_s_get(shot, "video_prompt") or "")
        gen_mode = str(_s_get(shot, "generation_mode") or _s_get(shot, "creation_mode") or "single_frame")
        first_last_cfg = _s_get(shot, "first_last_config")
        if first_last_cfg and not isinstance(first_last_cfg, dict):
            first_last_cfg = _dump_or_dict(first_last_cfg)
        multi_img_cfg = _s_get(shot, "multi_image_config")
        if multi_img_cfg and not isinstance(multi_img_cfg, dict):
            multi_img_cfg = _dump_or_dict(multi_img_cfg)

        if not img_prompt:
            if gen_mode == "first_last_frame" and isinstance(first_last_cfg, dict):
                img_prompt = str(first_last_cfg.get("first_frame_prompt") or "")
                vid_prompt = vid_prompt or str(first_last_cfg.get("video_motion_prompt") or "")
            elif isinstance(multi_img_cfg, dict):
                img_prompt = str(multi_img_cfg.get("video_prompt") or "")
                vid_prompt = vid_prompt or str(multi_img_cfg.get("video_prompt") or "")

        shot_num = int(_s_get(shot, "shot_id") or _s_get(shot, "storyboard_number") or _s_get(shot, "shot_number") or idx)
        shot_dur = float(_s_get(shot, "duration_sec") or _s_get(shot, "duration") or 3.0)
        shot_type = str(_s_get(shot, "framing") or _s_get(shot, "shot_type") or "MCU 中近景")
        movement = str(_s_get(shot, "camera_motion") or _s_get(shot, "movement") or "推镜")
        target_engine = str(_s_get(shot, "target_engine") or "wan3.0")
        selection_rationale = str(_s_get(shot, "selection_rationale") or "")
        mode_b_audit_verdict = str(_s_get(shot, "mode_b_audit_verdict") or "PASS_9")
        raw_dialogue_field = str(
            audio_val.get("dialogue")
            or _s_get(shot, "dialogue")
            or _s_get(shot, "srt_text")
            or _s_get(shot, "dialogue_text")
            or ""
        )
        narration = str(audio_val.get("narration") or _s_get(shot, "narration") or "")
        raw_action_field = str(_s_get(shot, "dynamic_cue") or _s_get(shot, "action") or "")

        # 核心清洗：剥离台词中的说话人前缀与动作指示，分离出 pure_dialogue，并回流至 action
        extracted_speaker, pure_dialogue, clean_phonetic, combined_action, extracted_cues = _extract_pure_dialogue_and_action(
            raw_dialogue_field, raw_action_field
        )
        # 深度清洗：三权分立隔离台词中的拟音词/提示音/舞台动作，强化声学规范化
        raw_atm = str(
            audio_val.get("foley")
            or _s_get(shot, "foley_cue")
            or _s_get(shot, "atmosphere")
            or ""
        )
        pure_dialogue, enriched_foley, enriched_action = PromptSynthesizer.sanitize_dialogue_sound_action(
            raw_dialogue=pure_dialogue,
            raw_foley=raw_atm,
            raw_action=combined_action,
        )
        dialogue = pure_dialogue
        action = enriched_action
        clean_phonetic = clean_dialogue_text(dialogue) if dialogue else ""
        atmosphere = enriched_foley

        # 收集镜头引用的全部资产标识（显式字段 + 模式A首尾帧 + 模式B参考图列表）
        raw_scene_ref = str(_s_get(shot, "scene_asset_id") or _s_get(shot, "scene_ref") or _s_get(shot, "scene_name") or "").strip()
        raw_char_refs: list[str] = [
            str(x).strip() for x in (_s_get(shot, "character_asset_ids") or _s_get(shot, "characters") or _s_get(shot, "character_refs") or []) if str(x).strip()
        ]
        raw_prop_refs: list[str] = [
            str(x).strip() for x in (_s_get(shot, "prop_asset_ids") or _s_get(shot, "props") or _s_get(shot, "prop_refs") or []) if str(x).strip()
        ]

        all_ref_keys: list[str] = []
        if isinstance(first_last_cfg, dict):
            for fl_k in ("first_frame_asset_id", "last_frame_asset_id"):
                val = str(first_last_cfg.get(fl_k) or "").strip()
                if val and val not in all_ref_keys:
                    all_ref_keys.append(val)
        if isinstance(multi_img_cfg, dict):
            for ref_item in (multi_img_cfg.get("reference_assets") or []):
                val = str(ref_item or "").strip()
                if val and val not in all_ref_keys:
                    all_ref_keys.append(val)

        # 从综合参考资产键中自动归类未显式声明的 ENV_ / CHAR_ / PROP_
        for ref_k in all_ref_keys:
            upper_k = ref_k.upper()
            if upper_k.startswith(("ENV_", "SCENE_")) and not raw_scene_ref:
                raw_scene_ref = ref_k
            elif upper_k.startswith("CHAR_") and ref_k not in raw_char_refs:
                raw_char_refs.append(ref_k)
            elif upper_k.startswith("PROP_") and ref_k not in raw_prop_refs:
                raw_prop_refs.append(ref_k)

        if raw_scene_ref and raw_scene_ref not in all_ref_keys:
            all_ref_keys.insert(0, raw_scene_ref)
        for cr in raw_char_refs:
            if cr not in all_ref_keys:
                all_ref_keys.append(cr)
        for pr in raw_prop_refs:
            if pr not in all_ref_keys:
                all_ref_keys.append(pr)

        # 1) 解析 Stage 6 场景外键 (scenes.id, scene_zones.id, scene_weathering_views.id)
        # 实现 6 级收敛漏斗：从精确 asset_id -> 清洗后地点名 -> 原始地点名 -> 剧情文本扫描 -> 当前集最新场景 -> 全局兜底
        raw_shot_loc = str(_s_get(shot, "location") or "").strip()
        clean_shot_loc = AssetProtocolHelper.sanitize_scene_location(raw_shot_loc)

        resolved_scene_info: dict[str, Any] | None = None
        # 漏斗 1：raw_scene_ref 精确/前缀查找
        if raw_scene_ref:
            resolved_scene_info = _resolve_asset_from_map(raw_scene_ref, scene_map)
        # 漏斗 2：clean_shot_loc 清洗后地点名查找
        if resolved_scene_info is None and clean_shot_loc:
            resolved_scene_info = _resolve_asset_from_map(clean_shot_loc, scene_map)
        # 漏斗 3：原始 raw_shot_loc 查找
        if resolved_scene_info is None and raw_shot_loc:
            resolved_scene_info = _resolve_asset_from_map(raw_shot_loc, scene_map)
        # 漏斗 4：从动作与提示词中扫描已注册场景地点名（优先匹配最长地点字符串）
        if resolved_scene_info is None:
            shot_full_text = f"{action} {img_prompt} {vid_prompt} {dialogue} {narration}"
            for cand_sid, cand_sinfo in sorted(
                scene_by_id.items(),
                key=lambda x: len(str(x[1].get("location") or "")),
                reverse=True,
            ):
                cand_loc = str(cand_sinfo.get("location") or "").strip()
                cand_clean_loc = str(cand_sinfo.get("clean_location") or cand_loc).strip()
                if (cand_clean_loc and len(cand_clean_loc) >= 2 and cand_clean_loc in shot_full_text) or \
                   (cand_loc and len(cand_loc) >= 2 and cand_loc in shot_full_text):
                    resolved_scene_info = cand_sinfo
                    break
        # 漏斗 5：优先绑定当前集 (episode_id) 在 scenes 表中最新登记的物理场景
        if resolved_scene_info is None and episode_id is not None:
            ep_scenes = [
                s for s in scene_by_id.values()
                if s.get("episode_id") == episode_id
            ]
            if ep_scenes:
                resolved_scene_info = ep_scenes[-1]
        # 漏斗 6：全局 fallback default_scene
        if resolved_scene_info is None and default_scene is not None:
            resolved_scene_info = default_scene

        resolved_scene_id: int | None = None
        resolved_scene_zone_id: int | None = None
        resolved_scene_weathering_view_id: int | None = None
        resolved_location = str(_s_get(shot, "location") or "")
        
        # 严谨解析 time（时段环境：如"早/中/晚/深夜/暴雨夜"），坚决阻断 timecode 或 srt_timing 时码污染
        raw_shot_time = str(_s_get(shot, "time") or "").strip()
        scene_fallback_time = str(resolved_scene_info.get("time") or "") if resolved_scene_info else ""
        resolved_time = _sanitize_storyboard_time(raw_shot_time, scene_fallback_time)

        if resolved_scene_info:
            resolved_scene_id = int(resolved_scene_info["scene_id"])
            # 基于景别、动作语义与镜头原始引用，智能推断二级机位(zone)与三级环境切片视图(weathering_view)
            s_views = scene_views_by_scene_id.get(resolved_scene_id) or []
            selected_sv = _select_scene_zone_and_view(
                resolved_scene_info,
                s_views,
                shot_type=shot_type,
                action=f"{action} {img_prompt} {vid_prompt}",
                raw_ref=raw_scene_ref,
            )
            sz_id = selected_sv.get("scene_zone_id")
            swv_id = selected_sv.get("scene_weathering_view_id")
            resolved_scene_zone_id = int(sz_id) if isinstance(sz_id, int) else None
            resolved_scene_weathering_view_id = int(swv_id) if isinstance(swv_id, int) else None

            # 完备性兜底：若智能匹配未能产出，使用已在 _load_stage6_asset_lookup_maps 加载的基准外键
            if resolved_scene_zone_id is None and resolved_scene_info.get("scene_zone_id"):
                resolved_scene_zone_id = int(resolved_scene_info["scene_zone_id"])
            if resolved_scene_weathering_view_id is None and resolved_scene_info.get("scene_weathering_view_id"):
                resolved_scene_weathering_view_id = int(resolved_scene_info["scene_weathering_view_id"])

            if not resolved_location:
                resolved_location = str(resolved_scene_info.get("location") or "")
            if not raw_scene_ref:
                raw_scene_ref = str(selected_sv.get("asset_key") or resolved_scene_info.get("benchmark_asset_key") or resolved_scene_info.get("scene_code") or "")

        # 物理资产门禁 (Asset Gatekeeper) 校验：场景母体与多级外键白名单过滤与极简收敛
        if resolved_scene_id is not None and resolved_scene_id not in valid_scene_ids:
            log.warning("【Gatekeeper门禁拦截】shot=%s resolved_scene_id=%s 悬空，已安全置为 None", shot_num, resolved_scene_id)
            resolved_scene_id = None
        if resolved_scene_zone_id is not None and resolved_scene_zone_id not in valid_scene_zone_ids:
            log.debug("【Gatekeeper门禁】shot=%s resolved_scene_zone_id=%s 未在阶段6物理生成，按需置为 None", shot_num, resolved_scene_zone_id)
            resolved_scene_zone_id = None
        if resolved_scene_weathering_view_id is not None and resolved_scene_weathering_view_id not in valid_scene_weathering_view_ids:
            log.debug("【Gatekeeper门禁】shot=%s resolved_scene_weathering_view_id=%s 未在阶段6物理生成，按需置为 None", shot_num, resolved_scene_weathering_view_id)
            resolved_scene_weathering_view_id = None

        # 统计场景闭环门禁指标
        if resolved_scene_id is not None:
            audit_scene_closed_count += 1
        if resolved_scene_zone_id is not None:
            audit_scene_zone_closed_count += 1
        if resolved_scene_weathering_view_id is not None:
            audit_scene_view_closed_count += 1

        # 2) 解析 Stage 6 角色三级外键 (characters.id, character_libraries.id, character_stages.id, character_stage_views.id)
        resolved_chars: list[dict[str, Any]] = []
        resolved_char_lib_ids: list[int] = []
        resolved_char_names: list[str] = []
        normalized_char_tokens: list[str] = []

        # 说话人判定：优先从台词解析提取出的 speaker，次级从原始 dialogue 冒号解析
        speaker_name = extracted_speaker
        if not speaker_name and dialogue and ("：" in dialogue or ":" in dialogue):
            sep = "：" if "：" in dialogue else ":"
            speaker_candidate = dialogue.split(sep, 1)[0].strip()
            speaker_candidate = re.sub(r"[（\(].*?[）\)]", "", speaker_candidate).strip()
            if speaker_candidate:
                speaker_name = speaker_candidate

        # 若存在明确说话人，优先解析并将说话人置于 resolved_chars 的第一位 (首要角色 primary)
        speaker_dict_entry: dict[str, Any] | None = None
        target_speaker_char: dict[str, Any] | None = None
        if speaker_name:
            speaker_info = _resolve_asset_from_map(speaker_name, char_map)
            if speaker_info:
                target_speaker_char = speaker_info
                scid = int(speaker_info.get("character_id") or speaker_info["character_lib_id"])
                slid = int(speaker_info["character_lib_id"])
                # 动态自适应机位景别与动作匹配最佳阶段与三级切片视图
                c_views = char_views_by_char_id.get(scid) or char_views_by_char_id.get(slid) or []
                selected_v = _select_character_stage_and_view(
                    speaker_info,
                    c_views,
                    shot_type=shot_type,
                    action=action,
                    raw_ref=speaker_name,
                )
                scs_id = selected_v["character_stage_id"]
                ssv_id = selected_v["stage_view_id"]
                sbkey = selected_v["asset_key"]
                scname = str(speaker_info.get("name") or speaker_name)
                speaker_dict_entry = {
                    "character_id": scid,
                    "character_lib_id": slid,
                    "character_stage_id": scs_id,
                    "stage_view_id": ssv_id,
                    "name": scname,
                    "asset_key": sbkey,
                }
                resolved_char_lib_ids.append(slid)
                resolved_chars.append(speaker_dict_entry)
                resolved_char_names.append(scname)
                normalized_char_tokens.append(sbkey)

        for c_ref in raw_char_refs:
            c_info = _resolve_asset_from_map(c_ref, char_map)
            if c_info:
                cid = int(c_info.get("character_id") or c_info["character_lib_id"])
                lid = int(c_info["character_lib_id"])
                c_views = char_views_by_char_id.get(cid) or char_views_by_char_id.get(lid) or []
                selected_v = _select_character_stage_and_view(
                    c_info,
                    c_views,
                    shot_type=shot_type,
                    action=action,
                    raw_ref=c_ref,
                )
                cs_id = selected_v["character_stage_id"]
                sv_id = selected_v["stage_view_id"]
                bkey = selected_v["asset_key"]
                cname = str(c_info.get("name") or "")
                if lid not in resolved_char_lib_ids:
                    resolved_char_lib_ids.append(lid)
                    resolved_chars.append({
                        "character_id": cid,
                        "character_lib_id": lid,
                        "character_stage_id": cs_id,
                        "stage_view_id": sv_id,
                        "name": cname,
                        "asset_key": bkey,
                    })
                else:
                    for existing in resolved_chars:
                        if existing["character_lib_id"] == lid or existing["character_id"] == cid:
                            if sv_id:
                                existing["stage_view_id"] = int(sv_id)
                            if cs_id:
                                existing["character_stage_id"] = int(cs_id)
                            if bkey:
                                existing["asset_key"] = bkey
                if cname and cname not in resolved_char_names:
                    resolved_char_names.append(cname)
                if bkey not in normalized_char_tokens:
                    normalized_char_tokens.append(bkey)
            else:
                if c_ref not in normalized_char_tokens:
                    normalized_char_tokens.append(c_ref)

        # 角色兜底扫描：若当前分镜仍未提取到角色（如动作戏、悬疑戏中未声明），扫描动作与画面文本
        shot_full_text = f"{action} {img_prompt} {vid_prompt} {dialogue} {narration}"
        for cid, cinfo in char_by_id.items():
            lid = int(cinfo.get("character_lib_id") or cid)
            cname = str(cinfo.get("name") or "").strip()
            if lid not in resolved_char_lib_ids and cname and len(cname) >= 2 and cname in shot_full_text:
                c_views = char_views_by_char_id.get(cid) or char_views_by_char_id.get(lid) or []
                selected_v = _select_character_stage_and_view(
                    cinfo,
                    c_views,
                    shot_type=shot_type,
                    action=action,
                    raw_ref=cname,
                )
                cs_id = selected_v["character_stage_id"]
                sv_id = selected_v["stage_view_id"]
                bkey = selected_v["asset_key"]
                resolved_char_lib_ids.append(lid)
                resolved_chars.append({
                    "character_id": cid,
                    "character_lib_id": lid,
                    "character_stage_id": cs_id,
                    "stage_view_id": sv_id,
                    "name": cname,
                    "asset_key": bkey,
                })
                resolved_char_names.append(cname)
                normalized_char_tokens.append(bkey)

        # 3) 解析 Stage 6 道具三级外键 (props.id, prop_damage_states.id, prop_detail_views.id)
        resolved_props: list[dict[str, Any]] = []
        resolved_prop_ids: list[int] = []
        normalized_prop_tokens: list[str] = []

        # 道具兜底提取：若未显式指定道具引用，自动扫描镜头画面与动作中的道具标识（包括【...】标注、props 实体名与核心别名）
        effective_prop_refs = list(raw_prop_refs)
        if not effective_prop_refs:
            for bracket_prop in re.findall(r"【([^】]+)】", shot_full_text):
                b_stripped = bracket_prop.strip()
                if b_stripped and b_stripped not in effective_prop_refs:
                    effective_prop_refs.append(b_stripped)
            for pid, pinfo in prop_by_id.items():
                pname = str(pinfo.get("name") or "").strip()
                if pname and len(pname) >= 2 and pname in shot_full_text:
                    if pname not in effective_prop_refs:
                        effective_prop_refs.append(pname)
                # 核心别名与同义词扫描
                for a_tok in pinfo.get("aliases") or []:
                    if a_tok and len(a_tok) >= 2 and a_tok in shot_full_text:
                        if a_tok not in effective_prop_refs and pname not in effective_prop_refs:
                            effective_prop_refs.append(a_tok)

        for p_ref in effective_prop_refs:
            p_info = _resolve_asset_from_map(p_ref, prop_map)
            if p_info:
                pid = int(p_info["prop_id"])
                p_views = prop_views_by_prop_id.get(pid) or []
                selected_pv = _select_prop_damage_and_view(
                    p_info,
                    p_views,
                    shot_type=shot_type,
                    action=f"{action} {img_prompt} {vid_prompt}",
                    raw_ref=p_ref,
                )
                ds_id = selected_pv["damage_state_id"]
                dv_id = selected_pv["prop_detail_view_id"]
                bkey = selected_pv["asset_key"]
                if pid not in resolved_prop_ids:
                    resolved_prop_ids.append(pid)
                    resolved_props.append({
                        "prop_id": pid,
                        "damage_state_id": ds_id,
                        "prop_detail_view_id": dv_id,
                        "asset_key": bkey,
                    })
                else:
                    for existing_p in resolved_props:
                        if existing_p["prop_id"] == pid:
                            if ds_id:
                                existing_p["damage_state_id"] = int(ds_id)
                            if dv_id:
                                existing_p["prop_detail_view_id"] = int(dv_id)
                            if bkey:
                                existing_p["asset_key"] = bkey
                if bkey not in normalized_prop_tokens:
                    normalized_prop_tokens.append(bkey)
            else:
                if p_ref not in normalized_prop_tokens:
                    normalized_prop_tokens.append(p_ref)

        # 物理资产门禁 (Asset Gatekeeper) 校验：角色与道具三级外键白名单过滤与虚假外键清洗
        filtered_chars: list[dict[str, Any]] = []
        for c_item in resolved_chars:
            cid = c_item.get("character_id")
            if cid not in valid_char_ids:
                log.warning("【Gatekeeper门禁拦截】shot=%s 角色 character_id=%s 不存在于阶段6资产库，跳过关联", shot_num, cid)
                continue
            if c_item.get("character_stage_id") not in valid_char_stage_ids:
                c_item["character_stage_id"] = None
            if c_item.get("stage_view_id") not in valid_char_stage_view_ids:
                c_item["stage_view_id"] = None
            filtered_chars.append(c_item)
        resolved_chars = filtered_chars
        resolved_char_lib_ids = [int(c["character_lib_id"]) for c in resolved_chars if c.get("character_lib_id") is not None]

        filtered_props: list[dict[str, Any]] = []
        for p_item in resolved_props:
            pid = p_item.get("prop_id")
            if pid not in valid_prop_ids:
                log.warning("【Gatekeeper门禁拦截】shot=%s 道具 prop_id=%s 不存在于阶段6资产库，跳过关联", shot_num, pid)
                continue
            if p_item.get("damage_state_id") not in valid_prop_damage_state_ids:
                p_item["damage_state_id"] = None
            if p_item.get("prop_detail_view_id") not in valid_prop_detail_view_ids:
                p_item["prop_detail_view_id"] = None
            filtered_props.append(p_item)
        resolved_props = filtered_props
        resolved_prop_ids = [int(p["prop_id"]) for p in resolved_props if p.get("prop_id") is not None]

        dur_ms = int(shot_dur * 1000)
        shot_start_ms = current_timeline_ms
        shot_end_ms = current_timeline_ms + dur_ms
        current_timeline_ms = shot_end_ms

        def _fmt_tc(ms_val: int) -> str:
            h = ms_val // 3600000
            m = (ms_val % 3600000) // 60000
            s = (ms_val % 60000) // 1000
            ms = ms_val % 1000
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        shot_timecode = str(_s_get(shot, "timecode") or f"{_fmt_tc(shot_start_ms)} --> {_fmt_tc(shot_end_ms)}")
        srt_timing_val = str(_s_get(shot, "srt_timing") or shot_timecode)
        
        # 音频内嵌与外部合成解耦标记解析
        is_audio_embedded = bool(_s_get(shot, "audio_prompt_embedded", False) or (first_last_cfg and first_last_cfg.get("audio_prompt_embedded")))
        if gen_mode == "first_last_frame":
            is_audio_embedded = True
            req_ext_synth = False
        else:
            req_ext_synth = bool(pure_dialogue or narration)

        srt_dynamics_json = json.dumps(
            {
                "srt_timing": srt_timing_val,
                "srt_text": _s_get(shot, "srt_text") or dialogue,
                "speech_inpoint_sec": _s_get(shot, "speech_inpoint_sec"),
                "contextual_tts_prompt": _s_get(shot, "contextual_tts_prompt"),
                "is_dialogue_complete_in_shot": _s_get(shot, "is_dialogue_complete_in_shot", True),
                "lipsync_dynamics": lipsync_val,
            },
            ensure_ascii=False,
        )
        audio_stem_json = json.dumps(
            {
                "audio": audio_val,
                "music_cue": _s_get(shot, "music_cue") or audio_val.get("bgm") or "",
                "foley_cue": _s_get(shot, "foley_cue") or audio_val.get("foley") or "",
                "audio_prompt_embedded": is_audio_embedded,
                "requires_external_synth": req_ext_synth,
            },
            ensure_ascii=False,
        )
        # 收集权威槽位与连续性状态机快照
        canonical_v_slots = _s_get(shot, "canonical_visual_slots") or []
        canonical_a_slots = _s_get(shot, "canonical_audios") or []
        eng_manifest = _s_get(shot, "engineering_manifest") or {}
        continuity_snap = _s_get(shot, "continuity_snapshot") or {}
        polished_p = str(_s_get(shot, "polished_prompt") or _s_get(shot, "image_prompt") or img_prompt)
        continuity_snap_json = json.dumps(continuity_snap, ensure_ascii=False) if continuity_snap else "{}"

        shot_result_payload = {
            "selection_rationale": selection_rationale,
            "target_engine": target_engine,
            "generation_mode": gen_mode,
            "rationale": _s_get(shot, "rationale"),
            "first_last_config": first_last_cfg,
            "multi_image_config": multi_img_cfg,
            "audio": audio_val,
            "lipsync_dynamics": lipsync_val,
            "audio_prompt_embedded": is_audio_embedded,
            "requires_external_synth": req_ext_synth,
            "speech_inpoint_sec": _s_get(shot, "speech_inpoint_sec"),
            "contextual_tts_prompt": _s_get(shot, "contextual_tts_prompt"),
            "is_dialogue_complete_in_shot": _s_get(shot, "is_dialogue_complete_in_shot", True),
            "srt_timing": srt_timing_val,
            "srt_text": _s_get(shot, "srt_text") or dialogue,
            "dynamic_cue": _s_get(shot, "dynamic_cue") or action,
            "music_cue": _s_get(shot, "music_cue") or audio_val.get("bgm") or "",
            "foley_cue": _s_get(shot, "foley_cue") or atmosphere,
            "scene_asset_id": raw_scene_ref,
            "character_asset_ids": normalized_char_tokens,
            "prop_asset_ids": normalized_prop_tokens,
            "resolved_scene_id": resolved_scene_id,
            "resolved_character_ids": resolved_char_lib_ids,
            "resolved_prop_ids": resolved_prop_ids,
            "canonical_visual_slots": canonical_v_slots,
            "canonical_audio_slots": canonical_a_slots,
            "engineering_manifest": eng_manifest,
            "continuity_snapshot": continuity_snap,
            "polished_prompt": polished_p,
        }
        shot_result_json = json.dumps(shot_result_payload, ensure_ascii=False)
        resolved_char_ids = [c["character_id"] for c in resolved_chars if isinstance(c.get("character_id"), int)]
        characters_json = json.dumps(
            resolved_char_ids if resolved_char_ids else (resolved_char_names or normalized_char_tokens),
            ensure_ascii=False,
        )
        ref_keys_json = json.dumps(all_ref_keys, ensure_ascii=False)
        
        # 优化 shot_title：优先使用 LLM 提炼的分镜节拍小标题，次级智能兜底动作前段，避免纯占位符
        candidate_title = str(_s_get(shot, "title") or "").strip()
        if not candidate_title or candidate_title.startswith("镜头 #") or candidate_title == f"镜头{shot_num}":
            action_cue = str(_s_get(shot, "action") or _s_get(shot, "dynamic_cue") or "").strip()
            if action_cue:
                # 截取动作前 14 个字符作为清晰的戏剧动作小标题
                candidate_title = action_cue[:14].rstrip("，。！？；:,")
            elif dialogue:
                candidate_title = dialogue[:14].rstrip("，。！？；:,")
            else:
                candidate_title = f"镜头 #{shot_num}"
        shot_title = candidate_title

        # 4) 插入 storyboards 主表（全面写入场景二级区域与三级做旧视图、物理连续性快照与精炼提示词）
        ins_res = db.execute(
            text("""
                INSERT INTO storyboards (
                    episode_id, scene_id, scene_zone_id, scene_weathering_view_id, scene_asset_key,
                    storyboard_number, title, description,
                    location, time, duration, shot_type, movement,
                    creation_mode, generation_mode, selection_rationale, target_engine,
                    timecode, mode_b_audit_verdict,
                    image_prompt, video_prompt, dialogue, narration,
                    action, atmosphere, characters, reference_asset_keys,
                    srt_dynamics, audio_stem_params, result, status,
                    continuity_snapshot, polished_prompt, created_at, updated_at
                ) VALUES (
                    :episode_id, :scene_id, :scene_zone_id, :scene_weathering_view_id, :scene_asset_key,
                    :storyboard_number, :title, :description,
                    :location, :time, :duration, :shot_type, :movement,
                    :creation_mode, :generation_mode, :selection_rationale, :target_engine,
                    :timecode, :mode_b_audit_verdict,
                    :image_prompt, :video_prompt, :dialogue, :narration,
                    :action, :atmosphere, :characters, :reference_asset_keys,
                    :srt_dynamics, :audio_stem_params, :result, :status,
                    :continuity_snapshot, :polished_prompt, :created_at, :updated_at
                )
            """),
            {
                "episode_id": episode_id,
                "scene_id": resolved_scene_id,
                "scene_zone_id": resolved_scene_zone_id,
                "scene_weathering_view_id": resolved_scene_weathering_view_id,
                "scene_asset_key": raw_scene_ref,
                "storyboard_number": shot_num,
                "title": shot_title,
                "description": img_prompt or action,
                "location": resolved_location,
                "time": resolved_time,
                "duration": shot_dur,
                "shot_type": shot_type,
                "movement": movement,
                "creation_mode": gen_mode,
                "generation_mode": gen_mode,
                "selection_rationale": selection_rationale,
                "target_engine": target_engine,
                "timecode": shot_timecode,
                "mode_b_audit_verdict": mode_b_audit_verdict,
                "image_prompt": img_prompt,
                "video_prompt": vid_prompt,
                "dialogue": dialogue,
                "narration": narration,
                "action": action,
                "atmosphere": atmosphere,
                "characters": characters_json,
                "reference_asset_keys": ref_keys_json,
                "srt_dynamics": srt_dynamics_json,
                "audio_stem_params": audio_stem_json,
                "result": shot_result_json,
                "status": status,
                "continuity_snapshot": continuity_snap_json,
                "polished_prompt": polished_p,
                "created_at": now_str,
                "updated_at": now_str,
            },
        )
        sb_count += 1

        storyboard_id: int | None = None
        raw_last_id = getattr(ins_res, "lastrowid", None)
        if isinstance(raw_last_id, int) and raw_last_id > 0:
            storyboard_id = raw_last_id
        else:
            try:
                sb_id_row = fetch_one(
                    db,
                    "SELECT id FROM storyboards WHERE episode_id = :ep_id AND storyboard_number = :sb_num ORDER BY id DESC LIMIT 1",
                    {"ep_id": episode_id, "sb_num": shot_num},
                )
                if isinstance(sb_id_row, dict) and isinstance(sb_id_row.get("id"), int):
                    storyboard_id = int(sb_id_row["id"])
            except Exception:
                storyboard_id = None

        if storyboard_id is not None and storyboard_id > 0:
            # 5) 写入 frame_prompts 关键帧表
            if gen_mode == "first_last_frame" and isinstance(first_last_cfg, dict):
                first_p = str(first_last_cfg.get("first_frame_prompt") or "")
                last_p = str(first_last_cfg.get("last_frame_prompt") or "")
                motion_p = str(first_last_cfg.get("video_motion_prompt") or vid_prompt)
                if first_p:
                    db.execute(
                        text("""
                            INSERT INTO frame_prompts (
                                storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                            ) VALUES (
                                :sb_id, 'first', :prompt, '首帧T=0s起始静态', 'single_first', :now, :now
                            )
                        """),
                        {"sb_id": storyboard_id, "prompt": first_p, "now": now_str},
                    )
                    fp_count += 1
                if last_p:
                    db.execute(
                        text("""
                            INSERT INTO frame_prompts (
                                storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                            ) VALUES (
                                :sb_id, 'last', :prompt, '尾帧T=Ds定格终态', 'single_last', :now, :now
                            )
                        """),
                        {"sb_id": storyboard_id, "prompt": last_p, "now": now_str},
                    )
                    fp_count += 1
                if motion_p:
                    db.execute(
                        text("""
                            INSERT INTO frame_prompts (
                                storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                            ) VALUES (
                                :sb_id, 'motion_interpolation', :prompt, '首尾帧三段式运动插值描述', 'motion_interpolation', :now, :now
                            )
                        """),
                        {"sb_id": storyboard_id, "prompt": motion_p, "now": now_str},
                    )
                    fp_count += 1
            elif img_prompt:
                db.execute(
                    text("""
                        INSERT INTO frame_prompts (
                            storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                        ) VALUES (
                            :sb_id, 'key', :prompt, '主关键帧画面', 'single', :now, :now
                        )
                    """),
                    {"sb_id": storyboard_id, "prompt": img_prompt, "now": now_str},
                )
                fp_count += 1

            # 6) 写入 storyboard_characters 保序表（图2..k，优先基于权威槽位 slot_order 与 ref_symbol 写入）
            # 强化：第一位优先为发话角色（primary），其余为次要角色（secondary）
            # 若 shot 携带权威视觉槽位 canonical_visual_slots，按槽位实际绑定的 symbol 与 order 精确对齐
            char_slot_map = {}
            for vs in canonical_v_slots:
                if vs.get("asset_type") == "character" and vs.get("asset_id"):
                    char_slot_map[vs["asset_id"]] = (vs.get("slot_order"), vs.get("symbol"))
                    # 同时登记 token 形式如 CHAR_SHENMO
                    token = vs["asset_id"].split("_")[1] if "_" in vs["asset_id"] else vs["asset_id"]
                    char_slot_map[token] = (vs.get("slot_order"), vs.get("symbol"))

            for c_idx, c_item in enumerate(resolved_chars, start=2):
                char_role = "primary" if c_idx == 2 else "secondary"
                audit_char_slot_count += 1
                if c_item.get("stage_view_id"):
                    audit_char_tier3_closed_count += 1
                
                # 尝试从权威槽位对齐 order 与 symbol
                matched_slot = char_slot_map.get(c_item.get("asset_key", ""))
                if not matched_slot and c_item.get("name"):
                    matched_slot = char_slot_map.get(c_item["name"])
                
                effective_c_slot = matched_slot[0] if (matched_slot and matched_slot[0]) else c_idx
                effective_c_symbol = matched_slot[1] if (matched_slot and matched_slot[1]) else f"图{effective_c_slot}"

                db.execute(
                    text("""
                        INSERT INTO storyboard_characters (
                            storyboard_id, character_id, character_lib_id, character_stage_id, stage_view_id,
                            slot_order, ref_symbol, asset_key, role_in_shot, created_at
                        ) VALUES (
                            :sb_id, :char_id, :lib_id, :stage_id, :view_id,
                            :slot_order, :ref_symbol, :asset_key, :role_in_shot, :now
                        )
                    """),
                    {
                        "sb_id": storyboard_id,
                        "char_id": c_item["character_id"],
                        "lib_id": c_item["character_lib_id"],
                        "stage_id": c_item.get("character_stage_id"),
                        "view_id": c_item.get("stage_view_id"),
                        "slot_order": effective_c_slot,
                        "ref_symbol": effective_c_symbol,
                        "asset_key": c_item.get("asset_key", ""),
                        "role_in_shot": char_role,
                        "now": now_str,
                    },
                )
                sb_char_count += 1

            # 7) 写入 storyboard_props 保序表（优先基于权威槽位对齐，写入二级破坏形态与三级细节视图）
            # 强化：智能推断道具交互角色 (interaction_role: foreground/primary/ambient)
            prop_slot_map = {}
            for vs in canonical_v_slots:
                if vs.get("asset_type") == "prop" and vs.get("asset_id"):
                    prop_slot_map[vs["asset_id"]] = (vs.get("slot_order"), vs.get("symbol"))
                    token = vs["asset_id"].split("_")[1] if "_" in vs["asset_id"] else vs["asset_id"]
                    prop_slot_map[token] = (vs.get("slot_order"), vs.get("symbol"))

            prop_slot_start = 2 + len(resolved_chars)
            for p_idx, p_item in enumerate(resolved_props, start=prop_slot_start):
                audit_prop_slot_count += 1
                if p_item.get("prop_detail_view_id"):
                    audit_prop_tier3_closed_count += 1
                prop_role = _deduce_prop_interaction_role(
                    p_item.get("asset_key", ""), action, shot_type
                )

                matched_p_slot = prop_slot_map.get(p_item.get("asset_key", ""))
                effective_p_slot = matched_p_slot[0] if (matched_p_slot and matched_p_slot[0]) else p_idx
                effective_p_symbol = matched_p_slot[1] if (matched_p_slot and matched_p_slot[1]) else f"图{effective_p_slot}"

                db.execute(
                    text("""
                        INSERT INTO storyboard_props (
                            storyboard_id, prop_id, damage_state_id, prop_detail_view_id,
                            slot_order, ref_symbol, asset_key, interaction_role, created_at
                        ) VALUES (
                            :sb_id, :prop_id, :damage_state_id, :prop_detail_view_id,
                            :slot_order, :ref_symbol, :asset_key, :interaction_role, :now
                        )
                    """),
                    {
                        "sb_id": storyboard_id,
                        "prop_id": p_item["prop_id"],
                        "damage_state_id": p_item.get("damage_state_id"),
                        "prop_detail_view_id": p_item.get("prop_detail_view_id"),
                        "slot_order": effective_p_slot,
                        "ref_symbol": effective_p_symbol,
                        "asset_key": p_item.get("asset_key", ""),
                        "interaction_role": prop_role,
                        "now": now_str,
                    },
                )
                sb_prop_count += 1

            # 8) 写入 storyboard_audios 与 storyboard_subtitles 表（AI母音驱动与毫秒级字幕）
            # 强化：台词与字幕完全纯净化，剥离角色冒号与动作括注
            dlg_target_text = clean_phonetic if clean_phonetic else (clean_dialogue_text(narration) if narration else "")
            subtitle_display_text = pure_dialogue if pure_dialogue else (narration or "")
            tts_prompt = str(_s_get(shot, "contextual_tts_prompt") or audio_val.get("contextual_tts_prompt") or "")
            if not tts_prompt and extracted_cues:
                tts_prompt = f"语气/情绪: {', '.join(extracted_cues)}"

            inpoint_s = float(_s_get(shot, "speech_inpoint_sec") or 0.3)
            # 使用高拟真毫秒测速函数估算入点、出点与持续时长
            calc_in_ms, calc_out_ms, calc_dur_ms = _calculate_subtitle_duration_ms(
                dlg_target_text or subtitle_display_text, inpoint_s, shot_dur
            )
            calc_dur_s = calc_dur_ms / 1000.0
            outpoint_s = min(shot_dur, inpoint_s + calc_dur_s)

            if dlg_target_text:
                audit_dialogue_shots_count += 1
                matched_voice: dict[str, Any] | None = None
                matched_char_id: int | None = None
                matched_speaker_name = speaker_name or (resolved_chars[0]["name"] if resolved_chars else "未知角色")

                # 多级音色卡高灵敏度检索：1) 说话人原名 2) 说话人纯化名 3) 说话角色ID 4) 镜头首位登场角色
                if speaker_name:
                    matched_voice = voice_by_name.get(speaker_name.upper())
                    if not matched_voice:
                        clean_spk = re.sub(r"[^\w\u4e00-\u9fa5]", "", speaker_name).upper()
                        if clean_spk:
                            matched_voice = voice_by_name.get(clean_spk)
                    if not matched_voice and target_speaker_char:
                        scid = target_speaker_char.get("character_id") or target_speaker_char.get("character_lib_id")
                        if scid:
                            matched_voice = voice_by_char_id.get(scid)
                if matched_voice is None and resolved_chars:
                    matched_voice = voice_by_char_id.get(resolved_chars[0]["character_id"])

                # 精确绑定说话角色 character_id 与 character_stage_id
                if target_speaker_char:
                    matched_char_id = target_speaker_char.get("character_id")
                    matched_char_stage_id = target_speaker_char.get("character_stage_id")
                elif matched_voice and isinstance(matched_voice.get("character_id"), int):
                    matched_char_id = int(matched_voice["character_id"])
                    c_info = char_by_id.get(matched_char_id)
                    matched_char_stage_id = c_info.get("character_stage_id") if c_info else None
                elif resolved_chars:
                    matched_char_id = resolved_chars[0]["character_id"]
                    matched_char_stage_id = resolved_chars[0].get("character_stage_id")
                else:
                    matched_char_stage_id = None

                if narration and not pure_dialogue:
                    matched_voice = default_narrator_voice or matched_voice
                    matched_speaker_name = "旁白"
                    matched_char_id = None
                    matched_char_stage_id = None

                provider = str((matched_voice and matched_voice.get("tts_provider")) or "minimax")
                model_name = str((matched_voice and matched_voice.get("tts_model")) or "speech-02-hd")
                voice_id = str((matched_voice and matched_voice.get("provider_voice_id")) or (matched_voice and matched_voice.get("voice_id")) or "")
                if voice_id:
                    audit_voice_bound_count += 1
                else:
                    log.warning(
                        "【Stage7音色卡预警】episode_id=%s, shot_num=%s, speaker=%s 存在台词但未匹配到有效 voice_id (matched_char_id=%s)",
                        episode_id, shot_num, matched_speaker_name, matched_char_id
                    )
                vp_id = int(matched_voice["id"]) if (matched_voice and isinstance(matched_voice.get("id"), int)) else None

                hash_str = f"{voice_id}|{dlg_target_text}|{tts_prompt}|{inpoint_s:.3f}"
                semantic_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()
                track_type = "narration" if (narration and not pure_dialogue) else "dialogue"

                ins_aud = db.execute(
                    text("""
                        INSERT INTO storyboard_audios (
                            drama_id, episode_id, storyboard_id, slot_order, ref_symbol,
                            asset_key, track_type, character_id, character_stage_id, voice_profile_id,
                            speaker_name, dialogue_text, clean_dialogue_text, tts_prompt, lipsync_dynamics,
                            srt_timing, inpoint_sec, outpoint_sec, duration_sec, is_complete_in_shot,
                            speed_ratio, pitch_ratio, emotion, emotion_intensity,
                            gain_db, ducking_db, target_lufs, provider, model, voice_id,
                            format, sample_rate, channels, semantic_hash, status, created_at, updated_at
                        ) VALUES (
                            :drama_id, :ep_id, :sb_id, 1, '音频1',
                            :asset_key, :track_type, :char_id, :char_stage_id, :vp_id,
                            :speaker_name, :dialogue_text, :clean_text, :tts_prompt, :lipsync_dynamics,
                            :srt_timing, :inpoint_sec, :outpoint_sec, :duration_sec, 1,
                            1.0, 1.0, 'neutral', 5,
                            0.0, 0.0, -23.0, :provider, :model, :voice_id,
                            'wav', 48000, 2, :semantic_hash, 'planned', :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "ep_id": episode_id,
                        "sb_id": storyboard_id,
                        "asset_key": f"VOICE_{matched_speaker_name}",
                        "track_type": track_type,
                        "char_id": matched_char_id,
                        "char_stage_id": matched_char_stage_id,
                        "vp_id": vp_id,
                        "speaker_name": matched_speaker_name,
                        "dialogue_text": subtitle_display_text,
                        "clean_text": dlg_target_text,
                        "tts_prompt": tts_prompt,
                        "lipsync_dynamics": json.dumps(lipsync_val, ensure_ascii=False) if lipsync_val else "",
                        "srt_timing": srt_timing_val,
                        "inpoint_sec": inpoint_s,
                        "outpoint_sec": outpoint_s,
                        "duration_sec": max(1.0, outpoint_s - inpoint_s),
                        "provider": provider,
                        "model": model_name,
                        "voice_id": voice_id,
                        "semantic_hash": semantic_hash,
                        "now": now_str,
                    },
                )
                sb_audio_count += 1
                aud_id: int | None = getattr(ins_aud, "lastrowid", None)

                sub_start_ms = shot_start_ms + int(inpoint_s * 1000)
                sub_end_ms = min(shot_end_ms, sub_start_ms + calc_dur_ms)
                sub_srt_timecode = f"{_fmt_tc(sub_start_ms)} --> {_fmt_tc(sub_end_ms)}"

                db.execute(
                    text("""
                        INSERT INTO storyboard_subtitles (
                            drama_id, episode_id, storyboard_id, sequence_order,
                            subtitle_type, character_id, speaker_name, text_content,
                            start_ms, end_ms, duration_ms, srt_timecode, audio_id,
                            created_at, updated_at
                        ) VALUES (
                            :drama_id, :ep_id, :sb_id, :seq_order,
                            :sub_type, :char_id, :speaker_name, :text_content,
                            :start_ms, :end_ms, :dur_ms, :srt_tc, :audio_id,
                            :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "ep_id": episode_id,
                        "sb_id": storyboard_id,
                        "seq_order": global_seq_order,
                        "sub_type": track_type,
                        "char_id": matched_char_id,
                        "speaker_name": matched_speaker_name,
                        "text_content": subtitle_display_text,
                        "start_ms": sub_start_ms,
                        "end_ms": sub_end_ms,
                        "dur_ms": max(100, sub_end_ms - sub_start_ms),
                        "srt_tc": sub_srt_timecode,
                        "audio_id": aud_id,
                        "now": now_str,
                    },
                )
                global_seq_order += 1
                sb_sub_count += 1

            # Foley 物理音效
            foley_text = str(audio_val.get("foley") or _s_get(shot, "foley_cue") or atmosphere or "")
            if foley_text:
                f_hash_str = f"FOLEY|{foley_text}|{shot_num}"
                f_hash = hashlib.sha256(f_hash_str.encode("utf-8")).hexdigest()
                db.execute(
                    text("""
                        INSERT INTO storyboard_audios (
                            drama_id, episode_id, storyboard_id, slot_order, ref_symbol,
                            asset_key, track_type, character_id,
                            speaker_name, dialogue_text, clean_dialogue_text,
                            srt_timing, inpoint_sec, outpoint_sec, duration_sec, is_complete_in_shot,
                            gain_db, ducking_db, target_lufs, format, sample_rate, channels,
                            semantic_hash, status, created_at, updated_at
                        ) VALUES (
                            :drama_id, :ep_id, :sb_id, 2, '音频2',
                            'SFX_FOLEY', 'foley', NULL,
                            '拟音', :dialogue_text, :clean_text,
                            :srt_timing, 0.0, :dur, :dur, 1,
                            3.0, 0.0, -23.0, 'wav', 48000, 2,
                            :semantic_hash, 'planned', :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "ep_id": episode_id,
                        "sb_id": storyboard_id,
                        "dialogue_text": foley_text,
                        "clean_text": foley_text,
                        "srt_timing": shot_timecode,
                        "dur": shot_dur,
                        "semantic_hash": f_hash,
                        "now": now_str,
                    },
                )
                sb_audio_count += 1

        log.debug(
            "【Stage7单镜六表落库】episode_id=%s, shot_num=%s, sb_id=%s -> scene_id=%s(%s), chars=%s, props=%s, audios=%s, subs=%s",
            episode_id,
            shot_num,
            storyboard_id,
            resolved_scene_id,
            raw_scene_ref,
            resolved_char_lib_ids,
            resolved_prop_ids,
            sb_audio_count,
            sb_sub_count,
        )

    # 计算并输出阶段6到阶段7资产衔接门禁审计指标
    scene_rate = (audit_scene_closed_count / audit_total_shots * 100) if audit_total_shots else 0.0
    zone_rate = (audit_scene_zone_closed_count / audit_total_shots * 100) if audit_total_shots else 0.0
    sview_rate = (audit_scene_view_closed_count / audit_total_shots * 100) if audit_total_shots else 0.0
    char_t3_rate = (audit_char_tier3_closed_count / audit_char_slot_count * 100) if audit_char_slot_count else 100.0
    prop_t3_rate = (audit_prop_tier3_closed_count / audit_prop_slot_count * 100) if audit_prop_slot_count else 100.0
    voice_rate = (audit_voice_bound_count / audit_dialogue_shots_count * 100) if audit_dialogue_shots_count else 100.0

    log.info(
        "【Stage6->Stage7资产衔接门禁审计】drama_id=%s, episode_id=%s:\n"
        "  - 分镜总数: %d\n"
        "  - 场景母体闭环率: %.1f%% (%d/%d)\n"
        "  - 场景机位(Zone)闭环率: %.1f%% (%d/%d)\n"
        "  - 场景环境切片(WeatheringView)闭环率: %.1f%% (%d/%d)\n"
        "  - 角色切片视图(StageView)闭环率: %.1f%% (%d/%d)\n"
        "  - 道具细节视图(DetailView)闭环率: %.1f%% (%d/%d)\n"
        "  - 对白音色卡(VoiceProfile)绑定率: %.1f%% (%d/%d)",
        drama_id, episode_id,
        audit_total_shots,
        scene_rate, audit_scene_closed_count, audit_total_shots,
        zone_rate, audit_scene_zone_closed_count, audit_total_shots,
        sview_rate, audit_scene_view_closed_count, audit_total_shots,
        char_t3_rate, audit_char_tier3_closed_count, audit_char_slot_count,
        prop_t3_rate, audit_prop_tier3_closed_count, audit_prop_slot_count,
        voice_rate, audit_voice_bound_count, audit_dialogue_shots_count,
    )

    if zone_rate < 100.0 or sview_rate < 100.0 or char_t3_rate < 100.0 or prop_t3_rate < 100.0:
        log.info(
            "【Stage6->Stage7资产衔接门禁审计】drama_id=%s, episode_id=%s 采用只读闭环与极简按需收敛，已物理核验所有外键有效性，拒绝任何虚拟伪自愈与虚假外键。",
            drama_id, episode_id
        )

    log.info(
        "【Stage7六表落库完成】drama_id=%s, episode_id=%s 成功原子覆盖写入: storyboards=%d, frame_prompts=%d, chars=%d, props=%d, audios=%d, subtitles=%d",
        drama_id,
        episode_id,
        sb_count,
        fp_count,
        sb_char_count,
        sb_prop_count,
        sb_audio_count,
        sb_sub_count,
    )
    return {
        "storyboards": sb_count,
        "frame_prompts": fp_count,
        "storyboard_characters": sb_char_count,
        "storyboard_props": sb_prop_count,
        "storyboard_audios": sb_audio_count,
        "storyboard_subtitles": sb_sub_count,
    }


def _rehydrate_episode_storyboard_shots(
    db: Session,
    drama_id: int,
    episode_id: int,
) -> list[StoryboardShot]:
    """从 storyboards、storyboard_characters、storyboard_props 三表全保真反序列化还原 StoryboardShot 列表。"""
    sb_rows = fetch_all(
        db,
        "SELECT * FROM storyboards WHERE episode_id = :epid AND deleted_at IS NULL ORDER BY storyboard_number ASC",
        {"epid": episode_id},
    )
    if not sb_rows:
        return []

    asset_maps = _load_stage6_asset_lookup_maps(db, drama_id, episode_id=episode_id)
    scene_by_id = asset_maps["scene_by_id"]
    char_by_lib_id = asset_maps["char_by_lib_id"]
    prop_by_id = asset_maps["prop_by_id"]

    shots: list[StoryboardShot] = []
    for sb in sb_rows:
        if not isinstance(sb, dict):
            continue
        sb_id = sb.get("id")
        res = _safe_json_loads(sb.get("result"), {})
        if not isinstance(res, dict):
            res = {}
        srt_dyn = _safe_json_loads(sb.get("srt_dynamics"), {})
        if not isinstance(srt_dyn, dict):
            srt_dyn = {}
        audio_stem = _safe_json_loads(sb.get("audio_stem_params"), {})
        if not isinstance(audio_stem, dict):
            audio_stem = {}

        # 1. 恢复场景资产关联（优先使用三级切片 scene_asset_key，再到 result JSON 与 scenes 主表）
        scene_asset_id = str(sb.get("scene_asset_key") or res.get("scene_asset_id") or "").strip()
        sb_scene_id = sb.get("scene_id") or res.get("resolved_scene_id")
        if not scene_asset_id and isinstance(sb_scene_id, int) and sb_scene_id in scene_by_id:
            s_info = scene_by_id[sb_scene_id]
            scene_asset_id = str(s_info.get("benchmark_asset_key") or s_info.get("scene_code") or f"ENV_{sb_scene_id}")

        # 2. 恢复角色资产关联（结合 result JSON 与 storyboard_characters 表中三级切片 asset_key）
        char_asset_ids: list[str] = [
            str(x).strip() for x in (res.get("character_asset_ids") or []) if str(x).strip()
        ]
        if isinstance(sb_id, int) and char_by_lib_id:
            try:
                sc_rows = fetch_all(
                    db,
                    "SELECT character_id, asset_key FROM storyboard_characters WHERE storyboard_id = :sb_id ORDER BY slot_order ASC, id ASC",
                    {"sb_id": sb_id},
                )
                for scr in sc_rows or []:
                    c_key = str(scr.get("asset_key") or "").strip()
                    cid = scr.get("character_id") if isinstance(scr, dict) else None
                    if not c_key and isinstance(cid, int) and cid in char_by_lib_id:
                        c_key = str(char_by_lib_id[cid].get("benchmark_asset_key") or f"CHAR_{cid}")
                    if c_key and c_key not in char_asset_ids:
                        char_asset_ids.append(c_key)
            except Exception:
                pass

        # 3. 恢复道具资产关联（结合 result JSON 与 storyboard_props 表中三级切片 asset_key）
        prop_asset_ids: list[str] = [
            str(x).strip() for x in (res.get("prop_asset_ids") or []) if str(x).strip()
        ]
        if isinstance(sb_id, int) and prop_by_id:
            try:
                sp_rows = fetch_all(
                    db,
                    "SELECT prop_id, asset_key FROM storyboard_props WHERE storyboard_id = :sb_id ORDER BY slot_order ASC, id ASC",
                    {"sb_id": sb_id},
                )
                for spr in sp_rows or []:
                    p_key = str(spr.get("asset_key") or "").strip()
                    pid = spr.get("prop_id") if isinstance(spr, dict) else None
                    if not p_key and isinstance(pid, int) and pid in prop_by_id:
                        p_key = str(prop_by_id[pid].get("benchmark_asset_key") or f"PROP_{pid}")
                    if p_key and p_key not in prop_asset_ids:
                        prop_asset_ids.append(p_key)
            except Exception:
                pass

        srt_timing_val = str(
            res.get("srt_timing")
            or srt_dyn.get("srt_timing")
            or sb.get("srt_timing")
            or ""
        )
        timecode_val = (
            srt_timing_val
            or str(sb.get("time") or "")
            or f"00:00:00,000 --> 00:00:{int(sb.get('duration') or 3):02d},000"
        )
        audio_dict = (
            res.get("audio")
            or audio_stem.get("audio")
            or {"dialogue": sb.get("dialogue", ""), "narration": sb.get("narration", "")}
        )
        img_prompt_val = str(
            sb.get("image_prompt")
            or res.get("image_prompt")
            or res.get("visual_description")
            or sb.get("description")
            or ""
        )

        shot = StoryboardShot(
            shot_id=int(sb.get("storyboard_number") or 1),
            timecode=timecode_val,
            duration_sec=float(sb.get("duration") or 3.0),
            framing=str(sb.get("shot_type") or "MCU 中近景"),
            camera_motion=str(sb.get("movement") or "Static"),
            generation_mode=str(sb.get("creation_mode") or "single_frame_dynamic"),
            image_prompt=img_prompt_val,
            video_prompt=str(sb.get("video_prompt") or ""),
            srt_text=str(res.get("srt_text") or srt_dyn.get("srt_text") or sb.get("srt_text") or sb.get("dialogue") or ""),
            srt_timing=srt_timing_val,
            dynamic_cue=str(sb.get("dynamic_cue") or res.get("dynamic_cue") or sb.get("action") or ""),
            music_cue=str(sb.get("music_cue") or res.get("music_cue") or audio_stem.get("music_cue") or ""),
            foley_cue=str(sb.get("foley_cue") or res.get("foley_cue") or sb.get("atmosphere") or ""),
            selection_rationale=res.get("selection_rationale") or "",
            target_engine=str(res.get("target_engine") or "wan3.0"),
            rationale=str(res.get("rationale") or ""),
            first_last_config=res.get("first_last_config"),
            multi_image_config=res.get("multi_image_config"),
            audio=audio_dict,
            lipsync_dynamics=res.get("lipsync_dynamics") or srt_dyn.get("lipsync_dynamics"),
            speech_inpoint_sec=res.get("speech_inpoint_sec") if res.get("speech_inpoint_sec") is not None else srt_dyn.get("speech_inpoint_sec"),
            contextual_tts_prompt=res.get("contextual_tts_prompt") or srt_dyn.get("contextual_tts_prompt"),
            is_dialogue_complete_in_shot=bool(
                res.get("is_dialogue_complete_in_shot", srt_dyn.get("is_dialogue_complete_in_shot", True))
            ),
            audio_prompt_embedded=bool(
                res.get("audio_prompt_embedded") or audio_stem.get("audio_prompt_embedded", False)
            ),
            requires_external_synth=bool(
                res.get("requires_external_synth", audio_stem.get("requires_external_synth", True))
            ),
            scene_asset_id=scene_asset_id,
            character_asset_ids=char_asset_ids,
            prop_asset_ids=prop_asset_ids,
        )
        shots.append(shot)

    log.debug(
        "【Stage7三表水合完成】drama_id=%s, episode_id=%s -> 成功还原 %d 个全保真 StoryboardShot 镜头",
        drama_id,
        episode_id,
        len(shots),
    )
    return shots


def persist_stage7(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 7 原子落库：六表联动写入 storyboards / frame_prompts / storyboard_characters / storyboard_props / storyboard_audios / storyboard_subtitles 与 SRT 导出。"""
    curr_ep = episode_num or getattr(state, "episode_number", None) or getattr(state, "episode_num", None) or getattr(state, "current_visual_episode", 1) or 1
    log.info("【阶段 7 落库】开始持久化短剧 [%s] 第 %s 集的分镜六表联动数据与 SRT...", drama_id, curr_ep)
    now = now_iso()

    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": curr_ep},
    )
    if not ep_row:
        log.warning("【阶段 7 落库】未找到第 %s 集，跳过分镜写入", curr_ep)
        return

    episode_id = ep_row["id"]
    storyboards: list[Any] = []
    if hasattr(state, "storyboard_shots") and isinstance(state.storyboard_shots, list) and state.storyboard_shots:
        storyboards = state.storyboard_shots
    elif isinstance(getattr(state, "storyboards", None), list) and state.storyboards:
        storyboards = state.storyboards
    elif isinstance(getattr(state, "storyboards", None), dict):
        storyboards = state.storyboards.get(curr_ep, [])
    elif hasattr(state, "episode_storyboards") and isinstance(state.episode_storyboards, dict):
        storyboards = state.episode_storyboards.get(curr_ep, [])
    elif hasattr(state, "storyboard_executions") and isinstance(state.storyboard_executions, dict):
        storyboards = state.storyboard_executions.get(curr_ep, [])

    if hasattr(state, "srt_content") and getattr(state, "srt_content", ""):
        srt_export = state.srt_content
    elif hasattr(state, "srt_script") and getattr(state, "srt_script", ""):
        srt_export = state.srt_script
    else:
        srt_export = (
            getattr(state, "srt_exports", {}).get(curr_ep, "")
            or getattr(state, "episode_srt_exports", {}).get(curr_ep, "")
        )

    # 更新 episodes 的 srt_export 与 mode_b_manifest_check
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    ep_ast["srt_export"] = srt_export
    mode_b_checks = getattr(state, "episode_mode_b_manifest_checks", {}) or getattr(state, "mode_b_manifest_checks", {})
    if mode_b_checks and curr_ep in mode_b_checks:
        ep_ast["mode_b_manifest_check"] = mode_b_checks[curr_ep]
    elif isinstance(getattr(state, "mode_b_manifest_check", None), dict) and getattr(state, "mode_b_manifest_check", None):
        ep_ast["mode_b_manifest_check"] = state.mode_b_manifest_check
    db.execute(
        text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
        {"id": episode_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
    )

    # 调用三表联动原子持久化（storyboards + storyboard_characters + storyboard_props）
    _persist_episode_storyboards_3tables(
        db=db,
        drama_id=drama_id,
        episode_id=episode_id,
        storyboards=storyboards,
        status="draft",
        now=str(now),
    )

    def _s_get(s: Any, key: str, default: Any = None) -> Any:
        if isinstance(s, dict):
            return s.get(key, default)
        return getattr(s, key, default)

    # 长期记忆自动入库与向量化（分镜视听指导与精确SRT）
    if storyboards:
        sb_summary_lines = []
        for s in storyboards[:15]:
            s_num = _s_get(s, "shot_id") or _s_get(s, "storyboard_number") or ""
            s_frame = _s_get(s, "framing") or _s_get(s, "shot_type") or ""
            s_motion = _s_get(s, "camera_motion") or _s_get(s, "movement") or ""
            s_prompt = str(_s_get(s, "image_prompt") or "")[:60]
            s_srt = _s_get(s, "srt_text") or _s_get(s, "dialogue") or ""
            sb_summary_lines.append(f"镜头{s_num} [{s_frame} / {s_motion}]: 画面[{s_prompt}...] 台词[{s_srt}]")
        stage7_memories = [
            {
                "title": f"第{curr_ep}集单帧分镜视听指导与精确SRT",
                "content": f"第{curr_ep}集分镜概况(共{len(storyboards)}镜):\n" + "\n".join(sb_summary_lines),
                "summary": f"第{curr_ep}集分镜共{len(storyboards)}镜，已生成精准SRT字幕",
                "keywords": [f"第{curr_ep}集", "分镜提示词", "运镜", "SRT字幕"],
                "memory_type": "storyboard_spec",
                "source_type": "stage7_storyboards",
                "source_id": f"ep_storyboards_{curr_ep}",
            }
        ]
        sync_stage_memories_to_vector_db(db, drama_id, 7, stage7_memories)

    db.execute(
        text("UPDATE dramas SET current_stage = 7, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 7, state.latest_audit)

    db.commit()
    log.info("【阶段 7 落库】成功完成并已提交事务。")


# 导出直接落库分镜数据接口，供单元测试与独立管线调用
def save_storyboard_data_direct(
    db: Session,
    drama_id: int,
    episode_id: int,
    storyboards: list[Any] | None = None,
    storyboard_data: list[Any] | None = None,
    status: str = "draft",
    now: str | None = None,
) -> dict[str, int]:
    """导出直接落库分镜数据接口，供单元测试与独立管线调用，兼容 storyboards 与 storyboard_data 参数名。"""
    payload = storyboards if storyboards is not None else (storyboard_data or [])
    return _persist_episode_storyboards_3tables(
        db=db,
        drama_id=drama_id,
        episode_id=episode_id,
        storyboards=payload,
        status=status,
        now=now,
    )


# =========================================================================
# 阶段 8：全息声学混音工程持久化
# =========================================================================

