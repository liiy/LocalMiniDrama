"""测试 videoClient 的 Veo3 建任务与参考图解析。

网络调用全部打桩（monkeypatch uploadService 的图床 + 注入 post_json）。
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.logger import get_logger  # noqa: E402
from app.services import uploadService  # noqa: E402
from app.services import videoClient as vc  # noqa: E402

log = get_logger("lmd.test")


# ---------------------------------------------------------------- 参考图解析


def test_resolve_veo3_image_empty():
    assert vc.resolve_veo3_image("", None, log) is None
    assert vc.resolve_veo3_image(None, None, log) is None


def test_resolve_veo3_image_proxy_host_passes_through():
    u = "https://imageproxy.zhongzhuan.chat/api/proxy/image/abc"
    out = vc.resolve_veo3_image(u, None, log)
    assert out == {"kind": "url", "value": u}


def test_resolve_veo3_image_data_url_uses_proxy(monkeypatch):
    monkeypatch.setattr(
        uploadService, "upload_to_image_proxy",
        lambda buf, mime, l, tag, cfg=None: "https://proxy/img/x",
    )
    b64 = base64.b64encode(b"pngbytes").decode()
    out = vc.resolve_veo3_image(f"data:image/png;base64,{b64}", None, log)
    assert out == {"kind": "url", "value": "https://proxy/img/x"}


def test_resolve_veo3_image_data_url_fallback_to_inline(monkeypatch):
    monkeypatch.setattr(uploadService, "upload_to_image_proxy", lambda *a, **k: None)
    b64 = base64.b64encode(b"pngbytes").decode()
    out = vc.resolve_veo3_image(f"data:image/png;base64,{b64}", None, log)
    assert out == {"kind": "data", "value": f"data:image/png;base64,{b64}"}


def test_resolve_veo3_image_local_static_file_uploads(tmp_path, monkeypatch):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "f.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    monkeypatch.setattr(
        uploadService, "upload_to_image_proxy",
        lambda buf, mime, l, tag, cfg=None: "https://proxy/img/local",
    )
    out = vc.resolve_veo3_image(
        "http://localhost:5679/static/images/f.png", str(tmp_path), log
    )
    assert out == {"kind": "url", "value": "https://proxy/img/local"}


def test_resolve_veo3_image_local_fallback_to_base64(tmp_path, monkeypatch):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "g.png").write_bytes(b"\x89PNG\r\n\x1a\ny")
    monkeypatch.setattr(uploadService, "upload_to_image_proxy", lambda *a, **k: None)
    out = vc.resolve_veo3_image(
        "http://localhost:5679/static/images/g.png", str(tmp_path), log
    )
    assert out["kind"] == "data"
    assert out["value"].startswith("data:image/png;base64,")


def test_resolve_veo3_image_remote_fetch_success(monkeypatch):
    monkeypatch.setattr(
        uploadService, "upload_to_image_proxy",
        lambda buf, mime, l, tag, cfg=None: "https://proxy/img/remote",
    )
    monkeypatch.setattr(vc, "_fetch_bytes", lambda u, h=None: (200, b"jpegdata", "image/jpeg"))
    out = vc.resolve_veo3_image("https://cdn.example/a.jpg", None, log)
    assert out == {"kind": "url", "value": "https://proxy/img/remote"}


def test_resolve_veo3_image_remote_fetch_failure_returns_raw_url(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_bytes", lambda u, h=None: (404, b"", ""))
    out = vc.resolve_veo3_image("https://cdn.example/missing.jpg", None, log)
    assert out == {"kind": "url", "value": "https://cdn.example/missing.jpg"}


def test_resolve_veo3_image_relative_url_returns_raw(monkeypatch):
    out = vc.resolve_veo3_image("images/x.png", None, log)
    assert out == {"kind": "url", "value": "images/x.png"}


def test_resolve_veo3_image_path_traversal_blocked(tmp_path, monkeypatch):
    """越界路径（../）不得被读取成 base64。"""
    called = []
    monkeypatch.setattr(uploadService, "upload_to_image_proxy",
                        lambda *a, **k: called.append(1) or None)
    out = vc.resolve_veo3_image(
        "http://localhost:5679/static/../../etc/passwd", str(tmp_path), log
    )
    assert out == {"kind": "url", "value": "http://localhost:5679/static/../../etc/passwd"}
    assert called == []


# ---------------------------------------------------------------- 建任务


def _cfg(**kw):
    c = {
        "provider": "openai",
        "api_protocol": "veo3",
        "base_url": "https://veo.example.com",
        "api_key": "KEY",
        "model": ["veo-3"],
        "default_model": "veo-3",
        "is_active": True,
        "is_default": True,
    }
    c.update(kw)
    return c


def test_veo3_text_only_body():
    captured = {}

    def post(url, headers, body):
        captured.update(url=url, headers=headers, body=body)
        return 200, json.dumps({"task_id": "veo-task-1", "status": "pending"})

    out = vc.call_veo3_video_api(_cfg(), log, {"prompt": "一只猫", "model": "veo-3",
                                               "video_gen_id": 7}, post_json=post)
    assert out == {"task_id": "veo-task-1", "status": "pending"}
    assert captured["url"] == "https://veo.example.com/v1/video/create"
    assert captured["headers"]["Authorization"] == "Bearer KEY"
    assert captured["body"] == {"model": "veo-3", "prompt": "一只猫", "enhance_prompt": True}


def test_veo3_custom_endpoint():
    captured = {}

    def post(url, headers, body):
        captured["url"] = url
        return 200, json.dumps({"id": "t"})

    vc.call_veo3_video_api(_cfg(endpoint="video/create"), log, {"prompt": "p"}, post_json=post)
    assert captured["url"] == "https://veo.example.com/video/create"


def test_veo3_with_image(monkeypatch):
    monkeypatch.setattr(uploadService, "upload_to_image_proxy",
                        lambda *a, **k: "https://proxy/img/v")
    monkeypatch.setattr(vc, "_fetch_bytes", lambda u, h=None: (200, b"jpegdata", "image/jpeg"))
    captured = {}

    def post(url, headers, body):
        captured["body"] = body
        return 200, json.dumps({"id": "t"})

    vc.call_veo3_video_api(_cfg(), log,
                           {"prompt": "p", "image_url": "https://cdn/a.jpg"}, post_json=post)
    assert captured["body"]["images"] == ["https://proxy/img/v"]


def test_veo3_image_unreachable_falls_back_to_raw_url(monkeypatch):
    """图床与拉取都失败时，仍按原 URL 提交（与 Node 一致）。"""
    monkeypatch.setattr(vc, "_fetch_bytes", lambda u, h=None: (_ for _ in ()).throw(OSError("unreachable")))
    captured = {}

    def post(url, headers, body):
        captured["body"] = body
        return 200, json.dumps({"id": "t"})

    vc.call_veo3_video_api(_cfg(), log,
                           {"prompt": "p", "image_url": "https://cdn/a.jpg"}, post_json=post)
    assert captured["body"]["images"] == ["https://cdn/a.jpg"]


def test_veo3_direct_video_url():
    def post(u, h, b):
        return 200, json.dumps({"video_url": "https://cdn/direct.mp4"})

    out = vc.call_veo3_video_api(_cfg(), log, {"prompt": "p"}, post_json=post)
    assert out == {"video_url": "https://cdn/direct.mp4"}


def test_veo3_task_id_fallback_chain():
    def post(u, h, b):
        return 200, json.dumps({"request_id": "req-9", "status": "queued"})

    out = vc.call_veo3_video_api(_cfg(), log, {"prompt": "p"}, post_json=post)
    assert out == {"task_id": "req-9", "status": "queued"}


def test_veo3_nested_data_task_id():
    def post(u, h, b):
        return 200, json.dumps({"data": {"task_id": "nested-1"}})

    out = vc.call_veo3_video_api(_cfg(), log, {"prompt": "p"}, post_json=post)
    assert out["task_id"] == "nested-1"


def test_veo3_no_task_id_returns_error():
    def post(u, h, b):
        return 200, json.dumps({"foo": 1})

    out = vc.call_veo3_video_api(_cfg(), log, {"prompt": "p"}, post_json=post)
    assert "error" in out and "Veo3 no task_id or video_url" in out["error"]


def test_veo3_http_error():
    def post(u, h, b):
        return 400, json.dumps({"error": {"message": "bad prompt"}})

    out = vc.call_veo3_video_api(_cfg(), log, {"prompt": "p"}, post_json=post)
    assert out == {"error": "Veo3 request failed: 400 - bad prompt"}


def test_veo3_bad_json_response():
    def post(u, h, b):
        return 200, "<html>"

    out = vc.call_veo3_video_api(_cfg(), log, {"prompt": "p"}, post_json=post)
    assert "error" in out and "Veo3 bad response" in out["error"]


# ---------------------------------------------------------------- 调度器接入


class _FakeDB:
    def __init__(self, configs):
        self._configs = configs
        self._orig = vc.aiConfigService.list_configs
        vc.aiConfigService.list_configs = lambda db, st: self._configs

    def __enter__(self):
        return self

    def __exit__(self, *a):
        vc.aiConfigService.list_configs = self._orig


def test_dispatcher_routes_veo3():
    captured = {}

    def post(url, headers, body):
        captured["body"] = body
        return 200, json.dumps({"task_id": "dispatched"})

    with _FakeDB([_cfg()]):
        out = vc.call_video_api(object(), log, {"prompt": "p", "model": "veo-3"}, post_json=post)
    assert out == {"task_id": "dispatched", "status": "processing"}
    assert captured["body"]["enhance_prompt"] is True


def test_dispatcher_all_vendor_protocols_dispatched():
    """确认所有列入厂商分发字典的协议均已被实现和调度，不再抛出 NotImplementedError。"""
    for protocol in sorted(vc._VENDOR_VIDEO_DISPATCH):
        with _FakeDB([_cfg(api_protocol=protocol, base_url="https://example.com", api_key="test-key")]):
            def post(url, headers, body):
                return 200, json.dumps({
                    "task_id": "t1",
                    "id": "t1",
                    "data": {"task_id": "t1", "video": {"url": "https://v.mp4"}, "id": "t1"},
                    "choices": [{"message": {"content": "ok"}}],
                })

            out = vc.call_video_api(object(), log, {"prompt": "p", "model": "test-model"}, post_json=post)
            assert out is not None
