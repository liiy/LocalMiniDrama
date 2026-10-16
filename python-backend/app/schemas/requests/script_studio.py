"""剧本工作室 (Script Studio) 请求与响应数据传输模型 (DTO / Schema)。

职责：
- 封装阶段 1 至阶段 5 以及两程九阶全生命周期的 API 入参校验与解析。
- 集中维护流转模式枚举、人工审核策略枚举与导出格式枚举。
- 与具体 FastAPI 路由逻辑解耦，统一继承 BaseApiRequest。
"""

from enum import StrEnum
from typing import Any, Literal
from pydantic import Field

from app.schemas.requests.base import BaseApiRequest


# =========================================================================
# 枚举定义 (带详尽中文释义)
# =========================================================================

class PipelineRunMode(StrEnum):
    """流水线执行与干预控制模式枚举。"""

    STAGE_BY_STAGE = "stage_by_stage"
    """逐阶段强干预模式：每完成一个创作阶段自动挂起（Stage 1-5），等待编剧人工审核或修改确认后方可继续流转。"""

    TWO_JOURNEY = "two_journey"
    """两程干预模式：第一程剧本创作（阶段 1~5）连续极速生成，在剧本定稿与视听工程交接处设立核心质检门禁（Gatekeeper），人工核准后流转至第二程视听制作。"""

    FULL_AUTO = "full_auto"
    """全自动极速模式：全流程全自动连续流转，跳过所有非致命的人工干预检查点，适用于无人值守批处理或基准测试。"""


class HitlStrategy(StrEnum):
    """人工干预审核 (Human-In-The-Loop) 策略枚举。"""

    STRICT = "strict"
    """严格审核策略：每个关键节点均须人工核准确认，不通过则持续阻塞流水线。"""

    KEY_NODES = "key_nodes"
    """关键节点审核：仅在阶段 3 大纲和阶段 5 定稿等关键节点触发人工审核，其余阶段自动放行。"""

    AUTO = "auto"
    """自动跳过审核：自动放行所有审核节点，降级为无需等待交互的自动化流转。"""


class TwoJourneyGateAction(StrEnum):
    """两程九阶第一程至第二程核心门禁 (Gatekeeper) 的主创决策动作枚举。"""

    PROCEED = "proceed"
    """推进放行：批准当前第一程定稿剧本，正式将资产与场景清单交接至第二程视听工程。"""

    RESUME = "resume"
    """唤醒恢复：从当前挂起检查点恢复流水线继续执行。"""

    RETRY = "retry"
    """重试驳回：对当前阶段产物发起重新生成，根据反馈意见进行原位迭代修补。"""


class ScriptExportType(StrEnum):
    """剧本资产导出目标格式类型枚举。"""

    ALL = "all"
    """打包导出全部产物（包含剧本正文、四幕大纲、人物小传、分镜表与质检雷达报告）。"""

    PDF = "pdf"
    """导出为标准行业格式排版的 PDF 电子剧本。"""

    WORD = "word"
    """导出为 Microsoft Word (.docx) 格式剧本文档，便于传统编剧二次修订。"""

    CSV = "csv"
    """导出为 CSV 格式分集与场景镜头对照表格。"""

    JSON = "json"
    """导出为完整工业化 AST 结构化 JSON 数据集。"""

    AUDIT_REPORT = "audit_report"
    """仅导出五阶质检与复盘审计分析报告。"""


# =========================================================================
# 1. 流水线生命周期与干预请求模型
# =========================================================================

class PipelineStartRequest(BaseApiRequest):
    """启动短剧剧本生成流水线请求模型。"""

    user_prompt: str = Field(
        ...,
        description="用户初始创作提示词或故事核心梗概，作为剧本创作的原点输入",
    )
    genre: str = Field(
        "现代",
        description="短剧题材分类（如：现代、古装、悬疑、科幻、战神、甜宠等）",
    )
    type: str | None = Field(
        "剧情",
        description="短剧类型分类（如：剧情、喜剧、动作、悬疑等）",
    )
    total_episodes: int = Field(
        80,
        description="规划总集数（推荐 5~100 集，默认 80 集标准竖屏短剧）",
    )
    episode_duration: str | None = Field(
        "90s",
        description="单集期望时长描述字符串（如 60s/90s/120s）",
    )
    paywall_episodes: str | None = Field(
        "10,15,20",
        description="核心付费卡点集数（逗号分隔，如 '10,15,20'）",
    )
    concurrency_mode: str | None = Field(
        "2-3",
        description="并发生成模式区间（如 1/2-3/4-5，用于控制单批次 LLM 并发调用数）",
    )
    commercial_tag: str = Field(
        "现代-剧情",
        description="商业定位标签（结合题材与类型的复合标签）",
    )
    hitl_mode: bool = Field(
        True,
        description="是否启用人工干预模式（在阶段 3 大纲生成完毕后自动挂起等待编剧审阅确认）",
    )
    hitl_strategy: HitlStrategy | str | None = Field(
        HitlStrategy.STRICT,
        description="人工审核策略：strict(严格审核)/key_nodes(关键节点)/auto(全自动放行)",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] | None = Field(
        None,
        description="执行控制模式：stage_by_stage(逐阶段强干预)/two_journey(两程干预)/full_auto(全自动极速)",
    )


class PipelineUpdateStateRequest(BaseApiRequest):
    """编剧人工干预修改流水线状态请求模型。"""

    updates: dict[str, Any] = Field(
        ...,
        description="编剧人工修改的大纲、人物或高概念结构化数据字典",
    )
    as_node: str | None = Field(
        None,
        description="作为哪个节点的后续更新，默认 outline_generation",
    )


class EpisodePatchRequest(BaseApiRequest):
    """对单集触发质检 AST 局部原位定向修补请求模型。"""

    issues: list[str] = Field(
        default_factory=list,
        description="需要修补的质检缺陷问题描述列表",
    )
    deductions: dict[str, int] = Field(
        default_factory=dict,
        description="质检扣分项明细字典（键为缺陷分类代码，值为扣除分数）",
    )


class CascadeInvalidateRequest(BaseApiRequest):
    """级联失效标记请求模型（当上游设定变更时级联将下游分集置为陈旧）。"""

    changed_episode_num: int = Field(
        ...,
        description="修改了大纲或人设的源分集集数序号（从此集往后的分集均进入级联失效判定）",
    )


class TwoJourneyStartRequest(BaseApiRequest):
    """两程九阶全生命周期工业化流水线启动请求模型。"""

    user_prompt: str = Field(
        ...,
        description="用户初始创作提示词或故事核心梗概",
    )
    genre: str = Field(
        "现代",
        description="短剧题材分类（默认：现代）",
    )
    type: str | None = Field(
        None,
        description="短剧类型分类",
    )
    total_episodes: int = Field(
        12,
        description="规划总集数（推荐 5~100 集，两程九阶默认先期规划 12 集样片）",
    )
    target_duration_sec: float = Field(
        120.0,
        description="单集目标时长秒数（默认 120.0s）",
    )
    episode_duration: str | None = Field(
        None,
        description="单集时长描述字符串（如 90s、120s）",
    )
    visual_style: str = Field(
        "真人电影/超写实",
        description="第二程视听工程默认视觉风格基调",
    )
    aspect_ratio: str = Field(
        "9:16",
        description="画幅比例（默认竖屏 9:16）",
    )
    auto_proceed_to_visual: bool = Field(
        False,
        description="第一程定稿后是否跳过门禁自动直接流转进入第二程视听分镜工程",
    )
    commercial_tag: str | None = Field(
        None,
        description="商业定位标签",
    )
    paywall_episodes: str | None = Field(
        None,
        description="核心付费卡点集数",
    )
    concurrency_mode: str | None = Field(
        None,
        description="并发生成模式",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        PipelineRunMode.TWO_JOURNEY,
        description="执行控制模式：stage_by_stage(逐阶段强干预)/two_journey(两程干预)/full_auto(全自动极速)",
    )


class TwoJourneyGateConfirmRequest(BaseApiRequest):
    """两程九阶核心门禁审核确认请求模型。"""

    approved: bool = Field(
        True,
        description="是否批准放行门禁（True 表示通过，False 表示驳回或退回修改）",
    )
    feedback: str | None = Field(
        None,
        description="主创编剧审核反馈意见与修改批注",
    )
    action: TwoJourneyGateAction | str = Field(
        TwoJourneyGateAction.PROCEED,
        description="门禁操作：proceed(放行推进)/resume(恢复执行)/retry(重新生成)",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        PipelineRunMode.TWO_JOURNEY,
        description="唤醒或恢复时采用的执行控制模式：stage_by_stage/two_journey/full_auto",
    )


# =========================================================================
# 2. 阶段 1~3 多级架构设计落库请求模型
# =========================================================================

class SaveConceptDesignRequest(BaseApiRequest):
    """阶段 1：创意立项与高概念落库请求模型。"""

    concept_design: dict[str, Any] = Field(
        ...,
        description="创意立项与高概念完整结构字典（含核心冲突、受众画像、四幕主线等）",
    )
    title: str | None = Field(
        None,
        description="更新后的短剧标题",
    )
    description: str | None = Field(
        None,
        description="更新后的故事核心梗概",
    )


class SaveBibleDesignRequest(BaseApiRequest):
    """阶段 2：故事圣经与世界观设定落库请求模型。"""

    bible_design: dict[str, Any] = Field(
        ...,
        description="故事圣经与世界观完整结构字典（含世界观法则、人物九维矩阵、人物关系图谱等）",
    )


class SaveOutlineDesignRequest(BaseApiRequest):
    """阶段 3：三级大纲与主场景库落库请求模型。"""

    two_level_acts: list[dict[str, Any]] | None = Field(
        None,
        description="二级四幕大纲数组（起承转合核心阶段目标与关键情节点）",
    )
    three_level_beats: list[dict[str, Any]] | None = Field(
        None,
        description="三级分集微观节拍列表（逐集的剧情钩子、冲突升级与反转卡点）",
    )
    main_scenes_pool: list[dict[str, Any]] | None = Field(
        None,
        description="全剧主场景库定义列表（场景编码、空间特征、复用频次等）",
    )


# =========================================================================
# 3. 阶段 4：分集剧本生成与维护请求模型
# =========================================================================

class SaveEpisodeScriptRequest(BaseApiRequest):
    """阶段 4：单集剧本 AST 与质检数据保存请求模型。"""

    title: str | None = Field(
        None,
        description="分集标题",
    )
    commercial_tag: str | None = Field(
        None,
        description="商业定位标签（如付费前哨、高潮卡点等）",
    )
    scenes: str | None = Field(
        None,
        description="场景概述与地点列表",
    )
    characters: str | None = Field(
        None,
        description="出场人物列表",
    )
    props: str | None = Field(
        None,
        description="关键道具列表",
    )
    ast_blocks: dict[str, Any] = Field(
        ...,
        description="AST 四分块结构化剧本内容字典（scene_heading/action/character/dialogue）",
    )
    qa_score: int | None = Field(
        None,
        description="五阶质检综合评测得分 (0~100)",
    )
    radar_scores: dict[str, Any] | None = Field(
        None,
        description="五维雷达评分字典（钩子强度/节奏张力/人设一致性/视听适配度/情绪共鸣度）",
    )
    qa_patches: list[dict[str, Any]] | None = Field(
        None,
        description="缺陷定位与修补建议项明细列表",
    )
    character_info_gaps: list[dict[str, Any]] | None = Field(
        None,
        description="角色实时信息差矩阵（各主要角色在当前分集掌握的已知与未知秘密）",
    )


class BatchGenerateRequest(BaseApiRequest):
    """批量触发分集剧本生成请求模型。"""

    start_episode: int = Field(
        ...,
        description="起始集数序号（闭区间，含）",
    )
    end_episode: int = Field(
        ...,
        description="结束集数序号（闭区间，含）",
    )
    batch_size: int = Field(
        3,
        description="并发生成批次窗口大小（如 2~3）",
    )


class AddEpisodeRequest(BaseApiRequest):
    """手动新增单集请求模型。"""

    episode_number: int | None = Field(
        None,
        description="指定集序号，不填则根据当前最大集号自动递增",
    )
    title: str = Field(
        ...,
        description="分集标题",
    )
    commercial_tag: str | None = Field(
        "常规剧情集",
        description="商业定位标签",
    )
    description: str | None = Field(
        None,
        description="剧情大纲或动作描述",
    )
    duration: int = Field(
        90,
        description="单集预期时长（秒）",
    )


# =========================================================================
# 4. 阶段 5：复盘定稿、导出与自愈请求模型
# =========================================================================

class ExportScriptRequest(BaseApiRequest):
    """阶段 5：剧本资产导出请求模型。"""

    export_type: ScriptExportType | str = Field(
        ScriptExportType.ALL,
        description="导出类型：all(打包全部)/pdf/word/csv/json/audit_report",
    )
    include_storyboards: bool = Field(
        True,
        description="是否包含视听分镜镜头数据",
    )
    include_qa_report: bool = Field(
        True,
        description="是否包含五阶质检分析报告",
    )


class HealEpisodeRequest(BaseApiRequest):
    """单集自动原位修复愈合请求模型。"""

    episode_num: int = Field(
        ...,
        description="需要自愈修补的目标分集序号",
    )
    target_score: int | None = Field(
        92,
        description="期望自愈达到的最低目标分 (默认 92 分)",
    )


class HealClueRequest(BaseApiRequest):
    """断裂伏笔线索自动回收修复请求模型。"""

    clue_id: str = Field(
        ...,
        description="需要补全回收的伏笔 ID (如 CLUE_001)",
    )
    recover_episode: int | None = Field(
        None,
        description="指定回收该伏笔的目标集数（不填则由系统自动推断合理回收集）",
    )


__all__ = [
    "PipelineRunMode",
    "HitlStrategy",
    "TwoJourneyGateAction",
    "ScriptExportType",
    "PipelineStartRequest",
    "PipelineUpdateStateRequest",
    "EpisodePatchRequest",
    "CascadeInvalidateRequest",
    "TwoJourneyStartRequest",
    "TwoJourneyGateConfirmRequest",
    "SaveConceptDesignRequest",
    "SaveBibleDesignRequest",
    "SaveOutlineDesignRequest",
    "SaveEpisodeScriptRequest",
    "BatchGenerateRequest",
    "AddEpisodeRequest",
    "ExportScriptRequest",
    "HealEpisodeRequest",
    "HealClueRequest",
]
