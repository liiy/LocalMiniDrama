"""契约安全网：scenes & props AI 生成与提取端点测试。

对齐 Node 版：
- POST /scenes/:scene_id/generate-prompt        → { message: '提示词已生成', polished_prompt }
- POST /scenes/:scene_id/extract-from-image     → { message: '场景描述已提取', prompt }
- POST /scenes/generate-image                   → { message: '场景视图生成任务已提交', image_generation }
- POST /scenes/:scene_id/generate-four-view-image → { message: '场景四视图生成任务已提交', image_generation }
- POST /props/:id/generate-prompt               → { message: '提示词已生成', prompt }
- POST /props/:id/generate                      → { task_id }
- POST /props/:id/extract-from-image            → { message: '道具描述已提取', description }
- POST /episodes/:episode_id/props/extract      → { task_id }
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _create_drama(client: TestClient) -> dict:
    r = client.post("/api/v1/dramas", json={"title": "AI场景道具测试剧"})
    assert r.status_code == 201
    return r.json()["data"]


def _create_scene(client: TestClient, drama_id: int) -> dict:
    r = client.post(
        "/api/v1/scenes",
        json={"drama_id": drama_id, "name": "皇宫大殿", "location": "紫禁城", "time": "黄昏"},
    )
    assert r.status_code == 201
    return r.json()["data"]


def _create_prop(client: TestClient, drama_id: int) -> dict:
    r = client.post(
        "/api/v1/props",
        json={"drama_id": drama_id, "name": "青龙偃月刀", "type": "兵器", "description": "长柄大刀，重八十二斤"},
    )
    assert r.status_code == 201
    return r.json()["data"]


def _create_episode(client: TestClient, drama_id: int) -> dict:
    r = client.put(
        f"/api/v1/dramas/{drama_id}/episodes",
        json={"episodes": [{"episode_number": 1, "title": "第一回", "script_content": "关羽手提青龙偃月刀，跨上赤兔马。"}]},
    )
    assert r.status_code == 200
    r_drama = client.get(f"/api/v1/dramas/{drama_id}")
    assert r_drama.status_code == 200
    return r_drama.json()["data"]["episodes"][0]


def test_scene_generate_prompt(client: TestClient):
    d = _create_drama(client)
    s = _create_scene(client, d["id"])

    with patch("app.services.aiClient.generate_text", return_value="A magnificent imperial palace hall, sunset lighting"):
        # 1. 默认四视图（会拼接风格前缀和网格指令）
        r = client.post(f"/api/v1/scenes/{s['id']}/generate-prompt", json={})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["message"] == "提示词已生成"
        assert "A magnificent imperial palace hall, sunset lighting" in data["polished_prompt"]

        # 2. 单图模式（直接返回AI生成结果）
        r2 = client.post(f"/api/v1/scenes/{s['id']}/generate-prompt", json={"mode": "single"})
        assert r2.status_code == 200
        data2 = r2.json()["data"]
        assert data2["message"] == "提示词已生成"
        assert "A magnificent imperial palace hall, sunset lighting" in data2["polished_prompt_single"]


def test_scene_generate_image_not_found(client: TestClient):
    r = client.post("/api/v1/scenes/generate-image", json={"scene_id": 999999})
    assert r.status_code == 404
    assert "场景不存在" in r.json()["error"]["message"]


def test_scene_generate_image_missing_id(client: TestClient):
    r = client.post("/api/v1/scenes/generate-image", json={})
    assert r.status_code == 400
    assert "缺少 scene_id" in r.json()["error"]["message"]


def test_prop_generate_prompt(client: TestClient):
    d = _create_drama(client)
    p = _create_prop(client, d["id"])

    with patch("app.services.aiClient.generate_text", return_value="A massive Chinese crescent blade with dragon engravings"):
        r = client.post(f"/api/v1/props/{p['id']}/generate-prompt", json={})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["message"] == "提示词已生成"
        assert data["prompt"] == "A massive Chinese crescent blade with dragon engravings"


def test_prop_generate_image(client: TestClient):
    d = _create_drama(client)
    p = _create_prop(client, d["id"])

    # 先设置 prompt
    client.put(f"/api/v1/props/{p['id']}", json={"prompt": "A Chinese crescent blade"})

    with patch("app.services.workerService.submit") as mock_submit:
        r = client.post(f"/api/v1/props/{p['id']}/generate", json={})
        assert r.status_code == 200
        data = r.json()["data"]
        assert "task_id" in data
        assert mock_submit.called


def test_episode_props_extract(client: TestClient):
    d = _create_drama(client)
    ep = _create_episode(client, d["id"])

    with patch("app.services.workerService.submit") as mock_submit:
        r = client.post(f"/api/v1/episodes/{ep['id']}/props/extract", json={})
        assert r.status_code == 200
        data = r.json()["data"]
        assert "task_id" in data
        assert mock_submit.called
