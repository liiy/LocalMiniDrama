"""三层解耦记忆架构服务 (Three-Tier Memory Architecture)。

严格遵循《详细设计说明书（V2.0 工业增强版）》第 2.4 节：
1. 第一层：短期工作记忆 (Working Memory) —— 批次内 3~5 集滑动窗口正文与上下文缓存；
2. 第二层：结构化实体记忆 (Structured Entity Memory) —— 角色动态状态、道具信物流向、角色间信息差矩阵（谁已知什么/谁以为谁不知道）；
3. 第三层：情境片段记忆 (Episodic Memory / RAG) —— 历史分集重要事件、伏笔埋设与回收检索，外挂 Qdrant / MySQL memory_items。
"""
from __future__ import annotations

import logging
from typing import Any
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.schemas.script_graph_state import ContinuityMemo, CharacterProfile, ClueItem
from app.db.session import fetch_all, fetch_one
from app.platform_common import json_dumps, json_loads, now_iso

logger = logging.getLogger("three_tier_memory")


class InformationGapEntry(BaseModel):
    """角色间信息差矩阵条目。"""
    fact_id: str = Field(..., description="事件/秘密唯一标识，如 SECRET_001")
    fact_description: str = Field(..., description="真相事实描述")
    knowing_characters: list[str] = Field(default_factory=list, description="已知真相角色列表")
    deceived_characters: list[str] = Field(default_factory=list, description="被蒙在鼓里/受误导的角色列表")
    planned_reveal_episode: int | None = Field(default=None, description="计划揭晓集数")


class ThreeTierMemoryManager:
    """三层解耦记忆管理器。"""

    @classmethod
    def update_entity_memory(
        cls,
        continuity_memo: ContinuityMemo,
        *,
        character_name: str,
        state_updates: dict[str, Any],
        prop_updates: dict[str, str] | None = None,
        gap_updates: list[InformationGapEntry] | None = None,
    ) -> ContinuityMemo:
        """更新第二层：结构化实体记忆（角色状态、道具流向与信息差矩阵）。"""
        char_states = dict(continuity_memo.character_states)
        if character_name not in char_states:
            char_states[character_name] = {}
        char_states[character_name].update(state_updates)

        props = dict(continuity_memo.prop_traces)
        if prop_updates:
            props.update(prop_updates)

        gaps = list(continuity_memo.information_gap_matrix)
        if gap_updates:
            gap_dicts = [g.model_dump() for g in gap_updates]
            gaps.extend(gap_dicts)

        return ContinuityMemo(
            character_states=char_states,
            prop_traces=props,
            information_gap_matrix=gaps,
            unresolved_crises=continuity_memo.unresolved_crises,
        )

    @classmethod
    def assemble_episode_context(
        cls,
        db: Session | None,
        drama_id: int,
        episode_num: int,
        continuity_memo: ContinuityMemo,
        active_window_summaries: list[str],
        characters_present: list[str],
    ) -> str:
        """为单集生成组装三层精准注入上下文（避免全局全量长文本注入导致幻觉）。"""
        # 1. 结构化实体层：仅抽取本集出场人物的状态与道具
        char_info_lines = []
        for cname in characters_present:
            state = continuity_memo.character_states.get(cname, {})
            if state:
                char_info_lines.append(f"- 【{cname}】当前状态: {json_dumps(state)}")

        prop_lines = []
        for prop, holder in continuity_memo.prop_traces.items():
            if holder in characters_present:
                prop_lines.append(f"- 道具【{prop}】当前由 [{holder}] 持有")

        # 2. 信息差层：本集出场人物涉及的信息差
        gap_lines = []
        for gap in continuity_memo.information_gap_matrix:
            knowers = gap.get("knowing_characters", [])
            deceived = gap.get("deceived_characters", [])
            overlap = set(characters_present) & (set(knowers) | set(deceived))
            if overlap:
                gap_lines.append(
                    f"- 秘密【{gap.get('fact_id')}】: {gap.get('fact_description')} "
                    f"(知情: {', '.join(knowers)} | 蒙蔽: {', '.join(deceived)})"
                )

        # 3. 短期工作记忆：前置滑动窗口剧情摘要
        recent_summary = "\n".join(active_window_summaries[-3:]) if active_window_summaries else "开篇剧情启动。"

        context_prompt = f"""【三层记忆精准注入上下文 (第 {episode_num} 集)】
### 1. 前置最近剧情滑动摘要：
{recent_summary}

### 2. 出场角色当前动态与道具流向：
{chr(10).join(char_info_lines) if char_info_lines else "角色状态稳定。"}
{chr(10).join(prop_lines) if prop_lines else ""}

### 3. 角色间信息差约束（严禁全知降智，必须遵循认知边界）：
{chr(10).join(gap_lines) if gap_lines else "暂无特殊信息差。"}
"""
        return context_prompt
