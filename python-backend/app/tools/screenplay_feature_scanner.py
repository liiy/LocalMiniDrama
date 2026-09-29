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
from typing import Any, Literal

logger = logging.getLogger("lmd.screenplay_feature_scanner")

# =========================================================================
# 【规则编号: RULE-V-S6-02 词表库】动词库与特征词常量
# =========================================================================

VIEW_FRONT_KEYWORDS = ["正面", "抬头", "直视", "走近", "迎面", "站立"]
VIEW_PROFILE_KEYWORDS = ["侧脸", "转头", "避开目光", "侧目", "向侧", "倚靠"]
VIEW_3Q_KEYWORDS = ["斜视", "侧身", "3/4", "回眸", "半侧"]
VIEW_BACK_KEYWORDS = ["背对", "背影", "转身离去", "后背", "远去"]

LIGHT_FLASH_KEYWORDS = ["手电筒直射", "强光照脸", "闪光"]
LIGHT_LOWKEY_KEYWORDS = ["阴暗", "侧逆光", "硬阴影", "月光", "烛光", "惨绿频闪"]

MACRO_HAND_KEYWORDS = ["手指", "掐掌心", "拉扯线头", "握住", "拿打火机", "指甲划过", "掐出指甲血痕", "掐指", "手背", "手腕"]
MACRO_EYE_KEYWORDS = ["眼眶", "眼角", "瞳孔", "血丝", "眼神"]
MACRO_MOUTH_KEYWORDS = ["嘴角", "咬唇", "皲裂起皮", "咬紧", "后槽牙"]
INJURY_KEYWORDS = ["淤青", "流血", "夹伤", "撕裂", "湿透", "骨折", "挫伤", "血痕", "干结盐水泥斑", "伤口"]

ENV_WIDE_KEYWORDS = ["远景", "全貌", "俯瞰", "大楼", "大门", "进站", "全景", "街头横幅"]
ENV_INSERT_KEYWORDS = ["水龙头滴水", "挂钟秒针", "电表箱", "特写空镜", "15W节能灯", "频闪"]

HERO_PROP_KEYWORDS = ["血信", "日记", "安全帽", "确认书", "病历", "合同", "录音笔", "药盒", "打火机"]
DEFORMATION_VERBS = ["撕", "砸", "切", "断", "烧", "挑开", "崩碎", "撬开", "撞烂", "撕页", "划破", "扯回"]
ANCHOR_PROP_KEYWORDS = ["打火机", "戒指", "手表", "创可贴", "老铜钥匙", "红绳", "煤油打火机"]
ATMOSPHERIC_PROP_KEYWORDS = ["冷水饺", "茶杯", "螺丝刀", "碗筷", "塑料袋", "纸巾", "白气", "烟雾", "积水"]

PINYIN_LOOKUP = {
    "沈炼": "SHENLIAN",
    "苏晓": "SUXIAO",
    "陆沉": "LUCHEN",
    "苏诚": "SU_CHENG",
    "林夏": "LIN_XIA",
    "林晚": "LINWAN",
    "周衍": "ZHOUYAN",
    "老郑": "LAOZHENG",
    "苏琴": "SUQIN",
    "陈峰": "CHENFENG",
    "赵崇山": "ZHAOCHONGSHAN",
    "烂尾楼": "LANWEILOU",
    "天台": "TIANTAI",
    "车库": "CHEKU",
    "地下车库": "CHEKU",
    "出租屋": "CHUZUWU",
    "火车站": "STATION",
    "扳道房": "BANDAOFANG",
    "血信": "XUEXIN",
    "安全帽": "ANQUANMAO",
    "日记": "RIJI",
    "合同": "HETONG",
    "打火机": "DAHUOJI",
    "手术刀": "DAGGER",
    "生锈的手术刀": "DAGGER",
}


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
        }


def _slugify_chinese(text: str) -> str:
    """将常见中文词汇转换为大写英文标识。"""
    for ch, py in PINYIN_LOOKUP.items():
        if ch in text:
            return py
    clean = re.sub(r"[^\w]", "", text).upper()
    return clean or "UNKNOWN"


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
    **kwargs: Any,
) -> ScreenplayScanResult:
    """【规则编号: RULE-V-S6-02】执行剧本多维特征逆向扫描识别引擎。"""
    logger.debug("[RULE-V-S6-02] Starting deterministic screenplay feature scan.")

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

    # 建立角色映射
    char_map: dict[str, str] = dict(PINYIN_LOOKUP)
    char_tier_map: dict[str, str] = {}
    if character_id_map:
        char_map.update(character_id_map)
    if known_characters:
        for c in known_characters:
            name = c.get("name")
            cid = c.get("character_id")
            tier = c.get("tier", "HERO")
            if name and cid:
                char_map[name] = cid
                char_tier_map[name] = tier
                char_tier_map[cid] = tier

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
    # 步骤 1：解析场景标头 (算子 B1)
    # -------------------------------------------------------------------------
    # 步骤 1：解析场景标头 (算子 B1)
    # -------------------------------------------------------------------------
    header_pattern = re.compile(
        r"[【\[]?\s*场景\s*(\d+)?[：:\s]*([^\n】\]]*)[】\]]?\s*([^\n]*)"
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
        for tw in ["夜", "日", "黄昏", "清晨", "暴雨", "雨"]:
            if tw in location_raw:
                time_weather = tw
                break

        slug_loc = ""
        if "15号" in location and "烂尾楼" in location and "天台" in location:
            slug_loc = "15HAO_LANWEILOU_TIANTAI"
        elif "烂尾楼" in location and "天台" in location:
            slug_loc = "LANWEILOU_TIANTAI"
        elif "扳道房" in location or "火车站" in location:
            slug_loc = "STATION"
        elif "车库" in location:
            slug_loc = "CHEKU"
        elif "出租屋" in location:
            slug_loc = "CHUZUWU"
        elif "天台" in location:
            slug_loc = "TIANTAI"
        else:
            slug_loc = _slugify_chinese(location)

        env_id = f"ENV_{slug_loc}_T1"
        scenes.append({
            "env_id": env_id,
            "scene_number": int(num_str) if num_str.isdigit() else idx,
            "location": location,
            "time_of_day": time_weather,
            "full_header": match.group(0),
        })
        scenes_text_list.append(location_raw)

    if known_environments:
        for ks in known_environments:
            ks_name = ks.get("name", "") if isinstance(ks, dict) else str(ks)
            if ks_name and (ks_name in screenplay_text) and (ks_name not in scenes_text_list):
                scenes_text_list.append(ks_name)

    result.scenes_detected = scenes_text_list

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
        r"^([^：:\(（\s]{2,8})\s*(?:[（(]([^）)]*)[）)])?\s*[：:]\s*(?:[（(]([^）)]*)[）)])?\s*[“\"]?([^”\"\n]+)[”\"]?"
    )

    for line in lines:
        if header_pattern.search(line) and "场景" in line:
            continue

        dlg_match = dialogue_line_pattern.match(line)
        if dlg_match:
            speaker_name = dlg_match.group(1).strip()
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

        # 动作行
        action_lines.append(line)
        for name in char_map:
            if name in line:
                detected_chars.add(name)

    result.characters_detected = sorted(list(detected_chars))

    # 情绪、伤残与微距逆向提取 (算子 A)
    EMOTION_KEYWORDS = ["绝望", "愤怒", "冷笑", "讥讽", "咬牙", "紧绷", "悲痛", "恐惧", "战栗", "冷静", "沉痛", "惊慌", "发狂", "狂喜"]
    INJURY_KEYWORDS = ["额角", "额", "鲜血", "血", "伤", "淤青", "流血", "骨折", "伤痕", "割伤", "创伤", "渗出", "红肿"]
    MACRO_KEYWORDS = ["手", "指", "手背", "青筋", "握紧", "攥", "眼", "眼眶", "瞳孔", "眼神", "嘴角", "咬唇", "牙齿", "脖颈", "喉结"]

    sentences = re.split(r"[。！？\n；!?;]", screenplay_text)
    emotions_map: dict[str, list[str]] = {}
    injuries_map: dict[str, list[str]] = {}
    macro_map: dict[str, list[str]] = {}

    for char_name in result.characters_detected:
        emotions_map[char_name] = []
        injuries_map[char_name] = []
        macro_map[char_name] = []

        for dlg in dialogues_per_char.get(char_name, []):
            brk = dlg.get("bracket", "")
            for em in EMOTION_KEYWORDS:
                if em in brk and em not in emotions_map[char_name]:
                    emotions_map[char_name].append(em)

        for sent in sentences:
            if (char_name in sent) or ("他" in sent and char_name == result.characters_detected[0]) or ("她" in sent and char_name == result.characters_detected[0]):
                for em in EMOTION_KEYWORDS:
                    if em in sent and em not in emotions_map[char_name]:
                        emotions_map[char_name].append(em)
                for inj in INJURY_KEYWORDS:
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
    # 步骤 3：角色资产推导 (算子 A1 ~ A5, D)
    # -------------------------------------------------------------------------
    full_action_text = " ".join(action_lines)

    for char_name in result.characters_detected:
        char_base = char_map.get(char_name, f"CHAR_{_slugify_chinese(char_name)}")
        if not char_base.startswith("CHAR_"):
            char_base = f"CHAR_{char_base}"
        char_tier = char_tier_map.get(char_name, char_tier_map.get(char_base, "HERO"))

        # 四视角
        if any(w in full_action_text for w in VIEW_FRONT_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_FRONT"
            add_or_reuse(aid, "character_view", "动作行命中正面视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, front view of {char_name} --style raw")

        if any(w in full_action_text for w in VIEW_PROFILE_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_PROFILE"
            add_or_reuse(aid, "character_view", "动作行命中侧脸视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, side profile view of {char_name} --style raw")

        if any(w in full_action_text for w in VIEW_3Q_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_3Q"
            add_or_reuse(aid, "character_view", "动作行命中3/4视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, 3/4 view of {char_name} --style raw")

        if any(w in full_action_text for w in VIEW_BACK_KEYWORDS):
            aid = f"{char_base}_{char_tier}_VIEW_BACK"
            add_or_reuse(aid, "character_view", "动作行命中背对视角", "image_to_image_pose",
                         image_prompt=f"{default_style}, back view of {char_name} --style raw")

        # 光感
        if any(w in full_action_text for w in LIGHT_FLASH_KEYWORDS):
            aid = f"{char_base}_{char_tier}_LIGHT_FLASH"
            add_or_reuse(aid, "character_light", "动作行命中强光照脸/手电筒", "relighting",
                         image_prompt=f"{default_style}, direct harsh flashlight on {char_name} --style raw")

        if any(w in full_action_text for w in LIGHT_LOWKEY_KEYWORDS):
            aid = f"{char_base}_{char_tier}_LIGHT_LOWKEY"
            add_or_reuse(aid, "character_light", "动作行命中暗调/频闪", "relighting",
                         image_prompt=f"{default_style}, moody low key rim light on {char_name} --style raw")

        # 微距与伤残
        if any(w in full_action_text for w in MACRO_HAND_KEYWORDS):
            aid = f"{char_base}_{char_tier}_MACRO_HAND"
            add_or_reuse(aid, "character_macro", "动作行命中手部特写微距", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, extreme close-up of {char_name}'s hands --style raw")

        if any(w in full_action_text for w in MACRO_MOUTH_KEYWORDS):
            aid = f"{char_base}_{char_tier}_MACRO_MOUTH"
            add_or_reuse(aid, "character_macro", "动作行命中嘴角/咬唇特写微距", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, close-up lips of {char_name} --style raw")

        if any(w in full_action_text for w in MACRO_EYE_KEYWORDS):
            aid = f"{char_base}_{char_tier}_MACRO_EYE"
            add_or_reuse(aid, "character_macro", "动作行命中眼眶/眼神特写微距", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, extreme close-up eyes of {char_name} --style raw")

        if any(w in full_action_text for w in INJURY_KEYWORDS):
            aid = f"{char_base}_{char_tier}_DAMAGE_BLOOD"
            add_or_reuse(aid, "character_injury", "动作行命中淤青/流血/撕裂创伤", "inpainting_local_edit",
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
    # 步骤 5：道具资产推导 (算子 C)
    # -------------------------------------------------------------------------
    hero_prop_items: list[tuple[str, str, str]] = []  # (prop_id, name, tier)
    props_detected_list: list[str] = []
    deformed_props_map: dict[str, list[str]] = {}

    all_prop_candidates = set()
    if known_props:
        for kp in known_props:
            kp_name = kp.get("name", "") if isinstance(kp, dict) else str(kp)
            if kp_name:
                all_prop_candidates.add(kp_name)
    for hp in HERO_PROP_KEYWORDS + ANCHOR_PROP_KEYWORDS:
        all_prop_candidates.add(hp)

    for p_name in all_prop_candidates:
        norm_p = p_name.replace("的", "")
        if p_name in screenplay_text or norm_p in screenplay_text:
            props_detected_list.append(p_name)
            verbs_found = set()
            for sent in sentences:
                if p_name in sent or norm_p in sent or any(tk in sent for tk in ["手术刀", "门锁", "铁门"] if tk in p_name):
                    for v in DEFORMATION_VERBS:
                        if v in sent:
                            verbs_found.add(v)
            if verbs_found:
                deformed_props_map[p_name] = sorted(list(verbs_found))

    result.props_detected = sorted(props_detected_list)
    result.deformed_props = deformed_props_map

    if known_props:
        for kp in known_props:
            p_name = kp.get("name", "")
            p_id = kp.get("prop_id", f"PROP_{_slugify_chinese(p_name)}")
            p_tier = kp.get("tier", "T1")
            norm_p = p_name.replace("的", "")
            if p_name and (p_name in full_action_text or p_name in screenplay_text or norm_p in screenplay_text):
                hero_prop_items.append((p_id, p_name, p_tier))
    else:
        for p_name in HERO_PROP_KEYWORDS:
            norm_p = p_name.replace("的", "")
            if p_name in full_action_text or p_name in screenplay_text or norm_p in screenplay_text:
                slug_p = _slugify_chinese(p_name)
                hero_prop_items.append((f"PROP_{slug_p}", p_name, "T1"))

    for p_id, p_name, p_tier in hero_prop_items:
        # 针对该道具检查所在句子或上下文是否命中形变破坏动词
        prop_has_deformation = bool(deformed_props_map.get(p_name))

        # 如果命中破坏动词，必须生成 ACTION 破坏态
        if prop_has_deformation:
            action_aid = f"{p_id}_{p_tier}_ACTION"
            add_or_reuse(action_aid, "prop_action", f"道具【{p_name}】命中破坏动词，触发破坏态", "inpainting_local_edit",
                         aspect_ratio="1:1", image_prompt=f"{default_style}, damaged broken {p_name} --style raw")
        else:
            static_aid = f"{p_id}_{p_tier}"
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

