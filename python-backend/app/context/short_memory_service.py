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
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_config
from app.core.logger import get_logger
from app.platform_common import now_iso, json_dumps, json_loads

log = get_logger("lmd.short_memory")

# 短期记忆在 Redis 中的默认过期时间：7 天（秒）
SHORT_MEMORY_TTL = 7 * 86400

# Redis 客户端单例缓存
_redis_client: Any = None
_redis_checked: bool = False
# 进程内内存降级存储（当未配置 Redis 或 Redis 宕机时使用）
_in_memory_scratchpads: dict[int, dict[str, Any]] = {}


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


def _make_key(drama_id: int) -> str:
    """生成剧目短期记忆在 Redis 中的 Hash Key。"""
    return f"lmd:drama:{drama_id}:short_memories"


def set_short_memories(
    drama_id: int,
    memories: dict[str, Any],
    stage_name: str = "",
) -> None:
    """更新剧目的短期工作记忆便签与第二程物理资源快照。

    参数:
        drama_id: 短剧主键 ID
        memories: 包含 pad_a, pad_b, pad_c, pad_d, inter_episode_physical_snapshot, current_resource_manifest 的字典
        stage_name: 当前正在执行或刚完成的流水线阶段名称（如 stage1_proposal, stage7_storyboard）
    """
    if not drama_id:
        return

    # 规范化物理快照与资源清单字段（转为 JSON 字符串或标准结构）
    phys_snap = memories.get("inter_episode_physical_snapshot") or memories.get("physical_snapshot") or {}
    if not isinstance(phys_snap, str):
        phys_snap_str = json_dumps(phys_snap)
    else:
        phys_snap_str = phys_snap

    res_manifest = memories.get("current_resource_manifest") or memories.get("resource_manifest") or {}
    if not isinstance(res_manifest, str):
        res_manifest_str = json_dumps(res_manifest)
    else:
        res_manifest_str = res_manifest

    data: dict[str, str] = {
        "pad_a": str(memories.get("pad_a") or memories.get("scratchpad_a") or "").strip(),
        "pad_b": str(memories.get("pad_b") or memories.get("scratchpad_b") or "").strip(),
        "pad_c": str(memories.get("pad_c") or memories.get("scratchpad_c") or "").strip(),
        "pad_d": str(memories.get("pad_d") or memories.get("scratchpad_d") or "").strip(),
        "inter_episode_physical_snapshot": phys_snap_str,
        "current_resource_manifest": res_manifest_str,
        "stage_name": stage_name or str(memories.get("stage_name") or ""),
        "updated_at": now_iso(),
    }

    log.debug(
        "【短期记忆】更新剧目 [%s] 短期记忆 (阶段: %s): A_len=%d, B_len=%d, C_len=%d, D_len=%d, 物理快照=%d字符, 资源清单=%d字符",
        drama_id,
        data["stage_name"],
        len(data["pad_a"]),
        len(data["pad_b"]),
        len(data["pad_c"]),
        len(data["pad_d"]),
        len(data["inter_episode_physical_snapshot"]),
        len(data["current_resource_manifest"]),
    )

    # 1. 尝试写入 Redis
    r = _get_redis()
    if r:
        try:
            key = _make_key(drama_id)
            try:
                r.hset(key, mapping=data)
            except Exception:
                # 兼容低版本 Redis / 严格双参数 HSET
                pipe = r.pipeline()
                for f_k, f_v in data.items():
                    pipe.hset(key, f_k, str(f_v))
                pipe.execute()
            r.expire(key, SHORT_MEMORY_TTL)
            return
        except Exception as e:
            log.warning("【短期记忆】写入 Redis 失败，降级至进程内存: %s", e)

    # 2. 内存降级存储
    _in_memory_scratchpads[drama_id] = data


def get_short_memories(
    drama_id: int,
    db: Session | None = None,
) -> dict[str, Any]:
    """获取剧目的当前短期记忆（便签 + 物理连续性快照 + 资源清单）。

    查询顺序：
    1. Redis Hash 缓存
    2. 进程内内存缓存
    3. 若未命中且提供了 db Session，则从数据库权威业务表中重建 (Cache-Aside)
    """
    if not drama_id:
        return {
            "pad_a": "",
            "pad_b": "",
            "pad_c": "",
            "pad_d": "",
            "inter_episode_physical_snapshot": {},
            "current_resource_manifest": {},
            "stage_name": "",
        }

    # 1. 尝试从 Redis 读取
    r = _get_redis()
    if r:
        try:
            key = _make_key(drama_id)
            raw = r.hgetall(key)
            if raw and any(raw.get(k) for k in ("pad_a", "pad_b", "pad_c", "pad_d", "inter_episode_physical_snapshot")):
                return {
                    "pad_a": raw.get("pad_a", ""),
                    "pad_b": raw.get("pad_b", ""),
                    "pad_c": raw.get("pad_c", ""),
                    "pad_d": raw.get("pad_d", ""),
                    "inter_episode_physical_snapshot": json_loads(raw.get("inter_episode_physical_snapshot"), {}),
                    "current_resource_manifest": json_loads(raw.get("current_resource_manifest"), {}),
                    "stage_name": raw.get("stage_name", ""),
                    "updated_at": raw.get("updated_at", ""),
                }
        except Exception as e:
            log.warning("【短期记忆】读取 Redis 失败，尝试读取内存或数据库: %s", e)

    # 2. 尝试从内存读取
    if drama_id in _in_memory_scratchpads:
        mem_data = dict(_in_memory_scratchpads[drama_id])
        return {
            "pad_a": mem_data.get("pad_a", ""),
            "pad_b": mem_data.get("pad_b", ""),
            "pad_c": mem_data.get("pad_c", ""),
            "pad_d": mem_data.get("pad_d", ""),
            "inter_episode_physical_snapshot": json_loads(mem_data.get("inter_episode_physical_snapshot"), {}) if isinstance(mem_data.get("inter_episode_physical_snapshot"), str) else mem_data.get("inter_episode_physical_snapshot", {}),
            "current_resource_manifest": json_loads(mem_data.get("current_resource_manifest"), {}) if isinstance(mem_data.get("current_resource_manifest"), str) else mem_data.get("current_resource_manifest", {}),
            "stage_name": mem_data.get("stage_name", ""),
            "updated_at": mem_data.get("updated_at", ""),
        }

    # 3. 数据库重建 (Cache-Aside 回退)
    if db is not None:
        log.info("【短期记忆】缓存未命中，从数据库重建剧目 [%s] 的短期记忆便签与物理快照...", drama_id)
        reconstructed = reconstruct_from_db(db, drama_id)
        # 写回缓存以便后续快速读取
        set_short_memories(drama_id, reconstructed, stage_name="reconstructed_from_db")
        return reconstructed

    return {
        "pad_a": "",
        "pad_b": "",
        "pad_c": "",
        "pad_d": "",
        "inter_episode_physical_snapshot": {},
        "current_resource_manifest": {},
        "stage_name": "",
    }


def reconstruct_from_db(db: Session, drama_id: int) -> dict[str, Any]:
    """从数据库权威业务表中提取信息，重新拼装出 Pad A/B/C/D 短期工作记忆与第二程快照。

    提取来源：
    - Pad A: dramas 表的 name, target_audience, core_selling_points, logline, drama_type 等
    - Pad B: characters 表的主要人物列表及 stage 变体
    - Pad C: scenes 与 props 表的场景和核心道具清单
    - Pad D: episodes 表的 hook, climax 与 storyboards 未决伏笔
    - inter_episode_physical_snapshot: 最近一集的角色状态演进与道具状态
    - current_resource_manifest: 最近一集的已生成分镜与音频资产概况
    """
    pad_a_parts = []
    pad_b_parts = []
    pad_c_parts = []
    pad_d_parts = []
    physical_snapshot = {}
    resource_manifest = {}

    try:
        # 1. 读取主剧目表 (dramas)
        drama_row = db.execute(
            text(
                """
                SELECT id, name, theme, drama_type, target_audience, core_selling_points,
                       logline, emotional_tone, genre, market_analysis, world_view
                FROM dramas WHERE id = :id
                """
            ),
            {"id": drama_id},
        ).mappings().first()

        if drama_row:
            d = dict(drama_row)
            pad_a_parts.append(f"【剧名】: {d.get('name') or '未定名'}")
            if d.get("drama_type"):
                pad_a_parts.append(f"【类型】: {d.get('drama_type')} / {d.get('genre') or ''}")
            if d.get("target_audience"):
                pad_a_parts.append(f"【目标受众】: {d.get('target_audience')}")
            if d.get("core_selling_points"):
                pad_a_parts.append(f"【核心爽点/卖点】: {d.get('core_selling_points')}")
            if d.get("logline"):
                pad_a_parts.append(f"【一句话梗概】: {d.get('logline')}")
            if d.get("emotional_tone"):
                pad_a_parts.append(f"【情绪基调】: {d.get('emotional_tone')}")

        # 2. 读取角色表 (characters)
        char_rows = db.execute(
            text(
                """
                SELECT id, name, role_type, personality, arc, appearance_features
                FROM characters WHERE drama_id = :drama_id
                ORDER BY id ASC LIMIT 10
                """
            ),
            {"drama_id": drama_id},
        ).mappings().all()

        for c in char_rows:
            char_info = f"- {c.get('name')} ({c.get('role_type') or '配角'}): 性格[{c.get('personality') or '普通'}] 弧光[{c.get('arc') or '发展中'}]"
            pad_b_parts.append(char_info)
            physical_snapshot[str(c.get("name"))] = {
                "character_id": c.get("id"),
                "last_clothing_state": "标准初始状态",
                "injuries_or_damage": "无",
                "held_props": [],
            }

        # 3. 读取场景与道具表 (scenes, props)
        scene_rows = db.execute(
            text("SELECT name, atmosphere, environment FROM scenes WHERE drama_id = :drama_id LIMIT 6"),
            {"drama_id": drama_id},
        ).mappings().all()
        for s in scene_rows:
            pad_c_parts.append(f"场景: {s.get('name')} | 氛围: {s.get('atmosphere') or '日常'}")

        prop_rows = db.execute(
            text("SELECT name, importance, description FROM props WHERE drama_id = :drama_id LIMIT 8"),
            {"drama_id": drama_id},
        ).mappings().all()
        for p in prop_rows:
            pad_c_parts.append(f"道具: {p.get('name')} ({p.get('importance') or '常规'}) - {p.get('description') or ''}")

        # 4. 读取分集悬念与伏笔 (episodes)
        ep_rows = db.execute(
            text(
                """
                SELECT id, episode_number, title, hook, climax, cliffhanger
                FROM episodes WHERE drama_id = :drama_id
                ORDER BY episode_number ASC
                """
            ),
            {"drama_id": drama_id},
        ).mappings().all()

        for ep in ep_rows:
            ep_hook = ep.get("cliffhanger") or ep.get("hook") or ep.get("climax")
            if ep_hook:
                pad_d_parts.append(f"第{ep.get('episode_number')}集 [{ep.get('title') or ''}]: 钩子/悬念 -> {ep_hook}")

        # 5. 读取最近的分镜资产概况 (storyboards)
        if ep_rows:
            last_ep = ep_rows[-1]
            sb_count_row = db.execute(
                text("SELECT COUNT(*) as c FROM storyboards WHERE episode_id = :ep_id"),
                {"ep_id": last_ep.get("id")},
            ).first()
            resource_manifest["last_episode_num"] = last_ep.get("episode_number")
            resource_manifest["storyboard_shots_count"] = sb_count_row[0] if sb_count_row else 0

    except Exception as e:
        log.error("【短期记忆】从数据库重建短期记忆异常: %s", e, exc_info=True)

    return {
        "pad_a": "\n".join(pad_a_parts),
        "pad_b": "\n".join(pad_b_parts),
        "pad_c": "\n".join(pad_c_parts),
        "pad_d": "\n".join(pad_d_parts),
        "inter_episode_physical_snapshot": physical_snapshot,
        "current_resource_manifest": resource_manifest,
        "stage_name": "reconstructed_from_db",
        "updated_at": now_iso(),
    }


def clear_short_memories(drama_id: int) -> None:
    """清理指定剧目的短期记忆（在剧目重置或删除时调用）。"""
    if not drama_id:
        return
    r = _get_redis()
    if r:
        try:
            r.delete(_make_key(drama_id))
        except Exception as e:
            log.warning("【短期记忆】清理 Redis 缓存失败: %s", e)
    _in_memory_scratchpads.pop(drama_id, None)
