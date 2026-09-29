"""测试两程九阶 Stage 3 空间物证与声学物理升级 (Stage 3 Upgrade Tests)。

验证内容：
1. ID 归一化规范：
   - _normalize_env_id 与 _normalize_prop_id 遵循 ENV_<NAME> 与 PROP_<NAME> 铁律；
2. Stage 3 节点与回退工厂数据契约完整性 (03_environments_props.json)：
   - env_id、level (primary_tier1 / transitional_tier2)、costume_resonance_check (True)；
   - three_layer_aging 与 weathering_layers 双向同源契约；
   - prop_id、level (hero_tier1 / anchor_tier2)、physical_specs、damage_scale、foley_resistance (+3.0dB)；
   - 哨卡 3 自审契约 audit_report (GREEN_APPROVED) 与短期记忆便签 short_memory_c。
3. RedBlueAuditor 针对 Stage 3 质检能力：
   - 完备数据通过审查；
   - 缺做旧层、同源共振为 False、物证缺破损尺度或缺 +3.0dB 拟音时触发阻断。
4. 存储适配器 (drama_storage_adapter) 的零破坏落库与双向反序列化还原。
5. 下游节点（Stage 4 / Stage 6）对 Stage 3 空间物证资产的无缝消费。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaMasterState,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_first_journey_state,
    persist_first_journey_state,
    persist_stage3,
)
from app.workflows.nodes.stage2_character import _stage2_fallback
from app.workflows.nodes.stage3_environment_prop import (
    _normalize_env_id,
    _normalize_prop_id,
    _stage3_fallback,
    stage3_environment_prop_node,
)
from app.workflows.nodes.stage4_outline import stage4_outline_node
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node


def test_normalize_env_and_prop_ids():
    """测试场景与道具唯一标识规范化。"""
    assert _normalize_env_id("ENV_WAREHOUSE", "废弃仓库", 0) == "ENV_WAREHOUSE"
    assert _normalize_env_id("warehouse_dock", "码头", 1) == "ENV_WAREHOUSE_DOCK"
    assert _normalize_env_id("", "码头仓库", 2) == "ENV_MATOUCANGKU"
    assert _normalize_env_id("", "", 2) == "ENV_SCENE_03"
    assert _normalize_env_id(None, "Dock1", 3) == "ENV_DOCK1"

    assert _normalize_prop_id("PROP_BLOOD_LETTER", "血书", 0) == "PROP_BLOOD_LETTER"
    assert _normalize_prop_id("old_pocket_watch", "旧怀表", 1) == "PROP_OLD_POCKET_WATCH"
    assert _normalize_prop_id("", "信物", 2) == "PROP_XINWU"
    assert _normalize_prop_id("", "", 2) == "PROP_ITEM_03"
    assert _normalize_prop_id(None, "Watch", 3) == "PROP_WATCH"


def test_stage3_fallback_and_node_conformance():
    """测试 Stage 3 节点与保底工厂输出满足全字段契约与红蓝自审规范。"""
    chars = _stage2_fallback("命悬一线", "警察与卧底的生死周旋")["characters"]
    state = IndustrialDramaMasterState(
        drama_id=301,
        selected_title="命悬一线",
        logline="警察与卧底的生死周旋",
        characters_engine={"characters": chars},
        short_memory_b="【短期记忆便签 B】主角陆沉(高颧骨, 600g粗花呢大衣泥斑)，反派韩泰",
    )

    res = stage3_environment_prop_node(state)
    assert res["current_stage"] == 3
    assert "environments_and_props" in res
    env_props = res["environments_and_props"]
    envs = env_props["environments"]
    props = env_props["props"]

    # 1. 场景契约校验
    assert len(envs) >= 2
    primary_env = envs[0]
    assert primary_env["env_id"].startswith("ENV_")
    assert primary_env["level"] == "primary_tier1"
    assert primary_env["costume_resonance_check"] is True
    assert "three_layer_aging" in primary_env
    tla = primary_env["three_layer_aging"]
    assert "structure" in tla and "lived_grime" in tla and "light_and_air" in tla
    # 验证与角色服装同源泥斑
    assert "泥" in tla["lived_grime"]

    # 别名双向同步
    wl = primary_env["weathering_layers"]
    assert wl["structural"] == tla["structure"]
    assert wl["living"] == tla["lived_grime"]
    assert wl["optical"] == tla["light_and_air"]

    # 2. 道具契约校验
    assert len(props) >= 2
    hero_prop = props[0]
    assert hero_prop["prop_id"].startswith("PROP_")
    assert hero_prop["level"] == "hero_tier1"
    assert hero_prop["damage_scale"] != ""
    assert "+3" in hero_prop["foley_resistance"]

    assert "physical_specs" in hero_prop
    specs = hero_prop["physical_specs"]
    assert specs["material_damage_dimensions"] != ""
    assert specs["weight_and_haptic_resistance"] != ""
    assert specs["foley_boost_db"] == "+3.0dB"

    # 3. 自审契约与便签
    assert "audit_report" in env_props
    audit = env_props["audit_report"]
    assert audit["verdict"] == "GREEN_APPROVED"
    assert "blue_team" in audit and "red_team_critic" in audit

    assert "short_memory_c" in res
    assert "【短期记忆便签 C】" in res["short_memory_c"]


def test_red_blue_auditor_stage3_checks():
    """测试红蓝质检引擎哨卡 3 对做旧层、同源共振、破损尺度及 +3.0dB 拟音的拦截与通过。"""
    chars = _stage2_fallback("命悬一线", "测试")["characters"]
    valid_payload = _stage3_fallback("命悬一线", "测试", chars)

    # 1. 完备数据通过审查
    report_valid = RedBlueAuditor.audit(stage=3, content_payload=valid_payload)
    assert report_valid.verdict == AuditVerdict.GREEN_APPROVED
    assert len(report_valid.blocking_issues) == 0

    # 2. 缺失做旧层触发阻断
    invalid_aging_payload = {
        "environments": [
            {
                "env_id": "ENV_TEST",
                "location_name": "崭新无做旧房间",
                "costume_resonance_check": True,
                "three_layer_aging": {"structure": "承重墙"},  # 缺失 lived_grime 与 light_and_air
            }
        ],
        "props": valid_payload["props"],
    }
    report_aging = RedBlueAuditor.audit(stage=3, content_payload=invalid_aging_payload)
    assert report_aging.verdict == AuditVerdict.RED_BLOCKING
    assert any("三层做旧架构" in issue for issue in report_aging.blocking_issues)

    # 3. 同源共振审查未通过 (costume_resonance_check: False) 触发阻断
    invalid_resonance_payload = {
        "environments": [
            {
                "env_id": "ENV_TEST",
                "location_name": "穿破衣进样板间",
                "costume_resonance_check": False,
                "three_layer_aging": {
                    "structure": "钢筋",
                    "lived_grime": "油污",
                    "light_and_air": "微光",
                },
            }
        ],
        "props": valid_payload["props"],
    }
    report_res = RedBlueAuditor.audit(stage=3, content_payload=invalid_resonance_payload)
    assert report_res.verdict == AuditVerdict.RED_BLOCKING
    assert any("costume_resonance_check" in issue for issue in report_res.blocking_issues)

    # 4. 核心物证缺失 +3.0dB 拟音触发阻断
    invalid_foley_payload = {
        "environments": valid_payload["environments"],
        "props": [
            {
                "prop_id": "PROP_TEST",
                "name": "静音物证",
                "level": "hero_tier1",
                "damage_scale": "微小凹痕2mm",
                "foley_resistance": "普通摩擦声",  # 未包含 +3.0dB
            }
        ],
    }
    report_foley = RedBlueAuditor.audit(stage=3, content_payload=invalid_foley_payload)
    assert report_foley.verdict == AuditVerdict.RED_BLOCKING
    assert any("+3.0dB" in issue for issue in report_foley.blocking_issues)


def test_storage_adapter_stage3_persistence_and_restore():
    """测试存储适配器对 Stage 3 场景与物证的全息落库与还原。"""
    mock_db = MagicMock()
    mock_drama_row = {
        "id": 303,
        "title": "深渊对峙",
        "style": "冷硬工业风",
        "total_episodes": 8,
        "lock_status": 0,
        "metadata": json.dumps({"aspect_ratio": "9:16", "journey": "journey_1_literary"}),
    }

    mock_scene_row = {
        "id": 11,
        "drama_id": 303,
        "location": "7号防空洞仓库",
        "name": "7号防空洞仓库",
        "time": "深夜暴雨",
        "prompt": "cinematic gritty shelter",
        "atmosphere": "死寂冷酷",
        "extra_images": json.dumps({
            "env_id": "ENV_SHELTER_7",
            "level": "primary_tier1",
            "costume_resonance_check": True,
            "three_layer_aging": {
                "structure": "锈蚀工字钢",
                "lived_grime": "泥脚印与水渍",
                "light_and_air": "丁达尔光束",
            },
            "weathering_layers": {
                "structural": "锈蚀工字钢",
                "living": "泥脚印与水渍",
                "optical": "丁达尔光束",
            },
        }),
    }

    mock_prop_row = {
        "id": 21,
        "drama_id": 303,
        "name": "生锈的指纹录音笔",
        "type": "narrative_reversal",
        "description": "反转核心录音",
        "prompt": "macro close up recorder",
        "extra_images": json.dumps({
            "prop_id": "PROP_RECORDER",
            "level": "hero_tier1",
            "damage_scale": "凹痕3mm",
            "foley_resistance": "金属撞击声 (+3.0dB)",
            "physical_specs": {
                "material_damage_dimensions": "凹痕3mm",
                "weight_and_haptic_resistance": "300g金属压手",
                "foley_boost_db": "+3.0dB",
            },
        }),
    }

    def fake_execute(query, params=None):
        return MagicMock()

    mock_db.execute.side_effect = fake_execute

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.workflows.adapters.drama_storage_adapter.fetch_one",
            lambda db, q, p: mock_drama_row if "dramas" in q else None,
        )
        mp.setattr(
            "app.workflows.adapters.drama_storage_adapter.fetch_all",
            lambda db, q, p: [mock_scene_row] if "scenes" in q else ([mock_prop_row] if "props" in q else []),
        )

        # 1. 测试落库
        chars = _stage2_fallback("深渊对峙", "测试")["characters"]
        stage3_data = _stage3_fallback("深渊对峙", "测试", chars)
        state = IndustrialDramaMasterState(
            drama_id=303,
            selected_title="深渊对峙",
            environments_and_props=stage3_data,
        )
        persist_first_journey_state(mock_db, drama_id=303, state=state)
        assert mock_db.execute.called

        # 2. 测试反序列化还原
        loaded_state = load_first_journey_state(mock_db, drama_id=303)
        assert loaded_state.drama_id == 303
        assert "environments" in loaded_state.environments_and_props
        assert "props" in loaded_state.environments_and_props

        loaded_envs = loaded_state.environments_and_props["environments"]
        assert len(loaded_envs) == 1
        e0 = loaded_envs[0]
        assert e0["env_id"] == "ENV_SHELTER_7"
        assert e0["level"] == "primary_tier1"
        assert e0["costume_resonance_check"] is True
        assert e0["three_layer_aging"]["structure"] == "锈蚀工字钢"
        assert e0["weathering_layers"]["structural"] == "锈蚀工字钢"

        loaded_props = loaded_state.environments_and_props["props"]
        assert len(loaded_props) == 1
        p0 = loaded_props[0]
        assert p0["prop_id"] == "PROP_RECORDER"
        assert p0["level"] == "hero_tier1"
        assert p0["physical_specs"]["foley_boost_db"] == "+3.0dB"
        assert "+3" in p0["foley_resistance"]


def test_downstream_stage4_and_stage6_compatibility():
    """测试下游 Stage 4 与 Stage 6 节点能无缝消费 Stage 3 产出的空间与物证资产。"""
    chars = _stage2_fallback("深渊对峙", "测试")["characters"]
    stage3_data = _stage3_fallback("深渊对峙", "测试", chars)

    state = IndustrialDramaMasterState(
        drama_id=404,
        selected_title="深渊对峙",
        logline="硬汉刑警绝境破局",
        total_episodes=5,
        current_visual_episode=1,
        characters_engine={"characters": chars},
        environments_and_props=stage3_data,
        short_memory_c=stage3_data["short_memory_c"],
    )

    # 1. 运行下游 Stage 4 (全季大纲与音乐动机母库)
    res_stage4 = stage4_outline_node(state)
    assert res_stage4["current_stage"] == 4
    assert "audio_bible" in res_stage4
    assert "season_outlines" in res_stage4
    outlines = res_stage4["season_outlines"]
    assert len(outlines) == 5

    # 2. 模拟集剧本并运行下游 Stage 6 (资产真理源提纯)
    state.completed_screenplays = {
        1: {
            "episode_num": 1,
            "title": "开局死局",
            "body_markdown": "**陆沉**在废弃仓库踩灭烟头，举起生锈的关键物证。",
        }
    }
    res_stage6 = stage6_asset_truth_node(state)
    assert res_stage6["current_stage"] == 6
    manifest = res_stage6["episode_resource_manifests"][1]
    assert len(manifest.environments) >= 1
    assert len(manifest.props) >= 1
    assert "weathering_layers" in str(manifest.environments[0])
    assert "+3" in str(manifest.props[0])
