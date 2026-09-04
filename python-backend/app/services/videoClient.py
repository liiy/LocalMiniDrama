"""视频生成客户端 — 契约翻译 backend-node/src/services/videoClient.js。

本模块覆盖 videoClient 的**全量纯函数**（协议推断、时长/画幅归一、URL 拼装、
模型别名、各厂商响应解析）与配置查找。这些函数不触碰网络，可与 Node 逐值对拍
（见 tests/contract/test_video_client_helpers.py）。

建任务 / 轮询（callVideoApi / pollVideoTask）为网络编排，依赖外部 AI，
按项目约定不在契约测试里对拍；其可复用的解析部分（extract_agnes_video_url、
pick_proxy_video_url、extract_minimax_h3_video_url 等）与 poll_video_task 的
协议分支已在此翻译，poll_video_task 支持注入 fetch_json 打桩以便测试。
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.services import aiConfigService
from app.services.mediaAspectRatioSpec import clamp_to_vidu_aspect_ratio, pick_vidu_resolution_param
from app.services.uploadService import upload_local_image_to_proxy, upload_to_image_proxy

# ---------------------------------------------------------------- 常量

KLING_OMNI_ASPECT_RATIOS = {"9:16", "16:9", "1:1", "4:3", "3:4", "3:2", "2:3"}

VOLC_VIDEO_CREATE_PATH = "/contents/generations/tasks"
VOLC_VIDEO_QUERY_PATH = "/contents/generations/tasks"

VOLC_MODEL_ALIASES = {
    "doubao-seedance-1.0-pro-fast": "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1.0-pro": "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1-0-pro": "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1.0-lite": "doubao-seedance-1-0-lite-250428",
    "doubao-seedance-1-0-lite": "doubao-seedance-1-0-lite-250428",
    "doubao-seedance-1.5-pro": "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-1-5-pro": "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-2.0-pro": "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-pro": "doubao-seedance-2-0-260128",
    "doubao-seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-2-0-fast": "doubao-seedance-2-0-fast-260128",
}

_ASPECT_ALIASES = {
    "portrait": "9:16",
    "landscape": "16:9",
    "square": "1:1",
    "vertical": "9:16",
    "horizontal": "16:9",
}

_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# 本地首/尾帧转 base64 时的扩展名→MIME 映射（与 Node videoClient 内联映射一致）
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _to_num(v) -> float:
    """等价 JS Number(v)：非法→NaN。用 float('nan') 表示 NaN。"""
    try:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return float("nan")
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _is_finite(n: float) -> bool:
    return n == n and n not in (float("inf"), float("-inf"))


def _safe_round(n: float) -> int:
    """等价 JS Math.round。NaN/Inf 返回 0（调用方已用 _is_finite 兜底取默认值）。"""
    if not _is_finite(n):
        return 0
    return int(math.floor(n + 0.5)) if n >= 0 else -int(math.floor(-n + 0.5))


def _js_str(v) -> str:
    """等价 JS String(v)：encodeURIComponent 会先做这一步，null → 'null'（不是 'None'）。"""
    return "null" if v is None else str(v)


def _q(v) -> str:
    """等价 JS encodeURIComponent(v)。"""
    return quote(_js_str(v), safe="")


# ---------------------------------------------------------------- 协议推断


def infer_video_protocol(provider) -> str:
    p = str(provider or "").lower()
    if p == "dashscope":
        return "dashscope"
    if p in ("gemini", "google"):
        return "gemini"
    if p in ("volces", "volcengine", "volc"):
        return "volcengine"
    if p == "vidu":
        return "vidu"
    if p == "ffir":
        return "kling_omni"
    if p in ("kling", "klingai"):
        return "kling"
    if p == "jimeng_ai_api":
        return "jimeng_ai_api"
    if p in ("xai", "grok"):
        return "xai"
    if p == "agnes":
        return "agnes"
    if p == "minimax_h3":
        return "minimax_h3"
    return "openai"


def is_minimax_h3_model(name) -> bool:
    m = str(name or "").strip().lower()
    return (
        m == "minimax-h3"
        or m == "minimax_h3"
        or bool(re.match(r"^minimax[-_]?h3\b", m))
    )


def resolve_video_protocol(config: dict, model_hint=None) -> str:
    """显式 api_protocol 优先；未配置时按 provider / base_url / model 推断。"""
    config = config or {}
    provider = str(config.get("provider") or "").lower()
    explicit = str(config.get("api_protocol") or "").strip()
    protocol = explicit.lower() or infer_video_protocol(provider)
    base_lower = str(config.get("base_url") or "").lower()

    raw_model = config.get("model")
    model_cand = (
        model_hint
        or config.get("default_model")
        or (raw_model[0] if isinstance(raw_model, list) and raw_model else (raw_model if raw_model is not None else ""))
        or ""
    )
    model_lower = str(model_cand or "").lower()

    if not explicit and protocol == "openai":
        if re.search(r"api\.x\.ai(/|$)", base_lower):
            protocol = "xai"
        elif re.search(r"grok-imagine|grok.*video", model_lower, re.IGNORECASE):
            protocol = "xai"
        elif provider == "agnes" or re.search(r"agnes-video|apihub\.agnes-ai\.com", base_lower, re.IGNORECASE):
            protocol = "agnes"

    if (not explicit or protocol == "openai") and (
        provider == "minimax_h3" or is_minimax_h3_model(model_cand)
    ):
        protocol = "minimax_h3"
    return protocol


def parse_config_settings_json(config) -> dict:
    if not config:
        return {}
    raw = config.get("settings")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        import json

        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- 画幅 / 时长


def normalize_aspect_ratio_for_api(raw) -> str | None:
    """归一化画幅字符串（全角冒号 / ×xX＊* / 空格 / 别名），命中可灵枚举否则 None。"""
    if raw is None:
        return None
    s = str(raw).strip().replace("：", ":")
    s = re.sub(r"[×xX＊*]", ":", s)
    s = re.sub(r"\s+", "", s)
    if not s:
        return None
    lower = s.lower()
    if lower in _ASPECT_ALIASES:
        s = _ASPECT_ALIASES[lower]
    return s if s in KLING_OMNI_ASPECT_RATIOS else None


def omni_duration_string(model_name, duration_num) -> str:
    m = str(model_name or "").lower()
    d = _to_num(duration_num)
    safe = d if (_is_finite(d) and d > 0) else 5
    if "v3-omni" in m or "kling-v3" in m:
        allowed = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
        best, best_diff = 5, 999
        for a in allowed:
            diff = abs(a - safe)
            if diff < best_diff:
                best_diff, best = diff, a
        return str(best)
    return "5" if safe <= 7 else "10"


def is_seedance2_family_model(model_name) -> bool:
    m = str(model_name or "").lower().strip()
    if not m:
        return False
    if re.search(r"seedance[-_]?2|seedance2", m):
        return True
    if re.search(r"2[-_]0[-_]", m):
        return True
    if re.search(r"(^|[-_./])sd2($|[-_./])", m):
        return True
    return False


def normalize_volcengine_duration(model_name, duration_num) -> int:
    m = str(model_name or "").lower()
    d = _to_num(duration_num)
    safe = _safe_round(d) if (_is_finite(d) and d > 0) else 5

    if is_seedance2_family_model(m):
        return min(15, max(4, safe))
    if re.search(r"seedance[-_]?1[-_.]?5|1-5-pro|1-5-lite|251215", m):
        return min(12, max(5, safe))
    if re.search(r"seedance|doubao-seedance", m):
        return 5 if safe <= 7 else 10
    return min(12, max(5, safe))


def normalize_volc_omni_duration(model_name, duration_num) -> int:
    """@deprecated 名称保留，实现与 normalize_volcengine_duration 一致。"""
    return normalize_volcengine_duration(model_name, duration_num)


def normalize_minimax_h3_duration(duration) -> int:
    n = _safe_round(_to_num(duration))
    safe = n if (_is_finite(n) and n > 0) else 5
    return min(15, max(4, safe))


def normalize_minimax_h3_resolution(resolution) -> str:
    s = str(resolution or "").strip().lower()
    if not s:
        return "768P"
    if s == "2k" or "2k" in s or "1080" in s or s == "1080p":
        return "2K"
    if "768" in s or s == "768p":
        return "768P"
    return "768P"


# ---------------------------------------------------------------- URL 拼装


def get_volc_video_base(config: dict) -> str:
    base = re.sub(r"/$", "", config.get("base_url") or "")
    base = re.sub(r"/(contents|video)/.*$", "", base, flags=re.IGNORECASE)
    return base or "https://ark.cn-beijing.volces.com/api/v3"


def build_video_url(config: dict, options: dict | None = None) -> str:
    options = options or {}
    p = str(config.get("provider") or "").lower()
    is_volc = p in ("volces", "volcengine", "volc")
    if is_volc:
        return get_volc_video_base(config) + VOLC_VIDEO_CREATE_PATH
    base = re.sub(r"/$", "", config.get("base_url") or "")
    fallback_ep = options.get("defaultEndpoint") if options.get("defaultEndpoint") is not None else "/video/generations"
    ep = config.get("endpoint") or fallback_ep
    if not ep.startswith("/"):
        ep = "/" + ep
    return base + ep


def get_agnes_api_root(base_url) -> str:
    base = re.sub(r"/$", "", str(base_url or "https://apihub.agnes-ai.com"))
    for suf in ("/v1/videos", "/v1"):
        if len(base) >= len(suf) and base[-len(suf):].lower() == suf:
            base = re.sub(r"/$", "", base[: -len(suf)])
    return base or "https://apihub.agnes-ai.com"


def is_agnes_builtin_query_endpoint(ep) -> bool:
    s = str(ep or "").strip()
    if not s:
        return True
    return bool(
        re.match(r"^/?(v1/)?videos/\{(taskId|task_id|id|videoId|video_id)\}/?$", s, re.IGNORECASE)
        or re.match(r"^/?agnesapi(\?|$)", s, re.IGNORECASE)
    )


def build_agnes_poll_url(config: dict, poll_id) -> str:
    root = get_agnes_api_root(config.get("base_url"))
    pid = str(poll_id or "").strip()
    cfg_ep = str(config.get("query_endpoint") or "").strip()

    if cfg_ep and not is_agnes_builtin_query_endpoint(cfg_ep):
        base = re.sub(r"/$", "", config.get("base_url") or "")
        q = _q(pid)
        ep = cfg_ep
        for token in ("videoId", "video_id", "taskId", "task_id", "id"):
            ep = re.sub(r"\{" + token + r"\}", q, ep, flags=re.IGNORECASE)
        if not ep.startswith("/"):
            ep = "/" + ep
        return base + ep

    return f"{root}/v1/videos/{_q(pid)}"


def build_query_url(config: dict, task_id) -> str:
    p = str(config.get("provider") or "").lower()
    proto = resolve_video_protocol(config)
    is_volc = p in ("volces", "volcengine", "volc")
    if is_volc:
        return get_volc_video_base(config) + VOLC_VIDEO_QUERY_PATH + "/" + _q(task_id)
    if proto == "agnes":
        return build_agnes_poll_url(config, task_id)
    if proto == "minimax_h3":
        return build_minimax_h3_poll_url(config, task_id)

    base = re.sub(r"/$", "", config.get("base_url") or "")
    if proto == "sora":
        default_ep = "/v1/videos/{taskId}"
    elif proto == "xai":
        default_ep = "/v1/videos/{taskId}"
    elif proto == "veo3":
        default_ep = "/v1/video/query?id={taskId}"
    elif proto == "dashscope" or p == "dashscope":
        default_ep = "/api/v1/tasks/{taskId}"
    elif proto == "volcengine_omni":
        default_ep = "/v1/videos/generations/async/{taskId}"
    else:
        default_ep = "/video/task/{taskId}"

    ep = config.get("query_endpoint") or default_ep
    q = _q(task_id)
    for token in ("taskId", "task_id", "id"):
        ep = re.sub(r"\{" + token + r"\}", q, str(ep), flags=re.IGNORECASE)
    if not ep.startswith("/"):
        ep = "/" + ep
    return base + ep


def get_minimax_api_root(base_url) -> str:
    root = re.sub(r"/$", "", str(base_url or "https://api.minimaxi.com").strip())
    for suf in ("/v2", "/v1"):
        if root.lower().endswith(suf):
            root = re.sub(r"/$", "", root[: -len(suf)])
            break
    return root or "https://api.minimaxi.com"


def build_minimax_h3_poll_url(config: dict, task_id) -> str:
    root = get_minimax_api_root(config.get("base_url"))
    tid = str(task_id or "").strip()
    ep = str(config.get("query_endpoint") or "/v2/query/video_generation/{taskId}").strip()
    if not ep.startswith("/"):
        ep = "/" + ep
    if re.search(r"query/video_generation\?task_id=", ep, re.IGNORECASE) or re.match(r"^/v1/query/", ep, re.IGNORECASE):
        ep = "/v2/query/video_generation/{taskId}"
    q = _q(tid)
    for token in ("taskId", "task_id", "id"):
        ep = re.sub(r"\{" + token + r"\}", q, ep, flags=re.IGNORECASE)
    # 兼容仅写目录的配置：/v2/query/video_generation → 追加 /{taskId}
    if re.search(r"/v2/query/video_generation/?$", ep, re.IGNORECASE) and tid:
        ep = re.sub(r"/?$", "/", ep) + q
    return root + ep


def _fetch_bytes(url: str, headers: dict | None = None) -> tuple[int, bytes, str]:
    """GET 二进制，返回 (status, content, content_type)。异常向上抛给调用方处理。"""
    import httpx

    resp = httpx.get(url, headers=headers or {}, timeout=60.0, follow_redirects=True)
    return resp.status_code, resp.content, (resp.headers.get("content-type") or "").split(";")[0].strip()


def resolve_volc_classic_image(
    raw_url, files_base_url, storage_local_path, log_=None, video_gen_id=None, role_hint=None
) -> str | None:
    """等价 resolveVolcClassicImage：asset:// 直传、公网 URL 直传、本地路径转 base64。"""
    u = str(raw_url or "").strip()
    if not u:
        return None
    if u.startswith("data:") or u.startswith("asset://"):
        return u
    if re.match(r"^https?://", u, re.IGNORECASE) and not re.search(r"localhost|127\.0\.0\.1", u, re.IGNORECASE):
        return u

    fb = re.sub(r"/$", "", str(files_base_url or ""))
    base_indicates_local = bool(fb) and bool(re.search(r"localhost|127\.0\.0\.1", fb, re.IGNORECASE))
    url_indicates_local = bool(re.search(r"localhost|127\.0\.0\.1", u, re.IGNORECASE))

    if (base_indicates_local or url_indicates_local) and storage_local_path:
        rel = None
        marker = "/static/"
        idx = u.lower().find(marker)
        if idx >= 0:
            rel = u[idx + len(marker):].lstrip("/").split("?")[0]
        elif fb:
            rel = u.replace(fb + "/", "").replace(fb, "").lstrip("/").split("?")[0]
        elif not re.match(r"^https?://", u, re.IGNORECASE):
            rel = u.lstrip("/").split("?")[0]
        if rel:
            file_path = os.path.join(storage_local_path, rel)
            try:
                if os.path.exists(file_path):
                    with open(file_path, "rb") as fh:
                        buf = fh.read()
                    ext = os.path.splitext(file_path)[1].lower()
                    mime = _MIME_BY_EXT.get(ext, "image/png")
                    if log_:
                        log_.info(
                            "[Volc] 本地首/尾帧已转为 base64 提交",
                            extra={"video_gen_id": video_gen_id, "role": role_hint, "rel": rel[:80]},
                        )
                    return "data:" + mime + ";base64," + base64.b64encode(buf).decode("ascii")
            except OSError:
                pass
    # 兜底返回原始值（中转或公网会处理）
    return u


# ---------------------------------------------------------------- Kling Omni

KLING_OMNI_PROXY_CREATE = "/kling/v1/videos/omni-video"
KLING_OMNI_PROXY_QUERY = "/kling/v1/images/omni-image/{taskId}"
KLING_OMNI_OFFICIAL_CREATE = "/v1/videos/omni-video"
KLING_OMNI_OFFICIAL_QUERY = "/v1/videos/omni-video/{taskId}"

_OFFICIAL_KLING_HOSTS = ("api.klingai.com", "api-beijing.klingai.com", "api-singapore.klingai.com")


def apply_kling_omni_env_overrides(config: dict) -> dict:
    """等价 applyKlingOmniEnvOverrides：环境变量覆盖 base_url / api_key / endpoint。"""
    c = dict(config or {})
    env_map = (
        ("KLING_FFIR_BASE_URL", "base_url"),
        ("KLING_FFIR_API_KEY", "api_key"),
        ("KLING_OFFICIAL_BASE_URL", "base_url"),
    )
    for env_key, cfg_key in env_map:
        v = os.environ.get(env_key)
        if v:
            c[cfg_key] = re.sub(r"/$", "", str(v))
    if os.environ.get("KLING_FFIR_CREATE_PATH"):
        p = str(os.environ["KLING_FFIR_CREATE_PATH"])
        c["endpoint"] = p if p.startswith("/") else "/" + p
    if os.environ.get("KLING_FFIR_QUERY_PATH"):
        c["query_endpoint"] = str(os.environ["KLING_FFIR_QUERY_PATH"])
    if os.environ.get("KLING_OFFICIAL_ACCESS_KEY"):
        c["_kling_official_access_key"] = str(os.environ["KLING_OFFICIAL_ACCESS_KEY"])
    if os.environ.get("KLING_OFFICIAL_SECRET_KEY"):
        c["_kling_official_secret_key"] = str(os.environ["KLING_OFFICIAL_SECRET_KEY"])
    return c


def resolve_kling_secret_key_base64_flag(cfg) -> bool:
    s = parse_config_settings_json(cfg)
    v = s.get("kling_secret_key_base64")
    if v is True or v == 1:
        return True
    if str(v or "").lower() == "true":
        return True
    return str(os.environ.get("KLING_SECRET_KEY_BASE64") or "").lower() in ("1", "true", "yes")


def resolve_kling_omni_bearer_token(cfg: dict, log_=None):
    """官方 AK/SK → JWT；否则 api_key 视为 Bearer Token（中转站）。"""
    from app.services.klingJwt import normalize_kling_credential, sign_kling_official_jwt

    s = parse_config_settings_json(cfg)
    ak = normalize_kling_credential(
        s.get("kling_access_key") or s.get("access_key") or cfg.get("_kling_official_access_key") or ""
    )
    sk = normalize_kling_credential(
        s.get("kling_secret_key") or s.get("secret_key") or cfg.get("_kling_official_secret_key") or ""
    )
    if ak and sk:
        try:
            token = sign_kling_official_jwt(
                ak, sk,
                {"secretEncoding": "base64" if resolve_kling_secret_key_base64_flag(cfg) else "utf8"},
            )
            if log_:
                log_.info("[KlingOmni] 鉴权：官方 AK/SK → JWT（HS256，payload: iss+exp+nbf）")
            return token
        except Exception as e:  # noqa: BLE001
            if log_:
                log_.warning("[KlingOmni] JWT 生成失败", extra={"reason": str(e)})
            return None
    bearer = normalize_kling_credential(cfg.get("api_key") or "")
    bearer = re.sub(r"^bearer\s+", "", bearer, flags=re.IGNORECASE)
    return bearer or None


def is_kling_official_omni_host(base_url) -> bool:
    raw = str(base_url or "").strip()
    if not raw:
        return False
    try:
        from urllib.parse import urlparse

        host = urlparse(raw if re.match(r"^https?://", raw, re.IGNORECASE) else "https://" + raw).hostname or ""
        return host.lower() in _OFFICIAL_KLING_HOSTS
    except Exception:  # noqa: BLE001
        return bool(re.search(r"api(-beijing|-singapore)?\.klingai\.com", raw, re.IGNORECASE))


def resolve_kling_omni_base_url(cfg: dict) -> str:
    """未填 base_url：官方凭据 → api-beijing.klingai.com；否则 ffir 中转默认。"""
    b = re.sub(r"/$", "", str(cfg.get("base_url") or "")).strip()
    if b:
        return b
    s = parse_config_settings_json(cfg)
    has_official = bool(
        ((s.get("kling_access_key") or s.get("access_key")) and (s.get("kling_secret_key") or s.get("secret_key")))
        or (cfg.get("_kling_official_access_key") and cfg.get("_kling_official_secret_key"))
    )
    return "https://api-beijing.klingai.com" if has_official else "https://ffir.cn"


def resolve_kling_omni_create_path(cfg: dict, base: str) -> str:
    official = is_kling_official_omni_host(base)
    ep = str(cfg.get("endpoint") or "").strip()
    if ep:
        norm = ep if ep.startswith("/") else "/" + ep
        if official and norm == KLING_OMNI_PROXY_CREATE:
            return KLING_OMNI_OFFICIAL_CREATE
        return norm
    return KLING_OMNI_OFFICIAL_CREATE if official else KLING_OMNI_PROXY_CREATE


def resolve_kling_omni_query_path_template(cfg: dict, base: str) -> str:
    official = is_kling_official_omni_host(base)
    q = str(cfg.get("query_endpoint") or "").strip()
    if q:
        if official and q == KLING_OMNI_PROXY_QUERY:
            return KLING_OMNI_OFFICIAL_QUERY
        return q
    return KLING_OMNI_OFFICIAL_QUERY if official else KLING_OMNI_PROXY_QUERY


def resolve_kling_omni_aspect_ratio(aspect_ratio, log_=None, video_gen_id=None) -> str:
    normalized = normalize_aspect_ratio_for_api(aspect_ratio)
    if normalized:
        return normalized
    raw = "" if aspect_ratio is None else str(aspect_ratio).strip()
    if raw and log_:
        log_.warning(
            "[KlingOmni] aspect_ratio 不在可灵支持列表，回退 16:9",
            extra={"raw": aspect_ratio, "video_gen_id": video_gen_id,
                   "supported": ", ".join(sorted(KLING_OMNI_ASPECT_RATIOS))},
        )
    return "16:9"


def parse_kling_omni_poll_video_url(data) -> str | None:
    u = pick_proxy_video_url(data)
    if u:
        return u
    if not data or not isinstance(data, dict):
        return None
    try_paths = [
        ((data.get("data") or {}).get("task_result") or {}).get("videos", [{}])[0].get("url")
        if isinstance((data.get("data") or {}).get("task_result"), dict) else None,
        ((data.get("data") or {}).get("videos") or [{}])[0].get("url")
        if isinstance((data.get("data") or {}).get("videos"), list) else None,
        (data.get("data") or {}).get("video_url"),
        ((data.get("task_result") or {}).get("videos") or [{}])[0].get("url")
        if isinstance(data.get("task_result"), dict) else None,
        ((data.get("result") or {}).get("videos") or [{}])[0].get("url")
        if isinstance(data.get("result"), dict) else None,
        (data.get("output") or {}).get("video_url"),
    ]
    for p in try_paths:
        if p and isinstance(p, str):
            return p
    return None


# ---------------------------------------------------------------- 配置查找


def get_default_video_config(db, preferred_model=None):
    configs = aiConfigService.list_configs(db, "video")
    active = [c for c in configs if c.get("is_active")]
    if not active:
        return None
    if preferred_model:
        for c in active:
            models = c.get("model") if isinstance(c.get("model"), list) else ([c["model"]] if c.get("model") is not None else [])
            if preferred_model in models:
                return c
    default_one = next((c for c in active if c.get("is_default")), None)
    return default_one if default_one is not None else active[0]


def normalize_volc_model(name):
    if not name:
        return name
    return VOLC_MODEL_ALIASES.get(str(name).lower(), name)


def get_model_from_config(config: dict, preferred_model=None) -> str:
    models = config.get("model") if isinstance(config.get("model"), list) else ([config["model"]] if config.get("model") is not None else [])
    if preferred_model and preferred_model in models:
        return preferred_model
    if config.get("default_model") and config.get("default_model") in models:
        return config["default_model"]
    return models[0] if models else ""


# ---------------------------------------------------------------- 响应解析


def is_plausible_http_video_url(s) -> bool:
    if not isinstance(s, str):
        return False
    return bool(_HTTP_URL_RE.match(s.strip()))


def coerce_http_video_url(s) -> str | None:
    return s.strip() if is_plausible_http_video_url(s) else None


def extract_poll_task_status(data) -> str:
    if not data or not isinstance(data, dict):
        return ""
    inner = data.get("data")
    candidates = [
        data.get("status"),
        data.get("state"),
        data.get("task_status"),
        (inner or {}).get("status") if isinstance(inner, dict) else None,
        (inner or {}).get("state") if isinstance(inner, dict) else None,
        (inner or {}).get("task_status") if isinstance(inner, dict) else None,
        ((data.get("output") or {}).get("task_status")) if isinstance(data.get("output"), dict) else None,
    ]
    for c in candidates:
        if c is not None and str(c).strip() != "":
            return str(c).strip().lower()
    return ""


def is_poll_task_failed(status) -> bool:
    return str(status) in ("failed", "failure", "error", "cancelled", "canceled", "fail")


def video_url_from_record(rec) -> str | None:
    if not rec or not isinstance(rec, dict):
        return None
    return (
        coerce_http_video_url(rec.get("video_url"))
        or coerce_http_video_url(rec.get("result_url"))
        or coerce_http_video_url(rec.get("url"))
        or coerce_http_video_url(rec.get("output_url"))
        or coerce_http_video_url(rec.get("remixed_from_video_id"))
        or None
    )


def video_url_from_ark_video_node(video) -> str | None:
    if not video or not isinstance(video, dict):
        return None
    tv = video.get("transcoded_video")
    origin = (tv or {}).get("origin") if isinstance(tv, dict) else None
    if isinstance(origin, dict) and isinstance(origin.get("video_url"), str):
        u = coerce_http_video_url(origin["video_url"])
        if u:
            return u
    for k in ("download_url", "play_url", "url", "video_url"):
        u = coerce_http_video_url(video.get(k))
        if u:
            return u
    return None


def pick_video_url_from_item_list(lst) -> str | None:
    if not isinstance(lst, list) or not lst:
        return None
    item = lst[0]
    if not item or not isinstance(item, dict):
        return None
    ca = item.get("common_attr")
    from_common = None
    if isinstance(ca, dict):
        tv = ca.get("transcoded_video")
        origin = (tv or {}).get("origin") if isinstance(tv, dict) else None
        if isinstance(origin, dict) and isinstance(origin.get("video_url"), str) and origin["video_url"].strip():
            from_common = origin["video_url"].strip()
    from_video = video_url_from_ark_video_node(item.get("video"))
    from_result = coerce_http_video_url(item.get("result_url"))
    flat = video_url_from_record(item)
    return from_common or from_video or from_result or flat or None


def pick_video_url_from_result_shape(obj) -> str | None:
    if not obj or not isinstance(obj, dict):
        return None
    x = video_url_from_record(obj)
    if x:
        return x.strip() if isinstance(x, str) else x
    inner = obj.get("content")
    if inner and isinstance(inner, dict):
        x = video_url_from_record(inner)
        if x:
            return x.strip() if isinstance(x, str) else x
        il = pick_video_url_from_item_list(inner.get("item_list"))
        if il:
            return il
        v = inner.get("video")
        if isinstance(v, dict):
            vv = video_url_from_ark_video_node(v) or v.get("url") or v.get("video_url")
            if vv and isinstance(vv, str):
                return vv.strip()
    return None


def pick_proxy_video_url(data) -> str | None:
    if not data or not isinstance(data, dict):
        return None
    top_list = pick_video_url_from_item_list(data.get("item_list"))
    if top_list:
        return top_list
    v = data.get("video")
    if isinstance(v, dict):
        vu = (
            video_url_from_ark_video_node(v)
            or coerce_http_video_url(v.get("url"))
            or coerce_http_video_url(v.get("video_url"))
        )
        if vu:
            return vu
    u = video_url_from_record(data)
    if u:
        return u

    meta = data.get("metadata")
    if isinstance(meta, dict):
        u = video_url_from_record(meta)
        if u:
            return u

    d = data.get("data")
    if isinstance(d, dict):
        nested_list = pick_video_url_from_item_list(d.get("item_list"))
        if nested_list:
            return nested_list
        u = video_url_from_record(d)
        if u:
            return u
        if isinstance(d.get("metadata"), dict):
            u = video_url_from_record(d["metadata"])
            if u:
                return u
        if isinstance(d.get("video"), dict):
            dv = (
                video_url_from_ark_video_node(d["video"])
                or coerce_http_video_url(d["video"].get("url"))
                or coerce_http_video_url(d["video"].get("video_url"))
            )
            if dv:
                return dv
        if isinstance(d.get("result"), dict):
            dr = pick_video_url_from_result_shape(d["result"])
            if dr:
                return dr

    r = data.get("result")
    if isinstance(r, dict):
        pr = pick_video_url_from_result_shape(r)
        if pr:
            return pr

    c = data.get("content")
    if isinstance(c, dict):
        cl = pick_video_url_from_item_list(c.get("item_list"))
        if cl:
            return cl
        u = video_url_from_record(c)
        if u:
            return u
        if isinstance(c.get("video"), dict):
            cv = (
                video_url_from_ark_video_node(c["video"])
                or coerce_http_video_url(c["video"].get("url"))
                or coerce_http_video_url(c["video"].get("video_url"))
            )
            if cv:
                return cv

    for k in ("videos", "generations", "works"):
        arr = data.get(k)
        if isinstance(arr, list) and arr:
            u = video_url_from_record(arr[0])
            if u:
                return u
            res = (arr[0] or {}).get("resource") if isinstance(arr[0], dict) else None
            if isinstance(res, dict) and res.get("resource"):
                return res["resource"]

    if isinstance(d, list) and d:
        u = video_url_from_record(d[0])
        if u:
            return u
    return None


def extract_poll_failure_message(data) -> str:
    """从轮询响应中提取失败文案，跳过形如 URL 的值。"""
    if not data or not isinstance(data, dict):
        return ""
    inner = data.get("data")
    inner = inner if (isinstance(inner, dict) and not isinstance(inner, list)) else None
    deep = inner.get("data") if (inner and isinstance(inner.get("data"), dict)) else None

    err = data.get("error")
    candidates = [
        (inner or {}).get("fail_reason"),
        data.get("fail_reason"),
        (inner or {}).get("message"),
        (deep or {}).get("msg"),
        err.get("message") if isinstance(err, dict) else None,
        err if isinstance(err, str) else None,
        data.get("message"),
        data.get("msg") if isinstance(data.get("msg"), str) else None,
    ]
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s and not re.match(r"^https?://", s, re.IGNORECASE):
            return s
    # 部分中转把错误文案塞在 url 字段里
    for rec in (inner, data):
        if not rec or not isinstance(rec, dict):
            continue
        for k in ("result_url", "video_url"):
            u = rec.get(k)
            if isinstance(u, str) and u.strip() and not is_plausible_http_video_url(u):
                return u.strip()
    return ""


def parse_dash_scope_video_url(data) -> str | None:
    """DashScope：output → output.output → results[0] → choices[0].message.content[]。"""
    if not data or not isinstance(data, dict):
        return None
    out = data.get("output")
    if not out or not isinstance(out, dict):
        return None
    u = video_url_from_record(out)
    if u:
        return u
    if isinstance(out.get("output"), dict):
        u = video_url_from_record(out["output"])
        if u:
            return u
    results = out.get("results") or out.get("result")
    if isinstance(results, list) and results:
        rec = results[0]
        if isinstance(rec, dict):
            u = video_url_from_record(rec)
            if u:
                return u
            if isinstance(rec.get("output"), dict):
                u = video_url_from_record(rec["output"])
                if u:
                    return u
    choices = out.get("choices")
    if isinstance(choices, list) and choices:
        c = choices[0]
        if isinstance(c, dict):
            msg = (c.get("message") or {}).get("content") if isinstance(c.get("message"), dict) else None
            msg = msg if msg is not None else c.get("content")
            if isinstance(msg, list):
                for m in msg:
                    if m:
                        u = video_url_from_record(m)
                        if u:
                            return u
    return None


def extract_minimax_h3_task_status(data) -> str:
    if not data or not isinstance(data, dict):
        return ""
    task = data.get("task") if isinstance(data.get("task"), dict) else data
    s = task.get("status") or task.get("state") or data.get("status")
    return str(s).strip().lower() if s is not None else ""


def extract_agnes_video_url(data) -> str | None:
    """对齐 new-api 的 extractVideoURL，并兼容完成态把直链放在 metadata.url。"""
    if not data or not isinstance(data, dict):
        return None

    def nested(obj, key):
        if obj and isinstance(obj, dict):
            return obj.get(key)
        return None

    candidates = [
        data.get("video_url"),
        nested(data.get("content"), "video_url"),
        nested(data.get("data"), "video_url"),
        nested(data.get("data"), "url"),
        nested(data.get("metadata"), "url"),
        nested(data.get("metadata"), "video_url"),
        nested(data.get("metadata"), "result_url"),
        data.get("remixed_from_video_id"),
        nested(data.get("data"), "remixed_from_video_id"),
        data.get("url"),
    ]
    for c in candidates:
        u = coerce_http_video_url(c)
        if u:
            return u
    return pick_proxy_video_url(data)


def extract_minimax_h3_video_url(data) -> str | None:
    if not data or not isinstance(data, dict):
        return None
    task = data.get("task") if isinstance(data.get("task"), dict) else data
    content = task.get("content") if isinstance(task.get("content"), dict) else None
    return (
        coerce_http_video_url((content or {}).get("url"))
        or coerce_http_video_url(task.get("video_url"))
        or coerce_http_video_url(task.get("url"))
        or pick_proxy_video_url(data)
        or None
    )


def call_video_api(db, log_, opts: dict, post_json=None) -> dict:
    """等价 callVideoApi：按协议路由各厂商建任务，返回 { task_id, status } / { video_url } / { error }。

    已完整移植：volcengine / openai（通用兜底，含首尾帧、时长归一、草稿模式）。
    其余厂商协议（jimeng_ai_api / xai / dashscope / gemini / vidu / kling / kling_omni /
    volcengine_omni / veo3 / sora / agnes / minimax_h3）走各自 callXxxVideoApi，
    尚未移植时抛 NotImplementedError，由调用方转为 500（与既有纯 AI 端点约定一致）。

    post_json 为可注入的 (url, headers, body) -> (status, raw_text) 钩子，便于测试打桩。
    """
    import httpx

    preferred_model = opts.get("model")
    config = get_default_video_config(db, preferred_model)
    if not config:
        raise RuntimeError("未配置视频模型，请在「AI 配置」中添加 video 类型且已启用的配置")

    model = get_model_from_config(config, preferred_model)
    provider = str(config.get("provider") or "").lower()
    protocol = resolve_video_protocol(config, preferred_model)

    log_.info(
        "[视频] 路由协议",
        extra={"video_gen_id": opts.get("video_gen_id"), "provider": provider,
               "api_protocol_raw": config.get("api_protocol") or "(empty→auto)",
               "protocol_used": protocol, "model": model,
               "endpoint": config.get("endpoint") or "(auto)"},
    )

    # 厂商专属协议：优先走实际实现；未匹配则兜底通用协议。
    if protocol == "veo3":
        return call_veo3_video_api(config, log_, opts, post_json=post_json)
    if protocol in _VENDOR_VIDEO_DISPATCH:
        fn_name = _VENDOR_VIDEO_DISPATCH[protocol]
        fn = globals().get(fn_name)
        if callable(fn):
            return fn(config, log_, opts, post_json=post_json)

    # ---------------- 通用兜底：volcengine / openai 兼容 ----------------
    prompt = opts.get("prompt")
    duration = opts.get("duration")
    aspect_ratio = opts.get("aspect_ratio")
    resolution = opts.get("resolution")
    seed = opts.get("seed")
    camera_fixed = opts.get("camera_fixed")
    watermark = opts.get("watermark")
    image_url = opts.get("image_url")
    first_frame_url = opts.get("first_frame_url")
    last_frame_url = opts.get("last_frame_url")
    files_base_url = opts.get("files_base_url")
    storage_local_path = opts.get("storage_local_path")
    video_gen_id = opts.get("video_gen_id")

    url = build_video_url(config)
    dur = _to_num(duration) if duration else 5
    dur = dur if _is_finite(dur) else 5
    ratio = aspect_ratio or "16:9"

    is_volc = protocol == "volcengine"
    # 火山需把展示名映射为 API 上的模型 ID
    final_model = normalize_volc_model(model) if is_volc else model

    # 首尾帧：优先显式 first/last_frame_url，其次回退 image_url（经典单图）
    raw_first = str(first_frame_url or opts.get("first_frame_local_path") or image_url or "").strip()
    raw_last = str(last_frame_url or opts.get("last_frame_local_path") or "").strip()

    first_for_api = resolve_volc_classic_image(
        raw_first, files_base_url, storage_local_path, log_, video_gen_id, "first_frame"
    )
    last_for_api = None
    if raw_last:
        last_for_api = resolve_volc_classic_image(
            raw_last, files_base_url, storage_local_path, log_, video_gen_id, "last_frame"
        )
    # 去重：首尾指向同一资源时只保留首帧
    if first_for_api and last_for_api and first_for_api == last_for_api:
        last_for_api = None

    has_any_frame = bool(first_for_api or last_for_api)
    volc_task_type = ("i2v" if has_any_frame else "t2v") if is_volc else None

    effective_duration = dur
    if is_volc:
        rounded = _safe_round(dur)
        effective_duration = normalize_volcengine_duration(final_model, rounded)
        if effective_duration != rounded:
            log_.info("Adjusted duration for Volcengine", extra={
                "original": dur, "adjusted": effective_duration,
                "model": final_model, "video_gen_id": video_gen_id,
            })

    body: dict[str, Any] = {
        "model": final_model,
        "content": [{"type": "text", "text": prompt or ""}],
        "ratio": ratio,
        "aspect_ratio": ratio,
        "duration": effective_duration,
        "watermark": bool(watermark) if watermark is not None else False,
    }
    if resolution:
        body["resolution"] = resolution
    if seed is not None:
        n = _to_num(seed)
        if _is_finite(n):
            body["seed"] = n
    if camera_fixed is not None:
        body["camera_fixed"] = bool(camera_fixed)
    if volc_task_type:
        body["task_type"] = volc_task_type

    # 官方要求：first_frame 必须在 last_frame 之前；role 严格区分
    if first_for_api:
        body["content"].append({"type": "image_url", "image_url": {"url": first_for_api}, "role": "first_frame"})
    if last_for_api:
        body["content"].append({"type": "image_url", "image_url": {"url": last_for_api}, "role": "last_frame"})

    # 向后兼容：无任何 first/last 字段时，单张 image_url 仍按老逻辑作为 first_frame
    if (not has_any_frame) and image_url and str(image_url).strip():
        legacy = resolve_volc_classic_image(
            image_url, files_base_url, storage_local_path, log_, video_gen_id, "image_url_fallback"
        )
        if legacy:
            body["content"].append({"type": "image_url", "image_url": {"url": legacy}, "role": "first_frame"})
            if not body.get("task_type"):
                body["task_type"] = "i2v"

    # Seedance 1.5 Pro（火山）480p 草稿模式：降本提速
    if is_volc:
        m = str(final_model or "").lower()
        res_str = str(resolution).lower() if resolution else ""
        if "seedance" in m and "1-5" in m and "pro" in m and res_str == "480p":
            body["draft"] = True
            log_.info("启用 Seedance 1.5 Pro 草稿模式 (draft=true) 以降低成本并提升速度",
                      extra={"model": final_model, "resolution": resolution, "video_gen_id": video_gen_id})

    def default_post(u: str, headers: dict, payload: dict):
        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text

    do_post = post_json or default_post
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or "")}
    status_code, raw = do_post(url, headers, body)
    log_.info("Video API raw response",
              extra={"video_gen_id": video_gen_id, "status": status_code, "raw": raw[:1000]})

    if status_code < 200 or status_code >= 300:
        log_.error("Video API failed", extra={"status": status_code, "body": raw[:500]})
        err_msg = f"视频生成失败: {status_code}"
        try:
            err_json = json.loads(raw)
            e = err_json.get("error")
            msg = (e or {}).get("message") if isinstance(e, dict) else None
            msg = msg or err_json.get("message") or e
            if msg:
                err_msg += " - " + (msg if isinstance(msg, str) else json.dumps(msg, ensure_ascii=False)[:200])
        except Exception:  # noqa: BLE001
            if raw:
                err_msg += " - " + raw[:200]
        return {"error": err_msg}

    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        log_.error("Video API response JSON parse failed",
                   extra={"video_gen_id": video_gen_id, "raw": raw[:1000], "parse_error": str(e)})
        return {"error": f"视频生成响应解析失败: {e} | raw: {raw[:200]}"}

    log_.info("Video API parsed response",
              extra={"video_gen_id": video_gen_id, "data": json.dumps(data, ensure_ascii=False)[:500]})

    task_id = data.get("id") or data.get("task_id") or (data.get("data") or {}).get("id")
    status = data.get("status") or (data.get("data") or {}).get("status")
    video_url = pick_proxy_video_url(data)
    if video_url:
        log_.info("Video API returned video_url directly",
                  extra={"video_gen_id": video_gen_id, "video_url": video_url})
        return {"video_url": video_url}
    if task_id:
        log_.info("Video API returned task_id",
                  extra={"video_gen_id": video_gen_id, "task_id": task_id, "status": status})
        return {"task_id": task_id, "status": status or "processing"}
    log_.error("Video API: no task_id or video_url in response",
               extra={"video_gen_id": video_gen_id, "data": json.dumps(data, ensure_ascii=False)[:500]})
    return {"error": "未返回 task_id 或 video_url: " + json.dumps(data, ensure_ascii=False)[:300]}


def resolve_veo3_image(raw_img_url, storage_local_path, log_, video_gen_id=None, cfg: dict | None = None) -> dict | None:
    """等价 resolveVeo3ImageForApi：优先转图床 URL，失败回退内联 base64。"""
    from urllib.parse import urlparse

    from app.services import uploadService

    raw = str(raw_img_url or "").strip()
    if not raw:
        return None
    tag = f"videoref_{video_gen_id or 0}"
    try:
        host = (urlparse(raw if re.match(r"^https?://", raw, re.IGNORECASE) else "https://" + raw).hostname or "").lower()
        if "imageproxy.zhongzhuan.chat" in host:
            return {"kind": "url", "value": raw}
    except Exception:  # noqa: BLE001
        pass

    if not raw.startswith("data:") and storage_local_path:
        proxy_url = uploadService.upload_local_image_to_proxy(
            storage_local_path, raw, log_, tag, cfg
        )
        if proxy_url:
            return {"kind": "url", "value": proxy_url}

    if raw.startswith("data:"):
        m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", raw, re.DOTALL | re.IGNORECASE)
        if m:
            try:
                buf = base64.b64decode(re.sub(r"\s", "", m.group(2)))
                mt = (m.group(1) or "image/jpeg").lower()
                mime = "image/png" if "png" in mt else ("image/webp" if "webp" in mt else "image/jpeg")
                proxy_url = uploadService.upload_to_image_proxy(buf, mime, log_, tag, cfg)
                if proxy_url:
                    return {"kind": "url", "value": proxy_url}
                log_.warning("[视频参考图] data 图床失败，回退内联 data",
                             extra={"video_gen_id": video_gen_id})
            except Exception as e:  # noqa: BLE001
                log_.warning("[视频参考图] data 解析失败",
                             extra={"video_gen_id": video_gen_id, "reason": str(e)})
        return {"kind": "data", "value": raw}

    rel_after_static = ""
    if "/static/" in raw:
        rel_after_static = re.sub(r"^/+", "", (raw.split("/static/")[1] or "").split("?")[0].split("#")[0])
    if rel_after_static and storage_local_path:
        try:
            try:
                from urllib.parse import unquote

                safe_rel = unquote(rel_after_static)
            except Exception:  # noqa: BLE001
                safe_rel = rel_after_static
            local_file = Path(storage_local_path) / safe_rel
            resolved = local_file.resolve()
            base_resolved = Path(storage_local_path).resolve()
            if str(resolved).startswith(str(base_resolved)) and local_file.exists():
                buf = local_file.read_bytes()
                ext = local_file.suffix.lower()
                mime = _MIME_BY_EXT.get(ext, "image/jpeg")
                proxy_url = uploadService.upload_to_image_proxy(buf, mime, log_, tag, cfg)
                if proxy_url:
                    return {"kind": "url", "value": proxy_url}
                log_.warning("[视频参考图] 本地图床失败 → base64", extra={"video_gen_id": video_gen_id})
                return {"kind": "data",
                        "value": f"data:{mime};base64," + base64.b64encode(buf).decode("ascii")}
        except Exception as e:  # noqa: BLE001
            log_.warning("[视频参考图] 读本地文件失败",
                         extra={"video_gen_id": video_gen_id, "reason": str(e)})

    if re.match(r"^https?://", raw, re.IGNORECASE):
        try:
            status, buf, ct = _fetch_bytes(raw)
            if 200 <= status < 300:
                mime = ct if ct.startswith("image/") else "image/jpeg"
                proxy_url = uploadService.upload_to_image_proxy(buf, mime, log_, tag, cfg)
                if proxy_url:
                    return {"kind": "url", "value": proxy_url}
                log_.warning("[视频参考图] 拉取后图床失败 → base64", extra={"video_gen_id": video_gen_id})
                return {"kind": "data",
                        "value": f"data:{mime};base64," + base64.b64encode(buf).decode("ascii")}
            log_.warning("[视频参考图] fetch 非 2xx",
                         extra={"status": status, "url_head": raw[:96], "video_gen_id": video_gen_id})
        except Exception as e:  # noqa: BLE001
            log_.warning("[视频参考图] fetch 失败",
                         extra={"url_head": raw[:96], "video_gen_id": video_gen_id, "reason": str(e)})
        return {"kind": "url", "value": raw}

    return {"kind": "url", "value": raw}


def call_veo3_video_api(config: dict, log_, opts: dict, post_json=None, cfg: dict | None = None) -> dict:
    """等价 callVeo3VideoApi：body { model, prompt, enhance_prompt, images? }。"""
    prompt = opts.get("prompt")
    model = opts.get("model")
    image_url = opts.get("image_url")
    storage_local_path = opts.get("storage_local_path")
    video_gen_id = opts.get("video_gen_id")

    base = re.sub(r"/$", "", config.get("base_url") or "")
    ep = config.get("endpoint") or "/v1/video/create"
    if not ep.startswith("/"):
        ep = "/" + ep
    url = base + ep

    body: dict[str, Any] = {"model": model or "", "prompt": prompt or "", "enhance_prompt": True}

    raw_img = str(image_url or "").strip()
    if raw_img:
        resolved = resolve_veo3_image(raw_img, storage_local_path, log_, video_gen_id, cfg)
        if resolved and resolved.get("value"):
            body["images"] = [resolved["value"]]
            log_.info("[视频参考图] Veo3 已解析", extra={
                "transport": resolved.get("kind"),
                "value_head": str(resolved["value"])[:80],
                "video_gen_id": video_gen_id,
            })

    log_.info("[Veo3] Video API request", extra={
        "url": url, "model": model, "has_image": bool(body.get("images")),
        "prompt_len": len(prompt or ""), "video_gen_id": video_gen_id,
    })

    def default_post(u, headers, payload):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text

    do_post = post_json or default_post
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or "")}
    status_code, raw = do_post(url, headers, body)
    log_.info("[Veo3] raw response", extra={"status": status_code, "raw": raw[:1000], "video_gen_id": video_gen_id})

    if status_code < 200 or status_code >= 300:
        err_msg = f"Veo3 request failed: {status_code}"
        try:
            err_json = json.loads(raw)
            e = err_json.get("error")
            msg = (e or {}).get("message") if isinstance(e, dict) else None
            msg = msg or err_json.get("message") or e
            if msg:
                err_msg += " - " + (msg if isinstance(msg, str) else json.dumps(msg, ensure_ascii=False)[:200])
        except Exception:  # noqa: BLE001
            if raw:
                err_msg += " - " + raw[:200]
        return {"error": err_msg}

    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Veo3 bad response: {e} | raw: {raw[:200]}"}

    direct = pick_proxy_video_url(data)
    if direct:
        log_.info("[Veo3] direct video URL", extra={"video_url": direct, "video_gen_id": video_gen_id})
        return {"video_url": direct}
    task_id = (
        data.get("task_id") or data.get("id") or data.get("request_id")
        or (data.get("data") or {}).get("task_id") or (data.get("data") or {}).get("id")
    )
    if task_id:
        log_.info("[Veo3] task ID returned",
                  extra={"task_id": task_id, "status": data.get("status"), "video_gen_id": video_gen_id})
        return {"task_id": str(task_id), "status": data.get("status") or "processing"}
    log_.error("[Veo3] cannot parse task_id or video_url",
               extra={"data": json.dumps(data, ensure_ascii=False)[:500], "video_gen_id": video_gen_id})
    return {"error": "Veo3 no task_id or video_url: " + json.dumps(data, ensure_ascii=False)[:300]}


def _resolve_public_or_local_image_url(raw_url: str, files_base_url: str | None, storage_local_path: str | None, log_=None, tag: str = "video_ref") -> str | None:
    raw = str(raw_url or "").strip()
    if not raw:
        return None
    if raw.startswith("data:"):
        return raw
    if re.match(r"^https?://", raw, re.IGNORECASE) and not re.search(r"localhost|127\.0\.0\.1", raw, re.IGNORECASE):
        return raw
    if storage_local_path:
        if "/static/" in raw:
            rel = re.sub(r"^/+", "", raw.split("/static/", 1)[1].split("?", 1)[0].split("#", 1)[0])
            file_path = Path(storage_local_path) / rel.replace("/", os.sep)
            if file_path.exists():
                try:
                    with open(file_path, "rb") as fh:
                        buf = fh.read()
                    mime = _MIME_BY_EXT.get(file_path.suffix.lower(), "image/jpeg")
                    return "data:" + mime + ";base64," + base64.b64encode(buf).decode("ascii")
                except Exception:  # noqa: BLE001
                    pass
        base = re.sub(r"/$", "", str(files_base_url or ""))
        if base and raw.startswith(base):
            rel = re.sub(r"^https?://[^/]+", "", raw)
            rel = rel.replace(base, "", 1).lstrip("/")
            file_path = Path(storage_local_path) / rel.replace("/", os.sep)
            if file_path.exists():
                try:
                    with open(file_path, "rb") as fh:
                        buf = fh.read()
                    mime = _MIME_BY_EXT.get(file_path.suffix.lower(), "image/jpeg")
                    return "data:" + mime + ";base64," + base64.b64encode(buf).decode("ascii")
                except Exception:  # noqa: BLE001
                    pass
    return raw


def call_jimeng_ai_api_video(config: dict, log_, opts: dict, post_json=None) -> dict:
    model = get_model_from_config(config, opts.get("model"))
    base = re.sub(r"/$", "", str(config.get("base_url") or "")).strip()
    if not base:
        return {"error": "Jimeng AI API 未配置 Base URL（请填写自建服务地址，如 http://127.0.0.1:8000）"}
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return {"error": "Jimeng AI API 未配置 Session（填入 API Key 字段，多个用英文逗号分隔）"}

    ratio = normalize_aspect_ratio_for_api(opts.get("aspect_ratio")) or "16:9"
    duration = opts.get("duration")
    dur = 4 if str(model).lower().find("seedance") >= 0 else 5
    if duration is not None:
        try:
            n = float(duration)
            dur = 4 if n <= 4 else 8 if n <= 8 else 12
        except Exception:  # noqa: BLE001
            pass

    url = base + (str(config.get("endpoint") or "/v1/videos/generations").strip())
    if not url.startswith(("http://", "https://")):
        url = base + ("/" if not str(config.get("endpoint") or "").startswith("/") else "") + str(config.get("endpoint") or "/v1/videos/generations")

    body = {
        "model": model,
        "prompt": str(opts.get("prompt") or ""),
        "ratio": ratio,
        "duration": dur,
        "resolution": str(opts.get("resolution") or "720p"),
    }
    ref_urls = []
    for key in ("reference_urls", "image_url", "first_frame_url", "last_frame_url"):
        val = opts.get(key)
        if isinstance(val, list):
            ref_urls.extend([str(v).strip() for v in val if str(v).strip()])
        elif val:
            ref_urls.append(str(val).strip())
    if ref_urls:
        body["reference_urls"] = ref_urls

    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text

    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"Jimeng AI API {status_code}: {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Jimeng AI API 非 JSON 响应 ({status_code}): {raw[:300]}"}
    video_url = ((data.get("data") or [{}])[0] if isinstance(data.get("data"), list) else {}).get("url") or data.get("video_url") or ((data.get("output") or {}).get("video_url"))
    if video_url:
        return {"video_url": str(video_url)}
    task_id = data.get("task_id") or data.get("id") or ((data.get("data") or {}).get("task_id"))
    if task_id:
        return {"task_id": str(task_id), "status": data.get("status") or "processing"}
    return {"error": "Jimeng AI API 未返回 data[0].url: " + json.dumps(data, ensure_ascii=False)[:400]}


def call_xai_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    model = get_model_from_config(config, opts.get("model"))
    base = re.sub(r"/$", "", str(config.get("base_url") or "https://api.x.ai"))
    ep = str(config.get("endpoint") or "/v1/videos/generations")
    if not ep.startswith("/"):
        ep = "/" + ep
    url = base + ep
    ratio = normalize_aspect_ratio_for_api(opts.get("aspect_ratio")) or "16:9"
    duration = opts.get("duration")
    safe_duration = max(1, min(15, int(float(duration)) if duration is not None else 8))

    body = {
        "model": model or "grok-imagine-video",
        "prompt": str(opts.get("prompt") or ""),
        "duration": safe_duration,
        "aspect_ratio": ratio,
    }
    if opts.get("image_url"):
        body["image"] = {"url": str(opts["image_url"]).strip()}
    if opts.get("reference_urls"):
        body["reference_images"] = [{"url": str(u).strip()} for u in opts["reference_urls"] if str(u).strip()]

    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text

    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or "")}, body)
    if status_code < 200 or status_code >= 300:
        err = raw[:200]
        return {"error": f"xAI 视频请求失败: {status_code} - {err}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"xAI 响应非 JSON: {raw[:200]}"}
    video_url = pick_proxy_video_url(data)
    if video_url:
        return {"video_url": video_url}
    task_id = data.get("request_id") or data.get("task_id") or data.get("id")
    if task_id:
        return {"task_id": str(task_id), "status": data.get("status") or "submitted"}
    return {"error": "xAI 未返回 request_id 或视频地址: " + json.dumps(data, ensure_ascii=False)[:300]}


def call_dash_scope_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    model = get_model_from_config(config, opts.get("model"))
    base = re.sub(r"/$", "", str(config.get("base_url") or ""))
    url = base + (str(config.get("endpoint") or "/api/v1/services/aigc/video-generation/video-synthesis"))
    if not url.startswith(("http://", "https://")):
        url = base + "/api/v1/services/aigc/video-generation/video-synthesis"
    body = {
        "model": model,
        "input": {"prompt": str(opts.get("prompt") or "")},
        "parameters": {"duration": int(float(opts.get("duration") or 10)), "size": "1280*720"},
    }
    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or ""), "X-DashScope-Async": "enable"}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"DashScope 请求失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"DashScope 响应非 JSON: {raw[:200]}"}
    video_url = parse_dash_scope_video_url(data)
    if video_url:
        return {"video_url": video_url}
    task_id = (data.get("output") or {}).get("task_id") or data.get("task_id") or data.get("id")
    if task_id:
        return {"task_id": str(task_id), "status": (data.get("output") or {}).get("task_status") or "PENDING"}
    return {"error": "DashScope 未返回 task_id 或 video_url: " + json.dumps(data, ensure_ascii=False)[:300]}


def call_gemini_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    model = get_model_from_config(config, opts.get("model"))
    base = re.sub(r"/$", "", str(config.get("base_url") or "https://generativelanguage.googleapis.com"))
    url = f"{base}/v1beta/models/{model}:generateVideo"
    body = {"prompt": str(opts.get("prompt") or "")}
    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "x-goog-api-key": config.get("api_key") or ""}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"Gemini 视频请求失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Gemini 响应非 JSON: {raw[:200]}"}
    if data.get("done") is True:
        samples = (((data.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or [])
        video_uri = (samples[0].get("video") or {}).get("uri") if samples else None
        if video_uri:
            return {"video_url": video_uri}
    task_id = data.get("id") or data.get("task_id") or data.get("request_id")
    if task_id:
        return {"task_id": str(task_id), "status": data.get("status") or "processing"}
    return {"error": "Gemini 未返回 task_id 或视频地址: " + json.dumps(data, ensure_ascii=False)[:300]}


def parse_vidu_aspect_ratio(aspect_str: str | None) -> float | None:
    t = str(aspect_str or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$", t)
    if not m or float(m.group(2)) == 0:
        return None
    return float(m.group(1)) / float(m.group(2))


def vidu_image_aspect_mismatches_target(img_w: float, img_h: float, target_aspect_str: str, rel_tol: float = 0.06) -> bool:
    tgt = parse_vidu_aspect_ratio(target_aspect_str)
    if tgt is None or not img_w or not img_h or img_h <= 0:
        return False
    img_r = img_w / img_h
    diff = abs(img_r - tgt) / max(img_r, tgt, 0.01)
    return diff > rel_tol


def vidu_letterbox_canvas_pixels(aspect_str: str | None) -> tuple[int, int] | None:
    mapping = {
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "1:1": (720, 720),
        "4:3": (960, 720),
        "3:4": (720, 960),
        "21:9": (1680, 720),
    }
    return mapping.get(str(aspect_str or "").strip())


def load_vidu_reference_image_buffer(raw_img_url: str | None, public_img_url: str | None, storage_local_path: str | None, log, video_gen_id) -> bytes | None:
    try:
        buf = None
        raw = str(raw_img_url or "").strip()
        if raw.startswith("data:image"):
            idx = raw.find(",")
            b64 = raw[idx + 1:] if idx >= 0 else ""
            buf = base64.b64decode(b64)
        elif re.search(r"localhost|127\.0\.0\.1", raw, re.IGNORECASE) and storage_local_path:
            if "/static/" in raw:
                after_static = raw.split("/static/")[1]
                if after_static:
                    local_file = os.path.join(storage_local_path, after_static.lstrip("/").replace("/", os.sep))
                    if os.path.exists(local_file):
                        with open(local_file, "rb") as fh:
                            buf = fh.read()
        if not buf:
            fetch_url = str(public_img_url or "").strip() or raw
            if not fetch_url or fetch_url.startswith("data:"):
                return None
            import httpx
            with httpx.Client(timeout=25.0) as client:
                res = client.get(fetch_url)
                if res.is_success:
                    buf = res.content
            if buf and len(buf) > 25 * 1024 * 1024:
                return None
        return buf
    except Exception as e:
        if log:
            log.warning("[Vidu] load reference image buffer failed", extra={"error": str(e), "video_gen_id": video_gen_id})
        return None


def letterbox_buffer_to_vidu_aspect(image_buffer: bytes | None, aspect_str: str, log, video_gen_id) -> bytes | None:
    if not image_buffer:
        return None
    box = vidu_letterbox_canvas_pixels(aspect_str)
    if not box:
        return None
    cw, ch = box
    try:
        from PIL import Image, ImageOps
        import io
        img = Image.open(io.BytesIO(image_buffer))
        img = ImageOps.exif_transpose(img)
        out_img = ImageOps.pad(img, (cw, ch), color=(0, 0, 0))
        if out_img.mode != "RGB":
            out_img = out_img.convert("RGB")
        out_buf = io.BytesIO()
        out_img.save(out_buf, format="JPEG", quality=88)
        out_bytes = out_buf.getvalue()
        if log:
            log.info("[Vidu] letterbox OK", extra={"video_gen_id": video_gen_id, "target_aspect": aspect_str, "canvas": f"{cw}x{ch}", "out_kb": round(len(out_bytes) / 1024)})
        return out_bytes
    except Exception as e:
        if log:
            log.warning("[Vidu] letterbox failed", extra={"video_gen_id": video_gen_id, "error": str(e)})
        return None


def probe_vidu_reference_image_size(raw_img_url: str | None, public_img_url: str | None, storage_local_path: str | None, log, video_gen_id) -> dict[str, int] | None:
    try:
        buf = load_vidu_reference_image_buffer(raw_img_url, public_img_url, storage_local_path, log, video_gen_id)
        if not buf:
            return None
        from PIL import Image, ImageOps
        import io
        img = Image.open(io.BytesIO(buf))
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        if not w or not h:
            return None
        wh_ratio = w / h
        if log:
            log.info("[Vidu] probe image: dimensions", extra={"video_gen_id": video_gen_id, "width": w, "height": h, "wh_ratio": round(wh_ratio, 6)})
        return {"width": w, "height": h}
    except Exception as e:
        if log:
            log.warning("[Vidu] probe image dimensions failed", extra={"error": str(e), "video_gen_id": video_gen_id})
        return None


def vidu_mismatch_aspect_prompt_suffix(target_ratio_label: str | None) -> str:
    r = target_ratio_label or "16:9"
    return (
        f"【画幅】参考图仅作角色、场景与风格参考，请勿沿用参考图的画幅比例；请按 {r} 宽高比输出整段视频，构图与运镜可在该比例下自由发挥。"
        f" The reference image is for subject/scene/style only; output the full video in aspect ratio {r}, not the reference frame shape."
    )


def call_vidu_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    prompt = opts.get("prompt") or ""
    model = opts.get("model")
    duration = opts.get("duration")
    aspect_ratio = opts.get("aspect_ratio")
    resolution_opt = opts.get("resolution")
    image_url = str(opts.get("image_url") or "").strip()
    video_gen_id = opts.get("video_gen_id")
    files_base_url = opts.get("files_base_url")
    storage_local_path = opts.get("storage_local_path")

    api_key = config.get("api_key") or ""
    base = re.sub(r"/$", "", str(config.get("base_url") or "https://api.vidu.cn"))
    model_name = get_model_from_config(config, model) or "viduq2"
    try:
        dur = min(10, max(1, round(float(duration or 5))))
    except (ValueError, TypeError):
        dur = 5
    ratio = clamp_to_vidu_aspect_ratio(aspect_ratio or "16:9")
    has_image = bool(image_url)
    resolution_body = pick_vidu_resolution_param(resolution_opt, model_name, has_image)

    is_official_vidu = bool(re.search(r"api\.vidu\.cn", base, re.IGNORECASE))
    auth_header = ("Token " if is_official_vidu else "Bearer ") + api_key

    default_ep = "/ent/v2/img2video" if has_image else "/ent/v2/text2video"
    ep = str(config.get("endpoint") or default_ep)
    if not ep.startswith("/"):
        ep = "/" + ep
    url = base + ep

    effective_prompt = str(prompt).strip()

    body: dict[str, Any] = {
        "model": model_name,
        "prompt": effective_prompt,
        "duration": dur,
        "resolution": resolution_body,
        "aspect_ratio": ratio,
        "movement_amplitude": "auto",
        "audio": False,
        "off_peak": False,
        "watermark": False,
    }
    if not is_official_vidu:
        body["aspectRatio"] = ratio

    if has_image:
        public_img_url = None
        raw_img_url = image_url
        if re.search(r"localhost|127\.0\.0\.1", raw_img_url, re.IGNORECASE):
            public_img_url = upload_local_image_to_proxy(storage_local_path, raw_img_url, log_, f"vidu_vg{video_gen_id}", config)
            if not public_img_url and files_base_url and not re.search(r"localhost|127\.0\.0\.1", files_base_url, re.IGNORECASE):
                public_img_url = re.sub(r"/$", "", files_base_url) + re.sub(r"^https?://[^/]+", "", raw_img_url)
        else:
            public_img_url = raw_img_url

        if public_img_url:
            image_url_for_vidu = public_img_url
            dims = probe_vidu_reference_image_size(raw_img_url, public_img_url, storage_local_path, log_, video_gen_id)
            tgt_num = parse_vidu_aspect_ratio(ratio)
            rel_tol = 0.06
            aspect_mismatch = bool(dims and tgt_num is not None and vidu_image_aspect_mismatches_target(dims["width"], dims["height"], ratio, rel_tol))

            used_letterbox = False
            if aspect_mismatch and vidu_letterbox_canvas_pixels(ratio):
                src_buf = load_vidu_reference_image_buffer(raw_img_url, public_img_url, storage_local_path, log_, video_gen_id)
                if src_buf:
                    lb_buf = letterbox_buffer_to_vidu_aspect(src_buf, ratio, log_, video_gen_id)
                    if lb_buf:
                        lb_url = upload_to_image_proxy(lb_buf, "image/jpeg", log_, f"vidu_vg{video_gen_id}_ar", config)
                        if lb_url:
                            image_url_for_vidu = lb_url
                            used_letterbox = True

            if aspect_mismatch and not used_letterbox:
                suffix = vidu_mismatch_aspect_prompt_suffix(ratio)
                sep = "\n\n"
                combined = f"{effective_prompt}{sep}{suffix}" if effective_prompt else suffix
                max_len = 5000
                if len(combined) > max_len:
                    room = max_len - len(suffix) - len(sep)
                    head = effective_prompt[:room] if (room > 0 and effective_prompt) else ""
                    combined = f"{head}{sep}{suffix}" if head else suffix[:max_len]
                effective_prompt = combined
                body["prompt"] = effective_prompt

            body["images"] = [image_url_for_vidu]

    def default_post(u: str, headers: dict, payload: dict):
        import httpx
        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text

    do_post = post_json or default_post
    headers = {"Content-Type": "application/json", "Authorization": auth_header}
    status_code, raw = do_post(url, headers, body)

    if status_code < 200 or status_code >= 300:
        err_msg = f"Vidu request failed: {status_code}"
        try:
            err_json = json.loads(raw)
            err_obj = err_json.get("error")
            msg = (
                err_json.get("message")
                or err_json.get("err_code")
                or (err_obj.get("message") if isinstance(err_obj, dict) else None)
                or err_obj
            )
            if msg:
                err_msg += f" - {str(msg)[:200]}"
        except Exception:
            if raw:
                err_msg += f" - {raw[:200]}"
        return {"error": err_msg}

    try:
        data = json.loads(raw)
    except Exception:
        return {"error": f"Vidu bad response: {raw[:200]}"}

    video_url = pick_proxy_video_url(data)
    if video_url:
        return {"video_url": video_url}

    task_id = data.get("task_id") or data.get("id") or (data.get("data") or {}).get("task_id")
    if not task_id:
        return {"error": "Vidu no task_id returned"}
    return {"task_id": str(task_id), "state": data.get("state"), "status": data.get("status") or "processing"}


def call_kling_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    model = get_model_from_config(config, opts.get("model")) or "kling-video"
    base = re.sub(r"/$", "", str(config.get("base_url") or "https://api.klingai.com"))
    image_url = str(opts.get("image_url") or "").strip()
    image_input = None
    if image_url:
        if image_url.startswith("data:"):
            image_input = image_url
        elif re.search(r"localhost|127\.0\.0\.1", image_url, re.IGNORECASE) and opts.get("storage_local_path"):
            image_input = _resolve_public_or_local_image_url(image_url, opts.get("files_base_url"), opts.get("storage_local_path"), log_, "kling")
        else:
            image_input = image_url
    task_type = "motion-control" if str(model).lower() == "kling-motion-control" else ("image2video" if image_input else "text2video")
    create_ep = str(config.get("endpoint") or ("/v1/videos/motion-control" if task_type == "motion-control" else "/v1/videos/image2video" if image_input else "/v1/videos/text2video"))
    if not create_ep.startswith("/"):
        create_ep = "/" + create_ep
    url = base + create_ep
    body = {
        "model": model,
        "prompt": str(opts.get("prompt") or ""),
        "aspect_ratio": normalize_aspect_ratio_for_api(opts.get("aspect_ratio")) or "16:9",
        "duration": "5" if int(float(opts.get("duration") or 5)) <= 5 else "10",
        "cfg_scale": 0.5,
        "mode": "std",
        "callback_url": "",
    }
    if image_input:
        body["image"] = {"type": "url", "url": image_input}
    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or "")}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"可灵视频生成请求失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"可灵视频响应格式异常: {raw[:200]}"}
    if data.get("code") not in (None, 0):
        return {"error": f"可灵错误({data.get('code')}): {data.get('message') or '未知错误'}"}
    direct_url = (((data.get("data") or {}).get("task_result") or {}).get("videos") or [{}])[0].get("url")
    if direct_url:
        return {"video_url": direct_url}
    task_id = (data.get("data") or {}).get("task_id") or data.get("task_id") or data.get("id")
    if task_id:
        return {"task_id": f"{task_type}:{task_id}", "status": "submitted"}
    return {"error": "可灵未返回 task_id: " + raw[:200]}


def call_kling_omni_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    cfg = apply_kling_omni_env_overrides(config)
    base = resolve_kling_omni_base_url(cfg)
    bearer = resolve_kling_omni_bearer_token(cfg, log_)
    if not bearer:
        return {"error": "可灵 Omni 未配置鉴权：请填写「API Key」（中转 Bearer），或在高级设置中填写官方 AccessKey + SecretKey（存 settings，自动生成 JWT）"}
    model_name = get_model_from_config(config, opts.get("model")) or "kling-video-o1"
    body = {
        "model_name": model_name,
        "mode": "std",
        "duration": omni_duration_string(model_name, opts.get("duration")),
        "multi_shot": False,
        "prompt": str(opts.get("prompt") or "").strip()[:2500],
        "sound": "off",
        "aspect_ratio": resolve_kling_omni_aspect_ratio(opts.get("aspect_ratio"), log_, opts.get("video_gen_id")),
    }
    ref_urls = []
    for key in ("reference_urls", "image_url"):
        val = opts.get(key)
        if isinstance(val, list):
            ref_urls.extend([str(v).strip() for v in val if str(v).strip()])
        elif str(val or "").strip():
            ref_urls.append(str(val).strip())
    if ref_urls:
        image_list = []
        for idx, raw in enumerate(ref_urls[:10]):
            resolved = _resolve_public_or_local_image_url(raw, opts.get("files_base_url"), opts.get("storage_local_path"), log_, f"omni_{idx}")
            if resolved:
                image_list.append({"image_url": resolved, "type": "first_frame" if idx == 0 else "reference_image"})
        if image_list:
            body["image_list"] = image_list
    url = base + str(resolve_kling_omni_create_path(cfg, base))
    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "Authorization": (bearer if bearer.startswith("Bearer ") else f"Bearer {bearer}")}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"Kling Omni 创建失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Kling Omni 响应非 JSON: {raw[:200]}"}
    direct_url = pick_proxy_video_url(data)
    if direct_url:
        return {"video_url": direct_url}
    task_id = (data.get("data") or {}).get("task_id") or data.get("task_id") or data.get("id")
    if task_id:
        return {"task_id": "omni:" + str(task_id), "status": "submitted"}
    return {"error": "Kling Omni 未返回 task_id: " + raw[:300]}


def call_volcengine_omni_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    model = get_model_from_config(config, opts.get("model"))
    url = build_video_url(config, {"defaultEndpoint": "/v1/videos/generations"})
    final_model = normalize_volc_model(model)
    body = {
        "model": final_model,
        "content": [{"type": "text", "text": str(opts.get("prompt") or "").strip()}],
        "ratio": opts.get("aspect_ratio") or "16:9",
        "duration": normalize_volc_omni_duration(final_model, opts.get("duration")),
        "watermark": bool(opts.get("watermark")) if opts.get("watermark") is not None else False,
    }
    for key in ("resolution", "seed", "camera_fixed"):
        if key in opts and opts.get(key) is not None:
            body[key] = opts[key]
    ref_urls = opts.get("reference_urls") or []
    if opts.get("image_url"):
        ref_urls = [opts.get("image_url")] + list(ref_urls)
    refs = []
    for idx, raw in enumerate(ref_urls[:9]):
        resolved = _resolve_public_or_local_image_url(raw, opts.get("files_base_url"), opts.get("storage_local_path"), log_, f"omni_{idx}")
        if resolved:
            refs.append({"type": "image_url", "image_url": {"url": resolved}, "role": "reference_image"})
    if refs:
        body["content"].extend(refs)
        body["task_type"] = "i2v"
    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or "")}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"火山 Seedance 全能创建失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"火山 Seedance 全能响应非 JSON: {raw[:200]}"}
    video_url = pick_proxy_video_url(data)
    if video_url:
        return {"video_url": video_url}
    task_id = data.get("id") or data.get("task_id") or (data.get("data") or {}).get("id")
    if task_id:
        return {"task_id": str(task_id), "status": data.get("status") or (data.get("data") or {}).get("status") or "processing"}
    return {"error": "火山 Seedance 全能未返回 task_id 或 video_url: " + json.dumps(data, ensure_ascii=False)[:300]}


def call_sora_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    base = re.sub(r"/$", "", str(config.get("base_url") or ""))
    ep = str(config.get("endpoint") or "/v1/videos")
    if not ep.startswith("/"):
        ep = "/" + ep
    url = base + ep
    model = get_model_from_config(config, opts.get("model")) or "sora-2"
    duration = float(opts.get("duration") or 4)
    seconds = "4" if duration <= 4 else ("8" if duration <= 8 else "12")
    size = {"9:16": "720x1280", "3:4": "1024x1792", "1:1": "720x1280", "16:9": "1280x720", "4:3": "1280x720"}.get(str(opts.get("aspect_ratio") or "9:16"), "720x1280")
    data = {
        "model": model,
        "prompt": str(opts.get("prompt") or ""),
        "seconds": seconds,
        "size": size,
        "watermark": "false",
        "private": "false",
    }
    files = None
    image_url = str(opts.get("image_url") or "").strip()
    if image_url:
        file_name = "reference.jpg"
        buf = None
        mime = "image/jpeg"
        if image_url.startswith("data:"):
            m = re.match(r"^data:([^;]+);base64,(.*)$", image_url, re.DOTALL | re.IGNORECASE)
            if m:
                mime = (m.group(1) or "image/jpeg").lower()
                buf = base64.b64decode(re.sub(r"\s", "", m.group(2)))
                ext = mime.split("/")[-1].replace("jpeg", "jpg")
                file_name = f"reference.{ext}"
        elif opts.get("storage_local_path"):
            resolved = _resolve_public_or_local_image_url(image_url, opts.get("files_base_url"), opts.get("storage_local_path"), log_, "sora")
            if resolved and resolved.startswith("data:"):
                m = re.match(r"^data:([^;]+);base64,(.*)$", resolved, re.DOTALL | re.IGNORECASE)
                if m:
                    mime = (m.group(1) or "image/jpeg").lower()
                    buf = base64.b64decode(re.sub(r"\s", "", m.group(2)))
                    file_name = f"reference.{mime.split('/')[-1].replace('jpeg', 'jpg')}"
        if buf is not None:
            files = {"input_reference": (file_name, buf, mime)}
    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, data=payload, files=files, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    headers = {"Content-Type": "multipart/form-data"} if files else {"Content-Type": "application/json"}
    status_code, raw = do_post(url, {"Authorization": "Bearer " + (config.get("api_key") or "") , **headers}, data if files is None else None)
    if status_code < 200 or status_code >= 300:
        return {"error": f"Sora 请求失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Sora 响应非 JSON: {raw[:200]}"}
    video_url = pick_proxy_video_url(data)
    if video_url:
        return {"video_url": video_url}
    task_id = data.get("id") or data.get("task_id") or data.get("request_id") or (data.get("data") or {}).get("task_id")
    if task_id:
        return {"task_id": str(task_id), "status": data.get("status") or "processing"}
    return {"error": "Sora 未返回 task_id 或 video_url: " + json.dumps(data, ensure_ascii=False)[:300]}


def call_agnes_video_api(config: dict, log_, opts: dict, post_json=None, db=None) -> dict:
    base = re.sub(r"/$", "", str(config.get("base_url") or "https://apihub.agnes-ai.com/v1"))
    ep = str(config.get("endpoint") or "/videos")
    if not ep.startswith("/"):
        ep = "/" + ep
    url = base + ep
    ratio = normalize_aspect_ratio_for_api(opts.get("aspect_ratio")) or "16:9"
    width, height = 1152, 768
    if ratio == "9:16":
        width, height = 768, 1152
    elif ratio == "4:3":
        width, height = 1024, 768
    elif ratio == "3:4":
        width, height = 768, 1024
    elif ratio == "1:1":
        width, height = 768, 768
    frame_rate = 24
    duration = float(opts.get("duration") or 5)
    num_frames = 24 * duration
    allowed = [24, 48, 72, 96, 120, 144, 168, 192, 216, 240, 264, 288, 312, 336, 360]
    num_frames = min(allowed, key=lambda x: abs(x - num_frames))
    body = {
        "model": get_model_from_config(config, opts.get("model")) or "agnes-video-v2.0",
        "prompt": str(opts.get("prompt") or ""),
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
    }
    ref_urls = list(opts.get("reference_urls") or [])
    use_omni_reference = len(ref_urls) > 0
    resolved_refs = []
    seen = set()
    for idx, raw in enumerate(ref_urls):
        resolved = _resolve_public_or_local_image_url(raw, opts.get("files_base_url"), opts.get("storage_local_path"), log_, f"agnes_ref_{idx}")
        if resolved and resolved not in seen:
            seen.add(resolved)
            resolved_refs.append(resolved)
    first_resolved = None
    last_resolved = None
    if not use_omni_reference:
        for key_name, role in (("first_frame_url", "first_frame"), ("last_frame_url", "last_frame")):
            raw = str(opts.get(key_name) or "").strip()
            if raw:
                resolved = _resolve_public_or_local_image_url(raw, opts.get("files_base_url"), opts.get("storage_local_path"), log_, f"agnes_{role}")
                if role == "first_frame":
                    first_resolved = resolved
                else:
                    last_resolved = resolved
    payload = build_agnes_video_image_payload(
        use_omni_reference,
        resolved_refs,
        first_resolved,
        last_resolved,
    )
    if payload.get("image") is not None:
        body["image"] = payload["image"]
    if payload.get("extra_body"):
        body["extra_body"] = payload["extra_body"]
    def default_post(u: str, headers: dict, payload_dict: dict):
        import httpx

        resp = httpx.post(u, json=payload_dict, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or "")}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"Agnes 视频请求失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Agnes 响应解析失败: {raw[:200]}"}
    direct_url = extract_agnes_video_url(data)
    if direct_url:
        return {"video_url": direct_url}
    task_id = data.get("id") or data.get("task_id") or (data.get("data") or {}).get("id") or (data.get("data") or {}).get("task_id")
    if task_id:
        return {"task_id": str(task_id), "status": data.get("status") or "processing"}
    return {"error": "Agnes 未返回 task_id 或 video_url: " + json.dumps(data, ensure_ascii=False)[:300]}


def build_minimax_h3_create_url(config: dict) -> str:
    """等价 buildMinimaxH3CreateUrl：构造 MiniMax H3 创建请求的 URL。"""
    root = get_minimax_api_root(config.get("base_url"))
    ep = str(config.get("endpoint") or "/v2/video_generation").strip()
    if not ep.startswith("/"):
        ep = "/" + ep
    return root + ep


def call_minimax_h3_video_api(config: dict, log_, opts: dict, post_json=None) -> dict:
    model = get_model_from_config(config, opts.get("model")) or "MiniMax-H3"
    url = build_minimax_h3_create_url(config)
    if not url:
        return {"error": "MiniMax H3 配置异常"}
    final_model = model if is_minimax_h3_model(model) else "MiniMax-H3"
    dur = normalize_minimax_h3_duration(opts.get("duration"))
    ratio = normalize_aspect_ratio_for_api(opts.get("aspect_ratio")) or "16:9"
    content = [{"type": "text", "text": str(opts.get("prompt") or "").strip() or "cinematic scene"}]
    first_raw = str(opts.get("first_frame_url") or opts.get("image_url") or "").strip()
    last_raw = str(opts.get("last_frame_url") or "").strip()
    first_for_api = _resolve_public_or_local_image_url(first_raw, opts.get("files_base_url"), opts.get("storage_local_path"), log_, "minimax_first")
    last_for_api = _resolve_public_or_local_image_url(last_raw, opts.get("files_base_url"), opts.get("storage_local_path"), log_, "minimax_last") if last_raw else None
    if first_for_api and last_for_api and first_for_api == last_for_api:
        last_for_api = None
    refs = opts.get("reference_urls") or []
    use_first_last = bool(first_for_api or last_for_api)
    if use_first_last:
        if first_for_api:
            content.append({"type": "image_url", "image_url": {"url": first_for_api}, "role": "first_frame"})
        if last_for_api:
            content.append({"type": "image_url", "image_url": {"url": last_for_api}, "role": "last_frame"})
    else:
        for idx, raw in enumerate(refs[:9]):
            resolved = _resolve_public_or_local_image_url(str(raw or "").strip(), opts.get("files_base_url"), opts.get("storage_local_path"), log_, f"minimax_ref_{idx}")
            if resolved:
                content.append({"type": "image_url", "image_url": {"url": resolved}, "role": "reference_image"})
    body = {"model": final_model, "content": content, "duration": dur, "resolution": normalize_minimax_h3_resolution(opts.get("resolution"))}
    if not use_first_last and not refs:
        body["ratio"] = ratio if ratio != "adaptive" else "16:9"
    elif use_first_last:
        body["ratio"] = "adaptive"
    def default_post(u: str, headers: dict, payload: dict):
        import httpx

        resp = httpx.post(u, json=payload, headers=headers, timeout=120.0)
        return resp.status_code, resp.text
    do_post = post_json or default_post
    status_code, raw = do_post(url, {"Content-Type": "application/json", "Authorization": "Bearer " + (config.get("api_key") or "")}, body)
    if status_code < 200 or status_code >= 300:
        return {"error": f"MiniMax H3 请求失败: {status_code} - {raw[:200]}"}
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"error": f"MiniMax H3 响应非 JSON: {raw[:200]}"}
    direct_url = extract_minimax_h3_video_url(data)
    if direct_url:
        return {"video_url": direct_url}
    task_id = data.get("task_id") or (data.get("task") or {}).get("id") or data.get("id") or (data.get("data") or {}).get("task_id")
    if task_id:
        return {"task_id": str(task_id), "status": "processing"}
    return {"error": "MiniMax H3 未返回 task_id: " + json.dumps(data, ensure_ascii=False)[:300]}


# 尚未移植的厂商协议（键存在即表示走厂商专属路径）
_VENDOR_VIDEO_DISPATCH = {
    "jimeng_ai_api": "call_jimeng_ai_api_video",
    "xai": "call_xai_video_api",
    "dashscope": "call_dash_scope_video_api",
    "gemini": "call_gemini_video_api",
    "vidu": "call_vidu_video_api",
    "kling": "call_kling_video_api",
    "kling_omni": "call_kling_omni_video_api",
    "volcengine_omni": "call_volcengine_omni_video_api",
    "sora": "call_sora_video_api",
    "agnes": "call_agnes_video_api",
    "minimax_h3": "call_minimax_h3_video_api",
}


def poll_video_task(
    log_,
    video_gen_id,
    task_id,
    config: dict,
    max_attempts: int = 300,
    interval_ms: int = 10_000,
    fetch_json=None,
) -> dict:
    """等价 pollVideoTask：按协议轮询各厂商任务，返回 { video_url } 或 { error }。

    覆盖协议：jimeng_ai_api（同步，不应轮询）、kling、kling_omni、gemini、vidu、veo3、
    sora、agnes、minimax_h3、dashscope、volcengine（方舟/火山）与 openai 通用兜底。

    fetch_json 为可注入的 (url, headers) -> (status, raw_text) 钩子，便于测试打桩；
    默认用 httpx 同步 GET。
    """
    import httpx

    provider = str(config.get("provider") or "").lower()
    protocol = resolve_video_protocol(config)
    is_dash_scope = protocol == "dashscope"
    is_gemini = protocol == "gemini"
    is_vidu = protocol == "vidu"
    is_sora = protocol == "sora"
    is_agnes = protocol == "agnes"
    is_minimax_h3 = protocol == "minimax_h3"
    is_kling = protocol == "kling"
    is_kling_omni = protocol == "kling_omni" or (isinstance(task_id, str) and task_id.startswith("omni:"))
    is_veo3 = protocol == "veo3"

    # 轮询日志里响应体最大字符数；0 / full 表示不截断
    raw_max = str(os.environ.get("VIDEO_POLL_LOG_MAX") or "16384").strip()
    if raw_max in ("0", "full"):
        poll_log_body_max = float("inf")
    else:
        try:
            n = int(raw_max)
        except ValueError:
            n = 0
        poll_log_body_max = min(n, 512 * 1024) if n > 0 else 16384

    is_volc_poll = provider in ("volces", "volcengine", "volc") or protocol in (
        "volcengine",
        "volcengine_omni",
    )

    if protocol == "jimeng_ai_api":
        log_.warning("[poll] Jimeng AI API 不应进入轮询", extra={"video_gen_id": video_gen_id, "task_id": task_id})
        return {"error": "Jimeng AI API 为同步返回视频地址，不应进入轮询"}

    poll_task_id = task_id
    # Agnes：completed 后直链偶发迟到，对齐 new-api 继续多查几轮
    agnes_completed_without_url = 0
    agnes_completed_url_grace = 12

    def query_url() -> str:
        return build_query_url(config, poll_task_id)

    def default_fetch(url: str, headers: dict):
        resp = httpx.get(url, headers=headers, timeout=60.0)
        return resp.status_code, resp.text

    do_fetch = fetch_json or default_fetch

    log_.info(
        "[poll] 开始",
        extra={"video_gen_id": video_gen_id, "task_id": poll_task_id, "protocol": protocol, "poll_url": query_url()},
    )

    for attempt in range(max_attempts):
        time.sleep(interval_ms / 1000.0)
        try:
            if is_kling:
                kling_base = re.sub(r"/$", "", config.get("base_url") or "https://api.klingai.com")
                actual_task_id = str(task_id)
                video_type = "text2video"
                if actual_task_id.startswith("i2v:"):
                    actual_task_id, video_type = actual_task_id[4:], "image2video"
                elif actual_task_id.startswith("t2v:"):
                    actual_task_id, video_type = actual_task_id[4:], "text2video"
                elif actual_task_id.startswith("mc:"):
                    actual_task_id, video_type = actual_task_id[3:], "motion-control"
                qep = str(config.get("query_endpoint") or f"/v1/videos/{video_type}/{{taskId}}")
                for token in ("taskId", "task_id", "id"):
                    qep = re.sub(r"\{" + token + r"\}", _q(actual_task_id), qep, flags=re.IGNORECASE)
                if not qep.startswith("/"):
                    qep = "/" + qep
                url = kling_base + qep
                headers = {"Authorization": "Bearer " + (config.get("api_key") or "")}
            elif is_kling_omni:
                cfg_omni = apply_kling_omni_env_overrides(config)
                omni_base = resolve_kling_omni_base_url(cfg_omni)
                actual_id = str(task_id)
                if actual_id.startswith("omni:"):
                    actual_id = actual_id[5:]
                qep = str(resolve_kling_omni_query_path_template(cfg_omni, omni_base))
                for token in ("taskId", "task_id", "id"):
                    qep = re.sub(r"\{" + token + r"\}", _q(actual_id), qep, flags=re.IGNORECASE)
                if not qep.startswith("/"):
                    qep = "/" + qep
                url = omni_base + qep
                bt = resolve_kling_omni_bearer_token(cfg_omni, log_)
                headers = ({"Authorization": bt if bt.startswith("Bearer ") else f"Bearer {bt}"} if bt else {})
            elif is_gemini:
                base = re.sub(r"/$", "", config.get("base_url") or "https://generativelanguage.googleapis.com")
                url = f"{base}/v1beta/{task_id}"
                headers = {"x-goog-api-key": config.get("api_key") or ""}
            elif is_vidu:
                vidu_base = re.sub(r"/$", "", config.get("base_url") or "https://api.vidu.cn")
                is_official_vidu = bool(re.search(r"api\.vidu\.cn", vidu_base, re.IGNORECASE))
                default_qep = "/ent/v2/tasks/{taskId}/creations"
                qep = str(config.get("query_endpoint") or default_qep)
                for token in ("taskId", "task_id", "id"):
                    qep = re.sub(r"\{" + token + r"\}", _q(task_id), qep, flags=re.IGNORECASE)
                if not qep.startswith("/"):
                    qep = "/" + qep
                url = vidu_base + qep
                headers = {"Authorization": ("Token " if is_official_vidu else "Bearer ") + (config.get("api_key") or "")}
            else:
                url = query_url()
                headers = {"Authorization": "Bearer " + (config.get("api_key") or "")}

            poll_round = attempt + 1
            log_.info("[poll] 发起查询", extra={"video_gen_id": video_gen_id, "round": poll_round, "url": url})
            status_code, raw = do_fetch(url, headers)
            body_logged = raw if len(raw) <= poll_log_body_max else (
                raw[:poll_log_body_max]
                + f"\n... [poll 响应已截断 前{poll_log_body_max}字符 / 共{len(raw)}字符，可设环境变量 VIDEO_POLL_LOG_MAX=0 输出全文]"
            )
            log_.info(
                "[poll] 查询 HTTP 结果",
                extra={"video_gen_id": video_gen_id, "round": poll_round, "http_status": status_code,
                       "bytes": len(raw), "body": body_logged},
            )
            if status_code < 200 or status_code >= 300:
                log_.warning("[poll] 查询非 2xx", extra={"video_gen_id": video_gen_id, "round": poll_round,
                                                         "http_status": status_code, "body": body_logged[:4000]})
                continue
            try:
                data = json.loads(raw)
            except Exception as parse_err:  # noqa: BLE001
                log_.warning("[poll] 响应非 JSON", extra={"video_gen_id": video_gen_id, "round": poll_round,
                                                          "error": str(parse_err), "body_head": raw[:800]})
                continue
            if not isinstance(data, dict):
                continue

            # ---- 各协议分支 ----
            if is_kling:
                code = data.get("code")
                if code is not None and code != 0:
                    msg = data.get("message") or f"可灵错误码: {code}"
                    log_.warning("[Kling poll] API 错误", extra={"video_gen_id": video_gen_id, "code": code, "reason": msg})
                    return {"error": msg}
                st = str((data.get("data") or {}).get("task_status") or "").lower()
                log_.info("[Kling poll] 状态", extra={"video_gen_id": video_gen_id, "attempt": attempt,
                                                      "status": st, "task_id": task_id})
                if st == "succeed":
                    videos = ((data.get("data") or {}).get("task_result") or {}).get("videos") or []
                    video_url = videos[0].get("url") if videos else None
                    if video_url:
                        log_.info("[Kling poll] 视频生成完成",
                                  extra={"video_gen_id": video_gen_id, "video_url": video_url})
                        return {"video_url": video_url}
                    return {"error": "可灵任务完成但未返回视频地址"}
                if st == "failed":
                    err_msg = (data.get("data") or {}).get("task_status_msg") or "任务失败"
                    log_.warning("[Kling poll] 任务失败", extra={"video_gen_id": video_gen_id, "error": err_msg})
                    return {"error": "可灵视频生成失败: " + str(err_msg)}
                continue

            if is_kling_omni:
                code = data.get("code")
                if code is not None and _to_num(code) != 0:
                    msg = data.get("message") or data.get("msg") or f"Kling Omni 错误码 {code}"
                    log_.warning("[KlingOmni poll] API 错误",
                                 extra={"video_gen_id": video_gen_id, "code": code, "reason": msg})
                    return {"error": msg}
                st = str(
                    (data.get("data") or {}).get("task_status")
                    or data.get("task_status")
                    or data.get("status") or ""
                ).lower()
                video_url_omni = parse_kling_omni_poll_video_url(data)
                log_.info("[KlingOmni poll] 状态",
                          extra={"video_gen_id": video_gen_id, "attempt": attempt, "status": st,
                                 "has_url": bool(video_url_omni)})
                if video_url_omni:
                    log_.info("[KlingOmni poll] 完成", extra={"video_gen_id": video_gen_id})
                    return {"video_url": video_url_omni}
                if st in ("succeed", "success", "completed", "succeeded", "done"):
                    return {"error": "Kling Omni 标记完成但未解析到视频地址"}
                if st in ("failed", "error"):
                    err_msg = (
                        (data.get("data") or {}).get("task_status_msg")
                        or data.get("task_status_msg")
                        or data.get("message") or "任务失败"
                    )
                    return {"error": "Kling Omni: " + str(err_msg)[:400]}
                continue

            if is_veo3:
                st = extract_poll_task_status(data)
                log_.info("[Veo3 poll] task status",
                          extra={"video_gen_id": video_gen_id, "attempt": attempt, "status": st,
                                 "id": data.get("task_id") or data.get("id")})
                if is_poll_task_failed(st):
                    msg = extract_poll_failure_message(data) or (data.get("data") or {}).get("error") or "Veo3 task failed"
                    log_.warning("[Veo3 poll] task failed", extra={"video_gen_id": video_gen_id, "reason": msg})
                    return {"error": str(msg)[:500]}
                video_url = pick_proxy_video_url(data)
                if video_url:
                    log_.info("[Veo3 poll] video completed",
                              extra={"video_gen_id": video_gen_id, "video_url": video_url})
                    return {"video_url": video_url}
                if st in ("succeeded", "completed", "done"):
                    log_.warning("[Veo3 poll] completed but no video_url",
                                 extra={"data": json.dumps(data, ensure_ascii=False)[:500]})
                    return {"error": "Veo3 completed but no video URL: " + json.dumps(data, ensure_ascii=False)[:300]}
                continue

            if is_sora:
                st = extract_poll_task_status(data)
                log_.info("[Sora poll] 状态",
                          extra={"video_gen_id": video_gen_id, "attempt": attempt, "status": st,
                                 "progress": data.get("progress"), "id": data.get("id")})
                if is_poll_task_failed(st):
                    msg = extract_poll_failure_message(data) or "Sora 任务失败"
                    log_.warning("[Sora poll] 任务失败", extra={"video_gen_id": video_gen_id, "reason": msg,
                                                               "data": json.dumps(data, ensure_ascii=False)[:300]})
                    return {"error": str(msg)[:500]}
                video_url = pick_proxy_video_url(data)
                if video_url and is_plausible_http_video_url(video_url):
                    log_.info("[Sora poll] 完成", extra={"video_gen_id": video_gen_id, "video_url": video_url})
                    return {"video_url": video_url}
                if st in ("succeeded", "completed", "done"):
                    log_.warning("[Sora poll] 已标记完成但未返回视频地址",
                                 extra={"video_gen_id": video_gen_id,
                                        "data": json.dumps(data, ensure_ascii=False)[:500]})
                    return {"error": "Sora 任务已完成但未返回可下载的视频地址: "
                                     + json.dumps(data, ensure_ascii=False)[:300]}
                continue

            if is_agnes:
                st = extract_poll_task_status(data)
                log_.info("[Agnes poll] 状态",
                          extra={"video_gen_id": video_gen_id, "attempt": attempt, "status": st,
                                 "progress": data.get("progress"), "id": data.get("id"),
                                 "poll_id": poll_task_id, "poll_url": query_url()})
                if is_poll_task_failed(st):
                    msg = extract_poll_failure_message(data) or "Agnes 视频任务失败"
                    log_.warning("[Agnes poll] 任务失败", extra={"video_gen_id": video_gen_id, "reason": msg,
                                                                 "data": json.dumps(data, ensure_ascii=False)[:300]})
                    return {"error": str(msg)[:500]}
                video_url = extract_agnes_video_url(data)
                if video_url and is_plausible_http_video_url(video_url):
                    log_.info("[Agnes poll] 完成", extra={"video_gen_id": video_gen_id, "video_url": video_url})
                    return {"video_url": video_url}
                if st in ("succeeded", "completed", "done"):
                    agnes_completed_without_url += 1
                    log_.warning("[Agnes poll] completed 但尚未返回视频直链，继续等待",
                                 extra={"video_gen_id": video_gen_id, "miss": agnes_completed_without_url,
                                        "grace": agnes_completed_url_grace,
                                        "data": json.dumps(data, ensure_ascii=False)[:500]})
                    if agnes_completed_without_url >= agnes_completed_url_grace:
                        return {"error": "Agnes 任务完成但未返回视频地址: "
                                         + json.dumps(data, ensure_ascii=False)[:300]}
                continue

            if is_minimax_h3:
                st = extract_minimax_h3_task_status(data)
                video_url = extract_minimax_h3_video_url(data)
                task_obj = data.get("task") if isinstance(data.get("task"), dict) else data
                log_.info("[MiniMaxH3 poll] 状态",
                          extra={"video_gen_id": video_gen_id, "attempt": attempt, "status": st,
                                 "has_url": bool(video_url), "id": task_obj.get("id") or task_id})
                if st in ("failed", "cancelled", "canceled", "error"):
                    err = task_obj.get("error") or {}
                    msg = (
                        (err.get("message") or err.get("code"))
                        or extract_poll_failure_message(data)
                        or st
                        or "MiniMax H3 任务失败"
                    )
                    log_.warning("[MiniMaxH3 poll] 任务失败", extra={"video_gen_id": video_gen_id, "reason": msg})
                    return {"error": str(msg)[:500]}
                if video_url and is_plausible_http_video_url(video_url):
                    log_.info("[MiniMaxH3 poll] 完成", extra={"video_gen_id": video_gen_id, "video_url": video_url})
                    return {"video_url": video_url}
                if st in ("succeeded", "completed", "success", "done"):
                    log_.warning("[MiniMaxH3 poll] 成功但无视频地址",
                                 extra={"video_gen_id": video_gen_id,
                                        "data": json.dumps(data, ensure_ascii=False)[:500]})
                    return {"error": "MiniMax H3 任务完成但未返回视频地址"}
                continue

            if is_vidu:
                st = str(data.get("state") or data.get("status") or (data.get("data") or {}).get("status") or "").lower()
                log_.info("[Vidu poll] 状态",
                          extra={"video_gen_id": video_gen_id, "attempt": attempt, "state": st, "id": task_id})
                if st in ("failed", "error"):
                    err = data.get("error")
                    msg = (
                        data.get("err_code")
                        or data.get("message")
                        or (err.get("message") if isinstance(err, dict) else None)
                        or err
                        or "Vidu 视频生成失败"
                    )
                    log_.warning("[Vidu poll] 失败", extra={"video_gen_id": video_gen_id, "reason": msg})
                    return {"error": str(msg)}
                creations = data.get("creations") or []
                first_creation = creations[0] if creations else None
                video_url = (
                    (first_creation or {}).get("url")
                    or video_url_from_record(first_creation)
                    or pick_proxy_video_url(data)
                )
                if video_url:
                    log_.info("[Vidu poll] 完成", extra={"video_gen_id": video_gen_id, "video_url": video_url})
                    return {"video_url": video_url}
                if st in ("success", "succeeded", "completed", "done"):
                    log_.warning("[Vidu poll] 成功但无视频地址",
                                 extra={"data": json.dumps(data, ensure_ascii=False)[:500]})
                    return {"error": "Vidu 任务成功但未返回视频地址"}
                continue

            if is_gemini:
                if data.get("error"):
                    err = data["error"]
                    return {"error": (err.get("message") if isinstance(err, dict) else str(err)) or "Gemini 视频生成失败"}
                if data.get("done") is True:
                    samples = (((data.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or [])
                    video_uri = (samples[0].get("video") or {}).get("uri") if samples else None
                    if video_uri:
                        return {"video_url": video_uri}
                    return {"error": "Gemini 任务完成但未返回视频地址"}
                continue

            if is_dash_scope:
                task_status = (data.get("output") or {}).get("task_status")
                video_url = parse_dash_scope_video_url(data)
                if video_url:
                    return {"video_url": video_url}
                if task_status in ("FAILED", "CANCELED"):
                    msg = data.get("message") or (data.get("output") or {}).get("message") or task_status
                    log_.warning("DashScope 任务失败（download image failed 时退化为 URL 仍指向 localhost）",
                                 extra={"video_gen_id": video_gen_id, "task_id": task_id,
                                        "task_status": task_status, "reason": msg, "output": data.get("output")})
                    return {"error": msg or "视频生成失败"}
                continue

            # ---- 通用兜底（含方舟/火山）----
            st = extract_poll_task_status(data)
            video_url = pick_proxy_video_url(data)
            fail_msg = extract_poll_failure_message(data)
            err = data.get("error")
            err_msg = (err if isinstance(err, str) else (err or {}).get("message")) if err else None

            if is_volc_poll:
                summary_json = json.dumps(data, ensure_ascii=False)
                summary = (
                    summary_json if len(summary_json) <= poll_log_body_max
                    else summary_json[:poll_log_body_max] + f"... [共{len(summary_json)}字符]"
                )
                err_code = (err or {}).get("code") if isinstance(err, dict) else None
                log_.info("[poll] 方舟/火山 解析摘要",
                          extra={"video_gen_id": video_gen_id, "round": poll_round, "top_level_status": st,
                                 "has_video_url": bool(video_url),
                                 # Node: failMsg || errMsg || data?.error?.code || data?.message || null
                                 "error_hint": fail_msg or err_msg or err_code or data.get("message"),
                                 "parsed_json": summary})

            if is_poll_task_failed(st) or err_msg:
                msg = fail_msg or err_msg or st or "任务失败"
                log_.warning("[poll] 任务失败",
                             extra={"video_gen_id": video_gen_id, "round": poll_round, "status": st, "reason": msg})
                return {"error": str(msg)[:500]}
            if video_url and is_plausible_http_video_url(video_url):
                return {"video_url": video_url}
            if fail_msg:
                log_.warning("[poll] 上游返回失败文案",
                             extra={"video_gen_id": video_gen_id, "round": poll_round, "reason": fail_msg[:200]})
                return {"error": fail_msg[:500]}
        except Exception as e:  # noqa: BLE001
            log_.warning("Video poll request failed", extra={"attempt": attempt, "error": str(e)})

    return {"error": "视频生成超时"}


def build_agnes_video_image_payload(
    use_omni_reference: bool,
    resolved_refs: list | None,
    first_resolved,
    last_resolved,
) -> dict:
    refs = [r for r in (resolved_refs or []) if r]
    if use_omni_reference and len(refs) >= 2:
        return {"strategy": "omni_reference_extra_body", "extra_body": {"image": refs[:10]}}
    if use_omni_reference and len(refs) == 1:
        return {"strategy": "omni_reference_single", "image": refs[0]}
    if (not use_omni_reference) and first_resolved and last_resolved and first_resolved != last_resolved:
        return {
            "strategy": "classic_keyframes",
            "extra_body": {"mode": "keyframes", "image": [first_resolved, last_resolved]},
        }
    if first_resolved:
        return {"strategy": "classic_i2v", "image": first_resolved}
    return {"strategy": "text_only"}
