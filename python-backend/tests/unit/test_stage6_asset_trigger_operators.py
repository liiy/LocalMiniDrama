# -*- coding: utf-8 -*-
"""阶段 6 多级资产触发与派生算子引擎测试 (Character/Environment/Prop Trigger Operators)。"""

import unittest
from app.workflows.operators.asset_trigger_operator_engine import AssetTriggerOperatorEngine


class TestAssetTriggerOperatorEngine(unittest.TestCase):
    """测试确定性算子引擎对【A/B/C 规则算子】的精确裁决。"""

    def test_character_trigger_operators_selective_derivation(self):
        """验证角色触发算子：按需触发视角、情绪、光感与手部微距，未出现的绝不生成。"""
        # 测试场景：仅正面直视与握紧打火机（手部动作），无转头、无背影、无负伤
        semantic_data = {
            "character_name": "沈炼",
            "in_screenplay_evidence": "沈炼迎面走来，右手握住银质打火机，眼神冰冷",
            "gaze_orientations": ["front"],
            "emotion_cues": ["suppressed"],
            "lighting_conditions": [],
            "has_macro_hand": True,
            "injuries": [],
        }

        screenplay_snippet = "沈炼迎面走来，右手握住打火机，眼神冰冷看着众人。"
        assets = AssetTriggerOperatorEngine.evaluate_character_assets(
            character_name="沈炼",
            canonical_id="CHAR_SHENLIAN",
            semantic_data=semantic_data,
            screenplay_text=screenplay_snippet,
        )

        asset_keys = [a["asset_key"] for a in assets]
        # 1. 必有标准 T1_BASE_PORTRAIT
        self.assertIn("CHAR_SHENLIAN_T1_BASE_PORTRAIT", asset_keys)
        # 2. 命中正面直视 -> 必有 T1_4V_FRONT_FULL
        self.assertIn("CHAR_SHENLIAN_T1_4V_FRONT_FULL", asset_keys)
        # 3. 命中 suppressed 情绪 -> 必有 T2_EXP_SUPPRESSED
        self.assertIn("CHAR_SHENLIAN_T2_EXP_SUPPRESSED", asset_keys)
        # 4. 命中手部动作 -> 必有 T3_MACRO_HAND
        self.assertIn("CHAR_SHENLIAN_T3_MACRO_HAND", asset_keys)

        # 5. 坚决不产生未触发的视角、情绪、光效与负伤
        self.assertNotIn("CHAR_SHENLIAN_T2_4V_PROFILE", asset_keys)
        self.assertNotIn("CHAR_SHENLIAN_T2_4V_3Q", asset_keys)
        self.assertNotIn("CHAR_SHENLIAN_T2_4V_BACK", asset_keys)
        self.assertNotIn("CHAR_SHENLIAN_T2_EXP_RAGE", asset_keys)
        self.assertNotIn("CHAR_SHENLIAN_T2_LIGHT_FLASH", asset_keys)
        self.assertNotIn("CHAR_SHENLIAN_T3_STATUS_INJURED", asset_keys)

        # 6. 【阶梯血统 DAG 拓扑断言】
        asset_map = {a["asset_key"]: a for a in assets}
        # T1_BASE_PORTRAIT 必须为文生图根节点 (parent=None, is_benchmark=1)
        self.assertIsNone(asset_map["CHAR_SHENLIAN_T1_BASE_PORTRAIT"]["parent_asset_key"])
        self.assertEqual(asset_map["CHAR_SHENLIAN_T1_BASE_PORTRAIT"]["generation_mode"], "t2i")
        self.assertEqual(asset_map["CHAR_SHENLIAN_T1_BASE_PORTRAIT"]["is_benchmark"], 1)

        # T1_4V_FRONT_FULL 正面全身立绘挂靠在 T1_BASE_PORTRAIT 上作为 FaceID 注入源 (ControlNet OpenPose 强约束)
        self.assertEqual(asset_map["CHAR_SHENLIAN_T1_4V_FRONT_FULL"]["parent_asset_key"], "CHAR_SHENLIAN_T1_BASE_PORTRAIT")
        self.assertEqual(asset_map["CHAR_SHENLIAN_T1_4V_FRONT_FULL"]["control_type"], "controlnet_openpose")
        self.assertEqual(asset_map["CHAR_SHENLIAN_T1_4V_FRONT_FULL"]["identity_reference"], "CHAR_SHENLIAN_T1_BASE_PORTRAIT")

        # T2_EXP_SUPPRESSED 微表情局部重绘挂靠在 T1_BASE_PORTRAIT 纯面部基准
        self.assertEqual(asset_map["CHAR_SHENLIAN_T2_EXP_SUPPRESSED"]["parent_asset_key"], "CHAR_SHENLIAN_T1_BASE_PORTRAIT")
        self.assertEqual(asset_map["CHAR_SHENLIAN_T2_EXP_SUPPRESSED"]["generation_mode"], "inpaint")
        self.assertEqual(asset_map["CHAR_SHENLIAN_T2_EXP_SUPPRESSED"]["control_type"], "inpaint_face_mask")

        # T3_MACRO_HAND 手部特写挂靠在正面全身立绘 T1_4V_FRONT_FULL
        self.assertEqual(asset_map["CHAR_SHENLIAN_T3_MACRO_HAND"]["parent_asset_key"], "CHAR_SHENLIAN_T1_4V_FRONT_FULL")
        self.assertEqual(asset_map["CHAR_SHENLIAN_T3_MACRO_HAND"]["generation_mode"], "inpaint")
        self.assertEqual(asset_map["CHAR_SHENLIAN_T3_MACRO_HAND"]["control_type"], "inpaint_body_mask")

    def test_character_trigger_operators_profile_back_and_injured(self):
        """验证角色触发算子：侧脸、背影、强光直射与战损流血触发。"""
        semantic_data = {
            "character_name": "陆沉",
            "in_screenplay_evidence": "陆沉侧脸避开目光，左臂刀伤流血不止，强光照脸，随后转身离去",
            "gaze_orientations": ["profile", "back"],
            "emotion_cues": ["rage"],
            "lighting_conditions": ["flash_light"],
            "has_macro_hand": False,
            "injuries": ["left_arm_cut_bleeding"],
        }
        assets = AssetTriggerOperatorEngine.evaluate_character_assets(
            character_name="陆沉",
            canonical_id="CHAR_LUCHEN",
            semantic_data=semantic_data,
            screenplay_text="陆沉侧脸避开目光，手电筒强光照脸，左臂鲜血流淌，随后决绝转身离去",
        )
        asset_keys = [a["asset_key"] for a in assets]
        self.assertIn("CHAR_LUCHEN_T2_4V_PROFILE", asset_keys)
        self.assertIn("CHAR_LUCHEN_T2_4V_BACK", asset_keys)
        self.assertIn("CHAR_LUCHEN_T2_EXP_RAGE", asset_keys)
        self.assertIn("CHAR_LUCHEN_T2_LIGHT_FLASH", asset_keys)
        self.assertIn("CHAR_LUCHEN_T3_STATUS_INJURED", asset_keys)
        # 未触发 front 与 3q
        self.assertNotIn("CHAR_LUCHEN_T1_4V_FRONT_FULL", asset_keys)
        self.assertNotIn("CHAR_LUCHEN_T2_4V_3Q", asset_keys)

        # 【阶梯血统 DAG 平滑降级断言】：在未触发 4V_FRONT_FULL 时，侧脸与背影安全平滑降级挂靠至 T1_BASE_PORTRAIT
        asset_map = {a["asset_key"]: a for a in assets}
        self.assertEqual(asset_map["CHAR_LUCHEN_T2_4V_PROFILE"]["parent_asset_key"], "CHAR_LUCHEN_T1_BASE_PORTRAIT")
        self.assertEqual(asset_map["CHAR_LUCHEN_T2_4V_PROFILE"]["generation_mode"], "i2i")
        self.assertEqual(asset_map["CHAR_LUCHEN_T2_4V_PROFILE"]["input_source_image"], "CHAR_LUCHEN_T1_BASE_PORTRAIT")

        self.assertEqual(asset_map["CHAR_LUCHEN_T2_4V_BACK"]["parent_asset_key"], "CHAR_LUCHEN_T1_BASE_PORTRAIT")
        self.assertEqual(asset_map["CHAR_LUCHEN_T2_4V_BACK"]["generation_mode"], "i2i")

        self.assertEqual(asset_map["CHAR_LUCHEN_T3_STATUS_INJURED"]["parent_asset_key"], "CHAR_LUCHEN_T1_BASE_PORTRAIT")
        self.assertEqual(asset_map["CHAR_LUCHEN_T3_STATUS_INJURED"]["generation_mode"], "inpaint")
        self.assertEqual(asset_map["CHAR_LUCHEN_T3_STATUS_INJURED"]["control_type"], "inpaint_body_mask")

    def test_environment_trigger_operators(self):
        """验证场景触发算子：全景建立图、过肩景深板(>=3句对白)、特写插镜与次要过场关键帧。"""
        # 1. 核心主场景，首句全景，对白 4 句，有水龙头特写
        sem_wide = {
            "scene_name": "7号仓库",
            "in_screenplay_evidence": "【场景1】夜 外 7号仓库全貌。狂风卷着暴雨...",
            "is_wide_establishing": True,
            "dialogue_count": 4,
            "insert_shots": ["水龙头滴水"],
            "is_minor_transitional_scene": False,
        }
        assets_wide = AssetTriggerOperatorEngine.evaluate_environment_assets(
            scene_name="7号仓库",
            canonical_id="ENV_CANGKU",
            semantic_data=sem_wide,
            screenplay_text="陆沉：谁？\n林浅：是我。\n陆沉：证据呢？\n林浅：在这里。",
        )
        keys_wide = [a["asset_key"] for a in assets_wide]
        self.assertIn("ENV_CANGKU_T1_WIDE", keys_wide)
        self.assertIn("ENV_CANGKU_T1_OTS_BG", keys_wide)
        self.assertTrue(any("INSERT" in k for k in keys_wide))

        # 2. 次要过场场景：仅生成 T2_KEYFRAME
        sem_minor = {
            "scene_name": "走廊暗角",
            "in_screenplay_evidence": "周正国快步穿过走廊暗角离去",
            "is_minor_transitional_scene": True,
        }
        assets_minor = AssetTriggerOperatorEngine.evaluate_environment_assets(
            scene_name="走廊暗角",
            canonical_id="ENV_ZHOULANG",
            semantic_data=sem_minor,
            screenplay_text="周正国快步穿过走廊暗角离去",
        )
        keys_minor = [a["asset_key"] for a in assets_minor]
        self.assertEqual(keys_minor, ["ENV_ZHOULANG_T2_KEYFRAME"])

    def test_prop_trigger_operators_and_tier_isolation(self):
        """验证道具算子：一级物证静态/破坏态判决、二级随身物绑定角色手部、三级杂物彻底剔除。"""
        # 1. 一级核心物证未被破坏 ➔ 仅 T1_STATIC
        res_static = AssetTriggerOperatorEngine.evaluate_prop_assets(
            prop_name="自杀结案卷宗",
            canonical_id="PROP_JUANZONG",
            semantic_data={
                "importance": "hero",
                "is_physically_damaged": False,
                "deformation_action": "周正国将卷宗紧紧按在胸前",
            },
            screenplay_text="周正国将卷宗按在胸前，脚步沉重。",
        )
        self.assertEqual(res_static["decision"], "HERO_PROP_GENERATED")
        keys_static = [a["asset_key"] for a in res_static["assets"]]
        self.assertIn("PROP_JUANZONG_T1_STATIC", keys_static)
        self.assertNotIn("PROP_JUANZONG_T1_ACTION", keys_static)

        # 2. 一级核心物证被破坏形变 ➔ 强制产出 STATIC 与 ACTION 双态
        res_damaged = AssetTriggerOperatorEngine.evaluate_prop_assets(
            prop_name="带血的牛皮纸信封",
            canonical_id="PROP_XINFENG",
            semantic_data={
                "importance": "hero",
                "is_physically_damaged": True,
                "deformation_action": "被一把暴力撕开，封蜡崩碎",
            },
            screenplay_text="信封被一把暴力撕开，暗红封蜡崩碎在地。",
        )
        self.assertEqual(res_damaged["decision"], "HERO_PROP_GENERATED")
        keys_damaged = [a["asset_key"] for a in res_damaged["assets"]]
        self.assertIn("PROP_XINFENG_T1_STATIC", keys_damaged)
        self.assertIn("PROP_XINFENG_T1_ACTION", keys_damaged)

        # 3. 二级随身私人物品 ➔ 零独立生图，挂靠角色手部特写
        res_personal = AssetTriggerOperatorEngine.evaluate_prop_assets(
            prop_name="纯银打火机",
            canonical_id="PROP_DAHUOJI",
            semantic_data={
                "importance": "personal",
                "associated_character": "沈炼",
                "is_physically_damaged": False,
            },
            screenplay_text="沈炼在手中反复把玩打火机",
        )
        self.assertEqual(res_personal["decision"], "BOUND_TO_CHARACTER_MACRO")
        self.assertEqual(res_personal["assets"], [])
        self.assertEqual(res_personal["bound_character"], "沈炼")

        # 4. 三级生活环境杂物 ➔ 零独立生图，坚决剔除
        res_ambient = AssetTriggerOperatorEngine.evaluate_prop_assets(
            prop_name="隔夜冷水饺",
            canonical_id="PROP_SHUIJIAO",
            semantic_data={
                "importance": "ambient",
                "is_physically_damaged": False,
            },
            screenplay_text="桌上摆着一盘吃剩的冷水饺",
        )
        self.assertEqual(res_ambient["decision"], "EXCLUDED_AMBIENT")
        self.assertEqual(res_ambient["assets"], [])


if __name__ == "__main__":
    unittest.main()
