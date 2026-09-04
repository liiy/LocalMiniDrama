"""契约安全网：/api/v1/dramas/* （backend-node/src/routes/drama.js 纯 CRUD 部分）。

Node 行为基线：
- POST   /dramas                     → 400 '标题不能为空' | 201 聚合对象
- GET    /dramas                     → 分页，含 episodes[].storyboards
- GET    /dramas/stats               → { total, by_status }
- GET    /dramas/{id}                → 404 '剧本不存在' | 聚合（episodes/characters/scenes/props）
- PUT    /dramas/{id}                → 404 | 更新后对象
- DELETE /dramas/{id}                → 404 | { message: '删除成功' }
- PUT    /dramas/{id}/outline        → 404 | { message: '保存成功' }
- GET    /dramas/{id}/characters     → 404 '剧本或章节不存在'
- PUT    /dramas/{id}/characters     → 400 'characters 必填且为数组' | 404
- PUT    /dramas/{id}/episodes       → 400 'episodes 必填且为数组' | 404
- PUT    /dramas/{id}/progress       → 400 'current_step 必填' | 404
- PUT    /dramas/{id}/canvas-layout  → 400 三种文案 | 404
- GET    /dramas/{id}/props          → 独立字段映射（无 error_msg、image_url 不 sanitize）
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _mk(client: TestClient, **extra) -> dict:
    r = client.post("/api/v1/dramas", json={"title": "测试剧本", **extra})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_create_requires_title(client: TestClient):
    assert client.post("/api/v1/dramas", json={"description": "x"}).status_code == 400
    r = client.post("/api/v1/dramas", json={"title": "   "})
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "BAD_REQUEST", "message": "标题不能为空"}


def test_create_defaults_and_metadata(client: TestClient):
    d = _mk(client)
    assert d["title"] == "测试剧本"
    assert d["style"] == "realistic"
    assert d["status"] == "draft"  # create 硬编码 draft，不随入参
    assert d["total_episodes"] == 1
    assert d["total_duration"] == 0
    # storage_folder_label 自动写入 metadata
    assert d["metadata"]["storage_folder_label"] == "测试剧本"
    # create 返回 getDramaById（不含聚合字段，与 Node 一致）
    assert "episodes" not in d
    assert "characters" not in d
    assert "scenes" not in d
    assert "props" not in d


def test_get_drama_not_found(client: TestClient):
    r = client.get("/api/v1/dramas/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "剧本不存在"


def test_list_pagination_and_filters(client: TestClient):
    _mk(client, title="古装剧", genre="古装")
    b = _mk(client, title="都市剧", genre="都市")
    client.put(f"/api/v1/dramas/{b['id']}", json={"status": "completed"})

    r = client.get("/api/v1/dramas")
    data = r.json()["data"]
    assert data["pagination"] == {"page": 1, "page_size": 20, "total": 2, "total_pages": 1}

    r2 = client.get("/api/v1/dramas?genre=古装")
    assert [d["title"] for d in r2.json()["data"]["items"]] == ["古装剧"]

    r3 = client.get("/api/v1/dramas?status=completed")
    assert [d["title"] for d in r3.json()["data"]["items"]] == ["都市剧"]

    r4 = client.get("/api/v1/dramas?keyword=都市")
    assert [d["title"] for d in r4.json()["data"]["items"]] == ["都市剧"]

    r5 = client.get("/api/v1/dramas?page=2&page_size=1")
    assert r5.json()["data"]["pagination"]["page"] == 2


def test_stats(client: TestClient):
    _mk(client, title="A")
    b = _mk(client, title="B")
    client.put(f"/api/v1/dramas/{b['id']}", json={"status": "completed"})
    r = client.get("/api/v1/dramas/stats")
    data = r.json()["data"]
    assert data["total"] == 2
    by = {x["status"]: x["count"] for x in data["by_status"]}
    assert by == {"draft": 1, "completed": 1}


def test_update_and_delete(client: TestClient):
    d = _mk(client)
    r = client.put(f"/api/v1/dramas/{d['id']}", json={"title": "改名", "status": "completed"})
    assert r.json()["data"]["title"] == "改名"
    assert r.json()["data"]["status"] == "completed"
    # 未传字段保持
    assert r.json()["data"]["genre"] is None

    assert client.put("/api/v1/dramas/999999", json={"title": "x"}).status_code == 404

    rd = client.delete(f"/api/v1/dramas/{d['id']}")
    assert rd.json()["data"] == {"message": "删除成功"}
    assert client.get(f"/api/v1/dramas/{d['id']}").status_code == 404
    assert client.delete(f"/api/v1/dramas/{d['id']}").status_code == 404
    # 软删后不出现在列表与统计
    assert client.get("/api/v1/dramas").json()["data"]["pagination"]["total"] == 0


def test_save_outline(client: TestClient):
    d = _mk(client)
    r = client.put(
        f"/api/v1/dramas/{d['id']}/outline",
        json={"title": "大纲标题", "summary": "梗概", "genre": "古装", "tags": ["a", "b"], "style": "ink wash"},
    )
    assert r.json()["data"] == {"message": "保存成功"}

    d2 = client.get(f"/api/v1/dramas/{d['id']}").json()["data"]
    assert d2["title"] == "大纲标题"
    assert d2["description"] == "梗概"
    assert d2["genre"] == "古装"
    assert d2["tags"] == '["a", "b"]'
    assert d2["style"] == "ink wash"
    # style 变更会展开画风提示词到 metadata
    assert "style_prompt_zh" in d2["metadata"]
    assert "style_prompt_en" in d2["metadata"]
    # 原有 metadata 保留
    assert d2["metadata"]["storage_folder_label"] == "测试剧本"

    assert client.put("/api/v1/dramas/999999/outline", json={"title": "x"}).status_code == 404


def test_episodes_crud_via_save(client: TestClient):
    d = _mk(client)
    r = client.put(
        f"/api/v1/dramas/{d['id']}/episodes",
        json={
            "episodes": [
                {"episode_number": 1, "title": "第一集", "script_content": "内容1", "duration": 60},
                {"episode_number": 2, "title": "第二集", "script_content": "内容2"},
            ]
        },
    )
    assert r.json()["data"] == {"message": "保存成功"}

    d2 = client.get(f"/api/v1/dramas/{d['id']}").json()["data"]
    assert [(e["episode_number"], e["title"]) for e in d2["episodes"]] == [(1, "第一集"), (2, "第二集")]
    assert d2["episodes"][1]["duration"] == 0  # 缺省补 0

    # 重新提交会复用 id 并软删未提交的集
    ids_before = [e["id"] for e in d2["episodes"]]
    client.put(
        f"/api/v1/dramas/{d['id']}/episodes",
        json={"episodes": [{"episode_number": 1, "title": "第一集改"}]},
    )
    d3 = client.get(f"/api/v1/dramas/{d['id']}").json()["data"]
    assert len(d3["episodes"]) == 1
    assert d3["episodes"][0]["id"] == ids_before[0]  # id 复用
    assert d3["episodes"][0]["title"] == "第一集改"

    # 校验
    r2 = client.put(f"/api/v1/dramas/{d['id']}/episodes", json={"episodes": "x"})
    assert r2.status_code == 400
    assert r2.json()["error"]["message"] == "episodes 必填且为数组"
    assert client.put("/api/v1/dramas/999999/episodes", json={"episodes": []}).status_code == 404


def test_characters_save_and_get(client: TestClient):
    d = _mk(client)
    r = client.put(
        f"/api/v1/dramas/{d['id']}/characters",
        json={
            "characters": [
                {
                    "name": "林晚",
                    "role": "main",
                    "description": "女主",
                    "appearance": "青衫",
                    "personality": "冷静",
                },
                {"name": "苏明", "role": "supporting"},
            ]
        },
    )
    assert r.json()["data"] == {"message": "保存成功"}

    chars = client.get(f"/api/v1/dramas/{d['id']}/characters").json()["data"]
    assert [c["name"] for c in chars] == ["林晚", "苏明"]  # sort_order 相同按 name 排序
    assert chars[0]["role"] == "main"
    assert chars[0]["appearance"] == "青衫"

    # 同名再次提交 → 更新并复用 id（不新增）；未提交的角色不会被删除（Node 语义）
    cid = chars[0]["id"]
    client.put(
        f"/api/v1/dramas/{d['id']}/characters",
        json={"characters": [{"name": "林晚", "role": "minor"}]},
    )
    chars2 = {c["name"]: c for c in client.get(f"/api/v1/dramas/{d['id']}/characters").json()["data"]}
    assert set(chars2) == {"林晚", "苏明"}
    assert chars2["林晚"]["id"] == cid
    assert chars2["林晚"]["role"] == "minor"
    # 未传字段被置空（Node 语义：core 字段整体覆盖）
    assert chars2["林晚"]["appearance"] is None

    r2 = client.put(f"/api/v1/dramas/{d['id']}/characters", json={"characters": "x"})
    assert r2.status_code == 400
    assert r2.json()["error"]["message"] == "characters 必填且为数组"
    assert client.put("/api/v1/dramas/999999/characters", json={"characters": []}).status_code == 404


def test_get_characters_by_episode(client: TestClient):
    d = _mk(client)
    client.put(
        f"/api/v1/dramas/{d['id']}/episodes",
        json={"episodes": [{"episode_number": 1, "title": "E1"}]},
    )
    ep = client.get(f"/api/v1/dramas/{d['id']}").json()["data"]["episodes"][0]
    client.put(
        f"/api/v1/dramas/{d['id']}/characters",
        json={"characters": [{"name": "甲"}], "episode_id": ep["id"]},
    )
    r = client.get(f"/api/v1/dramas/{d['id']}/characters?episode_id={ep['id']}")
    assert [c["name"] for c in r.json()["data"]] == ["甲"]

    # 不属于该剧本的 episode_id → 404
    assert client.get(f"/api/v1/dramas/{d['id']}/characters?episode_id=999999").status_code == 404


def test_progress(client: TestClient):
    d = _mk(client)
    r = client.put(f"/api/v1/dramas/{d['id']}/progress", json={"current_step": "story", "step_data": {"k": 1}})
    assert r.json()["data"] == {"message": "保存成功"}
    meta = client.get(f"/api/v1/dramas/{d['id']}").json()["data"]["metadata"]
    assert meta["current_step"] == "story"
    assert meta["step_data"] == {"k": 1}
    # 保留 storage_folder_label
    assert meta["storage_folder_label"] == "测试剧本"

    r2 = client.put(f"/api/v1/dramas/{d['id']}/progress", json={})
    assert r2.status_code == 400
    assert r2.json()["error"]["message"] == "current_step 必填"
    assert client.put("/api/v1/dramas/999999/progress", json={"current_step": "x"}).status_code == 404


def test_canvas_layout(client: TestClient):
    d = _mk(client)
    r = client.put(
        f"/api/v1/dramas/{d['id']}/canvas-layout",
        json={"canvas_layout": {"nodes": {"n1": {}}}, "workflow_groups": [{"id": "g1"}]},
    )
    assert r.status_code == 200
    meta = r.json()["data"]["metadata"]
    assert meta["canvas_layout"] == {"nodes": {"n1": {}}}
    assert meta["workflow_groups"] == [{"id": "g1"}]

    # 三种 400（注意 Node 的判定顺序）
    r1 = client.put(f"/api/v1/dramas/{d['id']}/canvas-layout", json={})
    assert r1.json()["error"]["message"] == "请提供 canvas_layout 或 workflow_groups"
    # canvas_layout 为数组时，因 workflow_groups 未传，命中第一条
    r2 = client.put(f"/api/v1/dramas/{d['id']}/canvas-layout", json={"canvas_layout": [1, 2]})
    assert r2.json()["error"]["message"] == "请提供 canvas_layout 或 workflow_groups"
    # 提供了 workflow_groups 时才走到类型校验
    r2b = client.put(
        f"/api/v1/dramas/{d['id']}/canvas-layout", json={"canvas_layout": "x", "workflow_groups": []}
    )
    assert r2b.json()["error"]["message"] == "canvas_layout 必须为对象"
    r3 = client.put(f"/api/v1/dramas/{d['id']}/canvas-layout", json={"workflow_groups": {"a": 1}})
    assert r3.json()["error"]["message"] == "workflow_groups 必须为数组"

    assert client.put("/api/v1/dramas/999999/canvas-layout", json={"canvas_layout": {}}).status_code == 404


def test_props_endpoint_mapping(client: TestClient):
    d = _mk(client)
    # 直接落库（props 的写入端点在 P4 才翻译）
    from sqlalchemy import text

    from app.db import session as dbm

    with dbm.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO props (drama_id, name, type, description, prompt, negative_prompt, image_url, "
                "local_path, created_at, updated_at) VALUES (:did, '玉佩', '信物', 'd', 'p', NULL, "
                "'data:image/png;base64,AAA', 'a/b.png', '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')"
            ),
            {"did": d["id"]},
        )
    props = client.get(f"/api/v1/dramas/{d['id']}/props").json()["data"]
    assert len(props) == 1
    p = props[0]
    # listByDramaId 不做 sanitize：base64 原样返回（与 Node 一致）
    assert p["image_url"].startswith("data:")
    assert set(p.keys()) == {
        "id",
        "drama_id",
        "name",
        "type",
        "description",
        "prompt",
        "negative_prompt",
        "image_url",
        "local_path",
        "extra_images",
        "ref_image",
        "created_at",
        "updated_at",
    }
