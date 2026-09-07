"""Script Studio 剧本创作工坊 V2.0 API 路由与 SSE 实时推送通道。

【接口与能力清单】
1. SSE 实时事件流通道：
   - GET /api/v1/script-studio/dramas/{drama_id}/events (Server-Sent Events 持续推送工作流节点进度、质检分数、修补变化与级联状态)
2. 创作工坊核心控制：
   - POST /api/v1/script-studio/dramas/{drama_id}/pipeline/start (触发 LangGraph 5阶段状态机创作流)
   - POST /api/v1/script-studio/dramas/{drama_id}/lock (剧本定稿锁定与版本递增)
   - POST /api/v1/script-studio/dramas/{drama_id}/sync-visual (提取 Script-to-Visual Bridge 契约并同步视听工坊)
   - POST /api/v1/script-studio/dramas/{drama_id}/cascade-invalidate (触发大纲修改后的级联失效)
   - POST /api/v1/script-studio/dramas/{drama_id}/episodes/{episode_num}/patch (对单集触发 AST 局部定向修补)
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.patch_router import PatchRouter
from app.agents.script_ast_parser import ScriptASTParser
from app.core.event_bus import EventBus
from app.core.response import success
from app.db.session import fetch_one, get_db
from app.platform_common import json_loads, now_iso
from app.services.cascadeService import mark_downstream_episodes_stale
from app.services.script_to_visual_bridge import ScriptToVisualBridge
from app.workflows.langgraph_script_pipeline import run_script_pipeline_for_drama

router = APIRouter(prefix="/script-studio", tags=["Script Studio V2.0"])


# =========================================================================
# 请求与响应 Schema
# =========================================================================
class PipelineStartRequest(BaseModel):
    user_prompt: str = Field(..., description="用户初始创作提示词或故事核心梗概")
    genre: str = Field("战神/都市逆袭", description="短剧题材类型")
    total_episodes: int = Field(5, description="总集数（推荐 5~80 集）")
    commercial_tag: str = Field("男频爽文-战神赘婿", description="商业定位标签")


class EpisodePatchRequest(BaseModel):
    issues: list[str] = Field(default_factory=list, description="需要修补的质检问题列表")
    deductions: dict[str, int] = Field(default_factory=dict, description="质检扣分项明细字典")


class CascadeInvalidateRequest(BaseModel):
    changed_episode_num: int = Field(..., description="修改了大纲或人设的源分集集数")


# =========================================================================
# 1. SSE 实时事件流通道
# =========================================================================
@router.get("/dramas/{drama_id}/events")
async def stream_drama_events(drama_id: int):
    """订阅指定短剧的 SSE 实时事件流（含进度、分集生成、质检雷达、修补与级联失效）。"""

    async def event_generator():
        async for event_dict in EventBus.subscribe_events(drama_id):
            yield EventBus.format_sse_message(event_dict)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================================
# 2. 创作工坊核心控制 API
# =========================================================================
@router.post("/dramas/{drama_id}/pipeline/start")
async def start_script_pipeline(
    drama_id: int,
    req: PipelineStartRequest,
    db: Session = Depends(get_db),
):
    """启动 LangGraph 剧本工业化创作工作流（在后台异步执行并发布 SSE 事件）。"""
    drama = fetch_one(db, "SELECT id, lock_status FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": drama_id})
    if not drama:
        raise HTTPException(status_code=404, detail="短剧项目不存在")
    if drama.get("lock_status", 0) == 1:
        raise HTTPException(status_code=400, detail="剧本已被定稿锁定，禁止重新生成！如需修改请先解锁或通过单集 Patch 修补。")

    # 异步在后台调度执行
    asyncio.create_task(
        _run_pipeline_background(
            drama_id=drama_id,
            user_prompt=req.user_prompt,
            genre=req.genre,
            total_episodes=req.total_episodes,
            commercial_tag=req.commercial_tag,
        )
    )

    EventBus.publish_event(
        drama_id,
        "pipeline_started",
        {"drama_id": drama_id, "total_episodes": req.total_episodes, "genre": req.genre},
    )

    return success({"status": "started", "drama_id": drama_id, "total_episodes": req.total_episodes})


async def _run_pipeline_background(
    drama_id: int,
    user_prompt: str,
    genre: str,
    total_episodes: int,
    commercial_tag: str,
):
    """后台执行 LangGraph 流水线并推送到事件总线。"""
    try:
        from app.db.session import get_db_context

        with get_db_context() as db:
            result = run_script_pipeline_for_drama(
                db=db,
                drama_id=drama_id,
                user_prompt=user_prompt,
                genre=genre,
                total_episodes=total_episodes,
                commercial_tag=commercial_tag,
            )
            EventBus.publish_event(
                drama_id,
                "pipeline_completed",
                {
                    "drama_id": drama_id,
                    "total_episodes": total_episodes,
                    "persisted_count": len(result.get("persisted_episode_refs", {})),
                    "version_cursor": result.get("version_cursor", 1),
                },
            )
    except Exception as e:
        EventBus.publish_event(
            drama_id,
            "pipeline_error",
            {"drama_id": drama_id, "error": str(e)},
        )


@router.post("/dramas/{drama_id}/lock")
def lock_drama_script(drama_id: int, db: Session = Depends(get_db)):
    """锁定剧本（定稿保护）：将 lock_status 置为 1，递增 version_cursor，发布锁定事件。"""
    drama = fetch_one(db, "SELECT id, lock_status, version_cursor FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": drama_id})
    if not drama:
        raise HTTPException(status_code=404, detail="短剧项目不存在")

    current_cursor = (drama.get("version_cursor") or 1) + 1
    db.execute(
        text("UPDATE dramas SET lock_status = 1, version_cursor = :vc, updated_at = :now WHERE id = :id"),
        {"vc": current_cursor, "now": now_iso(), "id": drama_id},
    )
    db.commit()

    EventBus.publish_event(
        drama_id,
        "status_locked",
        {"drama_id": drama_id, "lock_status": 1, "version_cursor": current_cursor},
    )

    return success({"drama_id": drama_id, "lock_status": 1, "version_cursor": current_cursor})


@router.post("/dramas/{drama_id}/sync-visual")
def sync_drama_to_visual(
    drama_id: int,
    episode_num: int = Query(1, description="需要同步的分集集数"),
    db: Session = Depends(get_db),
):
    """提取 Script-to-Visual Bridge 契约并同步到视听工坊。"""
    try:
        contract = ScriptToVisualBridge.extract_contract_from_script(db, drama_id=drama_id, episode_num=episode_num)
        sync_res = ScriptToVisualBridge.sync_contract_to_visual_studio(db, contract)

        EventBus.publish_event(
            drama_id,
            "bridge_synced",
            {
                "drama_id": drama_id,
                "episode_num": episode_num,
                "storyboard_count": sync_res.get("storyboard_count", 0),
                "task_fingerprints": sync_res.get("task_fingerprints", []),
            },
        )

        return success(sync_res)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"同步失败: {str(e)}")


@router.post("/dramas/{drama_id}/cascade-invalidate")
def trigger_cascade_invalidate(
    drama_id: int,
    req: CascadeInvalidateRequest,
    db: Session = Depends(get_db),
):
    """触发大纲修改后的下游剧集级联失效。"""
    cascade_res = mark_downstream_episodes_stale(db, drama_id=drama_id, modified_episode_num=req.changed_episode_num)
    stale_count = cascade_res.get("affected_episodes_count", 0)

    EventBus.publish_event(
        drama_id,
        "cascade_invalidated",
        {
            "drama_id": drama_id,
            "changed_episode_num": req.changed_episode_num,
            "stale_episodes_count": stale_count,
        },
    )

    return success({"drama_id": drama_id, "stale_episodes_count": stale_count})


@router.post("/dramas/{drama_id}/episodes/{episode_num}/patch")
def patch_single_episode(
    drama_id: int,
    episode_num: int,
    req: EpisodePatchRequest,
    db: Session = Depends(get_db),
):
    """对单集触发质检 AST 局部原位定向修补。"""
    ep = fetch_one(
        db,
        "SELECT id, title, script_content, ast_blocks FROM episodes WHERE drama_id = :did AND episode_number = :enum AND deleted_at IS NULL",
        {"did": drama_id, "enum": episode_num},
    )
    if not ep:
        raise HTTPException(status_code=404, detail="指定分集不存在")

    old_content = ep.get("script_content") or ""
    ast = ScriptASTParser.parse_to_ast(old_content)
    patched_ast = PatchRouter.patch_ast_by_qa(ast, req.issues, req.deductions)
    new_content = ScriptASTParser.stitch_ast(patched_ast)

    db.execute(
        text(
            "UPDATE episodes SET script_content = :sc, ast_blocks = :ast, patch_applied = 1, updated_at = :now WHERE id = :id"
        ),
        {
            "sc": new_content,
            "ast": patched_ast.model_dump_json(),
            "now": now_iso(),
            "id": ep["id"],
        },
    )
    db.commit()

    EventBus.publish_event(
        drama_id,
        "patch_applied",
        {
            "drama_id": drama_id,
            "episode_num": episode_num,
            "patched_blocks": ["hook", "reversal"] if req.deductions else ["climax"],
        },
    )

    return success({"episode_num": episode_num, "script_content": new_content})
