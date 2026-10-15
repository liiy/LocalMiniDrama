# -*- coding: utf-8 -*-
"""单元测试：资产血缘图谱 (Asset DAG Lineage) 与四维提示词解耦 (Quad-Prompt Decoupling)。

覆盖能力：
1. AssetProtocolHelper:
   - 标准化业务资产代号生成 (build_benchmark_asset_key)；
   - 资产层级依赖拓扑解析 (resolve_dependency) 与基准标记 (is_benchmark)；
   - 角色/场景/道具生成管线模式 (generation_mode) 与推荐降噪度 (recommended_denoise)；
2. PromptSynthesizer:
   - 角色面部真理锚点抽取 (extract_identity_face_anchor)；
   - 分层增量提示词合成 (synthesize_character_view_prompt / scene / prop)；
   - 四维提示词解构与属性访问兼容性验证 (SynthesizedPrompt)；
   - 排他性全局负向提示词注入 (get_negative_prompt)；
3. DramaStorageAdapter:
   - persist_stage6 深度原子落库：9张业务表完整写入；
   - assets 表统管结构与 DAG 父子指针关联验证。
"""

import json
import pytest
from sqlalchemy import text

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
    VisualAudioAssetsRegistryModel,
)
from app.workflows.utils.asset_protocol import (
    AssetProtocolHelper,
    AssetDependency,
    DEPENDENCY_RULES,
)
from app.workflows.utils.prompt_synthesizer import (
    PromptSynthesizer,
    SynthesizedPrompt,
)
from app.workflows.adapters.drama_storage_adapter import persist_stage6


class TestAssetProtocolHelper:
    """测试资产命名协议与 DAG 依赖解析。"""

    def test_normalize_token(self):
        assert AssetProtocolHelper.normalize_token("沈炼") == "SHENLIAN"
        assert AssetProtocolHelper.normalize_token("废弃驿站") == "FEIQIYIZHAN"
        assert AssetProtocolHelper.normalize_token("绣春刀") == "XIUCHUNDAO"
        assert AssetProtocolHelper.normalize_token("Hero_One") == "HERO_ONE"

    def test_build_benchmark_asset_keys(self):
        char_key = AssetProtocolHelper.build_benchmark_asset_key("character", "沈炼", "T1")
        assert char_key == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"

        scene_key = AssetProtocolHelper.build_benchmark_asset_key("scene", "废弃驿站", "Z01")
        assert scene_key == "ENV_FEIQIYIZHAN_Z01_WIDE"

        prop_key = AssetProtocolHelper.build_benchmark_asset_key("prop", "绣春刀", "S0")
        assert prop_key == "PROP_XIUCHUNDAO_S0_STATIC"

        voice_key = AssetProtocolHelper.build_benchmark_asset_key("voice", "沈炼", "T1")
        assert voice_key == "VOICE_SHENLIAN_T1_MASTER"

    def test_resolve_character_lineage_dag(self):
        # 1. 基准视图 (Level 0): T2I
        dep_base = AssetProtocolHelper.resolve_dependency("CHAR_SHENLIAN_T1_BASE_PORTRAIT")
        assert dep_base is not None
        assert bool(dep_base.is_benchmark) is True
        assert dep_base.parent_asset_id is None
        assert dep_base.parent_asset_key is None
        assert dep_base.generation_mode == "t2i"
        assert dep_base.recommended_denoise == 0.0

        # 2. 定妆全身照 (Level 1): 基于肖像图生图 I2I
        dep_costume = AssetProtocolHelper.resolve_dependency("CHAR_SHENLIAN_T1_BASE_COSTUME")
        assert dep_costume is not None
        assert bool(dep_costume.is_benchmark) is False
        assert dep_costume.parent_asset_key == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
        assert dep_costume.generation_mode == "i2i"
        assert dep_costume.recommended_denoise == 0.45

        # 3. 四视图 (Level 2): 基于全身照 ControlNet
        dep_4v = AssetProtocolHelper.resolve_dependency("CHAR_SHENLIAN_T1_4V_FRONT")
        assert dep_4v is not None
        assert bool(dep_4v.is_benchmark) is False
        assert dep_4v.parent_asset_key == "CHAR_SHENLIAN_T1_BASE_COSTUME"
        assert dep_4v.generation_mode == "controlnet"
        assert dep_4v.control_type == "openpose"
        assert dep_4v.recommended_denoise == 0.40

    def test_resolve_scene_and_prop_lineage_dag(self):
        # 场景 Wide 主空全景 (基准) 与 OTS 背景切片
        dep_scene_wide = AssetProtocolHelper.resolve_dependency("ENV_STATION_Z01_WIDE")
        assert bool(dep_scene_wide.is_benchmark) is True
        assert dep_scene_wide.generation_mode == "t2i"

        dep_scene_ots = AssetProtocolHelper.resolve_dependency("ENV_STATION_Z01_OTS_BG")
        assert bool(dep_scene_ots.is_benchmark) is False
        assert dep_scene_ots.parent_asset_key == "ENV_STATION_Z01_WIDE"
        assert dep_scene_ots.generation_mode == "depth_blur"
        assert dep_scene_ots.recommended_denoise == 0.30

        # 道具 Static 孤立物证 (基准) 与 Action 交互实拍
        dep_prop_static = AssetProtocolHelper.resolve_dependency("PROP_DAGGER_S0_STATIC")
        assert bool(dep_prop_static.is_benchmark) is True
        assert dep_prop_static.generation_mode == "t2i"

        dep_prop_action = AssetProtocolHelper.resolve_dependency("PROP_DAGGER_S1_ACTION")
        assert bool(dep_prop_action.is_benchmark) is False
        assert dep_prop_action.parent_asset_key == "PROP_DAGGER_S1_STATIC"
        assert dep_prop_action.generation_mode == "inpaint"
        assert dep_prop_action.recommended_denoise == 0.50


class TestPromptSynthesizer:
    """测试提示词解耦、合成与双向兼容性。"""

    def test_extract_identity_face_anchor(self):
        desc = "剑眉星目，面部轮廓刚毅如刀削，右眉有一道一寸长的浅疤痕。身穿黑色飞鱼服，腰系鸾带。"
        anchor = PromptSynthesizer.extract_identity_face_anchor({"appearance": desc})
        assert "剑眉星目" in anchor
        assert "疤痕" in anchor
        assert "飞鱼服" not in anchor

    def test_character_prompt_synthesis_quad_dimensions(self):
        face_anchor = "sharp facial features, stern gaze, distinct cheek scar"
        costume_desc = "embroidered dark silk Ming dynasty officer uniform, silver belt"
        synth = PromptSynthesizer.synthesize_character_view_prompt(
            character_or_identity={"appearance": face_anchor},
            costume_prompt=costume_desc,
            view_type="BASE_PORTRAIT",
        )

        # 验证 2-tuple 解构兼容性
        delta_p, visual_p = synth
        assert delta_p == synth.delta_prompt
        assert visual_p == synth.visual_prompt

        # 验证四维属性访问
        assert synth.identity_prompt != ""
        assert "neutral frontal headshot portrait" in synth.delta_prompt
        assert "East Asian Chinese biological features" in synth.visual_prompt
        assert synth.negative_prompt != ""
        assert "deformed face" in synth.negative_prompt

    def test_scene_and_prop_prompt_synthesis(self):
        scene_synth = PromptSynthesizer.synthesize_scene_view_prompt(
            scene_or_prompt="abandoned wooden post station in snowy night",
            view_type="OTS_BG",
            weathering_prompt="frost on window frames, melting snow stains",
        )
        assert "over-the-shoulder conversation background plate" in scene_synth.delta_prompt
        assert "bokeh blur" in scene_synth.visual_prompt
        assert "crooked architecture" in scene_synth.negative_prompt

        prop_synth = PromptSynthesizer.synthesize_prop_view_prompt(
            prop_or_prompt="Ming dynasty steel saber with damascus pattern",
            view_type="STATIC",
        )
        assert "isolated hero prop studio shot" in prop_synth.delta_prompt
        assert "neutral dark gray backdrop" in prop_synth.visual_prompt
        assert "deformed object" in prop_synth.negative_prompt


class TestDramaStorageAdapterLineagePersistence:
    """测试 persist_stage6 数据库原子持久化及血缘关系落库。"""

    def test_atomic_persistence_with_lineage(self, db_session):
        db = db_session
        drama_id = 202

        # 准备 Drama 与 Episode
        db.execute(text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (202, '绣春刀传奇', 'draft', '', '')"))
        db.execute(text("INSERT INTO episodes (id, drama_id, episode_number, title, created_at, updated_at) VALUES (2001, 202, 1, '第1集', '', '')"))
        db.commit()

        # 构建包含血缘关系的 Manifest
        manifest = EpisodeResourceManifest(
            episode_num=1,
            characters=[
                {
                    "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "character_name": "沈炼",
                    "role": "protagonist",
                    "stage_name": "锦衣卫常规巡查形态",
                    "visual_prompt": "神色冷峻，双目如鹰，身着玄黑锦衣卫飞鱼服",
                    "voice_style": "低沉磁性冷峻",
                }
            ],
            environments=[
                {
                    "scene_id": "ENV_STATION_Z01_WIDE",
                    "scene_name": "雪夜古驿站",
                    "time_lighting": "寒冬暴雪深夜，暗淡烛火",
                    "weathering_applied": ["木质腐朽", "窗檐积雪挂冰"],
                    "visual_prompt": "寒风怒号的破落驿站大堂全景",
                }
            ],
            props=[
                {
                    "prop_id": "PROP_SWORD_S0_STATIC",
                    "prop_name": "绣春刀",
                    "damage_state": "刀刃带有轻微缺口",
                    "damage_level": 1,
                    "visual_prompt": "明代制式绣春刀孤立陈列特写",
                }
            ],
            audio=[
                {
                    "voice_id": "VOICE_SHENLIAN_T1_MASTER",
                    "character_name": "沈炼",
                    "timbre": "磁性低沉中年男声",
                }
            ],
            newly_generated_assets=[
                {
                    "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "name": "沈炼基准立绘",
                    "category": "character",
                    "type": "image",
                    "is_benchmark": 1,
                    "generation_mode": "t2i",
                },
                {
                    "asset_id": "ENV_XUEYEGUYIZHAN_Z01_WIDE",
                    "name": "雪夜古驿站全景",
                    "category": "environment",
                    "type": "image",
                    "is_benchmark": 1,
                    "generation_mode": "t2i",
                },
                {
                    "asset_id": "PROP_XIUCHUNDAO_S0_STATIC",
                    "name": "绣春刀",
                    "category": "prop",
                    "type": "image",
                    "is_benchmark": 1,
                    "generation_mode": "t2i",
                },
            ],
        )

        state = IndustrialDramaMasterState(
            drama_id=drama_id,
            current_visual_episode=1,
            episode_manifests={1: manifest},
        )

        # 执行持久化
        persist_stage6(db, drama_id=drama_id, state=state, episode_num=1)

        # 验证 1: characters 表基准资产
        char = db.execute(text("SELECT * FROM characters WHERE drama_id = 202")).mappings().first()
        assert char is not None
        assert char["name"] == "沈炼"
        assert char["benchmark_asset_key"] == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
        assert char["appearance"] is not None

        # 验证 2: character_stage_views 四视图与基准肖像落库
        views = db.execute(text("SELECT * FROM character_stage_views ORDER BY id ASC")).mappings().all()
        assert len(views) >= 1
        portrait_v = views[0]
        assert portrait_v["is_benchmark"] == 1
        assert portrait_v["generation_mode"] == "t2i"
        assert portrait_v["parent_asset_key"] is None
        assert portrait_v["image_prompt"] is not None

        # 验证 3: scenes, scene_zones 与 weathering_views
        scenes = db.execute(text("SELECT * FROM scenes WHERE drama_id = 202")).mappings().all()
        assert len(scenes) == 1
        assert scenes[0]["benchmark_asset_key"] == "ENV_XUEYEGUYIZHAN_Z01_WIDE"

        w_views = db.execute(text("SELECT * FROM scene_weathering_views")).mappings().all()
        assert len(w_views) == 2
        assert all(w["parent_asset_key"] == "ENV_XUEYEGUYIZHAN_Z01_WIDE" for w in w_views)
        assert all(w["generation_mode"] in ("i2i", "controlnet") for w in w_views)

        # 验证 4: props 与 prop_damage_states / prop_detail_views
        props = db.execute(text("SELECT * FROM props WHERE drama_id = 202")).mappings().all()
        assert len(props) == 1
        assert props[0]["benchmark_asset_key"] == "PROP_XIUCHUNDAO_S0_STATIC"

        d_states = db.execute(text("SELECT * FROM prop_damage_states WHERE drama_id = 202")).mappings().all()
        assert len(d_states) == 1
        assert d_states[0]["state_label"] == "刀刃带有轻微缺口"

        p_views = db.execute(text("SELECT * FROM prop_detail_views")).mappings().all()
        assert len(p_views) >= 1
        assert p_views[0]["parent_asset_key"] == "PROP_XIUCHUNDAO_S0_STATIC"
        assert p_views[0]["generation_mode"] in ("crop_macro", "inpaint", "i2i")

        # 验证 5: assets 统管素材库落库与血缘关系
        asset_rows = db.execute(text("SELECT * FROM assets WHERE drama_id = 202 ORDER BY id ASC")).mappings().all()
        assert len(asset_rows) >= 3
        benchmarks = [a for a in asset_rows if a["is_benchmark"] == 1]
        assert len(benchmarks) >= 3  # 角色肖像基准、场景全景基准、道具静态基准、声音母卡基准

        # 验证 assets 表中提示词与负向提示词已写入
        for a in asset_rows:
            assert a["negative_prompt"] is not None
            assert a["prompt"] is not None
            assert a["generation_mode"] in ("t2i", "i2i", "controlnet", "inpaint", "depth_blur", "tts_master")
