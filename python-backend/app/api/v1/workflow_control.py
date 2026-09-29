"""工作流人工干预、审核与时光倒流控制 REST API 路由。

严格对齐《两程九阶架构方案》第 7 节 RESTful API 完整规范：
1.  GET  /pending-review                           获取当前挂起审核上下文 (波次/单集/自审报告)
2.  POST /stage5/wave/approve                     阶段五波次审核放行
3.  POST /stage5/wave/update-and-resume           阶段五波次剧本修改并继续
4.  POST /stage5/wave/rerun                       阶段五波次剧本重跑 (策略 A 时光倒流)
5.  POST /episodes/{episode_number}/approve       第二程单集视听工程审核通过
6.  POST /episodes/{episode_number}/update-and-resume 第二程单集分镜/音频在线修改并继续
7.  POST /episodes/{episode_number}/rerun         第二程单集独立重跑 (Stage 6/7/8)
8.  POST /resume                                  通用阶段审核放行 (Stage 1~4, Gatekeeper)
9.  POST /rerun-stage                             第一程阶段级时光倒流重跑
10. POST /pause & /retry                          紧急人工暂停 / 异常故障重试

以及通用辅助端点：
- GET  /status       查询当前工作流运行/挂起状态
- GET  /checkpoints  查询短剧检查点历史列表
- POST /approve      通用审核放行
- POST /time-travel  通用时光倒流分支派生
"""
from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.response import success
from app.db.session import get_db, session_scope
from app.services.checkpoint_index_service import (
    get_latest_active_checkpoint,
    list_drama_checkpoints,
    mark_checkpoint_ready,
    cascade_invalidate_downstream_business_records,
)
from app.services.workflow_lock_service import (
    workflow_lock_context,
    set_pause_flag,
    clear_pause_flag,
    is_pause_flag_set,
)
from app.services.workflow_time_travel_service import (
    approve_human_review,
    confirm_gatekeeper_and_lock,
    get_workflow_state_snapshot,
    resume_workflow,
    time_travel_and_fork,
)

logger = get_logger("lmd.api.workflow_control")

router = APIRouter(prefix="/dramas/{drama_id}/workflow", tags=["Workflow Control & Time Travel"])


# =========================================================================
# 请求模型定义 (全面覆盖方案第 7 节规范，采用 ConfigDict(extra="allow") 防御前端任意字段)
# =========================================================================

class WorkflowApproveRequest(BaseModel):
    """通用人工审核放行请求体。"""
    model_config = ConfigDict(extra="allow")

    stage: int | str | None = Field(default=None, description="指定放行阶段编号 (1~8 或 'stage1'~'stage8')")
    checkpoint_id: str | None = Field(default=None, description="可选特定检查点 ID，不传默认取当前最新活跃挂起点")
    comment: str | None = Field(default=None, description="审核批注 (兼容 comment 别名)")
    human_feedback: str | None = Field(default=None, description="人工审核批注/反馈说明")
    feedback: str | None = Field(default=None, description="兼容 feedback 别名")
    operator: str = Field(default="user", description="审批操作人")
    approved: bool = Field(default=True, description="是否审核通过")
    human_override_state: dict[str, Any] | None = Field(
        default=None,
        description="人工微调覆写数据字典 (例如在前端修改后的人设、大纲或分镜参数)"
    )
    auto_resume: bool = Field(default=True, description="审核放行后是否立即自动推进下一阶段")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="执行控制模式：stage_by_stage(单步精细)/two_journey(双程总控)/full_auto(全自动极速)"
    )


class GatekeeperConfirmRequest(BaseModel):
    """两程定稿总门禁确认请求体。"""
    model_config = ConfigDict(extra="allow")

    operator: str = Field(default="user", description="审批操作人姓名或标识")
    human_feedback: str | None = Field(default=None, description="全季文学剧本终审定稿批注与指导说明")
    comment: str | None = Field(default=None, description="审核批注 (兼容 comment 别名)")
    feedback: str | None = Field(default=None, description="兼容 feedback 别名")
    approved: bool = Field(default=True, description="是否审核通过")
    auto_resume: bool = Field(default=True, description="定稿锁本后是否立即自动推进至第二程视听工程")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="执行控制模式：stage_by_stage/two_journey/full_auto"
    )


class WorkflowTimeTravelRequest(BaseModel):
    """通用时光倒流与分支派生请求体。"""
    model_config = ConfigDict(extra="allow")

    target_stage: str | None = Field(
        default=None,
        description="目标回溯阶段 (如 'stage1', 'stage2'... 'stage8')"
    )
    target_episode: int | None = Field(
        default=None,
        description="目标回溯集数 (第二程单集视听工程回溯，>=1)"
    )
    target_checkpoint_id: str | None = Field(
        default=None,
        description="精确指定的历史检查点 ID (若提供则最高优先级定位)"
    )
    human_override_state: dict[str, Any] | None = Field(
        default=None,
        description="人工在回溯节点注入的覆写状态字典"
    )
    as_node: str | None = Field(
        default=None,
        description="声明本次 update_state 以哪个节点身份写入 (可选)"
    )
    auto_resume: bool = Field(
        default=True,
        description="分支派生后是否立即自动从新分支恢复向下执行"
    )
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="执行控制模式"
    )


class WorkflowResumeRequest(BaseModel):
    """手动恢复执行请求体 (通用/阶段放行)。"""
    model_config = ConfigDict(extra="allow")

    stage: int | None = Field(default=None, description="审核放行的阶段 (1~4 或 Gatekeeper)")
    comment: str | None = Field(default=None, description="放行批注")
    human_feedback: str | None = Field(default=None, description="兼容 human_feedback 别名")
    feedback: str | None = Field(default=None, description="兼容 feedback 别名")
    operator: str = Field(default="user", description="审批操作人")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="恢复执行控制模式"
    )


class Stage5WaveApproveRequest(BaseModel):
    """阶段五波次审核放行请求体 (方案 7.2.2)。"""
    model_config = ConfigDict(extra="allow")

    wave_index: int | None = Field(default=None, description="当前审核通过的波次编号")
    wave_number: int | None = Field(default=None, description="兼容 wave_number 别名")
    approved_episodes: list[int] = Field(default_factory=list, description="本波次通过的集数列表")
    comment: str = Field(default="", description="审核批注")
    human_feedback: str | None = Field(default=None, description="兼容 human_feedback 别名")
    feedback: str | None = Field(default=None, description="兼容 feedback 别名")
    auto_resume: bool = Field(default=True, description="是否立即恢复并执行下一波次")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="stage_by_stage",
        description="运行模式 (强干预推荐 stage_by_stage)"
    )


class Stage5WaveUpdateAndResumeRequest(BaseModel):
    """阶段五波次人工修改并继续请求体 (方案 7.2.3)。"""
    model_config = ConfigDict(extra="allow")

    wave_index: int | None = Field(default=None, description="波次编号")
    wave_number: int | None = Field(default=None, description="兼容 wave_number 别名")
    episodes_patch: dict[str, Any] | list[Any] = Field(default_factory=dict, description="剧本修改补丁")
    modified_screenplays: list[Any] | None = Field(default=None, description="兼容 modified_screenplays 别名")
    continue_next_wave: bool = Field(default=True, description="是否立即恢复并执行下一波次")
    auto_resume: bool = Field(default=True, description="兼容 auto_resume 别名")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="stage_by_stage",
        description="运行模式"
    )


class Stage5WaveRerunRequest(BaseModel):
    """阶段五波次重跑请求体 (方案 7.2.4)。"""
    model_config = ConfigDict(extra="allow")

    wave_index: int | None = Field(default=None, description="需重跑的波次编号")
    wave_number: int | None = Field(default=None, description="兼容 wave_number 别名")
    human_guidance: str = Field(default="", description="人工针对本波次的重跑指导意见")
    human_instructions: str | None = Field(default=None, description="兼容 human_instructions 别名")
    auto_resume: bool = Field(default=True, description="重跑派生后是否立即恢复")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="stage_by_stage",
        description="运行模式"
    )


class EpisodeApproveRequest(BaseModel):
    """第二程单集审核通过请求体 (方案 7.2.5)。"""
    model_config = ConfigDict(extra="allow")

    episode_number: int | None = Field(default=None, description="审核通过的集数")
    comment: str = Field(default="", description="审核批注")
    human_feedback: str | None = Field(default=None, description="兼容 human_feedback 别名")
    feedback: str | None = Field(default=None, description="兼容 feedback 别名")
    auto_resume: bool = Field(default=True, description="审核放行后是否自动推进")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="运行模式"
    )


class EpisodeUpdateAndResumeRequest(BaseModel):
    """第二程单集分镜/音频修改并继续请求体 (方案 7.2.6)。"""
    model_config = ConfigDict(extra="allow")

    episode_number: int | None = Field(default=None, description="集数")
    storyboards_patch: list[dict[str, Any]] = Field(default_factory=list, description="分镜修改列表")
    audio_patch: dict[str, Any] = Field(default_factory=dict, description="音频参数修改")
    modified_screenplay: dict[str, Any] | None = Field(default=None, description="兼容单集剧本修改")
    continue_next_episode: bool = Field(default=True, description="是否继续下一集")
    auto_resume: bool = Field(default=True, description="兼容 auto_resume 别名")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="运行模式"
    )


class EpisodeRerunRequest(BaseModel):
    """第二程单集独立重跑请求体 (方案 7.2.7)。"""
    model_config = ConfigDict(extra="allow")

    episode_number: int | None = Field(default=None, description="需重跑的集数")
    from_stage: int = Field(default=7, description="从哪一阶段开始重跑 (6 资产, 7 分镜, 8 音频)")
    human_guidance: str = Field(default="", description="重跑指导意见")
    human_instructions: str | None = Field(default=None, description="兼容指导意见别名")
    auto_resume: bool = Field(default=True, description="重跑派生后是否立即恢复")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="运行模式"
    )


class WorkflowRerunStageRequest(BaseModel):
    """第一程阶段级时光倒流重跑请求体 (方案 7.2.9)。"""
    model_config = ConfigDict(extra="allow")

    target_stage: int | str = Field(..., description="目标重跑阶段 (1~8 或 'stage1'~'stage8')")
    human_guidance: str = Field(default="", description="人工针对该阶段的修改指导意见")
    human_feedback: str | None = Field(default=None, description="兼容 human_feedback 别名")
    comment: str | None = Field(default=None, description="兼容 comment 别名")
    feedback: str | None = Field(default=None, description="兼容 feedback 别名")
    override_payload: dict[str, Any] | None = Field(default=None, description="附加覆写数据")
    auto_resume: bool = Field(default=True, description="重跑派生后是否立即恢复")
    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="执行控制模式"
    )


class WorkflowPauseRequest(BaseModel):
    """紧急人工暂停请求体 (方案 7.2.10)。"""
    model_config = ConfigDict(extra="allow")

    comment: str = Field(default="人工紧急暂停", description="暂停原因")
    reason: str | None = Field(default=None, description="兼容 reason 别名")


class WorkflowRetryRequest(BaseModel):
    """异常故障重试请求体 (方案 7.2.10)。"""
    model_config = ConfigDict(extra="allow")

    run_mode: Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default="two_journey",
        description="恢复执行控制模式"
    )


# =========================================================================
# 路由端点实现 (方案第 7 节 10 大核心端点)
# =========================================================================

@router.get(
    "/pending-review",
    summary="获取当前挂起审核上下文快照",
    description=(
        "**【两程九阶架构接口 1】**\n\n"
        "获取当前短剧工作流在状态机挂起时（HITL 阶段审核或 Gatekeeper 两程总门禁）的详细上下文快照。\n\n"
        "**核心功能：**\n"
        "- **阶段与节点定位**：返回当前阶数（`current_stage`）、挂起节点（`suspended_node`）及活跃检查点 ID；\n"
        "- **审核类型智能标识**：通过 `review_type` 精确区分阶段级审批（`STAGE_HITL`）与全季定稿门禁（`TWO_JOURNEY_GATEKEEPER`）；\n"
        "- **动态业务载荷**：Stage 5 返回波次信息（`wave_info`），Stage 6~8 返回单集视听进展（`episode_info`），附带质检自审报告与数据预览；\n"
        "- **操作指引**：返回当前状态下前端允许调用的合法操作集合 `allowed_actions`。"
    ),
    response_description="挂起上下文快照、自审报告、业务数据预览与允许操作集合",
)
def get_pending_review(drama_id: str):
    """【接口 1】获取当前挂起审核上下文 (GET /pending-review)。
    
    读取挂起节点快照，组装待审数据、波次信息、单集信息、自审报告与允许的操作列表。

    Args:
        drama_id: 短剧项目唯一标识 (例如 '7' 或数字 ID)

    Returns:
        包含 current_stage, review_type, suspended_node, wave_info, episode_info,
        audit_report, pending_items, allowed_actions 的结构化字典。
    """
    logger.debug(f"[API] 获取待审核上下文: drama_id={drama_id}")
    snapshot = get_workflow_state_snapshot(drama_id=drama_id)
    if not snapshot["exists"]:
        return success({
            "drama_id": drama_id,
            "status": "not_started",
            "is_waiting_review": False,
            "message": "工作流尚未启动",
        })

    values = snapshot.get("values") or {}
    current_stage = values.get("current_stage", 1)
    next_nodes = snapshot.get("next_nodes") or []
    suspended_node = next_nodes[0] if next_nodes else ""
    checkpoint_id = snapshot.get("checkpoint_id", "")

    # 提取波次信息 (Stage 5)
    completed_screenplays = values.get("completed_screenplays") or {}
    total_episodes = values.get("total_episodes", 80)
    total_completed = len(completed_screenplays)
    wave_info = None
    if current_stage == 5 or suspended_node == "audit_stage5":
        wave_size = 5
        current_wave = max(1, (total_completed + wave_size - 1) // wave_size) if total_completed > 0 else 1
        total_waves = max(1, (total_episodes + wave_size - 1) // wave_size)
        start_ep = (current_wave - 1) * wave_size + 1
        end_ep = min(start_ep + wave_size - 1, total_episodes)
        wave_info = {
            "current_wave": current_wave,
            "total_waves": total_waves,
            "episodes_in_wave": list(range(start_ep, end_ep + 1)),
            "total_completed_episodes": total_completed,
            "total_episodes": total_episodes,
        }

    # 提取单集信息 (Stage 6~8)
    episode_info = None
    if current_stage >= 6:
        episode_info = {
            "current_episode_number": values.get("current_episode_number", 1),
            "total_episodes": total_episodes,
            "has_storyboards": bool(values.get("storyboards")),
            "has_audio": bool(values.get("audio_mastering")),
        }

    # 提取自审报告
    latest_audit = values.get("latest_audit") or {}
    if hasattr(latest_audit, "model_dump"):
        latest_audit = latest_audit.model_dump()
    audit_report = {
        "verdict": latest_audit.get("verdict", "BLUE_PASS"),
        "score": latest_audit.get("score", 90.0),
        "suggestions": latest_audit.get("suggestions", []),
        "red_flag_triggered": values.get("red_flag_triggered", False),
    }

    # 载荷预览
    payload_preview: dict[str, Any] = {}
    if current_stage == 5:
        payload_preview["episodes"] = {
            k: {
                "title": v.get("title", f"第{k}集"),
                "scenes_count": len(v.get("scenes", [])) if isinstance(v.get("scenes"), list) else 0,
                "word_count": len(str(v.get("full_screenplay_text", ""))),
            }
            for k, v in list(completed_screenplays.items())[-5:]
            if isinstance(v, dict)
        }
    elif current_stage >= 6:
        payload_preview["storyboards_count"] = len(values.get("storyboards") or [])
        payload_preview["audio_stems"] = list((values.get("audio_mastering") or {}).keys())
    elif current_stage == 1:
        payload_preview["ideation"] = values.get("story_ideation")
    elif current_stage == 2:
        payload_preview["characters_count"] = len(values.get("characters_engine") or [])
    elif current_stage == 3:
        payload_preview["environments_count"] = len((values.get("environments_and_props") or {}).get("environments", []))
    elif current_stage == 4:
        payload_preview["season_outlines_count"] = len(values.get("season_outlines") or [])

    # 审查类型与允许的操作集合（明确区分阶段级审批 Stage HITL 与全季定稿总门禁 Two-Journey Gatekeeper）
    is_at_gatekeeper = suspended_node == "gatekeeper" or (
        current_stage == 5 and total_completed >= total_episodes
    )
    if is_at_gatekeeper:
        review_type = "TWO_JOURNEY_GATEKEEPER"
        stage_name = "两程定稿总门禁 (Gatekeeper)"
        allowed_actions = ["confirm_gatekeeper", "update_and_resume", "rerun_wave", "rerun_stage"]
    elif current_stage == 5:
        review_type = "STAGE_HITL"
        stage_name = f"阶段五：剧本分集编写 (第{wave_info.get('current_wave', 1) if wave_info else 1}波次)"
        allowed_actions = ["approve", "update_and_resume", "rerun_wave"]
    elif current_stage >= 6:
        review_type = "STAGE_HITL"
        stage_name = f"第二程单集视听工程 (第{values.get('current_episode_number', 1)}集)"
        allowed_actions = ["approve", "update_and_resume", "rerun_episode"]
    else:
        stage_names_map = {
            1: "阶段一：概念定位与核心叙事",
            2: "阶段二：人物小传与角色引擎",
            3: "阶段三：场景资产与道具系统",
            4: "阶段四：全季大纲与节奏切片",
        }
        review_type = "STAGE_HITL"
        stage_name = stage_names_map.get(current_stage, f"阶段{current_stage}")
        allowed_actions = ["approve", "update_and_resume", "rerun_stage"]

    return success({
        "drama_id": drama_id,
        "run_mode": values.get("run_mode", "two_journey"),
        "current_stage": current_stage,
        "stage_name": stage_name,
        "review_type": review_type,
        "is_at_gatekeeper": is_at_gatekeeper,
        "suspended_node": suspended_node,
        "checkpoint_id": checkpoint_id,
        "is_waiting_review": snapshot.get("is_waiting_review", True),
        "wave_info": wave_info,
        "episode_info": episode_info,
        "audit_report": audit_report,
        "payload_preview": payload_preview,
        "pending_items": payload_preview,
        "allowed_actions": allowed_actions,
    })


@router.post(
    "/stage5/wave/approve",
    summary="阶段五分批剧本波次审核放行",
    description=(
        "**【两程九阶架构接口 2】**\n\n"
        "在阶段五（分集剧本撰写与滚动质检）中，对当前已完成生成的波次（如 1~5 集、6~10 集等）进行人工审核放行。\n\n"
        "**业务流转：**\n"
        "- 获取分布式互斥锁，防止并发重入；\n"
        "- 调用 `approve_human_review(stage=5)` 将阶段五审核标记记录到 `stage_approvals['stage5'] = True`；\n"
        "- 若 `auto_resume=True`，自动触发状态机恢复执行推进至下一波次（或全波次完成进入全季总门禁 Gatekeeper）；\n"
        "- 返回放行结果及当前已放行波次编号与集数清单。"
    ),
    response_description="波次放行状态、通过波次编号与已审批集数列表",
)
def approve_stage5_wave(
    drama_id: str,
    req: Stage5WaveApproveRequest,
):
    """【接口 2】阶段五波次审核放行 (POST /stage5/wave/approve)。
    
    1. 获取分布式锁；
    2. 调用 approve_human_review 注入阶段五白名单放行与自审合格报告；
    3. 触发恢复执行下一波次。

    Args:
        drama_id: 短剧项目唯一标识
        req: 包含波次序号、已批准集数、审批批注及自动推进标识

    Returns:
        包含 approved_wave, approved_episodes, checkpoint_id, status 的响应字典
    """
    wave_idx = req.wave_index or req.wave_number or 1
    logger.info(f"[API] 阶段五波次审核通过: drama_id={drama_id}, wave={wave_idx}, comment={req.comment}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        res = approve_human_review(
            drama_id=drama_id,
            stage=5,
            human_feedback=req.comment or f"阶段五第{wave_idx}波次审核放行",
            auto_resume=req.auto_resume,
            run_mode=req.run_mode,
        )
        res["wave_number"] = wave_idx
        res["approved_wave"] = wave_idx
        res["approved_episodes"] = req.approved_episodes
        return success(res)


@router.post(
    "/stage5/wave/update-and-resume",
    summary="阶段五分批剧本在线修改并继续",
    description=(
        "**【两程九阶架构接口 3】**\n\n"
        "人工在线润色或修正当前波次生成的剧本分集内容后，将修正数据持久化回状态机并继续推进工作流。\n\n"
        "**业务流转：**\n"
        "- 获取分布式互斥锁并读取当前检查点快照；\n"
        "- 将前端传入的剧本修改补丁（`modified_screenplays` 或 `episodes_patch`）深度合并至 `completed_screenplays`；\n"
        "- 执行时光倒流与分支派生（`time_travel_and_fork`），在当前检查点处派生带修正内容的新版本检查点；\n"
        "- 若 `continue_next_wave=True` 且 `auto_resume=True`，自动唤醒状态机生成后续波次剧本。"
    ),
    response_description="分支派生结果、新检查点 ID 及后续执行恢复详情",
)
def update_and_resume_stage5_wave(
    drama_id: str,
    req: Stage5WaveUpdateAndResumeRequest,
):
    """【接口 3】阶段五波次人工修改并继续 (POST /stage5/wave/update-and-resume)。
    
    1. 获取分布式锁；
    2. 加载当前快照，将修改后的剧本补丁合并至 completed_screenplays；
    3. 调用 graph.update_state 派生新快照并标记就绪；
    4. 若 continue_next_wave=true 则恢复推进下一波次。

    Args:
        drama_id: 短剧项目唯一标识
        req: 包含修改后的剧本数据、波次编号、自动恢复与继续推进控制项

    Returns:
        包含新 checkpoint_id, fork_from, resume_result 的分支派生快照字典
    """
    wave_idx = req.wave_index or req.wave_number or 1
    logger.info(f"[API] 阶段五波次修改并继续: drama_id={drama_id}, wave={wave_idx}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        snapshot = get_workflow_state_snapshot(drama_id=drama_id)
        if not snapshot["exists"]:
            raise HTTPException(status_code=400, detail="未找到工作流快照")

        values = snapshot.get("values") or {}
        completed_screenplays = dict(values.get("completed_screenplays") or {})
        
        # 合并补丁 (兼容 dict 与 list[dict])
        if req.modified_screenplays and isinstance(req.modified_screenplays, list):
            for item in req.modified_screenplays:
                if isinstance(item, dict) and "episode_number" in item:
                    ep_key = str(item["episode_number"])
                    if ep_key in completed_screenplays:
                        completed_screenplays[ep_key].update(item)
                    else:
                        completed_screenplays[ep_key] = item
        elif isinstance(req.episodes_patch, dict):
            for ep_key, ep_data in req.episodes_patch.items():
                if ep_key in completed_screenplays:
                    completed_screenplays[ep_key].update(ep_data)
                else:
                    completed_screenplays[ep_key] = ep_data
        elif isinstance(req.episodes_patch, list):
            for item in req.episodes_patch:
                if isinstance(item, dict) and "episode_number" in item:
                    ep_key = str(item["episode_number"])
                    if ep_key in completed_screenplays:
                        completed_screenplays[ep_key].update(item)
                    else:
                        completed_screenplays[ep_key] = item

        fork_res = time_travel_and_fork(
            drama_id=drama_id,
            target_checkpoint_id=snapshot.get("checkpoint_id"),
            human_override_state={"completed_screenplays": completed_screenplays},
            as_node="audit_stage5",
            run_mode=req.run_mode,
        )

        should_resume = req.continue_next_wave and req.auto_resume
        if should_resume:
            resume_res = resume_workflow(drama_id=drama_id, run_mode=req.run_mode)
            fork_res["resume_result"] = resume_res

        fork_res["wave_number"] = wave_idx
        return success(fork_res)


@router.post(
    "/stage5/wave/rerun",
    summary="阶段五分批剧本波次时光倒流重跑",
    description=(
        "**【两程九阶架构接口 4】**\n\n"
        "当当前波次的剧本生成质量不达标时，丢弃本波次及后续脏数据，附带编剧人工指导指令并回溯重跑。\n\n"
        "**业务流转：**\n"
        "- 根据波次序号定位基准快照（第 1 波次回溯至 Stage 4 分集大纲合格检查点，第 2+ 波次回溯至上一波次合格检查点）；\n"
        "- 剔除状态机 `completed_screenplays` 中本波次及以后的集数数据；\n"
        "- 注入人工引导提示词 `human_guidance_for_stage5`，派生新分支检查点；\n"
        "- 若 `auto_resume=True`，状态机以全新提示词指导重新生成当前波次剧本。"
    ),
    response_description="重跑分支派生详情、基准检查点与恢复状态",
)
def rerun_stage5_wave(
    drama_id: str,
    req: Stage5WaveRerunRequest,
):
    """【接口 4】阶段五波次重跑 (POST /stage5/wave/rerun)。
    
    1. 定位上一波次或 Stage 4 终态合格快照；
    2. 剔除本波次已生成剧本，注入 human_guidance_for_stage5；
    3. 派生新分支并恢复执行。

    Args:
        drama_id: 短剧项目唯一标识
        req: 包含波次序号、人工重跑指导词及执行模式

    Returns:
        包含重跑派生检查点与执行恢复信息的字典
    """
    wave_idx = req.wave_index or req.wave_number or 1
    guidance = req.human_guidance or req.human_instructions or ""
    logger.info(f"[API] 阶段五波次重跑: drama_id={drama_id}, wave={wave_idx}, guidance={guidance}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        with session_scope() as db:
            # 若第一波次重跑，回溯到 stage4
            target_stage = "stage4" if wave_idx <= 1 else "stage5"
            anchor = get_latest_active_checkpoint(db, drama_id, stage=target_stage)
            if not anchor:
                anchor = get_latest_active_checkpoint(db, drama_id)
            if not anchor:
                raise HTTPException(status_code=400, detail=f"未找到重跑波次所需的基准检查点 ({target_stage})")

        snapshot = get_workflow_state_snapshot(drama_id=drama_id)
        values = (snapshot.get("values") or {}) if snapshot["exists"] else {}
        completed_screenplays = dict(values.get("completed_screenplays") or {})

        # 剔除本波次及以后的剧本
        wave_size = 5
        start_ep_to_remove = (wave_idx - 1) * wave_size + 1
        filtered_screenplays = {
            k: v for k, v in completed_screenplays.items()
            if int(k) < start_ep_to_remove
        }

        override_state = {
            "completed_screenplays": filtered_screenplays,
            "human_guidance_for_stage5": guidance,
            "current_stage": 5,
        }

        fork_res = time_travel_and_fork(
            drama_id=drama_id,
            target_checkpoint_id=anchor["checkpoint_id"],
            human_override_state=override_state,
            as_node="audit_stage4" if wave_idx <= 1 else "audit_stage5",
            run_mode=req.run_mode,
        )

        if req.auto_resume:
            resume_res = resume_workflow(drama_id=drama_id, run_mode=req.run_mode)
            fork_res["resume_result"] = resume_res

        fork_res["wave_number"] = wave_idx
        return success(fork_res)


@router.post(
    "/episodes/{episode_number}/approve",
    summary="第二程单集视听工程审核放行",
    description=(
        "**【两程九阶架构接口 5】**\n\n"
        "第二程视听工业化工程按集串行推进。当某集完成分镜设计（Stage 7）及全息混音（Stage 8）后，通过此接口完成人工审片放行。\n\n"
        "**业务流转：**\n"
        "- 获取分布式互斥锁并定位该集最新的活跃检查点；\n"
        "- 将检查点状态更新为 `HUMAN_APPROVED` 并标记就绪（`is_ready=1`）；\n"
        "- 调用 `approve_human_review` 将对应阶段放行记录写入状态机；\n"
        "- 若 `auto_resume=True`，自动触发图执行推进至下一集（直至最后一集完成）。"
    ),
    response_description="单集放行状态、已批准集数与恢复执行信息",
)
def approve_episode(
    drama_id: str,
    episode_number: int,
    req: EpisodeApproveRequest = EpisodeApproveRequest(),
):
    """【接口 5】第二程单集视听工程审核通过 (POST /episodes/{episode_number}/approve)。
    
    1. 标记单集检查点就绪与 HUMAN_APPROVED；
    2. 调用 approve_human_review 写入状态并恢复执行下一集。

    Args:
        drama_id: 短剧项目唯一标识
        episode_number: 路径中的目标集数 (从 1 开始)
        req: 审批请求体 (含审批意见、自动恢复标记等)

    Returns:
        包含 approved_episode, episode_number, status 的确认信息字典
    """
    ep_num = req.episode_number or episode_number
    logger.info(f"[API] 第二程单集审核放行: drama_id={drama_id}, ep={ep_num}, comment={req.comment}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        with session_scope() as db:
            active_ckpt = get_latest_active_checkpoint(db, drama_id, episode_number=ep_num)
            if not active_ckpt:
                active_ckpt = get_latest_active_checkpoint(db, drama_id)
            if not active_ckpt:
                raise HTTPException(status_code=400, detail="未找到活跃检查点")

            mark_checkpoint_ready(
                db, drama_id, active_ckpt["checkpoint_id"], is_ready=1, audit_verdict="HUMAN_APPROVED"
            )

        # 确定当前阶数（默认为当前检查点阶段或Stage 6）
        stage_num = 6
        if active_ckpt and active_ckpt.get("stage_name"):
            st_str = active_ckpt["stage_name"].replace("stage", "")
            if st_str.isdigit():
                stage_num = int(st_str)

        res = approve_human_review(
            drama_id=drama_id,
            stage=stage_num,
            human_feedback=req.comment or f"第{ep_num}集审核放行",
            auto_resume=req.auto_resume,
            run_mode=req.run_mode,
        )
        res["episode_number"] = ep_num
        res["approved_episode"] = ep_num
        return success(res)


@router.post(
    "/episodes/{episode_number}/update-and-resume",
    summary="第二程单集分镜与音频在线修改并继续",
    description=(
        "**【两程九阶架构接口 6】**\n\n"
        "导演或后期制作人员在线调整指定单集的镜头提示词、机位参数、镜头时长或音频母带配置后提交并恢复工作流。\n\n"
        "**业务流转：**\n"
        "- 获取分布式互斥锁并读取当前检查点快照；\n"
        "- 合并分镜镜头补丁（`storyboards_patch`）、音频母带补丁（`audio_patch`）或微调剧本（`modified_screenplay`）；\n"
        "- 执行时光倒流分支派生（`time_travel_and_fork`），将覆盖状态写入检查点；\n"
        "- 若 `continue_next_episode=True` 且 `auto_resume=True`，状态机恢复执行并流转进入下一集的视听制作。"
    ),
    response_description="修改派生快照详情、检查点 ID 及执行流转状态",
)
def update_and_resume_episode(
    drama_id: str,
    episode_number: int,
    req: EpisodeUpdateAndResumeRequest,
):
    """【接口 6】第二程单集分镜/音频在线修改并继续 (POST /episodes/{episode_number}/update-and-resume)。

    Args:
        drama_id: 短剧项目唯一标识
        episode_number: 路径中的目标集数
        req: 包含分镜补丁、音频母带补丁、剧本更新与推进控制项

    Returns:
        包含新 checkpoint_id, fork_from, resume_result 的分支派生结果字典
    """
    ep_num = req.episode_number or episode_number
    logger.info(f"[API] 第二程单集修改并继续: drama_id={drama_id}, ep={ep_num}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        snapshot = get_workflow_state_snapshot(drama_id=drama_id)
        if not snapshot["exists"]:
            raise HTTPException(status_code=400, detail="未找到工作流快照")

        override_state: dict[str, Any] = {}
        if req.storyboards_patch:
            override_state["storyboards"] = req.storyboards_patch
        if req.audio_patch:
            override_state["audio_mastering"] = req.audio_patch
        if req.modified_screenplay:
            values = snapshot.get("values") or {}
            completed = dict(values.get("completed_screenplays") or {})
            ep_key = str(ep_num)
            if ep_key in completed:
                completed[ep_key].update(req.modified_screenplay)
            else:
                completed[ep_key] = req.modified_screenplay
            override_state["completed_screenplays"] = completed

        fork_res = time_travel_and_fork(
            drama_id=drama_id,
            target_checkpoint_id=snapshot.get("checkpoint_id"),
            human_override_state=override_state,
            as_node="stage8_audio_mastering",
            run_mode=req.run_mode,
        )

        should_resume = req.continue_next_episode and req.auto_resume
        if should_resume:
            resume_res = resume_workflow(drama_id=drama_id, run_mode=req.run_mode)
            fork_res["resume_result"] = resume_res

        fork_res["episode_number"] = ep_num
        return success(fork_res)


@router.post(
    "/episodes/{episode_number}/rerun",
    summary="第二程单集视听工程独立重跑",
    description=(
        "**【两程九阶架构接口 7】**\n\n"
        "第二程单集级故障隔离重跑机制。仅针对指定单集的视听工程（Stage 6 资产匹配 / Stage 7 分镜生成 / Stage 8 音频母带）进行重新生成，完全不影响其他已完成单集。\n\n"
        "**业务流转：**\n"
        "- 定位指定单集的前置阶段合格快照作为基准锚点；\n"
        "- 清空该单集的分镜及音频脏数据，注入人工调整建议 `human_guidance_for_stage7`；\n"
        "- 派生独立重跑分支，若 `auto_resume=True` 则立即异步唤醒该集重新生成。"
    ),
    response_description="单集重跑分支快照、目标集数与恢复信息",
)
def rerun_episode(
    drama_id: str,
    episode_number: int,
    req: EpisodeRerunRequest,
):
    """【接口 7】第二程单集独立重跑 (POST /episodes/{episode_number}/rerun)。
    
    仅重新生成指定单集的 Stage 6/7/8，不影响其他集。

    Args:
        drama_id: 短剧项目唯一标识
        episode_number: 路径中的目标集数
        req: 包含起始重跑阶数 (6, 7, 或 8)、人工指导词及执行模式

    Returns:
        包含重跑检查点快照与恢复执行信息的字典
    """
    ep_num = req.episode_number or episode_number
    guidance = req.human_guidance or req.human_instructions or ""
    logger.info(
        f"[API] 第二程单集独立重跑: drama_id={drama_id}, ep={ep_num}, "
        f"from_stage={req.from_stage}, guidance={guidance}"
    )
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        parent_stage_num = max(6, req.from_stage - 1)
        parent_stage = f"stage{parent_stage_num}"

        with session_scope() as db:
            anchor = get_latest_active_checkpoint(
                db, drama_id, stage=parent_stage, episode_number=ep_num
            )
            if not anchor:
                anchor = get_latest_active_checkpoint(db, drama_id, stage=parent_stage)
            if not anchor:
                anchor = get_latest_active_checkpoint(db, drama_id)
            if not anchor:
                raise HTTPException(status_code=400, detail=f"未找到单集重跑所需的前置检查点 ({parent_stage})")

        override_state = {
            "current_episode_number": ep_num,
            "current_stage": req.from_stage,
            "storyboards": None,
            "audio_mastering": None,
            "human_guidance_for_stage7": guidance,
        }

        fork_res = time_travel_and_fork(
            drama_id=drama_id,
            target_checkpoint_id=anchor["checkpoint_id"],
            human_override_state=override_state,
            as_node=f"stage{parent_stage_num}",
            run_mode=req.run_mode,
        )

        if req.auto_resume:
            resume_res = resume_workflow(drama_id=drama_id, run_mode=req.run_mode)
            fork_res["resume_result"] = resume_res

        fork_res["target_episode"] = ep_num
        return success(fork_res)


@router.post(
    "/resume",
    summary="工作流通用恢复与放行 (智能防呆分流)",
    description=(
        "**【两程九阶架构接口 8】**\n\n"
        "通用工作流恢复与阶段审核放行端点，内置针对全季定稿门禁与阶段级自审的智能分流护栏机制：\n\n"
        "- **智能分流判定**：若未传入 `stage` 且当前挂起节点为 `gatekeeper`（或已完成 Stage 5），安全分流至 `confirm_gatekeeper_and_lock` 进行文学定稿锁定并激活第二程；\n"
        "- **阶段审核放行**：若处于各阶段自审拦截状态（Stage 1~5 或 Stage 6~8），分流至 `approve_human_review` 注入白名单放行标记并唤醒 LangGraph 状态机向下一阶段推进；\n"
        "- **防死锁与并发保护**：在分布式锁内原子执行，杜绝并发竞争。"
    ),
    response_description="恢复执行结果或门禁确认结果",
)
def resume_workflow_stage(
    drama_id: str,
    req: WorkflowResumeRequest,
):
    """【接口 8】通用阶段审核放行与恢复执行 (POST /resume)。
    
    适用场景：
    1. 若未传入 stage 且已处于 gatekeeper 门禁节点，安全分流到 confirm_gatekeeper_and_lock；
    2. 若处于普通阶段自审拦截或传入了 stage，调用 approve_human_review 进行白名单放行与恢复。

    Args:
        drama_id: 短剧项目唯一标识
        req: 包含目标阶段、操作人、批注反馈及执行模式

    Returns:
        状态机恢复执行或门禁锁定的响应数据字典
    """
    logger.info(f"[API] 收到通用恢复请求: drama_id={drama_id}, stage={req.stage}, run_mode={req.run_mode}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        # 检查当前状态机停顿位置与阶数
        target_stage = req.stage
        if target_stage is None:
            with session_scope() as db:
                active_ckpt = get_latest_active_checkpoint(db, drama_id)
                if active_ckpt and active_ckpt.get("stage_name"):
                    st_str = active_ckpt["stage_name"].replace("stage", "")
                    if st_str.isdigit():
                        target_stage = int(st_str)

        # 检查是否处于全季定稿门禁处
        snapshot = get_workflow_state_snapshot(drama_id=drama_id)
        next_nodes = snapshot.get("next_nodes") or []
        suspended_node = next_nodes[0] if next_nodes else ""
        values = snapshot.get("values") or {}
        current_stage = values.get("current_stage", target_stage or 1)

        if suspended_node == "gatekeeper" or (current_stage == 5 and target_stage is None):
            logger.info(f"[API] 检测到当前处于全季定稿总门禁，分流执行 confirm_gatekeeper_and_lock: drama_id={drama_id}")
            operator = getattr(req, "operator", "user") or "user"
            comment = (
                getattr(req, "comment", None)
                or getattr(req, "human_feedback", None)
                or getattr(req, "feedback", None)
            )
            try:
                res = confirm_gatekeeper_and_lock(
                    drama_id=drama_id,
                    human_feedback=comment,
                    operator=operator,
                    auto_resume=True,
                    run_mode=getattr(req, "run_mode", "two_journey"),
                )
                return success(res)
            except ValueError as ve:
                logger.warning(f"[API] 恢复门禁定稿校验未通过: {ve}")
                raise HTTPException(status_code=400, detail=str(ve))
            except Exception as e:
                logger.error(f"[API] 恢复门禁定稿执行失败: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        actual_stage = target_stage or current_stage or 1
        logger.info(f"[API] 分流执行阶段级审核放行: drama_id={drama_id}, stage={actual_stage}")
        comment = (
            getattr(req, "comment", None)
            or getattr(req, "human_feedback", None)
            or getattr(req, "feedback", None)
            or f"Stage {actual_stage} 通用放行"
        )
        try:
            res = approve_human_review(
                drama_id=drama_id,
                stage=actual_stage,
                human_feedback=comment,
                auto_resume=True,
                run_mode=getattr(req, "run_mode", "two_journey"),
            )
            return success(res)
        except ValueError as ve:
            logger.warning(f"[API] 恢复阶段审批参数或状态异常: {ve}")
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.error(f"[API] 恢复阶段审批执行失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/stages/{stage}/approve",
    summary="第一程阶段级显式审批放行 (Stage 1~5 HITL)",
    description=(
        "**【两程九阶架构阶段审批】**\n\n"
        "明确语义的阶段级人工审阅确认接口（区别于全季总门禁）：\n\n"
        "- 针对 Stage 1（概念策划）、Stage 2（角色设定）、Stage 3（场景道具）、Stage 4（分集大纲）、Stage 5（剧本生成）各阶段产物进行审核放行；\n"
        "- 仅将指定阶段注入白名单 `stage_approvals[f'stage{stage}'] = True`；\n"
        "- **架构安全保证**：绝不锁定第一程文学产物，绝不越级跳进第二程视听工程，精准避免意外提前定稿或状态重跑。"
    ),
    response_description="阶段审批放行快照与恢复执行信息",
)
def approve_stage_explicit(
    drama_id: str,
    stage: int,
    req: WorkflowApproveRequest = WorkflowApproveRequest(),
):
    """阶段级显式审批放行接口 (POST /stages/{stage}/approve)。
    
    明确语义：针对 Stage 1~5 各阶段产物的审阅确认，将该阶段加入 stage_approvals 白名单并放行到下一阶段。
    绝不锁定第一程文学产物，绝不越级进入第二程视听工程。

    Args:
        drama_id: 短剧项目唯一标识
        stage: 审批通过的目标阶段 (1~5)
        req: 审批请求体 (含人工覆盖状态、审核批注与自动恢复控制)

    Returns:
        包含 stage_approvals, checkpoint_id, status 的响应字典
    """
    if req is None:
        req = WorkflowApproveRequest()
    comment = (
        getattr(req, "comment", None)
        or getattr(req, "human_feedback", None)
        or getattr(req, "feedback", None)
        or f"Stage {stage} 显式审核放行"
    )
    auto_resume = getattr(req, "auto_resume", True)
    run_mode = getattr(req, "run_mode", "two_journey")
    human_override_state = getattr(req, "human_override_state", None)

    logger.info(f"[API] 显式阶段审批通过请求: drama_id={drama_id}, stage={stage}, comment={comment}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        try:
            res = approve_human_review(
                drama_id=drama_id,
                stage=stage,
                human_override_state=human_override_state,
                human_feedback=comment,
                auto_resume=auto_resume,
                run_mode=run_mode,
            )
            return success(res)
        except ValueError as ve:
            logger.warning(f"[API] 阶段审批参数或状态异常: {ve}")
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.error(f"[API] 阶段审批执行失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/gatekeeper/confirm",
    summary="两程九阶全季总门禁确认定稿 (文学定稿锁定与视听工程跃迁)",
    description=(
        "**【两程九阶架构总门禁】**\n\n"
        "全季文学剧本全部完成后的最高级别定稿确认门禁（Two-Journey Gatekeeper）：\n\n"
        "- **准入校验**：严格要求 `current_stage >= 5`（全季各集剧本已创作完毕），未达标调用直接拒绝并抛出 400 异常；\n"
        "- **原子资产锁定**：将第一程文学资产（人物设定、大纲、剧本）彻底封板加锁（`literary_journey_locked = True`）；\n"
        "- **跨程跃迁推进**：状态机阶数原子跃迁至 `current_stage = 6`，将工作流推进至第二程视听工业化工程（分镜/资产/音频）。"
    ),
    response_description="全季文学定稿锁定确认报告与第二程视听工程激活状态",
)
def confirm_gatekeeper_explicit(
    drama_id: str,
    req: GatekeeperConfirmRequest = GatekeeperConfirmRequest(),
):
    """全季总门禁定稿确认接口 (POST /gatekeeper/confirm)。
    
    明确语义：仅在阶段五全集剧本编写完成（Stage 5 Finished）后调用。
    严格执行三步原子操作：
    1. 冻结第一程文学产物 (literary_journey_locked=True)；
    2. 原子跃迁 current_stage=6；
    3. 更新持久化并恢复执行第二程分镜与视听工业化。
    若 current_stage < 5 则直接抛出 400 异常拒绝执行。

    Args:
        drama_id: 短剧项目唯一标识
        req: 门禁确认请求体 (含定稿操作人、自动恢复控制与执行模式)

    Returns:
        包含 literary_journey_locked=True, current_stage=6, checkpoint_id 的定稿锁定响应
    """
    if req is None:
        req = GatekeeperConfirmRequest()
    operator = getattr(req, "operator", "user") or "user"
    comment = (
        getattr(req, "human_feedback", None)
        or getattr(req, "comment", None)
        or getattr(req, "feedback", None)
        or "全季文学剧本定稿确认"
    )
    auto_resume = getattr(req, "auto_resume", True)
    run_mode = getattr(req, "run_mode", "two_journey")

    logger.info(f"[API] 显式全季定稿门禁确认请求: drama_id={drama_id}, operator={operator}")
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        try:
            res = confirm_gatekeeper_and_lock(
                drama_id=drama_id,
                human_feedback=comment,
                run_mode=run_mode,
                auto_resume=auto_resume,
                operator=operator,
            )
            return success(res)
        except ValueError as ve:
            logger.warning(f"[API] 全季门禁定稿校验未通过: {ve}")
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.error(f"[API] 全季门禁定稿执行失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/rerun-stage",
    summary="第一程阶段级时光倒流重跑 (回溯锚点与新分支派生)",
    description=(
        "**【两程九阶架构接口 9】**\n\n"
        "第一程（Stage 1~5）任意阶段的时光倒流（Time Travel）与新分支派生：\n\n"
        "- **基准锚点回溯**：自动定位目标阶段的前置合格检查点（例如重跑 Stage 4 则回溯 Stage 3 终态快照）；\n"
        "- **脏数据隔离**：级联使下游阶段的中间产物与检查点失效，派生全新的演进分支；\n"
        "- **人工指导注入**：将用户针对该阶段的修正意见 `human_guidance_for_stage{N}` 注入状态，实现精准修正重跑。"
    ),
    response_description="重跑派生检查点信息、目标阶数及执行恢复详情",
)
def rerun_stage(
    drama_id: str,
    req: WorkflowRerunStageRequest,
):
    """【接口 9】第一程阶段级时光倒流重跑 (POST /rerun-stage)。
    
    1. 定位前置合格锚定点 (target_stage - 1)；
    2. 级联标记业务表与下游状态机脏数据失效；
    3. 派生新分支快照并恢复执行。

    Args:
        drama_id: 短剧项目唯一标识
        req: 包含目标重跑阶段、人工修改指导词、状态覆盖载荷与自动恢复标记

    Returns:
        包含新 checkpoint_id, fork_from, target_stage 的重跑分支响应字典
    """
    target_stage_raw = req.target_stage
    if isinstance(target_stage_raw, int):
        target_stage_num = target_stage_raw
    else:
        target_stage_num = int(str(target_stage_raw).lower().replace("stage", "").strip())

    guidance = req.human_guidance or req.human_feedback or ""
    logger.info(
        f"[API] 第一程阶段级重跑: drama_id={drama_id}, target_stage={target_stage_num}, "
        f"guidance={guidance}"
    )
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        parent_stage_num = max(1, target_stage_num - 1)
        parent_stage = f"stage{parent_stage_num}"

        with session_scope() as db:
            anchor = get_latest_active_checkpoint(db, drama_id, stage=parent_stage)
            if not anchor:
                anchor = get_latest_active_checkpoint(db, drama_id)
            if not anchor:
                raise HTTPException(status_code=400, detail=f"未找到前置阶段合格快照 ({parent_stage})")

        override_state = dict(req.override_payload or {})
        override_state[f"human_guidance_for_stage{target_stage_num}"] = guidance
        override_state["current_stage"] = target_stage_num

        fork_res = time_travel_and_fork(
            drama_id=drama_id,
            target_checkpoint_id=anchor["checkpoint_id"],
            human_override_state=override_state,
            as_node=f"audit_{parent_stage}" if parent_stage_num > 1 else "audit_stage1",
            run_mode=req.run_mode,
        )

        if req.auto_resume:
            resume_res = resume_workflow(drama_id=drama_id, run_mode=req.run_mode)
            fork_res["resume_result"] = resume_res

        fork_res["target_stage"] = f"stage{target_stage_num}" if isinstance(target_stage_raw, str) and target_stage_raw.startswith("stage") else target_stage_num
        return success(fork_res)


@router.post("/pause")
def pause_workflow(
    drama_id: str,
    req: WorkflowPauseRequest | None = None,
):
    """【接口 10a】紧急人工暂停 (POST /pause)。
    
    在 Redis 或内存中设置 pause_flag:drama_{drama_id} = 1。
    """
    req_obj = req or WorkflowPauseRequest()
    comment = req_obj.reason or req_obj.comment or "人工紧急暂停"
    logger.info(f"[API] 触发紧急人工暂停: drama_id={drama_id}, comment={comment}")
    set_pause_flag(drama_id, is_paused=True)
    return success({
        "drama_id": drama_id,
        "status": "pause_signaled",
        "message": f"已设置人工暂停标志: {comment}",
    })


@router.post("/retry")
def retry_workflow(
    drama_id: str,
    req: WorkflowRetryRequest | None = None,
):
    """【接口 10b】异常故障重试 (POST /retry)。
    
    清除暂停标志，从最近一条安全检查点恢复图执行。
    """
    req_obj = req or WorkflowRetryRequest()
    logger.info(f"[API] 触发异常故障重试: drama_id={drama_id}, run_mode={req_obj.run_mode}")
    clear_pause_flag(drama_id)
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        res = resume_workflow(drama_id=drama_id, run_mode=req_obj.run_mode)
        res["status"] = "resumed"
        return success(res)


# =========================================================================
# 通用状态与历史查询端点 (兼容历史调用)
# =========================================================================

@router.get(
    "/status",
    summary="查询工作流实时状态与挂起断点",
    description=(
        "**【两程九阶工作流状态透视】**\n\n"
        "获取指定短剧当前工作流的执行拓扑、阶段进程、审计评级与中断挂起详情：\n\n"
        "- **阶段与历程**：返回当前阶数 `current_stage`、当前历程 `journey`、全季集数及文学定稿锁定标志 `literary_journey_locked`；\n"
        "- **挂起断点**：返回是否等待人工审核 `is_waiting_review`、下游待执行节点清单 `next_nodes` 以及活跃检查点 ID；\n"
        "- **最新质检**：包含最近一次自审报告（合规率、质检项、改进建议）；\n"
        "- **人工暂停状态**：返回是否已被置位紧急人工暂停标志 `is_paused`。"
    ),
    response_description="工作流执行状态、检查点 ID、当前阶段与审计快照",
)
def get_workflow_status(drama_id: str):
    """查询指定短剧工作流的当前执行状态、挂起断点与审计详情。

    Args:
        drama_id: 短剧项目唯一标识

    Returns:
        包含 drama_id, current_stage, journey, is_waiting_review, literary_journey_locked 等状态字段的响应字典
    """
    logger.debug(f"[API] 查询工作流状态: drama_id={drama_id}")
    snapshot = get_workflow_state_snapshot(drama_id=drama_id)
    if not snapshot["exists"]:
        return success({
            "drama_id": drama_id,
            "status": "not_started",
            "is_waiting_review": False,
            "current_stage": None,
            "journey": None,
            "next_nodes": [],
            "is_paused": is_pause_flag_set(drama_id),
        })

    values = snapshot.get("values") or {}
    latest_audit = values.get("latest_audit") or {}
    if hasattr(latest_audit, "model_dump"):
        latest_audit = latest_audit.model_dump()

    status_data = {
        "drama_id": drama_id,
        "thread_id": snapshot.get("thread_id"),
        "checkpoint_id": snapshot.get("checkpoint_id"),
        "is_waiting_review": snapshot.get("is_waiting_review", False),
        "next_nodes": snapshot.get("next_nodes", []),
        "current_stage": values.get("current_stage", 1),
        "journey": values.get("journey", "journey_1_literary"),
        "current_episode_number": values.get("current_episode_number", 0),
        "total_episodes": values.get("total_episodes", 80),
        "literary_journey_locked": values.get("literary_journey_locked", False),
        "latest_audit": latest_audit,
        "is_paused": is_pause_flag_set(drama_id),
        "created_at": snapshot.get("created_at"),
    }
    return success(status_data)


@router.get(
    "/checkpoints",
    summary="查询工作流历史持久化检查点列表",
    description=(
        "**【两程九阶持久化时间旅行索引】**\n\n"
        "按阶段、单集与活跃分支多维过滤查询当前短剧在 MySQL 持久化检查点索引表中的快照历史：\n\n"
        "- **多维过滤**：支持指定 `stage`（如 stage1/stage4）、`episode_number`（单集过滤）及 `active_only`（仅活跃演进分支或全部历史）；\n"
        "- **元数据丰富**：返回每条检查点的父检查点 ID（`parent_checkpoint_id`）、质检结论（`audit_verdict`）、分支深度与创建时间；\n"
        "- **时光倒流定位**：为前端时间旅行滑块与版本回退提供精准的可回溯检查点清单。"
    ),
    response_description="检查点记录列表，包含检查点 ID、阶段、集数与质检裁决",
)
def get_workflow_checkpoints(
    drama_id: str = Path(..., description="短剧项目唯一标识 (例如 '7' 或数字 ID)"),
    stage: str | None = Query(None, description="按阶段过滤，如 stage1/stage2/stage4/stage5"),
    episode_number: int | None = Query(None, description="按集数过滤 (第二程分集制作或第一程单集)"),
    active_only: bool = Query(True, description="是否仅返回当前活跃分支检查点 (忽略已回溯的废弃分支)"),
    limit: int = Query(50, ge=1, le=200, description="最大返回条数 (默认 50，上限 200)"),
    db: Session = Depends(get_db),
):
    """查询短剧的历史检查点索引列表，支持按阶段、集数与活跃状态过滤。

    Args:
        drama_id: 短剧项目唯一标识
        stage: 阶段过滤名称 (可选)
        episode_number: 集数过滤 (可选)
        active_only: 是否仅返回活跃分支检查点 (默认 True)
        limit: 最大返回数量 (默认 50)
        db: 数据库会话

    Returns:
        包含检查点 ID、阶数、父节点、分支深度与审核评级的字典列表
    """
    logger.debug(
        f"[API] 查询检查点列表: drama_id={drama_id}, stage={stage}, "
        f"ep={episode_number}, active_only={active_only}"
    )
    checkpoints = list_drama_checkpoints(
        db=db,
        drama_id=drama_id,
        stage=stage,
        episode_number=episode_number,
        active_only=active_only,
        limit=limit,
    )
    return success(checkpoints)


@router.post(
    "/approve",
    summary="通用人工审核放行 (兼容历史调用)",
    description=(
        "**【通用审核放行兼容端点】**\n\n"
        "接受审核放行参数（支持指定检查点 ID、阶段编号或从最新活跃检查点自动推断）：\n\n"
        "- **白名单注入**：调用 `approve_human_review` 注入阶段审核合格标记；\n"
        "- **状态覆盖支持**：支持传入 `human_override_state` 携带编剧直接修改的剧情字段；\n"
        "- **自动唤醒**：若 `auto_resume=True`，原子释放阻断并从当前位置继续驱动状态机。"
    ),
    response_description="审核放行结果、已更新检查点与恢复执行响应",
)
def approve_workflow(
    drama_id: str,
    req: WorkflowApproveRequest = WorkflowApproveRequest(),
):
    """通用人工审核放行。

    Args:
        drama_id: 短剧项目唯一标识
        req: 通用审核请求体 (含阶段、检查点 ID、人工反馈与覆盖状态)

    Returns:
        包含 checkpoint_id, status, resume_result 的响应字典
    """
    if req is None:
        req = WorkflowApproveRequest()
    stage = getattr(req, "stage", None)
    checkpoint_id = getattr(req, "checkpoint_id", None)
    comment = (
        getattr(req, "human_feedback", None)
        or getattr(req, "comment", None)
        or getattr(req, "feedback", None)
    )
    human_override_state = getattr(req, "human_override_state", None)
    auto_resume = getattr(req, "auto_resume", True)
    run_mode = getattr(req, "run_mode", "two_journey")

    logger.info(
        f"[API] 收到人工审核放行请求: drama_id={drama_id}, ckpt_id={checkpoint_id}, "
        f"auto_resume={auto_resume}, run_mode={run_mode}"
    )
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        try:
            res = approve_human_review(
                drama_id=drama_id,
                stage=stage,
                checkpoint_id=checkpoint_id,
                human_feedback=comment,
                human_override_state=human_override_state,
                auto_resume=auto_resume,
                run_mode=run_mode,
            )
            return success(res)
        except Exception as e:
            logger.error(f"[API] 人工审核处理失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/time-travel",
    summary="通用时光倒流与分支派生 (Strategy A: Time Travel & Forking)",
    description=(
        "**【时光倒流与分支派生核心端点】**\n\n"
        "实现两程九阶工业全息工作流的核心时间旅行回溯与分支树分叉：\n\n"
        "- **目标锚点定位**：可通过 `target_checkpoint_id` 直接指定检查点，或通过 `target_stage` + `target_episode` 定位最近合格快照；\n"
        "- **人工数据覆盖**：支持通过 `human_override_state` 注入修改后的剧本设定或控制参数；\n"
        "- **级联失效与克隆**：在 MySQL 检查点树中派生全新子分支，级联失效下游过时的检查点与业务模型，保留完整审计痕迹；\n"
        "- **无缝恢复**：若 `auto_resume=True`，派生后立即唤醒图引擎继续向下演进。"
    ),
    response_description="时间旅行分支派生快照、新检查点 ID 及执行恢复详情",
)
def time_travel_workflow(
    drama_id: str,
    req: WorkflowTimeTravelRequest,
):
    """通用时光倒流与分支派生 (Strategy A: Time Travel & Forking)。

    Args:
        drama_id: 短剧项目唯一标识
        req: 时光倒流请求体 (含回溯目标阶段/集数/检查点、人工覆盖状态及节点定位)

    Returns:
        包含新派生 checkpoint_id, fork_from, resume_result 的字典
    """
    logger.info(
        f"[API] 收到时光倒流请求: drama_id={drama_id}, target_stage={req.target_stage}, "
        f"target_ep={req.target_episode}, target_ckpt={req.target_checkpoint_id}, "
        f"auto_resume={req.auto_resume}, run_mode={req.run_mode}"
    )
    with workflow_lock_context(drama_id) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="工作流任务正在执行中，请勿重复操作")

        try:
            fork_result = time_travel_and_fork(
                drama_id=drama_id,
                target_stage=req.target_stage,
                target_episode=req.target_episode,
                target_checkpoint_id=req.target_checkpoint_id,
                human_override_state=req.human_override_state,
                as_node=req.as_node,
                run_mode=req.run_mode,
            )

            if req.auto_resume:
                resume_result = resume_workflow(drama_id=drama_id, run_mode=req.run_mode)
                fork_result["resume_result"] = resume_result

            return success(fork_result)
        except ValueError as ve:
            logger.warning(f"[API] 时光倒流参数或定位异常: {ve}")
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.error(f"[API] 时光倒流执行失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
