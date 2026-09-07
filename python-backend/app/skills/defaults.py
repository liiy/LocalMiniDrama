"""默认 Skill 与 Prompt 种子数据。

这些数据是 Multi-Agent 工作流的初始能力目录。后续可以在后台管理页中编辑、
发布新版本或替换为更细分的行业 Prompt。
"""
from __future__ import annotations

from typing import Any


DEFAULT_SKILLS: tuple[dict[str, Any], ...] = (
    {
        "skill_key": "novel_ingestion",
        "name": "小说导入清洗",
        "domain": "novel",
        "description": "识别小说正文结构、清理噪声并保留原文证据位置。",
        "prompt_keys": ["novel.ingestion"],
    },
    {
        "skill_key": "chapter_slicing",
        "name": "小说章节语义切片",
        "domain": "novel",
        "description": "按章节和语义边界生成带重叠上下文的可检索切片。",
        "prompt_keys": ["novel.chapter_slicing"],
    },
    {
        "skill_key": "long_memory_indexing",
        "name": "长期记忆提炼索引",
        "domain": "memory",
        "description": "从小说切片提炼事实、关系、时间线和伏笔并写入长期记忆。",
        "prompt_keys": ["memory.long_term_indexing"],
    },
    {
        "skill_key": "novel_bible_extraction",
        "name": "原著 Bible 提取",
        "domain": "novel",
        "description": "提取原著世界观、人物弧线、关系、时间线和不可改动事实。",
        "prompt_keys": ["novel.bible_extraction"],
    },
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
        "skill_key": "episode_outline_generation",
        "name": "分集大纲生成",
        "domain": "script",
        "description": "基于整剧 Bible 规划每集冲突、反转、卡点和跨集承接。",
        "prompt_keys": ["script.episode_outline"],
    },
    {
        "skill_key": "continuity_check",
        "name": "跨集连续性检查",
        "domain": "quality",
        "description": "检查角色、人设、时间线、场景和伏笔是否冲突。",
        "prompt_keys": ["qa.continuity_check"],
    },
    {
        "skill_key": "visual_prompt_generation",
        "name": "实体视觉提示词生成",
        "domain": "visual",
        "description": "为角色、场景和道具生成统一风格且可复用的文生图提示词。",
        "prompt_keys": ["visual.entity_prompts"],
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
        "prompt_key": "novel.ingestion",
        "agent_name": "novel_adapter",
        "skill_key": "novel_ingestion",
        "template": "清洗并分析小说原文，保留章节边界与来源位置。输入：{user_request}\n上下文：{context}\n输出 JSON：cleaned_text、chapters、warnings。",
    },
    {
        "prompt_key": "novel.chapter_slicing",
        "agent_name": "novel_adapter",
        "skill_key": "chapter_slicing",
        "template": "把小说章节切为适合 RAG 的语义片段。上下文：{context}\n输出 JSON：slices，每项包含 title、content、summary、keywords、source_ref。",
    },
    {
        "prompt_key": "memory.long_term_indexing",
        "agent_name": "novel_adapter",
        "skill_key": "long_memory_indexing",
        "template": "从小说切片提炼长期事实。上下文：{context}\n输出 JSON：memory_items，每项包含 memory_type、title、content、summary、keywords、confidence。",
    },
    {
        "prompt_key": "novel.bible_extraction",
        "agent_name": "novel_adapter",
        "skill_key": "novel_bible_extraction",
        "template": "提取原著 Bible。上下文：{context}\n输出 JSON：worldview、characters、relationships、timeline、plot_constraints、foreshadowing。",
    },
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
        "prompt_key": "script.episode_outline",
        "agent_name": "script_writer",
        "skill_key": "episode_outline_generation",
        "template": "根据整剧 Bible 生成分集大纲。Bible：{drama_bible}\n需求：{user_request}\n输出 JSON：episode_outlines，每集包含 hook、conflict、turning_points、cliffhanger。",
    },
    {
        "prompt_key": "qa.continuity_check",
        "agent_name": "continuity",
        "skill_key": "continuity_check",
        "template": "检查剧本连续性。剧本：{script_content}\n长期记忆：{memory}\n角色：{characters}\n输出 JSON：score、conflicts、suggestions。",
    },
    {
        "prompt_key": "visual.entity_prompts",
        "agent_name": "visual_director",
        "skill_key": "visual_prompt_generation",
        "template": "为实体生成统一文生图提示词。角色：{characters}\n场景：{scenes}\n道具：{props}\n输出 JSON：character_prompts、scene_prompts、prop_prompts、negative_prompt。",
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
