"""Stage storage adapters common utilities."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.context import memory_service, vector_memory_service
from app.context.short_memory_service import (
    get_short_memories as _raw_get_short_memories,
    publish_drama_event as _raw_publish_drama_event,
    publish_drama_read_projection as _raw_publish_drama_read_projection,
    publish_episode_read_projection as _raw_publish_episode_read_projection,
    set_short_memories as _raw_set_short_memories,
)
from app.core.logger import get_logger
from app.db.session import fetch_all as _raw_fetch_all, fetch_one as _raw_fetch_one
from app.platform_common import now_iso
from app.schemas.script_graph_state import RedBlueAuditReport

log = get_logger("lmd.storage_adapter")


# ---------------------------------------------------------------------------
# Dynamic test mock / monkeypatch transparent proxies
# When tests patch attributes on `app.workflows.adapters.drama_storage_adapter`
# (e.g. `mp.setattr("app.workflows.adapters.drama_storage_adapter.fetch_one", ...)`),
# these proxies dynamically check for patched attributes to preserve 100% test compatibility.
# ---------------------------------------------------------------------------

def fetch_one(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "fetch_one"):
        fn = getattr(adapter, "fetch_one")
        if fn is not fetch_one:
            return fn(*args, **kwargs)
    return _raw_fetch_one(*args, **kwargs)


def fetch_all(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "fetch_all"):
        fn = getattr(adapter, "fetch_all")
        if fn is not fetch_all:
            return fn(*args, **kwargs)
    return _raw_fetch_all(*args, **kwargs)


def publish_drama_read_projection(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "publish_drama_read_projection"):
        fn = getattr(adapter, "publish_drama_read_projection")
        if fn is not publish_drama_read_projection:
            return fn(*args, **kwargs)
    return _raw_publish_drama_read_projection(*args, **kwargs)


def publish_episode_read_projection(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "publish_episode_read_projection"):
        fn = getattr(adapter, "publish_episode_read_projection")
        if fn is not publish_episode_read_projection:
            return fn(*args, **kwargs)
    return _raw_publish_episode_read_projection(*args, **kwargs)


def publish_drama_event(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "publish_drama_event"):
        fn = getattr(adapter, "publish_drama_event")
        if fn is not publish_drama_event:
            return fn(*args, **kwargs)
    return _raw_publish_drama_event(*args, **kwargs)


def set_short_memories(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "set_short_memories"):
        fn = getattr(adapter, "set_short_memories")
        if fn is not set_short_memories:
            return fn(*args, **kwargs)
    return _raw_set_short_memories(*args, **kwargs)


def get_short_memories(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "get_short_memories"):
        fn = getattr(adapter, "get_short_memories")
        if fn is not get_short_memories:
            return fn(*args, **kwargs)
    return _raw_get_short_memories(*args, **kwargs)


def sync_stage_memories_to_vector_db(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "sync_stage_memories_to_vector_db"):
        fn = getattr(adapter, "sync_stage_memories_to_vector_db")
        if fn is not sync_stage_memories_to_vector_db:
            return fn(*args, **kwargs)
    return _raw_sync_stage_memories_to_vector_db(*args, **kwargs)


def persist_audit_report(*args: Any, **kwargs: Any) -> Any:
    adapter = sys.modules.get("app.workflows.adapters.drama_storage_adapter")
    if adapter is not None and hasattr(adapter, "persist_audit_report"):
        fn = getattr(adapter, "persist_audit_report")
        if fn is not persist_audit_report:
            return fn(*args, **kwargs)
    return _raw_persist_audit_report(*args, **kwargs)

def _safe_json_loads(data: Any, default: Any = None) -> Any:
    """安全反序列化 JSON 数据。"""
    if data is None:
        return default if default is not None else {}
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, str):
        trimmed = data.strip()
        if not trimmed:
            return default if default is not None else {}
        try:
            return json.loads(trimmed)
        except Exception:
            return default if default is not None else {}
    return default if default is not None else {}


def _ensure_valid_json_str(
    val: Any,
    default_json: str = "{}",
    wrap_key: str | None = None,
) -> str:
    """确保输出的字符串是 100% 合法的 MySQL JSON 列文本（杜绝 Error 3140 Invalid JSON text）。"""
    if val is None or val == "":
        return default_json
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, (int, float, bool)):
        if default_json == "[]":
            return json.dumps([val], ensure_ascii=False)
        if wrap_key:
            return json.dumps({wrap_key: val}, ensure_ascii=False)
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return default_json
        try:
            parsed = json.loads(s)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass
        if default_json == "[]":
            items = [x.strip() for x in re.split(r"[|｜,，;；\n]+", s) if x.strip()]
            return json.dumps(items or [s], ensure_ascii=False)
        if wrap_key:
            return json.dumps({wrap_key: s}, ensure_ascii=False)
        return json.dumps({"summary": s}, ensure_ascii=False)
    return default_json


def _dump_or_dict(val: Any) -> Any:
    """安全提取 Pydantic Model 字典或原生 dict，支持嵌套递归转换。"""
    if val is None:
        return {}
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, dict):
        return {k: _dump_or_dict(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_dump_or_dict(x) for x in val]
    return val


def _flatten_asset_collection(raw: Any, default_name_prefix: str = "ASSET") -> list[dict[str, Any]]:
    """递归解构并将可能为分层字典（tier 字典）、映射字典、列表、Pydantic 对象或字符串的资产集合，
    安全规范化为纯 dict 列表。确保下游任何迭代均可安全执行 .get()，彻底杜绝 AttributeError。
    """
    if raw is None:
        return []

    # 若为 Pydantic 模型，先转为原生结构
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "dict"):
        raw = raw.dict()

    results: list[dict[str, Any]] = []

    if isinstance(raw, list):
        for item in raw:
            results.extend(_flatten_asset_collection(item, default_name_prefix))
    elif isinstance(raw, dict):
        # 常见单实体特征字段
        entity_keys = {
            "name", "character_name", "char_name", "character_code", "char_id",
            "scene_name", "location", "location_name", "env_id", "scene_id",
            "prop_name", "item_name", "prop_id",
            "voice_id", "master_voice_id", "timbre", "voice_prompt",
            "asset_id", "visual_prompt", "appearance", "static_asset",
        }
        # 容器键特征 (包含分层 tier 或按类别嵌套的容器)
        container_keys = {
            "tier1_base", "tier2_performance", "tier3_special", "tier_1", "tier_2", "tier_3",
            "tier1_primary", "tier2_transitional", "primary", "transitional",
            "tier1_hero", "tier2_anchor", "tier3_atmospheric", "hero", "anchor", "atmospheric",
            "characters", "environments", "props",
            "characters_in_scene", "scenes_in_use", "props_in_use",
        }

        has_entity_field = any(k in raw for k in entity_keys)
        has_container_field = any(k in raw for k in container_keys)

        if has_container_field:
            # 包含子资产或层级的容器字典，递归解构其所有子项
            for sub_val in raw.values():
                results.extend(_flatten_asset_collection(sub_val, default_name_prefix))
        elif has_entity_field:
            # 单一实体字典
            results.append(raw)
        else:
            # 既没有明确保留字段也没有明确容器字段，可能是一个以 asset_id 为 key 的字典
            is_map_of_dicts = all(isinstance(v, (dict, list)) for v in raw.values()) if raw else False
            if is_map_of_dicts and raw:
                for k, v in raw.items():
                    if isinstance(v, dict):
                        d = dict(v)
                        if "asset_id" not in d and "id" not in d:
                            d["asset_id"] = str(k)
                        results.append(d)
                    else:
                        results.extend(_flatten_asset_collection(v, default_name_prefix))
            else:
                # 保守策略：作为单个字典实体保留
                results.append(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if s:
            results.append({
                "name": s,
                "asset_id": s,
                "character_name": s,
                "character_code": s,
                "location": s,
                "prop_name": s,
                "voice_id": s,
            })
    return results


def _get_table_columns(db: Session, table_name: str) -> set[str]:
    """安全获取指定表的物理列集合（统一兼容 SQLite 与 MySQL）。"""
    try:
        from sqlalchemy import inspect
        bind = db.get_bind()
        inspector = inspect(bind)
        cols = inspector.get_columns(table_name)
        return {c["name"] for c in cols}
    except Exception:
        try:
            rows = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            return {r[1] for r in rows}
        except Exception:
            return set()


def _raw_sync_stage_memories_to_vector_db(
    db: Session,
    drama_id: int,
    stage_id: int,
    items: list[dict[str, Any]],
) -> None:
    """将流水线阶段产生的核心结构化长期记忆同步落库至 memory_items 表并构建 Qdrant 向量索引。
    
    【工业级保障】
    1. 幂等性：基于 (drama_id, source_type, source_id) 查重，避免重复落库导致数据冗余；
    2. 自动向量化：自动生成 1536 维特征向量并写入剧目隔离的 Qdrant 向量集合；
    3. 容灾隔离：向量库异常或未部署时不阻断主关系型数据库事务，保证业务 100% 可用。
    """
    if not items or not drama_id:
        return
    log.debug("【长期记忆同步】开始为短剧 [%s] 阶段 %s 同步 %d 条核心长期记忆...", drama_id, stage_id, len(items))
    for item_data in items:
        try:
            source_type = item_data.get("source_type") or f"stage{stage_id}"
            source_id = str(item_data.get("source_id") or "")
            existing = None
            if source_id:
                existing = fetch_one(
                    db,
                    "SELECT id FROM memory_items WHERE drama_id = :did AND source_type = :st AND source_id = :sid AND deleted_at IS NULL",
                    {"did": drama_id, "st": source_type, "sid": source_id},
                )
            if existing:
                memory_service.update_memory_item(
                    db,
                    int(existing["id"]),
                    {
                        "title": item_data.get("title"),
                        "content": item_data.get("content"),
                        "summary": item_data.get("summary"),
                        "keywords": item_data.get("keywords"),
                        "status": "active",
                    },
                    editor=f"stage{stage_id}_auto_pipeline",
                )
                row = fetch_one(db, "SELECT * FROM memory_items WHERE id = :id", {"id": existing["id"]})
                if row:
                    vector_memory_service.index_memory_item(db, dict(row))
            else:
                payload = {
                    "drama_id": drama_id,
                    "episode_id": item_data.get("episode_id"),
                    "memory_type": item_data.get("memory_type") or "world_bible",
                    "scope": item_data.get("scope") or "drama",
                    "title": item_data.get("title") or f"Stage {stage_id} 关键记忆",
                    "content": item_data.get("content"),
                    "summary": item_data.get("summary"),
                    "keywords": item_data.get("keywords") or [],
                    "source_type": source_type,
                    "source_id": source_id,
                    "metadata": item_data.get("metadata") or {"stage": stage_id},
                    "status": "active",
                }
                memory_service.add_memory_item(db, payload)
        except Exception as exc:
            log.warning("【长期记忆同步】同步阶段记忆项失败 (%s): %s", item_data.get("title"), exc)


def _raw_persist_audit_report(
    db: Session,
    drama_id: int,
    stage_id: int,
    audit: RedBlueAuditReport | dict[str, Any] | None,
    episode_id: int | None = None,
) -> None:
    """将红蓝对抗独立质检报告持久化至 quality_reports 数据库表。"""
    if not audit:
        return

    log.debug("【质检落库】开始持久化剧目 [%s] 阶段 %s 的红蓝对抗报告...", drama_id, stage_id)
    now = now_iso()
    audit_dict = _dump_or_dict(audit)
    
    # 提取判定结果与各方审查数据
    verdict = audit_dict.get("verdict", "GREEN_APPROVED")
    blue_compliance = audit_dict.get("blue_team_compliance") or audit_dict.get("blue_checks") or {}
    red_criticism = audit_dict.get("red_team_criticism") or audit_dict.get("red_complaints") or {}
    blocking_issues = audit_dict.get("blocking_issues") or []
    warning_suggestions = audit_dict.get("warning_suggestions") or []
    
    # 计算综合分值
    score = 95.0 if verdict == "GREEN_APPROVED" else (80.0 if verdict == "YELLOW_WARNING" else 50.0)
    passed = 1 if verdict in ("GREEN_APPROVED", "YELLOW_WARNING") else 0

    try:
        db.execute(
            text("""
                INSERT INTO quality_reports (
                    drama_id, episode_id, stage_id, report_type, status,
                    score, passed, patch_applied, radar_scores, issues,
                    suggestions, raw_report, blue_compliance_score, blue_checklist,
                    red_sharp_critiques, anti_degrade_alerts, created_at, updated_at
                ) VALUES (
                    :drama_id, :episode_id, :stage_id, 'red_blue_audit', 'open',
                    :score, :passed, 0, :radar_scores, :issues,
                    :suggestions, :raw_report, :blue_score, :blue_checklist,
                    :red_critiques, :anti_degrade, :now, :now
                )
            """),
            {
                "drama_id": drama_id,
                "episode_id": episode_id,
                "stage_id": stage_id,
                "score": score,
                "passed": passed,
                "radar_scores": json.dumps({"overall": score}, ensure_ascii=False),
                "issues": json.dumps(blocking_issues, ensure_ascii=False),
                "suggestions": json.dumps(warning_suggestions, ensure_ascii=False),
                "raw_report": json.dumps(audit_dict, ensure_ascii=False),
                "blue_score": 100.0 if passed else 60.0,
                "blue_checklist": json.dumps(blue_compliance, ensure_ascii=False),
                "red_critiques": json.dumps(red_criticism, ensure_ascii=False),
                "anti_degrade": json.dumps(blocking_issues, ensure_ascii=False),
                "now": now,
            },
        )
    except Exception as e:
        log.warning("【质检落库】写入 quality_reports 表异常: %s", e)


def clean_character_name(raw_name: str) -> str:
    """从原始角色名或切片描述名中剥离括号形态标注及常见切片后缀，还原自然人本名。
    例如:
      '沈炼(全身定妆照)' -> '沈炼'
      '沈炼（飞鱼服）' -> '沈炼'
      '沈炼[四阿哥常服]' -> '沈炼'
      '沈炼(0号肖像)' -> '沈炼'
      '沈炼_特写' -> '沈炼'
    """
    if not raw_name:
        return ""
    # 1. 剔除括号及其内部说明 (支持中英文括号、中括号)
    name = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", raw_name).strip()
    # 2. 剥离常见切片下划线/破折号后缀
    name = re.sub(r"[_—\-](全身|肖像|特写|四视图|三视图|手部|面部|常服|战损).*$", "", name).strip()
    return name if name else raw_name.strip()


def synthesize_voice_prompt(
    char_name: str,
    timbre: str = "",
    role: str = "supporting",
    personality: str = "",
    gender: str = "male",
    monologue_source: str = "",
    perceived_age: str | int | None = None,
    voice_style: str = "",
    acoustic_persona: dict[str, Any] | None = None,
) -> str:
    """合成专业级广播剧/影视配音 TTS 声音生成提示词，
    覆盖【音色基调】、【发音与节奏】、【戏剧潜台词与语调】、【多维情绪演绎规范】与【声音质感】五大维度。
    """
    clean_name = clean_character_name(char_name) or "角色"
    if not timbre and voice_style:
        timbre = voice_style
    if not timbre:
        age_str = f"{perceived_age}岁" if perceived_age else ""
        timbre = f"清雅知性{age_str}女声，中高频温润通透" if gender == "female" else f"低沉磁性{age_str}成熟男声，胸腔共鸣浑厚"

    role_desc = "核心主角" if role in ("protagonist", "主角") else ("主要反派对手" if role in ("antagonist", "反派") else "关键推动角色")
    subtext = f"言辞间透露出{personality or '内敛克制'}的心理底色，字句咬合沉稳而有锋芒"

    prompt_lines = [
        f"【音色基调】：{timbre}，声音辨识度极高，音质纯净自然，中频富有饱满度与故事叙事厚度。",
        "【发音与节奏】：标准普通话发音，咬字清晰利落，平均语速约每分钟210字，重音抑扬顿挫，停顿呼吸真实自然。",
        f"【戏剧潜台词与语调】：紧密契合「{clean_name}」的{role_desc}身份，{subtext}。",
        "【多维情绪演绎规范】：",
        "- 常态对话：冷静自持，声调平稳，句尾微收，不疾不徐；",
        "- 戏剧冲突：声压增强，节奏骤紧，爆发力十足但破而不破，富有情绪穿透力；",
        "- 独白思考：压低共鸣腔，微弱气声自然融入，显露潜意识复杂波澜。",
        "【声音质感】：专业录音棚广播剧电影级声学混音，平直频响无失真，空间混响干净，杜绝电音及机械金属感。",
    ]
    if isinstance(acoustic_persona, dict) and acoustic_persona:
        acou_notes = []
        if acoustic_persona.get("pitch_base"):
            acou_notes.append(f"基础音高: {acoustic_persona['pitch_base']}")
        if acoustic_persona.get("formant_focus"):
            acou_notes.append(f"共鸣焦点: {acoustic_persona['formant_focus']}")
        if acoustic_persona.get("texture_detail"):
            acou_notes.append(f"质感细节: {acoustic_persona['texture_detail']}")
        if acou_notes:
            prompt_lines.append(f"【声学特征细节】：{', '.join(acou_notes)}")
    if monologue_source:
        prompt_lines.append(f"【参考台词示范】：『{monologue_source}』")

    return "\n".join(prompt_lines)



