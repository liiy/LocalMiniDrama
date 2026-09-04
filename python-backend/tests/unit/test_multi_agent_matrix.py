"""单元测试：验证迭代 5 多 Agent 专家矩阵与输出落库适配。"""
from __future__ import annotations

from app.agents.output_applier import OUTPUT_APPLIER_STEPS, normalize_agent_payload
from app.agents.registry import DEFAULT_AGENTS, get_agent, list_agents
from app.agents.runtime import AGENT_RUNTIME_STEPS, build_prompt_variables


def test_agent_registry_all_14_experts():
    """验证 Multi-Agent 专家矩阵 14 位领域 Agent 注册完整。"""
    agents = list_agents()
    assert len(agents) >= 14
    agent_names = {a["agent_name"] for a in agents}
    expected_agents = {
        "producer",
        "requirement",
        "novel_adapter",
        "script_writer",
        "continuity",
        "character",
        "scene",
        "prop",
        "storyboard_director",
        "visual_director",
        "video_director",
        "voice",
        "music_director",
        "qa",
    }
    assert expected_agents <= agent_names

    for name in expected_agents:
        agent = get_agent(name)
        assert agent is not None
        assert agent["display_name"] != ""
        assert len(agent["default_skill_keys"]) >= 1


def test_normalize_agent_payload_variants():
    """验证 Agent 输出结果规整化（dict、list、scalar 与 parse_error 兜底）。"""
    # 字典格式
    dict_res = {"parsed_output": {"title": "战神", "episodes": 80}}
    assert normalize_agent_payload(dict_res) == {"title": "战神", "episodes": 80}

    # 列表格式
    list_res = {"parsed_output": [{"name": "顾凌霄"}, {"name": "沈清月"}]}
    assert normalize_agent_payload(list_res) == {"items": [{"name": "顾凌霄"}, {"name": "沈清月"}]}

    # 纯文本值
    scalar_res = {"parsed_output": "这是一段纯文本"}
    assert normalize_agent_payload(scalar_res) == {"value": "这是一段纯文本"}

    # 解析错误回退
    err_res = {"parsed_output": None, "raw_output": "{bad json", "parse_error": "JSONDecodeError"}
    norm_err = normalize_agent_payload(err_res)
    assert norm_err["raw_output"] == "{bad json"
    assert norm_err["parse_error"] == "JSONDecodeError"


def test_build_prompt_variables_comprehensive_flattening():
    """验证 Agent Runtime 自动为 Prompt 模板组装扁平化变量。"""
    run = {
        "id": "wf_run_123",
        "user_request": "写一部战神归来短剧",
        "input_payload": {"title": "狂龙破天", "target_episodes": 60},
    }
    step = {
        "step_key": "drama_bible_generation",
        "skill_key": "drama_bible_generation",
    }
    context = {
        "content": {
            "drama": {"title": "狂龙破天", "genre": "都市热血", "description": "战神受辱归来"},
            "characters": [{"name": "林辰", "role": "主角"}],
            "scenes": [{"name": "江家大厅"}],
            "props": [{"name": "龙王令"}],
            "memory_items": [{"title": "隐世宗门背景"}],
        }
    }
    variables = build_prompt_variables(run, step, context)
    assert variables["workflow_run_id"] == "wf_run_123"
    assert variables["step_key"] == "drama_bible_generation"
    assert variables["user_request"] == "写一部战神归来短剧"
    assert variables["title"] == "狂龙破天"
    assert variables["genre"] == "都市热血"
    assert "林辰" in variables["characters"]
    assert "江家大厅" in variables["scenes"]
    assert "龙王令" in variables["props"]
    assert "隐世宗门背景" in variables["memory"]
