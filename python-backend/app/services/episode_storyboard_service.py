"""剧集分镜头 AI 生成与处理服务。

与 backend-node/src/services/episodeStoryboardService.js 严格 1:1 对齐：
- normalize_storyboard_shot_number / dedupe_storyboard_rows_by_number
- is_max_tokens_param_error
- generate_text_for_storyboard
- row_to_scene / normalize_duration
- lighting_style_hint_zh
- build_camera_motion_chain / build_fallback_universal_seedance_line
- get_storyboards_for_episode
- extract_initial_pose / generate_image_prompt / generate_video_prompt
- derive_storyboard_fields_from_ai / update_storyboard_row_from_derived / insert_one_storyboard
- try_incremental_save / save_storyboards
- build_continuation_prompt / process_storyboard_generation / generate_storyboard
- sync_storyboard_characters
- rebuild_video_prompt_for_storyboard
- audio split: copy_storyboard_asset_links, duration_for_split_segment, build_split_plans_from_storyboard,
  persist_split_storyboard_row, update_storyboard_as_split_segment, split_storyboard_by_audio
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one
from app.services import (
    aiClient,
    angleService,
    promptI18n,
    storyboardEntityService,
    taskService,
)
from app.utils import safeJson
from app.utils.dramaStyleMerge import resolved_stream_style_from_drama

log = get_logger("lmd.episodeStoryboardService")

DEFAULT_STORYBOARD_MAX_TOKENS = 16384
_SB_PROMPT_LOG_CHUNK = 14000


def to_int_id(val: Any) -> int:
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return 0


def normalize_storyboard_shot_number(raw_or_sb: Any) -> int:
    """统一镜号（AI 可能返回字符串 "1"，须与 Set 去重键一致）。"""
    if raw_or_sb is not None and isinstance(raw_or_sb, dict):
        raw = raw_or_sb.get("shot_number")
        if raw is None:
            raw = raw_or_sb.get("storyboard_number")
    else:
        raw = raw_or_sb
    try:
        n = float(str(raw).strip())
        if math.isfinite(n) and n > 0:
            return int(math.floor(n))
    except (TypeError, ValueError):
        pass
    return 0


def dedupe_storyboard_rows_by_number(rows: list[dict]) -> list[dict]:
    """同集相同 storyboard_number 多行时保留 id 最大的一条（通常为最新入库）。"""
    by_num: dict[int, dict] = {}
    extras: list[dict] = []
    for r in rows or []:
        num = normalize_storyboard_shot_number(r.get("storyboard_number") if isinstance(r, dict) else r)
        if num > 0:
            prev = by_num.get(num)
            if not prev or int(r.get("id") or 0) > int(prev.get("id") or 0):
                by_num[num] = r
        else:
            extras.append(r)
    merged = list(by_num.values()) + extras
    merged.sort(
        key=lambda x: (
            normalize_storyboard_shot_number(x.get("storyboard_number")),
            int(x.get("id") or 0),
        )
    )
    return merged


def is_max_tokens_param_error(err_msg: str | None) -> bool:
    m = str(err_msg or "").lower()
    return (
        "max_tokens" in m
        or "max_completion_tokens" in m
        or "maximum_context_length" in m
        or "context_length_exceeded" in m
        or "maximum length" in m
        or "token limit" in m
        or ("http 4" in m and ("token" in m or "length" in m or "parameter" in m))
    )


def generate_text_for_storyboard(
    db: Session,
    log_obj,
    user_prompt: str,
    system_prompt: str,
    options: dict[str, Any] | None = None,
) -> str:
    options = options or {}
    model = options.get("model")
    stream_callback = options.get("stream_callback") or options.get("streamCallback")
    temperature = options.get("temperature", 0.7)

    log_obj.info(
        "Storyboard generateText attempt 1",
        extra={"model": model or "(default)", "max_tokens": DEFAULT_STORYBOARD_MAX_TOKENS},
    )
    try:
        text_res = aiClient.generate_text(
            db,
            log_obj,
            "text",
            user_prompt,
            system_prompt,
            {
                "scene_key": "storyboard_extraction",
                "model": model or None,
                "temperature": temperature,
                "max_tokens": DEFAULT_STORYBOARD_MAX_TOKENS,
                "stream_callback": stream_callback,
                "streamCallback": stream_callback,
            },
        )
        return text_res
    except Exception as e:
        if is_max_tokens_param_error(str(e)):
            log_obj.warning(
                "Storyboard generateText: max_tokens rejected by model, retrying without it",
                extra={"model": model or "(default)", "error": str(e)[:200]},
            )
            log_obj.info(
                "Storyboard generateText attempt 2 (no max_tokens)",
                extra={"model": model or "(default)"},
            )
            text_res = aiClient.generate_text(
                db,
                log_obj,
                "text",
                user_prompt,
                system_prompt,
                {
                    "scene_key": "storyboard_extraction",
                    "model": model or None,
                    "temperature": temperature,
                    "stream_callback": stream_callback,
                    "streamCallback": stream_callback,
                },
            )
            log_obj.info("Storyboard generateText attempt 2 succeeded")
            return text_res
        raise


def row_to_scene(r: dict | None) -> dict | None:
    if not r:
        return None
    return {
        "id": r.get("id"),
        "drama_id": r.get("drama_id"),
        "location": r.get("location"),
        "time": r.get("time"),
        "prompt": r.get("prompt"),
        "storyboard_count": r.get("storyboard_count") if r.get("storyboard_count") is not None else 1,
        "image_url": r.get("image_url"),
        "local_path": r.get("local_path"),
        "status": r.get("status") or "pending",
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def normalize_duration(v: Any) -> int:
    """规范为数字秒：前端左侧用 {{ shot.duration }}s，右侧用 Math.round(duration)；避免 '5s' 导致 5ss。"""
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(round(v)) if math.isfinite(v) and v >= 0 else 0
    s = str(v).strip()
    if s.lower().endswith("s"):
        s = s[:-1]
    try:
        n = float(s)
        return int(round(n)) if math.isfinite(n) and n >= 0 else 0
    except (TypeError, ValueError):
        return 0


def log_debug_storyboard_prompts(log_obj, tag: str, user_prompt: str, system_prompt: str) -> None:
    on = str(os.environ.get("DEBUG_STORYBOARD_PROMPTS", "")).strip().lower()
    if on not in ("1", "true"):
        return
    sp = str(system_prompt or "")
    up = str(user_prompt or "")
    log_obj.info(f"[StoryboardPrompt:{tag}] system_prompt_bytes={len(sp)} user_prompt_bytes={len(up)}")
    for i in range(0, len(sp), _SB_PROMPT_LOG_CHUNK):
        log_obj.info(f"[StoryboardPrompt:{tag}] system_part_{i // _SB_PROMPT_LOG_CHUNK + 1}\n{sp[i:i + _SB_PROMPT_LOG_CHUNK]}")
    for i in range(0, len(up), _SB_PROMPT_LOG_CHUNK):
        log_obj.info(f"[StoryboardPrompt:{tag}] user_part_{i // _SB_PROMPT_LOG_CHUNK + 1}\n{up[i:i + _SB_PROMPT_LOG_CHUNK]}")


def lighting_style_hint_zh(code: str | None) -> str:
    m = {
        "natural": "自然窗光或环境散射光",
        "front": "正面柔光面部受光均匀",
        "side": "侧光约45°勾勒轮廓",
        "backlit": "逆光轮廓光发丝边缘发亮",
        "top": "顶光压暗眼窝",
        "under": "底光或脚光非常规氛围",
        "soft": "软光低反差过渡柔和",
        "dramatic": "戏剧高反差主辅分明",
        "golden_hour": "金色时刻暖斜阳",
        "blue_hour": "蓝调时刻冷环境光",
        "night": "夜景人工点光源",
        "neon": "霓虹混合色温",
    }
    return m.get(str(code or "").strip(), "主光方向明确侧光或窗光")


def build_camera_motion_chain(movement: str | None, shot_type: str | None, duration_sec: int | float) -> str:
    dur = max(1, int(duration_sec) if duration_sec else 5)
    mv = str(movement or "").strip()
    st = str(shot_type or "").strip()
    parts = []
    if dur >= 12:
        parts.append("定镜约1秒建立空间")
        if re.search(r"跟|追随|尾随", mv):
            parts.append("侧后方跟拍主体位移")
        elif "摇" in mv:
            parts.append(f"{mv or '轻摇'}拓展画幅信息")
        else:
            parts.append("缓推轨贴近动作核心")
        parts.append("横移从前景遮挡或门框一侧滑出拓宽视野带出纵深与环境细节")
    elif dur >= 8:
        parts.append("定镜")
        parts.append(mv if (mv and not re.search(r"^固定|^定镜", mv)) else "缓推轨由远及近")
        parts.append("微横移或轻摇让背景纵深与环境细节可读")
    elif dur >= 5:
        parts.append("定镜起幅")
        parts.append(mv or "缓推轨或短跟拍强化动线")
    else:
        parts.append(mv or "短跟拍或微推")

    if ("远" in st or "全景" in st) and not any(re.search(r"推|移|跟|摇", p) for p in parts):
        parts.append("缓推轨向事件中心")

    # 去重保留顺序
    seen = set()
    deduped = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            deduped.append(p)
    chain = "，".join(deduped)
    return chain or "定镜，缓推轨"


def build_fallback_universal_seedance_line(sb: dict, d: dict, style_hint: str | None) -> str:
    act = re.sub(r"\s+", " ", str(d.get("action") or "")).strip()[:220]
    res = re.sub(r"\s+", " ", str(d.get("result") or "")).strip()[:120]
    emo = re.sub(r"\s+", " ", str(d.get("emotion") or sb.get("emotion") or "")).strip()[:24]
    atm = re.sub(r"\s+", " ", str(sb.get("atmosphere") or "")).strip()[:100]
    shot_bits = "，".join([p for p in [d.get("shotType"), d.get("angle")] if p]).strip()
    loc = "，".join([p for p in [sb.get("location"), sb.get("time")] if p]).strip() or "叙事空间"
    dur = max(1, int(d.get("durationSec") or normalize_duration(sb.get("duration")) or 5))
    light_zh = lighting_style_hint_zh(d.get("lightingStyle"))
    dof_map = {
        "extreme_shallow": "浅景深前景虚化明显",
        "shallow": "浅景深背景柔化",
        "deep": "深焦前后景均清晰",
        "medium": "景深适中",
    }
    dof = dof_map.get(d.get("depthOfField"), "景深随景别可感")
    shot_num = max(1, int(d.get("shotNumber") or 1))
    link = "开篇情绪奠基" if shot_num <= 1 else "延续上一镜动势与视线"
    motion_core = (
        act
        or "在镜内时长里完成一段可感知的动作阶段变化，含走位或身体重心的转移，避免单姿势摆拍"
    )
    emo_paren = f"（{emo}）" if emo else "（专注投入）"
    fg = f"{atm[:42]}与主体相关的虚化层次" if atm else "与动作相关的近景细节或桌面器物"
    mg = "主体动作与表情核心区" if act else "主体占据画面叙事中心"
    bg = f"{loc}的环境延展与氛围层次" if loc else "环境纵深与空间气氛"
    light_block = f"[{light_zh}；结合{loc}，建议色温具象化如4500K-5600K区间择一；明暗比约2:1至3:1；{dof}]"
    cam_chain = build_camera_motion_chain(d.get("movement"), d.get("shotType"), dur)
    narr_dyn = (
        f"约{dur}秒内——在{loc}，@人物1{f'先后：{act}' if act else '持续推进戏内动作'}，"
        f"{f'阶段收束为：{res}' if res else '动作与视线随时间有阶段推进'}；"
        f"镜头以「{cam_chain}」配合人物动线，读出空间纵深与时间流逝"
    )
    lens_block = (
        f"运镜链：{cam_chain}；景别机位：{shot_bits or '中景，平视'}，"
        f"三分法或对角线择一（结尾动势：[{res or '视线或身体动线指向下一个节拍，动势渐收可衔接下镜'}]）"
    )
    sfx = f"环境层-[与{loc}一致的环境声底与远处细节] 动作层-[与动作同步的物理接触声] 情绪层-[无旋律仅以空间混响与材质细微声烘托情绪张力]"
    style_tail = (str(style_hint).strip() if style_hint else "") or "电影感叙事光色"
    dia = str(d.get("dialogue") or "").strip().replace('"', "'")
    line = (
        f"主体：@人物1{emo_paren}[朝向：依轴线面向戏中对象或画左/画右择一并保持统一] 正在 {motion_core}（与上镜衔接：{link}） "
        f"叙事动态：{narr_dyn} 空间：前景-[{fg}] 中景-[{mg}] 背景-[{bg}] 光影：{light_block} 镜头：{lens_block}"
    )
    if dia:
        line += f' 台词：第1秒 @人物1："{dia[:120]}"'
    line += f" 音效：{sfx} {style_tail} [禁BGM][禁字幕]"
    return re.sub(r"\r?\n", " ", line)


def get_storyboards_for_episode(db: Session, episode_id: Any) -> list[dict]:
    return storyboardEntityService.get_storyboards_for_episode(db, episode_id)


def extract_initial_pose(action: Any) -> str:
    if not action or not isinstance(action, str):
        return ""
    process_words = [
        "然后", "接着", "接下来", "随后", "紧接着",
        "向下", "向上", "向前", "向后", "向左", "向右",
        "开始", "继续", "逐渐", "慢慢", "快速", "突然", "猛然",
    ]
    result = action
    for word in process_words:
        idx = result.find(word)
        if idx > 0:
            result = result[:idx]
            break
    return re.sub(r"[，。,.]\s*$", "", result).strip()


def generate_image_prompt(sb: dict, style: str | None) -> str:
    parts = []
    # 场景位置与时间
    if sb.get("location"):
        location_desc = str(sb["location"])
        if sb.get("time"):
            location_desc += "，" + str(sb["time"])
        parts.append(location_desc)

    # 镜头视角：优先结构化三元组（中文标签），降级到旧文本
    if sb.get("angle_h") and sb.get("angle_v") and sb.get("angle_s"):
        parts.append(angleService.to_chinese_label(sb["angle_h"], sb["angle_v"], sb["angle_s"]))
    elif sb.get("angle") or sb.get("shot_type"):
        parsed = angleService.parse_from_legacy_text(sb.get("angle") or "", sb.get("shot_type") or "")
        parts.append(angleService.to_chinese_label(parsed["h"], parsed["v"], parsed["s"]))

    # 画面动作（取动作的起始状态）
    if sb.get("action"):
        initial_pose = extract_initial_pose(sb["action"])
        if initial_pose:
            parts.append(initial_pose)

    # 情绪
    if sb.get("emotion"):
        parts.append(str(sb["emotion"]))

    # 风格
    style_text = str(style).strip() if style else ""
    if style_text:
        parts.append(style_text)
    parts.append("首帧静止画面")
    return "，".join(parts)


def generate_video_prompt(sb: dict, style: str | None, video_ratio: str | None) -> str:
    parts = []
    # 场景与标题
    if sb.get("scene_description"):
        parts.append("场景：" + str(sb["scene_description"]))
    elif sb.get("location"):
        scene = f"{sb['location']}，{sb['time']}" if sb.get("time") else str(sb["location"])
        parts.append("场景：" + scene)

    if sb.get("title"):
        parts.append("镜头标题：" + str(sb["title"]))

    # 动作与对白（核心叙事）
    if sb.get("action"):
        parts.append("动作：" + str(sb["action"]))
    if sb.get("dialogue"):
        parts.append("对话：" + str(sb["dialogue"]))
    if sb.get("narration"):
        parts.append("解说旁白：" + str(sb["narration"]))
    if sb.get("result"):
        parts.append("结果：" + str(sb["result"]))

    # 镜头与运镜
    shot_type = sb.get("shot_type") or sb.get("camera_shot_type")
    if shot_type:
        parts.append("景别：" + str(shot_type))

    # 结构化视角：中文标签 + 英文描述（兼顾中英文视频模型）
    if sb.get("angle_h") and sb.get("angle_v") and sb.get("angle_s"):
        ch_label = angleService.to_chinese_label(sb["angle_h"], sb["angle_v"], sb["angle_s"])
        angle_frag = angleService.to_prompt_fragment(sb["angle_h"], sb["angle_v"], sb["angle_s"])
        parts.append(f"镜头角度：{ch_label}（{angle_frag}）")
    else:
        angle = sb.get("angle") or sb.get("camera_angle")
        if angle:
            parts.append("镜头角度：" + str(angle))

    movement = sb.get("movement") or sb.get("camera_movement")
    if movement:
        parts.append("运镜：" + str(movement))

    # 氛围与情绪
    if sb.get("atmosphere"):
        parts.append("氛围：" + str(sb["atmosphere"]))
    if sb.get("emotion"):
        parts.append("情绪：" + str(sb["emotion"]))
    if sb.get("emotion_intensity") is not None and sb.get("emotion_intensity") != "":
        parts.append("情绪强度：" + str(sb["emotion_intensity"]))

    # 声音
    if sb.get("bgm_prompt"):
        parts.append("配乐：" + str(sb["bgm_prompt"]))
    if sb.get("sound_effect"):
        parts.append("音效：" + str(sb["sound_effect"]))

    # 时长
    duration_sec = normalize_duration(sb.get("duration")) or 5
    parts.append(f"时长：{duration_sec}秒")

    # 风格与画面比例
    if style:
        parts.append("风格：" + str(style))
    if video_ratio:
        parts.append("=VideoRatio: " + str(video_ratio))

    return "。".join(parts) if parts else "视频场景"


def derive_storyboard_fields_from_ai(sb: dict, style: str | None, video_ratio: str | None, opts: dict | None = None) -> dict:
    opts = opts or {}
    universal_omni = bool(opts.get("universalOmni"))
    shot_number = normalize_storyboard_shot_number(sb)
    title = str(sb.get("title") or "")
    shot_type = str(sb.get("shot_type") or "")
    movement = str(sb.get("movement") or sb.get("camera_movement") or "")
    angle = sb.get("angle") or sb.get("camera_angle")
    action = str(sb.get("action") or "")
    dialogue = str(sb.get("dialogue") or "")
    narration = str(sb.get("narration") or "")
    result = str(sb.get("result") or "")
    emotion = str(sb.get("emotion") or "")
    segment_index = int(sb.get("segment_index")) if sb.get("segment_index") is not None else 0
    segment_title = sb.get("segment_title")
    lighting_style = sb.get("lighting_style")
    depth_of_field = sb.get("depth_of_field")

    duration_sec = normalize_duration(sb.get("duration")) or 5
    target_clip = opts.get("targetClipDuration")
    if target_clip is not None and isinstance(target_clip, (int, float)) and target_clip > 0:
        duration_sec = max(duration_sec, int(round(target_clip)))
    duration_sec = min(120, max(1, int(round(duration_sec))))
    sb["duration"] = duration_sec

    if not sb.get("location") and sb.get("scene_description"):
        scene_desc = str(sb["scene_description"]).strip()
        sep_m = re.search(r"[，,、]", scene_desc)
        if sep_m:
            idx = sep_m.start()
            sb["location"] = scene_desc[:idx].strip()
            if not sb.get("time"):
                sb["time"] = scene_desc[idx + 1:].strip()
        else:
            sb["location"] = scene_desc

    angle_h, angle_v, angle_s = None, None, None
    if angle or shot_type:
        parsed = angleService.parse_from_legacy_text(angle or "", shot_type or "")
        angle_h, angle_v, angle_s = parsed["h"], parsed["v"], parsed["s"]

    description = (
        f"【镜头类型】{shot_type}\n"
        f"【运镜】{movement}\n"
        f"【动作】{action}\n"
        f"【对话】{dialogue}\n"
        f"【解说】{narration}\n"
        f"【结果】{result}\n"
        f"【情绪】{emotion}"
    )
    sb_with_angles = dict(sb)
    sb_with_angles.update({"angle_h": angle_h, "angle_v": angle_v, "angle_s": angle_s})
    image_prompt = generate_image_prompt(sb_with_angles, style)
    video_prompt = generate_video_prompt(sb_with_angles, style, video_ratio)
    scene_id = int(sb["scene_id"]) if sb.get("scene_id") is not None else None

    raw_chars = sb.get("characters")
    if isinstance(raw_chars, list):
        characters_json = json.dumps(raw_chars, ensure_ascii=False)
    elif raw_chars:
        characters_json = json.dumps([raw_chars], ensure_ascii=False)
    else:
        characters_json = "[]"

    prop_ids = []
    if isinstance(sb.get("props"), list):
        for p in sb["props"]:
            try:
                prop_ids.append(int(p))
            except (TypeError, ValueError):
                pass

    universal_segment_text = None
    if sb.get("universal_segment_text") is not None and str(sb["universal_segment_text"]).strip():
        universal_segment_text = re.sub(r"\r?\n", " ", str(sb["universal_segment_text"]).strip())

    if universal_omni and not universal_segment_text:
        universal_segment_text = build_fallback_universal_seedance_line(
            sb,
            {
                "shotNumber": shot_number,
                "durationSec": duration_sec,
                "shotType": shot_type,
                "movement": movement,
                "angle": angle,
                "action": action,
                "dialogue": dialogue,
                "result": result,
                "emotion": emotion,
                "lightingStyle": lighting_style,
                "depthOfField": depth_of_field,
            },
            style,
        )

    creation_mode = "universal" if universal_omni else "classic"
    if not universal_omni:
        universal_segment_text = None

    return {
        "shotNumber": shot_number,
        "title": title,
        "shotType": shot_type,
        "movement": movement,
        "angle": angle,
        "action": action,
        "dialogue": dialogue,
        "narration": narration,
        "result": result,
        "emotion": emotion,
        "segmentIndex": segment_index,
        "segmentTitle": segment_title,
        "lightingStyle": lighting_style,
        "depthOfField": depth_of_field,
        "description": description,
        "imagePrompt": image_prompt,
        "videoPrompt": video_prompt,
        "sceneId": scene_id,
        "charactersJson": characters_json,
        "angleH": angle_h,
        "angleV": angle_v,
        "angleS": angle_s,
        "propIds": prop_ids,
        "creationMode": creation_mode,
        "universalSegmentText": universal_segment_text,
    }


def _get_last_inserted_id(db: Session, exec_res: Any = None) -> int | None:
    lid = getattr(exec_res, "lastrowid", None)
    if lid:
        return int(lid)
    dialect_name = getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", "")
    sql = "SELECT last_insert_rowid() as id" if dialect_name == "sqlite" else "SELECT LAST_INSERT_ID() as id"
    try:
        row = fetch_one(db, sql)
        return int(row["id"]) if row and row.get("id") else None
    except Exception:
        return None


def _insert_ignore_storyboard_prop(db: Session, storyboard_id: int, prop_id: int) -> None:
    dialect_name = getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", "")
    verb = "INSERT OR IGNORE" if dialect_name == "sqlite" else "INSERT IGNORE"
    execute(
        db,
        f"{verb} INTO storyboard_props (storyboard_id, prop_id) VALUES (:sid, :pid)",
        {"sid": storyboard_id, "pid": prop_id},
    )


def _insert_ignore_storyboard_character(db: Session, storyboard_id: int, character_id: int, now_val: str) -> None:
    dialect_name = getattr(getattr(getattr(db, "bind", None), "dialect", None), "name", "")
    verb = "INSERT OR IGNORE" if dialect_name == "sqlite" else "INSERT IGNORE"
    execute(
        db,
        f"{verb} INTO storyboard_characters (storyboard_id, character_id, created_at) VALUES (:sid, :cid, :now)",
        {"sid": storyboard_id, "cid": character_id, "now": now_val},
    )


def update_storyboard_row_from_derived(
    db: Session,
    existing_id: int,
    episode_id_num: int,
    d: dict,
    sb: dict,
    now: str,
) -> None:
    execute(
        db,
        """UPDATE storyboards SET
            scene_id = :scene_id, title = :title, description = :description, location = :location,
            time = :time, duration = :duration, dialogue = :dialogue, narration = :narration,
            action = :action, result = :result, atmosphere = :atmosphere,
            image_prompt = :image_prompt, video_prompt = :video_prompt, characters = :characters,
            shot_type = :shot_type, angle = :angle, angle_h = :angle_h, angle_v = :angle_v,
            angle_s = :angle_s, movement = :movement, lighting_style = :lighting_style,
            depth_of_field = :depth_of_field, segment_index = :segment_index,
            segment_title = :segment_title, creation_mode = :creation_mode,
            universal_segment_text = :universal_segment_text, updated_at = :updated_at
        WHERE id = :id AND episode_id = :episode_id AND deleted_at IS NULL""",
        {
            "scene_id": d["sceneId"],
            "title": d["title"] or None,
            "description": d["description"],
            "location": sb.get("location") or None,
            "time": sb.get("time") or None,
            "duration": sb.get("duration") or 5,
            "dialogue": d["dialogue"] or None,
            "narration": d["narration"] or None,
            "action": d["action"] or None,
            "result": d["result"] or None,
            "atmosphere": sb.get("atmosphere") or None,
            "image_prompt": d["imagePrompt"],
            "video_prompt": d["videoPrompt"],
            "characters": d["charactersJson"],
            "shot_type": d["shotType"] or None,
            "angle": d["angle"],
            "angle_h": d["angleH"],
            "angle_v": d["angleV"],
            "angle_s": d["angleS"],
            "movement": d["movement"] or None,
            "lighting_style": d["lightingStyle"],
            "depth_of_field": d["depthOfField"],
            "segment_index": d["segmentIndex"],
            "segment_title": d["segmentTitle"],
            "creation_mode": d["creationMode"] or "classic",
            "universal_segment_text": d["universalSegmentText"],
            "updated_at": now,
            "id": existing_id,
            "episode_id": episode_id_num,
        },
    )
    try:
        execute(db, "DELETE FROM storyboard_props WHERE storyboard_id = :id", {"id": existing_id})
        for pid in d["propIds"]:
            _insert_ignore_storyboard_prop(db, existing_id, pid)
    except Exception:
        pass


def insert_one_storyboard(
    db: Session,
    episode_id_num: int,
    sb: dict,
    style: str | None,
    video_ratio: str | None,
    now: str,
    derive_opts: dict | None = None,
) -> int | None:
    d = derive_storyboard_fields_from_ai(sb, style, video_ratio, derive_opts)
    shot_number = d["shotNumber"]
    try:
        res = execute(
            db,
            """INSERT INTO storyboards (
                episode_id, scene_id, storyboard_number, title, description, location, time,
                duration, dialogue, narration, action, result, atmosphere, image_prompt,
                video_prompt, characters, shot_type, angle, angle_h, angle_v, angle_s,
                movement, lighting_style, depth_of_field, segment_index, segment_title,
                creation_mode, universal_segment_text, status, created_at, updated_at
            ) VALUES (
                :episode_id, :scene_id, :storyboard_number, :title, :description, :location, :time,
                :duration, :dialogue, :narration, :action, :result, :atmosphere, :image_prompt,
                :video_prompt, :characters, :shot_type, :angle, :angle_h, :angle_v, :angle_s,
                :movement, :lighting_style, :depth_of_field, :segment_index, :segment_title,
                :creation_mode, :universal_segment_text, 'pending', :created_at, :updated_at
            )""",
            {
                "episode_id": episode_id_num,
                "scene_id": d["sceneId"],
                "storyboard_number": shot_number,
                "title": d["title"] or None,
                "description": d["description"],
                "location": sb.get("location") or None,
                "time": sb.get("time") or None,
                "duration": sb.get("duration") or 5,
                "dialogue": d["dialogue"] or None,
                "narration": d["narration"] or None,
                "action": d["action"] or None,
                "result": d["result"] or None,
                "atmosphere": sb.get("atmosphere") or None,
                "image_prompt": d["imagePrompt"],
                "video_prompt": d["videoPrompt"],
                "characters": d["charactersJson"],
                "shot_type": d["shotType"] or None,
                "angle": d["angle"],
                "angle_h": d["angleH"],
                "angle_v": d["angleV"],
                "angle_s": d["angleS"],
                "movement": d["movement"] or None,
                "lighting_style": d["lightingStyle"],
                "depth_of_field": d["depthOfField"],
                "segment_index": d["segmentIndex"],
                "segment_title": d["segmentTitle"],
                "creation_mode": d["creationMode"] or "classic",
                "universal_segment_text": d["universalSegmentText"],
                "created_at": now,
                "updated_at": now,
            },
        )
        new_id = _get_last_inserted_id(db, res)
        if new_id and d["propIds"]:
            try:
                for pid in d["propIds"]:
                    _insert_ignore_storyboard_prop(db, new_id, pid)
            except Exception:
                pass
        db.commit()
        return new_id
    except Exception:
        db.rollback()
        return None


def try_incremental_save(
    db: Session,
    log_obj,
    episode_id_num: int,
    accumulated: str,
    saved_nums: set[int],
    style: str | None,
    video_ratio: str | None,
    derive_opts: dict | None = None,
) -> None:
    try:
        cleaned = (
            accumulated.strip()
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        cleaned = safeJson.escape_newlines_in_strings(cleaned)
        candidate = safeJson.extract_json_candidate(cleaned)
        if not candidate:
            return

        inner_array = safeJson.extract_wrapped_array_str(candidate)
        array_candidate = inner_array or candidate

        parsed = None
        repaired = safeJson.repair_truncated_json_array(array_candidate)
        if repaired:
            try:
                parsed = json.loads(repaired)
            except Exception:
                pass
            if not parsed and getattr(safeJson, "_jsonrepair", None):
                try:
                    parsed = json.loads(safeJson._jsonrepair(repaired))
                except Exception:
                    pass

        if not parsed and getattr(safeJson, "_jsonrepair", None):
            try:
                parsed = json.loads(safeJson._jsonrepair(array_candidate))
            except Exception:
                pass

        if not parsed:
            return
        items = parsed if isinstance(parsed, list) else safeJson.extract_first_array(parsed)
        if not items:
            return

        now = timestamp()
        new_count = 0
        for sb in items:
            shot_number = normalize_storyboard_shot_number(sb)
            if shot_number > 0 and shot_number in saved_nums:
                continue
            new_id = insert_one_storyboard(db, episode_id_num, sb, style, video_ratio, now, derive_opts)
            if new_id is not None:
                saved_nums.add(shot_number)
                new_count += 1

        if new_count > 0:
            log_obj.info(
                "Storyboard incremental save",
                extra={"episode_id": episode_id_num, "new_count": new_count, "total_saved": len(saved_nums)},
            )
    except Exception:
        pass


def save_storyboards(
    db: Session,
    log_obj,
    episode_id: Any,
    storyboards: list[dict],
    cfg: dict | None,
    style_override: str | None = None,
    skip_shot_numbers: set[int] | None = None,
    derive_opts: dict | None = None,
) -> list[dict]:
    episode_id_num = to_int_id(episode_id)
    if not storyboards:
        raise ValueError("AI生成分镜失败：返回的分镜数量为0")

    style = (str(style_override).strip() if style_override else "") or (
        (cfg.get("style", {}) if isinstance(cfg, dict) else {}).get("default_style") or ""
    )
    video_ratio = (
        (cfg.get("style", {}) if isinstance(cfg, dict) else {}).get("default_video_ratio") or "16:9"
    )
    now = timestamp()

    # 仅在非增量模式下才删除旧数据（增量模式时已在流式开始前删除）
    if skip_shot_numbers is None:
        execute(
            db,
            "UPDATE storyboards SET deleted_at = :now WHERE episode_id = :eid AND deleted_at IS NULL",
            {"now": now, "eid": episode_id_num},
        )
        db.commit()

    saved: list[dict] = []
    processed_in_save: set[int] = set()

    for sb in storyboards:
        shot_number = normalize_storyboard_shot_number(sb)
        if shot_number > 0 and shot_number in processed_in_save:
            log_obj.warning(
                "Duplicate storyboard_number in final AI batch, skipping extra row",
                extra={"episode_id": episode_id_num, "storyboard_number": shot_number},
            )
            continue

        if skip_shot_numbers and shot_number in skip_shot_numbers:
            existing = fetch_one(
                db,
                "SELECT * FROM storyboards WHERE episode_id = :eid AND storyboard_number = :snum AND deleted_at IS NULL",
                {"eid": episode_id_num, "snum": shot_number},
            )
            if existing:
                d = derive_storyboard_fields_from_ai(sb, style, video_ratio, derive_opts)
                update_storyboard_row_from_derived(db, existing["id"], episode_id_num, d, sb, now)
                db.commit()
                log_obj.info(
                    "Storyboard merged from final parse after incremental save",
                    extra={
                        "episode_id": episode_id_num,
                        "storyboard_id": existing["id"],
                        "storyboard_number": shot_number,
                    },
                )
                refreshed = fetch_one(
                    db,
                    "SELECT * FROM storyboards WHERE id = :id AND deleted_at IS NULL",
                    {"id": existing["id"]},
                )
                prop_ids = []
                try:
                    prop_links = fetch_all(
                        db,
                        "SELECT prop_id FROM storyboard_props WHERE storyboard_id = :sid",
                        {"sid": refreshed["id"]},
                    )
                    prop_ids = [p["prop_id"] for p in prop_links]
                except Exception:
                    pass

                chars_list = []
                try:
                    chars_list = json.loads(refreshed.get("characters") or "[]")
                except Exception:
                    pass

                saved.append({
                    "id": refreshed["id"],
                    "episode_id": episode_id_num,
                    "scene_id": refreshed["scene_id"],
                    "storyboard_number": shot_number,
                    "title": refreshed["title"],
                    "description": refreshed["description"],
                    "location": refreshed["location"],
                    "time": refreshed["time"],
                    "duration": refreshed["duration"],
                    "dialogue": refreshed["dialogue"],
                    "narration": refreshed.get("narration"),
                    "action": refreshed["action"],
                    "result": refreshed["result"],
                    "atmosphere": refreshed["atmosphere"],
                    "image_prompt": refreshed["image_prompt"],
                    "video_prompt": refreshed["video_prompt"],
                    "shot_type": refreshed["shot_type"],
                    "angle": refreshed["angle"],
                    "movement": refreshed["movement"],
                    "segment_index": refreshed["segment_index"] if refreshed.get("segment_index") is not None else 0,
                    "segment_title": refreshed.get("segment_title"),
                    "creation_mode": "universal" if refreshed.get("creation_mode") == "universal" else "classic",
                    "universal_segment_text": refreshed.get("universal_segment_text"),
                    "characters": chars_list,
                    "prop_ids": prop_ids,
                    "status": refreshed["status"],
                    "created_at": refreshed["created_at"],
                    "updated_at": refreshed["updated_at"],
                })
                if shot_number > 0:
                    processed_in_save.add(shot_number)
                continue

            if shot_number > 0:
                log_obj.warning(
                    "Incremental shot missing in DB at final save, skipping insert",
                    extra={"episode_id": episode_id_num, "storyboard_number": shot_number},
                )
                continue

        d = derive_storyboard_fields_from_ai(sb, style, video_ratio, derive_opts)
        ins_res = None
        try:
            ins_res = execute(
                db,
                """INSERT INTO storyboards (
                    episode_id, scene_id, storyboard_number, title, description, location, time,
                    duration, dialogue, narration, action, result, atmosphere, image_prompt,
                    video_prompt, characters, shot_type, angle, angle_h, angle_v, angle_s,
                    movement, lighting_style, depth_of_field, segment_index, segment_title,
                    creation_mode, universal_segment_text, status, created_at, updated_at
                ) VALUES (
                    :episode_id, :scene_id, :storyboard_number, :title, :description, :location, :time,
                    :duration, :dialogue, :narration, :action, :result, :atmosphere, :image_prompt,
                    :video_prompt, :characters, :shot_type, :angle, :angle_h, :angle_v, :angle_s,
                    :movement, :lighting_style, :depth_of_field, :segment_index, :segment_title,
                    :creation_mode, :universal_segment_text, 'pending', :created_at, :updated_at
                )""",
                {
                    "episode_id": episode_id_num,
                    "scene_id": d["sceneId"],
                    "storyboard_number": shot_number,
                    "title": d["title"] or None,
                    "description": d["description"],
                    "location": sb.get("location") or None,
                    "time": sb.get("time") or None,
                    "duration": sb.get("duration") or 5,
                    "dialogue": d["dialogue"] or None,
                    "narration": d["narration"] or None,
                    "action": d["action"] or None,
                    "result": d["result"] or None,
                    "atmosphere": sb.get("atmosphere") or None,
                    "image_prompt": d["imagePrompt"],
                    "video_prompt": d["videoPrompt"],
                    "characters": d["charactersJson"],
                    "shot_type": d["shotType"] or None,
                    "angle": d["angle"],
                    "angle_h": d["angleH"],
                    "angle_v": d["angleV"],
                    "angle_s": d["angleS"],
                    "movement": d["movement"] or None,
                    "lighting_style": d["lightingStyle"],
                    "depth_of_field": d["depthOfField"],
                    "segment_index": d["segmentIndex"],
                    "segment_title": d["segmentTitle"],
                    "creation_mode": d["creationMode"] or "classic",
                    "universal_segment_text": d["universalSegmentText"],
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except Exception:
            # 回退少数字段旧表结构
            ins_res = execute(
                db,
                """INSERT INTO storyboards (
                    episode_id, scene_id, storyboard_number, title, description, location, time,
                    duration, dialogue, action, atmosphere, image_prompt, video_prompt,
                    characters, creation_mode, universal_segment_text, status, created_at, updated_at
                ) VALUES (
                    :episode_id, :scene_id, :storyboard_number, :title, :description, :location, :time,
                    :duration, :dialogue, :action, :atmosphere, :image_prompt, :video_prompt,
                    :characters, :creation_mode, :universal_segment_text, 'pending', :created_at, :updated_at
                )""",
                {
                    "episode_id": episode_id_num,
                    "scene_id": d["sceneId"],
                    "storyboard_number": shot_number,
                    "title": d["title"] or None,
                    "description": d["description"],
                    "location": sb.get("location") or None,
                    "time": sb.get("time") or None,
                    "duration": sb.get("duration") or 5,
                    "dialogue": d["dialogue"] or None,
                    "action": d["action"] or None,
                    "atmosphere": sb.get("atmosphere") or None,
                    "image_prompt": d["imagePrompt"],
                    "video_prompt": d["videoPrompt"],
                    "characters": d["charactersJson"],
                    "creation_mode": d["creationMode"] or "classic",
                    "universal_segment_text": d["universalSegmentText"],
                    "created_at": now,
                    "updated_at": now,
                },
            )

        new_id = _get_last_inserted_id(db, ins_res)
        if new_id and d["propIds"]:
            try:
                for pid in d["propIds"]:
                    _insert_ignore_storyboard_prop(db, new_id, pid)
            except Exception:
                pass

        chars_val = sb.get("characters")
        if not isinstance(chars_val, list):
            chars_val = []

        saved.append({
            "id": new_id,
            "episode_id": episode_id_num,
            "scene_id": d["sceneId"],
            "storyboard_number": shot_number,
            "title": d["title"] or None,
            "description": d["description"],
            "location": sb.get("location") or None,
            "time": sb.get("time") or None,
            "duration": sb.get("duration") or 5,
            "dialogue": d["dialogue"] or None,
            "narration": d["narration"] or None,
            "action": d["action"] or None,
            "result": d["result"] or None,
            "atmosphere": sb.get("atmosphere") or None,
            "image_prompt": d["imagePrompt"],
            "video_prompt": d["videoPrompt"],
            "shot_type": d["shotType"] or None,
            "angle": d["angle"],
            "movement": d["movement"] or None,
            "segment_index": d["segmentIndex"],
            "segment_title": d["segmentTitle"],
            "creation_mode": d["creationMode"] or "classic",
            "universal_segment_text": d["universalSegmentText"],
            "characters": chars_val,
            "prop_ids": d["propIds"],
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        })
        if shot_number > 0:
            processed_in_save.add(shot_number)

    db.commit()
    log_obj.info("Storyboards saved", extra={"episode_id": episode_id, "count": len(saved)})
    return saved


def build_continuation_prompt(
    original_user_prompt: str,
    already_saved: list[dict],
    last_shot_num: int,
    attempt: int,
    include_narration: bool,
    universal_omni: bool = False,
) -> str:
    narr_line = (
        "\n- 每条新增分镜必须含非空字符串 narration（至少一句解说，与首次任务一致；禁止留空）"
        if include_narration
        else ""
    )
    uni_line = (
        "\n- 每条新增分镜必须含 creation_mode:\"universal\" 与非空 universal_segment_text（单行：须含「叙事动态」时间线+「镜头」运镜链至少两步如定镜/缓推轨/横移从遮挡后滑出；按 duration 秒写视频动势，禁止静帧式描写；与首轮要求一致）"
        if universal_omni
        else ""
    )

    all_summary_lines = []
    for sb in already_saved:
        s_num = normalize_storyboard_shot_number(sb)
        seg_title = str(sb.get("segment_title") or "")
        sb_title = str(sb.get("title") or "")
        all_summary_lines.append(f"  {s_num}. [{seg_title}] {sb_title}")
    all_summary = "\n".join(all_summary_lines)

    last_ctx_lines = []
    for sb in already_saved[-5:]:
        item = {
            "shot_number": normalize_storyboard_shot_number(sb),
            "title": str(sb.get("title") or ""),
            "location": str(sb.get("location") or ""),
            "action": str(sb.get("action") or "")[:120],
        }
        last_ctx_lines.append("  " + json.dumps(item, ensure_ascii=False))
    last_ctx = ",\n".join(last_ctx_lines)

    return f"""[续写指令 - 第{attempt}次续写]
之前的分镜生成因长度限制在 shot_number {last_shot_num} 处中断，已生成 {len(already_saved)} 个分镜。

━━━ 已生成分镜完整列表（绝对不能重复以下内容）━━━
{all_summary}
━━━ 列表结束 ━━━

以上所有情节均已覆盖，请勿重复。末尾几个分镜详情供衔接参考：
[
{last_ctx}
]

请从 shot_number {last_shot_num + 1} 继续生成剩余分镜，直至剧本全部场景覆盖完毕。
要求：
- 仅返回新增分镜（JSON数组），shot_number 从 {last_shot_num + 1} 开始递增
- 格式与之前完全相同，字段保持一致{narr_line}{uni_line}
- 严禁重复已生成列表中的任何情节或场景
- 不要输出任何解释文字，直接输出 JSON

原始剧本与任务说明：
{original_user_prompt}"""


def process_storyboard_generation(
    db: Session,
    log_obj,
    cfg: dict | None,
    task_id: str,
    episode_id: str,
    model: str | None,
    style: str | None,
    user_prompt: str,
    system_prompt: str,
    include_narration: bool,
    universal_omni: bool,
    target_clip_duration_sec: int | None = None,
) -> None:
    episode_id_num = to_int_id(episode_id)
    stream_saved_nums: set[int] = set()
    stream_style = (str(style).strip() if style else "") or (
        (cfg.get("style", {}) if isinstance(cfg, dict) else {}).get("default_style") or ""
    )
    stream_video_ratio = (
        (cfg.get("style", {}) if isinstance(cfg, dict) else {}).get("default_video_ratio") or "16:9"
    )
    derive_opts = {
        "universalOmni": bool(universal_omni),
        "targetClipDuration": int(target_clip_duration_sec) if target_clip_duration_sec and int(target_clip_duration_sec) > 0 else None,
    }
    state = {"stream_throttle": 0}

    try:
        taskService.update_task_status(db, task_id, "processing", 10, "开始生成分镜头...")
        db.commit()
        log_obj.info("Processing storyboard generation", extra={"task_id": task_id, "episode_id": episode_id})
        log_obj.info(
            "Storyboard prompt preview",
            extra={
                "user_prompt_len": len(user_prompt) if user_prompt else 0,
                "system_prompt_len": len(system_prompt) if system_prompt else 0,
                "user_prompt_head": user_prompt[:200] if user_prompt else "",
            },
        )
        log_debug_storyboard_prompts(log_obj, f"task-{task_id}-initial", user_prompt, system_prompt)

        # 提前删除旧分镜，为增量流式保存腾出位置
        delete_now = timestamp()
        execute(
            db,
            "UPDATE storyboards SET deleted_at = :now WHERE episode_id = :eid AND deleted_at IS NULL",
            {"now": delete_now, "eid": episode_id_num},
        )
        db.commit()

        def _on_stream(accumulated: str) -> None:
            if len(accumulated) - state["stream_throttle"] < 400:
                return
            state["stream_throttle"] = len(accumulated)
            try_incremental_save(
                db,
                log_obj,
                episode_id_num,
                accumulated,
                stream_saved_nums,
                stream_style,
                stream_video_ratio,
                derive_opts,
            )
            if stream_saved_nums:
                taskService.update_task_status(
                    db,
                    task_id,
                    "processing",
                    30,
                    f"已解析 {len(stream_saved_nums)} 个分镜，生成中...",
                )
                db.commit()

        text_res = generate_text_for_storyboard(
            db,
            log_obj,
            user_prompt,
            system_prompt,
            {
                "model": model or None,
                "stream_callback": _on_stream,
            },
        )

        taskService.update_task_status(db, task_id, "processing", 50, "分镜头生成完成，正在解析结果...")
        db.commit()

        log_obj.info(
            "AI raw response received",
            extra={
                "task_id": task_id,
                "text_type": type(text_res).__name__,
                "text_length": len(str(text_res or "")),
                "text_preview": str(text_res or "")[:2000],
            },
        )

        storyboards: list = []
        parse_meta: dict[str, Any] = {}
        try:
            parsed = safeJson.safe_parse_ai_json(text_res, log=log_obj, out_meta=parse_meta)
            storyboards = safeJson.extract_first_array(parsed) or []
        except Exception as e:
            log_obj.error(
                "Parse storyboard JSON failed",
                extra={
                    "error": str(e),
                    "task_id": task_id,
                    "text_length": len(str(text_res or "")),
                    "raw_text": str(text_res or "")[:2000],
                },
            )
            if stream_saved_nums:
                partial_boards = get_storyboards_for_episode(db, episode_id_num)
                if partial_boards:
                    total_dur = sum(int(sb.get("duration") or 0) for sb in partial_boards)
                    log_obj.warning(
                        "Parse failed but partial storyboards already saved incrementally, treating as truncated success",
                        extra={"task_id": task_id, "recovered_count": len(partial_boards), "parse_error": str(e)},
                    )
                    taskService.update_task_result(
                        db,
                        task_id,
                        {
                            "storyboards": partial_boards,
                            "total": len(partial_boards),
                            "total_duration": total_dur,
                            "duration_minutes": math.ceil((total_dur + 59) / 60),
                            "truncated": True,
                            "error_message": f"AI输出含JSON格式缺陷（{str(e)}），已恢复 {len(partial_boards)} 个分镜",
                        },
                    )
                    db.commit()
                    return

            taskService.update_task_error(db, task_id, f"解析分镜头结果失败: {str(e)}")
            db.commit()
            return

        if not storyboards:
            if stream_saved_nums:
                partial_boards = get_storyboards_for_episode(db, episode_id_num)
                if partial_boards:
                    total_dur = sum(int(sb.get("duration") or 0) for sb in partial_boards)
                    log_obj.warning(
                        "Final parse returned 0 items but incremental saves exist, using those",
                        extra={"task_id": task_id, "recovered_count": len(partial_boards)},
                    )
                    taskService.update_task_result(
                        db,
                        task_id,
                        {
                            "storyboards": partial_boards,
                            "total": len(partial_boards),
                            "total_duration": total_dur,
                            "duration_minutes": math.ceil((total_dur + 59) / 60),
                            "truncated": True,
                        },
                    )
                    db.commit()
                    return
            log_obj.error("AI returned 0 storyboards", extra={"task_id": task_id})
            taskService.update_task_error(db, task_id, "AI生成分镜失败：返回的分镜数量为0")
            db.commit()
            return

        if parse_meta.get("truncated"):
            log_obj.warning(
                "Storyboard JSON was truncated by AI (max_tokens limit), will attempt continuation",
                extra={
                    "task_id": task_id,
                    "episode_id": episode_id,
                    "rescued_count": len(storyboards),
                    "raw_text_length": len(str(text_res or "")),
                },
            )

        log_obj.info(
            "Storyboard initial parse",
            extra={
                "task_id": task_id,
                "episode_id": episode_id,
                "count": len(storyboards),
                "truncated": bool(parse_meta.get("truncated")),
            },
        )

        # ── 自动续写：若 AI 输出被截断，最多续写 3 次直到完整 ──────────────────
        max_continuation = 3
        cont_attempt = 0
        while parse_meta.get("truncated") and storyboards and cont_attempt < max_continuation:
            cont_attempt += 1
            last_shot = max(
                (normalize_storyboard_shot_number(s) for s in storyboards),
                default=0,
            )
            log_obj.info(
                "Storyboard continuation start",
                extra={"task_id": task_id, "attempt": cont_attempt, "last_shot": last_shot, "current_count": len(storyboards)},
            )
            taskService.update_task_status(
                db,
                task_id,
                "processing",
                50 + cont_attempt * 5,
                f"已生成 {len(storyboards)} 个分镜，正在续写剩余部分（第{cont_attempt}次）...",
            )
            db.commit()

            cont_prompt = build_continuation_prompt(
                user_prompt,
                storyboards,
                last_shot,
                cont_attempt,
                bool(include_narration),
                bool(universal_omni),
            )
            log_debug_storyboard_prompts(log_obj, f"task-{task_id}-continuation-{cont_attempt}", cont_prompt, system_prompt)
            state["stream_throttle"] = 0

            time.sleep(3)

            try:
                cont_text = generate_text_for_storyboard(
                    db,
                    log_obj,
                    cont_prompt,
                    system_prompt,
                    {
                        "model": model or None,
                        "stream_callback": _on_stream,
                    },
                )
            except Exception as e:
                log_obj.warning("Continuation request failed", extra={"task_id": task_id, "attempt": cont_attempt, "error": str(e)})
                break

            cont_meta: dict[str, Any] = {}
            cont_items = []
            try:
                cont_parsed = safeJson.safe_parse_ai_json(cont_text, log=log_obj, out_meta=cont_meta)
                cont_items = safeJson.extract_first_array(cont_parsed) or []
            except Exception as e:
                log_obj.warning("Continuation parse failed", extra={"task_id": task_id, "attempt": cont_attempt, "error": str(e)})
                break

            if not cont_items:
                log_obj.warning("Continuation returned 0 items", extra={"task_id": task_id, "attempt": cont_attempt})
                break

            existing_nums = {normalize_storyboard_shot_number(s) for s in storyboards}
            new_items = [s for s in cont_items if normalize_storyboard_shot_number(s) not in existing_nums]
            if not new_items:
                log_obj.warning("Continuation returned only duplicate items", extra={"task_id": task_id, "attempt": cont_attempt})
                break

            storyboards = list(storyboards) + list(new_items)
            parse_meta["truncated"] = cont_meta.get("truncated", False)
            log_obj.info(
                "Storyboard continuation done",
                extra={
                    "task_id": task_id,
                    "attempt": cont_attempt,
                    "new_items": len(new_items),
                    "total_count": len(storyboards),
                    "still_truncated": bool(parse_meta.get("truncated")),
                },
            )

        total_duration = sum(int(sb.get("duration") or 0) for sb in storyboards)
        if parse_meta.get("truncated"):
            log_obj.warning(
                "Storyboard still truncated after max continuations",
                extra={
                    "task_id": task_id,
                    "final_count": len(storyboards),
                    "continuation_attempts": cont_attempt,
                },
            )
        log_obj.info(
            "Storyboard generated",
            extra={
                "task_id": task_id,
                "episode_id": episode_id,
                "count": len(storyboards),
                "total_duration_seconds": total_duration,
                "truncated": bool(parse_meta.get("truncated")),
                "continuation_attempts": cont_attempt,
            },
        )

        taskService.update_task_status(db, task_id, "processing", 70, "正在保存分镜头...")
        db.commit()

        saved = save_storyboards(
            db,
            log_obj,
            episode_id,
            storyboards,
            cfg,
            style,
            stream_saved_nums,
            derive_opts,
        )

        # ── 分镜角色补全 ──────────────────────────────────
        taskService.update_task_status(db, task_id, "processing", 75, "正在校验分镜角色关联...")
        db.commit()
        total_char_added = 0
        for sb in saved:
            if not sb.get("id"):
                continue
            res = sync_storyboard_characters(db, log_obj, sb["id"])
            total_char_added += len(res.get("added") or [])

        if total_char_added > 0:
            log_obj.info("[分镜] 角色补全完成", extra={"episode_id": episode_id, "total_added": total_char_added})

        taskService.update_task_status(db, task_id, "processing", 90, "正在更新剧集时长...")
        db.commit()

        duration_minutes = math.ceil((total_duration + 59) / 60)
        execute(
            db,
            "UPDATE episodes SET duration = :dur, updated_at = :now WHERE id = :id",
            {"dur": duration_minutes, "now": timestamp(), "id": episode_id_num},
        )
        db.commit()
        log_obj.info(
            "Episode duration updated",
            extra={"episode_id": episode_id, "duration_seconds": total_duration, "duration_minutes": duration_minutes},
        )

        result_data = {
            "storyboards": saved,
            "total": len(saved),
            "total_duration": total_duration,
            "duration_minutes": duration_minutes,
            "truncated": bool(parse_meta.get("truncated")),
        }
        taskService.update_task_result(db, task_id, result_data)
        db.commit()
        log_obj.info("Storyboard generation completed", extra={"task_id": task_id, "episode_id": episode_id})
    except Exception as err:
        log_obj.error("Storyboard generation failed", extra={"error": str(err), "task_id": task_id})
        if stream_saved_nums:
            try:
                partial_boards = get_storyboards_for_episode(db, episode_id_num)
                if partial_boards:
                    total_dur = sum(int(sb.get("duration") or 0) for sb in partial_boards)
                    log_obj.warning(
                        "Partial storyboards recovered after error, treating as truncated success",
                        extra={"task_id": task_id, "recovered_count": len(partial_boards), "error": str(err)},
                    )
                    taskService.update_task_result(
                        db,
                        task_id,
                        {
                            "storyboards": partial_boards,
                            "total": len(partial_boards),
                            "total_duration": total_dur,
                            "duration_minutes": math.ceil((total_dur + 59) / 60),
                            "truncated": True,
                            "error_message": f"连接中断（{str(err)}），已恢复 {len(partial_boards)} 个分镜",
                        },
                    )
                    db.commit()
                    return
            except Exception:
                pass

        taskService.update_task_error(db, task_id, str(err) or "生成分镜头失败")
        db.commit()


def sync_storyboard_characters(db: Session, log_obj, storyboard_id: Any) -> dict[str, list[str]]:
    """与 backend-node/src/services/imageService.js::syncStoryboardCharacters 严格一致。"""
    added = []
    sb_id = to_int_id(storyboard_id)
    if not sb_id:
        return {"added": added}
    try:
        sb = fetch_one(
            db,
            "SELECT id, episode_id, characters, action, dialogue, result, description FROM storyboards WHERE id = :id AND deleted_at IS NULL",
            {"id": sb_id},
        )
        if not sb:
            return {"added": added}

        ep = fetch_one(
            db,
            "SELECT drama_id FROM episodes WHERE id = :id AND deleted_at IS NULL",
            {"id": sb["episode_id"]},
        )
        drama_id = ep.get("drama_id") if ep else None
        if not drama_id:
            return {"added": added}

        scan_parts = [
            str(sb.get("action") or ""),
            str(sb.get("dialogue") or ""),
            str(sb.get("result") or ""),
            str(sb.get("description") or ""),
        ]
        scan_text = " ".join([p for p in scan_parts if p]).lower()
        if not scan_text:
            return {"added": added}

        char_list = []
        raw_chars = sb.get("characters")
        if raw_chars:
            try:
                char_list = json.loads(raw_chars) if isinstance(raw_chars, str) else raw_chars
                if not isinstance(char_list, list):
                    char_list = []
            except Exception:
                char_list = []

        covered_ids = set()
        for c in char_list:
            cid = c.get("id") if isinstance(c, dict) else c
            try:
                covered_ids.add(int(cid))
            except (TypeError, ValueError):
                pass

        all_chars = fetch_all(
            db,
            "SELECT id, name FROM characters WHERE drama_id = :did AND deleted_at IS NULL",
            {"did": int(drama_id)},
        )
        updated = False
        for ch in all_chars:
            ch_name = (ch.get("name") or "").strip()
            if not ch_name:
                continue
            if ch["id"] in covered_ids:
                continue
            if ch_name.lower() not in scan_text:
                continue
            char_list.append({"id": ch["id"], "name": ch_name})
            covered_ids.add(ch["id"])
            added.append(ch_name)
            updated = True

        if updated:
            execute(
                db,
                "UPDATE storyboards SET characters = :chars, updated_at = :now WHERE id = :id AND deleted_at IS NULL",
                {"chars": json.dumps(char_list, ensure_ascii=False), "now": timestamp(), "id": sb_id},
            )
            db.commit()
            if log_obj:
                log_obj.info("[分镜角色补全] 补全完成", extra={"storyboard_id": sb_id, "added": added})
    except Exception as err:
        if log_obj:
            log_obj.warning("[分镜角色补全] 异常", extra={"storyboard_id": sb_id, "error": str(err)})
    return {"added": added}


def generate_storyboard(
    db: Session,
    log_obj,
    episode_id: Any,
    model: str | None = None,
    style: str | None = None,
    storyboard_count: Any = None,
    video_duration: Any = None,
    aspect_ratio: str | None = None,
    include_narration: Any = None,
    universal_omni: Any = None,
    *,
    _existing_task_id: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    ep_id_num = to_int_id(episode_id)
    episode = fetch_one(
        db,
        "SELECT id, script_content, description, drama_id FROM episodes WHERE id = :id AND deleted_at IS NULL",
        {"id": ep_id_num},
    )
    if not episode:
        raise ValueError("剧集不存在或无权限访问")

    drama = fetch_one(
        db,
        "SELECT style, metadata FROM dramas WHERE id = :id",
        {"id": episode["drama_id"]},
    )
    final_style = resolved_stream_style_from_drama(style, drama)

    drama_aspect_ratio = None
    video_clip_duration = None
    if drama and drama.get("metadata"):
        try:
            meta = json.loads(drama["metadata"]) if isinstance(drama["metadata"], str) else drama["metadata"]
            if meta and meta.get("aspect_ratio"):
                drama_aspect_ratio = meta["aspect_ratio"]
            if meta and meta.get("video_clip_duration"):
                video_clip_duration = float(meta["video_clip_duration"])
        except Exception:
            pass

    image_ratio = (
        aspect_ratio
        or drama_aspect_ratio
        or ((cfg.get("style", {}) if isinstance(cfg, dict) else {}).get("default_video_ratio"))
        or "16:9"
    )

    effective_shot_duration = None
    implied_from_total = None
    if video_duration and storyboard_count:
        try:
            vd = float(video_duration)
            sc = float(storyboard_count)
            if sc > 0:
                implied_from_total = int(round(vd / sc))
        except (TypeError, ValueError):
            pass

    if video_clip_duration and video_clip_duration > 0:
        effective_shot_duration = int(video_clip_duration)
    elif implied_from_total and implied_from_total > 0:
        effective_shot_duration = implied_from_total
    else:
        effective_shot_duration = None

    script_content = (str(episode.get("script_content") or "").strip()) or (
        str(episode.get("description") or "").strip()
    )
    if not script_content:
        raise ValueError("剧本内容为空，请先生成剧集内容")

    characters = fetch_all(
        db,
        "SELECT id, name FROM characters WHERE drama_id = :did AND deleted_at IS NULL ORDER BY name ASC",
        {"did": episode["drama_id"]},
    )
    character_list = "无角色"
    if characters:
        character_list = json.dumps([
            {"id": c["id"], "name": str(c.get("name") or "")}
            for c in characters
        ], ensure_ascii=False)

    scenes = fetch_all(
        db,
        "SELECT id, location, time FROM scenes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY location ASC, time ASC",
        {"did": episode["drama_id"]},
    )
    scene_list = "无场景"
    if scenes:
        scene_list = json.dumps([
            {"id": s["id"], "location": str(s.get("location") or ""), "time": str(s.get("time") or "")}
            for s in scenes
        ], ensure_ascii=False)

    props = fetch_all(
        db,
        "SELECT id, name, type FROM props WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC",
        {"did": episode["drama_id"]},
    )
    prop_list = "无道具"
    if props:
        prop_items = []
        for p in props:
            item = {"id": p["id"], "name": str(p.get("name") or "")}
            if p.get("type"):
                item["type"] = str(p["type"])
            prop_items.append(item)
        prop_list = json.dumps(prop_items, ensure_ascii=False)

    script_label = promptI18n.format_user_prompt(cfg, "script_content_label")
    task_label = promptI18n.format_user_prompt(cfg, "task_label")
    task_instruction = promptI18n.format_user_prompt(cfg, "task_instruction")

    extra_constraint = ""
    if storyboard_count:
        try:
            count_val = int(storyboard_count)
            if count_val > 0:
                count_label = promptI18n.format_user_prompt(cfg, "storyboard_count_constraint", count_val)
                if count_label:
                    extra_constraint += f"\n{count_label}"
        except (TypeError, ValueError):
            pass

    if video_duration:
        try:
            duration_val = int(video_duration)
            if duration_val > 0:
                duration_label = promptI18n.format_user_prompt(cfg, "video_duration_constraint", duration_val)
                if duration_label:
                    extra_constraint += f"\n{duration_label}"
        except (TypeError, ValueError):
            pass

    if storyboard_count and video_duration and effective_shot_duration:
        is_en = promptI18n.is_english(cfg)
        clip_from_project = video_clip_duration and video_clip_duration > 0
        implied = implied_from_total or int(round(float(video_duration) / float(storyboard_count)))
        if clip_from_project:
            clip = int(video_clip_duration)
            if is_en:
                extra_constraint += f'\nEach shot "duration" field: prioritize **~{clip}s per shot** (project clip-length setting); ±1s OK. Total ~{int(video_duration)}s and ~{int(storyboard_count)} shots are overall planning hints—do NOT force every shot to ~{implied}s (total÷count) when it conflicts with the project clip length.'
            else:
                extra_constraint += f'\n每个镜头的 **duration** 请优先按项目「每段约 **{clip} 秒**」填写（可 ±1 秒微调）。全片总时长约 {int(video_duration)} 秒、镜头数约 {int(storyboard_count)} 为整体规划参考，**禁止**为机械凑「总时长÷镜数」（约 {implied}s）而把每镜普遍写成过短镜头；除非该镜对白与动作为实需的极短镜头。'
        elif is_en:
            extra_constraint += f"\nEach shot target duration: approximately {effective_shot_duration}s (= total {int(video_duration)}s ÷ {int(storyboard_count)} shots). Set each shot's duration field to this value, adjusting ±1s for dialogue/action length."
        else:
            extra_constraint += f"\n每镜头目标时长：约 {effective_shot_duration} 秒（= 总时长 {int(video_duration)}s ÷ {int(storyboard_count)} 个镜头）。每个镜头的 duration 字段请设为此值，可根据对话/动作长短适当调整 ±1 秒。"

    log_obj.info(
        "Storyboard generation params",
        extra={
            "storyboard_count": storyboard_count,
            "video_duration": video_duration,
            "video_clip_duration": video_clip_duration,
            "effective_shot_duration": effective_shot_duration,
        },
    )

    char_list_label = promptI18n.format_user_prompt(cfg, "character_list_label")
    char_constraint = promptI18n.format_user_prompt(cfg, "character_constraint")
    scene_list_label = promptI18n.format_user_prompt(cfg, "scene_list_label")
    scene_constraint = promptI18n.format_user_prompt(cfg, "scene_constraint")
    prop_list_label = promptI18n.format_user_prompt(cfg, "prop_list_label")
    prop_constraint = promptI18n.format_user_prompt(cfg, "prop_constraint")
    suffix = promptI18n.get_storyboard_user_prompt_suffix(cfg, effective_shot_duration)

    user_prompt = (
        f"{script_label}\n{script_content}\n\n"
        f"{task_label}\n{task_instruction}{extra_constraint}\n\n"
        f"{char_list_label}\n{character_list}\n\n{char_constraint}\n\n"
        f"{scene_list_label}\n{scene_list}\n\n{scene_constraint}\n\n"
        f"{prop_list_label}\n{prop_list}\n\n{prop_constraint}\n\n"
        f"{suffix}"
    )

    want_narration = (
        include_narration is True
        or include_narration == 1
        or str(include_narration).lower() in ("true", "1")
    )
    if want_narration:
        user_prompt += promptI18n.get_storyboard_narration_extra_instructions(cfg)

    system_prompt = promptI18n.get_storyboard_system_prompt(cfg)

    if storyboard_count:
        try:
            target_count = int(storyboard_count)
            if target_count > 0:
                is_en = "[Role]" in system_prompt
                if is_en:
                    system_prompt += f"""\n\n[HIGHEST PRIORITY — USER SPECIFIED COUNT]
The user requires exactly {target_count} shots (±10% tolerance is acceptable).
This requirement OVERRIDES the "one action = one shot, no merging" rule above.
You MUST merge related consecutive actions into fewer shots OR split key moments into more shots to reach this target.
Do NOT produce a shot count far from {target_count} under any circumstance."""
                else:
                    system_prompt += f"""\n\n【最高优先级——用户指定分镜数量】
用户要求生成恰好 {target_count} 个分镜（允许 ±10% 的偏差，即 {int(math.floor(target_count * 0.9))}~{int(math.ceil(target_count * 1.1))} 个均可接受）。
此要求优先级高于上述所有原则，包括"一动作一镜头、禁止合并"的规则。
- 若动作较多、自然拆分超过目标数量，请将相关联的连续小动作合并为一个镜头
- 若动作较少、自然拆分不足目标数量，请将重要场景或情绪转折拆分为多个镜头
- 严禁生成数量与 {target_count} 相差悬殊的分镜方案"""
        except (TypeError, ValueError):
            pass

    if want_narration:
        is_en = "[Role]" in system_prompt
        if is_en:
            system_prompt += """\n\n[HIGHEST PRIORITY — NARRATION / VO MODE]
The user enabled narrator voice-over for the whole episode. Every shot object MUST include non-empty "narration" (≥1 sentence). Shot 1 MUST have an opening VO hook (time/place/mood). Shots 1 and 2 MUST NOT both have empty narration. Empty "narration" is NOT allowed in this mode."""
        else:
            system_prompt += """\n\n【最高优先级——解说旁白已开启】
用户已开启全片解说：每个分镜的 narration 必须为非空字符串（至少一句）。第 1 镜必须有开场解说。第 1、2 镜禁止同时留空 narration。本模式下不允许 narration 为空。"""

    want_universal_omni = (
        universal_omni is True
        or universal_omni == 1
        or str(universal_omni or "").lower() in ("true", "1")
    )
    if want_universal_omni:
        system_prompt += promptI18n.get_storyboard_universal_omni_mode_suffix(cfg)

    if _existing_task_id:
        # Worker 恢复执行时复用 API 已创建的任务，避免再次入队形成递归。
        task = {"id": _existing_task_id}
    else:
        task = taskService.create_task(db, log_obj, "storyboard_generation", str(ep_id_num))
        db.commit()

    log_obj.info(
        "Generating storyboard asynchronously",
        extra={
            "task_id": task["id"],
            "episode_id": episode_id,
            "drama_id": episode["drama_id"],
            "script_length": len(script_content),
            "character_count": len(characters),
            "scene_count": len(scenes),
            "storyboard_count": storyboard_count,
            "video_duration": video_duration,
            "universal_omni_storyboard": want_universal_omni,
        },
    )

    run_cfg = dict(cfg) if isinstance(cfg, dict) else {}
    style_sec = dict(run_cfg.get("style", {}))
    style_sec["default_video_ratio"] = image_ratio
    style_sec["default_image_ratio"] = image_ratio
    run_cfg["style"] = style_sec

    clip_sec = int(video_clip_duration) if video_clip_duration and video_clip_duration > 0 else None

    if _existing_task_id:
        # 此分支只由持久化 Worker 调用；Prompt 在消费时构建，不写入 queue_jobs.payload。
        process_storyboard_generation(
            db,
            log_obj,
            run_cfg,
            task["id"],
            str(ep_id_num),
            model or None,
            final_style,
            user_prompt,
            system_prompt,
            want_narration,
            want_universal_omni,
            clip_sec,
        )
    else:
        from app.tasks import queue_service

        queue_service.enqueue_job(
            db,
            {
                "queue_name": "storyboards",
                "task_type": "legacy.storyboard.generate",
                "async_task_id": task["id"],
                "resource_id": str(ep_id_num),
                "payload": {
                    "episode_id": ep_id_num,
                    "model": model,
                    "style": style,
                    "storyboard_count": storyboard_count,
                    "video_duration": video_duration,
                    "aspect_ratio": aspect_ratio,
                    "include_narration": include_narration,
                    "universal_omni": universal_omni,
                },
            },
            create_async_task=False,
        )
        db.commit()

    return {
        "task_id": task["id"],
        "status": "pending",
        "message": "分镜生成任务已创建，正在后台处理...",
    }


def rebuild_video_prompt_for_storyboard(db: Session, log_obj, storyboard_id: Any) -> dict | None:
    sb_id = to_int_id(storyboard_id)
    if not sb_id or sb_id <= 0:
        return None

    row = fetch_one(
        db,
        """SELECT s.*, e.drama_id
           FROM storyboards s
           JOIN episodes e ON e.id = s.episode_id AND e.deleted_at IS NULL
           WHERE s.id = :id AND s.deleted_at IS NULL""",
        {"id": sb_id},
    )
    if not row:
        return None

    cfg = load_config()
    drama = None
    if row.get("drama_id"):
        drama = fetch_one(
            db,
            "SELECT style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL",
            {"id": row["drama_id"]},
        )

    final_style = (
        resolved_stream_style_from_drama("", drama)
        or ((cfg.get("style", {}) if isinstance(cfg, dict) else {}).get("default_style"))
        or ""
    )

    drama_aspect_ratio = None
    if drama and drama.get("metadata"):
        try:
            meta = json.loads(drama["metadata"]) if isinstance(drama["metadata"], str) else drama["metadata"]
            if meta and meta.get("aspect_ratio"):
                drama_aspect_ratio = meta["aspect_ratio"]
        except Exception:
            pass

    video_ratio = (
        drama_aspect_ratio
        or ((cfg.get("style", {}) if isinstance(cfg, dict) else {}).get("default_video_ratio"))
        or "16:9"
    )

    video_prompt = generate_video_prompt(row, final_style, video_ratio)
    now = timestamp()
    execute(
        db,
        "UPDATE storyboards SET video_prompt = :vp, updated_at = :now WHERE id = :id",
        {"vp": video_prompt, "now": now, "id": sb_id},
    )
    db.commit()

    if log_obj:
        log_obj.info("[分镜] 已按最新规则重建 video_prompt", extra={"id": sb_id, "len": len(video_prompt)})

    return storyboardEntityService.get_storyboard_by_id(db, sb_id)


def copy_storyboard_asset_links(db: Session, from_sb_id: int, to_sb_id: int) -> None:
    from_id = to_int_id(from_sb_id)
    to_id = to_int_id(to_sb_id)
    now = timestamp()
    try:
        chars = fetch_all(
            db,
            "SELECT character_id FROM storyboard_characters WHERE storyboard_id = :fid",
            {"fid": from_id},
        )
        for c in chars:
            _insert_ignore_storyboard_character(db, to_id, c["character_id"], now)
    except Exception:
        pass

    try:
        props = fetch_all(
            db,
            "SELECT prop_id FROM storyboard_props WHERE storyboard_id = :fid",
            {"fid": from_id},
        )
        for p in props:
            _insert_ignore_storyboard_prop(db, to_id, p["prop_id"])
    except Exception:
        pass


def char_speech_weight(text_content: str | None) -> float:
    if not text_content:
        return 0.0
    cleaned = re.sub(r"\s+", "", str(text_content))
    return max(1.0, len(cleaned) / 4.0)


def duration_for_split_segment(segment_type: str, text_content: str | None) -> int:
    w = char_speech_weight(text_content)
    if segment_type == "narration":
        return min(12, max(6, int(round(w + 2))))
    return min(10, max(5, int(round(w))))


def parse_dialogue_to_entries(dialogue: Any) -> list[dict[str, str]]:
    if not dialogue:
        return []
    lines = str(dialogue).strip().splitlines()
    entries = []
    pattern = re.compile(r"^([^：:\s]+)[：:]\s*[\"“'”]?([^\"“”']+)[\"“”']?$")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            entries.append({"speaker": m.group(1).strip(), "text": m.group(2).strip()})
        else:
            entries.append({"speaker": "", "text": line})
    return entries


def infer_primary_on_screen_character(row: dict, speakers: list[str]) -> str:
    combined = " ".join([
        str(row.get("action") or ""),
        str(row.get("result") or ""),
        str(row.get("title") or ""),
        str(row.get("dialogue") or ""),
    ])
    for s in speakers:
        if s and s in combined:
            return s
    return speakers[-1] if speakers else "角色"


def build_split_plans_from_storyboard(row: dict) -> list[dict[str, Any]]:
    dialogue_entries = parse_dialogue_to_entries(row.get("dialogue"))
    narration_text = str(row.get("narration") or "").strip()
    segment_count = len(dialogue_entries) + (1 if narration_text else 0)
    if segment_count < 2:
        raise ValueError("当前分镜仅有一段对白或旁白，无需拆镜")
    if not dialogue_entries and narration_text:
        raise ValueError("仅有旁白无法按对白拆镜")

    all_speakers = [d["speaker"] for d in dialogue_entries if d.get("speaker")]
    plans = []

    base_title = str(row.get("title") or "分镜").strip()

    for item in dialogue_entries:
        who = item.get("speaker") or "角色"
        text_val = item.get("text") or ""
        others = [n for n in all_speakers if n and n != who]
        closed = "、".join(others) if others else "对方"
        is_reporter = bool(re.search(r"记者", who)) or who == "小雅"
        plans.append({
            "type": "dialogue",
            "speaker": who,
            "dialogue": f"{who}：{text_val}",
            "narration": None,
            "title": f"{base_title}·{who}对白",
            "duration": duration_for_split_segment("dialogue", text_val),
            "action": (
                f"采访场景，{who}面向对方发问，仅{who}开口说话，{closed}闭口聆听无口型。"
                if is_reporter
                else f"镜头聚焦{who}，仅{who}开口对口型说话，{closed}全程闭口无口型。"
            ),
            "result": f"{closed}保持静默聆听。" if is_reporter else f"{who}完成台词，情绪鲜明。",
            "shot_type": row.get("shot_type") or "中景" if is_reporter else "近景",
            "movement": row.get("movement") or "固定" if is_reporter else "推镜",
        })

    if narration_text:
        focus = infer_primary_on_screen_character(row, all_speakers) or "角色"
        plans.append({
            "type": "narration",
            "speaker": None,
            "dialogue": None,
            "narration": narration_text,
            "title": f"{base_title}·画外旁白",
            "duration": duration_for_split_segment("narration", narration_text),
            "action": f"{focus}在画面中保持静止，双唇闭合，无口型，听画外纪录片旁白。",
            "result": f"{focus}表情维持强硬自信，无唇动。",
            "shot_type": "近景",
            "movement": row.get("movement") or "固定",
        })

    return plans


def persist_split_storyboard_row(
    db: Session,
    episode_id: int,
    storyboard_number: int,
    base_row: dict,
    plan: dict,
    now: str,
) -> int:
    res = execute(
        db,
        """INSERT INTO storyboards (
          episode_id, scene_id, storyboard_number, title, description, layout_description,
          location, time, duration, dialogue, narration, action, result, atmosphere,
          image_prompt, characters, shot_type, angle, angle_h, angle_v, angle_s,
          movement, lighting_style, depth_of_field, segment_index, segment_title,
          creation_mode, universal_segment_text, status, created_at, updated_at
        ) VALUES (
          :episode_id, :scene_id, :storyboard_number, :title, :description, :layout_description,
          :location, :time, :duration, :dialogue, :narration, :action, :result, :atmosphere,
          :image_prompt, :characters, :shot_type, :angle, :angle_h, :angle_v, :angle_s,
          :movement, :lighting_style, :depth_of_field, :segment_index, :segment_title,
          :creation_mode, NULL, 'pending', :created_at, :updated_at
        )""",
        {
            "episode_id": episode_id,
            "scene_id": base_row.get("scene_id"),
            "storyboard_number": storyboard_number,
            "title": plan["title"],
            "description": base_row.get("description"),
            "layout_description": base_row.get("layout_description"),
            "location": base_row.get("location"),
            "time": base_row.get("time"),
            "duration": plan["duration"],
            "dialogue": plan["dialogue"],
            "narration": plan["narration"],
            "action": plan["action"],
            "result": plan["result"],
            "atmosphere": base_row.get("atmosphere"),
            "image_prompt": base_row.get("image_prompt"),
            "characters": base_row.get("characters"),
            "shot_type": plan.get("shot_type") or base_row.get("shot_type"),
            "angle": base_row.get("angle"),
            "angle_h": base_row.get("angle_h"),
            "angle_v": base_row.get("angle_v"),
            "angle_s": base_row.get("angle_s"),
            "movement": plan.get("movement") or base_row.get("movement"),
            "lighting_style": base_row.get("lighting_style"),
            "depth_of_field": base_row.get("depth_of_field"),
            "segment_index": base_row.get("segment_index"),
            "segment_title": base_row.get("segment_title"),
            "creation_mode": "universal" if base_row.get("creation_mode") == "universal" else "classic",
            "created_at": now,
            "updated_at": now,
        },
    )
    return _get_last_inserted_id(db, res) or 0


def update_storyboard_as_split_segment(
    db: Session,
    sb_id: int,
    base_row: dict,
    plan: dict,
    now: str,
) -> None:
    execute(
        db,
        """UPDATE storyboards SET
          title = :title, duration = :duration, dialogue = :dialogue, narration = :narration,
          action = :action, result = :result, shot_type = :shot_type, movement = :movement,
          universal_segment_text = NULL, video_prompt = NULL, video_url = NULL,
          audio_local_path = NULL, narration_audio_local_path = NULL, status = 'pending',
          updated_at = :now
        WHERE id = :id AND deleted_at IS NULL""",
        {
            "title": plan["title"],
            "duration": plan["duration"],
            "dialogue": plan["dialogue"],
            "narration": plan["narration"],
            "action": plan["action"],
            "result": plan["result"],
            "shot_type": plan.get("shot_type") or base_row.get("shot_type"),
            "movement": plan.get("movement") or base_row.get("movement"),
            "now": now,
            "id": sb_id,
        },
    )


def split_storyboard_by_audio(db: Session, log_obj, storyboard_id: Any) -> dict[str, Any]:
    sb_id = to_int_id(storyboard_id)
    if not sb_id or sb_id <= 0:
        raise ValueError("无效的分镜 id")

    row = fetch_one(db, "SELECT * FROM storyboards WHERE id = :id AND deleted_at IS NULL", {"id": sb_id})
    if not row:
        raise ValueError("分镜不存在")

    plans = build_split_plans_from_storyboard(row)
    extra_count = len(plans) - 1
    now = timestamp()
    episode_id = row["episode_id"]
    base_number = int(row.get("storyboard_number") or 0)

    if extra_count > 0:
        execute(
            db,
            """UPDATE storyboards SET storyboard_number = storyboard_number + :extra, updated_at = :now
               WHERE episode_id = :eid AND storyboard_number > :base AND deleted_at IS NULL""",
            {"extra": extra_count, "now": now, "eid": episode_id, "base": base_number},
        )

    storyboard_ids = []
    update_storyboard_as_split_segment(db, sb_id, row, plans[0], now)
    storyboard_ids.append(sb_id)

    for i in range(1, len(plans)):
        new_num = base_number + i
        new_id = persist_split_storyboard_row(db, episode_id, new_num, row, plans[i], now)
        copy_storyboard_asset_links(db, sb_id, new_id)
        storyboard_ids.append(new_id)

    db.commit()

    for id_val in storyboard_ids:
        rebuild_video_prompt_for_storyboard(db, log_obj, id_val)

    summary = "；".join([f"{p['duration']}s {p['title']}" for p in plans])
    if log_obj:
        log_obj.info(
            "[分镜] 按对白拆镜完成",
            extra={"source_id": sb_id, "storyboard_ids": storyboard_ids, "plans": summary},
        )

    storyboard_rows = [storyboardEntityService.get_storyboard_by_id(db, sid) for sid in storyboard_ids]
    return {
        "source_id": sb_id,
        "storyboard_ids": storyboard_ids,
        "created_count": extra_count,
        "plans_summary": summary,
        "storyboards": storyboard_rows,
    }


# CamelCase 别名与 Node 严格保持一致
normalizeStoryboardShotNumber = normalize_storyboard_shot_number
dedupeStoryboardRowsByNumber = dedupe_storyboard_rows_by_number
getStoryboardsForEpisode = get_storyboards_for_episode
generateStoryboard = generate_storyboard
composeStoryboardVideoPrompt = generate_video_prompt
rebuildVideoPromptForStoryboard = rebuild_video_prompt_for_storyboard
splitStoryboardByAudio = split_storyboard_by_audio
syncStoryboardCharacters = sync_storyboard_characters
