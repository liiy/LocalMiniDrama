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

from app.core.event_bus import EventBus
from app.db.session import session_scope
from app.platform_common import now_iso
from app.schemas.script_graph_state import (
    DoubleTrackProhibitions,
    IndustrialDramaMasterState,
)
from app.workflows.adapters.drama_storage_adapter import DramaStorageAdapter
from app.workflows.industrial_master_graph import (
    GLOBAL_GRAPH_CHECKPOINTER,
    build_industrial_master_graph,
)

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


def _update_drama_pipeline_status(db: Session, drama_id: int, status: str, lock_status: int | None = None) -> None:
    """原子更新短剧 pipeline_status 与 lock_status。"""
    sql = "UPDATE dramas SET pipeline_status = :status, updated_at = :now"
    params: dict[str, Any] = {"status": status, "now": now_iso(), "id": drama_id}
    if lock_status is not None:
        sql += ", lock_status = :lock_status"
        params["lock_status"] = lock_status
    sql += " WHERE id = :id"
    db.execute(text(sql), params)
    db.commit()


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
) -> None:
    """执行两程九阶全息状态机的核心流式编排逻辑。"""
    try:
        _update_drama_pipeline_status(db, drama_id, "running")

        # 1. 尝试从数据库恢复已有状态或初始化新状态
        try:
            state = DramaStorageAdapter.load_state(db, drama_id)
        except Exception:
            state = IndustrialDramaMasterState(drama_id=drama_id)

        # 更新基线参数
        state.drama_id = drama_id
        state.total_episodes = total_episodes
        state.target_duration_sec = target_duration_sec
        state.visual_style = visual_style
        state.aspect_ratio = aspect_ratio
        state.genre = genre
        if not state.logline:
            state.logline = user_prompt
        if not state.selected_title:
            state.selected_title = f"{genre}短剧"

        # 记忆便签初始化
        if not state.short_memory_a:
            state.short_memory_a = f"立项题材: {genre}, 视觉风格: {visual_style}, 核心冲突: {user_prompt[:50]}"

        # 2. 编译图：若不自动进入第二程，则在 gatekeeper 处挂起等待人工审核
        interrupt_nodes = ["gatekeeper"] if not auto_proceed_to_visual else None
        graph = build_industrial_master_graph(
            checkpointer=GLOBAL_GRAPH_CHECKPOINTER,
            interrupt_after=interrupt_nodes,
        )

        thread_id = f"drama_{drama_id}"
        config = {"configurable": {"thread_id": thread_id}}

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

        # 3. 流式消费主图 updates
        for update in graph.stream(state, config=config, stream_mode="updates"):
            for node_name, fields in update.items():
                # 合并状态
                for k, v in fields.items():
                    if hasattr(state, k):
                        setattr(state, k, v)

                # 根据节点类型推送标准化 SSE 事件并原子落库至专属实体表
                if node_name == "stage1_ideation":
                    DramaStorageAdapter.persist_stage1(db, drama_id, state)
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
                elif node_name.startswith("audit_stage"):
                    stage_idx = int(node_name.replace("audit_stage", ""))
                    audit = state.latest_audit
                    v_val = audit.verdict.value if hasattr(audit.verdict, "value") else str(audit.verdict)
                    b_checks = getattr(audit, "blue_checks", getattr(audit, "blue_team_compliance", {}))
                    r_complaints = getattr(audit, "red_complaints", getattr(audit, "red_team_criticism", {}))
                    c_score = getattr(audit, "confidence_score", 0.95)
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
                elif node_name == "stage2_character":
                    DramaStorageAdapter.persist_stage2(db, drama_id, state)
                    chars = state.characters_engine.get("characters", [])
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
                elif node_name == "stage3_environment_prop":
                    DramaStorageAdapter.persist_stage3(db, drama_id, state)
                    envs = state.environments_and_props.get("environments", [])
                    props = state.environments_and_props.get("props", [])
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
                elif node_name == "stage4_outline":
                    DramaStorageAdapter.persist_stage4(db, drama_id, state)
                    motifs = state.audio_bible.leitmotifs if hasattr(state.audio_bible, "leitmotifs") else []
                    EventBus.publish_event(
                        drama_id,
                        "STAGE_PROGRESS",
                        {
                            "stage": 4,
                            "stage_name": STAGE_NAME_MAP[4],
                            "journey": "journey_1_literary",
                            "status": "completed",
                            "progress_pct": 60,
                            "summary": {"acts_count": len(state.season_outlines.get("acts", [])), "motifs_count": len(motifs)},
                        },
                    )
                elif node_name == "stage5_screenplay":
                    DramaStorageAdapter.persist_stage5(db, drama_id, state)
                    comp_cnt = len(state.completed_screenplays)
                    tot = state.total_episodes
                    pct = 60 + int(25 * (comp_cnt / max(tot, 1)))
                    latest_ep = max(state.completed_screenplays.keys(), default=1)
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
                elif node_name == "gatekeeper":
                    DramaStorageAdapter.persist_stage5(db, drama_id, state)
                    _update_drama_pipeline_status(db, drama_id, "running" if auto_proceed_to_visual else "paused_hitl", lock_status=1)
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
                elif node_name == "stage6_asset_truth":
                    DramaStorageAdapter.persist_stage6(db, drama_id, state)
                    EventBus.publish_event(
                        drama_id,
                        "EPISODE_VISUAL_STARTED",
                        {
                            "stage": 6,
                            "stage_name": STAGE_NAME_MAP[6],
                            "journey": "journey_2_visual_audio",
                            "episode_num": state.current_visual_episode,
                            "status": "started",
                        },
                    )
                elif node_name == "stage7_storyboard_srt":
                    DramaStorageAdapter.persist_stage7(db, drama_id, state)
                    EventBus.publish_event(
                        drama_id,
                        "STAGE_PROGRESS",
                        {
                            "stage": 7,
                            "stage_name": STAGE_NAME_MAP[7],
                            "journey": "journey_2_visual_audio",
                            "episode_num": state.current_visual_episode,
                            "status": "completed",
                        },
                    )
                elif node_name == "stage8_audio_mastering":
                    DramaStorageAdapter.persist_stage8(db, drama_id, state)
                    curr_ep = state.current_visual_episode
                    tot_eps = state.total_episodes
                    pct = 85 + int(15 * (curr_ep / max(tot_eps, 1)))
                    EventBus.publish_event(
                        drama_id,
                        "EPISODE_VISUAL_COMPLETED",
                        {
                            "stage": 8,
                            "stage_name": STAGE_NAME_MAP[8],
                            "journey": state.journey,
                            "episode_num": curr_ep,
                            "total_episodes": tot_eps,
                            "progress_pct": pct,
                            "status": "completed",
                        },
                    )

        # 4. 检查最终状态
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
        elif not auto_proceed_to_visual and state.literary_journey_locked:
            _update_drama_pipeline_status(db, drama_id, "paused_hitl")

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
) -> None:
    """唤醒处于门禁暂停状态的两程九阶工作流并进入第二程视听工程。"""
    try:
        _update_drama_pipeline_status(db, drama_id, "running")
        state = DramaStorageAdapter.load_state(db, drama_id)

        if feedback:
            state.short_memory_d = f"主创审批反馈: {feedback}"

        thread_id = f"drama_{drama_id}"
        config = {"configurable": {"thread_id": thread_id}}

        # 无 interrupt 编译，允许第二程持续滚动至完成
        graph = build_industrial_master_graph(checkpointer=GLOBAL_GRAPH_CHECKPOINTER, interrupt_after=None)

        # 检查点容错：优先从内存快照唤醒；若进程重启快照丢失，直接由 DB 重构的主状态接续执行
        resume_input = None
        has_active_checkpoint = False
        if hasattr(GLOBAL_GRAPH_CHECKPOINTER, "get_tuple"):
            try:
                cp_tuple = GLOBAL_GRAPH_CHECKPOINTER.get_tuple(config)
                if cp_tuple and cp_tuple.checkpoint:
                    has_active_checkpoint = True
            except Exception:
                has_active_checkpoint = False

        if not has_active_checkpoint:
            state.journey = "journey_2_visual_audio"
            state.literary_journey_locked = True
            state.current_stage = 6
            state.current_visual_episode = 1
            resume_input = state

        EventBus.publish_event(
            drama_id,
            "STAGE_PROGRESS",
            {
                "stage": 6,
                "stage_name": "唤醒第二程视听分镜工程",
                "journey": "journey_2_visual_audio",
                "status": "resumed",
                "progress_pct": 85,
            },
        )

        # 唤醒 LangGraph 流
        for update in graph.stream(resume_input, config=config, stream_mode="updates"):
            for node_name, fields in update.items():
                for k, v in fields.items():
                    if hasattr(state, k):
                        setattr(state, k, v)

                if node_name == "stage6_asset_truth":
                    EventBus.publish_event(
                        drama_id,
                        "EPISODE_VISUAL_STARTED",
                        {
                            "stage": 6,
                            "stage_name": STAGE_NAME_MAP[6],
                            "journey": "journey_2_visual_audio",
                            "episode_num": state.current_visual_episode,
                            "status": "started",
                        },
                    )
                elif node_name == "stage7_storyboard_srt":
                    EventBus.publish_event(
                        drama_id,
                        "STAGE_PROGRESS",
                        {
                            "stage": 7,
                            "stage_name": STAGE_NAME_MAP[7],
                            "journey": "journey_2_visual_audio",
                            "episode_num": state.current_visual_episode,
                            "status": "completed",
                        },
                    )
                elif node_name == "stage8_audio_mastering":
                    DramaStorageAdapter.persist_visual_journey(db, state)
                    curr_ep = state.current_visual_episode
                    tot_eps = state.total_episodes
                    pct = 85 + int(15 * (curr_ep / max(tot_eps, 1)))
                    EventBus.publish_event(
                        drama_id,
                        "EPISODE_VISUAL_COMPLETED",
                        {
                            "stage": 8,
                            "stage_name": STAGE_NAME_MAP[8],
                            "journey": state.journey,
                            "episode_num": curr_ep,
                            "total_episodes": tot_eps,
                            "progress_pct": pct,
                            "status": "completed",
                        },
                    )

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
            )


def resume_two_journey_pipeline_async(
    drama_id: int,
    approved: bool = True,
    feedback: str | None = None,
    db: Session | None = None,
) -> None:
    """唤醒处于门禁暂停状态的两程九阶工作流并进入第二程视听工程。"""
    if db is not None:
        _execute_resume_two_journey_pipeline(
            db=db,
            drama_id=drama_id,
            approved=approved,
            feedback=feedback,
        )
    else:
        with session_scope() as db_session:
            _execute_resume_two_journey_pipeline(
                db=db_session,
                drama_id=drama_id,
                approved=approved,
                feedback=feedback,
            )


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
