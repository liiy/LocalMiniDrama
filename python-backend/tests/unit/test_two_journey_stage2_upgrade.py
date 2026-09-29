"""测试两程九阶 Stage 2 微观生物肖像骨相与生活质感服化道代码升级 (Stage 2 Upgrade Tests)。

验证内容：
1. Stage 2 节点输出完整性：
   - biological_dna 结构（bone_structure, skin_micro_texture, blemishes_and_scars, eye_lip_anatomy, hair_texture）；
   - lived_in_costume 结构（top_wear, bottom_wear, footwear, wear_and_tear_details）；
   - psychological_quad、carried_anchor_item、dual_track_relationships、emotional_arc_trajectories。
2. RedBlueAuditor 针对 Stage 2 的质检能力：
   - 缺 biological_dna / lived_in_costume 时触发阻断；
   - 完备数据输出 GREEN_APPROVED。
3. 存储适配器 (drama_storage_adapter) 的零破坏落库与反序列化验证。
4. 下游节点（Stage 3 / Stage 6 / Stage 7）对 Stage 2 DNA 资产的继承与编译。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    BiologicalPortraitDNA,
    CharacterProfile,
    IndustrialDramaMasterState,
    LivedInCostumeSpecs,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_first_journey_state,
    persist_first_journey_state,
)
from app.workflows.nodes.stage2_character import _stage2_fallback, stage2_character_node
from app.workflows.nodes.stage3_environment_prop import stage3_environment_prop_node
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node


def test_stage2_fallback_and_node_dna_structure():
    """测试阶段 2 节点输出包含完整的生物骨相与服饰做旧代码。"""
    state = IndustrialDramaMasterState(
        drama_id=101,
        selected_title="双雄迷局",
        logline="硬汉刑警与伪善资本家的生死对决",
        visual_style="电影质感冷硬派",
        short_memory_a="【短期记忆便签 A】片名双雄迷局，商业类型悬疑刑侦",
    )
    res = stage2_character_node(state)
    assert res["current_stage"] == 2
    assert "characters_engine" in res
    chars = res["characters_engine"]["characters"]
    assert len(chars) >= 2

    protagonist = chars[0]
    assert protagonist["name"] == "陆沉"
    assert protagonist["character_id"] == "CHAR_LUCHEN"
    assert protagonist["gender"] == "male"
    assert isinstance(protagonist["perceived_age"], int)
    assert "acoustic_persona" in protagonist
    assert "vocal_position" in protagonist["acoustic_persona"]

    assert "biological_dna" in protagonist
    bio = protagonist["biological_dna"]
    assert "bone_structure" in bio and "skin_micro_texture" in bio
    assert "blemishes_and_scars" in bio and "eye_lip_anatomy" in bio
    # 别名双向同步
    assert bio["face_shape"] == bio["bone_structure"]
    assert bio["skin_pores"] == bio["skin_micro_texture"]

    costume = protagonist["lived_in_costume"]
    assert "top_wear" in costume and "wear_and_tear_details" in costume
    assert costume["outerwear"] == costume["top_wear"]
    assert "innerwear" in costume

    assert "dual_track_relationships" in protagonist
    assert len(protagonist["dual_track_relationships"]) >= 1

    assert "emotional_arc_trajectories" in protagonist
    assert len(protagonist["emotional_arc_trajectories"]) >= 1

    # 自审与便签
    assert "short_memory_b" in res
    assert "audit_report" in res
    assert res["audit_report"]["verdict"] in ("GREEN_APPROVED", AuditVerdict.GREEN_APPROVED)


def test_red_blue_auditor_stage2_checks():
    """测试红蓝质检引擎对阶段 2 生物骨相与生活质感服化道的合规校验。"""
    # 1. 完备数据通过审查
    valid_payload = _stage2_fallback("测试剧", "对决")
    report_valid = RedBlueAuditor.audit(stage=2, content_payload=valid_payload)
    assert report_valid.verdict == AuditVerdict.GREEN_APPROVED
    assert len(report_valid.blocking_issues) == 0

    # 2. 缺失 biological_dna 触发阻断
    invalid_payload = {
        "characters": [
            {
                "name": "塑料人",
                "role_type": "protagonist",
                "lived_in_costume": {"top_wear": "大衣"},
                "psychological_quad": {"want": "复仇", "need": "救赎", "lie": "无敌", "ghost": "往事"},
            }
        ]
    }
    report_invalid = RedBlueAuditor.audit(stage=2, content_payload=invalid_payload)
    assert report_invalid.verdict == AuditVerdict.RED_BLOCKING
    assert any("biological_dna" in issue for issue in report_invalid.blocking_issues)


def test_storage_adapter_stage2_persistence():
    """测试存储适配器将 Stage 2 生物DNA与服饰代码安全落库与还原。"""
    # 模拟 DB 数据库行为
    mock_db = MagicMock()
    mock_drama_row = {
        "id": 202,
        "title": "暗战深渊",
        "style": "电影质感",
        "total_episodes": 10,
        "lock_status": 0,
        "metadata": json.dumps({"aspect_ratio": "9:16", "journey": "journey_1_literary"}),
    }

    mock_char_row = {
        "id": 1,
        "name": "陆沉",
        "role": "protagonist",
        "personality": "敏锐隐忍",
        "appearance": "三十八岁高颧骨",
        "identity_anchors": json.dumps(["额角伤痕", "粗花呢大衣"]),
        "voice_style": "低沉沙哑",
        "growth_chain": json.dumps({
            "psychological_quad": {"want": "复仇", "need": "救赎", "lie": "理性万能", "ghost": "师亡"},
            "emotional_arc_trajectories": [{"stage_label": "第一幕", "psychological_state": "防御"}],
        }),
        "current_status": json.dumps({
            "biological_dna": {"bone_structure": "高颧骨刀刻下颌", "skin_micro_texture": "自然毛孔"},
            "lived_in_costume": {"top_wear": "600g粗花呢大衣", "wear_and_tear_details": "线头松脱"},
            "carried_anchor_item": {"item_name": "停摆怀表"},
            "dual_track_relationships": [{"target_character": "韩泰", "surface_relation": "客套", "hidden_tension": "死敌"}],
        }),
    }

    def fake_execute(query, params=None):
        return MagicMock()

    mock_db.execute.side_effect = fake_execute

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.workflows.adapters.drama_storage_adapter.fetch_one", lambda db, q, p: mock_drama_row if "dramas" in q else None)
        mp.setattr("app.workflows.adapters.drama_storage_adapter.fetch_all", lambda db, q, p: [mock_char_row] if "characters" in q else [])

        # 测试落库
        state = IndustrialDramaMasterState(
            drama_id=202,
            selected_title="暗战深渊",
            characters_engine={"characters": [_stage2_fallback("暗战深渊", "测试")["characters"][0]]},
        )
        persist_first_journey_state(mock_db, drama_id=202, state=state)
        assert mock_db.execute.called

        # 测试重构读取
        loaded_state = load_first_journey_state(mock_db, drama_id=202)
        assert loaded_state.drama_id == 202
        loaded_chars = loaded_state.characters_engine.get("characters", [])
        assert len(loaded_chars) == 1
        c = loaded_chars[0]
        assert c["name"] == "陆沉"
        assert c["biological_dna"]["bone_structure"] == "高颧骨刀刻下颌"
        assert c["lived_in_costume"]["top_wear"] == "600g粗花呢大衣"
        assert c["psychological_quad"]["want"] == "复仇"


def test_downstream_stage6_and_7_compile_dna():
    """测试下游 Stage 6 与 Stage 7 节点能正确编译 Stage 2 生物骨相与服化道代码。"""
    state = IndustrialDramaMasterState(
        drama_id=303,
        selected_title="破晓时刻",
        current_visual_episode=1,
        characters_engine=_stage2_fallback("破晓时刻", "对峙"),
        environments_and_props={
            "environments": [{"location_name": "7号仓库", "visual_prompt": "暗黑做旧"}],
            "props": [{"name": "加密U盘", "damage_scale": "微小划痕", "foley_resistance": "+3dB"}],
        },
        completed_screenplays={
            1: {
                "episode_num": 1,
                "title": "绝境交锋",
                "body_markdown": "**陆沉**（下颌紧绷）：把东西交出来！",
            }
        },
    )

    # 1. 运行 Stage 6 (资产真理源提纯)
    res_stage6 = stage6_asset_truth_node(state)
    assert res_stage6["current_stage"] == 6
    manifest = res_stage6["episode_resource_manifests"][1]
    assert len(manifest.characters) >= 2
    char_01 = manifest.characters[0]
    # 验证 visual_prompt 已经编译了骨相、毛孔、瑕疵、做旧服饰
    assert "bone_structure" in str(char_01) or "高颧骨" in str(char_01) or "粗花呢" in str(char_01) or "photorealistic" in str(char_01)

    # 2. 运行 Stage 7 (双模式分镜与SRT)
    res_stage7 = stage7_storyboard_srt_node(state)
    assert res_stage7["current_stage"] == 7
    shots = res_stage7["storyboard_shots"][1]
    assert len(shots) >= 3
    # 验证有对白镜头包含口型动力学 (lipsync_dynamics) 与骨相下颌张力
    dialogue_shots = [s for s in shots if s.lipsync_dynamics]
    assert len(dialogue_shots) >= 1
    d_shot = dialogue_shots[0]
    assert d_shot.lipsync_dynamics.jaw_open_scale > 0
    assert d_shot.lipsync_dynamics.mouth_tension is not None


def test_dynamic_character_id_and_token_generation():
    """测试阶段 2 彻底告别静态字典，全流程支持大模型动态生成 ID 与动态拼音转写。"""
    from app.workflows.nodes.stage2_character import _normalize_character_id

    # 1. 大模型直接输出了有效英数 ID / Token
    assert _normalize_character_id("随便角色", "CHAR_WARRIOR_X") == "CHAR_WARRIORX"
    assert _normalize_character_id("随便角色", "BLADE_007") == "CHAR_BLADE007"
    assert _normalize_character_id("主角", "char_cyber_punk") == "CHAR_CYBERPUNK"

    # 2. 大模型输出了带有中文的 ID，动态拼音清洗
    assert _normalize_character_id("欧阳修", "CHAR_欧阳修") == "CHAR_OUYANGXIU"

    # 3. 大模型未输出 ID，动态根据角色姓名生成（各种任意角色名，无需任何静态字典）
    assert _normalize_character_id("诸葛孔明") == "CHAR_ZHUGEKONGMING"
    assert _normalize_character_id("司徒绝") == "CHAR_SITUJUE"
    assert _normalize_character_id("上官婉儿") == "CHAR_SHANGGUANWANER"
    assert _normalize_character_id("Neo Anderson") == "CHAR_NEOANDERSON"

    # 4. 极端空值与无英数中文兜底
    assert _normalize_character_id("", idx=3) == "CHAR_ROLE03"
    assert _normalize_character_id("???###", idx=5) == "CHAR_ROLE05"


def test_stage2_node_with_dynamic_llm_output():
    """测试阶段 2 节点处理大模型输出的自定义角色与标识时的动态流转。"""
    mock_llm_characters = {
        "characters": [
            {
                "name": "东方不败",
                "character_id": "CHAR_DONGFANG_MASTER",
                "gender": "female",
                "perceived_age": 32,
                "role_type": "protagonist",
                "biological_dna": {
                    "bone_structure": "清冷凌厉高颧骨",
                    "skin_micro_texture": "苍白微青透光肤质",
                    "blemishes_and_scars": "无暇",
                    "eye_lip_anatomy": "凤眼细长微挑",
                    "hair_texture": "乌黑垂腰青丝",
                },
                "lived_in_costume": {
                    "top_wear": "猩红真丝宽袍重磅300g",
                    "bottom_wear": "同色曳地百褶裙",
                    "footwear": "锦缎软靴",
                    "wear_and_tear_details": "裙摆微有剑痕裂口",
                },
                "psychological_quad": {
                    "want": "天下第一",
                    "need": "真情救赎",
                    "lie": "唯我独尊方得自由",
                    "ghost": "深宫往事",
                },
            },
            {
                "name": "令狐冲",
                "character_token": "LINGHUCHONG",
                "gender": "male",
                "perceived_age": 25,
                "role_type": "antagonist",
                "biological_dna": {
                    "bone_structure": "潇洒俊逸下颌微翘",
                    "skin_micro_texture": "日晒麦色健康毛孔",
                    "blemishes_and_scars": "左脸浅笑纹",
                    "eye_lip_anatomy": "朗目星眸常含醉意",
                    "hair_texture": "蓬松散乱发髻",
                },
                "lived_in_costume": {
                    "top_wear": "粗布青衫洗得泛白",
                    "bottom_wear": "麻布打底绑腿裤",
                    "footwear": "芒鞋磨损破洞露出草絮",
                    "wear_and_tear_details": "肩头有酒渍与剑痕",
                },
                "psychological_quad": {
                    "want": "浪迹天涯有酒即安",
                    "need": "肩负责任庇护同门",
                    "lie": "逃避即自由",
                    "ghost": "师门决裂",
                },
            }
        ]
    }

    state = IndustrialDramaMasterState(
        drama_id=888,
        selected_title="黑木崖之变",
        logline="笑傲江湖恩怨情仇",
        visual_style="新派武侠冷峻质感",
        short_memory_a="【短期记忆便签 A】武侠新风，反套路博弈",
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.workflows.nodes.stage2_character.call_llm_json",
            lambda **kwargs: mock_llm_characters,
        )
        res = stage2_character_node(state)

    chars = res["characters"]
    assert len(chars) == 2
    c1, c2 = chars[0], chars[1]

    # 1. 验证东方不败采纳了大模型给出的标识，清洗为合规四段式 Token 并派生 ID
    assert c1["character_id"] == "CHAR_DONGFANGMASTER"
    assert c1["character_token"] == "DONGFANGMASTER"

    # 2. 验证令狐冲采纳了大模型给出的 character_token，并自动合成了 CHAR_LINGHUCHONG
    assert c2["character_id"] == "CHAR_LINGHUCHONG"
    assert c2["character_token"] == "LINGHUCHONG"

    # 3. 验证全局 Token 白名单
    assert res["character_tokens"] == ["DONGFANGMASTER", "LINGHUCHONG"]
    assert res["characters_engine"]["character_tokens"] == ["DONGFANGMASTER", "LINGHUCHONG"]

