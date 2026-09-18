"""实施路线图阶段二：Stage 1~4 前程文学故事工程流水线重构单元测试 (Test Phase 2 Stages 1 to 4 Pipeline)。

严格对齐《公共硬性约束》与《SKILL1.md v10.0.0》：
1. 【公共硬性约束 1 & 4】：节点内无业务分支判断，所有分支跳转由独立路由函数接管；
2. 【公共硬性约束 3】：统一使用 IndustrialDramaState (TypedDict) 入参与增量更新字典；
3. 【公共硬性约束 5】：条件路由函数全分支穷举，包含兜底 else 指向 "error_terminate"；
4. 【公共硬性约束 6】：逻辑对齐《Skill规则表》编号并配置 debug 日志；
5. 【防乱码】：代码全生命周期采用纯净 UTF-8 编码。
"""
from __future__ import annotations

import pytest
from typing import Any

from app.schemas.script_graph_state import IndustrialDramaState
from app.workflows.nodes.stage1_ideation import stage1_ideation_node
from app.workflows.nodes.stage2_character import stage2_character_node
from app.workflows.nodes.stage3_environment_prop import stage3_environment_prop_node
from app.workflows.nodes.stage4_outline import stage4_outline_node
from app.agents.red_blue_auditor import RedBlueAuditor
from app.workflows.routers.audit_router import (
    decide_audit_route,
    route_stage1_audit,
    route_stage2_audit,
    route_stage3_audit,
    route_stage4_audit,
    stage1_audit_node,
    stage2_audit_node,
    stage3_audit_node,
    stage4_audit_node,
    error_terminal_node,
    human_review_node,
)


class TestStage1To4Nodes:
    """【规则编号: RULE-VI-01 ~ RULE-VI-04】阶段 1~4 业务节点输入输出与契约合规测试。"""

    def test_stage1_ideation_node_contract_and_fallback(self):
        """测试 Stage 1 题材破壁节点：符合 TypedDict 契约，输出 10 大禁令、3 大爽点与 4 维度片名。"""
        initial_state: IndustrialDramaState = {
            "drama_id": 101,
            "genre": "都市悬疑",
            "visual_style": "电影胶片质感",
            "target_episodes": 12,
            "duration_sec_per_ep": 120,
            "aspect_ratio": "9:16",
        }
        
        output = stage1_ideation_node(initial_state)
        assert isinstance(output, dict)
        assert output.get("current_stage") == 1
        assert "selected_title" in output
        assert "forbidden_cliches_10" in output
        assert len(output["forbidden_cliches_10"]) >= 10
        assert "forbidden_cheap_tropes_3" in output
        assert len(output["forbidden_cheap_tropes_3"]) >= 3
        
        matrix = output.get("candidate_titles", {})
        assert "identity_contrast" in matrix
        assert "extreme_suspense" in matrix
        assert "prop_irony" in matrix
        assert "dark_psychology" in matrix
        
        assert "logline" in output
        assert "core_irony" in output
        assert "grand_payoff" in output
        assert "short_memory_a" in output

    def test_stage2_character_node_contract_and_gender(self):
        """测试 Stage 2 角色人设节点：必须强制声明生理性别、骨相DNA与生活质感服饰。"""
        state_after_s1: IndustrialDramaState = {
            "drama_id": 101,
            "selected_title": "暗局追踪",
            "logline": "法医调查旧案牵扯出惊天反转",
            "core_irony": "追凶者自己成了凶手的保护伞",
            "grand_payoff": "终局当众揭露三十年伪造证据真相",
            "visual_style": "冷峻蓝灰色调",
            "short_memory_a": "【短期记忆便签 A】已完成立项与双轨禁令",
        }

        output = stage2_character_node(state_after_s1)
        assert isinstance(output, dict)
        assert output.get("current_stage") == 2
        
        chars_engine = output.get("characters_engine", {})
        characters = chars_engine.get("characters", [])
        assert len(characters) >= 2
        
        # 检验生理性别强制字段与毫米级瑕疵
        for c in characters:
            assert "gender" in c, "角色必须强制显式声明生理性别 (male/female)"
            assert c["gender"] in ("male", "female")
            assert "biological_dna" in c
            assert "lived_in_costume" in c
            assert "psychological_quad" in c
            assert "carried_anchor_item" in c

        assert "dual_track_relationships" in output
        assert len(output["dual_track_relationships"]) >= 1
        assert "emotional_arc_trajectories" in output
        assert "short_memory_b" in output

    def test_stage3_environment_prop_node_contract_and_weathering(self):
        """测试 Stage 3 空间与物证节点：三层做旧、场景与服装同频、核心物证+3dB拟音。"""
        state_after_s2: IndustrialDramaState = {
            "drama_id": 101,
            "selected_title": "暗局追踪",
            "logline": "法医调查旧案牵扯出惊天反转",
            "short_memory_b": "【短期记忆便签 B】角色人设与关系网就绪",
            "characters_engine": {
                "characters": [
                    {
                        "name": "林巡",
                        "role_type": "protagonist",
                        "gender": "male",
                        "carried_anchor_item": {"item_name": "带划痕老怀表"},
                        "lived_in_costume": {"top_wear": "洗得起球的深灰色毛呢风衣，右袖口磨破露边"},
                    },
                    {
                        "name": "严栋",
                        "role_type": "antagonist",
                        "gender": "male",
                        "carried_anchor_item": {"item_name": "白金钢笔"},
                        "lived_in_costume": {"top_wear": "定制高支精纺西装，平整无褶皱"},
                    },
                ]
            },
        }

        output = stage3_environment_prop_node(state_after_s2)
        assert isinstance(output, dict)
        assert output.get("current_stage") == 3
        
        env_props = output.get("environments_and_props", {})
        envs = env_props.get("environments", [])
        props = env_props.get("props", [])
        assert len(envs) >= 1
        assert len(props) >= 1
        
        # 校验三层做旧与同频共振
        for env in envs:
            weathering = env.get("weathering_layers", {})
            assert "structural" in weathering
            assert "living" in weathering
            assert "optical" in weathering

        # 校验核心物证破损尺度与阻尼拟音分贝标注
        has_foley_db = any("+3" in p.get("foley_resistance", "") or "+2" in p.get("foley_resistance", "") for p in props)
        assert has_foley_db, "核心道具必须包含 +2dB ~ +3dB 拟音标记"
        assert "short_memory_c" in output

    def test_stage4_outline_node_contract_and_leitmotifs(self):
        """测试 Stage 4 双螺旋大纲节点：全剧 3 大音乐主题动机与分集黄金卡点。"""
        state_after_s3: IndustrialDramaState = {
            "drama_id": 101,
            "selected_title": "暗局追踪",
            "target_episodes": 6,
            "total_episodes": 6,
            "logline": "法医调查旧案牵扯出惊天反转",
            "core_irony": "追凶者自己成了凶手的保护伞",
            "short_memory_c": "【短期记忆便签 C】空间做旧与关键物证已闭环",
            "characters_engine": {
                "characters": [
                    {"name": "林巡", "role_type": "protagonist", "gender": "male"},
                    {"name": "严栋", "role_type": "antagonist", "gender": "male"},
                ]
            },
            "environments_and_props": {
                "props": [
                    {"name": "血迹怀表", "type": "narrative_reversal", "foley_resistance": "金属撞击声 (+3.0dB)"}
                ]
            },
        }

        output = stage4_outline_node(state_after_s3)
        assert isinstance(output, dict)
        assert output.get("current_stage") == 4
        
        # 校验全剧 3 大具象音乐主题动机
        audio_bible = output.get("audio_bible", {})
        leitmotifs = audio_bible.get("leitmotifs", [])
        assert len(leitmotifs) == 3
        motif_ids = [m.get("motif_id") for m in leitmotifs]
        assert "LEITMOTIF_01_SUSPENSE" in motif_ids
        assert "LEITMOTIF_02_TRAUMA" in motif_ids
        assert "LEITMOTIF_03_COUNTERATTACK" in motif_ids

        # 校验分集大纲双螺旋卡点
        outlines = output.get("season_outlines", {})
        assert len(outlines) >= 6
        for ep_num, ep_data in outlines.items():
            assert "hook_3s" in ep_data or "three_second_hook" in ep_data
            assert "micro_turning_point_45s" in ep_data
            assert "killer_cliffhanger_115s" in ep_data or "cliffhanger" in ep_data
            assert "lie_erosion_metric" in ep_data

        assert "short_memory_d" in output


class TestStage1To4AuditsAndRouters:
    """【规则编号: AUDIT-CHECKPOINT-01 ~ 04 & ROUTER-FAILOVER-01】哨卡 1~4 审查与独立路由穷举测试。"""

    def test_auditor_stage1_compliance_checks(self):
        """测试哨卡 1 蓝军硬指标核查与红军挑刺。"""
        # 合规样本
        valid_payload = {
            "selected_title": "绝命换脸",
            "forbidden_cliches_10": [f"禁令_{i}" for i in range(10)],
            "forbidden_cheap_tropes_3": ["爽点1", "爽点2", "爽点3"],
            "candidate_titles": {
                "identity_contrast": ["片名1"],
                "extreme_suspense": ["片名2"],
                "prop_irony": ["片名3"],
                "dark_psychology": ["片名4"],
            },
            "logline": "主角在致命缺陷下展开生死博弈",
            "grand_payoff": "终局核爆揭露真相",
        }
        report = RedBlueAuditor.audit_stage1(valid_payload)
        assert report.verdict in ("GREEN_APPROVED", "YELLOW_WARNING")
        assert len(report.blocking_issues) == 0

        # 不合规样本：缺少10大禁令
        invalid_payload = dict(valid_payload)
        invalid_payload["forbidden_cliches_10"] = ["只有一条"]
        bad_report = RedBlueAuditor.audit_stage1(invalid_payload)
        assert bad_report.verdict == "RED_BLOCKING"
        assert any("老套因果禁令" in issue for issue in bad_report.blocking_issues)

    def test_auditor_stage2_compliance_checks(self):
        """测试哨卡 2 蓝军硬指标：生理性别缺失直接触发 RED_BLOCKING。"""
        # 不合规样本：未声明生理性别
        no_gender_payload = {
            "characters": [
                {
                    "name": "主角A",
                    "role_type": "protagonist",
                    # 缺少 gender
                    "biological_dna": {"bone_structure": "高颧骨"},
                    "lived_in_costume": {"top_wear": "旧毛衣"},
                }
            ],
            "dual_track_relationships": [{"character_pair": "A vs B"}],
        }
        bad_report = RedBlueAuditor.audit_stage2(no_gender_payload)
        assert bad_report.verdict == "RED_BLOCKING"
        assert any("生理性别" in issue for issue in bad_report.blocking_issues)

    def test_auditor_stage3_compliance_checks(self):
        """测试哨卡 3 蓝军硬指标：缺少+3dB拟音标记或三层做旧阻断。"""
        # 不合规样本：无三层做旧
        bad_env_payload = {
            "environments": [
                {
                    "location_name": "样板间",
                    "weathering_layers": {},  # 空层
                }
            ],
            "props": [
                {
                    "name": "道具A",
                    "damage_scale": "轻微破损",
                    "foley_resistance": "普通声音",  # 缺少分贝标记
                }
            ],
        }
        bad_report = RedBlueAuditor.audit_stage3(bad_env_payload)
        assert bad_report.verdict == "RED_BLOCKING"
        assert len(bad_report.blocking_issues) >= 1

    def test_auditor_stage4_compliance_checks(self):
        """测试哨卡 4 蓝军硬指标：音乐动机不足 3 套直接阻断。"""
        bad_outline_payload = {
            "audio_bible": {"leitmotifs": [{"motif_id": "ONE_ONLY"}]},
            "season_outlines": {1: {"hook_3s": "开局", "micro_turning_point_45s": "反转", "cliffhanger": "断点"}},
            "total_episodes": 1,
        }
        bad_report = RedBlueAuditor.audit_stage4(bad_outline_payload)
        assert bad_report.verdict == "RED_BLOCKING"
        assert any("核心音乐主题动机" in issue for issue in bad_report.blocking_issues)

    def test_exhaustive_routing_decision_logic(self):
        """【公共硬性约束 5】测试纯决策路由函数 decide_audit_route 全分支穷举与兜底 else。"""
        # 1. GREEN_APPROVED -> proceed
        assert decide_audit_route(
            stage_name="stage1", verdict="GREEN_APPROVED", retry_count=0, max_retries=3
        ) == "proceed"

        # 2. YELLOW_WARNING -> proceed
        assert decide_audit_route(
            stage_name="stage2", verdict="YELLOW_WARNING", retry_count=1, max_retries=3
        ) == "proceed"

        # 3. RED_BLOCKING 且 retry < max_retries -> self_heal
        assert decide_audit_route(
            stage_name="stage3", verdict="RED_BLOCKING", retry_count=0, max_retries=3
        ) == "self_heal"
        assert decide_audit_route(
            stage_name="stage3", verdict="RED_BLOCKING", retry_count=2, max_retries=3
        ) == "self_heal"

        # 4. RED_BLOCKING 且 retry >= max_retries -> escalate_human
        assert decide_audit_route(
            stage_name="stage4", verdict="RED_BLOCKING", retry_count=3, max_retries=3
        ) == "escalate_human"
        assert decide_audit_route(
            stage_name="stage4", verdict="RED_BLOCKING", retry_count=4, max_retries=3
        ) == "escalate_human"

        # 5. 兜底 else：未知判定 -> error_terminate
        assert decide_audit_route(
            stage_name="stage1", verdict="UNKNOWN_STATE", retry_count=0, max_retries=3
        ) == "error_terminate"
        assert decide_audit_route(
            stage_name="stage2", verdict="", retry_count=0, max_retries=3
        ) == "error_terminate"

    def test_independent_stage_routers_and_nodes(self):
        """测试 4 个独立路由函数及审查节点契约。"""
        # 模拟 state 正常流转通过
        green_audit = {"verdict": "GREEN_APPROVED", "blocking_issues": []}
        state_green: IndustrialDramaState = {
            "latest_audit": green_audit,
            "stage_retry_counts": {"stage1": 0, "stage2": 0, "stage3": 0, "stage4": 0},
        }

        assert route_stage1_audit(state_green) == "proceed"
        assert route_stage2_audit(state_green) == "proceed"
        assert route_stage3_audit(state_green) == "proceed"
        assert route_stage4_audit(state_green) == "proceed"

        # 模拟 RED_BLOCKING 触发自愈与人工干预
        red_audit = {"verdict": "RED_BLOCKING", "blocking_issues": ["硬伤问题"]}
        state_retry: IndustrialDramaState = {
            "latest_audit": red_audit,
            "stage_retry_counts": {"stage1": 1, "stage2": 2, "stage3": 3},
        }
        # retry=1 < 3 -> self_heal
        assert route_stage1_audit(state_retry) == "self_heal"
        # retry=3 >= 3 -> escalate_human
        assert route_stage3_audit(state_retry) == "escalate_human"

        # 校验错误终止节点与人工复审节点
        err_out = error_terminal_node(state_retry)
        assert err_out.get("error_message") is not None
        assert err_out.get("journey") == "completed"

        human_out = human_review_node(state_retry)
        assert human_out.get("error_message") is not None

        # 校验 stage1_audit_node 审查节点执行
        valid_s1_state: IndustrialDramaState = {
            "selected_title": "绝命换脸",
            "forbidden_cliches_10": [f"禁令_{i}" for i in range(10)],
            "forbidden_cheap_tropes_3": ["爽点1", "爽点2", "爽点3"],
            "candidate_titles": {
                "identity_contrast": ["片名1"],
                "extreme_suspense": ["片名2"],
                "prop_irony": ["片名3"],
                "dark_psychology": ["片名4"],
            },
            "logline": "主角在致命缺陷下展开生死博弈",
            "grand_payoff": "终局核爆揭露真相",
            "stage_retry_counts": {},
        }
        node_res = stage1_audit_node(valid_s1_state)
        assert "latest_audit" in node_res
        assert node_res["latest_audit"]["verdict"] in ("GREEN_APPROVED", "YELLOW_WARNING")
