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

# 先加载项目 .env，再决定测试库地址，保证 pytest 与独立验收工具行为一致。
from app.core.config import load_environment_file  # noqa: E402

load_environment_file()
os.environ["LMD_CONFIG_PATH"] = _tmpcfg
# 测试使用固定隔离主密钥，避免在源码目录生成本地密钥文件。
os.environ.setdefault("LMD_MASTER_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
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
    node_str = str(getattr(request.node, "nodeid", "")) or str(getattr(request.node, "path", "")) or str(getattr(request.node, "fspath", ""))
    return "unit" in node_str.lower() or "test_platform_foundation" in node_str

# 每个契约测试前清空的表，仅操作隔离测试库。
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
    """每个契约测试前清表，避免用例之间残留数据互相影响。"""
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
    from sqlalchemy.pool import StaticPool
    from app.db.schema import ensure_schema

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    with engine.begin() as conn:
        ensure_schema(conn)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def unit_client(db_session):
    """单元测试专用 TestClient，覆盖 get_db 与 session_scope。"""
    from contextlib import asynccontextmanager, contextmanager
    from app.db.session import get_db
    import app.db.session as app_session_mod

    def override_get_db():
        yield db_session

    @contextmanager
    def override_session_scope():
        yield db_session

    orig_scope = app_session_mod.session_scope
    orig_lifespan = app.router.lifespan_context
    app_session_mod.session_scope = override_session_scope
    app.router.lifespan_context = asynccontextmanager(lambda app: (yield))
    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app_session_mod.session_scope = orig_scope
        app.router.lifespan_context = orig_lifespan

