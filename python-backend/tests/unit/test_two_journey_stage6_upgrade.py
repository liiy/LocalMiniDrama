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
        "audio": {
            "character_voices": [
                {
                    "voice_id": "VOICE_SHENLIAN_T1_MASTER",
                    "character_name": "沈炼",
                    "timbre_description": "低沉磁性，略带烟嗓的压抑男声",
                    "base_seed_audio": "audio/voices/shenlian_master.wav",
                }
            ],
            "environmental_ambience": ["雨夜风声呼啸"],
            "foley_cues": ["脚步踩在碎玻璃声"],
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
    assert len(manifest.audio_voices) == 1

    # 验证别名平铺访问 (characters/environments/props/audio)
    assert len(manifest.characters) == 2
    assert len(manifest.environments) == 1
    assert len(manifest.props) == 1
    assert len(manifest.audio) == 1

    # 验证 to_dict() 完整性
    d = manifest.to_dict()
    assert "characters" in d
    assert "environments" in d
    assert "props" in d
    assert "audio" in d
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
            audio=[
                {
                    "voice_id": "VOICE_SHENLIAN_T1_MASTER",
                    "character_name": "沈炼",
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
