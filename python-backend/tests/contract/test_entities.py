"""契约安全网：characters / scenes / props / storyboards 的 CRUD 端点。

Node 行为基线：
- GET    /characters/:id  → 404 '角色不存在' | { character: 固定字段集 }
- PUT    /characters/:id  → 404 | { message: '保存成功' }
- DELETE /characters/:id  → 404 | { message: '删除成功' }
- POST   /scenes          → 400 '缺少 drama_id' | 201 scene
- GET    /scenes/:id      → 404 '场景不存在' | { scene }
- PUT    /scenes/:id      → 404 | { message: '保存成功' }
- PUT    /scenes/:id/prompt → 404 | { message: '场景提示词已更新' }
- DELETE /scenes/:id      → 404 | { message: '场景已删除' }
- POST   /props           → 400 'drama_id 和 name 必填' | 201 prop
- GET    /props/:id       → 400 '无效的ID' | 404 '道具不存在' | { prop }
- PUT    /props/:id       → 400 | 404 | prop
- DELETE /props/:id       → 400 | 404 | { message: '删除成功' }
- POST   /storyboards     → 201 sb
- GET    /storyboards/:id → 404 '分镜不存在' | sb
- PUT    /storyboards/:id → 404 | sb
- DELETE /storyboards/:id → 404 | { message: '删除成功' }
- POST   /storyboards/:id/insert-before → 404 '目标分镜不存在' | 201 sb
- POST   /storyboards/:id/props         → { message: '关联成功' }
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _drama(client: TestClient, **extra) -> dict:
    r = client.post("/api/v1/dramas", json={"title": "实体测试剧", **extra})
    assert r.status_code == 201
    return r.json()["data"]


def _char(client: TestClient, drama_id, **extra) -> dict:
    r = client.put(
        f"/api/v1/dramas/{drama_id}/characters", json={"characters": [{"name": "测试角色", **extra}]}
    )
    assert r.status_code == 200, r.text
    return client.get(f"/api/v1/dramas/{drama_id}/characters").json()["data"][0]


# ---------------- characters ----------------


def test_character_get_field_set(client: TestClient):
    d = _drama(client)
    c = _char(client, d["id"], appearance="青衫")
    r = client.get(f"/api/v1/characters/{c['id']}")
    assert r.status_code == 200
    character = r.json()["data"]["character"]
    # Node getOne 硬编码的 SELECT 列
    assert set(character.keys()) == {
        "id",
        "drama_id",
        "name",
        "role",
        "appearance",
        "description",
        "personality",
        "voice_style",
        "image_url",
        "local_path",
        "polished_prompt",
        "four_view_image_url",
        "identity_anchors",
        "seedance2_asset",
        "seedance2_voice_asset",
        "negative_prompt",
        "updated_at",
    }
    assert character["appearance"] == "青衫"
    assert character["seedance2_asset"] is None
    assert character["seedance2_voice_asset"] is None


def test_character_get_not_found(client: TestClient):
    r = client.get("/api/v1/characters/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "角色不存在"


def test_character_update_and_delete(client: TestClient):
    d = _drama(client)
    c = _char(client, d["id"])

    r = client.put(f"/api/v1/characters/{c['id']}", json={"name": "改名", "appearance": "红衣"})
    assert r.json()["data"] == {"message": "保存成功"}
    got = client.get(f"/api/v1/characters/{c['id']}").json()["data"]["character"]
    assert got["name"] == "改名"
    assert got["appearance"] == "红衣"

    # 空 body 也算成功（Node：updates 为空直接 ok）
    assert client.put(f"/api/v1/characters/{c['id']}", json={}).status_code == 200

    assert client.put("/api/v1/characters/999999", json={"name": "x"}).status_code == 404
    assert client.delete("/api/v1/characters/999999").status_code == 404

    rd = client.delete(f"/api/v1/characters/{c['id']}")
    assert rd.json()["data"] == {"message": "删除成功"}
    assert client.get(f"/api/v1/characters/{c['id']}").status_code == 404


# ---------------- scenes ----------------


def test_scene_crud(client: TestClient):
    d = _drama(client)

    r = client.post("/api/v1/scenes", json={"location": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "缺少 drama_id"

    rc = client.post(
        "/api/v1/scenes",
        json={"drama_id": d["id"], "location": "卧室内", "time": "清晨", "prompt": "古风卧室"},
    )
    assert rc.status_code == 201
    scene = rc.json()["data"]
    assert scene["location"] == "卧室内"
    assert scene["status"] == "pending"
    assert "storyboard_count" not in scene  # Node getSceneById 不返回该列（DB 中固定为 1）

    rg = client.get(f"/api/v1/scenes/{scene['id']}")
    assert rg.json()["data"]["scene"]["location"] == "卧室内"
    # getSceneById 的字段集
    assert set(rg.json()["data"]["scene"].keys()) == {
        "id", "drama_id", "location", "time", "prompt", "polished_prompt",
        "polished_prompt_single", "image_url", "local_path", "extra_images",
        "status", "created_at", "updated_at",
    }

    ru = client.put(f"/api/v1/scenes/{scene['id']}", json={"location": "书房"})
    assert ru.json()["data"] == {"message": "保存成功"}
    assert client.get(f"/api/v1/scenes/{scene['id']}").json()["data"]["scene"]["location"] == "书房"

    rp = client.put(f"/api/v1/scenes/{scene['id']}/prompt", json={"prompt": "新提示词"})
    assert rp.json()["data"] == {"message": "场景提示词已更新"}
    assert client.get(f"/api/v1/scenes/{scene['id']}").json()["data"]["scene"]["prompt"] == "新提示词"

    # 不传 prompt 时置为空串（Node: req.prompt ?? ''）
    client.put(f"/api/v1/scenes/{scene['id']}/prompt", json={})
    assert client.get(f"/api/v1/scenes/{scene['id']}").json()["data"]["scene"]["prompt"] == ""

    rd = client.delete(f"/api/v1/scenes/{scene['id']}")
    assert rd.json()["data"] == {"message": "场景已删除"}

    assert client.get("/api/v1/scenes/999999").status_code == 404
    assert client.put("/api/v1/scenes/999999", json={"location": "x"}).status_code == 404
    assert client.put("/api/v1/scenes/999999/prompt", json={"prompt": "x"}).status_code == 404
    assert client.delete("/api/v1/scenes/999999").status_code == 404


# ---------------- props ----------------


def test_prop_crud(client: TestClient):
    d = _drama(client)

    assert client.post("/api/v1/props", json={"name": "无drama"}).status_code == 400
    r0 = client.post("/api/v1/props", json={"drama_id": d["id"]})
    assert r0.status_code == 400
    assert r0.json()["error"]["message"] == "drama_id 和 name 必填"

    rc = client.post(
        "/api/v1/props",
        json={"drama_id": d["id"], "name": "玉佩", "type": "信物", "prompt": "羊脂玉佩"},
    )
    assert rc.status_code == 201
    prop = rc.json()["data"]
    assert prop["name"] == "玉佩"
    assert prop["type"] == "信物"

    rg = client.get(f"/api/v1/props/{prop['id']}")
    assert rg.json()["data"]["prop"]["name"] == "玉佩"
    assert set(rg.json()["data"]["prop"].keys()) == {
        "id", "drama_id", "name", "type", "description", "prompt", "negative_prompt",
        "image_url", "local_path", "extra_images", "ref_image", "created_at", "updated_at",
    }

    ru = client.put(f"/api/v1/props/{prop['id']}", json={"name": "长剑", "description": "兵器"})
    assert ru.json()["data"]["name"] == "长剑"
    assert ru.json()["data"]["description"] == "兵器"

    rd = client.delete(f"/api/v1/props/{prop['id']}")
    assert rd.json()["data"] == {"message": "删除成功"}
    assert client.get(f"/api/v1/props/{prop['id']}").status_code == 404

    # 无效 ID
    assert client.get("/api/v1/props/abc").status_code == 400
    assert client.put("/api/v1/props/abc", json={"name": "x"}).status_code == 400
    assert client.delete("/api/v1/props/abc").status_code == 400
    assert client.get("/api/v1/props/999999").status_code == 404
    assert client.put("/api/v1/props/999999", json={"name": "x"}).status_code == 404
    assert client.delete("/api/v1/props/999999").status_code == 404


# ---------------- storyboards ----------------


def _episode(client: TestClient, drama_id, number=1) -> dict:
    client.put(
        f"/api/v1/dramas/{drama_id}/episodes",
        json={"episodes": [{"episode_number": number, "title": f"第{number}集"}]},
    )
    return client.get(f"/api/v1/dramas/{drama_id}").json()["data"]["episodes"][0]


def test_storyboard_crud(client: TestClient):
    d = _drama(client)
    ep = _episode(client, d["id"])

    rc = client.post(
        "/api/v1/storyboards",
        json={"episode_id": ep["id"], "storyboard_number": 1, "title": "开场", "duration": 5},
    )
    assert rc.status_code == 201
    sb = rc.json()["data"]
    assert sb["storyboard_number"] == 1
    assert sb["status"] == "pending"
    assert sb["characters"] == []
    assert sb["prop_ids"] == []
    assert sb["layout_description"] is None

    rg = client.get(f"/api/v1/storyboards/{sb['id']}")
    assert rg.json()["data"]["title"] == "开场"

    ru = client.put(f"/api/v1/storyboards/{sb['id']}", json={"title": "改后", "duration": 8})
    assert ru.json()["data"]["title"] == "改后"
    assert ru.json()["data"]["duration"] == 8

    rd = client.delete(f"/api/v1/storyboards/{sb['id']}")
    assert rd.json()["data"] == {"message": "删除成功"}

    assert client.get("/api/v1/storyboards/999999").status_code == 404
    assert client.put("/api/v1/storyboards/999999", json={"title": "x"}).status_code == 404
    assert client.delete("/api/v1/storyboards/999999").status_code == 404


def test_storyboard_characters_json_and_prop_links(client: TestClient):
    d = _drama(client)
    ep = _episode(client, d["id"])
    c = _char(client, d["id"])
    p = client.post("/api/v1/props", json={"drama_id": d["id"], "name": "道具A"}).json()["data"]

    sb = client.post("/api/v1/storyboards", json={"episode_id": ep["id"], "storyboard_number": 1}).json()["data"]

    # characters 存为 JSON 字符串；回读时解析（dramaService 侧输出 int 列表）
    ru = client.put(f"/api/v1/storyboards/{sb['id']}", json={"characters": [c["id"]]})
    assert ru.json()["data"]["characters"] == [c["id"]]

    # character_ids 与 characters 等价
    ru2 = client.put(f"/api/v1/storyboards/{sb['id']}", json={"character_ids": [c["id"], c["id"]]})
    assert ru2.json()["data"]["characters"] == [c["id"], c["id"]]

    # 非数组 → '[]'
    ru3 = client.put(f"/api/v1/storyboards/{sb['id']}", json={"characters": "not-json"})
    assert ru3.json()["data"]["characters"] == []

    # 道具关联：全量替换
    ra = client.post(f"/api/v1/storyboards/{sb['id']}/props", json={"prop_ids": [p["id"]]})
    assert ra.json()["data"] == {"message": "关联成功"}
    assert client.get(f"/api/v1/storyboards/{sb['id']}").json()["data"]["prop_ids"] == [p["id"]]

    ra2 = client.post(f"/api/v1/storyboards/{sb['id']}/props", json={"prop_ids": []})
    assert client.get(f"/api/v1/storyboards/{sb['id']}").json()["data"]["prop_ids"] == []

    # 非法 prop_ids 也按空数组处理
    client.post(f"/api/v1/storyboards/{sb['id']}/props", json={"prop_ids": "x"})
    assert client.get(f"/api/v1/storyboards/{sb['id']}").json()["data"]["prop_ids"] == []


def test_storyboard_insert_before(client: TestClient):
    d = _drama(client)
    ep = _episode(client, d["id"])
    sb1 = client.post("/api/v1/storyboards", json={"episode_id": ep["id"], "storyboard_number": 1}).json()["data"]
    sb2 = client.post("/api/v1/storyboards", json={"episode_id": ep["id"], "storyboard_number": 2}).json()["data"]

    r = client.post(f"/api/v1/storyboards/{sb2['id']}/insert-before")
    assert r.status_code == 201
    inserted = r.json()["data"]
    assert inserted["storyboard_number"] == 2  # 占位原 sb2 的编号
    # 原 sb2 后移到 3
    assert client.get(f"/api/v1/storyboards/{sb2['id']}").json()["data"]["storyboard_number"] == 3
    # sb1 不受影响
    assert client.get(f"/api/v1/storyboards/{sb1['id']}").json()["data"]["storyboard_number"] == 1

    assert client.post("/api/v1/storyboards/999999/insert-before").status_code == 404
