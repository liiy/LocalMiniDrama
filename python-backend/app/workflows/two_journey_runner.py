"""两程九阶 LangGraph 工作流运行时与后台任务调度器 (Two Journey Runner)。

【核心职责】
1. 协调工业主图 Industrial Master Graph、事件总线 EventBus 与持久化适配器 DramaStorageAdapter；
2. 管理第一程【文学故事工程】至第二程【视听分镜工程】的异步流式执行；
3. 支持 Gatekeeper 门禁人机交互挂起（HITL）与无缝断点唤醒恢复；
4. 全生命周期推送标准化 SSE 工业事件 (STAGE_PROGRESS, RED_BLUE_AUDIT, MINI_ARC_COMPLETED, FIRST_JOURNEY_LOCKED, EPISODE_VISUAL_STARTED, EPISODE_VISUAL_COMPLETED, PIPELINE_COMPLETED, PIPELINE_ERROR)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.context.short_memory_service import (
    publish_drama_event,
    publish_drama_read_projection,
    publish_episode_read_projection,
    set_episode_physical_snapshot,
)
from app.core.event_bus import EventBus
from app.db.session import fetch_one, session_scope
from app.platform_common import now_iso
from app.schemas.script_graph_state import (
    DoubleTrackProhibitions,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
)
from app.workflows.adapters.drama_storage_adapter import (
    DramaStorageAdapter,
    _safe_json_loads,
    load_episode_substate_slice,
    persist_episode_substate_slice,
)
from app.workflows.industrial_master_graph import (
    GLOBAL_GRAPH_CHECKPOINTER,
    build_episode_subgraph,
    build_industrial_master_graph,
    build_literary_master_graph,
    run_episode_subgraph,
    run_literary_master_pipeline,
    stream_literary_master_pipeline,
    sync_checkpoint_to_index,
)
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node
from app.workflows.nodes.stage8_audio_mastering import stage8_audio_mastering_node

import json

logger = logging.getLogger("lmd.two_journey_runner")


STAGE_NAME_MAP = {
    1: "题材立项与双轨禁令",
    2: "角色引擎与心理四元组",
    3: "空间三层做旧与物证拟音",
    4: "全季大纲与音频动机母库",
    5: "Mini-Arc工笔剧本波次生成",
    6: "单集资产提纯与真理源校验",
    7: "视听双模式分镜与SRT轴测",
    8: "全息声学混音与分贝避让",
}


def _update_drama_pipeline_status(db: Session, drama_id: int, status: str, lock_status: int | None = None, thread_id: str | None = None) -> None:
    """原子更新短剧 pipeline_status 与 lock_status。"""
    sql = "UPDATE dramas SET pipeline_status = :status, updated_at = :now"
    params: dict[str, Any] = {"status": status, "now": now_iso(), "id": drama_id}
    if lock_status is not None:
        sql += ", lock_status = :lock_status"
        params["lock_status"] = lock_status
    if thread_id is not None:
        sql += ", thread_id = :thread_id"
        params["thread_id"] = thread_id
    sql += " WHERE id = :id"
    db.execute(text(sql), params)
    db.commit()


def _process_node_update(
    db: Session,
    drama_id: int,
    state: GlobalDramaMasterState,
    node_name: str,
    fields: dict[str, Any],
    auto_proceed_to_visual: bool = False,
) -> None:
    """统一节点状态合并、原子持久化落库与 SSE 工业事件广播派发器。

    【设计原则】
    1. 消除代码冗余 (DRY)：正常全流程运行与断点唤醒恢复时，共享完全同构的持久化和事件派发逻辑；
    2. 阶段化即时原子落库：每个节点执行完毕，即时调用 DramaStorageAdapter 对应的原子持久化函数，并在操作结束提交事务；
    3. 全方位工业级日志记录：关键节点输出中文结构化审计日志，支持快速定位阶段执行状态；
    4. 标准化 SSE 事件广播：保持前端与总线感知到的事件 payload 绝对统一。
    """
    if not isinstance(fields, dict):
        logger.warning(f"[TwoJourneyRunner] 收到非字典状态更新，跳过分发: node_name={node_name}, type={type(fields)}")
        return

    # 1. 将节点产出的增量字段合并进全局主状态 GlobalDramaMasterState
    for k, v in fields.items():
        if hasattr(state, k):
            setattr(state, k, v)

    logger.debug(f"[TwoJourneyRunner] 派发节点更新: drama_id={drama_id}, node_name={node_name}")

    # 2. 阶段 1：题材立项与双轨禁令
    if node_name == "stage1_ideation":
        DramaStorageAdapter.persist_stage1(db, drama_id, state)
        logger.info(
            f"[TwoJourneyRunner] 【Stage 1 完成并原子落库】drama_id={drama_id}, "
            f"定稿剧名=《{state.selected_title}》, 题材={state.genre}"
        )
        EventBus.publish_event(
            drama_id,
            "STAGE_PROGRESS",
            {
                "stage": 1,
                "stage_name": STAGE_NAME_MAP[1],
                "journey": "journey_1_literary",
                "status": "completed",
                "progress_pct": 15,
                "summary": {
                    "selected_title": state.selected_title,
                    "candidate_titles": state.candidate_titles.model_dump() if hasattr(state.candidate_titles, "model_dump") else {},
                },
            },
        )

    # 3. 阶段红蓝对抗审查节点 (audit_stage1 ~ audit_stage5)
    elif node_name.startswith("audit_stage"):
        stage_idx = int(node_name.replace("audit_stage", ""))
        audit = state.latest_audit
        v_val = audit.verdict.value if hasattr(audit.verdict, "value") else str(audit.verdict)
        b_checks = getattr(audit, "blue_checks", getattr(audit, "blue_team_compliance", {}))
        r_complaints = getattr(audit, "red_complaints", getattr(audit, "red_team_criticism", {}))
        c_score = getattr(audit, "confidence_score", 0.95)
        logger.info(
            f"[TwoJourneyRunner] 【阶段 {stage_idx} 质检审查】drama_id={drama_id}, "
            f"裁决结果={v_val}, 置信度={c_score}"
        )
        EventBus.publish_event(
            drama_id,
            "RED_BLUE_AUDIT",
            {
                "stage": stage_idx,
                "stage_name": STAGE_NAME_MAP.get(stage_idx, f"阶段{stage_idx}"),
                "verdict": v_val,
                "blue_checks": b_checks,
                "red_complaints": r_complaints,
                "confidence_score": c_score,
            },
        )

    # 4. 阶段 2：角色引擎与心理四元组
    elif node_name == "stage2_character":
        DramaStorageAdapter.persist_stage2(db, drama_id, state)
        chars = state.characters_engine.get("characters", [])
        logger.info(
            f"[TwoJourneyRunner] 【Stage 2 完成并原子落库】drama_id={drama_id}, "
            f"构建角色总数={len(chars)} ({', '.join([c.get('name', '') for c in chars[:5]])})"
        )
        EventBus.publish_event(
            drama_id,
            "STAGE_PROGRESS",
            {
                "stage": 2,
                "stage_name": STAGE_NAME_MAP[2],
                "journey": "journey_1_literary",
                "status": "completed",
                "progress_pct": 30,
                "summary": {"characters_count": len(chars), "characters": [c.get("name") for c in chars]},
            },
        )

    # 5. 阶段 3：空间三层做旧与物证拟音
    elif node_name == "stage3_environment_prop":
        DramaStorageAdapter.persist_stage3(db, drama_id, state)
        envs = state.environments_and_props.get("environments", [])
        props = state.environments_and_props.get("props", [])
        logger.info(
            f"[TwoJourneyRunner] 【Stage 3 完成并原子落库】drama_id={drama_id}, "
            f"空间场景数={len(envs)}, 叙事物证数={len(props)}"
        )
        EventBus.publish_event(
            drama_id,
            "STAGE_PROGRESS",
            {
                "stage": 3,
                "stage_name": STAGE_NAME_MAP[3],
                "journey": "journey_1_literary",
                "status": "completed",
                "progress_pct": 45,
                "summary": {"environments_count": len(envs), "props_count": len(props)},
            },
        )

    # 6. 阶段 4：全季大纲与音频动机母库
    elif node_name == "stage4_outline":
        DramaStorageAdapter.persist_stage4(db, drama_id, state)
        motifs = state.audio_bible.leitmotifs if hasattr(state.audio_bible, "leitmotifs") else []
        acts = state.season_outlines.get("acts", []) if isinstance(state.season_outlines, dict) else []
        logger.info(
            f"[TwoJourneyRunner] 【Stage 4 完成并原子落库】drama_id={drama_id}, "
            f"全季幕数={len(acts)}, 核心音乐主题数={len(motifs)}"
        )
        EventBus.publish_event(
            drama_id,
            "STAGE_PROGRESS",
            {
                "stage": 4,
                "stage_name": STAGE_NAME_MAP[4],
                "journey": "journey_1_literary",
                "status": "completed",
                "progress_pct": 60,
                "summary": {"acts_count": len(acts), "motifs_count": len(motifs)},
            },
        )

    # 7. 阶段 5：Mini-Arc工笔剧本波次生成
    elif node_name == "stage5_screenplay":
        DramaStorageAdapter.persist_stage5(db, drama_id, state)
        comp_cnt = len(state.completed_screenplays)
        tot = state.total_episodes
        pct = 60 + int(25 * (comp_cnt / max(tot, 1)))
        latest_ep = max(state.completed_screenplays.keys(), default=1)
        logger.info(
            f"[TwoJourneyRunner] 【Stage 5 完成并原子落库】drama_id={drama_id}, "
            f"剧本生成进度={comp_cnt}/{tot}, 最新集数=第{latest_ep}集"
        )
        # 发布 CQRS 只读投影至 Redis HASH，确保读写分离即时同步
        try:
            publish_drama_read_projection(drama_id, {
                "drama_id": drama_id,
                "current_stage": 5,
                "journey": "journey_1_literary",
                "completed_episodes": sorted(list(state.completed_screenplays.keys())),
                "total_episodes": tot,
                "progress_pct": pct,
                "literary_journey_locked": getattr(state, "literary_journey_locked", False),
            })
            logger.info("【两程执行器】成功发布 Stage 5 CQRS 读模型投影 (drama_id=%s, 进度=%d/%d)", drama_id, comp_cnt, tot)
        except Exception as e:
            logger.warning("【两程执行器】发布 Stage 5 CQRS 读模型投影异常: %s", e)

        EventBus.publish_event(
            drama_id,
            "MINI_ARC_COMPLETED",
            {
                "stage": 5,
                "completed_count": comp_cnt,
                "total_episodes": tot,
                "progress_pct": pct,
                "latest_episode_num": latest_ep,
                "physical_snapshot": state.inter_episode_physical_snapshot,
            },
        )

    # 8. 第一程门禁哨卡 (gatekeeper)
    elif node_name == "gatekeeper":
        DramaStorageAdapter.persist_stage5(db, drama_id, state)
        _update_drama_pipeline_status(db, drama_id, "running" if auto_proceed_to_visual else "paused_hitl", lock_status=1)
        logger.info(
            f"[TwoJourneyRunner] 【Gatekeeper 门禁触发】drama_id={drama_id}, "
            f"auto_proceed_to_visual={auto_proceed_to_visual}, lock_status=1"
        )
        # 发布 CQRS 只读投影至 Redis HASH，标记第一程全季定稿锁死状态
        try:
            publish_drama_read_projection(drama_id, {
                "drama_id": drama_id,
                "current_stage": 6 if auto_proceed_to_visual else 5,
                "journey": "journey_2_visual" if auto_proceed_to_visual else "journey_1_literary",
                "lock_status": 1,
                "literary_journey_locked": True,
                "pipeline_status": "running" if auto_proceed_to_visual else "paused_hitl",
                "completed_episodes": sorted(list(state.completed_screenplays.keys())),
                "total_episodes": state.total_episodes,
            })
            logger.info("【两程执行器】成功发布 Gatekeeper CQRS 读模型投影 (drama_id=%s, lock_status=1)", drama_id)
        except Exception as e:
            logger.warning("【两程执行器】发布 Gatekeeper CQRS 读模型投影异常: %s", e)

        EventBus.publish_event(
            drama_id,
            "FIRST_JOURNEY_LOCKED",
            {
                "stage": 5,
                "journey": "journey_1_literary",
                "status": "locked",
                "total_episodes": state.total_episodes,
                "completed_screenplays": len(state.completed_screenplays),
                "paused_for_hitl": not auto_proceed_to_visual,
                "message": "第一程文学剧本全季已定稿锁定！" if auto_proceed_to_visual else "第一程文学剧本已定稿锁定，等待主创审批放行第二程！",
            },
        )

    # 9. 阶段 6：单集资产提纯与真理源校验
    elif node_name == "stage6_asset_truth":
        ep_num = state.current_visual_episode
        DramaStorageAdapter.persist_stage6(db, drama_id, state, ep_num)
        logger.info(
            f"[TwoJourneyRunner] 【Stage 6 完成并原子落库】drama_id={drama_id}, 第 {ep_num} 集资产真理源提纯完毕"
        )
        EventBus.publish_event(
            drama_id,
            "EPISODE_VISUAL_STARTED",
            {
                "stage": 6,
                "stage_name": STAGE_NAME_MAP[6],
                "journey": "journey_2_visual_audio",
                "episode_num": ep_num,
                "status": "started",
            },
        )

    # 10. 阶段 7：视听双模式分镜与SRT轴测
    elif node_name == "stage7_storyboard_srt":
        ep_num = state.current_visual_episode
        DramaStorageAdapter.persist_stage7(db, drama_id, state, ep_num)
        logger.info(
            f"[TwoJourneyRunner] 【Stage 7 完成并原子落库】drama_id={drama_id}, 第 {ep_num} 集双模式分镜与SRT对齐完毕"
        )
        EventBus.publish_event(
            drama_id,
            "STAGE_PROGRESS",
            {
                "stage": 7,
                "stage_name": STAGE_NAME_MAP[7],
                "journey": "journey_2_visual_audio",
                "episode_num": ep_num,
                "status": "completed",
            },
        )

    # 11. 阶段 8：全息声学混音与分贝避让
    elif node_name == "stage8_audio_mastering":
        ep_num = state.current_visual_episode
        DramaStorageAdapter.persist_stage8(db, drama_id, state, ep_num)
        tot_eps = state.total_episodes
        pct = 85 + int(15 * (ep_num / max(tot_eps, 1)))
        logger.info(
            f"[TwoJourneyRunner] 【Stage 8 完成并原子落库】drama_id={drama_id}, 第 {ep_num}/{tot_eps} 集全息混音完成"
        )
        EventBus.publish_event(
            drama_id,
            "EPISODE_VISUAL_COMPLETED",
            {
                "stage": 8,
                "stage_name": STAGE_NAME_MAP[8],
                "journey": state.journey,
                "episode_num": ep_num,
                "total_episodes": tot_eps,
                "progress_pct": pct,
                "status": "completed",
            },
        )

    # 12. 第二程分集迭代光标推进节点
    elif node_name == "episode_increment":
        logger.info(
            f"[TwoJourneyRunner] 【单集光标递增】drama_id={drama_id}, "
            f"准备进入下一集: 当前集号={state.current_visual_episode}"
        )

    # 13. 全流程成功完结终端节点
    elif node_name == "pipeline_complete":
        logger.info(
            f"[TwoJourneyRunner] 【两程九阶全流程完结节点】drama_id={drama_id}, journey标记置为 completed"
        )


def _stream_graph_execution(
    graph: Any,
    config: dict[str, Any],
    state: GlobalDramaMasterState,
    db: Session,
    drama_id: int,
    auto_proceed_to_visual: bool = False,
    initial_input: Any = None,
) -> None:
    """统一消费 LangGraph 工业主图流式事件循环，处理中断挂起、状态分发落库与全流程终态判定。"""
    logger.info(
        f"[TwoJourneyRunner] 启动主图流式执行消费: drama_id={drama_id}, "
        f"thread_id={config.get('configurable', {}).get('thread_id')}, "
        f"initial_input={'<State>' if initial_input is not None else 'None'}"
    )

    # 1. 遍历图流式 updates 输出
    for update in graph.stream(initial_input, config=config, stream_mode="updates"):
        for node_name, fields in update.items():
            # 命中 interrupt_after 中断挂起
            if node_name == "__interrupt__":
                logger.info(f"[TwoJourneyRunner] 流程触发中断节点挂起: drama_id={drama_id}, interrupts={fields}")
                sync_checkpoint_to_index(graph, config, drama_id, db)
                continue

            # 统一派发节点更新、原子持久化与事件推送
            _process_node_update(
                db=db,
                drama_id=drama_id,
                state=state,
                node_name=node_name,
                fields=fields,
                auto_proceed_to_visual=auto_proceed_to_visual,
            )

    # 2. 流式迭代结束，将当前最新检查点同步至索引表
    sync_checkpoint_to_index(graph, config, drama_id, db)

    # 3. 检查最终状态并原子更新 dramas 表状态与广播完结事件
    if state.journey == "completed":
        _update_drama_pipeline_status(db, drama_id, "completed")
        EventBus.publish_event(
            drama_id,
            "PIPELINE_COMPLETED",
            {
                "drama_id": drama_id,
                "journey": "completed",
                "total_episodes": state.total_episodes,
                "message": "短剧两程九阶全流程执行完毕，已交付全套工业级视听工程！",
            },
        )
        logger.info(f"[TwoJourneyRunner] 短剧两程九阶全流程执行完毕，已交付全套工业级视听工程！drama_id={drama_id}")
    elif not auto_proceed_to_visual and state.literary_journey_locked:
        _update_drama_pipeline_status(db, drama_id, "paused_hitl")
        logger.info(f"[TwoJourneyRunner] 第一程文学工程定稿，进入门禁挂起等待主创审批: drama_id={drama_id}")
    elif state.journey != "completed":
        _update_drama_pipeline_status(db, drama_id, "paused_hitl")
        logger.info(f"[TwoJourneyRunner] 工作流当前处于暂停挂起状态: drama_id={drama_id}, current_stage={state.current_stage}")


def _execute_two_journey_pipeline(
    db: Session,
    drama_id: int,
    user_prompt: str,
    genre: str = "现代",
    total_episodes: int = 12,
    target_duration_sec: float = 120.0,
    visual_style: str = "真人电影/超写实",
    aspect_ratio: str = "9:16",
    auto_proceed_to_visual: bool = False,
    run_mode: str = "two_journey",
) -> None:
    """执行两程九阶全息状态机的核心流式编排逻辑。"""
    try:
        thread_id = f"drama_{drama_id}"
        config = {"configurable": {"thread_id": thread_id}}

        _update_drama_pipeline_status(db, drama_id, "running", None, thread_id=thread_id)

        # 1. 尝试从数据库恢复已有状态或初始化新状态
        try:
            state = DramaStorageAdapter.load_state(db, drama_id)
        except Exception:
            state = GlobalDramaMasterState(drama_id=drama_id)

        # 更新基线参数
        state.drama_id = drama_id
        state.total_episodes = total_episodes
        state.target_duration_sec = target_duration_sec
        state.visual_style = visual_style
        state.aspect_ratio = aspect_ratio
        state.genre = genre
        state.run_mode = run_mode
        if user_prompt:
            state.user_idea = user_prompt
        if not state.logline:
            state.logline = user_prompt
        if not state.selected_title:
            state.selected_title = f"{genre}短剧"

        # 2. 编译图：根据 run_mode 与 auto_proceed_to_visual 配置 interrupt_after
        # 若 auto_proceed_to_visual 为 True，第一程定稿与第二程单集均不挂起，全自动直通跑完
        if auto_proceed_to_visual:
            interrupt_nodes = []
        else:
            interrupt_nodes = None  # 由 build_industrial_master_graph 依据 run_mode 动态推导

        graph = build_industrial_master_graph(
            checkpointer=GLOBAL_GRAPH_CHECKPOINTER,
            run_mode=run_mode,
            interrupt_after=interrupt_nodes,
        )

        logger.info(
            f"[TwoJourneyRunner] 启动两程九阶全息工作流: drama_id={drama_id}, "
            f"run_mode={run_mode}, auto_proceed_to_visual={auto_proceed_to_visual}"
        )

        EventBus.publish_event(
            drama_id,
            "STAGE_PROGRESS",
            {
                "stage": 1,
                "stage_name": STAGE_NAME_MAP[1],
                "journey": "journey_1_literary",
                "status": "started",
                "progress_pct": 5,
                "summary": {"prompt": user_prompt, "genre": genre},
            },
        )

        # 3. 执行统一流式调度引擎
        _stream_graph_execution(
            graph=graph,
            config=config,
            state=state,
            db=db,
            drama_id=drama_id,
            auto_proceed_to_visual=auto_proceed_to_visual,
            initial_input=state,
        )

    except Exception as e:
        logger.exception(f"Error executing two-journey pipeline for drama {drama_id}: {e}")
        try:
            _update_drama_pipeline_status(db, drama_id, "failed")
        except Exception:
            pass
        EventBus.publish_event(
            drama_id,
            "PIPELINE_ERROR",
            {"drama_id": drama_id, "error": str(e)},
        )


def _execute_resume_two_journey_pipeline(
    db: Session,
    drama_id: int,
    approved: bool = True,
    feedback: str | None = None,
    run_mode: str = "two_journey",
) -> None:
    """唤醒处于门禁暂停状态的两程九阶工作流并进入第二程视听工程。

    【两程门禁与阶段审批分流保护 (Fix Drama 7 Regression)】
    1. 若项目当前仍处于第一程中间阶段 (current_stage < 5)，说明属于阶段级审批挂起（如 Stage 4 自审拦截），
       严禁强行按第二程视听工程唤醒！转调 approve_human_review 放行阶段自审并推进到下一阶，彻底根除误重跑。
    2. 若项目处于全季文学创作完成节点 (current_stage >= 5)，调用 confirm_gatekeeper_and_lock
       锁定文学资产、原子跃迁 current_stage=6 并唤醒第二程视听工业化工程。
    """
    try:
        from app.services.workflow_lock_service import workflow_lock_context
        from app.services.workflow_time_travel_service import approve_human_review, confirm_gatekeeper_and_lock

        state = DramaStorageAdapter.load_state(db, drama_id)
        current_stage = getattr(state, "current_stage", 1)

        logger.info(
            f"[TwoJourneyRunner] 主创审批唤醒工作流: drama_id={drama_id}, "
            f"current_stage={current_stage}, approved={approved}, feedback={feedback}"
        )

        if not approved:
            logger.info(f"[TwoJourneyRunner] 审批未通过，中止唤醒: drama_id={drama_id}")
            return

        with workflow_lock_context(str(drama_id)) as acquired:
            if not acquired:
                logger.warning(f"[TwoJourneyRunner] drama_id={drama_id} 正在执行中，跳过重复唤醒")
                return

            if current_stage < 5:
                logger.warning(
                    f"[TwoJourneyRunner] 检测到 drama_id={drama_id} 处于第一程阶段 {current_stage}，"
                    f"非全季定稿总门禁。执行阶段级审批安全放行 (approve_human_review)，推进至 Stage {current_stage + 1}，防止误重跑！"
                )
                approve_human_review(
                    drama_id=str(drama_id),
                    stage=current_stage,
                    human_feedback=feedback or f"Stage {current_stage} 主创审批放行",
                    auto_resume=True,
                    run_mode=run_mode,
                )
                return

            logger.info(
                f"[TwoJourneyRunner] drama_id={drama_id} 处于全季定稿门禁节点 (current_stage={current_stage})，"
                f"执行文学资产定稿锁定与第二程唤醒！"
            )
            confirm_gatekeeper_and_lock(
                drama_id=str(drama_id),
                operator="human_gatekeeper",
                human_feedback=feedback,
                auto_resume=True,
                run_mode=run_mode,
            )

    except Exception as e:
        logger.exception(f"Error resuming two-journey pipeline for drama {drama_id}: {e}")
        try:
            _update_drama_pipeline_status(db, drama_id, "failed")
        except Exception:
            pass
        EventBus.publish_event(
            drama_id,
            "PIPELINE_ERROR",
            {"drama_id": drama_id, "error": str(e)},
        )


def run_two_journey_pipeline_async(
    drama_id: int,
    user_prompt: str,
    genre: str = "现代",
    total_episodes: int = 12,
    target_duration_sec: float = 120.0,
    visual_style: str = "真人电影/超写实",
    aspect_ratio: str = "9:16",
    auto_proceed_to_visual: bool = False,
    run_mode: str = "two_journey",
    db: Session | None = None,
) -> None:
    """后台独立线程运行两程九阶全息状态机。"""
    if db is not None:
        _execute_two_journey_pipeline(
            db=db,
            drama_id=drama_id,
            user_prompt=user_prompt,
            genre=genre,
            total_episodes=total_episodes,
            target_duration_sec=target_duration_sec,
            visual_style=visual_style,
            aspect_ratio=aspect_ratio,
            auto_proceed_to_visual=auto_proceed_to_visual,
            run_mode=run_mode,
        )
    else:
        with session_scope() as db_session:
            _execute_two_journey_pipeline(
                db=db_session,
                drama_id=drama_id,
                user_prompt=user_prompt,
                genre=genre,
                total_episodes=total_episodes,
                target_duration_sec=target_duration_sec,
                visual_style=visual_style,
                aspect_ratio=aspect_ratio,
                auto_proceed_to_visual=auto_proceed_to_visual,
                run_mode=run_mode,
            )


def resume_two_journey_pipeline_async(
    drama_id: int,
    approved: bool = True,
    feedback: str | None = None,
    run_mode: str = "two_journey",
    db: Session | None = None,
) -> None:
    """唤醒处于门禁暂停状态的两程九阶工作流并进入第二程视听工程。"""
    if db is not None:
        _execute_resume_two_journey_pipeline(
            db=db,
            drama_id=drama_id,
            approved=approved,
            feedback=feedback,
            run_mode=run_mode,
        )
    else:
        with session_scope() as db_session:
            _execute_resume_two_journey_pipeline(
                db=db_session,
                drama_id=drama_id,
                approved=approved,
                feedback=feedback,
                run_mode=run_mode,
            )


class SlidingWindowPipeline:
    """第二程（Stage 6~8）多集滑动窗口并发流水线调度器 (Sliding-Window Pipelining)。

    【核心特性与架构规范】
    1. 物理连续性解耦：第 N+1 集仅等待第 N 集的物理连续性快照 (InterEpisodePhysicalContinuity) 就绪，
       即可提前预热并行启动 Stage 6 资产提纯，无需阻塞等待第 N 集耗时漫长的 Stage 7/8 视听与音频密集工程；
    2. 滑动窗口容量控制：基于 asyncio.Semaphore 限制并发集数（默认 2~3），防止 GPU/API 显存耗尽或速率超限；
    3. 单集切片水合与隔离：各集使用 EpisodeScopedSubState，单集状态 < 100KB，实现物理级内存隔离；
    4. 原子落库与 CQRS 读模型刷新：单集执行完后通过 persist_episode_substate_slice 写入数据库并发布 Redis 读投影；
    5. 全生命周期 SSE 事件广播：STAGE_PROGRESS, EPISODE_VISUAL_STARTED, EPISODE_VISUAL_COMPLETED, PIPELINE_COMPLETED。
    """

    def __init__(
        self,
        db: Session | None = None,
        window_size: int = 2,
    ) -> None:
        self.db = db
        self.window_size = max(1, window_size)

    async def execute_sliding_window(
        self,
        drama_id: int,
        episodes: list[int] | None = None,
        total_episodes: int = 12,
    ) -> dict[int, EpisodeScopedSubState]:
        """异步执行多集滑动窗口流水线。"""
        episodes_to_run = episodes or list(range(1, total_episodes + 1))
        if not episodes_to_run:
            return {}

        logger.info(
            f"【滑动窗口流水线】启动剧目 [{drama_id}] 第二程视听分镜流水线: "
            f"集数列表={episodes_to_run}, 窗口大小={self.window_size}"
        )

        # 连续性快照传递事件与快照暂存字典
        continuity_events: dict[int, asyncio.Event] = {ep: asyncio.Event() for ep in episodes_to_run}
        continuity_snapshots: dict[int, Any] = {}

        # 首集无需等待前序连续性快照，直接唤醒
        continuity_events[episodes_to_run[0]].set()

        sem = asyncio.Semaphore(self.window_size)
        completed_substates: dict[int, EpisodeScopedSubState] = {}

        async def _process_episode(ep_num: int) -> None:
            # 1. 等待上一集物理连续性快照交付
            logger.debug(f"[SlidingWindow] Episode {ep_num} awaiting continuity snapshot...")
            await continuity_events[ep_num].wait()
            logger.info(f"【滑动窗口流水线】第 {ep_num} 集连续性快照已就绪，进入窗口执行队列...")

            async with sem:
                logger.info(f"【滑动窗口流水线】第 {ep_num} 集获取执行窗口 (当前并发槽占用中)，开始单集切片水合...")

                # 2. 懒水合单集切片 (EpisodeScopedSubState < 100KB)
                def _load() -> EpisodeScopedSubState:
                    if self.db:
                        return load_episode_substate_slice(self.db, drama_id, ep_num)
                    with session_scope() as s:
                        return load_episode_substate_slice(s, drama_id, ep_num)

                substate: EpisodeScopedSubState = await asyncio.to_thread(_load)

                # 注入前序集传递的连续性快照
                if ep_num in continuity_snapshots:
                    snapshot = continuity_snapshots[ep_num]
                    substate.incoming_physical_continuity = snapshot
                    substate.inherited_physical_continuity = snapshot

                # 广播 Stage 6 开始事件
                EventBus.publish_event(
                    drama_id,
                    "EPISODE_VISUAL_STARTED",
                    {
                        "stage": 6,
                        "stage_name": STAGE_NAME_MAP[6],
                        "journey": "journey_2_visual_audio",
                        "episode_num": ep_num,
                        "status": "started",
                    },
                )

                # 3. 执行 Stage 6 单集资产提纯与真理源校验
                stage6_res = await asyncio.to_thread(stage6_asset_truth_node, substate)
                for k, v in stage6_res.items():
                    if hasattr(substate, k):
                        setattr(substate, k, v)

                # 4. 提取连续性快照并立即唤醒下一集（核心流水线解耦点）
                outgoing_candidate = (
                    stage6_res.get("outgoing_physical_continuity")
                    or substate.outgoing_physical_continuity
                )
                if outgoing_candidate:
                    outgoing_snapshot = (
                        outgoing_candidate.model_dump()
                        if hasattr(outgoing_candidate, "model_dump")
                        else dict(outgoing_candidate)
                        if isinstance(outgoing_candidate, dict)
                        else {}
                    )
                else:
                    outgoing_snapshot = {}

                if not outgoing_snapshot.get("episode_number") and not outgoing_snapshot.get("from_episode"):
                    outgoing_snapshot["episode_number"] = ep_num
                    outgoing_snapshot["from_episode"] = ep_num
                if "location" not in outgoing_snapshot:
                    outgoing_snapshot["location"] = "延续场景"
                if "character_positions" not in outgoing_snapshot:
                    outgoing_snapshot["character_positions"] = {}

                next_ep = ep_num + 1
                if next_ep in continuity_events:
                    continuity_snapshots[next_ep] = outgoing_snapshot
                    set_episode_physical_snapshot(drama_id, ep_num, outgoing_snapshot)
                    continuity_events[next_ep].set()
                    logger.info(
                        f"【滑动窗口流水线】第 {ep_num} 集已交付物理连续性快照至 Redis 并唤醒第 {next_ep} 集！"
                    )

                # 5. 执行 Stage 7 双模式分镜与 SRT
                stage7_res = await asyncio.to_thread(stage7_storyboard_srt_node, substate)
                for k, v in stage7_res.items():
                    if hasattr(substate, k):
                        setattr(substate, k, v)

                EventBus.publish_event(
                    drama_id,
                    "STAGE_PROGRESS",
                    {
                        "stage": 7,
                        "stage_name": STAGE_NAME_MAP[7],
                        "journey": "journey_2_visual_audio",
                        "episode_num": ep_num,
                        "status": "completed",
                    },
                )

                # 6. 执行 Stage 8 全息混音工程与分贝避让
                stage8_res = await asyncio.to_thread(stage8_audio_mastering_node, substate)
                for k, v in stage8_res.items():
                    if hasattr(substate, k):
                        setattr(substate, k, v)
                substate.is_completed = True
                substate.current_stage = 8

                # 7. 原子持久化与 CQRS 读模型刷新
                def _persist() -> None:
                    if self.db:
                        persist_episode_substate_slice(self.db, drama_id, substate)
                    else:
                        with session_scope() as s:
                            persist_episode_substate_slice(s, drama_id, substate)

                await asyncio.to_thread(_persist)

                # 8. 发布单集完成事件
                completed_substates[ep_num] = substate
                pct = 85 + int(15 * (len(completed_substates) / max(total_episodes, 1)))
                EventBus.publish_event(
                    drama_id,
                    "EPISODE_VISUAL_COMPLETED",
                    {
                        "stage": 8,
                        "stage_name": STAGE_NAME_MAP[8],
                        "journey": "journey_2_visual_audio",
                        "episode_num": ep_num,
                        "total_episodes": total_episodes,
                        "progress_pct": pct,
                        "status": "completed",
                    },
                )
                logger.info(f"【滑动窗口流水线】第 {ep_num} 集视听全流程圆满完成。")

        # 并发派发所有分集任务（受信号量与连续性事件双重流控）
        tasks = [_process_episode(ep) for ep in episodes_to_run]
        await asyncio.gather(*tasks)

        # 9. 全流程完成收尾
        def _update_final_status() -> None:
            if self.db:
                _update_drama_pipeline_status(self.db, drama_id, "completed")
            else:
                with session_scope() as s:
                    _update_drama_pipeline_status(s, drama_id, "completed")

        await asyncio.to_thread(_update_final_status)

        EventBus.publish_event(
            drama_id,
            "PIPELINE_COMPLETED",
            {
                "drama_id": drama_id,
                "journey": "completed",
                "total_episodes": total_episodes,
                "completed_episodes": len(completed_substates),
                "message": "短剧两程九阶全流程执行完毕，已交付全套工业级视听工程！",
            },
        )
        logger.info(f"【滑动窗口流水线】剧目 [{drama_id}] 全部 {len(completed_substates)} 集视听工程交付完毕！")
        return completed_substates


class TwoJourneyRunner:
    """两程九阶全生命周期工业执行调度器。

    支持依赖注入会话管理与异步协程生命周期驱动。
    """

    def __init__(self, db_session: Session | None = None) -> None:
        self.db_session = db_session

    async def run_pipeline_async(
        self,
        drama_id: int,
        user_prompt: str,
        genre: str = "现代",
        total_episodes: int = 12,
        target_duration_sec: float = 120.0,
        visual_style: str = "真人电影/超写实",
        aspect_ratio: str = "9:16",
        auto_proceed_to_visual: bool = False,
    ) -> None:
        """异步协程调度执行两程九阶全生命周期。"""
        await asyncio.to_thread(
            run_two_journey_pipeline_async,
            drama_id=drama_id,
            user_prompt=user_prompt,
            genre=genre,
            total_episodes=total_episodes,
            target_duration_sec=target_duration_sec,
            visual_style=visual_style,
            aspect_ratio=aspect_ratio,
            auto_proceed_to_visual=auto_proceed_to_visual,
            db=self.db_session,
        )

    async def resume_pipeline_async(
        self,
        drama_id: int,
        approved: bool = True,
        feedback: str | None = None,
    ) -> None:
        """异步协程调度唤醒处于门禁暂停状态的工作流。"""
        await asyncio.to_thread(
            resume_two_journey_pipeline_async,
            drama_id=drama_id,
            approved=approved,
            feedback=feedback,
            db=self.db_session,
        )

    async def run_sliding_window_visual_pipeline_async(
        self,
        drama_id: int,
        episodes: list[int] | None = None,
        total_episodes: int = 12,
        window_size: int = 2,
    ) -> dict[int, EpisodeScopedSubState]:
        """使用多集滑动窗口并发流水线调度执行第二程视听工程。"""
        pipeline = SlidingWindowPipeline(db=self.db_session, window_size=window_size)
        return await pipeline.execute_sliding_window(
            drama_id=drama_id,
            episodes=episodes,
            total_episodes=total_episodes,
        )

    async def run_literary_pipeline_async(
        self,
        drama_id: int,
        user_prompt: str,
        genre: str = "现代",
        total_episodes: int = 12,
        target_duration_sec: float = 120.0,
        visual_style: str = "真人电影/超写实",
        aspect_ratio: str = "9:16",
        checkpointer: Any = None,
    ) -> GlobalDramaMasterState:
        """异步协程调度独立执行第一程文学主图 (Stage 1~5 + Gatekeeper)。"""
        def _run() -> GlobalDramaMasterState:
            init_state = GlobalDramaMasterState(
                drama_id=drama_id,
                user_idea=user_prompt,
                logline=user_prompt,
                genre=genre,
                total_episodes=total_episodes,
                target_duration_sec=target_duration_sec,
                visual_style=visual_style,
                aspect_ratio=aspect_ratio,
            )
            return run_literary_master_pipeline(
                drama_id=drama_id,
                initial_state=init_state,
                checkpointer=checkpointer or GLOBAL_GRAPH_CHECKPOINTER,
            )
        return await asyncio.to_thread(_run)
