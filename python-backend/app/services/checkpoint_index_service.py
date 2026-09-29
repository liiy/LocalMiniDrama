"""短剧业务阶段检查点索引服务 (Checkpoint Index Service)。

提供对 `drama_checkpoint_index` 表的增删改查业务操作，包括：
1. 记录状态机检查点与业务阶段、集数、波次的映射关系；
2. 查询指定短剧、阶段、单集的最新活跃检查点；
3. 时光倒流 (Time Travel) 时的分支失效标记 (is_current_active = 0)；
4. 标记检查点就绪状态 (is_ready_for_next = 1)。
"""
from __future__ import annotations

from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one, session_scope

logger = get_logger("lmd.checkpoint_index")


def record_checkpoint_index(
    db: Session,
    drama_id: str | int,
    thread_id: str,
    checkpoint_id: str,
    stage: str,
    episode_number: int = 0,
    wave_number: int = 0,
    step_name: str = "",
    node_name: str = "",
    journey: str = "",
    audit_verdict: str | None = None,
    version_tag: str = "v1",
    is_ready_for_next: int = 0,
    is_current_active: int = 1,
    checkpoint_ns: str = "",
    **kwargs: Any,
) -> int:
    """记录检查点与业务阶段的索引映射。

    Args:
        db: 数据库会话
        drama_id: 短剧项目 ID
        thread_id: 工作流线程隔离标识
        checkpoint_id: 检查点唯一版本标识
        stage: 业务阶段标识 (如 stage1, stage2... stage8 或 1~8)
        episode_number: 集数 (0 表示第一程全剧级，>=1 表示第二程单集)
        wave_number: 第5阶批次序号 (0 表示非第5阶，>=1 表示波次)
        step_name: 当前节点名称 (如 audit_stage1, gatekeeper 等)
        node_name: 节点名称 (若为空则取 step_name)
        journey: 所属程 (journey_1_literary / journey_2_visual)，若为空自动推断
        audit_verdict: 自审结论 (BLUE_PASS / RED_BLOCKING / HUMAN_APPROVED)
        version_tag: 重跑版本标识 (v1, v2, v3...)
        is_ready_for_next: 是否已就绪可执行下一阶段/单集/波次 (1=就绪, 0=未就绪/待审核)
        is_current_active: 是否为当前最新活跃分支检查点 (1=活跃, 0=已废弃)
        checkpoint_ns: 命名空间/子图标识

    Returns:
        int: 插入记录的主键 ID
    """
    now = timestamp()
    resolved_node = node_name or step_name
    resolved_step = step_name or node_name

    # 自动推导 journey
    if not journey:
        st_str = str(stage).lower()
        if "6" in st_str or "7" in st_str or "8" in st_str:
            journey = "journey_2_visual"
        else:
            journey = "journey_1_literary"

    sql = """
    INSERT INTO drama_checkpoint_index (
        drama_id, journey, thread_id, checkpoint_ns, checkpoint_id,
        stage, episode_number, wave_number, node_name, step_name,
        is_ready_for_next, audit_verdict, version_tag,
        is_current_active, created_at, updated_at
    ) VALUES (
        :drama_id, :journey, :thread_id, :checkpoint_ns, :checkpoint_id,
        :stage, :episode_number, :wave_number, :node_name, :step_name,
        :is_ready_for_next, :audit_verdict, :version_tag,
        :is_current_active, :created_at, :updated_at
    )
    """
    params = {
        "drama_id": str(drama_id),
        "journey": journey,
        "thread_id": thread_id,
        "checkpoint_ns": checkpoint_ns,
        "checkpoint_id": checkpoint_id,
        "stage": str(stage),
        "episode_number": int(episode_number),
        "wave_number": int(wave_number),
        "node_name": resolved_node,
        "step_name": resolved_step,
        "is_ready_for_next": int(is_ready_for_next),
        "audit_verdict": audit_verdict,
        "version_tag": version_tag,
        "is_current_active": int(is_current_active),
        "created_at": now,
        "updated_at": now,
    }
    result = execute(db, sql, params)
    inserted_id = getattr(result, "lastrowid", 0)
    logger.debug(
        f"[CheckpointIndex] 记录检查点索引完成: id={inserted_id}, drama_id={drama_id}, "
        f"journey={journey}, stage={stage}, ep={episode_number}, wave={wave_number}, "
        f"ckpt_id={checkpoint_id}, node={resolved_node}, ready={is_ready_for_next}, "
        f"verdict={audit_verdict}, version={version_tag}, active={is_current_active}"
    )
    return inserted_id


def get_latest_active_checkpoint(
    db: Session,
    drama_id: str | int,
    stage: str | None = None,
    episode_number: int | None = None,
) -> dict[str, Any] | None:
    """获取指定短剧最新的活跃检查点索引。

    Args:
        db: 数据库会话
        drama_id: 短剧项目 ID
        stage: 可选按阶段过滤
        episode_number: 可选按集数过滤

    Returns:
        dict | None: 检查点索引记录
    """
    conditions = ["drama_id = :drama_id", "is_current_active = 1"]
    params: dict[str, Any] = {"drama_id": str(drama_id)}

    if stage:
        conditions.append("stage = :stage")
        params["stage"] = stage
    if episode_number is not None:
        conditions.append("episode_number = :episode_number")
        params["episode_number"] = int(episode_number)

    where_clause = " AND ".join(conditions)
    sql = f"""
    SELECT * FROM drama_checkpoint_index
    WHERE {where_clause}
    ORDER BY id DESC
    LIMIT 1
    """
    row = fetch_one(db, sql, params)
    if row:
        logger.debug(
            f"[CheckpointIndex] 获取到最新活跃检查点: drama_id={drama_id}, "
            f"stage={row.get('stage')}, ep={row.get('episode_number')}, ckpt_id={row.get('checkpoint_id')}"
        )
    else:
        logger.debug(f"[CheckpointIndex] 未找到活跃检查点: drama_id={drama_id}, stage={stage}, ep={episode_number}")
    return row


def list_drama_checkpoints(
    db: Session,
    drama_id: str | int,
    stage: str | None = None,
    episode_number: int | None = None,
    active_only: bool = True,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询短剧的检查点索引列表。

    Args:
        db: 数据库会话
        drama_id: 短剧项目 ID
        stage: 可选按阶段过滤
        episode_number: 可选按集数过滤
        active_only: 是否仅查询当前活跃分支的检查点
        limit: 最大返回数量

    Returns:
        list[dict]: 检查点索引记录列表
    """
    conditions = ["drama_id = :drama_id"]
    params: dict[str, Any] = {"drama_id": str(drama_id), "limit": limit}

    if active_only:
        conditions.append("is_current_active = 1")
    if stage:
        conditions.append("stage = :stage")
        params["stage"] = stage
    if episode_number is not None:
        conditions.append("episode_number = :episode_number")
        params["episode_number"] = int(episode_number)

    where_clause = " AND ".join(conditions)
    sql = f"""
    SELECT * FROM drama_checkpoint_index
    WHERE {where_clause}
    ORDER BY id DESC
    LIMIT :limit
    """
    rows = fetch_all(db, sql, params)
    logger.debug(f"[CheckpointIndex] 查询检查点列表: drama_id={drama_id}, count={len(rows)}")
    return rows


def get_checkpoint_by_id(
    db: Session,
    drama_id: str | int,
    checkpoint_id: str,
) -> dict[str, Any] | None:
    """根据 checkpoint_id 获取检查点索引详情。"""
    sql = """
    SELECT * FROM drama_checkpoint_index
    WHERE drama_id = :drama_id AND checkpoint_id = :checkpoint_id
    LIMIT 1
    """
    return fetch_one(db, sql, {"drama_id": str(drama_id), "checkpoint_id": checkpoint_id})


def mark_checkpoint_ready(
    db: Session,
    drama_id: str | int,
    checkpoint_id: str,
    is_ready: int = 1,
    audit_verdict: str | None = None,
) -> bool:
    """更新检查点的就绪/审核状态 (is_ready_for_next) 与自审/审批结论 (audit_verdict)。

    Args:
        db: 数据库会话
        drama_id: 短剧项目 ID
        checkpoint_id: 检查点 ID
        is_ready: 1=就绪/审核通过, 0=未就绪/待审核
        audit_verdict: 可选更新审批/自审结论 (如 BLUE_PASS, HUMAN_APPROVED)

    Returns:
        bool: 是否更新成功
    """
    now = timestamp()
    sql = """
    UPDATE drama_checkpoint_index
    SET is_ready_for_next = :is_ready,
        audit_verdict = CASE WHEN :audit_verdict IS NOT NULL THEN :audit_verdict ELSE audit_verdict END,
        updated_at = :updated_at
    WHERE drama_id = :drama_id AND checkpoint_id = :checkpoint_id
    """
    res = execute(db, sql, {
        "drama_id": str(drama_id),
        "checkpoint_id": checkpoint_id,
        "is_ready": int(is_ready),
        "audit_verdict": audit_verdict,
        "updated_at": now,
    })
    rowcount = getattr(res, "rowcount", 0)
    logger.debug(
        f"[CheckpointIndex] 更新检查点就绪状态: drama_id={drama_id}, ckpt_id={checkpoint_id}, "
        f"is_ready={is_ready}, verdict={audit_verdict}, affected_rows={rowcount}"
    )
    return rowcount > 0


def deactivate_subsequent_checkpoints(
    db: Session,
    drama_id: str | int,
    from_checkpoint_index_id: int,
) -> int:
    """在时光倒流 (Time Travel) 产生新分支时，将该检查点之后的所有旧分支检查点置为非活跃 (is_current_active = 0)。

    Args:
        db: 数据库会话
        drama_id: 短剧项目 ID
        from_checkpoint_index_id: 目标回溯检查点在 drama_checkpoint_index 中的自增 id

    Returns:
        int: 废弃的旧检查点数量
    """
    now = timestamp()
    sql = """
    UPDATE drama_checkpoint_index
    SET is_current_active = 0, updated_at = :updated_at
    WHERE drama_id = :drama_id AND id > :from_id AND is_current_active = 1
    """
    res = execute(db, sql, {
        "drama_id": str(drama_id),
        "from_id": int(from_checkpoint_index_id),
        "updated_at": now,
    })
    affected = getattr(res, "rowcount", 0)
    logger.info(
        f"[CheckpointIndex] 时光倒流分支切换: drama_id={drama_id}, "
        f"基准 index_id={from_checkpoint_index_id}, 已将 {affected} 个后续旧检查点标记为非活跃"
    )
    return affected


class InvalidationStats(dict):
    """级联失效行数统计字典，同时支持整数比较运算 (如 stats >= 4)。"""

    @property
    def total(self) -> int:
        return sum(v for v in self.values() if isinstance(v, (int, float)))

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.total >= other
        return super().__ge__(other)

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.total > other
        return super().__gt__(other)

    def __le__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.total <= other
        return super().__le__(other)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.total < other
        return super().__lt__(other)

    def __int__(self) -> int:
        return self.total


def cascade_invalidate_downstream_business_records(
    db: Session,
    drama_id: str | int,
    from_stage: int | str,
    from_episode: int | None = 0,
) -> InvalidationStats:
    """级联失效防御：将目标重跑阶段/集数之后的历史业务数据库实体标记为 DIRTY_INVALIDATED。

    根据方案第四节：
    短剧创作具有强烈的上下文链式依赖（角色改变 -> 场景道具改变 -> 大纲动机改变 -> 台词剧本改变）。
    在业务数据库中，将该剧目下被影响的 episodes / storyboards 等数据状态批量更新为 DIRTY_INVALIDATED。

    Args:
        db: 数据库会话
        drama_id: 短剧 ID
        from_stage: 重跑的目标阶段 (2~8，或 'stage1' 等字符串)
        from_episode: 重跑的目标集数 (默认为 0)

    Returns:
        InvalidationStats: 影响的行数统计字典
    """
    now = timestamp()
    stats = InvalidationStats({"episodes": 0, "storyboards": 0})

    try:
        from_stage_num = int(str(from_stage).lower().replace("stage", ""))
    except Exception:
        from_stage_num = 1

    from_ep_num = int(from_episode or 0)

    try:
        # 1. 标记分集剧本失效 (若重跑 stage <= 5 则标记第一程剧本失效)
        if from_stage_num <= 5:
            sql_ep = """
            UPDATE episodes
            SET status = 'DIRTY_INVALIDATED', updated_at = :updated_at
            WHERE drama_id = :drama_id AND status != 'DIRTY_INVALIDATED'
            """
            ep_params: dict[str, Any] = {"drama_id": str(drama_id), "updated_at": now}
            if from_ep_num > 0:
                sql_ep += " AND episode_number >= :from_ep"
                ep_params["from_ep"] = from_ep_num
            res_ep = execute(db, sql_ep, ep_params)
            stats["episodes"] = getattr(res_ep, "rowcount", 0)

        # 2. 标记视听分镜失效 (若重跑 stage <= 7)
        if from_stage_num <= 7:
            sql_sb = """
            UPDATE storyboards
            SET status = 'DIRTY_INVALIDATED', updated_at = :updated_at
            WHERE episode_id IN (
                SELECT id FROM episodes WHERE drama_id = :drama_id
            ) AND status != 'DIRTY_INVALIDATED'
            """
            res_sb = execute(db, sql_sb, {"drama_id": str(drama_id), "updated_at": now})
            stats["storyboards"] = getattr(res_sb, "rowcount", 0)

        logger.info(
            f"[CheckpointIndex] 业务数据级联失效处理完成: drama_id={drama_id}, "
            f"from_stage={from_stage_num}, from_ep={from_ep_num}, stats={stats}"
        )
    except Exception as e:
        logger.warning(f"[CheckpointIndex] 业务数据级联失效标记出现非致命异常 (可能实体表为空或尚未落库): {e}")

    return stats
