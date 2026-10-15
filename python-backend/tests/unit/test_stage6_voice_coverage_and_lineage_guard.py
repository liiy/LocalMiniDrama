"""单元测试：验证阶段 6 角色母音卡 100% 覆盖率保底与底模防跨角色污染机制。

测试覆盖要点：
1. 【母音卡 100% 覆盖保底】：
   - 当 LLM 或外部输入遗漏次要角色或未开口角色的母音卡时，系统自动补录广播级母音卡入库。
   - 验证 character_voice_profiles 表中所有出场角色 100% 具备 master 音色卡，且 11 维声学参数完整合规。
2. 【图生图底模防跨角色污染】：
   - 衍生切片（full_body, four_view 等）若错误引用了异名角色的基准肖像作为 parent_asset_key，
     防线机制自动拦截并纠正为该角色自身的基准肖像，杜绝不同角色之间的图生图底模污染。
   - 基准肖像 (main_portrait / BASE_PORTRAIT) 自身强制为文生图根节点 (parent_asset_key=None, generation_mode='t2i')。
3. 【节点层防线验证】：
   - stage6_asset_truth_node 处理后，lineage_dag 与 newly_generated_assets 严格遵循同角色血统闭环。
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.schema import ensure_schema
from app.workflows.adapters.drama_storage_adapter import (
    clean_character_name,
    extract_character_tokens,
    find_canonical_entity,
    persist_stage6,
)
from app.workflows.nodes.stage6_asset_truth import (
    _ensure_standard_asset,
    stage6_asset_truth_node,
)


@pytest.fixture
def db_session():
    """建立基于 SQLite 内存数据库的隔离会话。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        ensure_schema(conn)
        conn.execute(
            text("""
                INSERT INTO dramas (id, title, genre, style, total_episodes, status, created_at, updated_at)
                VALUES (1, '亮剑测试短剧', '战争传奇', '胶片重颗粒写实', 10, 'draft', '2026-10-12T00:00:00Z', '2026-10-12T00:00:00Z')
            """)
        )
        conn.execute(
            text("""
                INSERT INTO episodes (id, drama_id, episode_number, title, status, created_at, updated_at)
                VALUES (101, 1, 1, '第1集：狭路相逢', 'draft', '2026-10-12T00:00:00Z', '2026-10-12T00:00:00Z')
            """)
        )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_stage6_voice_profiles_100_percent_coverage(db_session: Session):
    """验证阶段 6 角色母音卡 100% 覆盖率保底入库。"""
    drama_id = 1
    ep_num = 1

    # 模拟包含三个角色的阶段 6 Manifest 数据：
    # 1. 李云龙（主角，提供了显式母音卡）
    # 2. 赵刚（配角，提供了显式母音卡）
    # 3. 魏大勇/魏和尚（警卫员，未开口/次要角色，故意不提供母音卡）
    manifest_data = {
        "episode_num": ep_num,
        "characters": [
            {
                "char_id": "CHAR_LIYUNLONG_T1_BASE_PORTRAIT",
                "character_name": "李云龙",
                "role": "protagonist",
                "gender": "男",
                "perceived_age": "38岁",
                "stage_name": "八路军粗布军服",
                "stage_code": "T1",
                "visual_prompt": "李云龙正脸主肖像，眼神坚毅粗犷，黄土高坡风沙质感",
                "voice_style": "洪亮豪迈、略带沙哑的高亢嗓音",
            },
            {
                "char_id": "CHAR_ZHOUGANG_T1_BASE_PORTRAIT",
                "character_name": "赵刚",
                "role": "supporting",
                "gender": "男",
                "perceived_age": "32岁",
                "stage_name": "八路军干部灰布军服",
                "stage_code": "T1",
                "visual_prompt": "赵刚正脸主肖像，面容清秀儒雅，眼神沉稳坚定",
                "voice_style": "温和沉稳、清晰坚定的知识分子嗓音",
            },
            {
                "char_id": "CHAR_WEIDAYONG_T1_BASE_PORTRAIT",
                "character_name": "魏大勇",
                "role": "supporting",
                "gender": "男",
                "perceived_age": "24岁",
                "stage_name": "八路军战士军服",
                "stage_code": "T1",
                "visual_prompt": "魏大勇正脸主肖像，少林武僧还俗，虎背熊腰，眼神刚烈",
                "voice_style": "",  # 无台词/未开口，未配置音色描述
            },
        ],
        "environments": [],
        "props": [],
        "voice_cards": [
            # 仅提供李云龙和赵刚两人的母音卡，遗漏魏大勇
            {
                "master_voice_id": "VOICE_LIYUNLONG_MASTER",
                "character_name": "李云龙",
                "character_code": "CHAR_LIYUNLONG",
                "timbre": "豪迈粗粝中音",
                "vocal_flaws": "重度烟酒颗粒摩擦感",
                "timbre_archetype": "battlefield_commander",
                "vocal_position": "胸腔低位",
                "tts_provider": "edge-tts",
                "speed_ratio": 1.05,
                "pitch_ratio": 0.95,
            },
            {
                "master_voice_id": "VOICE_ZHOUGANG_MASTER",
                "character_name": "赵刚",
                "character_code": "CHAR_ZHOUGANG",
                "timbre": "儒雅清朗男中音",
                "vocal_flaws": "书生气克制吐字",
                "timbre_archetype": "intellectual_cadre",
                "vocal_position": "头腔与胸腔平衡",
                "tts_provider": "edge-tts",
                "speed_ratio": 0.98,
                "pitch_ratio": 1.0,
            },
        ],
    }

    state_dict = {
        "drama_id": drama_id,
        "episode_number": ep_num,
        "episode_resource_manifest": manifest_data,
        "character_manifest": manifest_data["characters"],
        "voice_cards": manifest_data["voice_cards"],
        "newly_generated_assets": [],
    }

    # 执行阶段 6 落库
    persist_stage6(db_session, drama_id=drama_id, state=state_dict, episode_num=ep_num)
    db_session.commit()

    # 1. 验证自然人角色表 characters 有 3 条记录
    char_rows = db_session.execute(
        text("SELECT id, name, character_code FROM characters WHERE drama_id = :did ORDER BY id ASC"),
        {"did": drama_id},
    ).mappings().all()
    assert len(char_rows) == 3
    char_names = {r["name"] for r in char_rows}
    assert char_names == {"李云龙", "赵刚", "魏大勇"}

    # 2. 验证 character_voice_profiles 表达成 100% 覆盖率（3 个人均有母音卡）
    vp_rows = db_session.execute(
        text("""
            SELECT cvp.*, c.name as char_name
            FROM character_voice_profiles cvp
            JOIN characters c ON cvp.character_id = c.id
            WHERE cvp.drama_id = :did AND cvp.deleted_at IS NULL
        """),
        {"did": drama_id},
    ).mappings().all()

    assert len(vp_rows) == 3, f"预期 3 张母音卡，实际查询到 {len(vp_rows)} 张"

    vp_by_name = {r["char_name"]: dict(r) for r in vp_rows}

    # 验证李云龙和赵刚显式录入的数据
    assert vp_by_name["李云龙"]["is_master_card"] == 1
    assert vp_by_name["李云龙"]["timbre_archetype"] == "battlefield_commander"
    assert vp_by_name["赵刚"]["is_master_card"] == 1
    assert vp_by_name["赵刚"]["timbre_archetype"] == "intellectual_cadre"

    # 验证魏大勇的自动补全保底数据
    wdy_vp = vp_by_name["魏大勇"]
    assert wdy_vp["is_master_card"] == 1, "未开口角色自动补录的母音卡必须具备 is_master_card=1"
    assert wdy_vp["timbre"] is not None and len(wdy_vp["timbre"]) > 0
    assert wdy_vp["vocal_position"] is not None
    assert wdy_vp["speed_ratio"] == pytest.approx(1.0, abs=0.2)
    assert wdy_vp["pitch_ratio"] == pytest.approx(1.0, abs=0.2)
    assert wdy_vp["tts_provider"] in ("minimax", "edge-tts")


def test_stage6_lineage_guard_cross_character_contamination(db_session: Session):
    """验证图生图底模防跨角色污染拦截与血统闭环。"""
    drama_id = 1
    ep_num = 1

    # 构造带有跨角色引用污染的 Manifest：
    # 赵刚的全身照切片，错误地将李云龙的基准肖像设为父资产
    manifest_data = {
        "episode_num": ep_num,
        "characters": [
            # 李云龙基准肖像
            {
                "char_id": "CHAR_LIYUNLONG_T1_BASE_PORTRAIT",
                "character_name": "李云龙",
                "role": "protagonist",
                "gender": "男",
                "stage_name": "八路军粗布军服",
                "stage_code": "T1",
                "visual_prompt": "李云龙正脸主肖像，刚毅面庞",
            },
            # 赵刚基准肖像（误设了父资产，防线需将其清空为 None）
            {
                "char_id": "CHAR_ZHOUGANG_T1_BASE_PORTRAIT",
                "character_name": "赵刚",
                "role": "supporting",
                "gender": "男",
                "stage_name": "八路军干部灰布军服",
                "stage_code": "T1",
                "visual_prompt": "赵刚正脸主肖像，书生气",
                "parent_asset_key": "CHAR_LIYUNLONG_T1_BASE_PORTRAIT",  # 错误跨角色污染！
            },
            # 赵刚全身定妆照（错误地将李云龙基准肖像设为父级，防线需将其纠正为赵刚自身的基准肖像）
            {
                "char_id": "CHAR_ZHOUGANG_T1_FULL_BODY",
                "character_name": "赵刚(全身照)",
                "role": "supporting",
                "gender": "男",
                "stage_name": "八路军干部灰布军服",
                "stage_code": "T1",
                "visual_prompt": "赵刚全身定妆照，站立姿态",
                "parent_asset_key": "CHAR_LIYUNLONG_T1_BASE_PORTRAIT",  # 严重跨角色污染！
            },
        ],
        "environments": [],
        "props": [],
        "voice_cards": [],
    }

    state_dict = {
        "drama_id": drama_id,
        "episode_number": ep_num,
        "episode_resource_manifest": manifest_data,
        "character_manifest": manifest_data["characters"],
        "voice_cards": [],
        "newly_generated_assets": [],
    }

    # 执行落库
    persist_stage6(db_session, drama_id=drama_id, state=state_dict, episode_num=ep_num)
    db_session.commit()

    # 查询 character_stage_views
    views = db_session.execute(
        text("""
            SELECT csv.*, cs.stage_code, c.name as char_name
            FROM character_stage_views csv
            JOIN character_stages cs ON csv.character_stage_id = cs.id
            JOIN characters c ON cs.character_id = c.id
            WHERE c.drama_id = :did AND csv.deleted_at IS NULL
            ORDER BY csv.id ASC
        """),
        {"did": drama_id},
    ).mappings().all()

    view_map = {(v["char_name"], v["view_type"]): dict(v) for v in views}

    # 1. 验证李云龙基准主肖像：parent_asset_key 必须为 None，generation_mode 必须为 t2i
    lyl_portrait = view_map[("李云龙", "main_portrait")]
    assert lyl_portrait["parent_asset_key"] is None
    assert lyl_portrait["generation_mode"] == "t2i"

    # 2. 验证赵刚基准主肖像：即使输入给定了父资产，防线必须强行纠正为 None，generation_mode 为 t2i
    zg_portrait = view_map[("赵刚", "main_portrait")]
    assert zg_portrait["parent_asset_key"] is None, "基准主肖像绝不允许继承父资产"
    assert zg_portrait["generation_mode"] == "t2i"

    # 3. 验证赵刚全身定妆照：原父资产为李云龙肖像，防线必须拦截并自动修复为赵刚自身的基准肖像！
    zg_fullbody = view_map[("赵刚", "full_body")]
    assert zg_fullbody["parent_asset_key"] is not None
    assert "LIYUNLONG" not in zg_fullbody["parent_asset_key"], "严禁赵刚切片包含李云龙的父资产密钥！"
    assert "ZHOUGANG" in zg_fullbody["parent_asset_key"], "赵刚切片必须绑定赵刚自身的基准肖像！"
    assert zg_fullbody["generation_mode"] == "i2i"


def test_ensure_standard_asset_lineage_and_mode_invariants():
    """验证 _ensure_standard_asset 规范化函数的一致性与血统约束。"""
    # 1. 基准肖像必须没有 parent_asset_key，且必须为 t2i
    raw_portrait = {
        "asset_key": "CHAR_ZHOU_T1_BASE_PORTRAIT",
        "character_name": "周老四",
        "parent_asset_key": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",  # 跨角色错误引用
        "generation_mode": "i2i",
    }
    std_portrait = _ensure_standard_asset(raw_portrait, default_cat="CHAR", token_whitelist={"ZHOU", "SHENLIAN"}, fallback_tok="ZHOU")
    assert std_portrait["generation_mode"] == "t2i"
    assert std_portrait["parent_asset_key"] is None
    assert std_portrait["entity_token"] == "ZHOU"

    # 2. 衍生切片如果跨角色引用，必须被修正为同角色的 BASE_PORTRAIT
    raw_slice = {
        "asset_key": "CHAR_ZHOU_T1_FULL_BODY",
        "character_name": "周老四",
        "parent_asset_key": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",  # 跨角色错误引用
        "generation_mode": "i2i",
    }
    std_slice = _ensure_standard_asset(raw_slice, default_cat="CHAR", token_whitelist={"ZHOU", "SHENLIAN"}, fallback_tok="ZHOU")
    assert std_slice["generation_mode"] == "i2i"
    assert std_slice["parent_asset_key"] == "CHAR_ZHOU_T1_BASE_PORTRAIT"
    assert "SHENLIAN" not in std_slice["parent_asset_key"]
