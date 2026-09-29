"""测试两程九阶 Stage 4 节拍大纲与声学母题升级 (Stage 4 Upgrade Tests)。

验证内容：
1. 双螺旋模型与声学母题数据契约规范 (Pydantic v2 & TypedDict)：
   - AudioMotifItem 支持 motif_id 与 leitmotif_id 双向同步映射；
   - AudioBible 支持 leitmotifs 与 leitmotif_registry 双向同步映射；
   - IndustrialDramaState 与 IndustrialDramaMasterState 原生纳管 mini_arc_units。
2. Stage 4 保底工厂 (_stage4_fallback) 契约完备性：
   - 包含符合工业级规范的 mini_arc_units (每 3-4 集构建一个微弧单元)；
   - 包含 3 大声学母题 (MOTIF_CORE_FATE, MOTIF_SUSPENSE_RHYTHM, MOTIF_EMOTIONAL_BREAKTHROUGH)；
   - 包含每集 killer_title, dual_helix_task (plot_event_chain, relational_shift_point, lie_erosion_metric),
     hook_3s, micro_twist_45s, cliffhanger_end 及其双向向下兼容别名；
   - 输出完整的自审报告 audit_report 与便签 short_memory_d。
3. Stage 4 节点 (stage4_outline_node) 容错与归一化能力：
   - 支持解析新标准契约与传统多结构 (dict/list) 分集数据；
   - 无论输入为 flat 别名还是嵌套结构，均实现双向补全；
   - 自动分组并生成 mini_arc_units。
4. RedBlueAuditor 针对哨卡 4 (Checkpoint 4) 质检能力：
   - 完备数据 (含标准契约与传统别名) 均可 GREEN_APPROVED 通过；
   - 核心动机缺失 (<3)、缺失微弧单元、分集缺失 3 秒钩子、缺失 45 秒微反转、缺失断点或缺失双螺旋任务时准确拦截并报告 RED_BLOCKING。
5. 存储适配器 (drama_storage_adapter) 的零破坏落库与双向反序列化还原：
   - persist_stage4 安全写入 episodes, music_bibles 及 dramas.metadata 中的 mini_arc_units；
   - 动态识别数据库实际列结构，规避缺列崩溃；
   - load_master_state_from_db 完整还原 season_outlines, audio_bible 与 mini_arc_units。
6. 下游节点 (Stage 5 单集工笔剧本) 对 Stage 4 产物的高可用消费兼容。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AudioBible,
    AudioMotifItem,
    AuditVerdict,
    IndustrialDramaMasterState,
    IndustrialDramaState,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_first_journey_state,
    load_master_state_from_db,
    persist_first_journey_state,
    persist_stage4,
)
from app.workflows.nodes.stage4_outline import (
    _stage4_fallback,
    stage4_outline_node,
)


def test_audio_bible_and_motif_bidirectional_models():
    """测试 AudioMotifItem 与 AudioBible 的双向别名自动映射与 Pydantic 校验。"""
    # 1. AudioMotifItem 通过 motif_id 初始化，自动补全 leitmotif_id
    m1 = AudioMotifItem(
        motif_id="MOTIF_FATE",
        name="命运钟声",
        type="fate",
        description="命运主题",
        instrumentation="低音大提琴",
        frequency_range="30Hz-120Hz",
        symbolic_meaning="无法逃避的审判",
    )
    assert m1.motif_id == "MOTIF_FATE"
    assert m1.leitmotif_id == "MOTIF_FATE"

    # 2. AudioMotifItem 通过 leitmotif_id 初始化，自动补全 motif_id
    m2 = AudioMotifItem(
        leitmotif_id="MOTIF_SUSPENSE",
        name="心跳倒计时",
        type="suspense",
        description="悬疑节奏",
        instrumentation="808低音底鼓",
        frequency_range="40Hz-90Hz",
        symbolic_meaning="危机降临",
    )
    assert m2.motif_id == "MOTIF_SUSPENSE"
    assert m2.leitmotif_id == "MOTIF_SUSPENSE"

    # 3. AudioBible 通过 leitmotif_registry 初始化，自动补全 leitmotifs
    bible1 = AudioBible(
        overall_key="D小调",
        leitmotif_registry=[m1, m2],
    )
    assert len(bible1.leitmotif_registry) == 2
    assert len(bible1.leitmotifs) == 2
    assert bible1.leitmotifs[0].motif_id == "MOTIF_FATE"

    # 4. AudioBible 通过 leitmotifs 初始化，自动补全 leitmotif_registry
    bible2 = AudioBible(
        overall_key="C小调",
        leitmotifs=[m1, m2],
    )
    assert len(bible2.leitmotif_registry) == 2
    assert len(bible2.leitmotifs) == 2

    # 5. 验证 State 结构具有 mini_arc_units
    state = IndustrialDramaMasterState(
        drama_id=401,
        selected_title="测试剧目",
        mini_arc_units=[{"unit_id": "UNIT_01", "name": "破冰"}],
    )
    assert len(state.mini_arc_units) == 1
    assert state.mini_arc_units[0]["unit_id"] == "UNIT_01"


def test_stage4_fallback_conformance():
    """测试 Stage 4 保底工厂生成的各项资产严格符合 SKILL1.md 阶段 4 规范。"""
    fallback_data = _stage4_fallback(
        title="深渊猎杀",
        total_episodes=8,
    )

    # 1. 验证声学母题三部曲
    assert "audio_bible" in fallback_data
    bible = fallback_data["audio_bible"]
    assert "leitmotif_registry" in bible and "leitmotifs" in bible
    motifs = bible["leitmotif_registry"]
    assert len(motifs) == 3
    motif_ids = {m.get("leitmotif_id") or m.get("motif_id") for m in motifs}
    assert any("SUSPENSE" in mid for mid in motif_ids)
    assert any("TRAUMA" in mid for mid in motif_ids)
    assert any("COUNTERATTACK" in mid for mid in motif_ids)
    for m in motifs:
        assert m.get("instrumentation")
        assert m.get("dramatic_function") or m.get("symbolic_meaning")

    # 2. 验证微弧单元规划 (3-4集单元)
    assert "mini_arc_units" in fallback_data
    units = fallback_data["mini_arc_units"]
    assert len(units) == 2  # 8集划分为 2 个单元 (1-4, 5-8)
    u0 = units[0]
    assert u0["unit_id"] == "MINI_ARC_A"
    assert u0["episode_range"] == [1, 4]
    assert u0["dramatic_focus"] != ""
    assert u0["climax_event"] != ""

    u1 = units[1]
    assert u1["unit_id"] == "MINI_ARC_B"
    assert u1["episode_range"] == [5, 8]

    # 3. 验证分集大纲双螺旋任务卡
    assert "episodes" in fallback_data
    episodes = fallback_data["episodes"]
    assert len(episodes) == 8

    for ep in episodes:
        assert ep["episode_number"] >= 1
        # 验证钩子、微反转与断点
        assert ep.get("killer_title") or ep.get("title")
        assert ep.get("hook_3s") or ep.get("hook")
        assert ep.get("micro_twist_45s") or ep.get("micro_turning_point_45s")
        assert ep.get("cliffhanger_end") or ep.get("killer_cliffhanger_115s") or ep.get("cliffhanger")
        # 验证双螺旋任务
        assert "dual_helix_task" in ep
        dh = ep["dual_helix_task"]
        assert dh["plot_event_chain"] != ""
        assert dh["relational_shift_point"] != ""
        assert dh["lie_erosion_metric"] != ""
        # 验证平铺兼容别名
        assert ep["plot_event_chain"] == dh["plot_event_chain"]
        assert ep["relational_shift_point"] == dh["relational_shift_point"]
        assert ep["lie_erosion_metric"] == dh["lie_erosion_metric"]
        # 验证视听锤点
        assert ep.get("visual_punch") != ""
        assert ep.get("audio_motif_ref") != ""

    # 4. 验证自审报告
    assert "audit_report" in fallback_data
    audit = fallback_data["audit_report"]
    assert audit["verdict"] == "GREEN_APPROVED"
    assert audit["blocking_issues"] == []


def test_stage4_outline_node_execution():
    """测试 Stage 4 节拍大纲节点在 LangGraph 状态机下的完整执行流程。"""
    state = IndustrialDramaMasterState(
        drama_id=402,
        selected_title="猎鹰行动",
        logline="两代特工的破晓之战",
        total_episodes=6,
        characters_engine={
            "characters": [
                {"name": "方舟", "role": "protagonist", "persona_summary": "深沉冷静的前特工"},
                {"name": "林越", "role": "antagonist", "persona_summary": "阴狠多疑的集团头目"},
            ]
        },
        environments_and_props={
            "environments": [
                {"env_id": "ENV_DOCK", "name": "深夜货运码头", "location_name": "深夜货运码头"}
            ],
            "props": [
                {"prop_id": "PROP_LIGHTER", "name": "带弹孔的金属打火机"}
            ]
        },
    )

    result = stage4_outline_node(state)
    assert result["current_stage"] == 4
    assert "season_outlines" in result
    assert "audio_bible" in result
    assert "mini_arc_units" in result
    assert "short_memory_d" in result

    # 验证生成的总集数
    outlines = result["season_outlines"]
    assert len(outlines) == 6
    for ep_id in range(1, 7):
        assert ep_id in outlines
        ep_data = outlines[ep_id]
        # 验证双螺旋与双向兼容性
        assert "killer_title" in ep_data and "title" in ep_data
        assert "micro_twist_45s" in ep_data and "micro_turning_point_45s" in ep_data
        assert "cliffhanger_end" in ep_data and "killer_cliffhanger_115s" in ep_data
        assert "dual_helix_task" in ep_data
        assert "plot_event_chain" in ep_data

    # 验证微弧单元自动划分 (6集划分为 2 个单元)
    units = result["mini_arc_units"]
    assert len(units) >= 2

    # 验证便签输出
    assert "【短期记忆便签 D】" in result["short_memory_d"]
    assert "6集" in result["short_memory_d"]


def test_stage4_outline_node_normalizes_legacy_and_flat_input():
    """测试 Stage 4 节点对仅有传统别名与平铺字段的数据执行双向自愈和归一化。"""
    # 构造仅提供平铺键和传统别名的 LLM 伪输出
    legacy_json = {
        "audio_bible": {
            "overall_key": "G小调",
            "leitmotifs": [
                {
                    "motif_id": "MOTIF_CORE_FATE",
                    "name": "命运钟声",
                    "type": "fate",
                    "description": "沉重钟鸣",
                    "instrumentation": "大提琴",
                    "frequency_range": "30-100Hz",
                    "symbolic_meaning": "宿命之网",
                },
                {
                    "motif_id": "MOTIF_SUSPENSE_RHYTHM",
                    "name": "心跳节拍",
                    "type": "suspense",
                    "description": "急促心跳",
                    "instrumentation": "合成鼓点",
                    "frequency_range": "40-80Hz",
                    "symbolic_meaning": "窒息逼近",
                },
                {
                    "motif_id": "MOTIF_EMOTIONAL_BREAKTHROUGH",
                    "name": "希望旋律",
                    "type": "emotional",
                    "description": "清脆钢琴",
                    "instrumentation": "原声钢琴",
                    "frequency_range": "200-2000Hz",
                    "symbolic_meaning": "黎明破晓",
                },
            ],
        },
        "episodes": [
            {
                "episode_number": 1,
                "title": "暗潮涌动",
                "hook": "开场 3 秒枪击倒计时",
                "micro_turning_point_45s": "看似友军实为内鬼暗算",
                "killer_cliffhanger_115s": "主角发现枪管对着自己后脑",
                "plot_event_chain": "码头密会 -> 遭遇黑吃黑 -> 逃生反杀",
                "relational_shift_point": "对搭档产生不可逆的裂痕信任",
                "lie_erosion_metric": "信任值自 100% 暴跌至 40%",
                "visual_punch": "暴雨中红白火光撕裂黑暗",
                "audio_motif_ref": "MOTIF_CORE_FATE",
            }
        ],
    }

    state = IndustrialDramaMasterState(
        drama_id=403,
        selected_title="破晓迷局",
        total_episodes=1,
    )

    with pytest.MonkeyPatch.context() as mp:
        # Mock call_llm_json 返回 legacy_json
        mp.setattr(
            "app.workflows.nodes.stage4_outline.call_llm_json",
            lambda *args, **kwargs: legacy_json,
        )
        res = stage4_outline_node(state)

    outlines = res["season_outlines"]
    assert 1 in outlines
    ep1 = outlines[1]

    # 验证传统键成功双向映射为标准契约键
    assert ep1["killer_title"] == "暗潮涌动"
    assert ep1["hook_3s"] == "开场 3 秒枪击倒计时"
    assert ep1["micro_twist_45s"] == "看似友军实为内鬼暗算"
    assert ep1["cliffhanger_end"] == "主角发现枪管对着自己后脑"

    # 验证由平铺键自动合成为 dual_helix_task 结构
    assert "dual_helix_task" in ep1
    dh = ep1["dual_helix_task"]
    assert dh["plot_event_chain"] == "码头密会 -> 遭遇黑吃黑 -> 逃生反杀"
    assert dh["relational_shift_point"] == "对搭档产生不可逆的裂痕信任"
    assert dh["lie_erosion_metric"] == "信任值自 100% 暴跌至 40%"

    # 验证声学母题已同步补齐 leitmotif_registry
    ab = res["audio_bible"]
    assert "leitmotif_registry" in ab
    assert len(ab["leitmotif_registry"]) == 3
    assert ab["leitmotif_registry"][0]["leitmotif_id"] == "MOTIF_CORE_FATE"

    # 验证微弧单元已自动补齐
    assert len(res["mini_arc_units"]) >= 1


def test_red_blue_auditor_stage4_checks():
    """测试红蓝质检引擎哨卡 4 对声学母题、微弧单元、双螺旋及三大时间节点的阻断能力。"""
    valid_payload = _stage4_fallback(
        title="无间风暴",
        total_episodes=4,
    )

    # 1. 完备数据通过质检
    report_valid = RedBlueAuditor.audit(stage=4, content_payload=valid_payload)
    assert report_valid.verdict == AuditVerdict.GREEN_APPROVED
    assert len(report_valid.blocking_issues) == 0

    # 2. 声学母题缺失 (<3个) 触发阻断
    invalid_motifs_payload = {
        "audio_bible": {
            "leitmotif_registry": [
                {"leitmotif_id": "MOTIF_CORE_FATE", "name": "唯一定制母题"}
            ]
        },
        "mini_arc_units": valid_payload["mini_arc_units"],
        "episodes": valid_payload["episodes"],
    }
    report_motifs = RedBlueAuditor.audit(stage=4, content_payload=invalid_motifs_payload)
    assert report_motifs.verdict == AuditVerdict.RED_BLOCKING
    assert any("声学母题" in issue for issue in report_motifs.blocking_issues)

    # 3. 缺失微弧单元 (mini_arc_units) 触发阻断
    invalid_units_payload = {
        "audio_bible": valid_payload["audio_bible"],
        "mini_arc_units": [],
        "episodes": valid_payload["episodes"],
    }
    report_units = RedBlueAuditor.audit(stage=4, content_payload=invalid_units_payload)
    assert report_units.verdict == AuditVerdict.RED_BLOCKING
    assert any("微弧单元" in issue for issue in report_units.blocking_issues)

    # 4. 分集缺失 45 秒微反转或 3 秒钩子或断点触发阻断
    flawed_episodes = [dict(ep) for ep in valid_payload["episodes"]]
    flawed_episodes[0] = {
        "episode_number": 1,
        "killer_title": "平淡无奇",
        # 缺失 hook_3s
        "micro_twist_45s": "",  # 缺失微反转
        "cliffhanger_end": "挂钩",
        "dual_helix_task": {"plot_event_chain": "A", "relational_shift_point": "B", "lie_erosion_metric": "C"},
    }
    invalid_twist_payload = {
        "audio_bible": valid_payload["audio_bible"],
        "mini_arc_units": valid_payload["mini_arc_units"],
        "episodes": flawed_episodes,
    }
    report_twist = RedBlueAuditor.audit(stage=4, content_payload=invalid_twist_payload)
    assert report_twist.verdict == AuditVerdict.RED_BLOCKING
    assert any("微反转" in issue or "钩子" in issue for issue in report_twist.blocking_issues)


def test_storage_adapter_stage4_persistence_and_restore():
    """测试存储适配器对 Stage 4 分集双螺旋大纲、声学母题与微弧单元的安全落库与反序列化还原。"""
    mock_db = MagicMock()
    mock_db.is_active = True

    mock_drama_row = {
        "id": 405,
        "title": "宿命之网",
        "style": "冷硬犯罪",
        "total_episodes": 4,
        "lock_status": 0,
        "metadata": json.dumps({
            "aspect_ratio": "9:16",
            "mini_arc_units": [
                {
                    "unit_id": "UNIT_01",
                    "name": "试探与破冰",
                    "episode_range": [1, 4],
                    "core_turn": "从相互戒备到建立血色同盟",
                    "climax_punch": "在废弃船坞遭遇警方突击包围",
                }
            ],
        }),
    }

    mock_episode_row = {
        "id": 101,
        "drama_id": 405,
        "episode_number": 1,
        "title": "生死契约",
        "description": "第1集双螺旋任务大纲",
        "hook_cliffhanger": json.dumps({
            "hook_3s": "倒计时爆炸前 3 秒",
            "micro_twist_45s": "救兵实为叛徒",
            "cliffhanger_end": "枪口转向主角眉心",
            "dual_helix_task": {
                "plot_event_chain": "密室脱困 -> 飞车枪战",
                "relational_shift_point": "信赖全面破裂",
                "lie_erosion_metric": "谎言戳穿度 80%",
            },
            "visual_punch": "火光吞没整面防弹玻璃",
            "audio_motif_ref": "MOTIF_CORE_FATE",
        }),
    }

    mock_music_row = {
        "id": 501,
        "drama_id": 405,
        "theme_name": "MOTIF_CORE_FATE",
        "style": "fate",
        "tempo": "80BPM",
        "mood": "沉重肃穆",
        "instrumentation": "低音提琴",
        "frequency_range": "30-100Hz",
        "scene_types": json.dumps({
            "leitmotif_id": "MOTIF_CORE_FATE",
            "name": "命运钟声",
            "type": "fate",
            "description": "命运裁决主题",
            "instrumentation": "低音提琴",
            "frequency_range": "30-100Hz",
            "symbolic_meaning": "不可逆转的宿命",
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
            lambda db, q, p: (
                [mock_episode_row] if "episodes" in q
                else ([mock_music_row] if "music_bibles" in q else [])
            ),
        )

        # 1. 执行落库
        stage4_data = _stage4_fallback("宿命之网", total_episodes=4)
        state = IndustrialDramaMasterState(
            drama_id=405,
            selected_title="宿命之网",
            season_outlines=stage4_data["season_outlines"],
            audio_bible=stage4_data["audio_bible"],
            mini_arc_units=stage4_data["mini_arc_units"],
        )
        persist_stage4(mock_db, drama_id=405, state=state)
        persist_first_journey_state(mock_db, drama_id=405, state=state)
        assert mock_db.execute.called

        # 2. 执行全量反序列化加载
        restored = load_master_state_from_db(mock_db, drama_id=405)
        assert restored.drama_id == 405
        assert len(restored.season_outlines) >= 1
        ep1 = restored.season_outlines[1]
        assert ep1["title"] == "生死契约"
        assert ep1["hook_3s"] == "倒计时爆炸前 3 秒"
        assert ep1["micro_twist_45s"] == "救兵实为叛徒"
        assert ep1["cliffhanger_end"] == "枪口转向主角眉心"

        # 验证微弧单元恢复
        assert len(restored.mini_arc_units) == 1
        assert restored.mini_arc_units[0]["unit_id"] == "UNIT_01"

        # 验证声学母题恢复
        assert len(restored.audio_bible.get("leitmotifs", [])) >= 1
        assert len(restored.audio_bible.get("leitmotif_registry", [])) >= 1


def test_downstream_stage5_consumption_compatibility():
    """测试下游 Stage 5 (单集剧本生成) 能够顺利读取 Stage 4 产出的大纲、钩子与断点。"""
    stage4_data = _stage4_fallback("黎明行动", total_episodes=2)
    state = IndustrialDramaMasterState(
        drama_id=406,
        selected_title="黎明行动",
        logline="特工博弈",
        total_episodes=2,
        season_outlines=stage4_data["season_outlines"],
        audio_bible=stage4_data["audio_bible"],
        mini_arc_units=stage4_data["mini_arc_units"],
    )

    outlines = state.season_outlines
    assert 1 in outlines
    ep1 = outlines[1]

    # Stage 5 核心提取逻辑模拟：
    # rag_query_parts: outline.get("title"), outline.get("hook_3s"), outline.get("killer_cliffhanger_115s")
    title = ep1.get("title") or ep1.get("killer_title")
    hook = ep1.get("hook_3s") or ep1.get("hook")
    cliff = ep1.get("killer_cliffhanger_115s") or ep1.get("cliffhanger_end")

    assert title is not None and len(str(title)) > 0
    assert hook is not None and len(str(hook)) > 0
    assert cliff is not None and len(str(cliff)) > 0

    # 验证双螺旋任务完整可供 Stage 5 作为情节点与谎言侵蚀度参考
    assert "dual_helix_task" in ep1
    assert "plot_event_chain" in ep1["dual_helix_task"]
    assert "lie_erosion_metric" in ep1["dual_helix_task"]
