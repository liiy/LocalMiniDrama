"""单元测试：验证三层解耦记忆架构与 N+1 级联失效 (Cascade Invalidation)。"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.schema import ensure_schema
from app.schemas.script_graph_state import ContinuityMemo
from app.context.three_tier_memory import ThreeTierMemoryManager, InformationGapEntry
from app.services.cascadeService import mark_downstream_episodes_stale


def test_three_tier_memory_entity_and_gap_management():
    """测试第二层结构化实体记忆与角色信息差更新。"""
    memo = ContinuityMemo()

    # 1. 更新角色动态状态
    memo = ThreeTierMemoryManager.update_entity_memory(
        memo,
        character_name="顾沉舟",
        state_updates={"health": "轻伤", "mask_exposure": "20%"},
        prop_updates={"龙纹金卡": "顾沉舟"},
    )
    assert memo.character_states["顾沉舟"]["health"] == "轻伤"
    assert memo.prop_traces["龙纹金卡"] == "顾沉舟"

    # 2. 注入角色间信息差
    secret_entry = InformationGapEntry(
        fact_id="SECRET_001",
        fact_description="顾沉舟实为隐龙殿主，当年入狱是为了替林家挡劫",
        knowing_characters=["顾沉舟", "暗卫队长"],
        deceived_characters=["林浅", "林家老太君"],
        planned_reveal_episode=20,
    )
    memo = ThreeTierMemoryManager.update_entity_memory(
        memo,
        character_name="顾沉舟",
        state_updates={},
        gap_updates=[secret_entry],
    )
    assert len(memo.information_gap_matrix) == 1

    # 3. 组装单集精准注入 Prompt
    prompt = ThreeTierMemoryManager.assemble_episode_context(
        db=None,
        drama_id=1,
        episode_num=10,
        continuity_memo=memo,
        active_window_summaries=["第9集结尾林浅起疑"],
        characters_present=["顾沉舟", "林浅"],
    )
    assert "SECRET_001" in prompt
    assert "知情: 顾沉舟, 暗卫队长" in prompt
    assert "蒙蔽: 林浅, 林家老太君" in prompt
    assert "龙纹金卡" in prompt


def test_cascade_invalidation_marks_downstream_stale():
    """测试修改第 N 集后，N+1 级联失效与 version_cursor 自增。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        ensure_schema(conn)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # 初始化测试数据：1 部剧，3 集，每集 1 个分镜
    db.execute(text("INSERT INTO dramas (id, title, version_cursor) VALUES (1, '测试短剧', 1)"))
    db.execute(text("INSERT INTO episodes (id, drama_id, episode_number, title) VALUES (10, 1, 1, '第1集')"))
    db.execute(text("INSERT INTO episodes (id, drama_id, episode_number, title) VALUES (20, 1, 2, '第2集')"))
    db.execute(text("INSERT INTO episodes (id, drama_id, episode_number, title) VALUES (30, 1, 3, '第3集')"))
    db.execute(text("INSERT INTO storyboards (id, episode_id, storyboard_number, status) VALUES (101, 10, 1, 'completed')"))
    db.execute(text("INSERT INTO storyboards (id, episode_id, storyboard_number, status) VALUES (201, 20, 1, 'completed')"))
    db.execute(text("INSERT INTO storyboards (id, episode_id, storyboard_number, status) VALUES (301, 30, 1, 'completed')"))
    db.commit()

    # 模拟用户修改了第 1 集大纲 -> 触发修改第 1 集级联失效
    result = mark_downstream_episodes_stale(db, drama_id=1, modified_episode_num=1)
    db.commit()

    assert result["status"] == "cascade_invalidated"
    assert result["affected_episodes"] == [2, 3]
    assert result["new_version_cursor"] == 2

    # 验证第 1 集的分镜不受影响保持 completed
    sb1 = db.execute(text("SELECT status FROM storyboards WHERE id = 101")).first()
    assert sb1[0] == "completed"

    # 验证第 2、3 集的分镜被标记为 stale
    sb2 = db.execute(text("SELECT status FROM storyboards WHERE id = 201")).first()
    sb3 = db.execute(text("SELECT status FROM storyboards WHERE id = 301")).first()
    assert sb2[0] == "stale"
    assert sb3[0] == "stale"
