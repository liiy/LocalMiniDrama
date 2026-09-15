"""第一程文学定稿总锁与人机协同门禁节点 (Stage 5 Gatekeeper Node)。

严格遵循 SKILL.md：
第一程阶段 1~5 完成后，必须经过该门禁进行全局锁定与持久化，
只有在第一程文学定稿完全锁死后，才允许向第二程视听分镜工程 (Stage 6~8) 切换。
"""
from __future__ import annotations

from typing import Any
import logging

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.adapters.drama_storage_adapter import DramaStorageAdapter

logger = logging.getLogger("lmd.gatekeeper")


def stage5_literary_gatekeeper_node(state: IndustrialDramaMasterState, db_session: Any = None) -> dict[str, Any]:
    """第一程定稿门禁节点：验证全季完整度、加锁并持久化到数据库。"""
    total = state.total_episodes or 5
    completed_count = len(state.completed_screenplays or {})

    if completed_count < total:
        logger.warning(
            f"Literary gatekeeper triggered before all episodes completed: {completed_count}/{total}"
        )
        return {
            "literary_journey_locked": False,
            "journey": "journey_1_literary",
            "current_stage": 5,
        }

    # 执行第一程锁定
    logger.info(
        f"All {total} episodes literary screenplays finalized. Locking Journey 1 and switching to Journey 2."
    )

    # 如果传入了数据库 Session，执行物理落库
    if db_session is not None and state.drama_id > 0:
        try:
            DramaStorageAdapter.persist_literary_journey(db_session, state)
            logger.info(f"Successfully persisted Journey 1 data to SQLite for drama {state.drama_id}")
        except Exception as e:
            logger.error(f"Failed to persist Journey 1 to DB: {e}")

    return {
        "literary_journey_locked": True,
        "journey": "journey_2_visual",
        "current_stage": 6,
        "current_visual_episode": 1,
    }
