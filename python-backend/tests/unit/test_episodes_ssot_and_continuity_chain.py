# -*- coding: utf-8 -*-
"""
tests/unit/test_episodes_ssot_and_continuity_chain.py
验证【阶段5剧本生成节点与episodes表的SSOT架构及上下集时空快照链式咬合】：
1. 数据库 Schema 契约：
   - episodes 表彻底剥离 description、hook_cliffhanger 大纲冗余字段（单一事实源原则）
   - episodes 表具备 physical_snapshot_start, physical_snapshot_end, audit_verdict, audit_report 独立物理列
2. persist_stage5 正文与快照物理分离存储：
   - script_content 仅存储人类可读纯视听 Markdown 文本，杜绝 JSON 杂糅
   - physical_snapshot_start / end 存入独立物理列
   - audit_verdict / report 独立入库
   - 自动关联 episode_outlines.id 外键
3. load_master_state_from_db 双向水合：
   - 从纯 Markdown 正文和独立物理快照列完整重建 LiteraryScreenplayEpisodeModel
4. load_episode_substate_slice 跨集时空快照链式咬合：
   - 第 N 集 (N>1) 启动时，若自身 start 快照为空，自动查询并水合第 N-1 集的 physical_snapshot_end
5. persist_episode_substate_slice 单集切片纯正文与快照落库
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
    persist_episode_substate_slice,
    persist_stage4,
    persist_stage5,
)
from app.schemas.script_graph_state import (
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    InterEpisodePhysicalContinuity,
)


@pytest.fixture
def ssot_test_db():
    """初始化遵循 SSOT 与时空连续性快照规范的 SQLite 测试数据库。"""
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
        # 1. 创建短剧
        session.execute(
            text("""
                INSERT INTO dramas (id, title, genre, status, current_stage, total_episodes, created_at, updated_at)
                VALUES (88, '暗夜追踪', '悬疑动作', 'running', 4, 3, :now, :now)
            """),
            {"now": now},
        )
        # 2. 创建角色与场景
        session.execute(
            text("""
                INSERT INTO characters (id, drama_id, name, role, appearance, created_at, updated_at)
                VALUES (10, 88, '陆巡', '男主', '黑色皮夹克带血痕', :now, :now),
                       (11, 88, '白微', '女主', '风衣湿透神色惊惶', :now, :now)
            """),
            {"now": now},
        )
        session.execute(
            text("""
                INSERT INTO scenes (id, drama_id, location, prompt, created_at, updated_at)
                VALUES (20, 88, '老旧钟楼天台', '暴雨倾盆霓虹闪烁', :now, :now)
            """),
            {"now": now},
        )
        session.commit()
        yield session


def test_episodes_schema_ssot_and_snapshot_columns(ssot_test_db):
    """【SSOT 契约验证】验证 episodes 表已移除大纲冗余列并拥有物理快照与自审列。"""
    res = ssot_test_db.execute(text("PRAGMA table_info(episodes);")).fetchall()
    col_names = [r[1] for r in res]

    # 1. 验证大纲冗余字段彻底剥离
    assert "description" not in col_names, "episodes 表不应冗余存储大纲 description"
    assert "hook_cliffhanger" not in col_names, "episodes 表不应冗余存储大纲 hook_cliffhanger"

    # 2. 验证时空快照链与自审列完备
    assert "outline_id" in col_names
    assert "physical_snapshot_start" in col_names
    assert "physical_snapshot_end" in col_names
    assert "audit_verdict" in col_names
    assert "audit_report" in col_names
    assert "script_content" in col_names


def test_persist_stage5_pure_markdown_and_physical_snapshots(ssot_test_db):
    """【Stage 5 落库验证】验证 script_content 存储纯 Markdown，且快照与自审存入物理列。"""
    drama_id = 88
    now = "2026-09-24T12:00:00Z"

    # 先通过 Stage 4 落地大纲并初始化 episodes 容器
    stage4_state = {
        "season_outlines": {
            1: {
                "episode_number": 1,
                "title": "雨夜钟声",
                "hook_3s": "暴雨中黑色皮靴踩碎水洼，枪管反光一闪而过",
                "micro_twist_45s": "白微拔出匕首反向刺中伏击者",
                "cliffhanger_end": "钟楼大钟轰然敲响，狙击红点锁定陆巡眉心",
                "dual_helix_task": {"plot": "钟楼接头", "relation": "试探与互保"},
            },
            2: {
                "episode_number": 2,
                "title": "绝命索道",
                "hook_3s": "狙击子弹打碎钟盘边缘，陆巡拉着白微纵身一跃",
                "micro_twist_45s": "索道缆车刹车被破坏",
                "cliffhanger_end": "缆绳断裂，车厢急速坠向江面",
                "dual_helix_task": {"plot": "索道脱险", "relation": "生死契阔"},
            },
        },
        "target_duration_sec": 120,
    }
    persist_stage4(ssot_test_db, drama_id, stage4_state)

    # 构造 Stage 5 产出物
    pure_markdown_body = """【场景 01】外景. 老旧钟楼天台 - 夜 - 暴雨
暴雨倾盆。霓虹倒影在积水中破碎。
[声学行为: 开场突发重击 Braam Hit]
陆巡背靠锈蚀水箱，左手按压肋下渗血伤口，右手五指死死扣住扳机。

白微
（贴在墙角阴影中，剧烈喘息，声音极轻极颤）
还有几颗子弹？

陆巡
（冷笑一声，拇指推开转轮弹巢检查）
够送他们上路。

[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]

远处铜钟齿轮沉重咬合，发出金属巨震的闷响。
白微猛然扑出，匕首在空中划出一道寒光！
"""
    snapshot_start = {
        "timeline_progress": "故事第 1 天 22:00",
        "character_pose": "陆巡半蹲在天台水箱后，左肋轻度挫伤出血",
        "held_props_and_injuries": "握紧警用左轮手枪，子弹余3发",
        "environment_and_weather": "钟楼天台，暴雨，东北风5级",
        "location": "老旧钟楼天台",
    }
    snapshot_end = {
        "timeline_progress": "故事第 1 天 22:02",
        "character_pose": "陆巡左臂揽住白微腰身，身躯向天台边缘滑落",
        "held_props_and_injuries": "左轮手枪空仓挂机，白微反握带血短匕",
        "environment_and_weather": "大钟轰鸣，惨白闪电映照狙击红点",
        "location": "老旧钟楼天台边缘",
        "freeze_frame_desc": "定格：红外狙击光斑停留在陆巡眉心正中",
    }
    audit_report = {
        "verdict": "GREEN_APPROVED",
        "passed": True,
        "blue_team": "声学标记规范，前3秒抓手爆发力强，物理快照链条闭环",
        "red_team_critic": "对白发声阻力真实，节奏紧凑",
    }

    stage5_state = {
        "completed_screenplays": {
            1: {
                "episode_num": 1,
                "title": "雨夜钟声",
                "screenplay_text": pure_markdown_body,
                "body_markdown": pure_markdown_body,
                "previous_episode_0s_pickup": snapshot_start,
                "episode_end_physical_delta": snapshot_end,
                "outgoing_physical_snapshot": snapshot_end,
                "audit_report": audit_report,
                "planned_duration_sec": 120.0,
                "commercial_tag": "regular",
            }
        },
        "inter_episode_physical_snapshot": snapshot_end,
    }

    # 执行 Stage 5 落库
    persist_stage5(ssot_test_db, drama_id, stage5_state)

    # 查验 episodes 表记录
    ep_row = ssot_test_db.execute(
        text("SELECT * FROM episodes WHERE drama_id = :drama_id AND episode_number = 1"),
        {"drama_id": drama_id},
    ).mappings().first()

    assert ep_row is not None
    # 1. 验证 script_content 是纯 Markdown 文本，绝非 JSON
    assert ep_row["script_content"].startswith("【场景 01】")
    assert "[声学行为: 开场突发重击 Braam Hit]" in ep_row["script_content"]
    assert not ep_row["script_content"].strip().startswith("{"), "script_content 必须是纯正文文本，不得被 JSON 序列化污染"

    # 2. 验证独立物理列正确持久化
    assert ep_row["physical_snapshot_start"] is not None
    assert json.loads(ep_row["physical_snapshot_start"])["timeline_progress"] == "故事第 1 天 22:00"

    assert ep_row["physical_snapshot_end"] is not None
    assert json.loads(ep_row["physical_snapshot_end"])["location"] == "老旧钟楼天台边缘"

    assert ep_row["audit_verdict"] == "passed"
    assert json.loads(ep_row["audit_report"])["verdict"] == "GREEN_APPROVED"

    # 3. 验证关联到独立大纲表 outline_id
    assert ep_row["outline_id"] is not None


def test_cross_episode_physical_continuity_chain_hydration(ssot_test_db):
    """【时空连续性链式咬合验证】验证第 2 集切片水合时，自动从第 1 集的 physical_snapshot_end 链式承接。"""
    drama_id = 88

    # 1. 模拟第 1 集已完成并落库，具备结尾物理快照
    snapshot_ep1_end = {
        "timeline_progress": "故事第 1 天 22:02",
        "character_pose": "陆巡揽住白微，身体悬空于钟楼天台边缘",
        "held_props_and_injuries": "左轮手枪子弹打光，白微握住匕首",
        "environment_and_weather": "暴雨闪电，狂风呼啸",
        "location": "老旧钟楼天台边缘",
        "freeze_frame_desc": "定格：红外激光正中陆巡眉心",
    }
    ssot_test_db.execute(
        text("""
            INSERT INTO episodes (
                drama_id, episode_number, title, duration, status,
                script_content, physical_snapshot_end, audit_verdict,
                created_at, updated_at
            ) VALUES (
                :drama_id, 1, '雨夜钟声', 120, 'completed',
                '【场景 01】天台正文...', :snap_end, 'passed',
                '2026-09-24T12:00:00Z', '2026-09-24T12:00:00Z'
            )
        """),
        {"drama_id": drama_id, "snap_end": json.dumps(snapshot_ep1_end, ensure_ascii=False)},
    )

    # 2. 模拟第 2 集已由 Stage 4 初始化，但 physical_snapshot_start 尚未填充
    ssot_test_db.execute(
        text("""
            INSERT INTO episodes (
                drama_id, episode_number, title, duration, status,
                created_at, updated_at
            ) VALUES (
                :drama_id, 2, '绝命索道', 120, 'outline_completed',
                '2026-09-24T12:00:00Z', '2026-09-24T12:00:00Z'
            )
        """),
        {"drama_id": drama_id},
    )
    ssot_test_db.commit()

    # 3. 懒水合第 2 集切片
    substate_ep2 = load_episode_substate_slice(ssot_test_db, drama_id, 2)

    # 4. 验证时空快照链式咬合成功！
    assert substate_ep2 is not None
    assert substate_ep2.episode_number == 2
    assert substate_ep2.incoming_physical_continuity is not None, "第 2 集开场快照必须链式继承第 1 集终态快照"
    assert substate_ep2.incoming_physical_continuity.location == "老旧钟楼天台边缘"
    assert "陆巡揽住白微" in (
        substate_ep2.incoming_physical_continuity.character_pose
        or substate_ep2.incoming_physical_continuity.posture_and_injuries
    )
    assert substate_ep2.incoming_physical_continuity.freeze_frame_desc == "定格：红外激光正中陆巡眉心"


def test_load_master_state_hydrates_pure_markdown_screenplays(ssot_test_db):
    """【全季母本水合验证】验证 load_master_state_from_db 能从纯文本与物理快照列无损还原。"""
    drama_id = 88
    test_persist_stage5_pure_markdown_and_physical_snapshots(ssot_test_db)

    # 从数据库完整还原全季主状态
    master_state = load_master_state_from_db(ssot_test_db, drama_id)

    assert master_state is not None
    completed = master_state.completed_screenplays
    assert 1 in completed
    ep1_dict = completed[1]

    # 验证剧本纯正文与快照无损
    body = ep1_dict.get("screenplay_text") or ep1_dict.get("body_markdown") or ""
    assert "【场景 01】" in body
    assert "[声学行为: 开场突发重击 Braam Hit]" in body
    assert not body.strip().startswith("{")

    assert ep1_dict.get("previous_episode_0s_pickup") is not None
    assert ep1_dict.get("episode_end_physical_delta") is not None
    assert ep1_dict.get("audit_report") is not None
    assert ep1_dict.get("audit_report", {}).get("verdict") == "GREEN_APPROVED"


def test_persist_episode_substate_slice_preserves_pure_markdown(ssot_test_db):
    """【切片落库验证】验证 persist_episode_substate_slice 不会用 JSON 污染 script_content。"""
    from app.schemas.script_graph_state import LiteraryScreenplayEpisodeModel
    drama_id = 88
    # 确保第 1 集存在
    test_persist_stage5_pure_markdown_and_physical_snapshots(ssot_test_db)

    # 构造单集切片并更新剧本
    updated_markdown = "### 开场特写\n风雨呼啸。\n\n### 视听正文\n【场景 01】修补后的纯正文镜头。\n"
    new_outgoing_snapshot = InterEpisodePhysicalContinuity(
        timeline_progress="第 1 天 22:05",
        location="天台出口楼梯间",
        character_pose="陆巡扶墙喘息",
    )
    screenplay_model = LiteraryScreenplayEpisodeModel(
        episode_num=1,
        title="雨夜钟声",
        screenplay_text=updated_markdown,
        body_markdown=updated_markdown,
    )
    substate = EpisodeScopedSubState(
        drama_id=drama_id,
        episode_number=1,
        current_stage=5,
        screenplay=screenplay_model,
        outgoing_physical_continuity=new_outgoing_snapshot,
    )

    persist_episode_substate_slice(ssot_test_db, drama_id, substate)

    # 查询数据库检验
    row = ssot_test_db.execute(
        text("SELECT script_content, physical_snapshot_end FROM episodes WHERE drama_id = :drama_id AND episode_number = 1"),
        {"drama_id": drama_id},
    ).mappings().first()

    assert row["script_content"] == updated_markdown
    assert not row["script_content"].strip().startswith("{")
    snap_end = json.loads(row["physical_snapshot_end"])
    assert snap_end["location"] == "天台出口楼梯间"
