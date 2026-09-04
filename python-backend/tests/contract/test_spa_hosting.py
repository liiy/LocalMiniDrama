from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app, resolve_web_dist_path


def test_no_dist_fallback_html():
    """未构建前端时，GET / 返回与 Node 一致的友好引导 HTML 页面。"""
    # 显式传入不存在的临时目录
    with tempfile.TemporaryDirectory() as tmp_empty:
        non_existent = Path(tmp_empty) / "not_exist_dist"
        app = create_app(web_dist=non_existent)
        client = TestClient(app)

        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "<h1>LocalMiniDrama API</h1>" in res.text
        assert "cd web &amp;&amp; pnpm install &amp;&amp; pnpm build" in res.text
        assert '<a href="/health">/health</a>' in res.text

        # 非 API 404 页面返回文本 Not Found（与 Node app.use res.status(404).send('Not Found') 对齐）
        res_404 = client.get("/random-page")
        assert res_404.status_code == 404
        assert res_404.text == "Not Found"

        # API 404 仍返回标准 JSON
        res_api = client.get("/api/v1/nonexistent-route")
        assert res_api.status_code == 404
        data = res_api.json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "timestamp" in data


def test_dist_spa_hosting_and_fallback():
    """存在前端 dist 目录时：托管 /assets、favicon.ico、根静态文件，并支持 SPA 路由回退。"""
    with tempfile.TemporaryDirectory() as tmp_dist:
        dist_path = Path(tmp_dist)
        assets_dir = dist_path / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # 写入模拟的前端文件
        index_content = "<!DOCTYPE html><html><head><title>Vue App</title></head><body><div id='app'></div></body></html>"
        (dist_path / "index.html").write_text(index_content, encoding="utf-8")
        (dist_path / "favicon.ico").write_bytes(b"\x00\x00\x01\x00fake-ico")
        (dist_path / "wx.jpg").write_bytes(b"\xff\xd8\xfffake-jpg")
        (assets_dir / "app.js").write_text("console.log('spa bundle');", encoding="utf-8")
        (assets_dir / "style.css").write_text("body { margin: 0; }", encoding="utf-8")

        app = create_app(web_dist=dist_path)
        client = TestClient(app)

        # 1. 首页 GET / -> index.html
        res_root = client.get("/")
        assert res_root.status_code == 200
        assert "<div id='app'></div>" in res_root.text

        # 2. SPA 路由回退：如 /episodes/123 或 /drama/editor
        res_spa1 = client.get("/episodes/123")
        assert res_spa1.status_code == 200
        assert "<div id='app'></div>" in res_spa1.text

        res_spa2 = client.get("/drama/detail/99/storyboards")
        assert res_spa2.status_code == 200
        assert "<div id='app'></div>" in res_spa2.text

        # 3. 静态资源 /assets
        res_js = client.get("/assets/app.js")
        assert res_js.status_code == 200
        assert "spa bundle" in res_js.text

        res_css = client.get("/assets/style.css")
        assert res_css.status_code == 200
        assert "margin: 0" in res_css.text

        # 4. dist 根目录静态文件
        res_wx = client.get("/wx.jpg")
        assert res_wx.status_code == 200
        assert res_wx.content == b"\xff\xd8\xfffake-jpg"

        # 5. favicon.ico
        res_fav = client.get("/favicon.ico")
        assert res_fav.status_code == 200
        assert res_fav.content == b"\x00\x00\x01\x00fake-ico"

        # 6. /health 正常响应
        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json()["status"] == "ok"

        # 7. API 请求绝不被 SPA 拦截，404 返回 JSON 格式
        res_api_v1 = client.get("/api/v1/not-found-endpoint")
        assert res_api_v1.status_code == 404
        assert res_api_v1.json()["success"] is False
        assert res_api_v1.json()["error"]["code"] == "NOT_FOUND"

        res_api_raw = client.get("/api/unknown")
        assert res_api_raw.status_code == 404
        assert res_api_raw.json()["success"] is False
        assert res_api_raw.json()["error"]["code"] == "NOT_FOUND"


def test_resolve_web_dist_env_var(monkeypatch):
    """验证 WEB_DIST_PATH 环境变量配置。"""
    with tempfile.TemporaryDirectory() as tmp_dist:
        monkeypatch.setenv("WEB_DIST_PATH", tmp_dist)
        resolved = resolve_web_dist_path()
        assert resolved == Path(tmp_dist).resolve()


def test_favicon_not_found():
    """当 dist 存在但没有 favicon.ico 时返回 404。"""
    with tempfile.TemporaryDirectory() as tmp_dist:
        dist_path = Path(tmp_dist)
        (dist_path / "index.html").write_text("<html></html>", encoding="utf-8")
        app = create_app(web_dist=dist_path)
        client = TestClient(app)

        res = client.get("/favicon.ico")
        assert res.status_code == 404
