"""剧本创作与改编规范 Schema (ScriptSpec & NovelAdaptationSpec)。

定义“AI 原创剧本”与“长篇小说转剧本”两类入口的结构化输入契约，
包含商业爆点、冲突密度、付费卡点、删改策略等关键维度。
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class PaywallStrategy(BaseModel):
    """短剧商业付费卡点规划策略。"""
    enabled: bool = Field(default=True, description="是否启用付费卡点规划")
    first_paywall_episode: int = Field(default=10, description="首个付费爆发/卡点集数（通常第 8-12 集）")
    paywall_interval: int = Field(default=5, description="后续付费卡点间隔集数")
    hook_intensity: Literal["high", "extreme"] = Field(default="extreme", description="卡点悬念强度")
    notes: str = Field(default="", description="付费点剧情特殊要求或策略备注")


class ScriptSpec(BaseModel):
    """AI 原创短剧创作需求规范。"""
    title_hint: str = Field(default="", description="剧本建议标题或暂定名")
    genre: str = Field(default="都市爽剧", description="短剧题材（如：战神归来、真假千金、穿越逆袭、虐恋情深、玄幻修真）")
    target_audience: str = Field(default="下沉市场主流受众/年轻网文读者", description="目标受众群体画像")
    distribution_platform: str = Field(default="抖音/快手/微信小程序短剧", description="主要发行与投放平台")
    target_episodes: int = Field(default=80, ge=1, le=200, description="规划总集数（通常 60~100 集）")
    episode_duration_seconds: int = Field(default=90, ge=30, le=300, description="单集期望时长（秒，通常 60-120 秒）")
    core_theme: str = Field(default="", description="核心母题与主线梗概（如：隐形首富隐姓埋名入赘三年遭羞辱后强势反击）")
    main_conflict: str = Field(default="", description="核心矛盾冲突与反派对抗主线")
    golden_hook_requirement: str = Field(default="前 3 秒出奇观/巨大冲突，前 3 集完成背景与第一个高潮打脸", description="黄金开头与快节奏抓人要求")
    taboos_and_limits: list[str] = Field(default_factory=list, description="创作禁忌项（如：禁止血腥违规、违背公序良俗等）")
    visual_style_reference: str = Field(default="写实短剧电影级质感，光影明暗对比强烈", description="视觉美术与画面调性参考")
    pace_rhythm: Literal["ultra_fast", "fast", "standard"] = Field(default="ultra_fast", description="剧情节奏（快节奏/超快节奏）")
    paywall_strategy: PaywallStrategy = Field(default_factory=PaywallStrategy, description="商业付费卡点与悬念规划")
    custom_requirements: dict[str, Any] = Field(default_factory=dict, description="额外自定义参数与指令")


class AdaptationRule(BaseModel):
    """小说改编策略项（保留/删减/合并）。"""
    action: Literal["keep", "remove", "merge", "modify", "amplify"] = Field(
        ..., description="改编动作：keep(保留主线), remove(删减旁支), merge(合并角色/场景), modify(微调时序), amplify(强化冲突与爽点)"
    )
    target: str = Field(..., description="目标情节/人物/线索名称")
    reason: str = Field(default="", description="改编原因及对节奏的影响说明")


class NovelChunk(BaseModel):
    """基于 LlamaIndex 语义断句与自适应滑动窗口切片块 (Novel Semantic Chunk)。"""
    chunk_index: int = Field(..., description="切片全局或章节内序号")
    chapter_index: int = Field(default=1, description="归属章节序号")
    chapter_title: str = Field(default="", description="归属章节标题")
    text: str = Field(..., description="切片正文内容")
    summary: str = Field(default="", description="切片语义摘要")
    char_count: int = Field(default=0, description="字符数")
    overlap_prefix: str = Field(default="", description="前向重叠文本片段（滑动窗口保持剧情连续）")
    overlap_suffix: str = Field(default="", description="后向重叠文本片段")
    is_key_plot: bool = Field(default=False, description="是否为关键高潮/名场面切片")
    dramatic_elements: list[str] = Field(default_factory=list, description="戏剧冲突与转折点")
    key_characters: list[str] = Field(default_factory=list, description="切片内出场人物")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外切片元数据")


class NovelSplitOptions(BaseModel):
    """小说切片配置与滑动窗口选项。"""
    chunk_size: int = Field(default=512, ge=64, le=4096, description="切片目标大小（字符数）")
    chunk_overlap: int = Field(default=64, ge=0, le=512, description="自适应滑动窗口重叠大小（字符数）")
    use_semantic_split: bool = Field(default=True, description="是否启用基于语义断句的切片算法")
    max_chapters: int = Field(default=20, ge=1, le=200, description="最多解析章节数")
    ai_summarize: bool = Field(default=False, description="是否调用 AI 进行剧本草稿改写")
    save_to_memory: bool = Field(default=True, description="是否自动写入长期记忆库 (memory_items)")


class NovelChapterSlice(BaseModel):
    """小说章节切片信息。"""
    chapter_index: int = Field(..., description="章节序号")
    chapter_title: str = Field(default="", description="章节标题")
    original_text: str = Field(default="", description="原文内容")
    summary: str = Field(default="", description="核心情节摘要")
    key_characters: list[str] = Field(default_factory=list, description="出场主要人物")
    dramatic_elements: list[str] = Field(default_factory=list, description="包含的戏剧冲突与转折点")
    is_key_plot: bool = Field(default=False, description="是否为必须保留的关键高潮/名场面章节")
    chunks: list[NovelChunk] = Field(default_factory=list, description="章节内自适应滑动窗口语义切片列表")


class NovelAdaptationSpec(BaseModel):
    """长篇小说改编短剧需求规范。"""
    novel_title: str = Field(..., description="原著小说名称")
    original_author: str = Field(default="", description="原著作者")
    source_summary: str = Field(default="", description="原著世界观与核心故事主线总结")
    target_episodes: int = Field(default=80, ge=1, le=200, description="改编后目标短剧集数")
    episode_duration_seconds: int = Field(default=90, description="单集目标时长（秒）")
    adaptation_style: Literal["faithful", "condensed", "reimagined"] = Field(
        default="condensed", description="改编偏好：faithful(原汁原味还原), condensed(精简提炼快节奏), reimagined(保留核心设定做短剧化重构)"
    )
    core_character_mapping: dict[str, str] = Field(default_factory=dict, description="核心人物关系与身份提炼")
    key_plot_anchors: list[str] = Field(default_factory=list, description="必须保留的原著名场面与核心主线锚点")
    adaptation_rules: list[AdaptationRule] = Field(default_factory=list, description="详细的情节删改与合并策略清单")
    chapter_slices: list[NovelChapterSlice] = Field(default_factory=list, description="章节切片摘要与分析缓存")
    paywall_strategy: PaywallStrategy = Field(default_factory=PaywallStrategy, description="付费卡点与集数划分策略")
    custom_notes: str = Field(default="", description="改编补充说明与要求")
