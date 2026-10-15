"""阶段 6 向量服务资产隔离与混合候选池召回测试 (Stage 6 Vector Isolation & Candidate Recall Tests)。

验证范围：
1. 剧目物理隔离 Collection 命名规范 (get_drama_asset_collection_name)；
2. 资产批量同步接口 (sync_assets_to_vector_db) 幂等性与容灾保护；
3. 动态候选池混合召回接口 (recall_candidate_assets_for_episode)：
   - 精确匹配 (db_exact) 权重最高 (1.0)；
   - 跨剧严格物理隔离：不同剧本资产绝对互不泄露与干扰；
   - 截断保护：Top-K 参数精准限制返回候选集长度；
   - 兜底能力：未命中或无文本时优雅回退至 Tier-0 核心基准桩。
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import text

from app.context.vector_memory_service import (
    get_drama_asset_collection_name,
    ensure_drama_asset_collection,
    sync_assets_to_vector_db,
    recall_candidate_assets_for_episode,
)


def test_drama_asset_collection_naming_isolation():
    """测试剧目 Collection 名称生成与物理隔离。"""
    # 1. 验证不同剧本生成不同的专属 Collection
    col_101 = get_drama_asset_collection_name(101)
    col_202 = get_drama_asset_collection_name("202")
    col_none = get_drama_asset_collection_name(None)

    assert col_101 == "lmd_assets_drama_101"
    assert col_202 == "lmd_assets_drama_202"
    assert col_none == "lmd_assets_shared"
    assert col_101 != col_202


def test_sync_assets_to_vector_db_graceful():
    """测试资产批量写入时的边界保护与容灾能力。"""
    # 空资产列表安全返回 0
    assert sync_assets_to_vector_db(101, []) == 0
    # 无效 drama_id 安全返回 0
    assert sync_assets_to_vector_db(None, [{"asset_key": "CHAR_TEST"}]) == 0


def test_recall_candidate_assets_for_episode_db_exact_and_isolation(db_session):
    """测试基于数据库精确扫描与跨剧隔离的单集资产召回。"""
    # 1. 插入剧本 A (九龙夺嫡, id=501) 的角色、场景、道具与 assets 表资产
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (501, '九龙夺嫡', 'draft', '{}', '', '')")
    )
    db_session.execute(
        text("INSERT INTO characters (id, drama_id, name, character_code, appearance, role, created_at, updated_at) VALUES (5011, 501, '胤禛', 'YINZHEN', '沉静内敛，冷峻坚毅', 'protagonist', '', '')")
    )
    db_session.execute(
        text("INSERT INTO characters (id, drama_id, name, character_code, appearance, role, created_at, updated_at) VALUES (5012, 501, '年羹尧', 'NIAN', '粗犷威武，虎背熊腰', 'supporting', '', '')")
    )
    db_session.execute(
        text("INSERT INTO scenes (id, drama_id, location, prompt, created_at, updated_at) VALUES (5013, 501, '养心殿', '昏暗烛光，紫檀雕龙案几', '', '')")
    )
    db_session.execute(
        text("INSERT INTO props (id, drama_id, name, prompt, created_at, updated_at) VALUES (5014, 501, '密折', '黄绫封套，朱砂封泥', '', '')")
    )
    db_session.execute(
        text("""
            INSERT INTO assets (id, drama_id, asset_key, name, type, category, prompt, metadata, created_at, updated_at)
            VALUES (5015, 501, 'CHAR_YINZHEN_T1_BASE_PORTRAIT', '胤禛', 'image', 'character', '清代皇子常服', '{"stage_code": "T1", "visual_summary": "深沉冷峻四阿哥"}', '', '')
        """)
    )

    # 2. 插入剧本 B (长风渡, id=502) 的干扰资产，验证隔离
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (502, '长风渡', 'draft', '{}', '', '')")
    )
    db_session.execute(
        text("INSERT INTO characters (id, drama_id, name, character_code, appearance, role, created_at, updated_at) VALUES (5021, 502, '顾九思', 'GUJIUSI', '红衣纨绔，折扇轻摇', 'protagonist', '', '')")
    )
    db_session.execute(
        text("INSERT INTO scenes (id, drama_id, location, prompt, created_at, updated_at) VALUES (5022, 502, '望都茶楼', '烟雨朦胧，木质栏杆', '', '')")
    )
    db_session.execute(
        text("""
            INSERT INTO assets (id, drama_id, asset_key, name, type, category, prompt, metadata, created_at, updated_at)
            VALUES (5023, 502, 'CHAR_GUJIUSI_T1_BASE_PORTRAIT', '顾九思', 'image', 'character', '红衣少年', '{"stage_code": "T1", "visual_summary": "金陵纨绔公卿"}', '', '')
        """)
    )
    db_session.commit()

    # 3. 模拟第 1 集剧本文本：包含“胤禛”、“养心殿”、“密折”，未提及“年羹尧”，也未提及“顾九思”
    screenplay_text_ep1 = (
        "【第1集：潜龙在渊】\n"
        "夜幕深沉。养心殿内烛火摇曳。\n"
        "胤禛面色凝重，缓步走向御案。他颤抖着翻开密折，目光如刀。"
    )

    # 4. 执行候选池召回 (针对剧本 501)
    candidates_501 = recall_candidate_assets_for_episode(
        db=db_session,
        drama_id=501,
        screenplay_text=screenplay_text_ep1,
        top_k=10,
    )

    # 5. 断言结果
    retrieved_keys = {c["asset_key"] for c in candidates_501}
    # 核心命中项
    assert "CHAR_YINZHEN_T1_BASE_PORTRAIT" in retrieved_keys
    assert "ENV_养心殿_T1_WIDE" in retrieved_keys
    assert "PROP_密折_T1_STATIC" in retrieved_keys

    # 验证评分与来源
    yinzhen_card = next(c for c in candidates_501 if c["asset_key"] == "CHAR_YINZHEN_T1_BASE_PORTRAIT")
    assert yinzhen_card["relevance_score"] == 1.0
    assert yinzhen_card["recall_source"] == "db_exact"
    assert yinzhen_card["name"] == "胤禛"

    # 绝对隔离校验：剧本 B 的任何资产（顾九思、望都茶楼）严禁被查出
    for c in candidates_501:
        assert "GUJIUSI" not in c["asset_key"]
        assert "望都" not in c["asset_key"]
        assert c["name"] != "顾九思"

    # 6. 测试 Top-K 截断
    limited_candidates = recall_candidate_assets_for_episode(
        db=db_session,
        drama_id=501,
        screenplay_text=screenplay_text_ep1,
        top_k=2,
    )
    assert len(limited_candidates) == 2


def test_recall_candidate_assets_fallback_tier0(db_session):
    """测试剧本文本无显式匹配时，自动兜底提供 Tier-0 基准桩。"""
    # 插入剧目 503 的主角与主场景
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (503, '楚汉相争', 'draft', '{}', '', '')")
    )
    db_session.execute(
        text("INSERT INTO characters (id, drama_id, name, character_code, appearance, role, created_at, updated_at) VALUES (5031, 503, '刘邦', 'LIUBANG', '汉高祖', 'protagonist', '', '')")
    )
    db_session.execute(
        text("INSERT INTO scenes (id, drama_id, location, prompt, created_at, updated_at) VALUES (5032, 503, '沛县大泽', '大雾弥漫，芒砀山中', '', '')")
    )

    # 针对 503 剧目，传入空剧本文本或无重合剧本文本
    candidates = recall_candidate_assets_for_episode(
        db=db_session,
        drama_id=503,
        screenplay_text="（一段完全没有提及刘邦或沛县的环境过渡音效）",
        top_k=5,
    )
    # 应包含主角与主场景兜底
    assert len(candidates) > 0
    keys = [c["asset_key"] for c in candidates]
    assert any("CHAR_" in k for k in keys)
    assert any("LIUBANG" in k for k in keys)
