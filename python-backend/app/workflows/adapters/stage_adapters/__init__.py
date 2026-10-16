"""Stage adapters subpackage aggregating modular storage adapters."""

from app.workflows.adapters.stage_adapters.common import (
    _safe_json_loads,
    _ensure_valid_json_str,
    _dump_or_dict,
    _flatten_asset_collection,
    _get_table_columns,
    sync_stage_memories_to_vector_db,
    persist_audit_report,
)
from app.workflows.adapters.stage_adapters.stage1_adapter import persist_stage1
from app.workflows.adapters.stage_adapters.stage2_adapter import persist_stage2
from app.workflows.adapters.stage_adapters.stage3_adapter import persist_stage3
from app.workflows.adapters.stage_adapters.stage4_adapter import persist_stage4
from app.workflows.adapters.stage_adapters.stage5_adapter import persist_stage5
from app.workflows.adapters.stage_adapters.stage6_adapter import (
    clean_character_name,
    extract_character_tokens,
    find_canonical_entity,
    parse_character_view_type,
    extract_natural_appearance,
    synthesize_character_literary_defaults,
    synthesize_voice_prompt,
    persist_stage6,
)
from app.workflows.adapters.stage_adapters.stage7_adapter import (
    _normalize_asset_lookup_token,
    _extract_core_asset_prefixes,
    _load_stage6_asset_lookup_maps,
    _resolve_asset_from_map,
    _cascade_delete_episode_storyboards,
    _persist_episode_storyboards_3tables,
    _rehydrate_episode_storyboard_shots,
    persist_stage7,
)
from app.workflows.adapters.stage_adapters.stage8_adapter import persist_stage8
from app.workflows.adapters.stage_adapters.journey_loader_adapter import (
    persist_first_journey_state,
    persist_second_journey_state,
    persist_episode_visual_package,
    load_master_state_from_db,
    load_first_journey_state,
    load_episode_visual_package,
    load_episode_substate_slice,
    persist_episode_substate_slice,
)

__all__ = [
    "_safe_json_loads",
    "_ensure_valid_json_str",
    "_dump_or_dict",
    "_flatten_asset_collection",
    "_get_table_columns",
    "sync_stage_memories_to_vector_db",
    "persist_audit_report",
    "persist_stage1",
    "persist_stage2",
    "persist_stage3",
    "persist_stage4",
    "persist_stage5",
    "clean_character_name",
    "extract_character_tokens",
    "find_canonical_entity",
    "parse_character_view_type",
    "extract_natural_appearance",
    "synthesize_character_literary_defaults",
    "synthesize_voice_prompt",
    "persist_stage6",
    "_normalize_asset_lookup_token",
    "_extract_core_asset_prefixes",
    "_load_stage6_asset_lookup_maps",
    "_resolve_asset_from_map",
    "_cascade_delete_episode_storyboards",
    "_persist_episode_storyboards_3tables",
    "_rehydrate_episode_storyboard_shots",
    "persist_stage7",
    "persist_stage8",
    "persist_first_journey_state",
    "persist_second_journey_state",
    "persist_episode_visual_package",
    "load_master_state_from_db",
    "load_first_journey_state",
    "load_episode_visual_package",
    "load_episode_substate_slice",
    "persist_episode_substate_slice",
]
