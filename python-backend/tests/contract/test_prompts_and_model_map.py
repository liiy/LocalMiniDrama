"""契约安全网：/api/v1/settings/prompts 与 /api/v1/scene-model-map。

Node 行为基线（backend-node/src/routes/promptOverrides.js、sceneModelMap.js）：
- GET    /settings/prompts      → success({ prompts: [9 项] })
- PUT    /settings/prompts/:key → 400 '未知的提示词 key: X' | 400 'content 不能为空' | { ok, key }
- DELETE /settings/prompts/:key → 400 '未知的提示词 key: X' | { ok, key }
- POST   /scene-model-map       → 400 '缺少必填字段: key' | 400 '场景键已存在' | 201 row
- GET/PUT/DELETE /scene-model-map/:key → 404 '场景模型映射不存在'
"""
from __future__ import annotations

from fastapi.testclient import TestClient

PROMPT_KEYS = [
    "story_expansion_system",
    "storyboard_system",
    "character_extraction",
    "scene_extraction",
    "prop_extraction",
    "storyboard_user_suffix",
    "first_frame_prompt",
    "key_frame_prompt",
    "last_frame_prompt",
]


# ---------------- settings/prompts ----------------


def test_list_prompts_shape(client: TestClient):
    r = client.get("/api/v1/settings/prompts")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    prompts = body["data"]["prompts"]
    assert [p["key"] for p in prompts] == PROMPT_KEYS
    for p in prompts:
        assert set(p.keys()) == {
            "key",
            "label",
            "description",
            "default_body",
            "locked_suffix",
            "current_body",
            "is_customized",
        }
        assert p["current_body"] is None
        assert p["is_customized"] is False
        assert isinstance(p["default_body"], str) and p["default_body"] != ""
    # story_expansion_system 的锁定后缀为 null，其余非空
    by_key = {p["key"]: p for p in prompts}
    assert by_key["story_expansion_system"]["locked_suffix"] is None
    assert by_key["storyboard_system"]["locked_suffix"] != ""


def test_put_and_reset_prompt(client: TestClient):
    r = client.put("/api/v1/settings/prompts/character_extraction", json={"content": "  自定义内容  "})
    assert r.status_code == 200
    assert r.json()["data"] == {"ok": True, "key": "character_extraction"}

    # 列表里应可见（内容已 trim）
    r2 = client.get("/api/v1/settings/prompts")
    item = next(p for p in r2.json()["data"]["prompts"] if p["key"] == "character_extraction")
    assert item["current_body"] == "自定义内容"
    assert item["is_customized"] is True

    # 重置
    r3 = client.delete("/api/v1/settings/prompts/character_extraction")
    assert r3.json()["data"] == {"ok": True, "key": "character_extraction"}
    r4 = client.get("/api/v1/settings/prompts")
    item = next(p for p in r4.json()["data"]["prompts"] if p["key"] == "character_extraction")
    assert item["current_body"] is None
    assert item["is_customized"] is False


def test_prompt_unknown_key(client: TestClient):
    r = client.put("/api/v1/settings/prompts/nope", json={"content": "x"})
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "BAD_REQUEST", "message": "未知的提示词 key: nope"}

    r2 = client.delete("/api/v1/settings/prompts/nope")
    assert r2.status_code == 400
    assert r2.json()["error"]["message"] == "未知的提示词 key: nope"


def test_prompt_empty_content(client: TestClient):
    r = client.put("/api/v1/settings/prompts/prop_extraction", json={"content": "   "})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "content 不能为空"

    r2 = client.put("/api/v1/settings/prompts/prop_extraction", json={})
    assert r2.status_code == 400
    assert r2.json()["error"]["message"] == "content 不能为空"


# ---------------- scene-model-map ----------------


def test_model_map_crud(client: TestClient):
    assert client.get("/api/v1/scene-model-map").json()["data"] == []

    r = client.post("/api/v1/scene-model-map", json={"key": "scene_a", "description": "A"})
    assert r.status_code == 201
    row = r.json()["data"]
    assert row["key"] == "scene_a"
    assert row["service_type"] == "text"  # 默认值
    assert row["config_id"] is None
    assert row["model_override"] is None
    assert row["description"] == "A"
    assert row["id"] >= 1

    # 重复 key
    r2 = client.post("/api/v1/scene-model-map", json={"key": "scene_a"})
    assert r2.status_code == 400
    assert r2.json()["error"]["message"] == "场景键已存在"

    # 缺 key
    r3 = client.post("/api/v1/scene-model-map", json={"description": "no key"})
    assert r3.status_code == 400
    assert r3.json()["error"]["message"] == "缺少必填字段: key"

    # get
    r4 = client.get("/api/v1/scene-model-map/scene_a")
    assert r4.json()["data"]["key"] == "scene_a"

    # update
    r5 = client.put(
        "/api/v1/scene-model-map/scene_a",
        json={"service_type": "image", "config_id": 7, "model_override": "m1"},
    )
    assert r5.status_code == 200
    d = r5.json()["data"]
    assert d["service_type"] == "image"
    assert d["config_id"] == 7
    assert d["model_override"] == "m1"
    # Node 用 !== undefined 语义：未传 description 会被置为空串（非保持原值）
    assert d["description"] == ""

    # delete
    r6 = client.delete("/api/v1/scene-model-map/scene_a")
    assert r6.json()["data"] == {"message": "删除成功"}
    assert client.get("/api/v1/scene-model-map").json()["data"] == []


def test_model_map_not_found(client: TestClient):
    assert client.get("/api/v1/scene-model-map/ghost").status_code == 404
    assert client.put("/api/v1/scene-model-map/ghost", json={}).status_code == 404
    assert client.delete("/api/v1/scene-model-map/ghost").status_code == 404
    body = client.get("/api/v1/scene-model-map/ghost").json()
    assert body["error"] == {"code": "NOT_FOUND", "message": "场景模型映射不存在"}
