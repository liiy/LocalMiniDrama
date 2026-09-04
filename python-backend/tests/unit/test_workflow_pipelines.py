"""单元测试：验证迭代 6 AI 原创剧本与小说改编两条端到端流水线结构与步骤汇聚。"""
from __future__ import annotations

from app.workflows.blueprints import COMMON_DOWNSTREAM_STEPS, WORKFLOW_BLUEPRINTS, get_workflow_blueprint
from app.workflows.run_service import VALID_WORKFLOW_TYPES


def test_workflow_types_and_blueprints_registration():
    """验证所有声明的 Workflow 类型均存在对应蓝图。"""
    for wf_type in VALID_WORKFLOW_TYPES:
        blueprint = get_workflow_blueprint(wf_type)
        assert blueprint is not None
        assert len(blueprint) >= 1


def test_original_script_pipeline_topology():
    """验证 AI 原创剧本流水线步骤拓扑。"""
    bp = get_workflow_blueprint("original_script")
    step_keys = [s["step_key"] for s in bp]

    # 原创剧本入口步骤
    assert step_keys[0] == "requirement_analysis"
    assert step_keys[1] == "drama_bible_generation"
    assert step_keys[2] == "episode_outline_generation"
    assert step_keys[3] == "episode_script_generation"

    # 下游通用资产生成步骤
    assert "character_extraction" in step_keys
    assert "scene_extraction" in step_keys
    assert "prop_extraction" in step_keys
    assert "storyboard_generation" in step_keys
    assert "frame_prompt_generation" in step_keys
    assert "video_prompt_generation" in step_keys
    assert "voice_music_generation" in step_keys
    assert "creative_quality_review" in step_keys


def test_novel_adaptation_pipeline_topology():
    """验证小说改编短剧流水线步骤拓扑。"""
    bp = get_workflow_blueprint("novel_adaptation")
    step_keys = [s["step_key"] for s in bp]

    # 小说改编入口步骤
    assert step_keys[0] == "novel_ingestion"
    assert step_keys[1] == "chapter_slicing"
    assert step_keys[2] == "long_memory_indexing"
    assert step_keys[3] == "novel_bible_extraction"
    assert step_keys[4] == "adaptation_plan_generation"
    assert step_keys[5] == "episode_script_generation"

    # 汇聚到相同下游资产步骤
    common_keys = [s["step_key"] for s in COMMON_DOWNSTREAM_STEPS]
    for ck in common_keys:
        assert ck in step_keys


def test_blueprint_step_keys_unique_per_workflow():
    """验证单条工作流内部 step_key 无重复。"""
    for wf_type, steps in WORKFLOW_BLUEPRINTS.items():
        keys = [s["step_key"] for s in steps]
        assert len(keys) == len(set(keys)), f"工作流 {wf_type} 存在重复的 step_key"
