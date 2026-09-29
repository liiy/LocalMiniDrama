#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剧集蓝图生成器 (Episode Blueprint Builder)
==========================================
把「总集数」翻译成「全剧共用的节奏基准」。

职责边界：
    程序做：查表、算术、校验
    程序不做：任何创作决策、arc_type/mechanism 判定（由上游 bible 阶段的大模型完成）

数据流：
    01_bible.json -> build_blueprint() -> 02_blueprint.json -> 注入大纲提示词

用法：
    # 从 bible 文件生成
    python blueprint.py --bible 01_bible.json --out 02_blueprint.json

    # 直接给参数
    python blueprint.py --episodes 12 --arc revenge --mechanism investigation --duration 120

    # 强制指定锚点 + 换段落策略
    python blueprint.py --bible 01_bible.json --force reveal=9 --strategy hybrid

    # 只校验不落盘
    python blueprint.py --bible 01_bible.json --dry-run

    # 全量回归扫描（1~200集）
    python blueprint.py --scan
"""

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# 0. 常量与配置加载
# ============================================================================

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# 标准锚点顺序（不含核心揭晓锚点，其名称随 arc_type 变化）
BASE_ANCHOR_ORDER = [
    "first_counterattack",
    "first_suspicion",
    "safe_low_start",
    # <-- 核心揭晓锚点插入位置（reveal / detonation_point / upgrade_point）
    "ultimate_antagonist",
    "finale",
]


class BlueprintError(Exception):
    """致命校验未通过时抛出，不返回半成品。"""
    pass


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """加载配置表。"""
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: Dict[str, Any]) -> None:
    """配置表自检：防止改配置改出洞。"""
    required = [
        "version", "tier_rule", "anchor_pct", "arc_modifier",
        "arc_modifier_exception", "reveal_key_by_arc",
        "mechanism_reveal_mode", "duration_modifier", "density_base",
    ]
    for k in required:
        if k not in cfg:
            raise BlueprintError(f"配置表缺少必需项: {k}")

    def _keys(d):
        return {k for k in d.keys() if not k.startswith("_")}

    tiers_in_rule = {r["tier"] for r in cfg["tier_rule"]}
    tiers_in_pct = _keys(cfg["anchor_pct"])
    tiers_in_density = _keys(cfg["density_base"])
    if not (tiers_in_rule == tiers_in_pct == tiers_in_density):
        raise BlueprintError(
            f"配置表 tier 不一致: rule={tiers_in_rule} pct={tiers_in_pct} density={tiers_in_density}"
        )

    # 每个 tier 的锚点键必须齐全
    base_keys = set(BASE_ANCHOR_ORDER) | {"reveal"}
    for tier, pcts in cfg["anchor_pct"].items():
        if set(pcts.keys()) != base_keys:
            raise BlueprintError(f"档位 {tier} 的锚点键不完整: {set(pcts.keys())}")
        for name, rng in pcts.items():
            if not (0 < rng[0] <= rng[1] <= 1.0):
                raise BlueprintError(f"档位 {tier} 锚点 {name} 区间非法: {rng}")


# ============================================================================
# 1. tier_resolver —— 档位判定
# ============================================================================

def arc_types(cfg: Dict[str, Any]) -> List[str]:
    """合法弧型列表（剔除 _comment 等注释键）。"""
    return [k for k in cfg["arc_modifier"].keys() if not k.startswith("_")]


def resolve_tier(total_episodes: int, cfg: Dict[str, Any]) -> Tuple[str, int]:
    """集数 -> (tier, 目标段落数)。"""
    for rule in cfg["tier_rule"]:
        max_ep = rule["max_episodes"]
        if max_ep is None or total_episodes <= max_ep:
            return rule["tier"], rule["target_segments"]
    raise BlueprintError(f"无法判定档位: {total_episodes}")


# ============================================================================
# 2~3. anchor_calculator —— 弧型修正 + 锚点换算
# ============================================================================

def resolve_anchor_order(
    arc_type: str, tier: str, total_episodes: int, cfg: Dict[str, Any]
) -> Tuple[List[str], str]:
    """
    返回 (锚点顺序, 核心揭晓锚点名称)。
    survival/growth 无单一揭晓，核心锚点替换为 detonation_point / upgrade_point。
    短集数档位（如 mini）可按配置精简锚点数量。
    """
    reveal_key = cfg["reveal_key_by_arc"].get(arc_type, "reveal")
    full = BASE_ANCHOR_ORDER[:3] + [reveal_key] + BASE_ANCHOR_ORDER[3:]

    subset = None
    rules = (cfg.get("anchor_subset_by_episodes", {}) or {}).get("rules", [])
    for r in rules:
        if r.get("max_episodes") is None or total_episodes <= r["max_episodes"]:
            subset = r.get("anchors")
            break
    if subset:
        wanted = [reveal_key if x == "reveal" else x for x in subset]
        order = [x for x in full if x in wanted]
        if not order:
            order = full
    else:
        order = full
    return order, reveal_key


def _resolve_modifiers(
    arc_type: str, mechanism: Optional[str], cfg: Dict[str, Any]
) -> Tuple[Dict[str, float], List[str]]:
    """
    计算实际生效的修正系数，返回 (系数表, 被例外条款跳过的记录)。
    系数作用于【百分比】，不是集数。
    """
    mods = dict(cfg["arc_modifier"].get(arc_type, {}))
    skipped: List[str] = []

    exceptions = cfg["arc_modifier_exception"].get(mechanism or "", {})
    skip_map = exceptions.get("skip", {})
    for anchor_name in skip_map.get(arc_type, []):
        if anchor_name in mods:
            mods.pop(anchor_name)
            skipped.append(
                f"{mechanism} 机制触发例外条款：忽略 {arc_type} 对 {anchor_name} 的修正"
            )
    return mods, skipped


def calculate_anchors(
    total_episodes: int,
    tier: str,
    arc_type: str,
    mechanism: Optional[str],
    cfg: Dict[str, Any],
) -> Tuple[Dict[str, float], Dict[str, float], List[str]]:
    """
    返回 (浮点锚点表, 生效系数表, 例外记录)。
    取区间中值 × 修正系数。取中值保证可复现且不贴死边界。
    """
    order, _ = resolve_anchor_order(arc_type, tier, total_episodes, cfg)
    pct_table = cfg["anchor_pct"][tier]
    mods, skipped = _resolve_modifiers(arc_type, mechanism, cfg)

    raw: Dict[str, float] = {}
    for name in order:
        # 锚点表键名统一为 reveal（detonation_point / upgrade_point 复用其区间）
        pct_key = "reveal" if name in ("detonation_point", "upgrade_point") else name
        lo, hi = pct_table[pct_key]
        mid = (lo + hi) / 2.0
        mid *= mods.get(pct_key, 1.0)
        raw[name] = total_episodes * mid

    return raw, mods, skipped


def _project_monotone(
    base: Dict[str, int],
    order: List[str],
    total_episodes: int,
    min_gap: int,
    fixed: Optional[set] = None,
    floor: Optional[List[int]] = None,
) -> Dict[str, int]:
    """
    迭代投影：在 [1,total] 与「相邻间隔 >= min_gap」两组约束下，
    寻找最接近原始百分比的解。交替正向/反向投影直至收敛。

    fixed：强制锚点的索引集合。固定点不被推动，改为反向拉动其相邻锚点，
           以保证用户指定的 forced_anchors 优先于自动推算结果。
    """
    fixed = set(fixed or ())
    n = len(order)
    fl = floor or [1] * n
    a = [base[o] for o in order]
    for _ in range(50):
        changed = False
        for i in range(n):
            v = max(fl[i], min(total_episodes, a[i]))
            if v != a[i]:
                a[i] = v
                changed = True
        for i in range(1, n):
            need = a[i - 1] + min_gap
            if a[i] < need:
                if i in fixed:
                    nv = max(fl[i - 1], a[i] - min_gap)
                    if a[i - 1] != nv:
                        a[i - 1] = nv
                        changed = True
                else:
                    a[i] = max(fl[i], need)
                    changed = True
        for i in range(n - 2, -1, -1):
            limit = a[i + 1] - min_gap
            if a[i] > limit:
                if i in fixed:
                    nv = min(total_episodes, max(fl[i + 1], a[i] + min_gap))
                    if a[i + 1] != nv:
                        a[i + 1] = nv
                        changed = True
                else:
                    a[i] = max(fl[i], limit)
                    changed = True
        if not changed:
            break
    return {o: a[i] for i, o in enumerate(order)}


def _feasible(a: Dict[str, int], order: List[str], total_episodes: int, min_gap: int) -> bool:
    vals = [a[o] for o in order]
    if any(not (1 <= v <= total_episodes) for v in vals):
        return False
    return all(vals[i] - vals[i - 1] >= min_gap for i in range(1, len(vals)))


# ============================================================================
# 4. anchor_normalizer —— 取整 / 钳位 / 单调
# ============================================================================

def _round_half_up(x: float) -> int:
    """四舍五入，.5 向上取整。"""
    return int(math.floor(x + 0.5))


def resolve_min_gap(total_episodes: int, n_anchors: int) -> int:
    """
    相邻锚点的最小间隔。短集数若不约束，多个锚点会挤在同一集。
    自适应降级：当集数不足以容纳时，逐步缩小间隔，最低为 1。
    """
    if n_anchors <= 1:
        return 1
    desired = max(2, int(round(total_episodes / 30.0)))
    feasible = (total_episodes - 1) // (n_anchors - 1)
    return max(1, min(desired, feasible))


def normalize_anchors(
    raw: Dict[str, float],
    order: List[str],
    total_episodes: int,
    fixed_names: Optional[List[str]] = None,
) -> List[str]:
    """
    取整 -> 钳位 -> 最小间隔约束（迭代投影）。
    若较大间隔不可行，自动降级间隔直至可行，保证一定产出合法结果。
    返回警告列表。
    """
    warnings: List[str] = []
    n = len(order)

    base = {
        o: max(1, min(total_episodes, _round_half_up(raw[o]))) for o in order
    }
    # 首次反击不得落在第 1 集：第 1 集须为建置集
    if total_episodes >= 4:
        base[order[0]] = max(base[order[0]], 2)

    if n == 1:
        raw[order[0]] = float(base[order[0]])
        return warnings

    desired = max(2, int(round(total_episodes / 30.0)))
    feasible_max = (total_episodes - 1) // (n - 1)

    fixed_idx = {i for i, o in enumerate(order) if o in set(fixed_names or ())}
    # 首位锚点（首次反击）下界为 2：第 1 集须为建置集
    floor = [1] * len(order)
    if total_episodes >= 4:
        floor[0] = 2

    chosen_gap, chosen = 1, _project_monotone(
        base, order, total_episodes, 1, fixed_idx, floor
    )
    for gap in range(max(1, min(desired, feasible_max)), 0, -1):
        cand = _project_monotone(base, order, total_episodes, gap, fixed_idx, floor)
        if _feasible(cand, order, total_episodes, gap):
            chosen_gap, chosen = gap, cand
            break

    if not _feasible(chosen, order, total_episodes, chosen_gap) and fixed_idx:
        conflict = ", ".join(f"{order[i]}={int(base[order[i]])}" for i in sorted(fixed_idx))
        raise BlueprintError(
            f"forced_anchors 无法满足最小间隔约束（{conflict}），"
            f"在 {total_episodes} 集内无解，请调整指定集数"
        )

    for o in order:
        if chosen[o] != base[o]:
            warnings.append(
                f"锚点 {o} 由 {base[o]} 调整为 {chosen[o]}（最小间隔 {chosen_gap} 集约束）"
            )
    for o in order:
        raw[o] = float(chosen[o])
    return warnings


# ============================================================================
# 5. forced_applier —— 强制锚点覆盖
# ============================================================================

def apply_forced_anchors(
    raw: Dict[str, float],
    order: List[str],
    total_episodes: int,
    forced: Optional[Dict[str, int]],
) -> List[str]:
    """覆盖指定锚点，然后重跑单调性修正。"""
    if not forced:
        return []

    unknown = [k for k in forced if k not in order]
    if unknown:
        raise BlueprintError(
            f"forced_anchors 含未知锚点: {unknown}，合法值: {order}"
        )

    out_of_range = {
        k: v for k, v in forced.items() if not (1 <= v <= total_episodes)
    }
    if out_of_range:
        raise BlueprintError(f"forced_anchors 超出 [1,{total_episodes}] 范围: {out_of_range}")

    for k, v in forced.items():
        raw[k] = float(v)

    warnings = normalize_anchors(raw, order, total_episodes, fixed_names=list(forced.keys()))

    for k, v in forced.items():
        actual = int(raw[k])
        if actual != v:
            warnings.append(
                f"forced_anchors 冲突：{k} 指定 {v}，因最小间隔约束最终为 {actual}"
            )
        else:
            warnings.append(f"forced_anchors 已生效：{k}={v}")
    return warnings


# ============================================================================
# 6. segmenter —— 段落切分（三种策略）
# ============================================================================

def _cut_blocks(boundaries: List[int], total_episodes: int) -> List[Tuple[int, int]]:
    """切点列表 -> 区块 [(start, end)]，闭区间。"""
    blocks = []
    pts = sorted(set([1] + boundaries + [total_episodes + 1]))
    for i in range(len(pts) - 1):
        s, e = pts[i], pts[i + 1] - 1
        if s <= e:
            blocks.append((s, e))
    return blocks


def _allocate_quotas(blocks: List[Tuple[int, int]], n_cuts: int) -> List[int]:
    """
    按区块长度比例分配内部切点配额（最大余数法）。
    返回与 blocks 等长的配额列表。
    """
    if n_cuts <= 0:
        return [0] * len(blocks)

    total_len = sum(e - s + 1 for s, e in blocks)
    if total_len <= 0:
        return [0] * len(blocks)

    exact = [(e - s + 1) * n_cuts / total_len for s, e in blocks]
    quotas = [int(math.floor(x)) for x in exact]
    remainder = n_cuts - sum(quotas)

    # 余数按小数部分降序分配
    fracs = sorted(
        range(len(blocks)),
        key=lambda i: (exact[i] - quotas[i], -(blocks[i][1] - blocks[i][0] + 1)),
        reverse=True,
    )
    for i in fracs[:remainder]:
        quotas[i] += 1

    # 配额不得超过区块可容纳上限
    for i, (s, e) in enumerate(blocks):
        quotas[i] = min(quotas[i], max(0, e - s))
    return quotas


def _snap_to_anchor(v: int, anchor_values: List[int], tolerance: int = 2) -> int:
    """若 v 距离某锚点在容差内，吸附到该锚点。"""
    best, best_dist = v, tolerance + 1
    for a in anchor_values:
        d = abs(a - v)
        if d <= tolerance and d < best_dist:
            best, best_dist = a, d
    return best


def build_segments(
    anchors: Dict[str, int],
    order: List[str],
    reveal_key: str,
    total_episodes: int,
    target_segments: int,
    strategy: str,
) -> List[Tuple[int, int]]:
    """
    返回段落边界列表 [(start, end)]。
    硬约束：safe_low_start 必须开启一段；reveal_key 必须结束一段。
    """
    # 硬切点：低谷起点开启一段；揭晓锚点结束一段（即其后一集开启新段）
    hard: List[int] = []
    sls = anchors.get("safe_low_start")
    if sls and 1 < sls <= total_episodes:
        hard.append(sls)
    rev = anchors.get(reveal_key)
    if rev and 1 <= rev < total_episodes:
        hard.append(rev + 1)
    hard = sorted(set(hard))

    if strategy == "anchor_locked":
        return _cut_blocks(hard, total_episodes)

    # balanced / hybrid：保留硬切点，按段数配额在区块内细分
    blocks = _cut_blocks(hard, total_episodes)
    n_internal = target_segments - 1 - len(hard)
    quotas = _allocate_quotas(blocks, max(0, n_internal))

    cuts: List[int] = []
    for (s, e), q in zip(blocks, quotas):
        if q <= 0:
            continue
        length = e - s + 1
        step = length / (q + 1)
        for j in range(1, q + 1):
            cuts.append(int(round(s + step * j)))

    all_cuts = sorted(set(hard + cuts))
    # 去重并剔除越界
    all_cuts = [c for c in all_cuts if 1 < c <= total_episodes]

    if strategy == "balanced":
        # 吸附：让非硬切点靠近锚点。硬切点绝不动，否则会破坏
        # 「低谷开启一段 / 揭晓结束一段」的硬约束。
        anchor_values = [anchors[o] for o in order]
        snapped: List[int] = []
        for c in all_cuts:
            if c in hard:
                snapped.append(c)
                continue
            v = _snap_to_anchor(c, anchor_values)
            if v in hard or v <= 1 or v > total_episodes:
                v = c
            snapped.append(v)
        all_cuts = sorted(set(snapped))
        all_cuts = [c for c in all_cuts if 1 < c <= total_episodes]

    segs = _cut_blocks(all_cuts, total_episodes)

    # 段数超目标时合并最短相邻段，直至达标
    while len(segs) > target_segments and len(segs) > 1:
        idx = min(
            range(len(segs) - 1),
            key=lambda i: (segs[i][1] - segs[i][0] + 1) + (segs[i + 1][1] - segs[i + 1][0] + 1),
        )
        merged = (segs[idx][0], segs[idx + 1][1])
        segs = segs[:idx] + [merged] + segs[idx + 2 :]

    return segs


# ============================================================================
# 7. density_resolver —— 密度参数
# ============================================================================

def resolve_density(
    tier: str, duration_sec: Optional[int], cfg: Dict[str, Any]
) -> Tuple[Dict[str, Any], str, float]:
    """返回 (密度参数, 时长档名, 生效系数)。"""
    base = dict(cfg["density_base"][tier])

    # 时长档判定
    dur_band, factor = "medium", 1.0
    if duration_sec is not None:
        for band, rule in cfg["duration_modifier"].items():
            if band.startswith("_"):
                continue
            max_sec = rule["max_sec"]
            if max_sec is None or duration_sec <= max_sec:
                dur_band, factor = band, rule["payoff_factor"]
                break

    lo, hi = base["payoff_interval"]
    new_lo = max(1, math.ceil(lo * factor - 1e-9))
    new_hi = max(new_lo, math.ceil(hi * factor - 1e-9))
    base["payoff_interval"] = [new_lo, new_hi]

    return base, dur_band, factor


def format_density(density: Dict[str, Any]) -> Dict[str, Any]:
    """输出友好的密度描述。"""
    lo, hi = density["payoff_interval"]
    interval = f"每{lo}集" if lo == hi else f"每{lo}~{hi}集"
    rlo, rhi = density["pattern_refresh_interval"]
    slo, shi = density["reveal_steps"]
    vlo, vhi = density["total_reversals"]
    return {
        "payoff_interval": interval,
        "max_open_debts": density["max_open_debts"],
        "pattern_refresh_interval": f"每{rlo}~{rhi}集",
        "reveal_steps": f"{slo}~{shi}次",
        "total_reversals": f"{vlo}~{vhi}次",
    }


# ============================================================================
# 8. validator —— 两级校验
# ============================================================================

def validate(
    anchors: Dict[str, int],
    order: List[str],
    reveal_key: str,
    segments: List[Tuple[int, int]],
    total_episodes: int,
    tier: str,
    density: Dict[str, Any],
    confidence: Optional[str],
) -> Tuple[List[str], List[str]]:
    """返回 (errors, warnings)。"""
    errors: List[str] = []
    warnings: List[str] = []

    # --- 段落：覆盖 / 相接 / 无重叠 ---
    if not segments:
        errors.append("段落切分为空")
    else:
        if segments[0][0] != 1:
            errors.append(f"首段起点为 {segments[0][0]}，必须为 1")
        if segments[-1][1] != total_episodes:
            errors.append(f"末段终点为 {segments[-1][1]}，必须为 {total_episodes}")
        for i in range(len(segments) - 1):
            if segments[i][1] + 1 != segments[i + 1][0]:
                errors.append(
                    f"段落不连续: 段{i+1} 止于 {segments[i][1]}，段{i+2} 起于 {segments[i+1][0]}"
                )
            if segments[i][1] >= segments[i + 1][0]:
                errors.append(f"段落重叠: 段{i+1} 与 段{i+2}")

    # --- 锚点：在界内 / 单调递增 ---
    for name in order:
        v = anchors[name]
        if not (1 <= v <= total_episodes):
            errors.append(f"锚点 {name}={v} 超出 [1,{total_episodes}]")
    for i in range(1, len(order)):
        if anchors[order[i]] <= anchors[order[i - 1]]:
            errors.append(
                f"锚点未单调递增: {order[i-1]}={anchors[order[i-1]]} >= {order[i]}={anchors[order[i]]}"
            )

    # --- 硬约束：低谷开启一段 / 揭晓结束一段 ---
    sls = anchors.get("safe_low_start")
    if sls and not any(s == sls for s, _ in segments):
        errors.append(f"安全低谷起点 {sls} 未开启任何段落")
    rev = anchors.get(reveal_key)
    if rev and not any(e == rev for _, e in segments):
        errors.append(f"核心揭晓锚点 {reveal_key}={rev} 未结束任何段落")

    # --- reveal_steps 不得超过可用集数跨度 ---
    max_steps = density["reveal_steps"][1]
    if max_steps > total_episodes:
        errors.append(f"reveal_steps 上限 {max_steps} 超过总集数 {total_episodes}")

    # --- mini 档专项红线 ---
    if tier == "mini":
        if anchors["first_counterattack"] <= 1:
            errors.append("mini 档首次反击不得落在第 1 集（第1集须为建置集）")
        span = total_episodes - anchors["finale"] + 1
        min_span = max(1, min(2, total_episodes // 6))
        if span < min_span:
            errors.append(f"mini 档终局区间仅 {span} 集，不得少于 {min_span} 集")

    # --- 警告 ---
    lengths = [e - s + 1 for s, e in segments]
    if lengths:
        mean = sum(lengths) / len(lengths)
        std = math.sqrt(sum((x - mean) ** 2 for x in lengths) / len(lengths))
        cv = std / mean if mean else 0.0
        if cv > 0.50:
            warnings.append(f"段落长度不均衡（变异系数 {cv:.2f}，长度 {lengths}）")
        elif cv > 0.30:
            warnings.append(f"段落长度较不均衡（变异系数 {cv:.2f}，长度 {lengths}）")

    if confidence == "low":
        warnings.append("上游 arc_type/mechanism 置信度为 low，需人工确认")

    # 锚点间隔过密
    min_gap = resolve_min_gap(total_episodes, len(order))
    for i in range(1, len(order)):
        gap = anchors[order[i]] - anchors[order[i - 1]]
        if gap < min_gap:
            warnings.append(
                f"锚点 {order[i-1]} 与 {order[i]} 间隔 {gap} 集，低于最小间隔 {min_gap} 集"
            )

    return errors, warnings


# ============================================================================
# 9. 主流程
# ============================================================================

def build_blueprint(
    total_episodes: int,
    arc_type: str,
    mechanism: Optional[str] = None,
    genre: Optional[str] = None,
    duration_sec: Optional[int] = None,
    forced_anchors: Optional[Dict[str, int]] = None,
    segment_strategy: str = "balanced",
    confidence: Optional[str] = None,
    slug: Optional[str] = None,
    title: Optional[str] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    构建剧集蓝图。致命校验不通过时抛 BlueprintError，不返回半成品。
    """
    if cfg is None:
        cfg = load_config()

    if not isinstance(total_episodes, int) or total_episodes < 1:
        raise BlueprintError(f"total_episodes 必须为正整数，收到: {total_episodes}")
    if total_episodes < 6:
        raise BlueprintError(
            f"总集数 {total_episodes} 过少，蓝图至少需要 6 集才能容纳核心锚点、低谷与终局"
        )
    if arc_type not in arc_types(cfg):
        raise BlueprintError(
            f"未知 arc_type: {arc_type}，合法值: {arc_types(cfg)}"
        )
    if segment_strategy not in ("anchor_locked", "balanced", "hybrid"):
        raise BlueprintError(
            f"未知 segment_strategy: {segment_strategy}，合法值: anchor_locked/balanced/hybrid"
        )
    mech_keys = [k for k in cfg["mechanism_reveal_mode"].keys() if not k.startswith("_")]
    if mechanism is not None and mechanism not in mech_keys:
        raise BlueprintError(
            f"未知 mechanism: {mechanism}，合法值: {mech_keys}"
        )

    # Step 1 · 档位
    tier, target_segments = resolve_tier(total_episodes, cfg)

    # Step 2~3 · 弧型修正 + 锚点换算
    order, reveal_key = resolve_anchor_order(arc_type, tier, total_episodes, cfg)
    raw, mods, skipped = calculate_anchors(
        total_episodes, tier, arc_type, mechanism, cfg
    )

    # Step 4 · 取整 / 钳位 / 单调
    norm_warnings = normalize_anchors(raw, order, total_episodes)

    # Step 5 · forced 覆盖
    forced_warnings = apply_forced_anchors(raw, order, total_episodes, forced_anchors)

    anchors = {k: int(raw[k]) for k in order}

    # Step 4(续) · mechanism -> reveal_mode
    reveal_mode = cfg["mechanism_reveal_mode"].get(mechanism or "none", "default")
    if reveal_mode == "default":
        reveal_mode = "single" if reveal_key == "reveal" else "multi"

    # Step 6 · 密度
    density, dur_band, dur_factor = resolve_density(tier, duration_sec, cfg)

    # Step 7 · 段落切分
    segments = build_segments(
        anchors, order, reveal_key, total_episodes, target_segments, segment_strategy
    )
    lengths = [e - s + 1 for s, e in segments]
    mean = sum(lengths) / len(lengths) if lengths else 0.0
    std = (
        math.sqrt(sum((x - mean) ** 2 for x in lengths) / len(lengths))
        if lengths
        else 0.0
    )
    cv = std / mean if mean else 0.0
    thr = cfg["balance_thresholds"]
    balance_score = (
        "均衡" if cv <= thr["good"] else "较均衡" if cv <= thr["fair"] else "不均衡"
    )

    # Step 8 · 校验
    errors, warnings = validate(
        anchors, order, reveal_key, segments, total_episodes,
        tier, density, confidence,
    )
    warnings = norm_warnings + forced_warnings + skipped + warnings

    if errors:
        raise BlueprintError("致命校验未通过:\n  - " + "\n  - ".join(errors))

    return {
        "meta": {
            "slug": slug,
            "title": title,
            "genre": genre,
            "mechanism": mechanism,
            "arc_type": arc_type,
            "confidence": confidence,
            "needs_human_confirm": confidence == "low",
            "config_version": cfg["version"],
            "generated_by": "program",
        },
        "inputs": {
            "total_episodes": total_episodes,
            "duration_sec_per_ep": duration_sec,
        },
        "tier": tier,
        "segment_count": len(segments),
        "segments_boundary": [f"{s}-{e}" for s, e in segments],
        "segment_stats": {
            "lengths": lengths,
            "std_dev": round(std, 2),
            "coef_var": round(cv, 3),
            "balance_score": balance_score,
        },
        "anchors": anchors,
        "reveal_key": reveal_key,
        "reveal_mode": reveal_mode,
        "density": format_density(density),
        "density_raw": density,
        "applied_modifiers": {
            "arc_type": arc_type,
            "arc_modifier": mods,
            "duration_band": dur_band,
            "duration_payoff_factor": dur_factor,
            "reveal_mode": reveal_mode,
            "forced_anchors": forced_anchors or {},
            "segment_strategy": segment_strategy,
        },
        "validation": {
            "passed": True,
            "errors": [],
            "warnings": warnings,
        },
    }


def build_from_bible(
    bible: Dict[str, Any],
    forced_anchors: Optional[Dict[str, int]] = None,
    segment_strategy: str = "balanced",
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """从 01_bible.json 直接构建。"""
    d = bible.get("derivation", {}) or {}
    return build_blueprint(
        total_episodes=bible["target_episodes"],
        arc_type=bible["arc_type"],
        mechanism=bible.get("mechanism"),
        genre=bible.get("genre"),
        duration_sec=bible.get("duration_sec_per_ep"),
        forced_anchors=forced_anchors,
        segment_strategy=segment_strategy,
        confidence=d.get("confidence"),
        slug=bible.get("slug"),
        title=bible.get("title"),
        cfg=cfg,
    )


# ============================================================================
# 10. 导出：JSON + 提示词注入摘要
# ============================================================================

ANCHOR_CN = {
    "first_counterattack": "首次反击",
    "first_suspicion": "起疑/扰动",
    "safe_low_start": "低谷起点",
    "reveal": "真相揭晓",
    "detonation_point": "危机引爆",
    "upgrade_point": "阶段升级",
    "ultimate_antagonist": "终极反派",
    "finale": "终局",
}


def to_prompt_block(bp: Dict[str, Any] | None) -> str:
    """生成注入大模型提示词的紧凑摘要（避免占用过多上下文）。"""
    if not bp or not isinstance(bp, dict):
        return ""
    try:
        a = bp.get("anchors") or {}
        anchor_txt = " | ".join(
            f"{ANCHOR_CN.get(k, k)} {v}" for k, v in a.items()
        )
        d = bp.get("density") or {}
        inputs = bp.get("inputs") or {}
        tot_eps = inputs.get("total_episodes") or bp.get("total_episodes", "")
        tier = bp.get("tier", "")
        seg_cnt = bp.get("segment_count", "")
        seg_bounds = bp.get("segments_boundary") or []
        reveal_mode = bp.get("reveal_mode", "")
        reveal_key = bp.get("reveal_key", "")
        payoff_int = d.get("payoff_interval", "")
        max_debts = d.get("max_open_debts", "")
        refresh_int = d.get("pattern_refresh_interval", "")
        reveal_steps = d.get("reveal_steps", "")

        return (
            f"【剧集蓝图】共 {tot_eps} 集 | "
            f"档位 {tier} | {seg_cnt} 段\n"
            f"段落：{' / '.join(seg_bounds)}\n"
            f"锚点：{anchor_txt}\n"
            f"揭晓模式：{reveal_mode}（核心锚点 {reveal_key}）\n"
            f"密度：打脸{payoff_int} | 待还债≤{max_debts}笔 | "
            f"换血{refresh_int} | 揭晓阶梯{reveal_steps}\n"
            f"【约束】所有集数决策必须引用上述锚点与段落边界，不得另立集数。"
        )
    except Exception:
        return ""


# ============================================================================
# CLI
# ============================================================================

def _scan(cfg: Dict[str, Any]) -> int:
    """全量回归扫描：1~200 集 × 各弧型 × 各策略。"""
    fails = 0
    checked = 0
    for ep in range(1, 201):
        for arc in arc_types(cfg):
            for strat in ("anchor_locked", "balanced", "hybrid"):
                checked += 1
                try:
                    bp = build_blueprint(
                        total_episodes=ep,
                        arc_type=arc,
                        duration_sec=120,
                        segment_strategy=strat,
                        cfg=cfg,
                    )
                    if not bp["validation"]["passed"]:
                        fails += 1
                        print(f"[FAIL] ep={ep} arc={arc} strat={strat}")
                except BlueprintError as e:
                    fails += 1
                    if fails <= 20:
                        print(f"[ERR ] ep={ep} arc={arc} strat={strat}: {str(e).splitlines()[0]}")
    print(f"\n扫描完成: 共 {checked} 组，失败 {fails} 组")
    return fails


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="剧集蓝图生成器")
    p.add_argument("--bible", help="01_bible.json 路径")
    p.add_argument("--episodes", type=int, help="总集数")
    p.add_argument("--arc", default="reveal", help="弧型 arc_type")
    p.add_argument("--mechanism", help="信息差机制")
    p.add_argument("--genre", help="题材/世界外壳")
    p.add_argument("--duration", type=int, help="单集秒数")
    p.add_argument("--force", help="强制锚点，如 reveal=9,reveal=8 或 reveal=9")
    p.add_argument("--strategy", default="balanced",
                   choices=["anchor_locked", "balanced", "hybrid"])
    p.add_argument("--out", help="输出路径 02_blueprint.json")
    p.add_argument("--dry-run", action="store_true", help="只校验不落盘")
    p.add_argument("--prompt", action="store_true", help="额外打印提示词注入摘要")
    p.add_argument("--scan", action="store_true", help="全量回归扫描 1~200 集")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = p.parse_args(argv)

    cfg = load_config(args.config)

    if args.scan:
        return 1 if _scan(cfg) else 0

    forced = None
    if args.force:
        forced = {}
        for item in args.force.split(","):
            k, v = item.split("=")
            forced[k.strip()] = int(v.strip())

    try:
        if args.bible:
            with open(args.bible, "r", encoding="utf-8") as f:
                bible = json.load(f)
            bp = build_from_bible(bible, forced, args.strategy, cfg)
        elif args.episodes:
            bp = build_blueprint(
                total_episodes=args.episodes,
                arc_type=args.arc,
                mechanism=args.mechanism,
                genre=args.genre,
                duration_sec=args.duration,
                forced_anchors=forced,
                segment_strategy=args.strategy,
                cfg=cfg,
            )
        else:
            p.error("需指定 --bible 或 --episodes（或用 --scan）")
            return 2
    except BlueprintError as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 1

    for w in bp["validation"]["warnings"]:
        print(f"[WARN ] {w}", file=sys.stderr)

    if args.prompt:
        print(to_prompt_block(bp))

    if not args.dry_run:
        out = args.out or "02_blueprint.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(bp, f, ensure_ascii=False, indent=2)
        print(f"[OK   ] 已输出 {out}", file=sys.stderr)
    else:
        print(json.dumps(bp, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
