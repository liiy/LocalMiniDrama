from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.platform_common import now_iso
from app.tools.screenplay_feature_scanner import is_valid_character_speaker
from app.tools.shot_duration_calculator import clean_dialogue_text
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer
from app.schemas.script_graph_state import (
    AudioBible,
    CandidateTitleMatrix,
    CharacterAnchorStub,
    DoubleTrackProhibitions,
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    InterEpisodePhysicalContinuity,
    LiteraryScreenplayEpisodeModel,
    PropAnchorStub,
    RedBlueAuditReport,
    SceneAnchorStub,
    SeasonOutlineCard,
    StoryboardShot,
    StoryboardShotStub,
)
from app.workflows.adapters.stage_adapters.common import (
    _safe_json_loads,
    _ensure_valid_json_str,
    _dump_or_dict,
    _flatten_asset_collection,
    _get_table_columns,
    sync_stage_memories_to_vector_db,
    persist_audit_report,
    fetch_all,
    fetch_one,
    get_short_memories,
    publish_drama_event,
    publish_drama_read_projection,
    publish_episode_read_projection,
    set_short_memories,
)

log = get_logger("lmd.storage_adapter")

def _normalize_asset_lookup_token(raw_token: Any) -> str:
    """将资产引用字符串归一化为无特殊符号的大写检索 Token。"""
    if raw_token is None:
        return ""
    s = str(raw_token).strip().upper()
    return re.sub(r"[^A-Z0-9\u4e00-\u9fa5_]", "", s)


_GENERIC_ASSET_SEGMENTS = {
    "CHAR", "PROP", "ENV", "SCENE", "VOICE", "SFX", "BGM", "AUDIO",
    "T1", "T2", "T3", "S0", "S1", "S2", "S3", "Z01", "Z02", "Z03",
    "BASE", "PORTRAIT", "STATIC", "ACTION", "WIDE", "MACRO", "FRONT", "4V",
}


def _extract_core_asset_prefixes(token: str) -> list[str]:
    """从四段式资产 ID（如 CHAR_LUCHEN_T1_BASE_PORTRAIT）提取候选匹配前缀与核心 Token。"""
    norm = _normalize_asset_lookup_token(token)
    if not norm:
        return []
    candidates = [norm]
    parts = [p for p in norm.split("_") if p]
    if len(parts) >= 2 and parts[0] in ("CHAR", "ENV", "SCENE", "PROP"):
        # 例如 CHAR_LUCHEN、ENV_WAREHOUSE、PROP_JADE
        prefix_two = f"{parts[0]}_{parts[1]}"
        if prefix_two not in candidates:
            candidates.append(prefix_two)
        # 若存在复合英文名（如 PROP_BRONZE_KEY_T1_STATIC -> PROP_BRONZE_KEY / BRONZE_KEY）
        core_segs: list[str] = []
        for seg in parts[1:]:
            if seg in _GENERIC_ASSET_SEGMENTS or re.match(r"^[TSZ]\d+$", seg):
                break
            core_segs.append(seg)
        if len(core_segs) >= 2:
            compound_tok = "_".join(core_segs)
            compound_pref = f"{parts[0]}_{compound_tok}"
            if compound_pref not in candidates:
                candidates.append(compound_pref)
            if compound_tok not in candidates:
                candidates.append(compound_tok)
        if parts[1] not in candidates and not parts[1].isdigit():
            candidates.append(parts[1])
        # 若前缀为 SCENE_xxx，同时兼容 ENV_xxx
        if parts[0] == "SCENE":
            env_alias = f"ENV_{parts[1]}"
            if env_alias not in candidates:
                candidates.append(env_alias)
        elif parts[0] == "ENV":
            scene_alias = f"SCENE_{parts[1]}"
            if scene_alias not in candidates:
                candidates.append(scene_alias)
    return candidates


def _load_stage6_asset_lookup_maps(
    db: Session,
    drama_id: int,
    episode_id: int | None = None,
) -> dict[str, Any]:
    """加载 Stage 6 权威资产真值表映射字典（scenes / characters / props 三级体系 + voice_profiles）。

    【核心职责与三级实体穿透规范】
    1. 严格限定 `WHERE drama_id = :drama_id AND deleted_at IS NULL`，杜绝跨剧本资产串库污染。
    2. 场景三级映射 (Tier 1: scenes -> Tier 2: scene_zones -> Tier 3: scene_weathering_views):
       - 支持反解出 scene_id, scene_zone_id, scene_weathering_view_id，以及场景全景资产 Token。
    3. 角色三级映射 (Tier 1: characters & character_libraries -> Tier 2: character_stages -> Tier 3: character_stage_views):
       - 同时支持通过人物名、阶段 Code (如 T1_BASE)、三级切片 Key (如 CHAR_LUCHEN_T1_4V_FRONT) 精准反解出
         character_id, character_lib_id, character_stage_id, stage_view_id。
    4. 道具三级映射 (Tier 1: props -> Tier 2: prop_damage_states -> Tier 3: prop_detail_views):
       - 支持通过道具名、破坏状态 Code (如 S1_CRACKED)、三级微距切片 Key (如 PROP_JADE_S1_ACTION) 精准反解出
         prop_id, damage_state_id, prop_detail_view_id。
    5. 角色母音档案映射：加载 character_voice_profiles，供 storyboard_audios 自动绑定 voice_profile_id。
    """
    scene_map: dict[str, dict[str, Any]] = {}
    char_map: dict[str, dict[str, Any]] = {}
    prop_map: dict[str, dict[str, Any]] = {}
    voice_by_char_id: dict[int, dict[str, Any]] = {}
    scene_by_id: dict[int, dict[str, Any]] = {}
    char_by_id: dict[int, dict[str, Any]] = {}
    char_by_lib_id: dict[int, dict[str, Any]] = {}
    prop_by_id: dict[int, dict[str, Any]] = {}
    default_scene: dict[str, Any] | None = None

    now = now_iso()
    log.debug("【Stage7资产字典】开始加载 drama_id=%s (episode_id=%s) 三级资产映射树...", drama_id, episode_id)

    # 1. 加载 scenes 主表 (Tier-1) + scene_zones 二级表 (Tier-2) + scene_weathering_views 三级切片表 (Tier-3)
    try:
        scene_rows = fetch_all(
            db,
            "SELECT * FROM scenes WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 scenes 表异常（可能处于 Mock 环境）: %s", exc)
        scene_rows = []

    for r in scene_rows or []:
        if not isinstance(r, dict) or not isinstance(r.get("id"), int):
            continue
        sid = int(r["id"])
        loc = str(r.get("location") or "").strip()
        s_time = str(r.get("time") or "").strip()
        s_code = str(r.get("scene_code") or f"ENV_{sid}").strip()
        b_key = str(r.get("benchmark_asset_key") or s_code).strip()
        s_info = {
            "scene_id": sid,
            "scene_zone_id": None,
            "scene_weathering_view_id": None,
            "location": loc,
            "time": s_time,
            "scene_code": s_code,
            "benchmark_asset_key": b_key,
            "episode_id": r.get("episode_id"),
        }
        scene_by_id[sid] = s_info
        if default_scene is None:
            default_scene = s_info
        elif episode_id is not None and r.get("episode_id") == episode_id:
            default_scene = s_info

        loc_tok = AssetProtocolHelper.chinese_to_token(loc) if loc else ""
        raw_scene_keys = [str(sid), f"ENV_{sid}", f"SCENE_{sid}", s_code, b_key, loc, f"{loc}_{s_time}"]
        if loc_tok:
            raw_scene_keys.extend([loc_tok, f"ENV_{loc_tok}", f"SCENE_{loc_tok}"])
        for raw_k in raw_scene_keys:
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    scene_map.setdefault(cand, s_info)

    # 级联加载 scene_zones 二级子空间与 scene_weathering_views 三级做旧切片
    try:
        sz_rows = fetch_all(
            db,
            """
            SELECT sz.id AS zone_id, sz.scene_id, sz.zone_code, sz.zone_name,
                   swv.id AS view_id, swv.asset_key AS view_asset_key, swv.layer_type
            FROM scene_zones sz
            LEFT JOIN scene_weathering_views swv ON swv.scene_zone_id = sz.id AND swv.deleted_at IS NULL
            WHERE sz.drama_id = :drama_id AND sz.deleted_at IS NULL
            ORDER BY sz.id ASC, swv.is_benchmark DESC, swv.is_primary DESC, swv.id ASC
            """,
            {"drama_id": drama_id},
        )
        for szr in sz_rows or []:
            if not isinstance(szr, dict):
                continue
            sid = szr.get("scene_id")
            zid = szr.get("zone_id")
            vid = szr.get("view_id")
            if isinstance(sid, int) and sid in scene_by_id:
                base_s_info = scene_by_id[sid]
                # 构造包含二级与三级切片外键的精细场景字典
                refined_s_info = {
                    **base_s_info,
                    "scene_zone_id": int(zid) if isinstance(zid, int) else None,
                    "scene_weathering_view_id": int(vid) if isinstance(vid, int) else None,
                    "benchmark_asset_key": str(szr.get("view_asset_key") or base_s_info.get("benchmark_asset_key") or ""),
                }
                # 如果主表还未确定二级 zone，默认由首个 zone_id 回填
                if base_s_info.get("scene_zone_id") is None and isinstance(zid, int):
                    base_s_info["scene_zone_id"] = zid

                for rk in (szr.get("zone_code"), szr.get("zone_name"), szr.get("view_asset_key")):
                    if rk:
                        for cand in _extract_core_asset_prefixes(str(rk)):
                            if cand:
                                scene_map.setdefault(cand, refined_s_info)
    except Exception as exc:
        log.debug("【Stage7资产字典】加载 scene_zones / scene_weathering_views 异常: %s", exc)

    # 2. 加载 character_libraries 与 characters 表，确保严格对齐本剧 characters.id
    lib_by_source_id: dict[int, int] = {}
    lib_by_name: dict[str, int] = {}
    try:
        lib_rows = fetch_all(
            db,
            "SELECT * FROM character_libraries WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception:
        lib_rows = []

    for lr in lib_rows or []:
        if not isinstance(lr, dict) or not isinstance(lr.get("id"), int):
            continue
        lid = int(lr["id"])
        lname = str(lr.get("name") or "").strip()
        raw_src_id = lr.get("source_id")
        parsed_src_id: int | None = None
        if isinstance(raw_src_id, int):
            parsed_src_id = raw_src_id
        elif isinstance(raw_src_id, str) and raw_src_id.strip().isdigit():
            parsed_src_id = int(raw_src_id.strip())
        if parsed_src_id is not None and parsed_src_id > 0:
            lib_by_source_id[parsed_src_id] = lid
        if lname:
            lib_by_name[lname.upper()] = lid

        effective_char_id = parsed_src_id if (parsed_src_id is not None and parsed_src_id > 0) else lid
        c_tok = AssetProtocolHelper.chinese_to_token(lname) if lname else f"{effective_char_id}"
        c_info = {
            "character_lib_id": lid,
            "character_id": effective_char_id,
            "character_stage_id": None,
            "stage_view_id": None,
            "name": lname or f"CHAR_{effective_char_id}",
            "character_code": f"CHAR_{c_tok}",
            "benchmark_asset_key": f"CHAR_{c_tok}_T1_BASE_PORTRAIT",
        }
        char_by_lib_id[lid] = c_info
        char_by_id.setdefault(effective_char_id, c_info)
        for raw_k in (str(lid), str(effective_char_id), f"CHAR_{lid}", f"CHAR_{effective_char_id}", f"CHAR_{c_tok}", lname):
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    char_map.setdefault(cand, c_info)

    try:
        char_rows = fetch_all(
            db,
            "SELECT * FROM characters WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 characters 表异常（可能处于 Mock 环境）: %s", exc)
        char_rows = []

    for cr in char_rows or []:
        if not isinstance(cr, dict) or not isinstance(cr.get("id"), int):
            continue
        cid = int(cr["id"])
        cname = str(cr.get("name") or f"CHAR_{cid}").strip()
        ccode = str(cr.get("character_code") or f"CHAR_{cid}").strip()
        b_key = str(cr.get("benchmark_asset_key") or ccode).strip()
        cn_tok = AssetProtocolHelper.chinese_to_token(cname) if cname else ""

        # 查找或自动同步创建对应的 character_libraries 记录（兼容旧表关联与双 ID 对齐）
        lib_id = lib_by_source_id.get(cid) or lib_by_name.get(cname.upper())
        if lib_id is None:
            try:
                ins_lib = db.execute(
                    text("""
                        INSERT INTO character_libraries (
                            drama_id, name, description, appearance,
                            source_type, source_id, created_at, updated_at
                        ) VALUES (
                            :drama_id, :name, :description, :appearance,
                            'stage6_character', :source_id, :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "name": cname,
                        "description": str(cr.get("description") or cr.get("personality") or ""),
                        "appearance": str(cr.get("appearance") or ""),
                        "source_id": str(cid),
                        "now": str(now),
                    },
                )
                raw_lid = getattr(ins_lib, "lastrowid", None)
                if isinstance(raw_lid, int) and raw_lid > 0:
                    lib_id = raw_lid
                    lib_by_source_id[cid] = lib_id
                    lib_by_name[cname.upper()] = lib_id
            except Exception as exc:
                log.debug("【Stage7资产字典】自动补齐 character_libraries 失败，回退使用 characters.id=%s: %s", cid, exc)
        if not isinstance(lib_id, int) or lib_id <= 0:
            lib_id = cid

        c_info = {
            "character_lib_id": lib_id,
            "character_id": cid,
            "character_stage_id": None,
            "stage_view_id": None,
            "name": cname,
            "character_code": ccode,
            "benchmark_asset_key": b_key,
        }
        char_by_id[cid] = c_info
        char_by_lib_id[lib_id] = c_info
        char_by_lib_id.setdefault(cid, c_info)

        raw_char_keys = [str(cid), str(lib_id), f"CHAR_{cid}", f"CHAR_{lib_id}", ccode, b_key, cname]
        if cn_tok:
            raw_char_keys.extend([cn_tok, f"CHAR_{cn_tok}", f"CHAR_{cn_tok}_T1_BASE_PORTRAIT"])
        for raw_k in raw_char_keys:
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    # 权威本剧 characters 表记录最高优先级覆盖
                    char_map[cand] = c_info

    # 级联加载 character_stages (Tier-2) 与 character_stage_views (Tier-3) 切片 Key 映射回本剧角色
    try:
        csv_rows = fetch_all(
            db,
            """
            SELECT cs.id AS stage_id, cs.character_id, cs.stage_code, cs.stage_name,
                   csv.id AS view_id, csv.asset_key, csv.view_type
            FROM character_stages cs
            LEFT JOIN character_stage_views csv ON csv.character_stage_id = cs.id AND csv.deleted_at IS NULL
            WHERE cs.drama_id = :drama_id AND cs.deleted_at IS NULL
            ORDER BY cs.id ASC, csv.is_benchmark DESC, csv.id ASC
            """,
            {"drama_id": drama_id},
        )
        for csvr in csv_rows or []:
            if not isinstance(csvr, dict):
                continue
            cid = csvr.get("character_id")
            stid = csvr.get("stage_id")
            vid = csvr.get("view_id")
            if isinstance(cid, int) and cid in char_by_id:
                base_c_info = char_by_id[cid]
                # 记录角色当前默认阶段 ID
                if base_c_info.get("character_stage_id") is None and isinstance(stid, int):
                    base_c_info["character_stage_id"] = stid
                if base_c_info.get("stage_view_id") is None and isinstance(vid, int):
                    base_c_info["stage_view_id"] = vid

                slice_c_info = {
                    **base_c_info,
                    "character_stage_id": int(stid) if isinstance(stid, int) else None,
                    "stage_view_id": int(vid) if isinstance(vid, int) else None,
                    "benchmark_asset_key": str(csvr.get("asset_key") or base_c_info.get("benchmark_asset_key") or ""),
                }
                for rk in (csvr.get("stage_code"), csvr.get("stage_name"), csvr.get("asset_key")):
                    if rk:
                        norm_rk = _normalize_asset_lookup_token(str(rk))
                        if norm_rk:
                            char_map.setdefault(norm_rk, slice_c_info)
                        for cand in _extract_core_asset_prefixes(str(rk)):
                            if cand:
                                char_map.setdefault(cand, slice_c_info)
    except Exception as exc:
        log.debug("【Stage7资产字典】加载 character_stages / character_stage_views 异常: %s", exc)

    # 补充加载 character_voice_profiles（供 storyboard_audios 绑定角色音色档案）
    voice_by_name: dict[str, dict[str, Any]] = {}
    default_narrator_voice: dict[str, Any] | None = None
    try:
        vp_rows = fetch_all(
            db,
            "SELECT * FROM character_voice_profiles WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY is_master_card DESC, id ASC",
            {"drama_id": drama_id},
        )
        for vpr in vp_rows or []:
            if not isinstance(vpr, dict) or not isinstance(vpr.get("id"), int):
                continue
            vp_cid = vpr.get("character_id")
            if isinstance(vp_cid, int) and vp_cid not in voice_by_char_id:
                voice_by_char_id[vp_cid] = vpr
                if vp_cid in char_by_id:
                    cname = char_by_id[vp_cid].get("name", "")
                    if cname:
                        voice_by_name[cname.strip().upper()] = vpr
            # 记录旁白母音
            m_key = str(vpr.get("master_voice_key") or "").upper()
            if "NARRATOR" in m_key or "旁白" in str(vpr.get("voice_label") or ""):
                if default_narrator_voice is None:
                    default_narrator_voice = vpr
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 character_voice_profiles 表异常: %s", exc)

    # 3. 加载 props 主表（Tier-1）+ prop_damage_states（Tier-2）+ prop_detail_views（Tier-3）+ assets 道具记录
    try:
        prop_rows = fetch_all(
            db,
            "SELECT * FROM props WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
            {"drama_id": drama_id},
        )
    except Exception as exc:
        log.debug("【Stage7资产字典】读取 props 表异常（可能处于 Mock 环境）: %s", exc)
        prop_rows = []

    for pr in prop_rows or []:
        if not isinstance(pr, dict) or not isinstance(pr.get("id"), int):
            continue
        pid = int(pr["id"])
        pname = str(pr.get("name") or f"PROP_{pid}").strip()
        pcode = str(pr.get("prop_code") or f"PROP_{pid}").strip()
        b_key = str(pr.get("benchmark_asset_key") or pcode).strip()
        pn_tok = AssetProtocolHelper.chinese_to_token(pname) if pname else ""
        p_info = {
            "prop_id": pid,
            "damage_state_id": None,
            "prop_detail_view_id": None,
            "name": pname,
            "prop_code": pcode,
            "benchmark_asset_key": b_key,
        }
        prop_by_id[pid] = p_info
        raw_prop_keys = [str(pid), f"PROP_{pid}", pcode, f"PROP_{pcode}", b_key, pname]
        if pn_tok:
            raw_prop_keys.extend([pn_tok, f"PROP_{pn_tok}", f"PROP_{pn_tok}_S0_STATIC", f"PROP_{pn_tok}_T1_STATIC"])
        for raw_k in raw_prop_keys:
            for cand in _extract_core_asset_prefixes(raw_k):
                if cand:
                    prop_map.setdefault(cand, p_info)

    # 级联加载 Tier-2 prop_damage_states 与 Tier-3 prop_detail_views，映射切片 Key 到父级 prop_id + damage_state_id + prop_detail_view_id
    try:
        pds_rows = fetch_all(
            db,
            """
            SELECT pds.id AS damage_state_id, pds.prop_id, pds.state_code, pds.state_label,
                   pdv.id AS detail_view_id, pdv.asset_key
            FROM prop_damage_states pds
            LEFT JOIN prop_detail_views pdv ON pdv.damage_state_id = pds.id AND pdv.deleted_at IS NULL
            WHERE pds.drama_id = :drama_id AND pds.deleted_at IS NULL
            ORDER BY pds.id ASC, pdv.is_benchmark DESC, pdv.id ASC
            """,
            {"drama_id": drama_id},
        )
        for pdsr in pds_rows or []:
            if not isinstance(pdsr, dict):
                continue
            pid = pdsr.get("prop_id")
            ds_id = pdsr.get("damage_state_id")
            dvid = pdsr.get("detail_view_id")
            if isinstance(pid, int) and pid in prop_by_id:
                base_p = prop_by_id[pid]
                if base_p.get("damage_state_id") is None and isinstance(ds_id, int):
                    base_p["damage_state_id"] = ds_id
                if base_p.get("prop_detail_view_id") is None and isinstance(dvid, int):
                    base_p["prop_detail_view_id"] = dvid

                slice_p_info = {
                    **base_p,
                    "damage_state_id": int(ds_id) if isinstance(ds_id, int) else None,
                    "prop_detail_view_id": int(dvid) if isinstance(dvid, int) else None,
                    "benchmark_asset_key": str(pdsr.get("asset_key") or base_p.get("benchmark_asset_key") or ""),
                }
                for rk in (pdsr.get("state_code"), pdsr.get("state_label"), pdsr.get("asset_key")):
                    if rk:
                        for cand in _extract_core_asset_prefixes(str(rk)):
                            if cand:
                                prop_map.setdefault(cand, slice_p_info)
    except Exception as exc:
        log.debug("【Stage7资产字典】加载 prop_damage_states / prop_detail_views 异常: %s", exc)

    # 加载 assets 表中 category='prop' 的资产索引（覆盖仅在 assets 注册过 asset_key 的道具）
    try:
        asset_prop_rows = fetch_all(
            db,
            "SELECT name, asset_key FROM assets WHERE drama_id = :drama_id AND category = 'prop' AND deleted_at IS NULL",
            {"drama_id": drama_id},
        )
        for apr in asset_prop_rows or []:
            if not isinstance(apr, dict):
                continue
            a_name = str(apr.get("name") or "").strip()
            a_key = str(apr.get("asset_key") or "").strip()
            matched_p = _resolve_asset_from_map(a_name, prop_map) or _resolve_asset_from_map(a_key, prop_map)
            if matched_p and a_key:
                for cand in _extract_core_asset_prefixes(a_key):
                    if cand:
                        prop_map.setdefault(cand, matched_p)
    except Exception:
        pass

    log.debug(
        "【Stage7资产字典加载完成】drama_id=%s, episode_id=%s -> scenes=%d(索引键=%d), chars=%d(索引键=%d), props=%d(索引键=%d), voices=%d",
        drama_id,
        episode_id,
        len(scene_by_id),
        len(scene_map),
        len(char_by_id),
        len(char_map),
        len(prop_by_id),
        len(prop_map),
        len(voice_by_char_id),
    )
    return {
        "scene_map": scene_map,
        "char_map": char_map,
        "prop_map": prop_map,
        "voice_by_char_id": voice_by_char_id,
        "voice_by_name": voice_by_name,
        "default_narrator_voice": default_narrator_voice,
        "scene_by_id": scene_by_id,
        "char_by_id": char_by_id,
        "char_by_lib_id": char_by_lib_id,
        "prop_by_id": prop_by_id,
        "default_scene": default_scene,
    }


def _resolve_asset_from_map(raw_ref: Any, lookup_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """在 Stage 6 资产映射字典中执行「精确匹配 -> 核心前缀匹配 -> 安全词元边界匹配 -> 中文名称包含」四级检索。

    【防串库与防碰撞保障】
    彻底废除原先 `len(k) >= 2 and (k in norm_full or norm_full in k)` 的无边界短字符串子串包含匹配，
    杜绝 `CHAR_1` 错误命中 `CHAR_10_T1_BASE` 或短编号跨角色误连。
    """
    if not raw_ref or not lookup_map:
        return None
    raw_str = str(raw_ref).strip()
    if not raw_str:
        return None
    candidates = _extract_core_asset_prefixes(raw_str)
    # 1. 精确候选键匹配（全名 Token -> 二段式前缀 -> 核心实体 Token）
    for cand in candidates:
        if cand in lookup_map:
            return lookup_map[cand]

    # 2. 尝试将中文引用转为标准英文拼音 Token 后再次精确匹配
    if re.search(r"[\u4e00-\u9fa5]", raw_str):
        cn_tok = AssetProtocolHelper.chinese_to_token(raw_str)
        if cn_tok and cn_tok != "UNKNOWN":
            for prefix in (cn_tok, f"CHAR_{cn_tok}", f"PROP_{cn_tok}", f"ENV_{cn_tok}", f"SCENE_{cn_tok}"):
                if prefix in lookup_map:
                    return lookup_map[prefix]

    # 3. 安全词元边界匹配（按下划线分词后比对非通用核心词元，绝不匹配纯数字或通用前缀）
    norm_full = candidates[0] if candidates else ""
    norm_parts = [
        p for p in norm_full.split("_")
        if len(p) >= 3 and not p.isdigit() and p not in _GENERIC_ASSET_SEGMENTS
    ]
    if norm_parts:
        for k, info in lookup_map.items():
            if k.isdigit() or k in _GENERIC_ASSET_SEGMENTS:
                continue
            k_parts = [
                kp for kp in k.split("_")
                if len(kp) >= 3 and not kp.isdigit() and kp not in _GENERIC_ASSET_SEGMENTS
            ]
            if k_parts and any(np == kp for np in norm_parts for kp in k_parts):
                return info

    # 4. 中文实体名称安全包含匹配（仅针对长度 >= 2 的中文实体名称，不针对英文/数字编号）
    if re.search(r"[\u4e00-\u9fa5]{2,}", norm_full):
        for k, info in lookup_map.items():
            if re.search(r"[\u4e00-\u9fa5]{2,}", k) and (k in norm_full or norm_full in k):
                return info
    return None


def _cascade_delete_episode_storyboards(db: Session, episode_id: int) -> None:
    """幂等级联清理指定集的分镜六表记录，确保重跑时 100% 覆盖。

    采用两阶段精准清理：
    1. 显式查出属于该集的全部旧 storyboard_id 列表；
    2. 使用具体 ID 集合精准清空 5 张从表（解除外键与主表依赖）；
    3. 彻底删除主表镜头，并校验主表残留行数必须为 0。
    """
    # 阶段 1：精准获取当前集存在的所有旧分镜 ID
    old_sb_rows = db.execute(
        text("SELECT id FROM storyboards WHERE episode_id = :ep_id"),
        {"ep_id": episode_id},
    ).fetchall()
    old_sb_ids = [r[0] for r in old_sb_rows if r[0] is not None]

    log.info(
        "【Stage7六表级联清理】准备清理 episode_id=%s 的旧分镜数据，探测到旧分镜数: %s (IDs: %s)",
        episode_id,
        len(old_sb_ids),
        old_sb_ids[:10] if len(old_sb_ids) > 10 else old_sb_ids,
    )

    # 阶段 2：如果存在旧分镜，先精确清除所有从表数据（先从后主，解除外键与引用依赖）
    if old_sb_ids:
        # 分批处理防止极端情况下 SQL 占位符超限，通常单集镜头数为 10~100
        batch_size = 500
        for i in range(0, len(old_sb_ids), batch_size):
            chunk = old_sb_ids[i : i + batch_size]
            id_in_clause = ",".join(str(int(sid)) for sid in chunk)

            # 0. 清理分镜字幕从表 storyboard_subtitles
            db.execute(
                text(f"""
                    DELETE FROM storyboard_subtitles
                    WHERE episode_id = :ep_id
                       OR storyboard_id IN ({id_in_clause})
                """),
                {"ep_id": episode_id},
            )
            # 1. 清理分镜音频轨从表 storyboard_audios
            db.execute(
                text(f"""
                    DELETE FROM storyboard_audios
                    WHERE episode_id = :ep_id
                       OR storyboard_id IN ({id_in_clause})
                """),
                {"ep_id": episode_id},
            )
            # 2. 清理分镜关键帧提示词从表 frame_prompts
            db.execute(
                text(f"DELETE FROM frame_prompts WHERE storyboard_id IN ({id_in_clause})"),
                {},
            )
            # 3. 清理分镜角色关联从表 storyboard_characters
            db.execute(
                text(f"DELETE FROM storyboard_characters WHERE storyboard_id IN ({id_in_clause})"),
                {},
            )
            # 4. 清理分镜道具关联从表 storyboard_props
            db.execute(
                text(f"DELETE FROM storyboard_props WHERE storyboard_id IN ({id_in_clause})"),
                {},
            )
    else:
        # 兜底清理可能残留孤儿数据的从表（仅根据 episode_id）
        db.execute(text("DELETE FROM storyboard_subtitles WHERE episode_id = :ep_id"), {"ep_id": episode_id})
        db.execute(text("DELETE FROM storyboard_audios WHERE episode_id = :ep_id"), {"ep_id": episode_id})

    # 阶段 3：清理分镜主表 storyboards
    db.execute(text("DELETE FROM storyboards WHERE episode_id = :ep_id"), {"ep_id": episode_id})

    # 阶段 4：清零断言验证（确保该集分镜主表在物理上已经 100% 清空，防止未成功删除导致追加）
    remaining = db.execute(
        text("SELECT COUNT(*) FROM storyboards WHERE episode_id = :ep_id"),
        {"ep_id": episode_id},
    ).scalar()
    if isinstance(remaining, int) and remaining > 0:
        raise RuntimeError(
            f"【Stage7六表级联清理失败】清理后 episode_id={episode_id} 仍残留 {remaining} 条主分镜记录，未成功清零，拒绝写入以防追加数据！"
        )
    log.info("【Stage7六表级联清理】episode_id=%s 旧分镜及全部关联从表已彻底物理清零。", episode_id)


def _persist_episode_storyboards_3tables(
    db: Session,
    drama_id: int,
    episode_id: int,
    storyboards: list[Any],
    status: str = "draft",
    now: str | None = None,
) -> dict[str, int]:
    """核心六表联动持久化函数：原子写入 storyboards 主表、frame_prompts 关键帧表、
    storyboard_characters 角色表、storyboard_props 道具表、storyboard_audios 音频表与 storyboard_subtitles 字幕表。
    """
    now_str = str(now or now_iso())
    _cascade_delete_episode_storyboards(db, episode_id)

    if not storyboards:
        log.debug("【Stage7六表落库】episode_id=%s 分镜列表为空，仅完成清理。", episode_id)
        return {
            "storyboards": 0,
            "frame_prompts": 0,
            "storyboard_characters": 0,
            "storyboard_props": 0,
            "storyboard_audios": 0,
            "storyboard_subtitles": 0,
        }

    log.info(
        "【Stage7六表落库】episode_id=%s 级联清理完毕，准备写入最新分镜数: %d",
        episode_id,
        len(storyboards),
    )

    asset_maps = _load_stage6_asset_lookup_maps(db, drama_id, episode_id=episode_id)
    scene_map = asset_maps["scene_map"]
    char_map = asset_maps["char_map"]
    prop_map = asset_maps["prop_map"]
    voice_by_char_id = asset_maps.get("voice_by_char_id", {})
    voice_by_name = asset_maps.get("voice_by_name", {})
    default_narrator_voice = asset_maps.get("default_narrator_voice")
    default_scene = asset_maps["default_scene"]

    def _s_get(s: Any, key: str, default: Any = None) -> Any:
        if isinstance(s, dict):
            return s.get(key, default)
        return getattr(s, key, default)

    sb_count = 0
    fp_count = 0
    sb_char_count = 0
    sb_prop_count = 0
    sb_audio_count = 0
    sb_sub_count = 0
    global_seq_order = 1
    current_timeline_ms = 0

    for idx, shot in enumerate(storyboards, start=1):
        lipsync_val = _dump_or_dict(_s_get(shot, "lipsync_dynamics"))
        audio_val = _s_get(shot, "audio") or {}
        if not isinstance(audio_val, dict):
            audio_val = _dump_or_dict(audio_val) or {}

        img_prompt = str(_s_get(shot, "image_prompt") or _s_get(shot, "visual_description") or "")
        vid_prompt = str(_s_get(shot, "video_prompt") or "")
        gen_mode = str(_s_get(shot, "generation_mode") or _s_get(shot, "creation_mode") or "single_frame")
        first_last_cfg = _s_get(shot, "first_last_config")
        if first_last_cfg and not isinstance(first_last_cfg, dict):
            first_last_cfg = _dump_or_dict(first_last_cfg)
        multi_img_cfg = _s_get(shot, "multi_image_config")
        if multi_img_cfg and not isinstance(multi_img_cfg, dict):
            multi_img_cfg = _dump_or_dict(multi_img_cfg)

        if not img_prompt:
            if gen_mode == "first_last_frame" and isinstance(first_last_cfg, dict):
                img_prompt = str(first_last_cfg.get("first_frame_prompt") or "")
                vid_prompt = vid_prompt or str(first_last_cfg.get("video_motion_prompt") or "")
            elif isinstance(multi_img_cfg, dict):
                img_prompt = str(multi_img_cfg.get("video_prompt") or "")
                vid_prompt = vid_prompt or str(multi_img_cfg.get("video_prompt") or "")

        shot_num = int(_s_get(shot, "shot_id") or _s_get(shot, "storyboard_number") or _s_get(shot, "shot_number") or idx)
        shot_dur = float(_s_get(shot, "duration_sec") or _s_get(shot, "duration") or 3.0)
        shot_type = str(_s_get(shot, "framing") or _s_get(shot, "shot_type") or "MCU 中近景")
        movement = str(_s_get(shot, "camera_motion") or _s_get(shot, "movement") or "推镜")
        target_engine = str(_s_get(shot, "target_engine") or "wan3.0")
        selection_rationale = str(_s_get(shot, "selection_rationale") or "")
        mode_b_audit_verdict = str(_s_get(shot, "mode_b_audit_verdict") or "PASS_9")
        dialogue = str(
            audio_val.get("dialogue")
            or _s_get(shot, "dialogue")
            or _s_get(shot, "srt_text")
            or _s_get(shot, "dialogue_text")
            or ""
        )
        narration = str(audio_val.get("narration") or _s_get(shot, "narration") or "")
        action = str(_s_get(shot, "dynamic_cue") or _s_get(shot, "action") or "")
        atmosphere = str(
            audio_val.get("foley")
            or _s_get(shot, "foley_cue")
            or _s_get(shot, "atmosphere")
            or ""
        )

        # 收集镜头引用的全部资产标识（显式字段 + 模式A首尾帧 + 模式B参考图列表）
        raw_scene_ref = str(_s_get(shot, "scene_asset_id") or "").strip()
        raw_char_refs: list[str] = [
            str(x).strip() for x in (_s_get(shot, "character_asset_ids") or []) if str(x).strip()
        ]
        raw_prop_refs: list[str] = [
            str(x).strip() for x in (_s_get(shot, "prop_asset_ids") or []) if str(x).strip()
        ]

        all_ref_keys: list[str] = []
        if isinstance(first_last_cfg, dict):
            for fl_k in ("first_frame_asset_id", "last_frame_asset_id"):
                val = str(first_last_cfg.get(fl_k) or "").strip()
                if val and val not in all_ref_keys:
                    all_ref_keys.append(val)
        if isinstance(multi_img_cfg, dict):
            for ref_item in (multi_img_cfg.get("reference_assets") or []):
                val = str(ref_item or "").strip()
                if val and val not in all_ref_keys:
                    all_ref_keys.append(val)

        # 从综合参考资产键中自动归类未显式声明的 ENV_ / CHAR_ / PROP_
        for ref_k in all_ref_keys:
            upper_k = ref_k.upper()
            if upper_k.startswith(("ENV_", "SCENE_")) and not raw_scene_ref:
                raw_scene_ref = ref_k
            elif upper_k.startswith("CHAR_") and ref_k not in raw_char_refs:
                raw_char_refs.append(ref_k)
            elif upper_k.startswith("PROP_") and ref_k not in raw_prop_refs:
                raw_prop_refs.append(ref_k)

        if raw_scene_ref and raw_scene_ref not in all_ref_keys:
            all_ref_keys.insert(0, raw_scene_ref)
        for cr in raw_char_refs:
            if cr not in all_ref_keys:
                all_ref_keys.append(cr)
        for pr in raw_prop_refs:
            if pr not in all_ref_keys:
                all_ref_keys.append(pr)

        # 1) 解析 Stage 6 场景外键 (scenes.id, scene_zones.id, scene_weathering_views.id)
        resolved_scene_info = _resolve_asset_from_map(raw_scene_ref, scene_map)
        if resolved_scene_info is None and default_scene is not None:
            resolved_scene_info = default_scene

        resolved_scene_id: int | None = None
        resolved_scene_zone_id: int | None = None
        resolved_scene_weathering_view_id: int | None = None
        resolved_location = str(_s_get(shot, "location") or "")
        
        # 严谨解析 time（时段环境：如"早/中/晚/深夜/暴雨夜"），坚决阻断 timecode 或 srt_timing 时码污染
        raw_shot_time = str(_s_get(shot, "time") or "").strip()
        if "-->" in raw_shot_time or (len(raw_shot_time) >= 8 and ":" in raw_shot_time and "," in raw_shot_time):
            raw_shot_time = ""  # 过滤误填入的时码字符串
        
        resolved_time = raw_shot_time
        if resolved_scene_info:
            resolved_scene_id = int(resolved_scene_info["scene_id"])
            sz_id = resolved_scene_info.get("scene_zone_id")
            swv_id = resolved_scene_info.get("scene_weathering_view_id")
            resolved_scene_zone_id = int(sz_id) if isinstance(sz_id, int) else None
            resolved_scene_weathering_view_id = int(swv_id) if isinstance(swv_id, int) else None
            if not resolved_location:
                resolved_location = str(resolved_scene_info.get("location") or "")
            if not resolved_time:
                resolved_time = str(resolved_scene_info.get("time") or "")
            if not raw_scene_ref:
                raw_scene_ref = str(resolved_scene_info.get("benchmark_asset_key") or resolved_scene_info.get("scene_code") or "")

        if not resolved_time:
            resolved_time = "日景/白天"  # 兜底默认自然时段，绝不使用时码替代

        # 2) 解析 Stage 6 角色三级外键 (characters.id, character_libraries.id, character_stages.id, character_stage_views.id)
        resolved_chars: list[dict[str, Any]] = []
        resolved_char_lib_ids: list[int] = []
        resolved_char_names: list[str] = []
        normalized_char_tokens: list[str] = []

        for c_ref in raw_char_refs:
            c_info = _resolve_asset_from_map(c_ref, char_map)
            if c_info:
                cid = int(c_info.get("character_id") or c_info["character_lib_id"])
                lid = int(c_info["character_lib_id"])
                cs_id = c_info.get("character_stage_id")
                sv_id = c_info.get("stage_view_id")
                cname = str(c_info.get("name") or "")
                bkey = str(c_info.get("benchmark_asset_key") or c_ref)
                if lid not in resolved_char_lib_ids:
                    resolved_char_lib_ids.append(lid)
                    resolved_chars.append({
                        "character_id": cid,
                        "character_lib_id": lid,
                        "character_stage_id": int(cs_id) if isinstance(cs_id, int) else None,
                        "stage_view_id": int(sv_id) if isinstance(sv_id, int) else None,
                        "name": cname,
                        "asset_key": bkey,
                    })
                if cname and cname not in resolved_char_names:
                    resolved_char_names.append(cname)
                if bkey not in normalized_char_tokens:
                    normalized_char_tokens.append(bkey)
            else:
                if c_ref not in normalized_char_tokens:
                    normalized_char_tokens.append(c_ref)

        speaker_name = ""
        if dialogue and ("：" in dialogue or ":" in dialogue):
            sep = "：" if "：" in dialogue else ":"
            speaker_candidate = dialogue.split(sep, 1)[0].strip()
            speaker_candidate = re.sub(r"[（\(].*?[）\)]", "", speaker_candidate).strip()
            if speaker_candidate:
                speaker_name = speaker_candidate
                speaker_info = _resolve_asset_from_map(speaker_name, char_map)
                if speaker_info:
                    scid = int(speaker_info.get("character_id") or speaker_info["character_lib_id"])
                    slid = int(speaker_info["character_lib_id"])
                    scs_id = speaker_info.get("character_stage_id")
                    ssv_id = speaker_info.get("stage_view_id")
                    scname = str(speaker_info.get("name") or speaker_name)
                    sbkey = str(speaker_info.get("benchmark_asset_key") or f"CHAR_{slid}")
                    if slid not in resolved_char_lib_ids:
                        resolved_char_lib_ids.append(slid)
                        resolved_chars.append({
                            "character_id": scid,
                            "character_lib_id": slid,
                            "character_stage_id": int(scs_id) if isinstance(scs_id, int) else None,
                            "stage_view_id": int(ssv_id) if isinstance(ssv_id, int) else None,
                            "name": scname,
                            "asset_key": sbkey,
                        })
                    if scname and scname not in resolved_char_names:
                        resolved_char_names.append(scname)
                    if sbkey not in normalized_char_tokens:
                        normalized_char_tokens.append(sbkey)

        # 3) 解析 Stage 6 道具三级外键 (props.id, prop_damage_states.id, prop_detail_views.id)
        resolved_props: list[dict[str, Any]] = []
        resolved_prop_ids: list[int] = []
        normalized_prop_tokens: list[str] = []
        for p_ref in raw_prop_refs:
            p_info = _resolve_asset_from_map(p_ref, prop_map)
            if p_info:
                pid = int(p_info["prop_id"])
                ds_id = p_info.get("damage_state_id")
                dv_id = p_info.get("prop_detail_view_id")
                bkey = str(p_info.get("benchmark_asset_key") or p_ref)
                if pid not in resolved_prop_ids:
                    resolved_prop_ids.append(pid)
                    resolved_props.append({
                        "prop_id": pid,
                        "damage_state_id": int(ds_id) if isinstance(ds_id, int) else None,
                        "prop_detail_view_id": int(dv_id) if isinstance(dv_id, int) else None,
                        "asset_key": bkey,
                    })
                if bkey not in normalized_prop_tokens:
                    normalized_prop_tokens.append(bkey)
            else:
                if p_ref not in normalized_prop_tokens:
                    normalized_prop_tokens.append(p_ref)

        dur_ms = int(shot_dur * 1000)
        shot_start_ms = current_timeline_ms
        shot_end_ms = current_timeline_ms + dur_ms
        current_timeline_ms = shot_end_ms

        def _fmt_tc(ms_val: int) -> str:
            h = ms_val // 3600000
            m = (ms_val % 3600000) // 60000
            s = (ms_val % 60000) // 1000
            ms = ms_val % 1000
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        shot_timecode = str(_s_get(shot, "timecode") or f"{_fmt_tc(shot_start_ms)} --> {_fmt_tc(shot_end_ms)}")
        srt_timing_val = str(_s_get(shot, "srt_timing") or shot_timecode)
        srt_dynamics_json = json.dumps(
            {
                "srt_timing": srt_timing_val,
                "srt_text": _s_get(shot, "srt_text") or dialogue,
                "speech_inpoint_sec": _s_get(shot, "speech_inpoint_sec"),
                "contextual_tts_prompt": _s_get(shot, "contextual_tts_prompt"),
                "is_dialogue_complete_in_shot": _s_get(shot, "is_dialogue_complete_in_shot", True),
                "lipsync_dynamics": lipsync_val,
            },
            ensure_ascii=False,
        )
        audio_stem_json = json.dumps(
            {
                "audio": audio_val,
                "music_cue": _s_get(shot, "music_cue") or audio_val.get("bgm") or "",
                "foley_cue": _s_get(shot, "foley_cue") or audio_val.get("foley") or "",
            },
            ensure_ascii=False,
        )
        shot_result_payload = {
            "selection_rationale": selection_rationale,
            "target_engine": target_engine,
            "generation_mode": gen_mode,
            "rationale": _s_get(shot, "rationale"),
            "first_last_config": first_last_cfg,
            "multi_image_config": multi_img_cfg,
            "audio": audio_val,
            "lipsync_dynamics": lipsync_val,
            "speech_inpoint_sec": _s_get(shot, "speech_inpoint_sec"),
            "contextual_tts_prompt": _s_get(shot, "contextual_tts_prompt"),
            "is_dialogue_complete_in_shot": _s_get(shot, "is_dialogue_complete_in_shot", True),
            "srt_timing": srt_timing_val,
            "srt_text": _s_get(shot, "srt_text") or dialogue,
            "dynamic_cue": _s_get(shot, "dynamic_cue") or action,
            "music_cue": _s_get(shot, "music_cue") or audio_val.get("bgm") or "",
            "foley_cue": _s_get(shot, "foley_cue") or atmosphere,
            "scene_asset_id": raw_scene_ref,
            "character_asset_ids": normalized_char_tokens,
            "prop_asset_ids": normalized_prop_tokens,
            "resolved_scene_id": resolved_scene_id,
            "resolved_character_ids": resolved_char_lib_ids,
            "resolved_prop_ids": resolved_prop_ids,
        }
        shot_result_json = json.dumps(shot_result_payload, ensure_ascii=False)
        characters_json = json.dumps(resolved_char_names or normalized_char_tokens, ensure_ascii=False)
        ref_keys_json = json.dumps(all_ref_keys, ensure_ascii=False)
        
        # 优化 shot_title：优先使用 LLM 提炼的分镜节拍小标题，次级智能兜底动作前段，避免纯占位符
        candidate_title = str(_s_get(shot, "title") or "").strip()
        if not candidate_title or candidate_title.startswith("镜头 #") or candidate_title == f"镜头{shot_num}":
            action_cue = str(_s_get(shot, "action") or _s_get(shot, "dynamic_cue") or "").strip()
            if action_cue:
                # 截取动作前 14 个字符作为清晰的戏剧动作小标题
                candidate_title = action_cue[:14].rstrip("，。！？；:,")
            elif dialogue:
                candidate_title = dialogue[:14].rstrip("，。！？；:,")
            else:
                candidate_title = f"镜头 #{shot_num}"
        shot_title = candidate_title

        # 4) 插入 storyboards 主表（全面写入场景二级区域与三级做旧视图）
        ins_res = db.execute(
            text("""
                INSERT INTO storyboards (
                    episode_id, scene_id, scene_zone_id, scene_weathering_view_id, scene_asset_key,
                    storyboard_number, title, description,
                    location, time, duration, shot_type, movement,
                    creation_mode, generation_mode, selection_rationale, target_engine,
                    timecode, mode_b_audit_verdict,
                    image_prompt, video_prompt, dialogue, narration,
                    action, atmosphere, characters, reference_asset_keys,
                    srt_dynamics, audio_stem_params, result, status, created_at, updated_at
                ) VALUES (
                    :episode_id, :scene_id, :scene_zone_id, :scene_weathering_view_id, :scene_asset_key,
                    :storyboard_number, :title, :description,
                    :location, :time, :duration, :shot_type, :movement,
                    :creation_mode, :generation_mode, :selection_rationale, :target_engine,
                    :timecode, :mode_b_audit_verdict,
                    :image_prompt, :video_prompt, :dialogue, :narration,
                    :action, :atmosphere, :characters, :reference_asset_keys,
                    :srt_dynamics, :audio_stem_params, :result, :status, :created_at, :updated_at
                )
            """),
            {
                "episode_id": episode_id,
                "scene_id": resolved_scene_id,
                "scene_zone_id": resolved_scene_zone_id,
                "scene_weathering_view_id": resolved_scene_weathering_view_id,
                "scene_asset_key": raw_scene_ref,
                "storyboard_number": shot_num,
                "title": shot_title,
                "description": img_prompt or action,
                "location": resolved_location,
                "time": resolved_time,
                "duration": shot_dur,
                "shot_type": shot_type,
                "movement": movement,
                "creation_mode": gen_mode,
                "generation_mode": gen_mode,
                "selection_rationale": selection_rationale,
                "target_engine": target_engine,
                "timecode": shot_timecode,
                "mode_b_audit_verdict": mode_b_audit_verdict,
                "image_prompt": img_prompt,
                "video_prompt": vid_prompt,
                "dialogue": dialogue,
                "narration": narration,
                "action": action,
                "atmosphere": atmosphere,
                "characters": characters_json,
                "reference_asset_keys": ref_keys_json,
                "srt_dynamics": srt_dynamics_json,
                "audio_stem_params": audio_stem_json,
                "result": shot_result_json,
                "status": status,
                "created_at": now_str,
                "updated_at": now_str,
            },
        )
        sb_count += 1

        storyboard_id: int | None = None
        raw_last_id = getattr(ins_res, "lastrowid", None)
        if isinstance(raw_last_id, int) and raw_last_id > 0:
            storyboard_id = raw_last_id
        else:
            try:
                sb_id_row = fetch_one(
                    db,
                    "SELECT id FROM storyboards WHERE episode_id = :ep_id AND storyboard_number = :sb_num ORDER BY id DESC LIMIT 1",
                    {"ep_id": episode_id, "sb_num": shot_num},
                )
                if isinstance(sb_id_row, dict) and isinstance(sb_id_row.get("id"), int):
                    storyboard_id = int(sb_id_row["id"])
            except Exception:
                storyboard_id = None

        if storyboard_id is not None and storyboard_id > 0:
            # 5) 写入 frame_prompts 关键帧表
            if gen_mode == "first_last_frame" and isinstance(first_last_cfg, dict):
                first_p = str(first_last_cfg.get("first_frame_prompt") or "")
                last_p = str(first_last_cfg.get("last_frame_prompt") or "")
                motion_p = str(first_last_cfg.get("video_motion_prompt") or vid_prompt)
                if first_p:
                    db.execute(
                        text("""
                            INSERT INTO frame_prompts (
                                storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                            ) VALUES (
                                :sb_id, 'first', :prompt, '首帧T=0s起始静态', 'single_first', :now, :now
                            )
                        """),
                        {"sb_id": storyboard_id, "prompt": first_p, "now": now_str},
                    )
                    fp_count += 1
                if last_p:
                    db.execute(
                        text("""
                            INSERT INTO frame_prompts (
                                storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                            ) VALUES (
                                :sb_id, 'last', :prompt, '尾帧T=Ds定格终态', 'single_last', :now, :now
                            )
                        """),
                        {"sb_id": storyboard_id, "prompt": last_p, "now": now_str},
                    )
                    fp_count += 1
                if motion_p:
                    db.execute(
                        text("""
                            INSERT INTO frame_prompts (
                                storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                            ) VALUES (
                                :sb_id, 'motion_interpolation', :prompt, '首尾帧三段式运动插值描述', 'motion_interpolation', :now, :now
                            )
                        """),
                        {"sb_id": storyboard_id, "prompt": motion_p, "now": now_str},
                    )
                    fp_count += 1
            elif img_prompt:
                db.execute(
                    text("""
                        INSERT INTO frame_prompts (
                            storyboard_id, frame_type, prompt, description, layout, created_at, updated_at
                        ) VALUES (
                            :sb_id, 'key', :prompt, '主关键帧画面', 'single', :now, :now
                        )
                    """),
                    {"sb_id": storyboard_id, "prompt": img_prompt, "now": now_str},
                )
                fp_count += 1

            # 6) 写入 storyboard_characters 保序表（图2..k，从 slot_order=2 开始，写入阶段造型与切片视图）
            for c_idx, c_item in enumerate(resolved_chars, start=2):
                db.execute(
                    text("""
                        INSERT INTO storyboard_characters (
                            storyboard_id, character_id, character_lib_id, character_stage_id, stage_view_id,
                            slot_order, ref_symbol, asset_key, role_in_shot, created_at
                        ) VALUES (
                            :sb_id, :char_id, :lib_id, :stage_id, :view_id,
                            :slot_order, :ref_symbol, :asset_key, 'primary', :now
                        )
                    """),
                    {
                        "sb_id": storyboard_id,
                        "char_id": c_item["character_id"],
                        "lib_id": c_item["character_lib_id"],
                        "stage_id": c_item.get("character_stage_id"),
                        "view_id": c_item.get("stage_view_id"),
                        "slot_order": c_idx,
                        "ref_symbol": f"图{c_idx}",
                        "asset_key": c_item.get("asset_key", ""),
                        "now": now_str,
                    },
                )
                sb_char_count += 1

            # 7) 写入 storyboard_props 保序表（slot_order 紧跟在角色之后，写入二级破坏形态与三级细节视图）
            prop_slot_start = 2 + len(resolved_chars)
            for p_idx, p_item in enumerate(resolved_props, start=prop_slot_start):
                db.execute(
                    text("""
                        INSERT INTO storyboard_props (
                            storyboard_id, prop_id, damage_state_id, prop_detail_view_id,
                            slot_order, ref_symbol, asset_key, interaction_role, created_at
                        ) VALUES (
                            :sb_id, :prop_id, :damage_state_id, :prop_detail_view_id,
                            :slot_order, :ref_symbol, :asset_key, 'primary', :now
                        )
                    """),
                    {
                        "sb_id": storyboard_id,
                        "prop_id": p_item["prop_id"],
                        "damage_state_id": p_item.get("damage_state_id"),
                        "prop_detail_view_id": p_item.get("prop_detail_view_id"),
                        "slot_order": p_idx,
                        "ref_symbol": f"图{p_idx}",
                        "asset_key": p_item.get("asset_key", ""),
                        "now": now_str,
                    },
                )
                sb_prop_count += 1

            # 8) 写入 storyboard_audios 与 storyboard_subtitles 表（AI母音驱动与毫秒级字幕）
            clean_dlg = clean_dialogue_text(dialogue) if dialogue else ""
            clean_narr = clean_dialogue_text(narration) if narration else ""
            tts_prompt = str(_s_get(shot, "contextual_tts_prompt") or audio_val.get("contextual_tts_prompt") or "")
            inpoint_s = float(_s_get(shot, "speech_inpoint_sec") or 0.3)
            outpoint_s = min(shot_dur, inpoint_s + max(1.0, len(clean_dlg or clean_narr) * 0.25))

            dlg_target_text = clean_dlg or clean_narr
            if dlg_target_text:
                matched_voice: dict[str, Any] | None = None
                matched_char_id: int | None = None
                matched_speaker_name = speaker_name or (resolved_chars[0]["name"] if resolved_chars else "未知角色")

                if speaker_name:
                    matched_voice = voice_by_name.get(speaker_name.upper())
                if matched_voice is None and resolved_chars:
                    matched_char_id = resolved_chars[0]["character_id"]
                    matched_voice = voice_by_char_id.get(matched_char_id)

                if clean_narr and not clean_dlg:
                    matched_voice = default_narrator_voice or matched_voice
                    matched_speaker_name = "旁白"
                    matched_char_id = None

                provider = str((matched_voice and matched_voice.get("tts_provider")) or "minimax")
                model_name = str((matched_voice and matched_voice.get("tts_model")) or "speech-02-hd")
                voice_id = str((matched_voice and matched_voice.get("provider_voice_id")) or (matched_voice and matched_voice.get("voice_id")) or "")
                vp_id = int(matched_voice["id"]) if (matched_voice and isinstance(matched_voice.get("id"), int)) else None

                hash_str = f"{voice_id}|{dlg_target_text}|{tts_prompt}|{inpoint_s:.3f}"
                semantic_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()
                track_type = "narration" if (clean_narr and not clean_dlg) else "dialogue"

                matched_char_stage_id: int | None = None
                if resolved_chars:
                    matched_char_stage_id = resolved_chars[0].get("character_stage_id")

                ins_aud = db.execute(
                    text("""
                        INSERT INTO storyboard_audios (
                            drama_id, episode_id, storyboard_id, slot_order, ref_symbol,
                            asset_key, track_type, character_id, character_stage_id, voice_profile_id,
                            speaker_name, dialogue_text, clean_dialogue_text, tts_prompt, lipsync_dynamics,
                            srt_timing, inpoint_sec, outpoint_sec, duration_sec, is_complete_in_shot,
                            speed_ratio, pitch_ratio, emotion, emotion_intensity,
                            gain_db, ducking_db, target_lufs, provider, model, voice_id,
                            format, sample_rate, channels, semantic_hash, status, created_at, updated_at
                        ) VALUES (
                            :drama_id, :ep_id, :sb_id, 1, '音频1',
                            :asset_key, :track_type, :char_id, :char_stage_id, :vp_id,
                            :speaker_name, :dialogue_text, :clean_text, :tts_prompt, :lipsync_dynamics,
                            :srt_timing, :inpoint_sec, :outpoint_sec, :duration_sec, 1,
                            1.0, 1.0, 'neutral', 5,
                            0.0, 0.0, -23.0, :provider, :model, :voice_id,
                            'wav', 48000, 2, :semantic_hash, 'planned', :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "ep_id": episode_id,
                        "sb_id": storyboard_id,
                        "asset_key": f"VOICE_{matched_speaker_name}",
                        "track_type": track_type,
                        "char_id": matched_char_id,
                        "char_stage_id": matched_char_stage_id,
                        "vp_id": vp_id,
                        "speaker_name": matched_speaker_name,
                        "dialogue_text": dialogue or narration,
                        "clean_text": dlg_target_text,
                        "tts_prompt": tts_prompt,
                        "lipsync_dynamics": json.dumps(lipsync_val, ensure_ascii=False) if lipsync_val else "",
                        "srt_timing": srt_timing_val,
                        "inpoint_sec": inpoint_s,
                        "outpoint_sec": outpoint_s,
                        "duration_sec": max(1.0, outpoint_s - inpoint_s),
                        "provider": provider,
                        "model": model_name,
                        "voice_id": voice_id,
                        "semantic_hash": semantic_hash,
                        "now": now_str,
                    },
                )
                sb_audio_count += 1
                aud_id: int | None = getattr(ins_aud, "lastrowid", None)

                sub_start_ms = shot_start_ms + int(inpoint_s * 1000)
                sub_end_ms = min(shot_end_ms, shot_start_ms + int(outpoint_s * 1000))
                sub_srt_timecode = f"{_fmt_tc(sub_start_ms)} --> {_fmt_tc(sub_end_ms)}"

                db.execute(
                    text("""
                        INSERT INTO storyboard_subtitles (
                            drama_id, episode_id, storyboard_id, sequence_order,
                            subtitle_type, character_id, speaker_name, text_content,
                            start_ms, end_ms, duration_ms, srt_timecode, audio_id,
                            created_at, updated_at
                        ) VALUES (
                            :drama_id, :ep_id, :sb_id, :seq_order,
                            :sub_type, :char_id, :speaker_name, :text_content,
                            :start_ms, :end_ms, :dur_ms, :srt_tc, :audio_id,
                            :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "ep_id": episode_id,
                        "sb_id": storyboard_id,
                        "seq_order": global_seq_order,
                        "sub_type": track_type,
                        "char_id": matched_char_id,
                        "speaker_name": matched_speaker_name,
                        "text_content": dlg_target_text,
                        "start_ms": sub_start_ms,
                        "end_ms": sub_end_ms,
                        "dur_ms": max(100, sub_end_ms - sub_start_ms),
                        "srt_tc": sub_srt_timecode,
                        "audio_id": aud_id,
                        "now": now_str,
                    },
                )
                global_seq_order += 1
                sb_sub_count += 1

            # Foley 物理音效
            foley_text = str(audio_val.get("foley") or _s_get(shot, "foley_cue") or atmosphere or "")
            if foley_text:
                f_hash_str = f"FOLEY|{foley_text}|{shot_num}"
                f_hash = hashlib.sha256(f_hash_str.encode("utf-8")).hexdigest()
                db.execute(
                    text("""
                        INSERT INTO storyboard_audios (
                            drama_id, episode_id, storyboard_id, slot_order, ref_symbol,
                            asset_key, track_type, character_id,
                            speaker_name, dialogue_text, clean_dialogue_text,
                            srt_timing, inpoint_sec, outpoint_sec, duration_sec, is_complete_in_shot,
                            gain_db, ducking_db, target_lufs, format, sample_rate, channels,
                            semantic_hash, status, created_at, updated_at
                        ) VALUES (
                            :drama_id, :ep_id, :sb_id, 2, '音频2',
                            'SFX_FOLEY', 'foley', NULL,
                            '拟音', :dialogue_text, :clean_text,
                            :srt_timing, 0.0, :dur, :dur, 1,
                            3.0, 0.0, -23.0, 'wav', 48000, 2,
                            :semantic_hash, 'planned', :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "ep_id": episode_id,
                        "sb_id": storyboard_id,
                        "dialogue_text": foley_text,
                        "clean_text": foley_text,
                        "srt_timing": shot_timecode,
                        "dur": shot_dur,
                        "semantic_hash": f_hash,
                        "now": now_str,
                    },
                )
                sb_audio_count += 1

        log.debug(
            "【Stage7单镜六表落库】episode_id=%s, shot_num=%s, sb_id=%s -> scene_id=%s(%s), chars=%s, props=%s, audios=%s, subs=%s",
            episode_id,
            shot_num,
            storyboard_id,
            resolved_scene_id,
            raw_scene_ref,
            resolved_char_lib_ids,
            resolved_prop_ids,
            sb_audio_count,
            sb_sub_count,
        )

    log.info(
        "【Stage7六表落库完成】drama_id=%s, episode_id=%s 成功原子覆盖写入: storyboards=%d, frame_prompts=%d, chars=%d, props=%d, audios=%d, subtitles=%d",
        drama_id,
        episode_id,
        sb_count,
        fp_count,
        sb_char_count,
        sb_prop_count,
        sb_audio_count,
        sb_sub_count,
    )
    return {
        "storyboards": sb_count,
        "frame_prompts": fp_count,
        "storyboard_characters": sb_char_count,
        "storyboard_props": sb_prop_count,
        "storyboard_audios": sb_audio_count,
        "storyboard_subtitles": sb_sub_count,
    }


def _rehydrate_episode_storyboard_shots(
    db: Session,
    drama_id: int,
    episode_id: int,
) -> list[StoryboardShot]:
    """从 storyboards、storyboard_characters、storyboard_props 三表全保真反序列化还原 StoryboardShot 列表。"""
    sb_rows = fetch_all(
        db,
        "SELECT * FROM storyboards WHERE episode_id = :epid AND deleted_at IS NULL ORDER BY storyboard_number ASC",
        {"epid": episode_id},
    )
    if not sb_rows:
        return []

    asset_maps = _load_stage6_asset_lookup_maps(db, drama_id, episode_id=episode_id)
    scene_by_id = asset_maps["scene_by_id"]
    char_by_lib_id = asset_maps["char_by_lib_id"]
    prop_by_id = asset_maps["prop_by_id"]

    shots: list[StoryboardShot] = []
    for sb in sb_rows:
        if not isinstance(sb, dict):
            continue
        sb_id = sb.get("id")
        res = _safe_json_loads(sb.get("result"), {})
        if not isinstance(res, dict):
            res = {}
        srt_dyn = _safe_json_loads(sb.get("srt_dynamics"), {})
        if not isinstance(srt_dyn, dict):
            srt_dyn = {}
        audio_stem = _safe_json_loads(sb.get("audio_stem_params"), {})
        if not isinstance(audio_stem, dict):
            audio_stem = {}

        # 1. 恢复场景资产关联（优先使用三级切片 scene_asset_key，再到 result JSON 与 scenes 主表）
        scene_asset_id = str(sb.get("scene_asset_key") or res.get("scene_asset_id") or "").strip()
        sb_scene_id = sb.get("scene_id") or res.get("resolved_scene_id")
        if not scene_asset_id and isinstance(sb_scene_id, int) and sb_scene_id in scene_by_id:
            s_info = scene_by_id[sb_scene_id]
            scene_asset_id = str(s_info.get("benchmark_asset_key") or s_info.get("scene_code") or f"ENV_{sb_scene_id}")

        # 2. 恢复角色资产关联（结合 result JSON 与 storyboard_characters 表中三级切片 asset_key）
        char_asset_ids: list[str] = [
            str(x).strip() for x in (res.get("character_asset_ids") or []) if str(x).strip()
        ]
        if isinstance(sb_id, int) and char_by_lib_id:
            try:
                sc_rows = fetch_all(
                    db,
                    "SELECT character_id, asset_key FROM storyboard_characters WHERE storyboard_id = :sb_id ORDER BY slot_order ASC, id ASC",
                    {"sb_id": sb_id},
                )
                for scr in sc_rows or []:
                    c_key = str(scr.get("asset_key") or "").strip()
                    cid = scr.get("character_id") if isinstance(scr, dict) else None
                    if not c_key and isinstance(cid, int) and cid in char_by_lib_id:
                        c_key = str(char_by_lib_id[cid].get("benchmark_asset_key") or f"CHAR_{cid}")
                    if c_key and c_key not in char_asset_ids:
                        char_asset_ids.append(c_key)
            except Exception:
                pass

        # 3. 恢复道具资产关联（结合 result JSON 与 storyboard_props 表中三级切片 asset_key）
        prop_asset_ids: list[str] = [
            str(x).strip() for x in (res.get("prop_asset_ids") or []) if str(x).strip()
        ]
        if isinstance(sb_id, int) and prop_by_id:
            try:
                sp_rows = fetch_all(
                    db,
                    "SELECT prop_id, asset_key FROM storyboard_props WHERE storyboard_id = :sb_id ORDER BY slot_order ASC, id ASC",
                    {"sb_id": sb_id},
                )
                for spr in sp_rows or []:
                    p_key = str(spr.get("asset_key") or "").strip()
                    pid = spr.get("prop_id") if isinstance(spr, dict) else None
                    if not p_key and isinstance(pid, int) and pid in prop_by_id:
                        p_key = str(prop_by_id[pid].get("benchmark_asset_key") or f"PROP_{pid}")
                    if p_key and p_key not in prop_asset_ids:
                        prop_asset_ids.append(p_key)
            except Exception:
                pass

        srt_timing_val = str(
            res.get("srt_timing")
            or srt_dyn.get("srt_timing")
            or sb.get("srt_timing")
            or ""
        )
        timecode_val = (
            srt_timing_val
            or str(sb.get("time") or "")
            or f"00:00:00,000 --> 00:00:{int(sb.get('duration') or 3):02d},000"
        )
        audio_dict = (
            res.get("audio")
            or audio_stem.get("audio")
            or {"dialogue": sb.get("dialogue", ""), "narration": sb.get("narration", "")}
        )
        img_prompt_val = str(
            sb.get("image_prompt")
            or res.get("image_prompt")
            or res.get("visual_description")
            or sb.get("description")
            or ""
        )

        shot = StoryboardShot(
            shot_id=int(sb.get("storyboard_number") or 1),
            timecode=timecode_val,
            duration_sec=float(sb.get("duration") or 3.0),
            framing=str(sb.get("shot_type") or "MCU 中近景"),
            camera_motion=str(sb.get("movement") or "Static"),
            generation_mode=str(sb.get("creation_mode") or "single_frame_dynamic"),
            image_prompt=img_prompt_val,
            video_prompt=str(sb.get("video_prompt") or ""),
            srt_text=str(res.get("srt_text") or srt_dyn.get("srt_text") or sb.get("srt_text") or sb.get("dialogue") or ""),
            srt_timing=srt_timing_val,
            dynamic_cue=str(sb.get("dynamic_cue") or res.get("dynamic_cue") or sb.get("action") or ""),
            music_cue=str(sb.get("music_cue") or res.get("music_cue") or audio_stem.get("music_cue") or ""),
            foley_cue=str(sb.get("foley_cue") or res.get("foley_cue") or sb.get("atmosphere") or ""),
            selection_rationale=res.get("selection_rationale") or "",
            target_engine=str(res.get("target_engine") or "wan3.0"),
            rationale=str(res.get("rationale") or ""),
            first_last_config=res.get("first_last_config"),
            multi_image_config=res.get("multi_image_config"),
            audio=audio_dict,
            lipsync_dynamics=res.get("lipsync_dynamics") or srt_dyn.get("lipsync_dynamics"),
            speech_inpoint_sec=res.get("speech_inpoint_sec") if res.get("speech_inpoint_sec") is not None else srt_dyn.get("speech_inpoint_sec"),
            contextual_tts_prompt=res.get("contextual_tts_prompt") or srt_dyn.get("contextual_tts_prompt"),
            is_dialogue_complete_in_shot=bool(
                res.get("is_dialogue_complete_in_shot", srt_dyn.get("is_dialogue_complete_in_shot", True))
            ),
            scene_asset_id=scene_asset_id,
            character_asset_ids=char_asset_ids,
            prop_asset_ids=prop_asset_ids,
        )
        shots.append(shot)

    log.debug(
        "【Stage7三表水合完成】drama_id=%s, episode_id=%s -> 成功还原 %d 个全保真 StoryboardShot 镜头",
        drama_id,
        episode_id,
        len(shots),
    )
    return shots


def persist_stage7(
    db: Session,
    drama_id: int,
    state: EpisodeScopedSubState | GlobalDramaMasterState | Any,
    episode_num: int | None = None,
) -> None:
    """阶段 7 原子落库：六表联动写入 storyboards / frame_prompts / storyboard_characters / storyboard_props / storyboard_audios / storyboard_subtitles 与 SRT 导出。"""
    curr_ep = episode_num or getattr(state, "episode_number", None) or getattr(state, "episode_num", None) or getattr(state, "current_visual_episode", 1) or 1
    log.info("【阶段 7 落库】开始持久化短剧 [%s] 第 %s 集的分镜六表联动数据与 SRT...", drama_id, curr_ep)
    now = now_iso()

    ep_row = fetch_one(
        db,
        "SELECT id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
        {"drama_id": drama_id, "ep_num": curr_ep},
    )
    if not ep_row:
        log.warning("【阶段 7 落库】未找到第 %s 集，跳过分镜写入", curr_ep)
        return

    episode_id = ep_row["id"]
    storyboards: list[Any] = []
    if hasattr(state, "storyboard_shots") and isinstance(state.storyboard_shots, list) and state.storyboard_shots:
        storyboards = state.storyboard_shots
    elif isinstance(getattr(state, "storyboards", None), list) and state.storyboards:
        storyboards = state.storyboards
    elif isinstance(getattr(state, "storyboards", None), dict):
        storyboards = state.storyboards.get(curr_ep, [])
    elif hasattr(state, "episode_storyboards") and isinstance(state.episode_storyboards, dict):
        storyboards = state.episode_storyboards.get(curr_ep, [])
    elif hasattr(state, "storyboard_executions") and isinstance(state.storyboard_executions, dict):
        storyboards = state.storyboard_executions.get(curr_ep, [])

    if hasattr(state, "srt_content") and getattr(state, "srt_content", ""):
        srt_export = state.srt_content
    elif hasattr(state, "srt_script") and getattr(state, "srt_script", ""):
        srt_export = state.srt_script
    else:
        srt_export = (
            getattr(state, "srt_exports", {}).get(curr_ep, "")
            or getattr(state, "episode_srt_exports", {}).get(curr_ep, "")
        )

    # 更新 episodes 的 srt_export 与 mode_b_manifest_check
    ep_ast = _safe_json_loads(ep_row.get("ast_blocks"), {})
    ep_ast["srt_export"] = srt_export
    mode_b_checks = getattr(state, "episode_mode_b_manifest_checks", {}) or getattr(state, "mode_b_manifest_checks", {})
    if mode_b_checks and curr_ep in mode_b_checks:
        ep_ast["mode_b_manifest_check"] = mode_b_checks[curr_ep]
    elif isinstance(getattr(state, "mode_b_manifest_check", None), dict) and getattr(state, "mode_b_manifest_check", None):
        ep_ast["mode_b_manifest_check"] = state.mode_b_manifest_check
    db.execute(
        text("UPDATE episodes SET ast_blocks = :ast_blocks, updated_at = :now WHERE id = :id"),
        {"id": episode_id, "ast_blocks": json.dumps(ep_ast, ensure_ascii=False), "now": now},
    )

    # 调用三表联动原子持久化（storyboards + storyboard_characters + storyboard_props）
    _persist_episode_storyboards_3tables(
        db=db,
        drama_id=drama_id,
        episode_id=episode_id,
        storyboards=storyboards,
        status="draft",
        now=str(now),
    )

    def _s_get(s: Any, key: str, default: Any = None) -> Any:
        if isinstance(s, dict):
            return s.get(key, default)
        return getattr(s, key, default)

    # 长期记忆自动入库与向量化（分镜视听指导与精确SRT）
    if storyboards:
        sb_summary_lines = []
        for s in storyboards[:15]:
            s_num = _s_get(s, "shot_id") or _s_get(s, "storyboard_number") or ""
            s_frame = _s_get(s, "framing") or _s_get(s, "shot_type") or ""
            s_motion = _s_get(s, "camera_motion") or _s_get(s, "movement") or ""
            s_prompt = str(_s_get(s, "image_prompt") or "")[:60]
            s_srt = _s_get(s, "srt_text") or _s_get(s, "dialogue") or ""
            sb_summary_lines.append(f"镜头{s_num} [{s_frame} / {s_motion}]: 画面[{s_prompt}...] 台词[{s_srt}]")
        stage7_memories = [
            {
                "title": f"第{curr_ep}集单帧分镜视听指导与精确SRT",
                "content": f"第{curr_ep}集分镜概况(共{len(storyboards)}镜):\n" + "\n".join(sb_summary_lines),
                "summary": f"第{curr_ep}集分镜共{len(storyboards)}镜，已生成精准SRT字幕",
                "keywords": [f"第{curr_ep}集", "分镜提示词", "运镜", "SRT字幕"],
                "memory_type": "storyboard_spec",
                "source_type": "stage7_storyboards",
                "source_id": f"ep_storyboards_{curr_ep}",
            }
        ]
        sync_stage_memories_to_vector_db(db, drama_id, 7, stage7_memories)

    db.execute(
        text("UPDATE dramas SET current_stage = 7, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 7, state.latest_audit)

    db.commit()
    log.info("【阶段 7 落库】成功完成并已提交事务。")


# =========================================================================
# 阶段 8：全息声学混音工程持久化
# =========================================================================

