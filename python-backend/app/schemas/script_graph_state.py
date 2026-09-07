"""LangGraph 短剧工业化创作状态数据契约 (Drama Script State Schema)。

基于《短剧剧本·全流程工业化创作提示词（升级增强版）》工业化标准设计，
支撑多智能体状态机流转、连续性追踪、五阶质检与 Human-in-the-Loop 中断恢复。
"""
from __future__ import annotations

from typing import Any, Literal, Annotated
from pydantic import BaseModel, Field


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
    era_and_location: str = Field(default="", description="时代背景与地域环境")
    core_main_scenes: list[str] = Field(default_factory=list, description="3-5 个核心主场景（严控拍摄成本）")
    social_structure: str = Field(default="", description="社会结构、阶层关系与对立势力")
    core_rules_and_taboos: list[str] = Field(default_factory=list, description="世界核心规则、人情逻辑、行业禁忌")
    rule_violation_cost: str = Field(default="", description="违反规则会付出的现实代价")


class GrowthChainItem(BaseModel):
    """主角错误认知成长链节点。"""
    stage_name: str = Field(default="", description="阶段名称")
    belief: str = Field(default="", description="认知信念状态")
    trigger_event: str = Field(default="", description="关键冲击事件")
    choice_made: str = Field(default="", description="做出的抉择与代价")


class CharacterProfile(BaseModel):
    """阶段二：标准化人物档案。"""
    name: str = Field(..., description="人物姓名")
    role_type: Literal["protagonist", "supporter", "antagonist"] = Field(..., description="角色定位")
    identity_and_mask: str = Field(default="", description="表面身份与隐藏马甲")
    visual_anchor: str = Field(default="", description="外貌记忆点与视觉特征")
    surface_desire: str = Field(default="", description="表层目标/核心欲望")
    deep_need: str = Field(default="", description="深层执念/内在需求")
    flaw: str = Field(default="", description="致命缺陷与性格盲点")
    secret: str = Field(default="", description="隐藏秘密与过往创伤")
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


# 兼容性别名
DramaScriptState = LeanDramaScriptState
