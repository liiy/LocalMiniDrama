"""剧集画风合并工具。

与 backend-node/src/utils/dramaStyleMerge.js 严格对齐：
- parse_drama_metadata
- style_fields_from_drama_row
- expand_style_slot_if_preset_key
- merge_cfg_style_with_drama
- resolved_stream_style_from_drama
"""
from __future__ import annotations

import json
from typing import Any

from app.constants.generationStylePresets import resolve_style_preset


def parse_drama_metadata(drama_row: Any) -> dict:
    if not drama_row:
        return {}
    meta = drama_row.get("metadata") if isinstance(drama_row, dict) else getattr(drama_row, "metadata", None)
    if not meta:
        return {}
    if isinstance(meta, str):
        try:
            return json.loads(meta)
        except Exception:
            return {}
    if isinstance(meta, dict):
        return meta
    return {}


def style_fields_from_drama_row(drama_row: Any) -> dict[str, str]:
    if not drama_row:
        return {"zh": "", "en": "", "legacy": ""}
    meta = parse_drama_metadata(drama_row)
    zh = str(meta["style_prompt_zh"]).strip() if meta.get("style_prompt_zh") is not None else ""
    en = str(meta["style_prompt_en"]).strip() if meta.get("style_prompt_en") is not None else ""
    raw_style = drama_row.get("style") if isinstance(drama_row, dict) else getattr(drama_row, "style", None)
    legacy = str(raw_style).strip() if raw_style is not None else ""
    return {"zh": zh, "en": en, "legacy": legacy}


def expand_style_slot_if_preset_key(style_obj: Any) -> Any:
    if not isinstance(style_obj, dict):
        return style_obj
    o = dict(style_obj)
    zh = str(o.get("default_style_zh") or "").strip()
    en = str(o.get("default_style_en") or "").strip()
    if zh or en:
        return o
    d = str(o.get("default_style") or "").strip()
    if not d:
        return o
    preset = resolve_style_preset(d)
    if not preset:
        return o
    o["default_style_zh"] = preset["zh"]
    o["default_style_en"] = preset["en"]
    o["default_style"] = preset["en"] or preset["zh"]
    return o


def merge_cfg_style_with_drama(cfg: dict | None, drama_row: Any) -> dict:
    fields = style_fields_from_drama_row(drama_row)
    zh, en, legacy = fields["zh"], fields["en"], fields["legacy"]
    base = dict((cfg or {}).get("style") or {})
    has_meta = bool(zh or en)
    if has_meta:
        if zh:
            base["default_style_zh"] = zh
        else:
            base.pop("default_style_zh", None)
        if en:
            base["default_style_en"] = en
        else:
            base.pop("default_style_en", None)
        base["default_style"] = en or zh
    elif legacy:
        preset = resolve_style_preset(legacy)
        if preset:
            base["default_style_zh"] = preset["zh"]
            base["default_style_en"] = preset["en"]
            base["default_style"] = preset["en"] or preset["zh"]
        elif legacy == "custom":
            pass
        else:
            base["default_style_zh"] = legacy
            base["default_style_en"] = legacy
            base["default_style"] = legacy

    res = dict(cfg or {})
    res["style"] = expand_style_slot_if_preset_key(base)
    return res


def resolved_stream_style_from_drama(style_param: str | None, drama_row: Any) -> str:
    s = str(style_param or "").strip()
    if s and s != "custom":
        p = resolve_style_preset(s)
        return (p.get("en") or p.get("zh")) if p else s
    fields = style_fields_from_drama_row(drama_row)
    zh, en, legacy = fields["zh"], fields["en"], fields["legacy"]
    if en or zh:
        return en or zh
    if legacy and legacy != "custom":
        p = resolve_style_preset(legacy)
        return (p.get("en") or p.get("zh")) if p else legacy
    return "realistic"


def apply_style_override_to_cfg(cfg: dict | None, style_override: Any) -> dict:
    o = str(style_override or "").strip()
    if not o:
        return dict(cfg or {})
    res = dict(cfg or {})
    style = dict(res.get("style") or {})
    style["default_style_zh"] = o
    style["default_style_en"] = o
    style["default_style"] = o
    res["style"] = style
    return res


# 驼峰别名与 Node 兼容
applyStyleOverrideToCfg = apply_style_override_to_cfg
mergeCfgStyleWithDrama = merge_cfg_style_with_drama
