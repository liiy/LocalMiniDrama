"""工作流总控与时光回溯 (Workflow Control & Time Travel) 请求模型 (DTO / Schema)。

职责：
- 封装两程九阶全流程中各阶段人工审核、波次放行、时光回溯、单集重跑与故障重试的 API 入参模型。
- 允许前端透传扩展字段 (extra="allow")，兼容多版本前端及历史请求别名。
- 与具体 FastAPI 路由逻辑解耦，统一继承 BaseApiRequest。
"""

from typing import Any, Literal, get_origin, get_args
from pydantic import ConfigDict, Field, model_validator

from app.schemas.requests.base import BaseApiRequest
from app.schemas.requests.script_studio import PipelineRunMode


class BaseWorkflowControlRequest(BaseApiRequest):
    """工作流总控基础请求模型。
    
    允许客户端附带前端扩展字段（extra='allow'），以便兼容各种历史操作痕迹与别名。
    """
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True,
        extra="allow",
    )

    @model_validator(mode="before")
    @classmethod
    def sanitize_empty_object_fields(cls, data: Any) -> Any:
        """自动兼容客户端或工具（如 Postman、部分前端请求库）对空字段序列化为 {} 的情况。

        若非 dict/Any 类型的标量/可选字段收到空字典 {}，自动转换为 None，避免 422 校验失败。
        """
        if isinstance(data, dict):
            sanitized = {}
            for k, v in data.items():
                if v == {}:
                    field_info = cls.model_fields.get(k)
                    if field_info:
                        annotation = field_info.annotation
                        origin = get_origin(annotation)
                        args = get_args(annotation)
                        if origin is not dict and dict not in args and annotation is not dict and annotation is not Any:
                            sanitized[k] = None
                            continue
                sanitized[k] = v
            return sanitized
        return data


# =========================================================================
# 1. 通用审批与定稿门禁请求模型
# =========================================================================

class WorkflowApproveRequest(BaseWorkflowControlRequest):
    """通用阶段人工审核放行请求模型。"""

    stage: int | str | None = Field(
        default=None,
        description="指定放行阶段编号 (1~8 或 'stage1'~'stage8')，不传则自动判定当前挂起点",
    )
    checkpoint_id: str | None = Field(
        default=None,
        description="可选特定检查点 ID，不传默认取当前最新活跃挂起点",
    )
    comment: str | None = Field(
        default=None,
        description="审核批注说明 (兼容 comment 别名)",
    )
    human_feedback: str | None = Field(
        default=None,
        description="人工审核批注与指导反馈意见",
    )
    feedback: str | None = Field(
        default=None,
        description="兼容 feedback 别名",
    )
    operator: str = Field(
        default="user",
        description="审批操作人姓名或身份标识",
    )
    approved: bool = Field(
        default=True,
        description="是否审核通过（True 为放行，False 为驳回或暂停）",
    )
    human_override_state: dict[str, Any] | None = Field(
        default=None,
        description="人工微调覆写数据字典 (例如在前端修改后的人设、大纲或分镜参数)",
    )
    auto_resume: bool = Field(
        default=True,
        description="审核放行后是否立即自动推进并唤醒下一阶段执行",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="执行控制模式：stage_by_stage(逐阶段强干预)/two_journey(两程总控)/full_auto(全自动极速)",
    )


class GatekeeperConfirmRequest(BaseWorkflowControlRequest):
    """两程九阶第一程至第二程核心定稿总门禁确认请求模型。"""

    operator: str = Field(
        default="user",
        description="审批操作人姓名或身份标识",
    )
    human_feedback: str | None = Field(
        default=None,
        description="全季文学剧本终审定稿批注与交接视听指导说明",
    )
    comment: str | None = Field(
        default=None,
        description="审核批注 (兼容 comment 别名)",
    )
    feedback: str | None = Field(
        default=None,
        description="兼容 feedback 别名",
    )
    approved: bool = Field(
        default=True,
        description="是否审核通过定稿",
    )
    auto_resume: bool = Field(
        default=True,
        description="定稿锁本后是否立即自动推进至第二程视听工程",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="执行控制模式：stage_by_stage/two_journey/full_auto",
    )


# =========================================================================
# 2. 时光回溯与恢复执行请求模型
# =========================================================================

class WorkflowTimeTravelRequest(BaseWorkflowControlRequest):
    """通用时光倒流、检查点快照恢复与分支派生请求模型。"""

    target_stage: str | None = Field(
        default=None,
        description="目标回溯阶段 (如 'stage1', 'stage2'... 'stage8')",
    )
    target_episode: int | None = Field(
        default=None,
        description="目标回溯集数 (第二程单集视听工程回溯，>=1)",
    )
    target_checkpoint_id: str | None = Field(
        default=None,
        description="精确指定的历史检查点快照 ID (若提供则最高优先级定位)",
    )
    human_override_state: dict[str, Any] | None = Field(
        default=None,
        description="人工在回溯节点注入的覆写状态字典",
    )
    as_node: str | None = Field(
        default=None,
        description="声明本次 update_state 以哪个节点身份写入 (可选)",
    )
    auto_resume: bool = Field(
        default=True,
        description="分支派生后是否立即自动从新分支恢复向下执行",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="执行控制模式",
    )


class WorkflowResumeRequest(BaseWorkflowControlRequest):
    """手动恢复执行请求模型 (通用/阶段放行)。"""

    stage: int | None = Field(
        default=None,
        description="审核放行的阶段 (1~4 或 Gatekeeper)",
    )
    comment: str | None = Field(
        default=None,
        description="放行批注",
    )
    human_feedback: str | None = Field(
        default=None,
        description="兼容 human_feedback 别名",
    )
    feedback: str | None = Field(
        default=None,
        description="兼容 feedback 别名",
    )
    operator: str = Field(
        default="user",
        description="审批操作人姓名或身份标识",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="恢复执行控制模式",
    )


# =========================================================================
# 3. 阶段五分波次审核与重跑请求模型
# =========================================================================

class Stage5WaveApproveRequest(BaseWorkflowControlRequest):
    """阶段五剧本分波次审核放行请求模型。"""

    wave_index: int | None = Field(
        default=None,
        description="当前审核通过的波次索引编号（从 0 开始）",
    )
    wave_number: int | None = Field(
        default=None,
        description="兼容 wave_number 别名（从 1 开始）",
    )
    approved_episodes: list[int] = Field(
        default_factory=list,
        description="本波次通过的集数列表",
    )
    comment: str = Field(
        default="",
        description="审核批注",
    )
    human_feedback: str | None = Field(
        default=None,
        description="兼容 human_feedback 别名",
    )
    feedback: str | None = Field(
        default=None,
        description="兼容 feedback 别名",
    )
    auto_resume: bool = Field(
        default=True,
        description="是否立即恢复并执行下一波次",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.STAGE_BY_STAGE,
        description="运行模式 (分波次精细干预推荐 stage_by_stage)",
    )


class Stage5WaveUpdateAndResumeRequest(BaseWorkflowControlRequest):
    """阶段五波次人工修改并继续执行请求模型。"""

    wave_index: int | None = Field(
        default=None,
        description="波次索引编号",
    )
    wave_number: int | None = Field(
        default=None,
        description="兼容 wave_number 别名",
    )
    episodes_patch: dict[str, Any] | list[Any] = Field(
        default_factory=dict,
        description="剧本修改补丁字典或列表",
    )
    modified_screenplays: list[Any] | None = Field(
        default=None,
        description="兼容 modified_screenplays 别名",
    )
    continue_next_wave: bool = Field(
        default=True,
        description="是否立即恢复并执行下一波次",
    )
    auto_resume: bool = Field(
        default=True,
        description="兼容 auto_resume 别名",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.STAGE_BY_STAGE,
        description="运行模式",
    )


class Stage5WaveRerunRequest(BaseWorkflowControlRequest):
    """阶段五波次重新生成重跑请求模型。"""

    wave_index: int | None = Field(
        default=None,
        description="需重跑的波次索引编号",
    )
    wave_number: int | None = Field(
        default=None,
        description="兼容 wave_number 别名",
    )
    human_guidance: str = Field(
        default="",
        description="人工针对本波次的重跑指导意见与调整要求",
    )
    human_instructions: str | None = Field(
        default=None,
        description="兼容 human_instructions 别名",
    )
    auto_resume: bool = Field(
        default=True,
        description="重跑分支派生后是否立即自动恢复生成",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.STAGE_BY_STAGE,
        description="运行模式",
    )


# =========================================================================
# 4. 第二程单集审核、修改与重跑请求模型
# =========================================================================

class EpisodeApproveRequest(BaseWorkflowControlRequest):
    """第二程单集视听工程审核通过请求模型。"""

    episode_number: int | None = Field(
        default=None,
        description="审核通过的分集集数序号",
    )
    comment: str = Field(
        default="",
        description="审核批注",
    )
    human_feedback: str | None = Field(
        default=None,
        description="兼容 human_feedback 别名",
    )
    feedback: str | None = Field(
        default=None,
        description="兼容 feedback 别名",
    )
    auto_resume: bool = Field(
        default=True,
        description="审核放行后是否自动推进后续执行",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="运行模式",
    )


class EpisodeUpdateAndResumeRequest(BaseWorkflowControlRequest):
    """第二程单集分镜与音频修改并继续执行请求模型。"""

    episode_number: int | None = Field(
        default=None,
        description="分集序号",
    )
    storyboards_patch: list[dict[str, Any]] = Field(
        default_factory=list,
        description="分镜镜头参数修改列表",
    )
    audio_patch: dict[str, Any] = Field(
        default_factory=dict,
        description="音频/配音/音效参数修改字典",
    )
    modified_screenplay: dict[str, Any] | None = Field(
        default=None,
        description="兼容单集剧本修改",
    )
    continue_next_episode: bool = Field(
        default=True,
        description="是否继续处理下一集",
    )
    auto_resume: bool = Field(
        default=True,
        description="兼容 auto_resume 别名",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="运行模式",
    )


class EpisodeRerunRequest(BaseWorkflowControlRequest):
    """第二程单集独立重跑请求模型。"""

    episode_number: int | None = Field(
        default=None,
        description="需重跑的目标集数序号",
    )
    from_stage: int = Field(
        default=7,
        description="从哪一阶段开始重跑 (6 角色/场景视听资产提取, 7 动态分镜设计与渲染, 8 音频对齐与母带混音)",
    )
    only_current_stage: bool = Field(
        default=False,
        description="是否仅重跑当前阶段 (若为 True，仅执行 from_stage 阶段，完成后立即挂起中断，不向下级联后续阶段)",
    )
    target_stage: int | None = Field(
        default=None,
        description="可选目标阶段，若 target_stage == from_stage，则等同于 only_current_stage=True",
    )
    human_guidance: str = Field(
        default="",
        description="重跑指导意见",
    )
    human_instructions: str | None = Field(
        default=None,
        description="兼容指导意见别名",
    )
    auto_resume: bool = Field(
        default=True,
        description="重跑分支派生后是否立即恢复执行",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="运行模式",
    )


# =========================================================================
# 5. 第一程阶段级时光回溯、暂停与重试请求模型
# =========================================================================

class WorkflowRerunStageRequest(BaseWorkflowControlRequest):
    """第一程阶段级时光倒流重跑请求模型。"""

    target_stage: int | str = Field(
        ...,
        description="目标重跑阶段 (1~8 或 'stage1'~'stage8')",
    )
    human_guidance: str = Field(
        default="",
        description="人工针对该阶段的修改指导意见与方向指示",
    )
    human_feedback: str | None = Field(
        default=None,
        description="兼容 human_feedback 别名",
    )
    comment: str | None = Field(
        default=None,
        description="兼容 comment 别名",
    )
    feedback: str | None = Field(
        default=None,
        description="兼容 feedback 别名",
    )
    override_payload: dict[str, Any] | None = Field(
        default=None,
        description="附加覆写数据字典",
    )
    auto_resume: bool = Field(
        default=True,
        description="重跑分支派生后是否立即恢复执行",
    )
    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="执行控制模式",
    )


class WorkflowPauseRequest(BaseWorkflowControlRequest):
    """紧急人工暂停请求模型。"""

    comment: str = Field(
        default="人工紧急暂停",
        description="暂停原因说明",
    )
    reason: str | None = Field(
        default=None,
        description="兼容 reason 别名",
    )


class WorkflowRetryRequest(BaseWorkflowControlRequest):
    """异常故障重试请求模型。"""

    run_mode: PipelineRunMode | Literal["stage_by_stage", "two_journey", "full_auto"] = Field(
        default=PipelineRunMode.TWO_JOURNEY,
        description="恢复执行控制模式",
    )


__all__ = [
    "BaseWorkflowControlRequest",
    "WorkflowApproveRequest",
    "GatekeeperConfirmRequest",
    "WorkflowTimeTravelRequest",
    "WorkflowResumeRequest",
    "Stage5WaveApproveRequest",
    "Stage5WaveUpdateAndResumeRequest",
    "Stage5WaveRerunRequest",
    "EpisodeApproveRequest",
    "EpisodeUpdateAndResumeRequest",
    "EpisodeRerunRequest",
    "WorkflowRerunStageRequest",
    "WorkflowPauseRequest",
    "WorkflowRetryRequest",
]
