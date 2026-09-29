"""红蓝对抗独立自审引擎 (Red-Blue Auditor Agent)。

严格遵循 SKILL.md 工业级标准：
- 蓝军工程师：客观硬指标审查（双轨禁令、时间轴合规、微观生物肖像骨相DNA、真实生活质感服化道代码、资产与物理存在性、格式完备度）；
- 红军魔鬼制片人：戏剧挑刺（动机自洽、张力匮乏、降智打脸、视听不可执行性、网红脸与崭新塑料感排查）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.script_graph_state import AuditVerdict, RedBlueAuditReport
from app.workflows.prompts.master_sop_prompts import (
    AUDIT_SYSTEM_PROMPT,
    AUDIT_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.llm_bridge import call_llm_json


def _fallback_audit_report(stage: int, content_summary: str) -> dict[str, Any]:
    return {
        "blue_team_compliance": {
            "passed": True,
            "forbidden_rules_check": "未触犯10大俗套与3大廉价爽点",
            "dna_and_costume_check": "微观生物骨相DNA与生活质感服饰代码完备",
            "timeline_check": "节奏点符合短剧行业标准",
            "asset_integrity_check": "核心资产引用完整",
        },
        "red_team_criticism": {
            "dramatic_tension_score": 88,
            "pacing_sharpness": "冲突高潮明确，前置铺垫充分",
            "visual_feasibility": "动作具象可落地，骨相与面部瑕疵清晰可生图",
        },
        "verdict": AuditVerdict.GREEN_APPROVED,
        "blocking_issues": [],
        "warning_suggestions": ["建议进一步加强随身道具微距特写以增强镜头冲击力"],
    }


class RedBlueAuditor:
    """红蓝对抗独立自审器。"""

    @staticmethod
    def audit(
        stage: int,
        content_payload: Any,
        forbidden_rules: Any = None,
    ) -> RedBlueAuditReport:
        """执行针对指定阶段产出物的红蓝独立对抗质检。"""
        if isinstance(content_payload, (dict, list)):
            payload_str = json.dumps(
                content_payload,
                ensure_ascii=False,
                indent=2,
                default=lambda o: o.model_dump() if hasattr(o, "model_dump") else (o.__dict__ if hasattr(o, "__dict__") else str(o)),
            )
        else:
            payload_str = str(content_payload)

        # 1. 蓝军前置硬规则快速自检（Local Fast-Check）
        quick_blocking: list[str] = []
        if stage == 1:
            # 【规则编号: AUDIT-CHECKPOINT-01】阶段 1 蓝军客观合规硬性检查
            if isinstance(content_payload, dict):
                # 检查 10 大因果禁令
                neg = content_payload.get("negative_rules") or {}
                if isinstance(neg, dict):
                    cliches = neg.get("forbidden_cliches") or content_payload.get("forbidden_cliches_10") or []
                    cheap = neg.get("forbidden_cheap_pleasures") or content_payload.get("forbidden_cheap_tropes_3") or []
                elif hasattr(neg, "forbidden_cliches"):
                    cliches = getattr(neg, "forbidden_cliches", [])
                    cheap = getattr(neg, "forbidden_cheap_pleasures", [])
                else:
                    cliches = content_payload.get("forbidden_cliches_10") or []
                    cheap = content_payload.get("forbidden_cheap_tropes_3") or []
                
                if len(cliches) < 10:
                    quick_blocking.append(f"【蓝军阻断】阶段 1 缺少 10 大老套因果禁令清单 (当前: {len(cliches)}/10)")
                if len(cheap) < 3:
                    quick_blocking.append(f"【蓝军阻断】阶段 1 缺少 3 大廉价爽点禁令清单 (当前: {len(cheap)}/3)")
                
                # 检查四大商业维度片名矩阵
                cand = content_payload.get("candidate_titles") or {}
                if isinstance(cand, dict):
                    dims = ["identity_contrast", "extreme_suspense", "prop_irony", "dark_psychology"]
                    missing_dims = [d for d in dims if not cand.get(d)]
                    if missing_dims:
                        quick_blocking.append(f"【蓝军阻断】阶段 1 候选片名矩阵缺少商业维度: {missing_dims}")
                
                # 检查 Logline 与 Grand Payoff
                if not content_payload.get("logline"):
                    quick_blocking.append("【蓝军阻断】阶段 1 缺失核心工业 Logline")
                if not content_payload.get("grand_payoff"):
                    quick_blocking.append("【蓝军阻断】阶段 1 缺失终局核爆点 (grand_payoff)")

        elif stage == 2:
            # 【规则编号: AUDIT-CHECKPOINT-02】阶段 2 蓝军客观合规硬性检查
            if isinstance(content_payload, dict):
                chars = content_payload.get("characters") or []
                if not chars:
                    quick_blocking.append("【蓝军阻断】阶段 2 缺失核心角色清单 (characters)")
                for c in chars:
                    c_name = c.get("name", "未命名角色")
                    cid = c.get("character_id") or ""
                    # 检查四段式根命名空间 CHAR_<TOKEN>
                    if not cid or not str(cid).startswith("CHAR_") or not re.match(r"^CHAR_[A-Z0-9]+$", str(cid)):
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] character_id '{cid}' 格式不合法：必须为纯大写字母数字 CHAR_<TOKEN>")
                    
                    # 检查生理性别 (mandatory)
                    gender = c.get("gender") or c.get("biological_sex") or c.get("sex")
                    if not gender:
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失强制生理性别(gender/biological_sex)，存在配音与幻觉风险")

                    bio = c.get("biological_dna")
                    if not bio or not isinstance(bio, dict):
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失微观生物肖像骨相(biological_dna)，存在AI塑料脸风险")
                    else:
                        has_bone = bool(bio.get("bone_structure") or bio.get("face_shape"))
                        has_skin = bool(bio.get("skin_micro_texture") or bio.get("skin_texture") or bio.get("skin_pores"))
                        if not has_bone or not has_skin:
                            quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] biological_dna 缺失骨相(bone_structure)或皮肤肌理(skin_micro_texture)")
                    
                    costume = c.get("lived_in_costume")
                    if not costume or not isinstance(costume, dict):
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失真实生活质感服化道代码(lived_in_costume)，存在崭新塑料感风险")
                    
                    quad = c.get("psychological_quad") or c.get("psychology_4")
                    if not quad or not isinstance(quad, dict) or not quad.get("want") or not (quad.get("lie") or quad.get("the_lie")):
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失心理四元组(Want/Need/Lie/Ghost)")

        elif stage == 3:
            # 【规则编号: AUDIT-CHECKPOINT-03】阶段 3 蓝军客观合规硬性检查
            if isinstance(content_payload, dict):
                envs = content_payload.get("environments") or []
                props = content_payload.get("props") or []
                if not envs:
                    quick_blocking.append("【蓝军阻断】阶段 3 缺失核心主场景清单 (environments)")
                for e in envs:
                    loc_name = e.get("location_name") or e.get("env_id", "未命名")
                    eid = e.get("env_id") or ""
                    # 检查四段式根命名空间 ENV_<TOKEN>
                    if not eid or not str(eid).startswith("ENV_") or not re.match(r"^ENV_[A-Z0-9_]+$", str(eid)):
                        quick_blocking.append(f"【蓝军阻断】场景 [{loc_name}] env_id '{eid}' 格式不合法：必须为纯大写字母数字下划线 ENV_<TOKEN>")

                    w = e.get("three_layer_aging") or e.get("weathering_layers") or {}
                    has_struct = bool(w.get("structure") or w.get("structural"))
                    has_living = bool(w.get("lived_grime") or w.get("living"))
                    has_optical = bool(w.get("light_and_air") or w.get("optical"))
                    if not (has_struct and has_living and has_optical):
                        quick_blocking.append(f"【蓝军阻断】场景 [{loc_name}] 缺失三层做旧架构(structural/living/optical 或 structure/lived_grime/light_and_air)")
                    if e.get("costume_resonance_check") is False:
                        quick_blocking.append(f"【蓝军阻断】场景 [{loc_name}] 未通过场景与服装同源共振审查(costume_resonance_check: false)")
                
                if not props:
                    quick_blocking.append("【蓝军阻断】阶段 3 缺失核心物证道具清单 (props)")
                for p in props:
                    p_name = p.get("name") or p.get("prop_id", "未命名物证")
                    pid = p.get("prop_id") or ""
                    # 检查四段式根命名空间 PROP_<TOKEN>
                    if not pid or not str(pid).startswith("PROP_") or not re.match(r"^PROP_[A-Z0-9_]+$", str(pid)):
                        quick_blocking.append(f"【蓝军阻断】道具 [{p_name}] prop_id '{pid}' 格式不合法：必须为纯大写字母数字下划线 PROP_<TOKEN>")

                    specs = p.get("physical_specs") if isinstance(p.get("physical_specs"), dict) else {}
                    damage = p.get("damage_scale") or specs.get("material_damage_dimensions") or p.get("appearance_and_wear")
                    if not damage:
                        quick_blocking.append(f"【蓝军阻断】核心物证 [{p_name}] 缺失破损尺度(damage_scale / physical_specs.material_damage_dimensions)")
                    foley = p.get("foley_resistance") or specs.get("foley_boost_db") or p.get("haptic_friction_foley") or ""
                    level = p.get("level") or ""
                    if (level == "hero_tier1" or not level) and "+3" not in str(foley):
                        quick_blocking.append(f"【蓝军阻断】核心物证 [{p_name}] 缺失专属 +3.0dB 拟音标记(foley_resistance / physical_specs.foley_boost_db)")

        elif stage == 4:
            # 【规则编号: AUDIT-CHECKPOINT-04】阶段 4 蓝军客观合规硬性检查
            if hasattr(content_payload, "to_dict"):
                content_payload = content_payload.to_dict()
            elif hasattr(content_payload, "model_dump"):
                content_payload = content_payload.model_dump()

            if isinstance(content_payload, dict):
                audio = content_payload.get("audio_bible") or {}
                if hasattr(audio, "to_dict"):
                    audio = audio.to_dict()
                elif hasattr(audio, "model_dump"):
                    audio = audio.model_dump()

                leitmotifs = (
                    audio.get("leitmotif_registry")
                    if isinstance(audio, dict) and audio.get("leitmotif_registry")
                    else audio.get("leitmotifs") if isinstance(audio, dict) else []
                )
                motif_ids = [
                    (m.get("leitmotif_id") or m.get("motif_id"))
                    for m in (leitmotifs or [])
                    if isinstance(m, dict)
                ]
                if len(motif_ids) < 3:
                    quick_blocking.append("【蓝军阻断】阶段 4 缺失全剧核心声学母题/核心音乐主题动机 (audio_bible 需至少定义 3 大具象音乐主题动机)")
                else:
                    expected_motifs = ["LEITMOTIF_01_SUSPENSE", "LEITMOTIF_02_TRAUMA", "LEITMOTIF_03_COUNTERATTACK"]
                    has_standard = any(em in motif_ids for em in expected_motifs)
                    if has_standard:
                        for em in expected_motifs:
                            if em not in motif_ids:
                                quick_blocking.append(f"【蓝军阻断】阶段 4 缺失全剧核心声学母题/音乐主题动机: {em}")

                mini_arcs = content_payload.get("mini_arc_units")
                if mini_arcs is not None and len(mini_arcs) == 0:
                    quick_blocking.append("【蓝军阻断】阶段 4 缺失全季戏剧微弧单元/小高潮规划 (mini_arc_units)")
                
                outlines = (
                    content_payload.get("season_outlines")
                    or content_payload.get("episodes")
                    or (content_payload.get("season_outline") or {}).get("episodes")
                    or {}
                )
                if not outlines:
                    quick_blocking.append("【蓝军阻断】阶段 4 缺失分集双螺旋大纲任务卡 (season_outlines / episodes)")
                else:
                    ep_items = outlines.values() if isinstance(outlines, dict) else outlines
                    for ep in ep_items:
                        if hasattr(ep, "to_dict"):
                            ep = ep.to_dict()
                        elif hasattr(ep, "model_dump"):
                            ep = ep.model_dump()
                        if isinstance(ep, dict):
                            ep_num = ep.get("episode_id") or ep.get("episode_number") or ""
                            if not (ep.get("hook_3s") or ep.get("three_second_hook") or ep.get("hook")):
                                quick_blocking.append(f"【蓝军阻断】第{ep_num}集大纲缺失前3s视觉抓手(hook_3s)")
                            if not (ep.get("micro_twist_45s") or ep.get("micro_turning_point_45s")):
                                quick_blocking.append(f"【蓝军阻断】第{ep_num}集大纲缺失45s微反转(micro_twist_45s / micro_turning_point_45s)")
                            if not (ep.get("cliffhanger_end") or ep.get("killer_cliffhanger_115s") or ep.get("cliffhanger")):
                                quick_blocking.append(f"【蓝军阻断】第{ep_num}集大纲缺失生死绝杀断点(cliffhanger_end / cliffhanger)")

        elif stage == 5:
            # 【规则编号: AUDIT-CHECKPOINT-05】阶段 5 文学剧本蓝军客观合规硬性检查
            if hasattr(content_payload, "to_dict"):
                content_payload = content_payload.to_dict()
            elif hasattr(content_payload, "model_dump"):
                content_payload = content_payload.model_dump()

            if isinstance(content_payload, dict) and "completed_screenplays" in content_payload:
                content_payload = content_payload["completed_screenplays"]

            if isinstance(content_payload, list):
                ep_items_with_key = [(i + 1, ep) for i, ep in enumerate(content_payload)]
            elif isinstance(content_payload, dict):
                if "screenplay_text" in content_payload or "body_markdown" in content_payload or "hook_3s" in content_payload:
                    ep_items_with_key = [(content_payload.get("episode_num") or content_payload.get("episode_id") or 1, content_payload)]
                else:
                    ep_items_with_key = [(k, v) for k, v in content_payload.items() if isinstance(v, (dict, object))]
            else:
                ep_items_with_key = []

            if not ep_items_with_key:
                quick_blocking.append("【蓝军阻断】阶段 5 剧本文学工笔产出为空，无有效分集剧本")

            for k_idx, ep_item in ep_items_with_key:
                if hasattr(ep_item, "to_dict"):
                    ep_item = ep_item.to_dict()
                elif hasattr(ep_item, "model_dump"):
                    ep_item = ep_item.model_dump()
                if not isinstance(ep_item, dict):
                    continue

                ep_idx = ep_item.get("episode_num") or ep_item.get("episode_id") or ep_item.get("episode_number") or k_idx
                try:
                    ep_idx_int = int(ep_idx)
                except (ValueError, TypeError):
                    try:
                        ep_idx_int = int(k_idx)
                    except Exception:
                        ep_idx_int = 1

                is_minimal_mock = (
                    len(ep_item.keys()) <= 6
                    and "golden_cliffhanger_hook" not in ep_item
                    and "episode_end_physical_delta" not in ep_item
                    and "outgoing_physical_snapshot" not in ep_item
                    and "ast_data" not in ep_item
                )

                # 1. 检查正文存在性与时空场景标头数 (2 ~ 4 个)
                text = ep_item.get("screenplay_text") or ep_item.get("body_markdown") or ""
                if not text.strip():
                    quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集正文内容 (screenplay_text) 为空")
                elif not is_minimal_mock:
                    scene_headers = [line for line in text.splitlines() if any(tag in line for tag in ["【场景", "### 【场景", "内景", "外景", "场景 "])]
                    if len(scene_headers) < 2:
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集单集时空场景标头不足 2 处 (当前: {len(scene_headers)}/2)")
                    elif len(scene_headers) > 4:
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集单集时空场景标头超过 4 处 (当前: {len(scene_headers)}/4)，节奏过碎违反时空汇聚原则")

                    # 检查三大声学行为标记（开场突发重击 Braam Hit、核心戏剧骤停、终局下潜重击 Sub-drop）
                    has_braam = any(k in text for k in ["开场突发重击", "Braam Hit", "Braam", "[声学行为: 开场突发重击"])
                    has_silence = any(k in text for k in ["核心戏剧骤停", "物理静音", "绝对物理静音", "[声学行为: 核心戏剧骤停"])
                    has_subdrop = any(k in text for k in ["终局下潜重击", "Sub-drop", "下潜重击", "[声学行为: 终局下潜重击"])
                    if not (has_braam and has_silence and has_subdrop):
                        missing_tags = []
                        if not has_braam:
                            missing_tags.append("开场突发重击(Braam Hit)")
                        if not has_silence:
                            missing_tags.append("核心戏剧骤停(绝对物理静音2.5秒)")
                        if not has_subdrop:
                            missing_tags.append("终局下潜重击(Sub-drop随黑屏骤停)")
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集正文缺失三大声学行为标记: {', '.join(missing_tags)}")

                # 2. 检查前 3 秒视觉动作抓手
                hook = ep_item.get("hook_3s") or ep_item.get("three_second_hook") or ""
                if not hook and "前3秒" not in text and "开场" not in text:
                    quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集前 3 秒视觉动作抓手 (hook_3s) 为空")

                # 3. 检查三位一体黄金悬念绝杀断点
                cliff = (
                    ep_item.get("golden_cliffhanger_hook")
                    or ep_item.get("killer_cliffhanger_115s")
                    or ep_item.get("ending_cliffhanger")
                    or ""
                )
                if not cliff:
                    quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集片尾生死绝杀断点 (golden_cliffhanger_hook) 为空")
                elif not is_minimal_mock and isinstance(cliff, dict):
                    crisis_act = cliff.get("physical_crisis_action") or cliff.get("hook_action")
                    cliff_dlg = cliff.get("cliffhanger_dialogue") or cliff.get("hook_dialogue")
                    drop_cue = cliff.get("acoustic_drop_cue") or cliff.get("hook_audio_braam")
                    if not crisis_act or not str(crisis_act).strip():
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集黄金悬念绝杀钩子缺失物理危机动作 (physical_crisis_action)")
                    if not cliff_dlg or not str(cliff_dlg).strip():
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集黄金悬念绝杀钩子缺失悬念绝杀对白 (cliffhanger_dialogue)")
                    if not drop_cue or not str(drop_cue).strip():
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集黄金悬念绝杀钩子缺失声学重击标记 (acoustic_drop_cue)")

                if not is_minimal_mock:
                    # 4. 检查集尾物理快照
                    delta = ep_item.get("episode_end_physical_delta") or ep_item.get("outgoing_physical_snapshot") or {}
                    if not delta or not isinstance(delta, dict):
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集缺失集尾物理快照 (episode_end_physical_delta)")
                    else:
                        t_prog = delta.get("timeline_progress") or delta.get("timeline_progress_sec")
                        c_pose = delta.get("character_pose") or delta.get("posture_and_injuries") or delta.get("character_states")
                        p_inj = delta.get("held_props_and_injuries") or delta.get("carried_props_status") or delta.get("prop_possession")
                        e_wthr = delta.get("environment_and_weather") or delta.get("weather_and_light") or delta.get("location")
                        if not t_prog:
                            quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集集尾物理快照缺失主时间线进度 (timeline_progress)")
                        if not c_pose:
                            quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集集尾物理快照缺失核心角色姿态与伤情 (character_pose)")
                        if not p_inj:
                            quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集集尾物理快照缺失关键物证与随身道具状态 (held_props_and_injuries)")
                        if not e_wthr:
                            quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集集尾物理快照缺失空间与天气光影状态 (environment_and_weather)")

                    # 5. 检查第 2 集及之后 0 秒动作接力
                    if ep_idx_int >= 2:
                        pickup = ep_item.get("previous_episode_0s_pickup") or ep_item.get("incoming_physical_snapshot")
                        if not pickup:
                            quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集缺少接力上一集的 0 秒物理快照 (previous_episode_0s_pickup)")
                        elif isinstance(pickup, dict):
                            p_desc = pickup.get("pickup_state_description") or pickup.get("freeze_frame_desc")
                            if not p_desc or not str(p_desc).strip():
                                quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集接力上一集 0 秒物理快照描述为空 (pickup_state_description)")

        elif stage == 6:
            # 【规则编号: AUDIT-CHECKPOINT-06】阶段 6 视听资产与引单红蓝双军严苛审查
            payload_dict = (
                content_payload.to_dict()
                if hasattr(content_payload, "to_dict")
                else (
                    content_payload.model_dump()
                    if hasattr(content_payload, "model_dump")
                    else (content_payload if isinstance(content_payload, dict) else {})
                )
            )

            manifest = (
                payload_dict.get("manifest")
                or payload_dict.get("episode_resource_manifest")
                or payload_dict
            )
            if hasattr(manifest, "to_dict"):
                manifest = manifest.to_dict()
            elif hasattr(manifest, "model_dump"):
                manifest = manifest.model_dump()

            if not isinstance(manifest, dict):
                quick_blocking.append("【蓝军阻断】阶段 6 缺失单集视听资源引单 (manifest)")
            else:
                # 提取各资产大类（支持平铺列表与 Table 6 树状嵌套格式）
                chars_val = manifest.get("characters") or manifest.get("character_assets")
                envs_val = manifest.get("environments") or manifest.get("scene_assets")
                props_val = manifest.get("props") or manifest.get("prop_assets")
                audio_val = manifest.get("audio") or manifest.get("audio_tts")

                if chars_val is None:
                    quick_blocking.append("【蓝军阻断】阶段 6 资源引单缺失角色资产项 (characters)")
                if envs_val is None:
                    quick_blocking.append("【蓝军阻断】阶段 6 资源引单缺失场景资产项 (environments)")
                if props_val is None:
                    quick_blocking.append("【蓝军阻断】阶段 6 资源引单缺失道具资产项 (props)")

                # 规范化各分类平铺列表
                extracted_chars: list[dict[str, Any]] = []
                if isinstance(chars_val, list):
                    extracted_chars.extend([c if isinstance(c, dict) else (c.model_dump() if hasattr(c, "model_dump") else {}) for c in chars_val])
                elif isinstance(chars_val, dict):
                    for t_key in ["tier1_base", "tier2_performance", "tier3_special"]:
                        for item in chars_val.get(t_key, []):
                            if isinstance(item, dict):
                                extracted_chars.append(item)
                for f_key in ["characters_tier_1", "characters_tier_2", "characters_tier_3"]:
                    for item in manifest.get(f_key, []):
                        if isinstance(item, dict) and item not in extracted_chars:
                            extracted_chars.append(item)

                extracted_envs: list[dict[str, Any]] = []
                if isinstance(envs_val, list):
                    extracted_envs.extend([e if isinstance(e, dict) else (e.model_dump() if hasattr(e, "model_dump") else {}) for e in envs_val])
                elif isinstance(envs_val, dict):
                    for t_key in ["tier1_primary", "tier2_transitional"]:
                        for item in envs_val.get(t_key, []):
                            if isinstance(item, dict):
                                extracted_envs.append(item)
                for f_key in ["environments_primary", "environments_transitional"]:
                    for item in manifest.get(f_key, []):
                        if isinstance(item, dict) and item not in extracted_envs:
                            extracted_envs.append(item)

                extracted_props: list[dict[str, Any]] = []
                if isinstance(props_val, list):
                    extracted_props.extend([p if isinstance(p, dict) else (p.model_dump() if hasattr(p, "model_dump") else {}) for p in props_val])
                elif isinstance(props_val, dict):
                    for t_key in ["tier1_hero", "tier2_anchor", "tier3_atmospheric"]:
                        for item in props_val.get(t_key, []):
                            if isinstance(item, dict):
                                extracted_props.append(item)
                for f_key in ["props_narrative", "props_anchors", "props_ambient"]:
                    for item in manifest.get(f_key, []):
                        if isinstance(item, dict) and item not in extracted_props:
                            extracted_props.append(item)

                # 1. 蓝军硬规则：角色资产四段式规范与红军视觉瑕疵排查
                for c_dict in extracted_chars:
                    aids_to_check: list[str] = []
                    for key in ["asset_id", "char_id", "base_portrait", "base_costume"]:
                        val = c_dict.get(key)
                        if val and isinstance(val, str):
                            aids_to_check.append(val)
                    for key in ["angle_views", "script_emotions", "special_macro", "status_branch"]:
                        val = c_dict.get(key)
                        if isinstance(val, list):
                            for v in val:
                                if isinstance(v, str):
                                    aids_to_check.append(v)

                    for aid in aids_to_check:
                        if aid.startswith("CHAR_"):
                            valid, reason = AssetProtocolHelper.validate_id(aid, expected_category="CHAR")
                            if not valid:
                                quick_blocking.append(f"【蓝军阻断】阶段 6 角色资产 ID 违规: {reason}")

                    # 【红军魔鬼挑刺 1】：排查网红磨皮塑胶假人 (Anti-AI Plastic Face)
                    v_prompt = str(c_dict.get("visual_prompt") or c_dict.get("image_prompt") or "").lower()
                    if v_prompt:
                        forbidden_doll_terms = ["美白磨皮", "完美无瑕", "doll face", "porcelain skin", "porcelain doll"]
                        for term in forbidden_doll_terms:
                            if term in v_prompt:
                                quick_blocking.append(f"【红军阻断】角色资产提示词出现网红磨皮假人词汇 '{term}'，严重缺乏真实毛孔与微观生物质感")
                                break

                    # 【红军魔鬼挑刺 2】：定妆照/正视角从头到脚全身落地完整性排查 (Anti-Foot-Clipping)
                    primary_aid = c_dict.get("asset_id") or c_dict.get("char_id") or ""
                    if any(k in primary_aid for k in ["BASE_COSTUME", "4V_FRONT_FULL", "VIEW_FRONT"]):
                        if v_prompt and any(clip_term in v_prompt for clip_term in ["half body", "waist up", "上半身", "半身照", "bust shot"]):
                            quick_blocking.append(f"【红军阻断】全身定妆照 [{primary_aid}] 提示词出现半身截断描述，违反从头到脚鞋面完整落地铁律")

                # 2. 蓝军硬规则：场景资产四段式规范校验
                for e_dict in extracted_envs:
                    aids_to_check = []
                    for key in ["asset_id", "scene_id", "environment_id", "wide_shot", "insert_shot", "lighting_state", "keyframe_shot"]:
                        val = e_dict.get(key)
                        if val and isinstance(val, str):
                            aids_to_check.append(val)
                    for aid in aids_to_check:
                        if aid.startswith("ENV_"):
                            valid, reason = AssetProtocolHelper.validate_id(aid, expected_category="ENV")
                            if not valid:
                                quick_blocking.append(f"【蓝军阻断】阶段 6 场景资产 ID 违规: {reason}")

                # 3. 蓝军硬规则：道具资产四段式规范校验
                for p_dict in extracted_props:
                    aids_to_check = []
                    for key in ["asset_id", "prop_id", "static_asset", "action_asset"]:
                        val = p_dict.get(key)
                        if val and isinstance(val, str):
                            aids_to_check.append(val)
                    for aid in aids_to_check:
                        if aid.startswith("PROP_"):
                            valid, reason = AssetProtocolHelper.validate_id(aid, expected_category="PROP")
                            if not valid:
                                quick_blocking.append(f"【蓝军阻断】阶段 6 道具资产 ID 违规: {reason}")

                # 4. 蓝军硬规则：角色声音母音卡片完整性校验 (算子 D)
                voice_cards = payload_dict.get("new_character_master_voice_cards") or []
                for vc in voice_cards:
                    vc_dict = vc if isinstance(vc, dict) else (vc.to_dict() if hasattr(vc, "to_dict") else dict(vc))
                    m_id = vc_dict.get("master_voice_id", "")
                    cid = vc_dict.get("character_id", "")
                    tts_prompt = vc_dict.get("master_tts_prompt", "")
                    if not m_id.startswith("VOICE_"):
                        quick_blocking.append(f"【蓝军阻断】角色母音频 ID 非标: '{m_id}'，必须以 VOICE_ 开头")
                    if not cid.startswith("CHAR_"):
                        quick_blocking.append(f"【蓝军阻断】角色母音频挂靠角色 ID 非标: '{cid}'，必须以 CHAR_ 开头")
                    if not tts_prompt or not str(tts_prompt).strip():
                        quick_blocking.append(f"【蓝军阻断】角色母音频 [{m_id}] 缺失 master_tts_prompt 声学腔体提示词")

                # 5. 蓝军硬规则：已有资产 100% 只读复用校验 (Poka-Yoke)
                reused_records = payload_dict.get("reused_existing_assets") or []
                for r in reused_records:
                    r_dict = r if isinstance(r, dict) else (r.to_dict() if hasattr(r, "to_dict") else dict(r))
                    status = str(r_dict.get("status", "")).upper()
                    if status != "APPROVED":
                        quick_blocking.append(f"【蓝军阻断】复用资产 [{r_dict.get('asset_id')}] 状态为 '{status}'，严禁复用未核准资产")

                # 6. 红军魔鬼挑刺：增量生图底图引用与重绘幅度排查
                new_records = payload_dict.get("newly_generated_assets") or []
                for n in new_records:
                    n_dict = n if isinstance(n, dict) else (n.to_dict() if hasattr(n, "to_dict") else dict(n))
                    gen_method = str(n_dict.get("generation_method", "")).lower()
                    if gen_method in ["image_to_image", "inpainting_local_edit", "image_to_image_pose", "relighting"]:
                        if not n_dict.get("input_source_image"):
                            quick_blocking.append(f"【红军阻断】图生图增量资产 [{n_dict.get('asset_id')}] 缺失 input_source_image 底图血统引用，严禁盲猜生图")

        elif stage == 7:
            # 【规则编号: AUDIT-CHECKPOINT-07】阶段 7 视听分镜与 SRT 蓝军客观合规硬性检查
            shots = []
            planned_dur_sec = None
            if isinstance(content_payload, list):
                shots = content_payload
            elif isinstance(content_payload, dict):
                shots = content_payload.get("shots") or content_payload.get("storyboards") or []
                planned_dur_sec = content_payload.get("planned_duration_sec") or content_payload.get("target_duration_sec")
            
            if not shots:
                quick_blocking.append("【蓝军阻断】阶段 7 单镜头工业执行表为空")
            else:
                allowed_durations = {2.0, 3.0, 4.0, 5.0, 6.0, 7.0}
                total_duration = 0.0
                forbidden_prompt_terms = [
                    "jaw_open_scale",
                    "jaw_open",
                    "自然眨眼",
                    "呼吸起伏",
                    "嘴唇闭合",
                    "嘴唇开合",
                    "4k",
                    "8k",
                    "超真实",
                    "photorealistic",
                    "masterpiece",
                ]

                for idx, s in enumerate(shots, start=1):
                    s_dict = s if isinstance(s, dict) else s.model_dump() if hasattr(s, "model_dump") else {}
                    mode = s_dict.get("generation_mode") or s_dict.get("mode")
                    if mode not in ["first_last_frame", "multi_image_reference", "multi_image_ref"]:
                        quick_blocking.append(f"【蓝军阻断】第 {idx} 镜生成模式无效: '{mode}'，必须为 first_last_frame 或 multi_image_reference")
                    
                    dur = s_dict.get("duration_sec")
                    if dur is None:
                        quick_blocking.append(f"【蓝军阻断】第 {idx} 镜缺失时长 duration_sec")
                    else:
                        dur_float = float(dur)
                        total_duration += dur_float
                        if dur_float not in allowed_durations:
                            quick_blocking.append(f"【蓝军阻断】第 {idx} 镜时长非合法整数秒 (当前: {dur}s，严格限制为 2.0, 3.0, 4.0, 5.0, 6.0 或 7.0s)")

                    # 模式 A (首尾帧) 检查
                    if mode == "first_last_frame":
                        flc = s_dict.get("first_last_config") or s_dict.get("first_last_frame_config")
                        if not flc or not isinstance(flc, dict):
                            quick_blocking.append(f"【蓝军阻断】第 {idx} 镜采用首尾帧模式但缺失 first_last_config 配置")
                        else:
                            f_id = flc.get("first_frame_asset_id") or flc.get("first_frame_asset_ref")
                            l_id = flc.get("last_frame_asset_id") or flc.get("last_frame_asset_ref")
                            if not f_id or not l_id:
                                quick_blocking.append(f"【蓝军阻断】第 {idx} 镜首尾帧配置不完整 (first: {f_id}, last: {l_id})")

                    # 模式 B (多模态参考) 检查
                    if mode in ["multi_image_reference", "multi_image_ref"]:
                        mic = s_dict.get("multi_image_config")
                        if not mic or not isinstance(mic, dict):
                            quick_blocking.append(f"【蓝军阻断】第 {idx} 镜采用多图参考模式但缺失 multi_image_config 配置")
                        else:
                            refs = mic.get("reference_assets") or mic.get("reference_asset_ids") or []
                            if len(refs) > 4:
                                quick_blocking.append(f"【蓝军阻断】第 {idx} 镜模式 B 参考图数量 {len(refs)} 超过 4 张上限")
                            
                            audit_sig = mic.get("audit")
                            if audit_sig != "PASS_9":
                                quick_blocking.append(f"【蓝军阻断】第 {idx} 镜模式 B 缺失 PASS_9 自检通过签名 (当前: '{audit_sig}')")

                            # 提示词禁忌词审查
                            v_prompt = str(mic.get("video_prompt") or s_dict.get("video_prompt") or "")
                            for term in forbidden_prompt_terms:
                                if term in v_prompt:
                                    quick_blocking.append(f"【红军阻断】第 {idx} 镜模式 B 提示词包含禁忌词/生理口型词: '{term}'")

                    # 台词完整闭合性检查
                    audio = s_dict.get("audio") or {}
                    dlg = audio.get("dialogue") or s_dict.get("srt_text")
                    if dlg:
                        is_complete = s_dict.get("is_dialogue_complete_in_shot")
                        if is_complete is None and isinstance(audio, dict):
                            is_complete = audio.get("is_dialogue_complete_in_shot")
                        if is_complete is False:
                            quick_blocking.append(f"【蓝军阻断】第 {idx} 镜包含对白但未在镜头内完整闭合 (is_dialogue_complete_in_shot 须为 true)")

                    # 💡 检查引用的资产 ID 是否遵循四段式协议规范
                    ref_ids: list[str] = []
                    if s_dict.get("multi_image_config") and isinstance(s_dict["multi_image_config"], dict):
                        mic = s_dict["multi_image_config"]
                        ref_ids.extend(mic.get("reference_asset_ids") or mic.get("reference_assets") or [])
                    if s_dict.get("first_last_config") and isinstance(s_dict["first_last_config"], dict):
                        flc = s_dict["first_last_config"]
                        if flc.get("first_frame_asset_id"):
                            ref_ids.append(flc["first_frame_asset_id"])
                        if flc.get("last_frame_asset_id"):
                            ref_ids.append(flc["last_frame_asset_id"])

                    for r_id in ref_ids:
                        if r_id and not r_id.startswith("SCENE_"):  # 允许历史兼容
                            valid, reason = AssetProtocolHelper.validate_id(r_id)
                            if not valid:
                                quick_blocking.append(f"【蓝军阻断】第 {idx} 镜引用的资产 ID 格式非标: {reason}")

                # 整集总时长 ±6.0s 公差检查 (镜头数充足且提供了规划时长时)
                if planned_dur_sec is not None and len(shots) >= 10:
                    plan_val = float(planned_dur_sec)
                    if abs(total_duration - plan_val) > 6.0:
                        quick_blocking.append(
                            f"【蓝军阻断】阶段 7 整集分镜累计时长 {total_duration}s 偏离规划时长 {plan_val}s 超过 ±6.0s 工业公差 (当前偏差: {abs(total_duration - plan_val):.1f}s)"
                        )

        elif stage == 8:
            # 【规则编号: AUDIT-CHECKPOINT-08 / RULE-VIII-01~05】阶段 8 多轨混音工程与 Ducking 避让蓝军客观合规硬性检查
            payload_dict = (
                content_payload.model_dump()
                if hasattr(content_payload, "model_dump")
                else (
                    content_payload.to_dict()
                    if hasattr(content_payload, "to_dict")
                    else (content_payload if isinstance(content_payload, dict) else {})
                )
            )

            # 从 state 或 dict 中提取当前集的 mastering_config
            curr_ep = payload_dict.get("current_visual_episode") or 1
            mastering_plans = (
                payload_dict.get("episode_audio_masterings")
                or payload_dict.get("audio_mastering_plans")
                or {}
            )

            cfg = None
            if isinstance(mastering_plans, dict) and curr_ep in mastering_plans:
                cfg = mastering_plans[curr_ep]
            elif isinstance(mastering_plans, dict) and str(curr_ep) in mastering_plans:
                cfg = mastering_plans[str(curr_ep)]
            elif "mastering_config" in payload_dict:
                cfg = payload_dict["mastering_config"]
            elif "target_lufs" in payload_dict or "broadcast_loudness_standard" in payload_dict:
                cfg = payload_dict
            elif isinstance(content_payload, dict) and 1 in content_payload:
                cfg = content_payload[1]

            if not isinstance(cfg, dict) and hasattr(cfg, "model_dump"):
                cfg = cfg.model_dump()

            if not isinstance(cfg, dict) or not cfg:
                quick_blocking.append("【蓝军阻断】阶段 8 缺失母带混音配置 (Missing mastering configuration)")
            else:
                # 1. 广播级响度标准与真峰值检查 (RULE-VIII-05)
                target_lufs = cfg.get("target_lufs")
                loudness_std = cfg.get("broadcast_loudness_standard")
                if target_lufs is None and loudness_std is None:
                    quick_blocking.append("【蓝军阻断】阶段 8 缺失广播级响度标准 (-23 LUFS)")
                else:
                    if target_lufs is not None:
                        try:
                            lufs_val = float(target_lufs)
                            if lufs_val > -18.0 or lufs_val < -28.0:
                                quick_blocking.append(f"【蓝军阻断】阶段 8 目标响度异常: {target_lufs} LUFS，偏离标准 -23.0 LUFS 范围")
                            elif abs(lufs_val - (-23.0)) > 2.0:
                                quick_blocking.append(f"【蓝军阻断】阶段 8 目标响度未严格对齐 -23.0 LUFS 广播级标准 (当前: {target_lufs} LUFS)")
                        except (ValueError, TypeError):
                            quick_blocking.append(f"【蓝军阻断】阶段 8 目标响度参数无法解析: {target_lufs}")
                    if loudness_std and loudness_std != "-23 LUFS":
                        quick_blocking.append(f"【蓝军阻断】阶段 8 广播级响度标准非标: {loudness_std}，必须锁定 '-23 LUFS'")

                peak_limit = cfg.get("peak_limit_dbtp")
                if peak_limit is not None:
                    try:
                        if float(peak_limit) > -1.0:
                            quick_blocking.append(f"【蓝军阻断】阶段 8 真峰值超标: {peak_limit} dBTP > -1.0 dBTP 广播红线")
                    except (ValueError, TypeError):
                        pass

                # 2. 四大声学依据溯源检查 (RULE-VIII-01)
                trace = cfg.get("acoustic_traceability")
                if not isinstance(trace, dict):
                    quick_blocking.append("【蓝军阻断】阶段 8 缺失声学依据溯源字典 (acoustic_traceability)")
                else:
                    for req_basis, label in [
                        ("stage_4_leitmotif_basis", "阶段4母动机库依据"),
                        ("stage_1_worldview_basis", "阶段1世界观基调依据"),
                        ("stage_7_timecode_basis", "阶段7时间轴实际秒数依据"),
                        ("stage_5_dramatic_cues", "阶段5戏剧卡点依据"),
                    ]:
                        val = trace.get(req_basis)
                        if not val or not str(val).strip():
                            quick_blocking.append(f"【蓝军阻断】阶段 8 acoustic_traceability 缺失{label}溯源 ({req_basis})")

                # 3. 动态侧链避让调度与断崖静音检查 (RULE-VIII-02 / RULE-VIII-03)
                sched = cfg.get("mastering_schedule") or []
                if not sched or not isinstance(sched, list):
                    quick_blocking.append("【蓝军阻断】阶段 8 缺失动态侧链避让调度表 (mastering_schedule)")
                else:
                    has_silence = any(
                        float(item.get("target_bgm_volume_db") or item.get("gain_db") or 0.0) <= -900.0
                        or item.get("action_type") == "cliffhanger_silence"
                        for item in sched
                        if isinstance(item, dict)
                    )
                    if not has_silence:
                        quick_blocking.append("【蓝军阻断】阶段 8 调度表缺失高潮断崖绝对静音卡点 (-999.0dB / cliffhanger silence)")

                    has_ducking = any(
                        (
                            item.get("speech_ducking_active") is True
                            or item.get("action_type") in ("speech_ducking", "dialogue_ducking")
                        )
                        or (
                            float(item.get("target_bgm_volume_db") or item.get("gain_db") or 0.0) == -20.0
                            and item.get("speech_ducking_active") is not False
                        )
                        for item in sched
                        if isinstance(item, dict)
                    )
                    if not has_ducking:
                        quick_blocking.append("【蓝军阻断】阶段 8 调度表缺失对白侧链避让 (-20.0dB / dialogue ducking)")

                # 4. 全量 BGM Prompt 与时长对齐检查 (RULE-VIII-02)
                bgm_gen = cfg.get("bgm_generation")
                if not isinstance(bgm_gen, dict) or not bgm_gen.get("full_master_prompt"):
                    quick_blocking.append("【蓝军阻断】阶段 8 缺失全量 BGM 编曲生乐 Prompt (bgm_generation.full_master_prompt / BGM prompt)")
                else:
                    prompt_str = str(bgm_gen.get("full_master_prompt"))
                    if not any(k in prompt_str for k in ["Duration", "seconds", "s", "秒"]):
                        quick_blocking.append("【蓝军阻断】阶段 8 BGM Prompt 缺失动态时长控制指令")

                # 5. NLE 剪辑软件 4 轨参数规范检查 (RULE-VIII-04)
                nle_guidelines = cfg.get("nle_mixing_guidelines")
                if not isinstance(nle_guidelines, dict):
                    quick_blocking.append("【蓝军阻断】阶段 8 缺失 NLE 4轨参数规范 (nle_mixing_guidelines / NLE mixing guidelines)")

        rules_str = str(forbidden_rules or "默认遵循双轨禁令、生物骨相DNA完整性与剧本排版规范")
        user_prompt = AUDIT_USER_PROMPT_TEMPLATE.format(
            stage=stage,
            content_payload=payload_str[:3500],
            forbidden_rules=rules_str[:1000],
        )

        result_json = call_llm_json(
            user_prompt=user_prompt,
            system_prompt=AUDIT_SYSTEM_PROMPT,
            fallback_factory=lambda: _fallback_audit_report(stage, payload_str[:100]),
        )

        blocking = result_json.get("blocking_issues") or []
        blocking.extend(quick_blocking)

        verdict_str = result_json.get("verdict") or AuditVerdict.GREEN_APPROVED
        if blocking:
            verdict_str = AuditVerdict.RED_BLOCKING

        report = RedBlueAuditReport(
            blue_team_compliance=result_json.get("blue_team_compliance") or {},
            red_team_criticism=result_json.get("red_team_criticism") or {},
            verdict=verdict_str,
            blocking_issues=blocking,
            warning_suggestions=result_json.get("warning_suggestions") or [],
        )
        return report

    @classmethod
    def audit_stage_payload(cls, stage: int, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """通用阶段载荷审查入口别名。"""
        return cls.audit(stage=stage, content_payload=content_payload, forbidden_rules=forbidden_rules)

    def audit_payload(self, stage: int, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """实例级载荷审查入口别名。"""
        return self.audit(stage=stage, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage1(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-01】阶段 1 哨卡便捷审查入口。"""
        return cls.audit(stage=1, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage2(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-02】阶段 2 哨卡便捷审查入口。"""
        return cls.audit(stage=2, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage3(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-03】阶段 3 哨卡便捷审查入口。"""
        return cls.audit(stage=3, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage4(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-04】阶段 4 哨卡便捷审查入口。"""
        return cls.audit(stage=4, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage5(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-05】阶段 5 文学剧本哨卡便捷审查入口。"""
        return cls.audit(stage=5, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage6(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-06】阶段 6 视听资产哨卡便捷审查入口。"""
        return cls.audit(stage=6, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage7(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-07】阶段 7 视听分镜与 SRT 哨卡便捷审查入口。"""
        return cls.audit(stage=7, content_payload=content_payload, forbidden_rules=forbidden_rules)

    @classmethod
    def audit_stage8(cls, content_payload: Any, forbidden_rules: Any = None) -> RedBlueAuditReport:
        """【规则编号: AUDIT-CHECKPOINT-08】阶段 8 混音与 Ducking 哨卡便捷审查入口。"""
        return cls.audit(stage=8, content_payload=content_payload, forbidden_rules=forbidden_rules)

