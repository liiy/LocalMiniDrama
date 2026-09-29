# -*- coding: utf-8 -*-
"""
tests/unit/test_working_memory_compiler.py
验证纯函数工作记忆编译器 (WorkingMemoryCompiler) 与 Redis 只读投影 (Read Model Projections)。
确保符合 CQRS 读分离规范与上下文防膨胀约束。
"""

import pytest
from app.context.short_memory_service import (
    WorkingMemoryCompiler,
    publish_drama_read_projection,
    get_drama_read_projection,
    publish_episode_read_projection,
    get_episode_read_projection,
)
from app.schemas.script_graph_state import (
    GlobalDramaMasterState,
    EpisodeScopedSubState,
    InterEpisodePhysicalContinuity,
)


def test_compile_ideation_working_memory():
    """测试阶段 1 概念工作记忆编译。"""
    stage1_data = {
        "selected_title": "极渊回声",
        "genre": "科幻悬疑",
        "visual_style": "高对比度冷色调",
        "logline": "深海勘探员发现海底基地的神秘信号，却发现自己就是信号源。",
        "dramatic_irony": "主角一直在逃避的异化体正是他未来的自己",
        "grand_payoff": "在倒计时结束时融合双重意识引爆能量核心拯救全员",
        "negative_rules": {
            "forbidden_cliches": ["机械降神", "突然失忆", "梦醒了"]
        }
    }

    result = WorkingMemoryCompiler.compile_ideation_working_memory(stage1_data)
    assert "极渊回声" in result
    assert "科幻悬疑" in result
    assert "戏剧反差" in result
    assert "终极爽点" in result
    assert "机械降神" in result
    # 严格控制在 800 字以内
    assert len(result) < 800


def test_compile_character_working_memory():
    """测试阶段 2 角色工作记忆精炼。"""
    chars_data = {
        "characters": [
            {
                "name": "沈凌",
                "character_id": "char_001",
                "psychology_4": {"want": "查明父亲死亡真相"},
                "biological_dna": {"permanent_flaws_coordinates": "左额角有三道缝合疤痕"},
            },
            {
                "name": "陈墨",
                "character_id": "char_002",
                "psychology_4": {"want": "不惜一切代价夺取能量晶核"},
                "biological_dna": {"permanent_flaws_coordinates": "右眼义眼泛着冷光"},
            },
        ]
    }

    result = WorkingMemoryCompiler.compile_character_working_memory(chars_data)
    assert "沈凌" in result
    assert "查明父亲死亡真相" in result
    assert "左额角有三道缝合疤痕" in result
    assert "陈墨" in result
    assert len(result) < 1000


def test_compile_world_building_working_memory():
    """测试阶段 3 空间做旧与物证拟音工作记忆。"""
    env_props_data = {
        "environments": [
            {"name": "沉没指挥舱", "level": "interior", "atmosphere": "幽暗潮湿带水滴声"},
            {"name": "压力走廊", "level": "interior", "atmosphere": "警报闪烁与金属扭曲声"},
        ],
        "props": [
            {"name": "生锈的气压表", "level": "hero_tier1", "visual_features": "表面裂纹指针卡在极限位"},
        ]
    }

    result = WorkingMemoryCompiler.compile_world_building_working_memory(env_props_data)
    assert "沉没指挥舱" in result
    assert "生锈的气压表" in result
    assert "表面裂纹指针卡在极限位" in result
    assert len(result) < 1000


def test_compile_season_outline_working_memory():
    """测试阶段 4 全季脉络工作记忆。"""
    outlines = {
        1: {
            "title": "深海之声",
            "core_conflict_task": "突入压力舱排查未知震动",
            "hook_cliffhanger": "声纳显示震动源就在沈凌背后",
        },
        2: {
            "title": "倒影",
            "core_conflict_task": "追捕潜入者却遭遇封闭阀门",
            "hook_cliffhanger": "隔热玻璃后露出一张与沈凌相同的面孔",
        }
    }
    audio_bible = {
        "theme_prompt": "低沉水下低音脉冲与心跳合奏，辅以高频金属摩擦声"
    }

    result = WorkingMemoryCompiler.compile_season_outline_working_memory(outlines, audio_bible)
    assert "深海之声" in result
    assert "声纳显示震动源就在沈凌背后" in result
    assert "低沉水下低音脉冲" in result
    assert len(result) < 1500


def test_compile_inter_episode_continuity():
    """测试阶段 5 集间物理接棒快照提炼。"""
    prev_result = {
        "episode_number": 1,
        "outgoing_physical_continuity": {
            "timecode_offset_sec": 78.5,
            "location": "压力走廊密封门前",
            "characters_posture": {
                "沈凌": "半跪在地上，右手死死攥住气压阀"
            },
            "lighting_atmosphere": "红色应急警报旋转闪烁",
            "unresolved_props_state": {
                "生锈的气压表": "指针已过载折断"
            }
        }
    }

    continuity = WorkingMemoryCompiler.compile_inter_episode_continuity(prev_result)
    assert continuity["inherited_from_episode"] == 1
    assert continuity["timecode_offset_sec"] == 78.5
    assert continuity["location"] == "压力走廊密封门前"
    assert "沈凌" in continuity["characters_posture"]

def test_semantic_redis_keys_and_idempotency():
    """测试第一程语义化工作便签、第二程物理连续性快照、幂等锁与事件广播。"""
    from app.context.short_memory_service import (
        set_journey1_working_memory,
        get_journey1_working_memory,
        set_episode_physical_snapshot,
        get_episode_physical_snapshot,
        check_and_set_idempotency,
        publish_drama_event,
        clear_drama_working_memory,
    )

    drama_id = 8888
    clear_drama_working_memory(drama_id)

    # 1. 验证第一程语义工作便签 (STRING)
    set_journey1_working_memory(drama_id, "stage1_ideation", "【剧名】: 极渊回声\n【题材】: 科幻")
    wm1 = get_journey1_working_memory(drama_id, "stage1_ideation")
    assert "极渊回声" in wm1
    assert "科幻" in wm1

    # 2. 验证第二程单集物理快照 (STRING JSON)
    snap = {
        "character_physical_states": {"CHAR_LU": "左臂受伤包扎"},
        "prop_custody_states": {"PROP_GUN": "上膛插在腰间"},
        "timeline_progress_sec": 120.0,
    }
    set_episode_physical_snapshot(drama_id, 1, snap)
    loaded_snap = get_episode_physical_snapshot(drama_id, 1)
    assert loaded_snap["character_physical_states"]["CHAR_LU"] == "左臂受伤包扎"
    assert loaded_snap["timeline_progress_sec"] == 120.0

    # 3. 验证任务幂等性锁 (24h)
    task_hash = "hash_task_stage1_run_01"
    first_try = check_and_set_idempotency(drama_id, task_hash, ttl=3600)
    assert first_try is True
    second_try = check_and_set_idempotency(drama_id, task_hash, ttl=3600)
    assert second_try is False  # 重复调用应被拦截

    # 4. 验证事件广播
    publish_drama_event(drama_id, "stage_completed", {"stage": 1, "stage_name": "stage1_ideation"})

    # 5. 清理验证
    clear_drama_working_memory(drama_id)
    assert get_journey1_working_memory(drama_id, "stage1_ideation") == ""
    assert get_episode_physical_snapshot(drama_id, 1) == {}
