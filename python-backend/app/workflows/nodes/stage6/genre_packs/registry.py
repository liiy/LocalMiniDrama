"""题材预设包注册中心与动态识别器 (Genre Pack Registry)。

根据剧本题材类型 (drama_genre)、视觉基准风格 (visual_style) 或剧本文本 (screenplay_text)，
自动精准匹配最适配的题材预设包；未命中时平滑降级至默认保底包，100% 保持历史既有行为兼容。
"""
from __future__ import annotations

import logging
from typing import Any

from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack
from app.workflows.nodes.stage6.genre_packs.default_pack import DefaultGenrePack
from app.workflows.nodes.stage6.genre_packs.scifi import SciFiGenrePack
from app.workflows.nodes.stage6.genre_packs.suspense import SuspenseGenrePack
from app.workflows.nodes.stage6.genre_packs.urban_romance import UrbanRomanceGenrePack
from app.workflows.nodes.stage6.genre_packs.xianxia import XianxiaGenrePack

logger = logging.getLogger("lmd.stage6.genre_packs")


class GenrePackRegistry:
    """题材预设包注册中心。"""

    def __init__(self) -> None:
        self._packs: dict[str, BaseGenrePack] = {}
        self._default_pack: BaseGenrePack = DefaultGenrePack()
        # 预注册内置四大主流题材包
        self.register(SuspenseGenrePack())
        self.register(XianxiaGenrePack())
        self.register(SciFiGenrePack())
        self.register(UrbanRomanceGenrePack())
        self.register(self._default_pack)

    def register(self, pack: BaseGenrePack) -> None:
        """注册一个新的题材预设包。"""
        self._packs[pack.name] = pack
        logger.debug("【题材预设中心】成功挂载题材包: [%s] (%s)", pack.name, pack.label)

    def get_pack(self, name: str) -> BaseGenrePack:
        """根据名称获取指定的题材预设包。"""
        return self._packs.get(name, self._default_pack)

    def detect_genre_pack(
        self,
        drama_genre: str = "",
        visual_style: str = "",
        screenplay_text: str = "",
    ) -> BaseGenrePack:
        """【规则编号: RULE-GENRE-PACK-DETECT】多维度题材识别与自动选包引擎。

        优先级：
          1. 显式 drama_genre 字段命中；
          2. 视觉基准风格 visual_style 命中；
          3. 剧本文本 screenplay_text 前 1000 字符关键词密度探测；
          4. 兜底回退至默认包 (DefaultGenrePack / SuspenseGenrePack)。

        Args:
            drama_genre: 剧目题材类型（如 "仙侠", "悬疑", "科幻"）
            visual_style: 视觉基准风格描述
            screenplay_text: 分集剧本文本内容

        Returns:
            BaseGenrePack: 匹配成功的题材预设包实例
        """
        candidate_texts = [drama_genre, visual_style, screenplay_text[:1000] if screenplay_text else ""]

        # 1. 优先扫描特定题材（古装仙侠、科幻、都市），若命中则立即返回
        for text in candidate_texts:
            if not text:
                continue
            for name in ["xianxia", "scifi", "urban_romance", "suspense"]:
                pack = self._packs.get(name)
                if pack and pack.matches(text):
                    logger.info(
                        "【题材预设中心】自动识别并启用题材包: [%s] (%s) (匹配特征文本: '%s')",
                        pack.name, pack.label, text[:40],
                    )
                    return pack

        logger.debug("【题材预设中心】未命中特殊题材，平滑采用默认影视基准包: [%s]", self._default_pack.label)
        return self._default_pack


# 全局单例注册中心
_global_registry = GenrePackRegistry()


def get_genre_pack(
    drama_genre: str = "",
    visual_style: str = "",
    screenplay_text: str = "",
) -> BaseGenrePack:
    """便捷获取或自动识别题材预设包的统一函数。"""
    return _global_registry.detect_genre_pack(
        drama_genre=drama_genre,
        visual_style=visual_style,
        screenplay_text=screenplay_text,
    )
