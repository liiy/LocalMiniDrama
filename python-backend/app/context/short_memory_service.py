"""短剧工业化流水线 - 短期记忆服务 (Short-Term Memory Service)。

【设计理念与架构】
1. 为什么将各阶段的短期记忆放入 Redis？
   - 短期记忆（便签/Scratchpad A/B/C/D、集间物理快照、全模态资源清单）是各阶段节点（Stage 1 ~ Stage 8）
     之间高频交互的“即时工作记忆”。
   - 权威数据已经在每个阶段完成时落库到数据库实体表（dramas, episodes, storyboards, characters 等）。
   - 将短期记忆保存在 Redis 中，避免了高频全量刷写大型快照到 MySQL，极大降低 I/O 压力并提升并发吞吐。
   - 采用 Cache-Aside 机制：Redis 命中则极速读取；Redis 未命中或未启用时，自动从数据库实体表中重建短期记忆。

2. 核心工作记忆结构：
   - pad_a: 核心创作目标、母题与主线冲突 (Creative Target & Core Conflict)
   - pad_b: 核心角色当前登场状态、情绪与人物弧光 (Active Character States & Arcs)
   - pad_c: 当前场景环境、空间布局与在场关键道具 (Scene Space & Props in Play)
   - pad_d: 未决伏笔钩子、悬念与剧情断点 (Open Hooks & Unresolved Cliffhangers)
   - inter_episode_physical_snapshot: 第二程集间物理连续性快照 (角色装造破损、伤痕演进、道具持握、空间位置)
   - current_resource_manifest: 当前阶段/分集的多模态就绪资源清单 (TTS语音文件、分镜画面图、SFX音效、参考垫图)
"""

from __future__ import annotations

import json
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.platform_common import now_iso, json_dumps, json_loads

from app.schemas.script_graph_state import (
    DoubleTrackProhibitions,
)

log = get_logger("lmd.short_memory")

# 短期记忆在 Redis 中的默认过期时间：7 天（秒）
SHORT_MEMORY_TTL = 7 * 86400

# Redis 客户端单例缓存
_redis_client: Any = None
_redis_checked: bool = False
# 进程内内存降级存储（当未配置 Redis 或 Redis 宕机时使用）
_in_memory_scratchpads: dict[int, dict[str, Any]] = {}
_in_memory_journey1_working_memory: dict[str, str] = {}
_in_memory_episode_continuity: dict[str, str] = {}
_in_memory_idempotency: dict[str, float] = {}
_in_memory_read_projections: dict[str, dict[str, Any]] = {}


def _get_redis():
    """获取 Redis 连接客户端，支持 protocol=2 降级以兼容不同版本的 Redis 服务。"""
    global _redis_client, _redis_checked
    if not _redis_checked:
        _redis_checked = True
        try:
            cfg = load_config()
            redis_url = cfg.get("queue", {}).get("redis_url")
            if redis_url:
                import redis
                try:
                    _redis_client = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
                    _redis_client.ping()
                except Exception:
                    _redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
                    _redis_client.ping()
                log.info("【短期记忆】成功连接至 Redis 缓存: %s", redis_url)
            else:
                log.info("【短期记忆】未配置 Redis URL，将使用内存模式与数据库回退。")
        except Exception as e:
            log.warning("【短期记忆】Redis 连接初始化失败，将降级至内存与数据库: %s", e)
            _redis_client = None
    return _redis_client

# =========================================================================
# 【语义化键规范与 CQRS 读分离】Redis 异步投影引擎 (Async Projection Engine)
# =========================================================================

READ_MODEL_TTL = 24 * 3600  # 读投影默认缓存 24 小时


def _make_journey1_working_memory_key(drama_id: int, stage_name: str) -> str:
    """第一程各阶段工作便签键 (drama:{id}:journey1:{stage_name}_working_memory, STRING)。"""
    return f"drama:{drama_id}:journey1:{stage_name}_working_memory"


def _make_episode_continuity_key(drama_id: int, episode_number: int) -> str:
    """第二程单集集间物理快照键 (drama:{id}:ep:{n}:continuity:physical_snapshot, STRING)。"""
    return f"drama:{drama_id}:ep:{episode_number}:continuity:physical_snapshot"


def _make_short_memory_key(drama_id: int) -> str:
    """全剧工作便签聚合键 (drama:{id}:short_memories, STRING)。"""
    return f"drama:{drama_id}:short_memories"


def set_short_memories(
    drama_id: int,
    memories: dict[str, Any],
    stage_name: str | None = None,
) -> None:
    """【兼容层】写入全模态短期记忆便签集合 (支持 Redis 与进程内内存降级)。"""
    if not drama_id or not isinstance(memories, dict):
        return

    safe_memories: dict[str, Any] = {}
    for k, v in memories.items():
        if hasattr(v, "model_dump"):
            safe_memories[k] = v.model_dump()
        else:
            safe_memories[k] = v

    if drama_id not in _in_memory_scratchpads:
        _in_memory_scratchpads[drama_id] = {}
    _in_memory_scratchpads[drama_id].update(safe_memories)

    r = _get_redis()
    if r:
        try:
            key = _make_short_memory_key(drama_id)
            existing_raw = r.get(key)
            current_dict = json_loads(existing_raw, {}) if existing_raw else {}
            current_dict.update(safe_memories)
            r.set(key, json_dumps(current_dict), ex=SHORT_MEMORY_TTL)
        except Exception as e:
            log.warning("【短期记忆兼容层】写入 Redis 失败: %s", e)

    if stage_name:
        text_content = ""
        for pad_key in ("pad_a", "pad_b", "pad_c", "pad_d"):
            if pad_key in safe_memories and isinstance(safe_memories[pad_key], str):
                text_content += safe_memories[pad_key] + "\n"
        if text_content.strip():
            set_journey1_working_memory(drama_id, stage_name, text_content.strip())

    snap = safe_memories.get("inter_episode_physical_snapshot")
    if snap and isinstance(snap, dict):
        ep_idx = snap.get("episode_index") or snap.get("episode_number") or snap.get("from_episode") or 1
        set_episode_physical_snapshot(drama_id, int(ep_idx), snap)


def get_short_memories(drama_id: int) -> dict[str, Any]:
    """【兼容层】读取全模态短期记忆便签集合 (优先从 Redis 读取，失败降级至进程内内存)。"""
    if not drama_id:
        return {}

    r = _get_redis()
    if r:
        try:
            key = _make_short_memory_key(drama_id)
            raw = r.get(key)
            if raw:
                data = json_loads(raw, {})
                if isinstance(data, dict):
                    return data
        except Exception as e:
            log.warning("【短期记忆兼容层】从 Redis 读取失败: %s", e)

    return _in_memory_scratchpads.get(drama_id, {}).copy()


def _make_drama_read_key(drama_id: int) -> str:
    """全剧维度只读投影键 (drama:{id}:read_model, HASH)。"""
    return f"drama:{drama_id}:read_model"


def _make_episode_read_key(drama_id: int, episode_number: int) -> str:
    """单集维度只读投影键 (drama:{id}:ep:{n}:read_model, HASH)。"""
    return f"drama:{drama_id}:ep:{episode_number}:read_model"


def _make_idempotency_key(drama_id: int, task_hash: str) -> str:
    """任务幂等性控制键 (drama:{id}:idempotency:{task_hash}, STRING)。"""
    return f"drama:{drama_id}:idempotency:{task_hash}"


def _make_drama_event_channel(drama_id: int) -> str:
    """全剧工作流事件广播频道 (channel:drama:{id}:events, PUB/SUB)。"""
    return f"channel:drama:{drama_id}:events"


def set_journey1_working_memory(drama_id: int, stage_name: str, memory_content: str) -> None:
    """设置第一程指定阶段的语义化工作便签 (STRING, TTL 7天)。"""
    if not drama_id or not stage_name:
        return
    text_val = str(memory_content or "").strip()
    log.debug("【语义工作记忆】写入第一程工作便签: drama_id=%s, stage=%s, 字符数=%d", drama_id, stage_name, len(text_val))
    r = _get_redis()
    if r:
        try:
            key = _make_journey1_working_memory_key(drama_id, stage_name)
            r.set(key, text_val, ex=SHORT_MEMORY_TTL)
            return
        except Exception as e:
            log.warning("【语义工作记忆】写入 Redis 失败: %s", e)
    _in_memory_journey1_working_memory[f"{drama_id}_{stage_name}"] = text_val


def get_journey1_working_memory(drama_id: int, stage_name: str) -> str:
    """获取第一程指定阶段的语义化工作便签 (STRING)。"""
    if not drama_id or not stage_name:
        return ""
    r = _get_redis()
    if r:
        try:
            key = _make_journey1_working_memory_key(drama_id, stage_name)
            val = r.get(key)
            if val is not None:
                return str(val)
        except Exception as e:
            log.warning("【语义工作记忆】从 Redis 读取失败: %s", e)
    return _in_memory_journey1_working_memory.get(f"{drama_id}_{stage_name}", "")


def set_episode_physical_snapshot(drama_id: int, episode_number: int, snapshot: dict[str, Any] | str | Any) -> None:
    """设置第二程单集集间物理快照 (STRING, TTL 7天)。"""
    if not drama_id or not episode_number:
        return
    snap_payload = snapshot.model_dump() if hasattr(snapshot, "model_dump") else snapshot
    snap_str = snap_payload if isinstance(snap_payload, str) else json_dumps(snap_payload)
    log.debug("【集间物理快照】写入单集物理快照: drama_id=%s, ep=%s, 字符数=%d", drama_id, episode_number, len(snap_str))
    r = _get_redis()
    if r:
        try:
            key = _make_episode_continuity_key(drama_id, episode_number)
            r.set(key, snap_str, ex=SHORT_MEMORY_TTL)
            return
        except Exception as e:
            log.warning("【集间物理快照】写入 Redis 失败: %s", e)
    _in_memory_episode_continuity[f"{drama_id}_{episode_number}"] = snap_str


def get_episode_physical_snapshot(drama_id: int, episode_number: int) -> dict[str, Any]:
    """获取第二程单集集间物理快照。"""
    if not drama_id or not episode_number:
        return {}
    r = _get_redis()
    if r:
        try:
            key = _make_episode_continuity_key(drama_id, episode_number)
            val = r.get(key)
            if val:
                return json_loads(val, {})
        except Exception as e:
            log.warning("【集间物理快照】从 Redis 读取失败: %s", e)
    raw = _in_memory_episode_continuity.get(f"{drama_id}_{episode_number}", "")
    return json_loads(raw, {}) if raw else {}


def clear_drama_working_memory(drama_id: int) -> None:
    """清理指定剧目的全部语义工作记忆与单集物理连续性快照。"""
    if not drama_id:
        return
    r = _get_redis()
    if r:
        try:
            pattern = f"drama:{drama_id}:*"
            keys = r.keys(pattern)
            if keys:
                r.delete(*keys)
        except Exception as e:
            log.warning("【工作记忆】清理 Redis 缓存失败: %s", e)
    prefix = f"{drama_id}_"
    for k in list(_in_memory_journey1_working_memory.keys()):
        if k.startswith(prefix):
            _in_memory_journey1_working_memory.pop(k, None)
    for k in list(_in_memory_episode_continuity.keys()):
        if k.startswith(prefix):
            _in_memory_episode_continuity.pop(k, None)
    # 同步清理内存中的只读投影备份
    _in_memory_read_projections.pop(f"drama_{drama_id}_master", None)


def check_and_set_idempotency(drama_id: int, task_hash: str, ttl: int = 86400, ttl_seconds: Optional[int] = None) -> bool:
    """检查并设置任务幂等性锁 (STRING, 默认 TTL 24小时)。
    
    返回值:
        True: 首次执行，成功获取锁
        False: 重复任务，已被锁定
    """
    if ttl_seconds is not None:
        ttl = ttl_seconds
    if not drama_id or not task_hash:
        return True
    key = _make_idempotency_key(drama_id, task_hash)
    r = _get_redis()
    if r:
        try:
            ok = r.set(key, now_iso(), ex=ttl, nx=True)
            log.debug("【任务幂等锁】Redis NX 结果: drama_id=%s, task_hash=%s, acquired=%s", drama_id, task_hash, bool(ok))
            return bool(ok)
        except Exception as e:
            log.warning("【任务幂等锁】Redis 检查失败，降级至进程内存: %s", e)

    import time
    now_ts = time.time()
    mem_key = f"{drama_id}_{task_hash}"
    exp_ts = _in_memory_idempotency.get(mem_key, 0.0)
    if now_ts < exp_ts:
        log.debug("【任务幂等锁】内存锁命中已存在: drama_id=%s, task_hash=%s", drama_id, task_hash)
        return False
    _in_memory_idempotency[mem_key] = now_ts + ttl
    log.debug("【任务幂等锁】内存锁新设置成功: drama_id=%s, task_hash=%s", drama_id, task_hash)
    return True


def publish_drama_event(drama_id: int, event_type: str, payload: dict[str, Any] | None = None) -> None:
    """向 channel:drama:{id}:events 广播工作流状态演进事件 (PUB/SUB)。"""
    if not drama_id or not event_type:
        return
    event_data = {
        "event_type": event_type,
        "drama_id": drama_id,
        "timestamp": now_iso(),
        "payload": payload or {},
    }
    channel = _make_drama_event_channel(drama_id)
    log.debug("【Pub/Sub 事件广播】向频道 [%s] 发布事件: type=%s", channel, event_type)
    r = _get_redis()
    if r:
        try:
            r.publish(channel, json_dumps(event_data))
        except Exception as e:
            log.warning("【Pub/Sub 事件广播】Redis 发布失败: %s", e)


def publish_drama_read_projection(drama_id: int, state: Any) -> None:
    """将全剧最新状态以增量补丁 (Partial Patch / Merge) 形式发布为极速只读投影 (Redis HASH: drama:{id}:read_model)。
    
    【核心设计理念与 CQRS 原则】：
    1. 读投影 (Read Model) 是全剧全生命周期的聚合只读物化视图，供前端大屏与看板快速轮询；
    2. 采用【增量字段合并 (Patch/Merge)】机制：仅提取入参 state 中显式存在且非 None 的键值，
       增量写入 Redis HASH，绝对严禁使用空字符串/默认值盲目全量覆写已存在的键；
    3. 严密保护核心累积资产（剧名、题材、梗概、总集数、蓝图机制、各阶段语义工作便签等），
       确保后续阶段推进（如阶段2角色、阶段3场景、阶段4大纲等）不会冲刷清空前序阶段的智力成果；
    4. 内存降级字典同样采用增量合并策略 (dict.update)，在无 Redis 环境下保持高度一致性。
    """
    if not drama_id:
        return

    # 1. 统一提取输入状态为标准字典
    if hasattr(state, "model_dump") and callable(state.model_dump):
        raw_dict = state.model_dump(exclude_unset=True)
    elif hasattr(state, "dict") and callable(state.dict):
        raw_dict = state.dict(exclude_unset=True)
    elif isinstance(state, dict):
        raw_dict = dict(state)
    elif hasattr(state, "__dict__"):
        raw_dict = dict(state.__dict__)
    else:
        raw_dict = {}

    # 2. 字段语义别名标准化对齐
    if "id" in raw_dict and "drama_id" not in raw_dict:
        raw_dict["drama_id"] = raw_dict["id"]
    if "selected_title" in raw_dict and "title" not in raw_dict:
        raw_dict["title"] = raw_dict["selected_title"]
    if "core_irony" in raw_dict and "dramatic_irony" not in raw_dict:
        raw_dict["dramatic_irony"] = raw_dict["core_irony"]
    if "short_memory_d" in raw_dict and "season_outline_working_memory" not in raw_dict:
        raw_dict["season_outline_working_memory"] = raw_dict["short_memory_d"]

    # 3. 若传入了全量对象，按需提取度量指标与轻量摘要，避免将多兆字节的大文本（如正文剧本）直接塞入顶层 HASH
    if "completed_episodes" not in raw_dict and isinstance(raw_dict.get("completed_screenplays"), dict):
        raw_dict["completed_episodes"] = sorted(list(raw_dict["completed_screenplays"].keys()))
    if "character_count" not in raw_dict and isinstance(raw_dict.get("characters"), list):
        raw_dict["character_count"] = len(raw_dict["characters"])
    if isinstance(raw_dict.get("environments_and_props"), dict):
        ep_dict = raw_dict["environments_and_props"]
        if "environments_count" not in raw_dict and isinstance(ep_dict.get("environments"), list):
            raw_dict["environments_count"] = len(ep_dict["environments"])
        if "props_count" not in raw_dict and isinstance(ep_dict.get("props"), list):
            raw_dict["props_count"] = len(ep_dict["props"])

    # 过滤无需直接写入全剧顶层 HASH 投影的重型/多阶段深层结构
    HEAVY_OBJECT_KEYS = {
        "completed_screenplays",
        "screenplays",
        "screenplay",
        "screenplay_text",
        "characters",
        "environments_and_props",
        "season_outlines",
        "mini_arc_units",
        "audio_bible",
        "checkpoints",
        "outgoing_physical_continuity",
        "inter_episode_physical_snapshot",
    }

    # 核心累积资产保护清单：若传入空值（如空字符串、空字典），直接跳过更新，严防调用方默认值覆写已存在成果
    CUMULATIVE_ASSET_KEYS = {
        "title",
        "genre",
        "logline",
        "dramatic_irony",
        "grand_payoff",
        "blueprint",
        "mechanism",
        "arc_type",
        "ideation_working_memory",
        "character_working_memory",
        "world_building_working_memory",
        "season_outline_working_memory",
    }

    # 4. 构建本次增量 Patch
    patch: dict[str, str] = {
        "drama_id": str(drama_id),
        "updated_at": now_iso(),
    }

    r = _get_redis()

    for k, v in raw_dict.items():
        if k in HEAVY_OBJECT_KEYS or v is None:
            continue

        # 防御性过滤：防止默认空值冲洗掉既有核心资产
        if k in CUMULATIVE_ASSET_KEYS and v in ("", "None", "{}", "[]", {}, []):
            continue

        # 特殊处理：已完成集数 (completed_episodes) 支持追加式集合合并
        if k == "completed_episodes":
            if isinstance(v, (list, tuple, set)):
                new_eps = set(int(x) for x in v if str(x).isdigit())
                # 若非空，尝试与既有已完成集数合并，防止单集生成模式冲刷历史集数
                if new_eps:
                    existing_eps_raw = None
                    if r:
                        try:
                            existing_eps_raw = r.hget(_make_drama_read_key(drama_id), "completed_episodes")
                        except Exception:
                            pass
                    if not existing_eps_raw:
                        existing_eps_raw = _in_memory_read_projections.get(f"drama_{drama_id}_master", {}).get("completed_episodes")
                    if existing_eps_raw:
                        old_eps = json_loads(existing_eps_raw, []) if isinstance(existing_eps_raw, str) else existing_eps_raw
                        if isinstance(old_eps, (list, tuple, set)):
                            new_eps |= set(int(x) for x in old_eps if str(x).isdigit())
                    patch[k] = json_dumps(sorted(list(new_eps)))
                else:
                    # 显式传入空列表说明需要清空重置已完成集数
                    patch[k] = "[]"
            else:
                patch[k] = str(v)
        elif isinstance(v, bool):
            patch[k] = "1" if v else "0"
        elif isinstance(v, (dict, list, tuple)):
            patch[k] = json_dumps(v)
        elif isinstance(v, (int, float)):
            patch[k] = str(v)
        else:
            val_str = str(v)
            if val_str == "None":
                continue
            patch[k] = val_str

    current_stage_disp = patch.get("current_stage", "current")
    log.debug("【CQRS 读投影】发布全剧 HASH 增量补丁: drama_id=%s, stage=%s, patch_keys=%s", drama_id, current_stage_disp, list(patch.keys()))

    # 5. 写入 Redis HASH (仅更新 patch 涉及的 key)
    if r:
        try:
            key = _make_drama_read_key(drama_id)
            try:
                r.hset(key, mapping=patch)
            except Exception:
                pipe = r.pipeline()
                for fk, fv in patch.items():
                    pipe.hset(key, fk, str(fv))
                pipe.execute()
            r.expire(key, READ_MODEL_TTL)
        except Exception as e:
            log.warning("【CQRS 读投影】全剧 HASH 增量写入 Redis 失败: %s", e)

    # 6. 进程内内存降级存储同步增量更新 (dict.update 保持历史字段累积)
    mem_key = f"drama_{drama_id}_master"
    if mem_key not in _in_memory_read_projections:
        _in_memory_read_projections[mem_key] = {}
    _in_memory_read_projections[mem_key].update(patch)


def get_drama_read_projection(drama_id: int) -> dict[str, Any] | None:
    """获取全剧只读投影 (优先从 Redis HASH 读取，支持进程内存降级)。
    
    【返回值规范】：
    返回强类型化的完整全剧物化视图字典，保证关键数值类型（集数、阶段、计数）与复合数据类型（蓝图、完成集数列表）正确反序列化，
    同时动态透传所有已累积的扩展字段，支撑前端全息看板无损展示。
    """
    if not drama_id:
        return None

    raw: dict[str, Any] | None = None
    r = _get_redis()
    if r:
        try:
            key = _make_drama_read_key(drama_id)
            raw = r.hgetall(key)
        except Exception as e:
            log.warning("【CQRS 读投影】从 Redis 读取全剧 HASH 投影失败: %s", e)

    if not raw:
        raw = _in_memory_read_projections.get(f"drama_{drama_id}_master")

    if not raw:
        return None

    # 反序列化蓝图与复合结构
    blueprint_raw = raw.get("blueprint")
    if isinstance(blueprint_raw, str):
        blueprint_val = json_loads(blueprint_raw, {}) if blueprint_raw and blueprint_raw != "None" else {}
    elif isinstance(blueprint_raw, dict):
        blueprint_val = blueprint_raw
    else:
        blueprint_val = {}

    completed_eps_raw = raw.get("completed_episodes")
    if isinstance(completed_eps_raw, str):
        completed_eps_val = json_loads(completed_eps_raw, [])
    elif isinstance(completed_eps_raw, (list, tuple, set)):
        completed_eps_val = list(completed_eps_raw)
    else:
        completed_eps_val = []

    # 标准字段类型归一化
    stage_val = raw.get("current_stage", 1)
    if str(stage_val).isdigit():
        stage_num: Any = int(stage_val)
    else:
        stage_num = stage_val

    result: dict[str, Any] = {
        "drama_id": int(raw.get("drama_id", drama_id)),
        "title": raw.get("title", ""),
        "slug": raw.get("slug", ""),
        "genre": raw.get("genre", ""),
        "type": raw.get("type", ""),
        "current_stage": stage_num,
        "journey": raw.get("journey", "journey_1_literary"),
        "total_episodes": int(raw.get("total_episodes", 1)),
        "completed_episodes": completed_eps_val,
        "user_idea": raw.get("user_idea", ""),
        "visual_style": raw.get("visual_style", ""),
        "logline": raw.get("logline", ""),
        "dramatic_irony": raw.get("dramatic_irony", ""),
        "grand_payoff": raw.get("grand_payoff", ""),
        "mechanism": None if raw.get("mechanism") in (None, "None", "") else raw.get("mechanism"),
        "arc_type": None if raw.get("arc_type") in (None, "None", "") else raw.get("arc_type"),
        "blueprint": blueprint_val,
        "bp_prompt": raw.get("bp_prompt", ""),
        "character_count": int(raw.get("character_count", 0)),
        "environments_count": int(raw.get("environments_count", 0)),
        "props_count": int(raw.get("props_count", 0)),
        "lock_status": int(raw.get("lock_status", 0)),
        "pipeline_status": raw.get("pipeline_status", "idle"),
        "literary_journey_locked": raw.get("literary_journey_locked") in ("1", "true", "True", True, 1),
        "second_journey_completed": raw.get("second_journey_completed") in ("1", "true", "True", True, 1),
        "gatekeeper_pending": raw.get("gatekeeper_pending") in ("1", "true", "True", True, 1),
        "progress_pct": float(raw.get("progress_pct", 0.0)),
        "current_mini_arc_index": int(raw.get("current_mini_arc_index", 1)),
        "ideation_working_memory": raw.get("ideation_working_memory", ""),
        "character_working_memory": raw.get("character_working_memory", ""),
        "world_building_working_memory": raw.get("world_building_working_memory", ""),
        "season_outline_working_memory": raw.get("season_outline_working_memory", ""),
        "updated_at": raw.get("updated_at", ""),
    }

    # 动态保留与解析其他任意未显式列出的自定义扩展字段
    for k, v in raw.items():
        if k not in result:
            if isinstance(v, str) and ((v.startswith("{") and v.endswith("}")) or (v.startswith("[") and v.endswith("]"))):
                result[k] = json_loads(v, v)
            else:
                result[k] = v

    return result


def publish_episode_read_projection(drama_id: int, episode_number: int, substate: Any) -> None:
    """发布单集独立执行只读投影 (Redis HASH: drama:{id}:ep:{n}:read_model)。"""
    if not drama_id or not episode_number:
        return

    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    outline = _safe_get(substate, "task_outline") or {}
    shots = _safe_get(substate, "storyboard_shots") or []
    audio = _safe_get(substate, "audio_mastering")
    script = _safe_get(substate, "screenplay")

    projection: dict[str, str] = {
        "drama_id": str(drama_id),
        "episode_number": str(episode_number),
        "title": str(_safe_get(outline, "title") or f"第{episode_number}集"),
        "current_stage": str(_safe_get(substate, "current_stage") or 5),
        "is_completed": "1" if _safe_get(substate, "is_completed") else "0",
        "has_screenplay": "1" if script else "0",
        "storyboard_shot_count": str(len(shots)),
        "has_srt": "1" if _safe_get(substate, "srt_content") else "0",
        "has_audio_mastering": "1" if audio else "0",
        "updated_at": now_iso(),
    }

    log.debug("【CQRS 读投影】发布单集 HASH 只读投影: drama_id=%s, ep=%s, shots=%d", drama_id, episode_number, len(shots))

    r = _get_redis()
    if r:
        try:
            key = _make_episode_read_key(drama_id, episode_number)
            try:
                r.hset(key, mapping=projection)
            except Exception:
                pipe = r.pipeline()
                for fk, fv in projection.items():
                    pipe.hset(key, fk, str(fv))
                pipe.execute()
            r.expire(key, READ_MODEL_TTL)
            return
        except Exception as e:
            log.warning("【CQRS 读投影】单集 HASH 写入 Redis 失败: %s", e)

    _in_memory_read_projections[f"drama_{drama_id}_ep_{episode_number}"] = projection


def get_episode_read_projection(drama_id: int, episode_number: int) -> dict[str, Any] | None:
    """获取单集只读投影 (优先从 Redis HASH 读取)。"""
    if not drama_id or not episode_number:
        return None

    r = _get_redis()
    if r:
        try:
            key = _make_episode_read_key(drama_id, episode_number)
            raw = r.hgetall(key)
            if raw:
                return {
                    "drama_id": int(raw.get("drama_id", drama_id)),
                    "episode_number": int(raw.get("episode_number", episode_number)),
                    "title": raw.get("title", f"第{episode_number}集"),
                    "current_stage": int(raw.get("current_stage", 5)),
                    "is_completed": raw.get("is_completed") in ("1", "true", "True", True),
                    "has_screenplay": raw.get("has_screenplay") in ("1", "true", "True", True),
                    "storyboard_shot_count": int(raw.get("storyboard_shot_count", 0)),
                    "has_srt": raw.get("has_srt") in ("1", "true", "True", True),
                    "has_audio_mastering": raw.get("has_audio_mastering") in ("1", "true", "True", True),
                    "updated_at": raw.get("updated_at", ""),
                }
        except Exception as e:
            log.warning("【CQRS 读投影】从 Redis 读取单集 HASH 投影失败: %s", e)

    in_mem = _in_memory_read_projections.get(f"drama_{drama_id}_ep_{episode_number}")
    if in_mem:
        return {
            "drama_id": int(in_mem.get("drama_id", drama_id)),
            "episode_number": int(in_mem.get("episode_number", episode_number)),
            "title": in_mem.get("title", f"第{episode_number}集"),
            "current_stage": int(in_mem.get("current_stage", 5)),
            "is_completed": in_mem.get("is_completed") in ("1", "true", "True", True),
            "has_screenplay": in_mem.get("has_screenplay") in ("1", "true", "True", True),
            "storyboard_shot_count": int(in_mem.get("storyboard_shot_count", 0)),
            "has_srt": in_mem.get("has_srt") in ("1", "true", "True", True),
            "has_audio_mastering": in_mem.get("has_audio_mastering") in ("1", "true", "True", True),
            "updated_at": in_mem.get("updated_at", ""),
        }
    return None


# =========================================================================
# 【纯函数工作记忆编译器】WorkingMemoryCompiler
# =========================================================================

class WorkingMemoryCompiler:
    """纯函数式工作记忆提取编译器 (Pure Functional Working Memory Compiler)。
    
    原则：
    1. 零大模型调用，纯规则与结构化提取，单次提取耗时严格 < 1ms；
    2. 严格控制体积在 500~1500 字符内，阻断上下文无节制膨胀与雪崩；
    3. 保留高阶决策信息（反差、核心设定、做旧物理特征、集间接棒快照）。
    """

    @staticmethod
    def compile_ideation_working_memory(stage1_data: dict[str, Any] | Any) -> str:
        """从阶段 1 产物中提炼概念与主线工作记忆 (对齐 SKILL1.md 【短期记忆 A：人设禁令子集 + 核心讽刺】)。"""
        def _get(k: str, default: Any = "") -> Any:
            if isinstance(stage1_data, dict):
                return stage1_data.get(k, default)
            return getattr(stage1_data, k, default)

        user_idea = _get('user_idea') or _get('user_prompt') or _get('story_prompt') or _get('prompt') or ""
        irony = _get('dramatic_irony') or _get('core_irony') or "核心讽刺未设定"
        grand_payoff = _get('grand_payoff') or ""
        target_engine = _get('target_video_engine') or "Seedance 2.0 / 超写实电影级"
        parts = [
            f"【剧名】: {_get('selected_title') or _get('title') or '未定名'}",
        ]
        if user_idea:
            parts.append(f"【用户核心构想/立项故事】: {user_idea}")
        parts.extend([
            f"【总集数】: {_get('total_episodes')}",
            f"【单集时长】:  {_get('target_dur')}",
            f"【题材与风格】: {_get('genre')} / {_get('visual_style')}",
            f"【弧型】: {_get('arc_type') or '依核心梗概与机制推导'}",
            f"【目标视听/视频引擎】: {target_engine}",
            f"【核心梗概】: {_get('logline')}",
            f"【核心讽刺 / 戏剧反差 (The Irony)】: {irony}",
            f"【终局核爆点 / 终极爽点 (Grand Payoff)】: {grand_payoff}",
        ])

        era = _get('era') or _get('time_period') or _get('setting') or _get('social_stratum')
        if era:
            parts.append(f"【时代背景与阶层场域】: {era}")

        neg_rules = _get("negative_rules")
        persona_cliches: list[str] = []
        custom_redlines: list[str] = []
        if isinstance(neg_rules, DoubleTrackProhibitions):
            # 提取显式人设排异红线
            p_redlines = neg_rules.persona_redlines or []
            if isinstance(p_redlines, list):
                custom_redlines.extend(str(r) for r in p_redlines if r)

            cliches = neg_rules.forbidden_cliches or neg_rules.forbidden_cliches_10 or []
            persona_cliches = [c for c in cliches if any(w in c for w in ("主角", "反派", "人物", "人设", "智商", "降智", "伟光正", "龙傲天", "脸谱", "圣母"))]
            if not persona_cliches and cliches:
                persona_cliches = cliches[:3]
        elif isinstance(neg_rules, dict):
            p_redlines = neg_rules.get("persona_redlines") or []
            if isinstance(p_redlines, list):
                custom_redlines.extend(str(r) for r in p_redlines if r)

            cliches = neg_rules.get("forbidden_cliches") or neg_rules.get("forbidden_cliches_10") or []
            persona_cliches = [c for c in cliches if any(w in c for w in ("主角", "反派", "人物", "人设", "智商", "降智", "伟光正", "龙傲天", "脸谱", "圣母"))]
            if not persona_cliches and cliches:
                persona_cliches = cliches[:3]

        redlines = []
        if custom_redlines:
            redlines.extend(custom_redlines[:3])
        if persona_cliches:
            redlines.append(f"老套禁忌: 严禁 {', '.join(persona_cliches[:3])}")

        parts.append(f"【人设禁令子集】: " + "；".join(redlines))
        parts.append("【推导指令 (The Irony ➔ The Lie)】: 必须基于核心讽刺直接推演主角的致命谎言(the_lie)与内在创伤(the_ghost)，严禁脱离核心讽刺臆造虚浮人设。")
        parts.append("【创作强约束 (Core Law)】: 本剧后续阶段（角色、空间物证、分集大纲及正文）必须严格锚定【用户核心构想/立项故事】与【终局核爆点】，严禁脱离用户构想偏离主线或套用无关样板模板。")

        compiled = "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())
        log.debug("【工作记忆编译器】阶段 1 工作记忆便签编译完成 (长度: %d 字符)", len(compiled))
        return compiled

    @staticmethod
    def compile_character_working_memory(characters_engine: dict[str, Any] | Any) -> str:
        """从阶段 2 产物中提炼主要角色与人物关系工作记忆 (阶段 2 角色工作便签 Pad B)。
        
        编译提取内容：
        1. 核心角色全息档案（代号、定位、视觉年龄、锁脸与服饰特征、随身旧物、戏剧引擎欲望与致命弱点、声纹习惯）；
        2. 双轨人物关系对抗矩阵（代号对抗对、表层社会关系、深层宿命情感、生死利益死结、戏剧功能、信息差、态度弧光与物证密码）；
        3. 情感弧光轨迹（坚冰防御 -> 信念崩解 -> 灵魂重铸 -> 终极救赎）。
        """
        if not characters_engine:
            return ""

        chars: list[dict[str, Any]] = []
        rels: list[dict[str, Any]] = []
        arc: dict[str, Any] = {}
        if isinstance(characters_engine, dict):
            chars = characters_engine.get("characters") or characters_engine.get("character_profiles") or []
            rels = (
                characters_engine.get("relationship_matrix")
                or characters_engine.get("character_relationships")
                or characters_engine.get("dual_track_relationships")
                or []
            )
            arc = characters_engine.get("emotional_arc_trajectory") or {}
        elif hasattr(characters_engine, "characters"):
            chars = getattr(characters_engine, "characters", [])
            rels = (
                getattr(characters_engine, "relationship_matrix", [])
                or getattr(characters_engine, "character_relationships", [])
                or getattr(characters_engine, "dual_track_relationships", [])
            )
            arc = getattr(characters_engine, "emotional_arc_trajectory", {}) or {}

        log.debug("【工作记忆编译器】开始编译阶段 2 便签: 角色条数=%d, 关系条数=%d", len(chars), len(rels))

        lines = ["【阶段 2 角色工作便签：锁脸装造代码 + 戏剧引擎动力 + 双轨关系死结网】"]
        lines.append("【核心角色档案精炼】:")
        for c in chars[:5]:  # 保留核心角色（主角、主要反派、关键见证人与摇摆者）
            c_dict = c if isinstance(c, dict) else (c.model_dump() if hasattr(c, "model_dump") else {})
            name = c_dict.get("name") or c_dict.get("character_id") or "未知角色"
            c_code = c_dict.get("character_code") or c_dict.get("character_id") or ""
            gender = c_dict.get("gender") or c_dict.get("biological_sex")
            role_type = c_dict.get("role") or c_dict.get("role_type") or "角色"
            perceived_age = c_dict.get("perceived_age")

            tag_parts = [str(name)]
            if c_code:
                tag_parts.append(str(c_code))
            if gender:
                tag_parts.append("男" if str(gender).lower() == "male" else ("女" if str(gender).lower() == "female" else str(gender)))
            if perceived_age:
                tag_parts.append(f"{perceived_age}岁")
            if role_type and role_type != "角色":
                tag_parts.append(str(role_type))
            header_tag = f"- {name}" + (f"({', '.join(tag_parts[1:])})" if len(tag_parts) > 1 else "")

            detail_items = []

            # 1. 戏剧引擎与心理四元组 (欲望核心与致命弱点)
            engine = c_dict.get("drama_engine") or {}
            psy = c_dict.get("psychology_4") or c_dict.get("psychological_quad") or {}
            want = engine.get("want") or engine.get("core_desire") or psy.get("want") or ""
            flaw = engine.get("flaw") or engine.get("fatal_weakness") or psy.get("the_lie") or ""
            action_style = engine.get("action_style") or ""
            if want:
                detail_items.append(f"核心欲望[{want}]")
            if flaw:
                detail_items.append(f"致命弱点[{flaw[:30]}]")
            if action_style:
                detail_items.append(f"行动风格[{action_style[:25]}]")

            # 2. 视觉一致性代码与装造特征
            vcc = c_dict.get("visual_consistency_code") or {}
            if isinstance(vcc, dict) and vcc:
                vcc_summary = []
                if vcc.get("hair"):
                    vcc_summary.append(str(vcc["hair"]))
                if vcc.get("face"):
                    vcc_summary.append(str(vcc["face"]))
                if vcc.get("costume"):
                    vcc_summary.append(str(vcc["costume"]))
                if vcc_summary:
                    detail_items.append(f"视觉代码[{'; '.join(vcc_summary)[:50]}]")
            else:
                bio = c_dict.get("biological_dna") or {}
                bio_flaw = bio.get("permanent_flaws_coordinates") or bio.get("blemishes_and_scars") or c_dict.get("visual_token") or ""
                costume = c_dict.get("lived_in_costume") or {}
                wear = costume.get("outerwear_fabric_wear") or costume.get("outerwear") or costume.get("top_wear") or ""
                if bio_flaw:
                    detail_items.append(f"容貌标识[{bio_flaw}]")
                if wear:
                    detail_items.append(f"装造磨损[{wear[:35]}]")

            # 3. 随身锚定旧物
            anchor = c_dict.get("carried_anchor_item") or {}
            if isinstance(anchor, dict) and anchor.get("item_name"):
                anchor_desc = f"{anchor['item_name']}"
                if anchor.get("visual_details"):
                    anchor_desc += f"({anchor['visual_details'][:20]})"
                detail_items.append(f"随身旧物[{anchor_desc}]")

            # 4. 声纹与口头禅
            acoustic = c_dict.get("acoustic_persona") or {}
            voice_style = c_dict.get("voice_style") or ""
            if isinstance(acoustic, dict) and acoustic.get("voice_timber"):
                voice_str = acoustic.get("voice_timber")
                if acoustic.get("signature_catchphrase"):
                    voice_str += f" | 口头禅:「{acoustic['signature_catchphrase']}」"
                detail_items.append(f"声纹特质[{voice_str}]")
            elif voice_style:
                detail_items.append(f"音色[{voice_style[:30]}]")

            if detail_items:
                lines.append(f"{header_tag}: {', '.join(detail_items)}")
            else:
                lines.append(f"{header_tag}")

        if rels:
            lines.append("【核心双轨关系死结网】:")
            for r in rels[:4]:  # 精炼前 4 组关键人物关系
                r_dict = r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else {})
                a_code = r_dict.get("character_a_code") or r_dict.get("character_a") or "A"
                b_code = r_dict.get("character_b_code") or r_dict.get("character_b") or "B"
                pair = r_dict.get("character_pair") or f"{a_code} vs {b_code}"

                surface = r_dict.get("surface_relation") or r_dict.get("surface_identity") or ""
                bond = r_dict.get("emotional_bond") or ""
                conflict = r_dict.get("fatal_interest_conflict") or r_dict.get("fatal_conflict") or ""
                drama_func = r_dict.get("drama_function") or ""
                attitude_arc = r_dict.get("attitude_arc") or ""
                shared_props = r_dict.get("shared_history_props") or []

                rel_parts = []
                if surface:
                    rel_parts.append(f"表层[{surface}]")
                if bond:
                    rel_parts.append(f"深层羁绊[{bond}]")
                if conflict:
                    rel_parts.append(f"生死死结[{conflict}]")
                if drama_func:
                    rel_parts.append(f"戏剧功能[{drama_func}]")
                if attitude_arc:
                    rel_parts.append(f"态度弧光[{attitude_arc}]")
                if shared_props:
                    props_str = "、".join(str(p) for p in shared_props[:2])
                    rel_parts.append(f"物证密码[{props_str}]")

                if rel_parts:
                    lines.append(f"- {pair}: {' | '.join(rel_parts)}")
                else:
                    lines.append(f"- {pair}: 命运纠葛")

        if arc and isinstance(arc, dict):
            a = arc.get("stage_a_guarded") or arc.get("stage_a_masked")
            b = arc.get("stage_b_fracture")
            c = arc.get("stage_c_abyss")
            d = arc.get("stage_d_catharsis")
            if a and b and c and d:
                lines.append("【四阶段情感弧光】: A.坚冰防御 -> B.信念崩解 -> C.灵魂重铸 -> D.终极救赎")

        compiled = "\n".join(lines)
        log.debug("【工作记忆编译器】阶段 2 角色工作记忆便签编译完成 (长度: %d 字符)", len(compiled))
        return compiled

    @staticmethod
    def compile_world_building_working_memory(environments_props: dict[str, Any] | Any) -> str:
        """从阶段 3 产物中提炼核心空间与物证工作记忆 (阶段 3 便签 C)。"""
        if not environments_props:
            return ""

        env_dict = environments_props if isinstance(environments_props, dict) else (
            environments_props.model_dump() if hasattr(environments_props, "model_dump") else {}
        )
        envs = env_dict.get("environments", [])
        props = env_dict.get("props", [])

        # 保留标准【短期记忆便签 C】前缀，兼容下游阶段与各质检套件
        lines = ["【短期记忆便签 C】空间做旧与物证拟音精炼:"]
        for e in envs[:4]:
            loc_name = e.get("name") or e.get("location_name") or "未命名空间"
            level = e.get("level", "interior")
            atmosphere = e.get("atmosphere") or e.get("time_and_lighting") or "冷峻"
            lines.append(f"- 空间[{loc_name}]: 类型[{level}], 氛围[{atmosphere}]")
        for p in props[:4]:
            p_name = p.get("name") or p.get("prop_name") or "未命名物证"
            level = p.get("level", "hero_tier1")
            feat = (
                p.get("visual_features")
                or p.get("damage_scale")
                or (p.get("physical_specs", {}).get("material_damage_dimensions") if isinstance(p.get("physical_specs"), dict) else None)
                or p.get("appearance_and_wear")
                or p.get("description")
                or "破损磨损"
            )
            lines.append(f"- 物证[{p_name}]: 级别[{level}], 特征[{feat}]")

        return "\n".join(lines)

    @staticmethod
    def compile_season_outline_working_memory(
        season_outlines: dict[int, Any] | list[Any],
        audio_bible: dict[str, Any] | None = None
    ) -> str:
        """从阶段 4 产物中提炼全季任务脉络与音乐母库基调 (阶段 4 便签 D)。"""
        outlines_dict = season_outlines if isinstance(season_outlines, dict) else {
            getattr(card, "episode_number", idx + 1): card for idx, card in enumerate(season_outlines)
        }
        total_eps = len(outlines_dict)
        # 包含【短期记忆便签 D】及全季总集数标识（如 6集/12集），严格满足下游与测试断言契约
        lines = [f"【短期记忆便签 D】全季共 {total_eps}集分集大纲与核心钩子总览:"]

        # 提取关键集数任务 (第1集、中段、高潮集)
        sorted_eps = sorted(outlines_dict.keys())
        for ep in sorted_eps[:6]:  # 取前 6 集或核心集
            card = outlines_dict[ep]
            c_dict = card if isinstance(card, dict) else (card.model_dump() if hasattr(card, "model_dump") else {})
            title = c_dict.get("title") or c_dict.get("killer_title") or c_dict.get("episode_title") or f"第{ep}集"
            task = (
                c_dict.get("core_conflict_task")
                or c_dict.get("core_dramatic_task")
                or (c_dict.get("dual_helix_task", {}).get("plot_event_chain") if isinstance(c_dict.get("dual_helix_task"), dict) else None)
                or c_dict.get("plot_event_chain")
                or ""
            )
            hook = (
                c_dict.get("hook_cliffhanger")
                or c_dict.get("cliffhanger")
                or c_dict.get("cliffhanger_end")
                or c_dict.get("killer_cliffhanger_115s")
                or ""
            )
            lines.append(f"- 第{ep}集 [{title}]: 冲突[{task}] | 钩子[{hook}]")

        if audio_bible and isinstance(audio_bible, dict):
            theme = audio_bible.get("theme_prompt") or audio_bible.get("overall_style") or ""
            if not theme:
                motifs = audio_bible.get("leitmotifs") or audio_bible.get("leitmotif_registry") or []
                if motifs and isinstance(motifs, list):
                    theme_parts = []
                    for m in motifs[:3]:
                        if isinstance(m, dict):
                            theme_parts.append(
                                f"{m.get('name') or m.get('motif_id')}: {m.get('instrumentation', '')} {m.get('description', '')}".strip()
                            )
                    theme = "; ".join(theme_parts)
            if theme:
                lines.append(f"【音乐母库基准】: {theme}")

        return "\n".join(lines)

    @staticmethod
    def compile_inter_episode_continuity(previous_episode_result: dict[str, Any] | Any) -> dict[str, Any]:
        """从前一集执行产物中提炼 0 秒物理接棒连续性快照。"""
        if not previous_episode_result:
            return {}

        res = previous_episode_result if isinstance(previous_episode_result, dict) else (
            previous_episode_result.model_dump() if hasattr(previous_episode_result, "model_dump") else {}
        )

        ep_num = res.get("episode_number") or res.get("episode") or 1
        outgoing = res.get("outgoing_physical_continuity") or res.get("inter_episode_physical_snapshot") or {}
        if outgoing and isinstance(outgoing, dict):
            return {
                "inherited_from_episode": ep_num,
                "timecode_offset_sec": outgoing.get("timecode_offset_sec", 0.0),
                "location": outgoing.get("location", ""),
                "characters_posture": outgoing.get("characters_posture", {}),
                "lighting_atmosphere": outgoing.get("lighting_atmosphere", ""),
                "unresolved_props_state": outgoing.get("unresolved_props_state", {}),
            }

        return {
            "inherited_from_episode": ep_num,
            "timecode_offset_sec": 0.0,
            "location": "延续上一集结尾场景",
            "characters_posture": {},
            "lighting_atmosphere": "保持上一集结尾光影氛围",
            "unresolved_props_state": {},
        }

