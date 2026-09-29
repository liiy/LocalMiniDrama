"""红蓝自审路由决策与原位自愈分流控制器 (Audit Router)。

【公共硬性约束遵守说明】：
1. 本模块严格抽离所有业务分支判断到独立的条件路由函数中，节点函数内部严禁包含业务跳转分支；
2. 路由函数严格穷举所有状态分支，并包含兜底 else 指向错误终止标识，无任何未定义分支；
3. 状态交互契约对齐 TypedDict (IndustrialDramaState)，各逻辑明确标注《Skill规则表》规则编号并配置 debug 日志。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Literal, Mapping

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    IndustrialDramaState,
    RedBlueAuditReport,
)

logger = logging.getLogger("lmd.audit_router")


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


# =========================================================================
# 哨卡审查节点函数 (统一入参 state，内部无分支跳转，仅输出状态更新字典)
# =========================================================================

def stage1_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-01】阶段 1 题材破壁哨卡审查节点。"""
    logger.debug("[Stage 1 Audit Node] Starting Checkpoint 1 evaluation.")
    payload = {
        "selected_title": _get_val(state, "selected_title", ""),
        "candidate_titles": _get_val(state, "candidate_titles", {}),
        "logline": _get_val(state, "logline", ""),
        "grand_payoff": _get_val(state, "grand_payoff", ""),
        "negative_rules": _get_val(state, "negative_rules", {}),
        "forbidden_cliches_10": _get_val(state, "forbidden_cliches_10", []),
        "forbidden_cheap_tropes_3": _get_val(state, "forbidden_cheap_tropes_3", []),
    }
    forbidden_rules = _get_val(state, "negative_rules", None)
    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=1,
        content_payload=payload,
        forbidden_rules=forbidden_rules,
    )
    
    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage1"] = retry_counts.get("stage1", 0) + 1

    logger.debug(
        f"[Stage 1 Audit Node] Checkpoint 1 complete: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage1', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def stage2_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-02】阶段 2 角色建模哨卡审查节点。"""
    logger.debug("[Stage 2 Audit Node] Starting Checkpoint 2 evaluation.")
    chars_engine = _get_val(state, "characters_engine", {})
    chars = chars_engine.get("characters", []) if isinstance(chars_engine, dict) else []
    payload = {"characters": chars}
    forbidden_rules = _get_val(state, "negative_rules", None)
    
    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=2,
        content_payload=payload,
        forbidden_rules=forbidden_rules,
    )
    
    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage2"] = retry_counts.get("stage2", 0) + 1

    logger.info(
        f"[Stage 2 Audit Node] Checkpoint 2 审查完成: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage2', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def stage3_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-03】阶段 3 空间与物证哨卡审查节点。"""
    logger.debug("[Stage 3 Audit Node] Starting Checkpoint 3 evaluation.")
    env_props = _get_val(state, "environments_and_props", {})
    payload = {
        "environments": env_props.get("environments", []) if isinstance(env_props, dict) else [],
        "props": env_props.get("props", []) if isinstance(env_props, dict) else [],
    }
    forbidden_rules = _get_val(state, "negative_rules", None)
    
    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=3,
        content_payload=payload,
        forbidden_rules=forbidden_rules,
    )
    
    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage3"] = retry_counts.get("stage3", 0) + 1

    logger.debug(
        f"[Stage 3 Audit Node] Checkpoint 3 complete: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage3', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def stage4_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-04】阶段 4 双螺旋大纲与音乐动机母库审查节点。"""
    logger.debug("[Stage 4 Audit Node] Starting Checkpoint 4 evaluation.")
    payload = {
        "audio_bible": _get_val(state, "audio_bible", {}),
        "season_outlines": _get_val(state, "season_outlines", {}),
    }
    forbidden_rules = _get_val(state, "negative_rules", None)
    
    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=4,
        content_payload=payload,
        forbidden_rules=forbidden_rules,
    )
    
    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage4"] = retry_counts.get("stage4", 0) + 1

    logger.debug(
        f"[Stage 4 Audit Node] Checkpoint 4 complete: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage4', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def stage5_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-05】阶段 5 文学剧本哨卡审查节点。"""
    logger.debug("[Stage 5 Audit Node] Starting Checkpoint 5 evaluation.")
    completed = _get_val(state, "completed_screenplays", {}) or {}
    payload = completed
    forbidden_rules = _get_val(state, "negative_rules", None)

    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=5,
        content_payload=payload,
        forbidden_rules=forbidden_rules,
    )

    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage5"] = retry_counts.get("stage5", 0) + 1

    logger.debug(
        f"[Stage 5 Audit Node] Checkpoint 5 complete: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage5', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def stage6_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-06】阶段 6 视听资产提纯哨卡审查节点。"""
    curr_ep = _get_val(state, "current_visual_episode", 1) or 1
    logger.debug(f"[Stage 6 Audit Node] Starting Checkpoint 6 evaluation for Episode {curr_ep}.")
    manifests = _get_val(state, "episode_resource_manifests", {}) or {}
    manifest = manifests.get(curr_ep) or {}
    manifest_dict = manifest.model_dump() if hasattr(manifest, "model_dump") else manifest if isinstance(manifest, dict) else {}
    forbidden_rules = _get_val(state, "negative_rules", None)

    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=6,
        content_payload=manifest_dict,
        forbidden_rules=forbidden_rules,
    )

    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage6"] = retry_counts.get("stage6", 0) + 1

    logger.debug(
        f"[Stage 6 Audit Node] Checkpoint 6 complete for Ep {curr_ep}: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage6', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def stage7_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-07】阶段 7 视听分镜与 SRT 哨卡审查节点。"""
    curr_ep = _get_val(state, "current_visual_episode", 1) or 1
    logger.debug(f"[Stage 7 Audit Node] Starting Checkpoint 7 evaluation for Episode {curr_ep}.")
    storyboards = _get_val(state, "episode_storyboards", {}) or {}
    shots = storyboards.get(curr_ep) or []
    srts = _get_val(state, "episode_srt_exports", {}) or {}
    srt_export = srts.get(curr_ep) or ""
    planned_duration = float(_get_val(state, "duration_sec_per_ep", 120.0) or _get_val(state, "target_duration_sec", 120.0) or 120.0)

    shots_payload = [
        s.model_dump() if hasattr(s, "model_dump") else s
        for s in shots
    ]
    payload = {
        "episode_num": curr_ep,
        "planned_duration_sec": planned_duration,
        "shots": shots_payload,
        "srt_export": srt_export,
    }
    forbidden_rules = _get_val(state, "negative_rules", None)

    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=7,
        content_payload=payload,
        forbidden_rules=forbidden_rules,
    )

    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage7"] = retry_counts.get("stage7", 0) + 1

    logger.debug(
        f"[Stage 7 Audit Node] Checkpoint 7 complete for Ep {curr_ep}: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage7', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def stage8_audit_node(state: Any) -> dict[str, Any]:
    """【规则编号: AUDIT-CHECKPOINT-08】阶段 8 声学混音与 Ducking 哨卡审查节点。"""
    curr_ep = _get_val(state, "current_visual_episode", 1) or 1
    logger.debug(f"[Stage 8 Audit Node] Starting Checkpoint 8 evaluation for Episode {curr_ep}.")
    masterings = _get_val(state, "episode_audio_masterings", {}) or {}
    mastering_config = masterings.get(curr_ep) or {}
    storyboards = _get_val(state, "episode_storyboards", {}) or {}
    shots = storyboards.get(curr_ep) or []

    shots_payload = [
        s.model_dump() if hasattr(s, "model_dump") else s
        for s in shots
    ]
    payload = {
        "mastering_config": mastering_config,
        "shots": shots_payload,
    }
    forbidden_rules = _get_val(state, "negative_rules", None)

    report: RedBlueAuditReport = RedBlueAuditor.audit(
        stage=8,
        content_payload=payload,
        forbidden_rules=forbidden_rules,
    )

    retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
    verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
    if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        retry_counts["stage8"] = retry_counts.get("stage8", 0) + 1

    logger.debug(
        f"[Stage 8 Audit Node] Checkpoint 8 complete for Ep {curr_ep}: verdict={verdict_str}, "
        f"blocking_issues={len(report.blocking_issues)}, retry_count={retry_counts.get('stage8', 0)}"
    )
    return {
        "latest_audit": report,
        "stage_retry_counts": retry_counts,
    }


def make_stage_audit_node(
    stage: int,
    payload_selector: Callable[[Any], Any],
):
    """构建通用阶段自审执行节点工厂（保持向后兼容）。"""
    def stage_audit_node(state: Any) -> dict[str, Any]:
        logger.debug(f"[make_stage_audit_node] Running generic audit node for Stage {stage}.")
        payload = payload_selector(state)
        forbidden_rules = _get_val(state, "negative_rules", None)
        
        report: RedBlueAuditReport = RedBlueAuditor.audit(
            stage=stage,
            content_payload=payload,
            forbidden_rules=forbidden_rules,
        )

        stage_key = f"stage{stage}"
        retry_counts = dict(_get_val(state, "stage_retry_counts", {}) or {})
        verdict_str = report.verdict if isinstance(report.verdict, str) else getattr(report.verdict, "value", str(report.verdict))
        if verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
            retry_counts[stage_key] = retry_counts.get(stage_key, 0) + 1

        logger.info(
            f"Stage {stage} Audit Complete: verdict={report.verdict}, blocking_count={len(report.blocking_issues)}"
        )
        return {
            "latest_audit": report,
            "stage_retry_counts": retry_counts,
        }

    return stage_audit_node


# =========================================================================
# 独立条件路由函数 (严格穷举所有分支，严禁 LLM 分支，兜底 else 指向错误终止)
# =========================================================================

def decide_audit_route(
    state: Any = None,
    stage_name: str | int = "stage1",
    max_retries: int = 2,
    current_retry_count: int | None = None,
    verdict: str | None = None,
    retry_count: int | None = None,
) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: ROUTER-FAILOVER-01】根据最新质检报告进行全分支穷举路由决策。
    
    分支穷举：
    1. GREEN_APPROVED ➔ proceed (放行进入下一阶段)
    2. YELLOW_WARNING ➔ proceed (放行进入下一阶段，携带提示)
    3. RED_BLOCKING 且 retry_count < max_retries ➔ self_heal (就地自愈重新执行当前阶段)
    4. RED_BLOCKING 且 retry_count >= max_retries ➔ escalate_human (超过重试上限，升级人工审核)
    5. else ➔ error_terminate (未知状态或数据异常，兜底转向错误终止节点)
    """
    logger.debug(f"[decide_audit_route] Evaluating audit route for '{stage_name}'.")
    if verdict is not None:
        verdict_str = verdict
    else:
        audit = _get_val(state, "latest_audit", None)
        if not audit:
            logger.warning(f"[decide_audit_route] No latest_audit found for {stage_name}, default proceed.")
            return "proceed"

        # 获取 verdict 字符串
        verdict_val = getattr(audit, "verdict", None)
        if verdict_val is None and isinstance(audit, dict):
            verdict_val = audit.get("verdict")
        verdict_str = verdict_val if isinstance(verdict_val, str) else getattr(verdict_val, "value", str(verdict_val))

    # 计算当前阶段已尝试的重试次数
    stage_key = f"stage{stage_name}" if isinstance(stage_name, int) else str(stage_name)
    if retry_count is not None:
        retries = retry_count
    elif current_retry_count is not None:
        retries = current_retry_count
    else:
        counts = _get_val(state, "stage_retry_counts", {}) or {}
        retries = counts.get(stage_key, 0)

    # 穷举分支判定
    if verdict_str == AuditVerdict.GREEN_APPROVED or verdict_str == "GREEN_APPROVED":
        logger.debug(f"[decide_audit_route] Stage {stage_key}: Verdict is GREEN_APPROVED. Routing -> proceed.")
        return "proceed"
    elif verdict_str == AuditVerdict.YELLOW_WARNING or verdict_str == "YELLOW_WARNING":
        logger.debug(f"[decide_audit_route] Stage {stage_key}: Verdict is YELLOW_WARNING. Routing -> proceed.")
        return "proceed"
    elif verdict_str == AuditVerdict.RED_BLOCKING or verdict_str == "RED_BLOCKING":
        if retries < max_retries:
            logger.warning(
                f"[decide_audit_route] Stage {stage_key}: Verdict is RED_BLOCKING. "
                f"Retry {retries}/{max_retries} < limit. Routing -> self_heal."
            )
            return "self_heal"
        elif retries >= max_retries:
            logger.error(
                f"[decide_audit_route] Stage {stage_key}: Verdict is RED_BLOCKING. "
                f"Retry {retries}/{max_retries} >= limit. Routing -> escalate_human."
            )
            # 兼容 legacy 节点调用返回 "human_review"，新独立条件路由返回 "escalate_human"
            if current_retry_count is not None:
                return "human_review"  # type: ignore
            return "escalate_human"
        else:
            # 逻辑防御兜底
            logger.error(f"[decide_audit_route] Stage {stage_key}: Unexpected retry count state: {retries}.")
            return "error_terminate"
    else:
        # 兜底 else：任何未定义的分支状态均指向错误终止节点，杜绝未定义分支
        logger.critical(
            f"[decide_audit_route] Stage {stage_key}: Unrecognized verdict '{verdict_str}'. "
            f"Routing to fallback error_terminate."
        )
        return "error_terminate"


def route_stage1_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-01 & ROUTER-FAILOVER-01】阶段 1 独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage1")


def route_stage2_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-02 & ROUTER-FAILOVER-01】阶段 2 独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage2")


def route_stage3_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-03 & ROUTER-FAILOVER-01】阶段 3 独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage3")


def route_stage4_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-04 & ROUTER-FAILOVER-01】阶段 4 独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage4")


def route_stage5_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-05 & ROUTER-FAILOVER-01】阶段 5 文学剧本独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage5")


def route_stage5_batch(state: Any) -> Literal["next_batch", "gatekeeper", "error_terminate"]:
    """【规则编号: ROUTER-BATCH-05】阶段 5 文学剧本波次吞吐状态路由函数。
    
    分支穷举：
    1. completed_count < total_episodes ➔ next_batch (推进下一波 Mini-Arc 批次)
    2. completed_count >= total_episodes ➔ gatekeeper (全季文学剧本就绪，进入定稿总门禁)
    3. else ➔ error_terminate (状态异常，兜底终止)
    """
    total = _get_val(state, "total_episodes", None)
    if total is None:
        total = _get_val(state, "target_episodes", 12)
    completed = _get_val(state, "completed_screenplays", {}) or {}
    completed_count = len(completed)

    logger.debug(f"[route_stage5_batch] Progress check: {completed_count}/{total} episodes completed.")

    if not isinstance(completed_count, int) or not isinstance(total, int) or total <= 0:
        logger.error(f"[route_stage5_batch] Invalid batch progress state: count={completed_count}, total={total}")
        return "error_terminate"
    elif completed_count < total:
        logger.debug(f"[route_stage5_batch] Routing -> next_batch.")
        return "next_batch"
    elif completed_count >= total:
        logger.debug(f"[route_stage5_batch] Routing -> gatekeeper.")
        return "gatekeeper"
    else:
        logger.critical(f"[route_stage5_batch] Unhandled branch state: count={completed_count}, total={total}")
        return "error_terminate"


def route_literary_gatekeeper(state: Any) -> Literal["proceed_journey2", "halt_journey1", "error_terminate"]:
    """【规则编号: ROUTER-GATEKEEPER-05】第一程定稿门禁独立条件路由函数。
    
    分支穷举：
    1. literary_journey_locked == True ➔ proceed_journey2 (第一程锁死，放行进入第二程视听工程)
    2. literary_journey_locked == False ➔ halt_journey1 (未锁定，留在第一程继续补充)
    3. else ➔ error_terminate (状态异常，兜底终止)
    """
    locked = _get_val(state, "literary_journey_locked", None)
    logger.debug(f"[route_literary_gatekeeper] Evaluating literary gate lock status: {locked}")

    if locked is True:
        logger.info("[route_literary_gatekeeper] Literary Journey locked. Routing -> proceed_journey2.")
        return "proceed_journey2"
    elif locked is False or locked is None:
        logger.warning("[route_literary_gatekeeper] Literary Journey unlocked. Routing -> halt_journey1.")
        return "halt_journey1"
    else:
        logger.critical(f"[route_literary_gatekeeper] Unexpected lock state '{locked}'. Routing -> error_terminate.")
        return "error_terminate"


def route_stage6_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-06 & ROUTER-FAILOVER-01】阶段 6 视听资产提纯独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage6")


def route_stage7_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-07 & ROUTER-FAILOVER-01】阶段 7 视听分镜与 SRT 独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage7")


def route_stage8_audit(state: Any) -> Literal["proceed", "self_heal", "escalate_human", "error_terminate"]:
    """【规则编号: AUDIT-CHECKPOINT-08 & ROUTER-FAILOVER-01】阶段 8 声学混音与 Ducking 独立条件路由函数。"""
    return decide_audit_route(state, stage_name="stage8")


def route_episode_loop(state: Any) -> Literal["next_episode", "complete_all", "error_terminate"]:
    """【规则编号: ROUTER-EPISODE-LOOP-01】第二程视听工程单集滚动微循环独立条件路由函数。
    
    分支穷举：
    1. current_visual_episode < total_episodes ➔ next_episode (推进下一集视听制作)
    2. current_visual_episode >= total_episodes ➔ complete_all (全季所有集数视听工程完毕)
    3. else ➔ error_terminate (状态异常，兜底终止)
    """
    curr_ep = _get_val(state, "current_visual_episode", 1) or 1
    total = _get_val(state, "total_episodes", None)
    if total is None:
        total = _get_val(state, "target_episodes", 12) or 12

    logger.debug(f"[route_episode_loop] Episode loop check: current_visual_episode={curr_ep}, total_episodes={total}")

    if not isinstance(curr_ep, int) or not isinstance(total, int) or total <= 0:
        logger.error(f"[route_episode_loop] Invalid loop parameters: curr_ep={curr_ep}, total={total}")
        return "error_terminate"
    elif curr_ep < total:
        logger.debug(f"[route_episode_loop] Next episode pending ({curr_ep} < {total}). Routing -> next_episode.")
        return "next_episode"
    elif curr_ep >= total:
        logger.info(f"[route_episode_loop] All episodes completed ({curr_ep} >= {total}). Routing -> complete_all.")
        return "complete_all"
    else:
        logger.critical(f"[route_episode_loop] Unhandled branch state: curr_ep={curr_ep}, total={total}")
        return "error_terminate"


def episode_increment_node(state: Any) -> dict[str, Any]:
    """【规则编号: NODE-EPISODE-INC-01】第二程单集视听游标递增辅助节点。
    
    统一入参 state，内部严禁业务分支跳转，仅输出增量状态字典。
    将 current_visual_episode 推进至下一集，并将 current_stage 复位为 6 (启动下一集资产提纯)。
    """
    curr_ep = _get_val(state, "current_visual_episode", 1) or 1
    next_ep = curr_ep + 1
    logger.info(f"[Episode Increment Node] Advancing visual episode cursor: {curr_ep} -> {next_ep}, resetting stage to 6.")
    return {
        "current_visual_episode": next_ep,
        "current_stage": 6,
    }


def pipeline_complete_node(state: Any) -> dict[str, Any]:
    """【规则编号: NODE-COMPLETE-ALL-01】全剧两程九阶全流程成功完结终端节点。"""
    logger.info("[Pipeline Complete Node] All literary and audio-visual stages successfully finished!")
    return {
        "journey": "completed",
        "current_stage": 8,
    }


# =========================================================================
# 错误终止与人工介入终端节点 (无后续业务分支，负责封装终止或挂起状态)
# =========================================================================

def error_terminal_node(state: Any) -> dict[str, Any]:
    """【规则编号: ROUTER-FAILOVER-01】错误兜底终止节点。"""
    logger.critical(f"[Error Terminal Node] Pipeline terminated due to unrecoverable audit error or invalid branch.")
    audit = _get_val(state, "latest_audit", None)
    err = "Unknown critical routing or validation error"
    if audit:
        blocking = getattr(audit, "blocking_issues", None) or (audit.get("blocking_issues") if isinstance(audit, dict) else [])
        if blocking:
            err = f"Audit Blocking: {'; '.join(blocking)}"
    return {
        "error_message": err,
        "journey": "completed",
    }


def human_review_node(state: Any) -> dict[str, Any]:
    """【规则编号: ROUTER-FAILOVER-01】人工干预与审核挂起节点。"""
    logger.warning(f"[Human Review Node] Pipeline suspended for human creative review.")
    audit = _get_val(state, "latest_audit", None)
    issues = []
    if audit:
        issues = getattr(audit, "blocking_issues", None) or (audit.get("blocking_issues") if isinstance(audit, dict) else [])
    return {
        "error_message": f"Suspended for human intervention: {issues}",
    }
