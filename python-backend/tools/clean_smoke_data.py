"""清理冒烟测试残留数据（仅删除 smoke_ 前缀的记录）。

用法：python tools/clean_smoke_data.py           # 默认操作生产库 drama_genertor
      python tools/clean_smoke_data.py --test    # 操作测试库
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_URL_TEST = "mysql+pymysql://admin:1qaz2wsX%21@117.72.149.170:3306/drama_genertor_test?charset=utf8mb4"
DB_URL_PROD = "mysql+pymysql://admin:1qaz2wsX%21@117.72.149.170:3306/drama_genertor?charset=utf8mb4"

# (表, 参与匹配的文本列)
TARGETS = [
    ("dramas", "title"),
    ("ai_model_map", "key"),
    ("character_libraries", "name"),
    ("scene_libraries", "location"),
    ("prop_libraries", "name"),
    ("characters", "name"),
    ("scenes", "location"),
    ("props", "name"),
    ("episodes", "title"),
    ("storyboards", "title"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="操作测试库而非生产库")
    args = ap.parse_args()

    os.environ["LMD_DATABASE_URL"] = DB_URL_TEST if args.test else DB_URL_PROD
    os.environ.setdefault("LMD_CONFIG_PATH", str(ROOT / "configs" / "config.yaml"))

    from sqlalchemy import text

    from app.db import session as dbm

    dbm.init_engine()
    total = 0
    with dbm.engine.begin() as conn:
        for table, col in TARGETS:
            try:
                n = conn.execute(
                    text(f"DELETE FROM `{table}` WHERE `{col}` LIKE 'smoke%'")
                ).rowcount
            except Exception as e:
                print(f"[skip] {table}: {e}")
                continue
            if n:
                print(f"{table}: deleted {n}")
            total += n
    print(f"total deleted = {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
