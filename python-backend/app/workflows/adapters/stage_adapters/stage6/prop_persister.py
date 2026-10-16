"""阶段 6 核心道具资产与剧情损坏形态演进持久化组件 (Stage 6 Prop Persister)。

持久化关键叙事道具主数据 (props) 及其剧情战损演进形态树 (prop_damage_states)。
"""
from __future__ import annotations

import json
from typing import Any

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

log = get_logger("lmd.storage_adapter.stage6.prop")


def persist_stage6_props(
    db: Session,
    drama_id: int,
    curr_ep: int,
    episode_id: int | None,
    now: str,
    props_manifest: list[dict[str, Any]],
    newly_discovered_props: list[dict[str, Any]],
    newly_generated_assets: list[dict[str, Any]],
    state: Any,
) -> None:
    """持久化核心道具主记录与剧情损坏演进状态。"""
    # 合并新发现道具项与新生成资产中的道具项
    for new_prop in newly_discovered_props:
        np_dict = _dump_or_dict(new_prop)
        if isinstance(np_dict, dict) and np_dict not in props_manifest:
            props_manifest.append(np_dict)

    for new_asset in newly_generated_assets:
        n_dict = _dump_or_dict(new_asset)
        if not isinstance(n_dict, dict):
            continue
        cat = str(n_dict.get("category") or "").lower()
        aid = str(n_dict.get("asset_id") or "")
        if (cat == "prop" or aid.startswith("PROP_")) and n_dict not in props_manifest:
            props_manifest.append(n_dict)

    for prop_raw in props_manifest:
        prop = _dump_or_dict(prop_raw)
        if not isinstance(prop, dict):
            continue
        p_name = str(prop.get("prop_name") or prop.get("name") or "").strip()
        if not p_name:
            continue

        raw_p_code = str(prop.get("prop_code") or prop.get("code") or "").strip()
        p_code = raw_p_code if raw_p_code else AssetProtocolHelper.normalize_token(p_name)
        bench_prop_key = prop.get("benchmark_asset_key") or AssetProtocolHelper.get_benchmark_key_for_prop(p_code)

        existing_prop = fetch_one(
            db,
            "SELECT id FROM props WHERE drama_id = :drama_id AND (prop_code = :p_code OR name = :name)",
            {"drama_id": drama_id, "p_code": p_code, "name": p_name},
        )
        if existing_prop:
            prop_id = existing_prop["id"]
            db.execute(
                text("""
                    UPDATE props
                    SET prop_code = CASE WHEN (prop_code IS NULL OR prop_code = '') AND :p_code != '' THEN :p_code ELSE prop_code END,
                        benchmark_asset_key = CASE WHEN (benchmark_asset_key IS NULL OR benchmark_asset_key = '') AND :bench_key != '' THEN :bench_key ELSE benchmark_asset_key END,
                        description = CASE WHEN :description != '' THEN :description ELSE description END,
                        prompt = CASE WHEN :prompt != '' THEN :prompt ELSE prompt END,
                        updated_at = :now
                    WHERE id = :id
                """),
                {
                    "id": prop_id,
                    "p_code": p_code,
                    "bench_key": bench_prop_key,
                    "description": prop.get("description") or f"第{curr_ep}集关键叙事道具",
                    "prompt": prop.get("visual_prompt") or prop.get("prompt") or "",
                    "now": now,
                },
            )
        else:
            p_ins = db.execute(
                text("""
                    INSERT INTO props (
                        drama_id, prop_code, benchmark_asset_key, name, type, description, prompt, created_at, updated_at
                    ) VALUES (
                        :drama_id, :prop_code, :benchmark_asset_key, :name, :type, :description, :prompt, :now, :now
                    )
                """),
                {
                    "drama_id": drama_id,
                    "prop_code": p_code,
                    "benchmark_asset_key": bench_prop_key,
                    "name": p_name,
                    "type": prop.get("type", "narrative_reversal"),
                    "description": prop.get("description") or f"第{curr_ep}集关键叙事道具",
                    "prompt": prop.get("visual_prompt") or "",
                    "now": now,
                },
            )
            prop_id = safe_int(getattr(p_ins, "lastrowid", None), default=1)
            log.info(
                "【阶段 6 落库】[步骤 5/6 道具] 登记第 %s 集新道具: prop_id=%s, 代号=%s, 名称=%s, 基准键=%s",
                curr_ep, prop_id, p_code, p_name, bench_prop_key,
            )

        # 写入道具破坏与战损演进状态 (prop_damage_states)
        d_states: list[dict[str, Any]] = []
        raw_ds = prop.get("damage_states") or prop.get("damage_state_views")
        if raw_ds:
            if isinstance(raw_ds, list):
                for item in raw_ds:
                    if isinstance(item, dict):
                        d_states.append(item)
                    elif isinstance(item, str) and item.strip():
                        d_states.append({"state_label": item.strip()})
            elif isinstance(raw_ds, dict):
                for k, v in raw_ds.items():
                    d_states.append({"state_label": str(k), "narrative_point": str(v)})
            elif isinstance(raw_ds, str) and raw_ds.strip():
                d_states.append({"state_label": raw_ds.strip()})

        single_state = str(prop.get("damage_state") or prop.get("state_label") or "").strip()
        if single_state and not any(ds.get("state_label") == single_state for ds in d_states):
            d_states.append({
                "state_label": single_state,
                "damage_level": prop.get("damage_level", 1),
                "parent_state_id": prop.get("parent_state_id"),
                "parent_state_label": prop.get("parent_state_label"),
                "narrative_point": prop.get("narrative_point"),
                "visual_prompt": prop.get("visual_prompt"),
            })

        # 若未提供显式战损形态（例如初始完整物证），自动为其建立 S0 初始完整形态，确保 3 层体系完整闭环
        if not d_states:
            d_states.append({
                "state_code": "S0",
                "state_label": "初始完整形态",
                "damage_level": 0,
                "narrative_point": prop.get("description") or f"第{curr_ep}集初始物证形态",
                "visual_prompt": prop.get("visual_prompt"),
            })

        prev_ds_id = 0
        for s_idx, ds_item in enumerate(d_states):
            s_label = str(ds_item.get("state_label") or "").strip()
            if not s_label or not prop_id:
                continue

            has_explicit_code = bool(ds_item.get("state_code"))
            if has_explicit_code:
                state_code = str(ds_item.get("state_code")).strip().upper()
                if state_code.isdigit():
                    state_code = f"S{state_code}"
            else:
                c_row = fetch_one(db, "SELECT count(id) as cnt FROM prop_damage_states WHERE prop_id = :prop_id", {"prop_id": prop_id})
                c_cnt = int(c_row.get("cnt", 0)) if c_row else s_idx
                state_code = f"S{c_cnt}"

            parent_state_ref = ds_item.get("parent_state_id") or ds_item.get("parent_state_label") or ""
            parent_state_id = 0
            if isinstance(parent_state_ref, int):
                parent_state_id = parent_state_ref
            elif isinstance(parent_state_ref, str) and parent_state_ref.strip():
                p_label = parent_state_ref.strip()
                parent_pds_row = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND (state_label = :p_label OR state_code = :p_label)",
                    {"prop_id": prop_id, "p_label": p_label},
                )
                if parent_pds_row:
                    parent_state_id = parent_pds_row["id"]
                    log.debug("【阶段 6 落库】[DEBUG 道具状态] 成功解析父级战损形态 ID: prop_id=%s, state_label=%s -> parent_state_id=%s", prop_id, s_label, parent_state_id)

            # 若未显式指定父级形态且非首个形态，自动绑定上一损伤形态作为演进母本
            if parent_state_id == 0:
                if prev_ds_id > 0:
                    parent_state_id = prev_ds_id
                else:
                    raw_cur_lvl = ds_item.get("damage_level", 0)
                    try:
                        cur_lvl = int(raw_cur_lvl)
                    except (ValueError, TypeError):
                        cur_lvl = 0
                    if cur_lvl > 0:
                        prev_row = fetch_one(
                            db,
                            "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND damage_level < :cur_lvl ORDER BY damage_level DESC, id DESC LIMIT 1",
                            {"prop_id": prop_id, "cur_lvl": cur_lvl},
                        )
                        if prev_row:
                            parent_state_id = prev_row["id"]

            p_id_prompt = PromptSynthesizer.extract_identity_face_anchor(prop.get("visual_prompt") or p_name)
            p_delta_prompt = f"damage state: {s_label}, level: {ds_item.get('damage_level', 1)}"
            p_neg_prompt = PromptSynthesizer.get_negative_prompt("prop")
            p_synth = PromptSynthesizer.synthesize_prop_view_prompt(p_id_prompt, view_type="STATIC", state_prompt=p_delta_prompt)
            p_full_prompt = p_synth.visual_prompt

            if has_explicit_code:
                existing_ds = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND (state_label = :s_label OR state_code = :s_code)",
                    {"prop_id": prop_id, "s_label": s_label, "s_code": state_code},
                )
            else:
                existing_ds = fetch_one(
                    db,
                    "SELECT id FROM prop_damage_states WHERE prop_id = :prop_id AND state_label = :s_label",
                    {"prop_id": prop_id, "s_label": s_label},
                )
            raw_d_level = ds_item.get("damage_level", prop.get("damage_level", 1))
            try:
                damage_level = int(raw_d_level)
            except (ValueError, TypeError):
                damage_level = 1

            narrative_point = str(ds_item.get("narrative_point") or prop.get("narrative_point") or f"第{curr_ep}集剧情触发物证形态演进: {s_label}")
            visual_prompt = str(ds_item.get("visual_prompt") or prop.get("visual_prompt") or p_full_prompt)

            if existing_ds:
                db.execute(
                    text("""
                        UPDATE prop_damage_states
                        SET state_code = CASE WHEN (state_code IS NULL OR state_code = '') THEN :state_code ELSE state_code END,
                            parent_state_id = CASE WHEN (parent_state_id IS NULL OR parent_state_id = 0) AND :parent_state_id > 0 THEN :parent_state_id ELSE parent_state_id END,
                            damage_level = :damage_level,
                            narrative_point = :narrative_point,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_ds["id"],
                        "state_code": state_code,
                        "parent_state_id": parent_state_id,
                        "damage_level": damage_level,
                        "narrative_point": narrative_point,
                        "now": now,
                    },
                )
                ds_id = existing_ds["id"]
            else:
                ins_ds = db.execute(
                    text("""
                        INSERT INTO prop_damage_states (
                            prop_id, drama_id, state_code, state_label, damage_level,
                            narrative_point, parent_state_id, created_at, updated_at
                        ) VALUES (
                            :prop_id, :drama_id, :state_code, :state_label, :damage_level,
                            :narrative_point, :parent_state_id, :now, :now
                        )
                    """),
                    {
                        "prop_id": prop_id,
                        "drama_id": drama_id,
                        "state_code": state_code,
                        "state_label": s_label,
                        "damage_level": damage_level,
                        "narrative_point": narrative_point,
                        "parent_state_id": parent_state_id,
                        "now": now,
                    },
                )
                ds_id = safe_int(getattr(ins_ds, "lastrowid", None), default=1)

            prev_ds_id = ds_id

            macro_asset_key = f"{bench_prop_key}_{state_code}_DETAIL"
            macro_delta = f"macro close-up feature of {s_label}"
            
            # 兼容从上游 manifest 传入的自定义 detail_views 特写描述
            custom_detail_desc = ""
            raw_dvs = ds_item.get("detail_views") or prop.get("detail_views") or []
            if isinstance(raw_dvs, list):
                for dv_item in raw_dvs:
                    if isinstance(dv_item, dict):
                        custom_detail_desc = dv_item.get("visual_prompt") or dv_item.get("description") or ""
                        if custom_detail_desc:
                            break
                    elif isinstance(dv_item, str) and dv_item.strip():
                        custom_detail_desc = dv_item.strip()
                        break
            if custom_detail_desc:
                macro_delta = f"{macro_delta}, {custom_detail_desc}"

            macro_synth = PromptSynthesizer.synthesize_prop_view_prompt(p_id_prompt, view_type="DETAIL", state_prompt=macro_delta)
            macro_prompt_str = macro_synth.visual_prompt

            existing_dv = fetch_one(
                db,
                "SELECT id FROM prop_detail_views WHERE damage_state_id = :ds_id AND view_type = 'macro_feature'",
                {"ds_id": ds_id},
            )
            if existing_dv:
                db.execute(
                    text("""
                        UPDATE prop_detail_views
                        SET asset_key = CASE WHEN (asset_key IS NULL OR asset_key = '') THEN :asset_key ELSE asset_key END,
                            parent_asset_key = CASE WHEN :parent_asset_key IS NOT NULL AND :parent_asset_key != '' THEN :parent_asset_key ELSE parent_asset_key END,
                            generation_mode = CASE WHEN (generation_mode IS NULL OR generation_mode = '' OR generation_mode = 't2i') THEN 'crop_macro' ELSE generation_mode END,
                            denoise_strength = CASE WHEN (denoise_strength IS NULL OR denoise_strength = 0) THEN 0.45 ELSE denoise_strength END,
                            visual_prompt = CASE WHEN :visual_prompt != '' THEN :visual_prompt ELSE visual_prompt END,
                            negative_prompt = CASE WHEN :negative_prompt != '' THEN :negative_prompt ELSE negative_prompt END,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": existing_dv["id"],
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_prompt_str,
                        "negative_prompt": p_neg_prompt,
                        "now": now,
                    },
                )
            else:
                db.execute(
                    text("""
                        INSERT INTO prop_detail_views (
                            damage_state_id, asset_key, view_type,
                            parent_asset_key, generation_mode, denoise_strength,
                            visual_prompt, negative_prompt,
                            is_benchmark, is_primary, is_locked_truth, created_at, updated_at
                        ) VALUES (
                            :damage_state_id, :asset_key, 'macro_feature',
                            :parent_asset_key, 'crop_macro', 0.45,
                            :visual_prompt, :negative_prompt,
                            0, 1, 1, :now, :now
                        )
                    """),
                    {
                        "damage_state_id": ds_id,
                        "asset_key": macro_asset_key,
                        "parent_asset_key": bench_prop_key,
                        "visual_prompt": macro_prompt_str,
                        "negative_prompt": p_neg_prompt,
                        "now": now,
                    },
                )
            log.info(
                "【阶段 6 落库】[步骤 5/6 道具形态] 记录道具 [%s] 战损演进状态: 形态=%s(%s), 父基准键=%s, 剧集=%s",
                p_name, s_label, state_code, bench_prop_key, curr_ep,
            )

    # 二次遍历解析可能因先后次序未解析的 parent_state_id
    for prop_raw in props_manifest:
        prop = _dump_or_dict(prop_raw)
        if not isinstance(prop, dict):
            continue
        p_name = str(prop.get("prop_name") or prop.get("name") or "").strip()
        p_row = fetch_one(db, "SELECT id FROM props WHERE drama_id = :drama_id AND name = :name", {"drama_id": drama_id, "name": p_name})
        if not p_row:
            continue
        pid = p_row["id"]
        raw_ds = prop.get("damage_states") or prop.get("damage_state_views") or []
        if isinstance(raw_ds, dict):
            raw_ds = [{"state_label": k, "narrative_point": v} for k, v in raw_ds.items()]
        elif not isinstance(raw_ds, list):
            raw_ds = []
        if prop.get("damage_state") or prop.get("parent_state_label"):
            raw_ds.append(prop)
        for ds_it in raw_ds:
            if not isinstance(ds_it, dict):
                continue
            s_lbl = str(ds_it.get("state_label") or ds_it.get("damage_state") or "").strip()
            p_lbl = str(ds_it.get("parent_state_label") or "").strip()
            if s_lbl and p_lbl:
                p_ds_row = fetch_one(
                    db,
                    """
                    SELECT id FROM prop_damage_states
                    WHERE prop_id = :pid AND state_label = :p_lbl
                    LIMIT 1
                    """,
                    {"pid": pid, "p_lbl": p_lbl},
                )
                if p_ds_row and p_ds_row.get("id"):
                    db.execute(
                        text("""
                            UPDATE prop_damage_states
                            SET parent_state_id = :parent_id
                            WHERE prop_id = :pid AND state_label = :s_lbl AND (parent_state_id IS NULL OR parent_state_id = 0)
                        """),
                        {"pid": pid, "s_lbl": s_lbl, "parent_id": p_ds_row["id"]},
                    )
                    log.debug("【阶段 6 落库】[DEBUG 道具状态二次解析] 关联 parent_state_id: prop_id=%s, state_label=%s, parent_label=%s, parent_id=%s", pid, s_lbl, p_lbl, p_ds_row["id"])

