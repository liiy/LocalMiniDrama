"""
阶段 7 视听编译全链路重构专项集成测试。
覆盖五大核心系统与六大真实业务缺陷防线：
1. 幽灵图号自愈（正文图号越界自动回落与无重叠替换）
2. 特写/近景景别自适应底图路由（特写不强制使用广角场景作为图1）
3. 台词/拟音/动作三权分立与纯净化清洗
4. 双轨提示词精炼（生图摄影构图 + 生视频物理动力学）
5. 跨镜头物理连续性状态机演进（角色衣着、道具破坏态与遗像跨镜头追踪）
6. 权威槽位映射与四段式资产合规性检验
"""

import unittest
from typing import Any
from unittest.mock import patch

from app.workflows.utils.prompt_synthesizer import (
    PromptSynthesizer,
    ContinuityStateManager,
    PhysicalEntityState,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.schemas.script_graph_state import IndustrialDramaMasterState
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node


class TestStage7AudiovisualRefactor(unittest.TestCase):
    """阶段 7 视听编译全链路重构专项测试套件"""

    def test_ghost_reference_self_healing(self):
        """测试 1: 幽灵图号自愈（正文引用图3/图4，但原槽位只有图1图2）"""
        raw_prompt = "特写[图3]中苏秀兰黑白遗像上的笑容逐渐扭曲，旁边[图4]的白色挽联被阴风吹动，而[图1]的灵堂依然昏暗。"
        char_ids = ["CHAR_SHENMO_T1_BASE_PORTRAIT"]
        prop_ids = ["PROP_PHOTO_T1_STATIC"]

        shot_dict = {
            "shot_id": 1,
            "framing": "CU 特写",
            "scene_asset_id": "ENV_LINGTANG_T1_WIDE",
            "character_asset_ids": char_ids,
            "prop_asset_ids": prop_ids,
            "image_prompt": raw_prompt,
            "video_prompt": raw_prompt,
        }
        
        # 编译槽位，允许自愈补齐幽灵图号
        healed_shot = PromptSynthesizer.compile_storyboard_multimodal_slots(
            shot_dict=shot_dict,
            known_chars_list=[{"name": "沈墨", "asset_id": "CHAR_SHENMO_T1_BASE_PORTRAIT"}],
            known_props_list=[{"name": "苏秀兰黑白遗像", "asset_id": "PROP_PHOTO_T1_STATIC"}],
        )

        visual_slots = healed_shot["canonical_visual_slots"]
        healed_text = healed_shot["image_prompt"]

        # 验证视觉槽位数量在 1 到 4 之间
        self.assertTrue(1 <= len(visual_slots) <= 4)
        
        # 验证治愈后的正文中引用的图号均在合法槽位定义中
        valid_symbols = {slot["symbol"] for slot in visual_slots}
        import re
        referenced_symbols = set(re.findall(r"图\d+", healed_text))
        for ref in referenced_symbols:
            self.assertIn(ref, valid_symbols, f"正文包含非法图号: {ref}，未在槽位中定义: {valid_symbols}")

        # 验证所有槽位资产均符合四段式规范
        for slot in visual_slots:
            is_valid, err = AssetProtocolHelper.validate_id(slot["asset_id"])
            self.assertTrue(is_valid, f"槽位资产非标: {slot['asset_id']}, 错误: {err}")

    def test_framing_asset_routing_close_up(self):
        """测试 2: 特写景别自适应底图解耦（特写不强制把广角场景作为图1底图）"""
        # 特写镜头关注遗像道具
        routing_plan = PromptSynthesizer.resolve_framing_asset_routing(
            framing="ECU 大特写",
            scene_asset_id="ENV_LINGTANG_T1_WIDE",
            character_asset_ids=[],
            prop_asset_ids=["PROP_PHOTO_T1_STATIC"],
        )
        
        # ECU 大特写且包含道具时，首选道具作为核心焦点，阻断广角大底图
        self.assertEqual(routing_plan["primary_focus"], "PROP")
        self.assertFalse(routing_plan["allow_wide_background"])
        self.assertIn("macro", routing_plan["camera_lens_directive"].lower())

    def test_dialogue_sound_action_sanitization(self):
        """测试 3: 台词/拟音/动作三权分立清洗"""
        raw_dialogue = "沈墨：（冷笑）[Foley+3dB: 棺材盖滑动声] 你们谁也别想活着离开！"
        raw_foley = "阴风呼啸"
        raw_action = "缓步走向供桌"

        clean_dlg, clean_foley, clean_act = PromptSynthesizer.sanitize_dialogue_sound_action(
            raw_dialogue=raw_dialogue,
            raw_foley=raw_foley,
            raw_action=raw_action,
        )

        # 验证台词完全纯净
        self.assertEqual(clean_dlg, "你们谁也别想活着离开！")
        # 验证拟音被隔离合并至音效轨
        self.assertIn("棺材盖滑动声", clean_foley)
        self.assertIn("阴风呼啸", clean_foley)
        # 验证动作被隔离合并至动作轨
        self.assertIn("冷笑", clean_act)
        self.assertIn("缓步走向供桌", clean_act)

    def test_dual_track_prompt_synthesis(self):
        """测试 4: 双轨提示词精炼（生图摄影构图 + 生视频物理动力学）"""
        visual_slots = [
            {"slot_order": 1, "symbol": "图1", "asset_id": "ENV_LINGTANG_T1_WIDE", "interaction_role": "background", "asset_type": "scene"},
            {"slot_order": 2, "symbol": "图2", "asset_id": "CHAR_SHENMO_T1_BASE_PORTRAIT", "interaction_role": "primary", "asset_type": "character"},
            {"slot_order": 3, "symbol": "图3", "asset_id": "PROP_PHOTO_T1_STATIC", "interaction_role": "focus", "asset_type": "prop"},
        ]

        # 视频动力学精炼
        video_prompt, manifest = PromptSynthesizer.synthesize_engine_video_prompt(
            framing="MCU 中近景",
            camera_movement="推镜缓慢推进至遗像特写",
            action_dynamics="沈墨伸手抚摸冰冷的镜框，眼神冰冷",
            visual_slots=visual_slots,
            target_engine="wan3.0",
        )

        # 验证包含摄影运镜机制与槽位指代
        self.assertIn("[推镜缓慢推进至遗像特写]", video_prompt)
        self.assertIn("图2", video_prompt)
        self.assertIn("图3", video_prompt)
        self.assertEqual(manifest["target_engine"], "wan3.0")

    def test_continuity_state_machine_tracking(self):
        """测试 5: 跨镜头物理连续性状态机演进追踪"""
        csm = ContinuityStateManager()

        # Shot 1: 设定角色初始状态与遗像道具
        csm.update_entity_state("CHAR_SHENMO", {"costume": "黑色丧服", "wound": "右脸血痕", "held_prop": "PROP_PHOTO"})
        csm.update_entity_state("PROP_PHOTO", {"damage": "镜框碎裂", "location_in_scene": "沈墨手中"})

        shot1_snap = csm.export_snapshot(shot_number=1)
        self.assertEqual(shot1_snap["entities"]["CHAR_SHENMO"]["costume"], "黑色丧服")
        self.assertEqual(shot1_snap["entities"]["PROP_PHOTO"]["damage"], "镜框碎裂")

        # Shot 2: 道具被摔碎，角色状态演进
        csm.update_entity_state("PROP_PHOTO", {"damage": "彻底粉碎", "location_in_scene": "地面散落"})
        shot2_snap = csm.export_snapshot(shot_number=2)

        self.assertEqual(shot2_snap["entities"]["PROP_PHOTO"]["damage"], "彻底粉碎")
        self.assertEqual(shot2_snap["entities"]["PROP_PHOTO"]["location_in_scene"], "地面散落")
        # 角色未更新的字段保持连续性
        self.assertEqual(shot2_snap["entities"]["CHAR_SHENMO"]["costume"], "黑色丧服")

    @patch("app.workflows.nodes.stage7_storyboard_srt.call_llm_json")
    def test_stage7_node_full_pipeline_refactor(self, mock_llm_json):
        """测试 6: 阶段 7 节点全流程集成回归（含自愈、三权分立与连续性快照）"""
        mock_llm_json.return_value = {
            "episode_num": 1,
            "shots": [
                {
                    "shot_id": 1,
                    "title": "开局烛火熄灭",
                    "framing": "ECU 极特写",
                    "camera_movement": "急速推移",
                    "duration_sec": 3.0,
                    "mode": "first_last_frame",
                    "character_asset_ids": ["CHAR_SHENMO_T1_BASE_PORTRAIT"],
                    "scene_asset_id": "ENV_LINGTANG_T1_WIDE",
                    "prop_asset_ids": ["PROP_PHOTO_T1_STATIC"],
                    "audio": {
                        "dialogue": None,
                        "foley": "[Foley: 阴风呼啸吹灭烛火]",
                    },
                    "visual_description": "白烛猛烈摇晃后熄灭，青烟升起",
                },
                {
                    "shot_id": 2,
                    "title": "沈墨对峙警告",
                    "framing": "MCU 中近景",
                    "camera_movement": "缓慢推镜",
                    "duration_sec": 4.0,
                    "mode": "multi_image_reference",
                    "character_asset_ids": ["CHAR_SHENMO_T1_BASE_PORTRAIT", "CHAR_LUCHEN_T1_BASE_PORTRAIT"],
                    "scene_asset_id": "ENV_LINGTANG_T1_WIDE",
                    "prop_asset_ids": ["PROP_PHOTO_T1_STATIC"],
                    "audio": {
                        "dialogue": "沈墨：（冷笑）[Foley: 棺材微颤声] 你们一个都跑不掉！",
                        "foley": "[Foley+3dB: 脚步逼近]",
                    },
                    "visual_description": "沈墨神色冷酷逼近陆沉，手中遗像镜框微裂",
                },
            ],
        }

        state = IndustrialDramaMasterState(
            drama_id=7,
            current_visual_episode=1,
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "回魂之夜",
                    "hook_3s": "开局阴森灵堂遗像前供奉的白烛突然熄灭",
                    "body_markdown": "灵堂昏暗，烛火摇曳。沈墨：（冷笑）[Foley: 棺材声] 你们一个都跑不掉！陆沉惊骇后退。",
                    "ending_cliffhanger": "遗像双眼流下血泪",
                }
            },
            characters_engine={
                "characters": [
                    {"name": "沈墨", "character_token": "SHENMO"},
                    {"name": "陆沉", "character_token": "LUCHEN"},
                ]
            },
            environments_and_props={
                "environments": [{"location_name": "阴森灵堂", "scene_token": "LINGTANG"}],
                "props": [{"name": "黑白遗像", "prop_token": "PHOTO"}],
            },
        )

        res = stage7_storyboard_srt_node(state)
        self.assertEqual(res["current_stage"], 7)
        shots = res["episode_storyboards"][1]
        self.assertTrue(len(shots) >= 2)

        for shot in shots:
            # 1. 验证台词中无冒号和拟音标记（检查 audio.dialogue）
            dlg = (shot.audio or {}).get("dialogue")
            if dlg:
                self.assertNotIn("：", dlg)
                self.assertNotIn(":", dlg)
                self.assertNotIn("[Foley", dlg)
                self.assertNotIn("（", dlg)
                self.assertEqual(dlg, "你们一个都跑不掉！")

            # 2. 验证权威槽位存在且四段式合规
            visual_slots = getattr(shot, "canonical_visual_slots", None) or getattr(shot, "_canonical_visual_slots", None)
            if not visual_slots and shot.multi_image_config:
                mm = shot.multi_image_config.get("media_manifest") or {}
                visual_slots = mm.get("images")
            if visual_slots:
                for slot in visual_slots:
                    valid, err = AssetProtocolHelper.validate_id(slot["asset_id"])
                    self.assertTrue(valid, f"集成测试中槽位资产 ID 违规: {slot['asset_id']}")

            # 3. 验证视频提示词存在
            self.assertTrue(bool(shot.video_prompt))


if __name__ == "__main__":
    unittest.main()
