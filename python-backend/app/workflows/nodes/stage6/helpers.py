"""阶段 6 基础辅助工具与协议规约纠偏模块 (Stage 6 Helpers & Protocol Sanity Guards)。

包含资产语义哈希计算、状态对象解构、剧本正文抽取、实体名称清洗及标准四段式资产格式自愈守卫。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Mapping

from app.workflows.utils.asset_protocol import AssetDependency, AssetProtocolHelper
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer

logger = logging.getLogger("lmd.stage6.helpers")


def compute_asset_semantic_hash(
    category: str,
    asset_id: str,
    prompt: str = "",
    attributes: dict[str, Any] | None = None,
) -> str:
    """计算资产的确定性 SHA-256 语义指纹 (16 位十六进制)。

    【设计原则】
    通过资产类型、核心对象标识、提示词与做旧/形变关键物理属性计算哈希，
    用于全剧跨集资产去重与一致性检测。当跨集新资产计算出的哈希与真理源已有资产
    指纹完全一致时，系统可判定为同一物理形态，自动触发无损复用，避免冗余生图与风格漂移。

    Args:
        category: 资产分类代码 (CHAR, ENV, PROP, VOICE 等)
        asset_id: 资产四段式规范编码
        prompt: 视觉生图提示词或声学 TTS 提示词
        attributes: 物理特征属性字典 (如生物 DNA、服化道参数、做旧层级、损坏规模等)

    Returns:
        16 位十六进制 SHA-256 语义指纹摘要
    """
    normalized_prompt = " ".join((prompt or "").strip().lower().split())
    attr_tokens: list[str] = []
    if attributes:
        for k in sorted(attributes.keys()):
            v = attributes[k]
            if v is not None and str(v).strip():
                attr_tokens.append(f"{k}:{str(v).strip().lower()}")
    attr_str = "|".join(attr_tokens)
    token_part = asset_id.split("_")[1] if "_" in asset_id else asset_id
    raw_key = f"{category.upper()}|{token_part}|{normalized_prompt}|{attr_str}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]




class StageResult(dict):
    """具备字典与对象双向属性访问能力的阶段状态容器。"""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'StageResult' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value




def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)




def _extract_token_from_id(raw_id: str, prefix: str, default_token: str) -> str:
    """辅助提取纯英文字符 token。"""
    norm = AssetProtocolHelper.normalize_id(raw_id)
    if norm.startswith(f"{prefix}_"):
        parts = norm.split("_")
        if len(parts) >= 2 and parts[1]:
            tok = re.sub(r"[^A-Z0-9]", "", parts[1])
            if tok:
                return tok
    # 尝试从整个字符串中提取
    cleaned = re.sub(r"[^A-Z0-9]", "", norm.replace(prefix, ""))
    return cleaned if cleaned else default_token




def _extract_screenplay_text(script_data: Any) -> str:
    """从各版本剧本结构体中精准抽取正本文学剧本文本。"""
    if not script_data:
        return ""
    if isinstance(script_data, str):
        return script_data.strip()
    if isinstance(script_data, dict):
        for k in ["screenplay_text", "body_markdown", "script_text", "content", "screenplay"]:
            val = script_data.get(k)
            if val and isinstance(val, str) and val.strip():
                return val.strip()
        scenes = script_data.get("scenes") or []
        if scenes:
            parts = []
            for sc in scenes:
                if isinstance(sc, dict):
                    hdr = sc.get("scene_header") or sc.get("header") or sc.get("heading") or sc.get("title") or ""
                    if hdr:
                        parts.append(hdr)
                    s_txt = sc.get("screenplay_text") or sc.get("content") or sc.get("text") or ""
                    if s_txt:
                        parts.append(str(s_txt).strip())
                    for act in sc.get("actions") or []:
                        parts.append(str(act))
                    for dlg in sc.get("dialogues") or []:
                        if isinstance(dlg, dict):
                            spk = dlg.get("speaker") or dlg.get("character") or "角色"
                            brk = f"（{dlg.get('parenthetical')}）" if dlg.get("parenthetical") else ""
                            line = dlg.get("lines") or dlg.get("dialogue") or ""
                            parts.append(f"{spk}：{brk}{line}")
                        elif isinstance(dlg, str):
                            parts.append(dlg)
            if parts:
                return "\n".join(parts)

        # 兼容仅包含结构化字段（characters_present / scene_header / core_props）的精简元数据剧本
        meta_parts = []
        if script_data.get("scene_header"):
            meta_parts.append(f"【场景】{script_data.get('scene_header')}")
        if script_data.get("characters_present") and isinstance(script_data.get("characters_present"), list):
            for cp in script_data.get("characters_present"):
                meta_parts.append(f"{cp}站在现场警惕四周。")
        if script_data.get("core_props") and isinstance(script_data.get("core_props"), list):
            for prop in script_data.get("core_props"):
                meta_parts.append(f"手持【{prop}】。")
        if meta_parts:
            return "\n".join(meta_parts).strip()
        return json.dumps(script_data, ensure_ascii=False)
    if hasattr(script_data, "screenplay_text") and getattr(script_data, "screenplay_text"):
        return str(getattr(script_data, "screenplay_text")).strip()
    return str(script_data)


# =========================================================================
# 【规则编号: RULE-STAGE6-VOICE-V2】母音频试音词清洗、防撞音色池与阶段2同构补录辅助函数
# =========================================================================



def _clean_name(raw_name: str) -> str:
    """去除角色名称中的括号说明、修饰后缀与舞台标记，提取自然人基准姓名。"""
    if not raw_name:
        return ""
    return re.sub(r"[\(（\[【].*?[\)）\]】]", "", str(raw_name)).strip()




def _ensure_standard_asset(
    item: dict[str, Any],
    default_cat: str,
    token_whitelist: set[str],
    fallback_tok: str = "DEFAULT",
) -> dict[str, Any]:
    """对 LLM 输出的资产项执行四段式纠偏与依赖推导补全。

    【架构防线设计】
    1. 动态角色令牌归纳：优先由 item 的 character_name / name 推导实体 token，阻断非主角资产降级为默认主角。
    2. 基准肖像独立性：BASE_PORTRAIT 严格作为文生图根节点 (parent_asset_id=None, generation_mode='t2i')。
    3. 衍生视图同实体闭环：严格防范跨角色资产继承，若 parent_asset_id 指向异名角色，强制修正为同角色标准底模。
    """
    raw_id = (
        item.get("asset_id")
        or item.get("asset_key")
        or item.get("char_id")
        or item.get("scene_id")
        or item.get("prop_id")
        or item.get("voice_id")
        or ""
    )
    parsed = AssetProtocolHelper.parse_id(raw_id)

    # 提取实体名称以便进行实体对齐
    char_name = str(item.get("character_name") or item.get("name") or "").strip()
    inferred_char_tok = ""
    if default_cat == "CHAR" and char_name:
        clean_nm = _clean_name(char_name)
        inferred_char_tok = AssetProtocolHelper.normalize_token(clean_nm or char_name)

    env_name = str(item.get("location_name") or item.get("scene_name") or item.get("name") or "").strip()
    inferred_env_tok = ""
    if default_cat == "ENV" and env_name:
        clean_en = _clean_name(env_name)
        inferred_env_tok = AssetProtocolHelper.normalize_token(clean_en or env_name)

    prop_name = str(item.get("prop_name") or item.get("item_name") or item.get("name") or "").strip()
    inferred_prop_tok = ""
    if default_cat == "PROP" and prop_name:
        clean_pn = _clean_name(prop_name)
        inferred_prop_tok = AssetProtocolHelper.normalize_token(clean_pn or prop_name)

    if parsed and parsed.category == default_cat:
        # 如果解析出的 token 是通用占位符 (DEFAULT, PROTAGONIST, CHAR) 且有更明确的 inferred_char_tok，则进行纠偏
        if default_cat == "CHAR" and inferred_char_tok and inferred_char_tok not in ("DEFAULT", "UNKNOWN", "CHARACTER"):
            if parsed.token in ("DEFAULT", "UNKNOWN", "PROTAGONIST", "CHAR") and parsed.token != inferred_char_tok:
                logger.debug(
                    "【阶段 6 资产协议纠偏】角色占位代号 [%s] 根据角色名 [%s] 纠正为 [%s]",
                    parsed.token, char_name, inferred_char_tok,
                )
                std_id = AssetProtocolHelper.build_id(parsed.category, inferred_char_tok, parsed.tier, parsed.function)
            else:
                std_id = parsed.standard_id
        elif default_cat == "ENV" and inferred_env_tok and inferred_env_tok not in ("DEFAULT", "UNKNOWN", "MAINSCENE", "SCENE", "ENV"):
            if parsed.token in ("DEFAULT", "UNKNOWN", "MAINSCENE", "SCENE", "ENV") and parsed.token != inferred_env_tok:
                logger.debug(
                    "【阶段 6 资产协议纠偏】场景占位代号 [%s] 根据场景名 [%s] 纠正为 [%s]",
                    parsed.token, env_name, inferred_env_tok,
                )
                std_id = AssetProtocolHelper.build_id(parsed.category, inferred_env_tok, parsed.tier, parsed.function)
            else:
                std_id = parsed.standard_id
        elif default_cat == "PROP" and inferred_prop_tok and inferred_prop_tok not in ("DEFAULT", "UNKNOWN", "EVIDENCE", "PROP", "ITEM"):
            if parsed.token in ("DEFAULT", "UNKNOWN", "EVIDENCE", "PROP", "ITEM") and parsed.token != inferred_prop_tok:
                logger.debug(
                    "【阶段 6 资产协议纠偏】道具占位代号 [%s] 根据道具名 [%s] 纠正为 [%s]",
                    parsed.token, prop_name, inferred_prop_tok,
                )
                std_id = AssetProtocolHelper.build_id(parsed.category, inferred_prop_tok, parsed.tier, parsed.function)
            else:
                std_id = parsed.standard_id
        else:
            std_id = parsed.standard_id
    else:
        norm_raw = AssetProtocolHelper.normalize_id(raw_id)
        tok = fallback_tok
        # 1. 优先使用从实体名推导出的 token
        if default_cat == "CHAR" and inferred_char_tok and inferred_char_tok not in ("DEFAULT", "UNKNOWN", "CHARACTER"):
            tok = inferred_char_tok
        elif default_cat == "ENV" and inferred_env_tok and inferred_env_tok not in ("DEFAULT", "UNKNOWN", "MAINSCENE", "SCENE", "ENV"):
            tok = inferred_env_tok
        elif default_cat == "PROP" and inferred_prop_tok and inferred_prop_tok not in ("DEFAULT", "UNKNOWN", "EVIDENCE", "PROP", "ITEM"):
            tok = inferred_prop_tok
        else:
            for t in token_whitelist:
                if t in norm_raw:
                    tok = t
                    break

        if default_cat == "CHAR":
            tier = "T1"
            # 优先识别服饰与全身定妆，防止误判为肖像
            if any(k in norm_raw for k in ["COSTUME", "FULL_BODY", "FULLBODY", "BASE_COSTUME"]):
                func = "BASE_COSTUME"
            elif any(k in norm_raw for k in ["PORTRAIT", "BASE_PORTRAIT", "MAIN_PORTRAIT"]):
                func = "BASE_PORTRAIT"
            elif any(k in norm_raw for k in ["FRONT", "4V_FRONT"]):
                func = "4V_FRONT"
            elif any(k in norm_raw for k in ["SIDE", "PROFILE", "4V_SIDE"]):
                func = "4V_SIDE"
            elif any(k in norm_raw for k in ["BACK", "REAR", "4V_BACK"]):
                func = "4V_BACK"
            elif any(k in norm_raw for k in ["3Q", "THREE_QUARTER", "QUARTER", "4V_3Q"]):
                func = "4V_3Q"
            elif any(k in norm_raw for k in ["MACRO_FACE", "FACIAL_MACRO"]):
                func = "MACRO_FACE"
            elif any(k in norm_raw for k in ["MACRO_HAND", "HANDS_DETAIL"]):
                func = "MACRO_HAND"
            elif "BASE" in norm_raw or norm_raw.endswith("_BASE"):
                # 显式 BASE 或 _BASE 标识角色 0 号人脸基因源基准肖像 (CHAR_*_T1_BASE -> BASE_PORTRAIT)
                func = "BASE_PORTRAIT"
            else:
                # 默认兜底：角色类资产默认回退为基准肖像 BASE_PORTRAIT，严禁默认回退为 BASE_COSTUME
                func = "BASE_PORTRAIT"
            logger.debug(
                "【阶段 6 资产协议自愈】角色资产标准化映射: raw_id=[%s], norm_raw=[%s] -> tier=[%s], func=[%s]",
                raw_id, norm_raw, tier, func,
            )
        elif default_cat == "ENV":
            tier = "T1"
            func = "OTS_BG" if "OTS" in norm_raw or "BG" in norm_raw else "WIDE"
        elif default_cat == "PROP":
            tier = "T1"
            func = "ACTION" if "ACTION" in norm_raw or "DAMAGE" in norm_raw else "STATIC"
        elif default_cat == "VOICE":
            tier = "T1"
            func = "MASTER"
        else:
            tier = "T1"
            func = "BASE"
        std_id = AssetProtocolHelper.build_id(default_cat, tok, tier, func)

    item["asset_id"] = std_id
    item["asset_key"] = std_id
    if default_cat == "CHAR":
        item["char_id"] = std_id
    elif default_cat == "ENV":
        item["scene_id"] = std_id
    elif default_cat == "PROP":
        item["prop_id"] = std_id
    elif default_cat == "VOICE":
        item["voice_id"] = std_id

    dep = AssetProtocolHelper.resolve_dependency(std_id)
    cur_parsed = AssetProtocolHelper.parse_id(std_id)
    if cur_parsed:
        item["entity_token"] = cur_parsed.token
    elif tok:
        item["entity_token"] = tok

    # 依据解析依赖规则严防 二阶/三阶资产退化为文生图 (t2i)
    if dep.generation_mode != "t2i":
        # 衍生切片：优先使用自身指定的 parent，但必须强校验同实体一致性
        p_cand = item.get("parent_asset_key") or item.get("parent_asset_id") or dep.parent_asset_id
        # 拦截自引用父资产 (Self-referencing loop)
        if p_cand == std_id:
            logger.warning("【阶段 6 资产协议纠偏·自环拦截】检测到资产 [%s] 自引用父资产，自动切断", std_id)
            p_cand = dep.parent_asset_id if dep.parent_asset_id != std_id else None

        if p_cand and cur_parsed:
            p_parsed = AssetProtocolHelper.parse_id(p_cand)
            if p_parsed and p_parsed.category == cur_parsed.category and p_parsed.token != cur_parsed.token:
                logger.warning(
                    "【阶段 6 资产协议纠偏·防跨实体污染】检测到资产 [%s] (token=%s) 错配父资产 [%s] (token=%s)，自动纠偏为同实体标准底模 [%s]",
                    std_id, cur_parsed.token, p_cand, p_parsed.token, dep.parent_asset_id,
                )
                p_cand = dep.parent_asset_id
        # 若 p_cand 仍为空且非根节点，必须强制兜底到协议推荐的 parent_asset_id，绝不能成为孤儿资产
        if not p_cand:
            p_cand = dep.parent_asset_id if dep.parent_asset_id != std_id else None

        # 终极自环拦截
        if p_cand == std_id:
            p_cand = None

        item["generation_mode"] = dep.generation_mode
        item["parent_asset_key"] = p_cand
        item["parent_asset_id"] = p_cand
        item["is_benchmark"] = 0
    else:
        # t2i 文生图基准肖像：仅允许一阶根节点 (T1 / Z01 / S0)
        item["generation_mode"] = "t2i"
        item["parent_asset_key"] = None
        item["parent_asset_id"] = None
        item["is_benchmark"] = 1 if dep.is_benchmark else 0

    item["denoise_strength"] = dep.recommended_denoise if item.get("denoise_strength") is None else item.get("denoise_strength")
    item.setdefault("recommended_denoise", dep.recommended_denoise)
    item.setdefault("control_type", dep.control_type)
    item.setdefault("workflow_note", dep.workflow_note)

    cat_map = {"CHAR": "character", "ENV": "scene", "PROP": "prop", "VOICE": "audio"}
    cat_key = cat_map.get(default_cat, "default")
    item.setdefault("negative_prompt", PromptSynthesizer.get_category_negative_prompt(cat_key))
    item.setdefault("identity_prompt", item.get("visual_prompt") or item.get("image_prompt") or "")
    item.setdefault("delta_prompt", "")

    logger.debug(
        "【阶段 6 资产四段式规范化】类别=%s, ID=%s, 模式=%s, 父级=%s, 基准=%s",
        default_cat, std_id, item.get("generation_mode"), item.get("parent_asset_key"), item.get("is_benchmark"),
    )
    return item



