# -*- coding: utf-8 -*-
"""工业化主图全局状态与分集子状态契约。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.master")

from app.schemas.states.core import (
    CandidateTitleMatrix,
    CharacterRelationshipItem,
    DoubleTrackProhibitions,
    DualTrackRelationshipItem,
    EmotionalArcTrajectory,
    merge_worker_results,
)
from app.schemas.states.audit import RedBlueAuditReport
from app.schemas.states.audio import AudioBible, AudioBibleSummary, AudioMasteringConfig
from app.schemas.states.asset import (
    EpisodeLocalAsset,
    EpisodeResourceManifest,
    VisualAudioAssetsRegistryModel,
)
from app.schemas.states.storyboard import StoryboardShot, StoryboardShotStub
from app.schemas.states.screenplay import (
    InterEpisodePhysicalContinuity,
    LiteraryScreenplayEpisodeModel,
    SeasonOutlineCard,
)


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
    journey: Literal["journey_1_literary", "journey_2_visual", "journey_2_visual_audio", "completed"] = Field(
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

    # 阶段 6 资产真理源完整状态契约 (跨集演化与资产落库)
    newly_generated_assets: list[dict[str, Any]] = Field(default_factory=list, description="阶段6生成的新增视听资产生成规格包列表")
    new_character_master_voice_cards: list[dict[str, Any]] = Field(default_factory=list, description="角色主音色母卡清单")
    lineage_dag: dict[str, Any] = Field(default_factory=dict, description="资产演进继承关系DAG")
    reused_existing_assets: list[dict[str, Any]] = Field(default_factory=list, description="复用的历史/库资产清单")
    episode_newly_generated_assets: dict[int, list[dict[str, Any]]] = Field(default_factory=dict, description="分集新增视听资产规格包映射")
    episode_reused_assets: dict[int, list[dict[str, Any]]] = Field(default_factory=dict, description="分集复用资产映射")

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
    
    # Stage 6 产物：单集增量资产引单与增量视听资产表
    episode_manifest: EpisodeResourceManifest | None = Field(default=None, description="单集视听资源引单")
    resource_manifest: EpisodeResourceManifest | None = Field(default=None, description="向后兼容旧命名：单集视听资源引单")
    episode_resource_manifest: EpisodeResourceManifest | None = Field(default=None, description="单集视听资源引单别名")
    manifest: EpisodeResourceManifest | dict[str, Any] | None = Field(default=None, description="单集引单快捷访问别名")
    new_character_master_voice_cards: list[dict[str, Any]] = Field(default_factory=list, description="本集新增角色主声线卡")
    newly_generated_assets: list[dict[str, Any]] = Field(default_factory=list, description="本集增量生成的物理视听资产")
    reused_existing_assets: list[dict[str, Any]] = Field(default_factory=list, description="本集复用的已有物理资产")
    lineage_dag: dict[str, Any] = Field(default_factory=dict, description="视听资产继承血统 DAG 图")
    
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

            m = (
                data.get("episode_manifest")
                or data.get("resource_manifest")
                or data.get("episode_resource_manifest")
                or data.get("manifest")
            )
            if m is not None:
                data["episode_manifest"] = m
                data["resource_manifest"] = m
                data["episode_resource_manifest"] = m
                data["manifest"] = m

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
    model_config = ConfigDict(extra="allow")

    drama_id: int = Field(default=0, description="短剧项目 ID")
    journey: Literal["journey_1_literary", "journey_2_visual", "journey_2_visual_audio", "completed"] = Field(
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
    new_character_master_voice_cards: list[Any] = Field(
        default_factory=list,
        description="阶段 6：新角色母音频卡片列表"
    )
    newly_generated_assets: list[Any] = Field(
        default_factory=list,
        description="阶段 6：本集新生成增量资产列表"
    )
    reused_existing_assets: list[Any] = Field(
        default_factory=list,
        description="阶段 6：本集复用资产列表"
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


class IndustrialDramaState(TypedDict, total=False):
    """【规则编号: RULE-VI-01 ~ RULE-VI-08】两程九阶全息闭环全局状态 TypedDict 契约 (LangGraph State)。
    
    严格对齐公共硬性约束：
    1. 大模型严禁参与任何业务分支判断，路由逻辑抽离至独立路由函数；
    2. State 统一使用 TypedDict 契约规范，节点统一入参 state，返回增量字典；
    3. 容器型字段使用 Annotated[dict, operator.ior] 实现分集增量自动合并；
    4. 分支全部穷举，兜底指向 error_terminal_node。
    """
    drama_id: int
    journey: Literal["journey_1_literary", "journey_2_visual", "journey_2_visual_audio", "completed"]
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


__all__ = [
    "CharacterAnchorStub",
    "SceneAnchorStub",
    "PropAnchorStub",
    "GlobalDramaMasterState",
    "EpisodeScopedSubState",
    "IndustrialDramaMasterState",
    "BiologicalPortraitDNADict",
    "LivedInCostumeSpecsDict",
    "AcousticPersonaDict",
    "PsychologicalQuadrupleDict",
    "CharacterProfileDict",
    "CharacterRelationshipItemDict",
    "DualTrackRelationshipItemDict",
    "EmotionalArcTrajectoryDict",
    "EnvironmentItemDict",
    "PropItemDict",
    "EpisodeOutlineItemDict",
    "IndustrialDramaState",
]
