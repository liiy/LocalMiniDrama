# -*- coding: utf-8 -*-
"""阶段 6 确定性多级资产触发与派生算子引擎 (AssetTriggerOperatorEngine)。

本模块承担“神经-符号”二段式分工架构中的符号算子执行层：
1. 接收大模型提纯的离散语义特征标签（Semantic Features）与文学剧本正文；
2. 依据电影工业级触发算子协议，执行【A. 角色资产算子】、【B. 场景资产算子】与【C. 道具资产算子】；
3. 执行规则决策、层级隔离与命名空间校验，确保“按需触发、动态衍生、零冗余资产”；
4. 提供基于正则与动作关键词库的启发式双重兜底扫描（Heuristic Fallback）。
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("app.workflows.operators.asset_trigger_operator_engine")


class AssetTriggerOperatorEngine:
    """多级影视视听资产触发与派生算子引擎。"""

    # --- 角色触发关键词库 (Character Trigger Lexicons) ---
    FOUR_VIEW_KEYWORDS: Dict[str, List[str]] = {
        "FRONT": ["正面", "抬头", "直视", "走近", "迎面", "站立", "正视", "转过身正面", "面向镜头"],
        "PROFILE": ["侧脸", "转头", "避开目光", "侧目", "向侧", "倚靠", "扭头", "侧向", "别过头"],
        "3Q": ["斜视", "侧身", "3/4", "回眸", "半侧", "侧转", "斜睨", "余光", "偷瞄"],
        "BACK": ["背对", "背影", "转身离去", "后背", "远去", "倒下背后", "背向镜头", "甩开大步离开"],
    }

    EMOTION_KEYWORDS: Dict[str, List[str]] = {
        "RAGE": ["咬牙", "青筋", "怒吼", "死死咬紧", "暴怒", "后槽牙", "厉声", "双目赤红", "怒目"],
        "FEAR": ["瞳孔收缩", "发抖", "惨白", "冷汗", "倒退", "惊恐", "战栗", "哆嗦", "倒吸凉气"],
        "GRIEF": ["眼泪打转", "哽咽", "落泪", "抽泣", "泪水决堤", "悲痛", "眼眶泛红"],
        "SUPPRESSED": ["面无表情", "眼神冰冷", "压抑", "冷笑", "下颌紧绷", "面冷如铁", "不动声色"],
    }

    LIGHTING_KEYWORDS: Dict[str, List[str]] = {
        "FLASH": ["手电筒直射", "强光照脸", "闪光", "车灯直射", "刺眼白光", "聚光灯"],
        "LOWKEY": ["阴暗", "侧逆光", "硬阴影", "月光", "烛光", "剪影", "晦暗", "微弱火光", "逆光"],
    }

    MACRO_HAND_KEYWORDS: List[str] = [
        "手指", "掐掌心", "拉扯线头", "握住", "拿打火机", "指关节", "攥紧", "抚摸", "掌心", "食指扣动", "撕开", "翻看"
    ]

    INJURY_KEYWORDS: List[str] = [
        "淤青", "流血", "夹伤", "撕裂", "湿透", "创口", "血痕", "骨折", "擦伤", "渗血", "血迹斑斑"
    ]

    # --- 场景触发关键词库 (Scene Trigger Lexicons) ---
    SCENE_WIDE_KEYWORDS: List[str] = [
        "远景", "全貌", "俯瞰", "大楼", "大门", "进站", "全景", "俯瞰全景", "鸟瞰", "建筑外观", "空旷原野"
    ]

    SCENE_INSERT_KEYWORDS: List[str] = [
        "水龙头滴水", "挂钟秒针", "电表箱", "特写空镜", "烟灰缸残烟", "摇晃的灯泡", "窗台水珠"
    ]

    # --- 道具触发关键词库 (Prop Trigger Lexicons) ---
    PROP_DEFORMATION_KEYWORDS: List[str] = [
        "撕", "砸", "切", "断", "烧", "挑开", "崩碎", "撬开", "撞烂", "踩碎", "捏扁", "斩断", "扯烂", "撕开"
    ]

    PERSONAL_PROP_NAMES: Set[str] = {
        "打火机", "戒指", "手表", "创可贴", "银手链", "钢笔", "项链", "耳钉", "钥匙扣", "怀表"
    }

    AMBIENT_PROP_NAMES: Set[str] = {
        "冷水饺", "茶杯", "螺丝刀", "碗筷", "垃圾桶", "纸巾", "塑料袋", "水壶", "筷子", "剩菜"
    }

    # =========================================================================
    # A. 角色资产识别与触发算子 (Character Trigger Operators)
    # =========================================================================

    @classmethod
    def evaluate_character_assets(
        cls,
        character_name: str,
        canonical_id: str,
        semantic_data: Dict[str, Any],
        screenplay_text: str = "",
    ) -> List[Dict[str, Any]]:
        """执行【A. 角色资产识别与触发算子】。
        
        Args:
            character_name: 角色名称。
            canonical_id: 角色规范化标识（如 CHAR_SHENLIAN）。
            semantic_data: LLM 提取的离散语义数据。
            screenplay_text: 文学剧本原文（用于启发式兜底）。
        
        Returns:
            生成的角色多级资产配置列表。
        """
        logger.debug(
            "【算子引擎·角色算子】启动评估: 角色=%s, ID=%s, 语义数据=%s",
            character_name, canonical_id, semantic_data,
        )
        assets: List[Dict[str, Any]] = []

        # 1. 出场判定：提取与当前角色相关的动作行与证据
        evidence = str(semantic_data.get("in_screenplay_evidence") or "").strip()
        gaze_set: Set[str] = set(semantic_data.get("gaze_orientations") or [])
        emotion_cues: Set[str] = set(semantic_data.get("emotion_cues") or [])
        lighting_cues: Set[str] = set(semantic_data.get("lighting_conditions") or [])
        has_macro_hand = bool(semantic_data.get("has_macro_hand", False))
        injuries: List[str] = list(semantic_data.get("injuries") or [])

        # 启发式双重兜底 (Heuristic Fallback)：扫描证据短句与剧本上下文
        context_corpus = f"{evidence} {screenplay_text}"

        # 默认必备：T1 角色主基准图 (Default Base Asset)
        assets.append({
            "asset_key": f"{canonical_id}_T1_BASE",
            "tier": "Tier1",
            "form": "BASE",
            "trigger_reason": "核心登场角色必选标准全身基准图",
            "motion_slice": semantic_data,
        })

        # 2. 四视角触发算子
        # 2.1 FRONT: 正面全景
        if "front" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["FRONT"]):
            assets.append({
                "asset_key": f"{canonical_id}_T1_4V_FRONT_FULL",
                "tier": "Tier1",
                "form": "4V_FRONT",
                "trigger_reason": "动作行命中正面直视/走近等指令，触发正面全景图",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 T1_4V_FRONT_FULL", character_name)

        # 2.2 PROFILE: 正侧脸
        if "profile" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["PROFILE"]):
            assets.append({
                "asset_key": f"{canonical_id}_T2_4V_PROFILE",
                "tier": "Tier2",
                "form": "4V_PROFILE",
                "trigger_reason": "动作行命中侧脸/转头/避开目光，触发侧视视线微调图",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 T2_4V_PROFILE", character_name)

        # 2.3 3Q: 3/4 侧身
        if "three_quarter" in gaze_set or "3q" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["3Q"]):
            assets.append({
                "asset_key": f"{canonical_id}_T2_4V_3Q",
                "tier": "Tier2",
                "form": "4V_3Q",
                "trigger_reason": "动作行命中斜视/半侧/回眸，触发3/4侧身阶段造型",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 T2_4V_3Q", character_name)

        # 2.4 BACK: 背对/背影
        if "back" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["BACK"]):
            assets.append({
                "asset_key": f"{canonical_id}_T2_4V_BACK",
                "tier": "Tier2",
                "form": "4V_BACK",
                "trigger_reason": "动作行命中背对/转身离去/后背，触发背影视线微调图",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 T2_4V_BACK", character_name)

        # 3. 情绪触发算子 (仅生成剧本出现的情绪)
        for emo_type, kw_list in cls.EMOTION_KEYWORDS.items():
            if emo_type.lower() in [e.lower() for e in emotion_cues] or any(kw in context_corpus for kw in kw_list):
                assets.append({
                    "asset_key": f"{canonical_id}_T2_EXP_{emo_type}",
                    "tier": "Tier2",
                    "form": f"EXP_{emo_type}",
                    "trigger_reason": f"扫描到剧本中强情绪表达 [{emo_type}]，触发情绪分支造型",
                    "motion_slice": semantic_data,
                })
                logger.debug("【算子引擎·角色情绪】角色 [%s] 触发 T2_EXP_%s", character_name, emo_type)
                break  # 避免同集单角色生成过多表情资产，取最高优先级爆发情绪

        # 4. 光感触发算子
        if "flash_light" in lighting_cues or any(kw in context_corpus for kw in cls.LIGHTING_KEYWORDS["FLASH"]):
            assets.append({
                "asset_key": f"{canonical_id}_T2_LIGHT_FLASH",
                "tier": "Tier2",
                "form": "LIGHT_FLASH",
                "trigger_reason": "命中强光直射/闪光，触发高反差光影分支",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色光感】角色 [%s] 触发 T2_LIGHT_FLASH", character_name)
        elif "lowkey" in lighting_cues or any(kw in context_corpus for kw in cls.LIGHTING_KEYWORDS["LOWKEY"]):
            assets.append({
                "asset_key": f"{canonical_id}_T2_LIGHT_LOWKEY",
                "tier": "Tier2",
                "form": "LIGHT_LOWKEY",
                "trigger_reason": "命中阴暗/硬阴影/侧逆光，触发剪影暗调分支",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色光感】角色 [%s] 触发 T2_LIGHT_LOWKEY", character_name)

        # 5. 微距与伤残触发算子
        if has_macro_hand or any(kw in context_corpus for kw in cls.MACRO_HAND_KEYWORDS):
            assets.append({
                "asset_key": f"{canonical_id}_T3_MACRO_HAND",
                "tier": "Tier3",
                "form": "MACRO_HAND",
                "trigger_reason": "命中手部特写微动作（握持/掐掌心/翻弄），触发手部微距资产",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色微距】角色 [%s] 触发 T3_MACRO_HAND", character_name)

        if injuries or any(kw in context_corpus for kw in cls.INJURY_KEYWORDS):
            assets.append({
                "asset_key": f"{canonical_id}_T3_STATUS_INJURED",
                "tier": "Tier3",
                "form": "STATUS_INJURED",
                "trigger_reason": "扫描到负伤/流血/撕裂痕迹，强制触发战损状态分支",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色战损】角色 [%s] 触发 T3_STATUS_INJURED", character_name)

        return assets

    # =========================================================================
    # B. 场景资产识别与触发算子 (Environment Trigger Operators)
    # =========================================================================

    @classmethod
    def evaluate_environment_assets(
        cls,
        scene_name: str,
        canonical_id: str,
        semantic_data: Dict[str, Any],
        screenplay_text: str = "",
    ) -> List[Dict[str, Any]]:
        """执行【B. 场景资产识别与触发算子】。
        
        Args:
            scene_name: 场景名称。
            canonical_id: 场景规范化标识（如 ENV_LINGTANG）。
            semantic_data: 场景离散语义数据。
            screenplay_text: 文学剧本原文。
        
        Returns:
            生成的场景多级资产配置列表。
        """
        logger.debug(
            "【算子引擎·场景算子】启动评估: 场景=%s, ID=%s, 语义数据=%s",
            scene_name, canonical_id, semantic_data,
        )
        assets: List[Dict[str, Any]] = []

        evidence = str(semantic_data.get("in_screenplay_evidence") or "").strip()
        is_wide = bool(semantic_data.get("is_wide_establishing", False))
        dialogue_count = int(semantic_data.get("dialogue_count", 0))
        insert_shots: List[str] = list(semantic_data.get("insert_shots") or [])
        is_minor = bool(semantic_data.get("is_minor_transitional_scene", False))

        context_corpus = f"{evidence} {screenplay_text}"

        # 规则 5：全剧仅出现 1-2 镜的次要过渡场景 ➔ 仅触发 ENV_<ID>_T2_KEYFRAME (单张关键帧)
        if is_minor:
            assets.append({
                "asset_key": f"{canonical_id}_T2_KEYFRAME",
                "tier": "Tier2",
                "form": "KEYFRAME",
                "trigger_reason": "判定为短促次要过渡场景，仅触发单张关键帧，阻断多余景别冗余生成",
                "env_slice": semantic_data,
            })
            logger.info("【算子引擎·场景】场景 [%s] 为过场次要场景，仅生成 T2_KEYFRAME", scene_name)
            return assets

        # 规则 1 & 2.1: 远景/全貌/俯瞰 ➔ 触发 ENV_<ID>_T1_WIDE (全景建立图)
        if is_wide or any(kw in context_corpus for kw in cls.SCENE_WIDE_KEYWORDS):
            assets.append({
                "asset_key": f"{canonical_id}_T1_WIDE",
                "tier": "Tier1",
                "form": "WIDE",
                "trigger_reason": "动作行命中全貌/远景/俯瞰，触发全景建立图建立空间关系",
                "env_slice": semantic_data,
            })
            logger.debug("【算子引擎·场景】场景 [%s] 触发 T1_WIDE", scene_name)
        else:
            # 默认兜底基准图
            assets.append({
                "asset_key": f"{canonical_id}_T1_BASE",
                "tier": "Tier1",
                "form": "BASE",
                "trigger_reason": "空间主环境基准图",
                "env_slice": semantic_data,
            })

        # 规则 2.2: 场景内连续对白超过 3 句 ➔ 触发 ENV_<ID>_T1_OTS_BG (过肩景深板，自动背景虚化)
        if dialogue_count >= 3 or len(re.findall(r"^[\u4e00-\u9fa5A-Za-z0-9_]{1,10}[:：]", screenplay_text, re.M)) >= 3:
            assets.append({
                "asset_key": f"{canonical_id}_T1_OTS_BG",
                "tier": "Tier1",
                "form": "OTS_BG",
                "trigger_reason": f"场景内对白句数 ({dialogue_count}) >= 3，触发双人正反打过肩景深板",
                "env_slice": semantic_data,
            })
            logger.debug("【算子引擎·场景】场景 [%s] 触发 T1_OTS_BG", scene_name)

        # 规则 2.3: 动作行命中水龙头滴水/秒针等 ➔ 触发 ENV_<ID>_T1_INSERT_<PROP> (特写插镜)
        for insert_item in insert_shots:
            clean_item_code = re.sub(r"[^\w]", "", insert_item).upper()[:10] or "DETAIL"
            assets.append({
                "asset_key": f"{canonical_id}_T1_INSERT_{clean_item_code}",
                "tier": "Tier1",
                "form": f"INSERT_{clean_item_code}",
                "trigger_reason": f"动作行扫描到特写空镜/微观物件 [{insert_item}]，触发特写插镜",
                "env_slice": semantic_data,
            })
            logger.debug("【算子引擎·场景】场景 [%s] 触发特写插镜 T1_INSERT_%s", scene_name, clean_item_code)

        # 启发式补充扫描特写空镜
        if not insert_shots:
            for kw in cls.SCENE_INSERT_KEYWORDS:
                if kw in context_corpus:
                    clean_kw = re.sub(r"[^\w]", "", kw).upper()[:8]
                    assets.append({
                        "asset_key": f"{canonical_id}_T1_INSERT_{clean_kw}",
                        "tier": "Tier1",
                        "form": f"INSERT_{clean_kw}",
                        "trigger_reason": f"启发式规则命中特写空镜关键词 [{kw}]，触发特写插镜",
                        "env_slice": semantic_data,
                    })
                    break

        return assets

    # =========================================================================
    # C. 道具资产识别与触发算子 (Prop Trigger Operators)
    # =========================================================================

    @classmethod
    def evaluate_prop_assets(
        cls,
        prop_name: str,
        canonical_id: str,
        semantic_data: Dict[str, Any],
        screenplay_text: str = "",
    ) -> Dict[str, Any]:
        """执行【C. 道具资产识别与触发算子】。
        
        Args:
            prop_name: 道具名称。
            canonical_id: 道具规范化标识（如 PROP_BAOWENBEI）。
            semantic_data: 道具语义数据。
            screenplay_text: 文学剧本原文。
        
        Returns:
            包含生成的道具资产列表 (assets) 与是否挂载角色/剔除的裁决结果元字典。
        """
        logger.debug(
            "【算子引擎·道具算子】启动评估: 道具=%s, ID=%s, 语义数据=%s",
            prop_name, canonical_id, semantic_data,
        )
        assets: List[Dict[str, Any]] = []
        action_binding: Optional[Dict[str, Any]] = None

        raw_importance = str(semantic_data.get("importance") or "hero").lower()
        assoc_char = str(semantic_data.get("associated_character") or "").strip()
        deformation_action = str(semantic_data.get("deformation_action") or "").strip()
        is_damaged = bool(semantic_data.get("is_physically_damaged", False))

        context_corpus = f"{deformation_action} {screenplay_text}"

        # 规则 4: 扫描到生活环境杂物 (冷水饺/茶杯/螺丝刀/碗筷) ➔ 判定为三级杂物，零独立生图
        if raw_importance == "ambient" or any(kw in prop_name for kw in cls.AMBIENT_PROP_NAMES):
            logger.info("【算子引擎·道具】物体 [%s] 判定为三级生活环境杂物，执行【零独立生图】裁决，仅保留环境痕迹文本", prop_name)
            return {
                "decision": "EXCLUDED_AMBIENT",
                "assets": [],
                "bound_character": None,
                "reason": "生活环境杂物，坚决剔除独立生图",
            }

        # 规则 3: 扫描到角色随身物品 (打火机/戒指/手表/创可贴) ➔ 判定为二级锚定物，直接挂靠角色 T3_MACRO_HAND，零独立道具图
        if raw_importance == "personal" or any(kw in prop_name for kw in cls.PERSONAL_PROP_NAMES):
            logger.info("【算子引擎·道具】物体 [%s] 判定为二级角色随身物，挂靠角色 [%s] T3_MACRO_HAND，零独立道具生图", prop_name, assoc_char)
            return {
                "decision": "BOUND_TO_CHARACTER_MACRO",
                "assets": [],
                "bound_character": assoc_char,
                "reason": "角色随身私人物品，直接融入角色手部特写生图",
            }

        # 规则 1 & 2: 判定为一级核心案情物证 (hero)
        # 1. 静态初始态必出
        assets.append({
            "asset_key": f"{canonical_id}_T1_STATIC",
            "tier": "Tier1",
            "form": "STATIC",
            "trigger_reason": "核心案情物证静态初始态（未破坏标准质感展示）",
            "prop_slice": semantic_data,
        })
        logger.debug("【算子引擎·道具】核心物证 [%s] 触发静态初始态 T1_STATIC", prop_name)

        # 2. 破坏交互态判决：扫描到形变破坏动词 ➔ 强制触发 PROP_<ID>_T1_ACTION (破坏交互态)！未破坏绝不生两态！
        has_deformation_verb = any(v in context_corpus for v in cls.PROP_DEFORMATION_KEYWORDS)
        if is_damaged or has_deformation_verb:
            assets.append({
                "asset_key": f"{canonical_id}_T1_ACTION",
                "tier": "Tier1",
                "form": "ACTION",
                "trigger_reason": "命中形变破坏动词或破坏状态，强制触发破坏交互态（撕裂/破碎/凹陷）",
                "prop_slice": semantic_data,
            })
            logger.info("【算子引擎·道具】核心物证 [%s] 命中破坏形变，触发两态之【破坏交互态 T1_ACTION】", prop_name)
        else:
            logger.debug("【算子引擎·道具】核心物证 [%s] 保持完好，坚决不生成破坏态", prop_name)

        return {
            "decision": "HERO_PROP_GENERATED",
            "assets": assets,
            "bound_character": None,
            "reason": "一级核心案情物证，按破坏判定生成单态或双态",
        }
