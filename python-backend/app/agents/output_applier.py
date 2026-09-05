"""Agent 输出落库适配器。

Agent Runtime 只负责调用模型并解析结构化结果；这里负责把结果写回业务表。
这样可以避免每个 Agent 自己拼 SQL，也方便后续统一加审核、回滚和版本控制。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.context import memory_service
from app.db.session import fetch_one, result_to_dict
from app.platform_common import json_dumps, json_loads, now_iso
from app.skills import registry_service as skill_registry
from app.workflows import run_service


OUTPUT_APPLIER_STEPS = {
    "requirement_analysis",
    "drama_bible_generation",
    "adaptation_plan_generation",
    "episode_outline_generation",
    "episode_script_generation",
    "character_extraction",
    "scene_extraction",
    "prop_extraction",
    "storyboard_generation",
    "continuity_check",
    "creative_quality_review",
    "novel_ingestion",
    "chapter_slicing",
    "long_memory_indexing",
    "novel_bible_extraction",
}


def normalize_agent_payload(agent_result: dict[str, Any] | None) -> dict[str, Any]:
    """把模型输出统一整理成 dict，便于后续写入数据库。

    模型可能输出 JSON object、JSON array，也可能 JSON 解析失败只剩原文。
    落库层不假设模型一定完美，而是尽量保留可追溯的原始结果。
    """
    agent_result = agent_result or {}
    parsed = agent_result.get("parsed_output")
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"items": parsed}
    if parsed not in (None, ""):
        return {"value": parsed}
    return {"raw_output": agent_result.get("raw_output") or "", "parse_error": agent_result.get("parse_error") or ""}


def apply_agent_output(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """按 workflow step 类型应用 Agent 结果。

    短期状态写入 workflow_runs.state；可长期复用的创作决策写入 memory_items；
    质量检查结果写入 quality_reports，避免混在普通 step output 中不好检索。
    """
    step_key = step.get("step_key")
    if step_key not in OUTPUT_APPLIER_STEPS:
        return {"status": "skipped", "reason": "当前步骤无需业务落库"}

    payload = normalize_agent_payload(agent_result)
    if step_key == "requirement_analysis":
        return _apply_requirement_analysis(db, run, payload)
    if step_key == "drama_bible_generation":
        return _apply_drama_bible(db, run, payload)
    if step_key == "adaptation_plan_generation":
        return _apply_adaptation_plan(db, run, step, agent_result, payload)
    if step_key == "episode_outline_generation":
        return _apply_episode_outline(db, run, payload)
    if step_key == "episode_script_generation":
        return _apply_episode_script(db, run, payload)
    if step_key == "character_extraction":
        return _apply_character_extraction(db, run, payload)
    if step_key == "scene_extraction":
        return _apply_scene_extraction(db, run, payload)
    if step_key == "prop_extraction":
        return _apply_prop_extraction(db, run, payload)
    if step_key == "storyboard_generation":
        return _apply_storyboard_generation(db, run, payload)
    if step_key == "novel_ingestion":
        return _apply_novel_ingestion(db, run, payload)
    if step_key == "chapter_slicing":
        return _apply_chapter_slicing(db, run, payload)
    if step_key == "long_memory_indexing":
        return _apply_long_memory_indexing(db, run, payload)
    if step_key == "novel_bible_extraction":
        return _apply_novel_bible(db, run, payload)
    if step_key == "continuity_check":
        return _apply_continuity_check(db, run, step, payload, agent_result)
    if step_key == "creative_quality_review":
        return _apply_quality_review(db, run, step, payload, agent_result)
    return {"status": "skipped", "reason": "未匹配到落库策略"}


def _apply_requirement_analysis(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """需求分析属于短期生产状态，写入 workflow state 供后续步骤读取。"""
    workflow = _merge_workflow_state(db, run["id"], {"requirement_analysis": payload})
    return {"status": "applied", "target": "workflow_runs.state", "workflow_run_id": workflow.get("id")}


def _apply_drama_bible(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """剧集 Bible 是全剧长期设定，优先写入 dramas.metadata，并同步到 workflow state。"""
    targets = ["workflow_runs.state"]
    _merge_workflow_state(db, run["id"], {"drama_bible": payload})
    drama_id = run.get("drama_id")
    if drama_id:
        updated = _merge_drama_metadata(
            db,
            int(drama_id),
            {
                "drama_bible": payload,
                "agent_outputs": {
                    "drama_bible_generation": {
                        "workflow_run_id": run.get("id"),
                        "updated_at": now_iso(),
                    }
                },
            },
        )
        if updated:
            targets.append("dramas.metadata")
    return {"status": "applied", "target": targets, "drama_id": drama_id}


def _apply_adaptation_plan(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    agent_result: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """小说改编计划既写入短期状态，也沉淀为长期记忆，后续分集改编可检索复用。"""
    _merge_workflow_state(db, run["id"], {"adaptation_plan": payload})
    drama_id = run.get("drama_id")
    if not drama_id:
        return {"status": "applied", "target": "workflow_runs.state", "memory_item_id": None}

    memory = memory_service.add_memory_item(
        db,
        {
            "drama_id": int(drama_id),
            "episode_id": run.get("episode_id"),
            "memory_type": "adaptation_plan",
            "scope": "drama",
            "title": _pick_text(payload, ("title", "name")) or "小说改编计划",
            "content": json_dumps(payload),
            "summary": _pick_text(payload, ("summary", "strategy", "adaptation_strategy", "logline")),
            "keywords": _extract_keywords(payload),
            "source_type": "workflow_step",
            "source_id": str(step.get("id")),
            "metadata": {
                "workflow_run_id": run.get("id"),
                "agent_run_id": agent_result.get("agent_run_id"),
                "prompt_run_id": agent_result.get("prompt_run_id"),
            },
        },
    )
    if agent_result.get("agent_run_id"):
        # 把新增长期记忆反挂到 agent_run，方便排查这次 Agent 影响了哪些上下文。
        skill_registry.update_agent_run(db, agent_result["agent_run_id"], {"memory_refs": [memory["id"]]})
    return {"status": "applied", "target": ["workflow_runs.state", "memory_items"], "memory_item_id": memory["id"]}


def _apply_episode_outline(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """分集大纲写入 workflow state 并更新到 dramas.metadata。"""
    _merge_workflow_state(db, run["id"], {"episode_outline": payload})
    drama_id = run.get("drama_id")
    targets = ["workflow_runs.state"]
    if drama_id:
        _merge_drama_metadata(
            db,
            int(drama_id),
            {
                "episode_outline": payload,
                "agent_outputs": {
                    "episode_outline_generation": {
                        "workflow_run_id": run.get("id"),
                        "updated_at": now_iso(),
                    }
                },
            },
        )
        targets.append("dramas.metadata")
    return {"status": "applied", "target": targets, "drama_id": drama_id}


def _apply_episode_script(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """单集剧本写入 episodes.script_content 并同步至 workflow state。"""
    _merge_workflow_state(db, run["id"], {"episode_script": payload})
    episode_id = run.get("episode_id")
    script_content = payload.get("script_content") or payload.get("content") or payload.get("script") or json_dumps(payload)
    targets = ["workflow_runs.state"]
    if episode_id:
        db.execute(
            text("UPDATE episodes SET script_content = :content, updated_at = :now WHERE id = :id"),
            {"id": int(episode_id), "content": str(script_content), "now": now_iso()},
        )
        targets.append("episodes.script_content")
    return {"status": "applied", "target": targets, "episode_id": episode_id}


def _apply_character_extraction(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """角色提取 Agent：将解析出的角色列表落库到 characters 表并智能更新锚点。"""
    items = payload.get("characters") or payload.get("items") or (payload if isinstance(payload, list) else [])
    if isinstance(payload, dict) and not items:
        items = [payload]
    _merge_workflow_state(db, run["id"], {"characters": items})
    drama_id = run.get("drama_id")
    created_ids = []
    if drama_id:
        now = now_iso()
        for char in items:
            if not isinstance(char, dict):
                continue
            name = (char.get("name") or "").strip()
            if not name:
                continue
            existing = fetch_one(
                db,
                "SELECT id, identity_anchors FROM characters WHERE drama_id = :drama_id AND name = :name AND deleted_at IS NULL",
                {"drama_id": int(drama_id), "name": name},
            )
            anchors = char.get("identity_anchors") or char.get("anchors") or {}
            if existing:
                db.execute(
                    text(
                        """
                        UPDATE characters SET
                            role = COALESCE(:role, role),
                            description = COALESCE(:desc, description),
                            personality = COALESCE(:personality, personality),
                            appearance = COALESCE(:appearance, appearance),
                            identity_anchors = :anchors,
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": existing["id"],
                        "role": char.get("role"),
                        "desc": char.get("description"),
                        "personality": char.get("personality"),
                        "appearance": char.get("appearance"),
                        "anchors": json_dumps(anchors) if anchors else existing.get("identity_anchors"),
                        "now": now,
                    },
                )
                created_ids.append(existing["id"])
            else:
                res = db.execute(
                    text(
                        """
                        INSERT INTO characters (
                            drama_id, name, role, description, personality, appearance, identity_anchors, created_at, updated_at
                        ) VALUES (
                            :drama_id, :name, :role, :desc, :personality, :appearance, :anchors, :now, :now
                        )
                        """
                    ),
                    {
                        "drama_id": int(drama_id),
                        "name": name,
                        "role": char.get("role", "supporting"),
                        "desc": char.get("description", ""),
                        "personality": char.get("personality", ""),
                        "appearance": char.get("appearance", ""),
                        "anchors": json_dumps(anchors) if anchors else "{}",
                        "now": now,
                    },
                )
                created_ids.append(res.lastrowid)
    return {"status": "applied", "target": ["characters", "workflow_runs.state"], "character_ids": created_ids}


def _apply_scene_extraction(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """场景提取 Agent：将场景解析落库到 scenes 表。"""
    items = payload.get("scenes") or payload.get("items") or (payload if isinstance(payload, list) else [])
    if isinstance(payload, dict) and not items:
        items = [payload]
    _merge_workflow_state(db, run["id"], {"scenes": items})
    drama_id = run.get("drama_id")
    episode_id = run.get("episode_id")
    created_ids = []
    if drama_id:
        now = now_iso()
        for sc in items:
            if not isinstance(sc, dict):
                continue
            loc = (sc.get("location") or sc.get("name") or "").strip()
            if not loc:
                continue
            prompt = sc.get("prompt") or sc.get("visual_prompt") or ""
            if sc.get("atmosphere") and sc.get("atmosphere") not in prompt:
                prompt = f"{prompt} 氛围: {sc.get('atmosphere')}".strip()
            res = db.execute(
                text(
                    """
                    INSERT INTO scenes (
                        drama_id, episode_id, location, time, prompt, created_at, updated_at
                    ) VALUES (
                        :drama_id, :episode_id, :location, :time, :prompt, :now, :now
                    )
                    """
                ),
                {
                    "drama_id": int(drama_id),
                    "episode_id": int(episode_id) if episode_id else None,
                    "location": loc,
                    "time": sc.get("time", "白天"),
                    "prompt": prompt,
                    "now": now,
                },
            )
            created_ids.append(res.lastrowid)
    return {"status": "applied", "target": ["scenes", "workflow_runs.state"], "scene_ids": created_ids}


def _apply_prop_extraction(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """道具提取 Agent：将关键道具落库到 props 表。"""
    items = payload.get("props") or payload.get("items") or (payload if isinstance(payload, list) else [])
    if isinstance(payload, dict) and not items:
        items = [payload]
    _merge_workflow_state(db, run["id"], {"props": items})
    drama_id = run.get("drama_id")
    episode_id = run.get("episode_id")
    created_ids = []
    if drama_id:
        now = now_iso()
        for p in items:
            if not isinstance(p, dict):
                continue
            name = (p.get("name") or "").strip()
            if not name:
                continue
            res = db.execute(
                text(
                    """
                    INSERT INTO props (
                        drama_id, episode_id, name, type, description, prompt, created_at, updated_at
                    ) VALUES (
                        :drama_id, :episode_id, :name, :type, :desc, :prompt, :now, :now
                    )
                    """
                ),
                {
                    "drama_id": int(drama_id),
                    "episode_id": int(episode_id) if episode_id else None,
                    "name": name,
                    "type": p.get("type", "关键道具"),
                    "desc": p.get("description", ""),
                    "prompt": p.get("prompt", ""),
                    "now": now,
                },
            )
            created_ids.append(res.lastrowid)
    return {"status": "applied", "target": ["props", "workflow_runs.state"], "prop_ids": created_ids}


def _apply_storyboard_generation(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """分镜导演 Agent：将拆解的分镜脚本批量落库到 storyboards 表。"""
    items = payload.get("storyboards") or payload.get("shots") or payload.get("items") or (payload if isinstance(payload, list) else [])
    if isinstance(payload, dict) and not items:
        items = [payload]
    _merge_workflow_state(db, run["id"], {"storyboards": items})
    episode_id = run.get("episode_id")
    created_ids = []
    if episode_id:
        now = now_iso()
        for idx, shot in enumerate(items, 1):
            if not isinstance(shot, dict):
                continue
            res = db.execute(
                text(
                    """
                    INSERT INTO storyboards (
                        episode_id, storyboard_number, title, description, location, time, duration,
                        dialogue, narration, action, atmosphere, image_prompt, video_prompt, shot_type,
                        created_at, updated_at
                    ) VALUES (
                        :episode_id, :num, :title, :desc, :location, :time, :duration,
                        :dialogue, :narration, :action, :atmosphere, :image_prompt, :video_prompt, :shot_type,
                        :now, :now
                    )
                    """
                ),
                {
                    "episode_id": int(episode_id),
                    "num": shot.get("storyboard_number") or idx,
                    "title": shot.get("title") or f"镜头 {idx}",
                    "desc": shot.get("description") or "",
                    "location": shot.get("location") or "",
                    "time": shot.get("time") or "白天",
                    "duration": float(shot.get("duration") or 3.0),
                    "dialogue": shot.get("dialogue") or "",
                    "narration": shot.get("narration") or "",
                    "action": shot.get("action") or "",
                    "atmosphere": shot.get("atmosphere") or "",
                    "image_prompt": shot.get("image_prompt") or shot.get("visual_prompt") or "",
                    "video_prompt": shot.get("video_prompt") or "",
                    "shot_type": shot.get("shot_type") or "中景",
                    "now": now,
                },
            )
            created_ids.append(res.lastrowid)
    return {"status": "applied", "target": ["storyboards", "workflow_runs.state"], "storyboard_ids": created_ids}


def _apply_continuity_check(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    payload: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """连续性检查 Agent：将一致性审查结果存入 state 并生成记忆快照。"""
    _merge_workflow_state(db, run["id"], {"continuity_check": payload})
    drama_id = run.get("drama_id")
    memory_id = None
    if drama_id:
        memory = memory_service.add_memory_item(
            db,
            {
                "drama_id": int(drama_id),
                "episode_id": run.get("episode_id"),
                "memory_type": "continuity",
                "scope": "drama",
                "title": f"连续性审查记录 - {now_iso()[:10]}",
                "content": json_dumps(payload),
                "summary": _pick_text(payload, ("summary", "verdict", "risk_summary")),
                "keywords": ["continuity", "audit"],
                "source_type": "workflow_step",
                "source_id": str(step.get("id")),
            },
        )
        memory_id = memory["id"]
    return {"status": "applied", "target": ["workflow_runs.state", "memory_items"], "memory_item_id": memory_id}



def _apply_novel_ingestion(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """小说导入清洗：写入 workflow state 与 dramas.metadata。"""
    _merge_workflow_state(db, run["id"], {"novel_ingestion": payload})
    drama_id = run.get("drama_id")
    targets = ["workflow_runs.state"]
    if drama_id:
        _merge_drama_metadata(
            db,
            int(drama_id),
            {
                "novel_source": payload,
                "agent_outputs": {"novel_ingestion": {"updated_at": now_iso()}},
            },
        )
        targets.append("dramas.metadata")
    return {"status": "applied", "target": targets, "drama_id": drama_id}


def _apply_chapter_slicing(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """小说章节切片：写入 memory_items (novel_slice) 供向量与关键词检索。"""
    items = payload.get("chapters") or payload.get("slices") or payload.get("items") or (payload if isinstance(payload, list) else [])
    if isinstance(payload, dict) and not items:
        items = [payload]
    _merge_workflow_state(db, run["id"], {"chapter_slicing": items})
    drama_id = run.get("drama_id")
    slice_ids = []
    if drama_id:
        for idx, ch in enumerate(items, 1):
            if not isinstance(ch, dict):
                continue
            content = ch.get("content") or ch.get("text") or ""
            if not content:
                continue
            title = ch.get("title") or f"第{idx}章"
            summary = ch.get("summary") or ch.get("outline") or ""
            mem = memory_service.add_memory_item(
                db,
                {
                    "drama_id": int(drama_id),
                    "memory_type": "novel_slice",
                    "scope": "drama",
                    "title": title,
                    "content": content,
                    "summary": summary,
                    "keywords": ch.get("keywords") or [],
                    "metadata": {"chapter_index": idx, "workflow_run_id": run.get("id")},
                },
            )
            slice_ids.append(mem["id"])
    return {"status": "applied", "target": ["workflow_runs.state", "memory_items"], "slice_ids": slice_ids}


def _apply_long_memory_indexing(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """长期记忆索引：将世界观、核心设定和关键伏笔写入 memory_items。"""
    _merge_workflow_state(db, run["id"], {"long_memory_indexing": payload})
    drama_id = run.get("drama_id")
    memory_ids = []
    if drama_id:
        settings_list = payload.get("worldview") or payload.get("settings") or payload.get("memories") or []
        if isinstance(settings_list, list):
            for s in settings_list:
                if not isinstance(s, dict):
                    continue
                content = s.get("content") or s.get("description") or json_dumps(s)
                mem = memory_service.add_memory_item(
                    db,
                    {
                        "drama_id": int(drama_id),
                        "memory_type": s.get("type", "worldview"),
                        "scope": "drama",
                        "title": s.get("title", "世界观设定"),
                        "content": content,
                        "summary": s.get("summary", ""),
                        "keywords": s.get("keywords") or [],
                    },
                )
                memory_ids.append(mem["id"])
    return {"status": "applied", "target": ["workflow_runs.state", "memory_items"], "memory_ids": memory_ids}


def _apply_novel_bible(db: Session, run: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """原著设定提取：写入 dramas.metadata.novel_bible 与 workflow state。"""
    _merge_workflow_state(db, run["id"], {"novel_bible": payload})
    drama_id = run.get("drama_id")
    targets = ["workflow_runs.state"]
    if drama_id:
        _merge_drama_metadata(
            db,
            int(drama_id),
            {
                "novel_bible": payload,
                "agent_outputs": {"novel_bible_extraction": {"updated_at": now_iso()}},
            },
        )
        targets.append("dramas.metadata")
    return {"status": "applied", "target": targets, "drama_id": drama_id}


def _apply_quality_review(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    payload: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """创意质检单独入表，便于后续做人工确认、返工队列和质量趋势统计。"""
    report = _insert_quality_report(db, run, step, payload)
    _merge_workflow_state(
        db,
        run["id"],
        {
            "latest_quality_report_id": report.get("id"),
            "latest_quality_review": {
                "score": report.get("score"),
                "status": report.get("status"),
                "prompt_run_id": agent_result.get("prompt_run_id"),
            },
        },
    )
    return {"status": "applied", "target": ["quality_reports", "workflow_runs.state"], "quality_report_id": report["id"]}


def _merge_workflow_state(db: Session, workflow_run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    current = run_service.get_workflow_run(db, workflow_run_id, include_steps=False) or {"state": {}}
    state = dict(current.get("state") or {})
    _deep_merge(state, patch)
    return run_service.update_workflow_run(db, workflow_run_id, {"state": state})


def _merge_drama_metadata(db: Session, drama_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
    row = fetch_one(db, "SELECT id, metadata FROM dramas WHERE id = :id AND deleted_at IS NULL", {"id": drama_id})
    if not row:
        return None
    metadata = json_loads(row.get("metadata"), {}) or {}
    if not isinstance(metadata, dict):
        metadata = {"legacy_metadata": metadata}
    _deep_merge(metadata, patch)
    db.execute(
        text("UPDATE dramas SET metadata = :metadata, updated_at = :updated_at WHERE id = :id"),
        {"id": drama_id, "metadata": json_dumps(metadata), "updated_at": now_iso()},
    )
    return {"id": drama_id, "metadata": metadata}


def _insert_quality_report(
    db: Session,
    run: dict[str, Any],
    step: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = now_iso()
    issues = payload.get("issues") or payload.get("missing_fields") or payload.get("continuity_risks") or []
    suggestions = payload.get("suggestions") or []
    score = _to_float(payload.get("score") or payload.get("overall_score"))
    status = "open" if issues or suggestions else "passed"
    res = db.execute(
        text(
            """
            INSERT INTO quality_reports (
                workflow_run_id, workflow_step_id, drama_id, episode_id, report_type, status,
                score, issues, suggestions, raw_report, created_at, updated_at
            ) VALUES (
                :workflow_run_id, :workflow_step_id, :drama_id, :episode_id, :report_type, :status,
                :score, :issues, :suggestions, :raw_report, :now, :now
            )
            """
        ),
        {
            "workflow_run_id": run.get("id"),
            "workflow_step_id": str(step.get("id")) if step.get("id") is not None else None,
            "drama_id": run.get("drama_id"),
            "episode_id": run.get("episode_id"),
            "report_type": "creative_review",
            "status": status,
            "score": score,
            "issues": json_dumps(issues),
            "suggestions": json_dumps(suggestions),
            "raw_report": json_dumps(payload),
            "now": now,
        },
    )
    row = db.execute(text("SELECT * FROM quality_reports WHERE id = :id"), {"id": res.lastrowid}).first()
    return result_to_dict(row)


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """只合并 dict，列表和标量整体替换，避免把剧本段落数组误拼接。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _pick_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_keywords(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("keywords") or payload.get("tags") or payload.get("themes") or []
    if isinstance(raw, str):
        return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
