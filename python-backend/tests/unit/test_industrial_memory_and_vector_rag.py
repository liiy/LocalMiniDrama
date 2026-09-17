"""单元测试：验证工业级长期记忆向量化 (Qdrant)、Redis 全模态短期记忆与 SOP 阶段同步。"""
from __future__ import annotations

import json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.context.memory_service import search_memory_items
from app.context.short_memory_service import get_short_memories, set_short_memories
from app.context.vector_memory_service import (
    generate_text_embedding,
    index_memory_item,
    search_memory_by_vector,
)
from app.db.schema import ensure_schema
from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.adapters.drama_storage_adapter import (
    persist_first_journey_state,
    persist_stage8,
    sync_stage_memories_to_vector_db,
)
from app.workflows.nodes.stage8_audio_mastering import _extract_ducking_events_from_shots


def test_generate_text_embedding_dimension_and_determinism():
    """验证文本 Embedding 生成函数的维度 (1536) 与确定性特征。"""
    vec1 = generate_text_embedding("主角陆沉手握染血加密U盘")
    vec2 = generate_text_embedding("主角陆沉手握染血加密U盘")
    vec3 = generate_text_embedding("反派韩泰金丝眼镜与冷笑")

    assert len(vec1) == 1536
    assert len(vec2) == 1536
    assert len(vec3) == 1536
    assert vec1 == vec2
    assert vec1 != vec3


def test_redis_short_memory_full_modal_and_snapshot():
    """验证 Redis 分布式短期工作记忆存储与物理快照读写。"""
    drama_id = 9988
    test_snapshot = {
        "episode_index": 2,
        "location": "夜 雨 7号废弃仓库",
        "character_states": {"陆沉": "左肩枪伤，眼神阴鸷"},
        "prop_possession": {"染血加密U盘": "右大衣内袋"},
        "freeze_frame_desc": "闪电划破雨夜，枪口直抵眉心",
    }
    test_manifest = {
        "characters": ["CHAR_01_LUCHEN"],
        "environments": ["SCENE_01_WAREHOUSE"],
        "props": ["PROP_01_USB"],
    }

    set_short_memories(
        drama_id=drama_id,
        memories={
            "pad_a": "便签A：主剧名《破晓复仇》；人设红线：防伟光正",
            "pad_b": "便签B：骨相方正下颌，粗花呢大衣",
            "pad_c": "便签C：三层做旧光影，+3dB拟音",
            "pad_d": "便签D：第1~3集Mini-Arc波次推进",
            "inter_episode_physical_snapshot": test_snapshot,
            "current_resource_manifest": test_manifest,
        },
        stage_name="stage5_screenplay",
    )

    loaded = get_short_memories(drama_id)
    assert "便签A" in loaded["pad_a"]
    assert "便签B" in loaded["pad_b"]
    assert loaded["inter_episode_physical_snapshot"]["location"] == "夜 雨 7号废弃仓库"
    assert loaded["current_resource_manifest"]["characters"] == ["CHAR_01_LUCHEN"]


def test_sync_stage_memories_and_hybrid_search():
    """验证阶段长期记忆落库、向量索引及混合检索。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        ensure_schema(conn)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # 初始化测试剧目
    db.execute(text("INSERT INTO dramas (id, title) VALUES (777, '绝命反击')"))
    db.commit()

    # 同步阶段 2 角色记忆
    char_memories = [
        {
            "title": "主角 陆沉 (生物肖像与骨相)",
            "content": "高颧骨方正下颌，右嘴角上方0.5cm浅褐色小痣，穿重磅粗花呢600gsm大衣，手肘磨损折痕",
            "summary": "主角骨相与真实生活质感服饰",
            "keywords": ["陆沉", "主角", "粗花呢", "骨相"],
            "memory_type": "character_profile",
            "source_type": "stage2_characters",
            "source_id": "char_lucheng",
        },
        {
            "title": "反派 韩泰 (生物肖像与骨相)",
            "content": "金丝眼镜，常年盘转紫檀手串第三颗，眼神阴鸷",
            "summary": "核心反派假面",
            "keywords": ["韩泰", "反派", "手串"],
            "memory_type": "character_profile",
            "source_type": "stage2_characters",
            "source_id": "char_hantai",
        },
    ]
    sync_stage_memories_to_vector_db(db, drama_id=777, stage_id=2, items=char_memories)

    # 验证关系数据库 memory_items 已写入
    rows = db.execute(text("SELECT id, title, memory_type FROM memory_items WHERE drama_id = 777")).mappings().all()
    assert len(rows) == 2

    # 执行混合 RAG 检索
    results = search_memory_items(db, drama_id=777, query="陆沉 粗花呢大衣", limit=5)
    assert len(results) >= 1
    assert any("陆沉" in r.get("title", "") for r in results)


def test_ducking_events_dynamic_alignment_from_shots():
    """验证分镜对白与 SRT 时间戳精准对齐 Ducking 避让事件。"""
    shots = [
        {
            "shot_id": 1,
            "timecode": "00:00:00,000 --> 00:00:02,500",
            "audio": {"dialogue": "", "foley": "暴雨声"},
        },
        {
            "shot_id": 2,
            "timecode": "00:00:02,500 --> 00:00:06,200",
            "audio": {"dialogue": "韩泰：你以为凭一件旧物就能翻盘？"},
        },
        {
            "shot_id": 3,
            "timecode": "00:00:06,200 --> 00:00:09,800",
            "audio": {"dialogue": "陆沉：当年杀人时，你也是这么说的！"},
        },
    ]

    events = _extract_ducking_events_from_shots(shots)
    assert len(events) == 2
    assert events[0]["start_sec"] == 2.5
    assert events[0]["end_sec"] == 6.2
    assert events[0]["gain_db"] == -18.0
    assert "韩泰" in events[0]["description"]

    assert events[1]["start_sec"] == 6.2
    assert events[1]["end_sec"] == 9.8
    assert events[1]["gain_db"] == -18.0
