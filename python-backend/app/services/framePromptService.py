"""分镜帧提示词服务 — 严格对齐 backend-node/src/services/framePromptService.js。"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import timestamp
from app.db.session import execute, fetch_all, fetch_one, session_scope
from app.services import aiClient, angleService, promptI18n, taskService
from app.utils.dramaStyleMerge import merge_cfg_style_with_drama
from app.utils.framePromptSanitize import parse_names_from_anchor_lines, sanitize_frame_prompt
from app.utils.safeJson import safe_parse_ai_json

log = get_logger("lmd.framePrompt")

FRAME_TYPES: list[str] = ["first", "key", "last", "panel", "action"]


def get_frame_prompts(db: Session, storyboard_id: int) -> list[dict]:
    rows = fetch_all(
        db,
        "SELECT * FROM frame_prompts WHERE storyboard_id = :sid ORDER BY created_at ASC",
        {"sid": int(storyboard_id)},
    )
    return [
        {
            "id": r["id"],
            "storyboard_id": r["storyboard_id"],
            "frame_type": r["frame_type"],
            "prompt": r["prompt"],
            "description": r["description"],
            "layout": r["layout"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def save_frame_prompt(
    db: Session,
    log_or_storyboard_id: Any,
    storyboard_id_or_frame_type: Any,
    frame_type_or_prompt: Any,
    prompt_or_description: Any = None,
    description_or_layout: Optional[str] = None,
    layout: Optional[str] = None,
) -> None:
    """兼容 save_frame_prompt(db, storyboard_id, frame_type, prompt, description, layout)
    及 save_frame_prompt(db, log, storyboard_id, frame_type, prompt, description, layout)。
    """
    if prompt_or_description is not None and not isinstance(frame_type_or_prompt, str):
        # (db, log, storyboard_id, frame_type, prompt, description, layout)
        storyboard_id = int(storyboard_id_or_frame_type)
        frame_type = str(frame_type_or_prompt)
        prompt = str(prompt_or_description)
        desc = description_or_layout
        lay = layout
    else:
        # (db, storyboard_id, frame_type, prompt, description, layout)
        storyboard_id = int(log_or_storyboard_id)
        frame_type = str(storyboard_id_or_frame_type)
        prompt = str(frame_type_or_prompt)
        desc = prompt_or_description
        lay = description_or_layout

    if frame_type not in FRAME_TYPES:
        raise ValueError("不支持的 frame_type，可选: " + ", ".join(FRAME_TYPES))
    if not (prompt or "").strip():
        raise ValueError("prompt 不能为空")
    now = timestamp()
    execute(
        db,
        "DELETE FROM frame_prompts WHERE storyboard_id = :sid AND frame_type = :ft",
        {"sid": int(storyboard_id), "ft": frame_type},
    )
    execute(
        db,
        """
        INSERT INTO frame_prompts (storyboard_id, frame_type, prompt, description, layout, created_at, updated_at)
        VALUES (:sid, :ft, :p, :d, :l, :c, :u)
        """,
        {
            "sid": int(storyboard_id), "ft": frame_type, "p": prompt,
            "d": desc, "l": lay, "c": now, "u": now,
        },
    )
    log.info("Frame prompt saved", {"storyboard_id": storyboard_id, "frame_type": frame_type})


def clean_appearance_for_identity(app_text: Any) -> str:
    """去除服装/衣着/配饰等可变描述，保留固定身份特征（脸型、发型、肤质、眼神、气质等）。"""
    if not app_text:
        return ""
    t = str(app_text).strip()
    clothing_patterns = [
        r"身穿[^，。；\n]*",
        r"穿着[^，。；\n]*",
        r"衣着[^，。；\n]*",
        r"手持[^，。；\n]*",
        r"戴着[^，。；\n]*",
        r"围[^，。；\n]*巾",
        r"服装[^，。；\n]*",
        r"服饰[^，。；\n]*",
        r"着装[^，。；\n]*",
        r" dressed in [^，。；\n]*",
        r" wearing [^，。；\n]*",
        r" holding [^，。；\n]*",
        r"着[^，。；\n]*鞋",
    ]
    for pat in clothing_patterns:
        t = re.sub(pat, "", t, flags=re.IGNORECASE)
    t = re.sub(r"[，、；]\s*[，、；]+", "，", t)
    t = re.sub(r"^[，、；\s]+|[，、；\s]+$", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def build_character_anchor_text(name: str, anchors: dict | None, appearance: str | None) -> str:
    """等价 buildCharacterAnchorText。"""
    if anchors and isinstance(anchors, dict) and len(anchors) > 0:
        parts = [f"Character: {name}"]
        if anchors.get("face_shape") and anchors.get("face_shape") != "unspecified":
            parts.append(f"Face: {anchors['face_shape']}")
        if anchors.get("facial_features") and anchors.get("facial_features") != "unspecified":
            parts.append(f"Features: {anchors['facial_features']}")
        if anchors.get("hair_style") and anchors.get("hair_style") != "unspecified":
            parts.append(f"Hair: {anchors['hair_style']}")
        if anchors.get("skin_texture") and anchors.get("skin_texture") != "unspecified":
            parts.append(f"Skin: {anchors['skin_texture']}")
        if anchors.get("color_anchors") and isinstance(anchors.get("color_anchors"), dict):
            colors = [
                f"{k}={v}"
                for k, v in anchors["color_anchors"].items()
                if v and v != "unspecified"
            ]
            if colors:
                parts.append(f"Colors: {', '.join(colors)}")
        if anchors.get("unique_marks") and anchors.get("unique_marks") not in ("none", "unspecified"):
            parts.append(f"Marks: {anchors['unique_marks']}")
        return "; ".join(parts)

    cleaned = clean_appearance_for_identity(appearance)
    if cleaned:
        return f"{name}（{cleaned}）—— 以上为该角色固定视觉身份锚点，生成画面时必须严格以此为基础，禁止添加任何未在此列出的外貌细节（发型/颜色/脸型/气质等）"
    return name


def load_storyboard_character_names(db: Session, storyboard_id: int) -> list[str]:
    """等价 loadStoryboardCharacterNames：优先按 storyboards.characters，兜底 storyboard_characters。"""
    sid = int(storyboard_id)
    ids: list[int] = []
    used_explicit_characters = False

    try:
        sb_row = fetch_one(db, "SELECT characters FROM storyboards WHERE id = :sid AND deleted_at IS NULL", {"sid": sid})
        raw_chars = sb_row.get("characters") if sb_row else None
        if raw_chars not in (None, "") and str(raw_chars).strip():
            parsed = json.loads(raw_chars) if isinstance(raw_chars, str) else raw_chars
            if isinstance(parsed, list):
                used_explicit_characters = True
                for item in parsed:
                    if isinstance(item, dict) and item.get("id") is not None:
                        ids.append(int(item["id"]))
                    elif isinstance(item, (int, float)):
                        ids.append(int(item))
                    elif isinstance(item, str) and item.strip().isdigit():
                        ids.append(int(item.strip()))
    except Exception:
        pass

    if not used_explicit_characters:
        links = fetch_all(db, "SELECT character_id FROM storyboard_characters WHERE storyboard_id = :sid", {"sid": sid})
        if links:
            ids = [int(r["character_id"]) for r in links if r.get("character_id") is not None]

    if not ids:
        if used_explicit_characters:
            return []
        try:
            sb_row = fetch_one(db, "SELECT characters FROM storyboards WHERE id = :sid AND deleted_at IS NULL", {"sid": sid})
            raw = (sb_row.get("characters") if sb_row else "") or ""
            if raw:
                matches = re.findall(r"[\u4e00-\u9fa5]{2,4}", str(raw))
                if matches:
                    placeholders = ", ".join(":p%d" % i for i in range(len(matches)))
                    params: dict[str, Any] = {f"p{i}": name for i, name in enumerate(matches)}
                    params["sid"] = sid
                    name_rows = fetch_all(
                        db,
                        f"""SELECT id, name, appearance, identity_anchors FROM characters 
                            WHERE name IN ({placeholders}) AND deleted_at IS NULL 
                            AND drama_id = (SELECT drama_id FROM episodes WHERE id = (SELECT episode_id FROM storyboards WHERE id = :sid))""",
                        params,
                    )
                    if name_rows:
                        result: list[str] = []
                        for r in name_rows:
                            anchors = None
                            if r.get("identity_anchors"):
                                try:
                                    anchors = json.loads(r["identity_anchors"])
                                except Exception:
                                    pass
                            result.append(build_character_anchor_text(r.get("name") or "", anchors, r.get("appearance")))
                        return result
        except Exception:
            pass
        return []

    placeholders = ", ".join(":p%d" % i for i in range(len(ids)))
    params = {f"p{i}": val for i, val in enumerate(ids)}
    rows = fetch_all(
        db,
        f"SELECT id, name, appearance, identity_anchors FROM characters WHERE id IN ({placeholders}) AND deleted_at IS NULL",
        params,
    )
    if not rows:
        rows = fetch_all(
            db,
            f"SELECT id, name, appearance, identity_anchors FROM character_libraries WHERE id IN ({placeholders}) AND deleted_at IS NULL",
            params,
        )

    out: list[str] = []
    for r in rows:
        anchors = None
        if r.get("identity_anchors"):
            try:
                anchors = json.loads(r["identity_anchors"])
            except Exception:
                pass
        out.append(build_character_anchor_text(r.get("name") or "", anchors, r.get("appearance")))
    return out


def load_drama_character_names_for_storyboard(db: Session, storyboard_id: int) -> list[str]:
    """本剧全部角色名（用于从帧提示词中剔除未勾选出场的人物）。"""
    try:
        rows = fetch_all(
            db,
            """SELECT name FROM characters
               WHERE drama_id = (
                 SELECT e.drama_id FROM episodes e
                 INNER JOIN storyboards s ON s.episode_id = e.id
                 WHERE s.id = :sid AND s.deleted_at IS NULL AND e.deleted_at IS NULL
               ) AND deleted_at IS NULL""",
            {"sid": int(storyboard_id)},
        )
        return [str(r.get("name") or "").strip() for r in rows if str(r.get("name") or "").strip()]
    except Exception:
        return []


def load_storyboard(db: Session, storyboard_id: int) -> dict | None:
    row = fetch_one(db, "SELECT * FROM storyboards WHERE id = :sid AND deleted_at IS NULL", {"sid": int(storyboard_id)})
    if not row:
        return None
    return {
        "id": row.get("id"),
        "description": row.get("description"),
        "location": row.get("location"),
        "time": row.get("time"),
        "dialogue": row.get("dialogue"),
        "narration": row.get("narration"),
        "action": row.get("action"),
        "atmosphere": row.get("atmosphere"),
        "result": row.get("result"),
        "scene_id": row.get("scene_id"),
        "shot_type": row.get("shot_type"),
        "angle": row.get("angle"),
        "angle_h": row.get("angle_h"),
        "angle_v": row.get("angle_v"),
        "angle_s": row.get("angle_s"),
        "movement": row.get("movement"),
        "lighting_style": row.get("lighting_style"),
        "depth_of_field": row.get("depth_of_field"),
        "layout_description": row.get("layout_description") or None,
    }


def load_scene(db: Session, scene_id: Any) -> dict | None:
    if scene_id is None:
        return None
    try:
        row = fetch_one(db, "SELECT id, location, time FROM scenes WHERE id = :id AND deleted_at IS NULL", {"id": int(scene_id)})
        return {"id": row["id"], "location": row.get("location"), "time": row.get("time")} if row else None
    except Exception:
        return None


def expand_angle_description(angle: str | None, is_en: bool, angle_h: str | None = None, angle_v: str | None = None, angle_s: str | None = None) -> str | None:
    if angle_h and angle_v and angle_s:
        return (
            angleService.to_prompt_fragment(angle_h, angle_v, angle_s)
            if is_en
            else f"相机角度：{angleService.to_chinese_label(angle_h, angle_v, angle_s)}"
        )
    if angle:
        if is_en:
            return angleService.from_legacy_text(angle, "")
        parsed = angleService.parse_from_legacy_text(angle, "")
        return f"相机角度：{angleService.to_chinese_label(parsed['h'], parsed['v'], parsed['s'])}"
    return None


def build_storyboard_context(cfg: dict | None, sb: dict, scene: dict | None, character_names: list[str]) -> str:
    parts: list[str] = []
    style_zh = str((cfg or {}).get("style", {}).get("default_style_zh") or "").strip()
    style_en = str((cfg or {}).get("style", {}).get("default_style_en") or (cfg or {}).get("style", {}).get("default_style") or "").strip()
    is_en = promptI18n.is_english(cfg)
    if is_en:
        if style_en:
            parts.append(f"MANDATORY ART STYLE: {style_en}")
        elif style_zh:
            parts.append(f"MANDATORY ART STYLE: {style_zh}")
    elif style_zh:
        parts.append(f"【画风·最高优先级】{style_zh}")
    elif style_en:
        parts.append(f"【画风·最高优先级】{style_en}")

    parts.append(promptI18n.get_realistic_physical_scale_contract(is_en))

    ld = str(sb.get("layout_description") or "").strip()
    if ld:
        if is_en:
            parts.insert(0, f"""【SPATIAL LAYOUT CONTRACT — HIGHEST PRIORITY + CINEMATIC BREATHING ROOM FOR MOVEMENT】
{ld}

【HARD LOCK (must stay 100% consistent)】
- Main character(s) basic screen placement (left/center/right third, facing direction, spatial relationship to key props).
- Realistic physical scale and relative proportions of all major props (only props actually present in the shot; sizes must match the story's era/setting; nothing exaggerated or distorted).
- Overall visual weight balance (character remains the clear focal point; all props stay secondary environmental elements).

【ALLOWED + ENCOURAGED CINEMATIC EVOLUTION (5-15s videos — support declared movement with meaningful change)】
- The last frame MUST show visible, cumulative framing evolution driven by the declared camera_movement over the full clip duration (typically 5-15 seconds). Evolution should be noticeable, not just tiny micro-adjustments.
- Hard lock remains: core character placement (no L/R swap), realistic physical sizes of all props, basic spatial relationships, and perspective must stay consistent.
- Goal: First and last frames must read as the same continuous physical scene and take, but with enough visual progression that the 5-15s video generated from them actually feels dynamic and realizes the declared movement, instead of looking nearly static or locked-off.

Violating hard lock = failure. Insufficient evolution that suppresses the movement = also bad result.""")
        else:
            parts.insert(0, f"""【空间布局合同 — 最高优先级铁律 + 运镜呼吸空间（必须严格遵守核心，但允许电影化微调）】
{ld}

【核心锁定（必须100%一致）】
- 主要角色在画面中的基本站位（画面左/中/右三分、朝向、与主要道具的相对空间关系）。
- 所有主要道具的真实物理尺寸与相对比例（仅写本分镜实际出现的道具，尺度须符合剧本时代背景，所有物件不得夸大或失真；古代场景严禁出现智能手机、遥控器等现代物品）。
- 整体画面重心与基本平衡感（主角仍是视觉焦点，所有道具均为次要环境元素）。

【允许且推荐的电影化演化（5-15秒视频，强烈支持 declared movement）】
- 尾帧必须根据本分镜的 movement 和视频时长（通常5-15秒）进行有意义的取景演化，而非微调。
- 示例（时长越长，演化幅度可越大）：
  - 缓推（slow push-in）5-10秒+：尾帧人物画面占比应明显大于首帧，背景明显更被压缩，取景更紧。
  - 手持跟拍：允许自然的取景晃动、轻微不完美偏移、以及随运动产生的构图漂移。
  - 横摇/环绕/跟拍：画面可有清晰的左右进入/退出变化或机位自然漂移。
- 硬锁：主要角色核心站位不左右互换、主要道具真实尺寸与基本相对位置不变、所有物体保持真实物理尺度与透视。
- 目标：首尾帧之间要有足够视觉差异，让基于它们的5-15秒视频真正“动”起来，充分实现声明的运镜效果，而不是几乎定格。

违背硬锁 = 生成失败；演化幅度过小导致运镜失效也属于不理想结果。""")

    if sb.get("description"):
        parts.append(promptI18n.format_user_prompt(cfg, "shot_description_label", sb["description"]))
    if scene:
        parts.append(promptI18n.format_user_prompt(cfg, "scene_label", scene.get("location") or "", scene.get("time") or ""))
    elif sb.get("location") or sb.get("time"):
        parts.append(promptI18n.format_user_prompt(cfg, "scene_label", sb.get("location") or "", sb.get("time") or ""))

    allowed_char_names = parse_names_from_anchor_lines(character_names)
    if allowed_char_names:
        roster_line = (
            f"【ALLOWED CHARACTERS IN THIS SHOT — ONLY these may appear; NO other people】\n{', '.join(allowed_char_names)}"
            if is_en
            else f"【本分镜允许出场的角色（仅此名单，严禁出现名单外的任何其他人物）】\n{'、'.join(allowed_char_names)}"
        )
        parts.insert(0, roster_line)

    if character_names:
        if is_en:
            parts.append(f"【CHARACTER VISUAL ANCHORS - MUST USE EXACTLY, DO NOT HALLUCINATE】\n{chr(10).join(character_names)}")
        else:
            parts.insert(0, f"【角色视觉锚点 - 最高优先级铁律，必须严格遵守，禁止任何脑补或添加未提供的外貌细节】\n{chr(10).join(character_names)}")

    if sb.get("action"):
        parts.append(promptI18n.format_user_prompt(cfg, "action_label", sb["action"]))
    if sb.get("result"):
        parts.append(promptI18n.format_user_prompt(cfg, "result_label", sb["result"]))
    if sb.get("dialogue"):
        parts.append(promptI18n.format_user_prompt(cfg, "dialogue_label", sb["dialogue"]))
    if sb.get("atmosphere"):
        parts.append(promptI18n.format_user_prompt(cfg, "atmosphere_label", sb["atmosphere"]))
    if sb.get("shot_type"):
        parts.append(promptI18n.format_user_prompt(cfg, "shot_type_label", sb["shot_type"]))
    if sb.get("angle") or (sb.get("angle_h") and sb.get("angle_v") and sb.get("angle_s")):
        angle_desc = expand_angle_description(sb.get("angle"), is_en, sb.get("angle_h"), sb.get("angle_v"), sb.get("angle_s"))
        if angle_desc:
            parts.append(angle_desc)
    if sb.get("movement"):
        parts.append(promptI18n.format_user_prompt(cfg, "movement_label", sb["movement"]))

    return "\n".join(parts)


def frame_kind_suffix(cfg: dict | None, frame_kind: str) -> str:
    is_en = promptI18n.is_english(cfg)
    if is_en:
        if frame_kind == "first":
            return "first frame, static shot"
        if frame_kind == "key":
            return "key frame, dynamic action"
        return "last frame, final state"
    if frame_kind == "first":
        return "首帧静止画面，动作发生前的初始状态"
    if frame_kind == "key":
        return "关键帧，动作高潮瞬间"
    return "尾帧静止画面，动作完成后的最终状态"


def build_fallback_prompt(cfg: dict | None, scene: dict | None, frame_kind: str) -> str:
    parts: list[str] = []
    is_en = promptI18n.is_english(cfg)
    if scene:
        loc = (", " if is_en else "，").join(
            [str(x) for x in [scene.get("location"), scene.get("time")] if x]
        )
        if loc:
            parts.append(loc)
    style = (
        str((cfg or {}).get("style", {}).get("default_style_en") or (cfg or {}).get("style", {}).get("default_style") or "").strip()
        if is_en
        else str((cfg or {}).get("style", {}).get("default_style_zh") or (cfg or {}).get("style", {}).get("default_style") or "").strip()
    )
    if style:
        parts.append(style)
    parts.append(frame_kind_suffix(cfg, frame_kind))
    return (", " if is_en else "，").join(parts)


def parse_frame_prompt_json(log_inst: Any, ai_response: str) -> dict | None:
    try:
        data = safe_parse_ai_json(ai_response, log_inst)
        if data and isinstance(data, dict) and isinstance(data.get("prompt"), str):
            return {"prompt": data["prompt"], "description": data.get("description") or ""}
    except Exception as e:
        (log_inst or log).warn("Frame prompt JSON parse failed", {"error": str(e), "response_head": (ai_response or "")[:200]})
    return None


def generate_single_frame(
    db: Session,
    log_inst: Any,
    cfg: dict,
    sb: dict,
    scene: dict | None,
    character_names: list[str],
    model: str | None,
    frame_kind: str,
    sanitize_opts: dict | None = None,
) -> dict:
    context = build_storyboard_context(cfg, sb, scene, character_names)
    allowed_char_names = parse_names_from_anchor_lines(character_names)
    all_drama_names = (sanitize_opts or {}).get("all_drama_names") or allowed_char_names

    if frame_kind == "first":
        system_prompt = promptI18n.get_first_frame_prompt(cfg)
        user_prompt = promptI18n.format_user_prompt(cfg, "frame_info", context)
    elif frame_kind == "key":
        system_prompt = promptI18n.get_key_frame_prompt(cfg)
        user_prompt = promptI18n.format_user_prompt(cfg, "key_frame_info", context)
    else:
        system_prompt = promptI18n.get_last_frame_prompt(cfg)
        user_prompt = promptI18n.format_user_prompt(cfg, "last_frame_info", context)

    logger = log_inst or log
    logger.info("[帧提示词] generateSingleFrame 开始", {
        "frame_kind": frame_kind,
        "storyboard_id": sb.get("id"),
        "angle": sb.get("angle"),
        "shot_type": sb.get("shot_type"),
        "movement": sb.get("movement"),
    })

    try:
        ai_response = aiClient.generate_text(
            db,
            logger,
            "text",
            user_prompt,
            system_prompt,
            {"model": model or None, "max_tokens": 2400},
        )
    except Exception as err:
        logger.warn("Frame prompt AI failed, using fallback", {"error": str(err)})
        prompt = build_fallback_prompt(cfg, scene, frame_kind)
        desc = (
            "镜头开始的静态画面，展示初始状态"
            if frame_kind == "first"
            else "动作高潮瞬间，展示关键动作"
            if frame_kind == "key"
            else "镜头结束画面，展示最终状态和结果"
        )
        return {"prompt": prompt, "description": desc}

    parsed = parse_frame_prompt_json(logger, ai_response)
    if parsed:
        cleaned_prompt = sanitize_frame_prompt(
            parsed["prompt"],
            allowed_char_names,
            all_drama_names,
            {
                "log": logger,
                "source": "frame_prompt_generation",
                "storyboard_id": sb.get("id"),
                "frame_kind": frame_kind,
            },
        )
        return {**parsed, "prompt": cleaned_prompt}

    fallback = build_fallback_prompt(cfg, scene, frame_kind)
    logger.warn("[帧提示词] JSON 解析失败，使用 FALLBACK prompt")
    return {
        "prompt": fallback,
        "description": "镜头结束画面，展示最终状态和结果" if frame_kind == "last" else "动作高潮瞬间，展示关键动作" if frame_kind == "key" else "镜头开始的静态画面，展示初始状态",
    }


def process_frame_prompt_generation(
    task_id: str,
    storyboard_id: int,
    frame_type: str,
    panel_count: int = 0,
    model: str | None = None,
) -> None:
    """持久化 Worker 执行函数。"""
    with session_scope() as db:
        cfg = load_config()
        taskService.update_task_status(db, task_id, "processing", 0, "正在生成帧提示词...")

        sb = load_storyboard(db, storyboard_id)
        if not sb:
            taskService.update_task_error(db, task_id, "分镜信息不存在")
            log.error("Frame prompt: storyboard not found", {"storyboard_id": storyboard_id})
            return

        try:
            ep_row = fetch_one(
                db,
                "SELECT drama_id FROM episodes WHERE id = (SELECT episode_id FROM storyboards WHERE id = :sid AND deleted_at IS NULL) AND deleted_at IS NULL",
                {"sid": int(storyboard_id)},
            )
            if ep_row and ep_row.get("drama_id"):
                drama_row = fetch_one(db, "SELECT style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": ep_row["drama_id"]})
                if drama_row:
                    next_cfg = {**cfg, "style": {**(cfg.get("style") or {})}}
                    if drama_row.get("metadata"):
                        meta = json.loads(drama_row["metadata"]) if isinstance(drama_row["metadata"], str) else drama_row["metadata"]
                        if meta and isinstance(meta, dict) and meta.get("aspect_ratio"):
                            next_cfg["style"]["default_image_ratio"] = meta["aspect_ratio"]
                            next_cfg["style"]["default_video_ratio"] = meta["aspect_ratio"]
                    cfg = merge_cfg_style_with_drama(next_cfg, drama_row)
        except Exception:
            pass

        scene = load_scene(db, sb.get("scene_id"))
        character_names = load_storyboard_character_names(db, storyboard_id)
        all_drama_names = load_drama_character_names_for_storyboard(db, storyboard_id)
        sanitize_opts = {"all_drama_names": all_drama_names}

        storyboard_id_str = str(storyboard_id)
        combined_prompt = ""
        description = ""
        layout = ""

        try:
            if frame_type in ("first", "key", "last"):
                single = generate_single_frame(db, log, cfg, sb, scene, character_names, model, frame_type, sanitize_opts)
                save_frame_prompt(db, log, storyboard_id, frame_type, single["prompt"], single.get("description"), "")
                combined_prompt = single["prompt"]
                description = single.get("description") or ""
            elif frame_type == "panel":
                count = panel_count or 3
                layout = f"horizontal_{count}"
                prompts: list[str] = []
                if count == 3:
                    first = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "first", sanitize_opts)
                    key = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "key", sanitize_opts)
                    last = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "last", sanitize_opts)
                    prompts.extend([first["prompt"], key["prompt"], last["prompt"]])
                elif count == 4:
                    first = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "first", sanitize_opts)
                    key1 = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "key", sanitize_opts)
                    key2 = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "key", sanitize_opts)
                    last = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "last", sanitize_opts)
                    prompts.extend([first["prompt"], key1["prompt"], key2["prompt"], last["prompt"]])
                else:
                    prompts.append(generate_single_frame(db, log, cfg, sb, scene, character_names, model, "first", sanitize_opts)["prompt"])
                    for _ in range(count - 2):
                        prompts.append(generate_single_frame(db, log, cfg, sb, scene, character_names, model, "key", sanitize_opts)["prompt"])
                    prompts.append(generate_single_frame(db, log, cfg, sb, scene, character_names, model, "last", sanitize_opts)["prompt"])
                description = "分镜板组合提示词"
                combined_prompt = "\n---\n".join(prompts)
                save_frame_prompt(db, log, storyboard_id, frame_type, combined_prompt, description, layout)
            elif frame_type == "action":
                layout = "horizontal_5"
                first = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "first", sanitize_opts)
                key1 = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "key", sanitize_opts)
                key2 = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "key", sanitize_opts)
                key3 = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "key", sanitize_opts)
                last = generate_single_frame(db, log, cfg, sb, scene, character_names, model, "last", sanitize_opts)
                combined_prompt = "\n---\n".join([first["prompt"], key1["prompt"], key2["prompt"], key3["prompt"], last["prompt"]])
                description = "动作序列组合提示词"
                save_frame_prompt(db, log, storyboard_id, frame_type, combined_prompt, description, layout)
            else:
                taskService.update_task_error(db, task_id, "不支持的帧类型")
                log.error("Frame prompt: unsupported frame_type", {"frame_type": frame_type})
                return

            taskService.update_task_result(db, task_id, {
                "storyboard_id": storyboard_id_str,
                "frame_type": frame_type,
                "response": {
                    "frame_type": frame_type,
                    "single_frame": {"prompt": combined_prompt, "description": description} if combined_prompt else None,
                    "layout": layout or None,
                },
            })
            db.commit()
            log.info("Frame prompt generation completed", {"task_id": task_id, "storyboard_id": storyboard_id, "frame_type": frame_type})
        except Exception as err:
            db.rollback()
            log.error("Frame prompt generation error", {"task_id": task_id, "error": str(err)})
            try:
                taskService.update_task_error(db, task_id, str(err) or "生成失败")
                db.commit()
            except Exception:
                pass


def generate_frame_prompt(
    db: Session,
    log_inst: Any,
    storyboard_id: int,
    frame_type: str,
    panel_count: int = 0,
    model: str | None = None,
) -> str:
    sid = int(storyboard_id)
    sb = fetch_one(db, "SELECT id FROM storyboards WHERE id = :id AND deleted_at IS NULL", {"id": sid})
    if not sb:
        raise ValueError("分镜不存在")
    if frame_type not in FRAME_TYPES:
        raise ValueError("不支持的 frame_type，可选: " + ", ".join(FRAME_TYPES))

    logger = log_inst or log
    task = taskService.create_task(db, logger, "frame_prompt_generation", str(storyboard_id))
    # async_tasks.id 是 UUID 字符串，不能强转 int；否则帧提示词任务刚创建就会失败。
    task_id = str(task["id"])

    from app.tasks import queue_service

    # 帧提示词可能包含多次模型调用，交给持久化队列执行，服务重启后仍可重试。
    queue_service.enqueue_job(
        db,
        {
            "queue_name": "storyboards",
            "task_type": "legacy.frame_prompt.generate",
            "async_task_id": task_id,
            "resource_id": str(sid),
            "payload": {
                "storyboard_id": sid,
                "frame_type": frame_type,
                "panel_count": panel_count or 0,
                "model": model,
            },
        },
        create_async_task=False,
    )
    db.commit()
    logger.info("Frame prompt task created", {"task_id": task_id, "storyboard_id": sid, "frame_type": frame_type})
    return task_id


def regenerate_layout_description(db: Session, storyboard_id: int) -> str:
    """等价 backend-node/src/services/framePromptService.js::regenerateLayoutDescription。"""
    sid = int(storyboard_id)
    sb_rows = fetch_all(
        db,
        "SELECT * FROM storyboards WHERE id = :sid AND deleted_at IS NULL",
        {"sid": sid},
    )
    if not sb_rows:
        raise ValueError("分镜不存在")
    sb = sb_rows[0]

    prev_sb = None
    next_sb = None
    if sb.get("episode_id") is not None and sb.get("storyboard_number") is not None:
        prev_sb = fetch_all(
            db,
            "SELECT storyboard_number, action, result, layout_description FROM storyboards WHERE episode_id = :eid AND storyboard_number < :num AND deleted_at IS NULL ORDER BY storyboard_number DESC LIMIT 1",
            {"eid": sb["episode_id"], "num": sb["storyboard_number"]},
        )
        next_sb = fetch_all(
            db,
            "SELECT storyboard_number, action, result, layout_description FROM storyboards WHERE episode_id = :eid AND storyboard_number > :num AND deleted_at IS NULL ORDER BY storyboard_number ASC LIMIT 1",
            {"eid": sb["episode_id"], "num": sb["storyboard_number"]},
        )
        prev_sb = prev_sb[0] if prev_sb else None
        next_sb = next_sb[0] if next_sb else None

    character_names = load_storyboard_character_names(db, sid)
    cfg = load_config()
    system_prompt = promptI18n.get_regenerate_layout_description_prompt(cfg)

    user_lines = [
        f"CURRENT_SHOT #{sb.get('storyboard_number') or sid}",
        f"ACTION: {sb.get('action')}" if sb.get("action") else None,
        f"RESULT: {sb.get('result')}" if sb.get("result") else None,
        f"DIALOGUE: {sb.get('dialogue')}" if sb.get("dialogue") else None,
        f"SHOT_TYPE: {sb.get('shot_type')}" if sb.get("shot_type") else None,
        f"CHARACTERS: {'；'.join(character_names)}" if character_names else None,
        f"PREV_SHOT #{prev_sb.get('storyboard_number')} LAYOUT: {prev_sb.get('layout_description') or '(none)'}" if prev_sb else "PREV_SHOT: (first shot)",
        f"NEXT_SHOT #{next_sb.get('storyboard_number')} LAYOUT: {next_sb.get('layout_description') or '(none)'}" if next_sb else "NEXT_SHOT: (last shot)",
        "请严格按照系统提示要求，只输出优化后的 layout_description 文本。",
    ]
    user_prompt = "\n".join(part for part in user_lines if part)

    log.info("[布局重生成] 开始", {"storyboard_id": sid, "has_prev": bool(prev_sb), "has_next": bool(next_sb)})

    raw = aiClient.generate_text(
        db,
        log,
        "text",
        user_prompt,
        system_prompt,
        {"max_tokens": 300, "temperature": 0.35},
    )

    new_layout = (raw or "").strip()
    new_layout = re.sub(r"^```[a-zA-Z]*\s*", "", new_layout, flags=re.IGNORECASE)
    new_layout = re.sub(r"\s*```$", "", new_layout)
    new_layout = re.sub(r"^[\"'“”‘’]+|[\"'“”‘’]+$", "", new_layout)
    new_layout = re.sub(r"^(布局描述|layout_description|空间布局|画面布局)[:：]\s*", "", new_layout, flags=re.IGNORECASE).strip()

    if not new_layout or len(new_layout) < 8:
        raise ValueError("AI 返回的布局描述过短或无效")

    now = timestamp()
    execute(
        db,
        "UPDATE storyboards SET layout_description = :v, updated_at = :t WHERE id = :id AND deleted_at IS NULL",
        {"v": new_layout, "t": now, "id": sid},
    )

    log.info("[布局重生成] 完成", {"storyboard_id": sid, "new_layout_preview": new_layout[:80]})
    return new_layout
