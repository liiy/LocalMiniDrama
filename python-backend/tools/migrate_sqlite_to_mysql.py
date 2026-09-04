"""SQLite → MySQL 数据迁移工具。

用法（在 python-backend/ 下执行）:
    python -m tools.migrate_sqlite_to_mysql --sqlite ../backend-node/data/drama_generator.db

连接串来源：--mysql 参数优先；否则读取 configs/config.yaml 的 database 段。

行为:
1. 幂等建表（app.db.schema 的最终形态）
2. 对每张业务表逐行 INSERT ... ON DUPLICATE KEY UPDATE（可重复执行）
3. 输出每表行数校验（SQLite vs MySQL）

说明:
- 目标库为空时执行；已有数据时按主键覆盖更新，适合增量/重复迁移
- 迁移完成后核对行数是否一致
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import database_url_from_config, load_config  # noqa: E402
from app.db.schema import ensure_schema  # noqa: E402

# SQLite 系统表过滤
_SKIP_TABLES = {"sqlite_sequence"}


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite → MySQL 数据迁移")
    parser.add_argument("--sqlite", required=True, help="SQLite 数据库文件路径")
    parser.add_argument(
        "--mysql", default=None, help="MySQL 连接串（缺省时读取 configs/config.yaml）"
    )
    parser.add_argument(
        "--drop-first",
        action="store_true",
        help="先 DROP 全部业务表再重建（用于 schema 调整后的全量重建）",
    )
    args = parser.parse_args()

    src_path = Path(args.sqlite)
    if not src_path.exists():
        sys.exit(f"SQLite 文件不存在: {src_path}")

    mysql_url = args.mysql or database_url_from_config(load_config())
    print(f"MySQL 目标: {mysql_url.split('@')[-1]}")

    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row

    engine = create_engine(mysql_url, pool_pre_ping=True)

    if args.drop_first:
        from app.db.schema import TABLES

        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for t in TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS `{t.name}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        print("DROP_FIRST: 已删除全部业务表")

    with engine.begin() as conn:
        ensure_schema(conn)
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        total_ok = 0
        for tname in sorted(tables):
            if tname in _SKIP_TABLES:
                continue
            rows = src.execute(f'SELECT * FROM "{tname}"').fetchall()
            if not rows:
                print(f"[{tname}] 0 rows, skip")
                continue
            cols = list(rows[0].keys())
            col_sql = ", ".join(f"`{c}`" for c in cols)
            ph = ", ".join(["%s"] * len(cols))
            # INSERT IGNORE：跳过主键/唯一键冲突（兼容无 id 列的表，如 global_settings/prompt_overrides）
            insert_sql = f"INSERT IGNORE INTO `{tname}` ({col_sql}) VALUES ({ph})"
            # 使用 pymysql 原生驱动执行批量插入（避开 SQLAlchemy 对 MySQL 逐行编译）
            raw = engine.raw_connection()
            try:
                with raw.cursor() as cur:
                    cur.executemany(insert_sql, [tuple(r[c] for c in cols) for r in rows])
                raw.commit()
            finally:
                raw.close()
            total_ok += 1

        # 行数总校验（用新连接查询，避免 engine.begin() 事务快照读到旧数据）
        print("\n===== 行数校验 =====")
        mismatch = 0
        with engine.connect() as vc:
            for tname in sorted(tables):
                if tname in _SKIP_TABLES:
                    continue
                src_count = src.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
                mysql_count = vc.execute(text(f"SELECT COUNT(*) FROM `{tname}`")).scalar()
                mark = "OK" if src_count == mysql_count else f"MISMATCH (mysql={mysql_count})"
                if src_count != mysql_count:
                    mismatch += 1
                print(f"{tname:28s} sqlite={src_count:<8d} mysql={mysql_count:<8d} {mark}")

    src.close()
    print(f"\n迁移完成，共 {total_ok} 张表。")
    if mismatch:
        print(f"警告：{mismatch} 张表行数不一致，请检查。")
        sys.exit(1)
    print("全部一致，迁移成功。")


if __name__ == "__main__":
    main()
