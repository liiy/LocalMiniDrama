"""阶段 6：第二程资产准备与真理源校验节点 (Stage 6 Asset Truth Registry Node)。

严格遵循 SKILL.md：
从已锁定的文学剧本中提纯【单集资源引单 EpisodeResourceManifest】，
【严禁现场脑补！1:1 编译阶段 2 肖像骨相 DNA 与真实服饰代码】：
- 调取阶段 2 锁定的微观生物肖像骨相（真实毛孔/毫米级痣疤/眼唇解剖/发质）；
- 调取阶段 2 锁定的真实生活质感服化道代码（面料克重/折痕线头/泥斑/磨损）；
保证每个出场人物、做旧场景、反转道具均有唯一资产 ID 与生图 Prompt，
并汇总更新到全剧真理源总库 (05_visual_audio_assets.json)。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE6_SYSTEM_PROMPT,
    STAGE6_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage6_asset_truth")


def _stage6_fallback(
    episode_num: int,
    script_data: dict[str, Any],
    characters_engine: dict[str, Any],
    envs_props: dict[str, Any],
) -> dict[str, Any]:
    """大模型离线或异常时的单集资产清单保底工厂，1:1 编译阶段 2 骨相与阶段 3 做旧环境。"""
    logger.warning(f"Triggering Stage 6 dynamic fallback asset compilation for Episode {episode_num}.")
    
    chars = characters_engine.get("characters") or []
    envs = envs_props.get("environments") or []
    props = envs_props.get("props") or []

    manifest_chars = []
    for idx, c in enumerate(chars, start=1):
        bio = c.get("biological_dna") or {}
        costume = c.get("lived_in_costume") or {}
        
        bio_desc = (
            f"骨相与五官: {bio.get('bone_structure', '硬朗骨相')}; "
            f"皮肤肌理: {bio.get('skin_micro_texture', '自然毛孔细纹')}; "
            f"面部瑕疵: {bio.get('blemishes_and_scars', '额角旧伤痕')}; "
            f"眼唇解剖: {bio.get('eye_lip_anatomy', '内双窄眼皮红血丝，干燥起皮唇')}; "
            f"发质发型: {bio.get('hair_texture', '粗硬微卷自然碎发')}"
        )
        costume_desc = (
            f"上装: {costume.get('top_wear', '重磅做旧大衣')}; "
            f"下装: {costume.get('bottom_wear', '耐磨工装裤')}; "
            f"鞋履: {costume.get('footwear', '磨损工装皮靴')}; "
            f"做旧细节: {costume.get('wear_and_tear_details', '手肘折痕与线头松脱')}"
        )

        manifest_chars.append({
            "char_id": f"CHAR_{idx:02d}_{c.get('name', 'ROLE')}",
            "name": c.get("name", "未命名"),
            "costume": costume_desc,
            "visual_prompt": (
                f"cinematic photorealistic 8k masterpiece, Chinese character, {c.get('appearance', '人物外观')}, "
                f"{bio_desc}, wearing {costume_desc}, raw gritty film grain, highly detailed, dramatic rim lighting"
            ),
        })

    manifest_envs = []
    for idx, e in enumerate(envs, start=1):
        manifest_envs.append({
            "scene_id": f"SCENE_{idx:02d}",
            "location_name": e.get("location_name", "核心场景"),
            "weathering_layers": e.get("weathering_layers", {}),
            "visual_prompt": e.get("visual_prompt", "电影胶片暗黑悬疑感，真实空间做旧与逆光丁达尔"),
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
    logger.info(f"[Stage 6 Node] Distilling visual/audio asset manifest for Episode {ep_num}")

    user_prompt = STAGE6_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        script_json=json.dumps(script, ensure_ascii=False),
        characters_engine_json=json.dumps(state.characters_engine, ensure_ascii=False),
        environments_props_json=json.dumps(state.environments_and_props, ensure_ascii=False),
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE6_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage6_fallback(
            ep_num, script, state.characters_engine, state.environments_and_props
        ),
    )

    manifest_data = result_json.get("manifest") or {}
    manifest = (
        EpisodeResourceManifest.model_validate(manifest_data)
        if manifest_data
        else EpisodeResourceManifest()
    )

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

    logger.info(
        f"[Stage 6 Node] Episode {ep_num} manifest registered. "
        f"Chars: {len(manifest.characters)}, Envs: {len(manifest.environments)}, Props: {len(manifest.props)}"
    )

    return {
        "current_stage": 6,
        "visual_audio_assets_registry": registry,
        "episode_resource_manifests": manifests,
    }
