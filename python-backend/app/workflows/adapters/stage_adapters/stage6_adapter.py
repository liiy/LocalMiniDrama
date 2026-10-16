from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.context import vector_memory_service
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

def clean_character_name(raw_name: str) -> str:
    """从原始角色名或切片描述名中剥离括号形态标注及常见切片后缀，还原自然人本名。
    例如:
      '沈炼(全身定妆照)' -> '沈炼'
      '沈炼（飞鱼服）' -> '沈炼'
      '沈炼[四阿哥常服]' -> '沈炼'
      '沈炼(0号肖像)' -> '沈炼'
      '沈炼_特写' -> '沈炼'
    """
    if not raw_name:
        return ""
    # 1. 剔除括号及其内部说明 (支持中英文括号、中括号)
    name = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", raw_name).strip()
    # 2. 剥离常见切片下划线/破折号后缀
    name = re.sub(r"[_—\-](全身|肖像|特写|四视图|三视图|手部|面部|常服|战损).*$", "", name).strip()
    return name if name else raw_name.strip()


def extract_character_tokens(asset_or_char_id: str) -> tuple[str, str, str]:
    """从四段式或多段式/两段式 asset_key / char_id 中解析出: (角色Code, 阶段Token, 切片Token)。
    标准模式: CHAR_<CODE>_<STAGE>_<VIEW>
    支持复合多段角色名（如 CHAR_ZHOU_LAO_SI_T1_PORTRAIT，避免被简单按首个下划线截断为 ZHOU）。
    例如:
      CHAR_SHENLIAN_T1_FULL_BODY -> ('SHENLIAN', 'T1', 'FULL_BODY')
      CHAR_ZHOU_LAO_SI_T1_PORTRAIT -> ('ZHOU_LAO_SI', 'T1', 'PORTRAIT')
      CHAR_ZHOU_LAO_SI_T1 -> ('ZHOU_LAO_SI', 'T1', '')
      CHAR_ZHOU_LAO_SI -> ('ZHOU_LAO_SI', '', '')
      CHAR_SHENLIAN -> ('SHENLIAN', '', '')
    """
    if not asset_or_char_id or not str(asset_or_char_id).startswith("CHAR_"):
        return ("", "", "")
    raw_str = str(asset_or_char_id).strip()
    parts = raw_str.split("_")
    # parts: ['CHAR', ...]
    if len(parts) < 2:
        return ("", "", "")

    # 策略 1: 优先寻找形态阶段锚点 (例如 T1, T2, S1, S2, Z1, BASE, DEFAULT, ORIGIN)
    # 形态锚点一般出现在角色代号之后，前面至少需要有角色代号段 (即 i >= 2)
    stage_idx = -1
    for i in range(2, len(parts)):
        segment = parts[i].upper()
        if re.match(r"^[TSZ]\d+$", segment, re.IGNORECASE) or segment in ("BASE", "DEFAULT", "ORIGIN"):
            stage_idx = i
            break

    if stage_idx != -1:
        # 成功通过阶段标记锚定边界
        code = "_".join(parts[1:stage_idx]).upper()
        stage_token = parts[stage_idx].upper()
        view_token = "_".join(parts[stage_idx + 1:]).upper() if stage_idx + 1 < len(parts) else ""
        log.debug(
            "【阶段 6 角色令牌解析·阶段锚点模式】输入=%s -> 角色代号=%s, 形态阶段=%s, 视图切片=%s",
            raw_str, code, stage_token, view_token
        )
        return (code, stage_token, view_token)

    # 策略 2: 若未找到显式 T1/T2 形态锚点，通过常见视图切片关键词从后向前反向识别边界
    known_view_keywords = {
        "PORTRAIT", "BASE_PORTRAIT", "MAIN_PORTRAIT", "FULL_BODY", "FULLBODY",
        "BASE_COSTUME", "FRONT", "SIDE", "BACK", "THREE_QUARTER", "4V_FRONT",
        "4V_FRONT_FULL", "4V_PROFILE", "4V_SIDE", "4V_BACK", "4V_3Q", "MACRO_FACE",
        "MACRO_HAND", "FACIAL_MACRO", "HANDS_DETAIL", "FOUR_VIEW", "STATUS_INJURED",
        "LIGHT_FLASH", "LIGHT_LOWKEY", "EXP_RAGE", "EXP_FEAR", "EXP_GRIEF", "EXP_SUPPRESSED",
    }
    view_start_idx = -1
    for i in range(len(parts) - 1, 1, -1):
        test_view = "_".join(parts[i:]).upper()
        if test_view in known_view_keywords or parts[i].upper() in known_view_keywords:
            view_start_idx = i
            break

    if view_start_idx != -1:
        code = "_".join(parts[1:view_start_idx]).upper()
        stage_token = "T1"  # 默认基准形态
        view_token = "_".join(parts[view_start_idx:]).upper()
        log.debug(
            "【阶段 6 角色令牌解析·视图后缀模式】输入=%s -> 角色代号=%s, 默认形态=%s, 视图切片=%s",
            raw_str, code, stage_token, view_token
        )
        return (code, stage_token, view_token)

    # 策略 3: 若均无形态与视图段，整体作为纯角色代号 (例如 CHAR_ZHOU_LAO_SI 或 CHAR_SHENLIAN)
    code = "_".join(parts[1:]).upper()
    log.debug(
        "【阶段 6 角色令牌解析·纯角色代号模式】输入=%s -> 角色代号=%s (无形态与视图后缀)",
        raw_str, code
    )
    return (code, "", "")


def find_canonical_entity(
    query_key: str,
    canonical_map: dict[str, dict[str, Any]],
    canonical_by_name: dict[str, dict[str, Any]],
    canonical_by_code: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """在规范化实体集合中按多维凭证高精度检索角色实体 (Tier 1 Entity)。
    支持通过: 中文名、清洗后中文名、小写名、带 CHAR_ 代号、去 CHAR_ 代号、归一化 Token 等任意维度检索。
    """
    if not query_key:
        return None
    q = str(query_key).strip()

    # 1. 尝试原始代码及名称精确检索
    if q in canonical_by_name:
        return canonical_by_name[q]
    if q in canonical_by_code:
        return canonical_by_code[q]

    # 2. 尝试清洗后的中文名检索
    q_clean = clean_character_name(q)
    if q_clean and q_clean in canonical_by_name:
        return canonical_by_name[q_clean]

    # 3. 尝试大小写不敏感的小写名称检索
    q_lower = q.lower()
    if q_lower in canonical_map:
        return canonical_map[q_lower]
    if q_clean and q_clean.lower() in canonical_map:
        return canonical_map[q_clean.lower()]

    # 4. 尝试代号变体检索 (大写、带/不带 CHAR_)
    q_upper = q.upper()
    if q_upper in canonical_by_code:
        return canonical_by_code[q_upper]
    if not q_upper.startswith("CHAR_") and f"CHAR_{q_upper}" in canonical_by_code:
        return canonical_by_code[f"CHAR_{q_upper}"]
    if q_upper.startswith("CHAR_") and q_upper.replace("CHAR_", "", 1) in canonical_by_code:
        return canonical_by_code[q_upper.replace("CHAR_", "", 1)]

    # 5. 尝试归一化 Token 匹配
    norm_tok = AssetProtocolHelper.normalize_token(q)
    if norm_tok in canonical_by_code:
        return canonical_by_code[norm_tok]
    if f"CHAR_{norm_tok}" in canonical_by_code:
        return canonical_by_code[f"CHAR_{norm_tok}"]

    # 6. 从四段式 asset_key 中解析出角色 token 再次检索
    if q_upper.startswith("CHAR_"):
        c_tok, _, _ = extract_character_tokens(q_upper)
        if c_tok and c_tok in canonical_by_code:
            return canonical_by_code[c_tok]
        if c_tok and f"CHAR_{c_tok}" in canonical_by_code:
            return canonical_by_code[f"CHAR_{c_tok}"]

    return None


def parse_character_view_type(token: str, explicit_label: str = "") -> tuple[str, str, int]:
    """根据切片标识符/名称推断标准化切片类型、中文标签与是否主视觉基准:
    返回: (view_type, view_label, is_primary)
    标准 view_type:
      'main_portrait'      (is_primary=1)
      'full_body'          (is_primary=0)
      'front_view'         (is_primary=0, 单张正立面四视图)
      'side_view'          (is_primary=0, 单张侧立面四视图)
      'back_view'          (is_primary=0, 单张背立面四视图)
      'three_quarter_view' (is_primary=0, 单张3/4侧面四视图)
      'four_view'          (is_primary=0, 传统复合多角度)
      'facial_macro'       (is_primary=0)
      'hands_detail'       (is_primary=0)
    """
    combined = f"{token} {explicit_label}".upper()
    # 1. 优先识别单张四视图具体视角 (严禁四宫格合并)
    if any(k in combined for k in ("4V_FRONT", "FRONT_VIEW", "正立面", "正视图", "正面视角", "FRONT_FULL")) and not any(k in combined for k in ("FOUR_VIEW", "四视图")):
        return ("front_view", explicit_label or "正面定妆视角", 0)
    if any(k in combined for k in ("4V_SIDE", "SIDE_VIEW", "4V_PROFILE", "PROFILE", "侧立面", "侧视图", "侧面视角")):
        return ("side_view", explicit_label or "侧面定妆视角", 0)
    if any(k in combined for k in ("4V_BACK", "BACK_VIEW", "REAR", "背立面", "背视图", "背面视角")):
        return ("back_view", explicit_label or "背面定妆视角", 0)
    if any(k in combined for k in ("4V_3Q", "4V_THREE_QUARTER", "THREE_QUARTER", "3Q", "四分之三侧面", "半侧面")):
        return ("three_quarter_view", explicit_label or "3/4侧面定妆视角", 0)
    # 2. 传统/复合多角度工程切片 (four_view, is_primary=0)
    if any(k in combined for k in (
        "FOUR_VIEW", "THREE_VIEW", "4V", "3V", "SHEET", "四视图", "三视图",
        "多角度", "工程视图", "工程切片", "正侧背"
    )):
        return ("four_view", explicit_label or "角色多角度工程视图", 0)
    # 3. 全身定妆立绘 (full_body, is_primary=0)
    if any(k in combined for k in ("FULL_BODY", "FULLBODY", "BASE_COSTUME", "全身", "立绘")):
        return ("full_body", explicit_label or "全身定妆立绘", 0)
    # 4. 面部微距/特写 (facial_macro, is_primary=0)
    if any(k in combined for k in ("MACRO_FACE", "FACIAL_MACRO", "MACRO", "CLOSEUP", "FACE", "FACIAL", "面部特写", "微距", "五官")):
        return ("facial_macro", explicit_label or "面部五官超清微距切片", 0)
    # 5. 手部细节与道具交互切片 (hands_detail, is_primary=0)
    if any(k in combined for k in ("MACRO_HAND", "HANDS_DETAIL", "HAND", "HANDS", "手部", "手部特写")):
        return ("hands_detail", explicit_label or "手部与握持动作精细切片", 0)
    # 6. 默认/主视觉肖像 (main_portrait, is_primary=1)
    return ("main_portrait", explicit_label or "主视觉肖像", 1)


def extract_natural_appearance(raw_prompt: str, char_name: str = "") -> str:
    """从可能包含工程切片或视图标签的描述中，清洗提取自然人生理外貌与气质核心描述，
    避免工程切片技术词（如纯白背景、4V多角度、中性无表情、T-pose等）污染 characters 表主外貌字段。
    """
    if not raw_prompt:
        return ""
    text_clean = str(raw_prompt).strip()
    engineering_patterns = [
        r"[【\[\(（]?(?:4V|3V|四视图|三视图|正侧背|工程切片|多角度工程视图)[】\]\)）]?",
        r"(?:纯白背景|白底|中性灰色背景|T-pose|A-pose|中性站姿|无动态表情|标准工程渲染图)[，,、\s]*",
        r"(?:正面、侧面、背面、四分之三侧面)[，,、\s]*",
        r"(?:正脸主肖像|全身定妆立绘|面部特写|手部特写)[：:\s]*",
    ]
    for pat in engineering_patterns:
        text_clean = re.sub(pat, "", text_clean, flags=re.IGNORECASE)
    text_clean = re.sub(r"^[，,、；;\s]+|[，,、；;\s]+$", "", text_clean)
    return text_clean.strip() or raw_prompt.strip()


def synthesize_character_literary_defaults(
    char_name: str,
    gender: str = "male",
    role: str = "supporting",
    appearance: str = "",
    perceived_age: int | None = None,
    curr_ep: int = 1,
) -> dict[str, Any]:
    """为阶段 6 新增/偶发梳理出的角色自动合成完整文学画像、心理动力学四元组与声音配置，
    避免 characters 核心元数据字段出现 NULL 或空串。
    """
    age_str = f"{perceived_age}岁" if perceived_age else "青年"
    gender_cn = "女性" if gender == "female" else ("男性" if gender == "male" else "角色")

    # 1. 角色描述 (description)
    desc = f"第{curr_ep}集登场的重要{gender_cn}角色（定位：{role}），在当前短剧剧情发展中承担戏剧推动与矛盾推进职能。"

    # 2. 性格特质 (personality) 与 心理动力学四元组 (psychology_4)
    if role in ("protagonist", "主角"):
        personality = "意志坚韧，行动果敢，在重重危机与两难抉择中展现强烈的目标感与隐忍克制。"
        want = "打破当前困境，查明核心真相并保护关键目标"
        need = "直面内心潜藏的脆弱与执念，完成自我人格救赎"
        the_lie = "唯有完全依靠自身算计与武力方能生存"
        the_ghost = "过往惨痛的背叛或重大失败阴影"
    elif role in ("antagonist", "反派"):
        personality = "城府深沉，手段狠辣，拥有极强控制欲，为达成目的不择手段。"
        want = "彻底掌控局势并铲除一切阻碍自身计划的对手"
        need = "认知自身欲望背后的虚妄，突破毁灭性偏执"
        the_lie = "权势与绝对威慑是世间唯一的通行法则"
        the_ghost = "曾被践踏屈辱所铸就的极度不安全感"
    else:
        personality = "机警敏锐，行事沉稳，对局势变化具备精准洞察力，恪守自身处世原则。"
        want = "在动荡交锋中坚守职责底线并保障自身立场"
        need = "超越独善其身，在关键抉择时刻勇于担当"
        the_lie = "只要置身事外便能远离风暴中心的漩涡"
        the_ghost = "曾因无能为力而未能挽回的遗憾往事"

    psychology_4 = {
        "want": want,
        "need": need,
        "the_lie": the_lie,
        "the_ghost": the_ghost,
    }

    # 3. 自然人基础外貌 (appearance)
    if not appearance:
        appearance = f"外表气质硬朗鲜明，约{age_str}左右，面容轮廓分明，眼神锐利且富于情绪表现力，身形体态端正。"

    # 4. 声音演播风格 (voice_style)
    if gender == "female":
        voice_style = "清亮从容，吐字清晰，语速平稳适中，情绪起伏富有层次感与张力"
        timbre = "清雅女声，中频温润自然"
    else:
        voice_style = "沉稳有力，中气饱满，语速沉着张弛有度，尾音平稳坚定"
        timbre = "低沉磁性男音，厚度与穿透力兼备"

    # 5. 声学人格 (acoustic_persona)
    acoustic_persona = {
        "timbre": timbre,
        "speed_ratio": 1.0,
        "pitch_ratio": 1.0,
        "cadence": "沉着稳健",
        "dramatic_subtext": f"{char_name}在交锋与对话中保持高度克制与防备",
    }

    # 6. 声学指纹 (voice_fingerprint)
    fp_hash = hashlib.md5(f"{char_name}_{timbre}".encode("utf-8")).hexdigest()[:8].upper()
    voice_fingerprint = {
        "fingerprint_id": f"VF_{fp_hash}",
        "acoustic_color": timbre,
        "delivery_dynamics": voice_style,
    }

    return {
        "description": desc,
        "personality": personality,
        "psychology_4": psychology_4,
        "appearance": appearance,
        "voice_style": voice_style,
        "acoustic_persona": acoustic_persona,
        "voice_fingerprint": voice_fingerprint,
    }


def synthesize_voice_prompt(
    char_name: str,
    timbre: str = "",
    role: str = "supporting",
    personality: str = "",
    gender: str = "male",
    monologue_source: str = "",
    perceived_age: str | int | None = None,
    voice_style: str = "",
    acoustic_persona: dict[str, Any] | None = None,
) -> str:
    """合成专业级广播剧/影视配音 TTS 声音生成提示词，
    覆盖【音色基调】、【发音与节奏】、【戏剧潜台词与语调】、【多维情绪演绎规范】与【声音质感】五大维度。
    """
    clean_name = clean_character_name(char_name) or "角色"
    if not timbre and voice_style:
        timbre = voice_style
    if not timbre:
        age_str = f"{perceived_age}岁" if perceived_age else ""
        timbre = f"清雅知性{age_str}女声，中高频温润通透" if gender == "female" else f"低沉磁性{age_str}成熟男声，胸腔共鸣浑厚"

    role_desc = "核心主角" if role in ("protagonist", "主角") else ("主要反派对手" if role in ("antagonist", "反派") else "关键推动角色")
    subtext = f"言辞间透露出{personality or '内敛克制'}的心理底色，字句咬合沉稳而有锋芒"

    prompt_lines = [
        f"【音色基调】：{timbre}，声音辨识度极高，音质纯净自然，中频富有饱满度与故事叙事厚度。",
        "【发音与节奏】：标准普通话发音，咬字清晰利落，平均语速约每分钟210字，重音抑扬顿挫，停顿呼吸真实自然。",
        f"【戏剧潜台词与语调】：紧密契合「{clean_name}」的{role_desc}身份，{subtext}。",
        "【多维情绪演绎规范】：",
        "- 常态对话：冷静自持，声调平稳，句尾微收，不疾不徐；",
        "- 戏剧冲突：声压增强，节奏骤紧，爆发力十足但破而不破，富有情绪穿透力；",
        "- 独白思考：压低共鸣腔，微弱气声自然融入，显露潜意识复杂波澜。",
        "【声音质感】：专业录音棚广播剧电影级声学混音，平直频响无失真，空间混响干净，杜绝电音及机械金属感。",
    ]
    if isinstance(acoustic_persona, dict) and acoustic_persona:
        acou_notes = []
        if acoustic_persona.get("pitch_base"):
            acou_notes.append(f"基础音高: {acoustic_persona['pitch_base']}")
        if acoustic_persona.get("formant_focus"):
            acou_notes.append(f"共鸣焦点: {acoustic_persona['formant_focus']}")
        if acoustic_persona.get("texture_detail"):
            acou_notes.append(f"质感细节: {acoustic_persona['texture_detail']}")
        if acou_notes:
            prompt_lines.append(f"【声学特征细节】：{', '.join(acou_notes)}")
    if monologue_source:
        prompt_lines.append(f"【参考台词示范】：『{monologue_source}』")

    return "\n".join(prompt_lines)


# =========================================================================
# 阶段 6：单集视听资源引单与资产校验持久化
# =========================================================================

def persist_stage6(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 6 深度原子落库：
    1. 单集 AST 结构化清单写入 episodes.ast_blocks['episode_resource_manifest']；
    2. 增量角色自动建档 characters，补全新出场角色基础属性；
    3. 角色各集外观服化道与主视切片写入 character_stages 与 character_stage_views；
    4. 当前集登场角色与集数映射落库 episode_characters 关联表；
    5. 角色专属音色卡片与母音同步写入 character_voice_profiles；
    6. 增量发生场景及气候做旧图层写入 scenes, scene_zones, scene_weathering_views；
    7. 增量关键道具及其剧情战损演进形态写入 props, prop_damage_states；
    8. 视听多模态资产全景注册表更新至 dramas.metadata，同步向量记忆库。
    """
    curr_ep = (
        episode_num
        or getattr(state, "episode_number", None)
        or getattr(state, "episode_num", None)
        or getattr(state, "current_visual_episode", None)
        or (state.get("episode_number") if isinstance(state, dict) else None)
        or (state.get("episode_num") if isinstance(state, dict) else None)
        or (state.get("current_visual_episode") if isinstance(state, dict) else None)
        or 1
    )
    log.info("【阶段 6 落库】开始持久化短剧 [%s] 第 %s 集的视听资源引单与关系表资产...", drama_id, curr_ep)
    now = now_iso()

    # -------------------------------------------------------------------------
    # 0. 鲁棒提取 manifest 资源引单数据
    # -------------------------------------------------------------------------
    manifest = (
        getattr(state, "manifest", None)
        or getattr(state, "resource_manifest", None)
        or getattr(state, "episode_manifest", None)
        or getattr(state, "episode_resource_manifest", None)
    )
    if not manifest and isinstance(state, dict):
        manifest = (
            state.get("manifest")
            or state.get("resource_manifest")
            or state.get("episode_manifest")
            or state.get("episode_resource_manifest")
        )
    if not manifest and hasattr(state, "episode_manifests") and isinstance(state.episode_manifests, dict):
        manifest = state.episode_manifests.get(curr_ep)
    if not manifest and hasattr(state, "episode_resource_manifests") and isinstance(state.episode_resource_manifests, dict):
        manifest = state.episode_resource_manifests.get(curr_ep)
    if not manifest and isinstance(state, dict):
        if isinstance(state.get("episode_manifests"), dict):
            manifest = state["episode_manifests"].get(curr_ep)
        elif isinstance(state.get("episode_resource_manifests"), dict):
            manifest = state["episode_resource_manifests"].get(curr_ep)
    if not manifest and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
        extra = state.__pydantic_extra__
        m_extra = extra.get("episode_manifests") or extra.get("episode_resource_manifests")
        if isinstance(m_extra, dict):
            manifest = m_extra.get(curr_ep)

    manifest_dict = _dump_or_dict(manifest) if manifest else {}

    # 提取角色、环境、道具、音频及增量卡片清单并规范化解构为字典列表
    raw_chars = (
        manifest_dict.get("characters")
        or manifest_dict.get("characters_in_scene")
        or manifest_dict.get("characters_tier_1")
        or []
    )
    characters_manifest = _flatten_asset_collection(raw_chars, "CHAR")

    raw_envs = (
        manifest_dict.get("environments")
        or manifest_dict.get("scenes_in_use")
        or []
    )
    environments_manifest = _flatten_asset_collection(raw_envs, "ENV")

    raw_props = (
        manifest_dict.get("props")
        or manifest_dict.get("props_in_use")
        or []
    )
    props_manifest = _flatten_asset_collection(raw_props, "PROP")

    extra_dict = getattr(state, "__pydantic_extra__", None) or {}
    raw_vc = (
        getattr(state, "new_character_master_voice_cards", None)
        or (state.get("new_character_master_voice_cards") if isinstance(state, dict) else None)
        or getattr(state, "voice_cards", None)
        or (state.get("voice_cards") if isinstance(state, dict) else None)
        or extra_dict.get("new_character_master_voice_cards")
        or extra_dict.get("voice_cards")
        or manifest_dict.get("new_character_master_voice_cards")
        or manifest_dict.get("voice_cards")
        or manifest_dict.get("voice_profiles")
        or []
    )
    voice_cards = _flatten_asset_collection(raw_vc, "VOICE")

    # 提取第 6 阶段增量发掘的未登记新角色全息档案 (Stage 2 11 维建档规格)
    raw_new_chars = (
        getattr(state, "newly_discovered_characters", None)
        or (state.get("newly_discovered_characters") if isinstance(state, dict) else None)
        or extra_dict.get("newly_discovered_characters")
        or manifest_dict.get("newly_discovered_characters")
        or []
    )
    newly_discovered_characters: list[dict[str, Any]] = []
    if isinstance(raw_new_chars, list):
        for nc in raw_new_chars:
            nc_dict = _dump_or_dict(nc)
            if isinstance(nc_dict, dict):
                newly_discovered_characters.append(nc_dict)
    log.debug(
        "【阶段 6 落库】[DEBUG 增量角色发现] 接收到 newly_discovered_characters 数量=%d",
        len(newly_discovered_characters),
    )

    # 提取第 6 阶段增量发掘的未登记新场景全息档案 (Stage 3 建档规格)
    raw_new_scenes = (
        getattr(state, "newly_discovered_scenes", None)
        or (state.get("newly_discovered_scenes") if isinstance(state, dict) else None)
        or extra_dict.get("newly_discovered_scenes")
        or manifest_dict.get("newly_discovered_scenes")
        or []
    )
    newly_discovered_scenes: list[dict[str, Any]] = []
    if isinstance(raw_new_scenes, list):
        for ns in raw_new_scenes:
            ns_dict = _dump_or_dict(ns)
            if isinstance(ns_dict, dict):
                newly_discovered_scenes.append(ns_dict)
    log.debug(
        "【阶段 6 落库】[DEBUG 增量场景发现] 接收到 newly_discovered_scenes 数量=%d",
        len(newly_discovered_scenes),
    )

    # 提取第 6 阶段增量发掘的未登记新道具全息档案 (Stage 3 建档规格)
    raw_new_props = (
        getattr(state, "newly_discovered_props", None)
        or (state.get("newly_discovered_props") if isinstance(state, dict) else None)
        or extra_dict.get("newly_discovered_props")
        or manifest_dict.get("newly_discovered_props")
        or []
    )
    newly_discovered_props: list[dict[str, Any]] = []
    if isinstance(raw_new_props, list):
        for np in raw_new_props:
            np_dict = _dump_or_dict(np)
            if isinstance(np_dict, dict):
                newly_discovered_props.append(np_dict)
    log.debug(
        "【阶段 6 落库】[DEBUG 增量道具发现] 接收到 newly_discovered_props 数量=%d",
        len(newly_discovered_props),
    )

    raw_new_assets = (
        getattr(state, "newly_generated_assets", None)
        or (state.get("newly_generated_assets") if isinstance(state, dict) else None)
        or extra_dict.get("newly_generated_assets")
        or manifest_dict.get("newly_generated_assets")
        or []
    )
    newly_generated_assets = _flatten_asset_collection(raw_new_assets, "ASSET")

    raw_reused_assets = (
        getattr(state, "reused_existing_assets", None)
        or (state.get("reused_existing_assets") if isinstance(state, dict) else None)
        or extra_dict.get("reused_existing_assets")
        or manifest_dict.get("reused_existing_assets")
        or []
    )
    reused_assets_data = _flatten_asset_collection(raw_reused_assets, "REUSED")

    raw_lineage_dag = (
        getattr(state, "lineage_dag", None)
        or (state.get("lineage_dag") if isinstance(state, dict) else None)
        or extra_dict.get("lineage_dag")
        or manifest_dict.get("lineage_dag")
        or {}
    )
    lineage_dag_data = _dump_or_dict(raw_lineage_dag) if isinstance(raw_lineage_dag, dict) else {}

    raw_sem_hashes = (
        getattr(state, "semantic_hashes", None)
        or (state.get("semantic_hashes") if isinstance(state, dict) else None)
        or (
            state.visual_audio_assets_registry.get("semantic_hashes")
            if hasattr(state, "visual_audio_assets_registry") and isinstance(getattr(state, "visual_audio_assets_registry"), dict)
            else (
                state.get("visual_audio_assets_registry", {}).get("semantic_hashes")
                if isinstance(state, dict) and isinstance(state.get("visual_audio_assets_registry"), dict)
                else None
            )
        )
        or manifest_dict.get("semantic_hashes")
        or {}
    )

    # -------------------------------------------------------------------------
    # 1. 查询并更新单集 AST 结构化块 (episodes 表)
    # -------------------------------------------------------------------------
    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": curr_ep},
    )
    episode_id = ep_row["id"] if ep_row else None

    # 确保 manifest_dict 完整保留血缘 DAG、复用资产和新生成资产及语义指纹
    if lineage_dag_data:
        manifest_dict["lineage_dag"] = lineage_dag_data
    if reused_assets_data:
        manifest_dict["reused_existing_assets"] = reused_assets_data
    if newly_generated_assets:
        manifest_dict["newly_generated_assets"] = newly_generated_assets
    if raw_sem_hashes:
        manifest_dict["semantic_hashes"] = raw_sem_hashes

    if ep_row and manifest_dict:
        ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
        ep_ast["episode_resource_manifest"] = manifest_dict
        db.execute(
            text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
            {"id": episode_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
        )
        log.info(
            "【阶段 6 落库】[步骤 1/6] 单集 AST 更新完成: drama_id=%s, episode_id=%s, ep_num=%s",
            drama_id, episode_id, curr_ep,
        )
        log.debug(
            "【阶段 6 落库】[DEBUG 单集 AST] episode_resource_manifest 内容快照: keys=%s, lineage_dag 项数=%d, 复用资产数=%d",
            list(manifest_dict.keys()), len(lineage_dag_data), len(reused_assets_data),
        )
    else:
        log.warning(
            "【阶段 6 落库】[步骤 1/6] 未找到短剧 [%s] 第 %s 集 episodes 记录或引单为空",
            drama_id, curr_ep,
        )

    # -------------------------------------------------------------------------
    # 2. 角色领域三层模型深度原子落库 (characters, character_stages, character_stage_views, episode_characters)
    #    Tier 1: 自然人角色核心实体 (characters, 1 人 1 条, 聚合所有造型与切片，杜绝空字段)
    #    Tier 2: 角色生命周期服化道/形态阶段 (character_stages, 演化树 parent_stage_id)
    #    Tier 3: 角色各形态切片基准视图 (character_stage_views, 正面肖像/全身/四视图/微距)
    #    Relation: 单集登场关联绑定 (episode_characters, 仅绑定自然人实体)
    # -------------------------------------------------------------------------
    # 2.1 汇集所有角色候选源 (引单 + 生成资产 + 引擎状态池)
    raw_character_candidates: list[dict[str, Any]] = []
    seen_candidate_keys: set[str] = set()

    # 提取上游各阶段注入的文学画像状态池 (characters_engine, character_engine, characters, newly_discovered_characters)
    engine_char_pool: dict[str, dict[str, Any]] = {}
    raw_pools: list[Any] = []
    for attr in ("characters_engine", "character_engine", "characters"):
        val = getattr(state, attr, None)
        if isinstance(val, dict):
            raw_pools.extend(val.get("characters") or val.get("character_profiles") or [])
        elif isinstance(val, list):
            raw_pools.extend(val)
    if newly_discovered_characters:
        raw_pools.extend(newly_discovered_characters)

    for item in raw_pools:
        item_dict = _dump_or_dict(item)
        if not isinstance(item_dict, dict):
            continue
        c_name = str(item_dict.get("name") or item_dict.get("character_name") or "").strip()
        c_code = str(item_dict.get("character_code") or item_dict.get("char_id") or "").strip()
        clean_n = clean_character_name(c_name)
        if c_name:
            engine_char_pool[c_name] = item_dict
            engine_char_pool[c_name.lower()] = item_dict
        if clean_n:
            engine_char_pool[clean_n] = item_dict
            engine_char_pool[clean_n.lower()] = item_dict
        if c_code:
            engine_char_pool[c_code] = item_dict
            engine_char_pool[c_code.upper()] = item_dict
            stripped = c_code.replace("CHAR_", "")
            engine_char_pool[stripped] = item_dict
            engine_char_pool[f"CHAR_{stripped}"] = item_dict

    log.debug(
        "【阶段 6 落库】[Tier 1 状态池检索] 预装载上游角色文学引擎档案索引项数: %s (含本集新发现未登记角色: %d)",
        len(engine_char_pool), len(newly_discovered_characters),
    )

    # 优先装填本集新发现未登记角色 (确保 11 维全息字段优先确立 canonical_map 实体)
    for ndc in newly_discovered_characters:
        if isinstance(ndc, dict):
            k = str(ndc.get("character_code") or ndc.get("char_id") or ndc.get("name") or "").strip()
            if k:
                seen_candidate_keys.add(k)
            raw_character_candidates.append(ndc)

    for c_raw in characters_manifest:
        c = _dump_or_dict(c_raw)
        if isinstance(c, dict):
            k = str(c.get("char_id") or c.get("asset_id") or c.get("asset_key") or c.get("character_code") or c.get("name") or "").strip()
            if k:
                seen_candidate_keys.add(k)
            raw_character_candidates.append(c)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or n_dict.get("asset_key") or "")
        if (cat == "character" or aid.startswith("CHAR_")):
            if aid not in seen_candidate_keys:
                seen_candidate_keys.add(aid)
                raw_character_candidates.append(n_dict)

    # 【重要架构守卫】：raw_pools (characters_engine 全量库) 仅作为只读画像字典 (engine_char_pool) 用于回填
    # 当集登场角色的 11 维背景属性，【严禁】无条件将其全局角色注入 raw_character_candidates！
    # 否则不在本集中的全剧角色（如其他集配角）会被当成本集在场角色派生 Tier 2 造型并写入 episode_asset_usages。
    log.debug(
        "【阶段 6 落库·边界守卫】当集待落库角色候选收敛完毕: 仅收录引单/新资产/新发现角色，共计 %d 项 (已阻断全剧 %d 名全量角色池盲目渗透)",
        len(raw_character_candidates), len(raw_pools),
    )

    # 2.2 预查已登记角色库构建内存索引（包含阶段 2 的 11 维全息字段）
    existing_chars_in_db = fetch_all(
        db,
        """
        SELECT id, character_code, name, appearance, voice_style, role, description,
               personality, gender, perceived_age, identity_anchors,
               visual_consistency_code, carried_anchor_item, drama_engine,
               growth_chain, current_status,
               psychology_4, acoustic_persona, voice_fingerprint
        FROM characters
        WHERE drama_id = :drama_id
        """,
        {"drama_id": drama_id},
    )
    db_char_by_name: dict[str, dict[str, Any]] = {row["name"]: row for row in existing_chars_in_db if row.get("name")}
    db_char_by_code: dict[str, dict[str, Any]] = {row["character_code"]: row for row in existing_chars_in_db if row.get("character_code")}
    db_char_by_stripped_code: dict[str, dict[str, Any]] = {
        row["character_code"].replace("CHAR_", ""): row
        for row in existing_chars_in_db if row.get("character_code")
    }

    # 2.3 内存三层模型规范化归纳聚合 (Canonical Entity Aggregation)
    canonical_map: dict[str, dict[str, Any]] = {}

    for c in raw_character_candidates:
        raw_name = str(c.get("character_name") or c.get("name") or "").strip()
        raw_code = str(c.get("character_code") or c.get("char_id") or c.get("asset_id") or c.get("asset_key") or "").strip()
        if not raw_name and not raw_code:
            continue

        parsed_code, parsed_stage, parsed_view = extract_character_tokens(raw_code)
        clean_name = clean_character_name(raw_name)

        # 匹配既有数据库角色
        matched_db = None
        if clean_name and clean_name in db_char_by_name:
            matched_db = db_char_by_name[clean_name]
        elif raw_name and raw_name in db_char_by_name:
            matched_db = db_char_by_name[raw_name]
        elif raw_code and raw_code in db_char_by_code:
            matched_db = db_char_by_code[raw_code]
        elif parsed_code and parsed_code in db_char_by_stripped_code:
            matched_db = db_char_by_stripped_code[parsed_code]
        elif parsed_code and f"CHAR_{parsed_code}" in db_char_by_code:
            matched_db = db_char_by_code[f"CHAR_{parsed_code}"]

        # 匹配上游引擎画像 (characters_engine / character_engine / characters)
        matched_engine = (
            engine_char_pool.get(clean_name)
            or engine_char_pool.get(clean_name.lower())
            or engine_char_pool.get(raw_name)
            or engine_char_pool.get(raw_name.lower())
            or engine_char_pool.get(raw_code)
            or engine_char_pool.get(raw_code.upper())
            or (engine_char_pool.get(parsed_code) if parsed_code else None)
        )

        # 确立规范化自然人属性 (Tier 1 Entity)
        if matched_db:
            char_name = matched_db["name"]
            char_code = matched_db["character_code"]
            existing_db_id = matched_db["id"]
        elif matched_engine:
            char_name = matched_engine.get("name") or clean_name or raw_name or "未命名角色"
            char_code = matched_engine.get("character_code") or (f"CHAR_{parsed_code}" if parsed_code else (raw_code if raw_code.startswith("CHAR_") else f"CHAR_{char_name}"))
            existing_db_id = None
        else:
            char_name = clean_name or (parsed_code if parsed_code else (raw_code if raw_code else "未命名角色"))
            char_code = f"CHAR_{parsed_code}" if parsed_code else (raw_code if raw_code.startswith("CHAR_") else f"CHAR_{char_name}")
            existing_db_id = None

        # 对未在数据库登记的新角色候选进行合法性守卫：拦截声学/舞台指令或括号残片（如 "[声学行为"）
        if not matched_db and raw_name and not is_valid_character_speaker(clean_name or raw_name, known_names=set(db_char_by_name.keys())):
            log.warning(
                "【阶段 6 落库·脏数据拦截】跳过非法角色名/舞台指令候选: raw_name=%s, clean_name=%s, raw_code=%s",
                raw_name, clean_name, raw_code,
            )
            continue

        entity_key = char_name.lower()
        visual_prompt = str(c.get("visual_prompt") or c.get("appearance") or c.get("prompt") or "").strip()
        cleaned_bio_appearance = extract_natural_appearance(visual_prompt, char_name)

        if entity_key not in canonical_map:
            raw_g = str(
                c.get("gender")
                or (matched_engine.get("gender") if matched_engine else "")
                or (matched_db.get("gender") if matched_db else "")
                or ""
            ).strip().lower()
            if raw_g in ("女", "female", "f"):
                gender = "female"
            elif raw_g in ("男", "male", "m"):
                gender = "male"
            elif raw_g == "other":
                gender = "other"
            else:
                gender = "female" if any(kw in (visual_prompt + char_name) for kw in ("女", "母", "姐", "妹", "妻", "妃", "后", "裙")) else "male"

            raw_age = (
                c.get("perceived_age")
                or (matched_engine.get("perceived_age") if matched_engine else None)
                or (matched_db.get("perceived_age") if matched_db else None)
            )
            if isinstance(raw_age, (int, float)):
                perceived_age = int(raw_age)
            elif raw_age:
                m_age = re.search(r"\d+", str(raw_age))
                perceived_age = int(m_age.group()) if m_age else None
            else:
                perceived_age = None

            role = str(
                c.get("role")
                or (matched_engine.get("role") if matched_engine else "")
                or (matched_db.get("role") if matched_db else "")
                or "supporting"
            ).strip()

            desc = str(
                c.get("description")
                or (matched_engine.get("description") if matched_engine else "")
                or (matched_db.get("description") if matched_db else "")
                or ""
            ).strip()

            personality = str(
                c.get("personality")
                or (matched_engine.get("personality") if matched_engine else "")
                or (matched_db.get("personality") if matched_db else "")
                or ""
            ).strip()

            appearance = (
                (matched_engine.get("appearance") if matched_engine else "")
                or (matched_db.get("appearance") if matched_db else "")
                or cleaned_bio_appearance
            ).strip()

            voice_style = str(
                c.get("voice_style")
                or (matched_engine.get("voice_style") if matched_engine else "")
                or (matched_db.get("voice_style") if matched_db else "")
                or ""
            ).strip()

            psychology_4 = (
                c.get("psychology_4") or c.get("psychological_quad")
                or (matched_engine.get("psychology_4") or matched_engine.get("psychological_quad") if matched_engine else None)
                or (matched_db.get("psychology_4") if matched_db else None)
            )

            acoustic_persona = (
                c.get("acoustic_persona")
                or (matched_engine.get("acoustic_persona") if matched_engine else None)
                or (matched_db.get("acoustic_persona") if matched_db else None)
            )

            voice_fingerprint = (
                c.get("voice_fingerprint")
                or (matched_engine.get("voice_fingerprint") if matched_engine else None)
                or (matched_db.get("voice_fingerprint") if matched_db else None)
            )

            identity_anchors = (
                c.get("identity_anchors")
                or (matched_engine.get("identity_anchors") if matched_engine else None)
                or (matched_db.get("identity_anchors") if matched_db else None)
            )

            visual_consistency_code = (
                c.get("visual_consistency_code")
                or (matched_engine.get("visual_consistency_code") if matched_engine else None)
                or (matched_db.get("visual_consistency_code") if matched_db else None)
            )
            carried_anchor_item = (
                c.get("carried_anchor_item")
                or (matched_engine.get("carried_anchor_item") if matched_engine else None)
                or (matched_db.get("carried_anchor_item") if matched_db else None)
            )
            drama_engine = (
                c.get("drama_engine")
                or (matched_engine.get("drama_engine") if matched_engine else None)
                or (matched_db.get("drama_engine") if matched_db else None)
            )
            growth_chain = (
                c.get("growth_chain")
                or (matched_engine.get("growth_chain") if matched_engine else None)
                or (matched_db.get("growth_chain") if matched_db else None)
            )
            current_status = (
                c.get("current_status")
                or (matched_engine.get("current_status") if matched_engine else None)
                or (matched_db.get("current_status") if matched_db else None)
            )
            new_relationships = (
                c.get("new_relationships")
                or (matched_engine.get("new_relationships") if matched_engine else None)
                or []
            )

            # 智能合成保底文学/心理/声音画像（防止字段出现 NULL 或空值，完全对齐阶段 2 11 维建档规格）
            lit_defaults = synthesize_character_literary_defaults(
                char_name=char_name,
                gender=gender,
                role=role,
                appearance=appearance,
                perceived_age=perceived_age,
                curr_ep=curr_ep,
            )
            if not desc or desc == f"第{curr_ep}集登场角色":
                desc = lit_defaults["description"]
            if not personality:
                personality = lit_defaults["personality"]
            if not appearance:
                appearance = lit_defaults["appearance"]
            if not psychology_4 or psychology_4 == {} or psychology_4 == "{}":
                psychology_4 = lit_defaults["psychology_4"]
            if not voice_style:
                voice_style = lit_defaults["voice_style"]
            if not acoustic_persona or acoustic_persona == {} or acoustic_persona == "{}":
                acoustic_persona = lit_defaults["acoustic_persona"]
            if not voice_fingerprint or voice_fingerprint == {} or voice_fingerprint == "{}":
                voice_fingerprint = lit_defaults["voice_fingerprint"]
            if not identity_anchors:
                identity_anchors = [appearance[:60] or f"{char_name}面部与装造生理锚点"]
            if not visual_consistency_code:
                visual_consistency_code = {
                    "base_face_lock": appearance[:80] or f"{char_name}面部骨骼特征锚定",
                    "default_costume_lock": f"第{curr_ep}集标准日常造型",
                    "skin_texture": "真实微瑕皮肤，清晰毛孔与自然高光，杜绝磨皮塑料感",
                }
            if not carried_anchor_item:
                carried_anchor_item = {
                    "item_name": f"{char_name}随身信物",
                    "visual_detail": "带有岁月摩挲痕迹与剧情线索的贴身小物件",
                }
            if not drama_engine:
                drama_engine = {
                    "core_motivation": f"在第{curr_ep}集冲突中守护核心利益并推动剧情转折",
                    "fatal_weakness": "对关键秘密或人际软肋的隐瞒",
                }
            if not growth_chain:
                growth_chain = [{
                    "episode": curr_ep,
                    "phase": f"第{curr_ep}集初登场建档",
                    "state": "卷入当前集核心戏剧冲突",
                }]
            if not current_status:
                current_status = {
                    "onboarded_at_episode": curr_ep,
                    "physical_state": "normal",
                    "emotional_state": "alert",
                }

            identity_anchors_str = _ensure_valid_json_str(identity_anchors, "[]")
            visual_consistency_code_str = _ensure_valid_json_str(
                visual_consistency_code,
                "{}",
                wrap_key="base_face_lock",
            )
            carried_anchor_item_str = _ensure_valid_json_str(
                carried_anchor_item,
                "{}",
                wrap_key="item_name",
            )
            drama_engine_str = _ensure_valid_json_str(
                drama_engine,
                "{}",
                wrap_key="core_motivation",
            )
            growth_chain_str = _ensure_valid_json_str(growth_chain, "[]")
            current_status_str = _ensure_valid_json_str(
                current_status,
                "{}",
                wrap_key="state",
            )
            psychology_4_str = _ensure_valid_json_str(
                psychology_4,
                "{}",
                wrap_key="summary",
            )
            acoustic_persona_str = _ensure_valid_json_str(
                acoustic_persona,
                "{}",
                wrap_key="tone",
            )
            voice_fingerprint_str = _ensure_valid_json_str(
                voice_fingerprint,
                "{}",
                wrap_key="catchphrase",
            )

            canonical_map[entity_key] = {
                "db_id": existing_db_id,
                "char_name": char_name,
                "char_code": char_code,
                "gender": gender,
                "perceived_age": perceived_age,
                "role": role,
                "description": desc,
                "personality": personality,
                "appearance": appearance,
                "identity_anchors": identity_anchors_str,
                "visual_consistency_code": visual_consistency_code_str,
                "carried_anchor_item": carried_anchor_item_str,
                "drama_engine": drama_engine_str,
                "growth_chain": growth_chain_str,
                "current_status": current_status_str,
                "voice_style": voice_style,
                "psychology_4": psychology_4_str,
                "acoustic_persona": acoustic_persona_str,
                "voice_fingerprint": voice_fingerprint_str,
                "new_relationships": new_relationships if isinstance(new_relationships, list) else [],
                "stages": {},
            }
            log.debug(
                "【阶段 6 落库】[Tier 1 规范化归纳] 登记 11 维实体 [%s]: 代号=%s, 性别=%s, 定位=%s, 外貌字数=%s, 心理画像状态=%s, 新增关系数=%d",
                char_name, char_code, gender, role, len(appearance), "已具备" if psychology_4_str else "无",
                len(new_relationships) if isinstance(new_relationships, list) else 0,
            )
        else:
            ent = canonical_map[entity_key]
            if ent.get("perceived_age") is None:
                r_age = c.get("perceived_age") or (matched_engine.get("perceived_age") if matched_engine else None)
                if isinstance(r_age, (int, float)):
                    ent["perceived_age"] = int(r_age)
                elif r_age:
                    m_age = re.search(r"\d+", str(r_age))
                    if m_age:
                        ent["perceived_age"] = int(m_age.group())
            if (not ent.get("appearance") or len(ent.get("appearance")) < 5) and cleaned_bio_appearance:
                ent["appearance"] = cleaned_bio_appearance
            if not ent.get("voice_style"):
                vs = str(c.get("voice_style") or (matched_engine.get("voice_style") if matched_engine else "") or "").strip()
                if vs:
                    ent["voice_style"] = vs
            if not ent.get("personality"):
                p = str(c.get("personality") or (matched_engine.get("personality") if matched_engine else "") or "").strip()
                if p:
                    ent["personality"] = p
            if not ent.get("description"):
                d = str(c.get("description") or (matched_engine.get("description") if matched_engine else "") or "").strip()
                if d:
                    ent["description"] = d

        # 确立二级形态阶段 (Tier 2 Stage)
        stage_code = str(
            c.get("stage_code")
            or c.get("tier")
            or parsed_stage
            or ("T1" if "_T1_" in raw_code or "BASE" in raw_code else "")
        ).strip()
        if not stage_code:
            st_m = re.search(r"_(T\d+)_", raw_code)
            stage_code = st_m.group(1).upper() if st_m else "T1"
        else:
            if re.match(r"^[ts]\d+", stage_code, re.IGNORECASE):
                stage_code = stage_code.upper()

        stage_name = str(c.get("stage_name") or c.get("appearance_variant") or c.get("outfit") or "").strip()
        if not stage_name:
            b_m = re.search(r"[\(（\[【]([^\)）\]】]+)[\)）\]】]", raw_name)
            if b_m:
                b_val = b_m.group(1).strip()
                if not any(k in b_val for k in ("定妆", "肖像", "特写", "视图", "切片", "微距", "立绘")):
                    stage_name = b_val
        if not stage_name:
            stage_name = f"{char_name}_{stage_code}造型" if stage_code not in ("T1", "BASE") else f"第{curr_ep}集造型"

        parent_ref = c.get("parent_stage_id") or c.get("parent_asset_id") or c.get("parent_stage_code") or c.get("parent_stage_name") or ""
        costume_desc = str(c.get("costume_description") or c.get("visual_prompt") or c.get("appearance") or c.get("prompt") or "").strip()
        color_palette = c.get("color_palette")
        color_palette_str = json.dumps(color_palette, ensure_ascii=False) if isinstance(color_palette, (dict, list)) else (str(color_palette) if color_palette else None)

        stages_dict = canonical_map[entity_key]["stages"]
        if stage_code not in stages_dict:
            stages_dict[stage_code] = {
                "stage_code": stage_code,
                "stage_name": stage_name,
                "parent_stage_ref": parent_ref,
                "costume_description": costume_desc,
                "color_palette": color_palette_str,
                "views": {},
            }
        else:
            st_data = stages_dict[stage_code]
            if not st_data.get("parent_stage_ref") and parent_ref:
                st_data["parent_stage_ref"] = parent_ref
            if not st_data.get("costume_description") and costume_desc:
                st_data["costume_description"] = costume_desc

        # 确立三级切片视图 (Tier 3 Slices)
        token = parsed_view or c.get("function_type") or c.get("view_type") or raw_code
        explicit_label = c.get("view_label") or c.get("slice_name") or raw_name
        view_type, default_label, is_primary = parse_character_view_type(token, explicit_label)

        if c.get("view_type"):
            view_type = str(c["view_type"]).strip()
            is_primary = 1 if view_type == "main_portrait" else 0

        view_prompt = str(c.get("prompt") or c.get("image_prompt") or c.get("visual_prompt") or c.get("appearance") or "").strip()
        neg_prompt = str(c.get("negative_prompt") or "").strip() or None
        image_url = str(c.get("image_url") or c.get("url") or "").strip() or None
        local_path = str(c.get("local_path") or "").strip() or None
        seedance2_id = str(c.get("seedance2_asset_id") or "").strip() or None
        asset_key = str(c.get("asset_key") or c.get("asset_id") or raw_code or "").strip()
        c_parent_key = c.get("parent_asset_key") or c.get("parent_asset_id")
        c_gen_mode = c.get("generation_mode")
        c_denoise = c.get("denoise_strength") if c.get("denoise_strength") is not None else c.get("recommended_denoise")
        c_ctrl_type = c.get("control_type")
        c_is_bench = c.get("is_benchmark")

        st_views = stages_dict[stage_code]["views"]
        if view_type not in st_views:
            st_views[view_type] = {
                "view_type": view_type,
                "view_label": explicit_label or default_label,
                "image_prompt": view_prompt,
                "negative_prompt": neg_prompt,
                "image_url": image_url,
                "local_path": local_path,
                "seedance2_asset_id": seedance2_id,
                "is_primary": is_primary,
                "asset_keys": [asset_key] if asset_key else [],
                "parent_asset_key": c_parent_key,
                "generation_mode": c_gen_mode,
                "denoise_strength": c_denoise,
                "control_type": c_ctrl_type,
                "is_benchmark": c_is_bench,
            }
        else:
            v_entry = st_views[view_type]
            if view_prompt:
                v_entry["image_prompt"] = view_prompt
            if not v_entry.get("image_url") and image_url:
                v_entry["image_url"] = image_url
            if not v_entry.get("local_path") and local_path:
                v_entry["local_path"] = local_path
            if asset_key and asset_key not in v_entry["asset_keys"]:
                v_entry["asset_keys"].append(asset_key)
            if not v_entry.get("parent_asset_key") and c_parent_key:
                v_entry["parent_asset_key"] = c_parent_key
            if not v_entry.get("generation_mode") and c_gen_mode:
                v_entry["generation_mode"] = c_gen_mode
            if v_entry.get("denoise_strength") is None and c_denoise is not None:
                v_entry["denoise_strength"] = c_denoise
            if not v_entry.get("control_type") and c_ctrl_type:
                v_entry["control_type"] = c_ctrl_type

        # 兼容 Table 6 嵌套双字段 (base_portrait / base_costume)
        bp_ref = str(c.get("base_portrait") or "").strip()
        if bp_ref:
            if "main_portrait" not in st_views:
                st_views["main_portrait"] = {
                    "view_type": "main_portrait",
                    "view_label": "正面主视觉基准切片",
                    "image_prompt": view_prompt,
                    "negative_prompt": neg_prompt,
                    "image_url": image_url,
                    "local_path": local_path,
                    "seedance2_asset_id": seedance2_id,
                    "is_primary": 1,
                    "asset_keys": [bp_ref],
                    "parent_asset_key": None,
                    "generation_mode": "t2i",
                    "is_benchmark": 1,
                }
            elif bp_ref not in st_views["main_portrait"]["asset_keys"]:
                st_views["main_portrait"]["asset_keys"].append(bp_ref)

        bc_ref = str(c.get("base_costume") or "").strip()
        if bc_ref:
            if "full_body" not in st_views:
                st_views["full_body"] = {
                    "view_type": "full_body",
                    "view_label": "全身定妆立绘",
                    "image_prompt": costume_desc or view_prompt,
                    "negative_prompt": neg_prompt,
                    "image_url": image_url,
                    "local_path": local_path,
                    "seedance2_asset_id": seedance2_id,
                    "is_primary": 0,
                    "asset_keys": [bc_ref],
                    "parent_asset_key": bp_ref or None,
                    "generation_mode": "i2i",
                    "denoise_strength": 0.45,
                    "is_benchmark": 0,
                }
            elif bc_ref not in st_views["full_body"]["asset_keys"]:
                st_views["full_body"]["asset_keys"].append(bc_ref)

    # 规范化阶段视图：确保每阶段有且仅有一个 is_primary=1 主视觉锚点
    for ent in canonical_map.values():
        for st_code, st_info in ent["stages"].items():
            st_views = st_info["views"]
            if not st_views:
                st_views["main_portrait"] = {
                    "view_type": "main_portrait",
                    "view_label": "正面主视觉基准切片",
                    "image_prompt": st_info.get("costume_description") or ent.get("appearance") or "",
                    "negative_prompt": None,
                    "image_url": None,
                    "local_path": None,
                    "seedance2_asset_id": None,
                    "is_primary": 1,
                    "asset_keys": [],
                }
            elif "main_portrait" in st_views:
                st_views["main_portrait"]["is_primary"] = 1
                for vt, vi in st_views.items():
                    if vt != "main_portrait":
                        vi["is_primary"] = 0
            else:
                has_prim = any(vi.get("is_primary") == 1 for vi in st_views.values())
                if not has_prim:
                    first_k = next(iter(st_views.keys()))
                    st_views[first_k]["is_primary"] = 1

    # 构建全局多维双向索引，支持任意凭证（中文名、代号、去前缀、归一化Token）快速索引实体
    canonical_by_name: dict[str, dict[str, Any]] = {}
    canonical_by_code: dict[str, dict[str, Any]] = {}

    for ent in canonical_map.values():
        c_name = ent["char_name"]
        c_clean_name = clean_character_name(c_name)
        c_code = ent["char_code"]
        c_code_stripped = c_code.replace("CHAR_", "", 1) if c_code.startswith("CHAR_") else c_code
        c_norm_tok = AssetProtocolHelper.normalize_token(c_code or c_name)

        if c_name:
            canonical_by_name[c_name] = ent
            canonical_by_name[c_name.lower()] = ent
        if c_clean_name:
            canonical_by_name[c_clean_name] = ent
            canonical_by_name[c_clean_name.lower()] = ent

        if c_code:
            canonical_by_code[c_code] = ent
            canonical_by_code[c_code.upper()] = ent
        if c_code_stripped:
            canonical_by_code[c_code_stripped] = ent
            canonical_by_code[c_code_stripped.upper()] = ent
        if c_norm_tok:
            canonical_by_code[c_norm_tok] = ent
            canonical_by_code[f"CHAR_{c_norm_tok}"] = ent

    log.debug(
        "【阶段 6 落库·双向索引初始化】已为 %d 位角色构建多维查找索引 (name_keys=%d, code_keys=%d)",
        len(canonical_map), len(canonical_by_name), len(canonical_by_code),
    )

    # 2.4 层级式物理落库 (Tier 1 -> Tier 2 -> Tier 3 + 集关联绑定)
    active_char_db_ids: list[int] = []
    stage_db_ids_by_code: dict[str, int] = {}
    stage_db_ids_by_name: dict[str, int] = {}
    asset_character_meta_map: dict[str, dict[str, Any]] = {}
    unresolved_stage_parents: list[dict[str, Any]] = []

    for ent_key, ent in canonical_map.items():
        char_name = ent["char_name"]
        char_code = ent["char_code"]
        char_id = ent.get("db_id")
        bench_char_key = AssetProtocolHelper.get_benchmark_key_for_character(char_code)

        # 序列化高级心理学四象限与声学画像
        psychology_4_json = _ensure_valid_json_str(ent.get("psychology_4"), "{}", wrap_key="summary")
        acoustic_persona_json = _ensure_valid_json_str(ent.get("acoustic_persona"), "{}", wrap_key="tone")
        voice_fingerprint_json = _ensure_valid_json_str(ent.get("voice_fingerprint"), "{}", wrap_key="catchphrase")

        if char_id:
            active_char_db_ids.append(char_id)
            db.execute(
                text("""
                    UPDATE characters
                    SET appearance = CASE WHEN appearance IS NULL OR appearance = '' THEN :appearance ELSE appearance END,
                        voice_style = CASE WHEN voice_style IS NULL OR voice_style = '' THEN :voice_style ELSE voice_style END,
                        personality = CASE WHEN personality IS NULL OR personality = '' THEN :personality ELSE personality END,
                        description = CASE WHEN description IS NULL OR description = '' THEN :description ELSE description END,
                        identity_anchors = CASE WHEN identity_anchors IS NULL OR identity_anchors = '' THEN :identity_anchors ELSE identity_anchors END,
                        visual_consistency_code = CASE WHEN visual_consistency_code IS NULL OR visual_consistency_code = '' OR visual_consistency_code = '{}' THEN :visual_consistency_code ELSE visual_consistency_code END,
                        carried_anchor_item = CASE WHEN carried_anchor_item IS NULL OR carried_anchor_item = '' OR carried_anchor_item = '{}' THEN :carried_anchor_item ELSE carried_anchor_item END,
                        drama_engine = CASE WHEN drama_engine IS NULL OR drama_engine = '' OR drama_engine = '{}' THEN :drama_engine ELSE drama_engine END,
                        growth_chain = CASE WHEN growth_chain IS NULL OR growth_chain = '' OR growth_chain = '[]' THEN :growth_chain ELSE growth_chain END,
                        current_status = CASE WHEN current_status IS NULL OR current_status = '' OR current_status = '{}' THEN :current_status ELSE current_status END,
                        psychology_4 = CASE WHEN psychology_4 IS NULL OR psychology_4 = '' OR psychology_4 = '{}' THEN :psychology_4 ELSE psychology_4 END,
                        acoustic_persona = CASE WHEN acoustic_persona IS NULL OR acoustic_persona = '' OR acoustic_persona = '{}' THEN :acoustic_persona ELSE acoustic_persona END,
                        voice_fingerprint = CASE WHEN voice_fingerprint IS NULL OR voice_fingerprint = '' OR voice_fingerprint = '{}' THEN :voice_fingerprint ELSE voice_fingerprint END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :benchmark_asset_key != '' THEN :benchmark_asset_key ELSE benchmark_asset_key END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": char_id,
                    "appearance": ent.get("appearance") or "",
                    "voice_style": ent.get("voice_style") or "",
                    "personality": ent.get("personality") or "",
                    "description": ent.get("description") or "",
                    "identity_anchors": ent.get("identity_anchors"),
                    "visual_consistency_code": ent.get("visual_consistency_code") or "{}",
                    "carried_anchor_item": ent.get("carried_anchor_item") or "{}",
                    "drama_engine": ent.get("drama_engine") or "{}",
                    "growth_chain": ent.get("growth_chain") or "[]",
                    "current_status": ent.get("current_status") or "{}",
                    "psychology_4": psychology_4_json,
                    "acoustic_persona": acoustic_persona_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "benchmark_asset_key": bench_char_key,
                    "now": now,
                },
            )
            log.debug(
                "【阶段 6 落库】[Tier 1 角色实体] 识别并更新已登记自然人角色: ID=%s, 代号=%s, 姓名=%s, 基准键=%s",
                char_id, char_code, char_name, bench_char_key,
            )
        else:
            c_ins = db.execute(
                text("""
                    INSERT INTO characters (
                        drama_id, character_code, name, gender, perceived_age,
                        role, description, personality, appearance,
                        identity_anchors, visual_consistency_code,
                        carried_anchor_item, drama_engine, growth_chain, current_status,
                        voice_style, acoustic_persona,
                        psychology_4, voice_fingerprint, benchmark_asset_key, created_at, updated_at
                    ) VALUES (
                        :drama_id, :character_code, :name, :gender, :perceived_age,
                        :role, :description, :personality, :appearance,
                        :identity_anchors, :visual_consistency_code,
                        :carried_anchor_item, :drama_engine, :growth_chain, :current_status,
                        :voice_style, :acoustic_persona,
                        :psychology_4, :voice_fingerprint, :benchmark_asset_key, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "character_code": char_code,
                    "name": char_name,
                    "gender": ent.get("gender") or "male",
                    "perceived_age": ent.get("perceived_age"),
                    "role": ent.get("role") or "supporting",
                    "description": ent.get("description") or f"第{curr_ep}集登场角色",
                    "personality": ent.get("personality") or "",
                    "appearance": ent.get("appearance") or "",
                    "identity_anchors": ent.get("identity_anchors"),
                    "visual_consistency_code": ent.get("visual_consistency_code") or "{}",
                    "carried_anchor_item": ent.get("carried_anchor_item") or "{}",
                    "drama_engine": ent.get("drama_engine") or "{}",
                    "growth_chain": ent.get("growth_chain") or "[]",
                    "current_status": ent.get("current_status") or "{}",
                    "voice_style": ent.get("voice_style") or "",
                    "acoustic_persona": acoustic_persona_json,
                    "psychology_4": psychology_4_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "benchmark_asset_key": bench_char_key,
                    "now": now,
                },
            )
            char_id = getattr(c_ins, "lastrowid", None) or 1
            ent["db_id"] = char_id
            active_char_db_ids.append(char_id)
            db_char_by_name[char_name] = {"id": char_id, "character_code": char_code, "name": char_name}
            db_char_by_code[char_code] = {"id": char_id, "character_code": char_code, "name": char_name}
            log.info(
                "【阶段 6 落库】[Tier 1 角色实体] 增量角色按阶段 2 11 维标准自动建档入库: ID=%s, 代号=%s, 姓名=%s, 基准键=%s",
                char_id, char_code, char_name, bench_char_key,
            )

        # 级联落库新角色双轨关系矩阵 (character_relationship)
        for rel_raw in ent.get("new_relationships") or []:
            rel = _dump_or_dict(rel_raw)
            if not isinstance(rel, dict):
                continue
            char_a_code = str(
                rel.get("character_a_code")
                or rel.get("character_a")
                or rel.get("source_code")
                or char_code
            ).strip()
            char_b_code = str(
                rel.get("character_b_code")
                or rel.get("character_b")
                or rel.get("target_character_code")
                or rel.get("target_code")
                or ""
            ).strip()
            target_name_val = rel.get("target_character_name") or rel.get("target_name")
            if not char_b_code and target_name_val:
                t_name = str(target_name_val).strip()
                if t_name in db_char_by_name:
                    char_b_code = db_char_by_name[t_name]["character_code"]
                else:
                    char_b_code = f"CHAR_{AssetProtocolHelper.normalize_token(t_name)}"
            if not char_a_code or not char_b_code or char_a_code == char_b_code:
                continue

            social_label = str(
                rel.get("social_label")
                or rel.get("surface_relation")
                or rel.get("relation_type")
                or "分集交互博弈关系"
            ).strip()
            tension_index = int(rel.get("tension_index") or rel.get("tension_level") or 65)
            drama_func = str(rel.get("drama_function") or "catalyst").strip()
            shared_props = rel.get("shared_history_props") or []
            shared_props_json = json.dumps(shared_props if isinstance(shared_props, list) else [str(shared_props)], ensure_ascii=False)
            raw_gap = rel.get("information_gap") or {"knows_truth_initially": False, "current_belief": f"第{curr_ep}集交锋认知", "reveal_condition": "剧情冲突揭晓"}
            gap_dict = raw_gap if isinstance(raw_gap, dict) else {"current_belief": str(raw_gap)}
            gap_json = json.dumps(gap_dict, ensure_ascii=False)
            knows_truth_initially = 1 if gap_dict.get("knows_truth_initially") else 0
            current_belief = str(gap_dict.get("current_belief") or "").strip()
            reveal_condition = str(gap_dict.get("reveal_condition") or "").strip()
            raw_swing = rel.get("swing_point") or {"can_defect": False, "defect_condition": None}
            swing_dict = raw_swing if isinstance(raw_swing, dict) else {"can_defect": False, "defect_condition": str(raw_swing)}
            swing_json = json.dumps(swing_dict, ensure_ascii=False)
            can_defect = 1 if swing_dict.get("can_defect") else 0
            defect_condition = str(swing_dict.get("defect_condition") or "").strip()

            existing_rel = fetch_one(
                db,
                "SELECT id FROM character_relationship WHERE drama_id = :drama_id AND character_a_code = :a_code AND character_b_code = :b_code",
                {"drama_id": drama_id, "a_code": char_a_code, "b_code": char_b_code},
            )
            if not existing_rel:
                db.execute(
                    text("""
                        INSERT INTO character_relationship (
                            drama_id, character_a_code, character_b_code,
                            social_label, tension_index, drama_function,
                            shared_history_props, information_gap,
                            knows_truth_initially, current_belief, reveal_condition,
                            can_defect, defect_condition, swing_point, raw,
                            created_at, updated_at
                        ) VALUES (
                            :drama_id, :character_a_code, :character_b_code,
                            :social_label, :tension_index, :drama_function,
                            :shared_history_props, :information_gap,
                            :knows_truth_initially, :current_belief, :reveal_condition,
                            :can_defect, :defect_condition, :swing_point, :raw,
                            :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "character_a_code": char_a_code,
                        "character_b_code": char_b_code,
                        "social_label": social_label,
                        "tension_index": tension_index,
                        "drama_function": drama_func,
                        "shared_history_props": shared_props_json,
                        "information_gap": gap_json,
                        "knows_truth_initially": knows_truth_initially,
                        "current_belief": current_belief,
                        "reveal_condition": reveal_condition,
                        "can_defect": can_defect,
                        "defect_condition": defect_condition,
                        "swing_point": swing_json,
                        "raw": json.dumps(rel, ensure_ascii=False),
                        "now": now,
                    },
                )
                log.debug(
                    "【阶段 6 落库】[DEBUG 增量关系对] 成功建立增量角色双轨关系: %s -> %s (%s)",
                    char_a_code, char_b_code, social_label,
                )

        # 单集登场关联绑定 (episode_characters): 仅绑定自然人实体
        if episode_id and char_id:
            existing_ec = fetch_one(
                db,
                "SELECT 1 FROM episode_characters WHERE episode_id = :eid AND character_id = :cid",
                {"eid": episode_id, "cid": char_id},
            )
            if not existing_ec:
                db.execute(
                    text("INSERT INTO episode_characters (episode_id, character_id) VALUES (:eid, :cid)"),
                    {"eid": episode_id, "cid": char_id},
                )
                log.info(
                    "【阶段 6 落库】[步骤 2/6 集-角色绑定] 成功绑定第 %s 集与自然人角色: episode_id=%s, character_id=%s, 角色名=%s",
                    curr_ep, episode_id, char_id, char_name,
                )

        # Tier 2: 角色多形态生命周期造型从表 (character_stages)
        for st_code, st_data in ent["stages"].items():
            stage_name = st_data["stage_name"]
            parent_ref = st_data.get("parent_stage_ref")

            parent_stage_id = 0
            if isinstance(parent_ref, int) and parent_ref > 0:
                parent_stage_id = parent_ref
            elif isinstance(parent_ref, str) and parent_ref.strip():
                ref_str = parent_ref.strip()
                if ref_str in stage_db_ids_by_code:
                    parent_stage_id = stage_db_ids_by_code[ref_str]
                elif ref_str in stage_db_ids_by_name:
                    parent_stage_id = stage_db_ids_by_name[ref_str]
                else:
                    parent_row = fetch_one(
                        db,
                        """
                        SELECT id FROM character_stages
                        WHERE drama_id = :drama_id AND (stage_code = :ref OR stage_name = :ref)
                        """,
                        {"drama_id": drama_id, "ref": ref_str},
                    )
                    if parent_row:
                        parent_stage_id = parent_row["id"]
                    else:
                        unresolved_stage_parents.append({
                            "stage_code": st_code,
                            "parent_ref": ref_str,
                        })

            existing_stage = fetch_one(
                db,
                """
                SELECT id, stage_code, parent_stage_id
                FROM character_stages
                WHERE character_id = :char_id AND (
                    (stage_code IS NOT NULL AND stage_code != '' AND stage_code = :s_code)
                    OR stage_name = :s_name
                )
                """,
                {"char_id": char_id, "s_name": stage_name, "s_code": st_code},
            )

            if existing_stage:
                stage_db_id = existing_stage["id"]
                db.execute(
                    text("""
                        UPDATE character_stages
                        SET end_episode = CASE WHEN end_episode < :curr_ep THEN :curr_ep ELSE end_episode END,
                            stage_code = CASE WHEN (stage_code IS NULL OR stage_code = '') AND :stage_code != '' THEN :stage_code ELSE stage_code END,
                            parent_stage_id = CASE WHEN (parent_stage_id IS NULL OR parent_stage_id = 0) AND :parent_stage_id > 0 THEN :parent_stage_id ELSE parent_stage_id END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": stage_db_id,
                        "curr_ep": curr_ep,
                        "stage_code": st_code,
                        "parent_stage_id": parent_stage_id,
                        "now": now,
                    },
                )
            else:
                costume_desc = st_data.get("costume_description") or ""
                color_pal = st_data.get("color_palette")
                st_ins = db.execute(
                    text("""
                        INSERT INTO character_stages (
                            character_id, drama_id, stage_name, stage_code, parent_stage_id,
                            start_episode, end_episode, costume_description, color_palette,
                            is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :character_id, :drama_id, :stage_name, :stage_code, :parent_stage_id,
                            :start_episode, :end_episode, :costume_description, :color_palette,
                            1, :now, :now
                        )
                    """),
                    {
                        "character_id": char_id,
                        "drama_id": drama_id,
                        "stage_name": stage_name,
                        "stage_code": st_code,
                        "parent_stage_id": parent_stage_id,
                        "start_episode": curr_ep,
                        "end_episode": curr_ep,
                        "costume_description": costume_desc,
                        "color_palette": color_pal,
                        "now": now,
                    },
                )
                stage_db_id = getattr(st_ins, "lastrowid", None) or 1
                log.info(
                    "【阶段 6 落库】[Tier 2 角色形态从表] 建立角色 [%s] 造型形态: stage_id=%s, stage_code=%s, stage_name=%s, parent_stage_id=%s",
                    char_name, stage_db_id, st_code, stage_name, parent_stage_id,
                )

            stage_db_ids_by_code[st_code] = stage_db_id
            stage_db_ids_by_name[stage_name] = stage_db_id

            # Tier 3: 角色各形态切片视图从表 (character_stage_views)
            for v_type, v_info in st_data["views"].items():
                v_label = v_info.get("view_label") or v_type
                v_url = v_info.get("image_url")
                v_local_path = v_info.get("local_path")
                v_seedance = v_info.get("seedance2_asset_id")
                is_prim = v_info.get("is_primary", 1 if v_type == "main_portrait" else 0)

                # 阶段 6 资产拓扑图与四维提示词解构
                cur_v_key = AssetProtocolHelper.build_character_asset_key(char_code, st_code, v_type)
                dep = AssetProtocolHelper.get_dependency_rule(cur_v_key)

                # 提取当前角色自然人的归一化令牌，用于同一实体约束校验
                curr_char_token = AssetProtocolHelper.normalize_token(char_code or char_name)

                # -------------------------------------------------------------
                # 血统防污染守卫 (Same-Entity Lineage Guard):
                # 1. 仅当一阶主视觉肖像 (main_portrait 且 st_code in ('T1', 'STAGE_1')) 为自然人第一基准，
                #    锁定为文生图 (t2i)，父级必为 None，is_benchmark 为 1
                # 2. 二阶/三阶换装主肖像 (main_portrait 且 st_code 不在 ('T1', 'STAGE_1')) 必须是图生图 (i2i)，
                #    父级严格锚定至同角色 T1 主肖像，denoise_strength 为 0.35，is_benchmark 为 0
                # 3. 衍生切片 (full_body/4v_front/side/back/macro) 必须严格继承自同角色的基准肖像，
                #    若传入异构角色资产（如角色 B 的视图错误指向角色 A 的肖像），立即拦截纠偏！
                # -------------------------------------------------------------
                candidate_parent = v_info.get("parent_asset_key")
                parent_asset_key = None

                if v_type == "main_portrait" and st_code in ("T1", "STAGE_1"):
                    # 仅一阶基准肖像无父级，为文生图根节点
                    parent_asset_key = None
                    gen_mode = "t2i"
                    denoise_str = 0.0
                    log.debug(
                        "【阶段 6 视图血缘·一阶基准肖像锁定】角色 [%s](%s) 阶段 %s 视图 main_portrait 锁定为文生图根节点 (parent=None, gen_mode=t2i)",
                        char_name, char_code, st_code,
                    )
                else:
                    # 衍生视图 或 二阶/三阶换装主肖像：进行同实体血缘一致性强校验
                    if candidate_parent:
                        p_code, _, _ = extract_character_tokens(str(candidate_parent).strip())
                        parent_char_token = AssetProtocolHelper.normalize_token(p_code) if p_code else ""
                        if parent_char_token and parent_char_token == curr_char_token:
                            # 验证通过：父级资产确实归属于当前同一角色
                            parent_asset_key = candidate_parent
                            log.debug(
                                "【阶段 6 视图血缘·同角色校验通过】角色 [%s] 阶段 %s 视图 %s 成功关联同源父级: %s (token=%s)",
                                char_name, st_code, v_type, parent_asset_key, curr_char_token,
                            )
                        else:
                            # 发生跨角色资产张冠李戴污染，立即拦截纠偏
                            log.warning(
                                "【阶段 6 视图血缘·跨角色污染拦截】角色 [%s](token=%s) 阶段 %s 视图 %s 试图绑定异构父资产 [%s](parent_token=%s)，触发强制纠偏剔除！",
                                char_name, curr_char_token, st_code, v_type, candidate_parent, parent_char_token,
                            )

                    # 若未提供父级或因跨角色污染被剔除，基于 AssetProtocolHelper 进行同角色安全回退
                    if not parent_asset_key:
                        if v_type == "main_portrait":
                            # 二阶/三阶换装肖像回退到同角色 T1 主肖像
                            parent_asset_key = AssetProtocolHelper.build_character_asset_key(char_code, "T1", "main_portrait")
                        elif dep and dep.parent_asset_key:
                            parent_asset_key = dep.parent_asset_key
                        else:
                            parent_asset_key = AssetProtocolHelper.build_character_asset_key(char_code, st_code, "main_portrait")
                        log.debug(
                            "【阶段 6 视图血缘·安全回退生效】角色 [%s] 阶段 %s 视图 %s 自动回退为同角色标准底模: %s",
                            char_name, st_code, v_type, parent_asset_key,
                        )

                    gen_mode = v_info.get("generation_mode") or (dep.generation_mode if dep else "i2i")
                    if gen_mode == "t2i":
                        # 衍生视图与二阶/三阶换装肖像不可为纯文生图，修正为 i2i
                        gen_mode = "i2i" if (not dep or dep.generation_mode == "t2i") else dep.generation_mode

                    raw_denoise = v_info.get("denoise_strength")
                    if raw_denoise is None and dep:
                        raw_denoise = dep.denoise_strength
                    if raw_denoise is None or float(raw_denoise) == 0.0:
                        raw_denoise = 0.35 if v_type == "main_portrait" else 0.45
                    denoise_str = float(raw_denoise)

                ctrl_type = v_info.get("control_type") or (dep.control_type if dep else None)
                is_bench = 1 if (v_type == "main_portrait" and st_code in ("T1", "STAGE_1")) else 0

                raw_app = ent.get("appearance") or ""
                costume_desc = st_data.get("costume_description") or ""
                id_prompt = v_info.get("identity_prompt") or PromptSynthesizer.extract_identity_face_anchor(raw_app)
                delta_prompt = v_info.get("delta_prompt") or (f"{costume_desc}, {v_label}" if costume_desc else v_label)
                v_neg_prompt = v_info.get("negative_prompt") or PromptSynthesizer.get_negative_prompt("character")
                if v_info.get("image_prompt"):
                    v_prompt = str(v_info["image_prompt"])
                else:
                    syn = PromptSynthesizer.synthesize_character_view_prompt(
                        id_prompt,
                        view_type=v_type,
                        costume_prompt=costume_desc,
                    )
                    v_prompt = syn.visual_prompt
                    if not v_info.get("delta_prompt"):
                        delta_prompt = syn.delta_prompt

                v_info["parent_asset_key"] = parent_asset_key
                v_info["generation_mode"] = gen_mode
                v_info["denoise_strength"] = denoise_str
                v_info["control_type"] = ctrl_type
                v_info["is_benchmark"] = is_bench
                v_info["identity_prompt"] = id_prompt
                v_info["delta_prompt"] = delta_prompt
                v_info["negative_prompt"] = v_neg_prompt
                v_info["image_prompt"] = v_prompt
                v_info.setdefault("asset_keys", [])
                if cur_v_key not in v_info["asset_keys"]:
                    v_info["asset_keys"].append(cur_v_key)

                existing_view = fetch_one(
                    db,
                    """
                    SELECT id FROM character_stage_views
                    WHERE character_stage_id = :st_id AND view_type = :v_type
                    """,
                    {"st_id": stage_db_id, "v_type": v_type},
                )

                if existing_view:
                    view_db_id = existing_view["id"]
                    db.execute(
                        text("""
                            UPDATE character_stage_views
                            SET asset_key = CASE WHEN :asset_key IS NOT NULL AND :asset_key != '' THEN :asset_key ELSE asset_key END,
                                view_label = :view_label,
                                parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                                generation_mode = CASE WHEN :generation_mode IS NOT NULL AND :generation_mode != '' THEN :generation_mode ELSE generation_mode END,
                                denoise_strength = CASE WHEN :denoise_strength IS NOT NULL THEN :denoise_strength ELSE denoise_strength END,
                                control_type = CASE WHEN :control_type IS NOT NULL AND :control_type != '' THEN :control_type ELSE control_type END,
                                is_benchmark = CASE WHEN :is_benchmark = 1 THEN 1 ELSE is_benchmark END,
                                identity_prompt = CASE WHEN :identity_prompt != '' THEN :identity_prompt ELSE identity_prompt END,
                                delta_prompt = CASE WHEN :delta_prompt != '' THEN :delta_prompt ELSE delta_prompt END,
                                image_prompt = CASE WHEN :prompt != '' THEN :prompt ELSE image_prompt END,
                                negative_prompt = CASE WHEN :neg_prompt IS NOT NULL AND :neg_prompt != '' THEN :neg_prompt ELSE negative_prompt END,
                                image_url = CASE WHEN image_url IS NULL AND :image_url IS NOT NULL THEN :image_url ELSE image_url END,
                                local_path = CASE WHEN local_path IS NULL AND :local_path IS NOT NULL THEN :local_path ELSE local_path END,
                                seedance2_asset_id = CASE WHEN seedance2_asset_id IS NULL AND :seedance IS NOT NULL THEN :seedance ELSE seedance2_asset_id END,
                                is_primary = :is_primary,
                                updated_at = :now
                            WHERE id = :id
                        """),
                        {
                            "id": view_db_id,
                            "asset_key": cur_v_key,
                            "view_label": v_label,
                            "parent_asset_key": parent_asset_key,
                            "generation_mode": gen_mode,
                            "denoise_strength": denoise_str,
                            "control_type": ctrl_type,
                            "is_benchmark": is_bench,
                            "identity_prompt": id_prompt,
                            "delta_prompt": delta_prompt,
                            "prompt": v_prompt,
                            "neg_prompt": v_neg_prompt,
                            "image_url": v_url,
                            "local_path": v_local_path,
                            "seedance": v_seedance,
                            "is_primary": is_prim,
                            "now": now,
                        },
                    )
                else:
                    vw_ins = db.execute(
                        text("""
                            INSERT INTO character_stage_views (
                                character_stage_id, asset_key, view_type, view_label,
                                parent_asset_key, generation_mode, denoise_strength, control_type, is_benchmark,
                                identity_prompt, delta_prompt, image_prompt, negative_prompt,
                                image_url, local_path, seedance2_asset_id,
                                is_primary, created_at, updated_at
                            ) VALUES (
                                :st_id, :asset_key, :v_type, :view_label,
                                :parent_asset_key, :generation_mode, :denoise_strength, :control_type, :is_benchmark,
                                :identity_prompt, :delta_prompt, :prompt, :neg_prompt,
                                :image_url, :local_path, :seedance,
                                :is_primary, :now, :now
                            )
                        """),
                        {
                            "st_id": stage_db_id,
                            "asset_key": cur_v_key,
                            "v_type": v_type,
                            "view_label": v_label,
                            "parent_asset_key": parent_asset_key,
                            "generation_mode": gen_mode,
                            "denoise_strength": denoise_str,
                            "control_type": ctrl_type,
                            "is_benchmark": is_bench,
                            "identity_prompt": id_prompt,
                            "delta_prompt": delta_prompt,
                            "prompt": v_prompt,
                            "neg_prompt": v_neg_prompt,
                            "image_url": v_url,
                            "local_path": v_local_path,
                            "seedance": v_seedance,
                            "is_primary": is_prim,
                            "now": now,
                        },
                    )
                    view_db_id = getattr(vw_ins, "lastrowid", None) or 1
                    log.info(
                        "【阶段 6 落库】[Tier 3 角色切片视图] 写入形态切片: view_id=%s, stage_id=%s, view_type=%s, is_benchmark=%s, is_primary=%s",
                        view_db_id, stage_db_id, v_type, is_bench, is_prim,
                    )

                # 记录 asset_key 到实体/阶段/切片的元数据反向映射
                for ak in v_info.get("asset_keys", []):
                    if ak:
                        asset_character_meta_map[ak] = {
                            "character_id": char_id,
                            "character_name": char_name,
                            "character_stage_id": stage_db_id,
                            "stage_code": st_code,
                            "view_type": v_type,
                            "is_master_portrait": (is_prim == 1),
                        }

    # 二次遍历解析可能因先后次序未解析的 parent_stage_id（避免 MySQL 1093 同表更新子查询限制）
    for item in unresolved_stage_parents:
        s_code = item["stage_code"]
        p_ref = item["parent_ref"]
        p_row = fetch_one(
            db,
            """
            SELECT id FROM character_stages
            WHERE drama_id = :drama_id AND (stage_code = :p_ref OR stage_name = :p_ref)
            LIMIT 1
            """,
            {"drama_id": drama_id, "p_ref": p_ref},
        )
        if p_row and p_row.get("id"):
            db.execute(
                text("""
                    UPDATE character_stages
                    SET parent_stage_id = :parent_id
                    WHERE drama_id = :drama_id AND stage_code = :s_code AND (parent_stage_id IS NULL OR parent_stage_id = 0)
                """),
                {"drama_id": drama_id, "s_code": s_code, "parent_id": p_row["id"]},
            )
            log.debug("【阶段 6 落库】[DEBUG 角色造型二次解析] 关联 parent_stage_id: stage_code=%s, parent_ref=%s, parent_id=%s", s_code, p_ref, p_row["id"])

    # -------------------------------------------------------------------------
    # 3. 角色母音频卡片与专属音色配置同步 (character_voice_profiles 表)
    # -------------------------------------------------------------------------
    all_voice_entries: list[dict[str, Any]] = []

    # 3.1 聚合所有来源的既有音色资产 (显式入参 voice_cards + newly_generated_assets + reused_assets_data)
    for vc in voice_cards:
        d = _dump_or_dict(vc)
        if isinstance(d, dict):
            all_voice_entries.append(d)

    for item in newly_generated_assets:
        d = _dump_or_dict(item)
        if isinstance(d, dict):
            aid = str(d.get("asset_id") or d.get("asset_key") or "").upper()
            cat = str(d.get("type") or d.get("category") or "").lower()
            if aid.startswith("VOICE_") or cat in ("voice", "audio"):
                all_voice_entries.append(d)

    for item in reused_assets_data:
        d = _dump_or_dict(item)
        if isinstance(d, dict):
            aid = str(d.get("asset_id") or d.get("asset_key") or "").upper()
            cat = str(d.get("type") or d.get("category") or "").lower()
            if aid.startswith("VOICE_") or cat in ("voice", "audio"):
                all_voice_entries.append(d)

    # 3.2 识别并标记已覆盖音色卡的角色实体 (使用 find_canonical_entity 精确多维归属)
    covered_char_keys: set[str] = set()
    for v_entry in all_voice_entries:
        if not isinstance(v_entry, dict):
            continue
        v_name = str(v_entry.get("character_name") or v_entry.get("name") or "").strip()
        v_code = str(v_entry.get("character_code") or v_entry.get("character_id") or v_entry.get("char_id") or "").strip()
        vid = str(v_entry.get("master_voice_id") or v_entry.get("voice_id") or v_entry.get("asset_id") or "").strip()

        matched_ent = (
            find_canonical_entity(v_name, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(v_code, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(vid, canonical_map, canonical_by_name, canonical_by_code)
        )
        if matched_ent:
            covered_char_keys.add(matched_ent["char_name"].lower())
            covered_char_keys.add(matched_ent["char_code"].upper())
            # 回填标准规范角色名与角色代码，避免后续处理遗失
            v_entry.setdefault("character_name", matched_ent["char_name"])
            v_entry.setdefault("character_code", matched_ent["char_code"])
            log.debug(
                "【阶段 6 落库·音色实体映射】既有音色卡归属成功: 角色=%s (%s), voice_id=%s",
                matched_ent["char_name"], matched_ent["char_code"], vid,
            )

    # 3.3 全角色 100% 覆盖差集保底构建 (Full Character Voice Card Guarantee)
    # 核心目标：解决出场配角/小角色/未开口角色在主音色母卡抽取中被遗漏的问题
    missing_voice_characters: list[dict[str, Any]] = []
    for ent in canonical_map.values():
        c_name = ent["char_name"]
        c_code = ent["char_code"]
        if c_name.lower() not in covered_char_keys and c_code.upper() not in covered_char_keys:
            missing_voice_characters.append(ent)

    if missing_voice_characters:
        log.info(
            "【阶段 6 落库·全角色音色保底】发现 %d 位本集出场/建档角色缺失主音色母卡，开始全自动合成广播级 11 维母音卡...",
            len(missing_voice_characters),
        )
        default_emotion_rules_dict = {
            "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
            "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
            "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
            "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
            "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
            "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
        }
        for ent in missing_voice_characters:
            c_name = ent["char_name"]
            c_code = ent["char_code"]
            tok = AssetProtocolHelper.normalize_token(c_code or c_name)
            master_voice_id = f"VOICE_{tok}_T1_MASTER"
            timbre = ent.get("voice_style") or "中性沉稳自然原声"

            # 基于角色 11 维人设自动生成广播级 5 维 TTS 提示词
            char_acou = ent.get("acoustic_persona")
            if isinstance(char_acou, str) and char_acou.strip():
                try:
                    char_acou = json.loads(char_acou)
                except Exception:
                    char_acou = None

            synth_tts_prompt = synthesize_voice_prompt(
                char_name=c_name,
                gender=str(ent.get("gender") or "male"),
                perceived_age=str(ent.get("perceived_age") or "30岁"),
                role=str(ent.get("role") or "配角"),
                personality=str(ent.get("personality") or ""),
                timbre=timbre,
                voice_style=timbre,
                acoustic_persona=char_acou,
            )
            # 生成原型纯净示范台词
            sample_line = f"我是{c_name}。在这局棋盘上，没有人能置身事外。"

            synth_card = {
                "character_code": c_code,
                "character_name": c_name,
                "character_id": c_code,
                "master_voice_id": master_voice_id,
                "master_voice_key": master_voice_id,
                "timbre": timbre,
                "timbre_archetype": timbre or "沉稳磁性声线",
                "master_tts_prompt": synth_tts_prompt,
                "voice_prompt": synth_tts_prompt,
                "master_sample_text": sample_line,
                "script_monologue_source": sample_line,
                "speed_ratio": 1.0,
                "pitch_ratio": 1.0,
                "is_master_card": 1,
                "synthesis_status": "pending",
                "emotion_rules": default_emotion_rules_dict,
            }
            all_voice_entries.append(synth_card)
            log.info(
                "【阶段 6 落库·全角色音色保底】已为出场配角/未开口角色 [%s](%s) 合成母音卡: voice_id=%s, 音色=%s",
                c_name, c_code, master_voice_id, timbre,
            )

    log.info(
        "【阶段 6 落库·声音档案总计】本集待持久化音色卡总数=%d (出场角色总数=%d, 达到 100%% 覆盖)",
        len(all_voice_entries), len(canonical_map),
    )

    for v_entry in all_voice_entries:
        if not isinstance(v_entry, dict):
            continue
        raw_name = str(v_entry.get("character_name") or v_entry.get("name") or "").strip()
        v_name = clean_character_name(raw_name) or raw_name
        v_code = str(v_entry.get("character_code") or v_entry.get("char_id") or "").strip()
        voice_id_val = str(v_entry.get("master_voice_id") or v_entry.get("voice_id") or v_entry.get("asset_id") or "").strip()
        timbre = str(v_entry.get("timbre") or "").strip()
        v_prompt = str(v_entry.get("master_tts_prompt") or v_entry.get("voice_prompt") or v_entry.get("visual_grounding_quote") or v_entry.get("description") or "").strip()
        voice_file_path = str(v_entry.get("voice_file_path") or "").strip()

        # 查找对应角色自然人 ID 及文学实体配置
        target_char_id = None
        target_char_ent = (
            find_canonical_entity(v_code, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(v_name, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(voice_id_val, canonical_map, canonical_by_name, canonical_by_code)
        )

        # 1) 若从 canonical_map 内存中精确命中
        if target_char_ent:
            target_char_id = target_char_ent.get("db_id")
            if not v_name:
                v_name = target_char_ent["char_name"]
            if not v_code:
                v_code = target_char_ent["char_code"]
            log.debug(
                "【阶段 6 声音落库·内存命中】音色卡 [%s] 命中实体: 姓名=%s, ID=%s, 代号=%s",
                voice_id_val, v_name, target_char_id, v_code,
            )

        # 2) 若在 canonical_map 中未直接命中，从 DB 角色缓存或数据库实时查询
        if not target_char_id and (v_name or v_code):
            clean_v_name = clean_character_name(v_name)
            char_row = fetch_one(
                db,
                """
                SELECT id, name, character_code, gender, perceived_age, role, personality, appearance, voice_style, acoustic_persona
                FROM characters
                WHERE drama_id = :drama_id AND (
                    name = :name OR character_code = :code
                    OR name = :c_name OR character_code = :c_name
                )
                LIMIT 1
                """,
                {"drama_id": drama_id, "name": v_name, "code": v_code or v_name, "c_name": clean_v_name or v_name},
            )
            if char_row:
                target_char_id = char_row["id"]
                if not v_name:
                    v_name = char_row["name"]
                if not target_char_ent:
                    target_char_ent = dict(char_row)
                log.debug(
                    "【阶段 6 声音落库·DB实时命中】音色卡 [%s] 从DB命中实体: 姓名=%s, ID=%s",
                    voice_id_val, v_name, target_char_id,
                )

        # 3) 若音色 (timbre) 为空，尝试从关联角色中回填 voice_style
        if not timbre and target_char_ent:
            timbre = str(target_char_ent.get("voice_style") or "").strip()
        if not timbre:
            timbre = "中性沉稳自然原声"

        # 4) 生成或补全声音生成提示词 (voice_prompt / master_tts_prompt)
        # 若传入的提示词为空，或过短（缺乏具体参数），自动调用 synthesize_voice_prompt 生成 5 维广播级 TTS 提示词
        if not v_prompt or len(v_prompt) < 25 or "【" not in v_prompt:
            char_gender = target_char_ent.get("gender") if target_char_ent else "male"
            char_age = target_char_ent.get("perceived_age") if target_char_ent else "30岁"
            char_role = target_char_ent.get("role") if target_char_ent else "配角"
            char_pers = target_char_ent.get("personality") if target_char_ent else ""
            char_acou = target_char_ent.get("acoustic_persona") if target_char_ent else None
            if isinstance(char_acou, str) and char_acou.strip():
                try:
                    char_acou = json.loads(char_acou)
                except Exception:
                    char_acou = None

            synth_vp = synthesize_voice_prompt(
                char_name=v_name,
                gender=str(char_gender or "male"),
                perceived_age=str(char_age or "30岁"),
                role=str(char_role or "配角"),
                personality=str(char_pers or ""),
                timbre=timbre,
                voice_style=str(target_char_ent.get("voice_style") or "") if target_char_ent else "",
                acoustic_persona=char_acou,
            )
            if v_prompt and v_prompt != synth_vp:
                v_prompt = f"{synth_vp} 【台词语气参考】{v_prompt}"
            else:
                v_prompt = synth_vp

        # 5) 判断是否为全剧母音卡 (is_master_card: 1)
        if not voice_id_val:
            tok = AssetProtocolHelper.normalize_token(v_code or v_name)
            voice_id_val = f"VOICE_{tok}_T1_MASTER"

        master_voice_key = str(v_entry.get("master_voice_key") or v_entry.get("master_voice_id") or voice_id_val).strip()
        character_code_val = str(
            v_code
            or (target_char_ent.get("char_code") or target_char_ent.get("character_code") if target_char_ent else "")
            or f"CHAR_{AssetProtocolHelper.normalize_token(v_name)}"
        ).strip()

        raw_sample_text = str(
            v_entry.get("master_sample_text")
            or v_entry.get("script_monologue_source")
            or ""
        ).strip()
        # 剥离剧本舞台提示括号，保证 TTS 母音朗读样本绝对纯净
        clean_sample_text = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", raw_sample_text).strip()
        if not clean_sample_text:
            clean_sample_text = f"我是{v_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
        script_monologue_source = str(v_entry.get("script_monologue_source") or clean_sample_text).strip()

        timbre_archetype = str(v_entry.get("timbre_archetype") or timbre or "沉稳磁性声线").strip()
        vocal_position = str(v_entry.get("vocal_position") or "胸腔与口腔平衡共鸣").strip()
        vocal_flaws = str(v_entry.get("vocal_flaws") or "句尾带真实微弱换气呼吸音").strip()
        regional_accent = str(v_entry.get("regional_accent") or "").strip()
        acoustic_space = str(v_entry.get("acoustic_space") or "").strip()

        # 动态补充声学空间与方言特征到音色提示词中
        extra_acoustic: list[str] = []
        if regional_accent and regional_accent not in v_prompt:
            extra_acoustic.append(f"地域口音:{regional_accent}")
        if acoustic_space and acoustic_space not in v_prompt:
            extra_acoustic.append(f"声学空间:{acoustic_space}")
        if extra_acoustic:
            v_prompt = f"{v_prompt}，{'，'.join(extra_acoustic)}" if v_prompt else "，".join(extra_acoustic)

        log.debug(
            "【阶段 6 落库·高维声学合成】角色 [%s] 音色卡注入: regional_accent=%s, acoustic_space=%s -> prompt=%s",
            v_name, regional_accent, acoustic_space, v_prompt,
        )
        tts_provider = str(v_entry.get("tts_provider") or "minimax").strip()
        tts_model = str(v_entry.get("tts_model") or "speech-02-hd").strip()
        provider_voice_id = str(v_entry.get("provider_voice_id") or "male-qn-qingse").strip()

        raw_tw = v_entry.get("timber_weights") or v_entry.get("timber_weights_json")
        if isinstance(raw_tw, (list, dict)):
            timber_weights_json = json.dumps(raw_tw, ensure_ascii=False)
        elif isinstance(raw_tw, str) and raw_tw.strip():
            timber_weights_json = raw_tw.strip()
        else:
            timber_weights_json = json.dumps([{"voice_id": provider_voice_id, "weight": 100}], ensure_ascii=False)

        sample_audio_path = str(v_entry.get("sample_audio_path") or "").strip()
        sample_audio_url = str(v_entry.get("sample_audio_url") or v_entry.get("reference_audio_url") or "").strip()
        try:
            sample_duration_sec = float(v_entry.get("sample_duration_sec") or 0.0)
        except (ValueError, TypeError):
            sample_duration_sec = 0.0
        synthesis_status = str(v_entry.get("synthesis_status") or ("CERTIFIED" if sample_audio_url else "pending")).strip()
        semantic_hash_val = str(
            v_entry.get("semantic_hash")
            or hashlib.sha256(f"{master_voice_key}|{v_prompt}|{clean_sample_text}".encode("utf-8")).hexdigest()[:16]
        ).strip()

        is_master_card = 1 if (
            v_entry.get("is_master_card") in (1, True, "1", "true")
            or "master_voice_id" in v_entry
            or ("VOICE_" in voice_id_val and "_MASTER" in voice_id_val)
            or any(str(vc.get("master_voice_id") or vc.get("voice_id")) == voice_id_val for vc in voice_cards)
            or (target_char_id and not fetch_one(
                db,
                "SELECT 1 FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 1 AND deleted_at IS NULL",
                {"cid": target_char_id},
            ))
        ) else 0

        try:
            speed_ratio = float(v_entry.get("speed_ratio") or 1.0)
        except (ValueError, TypeError):
            speed_ratio = 1.0

        try:
            pitch_ratio = float(v_entry.get("pitch_ratio") or 1.0)
        except (ValueError, TypeError):
            pitch_ratio = 1.0

        raw_rules = v_entry.get("emotion_rules")
        if isinstance(raw_rules, (list, dict)):
            emotion_rules_json = json.dumps(raw_rules, ensure_ascii=False)
        elif raw_rules:
            emotion_rules_json = _ensure_valid_json_str(raw_rules, "{}", wrap_key="default")
        else:
            emotion_rules_json = json.dumps({
                "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
                "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
                "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
                "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
                "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
                "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
            }, ensure_ascii=False)

        # 检查是否已有声音档案: 优先按 voice_id / master_voice_key 精确匹配；若未匹配到则按 (character_id/name + is_master_card) 匹配
        existing_vp = None
        if voice_id_val:
            existing_vp = fetch_one(
                db,
                "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND (voice_id = :v_id OR master_voice_key = :m_key) AND deleted_at IS NULL",
                {"drama_id": drama_id, "v_id": voice_id_val, "m_key": master_voice_key},
            )
        if not existing_vp and is_master_card == 1:
            if target_char_id:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 1 AND deleted_at IS NULL",
                    {"cid": target_char_id},
                )
            if not existing_vp and v_name:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND character_name = :v_name AND is_master_card = 1 AND deleted_at IS NULL",
                    {"drama_id": drama_id, "v_name": v_name},
                )
        elif not existing_vp and is_master_card == 0 and not voice_id_val:
            if target_char_id:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 0 AND deleted_at IS NULL",
                    {"cid": target_char_id},
                )
            if not existing_vp and v_name:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND character_name = :v_name AND is_master_card = 0 AND deleted_at IS NULL",
                    {"drama_id": drama_id, "v_name": v_name},
                )

        if existing_vp:
            vp_id = existing_vp["id"]
            db.execute(
                text("""
                    UPDATE character_voice_profiles
                    SET character_id = COALESCE(:cid, character_id),
                        character_code = CASE WHEN :char_code != '' THEN :char_code ELSE character_code END,
                        character_name = CASE WHEN :v_name != '' THEN :v_name ELSE character_name END,
                        voice_id = CASE WHEN :v_id != '' THEN :v_id ELSE voice_id END,
                        master_voice_key = CASE WHEN :m_key != '' THEN :m_key ELSE master_voice_key END,
                        timbre = CASE WHEN :timbre != '' THEN :timbre ELSE timbre END,
                        timbre_archetype = CASE WHEN :timbre_archetype != '' THEN :timbre_archetype ELSE timbre_archetype END,
                        vocal_position = CASE WHEN :vocal_position != '' THEN :vocal_position ELSE vocal_position END,
                        vocal_flaws = CASE WHEN :vocal_flaws != '' THEN :vocal_flaws ELSE vocal_flaws END,
                        voice_prompt = CASE WHEN :v_prompt != '' THEN :v_prompt ELSE voice_prompt END,
                        master_tts_prompt = CASE WHEN :v_prompt != '' THEN :v_prompt ELSE master_tts_prompt END,
                        master_sample_text = CASE WHEN :sample_text != '' THEN :sample_text ELSE master_sample_text END,
                        script_monologue_source = CASE WHEN :mono_source != '' THEN :mono_source ELSE script_monologue_source END,
                        tts_provider = CASE WHEN :tts_provider != '' THEN :tts_provider ELSE tts_provider END,
                        tts_model = CASE WHEN :tts_model != '' THEN :tts_model ELSE tts_model END,
                        provider_voice_id = CASE WHEN :provider_voice_id != '' THEN :provider_voice_id ELSE provider_voice_id END,
                        timber_weights_json = CASE WHEN :timber_weights_json != '' THEN :timber_weights_json ELSE timber_weights_json END,
                        speed_ratio = :speed_ratio,
                        pitch_ratio = :pitch_ratio,
                        emotion_rules = CASE WHEN :emotion_rules != '[]' THEN :emotion_rules ELSE emotion_rules END,
                        is_master_card = CASE WHEN :is_master_card = 1 THEN 1 ELSE is_master_card END,
                        reference_audio_url = CASE WHEN :sample_audio_url != '' THEN :sample_audio_url ELSE reference_audio_url END,
                        sample_audio_path = CASE WHEN :sample_audio_path != '' THEN :sample_audio_path ELSE sample_audio_path END,
                        sample_audio_url = CASE WHEN :sample_audio_url != '' THEN :sample_audio_url ELSE sample_audio_url END,
                        sample_duration_sec = CASE WHEN :sample_duration_sec > 0 THEN :sample_duration_sec ELSE sample_duration_sec END,
                        synthesis_status = CASE WHEN :sample_audio_url != '' THEN 'CERTIFIED' ELSE COALESCE(synthesis_status, :synthesis_status) END,
                        semantic_hash = CASE WHEN :semantic_hash != '' THEN :semantic_hash ELSE semantic_hash END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": vp_id,
                    "cid": target_char_id,
                    "char_code": character_code_val,
                    "v_name": v_name,
                    "v_id": voice_id_val,
                    "m_key": master_voice_key,
                    "timbre": timbre,
                    "timbre_archetype": timbre_archetype,
                    "vocal_position": vocal_position,
                    "vocal_flaws": vocal_flaws,
                    "v_prompt": v_prompt,
                    "sample_text": clean_sample_text,
                    "mono_source": script_monologue_source,
                    "tts_provider": tts_provider,
                    "tts_model": tts_model,
                    "provider_voice_id": provider_voice_id,
                    "timber_weights_json": timber_weights_json,
                    "speed_ratio": speed_ratio,
                    "pitch_ratio": pitch_ratio,
                    "emotion_rules": emotion_rules_json,
                    "is_master_card": is_master_card,
                    "sample_audio_path": sample_audio_path,
                    "sample_audio_url": sample_audio_url,
                    "sample_duration_sec": sample_duration_sec,
                    "synthesis_status": synthesis_status,
                    "semantic_hash": semantic_hash_val,
                    "now": now,
                },
            )
            log.info(
                "【阶段 6 落库】[步骤 3/6 声音档案] 更新角色 [%s] V2 声音档案: profile_id=%s, master_voice_key=%s, 音色原型=%s, 状态=%s",
                v_name, vp_id, master_voice_key, timbre_archetype, synthesis_status,
            )
            log.debug(
                "【阶段 6 落库】[DEBUG 音色卡 V2] 更新详情: char_code=%s, provider=%s/%s(%s), 试音台词=%s",
                character_code_val, tts_provider, tts_model, provider_voice_id, clean_sample_text[:30],
            )
        else:
            ins_vp = db.execute(
                text("""
                    INSERT INTO character_voice_profiles (
                        character_id, drama_id, character_code, character_name,
                        voice_id, master_voice_key, voice_prompt, master_tts_prompt,
                        master_sample_text, script_monologue_source,
                        timbre, timbre_archetype, vocal_position, vocal_flaws,
                        tts_provider, tts_model, provider_voice_id, timber_weights_json,
                        speed_ratio, pitch_ratio, emotion_rules,
                        is_master_card, reference_audio_url,
                        sample_audio_path, sample_audio_url, sample_duration_sec,
                        synthesis_status, semantic_hash,
                        status, created_at, updated_at
                    ) VALUES (
                        :cid, :drama_id, :char_code, :v_name,
                        :v_id, :m_key, :v_prompt, :v_prompt,
                        :sample_text, :mono_source,
                        :timbre, :timbre_archetype, :vocal_position, :vocal_flaws,
                        :tts_provider, :tts_model, :provider_voice_id, :timber_weights_json,
                        :speed_ratio, :pitch_ratio, :emotion_rules,
                        :is_master_card, :sample_audio_url,
                        :sample_audio_path, :sample_audio_url, :sample_duration_sec,
                        :synthesis_status, :semantic_hash,
                        'active', :now, :now
                    )
                """),
                {
                    "cid": target_char_id,
                    "drama_id": drama_id,
                    "char_code": character_code_val,
                    "v_name": v_name,
                    "v_id": voice_id_val,
                    "m_key": master_voice_key,
                    "v_prompt": v_prompt,
                    "sample_text": clean_sample_text,
                    "mono_source": script_monologue_source,
                    "timbre": timbre,
                    "timbre_archetype": timbre_archetype,
                    "vocal_position": vocal_position,
                    "vocal_flaws": vocal_flaws,
                    "tts_provider": tts_provider,
                    "tts_model": tts_model,
                    "provider_voice_id": provider_voice_id,
                    "timber_weights_json": timber_weights_json,
                    "speed_ratio": speed_ratio,
                    "pitch_ratio": pitch_ratio,
                    "emotion_rules": emotion_rules_json,
                    "is_master_card": is_master_card,
                    "sample_audio_path": sample_audio_path,
                    "sample_audio_url": sample_audio_url,
                    "sample_duration_sec": sample_duration_sec,
                    "synthesis_status": synthesis_status,
                    "semantic_hash": semantic_hash_val,
                    "now": now,
                },
            )
            log.info(
                "【阶段 6 落库】[步骤 3/6 声音档案] 新增角色 [%s] V2 声音母卡入库: profile_id=%s, master_voice_key=%s, 音色原型=%s",
                v_name, getattr(ins_vp, "lastrowid", None), master_voice_key, timbre_archetype,
            )
            log.debug(
                "【阶段 6 落库】[DEBUG 音色卡 V2] 新增详情: char_code=%s, provider=%s/%s(%s), 试音台词=%s",
                character_code_val, tts_provider, tts_model, provider_voice_id, clean_sample_text[:30],
            )

        # 同时确保 characters 表中该角色的 voice_style 不为空
        if target_char_id and timbre:
            db.execute(
                text("""
                    UPDATE characters
                    SET voice_style = CASE WHEN voice_style IS NULL OR voice_style = '' THEN :timbre ELSE voice_style END,
                        updated_at = :now
                    WHERE id = :cid
                """),
                {"cid": target_char_id, "timbre": timbre, "now": now},
            )

    # -------------------------------------------------------------------------
    # 4. 空间场景与气候做旧层增量对齐 (scenes, scene_zones, scene_weathering_views)
    # -------------------------------------------------------------------------
    # 合并新发现场景项与新生成资产中的场景项
    for new_scene in newly_discovered_scenes:
        ns_dict = _dump_or_dict(new_scene)
        if isinstance(ns_dict, dict) and ns_dict not in environments_manifest:
            environments_manifest.append(ns_dict)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or "")
        if (cat in ("environment", "scene") or aid.startswith("ENV_")) and n_dict not in environments_manifest:
            environments_manifest.append(n_dict)

    # 【幂等防重保障·场景清单按业务主键去重收敛】
    # 避免上游多数据源导致同一场景以略有差异的字典重复加入 environments_manifest，引发单次落库中对同一场景的重复执行
    deduped_environments_manifest: list[dict[str, Any]] = []
    seen_env_keys: set[str] = set()
    for raw_env in environments_manifest:
        env_dict = _dump_or_dict(raw_env)
        if not isinstance(env_dict, dict):
            continue
        env_loc = str(env_dict.get("scene_name") or env_dict.get("location") or env_dict.get("location_name") or "").strip()
        env_code = str(env_dict.get("scene_code") or env_dict.get("code") or "").strip()
        env_ident = env_code if env_code else (AssetProtocolHelper.normalize_token(env_loc) if env_loc else "")
        if not env_ident and not env_loc:
            continue
        dedup_key = f"{env_ident}::{env_loc}"
        if dedup_key in seen_env_keys:
            log.debug("【阶段 6 落库】[场景去重过滤] 忽略重复的场景定义: %s", dedup_key)
            continue
        seen_env_keys.add(dedup_key)
        deduped_environments_manifest.append(env_dict)

    log.debug(
        "【阶段 6 落库】[场景清单前置收敛] 原始清单数=%d, 排重后有效场景数=%d",
        len(environments_manifest), len(deduped_environments_manifest)
    )

    for env in deduped_environments_manifest:
        loc = str(env.get("scene_name") or env.get("location") or env.get("location_name") or "").strip()
        if not loc:
            continue

        raw_s_code = str(env.get("scene_code") or env.get("code") or "").strip()
        s_code = raw_s_code if raw_s_code else AssetProtocolHelper.normalize_token(loc)
        bench_scene_key = env.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_scene(s_code)
        time_lighting = str(env.get("time_lighting") or env.get("time_and_lighting") or "").strip()
        acoustic_resistance = str(env.get("acoustic_resistance") or "").strip()

        existing_scene = fetch_one(
            db,
            "SELECT id FROM scenes WHERE drama_id = :drama_id AND (scene_code = :s_code OR location = :loc)",
            {"drama_id": drama_id, "s_code": s_code, "loc": loc},
        )
        if existing_scene:
            scene_id = existing_scene["id"]
            db.execute(
                text("""
                    UPDATE scenes
                    SET scene_code = CASE WHEN (scene_code IS NULL OR scene_code = '') AND :s_code != '' THEN :s_code ELSE scene_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        time = CASE WHEN :time != '' THEN :time ELSE time END,
                        prompt = CASE WHEN :prompt != '' THEN :prompt ELSE prompt END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": scene_id,
                    "s_code": s_code,
                    "bench_key": bench_scene_key,
                    "time": time_lighting,
                    "prompt": env.get("visual_prompt") or env.get("prompt") or "",
                    "now": now,
                },
            )
        else:
            scene_ins = db.execute(
                text("""
                    INSERT INTO scenes (
                        drama_id, episode_id, scene_code, benchmark_asset_key, location, time, prompt,
                        status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :episode_id, :scene_code, :benchmark_asset_key, :location, :time, :prompt,
                        'draft', :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "episode_id": episode_id,
                    "scene_code": s_code,
                    "benchmark_asset_key": bench_scene_key,
                    "location": loc,
                    "time": time_lighting,
                    "prompt": env.get("visual_prompt") or "",
                    "now": now,
                },
            )
            scene_id = getattr(scene_ins, "lastrowid", None) or 1
            log.info(
                "【阶段 6 落库】[步骤 4/6 场景] 登记第 %s 集新场景: scene_id=%s, 代号=%s, 地点=%s, 基准键=%s",
                curr_ep, scene_id, s_code, loc, bench_scene_key,
            )

        # 4.1 动态提取与规范化场景子空间区域 (Tier 2 scene_zones)
        zones_data: list[dict[str, Any]] = []
        raw_zones = env.get("zones") or env.get("sub_zones")
        if isinstance(raw_zones, list) and raw_zones:
            for z_idx, z_val in enumerate(raw_zones, start=1):
                if isinstance(z_val, dict):
                    z_code = str(z_val.get("zone_code") or (f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}")).strip().upper()
                    z_name = str(z_val.get("zone_name") or z_val.get("name") or f"{loc}子区域{z_idx}").strip()
                    z_tl = str(z_val.get("time_lighting") or time_lighting).strip()
                    z_ar = str(z_val.get("acoustic_resistance") or acoustic_resistance).strip()
                    zones_data.append({
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                    })
                elif isinstance(z_val, str) and z_val.strip():
                    z_name = z_val.strip()
                    z_code = f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}"
                    zones_data.append({
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": time_lighting,
                        "acoustic_resistance": acoustic_resistance,
                    })
        elif isinstance(raw_zones, dict):
            for z_idx, (z_k, z_v) in enumerate(raw_zones.items(), start=1):
                z_name = str(z_k).strip()
                z_code = f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}"
                zones_data.append({
                    "zone_code": z_code,
                    "zone_name": z_name,
                    "time_lighting": str(z_v).strip() if isinstance(z_v, str) else time_lighting,
                    "acoustic_resistance": acoustic_resistance,
                })

        # 若未提供显式子区域列表，优先提取 zone_name，兜底保持向后兼容（杜绝无条件写死）
        if not zones_data:
            dyn_z_name = str(env.get("zone_name") or "核心主活动区").strip()
            dyn_z_code = str(env.get("zone_code") or "Z01").strip().upper()
            zones_data.append({
                "zone_code": dyn_z_code,
                "zone_name": dyn_z_name,
                "time_lighting": time_lighting,
                "acoustic_resistance": acoustic_resistance,
            })

        primary_zone_id: Optional[int] = None
        for z_entry in zones_data:
            z_code = z_entry["zone_code"]
            z_name = z_entry["zone_name"]
            z_tl = z_entry["time_lighting"]
            z_ar = z_entry["acoustic_resistance"]

            existing_zone = fetch_one(
                db,
                "SELECT id, zone_code FROM scene_zones WHERE scene_id = :scene_id AND (zone_code = :z_code OR zone_name = :z_name)",
                {"scene_id": scene_id, "z_code": z_code, "z_name": z_name},
            )
            if existing_zone:
                zone_id = existing_zone["id"]
                db.execute(
                    text("""
                        UPDATE scene_zones
                        SET zone_code = CASE WHEN (zone_code IS NULL OR zone_code = '') AND :z_code != '' THEN :z_code ELSE zone_code END,
                            zone_name = CASE WHEN (zone_name IS NULL OR zone_name = '') AND :z_name != '' THEN :z_name ELSE zone_name END,
                            time_lighting = CASE WHEN :time_lighting != '' THEN :time_lighting ELSE time_lighting END,
                            acoustic_resistance = CASE WHEN :acoustic_resistance != '' THEN :acoustic_resistance ELSE acoustic_resistance END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": zone_id,
                        "z_code": z_code,
                        "z_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                        "now": now,
                    },
                )
            else:
                z_ins = db.execute(
                    text("""
                        INSERT INTO scene_zones (
                            scene_id, drama_id, zone_code, zone_name, time_lighting,
                            acoustic_resistance, created_at, updated_at
                        ) VALUES (
                            :scene_id, :drama_id, :zone_code, :zone_name, :time_lighting,
                            :acoustic_resistance, :now, :now
                        )
                    """),
                    {
                        "scene_id": scene_id,
                        "drama_id": drama_id,
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                        "now": now,
                    },
                )
                zone_id = getattr(z_ins, "lastrowid", None) or 1
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景子区域] 登记第 %s 集空间子区域: zone_id=%s, scene_id=%s, 代号=%s, 名称=%s",
                    curr_ep, zone_id, scene_id, z_code, z_name,
                )

            if primary_zone_id is None:
                primary_zone_id = zone_id

        target_zone_id = primary_zone_id or 1

        # ---------------------------------------------------------------------
        # 4.2 写入本集气候做旧图层 (Tier 3: scene_weathering_views)
        # ---------------------------------------------------------------------
        # 【架构设计说明·状态切片独立寻址与幂等槽位对齐】
        # 为彻底杜绝大模型重跑文字随机性导致的无休止追加插入（Append）与键碰撞：
        # 1. 优先提取上游阶段 3/6 规范化构建的结构化切片列表 `weathering_views`；
        # 2. 兜底兼容字典形式 `weathering_layers` 与列表形式 `weathering_applied`；
        # 3. 构造确定性切片槽位 asset_key：{bench_scene_key}_W{curr_ep}_S{idx}；
        # 4. 基于 (scene_zone_id, 本集切片模式) 执行槽位级精确对齐 (Slot Alignment)：
        #    - 匹配已存在的槽位进行原位更新 (UPDATE)；
        #    - 若本集切片数增加，执行新增插入 (INSERT)；
        #    - 若本集切片数收敛变少，自动清理多余的历史旧槽位 (DELETE)；
        #    - 从而保证多次重跑时记录数恒定，绝不膨胀。
        # ---------------------------------------------------------------------
        weathering_entries: list[dict[str, Any]] = []

        # 优先从结构化 weathering_views 中提取三层切片
        raw_views = env.get("weathering_views")
        if isinstance(raw_views, list) and raw_views:
            for v_idx, v_item in enumerate(raw_views, start=1):
                if isinstance(v_item, dict):
                    weathering_entries.append(v_item)
                elif isinstance(v_item, str) and v_item.strip():
                    weathering_entries.append({
                        "layer_type": f"weathering_s{v_idx}",
                        "description": v_item.strip(),
                    })
        else:
            # 兼容读取 weathering_applied 与 weathering_layers
            weathering_source = env.get("weathering_applied") or env.get("weathering_layers") or []
            if isinstance(weathering_source, dict):
                for k, v in weathering_source.items():
                    weathering_entries.append({
                        "layer_type": str(k).strip(),
                        "description": str(v).strip(),
                    })
            elif isinstance(weathering_source, list):
                for v_idx, item in enumerate(weathering_source, start=1):
                    if isinstance(item, dict):
                        weathering_entries.append(item)
                    elif isinstance(item, str) and item.strip():
                        weathering_entries.append({
                            "layer_type": f"weathering_s{v_idx}",
                            "description": item.strip(),
                        })
            elif isinstance(weathering_source, str) and weathering_source.strip():
                weathering_entries.append({
                    "layer_type": "weathering_s1",
                    "description": weathering_source.strip(),
                })

        # 过滤掉无有效描述的空项
        valid_entries: list[dict[str, Any]] = [
            e for e in weathering_entries
            if str(e.get("description") or e.get("desc") or "").strip()
        ]

        log.debug(
            "【阶段 6 落库】[DEBUG 场景做旧切片] 场景 [%s] (ID=%s, ZoneID=%s) 待落库做旧图层数: %d",
            loc, scene_id, target_zone_id, len(valid_entries)
        )

        # 4.2.1 查询当前主区域下属于本集的已有存量做旧切片 (按 id 升序)
        # 本集切片特征：asset_key 形如 '%_W{curr_ep}' 或 '%_W{curr_ep}_%'，或 layer_type 指向本集
        ep_key_pattern = f"%_W{curr_ep}"
        ep_key_sub_pattern = f"%_W{curr_ep}_%"
        existing_ep_views = fetch_all(
            db,
            """
            SELECT id, asset_key, layer_type, description
            FROM scene_weathering_views
            WHERE scene_zone_id = :z_id
              AND (
                  asset_key LIKE :p1
                  OR asset_key LIKE :p2
                  OR layer_type LIKE :p_layer
              )
            ORDER BY id ASC
            """,
            {
                "z_id": target_zone_id,
                "p1": ep_key_pattern,
                "p2": ep_key_sub_pattern,
                "p_layer": f"%ep_{curr_ep}%",
            },
        )
        existing_view_count = len(existing_ep_views)
        target_view_count = len(valid_entries)

        log.debug(
            "【阶段 6 落库】[场景做旧槽位对齐] zone_id=%s, 第 %s 集已存切片数=%d, 本次待同步切片数=%d",
            target_zone_id, curr_ep, existing_view_count, target_view_count
        )

        # 4.2.2 逐个槽位对齐与写入
        for s_idx, w_entry in enumerate(valid_entries, start=1):
            w_desc = str(w_entry.get("description") or w_entry.get("desc") or "").strip()
            raw_layer_type = str(w_entry.get("layer_type") or "").strip()
            layer_type = raw_layer_type if raw_layer_type else "episode_weathering"

            # 资产切片键（asset_key）构造策略：
            # 策略 A: 优先复用上游预先构建好的合规 asset_key
            # 策略 B: 若图层类型具备特定语义（如 structural / living / optical 等），拼装 bench_scene_key + layer_tok + 分集
            # 策略 C: 若为通用状态，拼装 bench_scene_key + _W{curr_ep}_S{s_idx} 保证严格唯一
            explicit_key = str(w_entry.get("asset_key") or "").strip()
            if explicit_key:
                w_asset_key = explicit_key
            else:
                has_semantic_layer = (
                    layer_type
                    and layer_type.lower() not in ("episode_weathering", "default")
                    and not layer_type.lower().startswith("weathering_s")
                )
                if has_semantic_layer:
                    layer_tok = AssetProtocolHelper.normalize_token(layer_type)
                    w_asset_key = f"{bench_scene_key}_{layer_tok}_W{curr_ep}"
                else:
                    w_asset_key = f"{bench_scene_key}_W{curr_ep}_S{s_idx}"

            w_parent_key = str(w_entry.get("parent_asset_key") or bench_scene_key).strip()
            w_gen_mode = str(w_entry.get("generation_mode") or "i2i").strip()
            w_denoise = float(w_entry.get("denoise_strength") or 0.45)

            # 提示词合成与负向提示词
            explicit_prompt = str(w_entry.get("visual_prompt") or w_entry.get("image_prompt") or "").strip()
            if explicit_prompt:
                w_full_prompt = explicit_prompt
            else:
                w_delta_prompt, w_full_prompt = PromptSynthesizer.synthesize_scene_view_prompt(
                    env.get("visual_prompt") or loc,
                    view_type="STATE",
                    weathering_prompt=w_desc,
                    atmosphere_prompt=time_lighting,
                )
            w_neg_prompt = PromptSynthesizer.get_negative_prompt("environment")

            # 槽位匹配：优先匹配存量列表中相同序号的槽位，或者按 asset_key / description 精确匹配
            matched_view = None
            if s_idx <= existing_view_count:
                matched_view = existing_ep_views[s_idx - 1]
            else:
                # 兜底通过 asset_key 或 description 匹配未在槽位列表中的记录
                matched_view = fetch_one(
                    db,
                    """
                    SELECT id, asset_key FROM scene_weathering_views
                    WHERE scene_zone_id = :z_id
                      AND (description = :desc OR (asset_key IS NOT NULL AND asset_key != '' AND asset_key = :asset_key))
                    """,
                    {"z_id": target_zone_id, "desc": w_desc, "asset_key": w_asset_key},
                )

            if matched_view:
                # 原位更新槽位数据，覆盖描述、提示词、更新时间等，防止重跑追加
                db.execute(
                    text("""
                        UPDATE scene_weathering_views
                        SET asset_key = :asset_key,
                            parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                            layer_type = :layer_type,
                            description = :description,
                            generation_mode = :gen_mode,
                            denoise_strength = CASE WHEN (denoise_strength IS NULL OR denoise_strength = 0) THEN :denoise ELSE denoise_strength END,
                            visual_prompt = :visual_prompt,
                            negative_prompt = CASE WHEN (negative_prompt IS NULL OR negative_prompt = '') THEN :negative_prompt ELSE negative_prompt END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": matched_view["id"],
                        "asset_key": w_asset_key,
                        "parent_asset_key": w_parent_key,
                        "layer_type": layer_type,
                        "description": w_desc,
                        "gen_mode": w_gen_mode,
                        "denoise": w_denoise,
                        "visual_prompt": w_full_prompt,
                        "negative_prompt": w_neg_prompt,
                        "now": now,
                    },
                )
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景做旧] 原位更新第 %s 集场景做旧槽位: view_id=%s, zone_id=%s, 槽位序号=%d, asset_key=%s, 描述=%s",
                    curr_ep, matched_view["id"], target_zone_id, s_idx, w_asset_key, w_desc[:25],
                )
            else:
                # 存量槽位不足，插入新增记录
                db.execute(
                    text("""
                        INSERT INTO scene_weathering_views (
                            scene_zone_id, layer_type, description,
                            asset_key, parent_asset_key, generation_mode, denoise_strength,
                            visual_prompt, negative_prompt, is_benchmark, is_primary,
                            is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :scene_zone_id, :layer_type, :description,
                            :asset_key, :parent_asset_key, :gen_mode, :denoise,
                            :visual_prompt, :negative_prompt, 0, 0,
                            1, :now, :now
                        )
                    """),
                    {
                        "scene_zone_id": target_zone_id,
                        "layer_type": layer_type,
                        "description": w_desc,
                        "asset_key": w_asset_key,
                        "parent_asset_key": w_parent_key,
                        "gen_mode": w_gen_mode,
                        "denoise": w_denoise,
                        "visual_prompt": w_full_prompt,
                        "negative_prompt": w_neg_prompt,
                        "now": now,
                    },
                )
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景做旧] 新增第 %s 集场景做旧切片: scene_id=%s, zone_id=%s, 槽位序号=%d, asset_key=%s, 描述=%s",
                    curr_ep, scene_id, target_zone_id, s_idx, w_asset_key, w_desc[:25],
                )

        # 4.2.3 清理多余的历史幽灵切片（若本次重跑产生的切片数少于已有切片数）
        if existing_view_count > target_view_count:
            surplus_views = existing_ep_views[target_view_count:]
            surplus_ids = [v["id"] for v in surplus_views]
            for s_id in surplus_ids:
                db.execute(
                    text("DELETE FROM scene_weathering_views WHERE id = :id"),
                    {"id": s_id},
                )
            log.info(
                "【阶段 6 落库】[步骤 4/6 场景做旧] 清理第 %s 集多余做旧切片 %d 条: zone_id=%s, 清理ID列表=%s",
                curr_ep, len(surplus_ids), target_zone_id, surplus_ids,
            )

    # -------------------------------------------------------------------------
    # 5. 核心道具资产与剧情损坏形态演进 (props, prop_damage_states)
    # -------------------------------------------------------------------------
    # 合并新发现道具项与新生成资产中的道具项
    for new_prop in newly_discovered_props:
        np_dict = _dump_or_dict(new_prop)
        if isinstance(np_dict, dict) and np_dict not in props_manifest:
            props_manifest.append(np_dict)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or "")
        if (cat == "prop" or aid.startswith("PROP_")) and n_dict not in props_manifest:
            props_manifest.append(n_dict)

    for prop_raw in props_manifest:
        prop = _dump_or_dict(prop_raw)
        if not isinstance(prop, dict):
            continue
        p_name = str(prop.get("prop_name") or prop.get("name") or "").strip()
        if not p_name:
            continue

        raw_p_code = str(prop.get("prop_code") or prop.get("code") or "").strip()
        p_code = raw_p_code if raw_p_code else AssetProtocolHelper.normalize_token(p_name)
        bench_prop_key = prop.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_prop(p_code)

        existing_prop = fetch_one(
            db,
            "SELECT id FROM props WHERE drama_id = :drama_id AND (prop_code = :p_code OR name = :name)",
            {"drama_id": drama_id, "p_code": p_code, "name": p_name},
        )
        if existing_prop:
            prop_id = existing_prop["id"]
            db.execute(
                text("""
                    UPDATE props
                    SET prop_code = CASE WHEN (prop_code IS NULL OR prop_code = '') AND :p_code != '' THEN :p_code ELSE prop_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        description = CASE WHEN :description != '' THEN :description ELSE description END,
                        prompt = CASE WHEN :prompt != '' THEN :prompt ELSE prompt END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": prop_id,
                    "p_code": p_code,
                    "bench_key": bench_prop_key,
                    "description": prop.get("description") or f"第{curr_ep}集关键叙事道具",
                    "prompt": prop.get("visual_prompt") or prop.get("prompt") or "",
                    "now": now,
                },
            )
        else:
            p_ins = db.execute(
                text("""
                    INSERT INTO props (
                        drama_id, prop_code, benchmark_asset_key, name, type, description, prompt, created_at, updated_at
                    ) VALUES (
                        :drama_id, :prop_code, :benchmark_asset_key, :name, :type, :description, :prompt, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "prop_code": p_code,
                    "benchmark_asset_key": bench_prop_key,
                    "name": p_name,
                    "type": prop.get("type", "narrative_reversal"),
                    "description": prop.get("description") or f"第{curr_ep}集关键叙事道具",
                    "prompt": prop.get("visual_prompt") or "",
                    "now": now,
                },
            )
            prop_id = getattr(p_ins, "lastrowid", None) or 1
            log.info(
                "【阶段 6 落库】[步骤 5/6 道具] 登记第 %s 集新道具: prop_id=%s, 代号=%s, 名称=%s, 基准键=%s",
                curr_ep, prop_id, p_code, p_name, bench_prop_key,
            )

        # 写入道具破坏与战损演进状态 (prop_damage_states)
        d_states: list[dict[str, Any]] = []
        raw_ds = prop.get("damage_states") or prop.get("damage_state_views")
        if raw_ds:
            if isinstance(raw_ds, list):
                for item in raw_ds:
                    if isinstance(item, dict):
                        d_states.append(item)
                    elif isinstance(item, str) and item.strip():
                        d_states.append({"state_label": item.strip()})
            elif isinstance(raw_ds, dict):
                for k, v in raw_ds.items():
                    d_states.append({"state_label": str(k), "narrative_point": str(v)})
            elif isinstance(raw_ds, str) and raw_ds.strip():
                d_states.append({"state_label": raw_ds.strip()})

        single_state = str(prop.get("damage_state") or prop.get("state_label") or "").strip()
        if single_state and not any(ds.get("state_label") == single_state for ds in d_states):
            d_states.append({
                "state_label": single_state,
                "damage_level": prop.get("damage_level", 1),
                "parent_state_id": prop.get("parent_state_id"),
                "parent_state_label": prop.get("parent_state_label"),
                "narrative_point": prop.get("narrative_point"),
                "visual_prompt": prop.get("visual_prompt"),
            })

        # 若未提供显式战损形态（例如初始完整物证），自动为其建立 S0 初始完整形态，确保 3 层体系完整闭环
        if not d_states:
            d_states.append({
                "state_code": "S0",
                "state_label": "初始完整形态",
                "damage_level": 0,
                "narrative_point": prop.get("description") or f"第{curr_ep}集初始物证形态",
                "visual_prompt": prop.get("visual_prompt"),
            })

        prev_ds_id = 0
        for s_idx, ds_item in enumerate(d_states):
            s_label = str(ds_item.get("state_label") or "").strip()
            if not s_label or not prop_id:
                continue

            has_explicit_code = bool(ds_item.get("state_code"))
            if has_explicit_code:
                state_code = str(ds_item.get("state_code")).strip().upper()
                if state_code.isdigit():
                    state_code = f"S{state_code}"
            else:
                c_row = fetch_one(db, "SELECT count(id) as cnt FROM prop_damage_states WHERE prop_id = :prop_id", {"prop_id": prop_id})
                c_cnt = int(c_row.get("cnt", 0)) if c_row else s_idx
                state_code = f"S{c_cnt}"

            parent_state_ref = ds_item.get("parent_state_id") or ds_item.get("parent_state_label") or ""
            parent_state_id = 0
            if isinstance(parent_state_ref, int):
                parent_state_id = parent_state_ref
            elif isinstance(parent_state_ref, str) and parent_state_ref.strip():
                p_label = parent_state_ref.strip()
                parent_pds_row = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND (state_label = :p_label OR state_code = :p_label)",
                    {"prop_id": prop_id, "p_label": p_label},
                )
                if parent_pds_row:
                    parent_state_id = parent_pds_row["id"]
                    log.debug("【阶段 6 落库】[DEBUG 道具状态] 成功解析父级战损形态 ID: prop_id=%s, state_label=%s -> parent_state_id=%s", prop_id, s_label, parent_state_id)

            # 若未显式指定父级形态且非首个形态，自动绑定上一损伤形态作为演进母本
            if parent_state_id == 0:
                if prev_ds_id > 0:
                    parent_state_id = prev_ds_id
                else:
                    raw_cur_lvl = ds_item.get("damage_level", 0)
                    try:
                        cur_lvl = int(raw_cur_lvl)
                    except (ValueError, TypeError):
                        cur_lvl = 0
                    if cur_lvl > 0:
                        prev_row = fetch_one(
                            db,
                            "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND damage_level < :cur_lvl ORDER BY damage_level DESC, id DESC LIMIT 1",
                            {"prop_id": prop_id, "cur_lvl": cur_lvl},
                        )
                        if prev_row:
                            parent_state_id = prev_row["id"]

            p_id_prompt = PromptSynthesizer.extract_identity_face_anchor(prop.get("visual_prompt") or p_name)
            p_delta_prompt = f"damage state: {s_label}, level: {ds_item.get('damage_level', 1)}"
            p_neg_prompt = PromptSynthesizer.get_negative_prompt("prop")
            p_synth = PromptSynthesizer.synthesize_prop_view_prompt(p_id_prompt, view_type="STATIC", state_prompt=p_delta_prompt)
            p_full_prompt = p_synth.visual_prompt

            if has_explicit_code:
                existing_ds = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND (state_label = :s_label OR state_code = :s_code)",
                    {"prop_id": prop_id, "s_label": s_label, "s_code": state_code},
                )
            else:
                existing_ds = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND state_label = :s_label",
                    {"prop_id": prop_id, "s_label": s_label},
                )
            raw_d_level = ds_item.get("damage_level", prop.get("damage_level", 1))
            try:
                damage_level = int(raw_d_level)
            except (ValueError, TypeError):
                damage_level = 1

            narrative_point = str(ds_item.get("narrative_point") or prop.get("narrative_point") or f"第{curr_ep}集剧情触发物证形态演进: {s_label}")
            visual_prompt = str(ds_item.get("visual_prompt") or prop.get("visual_prompt") or p_full_prompt)

            if existing_ds:
                db.execute(
                    text("""
                        UPDATE prop_damage_states
                        SET state_code = CASE WHEN (state_code IS NULL OR state_code = '') THEN :state_code ELSE state_code END,
                            parent_state_id = CASE WHEN (parent_state_id IS NULL OR parent_state_id = 0) AND :parent_state_id > 0 THEN :parent_state_id ELSE parent_state_id END,
                            damage_level = :damage_level,
                            narrative_point = :narrative_point,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_ds["id"],
                        "state_code": state_code,
                        "parent_state_id": parent_state_id,
                        "damage_level": damage_level,
                        "narrative_point": narrative_point,
                        "now": now,
                    },
                )
                ds_id = existing_ds["id"]
            else:
                ins_ds = db.execute(
                    text("""
                        INSERT INTO prop_damage_states (
                            prop_id, drama_id, state_code, state_label, damage_level,
                            narrative_point, parent_state_id, created_at, updated_at
                        ) VALUES (
                            :prop_id, :drama_id, :state_code, :state_label, :damage_level,
                            :narrative_point, :parent_state_id, :now, :now
                        )
                    """),
                    {
                        "prop_id": prop_id,
                        "drama_id": drama_id,
                        "state_code": state_code,
                        "state_label": s_label,
                        "damage_level": damage_level,
                        "narrative_point": narrative_point,
                        "parent_state_id": parent_state_id,
                        "now": now,
                    },
                )
                ds_id = getattr(ins_ds, "lastrowid", None) or 1

            prev_ds_id = ds_id

            macro_asset_key = f"{bench_prop_key}_{state_code}_DETAIL"
            macro_delta = f"macro close-up feature of {s_label}"
            
            # 兼容从上游 manifest 传入的自定义 detail_views 特写描述
            custom_detail_desc = ""
            raw_dvs = ds_item.get("detail_views") or prop.get("detail_views") or []
            if isinstance(raw_dvs, list):
                for dv_item in raw_dvs:
                    if isinstance(dv_item, dict):
                        custom_detail_desc = dv_item.get("visual_prompt") or dv_item.get("description") or ""
                        if custom_detail_desc:
                            break
                    elif isinstance(dv_item, str) and dv_item.strip():
                        custom_detail_desc = dv_item.strip()
                        break
            if custom_detail_desc:
                macro_delta = f"{macro_delta}, {custom_detail_desc}"

            macro_synth = PromptSynthesizer.synthesize_prop_view_prompt(p_id_prompt, view_type="DETAIL", state_prompt=macro_delta)
            macro_prompt_str = macro_synth.visual_prompt

            existing_dv = fetch_one(
                db,
                "SELECT id FROM prop_detail_views WHERE damage_state_id = :ds_id AND view_type = 'macro_feature'",
                {"ds_id": ds_id},
            )
            if existing_dv:
                db.execute(
                    text("""
                        UPDATE prop_detail_views
                        SET asset_key = CASE WHEN (asset_key IS NULL OR asset_key = '') THEN :asset_key ELSE asset_key END,
                            parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                            generation_mode = CASE WHEN (generation_mode IS NULL OR generation_mode = '' OR generation_mode = 't2i') THEN 'crop_macro' ELSE generation_mode END,
                            denoise_strength = CASE WHEN (denoise_strength IS NULL OR denoise_strength = 0) THEN 0.45 ELSE denoise_strength END,
                            visual_prompt = CASE WHEN :visual_prompt != '' THEN :visual_prompt ELSE visual_prompt END,
                            negative_prompt = CASE WHEN :negative_prompt != '' THEN :negative_prompt ELSE negative_prompt END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_dv["id"],
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_prompt_str,
                        "negative_prompt": p_neg_prompt,
                        "now": now,
                    },
                )
            else:
                db.execute(
                    text("""
                        INSERT INTO prop_detail_views (
                            damage_state_id, asset_key, view_type,
                            parent_asset_key, generation_mode, denoise_strength,
                            visual_prompt, negative_prompt,
                            is_benchmark, is_primary, is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :damage_state_id, :asset_key, 'macro_feature',
                            :parent_asset_key, 'crop_macro', 0.45,
                            :visual_prompt, :negative_prompt,
                            0, 1, 1, :now, :now
                        )
                    """),
                    {
                        "damage_state_id": ds_id,
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_prompt_str,
                        "negative_prompt": p_neg_prompt,
                        "now": now,
                    },
                )
            log.info(
                "【阶段 6 落库】[步骤 5/6 道具形态] 记录道具 [%s] 战损演进状态: 形态=%s(%s), 父基准键=%s, 剧集=%s",
                p_name, s_label, state_code, bench_prop_key, curr_ep,
            )

    # 二次遍历解析可能因先后次序未解析的 parent_state_id
    for prop_raw in props_manifest:
        prop = _dump_or_dict(prop_raw)
        if not isinstance(prop, dict):
            continue
        p_name = str(prop.get("prop_name") or prop.get("name") or "").strip()
        p_row = fetch_one(db, "SELECT id FROM props WHERE drama_id = :drama_id AND name = :name", {"drama_id": drama_id, "name": p_name})
        if not p_row:
            continue
        pid = p_row["id"]
        raw_ds = prop.get("damage_states") or prop.get("damage_state_views") or []
        if isinstance(raw_ds, dict):
            raw_ds = [{"state_label": k, "narrative_point": v} for k, v in raw_ds.items()]
        elif not isinstance(raw_ds, list):
            raw_ds = []
        if prop.get("damage_state") or prop.get("parent_state_label"):
            raw_ds.append(prop)
        for ds_it in raw_ds:
            if not isinstance(ds_it, dict):
                continue
            s_lbl = str(ds_it.get("state_label") or ds_it.get("damage_state") or "").strip()
            p_lbl = str(ds_it.get("parent_state_label") or "").strip()
            if s_lbl and p_lbl:
                p_ds_row = fetch_one(
                    db,
                    """
                    SELECT id FROM prop_damage_states
                    WHERE prop_id = :pid AND state_label = :p_lbl
                    LIMIT 1
                    """,
                    {"pid": pid, "p_lbl": p_lbl},
                )
                if p_ds_row and p_ds_row.get("id"):
                    db.execute(
                        text("""
                            UPDATE prop_damage_states
                            SET parent_state_id = :parent_id
                            WHERE prop_id = :pid AND state_label = :s_lbl AND (parent_state_id IS NULL OR parent_state_id = 0)
                        """),
                        {"pid": pid, "s_lbl": s_lbl, "parent_id": p_ds_row["id"]},
                    )
                    log.debug("【阶段 6 落库】[DEBUG 道具状态二次解析] 关联 parent_state_id: prop_id=%s, state_label=%s, parent_label=%s, parent_id=%s", pid, s_lbl, p_lbl, p_ds_row["id"])

    # -------------------------------------------------------------------------
    # 5.5 统管媒体素材库原子落库 (assets 表全字段写入与元数据关联)
    # -------------------------------------------------------------------------
    log.info("【阶段 6 落库】[步骤 5.5/6 统管素材] 开始将多模态资产与母音卡写入 assets 统管表...")
    all_raw_assets_to_persist: list[dict[str, Any]] = []

    # 1. 收集新生成的多模态视听资产
    for na in newly_generated_assets:
        nad = _dump_or_dict(na)
        if isinstance(nad, dict):
            all_raw_assets_to_persist.append(nad)

    # 2. 收集角色母音卡作为音频资产
    for vc in voice_cards:
        vcd = _dump_or_dict(vc)
        if isinstance(vcd, dict):
            v_key = str(vcd.get("master_voice_id") or vcd.get("voice_id") or "").strip()
            if v_key and not any(str(a.get("asset_id") or a.get("asset_key")) == v_key for a in all_raw_assets_to_persist):
                all_raw_assets_to_persist.append({
                    "asset_id": v_key,
                    "asset_key": v_key,
                    "name": str(vcd.get("character_name") or "") + "母音卡",
                    "category": "voice",
                    "type": "audio",
                    "prompt": str(vcd.get("master_tts_prompt") or vcd.get("voice_prompt") or ""),
                    "negative_prompt": "",
                    "timbre": vcd.get("timbre"),
                    "speed_ratio": vcd.get("speed_ratio", 1.0),
                    "pitch_ratio": vcd.get("pitch_ratio", 1.0),
                    "semantic_hash": vcd.get("semantic_hash"),
                    "voice_file_path": vcd.get("voice_file_path"),
                    "character_id": vcd.get("character_id"),
                    "character_name": vcd.get("character_name"),
                    "is_master_card": 1,
                    "lifecycle_status": vcd.get("lifecycle_status", "READY"),
                })

    for a_item in all_raw_assets_to_persist:
        asset_key = str(a_item.get("asset_key") or a_item.get("asset_id") or "").strip()
        if not asset_key:
            continue

        a_name = str(a_item.get("name") or a_item.get("asset_name") or asset_key).strip()
        cat = str(a_item.get("category") or "").lower()
        if not cat:
            if asset_key.startswith("CHAR_"):
                cat = "character"
            elif asset_key.startswith("ENV_"):
                cat = "environment"
            elif asset_key.startswith("PROP_"):
                cat = "prop"
            elif asset_key.startswith("VOICE_"):
                cat = "voice"
            else:
                cat = "misc"

        a_type = str(a_item.get("type") or "").lower()
        if not a_type:
            a_type = "audio" if (cat == "voice" or asset_key.startswith("VOICE_")) else "image"

        prompt = str(a_item.get("prompt") or a_item.get("visual_prompt") or a_item.get("master_tts_prompt") or "").strip()
        neg_prompt = str(a_item.get("negative_prompt") or "").strip()

        # 构造 params 参数 JSON
        params_dict: dict[str, Any] = {}
        for pk in (
            "generation_method", "aspect_ratio", "input_source_image",
            "denoising_strength", "semantic_hash", "timbre",
            "speed_ratio", "pitch_ratio", "seed", "steps", "cfg_scale", "lora"
        ):
            if pk in a_item and a_item[pk] is not None:
                params_dict[pk] = a_item[pk]

        # 若 lineage_dag 中存在该资产的父级底图，且当前没有 input_source_image，则自动补齐
        if "input_source_image" not in params_dict and asset_key in lineage_dag_data:
            params_dict["input_source_image"] = lineage_dag_data[asset_key]

        # 构造 metadata 元数据 JSON
        meta_dict: dict[str, Any] = {}
        parent_id = a_item.get("parent_asset_id") or lineage_dag_data.get(asset_key) or params_dict.get("input_source_image")
        if parent_id:
            meta_dict["parent_asset_id"] = parent_id
        meta_dict["episode_num"] = curr_ep
        meta_dict["lifecycle_status"] = a_item.get("lifecycle_status", "READY")
        for mk in ("character_id", "character_name", "is_master_card", "voice_file_path", "stage_code", "damage_state"):
            if mk in a_item and a_item[mk] is not None:
                meta_dict[mk] = a_item[mk]

        # 角色领域三层模型反向回溯挂载 (注入 character_id, character_stage_id, view_type, is_master_portrait)
        if asset_key in asset_character_meta_map:
            for ak_k, ak_v in asset_character_meta_map[asset_key].items():
                meta_dict[ak_k] = ak_v
        elif cat == "character" or asset_key.startswith("CHAR_"):
            cand_p_code, cand_st_code, cand_v_tok = extract_character_tokens(asset_key)
            clean_aname = clean_character_name(a_name)
            matched_ent = canonical_map.get(clean_aname.lower())
            if matched_ent:
                meta_dict["character_id"] = matched_ent.get("db_id")
                meta_dict["character_name"] = matched_ent.get("char_name")
                st_key = cand_st_code or "T1"
                if st_key in stage_db_ids_by_code:
                    meta_dict["character_stage_id"] = stage_db_ids_by_code[st_key]
                    meta_dict["stage_code"] = st_key
                v_type, _, is_prim = parse_character_view_type(cand_v_tok, a_name)
                meta_dict["view_type"] = v_type
                meta_dict["is_master_portrait"] = (is_prim == 1)

        # 提取 DAG 关系与四维提示词元数据 (全系统防退化总关口)
        dep_rule = AssetProtocolHelper.get_dependency_rule(asset_key)
        rule_mode = (dep_rule.get("generation_mode") if isinstance(dep_rule, dict) else getattr(dep_rule, "generation_mode", "t2i")) or "t2i"
        rule_parent = (dep_rule.get("parent_asset_id") if isinstance(dep_rule, dict) else (getattr(dep_rule, "parent_asset_id", None) or getattr(dep_rule, "parent_asset_key", None)))
        rule_denoise = (dep_rule.get("recommended_denoise") if isinstance(dep_rule, dict) else getattr(dep_rule, "recommended_denoise", 0.45))

        a_parent_key = a_item.get("parent_asset_key") or a_item.get("parent_asset_id") or rule_parent
        a_gen_mode = a_item.get("generation_mode") or rule_mode

        if rule_mode != "t2i":
            # 非一阶根节点资产：严禁退化为文生图 t2i，且严禁父级引用丢失
            if a_gen_mode == "t2i":
                log.warning("【阶段 6 落库·防退化拦截】资产 [%s] (预期模式=%s) 企图以 t2i 落库，强制纠偏为 %s", asset_key, rule_mode, rule_mode)
                a_gen_mode = rule_mode
            if not a_parent_key:
                a_parent_key = rule_parent
                log.warning("【阶段 6 落库·孤儿资产救援】资产 [%s] (mode=%s) 缺少父级引用，自动挂载至标准根基准 [%s]", asset_key, a_gen_mode, a_parent_key)
            a_is_bench = 0
            raw_denoise = a_item.get("denoise_strength")
            try:
                if raw_denoise is None or float(raw_denoise) == 0.0:
                    a_denoise_flt = float(rule_denoise if rule_denoise is not None else 0.45)
                else:
                    a_denoise_flt = float(raw_denoise)
            except (ValueError, TypeError):
                a_denoise_flt = 0.45
        else:
            # 真正的一阶基准根节点 (T1 / Z01 / S0)
            a_gen_mode = "t2i"
            a_parent_key = None
            a_is_bench = 1
            a_denoise_flt = 0.0

        a_ctrl_type = a_item.get("control_type") or (
            dep_rule.get("control_type") if isinstance(dep_rule, dict) else getattr(dep_rule, "control_type", None)
        )

        a_id_prompt = a_item.get("identity_prompt") or PromptSynthesizer.extract_identity_face_anchor(prompt or a_name)
        a_delta_prompt = a_item.get("delta_prompt") or (prompt if prompt != a_id_prompt else "")
        if not neg_prompt:
            neg_prompt = PromptSynthesizer.get_negative_prompt(cat)

        existing_asset = fetch_one(
            db,
            "SELECT id FROM assets WHERE drama_id = :drama_id AND asset_key = :asset_key",
            {"drama_id": drama_id, "asset_key": asset_key},
        )
        if existing_asset:
            db.execute(
                text("""
                    UPDATE assets
                    SET name = :name,
                        type = :type,
                        category = :category,
                        parent_asset_id = :parent_asset_id,
                        generation_mode = :generation_mode,
                        denoise_strength = :denoise_strength,
                        is_benchmark = :is_benchmark,
                        prompt = :prompt,
                        negative_prompt = :negative_prompt,
                        params = :params,
                        metadata = :metadata,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": existing_asset["id"],
                    "name": a_name,
                    "type": a_type,
                    "category": cat,
                    "parent_asset_id": a_parent_key,
                    "generation_mode": a_gen_mode,
                    "denoise_strength": a_denoise_flt,
                    "is_benchmark": a_is_bench,
                    "prompt": prompt,
                    "negative_prompt": neg_prompt,
                    "params": json.dumps(params_dict, ensure_ascii=False),
                    "metadata": json.dumps(meta_dict, ensure_ascii=False),
                    "now": now,
                },
            )
            log.debug("【阶段 6 落库】[DEBUG 统管素材] 更新已有资产: asset_key=%s, id=%s", asset_key, existing_asset["id"])
        else:
            ins_a = db.execute(
                text("""
                    INSERT INTO assets (
                        drama_id, asset_key, name, type, category,
                        parent_asset_id, generation_mode, denoise_strength, is_benchmark,
                        prompt, negative_prompt,
                        params, metadata, created_at, updated_at
                    ) VALUES (
                        :drama_id, :asset_key, :name, :type, :category,
                        :parent_asset_id, :generation_mode, :denoise_strength, :is_benchmark,
                        :prompt, :negative_prompt,
                        :params, :metadata, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "asset_key": asset_key,
                    "name": a_name,
                    "type": a_type,
                    "category": cat,
                    "parent_asset_id": a_parent_key,
                    "generation_mode": a_gen_mode,
                    "denoise_strength": a_denoise_flt,
                    "is_benchmark": a_is_bench,
                    "prompt": prompt,
                    "negative_prompt": neg_prompt,
                    "params": json.dumps(params_dict, ensure_ascii=False),
                    "metadata": json.dumps(meta_dict, ensure_ascii=False),
                    "now": now,
                },
            )
            log.info("【阶段 6 落库】[步骤 5.5/6 统管素材] 新增资产成功入库: asset_key=%s, id=%s, is_benchmark=%s", asset_key, getattr(ins_a, "lastrowid", None), a_is_bench)

    # 步骤 5.6: 自动同步本集增量资产到专属向量集合 lmd_assets_drama_{drama_id}
    try:
        synced_count = vector_memory_service.sync_assets_to_vector_db(
            drama_id=drama_id,
            assets=all_raw_assets_to_persist,
        )
        log.info("【阶段 6 落库】[步骤 5.6 向量同步] 增量资产已成功同步至向量库专属集合: %d 项", synced_count)
    except Exception as v_err:
        log.warning("【阶段 6 落库】资产向量集合同步异常 (容灾降级，不阻断主事务): %s", v_err)

    # -------------------------------------------------------------------------
    # 6. 长期记忆自动入库与向量化
    # -------------------------------------------------------------------------
    chars_summary = manifest_dict.get("characters_in_scene") or manifest_dict.get("characters") or []
    scenes_summary = manifest_dict.get("scenes_in_use") or manifest_dict.get("environments") or []
    props_summary = manifest_dict.get("props_in_use") or manifest_dict.get("props") or []
    stage6_memories = [
        {
            "title": f"第{curr_ep}集视听资源清单与登场资产",
            "content": f"第{curr_ep}集多模态引单:\n登场角色变体: {json.dumps(chars_summary, ensure_ascii=False)}\n发生场景与做旧层: {json.dumps(scenes_summary, ensure_ascii=False)}\n关键叙事道具: {json.dumps(props_summary, ensure_ascii=False)}",
            "summary": f"第{curr_ep}集视听资源引单",
            "keywords": [f"第{curr_ep}集", "视听资源引单", "资产校验"],
            "memory_type": "visual_manifest",
            "source_type": "stage6_manifest",
            "source_id": f"ep_manifest_{curr_ep}",
        }
    ]
    try:
        sync_stage_memories_to_vector_db(db, drama_id, 6, stage6_memories)
        log.info("【阶段 6 落库】向量数据库同步成功完成")
    except Exception as e:
        log.warning("【阶段 6 落库】向量数据库同步出现非阻塞异常 (已隔离保护): %s", e)

    # -------------------------------------------------------------------------
    # 7. 全局资产注册表更新与短剧阶段跃迁
    # -------------------------------------------------------------------------
    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    if getattr(state, "visual_audio_assets_registry", None):
        current_meta["visual_audio_assets_registry"] = _dump_or_dict(state.visual_audio_assets_registry)
    elif isinstance(state, dict) and state.get("visual_audio_assets_registry"):
        current_meta["visual_audio_assets_registry"] = _dump_or_dict(state["visual_audio_assets_registry"])

    # 聚合全局 asset_lineage_dag
    existing_lineage_dag = current_meta.get("asset_lineage_dag") or {}
    if not isinstance(existing_lineage_dag, dict):
        existing_lineage_dag = {}
    if lineage_dag_data and isinstance(lineage_dag_data, dict):
        existing_lineage_dag.update(lineage_dag_data)
    current_meta["asset_lineage_dag"] = existing_lineage_dag
    log.debug("【阶段 6 落库】[DEBUG 全局元数据] asset_lineage_dag 合并后项数: %d", len(existing_lineage_dag))

    # 同步本集新入册角色的 11 维档案至 dramas.metadata["character_tokens"]，确保跨集长线一致
    existing_char_tokens = current_meta.get("character_tokens") or []
    if not isinstance(existing_char_tokens, list):
        existing_char_tokens = []
    known_token_codes = {
        str(ct.get("character_code") or ct.get("char_id") or "").strip()
        for ct in existing_char_tokens if isinstance(ct, dict)
    }
    known_token_names = {
        clean_character_name(str(ct.get("name") or ct.get("character_name") or ""))
        for ct in existing_char_tokens if isinstance(ct, dict)
    }
    for ndc in newly_discovered_characters:
        ndc_dict = _dump_or_dict(ndc)
        if not isinstance(ndc_dict, dict):
            continue
        ndc_code = str(ndc_dict.get("character_code") or "").strip()
        ndc_name = clean_character_name(str(ndc_dict.get("name") or ndc_dict.get("character_name") or ""))
        if ndc_code and ndc_code not in known_token_codes and ndc_name not in known_token_names:
            existing_char_tokens.append(ndc_dict)
            known_token_codes.add(ndc_code)
            if ndc_name:
                known_token_names.add(ndc_name)
            log.debug("【阶段 6 落库】[DEBUG 全局角色同步] 已将阶段 6 补建角色 [%s(%s)] 合并至 dramas.metadata.character_tokens", ndc_name, ndc_code)
    current_meta["character_tokens"] = existing_char_tokens

    db.execute(
        text("UPDATE dramas SET current_stage = 6, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 6, state.latest_audit)

    db.commit()
    log.info("【阶段 6 落库】短剧 [%s] 第 %s 集全部资产与关系表持久化完成并已提交事务。", drama_id, curr_ep)


# =========================================================================
# 阶段 7：单帧分镜提示词、运镜与精准 SRT 轴测持久化（含三表联动与 Stage 6 资产映射）
# =========================================================================

