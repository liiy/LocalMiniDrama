"""三个素材库（character/scene/prop libraries）的公共查询逻辑。

等价 Node services/libraryDedup.js 中被 list 路径用到的部分：
- normalizeSourceId / parseSourceIds / appendSourceIdFilters

Node 的 hasColumn() 用 SQLite PRAGMA 判断 source_id 列是否存在；
MySQL 三个表均含该列，故简化为常量（保留语义说明以便 P4 直接复用）。
"""
from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

_INT_RE = re.compile(r"^[+-]?\d+")


def js_parse_int(value: Any, default: int) -> int:
    """等价 JS parseInt(v, 10) || default。"""
    if value is None:
        return default
    m = _INT_RE.match(str(value).strip())
    if not m:
        return default
    return int(m.group(0)) or default


def to_int_id(value: Any) -> int:
    """等价 JS Number(id)（用于 WHERE id = ?）。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def normalize_source_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_source_ids(value: Any) -> list[str]:
    """等价 Node parseSourceIds：数组逐项 normalize；字符串按逗号切分。"""
    if isinstance(value, (list, tuple)):
        return [s for s in (normalize_source_id(v) for v in value) if s]
    return [s for s in (p.strip() for p in str(value or "").split(",")) if s]


def parse_source_ids_from_query(values: list[str]) -> list[str]:
    """按 Express 的 req.query 语义解析 source_ids。

    Express 行为：?source_ids=S1,S2 → 字符串（Node 按逗号切分）
                 ?source_ids=S1&source_ids=S2 → 数组（Node 逐项 normalize）
    因此单值时走字符串分支，多值时走数组分支。
    """
    if not values:
        return []
    if len(values) == 1:
        return parse_source_ids(values[0])
    return [s for s in (normalize_source_id(v) for v in values) if s]


def append_source_id_filters(query: dict, where: str, params: dict) -> str:
    """等价 Node appendSourceIdFilters（改为 SQLAlchemy 命名参数写法）。"""
    if query.get("source_id"):
        where += " AND source_id = :f_source_id"
        params["f_source_id"] = normalize_source_id(query["source_id"])
    raw_ids = query.get("source_ids")
    if isinstance(raw_ids, (list, tuple)):
        source_ids = parse_source_ids_from_query(list(raw_ids))
    else:
        source_ids = parse_source_ids(raw_ids)
    if source_ids:
        names = []
        for i, sid in enumerate(source_ids):
            key = f"f_source_ids_{i}"
            names.append(f":{key}")
            params[key] = sid
        where += f" AND source_id IN ({', '.join(names)})"
    return where


def build_list_where(table: str, keyword_cols: list[str], query: dict) -> tuple[str, dict]:
    """构造 listLibraryItems 的 WHERE 子句（不含 WHERE 关键字）。

    与 Node 逐条对齐：
    - global==='1' → drama_id IS NULL
    - drama_id 非空 → drama_id = Number(drama_id)
    - category / source_type 精确匹配
    - source_id / source_ids 过滤
    - keyword → 各 keyword_cols 的 LIKE OR
    """
    where = f"FROM {table} WHERE deleted_at IS NULL"
    params: dict[str, Any] = {}

    g = query.get("global")
    if g == "1" or g == 1 or g is True:
        where += " AND drama_id IS NULL"
    elif query.get("drama_id") is not None and query["drama_id"] != "":
        where += " AND drama_id = :drama_id"
        params["drama_id"] = js_parse_int(query["drama_id"], 0)

    if query.get("category"):
        where += " AND category = :category"
        params["category"] = query["category"]
    if query.get("source_type"):
        where += " AND source_type = :source_type"
        params["source_type"] = query["source_type"]

    where = append_source_id_filters(query, where, params)

    kw = query.get("keyword")
    if kw:
        conds = []
        for i, col in enumerate(keyword_cols):
            key = f"kw_{i}"
            conds.append(f"{col} LIKE :{key}")
            params[key] = f"%{kw}%"
        where += " AND (" + " OR ".join(conds) + ")"
    return where, params


def list_paged(
    db: Session, table: str, keyword_cols: list[str], query: dict, row_to_item: Callable[[dict], dict]
) -> tuple[list, int, int, int]:
    """等价 Node listLibraryItems：返回 (items, total, page, pageSize)。"""
    where, params = build_list_where(table, keyword_cols, query)
    total = db.execute(text(f"SELECT COUNT(*) AS total {where}"), params).scalar() or 0
    page = max(1, js_parse_int(query.get("page"), 1))
    page_size = min(100, max(1, js_parse_int(query.get("page_size"), 20)))
    offset = (page - 1) * page_size

    p = dict(params)
    p["_limit"] = page_size
    p["_offset"] = offset
    rows = db.execute(text(f"SELECT * {where} ORDER BY created_at DESC LIMIT :_limit OFFSET :_offset"), p)
    return [row_to_item(dict(r._mapping)) for r in rows], total, page, page_size


def insert_library_item(db: Session, table: str, fields: dict) -> Any:
    """等价 Node insertLibraryItem：剔除 undefined 字段（Python 中即不存在的 key）。

    Node 还会检查 source_id 列是否存在；MySQL 三表均含该列，无需判断。
    """
    names = list(fields.keys())
    placeholders = ", ".join(f":{n}" for n in names)
    sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})"
    return db.execute(text(sql), fields)


def normalize_path_ref(value: Any) -> str:
    """等价 Node normalizePathRef：反斜杠归一、去掉 static/ 前缀。"""
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.replace("\\", "/")
    s = re.sub(r"^/?static/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^/+", "", s)
    return s


def ref_key(value: Any) -> str:
    """等价 Node refKey：data:URL 取 sha256；http(s) 取 url:；本地路径取 path:。"""
    import hashlib

    s = str(value or "").strip()
    if not s:
        return ""
    if s.startswith("data:"):
        return f"data:{hashlib.sha256(s.encode('utf-8')).hexdigest()}"
    if re.match(r"^https?://", s, flags=re.IGNORECASE):
        return f"url:{s}"
    path_ref = normalize_path_ref(s)
    return f"path:{path_ref}" if path_ref else ""


def identity_keys(row: dict) -> set[str]:
    """等价 Node identityKeys：由 source_type+source_id、image_url、local_path 生成去重键集合。"""
    keys: set[str] = set()
    source_id = normalize_source_id(row.get("source_id"))
    if source_id and row.get("source_type"):
        keys.add(f"source:{row['source_type']}:{source_id}")
    image_key = ref_key(row.get("image_url"))
    path_key = ref_key(row.get("local_path"))
    if image_key:
        keys.add(image_key)
    if path_key:
        keys.add(path_key)
    return keys


def find_existing_library_item(
    db: Session, table: str, *, drama_id, source_type, source_id, image_url, local_path
) -> dict | None:
    """等价 Node findExistingLibraryItem：在 scope(drama_id) 内按 source_type 找，再用 identity_keys 去重。"""
    scope_sql = "drama_id IS NULL" if drama_id is None else "drama_id = :scope_drama_id"
    params: dict = {"source_type": source_type}
    if drama_id is not None:
        params["scope_drama_id"] = drama_id
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE deleted_at IS NULL AND source_type = :source_type AND {scope_sql} ORDER BY id ASC"),
        params,
    ).mappings().all()

    wanted = identity_keys(
        {"source_type": source_type, "source_id": source_id, "image_url": image_url, "local_path": local_path}
    )
    if not wanted:
        return None

    for row in rows:
        existing = identity_keys(dict(row))
        if wanted & existing:
            return dict(row)
    return None


def update_existing_library_item(db: Session, table: str, item_id, fields: dict) -> None:
    """等价 Node updateLibraryItem：对存在的库项做字段更新。"""
    names = [n for n in fields.keys()]
    if not names:
        return
    assignments = ", ".join(f"{n} = :{n}" for n in names)
    params = dict(fields)
    params["id"] = item_id
    db.execute(text(f"UPDATE {table} SET {assignments} WHERE id = :id"), params)
