"""单元测试：验证两程九阶工业化状态存储适配器 (drama_storage_adapter.py)。

验证数据库零破坏兼容策略：
1. 阶段 1~5 第一程状态双向持久化与反序列化幂等；
2. 阶段 6~8 第二程单集视听工程包双向持久化与反序列化幂等；
3. SQLite 纯内存零副作用快速自测。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.schema import ensure_schema
from app.schemas.script_graph_state import (
    AudioBible,
    AudioMotifItem,
    CandidateTitleMatrix,
    DoubleTrackProhibitions,
    EpisodeResourceManifest,
    EpisodeScriptV2,
    IndustrialDramaMasterState,
    RedBlueAuditReport,
    StoryboardShot,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_episode_visual_package,
    load_first_journey_state,
    persist_episode_visual_package,
    persist_first_journey_state,
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
                VALUES (1, '测试暂定剧名', '悬疑犯罪', '真人电影/超写实', 12, 'draft', '2026-09-14T00:00:00Z', '2026-09-14T00:00:00Z')
            """)
        )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_first_journey_state_roundtrip(db_session: Session):
    """测试第一程文学故事工程（阶段 1~5）成果落库与重构。"""
    state = IndustrialDramaMasterState(
        drama_id=1,
        journey="journey_1_literary",
        current_stage=5,
        selected_title="夜幕熔炉",
        candidate_titles=CandidateTitleMatrix(
            identity_contrast=["夜幕熔炉", "冰点证词"],
            extreme_suspense=["死者未亡", "404熔炉"],
            prop_irony=["带血的扳手", "生锈的工牌"],
            dark_psychology=["第三个嫌疑人", "伪装者之死"],
        ),
        aspect_ratio="9:16",
        target_duration_sec=120.0,
        visual_style="工业悬疑/冷峻暗色调",
        negative_rules=DoubleTrackProhibitions(),
        logline="下岗老刑警在废弃钢铁厂发现十五年前自己亲手结案的凶器，被迫与当年受害者的孤女联手暗查真相。",
        dramatic_irony="观众明知真凶就在身边，主角却一步步踩入陷阱",
        grand_payoff="最后一秒在炉火映照下撕碎伪证，完成复仇与救赎",
        short_memory_a="严禁亲子鉴定撕毁，坚守冷峻暗色调",
        short_memory_b="陈卫国随身携带磨损严重的1998年英雄牌钢笔",
        short_memory_c="第1波次核心任务：发现铁水中的骸骨",
        short_memory_d="全季12集：第1-3集起疑，第4-6集被构陷，第7-9集反杀，第10-12集终局",
        characters_engine={
            "characters": [
                {
                    "name": "陈卫国",
                    "role_type": "protagonist",
                    "personality": "固执、自责、观察入微但患有严重创伤后应激障碍",
                    "appearance": "五十岁上下，花白寸头，深灰色起球毛衣，右手食指有常年握枪的老茧",
                    "identity_anchors": ["花白寸头", "右手指茧", "深灰毛衣"],
                    "voice_style": "低沉沙哑，烟嗓，咬字偏慢",
                    "psychological_quad": {
                        "want": "证明自己当年没有办错案",
                        "need": "直面当年的自私懦弱并给予死者公道",
                        "lie": "只要严格按规矩办就不会出错",
                        "ghost": "十五年前因赶着回家看生病的女儿导致关键现场被破坏",
                    },
                }
            ]
        },
        environments_and_props={
            "environments": [
                {
                    "location_name": "红星炼钢厂3号车间高炉平台",
                    "time_and_lighting": "凌晨4点，阴冷深蓝，远处熔炉散发暗红余烬光",
                    "visual_prompt": "废弃重工业车间，锈迹斑斑的高炉管道，昏暗工业蒸汽，电影级胶片质感",
                    "weathering_layers": {"structural": "锈蚀钢梁", "living": "散落的空烟盒与劳保手套", "optical": "冰蓝与炉火暗红交织"},
                    "atmosphere": "窒息、死寂、冷冽",
                }
            ],
            "props": [
                {
                    "name": "生锈的1998年工牌",
                    "type": "narrative_reversal",
                    "description": "表面带有干涸铁锈色血迹的劳保铜质工牌，边角有被烈火灼烧的卷曲",
                    "visual_prompt": "近景特写，金属铜制工牌，刻有工号0417，斑驳血迹与火灼黑印",
                    "damage_scale": "70%氧化锈蚀，右下角火烧变形",
                    "foley_resistance": "金属与粗糙水泥地面摩擦的尖锐刺耳声 (+3dB)",
                }
            ],
        },
        audio_bible=AudioBible(
            leitmotifs=[
                AudioMotifItem(
                    motif_id="LEITMOTIF_01_SUSPENSE",
                    name="熔炉低鸣与命运倒计时",
                    instrumentation="大提琴低音单音长鸣 + 工业金属微弱撞击 + 40Hz次低频脉冲",
                    tempo_bpm="72",
                    musical_key="D minor",
                    dramatic_function="危机迫近与阶层压迫时刻触发",
                )
            ]
        ),
        season_outlines={
            1: {"title": "深渊来电", "hook_3s": "高炉内挖出未熔化的铁骷髅", "cliffhanger": "工牌主人竟是主角死去的师父"}
        },
        current_mini_arc_index=1,
        total_episodes=12,
        completed_screenplays={
            1: {
                "episode_number": 1,
                "title": "深渊来电",
                "duration_seconds": 120,
                "safety_guardrails_lock": {"subtext_matrix": {}, "friction_and_cost_preset": "严冬冻疮裂开流血"},
                "scenes": [
                    {
                        "scene_index": 1,
                        "location": "3号车间",
                        "action_and_dialogue": ["陈卫国用手电照向焦黑的铁块"],
                    }
                ],
                "dramatic_rhythm_check": {"hook_3s": "焦黑残骸暴露", "micro_turning_point_45s": "发现工号", "killer_cliffhanger_115s": "对讲机突然传出死者声音"},
                "episode_end_physical_delta": {
                    "character_pose": "陈卫国手握手电筒僵立，右手颤抖",
                    "held_prop": "生锈工牌紧捏在指缝中，血从指缝渗出",
                    "environment_state": "高炉排风扇发出沉闷的吱嘎声，风卷起地上的灰烬",
                },
            }
        },
        inter_episode_physical_snapshot={
            "character_pose": "陈卫国手握手电筒僵立，右手颤抖",
            "held_prop": "生锈工牌紧捏在指缝中，血从指缝渗出",
            "environment_state": "高炉排风扇发出沉闷的吱嘎声，风卷起地上的灰烬",
        },
        literary_journey_locked=True,
    )

    # 1. 执行落库
    persist_first_journey_state(db_session, drama_id=1, state=state)
    db_session.commit()

    # 2. 从数据库加载重构
    loaded_state = load_first_journey_state(db_session, drama_id=1)

    # 3. 验证字段一致性
    assert loaded_state.selected_title == "夜幕熔炉"
    assert loaded_state.visual_style == "工业悬疑/冷峻暗色调"
    assert loaded_state.literary_journey_locked is True
    assert len(loaded_state.candidate_titles.identity_contrast) == 2
    assert len(loaded_state.negative_rules.forbidden_cliches) >= 10
    assert loaded_state.inter_episode_physical_snapshot["held_prop"] == "生锈工牌紧捏在指缝中，血从指缝渗出"
    
    # 验证角色
    assert len(loaded_state.characters_engine.get("characters", [])) == 1
    char_loaded = loaded_state.characters_engine["characters"][0]
    assert char_loaded["name"] == "陈卫国"
    assert char_loaded["psychological_quad"]["lie"] == "只要严格按规矩办就不会出错"

    # 验证场景与道具
    assert len(loaded_state.environments_and_props.get("environments", [])) == 1
    assert loaded_state.environments_and_props["environments"][0]["location_name"] == "红星炼钢厂3号车间高炉平台"
    assert len(loaded_state.environments_and_props.get("props", [])) == 1
    assert loaded_state.environments_and_props["props"][0]["name"] == "生锈的1998年工牌"

    # 验证文学剧本
    assert 1 in loaded_state.completed_screenplays
    assert loaded_state.completed_screenplays[1]["title"] == "深渊来电"
    assert loaded_state.completed_screenplays[1]["dramatic_rhythm_check"]["killer_cliffhanger_115s"] == "对讲机突然传出死者声音"


def test_episode_visual_package_roundtrip(db_session: Session):
    """测试第二程单集视听工程包（阶段 6~8）落库与重构。"""
    # 先确保第 1 集存在
    db_session.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title) VALUES (101, 1, 1, '深渊来电')")
    )
    db_session.commit()

    manifest = EpisodeResourceManifest(
        characters_tier_1=[{"asset_id": "CHAR_CWG_BASE", "name": "陈卫国"}],
        environments_primary=[{"asset_id": "ENV_FURNACE_01", "name": "3号车间高炉平台"}],
        props_narrative=[{"asset_id": "PROP_BADGE_01", "name": "生锈工牌"}],
    )

    shot1 = StoryboardShot(
        shot_id=1,
        timecode="00:00:00,000 --> 00:00:03,000",
        duration_sec=3.0,
        framing="CU 特写",
        camera_motion="Slow Push-in 缓慢推进",
        generation_mode="first_last_frame",
        selection_rationale="涉及手电筒光束划破黑暗并照亮铁骷髅的强物理光影位移",
        first_last_config={
            "first_frame_prompt": "特写，光柱打在漆黑的废弃铁块上，尘埃飞扬",
            "last_frame_prompt": "特写，手电光定格在焦黑铁块中露出的半个森白头骨",
            "video_motion_prompt": "光束缓慢从左下扫向中央，光斑微颤，焦距锁定在金属骨骼上",
        },
        audio={"dialogue": "", "narration": "", "foley": "手电筒开关咔哒脆响 (+3dB)，沉重喘息声"},
        lipsync_dynamics={"jaw_open_scale": 0.4, "tension": "紧绷"},
    )

    shot2 = StoryboardShot(
        shot_id=2,
        timecode="00:00:03,000 --> 00:00:06,500",
        duration_sec=3.5,
        framing="MCU 中近景",
        camera_motion="Static 静态凝固",
        generation_mode="multi_image_reference",
        selection_rationale="对白与隐忍神态特写，无物理破坏位移，走多图参考锁脸",
        multi_image_config={
            "reference_assets": ["CHAR_CWG_BASE", "ENV_FURNACE_01"],
            "video_prompt": "陈卫国瞳孔震颤，嘴角肌肉抽搐，喉结上下滚动，欲言又止",
        },
        audio={"dialogue": "陈卫国：\"不可能……你十五年前就已经死了！\"", "narration": ""},
        lipsync_dynamics={"jaw_open_scale": 0.55, "tension": "牙齿打颤"},
    )

    srt_content = "1\n00:00:03,000 --> 00:00:06,500\n陈卫国：不可能……你十五年前就已经死了！\n"
    audio_mastering = {
        "ducking_rules": [{"time_range": "00:00:03,000-00:00:06,500", "bgm_attenuation": "-20dB"}],
        "silence_drop": {"time_range": "00:00:45,000-00:00:47,500", "gain": "-inf dB"},
    }

    # 落库
    persist_episode_visual_package(
        db=db_session,
        drama_id=1,
        episode_num=1,
        manifest=manifest,
        storyboards=[shot1, shot2],
        srt_export=srt_content,
        audio_mastering=audio_mastering,
    )
    db_session.commit()

    # 重新加载
    visual_pkg = load_episode_visual_package(db=db_session, drama_id=1, episode_num=1)

    assert visual_pkg["episode_number"] == 1
    assert visual_pkg["srt_export"] == srt_content
    assert len(visual_pkg["storyboards"]) == 2
    
    # 验证分镜选型与配置正确保存
    s1 = visual_pkg["storyboards"][0]
    assert s1.generation_mode == "first_last_frame"
    assert s1.first_last_config["first_frame_prompt"] == "特写，光柱打在漆黑的废弃铁块上，尘埃飞扬"
    
    s2 = visual_pkg["storyboards"][1]
    assert s2.generation_mode == "multi_image_reference"
    assert "CHAR_CWG_BASE" in s2.multi_image_config["reference_assets"]
    assert s2.lipsync_dynamics["jaw_open_scale"] == 0.55

    # 验证混音配置
    assert visual_pkg["audio_mastering"]["silence_drop"]["gain"] == "-inf dB"
