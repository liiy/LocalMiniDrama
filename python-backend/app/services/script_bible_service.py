"""Script Bible Service: assembling and persisting Stage 2 story bible, characters, worldview, props, and music."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common import json_dumps, json_loads, now_iso
from app.repositories.character_repo import character_repo
from app.repositories.drama_repo import drama_repo
from app.repositories.scene_prop_repo import music_bible_repo, prop_repo


def parse_nine_dimensions(char_row: dict[str, Any], cached_9d: dict[str, Any]) -> dict[str, Any]:
    """解析并提取角色九维画像。"""
    mask = cached_9d.get("mask") or char_row.get("description") or ""
    true_self = cached_9d.get("true_self") or ""
    visual_anchor = (
        char_row.get("appearance")
        or char_row.get("identity_anchors")
        or cached_9d.get("visual_anchor")
        or ""
    )
    desire = cached_9d.get("desire") or ""
    weakness = cached_9d.get("weakness") or ""
    secret = cached_9d.get("secret") or ""
    fear = cached_9d.get("fear") or ""
    moral_line = cached_9d.get("moral_line") or ""
    arc = cached_9d.get("arc") or ""

    pers = char_row.get("personality") or ""
    if pers and "|" in pers:
        parts = [p.strip() for p in pers.split("|")]
        if len(parts) >= 1 and not desire:
            desire = parts[0]
        if len(parts) >= 2 and not true_self:
            true_self = parts[1]
        if len(parts) >= 3 and not weakness:
            weakness = parts[2].replace("缺陷:", "").replace("缺陷：", "").strip()

    return {
        "mask": mask,
        "true_self": true_self,
        "visual_anchor": visual_anchor,
        "desire": desire,
        "weakness": weakness,
        "secret": secret,
        "fear": fear,
        "moral_line": moral_line,
        "arc": arc,
    }


def assemble_bible_design(db: Session, drama_id: int, drama: dict[str, Any]) -> dict[str, Any]:
    """从数据库关联表真实查询并组装故事圣经、世界观、人物九维矩阵、关系网、道具库与配乐设计。"""
    meta = json_loads(drama.get("metadata") or "{}") or {}
    meta_bible = meta.get("bible_design") if isinstance(meta.get("bible_design"), dict) else {}

    # 1. 角色九维画像
    char_rows = character_repo.list_by_drama(db, drama_id)
    cached_chars = {
        c.get("name"): c
        for c in meta_bible.get("characters", [])
        if isinstance(c, dict) and c.get("name")
    }

    characters_list: list[dict[str, Any]] = []
    if char_rows:
        for idx, r in enumerate(char_rows, 1):
            c_name = r.get("name") or f"角色{idx}"
            cached = cached_chars.get(c_name, {})
            cached_9d = cached.get("nine_dimensions") if isinstance(cached.get("nine_dimensions"), dict) else {}

            voice_profile = (
                json_loads(r.get("voice_style"))
                if r.get("voice_style")
                else cached.get("voice_profile", {})
            )
            if not isinstance(voice_profile, dict):
                voice_profile = {"tone": str(voice_profile), "speed": "标准", "catchphrase": ""}

            error_chain = (
                json_loads(r.get("growth_chain"))
                if r.get("growth_chain")
                else (cached.get("error_belief_chain") or [])
            )
            curr_status = (
                json_loads(r.get("current_status"))
                if r.get("current_status")
                else (cached.get("current_status") or {})
            )
            stages_data = json_loads(r.get("stages")) if r.get("stages") else (cached.get("stages") or [])

            raw_role = r.get("role") or cached.get("role_type") or "supporter"
            role_tag = cached.get("role_tag") or raw_role

            characters_list.append({
                "id": cached.get("id") or f"C{r.get('id', idx):02d}",
                "name": c_name,
                "role_tag": role_tag,
                "role_type": cached.get("role_type") or raw_role,
                "avatar": cached.get("avatar") or "👤",
                "image_url": r.get("image_url") or cached.get("image_url") or "",
                "local_path": r.get("local_path") or cached.get("local_path") or "",
                "seed": cached.get("seed") or (r.get("id", idx) * 12345),
                "nine_dimensions": parse_nine_dimensions(r, cached_9d),
                "voice_profile": voice_profile,
                "error_belief_chain": error_chain,
                "stages": stages_data,
                "current_status": curr_status,
            })
    elif meta_bible.get("characters"):
        characters_list = meta_bible.get("characters") or []

    # 2. 道具库
    prop_rows = prop_repo.list_by_drama(db, drama_id)
    cached_props = {
        p.get("name"): p
        for p in meta_bible.get("props_library", {}).get("items", [])
        if isinstance(p, dict) and p.get("name")
    }

    props_items: list[dict[str, Any]] = []
    if prop_rows:
        for idx, p in enumerate(prop_rows, 1):
            p_name = p.get("name") or f"道具{idx}"
            cached_p = cached_props.get(p_name, {})
            tag = p.get("type") or cached_p.get("tag") or "核心道具"
            desc = p.get("description") or cached_p.get("desc") or ""
            vis_prompt = p.get("prompt") or p.get("appearance") or cached_p.get("visual_prompt") or ""
            fragments = cached_p.get("fragments") or []

            props_items.append({
                "id": cached_p.get("id") or f"P{p.get('id', idx):02d}",
                "name": p_name,
                "tag": tag,
                "desc": desc,
                "fragments": fragments,
                "visual_prompt": vis_prompt,
                "extract_candidate": vis_prompt or desc,
                "image_url": p.get("image_url") or "",
                "local_path": p.get("local_path") or "",
                "status": cached_p.get("status") or "accepted",
            })
    elif meta_bible.get("props_library", {}).get("items"):
        props_items = meta_bible.get("props_library", {}).get("items", [])

    props_library = {
        "stats": {
            "extracted_count": len(props_items),
            "total_props": len(props_items),
            "hit_fragments_count": sum(len(p.get("fragments") or []) for p in props_items),
        },
        "items": props_items,
    }

    # 3. 配乐设计
    music_row = music_bible_repo.get_latest_by_drama(db, drama_id)
    cached_music = meta_bible.get("music_bible") if isinstance(meta_bible.get("music_bible"), dict) else {}
    if music_row:
        music_bible = {
            "overall_style": music_row.get("overall_style") or cached_music.get("overall_style") or "",
            "bpm_rules": (
                music_row.get("bpm_range")
                or music_row.get("mixing_rules")
                or cached_music.get("bpm_rules")
                or ""
            ),
            "theme_prompt": music_row.get("theme_prompt") or "",
            "emotional_palette": music_row.get("emotional_palette") or "",
            "instruments": music_row.get("instruments") or "",
            "motifs": cached_music.get("motifs") or [],
        }
    elif cached_music:
        music_bible = cached_music
    else:
        music_bible = {
            "overall_style": "",
            "bpm_rules": "",
            "motifs": [],
        }

    # 4. 世界观设定
    wv_source = meta_bible.get("worldview") or meta.get("worldview") or {}
    worldview = {
        "era": wv_source.get("era") or wv_source.get("era_and_location") or "",
        "iron_rules": wv_source.get("iron_rules") or [],
        "social_hierarchy": wv_source.get("social_hierarchy") or {"layers": []},
        "core_conflict": wv_source.get("core_conflict") or {"title": "核心矛盾", "desc": ""},
        "primary_scenes": wv_source.get("primary_scenes") or [],
    }

    # 5. 人物关系网络图
    relationship_graph = (
        meta_bible.get("relationship_graph")
        or meta.get("relationship_graph")
        or meta.get("character_relationships")
        or {"timeline_nodes": [], "current_ep": "E01", "relations_by_ep": {}}
    )

    return {
        "hitl_passed": meta_bible.get("hitl_passed", True),
        "worldview": worldview,
        "characters": characters_list,
        "relationship_graph": relationship_graph,
        "props_library": props_library,
        "music_bible": music_bible,
    }


def save_bible_design(db: Session, drama_id: int, bible_design: dict[str, Any]) -> None:
    """持久化故事圣经、世界观、人物九维画像、道具库与配乐设计。"""
    drama = drama_repo.get_by_id(db, drama_id)
    if not drama:
        raise ValueError("短剧项目不存在")

    existing_meta = json_loads(drama.get("metadata") or "{}") or {}
    existing_meta["bible_design"] = bible_design

    # 同步更新 characters 表
    for char in bible_design.get("characters", []):
        c_name = char.get("name")
        if c_name:
            nine_dim = char.get("nine_dimensions", {})
            existing_c = character_repo.get_by_name(db, drama_id, c_name)
            if existing_c:
                db.execute(
                    text("""
                        UPDATE characters
                        SET role = :role, description = :description, appearance = :appearance,
                            identity_anchors = :identity_anchors, updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "role": char.get("role_type", "主要角色"),
                        "description": nine_dim.get("mask", ""),
                        "appearance": nine_dim.get("visual_anchor", ""),
                        "identity_anchors": nine_dim.get("visual_anchor", ""),
                        "now": now_iso(),
                        "id": existing_c["id"],
                    },
                )

    # 同步更新 props 道具表
    for p_item in bible_design.get("props_library", {}).get("items", []):
        p_name = p_item.get("name")
        if p_name:
            existing_p = db.execute(
                text("SELECT id FROM props WHERE drama_id = :did AND name = :name"),
                {"did": drama_id, "name": p_name},
            ).first()
            if not existing_p:
                db.execute(
                    text("""
                        INSERT INTO props (drama_id, name, description, prompt, created_at, updated_at)
                        VALUES (:did, :name, :desc, :prompt, :now, :now)
                    """),
                    {
                        "did": drama_id,
                        "name": p_name,
                        "desc": p_item.get("desc", ""),
                        "prompt": p_item.get("visual_prompt", ""),
                        "now": now_iso(),
                    },
                )

    # 同步更新 music_bibles 配乐表
    music_data = bible_design.get("music_bible", {})
    if music_data:
        existing_mb = music_bible_repo.get_latest_by_drama(db, drama_id)
        if existing_mb:
            db.execute(
                text("""
                    UPDATE music_bibles
                    SET overall_style = :overall_style, bpm_range = :bpm_range, updated_at = :now
                    WHERE id = :id
                """),
                {
                    "overall_style": music_data.get("overall_style", ""),
                    "bpm_range": music_data.get("bpm_rules", ""),
                    "now": now_iso(),
                    "id": existing_mb["id"],
                },
            )
        else:
            db.execute(
                text("""
                    INSERT INTO music_bibles (drama_id, overall_style, bpm_range, status, created_at, updated_at)
                    VALUES (:did, :overall_style, :bpm_range, 'draft', :now, :now)
                """),
                {
                    "did": drama_id,
                    "overall_style": music_data.get("overall_style", ""),
                    "bpm_range": music_data.get("bpm_rules", ""),
                    "now": now_iso(),
                },
            )

    db.execute(
        text("UPDATE dramas SET metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"metadata": json_dumps(existing_meta), "now": now_iso(), "id": drama_id},
    )
    db.commit()
