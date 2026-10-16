"""阶段 6 角色专属声音档案与母音卡持久化组件 (Stage 6 Character Voice Persister)。

将角色母音频卡片与专属音色配置同步写入 character_voice_profiles 表，
并执行全角色 100% 覆盖差集兜底工程与台本清洗。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.workflows.adapters.stage_adapters.common import (
    _dump_or_dict,
    _ensure_valid_json_str,
    _safe_json_loads,
    fetch_all,
    fetch_one,
)
from app.workflows.adapters.stage_adapters.stage6.helpers import (
    clean_character_name,
    find_canonical_entity,
    synthesize_voice_prompt,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper

log = get_logger("lmd.storage_adapter.stage6.voice")


def persist_stage6_voices(
    db: Session,
    drama_id: int,
    curr_ep: int,
    now: str,
    voice_cards: list[dict[str, Any]],
    newly_generated_assets: list[dict[str, Any]],
    reused_assets_data: list[dict[str, Any]],
    canonical_map: dict[str, Any],
    canonical_by_code: dict[str, Any],
    canonical_by_name: dict[str, Any],
    state: Any,
) -> None:
    """持久化角色母音频卡片与专属音色配置。"""
    all_voice_entries: list[dict[str, Any]] = []

    # 3.1 聚合所有来源的既有音色资产 (显式入参 voice_cards + newly_generated_assets + reused_assets_data)
    for vc in voice_cards:
        d = _dump_or_dict(vc)
        if isinstance(d, dict):
            all_voice_entries.append(d)

    for item in newly_generated_assets:
        d = _dump_or_dict(item)
        if isinstance(d, dict):
            aid = str(d.get("asset_id") or d.get("asset_key") or "").upper()
            cat = str(d.get("type") or d.get("category") or "").lower()
            if aid.startswith("VOICE_") or cat in ("voice", "audio"):
                all_voice_entries.append(d)

    for item in reused_assets_data:
        d = _dump_or_dict(item)
        if isinstance(d, dict):
            aid = str(d.get("asset_id") or d.get("asset_key") or "").upper()
            cat = str(d.get("type") or d.get("category") or "").lower()
            if aid.startswith("VOICE_") or cat in ("voice", "audio"):
                all_voice_entries.append(d)

    # 3.2 识别并标记已覆盖音色卡的角色实体 (使用 find_canonical_entity 精确多维归属)
    covered_char_keys: set[str] = set()
    for v_entry in all_voice_entries:
        if not isinstance(v_entry, dict):
            continue
        v_name = str(v_entry.get("character_name") or v_entry.get("name") or "").strip()
        v_code = str(v_entry.get("character_code") or v_entry.get("character_id") or v_entry.get("char_id") or "").strip()
        vid = str(v_entry.get("master_voice_id") or v_entry.get("voice_id") or v_entry.get("asset_id") or "").strip()

        matched_ent = (
            find_canonical_entity(v_name, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(v_code, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(vid, canonical_map, canonical_by_name, canonical_by_code)
        )
        if matched_ent:
            covered_char_keys.add(matched_ent["char_name"].lower())
            covered_char_keys.add(matched_ent["char_code"].upper())
            # 回填标准规范角色名与角色代码，避免后续处理遗失
            v_entry.setdefault("character_name", matched_ent["char_name"])
            v_entry.setdefault("character_code", matched_ent["char_code"])
            log.debug(
                "【阶段 6 落库·音色实体映射】既有音色卡归属成功: 角色=%s (%s), voice_id=%s",
                matched_ent["char_name"], matched_ent["char_code"], vid,
            )

    # 3.3 全角色 100% 覆盖差集保底构建 (Full Character Voice Card Guarantee)
    # 核心目标：解决出场配角/小角色/未开口角色在主音色母卡抽取中被遗漏的问题
    missing_voice_characters: list[dict[str, Any]] = []
    for ent in canonical_map.values():
        c_name = ent["char_name"]
        c_code = ent["char_code"]
        if c_name.lower() not in covered_char_keys and c_code.upper() not in covered_char_keys:
            missing_voice_characters.append(ent)

    if missing_voice_characters:
        log.info(
            "【阶段 6 落库·全角色音色保底】发现 %d 位本集出场/建档角色缺失主音色母卡，开始全自动合成广播级 11 维母音卡...",
            len(missing_voice_characters),
        )
        default_emotion_rules_dict = {
            "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
            "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
            "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
            "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
            "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
            "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
        }
        for ent in missing_voice_characters:
            c_name = ent["char_name"]
            c_code = ent["char_code"]
            tok = AssetProtocolHelper.normalize_token(c_code or c_name)
            master_voice_id = f"VOICE_{tok}_T1_MASTER"
            timbre = ent.get("voice_style") or "中性沉稳自然原声"

            # 基于角色 11 维人设自动生成广播级 5 维 TTS 提示词
            char_acou = ent.get("acoustic_persona")
            if isinstance(char_acou, str) and char_acou.strip():
                try:
                    char_acou = json.loads(char_acou)
                except Exception:
                    char_acou = None

            synth_tts_prompt = synthesize_voice_prompt(
                char_name=c_name,
                gender=str(ent.get("gender") or "male"),
                perceived_age=str(ent.get("perceived_age") or "30岁"),
                role=str(ent.get("role") or "配角"),
                personality=str(ent.get("personality") or ""),
                timbre=timbre,
                voice_style=timbre,
                acoustic_persona=char_acou,
            )
            # 生成原型纯净示范台词
            sample_line = f"我是{c_name}。在这局棋盘上，没有人能置身事外。"

            synth_card = {
                "character_code": c_code,
                "character_name": c_name,
                "character_id": c_code,
                "master_voice_id": master_voice_id,
                "master_voice_key": master_voice_id,
                "timbre": timbre,
                "timbre_archetype": timbre or "沉稳磁性声线",
                "master_tts_prompt": synth_tts_prompt,
                "voice_prompt": synth_tts_prompt,
                "master_sample_text": sample_line,
                "script_monologue_source": sample_line,
                "speed_ratio": 1.0,
                "pitch_ratio": 1.0,
                "is_master_card": 1,
                "synthesis_status": "pending",
                "emotion_rules": default_emotion_rules_dict,
            }
            all_voice_entries.append(synth_card)
            log.info(
                "【阶段 6 落库·全角色音色保底】已为出场配角/未开口角色 [%s](%s) 合成母音卡: voice_id=%s, 音色=%s",
                c_name, c_code, master_voice_id, timbre,
            )

    log.info(
        "【阶段 6 落库·声音档案总计】本集待持久化音色卡总数=%d (出场角色总数=%d, 达到 100%% 覆盖)",
        len(all_voice_entries), len(canonical_map),
    )

    for v_entry in all_voice_entries:
        if not isinstance(v_entry, dict):
            continue
        raw_name = str(v_entry.get("character_name") or v_entry.get("name") or "").strip()
        v_name = clean_character_name(raw_name) or raw_name
        v_code = str(v_entry.get("character_code") or v_entry.get("char_id") or "").strip()
        voice_id_val = str(v_entry.get("master_voice_id") or v_entry.get("voice_id") or v_entry.get("asset_id") or "").strip()
        timbre = str(v_entry.get("timbre") or "").strip()
        v_prompt = str(v_entry.get("master_tts_prompt") or v_entry.get("voice_prompt") or v_entry.get("visual_grounding_quote") or v_entry.get("description") or "").strip()
        voice_file_path = str(v_entry.get("voice_file_path") or "").strip()

        # 查找对应角色自然人 ID 及文学实体配置
        target_char_id = None
        target_char_ent = (
            find_canonical_entity(v_code, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(v_name, canonical_map, canonical_by_name, canonical_by_code)
            or find_canonical_entity(voice_id_val, canonical_map, canonical_by_name, canonical_by_code)
        )

        # 1) 若从 canonical_map 内存中精确命中
        if target_char_ent:
            target_char_id = target_char_ent.get("db_id")
            if not v_name:
                v_name = target_char_ent["char_name"]
            if not v_code:
                v_code = target_char_ent["char_code"]
            log.debug(
                "【阶段 6 声音落库·内存命中】音色卡 [%s] 命中实体: 姓名=%s, ID=%s, 代号=%s",
                voice_id_val, v_name, target_char_id, v_code,
            )

        # 2) 若在 canonical_map 中未直接命中，从 DB 角色缓存或数据库实时查询
        if not target_char_id and (v_name or v_code):
            clean_v_name = clean_character_name(v_name)
            char_row = fetch_one(
                db,
                """
                SELECT id, name, character_code, gender, perceived_age, role, personality, appearance, voice_style, acoustic_persona
                FROM characters
                WHERE drama_id = :drama_id AND (
                    name = :name OR character_code = :code
                    OR name = :c_name OR character_code = :c_name
                )
                LIMIT 1
                """,
                {"drama_id": drama_id, "name": v_name, "code": v_code or v_name, "c_name": clean_v_name or v_name},
            )
            if char_row:
                target_char_id = char_row["id"]
                if not v_name:
                    v_name = char_row["name"]
                if not target_char_ent:
                    target_char_ent = dict(char_row)
                log.debug(
                    "【阶段 6 声音落库·DB实时命中】音色卡 [%s] 从DB命中实体: 姓名=%s, ID=%s",
                    voice_id_val, v_name, target_char_id,
                )

        # 3) 若音色 (timbre) 为空，尝试从关联角色中回填 voice_style
        if not timbre and target_char_ent:
            timbre = str(target_char_ent.get("voice_style") or "").strip()
        if not timbre:
            timbre = "中性沉稳自然原声"

        # 4) 生成或补全声音生成提示词 (voice_prompt / master_tts_prompt)
        # 若传入的提示词为空，或过短（缺乏具体参数），自动调用 synthesize_voice_prompt 生成 5 维广播级 TTS 提示词
        if not v_prompt or len(v_prompt) < 25 or "【" not in v_prompt:
            char_gender = target_char_ent.get("gender") if target_char_ent else "male"
            char_age = target_char_ent.get("perceived_age") if target_char_ent else "30岁"
            char_role = target_char_ent.get("role") if target_char_ent else "配角"
            char_pers = target_char_ent.get("personality") if target_char_ent else ""
            char_acou = target_char_ent.get("acoustic_persona") if target_char_ent else None
            if isinstance(char_acou, str) and char_acou.strip():
                try:
                    char_acou = json.loads(char_acou)
                except Exception:
                    char_acou = None

            synth_vp = synthesize_voice_prompt(
                char_name=v_name,
                gender=str(char_gender or "male"),
                perceived_age=str(char_age or "30岁"),
                role=str(char_role or "配角"),
                personality=str(char_pers or ""),
                timbre=timbre,
                voice_style=str(target_char_ent.get("voice_style") or "") if target_char_ent else "",
                acoustic_persona=char_acou,
            )
            if v_prompt and v_prompt != synth_vp:
                v_prompt = f"{synth_vp} 【台词语气参考】{v_prompt}"
            else:
                v_prompt = synth_vp

        # 5) 判断是否为全剧母音卡 (is_master_card: 1)
        if not voice_id_val:
            tok = AssetProtocolHelper.normalize_token(v_code or v_name)
            voice_id_val = f"VOICE_{tok}_T1_MASTER"

        master_voice_key = str(v_entry.get("master_voice_key") or v_entry.get("master_voice_id") or voice_id_val).strip()
        character_code_val = str(
            v_code
            or (target_char_ent.get("char_code") or target_char_ent.get("character_code") if target_char_ent else "")
            or f"CHAR_{AssetProtocolHelper.normalize_token(v_name)}"
        ).strip()

        raw_sample_text = str(
            v_entry.get("master_sample_text")
            or v_entry.get("script_monologue_source")
            or ""
        ).strip()
        # 剥离剧本舞台提示括号，保证 TTS 母音朗读样本绝对纯净
        clean_sample_text = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", raw_sample_text).strip()
        if not clean_sample_text:
            clean_sample_text = f"我是{v_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
        script_monologue_source = str(v_entry.get("script_monologue_source") or clean_sample_text).strip()

        timbre_archetype = str(v_entry.get("timbre_archetype") or timbre or "沉稳磁性声线").strip()
        vocal_position = str(v_entry.get("vocal_position") or "胸腔与口腔平衡共鸣").strip()
        vocal_flaws = str(v_entry.get("vocal_flaws") or "句尾带真实微弱换气呼吸音").strip()
        regional_accent = str(v_entry.get("regional_accent") or "").strip()
        acoustic_space = str(v_entry.get("acoustic_space") or "").strip()

        # 动态补充声学空间与方言特征到音色提示词中
        extra_acoustic: list[str] = []
        if regional_accent and regional_accent not in v_prompt:
            extra_acoustic.append(f"地域口音:{regional_accent}")
        if acoustic_space and acoustic_space not in v_prompt:
            extra_acoustic.append(f"声学空间:{acoustic_space}")
        if extra_acoustic:
            v_prompt = f"{v_prompt}，{'，'.join(extra_acoustic)}" if v_prompt else "，".join(extra_acoustic)

        log.debug(
            "【阶段 6 落库·高维声学合成】角色 [%s] 音色卡注入: regional_accent=%s, acoustic_space=%s -> prompt=%s",
            v_name, regional_accent, acoustic_space, v_prompt,
        )
        tts_provider = str(v_entry.get("tts_provider") or "minimax").strip()
        tts_model = str(v_entry.get("tts_model") or "speech-02-hd").strip()
        provider_voice_id = str(v_entry.get("provider_voice_id") or "male-qn-qingse").strip()

        raw_tw = v_entry.get("timber_weights") or v_entry.get("timber_weights_json")
        if isinstance(raw_tw, (list, dict)):
            timber_weights_json = json.dumps(raw_tw, ensure_ascii=False)
        elif isinstance(raw_tw, str) and raw_tw.strip():
            timber_weights_json = raw_tw.strip()
        else:
            timber_weights_json = json.dumps([{"voice_id": provider_voice_id, "weight": 100}], ensure_ascii=False)

        sample_audio_path = str(v_entry.get("sample_audio_path") or "").strip()
        sample_audio_url = str(v_entry.get("sample_audio_url") or v_entry.get("reference_audio_url") or "").strip()
        try:
            sample_duration_sec = float(v_entry.get("sample_duration_sec") or 0.0)
        except (ValueError, TypeError):
            sample_duration_sec = 0.0
        synthesis_status = str(v_entry.get("synthesis_status") or ("CERTIFIED" if sample_audio_url else "pending")).strip()
        semantic_hash_val = str(
            v_entry.get("semantic_hash")
            or hashlib.sha256(f"{master_voice_key}|{v_prompt}|{clean_sample_text}".encode("utf-8")).hexdigest()[:16]
        ).strip()

        is_master_card = 1 if (
            v_entry.get("is_master_card") in (1, True, "1", "true")
            or "master_voice_id" in v_entry
            or ("VOICE_" in voice_id_val and "_MASTER" in voice_id_val)
            or any(str(vc.get("master_voice_id") or vc.get("voice_id")) == voice_id_val for vc in voice_cards)
            or (target_char_id and not fetch_one(
                db,
                "SELECT 1 FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 1 AND deleted_at IS NULL",
                {"cid": target_char_id},
            ))
        ) else 0

        try:
            speed_ratio = float(v_entry.get("speed_ratio") or 1.0)
        except (ValueError, TypeError):
            speed_ratio = 1.0

        try:
            pitch_ratio = float(v_entry.get("pitch_ratio") or 1.0)
        except (ValueError, TypeError):
            pitch_ratio = 1.0

        raw_rules = v_entry.get("emotion_rules")
        if isinstance(raw_rules, (list, dict)):
            emotion_rules_json = json.dumps(raw_rules, ensure_ascii=False)
        elif raw_rules:
            emotion_rules_json = _ensure_valid_json_str(raw_rules, "{}", wrap_key="default")
        else:
            emotion_rules_json = json.dumps({
                "calm_suppressed": {"speed_delta": -0.08, "pitch_delta": -0.05, "instruction": "气息下沉，咬字克制隐忍"},
                "tension_clenched": {"speed_delta": 0.05, "pitch_delta": 0.0, "instruction": "牙关微紧，停顿短促有力"},
                "explosive_rage": {"speed_delta": 0.18, "pitch_delta": 0.10, "instruction": "声压骤增，胸腔强共鸣爆发"},
                "grief_choked": {"speed_delta": -0.15, "pitch_delta": -0.08, "instruction": "微带鼻音与咽音停顿"},
                "fear_trembling": {"speed_delta": 0.12, "pitch_delta": 0.06, "instruction": "呼吸急促，尾音轻微发颤"},
                "ironic_sneer": {"speed_delta": -0.05, "pitch_delta": 0.03, "instruction": "半声轻笑起音，尾音上挑冷冽"},
            }, ensure_ascii=False)

        # 检查是否已有声音档案: 优先按 voice_id / master_voice_key 精确匹配；若未匹配到则按 (character_id/name + is_master_card) 匹配
        existing_vp = None
        if voice_id_val:
            existing_vp = fetch_one(
                db,
                "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND (voice_id = :v_id OR master_voice_key = :m_key) AND deleted_at IS NULL",
                {"drama_id": drama_id, "v_id": voice_id_val, "m_key": master_voice_key},
            )
        if not existing_vp and is_master_card == 1:
            if target_char_id:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 1 AND deleted_at IS NULL",
                    {"cid": target_char_id},
                )
            if not existing_vp and v_name:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND character_name = :v_name AND is_master_card = 1 AND deleted_at IS NULL",
                    {"drama_id": drama_id, "v_name": v_name},
                )
        elif not existing_vp and is_master_card == 0 and not voice_id_val:
            if target_char_id:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE character_id = :cid AND is_master_card = 0 AND deleted_at IS NULL",
                    {"cid": target_char_id},
                )
            if not existing_vp and v_name:
                existing_vp = fetch_one(
                    db,
                    "SELECT id, is_master_card FROM character_voice_profiles WHERE drama_id = :drama_id AND character_name = :v_name AND is_master_card = 0 AND deleted_at IS NULL",
                    {"drama_id": drama_id, "v_name": v_name},
                )

        if existing_vp:
            vp_id = existing_vp["id"]
            db.execute(
                text("""
                    UPDATE character_voice_profiles
                    SET character_id = COALESCE(:cid, character_id),
                        character_code = CASE WHEN :char_code != '' THEN :char_code ELSE character_code END,
                        character_name = CASE WHEN :v_name != '' THEN :v_name ELSE character_name END,
                        voice_id = CASE WHEN :v_id != '' THEN :v_id ELSE voice_id END,
                        master_voice_key = CASE WHEN :m_key != '' THEN :m_key ELSE master_voice_key END,
                        timbre = CASE WHEN :timbre != '' THEN :timbre ELSE timbre END,
                        timbre_archetype = CASE WHEN :timbre_archetype != '' THEN :timbre_archetype ELSE timbre_archetype END,
                        vocal_position = CASE WHEN :vocal_position != '' THEN :vocal_position ELSE vocal_position END,
                        vocal_flaws = CASE WHEN :vocal_flaws != '' THEN :vocal_flaws ELSE vocal_flaws END,
                        voice_prompt = CASE WHEN :v_prompt != '' THEN :v_prompt ELSE voice_prompt END,
                        master_tts_prompt = CASE WHEN :v_prompt != '' THEN :v_prompt ELSE master_tts_prompt END,
                        master_sample_text = CASE WHEN :sample_text != '' THEN :sample_text ELSE master_sample_text END,
                        script_monologue_source = CASE WHEN :mono_source != '' THEN :mono_source ELSE script_monologue_source END,
                        tts_provider = CASE WHEN :tts_provider != '' THEN :tts_provider ELSE tts_provider END,
                        tts_model = CASE WHEN :tts_model != '' THEN :tts_model ELSE tts_model END,
                        provider_voice_id = CASE WHEN :provider_voice_id != '' THEN :provider_voice_id ELSE provider_voice_id END,
                        timber_weights_json = CASE WHEN :timber_weights_json != '' THEN :timber_weights_json ELSE timber_weights_json END,
                        speed_ratio = :speed_ratio,
                        pitch_ratio = :pitch_ratio,
                        emotion_rules = CASE WHEN :emotion_rules != '[]' THEN :emotion_rules ELSE emotion_rules END,
                        is_master_card = CASE WHEN :is_master_card = 1 THEN 1 ELSE is_master_card END,
                        reference_audio_url = CASE WHEN :sample_audio_url != '' THEN :sample_audio_url ELSE reference_audio_url END,
                        sample_audio_path = CASE WHEN :sample_audio_path != '' THEN :sample_audio_path ELSE sample_audio_path END,
                        sample_audio_url = CASE WHEN :sample_audio_url != '' THEN :sample_audio_url ELSE sample_audio_url END,
                        sample_duration_sec = CASE WHEN :sample_duration_sec > 0 THEN :sample_duration_sec ELSE sample_duration_sec END,
                        synthesis_status = CASE WHEN :sample_audio_url != '' THEN 'CERTIFIED' ELSE COALESCE(synthesis_status, :synthesis_status) END,
                        semantic_hash = CASE WHEN :semantic_hash != '' THEN :semantic_hash ELSE semantic_hash END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": vp_id,
                    "cid": target_char_id,
                    "char_code": character_code_val,
                    "v_name": v_name,
                    "v_id": voice_id_val,
                    "m_key": master_voice_key,
                    "timbre": timbre,
                    "timbre_archetype": timbre_archetype,
                    "vocal_position": vocal_position,
                    "vocal_flaws": vocal_flaws,
                    "v_prompt": v_prompt,
                    "sample_text": clean_sample_text,
                    "mono_source": script_monologue_source,
                    "tts_provider": tts_provider,
                    "tts_model": tts_model,
                    "provider_voice_id": provider_voice_id,
                    "timber_weights_json": timber_weights_json,
                    "speed_ratio": speed_ratio,
                    "pitch_ratio": pitch_ratio,
                    "emotion_rules": emotion_rules_json,
                    "is_master_card": is_master_card,
                    "sample_audio_path": sample_audio_path,
                    "sample_audio_url": sample_audio_url,
                    "sample_duration_sec": sample_duration_sec,
                    "synthesis_status": synthesis_status,
                    "semantic_hash": semantic_hash_val,
                    "now": now,
                },
            )
            log.info(
                "【阶段 6 落库】[步骤 3/6 声音档案] 更新角色 [%s] V2 声音档案: profile_id=%s, master_voice_key=%s, 音色原型=%s, 状态=%s",
                v_name, vp_id, master_voice_key, timbre_archetype, synthesis_status,
            )
            log.debug(
                "【阶段 6 落库】[DEBUG 音色卡 V2] 更新详情: char_code=%s, provider=%s/%s(%s), 试音台词=%s",
                character_code_val, tts_provider, tts_model, provider_voice_id, clean_sample_text[:30],
            )
        else:
            ins_vp = db.execute(
                text("""
                    INSERT INTO character_voice_profiles (
                        character_id, drama_id, character_code, character_name,
                        voice_id, master_voice_key, voice_prompt, master_tts_prompt,
                        master_sample_text, script_monologue_source,
                        timbre, timbre_archetype, vocal_position, vocal_flaws,
                        tts_provider, tts_model, provider_voice_id, timber_weights_json,
                        speed_ratio, pitch_ratio, emotion_rules,
                        is_master_card, reference_audio_url,
                        sample_audio_path, sample_audio_url, sample_duration_sec,
                        synthesis_status, semantic_hash,
                        status, created_at, updated_at
                    ) VALUES (
                        :cid, :drama_id, :char_code, :v_name,
                        :v_id, :m_key, :v_prompt, :v_prompt,
                        :sample_text, :mono_source,
                        :timbre, :timbre_archetype, :vocal_position, :vocal_flaws,
                        :tts_provider, :tts_model, :provider_voice_id, :timber_weights_json,
                        :speed_ratio, :pitch_ratio, :emotion_rules,
                        :is_master_card, :sample_audio_url,
                        :sample_audio_path, :sample_audio_url, :sample_duration_sec,
                        :synthesis_status, :semantic_hash,
                        'active', :now, :now
                    )
                """),
                {
                    "cid": target_char_id,
                    "drama_id": drama_id,
                    "char_code": character_code_val,
                    "v_name": v_name,
                    "v_id": voice_id_val,
                    "m_key": master_voice_key,
                    "v_prompt": v_prompt,
                    "sample_text": clean_sample_text,
                    "mono_source": script_monologue_source,
                    "timbre": timbre,
                    "timbre_archetype": timbre_archetype,
                    "vocal_position": vocal_position,
                    "vocal_flaws": vocal_flaws,
                    "tts_provider": tts_provider,
                    "tts_model": tts_model,
                    "provider_voice_id": provider_voice_id,
                    "timber_weights_json": timber_weights_json,
                    "speed_ratio": speed_ratio,
                    "pitch_ratio": pitch_ratio,
                    "emotion_rules": emotion_rules_json,
                    "is_master_card": is_master_card,
                    "sample_audio_path": sample_audio_path,
                    "sample_audio_url": sample_audio_url,
                    "sample_duration_sec": sample_duration_sec,
                    "synthesis_status": synthesis_status,
                    "semantic_hash": semantic_hash_val,
                    "now": now,
                },
            )
            log.info(
                "【阶段 6 落库】[步骤 3/6 声音档案] 新增角色 [%s] V2 声音母卡入库: profile_id=%s, master_voice_key=%s, 音色原型=%s",
                v_name, getattr(ins_vp, "lastrowid", None), master_voice_key, timbre_archetype,
            )
            log.debug(
                "【阶段 6 落库】[DEBUG 音色卡 V2] 新增详情: char_code=%s, provider=%s/%s(%s), 试音台词=%s",
                character_code_val, tts_provider, tts_model, provider_voice_id, clean_sample_text[:30],
            )

        # 同时确保 characters 表中该角色的 voice_style 不为空
        if target_char_id and timbre:
            db.execute(
                text("""
                    UPDATE characters
                    SET voice_style = CASE WHEN voice_style IS NULL OR voice_style = '' THEN :timbre ELSE voice_style END,
                        updated_at = :now
                    WHERE id = :cid
                """),
                {"cid": target_char_id, "timbre": timbre, "now": now},
            )

