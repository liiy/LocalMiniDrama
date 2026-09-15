"""Unit tests for the Two-Journey Nine-Stage schema extensions from SKILL.md."""
import pytest
from app.schemas.script_graph_state import (
    IndustrialDramaMasterState,
    RedBlueAuditReport,
    AuditVerdict,
    CandidateTitleMatrix,
    DoubleTrackProhibitions,
    AudioBible,
    AudioMotifItem,
    EpisodeResourceManifest,
    StoryboardShot,
)


def test_industrial_master_state_initialization():
    state = IndustrialDramaMasterState(
        drama_id=2026,
        selected_title="夜班汽笛",
        total_episodes=12,
    )
    assert state.drama_id == 2026
    assert state.journey == "journey_1_literary"
    assert state.current_stage == 1
    assert state.total_episodes == 12
    assert state.literary_journey_locked is False
    assert len(state.negative_rules.forbidden_cliches) == 10
    assert len(state.negative_rules.forbidden_cheap_pleasures) == 3


def test_candidate_title_matrix():
    matrix = CandidateTitleMatrix(
        identity_contrast=["《绝密质检员》", "《老厂长与清洁工》"],
        extreme_suspense=["《头七血信》", "《封口名单》"],
        prop_irony=["《带血安全帽》", "《生锈铜钥匙》"],
        dark_psychology=["《双面证人》", "《窒息博弈》"],
    )
    assert len(matrix.identity_contrast) == 2
    assert len(matrix.extreme_suspense) == 2
    assert len(matrix.prop_irony) == 2
    assert len(matrix.dark_psychology) == 2


def test_red_blue_audit_report():
    report = RedBlueAuditReport(
        blue_team_compliance={
            "timecode_sum_exact": True,
            "negative_rules_checked": True,
            "json_schema_valid": True,
        },
        red_team_criticism={
            "dramatic_tension_defect": "无严重缺陷，第45秒微反转张力充沛",
            "ai_distortion_risk": "镜号01通过首尾帧模式完全约束，无穿模形变风险",
        },
        verdict=AuditVerdict.GREEN_APPROVED,
        blocking_issues=[],
        warning_suggestions=["建议加重第2集男主角手部微颤特写"],
    )
    assert report.verdict == AuditVerdict.GREEN_APPROVED
    assert report.blue_team_compliance["timecode_sum_exact"] is True
    assert len(report.warning_suggestions) == 1


def test_storyboard_dual_mode_selection():
    # 模式 A: 首尾帧模式
    shot_a = StoryboardShot(
        shot_id=1,
        timecode="00:00:00,000 --> 00:00:02,500",
        duration_sec=2.5,
        framing="CU 特写",
        generation_mode="first_last_frame",
        selection_rationale="物理形变破坏场景，必须采用首尾帧强约束",
        first_last_config={
            "first_frame_prompt": "A utility knife blade touching red wax seal",
            "last_frame_prompt": "Knife blade slicing through wax seal splintering chips",
            "video_motion_prompt": "Slow continuous push-in knife cutting wax",
        },
    )
    assert shot_a.generation_mode == "first_last_frame"
    assert shot_a.duration_sec == 2.5

    # 模式 B: 多图参考模式
    shot_b = StoryboardShot(
        shot_id=2,
        timecode="00:00:02,500 --> 00:00:05,500",
        duration_sec=3.0,
        framing="MCU 中近景",
        generation_mode="multi_image_reference",
        selection_rationale="对白戏神态交锋，必须采用多图参考防面部抽搐",
        multi_image_config={
            "reference_assets": ["CHAR_LIN_FRONT", "CHAR_LIN_GRIEF"],
            "multi_image_video_prompt": "Static shot, Lin Wan speaks with clamped jaw",
        },
        lipsync_dynamics={
            "jaw_open_scale": 0.45,
            "lip_tension": "High",
        },
    )
    assert shot_b.generation_mode == "multi_image_reference"
    assert shot_b.lipsync_dynamics["jaw_open_scale"] == 0.45
