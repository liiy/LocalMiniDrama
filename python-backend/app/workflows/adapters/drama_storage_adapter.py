"""短剧创作工坊两程九阶工业化状态存储适配器 (Drama Storage Adapter) 外观门面。

本模块采用外观模式 (Facade Pattern)，统一聚合与转发 Stage 1 ~ Stage 8 独立子适配器及加载器。
保持 100% 接口与函数向后兼容。
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    StoryboardShot,
)
from app.workflows.adapters.stage_adapters.common import (
    _safe_json_loads,
    _ensure_valid_json_str,
    _dump_or_dict,
    _flatten_asset_collection,
    _get_table_columns,
    sync_stage_memories_to_vector_db,
    persist_audit_report,
    fetch_one,
    fetch_all,
    publish_episode_read_projection,
    publish_drama_read_projection,
    publish_drama_event,
    set_short_memories,
    get_short_memories,
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


def _resolve_session_and_args_helper(cls_or_self: Any, *args: Any, **kwargs: Any) -> tuple[Session, list[Any], dict[str, Any]]:
    """统一解析 Session 对象与剩余参数的辅助函数。"""
    arg_list = list(args)
    kw = dict(kwargs)
    db = None

    if hasattr(cls_or_self, "execute") and hasattr(cls_or_self, "commit"):
        db = cls_or_self
    elif getattr(cls_or_self, "db", None) is not None and hasattr(cls_or_self.db, "execute"):
        db = cls_or_self.db
    elif "db" in kw:
        db = kw.pop("db")
    elif "session" in kw:
        db = kw.pop("session")
    elif arg_list and hasattr(arg_list[0], "execute") and hasattr(arg_list[0], "commit"):
        db = arg_list.pop(0)

    # 如果 cls_or_self 既不是 Adapter 也不是 Session，说明是首个业务参数（如 drama_id）
    if not isinstance(cls_or_self, DramaStorageAdapter) and not (hasattr(cls_or_self, "execute") and hasattr(cls_or_self, "commit")):
        arg_list.insert(0, cls_or_self)

    if db is None:
        raise ValueError(f"DramaStorageAdapter 无法识别有效的数据库 Session: cls_or_self={cls_or_self}, args={args}")

    return db, arg_list, kw

class DramaStorageAdapter:
    """两程九阶存储适配器统一门面类，同时支持实例方法与类/静态方法调用。"""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def _resolve_session_and_args(self, *args: Any, **kwargs: Any) -> tuple[Session, list[Any], dict[str, Any]]:
        return _resolve_session_and_args_helper(self, *args, **kwargs)

    @classmethod
    def _extract_drama_id_and_state(cls, args: list[Any], kwargs: dict[str, Any]) -> tuple[int, Any]:
        drama_id = kwargs.get("drama_id")
        state = kwargs.get("state")
        
        if len(args) == 1:
            if hasattr(args[0], "drama_id"):
                state = args[0]
                drama_id = state.drama_id
            elif isinstance(args[0], int):
                drama_id = args[0]
        elif len(args) >= 2:
            if isinstance(args[0], int):
                drama_id = args[0]
                state = args[1]
            elif hasattr(args[0], "drama_id"):
                state = args[0]
                drama_id = state.drama_id

        if drama_id is None and state and hasattr(state, "drama_id"):
            drama_id = state.drama_id

        if drama_id is None or state is None:
            raise ValueError(f"无法解析 drama_id 或 state 参数 (args={args}, kwargs={kwargs})")

        return int(drama_id), state

    def persist_stage1(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage1(session, drama_id, state)

    def persist_stage2(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage2(session, drama_id, state)

    def persist_stage3(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage3(session, drama_id, state)

    def persist_stage4(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage4(session, drama_id, state)

    def persist_stage5(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage5(session, drama_id, state)

    def persist_stage6(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        episode_num = remaining_kwargs.get("episode_num")
        if len(remaining_args) >= 3 and isinstance(remaining_args[2], int):
            episode_num = remaining_args.pop(2)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage6(session, drama_id, state, episode_num)

    def persist_stage7(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        episode_num = remaining_kwargs.get("episode_num")
        if len(remaining_args) >= 3 and isinstance(remaining_args[2], int):
            episode_num = remaining_args.pop(2)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage7(session, drama_id, state, episode_num)

    def persist_stage8(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        episode_num = remaining_kwargs.get("episode_num")
        if len(remaining_args) >= 3 and isinstance(remaining_args[2], int):
            episode_num = remaining_args.pop(2)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_stage8(session, drama_id, state, episode_num)

    def persist_literary_journey(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_first_journey_state(session, drama_id, state)

    def persist_visual_journey(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_second_journey_state(session, drama_id, state)

    def persist_first_journey_state(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_first_journey_state(session, drama_id, state)

    def persist_second_journey_state(cls_or_self, *args: Any, **kwargs: Any) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id, state = DramaStorageAdapter._extract_drama_id_and_state(remaining_args, remaining_kwargs)
        persist_second_journey_state(session, drama_id, state)

    def persist_episode_visual_package(
        cls_or_self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_num = remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        manifest = remaining_kwargs.get("manifest") or (remaining_args[2] if len(remaining_args) > 2 else {})
        storyboards = remaining_kwargs.get("storyboards") or (remaining_args[3] if len(remaining_args) > 3 else None)
        srt_export = remaining_kwargs.get("srt_export") or (remaining_args[4] if len(remaining_args) > 4 else "")
        audio_mastering = remaining_kwargs.get("audio_mastering") or (remaining_args[5] if len(remaining_args) > 5 else None)

        if isinstance(manifest, dict) and storyboards is None:
            pkg = manifest
            m_obj = EpisodeResourceManifest.model_validate(pkg.get("manifest", {}))
            sb_list = pkg.get("storyboards", [])
            srt_str = pkg.get("srt_export", "")
            am_dict = pkg.get("audio_mastering", {})
            persist_episode_visual_package(session, drama_id, episode_num, m_obj, sb_list, srt_str, am_dict)
        else:
            persist_episode_visual_package(session, drama_id, episode_num, manifest, storyboards or [], srt_export, audio_mastering)

    def load_state(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

    def load_master_state_from_db(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        """从数据库全量加载全局文学状态（load_state 别名）。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

    def load_first_journey_state(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        """加载第一程文学故事工程状态。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_first_journey_state(session, int(drama_id))

    def load_global_master_state(cls_or_self, *args: Any, **kwargs: Any) -> GlobalDramaMasterState:
        """加载全局文学母状态。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        return load_master_state_from_db(session, int(drama_id))

    def load_episode_visual_package(cls_or_self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """加载单集视听工程包。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_num = remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        return load_episode_visual_package(session, int(drama_id), int(episode_num))

    def load_visual_package(cls_or_self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """加载单集视听工程包（load_episode_visual_package 别名）。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_num = remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        return load_episode_visual_package(session, int(drama_id), int(episode_num))

    def load_episode_substate_slice(cls_or_self, *args: Any, **kwargs: Any) -> EpisodeScopedSubState:
        """【懒水合】从数据库毫秒级加载单集独立执行切片。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id") or (remaining_args[0] if remaining_args else 0)
        episode_number = remaining_kwargs.get("episode_number") or remaining_kwargs.get("episode_num") or (remaining_args[1] if len(remaining_args) > 1 else 1)
        return load_episode_substate_slice(session, int(drama_id), int(episode_number))

    def persist_episode_substate_slice(cls_or_self, *args: Any, **kwargs: Any) -> None:
        """【原子切片持久化】持久化单集独立执行产物并刷新 Redis 只读投影。"""
        session, remaining_args, remaining_kwargs = _resolve_session_and_args_helper(cls_or_self, *args, **kwargs)
        drama_id = remaining_kwargs.get("drama_id")
        substate = remaining_kwargs.get("substate")
        if len(remaining_args) >= 2:
            drama_id = remaining_args[0]
            substate = remaining_args[1]
        elif len(remaining_args) == 1:
            if hasattr(remaining_args[0], "drama_id"):
                substate = remaining_args[0]
                drama_id = substate.drama_id
        if drama_id is None or substate is None:
            raise ValueError(f"无法解析 drama_id 或 substate 参数 (args={args}, kwargs={kwargs})")
        persist_episode_substate_slice(session, int(drama_id), substate)

