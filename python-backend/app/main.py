"""FastAPI 应用入口（等价 Node backend-node/src/app.js + server.js）。

- 端口 5679（与原服务一致，前端 Vite 代理无需改动）
- /static 挂载 Node 版存储目录（图片/视频/音频路径不变）
- 所有 JSON 响应自动注入 timestamp（等价 response.send()）
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.v1 import aiConfig as v1_ai_config
from app.api.v1 import assets as v1_assets
from app.api.v1 import audio as v1_audio
from app.api.v1 import auth as v1_auth
from app.api.v1 import characters as v1_characters
from app.api.v1 import images as v1_images
from app.api.v1 import videos as v1_videos
from app.api.v1 import videoMerges as v1_video_merges
from app.api.v1 import characterLibrary as v1_character_library
from app.api.v1 import drama as v1_drama
from app.api.v1 import episodes as v1_episodes
from app.api.v1 import generation as v1_generation
from app.api.v1 import props as v1_props
from app.api.v1 import scenes as v1_scenes
from app.api.v1 import storyboards as v1_storyboards
from app.api.v1 import propLibrary as v1_prop_library
from app.api.v1 import promptOverrides as v1_prompt_overrides
from app.api.v1 import platform as v1_platform
from app.api.v1 import sceneLibrary as v1_scene_library
from app.api.v1 import sceneModelMap as v1_scene_model_map
from app.api.v1 import settings as v1_settings
from app.api.v1 import tasks as v1_tasks
from app.api.v1 import upload as v1_upload
from app.core import config as cfgmod
from app.core.config import load_config
from app.core.logger import get_logger
from app.core.response import HttpError, TimestampJSONResponse
from app.core.security import build_security_middleware, request_id_from_headers
from app.db import session as dbmod
from app.services import aiConfigService, promptI18n, promptOverridesService, taskService

log = get_logger()


def _load_prompt_overrides() -> None:
    """等价 Node routes/index.js 启动时的 loadOverridesIntoCache。"""
    try:
        with dbmod.SessionLocal() as db:
            promptI18n.load_overrides_into_cache(promptOverridesService.list_overrides(db))
    except Exception as e:
        log.warning("Failed to load prompt overrides", extra={"error": str(e)})


def _apply_vendor_lock() -> None:
    """等价 Node app.js 启动时 applyVendorLock(db, logger, config)。"""
    try:
        with dbmod.SessionLocal() as db:
            aiConfigService.apply_vendor_lock(db, log, load_config())
            db.commit()
    except Exception as e:
        log.warning("Failed to apply vendor lock", extra={"error": str(e)})


def _fail_orphaned_tasks() -> None:
    """等价 Node app.js 启动时 taskService.failOrphanedAsyncTasksOnStartup(db, log)。"""
    try:
        with dbmod.SessionLocal() as db:
            taskService.fail_orphaned_async_tasks_on_startup(db, log)
            db.commit()
    except Exception as e:
        log.warning("Failed to fail orphaned async tasks", extra={"error": str(e)})


def _resume_processing_videos() -> None:
    """等价 Node app.js 启动时 videoService.resumeProcessingVideoGenerations(db, log)。

    - 无 provider_task_id 的 processing 记录判为中断 → failed
    - 有 provider_task_id 的 → 重新挂上轮询（各自在 worker 线程执行）
    """
    from app.services import videoService

    try:
        with dbmod.SessionLocal() as db:
            videoService.resume_processing_video_generations(db, log)
            db.commit()
    except Exception as e:
        log.warning("Failed to resume processing videos", extra={"error": str(e)})


def _start_embedded_queue_worker() -> None:
    """按配置启动内嵌队列 worker；默认关闭，生产环境也可改用独立 worker 进程。"""
    try:
        from app.tasks import worker_runtime

        runtime = worker_runtime.start_embedded_worker(load_config())
        status = runtime.status()
        log.info(
            "Embedded queue worker initialized",
            extra={"status": status.get("status"), "worker_id": status.get("settings", {}).get("worker_id")},
        )
    except Exception as e:  # noqa: BLE001
        # Worker 启动失败不阻止 API 提供只读/人工操作能力，错误会保留在日志中。
        log.warning("Failed to start embedded queue worker", extra={"error": str(e)})


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbmod.init_engine()
    with dbmod.engine.begin() as conn:
        from app.db.schema import ensure_schema

        ensure_schema(conn)
    _apply_vendor_lock()
    _fail_orphaned_tasks()
    _resume_processing_videos()
    _load_prompt_overrides()
    _start_embedded_queue_worker()
    log.info("Schema ensured, app started")
    yield
    # 先停止持久化队列 worker，避免数据库引擎释放后后台线程仍继续取任务。
    try:
        from app.tasks import worker_runtime

        worker_runtime.stop_embedded_worker(wait_seconds=10.0)
    except Exception as e:  # noqa: BLE001
        log.warning("Queue worker shutdown skipped", extra={"reason": str(e)})
    # 优雅退出：等待在途后台任务收尾（超时由线程池自行收敛）
    try:
        from app.services import workerService

        workerService.shutdown(wait=False)
    except Exception as e:  # noqa: BLE001
        log.warning("Worker shutdown skipped", extra={"reason": str(e)})
    dbmod.reset_engine()


def resolve_web_dist_path(custom_dist: Path | str | None = None) -> Path | None:
    """解析前端静态产物目录（对齐 Node app.js 的 WEB_DIST_PATH || frontweb/dist）。"""
    if custom_dist is not None:
        p = Path(custom_dist).resolve()
        return p if p.exists() and p.is_dir() else None

    env_path = os.environ.get("WEB_DIST_PATH")
    if env_path:
        p = Path(env_path).resolve()
        return p if p.exists() and p.is_dir() else None

    candidates = [
        Path.cwd() / "frontweb" / "dist",
        Path.cwd().parent / "frontweb" / "dist",
        Path(__file__).resolve().parent.parent.parent / "frontweb" / "dist",
        Path.cwd() / "web" / "dist",
        Path.cwd().parent / "web" / "dist",
        Path(__file__).resolve().parent.parent.parent / "web" / "dist",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c.resolve()
    return None


def create_app(web_dist: Path | str | None = None) -> FastAPI:
    cfg = load_config()
    v1_settings.init_config(cfg)
    v1_ai_config.init_config(cfg)
    v1_upload.init_config(cfg)
    v1_audio.init_config(cfg)
    v1_storyboards.init_config(cfg)
    v1_images.init_config(cfg)
    v1_characters.init_config(cfg)
    v1_drama.init_config(cfg)
    v1_episodes.init_config(cfg)

    app = FastAPI(
        title=cfg.get("app", {}).get("name", "LocalMiniDrama API"),
        version=str(cfg.get("app", {}).get("version", "1.0.0")),
        debug=bool(cfg.get("app", {}).get("debug", False)),
        lifespan=lifespan,
        docs_url="/docs" if cfg.get("app", {}).get("debug", False) else None,
        redoc_url=None,
        default_response_class=TimestampJSONResponse,
    )

    # CORS（原 server.cors_origins）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfgmod.cors_origins(cfg) or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.middleware("http")(build_security_middleware(cfg))

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request_id_from_headers(request)
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api"):
            log.info(
                "HTTP request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response

    # 静态资源（复用 Node 版存储目录）
    storage_dir = cfgmod.storage_local_path(cfg)
    storage_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(storage_dir)), name="static")

    # v1 老契约路由
    app.include_router(v1_auth.router, prefix="/api/v1")
    app.include_router(v1_settings.router, prefix="/api/v1")
    app.include_router(v1_prompt_overrides.router, prefix="/api/v1")
    app.include_router(v1_scene_model_map.router, prefix="/api/v1")
    app.include_router(v1_character_library.router, prefix="/api/v1")
    app.include_router(v1_scene_library.router, prefix="/api/v1")
    app.include_router(v1_prop_library.router, prefix="/api/v1")
    app.include_router(v1_drama.router, prefix="/api/v1")
    app.include_router(v1_characters.router, prefix="/api/v1")
    app.include_router(v1_scenes.router, prefix="/api/v1")
    app.include_router(v1_props.router, prefix="/api/v1")
    app.include_router(v1_storyboards.router, prefix="/api/v1")
    app.include_router(v1_episodes.router, prefix="/api/v1")
    app.include_router(v1_generation.router, prefix="/api/v1")
    app.include_router(v1_ai_config.router, prefix="/api/v1")
    app.include_router(v1_tasks.router, prefix="/api/v1")
    app.include_router(v1_assets.router, prefix="/api/v1")
    app.include_router(v1_upload.router, prefix="/api/v1")
    app.include_router(v1_audio.router, prefix="/api/v1")
    app.include_router(v1_images.router, prefix="/api/v1")
    app.include_router(v1_videos.router, prefix="/api/v1")
    app.include_router(v1_video_merges.router, prefix="/api/v1")
    # 平台化底座路由：Prompt / Skill / Context / Workflow / Memory，供后续多 Agent 编排逐步接入。
    app.include_router(v1_platform.router, prefix="/api/v1")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "name": cfg.get("app", {}).get("name"), "version": cfg.get("app", {}).get("version")}

    # 前端静态资源与 SPA 路由回退（对齐 Node app.js 79-106）
    web_dist_dir = resolve_web_dist_path(web_dist)
    if web_dist_dir is not None:
        assets_dir = web_dist_dir / "assets"
        if assets_dir.exists() and assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            fav = web_dist_dir / "favicon.ico"
            if fav.is_file():
                return FileResponse(str(fav))
            return Response(status_code=404)

        @app.get("/", include_in_schema=False)
        async def root_index():
            index_html = web_dist_dir / "index.html"
            if index_html.is_file():
                return FileResponse(str(index_html))
            return Response(status_code=404, content="Not Found")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/") or full_path == "api":
                raise HTTPException(status_code=404, detail="接口不存在")
            # 尝试返回 dist 根目录静态文件（如 wx.jpg、favicon.ico、manifest.json 等）
            try:
                candidate = (web_dist_dir / full_path).resolve()
                if candidate.is_relative_to(web_dist_dir.resolve()) and candidate.is_file():
                    return FileResponse(str(candidate))
            except (ValueError, RuntimeError):
                pass
            # SPA 回退：其余 GET 请求均返回 index.html
            index_html = web_dist_dir / "index.html"
            if index_html.is_file():
                return FileResponse(str(index_html))
            return Response(status_code=404, content="Not Found")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def index_prompt() -> str:
            return (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>LocalMiniDrama</title></head><body>"
                "<h1>LocalMiniDrama API</h1><p>后端已启动。请先构建前端：</p>"
                "<pre>cd web &amp;&amp; pnpm install &amp;&amp; pnpm build</pre>"
                "<p>然后将 <code>web/dist</code> 放到与 backend-node 同级的 <code>web/dist</code>，"
                "或访问 <a href=\"/health\">/health</a> 检查接口。</p></body></html>"
            )

    # ---- 异常处理（TimestampJSONResponse 自动注入 timestamp） ----
    @app.exception_handler(HttpError)
    async def http_error_handler(request: Request, exc: HttpError):
        log.warning(
            "HTTP error",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "path": request.url.path,
                "status_code": exc.status_code,
                "code": exc.code,
            },
        )
        return TimestampJSONResponse(status_code=exc.status_code, content=exc.payload())

    @app.exception_handler(StarletteHTTPException)
    async def starlette_error_handler(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api"):
            code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED", 403: "FORBIDDEN"}.get(
                exc.status_code, "HTTP_ERROR"
            )
            detail = str(exc.detail) if exc.detail else ""
            default_msgs = {404: "接口不存在", 405: "方法不允许"}
            message = (
                default_msgs.get(exc.status_code, detail or "HTTP_ERROR")
                if detail in ("", "Not Found", f"{exc.status_code}: Not Found")
                else detail
            )
            return TimestampJSONResponse(
                status_code=exc.status_code,
                content={"success": False, "error": {"code": code, "message": message}},
            )
        return Response(
            content="Not Found" if exc.status_code == 404 else str(exc.detail),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        log.exception(
            "Unhandled error on %s",
            request.url.path,
            extra={"request_id": getattr(request.state, "request_id", ""), "path": request.url.path},
        )
        return TimestampJSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": "服务器错误"},
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run("app.main:app", host=cfgmod.server_host(cfg), port=cfgmod.server_port(cfg))
