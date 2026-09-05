"""针对迭代 6、7、8 完整功能与端到端链路的自动化单元测试。

覆盖范畴：
1. 迭代 6：Provider Protocol 统一协议与注册中心、资产版本树与级联失效 (Stale Cascade)。
2. 迭代 7：Music Provider 适配层、智能响度归一化 (EBU R128) 与 Audio Ducking 侧链压制。
3. 迭代 8：OpenTelemetry 追踪中间件、Prometheus /metrics 端点、Langfuse Tracker、Golden Dataset 自动化回归评估套件。
"""
from __future__ import annotations

import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.providers import (
    get_image_provider,
    get_video_provider,
    get_music_provider,
    ImageGenerationOptions,
    VideoGenerationOptions,
    MusicGenerationOptions,
    BaseImageProvider,
    BaseVideoProvider,
    BaseMusicProvider,
)
from app.services import cascadeService
from app.services.loudnessService import normalize_audio_loudness, mix_multitrack_with_ducking
from app.core.telemetry import trace_span, metrics, LangfuseTracker
from app.quality.golden_eval import GoldenDatasetEvaluator, GoldenTestCase, run_golden_eval_pipeline
from app.platform_common import now_iso, json_dumps


# ── 1. 迭代 6 测试：Provider 协议与 Stale Cascade 级联失效 ──────────────────────

def test_provider_protocol_and_registry():
    """测试统一 Provider Protocol 注册中心与各厂商适配器接口。"""
    img_prov = get_image_provider("volcengine")
    assert isinstance(img_prov, BaseImageProvider)
    assert img_prov.provider_name == "volcengine"

    vid_prov = get_video_provider("kling")
    assert isinstance(vid_prov, BaseVideoProvider)
    assert vid_prov.provider_name == "kling"

    music_suno = get_music_provider("suno")
    assert isinstance(music_suno, BaseMusicProvider)
    assert music_suno.provider_name == "suno"

    # 测试 Mock 生成
    music_res = music_suno.generate_music({}, None, MusicGenerationOptions(prompt="dramatic battle", style="cinematic"))
    assert music_res.audio_url is not None
    assert music_res.duration_seconds > 0


def test_stale_cascade_on_character_and_scene_update(db_session):
    """测试当角色或场景修改时，下游关联分镜打上 stale 标记并支持重跑。"""
    now = now_iso()
    res = db_session.execute(
        text("INSERT INTO dramas (title, status, created_at, updated_at) VALUES ('Cascade Drama', 'active', :now, :now)"),
        {"now": now},
    )
    drama_id = res.lastrowid

    res = db_session.execute(
        text("INSERT INTO episodes (drama_id, episode_number, title, created_at, updated_at) VALUES (:d_id, 1, '第1集', :now, :now)"),
        {"d_id": drama_id, "now": now},
    )
    episode_id = res.lastrowid

    res = db_session.execute(
        text("INSERT INTO characters (drama_id, name, description, created_at, updated_at) VALUES (:d_id, '主角李明', '帅气剑客', :now, :now)"),
        {"d_id": drama_id, "now": now},
    )
    char_id = res.lastrowid

    res = db_session.execute(
        text("INSERT INTO scenes (drama_id, location, time, created_at, updated_at) VALUES (:d_id, '青云峰大殿', '白天', :now, :now)"),
        {"d_id": drama_id, "now": now},
    )
    scene_id = res.lastrowid

    # 插入分镜 1（关联角色与场景）与 分镜 2
    res = db_session.execute(
        text(
            """
            INSERT INTO storyboards (episode_id, scene_id, storyboard_number, characters, location, status, created_at, updated_at)
            VALUES (:ep_id, :sc_id, 1, :chars, '青云峰大殿', 'completed', :now, :now)
            """
        ),
        {
            "ep_id": episode_id,
            "sc_id": scene_id,
            "chars": json_dumps(["主角李明"]),
            "now": now,
        },
    )
    sb1_id = res.lastrowid

    res = db_session.execute(
        text(
            """
            INSERT INTO storyboards (episode_id, storyboard_number, characters, location, status, created_at, updated_at)
            VALUES (:ep_id, 2, :chars, '另一场景', 'completed', :now, :now)
            """
        ),
        {
            "ep_id": episode_id,
            "chars": json_dumps(["路人甲"]),
            "now": now,
        },
    )
    sb2_id = res.lastrowid
    db_session.commit()

    # 1. 修改角色外貌，触发级联失效
    marked = cascadeService.mark_storyboards_stale_for_character(db_session, char_id, reason="character_appearance_drift")
    assert marked["affected_storyboards"] >= 1

    row1 = db_session.execute(text("SELECT status FROM storyboards WHERE id = :id"), {"id": sb1_id}).mappings().one()
    row2 = db_session.execute(text("SELECT status FROM storyboards WHERE id = :id"), {"id": sb2_id}).mappings().one()
    assert row1["status"] == "stale"
    assert row2["status"] == "completed"

    # 2. 查询失效资产汇总
    summary = cascadeService.get_stale_assets_summary(db_session, drama_id)
    assert summary["stale_count"] >= 1

    # 3. 执行一键增量重跑
    rerun_res = cascadeService.rerun_stale_assets(db_session, drama_id)
    assert rerun_res["requeued_count"] >= 1

    row1_after = db_session.execute(text("SELECT status FROM storyboards WHERE id = :id"), {"id": sb1_id}).mappings().one()
    assert row1_after["status"] == "pending"



# ── 2. 迭代 7 测试：音频设计、智能响度与多轨 Ducking 混音 ───────────────────────

def test_loudness_normalization_and_ducking():
    """测试智能响度调平与音频混合服务。"""
    # 针对不存在的文件，安全返回 False 而不崩溃
    res_norm = normalize_audio_loudness("non_existent.wav", "dummy_out.wav", target_lufs=-16.0)
    assert res_norm is False

    res_mix = mix_multitrack_with_ducking(
        voice_audio_path=None,
        bgm_audio_path=None,
        sfx_audio_path=None,
        output_path="mixed_final.wav",
        target_duration=10.0,
        ducking_attenuation_db=-12.0,
    )
    assert res_mix is False


# ── 3. 迭代 8 测试：可观测性 (OTel/Prometheus/Langfuse) 与 Golden Dataset ────────

def test_telemetry_span_and_metrics():
    """测试 OpenTelemetry TraceSpan 上下文管理器与 Prometheus 指标生成。"""
    with trace_span("test_agent_step", {"agent": "ScriptAgent"}) as span:
        span.set_attribute("tokens", 150)
        assert span.status == "OK"

    # 记录 HTTP 请求和 Token
    metrics.inc_request("POST", "/api/v1/platform/workflows", 200)
    metrics.observe_latency("/api/v1/platform/workflows", 0.125)
    metrics.inc_ai_tokens("gpt-4o", "prompt", 200)
    metrics.inc_ai_tokens("gpt-4o", "completion", 500)

    prom_text = metrics.generate_prometheus_text()
    assert "http_requests_total" in prom_text
    assert "ai_tokens_consumed_total" in prom_text
    assert "http_request_duration_seconds" in prom_text


def test_langfuse_tracker_mock():
    """测试 Langfuse Tracker 实时调用追踪与度量记录。"""
    tracker = LangfuseTracker()
    tracker.track_generation(
        name="StoryboardGen",
        model="claude-3-7-sonnet",
        prompt="生成第1集分镜",
        output="分镜列表...",
        usage={"prompt_tokens": 100, "completion_tokens": 300},
    )


def test_golden_dataset_evaluator_pipeline():
    """测试 Golden Dataset 自动化质量基准测试流水线。"""
    evaluator = GoldenDatasetEvaluator()
    tc = GoldenTestCase(
        id="TC-UNIT-01",
        category="storyboard_prompt",
        input_text="雨夜决战，剑客李明挥剑斩向魔尊。",
        expected_entities=["李明", "魔尊"],
        required_keywords=["雨夜", "决战", "挥剑"],
    )
    
    # 模拟高质量生成输出
    good_output = "【分镜设计】在暴雨倾盆的雨夜决战中，剑客李明怒目圆睁，挥剑斩向魔尊，剑气撕裂夜空。"
    score = evaluator.evaluate_output(tc, good_output)
    assert score.passed is True
    assert score.entity_retention_score == 1.0
    assert score.keyword_coverage_score == 1.0
    assert score.overall_score >= 0.70

    # 运行内置完整流水线
    pipeline_result = run_golden_eval_pipeline()
    assert pipeline_result["summary"]["total_cases"] >= 4
    assert pipeline_result["summary"]["pass_rate"] >= 50.0
