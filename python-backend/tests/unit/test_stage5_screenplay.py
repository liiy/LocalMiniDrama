"""测试阶段 5 文学剧本工笔生成与物理连续性咬合。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage5_screenplay import (
    generate_single_episode,
    stage5_screenplay_node,
)


class TestStage5Screenplay(unittest.TestCase):
    def setUp(self):
        self.state = IndustrialDramaMasterState(
            drama_id=888,
            total_episodes=3,
            selected_title="破晓复仇局",
            logline="主角陆沉隐忍三年向韩泰复仇",
            characters_engine={
                "characters": [
                    {"name": "陆沉", "role_type": "protagonist", "carried_anchor_item": {"item_name": "怀表"}},
                    {"name": "韩泰", "role_type": "antagonist", "carried_anchor_item": {"item_name": "手串"}},
                ]
            },
            environments_and_props={
                "environments": [{"location_name": "7号废弃仓库"}],
                "props": [{"name": "染血加密U盘钥匙扣"}],
            },
            season_outlines={
                1: {"title": "第1集：生死突围", "hook_3s": "开局枪口抵头", "killer_cliffhanger_115s": "绝杀断点"},
                2: {"title": "第2集：暗流涌动", "hook_3s": "暴雨中急刹车", "killer_cliffhanger_115s": "神秘来电"},
                3: {"title": "第3集：终局对决", "hook_3s": "点燃引线", "killer_cliffhanger_115s": "全剧收官反转"},
            },
        )

    def test_single_episode_generation(self):
        result = generate_single_episode(self.state, 1)
        script = result["script"]
        snapshot = result["outgoing_snapshot"]

        self.assertEqual(script["episode_num"], 1)
        self.assertTrue(len(script["hook_3s"]) > 0)
        self.assertTrue(len(script["ending_cliffhanger"]) > 0)
        self.assertIsNotNone(script.get("ast_data"))
        self.assertEqual(snapshot["episode_index"], 1)

    def test_stage5_screenplay_batch_pipeline(self):
        # 批次生成（总集数 3 集）
        out = stage5_screenplay_node(self.state)
        self.assertEqual(out["current_stage"], 5)
        completed = out["completed_screenplays"]
        self.assertEqual(len(completed), 3)
        self.assertTrue(out["literary_journey_locked"])
        self.assertIsNotNone(out["inter_episode_physical_snapshot"])


if __name__ == "__main__":
    unittest.main()
