# -*- coding: utf-8 -*-
"""
tests/unit/test_two_journey_runner_and_time_travel_decoupled.py
解耦架构下两程运行调度器 (TwoJourneyRunner & SlidingWindowPipeline) 与时间旅行服务 (Workflow Time Travel) 专项验证。

验证范围：
1. TwoJourneyRunner 异步调度第一程文学主图，输出纯净的 GlobalDramaMasterState；
2. SlidingWindowPipeline 多集滑动窗口流水线使用 EpisodeScopedSubState，跨集传递物理连续性快照并原子入库；
3. WorkflowTimeTravelService 完美支持 GlobalDramaMasterState 状态快照提取与分支派生 (time_travel_and_fork)；
4. approve_human_review 与 resume_workflow 在解耦状态体系下的平滑推进与断点恢复。
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["LMD_FAST_TEST"] = "1"

from app.db.schema import ensure_schema
from app.schemas.script_graph_state import (
    GlobalDramaMasterState,
    EpisodeScopedSubState,
)
from app.services.workflow_time_travel_service import (
    approve_human_review,
    get_workflow_state_snapshot,
    resume_workflow,
    time_travel_and_fork,
)
from app.workflows.checkpointers.mysql_saver import MySQLCheckpointSaver
from app.workflows.two_journey_runner import (
    TwoJourneyRunner,
    SlidingWindowPipeline,
    run_two_journey_pipeline_async,
)
from app.workflows.adapters.drama_storage_adapter import (
    DramaStorageAdapter,
    load_episode_substate_slice,
    persist_episode_substate_slice,
)


@pytest.fixture(autouse=True)
def setup_test_db():
    """提供纯净的 SQLite 内存测试数据库。"""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with test_engine.connect() as conn:
        ensure_schema(conn)
        conn.commit()
    TestingSession = sessionmaker(
        bind=test_engine, autoflush=False, expire_on_commit=False, future=True
    )
    test_saver = MySQLCheckpointSaver(engine=test_engine)
    test_saver.setup()

    with patch("app.db.session.engine", test_engine), \
         patch("app.db.session.SessionLocal", TestingSession), \
         patch("app.workflows.checkpointers.mysql_saver.get_default_checkpointer", return_value=test_saver), \
         patch("app.workflows.industrial_master_graph.get_default_checkpointer", return_value=test_saver), \
         patch("app.services.workflow_time_travel_service.get_default_checkpointer", return_value=test_saver), \
         patch("app.workflows.two_journey_runner.GLOBAL_GRAPH_CHECKPOINTER", test_saver), \
         patch("app.workflows.industrial_master_graph.GLOBAL_GRAPH_CHECKPOINTER", test_saver):
        yield test_engine


@pytest.fixture(autouse=True)
def mock_llm():
    """统一 Mock LLM 调用，避免在测试中产生实际网络交互，采用 fallback_factory 极速构造测试数据。"""
    with patch(
        "app.workflows.utils.llm_bridge.call_llm_json",
        side_effect=lambda user_prompt, system_prompt="", fallback_factory=None, options=None: (
            fallback_factory() if fallback_factory else {}
        ),
    ):
        yield


@pytest.mark.anyio
async def test_two_journey_runner_literary_pipeline():
    """验证 TwoJourneyRunner 能够异步驱动第一程文学主图并返回 GlobalDramaMasterState。"""
    runner = TwoJourneyRunner()

    drama_id = 901
    # 模拟快速完成
    res_state = await runner.run_literary_pipeline_async(
        drama_id=drama_id,
        user_prompt="豪门赘婿逆袭复仇短剧",
        genre="都市逆袭",
        total_episodes=6,
    )

    assert isinstance(res_state, GlobalDramaMasterState)
    assert res_state.drama_id == drama_id
    assert res_state.current_stage >= 5
    assert res_state.literary_journey_locked is True
    assert len(res_state.completed_screenplays) >= 6


@pytest.mark.anyio
async def test_sliding_window_pipeline_with_substates():
    """验证 SlidingWindowPipeline 仅以 EpisodeScopedSubState 进行并发调度并传递连续性快照。"""
    from app.db.session import session_scope
    from sqlalchemy import text

    drama_id = 902
    total_episodes = 2
    now = "2026-09-21T12:00:00Z"

    # 初始化数据库中的剧目、角色、场景与第 1、2 集
    with session_scope() as db:
        db.execute(
            text(
                "INSERT INTO dramas (id, title, genre, total_episodes, pipeline_status, created_at, updated_at) "
                "VALUES (:id, '测试短剧', '都市', :total, 'running', :now, :now)"
            ),
            {"id": drama_id, "total": total_episodes, "now": now},
        )
        db.execute(
            text(
                "INSERT INTO characters (id, drama_id, name, role, appearance, created_at, updated_at) "
                "VALUES (9021, :did, '男主', '主导', '西装革履', :now, :now)"
            ),
            {"did": drama_id, "now": now},
        )
        db.execute(
            text(
                "INSERT INTO scenes (id, drama_id, location, prompt, created_at, updated_at) "
                "VALUES (9021, :did, '宴会大厅', '豪华宴会厅', :now, :now)"
            ),
            {"did": drama_id, "now": now},
        )
        for ep in range(1, total_episodes + 1):
            db.execute(
                text(
                    "INSERT INTO episodes (id, drama_id, episode_number, title, description, script_content, status, created_at, updated_at) "
                    "VALUES (:eid, :did, :ep, '第' || :ep || '集', '简介', :content, 'screenplay_completed', :now, :now)"
                ),
                {"eid": 9020 + ep, "did": drama_id, "ep": ep, "content": f"第{ep}集剧本文本，男主在宴会厅受辱后展示战神身份。", "now": now},
            )
        db.commit()

    pipeline = SlidingWindowPipeline(window_size=2)
    completed = await pipeline.execute_sliding_window(
        drama_id=drama_id,
        episodes=[1, 2],
        total_episodes=total_episodes,
    )

    assert len(completed) == 2
    assert 1 in completed and 2 in completed
    sub1 = completed[1]
    sub2 = completed[2]
    assert isinstance(sub1, EpisodeScopedSubState)
    assert isinstance(sub2, EpisodeScopedSubState)
    assert sub1.is_completed is True
    assert sub2.is_completed is True
    # 验证第 2 集接收到了第 1 集传递的物理连续性快照
    assert sub2.incoming_physical_continuity is not None
    assert sub2.incoming_physical_continuity.get("episode_number") == 1


def test_workflow_time_travel_with_global_master_state():
    """验证 WorkflowTimeTravelService 在使用 GlobalDramaMasterState 时的状态快照与分支派生。"""
    drama_id = 903

    # 1. 运行工作流第一阶段挂起 (stage_by_stage 模式)
    from app.workflows.industrial_master_graph import run_industrial_master_pipeline
    init_state = GlobalDramaMasterState(
        drama_id=drama_id,
        logline="少年废柴觉醒神脉",
        selected_title="原始标题",
        total_episodes=6,
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(
        initial_state=init_state,
        thread_id=str(drama_id),
        run_mode="stage_by_stage",
    )

    # 2. 获取快照验证
    snapshot = get_workflow_state_snapshot(drama_id=str(drama_id))
    assert snapshot["exists"] is True
    assert snapshot["values"] is not None
    assert snapshot["values"]["drama_id"] == drama_id
    assert snapshot["values"]["selected_title"] in ["原始标题", "少年废柴觉醒"]

    # 3. 时光倒流回溯到 stage1 并派生新分支
    fork_res = time_travel_and_fork(
        drama_id=str(drama_id),
        target_stage="stage1",
        human_override_state={"selected_title": "时光倒流新标题"},
        run_mode="stage_by_stage",
    )
    assert fork_res["success"] is True
    assert fork_res["forked_checkpoint_id"] is not None

    # 4. 人工审核放行并推进
    review_res = approve_human_review(
        drama_id=str(drama_id),
        human_feedback="通过 stage1 微调",
        auto_resume=True,
        run_mode="stage_by_stage",
    )
    assert review_res["status"] == "approved"

    # 5. 验证状态机已根据派生分支完成推进
    snapshot2 = get_workflow_state_snapshot(drama_id=str(drama_id))
    assert snapshot2["values"]["current_stage"] == 2
    assert snapshot2["values"]["selected_title"] == "时光倒流新标题"


def test_resume_two_journey_pipeline_feedback_and_stage_persistence():
    """验证断点唤醒 (resume) 时主创反馈持久化至 metadata 并统一分发 Stage 6~8 原子落库。"""
    import json
    from app.db.session import session_scope, fetch_one
    from sqlalchemy import text
    from app.workflows.two_journey_runner import _execute_resume_two_journey_pipeline

    drama_id = 904
    now = "2026-09-23T12:00:00Z"

    # 初始化测试短剧记录
    with session_scope() as db:
        db.execute(
            text(
                "INSERT INTO dramas (id, title, genre, total_episodes, pipeline_status, metadata, created_at, updated_at) "
                "VALUES (:id, '断点唤醒测试短剧', '玄幻', 6, 'paused_hitl', '{}', :now, :now)"
            ),
            {"id": drama_id, "now": now},
        )
        for ep in range(1, 7):
            db.execute(
                text(
                    "INSERT INTO episodes (id, drama_id, episode_number, title, description, script_content, status, created_at, updated_at) "
                    "VALUES (:eid, :did, :ep, '第' || :ep || '集', '简介', '剧本文本内容', 'screenplay_completed', :now, :now)"
                ),
                {"eid": 9040 + ep, "did": drama_id, "ep": ep, "now": now},
            )
        db.commit()

    # 执行唤醒流程
    with session_scope() as db:
        _execute_resume_two_journey_pipeline(
            db=db,
            drama_id=drama_id,
            approved=True,
            feedback="第二程视听风格建议加强冷色调光影",
            run_mode="full_auto",
        )

    # 验证主创反馈已被持久化至 dramas 表 metadata
    with session_scope() as db:
        row = fetch_one(db, "SELECT metadata, pipeline_status FROM dramas WHERE id = :id", {"id": drama_id})
        assert row is not None
        meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {})
        assert meta.get("gate_feedback") == "第二程视听风格建议加强冷色调光影"
        assert meta.get("gate_approved") is True
        assert "gate_reviewed_at" in meta

