"""阶段 6 资产真理源全面落库专项强化验证测试 (Stage 6 Full Persistence Enhancements Tests)。

验证范围：
1. 数据库 schema 列扩展校验（assets 5 列、character_voice_profiles.is_master_card、character_stages 2 列、prop_damage_states.parent_state_id）；
2. assets 表完整入库校验（asset_key, prompt, negative_prompt, params, metadata, type, category）；
3. character_stages 的 stage_code 与 parent_stage_id 继承树写入；
4. character_voice_profiles 的 is_master_card 标记正确性；
5. prop_damage_states 的 parent_state_id 剧情演进链追溯；
6. episodes.ast_blocks['episode_resource_manifest'] 的 lineage_dag 与 reused_existing_assets 完整保存；
7. dramas.metadata['asset_lineage_dag'] 全剧血缘 DAG 聚合合并；
8. TwoJourneyRunner 状态机更新时 newly_generated_assets / reused_existing_assets 无损传递。
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import text

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    GlobalDramaMasterState,
    IndustrialDramaMasterState,
)
from app.workflows.adapters.drama_storage_adapter import persist_stage6
from app.workflows.two_journey_runner import TwoJourneyRunner


def test_stage6_full_persistence_enhancements(db_session):
    """测试阶段 6 增强版全要素落库。"""
    # 1. 准备初始短剧与剧集记录
    db_session.execute(
        text("INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) VALUES (888, '九龙夺嫡', 'draft', '{}', '', '')")
    )
    db_session.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, ast_blocks, created_at, updated_at) VALUES (8881, 888, 1, '第1集：潜龙在渊', '{}', '', '')")
    )
    db_session.commit()

    # 2. 模拟 Stage 6 结构化产出数据
    manifest_data = {
        "episode_num": 1,
        "characters": [
            {
                "char_id": "CHAR_YINZHEN_T1_BASE_PORTRAIT",
                "character_name": "胤禛",
                "role": "protagonist",
                "stage_name": "四阿哥常服",
                "stage_code": "STAGE_PRINCE_NORMAL",
                "visual_prompt": "清代皇子藏青色常服，沉着隐忍，目光深邃，8k超清",
                "voice_style": "沉稳内敛有威严",
            },
            {
                "char_id": "CHAR_YINZHEN_T1_BASE_COSTUME",
                "character_name": "胤禛",
                "role": "protagonist",
                "stage_name": "四阿哥雨中跪奏造型",
                "stage_code": "STAGE_PRINCE_KNEELING",
                "parent_asset_id": "STAGE_PRINCE_NORMAL",
                "visual_prompt": "大雨倾盆中跪在御道，浑身湿透，眼神坚毅不屈",
                "voice_style": "克制喘息",
            },
        ],
        "environments": [
            {
                "scene_id": "ENV_STUDY_T1_WIDE",
                "scene_name": "雍亲王府书房",
                "time_lighting": "雪夜烛光",
                "weathering_applied": ["书桌墨迹干涸", "窗纸破损透风"],
                "visual_prompt": "深色木质书房，案头堆满文书，灯火微弱，窗外风雪交加",
            }
        ],
        "props": [
            {
                "prop_id": "PROP_SEAL_T1_STATIC",
                "prop_name": "白玉螭钮私印",
                "damage_state": "完好状态",
                "damage_level": 1,
                "visual_prompt": "温润和田白玉印章，螭龙盘踞，无任何瑕疵",
            },
            {
                "prop_id": "PROP_SEAL_T1_DAMAGE",
                "prop_name": "白玉螭钮私印",
                "damage_state": "边角磕损染血",
                "parent_state_label": "完好状态",
                "damage_level": 3,
                "narrative_point": "第1集末尾争执中摔落台阶磕掉一角，染上朱砂血痕",
                "visual_prompt": "特写镜头，白玉印章右下角崩裂缺损，带有暗红血渍痕迹",
            },
        ],
    }

    new_assets = [
        {
            "asset_id": "CHAR_YINZHEN_T1_BASE_PORTRAIT",
            "name": "胤禛0号基准肖像",
            "category": "character",
            "prompt": "清代皇子藏青色常服，沉着隐忍，目光深邃，8k超清",
            "negative_prompt": "现代发型, 模糊, 扭曲",
            "generation_method": "text_to_image",
            "aspect_ratio": "9:16",
            "semantic_hash": "hash_char_yinzhen_portrait",
            "lifecycle_status": "APPROVED",
        },
        {
            "asset_id": "CHAR_YINZHEN_T1_BASE_COSTUME",
            "name": "胤禛雨中跪奏造型",
            "category": "character",
            "prompt": "大雨倾盆中跪在御道，浑身湿透，眼神坚毅不屈",
            "negative_prompt": "雨伞, 干燥",
            "generation_method": "image_to_image",
            "input_source_image": "CHAR_YINZHEN_T1_BASE_PORTRAIT",
            "denoising_strength": 0.45,
            "aspect_ratio": "9:16",
            "semantic_hash": "hash_char_yinzhen_costume",
            "lifecycle_status": "READY",
        },
        {
            "asset_id": "PROP_SEAL_T1_STATIC",
            "name": "白玉螭钮私印初始态",
            "category": "prop",
            "prompt": "温润和田白玉印章，螭龙盘踞，无任何瑕疵",
            "generation_method": "text_to_image",
            "semantic_hash": "hash_prop_seal_static",
            "lifecycle_status": "APPROVED",
        },
    ]

    reused_assets = [
        {
            "asset_id": "ENV_PALACE_GATE_T1_WIDE",
            "type": "environment_base",
            "usage_in_current_ep": "午门广场远景复用",
            "lifecycle_status": "APPROVED",
            "semantic_hash": "hash_palace_gate",
        }
    ]

    master_voice_cards = [
        {
            "character_id": "CHAR_YINZHEN",
            "character_name": "胤禛",
            "master_voice_id": "VOICE_YINZHEN_T1_MASTER",
            "master_tts_prompt": "低沉平缓，每一个字都极具分量与压迫感",
            "timbre": "磁性低沉中年帝王音",
            "voice_file_path": "audio_mastering/voices/VOICE_YINZHEN_T1_MASTER.wav",
            "semantic_hash": "hash_voice_master_yinzhen",
            "lifecycle_status": "READY",
        }
    ]

    lineage_dag = {
        "CHAR_YINZHEN_T1_BASE_COSTUME": "CHAR_YINZHEN_T1_BASE_PORTRAIT",
        "PROP_SEAL_T1_DAMAGE": "PROP_SEAL_T1_STATIC",
    }

    state = GlobalDramaMasterState(
        drama_id=888,
        current_visual_episode=1,
        episode_resource_manifests={1: EpisodeResourceManifest.model_validate(manifest_data)},
        newly_generated_assets=new_assets,
        reused_existing_assets=reused_assets,
        new_character_master_voice_cards=master_voice_cards,
        lineage_dag=lineage_dag,
    )

    # 3. 执行 persist_stage6 原子落库
    persist_stage6(db_session, drama_id=888, state=state, episode_num=1)

    # 4. 断言 1: assets 表成功落库 4 项素材 (包含 3 个新资产和 1 个母音卡)
    assets_rows = db_session.execute(
        text("SELECT asset_key, name, type, category, prompt, negative_prompt, params, metadata FROM assets WHERE drama_id = 888 ORDER BY id ASC")
    ).mappings().all()
    assert len(assets_rows) >= 3

    asset_keys = {r["asset_key"] for r in assets_rows}
    assert "CHAR_YINZHEN_T1_BASE_PORTRAIT" in asset_keys
    assert "CHAR_YINZHEN_T1_BASE_COSTUME" in asset_keys
    assert "PROP_SEAL_T1_STATIC" in asset_keys
    assert "VOICE_YINZHEN_T1_MASTER" in asset_keys

    costume_asset = next(r for r in assets_rows if r["asset_key"] == "CHAR_YINZHEN_T1_BASE_COSTUME")
    assert costume_asset["type"] == "image"
    assert costume_asset["category"] == "character"
    assert "大雨倾盆" in costume_asset["prompt"]
    assert "雨伞" in costume_asset["negative_prompt"]
    c_params = json.loads(costume_asset["params"])
    assert c_params["input_source_image"] == "CHAR_YINZHEN_T1_BASE_PORTRAIT"
    assert c_params["denoising_strength"] == 0.45
    c_meta = json.loads(costume_asset["metadata"])
    assert c_meta["parent_asset_id"] == "CHAR_YINZHEN_T1_BASE_PORTRAIT"
    assert c_meta["episode_num"] == 1

    # 5. 断言 2: character_stages 包含 stage_code 与 parent_stage_id 继承
    stages_rows = db_session.execute(
        text("SELECT id, stage_name, stage_code, parent_stage_id FROM character_stages WHERE drama_id = 888 ORDER BY id ASC")
    ).mappings().all()
    assert len(stages_rows) >= 2
    normal_stage = next(s for s in stages_rows if s["stage_code"] == "STAGE_PRINCE_NORMAL")
    kneeling_stage = next(s for s in stages_rows if s["stage_code"] == "STAGE_PRINCE_KNEELING")
    assert kneeling_stage["parent_stage_id"] == normal_stage["id"]

    # 6. 断言 3: character_voice_profiles 区分母音卡 is_master_card
    vp_rows = db_session.execute(
        text("SELECT voice_id, character_name, is_master_card FROM character_voice_profiles WHERE drama_id = 888")
    ).mappings().all()
    assert len(vp_rows) >= 1
    master_vp = next((vp for vp in vp_rows if vp["voice_id"] == "VOICE_YINZHEN_T1_MASTER"), None)
    assert master_vp is not None
    assert master_vp["is_master_card"] == 1

    # 7. 断言 4: prop_damage_states 包含 parent_state_id 演进链
    pds_rows = db_session.execute(
        text("SELECT id, state_label, damage_level, parent_state_id FROM prop_damage_states WHERE drama_id = 888 ORDER BY id ASC")
    ).mappings().all()
    assert len(pds_rows) >= 2
    initial_pds = next(p for p in pds_rows if p["state_label"] == "完好状态")
    damage_pds = next(p for p in pds_rows if p["state_label"] == "边角磕损染血")
    assert damage_pds["parent_state_id"] == initial_pds["id"]

    # 8. 断言 5: episodes.ast_blocks['episode_resource_manifest'] 包含 lineage_dag 与 reused_existing_assets
    ep_row = db_session.execute(text("SELECT ast_blocks FROM episodes WHERE id = 8881")).mappings().first()
    ast_blocks = json.loads(ep_row["ast_blocks"])
    saved_manifest = ast_blocks["episode_resource_manifest"]
    assert "lineage_dag" in saved_manifest
    assert saved_manifest["lineage_dag"]["CHAR_YINZHEN_T1_BASE_COSTUME"] == "CHAR_YINZHEN_T1_BASE_PORTRAIT"
    assert "reused_existing_assets" in saved_manifest
    assert any(ra.get("asset_id") == "ENV_PALACE_GATE_T1_WIDE" for ra in saved_manifest["reused_existing_assets"])

    # 9. 断言 6: dramas.metadata 聚合了 asset_lineage_dag
    drama_row = db_session.execute(text("SELECT metadata FROM dramas WHERE id = 888")).mappings().first()
    d_meta = json.loads(drama_row["metadata"])
    assert "asset_lineage_dag" in d_meta
    assert d_meta["asset_lineage_dag"]["PROP_SEAL_T1_DAMAGE"] == "PROP_SEAL_T1_STATIC"


def test_stage6_unregistered_character_onboarding_and_v2_voice_synthesis(db_session, tmp_path):
    """验证阶段 6 未注册分集新角色按【阶段 2 工业级 11 维标准】入册、V2 音色卡及母音频合成联动。"""
    from app.services import audio_design_service as audioDesignService
    from app.workflows.adapters.drama_storage_adapter import persist_stage2

    # 1. 初始化短剧与第 1 集（先通过阶段 2 注册男主陆沉）
    db_session.execute(
        text(
            "INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) "
            "VALUES (901, '暗夜追凶', 'draft', '{}', '', '')"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO episodes (id, drama_id, episode_number, title, script_content, ast_blocks, created_at, updated_at) "
            "VALUES (9011, 901, 1, '第1集：夜审码头证人', "
            "'[声学行为: 开场突发重击 Braam Hit]\n【音效：低频心跳声骤停】\n陆沉（冷笑）：你以为闭嘴就能活命？\n周老四（声音发颤）：陆哥，这事儿真不能沾边，码头那辆黑车我只看清了半个车牌！\n陆沉一把撕开带血信封，火漆碎裂成屑。', "
            "'{}', '', '')"
        )
    )
    db_session.commit()

    # 阶段 2 先注册主角陆沉
    stage2_state = GlobalDramaMasterState(
        drama_id=901,
        character_dossiers={
            "CHAR_LUCHEN": {
                "character_code": "CHAR_LUCHEN",
                "name": "陆沉",
                "gender": "male",
                "perceived_age": 29,
                "role": "protagonist",
                "personality": "冷峻隐忍、观察力极强",
                "appearance": "黑色风衣，骨相深邃",
                "identity_anchors": ["黑色长风衣", "银质旧怀表"],
                "visual_consistency_code": {
                    "facial_bone_structure": "棱角分明冷白皮",
                    "stage_a_clothing": "黑色修身羊毛风衣",
                },
                "voice_style": "低沉颗粒感男中音",
                "acoustic_persona": {
                    "vocal_position": "胸腔深沉共鸣",
                    "vocal_flaws": "尾音极轻微沙砾感",
                    "stress_action": "拇指摩挲怀表表盖",
                },
                "psychology_4": {
                    "lie": "独自一人能查清真相",
                    "truth": "必须学会信任同伴",
                    "ghost": "五年前搭档失踪",
                    "want_vs_need": "追查真凶 vs 放下执念",
                },
                "voice_fingerprint": {
                    "sentence_length": "短句冷冽",
                    "catchphrase": "证据不会撒谎。",
                    "defensive_phrase": "与你无关。",
                    "forbidden_words": ["害怕"],
                },
                "carried_anchor_item": "银质旧怀表",
                "drama_engine": "复仇与追凶核心驱动",
            }
        },
        relationship_matrix=[],
    )
    persist_stage2(db_session, drama_id=901, state=stage2_state)

    # 验证阶段 2 已为陆沉生成 V2 基础音色卡记录
    luchen_vp = db_session.execute(
        text("SELECT * FROM character_voice_profiles WHERE drama_id = 901 AND character_code = 'CHAR_LUCHEN'")
    ).mappings().first()
    assert luchen_vp is not None
    assert luchen_vp["master_voice_key"] == "VOICE_LUCHEN_T1_MASTER"
    assert luchen_vp["vocal_position"] == "胸腔深沉共鸣"

    # 2. 调用阶段 6 增量审计服务：剧本中出现了阶段 2 未登记的新角色“周老四”，且命中破坏动词“撕开/碎裂”
    audit_res = audioDesignService.run_stage6_incremental_audit(
        db_session,
        drama_id=901,
        episode_num=1,
        payload={"auto_synthesize_master_voice": True},
        storage_base=str(tmp_path),
    )

    assert audit_res["drama_id"] == 901
    assert audit_res["episode_num"] == 1
    assert audit_res["newly_discovered_characters_count"] == 1
    onboarded_names = [c["name"] for c in audit_res["newly_discovered_characters"]]
    assert onboarded_names == ["周老四"]
    assert "[声学行为" not in onboarded_names
    assert "音效" not in onboarded_names

    # 3. 验证“周老四”已按阶段 2 的 11 维标准写入 characters / character_stages / character_stage_views / character_relationship / character_voice_profiles
    zhou_char = db_session.execute(
        text("SELECT * FROM characters WHERE drama_id = 901 AND name = '周老四' AND deleted_at IS NULL")
    ).mappings().first()
    assert zhou_char is not None
    assert zhou_char["character_code"].startswith("CHAR_")
    zhou_code = zhou_char["character_code"]
    # 验证所有 MySQL JSON 列在写入数据库后均为合法 JSON 字符串（不会触发 MySQL Error 3140）
    for json_col in (
        "identity_anchors",
        "visual_consistency_code",
        "carried_anchor_item",
        "drama_engine",
        "growth_chain",
        "current_status",
        "psychology_4",
        "acoustic_persona",
        "voice_fingerprint",
    ):
        raw_col_val = zhou_char[json_col]
        assert raw_col_val is not None and str(raw_col_val).strip() != ""
        parsed_col = json.loads(raw_col_val)
        assert isinstance(parsed_col, (dict, list))
    assert "facial_bone_structure" in json.loads(zhou_char["visual_consistency_code"])
    assert zhou_char["psychology_4"] is not None and "lie" in zhou_char["psychology_4"]
    assert zhou_char["voice_fingerprint"] is not None and "catchphrase" in zhou_char["voice_fingerprint"]
    assert zhou_char["acoustic_persona"] is not None and "vocal_position" in zhou_char["acoustic_persona"]

    # 验证阶段 0 默认基准阶段与 T1 视觉母盘已创建
    zhou_stage = db_session.execute(
        text("SELECT * FROM character_stages WHERE drama_id = 901 AND character_id = :cid"),
        {"cid": zhou_char["id"]},
    ).mappings().first()
    assert zhou_stage is not None

    zhou_views = db_session.execute(
        text("SELECT * FROM character_stage_views WHERE character_stage_id = :sid"),
        {"sid": zhou_stage["id"]},
    ).mappings().all()
    assert len(zhou_views) >= 1

    # 验证与主角的关系网已级联补录到 character_relationship
    rel_rows = db_session.execute(
        text("SELECT * FROM character_relationship WHERE drama_id = 901 AND character_a_code = :ccode"),
        {"ccode": zhou_code},
    ).mappings().all()
    assert len(rel_rows) >= 1

    # 验证 dramas.metadata['character_tokens'] 已同步注册新角色 Token
    drama_meta_row = db_session.execute(text("SELECT metadata FROM dramas WHERE id = 901")).mappings().first()
    drama_meta = json.loads(drama_meta_row["metadata"])
    token_names = [
        (ct.get("name") or ct.get("character_name") or "")
        for ct in drama_meta.get("character_tokens", [])
        if isinstance(ct, dict)
    ]
    assert "周老四" in token_names

    # 4. 验证 V2 音色卡与母音频文件已自动合成并四表联动落盘
    zhou_vp = audioDesignService.get_or_init_character_voice_profile(db_session, 901, zhou_char["id"])
    assert zhou_vp["master_voice_key"].startswith("VOICE_")
    assert zhou_vp["master_Sample_text"] if "master_Sample_text" in zhou_vp else zhou_vp["master_sample_text"]
    assert "（" not in zhou_vp["master_sample_text"] and "(" not in zhou_vp["master_sample_text"]
    assert zhou_vp["synthesis_status"] == "CERTIFIED"
    assert zhou_vp["sample_audio_url"].startswith("/static/audio/voices/VOICE_")
    assert isinstance(zhou_vp["emotion_rules"], dict)
    assert "calm_suppressed" in zhou_vp["emotion_rules"]

    # 验证 audio_generations 表写入了 master_voice_reference 记录
    ag_row = db_session.execute(
        text(
            "SELECT * FROM audio_generations WHERE drama_id = 901 AND character_id = :cid AND audio_type = 'master_voice_reference'"
        ),
        {"cid": zhou_char["id"]},
    ).mappings().first()
    assert ag_row is not None
    assert ag_row["status"] == "completed"

    # 验证 characters.seedance2_voice_asset 已回写认证母音引用
    zhou_char_refreshed = db_session.execute(
        text("SELECT seedance2_voice_asset FROM characters WHERE id = :cid"),
        {"cid": zhou_char["id"]},
    ).mappings().first()
    sd2_asset = json.loads(zhou_char_refreshed["seedance2_voice_asset"])
    assert sd2_asset["status"] == "certified"
    assert sd2_asset["master_voice_key"] == zhou_vp["master_voice_key"]

    # 5. 测试独立手动入册接口服务 onboard_unregistered_episode_character 与音色卡微调
    onboard_manual = audioDesignService.onboard_unregistered_episode_character(
        db_session,
        drama_id=901,
        episode_num=1,
        payload={
            "character_name": "林法医",
            "role": "supporter",
            "gender": "female",
            "perceived_age": 31,
            "context_lines": ["林法医（推了推眼镜）：死者指甲缝里的纤维，和三号船坞的缆绳完全一致。"],
            "auto_synthesize_master_voice": True,
        },
        storage_base=str(tmp_path),
    )
    assert onboard_manual["character_name"] == "林法医"
    assert onboard_manual["master_voice_synthesis"] is not None
    assert onboard_manual["master_voice_synthesis"]["synthesis_status"] == "CERTIFIED"

    # 微调林法医的 V2 音色卡并重新合成
    lin_cid = onboard_manual["character_id"]
    updated_vp = audioDesignService.update_character_voice_profile_by_char(
        db_session,
        drama_id=901,
        character_id=lin_cid,
        payload={
            "timbre_archetype": "cold_alto_crisp",
            "vocal_position": "鼻咽腔清冷共鸣",
            "master_sample_text": "解剖刀不会骗人，死者指甲缝里的缆绳纤维就是铁证。",
            "speed_ratio": 0.96,
        },
    )
    assert updated_vp["timbre_archetype"] == "cold_alto_crisp"
    assert updated_vp["vocal_position"] == "鼻咽腔清冷共鸣"
    assert updated_vp["synthesis_status"] == "READY"

    resynth = audioDesignService.synthesize_character_master_voice(
        db_session,
        drama_id=901,
        character_id=lin_cid,
        payload={},
        storage_base=str(tmp_path),
    )
    assert resynth["synthesis_status"] == "CERTIFIED"
    assert resynth["sample_duration_sec"] > 0

