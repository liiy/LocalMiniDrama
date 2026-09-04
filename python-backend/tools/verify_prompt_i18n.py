"""校验 app/services/promptI18n.py 的静态表与 Node 版 promptI18n.js 字符级一致。

做法：用 Node 打印两个函数的 JSON 输出，与 Python 侧 json.dumps 结果比对。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE_I18N = ROOT.parent / "backend-node" / "src" / "services" / "promptI18n.js"

sys.path.insert(0, str(ROOT))
from app.services import promptI18n  # noqa: E402

KEYS = [
    "story_expansion_system",
    "storyboard_system",
    "character_extraction",
    "scene_extraction",
    "prop_extraction",
    "storyboard_user_suffix",
    "first_frame_prompt",
    "key_frame_prompt",
    "last_frame_prompt",
]


def node_side() -> dict:
    script = (
        "const m = require(%s);"
        "const keys = %s;"
        "const out = { bodies: {}, suffixes: {} };"
        "for (const k of keys) { out.bodies[k] = m.getDefaultPromptBody(k); out.suffixes[k] = m.getLockedSuffix(k); }"
        "process.stdout.write(JSON.stringify(out));"
    ) % (json.dumps(str(NODE_I18N).replace("\\", "/")), json.dumps(KEYS))
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"node failed: {r.stderr}")
    return json.loads(r.stdout)


def main() -> None:
    n = node_side()
    bad = 0
    for k in KEYS:
        py_b = promptI18n.get_default_prompt_body(k)
        py_s = promptI18n.get_locked_suffix(k)
        if py_b != n["bodies"][k]:
            bad += 1
            print(f"[DIFF body] {k}: py_len={len(py_b)} node_len={len(n['bodies'][k])}")
        if py_s != n["suffixes"][k]:
            bad += 1
            print(f"[DIFF suffix] {k}: py={py_s!r} node={n['suffixes'][k]!r}")
    print("MATCH" if bad == 0 else f"DIFFS={bad}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
