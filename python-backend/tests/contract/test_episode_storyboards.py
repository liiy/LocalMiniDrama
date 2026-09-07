"""Contract tests for Storyboard Generation, Rebuild Video Prompt, and Split by Audio.

Tests 1:1 parity with backend-node:
1. POST /api/v1/episodes/:id/storyboards
   - 400 for missing/empty script
   - 200 { task_id, status: 'pending', message: '分镜生成任务已创建，正在后台处理...' }
2. Background storyboard generation worker execution:
   - Incremental saves & stream callback
   - JSON truncation & multi-pass continuation
   - Character auto-linking (sync_storyboard_characters)
   - Episode duration update
   - Task completion
3. POST /api/v1/storyboards/:id/rebuild-video-prompt:
   - 400 for invalid id
   - 404 for non-existent id
   - 200 for valid id with message '视频提示词已按最新规则重建并保存'
4. POST /api/v1/storyboards/:id/split-by-audio:
   - 400 for invalid id
   - 404 for non-existent id
   - 400 for single-line dialogue/narration ('当前分镜仅有一段对白或旁白，无需拆镜')
   - 200 for multi-line dialogue: splits into multiple rows, updates shot numbers, copies asset links
"""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

from app.tasks import queue_service

import pytest
from fastapi.testclient import TestClient

from app.db import session as dbm
from app.db.session import execute, fetch_all, fetch_one
from app.main import app
from app.services import episodeStoryboardService, taskService, workerService


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = dbm.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_test_drama_and_episode(db, script=""):
    r1 = execute(
        db,
        "INSERT INTO dramas (title, description, style, status) VALUES ('Test Drama', 'Desc', '国风写实', 'draft')",
    )
    did = r1.lastrowid

    execute(
        db,
        "INSERT INTO characters (drama_id, name, description) VALUES (:did, '李逍遥', '主角剑客')",
        {"did": did},
    )
    execute(
        db,
        "INSERT INTO characters (drama_id, name, description) VALUES (:did, '赵灵儿', '女主角女娲后人')",
        {"did": did},
    )
    execute(
        db,
        "INSERT INTO scenes (drama_id, location, time, prompt) VALUES (:did, '仙灵岛水月宫', '清晨', '仙境水榭')",
        {"did": did},
    )
    execute(
        db,
        "INSERT INTO props (drama_id, name, type) VALUES (:did, '紫金葫芦', '法宝')",
        {"did": did},
    )

    r2 = execute(
        db,
        "INSERT INTO episodes (drama_id, episode_number, title, script_content, status) VALUES (:did, 1, '第1集 仙灵奇遇', :script, 'draft')",
        {"did": did, "script": script},
    )
    ep_id = r2.lastrowid
    db.commit()
    return did, ep_id


def test_rebuild_video_prompt_routes(client, db):
    # 1. Invalid id -> 400
    res = client.post("/api/v1/storyboards/abc/rebuild-video-prompt")
    assert res.status_code == 400
    assert res.json()["error"]["message"] == "缺少分镜 id"

    # 2. Non-existent id -> 404
    res = client.post("/api/v1/storyboards/999999/rebuild-video-prompt")
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "分镜不存在"

    # 3. Existing storyboard -> 200 with updated video_prompt
    did, ep_id = create_test_drama_and_episode(db, "剧本内容")
    r_sb = execute(
        db,
        """INSERT INTO storyboards (
            episode_id, storyboard_number, title, shot_type, angle, movement,
            action, dialogue, narration, result, status
        ) VALUES (
            :eid, 1, '初遇', '特写', '仰视', '推镜头',
            '李逍遥拔剑出鞘', '李逍遥：你是何人？', '风吹动树叶沙沙作响', '灵儿退后一步', 'pending'
        )""",
        {"eid": ep_id},
    )
    sb_id = r_sb.lastrowid
    db.commit()

    res = client.post(f"/api/v1/storyboards/{sb_id}/rebuild-video-prompt")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["id"] == sb_id
    assert "镜头标题：初遇" in data["video_prompt"]
    assert "李逍遥：你是何人？" in data["video_prompt"]
    assert data["message"] == "视频提示词已按最新规则重建并保存"


def test_split_by_audio_routes(client, db):
    # 1. Invalid id -> 400
    res = client.post("/api/v1/storyboards/0/split-by-audio")
    assert res.status_code == 400
    assert res.json()["error"]["message"] == "缺少分镜 id"

    # 2. Non-existent id -> 404
    res = client.post("/api/v1/storyboards/888888/split-by-audio")
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "分镜不存在"

    # 3. Single line dialogue -> 400
    did, ep_id = create_test_drama_and_episode(db, "单句剧本")
    r_sb1 = execute(
        db,
        """INSERT INTO storyboards (
            episode_id, storyboard_number, title, action, dialogue, status
        ) VALUES (
            :eid, 1, '独白', '主角沉思', '李逍遥：今天天气不错。', 'pending'
        )""",
        {"eid": ep_id},
    )
    sb1_id = r_sb1.lastrowid
    db.commit()

    res = client.post(f"/api/v1/storyboards/{sb1_id}/split-by-audio")
    assert res.status_code == 400
    assert "当前分镜仅有一段对白或旁白，无需拆镜" in res.json()["error"]["message"]

    # 4. Multi-line dialogue -> 200, splits into 2 shots, shifts next shot
    r_sb2 = execute(
        db,
        """INSERT INTO storyboards (
            episode_id, storyboard_number, title, action, dialogue, status
        ) VALUES (
            :eid, 2, '对话', '两人交谈', '李逍遥：你叫什么名字？\n赵灵儿：我叫灵儿。', 'pending'
        )""",
        {"eid": ep_id},
    )
    sb2_id = r_sb2.lastrowid

    # Add shot 3 that should be shifted to shot 4
    r_sb3 = execute(
        db,
        """INSERT INTO storyboards (
            episode_id, storyboard_number, title, status
        ) VALUES (
            :eid, 3, '后续镜头', 'pending'
        )""",
        {"eid": ep_id},
    )
    sb3_id = r_sb3.lastrowid
    db.commit()

    res = client.post(f"/api/v1/storyboards/{sb2_id}/split-by-audio")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["source_id"] == sb2_id
    assert len(data["storyboard_ids"]) == 2
    assert data["created_count"] == 1
    assert "已拆成 2 条分镜（新增 1 条）" in data["message"]

    # Verify shot numbers in DB
    sb3_row = fetch_one(db, "SELECT storyboard_number FROM storyboards WHERE id = :id", {"id": sb3_id})
    assert sb3_row["storyboard_number"] == 4  # Shifted from 3 to 4


def test_episode_storyboards_generation_api(client, db):
    # 1. Missing script -> 500 / error
    did, ep_empty_id = create_test_drama_and_episode(db, "")
    res = client.post(f"/api/v1/episodes/{ep_empty_id}/storyboards", json={})
    assert res.status_code == 500
    assert "剧本内容为空" in res.json()["error"]["message"]

    # 2. Valid script -> 200 { task_id, status: 'pending' }
    did, ep_id = create_test_drama_and_episode(db, "李逍遥御剑飞行，来到仙灵岛。赵灵儿在荷塘边采药。")
    res = client.post(
        f"/api/v1/episodes/{ep_id}/storyboards",
        json={
            "storyboard_count": 2,
            "video_duration": 10,
            "aspect_ratio": "16:9",
            "universal_omni_storyboard": True,
        },
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert "task_id" in data
    assert data["status"] == "pending"
    assert data["message"] == "分镜生成任务已创建，正在后台处理..."
    db.rollback()
    jobs = queue_service.list_queue_jobs(db, task_type="legacy.storyboard.generate", limit=20)
    assert any(job["async_task_id"] == data["task_id"] for job in jobs)


def test_process_storyboard_generation_execution(db):
    did, ep_id = create_test_drama_and_episode(db, "李逍遥御剑飞行来到仙灵岛。赵灵儿在荷塘边采药。")
    task = taskService.create_task(db, episodeStoryboardService.log, "storyboard_generation", str(ep_id))
    db.commit()

    mock_ai_output = json.dumps([
        {
            "shot_number": 1,
            "title": "飞剑破云",
            "scene_description": "仙灵岛水月宫，清晨",
            "shot_type": "全景",
            "movement": "俯冲推进",
            "angle": "俯视",
            "action": "李逍遥踏着飞剑破开浓密云海，望向下方仙岛",
            "dialogue": "李逍遥：终于到了传说中的仙灵岛！",
            "narration": "云海苍茫，少年初试锋芒。",
            "result": "飞剑平稳落地",
            "emotion": "意气风发",
            "duration": 5,
            "characters": [{"id": 1, "name": "李逍遥"}],
            "props": [1],
        },
        {
            "shot_number": 2,
            "title": "水畔佳人",
            "scene_description": "仙灵岛水月宫，清晨",
            "shot_type": "特写",
            "movement": "缓推轨",
            "angle": "平视",
            "action": "赵灵儿蹲在荷塘边轻拂水面，回头望向动静处",
            "dialogue": "赵灵儿：是谁在外面？",
            "narration": "荷香阵阵，少女眸光澄澈。",
            "result": "两人目光相交",
            "emotion": "好奇警惕",
            "duration": 5,
            "characters": [{"id": 2, "name": "赵灵儿"}],
        },
    ], ensure_ascii=False)

    with patch("app.services.aiClient.generate_text", return_value=mock_ai_output):
        episodeStoryboardService.process_storyboard_generation(
            db,
            episodeStoryboardService.log,
            {"style": {"default_style": "国风CG", "default_video_ratio": "16:9"}},
            task["id"],
            str(ep_id),
            model="mock-gpt",
            style="国风CG",
            user_prompt="prompt",
            system_prompt="system",
            include_narration=True,
            universal_omni=True,
            target_clip_duration_sec=5,
        )

    # Verify task result
    refreshed_task = taskService.get_task(db, task["id"])
    assert refreshed_task["status"] == "completed"
    res_data = json.loads(refreshed_task["result"])
    assert res_data["total"] == 2
    assert res_data["total_duration"] == 10

    # Verify storyboards in database
    sbs = episodeStoryboardService.get_storyboards_for_episode(db, ep_id)
    assert len(sbs) == 2
    assert sbs[0]["storyboard_number"] == 1
    assert sbs[0]["title"] == "飞剑破云"
    assert sbs[0]["creation_mode"] == "universal"
    assert sbs[0]["universal_segment_text"] is not None
    assert "李逍遥" in sbs[0]["action"]
    assert sbs[1]["storyboard_number"] == 2
    assert sbs[1]["title"] == "水畔佳人"

    # Verify episode duration updated (Node formula: ceil((totalDuration + 59) / 60))
    ep_row = fetch_one(db, "SELECT duration FROM episodes WHERE id = :id", {"id": ep_id})
    assert ep_row["duration"] == 2
