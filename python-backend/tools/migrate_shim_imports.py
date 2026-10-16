# -*- coding: utf-8 -*-
"""一键扫描与迁移 68 个 camelCase 兼容垫片导入至规范的 snake_case 模块。

操作步骤：
1. 识别 app 下所有标有 Backward compatibility shim 的文件及其目标模块。
2. 批量重写 app/ 和 tests/ 内部的 import 语句，指向 canonical snake_case 路径。
3. 优化垫片文件本身，移除 globals() 动态遍历污染，改为标准 __all__ 显式转发。
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def collect_shims(base_dir: Path) -> dict[str, str]:
    """收集所有垫片模块的全限定名及其目标全限定名。"""
    shims = {}
    for root, _, files in os.walk(base_dir / "app"):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = Path(root) / f
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            m = re.search(r"Backward compatibility shim for (app\.[a-zA-Z0-9_\.]+)", text)
            if m:
                target = m.group(1).strip().rstrip(".")
                module_name = f[:-3]
                rel_pkg = Path(root).relative_to(base_dir).as_posix().replace("/", ".")
                shim_full = f"{rel_pkg}.{module_name}"
                shims[shim_full] = target
    return shims


def build_pkg_mapping(shims: dict[str, str]) -> dict[str, dict[str, str]]:
    """按包组织映射字典：pkg -> {shim_mod_name: target_mod_name}"""
    pkg_shims: dict[str, dict[str, str]] = {}
    for shim_full, target_full in shims.items():
        shim_pkg, shim_mod = shim_full.rsplit(".", 1)
        _, target_mod = target_full.rsplit(".", 1)
        pkg_shims.setdefault(shim_pkg, {})[shim_mod] = target_mod
    return pkg_shims


def transform_content(
    content: str,
    shims: dict[str, str],
    pkg_shims: dict[str, dict[str, str]],
) -> tuple[str, bool]:
    """转换单文件内容中的导入语句。"""
    if "Backward compatibility shim" in content:
        return content, False

    is_crlf = "\r\n" in content
    lines = content.splitlines()
    new_lines = []
    changed = False

    in_paren_pkg: str | None = None

    for line in lines:
        new_line = line

        # 快速跳过非导入行（95% 以上的代码行不是导入语句）
        if "import " not in new_line:
            new_lines.append(new_line)
            continue

        # 检查多行括号开始: from <pkg> import (
        m_paren_start = re.match(r"^\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s*\((.*)$", new_line)
        if m_paren_start:
            pkg = m_paren_start.group(1)
            if pkg in pkg_shims:
                in_paren_pkg = pkg

        if in_paren_pkg:
            has_close = ")" in new_line
            mapping = pkg_shims[in_paren_pkg]
            for shim_name, target_name in mapping.items():
                pat1 = rf"\b{shim_name}\s+as\s+([a-zA-Z0-9_]+)"
                if re.search(pat1, new_line):
                    new_line = re.sub(pat1, rf"{target_name} as \1", new_line)
                    changed = True
                else:
                    pat2 = rf"\b{shim_name}\b"
                    if re.search(pat2, new_line) and not re.search(rf"\bas\s+{shim_name}\b", new_line):
                        new_line = re.sub(pat2, f"{target_name} as {shim_name}", new_line)
                        changed = True
            if has_close:
                in_paren_pkg = None
            new_lines.append(new_line)
            continue

        # 检查 1: from shim_full import ...
        for shim_full, target_full in shims.items():
            pat_from = rf"(\bfrom\s+){re.escape(shim_full)}(\s+import\b)"
            if re.search(pat_from, new_line):
                new_line = re.sub(pat_from, rf"\1{target_full}\2", new_line)
                changed = True

            # 检查 2: import shim_full as alias
            pat_imp_as = rf"(\bimport\s+){re.escape(shim_full)}(\s+as\s+)"
            if re.search(pat_imp_as, new_line):
                new_line = re.sub(pat_imp_as, rf"\1{target_full}\2", new_line)
                changed = True

            # 检查 3: import shim_full (行末或注释前)
            pat_imp = rf"(\bimport\s+){re.escape(shim_full)}(\s*|\s*#.*)$"
            if re.search(pat_imp, new_line):
                shim_mod = shim_full.split(".")[-1]
                new_line = re.sub(pat_imp, rf"\1{target_full} as {shim_mod}\2", new_line)
                changed = True

        # 检查 4: 单行 from <pkg> import item1, item2 ...
        m_from = re.match(r"^(\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s+)(.+)$", new_line)
        if m_from and not m_from.group(3).strip().startswith("("):
            prefix, pkg, items_str = m_from.groups()
            if pkg in pkg_shims:
                mapping = pkg_shims[pkg]
                comment_part = ""
                if "#" in items_str:
                    items_str, comment_part = items_str.split("#", 1)
                    comment_part = "  #" + comment_part
                raw_items = [it.strip() for it in items_str.split(",")]
                updated_items = []
                line_modified = False
                for it in raw_items:
                    if not it:
                        continue
                    parts = it.split()
                    name = parts[0]
                    if name in mapping:
                        target_name = mapping[name]
                        line_modified = True
                        if len(parts) == 1:
                            updated_items.append(f"{target_name} as {name}")
                        elif len(parts) == 3 and parts[1] == "as":
                            updated_items.append(f"{target_name} as {parts[2]}")
                        else:
                            updated_items.append(it)
                    else:
                        updated_items.append(it)
                if line_modified:
                    new_line = prefix + ", ".join(updated_items) + comment_part
                    changed = True

        new_lines.append(new_line)

    separator = "\r\n" if is_crlf else "\n"
    # 末尾保持换行
    return separator.join(new_lines) + (separator if content.endswith(("\r", "\n")) else ""), changed


def upgrade_shim_file(p: Path, target_module: str) -> None:
    """将垫片文件重构成整洁安全的兼容转发，去除 globals() 动态污染。"""
    content = f'''# -*- coding: utf-8 -*-
"""兼容垫片：{p.stem} -> {target_module}。

保留此文件仅用于保障极少部分外部系统或老旧单测的向后兼容性。
业务逻辑与内部调用已全部迁移至规范的 snake_case 模块：`{target_module}`。
"""
from __future__ import annotations

from {target_module} import *  # noqa: F401, F403
import {target_module} as _target

__all__ = getattr(_target, "__all__", [k for k in dir(_target) if not k.startswith("_")])
'''
    p.write_text(content, encoding="utf-8")


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    shims = collect_shims(base_dir)
    pkg_shims = build_pkg_mapping(shims)
    print(f"识别到 {len(shims)} 个垫片模块。")

    updated_files = 0
    for folder in ["app", "tests"]:
        for root, _, files in os.walk(base_dir / folder):
            if "__pycache__" in root or ".venv" in root:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                file_path = Path(root) / f
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                new_content, changed = transform_content(content, shims, pkg_shims)
                if changed:
                    file_path.write_text(new_content, encoding="utf-8")
                    updated_files += 1

    print(f"成功将 {updated_files} 个文件中的历史垫片导入迁移为规范的 snake_case 导入。")

    # 升级所有垫片文件本身
    for shim_full, target_full in shims.items():
        parts = shim_full.split(".")
        shim_file = base_dir.joinpath(*parts).with_suffix(".py")
        if shim_file.exists():
            upgrade_shim_file(shim_file, target_full)

    print("已对所有垫片文件完成安全标准化加固。")


if __name__ == "__main__":
    main()
