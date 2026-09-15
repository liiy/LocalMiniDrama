"""Step 10 单元测试：两程九阶 FastAPI 路由与 SSE 实时事件总线集成验证。"""
import json
from unittest.mock import patch
from sqlalchemy import text

from app.core.event_bus import EventBus
from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    StoryboardShot,
)
from app.workflows.adapters.drama_storage_adapter import DramaStorageAdapter


def test_two_journey_api_endpoints(unit_client, db_session):
    """验证 Step 10 新增的两程九阶 API 端点交互。"""
    # 1. 准备测试短剧
    db_session.execute(
        text(
            "INSERT INTO dramas (id, title, description, genre, total_episodes, lock_status, pipeline_status) "
            "VALUES (101, '九霄龙吟', '战神赘婿逆袭', '都市战神', 12, 0, 'idle')"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO episodes (id, drama_id, episode_number, title, duration) "
            "VALUES (1001, 101, 1, '第1集 龙神归来', 120)"
        )
    )
    db_session.commit()

    # 2. 启动两程九阶 pipeline
    with patch("app.api.v1.script_studio.run_two_journey_pipeline_async") as mock_run:
        resp = unit_client.post(
            "/api/v1/script-studio/dramas/101/two-journey/start",
            json={
                "user_prompt": "隐形富豪归来守护爱妻",
                "genre": "都市",
                "total_episodes": 12,
                "target_duration_sec": 120.0,
                "visual_style": "真人电影/超写实",
                "aspect_ratio": "9:16",
                "auto_proceed_to_visual": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["status"] == "started"
        assert data["data"]["total_episodes"] == 12

    # 3. 获取状态 GET /two-journey/state
    resp_state = unit_client.get("/api/v1/script-studio/dramas/101/two-journey/state")
    assert resp_state.status_code == 200, resp_state.text
    state_data = resp_state.json()
    assert state_data["success"] is True
    assert state_data["data"]["drama_id"] == 101

    # 4. 测试定稿锁定 POST /two-journey/lock-literary
    resp_lock = unit_client.post("/api/v1/script-studio/dramas/101/two-journey/lock-literary")
    assert resp_lock.status_code == 200
    lock_data = resp_lock.json()
    assert lock_data["success"] is True
    assert lock_data["data"]["lock_status"] == 1
    assert lock_data["data"]["literary_journey_locked"] is True

    # 5. 模拟存入分镜视听工程包并查询 GET /episodes/1/visual-package
    manifest = EpisodeResourceManifest(
        approved_character_ids=[1, 2],
        approved_scene_ids=[1],
        approved_prop_ids=[1],
    )
    shot = StoryboardShot(
        shot_id=1,
        timecode="00:00:00,000 --> 00:00:03,000",
        duration_sec=3.0,
        framing="CU 特写",
        camera_motion="Dolly In",
        generation_mode="first_last_frame",
        selection_rationale="动作冲击强",
        first_last_config={"first_frame_prompt": "主角冷峻特写", "video_motion_prompt": "镜头向前推"},
        audio={"dialogue": "谁敢动她！", "narration": ""},
        lipsync_dynamics={"viseme": "AA", "jaw_open": 0.8},
    )
    DramaStorageAdapter.persist_episode_visual_package(
        db_session,
        drama_id=101,
        episode_num=1,
        manifest=manifest,
        storyboards=[shot],
        srt_export="1\n00:00:00,000 --> 00:00:03,000\n谁敢动她！\n",
        audio_mastering={"total_duration_sec": 3.0, "ducking_events": []},
    )
    db_session.commit()

    resp_pkg = unit_client.get("/api/v1/script-studio/dramas/101/episodes/1/visual-package")
    assert resp_pkg.status_code == 200
    pkg_data = resp_pkg.json()
    assert pkg_data["success"] is True
    assert pkg_data["data"]["episode_number"] == 1
    assert len(pkg_data["data"]["storyboards"]) == 1
    assert pkg_data["data"]["storyboards"][0]["framing"] == "CU 特写"
    assert "谁敢动她" in pkg_data["data"]["srt_export"]

    # 6. 测试门禁确认唤醒 POST /two-journey/gate-confirm
    with patch("app.api.v1.script_studio.resume_two_journey_pipeline_async") as mock_resume:
        resp_gate = unit_client.post(
            "/api/v1/script-studio/dramas/101/two-journey/gate-confirm",
            json={"approved": True, "feedback": "第一程文学剧本很棒，准予制作！"},
        )
        assert resp_gate.status_code == 200
        gate_data = resp_gate.json()
        assert gate_data["success"] is True
        assert gate_data["data"]["status"] == "resumed"


def test_two_journey_sse_event_types():
    """验证 Step 10 新增的 6 类 SSE 工业事件可以通过 EventBus 广播与序列化。"""
    drama_id = 8888
    events_to_test = [
        ("STAGE_PROGRESS", {"stage": 1, "stage_name": "题材立项", "progress_pct": 10}),
        ("RED_BLUE_AUDIT", {"stage": 2, "verdict": "BLUE_PASS", "blue_checks": ["合规"], "red_complaints": []}),
        ("MINI_ARC_COMPLETED", {"stage": 5, "completed_count": 3, "total_episodes": 12}),
        ("FIRST_JOURNEY_LOCKED", {"stage": 5, "status": "locked"}),
        ("EPISODE_VISUAL_STARTED", {"stage": 6, "episode_num": 1}),
        ("EPISODE_VISUAL_COMPLETED", {"stage": 8, "episode_num": 1, "storyboard_count": 5}),
    ]

    for ev_type, data in events_to_test:
        EventBus.publish_event(drama_id, ev_type, data)
        formatted = EventBus.format_sse_message({"event": ev_type, "data": data})
        assert formatted.startswith(f"event: {ev_type}\n")
        assert formatted.endswith("\n\n")
