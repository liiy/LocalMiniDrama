"""单元测试：验证 Script-to-Visual Bridge 契约提取与算力流幂等指纹 (Task Fingerprint)。"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.schema import ensure_schema
from app.services.script_to_visual_bridge import ScriptToVisualBridge, VisualStoryboardItem


def test_task_fingerprint_idempotency():
    """测试不同参数与相同参数下的 SHA256 幂等指纹计算。"""
    fp1 = ScriptToVisualBridge.compute_task_fingerprint(
        drama_id=1, episode_num=10, storyboard_num=1, prompt="顾沉舟冷酷特写", aspect_ratio="9:16", version_cursor=1
    )
    fp2 = ScriptToVisualBridge.compute_task_fingerprint(
        drama_id=1, episode_num=10, storyboard_num=1, prompt="顾沉舟冷酷特写", aspect_ratio="9:16", version_cursor=1
    )
    # 相同参数指纹完全一致
    assert fp1 == fp2
    assert len(fp1) == 64

    # 提示词修改或版本游标变更后，指纹变更触发重跑
    fp3 = ScriptToVisualBridge.compute_task_fingerprint(
        drama_id=1, episode_num=10, storyboard_num=1, prompt="顾沉舟冷酷特写（眼神带杀气）", aspect_ratio="9:16", version_cursor=1
    )
    assert fp1 != fp3

    fp4 = ScriptToVisualBridge.compute_task_fingerprint(
        drama_id=1, episode_num=10, storyboard_num=1, prompt="顾沉舟冷酷特写", aspect_ratio="9:16", version_cursor=2
    )
    assert fp1 != fp4


def test_bridge_contract_extraction_and_sync():
    """测试从已定稿短剧提取 Bridge 契约并同步写入视听工坊表。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        ensure_schema(conn)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # 初始化定稿剧本数据
    db.execute(text("INSERT INTO dramas (id, title, lock_status, version_cursor) VALUES (10, '天王战神', 1, 1)"))
    db.execute(text("INSERT INTO episodes (id, drama_id, episode_number, title, script_content) VALUES (101, 10, 1, '第1集：出狱', '正文视听动作与对白')"))
    db.execute(text("INSERT INTO characters (id, drama_id, name, role) VALUES (1, 10, '顾沉舟', '主角')"))
    db.commit()

    # 1. 提取契约
    contract = ScriptToVisualBridge.extract_contract_from_script(db, drama_id=10, episode_num=1)
    assert contract.drama_id == 10
    assert contract.episode_num == 1
    assert len(contract.storyboards) == 4
    assert len(contract.characters) == 1
    assert contract.storyboards[0].task_fingerprint != ""

    # 2. 同步写入视听工坊
    res = ScriptToVisualBridge.sync_contract_to_visual_studio(db, contract)
    db.commit()

    assert res["status"] == "bridged_to_visual_studio"
    assert res["synced_storyboards"] == 4

    # 验证 storyboards 表落库记录
    sbs = db.execute(text("SELECT id, storyboard_number, task_fingerprint, status FROM storyboards WHERE episode_id = 101 ORDER BY storyboard_number ASC")).fetchall()
    assert len(sbs) == 4
    assert sbs[0][1] == 1
    assert sbs[0][3] == "pending"
    assert sbs[0][2] == contract.storyboards[0].task_fingerprint
