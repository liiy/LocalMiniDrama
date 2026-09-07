"""清理冒烟测试残留数据（仅删除 smoke_ 前缀的记录）。

用法：python tools/clean_smoke_data.py --database-url <URL>
      LMD_TEST_DATABASE_URL=<URL> python tools/clean_smoke_data.py --test
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import load_environment_file  # noqa: E402

# 独立清理脚本也读取项目 .env，但仍要求调用者明确选择生产库或测试库。
load_environment_file()

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
    ap.add_argument("--database-url", help="目标数据库 URL；优先级高于环境变量")
    args = ap.parse_args()

    env_name = "LMD_TEST_DATABASE_URL" if args.test else "LMD_DATABASE_URL"
    database_url = args.database_url or os.environ.get(env_name)
    if not database_url:
        raise SystemExit(f"必须通过 --database-url 或 {env_name} 显式指定目标数据库")
    # 清理属于高风险操作，只接受调用者本次明确提供的连接地址。
    os.environ["LMD_DATABASE_URL"] = database_url
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
