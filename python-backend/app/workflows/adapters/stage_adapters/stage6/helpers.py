"""阶段 6 持久化适配器通用辅助函数 (Stage 6 Persistence Adapter Helpers)。

提供角色名称归一化、Token 提取、实体模糊匹配、多视图类型解构以及文学/声音提示词兜底合成。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from app.core.logger import get_logger
from app.platform_common import now_iso
from app.tools.screenplay_feature_scanner import is_valid_character_speaker
from app.tools.shot_duration_calculator import clean_dialogue_text
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

log = get_logger("lmd.storage_adapter.stage6.helpers")

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
      'main_portrait'      (is_primary=1, 仅限 T1_BASE 纯面部基准或显式主肖像)
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

    # 1. 显式命中 FaceID 根节点 / 纯面部基准图 -> 唯一合法 main_portrait (is_primary=1)
    tok_clean = str(token).strip().upper()
    if tok_clean == "BASE" or tok_clean.endswith("_BASE") or any(k in combined for k in ("T1_BASE", "MAIN_PORTRAIT", "BASE_PORTRAIT", "主视觉肖像", "主肖像", "面部基准")):
        return ("main_portrait", explicit_label or "正面主视觉基准切片", 1)

    # 2. 识别单张四视图具体视角 (is_primary=0, 严禁四宫格合并)
    if any(k in combined for k in ("4V_FRONT", "FRONT_VIEW", "正立面", "正视图", "正面视角", "FRONT_FULL")) and not any(k in combined for k in ("FOUR_VIEW", "四视图")):
        return ("front_view", explicit_label or "正面定妆视角", 0)
    if any(k in combined for k in ("4V_SIDE", "SIDE_VIEW", "4V_PROFILE", "PROFILE", "侧立面", "侧视图", "侧面视角")):
        return ("side_view", explicit_label or "侧面定妆视角", 0)
    if any(k in combined for k in ("4V_BACK", "BACK_VIEW", "REAR", "背立面", "背视图", "背面视角")):
        return ("back_view", explicit_label or "背面定妆视角", 0)
    if any(k in combined for k in ("4V_3Q", "4V_THREE_QUARTER", "THREE_QUARTER", "3Q", "四分之三侧面", "半侧面")):
        return ("three_quarter_view", explicit_label or "3/4侧面定妆视角", 0)

    # 3. 传统/复合多角度工程切片 (four_view, is_primary=0)
    if any(k in combined for k in (
        "FOUR_VIEW", "THREE_VIEW", "4V", "3V", "SHEET", "四视图", "三视图",
        "多角度", "工程视图", "工程切片", "正侧背"
    )):
        return ("four_view", explicit_label or "角色多角度工程视图", 0)

    # 4. 全身定妆立绘 (full_body, is_primary=0)
    if any(k in combined for k in ("FULL_BODY", "FULLBODY", "BASE_COSTUME", "全身", "立绘")):
        return ("full_body", explicit_label or "全身定妆立绘", 0)

    # 5. 面部微距/特写 (facial_macro, is_primary=0)
    if any(k in combined for k in ("MACRO_FACE", "FACIAL_MACRO", "MACRO", "CLOSEUP", "FACE", "FACIAL", "面部特写", "微距", "五官")):
        return ("facial_macro", explicit_label or "面部五官超清微距切片", 0)

    # 6. 手部细节与道具交互切片 (hands_detail, is_primary=0)
    if any(k in combined for k in ("MACRO_HAND", "HANDS_DETAIL", "HAND", "HANDS", "手部", "手部特写")):
        return ("hands_detail", explicit_label or "手部与握持动作精细切片", 0)

    # 7. 纯正通用 BASE (若未被前面命中) -> main_portrait (is_primary=1)
    if combined.strip() == "BASE" or "_BASE" in combined:
        return ("main_portrait", explicit_label or "主视觉肖像", 1)

    # 8. 默认兜底切片：一律视为从属辅助切片 (is_primary=0)，杜绝主视觉参考图滥发
    return ("detail_slice", explicit_label or "形态细节切片", 0)


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

