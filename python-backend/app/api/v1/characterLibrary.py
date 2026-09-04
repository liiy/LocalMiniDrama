"""/api/v1/character-library — 契约精确翻译 backend-node/src/routes/characterLibrary.js。"""
from __future__ import annotations

from app.api.v1.libraryRouterBase import make_library_router
from app.services import characterLibraryService as svc

router = make_library_router("/character-library", "characterLibrary", svc, "角色库项不存在")
