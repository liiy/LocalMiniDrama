"""Test fixtures use an isolated DB and a temporary config file.
Set LMD_TEST_DATABASE_URL for remote/container DB; local MySQL is the default."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="lmd-test-")
_tmpcfg = os.path.join(_tmpdir, "config.yaml")
_src_cfg = Path(__file__).resolve().parent.parent / "configs" / "config.yaml"
shutil.copy(_src_cfg, _tmpcfg)

os.environ["LMD_CONFIG_PATH"] = _tmpcfg
os.environ["LMD_DATABASE_URL"] = os.environ.get(
    "LMD_TEST_DATABASE_URL",
    "mysql+pymysql://lmd:lmd@127.0.0.1:3306/drama_genertor_test?charset=utf8mb4",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import session as dbm  # noqa: E402
from app.main import app  # noqa: E402


def _is_unit_test(request) -> bool:
    """纯单元测试不应被真实 MySQL 初始化阻塞。"""
    path = str(getattr(request.node, "fspath", ""))
    return "tests\\unit" in path or "tests/unit" in path

# 姣忎釜娴嬭瘯鍓嶆竻绌虹殑琛紙浠呮祴璇曞簱鍐呯殑鏁版嵁琛級
_CLEAN_TABLES = (
    "global_settings",
    "async_tasks",
    "dramas",
    "episodes",
    "characters",
    "prompt_overrides",
    "ai_model_map",
    "character_libraries",
    "scene_libraries",
    "prop_libraries",
    "episode_characters",
    "storyboard_props",
    "storyboards",
    "scenes",
    "props",
    "storyboard_characters",
    "ai_service_configs",
    "assets",
    "image_generations",
    "video_generations",
    "prompt_templates",
    "prompt_runs",
    "skills",
    "skill_versions",
    "context_snapshots",
    "workflow_runs",
    "workflow_steps",
    "queue_jobs",
    "worker_nodes",
    "agent_runs",
    "memory_items",
    "character_voice_profiles",
    "music_bibles",
    "music_cues",
    "audio_generations",
    "quality_reports",
)


@pytest.fixture(scope="session")
def _fresh_db():
    dbm.init_engine()
    with dbm.engine.begin() as conn:
        from app.db.schema import ensure_schema

        ensure_schema(conn)
    yield
    dbm.reset_engine()


@pytest.fixture(autouse=True)
def _clean_data(request):
    """姣忎釜娴嬭瘯鍓嶆竻绌烘暟鎹〃锛堥伩鍏嶆祴璇曢棿娈嬬暀锛夈€?
    鏄惧紡 init_engine锛歍estClient 閫€鍑烘椂 lifespan 浼?reset_engine锛?    session 绾?_fresh_db 缂撳瓨涓嶄細閲嶈窇锛岄渶鍦?setup 闃舵纭繚 engine 瀛樺湪銆?    """
    if _is_unit_test(request):
        yield
        return

    dbm.init_engine()
    with dbm.engine.begin() as conn:
        from app.db.schema import ensure_schema

        ensure_schema(conn)
        for table in _CLEAN_TABLES:
            try:
                conn.execute(text(f"DELETE FROM `{table}`"))
            except Exception:
                pass
    yield


@pytest.fixture()
def client(_fresh_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session():
    """单元测试专用独立内存 SQLite Session，免去外部 DB 依赖。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.schema import ensure_schema

    engine = create_engine("sqlite:///:memory:", echo=False)
    with engine.begin() as conn:
        ensure_schema(conn)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()

