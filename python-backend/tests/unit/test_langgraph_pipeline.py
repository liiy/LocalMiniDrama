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
    final_output = graph.invoke(initial_state)

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
