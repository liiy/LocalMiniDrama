"""/api/v1/prop-library — 契约精确翻译 backend-node/src/routes/propLibrary.js。"""
from __future__ import annotations

from app.api.v1.libraryRouterBase import make_library_router
from app.services import propLibraryService as svc

router = make_library_router("/prop-library", "propLibrary", svc, "道具库项不存在")
