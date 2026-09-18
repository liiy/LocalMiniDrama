"""实施路线图阶段一：契约与纯函数工具层单元测试 (Test Phase 1 Contracts and Deterministic Tools)。

严格对齐《公共硬性约束》与《SKILL1.md v10.0.0》：
1. 状态契约体系：IndustrialDramaState (TypedDict) 与所有子契约字段、向后兼容性与类型注解
2. Stage 6 逆向特征扫描引擎：角色/视角/微距/伤残/光感/场景标头/破坏动词/母音频抓取
3. Stage 7 整秒倒逼与自适应拆镜算子：复合时长公式、[2.0, 7.0]s 整秒锁定、>6.5s 强制解耦拆镜、时间码转换与 +-6.0s 容差校验
4. Stage 8 智能混音工程与 SRT 纯代码排版：+0.3s 入点偏移、-12dB/-20dB 闪避、-999dB 断崖静音、尾部淡出与 NLE 4 轨母带规范
"""
from __future__ import annotations

import pytest
from typing import get_type_hints

from app.schemas.script_graph_state import (
    IndustrialDramaState,
    IndustrialDramaMasterState,
    LeanDramaScriptState,
    PreviousEpisodePickup,
    GoldenCliffhangerHook,
    EpisodeEndPhysicalDelta,
    StageAuditReport,
    LiteraryScreenplayEpisode,
    CharacterProfileDict,
    BiologicalPortraitDNADict,
    LivedInCostumeSpecsDict,
    AcousticPersonaDict,
    PsychologicalQuadrupleDict,
    DualTrackRelationshipItemDict,
    EmotionalArcTrajectoryDict,
    EnvironmentItemDict,
    PropItemDict,
    EpisodeOutlineItemDict,
    AudioBibleDict,
    ReusedAssetItem,
    NewlyGeneratedAssetItem,
    MasterVoiceCardItem,
    EpisodeResourceManifestDict,
    StoryboardShotDict,
    EpisodeAudioSpecDict,
)
from app.tools import (
    scan_screenplay_features,
    ScreenplayFeatureScanner,
    ScreenplayScanResult,
    calculate_shot_duration,
    check_episode_duration_tolerance,
    format_timecode_ms,
    format_timecode_range,
    ShotDurationCalculator,
    ShotDurationResult,
    generate_srt_content,
    generate_mastering_schedule,
    generate_bgm_master_prompt,
    get_nle_mixing_guidelines,
    AudioMasteringEngine,
)


class TestPhase1DataContracts:
    """【规则编号: RULE-VI-01 ~ RULE-VI-08】数据契约与 TypedDict 规范测试。"""

    def test_industrial_drama_state_annotations(self):
        """验证 IndustrialDramaState 包含核心规范要求的全部状态键名。"""
        hints = get_type_hints(IndustrialDramaState)
        required_keys = [
            "drama_id", "journey", "current_stage",
            "slug", "selected_title", "target_video_engine",
            "duration_sec_per_ep", "target_episodes",
            "forbidden_cliches_10", "forbidden_cheap_tropes_3",
            "characters_engine", "dual_track_relationships", "emotional_arc_trajectories",
            "environments_and_props", "audio_bible", "season_outlines",
            "completed_screenplays", "inter_episode_physical_snapshot",
            "visual_audio_assets_registry", "episode_resource_manifests",
            "episode_storyboards", "episode_srt_exports", "episode_audio_masterings",
            "latest_audit", "stage_retry_counts", "error_message"
        ]
        for key in required_keys:
            assert key in hints, f"IndustrialDramaState 缺失必须字段: {key}"

    def test_industrial_master_state_backward_compatibility(self):
        """验证 IndustrialDramaMasterState 的向后兼容性与状态转换支持。"""
        legacy_state = IndustrialDramaMasterState(
            drama_id=101,
            selected_title="七封信",
            slug="seven_letters",
            target_video_engine="wan3.0",
            target_episodes=12,
            duration_sec_per_ep=120,
        )
        assert legacy_state.drama_id == 101
        assert legacy_state.slug == "seven_letters"
        assert legacy_state.target_video_engine == "wan3.0"
        assert legacy_state.get("selected_title") == "七封信"
        assert legacy_state.get("non_existent_key", "default_val") == "default_val"

        state_dict = legacy_state.to_state_dict()
        assert isinstance(state_dict, dict)
        assert state_dict["slug"] == "seven_letters"
        assert state_dict["target_video_engine"] == "wan3.0"

    def test_sub_contracts_instantiation(self):
        """验证各个子契约 TypedDict 能够正常构建符合规则的字典。"""
        pickup: PreviousEpisodePickup = {
            "inherited_from_episode": 1,
            "pickup_state_description": "苏诚右手紧握带血的信封，站在天台边缘。"
        }
        hook: GoldenCliffhangerHook = {
            "physical_crisis_action": "黑衣人猛然拉扯绳索，脚手架轰然倒塌。",
            "cliffhanger_dialogue": "七年前那场火，根本就不是意外！",
            "acoustic_drop_cue": "低音重击后瞬间全频断崖静音"
        }
        delta: EpisodeEndPhysicalDelta = {
            "timeline_progress": "第1集 02:00",
            "character_pose": "苏诚半跪在地，右臂撕裂流血",
            "held_props_and_injuries": "右手指甲掐出指甲血痕，手持血信",
            "environment_and_weather": "15号烂尾楼天台，暴雨倾盆"
        }
        audit: StageAuditReport = {
            "blue_team": "完成分镜与台词对齐",
            "red_team_critic": "无老套打脸与廉价爽点",
            "verdict": "GREEN_APPROVED",
            "blocking_issues": [],
            "warning_suggestions": []
        }
        screenplay_ep: LiteraryScreenplayEpisode = {
            "episode_id": 1,
            "episode_title": "暗夜来信",
            "planned_duration_sec": 120.0,
            "dramatic_arc_unit": "起-承-转-合",
            "core_dramatic_task": "苏诚收到亡妻遗信并遭遇初次围截",
            "previous_episode_0s_pickup": None,
            "screenplay_text": "【场景：烂尾楼天台 - 夜/暴雨】\n苏诚正面站立，眼神冰冷。",
            "golden_cliffhanger_hook": hook,
            "episode_end_physical_delta": delta,
            "audit_report": audit,
        }
        assert screenplay_ep["episode_id"] == 1
        assert screenplay_ep["golden_cliffhanger_hook"]["cliffhanger_dialogue"] == "七年前那场火，根本就不是意外！"


class TestStage6ScreenplayFeatureScanner:
    """【规则编号: RULE-V-S6-02】阶段 6 逆向特征扫描器纯代码逻辑测试。"""

    def test_operator_a_character_features(self):
        """测试算子 A：识别出场角色、四视角、光感、微距与伤残，生成四段式命名。"""
        screenplay = """
        【场景：15号烂尾楼天台 - 夜/暴雨】
        苏诚迎面站立，强光照脸，手电筒直射他的眼眸。
        他手指紧扣，掐掌心掐出指甲血痕，右臂撕裂流血，眼神充满血丝。
        林夏转头避开目光，侧脸看着地面，嘴角皲裂起皮。
        """
        known_characters = [
            {"character_id": "CHAR_SU_CHENG", "name": "苏诚", "tier": "HERO"},
            {"character_id": "CHAR_LIN_XIA", "name": "林夏", "tier": "ANCHOR"},
        ]
        result = ScreenplayFeatureScanner.scan(
            episode_id=1,
            screenplay_text=screenplay,
            known_characters=known_characters,
            known_environments=[],
            known_props=[],
            existing_assets_registry={},
        )
        assert isinstance(result, ScreenplayScanResult)
        assert len(result.new_assets) > 0

        asset_ids = [a["asset_id"] for a in result.new_assets]
        # 验证苏诚正面、强光照脸、微距手部、伤残流血
        assert any("CHAR_SU_CHENG_HERO_VIEW_FRONT" in aid for aid in asset_ids)
        assert any("CHAR_SU_CHENG_HERO_LIGHT_FLASH" in aid for aid in asset_ids)
        assert any("CHAR_SU_CHENG_HERO_MACRO_HAND" in aid for aid in asset_ids)
        assert any("CHAR_SU_CHENG_HERO_DAMAGE_BLOOD" in aid for aid in asset_ids)
        # 验证林夏侧脸、嘴角微距
        assert any("CHAR_LIN_XIA_ANCHOR_VIEW_PROFILE" in aid for aid in asset_ids)
        assert any("CHAR_LIN_XIA_ANCHOR_MACRO_MOUTH" in aid for aid in asset_ids)

    def test_operator_b_environment_headers(self):
        """测试算子 B：场景标头识别 (2-4个)，时态与景别识别。"""
        screenplay = """
        【场景：15号烂尾楼天台 - 深夜/暴雨】
        全貌俯瞰整个城市废墟。雨水如注。
        【场景：地下废弃车库 - 黎明/阴冷】
        15W节能灯频闪，电表箱发出微弱电流嗡鸣。
        【场景：苏诚破旧出租屋 - 清晨/灰蒙】
        水龙头滴水，桌上放着半盒发霉的泡面。
        """
        result = scan_screenplay_features(
            episode_id=1,
            screenplay_text=screenplay,
            known_characters=[],
            known_environments=[],
            known_props=[],
            existing_assets_registry={},
        )
        env_assets = [a for a in result.new_assets if a["asset_id"].startswith("ENV_")]
        assert len(env_assets) >= 3
        # 验证包含烂尾楼、车库与出租屋场景资产
        env_names = [a["asset_id"] for a in env_assets]
        assert any("LANWEILOU" in name or "TIANTAI" in name for name in env_names)
        assert any("CHEKU" in name for name in env_names)
        assert any("CHUZUWU" in name for name in env_names)

    def test_operator_c_prop_deformation_and_action(self):
        """测试算子 C：命中形变破坏动词库强制生成 ACTION 破坏态，未命中则仅静态态。"""
        screenplay_with_action = """
        【场景：天台 - 夜】
        苏诚颤抖着拿出那封血信，用打火机点燃，随后猛地撕成两半，将纸屑崩碎在雨中！
        他手里握着一把生锈的安全帽。
        """
        known_props = [
            {"prop_id": "PROP_XUEXIN", "name": "血信", "tier": "T1"},
            {"prop_id": "PROP_ANQUANMAO", "name": "安全帽", "tier": "T1"},
        ]
        result = scan_screenplay_features(
            episode_id=1,
            screenplay_text=screenplay_with_action,
            known_characters=[],
            known_environments=[],
            known_props=known_props,
            existing_assets_registry={},
        )
        prop_assets = [a for a in result.new_assets if a["asset_id"].startswith("PROP_")]
        prop_ids = [a["asset_id"] for a in prop_assets]
        # 血信命中了“撕”、“崩碎”，必须生成 ACTION 破坏态
        assert any("PROP_XUEXIN_T1_ACTION" in pid for pid in prop_ids)
        # 安全帽未命中破坏动词，保持静态态
        assert any("PROP_ANQUANMAO_T1" in pid and "ACTION" not in pid for pid in prop_ids)

    def test_operator_d_master_voice_card(self):
        """测试算子 D：角色首发高光台词抓取与母音频卡片生成。"""
        screenplay = """
        【场景：天台 - 夜】
        苏诚：（声音沙哑压抑）“既然你们不给我活路，那大家就一起下地狱！”
        林夏：（冷笑）“你以为你能走出这座大楼吗？”
        """
        known_characters = [
            {"character_id": "CHAR_SU_CHENG", "name": "苏诚", "tier": "HERO"},
            {"character_id": "CHAR_LIN_XIA", "name": "林夏", "tier": "ANCHOR"},
        ]
        result = scan_screenplay_features(
            episode_id=1,
            screenplay_text=screenplay,
            known_characters=known_characters,
            known_environments=[],
            known_props=[],
            existing_assets_registry={},
        )
        assert len(result.master_voice_cards) >= 2
        su_voice = next((v for v in result.master_voice_cards if v["character_id"] == "CHAR_SU_CHENG"), None)
        assert su_voice is not None
        assert "一起下地狱" in su_voice["script_monologue_source"]
        assert "压抑" in su_voice["master_tts_prompt"] or "沙哑" in su_voice["master_tts_prompt"]

    def test_assets_reuse_deduplication(self):
        """测试资产去重与复用逻辑：总库已有的资产自动进入 reused_assets 而非 new_assets。"""
        screenplay = """
        【场景：天台 - 夜】
        苏诚正面站立。
        """
        known_characters = [
            {"character_id": "CHAR_SU_CHENG", "name": "苏诚", "tier": "HERO"},
        ]
        existing_registry = {
            "CHAR_SU_CHENG_HERO_VIEW_FRONT": {
                "asset_id": "CHAR_SU_CHENG_HERO_VIEW_FRONT",
                "status": "APPROVED",
                "generation_method": "text_to_image",
            }
        }
        result = scan_screenplay_features(
            episode_id=2,
            screenplay_text=screenplay,
            known_characters=known_characters,
            known_environments=[],
            known_props=[],
            existing_assets_registry=existing_registry,
        )
        # 该资产必须在 reused_assets 中，且不在 new_assets 中
        reused_ids = [r["asset_id"] for r in result.reused_assets]
        new_ids = [n["asset_id"] for n in result.new_assets]
        assert "CHAR_SU_CHENG_HERO_VIEW_FRONT" in reused_ids
        assert "CHAR_SU_CHENG_HERO_VIEW_FRONT" not in new_ids


class TestStage7ShotDurationCalculator:
    """【规则编号: RULE-V-S7-02】阶段 7 复合时长倒逼与自适应拆镜算子纯代码逻辑测试。"""

    def test_duration_formula_and_integer_lock(self):
        """测试基础复合时长公式与整秒向上锁定 [2.0, 7.0]s。"""
        # 案例 1: 极短动作，无对白，基础约 1.5s -> 锁定为 2.0s
        res_short = ShotDurationCalculator.calculate(
            action_desc="苏诚猛然回头。",
            prop_desc="",
            dialogue_text="",
            is_fast_pace=True,
        )
        assert len(res_short.shots) == 1
        assert res_short.total_duration_sec == 2.0
        assert res_short.shots[0]["duration_sec"] == 2.0

        # 案例 2: 普通对白 18 字，非快节奏 (speed=4.5)
        # T = 1.0(action) + 0.0 + (18/4.5 + 0.3) + 0.4 = 1.0 + 4.3 + 0.4 = 5.7s -> 向上取整锁为 6.0s
        res_normal = ShotDurationCalculator.calculate(
            action_desc="苏诚冷冷地看着眼前的账本。",
            prop_desc="",
            dialogue_text="当年那笔工程款，到底进了谁的个人账户？",
            is_fast_pace=False,
        )
        assert len(res_normal.shots) == 1
        assert res_normal.total_duration_sec == 6.0
        assert res_normal.shots[0]["duration_sec"] == 6.0
        assert res_normal.shots[0]["audio"]["speech_inpoint_sec"] == 0.3

    def test_overlong_shot_automatic_decoupling_split(self):
        """测试时长 > 6.5s 强制解耦拆镜为 Shot A 铺垫动作镜 + Shot B 对白特写镜。"""
        long_dialogue = "你们以为把证据烧了就能当什么都没发生过吗？七年前的火灾真相，所有受害者的血债，今天我一定要让你们十倍奉还！"
        # 该对白达 52 字，计算肯定 > 6.5s
        res_split = calculate_shot_duration(
            action_desc="苏诚在暴雨中一步步向前逼近，手中紧握生锈的铁棍。",
            prop_desc="手中的铁棍划过地面摩擦出火花。",
            dialogue_text=long_dialogue,
            is_fast_pace=False,
        )
        assert res_split.is_split is True
        assert len(res_split.shots) == 2

        shot_a, shot_b = res_split.shots[0], res_split.shots[1]
        # Shot A: 动作铺垫镜 (2.0~3.0s 整秒), 静音/纯动作
        assert shot_a["duration_sec"] in [2.0, 3.0]
        assert shot_a["audio"]["voice_type"] is None
        assert "动作铺垫" in shot_a["rationale"]

        # Shot B: 对白特写镜 (4.0~5.0s 整秒), 0.3s 入点, 对白完整
        assert shot_b["duration_sec"] in [4.0, 5.0, 6.0, 7.0]
        assert shot_b["audio"]["voice_type"] == "dialogue"
        assert shot_b["audio"]["speech_inpoint_sec"] == 0.3
        assert shot_b["audio"]["is_dialogue_complete_in_shot"] is True
        assert "对白特写" in shot_b["rationale"]

    def test_timecode_formatting(self):
        """测试毫秒级时间码转换与格式严格对齐 HH:MM:SS,mmm。"""
        tc_start = format_timecode_ms(0.0)
        tc_mid = format_timecode_ms(83.456)
        assert tc_start == "00:00:00,000"
        assert tc_mid == "00:01:23,456"

        tc_range = format_timecode_range(0.0, 5.0)
        assert tc_range == "00:00:00,000 --> 00:00:05,000"

    def test_episode_duration_tolerance(self):
        """测试全集总时长 +-6.0s 容差校验。"""
        # 目标 120s，实际 124s -> 合格
        passed, actual, diff = check_episode_duration_tolerance(
            shots_durations=[5.0] * 24 + [4.0],  # 124s
            target_duration_sec=120.0,
            tolerance_sec=6.0,
        )
        assert passed is True
        assert actual == 124.0
        assert diff == 4.0

        # 目标 120s，实际 128s -> 超标不合格
        passed, actual, diff = check_episode_duration_tolerance(
            shots_durations=[5.0] * 25 + [3.0],  # 128s
            target_duration_sec=120.0,
            tolerance_sec=6.0,
        )
        assert passed is False
        assert actual == 128.0
        assert diff == 8.0


class TestStage8AudioMasteringEngine:
    """【规则编号: RULE-VI-08】阶段 8 智能混音工程与毫秒级 SRT 纯代码引擎测试。"""

    def test_srt_generation_with_300ms_visual_breathing_offset(self):
        """测试毫秒级 SRT 生成：+300ms 入点呼吸留白、序号严格连续与精确时间轴。"""
        storyboard_shots = [
            {
                "shot_id": 1,
                "duration_sec": 4.0,
                "audio": {
                    "speech_inpoint_sec": 0.3,
                    "contextual_tts_prompt": "既然你们不给活路",
                    "voice_type": "dialogue",
                }
            },
            {
                "shot_id": 2,
                "duration_sec": 3.0,
                "audio": {
                    "speech_inpoint_sec": None,
                    "contextual_tts_prompt": None,  # 空镜纯动作，无对白
                    "voice_type": None,
                }
            },
            {
                "shot_id": 3,
                "duration_sec": 5.0,
                "audio": {
                    "speech_inpoint_sec": 0.3,
                    "contextual_tts_prompt": "那大家就一起下地狱吧！",
                    "voice_type": "dialogue",
                }
            }
        ]
        srt_text = AudioMasteringEngine.generate_srt(storyboard_shots)
        assert "1\n00:00:00,300 --> " in srt_text
        assert "既然你们不给活路" in srt_text
        # Shot 2 没有对白，因此第二个字幕序号必须是 2 (严格递增)
        assert "2\n" in srt_text
        assert "一起下地狱吧！" in srt_text
        # Shot 1 结束于 4.0s，Shot 2 结束于 7.0s，Shot 3 从 7.0s 开始 + 0.3s = 7.3s
        assert "00:00:07,300 --> " in srt_text

    def test_mastering_schedule_ducking_and_cliff_silence(self):
        """测试智能混音调度：-12dB/-20dB 对白避让、[40,55]s 断崖静音与尾部淡出。"""
        # 构建一个总计 120s 的镜头序列
        storyboard_shots = []
        current_time = 0.0
        for i in range(1, 26):
            dur = 5.0 if i <= 23 else 2.5
            has_dialogue = (i % 2 == 1) and (i != 9)  # Shot 9 在 40~45s 区间留白，方便插入断崖静音
            storyboard_shots.append({
                "shot_id": i,
                "duration_sec": dur,
                "audio": {
                    "speech_inpoint_sec": 0.3 if has_dialogue else None,
                    "contextual_tts_prompt": f"第{i}句核心台词" if has_dialogue else None,
                    "voice_type": "dialogue" if has_dialogue else None,
                }
            })
            current_time += dur

        schedule = AudioMasteringEngine.generate_schedule(
            storyboard_shots=storyboard_shots,
            total_duration_sec=120.0,
            cliff_silence_window=(40.0, 55.0),
            cliff_silence_duration=3.0,
        )
        assert len(schedule) > 0

        # 1. 验证常规对白避让：-20.0dB
        ducking_events = [ev for ev in schedule if ev["speech_ducking_active"] and ev["target_bgm_volume_db"] == -20.0]
        assert len(ducking_events) > 0

        # 2. 验证常规环境垫音：-12.0dB
        ambient_events = [ev for ev in schedule if not ev["speech_ducking_active"] and ev["target_bgm_volume_db"] == -12.0]
        assert len(ambient_events) > 0

        # 3. 验证存在 3.0s 绝对断崖静音 (-999.0dB)
        cliff_events = [ev for ev in schedule if ev["target_bgm_volume_db"] <= -999.0]
        assert len(cliff_events) >= 1
        cliff = cliff_events[0]
        assert 40.0 <= cliff["time_start_sec"] <= 55.0
        assert (cliff["time_end_sec"] - cliff["time_start_sec"]) == pytest.approx(3.0, 0.1)
        assert "断崖静音" in cliff["event_description"]

        # 4. 验证片尾最后 2.0s 淡出硬切
        tail_events = [ev for ev in schedule if ev["time_end_sec"] >= 120.0]
        assert any("淡出" in ev["event_description"] or "硬切" in ev["event_description"] for ev in tail_events)

    def test_bgm_master_prompt_and_nle_specs(self):
        """测试 Suno BGM 提示词规范与 NLE 4 轨导出工程参数。"""
        bgm_prompt = generate_bgm_master_prompt(
            episode_id=1,
            genre="悬疑/复仇",
            emotional_arc="压抑-危机-爆发",
            key="C Minor",
            tempo_bpm=80,
            primary_instruments=["低音提琴", "大提琴拨弦", "冷感电子重击"],
        )
        assert "C Minor" in bgm_prompt
        assert "80 BPM" in bgm_prompt
        assert "低音提琴" in bgm_prompt
        assert "悬疑/复仇" in bgm_prompt

        nle = get_nle_mixing_guidelines()
        assert nle["sampling_rate"] == "48kHz"
        assert nle["bit_depth"] == "24-bit"
        assert nle["peak_db"] == -1.0
        assert nle["integrated_lufs"] == -14.0
        assert "A1_Dialogue" in nle["tracks"]
        assert "A4_Music_BGM" in nle["tracks"]
