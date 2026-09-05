"""整剧世界观与剧本设定 Schema (DramaBible & EpisodeScript)。

包含整剧设定集（DramaBible）、单集分场剧本（EpisodeScript）以及单场动作戏份（SceneSegment）。
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class DialogueLine(BaseModel):
    """单条台词/对白/旁白。"""
    character_name: str = Field(..., description="说话角色名称（'旁白' 表示旁白音）")
    dialogue_type: Literal["dialogue", "narration", "inner_monologue", "voiceover"] = Field(
        default="dialogue", description="台词类型：对白、旁白、内心独白、画外音"
    )
    text: str = Field(..., description="对白文本内容")
    emotion: str = Field(default="平静", description="说话情绪（如：愤怒、冷笑、哽咽、惊慌、戏谑）")
    action_cue: str = Field(default="", description="说话时的肢体动作或神态提示")


class SceneSegment(BaseModel):
    """剧本单场次设定（场号、场景、角色、动作、对白）。"""
    scene_number: int = Field(default=1, description="集内场次编号（第X场）")
    location_name: str = Field(..., description="场景地点名称（如：豪门客厅、破旧出租屋、雷雨天悬崖边）")
    interior_exterior: Literal["interior", "exterior"] = Field(default="interior", description="室内 (INT) / 室外 (EXT)")
    time_of_day: Literal["day", "night", "dawn", "dusk"] = Field(default="day", description="时间（日/夜/晨/昏）")
    atmosphere: str = Field(default="紧张对峙", description="场景环境氛围与光线基调")
    characters_present: list[str] = Field(default_factory=list, description="本场出场角色名单")
    action_description: str = Field(..., description="动作与画面调度描述（影视化动作语言）")
    dialogue_list: list[DialogueLine] = Field(default_factory=list, description="场内台词对白列表")
    duration_estimate_seconds: int = Field(default=20, ge=1, description="本场预估拍摄时长（秒）")


class EpisodeOutline(BaseModel):
    """单集大纲与剧情规划。"""
    episode_number: int = Field(..., description="集数编号")
    title: str = Field(default="", description="单集标题")
    logline: str = Field(..., description="一句话本集核心梗概")
    opening_hook: str = Field(..., description="前3秒黄金抓人钩子与矛盾切入点")
    main_conflict: str = Field(..., description="核心剧情推进与打脸/冲突点")
    ending_cliffhanger: str = Field(..., description="结尾悬念与致命下集卡点")
    is_paywall_episode: bool = Field(default=False, description="是否为付费/卡点重点集")


class DramaBible(BaseModel):
    """整部短剧设定集 (Drama Bible)。

    统筹整剧的世界观、核心人物关系网络、全集节奏脉络以及视听总基调。
    """
    title: str = Field(..., description="剧本定名")
    genre: str = Field(..., description="剧本题材类型")
    logline: str = Field(..., description="整剧一句话故事梗概（核心卖点与主线）")
    synopsis: str = Field(..., description="整剧故事梗概与剧情全貌")
    total_episodes: int = Field(default=80, description="规划总集数")
    worldview_rules: list[str] = Field(default_factory=list, description="世界观核心法则与社会设定（如等级规则、隐世势力等）")
    character_relationships: dict[str, str] = Field(
        default_factory=dict, description="主要人物关系网与冲突阵营描述"
    )
    visual_tone: str = Field(
        default="高对比度写实光影，电影质感，运镜节奏凌厉紧凑", description="全剧视觉美术基调与色彩风格"
    )
    sound_tone: str = Field(
        default="情绪饱满张力强，重音与打击感突显打脸反转", description="全剧声音基调与对白质感要求"
    )
    music_direction: str = Field(
        default="快节奏管弦+现代电子合成器，强调紧张压迫与高潮释放", description="BGM 音乐总谱风格规划"
    )
    episode_outlines: list[EpisodeOutline] = Field(
        default_factory=list, description="全剧分集大纲列表"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class EpisodeScript(BaseModel):
    """单集完整剧本（包含场次、台词、动作、视听标记）。"""
    drama_id: int | None = Field(default=None, description="所属短剧 ID")
    episode_number: int = Field(..., description="集数编号")
    title: str = Field(default="", description="集标题")
    synopsis: str = Field(default="", description="单集剧情摘要")
    opening_hook: str = Field(..., description="前3秒黄金钩子设计")
    scenes: list[SceneSegment] = Field(default_factory=list, description="单集分场场景与对白列表")
    climax_reversal: str = Field(default="", description="单集核心高潮/反转打脸点")
    ending_cliffhanger: str = Field(..., description="结尾悬念与卡点钩子")
    estimated_duration_seconds: int = Field(default=90, description="预估单集成片时长（秒）")
    is_paywall_episode: bool = Field(default=False, description="是否为商业付费卡点集")
    raw_script_text: str = Field(default="", description="格式化剧本文本完整备份")


# ---------------- 业务 CRUD 与生成请求 Schema ----------------


class DramaCreate(BaseModel):
    """创建短剧项目请求。"""
    title: str = Field(..., min_length=1, description="短剧标题（必填）")
    description: str | None = Field(default=None, description="短剧故事简介")
    genre: str | None = Field(default=None, description="短剧题材分类（如：都市、逆袭、战神、甜宠）")
    style: str | None = Field(default="realistic", description="画面与美术风格（如：realistic, anime）")
    tags: str | None = Field(default=None, description="标签逗号分隔")
    metadata: dict[str, Any] | str | None = Field(default_factory=dict, description="项目元数据配置")


class DramaUpdate(BaseModel):
    """更新短剧项目信息请求。"""
    title: str | None = Field(default=None, description="更新后的短剧标题")
    description: str | None = Field(default=None, description="更新后的故事简介")
    genre: str | None = Field(default=None, description="更新后的题材分类")
    style: str | None = Field(default=None, description="更新后的美术风格")
    tags: str | None = Field(default=None, description="更新后的标签")
    metadata: dict[str, Any] | str | None = Field(default=None, description="更新后的元数据")
    status: str | None = Field(default=None, description="项目状态（draft, published 等）")


class DramaOutlineUpdate(BaseModel):
    """保存剧本大纲与项目核心设定请求。"""
    title: str | None = Field(default=None, description="剧本定名")
    summary: str | None = Field(default=None, description="故事主线大纲梗概")
    genre: str | None = Field(default=None, description="题材分类")
    style: str | None = Field(default=None, description="视觉风格")
    metadata: dict[str, Any] | str | None = Field(default=None, description="项目元数据扩展配置")


class DramaCharacterItem(BaseModel):
    """单个角色数据定义。"""
    id: int | str | None = Field(default=None, description="角色ID（若为既有角色）")
    name: str = Field(..., min_length=1, description="角色名称")
    role: str | None = Field(default="supporting", description="角色定位（protagonist, antagonist, supporting 等）")
    description: str | None = Field(default=None, description="角色生平与设定描述")
    appearance: str | None = Field(default=None, description="角色外貌体型与服饰特征")
    personality: str | None = Field(default=None, description="角色性格特征")
    voice_style: str | None = Field(default=None, description="配音与音色要求")
    sort_order: int = Field(default=0, description="排序权重")
    extra_images: str | list | None = Field(default=None, description="额外参考图片")
    ref_image: str | None = Field(default=None, description="主参考图片")
    image_url: str | None = Field(default=None, description="角色立绘 URL")
    negative_prompt: str | None = Field(default=None, description="负向提示词")


class DramaCharactersUpdate(BaseModel):
    """批量保存剧本角色请求。"""
    characters: list[dict[str, Any] | DramaCharacterItem] = Field(..., description="角色列表数组")


class DramaEpisodeItem(BaseModel):
    """单集剧本定义。"""
    id: int | str | None = Field(default=None, description="集ID")
    episode_number: int = Field(..., description="集数序号")
    title: str | None = Field(default=None, description="单集标题")
    script_content: str | None = Field(default=None, description="单集剧本文本内容")
    duration: int | float | None = Field(default=0, description="预估时长")


class DramaEpisodesUpdate(BaseModel):
    """批量保存分集剧本请求。"""
    episodes: list[dict[str, Any] | DramaEpisodeItem] = Field(..., description="分集剧本列表数组")


class DramaProgressUpdate(BaseModel):
    """保存剧本创作进度请求。"""
    current_step: str = Field(..., min_length=1, description="当前进度步骤标识")
    step_data: dict[str, Any] | None = Field(default_factory=dict, description="当前步骤的附加数据")


class DramaCanvasLayoutUpdate(BaseModel):
    """保存无限画布节点与连线布局请求。"""
    nodes: list[dict[str, Any]] = Field(default_factory=list, description="画布节点集合")
    edges: list[dict[str, Any]] = Field(default_factory=list, description="画布连线集合")
    transform: dict[str, Any] | list | None = Field(default_factory=dict, description="视口平移与缩放坐标")


class StoryGenerationRequest(BaseModel):
    """AI 剧本故事生成请求规范。"""
    drama_id: int | str | None = Field(default=None, description="关联短剧 ID（若已创建项目）")
    topic: str | None = Field(default=None, description="故事题材或主线提示")
    title: str | None = Field(default=None, description="建议剧名")
    genre: str | None = Field(default="都市逆袭", description="剧本题材")
    drama_style: str | None = Field(default="realistic", description="画面风格")
    summary: str | None = Field(default=None, description="故事梗概或原著主线")
    target_episodes: int = Field(default=80, ge=1, le=200, description="期望生成的总集数")
    target_duration: int = Field(default=90, description="单集目标时长（秒）")
    characters: list[dict[str, Any]] | None = Field(default=None, description="预设角色列表")
    workflow_run_id: str | None = Field(default=None, description="关联工作流运行 ID")
    metadata: dict[str, Any] | None = Field(default=None, description="附加元数据")


class CharacterGenerationRequest(BaseModel):
    """AI 角色全套生成请求规范。"""
    drama_id: int | str = Field(..., description="关联短剧 ID")
    prompt: str | None = Field(default=None, description="自定义角色设定要求与提取提示")
    character_count: int = Field(default=4, ge=1, le=20, description="期望提取生成的角色数量")
    genre: str | None = Field(default=None, description="题材参考")
    style: str | None = Field(default=None, description="风格参考")
