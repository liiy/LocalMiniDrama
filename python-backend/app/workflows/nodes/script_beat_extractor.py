"""轻量级视听剧本节拍与戏剧实体提取器 (Script Beat Extractor)。

用于在 Stage 7 分镜解析前置或 LLM 降级自愈时，仅依靠确定性规则和纯 Python 正则表达式，
精准解析剧本 Markdown 纯文本或 AST 结构，提取出场景、开局 3 秒抓手动作、动作流、
真实角色对白、微动作/发声腔体以及片尾悬念，杜绝分镜生成无中生有和虚构实体。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, TypedDict

logger = logging.getLogger("lmd.script_beat_extractor")


class ExtractedDialogueBeat(TypedDict):
    """提取的对白视听小节"""
    speaker: str
    parenthetical: str
    dialogue_text: str
    vocal_delivery: str
    stress_action: str
    raw_line: str


class ScriptSceneContext(TypedDict):
    """提取出的剧本场景视听上下文"""
    scene_header: str
    environment_desc: str
    hook_3s_action: str
    ending_cliffhanger: str
    actions: List[str]
    dialogues: List[ExtractedDialogueBeat]
    sound_effects: List[str]
    involved_characters: List[str]
    action_characters: List[str]
    hook_characters: List[str]
    cliffhanger_characters: List[str]
    ordered_beats: List[Dict[str, Any]]


class ScriptBeatExtractor:
    """剧本视听原子节拍提取器"""

    # 场景标题正则：匹配【场景 01】内景. 苏秀兰旧居灵堂 - 深夜 - 昏暗钨丝灯与惨白雨夜光
    SCENE_HEADER_PATTERN = re.compile(
        r"【场景\s*\d+】([^\n]+)"
    )

    # 开局抓手动作正则：匹配 △ 【开局3秒抓手】xxx 或 △ 【3秒抓手】xxx
    HOOK_PATTERN = re.compile(
        r"△\s*【(?:开局)?3秒抓手】\s*([^\n]+)"
    )

    # 片尾悬念正则：匹配 △ 【115秒片尾悬念】xxx 或 △ 【片尾悬念】xxx
    CLIFFHANGER_PATTERN = re.compile(
        r"△\s*【(?:\d+秒)?(?:片尾)?悬念】\s*([^\n]+)"
    )

    # 通用动作行正则：匹配 △ 动作描述
    ACTION_PATTERN = re.compile(
        r"^[△▲]\s*(?:【[^】]+】)?\s*(.+)$"
    )

    # 对白行正则：匹配 角色名（括号微动作/情绪）：对白内容
    # 支持中文全角括号（）与半角括号()，支持中英文冒号：:
    DIALOGUE_PATTERN = re.compile(
        r"^([A-Za-z0-9_\u4e00-\u9fa5]{2,12})\s*[（(]([^）)]+)[）)]\s*[：:]\s*(.+)$"
    )

    # 简单对白行正则（无括号修饰）：角色名：对白内容
    SIMPLE_DIALOGUE_PATTERN = re.compile(
        r"^([A-Za-z0-9_\u4e00-\u9fa5]{2,12})\s*[：:]\s*(.+)$"
    )

    # 声学行为音效正则：匹配 [声学行为: 开场突发重击 Braam Hit]
    SOUND_PATTERN = re.compile(
        r"\[声学行为\s*[:：]\s*([^\]]+)\]"
    )

    @classmethod
    def extract_context(
        cls,
        script_input: Any,
        stage6_characters: Optional[List[Any]] = None,
    ) -> ScriptSceneContext:
        """从各种形式的剧本输入中提炼出结构化视听上下文。
        
        Args:
            script_input: 可以是 dict (包含 body_markdown / content / text / ast_data)
                          也可以是纯 str 剧本文本。
            stage6_characters: 可选的阶段 6 当集角色清单 (包含 name, character_token 等)，
                               作为非对白在场角色扫描的唯一准入白名单。
        """
        raw_text = ""
        ast_data: Dict[str, Any] = {}

        if isinstance(script_input, str):
            raw_text = script_input
        elif isinstance(script_input, dict):
            raw_text = (
                script_input.get("body_markdown")
                or script_input.get("screenplay_text")
                or script_input.get("content")
                or script_input.get("text")
                or script_input.get("script")
                or ""
            )
            if not raw_text and "hook_3s" in script_input:
                raw_text = str(script_input.get("hook_3s", ""))
            ast_data = script_input.get("ast_data", {}) if isinstance(script_input.get("ast_data"), dict) else {}

        context: ScriptSceneContext = {
            "scene_header": "",
            "environment_desc": "",
            "hook_3s_action": "",
            "ending_cliffhanger": "",
            "actions": [],
            "dialogues": [],
            "sound_effects": [],
            "involved_characters": [],
            "action_characters": [],
            "hook_characters": [],
            "cliffhanger_characters": [],
            "ordered_beats": [],
        }

        # 0. 构建阶段 6 角色白名单集合（以当集角色清单为唯一准入真值）
        target_whitelist: List[Dict[str, Any]] = []
        if stage6_characters:
            for item in stage6_characters:
                c_name = ""
                c_token = ""
                if isinstance(item, dict):
                    c_name = str(item.get("name") or item.get("character_name") or "").strip()
                    c_token = str(item.get("character_token") or "").strip()
                elif isinstance(item, str):
                    c_name = item.strip()
                if c_name and len(c_name) >= 2:
                    target_whitelist.append({"name": c_name, "token": c_token, "raw": item})

        def _scan_stage6_characters(text_val: str, beat_type: str = "action") -> List[str]:
            """在指定视听文本中定向扫描阶段 6 当集白名单角色"""
            matched: List[str] = []
            if not text_val or not target_whitelist:
                return matched
            for cand in target_whitelist:
                cand_name = cand["name"]
                if cand_name in text_val:
                    matched.append(cand_name)
                    if cand_name not in context["involved_characters"]:
                        context["involved_characters"].append(cand_name)
                        logger.debug(
                            "【ScriptBeatExtractor】命中阶段6当集动作/悬念在场角色: %s (节拍类型=%s, 文本='%s')",
                            cand_name,
                            beat_type,
                            text_val[:35],
                        )
            return matched

        # 1. 优先尝试从 AST beats 中读取（若已有 Stage 5 的 AST）
        beats = ast_data.get("beats", []) if isinstance(ast_data, dict) else []
        if beats:
            logger.debug("【ScriptBeatExtractor】命中结构化 ast_data beats，数量: %d", len(beats))
            for b in beats:
                b_dict = b if isinstance(b, dict) else getattr(b, "model_dump", lambda: {})()
                b_type = b_dict.get("beat_type")
                if b_type == "dialogue":
                    spk = b_dict.get("speaker") or ""
                    txt = b_dict.get("dialogue_text") or ""
                    stress = b_dict.get("stress_action") or ""
                    voice = b_dict.get("vocal_delivery") or ""
                    if spk and spk not in context["involved_characters"]:
                        context["involved_characters"].append(spk)
                    dlg_item = {
                        "speaker": spk,
                        "parenthetical": f"{stress}, {voice}".strip(", "),
                        "dialogue_text": txt,
                        "vocal_delivery": voice,
                        "stress_action": stress,
                        "raw_line": f"{spk}：{txt}",
                    }
                    context["dialogues"].append(dlg_item)
                    context["ordered_beats"].append({
                        "beat_type": "dialogue",
                        **dlg_item,
                    })
                    # 亦检查对白修饰词中是否包含其他在场角色
                    _scan_stage6_characters(stress, "dialogue_stress")
                elif b_type in ("action", "hook", "cliffhanger"):
                    act_txt = b_dict.get("action_desc") or b_dict.get("content") or ""
                    if act_txt:
                        context["actions"].append(act_txt)
                        if b_type == "hook" or not context["hook_3s_action"]:
                            context["hook_3s_action"] = act_txt
                        if b_type == "cliffhanger":
                            context["ending_cliffhanger"] = act_txt
                        c_chars = _scan_stage6_characters(act_txt, b_type or "action")
                        context["ordered_beats"].append({
                            "beat_type": b_type,
                            "action_desc": act_txt,
                            "characters": c_chars,
                            "is_twist": any(w in act_txt for w in ["45秒", "微反转", "反转", "高潮"]),
                        })

        # 2. 从文本按行分析（补充或主导提取）
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for line in lines:
            # 匹配场景头
            m_scene = cls.SCENE_HEADER_PATTERN.search(line)
            if m_scene and not context["scene_header"]:
                context["scene_header"] = line
                context["environment_desc"] = m_scene.group(1).strip()
                continue

            # 匹配声学行为
            m_sound = cls.SOUND_PATTERN.search(line)
            if m_sound:
                snd_txt = m_sound.group(1).strip()
                context["sound_effects"].append(snd_txt)
                _scan_stage6_characters(snd_txt, "sound")
                if not beats:
                    context["ordered_beats"].append({
                        "beat_type": "sound",
                        "sound_desc": snd_txt,
                    })
                continue

            # 匹配开局抓手
            m_hook = cls.HOOK_PATTERN.search(line)
            if m_hook:
                hook_action = m_hook.group(1).strip()
                if not beats:
                    context["actions"].append(hook_action)
                if not context["hook_3s_action"]:
                    context["hook_3s_action"] = hook_action
                h_chars = _scan_stage6_characters(hook_action, "hook")
                for hc in h_chars:
                    if hc not in context["hook_characters"]:
                        context["hook_characters"].append(hc)
                if not beats:
                    context["ordered_beats"].append({
                        "beat_type": "hook",
                        "action_desc": hook_action,
                        "characters": h_chars,
                    })
                continue

            # 匹配片尾悬念
            m_cliff = cls.CLIFFHANGER_PATTERN.search(line)
            if m_cliff:
                cliff_action = m_cliff.group(1).strip()
                if not beats:
                    context["actions"].append(cliff_action)
                context["ending_cliffhanger"] = cliff_action
                c_chars = _scan_stage6_characters(cliff_action, "cliffhanger")
                for cc in c_chars:
                    if cc not in context["cliffhanger_characters"]:
                        context["cliffhanger_characters"].append(cc)
                if not beats:
                    context["ordered_beats"].append({
                        "beat_type": "cliffhanger",
                        "action_desc": cliff_action,
                        "characters": c_chars,
                    })
                continue

            # 匹配对白 (带括号情绪/微动作)
            m_dlg = cls.DIALOGUE_PATTERN.match(line)
            if m_dlg:
                speaker = m_dlg.group(1).strip()
                paren = m_dlg.group(2).strip()
                dlg_text = m_dlg.group(3).strip()

                if speaker not in context["involved_characters"]:
                    context["involved_characters"].append(speaker)

                # 将括号细分为发声/微动作
                stress = paren
                voice = ""
                if "声" in paren or "音" in paren or "腔" in paren:
                    voice = paren

                dlg_item = {
                    "speaker": speaker,
                    "parenthetical": paren,
                    "dialogue_text": dlg_text,
                    "vocal_delivery": voice,
                    "stress_action": stress,
                    "raw_line": line,
                }
                if not beats:
                    context["dialogues"].append(dlg_item)
                    context["ordered_beats"].append({
                        "beat_type": "dialogue",
                        **dlg_item,
                    })
                _scan_stage6_characters(paren, "dialogue_parenthetical")
                continue

            # 匹配对白 (无括号)
            m_sdlg = cls.SIMPLE_DIALOGUE_PATTERN.match(line)
            if m_sdlg:
                spk_cand = m_sdlg.group(1).strip()
                # 排除明显的标签如【场景 01】等
                if not spk_cand.startswith("【") and not spk_cand.startswith("["):
                    dlg_text = m_sdlg.group(2).strip()
                    if spk_cand not in context["involved_characters"]:
                        context["involved_characters"].append(spk_cand)
                    dlg_item = {
                        "speaker": spk_cand,
                        "parenthetical": "",
                        "dialogue_text": dlg_text,
                        "vocal_delivery": "",
                        "stress_action": "",
                        "raw_line": line,
                    }
                    if not beats:
                        context["dialogues"].append(dlg_item)
                        context["ordered_beats"].append({
                            "beat_type": "dialogue",
                            **dlg_item,
                        })
                    continue

            # 匹配普通动作行
            m_act = cls.ACTION_PATTERN.match(line)
            if m_act:
                action_text = m_act.group(1).strip()
                if not beats:
                    context["actions"].append(action_text)
                if not context["hook_3s_action"]:
                    context["hook_3s_action"] = action_text
                act_chars = _scan_stage6_characters(action_text, "action")
                for ac in act_chars:
                    if ac not in context["action_characters"]:
                        context["action_characters"].append(ac)
                if not beats:
                    is_twist = any(w in line for w in ["45秒", "微反转", "反转", "高潮"])
                    context["ordered_beats"].append({
                        "beat_type": "action",
                        "action_desc": action_text,
                        "characters": act_chars,
                        "is_twist": is_twist,
                    })
                continue

            # 其他未带动作前缀但包含舞台指示的行扫描
            _scan_stage6_characters(line, "general_line")

        # 3. 兜底补齐：若未匹配到 hook_3s_action，则以第一个动作作为开篇抓手
        if not context["hook_3s_action"] and context["actions"]:
            context["hook_3s_action"] = context["actions"][0]

        # 兜底补齐：若未匹配到片尾悬念，则以最后一个动作作为片尾悬念
        if not context["ending_cliffhanger"] and context["actions"]:
            context["ending_cliffhanger"] = context["actions"][-1]

        logger.debug(
            "【ScriptBeatExtractor】提取完成: 场景='%s', 开局抓手='%s', 动作数=%d, 对白数=%d, 角色=%s",
            context["scene_header"][:30] if context["scene_header"] else "无",
            context["hook_3s_action"][:30] if context["hook_3s_action"] else "无",
            len(context["actions"]),
            len(context["dialogues"]),
            context["involved_characters"],
        )
        return context

    # 快捷别名
    extract = extract_context
