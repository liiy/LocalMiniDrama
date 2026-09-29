"""单元测试：验证 Stage 1-8 各节点直接消费分层状态 (GlobalDramaMasterState 与 EpisodeScopedSubState)。

确保：
1. 阶段 1-4 纯文学节点直接以 GlobalDramaMasterState 作为入参运行，产出规范化增量并正确合并；
2. 阶段 5 既支持全局多集模式，也支持 EpisodeScopedSubState 单集模式；
3. 阶段 6-8 视听节点直接以 EpisodeScopedSubState 作为入参运行，不依赖臃肿旧 MasterState。
"""
from __future__ import annotations

import unittest
from typing import Any

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    InterEpisodePhysicalContinuity,
    SeasonOutlineCard,
)
from app.workflows.nodes.stage1_ideation import stage1_ideation_node
from app.workflows.nodes.stage2_character import stage2_character_node
from app.workflows.nodes.stage3_environment_prop import stage3_environment_prop_node
from app.workflows.nodes.stage4_outline import stage4_outline_node
from app.workflows.nodes.stage5_gatekeeper import stage5_literary_gatekeeper_node
from app.workflows.nodes.stage5_screenplay import stage5_screenplay_node
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node
from app.workflows.nodes.stage8_audio_mastering import stage8_audio_mastering_node


class TestNodesDirectLayeredState(unittest.TestCase):
    """测试 Stage 1-8 节点直接消费分层状态。"""

    def test_stage1_to_4_with_global_master_state(self):
        """验证 Stage 1-4 节点能直接入参 GlobalDramaMasterState 并返回合格状态字典。"""
        global_state = GlobalDramaMasterState(
            drama_id=888,
            title="破晓之战",
            logline="卧底探员在黑暗势力中绝地反杀",
            genre="悬疑/动作",
            total_episodes=5,
            target_episodes=5,
        )

        # 1. Stage 1
        res1 = stage1_ideation_node(global_state)
        self.assertEqual(res1["current_stage"], 1)
        self.assertIn("ideation_working_memory", res1)
        self.assertIn("forbidden_cliches_10", res1)
        self.assertIn("negative_rules", res1)

        # 模拟 LangGraph 状态增量合并
        for k, v in res1.items():
            if hasattr(global_state, k):
                setattr(global_state, k, v)

        # 2. Stage 2
        res2 = stage2_character_node(global_state)
        self.assertEqual(res2["current_stage"], 2)
        self.assertIn("character_working_memory", res2)
        self.assertIn("characters", res2)
        self.assertIn("relationship_matrix", res2)

        for k, v in res2.items():
            if hasattr(global_state, k):
                setattr(global_state, k, v)

        # 3. Stage 3
        res3 = stage3_environment_prop_node(global_state)
        self.assertEqual(res3["current_stage"], 3)
        self.assertIn("world_building_working_memory", res3)
        self.assertIn("environments_and_props", res3)

        for k, v in res3.items():
            if hasattr(global_state, k):
                setattr(global_state, k, v)

        # 4. Stage 4
        res4 = stage4_outline_node(global_state)
        self.assertEqual(res4["current_stage"], 4)
        self.assertIn("season_outline_working_memory", res4)
        self.assertIn("season_outlines", res4)
        self.assertIn("audio_bible", res4)

        for k, v in res4.items():
            if hasattr(global_state, k):
                setattr(global_state, k, v)

        self.assertTrue(len(global_state.season_outlines) >= 3)
        self.assertTrue(len(global_state.characters) >= 1)

    def test_stage5_with_episode_scoped_substate(self):
        """验证 Stage 5 节点能直接运行于 EpisodeScopedSubState 单集模式。"""
        substate = EpisodeScopedSubState(
            drama_id=888,
            episode_num=1,
            season_outline_card=SeasonOutlineCard(
                episode_num=1,
                title="暗流涌动",
                dramatic_arc="主角初入龙潭虎穴",
                hook_3s="枪声在暴雨中骤然撕裂黑夜",
                cliffhanger_45s="发现保险箱内竟是空箱",
                cliffhanger_115s="门锁自动落锁红外线启动",
                act_one="危机降临",
                act_two="深入侦查",
                act_three="陷入重围",
            ),
            incoming_continuity=InterEpisodePhysicalContinuity(
                episode_num=1,
                ending_scene=1,
                ending_shot=1,
                character_positions={"主角": "潜伏在走廊尽头"},
                lighting_continuity="阴冷暴雨月光",
                key_props_held=["静音手枪"],
                cliffhanger_context="暴雨初至",
            ),
        )

        res5 = stage5_screenplay_node(substate)
        self.assertEqual(res5["current_stage"], 5)
        self.assertEqual(res5["episode_number"], 1)
        self.assertIn("screenplay_text", res5)
        self.assertIn("completed_screenplays", res5)
        self.assertIn("outgoing_physical_continuity", res5)

    def test_stages_6_to_8_with_episode_scoped_substate(self):
        """验证 Stage 6-8 能直接在 EpisodeScopedSubState 上串联运行。"""
        substate = EpisodeScopedSubState(
            drama_id=888,
            episode_num=1,
            screenplay={
                "title": "第1集 暗流涌动",
                "text": "【场景 01】废弃船坞 - 夜 - 内\n暴雨狂暴敲击着生锈的铁皮屋顶。\n陆沉紧贴集装箱，双手紧握消音手枪。",
                "body_markdown": "【场景 01】废弃船坞 - 夜 - 内\n暴雨狂暴敲击着生锈的铁皮屋顶。\n陆沉紧贴集装箱，双手紧握消音手枪。",
            },
            season_outline_card=SeasonOutlineCard(
                episode_num=1,
                title="暗流涌动",
                hook_3s="枪声骤响",
                cliffhanger_45s="保险箱竟空无一物",
                cliffhanger_115s="红外警报启动",
            ),
        )

        # Stage 6
        res6 = stage6_asset_truth_node(substate)
        self.assertEqual(res6["current_stage"], 6)
        self.assertIn("episode_manifest", res6)
        manifest_val = res6["episode_manifest"]
        if isinstance(manifest_val, dict):
            substate.manifest = EpisodeResourceManifest.model_validate(manifest_val)
        else:
            substate.manifest = manifest_val

        # Stage 7
        res7 = stage7_storyboard_srt_node(substate)
        self.assertEqual(res7["current_stage"], 7)
        self.assertIn("storyboard_shots", res7)
        self.assertIn("srt_content", res7)
        substate.storyboard_shots = res7["storyboard_shots"]
        substate.srt_content = res7["srt_content"]

        # Stage 8
        res8 = stage8_audio_mastering_node(substate)
        self.assertEqual(res8["current_stage"], 8)
        self.assertIn("audio_mastering", res8)
        self.assertIn("outgoing_physical_continuity", res8)


if __name__ == "__main__":
    unittest.main()
