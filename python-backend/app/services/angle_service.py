"""镜头角度/摄影参数服务 — 契约翻译 backend-node/src/services/angleService.js。

仅移植无 AI 依赖的纯推断函数 inferPhotographyParams（批量补全老分镜用）。
其余 AI 相关函数（toPromptFragment 等）按需补充。
"""
from __future__ import annotations

import re
from typing import Any, Optional

HORIZONTAL_DESC: dict[str, str] = {
    "front": "shooting from the front",
    "front_left": "shooting from front-left at 45-degree angle",
    "left": "shooting from the left side, profile view",
    "back_left": "shooting from back-left at 135-degree angle",
    "back": "shooting from behind, character's back to camera",
    "back_right": "shooting from back-right at 135-degree angle",
    "right": "shooting from the right side, profile view",
    "front_right": "shooting from front-right at 45-degree angle",
}

ELEVATION_DESC: dict[str, str] = {
    "worm": "extreme low-angle worm's eye view, camera near ground pointing sharply upward, strong upward perspective distortion, background shows sky/ceiling",
    "low": "low-angle upward shot, camera below eye-line, slight upward tilt, empowering perspective",
    "eye_level": "eye-level shot, neutral perspective, natural horizontal framing",
    "high": "high-angle bird's eye view, camera above looking down, background shows floor/ground with downward perspective distortion",
}

SHOT_SIZE_DESC: dict[str, str] = {
    "close_up": "close-up shot (face/bust framing), subject fills most of frame, shallow depth of field, background softly blurred",
    "medium": "medium shot (waist-up to full body), character and immediate surroundings visible, moderate depth of field",
    "wide": "wide shot (full body with environment), subject small relative to scene, deep depth of field, environment context prominent",
}

ZH_H_MAP = [
    {"keys": ["背后", "背面", "从背", "back"], "val": "back"},
    {"keys": ["前左", "左前", "front-left", "front_left"], "val": "front_left"},
    {"keys": ["前右", "右前", "front-right", "front_right"], "val": "front_right"},
    {"keys": ["左侧", "正侧", "侧面", "side", "left"], "val": "left"},
    {"keys": ["右侧", "right"], "val": "right"},
    {"keys": ["后左", "左后", "back-left", "back_left"], "val": "back_left"},
    {"keys": ["后右", "右后", "back-right", "back_right"], "val": "back_right"},
    {"keys": ["正面", "前方", "面向", "front"], "val": "front"},
]

ZH_V_MAP = [
    {"keys": ["虫眼", "极低", "worm"], "val": "worm"},
    {"keys": ["仰", "low angle", "low-angle"], "val": "low"},
    {"keys": ["俯", "high angle", "bird"], "val": "high"},
    {"keys": ["平视", "eye-level", "eye level"], "val": "eye_level"},
]

ZH_S_MAP = [
    {"keys": ["特写", "近景", "close"], "val": "close_up"},
    {"keys": ["全景", "远景", "大全", "wide", "long shot", "establishing"], "val": "wide"},
    {"keys": ["中景", "半身", "medium"], "val": "medium"},
]


def _match_map(text: str, m_list: list[dict]) -> str | None:
    t = text.lower()
    for entry in m_list:
        for k in entry["keys"]:
            if k.lower() in t:
                return entry["val"]
    return None


def to_prompt_fragment(h: str, v: str, s: str) -> str:
    h_desc = HORIZONTAL_DESC.get(h, HORIZONTAL_DESC["front"])
    v_desc = ELEVATION_DESC.get(v, ELEVATION_DESC["eye_level"])
    s_desc = SHOT_SIZE_DESC.get(s, SHOT_SIZE_DESC["medium"])
    return f"{s_desc}, {v_desc}, {h_desc}"


def parse_from_legacy_text(angle_text: str, shot_type: str = "") -> dict[str, str]:
    combined = f"{angle_text or ''} {shot_type or ''}"
    h = _match_map(combined, ZH_H_MAP) or "front"
    v = _match_map(combined, ZH_V_MAP) or "eye_level"
    s = _match_map(combined, ZH_S_MAP) or "medium"
    return {"h": h, "v": v, "s": s}


def from_legacy_text(angle_text: str, shot_type: str = "") -> str:
    res = parse_from_legacy_text(angle_text, shot_type)
    return to_prompt_fragment(res["h"], res["v"], res["s"])


def to_chinese_label(h: str, v: str, s: str) -> str:
    h_label = {
        "front": "正面", "front_left": "前左", "left": "左侧", "back_left": "后左",
        "back": "背面", "back_right": "后右", "right": "右侧", "front_right": "前右",
    }.get(h, "正面")
    v_label = {"worm": "虫眼仰", "low": "仰拍", "eye_level": "平视", "high": "俯拍"}.get(v, "平视")
    s_label = {"close_up": "特写", "medium": "中景", "wide": "远景"}.get(s, "中景")
    return f"{s_label}·{v_label}·{h_label}"


# 镜头运动 → 英文 prompt（枚举值已有英文片段直接返回）
MOVEMENT_DESC: dict[str, str] = {
    "static": "static locked shot, no camera movement, tripod-mounted",
    "push": "slow push-in dolly shot, camera gradually moves closer to subject",
    "pull": "pull-back dolly shot, camera gradually moves away from subject",
    "pan": "horizontal pan shot, camera sweeps laterally from side to side",
    "tilt": "vertical tilt shot, camera pivots up or down",
    "tracking": "tracking shot, camera follows subject movement, smooth motion",
    "crane_up": "crane up shot, camera rises vertically, revealing wider scene",
    "crane_dn": "crane down shot, camera descends vertically",
    "orbit": "orbiting arc shot, camera circles around subject",
    "handheld": "handheld shot, subtle natural camera shake, documentary feel",
}

# 中文关键字 → movement 枚举
ZH_MOVEMENT_MAP: list[dict[str, Any]] = [
    {"keys": ["固定", "不动", "static", "locked"], "val": "static"},
    {"keys": ["推镜", "推进", "推", "push in", "dolly in", "push"], "val": "push"},
    {"keys": ["拉镜", "拉出", "拉", "pull back", "dolly out", "pull"], "val": "pull"},
    {"keys": ["横移", "横摇", "摇镜", "摇", "pan"], "val": "pan"},
    {"keys": ["纵摇", "上摇", "下摇", "tilt"], "val": "tilt"},
    {"keys": ["跟镜", "跟拍", "跟随", "track"], "val": "tracking"},
    {"keys": ["升镜", "向上", "crane up"], "val": "crane_up"},
    {"keys": ["降镜", "向下", "crane down"], "val": "crane_dn"},
    {"keys": ["环绕", "绕", "orbit", "arc"], "val": "orbit"},
    {"keys": ["手持", "handheld"], "val": "handheld"},
]


def infer_photography_params(sb: dict) -> dict:
    """从分镜已有字段快速推断 movement / lighting_style / depth_of_field。"""
    atm = (sb.get("atmosphere") or "").lower()
    time_ = (sb.get("time") or "").lower()
    desc = (sb.get("description") or "").lower()
    action = (sb.get("action") or "").lower()
    combined = f"{atm} {time_} {desc} {action}"

    # ── 灯光推断（按优先级）──
    lighting = None
    if _re_test(r"霓虹|赛博|neon|cyberpunk", combined):
        lighting = "neon"
    elif _re_test(r"逆光|背光|backlit|轮廓光|rim light", combined):
        lighting = "backlit"
    elif _re_test(r"戏剧|明暗|强对比|chiaroscuro|dramatic|noir", combined):
        lighting = "dramatic"
    elif _re_test(r"黄金时段|黄昏|金色光|夕阳|落日|golden", combined):
        lighting = "golden_hour"
    elif _re_test(r"蓝调|蓝光|暮色|blue hour|twilight", combined):
        lighting = "blue_hour"
    elif _re_test(r"夜晚|夜景|深夜|午夜|night", combined):
        lighting = "night"
    elif _re_test(r"顶光|头顶|top light", combined):
        lighting = "top"
    elif _re_test(r"底光|脚灯|underlight", combined):
        lighting = "under"
    elif _re_test(r"侧光|side light|侧面光", combined):
        lighting = "side"
    elif _re_test(r"柔光|散射|soft light|soft", combined):
        lighting = "soft"
    elif _re_test(r"顺光|正面光|front light", combined):
        lighting = "front"
    elif _re_test(r"自然光|日光|阳光|natural light|sunlight", combined):
        lighting = "natural"
    elif _re_test(r"白天|清晨|午后|daytime|morning|afternoon", combined):
        lighting = "natural"

    # ── 景深推断（依据景别）──
    dof = None
    angle_s = sb.get("angle_s") or ""
    shot_type = (sb.get("shot_type") or "").lower()
    if angle_s == "close_up" or _re_test(r"特写|close.?up|extreme close", shot_type):
        dof = "shallow"
    elif angle_s == "wide" or _re_test(r"大远景|远景|long shot|wide shot", shot_type):
        dof = "deep"
    elif angle_s == "medium" or _re_test(r"中景|medium shot", shot_type):
        dof = "medium"

    # ── 运镜推断（从 movement 中文兜底到枚举）──
    movement = None
    raw_movement = (sb.get("movement") or "").strip()
    if raw_movement:
        movement = raw_movement if raw_movement in MOVEMENT_DESC else None
        if not movement:
            lower = raw_movement.lower()
            for entry in ZH_MOVEMENT_MAP:
                if any(k.lower() in lower for k in entry["keys"]):
                    movement = entry["val"]
                    break
        if not movement:
            movement = raw_movement

    return {
        "movement": movement or None,
        "lighting_style": lighting,
        "depth_of_field": dof,
    }


# ─── 枚举定义 ────────────────────────────────────────────────────────────────

HORIZONTAL = {
    "front": "front",
    "front_left": "front_left",
    "left": "left",
    "back_left": "back_left",
    "back": "back",
    "back_right": "back_right",
    "right": "right",
    "front_right": "front_right",
}

ELEVATION = {
    "worm": "worm",
    "low": "low",
    "eye_level": "eye_level",
    "high": "high",
}

SHOT_SIZE = {
    "close_up": "close_up",
    "medium": "medium",
    "wide": "wide",
}

HORIZONTAL_DESC = {
    "front": "shooting from the front",
    "front_left": "shooting from front-left at 45-degree angle",
    "left": "shooting from the left side, profile view",
    "back_left": "shooting from back-left at 135-degree angle",
    "back": "shooting from behind, character's back to camera",
    "back_right": "shooting from back-right at 135-degree angle",
    "right": "shooting from the right side, profile view",
    "front_right": "shooting from front-right at 45-degree angle",
}

ELEVATION_DESC = {
    "worm": "extreme low-angle worm's eye view, camera near ground pointing sharply upward, strong upward perspective distortion, background shows sky/ceiling",
    "low": "low-angle upward shot, camera below eye-line, slight upward tilt, empowering perspective",
    "eye_level": "eye-level shot, neutral perspective, natural horizontal framing",
    "high": "high-angle bird's eye view, camera above looking down, background shows floor/ground with downward perspective distortion",
}

SHOT_SIZE_DESC = {
    "close_up": "close-up shot (face/bust framing), subject fills most of frame, shallow depth of field, background softly blurred",
    "medium": "medium shot (waist-up to full body), character and immediate surroundings visible, moderate depth of field",
    "wide": "wide shot (full body with environment), subject small relative to scene, deep depth of field, environment context prominent",
}


def to_prompt_fragment(h: str | None, v: str | None, s: str | None) -> str:
    h_desc = HORIZONTAL_DESC.get(h or "", HORIZONTAL_DESC["front"])
    v_desc = ELEVATION_DESC.get(v or "", ELEVATION_DESC["eye_level"])
    s_desc = SHOT_SIZE_DESC.get(s or "", SHOT_SIZE_DESC["medium"])
    return f"{s_desc}, {v_desc}, {h_desc}"


ZH_H_MAP = [
    {"keys": ["背后", "背面", "从背", "back"], "val": "back"},
    {"keys": ["前左", "左前", "front-left", "front_left"], "val": "front_left"},
    {"keys": ["前右", "右前", "front-right", "front_right"], "val": "front_right"},
    {"keys": ["左侧", "正侧", "侧面", "side", "left"], "val": "left"},
    {"keys": ["右侧", "right"], "val": "right"},
    {"keys": ["后左", "左后", "back-left", "back_left"], "val": "back_left"},
    {"keys": ["后右", "右后", "back-right", "back_right"], "val": "back_right"},
    {"keys": ["正面", "前方", "面向", "front"], "val": "front"},
]

ZH_V_MAP = [
    {"keys": ["虫眼", "极低", "worm"], "val": "worm"},
    {"keys": ["仰", "low angle", "low-angle"], "val": "low"},
    {"keys": ["俯", "high angle", "bird"], "val": "high"},
    {"keys": ["平视", "eye-level", "eye level"], "val": "eye_level"},
]

ZH_S_MAP = [
    {"keys": ["特写", "近景", "close"], "val": "close_up"},
    {"keys": ["全景", "远景", "大全", "wide", "long shot", "establishing"], "val": "wide"},
    {"keys": ["中景", "半身", "medium"], "val": "medium"},
]


def _match_map(text: str, map_list: list[dict[str, Any]]) -> str | None:
    t = text.lower()
    for entry in map_list:
        if any(k.lower() in t for k in entry["keys"]):
            return entry["val"]
    return None


def parse_from_legacy_text(angle_text: str | None = "", shot_type: str | None = "") -> dict[str, str]:
    combined = f"{angle_text or ''} {shot_type or ''}"
    h = _match_map(combined, ZH_H_MAP) or "front"
    v = _match_map(combined, ZH_V_MAP) or "eye_level"
    s = _match_map(combined, ZH_S_MAP) or "medium"
    return {"h": h, "v": v, "s": s}


def from_legacy_text(angle_text: str | None = "", shot_type: str | None = "") -> str:
    parsed = parse_from_legacy_text(angle_text, shot_type)
    return to_prompt_fragment(parsed["h"], parsed["v"], parsed["s"])


def to_chinese_label(h: str | None, v: str | None, s: str | None) -> str:
    h_labels = {
        "front": "正面",
        "front_left": "前左",
        "left": "左侧",
        "back_left": "后左",
        "back": "背面",
        "back_right": "后右",
        "right": "右侧",
        "front_right": "前右",
    }
    v_labels = {"worm": "虫眼仰", "low": "仰拍", "eye_level": "平视", "high": "俯拍"}
    s_labels = {"close_up": "特写", "medium": "中景", "wide": "远景"}
    h_label = h_labels.get(h or "", "正面")
    v_label = v_labels.get(v or "", "平视")
    s_label = s_labels.get(s or "", "中景")
    return f"{s_label}·{v_label}·{h_label}"


def list_all_angles() -> list[dict[str, str]]:
    result = []
    for h in HORIZONTAL.values():
        for v in ELEVATION.values():
            for s in SHOT_SIZE.values():
                result.append({
                    "h": h,
                    "v": v,
                    "s": s,
                    "label": to_chinese_label(h, v, s),
                    "prompt_fragment": to_prompt_fragment(h, v, s),
                })
    return result


# 兼容 camelCase
toChineseLabel = to_chinese_label
toPromptFragment = to_prompt_fragment
parseFromLegacyText = parse_from_legacy_text
fromLegacyText = from_legacy_text
listAllAngles = list_all_angles


def _re_test(pattern: str, text: str) -> bool:
    import re
    return re.search(pattern, text) is not None
