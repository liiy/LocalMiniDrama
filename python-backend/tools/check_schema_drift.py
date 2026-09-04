"""schema 漂移对比 + 数据行数校验工具。

用法:
    python -m tools.check_schema_drift                 # 全量扫描所有表，打印漂移列
    python -m tools.check_schema_drift <table>         # 打印单表在 SQLite 中的完整列定义
    python -m tools.check_schema_drift --counts        # 对比 SQLite 与 MySQL 各行数（独立连接）
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.config import database_url_from_config, load_config  # noqa: E402
from app.db import session as dbm  # noqa: E402
from app.db.schema import TABLES  # noqa: E402

DB = Path(__file__).resolve().parent.parent.parent / "backend-node" / "data" / "drama_generator.db"


def _show_table(src: sqlite3.Connection, table: str) -> None:
    print(f"--- {table} ---")
    for r in src.execute(f'PRAGMA table_info("{table}")'):
        print(r[1], r[2], "NOT NULL" if r[3] else "", r[4] if r[4] is not None else "")


def _counts() -> None:
    src = sqlite3.connect(str(DB))
    dbm.init_engine()
    with dbm.engine.connect() as conn:
        for t in sorted(TABLES, key=lambda x: x.name):
            try:
                s = src.execute(f'SELECT COUNT(*) FROM "{t.name}"').fetchone()[0]
            except Exception:
                continue
            m = conn.execute(text(f"SELECT COUNT(*) FROM `{t.name}`")).scalar()
            mark = "OK" if s == m else f"DIFF"
            print(f"{t.name:28s} sqlite={s:<8d} mysql={m:<8d} {mark}")
    src.close()
    print("COUNTS_DONE")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--counts":
        _counts()
        return
    src = sqlite3.connect(str(DB))
    if len(sys.argv) > 1:
        _show_table(src, sys.argv[1])
    else:
        for t in TABLES:
            try:
                sqlite_cols = [r[1] for r in src.execute(f'PRAGMA table_info("{t.name}")')]
            except Exception as e:
                print("NO_TABLE", t.name, e)
                continue
            mysql_cols = [c.name for c in t.columns]
            missing = [c for c in sqlite_cols if c not in mysql_cols]
            extra = [c for c in mysql_cols if c not in sqlite_cols]
            if missing or extra:
                print(f"{t.name}: MISSING={missing} EXTRA={extra}")
        print("SCAN_DONE")
    src.close()


if __name__ == "__main__":
    main()
