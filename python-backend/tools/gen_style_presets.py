"""从 backend-node/src/constants/generationStylePresets.js 生成 Python 常量表。

画风预设是 44 条长文本，手工复制极易出错，故用 Node 输出 JSON 后自动生成。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE_FILE = ROOT.parent / "backend-node" / "src" / "constants" / "generationStylePresets.js"


def main() -> None:
    script = (
        "const m = require(%s);"
        "const out = { presets: m.PRESET_VALUES.map(v => ({ value: v, ...m.resolveStylePreset(v) })) };"
        "process.stdout.write(JSON.stringify(out));"
    ) % json.dumps(str(NODE_FILE).replace("\\", "/"))
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"node failed: {r.stderr}")
    data = json.loads(r.stdout)

    lines = [
        '"""画风预设（由 tools/gen_style_presets.py 自动生成，禁止手工编辑）。',
        "",
        "来源：backend-node/src/constants/generationStylePresets.js",
        "用途：DB 仅有 dramas.style（下拉 value）而无 metadata.style_prompt_* 时，展开为完整提示词。",
        '"""',
        "from __future__ import annotations",
        "",
        "",
        "PRESETS: dict[str, dict[str, str]] = {",
    ]
    for p in data["presets"]:
        lines.append(f'    {p["value"]!r}: {{')
        lines.append(f'        "zh": {p["zh"]!r},')
        lines.append(f'        "en": {p["en"]!r},')
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def resolve_style_preset(legacy) -> dict[str, str] | None:")
    lines.append('    """等价 Node resolveStylePreset：仅当完全匹配预设 value 时返回 { zh, en }。"""')
    lines.append("    if legacy is None:")
    lines.append("        return None")
    lines.append("    k = str(legacy).strip()")
    lines.append("    if not k:")
    lines.append("        return None")
    lines.append("    return PRESETS.get(k)")
    lines.append("")

    target = ROOT / "app" / "constants" / "generationStylePresets.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {target} presets={len(data['presets'])}")


if __name__ == "__main__":
    main()
