"""单元测试：场景与道具三层级联架构与100%动态NLP提取验证。

【核心验证指标】
1. 剧本逆向特征扫描器 (screenplay_feature_scanner.py):
   - 100% 动态 NLP 抽取未注册场景与子区域 (scene_zones_detected)，拒绝写死常量；
   - 100% 动态物理名词识别与动宾形变提取 (DEFORMATION_VERBS)，生成 ACTION/STATIC 态；
   - 彻底剔除 "冷水饺"、"核心主活动区" 等静态默认枚举。
2. 阶段 6 资产真理源节点 (stage6_asset_truth.py):
   - 动态保底工厂 (_stage6_fallback) 输出包含完整三层级联数据 (Tier 1 基础空间/道具, Tier 2 子区域/损伤态, Tier 3 做旧层/特写切片)；
   - 新发现场景与道具自动构建 Stage 3 档案 (_build_stage3_scene_dossier / _build_stage3_prop_dossier)；
   - episode_resource_manifest 与 state.new_scene_dossiers / state.new_prop_dossiers 同步更新。
3. 关系型数据库持久化适配器 (drama_storage_adapter.py):
   - 场景三层级联原子落库: scenes -> scene_zones -> scene_weathering_views；
   - 道具三层级联原子落库: props -> prop_damage_states -> prop_detail_views；
   - 幂等性测试: 多次重复落库不产生重复数据或外键损坏。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest
from sqlalchemy import text

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
    VisualAudioAssetsRegistryModel,
)
from app.tools.screenplay_feature_scanner import (
    scan_screenplay_features,
    _extract_dynamic_props_from_screenplay,
)
from app.workflows.adapters.drama_storage_adapter import (
    persist_stage6,
    persist_stage3,
)
from app.workflows.nodes.stage6_asset_truth import (
    _build_stage3_scene_dossier,
    _build_stage3_prop_dossier,
    _stage6_fallback,
    stage6_asset_truth_node,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper


# =========================================================================
# 1. 扫描器 100% 动态 NLP 提取测试
# =========================================================================

def test_scanner_dynamic_scene_and_subzones_extraction():
    """测试扫描器动态提取未注册场景与其物理子分区 (scene_zones_detected)。"""
    screenplay_text = """
    【场景：南区生鲜冷库 - 极寒/冰霜】
    林夏从通风排气管道中狼狈爬出，重重跌落在速冻储藏区的铁制托盘上。
    四周冰雾弥漫，墙壁上凝结着厚厚的白霜。
    【场景：半山废弃天文台 - 黎明/浓雾】
    苏诚推开生锈的观测穹顶大门，踏上旋转铁梯，走向圆顶观测室。
    """
    scan_res = scan_screenplay_features(
        episode_id=1,
        screenplay_text=screenplay_text,
        known_characters=[],
        known_environments=[],
        known_props=[],
        existing_assets_registry={},
    )

    # 1. 验证新场景识别
    env_assets = [a for a in scan_res.new_assets if a["asset_id"].startswith("ENV_")]
    assert len(env_assets) >= 2, f"应识别出至少两个场景资产，实际: {env_assets}"
    
    # 验证资产 ID 符合四段式
    for a in env_assets:
        valid, err = AssetProtocolHelper.validate_id(a["asset_id"], expected_category="ENV")
        assert valid is True, f"场景资产 ID 非标: {a['asset_id']}, err={err}"

    # 2. 验证子分区 (scene_zones_detected) 动态提取
    zones_map = scan_res.scene_zones_detected
    assert isinstance(zones_map, dict)
    
    # 冷库子区域应当提取到通风排气管道或速冻储藏区
    cold_storage_key = next((k for k in zones_map if "冷库" in k or "生鲜" in k), None)
    assert cold_storage_key is not None, f"未找到冷库场景键，当前键: {list(zones_map.keys())}"
    cold_zones = zones_map[cold_storage_key]
    assert any("管道" in z or "储藏区" in z or "托盘" in z for z in cold_zones), f"冷库子分区提取失败: {cold_zones}"

    # 天文台子区域应当提取到观测穹顶、铁梯或观测室
    observatory_key = next((k for k in zones_map if "天文台" in k), None)
    assert observatory_key is not None, f"未找到天文台场景键，当前键: {list(zones_map.keys())}"
    obs_zones = zones_map[observatory_key]
    assert any("穹顶" in z or "铁梯" in z or "观测室" in z for z in obs_zones), f"天文台子分区提取失败: {obs_zones}"

    # 3. 严格断言：绝对不包含写死的伪默认值
    for k, v in zones_map.items():
        assert "核心主活动区" not in v, f"场景 {k} 出现了写死的 '核心主活动区'！"


def test_scanner_dynamic_prop_and_verb_deformation():
    """测试扫描器动态提取物理道具，并基于动宾破坏动词生成 ACTION 破坏态。"""
    screenplay_text = """
    【场景：审讯室 - 昏暗】
    陈峰猛地抓起桌上的老式录音笔，狠狠砸向地面，外壳瞬间崩碎！
    苏琴颤抖着从怀里拿出一串黄铜钥匙，没有弄坏它，只是紧紧握住。
    """
    scan_res = scan_screenplay_features(
        episode_id=1,
        screenplay_text=screenplay_text,
        known_characters=[],
        known_environments=[],
        known_props=[],
        existing_assets_registry={},
    )

    prop_assets = [a for a in scan_res.new_assets if a["asset_id"].startswith("PROP_")]
    prop_ids = [a["asset_id"] for a in prop_assets]

    # 1. 录音笔受到“砸”、“崩碎”动作，必须生成 ACTION 破坏态
    action_props = [pid for pid in prop_ids if "ACTION" in pid]
    assert len(action_props) >= 1, f"应当识别出破坏态道具，实际道具列表: {prop_ids}"
    assert any("LUYINBI" in pid or "LUYIN" in pid or "RECORDER" in pid for pid in action_props)

    # 2. 黄铜钥匙未遭受破坏，必须为 STATIC 静态态
    static_props = [pid for pid in prop_ids if "STATIC" in pid]
    assert len(static_props) >= 1, f"应当识别出静态道具，实际道具列表: {prop_ids}"

    # 3. 验证绝对没有写死的“冷水饺”
    assert not any("LENGSHUIJIAO" in pid or "SHUIJIAO" in pid for pid in prop_ids), "出现了写死的冷水饺！"


# =========================================================================
# 2. 阶段 6 档案构建与保底工厂三层级联测试
# =========================================================================

def test_stage6_dossier_builders():
    """测试 _build_stage3_scene_dossier 与 _build_stage3_prop_dossier 动态组装三层级联数据。"""
    # 1. 测试场景档案构建
    scene_dossier = _build_stage3_scene_dossier(
        scene_name="南区生鲜冷库",
        time_lighting="极寒/昏暗泛蓝冷光",
        detected_zones=["通风排气管道", "速冻储藏区"],
        index_hint=1,
    )
    assert scene_dossier["name"] == "南区生鲜冷库"
    assert scene_dossier["scene_code"].startswith("ENV_")
    assert len(scene_dossier["zones"]) == 2
    assert scene_dossier["zones"][0]["zone_name"] == "通风排气管道"
    assert scene_dossier["zones"][1]["zone_name"] == "速冻储藏区"
    assert len(scene_dossier["weathering_views"]) >= 2
    assert all(w["parent_asset_key"].startswith("ENV_") for w in scene_dossier["weathering_views"])

    # 2. 测试道具档案构建
    prop_dossier = _build_stage3_prop_dossier(
        prop_name="老式录音笔",
        deformed_verbs=["砸", "崩碎"],
        index_hint=1,
    )
    assert prop_dossier["name"] == "老式录音笔"
    assert prop_dossier["prop_code"].startswith("PROP_")
    # 应当包含 S0 完好态 + S1 破坏态
    assert len(prop_dossier["damage_states"]) >= 2
    states = prop_dossier["damage_states"]
    assert states[0]["state_code"].endswith("_S0")
    assert states[0]["damage_level"] == 0
    assert states[1]["state_code"].endswith("_S1")
    assert states[1]["damage_level"] >= 1
    # 应当包含微距切片 views
    assert len(prop_dossier["detail_views"]) >= 2
    assert all(v["parent_asset_key"].startswith("PROP_") for v in prop_dossier["detail_views"])


def test_stage6_fallback_dynamic_hierarchies():
    """测试 _stage6_fallback 针对全新剧本动态生成三层级联 manifest 与新发现清单。"""
    state = IndustrialDramaMasterState(
        drama_id=202,
        current_visual_episode=1,
        completed_screenplays={
            1: {
                "episode_num": 1,
                "scenes": [
                    {
                        "heading": "【场景：化工厂控制室 - 夜/红光频闪】",
                        "screenplay_text": "周衍手持防爆手电筒，照向配电柜。他突然挥动铁锤砸烂了警报器！",
                    }
                ],
            }
        },
    )

    manifest_dict = _stage6_fallback(state, episode_num=1)
    manifest = manifest_dict["manifest"]

    # 1. 验证新发现清单已生成且无写死数据
    new_scenes = manifest.get("newly_discovered_scenes", [])
    new_props = manifest.get("newly_discovered_props", [])
    assert len(new_scenes) >= 1
    assert any("化工厂" in s["name"] or "控制室" in s["name"] for s in new_scenes)
    assert len(new_props) >= 1
    assert any("警报器" in p["name"] or "铁锤" in p["name"] or "手电筒" in p["name"] for p in new_props)

    # 2. 验证 environments 包含三层级联结构
    env_tier1 = manifest["environments"]["tier1_primary"]
    assert len(env_tier1) >= 1
    env_item = env_tier1[0]
    assert "zones" in env_item
    assert len(env_item["zones"]) >= 1
    # 动态子区域非“核心主活动区”
    assert env_item["zones"][0]["zone_name"] != "核心主活动区"

    # 3. 验证 props 包含三层级联结构
    prop_tier1 = manifest["props"]["tier1_hero"]
    assert len(prop_tier1) >= 1
    prop_item = prop_tier1[0]
    assert "damage_states" in prop_item
    assert len(prop_item["damage_states"]) >= 1


# =========================================================================
# 3. 数据库 6 张关联表级联原子落库测试
# =========================================================================

def test_cascading_persistence_scenes_and_props_six_tables(db_session):
    """测试 6 张表级联落库：
    1. scenes -> scene_zones -> scene_weathering_views
    2. props -> prop_damage_states -> prop_detail_views
    以及多轮落库的幂等性保证。
    """
    # 1. 初始化数据库基线
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (303, '幽暗回响', 'draft', '', '')")
    )
    db_session.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, created_at, updated_at) VALUES (3001, 303, 1, '第一集：暗潮', '', '')")
    )
    db_session.commit()

    # 2. 构造三层级联 manifest
    manifest = EpisodeResourceManifest(
        episode_num=1,
        characters=[
            {
                "char_id": "CHAR_ZHOUYAN_T1_BASE_PORTRAIT",
                "character_name": "周衍",
                "role": "protagonist",
                "stage_name": "常态刑警便装",
                "visual_prompt": "深灰夹克中年男子，目光冷峻锐利",
            }
        ],
        environments=[
            {
                "scene_id": "ENV_HUAGONGCHANG_T1_WIDE",
                "scene_code": "ENV_HUAGONGCHANG_T1_WIDE",
                "benchmark_asset_key": "ENV_HUAGONGCHANG_T1_WIDE",
                "scene_name": "化工厂控制室",
                "location": "化工厂控制室",
                "time_lighting": "深夜，红色报警应急频闪灯",
                "zones": [
                    {
                        "zone_name": "总监控操作台",
                        "time_lighting": "微弱绿光与警报频闪",
                        "acoustic_resistance": "封闭空间微弱回音",
                    },
                    {
                        "zone_name": "高压配电柜走廊",
                        "time_lighting": "漆黑，局部红光扫射",
                        "acoustic_resistance": "狭窄管道高混响",
                    },
                ],
                "weathering_applied": ["仪表盘蛛网与厚重灰尘", "地面电缆烧焦熏黑痕迹"],
            }
        ],
        props=[
            {
                "prop_id": "PROP_JINGBAOQI_T1_STATIC",
                "prop_code": "PROP_JINGBAOQI_T1_STATIC",
                "benchmark_asset_key": "PROP_JINGBAOQI_T1_STATIC",
                "prop_name": "红色警报器",
                "damage_states": [
                    {
                        "state_code": "PROP_JINGBAOQI_T1_S0",
                        "state_label": "出厂完好通电状态",
                        "damage_level": 0,
                    },
                    {
                        "state_code": "PROP_JINGBAOQI_T1_S1",
                        "state_label": "被铁锤重击砸碎破裂",
                        "damage_level": 3,
                    },
                ],
                "detail_views": [
                    {
                        "view_type": "macro_detail",
                        "description": "碎裂蜂鸣器内部铜线裸露微距",
                    }
                ],
            }
        ],
    )

    state = IndustrialDramaMasterState(
        drama_id=303,
        current_visual_episode=1,
        episode_manifests={1: manifest},
    )

    # 3. 第一次落库执行
    persist_stage6(db_session, drama_id=303, state=state, episode_num=1)

    # 4. 验证场景三层表 (scenes -> scene_zones -> scene_weathering_views)
    scene_rows = db_session.execute(text("SELECT * FROM scenes WHERE drama_id = 303")).mappings().all()
    assert len(scene_rows) == 1
    scene = scene_rows[0]
    assert scene["location"] == "化工厂控制室"
    assert scene["scene_code"] == "ENV_HUAGONGCHANG_T1_WIDE"
    assert scene["benchmark_asset_key"] == "ENV_HUAGONGCHANG_T1_WIDE"

    zone_rows = db_session.execute(
        text("SELECT * FROM scene_zones WHERE scene_id = :sid ORDER BY id ASC"), {"sid": scene["id"]}
    ).mappings().all()
    assert len(zone_rows) == 2, f"应当级联写入2个子区域，实际: {len(zone_rows)}"
    zone_names = [z["zone_name"] for z in zone_rows]
    assert "总监控操作台" in zone_names
    assert "高压配电柜走廊" in zone_names
    # 严格检验非默认“核心主活动区”
    assert "核心主活动区" not in zone_names

    weathering_rows = db_session.execute(
        text("""
            SELECT swv.* FROM scene_weathering_views swv
            JOIN scene_zones sz ON sz.id = swv.scene_zone_id
            WHERE sz.drama_id = 303
            ORDER BY swv.id ASC
        """)
    ).mappings().all()
    assert len(weathering_rows) >= 2, f"应当写入至少2条做旧切片，实际: {len(weathering_rows)}"
    w_descs = [w["description"] for w in weathering_rows]
    assert any("仪表盘" in d for d in w_descs)
    assert any("烧焦" in d for d in w_descs)

    # 5. 验证道具三层表 (props -> prop_damage_states -> prop_detail_views)
    prop_rows = db_session.execute(text("SELECT * FROM props WHERE drama_id = 303")).mappings().all()
    assert len(prop_rows) == 1
    prop = prop_rows[0]
    assert prop["name"] == "红色警报器"
    assert prop["prop_code"] == "PROP_JINGBAOQI_T1_STATIC"
    assert prop["benchmark_asset_key"] == "PROP_JINGBAOQI_T1_STATIC"

    dmg_rows = db_session.execute(
        text("SELECT * FROM prop_damage_states WHERE prop_id = :pid ORDER BY damage_level ASC"), {"pid": prop["id"]}
    ).mappings().all()
    assert len(dmg_rows) == 2, f"应当写入2个损伤形态(S0与S1)，实际: {len(dmg_rows)}"
    assert dmg_rows[0]["damage_level"] == 0
    assert dmg_rows[0]["state_code"] == "PROP_JINGBAOQI_T1_S0"
    assert dmg_rows[1]["damage_level"] == 3
    assert dmg_rows[1]["state_code"] == "PROP_JINGBAOQI_T1_S1"
    # 验证父子演进指针 (S1 的 parent_state_id 指向 S0)
    assert dmg_rows[1]["parent_state_id"] == dmg_rows[0]["id"]

    detail_rows = db_session.execute(
        text("""
            SELECT pdv.* FROM prop_detail_views pdv
            JOIN prop_damage_states pds ON pds.id = pdv.damage_state_id
            WHERE pds.drama_id = 303
            ORDER BY pdv.id ASC
        """)
    ).mappings().all()
    assert len(detail_rows) >= 1
    assert any("蜂鸣器" in (r["visual_prompt"] or "") for r in detail_rows)

    # 6. 幂等性测试：再次调用 persist_stage6，断言表记录不翻倍
    persist_stage6(db_session, drama_id=303, state=state, episode_num=1)
    
    assert len(db_session.execute(text("SELECT * FROM scenes WHERE drama_id = 303")).mappings().all()) == 1
    assert len(db_session.execute(text("SELECT * FROM scene_zones WHERE drama_id = 303")).mappings().all()) == 2
    assert len(db_session.execute(text("SELECT * FROM props WHERE drama_id = 303")).mappings().all()) == 1
    assert len(db_session.execute(text("SELECT * FROM prop_damage_states WHERE drama_id = 303")).mappings().all()) == 2


def test_stage3_persistence_hierarchical_support(db_session):
    """测试 persist_stage3_master_assets 对三层级联场景与道具档案的完整落库。"""
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (404, '密室疑云', 'draft', '', '')")
    )
    db_session.commit()

    scene_dossier = _build_stage3_scene_dossier(
        scene_name="密室暗道",
        time_lighting="幽暗烛光",
        detected_zones=["机关石门入口", "地下蓄水池"],
        index_hint=1,
    )
    prop_dossier = _build_stage3_prop_dossier(
        prop_name="玄铁匕首",
        deformed_verbs=["折断"],
        index_hint=1,
    )

    state = IndustrialDramaMasterState(
        drama_id=404,
        new_scene_dossiers=[scene_dossier],
        new_prop_dossiers=[prop_dossier],
    )

    # 执行 Stage 3 资产落库
    persist_stage3(db_session, drama_id=404, state=state)

    # 验证 scenes 与 scene_zones 记录
    scenes = db_session.execute(text("SELECT * FROM scenes WHERE drama_id = 404")).mappings().all()
    assert len(scenes) == 1
    assert scenes[0]["location"] == "密室暗道"
    zones = db_session.execute(text("SELECT * FROM scene_zones WHERE drama_id = 404")).mappings().all()
    assert len(zones) == 2
    zone_names = {z["zone_name"] for z in zones}
    assert "机关石门入口" in zone_names
    assert "地下蓄水池" in zone_names

    # 验证 props 与 prop_damage_states 记录
    props = db_session.execute(text("SELECT * FROM props WHERE drama_id = 404")).mappings().all()
    assert len(props) == 1
    assert props[0]["name"] == "玄铁匕首"
    damages = db_session.execute(text("SELECT * FROM prop_damage_states WHERE drama_id = 404")).mappings().all()
    assert len(damages) >= 2
