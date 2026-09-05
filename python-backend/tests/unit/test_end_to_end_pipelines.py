from __future__ import annotations

from unittest.mock import patch

from app.db.session import fetch_all, fetch_one
from app.skills import bootstrap_service
from app.workflows import executor, run_service


def test_original_script_end_to_end_pipeline(db_session):
    """测试原创剧本端到端流水线创建与全自动步进。"""
    bootstrap_service.bootstrap_defaults(db_session)

    # 1. 创建原创短剧工作流
    run = run_service.create_original_script_workflow(
        db_session,
        user_request="创作一部 80 集都市赘婿神医短剧",
        title="绝品神医赘婿",
        genre="都市逆袭",
        synopsis="三年前入赘江家，隐忍受辱，一朝神医传承觉醒...",
        target_episodes=80,
    )
    assert run["type"] == "original_script"
    assert len(run["steps"]) >= 12

    # 2. 连续执行推进（dry-run 快速验证 DAG 拓扑与状态机转移，遇审核节点挂起）
    res = executor.run_until_blocked(db_session, None, run["id"], {"max_steps": 20})
    assert res["status"] in {"completed", "processing", "paused", "waiting_approval"}
    assert res["executed_count"] >= 1


def test_novel_adaptation_end_to_end_pipeline(db_session):
    """测试小说改编端到端流水线创建与连续推进。"""
    bootstrap_service.bootstrap_defaults(db_session)

    # 1. 创建小说改编流水线
    run = run_service.create_novel_adaptation_workflow(
        db_session,
        novel_title="九天战神录",
        chapter_summaries="第1章：战神归隐入赘；第2章：三年期满风云动...",
        novel_text="第一章 归隐\n北境长风烈烈，林辰卸下戎装...",
    )
    assert run["type"] == "novel_adaptation"
    assert len(run["steps"]) >= 14

    # 2. 连续推进前两步
    res = executor.run_until_blocked(db_session, None, run["id"], {"max_steps": 5})
    assert res["executed_count"] >= 1
