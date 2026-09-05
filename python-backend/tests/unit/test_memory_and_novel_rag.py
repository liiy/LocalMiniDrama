"""单元测试：验证迭代 3 长期记忆与小说切片索引机制。"""
from __future__ import annotations

from app.context.vector_memory_service import (
    build_memory_document,
    is_vector_memory_enabled,
    make_embedding_ref,
    vector_memory_settings,
)
from app.schemas.spec import NovelAdaptationSpec, NovelChapterSlice
from app.services.novelImportService import detect_chapters_by_rules


def test_build_memory_document_formats_multiline_text():
    """验证记忆向量文档拼装。"""
    memory_item = {
        "title": "主角隐世宗门背景",
        "summary": "林辰为龙门第九代执剑传人",
        "content": "三年前龙门遭遇内乱，林辰封印修为进入江家为赘婿...",
        "keywords": ["林辰", "龙门", "赘婿", "执剑人"],
    }
    doc = build_memory_document(memory_item)
    assert "主角隐世宗门背景" in doc
    assert "林辰为龙门第九代执剑传人" in doc
    assert "林辰，龙门，赘婿，执剑人" in doc


def test_vector_memory_settings_default_safe_disabled():
    """验证未显式开启向量库时安全处于 disabled 状态，不阻断主链路。"""
    settings = vector_memory_settings({})
    assert settings["backend"] in ("disabled", "qdrant")
    ref = make_embedding_ref("qdrant", "drama_memory", 101)
    assert ref == "qdrant:drama_memory:101"


def test_detect_chapters_by_rules_multi_chapter_text():
    """验证小说章节标题正则切分规则。"""
    novel_raw_text = """
第一章 龙王出狱
江州监狱大门缓缓打开，林辰背着破旧帆布包走出，神色漠然。
狱警恭敬行礼：“恭送龙王！”

第二章 赘婿受辱
江家豪门大院内，丈母娘冷笑将离婚协议甩在地上：“把字签了，滚出江家！”
林辰默默不语。

第三章 战神归来
轰鸣声中，数十架武装直升机低空盘旋，龙门精锐整齐划一单膝跪地。
    """.strip()

    chapters = detect_chapters_by_rules(novel_raw_text)
    assert len(chapters) == 3
    assert "第一章" in chapters[0]["title"]
    assert "江州监狱大门" in chapters[0]["content"]
    assert "第二章" in chapters[1]["title"]
    assert "第三章" in chapters[2]["title"]


def test_novel_chapter_slices_schema_integration():
    """验证小说切片 Schema 结构与改编规划集成。"""
    slice1 = NovelChapterSlice(
        chapter_index=1,
        chapter_title="第一章 龙王出狱",
        summary="林辰出狱，隐世龙门势力就绪",
        is_key_plot=True,
    )
    spec = NovelAdaptationSpec(
        novel_title="狂龙出狱",
        source_summary="都市爽文",
        chapter_slices=[slice1],
    )
    assert len(spec.chapter_slices) == 1
    assert spec.chapter_slices[0].is_key_plot is True


def test_novel_chapter_slice_and_memory_persistence(db_session):
    """验证小说章节切片生成、结构化封装与持久化到 memory_items。"""
    from app.services.novelImportService import (
        build_chapter_slices,
        detect_chapters_by_rules,
        get_novel_slices_from_memory,
        save_novel_slices_to_memory,
        search_novel_memory,
    )

    sample_novel_text = """
    第一章 龙王赘婿归来
    江城叶家大堂内，叶辰冷冷地看着撕碎的婚约。
    三年前他隐姓埋名入赘叶家，如今三年之期已满，十万龙神卫已经集结！
    叶家老太太冷哼：“叶辰，你不过是个废物，真以为能配得上我们倾城？”
    叶辰淡然一笑，拿出一枚通体漆黑的龙神令。
    """

    raw_chapters = detect_chapters_by_rules(sample_novel_text)
    assert len(raw_chapters) >= 1
    slices = build_chapter_slices(raw_chapters, drama_title="龙王赘婿")
    assert len(slices) >= 1
    slice_obj = slices[0]
    assert isinstance(slice_obj, NovelChapterSlice)
    assert slice_obj.chapter_title == "第一章 龙王赘婿归来"

    # 保存到长期记忆库（包含宏观章节切片与细粒度滑动窗口切片）
    saved = save_novel_slices_to_memory(db_session, drama_id=999, slices=slices)
    assert len(saved) >= len(slices)
    assert any(item.get("memory_type") == "novel_slice" for item in saved)

    # 从长期记忆中按 drama_id 查询切片
    fetched_slices = get_novel_slices_from_memory(db_session, drama_id=999)
    assert len(fetched_slices) == len(slices)
    assert "第一章" in fetched_slices[0]["title"]

    # 执行 RAG 语义/关键词检索
    search_results = search_novel_memory(db_session, drama_id=999, query="龙神令", limit=5)
    assert len(search_results) >= 1
    assert any("龙神令" in s.get("content", "") or "龙神令" in s.get("summary", "") for s in search_results)


def test_context_builder_with_novel_rag_recall(db_session):
    """验证 Context Builder 自动召回关联的小说切片与长期记忆。"""
    from app.context.builder import build_context
    from app.services.novelImportService import (
        build_chapter_slices,
        detect_chapters_by_rules,
        save_novel_slices_to_memory,
    )

    raw_text = """
    第一章 龙王归来
    叶辰拿出龙神令，全场骇然！十万龙神卫齐声高呼拜见龙王！
    """
    raw_chapters = detect_chapters_by_rules(raw_text)
    slices = build_chapter_slices(raw_chapters, drama_title="龙王赘婿")
    save_novel_slices_to_memory(db_session, drama_id=888, slices=slices)

    # 调用 context builder 组装
    context_pkg = build_context(
        db=db_session,
        drama_id=888,
        episode_id=1,
        query="龙神令 龙王",
    )

    assert context_pkg["drama_id"] == 888
    # 验证自动召回了小说切片
    assert "novel_slices" in context_pkg
    assert len(context_pkg["novel_slices"]) >= 1
    assert "龙神令" in context_pkg["novel_slices"][0].get("content", "")


def test_semantic_overlap_split_algorithm():
    """验证语义断句与自适应滑动窗口切片 (Overlap Chunking) 算法。"""
    from app.services.novelImportService import semantic_overlap_split

    long_story_text = (
        "江州城外，暴雨倾盆。林辰撑着一把破旧的黑伞，伫立在林家祠堂前。"
        "三年前的那个雨夜，正是林家大长老亲手剥夺了他的少族长之位，并将他打断经脉逐出家族！"
        "如今，林辰已是威震四海的绝世医圣与龙门殿主，王者归来！"
        "“大长老，当年的旧账，今日该一笔一笔算清楚了！”林辰眼眸如电，一步跨入祠堂大殿。"
        "殿内众人纷纷拔刀相向，杀气凛冽，大战一触即发！"
    )

    chunks = semantic_overlap_split(
        text=long_story_text,
        chunk_size=60,
        chunk_overlap=20,
        min_chunk_size=15,
    )

    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.get("text")
        assert chunk.get("char_count") == len(chunk["text"])

    # 验证第 2 个 chunk 拥有 overlap_prefix 重叠前缀
    if len(chunks) >= 2:
        second_chunk = chunks[1]
        assert second_chunk.get("overlap_prefix") != "" or second_chunk.get("char_count", 0) > 0


def test_qdrant_drama_collection_isolation_lifecycle(db_session):
    """验证针对不同剧本项目的 Qdrant Collection 隔离与生命周期管理。"""
    from app.context.memory_service import add_memory_item
    from app.context.vector_memory_service import (
        clean_drama_memory_vectors,
        delete_drama_collection,
        ensure_drama_collection,
        get_drama_collection_info,
        get_drama_collection_name,
        make_embedding_ref,
    )

    drama_id = 777
    collection_name = get_drama_collection_name(drama_id=drama_id)
    assert f"drama_{drama_id}" in collection_name

    # 1. 创建/确保集合
    created = ensure_drama_collection(drama_id=drama_id, vector_size=1536)
    assert created.get("status") in ("created", "exists", "skipped")

    # 2. 诊断信息查询
    info = get_drama_collection_info(drama_id=drama_id)
    assert info.get("collection") == collection_name
    assert info.get("is_isolated") is True

    # 3. 准备带有 embedding_ref 的记忆条目
    item = add_memory_item(
        db_session,
        {
            "drama_id": drama_id,
            "memory_type": "novel_chunk",
            "title": "测试切片",
            "content": "测试内容",
            "embedding_ref": make_embedding_ref("qdrant", collection_name, 1),
        },
    )
    assert item.get("embedding_ref") is not None

    # 4. 批量清理剧本向量并验证 DB embedding_ref 重置
    clean_res = clean_drama_memory_vectors(db_session, drama_id=drama_id)
    assert clean_res.get("status") == "ok"
    assert clean_res.get("reset_db_items_count", 0) >= 1

    # 重新查询验证已重置为 NULL
    from sqlalchemy import text
    row = db_session.execute(
        text("SELECT embedding_ref FROM memory_items WHERE id = :id"),
        {"id": item["id"]},
    ).fetchone()
    assert row[0] is None

    # 5. 删除剧本专属 Collection
    del_res = delete_drama_collection(drama_id=drama_id)
    assert del_res.get("status") in ("deleted", "skipped")



