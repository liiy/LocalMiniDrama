from __future__ import annotations

from fastapi.testclient import TestClient

from app.services import generationService, framePromptService


def test_generate_story_parses_ai_json(monkeypatch):
    def fake_generate_text(db, log, service_type, user_prompt, system_prompt, options=None):
        assert "故事梗概" in user_prompt
        assert "第 1 集" not in system_prompt
        return '[{"episode":1,"title":"第一集","content":"第一集正文"}]'

    monkeypatch.setattr("app.services.aiClient.generate_text", fake_generate_text)

    result = generationService.generate_story(None, None, {"premise": "一个被误会的少年"})
    assert result["episodes"][0]["episode"] == 1
    assert result["episodes"][0]["content"] == "第一集正文"


def test_regenerate_layout_description_route(client: TestClient, monkeypatch):
    d = client.post("/api/v1/dramas", json={"title": "AI-布局测试"}).json()["data"]
    client.put(
        f"/api/v1/dramas/{d['id']}/episodes",
        json={"episodes": [{"episode_number": 1, "title": "第一集"}]},
    )
    e = client.get(f"/api/v1/dramas/{d['id']}").json()["data"]["episodes"][0]
    sb = client.post(
        "/api/v1/storyboards",
        json={
            "episode_id": e["id"],
            "storyboard_number": 1,
            "action": "他走向桌前",
            "result": "门轻轻合上",
            "dialogue": "他：我回来了",
        },
    ).json()["data"]

    def fake_generate_text(db, log, service_type, user_prompt, system_prompt, options=None):
        assert "CURRENT_SHOT" in user_prompt
        return "```\n布局描述：画面左侧，桌案位于右下 45cm，人物站在中间，面向门，允许轻微推近。\n```"

    monkeypatch.setattr("app.services.aiClient.generate_text", fake_generate_text)

    r = client.post(f"/api/v1/storyboards/{sb['id']}/regenerate-layout-description")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["layout_description"].startswith("画面左侧")

    row = client.get(f"/api/v1/storyboards/{sb['id']}").json()["data"]
    assert row["layout_description"].startswith("画面左侧")
