"""短剧项目管理与 AI 生成 API 请求数据传输模型 (DTO / Schema)。

职责：
- 封装短剧创建、信息更新、大纲保存、角色设定、分集剧本管理、画布布局等 REST API 请求。
- 封装 AI 故事生成与全套角色生成的请求入参规范。
- 统一继承 BaseApiRequest，提供自动去首尾空白与 extra='ignore' 安全防御。
"""

from enum import StrEnum
from typing import Any
from pydantic import Field

from app.schemas.requests.base import BaseApiRequest


# =========================================================================
# 枚举定义 (带详尽中文释义)
# =========================================================================

class DramaProjectStatus(StrEnum):
    """短剧项目生命周期状态枚举。"""

    DRAFT = "draft"
    """草稿阶段：项目创建初期，大纲或人物设定尚未锁定，仍在自由编辑创作中。"""

    IN_PROGRESS = "in_progress"
    """制作中：剧本生成或视听工坊正在进行中。"""

    LOCKED = "locked"
    """定稿锁定：剧本第一程已通过主创审核定稿，版本被锁定进入视听工程。"""

    PUBLISHED = "published"
    """已发布：全片视听制作完成并已正式导出或发布上线。"""

    ARCHIVED = "archived"
    """已归档：项目创作完毕或终止，放入历史归档库中只读备份。"""


class CharacterRoleType(StrEnum):
    """剧本角色定位与戏剧功能分类枚举。"""

    PROTAGONIST = "protagonist"
    """主角/男女主：故事核心驱动者，背负主线愿望、核心动机与人物弧光。"""

    ANTAGONIST = "antagonist"
    """反派/对手：制造核心阻碍与危机对立的核心对立角色。"""

    SUPPORTING = "supporting"
    """重要配角：协助主角或反派推进情节、提供关键信息或反转动力的配角。"""

    EXTRA = "extra"
    """龙套/背景角色：仅在特定场景中充当氛围背景或简单对话的工具人物。"""


# =========================================================================
# 1. 短剧项目 CRUD 请求模型
# =========================================================================

class DramaCreate(BaseApiRequest):
    """创建短剧项目请求模型。"""

    title: str = Field(
        ...,
        min_length=1,
        description="短剧项目定名（必填，如：《顾总的替嫁娇妻》）",
    )
    description: str | None = Field(
        default=None,
        description="短剧故事核心梗概与一句话卖点简介",
    )
    genre: str | None = Field(
        default=None,
        description="短剧题材分类（如：现代言情、都市逆袭、战神神豪、悬疑惊悚、科幻重生等）",
    )
    style: str | None = Field(
        default="realistic",
        description="画面与美术风格基调（如：realistic 写实胶片、anime 动漫二次元、cinematic 电影质感）",
    )
    tags: str | None = Field(
        default=None,
        description="项目标签（多个标签以逗号分隔，如：反转,爽文,打脸）",
    )
    metadata: dict[str, Any] | str | None = Field(
        default_factory=dict,
        description="项目扩展元数据字典或 JSON 字符串",
    )


class DramaUpdate(BaseApiRequest):
    """更新短剧项目基本信息请求模型。"""

    title: str | None = Field(
        default=None,
        description="更新后的短剧标题",
    )
    description: str | None = Field(
        default=None,
        description="更新后的故事核心梗概简介",
    )
    genre: str | None = Field(
        default=None,
        description="更新后的题材分类",
    )
    style: str | None = Field(
        default=None,
        description="更新后的美术风格基调",
    )
    tags: str | None = Field(
        default=None,
        description="更新后的项目标签（逗号分隔）",
    )
    metadata: dict[str, Any] | str | None = Field(
        default=None,
        description="更新后的元数据配置",
    )
    status: DramaProjectStatus | str | None = Field(
        default=None,
        description="项目状态：draft(草稿)/in_progress(制作中)/locked(定稿锁定)/published(已发布)/archived(已归档)",
    )


class DramaOutlineUpdate(BaseApiRequest):
    """保存剧本大纲与项目核心设定请求模型。"""

    title: str | None = Field(
        default=None,
        description="剧本定名",
    )
    summary: str | None = Field(
        default=None,
        description="故事主线大纲梗概与四幕起承转合",
    )
    genre: str | None = Field(
        default=None,
        description="题材分类",
    )
    style: str | None = Field(
        default=None,
        description="视觉风格基调",
    )
    metadata: dict[str, Any] | str | None = Field(
        default=None,
        description="项目元数据扩展配置",
    )


# =========================================================================
# 2. 角色与分集批量维护模型
# =========================================================================

class DramaCharacterItem(BaseApiRequest):
    """单个角色数据定义模型。"""

    id: int | str | None = Field(
        default=None,
        description="角色数据库主键 ID（若为更新既有角色）",
    )
    name: str = Field(
        ...,
        min_length=1,
        description="角色名称（如：陆沉、苏晚晴）",
    )
    role: CharacterRoleType | str | None = Field(
        default=CharacterRoleType.SUPPORTING,
        description="角色戏剧定位：protagonist(主角)/antagonist(反派)/supporting(重要配角)/extra(龙套)",
    )
    description: str | None = Field(
        default=None,
        description="角色生平与戏剧功能设定描述",
    )
    appearance: str | None = Field(
        default=None,
        description="角色外貌体征、骨相、穿搭与服饰特征",
    )
    personality: str | None = Field(
        default=None,
        description="角色性格特征与行为逻辑",
    )
    voice_style: str | None = Field(
        default=None,
        description="配音与音色音质要求（如：清冷低沉、干练果决、沙哑沧桑）",
    )
    sort_order: int = Field(
        default=0,
        description="角色展示排序权重（数值越小越靠前）",
    )
    extra_images: str | list | None = Field(
        default=None,
        description="额外参考图片 URL 或列表",
    )
    ref_image: str | None = Field(
        default=None,
        description="主参考标准立绘图片 URL",
    )
    image_url: str | None = Field(
        default=None,
        description="角色标准立绘图 URL",
    )
    negative_prompt: str | None = Field(
        default=None,
        description="该角色文生图时的专属负向提示词",
    )


class DramaCharactersUpdate(BaseApiRequest):
    """批量保存剧本角色请求模型。"""

    characters: list[dict[str, Any] | DramaCharacterItem] = Field(
        ...,
        description="角色列表数据数组",
    )


class DramaEpisodeItem(BaseApiRequest):
    """单集剧本定义模型。"""

    id: int | str | None = Field(
        default=None,
        description="分集数据库主键 ID（若为既有分集）",
    )
    episode_number: int = Field(
        ...,
        description="集数序号（如第 1 集）",
    )
    title: str | None = Field(
        default=None,
        description="单集标题",
    )
    script_content: str | None = Field(
        default=None,
        description="单集剧本文本内容（标准分场格式）",
    )
    duration: int | float | None = Field(
        default=0,
        description="预估时长（秒）",
    )


class DramaEpisodesUpdate(BaseApiRequest):
    """批量保存分集剧本请求模型。"""

    episodes: list[dict[str, Any] | DramaEpisodeItem] = Field(
        ...,
        description="分集剧本列表数据数组",
    )


# =========================================================================
# 3. 创作进度与无限画布布局模型
# =========================================================================

class DramaProgressUpdate(BaseApiRequest):
    """保存剧本创作进度步骤请求模型。"""

    current_step: str = Field(
        ...,
        min_length=1,
        description="当前进度步骤标识（如：outline, characters, script, storyboard）",
    )
    step_data: dict[str, Any] | None = Field(
        default_factory=dict,
        description="当前步骤的附加状态数据字典",
    )


class DramaCanvasLayoutUpdate(BaseApiRequest):
    """保存无限画布节点与连线布局请求模型。"""

    nodes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="画布节点集合（位置、大小、挂载数据）",
    )
    edges: list[dict[str, Any]] = Field(
        default_factory=list,
        description="画布连线边集合（源节点、目标节点与关系类型）",
    )
    transform: dict[str, Any] | list | None = Field(
        default_factory=dict,
        description="视口平移与缩放坐标 {x, y, zoom}",
    )


# =========================================================================
# 4. AI 故事与角色全套生成请求模型
# =========================================================================

class StoryGenerationRequest(BaseApiRequest):
    """AI 剧本故事生成请求规范模型。"""

    drama_id: int | str | None = Field(
        default=None,
        description="关联短剧 ID（若在既有项目中发起生成）",
    )
    topic: str | None = Field(
        default=None,
        description="故事题材方向或核心冲突主线提示词",
    )
    title: str | None = Field(
        default=None,
        description="建议短剧名称（若提供则作为优先剧名参考）",
    )
    genre: str | None = Field(
        default="都市逆袭",
        description="剧本题材分类（如：都市逆袭、甜宠虐恋、悬疑烧脑等）",
    )
    drama_style: str | None = Field(
        default="realistic",
        description="画面风格基调（如：realistic、cinematic、anime）",
    )
    summary: str | None = Field(
        default=None,
        description="故事梗概或原著主线输入",
    )
    target_episodes: int = Field(
        default=80,
        ge=1,
        le=200,
        description="期望规划生成的总集数（1~200 集）",
    )
    target_duration: int = Field(
        default=90,
        description="单集目标成片时长（秒）",
    )
    characters: list[dict[str, Any]] | None = Field(
        default=None,
        description="预设角色列表数据（可选）",
    )
    workflow_run_id: str | None = Field(
        default=None,
        description="关联异步工作流运行任务 ID",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="附加元数据字典",
    )


class CharacterGenerationRequest(BaseApiRequest):
    """AI 角色全套生成请求规范模型。"""

    drama_id: int | str = Field(
        ...,
        description="关联短剧项目 ID",
    )
    prompt: str | None = Field(
        default=None,
        description="自定义角色设定要求与提取提示词",
    )
    character_count: int = Field(
        default=4,
        ge=1,
        le=20,
        description="期望提取生成的角色数量（1~20 人）",
    )
    genre: str | None = Field(
        default=None,
        description="题材参考基调",
    )
    style: str | None = Field(
        default=None,
        description="风格参考基调",
    )


__all__ = [
    "DramaProjectStatus",
    "CharacterRoleType",
    "DramaCreate",
    "DramaUpdate",
    "DramaOutlineUpdate",
    "DramaCharacterItem",
    "DramaCharactersUpdate",
    "DramaEpisodeItem",
    "DramaEpisodesUpdate",
    "DramaProgressUpdate",
    "DramaCanvasLayoutUpdate",
    "StoryGenerationRequest",
    "CharacterGenerationRequest",
]
