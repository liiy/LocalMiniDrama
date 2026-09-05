"""Phase 7: 可观测性与质量评估系统 (迭代 8) 单元测试。

验证质量报告创建与状态更新、Token 消耗统计、可观测性健康指标与 Platform Observability API。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.platform import router as platform_router
from app.db.session import get_db
from app.prompts import registry_service as prompt_registry
from app.quality import report_service as quality_report_service
from app.skills import bootstrap_service
from app.workflows import run_service as workflow_service


def test_quality_evaluation_and_observability(db_session):
    """测试质量报告创建、状态流转与可观测性统计指标。"""
    bootstrap_service.bootstrap_defaults(db_session)

    # 1. 记录几次 Prompt Run (模拟 Token 消耗和延迟)
    prompt_registry.record_prompt_run(
        db_session,
        {
            "prompt_key": "storyboard_director.storyboard_generation",
            "model_name": "deepseek-chat",
            "prompt_text": "生成分镜脚本...",
            "response_text": '{"storyboards": []}',
            "prompt_tokens": 500,
            "completion_tokens": 300,
            "total_tokens": 800,
            "latency_ms": 1250,
            "status": "success",
        },
    )

    # 2. 创建质量评估报告
    report = quality_report_service.create_quality_report(
        db_session,
        {
            "report_type": "script_coherence",
            "score": 92.5,
            "status": "passed",
            "issues": ["第3分镜人物反转略突兀"],
            "suggestions": ["在第2分镜增加伏笔台词"],
            "raw_report": {"pacing": 90, "coherence": 95},
        },
    )
    assert report["id"] is not None
    assert report["score"] == 92.5
    assert len(report["issues"]) == 1

    # 3. 统计可观测性指标
    metrics = quality_report_service.get_observability_metrics(db_session)
    assert metrics["prompts"]["total_calls"] >= 1
    assert metrics["prompts"]["total_tokens"] >= 800
    assert metrics["quality"]["total_reports"] >= 1
    assert metrics["quality"]["avg_score"] >= 90.0


def test_observability_platform_endpoints(db_session):
    """测试 Platform 可观测性与 QA 报告 API。"""
    bootstrap_service.bootstrap_defaults(db_session)

    app = FastAPI()
    app.include_router(platform_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    # 1. POST /platform/quality-reports 创建质检报告
    res = client.post(
        "/api/v1/platform/quality-reports",
        json={
            "report_type": "continuity_review",
            "score": 88.0,
            "status": "needs_review",
            "issues": ["主角道具玉佩前置丢失"],
        },
    )
    assert res.status_code == 200
    rep_id = res.json()["data"]["id"]

    # 2. PATCH /platform/quality-reports/{id} 更新状态
    res_patch = client.patch(
        f"/api/v1/platform/quality-reports/{rep_id}",
        json={"status": "resolved", "suggestions": ["已在道具库补充玉佩设定"]},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["data"]["status"] == "resolved"

    # 3. GET /platform/observability/metrics 获取系统看板
    res_m = client.get("/api/v1/platform/observability/metrics")
    assert res_m.status_code == 200
    m_data = res_m.json()["data"]
    assert "prompts" in m_data
    assert "quality" in m_data
    assert "workflows" in m_data
