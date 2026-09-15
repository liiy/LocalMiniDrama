"""测试阶段 6 资产提纯与真理源总库维护。"""
import unittest

from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node


class TestStage6AssetTruth(unittest.TestCase):
    def test_asset_truth_extraction_and_registry(self):
        state = IndustrialDramaMasterState(
            drama_id=777,
            current_visual_episode=1,
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "绝境突围",
                    "scene_header": "夜 内 7号仓库",
                    "characters_present": ["陆沉"],
                    "core_props": ["染血加密U盘"],
                }
            },
            characters_engine={
                "characters": [
                    {"name": "陆沉", "appearance": "冷峻寸头伤疤"}
                ]
            },
            environments_and_props={
                "environments": [{"location_name": "7号仓库"}],
                "props": [{"name": "染血加密U盘"}],
            },
        )

        res = stage6_asset_truth_node(state)
        self.assertEqual(res["current_stage"], 6)
        manifests = res["episode_resource_manifests"]
        self.assertIn(1, manifests)
        registry = res["visual_audio_assets_registry"]
        self.assertIn("characters", registry)
        self.assertIn("environments", registry)
        self.assertIn("props", registry)


if __name__ == "__main__":
    unittest.main()
