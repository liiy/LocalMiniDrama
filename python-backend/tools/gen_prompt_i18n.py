"""从 backend-node/src/services/promptI18n.js 提取纯静态函数，生成 Python 常量表。

用途：getDefaultPromptBody / getLockedSuffix 是纯 switch-case 静态字符串表，
手工复制易错，故用脚本按字符原样抽取生成，保证与 Node 版字节级一致。

JS 单引号字符串与 Python 单引号字符串的转义语义一致（\\n \\t \\r \\\\ \\' \\uXXXX），
因此 literal 可原样复用。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

NODE_I18N = Path(__file__).resolve().parent.parent.parent / "backend-node" / "src" / "services" / "promptI18n.js"

CASE_RE = re.compile(r"^\s*case '([^']+)':\s*$")
RET_RE = re.compile(r"^\s*return ('(?:[^'\\]|\\.)*'|null);\s*$")


def extract(fn_name: str, src: str) -> list[tuple[str, str]]:
    start = src.index(f"function {fn_name}(key) {{")
    end = src.index("\n}\n", start)
    block = src[start:end]
    entries: list[tuple[str, str]] = []
    pending: list[str] = []
    for line in block.splitlines():
        m = CASE_RE.match(line)
        if m:
            pending.append(m.group(1))
            continue
        m = RET_RE.match(line)
        if m and pending:
            raw = m.group(1)
            for key in pending:
                entries.append((key, raw))
            pending = []
    return entries


def render(var_name: str, entries: list[tuple[str, str]]) -> str:
    out = [f"{var_name}: dict[str, str | None] = {{"]
    for key, raw in entries:
        val = "None" if raw == "null" else raw
        out.append(f'    "{key}": {val},')
    out.append("}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="app/services/promptI18n.py")
    args = ap.parse_args()

    src = NODE_I18N.read_text(encoding="utf-8")
    bodies = extract("getDefaultPromptBody", src)
    suffixes = extract("getLockedSuffix", src)

    header = '''"""提示词静态表（P2 阶段：仅覆盖管理端所需部分）。

来源：backend-node/src/services/promptI18n.js
- getDefaultPromptBody(key) / getLockedSuffix(key) 由 tools/gen_prompt_i18n.py 自动抽取生成，
  与 Node 版字符级一致，禁止手工编辑这两个表。
- 内存覆盖缓存 _override_cache 与 Node 的 promptI18n 模块级缓存语义一致。

P4 阶段将继续翻译 promptI18n 的其余动态函数（各 get*Prompt(cfg)）。
"""
from __future__ import annotations

'''

    tail = '''

_override_cache: dict[str, str] = {}


def load_overrides_into_cache(overrides) -> None:
    """等价 Node loadOverridesIntoCache(overrides)：启动时把 DB 覆盖灌入内存。"""
    for o in overrides or []:
        _override_cache[o["key"]] = o["content"]


def set_override_in_memory(key: str, content: str) -> None:
    _override_cache[key] = content


def clear_override_in_memory(key: str) -> None:
    _override_cache.pop(key, None)


def get_default_prompt_body(key: str) -> str:
    return DEFAULT_BODIES.get(key, "")


def get_locked_suffix(key: str) -> str | None:
    return LOCKED_SUFFIXES.get(key)


def get_body_with_override(key: str) -> str:
    """返回生效正文：优先内存覆盖，否则默认正文。"""
    return _override_cache.get(key) or DEFAULT_BODIES.get(key, "")
'''

    content = (
        header
        + render("DEFAULT_BODIES", bodies)
        + "\n\n"
        + render("LOCKED_SUFFIXES", suffixes)
        + "\n"
        + tail
    )
    target = Path(__file__).resolve().parent.parent / args.target
    target.write_text(content, encoding="utf-8")
    print(f"written {target} bodies={len(bodies)} suffixes={len(suffixes)}")


if __name__ == "__main__":
    main()
