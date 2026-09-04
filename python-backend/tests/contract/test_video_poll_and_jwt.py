"""测试 videoClient.poll_video_task 的协议分支与 klingJwt 的 JWT 签发。

poll_video_task 通过注入 fetch_json 打桩，避免真实网络调用；
同时校验它发出的 URL 与 Node buildQueryUrl 一致。
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.logger import get_logger  # noqa: E402
from app.services import klingJwt  # noqa: E402
from app.services import videoClient as vc  # noqa: E402

log = get_logger("lmd.test")


def _make_fetch(responses):
    """按顺序返回 (status, raw)；用尽后返回 500。"""

    calls = []

    def fetch(url, headers):
        calls.append((url, headers))
        if not responses:
            return 500, '{"error":"no more responses"}'
        return responses.pop(0)

    return fetch, calls


def _poll(config, responses, task_id="t-1", max_attempts=3, interval_ms=0):
    fetch, calls = _make_fetch(responses)
    # interval 设为 0，避免测试耗时
    out = vc.poll_video_task(
        log, 1, task_id, config, max_attempts=max_attempts, interval_ms=interval_ms, fetch_json=fetch
    )
    return out, calls


# ---------------------------------------------------------------- 各协议分支


def test_kling_success():
    cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
    body = {"code": 0, "data": {"task_status": "succeed",
                                "task_result": {"videos": [{"url": "https://v/1.mp4"}]}}}
    out, calls = _poll(cfg, [(200, json.dumps(body))], task_id="t2v:abc")
    assert out == {"video_url": "https://v/1.mp4"}
    assert calls[0][0] == "https://api.klingai.com/v1/videos/text2video/abc"
    assert calls[0][1] == {"Authorization": "Bearer k"}


def test_kling_i2v_endpoint():
    cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
    body = {"code": 0, "data": {"task_status": "succeed",
                                "task_result": {"videos": [{"url": "https://v/2.mp4"}]}}}
    out, calls = _poll(cfg, [(200, json.dumps(body))], task_id="i2v:xyz")
    assert out == {"video_url": "https://v/2.mp4"}
    assert calls[0][0] == "https://api.klingai.com/v1/videos/image2video/xyz"


def test_kling_failed():
    cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
    body = {"code": 0, "data": {"task_status": "failed", "task_status_msg": "内容违规"}}
    out, _ = _poll(cfg, [(200, json.dumps(body))], task_id="t2v:a")
    assert out == {"error": "可灵视频生成失败: 内容违规"}


def test_kling_api_error_code():
    cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
    out, _ = _poll(cfg, [(200, json.dumps({"code": 1001, "message": "鉴权失败"}))], task_id="t2v:a")
    assert out == {"error": "鉴权失败"}


def test_agnes_success_with_metadata_url():
    cfg = {"provider": "agnes", "base_url": "https://apihub.agnes-ai.com", "api_key": "k"}
    body = {"status": "completed", "metadata": {"url": "https://cdn/a.mp4"}}
    out, calls = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://cdn/a.mp4"}
    assert calls[0][0] == "https://apihub.agnes-ai.com/v1/videos/t-1"


def test_agnes_failed():
    cfg = {"provider": "agnes", "base_url": "https://apihub.agnes-ai.com", "api_key": "k"}
    out, _ = _poll(cfg, [(200, json.dumps({"status": "failed", "message": "余额不足"}))])
    assert out == {"error": "余额不足"}


def test_agnes_completed_without_url_exhausts_grace():
    """completed 但无直链 → 连续 12 轮后放弃。"""
    cfg = {"provider": "agnes", "base_url": "https://apihub.agnes-ai.com", "api_key": "k"}
    responses = [(200, json.dumps({"status": "completed"})) for _ in range(12)]
    out, _ = _poll(cfg, responses, max_attempts=20)
    assert "error" in out and "Agnes 任务完成但未返回视频地址" in out["error"]


def test_minimax_h3_success():
    cfg = {"provider": "minimax_h3", "base_url": "https://api.minimaxi.com", "api_key": "k"}
    body = {"task": {"id": "t-1", "status": "success", "content": {"url": "https://v/h3.mp4"}}}
    out, calls = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://v/h3.mp4"}
    assert calls[0][0] == "https://api.minimaxi.com/v2/query/video_generation/t-1"


def test_minimax_h3_failed_uses_error_message():
    cfg = {"provider": "minimax_h3", "base_url": "https://api.minimaxi.com", "api_key": "k"}
    body = {"task": {"status": "failed", "error": {"message": "prompt 违规"}}}
    out, _ = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"error": "prompt 违规"}


def test_dashscope_success():
    cfg = {"provider": "dashscope", "base_url": "https://dashscope.aliyuncs.com", "api_key": "k"}
    body = {"output": {"task_status": "SUCCEEDED", "video_url": "https://v/ds.mp4"}}
    out, _ = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://v/ds.mp4"}


def test_dashscope_failed():
    cfg = {"provider": "dashscope", "base_url": "https://dashscope.aliyuncs.com", "api_key": "k"}
    out, _ = _poll(cfg, [(200, json.dumps({"output": {"task_status": "FAILED", "message": "生成失败"}}))])
    assert out == {"error": "生成失败"}


def test_gemini_done():
    cfg = {"provider": "gemini", "base_url": "https://generativelanguage.googleapis.com", "api_key": "k"}
    body = {"done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "https://v/g.mp4"}}]}}}
    out, calls = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://v/g.mp4"}
    assert calls[0][0] == "https://generativelanguage.googleapis.com/v1beta/t-1"
    assert calls[0][1] == {"x-goog-api-key": "k"}


def test_gemini_error():
    cfg = {"provider": "gemini", "base_url": "https://generativelanguage.googleapis.com", "api_key": "k"}
    out, _ = _poll(cfg, [(200, json.dumps({"error": {"message": "quota exceeded"}}))])
    assert out == {"error": "quota exceeded"}


def test_vidu_success():
    cfg = {"provider": "vidu", "base_url": "https://api.vidu.cn", "api_key": "k"}
    body = {"state": "success", "creations": [{"url": "https://v/vidu.mp4"}]}
    out, calls = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://v/vidu.mp4"}
    # 官方域名用 Token 前缀
    assert calls[0][1] == {"Authorization": "Token k"}


def test_vidu_non_official_uses_bearer():
    cfg = {"provider": "vidu", "base_url": "https://proxy.example.com", "api_key": "k"}
    body = {"state": "success", "creations": [{"url": "https://v/v.mp4"}]}
    out, calls = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://v/v.mp4"}
    assert calls[0][1] == {"Authorization": "Bearer k"}


def test_sora_success():
    cfg = {"provider": "openai", "api_protocol": "sora", "base_url": "https://api.openai.com", "api_key": "k"}
    body = {"status": "completed", "video_url": "https://v/sora.mp4"}
    out, _ = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://v/sora.mp4"}


def test_volc_generic_fallback():
    cfg = {"provider": "volcengine", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "api_key": "k"}
    body = {"status": "succeeded", "content": {"video_url": "https://v/volc.mp4"}}
    out, calls = _poll(cfg, [(200, json.dumps(body))])
    assert out == {"video_url": "https://v/volc.mp4"}
    assert calls[0][0] == "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/t-1"


def test_jimeng_rejects_polling():
    cfg = {"provider": "jimeng_ai_api", "base_url": "https://x", "api_key": "k"}
    out, calls = _poll(cfg, [])
    assert "不应进入轮询" in out["error"]
    assert calls == []


def test_non_2xx_continues():
    cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
    body = {"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://v/1.mp4"}]}}}
    out, _ = _poll(cfg, [(500, "boom"), (200, json.dumps(body))], task_id="t2v:a")
    assert out == {"video_url": "https://v/1.mp4"}


def test_invalid_json_continues():
    cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
    body = {"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://v/1.mp4"}]}}}
    out, _ = _poll(cfg, [(200, "not json"), (200, json.dumps(body))], task_id="t2v:a")
    assert out == {"video_url": "https://v/1.mp4"}


def test_timeout_returns_error():
    cfg = {"provider": "kling", "base_url": "https://api.klingai.com", "api_key": "k"}
    out, _ = _poll(cfg, [(200, json.dumps({"code": 0, "data": {"task_status": "processing"}}))],
                   task_id="t2v:a", max_attempts=2)
    assert out == {"error": "视频生成超时"}


def test_kling_omni_official_query_path():
    """Omni 且官方域名：query 路径应为官方模板（用户未自定义时）。"""
    cfg = {"provider": "ffir", "base_url": "https://api-beijing.klingai.com", "api_key": "tok"}
    body = {"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://v/o.mp4"}]}}}
    out, calls = _poll(cfg, [(200, json.dumps(body))], task_id="omni:abc")
    assert out == {"video_url": "https://v/o.mp4"}
    assert calls[0][0] == "https://api-beijing.klingai.com/v1/videos/omni-video/abc"
    assert calls[0][1] == {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------- JWT


def test_kling_jwt_structure_and_payload():
    token = klingJwt.sign_kling_official_jwt("AK-123", "SK-456", {"ttlSeconds": 1800})
    parts = token.split(".")
    assert len(parts) == 3

    def b64d(seg):
        return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))

    assert b64d(parts[0]) == {"alg": "HS256", "typ": "JWT"}
    payload = b64d(parts[1])
    assert payload["iss"] == "AK-123"
    assert set(payload.keys()) == {"iss", "exp", "nbf"}  # noTimestamp：不含 iat
    assert payload["exp"] - payload["nbf"] == 1800 + klingJwt.DEFAULT_NBF_SKEW_SEC


def test_kling_jwt_secret_base64_mode():
    import base64 as b64
    import hmac
    from hashlib import sha256

    sk_plain = "my-secret"
    sk_b64 = b64.b64encode(sk_plain.encode()).decode()
    token = klingJwt.sign_kling_official_jwt("AK", sk_b64, {"secretEncoding": "base64"})
    signing_input, sig = token.rsplit(".", 1)
    expected = hmac.new(sk_plain.encode(), signing_input.encode(), sha256).digest()
    assert b64.urlsafe_b64encode(expected).rstrip(b"=").decode() == sig


def test_kling_jwt_empty_credentials_raise():
    with pytest.raises(ValueError):
        klingJwt.sign_kling_official_jwt("", "SK")
    with pytest.raises(ValueError):
        klingJwt.sign_kling_official_jwt("AK", "")


def test_normalize_credential_strips_zero_width():
    assert klingJwt.normalize_kling_credential("﻿AK​123﻿ ") == "AK123"
    assert klingJwt.normalize_kling_credential(None) == ""


def test_jwt_part_lengths():
    token = klingJwt.sign_kling_official_jwt("AK", "SK")
    lens = klingJwt.jwt_part_lengths(token)
    assert set(lens.keys()) == {"header", "payload", "signature"}
    assert klingJwt.jwt_part_lengths("not-a-jwt") == {"invalid": True, "part_count": 1}
    assert klingJwt.jwt_part_lengths(None) is None


def test_unsafe_decode_payload():
    token = klingJwt.sign_kling_official_jwt("AK-9", "SK")
    p = klingJwt.unsafe_decode_kling_jwt_payload(token)
    assert p["iss"] == "AK-9"
    assert klingJwt.unsafe_decode_kling_jwt_payload("junk") is None


# ---------------------------------------------------------------- Omni 配置解析


def test_resolve_kling_omni_base_url_defaults():
    assert vc.resolve_kling_omni_base_url({}) == "https://ffir.cn"
    assert vc.resolve_kling_omni_base_url({"base_url": "https://x.com/"}) == "https://x.com"
    cfg = {"settings": json.dumps({"kling_access_key": "ak", "kling_secret_key": "sk"})}
    assert vc.resolve_kling_omni_base_url(cfg) == "https://api-beijing.klingai.com"


def test_resolve_kling_omni_query_path_official_vs_proxy():
    assert vc.resolve_kling_omni_query_path_template({}, "https://api.klingai.com") == vc.KLING_OMNI_OFFICIAL_QUERY
    assert vc.resolve_kling_omni_query_path_template({}, "https://ffir.cn") == vc.KLING_OMNI_PROXY_QUERY
    # 官方域名 + 中转模板 → 纠正为官方模板
    cfg = {"query_endpoint": vc.KLING_OMNI_PROXY_QUERY}
    assert vc.resolve_kling_omni_query_path_template(cfg, "https://api.klingai.com") == vc.KLING_OMNI_OFFICIAL_QUERY


def test_is_kling_official_omni_host():
    assert vc.is_kling_official_omni_host("api-beijing.klingai.com")
    assert vc.is_kling_official_omni_host("https://api-singapore.klingai.com/")
    assert not vc.is_kling_official_omni_host("https://ffir.cn")
    assert not vc.is_kling_official_omni_host("")


def test_resolve_kling_omni_aspect_ratio_fallback():
    assert vc.resolve_kling_omni_aspect_ratio("9:16") == "9:16"
    assert vc.resolve_kling_omni_aspect_ratio("portrait") == "9:16"
    assert vc.resolve_kling_omni_aspect_ratio("21:9") == "16:9"
    assert vc.resolve_kling_omni_aspect_ratio(None) == "16:9"


def test_parse_kling_omni_poll_video_url():
    assert vc.parse_kling_omni_poll_video_url(
        {"data": {"task_result": {"videos": [{"url": "https://v/1.mp4"}]}}}
    ) == "https://v/1.mp4"
    assert vc.parse_kling_omni_poll_video_url({"data": {"video_url": "https://v/2.mp4"}}) == "https://v/2.mp4"
    assert vc.parse_kling_omni_poll_video_url({"output": {"video_url": "https://v/3.mp4"}}) == "https://v/3.mp4"
    assert vc.parse_kling_omni_poll_video_url({}) is None
