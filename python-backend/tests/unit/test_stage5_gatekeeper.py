"""测试第一程定稿门禁节点流转。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage5_gatekeeper import stage5_literary_gatekeeper_node


class TestStage5Gatekeeper(unittest.TestCase):
    def test_incomplete_episodes_cannot_lock(self):
        state = IndustrialDramaMasterState(
            drama_id=1,
            total_episodes=5,
            completed_screenplays={1: {"title": "第1集"}},
        )
        res = stage5_literary_gatekeeper_node(state)
        self.assertFalse(res["literary_journey_locked"])
        self.assertEqual(res["journey"], "journey_1_literary")

    def test_complete_episodes_locks_and_transitions_to_journey2(self):
        state = IndustrialDramaMasterState(
            drama_id=1,
            total_episodes=2,
            completed_screenplays={
                1: {"title": "第1集", "body_markdown": "正文1"},
                2: {"title": "第2集", "body_markdown": "正文2"},
            },
        )
        res = stage5_literary_gatekeeper_node(state)
        self.assertTrue(res["literary_journey_locked"])
        self.assertEqual(res["journey"], "journey_2_visual")
        self.assertEqual(res["current_stage"], 6)
        self.assertEqual(res["current_visual_episode"], 1)


if __name__ == "__main__":
    unittest.main()
