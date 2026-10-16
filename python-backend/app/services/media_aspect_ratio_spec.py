"""媒体生成「画幅/比例」官方参数说明与归一化（图片 + 视频）。

对应 Node: backend-node/src/services/mediaAspectRatioSpec.js
"""
from __future__ import annotations

import re

GEMINI_IMAGE_ASPECT_RATIOS = {
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
}

VIDU_ASPECT_RATIOS = {"16:9", "9:16", "3:4", "4:3", "1:1", "21:9"}


def clamp_to_gemini_image_aspect_ratio(ratio: str | None) -> str:
    """将任意比例标签限制在 Gemini 图片官方枚举内（未知则 16:9）。"""
    r = str(ratio or "").strip()
    if r in GEMINI_IMAGE_ASPECT_RATIOS:
        return r
    return "16:9"


def clamp_to_vidu_aspect_ratio(ratio: str | None) -> str:
    """将比例限制在 Vidu 常见枚举内（未知则 16:9）。"""
    r = str(ratio or "").strip()
    if r in VIDU_ASPECT_RATIOS:
        return r
    return "16:9"


def aspect_ratio_label_from_pixel_size(size: str | None) -> str:
    """从 "2560x1440" / "1440*2560" 推断比例标签。"""
    if not size or not isinstance(size, str):
        return "16:9"
    s = str(size).strip().lower().replace(" ", "")
    ratio_set = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"}
    if s in ratio_set:
        return s
    m = re.match(r"^(\d+)[x*](\d+)$", s)
    if not m:
        return "16:9"
    w = int(m.group(1))
    h = int(m.group(2))
    if not w or not h:
        return "16:9"
    r = w / h
    if r > 2:
        return "21:9"
    if r >= 1.6:
        return "16:9"
    if r >= 1.2:
        return "4:3"
    if r >= 0.9:
        return "1:1"
    if r >= 0.7:
        return "3:4"
    if r >= 0.55:
        return "4:5"
    return "9:16"


def pick_vidu_resolution_param(
    resolution: str | None,
    model_name: str | None = None,
    has_image: bool = False,
) -> str:
    """Vidu resolution 归一化；img2video + q2 系模型官方常见仅 720p/1080p（540p 易报错则抬到 720p）。"""
    r = str(resolution or "").strip().lower()
    if r == "480p":
        r = "540p"
    allowed = {"540p", "720p", "1080p"}
    if r not in allowed:
        r = "720p"
    m = str(model_name or "").lower()
    q2_family_img = has_image and bool(re.search(r"viduq2|vidu2\.0|viduq1", m, re.IGNORECASE))
    if q2_family_img and r == "540p":
        r = "720p"
    return r


def is_gemini_official_host(base_url: str | None) -> bool:
    """判断是否为 Google 官方 generativelanguage 域名。"""
    return bool(re.search(r"generativelanguage\.googleapis\.com", str(base_url or ""), re.IGNORECASE))
