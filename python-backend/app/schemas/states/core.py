# -*- coding: utf-8 -*-
"""核心文学状态契约（企划、世界观、人物画像与大纲）。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.core")


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
    benchmark_asset_key: str = Field(default="", description="全剧唯一0号人脸基因源基准资产Key (如 CHAR_LUCHEN_T1_BASE_PORTRAIT)")
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


DramaScriptState = LeanDramaScriptState


__all__ = [
    "ProjectProfile",
    "HighConcept",
    "WorldviewProfile",
    "GrowthChainItem",
    "BiologicalPortraitDNA",
    "LivedInCostumeSpecs",
    "PsychologicalQuadruple",
    "VoiceBehavioralFingerprint",
    "CarriedAnchorItem",
    "DualTrackRelationshipItem",
    "CharacterRelationshipItem",
    "EmotionalArcTrajectory",
    "CharacterProfile",
    "ClueItem",
    "ContinuityMemo",
    "EpisodeOutlineItem",
    "SingleSceneCheck",
    "ASTBlockItem",
    "AudioVisualBeat",
    "ScriptAST",
    "EpisodeScript",
    "QAReport",
    "merge_worker_results",
    "LeanDramaScriptState",
    "CandidateTitleMatrix",
    "DoubleTrackProhibitions",
    "DramaScriptState",
]
