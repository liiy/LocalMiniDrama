"""阶段 6 视听资产真理源组件包 (Stage 6 Asset Truth Package)。

提供单集视听资产提纯、实体全息建档、声学原型分配、四段式格式自愈及真理源总库维护能力。
"""
from __future__ import annotations

from app.tools.screenplay_feature_scanner import (
    ScreenplayScanResult,
    scan_screenplay_features,
)
from app.workflows.nodes.stage6.dossier_builders import (
    _build_stage2_character_dossier,
    _build_stage3_prop_dossier,
    _build_stage3_scene_dossier,
)
from app.workflows.nodes.stage6.fallback import _stage6_fallback
from app.workflows.nodes.stage6.helpers import (
    StageResult,
    _clean_name,
    _ensure_standard_asset,
    _extract_screenplay_text,
    _extract_token_from_id,
    _get_val,
    compute_asset_semantic_hash,
)
from app.workflows.nodes.stage6.node import stage6_asset_truth_node
from app.workflows.nodes.stage6.normalizer import (
    AssetEntityNormalizer,
    MorphStateMachine,
    extract_pure_physical_environment_cues,
)
from app.workflows.nodes.stage6.projectors import (
    _build_candidates_from_projected_registry,
    is_character_truly_in_screenplay,
    project_characters_for_stage6,
    project_environments_props_for_stage6,
    project_registry_index_for_stage6,
    summarize_scanner_findings,
)
from app.workflows.nodes.stage6.voice_rules import (
    TIMBRE_ARCHETYPE_POOL,
    _build_default_emotion_rules,
    _select_voice_archetype,
    _strip_dialogue_brackets,
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
]
