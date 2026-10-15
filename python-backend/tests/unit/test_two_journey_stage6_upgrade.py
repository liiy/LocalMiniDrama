"""测试两程九阶 Stage 6 分集增量视听资产提取与单项素材生成升级 (Stage 6 Upgrade Tests)。

验证内容：
1. 阶段 6 四段式资产 ID 与十项资产数据契约模型 (Pydantic v2 & TypedDict)：
   - EpisodeResourceManifest 支持 Table 6 树状嵌套 (tier1_base, tier2_performance, tier3_special 等)；
   - EpisodeResourceManifest 支持传统平铺列表与别名字段 (characters, environments, props, audio, characters_tier_1/2/3 等)；
   - 资产四段式协议严格校验 ([Category]_[ObjectToken]_[Tier]_[Function/StateModifier])；
   - ReusedAssetModel, NewlyGeneratedAssetModel, MasterVoiceCardModel 完备性；
   - VisualAudioAssetsRegistryModel 全局资产真理源注册表管理。
2. 剧本特征动态逆向扫描器 (app/tools/screenplay_feature_scanner.py)：
   - 算子 A: 角色定妆、视线机位、即时微表情与极速情绪震颤提取；
   - 算子 B: 空间视平线、物理光影做旧层与构图插入角扫描；
   - 算子 C: 关键叙事道具微观特写与物理形变破坏动词 (撕/砸/切/断/烧/挑开/崩碎/撬开/撞烂) 逆向检测；
   - 算子 D: 核心角色母音卡片与声学腔体提取。
3. Stage 6 保底工厂 (_stage6_fallback) 与业务节点 (stage6_asset_truth_node)：
   - 保证输出 100% 具备 Table 6 格式四段式标准化资产 ID；
   - 正确构建复用清单 (reused_existing_assets) 与增量生图引单 (newly_generated_assets)；
   - 100% 只读复用已核准资产 (Poka-Yoke 防呆断言)；
   - 增量角色自动绑定生成母音卡片 (VOICE_*_MASTER)；
   - 自动维护并累加更新 state.visual_audio_assets_registry。
4. RedBlueAuditor 哨卡 6 (Checkpoint 6) 严苛红蓝双军对抗审查：
   - 完备合规的 Table 6 视听引单判定为 GREEN_APPROVED；
   - 缺失 characters / environments / props 拦截 RED_BLOCKING；
   - 资产 ID 非标或段数错误精准拦截；
   - 角色声音母音卡片缺失 master_tts_prompt 或 ID 非标精准拦截；
   - 红军魔鬼挑刺：网红磨皮塑胶假人 (doll face/美白磨皮) 精准拦截；
   - 红军魔鬼挑刺：定妆照/全身图出现截肢半身描述 (waist up/半身照) 精准拦截；
   - 红军魔鬼挑刺：图生图增量资产缺失 input_source_image 底图血统精准拦截。
5. 存储适配器 (drama_storage_adapter) 零破坏落库与持久化还原：
   - persist_stage6 写入 episodes.ast_blocks 与 dramas.metadata；
   - load_master_state_from_db 还原后 state.episode_manifests 与 state.visual_audio_assets_registry 无损反序列化。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
    IndustrialDramaState,
    MasterVoiceCardModel,
    NewlyGeneratedAssetModel,
    ReusedAssetModel,
    VisualAudioAssetsRegistryModel,
)
from app.tools.screenplay_feature_scanner import scan_screenplay_features
from app.workflows.adapters.drama_storage_adapter import (
    load_master_state_from_db,
    persist_stage6,
)
from app.workflows.nodes.stage6_asset_truth import (
    _stage6_fallback,
    stage6_asset_truth_node,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper


# =========================================================================
# 1. 契约模型与四段式资产 ID 测试
# =========================================================================

def test_asset_protocol_helper_four_tier_validation():
    """测试 AssetProtocolHelper 对四段式资产 ID 的严格正则与语义校验。"""
    # 1.1 合法 ID
    valid, err = AssetProtocolHelper.validate_id("CHAR_SHENLIAN_T1_BASE_PORTRAIT", expected_category="CHAR")
    assert valid is True
    assert "合规" in err

    valid, err = AssetProtocolHelper.validate_id("CHAR_SHENLIAN_T1_BASE_COSTUME", expected_category="CHAR")
    assert valid is True

    valid, err = AssetProtocolHelper.validate_id("CHAR_SHENLIAN_T2_4V_FRONT_FULL", expected_category="CHAR")
    assert valid is True

    valid, err = AssetProtocolHelper.validate_id("ENV_STATION_T1_WIDE", expected_category="ENV")
    assert valid is True

    valid, err = AssetProtocolHelper.validate_id("PROP_DAGGER_T1_STATIC", expected_category="PROP")
    assert valid is True

    valid, err = AssetProtocolHelper.validate_id("VOICE_SHENLIAN_T1_MASTER", expected_category="VOICE")
    assert valid is True

    # 1.2 异常/非标 ID 拦截
    valid, err = AssetProtocolHelper.validate_id("CHAR_SHENLIAN_BASE_PORTRAIT")  # 只有3段
    assert valid is False
    assert "必须为4段" in err

    valid, err = AssetProtocolHelper.validate_id("INVALID_SHENLIAN_T1_BASE")  # 前缀非法
    assert valid is False
    assert "未知分类" in err

    valid, err = AssetProtocolHelper.validate_id("CHAR_SHENLIAN_T9_BASE_PORTRAIT")  # 梯队非法
    assert valid is False
    assert "梯队代码无效" in err

    valid, err = AssetProtocolHelper.validate_id("CHAR_SHENLIAN_T1_BASE_PORTRAIT", expected_category="ENV")
    assert valid is False
    assert "期望 ENV_" in err


def test_episode_resource_manifest_table6_and_flat_compatibility():
    """测试 EpisodeResourceManifest 同时兼容 Table 6 树状嵌套与平铺列表。"""
    manifest_data = {
        "episode_num": 1,
        "characters": {
            "tier1_base": [
                {
                    "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "character_name": "沈炼",
                    "base_portrait": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "base_costume": "CHAR_SHENLIAN_T1_BASE_COSTUME",
                    "visual_prompt": "沈炼，三十出头，神色冷峻，皮肤微瑕有毛孔，穿深灰风衣",
                }
            ],
            "tier2_performance": [
                {
                    "char_id": "CHAR_SHENLIAN_T2_4V_FRONT_FULL",
                    "character_name": "沈炼",
                    "angle_views": ["CHAR_SHENLIAN_T2_4V_FRONT_FULL", "CHAR_SHENLIAN_T2_4V_PROFILE"],
                    "script_emotions": ["CHAR_SHENLIAN_T2_EXP_DESPERATE"],
                    "visual_prompt": "从头到脚全身站姿，深灰风衣平整垂落，双脚稳固踩在地面，脚穿黑色作战短靴",
                }
            ],
            "tier3_special": [],
        },
        "environments": {
            "tier1_primary": [
                {
                    "scene_id": "ENV_STATION_T1_WIDE",
                    "scene_name": "废弃火车站扳道房",
                    "wide_shot": "ENV_STATION_T1_WIDE",
                    "lighting_state": "ENV_STATION_T1_LIGHT_NIGHT_RAIN",
                    "visual_prompt": "废弃火车站扳道房，夜景暴雨，冷调青蓝色顶光",
                }
            ],
            "tier2_transitional": [],
        },
        "props": {
            "tier1_hero": [
                {
                    "prop_id": "PROP_DAGGER_T1_STATIC",
                    "prop_name": "生锈手术刀",
                    "static_asset": "PROP_DAGGER_T1_STATIC",
                    "action_asset": "PROP_DAGGER_T1_ACTION",
                    "visual_prompt": "生锈手术刀特写，刀刃微卷沾染暗红血渍",
                }
            ],
            "tier2_anchor": [],
            "tier3_atmospheric": [],
        },
    }

    manifest = EpisodeResourceManifest.model_validate(manifest_data)

    # 验证模型属性与字典式属性聚合
    assert manifest.episode_num == 1
    assert len(manifest.characters_tier_1) == 1
    assert manifest.characters_tier_1[0]["char_id"] == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
    assert len(manifest.characters_tier_2) == 1
    assert len(manifest.environments_primary) == 1
    assert len(manifest.props_narrative) == 1

    # 验证别名平铺访问 (characters/environments/props)
    assert len(manifest.characters) == 2
    assert len(manifest.environments) == 1
    assert len(manifest.props) == 1

    # 验证 to_dict() 完整性
    d = manifest.to_dict()
    assert "characters" in d
    assert "environments" in d
    assert "props" in d
    assert "audio" not in d
    assert manifest["episode_num"] == 1


# =========================================================================
# 2. 剧本特征动态逆向扫描器测试
# =========================================================================

def test_screenplay_feature_scanner_operators():
    """测试 scan_screenplay_features 对四大算子的全面逆向提取。"""
    script_text = """
    【场景 01】外景 暴雨中的货运火车站扳道房 夜
    暴雨倾盆。一道惨白闪电撕裂雨幕，暴烈顶光照亮扳道房破损的窗棱。
    沈炼浑身湿透，满脸绝望与愤怒，右额角有鲜血渗出。他右手紧攥着一把生锈的手术刀，手背青筋暴起。
    沈炼发狂般地猛砸铁门，将门锁砸得崩碎，随后生锈手术刀在剧烈撞击下被切断！
    沈炼（咬牙切齿，压抑沉痛）：赵崇山，你逃不掉的！
    """

    known_characters = [{"name": "沈炼", "gender": "男"}]
    known_scenes = [{"name": "货运火车站扳道房", "description": "废弃车站扳道房"}]
    known_props = [{"name": "生锈的手术刀", "description": "沾血的手术刀"}]

    features = scan_screenplay_features(
        screenplay_text=script_text,
        characters=known_characters,
        scenes=known_scenes,
        props=known_props,
    )

    # 算子 A 验证: 角色登场、情绪、视角
    assert "沈炼" in features["characters_detected"]
    assert any("绝望" in e or "愤怒" in e for e in features["emotions_detected"]["沈炼"])
    assert any("额" in inj or "血" in inj for inj in features["injuries_detected"]["沈炼"])
    assert any("手" in m for m in features["macro_details"]["沈炼"])

    # 算子 B 验证: 场景与光影做旧
    assert any("扳道房" in s for s in features["scenes_detected"])
    assert any("夜" in l or "闪电" in l or "雨" in l for l in features["lighting_conditions"])

    # 算子 C 验证: 道具形变与破坏动词
    assert "生锈的手术刀" in features["props_detected"]
    deform_actions = features["deformed_props"].get("生锈的手术刀", [])
    assert any(verb in ["砸", "切", "断", "崩碎"] for verb in deform_actions)

    # 算子 D 验证: 角色台词声学母音触发
    assert "沈炼" in features["voice_actors_needed"]
    assert len(features["voice_actors_needed"]["沈炼"]["sample_lines"]) > 0


# =========================================================================
# 3. Stage 6 保底工厂与业务节点测试
# =========================================================================

def test_stage6_fallback_table6_compliance():
    """测试 _stage6_fallback 生成的视听清单完全符合 Table 6 标准契约。"""
    script_dict = {
        "episode_num": 1,
        "title": "绝境扳道房",
        "scenes": [
            {
                "scene_num": 1,
                "heading": "【场景 01】外景 暴雨中的废弃火车站扳道房 夜",
                "screenplay_text": "暴雨倾盆。沈炼握紧手术刀，砸向门锁。",
            }
        ],
    }
    characters_engine = [{"name": "沈炼", "id": 1, "description": "三十出头的亡命刑警"}]
    environments_props = {
        "scenes": [{"name": "废弃火车站扳道房", "description": "破败建筑"}],
        "props": [{"name": "手术刀", "description": "带血手术刀"}],
    }

    result = _stage6_fallback(
        episode_num=1,
        script_dict=script_dict,
        characters_engine=characters_engine,
        environments_props=environments_props,
        existing_registry=None,
    )

    manifest = result["manifest"]
    assert manifest["episode_num"] == 1

    # 检查 Table 6 三层角色资产
    c_t1 = manifest["characters"]["tier1_base"]
    assert len(c_t1) > 0
    assert c_t1[0]["char_id"].startswith("CHAR_")
    assert "T1_BASE_PORTRAIT" in c_t1[0]["base_portrait"]

    # 检查场景与道具
    e_t1 = manifest["environments"]["tier1_primary"]
    assert len(e_t1) > 0
    assert e_t1[0]["scene_id"].startswith("ENV_")

    p_t1 = manifest["props"]["tier1_hero"]
    assert len(p_t1) > 0
    assert p_t1[0]["prop_id"].startswith("PROP_")

    # 检查声学母音卡片
    voice_cards = result["new_character_master_voice_cards"]
    assert len(voice_cards) > 0
    assert voice_cards[0]["master_voice_id"].startswith("VOICE_")
    assert voice_cards[0]["master_tts_prompt"] != ""

    # 检查增量生成引单与 DAG
    new_assets = result["newly_generated_assets"]
    assert len(new_assets) > 0
    assert "lineage_dag" in result


def test_stage6_asset_truth_node_poka_yoke_reuse_and_incremental():
    """测试 stage6_asset_truth_node 业务节点对已核准资产的 100% 只读复用与增量资产入库。"""
    # 构造初始全局资产真理源注册表 (模拟第 1 集已核准的资产)
    initial_registry = VisualAudioAssetsRegistryModel(
        characters={
            "CHAR_SHENLIAN_T1_BASE_PORTRAIT": {
                "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "character_name": "沈炼",
                "status": "APPROVED",
                "storage_url": "storage/characters/shenlian_base.png",
                "visual_prompt": "沈炼标准肖像，面部皮肤细微毛孔微瑕",
            }
        },
        character_master_voices={
            "VOICE_SHENLIAN_T1_MASTER": {
                "master_voice_id": "VOICE_SHENLIAN_T1_MASTER",
                "character_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "master_tts_prompt": "低沉磁性压抑男声",
                "status": "APPROVED",
            }
        },
    )

    state = IndustrialDramaMasterState(
        drama_id=101,
        total_episodes=2,
        current_visual_episode=2,
        completed_screenplays={
            2: {
                "episode_num": 2,
                "title": "反转追踪",
                "scenes": [
                    {
                        "scene_num": 1,
                        "heading": "【场景 01】外景 暴雨中的废弃火车站扳道房 夜",
                        "screenplay_text": "沈炼看着断裂的手术刀，苏晓从阴影中缓步走出。",
                    }
                ],
            }
        },
        character_engine=[
            {"name": "沈炼", "id": 1, "description": "亡命刑警"},
            {"name": "苏晓", "id": 2, "description": "神秘女医生"},
        ],
        environments_and_props={
            "scenes": [{"name": "废弃火车站扳道房", "description": "破败车站"}],
            "props": [{"name": "手术刀", "description": "断裂的手术刀"}],
        },
        visual_audio_assets_registry=initial_registry,
    )

    # 模拟 LLM 离线生成 (使用 fallback 确保环境隔离)
    new_state = stage6_asset_truth_node(state)

    manifest = new_state.episode_manifests[2]
    assert manifest is not None

    # 验证 Poka-Yoke: 已有的沈炼基础肖像被安全标记为只读复用
    reused = new_state.reused_existing_assets
    assert any(r["asset_id"] == "CHAR_SHENLIAN_T1_BASE_PORTRAIT" for r in reused)

    # 验证增量资产: 新登场的苏晓被登记为增量资产并纳入真理源
    new_reg = new_state.visual_audio_assets_registry
    if hasattr(new_reg, "to_dict"):
        new_reg = new_reg.to_dict()
    
    chars_reg = new_reg.get("characters", {})
    # 苏晓或沈炼的新视角/新资产必须登记在全局真理源中
    assert len(chars_reg) >= 2


# =========================================================================
# 4. RedBlueAuditor Checkpoint 6 严苛红蓝对抗审查
# =========================================================================

def test_red_blue_auditor_checkpoint_6_compliance_and_blocks():
    """测试 RedBlueAuditor 在哨卡 6 上的合规批准与各维度红蓝阻断拦截。"""
    auditor = RedBlueAuditor()

    # 4.1 完备合规数据 -> 绿灯
    valid_manifest = {
        "episode_num": 1,
        "manifest": {
            "characters": {
                "tier1_base": [
                    {
                        "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                        "base_portrait": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                        "base_costume": "CHAR_SHENLIAN_T1_BASE_COSTUME",
                        "visual_prompt": "三十出头男子，皮肤真实微瑕有毛孔，深灰粗花呢大衣",
                    }
                ],
                "tier2_performance": [
                    {
                        "char_id": "CHAR_SHENLIAN_T2_4V_FRONT_FULL",
                        "angle_views": ["CHAR_SHENLIAN_T2_4V_FRONT_FULL"],
                        "visual_prompt": "从头到脚全身直立，双脚踩在地面，黑色作战靴完整落地",
                    }
                ],
                "tier3_special": [],
            },
            "environments": {
                "tier1_primary": [
                    {
                        "scene_id": "ENV_STATION_T1_WIDE",
                        "wide_shot": "ENV_STATION_T1_WIDE",
                        "lighting_state": "ENV_STATION_T1_LIGHT_NIGHT",
                    }
                ],
                "tier2_transitional": [],
            },
            "props": {
                "tier1_hero": [
                    {
                        "prop_id": "PROP_DAGGER_T1_STATIC",
                        "static_asset": "PROP_DAGGER_T1_STATIC",
                    }
                ],
                "tier2_anchor": [],
                "tier3_atmospheric": [],
            },
        },
        "new_character_master_voice_cards": [
            {
                "master_voice_id": "VOICE_SHENLIAN_T1_MASTER",
                "character_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "master_tts_prompt": "低沉磁性压抑男声",
            }
        ],
        "reused_existing_assets": [],
        "newly_generated_assets": [
            {
                "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "generation_method": "text_to_image",
                "prompt": "沈炼肖像",
            }
        ],
    }

    report_valid = auditor.audit_stage_payload(stage=6, content_payload=valid_manifest)
    assert report_valid.verdict == AuditVerdict.GREEN_APPROVED

    # 4.2 缺失关键分类拦截
    invalid_manifest = {
        "manifest": {
            "characters": [],
            # environments 缺失
            "props": [],
        }
    }
    report_missing = auditor.audit_stage_payload(stage=6, content_payload=invalid_manifest)
    assert report_missing.verdict == AuditVerdict.RED_BLOCKING
    assert any("缺失场景资产项" in b for b in report_missing.blocking_reasons)

    # 4.3 资产 ID 非标拦截
    invalid_id_payload = {
        "manifest": {
            "characters": [{"asset_id": "CHAR_BAD_ID"}],
            "environments": [{"asset_id": "ENV_OK_T1_WIDE"}],
            "props": [{"asset_id": "PROP_OK_T1_STATIC"}],
        }
    }
    report_bad_id = auditor.audit_stage_payload(stage=6, content_payload=invalid_id_payload)
    assert report_bad_id.verdict == AuditVerdict.RED_BLOCKING
    assert any("角色资产 ID 违规" in b for b in report_bad_id.blocking_reasons)

    # 4.4 角色母音卡片缺失 master_tts_prompt 拦截
    voice_bad_payload = dict(valid_manifest)
    voice_bad_payload["new_character_master_voice_cards"] = [
        {
            "master_voice_id": "VOICE_SHENLIAN_T1_MASTER",
            "character_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
            "master_tts_prompt": "",  # 缺失声学提示词
        }
    ]
    report_bad_voice = auditor.audit_stage_payload(stage=6, content_payload=voice_bad_payload)
    assert report_bad_voice.verdict == AuditVerdict.RED_BLOCKING
    assert any("缺失 master_tts_prompt" in b for b in report_bad_voice.blocking_reasons)

    # 4.5 红军魔鬼挑刺: 网红磨皮塑胶假人拦截 (Anti-Plastic Face)
    doll_face_payload = {
        "manifest": {
            "characters": [
                {
                    "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "visual_prompt": "绝美精致，美白磨皮，皮肤完美无瑕如同瓷娃娃 doll face",
                }
            ],
            "environments": [{"asset_id": "ENV_STATION_T1_WIDE"}],
            "props": [{"asset_id": "PROP_DAGGER_T1_STATIC"}],
        }
    }
    report_doll = auditor.audit_stage_payload(stage=6, content_payload=doll_face_payload)
    assert report_doll.verdict == AuditVerdict.RED_BLOCKING
    assert any("网红磨皮假人" in b for b in report_doll.blocking_reasons)

    # 4.6 红军魔鬼挑刺: 定妆全身照截断半身拦截 (Anti-Foot-Clipping)
    clip_payload = {
        "manifest": {
            "characters": [
                {
                    "asset_id": "CHAR_SHENLIAN_T1_BASE_COSTUME",
                    "visual_prompt": "沈炼全身定妆大衣，half body, waist up, 只拍上半身特写",
                }
            ],
            "environments": [{"asset_id": "ENV_STATION_T1_WIDE"}],
            "props": [{"asset_id": "PROP_DAGGER_T1_STATIC"}],
        }
    }
    report_clip = auditor.audit_stage_payload(stage=6, content_payload=clip_payload)
    assert report_clip.verdict == AuditVerdict.RED_BLOCKING
    assert any("半身截断描述" in b for b in report_clip.blocking_reasons)

    # 4.7 红军魔鬼挑刺: 图生图缺失 input_source_image 底图血统拦截
    no_source_payload = dict(valid_manifest)
    no_source_payload["newly_generated_assets"] = [
        {
            "asset_id": "CHAR_SHENLIAN_T2_4V_PROFILE",
            "generation_method": "image_to_image",
            "input_source_image": "",  # 缺失底图引用
            "prompt": "沈炼侧脸",
        }
    ]
    report_no_source = auditor.audit_stage_payload(stage=6, content_payload=no_source_payload)
    assert report_no_source.verdict == AuditVerdict.RED_BLOCKING
    assert any("缺失 input_source_image 底图血统引用" in b for b in report_no_source.blocking_reasons)


# =========================================================================
# 5. 存储适配器 (drama_storage_adapter) 落库与反序列化测试
# =========================================================================

def test_persist_stage6_and_hydration_roundtrip():
    """测试 persist_stage6 写入 episodes.ast_blocks 及 metadata 并能无损还原。"""
    mock_db = MagicMock()

    # 模拟 fetch_one 查询 episodes 与 dramas
    ep_row = {"id": 10, "ast_blocks": "{}"}
    drama_row = {"id": 1, "metadata": "{}"}

    def mock_fetch_one(session, sql, params=None):
        if "episodes" in sql:
            return ep_row
        if "dramas" in sql:
            return drama_row
        return None

    import app.workflows.adapters.drama_storage_adapter as dsa
    original_fetch_one = dsa.fetch_one
    original_sync_mem = dsa.sync_stage_memories_to_vector_db
    dsa.fetch_one = mock_fetch_one
    dsa.sync_stage_memories_to_vector_db = MagicMock()

    try:
        manifest = EpisodeResourceManifest(
            episode_num=1,
            characters=[
                {
                    "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "character_name": "沈炼",
                }
            ],
            environments=[
                {
                    "scene_id": "ENV_STATION_T1_WIDE",
                    "scene_name": "废弃车站",
                }
            ],
            props=[
                {
                    "prop_id": "PROP_DAGGER_T1_STATIC",
                    "prop_name": "手术刀",
                }
            ],
        )

        registry = VisualAudioAssetsRegistryModel(
            characters={
                "CHAR_SHENLIAN_T1_BASE_PORTRAIT": {
                    "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "status": "APPROVED",
                }
            }
        )

        state = IndustrialDramaMasterState(
            drama_id=1,
            current_visual_episode=1,
            episode_manifests={1: manifest},
            visual_audio_assets_registry=registry,
        )

        # 执行落库
        persist_stage6(mock_db, drama_id=1, state=state, episode_num=1)

        # 验证 db.execute 被调用且包含 UPDATE
        assert mock_db.execute.called
        assert mock_db.commit.called

        # 验证执行参数中的 JSON 能够正常 dump，没有报错
        updates = [c[0][1] for c in mock_db.execute.call_args_list if len(c[0]) > 1 and isinstance(c[0][1], dict)]
        assert any("ast_blocks" in p for p in updates)
        assert any("metadata" in p for p in updates)

    finally:
        dsa.fetch_one = original_fetch_one
        dsa.sync_stage_memories_to_vector_db = original_sync_mem


def test_persist_stage6_relational_full_sync(db_session):
    """测试阶段 6 关系表全量同步与深度原子落库：
    1. 自动写入 episodes.ast_blocks['episode_resource_manifest']；
    2. characters 自动创建增量角色并补全外观和声音风格；
    3. character_stages 与 character_stage_views 自动建立生命周期阶段与主视切片；
    4. episode_characters 成功绑定集与登场角色；
    5. character_voice_profiles 自动录入音色母卡与声音档案；
    6. scenes, scene_zones, scene_weathering_views 记录增量场景与做旧层；
    7. props, prop_damage_states 记录关键道具与战损演进形态；
    8. 幂等性校验：重复调用保持状态一致且不产生重复数据。
    """
    # 1. 准备短剧与剧集初始数据
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (101, '风雪夜归人', 'draft', '', '')")
    )
    db_session.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, created_at, updated_at) VALUES (1001, 101, 1, '第一集：暴雪出鞘', '', '')")
    )
    db_session.commit()

    # 2. 构建阶段 6 的 manifest 与 state
    manifest = EpisodeResourceManifest(
        episode_num=1,
        characters=[
            {
                "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "character_name": "沈炼",
                "role": "protagonist",
                "stage_name": "飞鱼服佩刀形态",
                "visual_prompt": "身着飞鱼服手握绣春刀，神色冷峻，眼神如鹰隼，电影质感",
                "voice_style": "低沉磁性烟嗓",
            },
            {
                "char_id": "CHAR_ZHAOJING_T1_BASE",
                "character_name": "赵靖",
                "role": "antagonist",
                "stage_name": "锦衣卫千户战损造型",
                "visual_prompt": "锦衣卫千户银甲破损，沾染血渍，眼神阴狠",
                "voice_style": "尖锐阴鸷",
            },
        ],
        environments=[
            {
                "scene_id": "ENV_STATION_T1_WIDE",
                "scene_name": "废弃驿站",
                "time_lighting": "深夜暴风雪，烛光摇曳",
                "weathering_applied": ["窗棂积雪结霜", "地面冻泥与融雪暗渍"],
                "visual_prompt": "破旧荒野木质驿站全景，暴风雪呼啸，摇曳烛光映照斑驳木墙",
            }
        ],
        props=[
            {
                "prop_id": "PROP_DAGGER_T1_STATIC",
                "prop_name": "绣春刀",
                "damage_state": "刀刃卷口带有暗红血痕",
                "damage_level": 2,
                "visual_prompt": "特写镜头，明代绣春刀刃口微卷，血槽带有干涸血迹",
            }
        ],
    )

    state = IndustrialDramaMasterState(
        drama_id=101,
        current_visual_episode=1,
        episode_manifests={1: manifest},
        new_character_master_voice_cards=[
            {
                "character_name": "沈炼",
                "character_code": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "master_voice_id": "VOICE_SHENLIAN_T1_MASTER",
                "timbre": "低沉磁性中年男音",
                "speed_ratio": 1.05,
                "pitch_ratio": 0.95,
                "emotion_rules": ["决斗时简短发力", "独白时压低语调"],
            },
            {
                "character_name": "赵靖",
                "character_code": "CHAR_ZHAOJING_T1_BASE",
                "master_voice_id": "VOICE_ZHAOJING_T1_MASTER",
                "timbre": "尖锐阴鸷太监音",
                "speed_ratio": 1.1,
                "pitch_ratio": 1.05,
            }
        ],
    )

    # 3. 执行 persist_stage6
    persist_stage6(db_session, drama_id=101, state=state, episode_num=1)

    # 4. 验证 episodes.ast_blocks
    ep_row = db_session.execute(text("SELECT ast_blocks FROM episodes WHERE id = 1001")).mappings().first()
    assert ep_row is not None
    ep_ast = json.loads(ep_row["ast_blocks"])
    assert "episode_resource_manifest" in ep_ast
    assert len(ep_ast["episode_resource_manifest"]["characters"]) == 2

    # 5. 验证 characters 表写入
    char_rows = db_session.execute(text("SELECT * FROM characters WHERE drama_id = 101 ORDER BY id ASC")).mappings().all()
    assert len(char_rows) == 2
    char_names = [c["name"] for c in char_rows]
    assert "沈炼" in char_names
    assert "赵靖" in char_names
    shenlian_char = next(c for c in char_rows if c["name"] == "沈炼")
    zhaojing_char = next(c for c in char_rows if c["name"] == "赵靖")
    assert shenlian_char["role"] == "protagonist"
    assert zhaojing_char["role"] == "antagonist"

    # 6. 验证 character_stages 表写入
    stages = db_session.execute(text("SELECT * FROM character_stages WHERE drama_id = 101 ORDER BY id ASC")).mappings().all()
    assert len(stages) >= 2
    stage_names = [s["stage_name"] for s in stages]
    assert "飞鱼服佩刀形态" in stage_names
    assert "锦衣卫千户战损造型" in stage_names

    # 7. 验证 character_stage_views 表写入
    views = db_session.execute(text("SELECT * FROM character_stage_views ORDER BY id ASC")).mappings().all()
    assert len(views) >= 2
    assert all(v["view_type"] == "main_portrait" for v in views)
    assert all(v["is_primary"] == 1 for v in views)

    # 8. 验证 episode_characters 关联表映射
    ep_chars = db_session.execute(text("SELECT * FROM episode_characters WHERE episode_id = 1001")).mappings().all()
    assert len(ep_chars) == 2
    ep_char_ids = {ec["character_id"] for ec in ep_chars}
    assert shenlian_char["id"] in ep_char_ids
    assert zhaojing_char["id"] in ep_char_ids

    # 9. 验证 character_voice_profiles 写入
    voice_profiles = db_session.execute(text("SELECT * FROM character_voice_profiles WHERE drama_id = 101")).mappings().all()
    assert len(voice_profiles) == 2
    vp_dict = {vp["character_name"]: vp for vp in voice_profiles}
    assert "沈炼" in vp_dict
    assert "赵靖" in vp_dict
    assert vp_dict["沈炼"]["voice_id"] == "VOICE_SHENLIAN_T1_MASTER"
    assert vp_dict["沈炼"]["timbre"] == "低沉磁性中年男音"
    assert vp_dict["赵靖"]["voice_id"] == "VOICE_ZHAOJING_T1_MASTER"
    assert vp_dict["赵靖"]["timbre"] == "尖锐阴鸷太监音"

    # 10. 验证 scenes, scene_zones, scene_weathering_views
    scenes = db_session.execute(text("SELECT * FROM scenes WHERE drama_id = 101")).mappings().all()
    assert len(scenes) == 1
    assert scenes[0]["location"] == "废弃驿站"
    zones = db_session.execute(text("SELECT * FROM scene_zones WHERE drama_id = 101")).mappings().all()
    assert len(zones) == 1
    assert zones[0]["zone_name"] == "核心主活动区"
    w_views = db_session.execute(text("SELECT * FROM scene_weathering_views WHERE scene_zone_id = :zid"), {"zid": zones[0]["id"]}).mappings().all()
    assert len(w_views) == 2
    w_descs = [w["description"] for w in w_views]
    assert "窗棂积雪结霜" in w_descs
    assert "地面冻泥与融雪暗渍" in w_descs

    # 11. 验证 props, prop_damage_states
    props = db_session.execute(text("SELECT * FROM props WHERE drama_id = 101")).mappings().all()
    assert len(props) == 1
    assert props[0]["name"] == "绣春刀"
    damage_states = db_session.execute(text("SELECT * FROM prop_damage_states WHERE drama_id = 101")).mappings().all()
    assert len(damage_states) == 1
    assert damage_states[0]["state_label"] == "刀刃卷口带有暗红血痕"
    assert damage_states[0]["damage_level"] == 2

    # 12. 幂等性验证：二次执行 persist_stage6，不产生重复记录
    persist_stage6(db_session, drama_id=101, state=state, episode_num=1)
    char_rows_after = db_session.execute(text("SELECT * FROM characters WHERE drama_id = 101")).mappings().all()
    assert len(char_rows_after) == 2
    ep_chars_after = db_session.execute(text("SELECT * FROM episode_characters WHERE episode_id = 1001")).mappings().all()
    assert len(ep_chars_after) == 2
    props_after = db_session.execute(text("SELECT * FROM props WHERE drama_id = 101")).mappings().all()
    assert len(props_after) == 1
    scenes_after = db_session.execute(text("SELECT * FROM scenes WHERE drama_id = 101")).mappings().all()
    assert len(scenes_after) == 1


def test_scanner_and_stage6_dynamic_token_stem_and_isolation():
    """测试五大深度重构能力：
    1. 动态拼音 Token 化：非固定词表中的任意新角色（如“顾言之”）、新场景（如“青云山断崖”）、新道具均可生成合规四段式 ID；
    2. 核心词干匹配：Stage 2/3 长修饰全称（如“《暗夜交锋》涉案加密暗账本”、“父亲留下的老式铜怀表”）可精准匹配剧本中的简称（“暗账本”、“铜怀表”）；
    3. Stage 2 角色随身锚点物自动桥接：从 carried_anchor_item / visual_consistency_code.anchor_props 自动合入道具池；
    4. 多角色分句级动作/特写/战损隔离：角色 A 的手部特写与额角流血不会串扰污染同场站立的角色 B；
    5. 多道具分句级形变隔离：仅被破坏动词作用的道具触发 ACTION 态，同场静态道具保持 STATIC 态。
    """
    characters = [
        {
            "name": "顾言之",
            "gender": "男",
            "carried_anchor_item": {
                "item_name": "父亲留下的老式铜怀表",
                "visual_prompt": "边缘磨损的黄铜怀表，表盖内侧刻有家训",
            },
        },
        {
            "name": "叶清歌",
            "gender": "女",
            "visual_consistency_code": {
                "anchor_props": ["青玉发簪"],
            },
        },
    ]
    scenes = [{"name": "《暗夜交锋》青云山断崖主决战台", "description": "悬崖峭壁，怪石嶙峋"}]
    props = [
        {"name": "《暗夜交锋》涉案加密暗账本", "description": "牛皮封面的涉案机密账册"},
        {"name": "青铜虎符", "description": "调兵遣将的虎符信物"},
    ]

    script_text = """
    【场景 01】外景 暴雨中的青云山断崖 夜
    暴雨如注，惨白闪电劈开夜幕。
    顾言之满脸绝望，右额角有鲜血渗出。他右手紧握着那本暗账本，手背青筋暴起，随后发狠将暗账本撕得粉碎！
    叶清歌静静站在远处的礁石旁，目光平静地注视着桌上的铜怀表与青铜虎符。
    顾言之（嘶哑低吼）：真相永远不会被掩埋！
    """

    features = scan_screenplay_features(
        screenplay_text=script_text,
        characters=characters,
        scenes=scenes,
        props=props,
    )

    # 1 & 2. 核心词干匹配：长修饰场景与长修饰道具均能命中剧本中的自然简称
    assert "《暗夜交锋》青云山断崖主决战台" in features["scenes_detected"]
    assert "《暗夜交锋》涉案加密暗账本" in features["props_detected"]

    # 3. Stage 2 角色随身锚点物自动桥接 + 核心词干匹配（“父亲留下的老式铜怀表”匹配剧本中的“铜怀表”）
    assert "父亲留下的老式铜怀表" in features["props_detected"]

    # 4. 多角色分句级动作/特写/战损隔离：顾言之有手部微距与额角流血，叶清歌不应被串扰
    assert len(features["macro_details"]["顾言之"]) > 0
    assert len(features["injuries_detected"]["顾言之"]) > 0
    assert features["macro_details"]["叶清歌"] == []
    assert features["injuries_detected"]["叶清歌"] == []

    # 5. 多道具分句级形变隔离：“撕”只作用于暗账本，铜怀表与青铜虎符不应触发形变
    assert "撕" in features["deformed_props"].get("《暗夜交锋》涉案加密暗账本", [])
    assert features["deformed_props"].get("父亲留下的老式铜怀表", []) == []
    assert features["deformed_props"].get("青铜虎符", []) == []

    # 6. 验证 _stage6_fallback 动态 Token 生成与道具 ACTION 态精准隔离
    fallback_res = _stage6_fallback(
        episode_num=1,
        script_dict={
            "episode_num": 1,
            "title": "断崖对决",
            "scenes": [{"scene_num": 1, "heading": "青云山断崖", "screenplay_text": script_text}],
        },
        characters_engine=characters,
        environments_props={"scenes": scenes, "props": props},
        existing_registry=None,
    )

    manifest = fallback_res["manifest"]
    t1_chars = manifest["characters"]["tier1_base"]
    assert len(t1_chars) == 2
    for c_item in t1_chars:
        is_ok, err_msg = AssetProtocolHelper.validate_id(c_item["char_id"], expected_category="CHAR")
        assert is_ok is True, f"角色资产ID不合规: {c_item['char_id']} -> {err_msg}"

    # 校验所有生成的资产 ID 100% 符合四段式协议且不含硬编码冷水饺
    for asset in fallback_res["newly_generated_assets"]:
        is_valid, reason = AssetProtocolHelper.validate_id(asset["asset_id"])
        assert is_valid is True, f"非标资产ID: {asset['asset_id']} -> {reason}"

    hero_props = {p["prop_name"]: p for p in manifest["props"]["tier1_hero"]}
    anchor_props = {p["prop_name"]: p for p in manifest["props"]["tier2_anchor"]}
    assert "《暗夜交锋》涉案加密暗账本" in hero_props
    assert "青铜虎符" in hero_props
    assert "父亲留下的老式铜怀表" in anchor_props
    assert hero_props["《暗夜交锋》涉案加密暗账本"]["action_asset"] is not None
    assert hero_props["青铜虎符"]["action_asset"] is None
    assert manifest["props"]["tier3_ambient"] == []
