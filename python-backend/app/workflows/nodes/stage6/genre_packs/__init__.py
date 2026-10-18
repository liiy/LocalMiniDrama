"""阶段 6 多题材预设包子系统 (Stage 6 Genre Packs Subsystem)。

提供多题材自适应架构，解除原系统硬编码现代工装夹克的限制，使阶段 6 自适应处理任何题材剧本。
"""
from __future__ import annotations

from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack
from app.workflows.nodes.stage6.genre_packs.default_pack import DefaultGenrePack
from app.workflows.nodes.stage6.genre_packs.registry import (
    GenrePackRegistry,
    get_genre_pack,
)
from app.workflows.nodes.stage6.genre_packs.scifi import SciFiGenrePack
from app.workflows.nodes.stage6.genre_packs.suspense import SuspenseGenrePack
from app.workflows.nodes.stage6.genre_packs.urban_romance import UrbanRomanceGenrePack
from app.workflows.nodes.stage6.genre_packs.xianxia import XianxiaGenrePack

__all__ = [
    "BaseGenrePack",
    "DefaultGenrePack",
    "GenrePackRegistry",
    "SciFiGenrePack",
    "SuspenseGenrePack",
    "UrbanRomanceGenrePack",
    "XianxiaGenrePack",
    "get_genre_pack",
]
