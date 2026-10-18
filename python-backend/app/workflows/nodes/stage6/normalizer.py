"""阶段 6 实体归一化漏斗与物理形态状态机 (Stage 6 Entity Normalizer & Morph State Machine)。

通过多级漏斗实现出场实体精确对齐与别名消歧，并通过状态机推进物证受损、气候风化等物理形态演化。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.tools.screenplay_feature_scanner import (
    DEFORMATION_VERBS,
    PINYIN_LOOKUP,
    ScreenplayScanResult,
    _entity_matches_text,
    _extract_anchor_props_from_characters,
    _slugify_chinese,
)
from app.workflows.nodes.stage6.genre_packs import BaseGenrePack, get_genre_pack
from app.workflows.nodes.stage6.helpers import _clean_name
from app.workflows.utils.asset_protocol import AssetProtocolHelper

logger = logging.getLogger("lmd.stage6.normalizer")


def extract_pure_physical_environment_cues(scanner_result: ScreenplayScanResult | None) -> str:
    """提取纯物理环境影调线索（仅光影氛围/气候/时间），绝不包含任何实体名单（角色名、场景名、道具名）。
    
    此举从输入源头彻底切除大模型的先验注意力锚定与弱关联台词提及幻读！
    """
    if not scanner_result:
        return "- 物理影调: 光照正常，自然影视漫反射，无极端气候异动。"

    lines: list[str] = []
    lights = scanner_result.lighting_conditions or []
    if lights:
        lines.append(f"- 光影明暗与照明质感: {', '.join(lights)}")
    else:
        lines.append("- 光影明暗与照明质感: 自然电影感侧逆光，微弱漫反射")

    time_weather = getattr(scanner_result, "time_weather_conditions", []) or []
    if time_weather:
        lines.append(f"- 气候与时间环境: {', '.join(time_weather)}")

    return "\n".join(lines) if lines else "- 物理影调: 现实影视质感，标准摄影布光。"




class AssetEntityNormalizer:
    """阶段 6 实体三级归一化漏斗 (Tiered Entity Normalizer)。
    
    通过 L1 别名精确查表 -> L2 职衔称谓正则剥离与双向包含 -> L3 随身物反向嗅探与空间闭包，
    将大模型纯文本盲抽出的粗糙名称与全局资产库进行高置信度对齐与新实体判定。
    """

    def __init__(
        self,
        known_characters: dict[str, Any] | list[Any] | None,
        known_envs_props: dict[str, Any] | None,
        scanner_result: ScreenplayScanResult | None,
        genre_pack: BaseGenrePack | None = None,
        drama_genre: str = "",
    ):
        """初始化实体归一化漏斗。

        Args:
            known_characters: 已登记的角色字典或列表（来自阶段 2 或全局真理源）。
            known_envs_props: 已登记的场景与道具注册表。
            scanner_result: 特征逆向扫描器识别出的结果集（含别名映射表等）。
            genre_pack: 可选的题材预设包实例；若为 None 则根据 drama_genre 自动解析。
            drama_genre: 可选剧本题材标签字符串。
        """
        self.known_chars: dict[str, dict[str, Any]] = {}
        if isinstance(known_characters, dict):
            for k, v in known_characters.items():
                if isinstance(v, dict):
                    self.known_chars[k] = v
        elif isinstance(known_characters, list):
            for idx, c in enumerate(known_characters):
                if isinstance(c, dict):
                    name = c.get("name") or f"CHAR_{idx}"
                    self.known_chars[name] = c

        self.known_envs_props = known_envs_props or {}
        self.scanner_alias_map = getattr(scanner_result, "character_alias_map", {}) or {}
        self.genre_pack: BaseGenrePack = genre_pack or get_genre_pack(drama_genre=drama_genre)
        logger.debug(
            "【阶段 6 实体归一化漏斗初始化】已知角色数=%d, 别名数=%d, 当前绑定题材包=[%s]",
            len(self.known_chars),
            len(self.scanner_alias_map),
            self.genre_pack.name,
        )

    def normalize_character_name(self, raw_name: str) -> tuple[str, bool, dict[str, Any] | None]:
        """三级归一化角色名称。

        Args:
            raw_name: 原始提取出的候选角色名称字符串。

        Returns:
            tuple[str, bool, dict[str, Any] | None]:
                - standard_name: 规范化对齐后的标准角色名（命中已有则为库中名，否则为去噪后的原名）。
                - is_existing: 是否为已登记的既有角色（True 代表在库，False 代表本集新角色）。
                - matched_char_profile: 命中的角色档案字典，若未命中则为 None。
        """
        clean_name = str(raw_name).strip()
        if not clean_name:
            return "UNKNOWN_CHAR", False, None

        # Level 1: 扫描器别名映射表与库中 aliases 列表精确命中
        # 1.1 扫描器别名字典 (如 "老沈" -> "沈炼")
        if clean_name in self.scanner_alias_map:
            target_name = self.scanner_alias_map[clean_name]
            for cid, prof in self.known_chars.items():
                if prof.get("name") == target_name:
                    logger.debug(
                        "【角色归一化 L1 别名命中】原名 [%s] -> 映射为已登场角色 [%s] (%s)",
                        clean_name,
                        target_name,
                        prof.get("character_code") or cid,
                    )
                    return target_name, True, prof

        # 1.2 库中别名字段匹配
        for cid, prof in self.known_chars.items():
            c_name = prof.get("name", "")
            aliases = prof.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            if clean_name == c_name or clean_name in aliases:
                logger.debug(
                    "【角色归一化 L1 库档案命中】原名 [%s] -> 命中已知角色 [%s] (%s)",
                    clean_name,
                    c_name,
                    prof.get("character_code") or cid,
                )
                return c_name, True, prof

        # Level 2: 题材自适应职衔称谓正则剥离与同姓歧义安全熔断
        prefixes = self.genre_pack.get_title_prefixes()
        suffixes = self.genre_pack.get_title_suffixes()
        # 兜底并集：合并历史明清/现代通用称谓（保持100%向下兼容）
        legacy_prefixes = ["老", "小", "阿", "大", "锦衣卫", "东厂", "提督", "掌柜", "刺客", "头领", "周", "张", "李", "王", "刘", "陈", "杨", "赵", "黄"]
        legacy_suffixes = ["大人", "公公", "姑娘", "公子", "师傅", "总管", "队", "队长", "警官", "处长", "局长", "主任", "官", "哥", "姐"]
        all_prefixes = sorted(set(prefixes + legacy_prefixes), key=len, reverse=True)
        all_suffixes = sorted(set(suffixes + legacy_suffixes), key=len, reverse=True)

        prefix_pattern = f"^({'|'.join(re.escape(p) for p in all_prefixes)})+"
        suffix_pattern = f"({'|'.join(re.escape(s) for s in all_suffixes)})+$"

        stripped_name = re.sub(prefix_pattern, "", clean_name).strip()
        stripped_name = re.sub(suffix_pattern, "", stripped_name).strip()

        # 支持 2.1: 叠词爱称解析（如“晚晚” -> 核心字“晚”）
        reduplicated_char = ""
        if len(clean_name) == 2 and clean_name[0] == clean_name[1]:
            reduplicated_char = clean_name[0]

        if stripped_name or reduplicated_char:
            match_candidates: list[tuple[str, dict[str, Any]]] = []
            for cid, prof in self.known_chars.items():
                c_name = prof.get("name", "")
                if not c_name:
                    continue
                # 规则 A: 剥离称谓后完全相等 (如 "周队长" 剥离后为 "周"，若库中名字恰好为单字 "周")
                if stripped_name and stripped_name == c_name:
                    match_candidates.append((c_name, prof))
                # 规则 B: 单字姓氏模糊匹配 (如 "周队" 剥离后为 "周"，库中有 "周衍")
                elif stripped_name and len(stripped_name) == 1 and c_name.startswith(stripped_name):
                    match_candidates.append((c_name, prof))
                # 规则 C: 叠词爱称归并 (如 "晚晚" -> "晚" in "林晚")
                elif reduplicated_char and reduplicated_char in c_name:
                    match_candidates.append((c_name, prof))
                # 规则 D: 多字主干包含 (如 "小林晚" 剥离后为 "林晚")
                elif stripped_name and len(stripped_name) >= 2 and (stripped_name in c_name or c_name in stripped_name):
                    match_candidates.append((c_name, prof))

            # 【防呆核心机制·同姓歧义自动熔断】
            # 若候选角色库中存在多个符合条件的同姓/同字人物（例如同时有"周衍"与"周正国"），
            # 绝对禁止贪婪单字模糊匹配，防止父子或上下级角色串号！
            if len(match_candidates) == 1:
                target_cname, target_prof = match_candidates[0]
                logger.info(
                    "【角色归一化 L2 安全消歧命中】原称谓 [%s] (主干/叠词: %s) -> 安全唯一映射至已知角色 [%s]",
                    clean_name, stripped_name or reduplicated_char, target_cname,
                )
                return target_cname, True, target_prof
            elif len(match_candidates) > 1:
                logger.warning(
                    "【角色归一化 L2 同姓歧义熔断】称谓 [%s] 命中多位潜在角色 %s，启动安全熔断，放弃模糊推断以防串号",
                    clean_name, [c[0] for c in match_candidates],
                )

        # Level 3: 未在库中命中，判定为真实当集新登场实体 (标记待增量入库)
        logger.debug("【角色归一化 L3 新实体判定】候选角色 [%s] 经三级漏斗核验确认为当集全新实体", clean_name)
        return clean_name, False, None

    def normalize_prop_name(
        self,
        raw_name: str,
        associated_char_name: str | None = None,
    ) -> tuple[str, bool, dict[str, Any] | None]:
        """道具三级归一化与随身物品反向嗅探。

        包含排他性修饰语相斥检测与核心词干安全对齐，杜绝同类不同道具误合并。
        """
        clean_name = str(raw_name).strip()
        if not clean_name:
            return "UNKNOWN_PROP", False, None

        props_registry = self.known_envs_props.get("props") or {}

        # 排他性修饰特征字典（颜色、材质、属性相斥检测）
        EXCLUSIVE_MODIFIERS = (
            "黑", "白", "红", "蓝", "黄", "绿", "金", "银", "木", "铁", "铜", "钢", "塑料", "纸", "牛皮纸",
        )

        # Level 1: 精确名称或已有注册 aliases 匹配
        for pid, pprof in props_registry.items():
            if isinstance(pprof, dict):
                p_name = pprof.get("name", "")
                aliases = pprof.get("aliases", [])
                if isinstance(aliases, str):
                    aliases = [aliases]
                if clean_name == p_name or clean_name in aliases:
                    logger.debug("【道具归一化 L1 精确命中】原名 [%s] -> 命中库中已知物证 [%s]", clean_name, p_name)
                    return p_name, True, pprof

        # Level 2: 字面双向包含与排他性修饰语检测 (Core Stem Safe Matching)
        for pid, pprof in props_registry.items():
            if isinstance(pprof, dict):
                p_name = pprof.get("name", "")
                if not p_name:
                    continue
                # 判断双向包含
                if clean_name in p_name or p_name in clean_name:
                    # 【防呆核心机制·排他性修饰语相斥检测】
                    # 如果两者各自带有冲突的颜色或材质修饰（如"白色信封" vs "带血的牛皮纸信封"），
                    # 严禁自动合并，确保不同阵营/主人的道具独立存在！
                    c_mods = {m for m in EXCLUSIVE_MODIFIERS if m in clean_name}
                    p_mods = {m for m in EXCLUSIVE_MODIFIERS if m in p_name}
                    # 若双方均有修饰词且存在排他性不一致，禁止合并
                    if c_mods and p_mods and c_mods != p_mods:
                        logger.debug(
                            "【道具归一化 L2 排他拦截】[%s](修饰:%s) 与库中物证 [%s](修饰:%s) 存在材质/颜色冲突，保持独立",
                            clean_name, c_mods, p_name, p_mods,
                        )
                        continue

                    logger.info(
                        "【道具归一化 L2 安全包含归并】原道具名 [%s] 安全合并归入物证 [%s]",
                        clean_name, p_name,
                    )
                    return p_name, True, pprof

        # Level 3: 角色随身物品反向嗅探 (如通用道具"药丸/刀"，结合角色反向查其随身道具)
        if associated_char_name:
            std_char, exists, char_prof = self.normalize_character_name(associated_char_name)
            if exists and char_prof:
                portable = char_prof.get("portable_props") or char_prof.get("anchored_items") or []
                for item in portable:
                    item_str = item if isinstance(item, str) else item.get("name", "")
                    if clean_name in item_str or item_str in clean_name:
                        logger.info(
                            "【道具归一化 L3 角色随身物嗅探】道具 [%s] 命中角色 [%s] 随身物 [%s]",
                            clean_name, std_char, item_str,
                        )
                        return item_str, True, {"name": item_str, "parent_character": std_char}

        return clean_name, False, None

    def normalize_environment_name(self, raw_name: str) -> tuple[str, bool, dict[str, Any] | None]:
        """场景名称归一化。"""
        clean_name = str(raw_name).strip()
        if not clean_name:
            return "UNKNOWN_ENV", False, None

        envs_registry = self.known_envs_props.get("environments") or {}

        # Level 1: 精确匹配
        for eid, eprof in envs_registry.items():
            if isinstance(eprof, dict):
                e_name = eprof.get("name", "")
                if clean_name == e_name or clean_name in eprof.get("aliases", []):
                    return e_name, True, eprof

        # Level 2: 空间词双向包含 (如 "废弃破庙" 与 "破庙大堂")
        for eid, eprof in envs_registry.items():
            if isinstance(eprof, dict):
                e_name = eprof.get("name", "")
                if e_name and (clean_name in e_name or e_name in clean_name):
                    return e_name, True, eprof

        return clean_name, False, None

    @classmethod
    def resolve_character_name(
        cls,
        candidate_name: str,
        existing_char_names: set[str] | list[str],
        alias_map: dict[str, str] | None = None,
        genre_pack: BaseGenrePack | None = None,
        drama_genre: str = "custom",
    ) -> str:
        """【类级别快捷方法】归纳消歧角色名称，带同姓多实体自动熔断保护。

        Args:
            candidate_name: 待消歧候选角色名（如“周队”、“晚晚”）。
            existing_char_names: 当前已知的核心角色全名集合（如 {"周衍", "林晚"}）。
            alias_map: 可选扫描器逆向分析出的别名反查字典。
            genre_pack: 可选题材包，用于获取前缀与后缀。
            drama_genre: 题材类型字符串。

        Returns:
            str: 若安全唯一定位到已知角色，返回其标准主名；若触发同姓熔断或无匹配，返回 candidate_name。
        """
        clean_name = str(candidate_name).strip()
        if not clean_name:
            return ""

        existing_set = {str(n).strip() for n in existing_char_names if str(n).strip()}
        if clean_name in existing_set:
            return clean_name

        # 1. 扫描器别名映射精确匹配
        if alias_map and clean_name in alias_map:
            target_name = alias_map[clean_name]
            if target_name in existing_set:
                return target_name

        # 2. 题材称谓与通用职衔剥离
        gp = genre_pack or get_genre_pack(drama_genre=drama_genre)
        prefixes = gp.get_title_prefixes()
        suffixes = gp.get_title_suffixes()
        all_prefixes = sorted(set(prefixes + ["老", "小", "阿", "大"]), key=len, reverse=True)
        all_suffixes = sorted(set(suffixes + ["大人", "公公", "姑娘", "公子", "师傅", "总管", "队", "队长", "警官", "处长", "局长", "主任", "官", "哥", "姐"]), key=len, reverse=True)

        prefix_pattern = f"^({'|'.join(re.escape(p) for p in all_prefixes)})+"
        suffix_pattern = f"({'|'.join(re.escape(s) for s in all_suffixes)})+$"

        stripped_name = re.sub(prefix_pattern, "", clean_name).strip()
        stripped_name = re.sub(suffix_pattern, "", stripped_name).strip()

        # 支持叠词爱称解析（如“晚晚” -> 核心字“晚”）
        reduplicated_char = ""
        if len(clean_name) == 2 and clean_name[0] == clean_name[1]:
            reduplicated_char = clean_name[0]

        if stripped_name or reduplicated_char:
            match_candidates: list[str] = []
            for c_name in existing_set:
                if stripped_name and stripped_name == c_name:
                    match_candidates.append(c_name)
                elif stripped_name and len(stripped_name) == 1 and c_name.startswith(stripped_name):
                    match_candidates.append(c_name)
                elif reduplicated_char and reduplicated_char in c_name:
                    match_candidates.append(c_name)
                elif stripped_name and len(stripped_name) >= 2 and (stripped_name in c_name or c_name in stripped_name):
                    match_candidates.append(c_name)

            # 同姓多实体歧义自动熔断
            if len(match_candidates) == 1:
                return match_candidates[0]
            elif len(match_candidates) > 1:
                logger.warning(
                    "【角色归一化快捷消歧·同姓熔断】候选名 [%s] 命中多位潜在角色 %s，启动安全熔断放弃模糊匹配",
                    clean_name, match_candidates,
                )

        return clean_name

    @classmethod
    def resolve_prop_name(
        cls,
        candidate_name: str,
        existing_prop_names: set[str] | list[str],
        screenplay_text: str = "",
    ) -> str:
        """【类级别快捷方法】归纳消歧道具名称，带排他性修饰语相斥保护。

        Args:
            candidate_name: 待消歧候选道具名（如“信封”）。
            existing_prop_names: 当前已知的核心物证全名集合（如 {"带血的牛皮纸信封"}）。
            screenplay_text: 可选文学剧本正文。

        Returns:
            str: 若安全归并入某核心母物证，返回母物证全名；若存在相斥修饰词或无从属关系，返回 candidate_name。
        """
        clean_name = str(candidate_name).strip()
        if not clean_name:
            return ""

        existing_set = {str(n).strip() for n in existing_prop_names if str(n).strip()}
        if clean_name in existing_set:
            return clean_name

        # 排他性修饰特征字典（颜色、材质相斥拦截）
        EXCLUSIVE_MODIFIERS = (
            "黑", "白", "红", "蓝", "黄", "绿", "金", "银", "木", "铁", "铜", "钢", "塑料", "纸", "牛皮纸",
        )

        # 双向包含与词干匹配判定（优先匹配已有集合中最长的全称物证）
        sorted_existings = sorted(existing_set, key=len, reverse=True)
        for p_name in sorted_existings:
            if clean_name in p_name or p_name in clean_name:
                c_mods = {m for m in EXCLUSIVE_MODIFIERS if m in clean_name}
                p_mods = {m for m in EXCLUSIVE_MODIFIERS if m in p_name}
                if c_mods and p_mods and c_mods != p_mods:
                    # 存在相斥修饰词（如“白信封”vs“黑信封”），严禁合并
                    continue
                # 无论谁包含谁，返回信息密度更高、更长的全称
                return p_name if len(p_name) >= len(clean_name) else clean_name

        return clean_name




class MorphStateMachine:
    """剧情语义驱动的多形态分级派生状态机。
    
    根据大模型提取的客观剧情物理切片（伤情、动作、交互、微距）及 Scanner 后端特征，
    确定性派生一级（基准）、二级（表演/局部机位/破坏物证）、三级（战损/手部特写）四段式规范资产：
    - 角色：
      * T1_BASE (Tier 1 基准肖像立绘，t2i，无父级依赖)；
      * T3_STATUS_INJURED (Tier 3 战伤态，i2i，挂载 T1_BASE，denoise=0.45)；
      * T3_MACRO_HAND (Tier 3 关键手部特写，i2i，挂载 T1_BASE，denoise=0.55)；
    - 场景：
      * T1_WIDE (Tier 1 全景基准机位，t2i，无父级依赖)；
      * Z01_ZONE (Tier 2 局部功能子机位，i2i/t2i，挂载 T1_WIDE，denoise=0.40)；
    - 道具：
      * S0_STATIC (Tier 1 基础完好底模，t2i，无父级依赖)；
      * S1_ACTION (Tier 2 破坏/形变/交互态，i2i，挂载 S0_STATIC，denoise=0.50)。
    """

    @classmethod
    def derive_character_morphs(
        cls,
        char_name: str,
        motion_slice: dict[str, Any],
        is_existing: bool,
        char_profile: dict[str, Any] | None = None,
        scanner_injuries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        morphs: list[dict[str, Any]] = []
        token = AssetProtocolHelper.chinese_to_token(char_name)
        base_id = (
            char_profile.get("character_code")
            or char_profile.get("asset_id")
            or f"CHAR_{token}_T1_BASE_PORTRAIT"
            if is_existing and char_profile
            else AssetProtocolHelper.generate_deterministic_id("CHAR", char_name, "T1_BASE")
        )

        # 1. 必选 Tier 1 基础肖像立绘态 (T1_BASE)
        morphs.append({
            "asset_id": base_id,
            "category": "CHAR",
            "name": char_name,
            "form": "T1_BASE",
            "tier": "T1",
            "is_benchmark": 1,
            "generation_mode": "t2i",
            "parent_asset_id": None,
            "parent_asset_key": None,
            "denoising_strength": 0.0,
            "motion_slice": motion_slice,
            "is_new": not is_existing,
        })
        logger.debug("【形态状态机】派生角色一级基准资产: %s -> %s (T1_BASE)", char_name, base_id)

        # 2. Tier 3 战损/负伤态判定 (T3_STATUS_INJURED)
        wounds = str(motion_slice.get("physical_wounds", "")).strip()
        has_injury = bool(wounds and wounds not in ("无", "none", "null")) or bool(scanner_injuries)
        if has_injury:
            injured_id = AssetProtocolHelper.generate_deterministic_id("CHAR", char_name, "T3_STATUS_INJURED")
            injury_detail = wounds if wounds and wounds not in ("无", "none", "null") else (", ".join(scanner_injuries) if scanner_injuries else "战损创伤")
            morphs.append({
                "asset_id": injured_id,
                "category": "CHAR",
                "name": char_name,
                "form": "T3_STATUS_INJURED",
                "tier": "T3",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.45,
                "motion_slice": {**motion_slice, "physical_wounds": injury_detail},
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发战损派生角色三级资产: %s -> %s (父级=%s, denoise=0.45)", char_name, injured_id, base_id)

        # 3. Tier 3 手部特写/微距态判定 (T3_MACRO_HAND)
        motion = str(motion_slice.get("current_motion", "")).strip()
        if any(kw in motion for kw in ("握", "持", "拿", "拔", "刺", "抓", "指", "扣", "按", "掏", "递")):
            macro_id = AssetProtocolHelper.generate_deterministic_id("CHAR", char_name, "T3_MACRO_HAND")
            morphs.append({
                "asset_id": macro_id,
                "category": "CHAR",
                "name": char_name,
                "form": "T3_MACRO_HAND",
                "tier": "T3",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.55,
                "motion_slice": motion_slice,
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发手部动作派生三级特写资产: %s -> %s (父级=%s, denoise=0.55)", char_name, macro_id, base_id)

        return morphs

    @classmethod
    def derive_environment_morphs(
        cls,
        env_name: str,
        env_slice: dict[str, Any],
        is_existing: bool,
        env_profile: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        morphs: list[dict[str, Any]] = []
        token = AssetProtocolHelper.chinese_to_token(env_name)
        base_id = (
            env_profile.get("scene_code")
            or env_profile.get("asset_id")
            or f"ENV_{token}_T1_WIDE"
            if is_existing and env_profile
            else AssetProtocolHelper.generate_deterministic_id("ENV", env_name, "T1_WIDE")
        )

        # 1. 必选 Tier 1 场景全景主机位 (T1_WIDE)
        morphs.append({
            "asset_id": base_id,
            "category": "ENV",
            "name": env_name,
            "form": "T1_WIDE",
            "tier": "T1",
            "is_benchmark": 1,
            "generation_mode": "t2i",
            "parent_asset_id": None,
            "parent_asset_key": None,
            "denoising_strength": 0.0,
            "env_slice": env_slice,
            "is_new": not is_existing,
        })
        logger.debug("【形态状态机】派生场景一级全景资产: %s -> %s (T1_WIDE)", env_name, base_id)

        # 2. Tier 2 局部功能子机位区域 (Z01_ZONE)
        sub_spot = str(env_slice.get("sub_zone_spot", "")).strip()
        if sub_spot and sub_spot not in ("无", "none", "全景"):
            zone_id = AssetProtocolHelper.generate_deterministic_id("ENV", env_name, "Z01_ZONE")
            morphs.append({
                "asset_id": zone_id,
                "category": "ENV",
                "name": f"{env_name}_{sub_spot}",
                "form": "Z01_ZONE",
                "tier": "T2",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.40,
                "env_slice": env_slice,
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发子区域机位派生二级资产: %s -> %s (父级=%s, denoise=0.40)", env_name, zone_id, base_id)

        return morphs

    @classmethod
    def derive_prop_morphs(
        cls,
        prop_name: str,
        prop_slice: dict[str, Any],
        is_existing: bool,
        prop_profile: dict[str, Any] | None = None,
        is_deformed_in_scanner: bool = False,
    ) -> list[dict[str, Any]]:
        morphs: list[dict[str, Any]] = []
        token = AssetProtocolHelper.chinese_to_token(prop_name)
        base_id = (
            prop_profile.get("prop_code")
            or prop_profile.get("asset_id")
            or f"PROP_{token}_T1_STATIC"
            if is_existing and prop_profile
            else AssetProtocolHelper.generate_deterministic_id("PROP", prop_name, "S0_STATIC")
        )

        # 1. 必选 Tier 1 标准完好底模 (S0_STATIC)
        morphs.append({
            "asset_id": base_id,
            "category": "PROP",
            "name": prop_name,
            "form": "S0_STATIC",
            "tier": "T1",
            "is_benchmark": 1,
            "generation_mode": "t2i",
            "parent_asset_id": None,
            "parent_asset_key": None,
            "denoising_strength": 0.0,
            "prop_slice": prop_slice,
            "is_new": not is_existing,
        })
        logger.debug("【形态状态机】派生道具一级静态底模: %s -> %s (S0_STATIC)", prop_name, base_id)

        # 2. Tier 2 破坏/形变/交互动作态 (S1_ACTION)
        damage_state = str(prop_slice.get("damage_state", "")).upper()
        if damage_state in ("DAMAGED", "ACTION", "BROKEN", "BURNT") or is_deformed_in_scanner:
            action_id = AssetProtocolHelper.generate_deterministic_id("PROP", prop_name, "S1_ACTION")
            morphs.append({
                "asset_id": action_id,
                "category": "PROP",
                "name": prop_name,
                "form": "S1_ACTION",
                "tier": "T2",
                "is_benchmark": 0,
                "generation_mode": "i2i",
                "parent_asset_id": base_id,
                "parent_asset_key": base_id,
                "denoising_strength": 0.50,
                "prop_slice": prop_slice,
                "is_new": not is_existing,
            })
            logger.debug("【形态状态机】触发物证破坏态派生二级动作资产: %s -> %s (父级=%s, denoise=0.50)", prop_name, action_id, base_id)

        return morphs



