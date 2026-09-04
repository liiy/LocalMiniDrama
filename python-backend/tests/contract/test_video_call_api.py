"""测试 videoClient.call_video_api 的请求体构造与响应解析。

通过注入 post_json 打桩，校验：
- 通用兜底（volcengine / openai）的请求体字段、首尾帧顺序与 role、时长归一、草稿模式
- task_id / video_url / error 三种返回的解析
- 未移植的厂商协议抛 NotImplementedError
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.logger import get_logger  # noqa: E402
from app.services import videoClient as vc  # noqa: E402

log = get_logger("lmd.test")


class _FakeDB:
    """get_default_video_config 只需要 list_configs 与 is_active 字段。"""

    def __init__(self, configs):
        self._configs = configs
        import app.services.videoClient as m

        self._orig = m.aiConfigService.list_configs
        m.aiConfigService.list_configs = lambda db, st: self._configs

    def __enter__(self):
        return self

    def __exit__(self, *a):
        import app.services.videoClient as m

        m.aiConfigService.list_configs = self._orig


def _cfg(provider="openai", **kw):
    c = {
        "id": 1,
        "provider": provider,
        "base_url": "https://api.example.com/v1",
        "api_key": "KEY",
        "model": ["model-a"],
        "default_model": "model-a",
        "is_active": True,
        "is_default": True,
        "endpoint": "/video/generations",
    }
    c.update(kw)
    return c


def _call(cfg, opts, response, monkeypatch=None):
    captured = {}

    def post(url, headers, body):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return response

    with _FakeDB([cfg]):
        out = vc.call_video_api(object(), log, opts, post_json=post)
    return out, captured


# ---------------------------------------------------------------- 通用兜底


def test_generic_t2v_body():
    out, cap = _call(_cfg(), {"prompt": "一只猫", "duration": 5, "video_gen_id": 1},
                     (200, json.dumps({"id": "task-1", "status": "queued"})))
    assert out == {"task_id": "task-1", "status": "queued"}
    assert cap["url"] == "https://api.example.com/v1/video/generations"
    assert cap["headers"]["Authorization"] == "Bearer KEY"
    body = cap["body"]
    assert body["model"] == "model-a"
    assert body["content"] == [{"type": "text", "text": "一只猫"}]
    assert body["ratio"] == "16:9" and body["aspect_ratio"] == "16:9"
    assert body["duration"] == 5
    assert body["watermark"] is False
    assert "task_type" not in body


def test_generic_returns_video_url_directly():
    out, _ = _call(_cfg(), {"prompt": "p"},
                   (200, json.dumps({"video_url": "https://cdn/a.mp4"})))
    assert out == {"video_url": "https://cdn/a.mp4"}


def test_generic_no_task_id_returns_error():
    out, _ = _call(_cfg(), {"prompt": "p"}, (200, json.dumps({"foo": 1})))
    assert "error" in out and "未返回 task_id 或 video_url" in out["error"]


def test_generic_http_error_message():
    out, _ = _call(_cfg(), {"prompt": "p"},
                   (400, json.dumps({"error": {"message": "prompt 违规"}})))
    assert out == {"error": "视频生成失败: 400 - prompt 违规"}


def test_generic_non_json_error_appends_raw():
    out, _ = _call(_cfg(), {"prompt": "p"}, (500, "upstream boom"))
    assert out == {"error": "视频生成失败: 500 - upstream boom"}


def test_generic_invalid_json_response():
    out, _ = _call(_cfg(), {"prompt": "p"}, (200, "<html>"))
    assert "error" in out and "视频生成响应解析失败" in out["error"]


def test_generic_optional_fields():
    out, cap = _call(_cfg(), {"prompt": "p", "resolution": "1080p", "seed": 42,
                              "camera_fixed": True, "watermark": True},
                     (200, json.dumps({"id": "t"})))
    body = cap["body"]
    assert body["resolution"] == "1080p"
    assert body["seed"] == 42
    assert body["camera_fixed"] is True
    assert body["watermark"] is True


def test_volc_model_alias_and_task_type():
    cfg = _cfg("volcengine", model=["doubao-seedance-1.0-pro"],
               base_url="https://ark.cn-beijing.volces.com/api/v3")
    out, cap = _call(cfg, {"prompt": "p", "duration": 5}, (200, json.dumps({"id": "t"})))
    assert cap["body"]["model"] == "doubao-seedance-1-0-pro-250528"
    assert cap["body"]["task_type"] == "t2v"
    assert cap["url"] == "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"


def test_volc_duration_normalized_to_5_or_10():
    cfg = _cfg("volcengine", model=["doubao-seedance-1-0-pro-250528"])
    _, cap = _call(cfg, {"prompt": "p", "duration": 8}, (200, json.dumps({"id": "t"})))
    assert cap["body"]["duration"] == 10


def test_volc_duration_12_for_1_5_pro():
    cfg = _cfg("volcengine", model=["doubao-seedance-1-5-pro-251215"])
    _, cap = _call(cfg, {"prompt": "p", "duration": 20}, (200, json.dumps({"id": "t"})))
    assert cap["body"]["duration"] == 12


def test_volc_draft_mode_480p_1_5_pro():
    cfg = _cfg("volcengine", model=["doubao-seedance-1-5-pro-251215"])
    _, cap = _call(cfg, {"prompt": "p", "resolution": "480p"}, (200, json.dumps({"id": "t"})))
    assert cap["body"]["draft"] is True


def test_volc_draft_mode_not_applied_1080p():
    cfg = _cfg("volcengine", model=["doubao-seedance-1-5-pro-251215"])
    _, cap = _call(cfg, {"prompt": "p", "resolution": "1080p"}, (200, json.dumps({"id": "t"})))
    assert "draft" not in cap["body"]


# ---------------------------------------------------------------- 首尾帧


def test_first_frame_role_and_i2v():
    out, cap = _call(_cfg("volcengine", model=["m"]),
                     {"prompt": "p", "first_frame_url": "https://cdn/first.png"},
                     (200, json.dumps({"id": "t"})))
    content = cap["body"]["content"]
    assert content[0] == {"type": "text", "text": "p"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "https://cdn/first.png"},
                          "role": "first_frame"}
    assert cap["body"]["task_type"] == "i2v"


def test_first_before_last_frame():
    out, cap = _call(_cfg("volcengine", model=["m"]),
                     {"prompt": "p",
                      "first_frame_url": "https://cdn/first.png",
                      "last_frame_url": "https://cdn/last.png"},
                     (200, json.dumps({"id": "t"})))
    content = cap["body"]["content"]
    assert [c.get("role") for c in content] == [None, "first_frame", "last_frame"]
    assert content[1]["image_url"]["url"].endswith("first.png")
    assert content[2]["image_url"]["url"].endswith("last.png")


def test_duplicate_frames_keeps_only_first():
    _, cap = _call(_cfg("volcengine", model=["m"]),
                   {"prompt": "p",
                    "first_frame_url": "https://cdn/same.png",
                    "last_frame_url": "https://cdn/same.png"},
                   (200, json.dumps({"id": "t"})))
    roles = [c.get("role") for c in cap["body"]["content"]]
    assert roles == [None, "first_frame"]


def test_image_url_falls_back_to_first_frame():
    """无 first/last 时，单张 image_url 仍按老逻辑作为 first_frame。"""
    _, cap = _call(_cfg("volcengine", model=["m"]),
                   {"prompt": "p", "image_url": "https://cdn/only.png"},
                   (200, json.dumps({"id": "t"})))
    roles = [c.get("role") for c in cap["body"]["content"]]
    assert roles == [None, "first_frame"]
    assert cap["body"]["task_type"] == "i2v"


def test_local_first_frame_converted_to_base64(tmp_path):
    (tmp_path / "f.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    _, cap = _call(_cfg("volcengine", model=["m"]),
                   {"prompt": "p",
                    "first_frame_url": "http://localhost:5679/static/f.png",
                    "files_base_url": "http://localhost:5679/static",
                    "storage_local_path": str(tmp_path)},
                   (200, json.dumps({"id": "t"})))
    url = cap["body"]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


def test_asset_url_passed_through():
    _, cap = _call(_cfg("volcengine", model=["m"]),
                   {"prompt": "p", "first_frame_url": "asset://abc-123"},
                   (200, json.dumps({"id": "t"})))
    assert cap["body"]["content"][1]["image_url"]["url"] == "asset://abc-123"


# ---------------------------------------------------------------- 调度 / 配置


def test_missing_config_raises():
    with _FakeDB([]):
        with pytest.raises(RuntimeError, match="未配置视频模型"):
            vc.call_video_api(object(), log, {"prompt": "p"})


@pytest.mark.parametrize(
    "protocol, cfg",
    [
        ("agnes", _cfg("agnes", api_protocol="agnes", endpoint="/videos", model=["agnes-video-v2.0"])),
        ("minimax_h3", _cfg("minimax_h3", api_protocol="minimax_h3", endpoint="/v2/video_generation", model=["MiniMax-H3"])),
        ("sora", _cfg("openai", api_protocol="sora", endpoint="/v1/videos", model=["sora-2"])),
        ("kling_omni", _cfg("ffir", api_protocol="kling_omni", base_url="https://ffir.cn", model=["kling-video-o1"])),
        ("volcengine_omni", _cfg("volcengine", api_protocol="volcengine_omni", base_url="https://ark.cn-beijing.volces.com/api/v3", model=["doubao-seedance-2.0-pro"])),
        ("vidu", _cfg("vidu", api_protocol="vidu", base_url="https://api.vidu.cn", model=["viduq2"])),
    ],
)
def test_ported_vendor_protocol_dispatches(protocol, cfg):
    def post(url, headers, body):
        return 200, json.dumps({"task_id": "task-1", "state": "success"})

    with _FakeDB([cfg]):
        out = vc.call_video_api(object(), log, {"prompt": "p", "model": cfg["model"][0]}, post_json=post)
    expected_id = "omni:task-1" if protocol == "kling_omni" else "task-1"
    assert out["task_id"] == expected_id


def test_vidu_official_headers_and_body():
    cfg = _cfg("vidu", api_protocol="vidu", base_url="https://api.vidu.cn", endpoint="", api_key="MY_KEY", model=["viduq2"])
    out, cap = _call(cfg, {"prompt": "测试提示词", "duration": 4, "aspect_ratio": "16:9", "resolution": "720p"},
                     (200, json.dumps({"task_id": "vidu-task-99", "state": "created"})))
    assert out["task_id"] == "vidu-task-99"
    assert cap["url"] == "https://api.vidu.cn/ent/v2/text2video"
    assert cap["headers"]["Authorization"] == "Token MY_KEY"
    body = cap["body"]
    assert body["model"] == "viduq2"
    assert body["duration"] == 4
    assert body["resolution"] == "720p"
    assert body["aspect_ratio"] == "16:9"
    assert body["watermark"] is False


def test_vidu_proxy_non_official_headers_and_aspect_ratio_field():
    cfg = _cfg("vidu", api_protocol="vidu", base_url="https://proxy.example.com", endpoint="", api_key="PROXY_KEY", model=["viduq2"])
    out, cap = _call(cfg, {"prompt": "测试提示词", "duration": 6, "aspect_ratio": "9:16"},
                     (200, json.dumps({"task_id": "vidu-task-100", "state": "created"})))
    assert out["task_id"] == "vidu-task-100"
    assert cap["headers"]["Authorization"] == "Bearer PROXY_KEY"
    assert cap["url"] == "https://proxy.example.com/ent/v2/text2video"
    body = cap["body"]
    assert body["aspect_ratio"] == "9:16"
    assert body["aspectRatio"] == "9:16"


def test_vidu_img2video_endpoint_when_image_url(monkeypatch):
    cfg = _cfg("vidu", api_protocol="vidu", base_url="https://api.vidu.cn", endpoint="", api_key="KEY", model=["viduq2"])
    monkeypatch.setattr(vc, "probe_vidu_reference_image_size", lambda *a, **kw: {"width": 1280, "height": 720})
    out, cap = _call(cfg, {"prompt": "生成", "image_url": "https://img.cdn/ref.png", "aspect_ratio": "16:9"},
                     (200, json.dumps({"task_id": "vidu-task-101"})))
    assert cap["url"] == "https://api.vidu.cn/ent/v2/img2video"
    assert cap["body"]["images"] == ["https://img.cdn/ref.png"]


def test_vidu_direct_video_url_return():
    cfg = _cfg("vidu", api_protocol="vidu", base_url="https://api.vidu.cn", endpoint="", model=["viduq2"])
    out, _ = _call(cfg, {"prompt": "生成"}, (200, json.dumps({"video_url": "https://cdn/vid.mp4"})))
    assert out == {"video_url": "https://cdn/vid.mp4"}


def test_vidu_error_handling():
    cfg = _cfg("vidu", api_protocol="vidu", base_url="https://api.vidu.cn", endpoint="", model=["viduq2"])
    out, _ = _call(cfg, {"prompt": "生成"}, (400, json.dumps({"message": "sensitive content detected"})))
    assert "sensitive content detected" in out["error"]


def test_preferred_model_overrides_default():
    cfg = _cfg(model=["model-a", "model-b"], default_model="model-a")
    _, cap = _call(cfg, {"prompt": "p", "model": "model-b"}, (200, json.dumps({"id": "t"})))
    assert cap["body"]["model"] == "model-b"
