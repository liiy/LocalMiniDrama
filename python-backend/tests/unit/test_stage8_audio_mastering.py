"""测试阶段 8 全息声学混音工程与集数游标推进。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage8_audio_mastering import stage8_audio_mastering_node


class TestStage8AudioMastering(unittest.TestCase):
    def test_audio_mastering_and_cursor_advance(self):
        # 测试第 1 集执行后推进至第 2 集
        state = IndustrialDramaMasterState(
            drama_id=555,
            total_episodes=2,
            current_visual_episode=1,
            journey="journey_2_visual",
        )

        res1 = stage8_audio_mastering_node(state)
        self.assertIn(1, res1["episode_audio_masterings"])
        config1 = res1["episode_audio_masterings"][1]
        self.assertEqual(config1["target_lufs"], -23.0)
        self.assertEqual(config1["ducking_strategy"]["dialogue_trigger_attenuation_db"], -12.0)
        self.assertEqual(res1["current_visual_episode"], 2)
        self.assertEqual(res1["journey"], "journey_2_visual")

        # 推进到第 2 集（最后一集）
        state.current_visual_episode = 2
        state.episode_audio_masterings = res1["episode_audio_masterings"]
        res2 = stage8_audio_mastering_node(state)
        self.assertIn(2, res2["episode_audio_masterings"])
        self.assertEqual(res2["current_visual_episode"], 2)
        self.assertEqual(res2["journey"], "completed")


if __name__ == "__main__":
    unittest.main()
