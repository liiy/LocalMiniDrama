"""静态守卫：logging 的 extra 不得使用 LogRecord 保留属性名作为键。

背景：Python 标准库 logging 在 `logger.xxx(msg, extra={...})` 时，若 extra 的键与
LogRecord 的内置属性同名，会抛
    KeyError: Attempt to overwrite 'msg' in LogRecord
其中 `msg` 与 `message` 最易踩中（Node 端日志字段常叫 msg，直译过来就会中招），
且这类代码往往位于 except 分支，会导致**异常处理器自身崩溃**、掩盖真实错误。

本测试用 AST 扫描全仓，防止回归。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"

# logging.LogRecord 的内置属性（部分在 __init__ 中赋值，部分是 property）
RESERVED_KEYS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


def _iter_py_files():
    for p in sorted(APP_DIR.rglob("*.py")):
        yield p


def _expr_key(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _find_violations(path: Path) -> list[tuple[int, str]]:
    """返回 [(行号, 违规键名)]。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:  # pragma: no cover - 语法错误由其它测试/ lint 负责
        return []

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "extra":
                continue
            # extra={...} 字典字面量
            if isinstance(kw.value, ast.Dict):
                for k in kw.value.keys:
                    name = _expr_key(k)
                    if name is not None and name in RESERVED_KEYS:
                        violations.append((kw.value.lineno, name))
            # extra=dict(msg=..., ...) 形式
            elif (
                isinstance(kw.value, ast.Call)
                and isinstance(kw.value.func, ast.Name)
                and kw.value.func.id == "dict"
            ):
                for kw2 in kw.value.keywords:
                    if kw2.arg in RESERVED_KEYS:
                        violations.append((kw.value.lineno, kw2.arg))
    return violations


def test_no_reserved_keys_in_logging_extra() -> None:
    all_violations: list[str] = []
    for path in _iter_py_files():
        for lineno, key in _find_violations(path):
            rel = path.relative_to(ROOT)
            all_violations.append(f"{rel}:{lineno} 使用了保留键 {key!r}")

    assert not all_violations, (
        "logging 的 extra 不得使用 LogRecord 保留属性名（会抛 "
        "KeyError: Attempt to overwrite ... in LogRecord）:\n"
        + "\n".join(all_violations)
    )


def test_logger_rejects_reserved_keys_at_runtime() -> None:
    """运行时验证：确认保留键确实会抛异常（守卫测试的前提成立）。"""
    import logging

    from app.core.logger import get_logger

    log = get_logger("lmd.test_guard")
    with pytest.raises(KeyError):
        log.info("hi", extra={"msg": "boom"})
    with pytest.raises(KeyError):
        log.info("hi", extra={"message": "boom"})
    # 非保留键应正常通过
    log.info("hi", extra={"reason": "ok", "video_gen_id": 1})


def test_logger_outputs_extra_and_redacts_sensitive_keys(capsys) -> None:
    from app.core.logger import get_logger

    log = get_logger("lmd.test_extra_output")
    log.info("with extra", extra={"request_id": "rid-1", "api_key": "sk-secret", "nested": {"token": "secret"}})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["request_id"] == "rid-1"
    assert payload["api_key"] == "***"
    assert payload["nested"]["token"] == "***"
