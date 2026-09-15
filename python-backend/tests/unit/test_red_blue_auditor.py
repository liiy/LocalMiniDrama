"""测试红蓝自审引擎与路由决策逻辑。"""
import unittest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaMasterState,
    RedBlueAuditReport,
)
from app.workflows.routers.audit_router import decide_audit_route, make_stage_audit_node


class TestRedBlueAuditorAndRouter(unittest.TestCase):
    def test_audit_green_approval_and_proceed(self):
        content = {
            "episode_num": 1,
            "title": "破晓生死局",
            "hook_3s": "特写：主角踩灭还在冒烟的雪茄，一把拽开车门",
            "body_markdown": "正文动作交锋...",
            "ending_cliffhanger": "定格：后视镜中浮现出一双戴着红宝石戒指的眼睛",
        }
        report = RedBlueAuditor.audit(stage=5, content_payload=content)
        self.assertIn(report.verdict, [AuditVerdict.GREEN_APPROVED, AuditVerdict.YELLOW_WARNING])
        self.assertEqual(len(report.blocking_issues), 0)

        state = IndustrialDramaMasterState(drama_id=1, latest_audit=report)
        route = decide_audit_route(state, max_retries=2, current_retry_count=0)
        self.assertEqual(route, "proceed")

    def test_audit_red_blocking_and_self_heal_route(self):
        # 故意缺失前3秒视觉抓手与结尾断钩
        flawed_content = {
            "episode_num": 1,
            "title": "残缺剧本",
            "hook_3s": "",
            "ending_cliffhanger": "",
        }
        report = RedBlueAuditor.audit(stage=5, content_payload=flawed_content)
        self.assertEqual(report.verdict, AuditVerdict.RED_BLOCKING)
        self.assertTrue(len(report.blocking_issues) >= 1)

        state = IndustrialDramaMasterState(drama_id=1, latest_audit=report)
        # 第一次触发阻断 -> 自愈修补
        route1 = decide_audit_route(state, max_retries=2, current_retry_count=0)
        self.assertEqual(route1, "self_heal")

        # 超过上限 -> 主创介入审核
        route2 = decide_audit_route(state, max_retries=2, current_retry_count=2)
        self.assertEqual(route2, "human_review")

    def test_stage_audit_node_factory(self):
        state = IndustrialDramaMasterState(
            drama_id=101,
            selected_title="假死复仇之重回巅峰",
            logline="主角被陷害后改头换面绝地反击",
        )
        node_fn = make_stage_audit_node(stage=1, payload_selector=lambda s: {"title": s.selected_title, "logline": s.logline})
        result = node_fn(state)
        self.assertIn("latest_audit", result)
        self.assertIsInstance(result["latest_audit"], RedBlueAuditReport)


if __name__ == "__main__":
    unittest.main()
