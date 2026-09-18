"""【阶段三验收测试】Stage 5 文学剧本疾速波次连续吞吐与第一程文学定稿总锁门禁全景测试。

严格对齐《Skill规则表》v10.0.0 与公共硬性约束：
1. 节点统一入参 state，返回增量字典；
2. 独立路由函数穷举所有分支并包含兜底 else，指向错误终止节点；
3. Stage 5 工笔生成符合 5 大工业规格（COT-01~05）；
4. 哨卡 5 蓝军硬指标（场景标头、前3秒钩子、三位一体黄金悬念钩子、集尾物理快照、上一集0秒接力）严格生效；
5. 第一程定稿门禁严格判定全季完备性并加锁。
"""
from __future__ import annotations

import unittest
from typing import Any

from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaMasterState,
    RedBlueAuditReport,
)
from app.agents.red_blue_auditor import RedBlueAuditor
from app.workflows.nodes.stage5_screenplay import (
    generate_single_episode,
    stage5_screenplay_node,
)
from app.workflows.nodes.stage5_gatekeeper import stage5_literary_gatekeeper_node
from app.workflows.routers.audit_router import (
    stage5_audit_node,
    route_stage5_audit,
    route_stage5_batch,
    route_literary_gatekeeper,
    error_terminal_node,
    human_review_node,
)


class TestPhase3Stage5AndGatekeeper(unittest.TestCase):
    """阶段三全景单元测试。"""

    def setUp(self):
        """初始化测试基底状态。"""
        self.base_state = IndustrialDramaMasterState(
            drama_id=999,
            total_episodes=5,
            target_episodes=5,
            selected_title="夜幕裁决者",
            logline="雨夜裁决，追查十五年前雨夜矿难真相",
            grand_payoff="终局庭审公开展出黑金账册，幕后大佬当庭认罪",
            characters_engine={
                "characters": [
                    {
                        "name": "沈炼",
                        "role_type": "protagonist",
                        "biological_dna": {
                            "bone_structure": "高眉骨深眼窝下颌如刀削",
                            "skin_micro_texture": "左颧骨有火药微灼痕，胡茬青黑",
                        },
                        "lived_in_costume": {
                            "outerwear": "洗得发灰翻领军绿风衣，右袖口磨破",
                        },
                        "carried_anchor_item": {"item_name": "老式银质打火机"},
                    },
                    {
                        "name": "赵崇山",
                        "role_type": "antagonist",
                        "biological_dna": {
                            "bone_structure": "鹰钩鼻三角眼，右侧法令纹深陷",
                            "skin_micro_texture": "常年室内皮肤惨白浮肿",
                        },
                        "lived_in_costume": {
                            "outerwear": "定制暗纹深蓝西服，领口微松",
                        },
                        "carried_anchor_item": {"item_name": "沉香木手串"},
                    },
                ]
            },
            environments_and_props={
                "environments": [
                    {
                        "location_name": "雨夜废弃扳道室",
                        "lighting_atmosphere": "惨白闪电与昏黄白炽灯交错",
                    },
                    {
                        "location_name": "赵氏地下密室",
                        "lighting_atmosphere": "暗红指示灯与冷调监控屏幕",
                    },
                ],
                "props": [
                    {"name": "锈蚀外科手术刀", "physical_texture": "手术级碳钢，表面有点状锈斑"},
                    {"name": "黑色防水加密U盘", "physical_texture": "哑光工程塑料外壳带有摩擦划痕"},
                ],
            },
            season_outlines={
                1: {
                    "title": "第1集：雨夜刀锋",
                    "hook_3s": "开场特写：带血的手术刀死死抵在赵崇山喉结",
                    "killer_cliffhanger_115s": "绝杀断点：扳道室铁门被焊死，四柄消音手枪红外激光锁胸",
                },
                2: {
                    "title": "第2集：绝地反杀",
                    "hook_3s": "开场特写：沈炼借力后撤撞翻铁架，手术刀割破保镖咽喉",
                    "killer_cliffhanger_115s": "绝杀断点：赵崇山狞笑着按动地下密室自毁倒计时",
                },
                3: {
                    "title": "第3集：致命交易",
                    "hook_3s": "开场特写：沈炼将加密U盘拍在满是碎玻璃的桌面上",
                    "killer_cliffhanger_115s": "绝杀断点：手机收到匿名彩信，妹妹正被绑在汽油桶上",
                },
                4: {
                    "title": "第4集：生死狂飙",
                    "hook_3s": "开场特写：重型皮卡撞碎铁闸门冲入暴雨泥泞公路",
                    "killer_cliffhanger_115s": "绝杀断点：刹车管被剪断，前方是断头高架桥",
                },
                5: {
                    "title": "第5集：终局审判",
                    "hook_3s": "开场特写：沈炼一脚踹开法庭侧门，手举染血账册",
                    "killer_cliffhanger_115s": "全剧绝杀终局：审判长法槌重重落下，赵崇山面如死灰瘫倒",
                },
            },
            completed_screenplays={},
            inter_episode_physical_snapshot=None,
            literary_journey_locked=False,
            stage_retry_counts={},
        )

    # ---------------------------------------------------------------------
    # 1. 单集生成规格与 5 大 COT 契约验证
    # ---------------------------------------------------------------------
    def test_stage5_single_episode_generation_contract(self):
        """【规则编号: STAGE-5-COT-01 ~ 05】测试单集工笔文学剧本生成是否完全满足五大工业契约。"""
        res = generate_single_episode(self.base_state, 1)
        self.assertIn("script", res)
        self.assertIn("outgoing_snapshot", res)

        script = res["script"]
        snapshot = res["outgoing_snapshot"]

        # 契约基础字段
        self.assertEqual(script["episode_num"], 1)
        self.assertEqual(script["episode_id"], 1)
        self.assertIn("第1集", script["episode_title"])
        self.assertEqual(script["planned_duration_sec"], 120.0)

        # COT-01 & 02: 正文、场景标头与声学标记
        body = script["screenplay_text"]
        self.assertTrue(len(body) > 100)
        self.assertIn("【场景", body)
        self.assertIn("[声学行为:", body)

        # COT-03: 前 3 秒动作钩子与片尾定格
        self.assertTrue(len(script["hook_3s"]) > 0)
        self.assertTrue(len(script["ending_cliffhanger"]) > 0)

        # COT-04: 三位一体黄金悬念绝杀钩子
        golden = script["golden_cliffhanger_hook"]
        self.assertIsInstance(golden, dict)
        self.assertIn("hook_action", golden)
        self.assertIn("hook_dialogue", golden)
        self.assertIn("hook_audio_braam", golden)

        # COT-05: 集尾物理快照
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(snapshot["episode_index"], 1)
        self.assertIn("timeline_progress_sec", snapshot)
        self.assertIn("posture_and_injuries", snapshot)
        self.assertIn("carried_props_status", snapshot)
        self.assertIn("weather_and_light", snapshot)
        self.assertIn("freeze_frame_desc", snapshot)

        # AST 解析树验证
        self.assertIsNotNone(script.get("ast_data"))

    # ---------------------------------------------------------------------
    # 2. 第 2 集及后续跨集 0 秒动作与物理快照接力
    # ---------------------------------------------------------------------
    def test_stage5_consecutive_episodes_physical_pickup(self):
        """【规则编号: STAGE-5-COT-03】测试跨集 0 秒物理咬合接力。"""
        # 生成第 1 集
        ep1_res = generate_single_episode(self.base_state, 1)
        ep1_snapshot = ep1_res["outgoing_snapshot"]

        # 生成第 2 集并注入第 1 集快照
        ep2_res = generate_single_episode(self.base_state, 2, incoming_snapshot=ep1_snapshot)
        ep2_script = ep2_res["script"]

        self.assertEqual(ep2_script["episode_num"], 2)
        pickup = ep2_script.get("previous_episode_0s_pickup")
        self.assertIsNotNone(pickup)
        self.assertEqual(pickup.get("inherited_from_episode"), 1)
        self.assertIn(ep1_snapshot["freeze_frame_desc"][:10], pickup.get("pickup_state_description", ""))

    # ---------------------------------------------------------------------
    # 3. Mini-Arc 波次生成节点与增量契约
    # ---------------------------------------------------------------------
    def test_stage5_mini_arc_batch_pipeline(self):
        """【规则编号: RULE-VI-05】测试波次吞吐节点 stage5_screenplay_node 分批连续吞吐。"""
        state = dict(self.base_state)
        # 第一波次：生成 1~3 集
        out1 = stage5_screenplay_node(state)
        self.assertEqual(out1["current_stage"], 5)
        completed1 = out1["completed_screenplays"]
        self.assertEqual(len(completed1), 3)
        self.assertFalse(out1["literary_journey_locked"])
        self.assertEqual(out1["current_mini_arc_index"], 1)

        # 模拟状态更新进入第二波次
        state.update(out1)
        out2 = stage5_screenplay_node(state)
        completed2 = out2["completed_screenplays"]
        self.assertEqual(len(completed2), 5)
        self.assertTrue(out2["literary_journey_locked"])
        self.assertEqual(out2["current_mini_arc_index"], 2)

    # ---------------------------------------------------------------------
    # 4. 哨卡 5 蓝军硬指标阻断与放行规则
    # ---------------------------------------------------------------------
    def test_stage5_audit_checkpoint_rules(self):
        """【规则编号: AUDIT-CHECKPOINT-05】测试哨卡 5 蓝军客观硬指标合规判定。"""
        # 1. 正常合格剧本 ➔ GREEN
        ep1 = generate_single_episode(self.base_state, 1)["script"]
        report_ok = RedBlueAuditor.audit_stage5({1: ep1})
        self.assertEqual(report_ok.verdict, AuditVerdict.GREEN_APPROVED)
        self.assertEqual(len(report_ok.blocking_issues), 0)

        # 2. 场景标头不足 2 处 ➔ 触发蓝军阻断
        bad_scene_ep = dict(ep1)
        bad_scene_ep["screenplay_text"] = "正文没有任何场景标头，纯台词描写沈炼走出大门"
        report_bad_scene = RedBlueAuditor.audit_stage5({1: bad_scene_ep})
        self.assertEqual(report_bad_scene.verdict, AuditVerdict.RED_BLOCKING)
        self.assertTrue(any("时空场景标头不足" in issue for issue in report_bad_scene.blocking_issues))

        # 3. 缺失前 3 秒钩子 ➔ 触发蓝军阻断
        bad_hook_ep = dict(ep1)
        bad_hook_ep["hook_3s"] = ""
        bad_hook_ep["screenplay_text"] = "【场景 1：内景 办公室】\n无前置爆点\n【场景 2：外景 走廊】\n正常走路"
        report_bad_hook = RedBlueAuditor.audit_stage5({1: bad_hook_ep})
        self.assertEqual(report_bad_hook.verdict, AuditVerdict.RED_BLOCKING)
        self.assertTrue(any("hook_3s" in issue for issue in report_bad_hook.blocking_issues))

        # 4. 缺失黄金绝杀断点 ➔ 触发蓝军阻断
        bad_cliff_ep = dict(ep1)
        bad_cliff_ep["golden_cliffhanger_hook"] = None
        bad_cliff_ep["killer_cliffhanger_115s"] = None
        bad_cliff_ep["ending_cliffhanger"] = ""
        report_bad_cliff = RedBlueAuditor.audit_stage5({1: bad_cliff_ep})
        self.assertEqual(report_bad_cliff.verdict, AuditVerdict.RED_BLOCKING)
        self.assertTrue(any("golden_cliffhanger_hook" in issue for issue in report_bad_cliff.blocking_issues))

        # 5. 第 2 集缺失 0 秒物理接力 ➔ 触发蓝军阻断
        bad_pickup_ep2 = dict(ep1)
        bad_pickup_ep2["episode_id"] = 2
        bad_pickup_ep2["episode_num"] = 2
        bad_pickup_ep2["previous_episode_0s_pickup"] = None
        bad_pickup_ep2["incoming_physical_snapshot"] = None
        report_bad_pickup = RedBlueAuditor.audit_stage5({2: bad_pickup_ep2})
        self.assertEqual(report_bad_pickup.verdict, AuditVerdict.RED_BLOCKING)
        self.assertTrue(any("previous_episode_0s_pickup" in issue for issue in report_bad_pickup.blocking_issues))

    # ---------------------------------------------------------------------
    # 5. stage5_audit_node 与 route_stage5_audit 独立路由函数
    # ---------------------------------------------------------------------
    def test_stage5_audit_node_and_route(self):
        """【规则编号: AUDIT-CHECKPOINT-05 & ROUTER-FAILOVER-01】测试审查节点与独立条件路由。"""
        # 测试 stage5_audit_node 正常执行
        ep1 = generate_single_episode(self.base_state, 1)["script"]
        state = dict(self.base_state)
        state["completed_screenplays"] = {1: ep1}

        res = stage5_audit_node(state)
        self.assertIn("latest_audit", res)
        self.assertEqual(res["latest_audit"].verdict, AuditVerdict.GREEN_APPROVED)

        # 测试 route_stage5_audit 分支覆盖
        # 1. GREEN -> proceed
        state["latest_audit"] = RedBlueAuditReport(
            blue_team_compliance={}, red_team_criticism={},
            verdict=AuditVerdict.GREEN_APPROVED, blocking_issues=[], warning_suggestions=[]
        )
        self.assertEqual(route_stage5_audit(state), "proceed")

        # 2. RED, retry < 2 -> self_heal
        state["latest_audit"] = RedBlueAuditReport(
            blue_team_compliance={}, red_team_criticism={},
            verdict=AuditVerdict.RED_BLOCKING, blocking_issues=["场景标头缺失"], warning_suggestions=[]
        )
        state["stage_retry_counts"] = {"stage5": 1}
        self.assertEqual(route_stage5_audit(state), "self_heal")

        # 3. RED, retry >= 2 -> escalate_human
        state["stage_retry_counts"] = {"stage5": 2}
        self.assertEqual(route_stage5_audit(state), "escalate_human")

        # 4. 未定义状态 -> error_terminate (兜底分支)
        state["latest_audit"] = {"verdict": "UNKNOWN_ERROR_VERDICT"}
        self.assertEqual(route_stage5_audit(state), "error_terminate")

    # ---------------------------------------------------------------------
    # 6. route_stage5_batch 波次推进独立条件路由函数
    # ---------------------------------------------------------------------
    def test_route_stage5_batch(self):
        """【规则编号: ROUTER-BATCH-05】测试波次推进独立条件路由函数的分支穷举与兜底。"""
        state = {"total_episodes": 5, "completed_screenplays": {1: {}, 2: {}, 3: {}}}
        # 1. 3/5 未完成 -> next_batch
        self.assertEqual(route_stage5_batch(state), "next_batch")

        # 2. 5/5 已全部完成 -> gatekeeper
        state["completed_screenplays"] = {1: {}, 2: {}, 3: {}, 4: {}, 5: {}}
        self.assertEqual(route_stage5_batch(state), "gatekeeper")

        # 3. 异常分支（total <= 0）-> error_terminate
        state["total_episodes"] = 0
        self.assertEqual(route_stage5_batch(state), "error_terminate")

    # ---------------------------------------------------------------------
    # 7. 第一程定稿门禁节点与路由
    # ---------------------------------------------------------------------
    def test_stage5_literary_gatekeeper_node_and_route(self):
        """【规则编号: RULE-GATEKEEPER-05 & ROUTER-GATEKEEPER-05】测试第一程定稿门禁与独立条件路由。"""
        state = dict(self.base_state)
        state["total_episodes"] = 5

        # 1. 未全部完成剧本时（仅完成 2 集），门禁节点拒绝锁定
        state["completed_screenplays"] = {1: {}, 2: {}}
        gate_res_unlocked = stage5_literary_gatekeeper_node(state)
        self.assertFalse(gate_res_unlocked["literary_journey_locked"])
        self.assertEqual(gate_res_unlocked["current_stage"], 5)

        # 路由判定未锁 -> halt_journey1
        state.update(gate_res_unlocked)
        self.assertEqual(route_literary_gatekeeper(state), "halt_journey1")

        # 2. 全季 5 集已全部生成完成，门禁节点放行加锁
        state["completed_screenplays"] = {1: {}, 2: {}, 3: {}, 4: {}, 5: {}}
        gate_res_locked = stage5_literary_gatekeeper_node(state)
        self.assertTrue(gate_res_locked["literary_journey_locked"])
        self.assertEqual(gate_res_locked["journey"], "journey_2_visual")
        self.assertEqual(gate_res_locked["current_stage"], 6)

        # 路由判定已锁 -> proceed_journey2
        state.update(gate_res_locked)
        self.assertEqual(route_literary_gatekeeper(state), "proceed_journey2")

        # 3. 兜底 else：异常状态 -> error_terminate
        self.assertEqual(route_literary_gatekeeper({"literary_journey_locked": "INVALID_BOOLEAN"}), "error_terminate")

    # ---------------------------------------------------------------------
    # 8. 错误终止与人工干预终端节点测试
    # ---------------------------------------------------------------------
    def test_terminal_nodes(self):
        """【规则编号: ROUTER-FAILOVER-01】测试终端节点。"""
        state = {
            "latest_audit": RedBlueAuditReport(
                blue_team_compliance={}, red_team_criticism={},
                verdict=AuditVerdict.RED_BLOCKING,
                blocking_issues=["严重逻辑硬伤"], warning_suggestions=[]
            )
        }
        err_out = error_terminal_node(state)
        self.assertIn("Audit Blocking", err_out["error_message"])
        self.assertEqual(err_out["journey"], "completed")

        human_out = human_review_node(state)
        self.assertIn("Suspended for human intervention", human_out["error_message"])


if __name__ == "__main__":
    unittest.main()
