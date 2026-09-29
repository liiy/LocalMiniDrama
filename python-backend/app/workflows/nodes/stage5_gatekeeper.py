"""【规则编号: RULE-GATEKEEPER-05】第一程文学定稿总锁与人机协同门禁节点 (Stage 5 Gatekeeper Node)。

严格遵循 SKILL.md v10.0.0 工业级标准：
第一程阶段 1~5 完成后，必须经过该门禁进行全局锁定与持久化，
只有在第一程文学定稿完全锁死后，才允许通过 route_literary_gatekeeper 路由向第二程视听分镜工程 (Stage 6~8) 切换。
"""
from __future__ import annotations

from typing import Any
import logging

from app.schemas.script_graph_state import (
    GlobalDramaMasterState,
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
    state: GlobalDramaMasterState | IndustrialDramaState | Any,
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
    # 持久化落库：优先使用传入的 db_session，若为空则自动通过 session_scope 建立会话落库
    if drama_id and drama_id > 0:
        if db_session is not None:
            try:
                DramaStorageAdapter.persist_literary_journey(db_session, state)
                logger.info(f"【第一程门禁】成功使用外部会话将第一程数据持久化至数据库 (drama_id={drama_id})")
            except Exception as e:
                logger.error(f"【第一程门禁】使用外部会话持久化第一程数据失败: {e}")
        else:
            try:
                from app.db.session import session_scope
                with session_scope() as session:
                    DramaStorageAdapter.persist_literary_journey(session, state)
                logger.info(f"【第一程门禁】通过 session_scope 自动获取会话并成功持久化第一程数据 (drama_id={drama_id})")
            except Exception as e:
                logger.error(f"【第一程门禁】通过 session_scope 持久化第一程数据失败: {e}")

        # 发布第一程总锁锁定 CQRS 读模型投影与 FIRST_JOURNEY_LOCKED 广播事件
        try:
            from app.context.short_memory_service import publish_drama_read_projection, publish_drama_event
            completed_nums = sorted(list(completed_screenplays.keys()))
            publish_drama_read_projection(int(drama_id), {
                "drama_id": int(drama_id),
                "current_stage": 6,
                "journey": "journey_2_visual",
                "lock_status": 1,
                "literary_journey_locked": True,
                "pipeline_status": "first_journey_locked",
                "completed_episodes": completed_nums,
                "total_episodes": int(total),
            })
            publish_drama_event(int(drama_id), "FIRST_JOURNEY_LOCKED", {
                "drama_id": int(drama_id),
                "current_stage": 6,
                "journey": "journey_2_visual",
                "status": "locked",
                "lock_status": 1,
                "total_episodes": int(total),
                "completed_screenplays": len(completed_nums),
                "message": "第一程文学剧本全季创作定稿完成，已执行总锁锁定，准备放行第二程视听工程！",
            })
            logger.info("【第一程门禁】成功发布第一程总锁 CQRS 读模型投影与 FIRST_JOURNEY_LOCKED 事件 (drama_id=%s)", drama_id)
        except Exception as e:
            logger.warning("【第一程门禁】发布 CQRS 读模型或 FIRST_JOURNEY_LOCKED 事件异常: %s", e)

    return {
        "literary_journey_locked": True,
        "journey": "journey_2_visual",
        "current_stage": 6,
        "current_visual_episode": 1,
    }
