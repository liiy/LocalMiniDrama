"""全能模式 universal_segment_text 统一格式：多子分镜段落（与 Node universalOmniMultiBeatFormat.js 一致）。"""
from __future__ import annotations

from typing import Any

DEFAULT_LINE3 = (
    "环境、光影与陈设定性参考 @图片1。若 @图片1 为宫格或多画面拼图，禁止成片复刻其分格或并列布局，"
    "仅提取统一的室内空间与光线语义；须单镜头完整连续画面。"
)


def _trim(s: Any) -> str:
    return str(s).strip() if s is not None and str(s).strip() else ""


def normalize_universal_segment_text_newlines(text: Any) -> str:
    if not text:
        return ""
    return str(text).replace("\r\n", "\n").replace("\r", "\n").strip()


def choose_beat_count(duration_sec: Any) -> int:
    try:
        dur = max(1, min(120, round(float(duration_sec or 5))))
    except Exception:
        dur = 5
    return min(8, max(1, round(dur / 5)))


def split_duration_seconds(dur: int, m: int) -> list[int]:
    if m <= 0:
        return [dur]
    base = dur // m
    rem = dur - base * m
    return [base + (1 if i < rem else 0) for i in range(m)]


def build_fallback_universal_multi_beat_text(sb: dict | None, d: dict, style_hint: str | None = None) -> str:
    sb = sb or {}
    try:
        dur = max(1, int(d.get("durationSec") or d.get("duration") or 5))
    except Exception:
        dur = 5
    m = choose_beat_count(dur)
    secs = split_duration_seconds(dur, m)
    loc_parts = [p for p in [sb.get("location"), sb.get("time")] if p]
    loc = "，".join(loc_parts).strip() if loc_parts else "叙事空间"
    act = _trim(d.get("action")) or "人物在场景内完成本镜戏核动作"
    res = _trim(d.get("result"))
    dia = _trim(d.get("dialogue"))
    narr = _trim(d.get("narration"))
    atm = _trim(sb.get("atmosphere"))
    style_tail = _trim(style_hint) or "电影感叙事"
    style_line = f"画面风格和类型: 真人写实, 电影风格, 高清画质, {style_tail}"

    lines = [style_line, f"生成一个由以下{m}个分镜组成的视频。", DEFAULT_LINE3]

    for k in range(m):
        tk = secs[k]
        is_first = (k == 0)
        is_last = (k == m - 1)
        body = ""
        if is_first:
            body = (
                f"镜头从 @图片1 的{loc}建立画面起，平稳缓推向戏眼；@图片2 处于{act[:80]}，"
                f"{f'{atm}，' if atm else ''}光影随空间纵深拉开。"
            )
        elif is_last:
            body = f"镜头徐徐拉回或推近收束；@图片2 {res or '完成本镜动作阶段'}，情绪落点明确。"
        else:
            body = f"镜头继续推进，跟住 @图片2 的动作节奏，{act[:100]}，运镜含定镜与缓推轨衔接。"

        if dia and (is_last or (m <= 2 and k == m - 1)):
            clean_dia = dia.replace('"', "")
            body += f' @图片2 说："{clean_dia}"'
        elif not dia:
            body += " 无对白。"

        if narr and is_last:
            clean_narr = narr.replace('"', "")
            body += f' 旁白（画面无声）："{clean_narr}"'

        lines.append(f"分镜{k + 1}： {tk}秒: {body}")

    return "\n".join(lines)
