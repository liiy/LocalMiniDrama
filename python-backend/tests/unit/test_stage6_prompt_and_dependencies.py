"""测试阶段 6 提示词工程重构、多维特征扫描摘要与上游跨阶段依赖注入。

本测试套件覆盖：
1. STAGE6_SYSTEM_PROMPT 与 STAGE6_USER_PROMPT_TEMPLATE 模板与结构化字段验证
2. summarize_scanner_findings 确定性特征扫描编译与代词消解摘要生成
3. _stage6_fallback 注入 visual_style, aspect_ratio, audio_bible, episode_title 的正确性
4. stage6_asset_truth_node 完整执行流程与跨阶段 (阶段 1/4/5) 依赖抽取与输出挂载
"""
import json
import unittest

from app.schemas.script_graph_state import AssetState, IndustrialDramaMasterState
from app.tools.screenplay_feature_scanner import ScreenplayScanResult
from app.workflows.nodes.stage6_asset_truth import (
    _stage6_fallback,
    project_characters_for_stage6,
    project_environments_props_for_stage6,
    project_registry_index_for_stage6,
    stage6_asset_truth_node,
    summarize_scanner_findings,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE6_SYSTEM_PROMPT,
    STAGE6_USER_PROMPT_TEMPLATE,
)


class TestStage6PromptAndDependencies(unittest.TestCase):
    """测试阶段 6 提示词与上游依赖增强。"""

    def test_stage6_prompts_structure_and_constraints(self):
        """验证阶段 6 系统提示词核心规范与用户提示词模板字段完整性。"""
        # 1. 验证系统提示词核心规范与安全锚点
        self.assertIn("CoT · Step 1 ~ Step 5", STAGE6_SYSTEM_PROMPT)
        self.assertIn("Denoising Strength", STAGE6_SYSTEM_PROMPT)
        self.assertIn("--style raw", STAGE6_SYSTEM_PROMPT)
        self.assertIn(AssetState.APPROVED.value, STAGE6_SYSTEM_PROMPT)
        self.assertIn(AssetState.READY.value, STAGE6_SYSTEM_PROMPT)
        self.assertIn(AssetState.MODIFIED.value, STAGE6_SYSTEM_PROMPT)

        # 2. 验证用户提示词模板包含 11 个显式结构化字段，且格式化成功无缺漏
        rendered_user_prompt = STAGE6_USER_PROMPT_TEMPLATE.format(
            episode_num=1,
            episode_title="绝境突围：第七号仓库的秘密",
            aspect_ratio="9:16",
            visual_style="电影质感，冷调青橙，8k写实，侧逆光",
            target_video_engine="kling_1.6_high_fidelity",
            inter_episode_physical_snapshot_json="{}",
            screenplay_text="夜 内 7号仓库\n陆沉手持染血加密U盘，眼神警惕。",
            characters_engine_json="{}",
            environments_props_json="{}",
            existing_assets_registry_json="{}",
            scanner_pre_analysis_summary="[扫描命中角色] 陆沉",
        )
        self.assertIn("第 1 集", rendered_user_prompt)
        self.assertIn("绝境突围：第七号仓库的秘密", rendered_user_prompt)
        self.assertIn("9:16", rendered_user_prompt)
        self.assertIn("kling_1.6_high_fidelity", rendered_user_prompt)
        self.assertIn("[扫描命中角色] 陆沉", rendered_user_prompt)
        self.assertIn("电影质感，冷调青橙", rendered_user_prompt)

    def test_summarize_scanner_findings(self):
        """验证特征扫描器结果高密度摘要编译函数的鲁棒性与信息完整性。"""
        # 测试空扫描结果
        self.assertEqual(
            summarize_scanner_findings(None),
            "无显著预扫描线索。",
        )

        # 测试填充完整特征的扫描结果
        mock_result = ScreenplayScanResult(
            characters_detected=["陆沉", "顾夜寒"],
            character_alias_map={"男主": "陆沉", "顾夜寒": "顾夜寒"},
            coreference_resolutions=[
                {"pronoun": "他", "resolved_character": "顾夜寒", "line_idx": 0}
            ],
            scenes_detected=["7号仓库"],
            lighting_conditions=["冷调夜戏", "侧逆光"],
            props_detected=["染血加密U盘"],
            deformed_props={"染血加密U盘": ["被砸碎", "撕裂"]},
            injuries_detected={"陆沉": ["左额角渗血"]},
            macro_details={"陆沉": ["手部颤抖"]},
            emotions_detected={"陆沉": ["咬牙切齿"]},
        )

        summary = summarize_scanner_findings(mock_result)
        self.assertIn("登场角色: 陆沉(别名/简称: 男主), 顾夜寒", summary)
        self.assertIn('关键代词共指消解: "他" -> 顾夜寒 (第1行)', summary)
        self.assertIn("涉及场景空间: 7号仓库", summary)
        self.assertIn("光影明暗氛围特征: 冷调夜戏, 侧逆光", summary)
        self.assertIn("触碰交互道具: 染血加密U盘", summary)
        self.assertIn("命中破坏形变铁律的核心道具", summary)
        self.assertIn("染血加密U盘(命中破坏动词: 被砸碎, 撕裂)", summary)
        self.assertIn("角色战损/负伤状态", summary)
        self.assertIn("陆沉: 左额角渗血", summary)
        self.assertIn("生理/手部微距线索: 陆沉: 手部颤抖", summary)
        self.assertIn("情绪特写触发: 陆沉: 咬牙切齿", summary)

    def test_stage6_fallback_with_visual_style_and_audio(self):
        """验证 _stage6_fallback 正确注入视觉风格、画幅、单集标题及声音动机。"""
        script = {
            "episode_num": 2,
            "title": "反戈一击",
            "screenplay_text": "陆沉在暴雨中拔枪。",
            "characters_present": ["陆沉"],
            "scenes": ["7号仓库"],
            "props": ["染血加密U盘"],
        }
        chars_engine = {
            "characters": [
                {
                    "character_id": "CHAR_LUCHEN",
                    "character_token": "LUCHEN",
                    "name": "陆沉",
                    "appearance": "冷峻短发，黑色风衣",
                }
            ]
        }
        envs_props = {
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
        }
        fallback_res = _stage6_fallback(
            episode_num=2,
            script_data=script,
            characters_engine=chars_engine,
            envs_props=envs_props,
            existing_registry={},
            scanner_result=None,
            visual_style="赛博朋克霓虹暗黑风，8k超清，电影级调色",
            aspect_ratio="16:9",
            episode_title="反戈一击",
        )

        manifest = fallback_res["episode_resource_manifest"]
        self.assertEqual(manifest["episode_title"], "反戈一击")
        self.assertEqual(manifest["aspect_ratio"], "16:9")

        # 验证提示词注入了视觉风格
        char_assets = manifest["character_assets"]
        self.assertTrue(len(char_assets) > 0)
        portrait_asset = char_assets[0]
        self.assertIn("赛博朋克霓虹暗黑风", portrait_asset["prompt"])

        # 验证声音母音卡正常输出且不冗余生成 audio_assets
        self.assertNotIn("audio_assets", manifest)
        self.assertTrue(len(fallback_res.get("new_character_master_voice_cards", [])) >= 1)

    def test_stage6_asset_truth_node_end_to_end_dependencies(self):
        """测试 stage6_asset_truth_node 完整节点执行时的跨阶段依赖装配。"""
        state = IndustrialDramaMasterState(
            drama_id=888,
            current_visual_episode=1,
            aspect_ratio="9:16",
            visual_style="新中式悬疑冷感，8k写实，柔和漫射光",
            target_video_engine="hunyuan_video_1.5",
            audio_bible={
                "bgm_motifs": [
                    {
                        "motif_name": "命运对弈",
                        "theme": "重低音合成器与钢琴交错",
                        "mood": "悬疑破局",
                    }
                ]
            },
            season_outlines={
                1: {
                    "episode_num": 1,
                    "title": "雨夜惊魂",
                    "killer_title": "雨夜惊魂：致命录像带",
                }
            },
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "雨夜惊魂",
                    "scene_header": "夜 内 密室",
                    "characters_present": ["沈听澜"],
                    "core_props": ["残破录像带"],
                    "screenplay_text": "夜 内 密室\n沈听澜撕开染血胶带，手中紧握残破录像带。他的左手掌心被玻璃划伤渗血。",
                }
            },
            characters_engine={
                "characters": [
                    {
                        "character_id": "CHAR_SHENTINGLAN",
                        "character_token": "SHENTINGLAN",
                        "name": "沈听澜",
                        "appearance": "金丝眼镜，神色沉静苍白",
                    }
                ]
            },
            environments_and_props={
                "environments": [
                    {
                        "environment_id": "ENV_MISHI",
                        "scene_token": "MISHI",
                        "location_name": "密室",
                    }
                ],
                "props": [
                    {
                        "prop_id": "PROP_CANPOLUXIANGDAI",
                        "prop_token": "CANPOLUXIANGDAI",
                        "name": "残破录像带",
                    }
                ],
            },
        )

        res = stage6_asset_truth_node(state)

        # 验证返回基本属性
        self.assertEqual(res["current_stage"], 6)
        self.assertEqual(res["episode_num"], 1)
        self.assertEqual(res["episode_title"], "雨夜惊魂")

        # 验证生成的清单中包含画幅、标题和角色母音卡
        manifests = res["episode_resource_manifests"]
        manifest = manifests[1]
        self.assertEqual(manifest.aspect_ratio, "9:16")
        self.assertEqual(manifest.episode_title, "雨夜惊魂")
        self.assertIn("VOICE_SHENTINGLAN_T1_MASTER", manifest.all_asset_ids)

    def test_context_projectors_field_pruning(self):
        """验证阶段 6 专用投影过滤器剥离非视听文学心理、长篇剧情背景与哈希表的正确性。"""
        # 1. 角色视听投影验证
        chars_engine = {
            "characters": [
                {
                    "character_id": "CHAR_LUCHEN",
                    "name": "陆沉",
                    "role_type": "冷峻男主",
                    "appearance": "消瘦冷酷，高颧骨",
                    "biological_dna": {
                        "bone_structure": "高颧骨硬朗下颌",
                        "skin_micro_texture": "粗糙毛孔",
                        "blemishes_and_scars": "眉骨两毫米旧疤痕",
                    },
                    "lived_in_costume": {
                        "top_wear": "炭灰色粗花呢大衣",
                        "footwear": "磨损鞋头黑色短靴",
                    },
                    "acoustic_persona": {
                        "vocal_position": "胸腔深层共鸣",
                        "vocal_flaws": "气泡音颗粒感",
                    },
                    "voice_fingerprint": {
                        "catchphrase": "说话要有凭据。",
                    },
                    # 应该被剥离的阶段 2 文学心理字段
                    "psychology_4": {"ego": "极度偏执", "superego": "内疚自毁"},
                    "the_ghost": "十年前目睹父亲跳楼，从此对雨夜有心理创伤",
                    "fatal_flaw": "不相信任何人",
                    "relationship_matrix": {"顾夜寒": "宿敌", "林晚": "互相利用"},
                    "character_arc": "第一阶段：封闭冷漠 -> 第二阶段：开始动摇",
                    "secret_motivation": "拿到当年化工厂改制贪腐名单",
                },
                {
                    "character_id": "CHAR_LINWAN",
                    "name": "林晚",
                    "role_type": "神秘女主",
                    "appearance": "长发微卷，风衣",
                    "psychology_4": {"ego": "防御"},
                },
            ]
        }

        # 仅陆沉出场
        projected_chars = project_characters_for_stage6(chars_engine, present_names=["陆沉"])
        self.assertEqual(len(projected_chars), 1)
        luc_proj = projected_chars[0]
        self.assertEqual(luc_proj["character_id"], "CHAR_LUCHEN")
        self.assertEqual(luc_proj["name"], "陆沉")
        self.assertIn("biological_dna", luc_proj)
        self.assertIn("lived_in_costume", luc_proj)
        self.assertIn("acoustic_persona", luc_proj)
        self.assertIn("voice_fingerprint", luc_proj)

        # 严格验证文学心理与关系网被剔除
        self.assertNotIn("psychology_4", luc_proj)
        self.assertNotIn("the_ghost", luc_proj)
        self.assertNotIn("fatal_flaw", luc_proj)
        self.assertNotIn("relationship_matrix", luc_proj)
        self.assertNotIn("character_arc", luc_proj)
        self.assertNotIn("secret_motivation", luc_proj)

        # 2. 空间与道具投影验证
        envs_props = {
            "environments": [
                {
                    "env_id": "ENV_WAREHOUSE",
                    "location_name": "7号废弃仓库",
                    "weathering_layers": "锈蚀工字钢与积水反光",
                    "visual_prompt": "cinematic abandoned warehouse...",
                    "atmosphere": "冷调阴郁",
                    # 应该被剥离的故事背景字段
                    "narrative_function": "主角与反派首次生死对决之地",
                    "backstory": "建于1985年，因特大火灾废弃至今三十年",
                }
            ],
            "props": [
                {
                    "prop_id": "PROP_USB",
                    "name": "加密U盘",
                    "tier": "hero_item",
                    "damage_scale": "表面刮痕与磨损金属角",
                    "foley_resistance": "+3dB 金属干脆插拔声",
                    "visual_prompt": "cinematic macro shot of weathered USB...",
                    # 应该被剥离的叙事寓意字段
                    "symbolic_meaning": "象征着被掩埋的真相与权钱交易",
                    "plot_importance": "决定第15集剧情大反转的关键物证",
                }
            ],
        }

        projected_ep = project_environments_props_for_stage6(envs_props, present_scenes=["7号废弃仓库"], present_props=["加密U盘"])
        proj_envs = projected_ep["environments"]
        proj_props = projected_ep["props"]
        self.assertEqual(len(proj_envs), 1)
        self.assertEqual(len(proj_props), 1)
        self.assertIn("weathering_layers", proj_envs[0])
        self.assertNotIn("narrative_function", proj_envs[0])
        self.assertNotIn("backstory", proj_envs[0])
        self.assertIn("damage_scale", proj_props[0])
        self.assertNotIn("symbolic_meaning", proj_props[0])
        self.assertNotIn("plot_importance", proj_props[0])

        # 3. 全剧真理源总库投影为 ID 索引表
        registry = {
            "characters": {
                "CHAR_LUCHEN_T1_BASE_PORTRAIT": {
                    "name": "陆沉",
                    "tier": "T1",
                    "type": "character_base_identity",
                    "lifecycle_status": "APPROVED",
                    "visual_prompt": "cinematic photorealistic 8k portrait masterpiece of Lu Chen with extreme details...",
                    "workflow_note": "基础人脸锁定",
                    "semantic_hash": "a1b2c3d4e5f67890",
                }
            },
            "environments": {
                "ENV_WAREHOUSE_T1_WIDE": {
                    "location_name": "7号仓库",
                    "tier": "T1",
                    "visual_prompt": "extremely long prompt describing every corner of the abandoned warehouse...",
                    "lifecycle_status": "APPROVED",
                }
            },
            "props": {
                "PROP_USB_T1_STATIC": {
                    "name": "加密U盘",
                    "tier": "T1",
                    "visual_prompt": "macro close-up of usb drive...",
                    "lifecycle_status": "APPROVED",
                }
            },
            # 内部大哈希表和历史记录，严禁传给 LLM
            "semantic_hashes": {"CHAR_LUCHEN_T1_BASE_PORTRAIT": "a1b2c3d4e5f67890"},
            "hash_index": {"a1b2c3d4e5f67890": "CHAR_LUCHEN_T1_BASE_PORTRAIT"},
            "reused_assets_history": {1: ["CHAR_LUCHEN_T1_BASE_PORTRAIT"]},
        }
        reg_index = project_registry_index_for_stage6(registry)
        self.assertIn("characters", reg_index)
        self.assertIn("environments", reg_index)
        self.assertIn("props", reg_index)
        self.assertNotIn("semantic_hashes", reg_index)
        self.assertNotIn("hash_index", reg_index)
        self.assertNotIn("reused_assets_history", reg_index)
        # 验证角色索引为轻量结构
        char_item = reg_index["characters"]["CHAR_LUCHEN_T1_BASE_PORTRAIT"]
        self.assertEqual(char_item["name"], "陆沉")
        self.assertEqual(char_item["status"], "APPROVED")
        self.assertNotIn("visual_prompt", char_item)

    def test_stage6_prompt_compression_ratio(self):
        """量化验证上下文投影对字符量与 Token 权重的缩减率 (目标减重 > 60%)。"""
        # 构造高拟真度的上游全量上下文 (包含大量文学长文本与历史资产库)
        chars_engine = {
            "characters": [
                {
                    "character_id": f"CHAR_ROLE_{i:02d}",
                    "name": f"角色_{i:02d}",
                    "role_type": "主角或重要配角",
                    "appearance": f"人物外观_{i:02d}，神情坚毅冷峻",
                    "biological_dna": {
                        "bone_structure": "骨相与轮廓",
                        "skin_micro_texture": "皮肤肌理细节",
                    },
                    "lived_in_costume": {
                        "top_wear": "服饰上装代码",
                    },
                    "acoustic_persona": {
                        "vocal_position": "胸腔深层共鸣",
                    },
                    "psychology_4": {
                        "ego": "极度偏执与防御机制分析" * 5,
                        "superego": "内疚感与道德约束剖面分析" * 5,
                    },
                    "the_ghost": "二十年前一场大火夺走了所有家人的生命，从此对一切火光产生病态恐惧" * 10,
                    "relationship_matrix": {f"角色_{j:02d}": "复杂的爱恨交织与利益冲突关系" * 4 for j in range(5)},
                    "character_arc": "从最初的绝望报复，逐渐在救赎中走向释怀与自我牺牲" * 8,
                }
                for i in range(5)
            ]
        }

        envs_props = {
            "environments": [
                {
                    "env_id": f"ENV_SCENE_{i:02d}",
                    "location_name": f"场景_{i:02d}",
                    "weathering_layers": "锈蚀金属与尘土覆盖",
                    "visual_prompt": "cinematic moody environment" * 5,
                    "backstory": "历史久远的工业遗址，曾经发生过不为人知的秘密惨案" * 15,
                }
                for i in range(4)
            ],
            "props": [
                {
                    "prop_id": f"PROP_ITEM_{i:02d}",
                    "name": f"道具物证_{i:02d}",
                    "tier": "T1",
                    "damage_scale": "微观裂纹与氧化痕迹",
                    "symbolic_meaning": "作为真相最后的守护物，象征着不可磨灭的记忆" * 12,
                }
                for i in range(4)
            ],
        }

        # 模拟运行到第 5 集时的真理源累积库
        registry = {
            "characters": {
                f"CHAR_ROLE_{i:02d}_T1_BASE_PORTRAIT": {
                    "name": f"角色_{i:02d}",
                    "visual_prompt": "extremely long cinematic portrait prompt with intricate lighting and fabric details" * 10,
                    "workflow_note": "基准肖像锁定",
                    "semantic_hash": f"hash_char_{i:04d}",
                }
                for i in range(5)
            },
            "environments": {
                f"ENV_SCENE_{i:02d}_T1_WIDE": {
                    "location_name": f"场景_{i:02d}",
                    "visual_prompt": "extremely long wide angle lens architecture establishing shot" * 10,
                    "semantic_hash": f"hash_env_{i:04d}",
                }
                for i in range(4)
            },
            "semantic_hashes": {f"ASSET_{i:04d}": f"hash_{i:08d}" for i in range(30)},
            "hash_index": {f"hash_{i:08d}": f"ASSET_{i:04d}" for i in range(30)},
            "reused_assets_history": {ep: [f"ASSET_{j:04d}" for j in range(5)] for ep in range(1, 5)},
        }

        # 原始未过滤字符量
        raw_chars_str = json.dumps(chars_engine, ensure_ascii=False)
        raw_envs_str = json.dumps(envs_props, ensure_ascii=False)
        raw_reg_str = json.dumps(registry, ensure_ascii=False)
        raw_total_len = len(raw_chars_str) + len(raw_envs_str) + len(raw_reg_str)

        # 投影后字符量 (假设本集出场角色 2 个，场景 2 个，道具 2 个)
        proj_chars = project_characters_for_stage6(chars_engine, present_names=["角色_00", "角色_01"])
        proj_ep = project_environments_props_for_stage6(envs_props, present_scenes=["场景_00", "场景_01"], present_props=["道具物证_00", "道具物证_01"])
        proj_reg = project_registry_index_for_stage6(registry)

        proj_total_len = (
            len(json.dumps(proj_chars, ensure_ascii=False, indent=2))
            + len(json.dumps(proj_ep, ensure_ascii=False, indent=2))
            + len(json.dumps(proj_reg, ensure_ascii=False, indent=2))
        )

        compression_ratio = (raw_total_len - proj_total_len) / raw_total_len
        print(f"\n[压缩基准评测] 原始上下文: {raw_total_len} 字符 -> 投影后上下文: {proj_total_len} 字符 (压缩率: {compression_ratio*100:.1f}%)")

        # 验证缩减率 > 60%
        self.assertGreater(compression_ratio, 0.60)


if __name__ == "__main__":
    unittest.main()
