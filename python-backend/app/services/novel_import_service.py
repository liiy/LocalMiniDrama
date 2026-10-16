"""小说/长文章节智能切片、剧本初稿改写与 RAG 长期记忆索引服务。

【业务定位与架构职责】
1. LlamaIndex 语义层级切片（LlamaIndex Semantic Overlap Chunking）：
   - 支持动态接入 LlamaIndex 的 `SentenceSplitter` 语义断句器与滑动重叠窗口。
   - 内置优雅降级的高精度中文语义切分器（按句号、问号、感叹号、换行、引语对话断句）。
   - 具备自适应滑动窗口（Overlap Chunking），确保剧情转折与人物对白不被生硬截断。
2. 层次化切片模型（Hierarchical Chunks & Slices）：
   - 章节层级（NovelChapterSlice）：提供宏观章节标题、剧情梗概与名场面标记。
   - 语义块层级（NovelChunk）：提供精细化检索 Chunk，附带前向/后向 overlap 上下文。
3. AI 剧本初稿摘要与改写：
   - 支持通过 AI 将小说原文快速提炼改写为包含动作、对白、情绪的短剧分集草稿。
4. 剧集长期记忆库持久化（Novel RAG & Memory Items）：
   - 将小说章节切片与语义块自动持久化到 `memory_items` 表（memory_type='novel_slice' / 'novel_chunk'）。
   - 在后续分集分镜与人物生成时，通过长期记忆召回原著上下文，保证全剧设定与人物性格不失真。
"""
from __future__ import annotations

import re
from typing import Any

from app.context import memory_service
from app.core.logger import get_logger
from app.schemas.spec import NovelChapterSlice, NovelChunk, NovelSplitOptions
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

# 中文常见标点与断句边界正则
SENTENCE_SPLIT_REGEX = re.compile(r"([^。！？!?；;\n\r]+[。！？!?；;\n\r]+|[^。！？!?；;\n\r]+$)")


def split_sentences_semantic(text: str) -> list[str]:
    """按标点符号与自然段落将文本切分为连续的完整句子列表，避免在句中生硬截断。"""
    if not text:
        return []
    raw_sentences = SENTENCE_SPLIT_REGEX.findall(text)
    sentences: list[str] = []
    for s in raw_sentences:
        clean_s = s.strip()
        if clean_s:
            sentences.append(clean_s)
    return sentences if sentences else [text.strip()]


def semantic_overlap_split(
    text: str,
    *,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    min_chunk_size: int = 50,
    use_llamaindex: bool = True,
) -> list[dict[str, Any]]:
    """基于 LlamaIndex 语义断句或内置自适应滑动窗口切片算法。

    参数：
    - text: 输入小说/长文段落文本
    - chunk_size: 切片目标字符数
    - chunk_overlap: 自适应滑动窗口重叠重叠字符数（保持剧情连贯）
    - min_chunk_size: 最小切片阈值（过短尾段自动合并）
    - use_llamaindex: 是否优先尝试加载 LlamaIndex 组件
    """
    clean_text = str(text or "").strip()
    if not clean_text:
        return []

    # 1. 尝试使用 LlamaIndex 官方组件进行切片
    if use_llamaindex:
        try:
            # 兼容 LlamaIndex 新旧版本导入路径
            try:
                from llama_index.core.node_parser import SentenceSplitter
            except ImportError:
                from llama_index.core.text_splitter import SentenceSplitter  # type: ignore

            splitter = SentenceSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=" ",
            )
            raw_splits = splitter.split_text(clean_text)
            if raw_splits:
                chunks: list[dict[str, Any]] = []
                for idx, split_text in enumerate(raw_splits):
                    prev_text = raw_splits[idx - 1] if idx > 0 else ""
                    next_text = raw_splits[idx + 1] if idx < len(raw_splits) - 1 else ""
                    overlap_prefix = prev_text[-chunk_overlap:] if prev_text else ""
                    overlap_suffix = next_text[:chunk_overlap] if next_text else ""
                    chunks.append({
                        "text": split_text,
                        "char_count": len(split_text),
                        "overlap_prefix": overlap_prefix,
                        "overlap_suffix": overlap_suffix,
                    })
                return chunks
        except Exception as err:
            log.debug("LlamaIndex SentenceSplitter 不可用，启用内置高精度自适应滑动窗口: %s", err)

    # 2. 内置自适应滑动窗口切片器（保持句子完整性与剧情重叠）
    sentences = split_sentences_semantic(clean_text)
    if not sentences:
        return [{"text": clean_text, "char_count": len(clean_text), "overlap_prefix": "", "overlap_suffix": ""}]

    chunks: list[dict[str, Any]] = []
    current_sentences: list[str] = []
    current_len = 0
    prev_chunk_text = ""

    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current_sentences:
            chunk_str = "".join(current_sentences)
            overlap_prefix = prev_chunk_text[-chunk_overlap:] if prev_chunk_text else ""
            chunks.append({
                "text": chunk_str,
                "char_count": len(chunk_str),
                "overlap_prefix": overlap_prefix,
                "overlap_suffix": "",  # 后续回填
            })
            prev_chunk_text = chunk_str

            # 计算保留进入下一个窗口的重叠句子
            overlap_sentences: list[str] = []
            overlap_accum = 0
            for s in reversed(current_sentences):
                if overlap_accum + len(s) <= chunk_overlap:
                    overlap_sentences.insert(0, s)
                    overlap_accum += len(s)
                else:
                    break
            current_sentences = overlap_sentences + [sent]
            current_len = sum(len(s) for s in current_sentences)
        else:
            current_sentences.append(sent)
            current_len += sent_len

    if current_sentences:
        chunk_str = "".join(current_sentences)
        # 如果尾段太短且已有前序分块，合并到前一个分块
        if len(chunk_str) < min_chunk_size and chunks:
            chunks[-1]["text"] += chunk_str
            chunks[-1]["char_count"] = len(chunks[-1]["text"])
        else:
            overlap_prefix = prev_chunk_text[-chunk_overlap:] if prev_chunk_text else ""
            chunks.append({
                "text": chunk_str,
                "char_count": len(chunk_str),
                "overlap_prefix": overlap_prefix,
                "overlap_suffix": "",
            })

    # 回填后向 overlap_suffix
    for i in range(len(chunks) - 1):
        chunks[i]["overlap_suffix"] = chunks[i + 1]["text"][:chunk_overlap]

    return chunks


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
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    use_semantic_split: bool = True,
) -> list[NovelChapterSlice]:
    """将规则提取的原始章节规整为结构化的 NovelChapterSlice 切片列表，并生成自适应滑动窗口子切片。"""
    slices: list[NovelChapterSlice] = []
    global_chunk_idx = 1

    for idx, ch in enumerate(raw_chapters, start=1):
        title = ch.get("title") or f"第{idx}章"
        content = ch.get("content") or ""
        is_key = any(kw in (title + content[:300]) for kw in KEY_PLOT_KEYWORDS)
        summary = content[:200].replace("\n", " ") + ("..." if len(content) > 200 else "")

        # 生成本章节内的自适应滑动窗口语义切片
        novel_chunks: list[NovelChunk] = []
        if use_semantic_split and content:
            raw_chunk_items = semantic_overlap_split(
                content,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                use_llamaindex=True,
            )
            for c_item in raw_chunk_items:
                c_text = c_item.get("text", "")
                c_is_key = any(kw in c_text for kw in KEY_PLOT_KEYWORDS)
                c_summary = c_text[:120].replace("\n", " ") + ("..." if len(c_text) > 120 else "")
                novel_chunks.append(
                    NovelChunk(
                        chunk_index=global_chunk_idx,
                        chapter_index=idx,
                        chapter_title=title,
                        text=c_text,
                        summary=c_summary,
                        char_count=c_item.get("char_count", len(c_text)),
                        overlap_prefix=c_item.get("overlap_prefix", ""),
                        overlap_suffix=c_item.get("overlap_suffix", ""),
                        is_key_plot=c_is_key,
                        dramatic_elements=["名场面/高潮冲突"] if c_is_key else ["情节推进"],
                        key_characters=[],
                        metadata={
                            "drama_title": drama_title,
                            "chapter_title": title,
                        },
                    )
                )
                global_chunk_idx += 1

        slices.append(
            NovelChapterSlice(
                chapter_index=idx,
                chapter_title=title,
                original_text=content,
                summary=summary,
                key_characters=[],
                dramatic_elements=["名场面/高潮冲突"] if is_key else ["日常剧情"],
                is_key_plot=is_key,
                chunks=novel_chunks,
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
    *,
    save_granular_chunks: bool = True,
) -> list[dict[str, Any]]:
    """将小说切片与精细化语义块作为长期记忆持久化到 memory_items 表中。

    每个切片记录包含：
    - drama_id: 归属短剧项目 ID
    - memory_type: 'novel_slice'（章节级） / 'novel_chunk'（自适应滑动窗口语义块）
    - scope: 'drama'
    - title: 章节标题或 Chunk 标题
    - content: 文本正文
    - summary: 情节摘要
    - keywords: 关键剧情标签与名场面标记
    - metadata: 章节序号、is_key_plot 与滑动窗口重叠标记
    """
    saved_items: list[dict[str, Any]] = []
    for sl in slices:
        # 1. 保存章节宏观切片 (novel_slice)
        slice_payload = {
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
                "total_chunks": len(sl.chunks),
            },
        }
        item = memory_service.add_memory_item(db, slice_payload)
        saved_items.append(item)

        # 2. 如果包含精细化语义块，保存滑动窗口块 (novel_chunk)
        if save_granular_chunks and sl.chunks:
            for chunk in sl.chunks:
                chunk_payload = {
                    "drama_id": drama_id,
                    "memory_type": "novel_chunk",
                    "scope": "drama",
                    "title": f"第{chunk.chapter_index}章 [{chunk.chapter_title}] - 切片#{chunk.chunk_index}",
                    "content": chunk.text,
                    "summary": chunk.summary,
                    "keywords": chunk.dramatic_elements + chunk.key_characters,
                    "source_type": "novel_chunk",
                    "source_id": f"chunk_{chunk.chunk_index}",
                    "metadata": {
                        "chunk_index": chunk.chunk_index,
                        "chapter_index": chunk.chapter_index,
                        "chapter_title": chunk.chapter_title,
                        "char_count": chunk.char_count,
                        "overlap_prefix": chunk.overlap_prefix,
                        "overlap_suffix": chunk.overlap_suffix,
                        "is_key_plot": chunk.is_key_plot,
                    },
                }
                c_item = memory_service.add_memory_item(db, chunk_payload)
                saved_items.append(c_item)

    log.info("Saved %d novel items (slices & chunks) to memory_items", len(saved_items), extra={"drama_id": drama_id})
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
    # 优先在 novel_chunk 和 novel_slice 中联合检索
    results = memory_service.search_memory_items(
        db,
        drama_id=drama_id,
        query=query,
        limit=limit,
    )
    return [r for r in results if r.get("memory_type") in ("novel_slice", "novel_chunk")]


def import_novel(
    db: Any,
    logger: Any,
    *,
    text: str,
    title: str = "",
    drama_id: int | None = None,
    max_chapters: int = 20,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    use_semantic_split: bool = True,
    ai_summarize: bool = False,
    save_to_memory: bool = True,
) -> dict[str, Any]:
    """主入口：解析小说文本，执行 LlamaIndex 语义滑动窗口切片并返回剧本草稿列表。

    当传入 drama_id 时，会自动将切片与 Chunk 存入 `memory_items` 表，供全剧后续生成分镜和视频时检索。
    @returns dict(chapters=list[dict(...)], total=int, slices=list, chunks=list)
    """
    if not text or not text.strip():
        raise ValueError("小说内容不能为空")

    chapters = detect_chapters_by_rules(text)
    if not chapters:
        # 没有检测到章节，整个文本作为一章
        chapters.append({"title": title or "第一集", "content": text.strip()})

    limit = min(max_chapters or 20, len(chapters))
    slices = build_chapter_slices(
        chapters[:limit],
        drama_title=title,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        use_semantic_split=use_semantic_split,
    )

    result = []
    all_chunks = []
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
            "chunks_count": len(sl.chunks),
        })
        for c in sl.chunks:
            all_chunks.append(c.model_dump())

    # 如果指定了 drama_id，且开启了记忆落库，则持久化到 memory_items
    if drama_id and save_to_memory and db is not None:
        try:
            save_novel_slices_to_memory(db, drama_id, slices, save_granular_chunks=True)
        except Exception as e:
            logger.warning("[小说导入] 写入小说切片记忆库失败", {"error": str(e), "drama_id": drama_id})

    return {
        "chapters": result,
        "total": len(chapters),
        "slices": [s.model_dump() for s in slices],
        "chunks": all_chunks,
    }

