"""三层角色资产领域模型落库专项单元测试 (Character 3-Tier Architecture Unit Tests)

验证范围：
1. Tier 1 (characters): 过滤切片后缀，聚合为唯一自然人主实体，不产生“沈炼(全身定妆照)”等伪角色；
2. Tier 2 (character_stages): 角色形态/造型阶段独立落库，支持 parent_stage_id 继承树与 is_locked_truth；
3. Tier 3 (character_stage_views): 容纳多切片基准视图 (main_portrait, full_body, four_view, facial_macro 等)，准确区分 is_primary；
4. 剧集出场关联 (episode_characters): 仅关联自然人主实体，无切片碎片记录；
5. 音色档案 (character_voice_profiles): 清洗角色名后准确关联至自然人主实体 ID；
6. 资产中心 (assets.metadata): 注入 character_id, character_stage_id, stage_code, view_type, is_master_portrait 双向回溯元数据。
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import text

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    GlobalDramaMasterState,
    IndustrialDramaMasterState,
)
from app.workflows.adapters.drama_storage_adapter import (
    clean_character_name,
    extract_character_tokens,
    parse_character_view_type,
    persist_stage6,
)


def test_helper_functions_character_parsing():
    """测试辅助函数：名称清洗、编码拆解、切片类型识别。"""
    # 1. clean_character_name
    assert clean_character_name("沈炼(全身定妆照)") == "沈炼"
    assert clean_character_name("周妙彤（四视图）") == "周妙彤"
    assert clean_character_name("陆文昭(战损造型)") == "陆文昭"
    assert clean_character_name(" 靳一川 ") == "靳一川"
    assert clean_character_name("裴纶[正脸主肖像]") == "裴纶"
    assert clean_character_name("魏忠贤(主角母音)") == "魏忠贤"

    # 2. extract_character_tokens
    p_code, st_code, v_code = extract_character_tokens("CHAR_SHENLIAN_T1_BASE_COSTUME")
    assert p_code == "SHENLIAN"
    assert st_code == "T1"
    assert v_code == "BASE_COSTUME"

    p_code2, st_code2, v_code2 = extract_character_tokens("CHAR_ZHOU_T2_BATTLE_DAMAGED")
    assert p_code2 == "ZHOU"
    assert st_code2 == "T2"
    assert v_code2 == "BATTLE_DAMAGED"

    # 3. parse_character_view_type
    vt1, lbl1, prim1 = parse_character_view_type("BASE_COSTUME", "全身定妆照")
    assert vt1 == "full_body"
    assert prim1 == 0

    vt2, lbl2, prim2 = parse_character_view_type("PORTRAIT", "正脸主肖像")
    assert vt2 == "main_portrait"
    assert prim2 == 1

    vt3, lbl3, prim3 = parse_character_view_type("FOUR_VIEW", "四视图")
    assert vt3 == "four_view"
    assert prim3 == 0

    vt4, lbl4, prim4 = parse_character_view_type("FACIAL_MACRO", "面部微距")
    assert vt4 == "facial_macro"
    assert prim4 == 0


def test_character_3tier_canonical_aggregation_and_persistence(db_session):
    """验证三层实体架构落库：自然人聚合、形态分层、切片多视图展开。"""
    drama_id = 999
    ep_id = 9991
    ep_num = 1

    # 1. 初始化短剧与剧集记录
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (:did, '绣春刀：修罗战场', 'draft', '{}', '', '')"),
        {"did": drama_id},
    )
    db_session.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, ast_blocks, created_at, updated_at) VALUES (:eid, :did, :ep_num, '第1集：夜雨暗战', '{}', '', '')"),
        {"eid": ep_id, "did": drama_id, "ep_num": ep_num},
    )
    db_session.commit()

    # 2. 模拟 Stage 6 结构化产出数据（含同一个角色的多个切片和形态）
    manifest_data = {
        "episode_num": ep_num,
        "characters": [
            # 沈炼 T1 阶段切片 1: 正脸主肖像
            {
                "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "character_name": "沈炼(正脸主肖像)",
                "role": "protagonist",
                "gender": "男",
                "perceived_age": "30岁",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "正脸特写，锦衣卫飞鱼服，眼神坚毅冷酷，8k超清",
                "voice_style": "低沉冷峻",
                "identity_anchors": ["眉宇右侧细微刀痕", "挺拔鼻梁"],
            },
            # 沈炼 T1 阶段切片 2: 全身定妆照
            {
                "char_id": "CHAR_SHENLIAN_T1_BASE_COSTUME",
                "character_name": "沈炼(全身定妆照)",
                "role": "protagonist",
                "gender": "男",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "全身站姿，飞鱼服绣纹清晰，腰佩绣春刀，全身比例协调",
            },
            # 沈炼 T1 阶段切片 3: 四视图
            {
                "char_id": "CHAR_SHENLIAN_T1_FOUR_VIEW",
                "character_name": "沈炼(四视图)",
                "role": "protagonist",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "正侧背三面及斜向四视图，飞鱼服形制考究",
            },
            # 沈炼 T2 阶段: 战损造型 (继承自 T1)
            {
                "char_id": "CHAR_SHENLIAN_T2_BATTLE_DAMAGED",
                "character_name": "沈炼(残破战损服)",
                "role": "protagonist",
                "stage_name": "残破战损服",
                "stage_code": "T2",
                "parent_asset_id": "T1",
                "visual_prompt": "飞鱼服残破染血，左臂绑带浸血，眼神决绝凌厉",
            },
            # 周妙彤 T1 阶段
            {
                "char_id": "CHAR_ZHOU_T1_MAIN",
                "character_name": "周妙彤",
                "role": "supporting",
                "gender": "女",
                "perceived_age": "22岁",
                "stage_name": "暖阁红裙",
                "stage_code": "T1",
                "visual_prompt": "一袭红裙，容貌倾城，眼带忧郁，琵琶斜抱",
                "voice_style": "温婉清亮略带哀伤",
            },
        ],
        "environments": [],
        "props": [],
        "voice_cards": [
            {
                "name": "沈炼(主角母音)",
                "character_name": "沈炼(主角母音)",
                "character_code": "CHAR_SHENLIAN",
                "voice_id": "VOICE_SHENLIAN_MASTER",
                "timbre": "低沉磁性冷酷",
                "is_master_card": True,
            }
        ],
        "lineage_dag": {
            "CHAR_SHENLIAN_T2_BATTLE_DAMAGED": "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
        },
    }

    state = GlobalDramaMasterState(
        drama_id=drama_id,
        current_visual_episode=ep_num,
        characters_engine={
            "characters": [
                {
                    "character_code": "CHAR_SHENLIAN",
                    "name": "沈炼",
                    "role": "protagonist",
                    "gender": "male",
                    "appearance": "冷峻寸头伤疤，身穿深玄色飞鱼服",
                    "personality": "隐忍刚毅",
                    "description": "北镇抚司锦衣卫",
                },
                # 全剧其他集数角色（未在当集登场）
                {
                    "character_code": "CHAR_ZHENGWEIGUO",
                    "name": "郑卫国",
                    "role": "supporter",
                    "gender": "male",
                    "appearance": "老刑警，面容沧桑有老茧",
                    "personality": "沉稳干练",
                    "description": "老局长",
                },
                {
                    "character_code": "CHAR_WANGXIUQIN",
                    "name": "王秀琴",
                    "role": "witness",
                    "gender": "female",
                    "appearance": "清洁工，头发花白布满皱纹",
                    "personality": "胆小谨慎",
                    "description": "目击证人",
                },
            ]
        },
        episode_resource_manifests={ep_num: EpisodeResourceManifest.model_validate(manifest_data)},
        newly_generated_assets=[
            {
                "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "asset_key": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "name": "沈炼(正脸主肖像)",
                "category": "character",
                "prompt": "正脸特写，锦衣卫飞鱼服，眼神坚毅冷酷，8k超清",
            },
            {
                "asset_id": "CHAR_SHENLIAN_T1_BASE_COSTUME",
                "asset_key": "CHAR_SHENLIAN_T1_BASE_COSTUME",
                "name": "沈炼(全身定妆照)",
                "category": "character",
                "prompt": "全身站姿，飞鱼服绣纹清晰，腰佩绣春刀",
            },
            {
                "asset_id": "CHAR_SHENLIAN_T1_FACIAL_MACRO",
                "asset_key": "CHAR_SHENLIAN_T1_FACIAL_MACRO",
                "name": "沈炼(面部微距)",
                "category": "character",
                "prompt": "沈炼面部微距，瞳孔反光与眼角细纹",
                "image_url": "http://assets.test/shenlian_macro.png",
            },
        ],
        new_character_master_voice_cards=manifest_data["voice_cards"],
        lineage_dag=manifest_data["lineage_dag"],
    )

    # 3. 执行持久化
    persist_stage6(
        db=db_session,
        drama_id=drama_id,
        state=state,
        episode_num=ep_num,
    )

    # -------------------------------------------------------------------------
    # 4. 断言验证 Tier 1 (characters 表)
    # -------------------------------------------------------------------------
    char_rows = db_session.execute(
        text("SELECT id, character_code, name, gender, perceived_age, role, appearance, identity_anchors FROM characters WHERE drama_id = :did ORDER BY name"),
        {"did": drama_id},
    ).mappings().all()

    # 必须严格只有 2 个自然人角色实体：周妙彤、沈炼
    assert len(char_rows) == 2, f"Expected 2 characters, got {[r['name'] for r in char_rows]}"
    char_names = [r["name"] for r in char_rows]
    assert char_names == ["周妙彤", "沈炼"]

    shenlian_char = next(r for r in char_rows if r["name"] == "沈炼")
    assert shenlian_char["gender"] in ("male", "男")
    assert shenlian_char["role"] == "protagonist"
    assert shenlian_char["perceived_age"] in (30, "30", "30岁")
    assert "眉宇右侧细微刀痕" in (shenlian_char["identity_anchors"] or "")

    zhou_char = next(r for r in char_rows if r["name"] == "周妙彤")
    assert zhou_char["gender"] in ("female", "女")
    assert zhou_char["role"] == "supporting"

    # -------------------------------------------------------------------------
    # 5. 断言验证 Tier 2 (character_stages 表)
    # -------------------------------------------------------------------------
    shenlian_stages = db_session.execute(
        text("SELECT id, stage_code, stage_name, parent_stage_id, is_locked_truth FROM character_stages WHERE character_id = :cid ORDER BY stage_code"),
        {"cid": shenlian_char["id"]},
    ).mappings().all()

    # 沈炼应有 2 个形态阶段：T1 (基础飞鱼服常服), T2 (残破战损服)
    assert len(shenlian_stages) == 2, f"Expected 2 stages for 沈炼, got {len(shenlian_stages)}"
    s_t1 = next(s for s in shenlian_stages if s["stage_code"] == "T1")
    s_t2 = next(s for s in shenlian_stages if s["stage_code"] == "T2")

    assert s_t1["is_locked_truth"] == 1
    assert s_t2["parent_stage_id"] == s_t1["id"], f"T2 parent_stage_id ({s_t2['parent_stage_id']}) must point to T1 id ({s_t1['id']})"

    # 周妙彤应有 1 个形态阶段：T1
    zhou_stages = db_session.execute(
        text("SELECT id, stage_code, stage_name FROM character_stages WHERE character_id = :cid"),
        {"cid": zhou_char["id"]},
    ).mappings().all()
    assert len(zhou_stages) == 1
    assert zhou_stages[0]["stage_code"] == "T1"

    # -------------------------------------------------------------------------
    # 6. 断言验证 Tier 3 (character_stage_views 表)
    # -------------------------------------------------------------------------
    t1_views = db_session.execute(
        text("SELECT id, view_type, view_label, image_prompt, is_primary, image_url FROM character_stage_views WHERE character_stage_id = :sid ORDER BY view_type"),
        {"sid": s_t1["id"]},
    ).mappings().all()

    # T1 阶段必须切片展开，包含 main_portrait, full_body, four_view, facial_macro 等
    view_types = [v["view_type"] for v in t1_views]
    assert "main_portrait" in view_types
    assert "full_body" in view_types
    assert "four_view" in view_types
    assert "facial_macro" in view_types

    # 严格检验 is_primary 语义：有且仅有 main_portrait 为 primary (1)
    primary_views = [v for v in t1_views if v["is_primary"] == 1]
    assert len(primary_views) == 1
    assert primary_views[0]["view_type"] == "main_portrait"

    # 非 primary 切片必须为 0
    secondary_views = [v for v in t1_views if v["is_primary"] == 0]
    assert len(secondary_views) >= 3

    # facial_macro 的 image_url 必须正确存入
    macro_view = next(v for v in t1_views if v["view_type"] == "facial_macro")
    assert macro_view["image_url"] == "http://assets.test/shenlian_macro.png"

    # -------------------------------------------------------------------------
    # 7. 断言验证出场关联 (episode_characters 表)
    # -------------------------------------------------------------------------
    ep_char_rows = db_session.execute(
        text("SELECT character_id FROM episode_characters WHERE episode_id = :eid"),
        {"eid": ep_id},
    ).mappings().all()
    ep_char_ids = {r["character_id"] for r in ep_char_rows}
    assert ep_char_ids == {shenlian_char["id"], zhou_char["id"]}

    # -------------------------------------------------------------------------
    # 8. 断言验证角色音色档案 (character_voice_profiles 表 100% 全覆盖保证)
    # -------------------------------------------------------------------------
    voice_rows = db_session.execute(
        text("SELECT character_id, character_name, voice_id, is_master_card FROM character_voice_profiles WHERE drama_id = :did ORDER BY character_id"),
        {"did": drama_id},
    ).mappings().all()
    # 阶段 6 架构保证：本集出场的所有自然人角色（沈炼、周妙彤）均必须拥有全剧母音卡 (is_master_card = 1)
    assert len(voice_rows) == 2, f"必须100%覆盖本集所有出场角色，实际得到: {[r['character_name'] for r in voice_rows]}"
    
    shenlian_vp = next(r for r in voice_rows if r["character_id"] == shenlian_char["id"])
    # 音色卡片中的 "沈炼(主角母音)" 必须通过 clean_character_name 准确映射到沈炼的自然人 ID
    assert shenlian_vp["character_name"] == "沈炼"
    assert shenlian_vp["voice_id"] == "VOICE_SHENLIAN_MASTER"
    assert shenlian_vp["is_master_card"] == 1

    zhou_vp = next(r for r in voice_rows if r["character_id"] == zhou_char["id"])
    assert zhou_vp["character_name"] == "周妙彤"
    assert zhou_vp["is_master_card"] == 1
    assert "ZHOU" in zhou_vp["voice_id"]

    # -------------------------------------------------------------------------
    # 9. 断言验证资产中心回溯 (assets.metadata)
    # -------------------------------------------------------------------------
    costume_asset = db_session.execute(
        text("SELECT metadata FROM assets WHERE drama_id = :did AND asset_key = 'CHAR_SHENLIAN_T1_BASE_COSTUME'"),
        {"did": drama_id},
    ).mappings().first()
    assert costume_asset is not None
    costume_meta = json.loads(costume_asset["metadata"])
    assert costume_meta["character_id"] == shenlian_char["id"]
    assert costume_meta["character_stage_id"] == s_t1["id"]
    assert costume_meta["stage_code"] == "T1"
    assert costume_meta["view_type"] == "full_body"
    assert costume_meta["is_master_portrait"] is False

    portrait_asset = db_session.execute(
        text("SELECT metadata FROM assets WHERE drama_id = :did AND asset_key = 'CHAR_SHENLIAN_T1_BASE_PORTRAIT'"),
        {"did": drama_id},
    ).mappings().first()
    assert portrait_asset is not None
    portrait_meta = json.loads(portrait_asset["metadata"])
    assert portrait_meta["character_id"] == shenlian_char["id"]
    assert portrait_meta["character_stage_id"] == s_t1["id"]
    assert portrait_meta["stage_code"] == "T1"
    assert portrait_meta["view_type"] == "main_portrait"
    assert portrait_meta["is_master_portrait"] is True


def test_character_multi_episode_inheritance_and_reuse(db_session):
    """验证跨集演进：第1集(T1常服) -> 第2集(T2战损服) -> 第3集(T3隐士服) 继承链与自然人唯一性。"""
    drama_id = 998
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (:did, '锦衣夜行', 'draft', '{}', '', '')"),
        {"did": drama_id},
    )
    for ep in (1, 2, 3):
        db_session.execute(
            text("INSERT INTO episodes (id, drama_id, episode_number, title, ast_blocks, created_at, updated_at) VALUES (:eid, :did, :ep, :title, '{}', '', '')"),
            {"eid": 9980 + ep, "did": drama_id, "ep": ep, "title": f"第{ep}集"},
        )
    db_session.commit()

    # --- Episode 1: 沈炼 T1 登场 ---
    ep1_manifest = {
        "episode_num": 1,
        "characters": [
            {
                "char_id": "CHAR_SHENLIAN_T1_PORTRAIT",
                "character_name": "沈炼",
                "gender": "男",
                "role": "protagonist",
                "stage_code": "T1",
                "stage_name": "锦衣卫飞鱼服",
                "visual_prompt": "正脸肖像，英气挺拔",
            }
        ],
        "environments": [],
        "props": [],
    }
    state_ep1 = GlobalDramaMasterState(
        drama_id=drama_id,
        current_visual_episode=1,
        episode_resource_manifests={1: EpisodeResourceManifest.model_validate(ep1_manifest)},
    )
    persist_stage6(db_session, drama_id=drama_id, state=state_ep1, episode_num=1)

    # --- Episode 2: 沈炼演化出 T2 (战损服，继承自 T1) ---
    ep2_manifest = {
        "episode_num": 2,
        "characters": [
            {
                "char_id": "CHAR_SHENLIAN_T2_DAMAGED",
                "character_name": "沈炼(残破战损服)",
                "role": "protagonist",
                "stage_code": "T2",
                "stage_name": "残破战损服",
                "parent_asset_id": "T1",
                "visual_prompt": "飞鱼服撕裂，带有暗红血迹",
            }
        ],
        "environments": [],
        "props": [],
    }
    state_ep2 = GlobalDramaMasterState(
        drama_id=drama_id,
        current_visual_episode=2,
        episode_resource_manifests={2: EpisodeResourceManifest.model_validate(ep2_manifest)},
    )
    persist_stage6(db_session, drama_id=drama_id, state=state_ep2, episode_num=2)

    # --- Episode 3: 沈炼演化出 T3 (隐士粗布衣，继承自 T2) ---
    ep3_manifest = {
        "episode_num": 3,
        "characters": [
            {
                "char_id": "CHAR_SHENLIAN_T3_HERMIT",
                "character_name": "沈炼(隐士粗布衣)",
                "role": "protagonist",
                "stage_code": "T3",
                "stage_name": "隐士粗布衣",
                "parent_stage_id": "T2",
                "visual_prompt": "粗布青衣，斗笠微遮",
            }
        ],
        "environments": [],
        "props": [],
    }
    state_ep3 = GlobalDramaMasterState(
        drama_id=drama_id,
        current_visual_episode=3,
        episode_resource_manifests={3: EpisodeResourceManifest.model_validate(ep3_manifest)},
    )
    persist_stage6(db_session, drama_id=drama_id, state=state_ep3, episode_num=3)

    # 验证 1: characters 表自始至终只有 1 个沈炼自然人实体
    all_chars = db_session.execute(
        text("SELECT id, name FROM characters WHERE drama_id = :did"),
        {"did": drama_id},
    ).mappings().all()
    assert len(all_chars) == 1
    assert all_chars[0]["name"] == "沈炼"
    shenlian_id = all_chars[0]["id"]

    # 验证 2: character_stages 表具有 T1, T2, T3 三个阶段，且继承指针为 T3 -> T2 -> T1 -> 0
    stages = db_session.execute(
        text("SELECT id, stage_code, stage_name, parent_stage_id FROM character_stages WHERE character_id = :cid ORDER BY stage_code"),
        {"cid": shenlian_id},
    ).mappings().all()
    assert len(stages) == 3
    st_t1 = next(s for s in stages if s["stage_code"] == "T1")
    st_t2 = next(s for s in stages if s["stage_code"] == "T2")
    st_t3 = next(s for s in stages if s["stage_code"] == "T3")

    assert st_t1["parent_stage_id"] in (0, None)
    assert st_t2["parent_stage_id"] == st_t1["id"]
    assert st_t3["parent_stage_id"] == st_t2["id"]

    # 验证 3: episode_characters 包含 3 集合计 3 条出场记录，全都指向同一个 shenlian_id
    ep_chars = db_session.execute(
        text("SELECT episode_id, character_id FROM episode_characters WHERE character_id = :cid ORDER BY episode_id"),
        {"cid": shenlian_id},
    ).mappings().all()
    assert len(ep_chars) == 3
    assert {r["episode_id"] for r in ep_chars} == {9981, 9982, 9983}


def test_character_single_four_views_and_asset_key_lineage(db_session):
    """验证需求：
    1. character_stage_views 表中的 asset_key 和 parent_asset_key 必须完整填充；
    2. 全身定妆照 generation_mode 为 i2i (基于肖像图生成)；
    3. 角色四视图必须单张生成（front_view, side_view, back_view, three_quarter_view），
       generation_mode 为 controlnet，parent_asset_key 指向全身定妆照；
    4. 提示词合成器中单张四视图包含 anti-grid / anti-turnaround 约束。
    """
    drama_id = 996
    ep_id = 9961
    ep_num = 1

    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (:did, '绣春刀：单张四视图', 'draft', '{}', '', '')"),
        {"did": drama_id},
    )
    db_session.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, ast_blocks, created_at, updated_at) VALUES (:eid, :did, :ep_num, '第1集', '{}', '', '')"),
        {"eid": ep_id, "did": drama_id, "ep_num": ep_num},
    )
    db_session.commit()

    manifest_data = {
        "episode_num": ep_num,
        "characters": [
            {
                "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "character_name": "沈炼",
                "role": "protagonist",
                "gender": "男",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "正脸特写，锦衣卫飞鱼服，眼神坚毅冷酷",
            },
            {
                "char_id": "CHAR_SHENLIAN_T1_BASE_COSTUME",
                "character_name": "沈炼(全身定妆照)",
                "role": "protagonist",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "全身站姿，飞鱼服绣纹清晰，腰佩绣春刀",
            },
            {
                "char_id": "CHAR_SHENLIAN_T1_4V_FRONT",
                "character_name": "沈炼(正面正身立像)",
                "role": "protagonist",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "单张正面立姿视角",
            },
            {
                "char_id": "CHAR_SHENLIAN_T1_4V_SIDE",
                "character_name": "沈炼(正侧身立像)",
                "role": "protagonist",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "单张正侧面立姿视角",
            },
            {
                "char_id": "CHAR_SHENLIAN_T1_4V_BACK",
                "character_name": "沈炼(背面立像)",
                "role": "protagonist",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "单张背面立姿视角",
            },
            {
                "char_id": "CHAR_SHENLIAN_T1_4V_3Q",
                "character_name": "沈炼(四分之三侧身像)",
                "role": "protagonist",
                "stage_name": "飞鱼服常服",
                "stage_code": "T1",
                "visual_prompt": "单张四分之三侧面立姿视角",
            },
        ],
        "environments": [],
        "props": [],
    }

    state = GlobalDramaMasterState(
        drama_id=drama_id,
        current_visual_episode=ep_num,
        episode_resource_manifests={ep_num: EpisodeResourceManifest.model_validate(manifest_data)},
    )

    persist_stage6(
        db=db_session,
        drama_id=drama_id,
        state=state,
        episode_num=ep_num,
    )

    # 查询角色阶段从表视图
    char_row = db_session.execute(
        text("SELECT id FROM characters WHERE drama_id = :did AND name = '沈炼'"),
        {"did": drama_id},
    ).mappings().first()
    assert char_row is not None

    stage_row = db_session.execute(
        text("SELECT id FROM character_stages WHERE character_id = :cid AND stage_code = 'T1'"),
        {"cid": char_row["id"]},
    ).mappings().first()
    assert stage_row is not None

    views = db_session.execute(
        text("""
            SELECT view_type, asset_key, parent_asset_key, generation_mode, denoise_strength, is_benchmark, is_primary
            FROM character_stage_views
            WHERE character_stage_id = :sid
        """),
        {"sid": stage_row["id"]},
    ).mappings().all()

    view_map = {v["view_type"]: v for v in views}

    # 1. 主视觉肖像 (main_portrait)
    assert "main_portrait" in view_map
    v_main = view_map["main_portrait"]
    assert v_main["asset_key"] == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
    assert v_main["parent_asset_key"] is None
    assert v_main["generation_mode"] == "t2i"
    assert v_main["is_primary"] == 1
    assert v_main["is_benchmark"] == 1

    # 2. 全身定妆照 (full_body) -> 继承自主视觉肖像
    assert "full_body" in view_map
    v_body = view_map["full_body"]
    assert v_body["asset_key"] == "CHAR_SHENLIAN_T1_BASE_COSTUME"
    assert v_body["parent_asset_key"] == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
    assert v_body["generation_mode"] == "i2i"
    assert v_body["is_primary"] == 0

    # 3. 单张四视图：正面、正侧、背面、四分之三侧 -> 继承自全身定妆照
    for v_key, expected_asset_suffix in [
        ("front_view", "4V_FRONT"),
        ("side_view", "4V_SIDE"),
        ("back_view", "4V_BACK"),
        ("three_quarter_view", "4V_3Q"),
    ]:
        assert v_key in view_map, f"Missing view: {v_key}"
        v_item = view_map[v_key]
        assert v_item["asset_key"] == f"CHAR_SHENLIAN_T1_{expected_asset_suffix}"
        assert v_item["parent_asset_key"] == "CHAR_SHENLIAN_T1_BASE_COSTUME"
        assert v_item["generation_mode"] == "controlnet"
        assert v_item["denoise_strength"] == 0.40
        assert v_item["is_primary"] == 0

    # 4. 严格断言当前造型下有且仅有 1 个 is_primary = 1
    primary_views = [v for v in views if v["is_primary"] == 1]
    assert len(primary_views) == 1
    assert primary_views[0]["view_type"] == "main_portrait"


def test_character_t1_base_unique_primary_storage(db_session):
    """验证 T1_BASE 资产被正确存储为 main_portrait，且造型下有且仅有一条 is_primary=1。"""
    drama_id = 997
    ep_num = 2
    ep_id = 9972

    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (:did, '光影测试剧', 'draft', '{}', '', '')"),
        {"did": drama_id},
    )
    db_session.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, ast_blocks, created_at, updated_at) VALUES (:eid, :did, :ep_num, '第2集', '{}', '', '')"),
        {"eid": ep_id, "did": drama_id, "ep_num": ep_num},
    )
    db_session.commit()

    manifest_data = {
        "episode_num": ep_num,
        "characters": [
            {
                "char_id": "CHAR_LUCHEN_T1_BASE",
                "character_name": "陆沉",
                "role": "protagonist",
                "stage_name": "深黑毛呢风衣",
                "stage_code": "T1",
                "view_type": "BASE",
                "visual_prompt": "纯骨相五官，暗灰纯色摄影底板",
            },
            {
                "char_id": "CHAR_LUCHEN_T1_4V_FRONT_FULL",
                "character_name": "陆沉(正面立绘)",
                "role": "protagonist",
                "stage_name": "深黑毛呢风衣",
                "stage_code": "T1",
                "view_type": "4V_FRONT",
                "visual_prompt": "全身站姿正面立绘，深黑毛呢风衣",
            },
            {
                "char_id": "CHAR_LUCHEN_T2_4V_PROFILE",
                "character_name": "陆沉(正侧面)",
                "role": "protagonist",
                "stage_name": "深黑毛呢风衣",
                "stage_code": "T1",
                "view_type": "4V_PROFILE",
                "visual_prompt": "正侧面90度侧视立绘",
            },
            {
                "char_id": "CHAR_LUCHEN_T2_EXP_RAGE",
                "character_name": "陆沉(暴怒表情)",
                "role": "protagonist",
                "stage_name": "深黑毛呢风衣",
                "stage_code": "T1",
                "view_type": "EXP_RAGE",
                "visual_prompt": "眼角充血，下颌紧咬，暴怒微表情",
            },
        ],
        "environments": [],
        "props": [],
    }

    state = GlobalDramaMasterState(
        drama_id=drama_id,
        current_visual_episode=ep_num,
        episode_resource_manifests={ep_num: EpisodeResourceManifest.model_validate(manifest_data)},
    )

    persist_stage6(
        db=db_session,
        drama_id=drama_id,
        state=state,
        episode_num=ep_num,
    )

    char_row = db_session.execute(
        text("SELECT id FROM characters WHERE drama_id = :did AND name = '陆沉'"),
        {"did": drama_id},
    ).mappings().first()
    assert char_row is not None

    stage_row = db_session.execute(
        text("SELECT id FROM character_stages WHERE character_id = :cid AND stage_code = 'T1'"),
        {"cid": char_row["id"]},
    ).mappings().first()
    assert stage_row is not None

    views = db_session.execute(
        text("""
            SELECT id, view_type, asset_key, is_benchmark, is_primary
            FROM character_stage_views
            WHERE character_stage_id = :sid
        """),
        {"sid": stage_row["id"]},
    ).mappings().all()

    view_map = {v["view_type"]: v for v in views}
    assert "main_portrait" in view_map
    assert "CHAR_LUCHEN_T1_BASE" in view_map["main_portrait"]["asset_key"]
    assert view_map["main_portrait"]["is_primary"] == 1

    primary_views = [v for v in views if v["is_primary"] == 1]
    assert len(primary_views) == 1
    assert primary_views[0]["view_type"] == "main_portrait"

    # 其他所有视图 is_primary 均为 0
    non_primary = [v for v in views if v["is_primary"] == 0]
    assert len(non_primary) == len(views) - 1

