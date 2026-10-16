"""规范化全能片段里「分镜k： X秒:」时长：单条时对齐总时长；多条时按比例缩放使秒数之和等于 total_sec。

对应 Node: backend-node/src/services/universalSegmentDurationNormalize.js
"""
from __future__ import annotations

import re


def normalize_universal_segment_shot_durations(
    text: str | None,
    duration_label: str | None,
    total_sec: float | int | None,
) -> str:
    """规范化全能片段里「分镜k： X秒:」时长。"""
    if not text or not isinstance(text, str) or not duration_label:
        return text or ""
    try:
        total = float(total_sec)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return text
    if total <= 0:
        return text

    lines = text.splitlines()
    head_re = re.compile(r"^\s*分镜(\d+)\s*[:：]\s*([\d.]+)\s*秒\s*[:：]\s*", re.IGNORECASE)

    hits: list[dict] = []
    for i, line in enumerate(lines):
        m = head_re.match(line)
        if not m:
            continue
        k = int(m.group(1))
        try:
            sec = float(m.group(2))
        except ValueError:
            sec = 1.0
        rest = line[len(m.group(0)) :]
        if k >= 1:
            hits.append({
                "i": i,
                "k": k,
                "sec": sec if sec > 0 else 1.0,
                "rest": rest,
            })

    if not hits:
        return text

    hits.sort(key=lambda h: (h["k"], h["i"]))
    uniq: list[dict] = []
    seen_k = set()
    for h in hits:
        if h["k"] in seen_k:
            continue
        seen_k.add(h["k"])
        uniq.append(h)

    if not uniq:
        return text

    def fmt(x: float) -> str:
        return str(int(x)) if x.is_integer() else str(round(x * 10) / 10)

    if len(uniq) == 1 and uniq[0]["k"] == 1:
        idx = uniq[0]["i"]
        lines[idx] = head_re.sub(f"分镜1： {duration_label}秒: ", lines[idx])
        return "\n".join(lines)

    weights = [max(0.05, h["sec"]) for h in uniq]
    wsum = sum(weights)
    allocated = 0.0
    new_secs: list[float] = []

    for idx in range(len(uniq)):
        if idx == len(uniq) - 1:
            last = round((total - allocated) * 10) / 10
            new_secs.append(max(0.1, last))
        else:
            raw = (total * weights[idx]) / wsum
            v = max(0.1, round(raw * 10) / 10)
            allocated += v
            new_secs.append(v)

    sum_mid = sum(new_secs[:-1])
    new_secs[-1] = max(0.1, round((total - sum_mid) * 10) / 10)
    sum_all = sum(new_secs)

    if sum_all > total + 0.05 or new_secs[-1] < 0.09:
        each = max(0.1, round((total / len(uniq)) * 10) / 10)
        for idx in range(len(uniq) - 1):
            new_secs[idx] = each
        new_secs[-1] = max(0.1, round((total - each * (len(uniq) - 1)) * 10) / 10)

    for j in range(len(uniq)):
        idx = uniq[j]["i"]
        k = uniq[j]["k"]
        lab = fmt(new_secs[j])
        lines[idx] = head_re.sub(f"分镜{k}： {lab}秒: ", lines[idx])

    return "\n".join(lines)


def normalize_universal_segment_at_image_spacing(text: str | None) -> str:
    """全能片段：@图片N 与中英字、引号之间补半角空格，便于模型与接口解析。"""
    if not text or not isinstance(text, str):
        return text or ""
    return re.sub(
        r"@图片(\d+)(?=[\u4e00-\u9fffA-Za-z「『【（])",
        r"@图片\1 ",
        text,
    )

