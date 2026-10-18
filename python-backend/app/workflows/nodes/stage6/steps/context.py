"""阶段 6 统一全生命周期上下文容器 (Stage 6 Step Context)。

本模块定义了阶段 6 执行上下文 `Stage6StepContext`，用于在 7 个标准化子步骤之间
安全传递剧本特征、上游依赖、中间资产、状态标志位与性能度量数据。
"""
from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any, Mapping

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    VisualAudioAssetsRegistryModel,
)
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag

logger = logging.getLogger("lmd.stage6.context")


@dataclasses.dataclass
class Stage6StepContext:
    """【阶段 6 执行上下文容器】承载单集资产提纯与真理源校验全链路的数据容器。

    详细说明：
        本上下文贯彻两程九阶中“单集独立切片 + 全剧真理源原子合并”设计原则，
        统一集中管理输入依赖、中间扫描产物、动态候选资产与最终产出的单集资源引单（Manifest）。
        内部提供状态标志位（Stage6StepFlag）的原子变更与耗时追踪能力，
        为分布式追踪与 Debug 调试提供统一日志载体。

    Attributes:
        state: 原始工作流状态输入 (支持 EpisodeScopedSubState/GlobalDramaMasterState/dict 等)。
        episode_number: 当前执行的单集集数（1-based 整数）。
        episode_title: 当前集爆款标题。
        script: 当前集的剧本结构化对象。
        screenplay_text: 从当前集提取出的纯文本正文。
        aspect_ratio: 画幅比例（默认 9:16）。
        visual_style: 导演视听规范与视觉基调（来自 Stage 1 视听圣经）。
        target_video_engine: 下游目标视频生成引擎（如 kling_1.6_high_fidelity）。
        previous_pickup: 上一集 0 秒物理接力快照字典（若当前为首集则为 None）。
        char_list: 阶段 2 已知的角色档案列表。
        scene_list: 阶段 3 已知的一级物理场景列表。
        prop_list: 阶段 3 已知的一级核心道具列表。
        char_tokens: 角色 Token 白名单集合（如 {"LINCHEN", "ZHOUYAN"}）。
        scene_tokens: 场景 Token 白名单集合。
        prop_tokens: 道具 Token 白名单集合。
        characters_engine: 角色引擎配置字典。
        environments_and_props: 场景道具引擎配置字典。
        registry: 当前全局视听资产真理源字典。
        manifests: 已编译的各集资源引单字典（key 为集数字符串）。
        scanner_result: 步骤 2 产出的剧本逆向特征扫描器结果 (ScreenplayScanResult)。
        summary_findings: 步骤 2 产出的高密度线索与视听动线摘要文本。
        projected_chars: 步骤 3 过滤后当前集真正出场的轻量角色列表。
        projected_envs: 步骤 3 过滤后的轻量场景列表。
        projected_props: 步骤 3 过滤后的轻量道具列表。
        vector_candidates: 步骤 3 召回的动态向量候选资产池。
        extracted_assets_raw: 步骤 4 大模型或 Fallback 提纯出的原始资产字典列表。
        dossier_new_chars: 步骤 5 新发掘并完成 11 维建档的新角色列表。
        dossier_new_scenes: 步骤 5 新发掘并完成建档的新场景列表。
        dossier_new_props: 步骤 5 新发掘并完成建档的新道具列表。
        derived_slices: 步骤 6 算子派生出的视角/微距/风化/破坏态切片列表。
        master_voice_cards: 步骤 6 生成的角色声音主母卡列表。
        lineage_dag: 步骤 7 校验纠偏后的资产血统 DAG 拓扑图。
        newly_generated_assets: 步骤 7 产出的本集全新生成资产列表 (NewlyGeneratedAssetModel)。
        reused_assets: 步骤 7 产出的本集复用上游资产列表 (ReusedAssetModel)。
        manifest: 步骤 7 编译完成的当前集资源引单 (EpisodeResourceManifest)。
        updated_registry: 步骤 7 合并更新后的全局真理源 (VisualAudioAssetsRegistryModel)。
        output: 节点最终返回的工作流 State 增量更新字典。
        flags: 当前流水线完成的状态旗帜位掩码。
        step_timings: 各步骤执行耗时记录字典 (单位: 秒)。
        stats: 各步骤关键统计数据 (用于调试与审计日志)。
        errors: 记录非致命性降级错误或警告日志。
    """

    # --- 1. 输入数据与上游依赖 ---
    state: Any = None
    episode_number: int = 1
    episode_title: str = ""
    drama_genre: str = ""
    genre_pack: Any = None
    script: dict[str, Any] = dataclasses.field(default_factory=dict)
    screenplay_text: str = ""
    aspect_ratio: str = "9:16"
    visual_style: str = "电影质感，冷调颗粒，8k超高清写实，戏剧性侧逆光"
    target_video_engine: str = "kling_1.6_high_fidelity"
    previous_pickup: dict[str, Any] | None = None

    # --- 2. 已知实体与白名单 ---
    char_list: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    scene_list: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    prop_list: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    char_tokens: set[str] = dataclasses.field(default_factory=set)
    scene_tokens: set[str] = dataclasses.field(default_factory=set)
    prop_tokens: set[str] = dataclasses.field(default_factory=set)
    characters_engine: dict[str, Any] = dataclasses.field(default_factory=dict)
    environments_and_props: dict[str, Any] = dataclasses.field(default_factory=dict)

    # --- 3. 真理源总库与引单清单 ---
    registry: dict[str, Any] = dataclasses.field(default_factory=dict)
    manifests: dict[str, Any] = dataclasses.field(default_factory=dict)

    # --- 4. 中间步骤产物 ---
    scanner_result: Any | None = None
    summary_findings: str = ""
    projected_chars: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    projected_envs: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    projected_props: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    vector_candidates: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    extracted_assets_raw: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    dossier_new_chars: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    dossier_new_scenes: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    dossier_new_props: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    derived_slices: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    master_voice_cards: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    lineage_dag: dict[str, Any] = dataclasses.field(default_factory=dict)
    newly_generated_assets: list[Any] = dataclasses.field(default_factory=list)
    reused_assets: list[Any] = dataclasses.field(default_factory=list)
    manifest: EpisodeResourceManifest | None = None
    updated_registry: VisualAudioAssetsRegistryModel | None = None

    # --- 5. 输出与状态度量 ---
    output: dict[str, Any] = dataclasses.field(default_factory=dict)
    flags: Stage6StepFlag = Stage6StepFlag.NONE
    step_timings: dict[str, float] = dataclasses.field(default_factory=dict)
    stats: dict[str, Any] = dataclasses.field(default_factory=dict)
    errors: list[str] = dataclasses.field(default_factory=list)

    def mark_flag(self, flag: Stage6StepFlag) -> None:
        """【状态变更】原子点亮指定步骤的格式旗帜。

        Args:
            flag (Stage6StepFlag): 待追加激活的步骤状态标志。
        """
        self.flags |= flag
        logger.debug(
            "【阶段 6 上下文】状态旗帜跃迁: +%s (当前全量掩码值: 0b%s)",
            flag.name,
            bin(self.flags.value),
        )

    def has_flag(self, flag: Stage6StepFlag) -> bool:
        """【状态查询】校验指定步骤标志位是否已全部点亮。

        Args:
            flag (Stage6StepFlag): 待校验的目标标志位。

        Returns:
            bool: 若目标标志位均已激活返回 True，否则返回 False。
        """
        return (self.flags & flag) == flag

    def record_timing(self, step_name: str, duration_sec: float) -> None:
        """【性能审计】记录子步骤执行耗时。

        Args:
            step_name (str): 子步骤名称标识。
            duration_sec (float): 执行所花费的秒数。
        """
        self.step_timings[step_name] = round(duration_sec, 4)
        logger.debug(
            "【阶段 6 耗时审计】步骤 [%s] 执行完毕，耗时: %.4f 秒",
            step_name,
            duration_sec,
        )
