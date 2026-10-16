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
    synthesize_voice_prompt,
    fetch_all,
    fetch_one,
    get_short_memories,
    publish_drama_event,
    publish_drama_read_projection,
    publish_episode_read_projection,
    set_short_memories,
)

log = get_logger("lmd.storage_adapter")

def persist_stage2(db: Session, drama_id: int, state: GlobalDramaMasterState | Any) -> None:
    """阶段 2 原子落库：写入 characters 主表、character_relationship 关系表、从表 (character_stages) 及短期记忆 B。
    
    业务逻辑：
    1. 从 state 中智能提取 characters 列表与 character_relationships/relationship_matrix 列表；
    2. 遍历 characters 列表，更新或插入 characters 主表，全量落库 11 个一等公民字段：
       - character_code, name, gender, perceived_age, role, description, personality, appearance,
       - identity_anchors, visual_consistency_code, voice_style, acoustic_persona, psychology_4,
       - voice_fingerprint, carried_anchor_item, drama_engine, growth_chain, current_status；
    3. 遍历 relationship_matrix 列表，写入或更新 character_relationship 关系表：
       - drama_id, character_a_code, character_b_code, surface_relation, emotional_bond,
       - fatal_interest_conflict, shared_history_props, drama_function, information_gap,
       - attitude_arc, swing_point；
    4. 级联写入 character_stages 从表；
    5. 向量化索引多模态角色全息档案与心理四元组；
    6. 更新 dramas 主表 current_stage=2 与 metadata.character_tokens，提交事务。
    """
    log.info("【阶段 2 落库】开始持久化短剧 [%s] 的角色全息资产与双轨关系网...", drama_id)
    now = now_iso()

    # 1. 提取角色列表 (兼容 dict、GlobalDramaMasterState 与 IndustrialDramaState，以及 character_dossiers 字典)
    if isinstance(state, dict):
        characters_list = state.get("characters") or []
        if not characters_list and isinstance(state.get("character_dossiers"), dict):
            characters_list = list(state["character_dossiers"].values())
        if not characters_list and isinstance(state.get("characters_engine"), dict):
            characters_list = state["characters_engine"].get("characters") or []
    elif hasattr(state, "characters") and state.characters:
        characters_list = state.characters
    elif hasattr(state, "character_dossiers") and getattr(state, "character_dossiers", None):
        cd = getattr(state, "character_dossiers")
        characters_list = list(cd.values()) if isinstance(cd, dict) else list(cd)
    else:
        ce = getattr(state, "characters_engine", {})
        if isinstance(ce, dict):
            characters_list = ce.get("characters", []) or ce.get("character_profiles", [])
        elif isinstance(ce, list):
            characters_list = ce
        else:
            characters_list = []

    # 2. 提取关系网列表 (兼容 relationship_matrix 与 character_relationships)
    if isinstance(state, dict):
        relationships_list = (
            state.get("character_relationships")
            or state.get("relationship_matrix")
            or state.get("dual_track_relationships")
            or []
        )
        if not relationships_list and isinstance(state.get("characters_engine"), dict):
            ce_dict = state["characters_engine"]
            relationships_list = (
                ce_dict.get("relationship_matrix")
                or ce_dict.get("character_relationships")
                or ce_dict.get("dual_track_relationships")
                or []
            )
    else:
        relationships_list = (
            getattr(state, "character_relationships", None)
            or getattr(state, "relationship_matrix", None)
            or getattr(state, "dual_track_relationships", None)
            or []
        )
        if not relationships_list:
            ce = getattr(state, "characters_engine", {})
            if isinstance(ce, dict):
                relationships_list = (
                    ce.get("relationship_matrix")
                    or ce.get("character_relationships")
                    or ce.get("dual_track_relationships")
                    or []
                )

    log.debug(
        "【阶段 2 落库】已解析待落库数据集: 角色数=%d, 关系对数=%d",
        len(characters_list),
        len(relationships_list),
    )

    # 3. 逐个角色写入或更新 characters 表
    for idx, char_raw in enumerate(characters_list, start=1):
        char = _dump_or_dict(char_raw)
        char_name = str(char.get("name") or "").strip()
        if not char_name:
            log.warning("【阶段 2 落库】第 %d 个角色缺少 name 字段，跳过", idx)
            continue

        char_code = str(char.get("character_code") or char.get("character_id") or f"CHAR_{idx}").strip()
        gender = str(char.get("gender") or char.get("biological_sex") or "male").strip().lower()
        if gender not in ("male", "female", "other"):
            gender = "female" if any(kw in str(char.get("appearance", "")) for kw in ("女", "裙", "发卡")) else "male"

        raw_age = char.get("perceived_age")
        if isinstance(raw_age, (int, float)):
            perceived_age = int(raw_age)
        elif raw_age and str(raw_age).strip().isdigit():
            perceived_age = int(str(raw_age).strip())
        else:
            perceived_age = None

        role = str(char.get("role") or char.get("role_type") or "protagonist").strip()
        description = str(char.get("description") or char.get("personality") or "").strip()
        personality = str(char.get("personality") or "").strip()
        appearance = str(char.get("appearance") or char.get("visual_anchor") or "").strip()
        voice_style = str(char.get("voice_style") or "").strip()

        # 序列化 JSON 字段 (确保任何上游传入的纯字符串均安全包装为合法 JSON 文本，杜绝 MySQL Error 3140)
        identity_anchors_json = _ensure_valid_json_str(char.get("identity_anchors"), "[]")
        visual_consistency_code_json = _ensure_valid_json_str(char.get("visual_consistency_code"), "{}", wrap_key="base_face_lock")
        acoustic_persona_json = _ensure_valid_json_str(char.get("acoustic_persona"), "{}", wrap_key="tone")
        psychology_4_json = _ensure_valid_json_str(char.get("psychology_4") or char.get("psychological_quad"), "{}", wrap_key="summary")
        voice_fingerprint_json = _ensure_valid_json_str(char.get("voice_fingerprint") or char.get("linguistic_fingerprint"), "{}", wrap_key="catchphrase")
        carried_anchor_item_json = _ensure_valid_json_str(char.get("carried_anchor_item"), "{}", wrap_key="item_name")
        drama_engine_json = _ensure_valid_json_str(char.get("drama_engine"), "{}", wrap_key="core_motivation")

        # 兼容历史 JSON 字段
        growth_chain_json = json.dumps({
            "psychological_quad": char.get("psychological_quad") or char.get("psychology_4") or {},
            "emotional_arc_trajectories": char.get("emotional_arc_trajectories") or [],
            "growth_chain": char.get("growth_chain") or [],
        }, ensure_ascii=False)

        current_status_json = json.dumps({
            "voice_fingerprint": char.get("voice_fingerprint") or {},
            "carried_anchor_item": char.get("carried_anchor_item") or {},
            "biological_dna": char.get("biological_dna") or {},
            "lived_in_costume": char.get("lived_in_costume") or {},
            "dual_track_relationships": char.get("dual_track_relationships") or [],
            "visual_consistency_code": char.get("visual_consistency_code") or {},
            "acoustic_persona": char.get("acoustic_persona") or {},
            "drama_engine": char.get("drama_engine") or {},
        }, ensure_ascii=False)

        # 检查是否已存在 (以 drama_id 与 (character_code 或 name) 联合排重)
        existing_char = fetch_one(
            db,
            "SELECT id FROM characters WHERE drama_id = :drama_id AND (character_code = :code OR name = :name)",
            {"drama_id": drama_id, "code": char_code, "name": char_name},
        )

        if existing_char:
            char_id = existing_char["id"]
            log.debug(
                "【阶段 2 落库】更新现有角色 [ID=%s, 代号=%s, 姓名=%s, 定位=%s]",
                char_id, char_code, char_name, role,
            )
            db.execute(
                text("""
                    UPDATE characters
                    SET character_code = :character_code,
                        gender = :gender,
                        perceived_age = :perceived_age,
                        role = :role,
                        description = :description,
                        personality = :personality,
                        appearance = :appearance,
                        identity_anchors = :identity_anchors,
                        visual_consistency_code = :visual_consistency_code,
                        voice_style = :voice_style,
                        acoustic_persona = :acoustic_persona,
                        psychology_4 = :psychology_4,
                        voice_fingerprint = :voice_fingerprint,
                        carried_anchor_item = :carried_anchor_item,
                        drama_engine = :drama_engine,
                        growth_chain = :growth_chain,
                        current_status = :current_status,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": char_id,
                    "character_code": char_code,
                    "gender": gender,
                    "perceived_age": perceived_age,
                    "role": role,
                    "description": description,
                    "personality": personality,
                    "appearance": appearance,
                    "identity_anchors": identity_anchors_json,
                    "visual_consistency_code": visual_consistency_code_json,
                    "voice_style": voice_style,
                    "acoustic_persona": acoustic_persona_json,
                    "psychology_4": psychology_4_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "carried_anchor_item": carried_anchor_item_json,
                    "drama_engine": drama_engine_json,
                    "growth_chain": growth_chain_json,
                    "current_status": current_status_json,
                    "updated_at": now,
                },
            )
        else:
            log.debug(
                "【阶段 2 落库】新增角色 [代号=%s, 姓名=%s, 定位=%s, 视觉年龄=%s]",
                char_code, char_name, role, perceived_age,
            )
            insert_res = db.execute(
                text("""
                    INSERT INTO characters (
                        drama_id, character_code, name, gender, perceived_age,
                        role, description, personality, appearance,
                        identity_anchors, visual_consistency_code, voice_style,
                        acoustic_persona, psychology_4, voice_fingerprint,
                        carried_anchor_item, drama_engine,
                        growth_chain, current_status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :character_code, :name, :gender, :perceived_age,
                        :role, :description, :personality, :appearance,
                        :identity_anchors, :visual_consistency_code, :voice_style,
                        :acoustic_persona, :psychology_4, :voice_fingerprint,
                        :carried_anchor_item, :drama_engine,
                        :growth_chain, :current_status, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "character_code": char_code,
                    "name": char_name,
                    "gender": gender,
                    "perceived_age": perceived_age,
                    "role": role,
                    "description": description,
                    "personality": personality,
                    "appearance": appearance,
                    "identity_anchors": identity_anchors_json,
                    "visual_consistency_code": visual_consistency_code_json,
                    "voice_style": voice_style,
                    "acoustic_persona": acoustic_persona_json,
                    "psychology_4": psychology_4_json,
                    "voice_fingerprint": voice_fingerprint_json,
                    "carried_anchor_item": carried_anchor_item_json,
                    "drama_engine": drama_engine_json,
                    "growth_chain": growth_chain_json,
                    "current_status": current_status_json,
                    "now": now,
                },
            )
            char_id = insert_res.lastrowid

        # 级联写入从表 1：character_stages (角色生命周期阶段)
        stages_data = char.get("stages") or char.get("character_stages") or []
        if not stages_data:
            stages_data = [{
                "stage_name": "初始基线形态",
                "start_episode": 1,
                "end_episode": 100,
                "costume_description": char.get("lived_in_costume", {}).get("outerwear", "") if isinstance(char.get("lived_in_costume"), dict) else "",
                "color_palette": json.dumps(char.get("color_palette", {}), ensure_ascii=False) if isinstance(char.get("color_palette"), dict) else "",
            }]

        for s_idx, st_item in enumerate(stages_data, start=1):
            s_name = st_item.get("stage_name", f"阶段_{s_idx}")
            existing_stage = fetch_one(
                db,
                "SELECT id FROM character_stages WHERE character_id = :char_id AND stage_name = :s_name",
                {"char_id": char_id, "s_name": s_name},
            )
            c_palette = st_item.get("color_palette")
            if isinstance(c_palette, (dict, list)):
                c_palette = json.dumps(c_palette, ensure_ascii=False)

            costume_desc = st_item.get("costume_description") or st_item.get("costume_desc", "")
            start_ep = st_item.get("start_episode", s_idx)
            end_ep = st_item.get("end_episode", 100)

            if existing_stage:
                stage_db_id = existing_stage["id"]
                db.execute(
                    text("""
                        UPDATE character_stages
                        SET start_episode = :start_episode,
                            end_episode = :end_episode,
                            costume_description = :costume_description,
                            color_palette = :color_palette,
                            updated_at = :updated_at
                        WHERE id = :id
                    """),
                    {
                        "id": stage_db_id,
                        "start_episode": start_ep,
                        "end_episode": end_ep,
                        "costume_description": costume_desc,
                        "color_palette": str(c_palette or ""),
                        "updated_at": now,
                    },
                )
            else:
                db.execute(
                    text("""
                        INSERT INTO character_stages (
                            character_id, drama_id, stage_name, start_episode, end_episode,
                            costume_description, color_palette, is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :character_id, :drama_id, :stage_name, :start_episode, :end_episode,
                            :costume_description, :color_palette, 0, :now, :now
                        )
                    """),
                    {
                        "character_id": char_id,
                        "drama_id": drama_id,
                        "stage_name": s_name,
                        "start_episode": start_ep,
                        "end_episode": end_ep,
                        "costume_description": costume_desc,
                        "color_palette": str(c_palette or ""),
                        "now": now,
                    },
                )

        # 级联写入从表 1.5：character_voice_profiles (阶段 2 初始化 V2 母音卡基线，状态 pending)
        tok = AssetProtocolHelper.normalize_token(char_code or char_name)
        master_v_key = f"VOICE_{tok}_T1_MASTER"
        existing_vp = fetch_one(
            db,
            "SELECT id FROM character_voice_profiles WHERE drama_id = :drama_id AND (character_id = :cid OR master_voice_key = :m_key OR voice_id = :m_key) AND deleted_at IS NULL",
            {"drama_id": drama_id, "cid": char_id, "m_key": master_v_key},
        )
        synth_vp = synthesize_voice_prompt(
            char_name=char_name,
            gender=gender,
            perceived_age=perceived_age,
            role=role,
            personality=personality,
            timbre=voice_style,
            voice_style=voice_style,
            acoustic_persona=_safe_json_loads(acoustic_persona_json, None),
        )
        ap_parsed = _safe_json_loads(acoustic_persona_json, {}) if acoustic_persona_json else {}
        if not isinstance(ap_parsed, dict):
            ap_parsed = {}
        vf_parsed = _safe_json_loads(voice_fingerprint_json, {}) if voice_fingerprint_json else {}
        if not isinstance(vf_parsed, dict):
            vf_parsed = {}
        extracted_vocal_pos = str(ap_parsed.get("vocal_position") or "胸腔与口腔平衡共鸣").strip()
        extracted_vocal_flaws = str(ap_parsed.get("vocal_flaws") or "句尾带真实微弱换气呼吸音").strip()
        catchphrase_str = str(vf_parsed.get("catchphrase") or "").strip()
        defensive_str = str(vf_parsed.get("defensive_phrase") or "").strip()
        if catchphrase_str or defensive_str:
            default_sample_text = f"{catchphrase_str} {defensive_str}".strip()
            if len(default_sample_text) < 20:
                default_sample_text = f"我是{char_name}。{default_sample_text} 有些账，终究要亲手算个清楚。"
        else:
            default_sample_text = f"我是{char_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
        default_provider_vid = "female-yujie" if gender == "female" else "male-qn-qingse"
        default_tw_json = json.dumps([{"voice_id": default_provider_vid, "weight": 100}], ensure_ascii=False)
        default_rules_json = json.dumps({
            "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
            "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
            "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
            "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
            "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
            "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
        }, ensure_ascii=False)
        vp_hash = hashlib.sha256(f"{master_v_key}|{synth_vp}|{default_sample_text}".encode("utf-8")).hexdigest()[:16]
        if not existing_vp:
            db.execute(
                text("""
                    INSERT INTO character_voice_profiles (
                        character_id, drama_id, character_code, character_name,
                        voice_id, master_voice_key, voice_prompt, master_tts_prompt,
                        master_sample_text, script_monologue_source,
                        timbre, timbre_archetype, vocal_position, vocal_flaws,
                        tts_provider, tts_model, provider_voice_id, timber_weights_json,
                        speed_ratio, pitch_ratio, emotion_rules,
                        is_master_card, synthesis_status, semantic_hash,
                        status, created_at, updated_at
                    ) VALUES (
                        :cid, :drama_id, :char_code, :char_name,
                        :m_key, :m_key, :v_prompt, :v_prompt,
                        :sample_text, :sample_text,
                        :timbre, :timbre_archetype, :vocal_position, :vocal_flaws,
                        'minimax', 'speech-02-hd', :provider_vid, :tw_json,
                        1.0, 1.0, :emotion_rules,
                        1, 'pending', :semantic_hash,
                        'active', :now, :now
                    )
                """),
                {
                    "cid": char_id,
                    "drama_id": drama_id,
                    "char_code": char_code,
                    "char_name": char_name,
                    "m_key": master_v_key,
                    "v_prompt": synth_vp,
                    "sample_text": default_sample_text,
                    "timbre": voice_style or "自然原声",
                    "timbre_archetype": voice_style or "沉稳磁性声线",
                    "vocal_position": extracted_vocal_pos,
                    "vocal_flaws": extracted_vocal_flaws,
                    "provider_vid": default_provider_vid,
                    "tw_json": default_tw_json,
                    "emotion_rules": default_rules_json,
                    "semantic_hash": vp_hash,
                    "now": now,
                },
            )
            log.debug("【阶段 2 落库】[DEBUG 音色卡基线] 已为角色 [%s(%s)] 初始化 V2 母音卡: %s", char_name, char_code, master_v_key)

    # 4. 级联写入人物关系表：character_relationship (双轨对抗与关系矩阵)
    log.debug("【阶段 2 落库】开始持久化短剧 [%s] 的角色双轨关系矩阵，待处理条数: %d", drama_id, len(relationships_list))
    for r_idx, rel_item in enumerate(relationships_list, start=1):
        rel = _dump_or_dict(rel_item)
        char_a_code = str(rel.get("character_a_code") or rel.get("character_a") or "").strip()
        char_b_code = str(rel.get("character_b_code") or rel.get("character_b") or "").strip()
        if not char_a_code or not char_b_code or char_a_code == char_b_code:
            log.debug("【阶段 2 落库】跳过无效或自环关系对: %s <-> %s", char_a_code, char_b_code)
            continue

        social_label = str(rel.get("social_label") or rel.get("surface_relation") or rel.get("surface_identity") or "表层社会关系").strip()
        tension_index = int(rel.get("tension_index") or 50)
        drama_func = str(rel.get("drama_function") or ("catalyst" if r_idx == 1 else "obstacle")).strip()

        shared_props = rel.get("shared_history_props") or rel.get("shared_past_token")
        if isinstance(shared_props, list):
            shared_props_list = [str(p).strip() for p in shared_props if str(p).strip()]
        elif shared_props:
            shared_props_list = [str(shared_props).strip()]
        else:
            shared_props_list = []
        shared_props_json = json.dumps(shared_props_list, ensure_ascii=False)

        raw_gap = rel.get("information_gap")
        if isinstance(raw_gap, dict):
            gap_dict = raw_gap
            gap_json = json.dumps(raw_gap, ensure_ascii=False)
        elif raw_gap:
            gap_dict = {"current_belief": str(raw_gap)}
            gap_json = json.dumps(gap_dict, ensure_ascii=False)
        else:
            gap_dict = {"knows_truth_initially": False, "current_belief": "受表象蒙蔽"}
            gap_json = json.dumps(gap_dict, ensure_ascii=False)

        knows_truth_initially = 1 if gap_dict.get("knows_truth_initially") or rel.get("knows_truth_initially") else 0
        current_belief = str(gap_dict.get("current_belief") or rel.get("current_belief") or "").strip()
        reveal_condition = str(gap_dict.get("reveal_condition") or rel.get("reveal_condition") or "").strip()

        raw_swing = rel.get("swing_point")
        if isinstance(raw_swing, dict):
            swing_dict = raw_swing
            swing_json = json.dumps(raw_swing, ensure_ascii=False)
        else:
            swing_dict = {"can_defect": False, "defect_condition": None}
            swing_json = json.dumps(swing_dict, ensure_ascii=False)

        can_defect = 1 if swing_dict.get("can_defect") or rel.get("can_defect") else 0
        defect_condition = str(swing_dict.get("defect_condition") or rel.get("defect_condition") or "").strip()

        raw_json = json.dumps(rel, ensure_ascii=False)

        existing_rel = fetch_one(
            db,
            "SELECT id FROM character_relationship WHERE drama_id = :drama_id AND character_a_code = :a_code AND character_b_code = :b_code",
            {"drama_id": drama_id, "a_code": char_a_code, "b_code": char_b_code},
        )

        if existing_rel:
            log.debug("【阶段 2 落库】更新现有角色关系对 (ID=%s): %s -> %s", existing_rel["id"], char_a_code, char_b_code)
            db.execute(
                text("""
                    UPDATE character_relationship
                    SET social_label = :social_label,
                        tension_index = :tension_index,
                        drama_function = :drama_function,
                        shared_history_props = :shared_history_props,
                        information_gap = :information_gap,
                        knows_truth_initially = :knows_truth_initially,
                        current_belief = :current_belief,
                        reveal_condition = :reveal_condition,
                        can_defect = :can_defect,
                        defect_condition = :defect_condition,
                        swing_point = :swing_point,
                        raw = :raw,
                        updated_at = :updated_at
                    WHERE id = :id
                """),
                {
                    "id": existing_rel["id"],
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
                    "raw": raw_json,
                    "updated_at": now,
                },
            )
        else:
            log.debug("【阶段 2 落库】新增角色关系对: %s -> %s", char_a_code, char_b_code)
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
                    "raw": raw_json,
                    "now": now,
                },
            )

    # 5. 长期记忆自动入库与向量化（角色全息档案与心理四元组）
    stage2_memories = []
    for char_item in characters_list:
        char = _dump_or_dict(char_item)
        c_name = char.get("name")
        if not c_name:
            continue
        c_code = char.get("character_code") or char.get("character_id") or ""
        c_role = char.get("role") or char.get("role_type") or "主要角色"
        c_quad = char.get("psychology_4") or char.get("psychological_quad") or {}
        c_arc = char.get("emotional_arc_trajectories") or []
        c_vcc = char.get("visual_consistency_code") or {}
        c_anchor = char.get("carried_anchor_item") or {}
        c_engine = char.get("drama_engine") or {}
        stage2_memories.append({
            "title": f"角色全息档案: {c_name} [{c_code}] ({c_role})",
            "content": (
                f"角色名: {c_name} (代号: {c_code})\n"
                f"角色定位: {c_role}\n"
                f"视觉年龄: {char.get('perceived_age', '未知')}\n"
                f"性格特征: {char.get('personality', '')}\n"
                f"外貌装造锚点: {char.get('appearance') or char.get('lived_in_costume', {})}\n"
                f"锁脸与服饰一致性代码: {json.dumps(c_vcc, ensure_ascii=False)}\n"
                f"随身锚定旧物: {json.dumps(c_anchor, ensure_ascii=False)}\n"
                f"戏剧引擎动力: {json.dumps(c_engine, ensure_ascii=False)}\n"
                f"心理四元组: {json.dumps(c_quad, ensure_ascii=False)}\n"
                f"人物弧光: {json.dumps(c_arc, ensure_ascii=False)}\n"
                f"声纹与行为指纹: {json.dumps(char.get('voice_fingerprint', {}), ensure_ascii=False)}"
            ),
            "summary": f"{c_name} [{c_code}]: {c_role}, {char.get('personality', '')}",
            "keywords": [c_name, c_code, c_role, "人物档案", "角色引擎"],
            "memory_type": "character_profile",
            "source_type": "stage2_character",
            "source_id": f"char_{c_code or c_name}",
        })
    sync_stage_memories_to_vector_db(db, drama_id, 2, stage2_memories)

    # 6. 更新主表状态及元数据命名空间
    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    tokens = getattr(state, "character_tokens", None) if not isinstance(state, dict) else state.get("character_tokens")
    if tokens:
        current_meta["character_tokens"] = tokens
    db.execute(
        text("UPDATE dramas SET current_stage = 2, metadata = :metadata, updated_at = :now WHERE id = :id"),
        {"id": drama_id, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    audit = (
        getattr(state, "latest_audit", None)
        or getattr(state, "audit_report", None)
        if not isinstance(state, dict)
        else (state.get("latest_audit") or state.get("audit_report"))
    )
    if audit:
        persist_audit_report(db, drama_id, 2, audit)

    db.commit()
    log.info("【阶段 2 落库】短剧 [%s] 角色全息资产与双轨关系网持久化成功并已提交事务。", drama_id)


# =========================================================================
# 阶段 3：空间三层做旧、场景区域与物证拟音持久化
# =========================================================================

