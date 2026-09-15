"""阶段 6：第二程资产准备与真理源校验节点 (Stage 6 Asset Truth Registry Node)。

严格遵循 SKILL.md：
从已锁定的文学剧本中提纯【单集资源引单 EpisodeResourceManifest】，
保证每个出场人物、做旧场景、反转道具均有唯一资产 ID 与生图 Prompt，
并汇总更新到全剧真理源总库 (05_visual_audio_assets.json)。
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
)
from app.workflows.prompts.master_sop_prompts import STAGE6_SYSTEM_PROMPT
from app.workflows.utils.llm_bridge import call_llm_json


def _stage6_fallback(
    episode_num: int,
    script_data: dict[str, Any],
    characters_engine: dict[str, Any],
    envs_props: dict[str, Any],
) -> dict[str, Any]:
    chars = characters_engine.get("characters") or []
    envs = envs_props.get("environments") or []
    props = envs_props.get("props") or []

    manifest_chars = []
    for idx, c in enumerate(chars, start=1):
        manifest_chars.append({
            "char_id": f"CHAR_{idx:02d}_{c.get('name', 'ROLE')}",
            "name": c.get("name", "未命名"),
            "costume": "根据场景搭配的常服与微破损痕迹",
            "visual_prompt": f"超写实电影质感，{c.get('appearance', '人物外观')}，高反差冷色调",
        })

    manifest_envs = []
    for idx, e in enumerate(envs, start=1):
        manifest_envs.append({
            "scene_id": f"SCENE_{idx:02d}",
            "location_name": e.get("location_name", "核心场景"),
            "weathering_layers": e.get("weathering_layers", {}),
            "visual_prompt": e.get("visual_prompt", "电影胶片暗黑悬疑感"),
        })

    manifest_props = []
    for idx, p in enumerate(props, start=1):
        manifest_props.append({
            "prop_id": f"PROP_{idx:02d}",
            "name": p.get("name", "核心道具"),
            "damage_scale": p.get("damage_scale", "微小磨损"),
            "foley_prompt": p.get("foley_resistance", "+3dB 金属锐利撞击声"),
        })

    return {
        "episode_num": episode_num,
        "manifest": {
            "characters": manifest_chars,
            "environments": manifest_envs,
            "props": manifest_props,
            "audio_motifs": [
                {
                    "motif_id": "LEITMOTIF_01_SUSPENSE",
                    "action": "引入低音大提琴单音震音与管道回响",
                }
            ],
        },
    }


def stage6_asset_truth_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 6：提纯单集资产清单并维护全剧真理源总库。"""
    ep_num = state.current_visual_episode or 1
    script = state.completed_screenplays.get(ep_num) or {}

    user_prompt = f"""【当前视听集数】第 {ep_num} 集
【单集文学剧本】
{json.dumps(script, ensure_ascii=False)}

【阶段 2 角色引擎】
{json.dumps(state.characters_engine, ensure_ascii=False)}

【阶段 3 空间与物证】
{json.dumps(state.environments_and_props, ensure_ascii=False)}

请提纯输出第 {ep_num} 集的视听资产真理清单纯 JSON 结构体："""

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE6_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage6_fallback(
            ep_num, script, state.characters_engine, state.environments_and_props
        ),
    )

    manifest_data = result_json.get("manifest") or {}
    manifest = EpisodeResourceManifest.model_validate(manifest_data) if manifest_data else EpisodeResourceManifest()

    # 更新全局 registry
    registry = dict(state.visual_audio_assets_registry or {})
    manifests = dict(state.episode_resource_manifests or {})
    manifests[ep_num] = manifest

    # 合并到全局 registry 的角色、场景、道具总库
    all_chars = registry.get("characters", {})
    for c in manifest.characters:
        c_dict = c if isinstance(c, dict) else c.model_dump() if hasattr(c, "model_dump") else {}
        cid = c_dict.get("char_id") or c_dict.get("name")
        if cid:
            all_chars[cid] = c_dict

    all_envs = registry.get("environments", {})
    for e in manifest.environments:
        e_dict = e if isinstance(e, dict) else e.model_dump() if hasattr(e, "model_dump") else {}
        eid = e_dict.get("scene_id") or e_dict.get("location_name")
        if eid:
            all_envs[eid] = e_dict

    all_props = registry.get("props", {})
    for p in manifest.props:
        p_dict = p if isinstance(p, dict) else p.model_dump() if hasattr(p, "model_dump") else {}
        pid = p_dict.get("prop_id") or p_dict.get("name")
        if pid:
            all_props[pid] = p_dict

    registry["characters"] = all_chars
    registry["environments"] = all_envs
    registry["props"] = all_props

    return {
        "current_stage": 6,
        "visual_audio_assets_registry": registry,
        "episode_resource_manifests": manifests,
    }
