"""契约测试：videoClient 的纯函数必须与 backend-node 逐值一致。

覆盖：协议推断、画幅归一化、时长归一（火山/Seedance/Omni/MiniMax）、
URL 拼装（火山/Agnes/MiniMax/通用）、模型别名、各厂商响应解析。

Node 基线：backend-node/node_video_helpers.json
重新生成（在 backend-node 目录下）：
    NODE_OPTIONS="" node ../python-backend/tools/dump_node_video_helpers.js
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE_DIR = ROOT.parent / "backend-node"
BASELINE = NODE_DIR / "node_video_helpers.json"

# Node 侧导出名 → Python 函数名（参数签名一致的可直接 *args）
PY_FN_NAMES = {
    "inferVideoProtocol": "infer_video_protocol",
    "isMinimaxH3Model": "is_minimax_h3_model",
    "resolveVideoProtocol": "resolve_video_protocol",
    "parseConfigSettingsJson": "parse_config_settings_json",
    "normalizeAspectRatioForApi": "normalize_aspect_ratio_for_api",
    "omniDurationString": "omni_duration_string",
    "isSeedance2FamilyModel": "is_seedance2_family_model",
    "normalizeVolcengineDuration": "normalize_volcengine_duration",
    "normalizeVolcOmniDuration": "normalize_volc_omni_duration",
    "normalizeMinimaxH3Duration": "normalize_minimax_h3_duration",
    "normalizeMinimaxH3Resolution": "normalize_minimax_h3_resolution",
    "getAgnesApiRoot": "get_agnes_api_root",
    "isAgnesBuiltinQueryEndpoint": "is_agnes_builtin_query_endpoint",
    "getMinimaxApiRoot": "get_minimax_api_root",
    "normalizeVolcModel": "normalize_volc_model",
    "getModelFromConfig": "get_model_from_config",
    "isPlausibleHttpVideoUrl": "is_plausible_http_video_url",
    "coerceHttpVideoUrl": "coerce_http_video_url",
    "extractPollTaskStatus": "extract_poll_task_status",
    "isPollTaskFailed": "is_poll_task_failed",
    "videoUrlFromRecord": "video_url_from_record",
    "videoUrlFromArkVideoNode": "video_url_from_ark_video_node",
    "pickVideoUrlFromItemList": "pick_video_url_from_item_list",
    "pickVideoUrlFromResultShape": "pick_video_url_from_result_shape",
    "pickProxyVideoUrl": "pick_proxy_video_url",
    "extractAgnesVideoUrl": "extract_agnes_video_url",
    "extractMinimaxH3VideoUrl": "extract_minimax_h3_video_url",
}

# 以 dict 为入参、需要展开为关键字参数的函数
KWARG_FNS = {
    "getVolcVideoBase": ("get_volc_video_base", ("config",)),
    "buildVideoUrl": ("build_video_url", ("config", "options")),
    "buildAgnesPollUrl": ("build_agnes_poll_url", ("config", "poll_id")),
    "buildQueryUrl": ("build_query_url", ("config", "task_id")),
    "buildMinimaxH3PollUrl": ("build_minimax_h3_poll_url", ("config", "task_id")),
    "buildAgnesVideoImagePayload": (
        "build_agnes_video_image_payload",
        ("use_omni_reference", "resolved_refs", "first_resolved", "last_resolved"),
    ),
}


def _load_baseline() -> dict:
    if not BASELINE.exists():
        env = dict(os.environ)
        env["NODE_OPTIONS"] = ""
        subprocess.run(
            ["node", str(ROOT / "tools" / "dump_node_video_helpers.js")],
            cwd=NODE_DIR,
            env=env,
            check=False,
            capture_output=True,
        )
    if not BASELINE.exists():
        pytest.skip(f"缺少 Node 基线：{BASELINE}")
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _py_fn(name: str):
    from app.services import videoClient

    return getattr(videoClient, name)


def _camel_to_snake(k: str) -> str:
    import re as _re

    return _re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()


def _to_kwargs(args, arg_names: tuple) -> dict:
    """把基线的入参形态归一为 Python 关键字参数。

    基线里单参数用例可能是：
    - 标量（如 getMinimaxApiRoot 的 base_url）
    - 数组（如 buildVideoUrl 的 [config, options]）
    - 单个 options 对象（如 buildAgnesVideoImagePayload 的驼峰键对象）
    - 单个 config 对象（如 getVolcVideoBase 的 { base_url }）
    """
    if isinstance(args, dict):
        # 键是目标参数名（驼峰或下划线）→ 视为关键字参数对象
        normalized = {_camel_to_snake(k): v for k, v in args.items()}
        if set(normalized).issubset(set(arg_names)):
            return normalized
        # 否则整体作为第一个命名参数
        return {arg_names[0]: args}
    call_args = args if isinstance(args, list) else [args]
    return dict(zip(arg_names, call_args))


@pytest.mark.parametrize("node_key", list(PY_FN_NAMES))
def test_helpers_match_node(node_key: str) -> None:
    baseline = _load_baseline()
    cases = baseline.get(node_key)
    if not cases:
        pytest.skip(f"基线缺少 {node_key}")
    fn = _py_fn(PY_FN_NAMES[node_key])

    import inspect

    n_params = len(inspect.signature(fn).parameters)

    for args, expected in cases:
        # 单参函数：基线里的数组就是实参本身（空数组 [] 是合法输入，不能被当成"无参数"）
        if n_params == 1:
            call_args = [args]
        else:
            call_args = args if isinstance(args, list) else [args]
        actual = fn(*call_args)
        assert actual == expected, (
            f"{node_key}({call_args!r}) 与 Node 不一致\n  node={expected!r}\n  py  ={actual!r}"
        )


@pytest.mark.parametrize("node_key", list(KWARG_FNS))
def test_kwargs_helpers_match_node(node_key: str) -> None:
    baseline = _load_baseline()
    cases = baseline.get(node_key)
    if not cases:
        pytest.skip(f"基线缺少 {node_key}")
    py_name, arg_names = KWARG_FNS[node_key]
    fn = _py_fn(py_name)

    for args, expected in cases:
        kwargs = _to_kwargs(args, arg_names)
        actual = fn(**kwargs)
        assert actual == expected, (
            f"{node_key}({kwargs!r}) 与 Node 不一致\n  node={expected!r}\n  py  ={actual!r}"
        )
