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


def test_output_applier_full_entities(db_session):
    """验证 Multi-Agent 产出的全实体智能落库（角色、场景、道具、分镜与剧本）。"""
    from sqlalchemy import text
    from app.agents import output_applier
    from app.db.session import fetch_all, fetch_one
    from app.skills import bootstrap_service

    bootstrap_service.bootstrap_defaults(db_session)

    # 1. 创建前置剧目与单集
    db_session.execute(
        text(
            """
            INSERT INTO dramas (id, title, description, created_at, updated_at)
            VALUES (101, '霸道总裁爱上我', '都市甜宠短剧', '2025-01-01', '2025-01-01')
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO episodes (id, drama_id, episode_number, title, created_at, updated_at)
            VALUES (201, 101, 1, '第一集：初遇', '2025-01-01', '2025-01-01')
            """
        )
    )
    db_session.commit()

    mock_run = {"id": "run_test_agent", "drama_id": 101, "episode_id": 201}

    # 2. 角色提取落库
    char_step = {"id": 1, "step_key": "character_extraction"}
    char_result = {
        "parsed_output": {
            "characters": [
                {
                    "name": "陆沉",
                    "role": "protagonist",
                    "description": "集团继承人",
                    "personality": "高冷深情",
                    "appearance": "黑色西装，银色腕表",
                    "identity_anchors": {"hair": "黑色短发", "eyes": "深邃黑眸"},
                }
            ]
        }
    }
    res_char = output_applier.apply_agent_output(db_session, mock_run, char_step, char_result)
    assert res_char["status"] == "applied"
    chars = fetch_all(db_session, "SELECT * FROM characters WHERE drama_id = 101")
    assert len(chars) == 1
    assert chars[0]["name"] == "陆沉"

    # 3. 场景提取落库
    scene_step = {"id": 2, "step_key": "scene_extraction"}
    scene_result = {
        "parsed_output": {
            "scenes": [
                {
                    "location": "总裁办公室",
                    "time": "傍晚",
                    "prompt": "落地窗，落日余晖洒在红木办公桌上",
                    "atmosphere": "奢华庄重",
                }
            ]
        }
    }
    res_scene = output_applier.apply_agent_output(db_session, mock_run, scene_step, scene_result)
    assert res_scene["status"] == "applied"
    scenes = fetch_all(db_session, "SELECT * FROM scenes WHERE drama_id = 101")
    assert len(scenes) == 1
    assert scenes[0]["location"] == "总裁办公室"

    # 4. 道具提取落库
    prop_step = {"id": 3, "step_key": "prop_extraction"}
    prop_result = {
        "parsed_output": {
            "props": [
                {
                    "name": "定情钢笔",
                    "type": "关键信物",
                    "description": "镶金复古钢笔",
                    "prompt": "复古金丝刻花钢笔",
                }
            ]
        }
    }
    res_prop = output_applier.apply_agent_output(db_session, mock_run, prop_step, prop_result)
    assert res_prop["status"] == "applied"
    props = fetch_all(db_session, "SELECT * FROM props WHERE drama_id = 101")
    assert len(props) == 1
    assert props[0]["name"] == "定情钢笔"

    # 5. 单集剧本落库
    script_step = {"id": 4, "step_key": "episode_script_generation"}
    script_result = {"parsed_output": {"script_content": "【场景：总裁办公室】\n陆沉站在窗前看着远方..."}}
    res_script = output_applier.apply_agent_output(db_session, mock_run, script_step, script_result)
    assert res_script["status"] == "applied"
    ep = fetch_one(db_session, "SELECT script_content FROM episodes WHERE id = 201")
    assert "总裁办公室" in ep["script_content"]

    # 6. 分镜脚本批量落库
    storyboard_step = {"id": 5, "step_key": "storyboard_generation"}
    storyboard_result = {
        "parsed_output": {
            "storyboards": [
                {
                    "storyboard_number": 1,
                    "title": "特写窗外夕阳",
                    "description": "镜头缓缓摇向陆沉的侧脸",
                    "location": "办公室",
                    "time": "傍晚",
                    "duration": 4.0,
                    "dialogue": "",
                    "narration": "城市的黄昏总是来得匆忙。",
                    "action": "陆沉若有所思地端起咖啡杯",
                    "atmosphere": "孤独忧郁",
                    "image_prompt": "Cinematic shot of handsome CEO looking at sunset",
                    "video_prompt": "Slow camera push-in towards the window",
                    "shot_type": "特写",
                }
            ]
        }
    }
    res_sb = output_applier.apply_agent_output(db_session, mock_run, storyboard_step, storyboard_result)
    assert res_sb["status"] == "applied"
    sbs = fetch_all(db_session, "SELECT * FROM storyboards WHERE episode_id = 201")
    assert len(sbs) == 1
    assert sbs[0]["storyboard_number"] == 1
    assert sbs[0]["shot_type"] == "特写"


def test_agent_platform_api(db_session):
    """测试平台 Agent API 接口调用。"""
    from unittest.mock import patch
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1 import platform
    from app.db.session import get_db
    from app.skills import bootstrap_service

    bootstrap_service.bootstrap_defaults(db_session)

    def _override_db():
        yield db_session

    mini_app = FastAPI()
    mini_app.include_router(platform.router, prefix="/api/v1")
    mini_app.dependency_overrides[get_db] = _override_db
    client = TestClient(mini_app)

    # 1. 查询所有 Agent
    res = client.get("/api/v1/platform/agents")
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) >= 14

    # 2. 查询单个 Agent
    res_single = client.get("/api/v1/platform/agents/storyboard_director")
    assert res_single.status_code == 200
    assert res_single.json()["data"]["agent_name"] == "storyboard_director"

    # 3. 模拟调用单 Agent
    with patch("app.services.aiClient.generate_text", return_value='{"storyboards": [{"title": "镜头1", "duration": 3.0}]}'):
        res_exec = client.post(
            "/api/v1/platform/agents/storyboard_director/execute",
            json={
                "input_payload": {"user_request": "生成第1集分镜", "episode_outline": "陆沉出场"},
                "options": {"model": "mock-text"},
            },
        )
        assert res_exec.status_code == 200
        result_data = res_exec.json()["data"]
        assert "agent_run_id" in result_data
        assert result_data["parsed_output"]["storyboards"][0]["title"] == "镜头1"


def test_human_in_the_loop_blocking_and_approval(db_session):
    """测试 Human-in-the-loop 审核阻断与人工审批放行全流程。"""
    from app.skills import bootstrap_service
    from app.workflows import executor, run_service

    bootstrap_service.bootstrap_defaults(db_session)

    # 1. 创建原创剧本工作流
    wf = run_service.create_workflow_run(
        db_session,
        {
            "type": "original_script",
            "user_request": "写一部赘婿反转短剧",
            "input_payload": {"title": "狂龙出渊"},
        },
    )
    wf_id = wf["id"]

    # 2. 推进第 1 步需求分析（无需审批，直接完成）
    step1_res = executor.execute_step(db_session, None, wf_id, "requirement_analysis")
    assert step1_res["status"] == "completed"

    # 3. 推进第 2 步整剧 Bible 生成（关键节点，默认 requires_approval: True）
    step2_res = executor.execute_step(db_session, None, wf_id, "drama_bible_generation")
    assert step2_res["status"] == "waiting_approval"

    # 4. 验证任务图整体状态被正确阻断挂起
    exec_state = run_service.get_workflow_execution_state(db_session, wf_id)
    assert len(exec_state["waiting_approval_steps"]) == 1
    assert exec_state["waiting_approval_steps"][0]["step_key"] == "drama_bible_generation"
    assert exec_state["workflow"]["status"] == "waiting_approval"

    # 5. 自动推进尝试：被 waiting_approval 拦截，下游步骤不可运行
    auto_res = executor.run_until_blocked(db_session, None, wf_id)
    assert auto_res["status"] == "waiting_approval"

    # 6. 人工审批放行并提交修正数据
    approval_res = run_service.approve_workflow_step(
        db_session,
        wf_id,
        "drama_bible_generation",
        approver="导演张三",
        feedback="设定很好，增强主角初期隐忍感",
        modified_output={"bible_version": "v1.1", "approved_premise": "龙王隐姓埋名入赘"},
    )
    assert approval_res["status"] == "approved"
    assert approval_res["step"]["status"] == "completed"
    assert approval_res["step"]["output_payload"]["approval_info"]["approver"] == "导演张三"
    assert approval_res["step"]["output_payload"]["approved_premise"] == "龙王隐姓埋名入赘"

    # 7. 审批后下游步骤（分集大纲）自动解除阻塞并就绪
    next_step = approval_res["next_step"]
    assert next_step is not None
    assert next_step["step_key"] == "episode_outline_generation"


def test_human_in_the_loop_rejection_and_feedback_propagation(db_session):
    """测试 Human-in-the-loop 人工驳回与反馈传递重新执行机制。"""
    from app.skills import bootstrap_service
    from app.workflows import executor, run_service

    bootstrap_service.bootstrap_defaults(db_session)

    # 1. 创建工作流并推进到审核节点
    wf = run_service.create_workflow_run(
        db_session,
        {
            "type": "original_script",
            "user_request": "写一部都市商战短剧",
        },
    )
    wf_id = wf["id"]
    executor.execute_step(db_session, None, wf_id, "requirement_analysis")
    executor.execute_step(db_session, None, wf_id, "drama_bible_generation")

    # 2. 人工驳回该步骤
    reject_res = run_service.reject_workflow_step(
        db_session,
        wf_id,
        "drama_bible_generation",
        rejector="总编剧李四",
        reason="反派动机不够充分，需增加家族世仇背景",
        action="retry",
    )
    assert reject_res["status"] == "rejected"
    assert reject_res["action"] == "retry"
    assert reject_res["step"]["status"] == "pending"
    assert reject_res["step"]["retry_count"] >= 1
    assert "反派动机不够充分" in reject_res["step"]["input_payload"]["rejection_feedback"]

    # 3. 验证驳回后工作流整体恢复为 processing 准备重跑
    updated_wf = run_service.get_workflow_run(db_session, wf_id, include_steps=False)
    assert updated_wf["status"] == "processing"


def test_human_in_the_loop_http_api(db_session):
    """测试 Human-in-the-loop 审批与驳回 HTTP 路由端点。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1 import platform
    from app.db.session import get_db
    from app.skills import bootstrap_service
    from app.workflows import executor, run_service

    bootstrap_service.bootstrap_defaults(db_session)

    def _override_db():
        yield db_session

    mini_app = FastAPI()
    mini_app.include_router(platform.router, prefix="/api/v1")
    mini_app.dependency_overrides[get_db] = _override_db
    client = TestClient(mini_app)

    # 1. 创建工作流并执行到审批阻断点
    wf = run_service.create_workflow_run(
        db_session,
        {"type": "original_script", "user_request": "战神短剧"},
    )
    wf_id = wf["id"]
    executor.execute_step(db_session, None, wf_id, "requirement_analysis")
    executor.execute_step(db_session, None, wf_id, "drama_bible_generation")

    # 2. 调用审批 API
    res_approve = client.post(
        f"/api/v1/platform/workflows/{wf_id}/steps/drama_bible_generation/approve",
        json={
            "approver": "审核员小王",
            "feedback": "通过审核，准予进入分集大纲创作",
            "modified_output": {"note": "符合投放标准"},
        },
    )
    assert res_approve.status_code == 200
    data = res_approve.json()["data"]
    assert data["status"] == "approved"
    assert data["step"]["status"] == "completed"

    # 3. 推进下一步并测试驳回 API
    executor.execute_step(db_session, None, wf_id, "episode_outline_generation")
    executor.execute_step(db_session, None, wf_id, "episode_script_generation")

    res_reject = client.post(
        f"/api/v1/platform/workflows/{wf_id}/steps/episode_script_generation/reject",
        json={
            "rejector": "制片人",
            "reason": "第1集末尾高潮悬念不足",
            "action": "retry",
        },
    )
    assert res_reject.status_code == 200
    reject_data = res_reject.json()["data"]
    assert reject_data["status"] == "rejected"
    assert reject_data["step"]["status"] == "pending"



