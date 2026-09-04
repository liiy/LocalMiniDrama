"""/api/v1/settings/prompts — 契约精确翻译 backend-node/src/routes/promptOverrides.js。

行为要点（与 Node 逐条对齐）：
- GET    /settings/prompts        → 9 条 { key,label,description,default_body,locked_suffix,current_body,is_customized }
- PUT    /settings/prompts/:key   → 400 '未知的提示词 key: X' | 400 'content 不能为空' | { ok, key }
- DELETE /settings/prompts/:key   → 400 '未知的提示词 key: X' | { ok, key }
- default_body / locked_suffix 从 promptI18n 静态表动态读取（与 Node 一致）
- 更新/重置同时同步 promptI18n 内存覆盖缓存
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import bad_request, success
from app.db.session import get_db
from app.services import promptI18n
from app.services import promptOverridesService as svc

router = APIRouter(tags=["promptOverrides"])
log = get_logger("lmd.prompts")

# 与 Node routes/promptOverrides.js 的 PROMPT_META 完全一致
PROMPT_META = [
    {"key": "story_expansion_system", "label": "故事生成提示词", "description": "控制 AI 如何将故事梗概扩写成完整剧本"},
    {
        "key": "storyboard_system",
        "label": "分镜拆解提示词",
        "description": "控制 AI 如何将剧本拆分成分镜头方案（输出格式要求已锁定）",
    },
    {
        "key": "character_extraction",
        "label": "角色提取提示词",
        "description": "控制 AI 如何从剧本中提取角色信息（输出格式要求已锁定）",
    },
    {
        "key": "scene_extraction",
        "label": "场景提取提示词",
        "description": "控制 AI 如何从剧本中提取场景背景（风格/比例和输出格式已锁定）",
    },
    {
        "key": "prop_extraction",
        "label": "道具提取提示词",
        "description": "控制 AI 如何从剧本中提取关键道具（风格/比例和输出格式已锁定）",
    },
    {
        "key": "storyboard_user_suffix",
        "label": "分镜输出格式要求",
        "description": "追加在分镜拆解用户提示词末尾的详细要素说明（JSON 输出格式已锁定）",
    },
    {
        "key": "first_frame_prompt",
        "label": "首帧图像提示词",
        "description": "控制 AI 如何生成分镜首帧（动作前静态画面）的图像提示词（风格/比例和 JSON 格式已锁定）",
    },
    {
        "key": "key_frame_prompt",
        "label": "关键帧图像提示词",
        "description": "控制 AI 如何生成分镜关键帧（动作高潮瞬间）的图像提示词（风格/比例和 JSON 格式已锁定）",
    },
    {
        "key": "last_frame_prompt",
        "label": "尾帧图像提示词",
        "description": "控制 AI 如何生成分镜尾帧（动作后静态画面）的图像提示词（风格/比例和 JSON 格式已锁定）",
    },
]

VALID_KEYS = {m["key"] for m in PROMPT_META}


def get_prompt_definitions() -> list[dict]:
    """等价 Node getPromptDefinitions()：元数据 + promptI18n 动态正文/锁定后缀。"""
    return [
        {
            **m,
            "default_body": promptI18n.get_default_prompt_body(m["key"]),
            "locked_suffix": promptI18n.get_locked_suffix(m["key"]),
        }
        for m in PROMPT_META
    ]


@router.get("/settings/prompts")
def list_prompts(db: Session = Depends(get_db)) -> dict:
    defs = get_prompt_definitions()
    override_map = {o["key"]: o["content"] for o in svc.list_overrides(db)}
    prompts = [
        {
            "key": d["key"],
            "label": d["label"],
            "description": d["description"],
            "default_body": d["default_body"],
            "locked_suffix": d["locked_suffix"],
            "current_body": override_map.get(d["key"]) or None,
            "is_customized": bool(override_map.get(d["key"])),
        }
        for d in defs
    ]
    return success({"prompts": prompts})


@router.put("/settings/prompts/{key}")
def update_prompt(key: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    if key not in VALID_KEYS:
        raise bad_request(f"未知的提示词 key: {key}")
    content = payload.get("content")
    if not content:
        raise bad_request("content 不能为空")
    trimmed = content.strip()  # 非字符串时抛 AttributeError → 500，与 Node TypeError 等价
    if not trimmed:
        raise bad_request("content 不能为空")
    svc.set_override(db, key, trimmed)
    promptI18n.set_override_in_memory(key, trimmed)
    log.info("prompt override updated", extra={"key": key})
    return success({"ok": True, "key": key})


@router.delete("/settings/prompts/{key}")
def reset_prompt(key: str, db: Session = Depends(get_db)) -> dict:
    if key not in VALID_KEYS:
        raise bad_request(f"未知的提示词 key: {key}")
    svc.delete_override(db, key)
    promptI18n.clear_override_in_memory(key)
    log.info("prompt override reset", extra={"key": key})
    return success({"ok": True, "key": key})
