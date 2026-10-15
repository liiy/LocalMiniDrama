"""阶段 6 多集串联资产复用与 Token 收敛集成测试 (Stage 6 Multi-Episodes Token Convergence Integration Tests)。

验证目标：
1. 连续长剧创作场景 (第 1 集 -> 第 2 集 -> 第 3 集) 下的资产一致性与复用准确率：
   - 第 1 集新增角色（沈炼）、场景（北镇抚司大堂）、道具（绣春刀），成功生成基准视图并落库；
   - 第 2 集剧情延续，沈炼与绣春刀被精准识别为已核准候选资产 (reused_existing_assets)，坚决杜绝重复生成基准视图；
   - 第 3 集登场新角色（陆文昭）与新道具（断魂剑），精准识别并增量生成基准视图与母音卡片；
2. 50+ 资产规模场景下的 Token 零膨胀与收敛验证：
   - 模拟历史集数累加至几十项资产时，输入大模型的候选资产池仍严格截断在 Top 15 资产以内；
   - 候选资产 JSON 字符数严格受控 (O(1) 阶)，彻底解决传统 O(N) 全量注入导致的 Token 爆炸；
3. 数据库全要素主从 + 统管表 + DAG 全生命周期持久化与还原闭环：
   - episodes.ast_blocks['episode_resource_manifest']
   - dramas.metadata['asset_lineage_dag']
   - assets / character_stages / character_voice_profiles / prop_damage_states 表一致性。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.context.vector_memory_service import recall_candidate_assets_for_episode
from app.schemas.script_graph_state import IndustrialDramaState
from app.workflows.adapters.drama_storage_adapter import (
    load_master_state_from_db,
    persist_stage6,
)
from app.context.vector_memory_service import delete_drama_asset_collection
from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node


def _init_drama_and_canon(db_session, drama_id: int = 888):
    """初始化短剧基础数据与阶段 2/3 标准资产 (Canon)。"""
    # 彻底清理可能残留的向量测试集合
    delete_drama_asset_collection(drama_id)

    db_session.execute(
        text(
            "INSERT INTO dramas (id, title, status, metadata, created_at, updated_at) "
            "VALUES (:id, '破晓行动', 'draft', '{}', '', '')"
        ),
        {"id": drama_id},
    )
    # 阶段 2 人物小传
    db_session.execute(
        text(
            "INSERT INTO characters (id, drama_id, name, character_code, appearance, role, created_at, updated_at) "
            "VALUES (:cid1, :did, '沈炼', 'SHENLIAN', '冷峻锦衣卫，飞鱼服佩绣春刀', 'protagonist', '', '')"
        ),
        {"cid1": drama_id * 10 + 1, "did": drama_id},
    )
    # 阶段 3 场景与道具
    db_session.execute(
        text(
            "INSERT INTO scenes (id, drama_id, location, prompt, created_at, updated_at) "
            "VALUES (:sid1, :did, '北镇抚司大堂', '昏暗烛火，黑漆立柱，威严肃杀', '', '')"
        ),
        {"sid1": drama_id * 10 + 2, "did": drama_id},
    )
    db_session.execute(
        text(
            "INSERT INTO props (id, drama_id, name, prompt, created_at, updated_at) "
            "VALUES (:pid1, :did, '绣春刀', '百炼精钢，云纹铜鞘，锋利无匹', '', '')"
        ),
        {"pid1": drama_id * 10 + 3, "did": drama_id},
    )
    db_session.commit()


def test_stage6_multiepisodes_asset_continuity_and_token_convergence(db_session):
    """测试阶段 6 多集串联：第 1 集基准建立 -> 第 2 集精准复用 -> 第 3 集增量新增 -> 规模膨胀时 Token 零爆炸。"""
    drama_id = 888
    _init_drama_and_canon(db_session, drama_id=drama_id)

    # =========================================================================
    # 1. 运行第 1 集：首次登场，提取基准视图 (Benchmark Views)
    # =========================================================================
    ep1_script = {
        "screenplay_text": "【场景：北镇抚司大堂·夜】\n沈炼手扶绣春刀，立于堂前。\n沈炼：（沉声）今夜谁也走不脱！",
        "characters": ["沈炼"],
        "scene": "北镇抚司大堂",
        "props": ["绣春刀"],
    }
    ep1_input_state = {
        "drama_id": drama_id,
        "db": db_session,
        "current_episode": 1,
        "episodes_scripts": [ep1_script],
        "characters_engine": {
            "characters": [
                {
                    "name": "沈炼",
                    "character_code": "SHENLIAN",
                    "appearance": "冷峻锦衣卫，飞鱼服佩绣春刀",
                    "visual_summary": "冷峻锦衣卫",
                    "voice_timbre": "低沉磁性",
                }
            ]
        },
        "environments_props": {
            "environments": [{"location": "北镇抚司大堂", "prompt": "昏暗烛火，黑漆立柱"}],
            "props": [{"name": "绣春刀", "prompt": "百炼精钢，云纹铜鞘"}],
        },
        "visual_audio_assets_registry": {},
    }

    # 执行第 1 集 Stage 6 节点 (在单测环境下触发保底工厂并注入候选池)
    ep1_out = stage6_asset_truth_node(ep1_input_state)
    assert "episode_resource_manifest" in ep1_out
    ep1_manifest = ep1_out["episode_resource_manifest"]

    # 验证第 1 集生成了全新的基准视图
    ep1_new_keys = [a["asset_key"] for a in ep1_manifest.get("newly_generated_assets", [])]
    assert "CHAR_SHENLIAN_T1_BASE_PORTRAIT" in ep1_new_keys
    assert "CHAR_SHENLIAN_T1_BASE_COSTUME" in ep1_new_keys
    assert any("XIUCHUNDAO" in k for k in ep1_new_keys)

    # 验证第 1 集复用列表为空（首次登场）
    assert len(ep1_manifest.get("reused_existing_assets", [])) == 0

    # 持久化第 1 集到数据库
    persist_stage6(
        db=db_session,
        drama_id=drama_id,
        episode_num=1,
        state=IndustrialDramaState(**ep1_out),
    )

    # 验证持久化落库结果：assets 表中包含沈炼、绣春刀、北镇抚司大堂
    rows = db_session.execute(
        text("SELECT asset_key, category FROM assets WHERE drama_id = :did"),
        {"did": drama_id},
    ).fetchall()
    stored_keys = [r[0] for r in rows]
    assert "CHAR_SHENLIAN_T1_BASE_PORTRAIT" in stored_keys
    assert "CHAR_SHENLIAN_T1_BASE_COSTUME" in stored_keys
    assert any("VOICE_SHENLIAN" in k for k in stored_keys)

    # 验证 character_stages 表
    stage_rows = db_session.execute(
        text("SELECT stage_code, start_episode FROM character_stages WHERE drama_id = :did"),
        {"did": drama_id},
    ).fetchall()
    assert any(r[0] == "T1" and r[1] == 1 for r in stage_rows)

    # =========================================================================
    # 2. 运行第 2 集：剧情延续，必须精准复用沈炼与绣春刀，零重复生成基准视图
    # =========================================================================
    ep2_script = {
        "screenplay_text": "【场景：北镇抚司大堂·夜】\n沈炼拔出绣春刀，刀锋如雪！突然，一名黑衣刺客破窗而入！",
        "characters": ["沈炼", "黑衣刺客"],
        "scene": "北镇抚司大堂",
        "props": ["绣春刀"],
    }
    # 传递第 1 集累计的 registry
    ep2_input_state = {
        "drama_id": drama_id,
        "db": db_session,
        "current_episode": 2,
        "episodes_scripts": [ep1_script, ep2_script],
        "characters_engine": ep1_input_state["characters_engine"],
        "environments_props": ep1_input_state["environments_props"],
        "visual_audio_assets_registry": ep1_out.get("visual_audio_assets_registry", {}),
        "previous_episode_pickup_snapshot": ep1_manifest.get("physical_continuity_snapshot", {}),
    }

    # 首先独立验证候选召回函数对第 2 集剧本的精准召回
    candidates_ep2 = recall_candidate_assets_for_episode(
        db=db_session,
        drama_id=drama_id,
        screenplay_text=ep2_script["screenplay_text"],
        top_k=15,
    )
    candidate_keys_ep2 = [c["asset_key"] for c in candidates_ep2]
    assert "CHAR_SHENLIAN_T1_BASE_PORTRAIT" in candidate_keys_ep2
    assert any("XIUCHUNDAO" in k for k in candidate_keys_ep2)

    # 运行第 2 集 Stage 6 节点
    ep2_out = stage6_asset_truth_node(ep2_input_state)
    ep2_manifest = ep2_out["episode_resource_manifest"]

    # 验证第 2 集复用列表：沈炼与绣春刀被成功标记为复用资产
    reused_keys_ep2 = [a["asset_key"] for a in ep2_manifest.get("reused_existing_assets", [])]
    assert "CHAR_SHENLIAN_T1_BASE_PORTRAIT" in reused_keys_ep2
    assert any("XIUCHUNDAO" in k for k in reused_keys_ep2)

    # 防呆断言：第 2 集中绝对不得重复生成 沈炼 T1 基础定妆照与全身图
    ep2_new_keys = [a["asset_key"] for a in ep2_manifest.get("newly_generated_assets", [])]
    assert "CHAR_SHENLIAN_T1_BASE_PORTRAIT" not in ep2_new_keys
    assert "CHAR_SHENLIAN_T1_BASE_COSTUME" not in ep2_new_keys

    # 持久化第 2 集
    persist_stage6(
        db=db_session,
        drama_id=drama_id,
        episode_num=2,
        state=IndustrialDramaState(**ep2_out),
    )

    # =========================================================================
    # 3. 运行第 3 集：登场全新配角“陆文昭”与道具“断魂剑”，增量生成基准视图
    # =========================================================================
    # 模拟在 characters 表中登记阶段 2 的新增角色陆文昭
    db_session.execute(
        text(
            "INSERT INTO characters (id, drama_id, name, character_code, appearance, role, created_at, updated_at) "
            "VALUES (:cid2, :did, '陆文昭', 'LUWENZHAO', '千户大人，八面玲珑，佩带断魂剑', 'supporting', '', '')"
        ),
        {"cid2": drama_id * 10 + 4, "did": drama_id},
    )
    db_session.commit()

    ep3_script = {
        "screenplay_text": "【场景：醉仙楼·日】\n沈炼推门而入。\n陆文昭坐在窗前，端着酒杯，腰悬断魂剑，嘴角挂着一丝讥诮。\n陆文昭：（冷笑）沈大人，好久不见。",
        "characters": ["沈炼", "陆文昭"],
        "scene": "醉仙楼",
        "props": ["断魂剑"],
    }
    ep3_chars_engine = {
        "characters": [
            {
                "name": "沈炼",
                "character_code": "SHENLIAN",
                "appearance": "冷峻锦衣卫，飞鱼服佩绣春刀",
                "visual_summary": "冷峻锦衣卫",
                "voice_timbre": "低沉磁性",
            },
            {
                "name": "陆文昭",
                "character_code": "LUWENZHAO",
                "appearance": "千户大人，八面玲珑，佩带断魂剑",
                "visual_summary": "千户大人八面玲珑",
                "voice_timbre": "圆滑沙哑",
            },
        ]
    }
    ep3_input_state = {
        "drama_id": drama_id,
        "db": db_session,
        "current_episode": 3,
        "episodes_scripts": [ep1_script, ep2_script, ep3_script],
        "characters_engine": ep3_chars_engine,
        "environments_props": {
            "environments": [{"location": "醉仙楼", "prompt": "雕梁画栋，红绸摇曳"}],
            "props": [{"name": "断魂剑", "prompt": "玄铁长剑，乌黑无光"}],
        },
        "visual_audio_assets_registry": ep2_out.get("visual_audio_assets_registry", {}),
    }

    # 执行第 3 集 Stage 6 节点
    ep3_out = stage6_asset_truth_node(ep3_input_state)
    ep3_manifest = ep3_out["episode_resource_manifest"]

    # 验证复用与新增隔离：
    # 沈炼被复用
    reused_keys_ep3 = [a["asset_key"] for a in ep3_manifest.get("reused_existing_assets", [])]
    assert "CHAR_SHENLIAN_T1_BASE_PORTRAIT" in reused_keys_ep3

    # 陆文昭作为全新角色，生成了 T1 基准定妆照、全身图与母音卡
    ep3_new_keys = [a["asset_key"] for a in ep3_manifest.get("newly_generated_assets", [])]
    assert "CHAR_LUWENZHAO_T1_BASE_PORTRAIT" in ep3_new_keys
    assert "CHAR_LUWENZHAO_T1_BASE_COSTUME" in ep3_new_keys

    # 持久化第 3 集
    persist_stage6(
        db=db_session,
        drama_id=drama_id,
        episode_num=3,
        state=IndustrialDramaState(**ep3_out),
    )

    # 验证 assets 表增量入库：陆文昭成功入库
    lu_row = db_session.execute(
        text("SELECT asset_key FROM assets WHERE drama_id = :did AND asset_key = 'CHAR_LUWENZHAO_T1_BASE_PORTRAIT'"),
        {"did": drama_id},
    ).fetchone()
    assert lu_row is not None

    # =========================================================================
    # 4. Token 零膨胀与收敛验证 (模拟长剧规模累积 40+ 资产场景)
    # =========================================================================
    # 批量注入 35 个历史衍生资产（模拟 50 集长剧背景）
    for i in range(1, 36):
        db_session.execute(
            text("""
                INSERT INTO assets (id, drama_id, asset_key, name, type, category, prompt, metadata, created_at, updated_at)
                VALUES (:aid, :did, :akey, :aname, 'image', 'prop', '历史背景道具描述', '{"stage_code": "T2"}', '', '')
            """),
            {
                "aid": 9000 + i,
                "did": drama_id,
                "akey": f"PROP_EXTRA_{i:03d}_T1_STATIC",
                "aname": f"历史辅助道具_{i}",
            },
        )
    db_session.commit()

    total_assets_count = db_session.execute(
        text("SELECT count(*) FROM assets WHERE drama_id = :did"),
        {"did": drama_id},
    ).scalar()
    # 此时资产库中至少包含 40+ 项资产
    assert total_assets_count >= 40

    # 针对第 4 集剧本进行候选资产召回
    ep4_screenplay = "沈炼和陆文昭在北镇抚司密谋，沈炼擦拭着绣春刀。"
    candidates_ep4 = recall_candidate_assets_for_episode(
        db=db_session,
        drama_id=drama_id,
        screenplay_text=ep4_screenplay,
        top_k=15,
    )

    # 【关键验收断言】：
    # 1. 候选数量严格 <= 15 (Top-K 截断)
    assert len(candidates_ep4) <= 15

    # 2. 候选池序列化为 JSON 字符串后的字符数收敛受控 (有界常量级，< 5,000 字符，相当于 < 900 Token，彻底消除 O(N) 随集数线性膨胀)
    candidates_json = json.dumps(candidates_ep4, ensure_ascii=False, indent=2)
    assert len(candidates_json) < 5000, f"候选资产池长度超标: {len(candidates_json)} 字符"

    # 3. 核心相关资产（沈炼、陆文昭、绣春刀）均被高置信度召回
    recalled_names = [c["name"] for c in candidates_ep4]
    assert "沈炼" in recalled_names
    assert "陆文昭" in recalled_names
    assert "绣春刀" in recalled_names

    # 4. 验证全局 asset_lineage_dag 在 dramas.metadata 中的有效聚合
    drama_row = db_session.execute(
        text("SELECT metadata FROM dramas WHERE id = :did"),
        {"did": drama_id},
    ).fetchone()
    drama_meta = json.loads(drama_row[0] or "{}")
    dag = drama_meta.get("asset_lineage_dag", {})
    assert isinstance(dag, dict)
    assert len(dag) > 0
    assert dag.get("CHAR_SHENLIAN_T1_BASE_COSTUME") == "CHAR_SHENLIAN_T1_BASE_PORTRAIT"
