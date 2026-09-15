"""工业化工作流 LLM 调度与防御性 JSON 解析工具 (LLM Bridge)。"""
from __future__ import annotations

import os
import json
import logging
from typing import Any, Callable

from app.core.logger import get_logger
from app.db.session import session_scope
from app.schemas.parser import extract_first_json_payload
from app.services import aiClient

logger = get_logger("lmd.llm_bridge")


def call_llm_json(
    user_prompt: str,
    system_prompt: str = "",
    *,
    fallback_factory: Callable[[], dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一向 LLM 发送请求并解析首个有效 JSON 结构体。

    防御式设计：
    1. 优先调用系统配置的 text 模型；
    2. 若未配置模型、超时、报错或返回非合法 JSON，则触发 fallback_factory；
    3. 杜绝因大模型输出额外自然语言说明导致整个流水线崩溃。
    """
    options = options or {}
    options.setdefault("temperature", 0.7)
    options.setdefault("json_mode", True)

    if os.environ.get("LMD_FAST_TEST") == "1" and fallback_factory is not None:
        return fallback_factory()

    try:
        with session_scope() as db:
            raw_output = aiClient.generate_text(
                db,
                logger,
                service_type="text",
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                options=options,
            )
            if raw_output and raw_output.strip():
                parsed = extract_first_json_payload(raw_output)
                if isinstance(parsed, dict) and parsed:
                    return parsed
    except Exception as exc:
        logger.warning("call_llm_json 调用外部模型失败或未配置，触发降级自愈: %s", exc)

    if fallback_factory is not None:
        return fallback_factory()
    return {}
