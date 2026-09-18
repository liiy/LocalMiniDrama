"""阶段四专属单元测试套件：第二程视听资产与分镜工程 (Stage 6~8) 及单集微循环路由验证。

测试覆盖：
1. 【Stage 6 资产提纯与真理源库】(stage6_asset_truth_node, stage6_audit_node, route_stage6_audit)
2. 【Stage 7 导演双模式分镜与毫秒级 SRT】(stage7_storyboard_srt_node, stage7_audit_node, route_stage7_audit)
   - 算子 1: 物理锚点咬合 (前序 0 秒快照与剧本上下文)
   - 算子 2: 整秒分镜约束 (2.0s~7.0s 整数秒与台词完整闭环)
   - 算子 3: 模式 A 首尾帧 vs 模式 B 多图参考选型及 PASS_9 签名
   - 算子 4: 微观拟音 +3.0dB 增益
   - 算子 5: 口型动力学下颌开度 (jaw_open_scale) 静默元数据隔离
   - 算子 6: 毫秒级标准 SRT 字幕对齐导出
3. 【Stage 8 全息声学混音工程与 Ducking 调度】(stage8_audio_mastering_node, stage8_audit_node, route_stage8_audit)
   - 四大依据溯源
   - 动态 T_actual 编译全量 BGM Prompt
   - -23 LUFS 广播级响度
   - 45s 断崖静音与精准分贝调度表
4. 【第二程单集滚动微循环独立条件路由】(route_episode_loop, episode_increment_node, pipeline_complete_node)
   - 未完结递增集数
   - 全季完结终端交付
   - 错误兜底终止
"""
import os
os.environ["LMD_FAST_TEST"] = "1"

import pytest
from unittest.mock import patch

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaMasterState,
    IndustrialDramaState,
    RedBlueAuditReport,
)
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node
from app.workflows.nodes.stage8_audio_mastering import stage8_audio_mastering_node
from app.workflows.routers.audit_router import (
    decide_audit_route,
    episode_increment_node,
    pipeline_complete_node,
    route_episode_loop,
    route_stage6_audit,
    route_stage7_audit,
    route_stage8_audit,
    stage6_audit_node,
    stage7_audit_node,
    stage8_audit_node,
)


# =========================================================================
# 辅助 Mock 数据工厂
# =========================================================================

def _make_sample_state(current_ep: int = 1, total_eps: int = 2) -> dict:
    """构造完备的第二程初始状态。"""
    return {
        "drama_id": 1001,
        "selected_title": "暗夜裁决者",
        "logline": "退役刑警潜伏黑帮寻找当年灭门真凶",
        "total_episodes": total_eps,
        "current_visual_episode": current_ep,
        "current_stage": 6,
        "journey": "journey_2_visual_audio",
        "literary_journey_locked": True,
        "aspect_ratio": "9:16",
        "target_duration_sec": 120.0,
        "visual_style": "冷硬工业黑帮题材，压抑克制且具爆发张力",
        "characters_engine": {
            "characters": [
                {
                    "character_id": "CHAR_LUCHEN",
                    "name": "陆沉",
                    "biological_dna": {"bone_structure": "刀削斧凿的坚毅下颌骨与深邃眼眶"},
                    "lived_in_costume": {"worn_texture": "洗得发白的重磅帆布夹克，右肩磨损"},
                    "voice_timbre": {"vocal_cavity": "声带发干低沉，带轻微颗粒砂砾感"},
                },
                {
                    "character_id": "CHAR_HANTAI",
                    "name": "韩泰",
                    "biological_dna": {"bone_structure": "横肉堆叠但眼神阴鸷的三角眼"},
                    "lived_in_costume": {"worn_texture": "昂贵但沾有油渍的暗色条纹西装"},
                    "voice_timbre": {"vocal_cavity": "冷厉鼻音，吐字如刀割"},
                },
            ]
        },
        "environments_and_props": {
            "environments": [
                {
                    "env_id": "ENV_BASEMENT",
                    "name": "废弃化工厂地下室",
                    "texture": "生锈斑驳的水泥立柱与潮湿滴水管道",
                }
            ],
            "props": [
                {
                    "prop_id": "PROP_LIGHTER",
                    "name": "刻字老式纯铜打火机",
                    "texture": "斑驳氧化绿锈与多次摔打凹痕",
                }
            ],
        },
        "completed_screenplays": {
            1: {
                "episode_num": 1,
                "scenes": [
                    {
                        "scene_id": 1,
                        "location": "废弃化工厂地下室",
                        "dialogue": "韩泰：你以为凭一件旧物就能翻盘？",
                    },
                    {
                        "scene_id": 2,
                        "location": "废弃化工厂地下室",
                        "dialogue": "陆沉：当年杀人时，你也是这么说的！",
                    },
                ],
            },
            2: {
                "episode_num": 2,
                "scenes": [
                    {
                        "scene_id": 1,
                        "location": "雨夜码头",
                        "dialogue": "陆沉：一切都结束了。",
                    }
                ],
            },
        },
        "inter_episode_physical_snapshot": {
            "last_scene": "陆沉手握老式打火机凝视黑暗",
            "lighting": "冷色单侧顶光与暗部高对比度",
            "characters_present": ["CHAR_LUCHEN"],
        },
    }


# =========================================================================
# 1. Stage 6 资产提纯与真理源测试
# =========================================================================

def test_stage6_asset_truth_node_execution():
    """验证阶段 6 资产提纯节点执行及产物契约。"""
    state = _make_sample_state(current_ep=1)
    
    res = stage6_asset_truth_node(state)
    assert "episode_resource_manifests" in res
    assert "visual_audio_assets_registry" in res
    assert res["current_stage"] == 6

    manifests = res["episode_resource_manifests"]
    assert 1 in manifests
    manifest = manifests[1]

    # 验证三级角色、两级场景、三级道具分类结构
    assert len(manifest.characters) > 0
    assert len(manifest.environments) > 0
    assert len(manifest.props) > 0

    # 验证全剧真理源库构建
    vault = res["visual_audio_assets_registry"]
    assert "characters" in vault
    assert "environments" in vault
    assert "props" in vault


def test_stage6_audit_node_and_route():
    """验证阶段 6 蓝军合规审查与独立条件路由。"""
    state = _make_sample_state(current_ep=1)
    res6 = stage6_asset_truth_node(state)
    state.update(res6)

    # 1. 运行自审节点
    audit_res = stage6_audit_node(state)
    assert "latest_audit" in audit_res
    report = audit_res["latest_audit"]
    assert report.verdict in (AuditVerdict.GREEN_APPROVED, "GREEN_APPROVED")

    # 2. 验证独立条件路由判定为 proceed
    state.update(audit_res)
    decision = route_stage6_audit(state)
    assert decision == "proceed"


# =========================================================================
# 2. Stage 7 视听分镜与 SRT 算子验证
# =========================================================================

def test_stage7_storyboard_srt_operators():
    """验证阶段 7 视听分镜 6 大算子落地质量。"""
    state = _make_sample_state(current_ep=1)
    res6 = stage6_asset_truth_node(state)
    state.update(res6)

    # 执行阶段 7 分镜与 SRT 节点
    res7 = stage7_storyboard_srt_node(state)
    assert "episode_storyboards" in res7
    assert "episode_srt_exports" in res7
    assert 1 in res7["episode_storyboards"]
    assert 1 in res7["episode_srt_exports"]

    shots = res7["episode_storyboards"][1]
    srt_text = res7["episode_srt_exports"][1]

    # 【算子 1 & 2】整秒约束与时间码闭环
    assert len(shots) > 0
    total_dur = 0.0
    for shot in shots:
        dur = shot.duration_sec
        # 必须为 2.0s~7.0s 的整数秒
        assert dur in (2.0, 3.0, 4.0, 5.0, 6.0, 7.0)
        assert dur == int(dur)
        total_dur += dur

        # 【算子 3】模式选型与 PASS_9 签名
        assert shot.generation_mode in ("first_last_frame", "multi_image_ref", "multi_image_reference")
        if shot.generation_mode in ("multi_image_ref", "multi_image_reference"):
            # 模式 B PASS_9 紧凑签名
            if shot.multi_image_config:
                assert shot.multi_image_config.get("audit") == "PASS_9"
                assert len(shot.multi_image_config.get("reference_assets", [])) <= 4

        # 【算子 4 & 5】口型动力学静默隔离与台词完整闭环
        audio_obj = shot.audio
        dialogue_val = audio_obj.get("dialogue") if isinstance(audio_obj, dict) else getattr(audio_obj, "dialogue", "")
        if dialogue_val:
            is_complete = audio_obj.get("is_dialogue_complete_in_shot") if isinstance(audio_obj, dict) else getattr(audio_obj, "is_dialogue_complete_in_shot", False)
            assert is_complete is True
            # 静默口型元数据不泄露至 video_prompt
            if shot.lipsync_dynamics:
                jaw = shot.lipsync_dynamics.jaw_open if hasattr(shot.lipsync_dynamics, "jaw_open") else shot.lipsync_dynamics.get("jaw_open")
                assert 0.0 <= jaw <= 1.0
                prompt_text = ""
                if shot.multi_image_config:
                    prompt_text = shot.multi_image_config.get("video_prompt", "")
                assert "jaw_open" not in prompt_text

    # 【算子 6】毫秒级 SRT 纯文本导出
    assert "-->" in srt_text
    assert "00:00:" in srt_text
    assert "1\n" in srt_text or "1\r\n" in srt_text


def test_stage7_audit_node_and_route():
    """验证阶段 7 自审审查与条件路由。"""
    state = _make_sample_state(current_ep=1)
    res6 = stage6_asset_truth_node(state)
    state.update(res6)
    res7 = stage7_storyboard_srt_node(state)
    state.update(res7)

    audit_res = stage7_audit_node(state)
    assert "latest_audit" in audit_res
    state.update(audit_res)

    decision = route_stage7_audit(state)
    assert decision in ("proceed", "self_heal")


# =========================================================================
# 3. Stage 8 全息声学混音工程与 Ducking 调度测试
# =========================================================================

def test_stage8_audio_mastering_specifications():
    """验证阶段 8 混音工程四大依据溯源、-23 LUFS 与 Ducking 调度表。"""
    state = _make_sample_state(current_ep=1)
    res6 = stage6_asset_truth_node(state)
    state.update(res6)
    res7 = stage7_storyboard_srt_node(state)
    state.update(res7)

    res8 = stage8_audio_mastering_node(state)
    assert "episode_audio_masterings" in res8
    assert 1 in res8["episode_audio_masterings"]

    mastering = res8["episode_audio_masterings"][1]

    # 1. 广播级响度标准
    assert mastering["target_lufs"] == -23.0
    assert mastering.get("broadcast_loudness_standard") == "-23 LUFS"

    # 2. 四大依据溯源
    trace = mastering["acoustic_traceability"]
    assert "stage_4_leitmotif_basis" in trace
    assert "stage_1_worldview_basis" in trace
    assert "stage_7_timecode_basis" in trace
    assert "stage_5_dramatic_cues" in trace

    # 3. 全量 BGM Prompt
    bgm_gen = mastering["bgm_generation"]
    assert "full_master_prompt" in bgm_gen
    assert len(bgm_gen["full_master_prompt"]) > 20

    # 4. Ducking 调度表与 45s 断崖静音 (-999.0dB)
    sched = mastering["mastering_schedule"]
    assert len(sched) > 0
    has_cliffhanger_silence = any(item.get("target_bgm_volume_db") == -999.0 for item in sched)
    assert has_cliffhanger_silence is True

    # 5. NLE 多轨指南
    guidelines = mastering["nle_mixing_guidelines"]
    assert "track_a1_dialogue" in guidelines
    assert "track_a2_foley" in guidelines
    assert "track_a3_bgm" in guidelines


def test_stage8_audit_node_and_route():
    """验证阶段 8 自审审查与条件路由。"""
    state = _make_sample_state(current_ep=1)
    res6 = stage6_asset_truth_node(state)
    state.update(res6)
    res7 = stage7_storyboard_srt_node(state)
    state.update(res7)
    res8 = stage8_audio_mastering_node(state)
    state.update(res8)

    audit_res = stage8_audit_node(state)
    assert "latest_audit" in audit_res
    state.update(audit_res)

    decision = route_stage8_audit(state)
    assert decision in ("proceed", "self_heal")


# =========================================================================
# 4. 第二程单集微循环独立条件路由全分支穷举测试
# =========================================================================

def test_route_episode_loop_exhaustive_branches():
    """穷举测试第二程单集微循环条件路由函数的所有分支。"""
    # 分支 1: current_visual_episode < total_episodes -> next_episode
    state_ep1 = {"current_visual_episode": 1, "total_episodes": 3}
    assert route_episode_loop(state_ep1) == "next_episode"

    # 分支 2: current_visual_episode >= total_episodes -> complete_all
    state_ep3 = {"current_visual_episode": 3, "total_episodes": 3}
    assert route_episode_loop(state_ep3) == "complete_all"

    state_ep4 = {"current_visual_episode": 4, "total_episodes": 3}
    assert route_episode_loop(state_ep4) == "complete_all"

    # 分支 3: 兜底非法状态 -> error_terminate
    assert route_episode_loop({"current_visual_episode": "invalid", "total_episodes": 3}) == "error_terminate"
    assert route_episode_loop({"current_visual_episode": 1, "total_episodes": -1}) == "error_terminate"


def test_episode_increment_and_complete_nodes():
    """测试游标递增辅助节点与完结节点的功能。"""
    # 游标递增节点
    state = {"current_visual_episode": 1}
    inc_update = episode_increment_node(state)
    assert inc_update["current_visual_episode"] == 2
    assert inc_update["current_stage"] == 6

    # 完结节点
    comp_update = pipeline_complete_node(state)
    assert comp_update["journey"] == "completed"
    assert comp_update["current_stage"] == 8


def test_decide_audit_route_failover_and_escalation():
    """测试审计路由在红牌阻塞情况下的就地自愈与升级人工穷举。"""
    # 1. 绿灯放行
    rep_green = RedBlueAuditReport(stage=6, verdict=AuditVerdict.GREEN_APPROVED)
    assert decide_audit_route(verdict="GREEN_APPROVED") == "proceed"

    # 2. 黄灯放行
    assert decide_audit_route(verdict="YELLOW_WARNING") == "proceed"

    # 3. 红牌阻塞但在重试上限内 -> self_heal
    assert decide_audit_route(verdict="RED_BLOCKING", retry_count=0, max_retries=2) == "self_heal"
    assert decide_audit_route(verdict="RED_BLOCKING", retry_count=1, max_retries=2) == "self_heal"

    # 4. 红牌阻塞且达到重试上限 -> escalate_human
    assert decide_audit_route(verdict="RED_BLOCKING", retry_count=2, max_retries=2) == "escalate_human"

    # 5. 未知非法判定 -> error_terminate
    assert decide_audit_route(verdict="UNKNOWN_FAIL") == "error_terminate"
