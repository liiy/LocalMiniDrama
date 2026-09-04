"""一次性核查：对比 node_probe.js 与权威 backend-node/src/routes/index.js 的路由注册。

用于发现"探针与 Python 同时用错方法/路径"导致的假阴性（DIFFS=0 但契约实际不一致）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDX = ROOT / "backend-node" / "src" / "routes" / "index.js"
PROBE = ROOT / "python-backend" / "tools" / "node_probe.js"

PAT = re.compile(r"r\.(get|post|put|delete)\(\s*'([^']+)'")


def norm(path: str) -> str:
    """去掉 /api/v1 前缀，并把路径参数 :id / {id} 统一为 {}。"""
    p = re.sub(r"^/api/v1", "", path)
    return re.sub(r":\w+", "{}", p)


def collect(src: str) -> set[tuple[str, str]]:
    return {(m.group(1).upper(), norm(m.group(2))) for m in PAT.finditer(src)}


def main() -> int:
    idx = collect(IDX.read_text(encoding="utf-8"))
    probe = collect(PROBE.read_text(encoding="utf-8"))

    only_idx = sorted(idx - probe)
    only_probe = sorted(probe - idx)

    # 路径相同但方法不同
    idx_paths = {p for _, p in idx}
    probe_paths = {p for _, p in probe}
    method_mismatch = []
    for p in sorted(idx_paths & probe_paths):
        im = sorted(m for m, pp in idx if pp == p)
        pm = sorted(m for m, pp in probe if pp == p)
        if im != pm:
            method_mismatch.append((p, im, pm))

    print(f"index.js 路由数={len(idx)}  node_probe.js 路由数={len(probe)}")
    print(f"\n[探针缺失] index 有、探针无：{len(only_idx)}")
    for m, p in only_idx:
        print(f"  {m:6} {p}")
    print(f"\n[探针多余] 探针有、index 无：{len(only_probe)}")
    for m, p in only_probe:
        print(f"  {m:6} {p}")
    print(f"\n[方法错配] 路径相同但方法不同：{len(method_mismatch)}")
    for p, im, pm in method_mismatch:
        print(f"  {p}\n    index={im}  probe={pm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
