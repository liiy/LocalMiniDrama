"""契约测试：imageClient 的纯函数必须与 backend-node 逐值一致。

覆盖：尺寸规整（Seedream / Agnes / DashScope）、宽高比（Gemini / NanoBanana / Kling）、
协议推断、负面词合并、Gemini imageConfig 组装。

Node 基线：backend-node/node_image_helpers.json
重新生成（在 backend-node 目录下）：
    NODE_OPTIONS="" node ../python-backend/tools/dump_node_image_helpers.js
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE_DIR = ROOT.parent / "backend-node"
BASELINE = NODE_DIR / "node_image_helpers.json"

# 基线键 → Python 可调用对象（延迟导入，避免模块级依赖）
PY_FN_NAMES = {
    "fixSeedreamSize": "fix_seedream_size",
    "fixAgnesImageSize": "fix_agnes_image_size",
    "dashScopeSize": "dash_scope_size",
    "geminiAspectRatio": "gemini_aspect_ratio",
    "nanoBananaAspectRatio": "nano_banana_aspect_ratio",
    "klingImageAspectRatio": "kling_image_aspect_ratio",
    "inferProtocol": "infer_protocol",
    "mergeNegativePromptFragments": "merge_negative_prompt_fragments",
    "buildGeminiImageConfig": "build_gemini_image_config",
    "closestGeminiAspectRatioFromPixels": "closest_gemini_aspect_ratio_from_pixels",
}


def _load_baseline() -> dict:
    if not BASELINE.exists():
        env = dict(os.environ)
        env["NODE_OPTIONS"] = ""
        subprocess.run(
            ["node", str(ROOT / "tools" / "dump_node_image_helpers.js")],
            cwd=NODE_DIR,
            env=env,
            check=False,
            capture_output=True,
        )
    if not BASELINE.exists():
        pytest.skip(f"缺少 Node 基线：{BASELINE}")
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _py_fn(name: str):
    from app.services import imageClient

    return getattr(imageClient, PY_FN_NAMES[name])


def _call(node_key: str, fn, args):
    """基线里单参数用例未包成数组，此处统一归一化。

    buildGeminiImageConfig 的基线入参为 [model, size]，而 Python 签名是
    (aspect_ratio, model_name, size)，需先算出 aspect_ratio。
    """
    if not isinstance(args, list):
        args = [args]
    if node_key == "buildGeminiImageConfig":
        model_name, size = args
        return fn(_py_fn("geminiAspectRatio")(size), model_name, size)
    return fn(*args)


@pytest.mark.parametrize("node_key", list(PY_FN_NAMES))
def test_helpers_match_node(node_key: str) -> None:
    baseline = _load_baseline()
    cases = baseline.get(node_key)
    if not cases:
        pytest.skip(f"基线缺少 {node_key}")
    fn = _py_fn(node_key)

    for args, expected in cases:
        actual = _call(node_key, fn, args)
        assert actual == expected, (
            f"{node_key}({args!r}) 与 Node 不一致\n  node={expected!r}\n  py  ={actual!r}"
        )


def test_anti_split_negative_prompt_matches_node() -> None:
    from app.services import imageClient

    src = (NODE_DIR / "src" / "services" / "imageClient.js").read_text(encoding="utf-8")
    marker = "const ANTI_SPLIT_NEGATIVE_PROMPT = '"
    start = src.index(marker) + len(marker)
    end = src.index("';", start)
    expected = src[start:end]
    assert imageClient.ANTI_SPLIT_NEGATIVE_PROMPT == expected, "ANTI_SPLIT_NEGATIVE_PROMPT 与 Node 不一致"


def test_resolve_image_ref_public_url() -> None:
    """公网 URL 原样返回；本地相对路径在文件存在时转 base64。"""
    from app.services import imageClient

    assert imageClient.resolve_image_ref(
        "https://cdn.example.com/a.png", "http://localhost:5679/static", None
    ) == "https://cdn.example.com/a.png"

    assert imageClient.resolve_image_ref("", "", None) is None
    assert imageClient.resolve_image_ref("   ", "", None) is None


def test_resolve_image_ref_local_file_to_base64(tmp_path) -> None:
    import base64

    from app.services import imageClient

    f = tmp_path / "ref.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    out = imageClient.resolve_image_ref("sub/ref.png", "http://x/static", str(tmp_path))
    # 文件不在 tmp_path/sub 下 → 回退为 public url
    assert out == "http://x/static/sub/ref.png"

    f2 = tmp_path / "ref2.png"
    f2.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    out2 = imageClient.resolve_image_ref("ref2.png", "http://x/static", str(tmp_path))
    assert out2 is not None and out2.startswith("data:image/png;base64,")
    assert base64.b64decode(out2.split(",", 1)[1]) == b"\x89PNG\r\n\x1a\nfake"
