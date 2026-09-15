"""测试阶段 7 分镜双模式选型与毫秒级 SRT 输出。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node


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

        # 检查 SRT 字幕
        srts = res["episode_srt_exports"]
        self.assertIn(1, srts)
        self.assertIn("-->", srts[1])


if __name__ == "__main__":
    unittest.main()
