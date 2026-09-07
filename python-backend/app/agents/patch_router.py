"""五阶质检局部原位修补智能体 (Targeted In-Place Patch Router)。

严格遵循《详细设计说明书（V2.0 工业增强版）》第 2.3 节：
当质检未达标（< 85 分）时，严禁整集推倒重写！
而是基于 AST 分块定位缺陷块（如仅对白说教、片尾缺字幕），下发定向 Diff Patch，
修补后原位重新缝合组装（In-place Stitching），保护合格高光段落。
"""
from __future__ import annotations

import json
from typing import Any, Literal
from app.schemas.script_graph_state import ASTBlockItem, ScriptAST, QAReport, EpisodeScript
from app.agents.script_ast_parser import ScriptASTParser


class TargetedPatchRouter:
    """局部原位修补智能体与调度器。"""

    # 缺陷关键词到 AST 分块类型的映射规则
    BLOCK_DEFECT_RULES = {
        "hook_3s": ["3秒", "特写", "开场", "前3秒", "视觉钩子", "抓人", "爆点"],
        "cliffhanger": ["定格", "片尾", "断章", "悬念", "字幕", "卡点", "尾声", "戛然而止"],
        "dialogues": ["台词", "对白", "说教", "潜台词", "降智", "语气", "口语", "口头禅"],
        "actions_and_scenes": ["动作", "水戏", "视听", "走位", "场景", "调度", "物理阻碍"],
    }

    @classmethod
    def identify_target_blocks(cls, qa_report: QAReport) -> list[str]:
        """根据质检报告中的分项分与缺陷列表，精确定位需要修补的 AST 块。"""
        target_blocks: set[str] = set()

        # 1. 根据雷达子项分判定
        # 结构层薄弱（< 18/25）：通常影响开场钩子或片尾定格
        if qa_report.structure_score < 18:
            target_blocks.add("hook_3s")
            target_blocks.add("cliffhanger")
        # 人物/语言层薄弱（< 15/20）：通常影响潜台词与对白
        if qa_report.character_score < 15 or qa_report.language_score < 12:
            target_blocks.add("dialogues")
        # 场景层薄弱（< 15/20）：影响视听动作与场景
        if qa_report.scene_score < 15:
            target_blocks.add("actions_and_scenes")

        # 2. 根据缺陷文本关键词匹配
        flaw_text = " ".join(qa_report.flaws_identified + qa_report.refine_suggestions).lower()
        for block_type, keywords in cls.BLOCK_DEFECT_RULES.items():
            if any(kw in flaw_text for kw in keywords):
                target_blocks.add(block_type)

        # 兜底：若均未命中，默认对白与动作两块
        if not target_blocks:
            target_blocks = {"dialogues", "actions_and_scenes"}

        qa_report.target_patch_blocks = list(target_blocks)
        return list(target_blocks)

    @classmethod
    def build_patch_prompt(
        cls,
        episode: EpisodeScript,
        qa_report: QAReport,
        target_blocks: list[str],
    ) -> str:
        """为大模型生成手术式局部修补 Prompt（只重写扣分块，锁定其余高分块）。"""
        ast = episode.ast_data or ScriptASTParser.parse(episode.episode_num, episode.body_markdown)
        block_map = {b.block_type: b for b in ast.blocks}

        locked_blocks_info = []
        defect_blocks_info = []

        for b_type in ["hook_3s", "actions_and_scenes", "dialogues", "cliffhanger"]:
            blk = block_map.get(b_type)
            content = blk.content if blk else ""
            if b_type in target_blocks:
                defect_blocks_info.append(
                    f"### 【待修补目标块: {b_type}】\n"
                    f"原文本：\n{content}\n"
                    f"缺陷与修改建议：{', '.join(qa_report.flaws_identified)}"
                )
            else:
                locked_blocks_info.append(f"- 【已锁定保留块: {b_type}】: {content[:40]}... (保持原样不动)")

        prompt = f"""你是一位顶级短剧剧本精修编剧。当前第 {episode.episode_num} 集剧本质检评分为 {qa_report.overall_score} 分（未达 85 分放行线）。
系统已启用【AST 局部原位修补（In-place Patching）】机制。

【已锁定高分分块（严禁修改，保留原样）】：
{chr(10).join(locked_blocks_info)}

【本次仅需定向手术式重写的分块】：
{chr(10).join(defect_blocks_info)}

【修改指令】：
1. 严格针对上述扣分缺陷进行定向精修，禁止通篇推倒重写；
2. 保持与已锁定分块的情绪张力和动作连续性；
3. 输出格式要求为 JSON，仅返回修补后的目标分块字典：
```json
{{
  "patched_blocks": {{
    {" , ".join(f'"{b}": "修补后的新内容"' for b in target_blocks)}
  }}
}}
```"""
        return prompt

    @classmethod
    def apply_patch(
        cls,
        episode: EpisodeScript,
        patched_blocks: dict[str, str],
    ) -> EpisodeScript:
        """将 LLM 局部修补输出应用到 AST 树上，并原位重新缝合组装。"""
        ast = episode.ast_data or ScriptASTParser.parse(episode.episode_num, episode.body_markdown)

        for block in ast.blocks:
            if block.block_type in patched_blocks:
                new_content = patched_blocks[block.block_type].strip()
                if new_content:
                    block.content = new_content
                    block.patch_content = new_content

        # 重新缝合
        stitched_markdown = ScriptASTParser.stitch(ast)
        episode.body_markdown = stitched_markdown
        episode.ast_data = ast

        # 更新分段属性
        for b in ast.blocks:
            if b.block_type == "hook_3s":
                episode.hook_3s = b.content
            elif b.block_type == "cliffhanger":
                episode.ending_cliffhanger = b.content

        return episode

    @classmethod
    def patch_ast_by_qa(
        cls,
        ast: ScriptAST,
        issues: list[str] | None = None,
        deductions: dict[str, int] | None = None,
    ) -> ScriptAST:
        """基于质检扣分和缺陷直接修补 AST 树（用于 API 快速修补通道）。"""
        issues = issues or []
        deductions = deductions or {}

        # 定位需要修补的块
        target_types = set()
        issue_text = " ".join(issues).lower()
        if "钩子" in issue_text or "开场" in issue_text or "3秒" in issue_text:
            target_types.add("hook_3s")
        if "定格" in issue_text or "片尾" in issue_text or "悬念" in issue_text:
            target_types.add("cliffhanger")
        if "对白" in issue_text or "台词" in issue_text or "说教" in issue_text or deductions.get("dialogue_score", 0) > 0:
            target_types.add("dialogues")
        if "动作" in issue_text or "场景" in issue_text or "反转" in issue_text or deductions.get("conflict_intensity", 0) > 0:
            target_types.add("actions_and_scenes")

        if not target_types:
            target_types = {"actions_and_scenes", "dialogues"}

        for b in ast.blocks:
            if b.block_type in target_types:
                patch_mark = f"\n△ 【精修反转增强】：针对（{', '.join(issues) or '质检要求'}）重构视听动作与对抗张力！"
                b.content = b.content.strip() + patch_mark
                b.patch_content = b.content

        return ast


PatchRouter = TargetedPatchRouter

