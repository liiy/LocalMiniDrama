"""测试阶段 8 全息声学混音工程与独立条件路由微循环推进。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage8_audio_mastering import stage8_audio_mastering_node
from app.workflows.routers.audit_router import (
    episode_increment_node,
    pipeline_complete_node,
    route_episode_loop,
)


class TestStage8AudioMastering(unittest.TestCase):
    def test_audio_mastering_and_cursor_advance(self):
        # 1. 验证第 1 集声学混音工程节点纯函数输出（无节点内跳转）
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
        self.assertEqual(res1["current_stage"], 8)

        # 2. 验证独立条件路由判定：第 1 集未完成全季，路由至 next_episode
        state.episode_audio_masterings = res1["episode_audio_masterings"]
        route1 = route_episode_loop(state)
        self.assertEqual(route1, "next_episode")

        # 3. 验证游标递增辅助节点执行
        inc_res = episode_increment_node(state)
        self.assertEqual(inc_res["current_visual_episode"], 2)
        self.assertEqual(inc_res["current_stage"], 6)

        # 4. 推进到第 2 集（最后一集）
        state.current_visual_episode = 2
        res2 = stage8_audio_mastering_node(state)
        self.assertIn(2, res2["episode_audio_masterings"])
        state.episode_audio_masterings = res2["episode_audio_masterings"]

        # 5. 验证全集完成独立条件路由：路由至 complete_all
        route2 = route_episode_loop(state)
        self.assertEqual(route2, "complete_all")

        # 6. 验证流程完结节点
        comp_res = pipeline_complete_node(state)
        self.assertEqual(comp_res["journey"], "completed")


if __name__ == "__main__":
    unittest.main()
