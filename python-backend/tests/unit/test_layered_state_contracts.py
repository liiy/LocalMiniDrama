# -*- coding: utf-8 -*-
"""分层状态机数据契约单元测试 (Phase 1 验证)

测试覆盖点：
1. GlobalDramaMasterState 轻量全局状态序列化与体积约束 (< 50KB)
2. EpisodeScopedSubState 单集独立执行子状态切片与体积约束 (< 100KB)
3. IndustrialDramaMasterState 语义化工作记忆字段与旧版 short_memory_a/b/c/d 双向同步兼容
4. extract_episode_substate 与 merge_episode_substate 状态隔离与增量合并
"""

import json
import pytest
from app.schemas.script_graph_state import (
    GlobalDramaMasterState,
    EpisodeScopedSubState,
    IndustrialDramaMasterState,
    CharacterAnchorStub,
    SceneAnchorStub,
    PropAnchorStub,
    SeasonOutlineCard,
    InterEpisodePhysicalContinuity,
    LiteraryScreenplayEpisodeModel,
    EpisodeResourceManifest,
    StoryboardShot,
    AudioMasteringConfig,
)


def test_global_master_state_lightweight_size():
    """验证全局文学父图状态轻量性与体积约束 (< 50KB)。"""
    # 模拟包含 10 个角色基底桩、20 个场景基底桩、20 个道具基底桩的大型短剧
    global_chars = {
        f"char_{i}": CharacterAnchorStub(
            character_id=f"char_{i}",
            name=f"主角_{i}",
            visual_token=f"[visual_token_{i}: black hair, cold eyes]",
            archetype="隐忍复仇者"
        )
        for i in range(10)
    }
    global_scenes = {
        f"scene_{i}": SceneAnchorStub(
            scene_id=f"scene_{i}",
            name=f"场景_{i}",
            spatial_type="interior"
        )
        for i in range(20)
    }
    global_props = {
        f"prop_{i}": PropAnchorStub(
            prop_id=f"prop_{i}",
            name=f"关键物证_{i}",
            level="hero_tier1"
        )
        for i in range(20)
    }
    season_outlines = {
        i: SeasonOutlineCard(
            episode_number=i,
            episode_id=i,
            title=f"第{i}集 龙王觉醒",
            killer_title=f"龙王第{i}次反杀",
            core_conflict_task="完成身份绝地翻盘",
            hook_cliffhanger="突遭神秘杀手狙击"
        )
        for i in range(1, 81)  # 80 集超长短剧
    }

    state = GlobalDramaMasterState(
        drama_id=1001,
        slug="dragon-revenge",
        journey="journey_1_literary",
        current_stage=4,
        selected_title="龙王出狱：无敌战神",
        genre="都市战神",
        visual_style="电影质感冷色调",
        logline="入狱三年的战神潜龙在渊，出狱之日便是仇敌覆灭之时。",
        dramatic_irony="仇敌以为主角依然是软弱弃子，不知其实力已通天彻地。",
        grand_payoff="在家族寿宴上当众揭开战神战袍，反派跪地求饶。",
        global_characters=global_chars,
        global_scenes=global_scenes,
        global_props=global_props,
        total_episodes=80,
        season_outlines=season_outlines,
        completed_episodes=list(range(1, 11))
    )

    serialized = state.model_dump_json()
    size_in_kb = len(serialized.encode("utf-8")) / 1024
    # 断言 80 集大型短剧的全局状态体积严格小于 50KB
    assert size_in_kb < 50.0, f"全局主状态体积超出预期: {size_in_kb:.2f} KB >= 50 KB"
    assert state.drama_id == 1001
    assert len(state.global_characters) == 10


def test_episode_scoped_substate_isolation_and_size():
    """验证单集执行子状态隔离性与体积约束 (< 100KB)。"""
    task_outline = SeasonOutlineCard(
        episode_number=5,
        episode_id=5,
        title="第5集 鸿门宴对峙",
        core_conflict_task="在宴席上完成言语试探与暗器破解",
        hook_cliffhanger="神秘红衣女子突然登场拔枪"
    )
    incoming_continuity = InterEpisodePhysicalContinuity(
        inherited_from_episode=4,
        timecode_offset_sec=90.0,
        location="豪门大堂主桌",
        characters_posture={"char_1": "右手持高脚杯，左臂微负伤", "char_2": "持枪对峙"},
        lighting_atmosphere="昏黄宴会水晶灯冷暖交织",
        unresolved_props_state={"prop_1": "酒杯裂纹扩散，桌上留有血渍"}
    )
    
    # 模拟单集剧本
    script = LiteraryScreenplayEpisodeModel(
        episode=5,
        episode_id=5,
        title="第5集 鸿门宴对峙",
        core_conflict="宴席生死杀局",
        cliffhanger="红衣女子拔枪",
        scenes=[
            {
                "scene_number": 1,
                "scene_name": "豪门大堂",
                "scene_type": "INT",
                "atmosphere": "剑拔弩张",
                "dialogues": [
                    {
                        "character_name": "林战",
                        "dialogue_content": "今天在座的各位，谁也走不出这道门。",
                        "emotional_state": "杀机凛冽",
                        "timing_seconds": 3.0
                    }
                ]
            }
        ]
    )

    substate = EpisodeScopedSubState(
        drama_id=1001,
        episode_number=5,
        current_stage=7,
        task_outline=task_outline,
        incoming_physical_continuity=incoming_continuity,
        screenplay=script
    )

    serialized = substate.model_dump_json()
    size_in_kb = len(serialized.encode("utf-8")) / 1024
    assert size_in_kb < 100.0, f"单集子状态体积超出预期: {size_in_kb:.2f} KB >= 100 KB"
    assert substate.episode_number == 5
    assert substate.task_outline.title == "第5集 鸿门宴对峙"


def test_master_state_bidirectional_synchronization():
    """验证 IndustrialDramaMasterState 语义化工作记忆字段与旧版 short_memory 双向兼容。"""
    # 场景 1: 传入新语义字段，自动同步到旧字段
    state1 = IndustrialDramaMasterState(
        drama_id=2001,
        ideation_working_memory="[创意灵感便签] 核心戏剧反讽：真假少爷身份错位",
        character_working_memory="[角色便签] 主角林动表面放浪不羁，实为暗夜判官",
        world_building_working_memory="[世界观便签] 云海城地下财阀盘根错节",
        season_outline_working_memory="[大纲便签] 前三集完成反客为主，第四集开启复仇",
        inter_episode_physical_continuity={
            "inherited_from_episode": 2,
            "location": "总裁办公室",
            "characters_posture": {"林动": "坐在老板椅上抽雪茄"}
        }
    )
    assert state1.short_memory_a == state1.ideation_working_memory
    assert state1.short_memory_b == state1.character_working_memory
    assert state1.short_memory_c == state1.world_building_working_memory
    assert state1.short_memory_d == state1.season_outline_working_memory
    assert state1.inter_episode_physical_snapshot == state1.inter_episode_physical_continuity

    # 场景 2: 传入旧版 short_memory 字段，自动填充新语义字段
    state2 = IndustrialDramaMasterState(
        drama_id=2002,
        short_memory_a="旧版阶段1输出",
        short_memory_b="旧版阶段2输出",
        short_memory_c="旧版阶段3输出",
        short_memory_d="旧版阶段4输出",
        inter_episode_physical_snapshot={"inherited_from_episode": 1, "location": "废弃仓库"}
    )
    assert state2.ideation_working_memory == "旧版阶段1输出"
    assert state2.character_working_memory == "旧版阶段2输出"
    assert state2.world_building_working_memory == "旧版阶段3输出"
    assert state2.season_outline_working_memory == "旧版阶段4输出"
    assert state2.inter_episode_physical_continuity == {"inherited_from_episode": 1, "location": "废弃仓库"}


def test_state_slicing_and_merging_round_trip():
    """验证 extract_episode_substate 切片与 merge_episode_substate 增量合并的往返一致性。"""
    master_state = IndustrialDramaMasterState(
        drama_id=3001,
        slug="legend-of-immortal",
        journey="journey_2_visual",
        current_stage=6,
        season_outlines={
            3: {
                "episode_title": "第3集 丹炉炸裂",
                "core_conflict_task": "在宗门长老刁难下成丹",
                "cliffhanger": "金色丹雷滚滚而下"
            }
        },
        inter_episode_physical_continuity={
            "inherited_from_episode": 2,
            "location": "炼丹大殿中央",
            "characters_posture": {"主角": "盘膝打坐，嘴角有血"}
        }
    )

    # 1. 切片提取
    substate = master_state.extract_episode_substate(3)
    assert substate.episode_number == 3
    assert substate.task_outline.title == "第3集 丹炉炸裂"
    assert substate.incoming_physical_continuity is not None
    assert substate.incoming_physical_continuity.location == "炼丹大殿中央"

    # 2. 在单集子图中执行 Stage 7 分镜与 Stage 8 音频
    substate.storyboard_shots = [
        StoryboardShot(
            shot_id=1,
            duration_sec=3.0,
            timecode="00:00:00,000 --> 00:00:03,000",
            generation_mode="multi_image_reference",
            target_engine="wan3.0",
            rationale="开场特写丹炉符文闪烁"
        )
    ]
    substate.srt_content = "1\n00:00:00,000 --> 00:00:03,000\n凝！给我凝丹！\n"
    substate.outgoing_physical_continuity = InterEpisodePhysicalContinuity(
        inherited_from_episode=3,
        location="崩塌的炼丹殿残骸",
        characters_posture={"主角": "手托极品金丹傲然而立"}
    )

    # 3. 增量合并回大状态
    master_state.merge_episode_substate(substate)

    assert 3 in master_state.episode_storyboards
    assert len(master_state.episode_storyboards[3]) == 1
    assert master_state.episode_storyboards[3][0].shot_id == 1
    assert master_state.episode_srt_exports[3] == "1\n00:00:00,000 --> 00:00:03,000\n凝！给我凝丹！\n"
    assert master_state.inter_episode_physical_continuity["location"] == "崩塌的炼丹殿残骸"
    assert master_state.inter_episode_physical_snapshot["location"] == "崩塌的炼丹殿残骸"


def test_global_master_state_enrichment_and_substate_extraction():
    """验证 GlobalDramaMasterState 自动归一化、锚点桩生成与单集子状态切片。"""
    raw_data = {
        "drama_id": 5001,
        "title": "暗战迷局",
        "core_irony": "捕蝉的螳螂不知自己是黄雀的饵",
        "duration_sec_per_ep": 115,
        "target_episodes": 10,
        "characters": [
            {
                "character_id": "CHAR_ZHOU",
                "name": "周巡",
                "personality": "老谋深算",
                "biological_dna": {"permanent_flaws_coordinates": "右脸颊暗痣"},
                "psychology_4": {"want": "洗刷冤屈"}
            }
        ],
        "environments_and_props": {
            "environments": [
                {"env_id": "SCENE_DOCK", "name": "十六号码头", "level": "hero_location"}
            ],
            "props": [
                {"prop_id": "PROP_GUN", "name": "左轮手枪", "level": "hero_tier1"}
            ]
        },
        "season_outlines": {
            "1": {
                "title": "第1集 雾夜暗涌",
                "core_conflict_task": "雨夜逃亡",
                "hook_cliffhanger": "枪响人倒"
            }
        },
        "short_memory_a": "便签A内容",
        "inter_episode_physical_continuity": {"location": "码头货柜前", "characters_posture": {"周巡": "持枪隐蔽"}}
    }

    g_state = GlobalDramaMasterState.model_validate(raw_data)
    # 验证字段与属性双向同步
    assert g_state.selected_title == "暗战迷局"
    assert g_state.title == "暗战迷局"
    assert g_state.dramatic_irony == "捕蝉的螳螂不知自己是黄雀的饵"
    assert g_state.core_irony == "捕蝉的螳螂不知自己是黄雀的饵"
    assert g_state.ideation_working_memory == "便签A内容"
    assert g_state.short_memory_a == "便签A内容"
    assert g_state.target_duration_sec == 115.0
    assert g_state.total_episodes == 10

    # 验证轻量桩自动生成
    assert "CHAR_ZHOU" in g_state.global_characters
    assert g_state.global_characters["CHAR_ZHOU"].visual_token == "右脸颊暗痣"
    assert "SCENE_DOCK" in g_state.global_scenes
    assert "PROP_GUN" in g_state.global_props
    assert 1 in g_state.season_outlines
    assert g_state.season_outlines[1].title == "第1集 雾夜暗涌"

    # 验证切片生成单集子状态
    substate = g_state.extract_episode_substate(1)
    assert isinstance(substate, EpisodeScopedSubState)
    assert substate.episode_number == 1
    assert substate.task_outline.title == "第1集 雾夜暗涌"
    assert len(substate.relevant_character_stubs) == 1
    assert substate.incoming_physical_continuity.location == "码头货柜前"
    assert substate["episode_number"] == 1

    # 验证子状态属性与赋值
    substate["current_stage"] = 6
    assert substate.current_stage == 6
    substate.episode_num = 2
    assert substate.episode_number == 2

