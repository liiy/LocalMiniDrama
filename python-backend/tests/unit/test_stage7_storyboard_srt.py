"""测试阶段 7 分镜双模式选型与毫秒级 SRT 输出（严格四段式资产对齐与哨卡自审）。"""
import unittest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node
from app.workflows.utils.asset_protocol import AssetProtocolHelper


class TestStage7StoryboardSRT(unittest.TestCase):
    def test_storyboard_and_srt_generation(self):
        state = IndustrialDramaMasterState(
            drama_id=666,
            current_visual_episode=1,
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "生死突围",
                    "hook_3s": "开局枪口顶头",
                    "body_markdown": "对白交锋...",
                    "ending_cliffhanger": "后视镜浮现面孔",
                }
            },
            characters_engine={
                "characters": [
                    {"name": "陆沉", "character_token": "LUCHEN"},
                    {"name": "沈墨", "character_token": "SHENMO"},
                ]
            },
            environments_and_props={
                "environments": [{"location_name": "核心仓库", "scene_token": "CANGKU"}],
                "props": [{"name": "加密信件", "prop_token": "LETTER"}],
            },
        )

        res = stage7_storyboard_srt_node(state)
        self.assertEqual(res["current_stage"], 7)
        storyboards = res["episode_storyboards"]
        self.assertIn(1, storyboards)
        shots = storyboards[1]
        self.assertTrue(len(shots) >= 2)

        # 检查是否包含模式 A 与模式 B
        modes = [s.generation_mode for s in shots]
        self.assertIn("first_last_frame", modes)
        self.assertIn("multi_image_reference", modes)

        # 检查四段式资产引用合规性
        for s in shots:
            if s.generation_mode == "first_last_frame" and s.first_last_config:
                ff_id = s.first_last_config.get("first_frame_asset_id")
                lf_id = s.first_last_config.get("last_frame_asset_id")
                if ff_id:
                    valid, _ = AssetProtocolHelper.validate_id(ff_id)
                    self.assertTrue(valid, f"首帧资产 ID 非标: {ff_id}")
                if lf_id:
                    valid, _ = AssetProtocolHelper.validate_id(lf_id)
                    self.assertTrue(valid, f"尾帧资产 ID 非标: {lf_id}")

            if s.generation_mode == "multi_image_reference" and s.multi_image_config:
                refs = s.multi_image_config.get("reference_asset_ids") or []
                for r in refs:
                    valid, _ = AssetProtocolHelper.validate_id(r)
                    self.assertTrue(valid, f"参考资产 ID 非标: {r}")

        # 检查红蓝对抗哨卡 7 审查通过
        audit_report = RedBlueAuditor.audit_stage7({"shots": shots})
        self.assertEqual(audit_report.verdict, "GREEN_APPROVED")
        self.assertEqual(len(audit_report.blocking_issues), 0)

        # 检查 SRT 字幕
        srts = res["episode_srt_exports"]
        self.assertIn(1, srts)
        self.assertIn("-->", srts[1])


if __name__ == "__main__":
    unittest.main()
