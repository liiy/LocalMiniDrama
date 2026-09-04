"""契约测试：小说/长文章节导入服务。

对照 backend-node:
- POST /api/v1/dramas/import-novel
  - 支持 multipart/form-data 文件上传 (file) 或文本内容 (text)
  - 支持 application/json 参数 (text, title, max_chapters, ai_summarize)
  - 缺少 text 或空文件返回 400 ("请上传小说文本文件或提供 text 参数")
  - 基于正则识别章节标题（第X章、第X节、Chapter X、1. 标题、等）
  - 支持 ai_summarize AI 摘要为剧本格式
"""
from __future__ import annotations

import io
from fastapi.testclient import TestClient


SAMPLE_NOVEL = """
第1章 初入江湖
天地玄黄，宇宙洪荒。这是一段用于测试小说章节拆分的内容，长度必须超过二十个字才能被规则识别为有效章节。

第2章 风起云涌
日月盈昃，辰宿列张。这是第二章的正文内容，用于验证小说章节解析器能够正确拆分多章节，并且索引递增。

第3章 剑指苍穹
寒来暑往，秋收冬藏。这是第三章的正文内容，包含更多的江湖恩怨和剧本描述。
"""


def test_import_novel_missing_text(client: TestClient):
    # 1. 没有任何参数
    r = client.post("/api/v1/dramas/import-novel")
    assert r.status_code == 400
    assert "请上传小说文本文件或提供 text 参数" in r.text

    # 2. 空文本
    r = client.post("/api/v1/dramas/import-novel", json={"text": "   "})
    assert r.status_code == 400
    assert "请上传小说文本文件或提供 text 参数" in r.text


def test_import_novel_with_json_and_rule_detection(client: TestClient):
    r = client.post(
        "/api/v1/dramas/import-novel",
        json={
            "text": SAMPLE_NOVEL,
            "title": "测试小说",
            "max_chapters": 10,
            "ai_summarize": False,
        },
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    chapters = data["chapters"]
    assert len(chapters) == 3
    assert chapters[0]["index"] == 1
    assert chapters[0]["title"] == "第1章 初入江湖"
    assert "天地玄黄" in chapters[0]["content"]
    assert chapters[0]["script"] == chapters[0]["content"]

    assert chapters[1]["index"] == 2
    assert chapters[1]["title"] == "第2章 风起云涌"

    assert chapters[2]["index"] == 3
    assert chapters[2]["title"] == "第3章 剑指苍穹"


def test_import_novel_with_file_upload(client: TestClient):
    file_bytes = SAMPLE_NOVEL.encode("utf-8")
    r = client.post(
        "/api/v1/dramas/import-novel",
        files={"file": ("novel.txt", io.BytesIO(file_bytes), "text/plain")},
        data={"title": "文件导入小说", "max_chapters": "2"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    assert len(data["chapters"]) == 2  # max_chapters 截断
    assert data["chapters"][0]["title"] == "第1章 初入江湖"


def test_import_novel_fallback_single_chapter(client: TestClient):
    # 1. 超过20字但无章节标记的普通文本，Node 原版规则识别为「序章」
    plain_text = "这是一段没有任何标准章节标题的普通文本内容，用来测试小说章节的分割规则，总字数超过二十字。"
    r = client.post(
        "/api/v1/dramas/import-novel",
        json={"text": plain_text, "title": "默认单集"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["chapters"][0]["title"] == "序章"
    assert data["chapters"][0]["content"] == plain_text

    # 2. 小于等于20字未被规则检测到，回退到 title 或「第一集」
    short_text = "短文本无章节"
    r2 = client.post(
        "/api/v1/dramas/import-novel",
        json={"text": short_text, "title": "自定义短剧标题"},
    )
    assert r2.status_code == 200
    data2 = r2.json()["data"]
    assert data2["total"] == 1
    assert data2["chapters"][0]["title"] == "自定义短剧标题"
    assert data2["chapters"][0]["content"] == short_text


def test_import_novel_ai_summarize(client: TestClient, monkeypatch):
    import app.services.aiClient as ai_client

    called = []

    def mock_generate_text(db, log, service_type, user_prompt, system_prompt, options=None):
        called.append(user_prompt)
        return "【剧本】场景：客栈。李逍遥推门而入。"

    monkeypatch.setattr(ai_client, "generate_text", mock_generate_text)

    r = client.post(
        "/api/v1/dramas/import-novel",
        json={
            "text": SAMPLE_NOVEL,
            "title": "仙剑奇侠传",
            "max_chapters": 1,
            "ai_summarize": True,
        },
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(called) == 1
    assert "仙剑奇侠传" in called[0]
    assert data["chapters"][0]["script"] == "【剧本】场景：客栈。李逍遥推门而入。"
