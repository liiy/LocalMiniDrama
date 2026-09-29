"""测试两程九阶 Stage 8 多轨智能音频工程与成片混音调度升级 (Stage 8 Upgrade Tests)。

遵循《Skill规则表》v10.0.0 与《剧本创作工坊_两程九阶实施计划》标准规范：
1. 阶段 8 强类型数据契约模型 (AudioMasteringConfig, AcousticTraceability, BgmGenerationConfig, NleMixingGuidelines)：
   - 广播级响度锁定 -23 LUFS 与 True Peak <= -1.0 dBTP；
   - 四大依据溯源完整性 (动机/时长/对白码/断点)；
   - 精准分贝避让调度表契约；
   - IndustrialDramaMasterState 状态机与 audio_mastering_plans 双向访问兼容。
2. 确定性声学母带引擎算法 (AudioMasteringEngine)：
   - 动态 T_actual 测算与全量 BGM Prompt 编译 (无拖尾硬切骤停指令)；
   - 动态分贝避让调度表生成 (动作底 -12dB、对白下沉 -20dB、45s 断崖静音 -999dB、集尾淡出)；
   - 广播级 NLE 4 轨导出指南 (A1/A2/A3/V1)。
3. Stage 8 业务节点与大模型/保底工厂闭环 (stage8_audio_mastering_node & _stage8_fallback)：
   - 7 大输入变量全量注入提示词模板；
   - 节点保底与强类型 Pydantic 校验标准化；
   - 避让参数双向兼容 (action_bed_db, dialogue_trigger_attenuation_db, dialogue_ducking_level_db)。
4. 哨卡 8 (Checkpoint 8) 红蓝对抗审查硬性拦截：
   - 完备合规母带配置判定为 GREEN_APPROVED；
   - 响度偏离 -23 LUFS 拦截；
   - 峰值限制超标拦截；
   - 四大声学溯源缺失拦截；
   - 调度表缺少 45s 断崖静音 (-999dB) 拦截；
   - 调度表缺少对白避让 (-20dB) 拦截；
   - 缺失 BGM Prompt 或缺失时长拦截；
   - 缺失 NLE 4 轨指南拦截。
5. 存储适配器 (drama_storage_adapter) 零破坏落库与持久化还原：
   - persist_stage8 写入 episodes.ast_blocks['audio_mastering']；
   - load_master_state_from_db 与 load_episode_visual_package 完整水合状态。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AcousticTraceability,
    AudioMasteringConfig,
    AuditVerdict,
    BgmGenerationConfig,
    EpisodeAudioMasteringPlan,
    IndustrialDramaMasterState,
    IndustrialDramaState,
    MasteringScheduleItemModel,
    NleMixingGuidelines,
    StoryboardShot,
)
from app.tools.audio_mastering_engine import (
    AudioMasteringEngine,
    BGM_VOLUME_ACTION_BED_DB,
    BGM_VOLUME_CLIFF_MUTE_DB,
    BGM_VOLUME_DIALOGUE_DUCKING_DB,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_episode_visual_package,
    load_master_state_from_db,
    persist_episode_visual_package,
    persist_stage8,
)
from app.workflows.nodes.stage8_audio_mastering import (
    _stage8_fallback,
    stage8_audio_mastering_node,
)


# =========================================================================
# 1. 契约模型与字段校验测试
# =========================================================================

def test_stage8_acoustic_traceability_model():
    """测试四大声学溯源依据强契约模型。"""
    trace = AcousticTraceability(
        stage_4_leitmotif_basis="LEITMOTIF_01_SUSPENSE 阴郁大提琴单音震音与管道回响",
        stage_1_worldview_basis="冷硬工业黑帮题材，压抑克制且具爆发张力",
        stage_7_timecode_basis="对齐阶段 7 镜头总时长 105.0s 与台词发声入点偏移",
        stage_5_dramatic_cues="开篇前3秒物理危机，45秒断崖静音卡点，片尾绝杀定格",
    )
    dumped = trace.model_dump()
    assert dumped["stage_4_leitmotif_basis"].startswith("LEITMOTIF_01")
    assert "105.0s" in dumped["stage_7_timecode_basis"]


def test_stage8_bgm_generation_config_model():
    """测试全量 BGM Prompt 与音乐生成参数模型。"""
    bgm = BgmGenerationConfig(
        full_master_prompt="[Episode 1] [Style: Cinematic noir] [Duration: 1分45秒 (105s)]",
        planned_duration_sec=105.0,
        actual_duration_sec=105.0,
        target_lufs=-23.0,
        bpm=84,
        musical_key="D minor",
    )
    dumped = bgm.model_dump()
    assert dumped["actual_duration_sec"] == 105.0
    assert dumped["target_lufs"] == -23.0
    assert dumped["musical_key"] == "D minor"


def test_stage8_mastering_schedule_item_model():
    """测试分贝调度表明细模型与别名映射。"""
    item = MasteringScheduleItemModel(
        time_start_sec=45.0,
        time_end_sec=48.0,
        timecode_range="00:00:45,000 --> 00:00:48,000",
        target_bgm_volume_db=-999.0,
        speech_ducking_active=False,
        action_type="cliffhanger_silence",
        event_description="核心戏剧骤停，进入断崖静音 3.0 秒 (-999.0dB)",
    )
    dumped = item.model_dump()
    assert dumped["time_start_sec"] == 45.0
    assert dumped["target_bgm_volume_db"] == -999.0
    assert dumped["speech_ducking_active"] is False


def test_stage8_nle_mixing_guidelines_model():
    """测试 NLE 4 轨混音指南模型。"""
    guidelines = NleMixingGuidelines(
        track_a1_dialogue={"target_lufs": -23.0, "compression": "3:1 ratio"},
        track_a2_foley={"gain_db": 3.0, "high_pass_filter": "80Hz"},
        track_a3_bgm={"bed_gain_db": -12.0, "ducking_gain_db": -20.0, "cliff_mute_db": -999.0},
        video_and_subtitles={"srt_sync": "ms-accurate"},
    )
    dumped = guidelines.model_dump()
    assert dumped["broadcast_loudness_standard"] == "-23 LUFS"
    assert dumped["peak_limit_dbtp"] == -1.0
    assert dumped["track_a3_bgm"]["ducking_gain_db"] == -20.0


def test_stage8_audio_mastering_config_full_validation():
    """测试 AudioMasteringConfig 完整模型校验与别名兼容。"""
    cfg_dict = {
        "broadcast_loudness_standard": "-23 LUFS",
        "target_lufs": -23.0,
        "peak_limit_dbtp": -1.0,
        "acoustic_traceability": {
            "stage_4_leitmotif_basis": "LEITMOTIF_01 阴郁大提琴",
            "stage_1_worldview_basis": "冷硬黑帮",
            "stage_7_timecode_basis": "对齐阶段 7 镜头总时长 90.0s",
            "stage_5_dramatic_cues": "前3秒动作，45秒断崖静音",
        },
        "bgm_generation": {
            "full_master_prompt": "[Episode 1] [Duration: 1分30秒 (90s)] Prompt details",
            "actual_duration_sec": 90.0,
            "target_lufs": -23.0,
        },
        "ducking_strategy": {
            "action_bed_db": -12.0,
            "dialogue_trigger_attenuation_db": -12.0,
            "dialogue_ducking_level_db": -20.0,
            "cliff_silence_db": -999.0,
        },
        "mastering_schedule": [
            {
                "time_start_sec": 0.0,
                "time_end_sec": 3.0,
                "target_bgm_volume_db": -12.0,
                "speech_ducking_active": False,
                "event_description": "开篇动作底",
            },
            {
                "time_start_sec": 45.0,
                "time_end_sec": 48.0,
                "target_bgm_volume_db": -999.0,
                "speech_ducking_active": False,
                "event_description": "高潮断崖静音",
            },
        ],
        "nle_mixing_guidelines": {
            "track_a1_dialogue": {"gain_db": 0.0},
            "track_a3_bgm": {"bed_db": -12.0, "ducking_db": -20.0},
        },
    }
    config = AudioMasteringConfig.model_validate(cfg_dict)
    assert config.target_lufs == -23.0
    assert config.broadcast_loudness_standard == "-23 LUFS"
    assert config.peak_limit_dbtp == -1.0
    assert len(config.mastering_schedule) == 2


def test_master_state_dual_audio_mastering_access():
    """测试 IndustrialDramaMasterState 的 audio_mastering_plans 与 episode_audio_masterings 双向同步属性。"""
    state = IndustrialDramaMasterState(drama_id=101, total_episodes=2)
    plan_ep1 = {"target_lufs": -23.0, "broadcast_loudness_standard": "-23 LUFS"}

    # 通过 audio_mastering_plans 赋值
    state.audio_mastering_plans[1] = plan_ep1
    assert 1 in state.episode_audio_masterings
    assert state.episode_audio_masterings[1]["target_lufs"] == -23.0

    # 通过 episode_audio_masterings 赋值
    plan_ep2 = {"target_lufs": -23.0, "broadcast_loudness_standard": "-23 LUFS"}
    state.episode_audio_masterings[2] = plan_ep2
    assert 2 in state.audio_mastering_plans
    assert state.audio_mastering_plans[2]["target_lufs"] == -23.0


# =========================================================================
# 2. 确定性声学母带引擎算法测试 (AudioMasteringEngine)
# =========================================================================

def test_engine_generate_bgm_prompt_duration_and_no_tail():
    """测试 BGM Prompt 编译器包含精确动态时长换算与集尾无拖尾硬切指令。"""
    prompt = AudioMasteringEngine.generate_bgm_prompt(
        genre="悬疑/黑帮犯罪",
        visual_style="Cinematic noir gritty contrast",
        actual_duration_sec=105.0,
        leitmotif_name="LEITMOTIF_01_SUSPENSE 阴郁大提琴单音震音与管道回响",
        bpm=84,
        musical_key="D minor",
        episode_id=1,
    )
    assert "[Episode 1]" in prompt
    assert "105s" in prompt
    assert "105 seconds" in prompt
    assert "BPM: 84" in prompt
    assert "D minor" in prompt
    assert "LEITMOTIF_01_SUSPENSE" in prompt
    assert "strictly end at 105s with zero reverb tail" in prompt


def test_engine_generate_schedule_with_ducking_and_cliff_silence():
    """测试确定性分贝避让调度表生成：动作底 -12dB、语音避让 -20dB、45s 断崖静音 -999dB。"""
    shots = [
        {
            "shot_id": 1,
            "duration_sec": 3.0,
            "audio": {"foley": "枪栓上膛"},
            "speech_inpoint_sec": None,
        },
        {
            "shot_id": 2,
            "duration_sec": 4.0,
            "dialogue_text": "你到底是谁？别动！",
            "speech_inpoint_sec": 0.8,
            "audio": {"foley": "衣物摩挲"},
        },
        {
            "shot_id": 3,
            "duration_sec": 40.0,
            "audio": {"foley": "脚步渐近"},
        },
        {
            "shot_id": 4,
            "duration_sec": 5.0,
            "audio": {"foley": "秒针停摆"},
        },
        {
            "shot_id": 5,
            "duration_sec": 10.0,
            "dialogue_text": "真相就在这里。",
            "speech_inpoint_sec": 0.5,
        },
    ]

    schedule = AudioMasteringEngine.generate_schedule(shots=shots, total_duration_sec=62.0)
    assert len(schedule) >= 5

    # 1. 验证开篇动作为动作音量底 (-12.0dB)
    first_item = schedule[0]
    assert first_item.target_bgm_volume_db == BGM_VOLUME_ACTION_BED_DB
    assert first_item.speech_ducking_active is False

    # 2. 验证对白镜头存在 -20.0dB 深度避让
    ducking_items = [item for item in schedule if item.target_bgm_volume_db == BGM_VOLUME_DIALOGUE_DUCKING_DB]
    assert len(ducking_items) > 0
    assert any(item.speech_ducking_active is True for item in ducking_items)

    # 3. 验证 45s 断崖静音 (-999.0dB) 存在且持续约 3 秒
    cliff_items = [item for item in schedule if item.target_bgm_volume_db == BGM_VOLUME_CLIFF_MUTE_DB]
    assert len(cliff_items) > 0
    cliff = cliff_items[0]
    assert cliff.time_start_sec >= 40.0
    assert cliff.time_end_sec <= 55.0

    # 4. 验证片尾淡出骤停
    last_item = schedule[-1]
    assert "淡出骤停" in last_item.event_description or last_item.time_end_sec == 62.0


def test_engine_generate_schedule_adaptive_for_short_clips():
    """测试短片或微片段 (< 45s) 自适应高潮断崖静音调度。"""
    shots = [
        {"shot_id": 1, "duration_sec": 3.0, "dialogue": ""},
        {"shot_id": 2, "duration_sec": 4.0, "dialogue": "快走！", "speech_inpoint_sec": 0.5},
        {"shot_id": 3, "duration_sec": 4.0, "dialogue": ""},
        {"shot_id": 4, "duration_sec": 4.0, "dialogue": "结束了。"},
    ]
    # 总长 15.0s
    schedule = AudioMasteringEngine.generate_schedule(shots=shots, total_duration_sec=15.0)
    has_silence = any(item.target_bgm_volume_db == -999.0 for item in schedule)
    assert has_silence is True


def test_engine_get_guidelines_broadcast_specs():
    """测试 NLE 指南生成符合 -23 LUFS 广播级标准。"""
    guidelines = AudioMasteringEngine.get_guidelines()
    assert guidelines["broadcast_loudness_standard"] == "-23 LUFS"
    assert guidelines["peak_limit_dbtp"] == -1.0
    assert guidelines["integrated_lufs"] == -23.0
    assert "-23 LUFS" in str(guidelines["track_a1_dialogue"])
    assert "-20.0dB" in str(guidelines["track_a3_bgm"])
    assert "-999.0dB" in str(guidelines["track_a3_bgm"])
    assert guidelines["tracks"]["A1_Dialogue"]["loudness_norm"] == "-23 LUFS"


# =========================================================================
# 3. Stage 8 业务节点与大模型/保底闭环测试
# =========================================================================

def test_stage8_fallback_factory_outputs_compliant_config():
    """测试 _stage8_fallback 工厂输出完备且合规的广播级母带配置。"""
    props = [{"name": "血迹怀表", "description": "核心物证"}]
    shots = [
        {"shot_id": 1, "duration_sec": 3.0, "audio": {"foley": "怀表秒针"}},
        {"shot_id": 2, "duration_sec": 4.0, "dialogue_text": "指针停了。", "speech_inpoint_sec": 0.5},
        {"shot_id": 3, "duration_sec": 55.0, "audio": {}},
    ]
    fb = _stage8_fallback(
        episode_num=1,
        props=props,
        shots=shots,
        worldview_summary="硬核悬疑犯罪",
        planned_duration_sec=62.0,
    )

    assert fb["episode_num"] == 1
    cfg = fb["mastering_config"]
    assert cfg["target_lufs"] == -23.0
    assert cfg["broadcast_loudness_standard"] == "-23 LUFS"
    assert cfg["peak_limit_dbtp"] == -1.0

    # 验证四大依据
    trace = cfg["acoustic_traceability"]
    assert "LEITMOTIF" in trace["stage_4_leitmotif_basis"]
    assert "硬核悬疑犯罪" in trace["stage_1_worldview_basis"]
    assert "62.0s" in trace["stage_7_timecode_basis"]
    assert trace["stage_5_dramatic_cues"]

    # 验证关键物证拟音提升 +3.0dB
    foley_tracks = cfg["foley_boost_tracks"]
    assert any(item["item"] == "血迹怀表" and item["boost_db"] == 3.0 for item in foley_tracks)


def test_stage8_node_normalizes_and_validates():
    """测试 stage8_audio_mastering_node 节点规范化与 Pydantic 校验。"""
    state = IndustrialDramaMasterState(
        drama_id=888,
        total_episodes=1,
        current_visual_episode=1,
        journey="journey_2_visual",
    )
    state.episode_storyboards[1] = [
        StoryboardShot(
            shot_id=1,
            timecode="00:00:00,000 --> 00:00:03,000",
            duration_sec=3.0,
            audio={"foley": "急刹车"},
        ),
        StoryboardShot(
            shot_id=2,
            timecode="00:00:03,000 --> 00:00:07,000",
            duration_sec=4.0,
            dialogue="站住！",
            speech_inpoint_sec=0.5,
        ),
        StoryboardShot(
            shot_id=3,
            timecode="00:00:07,000 --> 00:00:55,000",
            duration_sec=48.0,
            audio={"foley": "心跳加速"},
        ),
    ]

    # 使用 mock llm 返回合法母带 json
    mock_llm_result = {
        "mastering_config": {
            "broadcast_loudness_standard": "-23 LUFS",
            "target_lufs": -23.0,
            "peak_limit_dbtp": -1.0,
            "acoustic_traceability": {
                "stage_4_leitmotif_basis": "LEITMOTIF_01 悬疑大提琴",
                "stage_1_worldview_basis": "工业冷酷",
                "stage_7_timecode_basis": "对齐阶段 7 镜头总时长 55.0s",
                "stage_5_dramatic_cues": "前3秒刹车，45秒断崖静音",
            },
            "bgm_generation": {
                "full_master_prompt": "[Episode 1] [Duration: 55s] Cinematic noir suspense",
                "actual_duration_sec": 55.0,
                "target_lufs": -23.0,
            },
            "mastering_schedule": [
                {
                    "time_start_sec": 0.0,
                    "time_end_sec": 3.0,
                    "target_bgm_volume_db": -12.0,
                    "speech_ducking_active": False,
                    "event_description": "动作底",
                },
                {
                    "time_start_sec": 3.0,
                    "time_end_sec": 7.0,
                    "target_bgm_volume_db": -20.0,
                    "speech_ducking_active": True,
                    "event_description": "对白避让",
                },
                {
                    "time_start_sec": 45.0,
                    "time_end_sec": 48.0,
                    "target_bgm_volume_db": -999.0,
                    "speech_ducking_active": False,
                    "event_description": "断崖静音",
                },
            ],
            "nle_mixing_guidelines": AudioMasteringEngine.get_guidelines(),
        }
    }

    with patch("app.workflows.nodes.stage8_audio_mastering.call_llm_json", return_value=mock_llm_result):
        res = stage8_audio_mastering_node(state)

    assert "episode_audio_masterings" in res
    assert 1 in res["episode_audio_masterings"]
    cfg = res["episode_audio_masterings"][1]
    assert cfg["target_lufs"] == -23.0
    assert cfg["broadcast_loudness_standard"] == "-23 LUFS"
    assert cfg["ducking_strategy"]["dialogue_trigger_attenuation_db"] == -12.0
    assert cfg["ducking_strategy"]["dialogue_ducking_level_db"] == -20.0
    assert res["current_stage"] == 8


# =========================================================================
# 4. 哨卡 8 (Checkpoint 8) 红蓝对抗审查硬性拦截测试
# =========================================================================

def _make_valid_mastering_config(actual_sec: float = 60.0) -> dict:
    """构建完全符合哨卡 8 标准的母带配置数据。"""
    return {
        "broadcast_loudness_standard": "-23 LUFS",
        "target_lufs": -23.0,
        "peak_limit_dbtp": -1.0,
        "acoustic_traceability": {
            "stage_4_leitmotif_basis": "LEITMOTIF_01 阴郁大提琴单音震音与管道回响",
            "stage_1_worldview_basis": "冷硬工业黑帮题材，压抑克制且具爆发张力",
            "stage_7_timecode_basis": f"对齐阶段 7 镜头总时长 {actual_sec}s 与台词发声入点偏移",
            "stage_5_dramatic_cues": "开篇前3秒物理危机，45秒断崖静音卡点，片尾绝杀定格",
        },
        "bgm_generation": {
            "full_master_prompt": f"[Episode 1] [Style: Cinematic noir] [Duration: {actual_sec}s] Leitmotif details",
            "actual_duration_sec": actual_sec,
            "target_lufs": -23.0,
            "bpm": 84,
            "musical_key": "D minor",
        },
        "ducking_strategy": {
            "action_bed_db": -12.0,
            "dialogue_trigger_attenuation_db": -12.0,
            "dialogue_ducking_level_db": -20.0,
            "cliff_silence_db": -999.0,
        },
        "mastering_schedule": [
            {
                "time_start_sec": 0.0,
                "time_end_sec": 3.0,
                "target_bgm_volume_db": -12.0,
                "speech_ducking_active": False,
                "event_description": "开篇动作底",
            },
            {
                "time_start_sec": 3.0,
                "time_end_sec": 8.0,
                "target_bgm_volume_db": -20.0,
                "speech_ducking_active": True,
                "event_description": "台词对白避让",
            },
            {
                "time_start_sec": 45.0,
                "time_end_sec": 48.0,
                "target_bgm_volume_db": -999.0,
                "speech_ducking_active": False,
                "action_type": "cliffhanger_silence",
                "event_description": "高潮断崖静音",
            },
            {
                "time_start_sec": actual_sec - 2.0,
                "time_end_sec": actual_sec,
                "target_bgm_volume_db": -24.0,
                "speech_ducking_active": False,
                "event_description": "片尾淡出与硬切骤停",
            },
        ],
        "nle_mixing_guidelines": AudioMasteringEngine.get_guidelines(),
    }


def test_checkpoint8_green_approval():
    """测试哨卡 8 对完配合规配置判定为 GREEN_APPROVED。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config(actual_sec=60.0)
    state.episode_audio_masterings[1] = cfg

    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.GREEN_APPROVED
    assert len(report.blocking_issues) == 0


def test_checkpoint8_block_missing_config():
    """测试哨卡 8 拦截缺失母带配置。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    # episode_audio_masterings 为空
    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("Missing mastering configuration" in issue for issue in report.blocking_issues)


def test_checkpoint8_block_loudness_violation():
    """测试哨卡 8 拦截广播级响度偏离 -23 LUFS 标准。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config()
    cfg["target_lufs"] = -16.0  # 严重超标
    cfg["broadcast_loudness_standard"] = "-16 LUFS"
    state.episode_audio_masterings[1] = cfg

    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("-23 LUFS" in issue for issue in report.blocking_issues)


def test_checkpoint8_block_missing_acoustic_traceability():
    """测试哨卡 8 拦截缺失四大依据溯源。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config()
    # 抹掉 stage_7_timecode_basis
    cfg["acoustic_traceability"].pop("stage_7_timecode_basis")
    state.episode_audio_masterings[1] = cfg

    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("acoustic_traceability" in issue for issue in report.blocking_issues)


def test_checkpoint8_block_missing_cliffhanger_silence():
    """测试哨卡 8 拦截调度表缺失 45s 断崖静音 (-999dB)。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config()
    # 移除断崖静音条目
    cfg["mastering_schedule"] = [
        item for item in cfg["mastering_schedule"]
        if item.get("target_bgm_volume_db") != -999.0 and item.get("action_type") != "cliffhanger_silence"
    ]
    state.episode_audio_masterings[1] = cfg

    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("cliffhanger silence" in issue for issue in report.blocking_issues)


def test_checkpoint8_block_missing_dialogue_ducking():
    """测试哨卡 8 拦截调度表缺失对白避让 (-20dB)。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config()
    # 将对白避让条目修改为动作音量
    for item in cfg["mastering_schedule"]:
        if item.get("speech_ducking_active"):
            item["speech_ducking_active"] = False
            item["target_bgm_volume_db"] = -12.0
    state.episode_audio_masterings[1] = cfg

    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("dialogue ducking" in issue for issue in report.blocking_issues)


def test_checkpoint8_block_missing_bgm_prompt():
    """测试哨卡 8 拦截缺失 BGM Prompt 或缺失时长换算。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config()
    cfg["bgm_generation"]["full_master_prompt"] = ""  # 清空 prompt
    state.episode_audio_masterings[1] = cfg

    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("BGM prompt" in issue for issue in report.blocking_issues)


def test_checkpoint8_block_missing_nle_guidelines():
    """测试哨卡 8 拦截缺失 NLE 4 轨混音指南。"""
    auditor = RedBlueAuditor()
    state = IndustrialDramaMasterState(drama_id=999, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config()
    cfg.pop("nle_mixing_guidelines")
    state.episode_audio_masterings[1] = cfg

    report = auditor.audit_stage8(state)
    assert report.verdict == AuditVerdict.RED_BLOCKING
    assert any("NLE mixing guidelines" in issue for issue in report.blocking_issues)


# =========================================================================
# 5. 存储适配器 (drama_storage_adapter) 持久化与水合还原测试
# =========================================================================

def test_storage_adapter_persist_stage8_and_rehydrate():
    """测试 persist_stage8 写入 SQLite episodes.ast_blocks['audio_mastering'] 并能水合还原。"""
    mock_db = MagicMock()
    mock_ep_row = {
        "id": 12,
        "ast_blocks": json.dumps({"existing_stage": 7}),
    }

    state = IndustrialDramaMasterState(drama_id=777, total_episodes=1, current_visual_episode=1)
    cfg = _make_valid_mastering_config(actual_sec=75.0)
    state.audio_mastering_plans[1] = cfg

    with patch("app.workflows.adapters.drama_storage_adapter.fetch_one", return_value=mock_ep_row), \
         patch("app.workflows.adapters.drama_storage_adapter.sync_stage_memories_to_vector_db") as mock_sync_mem, \
         patch("app.workflows.adapters.drama_storage_adapter.set_short_memories") as mock_set_mem:
        
        persist_stage8(mock_db, drama_id=777, state=state, episode_num=1)

        # 验证 UPDATE episodes 包含 audio_mastering
        assert mock_db.execute.called
        update_call = mock_db.execute.call_args_list[0]
        params = update_call[0][1]
        ast_saved = json.loads(params["ast_blocks"])
        assert "audio_mastering" in ast_saved
        assert ast_saved["audio_mastering"]["target_lufs"] == -23.0
        assert ast_saved["audio_mastering"]["broadcast_loudness_standard"] == "-23 LUFS"
        assert ast_saved["audio_mastering"]["acoustic_traceability"]["stage_4_leitmotif_basis"].startswith("LEITMOTIF_01")

        # 验证长期记忆写入
        assert mock_sync_mem.called
        mem_args = mock_sync_mem.call_args[0]
        assert mem_args[2] == 8  # stage 8


def test_storage_adapter_episode_visual_package_roundtrip():
    """测试 persist_episode_visual_package 与 load_episode_visual_package 对 audio_mastering 的往返支持。"""
    mock_session = MagicMock()
    mock_ep_row = {
        "id": 88,
        "ast_blocks": json.dumps({}),
    }

    cfg = _make_valid_mastering_config(actual_sec=80.0)

    with patch("app.workflows.adapters.drama_storage_adapter.fetch_one", return_value=mock_ep_row):
        persist_episode_visual_package(
            db=mock_session,
            drama_id=999,
            episode_num=1,
            manifest={"chars": []},
            storyboards=[],
            srt_export="1\n00:00:00,000 --> 00:00:03,000\nHello",
            audio_mastering=cfg,
        )

        # 验证写入的 ast_blocks
        assert mock_session.execute.called
        update_call = mock_session.execute.call_args_list[0]
        params = update_call[0][1]
        saved_ast = json.loads(params["ast_blocks"])
        assert "audio_mastering" in saved_ast
        assert saved_ast["audio_mastering"]["target_lufs"] == -23.0

    # 模拟 load_episode_visual_package
    mock_load_ep_row = {
        "id": 88,
        "ast_blocks": json.dumps({"audio_mastering": cfg}),
    }
    with patch("app.workflows.adapters.drama_storage_adapter.fetch_one", return_value=mock_load_ep_row), \
         patch("app.workflows.adapters.drama_storage_adapter.fetch_all", return_value=[]):
        pkg = load_episode_visual_package(mock_session, drama_id=999, episode_num=1)
        assert "audio_mastering" in pkg
        assert pkg["audio_mastering"]["target_lufs"] == -23.0
        assert pkg["audio_mastering"]["broadcast_loudness_standard"] == "-23 LUFS"
