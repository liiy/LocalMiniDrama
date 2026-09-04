"""场景实体（scenes 表）操作，等价 Node services/sceneService.js 的 CRUD 部分。

P2 只翻译：getSceneById / createScene / updateScene / updateScenePrompt / deleteScene。
AI 生成（generateScenePromptOnly 等）留到 P4。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp
from app.services import aiClient, imageClient, promptI18n
from app.utils.dramaStyleMerge import apply_style_override_to_cfg, merge_cfg_style_with_drama

log = get_logger("lmd.scene")


def to_int_id(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def get_scene_by_id(db: Session, scene_id):
    """等价 Node sceneService.getSceneById（字段映射与 dramaService.rowToScene 不同）。"""
    r = db.execute(
        text("SELECT * FROM scenes WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(scene_id)}
    ).mappings().first()
    if not r:
        return None
    return {
        "id": r["id"],
        "drama_id": r["drama_id"],
        "location": r["location"],
        "time": r["time"],
        "prompt": r["prompt"],
        "polished_prompt": r["polished_prompt"] or None,
        "polished_prompt_single": r["polished_prompt_single"] or None,
        "image_url": r["image_url"],
        "local_path": r["local_path"],
        "extra_images": r["extra_images"] or None,
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def create_scene(db: Session, drama_id, req: dict):
    now = timestamp()
    episode_id = to_int_id(req["episode_id"]) if req.get("episode_id") is not None else None
    res = db.execute(
        text(
            """
            INSERT INTO scenes (drama_id, episode_id, location, time, prompt, image_url, local_path,
                storyboard_count, status, created_at, updated_at)
            VALUES (:drama_id, :episode_id, :location, :time, :prompt, :image_url, :local_path,
                1, 'pending', :created_at, :updated_at)
            """
        ),
        {
            "drama_id": to_int_id(drama_id),
            "episode_id": episode_id,
            "location": req.get("location") or "",
            "time": req.get("time") or "",
            "prompt": req.get("prompt") or "",
            "image_url": req.get("image_url"),
            "local_path": req.get("local_path"),
            "created_at": now,
            "updated_at": now,
        },
    )
    log.info("Scene created", extra={"scene_id": res.lastrowid, "drama_id": drama_id, "episode_id": episode_id})
    return get_scene_by_id(db, res.lastrowid)


def update_scene(db: Session, scene_id, req: dict) -> bool:
    exists = db.execute(
        text("SELECT id FROM scenes WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(scene_id)}
    ).first()
    if not exists:
        return False
    updates: list[str] = []
    params: dict = {}
    # Node 用 != null（image_url 走 != null，其余图片字段走 !== undefined）
    if req.get("location") is not None:
        updates.append("location = :location")
        params["location"] = req["location"]
    if req.get("time") is not None:
        updates.append("time = :time")
        params["time"] = req["time"]
    if req.get("prompt") is not None:
        updates.append("prompt = :prompt")
        params["prompt"] = req["prompt"]
    if req.get("polished_prompt") is not None:
        updates.append("polished_prompt = :polished_prompt")
        params["polished_prompt"] = req["polished_prompt"]
    if req.get("polished_prompt_single") is not None:
        updates.append("polished_prompt_single = :polished_prompt_single")
        params["polished_prompt_single"] = req["polished_prompt_single"]
    if req.get("image_url") is not None:
        updates.append("image_url = :image_url")
        params["image_url"] = req["image_url"]
    if "local_path" in req:
        updates.append("local_path = :local_path")
        params["local_path"] = req.get("local_path")
    if "extra_images" in req:
        updates.append("extra_images = :extra_images")
        params["extra_images"] = req.get("extra_images") or None
    if "ref_image" in req:
        updates.append("ref_image = :ref_image")
        params["ref_image"] = req.get("ref_image") or None

    if not updates:
        return True
    params["updated_at"] = timestamp()
    params["id"] = to_int_id(scene_id)
    db.execute(text(f"UPDATE scenes SET {', '.join(updates)}, updated_at = :updated_at WHERE id = :id"), params)
    log.info("Scene updated", extra={"scene_id": scene_id})
    return True


def update_scene_prompt(db: Session, scene_id, req: dict) -> bool:
    exists = db.execute(
        text("SELECT id FROM scenes WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(scene_id)}
    ).first()
    if not exists:
        return False
    db.execute(
        text("UPDATE scenes SET prompt = :prompt, updated_at = :now WHERE id = :id"),
        {"prompt": req["prompt"] if req.get("prompt") is not None else "", "now": timestamp(), "id": to_int_id(scene_id)},
    )
    log.info("Scene prompt updated", extra={"scene_id": scene_id})
    return True


def delete_scene(db: Session, scene_id) -> bool:
    res = db.execute(
        text("UPDATE scenes SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL"),
        {"now": timestamp(), "id": to_int_id(scene_id)},
    )
    if res.rowcount == 0:
        return False
    log.info("Scene deleted", extra={"scene_id": scene_id})
    return True


def build_scene_four_view_image_prompt(four_view_description: str, style_en: str, style_zh: str) -> str:
    image_layout_instruction = promptI18n.get_scene_generate_image_prompt()
    zh = (style_zh or "").strip()
    en = (style_en or "").strip()

    style_lines = []
    if zh:
        style_lines.append(f"【画风·最高优先级】四格统一：{zh}")
    if en and en != zh:
        style_lines.append(f"MANDATORY ART STYLE (all 4 panels): {en}.")
    elif en and not zh:
        style_lines.append(f"MANDATORY ART STYLE (all 4 panels): {en}.")
    style_header = f"{chr(10).join(style_lines)}\n\n" if style_lines else ""

    tail_parts = []
    if zh or en:
        tail_parts.append(f"Reiterate: same art style as above ({en or zh}). No people, no text.")
    tail = f"\n\n---\n\n{' '.join(tail_parts)}" if tail_parts else ""

    return f"{style_header}{image_layout_instruction}\n\n---\n\n{four_view_description}{tail}"


def build_scene_single_image_prompt(description: str, style_en: str, style_zh: str) -> str:
    image_layout_instruction = promptI18n.get_scene_generate_single_image_prompt()
    zh = (style_zh or "").strip()
    en = (style_en or "").strip()

    style_lines = []
    if zh:
        style_lines.append(f"【画风·最高优先级】{zh}")
    if en and en != zh:
        style_lines.append(f"MANDATORY ART STYLE: {en}.")
    elif en and not zh:
        style_lines.append(f"MANDATORY ART STYLE: {en}.")
    style_header = f"{chr(10).join(style_lines)}\n\n" if style_lines else ""

    tail_parts = []
    if zh or en:
        tail_parts.append(f"Reiterate: same art style as above ({en or zh}). No people, no text.")
    tail = f"\n\n---\n\n{' '.join(tail_parts)}" if tail_parts else ""

    return f"{style_header}{image_layout_instruction}\n\n---\n\n{description}{tail}"


def generate_scene_prompt_only(
    db: Session, log_, cfg: dict, scene_id, model_name: str | None = None, style: str | None = None
) -> dict:
    scene_row = db.execute(
        text("SELECT id, drama_id, location, time, prompt FROM scenes WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(scene_id)},
    ).mappings().first()
    if not scene_row:
        return {"ok": False, "error": "scene not found"}

    drama_full = db.execute(
        text("SELECT id, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
        {"id": scene_row["drama_id"]},
    ).mappings().first()
    merged_cfg = merge_cfg_style_with_drama(cfg, dict(drama_full) if drama_full else {})
    merged_cfg = apply_style_override_to_cfg(merged_cfg, style)

    location = (scene_row.get("location") or "").strip()
    time_str = (scene_row.get("time") or "").strip()
    raw_prompt = (scene_row.get("prompt") or "").strip()

    desc_lines = []
    if location:
        desc_lines.append(f"场景地点：{location}")
    if time_str:
        desc_lines.append(f"时间/时段：{time_str}")
    if raw_prompt:
        desc_lines.append(f"场景描述：{raw_prompt}")
    scene_desc = "\n".join(desc_lines) if desc_lines else (location or "未知场景")

    system_prompt = promptI18n.get_scene_polish_prompt(merged_cfg)
    user_prompt = f"请根据以下场景信息，生成四格场景参考图的提示词：\n\n{scene_desc}"

    log_.info("[场景提示词] Step1 开始生成四视图描述", extra={"scene_id": scene_id, "location": location, "time": time_str})

    try:
        four_view_description = aiClient.generate_text(
            db, log_, "text", user_prompt, system_prompt,
            {"model": model_name or None, "max_tokens": 4000},
        )
    except Exception as err:
        log_.error("[场景提示词] 文字AI失败", extra={"error": str(err)})
        return {"ok": False, "error": str(err)}

    if not four_view_description or not four_view_description.strip():
        return {"ok": False, "error": "AI返回内容为空"}

    style_dict = merged_cfg.get("style") or {}
    style_en = (style_dict.get("default_style_en") or style_dict.get("default_style") or "").strip()
    style_zh = (style_dict.get("default_style_zh") or "").strip()
    polished_prompt = build_scene_four_view_image_prompt(four_view_description.strip(), style_en, style_zh)

    now = timestamp()
    db.execute(
        text("UPDATE scenes SET polished_prompt = :p, updated_at = :u WHERE id = :id"),
        {"p": polished_prompt, "u": now, "id": to_int_id(scene_id)},
    )
    log_.info("[场景提示词] 生成并保存完成", extra={"scene_id": scene_id, "length": len(polished_prompt)})
    return {"ok": True, "polished_prompt": polished_prompt}


def generate_scene_single_prompt_only(
    db: Session, log_, cfg: dict, scene_id, model_name: str | None = None, style: str | None = None
) -> dict:
    scene_row = db.execute(
        text("SELECT id, drama_id, location, time, prompt FROM scenes WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(scene_id)},
    ).mappings().first()
    if not scene_row:
        return {"ok": False, "error": "scene not found"}

    drama_full = db.execute(
        text("SELECT id, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
        {"id": scene_row["drama_id"]},
    ).mappings().first()
    merged_cfg = merge_cfg_style_with_drama(cfg, dict(drama_full) if drama_full else {})
    merged_cfg = apply_style_override_to_cfg(merged_cfg, style)

    location = (scene_row.get("location") or "").strip()
    time_str = (scene_row.get("time") or "").strip()
    raw_prompt = (scene_row.get("prompt") or "").strip()

    desc_lines = []
    if location:
        desc_lines.append(f"场景地点：{location}")
    if time_str:
        desc_lines.append(f"时间/时段：{time_str}")
    if raw_prompt:
        desc_lines.append(f"场景描述：{raw_prompt}")
    scene_desc = "\n".join(desc_lines) if desc_lines else (location or "未知场景")

    system_prompt = promptI18n.get_scene_polish_prompt_single(merged_cfg)
    user_prompt = f"请根据以下场景信息，生成单图场景参考图的提示词：\n\n{scene_desc}"

    log_.info("[场景单图提示词] Step1 开始生成单图描述", extra={"scene_id": scene_id, "location": location, "time": time_str})

    try:
        single_view_description = aiClient.generate_text(
            db, log_, "text", user_prompt, system_prompt,
            {"model": model_name or None, "max_tokens": 4000},
        )
    except Exception as err:
        log_.error("[场景单图提示词] 文字AI失败", extra={"error": str(err)})
        return {"ok": False, "error": str(err)}

    if not single_view_description or not single_view_description.strip():
        return {"ok": False, "error": "AI返回内容为空"}

    style_dict = merged_cfg.get("style") or {}
    style_en = (style_dict.get("default_style_en") or style_dict.get("default_style") or "").strip()
    style_zh = (style_dict.get("default_style_zh") or "").strip()
    polished_prompt = build_scene_single_image_prompt(single_view_description.strip(), style_en, style_zh)

    now = timestamp()
    db.execute(
        text("UPDATE scenes SET polished_prompt_single = :p, updated_at = :u WHERE id = :id"),
        {"p": polished_prompt, "u": now, "id": to_int_id(scene_id)},
    )
    log_.info("[场景单图提示词] 生成并保存完成", extra={"scene_id": scene_id, "length": len(polished_prompt)})
    return {"ok": True, "polished_prompt_single": polished_prompt}


def generate_scene_four_view_image(
    db: Session, log_, cfg: dict, scene_id, model_name: str | None = None, style: str | None = None
) -> dict:
    scene_row = db.execute(
        text("SELECT id, drama_id, location, time, prompt, polished_prompt FROM scenes WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(scene_id)},
    ).mappings().first()
    if not scene_row:
        return {"ok": False, "error": "scene not found"}

    drama_full = db.execute(
        text("SELECT id, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
        {"id": scene_row["drama_id"]},
    ).mappings().first()
    if not drama_full:
        return {"ok": False, "error": "unauthorized"}

    merged_cfg = merge_cfg_style_with_drama(cfg, dict(drama_full))
    merged_cfg = apply_style_override_to_cfg(merged_cfg, style)

    if scene_row.get("polished_prompt") and str(scene_row["polished_prompt"]).strip():
        image_prompt = str(scene_row["polished_prompt"]).strip()
        log_.info("[场景四视图] 使用已保存的 polished_prompt，跳过文字AI", extra={"scene_id": scene_id})
    else:
        location = (scene_row.get("location") or "").strip()
        time_str = (scene_row.get("time") or "").strip()
        raw_prompt = (scene_row.get("prompt") or "").strip()
        desc_lines = []
        if location:
            desc_lines.append(f"场景地点：{location}")
        if time_str:
            desc_lines.append(f"时间/时段：{time_str}")
        if raw_prompt:
            desc_lines.append(f"场景描述：{raw_prompt}")
        input_text = "\n".join(desc_lines) if desc_lines else (location or "未知场景")

        system_prompt = promptI18n.get_scene_polish_prompt(merged_cfg)
        user_msg = f"请根据以下场景信息，生成四格场景参考图的提示词：\n\n{input_text}"

        log_.info("[场景四视图] Step1 开始生成提示词", extra={"scene_id": scene_id, "location": location, "time": time_str})

        try:
            four_view_description = aiClient.generate_text(
                db, log_, "text", user_msg, system_prompt,
                {"model": model_name or None, "max_tokens": 4000},
            )
        except Exception as err:
            log_.error("[场景四视图] Step1 文本AI失败，降级为直接使用场景描述", extra={"error": str(err)})
            four_view_description = input_text

        style_dict = merged_cfg.get("style") or {}
        style_en = (style_dict.get("default_style_en") or style_dict.get("default_style") or "").strip()
        style_zh = (style_dict.get("default_style_zh") or "").strip()
        image_prompt = build_scene_four_view_image_prompt(four_view_description, style_en, style_zh)

        try:
            db.execute(
                text("UPDATE scenes SET polished_prompt = :p, updated_at = :u WHERE id = :id"),
                {"p": image_prompt, "u": timestamp(), "id": to_int_id(scene_id)},
            )
        except Exception:
            pass

        log_.info("[场景四视图] Step1 完成，开始Step2生图", extra={"scene_id": scene_id})

    user_neg = imageClient.resolve_asset_user_negative_for_api(model_name, scene_row.get("negative_prompt")) if hasattr(imageClient, "resolve_asset_user_negative_for_api") else None
    image_gen = imageClient.create_and_generate_image(db, log_, {
        "drama_id": scene_row["drama_id"],
        "scene_id": scene_id,
        "prompt": image_prompt,
        "model": model_name or None,
        "size": "1792x1024",
        "quality": "standard",
        "provider": "openai",
        "user_negative_prompt": user_neg,
    })

    log_.info("[场景四视图] Step2 图片生成任务已提交", extra={"scene_id": scene_id, "image_gen_id": image_gen.get("id") if image_gen else None})
    return {"ok": True, "image_generation": image_gen}


def generate_scene_single_image(
    db: Session, log_, cfg: dict, scene_id, model_name: str | None = None, style: str | None = None
) -> dict:
    scene_row = db.execute(
        text("SELECT id, drama_id, location, time, prompt, polished_prompt, polished_prompt_single FROM scenes WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(scene_id)},
    ).mappings().first()
    if not scene_row:
        return {"ok": False, "error": "scene not found"}

    drama_full = db.execute(
        text("SELECT id, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
        {"id": scene_row["drama_id"]},
    ).mappings().first()
    if not drama_full:
        return {"ok": False, "error": "unauthorized"}

    merged_cfg = merge_cfg_style_with_drama(cfg, dict(drama_full))
    merged_cfg = apply_style_override_to_cfg(merged_cfg, style)

    if scene_row.get("polished_prompt_single") and str(scene_row["polished_prompt_single"]).strip():
        image_prompt = str(scene_row["polished_prompt_single"]).strip()
        log_.info("[场景单图] 使用已保存的 polished_prompt_single，跳过文字AI", extra={"scene_id": scene_id})
    else:
        location = (scene_row.get("location") or "").strip()
        time_str = (scene_row.get("time") or "").strip()
        raw_prompt = (scene_row.get("prompt") or "").strip()
        desc_lines = []
        if location:
            desc_lines.append(f"场景地点：{location}")
        if time_str:
            desc_lines.append(f"时间/时段：{time_str}")
        if raw_prompt:
            desc_lines.append(f"场景描述：{raw_prompt}")
        input_text = "\n".join(desc_lines) if desc_lines else (location or "未知场景")

        system_prompt = promptI18n.get_scene_polish_prompt_single(merged_cfg)
        user_msg = f"请根据以下场景信息，生成单图场景参考图的提示词：\n\n{input_text}"

        log_.info("[场景单图] Step1 开始生成提示词", extra={"scene_id": scene_id, "location": location, "time": time_str})

        try:
            single_view_description = aiClient.generate_text(
                db, log_, "text", user_msg, system_prompt,
                {"model": model_name or None, "max_tokens": 4000},
            )
        except Exception as err:
            log_.error("[场景单图] Step1 文本AI失败，降级为直接使用场景描述", extra={"error": str(err)})
            single_view_description = input_text

        style_dict = merged_cfg.get("style") or {}
        style_en = (style_dict.get("default_style_en") or style_dict.get("default_style") or "").strip()
        style_zh = (style_dict.get("default_style_zh") or "").strip()
        image_prompt = build_scene_single_image_prompt(single_view_description, style_en, style_zh)

        try:
            db.execute(
                text("UPDATE scenes SET polished_prompt_single = :p, updated_at = :u WHERE id = :id"),
                {"p": image_prompt, "u": timestamp(), "id": to_int_id(scene_id)},
            )
        except Exception:
            pass

        log_.info("[场景单图] Step1 完成，开始Step2生图", extra={"scene_id": scene_id})

    user_neg = imageClient.resolve_asset_user_negative_for_api(model_name, scene_row.get("negative_prompt")) if hasattr(imageClient, "resolve_asset_user_negative_for_api") else None
    image_gen = imageClient.create_and_generate_image(db, log_, {
        "drama_id": scene_row["drama_id"],
        "scene_id": scene_id,
        "prompt": image_prompt,
        "model": model_name or None,
        "size": "1792x1024",
        "quality": "standard",
        "provider": "openai",
        "user_negative_prompt": user_neg,
    })

    log_.info("[场景单图] Step2 图片生成任务已提交", extra={"scene_id": scene_id, "image_gen_id": image_gen.get("id") if image_gen else None})
    return {"ok": True, "image_generation": image_gen}


def extract_scene_from_image(db: Session, log_, cfg: dict, scene_id) -> dict:
    import re
    scene_row = db.execute(
        text("SELECT id, location, time, image_url, local_path, extra_images, ref_image FROM scenes WHERE id = :id AND deleted_at IS NULL"),
        {"id": to_int_id(scene_id)},
    ).mappings().first()
    if not scene_row:
        return {"ok": False, "error": "scene not found"}

    img_src = aiClient.resolve_entity_image_source(dict(scene_row), cfg)
    if not img_src:
        return {"ok": False, "error": "该场景暂无参考图片，请先上传图片"}

    location_label = " · ".join(filter(None, [scene_row.get("location"), scene_row.get("time")])) or "场景"
    prompts = aiClient.EXTRACT_PROMPTS.get("scene") or {}
    system_prompt = prompts.get("system") or ""
    user_fn = prompts.get("user")
    user_prompt = user_fn(location_label) if callable(user_fn) else f"这是场景{location_label}的参考图，请提取图中的场景视觉特征，生成可用于 AI 图生的场景描述文字。"

    try:
        prompt = aiClient.generate_text_with_vision(
            db, log_, "text", user_prompt, system_prompt, img_src, {"max_tokens": 2000}
        )
    except Exception as err:
        log_.error("[extractSceneFromImage] AI 调用失败", extra={"scene_id": scene_id, "error": str(err)})
        msg = str(err)
        if re.search(r"image|vision|visual|multimodal", msg, re.IGNORECASE):
            err_msg = f"AI 模型不支持图片识别，请在「AI 配置」中使用支持视觉的模型（如 GPT-4o、Gemini 1.5 等）【原始错误：{msg[:120]}】"
        else:
            err_msg = f"AI 分析失败：{msg}"
        return {"ok": False, "error": err_msg}

    now = timestamp()
    db.execute(
        text("UPDATE scenes SET prompt = :p, updated_at = :u WHERE id = :id"),
        {"p": prompt, "u": now, "id": to_int_id(scene_id)},
    )
    log_.info("[extractSceneFromImage] 场景描述提取成功", extra={"scene_id": scene_id, "prompt_len": len(prompt)})
    return {"ok": True, "prompt": prompt}


def create_scene_for_episode(db: Session, *args, **kwargs):
    """等价 Node createSceneForEpisode(db, log, dramaId, episodeId, req) 或 (db, drama_id, episode_id, req)。"""
    if len(args) == 4:
        # db, log, drama_id, episode_id, req (args has log, drama_id, episode_id, req)
        _, drama_id, episode_id, req = args
    elif len(args) == 3:
        # db, drama_id, episode_id, req
        drama_id, episode_id, req = args
    else:
        drama_id = kwargs.get("drama_id")
        episode_id = kwargs.get("episode_id")
        req = kwargs.get("req", {})
    return create_scene(db, drama_id, {**(req or {}), "episode_id": episode_id})


def delete_scenes_by_episode_id(db: Session, *args, **kwargs) -> int:
    """等价 Node deleteScenesByEpisodeId(db, log, episodeId)。"""
    if len(args) == 2:
        _, episode_id = args
    elif len(args) == 1:
        episode_id = args[0]
    else:
        episode_id = kwargs.get("episode_id")
    now = timestamp()
    try:
        res = db.execute(
            text("UPDATE scenes SET deleted_at = :now WHERE episode_id = :eid AND deleted_at IS NULL"),
            {"now": now, "eid": to_int_id(episode_id)},
        )
        db.commit()
        count = res.rowcount if hasattr(res, "rowcount") and res.rowcount is not None else 0
        log.info("Scenes deleted by episode", extra={"episode_id": episode_id, "count": count})
        return count
    except Exception as e:
        if "episode_id" in str(e):
            return 0
        raise e


def list_by_drama_id(db: Session, drama_id) -> list[dict]:
    rows = db.execute(
        text("SELECT * FROM scenes WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC"),
        {"did": to_int_id(drama_id)},
    ).mappings().all()
    return [dict(r) for r in rows]


# 驼峰别名与 Node 兼容
buildSceneFourViewImagePrompt = build_scene_four_view_image_prompt
buildSceneSingleImagePrompt = build_scene_single_image_prompt
generateScenePromptOnly = generate_scene_prompt_only
generateSceneSinglePromptOnly = generate_scene_single_prompt_only
generateSceneFourViewImage = generate_scene_four_view_image
generateSceneSingleImage = generate_scene_single_image
extractSceneFromImage = extract_scene_from_image
getSceneById = get_scene_by_id
createScene = create_scene
createSceneForEpisode = create_scene_for_episode
deleteScenesByEpisodeId = delete_scenes_by_episode_id
listByDramaId = list_by_drama_id
updateScene = update_scene
updateScenePrompt = update_scene_prompt
deleteScene = delete_scene
