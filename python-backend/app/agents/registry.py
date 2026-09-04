"""默认 Agent 清单。

这里先定义“受控多 Agent”的职责边界。真正执行模型调用时，每个 Agent 会通过
Skill Registry + Prompt Registry + Context Builder 获取能力、提示词和上下文。
"""
from __future__ import annotations

from typing import Any


DEFAULT_AGENTS: tuple[dict[str, Any], ...] = (
    {
        "agent_name": "producer",
        "display_name": "制片统筹 Agent",
        "responsibility": "拆解任务、推进工作流、判断是否需要人工审核",
        "default_skill_keys": ["workflow_supervision"],
    },
    {
        "agent_name": "requirement",
        "display_name": "需求分析 Agent",
        "responsibility": "分析 AI 原创剧本或小说改编的目标、限制、受众和商业节奏",
        "default_skill_keys": ["script_requirement_analysis"],
    },
    {
        "agent_name": "novel_adapter",
        "display_name": "小说改编 Agent",
        "responsibility": "解析章节、提炼原著设定、生成改编策略和分集承接方案",
        "default_skill_keys": ["novel_to_script_adaptation"],
    },
    {
        "agent_name": "script_writer",
        "display_name": "编剧 Agent",
        "responsibility": "生成整剧 Bible、分集大纲、单集剧本和短剧化爆点",
        "default_skill_keys": ["original_script_writing", "episode_script_writing"],
    },
    {
        "agent_name": "continuity",
        "display_name": "连续性检查 Agent",
        "responsibility": "检查人物关系、时间线、设定、口吻、跨集伏笔是否一致",
        "default_skill_keys": ["continuity_check"],
    },
    {
        "agent_name": "character",
        "display_name": "角色 Agent",
        "responsibility": "提取和补全角色人设、外貌锚点、阶段造型、声音建议",
        "default_skill_keys": ["character_extraction", "character_profile_enrichment"],
    },
    {
        "agent_name": "scene",
        "display_name": "场景 Agent",
        "responsibility": "提取场景空间、时间、光影氛围和背景图提示词",
        "default_skill_keys": ["scene_extraction", "scene_prompt_generation"],
    },
    {
        "agent_name": "prop",
        "display_name": "道具 Agent",
        "responsibility": "提取关键道具、剧情功能和资产级道具图提示词",
        "default_skill_keys": ["prop_extraction", "prop_prompt_generation"],
    },
    {
        "agent_name": "storyboard_director",
        "display_name": "分镜导演 Agent",
        "responsibility": "把剧本拆成分镜脚本、镜头景别、动作、对白和时长",
        "default_skill_keys": ["storyboard_generation"],
    },
    {
        "agent_name": "visual_director",
        "display_name": "视觉导演 Agent",
        "responsibility": "生成角色、场景、道具、首帧、关键帧和尾帧文生图提示词",
        "default_skill_keys": ["visual_prompt_generation", "frame_prompt_generation"],
    },
    {
        "agent_name": "video_director",
        "display_name": "视频导演 Agent",
        "responsibility": "生成图生视频提示词、运镜、动作强度、首尾帧动态描述",
        "default_skill_keys": ["video_prompt_generation"],
    },
    {
        "agent_name": "voice",
        "display_name": "声音 Agent",
        "responsibility": "根据角色人设生成声音档案、TTS 参数和台词情绪规则",
        "default_skill_keys": ["voice_profile_generation"],
    },
    {
        "agent_name": "music_director",
        "display_name": "音乐导演 Agent",
        "responsibility": "生成整剧 Music Bible、场景 BGM Cue 和关键音效提示",
        "default_skill_keys": ["music_bible_generation", "music_cue_generation"],
    },
    {
        "agent_name": "qa",
        "display_name": "质量检查 Agent",
        "responsibility": "检查结构完整性、一致性、缺失字段、成本风险和敏感内容",
        "default_skill_keys": ["creative_quality_review"],
    },
)


def list_agents() -> list[dict[str, Any]]:
    return [dict(agent) for agent in DEFAULT_AGENTS]


def get_agent(agent_name: str) -> dict[str, Any] | None:
    for agent in DEFAULT_AGENTS:
        if agent["agent_name"] == agent_name:
            return dict(agent)
    return None
