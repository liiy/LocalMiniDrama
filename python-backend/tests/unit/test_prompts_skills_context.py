"""单元测试：验证迭代 2 Prompt / Skill / Context 中心与运行记录功能。"""
from __future__ import annotations

from app.context.builder import _estimate_tokens, _limit_text
from app.platform_common import render_template_text
from app.prompts.registry_service import _decode_prompt_row
from app.skills.defaults import DEFAULT_PROMPTS, DEFAULT_SKILLS
from app.skills.registry_service import _decode_skill, _decode_skill_version


def test_default_skills_and_prompts_integrity():
    """验证预设的所有 Skill 和 Prompt 具有完整定义的 prompt_key 与 domain。"""
    skill_keys = {s["skill_key"] for s in DEFAULT_SKILLS}
    assert "script_requirement_analysis" in skill_keys
    assert "drama_bible_generation" in skill_keys
    assert "episode_script_writing" in skill_keys
    assert "novel_to_script_adaptation" in skill_keys
    assert "storyboard_generation" in skill_keys
    assert "frame_prompt_generation" in skill_keys
    assert "video_prompt_generation" in skill_keys
    assert "voice_profile_generation" in skill_keys
    assert "music_bible_generation" in skill_keys
    assert "creative_quality_review" in skill_keys

    prompt_keys = {p["prompt_key"] for p in DEFAULT_PROMPTS}
    for skill in DEFAULT_SKILLS:
        for pk in skill.get("prompt_keys", []):
            assert pk in prompt_keys, f"Skill {skill['skill_key']} 引用的 Prompt {pk} 未在 DEFAULT_PROMPTS 中定义"


def test_prompt_template_rendering():
    """验证 Prompt 模板渲染变量替换与缺失变量宽容保留机制。"""
    template = "我是短剧导演。剧名：{title}，题材：{genre}，集数：{episode_count}集，风格：{visual_style}。"
    vars_dict = {
        "title": "战神归来",
        "genre": "都市热血",
        "episode_count": 80,
    }
    rendered = render_template_text(template, vars_dict)
    assert "战神归来" in rendered
    assert "都市热血" in rendered
    assert "80集" in rendered
    # 缺失的变量保留占位符以便后续调试排查
    assert "{visual_style}" in rendered


def test_decode_prompt_and_skill_rows():
    """验证 DB 行记录解码为结构化 Python 字典。"""
    raw_prompt_row = {
        "prompt_key": "script.drama_bible",
        "version": 1,
        "name": "整剧 Bible 生成",
        "input_schema": '{"type": "object"}',
        "output_schema": '{"type": "object"}',
        "tags": '["script", "bible"]',
        "metadata": '{"author": "system"}',
    }
    decoded_prompt = _decode_prompt_row(raw_prompt_row)
    assert decoded_prompt["prompt_key"] == "script.drama_bible"
    assert isinstance(decoded_prompt["input_schema"], dict)
    assert isinstance(decoded_prompt["tags"], list)
    assert decoded_prompt["tags"] == ["script", "bible"]

    raw_skill_row = {
        "skill_key": "storyboard_generation",
        "name": "分镜生成",
        "domain": "storyboard",
        "metadata": '{"category": "visual"}',
    }
    decoded_skill = _decode_skill(raw_skill_row)
    assert decoded_skill["domain"] == "storyboard"
    assert decoded_skill["metadata"] == {"category": "visual"}

    raw_version_row = {
        "skill_key": "storyboard_generation",
        "version": 1,
        "input_schema": '{"episode_id": "int"}',
        "output_schema": '{"storyboards": "array"}',
        "prompt_keys": '["storyboard.generate"]',
        "context_policy": '{"include_scenes": true}',
        "model_policy": '{"temperature": 0.7}',
        "quality_checks": '{"require_json": true}',
        "examples": '[{"input": "foo", "output": "bar"}]',
    }
    decoded_ver = _decode_skill_version(raw_version_row)
    assert decoded_ver["prompt_keys"] == ["storyboard.generate"]
    assert decoded_ver["examples"][0]["input"] == "foo"
    assert decoded_ver["model_policy"]["temperature"] == 0.7


def test_context_builder_helpers():
    """验证 Context Builder 字符截断与 Token 估算纯函数。"""
    long_text = "这是一段非常长的剧本内容。" * 500
    limited = _limit_text(long_text, 100)
    assert len(limited) <= 120
    assert limited.endswith("...[truncated]")

    short_text = "短文本"
    assert _limit_text(short_text, 100) == "短文本"

    token_est = _estimate_tokens({"title": "战神狂飙", "characters": ["顾凌霄", "沈清月"]})
    assert token_est >= 1


def test_prompt_registry_compare_and_rollback_flow(db_session):
    """验证 Prompt 模板的版本发布、比对、回滚与审计记录流转。"""
    from app.prompts.registry_service import (
        compare_prompt_templates,
        create_prompt_template,
        get_prompt_template,
        get_prompt_template_history,
        record_prompt_run,
        rollback_prompt_template,
    )

    # 1. 创建 v1 模板
    v1 = create_prompt_template(
        db_session,
        {
            "prompt_key": "test.unit.drama_bible",
            "name": "测试剧本大纲生成",
            "template_body": "你是一个短剧编剧。请根据{premise}生成大纲。",
            "description": "初始版本",
            "metadata": {"author": "copilot"},
        },
    )
    assert v1["version"] == 1
    assert v1["status"] == "active"

    # 2. 创建 v2 模板（新版本）
    v2 = create_prompt_template(
        db_session,
        {
            "prompt_key": "test.unit.drama_bible",
            "name": "测试剧本大纲生成-进阶版",
            "template_body": "你是一个王牌短剧编剧。请根据{premise}和{genre}生成大纲。",
            "description": "增加题材参数",
        },
    )
    assert v2["version"] == 2
    assert v2["status"] == "active"

    # 查询当前激活版本应为 v2
    active = get_prompt_template(db_session, "test.unit.drama_bible")
    assert active["version"] == 2

    # 3. 历史版本查询
    history = get_prompt_template_history(db_session, "test.unit.drama_bible")
    assert len(history) == 2

    # 4. 双版本对比
    diff = compare_prompt_templates(db_session, "test.unit.drama_bible", 1, 2)
    assert diff["v1"]["version"] == 1
    assert diff["v2"]["version"] == 2
    assert diff["diff"]["body_changed"] is True

    # 5. 回滚到 v1
    v3 = rollback_prompt_template(db_session, "test.unit.drama_bible", 1)
    assert v3["version"] == 3
    assert v3["status"] == "active"
    assert "根据{premise}生成大纲" in v3["template_body"]

    # 6. 记录一次 Prompt Run
    run_rec = record_prompt_run(
        db_session,
        {
            "prompt_key": "test.unit.drama_bible",
            "prompt_version": 3,
            "agent_name": "script_agent",
            "variables": {"premise": "赘婿逆袭"},
            "context_snapshot": {"drama_id": 100},
            "final_prompt": "你是一个短剧编剧。请根据赘婿逆袭生成大纲。",
            "raw_output": '{"title": "赘婿之王"}',
            "parsed_output": {"title": "赘婿之王"},
            "prompt_tokens": 25,
            "completion_tokens": 40,
            "latency_ms": 320,
        },
    )
    assert run_rec["id"] > 0
    assert run_rec["prompt_key"] == "test.unit.drama_bible"
    assert run_rec["parsed_output"]["title"] == "赘婿之王"


def test_prompt_platform_api_endpoints(db_session):
    """验证平台化 Prompt 接口与别名路由（如 /platform/prompts 与 /platform/prompts/templates）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1 import platform
    from app.db.session import get_db

    def _override_db():
        yield db_session

    mini_app = FastAPI()
    mini_app.include_router(platform.router, prefix="/api/v1")
    mini_app.dependency_overrides[get_db] = _override_db

    client = TestClient(mini_app)
    # 1. 创建模板
    resp = client.post(
        "/api/v1/platform/prompts",
        json={
            "prompt_key": "test.api.prompt",
            "name": "API测试模板",
            "template_body": "测试模板内容：{topic}",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["prompt_key"] == "test.api.prompt"

    # 2. 列表查询（两种路由均支持）
    r1 = client.get("/api/v1/platform/prompts?prompt_key=test.api.prompt")
    assert r1.status_code == 200
    assert len(r1.json()["data"]) >= 1

    r2 = client.get("/api/v1/platform/prompts/templates?prompt_key=test.api.prompt")
    assert r2.status_code == 200
    assert len(r2.json()["data"]) >= 1

    # 3. 详情与历史查询
    r_detail = client.get("/api/v1/platform/prompts/test.api.prompt")
    assert r_detail.status_code == 200
    assert r_detail.json()["data"]["prompt_key"] == "test.api.prompt"

    r_hist = client.get("/api/v1/platform/prompts/templates/test.api.prompt/history")
    assert r_hist.status_code == 200
    assert len(r_hist.json()["data"]) >= 1


