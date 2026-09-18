"""LangGraph 短剧工业化创作状态数据契约 (Drama Script State Schema)。

基于《短剧剧本·全流程工业化创作提示词（升级增强版）》工业化标准设计，
支撑多智能体状态机流转、连续性追踪、五阶质检与 Human-in-the-Loop 中断恢复。
"""
from __future__ import annotations

import operator
from typing import Any, Literal, Annotated, TypedDict
from pydantic import BaseModel, Field, ConfigDict


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
    """阶段二：标准化全息人物档案（对齐 SKILL.md 工业全息规范）。"""
    model_config = ConfigDict(extra="allow")
    name: str = Field(..., description="人物姓名")
    role_type: Literal["protagonist", "supporter", "antagonist"] = Field(..., description="角色定位")
    identity_and_mask: str = Field(default="", description="表面身份与隐藏马甲")
    visual_anchor: str = Field(default="", description="外貌记忆点与视觉特征")
    surface_desire: str = Field(default="", description="表层目标/核心欲望")
    deep_need: str = Field(default="", description="深层执念/内在需求")
    flaw: str = Field(default="", description="致命缺陷与性格盲点")
    secret: str = Field(default="", description="隐藏秘密与过往创伤")
    
    # 工业全息增强字段 (SKILL.md)
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
    voice_fingerprint: VoiceBehavioralFingerprint | None = Field(
        default=None,
        description="语言与行为指纹（口头禅/防御语/禁词/应激动作）"
    )
    carried_anchor_item: CarriedAnchorItem | None = Field(
        default=None,
        description="随身旧物/物理锚定物（磨损细节与情感象征）"
    )
    emotional_arc: EmotionalArcTrajectory | None = Field(
        default=None,
        description="四阶段全季情感流转弧"
    )
    
    # 兼容历史字段
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


class ScriptAST(BaseModel):
    """单集剧本 AST 结构树。"""
    episode_num: int = Field(..., description="对应集数")
    blocks: list[ASTBlockItem] = Field(default_factory=list, description="4 个标准结构分块列表")
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
    name: str = Field(..., description="主题动机名称（如：悬疑压迫与阶层窒息）")
    instrumentation: str = Field(default="", description="核心配器说明")
    tempo_bpm: str = Field(default="86", description="速度区间与节拍")
    musical_key: str = Field(default="D minor", description="调性")
    dramatic_function: str = Field(default="", description="戏剧功能定位与触发场景")


class AudioBible(BaseModel):
    """阶段 4 长期资产：全剧音乐动机母库 (04_audio_bible.json)。"""
    leitmotifs: list[AudioMotifItem] = Field(default_factory=list, description="全剧 3 个贯穿始终的具象音乐主题动机")
    foley_rules: dict[str, str] = Field(
        default_factory=lambda: {"boost": "+2.0dB ~ +3.0dB", "clarity": "-23 LUFS"},
        description="拟音放大与混音规范"
    )


class EpisodeResourceManifest(BaseModel):
    """阶段 6 产出：本集视听资源引单 (Episode Resource Manifest)。"""
    model_config = ConfigDict(extra="allow")
    characters_tier_1: list[dict[str, Any]] = Field(default_factory=list, description="一级身份基础资产")
    characters_tier_2: list[dict[str, Any]] = Field(default_factory=list, description="二级叙事表现资产（角度/剧本情绪/服装状态）")
    characters_tier_3: list[dict[str, Any]] = Field(default_factory=list, description="三级镜头专项资产（生理微距/手部特写）")
    environments_primary: list[dict[str, Any]] = Field(default_factory=list, description="一级核心主场景（>=3场戏）")
    environments_transitional: list[dict[str, Any]] = Field(default_factory=list, description="二级过渡次场景（1-2镜）")
    props_narrative: list[dict[str, Any]] = Field(default_factory=list, description="一级核心叙事物证（支持静态/破坏形态双图）")
    props_anchors: list[dict[str, Any]] = Field(default_factory=list, description="二级角色锚定道具（并入角色 HAND_MACRO）")
    props_ambient: list[dict[str, Any]] = Field(default_factory=list, description="三级环境气氛杂物（零独立生图，纯提示词驱动）")
    audio_tts: list[dict[str, Any]] = Field(default_factory=list, description="TTS 声音资源引单")

    approved_character_ids: list[str | int] = Field(default_factory=list, description="已核准复用的角色ID列表")
    approved_scene_ids: list[str | int] = Field(default_factory=list, description="已核准复用的场景ID列表")
    approved_prop_ids: list[str | int] = Field(default_factory=list, description="已核准复用的道具ID列表")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "EpisodeResourceManifest":
        if isinstance(obj, dict):
            # 兼容 flat 结构输入
            if "characters" in obj and not obj.get("characters_tier_1"):
                obj["characters_tier_1"] = obj["characters"]
            if "environments" in obj and not obj.get("environments_primary"):
                obj["environments_primary"] = obj["environments"]
            if "props" in obj and not obj.get("props_narrative"):
                obj["props_narrative"] = obj["props"]
        return super().model_validate(obj, *args, **kwargs)

    @property
    def characters(self) -> list[dict[str, Any]]:
        return self.characters_tier_1 + self.characters_tier_2 + self.characters_tier_3

    @property
    def environments(self) -> list[dict[str, Any]]:
        return self.environments_primary + self.environments_transitional

    @property
    def props(self) -> list[dict[str, Any]]:
        return self.props_narrative + self.props_anchors + self.props_ambient

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


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
    duration_sec: float = Field(default=3.0, description="单镜时长（2.5 - 4.5秒）")
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
    foley_cue: str = Field(default="", description="拟音/物理音效指令")
    selection_rationale: str = Field(default="", description="选型依据决策解释")
    first_last_config: dict[str, Any] | None = Field(default=None, description="首尾帧配置（向下兼容）")
    multi_image_config: dict[str, Any] | None = Field(default=None, description="多图参考配置（向下兼容）")
    audio: dict[str, Any] = Field(default_factory=dict, description="全息声学提示词（对白/旁白/拟音Foley）")
    lipsync_dynamics: LipsyncDynamics | dict[str, Any] | None = Field(default=None, description="口型动力学（下颌开度jaw_open_scale/嘴角张力/头部微动）")

    target_engine: str | None = Field(default="wan3.0", description="目标生成模型 (wan3.0/seedance2.5/minimax_h3)")
    rationale: str = Field(default="", description="算子1+2景别与时长累加推导依据")
    first_last_frame_config: dict[str, Any] | None = Field(default=None, description="首尾帧Prompt配置")
    speech_inpoint_sec: float | None = Field(default=None, description="台词入点时间码偏移秒数")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "StoryboardShot":
        if isinstance(obj, dict) and "lipsync_dynamics" in obj and isinstance(obj["lipsync_dynamics"], dict):
            dyn = dict(obj["lipsync_dynamics"])
            if "jaw_open" in dyn and "jaw_open_scale" not in dyn:
                dyn["jaw_open_scale"] = dyn["jaw_open"]
            obj["lipsync_dynamics"] = LipsyncDynamics.model_validate(dyn)
        if isinstance(obj, dict):
            if "first_last_config" in obj and "first_last_frame_config" not in obj:
                obj["first_last_frame_config"] = obj["first_last_config"]
            elif "first_last_frame_config" in obj and "first_last_config" not in obj:
                obj["first_last_config"] = obj["first_last_frame_config"]
        return super().model_validate(obj, *args, **kwargs)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class IndustrialDramaMasterState(BaseModel):
    """两程九阶全息闭环全局状态模型 (Industrial Master State)。"""
    drama_id: int = Field(default=0, description="短剧项目 ID")
    journey: Literal["journey_1_literary", "journey_2_visual", "completed"] = Field(
        default="journey_1_literary",
        description="当前工业程：第一程文学故事工程 / 第二程视听与分镜工程"
    )
    current_stage: int = Field(default=1, description="当前阶段编号 (1 ~ 8)")
    
    # 阶段 1
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
    
    # 阶段 2 人设 (微观生物肖像骨相DNA、生活质感服化道代码、心理四元组、语言行为指纹、双轨关系网、四阶段情感流转)
    characters_engine: dict[str, Any] = Field(default_factory=dict)
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
    
    # 阶段 4 大纲与音乐主题动机
    audio_bible: AudioBible = Field(default_factory=AudioBible)
    season_outlines: dict[int, dict[str, Any]] = Field(default_factory=dict)
    
    # 阶段 5 全季文学剧本波次与集数管理
    current_mini_arc_index: int = Field(default=1, description="当前戏剧波次（3-4集一组）")
    total_episodes: int = Field(default=12, description="全季总集数")
    completed_screenplays: dict[int, dict[str, Any]] = Field(default_factory=dict, description="定稿文学剧本 ep_XX.json 字典")
    inter_episode_physical_snapshot: dict[str, Any] | None = Field(default=None, description="集间0秒物理咬合快照")
    literary_journey_locked: bool = Field(default=False, description="第一程全季文学定稿总锁")
    
    # 第二程真理源总库与单集循环
    current_visual_episode: int = Field(default=1, description="当前正在执行视听工程的集数 (1..NN)")
    visual_audio_assets_registry: dict[str, Any] = Field(default_factory=dict, description="05_visual_audio_assets.json 真理源总库")
    episode_resource_manifests: dict[int, EpisodeResourceManifest] = Field(default_factory=dict)
    episode_storyboards: dict[int, list[StoryboardShot]] = Field(default_factory=dict)
    episode_srt_exports: dict[int, str] = Field(default_factory=dict)
    episode_audio_masterings: dict[int, dict[str, Any]] = Field(default_factory=dict)
    
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

    @property
    def storyboard_executions(self) -> dict[int, list[StoryboardShot]]:
        return self.episode_storyboards

    @storyboard_executions.setter
    def storyboard_executions(self, val: dict[int, list[StoryboardShot]]) -> None:
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
    def audio_mastering_plans(self) -> dict[int, dict[str, Any]]:
        return self.episode_audio_masterings

    @audio_mastering_plans.setter
    def audio_mastering_plans(self, val: dict[int, dict[str, Any]]) -> None:
        self.episode_audio_masterings = val

    def get(self, key: str, default: Any = None) -> Any:
        """支持字典式安全访问，确保向后兼容与平滑过渡。"""
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        """将 Pydantic 状态完整序列化为字典。"""
        return self.model_dump()

    def to_state_dict(self) -> IndustrialDramaState:
        """转换为标准 LangGraph IndustrialDramaState TypedDict 字典。"""
        return self.model_dump()


# =========================================================================
# 【规则编号: RULE-VI-01 ~ RULE-VI-08】标准 TypedDict 数据契约体系
# =========================================================================

class PreviousEpisodePickup(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】0 秒接棒物理快照字典 (第 2 集及之后强制包含)。"""
    inherited_from_episode: int
    pickup_state_description: str


class GoldenCliffhangerHook(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】结尾黄金悬念钩子三位一体字典。"""
    physical_crisis_action: str
    cliffhanger_dialogue: str
    acoustic_drop_cue: str


class EpisodeEndPhysicalDelta(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】集尾物理状态快照字典 (封存最后一秒真实物理残局)。"""
    timeline_progress: str
    character_pose: str
    held_props_and_injuries: str
    environment_and_weather: str


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
    name: str
    gender: Literal["male", "female"]
    perceived_age: int
    biological_dna: BiologicalPortraitDNADict
    lived_in_costume: LivedInCostumeSpecsDict
    acoustic_persona: AcousticPersonaDict
    psychology_4: PsychologicalQuadrupleDict


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
    dramatic_arc_unit: str
    core_conflict_task: str
    ab_storylines: dict[str, str]
    micro_twist_45s: str
    cliffhanger_end: str


class AudioMotifItemDict(TypedDict, total=False):
    """【规则编号: RULE-VI-04】阶段 4 音乐主题动机母库项。"""
    motif_id: str
    name: str
    instrumentation: str
    tempo_bpm: str
    musical_key: str
    dramatic_function: str


class AudioBibleDict(TypedDict, total=False):
    """【规则编号: RULE-VI-04】阶段 4 音乐动机母库 (04_audio_bible.json)。"""
    leitmotifs: list[AudioMotifItemDict]
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
    first_frame_prompt: str
    last_frame_asset_ref: str
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
    video_prompt: str
    audit: Literal["PASS_9"]


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
    
    # 短期记忆便签 (即用即覆)
    short_memory_a: str
    short_memory_b: str
    short_memory_c: str
    short_memory_d: str
    
    # 阶段 2: 02_characters.json 角色引擎
    characters_engine: dict[str, Any]
    dual_track_relationships: list[dict[str, Any]]
    emotional_arc_trajectories: list[dict[str, Any]]
    
    # 阶段 3: 03_environments_props.json 空间做旧与物证拟音
    environments_and_props: dict[str, Any]
    
    # 阶段 4: 04_outline.json & 04_audio_bible.json 双螺旋任务卡与音乐母库
    audio_bible: dict[str, Any]
    season_outlines: Annotated[dict[int, Any], operator.ior]
    
    # 阶段 5: episodes_screenplay/ep_XX.json 全季文学剧本波次与时空总线
    current_mini_arc_index: int
    total_episodes: int
    completed_screenplays: Annotated[dict[int, Any], operator.ior]
    inter_episode_physical_snapshot: dict[str, Any] | None
    literary_journey_locked: bool
    
    # 第二程真理源总库与单集循环 (Stage 6~8)
    current_visual_episode: int
    visual_audio_assets_registry: Annotated[dict[str, Any], operator.ior]
    episode_resource_manifests: Annotated[dict[int, Any], operator.ior]
    episode_storyboards: Annotated[dict[int, Any], operator.ior]
    episode_srt_exports: Annotated[dict[int, Any], operator.ior]
    episode_audio_masterings: Annotated[dict[int, Any], operator.ior]
    
    # 红蓝对抗哨卡质检报告与自愈防死循环重试计数器
    latest_audit: dict[str, Any]
    stage_retry_counts: Annotated[dict[str, int], operator.ior]
    error_message: str | None


# 兼容性别名
DramaScriptState = LeanDramaScriptState
