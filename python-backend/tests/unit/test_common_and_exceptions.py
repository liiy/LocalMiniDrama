"""Unit tests for app.common utilities, app.core.exceptions, and backward-compatible platform_common."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common import (
    BEIJING_TZ,
    SafeFormatDict,
    beijing_now,
    compact_dict,
    ensure_dir,
    ensure_valid_json_str,
    json_dumps,
    json_loads,
    now_beijing_str,
    now_iso,
    render_template_text,
    safe_filename,
    safe_json_dumps,
    safe_json_loads,
    timestamp,
)
from app.core.exceptions import (
    AiProviderException,
    AppException,
    ConflictException,
    EntityNotFoundException,
    ForbiddenException,
    StorageException,
    UnauthorizedException,
    ValidationException,
    WorkflowException,
)
import app.platform_common as pc


def test_time_utils():
    now_dt = beijing_now()
    assert isinstance(now_dt, datetime)
    assert now_dt.tzinfo == BEIJING_TZ

    iso_str = now_iso()
    assert "+08:00" in iso_str

    bj_str = now_beijing_str()
    assert len(bj_str) == 19
    assert bj_str[4] == "-" and bj_str[7] == "-"

    ts = timestamp()
    assert isinstance(ts, str) and len(ts) > 0


def test_json_utils():
    assert json_dumps(None) == ""
    assert json_dumps({"a": 1}) == '{"a":1}'
    assert json_dumps("already_str") == "already_str"

    assert json_loads(None) is None
    assert json_loads("", default={}) == {}
    assert json_loads('{"x": 10}') == {"x": 10}
    assert json_loads("invalid json", default="fallback") == "fallback"
    assert json_loads(123) == 123

    assert safe_json_dumps({"k": "v"}) == '{"k":"v"}'
    assert safe_json_loads('{"k":"v"}') == {"k": "v"}

    assert ensure_valid_json_str(None) == "{}"
    assert ensure_valid_json_str({"key": "val"}) == '{"key":"val"}'
    assert ensure_valid_json_str('{"valid": true}') == '{"valid": true}'
    assert ensure_valid_json_str("invalid", fallback="[]") == "[]"


def test_template_utils():
    tmpl = "Hello, {name}! Your role is {role}. Schema: { name: string, type: 'scene' }"
    rendered = render_template_text(tmpl, {"name": "Alice", "role": "Hero"})
    assert "Hello, Alice!" in rendered
    assert "Your role is Hero." in rendered
    # JSON schema like braces should be preserved intact
    assert "{ name: string, type: 'scene' }" in rendered

    # Missing variables remain intact
    unfilled = render_template_text("Missing {missing_var}", {})
    assert unfilled == "Missing {missing_var}"


def test_file_and_dict_utils(tmp_path):
    sub = tmp_path / "sub" / "deep"
    res = ensure_dir(sub)
    assert res.exists() and res.is_dir()

    cleaned = safe_filename("test/file:name*?.txt")
    assert "/" not in cleaned and ":" not in cleaned and "?" not in cleaned

    row = {"id": 1, "name": "test", "deleted_at": None, "extra": "data"}
    compacted = compact_dict(row)
    assert "deleted_at" not in compacted
    assert compacted["id"] == 1
    assert compact_dict(None) is None


def test_platform_common_backward_compatibility():
    """Verify that app.platform_common exposes all expected legacy symbols."""
    assert pc.beijing_now is beijing_now
    assert pc.now_iso is now_iso
    assert pc.json_dumps is json_dumps
    assert pc.json_loads is json_loads
    assert pc.render_template_text is render_template_text
    assert pc.compact_dict is compact_dict


def test_domain_exceptions_and_fastapi_handling():
    app = FastAPI()

    @app.exception_handler(AppException)
    async def app_exc_handler(request, exc: AppException):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})

    @app.get("/test-404")
    def route_404():
        raise EntityNotFoundException("剧本不存在")

    @app.get("/test-400")
    def route_400():
        raise ValidationException("参数不合法")

    @app.get("/test-500")
    def route_500():
        raise WorkflowException("阶段执行错误")

    client = TestClient(app)

    r404 = client.get("/test-404")
    assert r404.status_code == 404
    assert r404.json()["error"] == "NOT_FOUND"

    r400 = client.get("/test-400")
    assert r400.status_code == 400
    assert r400.json()["error"] == "BAD_REQUEST"

    r500 = client.get("/test-500")
    assert r500.status_code == 500
    assert r500.json()["error"] == "WORKFLOW_EXECUTION_ERROR"


def test_ai_provider_strategy_registry():
    """验证图像与视频 Provider 策略工厂模式。"""
    from app.services.image_client import get_image_provider_registry
    from app.services.video_client import get_video_provider_registry
    from app.services.providers.base import BaseImageProvider, BaseVideoProvider

    image_reg = get_image_provider_registry()
    assert image_reg is not None
    dashscope_img = image_reg.get("dashscope")
    assert isinstance(dashscope_img, BaseImageProvider)
    assert dashscope_img.protocol_name == "dashscope"

    kling_img = image_reg.get("kling")
    assert isinstance(kling_img, BaseImageProvider)

    gemini_img = image_reg.get("gemini")
    assert isinstance(gemini_img, BaseImageProvider)

    volc_img = image_reg.get("volcengine")
    assert isinstance(volc_img, BaseImageProvider)

    video_reg = get_video_provider_registry()
    assert video_reg is not None
    volc_vid = video_reg.get("volcengine")
    assert isinstance(volc_vid, BaseVideoProvider)
    assert volc_vid.protocol_name == "volcengine"

    kling_vid = video_reg.get("kling")
    assert isinstance(kling_vid, BaseVideoProvider)

    minimax_vid = video_reg.get("minimax_h3")
    assert isinstance(minimax_vid, BaseVideoProvider)

    veo_vid = video_reg.get("veo3")
    assert isinstance(veo_vid, BaseVideoProvider)

