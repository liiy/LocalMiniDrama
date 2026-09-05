"""/api/v1/dramas/* — 契约精确翻译 backend-node/src/routes/drama.js（P2 纯 CRUD 部分）。

已翻译端点：
- GET    /dramas                     列表（分页 + status/genre/keyword 过滤）
- POST   /dramas                     新建（400 '标题不能为空' | 201）
- GET    /dramas/stats               统计（须注册在 /dramas/{id} 之前）
- GET    /dramas/{id}                聚合详情（404 '剧本不存在'）
- PUT    /dramas/{id}                更新（404）
- DELETE /dramas/{id}                软删（404 | { message: '删除成功' }）
- PUT    /dramas/{id}/outline        保存大纲（404 | { message: '保存成功' }）
- GET    /dramas/{id}/characters     角色列表（404 '剧本或章节不存在'）
- PUT    /dramas/{id}/characters     保存角色（400 'characters 必填且为数组' | 404）
- PUT    /dramas/{id}/episodes       保存分集（400 'episodes 必填且为数组' | 404）
- PUT    /dramas/{id}/progress       保存进度（400 'current_step 必填' | 404）
- PUT    /dramas/{id}/canvas-layout  保存画布布局（400 三种校验 | 404）
- GET    /dramas/{id}/props          道具列表（独立字段映射）

未翻译（P3/P4/P5）：export/import/import-novel/examples/import-example/finalize/download/generateStoryboard。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import (
    HttpError,
    bad_request,
    created,
    internal_error,
    not_found,
    success,
    success_with_pagination,
)
from app.core.upload_validation import (
    DEFAULT_MAX_TEXT_BYTES,
    DEFAULT_MAX_ZIP_BYTES,
    read_upload_limited,
    validate_text_type,
    validate_zip_type,
)
from app.db.session import get_db
from app.context import vector_memory_service
from app.schemas.drama import (
    DramaCanvasLayoutUpdate,
    DramaCharactersUpdate,
    DramaCreate,
    DramaEpisodesUpdate,
    DramaOutlineUpdate,
    DramaProgressUpdate,
    DramaUpdate,
)
from app.schemas.spec import NovelSplitOptions
from app.services import dramaExportService as export_svc
from app.services import dramaImportService as import_svc
from app.services import dramaService as svc
from app.services import novelImportService as novel_svc

router = APIRouter(tags=["dramas"])
log = get_logger("lmd.drama")

# 内存态配置（等价 Node routes(db, cfg, log) 闭包持有 cfg）
_CFG: dict = {}


def init_config(cfg: dict) -> None:
    global _CFG
    _CFG = cfg or {}


def _storage_base_url() -> str:
    return (_CFG.get("storage") or {}).get("base_url") or ""


def _storage_root() -> str:
    return (_CFG.get("storage") or {}).get("local_path") or ""


def _is_plain_object(v) -> bool:
    return isinstance(v, dict)


def get_example_drama_dir() -> Path | None:
    env_path = os.environ.get("EXAMPLE_DRAMA_PATH")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    dev_path = Path(__file__).resolve().parents[4] / "example_drama"
    if dev_path.exists():
        return dev_path
    return None


@router.get("/dramas")
def list_dramas(
    page: str | None = None,
    page_size: str | None = None,
    status: str | None = None,
    genre: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    dramas, total, page_no, page_len = svc.list_dramas(
        db, {"page": page, "page_size": page_size, "status": status, "genre": genre, "keyword": keyword}
    )
    return success_with_pagination(dramas, total, page_no, page_len)


@router.post("/dramas", status_code=201)
def create_drama(payload: DramaCreate | dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload.model_dump(exclude_unset=True) if isinstance(payload, DramaCreate) else (payload or {})
    if not body.get("title") or str(body["title"]).strip() == "":
        raise bad_request("标题不能为空")
    return created(svc.create_drama(db, body))


@router.get("/dramas/stats")
def get_drama_stats(db: Session = Depends(get_db)) -> dict:
    return success(svc.get_drama_stats(db))


@router.post("/dramas/import", status_code=201)
async def import_drama(
    file: UploadFile = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if not file or not file.filename:
        raise bad_request("请上传 ZIP 文件")
    validate_zip_type(file.filename)
    try:
        content = await read_upload_limited(file, DEFAULT_MAX_ZIP_BYTES, "ZIP 文件大小不能超过 128MB")
    except HttpError:
        raise
    except Exception:
        raise bad_request("请上传 ZIP 文件")
    if not content:
        raise bad_request("请上传 ZIP 文件")
    try:
        result = import_svc.import_drama(db, _CFG, log, content)
        return created(result)
    except Exception as err:
        err_msg = str(err)
        log.error("Import drama failed: %s", err_msg)
        if "格式" in err_msg or "缺少" in err_msg or "损坏" in err_msg:
            raise bad_request(err_msg)
        raise internal_error(err_msg or "导入失败")


@router.post("/dramas/import-novel")
async def import_novel_endpoint(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """导入小说文本并进行 LlamaIndex 语义断句与自适应滑动窗口切片（Overlap Chunking），存入剧本集数与长期记忆向量库。"""
    content_type = request.headers.get("content-type", "")
    text_content = ""
    title = ""
    max_chapters = 20
    ai_summarize = False
    chunk_size = 600
    chunk_overlap = 100
    semantic_chunking = True
    min_chunk_size = 80
    auto_embed = True

    if "multipart/form-data" in content_type:
        form = await request.form()
        file_obj = form.get("file")
        if file_obj and hasattr(file_obj, "read"):
            try:
                if getattr(file_obj, "filename", ""):
                    validate_text_type(file_obj.filename)
                raw_bytes = await read_upload_limited(
                    file_obj,
                    DEFAULT_MAX_TEXT_BYTES,
                    "小说文本大小不能超过 10MB",
                )
                text_content = raw_bytes.decode("utf-8", errors="replace")
            except HttpError:
                raise
            except Exception:
                text_content = ""
        if not text_content:
            text_content = str(form.get("text") or "")
        title = str(form.get("title") or "")
        mc_raw = form.get("max_chapters")
        if mc_raw is not None and str(mc_raw).isdigit():
            max_chapters = int(mc_raw)
        ai_raw = form.get("ai_summarize")
        ai_summarize = str(ai_raw).lower() in ("true", "1") or ai_raw is True
        
        # 语义切片与滑动窗口参数
        if form.get("chunk_size") and str(form.get("chunk_size")).isdigit():
            chunk_size = int(str(form.get("chunk_size")))
        if form.get("chunk_overlap") and str(form.get("chunk_overlap")).isdigit():
            chunk_overlap = int(str(form.get("chunk_overlap")))
        if form.get("semantic_chunking") is not None:
            semantic_chunking = str(form.get("semantic_chunking")).lower() in ("true", "1")
        if form.get("auto_embed") is not None:
            auto_embed = str(form.get("auto_embed")).lower() in ("true", "1")
    else:
        try:
            body = await request.json()
        except Exception:
            body = {}
        text_content = str(body.get("text") or "")
        title = str(body.get("title") or "")
        mc_raw = body.get("max_chapters")
        if mc_raw is not None and str(mc_raw).isdigit():
            max_chapters = int(mc_raw)
        ai_raw = body.get("ai_summarize")
        ai_summarize = str(ai_raw).lower() in ("true", "1") or ai_raw is True
        
        # 语义切片与滑动窗口参数
        if body.get("chunk_size"):
            chunk_size = int(body["chunk_size"])
        if body.get("chunk_overlap"):
            chunk_overlap = int(body["chunk_overlap"])
        if body.get("semantic_chunking") is not None:
            semantic_chunking = bool(body["semantic_chunking"])
        if body.get("auto_embed") is not None:
            auto_embed = bool(body["auto_embed"])

    if not text_content or not text_content.strip():
        raise bad_request("请上传小说文本文件或提供 text 参数")
    if len(text_content.encode("utf-8")) > DEFAULT_MAX_TEXT_BYTES:
        raise HttpError(413, "FILE_TOO_LARGE", "小说文本大小不能超过 10MB")

    split_options = NovelSplitOptions(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        semantic_chunking=semantic_chunking,
        min_chunk_size=min_chunk_size,
    )

    try:
        result = novel_svc.import_novel(
            db,
            log,
            text=text_content,
            title=title,
            max_chapters=max_chapters,
            ai_summarize=ai_summarize,
            split_options=split_options,
            auto_embed=auto_embed,
        )
        return success(result)
    except Exception as err:
        log.error("dramas import-novel failed: %s", err)
        raise internal_error(str(err))


@router.post("/dramas/novel-slices/semantic-split")
def semantic_split_novel_endpoint(
    payload: dict = Body(default={}),
) -> dict:
    """对传入的小说文本进行 LlamaIndex / 自适应滑动窗口语义切片预览，不直接持久化到数据库。"""
    body = payload or {}
    text_content = str(body.get("text") or "")
    if not text_content.strip():
        raise bad_request("text 必填")
    
    max_chapters = int(body.get("max_chapters") or 20)
    split_opts = NovelSplitOptions(
        chunk_size=int(body.get("chunk_size") or 600),
        chunk_overlap=int(body.get("chunk_overlap") or 100),
        semantic_chunking=bool(body.get("semantic_chunking", True)),
        min_chunk_size=int(body.get("min_chunk_size") or 80),
    )
    
    parsed = novel_svc.parse_novel_to_episodes(text_content, max_chapters=max_chapters)
    slices = novel_svc.build_chapter_slices(
        parsed.get("chapters") or [],
        drama_id=body.get("drama_id"),
        split_options=split_opts,
    )
    return success({
        "title": parsed.get("title") or "未命名小说",
        "chapter_count": len(slices),
        "slices": [s.model_dump() for s in slices],
    })


@router.get("/dramas/{drama_id}/memory/vectors/info")
def get_drama_vector_memory_info(
    drama_id: str,
) -> dict:
    """获取指定剧本的 Qdrant 隔离集合状态与向量索引诊断信息。"""
    d_id = int(drama_id) if drama_id.isdigit() else None
    info = vector_memory_service.get_drama_collection_info(drama_id=d_id)
    return success(info)


@router.delete("/dramas/{drama_id}/memory/vectors")
def clean_drama_vector_memory(
    drama_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """按剧本维度批量清理 Qdrant 向量索引，并联动重置数据库中 memory_items 的 embedding_ref。"""
    d_id = int(drama_id) if drama_id.isdigit() else None
    if not d_id:
        raise bad_request("drama_id 必须为数字")
    res = vector_memory_service.clean_drama_memory_vectors(db, drama_id=d_id)
    return success(res)


@router.delete("/dramas/{drama_id}/memory/collection")
def delete_drama_vector_collection(
    drama_id: str,
) -> dict:
    """删除指定剧本在 Qdrant 中的独立隔离 Collection。"""
    d_id = int(drama_id) if drama_id.isdigit() else None
    if not d_id:
        raise bad_request("drama_id 必须为数字")
    res = vector_memory_service.delete_drama_collection(drama_id=d_id)
    return success(res)


@router.get("/dramas/examples")
def list_examples() -> dict:
    dir_path = get_example_drama_dir()
    if not dir_path or not dir_path.is_dir():
        return success([])
    try:
        files = [f.name for f in dir_path.iterdir() if f.is_file() and f.name.endswith(".zip")]
        items = [{"filename": f, "name": f[:-4]} for f in files]
        return success(items)
    except Exception as err:
        log.error("List examples failed: %s", err)
        return success([])


@router.post("/dramas/import-example", status_code=201)
def import_example(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload or {}
    filename = body.get("filename")
    if not filename:
        raise bad_request("请指定示例文件名")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise bad_request("文件名不合法")
    dir_path = get_example_drama_dir()
    if not dir_path or not dir_path.is_dir():
        raise bad_request("示例目录不存在")
    file_path = dir_path / filename
    if not file_path.exists():
        raise not_found("示例文件不存在")
    try:
        data = file_path.read_bytes()
        result = import_svc.import_drama(db, _CFG, log, data)
        return created(result)
    except Exception as err:
        log.error("Import example failed: %s", err)
        raise internal_error(str(err) or "导入示例失败")


@router.get("/dramas/{drama_id}/export")
def export_drama(drama_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        buffer, title = export_svc.export_drama(db, _CFG, log, drama_id)
        safe_name = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", title or "drama")[:50]
        encoded_name = quote(f"{safe_name}.zip")
        return Response(
            content=buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            },
        )
    except Exception as err:
        err_msg = str(err)
        log.error("Export drama failed: %s", err_msg)
        raise internal_error(err_msg or "导出失败")


@router.get("/dramas/{drama_id}/props")
def list_props(drama_id: str, db: Session = Depends(get_db)) -> dict:
    """等价 propService.listByDramaId（字段映射与 rowToProp 不同，无 sanitize/error_msg）。"""
    rows = db.execute(
        text("SELECT * FROM props WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC"),
        {"did": svc.to_int_id(drama_id)},
    ).mappings().all()
    props = [
        {
            "id": r["id"],
            "drama_id": r["drama_id"],
            "name": r["name"],
            "type": r["type"],
            "description": r["description"],
            "prompt": r["prompt"],
            "negative_prompt": r["negative_prompt"] or None,
            "image_url": r["image_url"],
            "local_path": r["local_path"],
            "extra_images": r["extra_images"] or None,
            "ref_image": r["ref_image"] or None,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]
    return success(props)


@router.put("/dramas/{drama_id}/outline")
def save_outline(
    drama_id: str,
    payload: DramaOutlineUpdate | dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload.model_dump(exclude_unset=True) if isinstance(payload, DramaOutlineUpdate) else (payload or {})
    ok = svc.save_outline(db, drama_id, body)
    if not ok:
        raise not_found("剧本不存在")
    return success({"message": "保存成功"})


@router.get("/dramas/{drama_id}/characters")
def get_characters(
    drama_id: str, episode_id: str | None = Query(default=None), db: Session = Depends(get_db)
) -> dict:
    characters = svc.get_characters(db, drama_id, episode_id)
    if characters is None:
        raise not_found("剧本或章节不存在")
    return success(characters)


@router.put("/dramas/{drama_id}/characters")
def save_characters(
    drama_id: str,
    payload: DramaCharactersUpdate | dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload.model_dump(exclude_unset=True) if isinstance(payload, DramaCharactersUpdate) else (payload or {})
    if not isinstance(body.get("characters"), list):
        raise bad_request("characters 必填且为数组")
    ok = svc.save_characters(db, drama_id, body)
    if not ok:
        raise not_found("剧本或章节不存在")
    return success({"message": "保存成功"})


@router.put("/dramas/{drama_id}/episodes")
def save_episodes(
    drama_id: str,
    payload: DramaEpisodesUpdate | dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload.model_dump(exclude_unset=True) if isinstance(payload, DramaEpisodesUpdate) else (payload or {})
    if not isinstance(body.get("episodes"), list):
        raise bad_request("episodes 必填且为数组")
    ok = svc.save_episodes(db, drama_id, body)
    if not ok:
        raise not_found("剧本不存在")
    return success({"message": "保存成功"})


@router.put("/dramas/{drama_id}/progress")
def save_progress(
    drama_id: str,
    payload: DramaProgressUpdate | dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload.model_dump(exclude_unset=True) if isinstance(payload, DramaProgressUpdate) else (payload or {})
    if not body.get("current_step"):
        raise bad_request("current_step 必填")
    ok = svc.save_progress(db, drama_id, body)
    if not ok:
        raise not_found("剧本不存在")
    return success({"message": "保存成功"})


@router.put("/dramas/{drama_id}/canvas-layout")
def save_canvas_layout(
    drama_id: str,
    payload: DramaCanvasLayoutUpdate | dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload.model_dump(exclude_unset=True) if isinstance(payload, DramaCanvasLayoutUpdate) else (payload or {})
    try:
        updated = svc.save_canvas_layout(db, drama_id, body)
    except ValueError as e:
        if getattr(e, "code", None) == "BAD_REQUEST":
            raise bad_request(str(e))
        raise
    if not updated:
        raise not_found("剧本不存在")
    return success(updated)


@router.get("/dramas/{drama_id}")
def get_drama(drama_id: str, db: Session = Depends(get_db)) -> dict:
    drama = svc.get_drama(db, drama_id)
    if not drama:
        raise not_found("剧本不存在")
    return success(drama)


@router.put("/dramas/{drama_id}")
def update_drama(
    drama_id: str,
    payload: DramaUpdate | dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload.model_dump(exclude_unset=True) if isinstance(payload, DramaUpdate) else (payload or {})
    drama = svc.update_drama(db, drama_id, body)
    if not drama:
        raise not_found("剧本不存在")
    return success(drama)


@router.delete("/dramas/{drama_id}")
def delete_drama(drama_id: str, db: Session = Depends(get_db)) -> dict:
    ok = svc.delete_drama(db, drama_id)
    if not ok:
        raise not_found("剧本不存在")
    return success({"message": "删除成功"})


# ---------------- P4/P5：合成 / 下载 / 纯 AI 占位 ----------------


@router.get("/dramas/{drama_id}/episodes/{episode_id}/download-video")
def download_episode_video(drama_id: str, episode_id: str, db: Session = Depends(get_db)) -> dict:
    result = svc.download_episode_video(db, episode_id)
    if result is None:
        raise not_found("剧集不存在")
    if result.get("error"):
        raise bad_request(result["error"])
    return success(result)


@router.put("/dramas/{drama_id}/episodes/{episode_id}/finalize")
def finalize_episode(
    drama_id: str,
    episode_id: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    if not episode_id:
        raise bad_request("episode_id不能为空")
    base_url = _storage_base_url()
    result = svc.finalize_episode(db, log, episode_id, base_url, payload or {}, _storage_root())
    if not result:
        raise not_found("剧集不存在")
    return success(result)


@router.post("/dramas/{drama_id}/episodes/{episode_id}/generate-storyboard")
def generate_storyboard(
    drama_id: str,
    episode_id: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    body = payload or {}
    try:
        svc.generate_storyboard(db, log, episode_id, body)
    except NotImplementedError:
        raise internal_error("generate-storyboard 依赖外部 AI，python-backend 尚未接入")
    return success({})
