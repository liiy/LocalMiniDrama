"""工业级状态机时光倒流与分支派生服务 (Workflow Time Travel & Forking Service)。

基于 LangGraph 原生 `update_state` 状态分叉机制与 MySQLCheckpointer，
严格对齐《两程九阶架构方案》中 Strategy A (Checkpoint Time Travel / Forking) 规范：
1. 回溯定位 (Anchor Lookup)：快速按 stage/episode/checkpoint_id 定位历史检查点；
2. 状态覆写与分支派生 (State Update & Forking)：调用 `update_state` 注入人工干预数据，自动建立 DAG 父子关联生成新分支；
3. 级联数据失效 (Cascading Invalidation)：在 `drama_checkpoint_index` 中将旧分支后续节点标记为非活跃 (`is_current_active = 0`)；
4. 断点续跑 (Resume Execution)：从当前断点或分叉点无缝推进工作流。
"""
from __future__ import annotations

from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.event_bus import EventBus
from app.core.logger import get_logger
from app.db.session import fetch_one, session_scope
from app.platform_common import json_dumps, json_loads, now_iso
from app.schemas.script_graph_state import (
    AuditVerdict,
    GlobalDramaMasterState,
    RedBlueAuditReport,
)
from app.services.checkpoint_index_service import (
    deactivate_subsequent_checkpoints,
    get_checkpoint_by_id,
    get_latest_active_checkpoint,
    list_drama_checkpoints,
    mark_checkpoint_ready,
    record_checkpoint_index,
)
from app.workflows.adapters.drama_storage_adapter import DramaStorageAdapter
from app.workflows.industrial_master_graph import (
    build_industrial_master_graph,
    get_default_checkpointer,
    sync_checkpoint_to_index,
)
from app.workflows.two_journey_runner import _stream_graph_execution

logger = get_logger("lmd.workflow_time_travel")


def get_workflow_state_snapshot(
    drama_id: str | int,
    thread_id: str | None = None,
    checkpoint_id: str | None = None,
    checkpointer: Any = None,
) -> dict[str, Any]:
    """获取指定短剧工作流的当前状态快照与挂起信息。

    Args:
        drama_id: 短剧项目 ID
        thread_id: 会话线程 ID，默认自动定位
        checkpoint_id: 可选特定的检查点 ID，不传则取最新
        checkpointer: 可选 checkpointer 实例

    Returns:
        dict: 包含当前状态 values、待执行 next 节点、检查点元数据及是否处于人工审核等待状态
    """
    resolved_thread_id = thread_id
    resolved_checkpoint_id = checkpoint_id
    latest_index_entry = None

    try:
        with session_scope() as db:
            latest_index_entry = get_latest_active_checkpoint(db, drama_id)
            if latest_index_entry:
                if not resolved_thread_id:
                    resolved_thread_id = latest_index_entry.get("thread_id")
                if not resolved_checkpoint_id:
                    resolved_checkpoint_id = latest_index_entry.get("checkpoint_id")
    except Exception as e:
        logger.debug(f"[WorkflowStatus] 查询 drama_checkpoint_index 失败: {e}")

    resolved_thread_id = resolved_thread_id or f"drama_{drama_id}"
    cp = checkpointer or get_default_checkpointer()
    graph = build_industrial_master_graph(checkpointer=cp)

    config = {"configurable": {"thread_id": resolved_thread_id}}
    if resolved_checkpoint_id:
        config["configurable"]["checkpoint_id"] = resolved_checkpoint_id

    state_snapshot = graph.get_state(config)
    has_data = (
        state_snapshot is not None
        and state_snapshot.config is not None
        and bool(state_snapshot.config.get("configurable", {}).get("checkpoint_id"))
    )

    if not has_data and not thread_id and str(drama_id) != resolved_thread_id:
        # 回退尝试纯数字形式的 thread_id
        alt_config = {"configurable": {"thread_id": str(drama_id)}}
        alt_snapshot = graph.get_state(alt_config)
        if alt_snapshot and alt_snapshot.config and alt_snapshot.config.get("configurable", {}).get("checkpoint_id"):
            state_snapshot = alt_snapshot
            resolved_thread_id = str(drama_id)
            has_data = True

    if not has_data:
        logger.debug(f"[WorkflowStatus] 未找到状态快照: drama_id={drama_id}, thread_id={resolved_thread_id}")
        return {
            "exists": False,
            "drama_id": drama_id,
            "thread_id": resolved_thread_id,
            "values": None,
            "next_nodes": [],
            "is_waiting_review": False,
        }

    values = state_snapshot.values or {}
    if hasattr(values, "model_dump"):
        values = values.model_dump()
    elif not isinstance(values, dict):
        values = dict(values)

    next_nodes = list(state_snapshot.next or ())
    is_waiting_review = len(next_nodes) > 0
    if not is_waiting_review and latest_index_entry:
        is_waiting_review = (latest_index_entry.get("is_ready_for_next") == 0)

    current_ckpt_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")

    logger.debug(
        f"[WorkflowStatus] 获取到状态快照: drama_id={drama_id}, ckpt_id={current_ckpt_id}, "
        f"next_nodes={next_nodes}, is_waiting_review={is_waiting_review}"
    )

    return {
        "exists": True,
        "drama_id": drama_id,
        "thread_id": resolved_thread_id,
        "checkpoint_id": current_ckpt_id,
        "checkpoint_ns": state_snapshot.config.get("configurable", {}).get("checkpoint_ns", ""),
        "values": values,
        "next_nodes": next_nodes,
        "is_waiting_review": is_waiting_review,
        "metadata": state_snapshot.metadata or {},
        "created_at": state_snapshot.created_at if hasattr(state_snapshot, "created_at") else None,
    }


def time_travel_and_fork(
    drama_id: str | int,
    target_stage: str | None = None,
    target_episode: int | None = None,
    target_checkpoint_id: str | None = None,
    human_override_state: dict[str, Any] | None = None,
    as_node: str | None = None,
    run_mode: str = "two_journey",
    checkpointer: Any = None,
) -> dict[str, Any]:
    """时光倒流核心服务：回溯定位历史检查点并派生新分支 (Strategy A)。

    执行步骤：
    1. 【定位锚点】在 `drama_checkpoint_index` 中查找匹配的历史检查点；
    2. 【构建主图】基于指定 run_mode 编译主图与 checkpointer；
    3. 【分支派生】调用 `graph.update_state`，将旧检查点作为 parent，合并人工覆写数据，生成新 checkpoint_id；
    4. 【级联失效】将旧分支中该基准检查点之后的所有记录置为非活跃 (`is_current_active = 0`)；
    5. 【登记新分支】在 `drama_checkpoint_index` 中登记派生的新检查点；
    6. 【返回结果】包含新分支的 checkpoint_id 与父节点追踪信息。

    Args:
        drama_id: 短剧项目 ID
        target_stage: 目标回溯阶段 (如 "stage1", "stage2"... "stage8")
        target_episode: 目标回溯集数 (第二程分镜/音频回溯，>=1)
        target_checkpoint_id: 精确指定的历史检查点 ID (若提供则最高优先级)
        human_override_state: 人工在前端修改/填写的覆写状态字典 (如修改后的人设、大纲或分镜参数)
        as_node: 声明本次 update_state 以哪个节点的身份写入 (若不指定则自动推导)
        run_mode: 重跑执行模式 (stage_by_stage / two_journey / full_auto)
        checkpointer: 可选 checkpointer 实例

    Returns:
        dict: 派生结果详情，包含新旧 checkpoint_id、所属阶段与新分支状态
    """
    thread_id = f"drama_{drama_id}"
    cp = checkpointer or get_default_checkpointer()
    graph = build_industrial_master_graph(checkpointer=cp, run_mode=run_mode)

    with session_scope() as db:
        # 1. 定位基准检查点
        target_ckpt_entry = None
        if target_checkpoint_id:
            target_ckpt_entry = get_checkpoint_by_id(db, drama_id, target_checkpoint_id)
            if not target_ckpt_entry:
                raise ValueError(f"指定的检查点 {target_checkpoint_id} 不存在于短剧 {drama_id} 的索引记录中")
        else:
            target_ckpt_entry = get_latest_active_checkpoint(
                db, drama_id, stage=target_stage, episode_number=target_episode
            )
            if not target_ckpt_entry:
                raise ValueError(
                    f"未找到短剧 {drama_id} 在 stage={target_stage}, ep={target_episode} 的历史检查点"
                )

        anchor_checkpoint_id = target_ckpt_entry["checkpoint_id"]
        anchor_index_id = target_ckpt_entry["id"]
        anchor_stage = target_ckpt_entry["stage"]
        anchor_step_name = target_ckpt_entry["step_name"]
        thread_id = target_ckpt_entry.get("thread_id") or f"drama_{drama_id}"

        logger.info(
            f"[TimeTravel] 定位到回溯基准检查点: drama_id={drama_id}, index_id={anchor_index_id}, "
            f"stage={anchor_stage}, step={anchor_step_name}, ckpt_id={anchor_checkpoint_id}, thread_id={thread_id}"
        )

        # 2. 组装 LangGraph update_state 配置
        base_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": target_ckpt_entry.get("checkpoint_ns", ""),
                "checkpoint_id": anchor_checkpoint_id,
            }
        }

        # 3. 准备覆写载荷与脏数据清理 (根据方案 4.2 级联失效与状态机清理规范)
        override_payload = dict(human_override_state or {})
        
        # 针对第一程回溯，若之前已锁定了第一程，自动解锁以允许重新生成
        stage_num = 1
        try:
            stage_num = int(str(anchor_stage).replace("stage", ""))
        except Exception:
            pass

        if stage_num <= 5:
            override_payload["literary_journey_locked"] = False
            override_payload["journey"] = "journey_1_literary"
            override_payload["current_stage"] = stage_num

            # 级联清理状态机被污染的下游阶段数据
            if stage_num == 1:
                override_payload.setdefault("characters_engine", {})
                override_payload.setdefault("environments_and_props", {})
                override_payload.setdefault("season_outlines", {})
                override_payload.setdefault("completed_screenplays", {})
            elif stage_num == 2:
                override_payload.setdefault("environments_and_props", {})
                override_payload.setdefault("season_outlines", {})
                override_payload.setdefault("completed_screenplays", {})
            elif stage_num == 3:
                override_payload.setdefault("season_outlines", {})
                override_payload.setdefault("completed_screenplays", {})
            elif stage_num == 4:
                override_payload.setdefault("completed_screenplays", {})

        resolved_as_node = as_node or anchor_step_name or None
        if resolved_as_node and resolved_as_node not in graph.nodes:
            logger.debug(f"[TimeTravel] as_node '{resolved_as_node}' 不在主图节点中，由 LangGraph 自动推导")
            resolved_as_node = None

        logger.debug(
            f"[TimeTravel] 执行 update_state 派生新分支: base_ckpt={anchor_checkpoint_id}, "
            f"as_node={resolved_as_node}, override_keys={list(override_payload.keys())}"
        )

        # 4. 调用 LangGraph 原生 update_state 派生全新分支
        new_config = graph.update_state(
            base_config,
            values=override_payload,
            as_node=resolved_as_node,
        )

        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id", "")
        if not new_checkpoint_id:
            raise RuntimeError(f"LangGraph update_state 失败，未能生成新的 checkpoint_id")

        logger.info(
            f"[TimeTravel] 分支派生成功! 父检查点={anchor_checkpoint_id} -> 新分支检查点={new_checkpoint_id}"
        )

        # 5. 级联数据失效：将该基准点之后的旧分支检查点标记为非活跃，并级联标记业务表脏数据
        deactivated_count = deactivate_subsequent_checkpoints(db, drama_id, anchor_index_id)
        from app.services.checkpoint_index_service import cascade_invalidate_downstream_business_records
        invalidated_biz_stats = cascade_invalidate_downstream_business_records(
            db,
            drama_id,
            from_stage=stage_num + 1 if stage_num < 8 else stage_num,
            from_episode=target_ckpt_entry.get("episode_number", 0),
        )

        # 计算版本标识 (如 v2, v3...)
        existing_versions = list_drama_checkpoints(db, drama_id, stage=anchor_stage, active_only=False, limit=50)
        version_tag = f"v{len(existing_versions) + 1}"

        # 6. 在 drama_checkpoint_index 中登记派生的新检查点
        new_index_id = record_checkpoint_index(
            db=db,
            drama_id=drama_id,
            thread_id=thread_id,
            checkpoint_id=new_checkpoint_id,
            stage=anchor_stage,
            episode_number=target_ckpt_entry.get("episode_number", 0),
            wave_number=target_ckpt_entry.get("wave_number", 0),
            node_name=resolved_as_node or f"{anchor_step_name}_fork",
            step_name=f"{resolved_as_node or anchor_step_name}_fork",
            version_tag=version_tag,
            audit_verdict="FORKED_RETRY",
            is_ready_for_next=1,  # 派生修改已完成，处于就绪可推进状态
            is_current_active=1,
            checkpoint_ns=target_ckpt_entry.get("checkpoint_ns", ""),
        )

    return {
        "success": True,
        "action": "time_travel_and_fork",
        "drama_id": drama_id,
        "thread_id": thread_id,
        "parent_checkpoint_id": anchor_checkpoint_id,
        "new_checkpoint_id": new_checkpoint_id,
        "forked_checkpoint_id": new_checkpoint_id,
        "new_checkpoint_index_id": new_index_id,
        "stage": anchor_stage,
        "version_tag": version_tag,
        "deactivated_old_checkpoints": deactivated_count,
        "invalidated_biz_stats": invalidated_biz_stats,
        "status": "forked_ready",
    }


def resume_workflow(
    drama_id: str | int,
    run_mode: str = "two_journey",
    checkpointer: Any = None,
) -> dict[str, Any]:
    """从当前最新活跃检查点恢复执行工作流并流式原子落库。

    使用统一流式执行引擎 `_stream_graph_execution` 消费流式更新，
    自动触发各阶段 `DramaStorageAdapter.persist_stage*` 原子入库至业务表，
    并在执行完毕或再次触发 `interrupt_after` 挂起后，自动更新 `drama_checkpoint_index`。

    Args:
        drama_id: 短剧项目 ID
        run_mode: 运行模式 (stage_by_stage / two_journey / full_auto)
        checkpointer: 可选 checkpointer 实例

    Returns:
        dict: 执行结果与最新状态快照
    """
    int_drama_id = int(drama_id) if str(drama_id).isdigit() else 0

    with session_scope() as db:
        active_ckpt = get_latest_active_checkpoint(db, drama_id)
        thread_id = (active_ckpt.get("thread_id") if active_ckpt else None) or f"drama_{drama_id}"

        # 从数据库加载或初始化全局母状态
        try:
            state = DramaStorageAdapter.load_state(db, int_drama_id)
        except Exception:
            state = GlobalDramaMasterState(drama_id=int_drama_id)

        cp = checkpointer or get_default_checkpointer()
        graph = build_industrial_master_graph(checkpointer=cp, run_mode=run_mode)
        config = {"configurable": {"thread_id": thread_id}}

        # 从当前检查点快照水合最新字段至主状态
        snapshot = graph.get_state(config)
        if snapshot and snapshot.values:
            val_dict = (
                snapshot.values
                if isinstance(snapshot.values, dict)
                else (snapshot.values.model_dump() if hasattr(snapshot.values, "model_dump") else {})
            )
            for k, v in val_dict.items():
                if hasattr(state, k):
                    setattr(state, k, v)

        state.run_mode = run_mode

        logger.info(
            f"[WorkflowResume] 恢复工作流执行并消费流式原子落库: drama_id={drama_id}, "
            f"thread_id={thread_id}, run_mode={run_mode}"
        )

        # 统一通过 _stream_graph_execution 消费流式更新并原子落库至业务关系表
        _stream_graph_execution(
            graph=graph,
            config=config,
            state=state,
            db=db,
            drama_id=int_drama_id,
            auto_proceed_to_visual=False,
            initial_input=None,
        )

        # 同步检查点索引
        sync_checkpoint_to_index(graph, config, drama_id, db)

        # 查询当前状态机状态
        final_snapshot = graph.get_state(config)
        next_nodes = list(final_snapshot.next or ()) if final_snapshot else []
        is_paused = len(next_nodes) > 0
        current_ckpt_id = (
            final_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            if final_snapshot and final_snapshot.config
            else ""
        )
        final_values = (
            final_snapshot.values
            if isinstance(final_snapshot.values, dict)
            else (final_snapshot.values.model_dump() if hasattr(final_snapshot.values, "model_dump") else {})
        ) if final_snapshot else {}

        logger.info(
            f"[WorkflowResume] 工作流推进完成/挂起并完成原子落库: drama_id={drama_id}, ckpt_id={current_ckpt_id}, "
            f"next_nodes={next_nodes}, is_paused={is_paused}"
        )

        return {
            "success": True,
            "drama_id": drama_id,
            "thread_id": thread_id,
            "checkpoint_id": current_ckpt_id,
            "is_paused": is_paused,
            "next_nodes": next_nodes,
            "current_stage": final_values.get("current_stage", getattr(state, "current_stage", 1)),
            "journey": final_values.get("journey", getattr(state, "journey", "journey_1_literary")),
        }


def approve_human_review(
    drama_id: str | int,
    stage: int | str | None = None,
    checkpoint_id: str | None = None,
    human_feedback: str | None = None,
    human_override_state: dict[str, Any] | None = None,
    auto_resume: bool = True,
    run_mode: str = "two_journey",
    checkpointer: Any = None,
) -> dict[str, Any]:
    """阶段级人工审核放行与状态更新服务 (Stage-Level HITL Approval)。

    严格对齐《工业化状态机分层治理方案》与《两程九阶架构规范》：
    1. 彻底解决红牌阻断滞留问题：无条件通过 `graph.update_state` 注入 `latest_audit` 合格自审报告；
    2. 注入白名单豁免：在母状态 `stage_approvals` 中标记当前阶段已获人工放行，防止条件路由二次阻断；
    3. 清零防死循环计数器：重置 `stage_retry_counts` 与内存重试字典；
    4. 锚定自审节点：指定 `as_node=audit_stageX`，驱动 LangGraph 重新计算条件边，精准将 `checkpoint.next` 推进至下一阶段；
    5. 标记检查点就绪 (`is_ready_for_next = 1`) 并记录 `HUMAN_APPROVED`；
    6. 若 `auto_resume=True`，无缝触发 `resume_workflow` 向下推进执行。

    Args:
        drama_id: 短剧项目 ID
        stage: 可选指定放行阶段编号 (1~8 或 'stage1'~'stage8')，若未传则基于快照智能推断
        checkpoint_id: 可选特定检查点 ID
        human_feedback: 人工批注/审核说明
        human_override_state: 人工微调后的状态数据字典
        auto_resume: 审核通过后是否立即自动继续向下执行
        run_mode: 运行模式
        checkpointer: 可选 checkpointer 实例

    Returns:
        dict: 审核处理与推进结果
    """
    int_drama_id = int(drama_id) if str(drama_id).isdigit() else 0

    with session_scope() as db:
        # 获取最新活跃检查点
        active_ckpt = get_latest_active_checkpoint(db, drama_id)
        if not active_ckpt:
            raise ValueError(f"短剧 {drama_id} 无活跃检查点，无法执行人工审核放行")

        target_ckpt_id = checkpoint_id or active_ckpt["checkpoint_id"]
        thread_id = active_ckpt.get("thread_id") or f"drama_{drama_id}"

    cp = checkpointer or get_default_checkpointer()
    graph = build_industrial_master_graph(checkpointer=cp, run_mode=run_mode)
    config = {"configurable": {"thread_id": thread_id}}

    # 读取当前状态机母状态快照
    snapshot = graph.get_state(config)
    values = snapshot.values if snapshot and snapshot.values else {}
    if hasattr(values, "model_dump"):
        values = values.model_dump()
    elif not isinstance(values, dict):
        values = dict(values)

    # 推断当前放行阶段
    if stage is not None:
        try:
            stage_num = int(str(stage).lower().replace("stage", "").strip())
        except Exception:
            stage_num = values.get("current_stage", 1)
    else:
        stage_num = values.get("current_stage")
        if not stage_num:
            stage_str = active_ckpt.get("stage", "stage1")
            try:
                stage_num = int(str(stage_str).lower().replace("stage", "").strip())
            except Exception:
                stage_num = 1

    # 确定关联的自审节点名称
    if active_ckpt.get("step_name") == "gatekeeper":
        audit_node = "gatekeeper"
    elif stage_num <= 5:
        audit_node = f"audit_stage{stage_num}"
    else:
        audit_node = active_ckpt.get("step_name") or f"stage{stage_num}"

    if audit_node not in graph.nodes:
        fallback_node = active_ckpt.get("step_name")
        audit_node = fallback_node if fallback_node in graph.nodes else None

    logger.info(
        f"【阶段人工审批】开始处理阶段放行: drama_id={drama_id}, stage={stage_num}, "
        f"audit_node={audit_node}, ckpt_id={target_ckpt_id}, auto_resume={auto_resume}"
    )

    # 构造状态补丁
    state_patch: dict[str, Any] = dict(human_override_state or {})

    # 1. 注入白名单放行标记 (供 industrial_master_graph._route_after_audit 读取)
    existing_approvals = dict(values.get("stage_approvals") or {})
    existing_approvals[f"stage{stage_num}"] = True
    existing_approvals[f"audit_stage{stage_num}"] = True
    state_patch["stage_approvals"] = existing_approvals

    # 2. 清零重试计数器 (避免死循环判定残留)
    existing_retries = dict(values.get("stage_retry_counts") or {})
    existing_retries[f"{drama_id}_{audit_node}"] = 0
    self_nodes_map = {
        1: "stage1_ideation",
        2: "stage2_character",
        3: "stage3_environment_prop",
        4: "stage4_outline",
        5: "stage5_screenplay",
    }
    if stage_num in self_nodes_map:
        existing_retries[f"{drama_id}_{self_nodes_map[stage_num]}"] = 0
    state_patch["stage_retry_counts"] = existing_retries

    # 3. 构造通过级红蓝对抗自审报告覆盖，清除 RED_BLOCKING 阻断
    pass_audit = RedBlueAuditReport(
        verdict=AuditVerdict.BLUE_PASS,
        blue_team_compliance={"passed": True, "comment": human_feedback or "人工审核通过并放行"},
        red_team_criticism={"passed": True, "comment": "人工审核豁免红牌阻断"},
        blocking_issues=[],
        warning_suggestions=[],
    )
    state_patch["latest_audit"] = pass_audit
    if human_feedback:
        state_patch["human_feedback"] = human_feedback

    # 4. 无条件通过 update_state 注入并重新计算出边
    update_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_id": target_ckpt_id,
        }
    }
    new_config = graph.update_state(
        update_config,
        values=state_patch,
        as_node=audit_node,
    )
    new_ckpt_id = new_config.get("configurable", {}).get("checkpoint_id", target_ckpt_id)
    logger.info(
        f"【阶段人工审批】已通过 update_state 派生新检查点: drama_id={drama_id}, "
        f"stage={stage_num}, as_node={audit_node}, new_ckpt_id={new_ckpt_id}"
    )

    # 5. 标记检查点就绪与审批结论
    with session_scope() as db:
        mark_checkpoint_ready(db, drama_id, new_ckpt_id, is_ready=1, audit_verdict="HUMAN_APPROVED")

    # 6. 若开启自动推进，继续执行下一步
    if auto_resume:
        res = resume_workflow(drama_id=drama_id, run_mode=run_mode, checkpointer=cp)
        res["status"] = "approved"
        res["approved_stage"] = stage_num
        res["stage_approvals"] = existing_approvals
        return res

    return {
        "success": True,
        "status": "approved",
        "drama_id": drama_id,
        "approved_stage": stage_num,
        "checkpoint_id": new_ckpt_id,
        "is_ready_for_next": 1,
        "message": f"第 {stage_num} 阶人工审核已放行，状态已更新就绪",
        "stage_approvals": existing_approvals,
    }


def confirm_gatekeeper_and_lock(
    drama_id: str | int,
    human_feedback: str | None = None,
    run_mode: str = "two_journey",
    checkpointer: Any = None,
    auto_resume: bool = True,
    operator: str = "user",
) -> dict[str, Any]:
    """全季文学剧本定稿总门禁确认与视听工程唤醒 (Two-Journey Gatekeeper Confirmation)。

    严格对齐《工业化状态机分层治理方案》与《两程九阶架构规范》：
    1. 严格防御性门禁校验：必须确保全季第一程文学剧本（Stage 1~5）已全部完成 (current_stage >= 5)；
       若短剧尚处于 Stage 1~4，严禁越级定稿，抛出明确语义错误提示，引导使用阶段放行接口；
    2. 状态机定稿锁定：调用 update_state 将 `literary_journey_locked` 置为 True，
       锁定 `journey='journey_2_visual_audio'`，`current_stage=6`，锚定 `as_node='gatekeeper'`；
    3. 业务数据库定稿锁定：同步更新 dramas 表 `lock_status=1`，`metadata.literary_journey_locked=1`；
    4. 事件总线全息广播：发布 `FIRST_JOURNEY_LOCKED` 与 `STAGE_PROGRESS` 事件；
    5. 第二程视听工程唤醒：恢复执行进入第二程 Stage 6 资产真理层。

    Args:
        drama_id: 短剧项目 ID
        human_feedback: 主创团队对全季剧本的终审批注
        run_mode: 运行模式
        checkpointer: 可选 checkpointer 实例
        auto_resume: 锁定后是否自动恢复执行第二程 (默认 True)
        operator: 审批操作人姓名或标识

    Returns:
        dict: 定稿锁定与唤醒执行结果
    """
    int_drama_id = int(drama_id) if str(drama_id).isdigit() else 0

    with session_scope() as db:
        drama = fetch_one(
            db,
            "SELECT id, pipeline_status, lock_status, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
            {"id": int_drama_id},
        )
        if not drama:
            raise ValueError(f"短剧项目 {drama_id} 不存在")

        active_ckpt = get_latest_active_checkpoint(db, drama_id)
        if not active_ckpt:
            raise ValueError(f"短剧 {drama_id} 无活跃检查点，无法执行两程定稿总门禁确认")

        target_ckpt_id = active_ckpt["checkpoint_id"]
        thread_id = active_ckpt.get("thread_id") or f"drama_{drama_id}"

    cp = checkpointer or get_default_checkpointer()
    graph = build_industrial_master_graph(checkpointer=cp, run_mode=run_mode)
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = graph.get_state(config)
    values = snapshot.values if snapshot and snapshot.values else {}
    if hasattr(values, "model_dump"):
        values = values.model_dump()
    elif not isinstance(values, dict):
        values = dict(values)

    current_stage = values.get("current_stage", 1)

    # 防御性阶段校验：严禁在 Stage 1~4 未完成全季剧本时触发两程总门禁
    if current_stage < 5:
        logger.error(
            f"【两程总门禁拦截】短剧 [{drama_id}] 当前处于第 {current_stage} 阶，"
            f"尚未完成第一程全季文学剧本编写，拒绝执行定稿锁定！"
        )
        raise ValueError(
            f"短剧当前处于第 {current_stage} 阶，尚未完成第一程全季文学剧本编写，"
            f"不能执行全季定稿门禁确认！请使用阶段审核放行接口 (POST /resume 或 /stages/{current_stage}/approve)。"
        )

    logger.info(
        f"【两程总门禁确认】开始执行全季文学定稿锁定: drama_id={drama_id}, "
        f"current_stage={current_stage}, ckpt_id={target_ckpt_id}"
    )

    # 1. 构造母状态锁定补丁
    gate_patch = {
        "literary_journey_locked": True,
        "journey": "journey_2_visual_audio",
        "current_stage": 6,
        "current_visual_episode": 1,
        "human_feedback": human_feedback or "全季文学剧本定稿总门禁确认通过",
    }
    update_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_id": target_ckpt_id,
        }
    }
    gate_node = "gatekeeper" if "gatekeeper" in graph.nodes else None
    new_config = graph.update_state(
        update_config,
        values=gate_patch,
        as_node=gate_node,
    )
    new_ckpt_id = new_config.get("configurable", {}).get("checkpoint_id", target_ckpt_id)

    # 2. 数据库落库定稿锁定标记
    with session_scope() as db:
        meta = json_loads(drama.get("metadata") or "{}") or {}
        meta["literary_journey_locked"] = 1
        meta["gate_approved"] = True
        meta["gate_feedback"] = human_feedback
        meta["gate_reviewed_at"] = now_iso()
        db.execute(
            text("UPDATE dramas SET lock_status = 1, metadata = :metadata, updated_at = :now WHERE id = :id"),
            {"metadata": json_dumps(meta), "now": now_iso(), "id": int_drama_id},
        )
        mark_checkpoint_ready(db, drama_id, new_ckpt_id, is_ready=1, audit_verdict="HUMAN_APPROVED")
        db.commit()

    # 3. 发布第一程定稿锁定与第二程唤醒事件
    EventBus.publish_event(
        int_drama_id,
        "FIRST_JOURNEY_LOCKED",
        {
            "stage": 5,
            "journey": "journey_1_literary",
            "status": "locked",
            "message": "全季文学剧本定稿锁定生效！已通过两程定稿总门禁裁决。",
        },
    )
    EventBus.publish_event(
        int_drama_id,
        "STAGE_PROGRESS",
        {
            "stage": 6,
            "stage_name": "唤醒第二程视听分镜工程",
            "journey": "journey_2_visual_audio",
            "status": "resumed",
            "progress_pct": 50,
        },
    )

    logger.info(
        f"【两程总门禁确认】全季文学剧本已定稿锁定，唤醒第二程视听分镜工程: drama_id={drama_id}"
    )

    if not auto_resume:
        return {
            "status": "gate_confirmed",
            "drama_id": drama_id,
            "current_stage": 6,
            "literary_journey_locked": True,
            "checkpoint_id": new_ckpt_id,
            "message": "全季文学剧本定稿锁定已生效，处于就绪挂起状态",
        }

    # 4. 恢复执行进入第二程 Stage 6
    res = resume_workflow(drama_id=drama_id, run_mode=run_mode, checkpointer=cp)
    res["status"] = "gate_confirmed"
    res["literary_journey_locked"] = True
    return res
