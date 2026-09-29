"""测试两程九阶 Stage 7 单镜头工业执行表生成与 SRT 导出升级 (Stage 7 Upgrade Tests)。

遵循《Skill规则表》v10.0.0 与《剧本创作工坊_两程九阶实施计划》标准规范：
1. 阶段 7 数据契约模型与字段校验 (StoryboardShot, ModeBManifestCheckDict, MasterState)：
   - 整秒时长 (2.0s~7.0s) 与字段别名容错；
   - 目标视频生成引擎 target_engine (wan3.0 / seedance2.5 / minimax_h3)；
   - 首尾帧模式 first_last_frame 与多模态参考 multi_image_reference 契约；
   - 口型动力学与台词完整性 is_dialogue_complete_in_shot；
   - episode_mode_b_manifest_checks 汇总自检清单契约。
2. 确定性时长测算与自适应拆镜算子 (ShotDurationCalculator - 算子2)：
   - T_total = T_action + T_prop + (dialogue_len / speed + 0.3s) + 0.4s；
   - 允许整秒集合 {2.0, 3.0, 4.0, 5.0, 6.0, 7.0}；
   - > 6.5s 强制自适应拆镜解耦为 动作镜 (Shot A) + 对白镜 (Shot B)；
   - 整集累计总时长 ±6.0s 容差校验。
3. 多引擎提示词编译器与禁忌词清障 (算子3与算子5)：
   - Wan 3.0 / Seedance 2.5 / MiniMax H3 分支结构化语法；
   - 提示词黑名单 (jaw_open_scale, 自然眨眼, 呼吸起伏, 4k, photorealistic 等) 强力清洗；
   - 口型动力学静默元数据安全隔离 (jaw_open_scale 100% 隔离在数据模型，严禁渗入 video_prompt)。
4. Stage 7 业务节点与保底工厂闭环 (stage7_storyboard_srt_node & _stage7_fallback)：
   - 包含模式 A 首尾帧与模式 B 多图参考 (图片 <= 4 张，首图必须为场景环境)；
   - 全息声音算子 (+3dB 拟音、情境 TTS 腔体与 Leitmotif)；
   - 毫秒级标准 SRT 字幕导出。
5. 哨卡 7 (Checkpoint 7) 红蓝对抗审查：
   - 完备合规分镜判定为 GREEN_APPROVED；
   - 非整数秒拦截；
   - 模式 B 参考图超过 4 张拦截；
   - 模式 B 缺失 PASS_9 签名拦截；
   - 模式 B 包含禁忌词/生理口型词拦截；
   - 对白未在镜头内完整闭合拦截；
   - 非标四段式资产 ID 拦截。
6. 存储适配器 (drama_storage_adapter) 零破坏落库与持久化还原：
   - persist_stage7 与 load_master_state_from_db 准确持久化与水合 mode_b_manifest_check 与全量扩展字段。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaMasterState,
    IndustrialDramaState,
    ModeBManifestCheckDict,
    StoryboardShot,
)
from app.tools.shot_duration_calculator import (
    ShotDurationCalculator,
    calculate_shot_duration,
    check_episode_duration_tolerance,
    clean_dialogue_text,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_episode_visual_package,
    load_master_state_from_db,
    persist_episode_visual_package,
    persist_stage7,
)
from app.workflows.nodes.stage7_storyboard_srt import (
    _stage7_fallback,
    clean_video_prompt,
    compile_engine_video_prompt,
    compile_mode_b_manifest_check,
    stage7_storyboard_srt_node,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper


# =========================================================================
# 1. 契约模型与字段校验测试
# =========================================================================

def test_storyboard_shot_schema_and_alias_normalization():
    """测试 StoryboardShot 契约校验、字段别名与音频同步。"""
    raw_data = {
        "shot_id": 1,
        "timecode": "00:00:00,000 --> 00:00:03,000",
        "duration_seconds": 3.0,
        "shot_type": "MCU 中近景",
        "camera_movement": "慢速推镜头",
        "mode": "multi_image_reference",
        "target_engine": "wan3.0",
        "rationale": "起幅动作 1.0s + 台词 1.6s + 闭嘴缓冲 0.4s = 3.0s",
        "audio": {
            "dialogue": "陆沉：事情不是你想的那样！",
            "foley": "[Foley+3dB: 雨夜狂风与车门猛烈关闭声]",
            "music": "LEITMOTIF_01_SUSPENSE 持续低频铺底",
            "contextual_tts_prompt": "[陆沉_VOICE, 语调急促沙哑, 胸腔紧绷微喘]",
            "speech_inpoint_sec": 0.3,
            "is_dialogue_complete_in_shot": True,
        },
        "multi_image_config": {
            "reference_assets": ["ENV_WAREHOUSE_T1_WIDE", "CHAR_LUCHEN_T1_BASE_PORTRAIT"],
            "video_prompt": "在图1仓库中，图2站在雨中神色凝重开口说道（音频1）。无肢体畸变、无五官崩坏。",
            "audit": "PASS_9",
        },
    }

    shot = StoryboardShot.model_validate(raw_data)
    assert shot.duration_sec == 3.0
    assert shot.framing == "MCU 中近景"
    assert shot.camera_motion == "慢速推镜头"
    assert shot.generation_mode == "multi_image_reference"
    assert shot.target_engine == "wan3.0"
    assert shot.speech_inpoint_sec == 0.3
    assert shot.contextual_tts_prompt == "[陆沉_VOICE, 语调急促沙哑, 胸腔紧绷微喘]"
    assert shot.is_dialogue_complete_in_shot is True
    assert shot.audio.get("speech_inpoint_sec") == 0.3
    assert shot.audio.get("contextual_tts_prompt") == "[陆沉_VOICE, 语调急促沙哑, 胸腔紧绷微喘]"


def test_master_state_mode_b_manifest_check_property():
    """测试 IndustrialDramaMasterState 的 episode_mode_b_manifest_checks 与 property。"""
    state = IndustrialDramaMasterState(
        drama_id=888,
        episode_mode_b_manifest_checks={
            1: {
                "episode_num": 1,
                "total_mode_b_shots": 3,
                "max_images_under_limit": True,
                "scene_unique_and_first": True,
                "character_numbered_from_two": True,
                "audio_independent_order": True,
                "spatial_constraint_front": True,
                "temporal_order_forward": True,
                "target_engine_compliant": True,
                "no_forbidden_prompt_words": True,
                "all_pass_9_signed": True,
                "verdict": "PASS",
                "issues": [],
            }
        }
    )
    assert 1 in state.episode_mode_b_manifest_checks
    assert state.mode_b_manifest_checks[1]["verdict"] == "PASS"


# =========================================================================
# 2. 算子 2：确定性时长测算与自适应拆镜
# =========================================================================

def test_shot_duration_calculator_formula_and_quantization():
    """测试算子 2：时长测算公式与 {2.0, 3.0, 4.0, 5.0, 6.0, 7.0} 整秒量化。"""
    # 短台词：6个字，无动作
    res1 = calculate_shot_duration(dialogue_text="你必须离开。", action_desc="", speed_chars_per_sec=4.0)
    assert res1.is_split is False
    assert res1.single_plan.duration_sec in {2.0, 3.0, 4.0, 5.0, 6.0, 7.0}

    # 中长台词：14个字，普通道具接触，无大动作
    res2 = calculate_shot_duration(
        dialogue_text="你以为凭这个绝密密码，就能逃脱？",
        action_complexity="none",
        prop_interaction="touch",
        speed_chars_per_sec=4.0,
    )
    assert res2.is_split is False
    assert 4.0 <= res2.single_plan.duration_sec <= 6.0

    # 超长复合镜头：破坏性强动作 + 28字长对白 -> 触发 >6.5s 自适应拆镜
    res3 = calculate_shot_duration(
        dialogue_text="当年你亲手在刹车线上动手脚害死我全家的时候，难道就没想过今天会有报应吗！",
        action_complexity="heavy",
        prop_interaction="complex_deformation",
    )
    assert res3.is_split is True
    assert len(res3.plans) == 2

    # Shot A: 动作前置铺垫镜 (无对白)
    shot_a = res3.plans[0]
    assert shot_a.has_dialogue is False
    assert shot_a.duration_sec in {2.0, 3.0}

    # Shot B: 对白特写镜
    shot_b = res3.plans[1]
    assert shot_b.has_dialogue is True
    assert shot_b.speech_inpoint_sec == 0.3
    assert shot_b.duration_sec in {4.0, 5.0, 6.0, 7.0}


def test_episode_duration_tolerance_check():
    """测试整集累计总时长 ±6.0s 容差检查。"""
    ok, actual, diff = check_episode_duration_tolerance(actual_total_sec=124.0, planned_total_sec=120.0, tolerance_sec=6.0)
    assert ok is True
    assert actual == 124.0
    assert diff == 4.0

    ok, actual, diff = check_episode_duration_tolerance(actual_total_sec=128.0, planned_total_sec=120.0, tolerance_sec=6.0)
    assert ok is False
    assert actual == 128.0
    assert diff == 8.0


# =========================================================================
# 3. 算子 3 与算子 5：多引擎编译与禁忌词清障
# =========================================================================

def test_prompt_cleaning_and_forbidden_words_removal():
    """测试提示词清洗：剔除空洞词与口型/生理动作污染词。"""
    dirty_prompt = "电影级 4k 8k photorealistic 超真实 masterpiece，主角自然眨眼，呼吸起伏，嘴唇开合，jaw_open_scale 0.7，目光坚毅。"
    cleaned = clean_video_prompt(dirty_prompt)
    assert "4k" not in cleaned.lower()
    assert "8k" not in cleaned.lower()
    assert "photorealistic" not in cleaned.lower()
    assert "超真实" not in cleaned
    assert "masterpiece" not in cleaned.lower()
    assert "自然眨眼" not in cleaned
    assert "呼吸起伏" not in cleaned
    assert "嘴唇开合" not in cleaned
    assert "jaw_open_scale" not in cleaned
    assert "目光坚毅" in cleaned


def test_compile_engine_video_prompt_branches():
    """测试 Wan 3.0 / Seedance 2.5 / MiniMax H3 目标底模提示词分支生成。"""
    wan_prompt = compile_engine_video_prompt(
        target_engine="wan3.0",
        scene_symbol="图1",
        subject_symbol="图2",
        counterpart_symbol="图3",
        action_desc="冷峻逼视",
        dialogue_audio_symbol="音频1",
    )
    assert "在 图1 环境中" in wan_prompt
    assert "图2" in wan_prompt
    assert "音频1" in wan_prompt
    assert "电影级物理质感" in wan_prompt

    seedance_prompt = compile_engine_video_prompt(
        target_engine="seedance2.5",
        scene_symbol="图1",
        subject_symbol="图2",
        counterpart_symbol="图3",
        action_desc="冷峻逼视",
        dialogue_audio_symbol="音频1",
    )
    assert "[Subject] 图2 与 图3 对峙" in seedance_prompt
    assert "[Environment]" in seedance_prompt
    assert "[Action]" in seedance_prompt
    assert "[Camera]" in seedance_prompt

    minimax_prompt = compile_engine_video_prompt(
        target_engine="minimax_h3",
        scene_symbol="图1",
        subject_symbol="图2",
        counterpart_symbol="图3",
        action_desc="冷峻逼视",
        dialogue_audio_symbol="音频1",
    )
    assert "在 图1 空间中，图2" in minimax_prompt
    assert "情绪连贯克制" in minimax_prompt


# =========================================================================
# 4. Stage 7 节点与保底工厂测试
# =========================================================================

def test_stage7_fallback_factory_compliance():
    """测试 Stage 7 保底工厂生成镜头、SRT 以及自检报告的完整合规性。"""
    chars = [
        {"name": "林萧", "character_token": "LINXIAO"},
        {"name": "楚霸天", "character_token": "CHUBATIAN"},
    ]
    envs = [{"location_name": "顶楼天台", "scene_token": "ROOFTOP"}]
    props = [{"name": "遗嘱原件", "prop_token": "WILL"}]

    fb = _stage7_fallback(
        episode_num=1,
        script_title="生死对决",
        characters=chars,
        environments=envs,
        props=props,
        target_engine="wan3.0",
        planned_duration_sec=120.0,
    )

    assert fb["episode_num"] == 1
    shots = fb["shots"]
    assert len(shots) >= 3

    for s in shots:
        # 必须为整数秒且在 {2, 3, 4, 5, 6, 7}
        assert s["duration_sec"] in {2.0, 3.0, 4.0, 5.0, 6.0, 7.0}
        # 模式合规
        assert s["generation_mode"] in ["first_last_frame", "multi_image_reference"]
        # 台词闭合
        audio = s.get("audio") or {}
        if audio.get("dialogue"):
            assert audio.get("is_dialogue_complete_in_shot") is True
            assert audio.get("speech_inpoint_sec") is not None
            assert "[Foley+3dB:" in audio.get("foley", "")

    # 自检清单报告
    mode_b_check = fb.get("mode_b_manifest_check")
    assert mode_b_check is not None
    assert mode_b_check["verdict"] == "PASS"
    assert mode_b_check["max_images_under_limit"] is True
    assert mode_b_check["all_pass_9_signed"] is True

    # SRT 字幕
    srt = fb["srt_content"]
    assert "00:00:00,000 --> 00:00:03,000" in srt
    assert "林萧" in srt or "楚霸天" in srt


def test_stage7_storyboard_srt_node_execution():
    """测试 stage7_storyboard_srt_node 状态增量返回与自适应拆镜执行。"""
    state = IndustrialDramaMasterState(
        drama_id=999,
        current_visual_episode=1,
        target_video_engine="seedance2.5",
        duration_sec_per_ep=120.0,
        completed_screenplays={
            1: {
                "episode_num": 1,
                "title": "破晓之时",
                "hook_3s": "暴雨夜废弃铁厂",
                "body_markdown": "台词对峙...",
                "ending_cliffhanger": "枪声撕裂黑夜",
            }
        },
        characters_engine={
            "characters": [
                {"name": "主角方野", "character_token": "FANGYE"},
                {"name": "反派龙爷", "character_token": "LONGYE"},
            ]
        },
        environments_and_props={
            "environments": [{"location_name": "废弃钢铁厂", "scene_token": "STEELMILL"}],
            "props": [{"name": "加密U盘", "prop_token": "UDISK"}],
        },
    )

    res = stage7_storyboard_srt_node(state)
    assert res["current_stage"] == 7
    assert 1 in res["episode_storyboards"]
    assert 1 in res["episode_srt_exports"]
    assert 1 in res["episode_mode_b_manifest_checks"]

    shots = res["episode_storyboards"][1]
    assert len(shots) >= 3
    for s in shots:
        assert isinstance(s, StoryboardShot)
        assert s.duration_sec in {2.0, 3.0, 4.0, 5.0, 6.0, 7.0}
        # 验证口型隔离
        if s.video_prompt:
            assert "jaw_open_scale" not in s.video_prompt

    check_report = res["episode_mode_b_manifest_checks"][1]
    assert check_report["verdict"] == "PASS"


# =========================================================================
# 5. Checkpoint 7 哨卡红蓝对抗审查测试
# =========================================================================

def test_checkpoint7_auditor_pass_approved():
    """测试审查哨卡 7：合规分镜判定为 GREEN_APPROVED。"""
    valid_shots = [
        {
            "shot_id": 1,
            "duration_sec": 3.0,
            "generation_mode": "first_last_frame",
            "first_last_config": {
                "first_frame_asset_id": "CHAR_FANGYE_T1_BASE_PORTRAIT",
                "last_frame_asset_id": "PROP_UDISK_T1_STATIC",
            },
        },
        {
            "shot_id": 2,
            "duration_sec": 4.0,
            "generation_mode": "multi_image_reference",
            "multi_image_config": {
                "reference_assets": [
                    "ENV_STEELMILL_T1_WIDE",
                    "CHAR_FANGYE_T1_BASE_PORTRAIT",
                    "CHAR_LONGYE_T1_BASE_PORTRAIT",
                ],
                "video_prompt": "在图1钢铁厂中，图2冷视着图3开口（音频1）。无肢体畸变、无五官崩坏。",
                "audit": "PASS_9",
            },
            "audio": {
                "dialogue": "方野：证据都在这里，你跑不了了。",
                "is_dialogue_complete_in_shot": True,
            },
        },
    ]

    report = RedBlueAuditor.audit_stage7({"shots": valid_shots})
    assert report.verdict == AuditVerdict.GREEN_APPROVED
    assert len(report.blocking_issues) == 0


def test_checkpoint7_auditor_blocking_non_integer_duration():
    """测试审查哨卡 7：非合法整数秒（如 3.5s）精准蓝军阻断。"""
    invalid_shots = [
        {
            "shot_id": 1,
            "duration_sec": 3.5,  # 违规：非整数秒
            "generation_mode": "first_last_frame",
            "first_last_config": {
                "first_frame_asset_id": "CHAR_FANGYE_T1_BASE_PORTRAIT",
                "last_frame_asset_id": "PROP_UDISK_T1_STATIC",
            },
        }
    ]

    report = RedBlueAuditor.audit_stage7({"shots": invalid_shots})
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("非合法整数秒" in issue for issue in report.blocking_issues)


def test_checkpoint7_auditor_blocking_mode_b_exceeds_max_images():
    """测试审查哨卡 7：模式 B 参考图超过 4 张精准阻断。"""
    invalid_shots = [
        {
            "shot_id": 1,
            "duration_sec": 4.0,
            "generation_mode": "multi_image_reference",
            "multi_image_config": {
                "reference_assets": [
                    "ENV_STEELMILL_T1_WIDE",
                    "CHAR_A_T1_BASE_PORTRAIT",
                    "CHAR_B_T1_BASE_PORTRAIT",
                    "PROP_C_T1_STATIC",
                    "PROP_D_T1_STATIC",  # 5张，违规
                ],
                "video_prompt": "在图1中对峙。无肢体畸变。",
                "audit": "PASS_9",
            },
        }
    ]

    report = RedBlueAuditor.audit_stage7({"shots": invalid_shots})
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("超过 4 张上限" in issue for issue in report.blocking_issues)


def test_checkpoint7_auditor_blocking_missing_pass_9():
    """测试审查哨卡 7：模式 B 缺失 PASS_9 自检签名精准阻断。"""
    invalid_shots = [
        {
            "shot_id": 1,
            "duration_sec": 4.0,
            "generation_mode": "multi_image_reference",
            "multi_image_config": {
                "reference_assets": ["ENV_STEELMILL_T1_WIDE", "CHAR_A_T1_BASE_PORTRAIT"],
                "video_prompt": "在图1中对峙。无肢体畸变。",
                "audit": "FAIL_SIGN",  # 违规
            },
        }
    ]

    report = RedBlueAuditor.audit_stage7({"shots": invalid_shots})
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("缺失 PASS_9" in issue for issue in report.blocking_issues)


def test_checkpoint7_auditor_blocking_forbidden_prompt_terms():
    """测试审查哨卡 7：模式 B 提示词包含禁忌词/生理口型词精准红军阻断。"""
    invalid_shots = [
        {
            "shot_id": 1,
            "duration_sec": 4.0,
            "generation_mode": "multi_image_reference",
            "multi_image_config": {
                "reference_assets": ["ENV_STEELMILL_T1_WIDE", "CHAR_A_T1_BASE_PORTRAIT"],
                "video_prompt": "电影级 photorealistic 8k 超真实，主角下颌开度 jaw_open_scale 0.8，自然眨眼。",
                "audit": "PASS_9",
            },
        }
    ]

    report = RedBlueAuditor.audit_stage7({"shots": invalid_shots})
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("禁忌词" in issue for issue in report.blocking_issues)


def test_checkpoint7_auditor_blocking_dialogue_not_complete():
    """测试审查哨卡 7：台词未在单镜头内完整闭合精准阻断。"""
    invalid_shots = [
        {
            "shot_id": 1,
            "duration_sec": 4.0,
            "generation_mode": "multi_image_reference",
            "multi_image_config": {
                "reference_assets": ["ENV_STEELMILL_T1_WIDE", "CHAR_A_T1_BASE_PORTRAIT"],
                "video_prompt": "在图1中对峙。无肢体畸变。",
                "audit": "PASS_9",
            },
            "audio": {
                "dialogue": "这是一句未说完的半截台词……",
                "is_dialogue_complete_in_shot": False,  # 违规
            },
        }
    ]

    report = RedBlueAuditor.audit_stage7({"shots": invalid_shots})
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("未在镜头内完整闭合" in issue for issue in report.blocking_issues)


# =========================================================================
# 6. 持久化与水合测试
# =========================================================================

def test_stage7_persistence_and_rehydration_mock_db():
    """测试 Stage 7 数据库持久化落库与反向水合重构。"""
    fake_db = MagicMock()
    fake_drama = {
        "id": 777,
        "title": "测试短剧",
        "theme": "都市悬疑",
        "target_episodes": 1,
        "duration_per_episode": 120,
        "status": "running",
        "lock_status": 1,
        "current_stage": 7,
        "metadata": "{}",
        "prompt_overrides": "{}",
    }
    # 模拟 episodes 查询返回
    fake_ep = {
        "id": 101,
        "episode_number": 1,
        "ast_blocks": json.dumps({"existing_field": "ok"}),
    }
    # 模拟 storyboards 查询返回
    fake_sb_row = {
        "id": 201,
        "episode_id": 101,
        "storyboard_number": 1,
        "duration": 4.0,
        "shot_type": "CU 特写",
        "movement": "急速推移",
        "creation_mode": "multi_image_reference",
        "image_prompt": "图2特写",
        "video_prompt": "在图1中微距展示",
        "dialogue": "站住别动！",
        "narration": "",
        "action": "掏出物证",
        "atmosphere": "[Foley+3dB: 雨夜风声]",
        "result": json.dumps({
            "target_engine": "seedance2.5",
            "rationale": "特写动作 1.0s + 对白 2.6s + 闭嘴缓冲 0.4s",
            "speech_inpoint_sec": 0.3,
            "contextual_tts_prompt": "[怒斥/胸腔共鸣]",
            "is_dialogue_complete_in_shot": True,
            "multi_image_config": {
                "reference_assets": ["ENV_ROOFTOP_T1_WIDE", "CHAR_HERO_T1_BASE_PORTRAIT"],
                "audit": "PASS_9",
            },
        }),
    }

    executed_sqls = []

    def mock_execute(statement, params=None):
        sql_str = str(statement)
        executed_sqls.append((sql_str, params))
        if "UPDATE episodes SET ast_blocks" in sql_str and params:
            fake_ep["ast_blocks"] = params.get("ast_blocks")
        m = MagicMock()
        return m

    fake_db.execute.side_effect = mock_execute

    state = IndustrialDramaMasterState(
        drama_id=777,
        current_visual_episode=1,
        storyboard_executions={
            1: [
                StoryboardShot(
                    shot_id=1,
                    timecode="00:00:00,000 --> 00:00:04,000",
                    duration_sec=4.0,
                    framing="CU 特写",
                    camera_motion="急速推移",
                    generation_mode="multi_image_reference",
                    target_engine="seedance2.5",
                    rationale="特写动作 1.0s + 对白 2.6s + 闭嘴缓冲 0.4s",
                    speech_inpoint_sec=0.3,
                    contextual_tts_prompt="[怒斥/胸腔共鸣]",
                    is_dialogue_complete_in_shot=True,
                    audio={"dialogue": "站住别动！", "foley": "[Foley+3dB: 雨夜风声]"},
                    multi_image_config={
                        "reference_assets": ["ENV_ROOFTOP_T1_WIDE", "CHAR_HERO_T1_BASE_PORTRAIT"],
                        "audit": "PASS_9",
                    },
                )
            ]
        },
        srt_exports={1: "1\n00:00:00,300 --> 00:00:03,800\n站住别动！\n"},
        episode_mode_b_manifest_checks={
            1: {
                "episode_num": 1,
                "total_mode_b_shots": 1,
                "verdict": "PASS",
                "all_pass_9_signed": True,
            }
        },
    )

    with pytest.MonkeyPatch.context() as mp:
        def fake_fetch_one(db, query, params=None):
            if "dramas" in query:
                return fake_drama
            if "episodes" in query:
                return fake_ep
            return None

        def fake_fetch_all(db, query, params=None):
            if "storyboards" in query:
                return [fake_sb_row]
            if "episodes" in query:
                return [fake_ep]
            return []

        mp.setattr("app.workflows.adapters.drama_storage_adapter.fetch_one", fake_fetch_one)
        mp.setattr("app.workflows.adapters.drama_storage_adapter.fetch_all", fake_fetch_all)
        mp.setattr("app.workflows.adapters.drama_storage_adapter.get_short_memories", lambda drama_id: {})

        # 1. 执行落库
        persist_stage7(fake_db, drama_id=777, state=state, episode_num=1)
        # 验证 UPDATE episodes 写入了 ast_blocks (含 srt_export 与 mode_b_manifest_check)
        update_ep = [p for sql, p in executed_sqls if "UPDATE episodes SET ast_blocks" in sql]
        assert len(update_ep) >= 1
        written_ast = json.loads(update_ep[0]["ast_blocks"])
        assert "srt_export" in written_ast
        assert "mode_b_manifest_check" in written_ast
        assert written_ast["mode_b_manifest_check"]["verdict"] == "PASS"

        # 2. 执行状态水合
        hydrated_state = load_master_state_from_db(fake_db, drama_id=777)
        assert 1 in hydrated_state.episode_mode_b_manifest_checks
        assert hydrated_state.episode_mode_b_manifest_checks[1]["verdict"] == "PASS"
        assert 1 in hydrated_state.storyboard_executions
        hydrated_shot = hydrated_state.storyboard_executions[1][0]
        assert hydrated_shot.target_engine == "seedance2.5"
        assert hydrated_shot.duration_sec == 4.0
        assert hydrated_shot.is_dialogue_complete_in_shot is True
        assert hydrated_shot.speech_inpoint_sec == 0.3
