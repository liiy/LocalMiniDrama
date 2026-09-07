"""短剧视听正文 AST 结构化分块解析器与缝合器 (Script AST Parser & Stitcher)。

严格对齐《短剧剧本·全流程工业化创作提示词（升级增强版）》正文排版规范：
将单集正文 Markdown 解析为 4 个结构分块：
1. hook_3s: 前3秒视觉特写与强钩子
2. actions_and_scenes: 核心视听动作与场景调度
3. dialogues: 潜台词拉扯与情绪交锋对白
4. cliffhanger: 片尾定格与悬念字幕

具备双层容错机制（正则精准切片 + 关键词启发式兜底），确保格式轻微漂移时永不崩溃。
"""
from __future__ import annotations

import re
from typing import Literal
from app.schemas.script_graph_state import ASTBlockItem, ScriptAST


class ScriptASTParser:
    """视听正文 AST 结构化解析器。"""

    # 正则规则匹配
    CLIFFHANGER_PATTERNS = [
        re.compile(r"(【片尾定格(?:与悬念钩子)?】.*?$)", re.DOTALL | re.IGNORECASE),
        re.compile(r"(\[片尾定格.*?$)", re.DOTALL | re.IGNORECASE),
        re.compile(r"(△\s*特写：.*?（定格）.*?$)", re.DOTALL | re.IGNORECASE),
    ]

    HOOK_3S_PATTERNS = [
        re.compile(r"(△\s*开场特写[^\n]*\n.*?)(?=\n(?:△|[^\n]+[（\(][^\)]*[）\)]|【)|\Z)", re.DOTALL),
        re.compile(r"(前3秒[^\n]*\n.*?)(?=\n(?:△|[^\n]+[（\(][^\)]*[）\)]|【)|\Z)", re.DOTALL),
        re.compile(r"(△\s*特写[^\n]*\n.*?)(?=\n(?:△|[^\n]+[（\(][^\)]*[）\)]|【)|\Z)", re.DOTALL),
    ]

    @classmethod
    def parse(cls, episode_num: int, markdown_text: str) -> ScriptAST:
        """将正文 Markdown 解析为 4 个 AST 结构分块。"""
        raw_text = markdown_text.strip()
        if not raw_text:
            return ScriptAST(
                episode_num=episode_num,
                blocks=[
                    ASTBlockItem(block_type="hook_3s", title="前3秒特写钩子", content=""),
                    ASTBlockItem(block_type="actions_and_scenes", title="核心动作与场景", content=""),
                    ASTBlockItem(block_type="dialogues", title="潜台词拉扯对白", content=""),
                    ASTBlockItem(block_type="cliffhanger", title="片尾定格与悬念", content=""),
                ],
                raw_markdown="",
            )

        # 1. 提取片尾定格 (cliffhanger)
        cliffhanger_content = ""
        body_without_cliffhanger = raw_text

        for pattern in cls.CLIFFHANGER_PATTERNS:
            match = pattern.search(raw_text)
            if match:
                cliffhanger_content = match.group(1).strip()
                body_without_cliffhanger = raw_text[: match.start()].strip()
                break

        # 2. 提取前3秒特写钩子 (hook_3s)
        hook_3s_content = ""
        body_middle = body_without_cliffhanger

        for pattern in cls.HOOK_3S_PATTERNS:
            match = pattern.search(body_without_cliffhanger)
            if match:
                hook_3s_content = match.group(1).strip()
                # 剩余主体部分
                body_middle = (
                    body_without_cliffhanger[: match.start()] + body_without_cliffhanger[match.end() :]
                ).strip()
                break

        # 3. 区分中间主体的动作 (actions_and_scenes) 与 对白 (dialogues)
        action_lines: list[str] = []
        dialogue_lines: list[str] = []

        # 识别对白行规则：角色名（情绪/动作）：台词内容
        dialogue_pattern = re.compile(r"^([\u4e00-\u9fa5a-zA-Z0-9·_]+)\s*[（\(](.*?)[）\)]\s*[：:]\s*(.*)$")
        simple_dialogue_pattern = re.compile(r"^([\u4e00-\u9fa5a-zA-Z0-9·_]{2,8})\s*[：:]\s*(.*)$")

        lines = body_middle.split("\n")
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("△") or "【场景】" in line_str or "【人物】" in line_str or "【道具】" in line_str:
                action_lines.append(line_str)
            elif dialogue_pattern.match(line_str) or simple_dialogue_pattern.match(line_str):
                dialogue_lines.append(line_str)
            else:
                # 默认为动作/场景叙述
                action_lines.append(line_str)

        actions_content = "\n".join(action_lines).strip()
        dialogues_content = "\n".join(dialogue_lines).strip()

        # 兜底：若前3秒未显式匹配出，提取第一句动作作为 hook_3s
        if not hook_3s_content and action_lines:
            hook_3s_content = action_lines[0]
            actions_content = "\n".join(action_lines[1:]).strip()

        blocks = [
            ASTBlockItem(block_type="hook_3s", title="前3秒特写钩子", content=hook_3s_content),
            ASTBlockItem(block_type="actions_and_scenes", title="核心动作与场景", content=actions_content),
            ASTBlockItem(block_type="dialogues", title="潜台词拉扯对白", content=dialogues_content),
            ASTBlockItem(block_type="cliffhanger", title="片尾定格与悬念", content=cliffhanger_content),
        ]

        return ScriptAST(episode_num=episode_num, blocks=blocks, raw_markdown=raw_text)

    @classmethod
    def parse_to_ast(cls, markdown_text: str, episode_num: int = 1) -> ScriptAST:
        """parse 的便利别名方法。"""
        return cls.parse(episode_num=episode_num, markdown_text=markdown_text)

    @classmethod
    def stitch(cls, ast: ScriptAST) -> str:
        """将 4 个 AST 结构块原位重新缝合为标准的 Markdown 剧本文本。"""
        block_map: dict[str, str] = {b.block_type: b.content for b in ast.blocks}

        hook_3s = block_map.get("hook_3s", "").strip()
        actions = block_map.get("actions_and_scenes", "").strip()
        dialogues = block_map.get("dialogues", "").strip()
        cliffhanger = block_map.get("cliffhanger", "").strip()

        sections: list[str] = []
        if hook_3s:
            sections.append(hook_3s)
        if actions:
            sections.append(actions)
        if dialogues:
            sections.append(dialogues)
        if cliffhanger:
            sections.append(cliffhanger)

        stitched_markdown = "\n\n".join(sections).strip()
        ast.raw_markdown = stitched_markdown
        return stitched_markdown

    @classmethod
    def stitch_ast(cls, ast: ScriptAST) -> str:
        """stitch 的便利别名方法。"""
        return cls.stitch(ast)
