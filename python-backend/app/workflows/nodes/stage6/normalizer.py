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
    ):
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

    def normalize_character_name(self, raw_name: str) -> tuple[str, bool, dict[str, Any] | None]:
        """三级归一化角色名称。
        
        返回: (standard_name, is_existing, matched_char_profile)
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
                    return target_name, True, prof

        # 1.2 库中别名字段匹配
        for cid, prof in self.known_chars.items():
            c_name = prof.get("name", "")
            aliases = prof.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            if clean_name == c_name or clean_name in aliases:
                return c_name, True, prof

        # Level 2: 常见职衔称谓正则剥离与双向包含命中
        # 剥离前缀: 锦衣卫/东厂/提督/掌柜/大人/刺客/头领/老/小
        # 剥离后缀: 大人/公公/姑娘/公子/师傅/总管
        stripped_name = re.sub(r"^(锦衣卫|东厂|提督|掌柜|刺客|头领|老|小)+", "", clean_name).strip()
        stripped_name = re.sub(r"(大人|公公|姑娘|公子|师傅|总管)+$", "", stripped_name).strip()
        if stripped_name:
            for cid, prof in self.known_chars.items():
                c_name = prof.get("name", "")
                if not c_name:
                    continue
                if stripped_name == c_name or stripped_name in c_name or c_name in stripped_name:
                    return c_name, True, prof

        # Level 3: 未在库中命中，判定为真实当集新登场实体 (标记待增量入库)
        return clean_name, False, None

    def normalize_prop_name(
        self,
        raw_name: str,
        associated_char_name: str | None = None,
    ) -> tuple[str, bool, dict[str, Any] | None]:
        """道具三级归一化与随身物品反向嗅探。"""
        clean_name = str(raw_name).strip()
        if not clean_name:
            return "UNKNOWN_PROP", False, None

        props_registry = self.known_envs_props.get("props") or {}

        # Level 1: 精确名称或已有注册匹配
        for pid, pprof in props_registry.items():
            if isinstance(pprof, dict):
                p_name = pprof.get("name", "")
                if clean_name == p_name or clean_name in pprof.get("aliases", []):
                    return p_name, True, pprof

        # Level 2: 字面双向包含
        for pid, pprof in props_registry.items():
            if isinstance(pprof, dict):
                p_name = pprof.get("name", "")
                if p_name and (clean_name in p_name or p_name in clean_name):
                    return p_name, True, pprof

        # Level 3: 角色随身物品反向嗅探 (如通用道具"药丸/刀"，结合角色反向查其随身道具)
        if associated_char_name:
            std_char, exists, char_prof = self.normalize_character_name(associated_char_name)
            if exists and char_prof:
                portable = char_prof.get("portable_props") or char_prof.get("anchored_items") or []
                for item in portable:
                    item_str = item if isinstance(item, str) else item.get("name", "")
                    if clean_name in item_str or item_str in clean_name:
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



