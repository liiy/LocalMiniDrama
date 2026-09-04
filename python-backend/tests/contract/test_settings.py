"""契约安全网：/api/v1/settings/* 与 Node 版 backend-node/src/routes/settings.js 行为等价。

Node 行为基线：
- GET  /settings/language   → { success: true, data: { language } }
- PUT  /settings/language   → 400 '语言参数错误，只支持 zh 或 en' | 200 { message, language }
- GET  /settings/generation → { concurrency, video_concurrency, video_generation_timeout_minutes }
- PUT  /settings/generation → Number() 语义校验 1-20，返回保存后值
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_language_default(client: TestClient):
    # 先确保语言为 zh（避免测试间污染）
    client.put("/api/v1/settings/language", json={"language": "zh"})
    r = client.get("/api/v1/settings/language")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"] == {"language": "zh"}
    assert "timestamp" in body
    assert body["timestamp"].endswith("Z")


def test_put_language_invalid(client: TestClient):
    r = client.put("/api/v1/settings/language", json={"language": "fr"})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error"] == {"code": "BAD_REQUEST", "message": "语言参数错误，只支持 zh 或 en"}
    assert "timestamp" in body


def test_put_language_en(client: TestClient):
    r = client.put("/api/v1/settings/language", json={"language": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == {"message": "Language switched to English", "language": "en"}
    # 写回配置文件后 GET 应读到 en
    r2 = client.get("/api/v1/settings/language")
    assert r2.json()["data"]["language"] == "en"


def test_put_language_zh(client: TestClient):
    r = client.put("/api/v1/settings/language", json={"language": "zh"})
    assert r.status_code == 200
    assert r.json()["data"] == {"message": "语言已切换为中文", "language": "zh"}


def test_get_generation_defaults(client: TestClient):
    r = client.get("/api/v1/settings/generation")
    assert r.status_code == 200
    assert r.json()["data"] == {
        "concurrency": 3,
        "video_concurrency": 3,
        "video_generation_timeout_minutes": 30,
    }


def test_put_generation_invalid(client: TestClient):
    r = client.put("/api/v1/settings/generation", json={"concurrency": 0})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "图片并发数需为 1-20 之间的整数"

    r2 = client.put("/api/v1/settings/generation", json={"video_concurrency": 99})
    assert r2.status_code == 400
    assert r2.json()["error"]["message"] == "视频并发数需为 1-20 之间的整数"

    # 字符串数字可通过（JS Number("5") = 5）
    r3 = client.put("/api/v1/settings/generation", json={"concurrency": "5"})
    assert r3.status_code == 200
    assert r3.json()["data"]["concurrency"] == 5


def test_put_generation_valid_persists(client: TestClient):
    r = client.put(
        "/api/v1/settings/generation",
        json={"concurrency": 5, "video_concurrency": 2},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["concurrency"] == 5
    assert data["video_concurrency"] == 2
    # 持久化回读
    r2 = client.get("/api/v1/settings/generation")
    data2 = r2.json()["data"]
    assert data2["concurrency"] == 5
    assert data2["video_concurrency"] == 2


def test_put_generation_partial(client: TestClient):
    r = client.put("/api/v1/settings/generation", json={"concurrency": 7})
    data = r.json()["data"]
    assert data["concurrency"] == 7
    assert data["video_concurrency"] == 3  # 未传保持默认


def test_error_format_not_found(client: TestClient):
    r = client.get("/api/v1/nonexistent-route")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert "timestamp" in body


def test_timestamp_format(client: TestClient):
    """timestamp 与 JS toISOString 一致（毫秒 + Z）。"""
    r = client.get("/api/v1/settings/language")
    ts = r.json()["timestamp"]
    import re

    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", ts)
