"""首尾帧提示词后处理：禁止脑补外貌、剔除未勾选角色、清理场景中的人设描写。

对应 Node: backend-node/src/utils/framePromptSanitize.js
"""
from __future__ import annotations

import re
from typing import Any

STEP_KEYS = {
    "NORMALIZE": "normalize_appearance",
    "UNLISTED": "unlisted_character",
    "ORPHAN": "orphan_position",
    "SCENE": "scene_appearance",
    "MODERN_PROP_BOILERPLATE": "modern_prop_boilerplate",
    "PUNCT": "cleanup_punctuation",
}


def parse_character_name_from_anchor_line(line: str | None) -> str | None:
    """从角色锚点行解析角色名。"""
    s = str(line or "").strip()
    if not s:
        return None
    en = re.search(r"^Character:\s*([^;]+)", s, re.IGNORECASE)
    if en:
        return en.group(1).strip()
    zh = re.search(r"^([\u4e00-\u9fa5·]{1,10})", s)
    if zh:
        return zh.group(1).strip()
    return None


def parse_names_from_anchor_lines(anchor_lines: list[str] | None) -> list[str]:
    """从锚点文本行数组解析去重的角色名列表。"""
    names: list[str] = []
    for line in anchor_lines or []:
        n = parse_character_name_from_anchor_line(line)
        if n and n not in names:
            names.append(n)
    return names


def _is_reference_appearance_paren(inner: str) -> bool:
    t = str(inner or "").strip()
    return bool(re.search(r"参考图|reference\s*image", t, re.IGNORECASE))


def normalize_allowed_character_appearance(
    text: str, allowed_names: list[str] | None
) -> tuple[str, list[dict[str, Any]]]:
    """将允许出场角色的括号外貌描写统一为「参考图中的人物形象」。"""
    hits: list[dict[str, Any]] = []
    out = str(text or "")
    for name in allowed_names or []:
        if not name:
            continue
        esc = re.escape(name)

        def _repl_zh(m: re.Match) -> str:
            inner = m.group(1)
            if _is_reference_appearance_paren(inner):
                return m.group(0)
            hits.append({"name": name, "removed_appearance": inner[:120]})
            return f"{name}（参考图中的人物形象）"

        out = re.sub(rf"{esc}（([^）]*)）", _repl_zh, out)

        def _repl_en(m: re.Match) -> str:
            inner = m.group(1)
            if _is_reference_appearance_paren(inner):
                return m.group(0)
            hits.append({"name": name, "removed_appearance": inner[:120]})
            return f"{name}（参考图中的人物形象）"

        out = re.sub(rf"{esc}\(([^)]*)\)", _repl_en, out)
        out = re.sub(
            rf"{esc}\s*\(\s*use appearance from reference image\s*\)",
            f"{name}（参考图中的人物形象）",
            out,
            flags=re.IGNORECASE,
        )
    return out, hits


def strip_unlisted_character_clauses(
    text: str, allowed_names: list[str] | None, all_drama_names: list[str] | None
) -> tuple[str, list[dict[str, Any]]]:
    """剔除剧本中其他角色在本分镜 prompt 里的整段描述。"""
    allowed = set(allowed_names or [])
    candidates = list(dict.fromkeys((all_drama_names or []) + (allowed_names or [])))
    hits: list[dict[str, Any]] = []
    out = str(text or "")

    for name in candidates:
        if not name or name in allowed:
            continue
        esc = re.escape(name)
        before = out
        out = re.sub(rf"[，,]?{esc}（[^）]*）", "", out)
        out = re.sub(rf"[，,]?{esc}(?:位于|站在|坐在|表情|眼神|面向|背对)[^，,]+", "", out)
        if out != before:
            hits.append({"name": name})

    return out, hits


SCENE_APPEARANCE_FRAGMENTS = [
    re.compile(r"面容[\u4e00-\u9fa5a-zA-Z]{0,20}"),
    re.compile(r"眉眼[\u4e00-\u9fa5a-zA-Z]{0,20}"),
    re.compile(r"面部轮廓[\u4e00-\u9fa5a-zA-Z]{0,20}"),
    re.compile(r"眉头微皱"),
    re.compile(r"眼神[\u4e00-\u9fa5]{0,12}"),
    re.compile(r"长发[\u4e00-\u9fa5]{0,16}"),
    re.compile(r"短发[\u4e00-\u9fa5]{0,16}"),
    re.compile(r"束发[\u4e00-\u9fa5]{0,12}"),
    re.compile(r"马尾[\u4e00-\u9fa5]{0,12}"),
    re.compile(r"发色[\u4e00-\u9fa5]{0,12}"),
    re.compile(r"肤质[\u4e00-\u9fa5]{0,12}"),
    re.compile(r"皮肤纹理[\u4e00-\u9fa5]{0,12}"),
    re.compile(r"毛孔清晰可见"),
    re.compile(r"hair\s+(style|color|length)[^,，.]*", re.IGNORECASE),
    re.compile(r"facial\s+features[^,，.]*", re.IGNORECASE),
    re.compile(r"face\s+shape[^,，.]*", re.IGNORECASE),
]


def strip_scene_appearance_fragments(text: str) -> tuple[str, list[dict[str, Any]]]:
    """场景/环境句中常见的外貌描写碎片（无角色名前缀时）。"""
    hits: list[dict[str, Any]] = []
    out = str(text or "")
    scene_seg_re = re.compile(r"(场景为[^，,。]+|环境[^，,。]+|背景[^，,。]{0,80})")

    def _replace_seg(m: re.Match) -> str:
        seg = m.group(0)
        s = seg
        fragment_count = 0
        for pattern in SCENE_APPEARANCE_FRAGMENTS:
            matches = list(pattern.finditer(s))
            if matches:
                fragment_count += len(matches)
                s = pattern.sub("", s)
        cleaned = re.sub(r"[，,]{2,}", "，", s)
        cleaned = re.sub(r"^[，,\s]+|[，,\s]+$", "", cleaned)
        if fragment_count > 0:
            hits.append({"scene_segment_preview": seg[:80], "fragments_removed": fragment_count})
        return cleaned

    out = scene_seg_re.sub(_replace_seg, out)
    return out, hits


def strip_orphan_position_clauses(text: str) -> tuple[str, list[dict[str, Any]]]:
    """未出场角色被删后可能遗留「，位于画面右侧」等无主语站位句。"""
    hits: list[dict[str, Any]] = []
    s_full = str(text or "")

    def _repl(m: re.Match) -> str:
        full = m.group(0)
        clause = m.group(1)
        offset = m.start()
        before = s_full[max(0, offset - 100):offset]
        if re.search(r"人物形象）|reference image\)", before, re.IGNORECASE):
            return full
        hits.append({"removed_clause": clause})
        return ""

    out = re.sub(r"[，,](位于画面[^，,]+)", _repl, s_full)
    return out, hits


MODERN_PROP_BOILERPLATE_PATTERNS = [
    re.compile(
        r"所有道具严格真实物理比例[，,]?智能手机为正常[\d.\-–—]+英寸平放于茶几上[，,]?画面高度占比[\d.%\-–—]+[，,]?绝不可立起或夸大[，,]?茶几高度约[\d]+cm[，,]?书籍和遥控器均为真实家居小尺寸[，,]?所有道具均为次要环境元素"
    ),
    re.compile(r"智能手机为正常[\d.\-–—]+英寸平放于茶几上[，,]?画面高度占比[\d.%\-–—]+[，,]?绝不可立起或夸大"),
    re.compile(r"智能手机(?:\/平板)?(?:为|是)?(?:真实|正常)[\d.\-–—]+英寸[^，,。]*"),
    re.compile(r"书籍和遥控器均为真实家居小尺寸"),
    re.compile(r"遥控器均为真实家居小尺寸"),
    re.compile(r"A5\/A4(?:真实|家居)?尺寸"),
    re.compile(r"画面高度占比(?:严格)?[\d.%\-–—]+(?:以内)?"),
    re.compile(r"平放于茶几(?:表面|上)[^，,。]*"),
    re.compile(r"茶几高度约[\d]+cm"),
]


def strip_modern_prop_boilerplate(text: str) -> tuple[str, list[dict[str, Any]]]:
    """旧版首尾帧模板注入的现代室内道具尺度套话（剔除）。"""
    hits: list[dict[str, Any]] = []
    out = str(text or "")
    for pattern in MODERN_PROP_BOILERPLATE_PATTERNS:
        matches = list(pattern.finditer(out))
        if matches:
            for m in matches:
                hits.append({"removed": m.group(0)[:120]})
            out = pattern.sub("", out)
    return out, hits


def cleanup_punctuation(text: str) -> str:
    """清理多余逗号和空白。"""
    s = str(text or "")
    s = re.sub(r"[，,]{2,}", "，", s)
    s = re.sub(r"，\s*，", "，", s)
    s = re.sub(r"^[，,\s]+|[，,\s]+$", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _record_step(
    report: dict[str, Any], step_key: str, before: str, after: str, hits: list[Any]
) -> dict[str, Any]:
    changed = before != after
    removed_chars = max(0, len(before) - len(after))
    entry = {
        "step": step_key,
        "changed": changed,
        "hit_count": len(hits) if isinstance(hits, list) else 0,
        "removed_chars": removed_chars if changed else 0,
        "hits": hits[:8] if isinstance(hits, list) and hits else None,
    }
    report["steps"].append(entry)
    if changed:
        report["changed_steps"].append(step_key)
        report["removed_chars_by_step"][step_key] = removed_chars
    return entry


def _build_primary_issue(report: dict[str, Any]) -> str | None:
    primary = None
    best_score = 0
    for step in report.get("steps", []):
        if not step.get("changed"):
            continue
        score = step.get("removed_chars", 0) * 10 + step.get("hit_count", 0)
        if score > best_score:
            best_score = score
            primary = step.get("step")
    return primary


def _log_sanitize_report(log: Any, report: dict[str, Any], ctx: dict[str, Any]) -> None:
    if not log or not hasattr(log, "info"):
        return

    base = {
        **ctx,
        "allowed_characters": report.get("allowed_names"),
        "original_len": report.get("original_len"),
        "final_len": report.get("final_len"),
        "total_removed_chars": report.get("total_removed_chars"),
        "changed": report.get("changed"),
        "changed_steps": report.get("changed_steps"),
        "removed_chars_by_step": report.get("removed_chars_by_step"),
        "primary_issue_step": report.get("primary_issue_step"),
    }

    for step in report.get("steps", []):
        if not step.get("changed"):
            continue
        log.info(
            f"[帧提示词清洗] 步骤命中 · {step.get('step')}",
            extra={
                **base,
                "hit_count": step.get("hit_count"),
                "removed_chars": step.get("removed_chars"),
                "hits": step.get("hits"),
            },
        )

    if report.get("changed"):
        steps_ranked = [
            {
                "step": s.get("step"),
                "removed_chars": s.get("removed_chars"),
                "hit_count": s.get("hit_count"),
                "score": s.get("removed_chars", 0) * 10 + s.get("hit_count", 0),
            }
            for s in report.get("steps", [])
            if s.get("changed")
        ]
        steps_ranked.sort(key=lambda x: x["score"], reverse=True)
        log.info(
            "[帧提示词清洗] 汇总（便于统计哪类问题最多）",
            extra={
                **base,
                "step_ranking": steps_ranked,
                "prompt_before_preview": report.get("prompt_before_preview"),
                "prompt_after_preview": report.get("prompt_after_preview"),
            },
        )
    else:
        log.info("[帧提示词清洗] 无需修改", extra=base)


def sanitize_frame_prompt(
    prompt: str | None,
    allowed_names: list[str] | None = None,
    all_drama_names: list[str] | None = None,
    opts: dict[str, Any] | None = None,
) -> str | dict[str, Any]:
    """主入口函数：对提示词执行多步清洗。"""
    if not prompt or not isinstance(prompt, str):
        return prompt or ""

    opts = opts or {}
    original = prompt
    report: dict[str, Any] = {
        "allowed_names": allowed_names or [],
        "original_len": len(original),
        "final_len": 0,
        "total_removed_chars": 0,
        "changed": False,
        "changed_steps": [],
        "removed_chars_by_step": {},
        "steps": [],
        "primary_issue_step": None,
        "prompt_before_preview": original[:200],
        "prompt_after_preview": "",
    }

    text = original

    # Step 1: 规范化允许出场角色的外貌描述
    s1_text, s1_hits = normalize_allowed_character_appearance(text, allowed_names)
    _record_step(report, STEP_KEYS["NORMALIZE"], text, s1_text, s1_hits)
    text = s1_text

    # Step 2: 剔除未出场角色
    s2_text, s2_hits = strip_unlisted_character_clauses(text, allowed_names, all_drama_names)
    _record_step(report, STEP_KEYS["UNLISTED"], text, s2_text, s2_hits)
    text = s2_text

    # Step 3: 清除孤立的站位句
    s3_text, s3_hits = strip_orphan_position_clauses(text)
    _record_step(report, STEP_KEYS["ORPHAN"], text, s3_text, s3_hits)
    text = s3_text

    # Step 4: 清除场景描写中的人设外貌碎片
    s4_text, s4_hits = strip_scene_appearance_fragments(text)
    _record_step(report, STEP_KEYS["SCENE"], text, s4_text, s4_hits)
    text = s4_text

    # Step 5: 清除现代道具套话
    s5_text, s5_hits = strip_modern_prop_boilerplate(text)
    _record_step(report, STEP_KEYS["MODERN_PROP_BOILERPLATE"], text, s5_text, s5_hits)
    text = s5_text

    # Step 6: 标点整理
    before_punct = text
    text = cleanup_punctuation(text)
    _record_step(
        report,
        STEP_KEYS["PUNCT"],
        before_punct,
        text,
        [{"punctuation_cleanup": True}] if before_punct != text else [],
    )

    report["final_len"] = len(text)
    report["total_removed_chars"] = max(0, report["original_len"] - report["final_len"])
    report["changed"] = text != original
    report["primary_issue_step"] = _build_primary_issue(report)
    report["prompt_after_preview"] = text[:200]

    ctx = {
        "source": opts.get("source", "unknown"),
        "storyboard_id": opts.get("storyboard_id"),
        "frame_kind": opts.get("frame_kind"),
        "image_gen_id": opts.get("image_gen_id"),
    }
    _log_sanitize_report(opts.get("log"), report, ctx)

    if opts.get("return_report") or opts.get("returnReport"):
        return {"prompt": text, "report": report}
    return text
