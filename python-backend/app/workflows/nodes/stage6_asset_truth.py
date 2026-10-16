"""阶段 6：第二程资产准备与真理源校验节点外观门面 (Stage 6 Asset Truth Facade)。

本模块为阶段 6 (Stage 6) 视听资产真理源组件的统一外观门面。
已重构并解耦至 `app.workflows.nodes.stage6` 子包，包括以下职责子模块：
- `helpers.py`: 资产语义指纹计算、对象解构与四段式自愈校验守卫；
- `voice_rules.py`: 防撞声学原型池、试音词清洗与戏剧声学情绪偏移矩阵；
- `dossier_builders.py`: 分集增量角色、场景做旧图层与道具破坏态全息档案构建器；
- `normalizer.py`: 实体多级漏斗归一化、别名消歧与物理形态演化状态机；
- `projectors.py`: 逆向扫描算子摘要、角色在场判定与上游契约模型投影器；
- `fallback.py`: 离线/异常时 100% 章节三标准规约确定性资产引单合成工厂；
- `node.py`: 阶段 6 完整业务调度与全剧视听资产真理源注册表更新主节点。

【兼容性保证】
全量导出原单体文件暴露的 25 个公共函数与数据结构，100% 保持原有签名与行为。
"""
from __future__ import annotations

from app.tools.screenplay_feature_scanner import (
    ScreenplayScanResult,
    scan_screenplay_features,
)
from app.workflows.utils.llm_bridge import call_llm_json
from app.workflows.nodes.stage6 import (
    TIMBRE_ARCHETYPE_POOL,
    AssetEntityNormalizer,
    MorphStateMachine,
    StageResult,
    _build_candidates_from_projected_registry,
    _build_default_emotion_rules,
    _build_stage2_character_dossier,
    _build_stage3_prop_dossier,
    _build_stage3_scene_dossier,
    _clean_name,
    _ensure_standard_asset,
    _extract_screenplay_text,
    _extract_token_from_id,
    _get_val,
    _select_voice_archetype,
    _stage6_fallback,
    _strip_dialogue_brackets,
    compute_asset_semantic_hash,
    extract_pure_physical_environment_cues,
    is_character_truly_in_screenplay,
    project_characters_for_stage6,
    project_environments_props_for_stage6,
    project_registry_index_for_stage6,
    stage6_asset_truth_node,
    summarize_scanner_findings,
)

__all__ = [
    "compute_asset_semantic_hash",
    "StageResult",
    "_get_val",
    "_extract_token_from_id",
    "_extract_screenplay_text",
    "_strip_dialogue_brackets",
    "TIMBRE_ARCHETYPE_POOL",
    "_build_default_emotion_rules",
    "_select_voice_archetype",
    "_build_stage2_character_dossier",
    "_build_stage3_scene_dossier",
    "_build_stage3_prop_dossier",
    "extract_pure_physical_environment_cues",
    "AssetEntityNormalizer",
    "MorphStateMachine",
    "summarize_scanner_findings",
    "is_character_truly_in_screenplay",
    "project_characters_for_stage6",
    "project_environments_props_for_stage6",
    "project_registry_index_for_stage6",
    "_build_candidates_from_projected_registry",
    "_stage6_fallback",
    "_clean_name",
    "_ensure_standard_asset",
    "stage6_asset_truth_node",
    "scan_screenplay_features",
    "ScreenplayScanResult",
    "call_llm_json",
]
