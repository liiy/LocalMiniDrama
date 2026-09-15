"""端到端验证两程九阶 LangGraph 主图编排与完整生命周期流转。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.industrial_master_graph import run_industrial_master_pipeline


class TestIndustrialMasterGraph(unittest.TestCase):
    def test_full_pipeline_execution(self):
        initial_state = IndustrialDramaMasterState(
            drama_id=9999,
            total_episodes=2,
            selected_title="破晓复仇局",
            logline="陆沉假死归来反杀韩泰",
        )

        final_state = run_industrial_master_pipeline(
            initial_state=initial_state,
            thread_id="test_run_9999",
        )

        # 验证第一程成果
        self.assertTrue(final_state.literary_journey_locked)
        self.assertEqual(len(final_state.completed_screenplays), 2)
        self.assertIn(1, final_state.completed_screenplays)
        self.assertIn(2, final_state.completed_screenplays)

        # 验证第二程成果
        self.assertEqual(final_state.journey, "completed")
        self.assertIn(1, final_state.episode_storyboards)
        self.assertIn(2, final_state.episode_storyboards)
        self.assertIn(1, final_state.episode_srt_exports)
        self.assertIn(2, final_state.episode_srt_exports)
        self.assertIn(1, final_state.episode_audio_masterings)
        self.assertIn(2, final_state.episode_audio_masterings)


if __name__ == "__main__":
    unittest.main()
