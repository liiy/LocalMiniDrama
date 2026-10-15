# -*- coding: utf-8 -*-
"""资产切片多维智能补全与融合算子 (AssetSliceEnricher)。

本模块专为阶段 6 (Stage 6 Asset Truth Extraction) 研发，实现动静双层特征融合：
当文学剧本未涉及角色外貌骨相、服饰材质、发型，或场景建筑规制、道具微观材质等静态属性时，
程序自动从阶段 2 (角色档案库) 与阶段 3 (场景/道具总库) 的基准档案中继承补齐，
并与当集剧本所提炼出的动态剧情切片（如战伤、微表情、手持动词、子机位、空间痕迹、破损态）紧密熔接，
确保生成的文生图 (T2I) 与图生图 (I2I) 提示词具备充分的细节深度与全剧长效视觉一致性。
"""

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AssetSliceEnricher:
    """资产切片多维智能补全与融合算子。

    当单集文学剧本未涉及外貌骨相、服饰材质、建筑形制或道具微观细节时，
    自动从阶段 2 (角色) 与阶段 3 (场景/道具) 的基准档案中继承补齐。
    """

    # 弱描述特征正则表达式匹配（常见的大模型简写或敷衍性回复词）
    WEAK_PATTERNS = re.compile(
        r"^(|无|未提及|未知|常规|标准|普通|正常|自然|自然站立|默认|标准服饰|常规服饰|普通衣服)$",
        re.IGNORECASE,
    )

    @classmethod
    def is_weak_or_missing(cls, val: Optional[str]) -> bool:
        """判定切片字段是否为空或属于无效弱描述。

        Args:
            val: 待检测的文本字符串。

        Returns:
            bool: 若为空、长度过短或符合弱描述正则，则返回 True，代表需要触发继承补全。
        """
        if not val or not isinstance(val, str):
            return True
        cleaned = val.strip()
        if len(cleaned) < 4:
            return True
        return bool(cls.WEAK_PATTERNS.match(cleaned))

    @classmethod
    def enrich_character_slice(
        cls,
        raw_char: Dict[str, Any],
        stage2_dossier: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """融合补全角色切片。

        将当集提取的角色动态切片与阶段 2 角色档案融合。若骨相、服饰面料、发型等静态属性缺失，
        则从阶段 2 基准档案中自动回退继承。

        Args:
            raw_char: 大模型从当集剧本提取的角色原始切片。
            stage2_dossier: 阶段 2 产出的该角色官方定型基准档案 (若有)。

        Returns:
            Dict[str, Any]: 融合后的高保真角色切片。
        """
        enriched = raw_char.copy()
        cname = str(enriched.get("character_name") or enriched.get("name") or "未知角色").strip()

        if not stage2_dossier:
            logger.debug("【特征补齐】角色 [%s] 未检索到阶段 2 基准档案，保留原始切片描述", cname)
            return enriched

        # 1. 骨相五官与发型继承补齐
        if cls.is_weak_or_missing(enriched.get("facial_bone_structure")):
            vis_code = stage2_dossier.get("visual_consistency_code") or {}
            base_face = (
                stage2_dossier.get("facial_bone_structure")
                or (vis_code.get("facial_bone_structure") if isinstance(vis_code, dict) else None)
                or stage2_dossier.get("appearance")
                or f"{cname}的既定面部几何骨相与自然发丝细节"
            )
            enriched["facial_bone_structure"] = str(base_face).strip()
            logger.debug("【特征补齐】角色 [%s] 继承阶段 2 骨相五官: %s", cname, base_face)

        # 2. 服饰材质与层叠继承补齐
        if cls.is_weak_or_missing(enriched.get("costume_and_materials")):
            vis_code = stage2_dossier.get("visual_consistency_code") or {}
            base_costume = (
                stage2_dossier.get("costume_description")
                or stage2_dossier.get("clothing_style")
                or stage2_dossier.get("stage_a_clothing")
                or (vis_code.get("stage_a_clothing") if isinstance(vis_code, dict) else None)
                or "标准写实影视服饰面料，纹理层次细腻"
            )
            enriched["costume_and_materials"] = str(base_costume).strip()
            logger.debug("【特征补齐】角色 [%s] 继承阶段 2 服饰材质: %s", cname, base_costume)

        # 3. 声学原型与试音台本兜底继承
        if cls.is_weak_or_missing(enriched.get("timbre_archetype")):
            if stage2_dossier.get("timbre_archetype"):
                enriched["timbre_archetype"] = stage2_dossier["timbre_archetype"]
                logger.debug("【特征补齐】角色 [%s] 继承阶段 2 声学原型: %s", cname, enriched["timbre_archetype"])

        return enriched

    @classmethod
    def enrich_environment_slice(
        cls,
        raw_env: Dict[str, Any],
        stage3_scene_dossier: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """融合补全场景环境切片。

        若当集剧本未详细刻画主场景的建筑规制、材质年代感或基础光影，
        则从阶段 3 场景总库中自动回退继承。

        Args:
            raw_env: 大模型从当集剧本提取的场景环境原始切片。
            stage3_scene_dossier: 阶段 3 场景档案库中的基准档案 (若有)。

        Returns:
            Dict[str, Any]: 融合后的高保真场景切片。
        """
        enriched = raw_env.copy()
        sname = str(enriched.get("scene_name") or enriched.get("name") or "未知场景").strip()

        if not stage3_scene_dossier:
            logger.debug("【特征补齐】场景 [%s] 未检索到阶段 3 基准档案，保留原始切片描述", sname)
            return enriched

        # 1. 建筑规制与风格继承补齐
        if cls.is_weak_or_missing(enriched.get("architectural_style")):
            base_arch = (
                stage3_scene_dossier.get("architectural_style")
                or stage3_scene_dossier.get("spatial_type")
                or stage3_scene_dossier.get("spatial_traits")
                or f"{sname}的固定建筑空间结构与材质风貌"
            )
            enriched["architectural_style"] = str(base_arch).strip()
            logger.debug("【特征补齐】场景 [%s] 继承阶段 3 建筑规制: %s", sname, base_arch)

        # 2. 光影氛围兜底继承
        if cls.is_weak_or_missing(enriched.get("lighting_and_atmosphere")):
            base_lighting = (
                stage3_scene_dossier.get("lighting_atmosphere")
                or stage3_scene_dossier.get("lighting_and_atmosphere")
                or "戏剧性电影环境光影，冷暖对比与空间层次分明"
            )
            enriched["lighting_and_atmosphere"] = str(base_lighting).strip()
            logger.debug("【特征补齐】场景 [%s] 继承阶段 3 光影氛围: %s", sname, base_lighting)

        return enriched

    @classmethod
    def enrich_prop_slice(
        cls,
        raw_prop: Dict[str, Any],
        stage3_prop_dossier: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """融合补全道具物证切片。

        若当集剧本未详细说明核心道具的微观材质纹理、反光率或工艺细节，
        则从阶段 3 道具总库中自动回退继承。

        Args:
            raw_prop: 大模型从当集剧本提取的道具原始切片。
            stage3_prop_dossier: 阶段 3 道具档案库中的基准档案 (若有)。

        Returns:
            Dict[str, Any]: 融合后的高保真道具切片。
        """
        enriched = raw_prop.copy()
        pname = str(enriched.get("raw_name") or enriched.get("name") or "未知道具").strip()

        if not stage3_prop_dossier:
            logger.debug("【特征补齐】道具 [%s] 未检索到阶段 3 基准档案，保留原始切片描述", pname)
            return enriched

        # 1. 材质纹理与微观细节继承补齐
        if cls.is_weak_or_missing(enriched.get("material_details")):
            base_mat = (
                stage3_prop_dossier.get("material_details")
                or stage3_prop_dossier.get("material")
                or stage3_prop_dossier.get("description")
                or f"{pname}的标志性工艺结构与材质质感"
            )
            enriched["material_details"] = str(base_mat).strip()
            logger.debug("【特征补齐】道具 [%s] 继承阶段 3 工艺材质: %s", pname, base_mat)

        # 2. 物证类别兜底
        if cls.is_weak_or_missing(enriched.get("category")):
            enriched["category"] = stage3_prop_dossier.get("category", "hero")

        return enriched
