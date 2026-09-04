"""工作流蓝图定义。

蓝图描述“应该有哪些步骤、由哪个 Agent 负责、默认使用哪个 Skill”。它不直接调用 AI，
只提供稳定的编排骨架；后续接 LangGraph/Dramatiq 时可以直接复用这些 step_key。
"""
from __future__ import annotations

from typing import Any


COMMON_DOWNSTREAM_STEPS: tuple[dict[str, Any], ...] = (
    {
        "step_key": "continuity_check",
        "agent_name": "continuity",
        "skill_key": "continuity_check",
        "title": "连续性检查",
    },
    {
        "step_key": "character_extraction",
        "agent_name": "character",
        "skill_key": "character_extraction",
        "title": "提取角色",
    },
    {
        "step_key": "scene_extraction",
        "agent_name": "scene",
        "skill_key": "scene_extraction",
        "title": "提取场景",
    },
    {
        "step_key": "prop_extraction",
        "agent_name": "prop",
        "skill_key": "prop_extraction",
        "title": "提取道具",
    },
    {
        "step_key": "visual_prompt_generation",
        "agent_name": "visual_director",
        "skill_key": "visual_prompt_generation",
        "title": "生成文生图提示词",
    },
    {
        "step_key": "storyboard_generation",
        "agent_name": "storyboard_director",
        "skill_key": "storyboard_generation",
        "title": "生成分镜脚本",
    },
    {
        "step_key": "frame_prompt_generation",
        "agent_name": "visual_director",
        "skill_key": "frame_prompt_generation",
        "title": "生成首帧/关键帧/尾帧提示词",
    },
    {
        "step_key": "video_prompt_generation",
        "agent_name": "video_director",
        "skill_key": "video_prompt_generation",
        "title": "生成图生视频提示词",
    },
    {
        "step_key": "voice_music_generation",
        "agent_name": "voice",
        "skill_key": "voice_profile_generation",
        "title": "生成角色声音与整剧音乐设定",
    },
    {
        "step_key": "creative_quality_review",
        "agent_name": "qa",
        "skill_key": "creative_quality_review",
        "title": "质量检查",
    },
)


WORKFLOW_BLUEPRINTS: dict[str, tuple[dict[str, Any], ...]] = {
    "original_script": (
        {
            "step_key": "requirement_analysis",
            "agent_name": "requirement",
            "skill_key": "script_requirement_analysis",
            "title": "分析原创剧本需求",
        },
        {
            "step_key": "drama_bible_generation",
            "agent_name": "script_writer",
            "skill_key": "drama_bible_generation",
            "title": "生成整剧 Bible",
        },
        {
            "step_key": "episode_outline_generation",
            "agent_name": "script_writer",
            "skill_key": "episode_outline_generation",
            "title": "生成分集大纲",
        },
        {
            "step_key": "episode_script_generation",
            "agent_name": "script_writer",
            "skill_key": "episode_script_writing",
            "title": "生成单集剧本",
        },
        *COMMON_DOWNSTREAM_STEPS,
    ),
    "novel_adaptation": (
        {
            "step_key": "novel_ingestion",
            "agent_name": "novel_adapter",
            "skill_key": "novel_ingestion",
            "title": "导入并清洗小说",
        },
        {
            "step_key": "chapter_slicing",
            "agent_name": "novel_adapter",
            "skill_key": "chapter_slicing",
            "title": "章节切片",
        },
        {
            "step_key": "long_memory_indexing",
            "agent_name": "novel_adapter",
            "skill_key": "long_memory_indexing",
            "title": "写入长期记忆",
        },
        {
            "step_key": "novel_bible_extraction",
            "agent_name": "novel_adapter",
            "skill_key": "novel_bible_extraction",
            "title": "提取原著设定",
        },
        {
            "step_key": "adaptation_plan_generation",
            "agent_name": "novel_adapter",
            "skill_key": "novel_to_script_adaptation",
            "title": "生成短剧改编策略",
        },
        {
            "step_key": "episode_script_generation",
            "agent_name": "script_writer",
            "skill_key": "episode_script_writing",
            "title": "生成改编单集剧本",
        },
        *COMMON_DOWNSTREAM_STEPS,
    ),
    "entity_extraction": COMMON_DOWNSTREAM_STEPS[:4],
    "storyboard_generation": COMMON_DOWNSTREAM_STEPS[5:8],
    "voice_music_generation": COMMON_DOWNSTREAM_STEPS[8:9],
    "video_production": COMMON_DOWNSTREAM_STEPS[7:],
}


WORKFLOW_STEP_DEPENDENCIES: dict[str, dict[str, list[str]]] = {
    # 原创剧本：需求越重，越需要前置 Bible 和分集大纲稳定后再写单集剧本。
    "original_script": {
        "drama_bible_generation": ["requirement_analysis"],
        "episode_outline_generation": ["drama_bible_generation"],
        "episode_script_generation": ["episode_outline_generation"],
    },
    # 小说改编：先清洗原文、切章节、写长期记忆，再做改编策略和单集剧本。
    "novel_adaptation": {
        "chapter_slicing": ["novel_ingestion"],
        "long_memory_indexing": ["chapter_slicing"],
        "novel_bible_extraction": ["long_memory_indexing"],
        "adaptation_plan_generation": ["novel_bible_extraction"],
        "episode_script_generation": ["adaptation_plan_generation"],
    },
}

COMMON_STEP_DEPENDENCIES: dict[str, list[str]] = {
    # 角色/场景/道具提取依赖剧本稳定，可在连续性检查后并行执行。
    "continuity_check": ["episode_script_generation"],
    "character_extraction": ["continuity_check"],
    "scene_extraction": ["continuity_check"],
    "prop_extraction": ["continuity_check"],
    "visual_prompt_generation": ["character_extraction", "scene_extraction", "prop_extraction"],
    "storyboard_generation": ["visual_prompt_generation"],
    "frame_prompt_generation": ["storyboard_generation"],
    "video_prompt_generation": ["frame_prompt_generation"],
    "voice_music_generation": ["storyboard_generation"],
    "creative_quality_review": ["video_prompt_generation", "voice_music_generation"],
}


def _attach_dependencies(workflow_type: str, steps: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    specific = WORKFLOW_STEP_DEPENDENCIES.get(workflow_type, {})
    result: list[dict[str, Any]] = []
    for step in steps:
        item = dict(step)
        step_key = str(item.get("step_key") or "")
        depends_on = item.get("depends_on") or specific.get(step_key) or COMMON_STEP_DEPENDENCIES.get(step_key)
        if depends_on:
            item["depends_on"] = list(depends_on)
        result.append(item)
    return result


def list_workflow_blueprints() -> list[dict[str, Any]]:
    return [
        {"type": workflow_type, "steps": _attach_dependencies(workflow_type, steps), "step_count": len(steps)}
        for workflow_type, steps in WORKFLOW_BLUEPRINTS.items()
    ]


def get_workflow_blueprint(workflow_type: str) -> list[dict[str, Any]]:
    return _attach_dependencies(workflow_type, WORKFLOW_BLUEPRINTS.get(workflow_type, ()))
