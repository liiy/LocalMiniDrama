"""阶段 6 空间场景与气候做旧层增量对齐组件 (Stage 6 Scene & Weathering Persister)。

对齐并持久化场景全景空间 (scenes)、子空间划分 (scene_zones) 以及动态气候与做旧切片 (scene_weathering_views)。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.type_utils import safe_int
from app.core.logger import get_logger
from app.workflows.adapters.stage_adapters.common import (
    _dump_or_dict,
    _safe_json_loads,
    fetch_all,
    fetch_one,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

log = get_logger("lmd.storage_adapter.stage6.scene")


def persist_stage6_scenes(
    db: Session,
    drama_id: int,
    curr_ep: int,
    episode_id: int | None,
    now: str,
    environments_manifest: list[dict[str, Any]],
    newly_discovered_scenes: list[dict[str, Any]],
    newly_generated_assets: list[dict[str, Any]],
    state: Any,
) -> None:
    """增量对齐并原子落库空间场景与气候做旧层。"""
    # 合并新发现场景项与新生成资产中的场景项
    for new_scene in newly_discovered_scenes:
        ns_dict = _dump_or_dict(new_scene)
        if isinstance(ns_dict, dict) and ns_dict not in environments_manifest:
            environments_manifest.append(ns_dict)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or "")
        if (cat in ("environment", "scene") or aid.startswith("ENV_")) and n_dict not in environments_manifest:
            environments_manifest.append(n_dict)

    # 【幂等防重保障·场景清单按业务主键去重收敛】
    # 避免上游多数据源导致同一场景以略有差异的字典重复加入 environments_manifest，引发单次落库中对同一场景的重复执行
    deduped_environments_manifest: list[dict[str, Any]] = []
    seen_env_keys: set[str] = set()
    for raw_env in environments_manifest:
        env_dict = _dump_or_dict(raw_env)
        if not isinstance(env_dict, dict):
            continue
        env_loc = str(env_dict.get("scene_name") or env_dict.get("location") or env_dict.get("location_name") or "").strip()
        env_code = str(env_dict.get("scene_code") or env_dict.get("code") or "").strip()
        env_ident = env_code if env_code else (AssetProtocolHelper.normalize_token(env_loc) if env_loc else "")
        if not env_ident and not env_loc:
            continue
        dedup_key = f"{env_ident}::{env_loc}"
        if dedup_key in seen_env_keys:
            log.debug("【阶段 6 落库】[场景去重过滤] 忽略重复的场景定义: %s", dedup_key)
            continue
        seen_env_keys.add(dedup_key)
        deduped_environments_manifest.append(env_dict)

    log.debug(
        "【阶段 6 落库】[场景清单前置收敛] 原始清单数=%d, 排重后有效场景数=%d",
        len(environments_manifest), len(deduped_environments_manifest)
    )

    for env in deduped_environments_manifest:
        loc = str(env.get("scene_name") or env.get("location") or env.get("location_name") or "").strip()
        if not loc:
            continue

        raw_s_code = str(env.get("scene_code") or env.get("code") or "").strip()
        s_code = raw_s_code if raw_s_code else AssetProtocolHelper.normalize_token(loc)
        bench_scene_key = env.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_scene(s_code)
        time_lighting = str(env.get("time_lighting") or env.get("time_and_lighting") or "").strip()
        acoustic_resistance = str(env.get("acoustic_resistance") or "").strip()

        existing_scene = fetch_one(
            db,
            "SELECT id FROM scenes WHERE drama_id = :drama_id AND (scene_code = :s_code OR location = :loc)",
            {"drama_id": drama_id, "s_code": s_code, "loc": loc},
        )
        if existing_scene:
            scene_id = existing_scene["id"]
            db.execute(
                text("""
                    UPDATE scenes
                    SET scene_code = CASE WHEN (scene_code IS NULL OR scene_code = '') AND :s_code != '' THEN :s_code ELSE scene_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        time = CASE WHEN :time != '' THEN :time ELSE time END,
                        prompt = CASE WHEN :prompt != '' THEN :prompt ELSE prompt END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": scene_id,
                    "s_code": s_code,
                    "bench_key": bench_scene_key,
                    "time": time_lighting,
                    "prompt": env.get("visual_prompt") or env.get("prompt") or "",
                    "now": now,
                },
            )
        else:
            scene_ins = db.execute(
                text("""
                    INSERT INTO scenes (
                        drama_id, episode_id, scene_code, benchmark_asset_key, location, time, prompt,
                        status, created_at, updated_at
                    ) VALUES (
                        :drama_id, :episode_id, :scene_code, :benchmark_asset_key, :location, :time, :prompt,
                        'draft', :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "episode_id": episode_id,
                    "scene_code": s_code,
                    "benchmark_asset_key": bench_scene_key,
                    "location": loc,
                    "time": time_lighting,
                    "prompt": env.get("visual_prompt") or "",
                    "now": now,
                },
            )
            scene_id = safe_int(getattr(scene_ins, "lastrowid", None), default=1)
            log.info(
                "【阶段 6 落库】[步骤 4/6 场景] 登记第 %s 集新场景: scene_id=%s, 代号=%s, 地点=%s, 基准键=%s",
                curr_ep, scene_id, s_code, loc, bench_scene_key,
            )

        # 4.1 动态提取与规范化场景子空间区域 (Tier 2 scene_zones)
        zones_data: list[dict[str, Any]] = []
        raw_zones = env.get("zones") or env.get("sub_zones")
        if isinstance(raw_zones, list) and raw_zones:
            for z_idx, z_val in enumerate(raw_zones, start=1):
                if isinstance(z_val, dict):
                    z_code = str(z_val.get("zone_code") or (f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}")).strip().upper()
                    z_name = str(z_val.get("zone_name") or z_val.get("name") or f"{loc}子区域{z_idx}").strip()
                    z_tl = str(z_val.get("time_lighting") or time_lighting).strip()
                    z_ar = str(z_val.get("acoustic_resistance") or acoustic_resistance).strip()
                    zones_data.append({
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                    })
                elif isinstance(z_val, str) and z_val.strip():
                    z_name = z_val.strip()
                    z_code = f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}"
                    zones_data.append({
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": time_lighting,
                        "acoustic_resistance": acoustic_resistance,
                    })
        elif isinstance(raw_zones, dict):
            for z_idx, (z_k, z_v) in enumerate(raw_zones.items(), start=1):
                z_name = str(z_k).strip()
                z_code = f"Z0{z_idx}" if z_idx < 10 else f"Z{z_idx}"
                zones_data.append({
                    "zone_code": z_code,
                    "zone_name": z_name,
                    "time_lighting": str(z_v).strip() if isinstance(z_v, str) else time_lighting,
                    "acoustic_resistance": acoustic_resistance,
                })

        # 若未提供显式子区域列表，优先提取 zone_name，兜底保持向后兼容（杜绝无条件写死）
        if not zones_data:
            dyn_z_name = str(env.get("zone_name") or "核心主活动区").strip()
            dyn_z_code = str(env.get("zone_code") or "Z01").strip().upper()
            zones_data.append({
                "zone_code": dyn_z_code,
                "zone_name": dyn_z_name,
                "time_lighting": time_lighting,
                "acoustic_resistance": acoustic_resistance,
            })

        primary_zone_id: Optional[int] = None
        for z_entry in zones_data:
            z_code = z_entry["zone_code"]
            z_name = z_entry["zone_name"]
            z_tl = z_entry["time_lighting"]
            z_ar = z_entry["acoustic_resistance"]

            existing_zone = fetch_one(
                db,
                "SELECT id, zone_code FROM scene_zones WHERE scene_id = :scene_id AND (zone_code = :z_code OR zone_name = :z_name)",
                {"scene_id": scene_id, "z_code": z_code, "z_name": z_name},
            )
            if existing_zone:
                zone_id = existing_zone["id"]
                db.execute(
                    text("""
                        UPDATE scene_zones
                        SET zone_code = CASE WHEN (zone_code IS NULL OR zone_code = '') AND :z_code != '' THEN :z_code ELSE zone_code END,
                            zone_name = CASE WHEN (zone_name IS NULL OR zone_name = '') AND :z_name != '' THEN :z_name ELSE zone_name END,
                            time_lighting = CASE WHEN :time_lighting != '' THEN :time_lighting ELSE time_lighting END,
                            acoustic_resistance = CASE WHEN :acoustic_resistance != '' THEN :acoustic_resistance ELSE acoustic_resistance END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": zone_id,
                        "z_code": z_code,
                        "z_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                        "now": now,
                    },
                )
            else:
                z_ins = db.execute(
                    text("""
                        INSERT INTO scene_zones (
                            scene_id, drama_id, zone_code, zone_name, time_lighting,
                            acoustic_resistance, created_at, updated_at
                        ) VALUES (
                            :scene_id, :drama_id, :zone_code, :zone_name, :time_lighting,
                            :acoustic_resistance, :now, :now
                        )
                    """),
                    {
                        "scene_id": scene_id,
                        "drama_id": drama_id,
                        "zone_code": z_code,
                        "zone_name": z_name,
                        "time_lighting": z_tl,
                        "acoustic_resistance": z_ar,
                        "now": now,
                    },
                )
                zone_id = safe_int(getattr(z_ins, "lastrowid", None), default=1)
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景子区域] 登记第 %s 集空间子区域: zone_id=%s, scene_id=%s, 代号=%s, 名称=%s",
                    curr_ep, zone_id, scene_id, z_code, z_name,
                )

            if primary_zone_id is None:
                primary_zone_id = zone_id

        target_zone_id = primary_zone_id or 1

        # ---------------------------------------------------------------------
        # 4.2 写入本集气候做旧图层 (Tier 3: scene_weathering_views)
        # ---------------------------------------------------------------------
        # 【架构设计说明·状态切片独立寻址与幂等槽位对齐】
        # 为彻底杜绝大模型重跑文字随机性导致的无休止追加插入（Append）与键碰撞：
        # 1. 优先提取上游阶段 3/6 规范化构建的结构化切片列表 `weathering_views`；
        # 2. 兜底兼容字典形式 `weathering_layers` 与列表形式 `weathering_applied`；
        # 3. 构造确定性切片槽位 asset_key：{bench_scene_key}_W{curr_ep}_S{idx}；
        # 4. 基于 (scene_zone_id, 本集切片模式) 执行槽位级精确对齐 (Slot Alignment)：
        #    - 匹配已存在的槽位进行原位更新 (UPDATE)；
        #    - 若本集切片数增加，执行新增插入 (INSERT)；
        #    - 若本集切片数收敛变少，自动清理多余的历史旧槽位 (DELETE)；
        #    - 从而保证多次重跑时记录数恒定，绝不膨胀。
        # ---------------------------------------------------------------------
        weathering_entries: list[dict[str, Any]] = []

        # 优先从结构化 weathering_views 中提取三层切片
        raw_views = env.get("weathering_views")
        if isinstance(raw_views, list) and raw_views:
            for v_idx, v_item in enumerate(raw_views, start=1):
                if isinstance(v_item, dict):
                    weathering_entries.append(v_item)
                elif isinstance(v_item, str) and v_item.strip():
                    weathering_entries.append({
                        "layer_type": f"weathering_s{v_idx}",
                        "description": v_item.strip(),
                    })
        else:
            # 兼容读取 weathering_applied 与 weathering_layers
            weathering_source = env.get("weathering_applied") or env.get("weathering_layers") or []
            if isinstance(weathering_source, dict):
                for k, v in weathering_source.items():
                    weathering_entries.append({
                        "layer_type": str(k).strip(),
                        "description": str(v).strip(),
                    })
            elif isinstance(weathering_source, list):
                for v_idx, item in enumerate(weathering_source, start=1):
                    if isinstance(item, dict):
                        weathering_entries.append(item)
                    elif isinstance(item, str) and item.strip():
                        weathering_entries.append({
                            "layer_type": f"weathering_s{v_idx}",
                            "description": item.strip(),
                        })
            elif isinstance(weathering_source, str) and weathering_source.strip():
                weathering_entries.append({
                    "layer_type": "weathering_s1",
                    "description": weathering_source.strip(),
                })

        # 过滤掉无有效描述的空项
        valid_entries: list[dict[str, Any]] = [
            e for e in weathering_entries
            if str(e.get("description") or e.get("desc") or "").strip()
        ]

        log.debug(
            "【阶段 6 落库】[DEBUG 场景做旧切片] 场景 [%s] (ID=%s, ZoneID=%s) 待落库做旧图层数: %d",
            loc, scene_id, target_zone_id, len(valid_entries)
        )

        # 4.2.1 查询当前主区域下属于本集的已有存量做旧切片 (按 id 升序)
        # 本集切片特征：asset_key 形如 '%_W{curr_ep}' 或 '%_W{curr_ep}_%'，或 layer_type 指向本集
        ep_key_pattern = f"%_W{curr_ep}"
        ep_key_sub_pattern = f"%_W{curr_ep}_%"
        existing_ep_views = fetch_all(
            db,
            """
            SELECT id, asset_key, layer_type, description
            FROM scene_weathering_views
            WHERE scene_zone_id = :z_id
              AND (
                  asset_key LIKE :p1
                  OR asset_key LIKE :p2
                  OR layer_type LIKE :p_layer
              )
            ORDER BY id ASC
            """,
            {
                "z_id": target_zone_id,
                "p1": ep_key_pattern,
                "p2": ep_key_sub_pattern,
                "p_layer": f"%ep_{curr_ep}%",
            },
        )
        existing_view_count = len(existing_ep_views)
        target_view_count = len(valid_entries)

        log.debug(
            "【阶段 6 落库】[场景做旧槽位对齐] zone_id=%s, 第 %s 集已存切片数=%d, 本次待同步切片数=%d",
            target_zone_id, curr_ep, existing_view_count, target_view_count
        )

        # 4.2.2 逐个槽位对齐与写入
        for s_idx, w_entry in enumerate(valid_entries, start=1):
            w_desc = str(w_entry.get("description") or w_entry.get("desc") or "").strip()
            raw_layer_type = str(w_entry.get("layer_type") or "").strip()
            layer_type = raw_layer_type if raw_layer_type else "episode_weathering"

            # 资产切片键（asset_key）构造策略：
            # 策略 A: 优先复用上游预先构建好的合规 asset_key
            # 策略 B: 若图层类型具备特定语义（如 structural / living / optical 等），拼装 bench_scene_key + layer_tok + 分集
            # 策略 C: 若为通用状态，拼装 bench_scene_key + _W{curr_ep}_S{s_idx} 保证严格唯一
            explicit_key = str(w_entry.get("asset_key") or "").strip()
            if explicit_key:
                w_asset_key = explicit_key
            else:
                has_semantic_layer = (
                    layer_type
                    and layer_type.lower() not in ("episode_weathering", "default")
                    and not layer_type.lower().startswith("weathering_s")
                )
                if has_semantic_layer:
                    layer_tok = AssetProtocolHelper.normalize_token(layer_type)
                    w_asset_key = f"{bench_scene_key}_{layer_tok}_W{curr_ep}"
                else:
                    w_asset_key = f"{bench_scene_key}_W{curr_ep}_S{s_idx}"

            w_parent_key = str(w_entry.get("parent_asset_key") or bench_scene_key).strip()
            w_gen_mode = str(w_entry.get("generation_mode") or "i2i").strip()
            w_denoise = float(w_entry.get("denoise_strength") or 0.45)

            # 提示词合成与负向提示词
            explicit_prompt = str(w_entry.get("visual_prompt") or w_entry.get("image_prompt") or "").strip()
            if explicit_prompt:
                w_full_prompt = explicit_prompt
            else:
                w_delta_prompt, w_full_prompt = PromptSynthesizer.synthesize_scene_view_prompt(
                    env.get("visual_prompt") or loc,
                    view_type="STATE",
                    weathering_prompt=w_desc,
                    atmosphere_prompt=time_lighting,
                )
            w_neg_prompt = PromptSynthesizer.get_negative_prompt("environment")

            # 槽位匹配：优先匹配存量列表中相同序号的槽位，或者按 asset_key / description 精确匹配
            matched_view = None
            if s_idx <= existing_view_count:
                matched_view = existing_ep_views[s_idx - 1]
            else:
                # 兜底通过 asset_key 或 description 匹配未在槽位列表中的记录
                matched_view = fetch_one(
                    db,
                    """
                    SELECT id, asset_key FROM scene_weathering_views
                    WHERE scene_zone_id = :z_id
                      AND (description = :desc OR (asset_key IS NOT NULL AND asset_key != '' AND asset_key = :asset_key))
                    """,
                    {"z_id": target_zone_id, "desc": w_desc, "asset_key": w_asset_key},
                )

            if matched_view:
                # 原位更新槽位数据，覆盖描述、提示词、更新时间等，防止重跑追加
                db.execute(
                    text("""
                        UPDATE scene_weathering_views
                        SET asset_key = :asset_key,
                            parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                            layer_type = :layer_type,
                            description = :description,
                            generation_mode = :gen_mode,
                            denoise_strength = CASE WHEN (denoise_strength IS NULL OR denoise_strength = 0) THEN :denoise ELSE denoise_strength END,
                            visual_prompt = :visual_prompt,
                            negative_prompt = CASE WHEN (negative_prompt IS NULL OR negative_prompt = '') THEN :negative_prompt ELSE negative_prompt END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": matched_view["id"],
                        "asset_key": w_asset_key,
                        "parent_asset_key": w_parent_key,
                        "layer_type": layer_type,
                        "description": w_desc,
                        "gen_mode": w_gen_mode,
                        "denoise": w_denoise,
                        "visual_prompt": w_full_prompt,
                        "negative_prompt": w_neg_prompt,
                        "now": now,
                    },
                )
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景做旧] 原位更新第 %s 集场景做旧槽位: view_id=%s, zone_id=%s, 槽位序号=%d, asset_key=%s, 描述=%s",
                    curr_ep, matched_view["id"], target_zone_id, s_idx, w_asset_key, w_desc[:25],
                )
            else:
                # 存量槽位不足，插入新增记录
                db.execute(
                    text("""
                        INSERT INTO scene_weathering_views (
                            scene_zone_id, layer_type, description,
                            asset_key, parent_asset_key, generation_mode, denoise_strength,
                            visual_prompt, negative_prompt, is_benchmark, is_primary,
                            is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :scene_zone_id, :layer_type, :description,
                            :asset_key, :parent_asset_key, :gen_mode, :denoise,
                            :visual_prompt, :negative_prompt, 0, 0,
                            1, :now, :now
                        )
                    """),
                    {
                        "scene_zone_id": target_zone_id,
                        "layer_type": layer_type,
                        "description": w_desc,
                        "asset_key": w_asset_key,
                        "parent_asset_key": w_parent_key,
                        "gen_mode": w_gen_mode,
                        "denoise": w_denoise,
                        "visual_prompt": w_full_prompt,
                        "negative_prompt": w_neg_prompt,
                        "now": now,
                    },
                )
                log.info(
                    "【阶段 6 落库】[步骤 4/6 场景做旧] 新增第 %s 集场景做旧切片: scene_id=%s, zone_id=%s, 槽位序号=%d, asset_key=%s, 描述=%s",
                    curr_ep, scene_id, target_zone_id, s_idx, w_asset_key, w_desc[:25],
                )

        # 4.2.3 清理多余的历史幽灵切片（若本次重跑产生的切片数少于已有切片数）
        if existing_view_count > target_view_count:
            surplus_views = existing_ep_views[target_view_count:]
            surplus_ids = [v["id"] for v in surplus_views]
            for s_id in surplus_ids:
                db.execute(
                    text("DELETE FROM scene_weathering_views WHERE id = :id"),
                    {"id": s_id},
                )
            log.info(
                "【阶段 6 落库】[步骤 4/6 场景做旧] 清理第 %s 集多余做旧切片 %d 条: zone_id=%s, 清理ID列表=%s",
                curr_ep, len(surplus_ids), target_zone_id, surplus_ids,
            )

