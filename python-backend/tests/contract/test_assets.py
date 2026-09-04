"""契约安全网：/api/v1/assets/* 与 Node 版 backend-node/src/routes/assets.js 行为等价。

Node 行为基线：
- GET    /assets            → successWithPagination(items, total, page, pageSize)
                              page = max(1, parseInt(page,10)||1)；page_size = min(100, max(1, parseInt||20))
- POST   /assets            → 201；name 默认 '未命名'、type 默认 'image'、url 默认 ''
- POST   /assets/import/image/{id} → 404 '图片生成记录不存在' | 201（name='图片 {id}'）
- POST   /assets/import/video/{id} → 404 '视频生成记录不存在' | 201（name='视频 {id}'）
- GET    /assets/{id}       → 404 '资源不存在'
- PUT    /assets/{id}       → 404 | 200（空 body 原样返回）
- DELETE /assets/{id}       → 404 | { message: '删除成功' }
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import session as dbm

BASE = "/api/v1/assets"


def _create(client: TestClient, **overrides):
    return client.post(BASE, json={"name": "测试素材", **overrides})


def _seed_image(image_url: str = "http://x/a.png", local_path: str = "/s/a.png", drama_id: int = 7) -> int:
    with dbm.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO image_generations (drama_id, image_url, local_path, created_at) "
                "VALUES (:d, :u, :p, '2026-01-01T00:00:00.000Z')"
            ),
            {"d": drama_id, "u": image_url, "p": local_path},
        )
        return conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()


def _seed_video(video_url: str = "http://x/a.mp4", local_path: str = "/s/a.mp4", drama_id: int = 8) -> int:
    with dbm.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO video_generations (drama_id, video_url, local_path, created_at) "
                "VALUES (:d, :u, :p, '2026-01-01T00:00:00.000Z')"
            ),
            {"d": drama_id, "u": video_url, "p": local_path},
        )
        return conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()


# ---------------- create ----------------


def test_create_returns_201_with_defaults(client: TestClient):
    r = client.post(BASE, json={})
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["name"] == "未命名"
    assert data["type"] == "image"
    assert data["url"] == ""
    assert data["drama_id"] is None
    assert data["category"] is None
    assert data["duration"] is None
    assert set(data) == {
        "id",
        "drama_id",
        "name",
        "type",
        "category",
        "url",
        "local_path",
        "duration",
        "image_gen_id",
        "video_gen_id",
        "created_at",
        "updated_at",
    }


def test_create_with_full_payload(client: TestClient):
    r = _create(
        client,
        drama_id=3,
        type="video",
        category="分镜",
        url="http://x/v.mp4",
        local_path="/s/v.mp4",
        duration=5.5,
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["drama_id"] == 3
    assert data["type"] == "video"
    assert data["duration"] == 5.5


# ---------------- list ----------------


def test_list_empty(client: TestClient):
    r = client.get(BASE)
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["items"] == []
    assert body["data"]["pagination"] == {"page": 1, "page_size": 20, "total": 0, "total_pages": 0}


def test_list_pagination(client: TestClient):
    for i in range(3):
        _create(client, name=f"A{i}")
    r = client.get(BASE, params={"page": "1", "page_size": "2"})
    d = r.json()["data"]
    assert len(d["items"]) == 2
    assert d["pagination"] == {"page": 1, "page_size": 2, "total": 3, "total_pages": 2}


def test_list_page_size_capped_at_100(client: TestClient):
    r = client.get(BASE, params={"page_size": "999"})
    assert r.json()["data"]["pagination"]["page_size"] == 100


def test_list_page_size_zero_falls_back_to_20(client: TestClient):
    """Node：parseInt('0')||20 → 20。"""
    r = client.get(BASE, params={"page_size": "0"})
    assert r.json()["data"]["pagination"]["page_size"] == 20


def test_list_invalid_page_falls_back(client: TestClient):
    r = client.get(BASE, params={"page": "abc", "page_size": "abc"})
    p = r.json()["data"]["pagination"]
    assert p["page"] == 1
    assert p["page_size"] == 20


def test_list_filter_by_drama_id(client: TestClient):
    _create(client, name="A", drama_id=1)
    _create(client, name="B", drama_id=2)
    r = client.get(BASE, params={"drama_id": "2"})
    d = r.json()["data"]
    assert len(d["items"]) == 1
    assert d["items"][0]["name"] == "B"


def test_list_filter_by_type(client: TestClient):
    _create(client, name="A", type="image")
    _create(client, name="B", type="video")
    r = client.get(BASE, params={"type": "video"})
    d = r.json()["data"]
    assert len(d["items"]) == 1
    assert d["items"][0]["name"] == "B"


# ---------------- get / update / delete ----------------


def test_get_asset(client: TestClient):
    aid = _create(client).json()["data"]["id"]
    r = client.get(f"{BASE}/{aid}")
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "测试素材"


def test_get_asset_not_found(client: TestClient):
    r = client.get(f"{BASE}/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "资源不存在"


def test_get_asset_invalid_id_is_404(client: TestClient):
    """Node 用 Number('abc')=NaN 查不到行 → 404（不是 400）。"""
    r = client.get(f"{BASE}/abc")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "资源不存在"


def test_update_asset(client: TestClient):
    aid = _create(client).json()["data"]["id"]
    r = client.put(f"{BASE}/{aid}", json={"name": "改名", "category": "道具"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["name"] == "改名"
    assert d["category"] == "道具"


def test_update_empty_body_returns_existing(client: TestClient):
    aid = _create(client).json()["data"]["id"]
    r = client.put(f"{BASE}/{aid}", json={})
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "测试素材"


def test_update_not_found(client: TestClient):
    r = client.put(f"{BASE}/999999", json={"name": "x"})
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "资源不存在"


def test_delete_asset(client: TestClient):
    aid = _create(client).json()["data"]["id"]
    r = client.delete(f"{BASE}/{aid}")
    assert r.status_code == 200
    assert r.json()["data"] == {"message": "删除成功"}
    assert client.get(f"{BASE}/{aid}").status_code == 404
    assert client.get(BASE).json()["data"]["items"] == []


def test_delete_not_found(client: TestClient):
    r = client.delete(f"{BASE}/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "资源不存在"


# ---------------- import ----------------


def test_import_image(client: TestClient):
    gid = _seed_image()
    r = client.post(f"{BASE}/import/image/{gid}")
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["name"] == f"图片 {gid}"
    assert d["type"] == "image"
    assert d["url"] == "http://x/a.png"
    assert d["local_path"] == "/s/a.png"
    assert d["image_gen_id"] == gid
    assert d["drama_id"] == 7


def test_import_image_not_found(client: TestClient):
    r = client.post(f"{BASE}/import/image/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "图片生成记录不存在"


def test_import_video(client: TestClient):
    gid = _seed_video()
    r = client.post(f"{BASE}/import/video/{gid}")
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["name"] == f"视频 {gid}"
    assert d["type"] == "video"
    assert d["url"] == "http://x/a.mp4"
    assert d["video_gen_id"] == gid
    assert d["drama_id"] == 8


def test_import_video_not_found(client: TestClient):
    r = client.post(f"{BASE}/import/video/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "视频生成记录不存在"


def test_import_image_invalid_id_is_404(client: TestClient):
    r = client.post(f"{BASE}/import/image/abc")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "图片生成记录不存在"
