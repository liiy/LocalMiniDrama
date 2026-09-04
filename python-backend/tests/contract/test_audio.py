"""契约安全网：/api/v1/audio/* 与 Node 版 backend-node/src/routes/audio.js 行为等价。

Node 行为基线：
- POST /audio/extract
  - 无 text 且无 storyboard_id        → 400 '请提供 storyboard_id 或 text'
  - kind=narration 且文本为空         → 400 '分镜解说旁白为空，无法合成语音'
  - kind=dialogue（默认）且文本为空   → 400 '分镜对白为空，无法合成语音'
  - 成功 → { local_path, url: '/static/{local_path}', tts_kind }
  - 写回：narration → narration_audio_local_path；dialogue → audio_local_path
- POST /audio/extract/batch
  - storyboard_ids 缺失/空数组/非数组 → 400 'storyboard_ids 不能为空'
  - 恒取 dialogue 字段（无 tts_kind 参数）
  - 逐条独立：对白为空 → { storyboard_id, error: '对白为空' }，不中断后续

网络层全部 stub：synthesize_with_minimax / synthesize_with_openai 替换为返回固定
MP3 字节的假实现，仅验证路由编排与落盘/写库逻辑。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1 import audio as v1_audio
from app.db import session as dbm
from app.services import ttsService

EXTRACT = "/api/v1/audio/extract"
BATCH = "/api/v1/audio/extract/batch"

FAKE_AUDIO = b"ID3\x03fake-mp3-bytes"
MINIMAX_PAYLOAD = {
    "data": {"audio": FAKE_AUDIO.hex()},
    "base_resp": {"status_code": 0, "status_msg": ""},
}


@pytest.fixture(autouse=True)
def _tmp_storage(tmp_path, monkeypatch):
    """落盘目录指向临时目录；响应只含相对路径，不影响契约断言。"""
    monkeypatch.setattr(v1_audio, "_CFG", {"storage": {"local_path": str(tmp_path)}})
    yield tmp_path


@pytest.fixture
def _stub_tts(monkeypatch):
    """stub TTS HTTP 层，记录调用参数。"""
    calls: list[dict] = []

    def fake_minimax(text, voice_id, api_key, group_id, model):
        calls.append({"provider": "minimax", "text": text, "voice_id": voice_id,
                      "group_id": group_id, "model": model, "api_key": api_key})
        return FAKE_AUDIO

    def fake_openai(text, voice, api_key, base_url, model, speed):
        calls.append({"provider": "openai", "text": text, "voice": voice,
                      "base_url": base_url, "model": model, "speed": speed})
        return FAKE_AUDIO

    monkeypatch.setattr(ttsService, "synthesize_with_minimax", fake_minimax)
    monkeypatch.setattr(ttsService, "synthesize_with_openai", fake_openai)
    return calls


def _seed_drama(title="测试剧", created_at="2026-03-09T00:00:00.000Z") -> int:
    with dbm.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO dramas (title, created_at, updated_at) VALUES (:t, :c, :c)"),
            {"t": title, "c": created_at},
        )
        return conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()


def _seed_episode(drama_id: int, title="第1集") -> int:
    with dbm.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO episodes (drama_id, title, episode_number) VALUES (:d, :t, 1)"),
            {"d": drama_id, "t": title},
        )
        return conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()


def _seed_storyboard(episode_id: int, dialogue="你好世界", narration="旁白内容") -> int:
    with dbm.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO storyboards (episode_id, dialogue, narration) VALUES (:e, :d, :n)"),
            {"e": episode_id, "d": dialogue, "n": narration},
        )
        return conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()


def _seed_tts_config(provider="openai", **over) -> None:
    """写入一条 is_active 的 tts 配置（走真实 ai_configs 逻辑）。"""
    with dbm.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ai_service_configs "
                "(service_type, provider, api_protocol, name, base_url, api_key, model, default_model, "
                " priority, is_default, is_active, settings, created_at, updated_at) "
                "VALUES ('tts', :p, '', 'TTS', :base, 'sk-tts', '[\"tts-1\"]', :dm, "
                "        0, 1, 1, :settings, '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')"
            ),
            {
                "p": provider,
                "base": over.get("base_url") or "",
                "dm": over.get("default_model") or "tts-1",
                "settings": over.get("settings"),
            },
        )


# ---------------- 校验分支 ----------------


def test_extract_no_text_no_storyboard_id(client: TestClient):
    r = client.post(EXTRACT, json={})
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "BAD_REQUEST", "message": "请提供 storyboard_id 或 text"}


def test_extract_falsy_text_and_zero_storyboard_id(client: TestClient):
    """Node: !text && !storyboard_id —— 0 与 '' 都是 falsy。"""
    r = client.post(EXTRACT, json={"text": "", "storyboard_id": 0})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "请提供 storyboard_id 或 text"


def test_extract_narration_empty_returns_narration_error(client: TestClient):
    r = client.post(EXTRACT, json={"tts_kind": "narration", "text": "   "})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "分镜解说旁白为空，无法合成语音"


def test_extract_dialogue_empty_returns_dialogue_error(client: TestClient):
    r = client.post(EXTRACT, json={"text": "   "})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "分镜对白为空，无法合成语音"


def test_extract_unknown_storyboard_and_no_text(client: TestClient):
    """查不到分镜 → 文本仍为空 → '对白为空'。"""
    r = client.post(EXTRACT, json={"storyboard_id": 999999})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "分镜对白为空，无法合成语音"


def test_extract_unknown_kind_falls_back_to_dialogue(client: TestClient):
    """tts_kind 非 narration（含大写变体外的任意值）→ dialogue。"""
    r = client.post(EXTRACT, json={"storyboard_id": 999999, "tts_kind": "singing"})
    assert r.json()["error"]["message"] == "分镜对白为空，无法合成语音"


def test_batch_requires_non_empty_array(client: TestClient):
    for body in ({}, {"storyboard_ids": []}, {"storyboard_ids": "1"}, {"storyboard_ids": None}):
        r = client.post(BATCH, json=body)
        assert r.status_code == 400
        assert r.json()["error"] == {"code": "BAD_REQUEST", "message": "storyboard_ids 不能为空"}


def test_extract_no_tts_config_returns_500(client: TestClient, _stub_tts):
    r = client.post(EXTRACT, json={"text": "你好"})
    assert r.status_code == 500
    assert "未配置 TTS 模型" in r.json()["error"]["message"]


# ---------------- 成功路径 ----------------


def test_extract_with_inline_text(client: TestClient, _stub_tts, _tmp_storage):
    _seed_tts_config()
    r = client.post(EXTRACT, json={"text": "你好"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) == {"local_path", "url", "tts_kind"}
    assert data["tts_kind"] == "dialogue"
    assert data["local_path"].startswith("audio/tts_sbx_")
    assert data["local_path"].endswith(".mp3")
    assert data["url"] == f"/static/{data['local_path']}"
    # 文件真实落盘，且内容为 stub 返回的字节
    assert (Path(_tmp_storage) / data["local_path"]).read_bytes() == FAKE_AUDIO
    # 无 storyboard_id → 不写库
    assert _stub_tts[0] == {"provider": "openai", "text": "你好", "voice": "alloy",
                            "base_url": "", "model": "tts-1", "speed": 1.0}


def test_extract_narration_kind_normalized(client: TestClient, _stub_tts):
    _seed_tts_config()
    r = client.post(EXTRACT, json={"text": "旁白", "tts_kind": "NARRATION"})
    assert r.json()["data"]["tts_kind"] == "narration"  # toLowerCase


def test_extract_falls_back_to_storyboard_dialogue(client: TestClient, _stub_tts):
    _seed_tts_config()
    sb = _seed_storyboard(_seed_episode(_seed_drama()), dialogue="分镜对白文本", narration="分镜旁白文本")
    r = client.post(EXTRACT, json={"storyboard_id": sb})
    assert r.status_code == 200
    assert _stub_tts[0]["text"] == "分镜对白文本"


def test_extract_falls_back_to_storyboard_narration(client: TestClient, _stub_tts):
    _seed_tts_config()
    sb = _seed_storyboard(_seed_episode(_seed_drama()), dialogue="分镜对白文本", narration="分镜旁白文本")
    r = client.post(EXTRACT, json={"storyboard_id": sb, "tts_kind": "narration"})
    assert r.status_code == 200
    assert _stub_tts[0]["text"] == "分镜旁白文本"


def test_extract_inline_text_wins_over_storyboard(client: TestClient, _stub_tts):
    """body.text 非空时不查库。"""
    _seed_tts_config()
    sb = _seed_storyboard(_seed_episode(_seed_drama()), dialogue="库里的对白")
    r = client.post(EXTRACT, json={"storyboard_id": sb, "text": "传入的文本"})
    assert _stub_tts[0]["text"] == "传入的文本"


def test_extract_writes_audio_local_path_for_dialogue(client: TestClient, _stub_tts):
    _seed_tts_config()
    sb = _seed_storyboard(_seed_episode(_seed_drama()), dialogue="对白")
    local_path = client.post(EXTRACT, json={"storyboard_id": sb}).json()["data"]["local_path"]
    with dbm.engine.begin() as conn:
        row = conn.execute(
            text("SELECT audio_local_path, narration_audio_local_path FROM storyboards WHERE id = :id"),
            {"id": sb},
        ).mappings().one()
    assert row["audio_local_path"] == local_path
    assert row["narration_audio_local_path"] is None


def test_extract_writes_narration_column_for_narration(client: TestClient, _stub_tts):
    _seed_tts_config()
    sb = _seed_storyboard(_seed_episode(_seed_drama()), dialogue="对白", narration="旁白")
    local_path = client.post(EXTRACT, json={"storyboard_id": sb, "tts_kind": "narration"}).json()["data"][
        "local_path"
    ]
    with dbm.engine.begin() as conn:
        row = conn.execute(
            text("SELECT audio_local_path, narration_audio_local_path FROM storyboards WHERE id = :id"),
            {"id": sb},
        ).mappings().one()
    assert row["narration_audio_local_path"] == local_path
    assert row["audio_local_path"] is None


# ---------------- 批量 ----------------


def test_batch_success(client: TestClient, _stub_tts):
    _seed_tts_config()
    ep = _seed_episode(_seed_drama())
    sb1 = _seed_storyboard(ep, dialogue="对白一")
    sb2 = _seed_storyboard(ep, dialogue="对白二")
    r = client.post(BATCH, json={"storyboard_ids": [sb1, sb2]})
    assert r.status_code == 200
    results = r.json()["data"]
    assert len(results) == 2
    assert all("local_path" in x for x in results)
    assert [x["storyboard_id"] for x in results] == [sb1, sb2]
    assert [x["text"] for x in _stub_tts] == ["对白一", "对白二"]


def test_batch_empty_dialogue_is_reported_per_item(client: TestClient, _stub_tts):
    _seed_tts_config()
    ep = _seed_episode(_seed_drama())
    sb_blank = _seed_storyboard(ep, dialogue="   ")
    sb_ok = _seed_storyboard(ep, dialogue="正常对白")
    r = client.post(BATCH, json={"storyboard_ids": [sb_blank, sb_ok]})
    results = r.json()["data"]
    assert results[0] == {"storyboard_id": sb_blank, "error": "对白为空"}
    assert "local_path" in results[1]  # 前一条失败不中断后续


def test_batch_unknown_id_reported_as_empty(client: TestClient, _stub_tts):
    _seed_tts_config()
    r = client.post(BATCH, json={"storyboard_ids": [999999]})
    assert r.json()["data"] == [{"storyboard_id": 999999, "error": "对白为空"}]


def test_batch_ignores_tts_kind_and_uses_dialogue(client: TestClient, _stub_tts):
    """批量接口无 tts_kind 参数，恒取 dialogue。"""
    _seed_tts_config()
    sb = _seed_storyboard(_seed_episode(_seed_drama()), dialogue="对白", narration="旁白")
    client.post(BATCH, json={"storyboard_ids": [sb], "tts_kind": "narration"})
    assert _stub_tts[0]["text"] == "对白"


def test_batch_synthesis_error_isolated_per_item(client: TestClient, monkeypatch, _stub_tts):
    """单条合成抛错 → 该项 error，其余继续。"""
    _seed_tts_config()
    ep = _seed_episode(_seed_drama())
    sb1 = _seed_storyboard(ep, dialogue="触发失败")
    sb2 = _seed_storyboard(ep, dialogue="正常")

    def failing(text, voice, api_key, base_url, model, speed):
        if text == "触发失败":
            raise ValueError("上游炸了")
        return FAKE_AUDIO

    monkeypatch.setattr(ttsService, "synthesize_with_openai", failing)
    results = client.post(BATCH, json={"storyboard_ids": [sb1, sb2]}).json()["data"]
    assert results[0] == {"storyboard_id": sb1, "error": "上游炸了"}
    assert "local_path" in results[1]


# ---------------- provider 选择 ----------------


def test_minimax_provider_selected(client: TestClient, _stub_tts):
    _seed_tts_config(provider="minimax", default_model="speech-02-hd",
                     settings='{"voice_id":"male-qn-qingse","group_id":"grp-1"}')
    r = client.post(EXTRACT, json={"text": "MiniMax 文本"})
    assert r.status_code == 200
    assert _stub_tts[0]["provider"] == "minimax"
    assert _stub_tts[0]["voice_id"] == "male-qn-qingse"
    assert _stub_tts[0]["group_id"] == "grp-1"
    assert _stub_tts[0]["model"] == "speech-02-hd"


def test_unsupported_provider_returns_500(client: TestClient, _stub_tts):
    _seed_tts_config(provider="unknown_tts", base_url="")
    r = client.post(EXTRACT, json={"text": "x"})
    assert r.status_code == 500
    assert "不支持的 TTS provider" in r.json()["error"]["message"]


def test_provider_with_base_url_uses_openai_path(client: TestClient, _stub_tts):
    """无 provider 但有 base_url → 走 OpenAI 兼容路径。"""
    _seed_tts_config(provider="custom", base_url="https://tts.example.com/v1")
    r = client.post(EXTRACT, json={"text": "x"})
    assert r.status_code == 200
    assert _stub_tts[0]["provider"] == "openai"
    assert _stub_tts[0]["base_url"] == "https://tts.example.com/v1"


def test_inactive_tts_config_ignored(client: TestClient, _stub_tts):
    """is_active=0 的配置不参与选择。"""
    with dbm.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ai_service_configs (service_type, provider, api_protocol, name, base_url, "
                "api_key, model, default_model, priority, is_default, is_active, created_at, updated_at) "
                "VALUES ('tts','openai','','TTS','','sk','[\"tts-1\"]','tts-1',0,1,0,"
                "'2026-01-01T00:00:00.000Z','2026-01-01T00:00:00.000Z')"
            )
        )
    r = client.post(EXTRACT, json={"text": "x"})
    assert r.status_code == 500
    assert "未配置 TTS 模型" in r.json()["error"]["message"]


# ---------------- 真实字节解析（不走 stub）----------------


def test_minimax_hex_payload_parsed(client: TestClient, monkeypatch, _tmp_storage):
    """验证 MiniMax 响应解析：hex → bytes，且 base_resp.status_code != 0 时报错。"""
    import httpx

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return MINIMAX_PAYLOAD

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    _seed_tts_config(provider="minimax")
    r = client.post(EXTRACT, json={"text": "hex 解析"})
    assert r.status_code == 200
    local_path = r.json()["data"]["local_path"]
    assert (Path(_tmp_storage) / local_path).read_bytes() == FAKE_AUDIO


def test_minimax_business_error_surfaces(client: TestClient, monkeypatch):
    import httpx

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"base_resp": {"status_code": 2013, "status_msg": "insufficient balance"}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    _seed_tts_config(provider="minimax")
    r = client.post(EXTRACT, json={"text": "x"})
    assert r.status_code == 500
    assert "insufficient balance" in r.json()["error"]["message"]
