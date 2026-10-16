# -*- coding: utf-8 -*-
"""剧本质检与红蓝对抗审计状态契约。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.audit")


class AuditVerdict(str):
    """红蓝对抗自审判定状态。"""
    GREEN_APPROVED = "GREEN_APPROVED"
    GREEN_PASS = "GREEN_PASS"
    BLUE_PASS = "BLUE_PASS"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    YELLOW_WARNING = "YELLOW_WARNING"
    RED_BLOCKING = "RED_BLOCKING"


class RedBlueAuditReport(BaseModel):
    """双重视角独立红蓝对抗自审报告模型 (对齐 SKILL.md)。"""
    blue_team_compliance: dict[str, Any] = Field(
        default_factory=dict,
        description="【蓝军客观合规审查】（客观硬指标：时间轴秒数累加、资产存在性、格式完备、禁令红线）"
    )
    red_team_criticism: dict[str, Any] = Field(
        default_factory=dict,
        description="【红军魔鬼制片人挑刺】（专门挑刺：戏剧张力刺、逻辑硬伤刺、视听落地穿模刺）"
    )
    verdict: str = Field(
        default="GREEN_APPROVED",
        description="综合判定结果：GREEN_APPROVED / YELLOW_WARNING / RED_BLOCKING"
    )
    blocking_issues: list[str] = Field(default_factory=list, description="阻断级硬伤清单（触发状态机就地重构）")
    warning_suggestions: list[str] = Field(default_factory=list, description="警示改进建议（供主创在门控点裁决）")

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    @property
    def blue_checks(self) -> dict[str, Any]:
        return self.blue_team_compliance

    @property
    def red_complaints(self) -> dict[str, Any]:
        return self.red_team_criticism

    @property
    def blocking_reasons(self) -> list[str]:
        return self.blocking_issues

    @property
    def confidence_score(self) -> float:
        return 0.95 if self.verdict == "GREEN_APPROVED" else (0.8 if self.verdict == "YELLOW_WARNING" else 0.5)


class StageAuditReport(TypedDict, total=False):
    """【规则编号: RULE-IV-01】单阶段红蓝对抗自审汇报字典。"""
    blue_team: str
    red_team_critic: str
    verdict: Literal["GREEN_APPROVED", "YELLOW_WARNING", "RED_BLOCKED"]
    blocking_issues: list[str]
    warning_suggestions: list[str]


__all__ = [
    "AuditVerdict",
    "RedBlueAuditReport",
    "StageAuditReport",
]
