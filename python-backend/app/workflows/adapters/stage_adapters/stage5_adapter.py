from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.platform_common import now_iso
from app.tools.screenplay_feature_scanner import is_valid_character_speaker
from app.tools.shot_duration_calculator import clean_dialogue_text
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer
from app.schemas.script_graph_state import (
    AudioBible,
    CandidateTitleMatrix,
    CharacterAnchorStub,
    DoubleTrackProhibitions,
    EpisodeResourceManifest,
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    InterEpisodePhysicalContinuity,
    LiteraryScreenplayEpisodeModel,
    PropAnchorStub,
    RedBlueAuditReport,
    SceneAnchorStub,
    SeasonOutlineCard,
    StoryboardShot,
    StoryboardShotStub,
)
from app.workflows.adapters.stage_adapters.common import (
    _safe_json_loads,
    _ensure_valid_json_str,
    _dump_or_dict,
    _flatten_asset_collection,
    _get_table_columns,
    sync_stage_memories_to_vector_db,
    persist_audit_report,
    fetch_all,
    fetch_one,
    get_short_memories,
    publish_drama_event,
    publish_drama_read_projection,
    publish_episode_read_projection,
    set_short_memories,
)

log = get_logger("lmd.storage_adapter")

def persist_stage5(db: Session, drama_id: int, state: EpisodeScopedSubState | GlobalDramaMasterState | Any) -> None:
    """阶段 5 原子落库：写入 episodes 正文内容、AST 分块、节奏自检与定稿锁定状态。
    严格遵循单一事实源 (SSOT) 与物理分离原则：
    1. script_content 仅存储纯视听 Markdown 文本，绝不混杂元数据与 JSON 序列化；
    2. ast_blocks 存储语法树及视听节点分块；
    3. physical_snapshot_start / physical_snapshot_end 独立存储上下集时空连续性快照；
    4. audit_verdict / audit_report 独立存储剧本自检与质检合规数据；
    5. outline_id 关联分集大纲表，杜绝在 episodes 表重复存储大纲描述与悬念字段。
    """
    log.info("【阶段 5 落库】开始持久化短剧 [%s] 的文学剧本工笔正文...", drama_id)
    now = now_iso()

    def _state_val(key: str, default: Any = None) -> Any:
        if isinstance(state, dict):
            return state.get(key, default)
        return getattr(state, key, default)

    # 解析剧本字典：兼容 GlobalDramaMasterState, EpisodeScopedSubState 及 dict 结构
    screenplays: dict[int, Any] = {}
    completed_sc = _state_val("completed_screenplays", {}) or {}
    single_sc = _state_val("screenplay", None)
    if completed_sc:
        screenplays = completed_sc
    elif single_sc:
        ep_no = _state_val("episode_number", None) or _state_val("episode_num", 1)
        screenplays = {int(ep_no): single_sc}

    ep_cols = _get_table_columns(db, "episodes")
    has_audit_verdict = "audit_verdict" in ep_cols
    has_audit_report = "audit_report" in ep_cols
    has_snap_start = "physical_snapshot_start" in ep_cols
    has_snap_end = "physical_snapshot_end" in ep_cols
    has_commercial_tag = "commercial_tag" in ep_cols
    has_outline_id = "outline_id" in ep_cols

    stage5_memories = []
    latest_end_snapshot: dict[str, Any] = {}

    for ep_num, ep_data in screenplays.items():
        if hasattr(ep_data, "to_dict"):
            ep_dict = ep_data.to_dict()
        elif hasattr(ep_data, "model_dump"):
            ep_dict = ep_data.model_dump()
        elif isinstance(ep_data, dict):
            ep_dict = ep_data
        else:
            ep_dict = dict(ep_data)

        # 1. 提取纯视听 Markdown 剧本正文（严格解耦，杜绝 JSON 序列化污染文本正文）
        sc_text = (
            ep_dict.get("screenplay_text")
            or ep_dict.get("body_markdown")
            or ep_dict.get("screenplay_content")
            or ep_dict.get("text")
            or ""
        )
        if not sc_text and isinstance(ep_data, str):
            sc_text = ep_data
        if not sc_text and ep_dict.get("scenes"):
            # 兼容场景结构：从场景序列合成基础视听 Markdown 剧本正文
            scene_blocks = []
            for sc in ep_dict["scenes"]:
                if isinstance(sc, dict):
                    loc = sc.get("location") or ""
                    idx = sc.get("scene_index", 1)
                    scene_blocks.append(f"### 场景 {idx}: {loc}".strip())
                    for act in sc.get("action_and_dialogue") or []:
                        scene_blocks.append(str(act))
            sc_text = "\n\n".join(scene_blocks)
        # 若 sc_text 意外被传为 JSON 字符串，尝试解析恢复纯文本正文
        if isinstance(sc_text, str) and sc_text.strip().startswith("{") and sc_text.strip().endswith("}"):
            parsed_sc = _safe_json_loads(sc_text, None)
            if isinstance(parsed_sc, dict):
                sc_text = (
                    parsed_sc.get("screenplay_text")
                    or parsed_sc.get("body_markdown")
                    or parsed_sc.get("screenplay_content")
                    or parsed_sc.get("text")
                    or sc_text
                )

        # 2. 提取跨集 0 秒物理咬合快照（时空连续性链条）
        start_snap_raw = (
            ep_dict.get("previous_episode_0s_pickup")
            or ep_dict.get("previous_episode_physical_pickup")
            or ep_dict.get("incoming_physical_snapshot")
            or (getattr(state, "incoming_physical_continuity", None).model_dump() if hasattr(getattr(state, "incoming_physical_continuity", None), "model_dump") else getattr(state, "incoming_physical_continuity", None))
            or {}
        )
        start_snapshot = start_snap_raw if isinstance(start_snap_raw, dict) else _safe_json_loads(start_snap_raw, {})

        end_snap_raw = (
            ep_dict.get("episode_end_physical_delta")
            or ep_dict.get("outgoing_physical_snapshot")
            or ep_dict.get("outgoing_physical_continuity")
            or (getattr(state, "outgoing_physical_continuity", None).model_dump() if hasattr(getattr(state, "outgoing_physical_continuity", None), "model_dump") else getattr(state, "outgoing_physical_continuity", None))
            or {}
        )
        end_snapshot = end_snap_raw if isinstance(end_snap_raw, dict) else _safe_json_loads(end_snap_raw, {})
        if end_snapshot:
            latest_end_snapshot = end_snapshot

        # 3. 提取 AST 结构化块与视听节点（执行 SSOT 数据治理与冗余清洗）
        existing_ep = fetch_one(
            db,
            "SELECT id, outline_id, ast_blocks FROM episodes WHERE drama_id = :drama_id AND episode_number = :ep_num",
            {"drama_id": drama_id, "ep_num": ep_num},
        )
        ep_ast = _safe_json_loads(existing_ep.get("ast_blocks") if existing_ep else None, {})
        ep_ast["safety_guardrails_lock"] = ep_dict.get("safety_guardrails_lock", {})
        ep_ast["dramatic_rhythm_check"] = ep_dict.get("dramatic_rhythm_check", {})
        ep_ast["golden_cliffhanger_hook"] = ep_dict.get("golden_cliffhanger_hook", {})
        if ep_dict.get("ast_data"):
            ep_ast["ast_data"] = ep_dict["ast_data"]
        if ep_dict.get("scenes"):
            ep_ast["scenes"] = ep_dict["scenes"]

        # SSOT 治理：清理 ast_blocks 中残留的大纲冗余字段，大纲数据由 episode_outlines 独家纳管
        for outline_redundant_key in ("hook_3s", "three_second_hook", "micro_twist_45s", "micro_turning_point_45s", "cliffhanger_end", "killer_cliffhanger_115s", "raw_outline_card", "subtext_matrix", "dual_helix_task"):
            ep_ast.pop(outline_redundant_key, None)
            if isinstance(ep_ast.get("ast_data"), dict):
                ep_ast["ast_data"].pop(outline_redundant_key, None)

        # SSOT 治理：若 episodes 表具备 physical_snapshot_start / physical_snapshot_end 独立物理列，
        # 则绝不在 ast_blocks 中重复存储快照全量对象，避免存储膨胀与时序不一致；仅在无独立列时作为向后兼容兜底
        if has_snap_start:
            ep_ast.pop("previous_episode_0s_pickup", None)
        else:
            ep_ast["previous_episode_0s_pickup"] = start_snapshot

        if has_snap_end:
            ep_ast.pop("episode_end_physical_delta", None)
        else:
            ep_ast["episode_end_physical_delta"] = end_snapshot

        # 4. 提取质检自审报告与结论
        audit_rep_raw = (
            ep_dict.get("audit_report")
            or (getattr(state, "latest_audit", None).model_dump() if hasattr(getattr(state, "latest_audit", None), "model_dump") else getattr(state, "latest_audit", None))
            or {}
        )
        audit_report = audit_rep_raw if isinstance(audit_rep_raw, dict) else _safe_json_loads(audit_rep_raw, {})
        audit_verdict = ep_dict.get("audit_verdict") or ("passed" if audit_report else "pending")
        if isinstance(audit_report, dict) and audit_report.get("passed") is False:
            audit_verdict = "need_revision"

        # 5. 商业定位标签与集数基本属性
        comm_tag = ep_dict.get("commercial_tag") or ("paywall_climax" if int(ep_num) in [3, 6, 9] else "regular")
        ep_title = ep_dict.get("episode_title") or ep_dict.get("title") or f"第{ep_num}集"
        duration = int(ep_dict.get("planned_duration_sec") or ep_dict.get("duration_seconds") or getattr(state, "target_duration_sec", 120) or 120)

        # 6. 查询并绑定独立创作大纲 outline_id（SSOT原则）
        outline_id = existing_ep.get("outline_id") if existing_ep else None
        if not outline_id and has_outline_id:
            outline_row = fetch_one(
                db,
                "SELECT id FROM episode_outlines WHERE drama_id = :drama_id AND episode_number = :ep_num AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
                {"drama_id": drama_id, "ep_num": ep_num},
            )
            if outline_row:
                outline_id = outline_row["id"]

        if outline_id:
            log.info("【阶段 5 落库】第 %s 集成功绑定大纲单一事实源 outline_id=%s", ep_num, outline_id)
        else:
            log.warning("【阶段 5 落库】第 %s 集未找到关联的 episode_outlines 记录，outline_id 为空", ep_num)

        # 7. 动态执行 UPDATE 或 INSERT 写入（零冗余：不写入 description / hook_cliffhanger）
        set_clauses = [
            "script_content = :script_content",
            "duration = :duration",
            "ast_blocks = :ast_blocks",
            "status = 'script_completed'",
            "updated_at = :updated_at",
        ]
        params: dict[str, Any] = {
            "script_content": sc_text,
            "duration": duration,
            "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
            "updated_at": now,
        }
        if has_snap_start:
            set_clauses.append("physical_snapshot_start = :physical_snapshot_start")
            params["physical_snapshot_start"] = json.dumps(start_snapshot, ensure_ascii=False)
        if has_snap_end:
            set_clauses.append("physical_snapshot_end = :physical_snapshot_end")
            params["physical_snapshot_end"] = json.dumps(end_snapshot, ensure_ascii=False)
        if has_audit_verdict:
            set_clauses.append("audit_verdict = :audit_verdict")
            params["audit_verdict"] = audit_verdict
        if has_audit_report:
            set_clauses.append("audit_report = :audit_report")
            params["audit_report"] = json.dumps(audit_report, ensure_ascii=False)
        if has_commercial_tag:
            set_clauses.append("commercial_tag = :commercial_tag")
            params["commercial_tag"] = comm_tag
        if has_outline_id and outline_id is not None:
            set_clauses.append("outline_id = :outline_id")
            params["outline_id"] = outline_id

        if existing_ep:
            params["id"] = existing_ep["id"]
            db.execute(
                text(f"UPDATE episodes SET {', '.join(set_clauses)} WHERE id = :id"),
                params,
            )
            log.info(
                "【阶段 5 落库】成功更新第 %s 集剧本 [id=%s, 正文字数=%d, outline_id=%s, 终态快照=%s, 自审结论=%s]",
                ep_num,
                existing_ep["id"],
                len(sc_text),
                outline_id,
                bool(end_snapshot),
                audit_verdict,
            )
        else:
            col_names = ["drama_id", "episode_number", "title", "script_content", "duration", "ast_blocks", "status", "created_at", "updated_at"]
            val_names = [":drama_id", ":ep_num", ":title", ":script_content", ":duration", ":ast_blocks", "'script_completed'", ":now", ":now"]
            insert_params = {
                "drama_id": drama_id,
                "ep_num": ep_num,
                "title": ep_title,
                "script_content": sc_text,
                "duration": duration,
                "ast_blocks": json.dumps(ep_ast, ensure_ascii=False),
                "now": now,
            }
            if has_snap_start:
                col_names.append("physical_snapshot_start")
                val_names.append(":physical_snapshot_start")
                insert_params["physical_snapshot_start"] = json.dumps(start_snapshot, ensure_ascii=False)
            if has_snap_end:
                col_names.append("physical_snapshot_end")
                val_names.append(":physical_snapshot_end")
                insert_params["physical_snapshot_end"] = json.dumps(end_snapshot, ensure_ascii=False)
            if has_audit_verdict:
                col_names.append("audit_verdict")
                val_names.append(":audit_verdict")
                insert_params["audit_verdict"] = audit_verdict
            if has_audit_report:
                col_names.append("audit_report")
                val_names.append(":audit_report")
                insert_params["audit_report"] = json.dumps(audit_report, ensure_ascii=False)
            if has_commercial_tag:
                col_names.append("commercial_tag")
                val_names.append(":commercial_tag")
                insert_params["commercial_tag"] = comm_tag
            if has_outline_id and outline_id is not None:
                col_names.append("outline_id")
                val_names.append(":outline_id")
                insert_params["outline_id"] = outline_id

            db.execute(
                text(f"INSERT INTO episodes ({', '.join(col_names)}) VALUES ({', '.join(val_names)})"),
                insert_params,
            )
            log.info(
                "【阶段 5 落库】新建第 %s 集剧本记录 [正文字数=%d, outline_id=%s, 终态快照=%s, 自审结论=%s]",
                ep_num,
                len(sc_text),
                outline_id,
                bool(end_snapshot),
                audit_verdict,
            )

        stage5_memories.append({
            "title": f"第{ep_num}集定稿文学剧本: {ep_title}",
            "content": f"第{ep_num}集剧本文学正文 (节选前1500字):\n{str(sc_text)[:1500]}\n0秒物理接棒: {json.dumps(start_snapshot, ensure_ascii=False)}\n集末物理位移: {json.dumps(end_snapshot, ensure_ascii=False)}",
            "summary": f"第{ep_num}集定稿剧本: {ep_title}",
            "keywords": [f"第{ep_num}集", "文学剧本", ep_title, "定稿剧本"],
            "memory_type": "screenplay",
            "source_type": "stage5_screenplay",
            "source_id": f"ep_screenplay_{ep_num}",
        })

    is_locked = getattr(state, "literary_journey_locked", False)
    lock_val = 1 if is_locked else 0
    p_status = "first_journey_locked" if is_locked else "running"

    drama_row = fetch_one(db, "SELECT metadata FROM dramas WHERE id = :id", {"id": drama_id})
    current_meta = _safe_json_loads(drama_row.get("metadata") if drama_row else None, {})
    current_meta["inter_episode_physical_snapshot"] = latest_end_snapshot or getattr(state, "inter_episode_physical_snapshot", {})
    current_meta["literary_journey_locked"] = is_locked
    current_meta["current_mini_arc_index"] = getattr(state, "current_mini_arc_index", 0)
    current_meta["current_stage"] = 5

    # 更新 dramas 主表状态与阶段号为 5
    db.execute(
        text("""
            UPDATE dramas
            SET lock_status = :lock_status,
                pipeline_status = :p_status,
                current_stage = 5,
                metadata = :metadata,
                updated_at = :now
            WHERE id = :id
        """),
        {"id": drama_id, "lock_status": lock_val, "p_status": p_status, "metadata": json.dumps(current_meta, ensure_ascii=False), "now": now},
    )

    if getattr(state, "latest_audit", None):
        persist_audit_report(db, drama_id, 5, state.latest_audit)

    # 1. 核心架构保障：关系型数据库主事务立即提交（事务隔离），确保阶段 5 数据 100% 持久化成功，绝不受后续非核心外部调用影响
    db.commit()
    log.info("【阶段 5 落库】关系型数据库主事务成功提交 (drama_id=%s, current_stage=5, lock_status=%s)", drama_id, lock_val)

    # 2. CQRS 读模型闭环刷新：立即向 Redis 发布最新全剧投影与 STAGE_PROGRESS 事件，彻底消除前端轮询感知时差
    try:
        completed_ep_nums = sorted(list(screenplays.keys()))
        total_eps = int(_state_val("total_episodes") or len(screenplays) or 1)
        projection_payload = {
            "drama_id": drama_id,
            "current_stage": 5,
            "journey": "journey_1_literary",
            "lock_status": lock_val,
            "pipeline_status": p_status,
            "completed_episodes": completed_ep_nums,
            "total_episodes": total_eps,
            "literary_journey_locked": is_locked,
        }
        publish_drama_read_projection(drama_id, projection_payload)
        publish_drama_event(drama_id, "STAGE_PROGRESS", {
            "stage": 5,
            "stage_name": "文学剧本波次生成",
            "journey": "journey_1_literary",
            "status": "completed" if (len(completed_ep_nums) >= total_eps) else "in_progress",
            "current_stage": 5,
            "completed_screenplays": len(completed_ep_nums),
            "total_episodes": total_eps,
            "lock_status": lock_val,
        })
        log.info("【阶段 5 落库】成功发布 CQRS 读模型投影与 STAGE_PROGRESS 事件 (drama_id=%s, current_stage=5, 进度=%d/%d)", drama_id, len(completed_ep_nums), total_eps)
    except Exception as e:
        log.warning("【阶段 5 落库】发布 CQRS 读模型或事件出现非致命异常 (不影响数据库主记录): %s", e)

    # 3. 外部依赖隔离：长期记忆写入向量数据库（Chroma）采用独立 try-except 保护，若向量库离线/拒绝连接绝不触发事务回滚
    if stage5_memories:
        try:
            log.info("【阶段 5 落库】开始同步 %d 条文学剧本长期记忆至向量数据库...", len(stage5_memories))
            sync_stage_memories_to_vector_db(db, drama_id, 5, stage5_memories)
            log.info("【阶段 5 落库】向量数据库同步成功完成")
        except Exception as e:
            log.warning("【阶段 5 落库】向量数据库同步出现非阻塞异常 (已隔离保护，主数据库持久化不受影响): %s", e)


# =========================================================================
# 阶段 6 角色领域三层模型清洗与切片推断辅助函数
# =========================================================================

