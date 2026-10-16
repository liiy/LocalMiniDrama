"""即梦/Seedance2 素材认证守卫（等价 Node utils/seedance2AssetGuards.js）。

角色主图/音色发生漂移时，把已认证资产标记为 stale；若换回已认证版本则恢复 active。
"""
from __future__ import annotations

import json

from sqlalchemy import text

from app.core.response import timestamp


def normalize_storage_rel_path(p) -> str:
    s = str(p or "").strip().lstrip("/\\").split("?")[0]
    s = s.replace("\\", "/").rstrip("/")
    return s


def norm_image_url_key(u) -> str:
    return str(u or "").strip().split("?")[0]


def parse_seedance2_asset(val):
    if val is None or val == "":
        return None
    try:
        return json.loads(val) if isinstance(val, str) else val
    except Exception:
        return None


def norm_asset_status(raw) -> str:
    return str(raw or "").strip().lower()


def mark_stale_on_character_main_image_drift(db, log, prev_row: dict, next_patch: dict) -> None:
    """等价 Node markStaleOnCharacterMainImageDrift。"""
    if not db or not prev_row or not prev_row.get("id"):
        return
    # 注意：Node 用键存在性（'x' in nextPatch）判断，显式传 null 也走新值分支
    next_lp = normalize_storage_rel_path(
        next_patch["local_path"] if "local_path" in next_patch else (prev_row.get("local_path") or "")
    )
    next_img = norm_image_url_key(
        next_patch["image_url"] if "image_url" in next_patch else (prev_row.get("image_url") or "")
    )
    old_lp = normalize_storage_rel_path(prev_row.get("local_path") or "")
    old_img = norm_image_url_key(prev_row.get("image_url") or "")
    if old_lp == next_lp and old_img == next_img:
        return

    asset = parse_seedance2_asset(prev_row.get("seedance2_asset"))
    if not asset:
        return

    status = norm_asset_status(asset.get("status"))
    now = timestamp()

    if status == "stale":
        cert_lp = normalize_storage_rel_path(asset.get("certified_local_path") or "")
        cert_img = norm_image_url_key(asset.get("certified_image_url") or "")
        lp_hit = bool(cert_lp and next_lp and cert_lp == next_lp)
        img_hit = bool(cert_img and next_img and cert_img == next_img)
        if lp_hit or img_hit:
            merged = {
                **asset,
                "status": "active",
                "stale_reason": None,
                "updated_at": now,
                "restored_from_stale_at": now,
            }
            try:
                db.execute(
                    text("UPDATE characters SET seedance2_asset = :asset, updated_at = :now WHERE id = :id"),
                    {"asset": json.dumps(merged), "now": now, "id": int(prev_row["id"])},
                )
            except Exception:
                pass
        return

    if status != "active":
        return

    merged = {
        **asset,
        "status": "stale",
        "stale_reason": "character_main_image_changed",
        "updated_at": now,
    }
    db.execute(
        text("UPDATE characters SET seedance2_asset = :asset, updated_at = :now WHERE id = :id"),
        {"asset": json.dumps(merged), "now": now, "id": int(prev_row["id"])},
    )
    if log:
        log.info("[SD2认证] 角色主图已变更，状态标记为 stale", extra={"character_id": prev_row["id"]})


def mark_stale_on_character_voice_drift(db, log, prev_row: dict, next_patch: dict) -> None:
    """等价 Node markStaleOnCharacterVoiceDrift。"""
    if not db or not prev_row or not prev_row.get("id"):
        return
    next_voice = normalize_storage_rel_path(
        next_patch["seedance2_voice_local_path"]
        if "seedance2_voice_local_path" in next_patch
        else (prev_row.get("seedance2_voice_local_path") or "")
    )
    old_voice = normalize_storage_rel_path(prev_row.get("seedance2_voice_local_path") or "")
    if old_voice == next_voice:
        return

    asset = parse_seedance2_asset(prev_row.get("seedance2_voice_asset"))
    if not asset:
        return

    status = norm_asset_status(asset.get("status"))
    now = timestamp()

    if status == "stale":
        cert_voice = normalize_storage_rel_path(asset.get("certified_local_path") or "")
        if cert_voice and next_voice and cert_voice == next_voice:
            merged = {
                **asset,
                "status": "active",
                "stale_reason": None,
                "updated_at": now,
                "restored_from_stale_at": now,
            }
            try:
                db.execute(
                    text("UPDATE characters SET seedance2_voice_asset = :asset, updated_at = :now WHERE id = :id"),
                    {"asset": json.dumps(merged), "now": now, "id": int(prev_row["id"])},
                )
            except Exception:
                pass
        return

    if status != "active":
        return

    merged = {**asset, "status": "stale", "stale_reason": "character_voice_changed", "updated_at": now}
    db.execute(
        text("UPDATE characters SET seedance2_voice_asset = :asset, updated_at = :now WHERE id = :id"),
        {"asset": json.dumps(merged), "now": now, "id": int(prev_row["id"])},
    )
    if log:
        log.info("[SD2认证] 角色语音参考已变更，状态标记为 stale", extra={"character_id": prev_row["id"]})
