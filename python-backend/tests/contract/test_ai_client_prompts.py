"""契约测试：aiClient.EXTRACT_PROMPTS 的提示词文案必须与 backend-node 逐字一致。

Node 侧基线由 `tools/dump_node_prompts.js` 生成到 backend-node/node_prompts.json。
重新生成基线（在 backend-node 目录下）：
    node tools/dump_node_prompts.js
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE_DIR = ROOT.parent / "backend-node"
BASELINE = NODE_DIR / "node_prompts.json"

ENTITY_TYPES = ("character", "scene", "prop")


def _load_baseline() -> dict:
    if not BASELINE.exists():
        script = ROOT / "tools" / "dump_node_prompts.js"
        env = dict(__import__("os").environ)
        env["NODE_OPTIONS"] = ""
        subprocess.run(
            ["node", str(script)],
            cwd=NODE_DIR,
            check=True,
            env=env,
            capture_output=True,
        )
    if not BASELINE.exists():
        pytest.skip(f"缺少 Node 提示词基线：{BASELINE}")
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_extract_prompts_match_node() -> None:
    from app.services import aiClient

    baseline = _load_baseline()
    for et in ENTITY_TYPES:
        expected = baseline[et]
        actual = aiClient.EXTRACT_PROMPTS[et]
        assert actual["system"] == expected["system"], f"{et}.system 与 Node 不一致"
        assert actual["user"]("X") == expected["user"], f"{et}.user(name) 与 Node 不一致"
        assert actual["user"]("") == expected["userNoName"], f"{et}.user('') 与 Node 不一致"


def test_is_refusal_response_matches_node_patterns() -> None:
    """Node 的 8 条拒绝模式必须全部命中，且普通描述不误判。"""
    from app.services import aiClient

    refusal_samples = [
        "抱歉，我无法识别图中的人物。",
        "无法识别人物身份特征",
        "I cannot identify the person in this image.",
        "I'm unable to identify anyone here.",
        "我无法分析人物的面部",
        "无法描述人物外貌",
    ]
    for text in refusal_samples:
        assert aiClient.is_refusal_response(text), f"应判定为拒绝：{text}"

    normal_samples = [
        "这是一位黑色长发的女性角色，瓜子脸，身着红色长裙。",
        "古色古香的庭院，光线柔和。",
        "",
    ]
    for text in normal_samples:
        assert not aiClient.is_refusal_response(text), f"不应判定为拒绝：{text}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
