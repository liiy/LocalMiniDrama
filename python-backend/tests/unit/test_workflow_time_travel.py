# -*- coding: utf-8 -*-
"""
tests/unit/test_workflow_time_travel.py
工业级两程九阶工作流持久化、执行控制模式与时光倒流 (Time Travel & Forking) 单元测试。

验证范围：
1. MySQLCheckpointSaver 适配器与 drama_checkpoint_index 表的初始化与快照存取；
2. 三种执行控制模式 (stage_by_stage, two_journey, full_auto) 的中断行为与节点挂起；
3. 时光倒流 (Strategy A: Time Travel & Forking) 分支派生与旧分支逻辑作废；
4. 人工审核放行 (approve_human_review) 与状态微调注入；
5. 工作流控制与时光倒流 REST API 端点验证。
"""
from __future__ import annotations

import os
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["LMD_FAST_TEST"] = "1"

from app.db.schema import ensure_schema
from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.services.checkpoint_index_service import (
    get_latest_active_checkpoint,
    list_drama_checkpoints,
    record_checkpoint_index,
)
from app.services.workflow_time_travel_service import (
    approve_human_review,
    get_workflow_state_snapshot,
    resume_workflow,
    time_travel_and_fork,
)
from app.workflows.checkpointers.mysql_saver import MySQLCheckpointSaver
from app.workflows.industrial_master_graph import (
    build_industrial_master_graph,
    get_interrupt_after_nodes,
    run_industrial_master_pipeline,
)
from app.main import app


@pytest.fixture(autouse=True)
def setup_test_db():
    """提供干净的 SQLite 内存测试数据库，并注入到 app.db.session 和 checkpointer。"""
    test_engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with test_engine.connect() as conn:
        ensure_schema(conn)
        conn.commit()

    TestSessionLocal = sessionmaker(
        bind=test_engine, autoflush=False, expire_on_commit=False, future=True
    )

    test_saver = MySQLCheckpointSaver(engine=test_engine)
    test_saver.setup()

    with patch("app.db.session.engine", test_engine), \
         patch("app.db.session.SessionLocal", TestSessionLocal), \
         patch("app.workflows.checkpointers.mysql_saver.get_default_checkpointer", return_value=test_saver), \
         patch("app.workflows.industrial_master_graph.get_default_checkpointer", return_value=test_saver), \
         patch("app.services.workflow_time_travel_service.get_default_checkpointer", return_value=test_saver), \
         patch("app.workflows.industrial_master_graph.GLOBAL_GRAPH_CHECKPOINTER", test_saver):
        yield test_engine


@pytest.fixture
def mock_llm():
    """统一 Mock LLM 调用，避免在测试中产生实际网络交互，采用 fallback_factory 极速构造测试数据。"""
    with patch(
        "app.workflows.utils.llm_bridge.call_llm_json",
        side_effect=lambda user_prompt, system_prompt="", fallback_factory=None, options=None: (
            fallback_factory() if fallback_factory else {}
        ),
    ):
        yield


# =========================================================================
# 1. 测试 MySQLCheckpointSaver 与 drama_checkpoint_index 持久化基础
# =========================================================================

def test_checkpointer_setup_and_basic_persistence(setup_test_db):
    """测试 CheckpointSaver 初始化与表结构自动建立，以及基本的读写操作。"""
    engine = setup_test_db
    saver = MySQLCheckpointSaver(engine=engine)
    saver.setup()

    # 验证表是否存在
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "workflow_checkpoints" in table_names
        assert "workflow_checkpoint_blobs" in table_names
        assert "workflow_checkpoint_writes" in table_names
        assert "drama_checkpoint_index" in table_names

    # 验证 CheckpointSaver 基本读写
    config = {"configurable": {"thread_id": "drama_test_001"}}
    checkpoint = {
        "v": 1,
        "ts": "2026-09-19T00:00:00Z",
        "id": "1ef00000-0000-0000-0000-000000000001",
        "channel_values": {"current_stage": 1, "selected_title": "测试短剧"},
        "channel_versions": {"current_stage": 1, "selected_title": 1},
        "versions_seen": {},
    }
    saved_cfg = saver.put(
        config,
        checkpoint,
        metadata={"step": 1},
        new_versions={"current_stage": 1, "selected_title": 1},
    )
    assert saved_cfg["configurable"]["checkpoint_id"] == "1ef00000-0000-0000-0000-000000000001"

    # 读取验证
    loaded = saver.get_tuple(saved_cfg)
    assert loaded is not None
    assert loaded.checkpoint["channel_values"]["selected_title"] == "测试短剧"


def test_checkpoint_index_service_operations(setup_test_db):
    """测试 checkpoint_index_service 的记录、查询、状态标记与分支作废逻辑。"""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        # 1. 记录 stage1 检查点
        ckpt1 = record_checkpoint_index(
            db=db,
            drama_id="drama_idx_test",
            thread_id="drama_idx_test",
            checkpoint_id="ckpt-001",
            stage="stage1",
            step_name="audit_stage1",
            is_ready_for_next=True,
        )
        assert ckpt1 is not None and ckpt1 > 0

        # 2. 记录 stage2 检查点
        ckpt2 = record_checkpoint_index(
            db=db,
            drama_id="drama_idx_test",
            thread_id="drama_idx_test",
            checkpoint_id="ckpt-002",
            parent_checkpoint_id="ckpt-001",
            stage="stage2",
            step_name="audit_stage2",
            is_ready_for_next=True,
        )
        assert ckpt2 is not None and ckpt2 > ckpt1

        # 3. 查询最新活跃检查点
        latest = get_latest_active_checkpoint(db=db, drama_id="drama_idx_test")
        assert latest is not None
        assert latest["checkpoint_id"] == "ckpt-002"

        # 4. 列出活跃检查点
        items = list_drama_checkpoints(db=db, drama_id="drama_idx_test", active_only=True)
        assert len(items) == 2


# =========================================================================
# 2. 测试三种执行控制模式 (stage_by_stage, two_journey, full_auto)
# =========================================================================

def test_execution_mode_interrupt_configurations():
    """验证三种控制模式的 interrupt 节点配置。"""
    s_nodes = get_interrupt_after_nodes("stage_by_stage")
    assert "audit_stage1" in s_nodes
    assert "audit_stage2" in s_nodes
    assert "audit_stage5" in s_nodes
    assert "gatekeeper" in s_nodes
    assert "stage8_audio_mastering" in s_nodes

    t_nodes = get_interrupt_after_nodes("two_journey")
    assert "gatekeeper" in t_nodes
    assert "stage8_audio_mastering" in t_nodes
    assert "audit_stage1" not in t_nodes

    f_nodes = get_interrupt_after_nodes("full_auto")
    assert f_nodes is None


def test_stage_by_stage_mode_pauses_at_stage1(mock_llm):
    """测试 stage_by_stage 模式在 Stage 1 审计后精准挂起等待人工审核。"""
    drama_id = 1001
    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="单步精细测试剧",
        run_mode="stage_by_stage",
    )

    # 运行工作流，预期会在 audit_stage1 挂起
    res_state = run_industrial_master_pipeline(
        initial_state=initial_state,
        thread_id=str(drama_id),
    )

    # 检查状态：当前阶段已完成 Stage 1，但尚未执行 Stage 2
    assert res_state.current_stage == 1
    assert res_state.selected_title is not None

    # 查询状态快照
    snapshot = get_workflow_state_snapshot(drama_id=str(drama_id))
    assert snapshot["exists"] is True
    assert snapshot["is_waiting_review"] is True
    # 下一个等待执行的节点应为 stage2_character
    assert "stage2_character" in snapshot["next_nodes"]


def test_two_journey_mode_pauses_at_gatekeeper(mock_llm):
    """测试 two_journey 模式下第一程自动连贯执行至 Gatekeeper 总门禁处挂起。"""
    drama_id = 1002
    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="双程总控测试剧",
        run_mode="two_journey",
    )

    res_state = run_industrial_master_pipeline(
        initial_state=initial_state,
        thread_id=str(drama_id),
    )

    # 第一程完成 2 集剧本编写，并在 Gatekeeper 挂起，literary_journey_locked 已由 gatekeeper 锁定
    assert len(res_state.completed_screenplays) == 2
    assert res_state.literary_journey_locked is True

    snapshot = get_workflow_state_snapshot(drama_id=str(drama_id))
    assert snapshot["exists"] is True
    assert snapshot["is_waiting_review"] is True
    assert "stage6_asset_truth" in snapshot["next_nodes"]


# =========================================================================
# 3. 测试时光倒流 (Strategy A: Time Travel & Forking) 与分支派生
# =========================================================================

def test_time_travel_and_forking(mock_llm):
    """测试时光倒流回溯 Stage 1，注入人工修改并派生新分支。"""
    drama_id = 1003
    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="原始标题",
        run_mode="stage_by_stage",
    )

    # 1. 运行到 Stage 1 挂起
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=str(drama_id))

    # 2. 执行时光倒流与分支派生：修改标题为 "时光倒流新标题"
    fork_result = time_travel_and_fork(
        drama_id=str(drama_id),
        target_stage="stage1",
        human_override_state={"selected_title": "时光倒流新标题"},
        run_mode="stage_by_stage",
    )

    assert fork_result["forked_checkpoint_id"] is not None
    assert fork_result["parent_checkpoint_id"] is not None

    # 3. 验证当前状态快照已被更新
    snapshot = get_workflow_state_snapshot(drama_id=str(drama_id))
    assert snapshot["values"]["selected_title"] == "时光倒流新标题"

    # 4. 审核放行并推进到 Stage 2
    approve_res = approve_human_review(
        drama_id=str(drama_id),
        auto_resume=True,
        run_mode="stage_by_stage",
    )
    assert approve_res["status"] == "approved"

    # 验证已推进到 Stage 2 (由于 stage_by_stage 模式，会在 audit_stage2 挂起)
    snapshot2 = get_workflow_state_snapshot(drama_id=str(drama_id))
    assert snapshot2["values"]["current_stage"] == 2
    assert "stage3_environment_prop" in snapshot2["next_nodes"]


# =========================================================================
# 4. 测试工作流控制与时光倒流 REST API
# =========================================================================

def test_workflow_control_api_endpoints(mock_llm):
    """测试工作流 REST API 端点功能完整性。"""
    client = TestClient(app)
    drama_id = 1004

    # 1. 初始化并运行至 Stage 1 挂起点
    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="API 测试剧目",
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=str(drama_id))

    # 2. GET /api/v1/dramas/{drama_id}/workflow/status
    res_status = client.get(f"/api/v1/dramas/{drama_id}/workflow/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["success"] is True
    assert status_data["data"]["drama_id"] == str(drama_id)
    assert status_data["data"]["is_waiting_review"] is True
    assert status_data["data"]["current_stage"] == 1

    # 3. GET /api/v1/dramas/{drama_id}/workflow/checkpoints
    res_ckpts = client.get(f"/api/v1/dramas/{drama_id}/workflow/checkpoints")
    assert res_ckpts.status_code == 200
    ckpts_data = res_ckpts.json()
    assert ckpts_data["success"] is True
    assert len(ckpts_data["data"]) >= 1

    # 4. POST /api/v1/dramas/{drama_id}/workflow/time-travel
    res_tt = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/time-travel",
        json={
            "target_stage": "stage1",
            "human_override_state": {"selected_title": "通过API时光倒流修改标题"},
            "auto_resume": False,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_tt.status_code == 200
    tt_data = res_tt.json()
    assert tt_data["success"] is True
    assert tt_data["data"]["parent_checkpoint_id"] is not None

    # 5. POST /api/v1/dramas/{drama_id}/workflow/approve (放行并推进)
    res_appr = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/approve",
        json={
            "human_feedback": "人设与大纲审核通过，同意推进至世界观阶",
            "auto_resume": True,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_appr.status_code == 200
    appr_data = res_appr.json()
    assert appr_data["success"] is True
    assert appr_data["data"]["status"] == "approved"

    # 6. POST /api/v1/dramas/{drama_id}/workflow/resume
    res_resm = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/resume",
        json={"run_mode": "stage_by_stage"},
    )
    assert res_resm.status_code == 200
    resm_data = res_resm.json()
    assert resm_data["success"] is True


# =========================================================================
# 5. 测试方案第七节 10 个专用 REST API 端点
# =========================================================================

def test_pending_review_and_dual_prefix_api(mock_llm):
    """测试 7.2.1 GET /pending-review 待审核列表查询及 /api 与 /api/v1 双前缀兼容。"""
    client = TestClient(app)
    drama_id = 2001

    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="待审核端点测试剧",
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=str(drama_id))

    # 测试 /api/v1 前缀
    res_v1 = client.get(f"/api/v1/dramas/{drama_id}/workflow/pending-review")
    assert res_v1.status_code == 200
    data_v1 = res_v1.json()
    assert data_v1["success"] is True
    assert data_v1["data"]["is_waiting_review"] is True
    assert data_v1["data"]["current_stage"] == 1
    assert "pending_items" in data_v1["data"]

    # 测试 /api 前缀兼容性
    res_compat = client.get(f"/api/dramas/{drama_id}/workflow/pending-review")
    assert res_compat.status_code == 200
    assert res_compat.json()["success"] is True


def test_stage5_wave_control_apis(mock_llm):
    """测试 7.2.2/7.2.3/7.2.4 Stage 5 分波次审核、更新放行与重跑接口。"""
    client = TestClient(app)
    drama_id = 2002

    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="分波次控制测试剧",
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=str(drama_id))

    # 1. 测试 7.2.2 POST /stage5/wave/approve
    res_appr = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/stage5/wave/approve",
        json={"wave_number": 1, "auto_resume": False, "run_mode": "stage_by_stage"},
    )
    assert res_appr.status_code == 200
    assert res_appr.json()["success"] is True
    assert res_appr.json()["data"]["wave_number"] == 1

    # 2. 测试 7.2.3 POST /stage5/wave/update-and-resume
    res_update = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/stage5/wave/update-and-resume",
        json={
            "wave_number": 1,
            "modified_screenplays": [{"episode_number": 1, "content": "人工微调后的第一集剧本"}],
            "auto_resume": False,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_update.status_code == 200
    assert res_update.json()["success"] is True
    assert res_update.json()["data"]["forked_checkpoint_id"] is not None

    # 3. 测试 7.2.4 POST /stage5/wave/rerun
    res_rerun = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/stage5/wave/rerun",
        json={
            "wave_number": 1,
            "human_instructions": "重写第一波次剧本，增加反转冲突",
            "auto_resume": False,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_rerun.status_code == 200
    assert res_rerun.json()["success"] is True
    assert res_rerun.json()["data"]["forked_checkpoint_id"] is not None


def test_episodes_control_apis(mock_llm):
    """测试 7.2.5/7.2.6/7.2.7 单集剧本审核、更新放行与时光倒流重跑接口。"""
    client = TestClient(app)
    drama_id = 2003

    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=3,
        selected_title="单集控制测试剧",
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=str(drama_id))

    # 1. 测试 7.2.5 POST /episodes/{ep}/approve
    res_appr = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/episodes/1/approve",
        json={"auto_resume": False, "run_mode": "stage_by_stage"},
    )
    assert res_appr.status_code == 200
    assert res_appr.json()["success"] is True
    assert res_appr.json()["data"]["episode_number"] == 1

    # 2. 测试 7.2.6 POST /episodes/{ep}/update-and-resume
    res_update = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/episodes/1/update-and-resume",
        json={
            "modified_screenplay": {
                "episode_number": 1,
                "title": "第1集 命运的齿轮",
                "content": "修改后的剧本内容",
            },
            "auto_resume": False,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_update.status_code == 200
    assert res_update.json()["success"] is True
    assert res_update.json()["data"]["forked_checkpoint_id"] is not None

    # 3. 测试 7.2.7 POST /episodes/{ep}/rerun
    res_rerun = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/episodes/1/rerun",
        json={
            "human_instructions": "加强第1集的高潮冲突",
            "auto_resume": False,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_rerun.status_code == 200
    assert res_rerun.json()["success"] is True
    assert res_rerun.json()["data"]["target_episode"] == 1


def test_rerun_stage_pause_and_retry_apis(mock_llm):
    """测试 7.2.9 POST /rerun-stage 与 7.2.10 POST /pause 和 POST /retry 接口。"""
    client = TestClient(app)
    drama_id = 2004

    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="重跑与暂停测试剧",
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=str(drama_id))

    # 1. 7.2.9 POST /rerun-stage
    res_stage = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/rerun-stage",
        json={
            "target_stage": "stage1",
            "human_feedback": "大纲不满意，要求重新构思",
            "auto_resume": False,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_stage.status_code == 200
    assert res_stage.json()["success"] is True
    assert res_stage.json()["data"]["target_stage"] == "stage1"

    # 2. 7.2.10 POST /pause
    res_pause = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/pause",
        json={"reason": "运维人员手动紧急暂停"},
    )
    assert res_pause.status_code == 200
    assert res_pause.json()["success"] is True
    assert res_pause.json()["data"]["status"] == "pause_signaled"

    # 3. 7.2.10 POST /retry
    res_retry = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/retry",
        json={"run_mode": "stage_by_stage"},
    )
    assert res_retry.status_code == 200
    assert res_retry.json()["success"] is True
    assert res_retry.json()["data"]["status"] == "resumed"


# =========================================================================
# 6. 测试分布式锁与级联失效 (Section 4.2 & 8.1)
# =========================================================================

def test_workflow_lock_service_and_pause_flag():
    """测试 workflow_lock_service 的获取/释放锁、上下文管理器与暂停标志。"""
    from app.services.workflow_lock_service import (
        acquire_workflow_lock,
        release_workflow_lock,
        workflow_lock_context,
        set_pause_flag,
        clear_pause_flag,
        is_pause_flag_set,
    )

    test_drama_id = "lock_test_999"

    # 1. 分布式锁 acquire / release
    acquired, token = acquire_workflow_lock(test_drama_id, ttl_seconds=10)
    assert acquired is True
    assert token is not None

    # 重复获取应失败
    acquired_dup, _ = acquire_workflow_lock(test_drama_id, ttl_seconds=10)
    assert acquired_dup is False

    # 释放锁
    released = release_workflow_lock(test_drama_id, token)
    assert released is True

    # 2. 上下文管理器
    with workflow_lock_context(test_drama_id, ttl_seconds=10) as (ctx_acquired, ctx_token):
        assert ctx_acquired is True
        assert ctx_token is not None

    # 3. 暂停标志测试
    assert is_pause_flag_set(test_drama_id) is False
    set_pause_flag(test_drama_id, reason="单元测试暂停")
    assert is_pause_flag_set(test_drama_id) is True
    clear_pause_flag(test_drama_id)
    assert is_pause_flag_set(test_drama_id) is False


def test_cascade_invalidation_and_downstream_clearing(setup_test_db):
    """测试 Section 4.2 级联失效逻辑：旧分支业务记录打标 DIRTY_INVALIDATED 及状态字段重置。"""
    from app.db.session import SessionLocal
    from app.services.checkpoint_index_service import cascade_invalidate_downstream_business_records

    engine = setup_test_db
    with SessionLocal() as db:
        # 1. 插入一些测试业务数据到 episodes 与 storyboards 表
        # episodes
        db.execute(
            text(
                "INSERT INTO episodes (drama_id, episode_number, title, script_content, status) "
                "VALUES (:d_id, 1, '第1集', '剧本内容1', 'COMPLETED'), "
                "       (:d_id, 2, '第2集', '剧本内容2', 'COMPLETED')"
            ),
            {"d_id": "test_drama_cascade"},
        )
        # 获取 episodes ID
        ep_rows = db.execute(
            text("SELECT id FROM episodes WHERE drama_id = :d_id ORDER BY episode_number ASC"),
            {"d_id": "test_drama_cascade"},
        ).fetchall()
        ep_id1, ep_id2 = ep_rows[0][0], ep_rows[1][0]

        # storyboards
        db.execute(
            text(
                "INSERT INTO storyboards (episode_id, storyboard_number, status) "
                "VALUES (:ep1, 1, 'COMPLETED'), "
                "       (:ep2, 1, 'COMPLETED')"
            ),
            {"ep1": ep_id1, "ep2": ep_id2},
        )
        db.commit()

        # 2. 执行级联失效：从 Stage 1 开始回溯，所有下游业务记录均应失效
        invalidated_count = cascade_invalidate_downstream_business_records(
            db=db,
            drama_id="test_drama_cascade",
            from_stage="stage1",
            from_episode=None,
        )
        db.commit()
        assert invalidated_count >= 4

        # 3. 检查 episodes 状态
        ep_rows = db.execute(
            text("SELECT status FROM episodes WHERE drama_id = :d_id"),
            {"d_id": "test_drama_cascade"},
        ).fetchall()
        for r in ep_rows:
            assert r[0] == "DIRTY_INVALIDATED"

        # 4. 检查 storyboards 状态
        sb_rows = db.execute(
            text("SELECT status FROM storyboards WHERE episode_id IN (:ep1, :ep2)"),
            {"ep1": ep_id1, "ep2": ep_id2},
        ).fetchall()
        for r in sb_rows:
            assert r[0] == "DIRTY_INVALIDATED"


def test_start_and_gate_confirm_run_mode_param(setup_test_db, monkeypatch):
    """测试 TwoJourneyStartRequest 与 TwoJourneyGateConfirmRequest 支持 run_mode 入参。"""
    from app.api.v1.script_studio import TwoJourneyStartRequest, TwoJourneyGateConfirmRequest, PipelineStartRequest
    from app.main import app

    # 1. 验证 Pydantic 模型接收并正确解析 run_mode
    start_req = TwoJourneyStartRequest(
        user_prompt="测试霸道总裁短剧",
        genre="现代言情",
        total_episodes=10,
        run_mode="stage_by_stage",
    )
    assert start_req.run_mode == "stage_by_stage"

    gate_req = TwoJourneyGateConfirmRequest(
        approved=True,
        feedback="剧本质量优秀，放行视听工程",
        run_mode="stage_by_stage",
    )
    assert gate_req.run_mode == "stage_by_stage"

    pipe_req = PipelineStartRequest(
        user_prompt="测试故事梗概",
        run_mode="two_journey",
    )
    assert pipe_req.run_mode == "two_journey"

    # 2. 验证 API 端点请求与响应正确回显 run_mode
    client = TestClient(app)
    drama_id = 9999

    # Mock 后台任务避免真实启动大模型
    monkeypatch.setattr("app.api.v1.script_studio.run_two_journey_pipeline_async", lambda **kwargs: None)
    monkeypatch.setattr("app.api.v1.script_studio.resume_two_journey_pipeline_async", lambda **kwargs: None)

    # 模拟 drama 存在
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        db.execute(
            text("INSERT INTO dramas (id, title, status, lock_status, pipeline_status) VALUES (:id, 'RunMode测试短剧', 'draft', 0, 'idle')"),
            {"id": drama_id},
        )
        db.commit()

    res = client.post(
        f"/api/v1/script-studio/dramas/{drama_id}/two-journey/start",
        json={
            "user_prompt": "测试短剧提示词",
            "genre": "现代都市",
            "total_episodes": 12,
            "run_mode": "stage_by_stage",
        },
    )
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["success"] is True
    assert res_data["data"]["run_mode"] == "stage_by_stage"

    # 测试 gate-confirm 端点
    res_gate = client.post(
        f"/api/v1/script-studio/dramas/{drama_id}/two-journey/gate-confirm",
        json={
            "approved": True,
            "feedback": "主创已审批通过",
            "run_mode": "stage_by_stage",
        },
    )
    assert res_gate.status_code == 200
    res_gate_data = res_gate.json()
    assert res_gate_data["success"] is True
    assert res_gate_data["data"]["run_mode"] == "stage_by_stage"


def test_rerun_stage2_auto_resume_database_persistence(setup_test_db, mock_llm):
    """验证重跑阶段 2 时，auto_resume=True 会流式执行并将角色资产原子落库至 characters 与 character_stages 业务表。"""
    from app.db.session import SessionLocal

    client = TestClient(app)
    drama_id = 3001

    # 1. 预先在 dramas 表中建立记录
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO dramas (id, title, status, lock_status, pipeline_status) "
                "VALUES (:id, '阶段2落库测试短剧', 'draft', 0, 'idle')"
            ),
            {"id": drama_id},
        )
        db.commit()

    # 2. 运行第一阶段生成基础检查点
    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="阶段2落库测试短剧",
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=f"drama_{drama_id}")

    # 3. 发起阶段 2 重跑 (POST /rerun-stage with auto_resume=True)
    res_stage2 = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/rerun-stage",
        json={
            "target_stage": 2,
            "human_guidance": "增加一个反派角色",
            "auto_resume": True,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_stage2.status_code == 200
    stage2_data = res_stage2.json()
    assert stage2_data["success"] is True

    # 4. 验证业务表 characters 与 character_stages 是否已有落库数据
    with SessionLocal() as db:
        char_rows = db.execute(
            text("SELECT id, drama_id, name, role FROM characters WHERE drama_id = :drama_id"),
            {"drama_id": drama_id},
        ).fetchall()
        assert len(char_rows) > 0, "重跑阶段2后，characters 业务表中应有落库的角色数据"

        # 检查 character_stages 阶段表
        stage_rows = db.execute(
            text("SELECT id, character_id, stage_name FROM character_stages WHERE drama_id = :drama_id"),
            {"drama_id": drama_id},
        ).fetchall()
        assert len(stage_rows) > 0, "重跑阶段2后，character_stages 业务表中应有落库的角色阶段数据"


def test_stage_explicit_approve_and_gatekeeper_confirm_resilience(setup_test_db, mock_llm):
    """测试阶段显式放行 (POST /stages/{stage}/approve) 与总门禁确认在多种入参形态下的防御鲁棒性。
    
    验证范围：
    1. POST /gatekeeper/confirm 在未达 Stage 5 时被拦截并返回 400；
    2. POST /stages/1/approve 传递 comment 字段正常放行 (不报 AttributeError)；
    3. POST /stages/2/approve 传递空 JSON {} 正常放行；
    4. POST /stages/3/approve 传递额外未知字段 (extra="allow") 正常放行；
    5. POST /resume 兼容 comment 别名与阶段分流。
    """
    client = TestClient(app)
    drama_id = 4001

    from app.db.session import SessionLocal
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO dramas (id, title, status, lock_status, pipeline_status, current_stage) "
                "VALUES (:id, '防御鲁棒性测试剧', 'in_progress', 0, 'running', 1)"
            ),
            {"id": drama_id},
        )
        session.commit()

    initial_state = IndustrialDramaMasterState(
        drama_id=drama_id,
        total_episodes=2,
        selected_title="防御鲁棒性测试剧",
        run_mode="stage_by_stage",
    )
    run_industrial_master_pipeline(initial_state=initial_state, thread_id=str(drama_id))

    # 1. 验证在 Stage 1~4 未达到 Stage 5 时调用 POST /gatekeeper/confirm 会被严格拦截并返回 400
    res_gate = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/gatekeeper/confirm",
        json={"comment": "尝试提前定稿", "operator": "editor"},
    )
    assert res_gate.status_code == 400, res_gate.text
    gate_err = res_gate.json().get("error", {}).get("message", "") or res_gate.json().get("detail", "")
    assert "尚未完成" in gate_err or "尚未创作完成" in gate_err or "不能执行" in gate_err

    # 2. 验证 POST /stages/1/approve 传递 comment 字段正常放行 (不报 AttributeError)
    res_appr1 = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/stages/1/approve",
        json={"comment": "Stage 1 概念策划审核通过", "auto_resume": False, "run_mode": "stage_by_stage"},
    )
    assert res_appr1.status_code == 200, res_appr1.text
    data1 = res_appr1.json()
    assert data1["success"] is True
    assert data1["data"]["stage_approvals"]["stage1"] is True

    # 3. 验证 POST /stages/2/approve 传递空 JSON {} 正常放行 (防御入参缺省)
    res_appr2 = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/stages/2/approve",
        json={},
    )
    assert res_appr2.status_code == 200, res_appr2.text
    data2 = res_appr2.json()
    assert data2["success"] is True
    assert data2["data"]["stage_approvals"]["stage2"] is True

    # 4. 验证 POST /stages/3/approve 传递额外未知字段 (extra="allow") 正常放行
    res_appr3 = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/stages/3/approve",
        json={
            "feedback": "场景道具合格",
            "approved": True,
            "operator": "lead_writer",
            "unknown_extra_param": "foo_bar",
            "auto_resume": False,
            "run_mode": "stage_by_stage",
        },
    )
    assert res_appr3.status_code == 200, res_appr3.text
    data3 = res_appr3.json()
    assert data3["success"] is True
    assert data3["data"]["stage_approvals"]["stage3"] is True

    # 5. 验证 POST /resume 传入 comment 字段安全执行
    res_resume = client.post(
        f"/api/v1/dramas/{drama_id}/workflow/resume",
        json={"stage": 4, "comment": "Stage 4 大纲放行", "run_mode": "stage_by_stage"},
    )
    assert res_resume.status_code == 200, res_resume.text
    assert res_resume.json()["success"] is True


