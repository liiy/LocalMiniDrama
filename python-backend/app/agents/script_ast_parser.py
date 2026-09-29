"""短剧视听正文 AST 结构化分块解析器与缝合器 (Script AST Parser & Stitcher)。

严格对齐《短剧剧本·两程九阶工业化创作规范》正文排版规范与分镜对接标准：
1. 继承原有 4 个大粒度宏观分块（用于局部缺陷修补与多维度质检）：
   - hook_3s: 前3秒视觉特写与强钩子
   - actions_and_scenes: 核心视听动作与场景调度
   - dialogues: 潜台词拉扯与情绪交锋对白
   - cliffhanger: 片尾定格与悬念字幕
2. 升级新增细粒度原子视听节拍流 (AudioVisualBeat)：
   - 严格按剧本叙事时间轴顺序提取动作与对白混合节拍，绝不打乱前后时序；
   - 提取角色微动作应激（stress_action）、发声阻力与腔体（vocal_delivery）；
   - 纯净台词与动作剥离、关键交互道具（interacted_prop）提取、智能时长预估；
   - 为阶段七（分镜设计与机位生成）和阶段八（情绪母带与配音合成）提供无缝且确定性的数据支持。
"""
from __future__ import annotations

import logging
import re
from typing import Literal
from app.schemas.script_graph_state import ASTBlockItem, AudioVisualBeat, ScriptAST

logger = logging.getLogger(__name__)


class ScriptASTParser:
    """视听正文 AST 结构化解析器（支持双层结构：宏观四分块 + 微观时序视听节拍序列）。"""

    # 正则规则匹配：片尾定格与悬念
    CLIFFHANGER_PATTERNS = [
        re.compile(r"(【片尾定格(?:与悬念钩子)?】.*?$)", re.DOTALL | re.IGNORECASE),
        re.compile(r"(\[片尾定格.*?$)", re.DOTALL | re.IGNORECASE),
        re.compile(r"(△\s*特写：.*?（定格）.*?$)", re.DOTALL | re.IGNORECASE),
    ]

    # 正则规则匹配：前3秒开场特写钩子
    HOOK_3S_PATTERNS = [
        re.compile(r"(△\s*开场特写[^\n]*\n.*?)(?=\n(?:△|[^\n]+[（\(][^\)]*[）\)]|【)|\Z)", re.DOTALL),
        re.compile(r"(前3秒[^\n]*\n.*?)(?=\n(?:△|[^\n]+[（\(][^\)]*[）\)]|【)|\Z)", re.DOTALL),
        re.compile(r"(△\s*特写[^\n]*\n.*?)(?=\n(?:△|[^\n]+[（\(][^\)]*[）\)]|【)|\Z)", re.DOTALL),
    ]

    # 对白发声物理阻力/腔体常用关键词集合（辅助区分括号内的动作 vs 声学指示）
    VOCAL_KEYWORDS = {
        "气音", "压低", "冷声", "低沉", "声带颤抖", "齿缝挤出", "嘶吼", "破音", "哽咽",
        "咬牙", "低吼", "轻语", "耳语", "颤抖", "急促", "沙哑", "清脆", "高亢", "暴怒",
        "戏谑", "嘲讽", "断断续续", "呢喃", "字字如冰", "音调拔高", "气声", "带哭腔", "沉声",
        "语速加快", "语速急促", "停顿", "极度压抑", "发颤", "冷冰冰", "咬牙切齿"
    }

    @classmethod
    def parse_dialogue_line(cls, line: str) -> dict[str, str]:
        """解析单行对白中的角色、情绪/动作指示、语气/语速演出指令（OpenMontage Expressive Delivery）及正文。
        
        支持输入规范格式：
        1. `主角（冷笑，压低声音）：台词`
        2. `主角（指节泛白，齿缝挤出）：台词`
        3. `主角（指节泛白，目光如刀）[语速急促 · 极度压抑 · 2秒停顿]: 台词`
        4. `主角: 台词`
        
        返回字典包含历史键 (role, action, delivery, text) 与细化扩展键 (stress_action, vocal_delivery)。
        """
        line = line.strip()
        if not line:
            return {}

        # 匹配 `角色名（动作/情绪）[演出指示]：台词` 或 `角色名（动作/情绪）：台词`
        pattern = r"^([^\s（(\[:：]+)(?:[（\(]([^）\)]*)[）\)])?(?:\s*\[([^\]]*)\])?\s*[:：]\s*(.*)$"
        m = re.match(pattern, line)
        if m:
            role = m.group(1).strip()
            action = (m.group(2) or "").strip()
            delivery = (m.group(3) or "").strip()
            text = m.group(4).strip()
            
            # 细化拆分：应激动作 (stress_action) 与 发声阻力/腔体 (vocal_delivery)
            stress_action = action
            vocal_delivery = delivery

            # 若显式指定了 [演出指示]，则直接采纳；否则从括号内容进一步智能剥离
            if not vocal_delivery and action:
                parts = re.split(r"[,，/、]", action)
                if len(parts) >= 2:
                    stress_parts = []
                    vocal_parts = []
                    for part in parts:
                        p = part.strip()
                        if any(kw in p for kw in cls.VOCAL_KEYWORDS):
                            vocal_parts.append(p)
                        else:
                            stress_parts.append(p)
                    
                    if vocal_parts and stress_parts:
                        stress_action = "，".join(stress_parts)
                        vocal_delivery = "，".join(vocal_parts)
                    elif len(parts) == 2:
                        # 默认前部为动作，后部为发声腔体（规范：角色（应激微动作，发声物理阻力/腔体））
                        stress_action = parts[0].strip()
                        vocal_delivery = parts[1].strip()

            return {
                "role": role,
                "action": action,
                "delivery": delivery,
                "text": text,
                "stress_action": stress_action,
                "vocal_delivery": vocal_delivery,
            }

        return {
            "role": "",
            "action": "",
            "delivery": "",
            "text": line,
            "stress_action": "",
            "vocal_delivery": "",
        }

    @classmethod
    def _extract_props(cls, text: str) -> str:
        """从视听描述或台词中识别提取关键道具标识（如【染血文件】、【帝龙令】）。
        
        自动排除时空场景、人物指纹、音效声学行为以及三大节拍锚点（【开局3秒抓手】、【45秒微反转】、【115秒片尾悬念】等）。
        """
        props = re.findall(r"【([^】]+)】", text)
        excluded_prefixes = (
            "场景", "人物", "道具", "片尾定格", "字幕悬念", "音效", "BGM", "拟音",
            "开局3秒", "3秒", "45秒", "115秒", "微反转", "悬念", "抓手", "开场", "正文",
            "声学行为", "动作", "对白",
        )
        filtered = [
            p for p in props
            if not any(p.startswith(pref) for pref in excluded_prefixes)
            and not any(tag in p for tag in ("抓手", "微反转", "悬念", "声学行为"))
        ]
        return "、".join(filtered) if filtered else ""

    @classmethod
    def _extract_foley(cls, text: str) -> str:
        """提取环境音效或动作拟音提示。"""
        # 匹配 【音效：重摔声】 或 【BGM：心跳声骤停】 或 △ 音效：...
        sfx_match = re.search(r"【(?:音效|BGM|拟音)[:：]([^】]+)】", text)
        if sfx_match:
            return sfx_match.group(1).strip()
        foley_match = re.search(r"△\s*(?:音效|BGM|拟音)[:：]\s*(.*)$", text)
        if foley_match:
            return foley_match.group(1).strip()
        return ""

    @classmethod
    def estimate_beat_duration(cls, beat_type: str, text: str) -> float:
        """基于视听节奏模型估算原子节拍视听持续时长（秒）。"""
        if beat_type == "dialogue":
            # 中文短剧对白常态语速为每秒 3.5~4.2 字，额外增加 0.5 秒微停顿气口
            dur = len(text) / 3.8 + 0.5
            return max(1.2, round(min(dur, 8.5), 1))
        elif beat_type in ("hook", "cliffhanger"):
            # 钩子与片尾定格需要视觉重音，预估 2.5~4.0 秒
            return max(2.5, round(min(len(text) * 0.12 + 1.8, 5.0), 1))
        elif beat_type == "foley":
            return 1.5
        else:
            # 物理动作镜头通常 1.8~3.5 秒
            return max(1.5, round(min(len(text) * 0.1 + 1.2, 4.5), 1))

    @classmethod
    def parse_beats(cls, episode_num: int, markdown_text: str) -> list[AudioVisualBeat]:
        """按剧本真实时间轴顺序，精准解析细粒度原子视听节拍流 (AudioVisualBeat)。
        
        保证动作与对白的交织先后顺序不被破坏，同时分离微动作、发声阻力与纯文本。
        """
        raw_text = markdown_text.strip()
        if not raw_text:
            return []

        beats: list[AudioVisualBeat] = []
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]

        current_scene = ""
        in_hook = False
        in_cliffhanger = False
        beat_counter = 1

        dialogue_pattern = re.compile(r"^([\u4e00-\u9fa5a-zA-Z0-9·_]+)\s*[（\(](.*?)[）\)]\s*[：:]\s*(.*)$")
        simple_dialogue_pattern = re.compile(r"^([\u4e00-\u9fa5a-zA-Z0-9·_]{2,8})\s*[：:]\s*(.*)$")

        for line in lines:
            # 提取音效/BGM 与 道具标识
            foley_cue = cls._extract_foley(line)
            interacted_prop = cls._extract_props(line)

            # 1. 检测场景头标（如：【场景 01】日 内 顾氏集团顶层总裁办 或 【场景】日 内 总裁办 或 日 内 总裁办）
            scene_match = re.match(r"^(?:【场景(?:\s*\d+)?】|【场景】|△\s*场景[:：])\s*(.*)$", line)
            if scene_match:
                current_scene = scene_match.group(1).strip()
                continue
            if re.match(r"^(?:日|夜)\s+(?:内|外)\s+", line):
                current_scene = line
                continue

            # 2. 检测开场特写钩子与片尾悬念定格区域状态
            if "开场特写" in line or "前3秒" in line:
                in_hook = True
                # 若标题行本身就附带了具体动作描述（如 △ 开场特写（前3秒钩子）：一只骨节分明的手...）
                header_action = re.sub(r"^[△\s]*(?:开场特写|前3秒钩子|前3秒特写)[^\n:：]*[:：]?", "", line).strip()
                if header_action:
                    dur = cls.estimate_beat_duration("hook", header_action)
                    beat = AudioVisualBeat(
                        beat_id=f"EP{episode_num:02d}_B{beat_counter:03d}",
                        scene_ref=current_scene,
                        beat_type="hook",
                        speaker="",
                        stress_action="",
                        vocal_delivery="",
                        dialogue_text="",
                        physical_action=header_action,
                        interacted_prop=interacted_prop or cls._extract_props(header_action),
                        foley_cue=foley_cue,
                        estimated_duration_sec=dur,
                    )
                    beats.append(beat)
                    beat_counter += 1
                    in_hook = False
                continue
            elif "片尾定格" in line or "【字幕悬念】" in line:
                in_cliffhanger = True
                in_hook = False

            # 3. 判断是否为对白行
            is_dialogue = bool(dialogue_pattern.match(line) or simple_dialogue_pattern.match(line))

            if is_dialogue:
                # 对白一旦出现，开场特写钩子区域结束
                in_hook = False
                parsed = cls.parse_dialogue_line(line)
                speaker = parsed.get("role", "")
                pure_dialogue = parsed.get("text", "")
                stress_act = parsed.get("stress_action", "") or parsed.get("action", "")
                vocal_deliv = parsed.get("vocal_delivery", "") or parsed.get("delivery", "")
                
                # 如果正文是单纯音效则归入音效
                beat_type = "dialogue"
                dur = cls.estimate_beat_duration("dialogue", pure_dialogue)

                beat = AudioVisualBeat(
                    beat_id=f"EP{episode_num:02d}_B{beat_counter:03d}",
                    scene_ref=current_scene,
                    beat_type=beat_type,
                    speaker=speaker,
                    stress_action=stress_act,
                    vocal_delivery=vocal_deliv,
                    dialogue_text=pure_dialogue,
                    physical_action="",
                    interacted_prop=interacted_prop or cls._extract_props(line),
                    foley_cue=foley_cue,
                    estimated_duration_sec=dur,
                )
                beats.append(beat)
                beat_counter += 1
            else:
                # 动作、场景叙述、钩子特写或悬念定格
                clean_action = line.lstrip("△").strip()
                # 剔除纯结构标签
                if clean_action in ("【片尾定格与悬念钩子】", "【片尾定格】", "【正文】"):
                    continue

                if in_cliffhanger or "定格" in clean_action or "字幕悬念" in clean_action:
                    b_type = "cliffhanger"
                elif in_hook or "开场特写" in clean_action:
                    b_type = "hook"
                    # 开场钩子通常为首条动作，提取完后后续动作恢复为 normal action
                    in_hook = False
                elif foley_cue and len(clean_action) < 15:
                    b_type = "foley"
                else:
                    b_type = "action"

                dur = cls.estimate_beat_duration(b_type, clean_action)

                beat = AudioVisualBeat(
                    beat_id=f"EP{episode_num:02d}_B{beat_counter:03d}",
                    scene_ref=current_scene,
                    beat_type=b_type,
                    speaker="",
                    stress_action="",
                    vocal_delivery="",
                    dialogue_text="",
                    physical_action=clean_action,
                    interacted_prop=interacted_prop,
                    foley_cue=foley_cue,
                    estimated_duration_sec=dur,
                )
                beats.append(beat)
                beat_counter += 1

        logger.info(
            f"[ScriptASTParser] 第 {episode_num} 集时序视听节拍解析完毕，共生成 {len(beats)} 个原子节拍。"
        )
        return beats

    @classmethod
    def parse(cls, episode_num: int, markdown_text: str) -> ScriptAST:
        """将正文 Markdown 解析为 4 个 AST 结构分块以及时序视听节拍流 (beats)。"""
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
                beats=[],
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

        # 4. 解析按时间轴严格排列的原子视听节拍序列 (beats)
        beats = cls.parse_beats(episode_num=episode_num, markdown_text=raw_text)

        logger.debug(
            f"[ScriptASTParser] 完成第 {episode_num} 集 AST 构建: 4 大分块已就绪, 视听节拍共 {len(beats)} 条。"
        )

        return ScriptAST(episode_num=episode_num, blocks=blocks, beats=beats, raw_markdown=raw_text)

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
