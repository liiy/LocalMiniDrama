"""测试第一程阶段 1~4 节点流转与状态更新。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage1_ideation import stage1_ideation_node
from app.workflows.nodes.stage2_character import stage2_character_node
from app.workflows.nodes.stage3_environment_prop import stage3_environment_prop_node
from app.workflows.nodes.stage4_outline import stage4_outline_node


class TestStages1To4(unittest.TestCase):
    def test_stages_1_to_4_pipeline(self):
        state = IndustrialDramaMasterState(
            drama_id=999,
            total_episodes=5,
        )

        # Stage 1
        out1 = stage1_ideation_node(state)
        self.assertEqual(out1["current_stage"], 1)
        self.assertTrue(len(out1["selected_title"]) > 0)
        self.assertTrue(len(out1["candidate_titles"].identity_contrast) >= 1)
        self.assertTrue("short_memory_a" in out1)

        # Update state for Stage 2
        state.selected_title = out1["selected_title"]
        state.logline = out1["logline"]
        state.candidate_titles = out1["candidate_titles"]
        state.negative_rules = out1["negative_rules"]
        state.short_memory_a = out1["short_memory_a"]

        # Stage 2
        out2 = stage2_character_node(state)
        self.assertEqual(out2["current_stage"], 2)
        chars = out2["characters_engine"]["characters"]
        self.assertTrue(len(chars) >= 2)
        self.assertIn("psychological_quad", chars[0])
        self.assertIn("linguistic_fingerprint", chars[0])
        self.assertTrue("short_memory_b" in out2)

        # Update state for Stage 3
        state.characters_engine = out2["characters_engine"]
        state.short_memory_b = out2["short_memory_b"]

        # Stage 3
        out3 = stage3_environment_prop_node(state)
        self.assertEqual(out3["current_stage"], 3)
        envs = out3["environments_and_props"]["environments"]
        props = out3["environments_and_props"]["props"]
        self.assertTrue(len(envs) >= 1)
        self.assertTrue(len(props) >= 1)
        self.assertIn("weathering_layers", envs[0])
        self.assertIn("damage_scale", props[0])
        self.assertTrue("short_memory_c" in out3)

        # Update state for Stage 4
        state.environments_and_props = out3["environments_and_props"]
        state.short_memory_c = out3["short_memory_c"]

        # Stage 4
        out4 = stage4_outline_node(state)
        self.assertEqual(out4["current_stage"], 4)
        season_outlines = out4["season_outlines"]
        self.assertEqual(len(season_outlines), 5)
        self.assertTrue("three_second_hook" in season_outlines[1])
        self.assertTrue("cliffhanger" in season_outlines[1])
        self.assertTrue("short_memory_d" in out4)


if __name__ == "__main__":
    unittest.main()
