"""契约安全网：/api/v1/tasks/* 与 Node 版 backend-node/src/routes/task.js 行为等价。

Node 行为基线：
- GET  /tasks/{task_id}         → 404 '任务不存在' | rowToTask(...)
- POST /tasks/{task_id}/cancel  → 404 | 已 completed/failed 时原样返回（不报错）
                                  待处理任务 → status='failed' + error=原因
- GET  /tasks?resource_id=      → 400 '缺少resource_id参数' | 按 created_at DESC

任务记录通过 taskService.create_task 直接写入（Node 侧同样无创建端点）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import session as dbm
from app.services import taskService as svc

BASE = "/api/v1/tasks"


def _make_task(resource_id: str = "drama:1", task_type: str = "test_task") -> dict:
    """用真实服务创建任务，返回 rowToTask 后的结构。"""
    from app.core.logger import get_logger

    log = get_logger("lmd.tasks.test")
    with dbm.SessionLocal() as db:
        task = svc.create_task(db, log, task_type, resource_id)
        db.commit()
        return task


# ---------------- GET /tasks/{task_id} ----------------


def test_get_task_not_found(client: TestClient):
    r = client.get(f"{BASE}/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"] == {"code": "NOT_FOUND", "message": "任务不存在"}


def test_get_task_returns_full_row(client: TestClient):
    task = _make_task()
    r = client.get(f"{BASE}/{task['id']}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["id"] == task["id"]
    assert data["type"] == "test_task"
    assert data["status"] == "pending"
    assert data["progress"] == 0
    assert data["resource_id"] == "drama:1"
    # rowToTask 固定字段集（顺序无关）
    assert set(data) == {
        "id",
        "type",
        "status",
        "progress",
        "message",
        "error",
        "result",
        "resource_id",
        "created_at",
        "updated_at",
        "completed_at",
    }


def test_created_task_defaults(client: TestClient):
    """create_task 插入 status='pending'、progress=0、message=''。"""
    task = _make_task()
    data = client.get(f"{BASE}/{task['id']}").json()["data"]
    assert data["message"] == ""
    assert data["error"] is None
    assert data["result"] is None
    assert data["completed_at"] is None


# ---------------- GET /tasks?resource_id= ----------------


def test_get_tasks_missing_resource_id(client: TestClient):
    r = client.get(BASE)
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "BAD_REQUEST", "message": "缺少resource_id参数"}


def test_get_tasks_empty_resource_id(client: TestClient):
    """Node 用 !resourceId 判定，空串同样 400。"""
    r = client.get(BASE, params={"resource_id": ""})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "缺少resource_id参数"


def test_get_tasks_by_resource(client: TestClient):
    _make_task(resource_id="drama:A")
    _make_task(resource_id="drama:A")
    _make_task(resource_id="drama:B")
    r = client.get(BASE, params={"resource_id": "drama:A"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    assert all(t["resource_id"] == "drama:A" for t in data)


def test_get_tasks_unknown_resource_returns_empty(client: TestClient):
    r = client.get(BASE, params={"resource_id": "nope"})
    assert r.status_code == 200
    assert r.json()["data"] == []


# ---------------- POST /tasks/{task_id}/cancel ----------------


def test_cancel_missing_task(client: TestClient):
    r = client.post(f"{BASE}/does-not-exist/cancel", json={})
    assert r.status_code == 404
    assert r.json()["error"] == {"code": "NOT_FOUND", "message": "任务不存在"}


def test_cancel_pending_task_marks_failed(client: TestClient):
    task = _make_task()
    r = client.post(f"{BASE}/{task['id']}/cancel", json={})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == svc.USER_CANCEL_TASK_MSG
    assert data["progress"] == 0
    assert data["completed_at"] is not None


def test_cancel_with_custom_reason(client: TestClient):
    task = _make_task()
    r = client.post(f"{BASE}/{task['id']}/cancel", json={"reason": "  不要了  "})
    assert r.json()["data"]["error"] == "不要了"  # Node 会 trim


def test_cancel_with_blank_reason_falls_back(client: TestClient):
    task = _make_task()
    r = client.post(f"{BASE}/{task['id']}/cancel", json={"reason": "   "})
    assert r.json()["data"]["error"] == svc.USER_CANCEL_TASK_MSG


def test_cancel_already_completed_is_idempotent(client: TestClient):
    """已 completed/failed 的任务 cancel 不报错，原样返回且不再改写。"""
    task = _make_task()
    with dbm.SessionLocal() as db:
        svc.update_task_result(db, task["id"], {"ok": True})
        db.commit()
    completed = client.get(f"{BASE}/{task['id']}").json()["data"]
    assert completed["status"] == "completed"

    r = client.post(f"{BASE}/{task['id']}/cancel", json={})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "completed"  # 未被改成 failed
    assert data["progress"] == 100
    assert data["completed_at"] == completed["completed_at"]


def test_cancel_failed_task_keeps_original_error(client: TestClient):
    task = _make_task()
    with dbm.SessionLocal() as db:
        svc.update_task_error(db, task["id"], "原始错误")
        db.commit()
    r = client.post(f"{BASE}/{task['id']}/cancel", json={})
    assert r.status_code == 200
    assert r.json()["data"]["error"] == "原始错误"  # 未被覆盖为用户已取消


# ---------------- 软删除 ----------------


def test_soft_deleted_task_is_hidden(client: TestClient):
    """Node 所有查询都带 deleted_at IS NULL。"""
    task = _make_task()
    with dbm.engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("UPDATE async_tasks SET deleted_at = '2026-01-01T00:00:00.000Z' WHERE id = :id"), {"id": task["id"]})
    assert client.get(f"{BASE}/{task['id']}").status_code == 404
    assert client.get(BASE, params={"resource_id": "drama:1"}).json()["data"] == []
    assert client.post(f"{BASE}/{task['id']}/cancel", json={}).status_code == 404
