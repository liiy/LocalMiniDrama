"""Phase 6: 角色声音与整剧音乐体系 (迭代 7) 单元测试。

验证 VoiceProfile 生成与持久化、MusicBible 体系、MusicCue 分镜配乐与 Platform Audio API。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.platform import router as platform_router
from app.db.session import get_db
from app.schemas.audio import MusicBible, MusicCue, VoiceProfile
from app.services import audioDesignService
from app.skills import bootstrap_service


def _create_test_drama_and_characters(db):
    """辅助创建测试短剧、角色与分镜数据。"""
    from sqlalchemy import text
    from app.platform_common import now_iso

    now = now_iso()
    res = db.execute(
        text(
            """
            INSERT INTO dramas (title, genre, style, status, created_at, updated_at)
            VALUES ('极道医圣', '都市神医', '悬疑爽剧', 'active', :now, :now)
            """
        ),
        {"now": now},
    )
    drama_id = res.lastrowid

    # 角色 1：主角
    db.execute(
        text(
            """
            INSERT INTO characters (drama_id, name, role, description, personality, appearance, created_at, updated_at)
            VALUES (:drama_id, '林辰', 'protagonist', '隐忍三年的极道医圣', '表面温和内心冷峻', '青年男子身着布衣', :now, :now)
            """
        ),
        {"drama_id": drama_id, "now": now},
    )

    # 角色 2：反派
    db.execute(
        text(
            """
            INSERT INTO characters (drama_id, name, role, description, personality, appearance, created_at, updated_at)
            VALUES (:drama_id, '江浩天', 'antagonist', '跋扈富二代', '残忍傲慢', '西装革履神态嚣张', :now, :now)
            """
        ),
        {"drama_id": drama_id, "now": now},
    )

    # 分集与分镜
    res_ep = db.execute(
        text(
            """
            INSERT INTO episodes (drama_id, episode_number, title, created_at, updated_at)
            VALUES (:drama_id, 1, '第1集 龙隐受辱', :now, :now)
            """
        ),
        {"drama_id": drama_id, "now": now},
    )
    episode_id = res_ep.lastrowid

    db.execute(
        text(
            """
            INSERT INTO storyboards (
                episode_id, storyboard_number, action, dialogue, emotion, created_at, updated_at
            ) VALUES (
                :episode_id, 1, '江浩天猛摔酒杯，林辰眼神微冷', '今天若不跪下，别想踏出江家半步！', '剑拔弩张', :now, :now
            )
            """
        ),
        {"episode_id": episode_id, "now": now},
    )

    return drama_id, episode_id


def test_voice_and_music_schemas():
    """测试 Audio 相关 Pydantic Schema 校验。"""
    vp = VoiceProfile(
        character_name="林辰",
        timbre_description="低沉磁性，咬字清晰",
        gender_age_category="青年男性",
        speaking_speed_ratio=1.1,
    )
    assert vp.character_name == "林辰"
    assert vp.speaking_speed_ratio == 1.1

    mb = MusicBible(
        overall_music_genre="都市悬疑影视配乐",
        tempo_bpm_range="100 - 130 BPM",
    )
    assert "大提琴" in mb.lead_instruments[0]

    cue = MusicCue(
        scene_number=1,
        bgm_prompt="极度压抑紧张的弦乐重音",
        target_volume=0.8,
    )
    assert cue.target_volume == 0.8


def test_audio_design_service(db_session):
    """测试声音与音乐设计服务生成与查询。"""
    bootstrap_service.bootstrap_defaults(db_session)
    drama_id, episode_id = _create_test_drama_and_characters(db_session)

    design = audioDesignService.generate_voice_music_design(db_session, drama_id, episode_id)
    assert len(design["voice_profiles"]) == 2
    assert design["music_bible"]["drama_id"] == drama_id
    assert len(design["music_cues"]) == 1

    # 验证查询方法
    voices = audioDesignService.list_character_voice_profiles(db_session, drama_id)
    assert len(voices) == 2
    assert any(v["character_name"] == "林辰" for v in voices)

    bible = audioDesignService.get_music_bible(db_session, drama_id)
    assert bible is not None
    assert "短剧配乐" in bible["overall_style"]

    cues = audioDesignService.list_music_cues(db_session, episode_id=episode_id)
    assert len(cues) == 1
    assert cues[0]["emotion"] == "剑拔弩张"


def test_platform_audio_endpoints(db_session):
    """测试 Platform 平台级 Audio API。"""
    bootstrap_service.bootstrap_defaults(db_session)
    drama_id, episode_id = _create_test_drama_and_characters(db_session)

    app = FastAPI()
    app.include_router(platform_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    # 1. 自动生成声音与音乐
    res = client.post("/api/v1/platform/audio/design/generate", json={"drama_id": drama_id, "episode_id": episode_id})
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data["voice_profiles"]) == 2

    # 2. 查询声音列表
    res_voices = client.get(f"/api/v1/platform/audio/voice-profiles?drama_id={drama_id}")
    assert res_voices.status_code == 200
    assert len(res_voices.json()["data"]) == 2

    # 3. 查询 Music Bible
    res_bible = client.get(f"/api/v1/platform/audio/music-bible?drama_id={drama_id}")
    assert res_bible.status_code == 200
    assert res_bible.json()["data"]["drama_id"] == drama_id

    # 4. 查询 Music Cues
    res_cues = client.get(f"/api/v1/platform/audio/music-cues?episode_id={episode_id}")
    assert res_cues.status_code == 200
    assert len(res_cues.json()["data"]) == 1

    # 5. 声音档案更新走 SQL 服务，并兼容前端 speed/pitch/voice_name 字段。
    profile_id = data["voice_profiles"][0]["id"]
    res_update = client.put(
        f"/api/v1/platform/audio/voice-profiles/{profile_id}",
        json={
            "voice_name": "zh-CN-XiaoxiaoNeural",
            "speed": 1.15,
            "pitch": 2,
            "emotion": "happy",
        },
    )
    assert res_update.status_code == 200
    updated = res_update.json()["data"]
    assert updated["voice_id"] == "zh-CN-XiaoxiaoNeural"
    assert updated["speed"] == 1.15
    assert updated["pitch"] == 2.0
    assert updated["emotion"] == "happy"

    # 6. 本地配乐检索可直接使用；远程 Provider 缺配置时必须明确失败。
    res_music = client.post(
        "/api/v1/platform/audio/music/generate",
        json={"provider": "local", "mood": "紧张", "duration_seconds": 20},
    )
    assert res_music.status_code == 200
    assert res_music.json()["data"]["audio_url"].startswith("/static/audio/bgm/")

    res_missing_config = client.post(
        "/api/v1/platform/audio/music/generate",
        json={"provider": "suno", "prompt": "悬疑配乐"},
    )
    assert res_missing_config.status_code == 400
