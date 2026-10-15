"""声音与音乐设计服务。

当前版本先用规则生成 Voice Profile / Music Bible / Music Cue，作为后续声音 Agent、
音乐 Agent 和 TTS/BGM 生成模型的稳定输入。等 Prompt/Skill 成熟后，可以把这里的
规则生成替换成 AI 结构化输出。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import config as cfgmod
from app.core.logger import get_logger
from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso
from app.services import ttsService
from app.workflows.utils.asset_protocol import AssetProtocolHelper

logger = get_logger("lmd.audio_design")


def _serialize_voice_profile(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """统一声音档案输出，完整暴露 V2 母音卡字段并提供前端历史字段兼容别名。"""
    if not row:
        return None
    item = dict(row)
    emotion_rules = json_loads(item.get("emotion_rules"), [])
    item["emotion_rules"] = emotion_rules
    item["negative_traits"] = json_loads(item.get("negative_traits"), [])
    timber_weights = json_loads(item.get("timber_weights_json"), [])
    item["timber_weights"] = timber_weights if isinstance(timber_weights, list) else []

    # 兼容 V2 与 V1 字段别名
    item["master_voice_key"] = item.get("master_voice_key") or item.get("voice_id") or ""
    item["master_tts_prompt"] = item.get("master_tts_prompt") or item.get("voice_prompt") or ""
    item["master_sample_text"] = item.get("master_sample_text") or item.get("script_monologue_source") or ""
    item["timbre_archetype"] = item.get("timbre_archetype") or item.get("timbre") or ""
    item["vocal_position"] = item.get("vocal_position") or "胸腔与口腔平衡共鸣"
    item["vocal_flaws"] = item.get("vocal_flaws") or "句尾带真实微弱换气呼吸音"
    item["tts_provider"] = item.get("tts_provider") or item.get("provider") or "minimax"
    item["tts_model"] = item.get("tts_model") or "speech-02-hd"
    item["provider_voice_id"] = item.get("provider_voice_id") or ""
    item["synthesis_status"] = item.get("synthesis_status") or (
        "completed" if (item.get("sample_audio_url") or item.get("reference_audio_url")) else "pending"
    )
    item["voice_name"] = item.get("voice_id") or item.get("master_voice_key") or ""
    item["speed"] = float(item.get("speed_ratio") or 1.0)
    pitch_ratio = max(float(item.get("pitch_ratio") or 1.0), 0.01)
    item["pitch"] = round(12 * math.log2(pitch_ratio), 2)
    item["sample_audio_url"] = item.get("sample_audio_url") or item.get("reference_audio_url") or ""
    if isinstance(emotion_rules, list):
        default_rule = next((str(rule) for rule in emotion_rules if str(rule).startswith("默认情绪：")), "")
        item["emotion"] = default_rule.removeprefix("默认情绪：") or "neutral"
    else:
        item["emotion"] = "neutral"
    return item


def _voice_timbre(character: dict[str, Any]) -> str:
    """根据角色基础人设推断音色，先保证跨集一致性。"""
    existing = str(character.get("voice_style") or "").strip()
    if existing:
        return existing
    role = str(character.get("role") or "").lower()
    personality = str(character.get("personality") or character.get("description") or "")
    if "反派" in personality or role in {"antagonist", "villain"}:
        return "冷硬低沉，压迫感强，语尾带轻微冷笑"
    if "女" in str(character.get("appearance") or ""):
        return "清晰明亮，情绪起伏明显，关键台词带克制爆发"
    if role in {"main", "protagonist"}:
        return "低沉磁性，咬字清晰，情绪越紧张语速越稳"
    return "自然写实，语速适中，情绪表达贴近生活短剧表演"


def _voice_prompt(character: dict[str, Any], timbre: str) -> str:
    name = character.get("name") or "角色"
    appearance = str(character.get("appearance") or "").strip()
    personality = str(character.get("personality") or character.get("description") or "").strip()
    return (
        f"为短剧角色“{name}”生成稳定配音：音色{timbre}。"
        f"人物外貌/气质参考：{appearance or '未提供'}。"
        f"人物性格/关系参考：{personality or '未提供'}。"
        "要求对白清楚、表演真实、情绪服务剧情，不要机械电音感，不要过度夸张。"
    )


def upsert_character_voice_profiles(db: Session, drama_id: int) -> list[dict[str, Any]]:
    """为整部剧的角色生成或更新声音档案。"""
    characters = fetch_all(
        db,
        """
        SELECT id, drama_id, name, role, description, personality, appearance, voice_style
        FROM characters
        WHERE drama_id = :drama_id AND deleted_at IS NULL
        ORDER BY sort_order ASC, id ASC
        """,
        {"drama_id": drama_id},
    )
    results: list[dict[str, Any]] = []
    now = now_iso()
    for character in characters:
        timbre = _voice_timbre(character)
        prompt = _voice_prompt(character, timbre)
        existing = fetch_one(
            db,
            "SELECT id FROM character_voice_profiles WHERE character_id = :cid AND deleted_at IS NULL",
            {"cid": character["id"]},
        )
        params = {
            "character_id": character["id"],
            "drama_id": drama_id,
            "character_name": character.get("name") or "",
            "voice_prompt": prompt,
            "timbre": timbre,
            "speed_ratio": 1.08 if str(character.get("role") or "").lower() in {"main", "protagonist"} else 1.0,
            "pitch_ratio": 1.0,
            "emotion_rules": json_dumps(["愤怒时提高力度但不破音", "悲伤时放慢语速", "反转打脸台词保持短促有力"]),
            "provider": "",
            "voice_id": "",
            "reference_audio_url": "",
            "negative_traits": json_dumps(["机械电音感", "语调平淡", "过度油腻", "含混不清"]),
            "status": "active",
            "now": now,
        }
        if existing:
            db.execute(
                text(
                    """
                    UPDATE character_voice_profiles
                    SET character_name = :character_name, voice_prompt = :voice_prompt, timbre = :timbre,
                        speed_ratio = :speed_ratio, pitch_ratio = :pitch_ratio, emotion_rules = :emotion_rules,
                        provider = :provider, voice_id = :voice_id, reference_audio_url = :reference_audio_url,
                        negative_traits = :negative_traits, status = :status, updated_at = :now
                    WHERE id = :id
                    """
                ),
                {**params, "id": existing["id"]},
            )
            row_id = existing["id"]
        else:
            res = db.execute(
                text(
                    """
                    INSERT INTO character_voice_profiles (
                        character_id, drama_id, character_name, voice_prompt, timbre, speed_ratio, pitch_ratio,
                        emotion_rules, provider, voice_id, reference_audio_url, negative_traits, status, created_at, updated_at
                    ) VALUES (
                        :character_id, :drama_id, :character_name, :voice_prompt, :timbre, :speed_ratio, :pitch_ratio,
                        :emotion_rules, :provider, :voice_id, :reference_audio_url, :negative_traits, :status, :now, :now
                    )
                    """
                ),
                params,
            )
            row_id = res.lastrowid
        row = result_to_dict(
            db.execute(text("SELECT * FROM character_voice_profiles WHERE id = :id"), {"id": row_id}).first()
        )
        results.append(_serialize_voice_profile(row))
    return results


def update_character_voice_profile(
    db: Session,
    profile_id: int,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """更新单个角色声音档案。

    数据库采用稳定的领域字段名；这里集中兼容旧前端的 voice_name/speed/pitch 等别名，
    防止 API 层直接依赖不存在的 ORM 模型或把任意字段拼入 SQL。
    """
    current = fetch_one(
        db,
        "SELECT * FROM character_voice_profiles WHERE id = :id AND deleted_at IS NULL",
        {"id": profile_id},
    )
    if not current:
        return None

    body = payload or {}
    updates: dict[str, Any] = {}
    alias_map = {
        "voice_name": "voice_id",
        "sample_audio_url": "reference_audio_url",
    }
    for source, target in alias_map.items():
        if source in body:
            updates[target] = str(body.get(source) or "").strip()
    for field in (
        "voice_prompt",
        "master_tts_prompt",
        "master_sample_text",
        "script_monologue_source",
        "timbre",
        "timbre_archetype",
        "vocal_position",
        "vocal_flaws",
        "provider",
        "tts_provider",
        "tts_model",
        "provider_voice_id",
        "voice_id",
        "master_voice_key",
        "character_code",
        "reference_audio_url",
        "sample_audio_path",
        "sample_audio_url",
        "synthesis_status",
        "status",
    ):
        if field in body and body.get(field) is not None:
            val_str = str(body.get(field) or "").strip()
            if field in ("master_sample_text", "script_monologue_source"):
                val_str = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", val_str).strip()
            updates[field] = val_str

    # 保持 V1 与 V2 对偶字段同步
    if "master_tts_prompt" in updates and "voice_prompt" not in updates:
        updates["voice_prompt"] = updates["master_tts_prompt"]
    elif "voice_prompt" in updates and "master_tts_prompt" not in updates:
        updates["master_tts_prompt"] = updates["voice_prompt"]

    if "timbre_archetype" in updates and "timbre" not in updates:
        updates["timbre"] = updates["timbre_archetype"]

    if "timber_weights" in body:
        tw = body.get("timber_weights")
        if isinstance(tw, (list, dict)):
            updates["timber_weights_json"] = json_dumps(tw)
        elif isinstance(tw, str):
            updates["timber_weights_json"] = tw

    if "emotion_rules" in body and isinstance(body.get("emotion_rules"), (list, dict)):
        updates["emotion_rules"] = json_dumps(body["emotion_rules"])

    if "speed" in body or "speed_ratio" in body:
        speed = float(body.get("speed", body.get("speed_ratio")))
        if not 0.5 <= speed <= 2.0:
            raise ValueError("speed 必须在 0.5 到 2.0 之间")
        updates["speed_ratio"] = speed

    if "pitch" in body:
        semitones = float(body["pitch"])
        if not -12 <= semitones <= 12:
            raise ValueError("pitch 必须在 -12 到 12 个半音之间")
        updates["pitch_ratio"] = 2 ** (semitones / 12)
    elif "pitch_ratio" in body:
        pitch_ratio = float(body["pitch_ratio"])
        if not 0.5 <= pitch_ratio <= 2.0:
            raise ValueError("pitch_ratio 必须在 0.5 到 2.0 之间")
        updates["pitch_ratio"] = pitch_ratio

    if "emotion" in body:
        emotion = str(body.get("emotion") or "neutral").strip() or "neutral"
        rules = json_loads(current.get("emotion_rules"), [])
        if isinstance(rules, list):
            rules = [str(rule) for rule in rules if not str(rule).startswith("默认情绪：")]
            updates["emotion_rules"] = json_dumps([f"默认情绪：{emotion}", *rules])

    if not updates:
        return _serialize_voice_profile(current)

    # 当核心声学参数或试音台词变更且未显式指定 synthesis_status 时，自动将状态置为 READY (待重新合成母音)
    acoustic_changed_keys = {
        "master_sample_text",
        "master_tts_prompt",
        "voice_prompt",
        "timbre_archetype",
        "vocal_position",
        "vocal_flaws",
        "provider_voice_id",
        "voice_id",
        "timber_weights_json",
        "speed_ratio",
        "pitch_ratio",
    }
    if "synthesis_status" not in updates and (acoustic_changed_keys & set(updates.keys())):
        updates["synthesis_status"] = "READY"

    # 字段名只来自上面的固定白名单，用户输入永远不会直接进入 SQL 结构部分。
    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{field} = :{field}" for field in updates)
    db.execute(
        text(f"UPDATE character_voice_profiles SET {assignments} WHERE id = :id"),
        {**updates, "id": profile_id},
    )
    updated = fetch_one(db, "SELECT * FROM character_voice_profiles WHERE id = :id", {"id": profile_id})
    logger.debug("【音色卡更新】[DEBUG] profile_id=%s, 更新字段=%s", profile_id, list(updates.keys()))
    return _serialize_voice_profile(updated)


def upsert_music_bible(db: Session, drama_id: int) -> dict[str, Any]:
    """生成整剧音乐 Bible，保证不同分镜 Cue 有统一音乐方向。"""
    drama = fetch_one(db, "SELECT title, genre, style, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": drama_id})
    if not drama:
        raise ValueError("项目不存在")
    genre = str(drama.get("genre") or drama.get("style") or "短剧").strip()
    now = now_iso()
    params = {
        "drama_id": drama_id,
        "overall_style": f"{genre}短剧配乐，现代影视管弦与电子氛围结合，服务强冲突和快节奏反转",
        "theme_prompt": f"为《{drama.get('title') or '未命名短剧'}》设计统一主题音乐：紧张铺垫、反转爆发、情绪释放层次清楚。",
        "instruments": json_dumps(["弦乐拨奏", "低频鼓点", "大提琴长音", "电子脉冲", "冲击重音"]),
        "bpm_range": "90-135 BPM",
        "emotional_palette": json_dumps(["紧张压迫", "反转打脸", "悬疑推进", "情感破防", "胜利释放"]),
        "mixing_rules": "对白优先，BGM 默认低于对白约 14dB；高潮重音尽量落在台词停顿处。",
        "status": "active",
        "now": now,
    }
    existing = fetch_one(db, "SELECT id FROM music_bibles WHERE drama_id = :drama_id AND deleted_at IS NULL", {"drama_id": drama_id})
    if existing:
        db.execute(
            text(
                """
                UPDATE music_bibles
                SET overall_style = :overall_style, theme_prompt = :theme_prompt, instruments = :instruments,
                    bpm_range = :bpm_range, emotional_palette = :emotional_palette,
                    mixing_rules = :mixing_rules, status = :status, updated_at = :now
                WHERE id = :id
                """
            ),
            {**params, "id": existing["id"]},
        )
        row_id = existing["id"]
    else:
        res = db.execute(
            text(
                """
                INSERT INTO music_bibles (
                    drama_id, overall_style, theme_prompt, instruments, bpm_range,
                    emotional_palette, mixing_rules, status, created_at, updated_at
                ) VALUES (
                    :drama_id, :overall_style, :theme_prompt, :instruments, :bpm_range,
                    :emotional_palette, :mixing_rules, :status, :now, :now
                )
                """
            ),
            params,
        )
        row_id = res.lastrowid
    return result_to_dict(db.execute(text("SELECT * FROM music_bibles WHERE id = :id"), {"id": row_id}).first())


def upsert_music_cues_for_episode(db: Session, drama_id: int, episode_id: int | None = None) -> list[dict[str, Any]]:
    """按分镜生成音乐/音效 Cue。"""
    if not episode_id:
        return []
    rows = fetch_all(
        db,
        """
        SELECT id, episode_id, emotion, atmosphere, action, dialogue, narration, storyboard_number
        FROM storyboards
        WHERE episode_id = :episode_id AND deleted_at IS NULL
        ORDER BY storyboard_number ASC, id ASC
        """,
        {"episode_id": episode_id},
    )
    results: list[dict[str, Any]] = []
    now = now_iso()
    for row in rows:
        emotion = str(row.get("emotion") or row.get("atmosphere") or "紧张").strip()
        action = str(row.get("action") or "").strip()
        bgm_prompt = f"{emotion}情绪下的短剧背景音乐，低频铺底，弦乐逐步推进，避免压过对白。"
        sfx_prompt = "根据动作补充真实环境声和轻量 Foley" if action else "轻微环境氛围声"
        existing = fetch_one(
            db,
            "SELECT id FROM music_cues WHERE storyboard_id = :sid AND cue_type = 'bgm' AND deleted_at IS NULL",
            {"sid": row["id"]},
        )
        params = {
            "drama_id": drama_id,
            "episode_id": episode_id,
            "storyboard_id": row["id"],
            "cue_type": "bgm",
            "emotion": emotion,
            "bgm_prompt": bgm_prompt,
            "sfx_prompt": sfx_prompt,
            "volume": 0.68,
            "start_offset": 0,
            "fade_in": 0.5,
            "fade_out": 1.0,
            "status": "draft",
            "now": now,
        }
        if existing:
            db.execute(
                text(
                    """
                    UPDATE music_cues
                    SET emotion = :emotion, bgm_prompt = :bgm_prompt, sfx_prompt = :sfx_prompt,
                        volume = :volume, start_offset = :start_offset, fade_in = :fade_in,
                        fade_out = :fade_out, status = :status, updated_at = :now
                    WHERE id = :id
                    """
                ),
                {**params, "id": existing["id"]},
            )
            row_id = existing["id"]
        else:
            res = db.execute(
                text(
                    """
                    INSERT INTO music_cues (
                        drama_id, episode_id, storyboard_id, cue_type, emotion, bgm_prompt, sfx_prompt,
                        volume, start_offset, fade_in, fade_out, status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :episode_id, :storyboard_id, :cue_type, :emotion, :bgm_prompt, :sfx_prompt,
                        :volume, :start_offset, :fade_in, :fade_out, :status, :now, :now
                    )
                    """
                ),
                params,
            )
            row_id = res.lastrowid
        results.append(result_to_dict(db.execute(text("SELECT * FROM music_cues WHERE id = :id"), {"id": row_id}).first()))
    return results


def generate_voice_music_design(db: Session, drama_id: int, episode_id: int | None = None) -> dict[str, Any]:
    """生成整剧声音与音乐设计产物。"""
    voices = upsert_character_voice_profiles(db, drama_id)
    music_bible = upsert_music_bible(db, drama_id)
    cues = upsert_music_cues_for_episode(db, drama_id, episode_id)
    return {
        "drama_id": drama_id,
        "episode_id": episode_id,
        "voice_profiles": voices,
        "music_bible": music_bible,
        "music_cues": cues,
    }


def list_character_voice_profiles(db: Session, drama_id: int) -> list[dict[str, Any]]:
    """查询指定短剧的角色声音配置列表。"""
    rows = fetch_all(
        db,
        """
        SELECT * FROM character_voice_profiles
        WHERE drama_id = :drama_id AND deleted_at IS NULL
        ORDER BY id ASC
        """,
        {"drama_id": drama_id},
    )
    return [_serialize_voice_profile(row) for row in rows]


def get_music_bible(db: Session, drama_id: int) -> dict[str, Any] | None:
    """获取指定短剧的整剧音乐设计 Bible。"""
    row = fetch_one(
        db,
        """
        SELECT * FROM music_bibles
        WHERE drama_id = :drama_id AND deleted_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        {"drama_id": drama_id},
    )
    if not row:
        return None
    row["instruments"] = json_loads(row.get("instruments"), [])
    row["emotional_palette"] = json_loads(row.get("emotional_palette"), [])
    return row


def list_music_cues(
    db: Session,
    *,
    drama_id: int | None = None,
    episode_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """查询分镜音乐与音效 Cue 列表。"""
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": limit}
    if episode_id:
        where.append("episode_id = :episode_id")
        params["episode_id"] = episode_id
    if drama_id:
        where.append("drama_id = :drama_id")
        params["drama_id"] = drama_id
    return fetch_all(
        db,
        "SELECT * FROM music_cues WHERE " + " AND ".join(where) + " ORDER BY id ASC LIMIT :limit",
        params,
    )


# =========================================================================
# V2 角色音色卡管理、母音频合成与阶段 6 分集新角色入册服务
# =========================================================================

def get_or_init_character_voice_profile(
    db: Session,
    drama_id: int,
    character_id: int,
) -> dict[str, Any]:
    """查询指定角色的 V2 音色卡；若尚未创建，则基于 characters 表 11 维人设自动初始化。"""
    char_row = fetch_one(
        db,
        """
        SELECT * FROM characters
        WHERE id = :cid AND drama_id = :drama_id AND deleted_at IS NULL
        """,
        {"cid": character_id, "drama_id": drama_id},
    )
    if not char_row:
        raise ValueError(f"未找到角色 (drama_id={drama_id}, character_id={character_id})")

    vp_row = fetch_one(
        db,
        """
        SELECT * FROM character_voice_profiles
        WHERE drama_id = :drama_id AND character_id = :cid AND deleted_at IS NULL
        ORDER BY is_master_card DESC, id DESC LIMIT 1
        """,
        {"drama_id": drama_id, "cid": character_id},
    )
    if vp_row:
        logger.debug(
            "【音色卡查询】[DEBUG] 命中现有 V2 音色卡: profile_id=%s, char_id=%s, master_voice_key=%s",
            vp_row.get("id"),
            character_id,
            vp_row.get("master_voice_key") or vp_row.get("voice_id"),
        )
        return _serialize_voice_profile(vp_row)

    # 若尚未存在，基于角色档案自动初始化 V2 音色卡
    from app.workflows.nodes.stage6_asset_truth import (
        _build_default_emotion_rules,
        _select_voice_archetype,
    )

    c_name = str(char_row.get("name") or f"角色_{character_id}").strip()
    c_code = str(char_row.get("character_code") or "").strip()
    tok = AssetProtocolHelper.normalize_token(c_code or c_name)
    if not c_code:
        c_code = f"CHAR_{tok}"
    master_voice_key = f"VOICE_{tok}_T1_MASTER"

    c_gender = str(char_row.get("gender") or "male").strip()
    c_age = str(char_row.get("perceived_age") or "28岁").strip()
    c_role = str(char_row.get("role") or "supporting").strip()

    existing_vps = fetch_all(
        db,
        "SELECT provider_voice_id FROM character_voice_profiles WHERE drama_id = :drama_id AND deleted_at IS NULL",
        {"drama_id": drama_id},
    )
    used_vids = {str(r.get("provider_voice_id") or "") for r in existing_vps if r.get("provider_voice_id")}
    archetype = _select_voice_archetype(
        gender=c_gender,
        age=c_age,
        role=c_role,
        used_voice_ids=used_vids,
        char_idx=character_id,
    )

    timbre_str = _voice_timbre(char_row)
    prompt_str = (
        f"【角色名】{c_name} 【音色原型】{archetype['timbre_archetype']}（{timbre_str}） "
        f"【发声共鸣部位】{archetype['vocal_position']} 【声学物理瑕疵】{archetype['vocal_flaws']} "
        f"【基准语速】1.0x 【演绎要求】严禁播音腔与电子机械感，保留真实呼吸停顿。"
    )
    sample_text = f"我是{c_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
    emotion_rules_dict = _build_default_emotion_rules(c_role)
    tw_json = json_dumps(archetype["timber_weights"])
    rules_json = json_dumps(emotion_rules_dict)
    sem_hash = hashlib.sha256(f"{master_voice_key}|{prompt_str}|{sample_text}".encode("utf-8")).hexdigest()[:16]
    now = now_iso()

    ins = db.execute(
        text(
            """
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
                :cid, :drama_id, :c_code, :c_name,
                :m_key, :m_key, :prompt, :prompt,
                :sample_text, :sample_text,
                :timbre, :timbre_archetype, :vocal_position, :vocal_flaws,
                'minimax', 'speech-02-hd', :provider_vid, :tw_json,
                1.0, 1.0, :rules_json,
                1, 'pending', :sem_hash,
                'active', :now, :now
            )
            """
        ),
        {
            "cid": character_id,
            "drama_id": drama_id,
            "c_code": c_code,
            "c_name": c_name,
            "m_key": master_voice_key,
            "prompt": prompt_str,
            "sample_text": sample_text,
            "timbre": timbre_str,
            "timbre_archetype": archetype["timbre_archetype"],
            "vocal_position": archetype["vocal_position"],
            "vocal_flaws": archetype["vocal_flaws"],
            "provider_vid": archetype["provider_voice_id"],
            "tw_json": tw_json,
            "rules_json": rules_json,
            "sem_hash": sem_hash,
            "now": now,
        },
    )
    db.commit()
    new_row = fetch_one(db, "SELECT * FROM character_voice_profiles WHERE id = :id", {"id": ins.lastrowid})
    logger.debug(
        "【音色卡自动初始化】[DEBUG] 为角色 [%s(id=%s)] 创建 V2 音色卡: profile_id=%s, master_voice_key=%s",
        c_name,
        character_id,
        ins.lastrowid,
        master_voice_key,
    )
    return _serialize_voice_profile(new_row)


def update_character_voice_profile_by_char(
    db: Session,
    drama_id: int,
    character_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """根据 drama_id + character_id 更新角色 V2 音色卡。"""
    vp = get_or_init_character_voice_profile(db, drama_id, character_id)
    updated = update_character_voice_profile(db, int(vp["id"]), payload)
    db.commit()
    return updated


def _resolve_default_storage_base() -> str:
    """获取默认本地存储根目录。"""
    try:
        cfg = cfgmod.load_config()
        return str(cfgmod.storage_local_path(cfg))
    except Exception:
        return str(Path("data/storage").resolve())


def synthesize_character_master_voice(
    db: Session,
    drama_id: int,
    character_id: int,
    payload: dict[str, Any] | None = None,
    storage_base: str | None = None,
) -> dict[str, Any]:
    """合成单个角色的基准母音频（VOICE_<TOKEN>_T1_MASTER），并四表联动落盘。

    四表联动：
    1. character_voice_profiles: 更新 sample_audio_path / sample_audio_url / synthesis_status='completed'
    2. assets: 注册或更新 VOICE_<TOKEN>_T1_MASTER 母音资产 (lifecycle_status='APPROVED')
    3. audio_generations: 写入母音合成审计记录 (audio_type='master_voice_reference')
    4. characters: 回填 seedance2_voice_asset JSON 供阶段 8 与多模态视频声画对齐直接引用
    """
    body = payload or {}
    vp = get_or_init_character_voice_profile(db, drama_id, character_id)
    profile_id = int(vp["id"])

    # 若请求体携带临时覆盖参数，先更新到音色卡
    override_updates: dict[str, Any] = {}
    if body.get("override_sample_text"):
        override_updates["master_sample_text"] = str(body["override_sample_text"])
    if body.get("override_tts_prompt"):
        override_updates["master_tts_prompt"] = str(body["override_tts_prompt"])
    for k in ("tts_provider", "tts_model", "provider_voice_id", "timber_weights", "speed_ratio", "pitch_ratio"):
        if k in body and body.get(k) is not None:
            override_updates[k] = body[k]
    if override_updates:
        vp = update_character_voice_profile(db, profile_id, override_updates) or vp

    master_voice_key = str(vp.get("master_voice_key") or vp.get("voice_id") or "").strip()
    if not master_voice_key:
        tok = AssetProtocolHelper.normalize_token(vp.get("character_code") or vp.get("character_name") or f"CHAR{character_id}")
        master_voice_key = f"VOICE_{tok}_T1_MASTER"

    raw_sample_text = str(
        body.get("override_sample_text")
        or vp.get("master_sample_text")
        or vp.get("script_monologue_source")
        or f"我是{vp.get('character_name') or '角色'}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
    ).strip()
    # 剥离剧本舞台提示括号，防止 TTS 朗读括号内容
    clean_sample_text = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", raw_sample_text).strip()
    if not clean_sample_text:
        clean_sample_text = f"我是{vp.get('character_name') or '角色'}，说到做到。"

    master_tts_prompt = str(
        body.get("override_tts_prompt")
        or vp.get("master_tts_prompt")
        or vp.get("voice_prompt")
        or ""
    ).strip()
    provider_voice_id = str(vp.get("provider_voice_id") or vp.get("voice_id") or "male-qn-qingse").strip()
    timber_weights = vp.get("timber_weights") if isinstance(vp.get("timber_weights"), list) else None
    speed_ratio = float(vp.get("speed_ratio") or 1.0)
    pitch_ratio = float(vp.get("pitch_ratio") or 1.0)
    semitone_pitch = int(round(12 * math.log2(max(pitch_ratio, 0.01))))

    base_dir = storage_base or _resolve_default_storage_base()
    rel_audio_path = f"audio/voices/{master_voice_key}.mp3"

    logger.debug(
        "【母音频合成启动】[DEBUG] drama_id=%s, char_id=%s, master_voice_key=%s, voice_id=%s, sample_text=%s",
        drama_id,
        character_id,
        master_voice_key,
        provider_voice_id,
        clean_sample_text,
    )

    synth_res = ttsService.synthesize(
        db,
        logger,
        {
            "text": clean_sample_text,
            "storage_base": base_dir,
            "voice_id": provider_voice_id,
            "speed": speed_ratio,
            "pitch": semitone_pitch,
            "timber_weights": timber_weights,
            "instructions": master_tts_prompt,
            "custom_rel_path": rel_audio_path,
            "allow_mock_fallback": True,
        },
    )

    local_path = str(synth_res.get("local_path") or rel_audio_path)
    audio_url = f"/static/{local_path.lstrip('/')}"
    duration_sec = float(synth_res.get("duration_sec") or 3.5)
    used_provider = str(synth_res.get("provider") or vp.get("tts_provider") or "minimax")
    used_model = str(synth_res.get("model") or vp.get("tts_model") or "speech-02-hd")
    now = now_iso()

    # 1. 更新 character_voice_profiles
    db.execute(
        text(
            """
            UPDATE character_voice_profiles
            SET master_voice_key = :m_key,
                voice_id = :m_key,
                master_sample_text = :sample_text,
                sample_audio_path = :local_path,
                sample_audio_url = :audio_url,
                reference_audio_url = :audio_url,
                sample_duration_sec = :duration_sec,
                synthesis_status = 'CERTIFIED',
                updated_at = :now
            WHERE id = :id
            """
        ),
        {
            "id": profile_id,
            "m_key": master_voice_key,
            "sample_text": clean_sample_text,
            "local_path": local_path,
            "audio_url": audio_url,
            "duration_sec": duration_sec,
            "now": now,
        },
    )

    # 2. 写入或更新 assets 表中的母音资产 (VOICE_<TOKEN>_T1_MASTER)
    existing_asset = fetch_one(
        db,
        "SELECT id, metadata FROM assets WHERE drama_id = :drama_id AND asset_key = :a_key AND deleted_at IS NULL",
        {"drama_id": drama_id, "a_key": master_voice_key},
    )
    asset_meta = json_loads(existing_asset.get("metadata") if existing_asset else None, {})
    if not isinstance(asset_meta, dict):
        asset_meta = {}
    asset_meta.update(
        {
            "lifecycle_status": "APPROVED",
            "local_path": local_path,
            "audio_url": audio_url,
            "duration_sec": duration_sec,
            "character_id": character_id,
            "character_name": vp.get("character_name"),
            "timbre_archetype": vp.get("timbre_archetype"),
            "provider_voice_id": provider_voice_id,
        }
    )
    asset_params = {
        "tts_provider": used_provider,
        "tts_model": used_model,
        "provider_voice_id": provider_voice_id,
        "timber_weights": timber_weights or [],
        "speed_ratio": speed_ratio,
        "pitch_ratio": pitch_ratio,
    }
    if existing_asset:
        asset_db_id = existing_asset["id"]
        db.execute(
            text(
                """
                UPDATE assets
                SET name = :name,
                    type = 'audio',
                    category = 'voice',
                    generation_mode = 'tts',
                    is_benchmark = 1,
                    prompt = :prompt,
                    params = :params,
                    metadata = :metadata,
                    updated_at = :now
                WHERE id = :id
                """
            ),
            {
                "id": asset_db_id,
                "name": f"{vp.get('character_name') or ''}母音卡",
                "prompt": master_tts_prompt,
                "params": json_dumps(asset_params),
                "metadata": json_dumps(asset_meta),
                "now": now,
            },
        )
    else:
        ins_asset = db.execute(
            text(
                """
                INSERT INTO assets (
                    drama_id, asset_key, name, type, category,
                    generation_mode, is_benchmark, prompt, negative_prompt,
                    params, metadata, created_at, updated_at
                ) VALUES (
                    :drama_id, :asset_key, :name, 'audio', 'voice',
                    'tts', 1, :prompt, '禁止机械电音、播音腔、背景底噪',
                    :params, :metadata, :now, :now
                )
                """
            ),
            {
                "drama_id": drama_id,
                "asset_key": master_voice_key,
                "name": f"{vp.get('character_name') or ''}母音卡",
                "prompt": master_tts_prompt,
                "params": json_dumps(asset_params),
                "metadata": json_dumps(asset_meta),
                "now": now,
            },
        )
        asset_db_id = ins_asset.lastrowid

    # 3. 写入 audio_generations 审计表
    ins_ag = db.execute(
        text(
            """
            INSERT INTO audio_generations (
                drama_id, character_id, generation_type, audio_type, provider,
                prompt, result, url, local_path, duration_sec, status, extra,
                created_at, updated_at
            ) VALUES (
                :drama_id, :cid, 'tts', 'master_voice_reference', :provider,
                :text, :result_json, :audio_url, :local_path, :duration_sec, 'completed', :extra,
                :now, :now
            )
            """
        ),
        {
            "drama_id": drama_id,
            "cid": character_id,
            "provider": used_provider,
            "text": clean_sample_text,
            "result_json": json_dumps({"model": used_model, "voice_id": provider_voice_id}),
            "audio_url": audio_url,
            "local_path": local_path,
            "duration_sec": duration_sec,
            "extra": json_dumps(
                {
                    "master_voice_key": master_voice_key,
                    "profile_id": profile_id,
                    "asset_id": asset_db_id,
                    "model": used_model,
                    "voice_id": provider_voice_id,
                    "timber_weights": timber_weights or [],
                }
            ),
            "now": now,
        },
    )

    # 4. 同步回填 characters.seedance2_voice_asset
    seedance_voice_payload = {
        "status": "certified",
        "master_voice_key": master_voice_key,
        "audio_url": audio_url,
        "local_path": local_path,
        "duration_sec": duration_sec,
        "timbre_archetype": vp.get("timbre_archetype"),
        "provider_voice_id": provider_voice_id,
        "updated_at": now,
    }
    db.execute(
        text("UPDATE characters SET seedance2_voice_asset = :sva, updated_at = :now WHERE id = :cid"),
        {"cid": character_id, "sva": json_dumps(seedance_voice_payload), "now": now},
    )

    db.commit()
    logger.debug(
        "【母音频合成完成】[DEBUG] 四表联动已提交: profile_id=%s, asset_id=%s, audio_gen_id=%s, url=%s",
        profile_id,
        asset_db_id,
        ins_ag.lastrowid,
        audio_url,
    )
    updated_vp = fetch_one(db, "SELECT * FROM character_voice_profiles WHERE id = :id", {"id": profile_id})
    return {
        "profile_id": profile_id,
        "character_id": character_id,
        "character_name": vp.get("character_name"),
        "master_voice_key": master_voice_key,
        "sample_audio_path": local_path,
        "sample_audio_url": audio_url,
        "sample_duration_sec": duration_sec,
        "synthesis_status": "CERTIFIED",
        "asset_id": asset_db_id,
        "audio_generation_id": ins_ag.lastrowid,
        "voice_profile": _serialize_voice_profile(updated_vp),
    }


def batch_synthesize_drama_master_voices(
    db: Session,
    drama_id: int,
    payload: dict[str, Any] | None = None,
    storage_base: str | None = None,
) -> dict[str, Any]:
    """一键批量合成全剧（或指定角色列表）的母音参考音频。"""
    body = payload or {}
    only_pending = bool(body.get("only_pending", False))
    target_char_ids = body.get("character_ids")

    chars = fetch_all(
        db,
        "SELECT id, name, character_code FROM characters WHERE drama_id = :drama_id AND deleted_at IS NULL ORDER BY id ASC",
        {"drama_id": drama_id},
    )
    if isinstance(target_char_ids, list) and target_char_ids:
        id_set = {int(x) for x in target_char_ids if str(x).isdigit()}
        chars = [c for c in chars if int(c["id"]) in id_set]

    synthesized_list: list[dict[str, Any]] = []
    skipped_count = 0

    for ch in chars:
        cid = int(ch["id"])
        vp = get_or_init_character_voice_profile(db, drama_id, cid)
        if only_pending and str(vp.get("synthesis_status") or "").upper() in ("COMPLETED", "CERTIFIED") and vp.get("sample_audio_url"):
            skipped_count += 1
            logger.debug("【批量母音频合成】[DEBUG] 跳过已完成角色: char_id=%s, name=%s", cid, ch.get("name"))
            continue
        res_item = synthesize_character_master_voice(
            db,
            drama_id=drama_id,
            character_id=cid,
            payload=None,
            storage_base=storage_base,
        )
        synthesized_list.append(res_item)

    logger.debug(
        "【批量母音频合成汇总】[DEBUG] drama_id=%s, 合成成功=%d, 跳过=%d",
        drama_id,
        len(synthesized_list),
        skipped_count,
    )
    return {
        "drama_id": drama_id,
        "total_characters": len(chars),
        "synthesized_count": len(synthesized_list),
        "skipped_count": skipped_count,
        "results": synthesized_list,
    }


def onboard_unregistered_episode_character(
    db: Session,
    drama_id: int,
    episode_num: int,
    payload: dict[str, Any],
    storage_base: str | None = None,
) -> dict[str, Any]:
    """分集未注册新角色按【阶段 2 工业级 11 维标准】全量补建入册并初始化 T1 视觉母盘与 V2 音色卡。"""
    from app.workflows.adapters.drama_storage_adapter import persist_stage6
    from app.workflows.nodes.stage6_asset_truth import (
        _build_default_emotion_rules,
        _build_stage2_character_dossier,
        _select_voice_archetype,
        _strip_dialogue_brackets,
    )

    body = payload or {}
    c_name = str(body.get("character_name") or body.get("name") or "").strip()
    if not c_name:
        raise ValueError("character_name 不能为空")

    role_hint = str(body.get("role_hint") or body.get("role") or "supporting").strip()
    raw_lines = body.get("sample_lines") or body.get("context_lines")
    sample_lines = raw_lines if isinstance(raw_lines, list) else []
    script_excerpt = str(body.get("script_context") or "\n".join(str(x) for x in sample_lines) or "").strip()
    if not sample_lines and script_excerpt:
        sample_lines = [script_excerpt]

    existing_chars = fetch_all(
        db,
        "SELECT id, name, character_code, role FROM characters WHERE drama_id = :drama_id AND deleted_at IS NULL",
        {"drama_id": drama_id},
    )
    known_dicts = [dict(r) for r in existing_chars]
    existing_char_codes = {
        str(r.get("character_code") or "").strip()
        for r in known_dicts
        if r.get("character_code")
    }
    protagonist_row = next(
        (r for r in known_dicts if str(r.get("role") or "").lower() in ("protagonist", "lead", "男主", "女主", "主角")),
        known_dicts[0] if known_dicts else {"character_code": "CHAR_PROTAGONIST", "name": "主角"},
    )

    existing_vps = fetch_all(
        db,
        "SELECT timbre_archetype, provider_voice_id FROM character_voice_profiles WHERE drama_id = :drama_id AND deleted_at IS NULL",
        {"drama_id": drama_id},
    )
    used_archetypes = {
        str(r.get("timbre_archetype") or "").strip()
        for r in existing_vps
        if r.get("timbre_archetype")
    }

    # 1. 构建阶段 2 完整 11 维角色档案
    dossier = _build_stage2_character_dossier(
        char_name=c_name,
        episode_num=episode_num,
        screenplay_text=script_excerpt,
        existing_char_codes=existing_char_codes,
        used_archetypes=used_archetypes,
        primary_protagonist_code=str(protagonist_row.get("character_code") or "CHAR_PROTAGONIST"),
        primary_protagonist_name=str(protagonist_row.get("name") or "主角"),
        index_hint=len(known_dicts) + 1,
    )
    if role_hint:
        dossier["role"] = role_hint
    if body.get("gender"):
        dossier["gender"] = str(body["gender"]).strip()
    if body.get("perceived_age"):
        dossier["perceived_age"] = int(body["perceived_age"])

    tok = AssetProtocolHelper.normalize_token(dossier["character_code"] or c_name)
    portrait_key = f"CHAR_{tok}_T1_BASE_PORTRAIT"
    costume_key = f"CHAR_{tok}_T1_BASE_COSTUME"
    voice_key = f"VOICE_{tok}_T1_MASTER"

    # 2. 分配不撞车声线原型与 V2 音色卡
    archetype = _select_voice_archetype(
        {"name": c_name, "gender": dossier["gender"]},
        used_archetypes=set(),
        index_hint=len(known_dicts) + 1,
    )
    clean_line = _strip_dialogue_brackets(sample_lines[0], c_name) if sample_lines else ""
    if len(clean_line) < 12:
        clean_line = f"我是{c_name}，有些账哪怕跨越漫长岁月，也终究要亲手算个清楚。"
    else:
        clean_line = clean_line[:48]

    voice_card = {
        "master_voice_id": voice_key,
        "master_voice_key": voice_key,
        "character_code": dossier["character_code"],
        "character_name": c_name,
        "timbre": dossier["voice_style"],
        "timbre_archetype": archetype["timbre_archetype"],
        "vocal_position": archetype["vocal_position"],
        "vocal_flaws": archetype["vocal_flaws"],
        "master_tts_prompt": (
            f"【角色名】{c_name} 【音色原型】{archetype['timbre_archetype']}（{dossier['voice_style']}） "
            f"【发声共鸣部位】{archetype['vocal_position']} 【声学物理瑕疵】{archetype['vocal_flaws']} "
            f"【基准语速】1.0x 【演绎要求】严禁播音腔与电子机械感，保留真实呼吸停顿。"
        ),
        "master_sample_text": clean_line,
        "script_monologue_source": clean_line,
        "tts_provider": "minimax",
        "tts_model": "speech-02-hd",
        "provider_voice_id": archetype["provider_voice_id"],
        "timber_weights": archetype["timber_weights"],
        "speed_ratio": 1.0,
        "pitch_ratio": 1.0,
        "emotion_rules": _build_default_emotion_rules(),
        "is_master_card": 1,
    }

    # 3. 构建 T1 视觉母盘资产与 manifest 并调用 persist_stage6 落库
    new_assets = [
        {
            "asset_id": portrait_key,
            "asset_key": portrait_key,
            "name": f"{c_name}面部骨相基准母盘",
            "category": "character",
            "type": "image",
            "generation_mode": "t2i",
            "denoise_strength": 0.35,
            "is_benchmark": True,
            "visual_prompt": f"{c_name}，{dossier['appearance']}，面部骨相特写定妆照，85mm人像镜头，真实皮肤微瑕毛孔，8k写实",
            "negative_prompt": "网红磨皮，塑胶假脸，畸形五官，卡通二次元",
        },
        {
            "asset_id": costume_key,
            "asset_key": costume_key,
            "name": f"{c_name}全身服装正立面母盘",
            "category": "character",
            "type": "image",
            "parent_asset_id": portrait_key,
            "input_source_image": portrait_key,
            "generation_mode": "i2i",
            "denoise_strength": 0.40,
            "is_benchmark": True,
            "visual_prompt": f"{c_name}，从头到脚全身站姿，{dossier['appearance']}，双脚稳固踩在地面，真实织物垂坠感，8k写实",
            "negative_prompt": "半身截断，悬空脚，多手指，畸形肢体",
        },
    ]

    # 确保对应分集存在
    ep_row = fetch_one(
        db,
        "SELECT id FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL",
        {"drama_id": drama_id, "ep_num": episode_num},
    )
    if not ep_row:
        now = now_iso()
        db.execute(
            text(
                """
                INSERT INTO episodes (drama_id, episode_number, title, status, created_at, updated_at)
                VALUES (:drama_id, :ep_num, :title, 'draft', :now, :now)
                """
            ),
            {"drama_id": drama_id, "ep_num": episode_num, "title": f"第{episode_num}集", "now": now},
        )
        db.commit()

    mini_manifest = {
        "episode_num": episode_num,
        "newly_discovered_characters": [dossier],
        "characters_tier_1": [
            {
                "char_id": portrait_key,
                "character_code": dossier["character_code"],
                "character_name": c_name,
                "gender": dossier["gender"],
                "perceived_age": dossier["perceived_age"],
                "role": dossier["role"],
                "personality": dossier["personality"],
                "appearance": dossier["appearance"],
                "voice_style": dossier["voice_style"],
                "base_portrait": portrait_key,
                "base_costume": costume_key,
                "visual_prompt": new_assets[0]["visual_prompt"],
            }
        ],
        "new_character_master_voice_cards": [voice_card],
        "newly_generated_assets": new_assets,
        "reused_existing_assets": [],
        "asset_lineage_dag": {
            portrait_key: {"parent_asset_id": None, "generation_mode": "t2i", "denoise_strength": 0.35, "is_benchmark": True},
            costume_key: {"parent_asset_id": portrait_key, "generation_mode": "i2i", "denoise_strength": 0.40, "is_benchmark": True},
        },
    }

    persist_stage6(db, drama_id, {"episode_num": episode_num, "manifest": mini_manifest}, episode_num=episode_num)

    char_db = fetch_one(
        db,
        "SELECT * FROM characters WHERE drama_id = :drama_id AND (character_code = :c_code OR name = :c_name) AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        {"drama_id": drama_id, "c_code": dossier["character_code"], "c_name": c_name},
    )
    char_id = int(char_db["id"])
    vp_serialized = get_or_init_character_voice_profile(db, drama_id, char_id)

    synth_result = None
    if body.get("synthesize_master_audio", False) or body.get("auto_synthesize_master_voice", False):
        synth_result = synthesize_character_master_voice(
            db,
            drama_id=drama_id,
            character_id=char_id,
            storage_base=storage_base,
        )
        vp_serialized = synth_result.get("voice_profile") or vp_serialized

    logger.debug(
        "【新角色阶段 2 标准入册完成】[DEBUG] drama_id=%s, ep=%s, char_id=%s, code=%s, name=%s, 已合成母音=%s",
        drama_id,
        episode_num,
        char_id,
        dossier["character_code"],
        c_name,
        bool(synth_result),
    )

    return {
        "character_id": char_id,
        "character_code": dossier["character_code"],
        "character_name": c_name,
        "onboarded_stage2_dossier": dossier,
        "visual_t1_assets": [portrait_key, costume_key],
        "voice_profile": vp_serialized,
        "master_audio_synthesis": synth_result,
        "master_voice_synthesis": synth_result,
    }


def run_stage6_incremental_audit(
    db: Session,
    drama_id: int,
    episode_num: int,
    payload: dict[str, Any] | None = None,
    storage_base: str | None = None,
) -> dict[str, Any]:
    """执行第 N 集的阶段 6 视觉资产增量审计、未注册新角色阶段 2 标准入册及 V2 音色卡落库。"""
    from app.workflows.adapters.drama_storage_adapter import (
        load_master_state_from_db,
        persist_stage6,
    )
    from app.workflows.nodes.stage6_asset_truth import stage6_asset_truth_node

    body = payload or {}
    state = load_master_state_from_db(db, drama_id)
    state.current_visual_episode = episode_num

    auto_synth = bool(
        body.get("auto_synthesize_master_voices", False)
        or body.get("auto_synthesize_master_voice", False)
    )
    logger.debug(
        "【阶段 6 增量审计接口】[DEBUG] 启动: drama_id=%s, episode_num=%s, auto_synthesize_master_voices=%s",
        drama_id,
        episode_num,
        auto_synth,
    )

    node_out = stage6_asset_truth_node(state)
    manifest = (node_out.get("episode_manifests") or {}).get(episode_num) or {}
    state.episode_manifests[episode_num] = manifest
    if node_out.get("visual_audio_assets_registry"):
        state.visual_audio_assets_registry = node_out["visual_audio_assets_registry"]
    if node_out.get("character_tokens"):
        state.character_tokens = node_out["character_tokens"]
    if node_out.get("relationship_matrix"):
        state.relationship_matrix = node_out["relationship_matrix"]

    persist_stage6(db, drama_id, state, episode_num=episode_num)

    manifest_dict = manifest.to_dict() if hasattr(manifest, "to_dict") else (manifest if isinstance(manifest, dict) else {})
    synth_summary = None
    if auto_synth:
        synth_summary = batch_synthesize_drama_master_voices(
            db,
            drama_id=drama_id,
            payload={"only_pending": True},
            storage_base=storage_base,
        )

    newly_chars = manifest_dict.get("newly_discovered_characters", []) or []
    return {
        "drama_id": drama_id,
        "episode_num": episode_num,
        "newly_discovered_characters_count": len(newly_chars),
        "newly_discovered_characters": newly_chars,
        "reused_existing_assets": manifest_dict.get("reused_existing_assets", []),
        "newly_generated_assets": manifest_dict.get("newly_generated_assets", []),
        "new_character_master_voice_cards": manifest_dict.get("new_character_master_voice_cards", []),
        "asset_lineage_dag": manifest_dict.get("asset_lineage_dag", {}),
        "master_voices_synthesis_summary": synth_summary,
    }
