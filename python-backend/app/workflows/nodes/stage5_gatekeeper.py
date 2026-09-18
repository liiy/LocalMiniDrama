"""【规则编号: RULE-GATEKEEPER-05】第一程文学定稿总锁与人机协同门禁节点 (Stage 5 Gatekeeper Node)。

严格遵循 SKILL.md v10.0.0 工业级标准：
第一程阶段 1~5 完成后，必须经过该门禁进行全局锁定与持久化，
只有在第一程文学定稿完全锁死后，才允许通过 route_literary_gatekeeper 路由向第二程视听分镜工程 (Stage 6~8) 切换。
"""
from __future__ import annotations

from typing import Any
import logging

from app.schemas.script_graph_state import (
    IndustrialDramaMasterState,
    IndustrialDramaState,
)
from app.workflows.adapters.drama_storage_adapter import DramaStorageAdapter

logger = logging.getLogger("lmd.gatekeeper")


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """安全读取字典或对象字段值。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def stage5_literary_gatekeeper_node(
    state: Any,
    db_session: Any = None,
) -> dict[str, Any]:
    """【规则编号: RULE-GATEKEEPER-05】第一程定稿门禁节点：验证全季完整度、加锁并持久化到数据库。
    
    遵循公共硬性约束：
    - 入参为标准 State（支持 IndustrialDramaState 契约），返回增量字典；
    - 纯业务节点，不含下游流转判断（分支全部由 route_literary_gatekeeper 路由函数裁决）。
    """
    total = _get_val(state, "total_episodes", None) or _get_val(state, "target_episodes", 5)
    completed_screenplays = _get_val(state, "completed_screenplays", {}) or {}
    completed_count = len(completed_screenplays)

    logger.debug(f"[Literary Gatekeeper Node] Checking progress: {completed_count}/{total} screenplays completed.")

    if completed_count < total:
        logger.warning(
            f"[Literary Gatekeeper Node] Triggered before all episodes completed: {completed_count}/{total}. Refusing to lock."
        )
        return {
            "literary_journey_locked": False,
            "journey": "journey_1_literary",
            "current_stage": 5,
        }

    # 执行第一程锁定
    logger.info(
        f"[Literary Gatekeeper Node] All {total} episodes literary screenplays finalized. "
        f"Locking Journey 1 and preparing state for Journey 2."
    )

    drama_id = _get_val(state, "drama_id", 0)
    # 如果传入了数据库 Session，执行物理落库
    if db_session is not None and drama_id and drama_id > 0:
        try:
            DramaStorageAdapter.persist_literary_journey(db_session, state)
            logger.info(f"[Literary Gatekeeper Node] Successfully persisted Journey 1 data to SQLite for drama {drama_id}")
        except Exception as e:
            logger.error(f"[Literary Gatekeeper Node] Failed to persist Journey 1 to DB: {e}")

    return {
        "literary_journey_locked": True,
        "journey": "journey_2_visual",
        "current_stage": 6,
        "current_visual_episode": 1,
    }
