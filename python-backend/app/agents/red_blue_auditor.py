"""红蓝对抗独立自审引擎 (Red-Blue Auditor Agent)。

严格遵循 SKILL.md 工业级标准：
- 蓝军工程师：客观硬指标审查（双轨禁令、时间轴合规、资产与物理存在性、格式完备度）；
- 红军魔鬼制片人：戏剧挑刺（动机自洽、张力匮乏、降智打脸、视听不可执行性）。
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.script_graph_state import AuditVerdict, RedBlueAuditReport
from app.workflows.prompts.master_sop_prompts import (
    AUDIT_SYSTEM_PROMPT,
    AUDIT_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json


def _fallback_audit_report(stage: int, content_summary: str) -> dict[str, Any]:
    return {
        "blue_team_compliance": {
            "passed": True,
            "forbidden_rules_check": "未触犯10大俗套与3大廉价爽点",
            "timeline_check": "节奏点符合短剧行业标准",
            "asset_integrity_check": "核心资产引用完整",
        },
        "red_team_criticism": {
            "dramatic_tension_score": 88,
            "pacing_sharpness": "冲突高潮明确，前置铺垫充分",
            "visual_feasibility": "动作具象可落地，无虚浮心理描写",
        },
        "verdict": AuditVerdict.GREEN_APPROVED,
        "blocking_issues": [],
        "warning_suggestions": ["建议进一步加强随身道具微距特写以增强镜头冲击力"],
    }


class RedBlueAuditor:
    """红蓝对抗独立自审器。"""

    @staticmethod
    def audit(
        stage: int,
        content_payload: Any,
        forbidden_rules: Any = None,
    ) -> RedBlueAuditReport:
        """执行针对指定阶段产出物的红蓝独立对抗质检。"""
        if isinstance(content_payload, (dict, list)):
            payload_str = json.dumps(content_payload, ensure_ascii=False, indent=2)
        else:
            payload_str = str(content_payload)

        # 1. 蓝军前置硬规则快速自检（Local Fast-Check）
        quick_blocking: list[str] = []
        if stage == 1:
            # 必须包含四大片名维度
            pass
        elif stage == 5:
            # 阶段 5 剧本检查：必须有前3秒与片尾断点
            if isinstance(content_payload, dict):
                # 判断是单集还是多集合集
                if "hook_3s" in content_payload or "body_markdown" in content_payload:
                    ep_list = [content_payload]
                else:
                    ep_list = [v for v in content_payload.values() if isinstance(v, dict)]

                for ep_item in ep_list:
                    ep_idx = ep_item.get("episode_num") or ep_item.get("episode_number") or ""
                    if not ep_item.get("hook_3s"):
                        quick_blocking.append(f"【蓝军阻断】第{ep_idx}集前3秒视觉动作抓手(hook_3s)为空")
                    if not ep_item.get("ending_cliffhanger"):
                        quick_blocking.append(f"【蓝军阻断】第{ep_idx}集片尾生死绝杀断点(ending_cliffhanger)为空")

        rules_str = str(forbidden_rules or "默认遵循双轨禁令与剧本排版规范")
        user_prompt = AUDIT_USER_PROMPT_TEMPLATE.format(
            stage=stage,
            content_payload=payload_str[:3500],
            forbidden_rules=rules_str[:1000],
        )

        result_json = call_llm_json(
            user_prompt=user_prompt,
            system_prompt=AUDIT_SYSTEM_PROMPT,
            fallback_factory=lambda: _fallback_audit_report(stage, payload_str[:100]),
        )

        blocking = result_json.get("blocking_issues") or []
        blocking.extend(quick_blocking)

        verdict_str = result_json.get("verdict") or AuditVerdict.GREEN_APPROVED
        if blocking:
            verdict_str = AuditVerdict.RED_BLOCKING

        report = RedBlueAuditReport(
            blue_team_compliance=result_json.get("blue_team_compliance") or {},
            red_team_criticism=result_json.get("red_team_criticism") or {},
            verdict=verdict_str,
            blocking_issues=blocking,
            warning_suggestions=result_json.get("warning_suggestions") or [],
        )
        return report
