"""列漂移检查：Node（内存 SQLite，经 migrations + ensureAllColumns 建库）vs MySQL 测试库。

背景：Node 的 rowTo* 会引用一些 DB 中并不存在的列。JS 中这些值为 undefined，
JSON.stringify 时键被直接丢弃；Python 用 dict.get() 会得到 None 并输出 null，
导致契约不等价。因此需要识别「MySQL 有、Node 没有」的列，在 rowTo* 中剔除。

用法：python tools/check_column_drift.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LMD_CONFIG_PATH", str(ROOT / "configs" / "config.yaml"))
os.environ["LMD_DATABASE_URL"] = (
    "mysql+pymysql://admin:1qaz2wsX%21@117.72.149.170:3306/drama_genertor_test?charset=utf8mb4"
)

NODE_SCRIPT = r"""
// node -e <script> <arg> 时：process.argv = [node, <arg>]
const WS = process.argv[1];
// migrate.js 会 console.log 迁移进度，会污染 stdout 上的 JSON
console.log = () => {};
console.warn = () => {};
const path = require('path');
const Database = require(path.join(WS, 'backend-node', 'node_modules', 'better-sqlite3'));
const NODE_SRC = path.join(WS, 'backend-node', 'src');
const db = new Database(':memory:');
const { runMigrationsAndEnsure } = require(path.join(NODE_SRC, 'db', 'migrate.js'));
runMigrationsAndEnsure(db);
const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").all();
const out = {};
for (const t of tables) {
  out[t.name] = db.prepare(`PRAGMA table_info(${t.name})`).all().map(r => r.name);
}
process.stdout.write(JSON.stringify(out));
"""

TABLES = [
    "dramas",
    "episodes",
    "characters",
    "scenes",
    "props",
    "storyboards",
    "storyboard_props",
    "storyboard_characters",
    "frame_prompts",
    "episode_characters",
    "episode_scenes",
    "character_libraries",
    "scene_libraries",
    "prop_libraries",
    "ai_model_map",
    "prompt_overrides",
    "global_settings",
    "async_tasks",
    "image_generations",
    "video_generations",
    "video_merges",
    "assets",
    "ai_service_configs",
    "image_proxy_cache",
]


def node_columns(workspace: Path) -> dict[str, list[str]]:
    r = subprocess.run(
        ["node", "-e", NODE_SCRIPT, str(workspace)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if r.returncode != 0:
        raise SystemExit(f"node failed: {r.stderr}")
    return json.loads(r.stdout)


def main() -> int:
    from sqlalchemy import text

    from app.db import session as dbm
    from app.db.schema import ensure_schema

    dbm.init_engine()
    with dbm.engine.begin() as conn:
        ensure_schema(conn)
        mysql_cols: dict[str, list[str]] = {}
        for t in TABLES:
            rows = conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"
                ),
                {"t": t},
            ).scalars().all()
            if rows:
                mysql_cols[t] = list(rows)

    node_cols = node_columns(ROOT.parent)

    drift = 0
    for t in sorted(set(mysql_cols) | set(node_cols)):
        n = set(node_cols.get(t, []))
        m = set(mysql_cols.get(t, []))
        if not n and not m:
            continue
        only_mysql = sorted(m - n)
        only_node = sorted(n - m)
        if only_mysql or only_node:
            drift += 1
            print(f"\n[{t}]")
            if only_mysql:
                print(f"  仅 MySQL 有（rowTo* 需剔除，否则 Python 输出 null 而 Node 丢弃键）: {only_mysql}")
            if only_node:
                print(f"  仅 Node 有（Python schema 缺列）: {only_node}")
    print(f"\nTABLES_WITH_DRIFT={drift}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
