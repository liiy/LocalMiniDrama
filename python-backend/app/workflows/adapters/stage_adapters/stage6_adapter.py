"""阶段 6 资产持久化适配器兼容门面 (Stage 6 Persistence Adapter Facade)。

本模块作为向后兼容门面，完整重导出 `app.workflows.adapters.stage_adapters.stage6`
子包中的所有公共函数、落库调度器与清洗工具：
- `helpers.py`: 字符清洗、Token 提取、实体模糊匹配与提示词兜底合成；
- `character_persister.py`: Tier 1 角色主体、Tier 2 外观阶段、Tier 3 多视切片与单集登场映射；
- `voice_persister.py`: 角色母音频卡片与专属音色配置同步落库及 100% 覆盖差集兜底；
- `scene_persister.py`: 空间场景层级、子空间划分及动态气候做旧切片原子落库；
- `prop_persister.py`: 关键叙事道具主记录及其剧情战损演进形态树落库；
- `asset_persister.py`: 统管媒体素材库全量写入、DAG 血统关联、Qdrant 向量同步及短剧全局阶段跃迁；
- `orchestrator.py`: 调度统筹上述所有落库子流水线的业务入口 `persist_stage6`。

【重构说明】
原 3,651 行单体大文件已拆解为上述领域子模块，本文件保持 100% 的签名与命名空间兼容。
"""
from __future__ import annotations

from app.workflows.adapters.stage_adapters.stage6 import (
    clean_character_name,
    extract_character_tokens,
    extract_natural_appearance,
    find_canonical_entity,
    parse_character_view_type,
    persist_stage6,
    persist_stage6_assets,
    persist_stage6_characters,
    persist_stage6_props,
    persist_stage6_scenes,
    persist_stage6_voices,
    synthesize_character_literary_defaults,
    synthesize_voice_prompt,
)

__all__ = [
    "clean_character_name",
    "extract_character_tokens",
    "find_canonical_entity",
    "parse_character_view_type",
    "extract_natural_appearance",
    "synthesize_character_literary_defaults",
    "synthesize_voice_prompt",
    "persist_stage6",
    "persist_stage6_characters",
    "persist_stage6_voices",
    "persist_stage6_scenes",
    "persist_stage6_props",
    "persist_stage6_assets",
]
