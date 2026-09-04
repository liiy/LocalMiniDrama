"""契约安全网：/api/v1/ai-configs/* 与 Node 版 backend-node/src/routes/aiConfig.js 行为等价。

Node 行为基线：
- GET    /ai-configs                    → { success: true, data: [rowToConfig...] }
- POST   /ai-configs                    → 400 缺字段 | 201 rowToConfig（endpoint 按 provider 推断）
- GET    /ai-configs/vendor-lock        → { enabled, config_file }
- PUT    /ai-configs/bulk-update-key    → 400 '批量换Key仅在厂商锁定模式下可用'（未锁定）
- POST   /ai-configs/test               → 400 '缺少 base_url 或 api_key'
- POST   /ai-configs/jimeng2-list-assets→ 400 '请先填写网关 URL 与 Token'
- POST   /ai-configs/model-ark-asset    → 400 MODEL_ARK_ASSET（非法 action）
- GET    /ai-configs/{id}               → 400 '无效的配置ID' | 404 '配置不存在'
- PUT    /ai-configs/{id}               → 404 | 200
- DELETE /ai-configs/{id}               → 404 | { message: '删除成功' }

注意：不覆盖真实网络请求（test / model-ark / jimeng2 仅测校验分支）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import session as dbm
from app.services import aiConfigService as svc

BASE = "/api/v1/ai-configs"

VALID_BODY = {
    "service_type": "text",
    "name": "测试文本配置",
    "provider": "openai",
    "base_url": "https://api.example.com/v1",
    "api_key": "sk-test-key",
}


def _create(client: TestClient, **overrides):
    return client.post(BASE, json={**VALID_BODY, **overrides})


# ---------------- vendor-lock ----------------


def test_get_vendor_lock(client: TestClient):
    r = client.get(f"{BASE}/vendor-lock")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["enabled"] is False
    assert "timestamp" in body


def test_bulk_update_key_requires_lock(client: TestClient):
    r = client.put(f"{BASE}/bulk-update-key", json={"api_key": "sk-new"})
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "BAD_REQUEST", "message": "批量换Key仅在厂商锁定模式下可用"}


# ---------------- create ----------------


def test_create_missing_required_fields(client: TestClient):
    r = client.post(BASE, json={"name": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "缺少必填字段: service_type, name, provider, base_url"


def test_create_missing_api_key(client: TestClient):
    body = {**VALID_BODY}
    body.pop("api_key")
    r = client.post(BASE, json=body)
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "缺少必填字段: api_key"


def test_create_returns_201_and_infers_endpoint(client: TestClient):
    r = _create(client)
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["service_type"] == "text"
    assert data["provider"] == "openai"
    assert data["endpoint"] == "/chat/completions"  # openai + text 自动推断
    assert data["model"] == []  # 未传 model → []
    assert data["is_default"] is False
    assert data["is_active"] is True
    assert data["api_protocol"] == ""
    assert data["api_key"] == svc.MASKED_SECRET_VALUE
    assert data["api_key_masked"] == svc.MASKED_SECRET_VALUE
    assert data["has_api_key"] is True


def test_create_infers_endpoint_by_service_type(client: TestClient):
    r = _create(client, service_type="video", name="视频配置")
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["endpoint"] == "/videos"
    assert data["query_endpoint"] == "/videos/{taskId}"


def test_create_model_string_normalized_to_array(client: TestClient):
    r = _create(client, model="gpt-4o", name="单模型")
    assert r.json()["data"]["model"] == ["gpt-4o"]


def test_create_model_array_preserved(client: TestClient):
    r = _create(client, model=["a", "b"], name="多模型")
    assert r.json()["data"]["model"] == ["a", "b"]


def test_create_default_model_trimmed(client: TestClient):
    r = _create(client, default_model="  gpt-4o  ", name="默认模型")
    assert r.json()["data"]["default_model"] == "gpt-4o"


def test_create_jimeng2_normalizes_bearer_prefix(client: TestClient):
    r = _create(
        client,
        service_type="jimeng2_character_auth",
        name="即梦2",
        provider="custom",
        api_key="Bearer abc123",
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["api_key"] == svc.MASKED_SECRET_VALUE
    assert data["has_api_key"] is True
    with dbm.SessionLocal() as db:
        saved = svc.get_config(db, data["id"])
    assert saved["api_key"] == "abc123"


# ---------------- list / get ----------------


def test_list_configs(client: TestClient):
    _create(client, name="A")
    _create(client, service_type="image", name="B")
    r = client.get(BASE)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


def test_list_configs_filtered_by_service_type(client: TestClient):
    _create(client, name="A")
    _create(client, service_type="image", name="B")
    r = client.get(BASE, params={"service_type": "image"})
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["service_type"] == "image"


def test_get_config_by_id(client: TestClient):
    cid = _create(client).json()["data"]["id"]
    r = client.get(f"{BASE}/{cid}")
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "测试文本配置"


def test_get_config_invalid_id(client: TestClient):
    r = client.get(f"{BASE}/abc")
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "无效的配置ID"


def test_get_config_not_found(client: TestClient):
    r = client.get(f"{BASE}/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "配置不存在"


# ---------------- update ----------------


def test_update_config(client: TestClient):
    cid = _create(client).json()["data"]["id"]
    r = client.put(f"{BASE}/{cid}", json={"name": "改名", "priority": 5})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["name"] == "改名"
    assert data["priority"] == 5


def test_update_config_not_found(client: TestClient):
    r = client.put(f"{BASE}/999999", json={"name": "x"})
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "配置不存在"


def test_update_config_invalid_id(client: TestClient):
    r = client.put(f"{BASE}/abc", json={"name": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "无效的配置ID"


def test_update_empty_body_returns_existing(client: TestClient):
    cid = _create(client).json()["data"]["id"]
    r = client.put(f"{BASE}/{cid}", json={})
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "测试文本配置"


def test_update_model_to_db_array(client: TestClient):
    cid = _create(client).json()["data"]["id"]
    r = client.put(f"{BASE}/{cid}", json={"model": ["m1", "m2"]})
    assert r.json()["data"]["model"] == ["m1", "m2"]


# ---------------- delete ----------------


def test_delete_config(client: TestClient):
    cid = _create(client).json()["data"]["id"]
    r = client.delete(f"{BASE}/{cid}")
    assert r.status_code == 200
    assert r.json()["data"] == {"message": "删除成功"}
    # 软删后列表里不再出现
    assert client.get(BASE).json()["data"] == []
    assert client.get(f"{BASE}/{cid}").status_code == 404


def test_delete_config_not_found(client: TestClient):
    r = client.delete(f"{BASE}/999999")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "配置不存在"


def test_delete_config_invalid_id(client: TestClient):
    r = client.delete(f"{BASE}/abc")
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "无效的配置ID"


# ---------------- 代理端点（仅校验分支，不发真实请求）----------------


def test_test_connection_missing_params(client: TestClient):
    r = client.post(f"{BASE}/test", json={"base_url": "https://x.com"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "缺少 base_url 或 api_key"


def test_jimeng2_list_assets_missing_credentials(client: TestClient):
    r = client.post(f"{BASE}/jimeng2-list-assets", json={})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "请先填写网关 URL 与 Token"


def test_model_ark_asset_missing_action(client: TestClient):
    r = client.post(f"{BASE}/model-ark-asset", json={"base_url": "https://ark.cn-beijing.volces.com"})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "MODEL_ARK_ASSET"
    assert body["error"]["message"] == "缺少 action"


def test_model_ark_asset_unsupported_action(client: TestClient):
    r = client.post(
        f"{BASE}/model-ark-asset",
        json={"base_url": "https://ark.cn-beijing.volces.com", "action": "Nope"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "MODEL_ARK_ASSET"
    assert body["error"]["message"] == "不支持的 action: Nope"


def test_model_ark_asset_missing_base_url(client: TestClient):
    r = client.post(f"{BASE}/model-ark-asset", json={"action": "ListAssets"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "缺少 base_url"


def test_model_ark_asset_bad_scheme(client: TestClient):
    r = client.post(f"{BASE}/model-ark-asset", json={"base_url": "ftp://x.com", "action": "ListAssets"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "base_url 须以 http:// 或 https:// 开头"


def test_model_ark_asset_volc_sign_missing_keys(client: TestClient):
    r = client.post(
        f"{BASE}/model-ark-asset",
        json={
            "base_url": "https://ark.cn-beijing.volces.com",
            "action": "ListAssets",
            "auth_mode": "volc_sign",
        },
    )
    assert r.status_code == 400
    assert (
        r.json()["error"]["message"]
        == "控制面 OpenAPI 须填写 Access Key ID 与 Secret Access Key（控制台 IAM 密钥，非推理 API Key）"
    )
