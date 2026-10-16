# -*- coding: utf-8 -*-
"""自动化状态契约解耦与领域拆分脚本。

将超大单体 script_graph_state.py (3292行) 拆解至 app/schemas/states/ 领域包：
1. core.py: 企划、世界观、人物画像、大纲与瘦状态机
2. audit.py: 红蓝对抗与质检审计契约
3. audio.py: 声音资产、母带规范与音频圣经
4. asset.py: 资产真理层、多模态资产注册清单
5. storyboard.py: 分镜镜头、口型动态与媒体配置
6. screenplay.py: 文学剧本、集间物理状态连续性与钩子
7. master.py: 全局工业主图状态（GlobalDramaMasterState等）与单集子状态
8. __init__.py: 统一汇聚导出
9. script_graph_state.py: 门面（Facade）转发，确保 100% 向后兼容性
"""
from __future__ import annotations

import ast
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_FILE = BASE_DIR / "app" / "schemas" / "script_graph_state.py"
STATES_DIR = BASE_DIR / "app" / "schemas" / "states"

# 节点所属领域划分
DOMAINS = {
    "base": [
        "AssetState", "AssetGenerationMode"
    ],
    "core": [
        "ProjectProfile", "HighConcept", "WorldviewProfile", "GrowthChainItem",
        "BiologicalPortraitDNA", "LivedInCostumeSpecs", "PsychologicalQuadruple",
        "VoiceBehavioralFingerprint", "CarriedAnchorItem", "DualTrackRelationshipItem",
        "CharacterRelationshipItem", "EmotionalArcTrajectory", "CharacterProfile",
        "ClueItem", "ContinuityMemo", "EpisodeOutlineItem", "SingleSceneCheck",
        "ASTBlockItem", "AudioVisualBeat", "ScriptAST", "EpisodeScript", "QAReport",
        "merge_worker_results", "LeanDramaScriptState", "CandidateTitleMatrix",
        "DoubleTrackProhibitions", "DramaScriptState"
    ],
    "audit": [
        "AuditVerdict", "RedBlueAuditReport", "StageAuditReport"
    ],
    "audio": [
        "AudioMotifItem", "AudioBible", "MasterVoiceCardModel", "AcousticTraceability",
        "BgmGenerationConfig", "MasteringScheduleItemModel", "NleMixingGuidelines",
        "AudioMasteringConfig", "AudioBibleSummary", "AudioMotifItemDict",
        "AudioBibleDict", "MasterVoiceCardItem", "ShotAudioConfig",
        "MasteringScheduleItemDict", "EpisodeAudioSpecDict", "EpisodeAudioMasteringPlan"
    ],
    "asset": [
        "ReusedAssetModel", "NewlyGeneratedAssetModel",
        "EpisodeResourceManifest", "VisualAudioAssetsRegistryModel", "CharacterStageViewAsset",
        "CharacterStageAsset", "SceneWeatheringViewAsset", "SceneZoneAsset",
        "PropDetailViewAsset", "PropDamageStateAsset", "EpisodeLocalAsset",
        "ReusedAssetItem", "NewlyGeneratedAssetItem", "EpisodeResourceManifestDict",
        "VisualAudioAssetsRegistry"
    ],
    "storyboard": [
        "LipsyncDynamics", "StoryboardShot", "StoryboardShotStub", "FirstLastFrameConfig",
        "MediaImageItem", "MediaAudioItem", "MediaManifestDict", "MultiImageReferenceConfig",
        "ModeBManifestCheckDict", "LipSyncDynamicsConfig", "StoryboardShotDict"
    ],
    "screenplay": [
        "EpisodeScriptV2", "SeasonOutlineCard", "InterEpisodePhysicalContinuity",
        "PreviousEpisodePickup", "GoldenCliffhangerHook", "EpisodeEndPhysicalDelta",
        "LiteraryScreenplayEpisode", "GoldenCliffhangerHookModel",
        "EpisodeEndPhysicalDeltaModel", "PreviousEpisodePickupModel",
        "LiteraryScreenplayEpisodeModel"
    ],
    "master": [
        "CharacterAnchorStub", "SceneAnchorStub", "PropAnchorStub",
        "GlobalDramaMasterState", "EpisodeScopedSubState", "IndustrialDramaMasterState",
        "BiologicalPortraitDNADict", "LivedInCostumeSpecsDict", "AcousticPersonaDict",
        "PsychologicalQuadrupleDict", "CharacterProfileDict", "CharacterRelationshipItemDict",
        "DualTrackRelationshipItemDict", "EmotionalArcTrajectoryDict", "EnvironmentItemDict",
        "PropItemDict", "EpisodeOutlineItemDict", "IndustrialDramaState"
    ]
}

DOMAIN_TITLES = {
    "base": "状态机基础枚举与元类型契约",
    "core": "核心文学状态契约（企划、世界观、人物画像与大纲）",
    "audit": "剧本质检与红蓝对抗审计状态契约",
    "audio": "音频圣经、声音动机与声音母带规范状态契约",
    "asset": "多模态资产真理层与注册清单契约",
    "storyboard": "分镜头脚本、音画同步与视觉资产契约",
    "screenplay": "文学剧本、物理连续性与钩子契约",
    "master": "工业化主图全局状态与分集子状态契约"
}


def main():
    STATES_DIR.mkdir(parents=True, exist_ok=True)
    source_text = SOURCE_FILE.read_text(encoding="utf-8")
    source_lines = source_text.splitlines(keepends=True)
    tree = ast.parse(source_text)

    # 提取所有顶级节点及其源码片段
    node_map = {}
    for n in tree.body:
        if isinstance(n, (ast.ClassDef, ast.FunctionDef)):
            start = n.lineno - 1
            end = n.end_lineno
            # 包含节点上方的注释（如果有的话）
            while start > 0 and source_lines[start - 1].strip().startswith("#"):
                start -= 1
            node_map[n.name] = "".join(source_lines[start:end])
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    start = n.lineno - 1
                    end = n.end_lineno
                    node_map[t.id] = "".join(source_lines[start:end])

    # 验证是否全部覆盖
    all_assigned = []
    for items in DOMAINS.values():
        all_assigned.extend(items)
    missing = set(node_map.keys()) - set(all_assigned)
    if missing:
        raise RuntimeError(f"未分类节点: {missing}")

    # 分别生成每个领域的模块
    all_symbols_export = []
    for domain, names in DOMAINS.items():
        domain_file = STATES_DIR / f"{domain}.py"
        title = DOMAIN_TITLES[domain]

        # 基础头部导入
        header = f'''# -*- coding: utf-8 -*-
"""{title}。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.{domain}")
'''
        # 针对各领域的跨领域依赖显式导入
        extra_imports = ""
        if domain == "audio":
            extra_imports = "\nfrom app.schemas.states.base import AssetState\n"
        elif domain == "asset":
            extra_imports = "\nfrom app.schemas.states.base import AssetState, AssetGenerationMode\nfrom app.schemas.states.audio import MasterVoiceCardModel\n"
        elif domain == "storyboard":
            extra_imports = "\nfrom app.schemas.states.audio import ShotAudioConfig\n"
        elif domain == "screenplay":
            extra_imports = "\nfrom app.schemas.states.audit import StageAuditReport\n"
        elif domain == "master":
            extra_imports = '''
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
'''

        body_parts = []
        for name in names:
            body_parts.append(node_map[name])
            all_symbols_export.append(name)

        all_list_str = ",\n    ".join(f'"{name}"' for name in names)
        footer = f'''

__all__ = [
    {all_list_str},
]
'''
        full_content = header + extra_imports + "\n\n" + "\n\n".join(body_parts) + footer
        domain_file.write_text(full_content, encoding="utf-8")
        print(f"已生成领域模块: {domain_file.name} ({len(names)} 个模型/定义)")

    # 生成 app/schemas/states/__init__.py
    init_file = STATES_DIR / "__init__.py"
    init_imports = []
    for domain in DOMAINS.keys():
        init_imports.append(f"from app.schemas.states.{domain} import *  # noqa: F401, F403")

    init_all_str = ",\n    ".join(f'"{name}"' for name in all_symbols_export)
    init_content = f'''# -*- coding: utf-8 -*-
"""短剧状态机模型契约包 (State Schemas Package)。

解耦拆解为细粒度领域契约，同时在此处汇聚导出全部状态定义。
"""
from __future__ import annotations

{chr(10).join(init_imports)}

__all__ = [
    {init_all_str},
]
'''
    init_file.write_text(init_content, encoding="utf-8")
    print(f"已生成 states/__init__.py，汇聚导出 {len(all_symbols_export)} 个契约符号。")

    # 更新 app/schemas/script_graph_state.py 为标准门面
    facade_content = f'''# -*- coding: utf-8 -*-
"""LangGraph 短剧工业化创作状态数据契约门面 (Drama Script State Schema Facade)。

【架构解耦说明】
原单体大文件已按关注点分离原则拆解至 `app.schemas.states` 领域子包：
- core.py: 企划、世界观、人物画像、大纲与瘦状态机
- audit.py: 红蓝对抗与质检审计契约
- audio.py: 声音资产、母带规范与音频圣经
- asset.py: 资产真理层、多模态资产注册清单
- storyboard.py: 分镜镜头、口型动态与媒体配置
- screenplay.py: 文学剧本、集间物理状态连续性与钩子
- master.py: 全局工业主图状态（GlobalDramaMasterState等）与单集子状态

本门面保留完整向后兼容性，所有旧版 `from app.schemas.script_graph_state import ...` 导入完全不受影响。
"""
from __future__ import annotations

import logging

from app.schemas.states import *  # noqa: F401, F403
from app.schemas.states import __all__ as _states_all

logger = logging.getLogger("app.schemas.script_graph_state")
logger.debug("已加载状态契约领域门面模块 app.schemas.script_graph_state")

__all__ = _states_all
'''
    SOURCE_FILE.write_text(facade_content, encoding="utf-8")
    print("已成功将 script_graph_state.py 升级为状态契约领域门面！")


if __name__ == "__main__":
    main()
