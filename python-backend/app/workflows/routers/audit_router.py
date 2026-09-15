"""红蓝自审路由决策与原位自愈分流控制器 (Audit Router)。"""
from __future__ import annotations

from typing import Any, Callable, Literal
import logging

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import AuditVerdict, IndustrialDramaMasterState, RedBlueAuditReport

logger = logging.getLogger("lmd.audit_router")


def make_stage_audit_node(
    stage: int,
    payload_selector: Callable[[IndustrialDramaMasterState], Any],
):
    """构建阶段自审执行节点。"""
    def stage_audit_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
        payload = payload_selector(state)
        forbidden_rules = getattr(state, "negative_rules", None)
        
        report: RedBlueAuditReport = RedBlueAuditor.audit(
            stage=stage,
            content_payload=payload,
            forbidden_rules=forbidden_rules,
        )

        logger.info(
            f"Stage {stage} Audit Complete: verdict={report.verdict}, blocking_count={len(report.blocking_issues)}"
        )
        return {
            "latest_audit": report,
        }

    return stage_audit_node


def decide_audit_route(
    state: IndustrialDramaMasterState,
    max_retries: int = 2,
    current_retry_count: int = 0,
) -> Literal["proceed", "self_heal", "human_review"]:
    """根据最新红蓝质检报告决定状态机下一跳方向。"""
    audit = state.latest_audit
    if not audit:
        return "proceed"

    if audit.verdict == AuditVerdict.GREEN_APPROVED or audit.verdict == AuditVerdict.YELLOW_WARNING:
        return "proceed"

    if audit.verdict == AuditVerdict.RED_BLOCKING:
        if current_retry_count < max_retries:
            logger.warning(
                f"Audit RED_BLOCKING triggered self-healing (retry {current_retry_count + 1}/{max_retries}): {audit.blocking_issues}"
            )
            return "self_heal"
        else:
            logger.error(
                f"Audit RED_BLOCKING exceeded max_retries ({max_retries}), escalating to human review: {audit.blocking_issues}"
            )
            return "human_review"

    return "proceed"
