"""存储布局辅助 — 契约翻译 backend-node/src/services/storageLayout.js。

本地图片/媒体按「工程目录」分层：projects/{id}_{日期}_{固化剧名}/…
- 公共素材、无 drama_id 的生成物 → library/{category}/…
- storage_folder_label 写入 dramas.metadata，避免用户改剧名后新文件落到另一目录导致分裂
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|#\x00-\x1f]')
_WS = re.compile(r"\s+")

PROJECTS = "projects"
LIBRARY = "library"


def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"


def sanitize_folder_label(title) -> str:
    """等价 Node sanitizeFolderLabel。"""
    s = str(title or "untitled").strip()[:20]
    s = _INVALID_CHARS.sub("_", s)
    s = _WS.sub("_", s)
    return s or "untitled"


def parse_metadata(raw) -> dict:
    """等价 Node parseMetadata：非对象/解析失败一律返回 {}。"""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list):
        return {}
    try:
        o = json.loads(raw)
        return dict(o) if isinstance(o, dict) else {}
    except Exception:
        return {}


def date_prefix_from_created_at(iso) -> str:
    """等价 Node datePrefixFromCreatedAt：取日期部分并去掉连字符。"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if not iso:
        return today
    return str(iso)[:10].replace("-", "") or today


def build_project_relative_dir(drama_row: dict) -> str:
    """由剧集行构造稳定相对目录（不含 category）。"""
    did = str(int(drama_row.get("id") or 0)).zfill(4)
    date_part = date_prefix_from_created_at(drama_row.get("created_at"))
    meta = parse_metadata(drama_row.get("metadata"))
    label_src = meta.get("storage_folder_label") or drama_row.get("title")
    return f"{PROJECTS}/{did}_{date_part}_{sanitize_folder_label(label_src)}"


def ensure_drama_storage_folder_label(db, drama_row: dict) -> dict:
    """缺省时把 storage_folder_label 写入 dramas.metadata（只写一次）。"""
    if not drama_row or not drama_row.get("id"):
        return drama_row
    meta = parse_metadata(drama_row.get("metadata"))
    if meta.get("storage_folder_label") and str(meta["storage_folder_label"]).strip():
        return drama_row

    meta["storage_folder_label"] = sanitize_folder_label(drama_row.get("title"))
    # 与 Node JSON.stringify 一致：不转义非 ASCII、无额外空格
    meta_str = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    try:
        from app.db.session import execute

        execute(
            db,
            "UPDATE dramas SET metadata = :metadata, updated_at = :updated_at WHERE id = :id",
            {"metadata": meta_str, "updated_at": _now_iso(), "id": drama_row["id"]},
        )
    except Exception:
        pass
    return {**drama_row, "metadata": meta_str}


def get_project_storage_subdir(db, drama_id) -> str:
    """返回相对 storage 根的前缀：projects/… 或 library。"""
    from app.db.session import fetch_one

    try:
        did = float(drama_id)
    except (TypeError, ValueError):
        return LIBRARY
    if not did or did <= 0:
        return LIBRARY

    row = fetch_one(
        db,
        "SELECT id, title, created_at, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
        {"id": int(did)},
    )
    if not row:
        return LIBRARY
    row = ensure_drama_storage_folder_label(db, row)
    return build_project_relative_dir(row)
