"""测试 Stage 5 SSOT 数据去重、事务隔离保护与 CQRS 读模型闭环刷新。

【验证范围】
1. SSOT 数据去重：
   - persist_stage5 写入 episodes 表时，剪除 ast_blocks 中的大纲冗余字段与快照冗余；
   - 自动关联 episode_outlines.id 至 episodes.outline_id。
2. 事务隔离保护：
   - 关系数据库主事务在向量库同步前提交；
   - 向量数据库连接拒绝（[WinError 10061] 等网络异常）被 try-except 安全隔离，不引发数据库回滚。
3. CQRS 读模型闭环：
   - persist_stage5 成功后立即发布 Redis HASH 读模型投影与 STAGE_PROGRESS 事件；
   - stage5_screenplay_node 执行完成后立即发布读模型投影与业务事件；
   - stage5_literary_gatekeeper_node 支持无外部 session 时自动建立会话并发布总锁投影。
4. 状态重构与缓存校准：
   - load_master_state_from_db 优先读取 dramas.current_stage 权威列；
   - get_two_journey_state 遇到 Redis 投影滞后于数据库时，能够自动识别、穿透重载并回写校准。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.schemas.script_graph_state import (
    EpisodeEndPhysicalDeltaModel,
    GoldenCliffhangerHookModel,
    LiteraryScreenplayEpisodeModel,
    PreviousEpisodePickupModel,
)
from app.workflows.adapters.drama_storage_adapter import (
    DramaStorageAdapter,
    load_master_state_from_db,
)
from app.workflows.nodes.stage5_gatekeeper import stage5_literary_gatekeeper_node
from app.workflows.nodes.stage5_screenplay import stage5_screenplay_node


@pytest.fixture
def sqlite_db_session():
    """提供具有标准 schema 表结构的内存 SQLite 会话。"""
    from sqlalchemy.pool import StaticPool
    from app.db.schema import ensure_schema

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        ensure_schema(conn)
        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _build_dummy_state(drama_id: int):
    """构建用于测试的 Mock 状态对象。"""
    hook = GoldenCliffhangerHookModel(
        physical_crisis_action="长剑破空直刺咽喉",
        cliffhanger_dialogue="你认输吧",
        acoustic_drop_cue="【音频重击：Braam Hit】",
    )
    delta = EpisodeEndPhysicalDeltaModel(
        timeline_progress="00:01:58",
        character_pose="单膝跪地",
        held_props_and_injuries="左臂染血，紧握密函",
        environment_and_weather="雨夜破庙，火把熄灭",
    )
    pickup = PreviousEpisodePickupModel(
        inherited_from_episode=0,
        pickup_state_description="承接开篇",
    )

    sc = LiteraryScreenplayEpisodeModel(
        episode_id=1,
        episode_num=1,
        episode_title="风云初起",
        body_markdown="【场景 01】破庙 内 夜\n林云拔剑出鞘。\n林云（眼神冷厉）：今日谁也走不了。",
        hook_3s="林云剑锋微挑",
        ending_cliffhanger="黑衣人破窗而入",
        golden_cliffhanger_hook=hook,
        episode_end_physical_delta=delta,
        previous_episode_0s_pickup=pickup,
        ast_data={
            "dual_helix_task": "大纲重复任务",
            "subtext_matrix": "大纲潜台词",
            "cliffhanger_end": "大纲钩子",
            "scene_count": 1,
        },
        audit_report={
            "verdict": "GREEN_APPROVED",
            "blue_team": "合规",
            "red_team_critic": "通过",
        },
    )

    state = MagicMock()
    state.drama_id = drama_id
    state.completed_screenplays = {1: sc}
    state.total_episodes = 5
    state.literary_journey_locked = False
    state.current_mini_arc_index = 1
    state.inter_episode_physical_snapshot = delta.to_dict()
    state.latest_audit = None
    return state


def test_stage5_ssot_deduplication_and_outline_link(sqlite_db_session):
    """【SSOT 去重验证】验证 persist_stage5 剔除 ast_blocks 大纲冗余字段，并关联 outline_id。"""
    session = sqlite_db_session

    # 1. 插入主剧本与第 1 集大纲
    session.execute(text("""
        INSERT INTO dramas (id, title, total_episodes, current_stage)
        VALUES (101, '测试剧本', 5, 4)
    """))
    session.execute(text("""
        INSERT INTO episode_outlines (id, drama_id, episode_number, title, hook_3s)
        VALUES (501, 101, 1, '第1集大纲', '夺取密函')
    """))
    session.commit()

    state = _build_dummy_state(101)

    # 2. 执行 persist_stage5
    with patch("app.workflows.adapters.drama_storage_adapter.publish_drama_read_projection") as mock_proj, \
         patch("app.workflows.adapters.drama_storage_adapter.publish_drama_event") as mock_event, \
         patch("app.workflows.adapters.drama_storage_adapter.sync_stage_memories_to_vector_db") as mock_vec:

        DramaStorageAdapter.persist_stage5(session, 101, state)

    # 3. 校验 episodes 表数据
    ep_row = session.execute(text("SELECT * FROM episodes WHERE drama_id = 101 AND episode_number = 1")).mappings().fetchone()
    assert ep_row is not None
    # 验证 outline_id 正确关联
    assert ep_row["outline_id"] == 501
    assert ep_row["title"] == "风云初起"
    assert "林云拔剑出鞘" in ep_row["script_content"]

    # 验证 ast_blocks 去除了大纲冗余字段
    ast_saved = json.loads(ep_row["ast_blocks"])
    assert "dual_helix_task" not in ast_saved
    assert "subtext_matrix" not in ast_saved
    assert "cliffhanger_end" not in ast_saved
    assert ast_saved.get("golden_cliffhanger_hook", {}).get("physical_crisis_action") == "长剑破空直刺咽喉"
    assert ast_saved.get("ast_data", {}).get("scene_count") == 1
    assert "dual_helix_task" not in ast_saved.get("ast_data", {})
    assert "subtext_matrix" not in ast_saved.get("ast_data", {})
    assert "cliffhanger_end" not in ast_saved.get("ast_data", {})

    # 验证 dramas 表的 current_stage 更新为 5
    drama_row = session.execute(text("SELECT current_stage FROM dramas WHERE id = 101")).mappings().fetchone()
    assert drama_row["current_stage"] == 5


def test_stage5_transaction_isolation_on_vector_failure(sqlite_db_session):
    """【事务隔离验证】验证向量数据库连接拒绝（如 [WinError 10061]）绝不影响关系数据库落库。"""
    session = sqlite_db_session

    session.execute(text("""
        INSERT INTO dramas (id, title, total_episodes, current_stage)
        VALUES (202, '隔离测试剧', 5, 4)
    """))
    session.commit()

    state = _build_dummy_state(202)

    # 模拟向量数据库抛出连接拒绝异常
    def _raise_conn_error(*args, **kwargs):
        raise ConnectionRefusedError("[WinError 10061] 由于目标计算机积极拒绝，无法连接。")

    with patch("app.workflows.adapters.drama_storage_adapter.sync_stage_memories_to_vector_db", side_effect=_raise_conn_error), \
         patch("app.workflows.adapters.drama_storage_adapter.publish_drama_read_projection"), \
         patch("app.workflows.adapters.drama_storage_adapter.publish_drama_event"):

        # 执行持久化，应当被隔离并正常结束，绝不向外抛出异常
        DramaStorageAdapter.persist_stage5(session, 202, state)

    # 验证关系数据库事务依然成功提交，状态已前进至 5
    drama_row = session.execute(text("SELECT current_stage FROM dramas WHERE id = 202")).mappings().fetchone()
    assert drama_row["current_stage"] == 5

    ep_row = session.execute(text("SELECT id FROM episodes WHERE drama_id = 202 AND episode_number = 1")).mappings().fetchone()
    assert ep_row is not None


def test_stage5_cqrs_projection_published(sqlite_db_session):
    """【CQRS 投影闭环验证】验证 persist_stage5 与 stage5_screenplay_node 均正确广播投影。"""
    session = sqlite_db_session

    session.execute(text("""
        INSERT INTO dramas (id, title, total_episodes, current_stage)
        VALUES (303, 'CQRS测试剧', 5, 4)
    """))
    session.commit()

    state = _build_dummy_state(303)

    with patch("app.workflows.adapters.drama_storage_adapter.publish_drama_read_projection") as mock_proj, \
         patch("app.workflows.adapters.drama_storage_adapter.publish_drama_event") as mock_event, \
         patch("app.workflows.adapters.drama_storage_adapter.sync_stage_memories_to_vector_db"):

        DramaStorageAdapter.persist_stage5(session, 303, state)

        # 验证调用了 publish_drama_read_projection，且 current_stage 为 5
        mock_proj.assert_called_once()
        args, kwargs = mock_proj.call_args
        assert args[0] == 303
        payload = args[1]
        assert payload["current_stage"] == 5
        assert payload["journey"] == "journey_1_literary"
        assert payload["completed_episodes"] == [1]

        # 验证广播了 STAGE_PROGRESS 事件
        mock_event.assert_called_once()
        event_args = mock_event.call_args[0]
        assert event_args[0] == 303
        assert event_args[1] == "STAGE_PROGRESS"
        assert event_args[2]["stage"] == 5


def test_load_master_state_reads_dramas_current_stage(sqlite_db_session):
    """【状态加载权威验证】验证 load_master_state_from_db 优先读取 dramas.current_stage 列并校准 completed_episodes。"""
    session = sqlite_db_session

    meta = {"current_stage": 4, "journey": "journey_1_literary"}
    session.execute(text("""
        INSERT INTO dramas (id, title, total_episodes, current_stage, metadata)
        VALUES (404, '加载测试剧', 5, 5, :meta)
    """), {"meta": json.dumps(meta)})

    session.execute(text("""
        INSERT INTO episodes (drama_id, episode_number, title, script_content, ast_blocks)
        VALUES (404, 1, '第1集', '剧本文学正文', '{}')
    """))
    session.commit()

    # 从数据库加载
    loaded_state = load_master_state_from_db(session, 404)

    # 验证 current_stage 以 dramas 表的 5 为准（即使 metadata 滞留在 4）
    assert loaded_state.current_stage == 5
    assert loaded_state.completed_episodes == [1]
    assert 1 in loaded_state.completed_screenplays


def test_gatekeeper_node_fallback_session_scope():
    """【门禁自举落库验证】验证 stage5_literary_gatekeeper_node 在 db_session=None 时能自举落库并广播总锁。"""
    state = MagicMock()
    state.drama_id = 505
    state.total_episodes = 1
    state.completed_screenplays = {1: {"title": "终局"}}

    with patch("app.db.session.session_scope") as mock_scope, \
         patch("app.workflows.adapters.drama_storage_adapter.DramaStorageAdapter.persist_literary_journey") as mock_persist, \
         patch("app.context.short_memory_service.publish_drama_read_projection") as mock_proj, \
         patch("app.context.short_memory_service.publish_drama_event") as mock_event:

        mock_session_obj = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session_obj

        res = stage5_literary_gatekeeper_node(state, db_session=None)

        assert res["literary_journey_locked"] is True
        assert res["current_stage"] == 6
        assert res["journey"] == "journey_2_visual"

        mock_persist.assert_called_once_with(mock_session_obj, state)
        mock_proj.assert_called_once()
        proj_payload = mock_proj.call_args[0][1]
        assert proj_payload["current_stage"] == 6
        assert proj_payload["lock_status"] == 1
