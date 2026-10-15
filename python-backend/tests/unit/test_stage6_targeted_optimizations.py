# -*- coding: utf-8 -*-
"""针对性改进与优化落地建议的单元测试套件。

覆盖 5 大核心优化项：
1. SSOT 模式统一 (EpisodeResourceManifest 双向平铺/嵌套互通与属性访问)
2. 命名实体识别与代词指代消解 (NER 别名归一化与上下文敏感的“他/她”消解)
3. 资产生命周期状态机推进 (AssetState 枚举与全生命周期状态流转)
4. 语义资产哈希与跨集幂等去重 (确定性 SHA-256 指纹与跨集自动去重为复用池)
5. 存储适配器元数据持久化与 Schema 健壮性 (多模态指纹与级联表落地)
"""

import json
import pytest
from sqlalchemy import text

from app.schemas.script_graph_state import (
    AssetState,
    EpisodeResourceManifest,
    ReusedAssetModel,
    NewlyGeneratedAssetModel,
    IndustrialDramaMasterState,
)
from app.tools.screenplay_feature_scanner import (
    scan_screenplay_features,
)
from app.workflows.nodes.stage6_asset_truth import (
    compute_asset_semantic_hash,
    stage6_asset_truth_node,
    _stage6_fallback,
)
from app.workflows.adapters.drama_storage_adapter import (
    persist_stage6,
)


# =========================================================================
# 1. SSOT 模式统一与双向平铺/嵌套兼容性测试
# =========================================================================

def test_ssot_schema_bidirectional_and_properties():
    """验证 EpisodeResourceManifest 兼容嵌套与平铺双向结构，并提供统一的快捷属性。"""
    # 构造嵌套结构的 manifest
    nested_data = {
        "episode_num": 1,
        "characters": {
            "tier1_base": [
                {
                    "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "character_name": "沈炼",
                    "master_voice": "VOICE_SHENLIAN_T1_MASTER",
                    "visual_prompt": "冷峻锦衣卫正面肖像",
                    "lifecycle_status": "APPROVED",
                }
            ],
            "tier2_performance": [],
            "tier3_special": [],
        },
        "environments": {
            "tier1_primary": [
                {
                    "scene_id": "ENV_STATION_T1_WIDE",
                    "location_name": "废弃驿站",
                    "visual_prompt": "暴风雪中的驿站全景",
                    "lifecycle_status": "APPROVED",
                }
            ],
            "tier2_transitional": [],
        },
        "props": {
            "tier1_hero": [
                {
                    "prop_id": "PROP_SWORD_T1_STATIC",
                    "name": "绣春刀",
                    "visual_prompt": "带血槽的绣春刀特写",
                    "lifecycle_status": "READY",
                }
            ],
            "tier2_anchor": [],
            "tier3_atmospheric": [],
        },
    }

    manifest = EpisodeResourceManifest.model_validate(nested_data)

    # 1. 验证便捷属性提取
    assert manifest.character_names == ["沈炼"]
    assert manifest.scene_names == ["废弃驿站"]
    assert manifest.prop_names == ["绣春刀"]
    assert "CHAR_SHENLIAN_T1_BASE_PORTRAIT" in manifest.all_asset_ids
    assert "ENV_STATION_T1_WIDE" in manifest.all_asset_ids
    assert "PROP_SWORD_T1_STATIC" in manifest.all_asset_ids
    assert "VOICE_SHENLIAN_T1_MASTER" in manifest.all_asset_ids

    # 2. 验证字典类索引与 get() 访问
    assert manifest["characters"] is not None
    assert manifest.get("environments") is not None
    assert len(manifest["props"]) >= 1

    # 3. 验证平铺与嵌套字典转换
    flat_dict = manifest.to_flat_dict()
    assert "characters_tier_1" in flat_dict
    assert "environments_primary" in flat_dict
    assert "props_narrative" in flat_dict

    nested_dict = manifest.to_nested_dict()
    assert "tier1_base" in nested_dict["characters"]
    assert "tier1_primary" in nested_dict["environments"]


# =========================================================================
# 2. 命名实体识别与代词指代消解 (NER & Coreference)
# =========================================================================

def test_screenplay_feature_scanner_ner_and_coreference():
    """验证剧本特征扫描器的别名归一化与代词上下文敏感消解。"""
    script_text = """
    第1幕 暴风雪夜 废弃驿站 内/夜
    
    沈炼推开斑驳木门，寒风夹着雪沫灌入。
    
    沈哥：（低沉克制）这间屋子有第三个人的呼吸。
    
    他死死咬牙，掌心渗出暗红血迹。
    
    苏晓从阴影中走出，右手握着手术刀。
    
    苏医生：（冷笑）心跳快了15次，你在撒谎。
    
    她眼角含泪，手指微微发颤。
    """

    alias_map = {
        "沈哥": "沈炼",
        "苏医生": "苏晓",
    }

    # 验证特征扫描器对别名与代词情绪/动作的捕获
    scan_result = scan_screenplay_features(
        screenplay_text=script_text,
        known_characters=[
            {"name": "沈炼", "gender": "male", "aliases": ["老沈"]},
            {"name": "苏晓", "gender": "female", "aliases": ["晓晓"]},
        ],
        character_alias_map=alias_map,
    )

    # 验证沈炼与苏晓成功消解别名并捕获台词与微表情
    assert "沈炼" in scan_result.characters_detected
    assert "苏晓" in scan_result.characters_detected
    assert len(scan_result.coreference_resolutions) >= 2
    assert any(r["pronoun"] == "他" and r["resolved_character"] == "沈炼" for r in scan_result.coreference_resolutions)
    assert any(r["pronoun"] == "她" and r["resolved_character"] == "苏晓" for r in scan_result.coreference_resolutions)

    # 验证新生成资产包含两名角色
    char_asset_names = [a.asset_id for a in scan_result.newly_generated_assets if "CHAR" in a.asset_id]
    assert len(char_asset_names) >= 2
    assert "沈炼" in scan_result.emotions_detected or "苏晓" in scan_result.emotions_detected
    assert len(scan_result.macro_details) > 0 or len(scan_result.injuries_detected) > 0


# =========================================================================
# 3. 资产生命周期状态机推进测试
# =========================================================================

def test_asset_lifecycle_state_machine():
    """验证 AssetState 生命周期枚举及其在数据模型与状态节点中的合规流转。"""
    assert AssetState.DRAFT.value == "DRAFT"
    assert AssetState.READY.value == "READY"
    assert AssetState.QUEUED.value == "QUEUED"
    assert AssetState.RENDERED.value == "RENDERED"
    assert AssetState.APPROVED.value == "APPROVED"
    assert AssetState.REJECTED.value == "REJECTED"

    # 验证资产项模型中的生命周期默认值与校验
    char_item = NewlyGeneratedAssetModel(
        asset_id="CHAR_TEST_T1_BASE_PORTRAIT",
        asset_category="character_tier1_base",
        script_inference_trigger="剧本推理铁证",
        visual_prompt="测试生图提示词",
        lifecycle_status=AssetState.READY,
    )
    assert char_item.lifecycle_status == "READY"

    reused_item = ReusedAssetModel(
        asset_id="CHAR_TEST_T1_BASE_PORTRAIT",
        type="character",
        usage_in_current_ep="本集复用",
        lifecycle_status=AssetState.APPROVED,
    )
    assert reused_item.lifecycle_status == "APPROVED"


# =========================================================================
# 4. 语义资产哈希与跨集去重测试
# =========================================================================

def test_semantic_asset_hashing_and_deduplication():
    """验证 SHA-256 确定性语义指纹计算与跨集自动去重转为复用。"""
    # 1. 确定性测试：相同类别、ID、Prompt 与特征必然产出一致哈希
    h1 = compute_asset_semantic_hash("CHAR", "CHAR_SHENLIAN_T1_BASE", "cinematic photorealistic沈炼", {"costume": "飞鱼服"})
    h2 = compute_asset_semantic_hash("CHAR", "CHAR_SHENLIAN_T1_BASE", "cinematic photorealistic沈炼", {"costume": "飞鱼服"})
    assert h1 == h2
    assert len(h1) == 16  # 截取的前 16 位 16 进制指纹

    # 2. 差异测试：不同 prompt 产出不同指纹
    h3 = compute_asset_semantic_hash("CHAR", "CHAR_SHENLIAN_T1_BASE", "different prompt", {"costume": "飞鱼服"})
    assert h1 != h3

    # 3. 跨集去重测试：在已有真理源中注册沈炼指纹
    existing_registry = {
        "characters": {
            "CHAR_SHENLIAN_T1_BASE_PORTRAIT": {
                "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                "character_name": "沈炼",
                "visual_prompt": "cinematic photorealistic沈炼",
                "semantic_hash": h1,
                "lifecycle_status": "APPROVED",
            }
        },
        "environments": {},
        "props": {},
        "audio_tts": {},
        "semantic_hashes": {
            "CHAR_SHENLIAN_T1_BASE_PORTRAIT": h1,
        },
        "hash_index": {
            h1: "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
        },
    }

    state = IndustrialDramaMasterState(
        drama_id=1,
        current_visual_episode=2,
        episode_number=2,
        screenplay={"body_markdown": "沈炼走进客栈。"},
        characters=[{"name": "沈炼", "id": 1, "appearance": "身着飞鱼服"}],
        environments_and_props={"scenes": [{"name": "客栈"}], "props": []},
        visual_audio_assets_registry=existing_registry,
    )

    new_state = stage6_asset_truth_node(state)

    # 验证新生成的阶段状态中，沈炼肖像被判定为复用项而非增量项
    reused = new_state.reused_existing_assets
    assert any(r.get("asset_id") == "CHAR_SHENLIAN_T1_BASE_PORTRAIT" for r in reused)


# =========================================================================
# 5. 存储适配器 Schema 健壮性与元数据持久化
# =========================================================================

def test_storage_adapter_semantic_metadata_persistence(db_session):
    """验证 persist_stage6 将语义哈希与双向引单完整落库并保持关系表健壮无异常。"""
    # 初始剧本与剧集
    db_session.execute(text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (201, '优化测试剧', 'draft', '', '')"))
    db_session.execute(text("INSERT INTO episodes (id, drama_id, episode_number, title, created_at, updated_at) VALUES (2001, 201, 1, '第1集', '', '')"))
    db_session.commit()

    # 构造带语义指纹的 manifest
    manifest = EpisodeResourceManifest(
        episode_num=1,
        characters=[
            {
                "char_id": "CHAR_TEST_T1_BASE_PORTRAIT",
                "character_name": "测试侠",
                "visual_prompt": "黑衣侠客",
                "lifecycle_status": "APPROVED",
            }
        ],
        environments=[
            {
                "scene_id": "ENV_TEST_T1_WIDE",
                "scene_name": "迷雾森林",
                "visual_prompt": "月光下的冷雾森林",
                "lifecycle_status": "APPROVED",
            }
        ],
        props=[
            {
                "prop_id": "PROP_TEST_T1_STATIC",
                "prop_name": "玉佩",
                "damage_state": "温润有微小裂纹",
                "damage_level": 1,
                "visual_prompt": "雕刻精致的羊脂白玉佩",
                "lifecycle_status": "APPROVED",
            }
        ],
    )

    state = IndustrialDramaMasterState(
        drama_id=201,
        current_visual_episode=1,
        episode_manifests={1: manifest},
        visual_audio_assets_registry={
            "characters": {"CHAR_TEST_T1_BASE_PORTRAIT": {"name": "测试侠"}},
            "environments": {},
            "props": {},
            "audio_tts": {},
            "semantic_hashes": {"CHAR_TEST_T1_BASE_PORTRAIT": "abcdef0123456789"},
        },
    )

    # 执行落库
    persist_stage6(db_session, drama_id=201, state=state, episode_num=1)

    # 1. 验证 episodes.ast_blocks 包含平铺与嵌套及语义指纹
    ep_row = db_session.execute(text("SELECT ast_blocks FROM episodes WHERE id = 2001")).mappings().first()
    assert ep_row is not None
    ep_ast = json.loads(ep_row["ast_blocks"])
    res_manifest = ep_ast["episode_resource_manifest"]
    assert "characters" in res_manifest
    assert "characters_tier_1" in res_manifest
    assert "semantic_hashes" in res_manifest

    # 2. 验证 dramas.metadata 包含全局真理源
    drama_row = db_session.execute(text("SELECT metadata FROM dramas WHERE id = 201")).mappings().first()
    assert drama_row is not None
    drama_meta = json.loads(drama_row["metadata"])
    assert "visual_audio_assets_registry" in drama_meta
    assert "CHAR_TEST_T1_BASE_PORTRAIT" in drama_meta["visual_audio_assets_registry"]["characters"]

    # 3. 验证关系表无死锁与脏数据写入
    prop_rows = db_session.execute(text("SELECT * FROM props WHERE drama_id = 201")).mappings().all()
    assert len(prop_rows) == 1
    assert prop_rows[0]["name"] == "玉佩"

    ds_rows = db_session.execute(text("SELECT * FROM prop_damage_states WHERE drama_id = 201")).mappings().all()
    assert len(ds_rows) == 1
    assert ds_rows[0]["state_label"] == "温润有微小裂纹"

    # 4. 验证 prop_detail_views 级联子表
    dv_rows = db_session.execute(text("SELECT * FROM prop_detail_views WHERE damage_state_id = :ds_id"), {"ds_id": ds_rows[0]["id"]}).mappings().all()
    assert len(dv_rows) == 1
    assert dv_rows[0]["view_type"] == "macro_feature"
