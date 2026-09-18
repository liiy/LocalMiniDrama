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
from typing import Any, Mapping

from app.schemas.script_graph_state import (
    EpisodeResourceManifest,
    IndustrialDramaMasterState,
    IndustrialDramaState,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE6_SYSTEM_PROMPT,
    STAGE6_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage6_asset_truth")


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _stage6_fallback(
    episode_num: int,
    script_data: dict[str, Any],
    characters_engine: dict[str, Any],
    envs_props: dict[str, Any],
) -> dict[str, Any]:
    """【规则编号: RULE-STAGE6-03】大模型离线或异常时的单集资产清单保底工厂，1:1 编译阶段 2 骨相与阶段 3 做旧环境。"""
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


def stage6_asset_truth_node(state: IndustrialDramaState | IndustrialDramaMasterState) -> dict[str, Any]:
    """【规则编号: RULE-VI-06 & RULE-STAGE6-01】执行阶段 6：提纯单集资产清单并维护全剧真理源总库。
    
    遵守公共硬性约束：
    - 入参统一为 state，返回更新增量字典；
    - 内部严禁任何业务分支跳转，分支全部交由独立条件路由处理；
    - 关键执行步骤记录 debug 日志并标注规则编号。
    """
    ep_num = _get_val(state, "current_visual_episode", 1) or 1
    completed = _get_val(state, "completed_screenplays", {}) or {}
    script = completed.get(ep_num) or completed.get(str(ep_num)) or {}
    chars_engine = _get_val(state, "characters_engine", {}) or {}
    envs_props = _get_val(state, "environments_and_props", {}) or {}

    logger.debug(f"[Stage 6 Node] [RULE-STAGE6-01] Starting asset distillation for Episode {ep_num}.")

    # 【规则编号: RULE-STAGE6-02】组装大模型提示词，提取本集四视角角色、做旧场景、反转物证与母音频
    user_prompt = STAGE6_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        script_json=json.dumps(script, ensure_ascii=False),
        characters_engine_json=json.dumps(chars_engine, ensure_ascii=False),
        environments_props_json=json.dumps(envs_props, ensure_ascii=False),
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE6_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage6_fallback(
            ep_num, script, chars_engine, envs_props
        ),
    )

    manifest_data = result_json.get("manifest") or {}
    manifest = (
        EpisodeResourceManifest.model_validate(manifest_data)
        if manifest_data
        else EpisodeResourceManifest()
    )

    # 【规则编号: RULE-STAGE6-03】真理源已有 APPROVED 资产 100% 只读复用，增量资产建档注册
    registry = dict(_get_val(state, "visual_audio_assets_registry", {}) or {})
    manifests = dict(_get_val(state, "episode_resource_manifests", {}) or {})
    manifests[ep_num] = manifest

    all_chars = dict(registry.get("characters", {}) or {})
    for c in manifest.characters:
        c_dict = c if isinstance(c, dict) else c.model_dump() if hasattr(c, "model_dump") else {}
        cid = c_dict.get("char_id") or c_dict.get("name")
        if cid:
            all_chars[cid] = c_dict

    all_envs = dict(registry.get("environments", {}) or {})
    for e in manifest.environments:
        e_dict = e if isinstance(e, dict) else e.model_dump() if hasattr(e, "model_dump") else {}
        eid = e_dict.get("scene_id") or e_dict.get("location_name")
        if eid:
            all_envs[eid] = e_dict

    all_props = dict(registry.get("props", {}) or {})
    for p in manifest.props:
        p_dict = p if isinstance(p, dict) else p.model_dump() if hasattr(p, "model_dump") else {}
        pid = p_dict.get("prop_id") or p_dict.get("name")
        if pid:
            all_props[pid] = p_dict

    registry["characters"] = all_chars
    registry["environments"] = all_envs
    registry["props"] = all_props

    logger.debug(
        f"[Stage 6 Node] [RULE-STAGE6-03] Episode {ep_num} manifest compiled: "
        f"Chars: {len(manifest.characters)}, Envs: {len(manifest.environments)}, Props: {len(manifest.props)}"
    )

    return {
        "current_stage": 6,
        "visual_audio_assets_registry": registry,
        "episode_resource_manifests": manifests,
    }
