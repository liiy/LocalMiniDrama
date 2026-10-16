"""道具实体（props 表）操作，等价 Node services/propService.js 的 CRUD 部分。

P2 只翻译：listByDramaId / create / getById / update / deleteById / associateWithStoryboard。
AI 生成（generatePropPromptOnly 等）留到 P4。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import timestamp

log = get_logger("lmd.prop")


def to_int_id(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def _row_to_prop(r: dict) -> dict:
    return {
        "id": r["id"],
        "drama_id": r["drama_id"],
        "name": r["name"],
        "type": r["type"],
        "description": r["description"],
        "prompt": r["prompt"],
        "negative_prompt": r["negative_prompt"] or None,
        "image_url": r["image_url"],
        "local_path": r["local_path"],
        "extra_images": r["extra_images"] or None,
        "ref_image": r["ref_image"] or None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def list_by_drama_id(db: Session, drama_id) -> list[dict]:
    rows = db.execute(
        text("SELECT * FROM props WHERE drama_id = :did AND deleted_at IS NULL ORDER BY id ASC"),
        {"did": to_int_id(drama_id)},
    ).mappings().all()
    return [_row_to_prop(dict(r)) for r in rows]


def get_by_id(db: Session, prop_id):
    r = db.execute(
        text("SELECT * FROM props WHERE id = :id AND deleted_at IS NULL"), {"id": to_int_id(prop_id)}
    ).mappings().first()
    return _row_to_prop(dict(r)) if r else None


def create(db: Session, req: dict):
    now = timestamp()
    episode_id = to_int_id(req["episode_id"]) if req.get("episode_id") is not None else None
    res = db.execute(
        text(
            """
            INSERT INTO props (drama_id, episode_id, name, type, description, prompt, negative_prompt,
                image_url, local_path, created_at, updated_at)
            VALUES (:drama_id, :episode_id, :name, :type, :description, :prompt, :negative_prompt,
                :image_url, :local_path, :created_at, :updated_at)
            """
        ),
        {
            "drama_id": req.get("drama_id"),
            "episode_id": episode_id,
            "name": req.get("name") or "",
            "type": req.get("type"),
            "description": req.get("description"),
            "prompt": req.get("prompt"),
            "negative_prompt": req.get("negative_prompt"),
            "image_url": req.get("image_url"),
            "local_path": req.get("local_path"),
            "created_at": now,
            "updated_at": now,
        },
    )
    log.info("Prop created", extra={"prop_id": res.lastrowid})
    return get_by_id(db, res.lastrowid)


def update(db: Session, prop_id, req: dict):
    existing = get_by_id(db, prop_id)
    if not existing:
        return None
    sets: list[str] = []
    params: dict = {}
    if req.get("name") is not None:
        sets.append("name = :name")
        params["name"] = req["name"]
    if req.get("type") is not None:
        sets.append("type = :type")
        params["type"] = req["type"]
    if req.get("description") is not None:
        sets.append("description = :description")
        params["description"] = req["description"]
    if req.get("prompt") is not None:
        sets.append("prompt = :prompt")
        params["prompt"] = req["prompt"]
    if "negative_prompt" in req:
        sets.append("negative_prompt = :negative_prompt")
        params["negative_prompt"] = req.get("negative_prompt")
    if req.get("image_url") is not None:
        sets.append("image_url = :image_url")
        params["image_url"] = req["image_url"]
    if "local_path" in req:
        sets.append("local_path = :local_path")
        params["local_path"] = req.get("local_path") or None
    if "extra_images" in req:
        sets.append("extra_images = :extra_images")
        params["extra_images"] = req.get("extra_images") or None
    if "ref_image" in req:
        sets.append("ref_image = :ref_image")
        params["ref_image"] = req.get("ref_image") or None

    if not sets:
        return existing
    params["updated_at"] = timestamp()
    params["id"] = to_int_id(prop_id)
    db.execute(text(f"UPDATE props SET {', '.join(sets)}, updated_at = :updated_at WHERE id = :id"), params)
    log.info("Prop updated", extra={"prop_id": prop_id})
    return get_by_id(db, prop_id)


def delete_by_id(db: Session, prop_id) -> bool:
    res = db.execute(
        text("UPDATE props SET deleted_at = :now WHERE id = :id AND deleted_at IS NULL"),
        {"now": timestamp(), "id": to_int_id(prop_id)},
    )
    if res.rowcount == 0:
        return False
    log.info("Prop deleted", extra={"prop_id": prop_id})
    return True


def associate_with_storyboard(db: Session, storyboard_id, prop_ids: list) -> None:
    """等价 propService.associateWithStoryboard：全量替换关联。"""
    sid = to_int_id(storyboard_id)
    db.execute(text("DELETE FROM storyboard_props WHERE storyboard_id = :sid"), {"sid": sid})
    if not isinstance(prop_ids, list):
        prop_ids = []
    bind = getattr(db, "bind", None) or (db.get_bind() if hasattr(db, "get_bind") else None)
    is_sqlite = bool(bind and getattr(bind.dialect, "name", "") == "sqlite")
    sql = (
        "INSERT OR IGNORE INTO storyboard_props (storyboard_id, prop_id) VALUES (:sid, :pid)"
        if is_sqlite
        else "INSERT IGNORE INTO storyboard_props (storyboard_id, prop_id) VALUES (:sid, :pid)"
    )
    for pid in prop_ids:
        db.execute(
            text(sql),
            {"sid": sid, "pid": to_int_id(pid)},
        )


def soft_delete_props_by_episode_id(db: Session, log, episode_id) -> int:
    """软删除本集「从剧本提取」写入的道具（props.episode_id），避免再次提取时与旧数据累加。"""
    now = timestamp()
    try:
        res = db.execute(
            text("UPDATE props SET deleted_at = :now WHERE episode_id = :eid AND deleted_at IS NULL"),
            {"now": now, "eid": to_int_id(episode_id)},
        )
        count = res.rowcount if res.rowcount is not None else 0
        log.info("Props soft-deleted by episode", extra={"episode_id": episode_id, "count": count})
        return count
    except Exception as e:
        if "episode_id" in str(e):
            return 0
        raise


def generate_prop_prompt_only(
    db: Session, log, cfg: dict, prop_id, model_name: str | None = None, style: str | None = None
) -> dict:
    """用文字 AI 生成道具图片提示词并保存到 props.prompt。"""
    from app.services import aiClient, promptI18n
    from app.utils.dramaStyleMerge import apply_style_override_to_cfg, merge_cfg_style_with_drama

    prop = get_by_id(db, prop_id)
    if not prop:
        return {"ok": False, "error": "prop not found"}

    drama_row = None
    if prop.get("drama_id"):
        drama_row = db.execute(
            text("SELECT style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL"),
            {"id": to_int_id(prop["drama_id"])},
        ).mappings().first()

    polish_cfg = merge_cfg_style_with_drama(cfg, dict(drama_row) if drama_row else {})
    so = str(style or "").strip()
    if so:
        polish_cfg = apply_style_override_to_cfg(polish_cfg, so)

    desc_parts = []
    if prop.get("name"):
        desc_parts.append(f"道具名称：{prop['name']}")
    if prop.get("type"):
        desc_parts.append(f"道具类型：{prop['type']}")
    if prop.get("description"):
        desc_parts.append(f"道具描述：{prop['description']}")
    desc_text = "\n".join(desc_parts) if desc_parts else (prop.get("name") or "")

    system_prompt = promptI18n.get_prop_polish_prompt(polish_cfg)
    user_prompt = (
        "请为以下道具生成**一段英文**图片提示词。\n"
        "**约束**：最终英文中不得出现人名、地名、组织名、台词或任何剧本专有信息"
        "（若下列「道具名称/描述」中含此类词，请改写为泛化物体描述）；"
        "只写已给出的可见外观信息，不要扩写未提及的细节。\n\n"
        f"{desc_text}"
    )

    log.info("[道具提示词] 开始生成", extra={"prop_id": prop_id, "prop_name": prop.get("name")})

    try:
        generated_prompt = aiClient.generate_text(
            db,
            log,
            "text",
            user_prompt,
            system_prompt,
            {
                "scene_key": "prop_image_polish",
                "model": model_name or None,
                "max_tokens": 800,
            },
        )
    except Exception as err:
        log.error("[道具提示词] 文字AI失败", extra={"error": str(err)})
        return {"ok": False, "error": str(err)}

    if generated_prompt and str(generated_prompt).strip():
        final_prompt = str(generated_prompt).strip()
        now = timestamp()
        db.execute(
            text("UPDATE props SET prompt = :prompt, updated_at = :now WHERE id = :id"),
            {"prompt": final_prompt, "now": now, "id": to_int_id(prop_id)},
        )
        log.info("[道具提示词] 生成并保存完成", extra={"prop_id": prop_id, "length": len(final_prompt)})
        return {"ok": True, "prompt": final_prompt}

    return {"ok": False, "error": "AI返回内容为空"}


def extract_prop_from_image(db: Session, log, cfg: dict, prop_id) -> dict:
    """从道具现有图片中反向提取外观描述，更新 description 字段。"""
    import re

    from app.services import aiClient

    prop = db.execute(
        text(
            "SELECT id, name, type, image_url, local_path, extra_images, ref_image "
            "FROM props WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": to_int_id(prop_id)},
    ).mappings().first()
    if not prop:
        return {"ok": False, "error": "prop not found"}

    prop_dict = dict(prop)
    img_src = aiClient.resolve_entity_image_source(prop_dict, cfg)
    if not img_src:
        return {"ok": False, "error": "该道具暂无参考图片，请先上传图片"}

    prop_label = prop_dict.get("name") or "道具"
    extract_cfg = aiClient.EXTRACT_PROMPTS.get("prop") or {}
    system_prompt = extract_cfg.get("system") or ""
    user_fn = extract_cfg.get("user")
    user_prompt = user_fn(prop_label) if callable(user_fn) else f"请根据图片详细描述这个道具的外观特征：{prop_label}"

    try:
        description = aiClient.generate_text_with_vision(
            db,
            log,
            "text",
            user_prompt,
            system_prompt,
            img_src,
            {"max_tokens": 2000},
        )
    except Exception as err:
        err_msg = str(err)
        log.error("[extractPropFromImage] AI 调用失败", extra={"propId": prop_id, "error": err_msg})
        if re.search(r"image|vision|visual|multimodal", err_msg, re.IGNORECASE):
            final_err = (
                f"AI 模型不支持图片识别，请在「AI 配置」中使用支持视觉的模型"
                f"（如 GPT-4o、Gemini 1.5 等）【原始错误：{err_msg[:120]}】"
            )
        else:
            final_err = f"AI 分析失败：{err_msg}"
        return {"ok": False, "error": final_err}

    desc_str = str(description or "").strip()
    now = timestamp()
    db.execute(
        text("UPDATE props SET description = :desc, updated_at = :now WHERE id = :id"),
        {"desc": desc_str, "now": now, "id": to_int_id(prop_id)},
    )
    log.info("[extractPropFromImage] 道具描述提取成功", extra={"propId": prop_id, "description_len": len(desc_str)})
    return {"ok": True, "description": desc_str}


# 驼峰别名与 Node 兼容
listByDramaId = list_by_drama_id
getById = get_by_id
deleteById = delete_by_id
softDeletePropsByEpisodeId = soft_delete_props_by_episode_id
associateWithStoryboard = associate_with_storyboard
generatePropPromptOnly = generate_prop_prompt_only
extractPropFromImage = extract_prop_from_image

