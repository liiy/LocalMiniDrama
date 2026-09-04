"""契约安全网：/api/v1/episodes/* 与 Node 版 backend-node/src/routes/index.js + drama.js 行为等价。

Node 行为基线：
- GET  /episodes/:episode_id/storyboards   → { storyboards: [...], total: n }
- POST /episodes/:episode_id/characters/extract → { task_id }
- POST /episodes/:episode_id/props/extract      → { task_id }
- POST /episodes/:episode_id/finalize          → { merge_id, episode_id, scenes_count, task_id }
- GET  /episodes/:episode_id/download          → 404 (不存在) | 400 (无视频) | { video_url, title, episode_number }
- POST /episodes/:episode_id/storyboards       → { task_id, status: 'pending', message: '...' }
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _create_drama_and_episode(client: TestClient) -> tuple[dict, dict]:
    r = client.post("/api/v1/dramas", json={"title": "分镜测试剧"})
    assert r.status_code == 201
    d = r.json()["data"]

    r_ep = client.put(
        f"/api/v1/dramas/{d['id']}/episodes",
        json={"episodes": [{"episode_number": 1, "title": "第一回", "script_content": "关羽挥起青龙偃月刀斩杀华雄。"}]},
    )
    assert r_ep.status_code == 200

    r_drama = client.get(f"/api/v1/dramas/{d['id']}")
    assert r_drama.status_code == 200
    ep = r_drama.json()["data"]["episodes"][0]
    return d, ep


def test_get_episode_storyboards_empty(client: TestClient):
    d, ep = _create_drama_and_episode(client)
    r = client.get(f"/api/v1/episodes/{ep['id']}/storyboards")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["storyboards"] == []
    assert data["total"] == 0


def test_episode_characters_extract(client: TestClient):
    d, ep = _create_drama_and_episode(client)
    r = client.post(f"/api/v1/episodes/{ep['id']}/characters/extract")
    assert r.status_code == 200
    assert "task_id" in r.json()["data"]


def test_episode_download_not_found(client: TestClient):
    r = client.get("/api/v1/episodes/999999/download")
    assert r.status_code == 404
    assert "剧集不存在" in r.json()["error"]["message"]


def test_episode_download_no_video(client: TestClient):
    d, ep = _create_drama_and_episode(client)
    r = client.get(f"/api/v1/episodes/{ep['id']}/download")
    assert r.status_code == 400
    assert "还没有生成视频" in r.json()["error"]["message"]


def test_episode_finalize_not_found(client: TestClient):
    r = client.post("/api/v1/episodes/999999/finalize", json={})
    assert r.status_code == 404
    assert "剧集不存在" in r.json()["error"]["message"]


def test_episode_finalize_success(client: TestClient):
    d, ep = _create_drama_and_episode(client)
    r = client.post(f"/api/v1/episodes/{ep['id']}/finalize", json={})
    assert r.status_code == 200
    data = r.json()["data"]
    assert "merge_id" in data
    assert str(data["episode_id"]) == str(ep["id"])
    assert "task_id" in data
