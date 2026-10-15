"""【单测】二阶/三阶资产防退化为文生图 (Anti-T2I Degradation) 专项测试套件。

覆盖范围：
1. AssetProtocolHelper：二阶/三阶角色、场景、道具绝对禁止生成 t2i，自动继承对应 T1 根基准；
2. 非规范拼写自愈引擎：对包含 STAGE_2、自定义后缀等的二阶/三阶资产强力纠偏为 i2i 且挂载 T1 锚点；
3. Stage 6 资产规范化防线：_ensure_standard_asset 与 lineage_dag 拦截非法 t2i 并保留 T2/T3 肖像继承边；
4. DramaStorageAdapter：character_stage_views 针对 Stage 2/3 main_portrait 锁定 i2i 并锚定 T1，统管 assets 落库自动救援孤儿资产与拦截 t2i。
"""

import json
import pytest
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.nodes.stage6_asset_truth import _ensure_standard_asset


class TestAssetProtocolAntiT2IDegradation:
    """验证资产协议层彻底阻断二阶与三阶资产退化为 t2i。"""

    def test_tier1_character_root_is_t2i_benchmark(self):
        """一阶角色基准肖像保持唯一的文生图根节点。"""
        dep = AssetProtocolHelper.resolve_dependency("CHAR_LUCHEN_T1_BASE_PORTRAIT")
        assert dep.generation_mode == "t2i"
        assert dep.parent_asset_id is None
        assert dep.is_benchmark == 1
        assert dep.recommended_denoise == 0.0

    def test_tier2_and_tier3_character_portraits_are_i2i(self):
        """二阶与三阶换装主肖像必须为图生图 (i2i)，父级必须为 T1 基准肖像，严禁退化为 t2i。"""
        # T2 阶段换装肖像
        dep_t2 = AssetProtocolHelper.resolve_dependency("CHAR_LUCHEN_T2_BASE_PORTRAIT")
        assert dep_t2.generation_mode == "i2i"
        assert dep_t2.parent_asset_id == "CHAR_LUCHEN_T1_BASE_PORTRAIT"
        assert dep_t2.is_benchmark == 0
        assert dep_t2.recommended_denoise == 0.35

        # T3 极化/终局阶段换装肖像
        dep_t3 = AssetProtocolHelper.resolve_dependency("CHAR_LUCHEN_T3_BASE_PORTRAIT")
        assert dep_t3.generation_mode == "i2i"
        assert dep_t3.parent_asset_id == "CHAR_LUCHEN_T1_BASE_PORTRAIT"
        assert dep_t3.is_benchmark == 0
        assert dep_t3.recommended_denoise == 0.35

    def test_environment_tier_progression(self):
        """场景资产：T1/Z01 广角为 t2i 基准；T2/Z02 等演化广角必须为 i2i 并继承 T1。"""
        dep_env_t1 = AssetProtocolHelper.resolve_dependency("ENV_WAREHOUSE_T1_WIDE")
        assert dep_env_t1.generation_mode == "t2i"
        assert dep_env_t1.parent_asset_id is None
        assert dep_env_t1.is_benchmark == 1

        # T2 场景
        dep_env_t2 = AssetProtocolHelper.resolve_dependency("ENV_WAREHOUSE_T2_WIDE")
        assert dep_env_t2.generation_mode == "i2i"
        assert dep_env_t2.parent_asset_id == "ENV_WAREHOUSE_T1_WIDE"
        assert dep_env_t2.is_benchmark == 0
        assert dep_env_t2.recommended_denoise == 0.45

        # Z02 区域场景
        dep_env_z2 = AssetProtocolHelper.resolve_dependency("ENV_WAREHOUSE_Z02_WIDE")
        assert dep_env_z2.generation_mode == "i2i"
        assert dep_env_z2.parent_asset_id == "ENV_WAREHOUSE_Z01_WIDE"
        assert dep_env_z2.is_benchmark == 0

    def test_prop_tier_progression(self):
        """道具资产：S0/T1 静态图为 t2i 基准；S1/S2/T2 战损及动作形态必须为 i2i 或 inpaint，严禁 t2i。"""
        # S0 静态
        dep_prop_s0 = AssetProtocolHelper.resolve_dependency("PROP_SWORD_S0_STATIC")
        assert dep_prop_s0.generation_mode == "t2i"
        assert dep_prop_s0.parent_asset_id is None
        assert dep_prop_s0.is_benchmark == 1

        # S2 战损破损
        dep_prop_s2 = AssetProtocolHelper.resolve_dependency("PROP_SWORD_S2_STATIC")
        assert dep_prop_s2.generation_mode == "i2i"
        assert dep_prop_s2.parent_asset_id == "PROP_SWORD_S0_STATIC"
        assert dep_prop_s2.is_benchmark == 0

        # T2 道具
        dep_prop_t2 = AssetProtocolHelper.resolve_dependency("PROP_SWORD_T2_STATIC")
        assert dep_prop_t2.generation_mode == "i2i"
        assert dep_prop_t2.parent_asset_id == "PROP_SWORD_T1_STATIC"
        assert dep_prop_t2.is_benchmark == 0

    def test_non_standard_fuzzy_healing(self):
        """非标准拼写命名（如 STAGE_2 或特殊后缀）自愈后严禁退化为 t2i。"""
        # 角色非标命名
        dep_char_fuzzy = AssetProtocolHelper.resolve_dependency("CHAR_LINWAN_STAGE_2_MAIN_PORTRAIT")
        assert dep_char_fuzzy.generation_mode == "i2i"
        assert dep_char_fuzzy.parent_asset_id == "CHAR_LINWAN_T1_BASE_PORTRAIT"
        assert dep_char_fuzzy.is_benchmark == 0

        # 道具非标命名
        dep_prop_fuzzy = AssetProtocolHelper.resolve_dependency("PROP_JADE_STAGE_2_BROKEN")
        assert dep_prop_fuzzy.generation_mode == "i2i"
        assert dep_prop_fuzzy.parent_asset_id == "PROP_JADE_T1_STATIC"
        assert dep_prop_fuzzy.is_benchmark == 0


class TestStage6EnsureStandardAssetGuard:
    """验证阶段 6 节点中的 _ensure_standard_asset 规范化纠偏函数。"""

    def test_ensure_standard_asset_corrects_hallucinated_t2i_on_t2(self):
        """如果上游或 LLM 对二阶资产生成了 t2i 模式且无 parent，_ensure_standard_asset 强制纠偏为 i2i 并挂载父资产。"""
        raw_item = {
            "asset_id": "CHAR_LUCHEN_T2_BASE_PORTRAIT",
            "generation_mode": "t2i",  # 模拟 LLM 错误声明为 t2i
            "parent_asset_key": None,
            "is_benchmark": 1,
        }
        cleansed = _ensure_standard_asset(raw_item, "CHAR", {"LUCHEN"})

        assert cleansed["generation_mode"] == "i2i"
        assert cleansed["parent_asset_key"] == "CHAR_LUCHEN_T1_BASE_PORTRAIT"
        assert cleansed["parent_asset_id"] == "CHAR_LUCHEN_T1_BASE_PORTRAIT"
        assert cleansed["is_benchmark"] == 0
        assert cleansed["denoise_strength"] == 0.35

    def test_ensure_standard_asset_preserves_t1_benchmark(self):
        """一阶基准肖像保持 t2i，且父级为 None。"""
        raw_item = {
            "asset_id": "CHAR_LUCHEN_T1_BASE_PORTRAIT",
            "generation_mode": "t2i",
            "parent_asset_key": None,
        }
        cleansed = _ensure_standard_asset(raw_item, "CHAR", {"LUCHEN"})

        assert cleansed["generation_mode"] == "t2i"
        assert cleansed["parent_asset_key"] is None
        assert cleansed["is_benchmark"] == 1
        assert cleansed["denoise_strength"] == 0.0


class TestStorageAdapterAntiT2IDegradation:
    """验证持久化适配器层 (DramaStorageAdapter) 强力拦截孤儿二阶资产并阻断 t2i 退化。"""

    def test_persist_stage6_intercepts_t2_t2i_degradation(self, db_session):
        from sqlalchemy import text
        from app.schemas.script_graph_state import (
            EpisodeResourceManifest,
            IndustrialDramaMasterState,
        )
        from app.workflows.adapters.drama_storage_adapter import persist_stage6

        db = db_session
        drama_id = 909

        # 初始化 Drama 与 Episode
        db.execute(text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (909, '防退化测试剧', 'draft', '', '')"))
        db.execute(text("INSERT INTO episodes (id, drama_id, episode_number, title, created_at, updated_at) VALUES (9091, 909, 1, '第1集', '', '')"))
        db.commit()

        # 模拟包含错误申明为 t2i 的二阶资产
        manifest = EpisodeResourceManifest(
            episode_num=1,
            characters=[
                {
                    "char_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "character_name": "沈炼",
                    "role": "protagonist",
                    "stage_name": "锦衣卫常规巡查形态",
                    "visual_prompt": "神色冷峻，双目如鹰",
                }
            ],
            environments=[
                {
                    "scene_id": "ENV_STATION_Z01_WIDE",
                    "scene_name": "雪夜古驿站",
                    "time_lighting": "深夜",
                    "visual_prompt": "破落驿站大堂全景",
                }
            ],
            props=[
                {
                    "prop_id": "PROP_SWORD_S0_STATIC",
                    "prop_name": "绣春刀",
                    "visual_prompt": "明代制式绣春刀",
                }
            ],
            audio=[],
            newly_generated_assets=[
                {
                    "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "name": "沈炼基准立绘",
                    "category": "character",
                    "type": "image",
                    "is_benchmark": 1,
                    "generation_mode": "t2i",
                },
                # 错误案例 1：二阶阶段立绘被误标为 t2i 且无 parent
                {
                    "asset_id": "CHAR_SHENLIAN_T2_BASE_PORTRAIT",
                    "name": "沈炼换装立绘",
                    "category": "character",
                    "type": "image",
                    "is_benchmark": 1,
                    "generation_mode": "t2i",
                    "parent_asset_key": None,
                },
                # 错误案例 2：二阶做旧场景被误标为 t2i 且无 parent
                {
                    "asset_id": "ENV_XUEYEGUYIZHAN_Z02_WIDE",
                    "name": "雪夜古驿站战损全景",
                    "category": "environment",
                    "type": "image",
                    "is_benchmark": 1,
                    "generation_mode": "t2i",
                    "parent_asset_key": None,
                },
                # 错误案例 3：二阶战损道具被误标为 t2i 且无 parent
                {
                    "asset_id": "PROP_XIUCHUNDAO_S2_STATIC",
                    "name": "绣春刀断刃",
                    "category": "prop",
                    "type": "image",
                    "is_benchmark": 1,
                    "generation_mode": "t2i",
                    "parent_asset_key": None,
                },
            ],
        )

        state = IndustrialDramaMasterState(
            drama_id=drama_id,
            current_visual_episode=1,
            episode_manifests={1: manifest},
        )

        persist_stage6(db, drama_id=drama_id, state=state, episode_num=1)

        # 检查 assets 表持久化结果
        asset_map = {
            row["asset_key"]: row
            for row in db.execute(text("SELECT * FROM assets WHERE drama_id = 909")).mappings().all()
        }

        # 验证 1: 一阶基准依然正确为 t2i / parent=None / is_benchmark=1
        t1_char = asset_map["CHAR_SHENLIAN_T1_BASE_PORTRAIT"]
        assert t1_char["generation_mode"] == "t2i"
        assert t1_char["parent_asset_id"] is None
        assert t1_char["is_benchmark"] == 1

        # 验证 2: 二阶角色换装肖像被纠偏为 i2i，自动挂载父资产为同角色 T1，is_benchmark 为 0
        t2_char = asset_map["CHAR_SHENLIAN_T2_BASE_PORTRAIT"]
        assert t2_char["generation_mode"] == "i2i"
        assert t2_char["parent_asset_id"] == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
        assert t2_char["is_benchmark"] == 0
        assert t2_char["denoise_strength"] == 0.35

        # 验证 3: 二阶场景被纠偏为 i2i，自动挂载 Z01 基准
        z2_env = asset_map["ENV_XUEYEGUYIZHAN_Z02_WIDE"]
        assert z2_env["generation_mode"] == "i2i"
        assert z2_env["parent_asset_id"] == "ENV_XUEYEGUYIZHAN_Z01_WIDE"
        assert z2_env["is_benchmark"] == 0
        assert z2_env["denoise_strength"] == 0.45

        # 验证 4: 二阶战损道具被纠偏为 i2i，自动挂载 S0 基准
        s2_prop = asset_map["PROP_XIUCHUNDAO_S2_STATIC"]
        assert s2_prop["generation_mode"] == "i2i"
        assert s2_prop["parent_asset_id"] == "PROP_XIUCHUNDAO_S0_STATIC"
        assert s2_prop["is_benchmark"] == 0
        assert s2_prop["denoise_strength"] == 0.45

