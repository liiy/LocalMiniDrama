"""短剧两程九阶全息工业化 LangGraph 主图 (Industrial Master Graph)。

严格对齐 SKILL.md 两程九阶 SOP 规范：
【第一程：文学故事工程 (Stages 1~5)】
  Stage 1: 题材立项与双轨禁令 (stage1_ideation)
    -> Audit 1 (红蓝自审)
  Stage 2: 角色引擎与心理四元组 (stage2_character)
    -> Audit 2 (红蓝自审)
  Stage 3: 空间三层做旧与物证拟音 (stage3_environment_prop)
    -> Audit 3 (红蓝自审)
  Stage 4: 全季大纲与音频动机 (stage4_outline)
    -> Audit 4 (红蓝自审)
  Stage 5: Mini-Arc 文学剧本波次生成 (stage5_screenplay)
    -> Audit 5 (红蓝自审)
  Gatekeeper: 第一程定稿总锁与人机门禁 (stage5_gatekeeper)

【第二程：视听分镜工程 (Stages 6~8)】
  Stage 6: 单集资产提纯与真理源校验 (stage6_asset_truth)
  Stage 7: 视听导演双模式分镜与毫秒级 SRT (stage7_storyboard_srt)
  Stage 8: 全息声学混音工程与响度避让 (stage8_audio_mastering)
    -> 集数循环判定：未完则跳回 Stage 6 下一集，全完则流转至 END。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Generator, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaMasterState,
)
from app.workflows.nodes.stage1_ideation import stage1_ideation_node
from app.workflows.nodes.stage2_character import stage2_character_node
from app.workflows.nodes.stage3_environment_prop import stage3_environment_prop_node
from app.workflows.nodes.stage4_outline import stage4_outline_node
from app.workflows.nodes.stage5_gatekeeper import stage5_literary_gatekeeper_node
from app.workflows.nodes.stage5_screenplay import stage5_screenplay_node
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node
from app.workflows.nodes.stage8_audio_mastering import stage8_audio_mastering_node
from app.workflows.routers.audit_router import make_stage_audit_node

logger = logging.getLogger("lmd.master_graph")


# 节点自愈防死循环重试计数器字典
_RETRY_COUNTERS: dict[str, int] = {}


def _route_after_audit(next_stage_node: str, self_stage_node: str):
    """构建审计后的条件路由，具备最大自愈次数兜底。"""
    def route_fn(state: IndustrialDramaMasterState) -> str:
        audit = state.latest_audit
        counter_key = f"{state.drama_id}_{self_stage_node}"
        current_retries = _RETRY_COUNTERS.get(counter_key, 0)

        if audit and audit.verdict == AuditVerdict.RED_BLOCKING:
            if current_retries < 2:
                _RETRY_COUNTERS[counter_key] = current_retries + 1
                logger.warning(
                    f"Audit RED_BLOCKING on stage, self-healing back to {self_stage_node} (retry {current_retries + 1}/2)"
                )
                return self_stage_node
            else:
                logger.error(
                    f"Max self-healing retries reached for {self_stage_node}, forcing progression to {next_stage_node}"
                )
                _RETRY_COUNTERS[counter_key] = 0
                return next_stage_node

        _RETRY_COUNTERS[counter_key] = 0
        return next_stage_node

    return route_fn


def _route_after_stage5_audit(state: IndustrialDramaMasterState) -> str:
    """阶段 5 审计后的路由判定：波次推进循环 vs 定稿门禁。"""
    total = state.total_episodes or 5
    completed = len(state.completed_screenplays or {})

    counter_key = f"{state.drama_id}_stage5_screenplay"
    current_retries = _RETRY_COUNTERS.get(counter_key, 0)
    audit = state.latest_audit

    if audit and audit.verdict == AuditVerdict.RED_BLOCKING and current_retries < 2:
        _RETRY_COUNTERS[counter_key] = current_retries + 1
        return "stage5_screenplay"

    _RETRY_COUNTERS[counter_key] = 0

    if completed < total:
        logger.info(f"Mini-Arc progress: {completed}/{total} episodes completed. Continuing Stage 5.")
        return "stage5_screenplay"

    logger.info(f"All {total} episodes screenplay generated. Moving to Gatekeeper.")
    return "gatekeeper"


def _route_after_stage8(state: IndustrialDramaMasterState) -> str:
    """阶段 8 音频工程后的路由判定：下一集循环 vs 全剧交付结束。"""
    if state.journey == "completed":
        logger.info(f"All episodes visual & audio journey completed! Terminating graph.")
        return END
    
    total = state.total_episodes or 5
    curr_ep = state.current_visual_episode or 1
    if curr_ep <= total:
        logger.info(f"Advancing visual journey to Episode {curr_ep}/{total}.")
        return "stage6_asset_truth"

    return END


def _route_entry_node(state: IndustrialDramaMasterState) -> str:
    """根据全局状态判断主图入口：直接启动第一程文学立项 vs 断点恢复进入第二程视听分镜。"""
    if state.journey == "journey_2_visual_audio" or state.literary_journey_locked:
        logger.info("Entry router: Literary journey already locked, entering Stage 6 Asset Truth directly.")
        return "stage6_asset_truth"
    return "stage1_ideation"


# 全局共享内存检查点
GLOBAL_GRAPH_CHECKPOINTER = MemorySaver()


def build_industrial_master_graph(checkpointer: Any = None, interrupt_after: list[str] | None = None):
    """构建两程九阶工业全息图编排。"""
    workflow = StateGraph(IndustrialDramaMasterState)

    # 1. 注册各阶节点
    workflow.add_node("stage1_ideation", stage1_ideation_node)
    workflow.add_node(
        "audit_stage1",
        make_stage_audit_node(1, lambda s: {"title": s.selected_title, "matrix": s.candidate_titles.model_dump() if hasattr(s.candidate_titles, "model_dump") else {}}),
    )

    workflow.add_node("stage2_character", stage2_character_node)
    workflow.add_node(
        "audit_stage2",
        make_stage_audit_node(2, lambda s: s.characters_engine),
    )

    workflow.add_node("stage3_environment_prop", stage3_environment_prop_node)
    workflow.add_node(
        "audit_stage3",
        make_stage_audit_node(3, lambda s: s.environments_and_props),
    )

    workflow.add_node("stage4_outline", stage4_outline_node)
    workflow.add_node(
        "audit_stage4",
        make_stage_audit_node(4, lambda s: s.season_outlines),
    )

    workflow.add_node("stage5_screenplay", stage5_screenplay_node)
    workflow.add_node(
        "audit_stage5",
        make_stage_audit_node(5, lambda s: s.completed_screenplays),
    )

    workflow.add_node("gatekeeper", stage5_literary_gatekeeper_node)

    workflow.add_node("stage6_asset_truth", stage6_asset_truth_node)
    workflow.add_node("stage7_storyboard_srt", stage7_storyboard_srt_node)
    workflow.add_node("stage8_audio_mastering", stage8_audio_mastering_node)

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
        _route_after_stage8,
    )

    cp = checkpointer if checkpointer is not None else GLOBAL_GRAPH_CHECKPOINTER
    if interrupt_after:
        return workflow.compile(checkpointer=cp, interrupt_after=interrupt_after)
    return workflow.compile(checkpointer=cp)


def run_industrial_master_pipeline(
    initial_state: IndustrialDramaMasterState,
    thread_id: str | None = None,
    checkpointer: Any = None,
) -> IndustrialDramaMasterState:
    """同步运行全流程两程九阶工作流。"""
    graph = build_industrial_master_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id or f"drama_{initial_state.drama_id}"}}
    
    final_state_dict = graph.invoke(initial_state, config=config)
    return IndustrialDramaMasterState.model_validate(final_state_dict)


def stream_industrial_master_pipeline(
    initial_state: IndustrialDramaMasterState,
    thread_id: str | None = None,
    checkpointer: Any = None,
) -> Generator[dict[str, Any], None, None]:
    """流式运行两程九阶工作流，yield 每个节点的执行事件与产出状态。"""
    graph = build_industrial_master_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id or f"drama_{initial_state.drama_id}"}}

    for chunk in graph.stream(initial_state, config=config, stream_mode="updates"):
        yield chunk
