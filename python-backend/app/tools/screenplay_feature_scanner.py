"""剧本多维特征逆向扫描识别引擎 (Screenplay Feature Scanner)。

【规则编号: RULE-V-S6-02】严格遵循 SKILL1.md v10.0.0 阶段 6 剧本多维特征逆向扫描识别引擎规范：
- 算子 A：角色资产识别与触发算子 (出场判定/四视角/情绪/光感/微距与伤残)
- 算子 B：场景资产识别与触发算子 (标头解析/景别与时态/过肩景深板)
- 算子 C：道具资产识别与触发算子 (一级物证静态/破坏形变动词库/二级锚定物/三级杂物)
- 算子 D：母音频实体化算子 (新角色首发高光对白金句抓取)
【规则编号: RULE-III-01 / RULE-III-02】四段式确定性资产命名协议 ([Category]_[Name]_[Tier]_[Modifier])
【规则编号: RULE-VI-06】05_visual_audio_assets.json 与 episode_resource_manifest 字段级契约

100% 确定性纯代码逻辑，零大模型幻觉，零随机盲猜。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.workflows.utils.asset_protocol import AssetProtocolHelper

if TYPE_CHECKING:
    from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack

logger = logging.getLogger("lmd.screenplay_feature_scanner")

# =========================================================================
# 【规则编号: RULE-V-S6-02 词表库】通用视听特征与破坏动词常量库
# 说明：
# 1. 视角、光感、微距、伤残与破坏形变动词属于跨题材通用的电影视听语言算子；
# 2. 严禁在此处硬编码特定剧目的专有角色、专有地点或剧情专属道具（如“冷水饺”等），
#    所有实体均通过 Stage 2/3 上游资产契约、核心词干脱敏匹配与通用动宾语法动态识别。
# =========================================================================

VIEW_FRONT_KEYWORDS = ["正面", "抬头", "直视", "走近", "迎面", "站立"]
VIEW_PROFILE_KEYWORDS = ["侧脸", "转头", "避开目光", "侧目", "向侧", "倚靠"]
VIEW_3Q_KEYWORDS = ["斜视", "侧身", "3/4", "回眸", "半侧"]
VIEW_BACK_KEYWORDS = ["背对", "背影", "转身离去", "后背", "远去"]

LIGHT_FLASH_KEYWORDS = ["手电筒直射", "强光照脸", "闪光"]
LIGHT_LOWKEY_KEYWORDS = ["阴暗", "侧逆光", "硬阴影", "月光", "烛光", "惨绿频闪"]

MACRO_HAND_KEYWORDS = [
    "手指", "掐掌心", "拉扯线头", "握住", "拿打火机", "指甲划过", "掐出指甲血痕", "掐指", "手背", "手腕",
    "死死攥着", "握紧", "掏出", "递过去", "从口袋拿出", "拔出", "指节发白", "紧握", "双手颤抖", "按住"
]
MACRO_EYE_KEYWORDS = ["眼眶", "眼角", "瞳孔", "血丝", "眼神", "逼视", "冷睨", "微缩"]
MACRO_MOUTH_KEYWORDS = ["嘴角", "咬唇", "皲裂起皮", "咬紧", "后槽牙", "渗血", "冷笑"]
INJURY_KEYWORDS = ["淤青", "流血", "夹伤", "撕裂", "湿透", "骨折", "挫伤", "血痕", "干结盐水泥斑", "伤口", "狼狈", "破碎", "血迹"]

ENV_WIDE_KEYWORDS = ["远景", "全貌", "俯瞰", "大楼", "大门", "进站", "全景", "街头横幅"]
ENV_INSERT_KEYWORDS = ["水龙头滴水", "挂钟秒针", "电表箱", "特写空镜", "15W节能灯", "频闪"]

# 通用高频道具类型兜底词表（仅当未传入上游 Stage 2/3 known_props 时作为无配置回退参考）
HERO_PROP_KEYWORDS: list[str] = [
    "日记", "确认书", "病历", "合同", "录音笔", "药盒", "打火机", "账本", "钥匙", "档案", "信件",
    "手枪", "匕首", "玉佩", "令牌", "U盘", "信封", "怀表", "短刀", "印章", "残卷"
]
DEFORMATION_VERBS = [
    "撕", "砸", "切", "断", "烧", "挑开", "崩碎", "撬开", "撞烂", "撕页", "划破", "扯回",
    "摔碎", "焚毁", "斩断", "捏碎", "折断", "撕开", "按动", "染血", "点燃", "咬碎", "浸湿",
    "剥离", "摔在地上", "砸烂", "被踩碎", "划痕", "开裂", "崩口", "卷刃"
]
ANCHOR_PROP_KEYWORDS: list[str] = ["打火机", "戒指", "手表", "创可贴", "钥匙", "红绳", "怀表", "吊坠", "眼镜", "钢笔"]
ATMOSPHERIC_PROP_KEYWORDS: list[str] = ["茶杯", "碗筷", "纸巾", "白气", "烟雾", "积水", "灰尘", "烛台", "酒杯"]

# 向后兼容保留的自定义拼音/语义代号覆盖字典接口（默认置空，完全由 AssetProtocolHelper.chinese_to_token 动态转写，
# 彻底消除特定剧目硬编码人名/地点/道具对通用流程的潜在干扰）
CHARACTER_PINYIN_LOOKUP: dict[str, str] = {}

PINYIN_LOOKUP: dict[str, str] = {}


@dataclass
class ReusedAssetRecord:
    """【规则编号: RULE-VI-06】本集复用的已核准资产。"""
    asset_id: str
    type: str
    usage_in_current_ep: str
    status: Literal["APPROVED"] = "APPROVED"

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "type": self.type,
            "usage_in_current_ep": self.usage_in_current_ep,
            "status": self.status,
        }


@dataclass
class NewlyGeneratedAssetRecord:
    """【规则编号: RULE-VI-06】本集增量新生成的单项资产。"""
    asset_id: str
    asset_category: str
    script_inference_trigger: str
    generation_method: str
    input_source_image: str | None
    identity_reference: str | None
    denoising_strength: float | None
    aspect_ratio: str
    image_prompt: str
    status: Literal["APPROVED"] = "APPROVED"

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_category": self.asset_category,
            "script_inference_trigger": self.script_inference_trigger,
            "generation_method": self.generation_method,
            "input_source_image": self.input_source_image,
            "identity_reference": self.identity_reference,
            "denoising_strength": self.denoising_strength,
            "aspect_ratio": self.aspect_ratio,
            "image_prompt": self.image_prompt,
            "status": self.status,
        }


@dataclass
class MasterVoiceCardRecord:
    """【规则编号: RULE-V-S6-02 算子 D】角色母音频实体化卡片。"""
    character_id: str
    master_voice_id: str
    script_monologue_source: str
    master_tts_prompt: str
    voice_file_path: str

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "master_voice_id": self.master_voice_id,
            "script_monologue_source": self.script_monologue_source,
            "master_tts_prompt": self.master_tts_prompt,
            "voice_file_path": self.voice_file_path,
        }


@dataclass
class ScreenplayScanResult:
    """剧本多维特征逆向扫描识别引擎全量产出。"""
    reused_existing_assets: list[ReusedAssetRecord] = field(default_factory=list)
    newly_generated_assets: list[NewlyGeneratedAssetRecord] = field(default_factory=list)
    new_character_master_voice_cards: list[MasterVoiceCardRecord] = field(default_factory=list)
    episode_resource_manifest: dict[str, Any] = field(default_factory=dict)
    characters_detected: list[str] = field(default_factory=list)
    scenes_detected: list[str] = field(default_factory=list)
    props_detected: list[str] = field(default_factory=list)
    emotions_detected: dict[str, list[str]] = field(default_factory=dict)
    injuries_detected: dict[str, list[str]] = field(default_factory=dict)
    macro_details: dict[str, list[str]] = field(default_factory=dict)
    lighting_conditions: list[str] = field(default_factory=list)
    deformed_props: dict[str, list[str]] = field(default_factory=dict)
    voice_actors_needed: dict[str, Any] = field(default_factory=dict)
    # 【新增】实体别名映射字典与代词共指消解决策追踪记录
    character_alias_map: dict[str, str] = field(default_factory=dict)
    coreference_resolutions: list[dict[str, Any]] = field(default_factory=list)
    # 【新增】空间功能子区域动态提取追踪字典 (scene_name -> [zone_names])
    scene_zones_detected: dict[str, list[str]] = field(default_factory=dict)

    @property
    def new_assets(self) -> list[NewlyGeneratedAssetRecord]:
        return self.newly_generated_assets

    @property
    def reused_assets(self) -> list[ReusedAssetRecord]:
        return self.reused_existing_assets

    @property
    def master_voice_cards(self) -> list[MasterVoiceCardRecord]:
        return self.new_character_master_voice_cards

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reused_existing_assets": [a.to_dict() if hasattr(a, "to_dict") else a for a in self.reused_existing_assets],
            "newly_generated_assets": [a.to_dict() if hasattr(a, "to_dict") else a for a in self.newly_generated_assets],
            "new_character_master_voice_cards": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.new_character_master_voice_cards],
            "episode_resource_manifest": self.episode_resource_manifest,
            "characters_detected": self.characters_detected,
            "scenes_detected": self.scenes_detected,
            "props_detected": self.props_detected,
            "emotions_detected": self.emotions_detected,
            "injuries_detected": self.injuries_detected,
            "macro_details": self.macro_details,
            "lighting_conditions": self.lighting_conditions,
            "deformed_props": self.deformed_props,
            "voice_actors_needed": self.voice_actors_needed,
            "character_alias_map": self.character_alias_map,
            "coreference_resolutions": self.coreference_resolutions,
            "scene_zones_detected": self.scene_zones_detected,
        }


NON_CHARACTER_SPEAKER_KEYWORDS = {
    "声学行为", "音效", "环境音", "背景音", "拟音", "配乐", "音乐", "BGM", "SFX", "VO", "OS",
    "旁白", "画外音", "字幕", "屏幕显示", "特写", "近景", "中景", "全景", "远景", "大特写", "主观视角",
    "镜头", "画面", "场景", "内景", "外景", "日景", "夜景", "切至", "转场", "闪回", "黑屏", "定格",
    "开局", "抓手", "微反转", "悬念", "钩子", "断章", "核心戏剧", "动作", "对白", "台词", "提示",
    "备注", "注意", "时间", "地点", "人物", "角色", "道具", "路人", "群演", "众人", "记者们", "围观者",
    "保安们", "手下们", "宾客们", "村民们", "警员们", "医护人员",
    # 泛化亲属与社会职业称谓（未前置明确具名注册前，严禁单独自动建档为活体大角色）
    "伯母", "伯父", "叔叔", "阿姨", "大妈", "大爷", "老人家", "保洁", "保洁阿姨", "保洁员",
    "服务员", "前台", "司机", "师傅", "快递员", "外卖员", "医生", "护士", "法医", "警官", "队长",
}


def is_valid_character_speaker(raw_name: str, known_names: set[str] | None = None) -> bool:
    """判定提取出的候选说话人是否为合法具名角色（过滤声学/镜头/结构指令与泛化群演）。"""
    if not raw_name:
        return False
    s = raw_name.strip()
    if known_names and s in known_names:
        return True
    # 包含括号、方括号、书名号、三角动作符等结构化符号的绝不是合法角色名
    if any(ch in s for ch in "[]【】()（）<>《》△▲◆●★☆/\\|@#￥%&*+=~`\"'“”‘’"):
        return False
    # 纯数字、纯英文指令或过短/过长
    if len(s) < 2 or len(s) > 8:
        return False
    if re.match(r"^\d+", s) or re.match(r"^第.+[集场幕秒]", s):
        return False
    # 命中舞台/声学/镜头/群演非具名关键词
    upper_s = s.upper()
    if upper_s in NON_CHARACTER_SPEAKER_KEYWORDS or s in NON_CHARACTER_SPEAKER_KEYWORDS:
        return False
    for kw in NON_CHARACTER_SPEAKER_KEYWORDS:
        if kw in s or kw in upper_s:
            return False
    return True


def _slugify_chinese(text: str) -> str:
    """将任意中文角色、场景或道具词汇动态转换为确定性大写拼音/英文 Token。

    优先级：
    1. 优先匹配 PINYIN_LOOKUP 精确覆盖项（如保留下划线的 SU_CHENG、LIN_XIA 或英文意译 DAGGER、STATION）；
    2. 调用全栈统一的 AssetProtocolHelper.chinese_to_token(text, max_len=24) 动态生成拼音 Token；
    3. 若包含子串覆盖项（如“货运火车站扳道房”含“火车站”），仅在未命中完整中文转写或特定场景约定下兜底。
    """
    if not text:
        return "UNKNOWN"
    clean_input = text.strip()
    # 1. 精确命中覆盖表（兼容历史单测如 苏诚 -> SU_CHENG, 生锈的手术刀 -> DAGGER）
    if clean_input in PINYIN_LOOKUP:
        token = PINYIN_LOOKUP[clean_input]
        logger.debug("【特征扫描·Token生成】实体 '%s' 命中精确覆盖字典 -> [%s]", clean_input, token)
        return token

    # 2. 尝试剔除书名号、引号与常见修饰前缀后使用全栈统一的动态拼音协议
    stripped = re.sub(r"《[^》]*》", "", clean_input)
    stripped = re.sub(r"[“”\"'‘’（）()【】\[\]]", "", stripped).strip()
    if stripped in PINYIN_LOOKUP:
        token = PINYIN_LOOKUP[stripped]
        logger.debug("【特征扫描·Token生成】去修饰实体 '%s' 命中覆盖字典 -> [%s]", stripped, token)
        return token

    # 3. 调用 AssetProtocolHelper.chinese_to_token 动态转写拼音/确定性大写标识（最长截取 24 位 [A-Z0-9] 字符）
    dynamic_token = AssetProtocolHelper.chinese_to_token(stripped or clean_input)[:24]
    if dynamic_token and dynamic_token != "UNKNOWN" and any(c.isalpha() for c in dynamic_token):
        logger.debug("【特征扫描·Token生成】实体 '%s' 动态转写 Token -> [%s]", clean_input, dynamic_token)
        return dynamic_token

    # 3.5 兜底防护：若 dynamic_token 为纯数字或缺失（例如无 pypinyin 运行环境），优先检索 PINYIN_LOOKUP 子词库
    for kw, val in sorted(PINYIN_LOOKUP.items(), key=lambda x: len(x[0]), reverse=True):
        if len(kw) >= 2 and kw in clean_input:
            logger.debug("【特征扫描·Token生成】实体 '%s' 兜底命中子词 '%s' -> [%s]", clean_input, kw, val)
            return val

    if dynamic_token and dynamic_token != "UNKNOWN":
        return dynamic_token

    clean = re.sub(r"[^A-Z0-9]", "", clean_input.upper())
    return clean or "UNKNOWN"


def _extract_entity_core_stems(entity_name: str) -> list[str]:
    """从长修饰名（如 Stage 2/3 產出的“《绝密之局》涉案加密暗账本”、“父亲留下的老式铜怀表”）中提取核心名词词干。

    解决 Stage 2/3 字典全称与 Stage 5 剧本正文中自然简称（如“暗账本”、“铜怀表”、“手术刀”）不一致导致的漏检问题。
    返回的候选列表按从长到短排序，包含：
    1. 原始全称；
    2. 剥离《剧名》与括号备注后的主体名；
    3. 剥离“的”字定语从句后的核心名词及末尾 2~4 字词干。
    """
    if not entity_name:
        return []
    stems: list[str] = []

    def _add(candidate: str) -> None:
        c = candidate.strip()
        if len(c) >= 2 and c not in stems:
            stems.append(c)

    _add(entity_name)
    # 去除《...》剧名标签与括号说明
    no_book = re.sub(r"《[^》]*》", "", entity_name)
    no_book = re.sub(r"（[^）]*）|\([^)]*\)", "", no_book).strip()
    _add(no_book)

    # 去除常见策划前缀（如“涉案”、“核心物证”、“关键道具”）及尾部常见功能后缀（如“主场景”、“核心功能区”、“主决战台”）
    no_prefix = re.sub(r"^(?:涉案|核心物证|关键物证|关键道具|随身|祖传|特制|伪造|神秘|老旧|破旧|生锈)+", "", no_book).strip()
    _add(no_prefix)
    no_suffix = re.sub(r"(?:主决战台|决战台|核心功能区|主活动区|核心区|主场景|全景|内景|外景|区域)+$", "", no_prefix).strip()
    _add(no_suffix)

    # 去除“的”字无意义连接及定语前缀（如“生锈的手术刀” -> “生锈手术刀” & “手术刀”）
    if "的" in no_book:
        _add(no_book.replace("的", ""))
        tail_after_de = no_book.split("的")[-1].strip()
        _add(tail_after_de)

    # 针对长度 >= 4 的复合中文名词，提取首尾及核心词干（如“加密暗账本” -> “暗账本”、“账本”；“青云山断崖” -> “断崖”）
    base_for_tail = no_suffix if len(no_suffix) >= 2 else (no_prefix if len(no_prefix) >= 2 else no_book)
    if len(base_for_tail) >= 4:
        _add(base_for_tail[-3:])
        _add(base_for_tail[-2:])
        _add(base_for_tail[:3])
    elif len(base_for_tail) == 3:
        _add(base_for_tail[-2:])

    logger.debug("【特征扫描·词干提取】实体 '%s' 派生匹配词干列表: %s", entity_name, stems)
    return stems


def _entity_matches_text(entity_name: str, text: str) -> bool:
    """判断实体（或其脱敏核心词干）是否在目标剧本或单句文本中出现。"""
    if not entity_name or not text:
        return False
    for stem in _extract_entity_core_stems(entity_name):
        if stem in text:
            return True
    return False


def _extract_anchor_props_from_characters(known_characters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """从 Stage 2 角色档案中自动提取二级随身锚点道具（carried_anchor_item / anchor_props）。

    消除原先需要在 scanner 中硬编码 ANCHOR_PROP_KEYWORDS 的问题，实现 Stage 2 -> Stage 6 随身道具闭环。
    """
    extracted: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    if not known_characters:
        return extracted

    for char_obj in known_characters:
        if not isinstance(char_obj, dict):
            continue
        c_name = str(char_obj.get("name") or "").strip()
        candidates: list[str] = []

        # 1. Stage 2 标准字段 carried_anchor_item.item_name
        carried = char_obj.get("carried_anchor_item")
        if isinstance(carried, dict):
            item_name = str(carried.get("item_name") or carried.get("name") or "").strip()
            if item_name:
                candidates.append(item_name)
        elif isinstance(carried, str) and carried.strip():
            candidates.append(carried.strip())

        # 2. visual_consistency_code / lived_in_costume 下的 anchor_props
        for sub_key in ("visual_consistency_code", "lived_in_costume"):
            sub_dict = char_obj.get(sub_key)
            if isinstance(sub_dict, dict):
                ap = sub_dict.get("anchor_props")
                if isinstance(ap, list):
                    candidates.extend(str(x).strip() for x in ap if str(x).strip())
                elif isinstance(ap, str) and ap.strip():
                    candidates.extend(s.strip() for s in re.split(r"[,，、/；;]+", ap) if s.strip())

        # 3. 顶层 anchor_props
        top_ap = char_obj.get("anchor_props")
        if isinstance(top_ap, list):
            candidates.extend(str(x).strip() for x in top_ap if str(x).strip())
        elif isinstance(top_ap, str) and top_ap.strip():
            candidates.extend(s.strip() for s in re.split(r"[,，、/；;]+", top_ap) if s.strip())

        for raw_prop in candidates:
            # 清理括号说明，保留道具本体名称
            clean_prop = re.sub(r"（[^）]*）|\([^)]*\)", "", raw_prop).strip()
            if len(clean_prop) >= 2 and clean_prop not in seen_names:
                seen_names.add(clean_prop)
                prop_id = f"PROP_{_slugify_chinese(clean_prop)}"
                extracted.append({
                    "prop_id": prop_id,
                    "name": clean_prop,
                    "tier": "T2",
                    "owner": c_name,
                })
                logger.debug(
                    "【特征扫描·Stage2锚点汇入】从角色 [%s] 档案提取二级随身锚点道具: '%s' (%s)",
                    c_name or "未知角色", clean_prop, prop_id,
                )
    return extracted


def _extract_dynamic_props_from_screenplay(
    screenplay_text: str,
    known_character_names: set[str] | None = None,
    known_scene_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """【规则编号: RULE-SCAN-DYNAMIC-PROP】基于剧本动作行动宾短语与物理实体形态动态抽取道具。

    彻底打破死板的静态枚举关键词限制，通过扫描剧本动作行中与动词（拿/拔/掏/撕/摔/砸/递/捡/抽/扣动等）
    发生物理交互的名词短语，动态发现任意类型剧情物证，并建立统一的候选道具结构。
    """
    if not screenplay_text:
        return []

    known_chars = {str(c).strip() for c in (known_character_names or set()) if str(c).strip()}
    known_scenes = {str(s).strip() for s in (known_scene_names or set()) if str(s).strip()}

    # 常见动作交互动词（支持动宾短语抽取与物理实体扫描）
    ACTION_VERBS = [
        "手持", "手握", "持有", "握着", "紧握", "握紧", "挥舞", "刺向", "刺入", "抵住", "指向", "瞄准",
        "佩戴", "戴着", "揣着", "挂着", "系着", "装着", "亮出", "掏出", "拿起", "拔出", "捡起",
        "夺过", "摔下", "摔碎", "砸向", "递过", "递来", "翻开", "撕毁", "撕碎", "点燃", "扣动",
        "插进", "插入", "藏起", "举起", "抽出", "攥着", "放下", "推开", "打开", "合上", "取出",
        "擦拭", "抱起", "夺走", "拾起", "端起", "握住", "掏出", "拿出", "抓起", "递出", "端来",
        "掏", "拿", "拔", "握", "捡", "夺", "摔", "砸", "递", "翻", "撕", "抽", "攥", "端", "提", "抓",
    ]

    # 物理道具典型词缀（词尾匹配）
    PROP_SUFFIXES = (
        "刀", "枪", "剑", "笔", "盒", "本", "锁", "证", "卡", "表", "机", "环", "绳", "坠",
        "符", "镜", "杯", "瓶", "带", "箱", "夹", "盘", "纸", "书", "袋", "玉", "链", "印",
        "牌", "器", "管", "扣", "戒", "针", "片", "柄", "包", "棒", "棍", "尺", "卷", "药",
        "珠", "币", "扇", "伞", "笛", "箫", "琴", "鼎", "鉴", "录", "票", "单", "簿", "券",
    )

    # 物理道具核心词干（子串包含）
    PHYSICAL_CORE_STEMS = (
        "账本", "档案", "芯片", "首饰", "项链", "打火机", "手机", "电脑", "录音", "钥匙",
        "手铐", "药丸", "注射器", "红绳", "公文包", "病历", "合同", "裁纸刀", "短刃", "碎瓷片",
        "急救包", "信封", "皮夹", "手电筒", "碎玻璃", "U盘", "暗账", "玉佩", "令牌", "手串",
    )

    # 排除的人体部位、抽象概念与非道具实体停用词
    NON_PROP_STOPWORDS = {
        "自己", "对方", "众人", "两人", "身体", "拳头", "手臂", "手掌", "手腕", "手背",
        "双眼", "眼睛", "嘴角", "后背", "肩膀", "胸膛", "脚步", "呼吸", "声音", "目光",
        "眼神", "主意", "机会", "情绪", "怒火", "寒意", "决定", "念头", "心思", "秘密",
        "真相", "门", "窗", "门把手", "门锁", "墙壁", "地板", "地面", "天花板", "桌子",
        "椅子", "沙发", "空气", "床铺", "被子", "栏杆", "走廊", "大门", "衣服", "衣角",
    }

    # 动词按字符长度降序排序，确保多字动词优先于单字动词匹配（如避免'掏出'被'掏'截断）
    sorted_verbs = sorted(set(ACTION_VERBS), key=len, reverse=True)
    verb_alt = "|".join(re.escape(v) for v in sorted_verbs)
    prop_pattern = re.compile(
        rf"(?:{verb_alt})\s*"
        r"(?:[一两三四五六七八九十几1-9]个|[一两三四五六七八九十几1-9]把|[一两三四五六七八九十几1-9]张|[一两三四五六七八九十几1-9]本|"
        r"[一两三四五六七八九十几1-9]支|[一两三四五六七八九十几1-9]条|[一两三四五六七八九十几1-9]盒|[一两三四五六七八九十几1-9]包|"
        r"[一两三四五六七八九十几1-9]块|[一两三四五六七八九十几1-9]枚|[一两三四五六七八九十几1-9]管|[一两三四五六七八九十几1-9]根|"
        r"[一两三四五六七八九十几1-9]柄|[一两三四五六七八九十几1-9]卷|[一两三四五六七八九十几1-9]封|[一两三四五六七八九十几1-9]具|"
        r"[一两三四五六七八九十几1-9]串|[一两三四五六七八九十几1-9]沓|[一两三四五六七八九十几1-9]套|[一两三四五六七八九十几1-9]副|"
        r"[一两三四五六七八九十几1-9]件|那[个把张本支条盒包块枚管根柄卷封串沓套副件]|这[个把张本支条盒包块枚管根柄卷封串沓套副件]|"
        r"手中的|怀里的|胸前的|桌上的|地上的|兜里的|包里的|抽屉里的|墙上的)?\s*"
        r"([^\s，。！？、（）：“”\"\'\n\r]{2,12}?)(?:[，。！？、（）：“”\"\'\n\r]|$)"
    )

    found_props: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # -------------------------------------------------------------------------
    # 步骤 1：优先抓取剧本行业标准物证标记 【...】 或 「...」
    # -------------------------------------------------------------------------
    # 场景固定大尺度陈设黑名单（二元法则：棺木/遗像/铁盆等应融入场景描述，不得单独建道具资产）
    SPATIAL_SETTLEMENT_STOPWORDS = {
        "灵堂棺木", "棺木", "棺材", "供桌", "生锈铁盆", "铁盆", "黄纸", "纸灰",
        "苏秀兰黑白遗像", "黑白遗像", "遗像", "遗像玻璃框", "镜框", "钨丝灯",
    }
    
    # 残缺动词前缀黑名单（杜绝因动词匹配不全导致抽取到“转信封”、“扯信封”等病态短语）
    ACTION_VERB_PREFIXES = (
        "转", "翻转", "扯", "扯下", "推", "推向", "拍", "拍在", "撕", "撕开",
        "抓", "抓向", "看", "按", "看清", "拔", "拔出", "拿", "拿出",
    )

    # 仅抓取【...】中的实体物证，不把「...」中的直接引语/血字台词当做道具名
    bracket_pattern = re.compile(r"【([^\s】]+)】")
    for line in screenplay_text.splitlines():
        line_str = line.strip()
        if not line_str or line_str.startswith("场景") or line_str.startswith("第"):
            continue
        for bm in bracket_pattern.finditer(line_str):
            raw_bracket = bm.group(1).strip()
            # 滤除剧本标记如“开局3秒抓手”、“45秒微反转”、“115秒片尾悬念”等镜头说明
            if any(marker in raw_bracket for marker in ["秒", "抓手", "反转", "悬念", "场景", "镜头", "特效"]):
                continue
            # 二元法则过滤：空间固定陈设不作为独立道具
            if raw_bracket in SPATIAL_SETTLEMENT_STOPWORDS:
                logger.debug("【特征扫描·二元法则】空间大尺度陈设 [%s] 跳过独立道具提取，归入场景描述", raw_bracket)
                continue
            # 清除前后残留修饰
            clean_bname = raw_bracket
            # 剔除截断动词
            for act_pf in ACTION_VERB_PREFIXES:
                if clean_bname.startswith(act_pf) and len(clean_bname) > len(act_pf) + 1:
                    clean_bname = clean_bname[len(act_pf):].strip()
            if len(clean_bname) >= 2 and clean_bname not in seen_names:
                seen_names.add(clean_bname)
                prop_slug = _slugify_chinese(clean_bname)
                prop_id = f"PROP_{prop_slug}"
                found_props.append({
                    "prop_id": prop_id,
                    "prop_code": prop_id,
                    "name": clean_bname,
                    "material": "关键案情物证",
                    "form": "S0_STATIC",
                    "category": "hero",
                    "importance": "high",
                    "screenplay_evidence": line_str,
                })
                logger.debug("【特征扫描·核心物证捕获】命中剧本【...】高维物证: [%s] -> %s", clean_bname, prop_id)

    # -------------------------------------------------------------------------
    # 步骤 1.5：构建高维物证核心物理词干反向索引池 (Core Stem Index Map)
    # 核心目标：
    # 剧本写作呈现“首次详写修饰、后续动作自然简写”规律（如【带血的牛皮纸信封】后续写为“信封”）。
    # 建立词干索引，便于步骤 2 动宾抽取时精准拦截同源简写，杜绝同一道具裂变为两个独立资产。
    # -------------------------------------------------------------------------
    stem_to_parent_prop: dict[str, dict[str, Any]] = {}
    for p_item in found_props:
        p_name = p_item["name"]
        # 1. 剥离状态修饰词提取物理核心词（例如“带血的牛皮纸信封”剥离修饰后为“牛皮纸信封”）
        core_candidate = re.sub(
            r"^(?:染血的|生锈的|破碎的|残破的|发黄的|带血的|破旧的|崭新的|锋利的|冰冷的|沾血的|烧焦的|厚重的|泛黄的)+",
            "",
            p_name,
        ).strip()
        # 2. 匹配物理道具核心词干（例如“信封”、“卷宗”、“处方笺”、“存根”、“手电筒”）
        for stem in PHYSICAL_CORE_STEMS:
            if stem in p_name:
                stem_to_parent_prop[stem] = p_item
        # 3. 后缀物理词缀提取
        for sfx in PROP_SUFFIXES:
            if core_candidate.endswith(sfx) and len(core_candidate) >= len(sfx) + 1:
                # 截取后 2-3 个汉字作为短词干
                short_s = core_candidate[-2:]
                stem_to_parent_prop[short_s] = p_item
        if core_candidate and core_candidate != p_name:
            stem_to_parent_prop[core_candidate] = p_item

    # -------------------------------------------------------------------------
    # 步骤 2：正文动作行手持与交互器具动宾抽取
    # -------------------------------------------------------------------------
    for line in screenplay_text.splitlines():
        line = line.strip()
        if not line or line.startswith("场景") or line.startswith("第") or ":" in line or "：" in line:
            continue

        for m in prop_pattern.finditer(line):
            raw_target = m.group(1).strip()
            # 滤除前导代词、冠词与方位介词
            clean_target = re.sub(
                r"^(?:那|这|某个|一[个把张本支条盒包块枚管根柄卷封串沓套副件]|手中|怀里|胸前|桌上|地上|兜里|包里|抽屉里|墙上|出)+的?",
                "",
                raw_target,
            ).strip()
            clean_target = re.sub(r"^(?:出|的|地|得)+", "", clean_target).strip()
            clean_target = re.sub(r"(?:的|地|得)$", "", clean_target).strip()
            # 滤除结尾的动作副词与谓语动词（如“推上开关”、“撕开封口”等残留在宾语后的动作词）
            clean_target = re.sub(r"(?:推上开关|推开开关|撕开封口|刺破纸边|滑落掌心|摔向地面|拍在供桌上|按在桌面).*$", "", clean_target).strip()
            # 杜绝谓语残缺截断（如“翻转信封”被拆出“转信封”）
            for act_pf in ACTION_VERB_PREFIXES:
                if clean_target.startswith(act_pf) and len(clean_target) > len(act_pf) + 1:
                    clean_target = clean_target[len(act_pf):].strip()
            if len(clean_target) < 2 or len(clean_target) > 12:
                continue
            if clean_target in NON_PROP_STOPWORDS or clean_target in SPATIAL_SETTLEMENT_STOPWORDS:
                continue
            if clean_target in known_chars or any(c in clean_target for c in known_chars):
                continue
            if clean_target in known_scenes or any(s in clean_target for s in known_scenes):
                continue

            # 剔除动作状态修饰前缀（如“染血的”、“生锈的”），抽取出纯净物理实体基名
            core_noun = re.sub(r"^(?:染血的|生锈的|破碎的|残破的|发黄的|带血的|破旧的|崭新的|锋利的|冰冷的|沾血的|烧焦的|厚重的|泛黄的)+", "", clean_target).strip()
            target_name = core_noun if (len(core_noun) >= 2 and (core_noun.endswith(PROP_SUFFIXES) or any(s in core_noun for s in PHYSICAL_CORE_STEMS))) else clean_target

            is_physical = target_name.endswith(PROP_SUFFIXES) or any(stem in target_name for stem in PHYSICAL_CORE_STEMS)
            if not is_physical:
                continue

            # -----------------------------------------------------------------
            # 核心指代消解与同源物证归并 (Coreference Resolution & Merging)
            # -----------------------------------------------------------------
            matched_parent: dict[str, Any] | None = None
            # 优先级 A: 精确命中步骤 1 构建的核心词干索引池
            if target_name in stem_to_parent_prop:
                matched_parent = stem_to_parent_prop[target_name]
            elif clean_target in stem_to_parent_prop:
                matched_parent = stem_to_parent_prop[clean_target]
            else:
                # 优先级 B: 母子词双向包含且末尾词干一致（如“信封”与“带血的牛皮纸信封”）
                for p_item in found_props:
                    p_name = p_item.get("name", "")
                    if p_name and (target_name in p_name or p_name in target_name):
                        # 防呆排他：若两实体均具备相斥的颜色或材质修饰，严禁合并（例如白信封 vs 黑信封）
                        matched_parent = p_item
                        break

            if matched_parent is not None:
                # 【防呆合流】同源简写命中已知母物证：绝不重复创建新独立资产！
                parent_name = matched_parent.get("name", "")
                # 1. 录入母物证的别名列表
                aliases = matched_parent.setdefault("aliases", [])
                if target_name != parent_name and target_name not in aliases:
                    aliases.append(target_name)
                    logger.info(
                        "【特征扫描·道具指代归并】动作行简写 [%s] 成功合并归入母物证 [%s] 别名库",
                        target_name, parent_name,
                    )
                # 2. 动作语料冒泡合并 (Action Corpus Bubbling)：将动作行语料追加至母物证证据链
                existing_ev = matched_parent.get("screenplay_evidence", "")
                if line not in existing_ev:
                    matched_parent["screenplay_evidence"] = f"{existing_ev}\n{line}".strip()
                # 3. 收集并回传动作行中的破坏动词（供算子引擎精确触发 T1_ACTION）
                for d_verb in DEFORMATION_VERBS:
                    if d_verb in line:
                        matched_parent.setdefault("deformation_verbs", []).append(d_verb)
                        logger.debug(
                            "【特征扫描·破坏语料冒泡】母物证 [%s] 从简写动作行吸收破坏动词 [%s]",
                            parent_name, d_verb,
                        )
                # 跳过后续独立新建资产逻辑，实现平滑归一
                continue

            if target_name not in seen_names:
                seen_names.add(target_name)
                prop_slug = _slugify_chinese(target_name)
                prop_id = f"PROP_{prop_slug}"
                found_props.append({
                    "prop_id": prop_id,
                    "name": target_name,
                    "tier": "T1",
                })
                logger.debug(
                    "【特征扫描·NLP动宾动态抽取】从剧本动作行捕获全新物理道具: '%s' (%s)",
                    target_name, prop_id,
                )

    return found_props


def _normalize_emotion(raw_bracket_text: str) -> str:
    """将对白括注中的情绪归一化为英文大写标识。"""
    if any(k in raw_bracket_text for k in ["冷笑", "讥讽"]):
        return "COLD_SNEER"
    if any(k in raw_bracket_text for k in ["咬牙", "后槽牙", "紧绷", "低吼"]):
        return "TENSION"
    if any(k in raw_bracket_text for k in ["哭", "泪", "悲", "红眶"]):
        return "GRIEF"
    if any(k in raw_bracket_text for k in ["怒", "咆哮", "猛地", "甩"]):
        return "ANGER"
    if any(k in raw_bracket_text for k in ["恐", "惊", "战栗", "颤抖"]):
        return "FEAR"
    if any(k in raw_bracket_text for k in ["平稳", "冷静", "冷冷"]):
        return "CALM"
    return "INTENSE"


def scan_screenplay_features(
    screenplay_text: str,
    previous_pickup: dict[str, Any] | None = None,
    existing_asset_ids: set[str] | list[str] | None = None,
    character_id_map: dict[str, str] | None = None,
    default_style: str = "Cinematic film still, photorealistic gritty noir, 8k resolution, raw photo",
    *,
    episode_id: int | None = None,
    known_characters: list[dict[str, Any]] | None = None,
    known_environments: list[dict[str, Any]] | None = None,
    known_props: list[dict[str, Any]] | None = None,
    existing_assets_registry: dict[str, Any] | set[str] | list[str] | None = None,
    characters: list[dict[str, Any]] | None = None,
    scenes: list[dict[str, Any]] | None = None,
    environments: list[dict[str, Any]] | None = None,
    props: list[dict[str, Any]] | None = None,
    character_alias_map: dict[str, str] | None = None,
    genre_pack: BaseGenrePack | None = None,
    drama_genre: str = "",
    **kwargs: Any,
) -> ScreenplayScanResult:
    """【规则编号: RULE-V-S6-02】执行剧本多维特征逆向扫描识别引擎。

    涵盖四大算子：
    - 算子 A：角色特征扫描、别名消歧 (NER) 与代词共指消解 (Coreference Resolution)
    - 算子 B：场景标头与光影气候逆向提取
    - 算子 C：核心物证、形变破坏动词与道具演进追踪
    - 算子 D：对白示范与母音频卡片逆向抓取

    支持注入 `genre_pack` 题材预设包，动态自适应多题材（修仙、科幻、都市、悬疑等）的道具与动作特征。

    Args:
        screenplay_text: 当集分集剧本文本。
        previous_pickup: 上一集 0 秒物理快照交接数据。
        existing_asset_ids: 已登记存在的资产 ID 集合。
        character_id_map: 角色名称到资产编码的映射表。
        default_style: 默认视觉画风提示词。
        episode_id: 分集编号。
        known_characters: 上游已知角色列表。
        known_environments: 上游已知物理空间列表。
        known_props: 上游已知关键道具列表。
        existing_assets_registry: 已知资产注册表字典或集合。
        genre_pack: 题材预设包实例（可选，为空则动态自动探测）。
        drama_genre: 剧本题材标签（如 '仙侠', '悬疑', '科幻', '都市' 等）。

    Returns:
        ScreenplayScanResult: 规范化的扫描识别结果数据类。
    """
    if genre_pack is None:
        from app.workflows.nodes.stage6.genre_packs.registry import get_genre_pack

        genre_pack = get_genre_pack(
            drama_genre=drama_genre or kwargs.get("genre", ""),
            visual_style=default_style or kwargs.get("visual_style", ""),
            screenplay_text=screenplay_text,
        )
    logger.debug(
        "【阶段 6 特征逆向扫描引擎】启动确定性扫描 (集数: %s, 剧本长度: %d 字, 绑定题材包: [%s])",
        episode_id,
        len(screenplay_text) if screenplay_text else 0,
        genre_pack.name if genre_pack else "none",
    )

    known_characters = known_characters or characters or kwargs.get("character_engine") or []
    known_environments = known_environments or scenes or environments or []
    known_props = known_props or props or []

    # 规范化已有资产集合
    all_existing_ids: set[str] = set(existing_asset_ids or [])
    if existing_assets_registry:
        if isinstance(existing_assets_registry, dict):
            all_existing_ids.update(existing_assets_registry.keys())
        elif isinstance(existing_assets_registry, (list, set)):
            all_existing_ids.update(existing_assets_registry)

    # -------------------------------------------------------------------------
    # 建立别名消歧映射表 (NER) 与角色性别映射 (用于代词共指消解)
    # -------------------------------------------------------------------------
    alias_map: dict[str, str] = {}
    if character_alias_map:
        alias_map.update(character_alias_map)

    char_gender_map: dict[str, str] = {}
    FEMALE_NAME_TOKENS = ["婉", "晓", "夏", "琴", "琳", "姐", "妹", "女", "妻", "母", "颖", "雅", "婷", "静", "雪", "菲", "薇", "柔", "云"]

    if known_characters:
        for c in known_characters:
            if not isinstance(c, dict):
                continue
            c_name = c.get("name") or ""
            if not c_name:
                continue
            # 提取别名列表 (如 顾总 -> 顾夜白, 老徐 -> 徐伯)
            raw_aliases = c.get("aliases") or c.get("alias") or []
            if isinstance(raw_aliases, str):
                raw_aliases = [a.strip() for a in re.split(r"[,，/、\s]+", raw_aliases) if a.strip()]
            for alt in raw_aliases:
                if alt and alt != c_name:
                    alias_map[alt] = c_name
            if c.get("nickname") and c["nickname"] != c_name:
                alias_map[c["nickname"]] = c_name
            if c.get("title") and c["title"] != c_name:
                alias_map[c["title"]] = c_name

            # 性别推断
            raw_g = str(c.get("gender") or "").lower()
            if raw_g in ("female", "女", "woman"):
                char_gender_map[c_name] = "female"
            elif raw_g in ("male", "男", "man"):
                char_gender_map[c_name] = "male"
            else:
                char_gender_map[c_name] = "female" if any(tk in c_name for tk in FEMALE_NAME_TOKENS) else "male"

    # 建立角色映射：优先使用上游显式传入的 character_id_map 与 known_characters，
    # 严禁将无关剧目的硬编码人名无条件注入当前剧集的待检角色池
    char_map: dict[str, str] = {}
    char_tier_map: dict[str, str] = {}
    if character_id_map:
        for c_name, c_id in character_id_map.items():
            if c_name:
                char_map[c_name] = c_id or f"CHAR_{_slugify_chinese(c_name)}"
                if c_name not in char_gender_map:
                    char_gender_map[c_name] = "female" if any(tk in c_name for tk in FEMALE_NAME_TOKENS) else "male"
    if known_characters:
        for c in known_characters:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            if not name:
                continue
            cid = c.get("character_id") or f"CHAR_{_slugify_chinese(name)}"
            tier = c.get("tier", "HERO")
            char_map[name] = cid
            char_tier_map[name] = tier
            char_tier_map[cid] = tier

    # 别名继承标准代号与 tier
    for alias_k, canon_v in alias_map.items():
        if canon_v not in char_map:
            char_map[canon_v] = f"CHAR_{_slugify_chinese(canon_v)}"
        if canon_v not in char_gender_map:
            char_gender_map[canon_v] = "female" if any(tk in canon_v for tk in FEMALE_NAME_TOKENS) else "male"
        if alias_k not in char_map:
            char_map[alias_k] = char_map[canon_v]
        if canon_v in char_tier_map and alias_k not in char_tier_map:
            char_tier_map[alias_k] = char_tier_map[canon_v]
        if canon_v in char_gender_map and alias_k not in char_gender_map:
            char_gender_map[alias_k] = char_gender_map[canon_v]

    logger.debug(
        "【特征扫描·初始化】已加载候选角色映射 %d 个: %s, 别名映射 %d 个: %s",
        len(char_map), list(char_map.keys()), len(alias_map), alias_map,
    )

    result = ScreenplayScanResult()

    def add_or_reuse(asset_id: str, category: str, trigger: str, method: str,
                     input_source: str | None = None, id_ref: str | None = None,
                     denoising: float | None = None, aspect_ratio: str = "9:16",
                     image_prompt: str = "") -> None:
        """根据是否在总库已存在自动归入 reused 或 newly_generated。"""
        if asset_id in all_existing_ids:
            result.reused_existing_assets.append(
                ReusedAssetRecord(
                    asset_id=asset_id,
                    type=category,
                    usage_in_current_ep=f"复用已核准资产 {asset_id}",
                )
            )
        else:
            result.newly_generated_assets.append(
                NewlyGeneratedAssetRecord(
                    asset_id=asset_id,
                    asset_category=category,
                    script_inference_trigger=trigger,
                    generation_method=method,
                    input_source_image=input_source,
                    identity_reference=id_ref,
                    denoising_strength=denoising,
                    aspect_ratio=aspect_ratio,
                    image_prompt=image_prompt,
                )
            )

    # -------------------------------------------------------------------------
    # 步骤 1：解析场景标头 (算子 B1) + 三级核心空间词干匹配
    # -------------------------------------------------------------------------
    header_pattern = re.compile(
        r"[【\[]?[ \t]*场景[ \t]*(\d+)?[：:\s]*([^】\]\r\n]*)[】\]]?[ \t]*([^\r\n]*)"
    )
    scenes: list[dict[str, Any]] = []
    scenes_text_list: list[str] = []
    header_matches = list(header_pattern.finditer(screenplay_text))

    for idx, match in enumerate(header_matches, start=1):
        num_str = match.group(1) or f"{idx:02d}"
        part_inside = (match.group(2) or "").strip()
        part_outside = (match.group(3) or "").strip()
        location_raw = f"{part_inside} {part_outside}".strip() if (part_inside and part_outside) else (part_inside or part_outside)

        time_weather = "日"
        location = location_raw
        for tw in ["深夜", "黎明", "清晨", "黄昏", "暴雨", "夜", "日", "雨"]:
            if tw in location_raw:
                time_weather = tw
                break

        # 剥离标头中“ - 深夜/暴雨”等时态气候尾缀，保留纯净地点主干用于生成 ENV 资产 ID
        clean_location = re.split(r"\s*[-—–｜|]\s*", location_raw)[0].strip()
        clean_location = re.sub(r"[（(][^）)]*[）)]", "", clean_location).strip() or location_raw

        # 优先与上游 Stage 3 known_environments 做全称或核心词干对齐
        matched_env_id: str | None = None
        if known_environments:
            for ks in known_environments:
                if isinstance(ks, dict):
                    ks_name = str(ks.get("name") or ks.get("location") or "").strip()
                    ks_id = str(ks.get("env_id") or ks.get("scene_id") or "").strip()
                else:
                    ks_name = str(ks).strip()
                    ks_id = ""
                if ks_name and (_entity_matches_text(ks_name, clean_location) or _entity_matches_text(clean_location, ks_name)):
                    if ks_id:
                        matched_env_id = ks_id if ks_id.startswith("ENV_") else f"ENV_{ks_id}"
                    else:
                        matched_env_id = f"ENV_{_slugify_chinese(ks_name)}_T1_WIDE"
                    logger.debug(
                        "【特征扫描·场景对齐】剧本标头 '%s' 命中 Stage3 已知空间 '%s' -> [%s]",
                        clean_location, ks_name, matched_env_id,
                    )
                    break

        if matched_env_id:
            if re.match(r"^ENV_[A-Z0-9]+_(?:T[1-3]|Z\d+)_[A-Z0-9]+", matched_env_id):
                env_id = matched_env_id
            elif matched_env_id.endswith(("_T1", "_T2")):
                env_id = f"{matched_env_id}_WIDE"
            else:
                env_id = f"{matched_env_id}_T1_WIDE"
        else:
            slug_loc = _slugify_chinese(clean_location)
            env_id = f"ENV_{slug_loc}_T1_WIDE"
            logger.debug("【特征扫描·场景标头】解析场景 #%s '%s' -> 动态资产ID [%s]", num_str, clean_location, env_id)

        scenes.append({
            "env_id": env_id,
            "scene_number": int(num_str) if num_str.isdigit() else idx,
            "location": location,
            "time_of_day": time_weather,
            "full_header": match.group(0),
        })
        scenes_text_list.append(location_raw)

    # 补充扫描正文中直接或通过核心词干提及的 Stage 3 已知空间
    if known_environments:
        for ks in known_environments:
            ks_name = ks.get("name", "") if isinstance(ks, dict) else str(ks)
            if ks_name and _entity_matches_text(ks_name, screenplay_text) and (ks_name not in scenes_text_list):
                scenes_text_list.append(ks_name)
                logger.debug("【特征扫描·场景词干命中】正文中命中已知空间 '%s'", ks_name)

    result.scenes_detected = scenes_text_list

    # 空间功能子区域（scene_zones）动态探测算子
    ZONE_FEATURE_PATTERNS = [
        re.compile(
            r"(?:站在|坐在|倚在|靠在|躲在|走向|走入|步入|进入|冲到|冲向|跑向|退到|位于|爬出|爬入|钻出|跌落在|跌落到|倒在|落在|踏上|踏入|推开|守在|贴在|穿过|从|在|来到|停在)\s*"
            r"([^\s，。！？、（）：“”\"\'\n\r]{2,14}?"
            r"(?:门前|窗边|落地窗前|阳台|走廊|楼梯口|楼梯|铁梯|玄关|吧台|办公桌|控制台|操作台|沙发旁|沙发|卫生间|病床前|病床|茶几旁|茶几|书架前|书架|角落|隔断后|隔断|主位|展柜前|展柜|高台|审讯桌前|审讯桌|通风口|保险箱前|保险箱|天台边缘|天台|管道|托盘|穹顶大门|穹顶|观测室|储藏区|储藏室|冷藏区|操作区|控制室|配电室|配电柜|走道|通道|机房|平台|大门|窗台|大厅|前台|机位|库区))"
            r"(?:[中内里上下]|的)?"
        ),
    ]
    scene_zones_detected_map: dict[str, list[str]] = {}
    for idx, sc in enumerate(scenes):
        sc_loc = sc.get("location", "")
        # 如果有多个场景标头，切分各场景对应专属文本段，避免子区域跨场景串扰
        if header_matches and idx < len(header_matches):
            sec_start = header_matches[idx].end()
            sec_end = header_matches[idx + 1].start() if idx + 1 < len(header_matches) else len(screenplay_text)
            sc_text = screenplay_text[sec_start:sec_end]
        else:
            sc_text = screenplay_text

        found_zones: list[str] = []
        for pat in ZONE_FEATURE_PATTERNS:
            for zm in pat.finditer(sc_text):
                z_raw = zm.group(1).strip()
                # 去除前缀修饰语
                z_name = re.sub(r"^(?:生锈的|破旧的|厚重的|冰冷的|狭窄的|昏暗的|巨大的|铁制|木制|石制)", "", z_raw).strip() or z_raw
                if z_name and z_name not in found_zones and z_name != sc_loc and z_name not in sc_loc:
                    found_zones.append(z_name)
        if found_zones:
            scene_zones_detected_map[sc_loc] = found_zones[:4]
            clean_sc_loc = re.split(r"\s*[-—–｜|]\s*", sc_loc)[0].strip()
            if clean_sc_loc and clean_sc_loc != sc_loc:
                scene_zones_detected_map[clean_sc_loc] = found_zones[:4]
            logger.debug("【特征扫描·空间子区域】场景 '%s' 动态探测到子功能机位区域: %s", sc_loc, found_zones[:4])
    result.scene_zones_detected = scene_zones_detected_map

    # 光影气候提取 (算子 B)
    LIGHTING_KEYWORDS = ["夜", "雨", "暴雨", "闪电", "顶光", "日", "夕阳", "黄昏", "昏暗", "明亮", "阴天", "雾", "冷调", "暗调", "手电筒", "强光"]
    result.lighting_conditions = sorted(list(set(l for l in LIGHTING_KEYWORDS if l in screenplay_text)))

    # -------------------------------------------------------------------------
    # 步骤 2：逐行扫描角色、动作行与对白 (算子 A1, A2, A3, A4, A5, D)
    # -------------------------------------------------------------------------
    lines = [ln.strip() for ln in screenplay_text.splitlines() if ln.strip()]
    detected_chars: set[str] = set()
    dialogues_per_char: dict[str, list[dict[str, str]]] = {}
    action_lines: list[str] = []

    dialogue_line_pattern = re.compile(
        r"^([\u4e00-\u9fa5A-Za-z0-9·]{2,8})\s*(?:[（(]([^）)]*)[）)])?\s*[：:]\s*(?:[（(]([^）)]*)[）)])?\s*[“\"]?([^”\"\n]+)[”\"]?"
    )
    known_char_names_set = set(char_map.keys()) | set(alias_map.keys()) | set(alias_map.values())

    for line in lines:
        if header_pattern.search(line) and "场景" in line:
            continue
        # 跳过以方括号/中括号/动作三角符开头的声学指令、舞台提示与动作行（如 [声学行为: ...]、△ ...）
        if line.startswith(("[", "【", "△", "▲", "（", "(", "#", "*")):
            action_lines.append(line)
            for name in list(char_map.keys()):
                if name in line:
                    canonical = alias_map.get(name, name)
                    detected_chars.add(canonical)
                    if name != canonical:
                        result.character_alias_map[name] = canonical
                        logger.debug("【特征扫描·别名消歧】动作行别名 '%s' 规范化映射为标准角色名 [%s]", name, canonical)
            continue

        dlg_match = dialogue_line_pattern.match(line)
        if dlg_match:
            raw_speaker = dlg_match.group(1).strip()
            # 实体别名规范化消歧 (NER Alias Normalization)
            speaker_name = alias_map.get(raw_speaker, raw_speaker)
            if not is_valid_character_speaker(speaker_name, known_names=known_char_names_set):
                logger.debug("【特征扫描·非角色过滤】忽略非具名角色/舞台指令前缀: '%s' (原行: %s)", raw_speaker, line[:40])
                action_lines.append(line)
                continue
            if raw_speaker != speaker_name:
                result.character_alias_map[raw_speaker] = speaker_name
                logger.info("【特征扫描·别名消歧】对白说话人别名 '%s' 规范化映射为标准角色名 [%s]", raw_speaker, speaker_name)

            # 对白动态发现的新角色自动注册进 char_map 与性别字典
            if speaker_name not in char_map:
                char_map[speaker_name] = f"CHAR_{_slugify_chinese(speaker_name)}"
                known_char_names_set.add(speaker_name)
                logger.debug(
                    "【特征扫描·新角色动态注册】从对白行发现新角色 '%s' -> 分配资产代号 [%s]",
                    speaker_name, char_map[speaker_name],
                )
            if speaker_name not in char_gender_map:
                char_gender_map[speaker_name] = "female" if any(tk in speaker_name for tk in FEMALE_NAME_TOKENS) else "male"

            bracket = (dlg_match.group(2) or dlg_match.group(3) or "").strip()
            speech = dlg_match.group(4) or ""
            detected_chars.add(speaker_name)
            if speaker_name not in dialogues_per_char:
                dialogues_per_char[speaker_name] = []
            dialogues_per_char[speaker_name].append({
                "bracket": bracket,
                "speech": speech,
            })
            continue

        # 普通动作行：匹配已知角色池（含 Stage 2 传入角色、别名及本集对白已动态注册的新角色）
        action_lines.append(line)
        # 常见非在场、回忆、心理活动、道具媒介等虚拟语境关键词
        NON_PRESENT_PATTERNS = [
            "想起", "想到了", "回想起", "回忆起", "脑海中浮现", "记忆中", "梦见",
            "提起", "谈及", "听说", "听闻", "转述",
            "照片", "画像", "肖像", "遗像", "照片里", "画像上", "雕像", "墓碑",
            "留下的", "留给", "寄来的", "写着", "信笺", "信件", "短信", "绝笔",
            "如同", "好似", "宛如", "宛若", "仿佛是",
        ]
        for name in list(char_map.keys()):
            if name in line:
                # 检查该句子是否属于“仅提及/回忆/画像”等非在场虚拟语境
                # 如果该行包含非在场提示，且角色名字处于回忆/媒介关键词附近，或行中没有角色自身的直接物理动作动词
                is_virtual_mention = any(pat in line for pat in NON_PRESENT_PATTERNS)
                if is_virtual_mention:
                    # 进一步验证：是否仅仅是被提起/在回忆中出现
                    # 若该行没有任何直接物理位移动词或行首主语特征，则视为非在场提及
                    if not re.search(rf"(?:^|[，。！？；\s]){re.escape(name)}\s*(?:走|跑|冲|拔|拿|握|站|坐|看|望|转|推|拉|挥|刺|砍|倒|扑|抓|盯|冷笑|咬牙)", line):
                        logger.debug("【特征扫描·非在场过滤】忽略动作行中的回忆/提及/媒介角色: '%s' (原行: %s)", name, line[:40])
                        continue

                # 验证是否为真实出场：支持说话人、显式动作动词、以及声学生理在场（如脚步声、逼视、按住、立在...）
                canonical = alias_map.get(name, name)
                if canonical not in char_map:
                    char_map[canonical] = f"CHAR_{_slugify_chinese(canonical)}"
                if canonical not in char_gender_map:
                    char_gender_map[canonical] = "female" if any(tk in canonical for tk in FEMALE_NAME_TOKENS) else "male"
                detected_chars.add(canonical)
                if name != canonical:
                    result.character_alias_map[name] = canonical
                    logger.debug("【特征扫描·别名消歧】动作行别名 '%s' 规范化映射为标准角色名 [%s]", name, canonical)

    result.characters_detected = sorted(list(detected_chars))
    logger.debug("【特征扫描·角色汇总】本集共识别出场角色 %d 名: %s", len(result.characters_detected), result.characters_detected)

    # 情绪、伤残与微距逆向提取 (算子 A)
    EMOTION_KEYWORDS = ["绝望", "愤怒", "冷笑", "讥讽", "咬牙", "紧绷", "悲痛", "恐惧", "战栗", "冷静", "沉痛", "惊慌", "发狂", "狂喜"]
    INJURY_KEYWORDS_SENT = ["额角", "额", "鲜血", "血", "伤", "淤青", "流血", "骨折", "伤痕", "割伤", "创伤", "渗出", "红肿", "撕裂", "血痕"]
    MACRO_KEYWORDS = ["手", "指", "手背", "青筋", "握紧", "攥", "眼", "眼眶", "瞳孔", "眼神", "嘴角", "咬唇", "牙齿", "脖颈", "喉结", "血丝"]

    sentences = re.split(r"[。！？\n；!?;]", screenplay_text)
    emotions_map: dict[str, list[str]] = {c: [] for c in result.characters_detected}
    injuries_map: dict[str, list[str]] = {c: [] for c in result.characters_detected}
    macro_map: dict[str, list[str]] = {c: [] for c in result.characters_detected}
    # 【核心改造】按角色隔离专属动作句上下文（含直接提及、别名命中、以及代词“他/她”共指消解归属的句子）
    char_scoped_sentences: dict[str, list[str]] = {c: [] for c in result.characters_detected}

    # 1. 抓取对白括注中的微表情与情绪，并将括注动作并入该角色的专属上下文
    for char_name in result.characters_detected:
        for dlg in dialogues_per_char.get(char_name, []):
            brk = dlg.get("bracket", "")
            if brk:
                char_scoped_sentences[char_name].append(brk)
            for em in EMOTION_KEYWORDS:
                if em in brk and em not in emotions_map[char_name]:
                    emotions_map[char_name].append(em)

    # 2. 上下文滑动状态机：支持代词共指消解 (Pronoun Coreference Resolution) 与单角色动作句精准绑定
    last_mentioned_male: str | None = None
    last_mentioned_female: str | None = None
    last_mentioned_char: str | None = None
    active_speaker: str | None = None

    for raw_sent in sentences:
        sent = raw_sent.strip()
        if not sent:
            continue

        # 检查是否为对白行前导（更新说话人与性别焦点）
        dlg_match = dialogue_line_pattern.match(sent)
        if dlg_match:
            raw_spk = dlg_match.group(1).strip()
            spk = alias_map.get(raw_spk, raw_spk)
            if is_valid_character_speaker(spk, known_names=known_char_names_set):
                active_speaker = spk
                last_mentioned_char = spk
                if char_gender_map.get(spk) == "female":
                    last_mentioned_female = spk
                else:
                    last_mentioned_male = spk

        # 识别句子中直接提及的角色（含别名消歧）
        target_chars_in_sent: set[str] = set()
        for c_name in result.characters_detected:
            if c_name in sent:
                target_chars_in_sent.add(c_name)
                last_mentioned_char = c_name
                if char_gender_map.get(c_name) == "female":
                    last_mentioned_female = c_name
                else:
                    last_mentioned_male = c_name

        for alias_k, canon_v in alias_map.items():
            if alias_k in sent and canon_v in result.characters_detected:
                target_chars_in_sent.add(canon_v)
                last_mentioned_char = canon_v
                if char_gender_map.get(canon_v) == "female":
                    last_mentioned_female = canon_v
                else:
                    last_mentioned_male = canon_v

        # 代词共指消解：女性代词 "她"
        if "她" in sent and not any(char_gender_map.get(c) == "female" for c in target_chars_in_sent):
            resolved_female: str | None = None
            strategy = ""
            if last_mentioned_female:
                resolved_female = last_mentioned_female
                strategy = "last_mentioned_female"
            elif active_speaker and char_gender_map.get(active_speaker) == "female":
                resolved_female = active_speaker
                strategy = "active_speaker_female"
            else:
                females = [c for c in result.characters_detected if char_gender_map.get(c) == "female"]
                if females:
                    resolved_female = females[0]
                    strategy = "first_detected_female"
                elif last_mentioned_char:
                    resolved_female = last_mentioned_char
                    strategy = "last_mentioned_fallback"

            if resolved_female:
                target_chars_in_sent.add(resolved_female)
                result.coreference_resolutions.append({
                    "sentence": sent[:40],
                    "pronoun": "她",
                    "resolved_character": resolved_female,
                    "strategy": strategy,
                })
                logger.info(
                    "【特征扫描·共指消解】句子 '%s...' 中代词 [她] 成功绑定至角色 [%s] (策略: %s)",
                    sent[:30], resolved_female, strategy,
                )

        # 代词共指消解：男性代词 "他"
        if "他" in sent and not any(char_gender_map.get(c) == "male" for c in target_chars_in_sent):
            resolved_male: str | None = None
            strategy = ""
            if last_mentioned_male:
                resolved_male = last_mentioned_male
                strategy = "last_mentioned_male"
            elif active_speaker and char_gender_map.get(active_speaker) == "male":
                resolved_male = active_speaker
                strategy = "active_speaker_male"
            else:
                males = [c for c in result.characters_detected if char_gender_map.get(c) == "male"]
                if males:
                    resolved_male = males[0]
                    strategy = "first_detected_male"
                elif last_mentioned_char:
                    resolved_male = last_mentioned_char
                    strategy = "last_mentioned_fallback"

            if resolved_male:
                target_chars_in_sent.add(resolved_male)
                result.coreference_resolutions.append({
                    "sentence": sent[:40],
                    "pronoun": "他",
                    "resolved_character": resolved_male,
                    "strategy": strategy,
                })
                logger.info(
                    "【特征扫描·共指消解】句子 '%s...' 中代词 [他] 成功绑定至角色 [%s] (策略: %s)",
                    sent[:30], resolved_male, strategy,
                )

        # 若无显式人名且无代词，但属于紧随最近提及角色的连续无主分句（如“手指紧扣，掐出指甲血痕”）
        if not target_chars_in_sent and last_mentioned_char and not header_pattern.search(sent):
            if any(w in sent for w in (
                VIEW_FRONT_KEYWORDS + VIEW_PROFILE_KEYWORDS + VIEW_3Q_KEYWORDS + VIEW_BACK_KEYWORDS
                + LIGHT_FLASH_KEYWORDS + LIGHT_LOWKEY_KEYWORDS
                + MACRO_HAND_KEYWORDS + MACRO_EYE_KEYWORDS + MACRO_MOUTH_KEYWORDS + INJURY_KEYWORDS
            )):
                target_chars_in_sent.add(last_mentioned_char)
                logger.debug(
                    "【特征扫描·零代词承接】无主语动作分句 '%s...' 自动承接上一焦点角色 [%s]",
                    sent[:25], last_mentioned_char,
                )

        # 3. 将本句记录到目标角色的专属动作上下文，并精准赋权情绪、伤残、微距属性
        for char_name in target_chars_in_sent:
            if char_name not in char_scoped_sentences:
                char_scoped_sentences[char_name] = []
            char_scoped_sentences[char_name].append(sent)

            if char_name not in emotions_map:
                emotions_map[char_name] = []
            if char_name not in injuries_map:
                injuries_map[char_name] = []
            if char_name not in macro_map:
                macro_map[char_name] = []

            for em in EMOTION_KEYWORDS:
                if em in sent and em not in emotions_map[char_name]:
                    emotions_map[char_name].append(em)
            for inj in INJURY_KEYWORDS_SENT:
                if inj in sent and inj not in injuries_map[char_name]:
                    injuries_map[char_name].append(inj)
            for mac in MACRO_KEYWORDS:
                if mac in sent and mac not in macro_map[char_name]:
                    macro_map[char_name].append(mac)

    result.emotions_detected = emotions_map
    result.injuries_detected = injuries_map
    result.macro_details = macro_map

    # 算子 D: 母音频抓取与演员需求
    voice_actors: dict[str, Any] = {}
    for speaker_name, dlgs in dialogues_per_char.items():
        voice_actors[speaker_name] = {
            "sample_lines": [d["speech"] for d in dlgs if d.get("speech")],
            "timbre_hint": dlgs[0].get("bracket") or "沉稳",
        }
    result.voice_actors_needed = voice_actors

    # -------------------------------------------------------------------------
    # 步骤 3：角色资产推导 (算子 A1 ~ A5, D) —— 基于单角色专属动作作用域 (char_scoped_text)
    # 彻底消除原先使用全局 full_action_text 导致 A 角色流血/侧脸污染全场所有角色的串味问题！
    # -------------------------------------------------------------------------
    full_action_text = " ".join(action_lines)

    for char_name in result.characters_detected:
        char_base = char_map.get(char_name, f"CHAR_{_slugify_chinese(char_name)}")
        if not char_base.startswith("CHAR_"):
            char_base = f"CHAR_{char_base}"
        char_tier = char_tier_map.get(char_name, char_tier_map.get(char_base, "HERO"))

        # 仅拼接归属该角色本人的句子集合（若该角色仅出现在名单而无专属句，退化为空串并给保底正面视角）
        scoped_sents = char_scoped_sentences.get(char_name) or []
        char_action_text = " ".join(scoped_sents)
        logger.debug(
            "【特征扫描·角色算子A】角色 [%s] (%s, Tier=%s) 专属动作句数=%d, 聚合文本='%s'",
            char_name, char_base, char_tier, len(scoped_sents), char_action_text[:80],
        )

        has_any_view = False
        # 四视角（严格基于角色专属动作上下文判定）
        if any(w in char_action_text for w in VIEW_FRONT_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_FRONT"
            add_or_reuse(aid, "character_view", f"角色【{char_name}】动作行命中正面视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, front view of {char_name} --style raw")
            has_any_view = True

        if any(w in char_action_text for w in VIEW_PROFILE_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_PROFILE"
            add_or_reuse(aid, "character_view", f"角色【{char_name}】动作行命中侧脸视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, side profile view of {char_name} --style raw")
            has_any_view = True

        if any(w in char_action_text for w in VIEW_3Q_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_3Q"
            add_or_reuse(aid, "character_view", f"角色【{char_name}】动作行命中3/4视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, 3/4 view of {char_name} --style raw")
            has_any_view = True

        if any(w in char_action_text for w in VIEW_BACK_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_BACK"
            add_or_reuse(aid, "character_view", f"角色【{char_name}】动作行命中背对视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, back view of {char_name} --style raw")
            has_any_view = True

        # 若角色在本集已出场但未显式写出视角方位词，默认补齐正面基准立绘以保障 Stage 7 图生视频有据可依
        if not has_any_view:
            aid = f"{char_base}_{char_tier}_VIEW_FRONT"
            add_or_reuse(aid, "character_view", f"角色【{char_name}】本集出场默认正面基准视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, front view of {char_name} --style raw")
            logger.debug("【特征扫描·角色算子A】角色 [%s] 未显式命中方位词，自动补齐默认视角 [%s]", char_name, aid)

        # 光感（严格基于角色专属动作上下文判定）
        if any(w in char_action_text for w in LIGHT_FLASH_KEYWORDS):
            aid = f"{char_base}_{char_tier}_LIGHT_FLASH"
            add_or_reuse(aid, "character_light", f"角色【{char_name}】动作行命中强光照脸/手电筒", "relighting",
                         image_prompt=f"{default_style}, direct harsh flashlight on {char_name} --style raw")

        if any(w in char_action_text for w in LIGHT_LOWKEY_KEYWORDS):
            aid = f"{char_base}_{char_tier}_LIGHT_LOWKEY"
            add_or_reuse(aid, "character_light", f"角色【{char_name}】动作行命中暗调/频闪", "relighting",
                         image_prompt=f"{default_style}, moody low key rim light on {char_name} --style raw")

        # 微距与伤残（严格基于角色专属动作上下文判定）
        if any(w in char_action_text for w in MACRO_HAND_KEYWORDS):
            aid = f"{char_base}_{char_tier}_MACRO_HAND"
            add_or_reuse(aid, "character_macro", f"角色【{char_name}】动作行命中手部特写微距", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, extreme close-up of {char_name}'s hands --style raw")

        if any(w in char_action_text for w in MACRO_MOUTH_KEYWORDS):
            aid = f"{char_base}_{char_tier}_MACRO_MOUTH"
            add_or_reuse(aid, "character_macro", f"角色【{char_name}】动作行命中嘴角/咬唇特写微距", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, close-up lips of {char_name} --style raw")

        if any(w in char_action_text for w in MACRO_EYE_KEYWORDS):
            aid = f"{char_base}_{char_tier}_MACRO_EYE"
            add_or_reuse(aid, "character_macro", f"角色【{char_name}】动作行命中眼眶/眼神特写微距", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, extreme close-up eyes of {char_name} --style raw")

        if any(w in char_action_text for w in INJURY_KEYWORDS):
            aid = f"{char_base}_{char_tier}_DAMAGE_BLOOD"
            add_or_reuse(aid, "character_injury", f"角色【{char_name}】动作行命中淤青/流血/撕裂创伤", "inpainting_local_edit",
                         image_prompt=f"{default_style}, injured {char_name} with bleeding and bruises --style raw")

        # 算子 D: 母音频抓取
        if char_name in dialogues_per_char and dialogues_per_char[char_name]:
            first_dlg = dialogues_per_char[char_name][0]
            clean_name = char_base.replace("CHAR_", "")
            voice_id = f"VOICE_{clean_name}_MASTER"
            bracket_desc = first_dlg["bracket"] or "自然沉稳"
            tts_prompt = f"音色气质：{bracket_desc}，真实人声微表情，沉浸低压感"
            result.new_character_master_voice_cards.append(
                MasterVoiceCardRecord(
                    character_id=char_base,
                    master_voice_id=voice_id,
                    script_monologue_source=first_dlg["speech"],
                    master_tts_prompt=tts_prompt,
                    voice_file_path=f"voices/{voice_id}.wav",
                )
            )

    # -------------------------------------------------------------------------
    # 步骤 4：场景资产生成 (算子 B)
    # -------------------------------------------------------------------------
    for sc in scenes:
        env_aid = sc["env_id"]
        add_or_reuse(env_aid, "environment_primary", f"场景 {sc['location']} 空间标头", "text_to_image",
                     image_prompt=f"{default_style}, wide shot of {sc['location']} --style raw")

    # -------------------------------------------------------------------------
    # 步骤 5：道具资产推导 (算子 C) —— 三级动态实体对齐 + 单道具同句形变隔离判定
    # 1. 第一级：Stage 3 known_props（含全称与核心词干脱敏匹配，如“《绝密之局》涉案加密暗账本” -> “暗账本”）；
    # 2. 第二级：从 Stage 2 known_characters 自动汇入角色随身锚点道具（carried_anchor_item / anchor_props）；
    # 3. 第三级：仅当上游未传入 known_props 时，基于题材包自适应词表与通用动宾短语提取，绝不注入无关剧目的幽灵道具。
    # -------------------------------------------------------------------------
    genre_hero_props = genre_pack.get_hero_prop_keywords() if genre_pack else []
    genre_anchor_props = genre_pack.get_anchor_prop_keywords() if genre_pack else []
    genre_verbs = genre_pack.get_deformation_verbs() if genre_pack else []

    active_hero_props = list(dict.fromkeys(genre_hero_props + HERO_PROP_KEYWORDS))
    active_anchor_props = list(dict.fromkeys(genre_anchor_props + ANCHOR_PROP_KEYWORDS))
    active_deformation_verbs = sorted(set(genre_verbs + DEFORMATION_VERBS), key=len, reverse=True)

    hero_prop_items: list[tuple[str, str, str]] = []  # (prop_id, name, tier)
    props_detected_list: list[str] = []
    deformed_props_map: dict[str, list[str]] = {}

    # 组装结构化候选道具表（保持顺序与去重）
    structured_prop_candidates: list[dict[str, str]] = []
    seen_prop_names: set[str] = set()

    if known_props:
        for kp in known_props:
            if isinstance(kp, dict):
                kp_name = str(kp.get("name") or kp.get("prop_name") or "").strip()
                kp_id = str(kp.get("prop_id") or f"PROP_{_slugify_chinese(kp_name)}").strip()
                kp_tier = str(kp.get("tier") or "T1").strip()
            else:
                kp_name = str(kp).strip()
                kp_id = f"PROP_{_slugify_chinese(kp_name)}"
                kp_tier = "T1"
            if kp_name and kp_name not in seen_prop_names:
                seen_prop_names.add(kp_name)
                structured_prop_candidates.append({
                    "prop_id": kp_id if kp_id.startswith("PROP_") else f"PROP_{kp_id}",
                    "name": kp_name,
                    "tier": kp_tier,
                })

    # 汇入 Stage 2 角色随身锚点道具 (Tier 2)
    for char_anchor in _extract_anchor_props_from_characters(known_characters):
        ap_name = char_anchor["name"]
        if ap_name not in seen_prop_names:
            seen_prop_names.add(ap_name)
            structured_prop_candidates.append(char_anchor)

    # 汇入基于剧本动作行动宾短语与物理实体形态动态抽取的道具 (全新动态发现，打破静态枚举)
    dynamic_props = _extract_dynamic_props_from_screenplay(
        screenplay_text,
        known_character_names=set(detected_chars),
        known_scene_names=set(scenes_text_list),
    )
    for dp in dynamic_props:
        dp_name = dp["name"]
        if dp_name not in seen_prop_names:
            seen_prop_names.add(dp_name)
            structured_prop_candidates.append(dp)
            logger.debug("【特征扫描·候选道具汇入】动态物证加入候选池: '%s' (%s)", dp_name, dp["prop_id"])

    # 若上游未提供任何已知道具且未动态抽取出道具，则使用题材自适应高频道具词表作为候选兜底
    if not structured_prop_candidates:
        for hp in active_hero_props:
            if hp not in seen_prop_names:
                seen_prop_names.add(hp)
                structured_prop_candidates.append({
                    "prop_id": f"PROP_{_slugify_chinese(hp)}",
                    "name": hp,
                    "tier": "T1",
                })
        for ap in active_anchor_props:
            if ap not in seen_prop_names:
                seen_prop_names.add(ap)
                structured_prop_candidates.append({
                    "prop_id": f"PROP_{_slugify_chinese(ap)}",
                    "name": ap,
                    "tier": "T2",
                })

    for cand in structured_prop_candidates:
        p_name = cand["name"]
        p_id = cand.get("prop_id") or f"PROP_{_slugify_chinese(p_name)}"
        p_tier = cand.get("tier") or "T1"

        # 使用全称或核心名词词干检查该道具是否在本集剧本正文中出现
        if _entity_matches_text(p_name, screenplay_text):
            props_detected_list.append(p_name)
            hero_prop_items.append((p_id, p_name, p_tier))

            # 严格在提及该道具（或其核心词干）的同句范围内检查是否命中形变破坏动词
            verbs_found: set[str] = set()
            for sent in sentences:
                if _entity_matches_text(p_name, sent):
                    for v in active_deformation_verbs:
                        if v in sent:
                            verbs_found.add(v)
            if verbs_found:
                deformed_props_map[p_name] = sorted(list(verbs_found))
                logger.debug(
                    "【特征扫描·道具形变C2】道具 '%s' (%s) 在同句中命中破坏动词 %s -> 触发 ACTION 破坏态",
                    p_name, p_id, deformed_props_map[p_name],
                )
            else:
                logger.debug(
                    "【特征扫描·道具静态C1】道具 '%s' (%s) 在本集出场且未发生形变破坏",
                    p_name, p_id,
                )

    result.props_detected = sorted(props_detected_list)
    result.deformed_props = deformed_props_map

    for p_id, p_name, p_tier in hero_prop_items:
        # 针对该道具检查所在句子或上下文是否命中形变破坏动词
        prop_has_deformation = bool(deformed_props_map.get(p_name))

        # 如果命中破坏动词，必须生成 ACTION 破坏态
        if prop_has_deformation:
            action_aid = f"{p_id}_{p_tier}_ACTION"
            add_or_reuse(action_aid, "prop_action", f"道具【{p_name}】命中破坏动词，触发破坏态", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, damaged broken {p_name} --style raw")
        else:
            static_aid = f"{p_id}_{p_tier}_STATIC"
            add_or_reuse(static_aid, "prop_static", f"道具【{p_name}】静态初始态", "text_to_image",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, close-up of {p_name} --style raw")

    # 装配 episode_resource_manifest
    result.episode_resource_manifest = {
        "characters": {"all": [a.asset_id for a in result.newly_generated_assets if a.asset_id.startswith("CHAR_")]},
        "environments": {"all": [s["env_id"] for s in scenes]},
        "props": {"all": [p[0] for p in hero_prop_items]},
        "audio": {"master_voices": [v.master_voice_id for v in result.new_character_master_voice_cards]},
    }
    return result


class ScreenplayFeatureScanner:
    """剧本多维特征逆向扫描识别类门面。"""
    scan = staticmethod(scan_screenplay_features)

