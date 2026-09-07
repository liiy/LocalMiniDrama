"""/api/v1/platform/* — 平台化能力底座。

这些接口先提供 Prompt、Skill、Context、Workflow、Memory 的最小管理能力。
它们不替换现有生成接口，而是给后续 Multi-Agent 编排逐步接管现有流程预留稳定入口。
"""
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agents import registry as agent_registry
from app.agents import runtime as agent_runtime
from app.context import builder as context_builder
from app.context import memory_service
from app.context import vector_memory_service
from app.core.logger import get_logger
from app.core.response import ai_provider_error, bad_request, not_found, success
from app.db import session as db_session_module
from app.db.session import get_db
from app.platform_common import json_dumps
from app.prompts import registry_service as prompt_registry
from app.quality import report_service as quality_report_service
from app.services import aiConfigService, audioDesignService
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
log = get_logger("lmd.platform")


@router.get("/platform/agents")
def list_agents() -> dict:
    return success(agent_registry.list_agents())


@router.get("/platform/agents/{agent_name}")
def get_agent_detail(agent_name: str) -> dict:
    agent = agent_registry.get_agent(agent_name)
    if not agent:
        raise not_found(f"Agent '{agent_name}' 不存在")
    return success(agent)


@router.post("/platform/agents/{agent_name}/execute")
def execute_agent(
    agent_name: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    payload = payload or {}
    input_payload = payload.get("input_payload") or payload
    options = payload.get("options") or {}
    import logging
    log = logging.getLogger("agent_runner")
    try:
        result = agent_runtime.execute_agent_directly(
            db,
            log,
            agent_name=agent_name,
            input_payload=input_payload,
            options=options,
        )
        return success(result)
    except ValueError as e:
        raise bad_request(str(e)) from e
    except Exception as e:
        raise bad_request(f"Agent 执行失败: {e}") from e


@router.post("/platform/bootstrap/defaults")
def bootstrap_platform_defaults(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    # 默认 Skill/Prompt 只作为平台初始能力目录，后续版本应通过 Prompt Registry 单独发布。
    status = str((payload or {}).get("status") or "active")
    return success(bootstrap_service.bootstrap_defaults(db, status=status))


@router.post("/platform/prompts")
@router.post("/platform/prompts/templates")
def upsert_prompt_template(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = prompt_registry.create_prompt_template(db, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.get("/platform/prompts")
@router.get("/platform/prompts/templates")
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


@router.get("/platform/prompts/templates/{template_id_or_key}")
@router.get("/platform/prompts/{template_id_or_key}")
def get_prompt_template_detail(template_id_or_key: str, db: Session = Depends(get_db)) -> dict:
    """按 ID 或 prompt_key 获取 Prompt 模板详情。"""
    if template_id_or_key.isdigit():
        item = prompt_registry.get_prompt_template_by_id(db, int(template_id_or_key))
        if item:
            return success(item)
    item = prompt_registry.get_prompt_template(db, template_id_or_key)
    if not item:
        raise not_found("Prompt 模板不存在")
    return success(item)


@router.get("/platform/prompts/{prompt_key}/history")
@router.get("/platform/prompts/templates/{prompt_key}/history")
def get_prompt_template_history(prompt_key: str, db: Session = Depends(get_db)) -> dict:
    """获取指定 Prompt 的全部历史版本列表。"""
    return success(prompt_registry.get_prompt_template_history(db, prompt_key))


@router.get("/platform/prompts/{prompt_key}/compare")
@router.get("/platform/prompts/templates/{prompt_key}/compare")
def compare_prompt_templates(
    prompt_key: str,
    version_a: int | None = Query(default=None, description="版本 A"),
    version_b: int | None = Query(default=None, description="版本 B"),
    v1: int | None = Query(default=None, description="版本 A 别名"),
    v2: int | None = Query(default=None, description="版本 B 别名"),
    db: Session = Depends(get_db),
) -> dict:
    """对比同一 Prompt 模板的两个历史版本（支持 version_a/b 或 v1/v2 传参）。"""
    va = version_a if version_a is not None else v1
    vb = version_b if version_b is not None else v2
    if va is None or vb is None:
        raise bad_request("必须提供要对比的两个版本号 (version_a/version_b 或 v1/v2)")
    try:
        res = prompt_registry.compare_prompt_templates(db, prompt_key, va, vb)
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(res)


@router.post("/platform/prompts/{prompt_key}/rollback")
@router.post("/platform/prompts/templates/{prompt_key}/rollback")
def rollback_prompt_template(
    prompt_key: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """将指定历史版本回滚激活为当前最新版本。"""
    target_version = (payload or {}).get("target_version")
    if target_version is None:
        raise bad_request("target_version 必填")
    try:
        res = prompt_registry.rollback_prompt_template(db, prompt_key, int(target_version))
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(res)


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


@router.get("/platform/prompt-runs")
@router.get("/platform/prompts/runs")
def list_prompt_runs(
    prompt_key: str | None = Query(default=None),
    skill_key: str | None = Query(default=None),
    agent_name: str | None = Query(default=None),
    workflow_run_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    db: Session = Depends(get_db),
) -> dict:
    """查询模型调用 Prompt Runs 快照审计列表。"""
    return success(
        prompt_registry.list_prompt_runs(
            db,
            {
                "prompt_key": prompt_key,
                "skill_key": skill_key,
                "agent_name": agent_name,
                "workflow_run_id": workflow_run_id,
                "status": status,
            },
            limit=limit,
            offset=offset,
        )
    )


@router.get("/platform/prompt-runs/{run_id}")
@router.get("/platform/prompts/runs/{run_id}")
def get_prompt_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    """获取单次 Prompt 调用的完整快照详情。"""
    item = prompt_registry.get_prompt_run(db, run_id)
    if not item:
        raise not_found("Prompt Run 记录不存在")
    return success(item)


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


@router.get("/platform/context/snapshots/{snapshot_id}")
def get_context_snapshot(snapshot_id: int, db: Session = Depends(get_db)) -> dict:
    """获取指定 ID 的上下文快照详细内容。"""
    item = context_builder.get_context_snapshot(db, snapshot_id)
    if not item:
        raise not_found("上下文快照不存在")
    return success(item)


@router.post("/platform/memory")
def add_memory_item(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    try:
        item = memory_service.add_memory_item(db, payload or {})
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.patch("/platform/memory/{memory_id}")
def update_memory_item(memory_id: int, payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """人工修订记忆，保留修订版本和编辑审计信息。"""
    try:
        item = memory_service.update_memory_item(db, memory_id, payload or {}, editor=str((payload or {}).get("editor") or "human"))
    except ValueError as e:
        raise bad_request(str(e)) from e
    if not item:
        raise not_found("记忆不存在")
    return success(item)


@router.post("/platform/memory/distill")
def distill_memory(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """把原始素材或多条短期记忆自动提炼为长期记忆。"""
    try:
        return success(memory_service.distill_memory_items(db, payload or {}))
    except ValueError as e:
        raise bad_request(str(e)) from e


@router.post("/platform/memory/conflicts/detect")
def detect_memory_conflicts(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """扫描并标记同作用域内互相矛盾的记忆。"""
    return success(memory_service.detect_memory_conflicts(db, drama_id=(payload or {}).get("drama_id")))


@router.post("/platform/memory/expire")
def expire_memory(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """执行过期淘汰；采用状态标记保留历史审计。"""
    return success(memory_service.expire_memory_items(db, as_of=(payload or {}).get("as_of")))


@router.post("/platform/memory/retrieval-evaluations")
def evaluate_memory_retrieval(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """基于标注的期望 ID 计算向量或关键词召回质量。"""
    try:
        return success(memory_service.evaluate_retrieval(db, payload or {}))
    except ValueError as e:
        raise bad_request(str(e)) from e


@router.get("/platform/memory/search")
def search_memory_items(
    drama_id: int | None = Query(default=None),
    episode_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    query: str | None = Query(default=None),
    memory_type: str | None = Query(default=None),
    status: str | None = Query(default="active"),
    limit: int = Query(default=20),
    db: Session = Depends(get_db),
) -> dict:
    search_q = q if q is not None else query
    return success(
        memory_service.search_memory_items(
            db,
            drama_id=drama_id,
            episode_id=episode_id,
            query=search_q,
            memory_type=memory_type,
            status=status,
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
            status=body.get("status", "active"),
            limit=body.get("limit") or 20,
        )
    )


@router.get("/platform/memory/vector-settings")
def get_vector_memory_settings() -> dict:
    settings = vector_memory_service.vector_memory_settings()
    # API 返回时隐藏密钥，只暴露是否已配置，方便前端做诊断提示。
    return success({**settings, "api_key": "***" if settings.get("api_key") else ""})


@router.get("/platform/memory/vectors/info")
def get_platform_vector_memory_info(
    drama_id: int | None = Query(default=None),
) -> dict:
    """查询指定剧本或全局 Qdrant 集合的状态和向量数量信息。"""
    info = vector_memory_service.get_drama_collection_info(drama_id=drama_id)
    return success(info)


@router.post("/platform/memory/vectors/clean")
def clean_platform_vector_memory(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """按剧本维度批量清理向量数据，并重置数据库 memory_items.embedding_ref。"""
    body = payload or {}
    drama_id = body.get("drama_id")
    if not drama_id:
        raise bad_request("drama_id 必填")
    res = vector_memory_service.clean_drama_memory_vectors(db, drama_id=int(drama_id))
    return success(res)


@router.delete("/platform/memory/vectors/collection")
def delete_platform_vector_collection(
    drama_id: int = Query(...),
) -> dict:
    """删除指定剧本在 Qdrant 中的独立 Collection。"""
    if not drama_id:
        raise bad_request("drama_id 必填")
    res = vector_memory_service.delete_drama_collection(drama_id=int(drama_id))
    return success(res)


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


@router.post("/platform/quality-reports")
def create_quality_report(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """创建并保存一条创作质量评估报告。"""
    return success(quality_report_service.create_quality_report(db, payload or {}))


@router.get("/platform/observability/metrics")
def get_observability_metrics(db: Session = Depends(get_db)) -> dict:
    """获取系统可观测性与健康度指标看板数据。"""
    return success(quality_report_service.get_observability_metrics(db))


@router.post("/platform/quality/golden-eval")
def trigger_golden_dataset_evaluation(db: Session = Depends(get_db)) -> dict:
    """触发 Golden Dataset 自动化质量基准评估流水线。"""
    from app.quality.golden_eval import run_golden_eval_pipeline
    return success(run_golden_eval_pipeline())


@router.get("/platform/audio/voice-profiles")
def list_voice_profiles(drama_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    """查询短剧角色声音配置档案列表。"""
    return success(audioDesignService.list_character_voice_profiles(db, drama_id=drama_id))


@router.post("/platform/audio/voice-profiles/generate")
def generate_voice_profiles(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """自动分析角色人设并生成 VoiceProfile 声音档案。"""
    body = payload or {}
    drama_id = body.get("drama_id")
    if not drama_id:
        raise bad_request("drama_id 必填")
    return success(audioDesignService.upsert_character_voice_profiles(db, drama_id=int(drama_id)))


@router.get("/platform/audio/music-bible")
def get_music_bible(drama_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    """获取整剧 Music Bible 音乐设计规范。"""
    item = audioDesignService.get_music_bible(db, drama_id=drama_id)
    if not item:
        return success({})
    return success(item)


@router.post("/platform/audio/music-bible/generate")
def generate_music_bible(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """根据短剧风格与主题生成整剧 Music Bible。"""
    body = payload or {}
    drama_id = body.get("drama_id")
    if not drama_id:
        raise bad_request("drama_id 必填")
    return success(audioDesignService.upsert_music_bible(db, drama_id=int(drama_id)))


@router.get("/platform/audio/music-cues")
def list_music_cues(
    drama_id: int | None = Query(default=None),
    episode_id: int | None = Query(default=None),
    limit: int = Query(default=100),
    db: Session = Depends(get_db),
) -> dict:
    """查询分镜音乐与音效 Cue 列表。"""
    return success(audioDesignService.list_music_cues(db, drama_id=drama_id, episode_id=episode_id, limit=limit))


@router.post("/platform/audio/design/generate")
def generate_audio_design(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """一键生成整剧声音与分镜音乐全套设计。"""
    body = payload or {}
    drama_id = body.get("drama_id")
    if not drama_id:
        raise bad_request("drama_id 必填")
    return success(
        audioDesignService.generate_voice_music_design(
            db,
            drama_id=int(drama_id),
            episode_id=body.get("episode_id"),
        )
    )


@router.put("/platform/audio/voice-profiles/{profile_id}")
def update_voice_profile(
    profile_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """更新角色声音档案（音色、语速、音高、采样率、参考音频等）。"""
    try:
        item = audioDesignService.update_character_voice_profile(db, profile_id, payload or {})
    except (TypeError, ValueError) as err:
        raise bad_request(str(err)) from err
    if not item:
        raise not_found("声音档案不存在")
    return success(item)


@router.post("/platform/audio/music/generate")
def generate_music_track(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """调用 Music Provider（Suno / Udio / 本地配乐库）生成配乐。"""
    from app.services.providers import get_music_provider, MusicGenerationOptions
    body = payload or {}
    provider_name = str(body.get("provider") or "suno").strip().lower()
    provider = get_music_provider(provider_name)
    config: dict = dict(body.get("config") or {})
    config_id = body.get("config_id")
    if config_id:
        config = aiConfigService.get_config(db, config_id) or {}
    elif not config:
        # 优先选择同名启用配置；兼容历史上使用 audio 作为音乐服务类型的记录。
        candidates = [
            *aiConfigService.list_configs(db, "music"),
            *aiConfigService.list_configs(db, "audio"),
        ]
        config = next(
            (
                item for item in candidates
                if item.get("is_active") and str(item.get("provider") or "").lower() == str(provider_name).lower()
            ),
            {},
        )
    if provider_name in {"suno", "udio"} and not config.get("base_url"):
        raise bad_request(f"请先配置 {provider_name} 音乐服务的 base_url 和 API Key")
    options = MusicGenerationOptions(
        prompt=body.get("prompt") or "cinematic dramatic background music",
        style=body.get("style"),
        mood=body.get("mood"),
        title=body.get("title"),
        bpm=body.get("bpm"),
        duration_seconds=int(body.get("duration_seconds") or 30),
        instrumental=bool(body.get("instrumental", True)),
        tags=body.get("tags") or [],
        reference_audio_url=body.get("reference_audio_url"),
        extra_options=body.get("extra_options") or {},
    )
    result = provider.generate_music(config, log, options)
    if result.error:
        raise ai_provider_error(result.error)
    return success(result.model_dump())


@router.post("/platform/audio/mix-ducking")
def mix_multitrack_with_ducking(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """智能多轨混音：对白、BGM、音效多轨合并，自动执行 Audio Ducking 侧链压制并统一 EBU R128 (-16 LUFS) 响度调平。"""
    from app.services.loudnessService import mix_multitrack_with_ducking as do_mix
    body = payload or {}
    output_path = body.get("output_path")
    if not output_path:
        raise bad_request("output_path 必填")
    res = do_mix(
        dialogue_path=body.get("dialogue_path"),
        bgm_path=body.get("bgm_path"),
        sfx_path=body.get("sfx_path"),
        output_path=output_path,
        target_lufs=float(body.get("target_lufs") or -16.0),
        bgm_ducking_reduction_db=float(body.get("bgm_ducking_reduction_db") or -12.0),
    )
    return success(res)



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


@router.get("/platform/queue/metrics")
def get_queue_metrics(
    hours: int = Query(default=24, ge=1, le=168),
    queue_name: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """返回队列调度指标；最多回看 7 天，避免监控查询长期占用数据库。"""
    return success(
        queue_service.queue_metrics(
            db,
            hours=hours,
            queue_name=queue_name,
            task_type=task_type,
        )
    )


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
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    jobs = queue_service.list_queue_jobs(
        db,
        queue_name=queue_name,
        status=status,
        task_type=task_type,
        workflow_run_id=workflow_run_id,
        limit=limit,
        offset=offset,
    )
    # total 用于分页；summary 忽略 status 参数，展示当前队列范围内的完整状态分布。
    total = queue_service.count_queue_jobs(
        db,
        queue_name=queue_name,
        status=status,
        task_type=task_type,
        workflow_run_id=workflow_run_id,
    )
    summary = queue_service.queue_status_summary(
        db,
        queue_name=queue_name,
        task_type=task_type,
        workflow_run_id=workflow_run_id,
    )
    return success({"items": jobs, "total": total, "limit": limit, "offset": offset, "summary": summary})


@router.get("/platform/queue/jobs/{job_id}")
def get_queue_job_detail(job_id: str, db: Session = Depends(get_db)) -> dict:
    """查询单个队列任务完整载荷、执行结果与错误信息。"""
    item = queue_service.get_queue_job(db, job_id)
    if not item:
        raise not_found("队列任务不存在")
    return success(item)


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


@router.get("/platform/queue/jobs/{job_id}/stream")
async def stream_queue_job_progress(
    job_id: str,
    interval: float = Query(default=1.0, ge=0.2, le=5.0),
    max_duration: int = Query(default=600, le=3600),
):
    """Server-Sent Events (SSE) 实时推送单个队列任务状态与执行进度。"""
    async def event_generator():
        start_time = asyncio.get_event_loop().time()
        last_status = None
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_duration:
                yield f"event: timeout\ndata: {json_dumps({'message': 'Stream timeout reached'})}\n\n"
                break
            try:
                with db_session_module.session_scope() as db:
                    job = queue_service.get_queue_job(db, job_id)
                if not job:
                    yield f"event: error\ndata: {json_dumps({'error': 'Queue job not found'})}\n\n"
                    break
                status = job.get("status")
                if status != last_status:
                    last_status = status
                    yield f"event: job_update\ndata: {json_dumps(job)}\n\n"
                else:
                    yield ": ping\n\n"
                if status in queue_service.TERMINAL_JOB_STATUSES:
                    yield f"event: job_finished\ndata: {json_dumps({'status': status, 'job_id': job_id})}\n\n"
                    break
            except Exception as err:
                yield f"event: error\ndata: {json_dumps({'error': str(err)})}\n\n"
                break
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.post("/platform/workflows/{workflow_run_id}/pause")
def pause_workflow(workflow_run_id: str, db: Session = Depends(get_db)) -> dict:
    """暂停处于运行中的工作流。"""
    try:
        item = workflow_service.pause_workflow_run(db, workflow_run_id)
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/resume")
def resume_workflow(workflow_run_id: str, db: Session = Depends(get_db)) -> dict:
    """恢复已暂停的工作流。"""
    try:
        item = workflow_service.resume_workflow_run(db, workflow_run_id)
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/cancel")
def cancel_workflow(
    workflow_run_id: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """取消工作流。"""
    try:
        item = workflow_service.cancel_workflow_run(db, workflow_run_id, reason=(payload or {}).get("reason"))
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.post("/platform/workflows/{workflow_run_id}/steps/{step_key}/approve")
def approve_workflow_step(
    workflow_run_id: str,
    step_key: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """人工审批放行关键工作流步骤 (Human-in-the-loop)。"""
    body = payload or {}
    try:
        result = workflow_service.approve_workflow_step(
            db,
            workflow_run_id,
            step_key,
            approver=body.get("approver") or "user",
            feedback=body.get("feedback"),
            modified_output=body.get("modified_output"),
        )
        if body.get("auto_resume") and result.get("next_step"):
            resume_result = workflow_executor.run_until_blocked(
                db,
                None,
                workflow_run_id,
                body.get("executor_options") or {},
            )
            result["auto_resume_result"] = resume_result
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(result)


@router.post("/platform/workflows/{workflow_run_id}/steps/{step_key}/reject")
def reject_workflow_step(
    workflow_run_id: str,
    step_key: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """人工驳回关键工作流步骤 (Human-in-the-loop)。"""
    body = payload or {}
    try:
        result = workflow_service.reject_workflow_step(
            db,
            workflow_run_id,
            step_key,
            rejector=body.get("rejector") or "user",
            reason=body.get("reason"),
            action=body.get("action") or "retry",
        )
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(result)


@router.post("/platform/workflows/{workflow_run_id}/retry-step/{step_key}")
def retry_workflow_step(
    workflow_run_id: str,
    step_key: str,
    db: Session = Depends(get_db),
) -> dict:
    """精准重试工作流的指定步骤。"""
    try:
        item = workflow_service.retry_workflow_step(db, workflow_run_id, step_key)
    except ValueError as e:
        raise bad_request(str(e)) from e
    return success(item)


@router.get("/platform/workflows/{workflow_run_id}/stream")
async def stream_workflow_progress(
    workflow_run_id: str,
    interval: float = Query(default=1.0, ge=0.2, le=5.0),
    max_duration: int = Query(default=1800, le=7200),
):
    """Server-Sent Events (SSE) 实时推送工作流状态演进与节点进度更新。"""
    async def event_generator():
        start_time = asyncio.get_event_loop().time()
        last_state_hash = None
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_duration:
                yield f"event: timeout\ndata: {json_dumps({'message': 'Stream timeout reached'})}\n\n"
                break
            try:
                with db_session_module.session_scope() as db:
                    state = workflow_service.get_workflow_execution_state(db, workflow_run_id)
                if not state:
                    yield f"event: error\ndata: {json_dumps({'error': 'Workflow not found'})}\n\n"
                    break

                current_status = (state.get("workflow") or {}).get("status")
                # 序列化为 JSON 计算摘要比对，检测任意节点或整体状态变更
                state_str = json_dumps(state)
                state_hash = hash(state_str)

                if state_hash != last_state_hash:
                    last_state_hash = state_hash
                    yield f"event: workflow_state\ndata: {state_str}\n\n"
                else:
                    yield ": ping\n\n"

                # 终端态（完成、失败、取消）主动结束 SSE 流
                if current_status in ("completed", "failed", "cancelled"):
                    yield f"event: workflow_finished\ndata: {json_dumps({'status': current_status, 'workflow_run_id': workflow_run_id})}\n\n"
                    break
            except Exception as err:
                yield f"event: error\ndata: {json_dumps({'error': str(err)})}\n\n"
                break

            await asyncio.sleep(interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/platform/agent-runs")
def create_agent_run(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    return success(skill_registry.create_agent_run(db, payload or {}))


@router.get("/platform/cascades/stale-assets")
def get_stale_assets(drama_id: int = Query(..., ge=1), db: Session = Depends(get_db)) -> dict:
    """获取指定剧集由于角色/场景修改导致的已失效 (stale) 资产列表。"""
    from app.services import cascadeService
    return success(cascadeService.get_stale_assets_summary(db, drama_id))


@router.post("/platform/cascades/rerun-stale")
def rerun_stale_assets(payload: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    """一键重跑所有标记为失效 (stale) 的资产。"""
    drama_id = (payload or {}).get("drama_id")
    if not drama_id:
        raise bad_request("drama_id is required")
    from app.services import cascadeService
    return success(cascadeService.rerun_stale_assets(db, int(drama_id), (payload or {}).get("asset_type") or "all"))

