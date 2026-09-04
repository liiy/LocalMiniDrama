"""小说/长文章节导入服务
功能：上传 txt 内容 → 识别章节分割 → 自动填充各集剧本
对照 Node 版 backend-node/src/services/novelImportService.js 1:1 实现。
"""
from __future__ import annotations

import re
from typing import Any

from app.core.logger import get_logger
from app.services import aiClient

log = get_logger("lmd.novelImportService")

CHAPTER_PATTERNS = [
    re.compile(r"^第[零一二三四五六七八九十百千\d]+章"),
    re.compile(r"^第[零一二三四五六七八九十百千\d]+节"),
    re.compile(r"^Chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^CHAPTER\s+\d+"),
    re.compile(r"^\d+[\.、]\s*.{2,20}$"),
    re.compile(r"^【.{1,30}】$"),
    re.compile(r"^「.{1,30}」$"),
]


def detect_chapters_by_rules(text: str) -> list[dict[str, str]]:
    """简单的章节检测（不调用 AI，基于规则）
    识别常见章节标题格式
    """
    lines = re.split(r"\r?\n", text)
    chapters: list[dict[str, str]] = []
    current_start = 0
    current_title = "序章"

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        is_chapter = any(p.search(line) for p in CHAPTER_PATTERNS)
        if is_chapter:
            if i > current_start:
                content = "\n".join(lines[current_start:i]).strip()
                if len(content) > 20:
                    chapters.append({"title": current_title, "content": content})
            current_title = line
            current_start = i + 1

    # 最后一章
    last_content = "\n".join(lines[current_start:]).strip()
    if len(last_content) > 20:
        chapters.append({"title": current_title, "content": last_content})

    return chapters


def summarize_chapter_to_script(
    db: Any, logger: Any, chapter_title: str, chapter_content: str, drama_title: str | None = None
) -> str:
    """用 AI 将章节内容摘要为剧本形式"""
    max_len = 2000
    truncated = chapter_content[:max_len] + "..." if len(chapter_content) > max_len else chapter_content
    user_prompt = f"""小说名称：{drama_title or '未知'}
章节标题：{chapter_title}

章节原文（部分）：
{truncated}

请将上述章节内容改写为短剧剧本格式，包含：场景描述、角色对话、动作说明。输出为中文纯文本，不需要 JSON 格式，长度200-500字。"""

    try:
        result = aiClient.generate_text(
            db,
            logger,
            "text",
            user_prompt,
            "",
            {
                "scene_key": "novel_import",
                "max_tokens": 800,
                "temperature": 0.7,
            },
        )
        return result or chapter_content[:500]
    except Exception as err:
        logger.warning("[小说导入] AI改写章节失败，使用原文截断", {"error": str(err)})
        return chapter_content[:500]


def import_novel(
    db: Any,
    logger: Any,
    *,
    text: str,
    title: str = "",
    max_chapters: int = 20,
    ai_summarize: bool = False,
) -> dict[str, Any]:
    """主入口：解析小说文本，返回章节列表
    @returns dict(chapters=list[dict(index, title, content, script)], total=int)
    """
    if not text or not text.strip():
        raise ValueError("小说内容不能为空")

    chapters = detect_chapters_by_rules(text)
    if not chapters:
        # 没有检测到章节，整个文本作为一章
        chapters.append({"title": title or "第一集", "content": text.strip()})

    limit = min(max_chapters or 20, len(chapters))
    result = []

    for i in range(limit):
        ch = chapters[i]
        script = ch["content"]
        if ai_summarize:
            script = summarize_chapter_to_script(db, logger, ch["title"], ch["content"], title)
        result.append({
            "index": i + 1,
            "title": ch["title"],
            "content": ch["content"][:300],
            "script": script,
        })

    return {"chapters": result, "total": len(chapters)}
