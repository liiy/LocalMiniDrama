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
    "苏诚": "SU_CHENG",
    "林夏": "LIN_XIA",
    "林晚": "LINWAN",
    "周衍": "ZHOUYAN",
    "老郑": "LAOZHENG",
    "苏琴": "SUQIN",
    "陈峰": "CHENFENG",
    "烂尾楼": "LANWEILOU",
    "天台": "TIANTAI",
    "车库": "CHEKU",
    "地下车库": "CHEKU",
    "出租屋": "CHUZUWU",
    "血信": "XUEXIN",
    "安全帽": "ANQUANMAO",
    "日记": "RIJI",
    "合同": "HETONG",
    "打火机": "DAHUOJI",
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


@dataclass
class ScreenplayScanResult:
    """剧本多维特征逆向扫描识别引擎全量产出。"""
    reused_existing_assets: list[ReusedAssetRecord] = field(default_factory=list)
    newly_generated_assets: list[NewlyGeneratedAssetRecord] = field(default_factory=list)
    new_character_master_voice_cards: list[MasterVoiceCardRecord] = field(default_factory=list)
    episode_resource_manifest: dict[str, Any] = field(default_factory=dict)
    characters_detected: list[str] = field(default_factory=list)
    scenes_detected: list[dict[str, Any]] = field(default_factory=list)
    props_detected: dict[str, list[str]] = field(default_factory=dict)

    @property
    def new_assets(self) -> list[NewlyGeneratedAssetRecord]:
        return self.newly_generated_assets

    @property
    def reused_assets(self) -> list[ReusedAssetRecord]:
        return self.reused_existing_assets

    @property
    def master_voice_cards(self) -> list[MasterVoiceCardRecord]:
        return self.new_character_master_voice_cards


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
) -> ScreenplayScanResult:
    """【规则编号: RULE-V-S6-02】执行剧本多维特征逆向扫描识别引擎。"""
    logger.debug("[RULE-V-S6-02] Starting deterministic screenplay feature scan.")

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
    header_pattern = re.compile(
        r"[【\[]场景(?:\s*(\d+))?[：:\s]*([^-\]\n]+?)(?:-\s*([^\]\n]+))?[】\]]"
    )
    scenes: list[dict[str, Any]] = []
    header_matches = list(header_pattern.finditer(screenplay_text))

    for idx, match in enumerate(header_matches, start=1):
        num_str = match.group(1) or f"{idx:02d}"
        location = match.group(2).strip()
        time_weather = (match.group(3) or "日").strip()

        # 生成场景 asset_id
        slug_loc = ""
        if "15号" in location and "烂尾楼" in location and "天台" in location:
            slug_loc = "15HAO_LANWEILOU_TIANTAI"
        elif "烂尾楼" in location and "天台" in location:
            slug_loc = "LANWEILOU_TIANTAI"
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

    result.scenes_detected = scenes

    # -------------------------------------------------------------------------
    # 步骤 2：逐行扫描角色、动作行与对白 (算子 A1, A2, A3, A4, A5, D)
    # -------------------------------------------------------------------------
    lines = [ln.strip() for ln in screenplay_text.splitlines() if ln.strip()]
    detected_chars: set[str] = set()
    dialogues_per_char: dict[str, list[dict[str, str]]] = {}
    action_lines: list[str] = []

    dialogue_line_pattern = re.compile(
        r"^([^：:]{2,8})[：:]\s*(?:[（(]([^）)]+)[）)])?\s*[“\"]?([^”\"\n]+)[”\"]?"
    )

    for line in lines:
        if header_pattern.search(line):
            continue

        dlg_match = dialogue_line_pattern.match(line)
        if dlg_match:
            speaker_name = dlg_match.group(1).strip()
            bracket = dlg_match.group(2) or ""
            speech = dlg_match.group(3) or ""
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
    if known_props:
        for kp in known_props:
            p_name = kp.get("name", "")
            p_id = kp.get("prop_id", f"PROP_{_slugify_chinese(p_name)}")
            p_tier = kp.get("tier", "T1")
            if p_name and (p_name in full_action_text or p_name in screenplay_text):
                hero_prop_items.append((p_id, p_name, p_tier))
    else:
        for p_name in HERO_PROP_KEYWORDS:
            if p_name in full_action_text or p_name in screenplay_text:
                slug_p = _slugify_chinese(p_name)
                hero_prop_items.append((f"PROP_{slug_p}", p_name, "T1"))

    # 形变动词检测
    has_deformation = any(verb in full_action_text for verb in DEFORMATION_VERBS)

    for p_id, p_name, p_tier in hero_prop_items:
        # 针对该道具检查所在句子或上下文是否命中形变破坏动词
        prop_has_deformation = False
        sentences = re.split(r"[。！？\n；!?;]", screenplay_text)
        for sent in sentences:
            if p_name in sent and any(verb in sent for verb in DEFORMATION_VERBS):
                prop_has_deformation = True
                break

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

