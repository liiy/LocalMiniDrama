"""/api/v1/platform/* — 平台化能力底座。

这些接口先提供 Prompt、Skill、Context、Workflow、Memory 的最小管理能力。
它们不替换现有生成接口，而是给后续 Multi-Agent 编排逐步接管现有流程预留稳定入口。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.agents import registry as agent_registry
from app.context import builder as context_builder
from app.context import memory_service
from app.context import vector_memory_service
from app.core.response import bad_request, not_found, success
from app.db.session import get_db
from app.prompts import registry_service as prompt_registry
from app.quality import report_service as quality_report_service
from app.skills import bootstrap_service
from app.skills import registry_service as skill_registry
from app.tasks import queue_service
from app.tasks import worker_runner
from app.tasks import worker_runtime
from app.workflows import blueprints as workflow_blueprints
from app.workflows import executor as workflow_executor
from app.workflows import run_service as workflow_service
from app.workflows import task_bridge as workflow_task_bridge

router = APIRouter(tags=["platform"])


@router.get("/platform/agents")
def list_agents() -> dict:
    return success(agent_registry.list_agents())


@router.post("/platform/bootstrap/defaults")
def bootstrap_platform_defaults(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    # 默认 Skill/Prompt 只作为平台初始能力目录，后续版本应通过 Prompt Registry 单独发布。
    status = str((payload or {}).get("status") or "active")
    return success(bootstrap_service.bootstrap_defaults(db, status=status))


@router.post("/platform/prompts")
def upsert_prompt_template(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = prompt_registry.create_prompt_template(db, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.get("/platform/prompts")
def list_prompt_templates(
    prompt_key: str | None = Query(default=None),
    skill_key: str | None = Query(default=None),
    agent_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return success(
        prompt_registry.list_prompt_templates(
            db,
            {"prompt_key": prompt_key, "skill_key": skill_key, "agent_name": agent_name, "status": status},
        )
    )


@router.post("/platform/prompts/render")
def render_prompt(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    try:
        result = prompt_registry.render_prompt(
            db,
            str(body.get("prompt_key") or ""),
            body.get("variables") or {},
            body.get("version"),
        )
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(result)


@router.post("/platform/prompts/runs")
def record_prompt_run(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    # Prompt Run 是后续成本统计、Prompt 回放和 Agent 调试的关键证据链。
    return success(prompt_registry.record_prompt_run(db, payload or {}))


@router.post("/platform/skills")
def upsert_skill(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = skill_registry.upsert_skill(db, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.get("/platform/skills")
def list_skills(status: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return success(skill_registry.list_skills(db, status))


@router.get("/platform/skills/{skill_key}")
def get_skill(skill_key: str, db: Session = Depends(get_db)) -> dict:
    item = skill_registry.get_skill(db, skill_key)
    if not item:
        raise not_found("Skill 不存在")
    return success(item)


@router.post("/platform/context/build")
def build_context(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    context = context_builder.build_context(
        db,
        drama_id=body.get("drama_id"),
        episode_id=body.get("episode_id"),
        storyboard_id=body.get("storyboard_id"),
        skill_key=body.get("skill_key"),
        include_memory=body.get("include_memory", True),
    )
    if body.get("save_snapshot"):
        context["snapshot"] = context_builder.save_context_snapshot(db, context, body.get("workflow_run_id"))
    return success(context)


@router.post("/platform/memory")
def add_memory_item(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = memory_service.add_memory_item(db, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.get("/platform/memory/search")
def search_memory_items(
    drama_id: int | None = Query(default=None),
    episode_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    memory_type: str | None = Query(default=None),
    limit: int = Query(default=20),
    db: Session = Depends(get_db),
) -> dict:
    return success(
        memory_service.search_memory_items(
            db,
            drama_id=drama_id,
            episode_id=episode_id,
            query=q,
            memory_type=memory_type,
            limit=limit,
        )
    )


@router.post("/platform/memory/search")
def search_memory_items_post(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    # POST 入口用于语义检索：query_vector 体积较大，不适合放到 URL 查询参数中。
    return success(
        memory_service.search_memory_items(
            db,
            drama_id=body.get("drama_id"),
            episode_id=body.get("episode_id"),
            query=body.get("q") or body.get("query"),
            query_vector=body.get("query_vector"),
            memory_type=body.get("memory_type"),
            limit=body.get("limit") or 20,
        )
    )


@router.get("/platform/memory/vector-settings")
def get_vector_memory_settings() -> dict:
    settings = vector_memory_service.vector_memory_settings()
    # API 返回时隐藏密钥，只暴露是否已配置，方便前端做诊断提示。
    return success({**settings, "api_key": "***" if settings.get("api_key") else ""})


@router.get("/platform/quality-reports")
def list_quality_reports(
    workflow_run_id: str | None = Query(default=None),
    drama_id: int | None = Query(default=None),
    episode_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    report_type: str | None = Query(default=None),
    limit: int = Query(default=50),
    db: Session = Depends(get_db),
) -> dict:
    return success(
        quality_report_service.list_quality_reports(
            db,
            workflow_run_id=workflow_run_id,
            drama_id=drama_id,
            episode_id=episode_id,
            status=status,
            report_type=report_type,
            limit=limit,
        )
    )


@router.get("/platform/quality-reports/{report_id}")
def get_quality_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    item = quality_report_service.get_quality_report(db, report_id)
    if not item:
        raise not_found("质量报告不存在")
    return success(item)


@router.patch("/platform/quality-reports/{report_id}")
def update_quality_report(report_id: int, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    # 仅允许更新质检处理结果，workflow/drama/episode 归属由系统生成，不能由前端随意改动。
    item = quality_report_service.update_quality_report(db, report_id, payload or {})
    if not item:
        raise not_found("质量报告不存在")
    return success(item)


@router.post("/platform/queue/jobs")
def enqueue_queue_job(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = queue_service.enqueue_job(db, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.get("/platform/queue/workers")
def list_queue_workers(
    status: str | None = Query(default=None),
    limit: int = Query(default=100),
    db: Session = Depends(get_db),
) -> dict:
    return success(queue_service.list_worker_nodes(db, status=status, limit=limit))


@router.get("/platform/queue/runtime")
def get_queue_runtime_status() -> dict:
    return success(worker_runtime.embedded_worker_status())


@router.post("/platform/queue/recover-stale")
def recover_stale_queue_state(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    # 管理端可主动回收失联 worker 和超时 processing job，常驻 Runtime 也会定期执行同样逻辑。
    stale_workers = queue_service.mark_stale_workers_offline(
        db,
        timeout_seconds=body.get("stale_worker_seconds") or 90,
    )
    stale_jobs = worker_runner.recover_stale_jobs(
        db,
        timeout_seconds=body.get("stale_job_seconds") or 1800,
        limit=body.get("limit") or 100,
    )
    return success({"stale_workers": stale_workers, "stale_jobs": stale_jobs})


@router.get("/platform/queue/jobs")
def list_queue_jobs(
    queue_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    workflow_run_id: str | None = Query(default=None),
    limit: int = Query(default=50),
    db: Session = Depends(get_db),
) -> dict:
    jobs = queue_service.list_queue_jobs(
        db,
        queue_name=queue_name,
        status=status,
        task_type=task_type,
        workflow_run_id=workflow_run_id,
        limit=limit,
    )
    return success({"items": jobs, "summary": queue_service.queue_summary(jobs)})


@router.post("/platform/queue/claim-next")
def claim_next_queue_job(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    worker_id = str(body.get("worker_id") or "").strip()
    if not worker_id:
        raise bad_request("worker_id 必填")
    return success(queue_service.claim_next_job(db, worker_id=worker_id, queue_name=body.get("queue_name")))


@router.post("/platform/queue/run-next")
def run_next_queue_job(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    worker_id = str(body.get("worker_id") or "").strip()
    if not worker_id:
        raise bad_request("worker_id 必填")
    # 单次只执行一个 job，便于外部 supervisor/定时任务控制并发和进程生命周期。
    return success(
        worker_runner.run_next_job(
            db,
            worker_id=worker_id,
            queue_name=body.get("queue_name"),
            auto_advance=bool(body.get("auto_advance")),
        )
    )


@router.post("/platform/queue/sync-waiting")
def sync_waiting_queue_jobs(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    return success(
        worker_runner.sync_waiting_jobs(
            db,
            workflow_run_id=body.get("workflow_run_id"),
            auto_advance=bool(body.get("auto_advance")),
            limit=body.get("limit") or 100,
        )
    )


@router.post("/platform/queue/jobs/{job_id}/complete")
def complete_queue_job(job_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    item = queue_service.complete_job(db, job_id, (payload or {}).get("result") or {})
    if not item:
        raise not_found("队列任务不存在")
    return success(item)


@router.post("/platform/queue/jobs/{job_id}/fail")
def fail_queue_job(job_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    item = queue_service.fail_job(db, job_id, str(body.get("error") or ""), retryable=body.get("retryable", True))
    if not item:
        raise not_found("队列任务不存在")
    return success(item)


@router.post("/platform/queue/jobs/{job_id}/retry")
def retry_queue_job(job_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    item = queue_service.retry_job(db, job_id, run_after=(payload or {}).get("run_after"))
    if not item:
        raise not_found("队列任务不存在")
    return success(item)


@router.post("/platform/queue/jobs/{job_id}/cancel")
def cancel_queue_job(job_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    # 取消由 Runner 统一处理，确保 queue、async_task 和 workflow 三层状态一致。
    item = worker_runner.cancel_job(db, job_id, reason=(payload or {}).get("reason"))
    if not item:
        raise not_found("队列任务不存在")
    return success(item)


@router.post("/platform/workflows")
def create_workflow(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = workflow_service.create_workflow_run(db, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/original-script")
def create_original_script_workflow(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    # 原创剧本入口要求更重：先记录完整需求，再由蓝图拆成创作与下游生产步骤。
    item = workflow_service.create_workflow_run(
        db,
        {
            **body,
            "type": "original_script",
            "user_request": body.get("user_request") or body.get("core_theme") or body.get("title_hint"),
            "input_payload": body,
            "seed_steps": body.get("seed_steps", True),
        },
    )
    return success(item)


@router.post("/platform/workflows/novel-adaptation")
def create_novel_adaptation_workflow(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    # 小说改编入口先强调原文、章节、改编策略，后续与原创共用实体/分镜/视听生产链路。
    item = workflow_service.create_workflow_run(
        db,
        {
            **body,
            "type": "novel_adaptation",
            "user_request": body.get("user_request") or body.get("novel_title") or "小说改编短剧",
            "input_payload": body,
            "seed_steps": body.get("seed_steps", True),
        },
    )
    return success(item)


@router.get("/platform/workflows")
def list_workflows(
    drama_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),  # noqa: A002 - API 查询参数沿用 type 更直观
    limit: int = Query(default=50),
    db: Session = Depends(get_db),
) -> dict:
    return success(workflow_service.list_workflow_runs(db, drama_id=drama_id, status=status, workflow_type=type, limit=limit))


@router.get("/platform/workflows/blueprints")
def list_workflow_blueprints() -> dict:
    return success(workflow_blueprints.list_workflow_blueprints())


@router.get("/platform/workflows/blueprints/{workflow_type}")
def get_workflow_blueprint(workflow_type: str) -> dict:
    steps = workflow_blueprints.get_workflow_blueprint(workflow_type)
    if not steps:
        raise not_found("Workflow 蓝图不存在")
    return success({"type": workflow_type, "steps": steps, "step_count": len(steps)})


@router.get("/platform/workflows/{workflow_run_id}")
def get_workflow(workflow_run_id: str, db: Session = Depends(get_db)) -> dict:
    item = workflow_service.get_workflow_run(db, workflow_run_id)
    if not item:
        raise not_found("Workflow 不存在")
    return success(item)


@router.get("/platform/workflows/{workflow_run_id}/graph")
def get_workflow_graph(workflow_run_id: str, db: Session = Depends(get_db)) -> dict:
    # 任务图接口用于前端展示当前可执行节点、等待依赖节点和整体进度。
    return success(workflow_service.get_workflow_execution_state(db, workflow_run_id))


@router.patch("/platform/workflows/{workflow_run_id}")
def update_workflow(workflow_run_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    return success(workflow_service.update_workflow_run(db, workflow_run_id, payload or {}))


@router.post("/platform/workflows/{workflow_run_id}/execute-next")
def execute_next_workflow_step(
    workflow_run_id: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    try:
        item = workflow_executor.execute_next_step(db, None, workflow_run_id, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/execute-until-blocked")
def execute_workflow_until_blocked(
    workflow_run_id: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    try:
        item = workflow_executor.run_until_blocked(db, None, workflow_run_id, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/execute-step/{step_key}")
def execute_workflow_step(
    workflow_run_id: str,
    step_key: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    try:
        item = workflow_executor.execute_step(db, None, workflow_run_id, step_key, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/sync-step/{step_key}")
def sync_workflow_step(
    workflow_run_id: str,
    step_key: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    try:
        item = workflow_task_bridge.sync_step_from_async_task(db, workflow_run_id, step_key, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/sync-all")
def sync_workflow_processing_steps(
    workflow_run_id: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    try:
        item = workflow_task_bridge.sync_all_processing_steps(db, workflow_run_id, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/steps")
def add_workflow_step(workflow_run_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = workflow_service.add_workflow_step(db, workflow_run_id, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.patch("/platform/workflows/{workflow_run_id}/steps/{step_key}")
def update_workflow_step(
    workflow_run_id: str,
    step_key: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    item = workflow_service.update_workflow_step(db, workflow_run_id, step_key, payload or {})
    if not item:
        raise not_found("Workflow Step 不存在")
    return success(item)


@router.post("/platform/agent-runs")
def create_agent_run(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    return success(skill_registry.create_agent_run(db, payload or {}))
