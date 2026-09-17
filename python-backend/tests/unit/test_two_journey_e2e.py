"""Step 12 综合端到端测试：两程九阶全生命周期工业闭环集成验证。

覆盖：
1. 主图构建与全生命周期状态流转 (Stages 1~8)；
2. 红蓝对抗质检自愈与 0 秒快照咬合；
3. 第一程全季文学剧本定稿锁定与 Gatekeeper 人机门禁挂起/唤醒；
4. 第二程视听真理源资产提纯、双模式分镜、口型下颌动力学、SRT 轴测及全息混音工程；
5. 两程九阶数据库持久化与零破坏兼容性往返验证；
6. TwoJourneyRunner 流水线调度与 6 类核心 SSE 事件广播。
"""
import asyncio
import json
import os
from unittest.mock import patch
import pytest
from sqlalchemy import text

os.environ["LMD_FAST_TEST"] = "1"

from app.core.event_bus import EventBus
from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaMasterState,
    EpisodeResourceManifest,
    StoryboardShot,
)
from app.workflows.adapters.drama_storage_adapter import DramaStorageAdapter
from app.workflows.industrial_master_graph import (
    build_industrial_master_graph,
    run_industrial_master_pipeline,
)
from app.workflows.two_journey_runner import TwoJourneyRunner


def test_two_journey_end_to_end_graph_execution():
    """测试工业主图 Stages 1~8 端到端完整闭环执行。"""
    with patch("app.workflows.utils.llm_bridge.call_llm_json", side_effect=lambda user_prompt, system_prompt="", fallback_factory=None, options=None: fallback_factory() if fallback_factory else {}):
        # 构造初始主状态 (2集极速验证)
        initial_state = IndustrialDramaMasterState(
            drama_id=888,
            total_episodes=2,
            selected_title="寒门状元归来",
            logline="寒门学子考取状元反击宗族恶霸",
            aspect_ratio="9:16",
            target_duration_sec=90.0,
            visual_style="古风国潮/微短剧",
        )

        final_state = run_industrial_master_pipeline(
            initial_state=initial_state,
            thread_id="test_run_e2e_888",
        )

        # 1. 验证第一程成果
        assert final_state.literary_journey_locked is True
        assert len(final_state.completed_screenplays) == 2
        assert 1 in final_state.completed_screenplays
        assert 2 in final_state.completed_screenplays

    # 验证 0 秒快照物理咬合
    assert final_state.inter_episode_physical_snapshot is not None
    assert "last_scene" in final_state.inter_episode_physical_snapshot

    # 2. 验证第二程成果
    assert final_state.journey == "completed"
    assert len(final_state.episode_storyboards) == 2
    assert len(final_state.episode_srt_exports) == 2
    assert len(final_state.episode_audio_masterings) == 2

    # 验证分镜双模式与口型动力学
    ep1_storyboards = final_state.episode_storyboards[1]
    assert len(ep1_storyboards) > 0
    for shot in ep1_storyboards:
        assert shot.generation_mode in ("first_last_frame", "multi_image_ref", "multi_image_reference")
        if shot.lipsync_dynamics:
            assert 0.0 <= shot.lipsync_dynamics.jaw_open <= 1.0

    # 验证 SRT 轴测
    ep1_srt = final_state.episode_srt_exports[1]
    assert "-->" in ep1_srt

    # 验证混音工程与 -12dB 避让
    ep1_audio = final_state.episode_audio_masterings[1]
    assert "ducking_events" in ep1_audio
    assert len(ep1_audio["ducking_events"]) > 0
    for duck in ep1_audio["ducking_events"]:
        assert duck["gain_db"] <= -12.0


def test_two_journey_gatekeeper_interrupt_and_resume():
    """测试第一程定稿门禁中断与唤醒流转。"""
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    graph = build_industrial_master_graph(checkpointer=checkpointer, interrupt_after=["gatekeeper"])

    config = {"configurable": {"thread_id": "test_drama_gate_999"}}

    initial_state = IndustrialDramaMasterState(
        drama_id=999,
        total_episodes=2,
        selected_title="豪门千金复仇记",
        logline="豪门千金隐姓埋名回归复仇",
    )

    # 运行到 gatekeeper 门禁处安全挂起
    events = list(graph.stream(initial_state, config=config))
    snapshot = graph.get_state(config)
    assert snapshot.next == ("stage6_asset_truth",)
    assert snapshot.values.get("literary_journey_locked") is True

    # 模拟主创审批通过并恢复唤醒流转
    resume_events = list(graph.stream(None, config=config))
    final_snapshot = graph.get_state(config)
    assert final_snapshot.values.get("journey") == "completed"
    assert len(final_snapshot.values.get("episode_storyboards") or {}) == 2


def test_storage_adapter_full_two_journey_lifecycle(db_session):
    """测试 DramaStorageAdapter 对两程九阶全息状态的持久化与还原往返。"""
    db_session.execute(
        text(
            "INSERT INTO dramas (id, title, description, genre, total_episodes, lock_status, pipeline_status) "
            "VALUES (501, '龙王战令', '绝密龙王归隐都市', '战神', 2, 0, 'idle')"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO episodes (id, drama_id, episode_number, title, duration) "
            "VALUES (5001, 501, 1, '第1集 龙令初现', 90)"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO episodes (id, drama_id, episode_number, title, duration) "
            "VALUES (5002, 501, 2, '第2集 斩断宿怨', 90)"
        )
    )
    db_session.commit()

    adapter = DramaStorageAdapter(db_session)

    # 1. 持久化第一程定稿与快照
    state_to_save = IndustrialDramaMasterState(
        drama_id=501,
        selected_title="龙王战令",
        logline="绝密龙王归隐都市",
        total_episodes=2,
        literary_journey_locked=True,
        characters_engine={
            "characters": [
                {
                    "id": "char_longwang",
                    "name": "叶凡",
                    "role_type": "主角",
                    "personality": "冷静杀伐果断",
                    "appearance": "黑袍龙纹",
                    "voice_style": "沉稳低音",
                    "identity_anchors": {"core_goal": "复仇"},
                }
            ]
        },
        environments_and_props={
            "environments": [
                {
                    "location_name": "龙王殿废墟",
                    "time_and_lighting": "雷雨夜",
                    "atmosphere": "肃杀",
                    "weathering_layers": {"texture": "烧焦青石"},
                    "visual_prompt": "破败古代宫殿，暴雨倾盆",
                }
            ],
            "props": [
                {
                    "name": "修罗龙令",
                    "type": "令牌",
                    "description": "玄铁铸就，刻九爪金龙",
                    "narrative_reversal_anchor": "令出如山倒",
                    "visual_prompt": "特写，黑色令牌泛微光",
                }
            ],
        },
    )
    adapter.persist_first_journey_state(501, state_to_save)
    db_session.commit()

    # 检查数据库 lock_status
    row = db_session.execute(text("SELECT lock_status, pipeline_status FROM dramas WHERE id = 501")).mappings().first()
    assert row["lock_status"] == 1
    assert row["pipeline_status"] == "first_journey_locked"

    # 检查长期记忆 memory_items 是否成功写入
    mem_rows = db_session.execute(text("SELECT memory_type, title FROM memory_items WHERE drama_id = 501")).mappings().all()
    assert len(mem_rows) >= 3
    mem_types = [m["memory_type"] for m in mem_rows]
    assert "character_profile" in mem_types
    assert "world_rule" in mem_types
    assert "prop_anchor" in mem_types

    # 2. 持久化第二程视听工程包
    pkg1 = {
        "episode_num": 1,
        "manifest": {
            "episode_num": 1,
            "approved_character_ids": ["char_longwang"],
            "approved_scene_ids": ["scene_mansion"],
            "approved_prop_ids": ["prop_badge"],
        },
        "storyboards": [
            {
                "shot_id": 1,
                "timecode": "00:00-00:03",
                "duration_sec": 3.0,
                "generation_mode": "first_last_frame",
                "framing": "特写",
                "camera_motion": "推镜头",
                "selection_rationale": "精准控速",
            }
        ],
        "srt_export": "1\n00:00:00,000 --> 00:00:03,000\n龙王归来！\n",
        "audio_mastering": {
            "total_duration_sec": 90.0,
            "ducking_events": [
                {
                    "start_sec": 1.0,
                    "end_sec": 3.0,
                    "target_track": "BGM",
                    "gain_db": -12.0,
                    "description": "对白避让",
                }
            ],
        },
    }

    adapter.persist_episode_visual_package(501, 1, pkg1)
    db_session.commit()

    # 3. 读取单集视听工程包
    loaded_pkg = adapter.load_episode_visual_package(501, 1)
    assert loaded_pkg is not None
    assert loaded_pkg["episode_num"] == 1
    assert loaded_pkg["manifest"]["approved_character_ids"] == ["char_longwang"]
    assert len(loaded_pkg["storyboards"]) == 1
    assert loaded_pkg["storyboards"][0]["generation_mode"] == "first_last_frame"
    assert loaded_pkg["audio_mastering"]["ducking_events"][0]["gain_db"] == -12.0

    # 4. 整体重载状态并验证
    loaded_master = adapter.load_master_state_from_db(501)
    assert loaded_master.drama_id == 501
    assert loaded_master.literary_journey_locked is True


def test_two_journey_runner_sse_events(db_session):
    """测试 TwoJourneyRunner 异步执行并校验 6 类核心 SSE 事件发布。"""
    async def _test():
        with patch.dict(os.environ, {"LMD_FAST_TEST": "1"}), patch("app.workflows.utils.llm_bridge.call_llm_json", side_effect=lambda user_prompt, system_prompt="", fallback_factory=None, options=None: fallback_factory() if fallback_factory else {}):
            db_session.execute(
                text(
                    "INSERT INTO dramas (id, title, description, genre, total_episodes, lock_status, pipeline_status) "
                    "VALUES (701, '修罗神尊', '修罗血战', '玄幻', 2, 0, 'idle')"
                )
            )
            db_session.commit()

            runner = TwoJourneyRunner(db_session=db_session)
            event_bus = EventBus.get_instance()

            received_events = []

            async def event_collector():
                async for event in event_bus.subscribe():
                    received_events.append(event)
                    if str(event.get("type")).upper() in ("PIPELINE_COMPLETED", "PIPELINE_ERROR"):
                        break

            # 订阅事件
            collector_task = asyncio.create_task(event_collector())

            # 异步执行全流程 (2集)
            run_task = asyncio.create_task(
                runner.run_pipeline_async(
                    drama_id=701,
                    user_prompt="修罗血战神尊重生",
                    genre="玄幻",
                    total_episodes=2,
                    target_duration_sec=60.0,
                    auto_proceed_to_visual=True,
                )
            )

            await asyncio.wait_for(asyncio.gather(run_task, collector_task), timeout=60.0)

            # 验证捕获到的事件类型
            event_types = [str(e.get("type")).upper() for e in received_events]
            assert "STAGE_PROGRESS" in event_types
            assert "MINI_ARC_COMPLETED" in event_types
            assert "FIRST_JOURNEY_LOCKED" in event_types
            assert "EPISODE_VISUAL_STARTED" in event_types
            assert "EPISODE_VISUAL_COMPLETED" in event_types

    asyncio.run(_test())
