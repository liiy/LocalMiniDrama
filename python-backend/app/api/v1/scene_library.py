"""/api/v1/scene-library — 契约精确翻译 backend-node/src/routes/sceneLibrary.js。"""
from __future__ import annotations

from app.api.v1.libraryRouterBase import make_library_router
from app.services import sceneLibraryService as svc

router = make_library_router("/scene-library", "sceneLibrary", svc, "场景库项不存在")
