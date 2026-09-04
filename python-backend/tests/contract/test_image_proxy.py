"""测试 uploadService 的中转图床与本地落盘。

图床走注入的 httpx monkeypatch，不做真实网络请求。
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.logger import get_logger  # noqa: E402
from app.services import uploadService as us  # noqa: E402

log = get_logger("lmd.test")


# ---------------------------------------------------------------- 配置解析


def test_default_proxy_settings():
    s = us.get_image_proxy_upload_settings({})
    assert s["uploadUrl"] == "https://imageproxy.zhongzhuan.chat/api/upload"
    assert s["timeoutMs"] == 45000
    assert s["maxAttempts"] == 2


def test_proxy_settings_from_config():
    cfg = {"image_proxy": {
        "upload_url": "https://proxy.example/api/upload",
        "upload_timeout_seconds": 10,
        "upload_max_attempts": 3,
    }}
    s = us.get_image_proxy_upload_settings(cfg)
    assert s["uploadUrl"] == "https://proxy.example/api/upload"
    assert s["timeoutMs"] == 10000
    assert s["maxAttempts"] == 3


def test_proxy_settings_clamped():
    # 超时下限 5s，重试次数 1..5
    s = us.get_image_proxy_upload_settings({"image_proxy": {"upload_timeout_seconds": 0, "upload_max_attempts": 99}})
    assert s["timeoutMs"] == 5000
    assert s["maxAttempts"] == 5


def test_proxy_settings_invalid_values_fall_back():
    s = us.get_image_proxy_upload_settings({"image_proxy": {"upload_timeout_seconds": "abc", "upload_max_attempts": "x"}})
    assert s["timeoutMs"] == 45000
    assert s["maxAttempts"] == 2


# ---------------------------------------------------------------- 上传


def _patch_post(monkeypatch, handler):
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return handler(len(calls))

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_upload_success(monkeypatch):
    def handler(n):
        return httpx.Response(200, text=json.dumps({"url": "https://proxy/img/abc"}))

    calls = _patch_post(monkeypatch, handler)
    out = us.upload_to_image_proxy(b"fake-bytes", "image/png", log, "tag1", {})
    assert out == "https://proxy/img/abc"
    url, kw = calls[0]
    assert url == "https://imageproxy.zhongzhuan.chat/api/upload"
    files = kw["files"]["file"]
    assert files[0].endswith(".png")
    assert files[1] == b"fake-bytes"
    assert files[2] == "image/png"


def test_upload_retries_then_succeeds(monkeypatch):
    def handler(n):
        if n == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, text=json.dumps({"url": "https://proxy/img/ok"}))

    calls = _patch_post(monkeypatch, handler)
    out = us.upload_to_image_proxy(b"x", "image/jpeg", log, "tag", {})
    assert out == "https://proxy/img/ok"
    assert len(calls) == 2


def test_upload_exhausts_attempts_returns_none(monkeypatch):
    cfg = {"image_proxy": {"upload_max_attempts": 3}}

    def handler(n):
        return httpx.Response(503, text="down")

    calls = _patch_post(monkeypatch, handler)
    assert us.upload_to_image_proxy(b"x", "image/jpeg", log, "tag", cfg) is None
    assert len(calls) == 3


def test_upload_response_without_url_returns_none(monkeypatch):
    def handler(n):
        return httpx.Response(200, text=json.dumps({"ok": True}))

    _patch_post(monkeypatch, handler)
    assert us.upload_to_image_proxy(b"x", "image/jpeg", log, "tag", {}) is None


def test_upload_non_json_response_returns_none(monkeypatch):
    def handler(n):
        return httpx.Response(200, text="<html>ok</html>")

    _patch_post(monkeypatch, handler)
    assert us.upload_to_image_proxy(b"x", "image/jpeg", log, "tag", {}) is None


def test_upload_timeout_is_reported(monkeypatch):
    def handler(n):
        raise httpx.TimeoutException("timed out")

    cfg = {"image_proxy": {"upload_max_attempts": 1}}
    _patch_post(monkeypatch, handler)
    assert us.upload_to_image_proxy(b"x", "image/jpeg", log, "tag", cfg) is None


def test_upload_mime_fallback_extension():
    """未知 MIME → jpg。"""
    assert us._PROXY_EXT_BY_MIME.get("application/octet-stream", "jpg") == "jpg"


# ---------------------------------------------------------------- 本地上传


def test_upload_local_relative_path(tmp_path, monkeypatch):
    (tmp_path / "images").mkdir()
    f = tmp_path / "images" / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\ndata")

    def handler(n):
        return httpx.Response(200, text=json.dumps({"url": "https://proxy/img/local"}))

    _patch_post(monkeypatch, handler)
    out = us.upload_local_image_to_proxy(str(tmp_path), "images/a.png", log, "t", {})
    assert out == "https://proxy/img/local"


def test_upload_local_absolute_path(tmp_path, monkeypatch):
    f = tmp_path / "b.jpg"
    f.write_bytes(b"jpegbytes")

    def handler(n):
        return httpx.Response(200, text=json.dumps({"url": "https://proxy/img/abs"}))

    _patch_post(monkeypatch, handler)
    assert us.upload_local_image_to_proxy(str(tmp_path), str(f), log, "t", {}) == "https://proxy/img/abs"


def test_upload_local_localhost_url(tmp_path, monkeypatch):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "c.png").write_bytes(b"\x89PNG\r\n\x1a\nx")

    def handler(n):
        return httpx.Response(200, text=json.dumps({"url": "https://proxy/img/url"}))

    _patch_post(monkeypatch, handler)
    out = us.upload_local_image_to_proxy(
        str(tmp_path), "http://localhost:5679/static/images/c.png", log, "t", {}
    )
    assert out == "https://proxy/img/url"


def test_upload_local_missing_file_returns_none(tmp_path, monkeypatch):
    def handler(n):
        raise AssertionError("不应发起请求")

    _patch_post(monkeypatch, handler)
    assert us.upload_local_image_to_proxy(str(tmp_path), "images/nope.png", log, "t", {}) is None


def test_upload_local_empty_input_returns_none(tmp_path, monkeypatch):
    def handler(n):
        raise AssertionError("不应发起请求")

    _patch_post(monkeypatch, handler)
    assert us.upload_local_image_to_proxy(str(tmp_path), "", log, "t", {}) is None
    assert us.upload_local_image_to_proxy(str(tmp_path), None, log, "t", {}) is None


# ---------------------------------------------------------------- 落盘


def test_download_image_to_local_data_url(tmp_path):
    b64 = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()
    out = us.download_image_to_local(
        tmp_path, f"data:image/png;base64,{b64}", "images", log, "ig"
    )
    assert out is not None and out.startswith("images/")
    assert (tmp_path / out).read_bytes() == b"\x89PNG\r\n\x1a\npayload"


def test_download_image_to_local_empty_url(tmp_path):
    assert us.download_image_to_local(tmp_path, "", "images", log, "ig") is None


def test_download_image_to_local_bad_data_url(tmp_path):
    assert us.download_image_to_local(tmp_path, "data:notbase64", "images", log, "ig") is None


def test_download_image_to_local_network_failure_returns_none(tmp_path):
    # 不可达地址 → 失败返回 None（不抛异常）
    assert us.download_image_to_local(
        tmp_path, "http://127.0.0.1:1/none.png", "images", log, "ig"
    ) is None
