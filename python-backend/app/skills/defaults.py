"""默认 Skill 与 Prompt 种子数据。

这些数据是 Multi-Agent 工作流的初始能力目录。后续可以在后台管理页中编辑、
发布新版本或替换为更细分的行业 Prompt。
"""
from __future__ import annotations

from typing import Any


DEFAULT_SKILLS: tuple[dict[str, Any], ...] = (
    {
        "skill_key": "script_requirement_analysis",
        "name": "短剧需求分析",
        "domain": "script",
        "description": "分析原创剧本的题材、受众、集数、冲突密度、付费卡点和限制条件。",
        "prompt_keys": ["script.requirement.analysis"],
    },
    {
        "skill_key": "drama_bible_generation",
        "name": "整剧 Bible 生成",
        "domain": "script",
        "description": "生成整剧设定、世界观、人物关系、视觉声音基调和分集规划。",
        "prompt_keys": ["script.drama_bible"],
    },
    {
        "skill_key": "episode_script_writing",
        "name": "单集剧本写作",
        "domain": "script",
        "description": "根据整剧设定或小说改编策略生成单集短剧剧本。",
        "prompt_keys": ["script.episode.write"],
    },
    {
        "skill_key": "novel_to_script_adaptation",
        "name": "小说短剧化改编",
        "domain": "novel",
        "description": "提炼小说主线、保留名场面、压缩旁支并生成短剧改编策略。",
        "prompt_keys": ["novel.adaptation.plan"],
    },
    {
        "skill_key": "character_extraction",
        "name": "角色提取",
        "domain": "entity",
        "description": "从剧本中提取角色、人设、外貌、关系、声音建议和视觉锚点。",
        "prompt_keys": ["entity.character.extract"],
    },
    {
        "skill_key": "scene_extraction",
        "name": "场景提取",
        "domain": "entity",
        "description": "从剧本中提取场景地点、时间、氛围和背景图提示词。",
        "prompt_keys": ["entity.scene.extract"],
    },
    {
        "skill_key": "prop_extraction",
        "name": "道具提取",
        "domain": "entity",
        "description": "从剧本中提取关键道具、剧情功能和资产级提示词。",
        "prompt_keys": ["entity.prop.extract"],
    },
    {
        "skill_key": "storyboard_generation",
        "name": "分镜生成",
        "domain": "storyboard",
        "description": "把单集剧本拆成分镜脚本，包含景别、运镜、动作、对白和时长。",
        "prompt_keys": ["storyboard.generate"],
    },
    {
        "skill_key": "frame_prompt_generation",
        "name": "帧提示词生成",
        "domain": "visual",
        "description": "生成首帧、关键帧、尾帧或分镜板组合提示词。",
        "prompt_keys": ["visual.frame_prompt"],
    },
    {
        "skill_key": "video_prompt_generation",
        "name": "图生视频提示词生成",
        "domain": "video",
        "description": "生成图生视频动作、镜头运动、节奏和首尾帧变化描述。",
        "prompt_keys": ["video.prompt"],
    },
    {
        "skill_key": "voice_profile_generation",
        "name": "角色声音档案生成",
        "domain": "audio",
        "description": "根据角色人设生成跨集一致的声音提示词和 TTS 参数。",
        "prompt_keys": ["audio.voice_profile"],
    },
    {
        "skill_key": "music_bible_generation",
        "name": "整剧音乐 Bible 生成",
        "domain": "audio",
        "description": "生成整剧配乐风格、配器、BPM、情绪谱和混音规则。",
        "prompt_keys": ["audio.music_bible"],
    },
    {
        "skill_key": "creative_quality_review",
        "name": "创作质量检查",
        "domain": "qa",
        "description": "检查剧本、实体、分镜、视听提示词的一致性、完整性和风险。",
        "prompt_keys": ["qa.creative_review"],
    },
)


DEFAULT_PROMPTS: tuple[dict[str, Any], ...] = (
    {
        "prompt_key": "script.requirement.analysis",
        "agent_name": "requirement",
        "skill_key": "script_requirement_analysis",
        "template": (
            "你是短剧制片策划，请分析以下原创剧本需求。\n"
            "需求：{user_request}\n"
            "请输出 JSON，包含 genre、target_audience、episode_count、episode_duration_seconds、"
            "core_hook、main_conflict、paywall_strategy、taboos、visual_style、audio_style。"
        ),
    },
    {
        "prompt_key": "script.drama_bible",
        "agent_name": "script_writer",
        "skill_key": "drama_bible_generation",
        "template": (
            "你是短剧总编剧。请基于需求和上下文生成整剧 Bible。\n"
            "需求：{user_request}\n上下文：{context}\n"
            "输出 JSON，字段包含 title、genre、logline、synopsis、worldview_rules、"
            "character_relationships、visual_tone、sound_tone、music_direction、episode_outlines。"
        ),
    },
    {
        "prompt_key": "script.episode.write",
        "agent_name": "script_writer",
        "skill_key": "episode_script_writing",
        "template": (
            "你是短剧编剧，请写单集剧本。\n"
            "整剧设定：{drama_bible}\n本集要求：{episode_outline}\n长期记忆：{memory}\n"
            "必须包含 opening_hook、scenes、dialogue_list、climax_reversal、ending_cliffhanger。"
        ),
    },
    {
        "prompt_key": "novel.adaptation.plan",
        "agent_name": "novel_adapter",
        "skill_key": "novel_to_script_adaptation",
        "template": (
            "你是小说短剧化改编策划。请根据小说章节摘要和长期记忆生成改编策略。\n"
            "小说：{novel_title}\n章节摘要：{chapter_summaries}\n核心记忆：{memory}\n"
            "输出 JSON，包含 keep、remove、merge、modify、amplify、episode_mapping、risk_notes。"
        ),
    },
    {
        "prompt_key": "entity.character.extract",
        "agent_name": "character",
        "skill_key": "character_extraction",
        "template": "从剧本中提取角色档案，必须输出 JSON 数组。剧本：{script_content}",
    },
    {
        "prompt_key": "entity.scene.extract",
        "agent_name": "scene",
        "skill_key": "scene_extraction",
        "template": "从剧本中提取唯一场景，输出 JSON 数组，场景提示词必须是纯背景。剧本：{script_content}",
    },
    {
        "prompt_key": "entity.prop.extract",
        "agent_name": "prop",
        "skill_key": "prop_extraction",
        "template": "从剧本中提取关键道具，输出 JSON 数组，道具图提示词不得包含人物和剧情专名。剧本：{script_content}",
    },
    {
        "prompt_key": "storyboard.generate",
        "agent_name": "storyboard_director",
        "skill_key": "storyboard_generation",
        "template": (
            "你是分镜导演。请将剧本拆成短视频分镜。\n剧本：{script_content}\n"
            "角色：{characters}\n场景：{scenes}\n道具：{props}\n"
            "输出 JSON，包含 shot_number、title、shot_type、angle、movement、action、dialogue、duration、image_prompt、video_prompt。"
        ),
    },
    {
        "prompt_key": "visual.frame_prompt",
        "agent_name": "visual_director",
        "skill_key": "frame_prompt_generation",
        "template": "根据分镜生成 {frame_type} 帧图像提示词。分镜：{storyboard}\n角色锚点：{characters}\n场景：{scene}",
    },
    {
        "prompt_key": "video.prompt",
        "agent_name": "video_director",
        "skill_key": "video_prompt_generation",
        "template": "根据分镜和首尾帧生成图生视频提示词。分镜：{storyboard}\n视觉提示词：{visual_prompt}",
    },
    {
        "prompt_key": "audio.voice_profile",
        "agent_name": "voice",
        "skill_key": "voice_profile_generation",
        "template": "根据角色人设生成声音档案。角色：{character}\n整剧声音基调：{sound_tone}",
    },
    {
        "prompt_key": "audio.music_bible",
        "agent_name": "music_director",
        "skill_key": "music_bible_generation",
        "template": "生成整剧音乐 Bible。剧名：{title}\n题材：{genre}\n剧情基调：{synopsis}",
    },
    {
        "prompt_key": "qa.creative_review",
        "agent_name": "qa",
        "skill_key": "creative_quality_review",
        "template": (
            "你是短剧生产 QA，请检查以下产物的一致性、完整性和风险。\n"
            "上下文：{context}\n输出 JSON，包含 issues、missing_fields、continuity_risks、cost_risks、suggestions。"
        ),
    },
)
