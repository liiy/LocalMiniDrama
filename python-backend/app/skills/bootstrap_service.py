"""Skill/Prompt 默认数据初始化服务。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.prompts import registry_service as prompt_registry
from app.skills import registry_service as skill_registry
from app.skills.defaults import DEFAULT_PROMPTS, DEFAULT_SKILLS


def bootstrap_defaults(db: Session, *, status: str = "active") -> dict[str, Any]:
    """幂等写入默认 Skill 与 Prompt。

    默认数据只提供平台可运行的“起始版本”，不会覆盖后续通过管理后台发布的新版本。
    当前固定 version=1；如果要升级默认 Prompt，应新增 version=2 并由用户主动切换。
    """
    skills = []
    prompts = []

    for skill in DEFAULT_SKILLS:
        prompt_keys = skill.get("prompt_keys") or []
        skills.append(
            skill_registry.upsert_skill(
                db,
                {
                    **skill,
                    "version": 1,
                    "status": status,
                    "prompt_keys": prompt_keys,
                    "context_policy": {
                        "include_drama": True,
                        "include_episode": True,
                        "include_entities": True,
                        "include_memory": True,
                    },
                    "model_policy": {
                        "service_type": "text",
                        "temperature": 0.7,
                        "json_mode": True,
                    },
                    "quality_checks": {
                        "require_json": True,
                        "require_chinese_for_zh_project": True,
                    },
                },
            )
        )

    for prompt in DEFAULT_PROMPTS:
        # Prompt 与 Skill 分开写入，后续允许同一个 Skill 切换不同 Prompt 版本。
        prompts.append(
            prompt_registry.create_prompt_template(
                db,
                {
                    **prompt,
                    "version": 1,
                    "status": status,
                    "locale": "zh",
                    "model_family": "openai-compatible",
                    "input_schema": {},
                    "output_schema": {},
                    "tags": ["default", "multi-agent", prompt.get("skill_key")],
                },
            )
        )

    return {
        "skill_count": len(skills),
        "prompt_count": len(prompts),
        "skills": skills,
        "prompts": prompts,
    }
