"""单元测试：验证 LangGraph 剧本管道状态图编译、Send API 批次并发与瘦状态滑动窗口。"""
from __future__ import annotations

import json
from app.schemas.script_graph_state import LeanDramaScriptState, ProjectProfile
from app.workflows.langgraph_script_pipeline import build_script_pipeline_graph


def test_build_and_run_langgraph_script_pipeline():
    """测试完整运行 6 集短剧管道生成（验证 2 批次并发分发与最终定稿）。"""
    graph = build_script_pipeline_graph()
    assert graph is not None

    initial_state = LeanDramaScriptState(
        drama_id=101,
        version_cursor=1,
        project=ProjectProfile(
            title="龙王出狱之江城风云",
            episode_count=6,
            genre="都市爽剧",
        ),
        phase_status="concept_done",
    )

    # 执行状态图
    final_output = graph.invoke(initial_state, config={"configurable": {"thread_id": "test_drama_101"}})

    # 验证主线输出
    assert final_output["phase_status"] == "completed"
    assert final_output["lock_status"] is True
    assert final_output["version_cursor"] == 2

    # 验证 6 集全部存在于持久化引用映射中
    persisted_refs = final_output.get("persisted_episode_refs", {})
    assert len(persisted_refs) == 6
    assert set(persisted_refs.keys()) == {1, 2, 3, 4, 5, 6}

    # 验证滑动窗口仅保留最新集数（不超过 5 集），旧集已移至外存索引
    active_window = final_output.get("active_window_episodes", {})
    assert len(active_window) <= 5

    # 验证大纲数量为 6
    outlines = final_output.get("episode_outlines", {})
    assert len(outlines) == 6

    # 验证序列化体积严格 < 50KB
    serialized = json.dumps(
        final_output,
        default=lambda o: o.model_dump() if hasattr(o, "model_dump") else (o.dict() if hasattr(o, "dict") else str(o)),
    )
    size_kb = len(serialized.encode("utf-8")) / 1024.0
    print(f"\nFinal State serialized size: {size_kb:.2f} KB")
    assert size_kb < 50.0, f"State size exceeds 50KB limit: {size_kb:.2f} KB"


def test_langgraph_hitl_interrupt_update_and_resume():
    """测试 HITL 模式：阶段 3 大纲后挂起、人工修改状态覆写与断点恢复执行。"""
    from app.workflows.langgraph_script_pipeline import (
        build_script_pipeline_graph,
        get_pipeline_state_for_drama,
        update_pipeline_state_for_drama,
        resume_script_pipeline_for_drama,
        run_script_pipeline_for_drama,
    )
    from unittest.mock import MagicMock

    mock_db = MagicMock()
    mock_db.execute.return_value.fetchone.return_value = None

    drama_id = 999
    thread_id = f"drama_{drama_id}_test"

    # 1. 启动 HITL 模式，应在 outline_generation 后挂起
    init_res = run_script_pipeline_for_drama(
        db=mock_db,
        drama_id=drama_id,
        user_prompt="战神回归豪门",
        genre="都市爽剧",
        total_episodes=3,
        hitl_mode=True,
        thread_id=thread_id,
    )

    assert init_res.get("status") == "paused_hitl"
    assert init_res.get("thread_id") == thread_id

    # 2. 查询当前快照状态
    state_snapshot = get_pipeline_state_for_drama(drama_id=drama_id, thread_id=thread_id)
    assert state_snapshot["has_state"] is True
    assert state_snapshot["is_paused"] is True
    assert len(state_snapshot["episode_outlines"]) == 3

    # 3. 人工干预：修改第 1 集大纲反转点
    modified_outlines = state_snapshot["episode_outlines"]
    modified_outlines[1]["title"] = "第1集：龙王亮令震撼全场"
    modified_outlines[1]["commercial_tag"] = "free_hook"

    update_res = update_pipeline_state_for_drama(
        drama_id=drama_id,
        updates={"episode_outlines": modified_outlines},
        thread_id=thread_id,
    )
    assert update_res["status"] == "success"
    assert update_res["version_cursor"] == 2

    # 4. 断点恢复：唤醒状态机继续完成后续单集生成
    resume_res = resume_script_pipeline_for_drama(
        db=mock_db,
        drama_id=drama_id,
        thread_id=thread_id,
    )

    assert resume_res["phase_status"] == "completed"
    assert resume_res["lock_status"] is True
    assert len(resume_res["persisted_episode_refs"]) == 3
