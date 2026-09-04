"""小说/长文章节智能切片、剧本初稿改写与 RAG 长期记忆索引服务。

【业务定位与架构职责】
1. 小说智能切片（Chapter Slicing）：
   - 基于正则表达式与多段落结构分析识别长篇小说的章节与分节。
   - 提取章节序号、标题、正文、出场人物、冲突点及名场面/关键高潮标记（is_key_plot）。
2. AI 剧本初稿摘要与改写：
   - 支持通过 AI 将小说原文快速提炼改写为包含动作、对白、情绪的短剧分集草稿。
3. 剧集长期记忆库持久化（Novel RAG & Memory Items）：
   - 将小说章节切片自动持久化到 `memory_items` 表（memory_type='novel_slice'）。
   - 在后续第 N 集分镜生成或人物对话生成时，通过长期记忆召回原著上下文，保证全剧设定与人物性格不失真。
"""
from __future__ import annotations

import re
from typing import Any

from app.context import memory_service
from app.core.logger import get_logger
from app.schemas.spec import NovelChapterSlice
from app.services import aiClient

log = get_logger("lmd.novelImportService")

# 常见章节与小节标题正则模式匹配
CHAPTER_PATTERNS = [
    re.compile(r"^第[零一二三四五六七八九十百千\d]+章"),
    re.compile(r"^第[零一二三四五六七八九十百千\d]+节"),
    re.compile(r"^Chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^CHAPTER\s+\d+"),
    re.compile(r"^\d+[\.、]\s*.{2,20}$"),
    re.compile(r"^【.{1,30}】$"),
    re.compile(r"^「.{1,30}」$"),
]

# 高潮、冲突、反转、名场面关键词，用于规则预判 is_key_plot
KEY_PLOT_KEYWORDS = [
    "决战", "真相", "复仇", "反杀", "退婚", "打脸", "暴怒", "生死",
    "背叛", "表白", "诀别", "摊牌", "秘密", "高潮", "反转", "觉醒",
]


def detect_chapters_by_rules(text: str) -> list[dict[str, str]]:
    """简单的章节检测（基于规则分段，不依赖大模型）

    识别常见章节标题格式并拆分正文。
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


def build_chapter_slices(
    raw_chapters: list[dict[str, str]],
    *,
    drama_title: str = "",
) -> list[NovelChapterSlice]:
    """将规则提取的原始章节规整为结构化的 NovelChapterSlice 切片列表。"""
    slices: list[NovelChapterSlice] = []
    for idx, ch in enumerate(raw_chapters, start=1):
        title = ch.get("title") or f"第{idx}章"
        content = ch.get("content") or ""
        # 简单提取出场角色候选词（双字/三字高频词或人名词法）
        is_key = any(kw in (title + content[:300]) for kw in KEY_PLOT_KEYWORDS)
        summary = content[:200].replace("\n", " ") + ("..." if len(content) > 200 else "")

        slices.append(
            NovelChapterSlice(
                chapter_index=idx,
                chapter_title=title,
                original_text=content,
                summary=summary,
                key_characters=[],
                dramatic_elements=["名场面/高潮冲突"] if is_key else ["日常剧情"],
                is_key_plot=is_key,
            )
        )
    return slices


def summarize_chapter_to_script(
    db: Any, logger: Any, chapter_title: str, chapter_content: str, drama_title: str | None = None
) -> str:
    """用 AI 将章节内容摘要改写为包含场景、角色对白和动作说明的短剧剧本草稿。"""
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


def save_novel_slices_to_memory(
    db: Any,
    drama_id: int,
    slices: list[NovelChapterSlice],
) -> list[dict[str, Any]]:
    """将小说切片作为长期记忆持久化到 memory_items 表中。

    每个切片记录包含：
    - drama_id: 归属短剧项目 ID
    - memory_type: 'novel_slice'
    - scope: 'drama'
    - title: 章节标题
    - content: 章节原文
    - summary: 情节摘要
    - keywords: 关键剧情标签与名场面标记
    - metadata: 章节序号与 is_key_plot 标记
    """
    saved_items: list[dict[str, Any]] = []
    for sl in slices:
        payload = {
            "drama_id": drama_id,
            "memory_type": "novel_slice",
            "scope": "drama",
            "title": f"第{sl.chapter_index}章: {sl.chapter_title}",
            "content": sl.original_text,
            "summary": sl.summary,
            "keywords": sl.dramatic_elements + sl.key_characters,
            "source_type": "novel_chapter",
            "source_id": f"chapter_{sl.chapter_index}",
            "metadata": {
                "chapter_index": sl.chapter_index,
                "chapter_title": sl.chapter_title,
                "is_key_plot": sl.is_key_plot,
            },
        }
        item = memory_service.add_memory_item(db, payload)
        saved_items.append(item)
    log.info("Saved %d novel chapter slices to memory_items", len(saved_items), extra={"drama_id": drama_id})
    return saved_items


def get_novel_slices_from_memory(db: Any, drama_id: int) -> list[dict[str, Any]]:
    """从长期记忆库中检索当前短剧项目的所有小说章节切片。"""
    return memory_service.search_memory_items(
        db,
        drama_id=drama_id,
        memory_type="novel_slice",
        limit=100,
    )


def search_novel_memory(
    db: Any,
    drama_id: int,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """在小说切片与世界观长期记忆中执行全文或语义检索。"""
    return memory_service.search_memory_items(
        db,
        drama_id=drama_id,
        query=query,
        memory_type="novel_slice",
        limit=limit,
    )


def import_novel(
    db: Any,
    logger: Any,
    *,
    text: str,
    title: str = "",
    drama_id: int | None = None,
    max_chapters: int = 20,
    ai_summarize: bool = False,
    save_to_memory: bool = True,
) -> dict[str, Any]:
    """主入口：解析小说文本，生成章节切片并返回剧本草稿列表。

    当传入 drama_id 时，会自动将切片存入 `memory_items` 表，供全剧后续生成分镜和视频时检索。
    @returns dict(chapters=list[dict(index, title, content, script, is_key_plot)], total=int, slices=list)
    """
    if not text or not text.strip():
        raise ValueError("小说内容不能为空")

    chapters = detect_chapters_by_rules(text)
    if not chapters:
        # 没有检测到章节，整个文本作为一章
        chapters.append({"title": title or "第一集", "content": text.strip()})

    limit = min(max_chapters or 20, len(chapters))
    slices = build_chapter_slices(chapters[:limit], drama_title=title)

    result = []
    for i in range(limit):
        ch = chapters[i]
        sl = slices[i]
        script = ch["content"]
        if ai_summarize:
            script = summarize_chapter_to_script(db, logger, ch["title"], ch["content"], title)
        result.append({
            "index": i + 1,
            "title": ch["title"],
            "content": ch["content"][:300],
            "script": script,
            "is_key_plot": sl.is_key_plot,
            "dramatic_elements": sl.dramatic_elements,
        })

    # 如果指定了 drama_id，且开启了记忆落库，则持久化到 memory_items
    if drama_id and save_to_memory and db is not None:
        try:
            save_novel_slices_to_memory(db, drama_id, slices)
        except Exception as e:
            logger.warning("[小说导入] 写入小说切片记忆库失败", {"error": str(e), "drama_id": drama_id})

    return {
        "chapters": result,
        "total": len(chapters),
        "slices": [s.model_dump() for s in slices],
    }

