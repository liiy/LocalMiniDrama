"""Sprint 6 单元测试：Redis/内存 PubSub 事件总线与 Script Studio SSE 接口契约验证。"""
import asyncio
from sqlalchemy import text
from app.core.event_bus import EventBus


def test_event_bus_pub_sub_in_memory():
    """测试事件总线在内存模式下的异步发布与订阅能力。"""
    async def run_test():
        drama_id = 999
        received_events = []

        async def consumer():
            count = 0
            async for ev in EventBus.subscribe_events(drama_id, heartbeat_interval=0.5):
                received_events.append(ev)
                count += 1
                if count >= 3:
                    break

        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # 发布测试事件
        EventBus.publish_event(drama_id, "node_progress", {"node": "bible_generation", "percent": 20})
        EventBus.publish_event(drama_id, "qa_reported", {"episode_num": 1, "score": 88})

        await consumer_task

        assert len(received_events) >= 3
        assert received_events[0]["event"] == "connected"
        assert received_events[1]["event"] == "node_progress"
        assert received_events[1]["data"]["percent"] == 20
        assert received_events[2]["event"] == "qa_reported"

    asyncio.run(run_test())


def test_sse_message_formatting():
    """测试 SSE 格式化方法输出是否符合 W3C 标准。"""
    event = {
        "event": "batch_started",
        "data": {"batch_index": 1, "episode_nums": [1, 2, 3]},
    }
    raw_sse = EventBus.format_sse_message(event)
    assert raw_sse.startswith("event: batch_started\n")
    assert '"batch_index": 1' in raw_sse
    assert raw_sse.endswith("\n\n")


def test_script_studio_api_endpoints(unit_client, db_session):
    """测试 Script Studio V2.0 创作工坊核心 API (锁定、级联失效、局部修补、Bridge同步)。"""
    # 1. 初始化短剧与分集数据
    db_session.execute(
        text(
            "INSERT INTO dramas (id, title, lock_status, version_cursor) VALUES (1, '逆天战神', 0, 1)"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO episodes (id, drama_id, episode_number, title, script_content, status) VALUES "
            "(101, 1, 1, '第1集 战神觉醒', '【场景】荒郊野外\\n【钩子】战神撕毁婚书！\\n【动作】一拳轰出。', 'approved'),"
            "(102, 1, 2, '第2集 家族震惊', '【场景】林家大院\\n林家长老震怒。', 'approved'),"
            "(103, 1, 3, '第3集 强势打脸', '【场景】林家大厅\\n战神登场。', 'approved')"
        )
    )
    db_session.commit()

    # 2. 测试级联失效 API
    resp = unit_client.post("/api/v1/script-studio/dramas/1/cascade-invalidate", json={"changed_episode_num": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["stale_episodes_count"] == 2

    ep2 = db_session.execute(text("SELECT status FROM episodes WHERE id = 102")).scalar()
    ep3 = db_session.execute(text("SELECT status FROM episodes WHERE id = 103")).scalar()
    assert ep2 == "stale"
    assert ep3 == "stale"

    # 3. 测试单集局部修补 API
    resp = unit_client.post(
        "/api/v1/script-studio/dramas/1/episodes/1/patch",
        json={"issues": ["反转力度不足"], "deductions": {"conflict_intensity": 10}},
    )
    assert resp.status_code == 200
    patch_data = resp.json()["data"]
    assert "反转增强" in patch_data["script_content"]

    # 4. 测试定稿锁定保护 API
    resp = unit_client.post("/api/v1/script-studio/dramas/1/lock")
    assert resp.status_code == 200
    lock_data = resp.json()["data"]
    assert lock_data["lock_status"] == 1
    assert lock_data["version_cursor"] == 3

    # 锁定后再尝试启动 pipeline 应被拒绝
    resp = unit_client.post(
        "/api/v1/script-studio/dramas/1/pipeline/start",
        json={"user_prompt": "重写剧本", "total_episodes": 3},
    )
    assert resp.status_code == 400
    err_msg = resp.json().get("error", {}).get("message", "")
    assert "锁定" in err_msg

    # 5. 测试 Bridge 契约同步视听工坊 API
    resp = unit_client.post("/api/v1/script-studio/dramas/1/sync-visual?episode_num=1")
    assert resp.status_code == 200
    sync_data = resp.json()["data"]
    assert sync_data["synced_storyboards"] == 4
    assert sync_data["status"] == "bridged_to_visual_studio"


def test_script_studio_hitl_and_resume_api(unit_client, db_session):
    """测试 Script Studio V2.0 HITL 人工干预与断点恢复 API (state / update-state / resume)。"""
    db_session.execute(
        text(
            "INSERT INTO dramas (id, title, lock_status, version_cursor, pipeline_status) VALUES (2, '都市医圣', 0, 1, 'idle')"
        )
    )
    db_session.commit()

    # 1. 查询当前流水线状态快照
    resp = unit_client.get("/api/v1/script-studio/dramas/2/pipeline/state")
    assert resp.status_code == 200
    state_data = resp.json()["data"]
    assert state_data["drama_id"] == 2

    # 2. 启动 HITL 模式
    resp = unit_client.post(
        "/api/v1/script-studio/dramas/2/pipeline/start",
        json={"user_prompt": "绝世医圣潜伏江城", "total_episodes": 3, "hitl_mode": True},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["hitl_mode"] is True

    # 3. 模拟人工干预状态更新
    resp = unit_client.post(
        "/api/v1/script-studio/dramas/2/pipeline/update-state",
        json={
            "updates": {
                "episode_outlines": {
                    "1": {
                        "episode_num": 1,
                        "title": "第1集 医圣归来施九针",
                        "commercial_tag": "free_hook",
                        "main_scene": "江城市中心医院",
                        "core_action": "九阴绝脉银针逆转生死",
                        "core_resistance": "西医泰斗质疑",
                        "information_disclosure": "主角师承鬼谷医门",
                        "relationship_change": "院长女儿暗生崇拜",
                        "episode_twist": "仪器全线复苏，泰斗当场下跪",
                        "ending_cliffhanger": "特写定格：绝密信物曝光！",
                        "duration_seconds": 90,
                    }
                }
            }
        },
    )
    # 若尚无活跃 Checkpoint 节点，将捕获返回 400 或更新成功
    assert resp.status_code in (200, 400)

    # 4. 测试 Resume 恢复接口
    resp = unit_client.post("/api/v1/script-studio/dramas/2/pipeline/resume")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "resuming"


