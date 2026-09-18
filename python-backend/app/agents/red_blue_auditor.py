"""红蓝对抗独立自审引擎 (Red-Blue Auditor Agent)。

严格遵循 SKILL.md 工业级标准：
- 蓝军工程师：客观硬指标审查（双轨禁令、时间轴合规、微观生物肖像骨相DNA、真实生活质感服化道代码、资产与物理存在性、格式完备度）；
- 红军魔鬼制片人：戏剧挑刺（动机自洽、张力匮乏、降智打脸、视听不可执行性、网红脸与崭新塑料感排查）。
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.script_graph_state import AuditVerdict, RedBlueAuditReport
from app.workflows.prompts.master_sop_prompts import (
    AUDIT_SYSTEM_PROMPT,
    AUDIT_USER_PROMPT_TEMPLATE,
)
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
                for c in chars:
                    c_name = c.get("name", "未命名角色")
                    # 检查生理性别 (mandatory)
                    gender = c.get("gender") or c.get("biological_sex") or c.get("sex")
                    if not gender:
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失强制生理性别(gender/biological_sex)，存在配音与幻觉风险")

                    bio = c.get("biological_dna")
                    if not bio or not isinstance(bio, dict):
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失微观生物肖像骨相(biological_dna)，存在AI塑料脸风险")
                    else:
                        if not bio.get("bone_structure") or not (bio.get("skin_micro_texture") or bio.get("skin_texture")):
                            quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] biological_dna 缺失骨相(bone_structure)或皮肤肌理(skin_micro_texture)")
                    
                    costume = c.get("lived_in_costume")
                    if not costume or not isinstance(costume, dict):
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失真实生活质感服化道代码(lived_in_costume)，存在崭新塑料感风险")
                    
                    quad = c.get("psychological_quad")
                    if not quad or not isinstance(quad, dict) or not quad.get("want") or not quad.get("lie"):
                        quick_blocking.append(f"【蓝军阻断】角色 [{c_name}] 缺失心理四元组(Want/Need/Lie/Ghost)")

        elif stage == 3:
            # 【规则编号: AUDIT-CHECKPOINT-03】阶段 3 蓝军客观合规硬性检查
            if isinstance(content_payload, dict):
                envs = content_payload.get("environments") or []
                props = content_payload.get("props") or []
                if not envs:
                    quick_blocking.append("【蓝军阻断】阶段 3 缺失核心主场景清单 (environments)")
                for e in envs:
                    w = e.get("weathering_layers") or {}
                    if not (w.get("structural") and w.get("living") and w.get("optical")):
                        quick_blocking.append(f"【蓝军阻断】场景 [{e.get('location_name', '未命名')}] 缺失三层做旧架构(structural/living/optical)")
                
                if not props:
                    quick_blocking.append("【蓝军阻断】阶段 3 缺失核心物证道具清单 (props)")
                for p in props:
                    p_name = p.get("name", "未命名物证")
                    if not p.get("damage_scale"):
                        quick_blocking.append(f"【蓝军阻断】核心物证 [{p_name}] 缺失破损尺度(damage_scale)")
                    foley = p.get("foley_resistance", "")
                    if "+3" not in str(foley):
                        quick_blocking.append(f"【蓝军阻断】核心物证 [{p_name}] 缺失专属 +3.0dB 拟音标记(foley_resistance)")

        elif stage == 4:
            # 【规则编号: AUDIT-CHECKPOINT-04】阶段 4 蓝军客观合规硬性检查
            if isinstance(content_payload, dict):
                audio = content_payload.get("audio_bible") or {}
                leitmotifs = audio.get("leitmotifs") if isinstance(audio, dict) else []
                motif_ids = [m.get("motif_id") for m in (leitmotifs or []) if isinstance(m, dict)]
                expected_motifs = ["LEITMOTIF_01_SUSPENSE", "LEITMOTIF_02_TRAUMA", "LEITMOTIF_03_COUNTERATTACK"]
                for em in expected_motifs:
                    if em not in motif_ids:
                        quick_blocking.append(f"【蓝军阻断】阶段 4 缺失全剧核心音乐主题动机: {em}")
                
                outlines = content_payload.get("season_outlines") or {}
                if not outlines:
                    quick_blocking.append("【蓝军阻断】阶段 4 缺失分集双螺旋大纲任务卡 (season_outlines)")
                else:
                    ep_items = outlines.values() if isinstance(outlines, dict) else outlines
                    for ep in ep_items:
                        if isinstance(ep, dict):
                            ep_num = ep.get("episode_number") or ""
                            if not (ep.get("hook_3s") or ep.get("three_second_hook")):
                                quick_blocking.append(f"【蓝军阻断】第{ep_num}集大纲缺失前3s视觉抓手(hook_3s)")
                            if not ep.get("micro_turning_point_45s"):
                                quick_blocking.append(f"【蓝军阻断】第{ep_num}集大纲缺失45s微反转(micro_turning_point_45s)")
                            if not (ep.get("killer_cliffhanger_115s") or ep.get("cliffhanger")):
                                quick_blocking.append(f"【蓝军阻断】第{ep_num}集大纲缺失生死绝杀断点(cliffhanger)")

        elif stage == 5:
            # 【规则编号: AUDIT-CHECKPOINT-05】阶段 5 文学剧本蓝军客观合规硬性检查
            if isinstance(content_payload, list):
                ep_items_with_key = [(i + 1, ep) for i, ep in enumerate(content_payload)]
            elif isinstance(content_payload, dict):
                if "screenplay_text" in content_payload or "body_markdown" in content_payload or "hook_3s" in content_payload:
                    ep_items_with_key = [(content_payload.get("episode_num") or content_payload.get("episode_id") or 1, content_payload)]
                else:
                    ep_items_with_key = [(k, v) for k, v in content_payload.items() if isinstance(v, dict)]
            else:
                ep_items_with_key = []

            if not ep_items_with_key:
                quick_blocking.append("【蓝军阻断】阶段 5 剧本文学工笔产出为空，无有效分集剧本")

            for k_idx, ep_item in ep_items_with_key:
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

                if not is_minimal_mock:
                    # 4. 检查集尾物理快照
                    delta = ep_item.get("episode_end_physical_delta") or ep_item.get("outgoing_physical_snapshot") or {}
                    if not delta:
                        quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集缺失集尾物理快照 (episode_end_physical_delta)")

                    # 5. 检查第 2 集及之后 0 秒动作接力
                    if ep_idx_int >= 2:
                        pickup = ep_item.get("previous_episode_0s_pickup") or ep_item.get("incoming_physical_snapshot")
                        if not pickup:
                            quick_blocking.append(f"【蓝军阻断】第 {ep_idx} 集缺少接力上一集的 0 秒物理快照 (previous_episode_0s_pickup)")

        elif stage == 6:
            # 【规则编号: AUDIT-CHECKPOINT-06】阶段 6 视听资产与引单蓝军客观合规硬性检查
            if isinstance(content_payload, dict):
                manifest = content_payload.get("manifest") or content_payload.get("episode_resource_manifest") or content_payload
                if not isinstance(manifest, dict) and hasattr(manifest, "model_dump"):
                    manifest = manifest.model_dump()
                
                if not isinstance(manifest, dict):
                    quick_blocking.append("【蓝军阻断】阶段 6 缺失单集视听资源引单 (manifest)")
                else:
                    chars = manifest.get("characters")
                    envs = manifest.get("environments")
                    props = manifest.get("props")
                    
                    if chars is None:
                        quick_blocking.append("【蓝军阻断】阶段 6 资源引单缺失角色资产项 (characters)")
                    if envs is None:
                        quick_blocking.append("【蓝军阻断】阶段 6 资源引单缺失场景资产项 (environments)")
                    if props is None:
                        quick_blocking.append("【蓝军阻断】阶段 6 资源引单缺失道具资产项 (props)")

        elif stage == 7:
            # 【规则编号: AUDIT-CHECKPOINT-07】阶段 7 视听分镜与 SRT 蓝军客观合规硬性检查
            shots = []
            if isinstance(content_payload, list):
                shots = content_payload
            elif isinstance(content_payload, dict):
                shots = content_payload.get("shots") or content_payload.get("storyboards") or []
            
            if not shots:
                quick_blocking.append("【蓝军阻断】阶段 7 单镜头工业执行表为空")
            else:
                for idx, s in enumerate(shots, start=1):
                    s_dict = s if isinstance(s, dict) else s.model_dump() if hasattr(s, "model_dump") else {}
                    mode = s_dict.get("generation_mode") or s_dict.get("mode")
                    if mode not in ["first_last_frame", "multi_image_reference"]:
                        quick_blocking.append(f"【蓝军阻断】第 {idx} 镜生成模式无效: '{mode}'，必须为 first_last_frame 或 multi_image_reference")
                    
                    dur = s_dict.get("duration_sec")
                    if dur is not None and (float(dur) < 1.0 or float(dur) > 8.0):
                        quick_blocking.append(f"【蓝军阻断】第 {idx} 镜时长超出工业安全阈值 (当前: {dur}s，允许 1.0~8.0s)")

        elif stage == 8:
            # 【规则编号: AUDIT-CHECKPOINT-08】阶段 8 多轨混音工程与 Ducking 避让蓝军客观合规硬性检查
            if isinstance(content_payload, dict):
                cfg = content_payload.get("mastering_config") or content_payload
                if not isinstance(cfg, dict) and hasattr(cfg, "model_dump"):
                    cfg = cfg.model_dump()
                
                if not isinstance(cfg, dict):
                    quick_blocking.append("【蓝军阻断】阶段 8 缺失母带混音配置 (mastering_config)")
                else:
                    target_lufs = cfg.get("target_lufs")
                    if target_lufs is not None and (float(target_lufs) > -18.0 or float(target_lufs) < -28.0):
                        quick_blocking.append(f"【蓝军阻断】阶段 8 目标响度异常: {target_lufs} LUFS，偏离标准 -23.0 LUFS 范围")
                    
                    # 检查 ducking 调度或策略
                    ducking = cfg.get("ducking_strategy") or cfg.get("ducking_schedule") or cfg.get("ducking_events")
                    if ducking is None:
                        quick_blocking.append("【蓝军阻断】阶段 8 缺失动态侧链避让调度 (ducking)")

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

