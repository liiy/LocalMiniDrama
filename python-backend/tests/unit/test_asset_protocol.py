"""测试章节三四段式资产协议核心解析、校验、构建与 DAG 依赖派生。"""
import unittest

from app.workflows.utils.asset_protocol import (
    ASSET_ID_REGEX,
    AssetDependency,
    AssetProtocolHelper,
    ParsedAssetID,
)


class TestAssetProtocolHelper(unittest.TestCase):
    def test_parse_valid_ids(self):
        # 1. 基础肖像
        parsed = AssetProtocolHelper.parse_id("CHAR_LINWAN_T1_BASE_PORTRAIT")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.category, "CHAR")
        self.assertEqual(parsed.object_token, "LINWAN")
        self.assertEqual(parsed.tier, "T1")
        self.assertEqual(parsed.function_type, "BASE")
        self.assertEqual(parsed.modifier, "PORTRAIT")
        self.assertEqual(parsed.standard_id, "CHAR_LINWAN_T1_BASE_PORTRAIT")

        # 2. 四视角表情
        parsed2 = AssetProtocolHelper.parse_id("CHAR_LINWAN_T2_4V_FRONT")
        self.assertIsNotNone(parsed2)
        self.assertEqual(parsed2.category, "CHAR")
        self.assertEqual(parsed2.tier, "T2")
        self.assertEqual(parsed2.function_type, "4V")
        self.assertEqual(parsed2.modifier, "FRONT")

        # 3. 场景全景
        parsed_env = AssetProtocolHelper.parse_id("ENV_WAREHOUSE_T1_WIDE")
        self.assertIsNotNone(parsed_env)
        self.assertEqual(parsed_env.category, "ENV")
        self.assertEqual(parsed_env.object_token, "WAREHOUSE")

        # 4. 道具破损
        parsed_prop = AssetProtocolHelper.parse_id("PROP_LETTER_T1_ACTION_DAMAGED")
        self.assertIsNotNone(parsed_prop)
        self.assertEqual(parsed_prop.category, "PROP")
        self.assertEqual(parsed_prop.object_token, "LETTER")
        self.assertEqual(parsed_prop.function_type, "ACTION")
        self.assertEqual(parsed_prop.modifier, "DAMAGED")

        # 5. 音色母音频
        parsed_voice = AssetProtocolHelper.parse_id("VOICE_LINWAN_T1_MASTER")
        self.assertIsNotNone(parsed_voice)
        self.assertEqual(parsed_voice.category, "VOICE")
        self.assertEqual(parsed_voice.function_type, "MASTER")

    def test_voice_master_short_normalization(self):
        """VOICE_<TOKEN>_MASTER 应自动规范化为 VOICE_<TOKEN>_T1_MASTER"""
        norm = AssetProtocolHelper.normalize_id("VOICE_LINWAN_MASTER")
        self.assertEqual(norm, "VOICE_LINWAN_T1_MASTER")
        parsed = AssetProtocolHelper.parse_id("VOICE_LINWAN_MASTER")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.standard_id, "VOICE_LINWAN_T1_MASTER")

    def test_validate_id_rejections(self):
        # 非法前缀
        valid, _ = AssetProtocolHelper.validate_id("SCENE_01_TEST")
        self.assertFalse(valid)

        # 缺少 Tier
        valid, _ = AssetProtocolHelper.validate_id("CHAR_LINWAN_PORTRAIT")
        self.assertFalse(valid)

        # 期望类型不符
        valid, reason = AssetProtocolHelper.validate_id(
            "ENV_OFFICE_T1_WIDE", expected_category="CHAR"
        )
        self.assertFalse(valid)
        self.assertIn("期望为 'CHAR'", reason)

        # 白名单 Token 拦截
        valid, reason = AssetProtocolHelper.validate_id(
            "CHAR_STRANGER_T1_BASE_PORTRAIT", allowed_tokens={"LINWAN", "SHENMO"}
        )
        self.assertFalse(valid)
        self.assertIn("未在前期阶段白名单中锁定注册", reason)

    def test_resolve_dependency_dag(self):
        # 1. 基础肖像 -> T2I 无父级
        dep_base = AssetProtocolHelper.resolve_dependency("CHAR_LINWAN_T1_BASE_PORTRAIT")
        self.assertIsNone(dep_base.parent_asset_id)
        self.assertEqual(dep_base.generation_mode, "t2i")

        # 2. 基础服装 -> 派生自 BASE_PORTRAIT, i2i, 0.45
        dep_costume = AssetProtocolHelper.resolve_dependency("CHAR_LINWAN_T1_BASE_COSTUME")
        self.assertEqual(dep_costume.parent_asset_id, "CHAR_LINWAN_T1_BASE_PORTRAIT")
        self.assertEqual(dep_costume.generation_mode, "i2i")
        self.assertEqual(dep_costume.recommended_denoise, 0.45)

        # 3. 四视角 -> 派生自 BASE_COSTUME, controlnet, 0.40
        dep_4v = AssetProtocolHelper.resolve_dependency("CHAR_LINWAN_T2_4V_FRONT")
        self.assertEqual(dep_4v.parent_asset_id, "CHAR_LINWAN_T1_BASE_COSTUME")
        self.assertEqual(dep_4v.generation_mode, "controlnet")
        self.assertEqual(dep_4v.recommended_denoise, 0.40)

        # 4. 微表情 -> 派生自 BASE_PORTRAIT, inpaint, 0.40
        dep_exp = AssetProtocolHelper.resolve_dependency("CHAR_LINWAN_T2_EXP_FEAR")
        self.assertEqual(dep_exp.parent_asset_id, "CHAR_LINWAN_T1_BASE_PORTRAIT")
        self.assertEqual(dep_exp.generation_mode, "inpaint")

        # 5. 过肩景深背景 -> 派生自 WIDE, depth_blur, 0.30
        dep_ots = AssetProtocolHelper.resolve_dependency("ENV_OFFICE_T1_OTS_BG")
        self.assertEqual(dep_ots.parent_asset_id, "ENV_OFFICE_T1_WIDE")
        self.assertEqual(dep_ots.generation_mode, "depth_blur")

        # 6. 道具形变 -> 派生自 STATIC, inpaint, 0.50
        dep_action = AssetProtocolHelper.resolve_dependency("PROP_LETTER_T1_ACTION_DAMAGED")
        self.assertEqual(dep_action.parent_asset_id, "PROP_LETTER_T1_STATIC")
        self.assertEqual(dep_action.generation_mode, "inpaint")


if __name__ == "__main__":
    unittest.main()
