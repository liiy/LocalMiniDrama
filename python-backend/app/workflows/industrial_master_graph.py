"""短剧两程九阶全息工业化 LangGraph 主图与分层编排器 (Industrial Master & Layered Graphs)。

严格对齐 SKILL.md 两程九阶 SOP 规范与状态机分层解耦架构：
【第一程：文学故事工程主图 (Stages 1~5 + Gatekeeper)】
  - 契约状态：GlobalDramaMasterState (<50KB 轻量级文学大纲与全剧全局状态)
  - 编排函数：build_literary_master_graph
  Stage 1: 题材立项与双轨禁令 (stage1_ideation) -> Audit 1 (红蓝自审)
  Stage 2: 角色引擎与心理四元组 (stage2_character) -> Audit 2 (红蓝自审)
  Stage 3: 空间三层做旧与物证拟音 (stage3_environment_prop) -> Audit 3 (红蓝自审)
  Stage 4: 全季大纲与音频动机 (stage4_outline) -> Audit 4 (红蓝自审)
  Stage 5: Mini-Arc 文学剧本波次生成 (stage5_screenplay) -> Audit 5 (红蓝自审)
  Gatekeeper: 第一程定稿总锁与人机门禁 (stage5_gatekeeper) -> END

【第二程：单集视听工程子图 (Stages 6~8)】
  - 契约状态：EpisodeScopedSubState (<100KB 单集切片隔离状态)
  - 编排函数：build_episode_visual_subgraph (别名 build_episode_subgraph)
  Stage 6: 单集资产提纯与真理源校验 (stage6_asset_truth)
  Stage 7: 视听导演双模式分镜与毫秒级 SRT (stage7_storyboard_srt)
  Stage 8: 全息声学混音工程与响度避让 (stage8_audio_mastering) -> END

【全生命周期贯通兼容主图 (Stages 1~8 统合兼容)】
  - 编排函数：build_industrial_master_graph (采用 GlobalDramaMasterState)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Generator, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.schemas.script_graph_state import (
    AuditVerdict,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
)
from app.workflows.checkpointers.mysql_saver import MySQLCheckpointSaver
from app.workflows.nodes.stage1_ideation import stage1_ideation_node
from app.workflows.nodes.stage2_character import stage2_character_node
from app.workflows.nodes.stage3_environment_prop import stage3_environment_prop_node
from app.workflows.nodes.stage4_outline import stage4_outline_node
from app.workflows.nodes.stage5_gatekeeper import stage5_literary_gatekeeper_node
from app.workflows.nodes.stage5_screenplay import stage5_screenplay_node
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node
from app.workflows.nodes.stage8_audio_mastering import stage8_audio_mastering_node
from app.workflows.routers.audit_router import (
    episode_increment_node,
    make_stage_audit_node,
    pipeline_complete_node,
    route_episode_loop,
    stage1_audit_node,
    stage2_audit_node,
    stage3_audit_node,
    stage4_audit_node,
    stage5_audit_node,
)

logger = logging.getLogger("lmd.master_graph")

# 全局内存降级 Checkpointer 单例缓存
_FALLBACK_MEMORY_CHECKPOINTER = MemorySaver()
_GLOBAL_MYSQL_CHECKPOINTER: MySQLCheckpointSaver | None = None


def get_default_checkpointer() -> BaseCheckpointSaver:
    """获取生产级检查点保存器实例。
    
    自动检测并初始化 workflow_checkpoints 相关表结构。
    若 MySQL 不可用（如本地单测或未配置 MySQL），优雅降级为 MemorySaver。
    """
    global _GLOBAL_MYSQL_CHECKPOINTER
    if _GLOBAL_MYSQL_CHECKPOINTER is not None:
        return _GLOBAL_MYSQL_CHECKPOINTER
    try:
        saver = MySQLCheckpointSaver()
        saver.setup()
        _GLOBAL_MYSQL_CHECKPOINTER = saver
        logger.info("【MasterGraph】生产级 MySQLCheckpointSaver 已就绪")
        return _GLOBAL_MYSQL_CHECKPOINTER
    except Exception as e:
        logger.warning(f"【MasterGraph】MySQLCheckpointSaver 不可用，优雅降级为 MemorySaver: {e}")
        return _FALLBACK_MEMORY_CHECKPOINTER


# 全局默认 Checkpointer (向后兼容历史引用)
GLOBAL_GRAPH_CHECKPOINTER = get_default_checkpointer()

# 节点自愈防死循环重试计数器字典 (内存兜底缓存)
_RETRY_COUNTERS: dict[str, int] = {}


def _route_after_audit(next_stage_node: str, self_stage_node: str):
    """构建各阶段审计节点 (audit_stage1~4) 后的条件路由判定。
    
    三级决策流转逻辑：
    1. 人工审批白名单优先：若检测到人工已对该阶段执行放行 (stage_approvals[stage]=True)，无条件推进；
    2. 自动质检合格放行：若最新质检报告为 GREEN_PASS 或 BLUE_PASS，正常推进；
    3. 红牌阻断与自愈重跑：若为 RED_BLOCKING，在允许重试次数内 (<=2次) 回退本阶段重跑自愈；超限则触发熔断推进。
    """
    def route_fn(state: GlobalDramaMasterState | Any) -> str:
        drama_id = getattr(state, "drama_id", "default")
        counter_key = f"{drama_id}_{self_stage_node}"

        # 1. 优先级一：人工审批放行白名单判断
        stage_approvals = getattr(state, "stage_approvals", {}) or {}
        # 提取阶段标识，如 stage1_ideation -> stage1
        stage_prefix = self_stage_node.split("_")[0] if "_" in self_stage_node else self_stage_node
        is_human_approved = any(
            stage_approvals.get(k) is True
            for k in [self_stage_node, stage_prefix, f"audit_{stage_prefix}"]
        )
        if is_human_approved:
            _RETRY_COUNTERS[counter_key] = 0
            logger.info(
                f"【工作流路由】短剧 [{drama_id}] 阶段 [{self_stage_node}] 命中人工审核放行白名单，"
                f"跳过质检阻断，直接推进至下一节点 [{next_stage_node}]"
            )
            return next_stage_node

        # 2. 获取最新质检报告结论
        audit = getattr(state, "latest_audit", None)
        raw_verdict = getattr(audit, "verdict", None) if audit else None
        verdict_str = raw_verdict.value if hasattr(raw_verdict, "value") else str(raw_verdict or "")

        # 3. 优先级二：自动质检合格判定 (绿牌/蓝牌通过)
        if raw_verdict in [AuditVerdict.GREEN_PASS, AuditVerdict.GREEN_APPROVED, AuditVerdict.BLUE_PASS, AuditVerdict.HUMAN_APPROVED] or verdict_str.upper() in ["GREEN_PASS", "GREEN_APPROVED", "BLUE_PASS", "HUMAN_APPROVED"]:
            _RETRY_COUNTERS[counter_key] = 0
            logger.info(
                f"【工作流路由】短剧 [{drama_id}] 阶段 [{self_stage_node}] 质检结论合格 ({verdict_str})，"
                f"正常推进至下一节点 [{next_stage_node}]"
            )
            return next_stage_node

        # 4. 优先级三：红牌阻断 (RED_BLOCKING) 与自愈重试
        # 优先读取持久化状态字典中的重试计数，兼容内存计数器
        persistent_retries = getattr(state, "stage_retry_counts", {}) or {}
        current_retries = persistent_retries.get(counter_key, _RETRY_COUNTERS.get(counter_key, 0))

        if raw_verdict == AuditVerdict.RED_BLOCKING or verdict_str.upper() == "RED_BLOCKING":
            if current_retries < 2:
                next_retry = current_retries + 1
                _RETRY_COUNTERS[counter_key] = next_retry
                if hasattr(state, "stage_retry_counts") and isinstance(state.stage_retry_counts, dict):
                    state.stage_retry_counts[counter_key] = next_retry

                logger.warning(
                    f"【工作流路由】短剧 [{drama_id}] 阶段 [{self_stage_node}] 质检红牌阻断 (RED_BLOCKING)，"
                    f"触发大模型自动重跑自愈机制 (第 {next_retry}/2 次)，回退至 [{self_stage_node}]"
                )
                return self_stage_node
            else:
                logger.error(
                    f"【工作流路由】短剧 [{drama_id}] 阶段 [{self_stage_node}] 自愈重试达到上限 (2/2)，"
                    f"触发防死循环兜底熔断，强制推进至下一节点 [{next_stage_node}]"
                )
                _RETRY_COUNTERS[counter_key] = 0
                if hasattr(state, "stage_retry_counts") and isinstance(state.stage_retry_counts, dict):
                    state.stage_retry_counts[counter_key] = 0
                return next_stage_node

        _RETRY_COUNTERS[counter_key] = 0
        logger.info(f"【工作流路由】短剧 [{drama_id}] 阶段 [{self_stage_node}] 默认流转至 [{next_stage_node}]")
        return next_stage_node

    return route_fn


def _route_after_stage5_audit(state: GlobalDramaMasterState | Any) -> str:
    """阶段 5 剧本自审后的条件路由判定：波次推进循环 vs 定稿总门禁。"""
    total = getattr(state, "total_episodes", None) or getattr(state, "target_episodes", 5) or 5
    completed = len(getattr(state, "completed_screenplays", {}) or {})

    drama_id = getattr(state, "drama_id", "default")
    counter_key = f"{drama_id}_stage5_screenplay"

    # 1. 优先检查人工审批白名单放行
    stage_approvals = getattr(state, "stage_approvals", {}) or {}
    is_human_approved = any(
        stage_approvals.get(k) is True
        for k in ["stage5", "stage5_screenplay", "audit_stage5"]
    )

    audit = getattr(state, "latest_audit", None)
    raw_verdict = getattr(audit, "verdict", None) if audit else None
    verdict_str = raw_verdict.value if hasattr(raw_verdict, "value") else str(raw_verdict or "")

    # 2. 若未获得人工放行且质检出现红牌阻断，执行局部重试
    if not is_human_approved and (raw_verdict == AuditVerdict.RED_BLOCKING or verdict_str.upper() == "RED_BLOCKING"):
        current_retries = _RETRY_COUNTERS.get(counter_key, 0)
        if current_retries < 2:
            _RETRY_COUNTERS[counter_key] = current_retries + 1
            logger.warning(
                f"【工作流路由】短剧 [{drama_id}] 阶段五剧本质检红牌阻断，重试当前波次 (第 {current_retries + 1}/2 次)"
            )
            return "stage5_screenplay"
        else:
            logger.error(f"【工作流路由】短剧 [{drama_id}] 阶段五重试超限，强制继续向下判定波次")

    _RETRY_COUNTERS[counter_key] = 0

    # 3. 检查全季分集是否全部完结
    if completed < total:
        logger.info(f"【工作流路由】短剧 [{drama_id}] 阶段五微弧波次推进中: 已完成 {completed}/{total} 集，继续生成下一波次")
        return "stage5_screenplay"

    logger.info(f"【工作流路由】短剧 [{drama_id}] 全季共 {total} 集文学剧本全部完成，推进至两程总门禁 [gatekeeper]")
    return "gatekeeper"


def _route_entry_node(state: GlobalDramaMasterState | Any) -> str:
    """根据全局状态判断主图入口：直接启动第一程文学立项 vs 断点恢复进入第二程视听分镜。"""
    journey = getattr(state, "journey", "")
    locked = getattr(state, "literary_journey_locked", False)
    if journey == "journey_2_visual_audio" or locked:
        logger.info("Entry router: Literary journey already locked, entering Stage 6 Asset Truth directly.")
        return "stage6_asset_truth"
    return "stage1_ideation"


def get_interrupt_after_nodes(run_mode: str = "two_journey") -> list[str] | None:
    """根据执行模式计算 interrupt_after 节点清单。

    - stage_by_stage (单步精细化模式):
      每阶自审后中断 + 第5阶每波 Mini-Arc 后中断 + 第一程定稿门禁中断 + 第二程每集 Stage 8 完成后中断。
    - two_journey (双程总控模式 - 推荐默认模式):
      第一程文学工程自动化执行直至 gatekeeper 门禁中断人工验收定稿；
      第二程单集视听工程推进，每集 Stage 8 完成后中断人工验收单集分镜与声音。
    - full_auto (全自动极速模式):
      不设任何中断点，全流程自动自审自愈直通完结。
    """
    if run_mode == "stage_by_stage":
        return [
            "audit_stage1",
            "audit_stage2",
            "audit_stage3",
            "audit_stage4",
            "audit_stage5",
            "gatekeeper",
            "stage8_audio_mastering",
        ]
    elif run_mode == "two_journey":
        return [
            "gatekeeper",
            "stage8_audio_mastering",
        ]
    elif run_mode == "full_auto":
        return None
    else:
        logger.warning(f"【MasterGraph】未知 run_mode '{run_mode}'，回退至 'two_journey'")
        return ["gatekeeper", "stage8_audio_mastering"]


def get_literary_interrupt_after_nodes(run_mode: str = "two_journey") -> list[str] | None:
    """根据执行模式计算第一程文学主图专属 interrupt_after 节点清单。"""
    if run_mode == "stage_by_stage":
        return [
            "audit_stage1",
            "audit_stage2",
            "audit_stage3",
            "audit_stage4",
            "audit_stage5",
            "gatekeeper",
        ]
    elif run_mode == "two_journey":
        return ["gatekeeper"]
    elif run_mode == "full_auto":
        return None
    else:
        return ["gatekeeper"]


def sync_checkpoint_to_index(
    graph: Any,
    config: dict[str, Any],
    drama_id: str | int,
    db: Any = None,
) -> int | None:
    """在状态机执行完毕或中断暂停后，将当前状态机最新检查点同步索引至 drama_checkpoint_index 表。
    
    提取当前阶段 stage、集数 episode_number、波次 wave_number、节点名称 step_name 与就绪状态。
    """
    try:
        state_snapshot = graph.get_state(config)
        if not state_snapshot or not state_snapshot.config:
            logger.debug(f"[MasterGraph] 未获取到状态机快照，跳过检查点索引同步: drama_id={drama_id}")
            return None

        thread_id = state_snapshot.config.get("configurable", {}).get("thread_id", f"drama_{drama_id}")
        checkpoint_ns = state_snapshot.config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
        if not checkpoint_id:
            logger.debug(f"[MasterGraph] 快照中 checkpoint_id 为空，跳过索引: drama_id={drama_id}")
            return None

        values = state_snapshot.values or {}
        if hasattr(values, "model_dump"):
            values = values.model_dump()
        elif not isinstance(values, dict):
            values = dict(values)

        current_stage_num = values.get("current_stage", 1)
        stage = f"stage{current_stage_num}"
        episode_number = values.get("current_episode_number", values.get("current_visual_episode", 0))

        # 第5阶波次计算 (根据已完成剧本数)
        completed_screenplays = values.get("completed_screenplays") or {}
        wave_number = len(completed_screenplays) if current_stage_num == 5 else 0

        # 当前执行/完成节点名称 (从 writes 获取实际节点名，避免取到 'loop')
        meta = state_snapshot.metadata or {}
        writes = meta.get("writes") or {}
        if isinstance(writes, dict) and writes:
            step_name = list(writes.keys())[0]
        else:
            step_name = meta.get("source", "")

        # 挂起判定：若 state_snapshot.next 非空，说明触发了 interrupt_after 等待人工审核，置为 0；否则置为 1
        is_paused = bool(state_snapshot.next)
        is_ready_for_next = 0 if is_paused else 1

        journey = "journey_1_literary" if current_stage_num <= 5 else "journey_2_visual"
        audit_verdict = "BLUE_PASS" if (step_name.startswith("audit_") or step_name == "gatekeeper") else None

        logger.debug(
            f"[MasterGraph] 同步检查点索引: drama_id={drama_id}, journey={journey}, stage={stage}, "
            f"ep={episode_number}, wave={wave_number}, node={step_name}, ckpt_id={checkpoint_id}, "
            f"is_ready={is_ready_for_next}, verdict={audit_verdict}, is_paused={is_paused}"
        )

        from app.services.checkpoint_index_service import record_checkpoint_index
        if db is not None:
            return record_checkpoint_index(
                db=db,
                drama_id=drama_id,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                stage=stage,
                episode_number=episode_number,
                wave_number=wave_number,
                step_name=step_name,
                node_name=step_name,
                journey=journey,
                audit_verdict=audit_verdict,
                is_ready_for_next=is_ready_for_next,
                checkpoint_ns=checkpoint_ns,
            )
        else:
            from app.db.session import session_scope
            with session_scope() as session:
                return record_checkpoint_index(
                    db=session,
                    drama_id=drama_id,
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    stage=stage,
                    episode_number=episode_number,
                    wave_number=wave_number,
                    step_name=step_name,
                    node_name=step_name,
                    journey=journey,
                    audit_verdict=audit_verdict,
                    is_ready_for_next=is_ready_for_next,
                    checkpoint_ns=checkpoint_ns,
                )
    except Exception as e:
        logger.warning(f"[MasterGraph] 同步检查点索引跳过或失败 (非关键路径): {e}")
        return None


# =========================================================================
# 1. 第一程：文学故事工程主图 (Literary Master Graph)
# =========================================================================

def build_literary_master_graph(
    checkpointer: Any = None,
    run_mode: str = "two_journey",
    interrupt_after: list[str] | None = None,
):
    """【第一程文学主图】编排执行全季短剧文学故事工程 (Stages 1~5 + Gatekeeper)。

    输入/状态：GlobalDramaMasterState（<50KB 轻量级文学大纲与全剧全局状态）
    流转流程：
      START -> stage1_ideation -> audit_stage1
            -> stage2_character -> audit_stage2
            -> stage3_environment_prop -> audit_stage3
            -> stage4_outline -> audit_stage4
            -> stage5_screenplay -> audit_stage5 (Mini-Arc 波次循环)
            -> gatekeeper -> END
    
    Args:
        checkpointer: 检查点保存器 (默认使用 get_default_checkpointer())
        run_mode: 控制模式 (stage_by_stage / two_journey / full_auto)
        interrupt_after: 自定义中断节点清单
    """
    workflow = StateGraph(GlobalDramaMasterState)

    # 注册第一程节点
    workflow.add_node("stage1_ideation", stage1_ideation_node)
    workflow.add_node("audit_stage1", stage1_audit_node)

    workflow.add_node("stage2_character", stage2_character_node)
    workflow.add_node("audit_stage2", stage2_audit_node)

    workflow.add_node("stage3_environment_prop", stage3_environment_prop_node)
    workflow.add_node("audit_stage3", stage3_audit_node)

    workflow.add_node("stage4_outline", stage4_outline_node)
    workflow.add_node("audit_stage4", stage4_audit_node)

    workflow.add_node("stage5_screenplay", stage5_screenplay_node)
    workflow.add_node("audit_stage5", stage5_audit_node)

    workflow.add_node("gatekeeper", stage5_literary_gatekeeper_node)

    # 编排第一程边与条件自审
    workflow.add_edge(START, "stage1_ideation")
    workflow.add_edge("stage1_ideation", "audit_stage1")
    workflow.add_conditional_edges(
        "audit_stage1",
        _route_after_audit("stage2_character", "stage1_ideation"),
    )

    workflow.add_edge("stage2_character", "audit_stage2")
    workflow.add_conditional_edges(
        "audit_stage2",
        _route_after_audit("stage3_environment_prop", "stage2_character"),
    )

    workflow.add_edge("stage3_environment_prop", "audit_stage3")
    workflow.add_conditional_edges(
        "audit_stage3",
        _route_after_audit("stage4_outline", "stage3_environment_prop"),
    )

    workflow.add_edge("stage4_outline", "audit_stage4")
    workflow.add_conditional_edges(
        "audit_stage4",
        _route_after_audit("stage5_screenplay", "stage4_outline"),
    )

    workflow.add_edge("stage5_screenplay", "audit_stage5")
    workflow.add_conditional_edges(
        "audit_stage5",
        _route_after_stage5_audit,
    )

    workflow.add_edge("gatekeeper", END)

    if interrupt_after is None and run_mode is not None:
        interrupt_after = get_literary_interrupt_after_nodes(run_mode)

    cp = checkpointer if checkpointer is not None else get_default_checkpointer()
    logger.debug(
        f"[LiteraryMasterGraph] 编译文学主图: run_mode={run_mode}, interrupt_after={interrupt_after}"
    )
    if interrupt_after:
        return workflow.compile(checkpointer=cp, interrupt_after=interrupt_after)
    return workflow.compile(checkpointer=cp)


def run_literary_master_pipeline(
    initial_state: GlobalDramaMasterState | dict[str, Any] | None = None,
    thread_id: str | None = None,
    drama_id: str | int | None = None,
    checkpointer: Any = None,
    run_mode: str = "two_journey",
) -> GlobalDramaMasterState:
    """同步运行第一程文学主图工作流。"""
    resolved_drama_id = drama_id
    if initial_state is not None:
        if hasattr(initial_state, "drama_id"):
            resolved_drama_id = resolved_drama_id or getattr(initial_state, "drama_id")
            resolved_run_mode = getattr(initial_state, "run_mode", run_mode) or run_mode
        elif isinstance(initial_state, dict):
            resolved_drama_id = resolved_drama_id or initial_state.get("drama_id")
            resolved_run_mode = initial_state.get("run_mode") or run_mode
        else:
            resolved_run_mode = run_mode
    else:
        resolved_run_mode = run_mode

    resolved_thread_id = thread_id or f"drama_{resolved_drama_id}_literary"
    logger.info(
        f"[LiteraryMasterGraph] 开始执行文学主图: drama_id={resolved_drama_id}, "
        f"thread_id={resolved_thread_id}, run_mode={resolved_run_mode}"
    )

    graph = build_literary_master_graph(checkpointer=checkpointer, run_mode=resolved_run_mode)
    config = {"configurable": {"thread_id": resolved_thread_id}}

    final_state_dict = graph.invoke(initial_state, config=config)

    if resolved_drama_id:
        sync_checkpoint_to_index(graph, config, resolved_drama_id)

    return GlobalDramaMasterState.model_validate(final_state_dict)


def stream_literary_master_pipeline(
    initial_state: GlobalDramaMasterState | dict[str, Any] | None = None,
    thread_id: str | None = None,
    drama_id: str | int | None = None,
    checkpointer: Any = None,
    run_mode: str = "two_journey",
) -> Generator[dict[str, Any], None, None]:
    """流式运行第一程文学主图工作流，yield 每个节点的执行事件与产出状态。"""
    resolved_drama_id = drama_id
    if initial_state is not None:
        if hasattr(initial_state, "drama_id"):
            resolved_drama_id = resolved_drama_id or getattr(initial_state, "drama_id")
            resolved_run_mode = getattr(initial_state, "run_mode", run_mode) or run_mode
        elif isinstance(initial_state, dict):
            resolved_drama_id = resolved_drama_id or initial_state.get("drama_id")
            resolved_run_mode = initial_state.get("run_mode") or run_mode
        else:
            resolved_run_mode = run_mode
    else:
        resolved_run_mode = run_mode

    resolved_thread_id = thread_id or f"drama_{resolved_drama_id}_literary"
    logger.info(
        f"[LiteraryMasterGraph] 开始流式执行文学主图: drama_id={resolved_drama_id}, "
        f"thread_id={resolved_thread_id}, run_mode={resolved_run_mode}"
    )

    graph = build_literary_master_graph(checkpointer=checkpointer, run_mode=resolved_run_mode)
    config = {"configurable": {"thread_id": resolved_thread_id}}

    for chunk in graph.stream(initial_state, config=config, stream_mode="updates"):
        yield chunk

    if resolved_drama_id:
        sync_checkpoint_to_index(graph, config, resolved_drama_id)


# =========================================================================
# 2. 第二程：单集视听工程子图 (Episode Visual Subgraph)
# =========================================================================

def build_episode_visual_subgraph(
    checkpointer: Any = None,
    interrupt_after: list[str] | None = None,
):
    """【第二程单集视听工程子图】针对单集 EpisodeScopedSubState 进行轻量级编排执行。

    流转流程：
    START -> stage6_asset_truth -> stage7_storyboard_srt -> stage8_audio_mastering -> END
    输入/输出：轻量级 EpisodeScopedSubState（<100KB），彻底消除全剧巨石状态膨胀。
    """
    subgraph = StateGraph(EpisodeScopedSubState)

    subgraph.add_node("stage6_asset_truth", stage6_asset_truth_node)
    subgraph.add_node("stage7_storyboard_srt", stage7_storyboard_srt_node)
    subgraph.add_node("stage8_audio_mastering", stage8_audio_mastering_node)

    subgraph.add_edge(START, "stage6_asset_truth")
    subgraph.add_edge("stage6_asset_truth", "stage7_storyboard_srt")
    subgraph.add_edge("stage7_storyboard_srt", "stage8_audio_mastering")
    subgraph.add_edge("stage8_audio_mastering", END)

    cp = checkpointer if checkpointer is not None else get_default_checkpointer()
    if interrupt_after:
        return subgraph.compile(checkpointer=cp, interrupt_after=interrupt_after)
    return subgraph.compile(checkpointer=cp)


# 别名保持兼容
build_episode_subgraph = build_episode_visual_subgraph


def run_episode_subgraph(
    substate: EpisodeScopedSubState | dict[str, Any],
    thread_id: str | None = None,
    checkpointer: Any = None,
    config: dict[str, Any] | None = None,
) -> EpisodeScopedSubState:
    """运行单集视听工程子图并返回完成的 EpisodeScopedSubState。"""
    subgraph = build_episode_visual_subgraph(checkpointer=checkpointer)
    if isinstance(substate, dict):
        substate = EpisodeScopedSubState.model_validate(substate)

    ep_num = getattr(substate, "episode_number", 1)
    drama_id = getattr(substate, "drama_id", "default")
    resolved_thread_id = thread_id or f"drama_{drama_id}_ep_{ep_num}"
    invoke_config = config or {"configurable": {"thread_id": resolved_thread_id}}

    result = subgraph.invoke(substate, config=invoke_config)
    return EpisodeScopedSubState.model_validate(result)


# =========================================================================
# 3. 两程九阶全生命周期主图 (Industrial Master Graph - 迁移至 GlobalDramaMasterState)
# =========================================================================

def build_industrial_master_graph(
    checkpointer: Any = None,
    run_mode: str = "two_journey",
    interrupt_after: list[str] | None = None,
):
    """构建两程九阶工业全息图编排。
    
    内部基于解耦后的 GlobalDramaMasterState，向下兼容全流程执行。
    
    Args:
        checkpointer: 检查点保存器 (默认使用 get_default_checkpointer())
        run_mode: 控制模式 (stage_by_stage / two_journey / full_auto)
        interrupt_after: 自定义中断节点清单 (若显式传入则覆盖 run_mode 默认配置)
    """
    workflow = StateGraph(GlobalDramaMasterState)

    # 1. 注册各阶节点
    workflow.add_node("stage1_ideation", stage1_ideation_node)
    workflow.add_node("audit_stage1", stage1_audit_node)

    workflow.add_node("stage2_character", stage2_character_node)
    workflow.add_node("audit_stage2", stage2_audit_node)

    workflow.add_node("stage3_environment_prop", stage3_environment_prop_node)
    workflow.add_node("audit_stage3", stage3_audit_node)

    workflow.add_node("stage4_outline", stage4_outline_node)
    workflow.add_node("audit_stage4", stage4_audit_node)

    workflow.add_node("stage5_screenplay", stage5_screenplay_node)
    workflow.add_node("audit_stage5", stage5_audit_node)

    workflow.add_node("gatekeeper", stage5_literary_gatekeeper_node)

    workflow.add_node("stage6_asset_truth", stage6_asset_truth_node)
    workflow.add_node("stage7_storyboard_srt", stage7_storyboard_srt_node)
    workflow.add_node("stage8_audio_mastering", stage8_audio_mastering_node)
    workflow.add_node("episode_increment", episode_increment_node)
    workflow.add_node("pipeline_complete", pipeline_complete_node)

    # 2. 编排边与条件边（入口支持基于锁定状态智能分流）
    workflow.add_conditional_edges(START, _route_entry_node)
    workflow.add_edge("stage1_ideation", "audit_stage1")
    workflow.add_conditional_edges(
        "audit_stage1",
        _route_after_audit("stage2_character", "stage1_ideation"),
    )

    workflow.add_edge("stage2_character", "audit_stage2")
    workflow.add_conditional_edges(
        "audit_stage2",
        _route_after_audit("stage3_environment_prop", "stage2_character"),
    )

    workflow.add_edge("stage3_environment_prop", "audit_stage3")
    workflow.add_conditional_edges(
        "audit_stage3",
        _route_after_audit("stage4_outline", "stage3_environment_prop"),
    )

    workflow.add_edge("stage4_outline", "audit_stage4")
    workflow.add_conditional_edges(
        "audit_stage4",
        _route_after_audit("stage5_screenplay", "stage4_outline"),
    )

    workflow.add_edge("stage5_screenplay", "audit_stage5")
    workflow.add_conditional_edges(
        "audit_stage5",
        _route_after_stage5_audit,
    )

    workflow.add_edge("gatekeeper", "stage6_asset_truth")
    workflow.add_edge("stage6_asset_truth", "stage7_storyboard_srt")
    workflow.add_edge("stage7_storyboard_srt", "stage8_audio_mastering")
    workflow.add_conditional_edges(
        "stage8_audio_mastering",
        route_episode_loop,
        {
            "next_episode": "episode_increment",
            "complete_all": "pipeline_complete",
            "error_terminate": END,
        },
    )
    workflow.add_edge("episode_increment", "stage6_asset_truth")
    workflow.add_edge("pipeline_complete", END)

    # 计算中断节点配置
    if interrupt_after is None and run_mode is not None:
        interrupt_after = get_interrupt_after_nodes(run_mode)

    cp = checkpointer if checkpointer is not None else get_default_checkpointer()
    logger.debug(
        f"[MasterGraph] 编译主图: run_mode={run_mode}, interrupt_after={interrupt_after}, "
        f"checkpointer={type(cp).__name__}"
    )
    if interrupt_after:
        return workflow.compile(checkpointer=cp, interrupt_after=interrupt_after)
    return workflow.compile(checkpointer=cp)


def run_industrial_master_pipeline(
    initial_state: GlobalDramaMasterState | dict[str, Any] | None = None,
    thread_id: str | None = None,
    drama_id: str | int | None = None,
    checkpointer: Any = None,
    run_mode: str | None = None,
    interrupt_after: list[str] | None = None,
) -> GlobalDramaMasterState:
    """同步运行全流程两程九阶工作流。
    
    支持冷启动 (传入 initial_state) 或从最新检查点无缝恢复续跑 (initial_state 为 None)。
    执行完毕或触发中断挂起后，自动将最新检查点同步索引至 drama_checkpoint_index。
    """
    resolved_drama_id = drama_id
    resolved_run_mode = run_mode
    if resolved_run_mode is None:
        if initial_state is not None:
            if hasattr(initial_state, "model_fields_set") and "run_mode" in initial_state.model_fields_set:
                resolved_run_mode = getattr(initial_state, "run_mode")
            elif isinstance(initial_state, dict) and "run_mode" in initial_state:
                resolved_run_mode = initial_state["run_mode"]
            else:
                resolved_run_mode = "full_auto"
        else:
            resolved_run_mode = "full_auto"

    if initial_state is not None:
        if hasattr(initial_state, "drama_id"):
            resolved_drama_id = resolved_drama_id or getattr(initial_state, "drama_id")
        elif isinstance(initial_state, dict):
            resolved_drama_id = resolved_drama_id or initial_state.get("drama_id")

    resolved_thread_id = thread_id or f"drama_{resolved_drama_id}"
    logger.info(
        f"[MasterGraph] 开始执行主图管线: drama_id={resolved_drama_id}, "
        f"thread_id={resolved_thread_id}, run_mode={resolved_run_mode}, is_resume={initial_state is None}"
    )

    graph = build_industrial_master_graph(
        checkpointer=checkpointer,
        run_mode=resolved_run_mode,
        interrupt_after=interrupt_after,
    )
    config = {"configurable": {"thread_id": resolved_thread_id}}

    # 当 initial_state 为 None 时，invoke(None, config) 触发从最新检查点续跑
    final_state_dict = graph.invoke(initial_state, config=config)

    # 自动同步检查点索引
    if resolved_drama_id:
        sync_checkpoint_to_index(graph, config, resolved_drama_id)

    return GlobalDramaMasterState.model_validate(final_state_dict)


def stream_industrial_master_pipeline(
    initial_state: GlobalDramaMasterState | dict[str, Any] | None = None,
    thread_id: str | None = None,
    drama_id: str | int | None = None,
    checkpointer: Any = None,
    run_mode: str | None = None,
    interrupt_after: list[str] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """流式运行两程九阶工作流，yield 每个节点的执行事件与产出状态。
    
    支持冷启动或断点恢复续跑，完成后自动同步检查点索引。
    """
    resolved_drama_id = drama_id
    resolved_run_mode = run_mode
    if resolved_run_mode is None:
        if initial_state is not None:
            if hasattr(initial_state, "model_fields_set") and "run_mode" in initial_state.model_fields_set:
                resolved_run_mode = getattr(initial_state, "run_mode")
            elif isinstance(initial_state, dict) and "run_mode" in initial_state:
                resolved_run_mode = initial_state["run_mode"]
            else:
                resolved_run_mode = "full_auto"
        else:
            resolved_run_mode = "full_auto"

    if initial_state is not None:
        if hasattr(initial_state, "drama_id"):
            resolved_drama_id = resolved_drama_id or getattr(initial_state, "drama_id")
        elif isinstance(initial_state, dict):
            resolved_drama_id = resolved_drama_id or initial_state.get("drama_id")

    resolved_thread_id = thread_id or f"drama_{resolved_drama_id}"
    logger.info(
        f"[MasterGraph] 开始流式执行主图管线: drama_id={resolved_drama_id}, "
        f"thread_id={resolved_thread_id}, run_mode={resolved_run_mode}, is_resume={initial_state is None}"
    )

    graph = build_industrial_master_graph(
        checkpointer=checkpointer,
        run_mode=resolved_run_mode,
        interrupt_after=interrupt_after,
    )
    config = {"configurable": {"thread_id": resolved_thread_id}}

    for chunk in graph.stream(initial_state, config=config, stream_mode="updates"):
        yield chunk

    # 流式完成后自动同步检查点索引
    if resolved_drama_id:
        sync_checkpoint_to_index(graph, config, resolved_drama_id)


def run_episode_subgraph(
    substate: EpisodeScopedSubState,
    thread_id: str | None = None,
    checkpointer: Any = None,
) -> EpisodeScopedSubState:
    """同步运行单集视听工程子图 (Stage 6~8)。"""
    graph = build_episode_subgraph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id or f"drama_{substate.drama_id}_ep_{substate.episode_number}"}}
    result_dict = graph.invoke(substate, config=config)
    return EpisodeScopedSubState.model_validate(result_dict)


def stream_episode_subgraph(
    substate: EpisodeScopedSubState,
    thread_id: str | None = None,
    checkpointer: Any = None,
) -> Generator[dict[str, Any], None, None]:
    """流式运行单集视听工程子图，yield 节点增量更新。"""
    graph = build_episode_subgraph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id or f"drama_{substate.drama_id}_ep_{substate.episode_number}"}}
    for chunk in graph.stream(substate, config=config, stream_mode="updates"):
        yield chunk
