"""契约与功能测试：AI 后台异步生成任务（角色生成、剧本扩展、场景背景提取、锚点提炼）。"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import session_scope
from app.services import (
    backgroundExtractionService,
    characterGenerationService,
    generationService,
    taskService,
)
from app.tasks import queue_service, worker_runner


def _wait_for_task(task_id: str, timeout: float = 8.0) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        with session_scope() as db:
            t = taskService.get_task(db, task_id)
            if t and t.get("status") in ("completed", "failed"):
                return t
        time.sleep(0.1)
    raise TimeoutError(f"Task {task_id} timed out")


def _create_drama(client: TestClient) -> dict:
    r = client.post("/api/v1/dramas", json={"title": "仙剑奇侠传", "drama_style": "仙侠古风"})
    assert r.status_code == 201
    return r.json()["data"]


def _create_episode(client: TestClient, drama_id: int) -> dict:
    r = client.put(
        f"/api/v1/dramas/{drama_id}/episodes",
        json={"episodes": [{"episode_number": 1, "title": "初入江湖", "script_content": "李逍遥在客栈醒来，准备前往仙灵岛求药。"}]},
    )
    assert r.status_code == 200
    r_drama = client.get(f"/api/v1/dramas/{drama_id}")
    assert r_drama.status_code == 200
    return r_drama.json()["data"]["episodes"][0]


def test_character_generation_flow(client: TestClient):
    d = _create_drama(client)
    e = _create_episode(client, d["id"])

    mock_chars = [
        {
            "name": "李逍遥",
            "role": "主角",
            "description": "天资聪颖的少年侠客",
            "personality": "爽朗豁达",
            "appearance": "长发束冠，身穿青白布衫，腰挎长剑",
            "voice_style": "阳光清亮",
        }
    ]

    def fake_generate_text(db, log, service_type, user_prompt, system_prompt, options=None):
        if "锚点" in user_prompt or "identity" in user_prompt.lower():
            return '{"face": "俊朗少年", "clothing": "青白布衫", "features": "腰挎长剑"}'
        if "四视图" in user_prompt or "four view" in user_prompt.lower():
            return "A dashing young swordsman in traditional Chinese garments"
        return json.dumps(mock_chars, ensure_ascii=False)

    # 1. 路由触发角色生成，异步后台执行
    with patch("app.services.aiClient.generate_text", side_effect=fake_generate_text):
        r = client.post("/api/v1/generation/characters", json={"drama_id": d["id"], "episode_id": e["id"]})
        assert r.status_code == 200
        task_id = r.json()["data"]["task_id"]
        assert task_id

        t = _wait_for_task(task_id)

    # 验证任务完成
    assert t["status"] == "completed"
    assert t["progress"] == 100
    res = t["result"]
    if isinstance(res, str):
        res = json.loads(res)
    assert res["count"] == 1
    assert res["characters"][0]["name"] == "李逍遥"

    with session_scope() as db:
        # 验证数据库中持久化了角色并绑定到剧集
        row = db.execute(
            text("SELECT * FROM characters WHERE drama_id = :did AND name = '李逍遥' AND deleted_at IS NULL"),
            {"did": d["id"]},
        ).mappings().first()
        assert row is not None
        assert row["role"] == "主角"

        # 验证绑定关系
        link = db.execute(
            text("SELECT * FROM episode_characters WHERE episode_id = :eid AND character_id = :cid"),
            {"eid": e["id"], "cid": row["id"]},
        ).first()
        assert link is not None


def test_character_extract_anchors_flow(client: TestClient):
    d = _create_drama(client)

    # 2.1 缺少外貌时报错 400
    client.put(
        f"/api/v1/dramas/{d['id']}/characters",
        json={"characters": [{"name": "路人甲", "appearance": ""}]},
    )
    c_no_app = client.get(f"/api/v1/dramas/{d['id']}/characters").json()["data"][0]
    r_err = client.post(f"/api/v1/characters/{c_no_app['id']}/extract-anchors")
    assert r_err.status_code == 400
    assert "外貌" in r_err.json()["error"]["message"]

    # 2.2 不存在的角色返回 404
    r_404 = client.post("/api/v1/characters/999999/extract-anchors")
    assert r_404.status_code == 404

    # 2.3 正常提炼流程
    client.put(
        f"/api/v1/dramas/{d['id']}/characters",
        json={"characters": [{"name": "赵灵儿", "appearance": "白衣水月，发系红丝带，清纯出尘"}]},
    )
    chars = client.get(f"/api/v1/dramas/{d['id']}/characters").json()["data"]
    char = next(c for c in chars if c["name"] == "赵灵儿")

    fake_anchors = {"face": "瓜子脸，清纯秀丽", "clothing": "白色苗服绣花长裙", "features": "发系红色发带"}

    with patch("app.services.aiClient.generate_text", return_value=json.dumps(fake_anchors, ensure_ascii=False)):
        r_ok = client.post(f"/api/v1/characters/{char['id']}/extract-anchors")
        assert r_ok.status_code == 200
        assert "锚点提炼已启动" in r_ok.json()["data"]["message"]
        queue_job_id = r_ok.json()["data"]["queue_job_id"]

        # 契约测试显式驱动独立 Worker，验证请求进程退出后仍可恢复执行。
        with session_scope() as db:
            claimed = queue_service.claim_next_job(
                db,
                worker_id="contract-character-anchor",
                queue_name="entities",
            )
            db.commit()
            assert claimed and claimed["id"] == queue_job_id
            worker_result = worker_runner.execute_claimed_job(db, claimed)
            assert worker_result["status"] == "completed"

        with session_scope() as db:
            row = db.execute(
                text("SELECT identity_anchors FROM characters WHERE id = :id"),
                {"id": char["id"]},
            ).mappings().first()
            assert row is not None
            anchors_val = row["identity_anchors"]
            if isinstance(anchors_val, str):
                anchors_val = json.loads(anchors_val)
            assert anchors_val["face"] == "瓜子脸，清纯秀丽"
            assert anchors_val["features"] == "发系红色发带"


def test_story_generation_background_flow(client: TestClient):
    d = _create_drama(client)

    mock_episodes = [
        {"episode": 1, "title": "初遇灵儿", "content": "李逍遥登岛初遇赵灵儿。"},
        {"episode": 2, "title": "拜堂成亲", "content": "在姥姥见证下两人拜堂成亲。"},
    ]

    with patch("app.services.aiClient.generate_text", return_value=json.dumps(mock_episodes, ensure_ascii=False)):
        # 1. 提交故事生成任务
        r = client.post("/api/v1/generation/story", json={"drama_id": d["id"], "premise": "仙灵岛求药遇灵儿", "episode_count": 2})
        assert r.status_code == 200
        task_id = r.json()["data"]["task_id"]
        assert task_id

        t = _wait_for_task(task_id)

    # 验证任务完成与剧集持久化
    assert t["status"] == "completed"

    drama_row = client.get(f"/api/v1/dramas/{d['id']}").json()["data"]
    episodes = drama_row["episodes"]
    assert len(episodes) == 2
    assert episodes[0]["title"] == "初遇灵儿"
    assert episodes[1]["title"] == "拜堂成亲"


def test_background_extraction_flow(client: TestClient):
    d = _create_drama(client)
    e = _create_episode(client, d["id"])

    mock_scenes = [
        {
            "location": "仙灵岛荷花池",
            "time": "清晨",
            "prompt": "Tranquil lotus pond in ancient Chinese fantasy style",
            "atmosphere": "幽静仙气",
        }
    ]

    def fake_generate_text(db, log, service_type, user_prompt, system_prompt, options=None):
        if "翻译" in user_prompt:
            return "宁静的荷花池，古风仙侠风格"
        if "四格" in user_prompt or "场景信息" in user_prompt:
            return "Four views of a peaceful misty lotus pond"
        return json.dumps(mock_scenes, ensure_ascii=False)

    with patch("app.services.aiClient.generate_text", side_effect=fake_generate_text), \
         patch("app.services.sceneService.generate_scene_prompt_only"):
        # 1. 提交场景提取任务
        r = client.post(
            f"/api/v1/images/episode/{e['id']}/backgrounds/extract",
            json={"language": "zh"},
        )
        assert r.status_code == 200
        task_id = r.json()["data"]["task_id"]
        assert task_id

        t = _wait_for_task(task_id)

    # 验证任务完成
    assert t["status"] == "completed"
    res = t["result"]
    if isinstance(res, str):
        res = json.loads(res)
    assert res["count"] == 1

    # 验证场景持久化
    with session_scope() as db:
        scenes = db.execute(
            text("SELECT * FROM scenes WHERE episode_id = :eid AND deleted_at IS NULL"),
            {"eid": e["id"]},
        ).mappings().all()
        assert len(scenes) == 1
        assert scenes[0]["location"] == "仙灵岛荷花池"
        assert "荷花池" in scenes[0]["prompt"]
