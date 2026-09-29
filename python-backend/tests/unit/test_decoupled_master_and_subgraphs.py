# -*- coding: utf-8 -*-
"""分层解耦图编排单元测试 (Decoupled Master and Subgraphs Tests)。

覆盖：
1. 第一程文学主图 (build_literary_master_graph / run_literary_master_pipeline) 契约与流转
2. 第二程单集视听子图 (build_episode_visual_subgraph / run_episode_subgraph) 单集隔离执行
3. Gatekeeper 中断机制与全季文学定稿
4. 全流程兼容主图 (build_industrial_master_graph) 采用 GlobalDramaMasterState 的平滑流转
"""
from __future__ import annotations

import os
from unittest.mock import patch
import pytest

os.environ["LMD_FAST_TEST"] = "1"

from langgraph.checkpoint.memory import MemorySaver

from app.schemas.script_graph_state import (
    AuditVerdict,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    LiteraryScreenplayEpisodeModel,
    RedBlueAuditReport,
    SeasonOutlineCard,
)
from app.workflows.industrial_master_graph import (
    build_episode_subgraph,
    build_episode_visual_subgraph,
    build_industrial_master_graph,
    build_literary_master_graph,
    get_interrupt_after_nodes,
    get_literary_interrupt_after_nodes,
    run_episode_subgraph,
    run_literary_master_pipeline,
)


def _mock_llm(user_prompt: str, system_prompt: str = "", fallback_factory=None, options=None):
    """单测 LLM 桩：返回 fallback_factory() 兜底结构。"""
    if fallback_factory:
        return fallback_factory()
    return {}


class TestDecoupledMasterAndSubgraphs:
    """分层解耦图编排与子图测试套件。"""

    def test_literary_interrupt_after_nodes(self):
        """测试第一程中断节点计算。"""
        assert get_literary_interrupt_after_nodes("stage_by_stage") == [
            "audit_stage1",
            "audit_stage2",
            "audit_stage3",
            "audit_stage4",
            "audit_stage5",
            "gatekeeper",
        ]
        assert get_literary_interrupt_after_nodes("two_journey") == ["gatekeeper"]
        assert get_literary_interrupt_after_nodes("full_auto") is None

    def test_run_literary_master_pipeline_e2e(self):
        """测试第一程文学主图全流程执行至 Gatekeeper。"""
        with patch("app.workflows.utils.llm_bridge.call_llm_json", side_effect=_mock_llm):
            checkpointer = MemorySaver()
            initial_state = GlobalDramaMasterState(
                drama_id=7701,
                total_episodes=2,
                selected_title="龙王潜渊",
                logline="战神龙王隐藏身份回归都市报恩复仇",
                genre="战神都市",
                run_mode="full_auto",
            )

            # full_auto 模式直通 gatekeeper 完成
            final_state = run_literary_master_pipeline(
                initial_state=initial_state,
                thread_id="test_literary_7701",
                checkpointer=checkpointer,
                run_mode="full_auto",
            )

            # 验证第一程各阶段产物
            assert final_state.drama_id == 7701
            assert final_state.literary_journey_locked is True
            assert "战神龙王隐藏" in final_state.logline
            assert len(final_state.completed_screenplays) == 2
            assert 1 in final_state.completed_screenplays
            assert 2 in final_state.completed_screenplays
            assert final_state.characters_engine is not None
            assert final_state.environments_and_props is not None
            assert final_state.audio_bible is not None

    def test_literary_master_graph_gatekeeper_interrupt(self):
        """测试第一程文学主图在 two_journey 模式下在 Gatekeeper 安全挂起。"""
        with patch("app.workflows.utils.llm_bridge.call_llm_json", side_effect=_mock_llm):
            checkpointer = MemorySaver()
            graph = build_literary_master_graph(
                checkpointer=checkpointer,
                run_mode="two_journey",
            )

            config = {"configurable": {"thread_id": "test_lit_gate_7702"}}
            initial_state = GlobalDramaMasterState(
                drama_id=7702,
                total_episodes=1,
                selected_title="九龙至尊",
                logline="至尊退隐重登巅峰",
                run_mode="two_journey",
            )

            # 运行流直至挂起
            events = list(graph.stream(initial_state, config=config))
            snapshot = graph.get_state(config)

            # 挂起后 next 应为空（已完成 gatekeeper 节点并由于 interrupt_after 暂停在 gatekeeper 之后，即走向 END）
            # 或者 values 中 literary_journey_locked 为 True
            assert snapshot.values.get("literary_journey_locked") is True
            assert len(snapshot.values.get("completed_screenplays", {})) >= 1

    def test_episode_visual_subgraph_execution(self):
        """测试第二程单集视听子图独立执行 (Stage 6 -> 7 -> 8)。"""
        with patch("app.workflows.utils.llm_bridge.call_llm_json", side_effect=_mock_llm):
            checkpointer = MemorySaver()
            substate = EpisodeScopedSubState(
                drama_id="7703",
                episode_number=1,
                title="战神觉醒",
                scene_summary="龙王入城偶遇昔日恩人",
                script=LiteraryScreenplayEpisodeModel(
                    episode_id=1,
                    episode_title="战神觉醒",
                    screenplay_text="日内 豪门公馆\n龙王步入大厅，冷视众人。\n龙王：（冷声）十年恩仇，今日清算！",
                ),
                global_characters=[{"character_id": "char_01", "name": "龙王", "gender": "男"}],
                global_scenes=[{"scene_id": "SCENE_01", "name": "豪门公馆"}],
                season_outlines={
                    "episodes": [
                        SeasonOutlineCard(
                            episode_number=1,
                            title="战神觉醒",
                            dramatic_purpose="引出主角身世",
                            cliffhanger="黑衣人现身拔枪！",
                        )
                    ]
                },
            )

            # 执行单集子图
            result = run_episode_subgraph(
                substate=substate,
                thread_id="test_ep_subgraph_7703_1",
                checkpointer=checkpointer,
            )

            # 验证 Stage 6 资产提纯
            assert result.resource_manifest is not None
            assert result.resource_manifest.episode_num == 1

            # 验证 Stage 7 双模式分镜与 SRT
            assert result.storyboards is not None
            assert len(result.storyboards) > 0
            assert result.srt_export != ""
            assert "-->" in result.srt_export

            # 验证 Stage 8 声学混音与连续性
            assert result.mastering_config is not None
            assert result.is_completed is True
            assert result.outgoing_physical_continuity is not None
            assert result.outgoing_physical_continuity.episode_number == 1

    def test_build_industrial_master_graph_uses_global_state(self):
        """测试主图 build_industrial_master_graph 完美消费 GlobalDramaMasterState。"""
        with patch("app.workflows.utils.llm_bridge.call_llm_json", side_effect=_mock_llm):
            checkpointer = MemorySaver()
            graph = build_industrial_master_graph(checkpointer=checkpointer, run_mode="full_auto")

            initial_state = GlobalDramaMasterState(
                drama_id=7704,
                total_episodes=1,
                selected_title="逆袭之王",
                logline="小人物底层逆袭成为一代传奇",
                run_mode="full_auto",
            )

            config = {"configurable": {"thread_id": "test_master_global_7704"}}
            final_dict = graph.invoke(initial_state, config=config)

            assert final_dict["literary_journey_locked"] is True
            assert final_dict["journey"] == "completed"
            assert 1 in final_dict["completed_screenplays"]
            assert 1 in final_dict["episode_storyboards"]
            assert 1 in final_dict["episode_srt_exports"]
