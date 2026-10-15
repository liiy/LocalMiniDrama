"""阶段 6 零先验三步流水线专属单元测试套件。

覆盖验证：
1. 提示词零先验实体泄露断言 (Prompt 无 characters_engine / 无 scanner 实体名单);
2. 台词虚指角色抗幻读断言 (如仅在台词中提及“魏忠贤”，输出中绝对不包含);
3. 实体三级归一化漏斗与别名对齐断言 (老沈 -> 沈炼，锦衣卫沈大人 -> 沈炼);
4. 跨集跨次生成确定性四段式 ID 一致性断言;
5. 多形态自动派生状态机断言 (T1_BASE, T3_STATUS_INJURED, Z01_ZONE, S0_STATIC, S1_ACTION);
6. 本地规则矩阵生图提示词 Token 黄金优先级断言 (东亚/中国面孔, 80年代红砖筒子楼材质, 零 [visual_style] 占位符).
"""
import pytest
from unittest.mock import patch, MagicMock

from app.workflows.nodes.stage6_asset_truth import (
    AssetEntityNormalizer,
    MorphStateMachine,
    extract_pure_physical_environment_cues,
    stage6_asset_truth_node,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE6_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptMatrixSynthesizer
from app.tools.screenplay_feature_scanner import ScreenplayScanResult


def test_prompt_template_zero_prior_sanitization():
    """验证 Prompt 模板为原生 str，已彻底移除实体名单与先验资产库字段，仅暴露纯剧本与物理快照。"""
    assert isinstance(STAGE6_USER_PROMPT_TEMPLATE, str)
    formatted_prompt = STAGE6_USER_PROMPT_TEMPLATE.format(
        episode_num=1,
        episode_title="风雨客栈",
        aspect_ratio="9:16",
        visual_style="80年代写实胶片风",
        target_video_engine="kling",
        inter_episode_physical_snapshot_json="无",
        screenplay_text="沈炼握紧绣春刀，冷冷看着门口。",
    )

    # 1. 确保核心剧本与集数注入成功
    assert "风雨客栈" in formatted_prompt
    assert "沈炼握紧绣春刀，冷冷看着门口。" in formatted_prompt
    # 2. 确保模板正文中不再包含实体白名单先验字段标题
    assert "核心角色视觉白名单基准" not in formatted_prompt
    assert "空间与物证视觉白名单基准" not in formatted_prompt
    assert "本集可复用候选资产池" not in formatted_prompt


def test_extract_pure_physical_environment_cues_no_entities():
    """验证 extract_pure_physical_environment_cues 坚决不输出任何实体名称。"""
    mock_scan = ScreenplayScanResult(
        characters_detected=["沈炼", "魏忠贤", "卢剑星"],
        scenes_detected=["废弃客栈大堂"],
        props_detected=["绣春刀", "纯铜腰牌"],
        lighting_conditions=["冷调逆光", "昏暗烛火"],
    )

    cues = extract_pure_physical_environment_cues(mock_scan)

    # 光照线索必须保留
    assert "冷调逆光" in cues
    # 实体名单绝对不能泄漏给模型
    assert "魏忠贤" not in cues
    assert "沈炼" not in cues
    assert "废弃客栈大堂" not in cues
    assert "绣春刀" not in cues


def test_asset_entity_normalizer_three_levels():
    """验证实体三级归一化漏斗：L1 别名映射 -> L2 职衔清洗 -> L3 随身物反向嗅探。"""
    known_chars = {
        "CHAR_SHENLIAN_T1": {
            "name": "沈炼",
            "aliases": ["老沈", "老三"],
            "portable_props": ["绣春刀", "金疮药丸"],
        }
    }
    known_envs_props = {
        "environments": {
            "ENV_INNHALL_T1": {"name": "风雨客栈大堂", "aliases": ["客栈大堂"]}
        },
        "props": {
            "PROP_TOKEN_T1": {"name": "锦衣卫腰牌", "aliases": ["纯铜腰牌"]}
        }
    }
    mock_scan = ScreenplayScanResult(
        character_alias_map={"老沈": "沈炼"},
    )

    normalizer = AssetEntityNormalizer(known_chars, known_envs_props, mock_scan)

    # Level 1: 扫描器/库内别名查表精确命中
    std_name, exists, prof = normalizer.normalize_character_name("老沈")
    assert std_name == "沈炼"
    assert exists is True
    assert prof["name"] == "沈炼"

    # Level 2: 职衔前缀正则清洗 ("锦衣卫沈大人" -> "沈炼")
    std_name2, exists2, prof2 = normalizer.normalize_character_name("锦衣卫沈大人")
    assert std_name2 == "沈炼"
    assert exists2 is True

    # Level 3: 随身物品反向嗅探 (通用道具"金疮药丸"结合沈炼反向锁定)
    p_name, p_exists, _ = normalizer.normalize_prop_name("金疮药丸", associated_char_name="老沈")
    assert p_name == "金疮药丸"
    assert p_exists is True

    # 新实体判定 (数据库未登记的刺客头领)
    new_name, new_exists, _ = normalizer.normalize_character_name("黑衣神秘刺客")
    assert new_name == "黑衣神秘刺客"
    assert new_exists is False


def test_deterministic_id_generation_consistency():
    """验证确定性 ID 生成器跨集跨次生成 100% 字节一致。"""
    id_run1 = AssetProtocolHelper.generate_deterministic_id("CHAR", "沈炼", "T1_BASE")
    id_run2 = AssetProtocolHelper.generate_deterministic_id("CHAR", "沈炼", "T1_BASE")
    assert id_run1 == id_run2
    assert id_run1.startswith("CHAR_")
    assert "T1_BASE" in id_run1

    injured_id1 = AssetProtocolHelper.generate_deterministic_id("CHAR", "沈炼", "T3_STATUS_INJURED")
    injured_id2 = AssetProtocolHelper.generate_deterministic_id("CHAR", "沈炼", "T3_STATUS_INJURED")
    assert injured_id1 == injured_id2
    assert "T3_STATUS_INJURED" in injured_id1

    zone_id = AssetProtocolHelper.generate_deterministic_id("ENV", "红星轧钢厂筒子楼", "Z01_ZONE")
    assert zone_id.startswith("ENV_")
    assert "Z01_ZONE" in zone_id

    prop_s0 = AssetProtocolHelper.generate_deterministic_id("PROP", "纯铜腰牌", "S0_STATIC")
    prop_s1 = AssetProtocolHelper.generate_deterministic_id("PROP", "纯铜腰牌", "S1_ACTION")
    assert prop_s0 != prop_s1
    assert "STATIC" in prop_s0
    assert "ACTION" in prop_s1


def test_morph_state_machine_derivation():
    """验证剧情语义多形态派生状态机。"""
    motion_slice = {
        "current_motion": "警惕四周，左手按住刀柄",
        "physical_wounds": "左臂被刀划伤，渗出暗红血渍",
        "emotional_expression": "眼神冷冽咬牙",
    }

    morphs = MorphStateMachine.derive_character_morphs(
        char_name="沈炼",
        motion_slice=motion_slice,
        is_existing=False,
    )

    form_names = [m["form"] for m in morphs]
    # 必须派生基础立绘 T1_BASE
    assert "T1_BASE" in form_names
    # 命中伤情必须派生 T3_STATUS_INJURED
    assert "T3_STATUS_INJURED" in form_names
    # 命中手部按刀动作必须派生 T3_MACRO_HAND
    assert "T3_MACRO_HAND" in form_names


def test_prompt_matrix_synthesizer_token_priority_and_no_placeholder():
    """验证本地规则矩阵生图提示词合成引擎：
    1. Slot 0 锁定东亚/中国人面孔 (黄金前排);
    2. Slot 1 具象解构 80 年代中国建筑与红砖筒子楼;
    3. 彻底消除 [visual_style] 占位符.
    """
    # 1. 角色提示词生成 (中国人防漂移)
    char_prompt = PromptMatrixSynthesizer.assemble_character_prompt(
        name="沈炼",
        form="T1_BASE",
        motion_slice={"current_motion": "站立警惕", "physical_wounds": "无", "emotional_expression": "目光如炬"},
        char_profile={"gender": "male", "ethnicity": "chinese", "appearance": "身穿飞鱼服"},
        visual_style="visual style: [visual_style], 80年代复古胶片感",
    )

    # 黄金前排必须锁定中国/东亚面孔
    assert "Authentic East Asian Chinese face" in char_prompt[:60]
    # 绝不能有任何未展开占位符
    assert "[visual_style]" not in char_prompt
    assert "visual style:" not in char_prompt
    assert "85mm portrait photography" in char_prompt

    # 2. 80年代中国建筑场景提示词生成
    env_prompt = PromptMatrixSynthesizer.assemble_environment_prompt(
        name="红星家属区筒子楼",
        form="Z01_ZONE",
        env_slice={"sub_zone_spot": "二楼外挂水泥楼梯拐角", "scene_traces": "地面积水倒灌泥泞"},
        visual_style="1980年代中国重工业现实主义风格",
    )

    # 时代建筑具象解构锁定
    assert "1980s mainland China" in env_prompt
    assert "red-brick residential dormitory building (筒子楼)" in env_prompt
    assert "peeling green paint" in env_prompt
    assert "[visual_style]" not in env_prompt
    assert "50mm medium lens" in env_prompt
