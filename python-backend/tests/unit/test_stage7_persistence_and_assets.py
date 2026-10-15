"""测试两程九阶 Stage 7 三表持久化、Stage 6 资产映射关联与全保真水合还原。

核心验证点：
1. Stage 7 提示词白名单构建（_build_stage6_asset_whitelist_block）与资产 Token 归一化修正；
2. 真实 SQLite 内存库下 storyboards / storyboard_props / storyboard_characters 三表原子写入：
   - storyboards.scene_id 精确绑定 Stage 6 scenes.id；
   - storyboards.characters JSON 数组存储 Stage 6 characters.id；
   - storyboard_characters.character_id 精确绑定 Stage 6 character_libraries.id；
   - storyboard_props.prop_id 精确绑定 Stage 6 props.id（无 created_at 列）；
3. 幂等重跑时先清理子表（storyboard_props / storyboard_characters）再清理主表（storyboards），无孤儿脏数据；
4. load_episode_substate_slice 与 load_episode_visual_package 从三表全保真水合 StoryboardShot 对象，
   且 StoryboardShot 兼容旧版 StoryboardShotStub 属性（shot_number, visual_description, dialogue_text, keyframe_image_ref）；
5. TwoJourneyRunner._process_episode 执行完 Stage 7 后立即调用 persist_stage7 落库。
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.schema import ensure_schema
from app.platform_common import now_iso
from app.schemas.script_graph_state import (
    CharacterAnchorStub,
    EpisodeScopedSubState,
    PropAnchorStub,
    SceneAnchorStub,
    StoryboardShot,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_episode_substate_slice,
    load_episode_visual_package,
    persist_episode_substate_slice,
    persist_stage6,
    persist_stage7,
)
from app.workflows.nodes.stage7_storyboard_srt import (
    _build_stage6_asset_whitelist_block,
    stage7_storyboard_srt_node,
)


@pytest.fixture()
def sqlite_db():
    """创建包含完整业务表结构的内存 SQLite 会话。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        ensure_schema(conn)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_drama_and_stage6_assets(db) -> int:
    """初始化剧集、第1集以及 Stage 6 落库的角色、角色库、场景、道具资产。"""
    now = now_iso()
    db.execute(
        text(
            "INSERT INTO dramas (id, title, status, total_episodes, created_at, updated_at) "
            "VALUES (1, '测试短剧', 'draft', 10, :now, :now)"
        ),
        {"now": now},
    )
    db.execute(
        text(
            "INSERT INTO episodes (id, drama_id, episode_number, title, status, duration, script_content, ast_blocks, created_at, updated_at) "
            "VALUES (10, 1, 1, '第1集：雨夜交锋', 'draft', 120, '【场景】废弃仓库\n沈墨手持青铜密钥质问苏晚。', '{}', :now, :now)"
        ),
        {"now": now},
    )
    db.commit()

    # 使用 persist_stage6 写入标准 Stage 6 视觉资产与全局角色库
    stage6_payload = {
        "current_visual_episode": 1,
        "manifest": {
            "characters": [
                {
                    "asset_id": "CHAR_SHENMO_T1_BASE_PORTRAIT",
                    "name": "沈墨",
                    "character_token": "SHENMO",
                    "role_type": "protagonist",
                    "visual_prompt": "冷峻青年，黑色风衣，眼神锐利",
                    "identity_anchors": "右眉微断疤痕",
                },
                {
                    "asset_id": "CHAR_SUWAN_T1_BASE_PORTRAIT",
                    "name": "苏晚",
                    "character_token": "SUWAN",
                    "role_type": "protagonist",
                    "visual_prompt": "清冷长发女子，米色高领风衣",
                    "identity_anchors": "银色耳坠",
                },
            ],
            "environments": [
                {
                    "asset_id": "ENV_WAREHOUSE_T1_WIDE",
                    "scene_code": "WAREHOUSE",
                    "benchmark_asset_key": "ENV_WAREHOUSE_T1_WIDE",
                    "location_name": "废弃仓库",
                    "scene_token": "WAREHOUSE",
                    "time_of_day": "暴雨深夜",
                    "visual_prompt": "空旷破败的钢铁仓库，雨水从天窗滴落",
                    "lighting_style": "冷蓝侧逆光",
                }
            ],
            "props": [
                {
                    "asset_id": "PROP_BRONZEKEY_T1_STATIC",
                    "prop_code": "BRONZEKEY",
                    "benchmark_asset_key": "PROP_BRONZEKEY_T1_STATIC",
                    "name": "青铜密钥",
                    "prop_token": "BRONZEKEY",
                    "tier": "T1",
                    "visual_prompt": "刻有暗纹的古旧青铜钥匙",
                }
            ],
        },
    }
    persist_stage6(db, 1, stage6_payload)
    return 1


def test_stage6_whitelist_builder_and_stage7_substate_normalization():
    """测试 Stage 7 从 EpisodeScopedSubState 提取 Stage 6 锚点白名单并归一化非标资产引用。"""
    substate = EpisodeScopedSubState(
        drama_id=1,
        episode_number=1,
        relevant_character_stubs=[
            CharacterAnchorStub(
                character_id="CHAR_SHENMO_T1_BASE_PORTRAIT",
                name="沈墨",
                archetype="男主",
                visual_token="黑色风衣冷峻青年",
            ),
            CharacterAnchorStub(
                character_id="CHAR_SUWAN_T1_BASE_PORTRAIT",
                name="苏晚",
                archetype="女主",
                visual_token="清冷长发女子",
            ),
        ],
        relevant_scene_stubs=[
            SceneAnchorStub(
                scene_id="ENV_WAREHOUSE_T1_WIDE",
                name="废弃仓库",
                color_tone="冷蓝暗调",
                weathering_summary="铁锈斑驳",
            )
        ],
        relevant_prop_stubs=[
            PropAnchorStub(
                prop_id="PROP_BRONZEKEY_T1_STATIC",
                name="青铜密钥",
                level="T1",
                visual_token="古旧青铜钥匙",
            )
        ],
    )

    whitelist_text = _build_stage6_asset_whitelist_block(
        {},
        [
            {"name": "沈墨", "character_token": "SHENMO", "asset_id": "CHAR_SHENMO_T1_BASE_PORTRAIT"},
        ],
        [
            {"location_name": "废弃仓库", "scene_token": "WAREHOUSE", "asset_id": "ENV_WAREHOUSE_T1_WIDE"},
        ],
        [
            {"name": "青铜密钥", "prop_token": "BRONZEKEY", "asset_id": "PROP_BRONZEKEY_T1_STATIC"},
        ],
    )
    assert "CHAR_SHENMO_T1_BASE_PORTRAIT" in whitelist_text
    assert "ENV_WAREHOUSE_T1_WIDE" in whitelist_text
    assert "PROP_BRONZEKEY_T1_STATIC" in whitelist_text

    res = stage7_storyboard_srt_node(substate)
    shots = res["storyboard_shots"]
    assert len(shots) >= 3
    for shot in shots:
        assert isinstance(shot, StoryboardShot)
        # 验证向后兼容属性
        assert shot.shot_number == shot.shot_id
        assert isinstance(shot.visual_description, str)
        assert isinstance(shot.dialogue_text, str)
        assert isinstance(shot.keyframe_image_ref, str)


def test_stage7_3table_persistence_cascade_delete_and_full_rehydration(sqlite_db):
    """测试 Stage 7 三表原子落库、Stage 6 外键精确映射、幂等重跑级联清理与全保真水合还原。"""
    drama_id = _seed_drama_and_stage6_assets(sqlite_db)

    substate = load_episode_substate_slice(sqlite_db, drama_id, 1)
    assert len(substate.relevant_character_stubs) == 2
    assert len(substate.relevant_scene_stubs) == 1
    assert len(substate.relevant_prop_stubs) == 1

    # 构造 2 个包含完整 Stage 6 资产引用的分镜（模式 B 多图参考 + 模式 A 首尾帧）
    shot1 = StoryboardShot(
        shot_id=1,
        timecode="00:00:00,000 --> 00:00:04,000",
        duration_sec=4.0,
        framing="MCU 中近景",
        camera_angle="Eye-level 平视",
        camera_motion="慢速推镜",
        generation_mode="multi_image_reference",
        target_engine="seedance2.5",
        rationale="起幅 1.0s + 台词 2.6s + 闭嘴缓冲 0.4s = 4.0s",
        speech_inpoint_sec=0.3,
        contextual_tts_prompt="[沈墨_VOICE, 低沉冷冽]",
        is_dialogue_complete_in_shot=True,
        audio={
            "dialogue": "沈墨：把青铜密钥交出来，否则今晚谁也别想离开仓库！",
            "foley": "[Foley+3dB: 暴雨砸落铁皮屋顶声与皮靴踩水声]",
            "music": "LEITMOTIF_01_TENSION",
            "speech_inpoint_sec": 0.3,
            "contextual_tts_prompt": "[沈墨_VOICE, 低沉冷冽]",
            "is_dialogue_complete_in_shot": True,
        },
        multi_image_config={
            "reference_assets": [
                "ENV_WAREHOUSE_T1_WIDE",
                "CHAR_SHENMO_T1_BASE_PORTRAIT",
                "CHAR_SUWAN_T1_BASE_PORTRAIT",
                "PROP_BRONZEKEY_T1_STATIC",
            ],
            "video_prompt": "在图1废弃仓库中，图2手持图4冷冷注视着图3开口质问（音频1）。无肢体畸变、无五官崩坏。",
            "audit": "PASS_9",
        },
        lipsync_dynamics={
            "speaker": "沈墨",
            "jaw_open_scale": 0.65,
            "mouth_tension": "紧绷",
            "head_subtle_motion": "微沉",
        },
    )
    shot2 = StoryboardShot(
        shot_id=2,
        timecode="00:00:04,000 --> 00:00:07,000",
        duration_sec=3.0,
        framing="ECU 大特写",
        camera_angle="High-angle 俯拍",
        camera_motion="固定微距",
        generation_mode="first_last_frame",
        target_engine="seedance2.5",
        rationale="纯动作特写 3.0s",
        speech_inpoint_sec=0.3,
        is_dialogue_complete_in_shot=True,
        audio={
            "dialogue": "",
            "foley": "[Foley+3dB: 青铜金属碰撞清脆声]",
            "music": "LEITMOTIF_01_TENSION",
        },
        first_last_config={
            "first_frame_asset_id": "CHAR_SUWAN_T1_BASE_PORTRAIT",
            "last_frame_asset_id": "PROP_BRONZEKEY_T1_STATIC",
            "first_frame_prompt": "苏晚指尖紧握青铜密钥",
            "last_frame_prompt": "青铜密钥滑落积水地面",
            "motion_vector_prompt": "特写慢镜头滑落溅起水花",
        },
    )

    substate.storyboard_shots = [shot1, shot2]
    substate.srt_content = (
        "1\n00:00:00,300 --> 00:00:03,800\n沈墨：把青铜密钥交出来，否则今晚谁也别想离开仓库！\n"
    )

    # 1. 执行 persist_stage7
    persist_stage7(sqlite_db, drama_id, substate)

    # 验证 storyboards 主表
    sb_rows = sqlite_db.execute(
        text("SELECT * FROM storyboards WHERE episode_id = 10 AND deleted_at IS NULL ORDER BY storyboard_number ASC")
    ).mappings().all()
    assert len(sb_rows) == 2

    sb1 = dict(sb_rows[0])
    assert sb1["scene_id"] is not None  # 必须关联到 Stage 6 废弃仓库的 scene.id
    assert sb1["location"] == "废弃仓库"
    # 验证 title 与 time 解析：time 绝不能被时码污染，必须继承/解析为自然时段；title 必须具备戏剧动作标题
    assert "-->" not in str(sb1["time"])
    assert sb1["time"] in ("深夜暴雨", "日景/白天")
    assert sb1["title"] != ""
    char_ids_in_sb1 = json.loads(sb1["characters"])
    assert len(char_ids_in_sb1) == 2  # 沈墨 + 苏晚 的 characters.id

    # 验证 storyboard_characters 关联表（外键指向 character_libraries.id）
    sc_rows = sqlite_db.execute(
        text("SELECT * FROM storyboard_characters ORDER BY id ASC")
    ).mappings().all()
    assert len(sc_rows) == 3  # Shot 1 有 2 个角色，Shot 2 有 1 个角色(苏晚)
    lib_ids = {
        r["id"]
        for r in sqlite_db.execute(text("SELECT id FROM character_libraries")).mappings().all()
    }
    for r in sc_rows:
        assert r["character_id"] in lib_ids

    # 验证 storyboard_props 关联表（外键指向 props.id）
    sp_rows = sqlite_db.execute(
        text("SELECT * FROM storyboard_props")
    ).mappings().all()
    assert len(sp_rows) == 2  # Shot 1 与 Shot 2 均引用了青铜密钥
    prop_ids = {
        r["id"]
        for r in sqlite_db.execute(text("SELECT id FROM props WHERE drama_id = 1")).mappings().all()
    }
    for r in sp_rows:
        assert r["prop_id"] in prop_ids

    # 2. 验证幂等重跑与绝对覆盖（再次重跑且镜头数量由 2 改为 1 时，必须严格覆盖，绝不追加）
    single_shot_substate = substate.model_copy(deep=True)
    single_shot_substate.storyboard_shots = [substate.storyboard_shots[0]]  # 仅剩 1 镜
    persist_stage7(sqlite_db, drama_id, single_shot_substate)

    sb_rows_after = sqlite_db.execute(
        text("SELECT * FROM storyboards WHERE episode_id = 10 AND deleted_at IS NULL")
    ).mappings().all()
    sc_rows_after = sqlite_db.execute(text("SELECT * FROM storyboard_characters")).mappings().all()
    sp_rows_after = sqlite_db.execute(text("SELECT * FROM storyboard_props")).mappings().all()
    fp_rows_after = sqlite_db.execute(text("SELECT * FROM frame_prompts")).mappings().all()
    sa_rows_after = sqlite_db.execute(text("SELECT * FROM storyboard_audios")).mappings().all()
    ss_rows_after = sqlite_db.execute(text("SELECT * FROM storyboard_subtitles")).mappings().all()

    # 严格覆盖断言：从原有的 2 镜缩减为 1 镜，全部从表与主表必须完全同步缩减，绝不追加或残留
    assert len(sb_rows_after) == 1
    assert len(sc_rows_after) == 2  # Shot 1 的 2 个角色 (沈墨、苏晚)
    assert len(sp_rows_after) == 1  # Shot 1 的 1 个道具 (青铜密钥)
    assert len(fp_rows_after) == 1  # Shot 1 的 1 个 frame_prompt
    assert len(sa_rows_after) == 2  # Shot 1 包含台词轨(dialogue)与拟音轨(foley)共 2 条音频
    assert len(ss_rows_after) == 1  # Shot 1 的 1 个 subtitle (台词字幕)

    # 恢复 2 镜再次重跑，验证从 1 镜扩充回 2 镜的覆盖能力
    persist_episode_substate_slice(sqlite_db, drama_id, substate)
    sb_rows_2 = sqlite_db.execute(text("SELECT * FROM storyboards WHERE episode_id = 10")).mappings().all()
    sc_rows_2 = sqlite_db.execute(text("SELECT * FROM storyboard_characters")).mappings().all()
    sp_rows_2 = sqlite_db.execute(text("SELECT * FROM storyboard_props")).mappings().all()
    assert len(sb_rows_2) == 2
    assert len(sc_rows_2) == 3
    assert len(sp_rows_2) == 2

    # 3. 验证全保真水合还原（load_episode_substate_slice & load_episode_visual_package）
    rehydrated_substate = load_episode_substate_slice(sqlite_db, drama_id, 1)
    assert len(rehydrated_substate.storyboard_shots) == 2
    r_shot1 = rehydrated_substate.storyboard_shots[0]
    assert isinstance(r_shot1, StoryboardShot)
    assert r_shot1.shot_id == 1
    assert r_shot1.shot_number == 1
    assert r_shot1.generation_mode == "multi_image_reference"
    assert r_shot1.target_engine == "seedance2.5"
    assert r_shot1.multi_image_config["audit"] == "PASS_9"
    assert "ENV_WAREHOUSE_T1_WIDE" in r_shot1.multi_image_config["reference_assets"]
    assert "CHAR_SHENMO_T1_BASE_PORTRAIT" in r_shot1.multi_image_config["reference_assets"]
    assert "PROP_BRONZEKEY_T1_STATIC" in r_shot1.multi_image_config["reference_assets"]
    assert r_shot1.lipsync_dynamics is not None
    assert r_shot1.lipsync_dynamics.get("jaw_open_scale") == 0.65

    vis_pkg = load_episode_visual_package(sqlite_db, drama_id, 1)
    assert len(vis_pkg["storyboard_shots"]) == 2
    assert vis_pkg["storyboard_shots"][1].generation_mode == "first_last_frame"
    assert vis_pkg["storyboard_shots"][1].first_last_config["last_frame_asset_id"] == "PROP_BRONZEKEY_T1_STATIC"


def test_stage7_tier3_subtable_lineage_and_cascades(sqlite_db):
    """测试阶段 7 与阶段 6 三级实体切片 (L1-L2-L3) 的精准级联持久化。

    验证：
    1. storyboards 表正确记录 scene_zone_id (L2) 与 scene_weathering_view_id (L3)；
    2. storyboard_characters 表正确记录 character_stage_id (L2) 与 stage_view_id (L3)；
    3. storyboard_props 表正确记录 damage_state_id (L2) 与 prop_detail_view_id (L3)；
    4. storyboard_audios 表正确记录 character_stage_id。
    """
    now = now_iso()
    # 1. 播种 drama 与 episode
    sqlite_db.execute(
        text("INSERT INTO dramas (id, title, status, total_episodes, created_at, updated_at) VALUES (2, '三级资产测试剧', 'draft', 5, :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, status, duration, script_content, ast_blocks, created_at, updated_at) VALUES (20, 2, 1, '第1集', 'draft', 60, '...', '{}', :now, :now)"),
        {"now": now},
    )

    # 2. 播种场景三级体系：scenes -> scene_zones -> scene_weathering_views
    sqlite_db.execute(
        text("INSERT INTO scenes (id, drama_id, episode_id, location, time, scene_code, benchmark_asset_key, created_at, updated_at) VALUES (101, 2, 20, '地下实验室', '暴雨夜', 'ENV_LAB_01', 'ENV_LAB_01_WIDE', :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO scene_zones (id, drama_id, scene_id, zone_code, zone_name, time_lighting, created_at, updated_at) VALUES (201, 2, 101, 'ENV_LAB_Z01', '离心机操控区', '深夜暴雨冷蓝泛光', :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO scene_weathering_views (id, scene_zone_id, asset_key, layer_type, description, visual_prompt, created_at, updated_at) VALUES (301, 201, 'ENV_LAB_Z01_RAIN_NIGHT', 'weathering', '冷蓝侧光', '暴雨夜冷蓝侧逆光透窗', :now, :now)"),
        {"now": now},
    )

    # 3. 播种角色三级体系：characters -> character_stages -> character_stage_views
    sqlite_db.execute(
        text("INSERT INTO characters (id, drama_id, name, character_code, benchmark_asset_key, created_at, updated_at) VALUES (401, 2, '陆辰', 'CHAR_LUCHEN', 'CHAR_LUCHEN_T1_BASE', :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO character_libraries (id, drama_id, name, source_type, source_id, created_at, updated_at) VALUES (501, 2, '陆辰', 'stage6_character', '401', :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO character_stages (id, drama_id, character_id, stage_code, stage_name, costume_description, created_at, updated_at) VALUES (601, 2, 401, 'CHAR_LUCHEN_T1', '落魄科研员造型', '破旧防辐射服', :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO character_stage_views (id, character_stage_id, asset_key, view_type, view_label, image_prompt, image_url, created_at, updated_at) VALUES (701, 601, 'CHAR_LUCHEN_T1_4V_FRONT', '4v_front', '正面立绘', '冷峻正面肖像', 'https://asset.test/front.png', :now, :now)"),
        {"now": now},
    )

    # 4. 播种道具三级体系：props -> prop_damage_states -> prop_detail_views
    sqlite_db.execute(
        text("INSERT INTO props (id, drama_id, name, prop_code, benchmark_asset_key, created_at, updated_at) VALUES (801, 2, '量子核芯', 'PROP_CORE', 'PROP_CORE_S0', :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO prop_damage_states (id, drama_id, prop_id, state_code, state_label, damage_level, created_at, updated_at) VALUES (901, 2, 801, 'PROP_CORE_S1_CRACKED', '开裂过载', 1, :now, :now)"),
        {"now": now},
    )
    sqlite_db.execute(
        text("INSERT INTO prop_detail_views (id, damage_state_id, asset_key, view_type, visual_prompt, created_at, updated_at) VALUES (1001, 901, 'PROP_CORE_S1_MACRO_GLOW', 'macro', '发光开裂特写', :now, :now)"),
        {"now": now},
    )
    sqlite_db.commit()

    # 5. 构造引用了三级切片 Key 的分镜
    substate = EpisodeScopedSubState(
        drama_id=2,
        episode_number=1,
        storyboard_shots=[
            StoryboardShot(
                shot_id=1,
                timecode="00:00:00,000 --> 00:00:03,000",
                duration_sec=3.0,
                generation_mode="multi_image_reference",
                multi_image_config={
                    "reference_assets": [
                        "ENV_LAB_Z01_RAIN_NIGHT",    # 场景三级做旧切片
                        "CHAR_LUCHEN_T1_4V_FRONT",    # 角色三级正面切片
                        "PROP_CORE_S1_MACRO_GLOW",    # 道具三级特写切片
                    ],
                    "video_prompt": "在图1操纵台前，图2身穿防护服凝视图3发光的开裂核芯（音频1）。",
                },
                audio={
                    "dialogue": "陆辰：能量还在上升，必须马上手动降载！",
                },
            )
        ],
    )

    # 6. 持久化落库
    persist_stage7(sqlite_db, 2, substate)

    # 7. 断言验证：三级外键全部正确命中并透传落库
    sb = dict(sqlite_db.execute(text("SELECT * FROM storyboards WHERE episode_id = 20")).mappings().first())
    assert sb["scene_id"] == 101
    assert sb["scene_zone_id"] == 201
    assert sb["scene_weathering_view_id"] == 301
    assert sb["scene_asset_key"] == "ENV_LAB_Z01_RAIN_NIGHT"

    sbc = dict(sqlite_db.execute(text("SELECT * FROM storyboard_characters WHERE storyboard_id = :sb_id"), {"sb_id": sb["id"]}).mappings().first())
    assert sbc["character_id"] == 401
    assert sbc["character_stage_id"] == 601
    assert sbc["stage_view_id"] == 701
    assert sbc["asset_key"] == "CHAR_LUCHEN_T1_4V_FRONT"

    sbp = dict(sqlite_db.execute(text("SELECT * FROM storyboard_props WHERE storyboard_id = :sb_id"), {"sb_id": sb["id"]}).mappings().first())
    assert sbp["prop_id"] == 801
    assert sbp["damage_state_id"] == 901
    assert sbp["prop_detail_view_id"] == 1001
    assert sbp["asset_key"] == "PROP_CORE_S1_MACRO_GLOW"

    sba = dict(sqlite_db.execute(text("SELECT * FROM storyboard_audios WHERE storyboard_id = :sb_id"), {"sb_id": sb["id"]}).mappings().first())
    assert sba["character_id"] == 401
    assert sba["character_stage_id"] == 601
    assert sba["speaker_name"] == "陆辰"
