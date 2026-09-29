# -*- coding: utf-8 -*-
"""
tests/unit/test_episode_outlines_and_tiered_context.py
验证【分集大纲表独立分立与阶梯式记忆流转方案（最小侵入版）】：
1. 数据库 DDL 与 Schema：验证 episode_outlines 独立表及其与 episodes.outline_id 的逻辑外键关联
2. Stage 4 持久化：验证 persist_stage4 写入 episode_outlines 并回填 episodes.outline_id
3. 单集切片水合：验证 load_episode_substate_slice 优先从 episode_outlines 精确水合任务大纲卡
4. 全季状态水合：验证 load_master_state_from_db 优先从 episode_outlines 还原无损大纲母本
5. Stage 5 四层局部滑动窗口装配：验证 build_stage5_tiered_context 实现 N+2 严格视界阻断与 Token 预算收敛
"""

import json
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.schema import ensure_schema
from app.workflows.adapters.drama_storage_adapter import (
    load_episode_substate_slice,
    load_master_state_from_db,
    persist_stage4,
)
from app.workflows.nodes.stage5_screenplay import build_stage5_tiered_context


@pytest.fixture
def sqlite_test_db():
    """初始化包含 episode_outlines 独立表的 SQLite 内存数据库。"""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        ensure_schema(conn)
        conn.commit()

    with Session(engine) as session:
        now = "2026-09-24T12:00:00Z"
        # 1. 初始化剧目
        session.execute(
            text("""
                INSERT INTO dramas (id, title, genre, status, current_stage, total_episodes, metadata, created_at, updated_at)
                VALUES (99, '破晓猎鹰', '谍战动作', 'running', 4, 6, :meta, :now, :now)
            """),
            {
                "meta": json.dumps({
                    "mini_arc_units": [
                        {
                            "unit_id": "MINI_ARC_1",
                            "name": "潜伏与破冰",
                            "episode_range": [1, 3],
                            "dramatic_focus": "特工方舟取得林越初步信任",
                            "core_conflict": "身份甄别与测谎考验",
                            "climax_event": "林越突然用枪指着方舟要求击毙卧底同伴",
                        },
                        {
                            "unit_id": "MINI_ARC_2",
                            "name": "收网与逆转",
                            "episode_range": [4, 6],
                            "dramatic_focus": "方舟逆风绝地反击摧毁秘密军火库",
                            "core_conflict": "生死时速与情报闭环",
                            "climax_event": "货运码头最终对决",
                        }
                    ]
                }, ensure_ascii=False),
                "now": now,
            },
        )
        # 2. 初始化角色
        session.execute(
            text("""
                INSERT INTO characters (id, drama_id, name, role, appearance, voice_style, created_at, updated_at)
                VALUES (1, 99, '方舟', '男主', '深黑风衣冷峻短发', '沉稳低音', :now, :now),
                       (2, 99, '林越', '反派', '银灰西装阴鸷神态', '阴冷刺骨', :now, :now)
            """),
            {"now": now},
        )
        session.commit()
        yield session


def test_schema_has_episode_outlines_and_outline_id(sqlite_test_db):
    """验证 DDL 成功创建 episode_outlines 表及 episodes.outline_id 字段。"""
    # 检查 episode_outlines 表是否存在
    res = sqlite_test_db.execute(text("PRAGMA table_info(episode_outlines);")).fetchall()
    col_names = [r[1] for r in res]
    assert "id" in col_names
    assert "drama_id" in col_names
    assert "episode_number" in col_names
    assert "title" in col_names
    assert "dual_helix_task" in col_names
    assert "subtext_matrix" in col_names
    assert "raw_outline_card" in col_names
    assert "hook_3s" in col_names
    assert "micro_twist_45s" in col_names
    assert "cliffhanger_end" in col_names

    # 检查 episodes 表是否包含 outline_id
    res_ep = sqlite_test_db.execute(text("PRAGMA table_info(episodes);")).fetchall()
    ep_col_names = [r[1] for r in res_ep]
    assert "outline_id" in ep_col_names


def test_persist_stage4_writes_episode_outlines_and_links_episodes(sqlite_test_db):
    """验证 Stage 4 持久化向 episode_outlines 写入全量工笔大纲并挂载 episodes.outline_id。"""
    drama_id = 99
    season_outlines = {
        1: {
            "episode_number": 1,
            "title": "破冰试探",
            "killer_title": "破冰试探",
            "hook_3s": "开局黑洞洞的枪口直抵眉心，倒计时 3 秒",
            "micro_twist_45s": "看似救兵的线人实际早已变节投敌",
            "cliffhanger_end": "引爆器启动，密室大门从外侧重重反锁",
            "dual_helix_task": {
                "plot_event_chain": "密室逼供 -> 假死脱身 -> 取得林越接见",
                "relational_shift_point": "从猜忌戒备转入初步同盟",
                "lie_erosion_metric": "伪装身份谎言面临 70% 穿帮风险",
            },
            "subtext_matrix": {
                "surface_dialogue": "林总，这批货保真，我用命担保。",
                "covert_intent": "暗中记录货运批号，植入微型定位芯片。",
                "power_dynamics": "林越持枪主导，方舟通过技术反客为主。",
            },
            "visual_punch": "碎玻璃在闪光弹照耀下如暴雨般横飞",
            "audio_motif_ref": "MOTIF_CORE_FATE",
        },
        2: {
            "episode_number": 2,
            "title": "血色甄别",
            "hook_3s": "测谎仪指针瞬间狂摆到极值红区",
            "micro_twist_45s": "方舟故意刺破指尖利用剧痛干扰生理指标",
            "cliffhanger_end": "同伴被推入刑室，林越将枪递给方舟：开枪自证清白",
            "dual_helix_task": {
                "plot_event_chain": "测谎过关 -> 进入核心机房 -> 突发同伴暴露",
                "relational_shift_point": "林越产生致命杀意",
                "lie_erosion_metric": "谎言濒临全面崩盘 90%",
            },
            "visual_punch": "血滴溅在冷光液晶屏幕上缓缓滑落",
            "audio_motif_ref": "MOTIF_SUSPENSE_RHYTHM",
        },
    }

    audio_bible = {
        "overall_key": "D小调",
        "leitmotifs": [
            {
                "motif_id": "MOTIF_CORE_FATE",
                "name": "命运钟声",
                "type": "fate",
                "instrumentation": "低音大提琴",
                "frequency_range": "30-100Hz",
                "symbolic_meaning": "不可逃避的宿命之战",
            }
        ],
    }

    mini_arc_units = [
        {
            "unit_id": "MINI_ARC_1",
            "name": "潜伏与破冰",
            "episode_range": [1, 2],
            "dramatic_focus": "特工方舟取得林越初步信任",
            "climax_event": "刑室开枪自证抉择",
        }
    ]

    stage4_state = {
        "season_outlines": season_outlines,
        "audio_bible": audio_bible,
        "mini_arc_units": mini_arc_units,
    }

    # 执行持久化
    persist_stage4(sqlite_test_db, drama_id, stage4_state)

    # 1. 验证 episode_outlines 表记录
    outlines = sqlite_test_db.execute(
        text("SELECT * FROM episode_outlines WHERE drama_id = :did ORDER BY episode_number ASC"),
        {"did": drama_id},
    ).mappings().fetchall()
    assert len(outlines) == 2

    row1 = dict(outlines[0])
    assert row1["episode_number"] == 1
    assert row1["title"] == "破冰试探"
    assert "枪口直抵眉心" in row1["hook_3s"]
    assert "反锁" in row1["cliffhanger_end"]

    # 验证反序列化 JSON 结构
    dh1 = json.loads(row1["dual_helix_task"])
    assert dh1["plot_event_chain"] == "密室逼供 -> 假死脱身 -> 取得林越接见"
    assert dh1["lie_erosion_metric"] == "伪装身份谎言面临 70% 穿帮风险"

    subtext1 = json.loads(row1["subtext_matrix"])
    assert "微型定位芯片" in subtext1["covert_intent"]

    # 2. 验证 episodes 表的 outline_id 外键正确关联
    episodes = sqlite_test_db.execute(
        text("SELECT * FROM episodes WHERE drama_id = :did ORDER BY episode_number ASC"),
        {"did": drama_id},
    ).mappings().fetchall()
    assert len(episodes) == 2
    assert episodes[0]["outline_id"] == row1["id"]
    assert episodes[1]["outline_id"] == outlines[1]["id"]


def test_load_episode_substate_slice_hydrates_from_episode_outlines(sqlite_test_db):
    """验证 load_episode_substate_slice 能够直接从 episode_outlines 精准水合高密大纲。"""
    drama_id = 99
    # 先持久化大纲
    season_outlines = {
        1: {
            "episode_number": 1,
            "title": "破冰试探",
            "hook_3s": "开局黑洞洞的枪口直抵眉心",
            "micro_twist_45s": "线人早已变节",
            "cliffhanger_end": "密室大门反锁",
            "dual_helix_task": {
                "plot_event_chain": "密室逼供 -> 假死脱身",
                "relational_shift_point": "从猜忌到同盟",
                "lie_erosion_metric": "穿帮风险 70%",
            },
            "subtext_matrix": {
                "surface_dialogue": "林总我用命担保",
                "covert_intent": "暗中植入芯片",
            },
        }
    }
    stage4_state = {
        "season_outlines": season_outlines,
        "audio_bible": {},
        "mini_arc_units": [],
    }
    persist_stage4(sqlite_test_db, drama_id, stage4_state)

    # 执行单集轻量切片水合
    substate = load_episode_substate_slice(sqlite_test_db, drama_id=drama_id, episode_number=1)

    assert substate.drama_id == drama_id
    assert substate.episode_number == 1
    assert substate.task_outline is not None
    assert substate.task_outline.title == "破冰试探"
    assert "枪口直抵眉心" in (substate.task_outline.three_second_hook or substate.task_outline.hook_3s)
    assert "密室大门反锁" in (substate.task_outline.killer_cliffhanger_115s or substate.task_outline.hook_cliffhanger)


def test_load_master_state_from_db_hydrates_outlines(sqlite_test_db):
    """验证 load_master_state_from_db 能够优先从 episode_outlines 恢复全季双螺旋大纲。"""
    drama_id = 99
    season_outlines = {
        1: {
            "episode_number": 1,
            "title": "破冰试探",
            "hook_3s": "开局枪口直抵眉心",
            "micro_twist_45s": "线人变节",
            "cliffhanger_end": "密室大门反锁",
            "dual_helix_task": {
                "plot_event_chain": "密室逼供 -> 假死脱身",
                "relational_shift_point": "从猜忌到同盟",
                "lie_erosion_metric": "穿帮风险 70%",
            },
        }
    }
    stage4_state = {
        "season_outlines": season_outlines,
        "audio_bible": {},
        "mini_arc_units": [],
    }
    persist_stage4(sqlite_test_db, drama_id, stage4_state)

    # 从数据库加载全剧主状态
    master_state = load_master_state_from_db(sqlite_test_db, drama_id=drama_id)
    assert master_state.drama_id == drama_id
    assert 1 in master_state.season_outlines
    ep1 = master_state.season_outlines[1]
    assert ep1["title"] == "破冰试探"
    assert "dual_helix_task" in ep1
    assert ep1["dual_helix_task"]["plot_event_chain"] == "密室逼供 -> 假死脱身"


def test_build_stage5_tiered_context_projection_matrix():
    """验证 Stage 5 四层局部滑动窗口装配机制 (build_stage5_tiered_context)：
    1. 包含宏观微弧单元 (Tier 1)
    2. 仅包含 [N-1, N, N+1] 滑动窗口，严格切断 N+2 防止剧透 (Tier 2)
    3. 包含本集高密任务卡（双螺旋、潜台词、视听锤点、声学引用）(Tier 3)
    4. 包含上一集 0s 物理快照接棒 (Tier 4)
    5. Token 预算严格受控（<600 tokens 契约）
    """
    total_episodes = 6
    season_outlines = {
        i: {
            "episode_number": i,
            "title": f"第{i}集 猎鹰行动",
            "killer_title": f"第{i}集 猎鹰行动",
            "hook_3s": f"第{i}集开场3s抓手动作",
            "micro_twist_45s": f"第{i}集45s微反转破局",
            "cliffhanger_end": f"第{i}集115s悬崖绝杀断点",
            "dual_helix_task": {
                "plot_event_chain": f"事件链条 E{i}_A -> E{i}_B",
                "relational_shift_point": f"第{i}集人物关系剧变",
                "lie_erosion_metric": f"第{i}集谎言剥落度 {i * 15}%",
            },
            "subtext_matrix": {
                "surface_excuse": f"第{i}代表面对白与借口",
                "core_intention": f"第{i}代深层真实动机",
            },
            "visual_punch": f"第{i}集核心特写视听锤点",
            "audio_motif_ref": "MOTIF_CORE_FATE",
        }
        for i in range(1, 7)
    }

    mini_arc_units = [
        {
            "unit_id": "MINI_ARC_1",
            "name": "潜伏与破冰",
            "episode_range": [1, 3],
            "dramatic_focus": "特工方舟取得林越初步信任",
            "core_conflict": "身份甄别与测谎考验",
            "climax_event": "林越要求方舟击毙卧底同伴",
        },
        {
            "unit_id": "MINI_ARC_2",
            "name": "收网与逆转",
            "episode_range": [4, 6],
            "dramatic_focus": "方舟逆风绝地反击摧毁秘密军火库",
            "core_conflict": "生死时速与情报闭环",
            "climax_event": "货运码头最终对决",
        },
    ]

    incoming_snapshot = {
        "inherited_from_episode": 2,
        "timeline_progress": "故事第 2 天夜晚 23:45",
        "location": "刑讯室侧门走廊",
        "character_pose": "方舟持枪半跪，右手渗血；林越站在阴影中冷视",
        "held_props_and_injuries": "方舟握住配枪，弹夹剩余 3 发",
        "environment_and_weather": "冷白顶灯闪烁，暴雨水珠顺着排风口滴落",
    }

    state = {
        "season_outlines": season_outlines,
        "mini_arc_units": mini_arc_units,
        "total_episodes": total_episodes,
    }

    # 测试第 3 集上下文投影
    episode_num = 3
    tiered_context = build_stage5_tiered_context(
        state=state,
        episode_num=episode_num,
        total_episodes=total_episodes,
        outline=season_outlines[3],
        incoming_snapshot=incoming_snapshot,
    )

    # 1. 验证微观微弧单元 (Tier 1)
    tier1 = tiered_context["tier1_macro_arc"]
    assert tier1["arc_unit_name"] == "潜伏与破冰"
    assert "01" in tier1["episode_range"] and "03" in tier1["episode_range"]
    assert "身份甄别与测谎考验" in tier1["macro_conflict_theme"]

    # 2. 验证滑动窗口与严格 N+2 阻断 (Tier 2)
    tier2 = tiered_context["tier2_sliding_window"]
    assert tier2["window_range"] == [2, 3, 4]
    assert tier2["previous_episode_facts"]["episode_number"] == 2
    assert tier2["current_episode_focus"]["episode_number"] == 3
    assert tier2["next_episode_teaser"]["episode_number"] == 4
    assert tier2["horizon_cutoff_n_plus_2"]["blocked_episode"] == 5

    # 序列化为 JSON 字符串，验证在文本流中绝对无第 5、6 集剧透
    context_json = json.dumps(tiered_context, ensure_ascii=False)
    assert "第5集" not in context_json
    assert "第6集" not in context_json
    assert "E5_A" not in context_json
    assert "E6_A" not in context_json

    # 3. 验证高密单集任务卡 (Tier 3)
    tier3 = tiered_context["tier3_single_episode_task"]
    assert tier3["episode_number"] == 3
    assert "事件链条 E3_A -> E3_B" in tier3["dual_helix_task"]["plot_event_chain"]
    assert "第3集人物关系剧变" in tier3["dual_helix_task"]["relational_shift_point"]
    assert "第3集45s微反转破局" in tier3["micro_twist_45s"]
    assert "第3集115s悬崖绝杀断点" in tier3["cliffhanger_end"]

    # 4. 验证上一集 0s 物理接棒快照 (Tier 4)
    tier4 = tiered_context["tier4_physical_pickup"]
    assert tier4["inherited_from_episode"] == 2
    assert "刑讯室侧门走廊" in tier4["location"]
    assert "右手渗血" in tier4["character_pose"]
    assert "弹夹剩余 3 发" in tier4["held_props_and_injuries"]

    # 5. 验证 Token 预算：紧凑投影字符数通常在 1000~1800 字符之间，折合约 400~550 tokens
    char_len = len(context_json)
    approx_tokens = char_len / 2.5
    assert approx_tokens < 600, f"Context projected tokens {approx_tokens:.1f} exceeds 600 tokens limit!"


def test_season_outline_card_lossless_propagation():
    """验证 SeasonOutlineCard 与状态机提取子状态时对双螺旋大纲与事件链的 100% 无损透传。"""
    from app.schemas.script_graph_state import (
        SeasonOutlineCard,
        GlobalDramaMasterState,
        IndustrialDramaMasterState,
    )

    raw_card = {
        "episode_number": 3,
        "title": "暗室对决",
        "core_conflict_task": "逼问密电码真相并完成同盟结缔",
        "plot_event_chain": "伪造火灾警报 -> 潜入档案室 -> 遭遇林浅反锁对峙",
        "relational_shift_point": "由虚假试探转为生死捆绑",
        "lie_erosion_metric": "借口破绽率达到 85%",
        "hook_3s": "开局刀尖刺入档案袋",
        "micro_twist_45s": "档案袋内只有一张空白信纸",
        "cliffhanger_end": "门锁转动，第三人脚步声逼近",
        "subtext_matrix": {
            "surface_dialogue": "这只是例行巡查。",
            "covert_intent": "搜寻销毁名单第7页。",
        },
    }

    # 1. 验证 SeasonOutlineCard 归一化与双螺旋任务打包
    card = SeasonOutlineCard.model_validate(raw_card)
    assert card.title == "暗室对决"
    assert card.dual_helix_task is not None
    assert card.dual_helix_task.get("plot_event_chain") == "伪造火灾警报 -> 潜入档案室 -> 遭遇林浅反锁对峙"
    assert card.dual_helix_task.get("relational_shift_point") == "由虚假试探转为生死捆绑"
    assert card.dual_helix_task.get("lie_erosion_metric") == "借口破绽率达到 85%"
    assert card.hook_3s == "开局刀尖刺入档案袋"
    assert card.micro_twist_45s == "档案袋内只有一张空白信纸"
    assert card.cliffhanger_end == "门锁转动，第三人脚步声逼近"

    # 2. 验证注入 IndustrialDramaMasterState
    ind_state = IndustrialDramaMasterState(
        drama_id=88,
        title="潜伏暗流",
        total_episodes=5,
        season_outlines={3: card},
    )

    # 3. 验证转为 GlobalDramaMasterState
    master_state = ind_state.to_global_master_state()
    assert 3 in master_state.season_outlines
    m_card = master_state.season_outlines[3]
    assert isinstance(m_card, SeasonOutlineCard)
    assert m_card.dual_helix_task.get("plot_event_chain") == "伪造火灾警报 -> 潜入档案室 -> 遭遇林浅反锁对峙"

    # 4. 验证从 MasterState 提取 EpisodeScopedSubState
    substate = master_state.extract_episode_substate(3)
    assert substate.task_outline is not None
    assert isinstance(substate.task_outline, SeasonOutlineCard)
    assert substate.task_outline.dual_helix_task.get("plot_event_chain") == "伪造火灾警报 -> 潜入档案室 -> 遭遇林浅反锁对峙"
    assert substate.task_outline.dual_helix_task.get("relational_shift_point") == "由虚假试探转为生死捆绑"
    assert substate.task_outline.micro_twist_45s == "档案袋内只有一张空白信纸"
    assert substate.task_outline.cliffhanger_end == "门锁转动，第三人脚步声逼近"

