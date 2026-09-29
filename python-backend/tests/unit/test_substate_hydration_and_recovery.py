# -*- coding: utf-8 -*-
"""
tests/unit/test_substate_hydration_and_recovery.py
验证单集切片懒水合 (load_episode_substate_slice)、原子持久化与宕机恢复。
确保在 Stage 7/8 故障时能够毫秒级无损恢复，且单集状态保持在 <100KB。
"""

import json
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.schema import ensure_schema
from app.schemas.script_graph_state import (
    EpisodeScopedSubState,
    SeasonOutlineCard,
    StoryboardShotStub,
    InterEpisodePhysicalContinuity,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_episode_substate_slice,
    persist_episode_substate_slice,
    DramaStorageAdapter,
)
from app.context.short_memory_service import get_episode_read_projection


@pytest.fixture
def sqlite_db_session():
    """提供干净的 SQLite 内存测试数据库。"""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        ensure_schema(conn)
        conn.commit()

    with Session(engine) as session:
        now = "2026-09-19T12:00:00Z"
        # 初始化剧目
        session.execute(
            text("""
                INSERT INTO dramas (id, title, genre, status, current_stage, total_episodes, created_at, updated_at)
                VALUES (1, '深海回声', '科幻悬疑', 'running', 4, 10, :now, :now)
            """),
            {"now": now},
        )
        # 初始化角色
        session.execute(
            text("""
                INSERT INTO characters (id, drama_id, name, role, appearance, voice_style, created_at, updated_at)
                VALUES (1, 1, '沈凌', '男主', '深蓝潜水服短发左额疤痕', '沉稳磁性青年音', :now, :now),
                       (2, 1, '陈墨', '反派', '黑色战术甲右眼机械义眼', '冷酷低沉音', :now, :now)
            """),
            {"now": now},
        )
        # 初始化场景
        session.execute(
            text("""
                INSERT INTO scenes (id, drama_id, location, prompt, created_at, updated_at)
                VALUES (1, 1, '主控制舱', 'futuristic submarine control room, dim red light', :now, :now)
            """),
            {"now": now},
        )
        # 初始化道具
        session.execute(
            text("""
                INSERT INTO props (id, drama_id, name, type, prompt, created_at, updated_at)
                VALUES (1, 1, '深海气压表', 'hero_tier1', 'worn brass pressure gauge with cracked glass', :now, :now)
            """),
            {"now": now},
        )
        # 初始化第 1 集大纲与 AST
        ast_blocks = {
            "previous_episode_0s_pickup": {
                "inherited_from_episode": 0,
                "location": "潜艇进水走廊",
                "characters_posture": {"沈凌": "握紧手电筒前进"},
            },
            "episode_end_physical_delta": {
                "inherited_from_episode": 1,
                "location": "主控制舱密封门前",
                "characters_posture": {"沈凌": "半跪在门前右臂擦伤"},
            },
        }
        session.execute(
            text("""
                INSERT INTO episodes (
                    id, drama_id, episode_number, title, description,
                    hook_cliffhanger, duration, status, ast_blocks, created_at, updated_at
                ) VALUES (
                    101, 1, 1, '深潜危机', '深海探测第一集：45秒微反转：舱门从外部被焊死',
                    '115秒断点：隔热玻璃外有一双眼睛',
                    90, 'outline_completed', :ast, :now, :now
                )
            """),
            {"ast": json.dumps(ast_blocks, ensure_ascii=False), "now": now},
        )
        session.commit()
        yield session


def test_load_episode_substate_slice_minimal_footprint(sqlite_db_session):
    """测试 load_episode_substate_slice 能够毫秒级加载轻量级切片且字段完备。"""
    substate = load_episode_substate_slice(sqlite_db_session, drama_id=1, episode_number=1)

    assert isinstance(substate, EpisodeScopedSubState)
    assert substate.drama_id == 1
    assert substate.episode_number == 1
    assert substate.current_stage == 5  # 未有剧本和分镜时，默认待执行 stage 5

    # 1. 验证大纲卡
    assert substate.task_outline.title == "深潜危机"
    assert "声纳发出尖锐报警" in substate.task_outline.hook_cliffhanger or "115秒断点" in substate.task_outline.hook_cliffhanger

    # 2. 验证 0 秒物理接棒快照
    assert substate.inherited_physical_continuity.location == "潜艇进水走廊"
    assert "沈凌" in substate.inherited_physical_continuity.characters_posture

    # 3. 验证轻量级桩 (Stubs)
    assert len(substate.relevant_character_stubs) == 2
    assert substate.relevant_character_stubs[0].name == "沈凌"
    assert "左额疤痕" in substate.relevant_character_stubs[0].visual_token

    assert len(substate.relevant_scene_stubs) == 1
    assert substate.relevant_scene_stubs[0].name == "主控制舱"

    assert len(substate.relevant_prop_stubs) == 1
    assert substate.relevant_prop_stubs[0].name == "深海气压表"

    # 4. 验证体积极其轻量 (<50KB)
    substate_json = substate.model_dump_json()
    assert len(substate_json.encode("utf-8")) < 50 * 1024


def test_persist_episode_substate_slice_and_cqrs(sqlite_db_session):
    """测试单集切片执行完毕后的原子持久化与 CQRS 读模型推送。"""
    substate = load_episode_substate_slice(sqlite_db_session, drama_id=1, episode_number=1)

    # 模拟执行 Stage 5~7
    substate.screenplay = {
        "title": "深潜危机",
        "scenes": [
            {"scene_id": 1, "heading": "内景 主控制舱", "dialogue": "沈凌: 气压还在上升！"}
        ]
    }
    substate.storyboard_shots = [
        StoryboardShotStub(
            shot_id=1,
            shot_number=1,
            visual_description="沈凌惊恐地看着气压表指针剧烈晃动",
            duration_sec=3.0,
            framing="MCU",
            camera_motion="Push In",
            dialogue_text="气压还在上升！",
        ),
        StoryboardShotStub(
            shot_id=2,
            shot_number=2,
            visual_description="仪表盘玻璃突然出现裂痕，火花四溅",
            duration_sec=2.5,
            framing="CU",
            camera_motion="Shake",
            dialogue_text="",
        ),
    ]
    substate.srt_content = "1\n00:00:00,000 --> 00:00:03,000\n气压还在上升！\n"
    substate.current_stage = 7

    # 持久化切片
    persist_episode_substate_slice(sqlite_db_session, drama_id=1, substate=substate)

    # 验证数据库中 episodes 与 storyboards 表是否已更新
    ep_row = sqlite_db_session.execute(
        text("SELECT script_content, ast_blocks FROM episodes WHERE id = 101")
    ).mappings().first()
    assert ep_row is not None
    assert "气压还在上升！" in ep_row["script_content"]

    sb_rows = sqlite_db_session.execute(
        text("SELECT storyboard_number, image_prompt, shot_type FROM storyboards WHERE episode_id = 101 ORDER BY storyboard_number ASC")
    ).mappings().all()
    assert len(sb_rows) == 2
    assert sb_rows[0]["storyboard_number"] == 1
    assert "气压表指针剧烈晃动" in sb_rows[0]["image_prompt"]

    # 验证 CQRS 读投影
    proj = get_episode_read_projection(drama_id=1, episode_number=1)
    assert proj is not None
    assert proj["drama_id"] == 1
    assert proj["episode_number"] == 1
    assert proj["has_screenplay"] is True
    assert proj["storyboard_shot_count"] == 2


def test_crash_recovery_from_breakpoint(sqlite_db_session):
    """测试宕机恢复：模拟在 Stage 7 生成分镜后进程崩溃，重启后无需重算直接秒级恢复。"""
    # 1. 模拟崩溃前状态已落库
    substate = load_episode_substate_slice(sqlite_db_session, drama_id=1, episode_number=1)
    substate.screenplay = {"title": "深潜危机", "content": "文学剧本正文"}
    substate.storyboard_shots = [
        StoryboardShotStub(
            shot_id=1,
            shot_number=1,
            visual_description="镜头缓缓摇过黑暗走廊",
            duration_sec=3.0,
            framing="WS",
        )
    ]
    substate.current_stage = 7
    persist_episode_substate_slice(sqlite_db_session, drama_id=1, substate=substate)

    # 2. 模拟进程崩溃重启：重新实例化 Adapter 并水合
    adapter = DramaStorageAdapter(sqlite_db_session)
    recovered_substate = adapter.load_episode_substate_slice(drama_id=1, episode_number=1)

    # 3. 验证断点无缝恢复
    assert recovered_substate.current_stage == 7
    assert len(recovered_substate.storyboard_shots) == 1
    assert recovered_substate.storyboard_shots[0].visual_description == "镜头缓缓摇过黑暗走廊"
    assert recovered_substate.screenplay is not None

    # 后续直接继续执行 Stage 8 混音，无需从 Stage 1 或 Stage 5 重跑
    recovered_substate.audio_mastering = {
        "status": "completed",
        "music_tracks": [{"track_id": "bgm_01", "name": "深海恐惧"}],
    }
    recovered_substate.is_completed = True
    recovered_substate.current_stage = 8
    adapter.persist_episode_substate_slice(drama_id=1, substate=recovered_substate)

    # 再次读取验证终态
    final_substate = adapter.load_episode_substate_slice(drama_id=1, episode_number=1)
    assert final_substate.is_completed is True
    assert final_substate.current_stage == 8
    assert final_substate.audio_mastering["status"] == "completed"


def test_multi_episode_parallel_isolation(sqlite_db_session):
    """测试多集并行滑动窗口隔离性：各集切片互相独立，无内存相互影响。"""
    now = "2026-09-19T12:00:00Z"
    # 创建第 2 集和第 3 集数据
    for ep_num in [2, 3]:
        ast_blocks = {
            "previous_episode_0s_pickup": {"location": f"第{ep_num}集接棒点"},
            "episode_end_physical_delta": {"location": f"第{ep_num}集结束点"},
        }
        sqlite_db_session.execute(
            text("""
                INSERT INTO episodes (
                    id, drama_id, episode_number, title, duration, status, ast_blocks, created_at, updated_at
                ) VALUES (
                    :id, 1, :ep_num, :title, 90, 'outline_completed', :ast, :now, :now
                )
            """),
            {
                "id": 100 + ep_num,
                "ep_num": ep_num,
                "title": f"第{ep_num}集",
                "ast": json.dumps(ast_blocks, ensure_ascii=False),
                "now": now,
            },
        )
    sqlite_db_session.commit()

    adapter = DramaStorageAdapter(sqlite_db_session)
    slice1 = adapter.load_episode_substate_slice(drama_id=1, episode_number=1)
    slice2 = adapter.load_episode_substate_slice(drama_id=1, episode_number=2)
    slice3 = adapter.load_episode_substate_slice(drama_id=1, episode_number=3)

    assert slice1.episode_number == 1
    assert slice2.episode_number == 2
    assert slice3.episode_number == 3

    # 修改 slice2 不应影响 slice1 和 slice3
    slice2.storyboard_shots.append(
        StoryboardShotStub(shot_id=99, shot_number=99, visual_description="第2集独有镜头")
    )
    assert len(slice1.storyboard_shots) == 0
    assert len(slice2.storyboard_shots) == 1
    assert len(slice3.storyboard_shots) == 0
