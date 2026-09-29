"""LangGraph 短剧工业化创作状态数据契约 (Drama Script State Schema)。

基于《短剧剧本·全流程工业化创作提示词（升级增强版）》工业化标准设计，
支撑多智能体状态机流转、连续性追踪、五阶质检与 Human-in-the-Loop 中断恢复。
"""
from __future__ import annotations

import operator
from typing import Any, Literal, Annotated, TypedDict
from pydantic import BaseModel, Field, ConfigDict, model_validator


class ProjectProfile(BaseModel):
    """阶段一：项目基础信息档案。"""
    mode: Literal["mode_a_prestige", "mode_b_commercial"] = Field(
        default="mode_b_commercial",
        description="创作模式：mode_a_prestige(精品正剧/悬疑/情感) / mode_b_commercial(爆款商业/爽感/付费转化)"
    )
    title: str = Field(default="", description="暂定剧名")
    alt_titles: list[str] = Field(default_factory=list, description="10个爆款备选剧名")
    genre: str = Field(default="都市爽剧", description="剧本类型（如：甜宠/虐恋/悬疑/复仇/逆袭/都市等）")
    target_audience: str = Field(default="下沉市场主流受众/年轻网文读者", description="目标受众群体画像")
    drama_format: Literal["micro_drama", "commercial_standard", "prestige_mini"] = Field(
        default="commercial_standard",
        description="剧本体量：微短剧 / 爆款短剧(80-100集) / 精品短剧(20-30集)"
    )
    episode_count: int = Field(default=80, ge=1, le=200, description="总集数")
    duration_per_ep: int = Field(default=90, ge=30, le=300, description="单集时长（秒：60s / 90s / 120s 竖屏标准）")
    distribution_platform: str = Field(default="抖音/快手/微信小程序/红果", description="发布适配平台与分发策略")
    commercial_points: list[str] = Field(default_factory=list, description="商业化投流核心卖点（爽点、虐点、反转点、极速打脸点）")
    one_sentence_story: str = Field(default="", description="一句话爆款故事（30字以内封面级简介）")
    core_theme: str = Field(default="", description="核心主题（人性/抉择/救赎/谎言/复仇/成长等）")
    overall_tone: str = Field(default="爽感", description="整体基调（治愈/压抑/爽感/甜虐/冷峻/温情/暗黑/写实）")
    paywall_episodes: list[int] = Field(default_factory=lambda: [10, 15, 20, 25], description="关键付费卡点集数规划")
    ending_type: str = Field(default="苦尽甘来/逆袭圆满", description="结局类型（圆满/苦尽甘来/开放式/反转/救赎）")
    content_limits: dict[str, list[str]] = Field(
        default_factory=lambda: {"allowed": [], "forbidden": ["过度血腥", "违背公序良俗", "封建迷信"]},
        description="内容尺度限制"
    )
    age_rating: str = Field(default="全年龄", description="年龄分级（全年龄/青少年/成人不露骨）")


class HighConcept(BaseModel):
    """阶段一：核心创意与高概念设定。"""
    one_sentence_hook: str = Field(default="", description="一句话高概念设定（差异化核心钩子）")
    core_contradiction: str = Field(default="", description="贯穿全剧核心矛盾（可持续驱动每集剧情）")
    protagonist_inner_conflict: dict[str, str] = Field(
        default_factory=lambda: {"surface_desire": "", "deep_need": ""},
        description="主角「表层想要（欲望）」VS「深层需要（成长）」内在冲突"
    )
    failure_cost: str = Field(default="", description="主角失败的具象可感知代价（生存危机/名誉扫地/失去挚爱等）")
    unique_selling_points: list[str] = Field(default_factory=list, description="3-5 个差异化爆款卖点")
    opening_3s_hook: str = Field(default="", description="开篇 3 秒强钩子事件")
    surface_illusion_vs_truth: dict[str, str] = Field(
        default_factory=lambda: {"illusion": "", "truth": ""},
        description="表层剧情假象 + 底层隐藏真相（多层反转架构）"
    )
    ultimate_question: str = Field(default="", description="全剧终极拷问（用于结局升华）")
    core_symbol_token: str = Field(default="", description="贯穿全剧核心信物/象征物（首尾闭环呼应）")
    three_layer_conflicts: dict[str, str] = Field(
        default_factory=lambda: {"external": "", "interpersonal": "", "internal": ""},
        description="三层冲突架构（外部冲突、人际冲突、内心冲突）"
    )


class WorldviewProfile(BaseModel):
    """阶段二：轻量化短剧世界观设计（拍摄降本适配）。"""
    model_config = ConfigDict(extra="allow")
    era_and_location: str = Field(default="", description="时代背景与地域环境")
    core_main_scenes: list[str] = Field(default_factory=list, description="3-5 个核心主场景（严控拍摄成本）")
    primary_scenes: list[str] = Field(default_factory=list, description="主场景列表")
    social_structure: str = Field(default="", description="社会结构、阶层关系与对立势力")
    core_rules_and_taboos: list[str] = Field(default_factory=list, description="世界核心规则、人情逻辑、行业禁忌")
    core_rules: list[str] = Field(default_factory=list, description="核心规则列表")
    rule_violation_cost: str = Field(default="", description="违反规则会付出的现实代价")


class GrowthChainItem(BaseModel):
    """主角错误认知成长链节点。"""
    stage_name: str = Field(default="", description="阶段名称")
    belief: str = Field(default="", description="认知信念状态")
    trigger_event: str = Field(default="", description="关键冲击事件")
    choice_made: str = Field(default="", description="做出的抉择与代价")


# =========================================================================
# 阶段 2：微观生物骨相 DNA、真实生活质感服化道、心理四元组与双轨关系模型
# =========================================================================

class BiologicalPortraitDNA(BaseModel):
    """阶段 2：微观生物肖像与骨相 DNA（防塑料假脸与跨集漂移的绝对锚点）。
    
    【工业规范】为阶段 6 单项生图提供 100% 明确的骨相与材质输入，严禁现场脑补：
    1. 脸型与骨骼架构：高颧骨/方正下颌/面部折叠度/下巴紧绷感（杜绝整容模板假脸）；
    2. 真实皮肤物理质地：干性/油性真实毛孔分布、眼周细微干纹、皮下毛细血管微泛红反应；
    3. 永久面部坐标瑕疵：精确到毫米级的痣/疤痕坐标（如：右嘴角上方 0.5cm 浅褐色小痣、鼻梁骨性轻微驼峰、脸颊暗红日晒斑）；
    4. 眼唇解剖特征：窄内双/单眼皮眼褶深度、巩膜微血丝分布、瞳孔暗棕色微光、嘴唇常年缺水细小皲裂起皮；
    5. 发型与发质：发际线高度、低马尾/凌乱发型、两鬓冷雨打湿碎发、干枯毛躁微带静电等质感。
    """
    model_config = ConfigDict(extra="allow")
    bone_structure: str = Field(default="", description="脸型与骨骼架构（高颧骨/方正下颌/面部折叠度/紧绷感）")
    skin_texture: str = Field(default="", description="真实皮肤物理质地（真实毛孔分布、眼周干纹、毛细血管微泛红）")
    permanent_blemish_dna: str = Field(default="", description="永久面部坐标瑕疵（毫米级痣/疤痕坐标/骨性驼峰/日晒斑）")
    eye_lip_features: str = Field(default="", description="眼唇解剖特征（内双/单眼皮眼褶、巩膜血丝、瞳孔微光、嘴唇皲裂起皮）")
    hair_spec: str = Field(default="", description="发型与发质（发际线、低马尾/凌乱发型、打湿碎发、毛躁静电质感）")


class LivedInCostumeSpecs(BaseModel):
    """阶段 2：从头到脚真实生活质感服化道代码 (Lived-in Texture & Fabric Specs - 拒绝崭新塑料布)。
    
    【工业规范】作为阶段 5 动作发音描写与阶段 6 生图编译的绝对基准：
    1. 外披面料与穿着痕迹：具体面料材质参数（如重磅粗花呢克重 600g/m²、双面羊绒、洗褪色耐磨卡其布）、手肘自然折痕、纽扣松脱线头长度（如第二颗纽扣线头松脱2cm）、下摆干涸泥斑；
    2. 内搭细节：粗棒针针织纹理、领口松弛起球形变与波浪状磨损、领圈内侧汗渍硬壳感；
    3. 下装与鞋履：裤腿直筒水磨白印、工装皮靴/千层底布鞋皮面开裂擦痕、鞋跟磨偏与鞋带起毛；
    4. 随身饰品与固有锚定物：随身佩戴的不可变物品（如发绳、素圈细银戒划痕、包带金属扣氧化绿锈、特定磨砂打火机）。
    """
    model_config = ConfigDict(extra="allow")
    outerwear: str = Field(default="", description="外披面料与穿着痕迹（面料材质克重、手肘折痕、纽扣松脱线头长度、下摆干涸泥斑）")
    innerwear: str = Field(default="", description="内搭细节（粗棒针针织纹理、领口松弛起球形变、领圈汗渍硬壳感）")
    bottoms_and_shoes: str = Field(default="", description="下装与鞋履（裤腿水磨白印、鞋面开裂擦痕、鞋跟磨偏与鞋带起毛）")
    accessories_anchors: str = Field(default="", description="随身饰品与固有锚定物（发绳、素圈银戒划痕、包带金属扣氧化绿锈、特定打火机）")


class PsychologicalQuadruple(BaseModel):
    """阶段 2：角色心理动力学四元组 (Psychological Quadruple)。
    
    1. Want (外在欲望)：表层欲望与想要达成的直接目标；
    2. Need (内在救赎)：深层真实需要与必须直面的成长真相；
    3. The Lie (致命谎言)：深信不疑的防御机制谎言；
    4. The Ghost (创伤原罪)：心理创伤源与童年/过去的伤痛幽灵。
    """
    model_config = ConfigDict(extra="allow")
    want: str = Field(default="", description="Want: 表层欲望与直接目标")
    need: str = Field(default="", description="Need: 深层成长需要与直面的真相")
    lie: str = Field(default="", description="The Lie: 坚信不疑的致命谎言/防御机制")
    ghost: str = Field(default="", description="The Ghost: 心理创伤源/过去的幽灵原罪")


class VoiceBehavioralFingerprint(BaseModel):
    """阶段 2：语言与行为指纹 (Voice & Behavioral Fingerprint)。
    
    1. catchphrase: 核心口头禅（带人物背景烙印）；
    2. defensive_phrase: 防御性口头用语（被刺痛时下意识的反击词）；
    3. forbidden_words: 绝对禁词（绝不会说出的词，体现心理雷区）；
    4. stress_action: 焦虑应激生理动作（如用力摩挲大拇指指甲边缘、咬下唇侧内肉）。
    """
    model_config = ConfigDict(extra="allow")
    catchphrase: str = Field(default="", description="特征口头禅（带人物背景烙印）")
    defensive_phrase: str = Field(default="", description="防御性口头用语（被刺痛时下意识的反击词）")
    forbidden_words: list[str] = Field(default_factory=list, description="绝对禁词（绝不会说出的词，体现心理雷区）")
    stress_action: str = Field(default="", description="焦虑应激生理动作（如：用力摩挲大拇指指甲边缘、咬下唇侧内肉）")


class CarriedAnchorItem(BaseModel):
    """阶段 2：随身旧物/物理锚定物 (Carried Anchor Item)。
    
    陪伴多年的具体旧物，具备精确物理磨损刻痕，承载深层情感象征与创伤回忆。
    """
    model_config = ConfigDict(extra="allow")
    item_name: str = Field(default="", description="随身旧物名称")
    physical_trace: str = Field(default="", description="具体物理磨损/刻痕/瑕疵细节")
    emotional_significance: str = Field(default="", description="背后的情感象征与创伤信物意义")


class DualTrackRelationshipItem(BaseModel):
    """阶段 2：全剧利益与情感双轨关系网络矩阵单项 (Dual-Track Relationship Matrix)。
    
    揭示角色对之间的表面社会身份、深层情感羁绊、生死利益死结与共同生活旧情物证。
    """
    model_config = ConfigDict(extra="allow")
    character_pair: str = Field(default="", description="角色对 (如: 陆沉 vs 韩泰)")
    surface_identity: str = Field(default="", description="表面社会身份关系 (如: 调查组长 vs 慈善巨贾)")
    deep_bond: str = Field(default="", description="深层情感牵绊 (爱/恨/负罪/眷恋)")
    fatal_conflict: str = Field(default="", description="生死利益死结 (不可调和的冲突爆发点)")
    shared_past_token: str = Field(default="", description="共同生活旧情物证 (旧情密码，如: 红塔山烟盒、白糖发糕、老铜钥匙)")
    danger_level: str = Field(default="极度危险", description="动态危险系数 (极度危险/毁灭级反转点/利益共谋铁笼)")


class CharacterRelationshipItem(BaseModel):
    """阶段二：结构化角色动态关系矩阵单项（对齐 character_relationship 数据表）。"""
    model_config = ConfigDict(extra="allow")
    character_a_code: str = Field(default="", description="主体角色编码（CHAR_XXX）")
    character_b_code: str = Field(default="", description="客体角色编码（CHAR_XXX）")
    character_a_name: str = Field(default="", description="主体角色姓名")
    character_b_name: str = Field(default="", description="客体角色姓名")
    social_label: str = Field(default="", description="表层社会关系标签，如：师徒/死敌/假夫妻")
    tension_index: int = Field(default=50, description="关系张力指数（0-100）")
    drama_function: Literal["catalyst", "obstacle", "mirror", "anchor"] | str = Field(
        default="catalyst",
        description="戏剧功能：catalyst(催化剂)/obstacle(阻碍者)/mirror(镜像对比)/anchor(情感锚点)"
    )
    shared_history_props: dict[str, Any] | list[Any] | str = Field(
        default_factory=dict,
        description="共享历史与纽带道具（如 key_item, shared_memory）"
    )
    information_gap: dict[str, Any] | str = Field(
        default_factory=dict,
        description="关键信息差说明（如 a_knows, b_knows, fatal_secret）"
    )
    knows_truth_initially: bool = Field(default=False, description="A 是否在初始阶段就知晓真相")
    current_belief: str = Field(default="", description="A 当前深信不疑的假象或认知")
    reveal_condition: str = Field(default="", description="真相被揭露的触发条件/集数节点")
    can_defect: bool = Field(default=False, description="是否具备倒戈/阵营背叛倾向")
    defect_condition: str = Field(default="", description="触发倒戈的极限压力或利益阈值")
    swing_point: dict[str, Any] | list[Any] | str = Field(
        default_factory=dict,
        description="关系转折点与催化事件（如 catalyst_event, point_of_no_return）"
    )
    raw: dict[str, Any] | None = Field(default=None, description="大模型输出的原始关系定义 JSON")

    @model_validator(mode="before")
    @classmethod
    def _hydrate_relationship_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        
        # 兼容角色编码和名称
        if not data.get("character_a_code"):
            data["character_a_code"] = data.get("character_a") or ""
        if not data.get("character_b_code"):
            data["character_b_code"] = data.get("character_b") or ""
        if not data.get("character_a_name"):
            data["character_a_name"] = data.get("character_a") or ""
        if not data.get("character_b_name"):
            data["character_b_name"] = data.get("character_b") or ""

        # 兼容社会标签/表层关系
        if not data.get("social_label"):
            data["social_label"] = (
                data.get("surface_relation")
                or data.get("surface_identity")
                or data.get("relationship")
                or data.get("relation")
                or ""
            )

        # 兼容戏剧功能
        df = data.get("drama_function")
        if df:
            df_str = str(df).lower()
            if "catalyst" in df_str or "催化" in df_str:
                data["drama_function"] = "catalyst"
            elif "obstacle" in df_str or "阻碍" in df_str:
                data["drama_function"] = "obstacle"
            elif "mirror" in df_str or "镜像" in df_str:
                data["drama_function"] = "mirror"
            elif "anchor" in df_str or "锚点" in df_str:
                data["drama_function"] = "anchor"

        # 兼容信息差提取
        raw_gap = data.get("information_gap")
        if isinstance(raw_gap, dict):
            if "knows_truth_initially" in raw_gap and "knows_truth_initially" not in data:
                data["knows_truth_initially"] = bool(raw_gap.get("knows_truth_initially"))
            if "current_belief" in raw_gap and "current_belief" not in data:
                data["current_belief"] = str(raw_gap.get("current_belief") or "")
            if "reveal_condition" in raw_gap and "reveal_condition" not in data:
                data["reveal_condition"] = str(raw_gap.get("reveal_condition") or "")

        # 兼容反水点提取
        raw_swing = data.get("swing_point")
        if isinstance(raw_swing, dict):
            if "can_defect" in raw_swing and "can_defect" not in data:
                data["can_defect"] = bool(raw_swing.get("can_defect"))
            if "defect_condition" in raw_swing and "defect_condition" not in data:
                data["defect_condition"] = str(raw_swing.get("defect_condition") or "")

        return data


class EmotionalArcTrajectory(BaseModel):
    """阶段 2：核心角色全季动态情感流转线路图 (Emotional Arc Trajectory)。
    
    分阶段跟踪角色心理防御机制崩解与救赎历程：
    - 阶段 A: 防御与伪装期 (0%~25%) - 谎言支配/防备所有人
    - 阶段 B: 怀疑与裂痕期 (25%~50%) - 利益死结撞击/爆发激烈对峙
    - 阶段 C: 深渊与自剖期 (50%~75%) - 绝境降临/谎言崩解痛哭自剖
    - 阶段 D: 超越与悲壮和解期 (75%~100%) - 精神救赎/生死和解
    """
    model_config = ConfigDict(extra="allow")
    character_name: str = Field(default="", description="角色姓名")
    stage_a_masked: str = Field(default="", description="阶段 A: 防御与伪装期 (0%~25%) - 谎言支配/防备所有人")
    stage_b_fracture: str = Field(default="", description="阶段 B: 怀疑与裂痕期 (25%~50%) - 利益死结撞击/对峙")
    stage_c_abyss: str = Field(default="", description="阶段 C: 深渊与自剖期 (50%~75%) - 绝境降临/谎言崩解痛哭")
    stage_d_catharsis: str = Field(default="", description="阶段 D: 超越与悲壮和解期 (75%~100%) - 精神救赎/生死和解")


class CharacterProfile(BaseModel):
    """阶段二：标准化全息人物档案（对齐提示词与 characters 数据表）。"""
    model_config = ConfigDict(extra="allow")
    name: str = Field(..., description="人物姓名")
    character_code: str = Field(default="", description="角色唯一编码，如 CHAR_LUOCHENG，跨集绑定依据")
    role_type: Literal["protagonist", "antagonist", "supporter", "witness", "swing"] | str = Field(
        default="supporter",
        description="角色定位（protagonist/antagonist/supporter/witness/swing）"
    )
    gender: Literal["male", "female", "other", "unknown"] | str = Field(
        default="unknown",
        description="性别（male/female/other/unknown）"
    )
    perceived_age: int | None = Field(default=None, description="视觉感知年龄（纯整数，用于排卡与控图）")
    description: str = Field(default="", description="角色背景与隐藏身份设定")
    personality: str = Field(default="", description="性格特征与行为动机")
    appearance: str = Field(default="", description="外貌特征与服装风格")
    visual_consistency_code: str = Field(default="", description="视觉一致性特征代码（五官/发型/体型/固定服饰描述）")
    psychology_4: dict[str, Any] | str = Field(
        default_factory=dict,
        description="四维心理画像 JSON（core_desire/fear_taboo/flaw_blindspot/behavior_pattern）"
    )
    acoustic_persona: dict[str, Any] | str = Field(
        default_factory=dict,
        description="听觉画像与台词潜台词风格 JSON（speech_rhythm/catchphrase/tone/subtext_pattern）"
    )
    voice_fingerprint: VoiceBehavioralFingerprint | str | None = Field(
        default="",
        description="声音指纹描述（音色/声线特征）"
    )
    carried_anchor_item: CarriedAnchorItem | dict[str, Any] | str | None = Field(
        default="",
        description="随身锚点道具设定（随身携带的标志性物品）"
    )
    drama_engine: str | dict[str, Any] = Field(
        default="",
        description="戏剧推动引擎设定（角色在主线中的戏剧驱动力）"
    )
    
    # 兼容历史与扩展字段
    identity_and_mask: str = Field(default="", description="表面身份与隐藏马甲")
    visual_anchor: str = Field(default="", description="外貌记忆点与视觉特征")
    surface_desire: str = Field(default="", description="表层目标/核心欲望")
    deep_need: str = Field(default="", description="深层执念/内在需求")
    flaw: str = Field(default="", description="致命缺陷与性格盲点")
    secret: str = Field(default="", description="隐藏秘密与过往创伤")
    biological_dna: BiologicalPortraitDNA | None = Field(
        default=None,
        description="微观生物肖像与骨相 DNA（骨骼/皮肤毛孔/毫米级瑕疵/眼唇解剖/发质）"
    )
    lived_in_costume: LivedInCostumeSpecs | None = Field(
        default=None,
        description="从头到脚真实生活质感服化道代码（外披/内搭/下装鞋履/饰品做旧）"
    )
    psychological_quad: PsychologicalQuadruple | None = Field(
        default=None,
        description="心理动力学四元组 (Want/Need/Lie/Ghost)"
    )
    emotional_arc: EmotionalArcTrajectory | None = Field(
        default=None,
        description="四阶段全季情感流转弧"
    )
    voice_profile: dict[str, str] = Field(
        default_factory=lambda: {"speed": "标准", "catchphrase": "", "tone": "利落"},
        description="声音画像（语速、句式、口头禅、语气习惯）"
    )
    growth_chain: list[GrowthChainItem] = Field(default_factory=list, description="错误认知成长链")
    current_status: dict[str, Any] = Field(
        default_factory=lambda: {"health": "良好", "wealth": "普通", "mask_exposure": "0%"},
        description="运行时实时动态状态（伤势/财富/马甲暴露度）"
    )


class ClueItem(BaseModel):
    """阶段二：伏笔、悬念与反转追踪项。"""
    clue_id: str = Field(..., description="伏笔唯一标识，如 CLUE_001")
    clue_type: Literal["short_term", "mid_term", "long_term"] = Field(
        default="short_term",
        description="伏笔分类：short_term(1-3集回收), mid_term(单元卡点回收), long_term(高潮/大结局回收)"
    )
    plant_ep: int = Field(..., description="首次埋设集数")
    reinforce_eps: list[int] = Field(default_factory=list, description="中途强化集数列表")
    resolve_ep: int = Field(..., description="计划回收集数")
    surface_meaning: str = Field(default="", description="表层含义")
    hidden_truth: str = Field(default="", description="真实含义")
    misdirection: str = Field(default="", description="误导方向")
    resolve_method: str = Field(default="", description="回收方式与视听呈现")
    impact_on_plot: str = Field(default="", description="对剧情与人物的影响")
    status: Literal["pending", "active", "resolved"] = Field(default="pending", description="伏笔流转状态")


class ContinuityMemo(BaseModel):
    """运行时连续性备忘录（每5集/每集动态维护）。"""
    character_states: dict[str, dict[str, Any]] = Field(default_factory=dict, description="角色动态状态表")
    prop_traces: dict[str, str] = Field(default_factory=dict, description="关键道具与核心信物流向（道具名 -> 当前持有人）")
    information_gap_matrix: list[dict[str, Any]] = Field(
        default_factory=list,
        description="角色间信息差矩阵（谁已知什么 / 谁以为谁不知道什么）"
    )
    unresolved_crises: list[str] = Field(default_factory=list, description="未解决核心危机与倒计时")


class EpisodeOutlineItem(BaseModel):
    """阶段三：分集大纲条目。"""
    episode_num: int = Field(..., description="集数序号")
    title: str = Field(default="", description="单集爆款标题")
    commercial_tag: Literal["free_hook", "ad_clip", "paywall_climax", "regular"] = Field(
        default="regular",
        description="商业定位标签：free_hook(免费引流), ad_clip(投流切片), paywall_climax(黄金付费卡点), regular(常规推进)"
    )
    main_scene: str = Field(default="", description="主要场景（日/夜 内/外）")
    core_action: str = Field(default="", description="核心事件与视听动作")
    core_resistance: str = Field(default="", description="核心阻力与冲突升级")
    information_disclosure: str = Field(default="", description="信息披露与秘密揭示")
    relationship_change: str = Field(default="", description="人物关系变化")
    clue_operations: list[str] = Field(default_factory=list, description="新增或回收伏笔标识")
    episode_twist: str = Field(default="", description="本集反转点")
    ending_cliffhanger: str = Field(default="", description="片尾定格与悬念钩子")
    duration_seconds: int = Field(default=90, description="单集时长秒数")


class SingleSceneCheck(BaseModel):
    """单场戏内部构思质检项。"""
    viewpoint_char: str = Field(default="", description="视角人物")
    current_goal: str = Field(default="", description="当下具体目标")
    resistance: str = Field(default="", description="阻碍对象与手段")
    countermeasure: str = Field(default="", description="采取的反制手段")
    opening_emotion: str = Field(default="", description="开场情绪状态")
    ending_emotion_peak: str = Field(default="", description="结尾情绪爆发")
    irreversible_change: str = Field(default="", description="产生的不可逆后果")


class ASTBlockItem(BaseModel):
    """AST 视听正文结构化分块。"""
    block_type: Literal["hook_3s", "actions_and_scenes", "dialogues", "cliffhanger"] = Field(
        ..., description="块类型：前3秒钩子 / 核心动作与场景 / 潜台词对白 / 片尾定格"
    )
    title: str = Field(default="", description="块标题描述")
    content: str = Field(default="", description="分块 Markdown 文本")
    line_start: int = Field(default=0, description="起始行号")
    line_end: int = Field(default=0, description="结束行号")
    defect_identified: str | None = Field(default=None, description="质检识别出的具体缺陷（如有）")
    patch_content: str | None = Field(default=None, description="局部原位修补替换文本（如有）")


class AudioVisualBeat(BaseModel):
    """阶段五剧本视听节拍原子模型（支持下游阶段七分镜与阶段八配音精确解构）。
    
    代表正文按时间轴演进的一条原子视听节拍（对话、动作、环境音效、悬念转折）。
    """
    model_config = ConfigDict(extra="allow")
    beat_id: str = Field(default="", description="节拍唯一编码，如 EP01_B001")
    scene_ref: str = Field(default="", description="归属场景编号或名称")
    beat_type: Literal["dialogue", "action", "hook", "cliffhanger", "foley"] = Field(
        default="action", description="节拍类型：对话/物理动作/钩子/悬念/音效提示"
    )
    speaker: str = Field(default="", description="发言角色名（若为对白节拍）")
    stress_action: str = Field(default="", description="角色的应激肢体微动作（如：死死攥紧衣角、指节泛白）")
    vocal_delivery: str = Field(default="", description="台词发声物理阻力/腔体特色/语气指令（如：齿缝挤出、声带颤抖、压低气音）")
    dialogue_text: str = Field(default="", description="台词纯文本（严格剥离括号与动作说明）")
    physical_action: str = Field(default="", description="纯视觉画面的物理动作描述（无抽象心理描写）")
    interacted_prop: str = Field(default="", description="产生交互的物理道具（如：染血化验单）")
    foley_cue: str = Field(default="", description="伴随的物理音效提示（如：重摔声、玻璃爆裂声）")
    estimated_duration_sec: float = Field(default=2.0, description="该节拍预估视听时长（秒）")


class ScriptAST(BaseModel):
    """单集剧本 AST 结构树。包含历史兼容的4大结构分块及按时间轴严格排序的细粒度视听节拍序列。"""
    episode_num: int = Field(..., description="对应集数")
    blocks: list[ASTBlockItem] = Field(default_factory=list, description="4 个标准结构分块列表（用于历史质检与修补）")
    beats: list[AudioVisualBeat] = Field(default_factory=list, description="按时间轴顺序严格排列的细粒度视听节拍序列")
    raw_markdown: str = Field(default="", description="组装缝合后的完整 Markdown")


class EpisodeScript(BaseModel):
    """阶段四：标准短剧正文交付模型（严格对齐视听排版规范）。"""
    episode_num: int = Field(..., description="集数序号")
    title: str = Field(default="", description="爆款单集标题")
    commercial_tag: str = Field(default="常规推进", description="商业定位（free_hook/ad_clip/paywall_climax/regular）")
    scene_header: str = Field(default="", description="场景标注（如：日 内 顾氏集团顶层总裁办）")
    characters_present: list[str] = Field(default_factory=list, description="本场出场人物列表")
    core_props: list[str] = Field(default_factory=list, description="核心道具/状态")
    hook_3s: str = Field(default="", description="开场特写（前3秒抓人动作与视觉爆点）")
    body_markdown: str = Field(default="", description="正文动作与对白 Markdown 文本")
    ending_cliffhanger: str = Field(default="", description="片尾定格与悬念钩子（含定格画面、音效与字幕悬念）")
    ast_data: ScriptAST | None = Field(default=None, description="AST 结构化分块树")
    single_scene_check: SingleSceneCheck | None = Field(default=None, description="单场戏核对")
    review_summary: dict[str, Any] | None = Field(default=None, description="单集简要复盘")


class QAReport(BaseModel):
    """五阶闭环质检评估报告。"""
    episode_num: int = Field(..., description="评估集数")
    overall_score: int = Field(..., ge=0, le=100, description="综合总评分（满分100，>=85分放行）")
    passed: bool = Field(default=False, description="是否放行通过")
    structure_score: int = Field(default=0, description="1. 结构层得分（前3秒钩子/节奏/付费断章）")
    character_score: int = Field(default=0, description="2. 人物层得分（动机自洽/拒绝降智/反派压迫感）")
    scene_score: int = Field(default=0, description="3. 场景层得分（动作驱动/拒绝水戏/视听化）")
    language_score: int = Field(default=0, description="4. 语言层得分（台词张力/潜台词/口语化）")
    continuity_score: int = Field(default=0, description="5. 连续性得分（道具流向/信息差/伏笔闭环）")
    flaws_identified: list[str] = Field(default_factory=list, description="识别出的核心缺陷清单")
    refine_suggestions: list[str] = Field(default_factory=list, description="定向修改与重写建议")
    target_patch_blocks: list[str] = Field(
        default_factory=list,
        description="需要局部原位修补的 AST 分块类型列表（如 ['dialogues', 'cliffhanger']）"
    )


def merge_worker_results(current: list[Any], new_val: list[Any] | None) -> list[Any]:
    """LangGraph Send 并发结果聚合 Reducer。当为 None 时重置为空列表。"""
    if new_val is None:
        return []
    return (current or []) + (new_val or [])


class LeanDramaScriptState(BaseModel):
    """LangGraph 剧本工业化创作瘦状态机 (Lean State)。
    
    【核心设计原则】
    1. 序列化体积恒定 < 50KB，避免 Checkpoint 快照引起 Redis/MySQL I/O 阻塞；
    2. 仅保留轻量游标、滑动窗口（active_window_episodes 仅保留 3~5 集）与外部持久化引用字典（persisted_episode_refs）；
    3. 全量 80-100 集剧本正文与版本由 MySQL episodes 表外挂承载。
    """
    # 0. 项目标识与协同版本
    drama_id: int = Field(default=0, description="关联短剧项目 ID (dramas.id)")
    version_cursor: int = Field(default=1, description="全局版本游标，用于级联失效控制")
    lock_status: bool = Field(default=False, description="剧本定稿锁定状态（True 则转入只读并触发 Bridge）")

    # 1. 项目基础与高概念
    project: ProjectProfile = Field(default_factory=ProjectProfile, description="立项基础档案")
    high_concept: HighConcept = Field(default_factory=HighConcept, description="核心创意高概念")
    worldview: WorldviewProfile = Field(default_factory=WorldviewProfile, description="3-5个核心主场景世界观")
    
    # 2. 角色与关系
    characters: dict[str, CharacterProfile] = Field(default_factory=dict, description="标准化角色档案库")
    character_relations: list[dict[str, Any]] = Field(default_factory=list, description="人物关系网络与秘密")
    
    # 3. 大纲与节拍
    master_outline: dict[str, Any] = Field(default_factory=dict, description="全书总纲与三次大转折")
    unit_outlines: list[dict[str, Any]] = Field(default_factory=list, description="单元大纲与付费波浪线")
    episode_outlines: dict[int, EpisodeOutlineItem] = Field(default_factory=dict, description="80-100集分集大纲表")
    
    # 4. 伏笔与连续性
    clue_pool: list[ClueItem] = Field(default_factory=list, description="全剧伏笔池（待激活/待回收）")
    continuity_memo: ContinuityMemo = Field(default_factory=ContinuityMemo, description="角色信息差矩阵与道具流向备忘录")
    
    # 5. 正文滑动窗口与外部持久化索引（Lean State 核心）
    current_batch_range: tuple[int, int] = Field(default=(1, 3), description="当前并发处理集数批次范围")
    current_episode_index: int = Field(default=1, description="当前执行游标指针集数")
    batch_worker_results: Annotated[list[Any], merge_worker_results] = Field(
        default_factory=list,
        description="Send API 并发生成临时聚合槽，由 Reducer 合并后在 aggregate 节点置换清空"
    )
    active_window_episodes: dict[int, EpisodeScript] = Field(
        default_factory=dict,
        description="活跃正文滑动窗口：仅保留当前批次（2~3集）的正文对象，完成后置换写入 MySQL"
    )
    persisted_episode_refs: dict[int, int] = Field(
        default_factory=dict,
        description="已持久化历史集数引用索引映射：{episode_num: db_episode_id}"
    )
    qa_summary_scores: dict[int, int] = Field(
        default_factory=dict,
        description="轻量质检分值映射表：{episode_num: 92}"
    )
    
    # 6. 质检与人工干预
    qa_reports: dict[int, QAReport] = Field(
        default_factory=dict,
        description="当前批次活跃质检报告"
    )
    retry_count: int = Field(default=0, description="当前集 AST 局部修补重试计数（<=3次）")
    max_retries: int = Field(default=3, description="单集自动修补上限")
    human_feedback: str | None = Field(default=None, description="HITL 审批人工反馈意见")
    phase_status: Literal[
        "concept_done", "bible_done", "outline_done", "writing_in_progress", "completed", "escalated"
    ] = Field(default="concept_done", description="全局阶段流转状态")


# =========================================================================
# SKILL.md 两程九阶 (Two-Journey Nine-Stage) 工业化增强契约模型
# =========================================================================

class AuditVerdict(str):
    """红蓝对抗自审判定状态。"""
    GREEN_APPROVED = "GREEN_APPROVED"
    GREEN_PASS = "GREEN_PASS"
    BLUE_PASS = "BLUE_PASS"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    YELLOW_WARNING = "YELLOW_WARNING"
    RED_BLOCKING = "RED_BLOCKING"


class RedBlueAuditReport(BaseModel):
    """双重视角独立红蓝对抗自审报告模型 (对齐 SKILL.md)。"""
    blue_team_compliance: dict[str, Any] = Field(
        default_factory=dict,
        description="【蓝军客观合规审查】（客观硬指标：时间轴秒数累加、资产存在性、格式完备、禁令红线）"
    )
    red_team_criticism: dict[str, Any] = Field(
        default_factory=dict,
        description="【红军魔鬼制片人挑刺】（专门挑刺：戏剧张力刺、逻辑硬伤刺、视听落地穿模刺）"
    )
    verdict: str = Field(
        default="GREEN_APPROVED",
        description="综合判定结果：GREEN_APPROVED / YELLOW_WARNING / RED_BLOCKING"
    )
    blocking_issues: list[str] = Field(default_factory=list, description="阻断级硬伤清单（触发状态机就地重构）")
    warning_suggestions: list[str] = Field(default_factory=list, description="警示改进建议（供主创在门控点裁决）")

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    @property
    def blue_checks(self) -> dict[str, Any]:
        return self.blue_team_compliance

    @property
    def red_complaints(self) -> dict[str, Any]:
        return self.red_team_criticism

    @property
    def blocking_reasons(self) -> list[str]:
        return self.blocking_issues

    @property
    def confidence_score(self) -> float:
        return 0.95 if self.verdict == "GREEN_APPROVED" else (0.8 if self.verdict == "YELLOW_WARNING" else 0.5)


class CandidateTitleMatrix(BaseModel):
    """阶段 1：四大商业维度爆款候选片名矩阵。"""
    identity_contrast: list[str] = Field(default_factory=list, description="A. 身份与反常识反差型（极高阶/极底层错位）")
    extreme_suspense: list[str] = Field(default_factory=list, description="B. 极端悬念与夺命钩子型（致命危机/生死倒计时）")
    prop_irony: list[str] = Field(default_factory=list, description="C. 核心物证与阶层讽刺型（生活旧物与社会隐喻）")
    dark_psychology: list[str] = Field(default_factory=list, description="D. 人格黑化与心理反杀型（双面伪装与窒息智斗）")


class DoubleTrackProhibitions(BaseModel):
    """阶段 1：负向双轨禁令清单母集。"""
    forbidden_cliches: list[str] = Field(
        default_factory=lambda: [
            "1. 绝症诊断书误诊或调包",
            "2. 亲子鉴定报告当场撕毁",
            "3. 监听录音笔在关键时刻没电",
            "4. 豪车车祸刚好失忆三年",
            "5. 恶毒配角在走廊大声密谋被路过主角偷听",
            "6. 协议结婚期满当天突然怀孕",
            "7. 隐形富豪在老同学聚会上被看不起最后包场",
            "8. 抢救室门口医生只说'我们尽力了'",
            "9. 绑架案中二选一救白月光还是原配",
            "10. 最后一秒拆炸弹剪红线蓝线"
        ],
        description="10 大绝对禁止俗套情节（过滤因果逻辑硬伤）"
    )
    forbidden_cheap_pleasures: list[str] = Field(
        default_factory=lambda: [
            "1. 毫无代价与前置铺垫的机械降神与无脑打脸",
            "2. 降智反派脸谱化癫狂求饶",
            "3. 纯靠口嗨说教嘴替强行升华正能量"
        ],
        description="3 大绝对禁止廉价爽点（过滤低幼情绪垃圾）"
    )
    persona_redlines: list[str] = Field(
        default_factory=lambda: [
            "1. 严禁主角全知全能、伟光正圣母或龙傲天无脑开挂，必须具备致命性格缺陷(Lie)与创伤幽灵(Ghost)",
            "2. 严禁反派脸谱化纯恶或为了作恶而作恶，必须具备自洽的利益逻辑与道德防御机制",
            "3. 严禁配角沦为无独立欲望的降智工具人或单向嘴替"
        ],
        description="人设禁令清单（防伟光正/防龙傲天/防脸谱化）"
    )


class AudioMotifItem(BaseModel):
    """阶段 4：全剧核心音乐主题动机母库单项 (Leitmotif)。"""
    motif_id: str = Field(..., description="动机 ID，如 LEITMOTIF_01_SUSPENSE")
    leitmotif_id: str = Field(default="", description="标准契约别名")
    name: str = Field(..., description="主题动机名称（如：悬疑压迫与阶层窒息）")
    instrumentation: str = Field(default="", description="核心配器说明")
    tempo_bpm: str = Field(default="86", description="速度区间与节拍")
    musical_key: str = Field(default="D minor", description="调性")
    dramatic_function: str = Field(default="", description="戏剧功能定位与触发场景")

    @model_validator(mode="before")
    @classmethod
    def _coerce_motif_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            m_id = data.get("motif_id") or data.get("leitmotif_id") or ""
            if m_id:
                data["motif_id"] = m_id
                data["leitmotif_id"] = m_id
        return data


class AudioBible(BaseModel):
    """阶段 4 长期资产：全剧音乐动机母库 (04_audio_bible.json)。"""
    leitmotifs: list[AudioMotifItem] = Field(default_factory=list, description="全剧 3 个贯穿始终的具象音乐主题动机")
    leitmotif_registry: list[AudioMotifItem] = Field(default_factory=list, description="标准契约别名")
    foley_rules: dict[str, str] = Field(
        default_factory=lambda: {"boost": "+2.0dB ~ +3.0dB", "clarity": "-23 LUFS"},
        description="拟音放大与混音规范"
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_registry(cls, data: Any) -> Any:
        if isinstance(data, dict):
            motifs = data.get("leitmotif_registry") or data.get("leitmotifs") or []
            data["leitmotifs"] = motifs
            data["leitmotif_registry"] = motifs
        return data

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


class ReusedAssetModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 已核准复用资产模型。"""
    model_config = ConfigDict(extra="allow")

    asset_id: str = Field(..., description="已注册四段式资产ID (如 CHAR_LIN_BASE_PORTRAIT)")
    type: str = Field(default="character_base_identity", description="资产类别标识")
    usage_in_current_ep: str = Field(default="", description="声明该老资产在本集中的具体用途")
    status: str = Field(default="APPROVED", description="核准状态，固定为 APPROVED")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


class NewlyGeneratedAssetModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 增量单项视听资产模型。"""
    model_config = ConfigDict(extra="allow")

    asset_id: str = Field(..., description="四段式标准资产ID (如 CHAR_LIN_4V_FRONT_FULL, PROP_01_ACTION)")
    asset_category: str = Field(
        default="character_tier1_base",
        description="资产分级枚举 (character_tier1_base, character_tier2_performance, character_tier3_special, env_tier1_primary, env_tier2_transitional, prop_tier1_hero等)"
    )
    script_inference_trigger: str = Field(..., description="剧本逆向推理铁证长句，写明触发动作行动词依据")
    generation_method: str = Field(
        default="text_to_image",
        description="生图/生音算法模式 (text_to_image, image_to_image_outpainting, image_to_image_pose, inpainting_local_edit, relighting)"
    )
    input_source_image: str | None = Field(default=None, description="图生图底图来源资产ID，纯文生图填 null")
    identity_reference: str | None = Field(default=None, description="角色肖像身份基准ID，角色图必填")
    denoising_strength: float | None = Field(default=None, description="图生图重绘幅度 (0.30 ~ 0.60)")
    aspect_ratio: str = Field(default="9:16", description="单项素材专用画幅比例 (如 4:5, 1:1, 9:16)")
    image_prompt: str = Field(default="", description="完整英文生图Prompt，带风格介质参数与 --style raw")
    status: str = Field(default="APPROVED", description="新生成并通过审核的资产状态，固定为 APPROVED")

    # 扩展属性，兼容底图依赖与工作流
    parent_asset_id: str | None = Field(default=None, description="父级资产ID")
    recommended_denoise: float | None = Field(default=None, description="推荐重绘幅度")
    workflow_note: str = Field(default="", description="工作流管线说明")
    visual_prompt: str = Field(default="", description="生图Prompt别名")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


class MasterVoiceCardModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 角色母音频卡片模型。"""
    model_config = ConfigDict(extra="allow")

    character_id: str = Field(..., description="角色唯一ID (如 CHAR_LINWAN)")
    master_voice_id: str = Field(..., description="母音频唯一标识 (如 VOICE_LINWAN_MASTER)")
    script_monologue_source: str = Field(default="", description="从文学剧本抓取的灵魂示范台词（含发声括注）")
    master_tts_prompt: str = Field(default="", description="全量跨平台 TTS 提示词")
    voice_file_path: str = Field(default="", description="标准音频路径 (audio_mastering/voices/VOICE_[ID]_MASTER.wav)")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


class EpisodeResourceManifest(BaseModel):
    """阶段 6 产出：本集视听资源引单 (Episode Resource Manifest)。
    
    严格对齐 SKILL1.md v10.0.0 阶段 6 数据契约：
    - 角色三级 (tier1_base / tier2_performance / tier3_special)
    - 场景两级 (tier1_primary / tier2_transitional)
    - 道具三级 (tier1_hero / tier2_anchor / tier3_atmospheric)
    - 音频双元 (voices_used / foley_focus)
    支持嵌套树状契约与平铺字段双向序列化/反序列化。
    """
    model_config = ConfigDict(extra="allow")

    episode_num: int = Field(default=1, description="集数编号")

    # 平铺存储（一级/二级/三级）
    characters_tier_1: list[dict[str, Any]] = Field(default_factory=list, description="一级身份基础资产 (base_portrait, base_costume, master_voice)")
    characters_tier_2: list[dict[str, Any]] = Field(default_factory=list, description="二级叙事表现资产（angle_views, script_emotions）")
    characters_tier_3: list[dict[str, Any]] = Field(default_factory=list, description="三级镜头专项资产（special_macro, status_branch）")
    environments_primary: list[dict[str, Any]] = Field(default_factory=list, description="一级核心主场景 (wide_shot, insert_shot, lighting_state)")
    environments_transitional: list[dict[str, Any]] = Field(default_factory=list, description="二级过渡次场景 (keyframe_asset)")
    props_narrative: list[dict[str, Any]] = Field(default_factory=list, description="一级核心叙事物证 (static_asset, action_asset, haptic_resistance)")
    props_anchors: list[dict[str, Any]] = Field(default_factory=list, description="二级角色锚定道具 (attached_character_macro)")
    props_ambient: list[dict[str, Any]] = Field(default_factory=list, description="三级环境气氛杂物 (item_name, scene, motion_note 零独立生图)")
    audio_tts: list[dict[str, Any]] = Field(default_factory=list, description="TTS 声音资源引单")
    audio_motifs: list[dict[str, Any]] = Field(default_factory=list, description="配乐动机引单")
    voices_used: list[str] = Field(default_factory=list, description="本集涉及的所有母音频 ID 列表")
    foley_focus: str = Field(default="", description="本集必须放大的微观拟音")

    approved_character_ids: list[str | int] = Field(default_factory=list, description="已核准复用的角色ID列表")
    approved_scene_ids: list[str | int] = Field(default_factory=list, description="已核准复用的场景ID列表")
    approved_prop_ids: list[str | int] = Field(default_factory=list, description="已核准复用的道具ID列表")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "EpisodeResourceManifest":
        if isinstance(obj, dict):
            obj = dict(obj)
            # 1. 角色层级解析
            chars_val = obj.get("characters") or obj.get("character_assets")
            if isinstance(chars_val, dict):
                if not obj.get("characters_tier_1"):
                    obj["characters_tier_1"] = chars_val.get("tier1_base") or chars_val.get("tier_1") or []
                if not obj.get("characters_tier_2"):
                    obj["characters_tier_2"] = chars_val.get("tier2_performance") or chars_val.get("tier_2") or []
                if not obj.get("characters_tier_3"):
                    obj["characters_tier_3"] = chars_val.get("tier3_special") or chars_val.get("tier_3") or []
            elif isinstance(chars_val, list) and not obj.get("characters_tier_1"):
                t1, t2, t3 = [], [], []
                for item in chars_val:
                    if not isinstance(item, dict):
                        continue
                    tier = str(item.get("tier", "")).upper()
                    aid = str(item.get("asset_id") or item.get("char_id") or "")
                    if tier == "T1" or "_T1_" in aid or "BASE" in aid:
                        t1.append(item)
                    elif tier == "T2" or "_T2_" in aid or "4V" in aid or "EXP_" in aid or "LIGHT_" in aid:
                        t2.append(item)
                    elif tier == "T3" or "_T3_" in aid or "MACRO" in aid or "STATUS" in aid:
                        t3.append(item)
                    else:
                        t1.append(item)
                obj["characters_tier_1"] = t1
                obj["characters_tier_2"] = t2
                obj["characters_tier_3"] = t3

            # 2. 场景层级解析
            envs_val = obj.get("environments") or obj.get("scene_assets")
            if isinstance(envs_val, dict):
                if not obj.get("environments_primary"):
                    obj["environments_primary"] = envs_val.get("tier1_primary") or envs_val.get("primary") or []
                if not obj.get("environments_transitional"):
                    obj["environments_transitional"] = envs_val.get("tier2_transitional") or envs_val.get("transitional") or []
            elif isinstance(envs_val, list) and not obj.get("environments_primary"):
                e1, e2 = [], []
                for item in envs_val:
                    if not isinstance(item, dict):
                        continue
                    tier = str(item.get("tier", "")).upper()
                    aid = str(item.get("asset_id") or item.get("scene_id") or "")
                    if tier == "T2" or "_T2_" in aid or "KEYFRAME" in aid:
                        e2.append(item)
                    else:
                        e1.append(item)
                obj["environments_primary"] = e1
                obj["environments_transitional"] = e2

            # 3. 道具层级解析
            props_val = obj.get("props") or obj.get("prop_assets")
            if isinstance(props_val, dict):
                if not obj.get("props_narrative"):
                    obj["props_narrative"] = props_val.get("tier1_hero") or props_val.get("hero") or []
                if not obj.get("props_anchors"):
                    obj["props_anchors"] = props_val.get("tier2_anchor") or props_val.get("anchor") or []
                if not obj.get("props_ambient"):
                    obj["props_ambient"] = props_val.get("tier3_atmospheric") or props_val.get("atmospheric") or []
            elif isinstance(props_val, list) and not obj.get("props_narrative"):
                p1, p2, p3 = [], [], []
                for item in props_val:
                    if not isinstance(item, dict):
                        continue
                    tier = str(item.get("tier", "")).upper()
                    aid = str(item.get("asset_id") or item.get("prop_id") or "")
                    if tier == "T2" or "_T2_" in aid or "ANCHOR" in aid:
                        p2.append(item)
                    elif tier == "T3" or "_T3_" in aid or "AMBIENT" in aid or "ATMOSPHERIC" in aid:
                        p3.append(item)
                    else:
                        p1.append(item)
                obj["props_narrative"] = p1
                obj["props_anchors"] = p2
                obj["props_ambient"] = p3

            # 4. 音频层级解析
            audio_val = obj.get("audio") or obj.get("audio_assets")
            if isinstance(audio_val, dict):
                if not obj.get("voices_used"):
                    v_raw = audio_val.get("voices_used") or audio_val.get("character_voices") or []
                    extracted_v = []
                    for item in v_raw:
                        if isinstance(item, dict):
                            extracted_v.append(item.get("voice_id") or item.get("asset_id") or str(item))
                        elif isinstance(item, str):
                            extracted_v.append(item)
                    obj["voices_used"] = extracted_v
                if not obj.get("foley_focus"):
                    f_cues = audio_val.get("foley_cues") or []
                    obj["foley_focus"] = audio_val.get("foley_focus") or (f_cues[0] if f_cues else "")
                if not obj.get("audio_tts") and "audio_tts" in audio_val:
                    obj["audio_tts"] = audio_val.get("audio_tts", [])
                elif not obj.get("audio_tts") and "character_voices" in audio_val:
                    obj["audio_tts"] = audio_val.get("character_voices", [])
            elif isinstance(audio_val, list) and not obj.get("audio_tts"):
                obj["audio_tts"] = audio_val

        return super().model_validate(obj, *args, **kwargs)

    @property
    def characters(self) -> list[dict[str, Any]]:
        """全量角色资产平铺列表。"""
        return self.characters_tier_1 + self.characters_tier_2 + self.characters_tier_3

    @property
    def character_assets(self) -> list[dict[str, Any]]:
        return self.characters

    @property
    def characters_by_tier(self) -> dict[str, list[dict[str, Any]]]:
        """SKILL1.md Table 6 规范三级角色资产字典。"""
        return {
            "tier1_base": self.characters_tier_1,
            "tier2_performance": self.characters_tier_2,
            "tier3_special": self.characters_tier_3,
        }

    @property
    def environments(self) -> list[dict[str, Any]]:
        """全量场景资产平铺列表。"""
        return self.environments_primary + self.environments_transitional

    @property
    def scene_assets(self) -> list[dict[str, Any]]:
        return self.environments

    @property
    def environments_by_tier(self) -> dict[str, list[dict[str, Any]]]:
        """SKILL1.md Table 6 规范两级场景资产字典。"""
        return {
            "tier1_primary": self.environments_primary,
            "tier2_transitional": self.environments_transitional,
        }

    @property
    def props(self) -> list[dict[str, Any]]:
        """全量道具资产平铺列表。"""
        return self.props_narrative + self.props_anchors + self.props_ambient

    @property
    def prop_assets(self) -> list[dict[str, Any]]:
        return self.props

    @property
    def props_by_tier(self) -> dict[str, list[dict[str, Any]]]:
        """SKILL1.md Table 6 规范三级道具资产字典。"""
        return {
            "tier1_hero": self.props_narrative,
            "tier2_anchor": self.props_anchors,
            "tier3_atmospheric": self.props_ambient,
        }

    @property
    def audio_assets(self) -> list[dict[str, Any]]:
        return self.audio_tts or self.audio_motifs

    @property
    def audio_voices(self) -> list[Any]:
        """声音列表别名访问。"""
        return self.voices_used or self.audio_tts

    @property
    def audio(self) -> list[Any]:
        """全量音频资产平铺列表。"""
        return self.audio_assets or self.voices_used

    @property
    def audio_by_spec(self) -> dict[str, Any]:
        """SKILL1.md Table 6 规范音频资源字典。"""
        resolved_voices = self.voices_used
        if not resolved_voices:
            resolved_voices = [
                str(v.get("voice_id") or v.get("asset_id") or "")
                for v in self.audio_tts
                if isinstance(v, dict) and (v.get("voice_id") or v.get("asset_id"))
            ]
        return {
            "voices_used": resolved_voices,
            "foley_focus": self.foley_focus,
        }

    def to_dict(self) -> dict[str, Any]:
        """输出同时兼容 SKILL1.md 树状嵌套契约与平铺字段的字典。"""
        res = self.model_dump()
        res["characters"] = self.characters_by_tier
        res["environments"] = self.environments_by_tier
        res["props"] = self.props_by_tier
        res["audio"] = self.audio_by_spec
        return res

    def get(self, key: str, default: Any = None) -> Any:
        if key == "characters":
            return self.characters
        if key == "characters_by_tier" or key == "characters_nested":
            return self.characters_by_tier
        if key == "environments":
            return self.environments
        if key == "environments_by_tier" or key == "environments_nested":
            return self.environments_by_tier
        if key == "props":
            return self.props
        if key == "props_by_tier" or key == "props_nested":
            return self.props_by_tier
        if key == "audio":
            return self.audio_by_spec
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if key == "characters":
            return self.characters
        if key == "characters_by_tier" or key == "characters_nested":
            return self.characters_by_tier
        if key == "environments":
            return self.environments
        if key == "environments_by_tier" or key == "environments_nested":
            return self.environments_by_tier
        if key == "props":
            return self.props
        if key == "props_by_tier" or key == "props_nested":
            return self.props_by_tier
        if key == "audio":
            return self.audio_by_spec
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def keys(self) -> list[str]:
        return list(self.to_dict().keys())

    def values(self) -> list[Any]:
        return list(self.to_dict().values())

    def items(self) -> list[tuple[str, Any]]:
        return list(self.to_dict().items())

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


class VisualAudioAssetsRegistryModel(BaseModel):
    """【规则编号: RULE-VI-06】阶段 6 产出：05_visual_audio_assets.json 全局视听资产真理源模型。"""
    model_config = ConfigDict(extra="allow")

    episode_id: int = Field(default=1, description="当前集物理序号")
    episode_title: str = Field(default="", description="单集剧名")
    global_assets_summary: dict[str, Any] = Field(default_factory=dict, description="全局资产统计对象")
    characters: dict[str, Any] = Field(default_factory=dict, description="全剧已注册角色资产库")
    environments: dict[str, Any] = Field(default_factory=dict, description="全剧已注册场景资产库")
    props: dict[str, Any] = Field(default_factory=dict, description="全剧已注册道具资产库")
    audio_tts: dict[str, Any] = Field(default_factory=dict, description="全剧已注册母音频库")
    character_master_voices: dict[str, Any] = Field(default_factory=dict, description="全剧已注册母音频卡片库")
    reused_assets_history: dict[int, list[str]] = Field(default_factory=dict, description="各集复用资产历史记录")
    reused_existing_assets: list[ReusedAssetModel] = Field(default_factory=list, description="本集复用资产列表")
    newly_generated_assets: list[NewlyGeneratedAssetModel] = Field(default_factory=list, description="本集新生成增量资产列表")
    new_character_master_voice_cards: list[MasterVoiceCardModel] = Field(default_factory=list, description="新角色母音频卡片列表")
    episode_resource_manifest: EpisodeResourceManifest | None = Field(default=None, description="本集视听资源引单")
    audit_report: dict[str, Any] = Field(default_factory=dict, description="红蓝对抗质检报告")

    def to_dict(self) -> dict[str, Any]:
        res = self.model_dump()
        if self.episode_resource_manifest:
            res["episode_resource_manifest"] = self.episode_resource_manifest.to_dict()
        return res

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)


VisualAudioAssetsRegistry = VisualAudioAssetsRegistryModel


class EpisodeScriptV2(BaseModel):
    """阶段 5：单集纯文学剧本标准化契约 (ep_XX.json)。"""
    episode_number: int = Field(..., description="集数编号")
    title: str = Field(default="", description="单集剧名")
    duration_seconds: float = Field(default=120.0, description="单集规划时长秒数")
    safety_guardrails_lock: dict[str, Any] = Field(
        default_factory=dict,
        description="事前三道安全护栏锁（潜台词交锋矩阵/物理摩擦力与现实代价/强因果逻辑分集任务）"
    )
    previous_episode_physical_pickup: dict[str, Any] | None = Field(
        default=None,
        description="接力前一集集尾断点的物理快照（角色体态/手持道具/环境状态）"
    )
    scenes: list[dict[str, Any]] = Field(default_factory=list, description="场次列表（纯文学剧本场次与对白）")
    dramatic_rhythm_check: dict[str, str] = Field(
        default_factory=dict,
        description="戏剧节奏自检（前3s钩子、40-60s微反转、集尾绝杀断点）"
    )
    episode_end_physical_delta: dict[str, str] = Field(
        default_factory=dict,
        description="集尾绝杀断点0秒物理快照（下一集开篇第一秒接力源）"
    )


class LipsyncDynamics(BaseModel):
    """阶段 7 口型动力学与微表情参数。"""
    model_config = ConfigDict(extra="allow")
    speaker: str = Field(default="", description="说话角色")
    jaw_open_scale: float = Field(default=0.6, description="下颌开度比例 (0.0~1.0)")
    mouth_tension: str = Field(default="", description="嘴角张力描述")
    head_subtle_motion: str = Field(default="", description="头部微动描述")

    @property
    def jaw_open(self) -> float:
        return self.jaw_open_scale

    @jaw_open.setter
    def jaw_open(self, value: float) -> None:
        self.jaw_open_scale = value

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


# =========================================================================
# 多级资产结构化模型（对齐 6 大从表：阶段/视角/子区域/做旧/损坏/细节）
# =========================================================================

class CharacterStageViewAsset(BaseModel):
    """角色阶段分视角资产 (character_stage_views 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    view_type: str = Field(default="front", description="视角类型：front(正)/side(侧)/back(背)/closeup(特写)/macro(微距)")
    image_url: str = Field(default="", description="生成图访问 URL")
    local_path: str = Field(default="", description="本地物理存储路径")
    seedance_asset_id: str = Field(default="", description="Seedance/外部平台资产引用 ID")
    prompt: str = Field(default="", description="正向生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    status: str = Field(default="completed", description="状态：pending/processing/completed/failed")


class CharacterStageAsset(BaseModel):
    """角色生命周期阶段变体资产 (character_stages 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    stage_name: str = Field(default="初始阶段", description="阶段名称（如：落魄期/逆袭崛起/黑化复仇/终局巅峰）")
    stage_order: int = Field(default=1, description="阶段顺序编号")
    costume_desc: str = Field(default="", description="本阶段服化道物理做旧描述")
    makeup_desc: str = Field(default="", description="本阶段妆容与骨相微变描述")
    image_url: str = Field(default="", description="代表图 URL")
    local_path: str = Field(default="", description="代表图本地存储路径")
    seedance_asset_id: str = Field(default="", description="Seedance/外部平台资产引用 ID")
    prompt: str = Field(default="", description="正向生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    views: list[CharacterStageViewAsset] = Field(default_factory=list, description="本阶段多视角子资产列表")


class SceneWeatheringViewAsset(BaseModel):
    """场景气候/做旧/光影图层资产 (scene_weathering_views 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    layer_type: str = Field(default="natural", description="图层类型：natural(晴朗自然)/rain(暴雨湿滑)/night(暗夜冷调)/ruin(破败战损)")
    image_url: str = Field(default="", description="图层资产 URL")
    local_path: str = Field(default="", description="本地物理路径")
    lighting_prompt: str = Field(default="", description="光影与氛围专用提示词")
    texture_prompt: str = Field(default="", description="材质与做旧专用提示词")
    prompt: str = Field(default="", description="完整合成生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    status: str = Field(default="completed", description="状态")


class SceneZoneAsset(BaseModel):
    """场景三级子功能区域资产 (scene_zones 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    zone_name: str = Field(default="主活动区", description="子区域名称（如：办公桌区域/落地窗前/秘密暗格/会客沙发）")
    camera_orientation: str = Field(default="", description="机位朝向与空间构图说明")
    spatial_layout: str = Field(default="", description="空间长宽高与摆设布局细节")
    image_url: str = Field(default="", description="局部区域效果图 URL")
    local_path: str = Field(default="", description="本地物理存储路径")
    prompt: str = Field(default="", description="生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    weathering_views: list[SceneWeatheringViewAsset] = Field(default_factory=list, description="多气候图层资产")


class PropDetailViewAsset(BaseModel):
    """道具微距局部与多视角资产 (prop_detail_views 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    view_type: str = Field(default="macro_detail", description="视角类型：macro_detail(微距特写)/front(正)/side(侧)/engraving(铭文刻痕)")
    image_url: str = Field(default="", description="生成图访问 URL")
    local_path: str = Field(default="", description="本地物理路径")
    prompt: str = Field(default="", description="正向生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    status: str = Field(default="completed", description="状态")


class PropDamageStateAsset(BaseModel):
    """道具损坏/形变状态演进资产 (prop_damage_states 从表模型)。"""
    model_config = ConfigDict(extra="allow")
    state_label: str = Field(default="完整初始态", description="状态标签（如：完整初始态/裂痕破损/断裂烧焦）")
    state_order: int = Field(default=1, description="状态顺序编号")
    damage_desc: str = Field(default="", description="物理形变与破损原因详细描述")
    image_url: str = Field(default="", description="状态代表图 URL")
    local_path: str = Field(default="", description="本地存储路径")
    prompt: str = Field(default="", description="正向生图提示词")
    negative_prompt: str = Field(default="", description="负向提示词")
    detail_views: list[PropDetailViewAsset] = Field(default_factory=list, description="本状态多视角/微距图层")


class StoryboardShot(BaseModel):
    """阶段 7：单镜头工业执行表单项契约（对齐单帧图像生成与音视频动态指令）。"""
    model_config = ConfigDict(extra="allow")
    shot_id: int = Field(..., description="镜号")
    timecode: str = Field(default="00:00:00,000 --> 00:00:02,500", description="时间码（如：00:00:00,000 --> 00:00:02,500）")
    duration_sec: float = Field(default=3.0, description="单镜时长（严格整秒 2.0, 3.0, 4.0, 5.0, 6.0, 7.0）")
    framing: str = Field(default="MCU 中近景", description="景别")
    camera_motion: str = Field(default="Static", description="运镜方式（推/拉/摇/移/跟随/升降/静止）")
    image_prompt: str = Field(default="", description="单帧视觉画面生图提示词 (Prompt)")
    video_prompt: str = Field(default="", description="视频运动与动态演变提示词")
    generation_mode: str = Field(
        default="single_frame_dynamic",
        description="分镜生成模式：single_frame_dynamic(单帧图像+运镜), first_last_frame(首尾帧), multi_image_reference(多图参考)"
    )
    character_asset_ids: list[str] = Field(default_factory=list, description="本镜头涉及的角色资产ID列表")
    scene_asset_id: str = Field(default="", description="本镜头涉及的场景资产ID")
    prop_asset_ids: list[str] = Field(default_factory=list, description="本镜头涉及的道具资产ID列表")
    srt_text: str = Field(default="", description="对白/旁白字幕文本")
    srt_timing: str = Field(default="", description="字幕精准时间戳（如 00:00:00,200 --> 00:00:02,100）")
    dynamic_cue: str = Field(default="", description="镜头动态与视听动效指令")
    music_cue: str = Field(default="", description="背景音乐动机与情绪标签")
    foley_cue: str = Field(default="", description="拟音/物理音效指令 (+3dB 规范)")
    selection_rationale: str = Field(default="", description="选型依据决策解释")
    first_last_config: dict[str, Any] | None = Field(default=None, description="首尾帧配置（向下兼容）")
    multi_image_config: dict[str, Any] | None = Field(default=None, description="多图参考配置（向下兼容）")
    audio: dict[str, Any] = Field(default_factory=dict, description="全息声学提示词（对白/旁白/拟音Foley/TTS腔体共鸣/闭环状态）")
    lipsync_dynamics: LipsyncDynamics | dict[str, Any] | None = Field(default=None, description="口型动力学（下颌开度jaw_open_scale/嘴角张力/头部微动）")

    target_engine: str | None = Field(default="wan3.0", description="目标生成模型 (wan3.0/seedance2.5/minimax_h3)")
    rationale: str = Field(default="", description="算子1+2景别与时长累加推导依据")
    first_last_frame_config: dict[str, Any] | None = Field(default=None, description="首尾帧Prompt配置")
    speech_inpoint_sec: float | None = Field(default=None, description="台词入点时间码偏移秒数")
    contextual_tts_prompt: str | None = Field(default="", description="腔体与情绪 TTS 提示词")
    is_dialogue_complete_in_shot: bool = Field(default=True, description="台词是否在镜头内完整闭环说完")

    # 大对象外挂指针（严禁在 State 中内嵌 Base64，通过 URI / local_path 关联）
    image_url: str = Field(default="", description="单帧画面或首帧图像存储 URL/URI（大对象外挂）")
    local_path: str = Field(default="", description="单帧画面或首帧图像本地持久化路径")
    video_url: str = Field(default="", description="生成的视频切片存储 URL/URI（大对象外挂）")
    video_local_path: str = Field(default="", description="生成的视频切片本地持久化路径")
    audio_url: str = Field(default="", description="合成音频/TTS 存储 URL/URI")

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (bool(self.model_extra) and key in self.model_extra)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "StoryboardShot":
        if isinstance(obj, dict):
            obj = dict(obj)
            # 兼容字段别名 (Framing / Camera Motion / Mode / Duration)
            if "shot_type" in obj and "framing" not in obj:
                obj["framing"] = obj["shot_type"]
            if "camera_movement" in obj and "camera_motion" not in obj:
                obj["camera_motion"] = obj["camera_movement"]
            elif "movement" in obj and "camera_motion" not in obj:
                obj["camera_motion"] = obj["movement"]
            if "mode" in obj and "generation_mode" not in obj:
                obj["generation_mode"] = obj["mode"]
            elif "creation_mode" in obj and "generation_mode" not in obj:
                obj["generation_mode"] = obj["creation_mode"]
            if "duration_seconds" in obj and "duration_sec" not in obj:
                obj["duration_sec"] = obj["duration_seconds"]
            elif "duration" in obj and "duration_sec" not in obj:
                obj["duration_sec"] = obj["duration"]

            if "lipsync_dynamics" in obj and isinstance(obj["lipsync_dynamics"], dict):
                dyn = dict(obj["lipsync_dynamics"])
                if "jaw_open" in dyn and "jaw_open_scale" not in dyn:
                    dyn["jaw_open_scale"] = dyn["jaw_open"]
                obj["lipsync_dynamics"] = LipsyncDynamics.model_validate(dyn)
            if "first_last_config" in obj and "first_last_frame_config" not in obj:
                obj["first_last_frame_config"] = obj["first_last_config"]
            elif "first_last_frame_config" in obj and "first_last_config" not in obj:
                obj["first_last_config"] = obj["first_last_frame_config"]
            if "multi_image_config" in obj and isinstance(obj["multi_image_config"], dict):
                mic = dict(obj["multi_image_config"])
                if "reference_assets" in mic and "reference_asset_ids" not in mic:
                    mic["reference_asset_ids"] = mic["reference_assets"]
                elif "reference_asset_ids" in mic and "reference_assets" not in mic:
                    mic["reference_assets"] = mic["reference_asset_ids"]
                obj["multi_image_config"] = mic
            audio_data = obj.get("audio")
            if isinstance(audio_data, dict):
                audio_dict = dict(audio_data)
                if "is_dialogue_complete_in_shot" in audio_dict:
                    obj.setdefault("is_dialogue_complete_in_shot", audio_dict["is_dialogue_complete_in_shot"])
                elif "is_dialogue_complete_in_shot" in obj:
                    audio_dict["is_dialogue_complete_in_shot"] = obj["is_dialogue_complete_in_shot"]
                if "speech_inpoint_sec" in audio_dict:
                    obj.setdefault("speech_inpoint_sec", audio_dict["speech_inpoint_sec"])
                elif "speech_inpoint_sec" in obj:
                    audio_dict["speech_inpoint_sec"] = obj["speech_inpoint_sec"]
                if "contextual_tts_prompt" in audio_dict:
                    obj.setdefault("contextual_tts_prompt", audio_dict["contextual_tts_prompt"])
                elif "contextual_tts_prompt" in obj:
                    audio_dict["contextual_tts_prompt"] = obj["contextual_tts_prompt"]
                obj["audio"] = audio_dict
        return super().model_validate(obj, *args, **kwargs)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


# =========================================================================
# 阶段 8：多轨智能音频工程与混音调度模型 (Stage 8 Audio Mastering)
# =========================================================================

class AcousticTraceability(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 四大依据溯源契约。"""
    model_config = ConfigDict(extra="allow")
    stage_4_leitmotif_basis: str = Field(default="", description="阶段 4 主题音乐动机依据 (A/B/C)")
    stage_1_worldview_basis: str = Field(default="", description="阶段 1 世界观与题材风格依据")
    stage_7_timecode_basis: str = Field(default="", description="阶段 7 镜头总时长与台词入点时间码依据")
    stage_5_dramatic_cues: str = Field(default="", description="阶段 5 开篇动作/45s断崖/集尾断钩戏剧点依据")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class BgmGenerationConfig(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 动态生乐 Prompt 契约。"""
    model_config = ConfigDict(extra="allow")
    full_master_prompt: str = Field(default="", description="Suno/Udio 动态生乐全量 Prompt (包含 T_actual 绝对秒数与淡出硬切)")
    planned_duration_sec: float = Field(default=120.0, description="实际总时长 T_actual")
    bpm: int = Field(default=85, description="节奏速度 (BPM)")
    musical_key: str = Field(default="D minor", description="调性")
    leitmotif_name: str = Field(default="", description="动机标识")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class MasteringScheduleItemModel(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 精准分贝避让调度表单项。"""
    model_config = ConfigDict(extra="allow")
    time_start_sec: float = Field(default=0.0, description="开始秒数")
    time_end_sec: float = Field(default=0.0, description="结束秒数")
    timecode_range: str = Field(default="", description="时间码区间 (如 00:00:00,000 --> 00:00:02,500)")
    target_bgm_volume_db: float = Field(default=-12.0, description="目标 BGM 音量 (动作 -12.0dB, 对白避让 -20.0dB, 断崖静音 -999.0dB)")
    speech_ducking_active: bool = Field(default=False, description="是否激活侧链对白避让")
    event_description: str = Field(default="", description="声学事件描述")
    action_type: str = Field(default="", description="动作类别 (action_intro/speech_ducking/cliffhanger_silence/fade_out_stop)")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "MasteringScheduleItemModel":
        if isinstance(obj, dict):
            obj = dict(obj)
            if "start_sec" in obj and "time_start_sec" not in obj:
                obj["time_start_sec"] = obj["start_sec"]
            if "end_sec" in obj and "time_end_sec" not in obj:
                obj["time_end_sec"] = obj["end_sec"]
            if "gain_db" in obj and "target_bgm_volume_db" not in obj:
                obj["target_bgm_volume_db"] = obj["gain_db"]
            if "description" in obj and "event_description" not in obj:
                obj["event_description"] = obj["description"]
        return super().model_validate(obj, *args, **kwargs)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class NleMixingGuidelines(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 NLE 剪辑软件多轨混音导入参数指南。"""
    model_config = ConfigDict(extra="allow")
    broadcast_loudness_standard: str = Field(default="-23 LUFS", description="广播级响度标准")
    sampling_rate: str = Field(default="48kHz", description="采样率")
    bit_depth: str = Field(default="24-bit", description="位深")
    peak_db: float = Field(default=-1.0, description="真峰值限制 (dBTP)")
    peak_limit_dbtp: float = Field(default=-1.0, description="真峰值限制 (dBTP)")
    integrated_lufs: float = Field(default=-23.0, description="综合响度标准 (LUFS)")
    track_a1_dialogue: str | dict[str, Any] = Field(default="0.0dB, 压缩比 3:1, -23 LUFS 标准", description="Track A1 对白轨参数")
    track_a2_foley: str | dict[str, Any] = Field(default="+3.0dB, 80Hz 高通滤波", description="Track A2 拟音轨参数")
    track_a3_bgm: str | dict[str, Any] = Field(default="动作区 -12.0dB, 对白区 -20.0dB Ducking 避让, 45s断崖静音 -999.0dB", description="Track A3 BGM 轨参数")
    track_v1_video: str | dict[str, Any] = Field(default="V1 视频切片, V2 SRT 字幕文本", description="Track V1/V2 视频与字幕")
    tracks: dict[str, Any] = Field(default_factory=dict, description="轨道详细参数字典")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class AudioMasteringConfig(BaseModel):
    """【规则编号: RULE-VI-08】阶段 8 单集多轨智能音频工程与混音调度模型。"""
    model_config = ConfigDict(extra="allow")
    broadcast_loudness_standard: str = Field(default="-23 LUFS", description="广播级响度标准 (固定锁定 -23 LUFS)")
    target_lufs: float = Field(default=-23.0, description="目标响度数值 (-23.0)")
    peak_limit_dbtp: float = Field(default=-1.0, description="真峰值限制 (-1.0 dBTP)")
    acoustic_traceability: AcousticTraceability = Field(default_factory=AcousticTraceability, description="四大依据溯源")
    bgm_generation: BgmGenerationConfig = Field(default_factory=BgmGenerationConfig, description="BGM 动态生乐 Prompt 配置")
    mastering_schedule: list[MasteringScheduleItemModel] = Field(default_factory=list, description="精准分贝避让调度表")
    nle_mixing_guidelines: NleMixingGuidelines | dict[str, Any] = Field(default_factory=NleMixingGuidelines, description="NLE 多轨参数指南")
    ducking_strategy: dict[str, Any] = Field(default_factory=dict, description="侧链避让策略")
    ducking_events: list[dict[str, Any]] = Field(default_factory=list, description="侧链避让事件列表")
    foley_boost_tracks: list[dict[str, Any]] = Field(default_factory=list, description="拟音高光增强列表 (+3.0dB)")
    tracks: list[dict[str, Any]] = Field(default_factory=list, description="多轨总线参数")
    full_srt_content: str = Field(default="", description="毫秒级广播级 SRT 内容")
    actual_duration_sec: float = Field(default=120.0, description="阶段 7 实际总秒数 T_actual")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "AudioMasteringConfig":
        if isinstance(obj, dict):
            obj = dict(obj)
            # 自动提取或推导 broadcast_loudness_standard / target_lufs
            if "broadcast_loudness_standard" not in obj or not obj["broadcast_loudness_standard"]:
                obj["broadcast_loudness_standard"] = "-23 LUFS"
            if "target_lufs" not in obj:
                obj["target_lufs"] = -23.0
            if "peak_limit_dbtp" not in obj:
                obj["peak_limit_dbtp"] = -1.0
            if "acoustic_traceability" in obj and isinstance(obj["acoustic_traceability"], dict):
                obj["acoustic_traceability"] = AcousticTraceability.model_validate(obj["acoustic_traceability"])
            if "bgm_generation" in obj and isinstance(obj["bgm_generation"], dict):
                obj["bgm_generation"] = BgmGenerationConfig.model_validate(obj["bgm_generation"])
            if "mastering_schedule" in obj and isinstance(obj["mastering_schedule"], list):
                obj["mastering_schedule"] = [
                    MasteringScheduleItemModel.model_validate(item) if isinstance(item, dict) else item
                    for item in obj["mastering_schedule"]
                ]
            if "nle_mixing_guidelines" in obj and isinstance(obj["nle_mixing_guidelines"], dict):
                obj["nle_mixing_guidelines"] = NleMixingGuidelines.model_validate(obj["nle_mixing_guidelines"])
        return super().model_validate(obj, *args, **kwargs)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (bool(self.model_extra) and key in self.model_extra)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


EpisodeAudioMasteringPlan = AudioMasteringConfig


# =========================================================================
# 【分层状态机与持久化执行架构】轻量契约模型 (Thin State Machine Contracts)
# =========================================================================

class EpisodeLocalAsset(BaseModel):
    """【单集局部资产】单集独有资产（如特约群演、一次性道具、临时特定场景），生命周期局限于本集。"""
    model_config = ConfigDict(extra="allow")
    asset_id: str = Field(default="", description="局部资产唯一标识 (如 EP01_CHAR_WAITER)")
    asset_type: str = Field(default="character", description="资产类型: character / prop / scene")
    name: str = Field(default="", description="资产名称")
    visual_prompt: str = Field(default="", description="视觉生图提示词特征")
    local_path: str = Field(default="", description="本地图片或文件持久化路径")
    image_url: str = Field(default="", description="对象存储或网络图片 URI")
    description: str = Field(default="", description="资产简要说明与戏剧功能")

    @model_validator(mode="before")
    @classmethod
    def _normalize_asset_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if not data.get("name"):
                data["name"] = (
                    data.get("item_name")
                    or data.get("prop_name")
                    or data.get("character_name")
                    or data.get("location_name")
                    or data.get("title")
                    or data.get("asset_id")
                    or "未命名资产"
                )
            if not data.get("asset_id"):
                data["asset_id"] = (
                    data.get("prop_id")
                    or data.get("char_id")
                    or data.get("scene_id")
                    or data.get("voice_id")
                    or data.get("id")
                    or "ASSET_DEFAULT"
                )
            if not data.get("asset_type"):
                aid = str(data.get("asset_id", ""))
                if "CHAR" in aid:
                    data["asset_type"] = "character"
                elif "ENV" in aid or "SCENE" in aid:
                    data["asset_type"] = "scene"
                elif "PROP" in aid:
                    data["asset_type"] = "prop"
                elif "VOICE" in aid or "AUDIO" in aid:
                    data["asset_type"] = "audio"
        return data

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (bool(self.model_extra) and key in self.model_extra)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default


class CharacterAnchorStub(BaseModel):
    """【轻量全局锚点】角色基础特征索引桩（仅保留高频匹配与提示词注入必要字段，<1KB）。"""
    model_config = ConfigDict(extra="allow")
    character_id: str = Field(description="角色全局唯一标识 Token (如 CHAR_LUCHEN)")
    name: str = Field(description="角色中文姓名")
    visual_token: str = Field(default="", description="生图视觉提示词特征锚点 (如 sharp jawline, messy black hair)")
    archetype: str = Field(default="", description="戏剧原型/角色定位 (如 复仇潜伏者/隐忍主角)")
    core_costume_prompt: str = Field(default="", description="默认标志性服化道 Prompt 摘要")


class SceneAnchorStub(BaseModel):
    """【轻量全局锚点】空间场景基础特征索引桩。"""
    model_config = ConfigDict(extra="allow")
    scene_id: str = Field(description="场景全局唯一标识 Token (如 SCENE_WAREHOUSE)")
    name: str = Field(description="场景中文名称")
    spatial_type: str = Field(default="interior", description="空间类别: interior / exterior")
    color_tone: str = Field(default="", description="标志性色调与环境光影描述")
    weathering_summary: str = Field(default="", description="空间做旧三层质感摘要")


class PropAnchorStub(BaseModel):
    """【轻量全局锚点】核心道具物证索引桩。"""
    model_config = ConfigDict(extra="allow")
    prop_id: str = Field(description="道具全局唯一标识 Token (如 PROP_GOD_SLAYER)")
    name: str = Field(description="道具中文名称")
    level: str = Field(default="hero_tier1", description="道具评级: hero_tier1 / anchor_tier2 / atmospheric_tier3")
    visual_token: str = Field(default="", description="视觉识别特征描述")


class AudioBibleSummary(BaseModel):
    """【轻量全局锚点】音乐母法典概要索引。"""
    model_config = ConfigDict(extra="allow")
    overall_style: str = Field(default="悬疑反转/重型低频", description="全剧整体声学基调")
    leitmotif_registry: list[dict[str, Any]] = Field(default_factory=list, description="主导动机简表 (包含 motif_id, name, tempo_bpm, musical_key)")
    leitmotifs: list[dict[str, Any]] = Field(default_factory=list, description="主导动机别名列表")
    leitmotif_names: list[str] = Field(default_factory=list, description="动机名称索引列表")
    foley_rules_count: int = Field(default=0, description="拟音规则数量")
    theme_prompt: str = Field(default="", description="主旋律 Prompt")

    @model_validator(mode="before")
    @classmethod
    def _normalize_leitmotifs(cls, values: Any) -> Any:
        if isinstance(values, dict):
            reg = values.get("leitmotif_registry")
            motifs = values.get("leitmotifs")
            if reg and not motifs:
                values["leitmotifs"] = reg
            elif motifs and not reg:
                values["leitmotif_registry"] = motifs
        return values

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        return self.__dict__.get(item)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item) or item in self.__dict__

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class SeasonOutlineCard(BaseModel):
    """【单集任务卡】全季分集宏观节律任务卡（完整承载 Stage 4 双螺旋工笔契约，包含双螺旋事件链、反转钩子与潜台词矩阵）。"""
    model_config = ConfigDict(extra="allow")
    episode_number: int = Field(default=1, description="集数编号 (1..NN)")
    episode_id: int = Field(default=1, description="集数 ID (同 episode_number)")
    title: str = Field(default="", description="单集爆款标题")
    killer_title: str = Field(default="", description="商业吸睛片名")
    core_conflict_task: str = Field(default="", description="本集核心戏剧冲突任务")
    hook_cliffhanger: str = Field(default="", description="集尾 115 秒黄金悬念钩子")
    dramatic_arc_unit: str = Field(default="", description="所属戏剧微弧单元")
    # 双螺旋工笔任务卡与视听节律核心字段（全面对齐 Stage 4 交付标准与 Stage 5 执行契约）
    dual_helix_task: dict[str, Any] = Field(default_factory=dict, description="双螺旋任务卡对象（含 plot_event_chain, relational_shift_point, lie_erosion_metric）")
    subtext_matrix: dict[str, Any] = Field(default_factory=dict, description="潜台词与深层冲突矩阵")
    hook_3s: str = Field(default="", description="开篇 3 秒视觉/动作钩子")
    micro_twist_45s: str = Field(default="", description="45 秒微反转或关系质变")
    cliffhanger_end: str = Field(default="", description="集尾悬念/卡点钩子")
    raw_outline_card: dict[str, Any] = Field(default_factory=dict, description="Stage 4 生成的原始完整大纲卡片备份")

    @model_validator(mode="before")
    @classmethod
    def _normalize_outline_fields(cls, values: Any) -> Any:
        if isinstance(values, dict):
            # 1. 兼容多版本集数主键别名
            ep_num = values.get("episode_number") or values.get("episode_num") or values.get("episode_id") or values.get("episode") or 1
            values["episode_number"] = int(ep_num)
            values["episode_id"] = int(ep_num)

            # 2. 标题别名对齐
            if not values.get("title") and values.get("episode_title"):
                values["title"] = str(values["episode_title"])
            if not values.get("killer_title") and values.get("title"):
                values["killer_title"] = str(values["title"])

            # 3. 节律钩子别名对齐
            if not values.get("hook_3s") and values.get("three_second_hook"):
                values["hook_3s"] = str(values["three_second_hook"])
            if not values.get("micro_twist_45s") and values.get("micro_turning_point_45s"):
                values["micro_twist_45s"] = str(values["micro_turning_point_45s"])
            if not values.get("cliffhanger_end"):
                values["cliffhanger_end"] = str(
                    values.get("killer_cliffhanger_115s")
                    or values.get("hook_cliffhanger")
                    or values.get("cliffhanger")
                    or ""
                )

            # 4. 核心任务别名对齐
            if not values.get("core_conflict_task"):
                values["core_conflict_task"] = str(
                    values.get("core_dramatic_task")
                    or values.get("task")
                    or ""
                )

            # 5. 双螺旋任务结构自动聚合（兼容扁平化字段）
            dh = values.get("dual_helix_task")
            if not isinstance(dh, dict):
                dh = {}
            if "plot_event_chain" not in dh and values.get("plot_event_chain"):
                dh["plot_event_chain"] = values["plot_event_chain"]
            if "relational_shift_point" not in dh and values.get("relational_shift_point"):
                dh["relational_shift_point"] = values["relational_shift_point"]
            if "lie_erosion_metric" not in dh and values.get("lie_erosion_metric"):
                dh["lie_erosion_metric"] = values["lie_erosion_metric"]
            values["dual_helix_task"] = dh
        return values

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        if self.__pydantic_extra__ and item in self.__pydantic_extra__:
            return self.__pydantic_extra__[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            val = self[item]
            return val if val is not None else default
        except KeyError:
            return default

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return hasattr(self, item) or (self.__pydantic_extra__ is not None and item in self.__pydantic_extra__)


class InterEpisodePhysicalContinuity(BaseModel):
    """【跨集连续性】集间 0 秒物理咬合连续性快照。"""
    model_config = ConfigDict(extra="allow")
    from_episode: int = Field(default=0, description="来源集数编号")
    to_episode: int = Field(default=0, description="目标继承集数编号")
    episode_number: int = Field(default=0, description="兼容别名：集数编号")
    character_physical_states: dict[str, str] = Field(
        default_factory=dict,
        description="角色身体姿态与肉体伤情描述 (如 {'CHAR_LUCHEN': '左肩渗血，单膝跪地'})"
    )
    prop_custody_states: dict[str, str] = Field(
        default_factory=dict,
        description="关键道具持有与损坏状态 (如 {'PROP_BLADE': '掉落右侧地面 3 米处'})"
    )
    environmental_state: str = Field(default="", description="残留环境与天气光影状态 (如 '暴雨停歇，地面积水倒映霓虹')")
    timeline_progress_sec: float = Field(default=120.0, description="前集剧情结束时的累积时间线进度秒数")

    @model_validator(mode="before")
    @classmethod
    def _sync_ep_numbers(cls, data: Any) -> Any:
        if isinstance(data, dict):
            ep = data.get("episode_number") or data.get("from_episode") or 0
            if "from_episode" not in data or not data.get("from_episode"):
                data["from_episode"] = ep
            if "episode_number" not in data or not data.get("episode_number"):
                data["episode_number"] = ep
        return data

    def __getitem__(self, item: str) -> Any:
        if item == "episode_number":
            return getattr(self, "episode_number", 0) or self.from_episode
        if hasattr(self, item):
            return getattr(self, item)
        if self.__pydantic_extra__ and item in self.__pydantic_extra__:
            return self.__pydantic_extra__[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            val = self[item]
            return val if val is not None else default
        except KeyError:
            return default

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return hasattr(self, item) or (self.__pydantic_extra__ is not None and item in self.__pydantic_extra__)


class StoryboardShotStub(BaseModel):
    """【轻量分镜桩】单镜头轻量索引（仅保留机位元数据与资产 URI 指针，严禁内联 Base64）。"""
    model_config = ConfigDict(extra="allow")
    shot_id: int = Field(description="镜头序号 (1..NN)")
    shot_type: str = Field(default="特写", description="景别机位")
    camera_movement: str = Field(default="慢速推进", description="运镜方式")
    duration_sec: float = Field(default=3.0, description="镜头时长秒数")
    screen_description: str = Field(default="", description="画面内容与视觉描述")
    image_uri: str = Field(default="", description="外挂图像存储 URI 指针 (如 storage://ep01/shot_03.png)")
    audio_summary: str = Field(default="", description="对白及声效配置摘要")


class GlobalDramaMasterState(BaseModel):
    """【全局文学父图状态】第一程文学故事工程核心真理源与宏观调度器。
    
    架构特征:
    1. 内存极度收敛: 严禁累加分集正文、全集分镜及音频分轨，尺寸严格约束在 50KB 以内;
    2. 全局真理源索引: 仅保存角色、场景、音乐母法典的轻量级锚点注册表;
    3. 语义化工作便签: 彻底废弃 short_memory_a/b/c/d，采用业务语义字段。
    """
    model_config = ConfigDict(extra="allow")
    drama_id: int = Field(default=0, description="短剧项目 ID")
    slug: str = Field(default="", description="项目唯一英文标识")
    journey: Literal["journey_1_literary", "journey_2_visual", "completed"] = Field(
        default="journey_1_literary",
        description="当前所处宏观程"
    )
    current_stage: int = Field(default=1, description="当前宏观阶段 (1..8)")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="执行控制模式：stage_by_stage(单步精细)/two_journey(双程总控)/full_auto(全自动极速)"
    )
    
    # 阶段 1 核心契约与双轨禁令
    user_idea: str = Field(default="", description="用户原始核心构想与立项故事创意")
    selected_title: str = Field(default="", description="定稿片名")
    candidate_titles: CandidateTitleMatrix = Field(default_factory=CandidateTitleMatrix)
    aspect_ratio: str = Field(default="9:16", description="画幅比例")
    target_duration_sec: float = Field(default=120.0, description="单集时长秒数")
    duration_sec_per_ep: int = Field(default=120, description="单集规划秒数")
    genre: str = Field(default="都市/悬疑", description="全剧类型")
    visual_style: str = Field(default="真人电影/超写实", description="全剧视觉基调")
    logline: str = Field(default="", description="全剧一句话高概念梗概")
    dramatic_irony: str = Field(default="", description="贯穿全剧的核心讽刺")
    grand_payoff: str = Field(default="", description="终局核爆点")
    mechanism: str = Field(default="", description="信息差机制")
    arc_type: str = Field(default="", description="情感弧型")
    blueprint: dict[str, Any] | None = Field(default=None, description="项目蓝图")
    derivation: dict[str, Any] | None = Field(default=None, description="弧型与机制判定结论")
    negative_rules: DoubleTrackProhibitions = Field(default_factory=DoubleTrackProhibitions)
    forbidden_cliches_10: list[str] = Field(default_factory=list, description="10大老套因果禁令")
    forbidden_cheap_tropes_3: list[str] = Field(default_factory=list, description="3大廉价爽点禁令")
    target_video_engine: str = Field(default="wan3.0", description="全剧目标视频生成引擎底模 (wan3.0/seedance2.5/minimax_h3)")
    
    # 语义化阶段工作便签 (Working Memory) 与兼容短记忆
    ideation_working_memory: str = Field(default="", description="阶段 1 创意工作便签：人设禁令子集 + 核心讽刺 + 终局核爆")
    character_working_memory: str = Field(default="", description="阶段 2 角色工作便签：核心主角骨相 + 服化道 + 关系死结网")
    world_building_working_memory: str = Field(default="", description="阶段 3 空间与物证工作便签：核心空间做旧 + 物证拟音锚点")
    season_outline_working_memory: str = Field(default="", description="阶段 4 大纲工作便签：全季戏剧小高潮路线图 + 音乐主导动机")
    inter_episode_physical_continuity: dict[str, Any] | None = Field(default=None, description="集间0秒物理咬合连续性快照")
    inter_episode_physical_snapshot: dict[str, Any] | None = Field(default=None, description="集间0秒物理咬合快照")
    
    # 阶段 2、3、4 结构化实体真理源 (支持平滑过渡与轻量桩合成)
    characters_engine: dict[str, Any] | list[Any] = Field(default_factory=dict, description="阶段 2 角色引擎完整实体")
    characters: list[dict[str, Any]] = Field(default_factory=list, description="阶段 2 角色列表")
    character_tokens: list[str] | dict[str, Any] = Field(default_factory=list, description="角色 Token 白名单")
    dual_track_relationships: list[DualTrackRelationshipItem] = Field(default_factory=list, description="双轨关系网")
    relationship_matrix: list[dict[str, Any]] = Field(default_factory=list, description="关系矩阵")
    character_relationships: list[CharacterRelationshipItem] = Field(default_factory=list, description="角色动态关系矩阵")
    emotional_arc_trajectories: list[EmotionalArcTrajectory] = Field(default_factory=list, description="情感弧光轨迹")
    emotional_arc_trajectory: dict[str, Any] = Field(default_factory=dict, description="情感弧光字典")
    
    environments_and_props: dict[str, Any] = Field(default_factory=dict, description="阶段 3 空间与物证完整实体")
    scene_tokens: list[str] | dict[str, Any] = Field(default_factory=list, description="场景 Token 白名单")
    prop_tokens: list[str] | dict[str, Any] = Field(default_factory=list, description="道具 Token 白名单")
    
    audio_bible: AudioBible = Field(default_factory=AudioBible, description="阶段 4 音乐母法典完整实体")
    mini_arc_units: list[dict[str, Any]] = Field(default_factory=list, description="阶段 4 戏剧微弧划分")
    current_mini_arc_index: int = Field(default=1, description="当前戏剧波次")
    literary_journey_locked: bool = Field(default=False, description="第一程全季文学定稿总锁")
    stage_approvals: dict[str, bool] = Field(
        default_factory=dict,
        description="阶段人工审批放行白名单标记字典 (例如 {'stage4': True, 'audit_stage4': True})"
    )
    stage_retry_counts: dict[str, int] = Field(
        default_factory=dict,
        description="阶段自愈重试计数器持久化字典 (防止进程重启后自愈计数归零)"
    )

    # 阶段 5 全季文学剧本
    completed_screenplays: dict[int, dict[str, Any]] = Field(default_factory=dict, description="定稿文学剧本 ep_XX.json 字典")

    # 第二程视听兼容桥接字段
    current_visual_episode: int = Field(default=1, description="当前视听执行集数")
    visual_audio_assets_registry: dict[str, Any] = Field(default_factory=dict, description="视听资源总表")
    episode_manifests: dict[int, Any] = Field(default_factory=dict, description="分集视听资源引单字典")
    episode_resource_manifests: dict[int, Any] = Field(default_factory=dict, description="分集视听资源引单字典(标准别名)")
    storyboard_executions: dict[int, list[Any]] = Field(default_factory=dict, description="分集分镜字典")
    episode_storyboards: dict[int, list[Any]] = Field(default_factory=dict, description="分集分镜字典(标准别名)")
    srt_exports: dict[int, str] = Field(default_factory=dict, description="分集字幕导出字典")
    episode_srt_exports: dict[int, str] = Field(default_factory=dict, description="分集字幕导出字典(标准别名)")
    episode_mode_b_manifest_checks: dict[int, dict[str, Any]] = Field(default_factory=dict, description="分集模式B自审字典")
    audio_mastering_plans: dict[int, dict[str, Any]] = Field(default_factory=dict, description="分集音频混音方案字典")
    episode_audio_masterings: dict[int, dict[str, Any]] = Field(default_factory=dict, description="分集音频混音方案字典(标准别名)")

    # 全局锚点注册表 (轻量引用)
    global_characters: dict[str, CharacterAnchorStub] = Field(default_factory=dict, description="全局角色特征锚点字典")
    global_scenes: dict[str, SceneAnchorStub] = Field(default_factory=dict, description="全局场景空间锚点字典")
    global_props: dict[str, PropAnchorStub] = Field(default_factory=dict, description="全局核心道具锚点字典")
    audio_bible_summary: AudioBibleSummary = Field(default_factory=AudioBibleSummary, description="配乐母法典简要索引")
    
    # 全季大纲任务卡
    total_episodes: int = Field(default=12, description="全季总集数")
    target_episodes: int = Field(default=12, description="全季规划总集数")
    season_outlines: dict[int, SeasonOutlineCard] = Field(default_factory=dict, description="全季各集任务卡字典")
    completed_episodes: list[int] = Field(default_factory=list, description="已完成全流程（Stage 8 验收通过）的集数列表")
    
    # 红蓝对抗自审与重试
    audit_report: dict[str, Any] = Field(default_factory=dict, description="阶段红蓝对抗自审汇报字典")
    latest_audit: RedBlueAuditReport = Field(default_factory=RedBlueAuditReport)
    stage_retry_counts: dict[str, int] = Field(default_factory=dict)
    error_message: str | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def _normalize_global_master_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            # title / selected_title
            if "title" in data and not data.get("selected_title"):
                data["selected_title"] = data["title"]
            elif "selected_title" in data and not data.get("title"):
                data["title"] = data["selected_title"]

            # dramatic_irony / core_irony
            if "core_irony" in data and not data.get("dramatic_irony"):
                data["dramatic_irony"] = data["core_irony"]
            elif "dramatic_irony" in data and not data.get("core_irony"):
                data["core_irony"] = data["dramatic_irony"]

            # duration
            if "duration_sec_per_ep" in data and not data.get("target_duration_sec"):
                data["target_duration_sec"] = float(data["duration_sec_per_ep"])
            elif "target_duration_sec" in data and not data.get("duration_sec_per_ep"):
                data["duration_sec_per_ep"] = int(data["target_duration_sec"])

            # episodes
            if "target_episodes" in data and not data.get("total_episodes"):
                data["total_episodes"] = int(data["target_episodes"])
            elif "total_episodes" in data and not data.get("target_episodes"):
                data["target_episodes"] = int(data["total_episodes"])

            # working memory 双向兼容同步
            if "ideation_working_memory" in data and not data.get("short_memory_a"):
                data["short_memory_a"] = data["ideation_working_memory"]
            elif "short_memory_a" in data and not data.get("ideation_working_memory"):
                data["ideation_working_memory"] = data["short_memory_a"]

            if "character_working_memory" in data and not data.get("short_memory_b"):
                data["short_memory_b"] = data["character_working_memory"]
            elif "short_memory_b" in data and not data.get("character_working_memory"):
                data["character_working_memory"] = data["short_memory_b"]

            if "world_building_working_memory" in data and not data.get("short_memory_c"):
                data["short_memory_c"] = data["world_building_working_memory"]
            elif "short_memory_c" in data and not data.get("world_building_working_memory"):
                data["world_building_working_memory"] = data["short_memory_c"]

            if "season_outline_working_memory" in data and not data.get("short_memory_d"):
                data["short_memory_d"] = data["season_outline_working_memory"]
            elif "short_memory_d" in data and not data.get("season_outline_working_memory"):
                data["season_outline_working_memory"] = data["short_memory_d"]

            if "inter_episode_physical_continuity" in data and not data.get("inter_episode_physical_snapshot"):
                data["inter_episode_physical_snapshot"] = data["inter_episode_physical_continuity"]
            elif "inter_episode_physical_snapshot" in data and not data.get("inter_episode_physical_continuity"):
                data["inter_episode_physical_continuity"] = data["inter_episode_physical_snapshot"]

            # 分集视听字段双向同步
            if "episode_storyboards" in data and not data.get("storyboard_executions"):
                data["storyboard_executions"] = data["episode_storyboards"]
            elif "storyboard_executions" in data and not data.get("episode_storyboards"):
                data["episode_storyboards"] = data["storyboard_executions"]

            if "episode_srt_exports" in data and not data.get("srt_exports"):
                data["srt_exports"] = data["episode_srt_exports"]
            elif "srt_exports" in data and not data.get("episode_srt_exports"):
                data["episode_srt_exports"] = data["srt_exports"]

            if "episode_audio_masterings" in data and not data.get("audio_mastering_plans"):
                data["audio_mastering_plans"] = data["episode_audio_masterings"]
            elif "audio_mastering_plans" in data and not data.get("episode_audio_masterings"):
                data["episode_audio_masterings"] = data["audio_mastering_plans"]

            if "episode_resource_manifests" in data and not data.get("episode_manifests"):
                data["episode_manifests"] = data["episode_resource_manifests"]
            elif "episode_manifests" in data and not data.get("episode_resource_manifests"):
                data["episode_resource_manifests"] = data["episode_manifests"]

            # 角色结构规范化与 global_characters 桩合成
            if "character_engine" in data and "characters_engine" not in data:
                data["characters_engine"] = data.pop("character_engine")
            if "characters" in data and "characters_engine" not in data:
                data["characters_engine"] = {"characters": data["characters"]}

            if not data.get("global_characters"):
                c_list = []
                ce = data.get("characters_engine")
                if isinstance(ce, dict):
                    c_list = ce.get("characters") or ce.get("character_profiles") or []
                elif isinstance(ce, list):
                    c_list = ce
                elif isinstance(data.get("characters"), list):
                    c_list = data["characters"]

                g_chars = {}
                for c in c_list:
                    if isinstance(c, dict) and (c.get("character_id") or c.get("id")):
                        cid = str(c.get("character_id") or c.get("id"))
                        dna = c.get("biological_dna") or {}
                        psy = c.get("psychology_4") or c.get("psychological_quad") or {}
                        g_chars[cid] = CharacterAnchorStub(
                            character_id=cid,
                            name=str(c.get("name") or cid),
                            visual_token=str(dna.get("permanent_flaws_coordinates") or dna.get("bone_structure") or ""),
                            archetype=str(psy.get("want") or c.get("personality") or "")
                        )
                if g_chars:
                    data["global_characters"] = g_chars

            # 场景道具结构规范化与 global_scenes / global_props 桩合成
            if data.get("environments_and_props"):
                ep = data["environments_and_props"]
                if isinstance(ep, dict):
                    if not data.get("global_scenes") and "environments" in ep:
                        g_scenes = {}
                        for s in ep.get("environments", []):
                            if isinstance(s, dict) and (s.get("env_id") or s.get("id")):
                                sid = str(s.get("env_id") or s.get("id"))
                                g_scenes[sid] = SceneAnchorStub(
                                    scene_id=sid,
                                    name=str(s.get("name") or sid),
                                    spatial_type=str(s.get("level") or s.get("spatial_hierarchy") or "interior")
                                )
                        data["global_scenes"] = g_scenes
                    if not data.get("global_props") and "props" in ep:
                        g_props = {}
                        for p in ep.get("props", []):
                            if isinstance(p, dict) and (p.get("prop_id") or p.get("id")):
                                pid = str(p.get("prop_id") or p.get("id"))
                                g_props[pid] = PropAnchorStub(
                                    prop_id=pid,
                                    name=str(p.get("name") or pid),
                                    level=str(p.get("level") or "hero_tier1")
                                )
                        data["global_props"] = g_props

            # audio_bible_summary 合成
            if not data.get("audio_bible_summary") and data.get("audio_bible"):
                ab = data["audio_bible"]
                if isinstance(ab, dict):
                    reg = ab.get("leitmotif_registry") or []
                    data["audio_bible_summary"] = AudioBibleSummary(
                        overall_style=str(ab.get("overall_style") or ab.get("soundtrack_anchor_style") or ""),
                        leitmotif_registry=reg if isinstance(reg, list) else []
                    )
                elif hasattr(ab, "leitmotif_registry"):
                    data["audio_bible_summary"] = AudioBibleSummary(
                        overall_style=str(getattr(ab, "overall_style", "")),
                        leitmotif_registry=list(getattr(ab, "leitmotif_registry", []))
                    )

            # season_outlines 归一化为 dict[int, SeasonOutlineCard]
            if "season_outlines" in data and isinstance(data["season_outlines"], dict):
                norm_outlines = {}
                for ep_key, item in data["season_outlines"].items():
                    try:
                        ep_num = int(ep_key)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(item, SeasonOutlineCard):
                        norm_outlines[ep_num] = item
                    elif isinstance(item, dict):
                        # 深度保留双螺旋全量字段，严防通过显式参数构造造成数据截断丢弃
                        card_dict = dict(item)
                        card_dict.setdefault("episode_number", ep_num)
                        card_dict.setdefault("episode_id", ep_num)
                        norm_outlines[ep_num] = SeasonOutlineCard.model_validate(card_dict)
                data["season_outlines"] = norm_outlines

        return data

    @property
    def title(self) -> str:
        return self.selected_title

    @title.setter
    def title(self, val: str) -> None:
        self.selected_title = val

    @property
    def core_irony(self) -> str:
        return self.dramatic_irony

    @core_irony.setter
    def core_irony(self, val: str) -> None:
        self.dramatic_irony = val

    @property
    def character_engine(self) -> Any:
        return self.characters_engine

    @character_engine.setter
    def character_engine(self, val: Any) -> None:
        self.characters_engine = val

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            if self.model_extra is None:
                self.__pydantic_extra__ = {}
            self.model_extra[key] = value

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (bool(self.model_extra) and key in self.model_extra)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def to_state_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def extract_episode_substate(self, episode_number: int) -> EpisodeScopedSubState:
        """从当前全局文学状态中切片提取单集独立执行子状态。"""
        raw_card = self.season_outlines.get(episode_number)
        if isinstance(raw_card, SeasonOutlineCard):
            card = raw_card
        elif isinstance(raw_card, dict):
            c_dict = dict(raw_card)
            c_dict.setdefault("episode_number", episode_number)
            c_dict.setdefault("episode_id", episode_number)
            card = SeasonOutlineCard.model_validate(c_dict)
        else:
            card = SeasonOutlineCard(
                episode_number=episode_number,
                episode_id=episode_number,
                title=f"第{episode_number}集"
            )

        incoming_continuity = None
        if self.inter_episode_physical_continuity and isinstance(self.inter_episode_physical_continuity, dict):
            incoming_continuity = InterEpisodePhysicalContinuity.model_validate(self.inter_episode_physical_continuity)

        rel_chars = list(self.global_characters.values())
        rel_scenes = list(self.global_scenes.values())
        rel_props = list(self.global_props.values())

        return EpisodeScopedSubState(
            drama_id=self.drama_id,
            episode_number=episode_number,
            episode_id=episode_number,
            current_visual_episode=episode_number,
            current_stage=5,
            task_outline=card,
            incoming_physical_continuity=incoming_continuity,
            inherited_physical_continuity=incoming_continuity,
            relevant_character_stubs=rel_chars,
            relevant_scene_stubs=rel_scenes,
            relevant_prop_stubs=rel_props,
        )


class EpisodeScopedSubState(BaseModel):
    """【单集视听工程独立子状态】第二程 (Stage 5 ~ Stage 8) 局部执行子图状态。
    
    架构特征:
    1. 瞬时生命周期: 启动该集执行时从数据库/全局上下文按需实例化，Stage 8 终态落库后即刻销毁;
    2. 体积严格约束: 单集全流程内存体积控制在 100KB 以内;
    3. 并发安全: 每集具有独立的上下文，支持多集多卡多线程流水线并行调度;
    4. 资产引用化: 镜头生图、音轨音频全链路通过 URI 指针流转，坚决杜绝内嵌大对象。
    """
    model_config = ConfigDict(extra="allow")
    drama_id: int = Field(default=0, description="所属短剧项目 ID")
    episode_number: int = Field(default=1, description="当前单集编号 (1..NN)")
    episode_id: int = Field(default=1, description="集数 ID (同 episode_number)")
    current_visual_episode: int = Field(default=1, description="当前单集编号 (兼容别名)")
    current_stage: int = Field(default=5, description="单集当前阶段 (5..8)")
    
    # 外部注入的静态单集任务卡
    task_outline: SeasonOutlineCard = Field(default_factory=lambda: SeasonOutlineCard(episode_number=1), description="本集大纲任务卡")
    
    # 跨集物理连续性快照 (接棒与交棒)
    incoming_physical_continuity: InterEpisodePhysicalContinuity | None = Field(
        default=None,
        description="自上一集继承的 0 秒物理咬合快照 (第 1 集为 None)"
    )
    inherited_physical_continuity: InterEpisodePhysicalContinuity | None = Field(
        default=None,
        description="向后兼容旧命名：自上一集继承的 0 秒物理咬合快照"
    )
    outgoing_physical_continuity: InterEpisodePhysicalContinuity | None = Field(
        default=None,
        description="本集结尾封存的物理状态快照，供下一集消费"
    )

    # 轻量锚点桩集合
    relevant_character_stubs: list[CharacterAnchorStub] = Field(default_factory=list, description="本集出场角色轻量桩")
    relevant_scene_stubs: list[SceneAnchorStub] = Field(default_factory=list, description="本集登场场景轻量桩")
    relevant_prop_stubs: list[PropAnchorStub] = Field(default_factory=list, description="本集使用道具轻量桩")
    
    # 单集独有局部资产集合（群演、道具等）
    local_assets: list[EpisodeLocalAsset] = Field(default_factory=list, description="单集局部资产（如分集独有群演、临时道具）")

    # Stage 5 产物：单集文学剧本
    screenplay: LiteraryScreenplayEpisodeModel | None = Field(default=None, description="定稿文学剧本")
    
    # Stage 6 产物：单集增量资产引单
    episode_manifest: EpisodeResourceManifest | None = Field(default=None, description="单集视听资源引单")
    resource_manifest: EpisodeResourceManifest | None = Field(default=None, description="向后兼容旧命名：单集视听资源引单")
    
    # Stage 7 产物：单集分镜列表与导出 SRT
    storyboard_shots: list[StoryboardShot | StoryboardShotStub | dict[str, Any]] = Field(
        default_factory=list,
        description="单集分镜执行镜头列表"
    )
    srt_content: str = Field(default="", description="单集 SRT 字幕导出文本")
    
    # Stage 8 产物：单集多轨音频工程
    audio_mastering: AudioMasteringConfig | None = Field(default=None, description="单集多轨音频母带工程配置")
    
    # 模式 B 9项自审检查清单
    mode_b_manifest_check: dict[str, Any] = Field(default_factory=dict, description="模式 B 多图参考自审")

    # 单集执行状态与错误标记
    is_completed: bool = Field(default=False, description="本集视听全流程是否已成功交付落库")
    audit_report: dict[str, Any] = Field(default_factory=dict, description="阶段红蓝对抗自审汇报字典")
    latest_audit: RedBlueAuditReport = Field(default_factory=RedBlueAuditReport)
    stage_retry_counts: dict[str, int] = Field(default_factory=dict)
    error_message: str | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def _normalize_substate_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            ep_num = data.get("episode_number") or data.get("episode_id") or data.get("current_visual_episode") or 1
            data["episode_number"] = int(ep_num)
            data["episode_id"] = int(ep_num)
            data["current_visual_episode"] = int(ep_num)

            if data.get("inherited_physical_continuity") and not data.get("incoming_physical_continuity"):
                data["incoming_physical_continuity"] = data["inherited_physical_continuity"]
            elif data.get("incoming_physical_continuity") and not data.get("inherited_physical_continuity"):
                data["inherited_physical_continuity"] = data["incoming_physical_continuity"]

            if data.get("resource_manifest") and not data.get("episode_manifest"):
                data["episode_manifest"] = data["resource_manifest"]
            elif data.get("episode_manifest") and not data.get("resource_manifest"):
                data["resource_manifest"] = data["episode_manifest"]

            if data.get("script") and not data.get("screenplay"):
                data["screenplay"] = data["script"]
            elif data.get("screenplay") and not data.get("script"):
                data["script"] = data["screenplay"]

            if "storyboard_executions" in data and not data.get("storyboard_shots"):
                data["storyboard_shots"] = data["storyboard_executions"]
            if "storyboards" in data and not data.get("storyboard_shots"):
                data["storyboard_shots"] = data["storyboards"]

            if "episode_srt_export" in data and not data.get("srt_content"):
                data["srt_content"] = data["episode_srt_export"]

            if "audio_mastering_plan" in data and not data.get("audio_mastering"):
                data["audio_mastering"] = data["audio_mastering_plan"]
        return data

    @property
    def episode_num(self) -> int:
        return self.episode_number

    @episode_num.setter
    def episode_num(self, val: int) -> None:
        self.episode_number = val
        self.episode_id = val
        self.current_visual_episode = val

    @property
    def storyboards(self) -> list[Any]:
        return self.storyboard_shots

    @storyboards.setter
    def storyboards(self, val: list[Any]) -> None:
        self.storyboard_shots = val

    @property
    def srt(self) -> str:
        return self.srt_content

    @srt.setter
    def srt(self, val: str) -> None:
        self.srt_content = val

    @property
    def srt_export(self) -> str:
        return self.srt_content

    @srt_export.setter
    def srt_export(self, val: str) -> None:
        self.srt_content = val

    @property
    def audio_mastering_plan(self) -> AudioMasteringConfig | None:
        return self.audio_mastering

    @audio_mastering_plan.setter
    def audio_mastering_plan(self, val: AudioMasteringConfig | None) -> None:
        self.audio_mastering = val

    @property
    def mastering_config(self) -> AudioMasteringConfig | None:
        return self.audio_mastering

    @mastering_config.setter
    def mastering_config(self, val: AudioMasteringConfig | None) -> None:
        self.audio_mastering = val

    @property
    def script(self) -> LiteraryScreenplayEpisodeModel | None:
        return self.screenplay

    @script.setter
    def script(self, val: LiteraryScreenplayEpisodeModel | None) -> None:
        self.screenplay = val

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            if self.model_extra is None:
                self.__pydantic_extra__ = {}
            self.model_extra[key] = value

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (bool(self.model_extra) and key in self.model_extra)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def to_state_dict(self) -> dict[str, Any]:
        return self.model_dump()


class IndustrialDramaMasterState(BaseModel):
    """【已废弃兼容模型 / Deprecated Legacy State】
    两程九阶全息闭环全局状态旧模型 (Industrial Master State)。
    
    架构升级说明：
    根据分层状态机与持久化执行架构方案，本项目已全面解耦为：
    - GlobalDramaMasterState: 第一程轻量全局文学状态 (<50KB)
    - EpisodeScopedSubState: 第二程单集独立视听分镜状态 (<100KB)
    
    保留此类仅用于向下兼容旧版测试与过渡期，所有新业务与主图管线请使用 GlobalDramaMasterState。
    """
    drama_id: int = Field(default=0, description="短剧项目 ID")
    journey: Literal["journey_1_literary", "journey_2_visual", "completed"] = Field(
        default="journey_1_literary",
        description="当前工业程：第一程文学故事工程 / 第二程视听与分镜工程"
    )
    current_stage: int = Field(default=1, description="当前阶段编号 (1 ~ 8)")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="执行控制模式：stage_by_stage(单步精细)/two_journey(双程总控)/full_auto(全自动极速)"
    )
    
    # 阶段 1
    user_idea: str = Field(default="", description="用户原始核心构想与立项故事创意")
    selected_title: str = Field(default="", description="敲定片名")
    candidate_titles: CandidateTitleMatrix = Field(default_factory=CandidateTitleMatrix)
    aspect_ratio: str = Field(default="9:16", description="画幅比例")
    target_duration_sec: float = Field(default=120.0, description="单集规划时长")
    genre: str = Field(default="剧情", description="类型")
    visual_style: str = Field(default="真人电影/超写实", description="项目风格")
    negative_rules: DoubleTrackProhibitions = Field(default_factory=DoubleTrackProhibitions)
    logline: str = Field(default="", description="工业级 Logline")
    dramatic_irony: str = Field(default="", description="核心讽刺")
    grand_payoff: str = Field(default="", description="终局核爆点")
    
    # 短期记忆便签 A/B/C/D
    short_memory_a: str = Field(default="", description="短期记忆 A：人设禁令子集 + 核心讽刺")
    short_memory_b: str = Field(default="", description="短期记忆 B：肖像骨相DNA + 真实服饰代码 + 关系死结网")
    short_memory_c: str = Field(default="", description="短期记忆 C：大纲冲突要素包")
    short_memory_d: str = Field(default="", description="短期记忆 D：全季分集剧作路线图")
    
    # 语义化工作便签 Working Memory (新分层架构标准)
    ideation_working_memory: str = Field(default="", description="阶段 1 创意工作便签：人设禁令子集 + 核心讽刺")
    character_working_memory: str = Field(default="", description="阶段 2 角色工作便签：肖像骨相DNA + 真实服饰代码 + 关系死结网")
    world_building_working_memory: str = Field(default="", description="阶段 3 空间物证工作便签：核心空间做旧 + 物证拟音")
    season_outline_working_memory: str = Field(default="", description="阶段 4 大纲工作便签：全季分集剧作路线图")
    inter_episode_physical_continuity: dict[str, Any] | None = Field(default=None, description="集间0秒物理咬合连续性快照")
    
    # 阶段 2 人设 (微观生物肖像骨相DNA、生活质感服化道代码、心理四元组、语言行为指纹、双轨关系网、四阶段情感流转)
    characters_engine: dict[str, Any] | list[Any] = Field(default_factory=dict)
    character_tokens: list[str] | dict[str, Any] = Field(
        default_factory=list,
        description="阶段 2 锁定的角色Token白名单 (如 LUCHEN, HANTAI)"
    )
    dual_track_relationships: list[DualTrackRelationshipItem] = Field(
        default_factory=list,
        description="阶段 2：全剧利益与情感双轨关系网络矩阵"
    )
    emotional_arc_trajectories: list[EmotionalArcTrajectory] = Field(
        default_factory=list,
        description="阶段 2：核心角色全季动态情感流转线路图"
    )
    
    # 阶段 3 空间与物证 (三层做旧、反转道具与阻力拟音)
    environments_and_props: dict[str, Any] = Field(default_factory=dict)
    scene_tokens: list[str] | dict[str, Any] = Field(
        default_factory=list,
        description="阶段 3 锁定的场景Token白名单 (如 WAREHOUSE, PENTHOUSE)"
    )
    prop_tokens: list[str] | dict[str, Any] = Field(
        default_factory=list,
        description="阶段 3 锁定的道具Token白名单 (如 LETTER, ROSARY)"
    )
    
    # 阶段 4 大纲与音乐主题动机
    audio_bible: AudioBible = Field(default_factory=AudioBible)
    season_outlines: dict[int, SeasonOutlineCard | dict[str, Any]] = Field(default_factory=dict)
    mini_arc_units: list[dict[str, Any]] = Field(
        default_factory=list,
        description="阶段 4：全季戏剧小高潮单元划分 (3-4集/单元)"
    )
    
    # 阶段 5 全季文学剧本波次与集数管理
    current_mini_arc_index: int = Field(default=1, description="当前戏剧波次（3-4集一组）")
    total_episodes: int = Field(default=12, description="全季总集数")
    completed_screenplays: dict[int, dict[str, Any]] = Field(default_factory=dict, description="定稿文学剧本 ep_XX.json 字典")
    inter_episode_physical_snapshot: dict[str, Any] | None = Field(default=None, description="集间0秒物理咬合快照")
    literary_journey_locked: bool = Field(default=False, description="第一程全季文学定稿总锁")
    
    # 第二程真理源总库与单集循环
    current_visual_episode: int = Field(default=1, description="当前正在执行视听工程的集数 (1..NN)")
    visual_audio_assets_registry: dict[str, Any] | VisualAudioAssetsRegistryModel = Field(
        default_factory=dict,
        description="05_visual_audio_assets.json 真理源总库"
    )
    episode_resource_manifests: dict[int, EpisodeResourceManifest] = Field(default_factory=dict)
    episode_storyboards: dict[int, list[StoryboardShot]] = Field(default_factory=dict)
    episode_srt_exports: dict[int, str] = Field(default_factory=dict)
    episode_audio_masterings: dict[int, AudioMasteringConfig | dict[str, Any]] = Field(default_factory=dict)
    episode_mode_b_manifest_checks: dict[int, dict[str, Any]] = Field(
        default_factory=dict,
        description="各集模式 B 多图参考 9 项自审清单"
    )
    
    # 统一红蓝对抗报告
    latest_audit: RedBlueAuditReport = Field(default_factory=RedBlueAuditReport)

    # 阶段 1 扩展字段 (对齐 SKILL1.md RULE-VI-01)
    slug: str = Field(default="", description="项目唯一英文标识 (如 seven_letters)")
    target_video_engine: str = Field(default="wan3.0", description="全剧目标视频生成引擎底模 (wan3.0/seedance2.5/minimax_h3)")
    duration_sec_per_ep: int = Field(default=120, description="单集规划秒数")
    target_episodes: int = Field(default=12, description="全季规划总集数")
    forbidden_cliches_10: list[str] = Field(default_factory=list, description="10大老套因果禁令")
    forbidden_cheap_tropes_3: list[str] = Field(default_factory=list, description="3大廉价爽点禁令")

    # 状态机循环自愈计数器与错误信息 (对齐 RULE-IV-02)
    stage_retry_counts: dict[str, int] = Field(default_factory=dict, description="各阶段独立自愈重试计数器")
    error_message: str | None = Field(default=None, description="错误终止节点提示信息")

    @model_validator(mode="before")
    @classmethod
    def _normalize_master_state_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "character_engine" in data and "characters_engine" not in data:
                data["characters_engine"] = data.pop("character_engine")
            if "characters" in data and "characters_engine" not in data:
                data["characters_engine"] = data.pop("characters")
            if "episode_manifests" in data and "episode_resource_manifests" not in data:
                data["episode_resource_manifests"] = data.pop("episode_manifests")
            if "storyboard_executions" in data and "episode_storyboards" not in data:
                data["episode_storyboards"] = data.pop("storyboard_executions")
            if "srt_exports" in data and "episode_srt_exports" not in data:
                data["episode_srt_exports"] = data.pop("srt_exports")
            if "audio_mastering_plans" in data and "episode_audio_masterings" not in data:
                data["episode_audio_masterings"] = data.pop("audio_mastering_plans")
            if "mode_b_manifest_checks" in data and "episode_mode_b_manifest_checks" not in data:
                data["episode_mode_b_manifest_checks"] = data.pop("mode_b_manifest_checks")

            # 语义化工作便签双向同步
            if "ideation_working_memory" in data and not data.get("short_memory_a"):
                data["short_memory_a"] = data["ideation_working_memory"]
            elif "short_memory_a" in data and not data.get("ideation_working_memory"):
                data["ideation_working_memory"] = data["short_memory_a"]

            if "character_working_memory" in data and not data.get("short_memory_b"):
                data["short_memory_b"] = data["character_working_memory"]
            elif "short_memory_b" in data and not data.get("character_working_memory"):
                data["character_working_memory"] = data["short_memory_b"]

            if "world_building_working_memory" in data and not data.get("short_memory_c"):
                data["short_memory_c"] = data["world_building_working_memory"]
            elif "short_memory_c" in data and not data.get("world_building_working_memory"):
                data["world_building_working_memory"] = data["short_memory_c"]

            if "season_outline_working_memory" in data and not data.get("short_memory_d"):
                data["short_memory_d"] = data["season_outline_working_memory"]
            elif "short_memory_d" in data and not data.get("season_outline_working_memory"):
                data["season_outline_working_memory"] = data["short_memory_d"]

            if "inter_episode_physical_continuity" in data and not data.get("inter_episode_physical_snapshot"):
                data["inter_episode_physical_snapshot"] = data["inter_episode_physical_continuity"]
            elif "inter_episode_physical_snapshot" in data and not data.get("inter_episode_physical_continuity"):
                data["inter_episode_physical_continuity"] = data["inter_episode_physical_snapshot"]
        return data

    @property
    def character_engine(self) -> Any:
        return self.characters_engine

    @character_engine.setter
    def character_engine(self, val: Any) -> None:
        self.characters_engine = val

    @property
    def storyboard_executions(self) -> dict[int, list[StoryboardShot]]:
        return self.episode_storyboards

    @storyboard_executions.setter
    def storyboard_executions(self, val: dict[int, list[StoryboardShot]]) -> None:
        self.episode_storyboards = val

    @property
    def storyboards(self) -> dict[int, list[StoryboardShot]]:
        return self.episode_storyboards

    @storyboards.setter
    def storyboards(self, val: dict[int, list[StoryboardShot]]) -> None:
        self.episode_storyboards = val

    @property
    def episode_manifests(self) -> dict[int, EpisodeResourceManifest]:
        return self.episode_resource_manifests

    @episode_manifests.setter
    def episode_manifests(self, val: dict[int, EpisodeResourceManifest]) -> None:
        self.episode_resource_manifests = val

    @property
    def srt_exports(self) -> dict[int, str]:
        return self.episode_srt_exports

    @srt_exports.setter
    def srt_exports(self, val: dict[int, str]) -> None:
        self.episode_srt_exports = val

    @property
    def audio_mastering_plans(self) -> dict[int, AudioMasteringConfig | dict[str, Any]]:
        return self.episode_audio_masterings

    @audio_mastering_plans.setter
    def audio_mastering_plans(self, val: dict[int, Any]) -> None:
        self.episode_audio_masterings = val

    @property
    def mode_b_manifest_checks(self) -> dict[int, dict[str, Any]]:
        return self.episode_mode_b_manifest_checks

    @mode_b_manifest_checks.setter
    def mode_b_manifest_checks(self, val: dict[int, dict[str, Any]]) -> None:
        self.episode_mode_b_manifest_checks = val

    def get(self, key: str, default: Any = None) -> Any:
        """支持字典式安全访问，确保向后兼容与平滑过渡。"""
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        """将 Pydantic 状态完整序列化为字典。"""
        return self.model_dump()

    def to_state_dict(self) -> IndustrialDramaState:
        """转换为标准 LangGraph IndustrialDramaState TypedDict 字典。"""
        return self.model_dump()

    def to_global_master_state(self) -> GlobalDramaMasterState:
        """导出轻量全局文学父图状态 (尺寸严格控制在 50KB 以内)。"""
        global_chars: dict[str, CharacterAnchorStub] = {}
        if isinstance(self.characters_engine, dict):
            c_list = self.characters_engine.get("characters") or self.characters_engine.get("character_profiles") or []
            if isinstance(c_list, list):
                for c in c_list:
                    if isinstance(c, dict) and c.get("character_id"):
                        cid = str(c["character_id"])
                        global_chars[cid] = CharacterAnchorStub(
                            character_id=cid,
                            name=str(c.get("name") or cid),
                            visual_token=str(c.get("biological_dna", {}).get("permanent_flaws_coordinates") or ""),
                            archetype=str(c.get("psychology_4", {}).get("want") or "")
                        )
        
        global_scenes: dict[str, SceneAnchorStub] = {}
        global_props: dict[str, PropAnchorStub] = {}
        if isinstance(self.environments_and_props, dict):
            for s in self.environments_and_props.get("environments", []):
                if isinstance(s, dict) and s.get("env_id"):
                    sid = str(s["env_id"])
                    global_scenes[sid] = SceneAnchorStub(
                        scene_id=sid,
                        name=str(s.get("name") or sid),
                        spatial_type=str(s.get("level") or "interior")
                    )
            for p in self.environments_and_props.get("props", []):
                if isinstance(p, dict) and p.get("prop_id"):
                    pid = str(p["prop_id"])
                    global_props[pid] = PropAnchorStub(
                        prop_id=pid,
                        name=str(p.get("name") or pid),
                        level=str(p.get("level") or "hero_tier1")
                    )

        outlines: dict[int, SeasonOutlineCard] = {}
        for ep_num, card in self.season_outlines.items():
            if isinstance(card, SeasonOutlineCard):
                outlines[int(ep_num)] = card
            elif isinstance(card, dict):
                # 完整透传双螺旋等全部大纲属性，杜绝字段截断丢弃
                c_dict = dict(card)
                c_dict.setdefault("episode_number", int(ep_num))
                c_dict.setdefault("episode_id", int(ep_num))
                outlines[int(ep_num)] = SeasonOutlineCard.model_validate(c_dict)

        return GlobalDramaMasterState(
            drama_id=self.drama_id,
            slug=self.slug,
            journey=self.journey,
            current_stage=self.current_stage,
            selected_title=self.selected_title,
            candidate_titles=self.candidate_titles,
            aspect_ratio=self.aspect_ratio,
            target_duration_sec=self.target_duration_sec,
            genre=self.genre,
            visual_style=self.visual_style,
            logline=self.logline,
            dramatic_irony=self.dramatic_irony,
            grand_payoff=self.grand_payoff,
            negative_rules=self.negative_rules,
            ideation_working_memory=self.ideation_working_memory or self.short_memory_a,
            character_working_memory=self.character_working_memory or self.short_memory_b,
            world_building_working_memory=self.world_building_working_memory or self.short_memory_c,
            season_outline_working_memory=self.season_outline_working_memory or self.short_memory_d,
            global_characters=global_chars,
            global_scenes=global_scenes,
            global_props=global_props,
            total_episodes=self.total_episodes,
            season_outlines=outlines,
            completed_episodes=list(self.completed_screenplays.keys())
        )

    def extract_episode_substate(self, episode_number: int) -> EpisodeScopedSubState:
        """从当前大状态中按需切片提取单集独立执行子状态 (尺寸严格控制在 100KB 以内)。"""
        outline_obj = self.season_outlines.get(episode_number)
        if isinstance(outline_obj, SeasonOutlineCard):
            task_outline = outline_obj
        elif isinstance(outline_obj, dict):
            outline_dict = dict(outline_obj)
            outline_dict.setdefault("episode_number", episode_number)
            outline_dict.setdefault("episode_id", episode_number)
            task_outline = SeasonOutlineCard.model_validate(outline_dict)
        else:
            task_outline = SeasonOutlineCard(
                episode_number=episode_number,
                episode_id=episode_number,
                title=f"第{episode_number}集"
            )

        incoming_continuity = None
        if self.inter_episode_physical_continuity and isinstance(self.inter_episode_physical_continuity, dict):
            incoming_continuity = InterEpisodePhysicalContinuity.model_validate(self.inter_episode_physical_continuity)

        raw_script = self.completed_screenplays.get(episode_number)
        screenplay_obj = None
        if raw_script:
            if isinstance(raw_script, LiteraryScreenplayEpisodeModel):
                screenplay_obj = raw_script
            elif isinstance(raw_script, dict):
                screenplay_obj = LiteraryScreenplayEpisodeModel.model_validate(raw_script)

        manifest_obj = self.episode_resource_manifests.get(episode_number)
        shots = self.episode_storyboards.get(episode_number) or []
        srt = self.episode_srt_exports.get(episode_number) or ""
        audio = self.episode_audio_masterings.get(episode_number)
        audio_obj = None
        if audio:
            if isinstance(audio, AudioMasteringConfig):
                audio_obj = audio
            elif isinstance(audio, dict):
                audio_obj = AudioMasteringConfig.model_validate(audio)

        return EpisodeScopedSubState(
            drama_id=self.drama_id,
            episode_number=episode_number,
            current_stage=max(5, self.current_stage),
            task_outline=task_outline,
            incoming_physical_continuity=incoming_continuity,
            screenplay=screenplay_obj,
            episode_manifest=manifest_obj,
            storyboard_shots=shots,
            srt_content=srt,
            audio_mastering=audio_obj,
            is_completed=(episode_number in self.episode_storyboards and episode_number in self.episode_audio_masterings)
        )

    def merge_episode_substate(self, substate: EpisodeScopedSubState) -> None:
        """将执行完成的单集独立子状态增量合并回大状态。"""
        ep_num = substate.episode_number
        if substate.screenplay:
            self.completed_screenplays[ep_num] = substate.screenplay.model_dump()
        if substate.episode_manifest:
            self.episode_resource_manifests[ep_num] = substate.episode_manifest
        if substate.storyboard_shots:
            self.episode_storyboards[ep_num] = substate.storyboard_shots
        if substate.srt_content:
            self.episode_srt_exports[ep_num] = substate.srt_content
        if substate.audio_mastering:
            self.episode_audio_masterings[ep_num] = substate.audio_mastering
        if substate.outgoing_physical_continuity:
            self.inter_episode_physical_continuity = substate.outgoing_physical_continuity.model_dump()
            self.inter_episode_physical_snapshot = self.inter_episode_physical_continuity


# =========================================================================
# 【规则编号: RULE-VI-01 ~ RULE-VI-08】标准 TypedDict 与 Pydantic 数据契约体系
# =========================================================================

class PreviousEpisodePickup(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】0 秒接棒物理快照字典 (第 2 集及之后强制包含)。"""
    inherited_from_episode: int
    pickup_state_description: str
    # 兼容别名
    freeze_frame_desc: str
    episode_index: int


class GoldenCliffhangerHook(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】结尾黄金悬念钩子三位一体字典。"""
    physical_crisis_action: str
    cliffhanger_dialogue: str
    acoustic_drop_cue: str
    # 兼容别名
    hook_action: str
    hook_dialogue: str
    hook_audio_braam: str


class EpisodeEndPhysicalDelta(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】集尾物理状态快照字典 (封存最后一秒真实物理残局)。"""
    timeline_progress: str
    character_pose: str
    held_props_and_injuries: str
    environment_and_weather: str
    # 兼容别名
    timeline_progress_sec: float
    posture_and_injuries: str
    carried_props_status: str
    weather_and_light: str
    freeze_frame_desc: str
    location: str
    last_scene: str
    episode_index: int


class StageAuditReport(TypedDict, total=False):
    """【规则编号: RULE-IV-01】单阶段红蓝对抗自审汇报字典。"""
    blue_team: str
    red_team_critic: str
    verdict: Literal["GREEN_APPROVED", "YELLOW_WARNING", "RED_BLOCKED"]
    blocking_issues: list[str]
    warning_suggestions: list[str]


class LiteraryScreenplayEpisode(TypedDict, total=False):
    """【规则编号: RULE-VI-05】阶段 5 标准单集文学剧本 (episodes_screenplay/ep_XX.json)。"""
    episode_id: int
    episode_title: str
    planned_duration_sec: float
    dramatic_arc_unit: str
    core_dramatic_task: str
    previous_episode_0s_pickup: PreviousEpisodePickup | None
    screenplay_text: str
    golden_cliffhanger_hook: GoldenCliffhangerHook
    episode_end_physical_delta: EpisodeEndPhysicalDelta
    audit_report: StageAuditReport
    # 兼容与扩展字段
    episode_num: int
    title: str
    body_markdown: str
    hook_3s: str
    ending_cliffhanger: str
    outgoing_physical_snapshot: dict[str, Any]
    scene_header: str
    characters_present: list[str]
    core_props: list[str]
    commercial_tag: str
    ast_data: dict[str, Any]


class GoldenCliffhangerHookModel(BaseModel):
    """【规则编号: RULE-II-02 / RULE-VI-05】结尾黄金悬念钩子三位一体结构化模型。"""
    model_config = ConfigDict(extra="allow")
    physical_crisis_action: str = Field(default="", description="物理危机动作（如两人在碎石路上对峙，刀锋抵喉）")
    cliffhanger_dialogue: str = Field(default="", description="绝杀对白（如‘这是小县城，这里没有头条只有过日子！’）")
    acoustic_drop_cue: str = Field(default="[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！", description="声学骤停/重击标记")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            action = d.get("physical_crisis_action") or d.get("hook_action") or d.get("action") or ""
            dialogue = d.get("cliffhanger_dialogue") or d.get("hook_dialogue") or d.get("dialogue") or ""
            acoustic = d.get("acoustic_drop_cue") or d.get("hook_audio_braam") or d.get("audio_cue") or "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"
            d["physical_crisis_action"] = str(action)
            d["cliffhanger_dialogue"] = str(dialogue)
            d["acoustic_drop_cue"] = str(acoustic)
            # 同时保留 legacy 别名
            d.setdefault("hook_action", str(action))
            d.setdefault("hook_dialogue", str(dialogue))
            d.setdefault("hook_audio_braam", str(acoustic))
            return d
        return data

    @property
    def hook_action(self) -> str:
        return self.physical_crisis_action

    @property
    def hook_dialogue(self) -> str:
        return self.cliffhanger_dialogue

    @property
    def hook_audio_braam(self) -> str:
        return self.acoustic_drop_cue

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["physical_crisis_action"] = self.physical_crisis_action
        d["cliffhanger_dialogue"] = self.cliffhanger_dialogue
        d["acoustic_drop_cue"] = self.acoustic_drop_cue
        d["hook_action"] = self.hook_action
        d["hook_dialogue"] = self.hook_dialogue
        d["hook_audio_braam"] = self.hook_audio_braam
        return d

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)


class EpisodeEndPhysicalDeltaModel(BaseModel):
    """【规则编号: RULE-II-02 / RULE-VI-05】集尾物理状态快照模型 (封存最后一秒真实物理残局)。"""
    model_config = ConfigDict(extra="allow")
    timeline_progress: str = Field(default="", description="时间线进度（故事时间、倒计时等）")
    character_pose: str = Field(default="", description="角色身体姿态、动作与微表情")
    held_props_and_injuries: str = Field(default="", description="手持道具位置、状态与肉体伤势")
    environment_and_weather: str = Field(default="", description="环境物理与天气光影状态")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            # 提取时间线
            time_val = d.get("timeline_progress") or d.get("timeline_progress_sec") or d.get("timeline") or ""
            if isinstance(time_val, (int, float)):
                time_val = f"单集第 {time_val} 秒"
            # 提取角色姿态
            c_pose = d.get("character_pose") or d.get("posture_and_injuries") or ""
            if not c_pose and isinstance(d.get("character_states"), dict):
                c_pose = "; ".join(f"{k}: {v}" for k, v in d["character_states"].items())
            # 提取道具与伤残
            props_injuries = d.get("held_props_and_injuries") or d.get("carried_props_status") or ""
            if not props_injuries and isinstance(d.get("prop_possession"), dict):
                props_injuries = "; ".join(f"{k}: {v}" for k, v in d["prop_possession"].items())
            # 提取环境与天气
            env_weather = d.get("environment_and_weather") or d.get("weather_and_light") or d.get("environmental_state") or d.get("location") or ""
            
            d["timeline_progress"] = str(time_val)
            d["character_pose"] = str(c_pose)
            d["held_props_and_injuries"] = str(props_injuries)
            d["environment_and_weather"] = str(env_weather)

            # 保留 legacy 别名
            d.setdefault("timeline_progress_sec", 120.0)
            d.setdefault("posture_and_injuries", str(c_pose))
            d.setdefault("carried_props_status", str(props_injuries))
            d.setdefault("weather_and_light", str(env_weather))
            d.setdefault("freeze_frame_desc", d.get("freeze_frame_desc") or str(c_pose))
            return d
        return data

    @property
    def posture_and_injuries(self) -> str:
        return self.character_pose

    @property
    def carried_props_status(self) -> str:
        return self.held_props_and_injuries

    @property
    def weather_and_light(self) -> str:
        return self.environment_and_weather

    @property
    def timeline_progress_sec(self) -> float:
        val = getattr(self, "__pydantic_extra__", {}).get("timeline_progress_sec") if self.__pydantic_extra__ else None
        return float(val) if val is not None else 120.0

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["timeline_progress"] = self.timeline_progress
        d["character_pose"] = self.character_pose
        d["held_props_and_injuries"] = self.held_props_and_injuries
        d["environment_and_weather"] = self.environment_and_weather
        d["timeline_progress_sec"] = self.timeline_progress_sec
        d["posture_and_injuries"] = self.posture_and_injuries
        d["carried_props_status"] = self.carried_props_status
        d["weather_and_light"] = self.weather_and_light
        return d

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)


class PreviousEpisodePickupModel(BaseModel):
    """【规则编号: RULE-II-02 / RULE-VI-05】0 秒接棒物理快照模型 (第 2 集及之后强制包含)。"""
    model_config = ConfigDict(extra="allow")
    inherited_from_episode: int = Field(default=0, description="继承自上一集的集数编号")
    pickup_state_description: str = Field(default="", description="接棒物理状态描写（身体姿态/手持道具/环境伤势）")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            ep_from = d.get("inherited_from_episode") or d.get("episode_index") or d.get("inherited_from") or 0
            desc = d.get("pickup_state_description") or d.get("freeze_frame_desc") or d.get("description") or d.get("pickup_desc") or ""
            d["inherited_from_episode"] = int(ep_from) if str(ep_from).isdigit() else 0
            d["pickup_state_description"] = str(desc)
            # legacy alias
            d.setdefault("freeze_frame_desc", str(desc))
            return d
        return data

    @property
    def freeze_frame_desc(self) -> str:
        return self.pickup_state_description

    @property
    def episode_index(self) -> int:
        return self.inherited_from_episode

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["inherited_from_episode"] = self.inherited_from_episode
        d["pickup_state_description"] = self.pickup_state_description
        d["freeze_frame_desc"] = self.freeze_frame_desc
        d["episode_index"] = self.episode_index
        return d

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)


class LiteraryScreenplayEpisodeModel(BaseModel):
    """【规则编号: RULE-VI-05】阶段 5 标准单集文学剧本模型 (episodes_screenplay/ep_XX.json)。"""
    model_config = ConfigDict(extra="allow")
    episode_id: int = Field(default=1, description="集数编号 (1..NN)")
    episode_title: str = Field(default="", description="单集文学剧本规范标题")
    planned_duration_sec: float = Field(default=120.0, description="单集规划秒数 (如 120.0)")
    dramatic_arc_unit: str = Field(default="", description="所属戏剧微弧单元 (如：单元 A (第 01 - 03 集) · 阶段 A 防御与伪装期)")
    core_dramatic_task: str = Field(default="", description="单集核心戏剧任务/冲突卡点")
    previous_episode_0s_pickup: PreviousEpisodePickupModel | None = Field(default=None, description="上集 0 秒接棒物理快照 (第 2 集起必填)")
    screenplay_text: str = Field(default="", description="影视级标准文学剧本正文 (含时空场景标头、动作行动词、发声阻力括注、对白与三大声学标记)")
    golden_cliffhanger_hook: GoldenCliffhangerHookModel = Field(default_factory=GoldenCliffhangerHookModel, description="结尾三位一体黄金悬念钩子")
    episode_end_physical_delta: EpisodeEndPhysicalDeltaModel = Field(default_factory=EpisodeEndPhysicalDeltaModel, description="集尾最后一秒四维物理快照")
    audit_report: dict[str, Any] = Field(default_factory=dict, description="单阶段红蓝对抗自审汇报")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            ep_id = d.get("episode_id") or d.get("episode_num") or d.get("episode_number") or 1
            d["episode_id"] = int(ep_id) if str(ep_id).isdigit() else 1
            title = d.get("episode_title") or d.get("title") or f"第{d['episode_id']:02d}集"
            d["episode_title"] = str(title)
            dur = d.get("planned_duration_sec") or d.get("duration_seconds") or d.get("duration") or 120.0
            d["planned_duration_sec"] = float(dur)
            d["dramatic_arc_unit"] = str(d.get("dramatic_arc_unit") or f"单元 {(d['episode_id'] - 1) // 3 + 1}")
            d["core_dramatic_task"] = str(d.get("core_dramatic_task") or d.get("core_conflict_task") or "")
            
            # pickup
            pickup = d.get("previous_episode_0s_pickup") or d.get("previous_episode_physical_pickup") or d.get("incoming_physical_snapshot")
            if pickup:
                if isinstance(pickup, PreviousEpisodePickupModel):
                    d["previous_episode_0s_pickup"] = pickup
                elif isinstance(pickup, dict):
                    d["previous_episode_0s_pickup"] = PreviousEpisodePickupModel.model_validate(pickup)
            elif d["episode_id"] == 1:
                d["previous_episode_0s_pickup"] = None

            # screenplay_text
            text = d.get("screenplay_text") or d.get("body_markdown") or d.get("screenplay_content") or ""
            d["screenplay_text"] = str(text)

            # golden_cliffhanger_hook
            hook = d.get("golden_cliffhanger_hook") or {}
            if isinstance(hook, GoldenCliffhangerHookModel):
                d["golden_cliffhanger_hook"] = hook
            elif isinstance(hook, dict):
                d["golden_cliffhanger_hook"] = GoldenCliffhangerHookModel.model_validate(hook)
            else:
                d["golden_cliffhanger_hook"] = GoldenCliffhangerHookModel(physical_crisis_action=str(hook))

            # episode_end_physical_delta
            delta = d.get("episode_end_physical_delta") or d.get("outgoing_physical_snapshot") or {}
            if isinstance(delta, EpisodeEndPhysicalDeltaModel):
                d["episode_end_physical_delta"] = delta
            elif isinstance(delta, dict):
                d["episode_end_physical_delta"] = EpisodeEndPhysicalDeltaModel.model_validate(delta)
            else:
                d["episode_end_physical_delta"] = EpisodeEndPhysicalDeltaModel(character_pose=str(delta))

            # audit_report
            ar = d.get("audit_report") or {}
            if hasattr(ar, "model_dump"):
                ar = ar.model_dump()
            d["audit_report"] = ar if isinstance(ar, dict) else {}

            # 保留 legacy 别名
            d.setdefault("episode_num", d["episode_id"])
            d.setdefault("title", title)
            d.setdefault("body_markdown", text)
            d.setdefault("outgoing_physical_snapshot", d["episode_end_physical_delta"].model_dump() if hasattr(d["episode_end_physical_delta"], "model_dump") else d["episode_end_physical_delta"])
            return d
        return data

    @property
    def episode_num(self) -> int:
        return self.episode_id

    @property
    def title(self) -> str:
        return self.episode_title

    @property
    def body_markdown(self) -> str:
        return self.screenplay_text

    @property
    def outgoing_physical_snapshot(self) -> EpisodeEndPhysicalDeltaModel:
        return self.episode_end_physical_delta

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            if self.__pydantic_extra__ is None:
                self.__pydantic_extra__ = {}
            self.__pydantic_extra__[key] = value

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)

    def keys(self) -> list[str]:
        base_keys = list(self.model_fields.keys()) + ["episode_num", "title", "body_markdown", "outgoing_physical_snapshot"]
        if self.__pydantic_extra__:
            base_keys.extend(self.__pydantic_extra__.keys())
        return list(dict.fromkeys(base_keys))

    def items(self) -> list[tuple[str, Any]]:
        return [(k, self.get(k)) for k in self.keys()]

    def values(self) -> list[Any]:
        return [self.get(k) for k in self.keys()]

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["episode_num"] = self.episode_id
        d["title"] = self.episode_title
        d["body_markdown"] = self.screenplay_text
        d["outgoing_physical_snapshot"] = self.episode_end_physical_delta.model_dump()
        return d


class BiologicalPortraitDNADict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】微观生物肖像骨相 DNA 契约。"""
    face_shape: str
    skin_pores: str
    permanent_flaws_coordinates: str
    eyes_and_lips: str
    hair_texture: str


class LivedInCostumeSpecsDict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】真实生活质感服化道代码契约。"""
    outerwear_fabric_wear: str
    innerwear: str
    bottoms_and_shoes: str
    anchor_props: list[str]


class AcousticPersonaDict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】角色声学发音腔体人设契约。"""
    vocal_position: str
    vocal_flaws: str
    speed_and_intonation: str


class PsychologicalQuadrupleDict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】角色心理四元组契约。"""
    want: str
    need: str
    the_lie: str
    the_ghost: str


class CharacterProfileDict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】阶段 2 核心角色档案契约。"""
    character_id: str
    character_code: str
    name: str
    role_type: str
    gender: Literal["male", "female", "other", "unknown"] | str
    perceived_age: int
    description: str
    personality: str
    appearance: str
    visual_consistency_code: str
    psychology_4: dict[str, Any] | str
    acoustic_persona: dict[str, Any] | str
    voice_fingerprint: str
    carried_anchor_item: Any
    drama_engine: Any
    biological_dna: BiologicalPortraitDNADict
    lived_in_costume: LivedInCostumeSpecsDict


class CharacterRelationshipItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】阶段 2 角色动态关系矩阵字典契约。"""
    character_a_code: str
    character_b_code: str
    character_a_name: str
    character_b_name: str
    social_label: str
    tension_index: int
    drama_function: str
    shared_history_props: Any
    information_gap: Any
    knows_truth_initially: bool
    current_belief: str
    reveal_condition: str
    can_defect: bool
    defect_condition: str
    swing_point: Any
    raw: Any


class DualTrackRelationshipItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】阶段 2 利益与情感双轨关系矩阵项。"""
    character_a: str
    character_b: str
    surface_relation: str
    emotional_bond: str
    fatal_interest_conflict: str
    shared_history_props: list[str]


class EmotionalArcTrajectoryDict(TypedDict, total=False):
    """【规则编号: RULE-VI-02】阶段 2 动态四阶段情感弧轨迹。"""
    stage_a_guarded: str
    stage_b_fracture: str
    stage_c_abyss: str
    stage_d_catharsis: str


class EnvironmentItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-03】阶段 3 空间场景三层做旧契约。"""
    env_id: str
    level: Literal["primary_tier1", "transitional_tier2"]
    three_layer_aging: dict[str, str]
    costume_resonance_check: bool


class PropItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-03】阶段 3 核心物证与阻力拟音契约。"""
    prop_id: str
    level: Literal["hero_tier1", "anchor_tier2", "atmospheric_tier3"]
    appearance_and_wear: str
    symbolic_meaning: str
    haptic_friction_foley: str


class EpisodeOutlineItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-04】阶段 4 双螺旋分集任务卡契约。"""
    episode_id: int
    episode_title: str
    killer_title: str
    dramatic_arc_unit: str
    core_conflict_task: str
    core_dramatic_task: str
    ab_storylines: dict[str, str]
    dual_helix_task: dict[str, Any]
    hook_3s: str
    three_second_hook: str
    micro_twist_45s: str
    micro_turning_point_45s: str
    cliffhanger_end: str
    killer_cliffhanger_115s: str
    cliffhanger: str
    subtext_matrix: dict[str, Any]
    relational_shift_point: str
    lie_erosion_metric: str


class AudioMotifItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-04】阶段 4 音乐主题动机母库项。"""
    motif_id: str
    leitmotif_id: str
    name: str
    instrumentation: str
    tempo_bpm: str
    musical_key: str
    dramatic_function: str


class AudioBibleDict(TypedDict, total=False):
    """【规则编号: RULE-VI-04】阶段 4 音乐动机母库 (04_audio_bible.json)。"""
    leitmotifs: list[AudioMotifItemDict]
    leitmotif_registry: list[AudioMotifItemDict]
    foley_rules: dict[str, str]


class ReusedAssetItem(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 已核准复用资产项。"""
    asset_id: str
    type: str
    usage_in_current_ep: str
    status: Literal["APPROVED"]


class NewlyGeneratedAssetItem(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 新生成增量资产项。"""
    asset_id: str
    asset_category: str
    script_inference_trigger: str
    generation_method: Literal["text_to_image", "image_to_image_outpainting", "image_to_image_pose", "inpainting_local_edit", "relighting"]
    input_source_image: str | None
    identity_reference: str | None
    denoising_strength: float | None
    aspect_ratio: str
    image_prompt: str
    status: Literal["APPROVED"]


class MasterVoiceCardItem(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 角色母音频卡片项。"""
    character_id: str
    master_voice_id: str
    script_monologue_source: str
    master_tts_prompt: str
    voice_file_path: str


class EpisodeResourceManifestDict(TypedDict, total=False):
    """【规则编号: RULE-VI-06】阶段 6 单集视听资源引单字典。"""
    characters: dict[str, list[dict[str, Any]]]
    environments: dict[str, list[dict[str, Any]]]
    props: dict[str, list[dict[str, Any]]]
    audio: dict[str, Any]


class FirstLastFrameConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 模式 A 首尾帧 Prompt 配置。"""
    first_frame_asset_ref: str
    first_frame_asset_id: str
    first_frame_prompt: str
    last_frame_asset_ref: str
    last_frame_asset_id: str
    last_frame_prompt: str
    video_motion_prompt: str


class MediaImageItem(TypedDict, total=False):
    """【规则编号: RULE-VI-07】模式 B 多模态图片编号素材项。"""
    symbol: str  # 图1, 图2...
    asset_id: str
    role: str


class MediaAudioItem(TypedDict, total=False):
    """【规则编号: RULE-VI-07】模式 B 多模态音频编号素材项。"""
    symbol: str  # 音频1, 音频2...
    voice_id: str
    role: str


class MediaManifestDict(TypedDict, total=False):
    """【规则编号: RULE-VI-07】模式 B 先排后编多模态映射表。"""
    images: list[MediaImageItem]
    audios: list[MediaAudioItem]


class MultiImageReferenceConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 模式 B 多图参考配置。"""
    media_manifest: MediaManifestDict
    reference_assets: list[str]
    reference_asset_ids: list[str]
    video_prompt: str
    target_engine: str
    audit: Literal["PASS_9"] | str


class ModeBManifestCheckDict(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 模式 B 多图参考集末 9 项自审清单。"""
    episode_num: int
    total_mode_b_shots: int
    max_images_under_limit: bool
    scene_unique_and_first: bool
    character_numbered_from_two: bool
    audio_independent_order: bool
    spatial_constraint_front: bool
    temporal_order_forward: bool
    target_engine_compliant: bool
    no_forbidden_prompt_words: bool
    all_pass_9_signed: bool
    verdict: Literal["PASS", "FAIL"] | str
    issues: list[str]


class ShotAudioConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】单镜全息声音配置。"""
    voice_type: str | None
    speech_inpoint_sec: float | None
    is_dialogue_complete_in_shot: bool
    contextual_tts_prompt: str | None


class LipSyncDynamicsConfig(TypedDict, total=False):
    """【规则编号: RULE-VI-07】离线口型动力学静默元数据。"""
    jaw_open_scale: float | None


class StoryboardShotDict(TypedDict, total=False):
    """【规则编号: RULE-VI-07】阶段 7 单镜头工业执行表单项字典 (sb_XX.json)。"""
    shot_id: int
    duration_sec: float  # 严格整秒 (2.0, 3.0, 4.0, 5.0, 6.0, 7.0)
    timecode: str  # HH:MM:SS,mmm --> HH:MM:SS,mmm
    rationale: str
    generation_mode: Literal["first_last_frame", "multi_image_reference"]
    selection_rationale: str
    target_engine: Literal["wan3.0", "seedance2.5", "minimax_h3"] | str
    first_last_frame_config: FirstLastFrameConfig | None
    multi_image_config: MultiImageReferenceConfig | None
    audio: ShotAudioConfig
    lipsync_dynamics: LipSyncDynamicsConfig | None


class MasteringScheduleItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-08】阶段 8 精准分贝避让调度表单项。"""
    time_start_sec: float
    time_end_sec: float
    timecode_range: str
    target_bgm_volume_db: float  # -12.0, -20.0, -999.0
    speech_ducking_active: bool
    event_description: str


class EpisodeAudioSpecDict(TypedDict, total=False):
    """【规则编号: RULE-VI-08】阶段 8 结构化音频工程规范字典 (ep_XX_audio_spec.json)。"""
    audio_specs: dict[str, str]
    acoustic_traceability: dict[str, str]
    bgm_generation: dict[str, Any]
    mastering_schedule: list[MasteringScheduleItemDict]
    nle_mixing_guidelines: dict[str, Any]


# =========================================================================
# 【公共硬性约束 3】LangGraph 核心全局状态 TypedDict 契约定义
# =========================================================================

class IndustrialDramaState(TypedDict, total=False):
    """【规则编号: RULE-VI-01 ~ RULE-VI-08】两程九阶全息闭环全局状态 TypedDict 契约 (LangGraph State)。
    
    严格对齐公共硬性约束：
    1. 大模型严禁参与任何业务分支判断，路由逻辑抽离至独立路由函数；
    2. State 统一使用 TypedDict 契约规范，节点统一入参 state，返回增量字典；
    3. 容器型字段使用 Annotated[dict, operator.ior] 实现分集增量自动合并；
    4. 分支全部穷举，兜底指向 error_terminal_node。
    """
    drama_id: int
    journey: Literal["journey_1_literary", "journey_2_visual", "completed"]
    current_stage: int
    
    # 阶段 1: 01_bible.json 基本盘与双轨禁令
    user_idea: str
    slug: str
    selected_title: str
    candidate_titles: dict[str, Any]
    aspect_ratio: str
    target_duration_sec: float
    duration_sec_per_ep: int
    target_episodes: int
    genre: str
    visual_style: str
    target_video_engine: Literal["wan3.0", "seedance2.5", "minimax_h3"] | str
    forbidden_cliches_10: list[str]
    forbidden_cheap_tropes_3: list[str]
    negative_rules: dict[str, Any]
    logline: str
    core_irony: str
    grand_payoff: str
    
    # 语义化工作记忆便签 (第一程文学工程单阶提取)
    ideation_working_memory: str
    character_working_memory: str
    world_building_working_memory: str
    season_outline_working_memory: str
    
    # 阶段 2: 02_characters.json 角色引擎
    characters_engine: dict[str, Any]
    dual_track_relationships: list[dict[str, Any]]
    emotional_arc_trajectories: list[dict[str, Any]]
    
    # 阶段 3: 03_environments_props.json 空间做旧与物证拟音
    environments_and_props: dict[str, Any]
    
    # 阶段 4: 04_outline.json & 04_audio_bible.json 双螺旋任务卡与音乐母库
    audio_bible: dict[str, Any]
    season_outlines: Annotated[dict[int, Any], operator.ior]
    mini_arc_units: list[dict[str, Any]]
    
    # 阶段 5: episodes_screenplay/ep_XX.json 全季文学剧本波次与时空总线
    current_mini_arc_index: int
    total_episodes: int
    completed_screenplays: Annotated[dict[int, Any], operator.ior]
    inter_episode_physical_snapshot: dict[str, Any] | None
    inter_episode_physical_continuity: dict[str, Any] | None
    literary_journey_locked: bool
    
    # 第二程真理源总库与单集循环 (Stage 6~8)
    current_visual_episode: int
    visual_audio_assets_registry: Annotated[dict[str, Any], operator.ior]
    episode_resource_manifests: Annotated[dict[int, Any], operator.ior]
    episode_storyboards: Annotated[dict[int, Any], operator.ior]
    episode_srt_exports: Annotated[dict[int, Any], operator.ior]
    episode_audio_masterings: Annotated[dict[int, Any], operator.ior]
    episode_mode_b_manifest_checks: Annotated[dict[int, Any], operator.ior]
    
    # 红蓝对抗哨卡质检报告与自愈防死循环重试计数器
    latest_audit: dict[str, Any]
    stage_retry_counts: Annotated[dict[str, int], operator.ior]
    error_message: str | None


# 兼容性别名
DramaScriptState = LeanDramaScriptState
