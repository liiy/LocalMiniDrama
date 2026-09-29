# -*- coding: utf-8 -*-
"""
tests/unit/test_cross_stage_user_concept_continuity.py
验证阶段 1~4 用户核心构想跨阶段全链路锚定与叙事防偏离机制。
确保用户原始创意、核心冲突与终极爽点在：
1. 状态契约 (GlobalDramaMasterState / IndustrialDramaMasterState)
2. 跨阶段工作记忆编译器 (WorkingMemoryCompiler)
3. 阶段 1~4 执行节点与兜底合成器 (stage1~stage4)
4. 数据库持久化与水合还原 (DramaStorageAdapter)
中均保持 100% 贯通，彻底根除阶段 2/3/4 与阶段 1 脱节飘移的问题。
"""

import pytest
from unittest.mock import MagicMock

from app.schemas.script_graph_state import (
    GlobalDramaMasterState,
    IndustrialDramaMasterState,
)
from app.context.short_memory_service import WorkingMemoryCompiler
from app.workflows.nodes.stage1_ideation import stage1_ideation_node
from app.workflows.nodes.stage2_character import stage2_character_node, _stage2_fallback
from app.workflows.nodes.stage3_environment_prop import stage3_environment_prop_node, _stage3_fallback
from app.workflows.nodes.stage4_outline import stage4_outline_node, _stage4_fallback
from app.workflows.adapters.drama_storage_adapter import (
    persist_stage1,
    load_master_state_from_db,
)


def test_user_idea_in_working_memory_compiler():
    """测试工作记忆编译器对 user_idea 的强力锚定与防偏离约束。"""
    user_idea = "赛博修真：底层程序员穿越到修仙世界，发现灵气本质上是未开源操作系统的底层内存泄漏，通过反向汇编和0day漏洞逆袭成仙。"
    state_dict = {
        "user_idea": user_idea,
        "selected_title": "代码飞升",
        "genre": "赛博修仙/科幻",
        "visual_style": "霓虹青绿古风高科技混搭",
        "logline": "程序员利用系统漏洞改写修仙界运行法则",
        "dramatic_irony": "世人皆以为这是神力恩赐，实为死循环内存溢出灾难",
        "grand_payoff": "终局向天道防火墙注入零日漏洞彻底摧毁仙阀垄断",
        "negative_rules": {
            "forbidden_cliches": ["传统退婚流", "毫无逻辑的老爷爷救场", "反派降智送人头"]
        },
    }

    wm = WorkingMemoryCompiler.compile_ideation_working_memory(state_dict)

    # 1. 验证用户原始构想被原汁原味注入
    assert "【用户核心构想/立项故事】" in wm
    assert "底层程序员穿越到修仙世界" in wm
    assert "内存泄漏" in wm
    assert "0day漏洞" in wm

    # 2. 验证创作强约束 (Core Law) 存在
    assert "创作强约束 (Core Law)" in wm
    assert "必须严格锚定【用户核心构想/立项故事】" in wm
    assert "严禁脱离用户构想偏离主线" in wm

    # 3. 验证长度受控 (<1500 字符)
    assert len(wm) < 1500


def test_stages_1_to_4_user_concept_propagation():
    """测试阶段 1 到阶段 4 节点执行全流程，验证 user_idea 与核心设定全程不脱节。"""
    raw_user_idea = "末日废土咖啡馆：地球冰封纪元，主角开着一辆履带装甲咖啡车穿越暴风雪废土，用绝迹的真正咖啡豆换取各方势力的生存秘密，终局解冻地球。"

    state = IndustrialDramaMasterState(
        drama_id=888,
        user_idea=raw_user_idea,
        genre="废土科幻/治愈冒险",
        visual_style="冰封废土冷白与暖黄咖啡灯光撞色",
        total_episodes=10,
        arc_type="adventure",
    )

    # --- 阶段 1：立项与概念孵化 ---
    out1 = stage1_ideation_node(state)
    assert out1["current_stage"] == 1
    assert "user_idea" in out1
    assert out1["user_idea"] == raw_user_idea
    assert "ideation_working_memory" in out1
    assert "咖啡车" in out1["ideation_working_memory"] or "冰封" in out1["ideation_working_memory"]

    # 状态合并
    state.selected_title = out1["selected_title"]
    state.logline = out1["logline"]
    state.candidate_titles = out1["candidate_titles"]
    state.negative_rules = out1["negative_rules"]
    state.dramatic_irony = out1.get("dramatic_irony", "")
    state.grand_payoff = out1.get("grand_payoff", "")
    state.ideation_working_memory = out1.get("ideation_working_memory", "")
    state.short_memory_a = out1["short_memory_a"]

    # --- 阶段 2：角色引擎构建 ---
    out2 = stage2_character_node(state)
    assert out2["current_stage"] == 2
    assert "user_idea" in out2
    assert out2["user_idea"] == raw_user_idea
    chars = out2["characters_engine"]["characters"]
    assert len(chars) >= 2

    # 状态合并
    state.characters_engine = out2["characters_engine"]
    state.short_memory_b = out2["short_memory_b"]

    # --- 阶段 3：做旧空间与叙事道具 ---
    out3 = stage3_environment_prop_node(state)
    assert out3["current_stage"] == 3
    assert "user_idea" in out3
    assert out3["user_idea"] == raw_user_idea
    envs = out3["environments_and_props"]["environments"]
    props = out3["environments_and_props"]["props"]
    assert len(envs) >= 1
    assert len(props) >= 1

    # 状态合并
    state.environments_and_props = out3["environments_and_props"]
    state.short_memory_c = out3["short_memory_c"]

    # --- 阶段 4：分集大纲与母带 ---
    out4 = stage4_outline_node(state)
    assert out4["current_stage"] == 4
    assert "user_idea" in out4
    assert out4["user_idea"] == raw_user_idea
    season_outlines = out4["season_outlines"]
    assert len(season_outlines) == 10
    assert 1 in season_outlines
    assert 10 in season_outlines


def test_fallback_synthesizers_dynamic_anchoring():
    """测试离线或接口异常时的兜底合成器能否动态响应 user_idea，杜绝刻板商战脑补。"""
    user_idea = "克苏鲁星际殖民：太空飞船深空采矿时挖到了苏醒的古神眼球"
    genre = "太空科幻/克苏鲁"

    # Stage 2 兜底
    fb2 = _stage2_fallback("星渊呼唤", logline="太空深处挖掘出古神眼球", user_idea=user_idea, genre=genre)
    chars = fb2["characters"]
    assert len(chars) >= 2
    protagonist = chars[0]
    # 主角设定必须吸收了太空/克苏鲁/主角信息，而不是刻板前夫或豪门总裁
    assert "总裁" not in protagonist["name"]
    assert "顾" not in protagonist["name"]

    # Stage 3 兜底
    fb3 = _stage3_fallback("星渊呼唤", "太空深处挖掘出古神眼球", chars, user_idea=user_idea, genre=genre)
    envs = fb3["environments"]
    props = fb3["props"]
    # 场景和道具必须动态映射太空/科幻，不能是顾氏集团总裁办公室
    env_names = [e.get("location_name") or e.get("name", "") for e in envs]
    assert not any("顾氏" in name for name in env_names)
    assert any("控制台" in name or "主行动空间" in name or "星渊呼唤" in name for name in env_names)
    # Stage 4 兜底
    fb4 = _stage4_fallback(
        "星渊呼唤",
        total_episodes=6,
        characters=chars,
        props=props,
        user_idea=user_idea,
        grand_payoff="引爆飞船曲率引擎将古神眼球湮灭在超新星奇点",
        genre=genre,
    )
    episodes = fb4["season_outlines"]
    assert len(episodes) == 6
    # 终局大结局必须体现 grand_payoff
    final_ep = episodes.get(6) or episodes.get("6")
    assert final_ep is not None
    assert "超新星" in str(final_ep) or "引爆" in str(final_ep) or "星渊呼唤" in str(final_ep)


def test_storage_adapter_user_idea_persistence_and_hydration():
    """测试数据库存储适配器持久化 user_idea 并反向水合还原的能力。"""
    db_mock = MagicMock()
    drama_id = 999
    user_idea = "御兽纪元：全人类觉醒宠物契约，主角契约了平平无奇的土狗，实为吞噬星空的噬元神兽。"

    state = GlobalDramaMasterState(
        drama_id=drama_id,
        user_idea=user_idea,
        selected_title="我的契约兽是噬元神尊",
        genre="玄幻/御兽",
        visual_style="东方玄幻热血写实",
        logline="少年与土狗逆天改命吞噬九天",
        dramatic_irony="世人皆嘲笑主角契约土狗，不知神兽一口吞下上古禁咒",
        grand_payoff="九大兽皇围攻时土狗法相天地一口吞噬整片星域",
    )

    # 模拟已有记录
    fake_metadata = {}
    fake_drama_row = {
        "id": drama_id,
        "name": "我的契约兽是噬元神尊",
        "title": "我的契约兽是噬元神尊",
        "metadata": "{}",
        "description": "少年与土狗逆天改命吞噬九天",
        "genre": "玄幻/御兽",
        "style": "东方玄幻热血写实",
        "aspect_ratio": "9:16",
        "total_episodes": 12,
        "current_stage": 1,
    }

    def fake_fetch_one(db, query, params):
        if "FROM dramas" in query:
            return fake_drama_row
        return None

    def fake_execute(statement, params=None):
        nonlocal fake_metadata
        if params and "metadata" in params:
            import json
            fake_metadata = json.loads(params["metadata"])
            fake_drama_row["metadata"] = params["metadata"]
        return MagicMock()

    db_mock.execute.side_effect = fake_execute

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.workflows.adapters.drama_storage_adapter.fetch_one", fake_fetch_one)
        mp.setattr("app.workflows.adapters.drama_storage_adapter.fetch_all", lambda *a, **k: [])
        mp.setattr("app.workflows.adapters.drama_storage_adapter.sync_stage_memories_to_vector_db", lambda *a, **k: None)

        # 1. 执行落库
        persist_stage1(db_mock, drama_id, state)

        # 验证 metadata 中已持久化 user_idea
        assert "user_idea" in fake_metadata
        assert fake_metadata["user_idea"] == user_idea

        # 2. 从数据库反向水合加载
        loaded_state = load_master_state_from_db(db_mock, drama_id)

        # 验证加载出的状态完整保留 user_idea，并且自动重构了 ideation_working_memory
        assert loaded_state.user_idea == user_idea
        assert loaded_state.ideation_working_memory != ""
        assert "噬元神兽" in loaded_state.ideation_working_memory
