"""阶段 6 角色三层模型深度原子落库组件 (Stage 6 Character 3-Tier Persister)。

严格遵循工业化三层规范与四段式资产协议持久化角色：
- Tier 1: 自然人核心实体 (characters)；
- Tier 2: 角色造型形态阶段 (character_stages)；
- Tier 3: 角色各形态切片基准视图 (character_stage_views)；
- Relation: 单集登场关联绑定 (episode_characters)。
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.type_utils import safe_int
from app.core.logger import get_logger
from app.tools.screenplay_feature_scanner import is_valid_character_speaker
from app.workflows.adapters.stage_adapters.common import (
    _dump_or_dict,
    _ensure_valid_json_str,
    _safe_json_loads,
    fetch_all,
    fetch_one,
)
from app.workflows.adapters.stage_adapters.stage6.helpers import (
    clean_character_name,
    extract_character_tokens,
    extract_natural_appearance,
    find_canonical_entity,
    parse_character_view_type,
    synthesize_character_literary_defaults,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

log = get_logger("lmd.storage_adapter.stage6.character")


def persist_stage6_characters(
    db: Session,
    drama_id: int,
    curr_ep: int,
    episode_id: int | None,
    now: str,
    characters_manifest: list[dict[str, Any]],
    newly_discovered_characters: list[dict[str, Any]],
    newly_generated_assets: list[dict[str, Any]],
    reused_assets_data: list[dict[str, Any]],
    manifest_dict: dict[str, Any],
    state: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """持久化阶段 6 角色领域三层模型与关系映射。

    Returns:
        tuple of (canonical_map, canonical_by_code, canonical_by_name, stage_db_ids_by_code, asset_character_meta_map)
    """
    # 2.1 汇集所有角色候选源 (引单 + 生成资产 + 引擎状态池)
    raw_character_candidates: list[dict[str, Any]] = []
    seen_candidate_keys: set[str] = set()

    # 提取上游各阶段注入的文学画像状态池 (characters_engine, character_engine, characters, newly_discovered_characters)
    engine_char_pool: dict[str, dict[str, Any]] = {}
    raw_pools: list[Any] = []
    for attr in ("characters_engine", "character_engine", "characters"):
        val = getattr(state, attr, None)
        if isinstance(val, dict):
            raw_pools.extend(val.get("characters") or val.get("character_profiles") or [])
        elif isinstance(val, list):
            raw_pools.extend(val)
    if newly_discovered_characters:
        raw_pools.extend(newly_discovered_characters)

    for item in raw_pools:
        item_dict = _dump_or_dict(item)
        if not isinstance(item_dict, dict):
            continue
        c_name = str(item_dict.get("name") or item_dict.get("character_name") or "").strip()
        c_code = str(item_dict.get("character_code") or item_dict.get("char_id") or "").strip()
        clean_n = clean_character_name(c_name)
        if c_name:
            engine_char_pool[c_name] = item_dict
            engine_char_pool[c_name.lower()] = item_dict
        if clean_n:
            engine_char_pool[clean_n] = item_dict
            engine_char_pool[clean_n.lower()] = item_dict
        if c_code:
            engine_char_pool[c_code] = item_dict
            engine_char_pool[c_code.upper()] = item_dict
            stripped = c_code.replace("CHAR_", "")
            engine_char_pool[stripped] = item_dict
            engine_char_pool[f"CHAR_{stripped}"] = item_dict

    log.debug(
        "【阶段 6 落库】[Tier 1 状态池检索] 预装载上游角色文学引擎档案索引项数: %s (含本集新发现未登记角色: %d)",
        len(engine_char_pool), len(newly_discovered_characters),
    )

    # 优先装填本集新发现未登记角色 (确保 11 维全息字段优先确立 canonical_map 实体)
    for ndc in newly_discovered_characters:
        if isinstance(ndc, dict):
            k = str(ndc.get("character_code") or ndc.get("char_id") or ndc.get("name") or "").strip()
            if k:
                seen_candidate_keys.add(k)
            raw_character_candidates.append(ndc)

    for c_raw in characters_manifest:
        c = _dump_or_dict(c_raw)
        if isinstance(c, dict):
            k = str(c.get("char_id") or c.get("asset_id") or c.get("asset_key") or c.get("character_code") or c.get("name") or "").strip()
            if k:
                seen_candidate_keys.add(k)
            raw_character_candidates.append(c)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or n_dict.get("asset_key") or "")
        if (cat == "character" or aid.startswith("CHAR_")):
            if aid not in seen_candidate_keys:
                seen_candidate_keys.add(aid)
                raw_character_candidates.append(n_dict)

    # 【重要架构守卫】：raw_pools (characters_engine 全量库) 仅作为只读画像字典 (engine_char_pool) 用于回填
    # 当集登场角色的 11 维背景属性，【严禁】无条件将其全局角色注入 raw_character_candidates！
    # 否则不在本集中的全剧角色（如其他集配角）会被当成本集在场角色派生 Tier 2 造型并写入 episode_asset_usages。
    log.debug(
        "【阶段 6 落库·边界守卫】当集待落库角色候选收敛完毕: 仅收录引单/新资产/新发现角色，共计 %d 项 (已阻断全剧 %d 名全量角色池盲目渗透)",
        len(raw_character_candidates), len(raw_pools),
    )

    # 2.2 预查已登记角色库构建内存索引（包含阶段 2 的 11 维全息字段）
    existing_chars_in_db = fetch_all(
        db,
        """
        SELECT id, character_code, name, appearance, voice_style, role, description,
               personality, gender, perceived_age, identity_anchors,
               visual_consistency_code, carried_anchor_item, drama_engine,
               growth_chain, current_status,
               psychology_4, acoustic_persona, voice_fingerprint
        FROM characters
        WHERE drama_id = :drama_id
        """,
        {"drama_id": drama_id},
    )
    db_char_by_name: dict[str, dict[str, Any]] = {row["name"]: row for row in existing_chars_in_db if row.get("name")}
    db_char_by_code: dict[str, dict[str, Any]] = {row["character_code"]: row for row in existing_chars_in_db if row.get("character_code")}
    db_char_by_stripped_code: dict[str, dict[str, Any]] = {
        row["character_code"].replace("CHAR_", ""): row
        for row in existing_chars_in_db if row.get("character_code")
    }

    # 2.3 内存三层模型规范化归纳聚合 (Canonical Entity Aggregation)
    canonical_map: dict[str, dict[str, Any]] = {}

    for c in raw_character_candidates:
        raw_name = str(c.get("character_name") or c.get("name") or "").strip()
        raw_code = str(c.get("character_code") or c.get("char_id") or c.get("asset_id") or c.get("asset_key") or "").strip()
        if not raw_name and not raw_code:
            continue

        parsed_code, parsed_stage, parsed_view = extract_character_tokens(raw_code)
        clean_name = clean_character_name(raw_name)

        # 匹配既有数据库角色
        matched_db = None
        if clean_name and clean_name in db_char_by_name:
            matched_db = db_char_by_name[clean_name]
        elif raw_name and raw_name in db_char_by_name:
            matched_db = db_char_by_name[raw_name]
        elif raw_code and raw_code in db_char_by_code:
            matched_db = db_char_by_code[raw_code]
        elif parsed_code and parsed_code in db_char_by_stripped_code:
            matched_db = db_char_by_stripped_code[parsed_code]
        elif parsed_code and f"CHAR_{parsed_code}" in db_char_by_code:
            matched_db = db_char_by_code[f"CHAR_{parsed_code}"]

        # 匹配上游引擎画像 (characters_engine / character_engine / characters)
        matched_engine = (
            engine_char_pool.get(clean_name)
            or engine_char_pool.get(clean_name.lower())
            or engine_char_pool.get(raw_name)
            or engine_char_pool.get(raw_name.lower())
            or engine_char_pool.get(raw_code)
            or engine_char_pool.get(raw_code.upper())
            or (engine_char_pool.get(parsed_code) if parsed_code else None)
        )

        # 确立规范化自然人属性 (Tier 1 Entity)
        if matched_db:
            char_name = matched_db["name"]
            char_code = matched_db["character_code"]
            existing_db_id = matched_db["id"]
        elif matched_engine:
            char_name = matched_engine.get("name") or clean_name or raw_name or "未命名角色"
            char_code = matched_engine.get("character_code") or (f"CHAR_{parsed_code}" if parsed_code else (raw_code if raw_code.startswith("CHAR_") else f"CHAR_{char_name}"))
            existing_db_id = None
        else:
            char_name = clean_name or (parsed_code if parsed_code else (raw_code if raw_code else "未命名角色"))
            char_code = f"CHAR_{parsed_code}" if parsed_code else (raw_code if raw_code.startswith("CHAR_") else f"CHAR_{char_name}")
            existing_db_id = None

        # 对未在数据库登记的新角色候选进行合法性守卫：拦截声学/舞台指令或括号残片（如 "[声学行为"）
        if not matched_db and raw_name and not is_valid_character_speaker(clean_name or raw_name, known_names=set(db_char_by_name.keys())):
            log.warning(
                "【阶段 6 落库·脏数据拦截】跳过非法角色名/舞台指令候选: raw_name=%s, clean_name=%s, raw_code=%s",
                raw_name, clean_name, raw_code,
            )
            continue

        entity_key = char_name.lower()
        visual_prompt = str(c.get("visual_prompt") or c.get("appearance") or c.get("prompt") or "").strip()
        cleaned_bio_appearance = extract_natural_appearance(visual_prompt, char_name)

        if entity_key not in canonical_map:
            raw_g = str(
                c.get("gender")
                or (matched_engine.get("gender") if matched_engine else "")
                or (matched_db.get("gender") if matched_db else "")
                or ""
            ).strip().lower()
            if raw_g in ("女", "female", "f"):
                gender = "female"
            elif raw_g in ("男", "male", "m"):
                gender = "male"
            elif raw_g == "other":
                gender = "other"
            else:
                gender = "female" if any(kw in (visual_prompt + char_name) for kw in ("女", "母", "姐", "妹", "妻", "妃", "后", "裙")) else "male"

            raw_age = (
                c.get("perceived_age")
                or (matched_engine.get("perceived_age") if matched_engine else None)
                or (matched_db.get("perceived_age") if matched_db else None)
            )
            if isinstance(raw_age, (int, float)):
                perceived_age = int(raw_age)
            elif raw_age:
                m_age = re.search(r"\d+", str(raw_age))
                perceived_age = int(m_age.group()) if m_age else None
            else:
                perceived_age = None

            role = str(
                c.get("role")
                or (matched_engine.get("role") if matched_engine else "")
                or (matched_db.get("role") if matched_db else "")
                or "supporting"
            ).strip()

            desc = str(
                c.get("description")
                or (matched_engine.get("description") if matched_engine else "")
                or (matched_db.get("description") if matched_db else "")
                or ""
            ).strip()

            personality = str(
                c.get("personality")
                or (matched_engine.get("personality") if matched_engine else "")
                or (matched_db.get("personality") if matched_db else "")
                or ""
            ).strip()

            appearance = (
                (matched_engine.get("appearance") if matched_engine else "")
                or (matched_db.get("appearance") if matched_db else "")
                or cleaned_bio_appearance
            ).strip()

            voice_style = str(
                c.get("voice_style")
                or (matched_engine.get("voice_style") if matched_engine else "")
                or (matched_db.get("voice_style") if matched_db else "")
                or ""
            ).strip()

            psychology_4 = (
                c.get("psychology_4") or c.get("psychological_quad")
                or (matched_engine.get("psychology_4") or matched_engine.get("psychological_quad") if matched_engine else None)
                or (matched_db.get("psychology_4") if matched_db else None)
            )

            acoustic_persona = (
                c.get("acoustic_persona")
                or (matched_engine.get("acoustic_persona") if matched_engine else None)
                or (matched_db.get("acoustic_persona") if matched_db else None)
            )

            voice_fingerprint = (
                c.get("voice_fingerprint")
                or (matched_engine.get("voice_fingerprint") if matched_engine else None)
                or (matched_db.get("voice_fingerprint") if matched_db else None)
            )

            identity_anchors = (
                c.get("identity_anchors")
                or (matched_engine.get("identity_anchors") if matched_engine else None)
                or (matched_db.get("identity_anchors") if matched_db else None)
            )

            visual_consistency_code = (
                c.get("visual_consistency_code")
                or (matched_engine.get("visual_consistency_code") if matched_engine else None)
                or (matched_db.get("visual_consistency_code") if matched_db else None)
            )
            carried_anchor_item = (
                c.get("carried_anchor_item")
                or (matched_engine.get("carried_anchor_item") if matched_engine else None)
                or (matched_db.get("carried_anchor_item") if matched_db else None)
            )
            drama_engine = (
                c.get("drama_engine")
                or (matched_engine.get("drama_engine") if matched_engine else None)
                or (matched_db.get("drama_engine") if matched_db else None)
            )
            growth_chain = (
                c.get("growth_chain")
                or (matched_engine.get("growth_chain") if matched_engine else None)
                or (matched_db.get("growth_chain") if matched_db else None)
            )
            current_status = (
                c.get("current_status")
                or (matched_engine.get("current_status") if matched_engine else None)
                or (matched_db.get("current_status") if matched_db else None)
            )
            new_relationships = (
                c.get("new_relationships")
                or (matched_engine.get("new_relationships") if matched_engine else None)
                or []
            )

            # 智能合成保底文学/心理/声音画像（防止字段出现 NULL 或空值，完全对齐阶段 2 11 维建档规格）
            lit_defaults = synthesize_character_literary_defaults(
                char_name=char_name,
                gender=gender,
                role=role,
                appearance=appearance,
                perceived_age=perceived_age,
                curr_ep=curr_ep,
            )
            if not desc or desc == f"第{curr_ep}集登场角色":
                desc = lit_defaults["description"]
            if not personality:
                personality = lit_defaults["personality"]
            if not appearance:
                appearance = lit_defaults["appearance"]
            if not psychology_4 or psychology_4 == {} or psychology_4 == "{}":
                psychology_4 = lit_defaults["psychology_4"]
            if not voice_style:
                voice_style = lit_defaults["voice_style"]
            if not acoustic_persona or acoustic_persona == {} or acoustic_persona == "{}":
                acoustic_persona = lit_defaults["acoustic_persona"]
            if not voice_fingerprint or voice_fingerprint == {} or voice_fingerprint == "{}":
                voice_fingerprint = lit_defaults["voice_fingerprint"]
            if not identity_anchors:
                identity_anchors = [appearance[:60] or f"{char_name}面部与装造生理锚点"]
            if not visual_consistency_code:
                visual_consistency_code = {
                    "base_face_lock": appearance[:80] or f"{char_name}面部骨骼特征锚定",
                    "default_costume_lock": f"第{curr_ep}集标准日常造型",
                    "skin_texture": "真实微瑕皮肤，清晰毛孔与自然高光，杜绝磨皮塑料感",
                }
            if not carried_anchor_item:
                carried_anchor_item = {
                    "item_name": f"{char_name}随身信物",
                    "visual_detail": "带有岁月摩挲痕迹与剧情线索的贴身小物件",
                }
            if not drama_engine:
                drama_engine = {
                    "core_motivation": f"在第{curr_ep}集冲突中守护核心利益并推动剧情转折",
                    "fatal_weakness": "对关键秘密或人际软肋的隐瞒",
                }
            if not growth_chain:
                growth_chain = [{
                    "episode": curr_ep,
                    "phase": f"第{curr_ep}集初登场建档",
                    "state": "卷入当前集核心戏剧冲突",
                }]
            if not current_status:
                current_status = {
                    "onboarded_at_episode": curr_ep,
                    "physical_state": "normal",
                    "emotional_state": "alert",
                }

            identity_anchors_str = _ensure_valid_json_str(identity_anchors, "[]")
            visual_consistency_code_str = _ensure_valid_json_str(
                visual_consistency_code,
                "{}",
                wrap_key="base_face_lock",
            )
            carried_anchor_item_str = _ensure_valid_json_str(
                carried_anchor_item,
                "{}",
                wrap_key="item_name",
            )
            drama_engine_str = _ensure_valid_json_str(
                drama_engine,
                "{}",
                wrap_key="core_motivation",
            )
            growth_chain_str = _ensure_valid_json_str(growth_chain, "[]")
            current_status_str = _ensure_valid_json_str(
                current_status,
                "{}",
                wrap_key="state",
            )
            psychology_4_str = _ensure_valid_json_str(
                psychology_4,
                "{}",
                wrap_key="summary",
            )
            acoustic_persona_str = _ensure_valid_json_str(
                acoustic_persona,
                "{}",
                wrap_key="tone",
            )
            voice_fingerprint_str = _ensure_valid_json_str(
                voice_fingerprint,
                "{}",
                wrap_key="catchphrase",
            )

            canonical_map[entity_key] = {
                "db_id": existing_db_id,
                "char_name": char_name,
                "char_code": char_code,
                "gender": gender,
                "perceived_age": perceived_age,
                "role": role,
                "description": desc,
                "personality": personality,
                "appearance": appearance,
                "identity_anchors": identity_anchors_str,
                "visual_consistency_code": visual_consistency_code_str,
                "carried_anchor_item": carried_anchor_item_str,
                "drama_engine": drama_engine_str,
                "growth_chain": growth_chain_str,
                "current_status": current_status_str,
                "voice_style": voice_style,
                "psychology_4": psychology_4_str,
                "acoustic_persona": acoustic_persona_str,
                "voice_fingerprint": voice_fingerprint_str,
                "new_relationships": new_relationships if isinstance(new_relationships, list) else [],
                "stages": {},
            }
            log.debug(
                "【阶段 6 落库】[Tier 1 规范化归纳] 登记 11 维实体 [%s]: 代号=%s, 性别=%s, 定位=%s, 外貌字数=%s, 心理画像状态=%s, 新增关系数=%d",
                char_name, char_code, gender, role, len(appearance), "已具备" if psychology_4_str else "无",
                len(new_relationships) if isinstance(new_relationships, list) else 0,
            )
        else:
            ent = canonical_map[entity_key]
            if ent.get("perceived_age") is None:
                r_age = c.get("perceived_age") or (matched_engine.get("perceived_age") if matched_engine else None)
                if isinstance(r_age, (int, float)):
                    ent["perceived_age"] = int(r_age)
                elif r_age:
                    m_age = re.search(r"\d+", str(r_age))
                    if m_age:
                        ent["perceived_age"] = int(m_age.group())
            if (not ent.get("appearance") or len(ent.get("appearance")) < 5) and cleaned_bio_appearance:
                ent["appearance"] = cleaned_bio_appearance
            if not ent.get("voice_style"):
                vs = str(c.get("voice_style") or (matched_engine.get("voice_style") if matched_engine else "") or "").strip()
                if vs:
                    ent["voice_style"] = vs
            if not ent.get("personality"):
                p = str(c.get("personality") or (matched_engine.get("personality") if matched_engine else "") or "").strip()
                if p:
                    ent["personality"] = p
            if not ent.get("description"):
                d = str(c.get("description") or (matched_engine.get("description") if matched_engine else "") or "").strip()
                if d:
                    ent["description"] = d

        # 确立二级形态阶段 (Tier 2 Stage) 并彻底规范化
        # 严格解决 "Tier1", "Stage_1", "stage1", "T1", "BASE" 等命名异构导致无法识别为 T1 基准形态的问题，
        # 同时保留自定义阶段代号（如 STAGE_PRINCE_NORMAL, STAGE_PRINCE_KNEELING 等）
        raw_stage_val = str(
            c.get("stage_code")
            or c.get("tier")
            or parsed_stage
            or ("T1" if "_T1_" in raw_code or "BASE" in raw_code else "")
        ).strip()
        if not raw_stage_val:
            st_m = re.search(r"_(T\d+)_", raw_code)
            raw_stage_val = st_m.group(1).upper() if st_m else "T1"

        # 规范化：若属于 Tier/Stage 序数命名（如 Tier1, Stage_1, t1, s2），统一规范化为 T1, T2 等；
        # 否则保留显式给定的阶段代号（如 STAGE_PRINCE_NORMAL）
        m_tier = re.match(r"^(?:TIER|STAGE|T|S)[_\-\s]*(\d+)$", raw_stage_val, re.IGNORECASE)
        if m_tier:
            stage_code = f"T{m_tier.group(1)}"
        elif raw_stage_val.upper() in ("BASE", "BASE_PORTRAIT", "PORTRAIT", "T1_BASE"):
            stage_code = "T1"
        else:
            stage_code = raw_stage_val

        stage_name = str(c.get("stage_name") or c.get("appearance_variant") or c.get("outfit") or "").strip()
        if not stage_name:
            b_m = re.search(r"[\(（\[【]([^\)）\]】]+)[\)）\]】]", raw_name)
            if b_m:
                b_val = b_m.group(1).strip()
                if not any(k in b_val for k in ("定妆", "肖像", "特写", "视图", "切片", "微距", "立绘")):
                    stage_name = b_val
        if not stage_name:
            stage_name = f"{char_name}_{stage_code}造型" if stage_code not in ("T1", "BASE") else f"第{curr_ep}集造型"

        parent_ref = c.get("parent_stage_id") or c.get("parent_asset_id") or c.get("parent_stage_code") or c.get("parent_stage_name") or ""
        costume_desc = str(c.get("costume_description") or c.get("visual_prompt") or c.get("appearance") or c.get("prompt") or "").strip()
        color_palette = c.get("color_palette")
        color_palette_str = json.dumps(color_palette, ensure_ascii=False) if isinstance(color_palette, (dict, list)) else (str(color_palette) if color_palette else None)

        stages_dict = canonical_map[entity_key]["stages"]
        if stage_code not in stages_dict:
            stages_dict[stage_code] = {
                "stage_code": stage_code,
                "stage_name": stage_name,
                "parent_stage_ref": parent_ref,
                "costume_description": costume_desc,
                "color_palette": color_palette_str,
                "views": {},
            }
        else:
            st_data = stages_dict[stage_code]
            if not st_data.get("parent_stage_ref") and parent_ref:
                st_data["parent_stage_ref"] = parent_ref
            if not st_data.get("costume_description") and costume_desc:
                st_data["costume_description"] = costume_desc

        # 确立三级切片视图 (Tier 3 Slices)
        raw_view_type = c.get("view_type")
        token = raw_view_type or parsed_view or c.get("function_type") or raw_code
        explicit_label = c.get("view_label") or c.get("slice_name") or raw_name
        view_type, default_label, is_primary = parse_character_view_type(token, explicit_label)

        # 若原结构携带了显式 view_type 但经过解析属于 main_portrait 范畴，统一标准化为 main_portrait
        if raw_view_type:
            raw_vt_norm, norm_lbl, norm_prim = parse_character_view_type(str(raw_view_type).strip(), explicit_label)
            view_type = raw_vt_norm
            is_primary = norm_prim

        view_prompt = str(c.get("prompt") or c.get("image_prompt") or c.get("visual_prompt") or c.get("appearance") or "").strip()
        neg_prompt = str(c.get("negative_prompt") or "").strip() or None
        image_url = str(c.get("image_url") or c.get("url") or "").strip() or None
        local_path = str(c.get("local_path") or "").strip() or None
        seedance2_id = str(c.get("seedance2_asset_id") or "").strip() or None
        asset_key = str(c.get("asset_key") or c.get("asset_id") or raw_code or "").strip()
        c_parent_key = c.get("parent_asset_key") or c.get("parent_asset_id")
        c_gen_mode = c.get("generation_mode")
        c_denoise = c.get("denoise_strength") if c.get("denoise_strength") is not None else c.get("recommended_denoise")
        c_ctrl_type = c.get("control_type")
        c_is_bench = c.get("is_benchmark")

        st_views = stages_dict[stage_code]["views"]
        if view_type not in st_views:
            st_views[view_type] = {
                "view_type": view_type,
                "view_label": explicit_label or default_label,
                "image_prompt": view_prompt,
                "negative_prompt": neg_prompt,
                "image_url": image_url,
                "local_path": local_path,
                "seedance2_asset_id": seedance2_id,
                "is_primary": is_primary,
                "asset_keys": [asset_key] if asset_key else [],
                "parent_asset_key": c_parent_key,
                "generation_mode": c_gen_mode,
                "denoise_strength": c_denoise,
                "control_type": c_ctrl_type,
                "is_benchmark": c_is_bench,
            }
        else:
            v_entry = st_views[view_type]
            if view_prompt:
                v_entry["image_prompt"] = view_prompt
            if not v_entry.get("image_url") and image_url:
                v_entry["image_url"] = image_url
            if not v_entry.get("local_path") and local_path:
                v_entry["local_path"] = local_path
            if asset_key and asset_key not in v_entry["asset_keys"]:
                v_entry["asset_keys"].append(asset_key)
            if not v_entry.get("parent_asset_key") and c_parent_key:
                v_entry["parent_asset_key"] = c_parent_key
            if not v_entry.get("generation_mode") and c_gen_mode:
                v_entry["generation_mode"] = c_gen_mode
            if v_entry.get("denoise_strength") is None and c_denoise is not None:
                v_entry["denoise_strength"] = c_denoise
            if not v_entry.get("control_type") and c_ctrl_type:
                v_entry["control_type"] = c_ctrl_type

        # 兼容 Table 6 嵌套双字段 (base_portrait / base_costume)
        bp_ref = str(c.get("base_portrait") or "").strip()
        if bp_ref:
            if "main_portrait" not in st_views:
                st_views["main_portrait"] = {
                    "view_type": "main_portrait",
                    "view_label": "正面主视觉基准切片",
                    "image_prompt": view_prompt,
                    "negative_prompt": neg_prompt,
                    "image_url": image_url,
                    "local_path": local_path,
                    "seedance2_asset_id": seedance2_id,
                    "is_primary": 1,
                    "asset_keys": [bp_ref],
                    "parent_asset_key": None,
                    "generation_mode": "t2i",
                    "is_benchmark": 1,
                }
            elif bp_ref not in st_views["main_portrait"]["asset_keys"]:
                st_views["main_portrait"]["asset_keys"].append(bp_ref)

        bc_ref = str(c.get("base_costume") or "").strip()
        if bc_ref:
            if "full_body" not in st_views:
                st_views["full_body"] = {
                    "view_type": "full_body",
                    "view_label": "全身定妆立绘",
                    "image_prompt": costume_desc or view_prompt,
                    "negative_prompt": neg_prompt,
                    "image_url": image_url,
                    "local_path": local_path,
                    "seedance2_asset_id": seedance2_id,
                    "is_primary": 0,
                    "asset_keys": [bc_ref],
                    "parent_asset_key": bp_ref or None,
                    "generation_mode": "i2i",
                    "denoise_strength": 0.45,
                    "is_benchmark": 0,
                }
            elif bc_ref not in st_views["full_body"]["asset_keys"]:
                st_views["full_body"]["asset_keys"].append(bc_ref)

    # 规范化阶段视图：确保每阶段有且仅有一个 is_primary=1 主视觉锚点 (严格绑定 main_portrait)
    for ent in canonical_map.values():
        for st_code, st_info in ent["stages"].items():
            st_views = st_info["views"]
            if not st_views:
                st_views["main_portrait"] = {
                    "view_type": "main_portrait",
                    "view_label": "正面主视觉基准切片",
                    "image_prompt": st_info.get("costume_description") or ent.get("appearance") or "",
                    "negative_prompt": None,
                    "image_url": None,
                    "local_path": None,
                    "seedance2_asset_id": None,
                    "is_primary": 1,
                    "asset_keys": [],
                }
            elif "main_portrait" in st_views:
                st_views["main_portrait"]["is_primary"] = 1
                for vt, vi in st_views.items():
                    if vt != "main_portrait":
                        vi["is_primary"] = 0
            else:
                # 若未显式包含 main_portrait，则推举第一个视图提升为唯一主视觉，其余强制全部归零
                first_k = next(iter(st_views.keys()))
                for vt, vi in st_views.items():
                    vi["is_primary"] = 1 if vt == first_k else 0

    # 构建全局多维双向索引，支持任意凭证（中文名、代号、去前缀、归一化Token）快速索引实体
    canonical_by_name: dict[str, dict[str, Any]] = {}
    canonical_by_code: dict[str, dict[str, Any]] = {}

    for ent in canonical_map.values():
        c_name = ent["char_name"]
        c_clean_name = clean_character_name(c_name)
        c_code = ent["char_code"]
        c_code_stripped = c_code.replace("CHAR_", "", 1) if c_code.startswith("CHAR_") else c_code
        c_norm_tok = AssetProtocolHelper.normalize_token(c_code or c_name)

        if c_name:
            canonical_by_name[c_name] = ent
            canonical_by_name[c_name.lower()] = ent
        if c_clean_name:
            canonical_by_name[c_clean_name] = ent
            canonical_by_name[c_clean_name.lower()] = ent

        if c_code:
            canonical_by_code[c_code] = ent
            canonical_by_code[c_code.upper()] = ent
        if c_code_stripped:
            canonical_by_code[c_code_stripped] = ent
            canonical_by_code[c_code_stripped.upper()] = ent
        if c_norm_tok:
            canonical_by_code[c_norm_tok] = ent
            canonical_by_code[f"CHAR_{c_norm_tok}"] = ent

    log.debug(
        "【阶段 6 落库·双向索引初始化】已为 %d 位角色构建多维查找索引 (name_keys=%d, code_keys=%d)",
        len(canonical_map), len(canonical_by_name), len(canonical_by_code),
    )

    # 2.4 层级式物理落库 (Tier 1 -> Tier 2 -> Tier 3 + 集关联绑定)
    active_char_db_ids: list[int] = []
    stage_db_ids_by_code: dict[str, int] = {}
    stage_db_ids_by_name: dict[str, int] = {}
    asset_character_meta_map: dict[str, dict[str, Any]] = {}
    unresolved_stage_parents: list[dict[str, Any]] = []

    for ent_key, ent in canonical_map.items():
        char_name = ent["char_name"]
        char_code = ent["char_code"]
        char_id = ent.get("db_id")
        bench_char_key = AssetProtocolHelper.get_benchmark_key_for_character(char_code)

        # 解析本角色的 T1 基准主肖像 key（优先从 stages[T1]["views"]["main_portrait"] 提取实际 asset_keys，保底为 bench_char_key）
        canonical_bench_portrait_key = None
        for s_code_item, s_info_item in ent.get("stages", {}).items():
            if str(s_code_item).upper() in ("T1", "STAGE_1", "TIER1", "TIER_1", "BASE", "S1"):
                mp_item = s_info_item.get("views", {}).get("main_portrait")
                if mp_item:
                    ak_list = mp_item.get("asset_keys") or []
                    if ak_list:
                        canonical_bench_portrait_key = ak_list[0]
                    elif mp_item.get("asset_key"):
                        canonical_bench_portrait_key = mp_item.get("asset_key")
                break
        if not canonical_bench_portrait_key:
            canonical_bench_portrait_key = bench_char_key

        # 序列化高级心理学四象限与声学画像
        psychology_4_json = _ensure_valid_json_str(ent.get("psychology_4"), "{}", wrap_key="summary")
        acoustic_persona_json = _ensure_valid_json_str(ent.get("acoustic_persona"), "{}", wrap_key="tone")
        voice_fingerprint_json = _ensure_valid_json_str(ent.get("voice_fingerprint"), "{}", wrap_key="catchphrase")

        if char_id:
            active_char_db_ids.append(char_id)
            # =========================================================================
            # 【架构契约规约 (ISSUE-1 AS-DESIGNED)】：
            # characters 表为 Tier 1 自然人实体元数据总表，负责存储生物学骨相 (visual_consistency_code)、
            # 声音指纹 (voice_fingerprint)、心理特征与全局 benchmark_asset_key。
            # 物理机位的生图提示词 (image_prompt/polished_prompt) 严格归属于 Tier 3 视图表 character_stage_views
            # 与全局调度总表 assets。严禁向 characters 实体表写入特定机位的生图 prompt。
            # =========================================================================
            db.execute(
                text("""
                    UPDATE characters
                    SET appearance = CASE WHEN appearance IS NULL OR appearance = '' THEN :appearance ELSE appearance END,
                        voice_style = CASE WHEN voice_style IS NULL OR voice_style = '' THEN :voice_style ELSE voice_style END,
                        personality = CASE WHEN personality IS NULL OR personality = '' THEN :personality ELSE personality END,
                        description = CASE WHEN description IS NULL OR description = '' THEN :description ELSE description END,
                        identity_anchors = CASE WHEN identity_anchors IS NULL OR identity_anchors = '' THEN :identity_anchors ELSE identity_anchors END,
                        visual_consistency_code = CASE WHEN visual_consistency_code IS NULL OR visual_consistency_code = '' OR visual_consistency_code = '{}' THEN :visual_consistency_code ELSE visual_consistency_code END,
                        carried_anchor_item = CASE WHEN carried_anchor_item IS NULL OR carried_anchor_item = '' OR carried_anchor_item = '{}' THEN :carried_anchor_item ELSE carried_anchor_item END,
                        drama_engine = CASE WHEN drama_engine IS NULL OR drama_engine = '' OR drama_engine = '{}' THEN :drama_engine ELSE drama_engine END,
                        growth_chain = CASE WHEN growth_chain IS NULL OR growth_chain = '' OR growth_chain = '[]' THEN :growth_chain ELSE growth_chain END,
                        current_status = CASE WHEN current_status IS NULL OR current_status = '' OR current_status = '{}' THEN :current_status ELSE current_status END,
                        psychology_4 = CASE WHEN psychology_4 IS NULL OR psychology_4 = '' OR psychology_4 = '{}' THEN :psychology_4 ELSE psychology_4 END,
                        acoustic_persona = CASE WHEN acoustic_persona IS NULL OR acoustic_persona = '' OR acoustic_persona = '{}' THEN :acoustic_persona ELSE acoustic_persona END,
                        voice_fingerprint = CASE WHEN voice_fingerprint IS NULL OR voice_fingerprint = '' OR voice_fingerprint = '{}' THEN :voice_fingerprint ELSE voice_fingerprint END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :benchmark_asset_key != '' THEN :benchmark_asset_key ELSE benchmark_asset_key END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": char_id,
                    "appearance": ent.get("appearance") or "",
                    "voice_style": ent.get("voice_style") or "",
                    "personality": ent.get("personality") or "",
                    "description": ent.get("description") or "",
                    "identity_anchors": ent.get("identity_anchors"),
                    "visual_consistency_code": ent.get("visual_consistency_code") or "{}",
                    "carried_anchor_item": ent.get("carried_anchor_item") or "{}",
                    "drama_engine": ent.get("drama_engine") or "{}",
                    "growth_chain": ent.get("growth_chain") or "[]",
                    "current_status": ent.get("current_status") or "{}",
                    "psychology_4": psychology_4_json,
                    "acoustic_persona": acoustic_persona_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "benchmark_asset_key": bench_char_key,
                    "now": now,
                },
            )
            log.debug(
                "【阶段 6 落库】[Tier 1 角色实体] 识别并更新已登记自然人角色: ID=%s, 代号=%s, 姓名=%s, 基准键=%s",
                char_id, char_code, char_name, bench_char_key,
            )
        else:
            c_ins = db.execute(
                text("""
                    INSERT INTO characters (
                        drama_id, character_code, name, gender, perceived_age,
                        role, description, personality, appearance,
                        identity_anchors, visual_consistency_code,
                        carried_anchor_item, drama_engine, growth_chain, current_status,
                        voice_style, acoustic_persona,
                        psychology_4, voice_fingerprint, benchmark_asset_key, created_at, updated_at
                    ) VALUES (
                        :drama_id, :character_code, :name, :gender, :perceived_age,
                        :role, :description, :personality, :appearance,
                        :identity_anchors, :visual_consistency_code,
                        :carried_anchor_item, :drama_engine, :growth_chain, :current_status,
                        :voice_style, :acoustic_persona,
                        :psychology_4, :voice_fingerprint, :benchmark_asset_key, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "character_code": char_code,
                    "name": char_name,
                    "gender": ent.get("gender") or "male",
                    "perceived_age": ent.get("perceived_age"),
                    "role": ent.get("role") or "supporting",
                    "description": ent.get("description") or f"第{curr_ep}集登场角色",
                    "personality": ent.get("personality") or "",
                    "appearance": ent.get("appearance") or "",
                    "identity_anchors": ent.get("identity_anchors"),
                    "visual_consistency_code": ent.get("visual_consistency_code") or "{}",
                    "carried_anchor_item": ent.get("carried_anchor_item") or "{}",
                    "drama_engine": ent.get("drama_engine") or "{}",
                    "growth_chain": ent.get("growth_chain") or "[]",
                    "current_status": ent.get("current_status") or "{}",
                    "voice_style": ent.get("voice_style") or "",
                    "acoustic_persona": acoustic_persona_json,
                    "psychology_4": psychology_4_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "benchmark_asset_key": bench_char_key,
                    "now": now,
                },
            )
            char_id = safe_int(getattr(c_ins, "lastrowid", None), default=1)
            ent["db_id"] = char_id
            active_char_db_ids.append(char_id)
            db_char_by_name[char_name] = {"id": char_id, "character_code": char_code, "name": char_name}
            db_char_by_code[char_code] = {"id": char_id, "character_code": char_code, "name": char_name}
            log.info(
                "【阶段 6 落库】[Tier 1 角色实体] 增量角色按阶段 2 11 维标准自动建档入库: ID=%s, 代号=%s, 姓名=%s, 基准键=%s",
                char_id, char_code, char_name, bench_char_key,
            )

        # 级联落库新角色双轨关系矩阵 (character_relationship)
        for rel_raw in ent.get("new_relationships") or []:
            rel = _dump_or_dict(rel_raw)
            if not isinstance(rel, dict):
                continue
            char_a_code = str(
                rel.get("character_a_code")
                or rel.get("character_a")
                or rel.get("source_code")
                or char_code
            ).strip()
            char_b_code = str(
                rel.get("character_b_code")
                or rel.get("character_b")
                or rel.get("target_character_code")
                or rel.get("target_code")
                or ""
            ).strip()
            target_name_val = rel.get("target_character_name") or rel.get("target_name")
            if not char_b_code and target_name_val:
                t_name = str(target_name_val).strip()
                if t_name in db_char_by_name:
                    char_b_code = db_char_by_name[t_name]["character_code"]
                else:
                    char_b_code = f"CHAR_{AssetProtocolHelper.normalize_token(t_name)}"
            if not char_a_code or not char_b_code or char_a_code == char_b_code:
                continue

            social_label = str(
                rel.get("social_label")
                or rel.get("surface_relation")
                or rel.get("relation_type")
                or "分集交互博弈关系"
            ).strip()
            tension_index = int(rel.get("tension_index") or rel.get("tension_level") or 65)
            drama_func = str(rel.get("drama_function") or "catalyst").strip()
            shared_props = rel.get("shared_history_props") or []
            shared_props_json = json.dumps(shared_props if isinstance(shared_props, list) else [str(shared_props)], ensure_ascii=False)
            raw_gap = rel.get("information_gap") or {"knows_truth_initially": False, "current_belief": f"第{curr_ep}集交锋认知", "reveal_condition": "剧情冲突揭晓"}
            gap_dict = raw_gap if isinstance(raw_gap, dict) else {"current_belief": str(raw_gap)}
            gap_json = json.dumps(gap_dict, ensure_ascii=False)
            knows_truth_initially = 1 if gap_dict.get("knows_truth_initially") else 0
            current_belief = str(gap_dict.get("current_belief") or "").strip()
            reveal_condition = str(gap_dict.get("reveal_condition") or "").strip()
            raw_swing = rel.get("swing_point") or {"can_defect": False, "defect_condition": None}
            swing_dict = raw_swing if isinstance(raw_swing, dict) else {"can_defect": False, "defect_condition": str(raw_swing)}
            swing_json = json.dumps(swing_dict, ensure_ascii=False)
            can_defect = 1 if swing_dict.get("can_defect") else 0
            defect_condition = str(swing_dict.get("defect_condition") or "").strip()

            existing_rel = fetch_one(
                db,
                "SELECT id FROM character_relationship WHERE drama_id = :drama_id AND character_a_code = :a_code AND character_b_code = :b_code",
                {"drama_id": drama_id, "a_code": char_a_code, "b_code": char_b_code},
            )
            if not existing_rel:
                db.execute(
                    text("""
                        INSERT INTO character_relationship (
                            drama_id, character_a_code, character_b_code,
                            social_label, tension_index, drama_function,
                            shared_history_props, information_gap,
                            knows_truth_initially, current_belief, reveal_condition,
                            can_defect, defect_condition, swing_point, raw,
                            created_at, updated_at
                        ) VALUES (
                            :drama_id, :character_a_code, :character_b_code,
                            :social_label, :tension_index, :drama_function,
                            :shared_history_props, :information_gap,
                            :knows_truth_initially, :current_belief, :reveal_condition,
                            :can_defect, :defect_condition, :swing_point, :raw,
                            :now, :now
                        )
                    """),
                    {
                        "drama_id": drama_id,
                        "character_a_code": char_a_code,
                        "character_b_code": char_b_code,
                        "social_label": social_label,
                        "tension_index": tension_index,
                        "drama_function": drama_func,
                        "shared_history_props": shared_props_json,
                        "information_gap": gap_json,
                        "knows_truth_initially": knows_truth_initially,
                        "current_belief": current_belief,
                        "reveal_condition": reveal_condition,
                        "can_defect": can_defect,
                        "defect_condition": defect_condition,
                        "swing_point": swing_json,
                        "raw": json.dumps(rel, ensure_ascii=False),
                        "now": now,
                    },
                )
                log.debug(
                    "【阶段 6 落库】[DEBUG 增量关系对] 成功建立增量角色双轨关系: %s -> %s (%s)",
                    char_a_code, char_b_code, social_label,
                )

        # 单集登场关联绑定 (episode_characters): 仅绑定自然人实体
        if episode_id and char_id:
            existing_ec = fetch_one(
                db,
                "SELECT 1 FROM episode_characters WHERE episode_id = :eid AND character_id = :cid",
                {"eid": episode_id, "cid": char_id},
            )
            if not existing_ec:
                db.execute(
                    text("INSERT INTO episode_characters (episode_id, character_id) VALUES (:eid, :cid)"),
                    {"eid": episode_id, "cid": char_id},
                )
                log.info(
                    "【阶段 6 落库】[步骤 2/6 集-角色绑定] 成功绑定第 %s 集与自然人角色: episode_id=%s, character_id=%s, 角色名=%s",
                    curr_ep, episode_id, char_id, char_name,
                )

        # Tier 2: 角色多形态生命周期造型从表 (character_stages)
        for st_code, st_data in ent["stages"].items():
            stage_name = st_data["stage_name"]
            parent_ref = st_data.get("parent_stage_ref")

            parent_stage_id = 0
            if isinstance(parent_ref, int) and parent_ref > 0:
                parent_stage_id = parent_ref
            elif isinstance(parent_ref, str) and parent_ref.strip():
                ref_str = parent_ref.strip()
                if ref_str in stage_db_ids_by_code:
                    parent_stage_id = stage_db_ids_by_code[ref_str]
                elif ref_str in stage_db_ids_by_name:
                    parent_stage_id = stage_db_ids_by_name[ref_str]
                else:
                    parent_row = fetch_one(
                        db,
                        """
                        SELECT id FROM character_stages
                        WHERE drama_id = :drama_id AND (stage_code = :ref OR stage_name = :ref)
                        """,
                        {"drama_id": drama_id, "ref": ref_str},
                    )
                    if parent_row:
                        parent_stage_id = parent_row["id"]
                    else:
                        unresolved_stage_parents.append({
                            "stage_code": st_code,
                            "parent_ref": ref_str,
                        })

            existing_stage = fetch_one(
                db,
                """
                SELECT id, stage_code, parent_stage_id
                FROM character_stages
                WHERE character_id = :char_id AND (
                    (stage_code IS NOT NULL AND stage_code != '' AND stage_code = :s_code)
                    OR stage_name = :s_name
                )
                """,
                {"char_id": char_id, "s_name": stage_name, "s_code": st_code},
            )

            if existing_stage:
                stage_db_id = existing_stage["id"]
                db.execute(
                    text("""
                        UPDATE character_stages
                        SET end_episode = CASE WHEN end_episode < :curr_ep THEN :curr_ep ELSE end_episode END,
                            stage_code = CASE WHEN (stage_code IS NULL OR stage_code = '') AND :stage_code != '' THEN :stage_code ELSE stage_code END,
                            parent_stage_id = CASE WHEN (parent_stage_id IS NULL OR parent_stage_id = 0) AND :parent_stage_id > 0 THEN :parent_stage_id ELSE parent_stage_id END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": stage_db_id,
                        "curr_ep": curr_ep,
                        "stage_code": st_code,
                        "parent_stage_id": parent_stage_id,
                        "now": now,
                    },
                )
            else:
                costume_desc = st_data.get("costume_description") or ""
                color_pal = st_data.get("color_palette")
                st_ins = db.execute(
                    text("""
                        INSERT INTO character_stages (
                            character_id, drama_id, stage_name, stage_code, parent_stage_id,
                            start_episode, end_episode, costume_description, color_palette,
                            is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :character_id, :drama_id, :stage_name, :stage_code, :parent_stage_id,
                            :start_episode, :end_episode, :costume_description, :color_palette,
                            1, :now, :now
                        )
                    """),
                    {
                        "character_id": char_id,
                        "drama_id": drama_id,
                        "stage_name": stage_name,
                        "stage_code": st_code,
                        "parent_stage_id": parent_stage_id,
                        "start_episode": curr_ep,
                        "end_episode": curr_ep,
                        "costume_description": costume_desc,
                        "color_palette": color_pal,
                        "now": now,
                    },
                )
                stage_db_id = safe_int(getattr(st_ins, "lastrowid", None), default=1)
                log.info(
                    "【阶段 6 落库】[Tier 2 角色形态从表] 建立角色 [%s] 造型形态: stage_id=%s, stage_code=%s, stage_name=%s, parent_stage_id=%s",
                    char_name, stage_db_id, st_code, stage_name, parent_stage_id,
                )

            stage_db_ids_by_code[st_code] = stage_db_id
            stage_db_ids_by_name[stage_name] = stage_db_id

            # 阶段内已登记资产键集合，确保同一阶段下所有切片视图 asset_key 绝对唯一
            seen_stage_asset_keys: set[str] = set()

            # Tier 3: 角色各形态切片视图从表 (character_stage_views)
            for v_type, v_info in st_data["views"].items():
                v_label = v_info.get("view_label") or v_type
                v_url = v_info.get("image_url")
                v_local_path = v_info.get("local_path")
                v_seedance = v_info.get("seedance2_asset_id")
                is_prim = v_info.get("is_primary", 1 if v_type == "main_portrait" else 0)

                # 阶段 6 资产拓扑图与四维提示词解构
                cur_v_key = AssetProtocolHelper.build_character_asset_key(char_code, st_code, v_type)
                dep = AssetProtocolHelper.get_dependency_rule(cur_v_key)

                # 提取当前角色自然人的归一化令牌，用于同一实体约束校验
                curr_char_token = AssetProtocolHelper.normalize_token(char_code or char_name)
                norm_tok = curr_char_token

                # -------------------------------------------------------------
                # 血统防污染守卫 (Same-Entity Lineage Guard):
                # 1. 唯有一阶主视觉肖像 (main_portrait 且 st_code 归一化为 T1/STAGE_1) 为自然人第一基准，
                #    锁定为文生图 (t2i)，父级必为 None，is_benchmark 为 1
                # 2. 二阶/三阶换装主肖像 (main_portrait 且 st_code 不在 T1/STAGE_1) 必须是图生图 (i2i)，
                #    父级严格锚定至同角色 T1 主肖像，denoise_strength 为 0.35，is_benchmark 为 0
                # 3. 衍生切片 (full_body/4v_front/side/back/macro) 必须严格继承自同角色的基准肖像，
                #    若传入异构角色资产（如角色 B 的视图错误指向角色 A 的肖像），立即拦截纠偏！
                # -------------------------------------------------------------
                candidate_parent = v_info.get("parent_asset_key")
                parent_asset_key = None
                is_t1_benchmark = (
                    v_type == "main_portrait"
                    and st_code.upper() in ("T1", "STAGE_1", "TIER1", "TIER_1", "BASE", "S1")
                )

                if is_t1_benchmark:
                    # 仅一阶基准肖像无父级，为文生图根节点
                    parent_asset_key = None
                    gen_mode = "t2i"
                    denoise_str = 0.0
                    is_bench = 1
                    log.debug(
                        "【阶段 6 视图血缘·一阶基准肖像锁定】角色 [%s](%s) 阶段 %s 视图 %s 锁定为文生图根节点 (parent=None, gen_mode=t2i, is_benchmark=1)",
                        char_name, char_code, st_code, v_type,
                    )
                else:
                    is_bench = 0
                    # 衍生视图 或 二阶/三阶换装主肖像：进行同实体血缘一致性强校验
                    if candidate_parent:
                        cand_parent_str = str(candidate_parent).strip()
                        curr_v_keys = set(v_info.get("asset_keys") or [])
                        curr_v_keys.add(cur_v_key)
                        # 拦截自身引用（自环）：若与当前 view key 或已有 asset_keys 重合，绝不可作为父级
                        if cand_parent_str in curr_v_keys or cand_parent_str == cur_v_key:
                            log.warning(
                                "【阶段 6 视图血缘·自引用拦截】视图 %s 试图绑定自身作为父资产 [%s]，强制剔除！",
                                cur_v_key, cand_parent_str,
                            )
                            candidate_parent = None
                        else:
                            p_code, _, _ = extract_character_tokens(cand_parent_str)
                            parent_char_token = AssetProtocolHelper.normalize_token(p_code) if p_code else ""
                            if parent_char_token and parent_char_token == curr_char_token:
                                # 验证通过：父级资产确实归属于当前同一角色
                                parent_asset_key = cand_parent_str
                                log.debug(
                                    "【阶段 6 视图血缘·同角色校验通过】角色 [%s] 阶段 %s 视图 %s 成功关联同源父级: %s (token=%s)",
                                    char_name, st_code, v_type, parent_asset_key, curr_char_token,
                                )
                            else:
                                # 发生跨角色资产张冠李戴污染，立即拦截纠偏
                                log.warning(
                                    "【阶段 6 视图血缘·跨角色污染拦截】角色 [%s](token=%s) 阶段 %s 视图 %s 试图绑定异构父资产 [%s](parent_token=%s)，触发强制纠偏剔除！",
                                    char_name, curr_char_token, st_code, v_type, candidate_parent, parent_char_token,
                                )

                    # 若未提供父级或因跨角色污染被剔除，基于阶梯血统 DAG 进行同角色高保真安全回退:
                    # 1. 微表情 (exp_*) / 面部微距：回退到同角色 T1 纯面部肖像 (BASE_PORTRAIT / T1_BASE)
                    # 2. 四视角侧面/背面 (4v_profile, 4v_back, 4v_3q) 或手部战损 (macro_hand, status_injured)：
                    #    优先回退到同角色正面全身立绘 (4V_FRONT)，若不存在则平滑回退到 T1 主肖像
                    if not parent_asset_key:
                        # 优先查找当前角色当前形态或 T1 的 main_portrait、full_body、front_view 实际 asset_key
                        real_main_key = None
                        real_costume_key = None
                        real_front_key = None
                        st_views = ent.get("stages", {}).get(st_code, {}).get("views", {})
                        t1_views = ent.get("stages", {}).get("T1", {}).get("views", {})

                        for v_dict in (st_views, t1_views):
                            if not real_main_key and "main_portrait" in v_dict:
                                m_keys = v_dict["main_portrait"].get("asset_keys") or []
                                if m_keys:
                                    real_main_key = m_keys[0]
                            if not real_costume_key and "full_body" in v_dict:
                                c_keys = v_dict["full_body"].get("asset_keys") or []
                                if c_keys:
                                    real_costume_key = c_keys[0]
                            if not real_front_key:
                                for f_cand in ("front_view", "4v_front"):
                                    if f_cand in v_dict:
                                        f_keys = v_dict[f_cand].get("asset_keys") or []
                                        if f_keys:
                                            real_front_key = f_keys[0]
                                            break

                        t1_base_key = real_main_key or canonical_bench_portrait_key or f"CHAR_{norm_tok}_T1_BASE"
                        t1_costume_key = real_costume_key or f"CHAR_{norm_tok}_{st_code}_BASE_COSTUME"
                        t1_front_key = real_front_key or f"CHAR_{norm_tok}_{st_code}_4V_FRONT"
                        
                        if v_type in ("main_portrait", "base_portrait"):
                            # 若处于 T1 阶段，绝不能指向自身造成自环；二阶/三阶换装主肖像回退到 T1 纯面部基准
                            if st_code.upper() in ("T1", "STAGE_1", "TIER1", "TIER_1", "BASE", "S1"):
                                parent_asset_key = None
                            else:
                                parent_asset_key = t1_base_key
                        elif v_type in ("full_body", "base_costume"):
                            # 全身定妆照继承自当前阶段或 T1 主肖像
                            parent_asset_key = t1_base_key
                        elif v_type in (
                            "4v_profile", "4v_back", "4v_3q", "4v_side", "side_view", "back_view",
                            "three_quarter_view", "front_view", "4v_front", "four_view", "4v_sheet",
                        ):
                            # 四视图（正面、侧面、背面、四分之三侧或多合一），优先继承自全身定妆照 (BASE_COSTUME)
                            # 若当前阶段未定义全身定妆照，则回退到正面立绘或主肖像
                            if real_costume_key or "full_body" in st_views or "full_body" in t1_views:
                                parent_asset_key = t1_costume_key
                            elif dep and getattr(dep, "parent_asset_id", None):
                                parent_asset_key = dep.parent_asset_id
                            elif v_type in ("front_view", "4v_front"):
                                parent_asset_key = t1_base_key
                            else:
                                parent_asset_key = t1_front_key or t1_base_key
                        elif v_type.startswith("exp_") or v_type in ("facial_macro", "macro_face"):
                            # 表情与面部微距回退到面部肖像
                            parent_asset_key = t1_base_key
                        elif v_type in ("macro_hand", "hands_detail", "status_injured"):
                            # 手部微距与负伤战损回退到全身定妆照（或正面立绘）
                            parent_asset_key = t1_costume_key if (real_costume_key or "full_body" in st_views or "full_body" in t1_views) else t1_front_key
                        elif dep and getattr(dep, "parent_asset_id", None):
                            parent_asset_key = dep.parent_asset_id
                        elif dep and getattr(dep, "parent_asset_key", None):
                            parent_asset_key = dep.parent_asset_key
                        else:
                            parent_asset_key = t1_base_key

                        if parent_asset_key:
                            log.debug(
                                "【阶段 6 视图血缘·阶梯安全回退生效】角色 [%s] 阶段 %s 视图 %s (view_type=%s) 自动阶梯回退绑定底模: %s",
                                char_name, st_code, v_type, v_type, parent_asset_key,
                            )

                    gen_mode = v_info.get("generation_mode") or (dep.generation_mode if dep else "i2i")
                    if v_type in ("front_view", "side_view", "back_view", "three_quarter_view", "4v_front", "4v_side", "4v_back", "4v_3q", "4v_profile", "four_view", "4v_sheet"):
                        gen_mode = "controlnet"
                    elif gen_mode == "t2i":
                        # 衍生视图与二阶/三阶换装肖像不可为纯文生图，修正为 i2i
                        gen_mode = "i2i" if (not dep or dep.generation_mode == "t2i") else dep.generation_mode

                    raw_denoise = v_info.get("denoise_strength")
                    if raw_denoise is None and dep:
                        raw_denoise = dep.denoise_strength
                    if raw_denoise is None or float(raw_denoise) == 0.0:
                        raw_denoise = 0.40 if v_type in ("front_view", "side_view", "back_view", "three_quarter_view", "4v_front", "4v_side", "4v_back", "4v_3q", "4v_profile", "four_view", "4v_sheet") else (0.35 if v_type == "main_portrait" else 0.45)
                    denoise_str = float(raw_denoise)

                # 控制网与生图调度载荷补齐 (ControlNet OpenPose / FaceID / Inpaint)
                ctrl_type = v_info.get("control_type") or (dep.control_type if dep else None)
                if v_type in ("front_view", "side_view", "back_view", "three_quarter_view", "4v_front", "4v_side", "4v_back", "4v_3q", "4v_profile", "four_view", "4v_sheet") and not ctrl_type:
                    ctrl_type = "openpose"
                elif v_type in ("4v_front", "front_full", "4v_front_full") and not ctrl_type:
                    ctrl_type = "controlnet_openpose"
                elif v_type.startswith("exp_") and not ctrl_type:
                    ctrl_type = "inpaint_face_mask"
                elif v_type in ("macro_hand", "status_injured") and not ctrl_type:
                    ctrl_type = "inpaint_body_mask"

                raw_app = ent.get("appearance") or ""
                costume_desc = st_data.get("costume_description") or ""
                id_prompt = v_info.get("identity_prompt") or PromptSynthesizer.extract_identity_face_anchor(raw_app)
                delta_prompt = v_info.get("delta_prompt") or (f"{costume_desc}, {v_label}" if costume_desc else v_label)
                v_neg_prompt = v_info.get("negative_prompt") or PromptSynthesizer.get_negative_prompt("character")
                if v_info.get("image_prompt"):
                    v_prompt = str(v_info["image_prompt"])
                else:
                    syn = PromptSynthesizer.synthesize_character_view_prompt(
                        id_prompt,
                        view_type=v_type,
                        costume_prompt=costume_desc,
                    )
                    v_prompt = syn.visual_prompt
                    if not v_info.get("delta_prompt"):
                        delta_prompt = syn.delta_prompt

                # 确定当前视图的唯一 asset_key:
                # 1. 优先使用与当前 v_type 语义精确匹配的 upstream_keys
                # 2. 若上游无精确匹配的 key，坚决使用标准协议生成的 cur_v_key (例如 CHAR_SHENLIAN_T1_4V_FRONT)
                # 3. 绝不盲目回退到 upstream_keys[0]，防止所有切片视图塌缩为一阶主肖像 key
                stored_asset_key = cur_v_key
                upstream_keys = [ak for ak in v_info.get("asset_keys", []) if ak]
                if upstream_keys:
                    matched_key = None
                    for uk in upstream_keys:
                        uk_upper = uk.upper()
                        if v_type == "main_portrait" and any(k in uk_upper for k in ("_T1_BASE", "BASE_PORTRAIT", "PORTRAIT", "_BASE")):
                            matched_key = uk
                            break
                        elif v_type in ("full_body", "4v_front_full") and any(k in uk_upper for k in ("4V_FRONT_FULL", "FULL_BODY", "BASE_COSTUME")):
                            matched_key = uk
                            break
                        elif v_type in ("front_view", "4v_front") and any(k in uk_upper for k in ("4V_FRONT", "FRONT_VIEW")):
                            matched_key = uk
                            break
                        elif v_type in ("side_view", "4v_profile", "4v_side") and any(k in uk_upper for k in ("4V_PROFILE", "4V_SIDE", "SIDE_VIEW", "PROFILE")):
                            matched_key = uk
                            break
                        elif v_type in ("back_view", "4v_back") and any(k in uk_upper for k in ("4V_BACK", "BACK_VIEW", "REAR")):
                            matched_key = uk
                            break
                        elif v_type in ("three_quarter_view", "4v_3q") and any(k in uk_upper for k in ("4V_3Q", "THREE_QUARTER", "3Q")):
                            matched_key = uk
                            break
                        elif v_type in ("facial_macro", "macro_face") and any(k in uk_upper for k in ("MACRO_FACE", "FACIAL_MACRO")):
                            matched_key = uk
                            break
                        elif v_type in ("hands_detail", "macro_hand") and any(k in uk_upper for k in ("MACRO_HAND", "HANDS_DETAIL")):
                            matched_key = uk
                            break
                        elif v_type == "status_injured" and any(k in uk_upper for k in ("STATUS_INJURED", "INJURED", "WOUND")):
                            matched_key = uk
                            break
                        elif v_type.startswith("exp_"):
                            emo_suffix = v_type[4:].upper()
                            if f"EXP_{emo_suffix}" in uk_upper or emo_suffix in uk_upper:
                                matched_key = uk
                                break
                    stored_asset_key = matched_key or cur_v_key

                # 阶段内唯一性去重拦截：保证同一阶段内 character_stage_views 绝对无重复 asset_key
                if stored_asset_key in seen_stage_asset_keys:
                    log.warning(
                        "【阶段 6 视图资产键去重】检测到阶段内已存在相同 asset_key [%s]，自动基于 view_type [%s] 进行唯一性后缀重铸",
                        stored_asset_key, v_type,
                    )
                    disambig_key = f"{cur_v_key}_{v_type.upper()}"
                    idx_counter = 1
                    while disambig_key in seen_stage_asset_keys:
                        disambig_key = f"{cur_v_key}_{v_type.upper()}_{idx_counter}"
                        idx_counter += 1
                    stored_asset_key = disambig_key
                seen_stage_asset_keys.add(stored_asset_key)

                # -------------------------------------------------------------
                # 终极血统闭环与自引用硬拦截 (Anti-Self-Parenting Ultimate Guard)
                # 无论任何外部传参或回退，绝对禁止 asset_key 与 parent_asset_key 相同
                # -------------------------------------------------------------
                if parent_asset_key and parent_asset_key == stored_asset_key:
                    log.warning(
                        "【阶段 6 视图血缘·自引用环终极拦截】检测到 asset_key [%s] 与 parent_asset_key [%s] 完全相同！强制斩断自环",
                        stored_asset_key, parent_asset_key,
                    )
                    if is_t1_benchmark:
                        parent_asset_key = None
                        gen_mode = "t2i"
                        denoise_str = 0.0
                        is_bench = 1
                    else:
                        t1_fallback_key = canonical_bench_portrait_key or (f"CHAR_{norm_tok}_T1_BASE" if f"CHAR_{norm_tok}_T1_BASE" != stored_asset_key else None)
                        if t1_fallback_key and t1_fallback_key != stored_asset_key:
                            parent_asset_key = t1_fallback_key
                            gen_mode = "i2i"
                            denoise_str = 0.40
                            is_bench = 0
                        else:
                            parent_asset_key = None

                # 基准视图纯度约束：唯有 T1 一阶主肖像是文生图基准 (is_benchmark=1, parent=None, t2i)
                if is_t1_benchmark:
                    parent_asset_key = None
                    gen_mode = "t2i"
                    denoise_str = 0.0
                    is_bench = 1
                else:
                    # 铁律：除了 CHAR_*_T1_BASE 是文生图，其余所有视图均利用角色三级资产的关联关系逐步生成
                    is_bench = 0
                    if gen_mode == "t2i":
                        gen_mode = "i2i"
                    if denoise_str == 0.0:
                        denoise_str = 0.40
                    if not parent_asset_key:
                        t1_fallback_key = canonical_bench_portrait_key or (f"CHAR_{norm_tok}_T1_BASE" if f"CHAR_{norm_tok}_T1_BASE" != stored_asset_key else None)
                        if t1_fallback_key and t1_fallback_key != stored_asset_key:
                            parent_asset_key = t1_fallback_key

                # 再次防御：绝对禁止 parent_asset_key == stored_asset_key
                if parent_asset_key == stored_asset_key:
                    parent_asset_key = None

                v_info["parent_asset_key"] = parent_asset_key
                v_info["generation_mode"] = gen_mode
                v_info["denoise_strength"] = denoise_str
                v_info["control_type"] = ctrl_type
                v_info["is_benchmark"] = is_bench
                v_info["identity_prompt"] = id_prompt
                v_info["delta_prompt"] = delta_prompt
                v_info["negative_prompt"] = v_neg_prompt
                v_info["image_prompt"] = v_prompt
                v_info.setdefault("asset_keys", [])
                if cur_v_key not in v_info["asset_keys"]:
                    v_info["asset_keys"].append(cur_v_key)

                # 强制 is_prim 仅允许 main_portrait 且第一阶段为 1，阻断任何外部入参滥赋权
                is_prim = 1 if v_type == "main_portrait" else 0

                existing_view = fetch_one(
                    db,
                    """
                    SELECT id FROM character_stage_views
                    WHERE character_stage_id = :st_id AND view_type = :v_type
                    """,
                    {"st_id": stage_db_id, "v_type": v_type},
                )

                if existing_view:
                    view_db_id = existing_view["id"]
                    db.execute(
                        text("""
                            UPDATE character_stage_views
                            SET asset_key = CASE WHEN :asset_key IS NOT NULL AND :asset_key != '' THEN :asset_key ELSE asset_key END,
                                view_label = :view_label,
                                parent_asset_key = :parent_asset_key,
                                generation_mode = CASE WHEN :generation_mode IS NOT NULL AND :generation_mode != '' THEN :generation_mode ELSE generation_mode END,
                                denoise_strength = CASE WHEN :denoise_strength IS NOT NULL THEN :denoise_strength ELSE denoise_strength END,
                                control_type = CASE WHEN :control_type IS NOT NULL AND :control_type != '' THEN :control_type ELSE control_type END,
                                is_benchmark = :is_benchmark,
                                identity_prompt = CASE WHEN :identity_prompt != '' THEN :identity_prompt ELSE identity_prompt END,
                                delta_prompt = CASE WHEN :delta_prompt != '' THEN :delta_prompt ELSE delta_prompt END,
                                image_prompt = CASE WHEN :prompt != '' THEN :prompt ELSE image_prompt END,
                                negative_prompt = CASE WHEN :neg_prompt IS NOT NULL AND :neg_prompt != '' THEN :neg_prompt ELSE negative_prompt END,
                                image_url = CASE WHEN image_url IS NULL AND :image_url IS NOT NULL THEN :image_url ELSE image_url END,
                                local_path = CASE WHEN local_path IS NULL AND :local_path IS NOT NULL THEN :local_path ELSE local_path END,
                                seedance2_asset_id = CASE WHEN seedance2_asset_id IS NULL AND :seedance IS NOT NULL THEN :seedance ELSE seedance2_asset_id END,
                                is_primary = :is_primary,
                                updated_at = :now
                            WHERE id = :id
                        """),
                        {
                            "id": view_db_id,
                            "asset_key": stored_asset_key,
                            "view_label": v_label,
                            "parent_asset_key": parent_asset_key,
                            "generation_mode": gen_mode,
                            "denoise_strength": denoise_str,
                            "control_type": ctrl_type,
                            "is_benchmark": is_bench,
                            "identity_prompt": id_prompt,
                            "delta_prompt": delta_prompt,
                            "prompt": v_prompt,
                            "neg_prompt": v_neg_prompt,
                            "image_url": v_url,
                            "local_path": v_local_path,
                            "seedance": v_seedance,
                            "is_primary": is_prim,
                            "now": now,
                        },
                    )
                else:
                    vw_ins = db.execute(
                        text("""
                            INSERT INTO character_stage_views (
                                character_stage_id, asset_key, view_type, view_label,
                                parent_asset_key, generation_mode, denoise_strength, control_type, is_benchmark,
                                identity_prompt, delta_prompt, image_prompt, negative_prompt,
                                image_url, local_path, seedance2_asset_id,
                                is_primary, created_at, updated_at
                            ) VALUES (
                                :st_id, :asset_key, :v_type, :view_label,
                                :parent_asset_key, :generation_mode, :denoise_strength, :control_type, :is_benchmark,
                                :identity_prompt, :delta_prompt, :prompt, :neg_prompt,
                                :image_url, :local_path, :seedance,
                                :is_primary, :now, :now
                            )
                        """),
                        {
                            "st_id": stage_db_id,
                            "asset_key": stored_asset_key,
                            "v_type": v_type,
                            "view_label": v_label,
                            "parent_asset_key": parent_asset_key,
                            "generation_mode": gen_mode,
                            "denoise_strength": denoise_str,
                            "control_type": ctrl_type,
                            "is_benchmark": is_bench,
                            "identity_prompt": id_prompt,
                            "delta_prompt": delta_prompt,
                            "prompt": v_prompt,
                            "neg_prompt": v_neg_prompt,
                            "image_url": v_url,
                            "local_path": v_local_path,
                            "seedance": v_seedance,
                            "is_primary": is_prim,
                            "now": now,
                        },
                    )
                    view_db_id = safe_int(getattr(vw_ins, "lastrowid", None), default=1)
                    log.info(
                        "【阶段 6 落库】[Tier 3 角色切片视图] 写入形态切片: view_id=%s, stage_id=%s, view_type=%s, is_benchmark=%s, is_primary=%s",
                        view_db_id, stage_db_id, v_type, is_bench, is_prim,
                    )

                # 数据库层原子级唯一性互斥守卫：若当前记录为 is_primary=1，排他性清零同 stage 下所有其他视图
                if is_prim == 1 and view_db_id:
                    db.execute(
                        text("""
                            UPDATE character_stage_views
                            SET is_primary = 0, updated_at = :now
                            WHERE character_stage_id = :st_id AND id != :vid AND is_primary != 0
                        """),
                        {"st_id": stage_db_id, "vid": view_db_id, "now": now},
                    )

                # 确保当前切片视图的 asset_keys 仅包含当前切片的唯一合法 key，杜绝主肖像 key 污染衍生切片
                valid_view_keys = [stored_asset_key] if stored_asset_key else []
                v_info["asset_keys"] = valid_view_keys

                # 记录 asset_key 到实体/阶段/切片的元数据反向映射
                for ak in valid_view_keys:
                    if ak:
                        asset_character_meta_map[ak] = {
                            "character_id": char_id,
                            "character_name": char_name,
                            "character_stage_id": stage_db_id,
                            "stage_code": st_code,
                            "view_type": v_type,
                            "is_master_portrait": (is_prim == 1),
                        }

    # 二次遍历解析可能因先后次序未解析的 parent_stage_id（避免 MySQL 1093 同表更新子查询限制）
    for item in unresolved_stage_parents:
        s_code = item["stage_code"]
        p_ref = item["parent_ref"]
        p_row = fetch_one(
            db,
            """
            SELECT id FROM character_stages
            WHERE drama_id = :drama_id AND (stage_code = :p_ref OR stage_name = :p_ref)
            LIMIT 1
            """,
            {"drama_id": drama_id, "p_ref": p_ref},
        )
        if p_row and p_row.get("id"):
            db.execute(
                text("""
                    UPDATE character_stages
                    SET parent_stage_id = :parent_id
                    WHERE drama_id = :drama_id AND stage_code = :s_code AND (parent_stage_id IS NULL OR parent_stage_id = 0)
                """),
                {"drama_id": drama_id, "s_code": s_code, "parent_id": p_row["id"]},
            )
            log.debug("【阶段 6 落库】[DEBUG 角色造型二次解析] 关联 parent_stage_id: stage_code=%s, parent_ref=%s, parent_id=%s", s_code, p_ref, p_row["id"])


    # -------------------------------------------------------------
    # 数据库自愈防护机制：自动清理并矫正 character_stage_views 中可能存在的自引用脏数据 (asset_key == parent_asset_key)
    # -------------------------------------------------------------
    try:
        db.execute(
            text("""
                UPDATE character_stage_views
                SET parent_asset_key = NULL,
                    generation_mode = CASE WHEN generation_mode = 'i2i' THEN 't2i' ELSE generation_mode END,
                    denoise_strength = CASE WHEN generation_mode = 'i2i' THEN 0.0 ELSE denoise_strength END,
                    updated_at = :now
                WHERE parent_asset_key IS NOT NULL
                  AND parent_asset_key != ''
                  AND asset_key = parent_asset_key
            """),
            {"now": now},
        )
    except Exception as e:
        log.warning("【阶段 6 落库·自愈检查】执行自引用清理时出现异常（非致命）: %s", e)

    return (
        canonical_map,
        canonical_by_code,
        canonical_by_name,
        stage_db_ids_by_code,
        asset_character_meta_map,
    )
