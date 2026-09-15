"""LangGraph 短剧工业化创作状态数据契约 (Drama Script State Schema)。

基于《短剧剧本·全流程工业化创作提示词（升级增强版）》工业化标准设计，
支撑多智能体状态机流转、连续性追踪、五阶质检与 Human-in-the-Loop 中断恢复。
"""
from __future__ import annotations

from typing import Any, Literal, Annotated
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


class StoryboardShot(BaseModel):
    """阶段 7：单镜头工业执行表单项契约。"""
    model_config = ConfigDict(extra="allow")
    shot_id: int = Field(..., description="镜号")
    timecode: str = Field(default="00:00:00,000 --> 00:00:02,500", description="时间码（如：00:00:00,000 --> 00:00:02,500）")
    duration_sec: float = Field(..., description="单镜时长（2.5 - 4.5秒）")
    framing: str = Field(default="MCU 中近景", description="景别")
    camera_motion: str = Field(default="Static", description="运镜方式")
    generation_mode: Literal["first_last_frame", "multi_image_reference", "multi_image_ref"] = Field(
        ...,
        description="生成模式二选一：first_last_frame(首尾帧模式，专治物理形变/位移) / multi_image_reference(多图参考模式，专治对白神态)"
    )
    selection_rationale: str = Field(default="", description="选型依据决策解释")
    first_last_config: dict[str, Any] | None = Field(default=None, description="模式A首尾帧提示词与运动指令")
    multi_image_config: dict[str, Any] | None = Field(default=None, description="模式B多图参考资产ID列表与生视频提示词")
    audio: dict[str, Any] = Field(default_factory=dict, description="全息声学提示词（对白/旁白/拟音Foley）")
    lipsync_dynamics: LipsyncDynamics | dict[str, Any] | None = Field(default=None, description="口型动力学（下颌开度jaw_open_scale/嘴角张力/头部微动）")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "StoryboardShot":
        if isinstance(obj, dict) and "lipsync_dynamics" in obj and isinstance(obj["lipsync_dynamics"], dict):
            dyn = dict(obj["lipsync_dynamics"])
            if "jaw_open" in dyn and "jaw_open_scale" not in dyn:
                dyn["jaw_open_scale"] = dyn["jaw_open"]
            obj["lipsync_dynamics"] = LipsyncDynamics.model_validate(dyn)
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
    visual_style: str = Field(default="真人电影/超写实", description="项目风格")
    negative_rules: DoubleTrackProhibitions = Field(default_factory=DoubleTrackProhibitions)
    logline: str = Field(default="", description="工业级 Logline")
    dramatic_irony: str = Field(default="", description="核心讽刺")
    grand_payoff: str = Field(default="", description="终局核爆点")
    
    # 短期记忆便签 A/B/C/D
    short_memory_a: str = Field(default="", description="短期记忆 A：人设禁令子集 + 核心讽刺")
    short_memory_b: str = Field(default="", description="短期记忆 B：角色活动轨迹与随身旧物")
    short_memory_c: str = Field(default="", description="短期记忆 C：大纲冲突要素包")
    short_memory_d: str = Field(default="", description="短期记忆 D：全季分集剧作路线图")
    
    # 阶段 2 人设 (心理四元组、语言指纹、随身锚定物)
    characters_engine: dict[str, Any] = Field(default_factory=dict)
    
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


# 兼容性别名
DramaScriptState = LeanDramaScriptState
