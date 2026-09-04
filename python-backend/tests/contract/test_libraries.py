"""契约安全网：/api/v1/{character,scene,prop}-library。

Node 行为基线（backend-node/src/routes/{character,scene,prop}Library.js）：
- GET    /:lib        → successWithPagination（items/total/page/page_size/total_pages）
- POST   /:lib        → 201 新建项
- GET    /:lib/:id    → 404 'X库项不存在'
- PUT    /:lib/:id    → 404 | 200 更新后项
- DELETE /:lib/:id    → 404 | 200 { message: '删除成功' }（软删 deleted_at）
- 分页：page 默认 1，page_size 默认 20 且 clamp 到 [1,100]
- 过滤：global=1（drama_id IS NULL）、drama_id、category、source_type、source_id/source_ids、keyword
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

LIBS = [
    ("/character-library", "角色库项不存在", {"name": "林晚", "description": "女主", "category": "主角"}),
    ("/scene-library", "场景库项不存在", {"location": "卧室内", "time": "清晨", "prompt": "古风卧室", "category": "室内"}),
    ("/prop-library", "道具库项不存在", {"name": "玉佩", "description": "信物", "prompt": "羊脂玉佩", "category": "道具"}),
]

IDS = [lib for lib, _, _ in LIBS]


def _create(client: TestClient, path: str, payload: dict, **extra):
    return client.post(f"/api/v1{path}", json={**payload, **extra})


# ---------------- 通用 CRUD ----------------


@pytest.mark.parametrize("path,missing,payload", LIBS)
def test_crud_roundtrip(client: TestClient, path: str, missing: str, payload: dict):
    # 空列表
    r = client.get(f"/api/v1{path}")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["items"] == []
    assert body["data"]["pagination"] == {"page": 1, "page_size": 20, "total": 0, "total_pages": 0}

    # 创建
    rc = _create(client, path, payload, source_type="manual")
    assert rc.status_code == 201
    item = rc.json()["data"]
    assert item["id"] >= 1
    assert item["source_type"] == "manual"
    assert item["source_id"] is None
    assert item["drama_id"] is None
    assert item["created_at"] and item["updated_at"]
    assert "deleted_at" not in item  # Node rowToItem 不输出该字段

    # 读取
    rg = client.get(f"/api/v1{path}/{item['id']}")
    assert rg.json()["data"]["id"] == item["id"]

    # 更新
    ru = client.put(f"/api/v1{path}/{item['id']}", json={"category": "改后"})
    assert ru.status_code == 200
    assert ru.json()["data"]["category"] == "改后"

    # 软删
    rd = client.delete(f"/api/v1{path}/{item['id']}")
    assert rd.json()["data"] == {"message": "删除成功"}
    assert client.get(f"/api/v1{path}/{item['id']}").status_code == 404
    assert client.get(f"/api/v1{path}").json()["data"]["pagination"]["total"] == 0


@pytest.mark.parametrize("path,missing,payload", LIBS)
def test_not_found_messages(client: TestClient, path: str, missing: str, payload: dict):
    for resp in (
        client.get(f"/api/v1{path}/999999"),
        client.put(f"/api/v1{path}/999999", json={"category": "x"}),
        client.delete(f"/api/v1{path}/999999"),
    ):
        assert resp.status_code == 404
        assert resp.json()["error"] == {"code": "NOT_FOUND", "message": missing}


# ---------------- 分页与过滤 ----------------


def test_pagination_defaults_and_clamp(client: TestClient):
    path = "/character-library"
    for i in range(5):
        _create(client, path, {"name": f"角色{i}", "description": f"描述{i}"})

    r = client.get(f"/api/v1{path}?page=2&page_size=2")
    data = r.json()["data"]
    assert data["pagination"] == {"page": 2, "page_size": 2, "total": 5, "total_pages": 3}
    assert len(data["items"]) == 2

    # page_size 上限 100，非法值回退默认 20
    r2 = client.get(f"/api/v1{path}?page_size=999")
    assert r2.json()["data"]["pagination"]["page_size"] == 100
    r3 = client.get(f"/api/v1{path}?page_size=0")
    assert r3.json()["data"]["pagination"]["page_size"] == 20
    r4 = client.get(f"/api/v1{path}?page=abc")
    assert r4.json()["data"]["pagination"]["page"] == 1


def test_filters_global_drama_category_source(client: TestClient):
    path = "/prop-library"
    _create(client, path, {"name": "全局道具"}, source_type="global")
    _create(client, path, {"name": "剧内道具", "drama_id": 3}, source_type="drama")
    _create(client, path, {"name": "来源道具", "drama_id": 3, "source_id": "S1"}, source_type="drama")

    # global=1 → drama_id IS NULL
    r = client.get(f"/api/v1{path}?global=1")
    assert [i["name"] for i in r.json()["data"]["items"]] == ["全局道具"]

    # drama_id
    r2 = client.get(f"/api/v1{path}?drama_id=3")
    names = {i["name"] for i in r2.json()["data"]["items"]}
    assert names == {"剧内道具", "来源道具"}

    # source_type
    r3 = client.get(f"/api/v1{path}?source_type=global")
    assert [i["name"] for i in r3.json()["data"]["items"]] == ["全局道具"]

    # source_id
    r4 = client.get(f"/api/v1{path}?source_id=S1")
    assert [i["name"] for i in r4.json()["data"]["items"]] == ["来源道具"]

    # source_ids 多值（重复参数 & 逗号串两种写法）
    r5 = client.get(f"/api/v1{path}?source_ids=S1&source_ids=S2")
    assert [i["name"] for i in r5.json()["data"]["items"]] == ["来源道具"]
    r6 = client.get(f"/api/v1{path}?source_ids=S1,S2")
    assert [i["name"] for i in r6.json()["data"]["items"]] == ["来源道具"]

    # category
    _create(client, path, {"name": "分类道具", "category": "兵器"})
    r7 = client.get(f"/api/v1{path}?category=兵器")
    assert [i["name"] for i in r7.json()["data"]["items"]] == ["分类道具"]


def test_keyword_search_columns(client: TestClient):
    # character: name/description；scene: location/description/prompt；prop: name/description/prompt
    _create(client, "/character-library", {"name": "张三", "description": "无"})
    _create(client, "/character-library", {"name": "无", "description": "李四"})
    assert client.get("/api/v1/character-library?keyword=张三").json()["data"]["pagination"]["total"] == 1
    assert client.get("/api/v1/character-library?keyword=李四").json()["data"]["pagination"]["total"] == 1

    _create(client, "/scene-library", {"location": "庭院", "prompt": "青石板路"})
    assert client.get("/api/v1/scene-library?keyword=庭院").json()["data"]["pagination"]["total"] == 1
    assert client.get("/api/v1/scene-library?keyword=青石板").json()["data"]["pagination"]["total"] == 1

    _create(client, "/prop-library", {"name": "长剑", "prompt": "寒光凛冽"})
    assert client.get("/api/v1/prop-library?keyword=长剑").json()["data"]["pagination"]["total"] == 1
    assert client.get("/api/v1/prop-library?keyword=寒光").json()["data"]["pagination"]["total"] == 1


# ---------------- 字段映射细节 ----------------


def test_character_item_fields(client: TestClient):
    item = _create(
        client,
        "/character-library",
        {"name": "苏明", "image_url": "http://x/a.png", "local_path": "a/b.png", "tags": "古风"},
    ).json()["data"]
    assert set(item.keys()) == {
        "id",
        "drama_id",
        "name",
        "category",
        "image_url",
        "local_path",
        "description",
        "tags",
        "source_type",
        "source_id",
        "created_at",
        "updated_at",
    }
    assert item["name"] == "苏明"
    assert item["image_url"] == "http://x/a.png"
    assert item["local_path"] == "a/b.png"
    assert item["tags"] == "古风"


def test_scene_item_fields(client: TestClient):
    item = _create(
        client, "/scene-library", {"location": "书房", "time": "夜", "prompt": "古书房", "category": "室内"}
    ).json()["data"]
    assert set(item.keys()) == {
        "id",
        "drama_id",
        "location",
        "time",
        "prompt",
        "description",
        "image_url",
        "local_path",
        "category",
        "tags",
        "source_type",
        "source_id",
        "created_at",
        "updated_at",
    }
    assert item["location"] == "书房"


def test_prop_item_fields(client: TestClient):
    item = _create(client, "/prop-library", {"name": "丹药", "prompt": "玉瓶丹药"}).json()["data"]
    assert set(item.keys()) == {
        "id",
        "drama_id",
        "name",
        "description",
        "prompt",
        "image_url",
        "local_path",
        "category",
        "tags",
        "source_type",
        "source_id",
        "created_at",
        "updated_at",
    }
    assert item["prompt"] == "玉瓶丹药"


def test_defaults_on_create(client: TestClient):
    """Node 语义：name/location 空串兜底，source_type 默认 generated，image_url 空串。"""
    item = _create(client, "/character-library", {}).json()["data"]
    assert item["name"] == ""
    assert item["image_url"] == ""
    assert item["source_type"] == "generated"
    assert item["category"] is None

    s = _create(client, "/scene-library", {}).json()["data"]
    assert s["location"] == ""
    assert s["source_type"] == "generated"

    p = _create(client, "/prop-library", {}).json()["data"]
    assert p["name"] == ""
    assert p["source_type"] == "generated"


def test_update_no_fields_returns_current(client: TestClient):
    """Node：updates 为空时直接回读，不报错。"""
    created = _create(client, "/character-library", {"name": "原名"}).json()["data"]
    r = client.put(f"/api/v1/character-library/{created['id']}", json={})
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "原名"


def test_update_normalizes_source_id(client: TestClient):
    created = _create(client, "/character-library", {"name": "X"}).json()["data"]
    r = client.put(f"/api/v1/character-library/{created['id']}", json={"source_id": "  S7  "})
    assert r.json()["data"]["source_id"] == "S7"
