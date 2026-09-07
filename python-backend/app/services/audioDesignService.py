"""声音与音乐设计服务。

当前版本先用规则生成 Voice Profile / Music Bible / Music Cue，作为后续声音 Agent、
音乐 Agent 和 TTS/BGM 生成模型的稳定输入。等 Prompt/Skill 成熟后，可以把这里的
规则生成替换成 AI 结构化输出。
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import fetch_all, fetch_one, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso


def _serialize_voice_profile(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """统一声音档案输出，并提供前端历史字段的兼容别名。"""
    if not row:
        return None
    item = dict(row)
    emotion_rules = json_loads(item.get("emotion_rules"), [])
    item["emotion_rules"] = emotion_rules
    item["negative_traits"] = json_loads(item.get("negative_traits"), [])
    item["voice_name"] = item.get("voice_id") or ""
    item["speed"] = float(item.get("speed_ratio") or 1.0)
    pitch_ratio = max(float(item.get("pitch_ratio") or 1.0), 0.01)
    item["pitch"] = round(12 * math.log2(pitch_ratio), 2)
    item["sample_audio_url"] = item.get("reference_audio_url") or ""
    default_rule = next((str(rule) for rule in emotion_rules if str(rule).startswith("默认情绪：")), "")
    item["emotion"] = default_rule.removeprefix("默认情绪：") or "neutral"
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
    for field in ("voice_prompt", "timbre", "provider", "voice_id", "reference_audio_url", "status"):
        if field in body:
            updates[field] = str(body.get(field) or "").strip()

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
        rules = [str(rule) for rule in rules if not str(rule).startswith("默认情绪：")]
        updates["emotion_rules"] = json_dumps([f"默认情绪：{emotion}", *rules])

    if not updates:
        return _serialize_voice_profile(current)

    # 字段名只来自上面的固定白名单，用户输入永远不会直接进入 SQL 结构部分。
    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{field} = :{field}" for field in updates)
    db.execute(
        text(f"UPDATE character_voice_profiles SET {assignments} WHERE id = :id"),
        {**updates, "id": profile_id},
    )
    updated = fetch_one(db, "SELECT * FROM character_voice_profiles WHERE id = :id", {"id": profile_id})
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
