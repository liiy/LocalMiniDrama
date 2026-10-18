"""阶段 6 增量差集识别与三级推断专项测试 (Stage 6 Entity Diff & 3-Tier Resolution Tests)。

验证范围：
1. _build_stage2_character_dossier 的三级渐进式性别与年龄推断：
   - Tier 1: 大模型显式提供 gender 与 perceived_age；
   - Tier 2: 大模型未提供时，通过剧本上下文代词反查（她/他）；
   - Tier 3: 上下文缺乏代词时，委托 GenrePack 题材包推断（仙侠/都市/通用）。
2. Step 5 增量实体识别逻辑：
   - 大模型 output 中已剔除 newly_discovered_*，仅输出 characters/environments/props；
   - Step 5 通过与 Stage 2/3 白名单做集合差集，成功提取并登记新角色、新场景、新道具；
   - 提取的新档案完整回填大模型特征与视觉描述。
3. Step 7 汇聚与向下传递通道：
   - ctx.dossier_new_chars / ctx.dossier_new_scenes / ctx.dossier_new_props 规范落入 manifest 与 StageResult。
"""
from __future__ import annotations

import pytest
from app.workflows.nodes.stage6.dossier_builders import _build_stage2_character_dossier
from app.workflows.nodes.stage6.genre_packs import get_genre_pack
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.step5_dossier import IncrementalDossierStep
from app.workflows.nodes.stage6.steps.step7_converge import LineageConvergenceStep


def test_3tier_gender_age_resolution_tier1():
    """验证 Tier 1：大模型显式提供 gender 与 perceived_age 优先使用。"""
    dossier = _build_stage2_character_dossier(
        char_name="李云",
        episode_num=1,
        screenplay_text="李云快步走来，神色凝重。",
        explicit_gender="female",
        explicit_age=26,
    )
    assert dossier["gender"] == "female"
    assert dossier["perceived_age"] == 26
    assert dossier["name"] == "李云"
    assert dossier["character_code"] == "CHAR_LIYUN"


def test_3tier_gender_age_resolution_tier2_pronoun():
    """验证 Tier 2：大模型未传性别年龄，从剧本上下文代词反查。"""
    script_context = "走廊尽头，苏晴默默站着。她手里攥着一份文件，眼眶微红，她深吸了一口气。"
    dossier = _build_stage2_character_dossier(
        char_name="苏晴",
        episode_num=1,
        screenplay_text=script_context,
    )
    assert dossier["gender"] == "female"
    # 年龄未传时有安全兜底
    assert isinstance(dossier["perceived_age"], int)
    assert 18 <= dossier["perceived_age"] <= 60


def test_3tier_gender_age_resolution_tier3_genre_pack():
    """验证 Tier 3：上下文缺乏代词时，委托题材包判定。"""
    # 仙侠题材包测试
    xianxia_pack = get_genre_pack(drama_genre="仙侠修真")
    dossier_xx = _build_stage2_character_dossier(
        char_name="玄天圣女",
        episode_num=2,
        screenplay_text="虚空之中，玄天圣女现身。",
        genre_pack=xianxia_pack,
    )
    assert dossier_xx["gender"] == "female"

    # 都市言情题材包测试
    urban_pack = get_genre_pack(drama_genre="都市甜宠")
    dossier_ur = _build_stage2_character_dossier(
        char_name="陈学姐",
        episode_num=1,
        screenplay_text="操场边，陈学姐招手示意。",
        genre_pack=urban_pack,
    )
    assert dossier_ur["gender"] == "female"
    assert dossier_ur["perceived_age"] == 26


def test_step5_entity_diff_without_legacy_keys():
    """验证 Step 5：大模型输出纯净化（无 newly_discovered_*），通过差集识别新实体。"""
    ctx = Stage6StepContext()
    ctx.episode_num = 1
    ctx.episode_title = "第一集：试炼开始"
    ctx.screenplay_text = "林凡手握断剑，看向突然出现的神秘黑衣人老墨。四周是万丈深渊的葬剑崖。"

    # 已知实体清单（阶段 2/3 白名单）
    ctx.char_list = [{"character_id": "CHAR_LINFAN", "name": "林凡", "role": "protagonist"}]
    ctx.scene_list = [{"env_id": "ENV_SWORD_CLIFF", "name": "葬剑崖"}]
    ctx.prop_list = [{"prop_id": "PROP_BROKEN_SWORD", "name": "断剑"}]
    ctx.char_tokens = {"LINFAN"}
    ctx.scene_tokens = {"SWORDCLIFF"}
    ctx.prop_tokens = {"BROKENSWORD"}

    # 大模型返回纯净格式（绝对不含 newly_discovered_*）
    ctx.raw_llm_json = {
        "manifest": {
            "characters": [
                {"char_id": "CHAR_LINFAN", "name": "林凡", "visual_prompt": "少年剑客"},
                {
                    "name": "老墨",
                    "gender": "male",
                    "perceived_age": 48,
                    "visual_prompt": "面容枯槁的中年刺客，身披破旧斗篷",
                    "voice_style": "沙哑低沉",
                },
            ],
            "environments": [
                {"scene_id": "ENV_SWORD_CLIFF", "name": "葬剑崖", "visual_prompt": "绝壁深渊"},
                {"name": "迷雾密林", "visual_prompt": "浓雾弥漫的古树林，地面铺满腐殖落叶"},
            ],
            "props": [
                {"prop_id": "PROP_BROKEN_SWORD", "name": "断剑", "visual_prompt": "残破铁剑"},
                {"name": "青铜兽首令", "visual_prompt": "生满绿锈的青铜令牌，正面刻有穷奇兽面"},
            ],
        }
    }

    # 执行 Step 5 建档
    step5 = IncrementalDossierStep()
    step5.execute(ctx)

    # 断言：已从 characters/environments/props 中差集提取出未注册的新实体
    assert len(ctx.dossier_new_chars) == 1
    new_char = ctx.dossier_new_chars[0]
    assert new_char["name"] == "老墨"
    assert new_char["gender"] == "male"
    assert new_char["perceived_age"] == 48
    assert "面容枯槁" in new_char["visual_prompt"]

    assert len(ctx.dossier_new_scenes) == 1
    new_scene = ctx.dossier_new_scenes[0]
    assert new_scene["name"] == "迷雾密林"
    assert "浓雾弥漫" in new_scene["visual_prompt"]

    assert len(ctx.dossier_new_props) == 1
    new_prop = ctx.dossier_new_props[0]
    assert new_prop["name"] == "青铜兽首令"
    assert "青铜令牌" in new_prop["visual_prompt"]


def test_step7_convergence_preserves_new_entities():
    """验证 Step 7：汇聚步骤无损向下传递差集提取出的实体档案。"""
    ctx = Stage6StepContext()
    ctx.episode_num = 1
    ctx.episode_title = "第一集"
    ctx.screenplay_text = "正文"
    ctx.char_list = []
    ctx.scene_list = []
    ctx.prop_list = []
    ctx.raw_llm_json = {
        "newly_generated_assets": [],
        "reused_existing_assets": [],
        "new_character_master_voice_cards": [],
    }
    ctx.dossier_new_chars = [{"name": "老墨", "character_code": "CHAR_LAOMO"}]
    ctx.dossier_new_scenes = [{"name": "迷雾密林", "env_id": "ENV_MIWUMILIN"}]
    ctx.dossier_new_props = [{"name": "青铜兽首令", "prop_id": "PROP_QINGTONGSHOUSHOULING"}]

    step7 = LineageConvergenceStep()
    step7.execute(ctx)

    # 验证 manifest 和 output 均保存了差集识别的新实体
    assert ctx.manifest.newly_discovered_characters == ctx.dossier_new_chars
    assert ctx.manifest.newly_discovered_scenes == ctx.dossier_new_scenes
    assert ctx.manifest.newly_discovered_props == ctx.dossier_new_props
    assert ctx.output["newly_discovered_characters"] == ctx.dossier_new_chars
