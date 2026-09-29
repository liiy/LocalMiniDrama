"""测试阶段 6 资产提纯与真理源总库维护（章节三四段式协议与 DAG 派生血缘）。"""
import unittest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node
from app.workflows.utils.asset_protocol import AssetProtocolHelper


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
                    {
                        "character_id": "CHAR_LUCHEN",
                        "character_token": "LUCHEN",
                        "name": "陆沉",
                        "appearance": "冷峻寸头伤疤",
                    }
                ]
            },
            environments_and_props={
                "environments": [
                    {
                        "environment_id": "ENV_7HAOCANGKU",
                        "scene_token": "7HAOCANGKU",
                        "location_name": "7号仓库",
                    }
                ],
                "props": [
                    {
                        "prop_id": "PROP_RANXUEJIAMIUPAN",
                        "prop_token": "RANXUEJIAMIUPAN",
                        "name": "染血加密U盘",
                    }
                ],
            },
        )

        res = stage6_asset_truth_node(state)
        self.assertEqual(res["current_stage"], 6)
        manifests = res["episode_resource_manifests"]
        self.assertIn(1, manifests)
        manifest = manifests[1]

        # 1. 验证角色资产四段式规范与 DAG 派生
        char_assets = manifest.character_assets
        self.assertTrue(len(char_assets) >= 1)
        for ca in char_assets:
            aid = ca.get("asset_id") if isinstance(ca, dict) else getattr(ca, "asset_id")
            valid, reason = AssetProtocolHelper.validate_id(aid, expected_category="CHAR")
            self.assertTrue(valid, f"角色资产 ID 校验失败: {reason}")
            parsed = AssetProtocolHelper.parse_id(aid)
            self.assertEqual(parsed.object_token, "LUCHEN")

        # 验证服装派生自主肖像
        costume_assets = [
            ca for ca in char_assets
            if "BASE_COSTUME" in (ca.get("asset_id") if isinstance(ca, dict) else getattr(ca, "asset_id"))
        ]
        if costume_assets:
            c_item = costume_assets[0]
            pid = c_item.get("parent_asset_id") if isinstance(c_item, dict) else getattr(c_item, "parent_asset_id")
            gmode = c_item.get("generation_mode") if isinstance(c_item, dict) else getattr(c_item, "generation_mode")
            self.assertEqual(pid, "CHAR_LUCHEN_T1_BASE_PORTRAIT")
            self.assertEqual(gmode, "i2i")

        # 2. 验证场景与道具四段式规范
        scene_assets = manifest.scene_assets
        self.assertTrue(len(scene_assets) >= 1)
        for sa in scene_assets:
            aid = sa.get("asset_id") if isinstance(sa, dict) else getattr(sa, "asset_id")
            valid, reason = AssetProtocolHelper.validate_id(aid, expected_category="ENV")
            self.assertTrue(valid, f"场景资产 ID 校验失败: {reason}")

        prop_assets = manifest.prop_assets
        self.assertTrue(len(prop_assets) >= 1)
        for pa in prop_assets:
            aid = pa.get("asset_id") if isinstance(pa, dict) else getattr(pa, "asset_id")
            valid, reason = AssetProtocolHelper.validate_id(aid, expected_category="PROP")
            self.assertTrue(valid, f"道具资产 ID 校验失败: {reason}")

        # 3. 验证母音色资产
        audio_assets = manifest.audio_assets
        self.assertTrue(len(audio_assets) >= 1)
        self.assertTrue(
            any("VOICE_LUCHEN_T1_MASTER" in (aa.get("asset_id", "") if isinstance(aa, dict) else getattr(aa, "asset_id", ""))
                for aa in audio_assets)
        )

        # 4. 验证红蓝对抗哨卡 6 审查通过
        audit_report = RedBlueAuditor.audit_stage6({"manifest": manifest})
        self.assertEqual(audit_report.verdict, "GREEN_APPROVED")
        self.assertEqual(len(audit_report.blocking_issues), 0)


if __name__ == "__main__":
    unittest.main()
