"""通用默认保底题材预设包 (Default Universal Genre Pack)。

当未匹配到特定专有题材时作为自适应后备，兼具广泛兼容性。
"""
from __future__ import annotations

from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack
from app.workflows.nodes.stage6.genre_packs.suspense import SuspenseGenrePack


class DefaultGenrePack(SuspenseGenrePack):
    """通用默认保底题材包（继承自 SuspenseGenrePack，保证向后 100% 兼容）。"""

    @property
    def name(self) -> str:
        return "default"

    @property
    def label(self) -> str:
        return "通用/默认影视"

    @property
    def match_keywords(self) -> list[str]:
        return ["通用", "剧情", "默认", "影视", "短剧"]
