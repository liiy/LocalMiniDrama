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
        stage_code: str = "T1",
    ) -> List[Dict[str, Any]]:
        """执行【A. 角色资产识别与触发算子】。
        
        Args:
            character_name: 角色名称。
            canonical_id: 角色规范化标识（如 CHAR_SHENLIAN）。
            semantic_data: LLM 提取的离散语义数据。
            screenplay_text: 文学剧本原文（用于启发式兜底）。
            stage_code: 角色造型形态阶段代码（如 T1, T2, T3，默认 T1）。
        
        Returns:
            生成的角色多级资产配置列表。
        """
        logger.debug(
            "【算子引擎·角色算子】启动评估: 角色=%s, ID=%s, 阶段=%s, 语义数据=%s",
            character_name, canonical_id, stage_code, semantic_data,
        )
        assets: List[Dict[str, Any]] = []

        # 归一化阶段代码
        stg = str(stage_code or "T1").strip().upper()
        if not stg.startswith("T") and stg.isdigit():
            stg = f"T{stg}"
        elif not stg.startswith("T") and stg in ("BASE", "DEFAULT", "ORIGIN"):
            stg = "T1"

        is_t1 = (stg == "T1")
        base_asset_key = f"{canonical_id}_{stg}_BASE_PORTRAIT"
        t1_root_face_key = f"{canonical_id}_T1_BASE_PORTRAIT"
        front_full_key = f"{canonical_id}_{stg}_4V_FRONT_FULL"

        # 三级谱系阶段前缀：T1 基准阶段下，Tier 2 视角/表情/光效挂载 T2 前缀，Tier 3 微观/战损挂载 T3 前缀
        t2_stg = "T2" if is_t1 else stg
        t3_stg = "T3" if is_t1 else stg

        # 1. 出场判定：提取与当前角色相关的动作行与证据
        evidence = str(semantic_data.get("in_screenplay_evidence") or "").strip()
        gaze_set: Set[str] = set(semantic_data.get("gaze_orientations") or [])
        emotion_cues: Set[str] = set(semantic_data.get("emotion_cues") or [])
        lighting_cues: Set[str] = set(semantic_data.get("lighting_conditions") or [])
        has_macro_hand = bool(semantic_data.get("has_macro_hand", False))
        injuries: List[str] = list(semantic_data.get("injuries") or [])

        # 启发式双重兜底 (Heuristic Fallback)：扫描证据短句与剧本上下文
        context_corpus = f"{evidence} {screenplay_text}"

        # 默认必备：角色主基准图 (Tier 1 纯面部基准肖像，或 T2/T3 阶段基准)
        # 严格作为全剧 FaceID 根节点: 仅 T1_BASE_PORTRAIT 纯面部肖像 parent_asset_key 为 None, is_benchmark = 1, generation_mode = 't2i'
        # 其余阶段 (T2/T3) 基准图必须作为图生图 i2i 挂载 T1_BASE_PORTRAIT，保证面相特征 100% 一致
        assets.append({
            "asset_key": base_asset_key,
            "tier": "Tier1" if is_t1 else "Tier2",
            "form": f"{stg}_BASE_PORTRAIT",
            "parent_asset_key": None if is_t1 else t1_root_face_key,
            "input_source_image": None if is_t1 else t1_root_face_key,
            "identity_reference": None if is_t1 else t1_root_face_key,
            "generation_mode": "t2i" if is_t1 else "i2i",
            "control_type": None,
            "denoise_strength": 0.0 if is_t1 else 0.35,
            "is_benchmark": 1 if is_t1 else 0,
            "trigger_reason": "核心登场角色必选标准纯面部基准图 (FaceID 根节点)" if is_t1 else f"角色换装/成长造型基准图 (i2i 继承自 {t1_root_face_key})",
            "motion_slice": semantic_data,
        })

        # 2. 四视角触发算子 (严格三级阶梯拓扑图 DAG Execution)
        # 2.1 FRONT: 正面全景立绘 (Tier 2.1: i2i + ControlNet OpenPose 强约束 + FaceID 注入 T1)
        has_front_full = False
        if "front" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["FRONT"]):
            has_front_full = True
            assets.append({
                "asset_key": front_full_key,
                "tier": "Tier2",
                "form": "4V_FRONT",
                "parent_asset_key": base_asset_key,
                "input_source_image": base_asset_key,  # 垫图当前阶段基准肖像
                "identity_reference": t1_root_face_key,  # FaceID 强注入 T1
                "generation_mode": "i2i",  # 严格纠正为 i2i，绝不可为 t2i
                "control_type": "controlnet_openpose",  # OpenPose 强约束全身站姿
                "denoise_strength": 0.40,
                "is_benchmark": 0,
                "trigger_reason": "动作行命中正面直视/走近等指令，触发正面立绘全身图 (ControlNet OpenPose + FaceID 注入 T1)",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 %s (Tier2.1), 挂靠父级=%s", character_name, front_full_key, base_asset_key)

        # 决定全身衍生视角的阶梯父级母图 (Ladder Parent for Full-Body):
        # 优先以正面全身立绘为母图 (保持服装版型、材质、鞋履 100% 一致)；若本集未触发正面全身，平滑安全回退至当前阶段 BASE
        full_body_parent_key = front_full_key if has_front_full else base_asset_key

        # 2.2 PROFILE: 正侧脸/侧身 (Tier 2.2: 阶梯挂靠在正面全身立绘，i2i 垫图 T2.1，杜绝图生图衣服换款变色)
        if "profile" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["PROFILE"]):
            profile_key = f"{canonical_id}_{t2_stg}_4V_PROFILE"
            assets.append({
                "asset_key": profile_key,
                "tier": "Tier2",
                "form": "4V_PROFILE",
                "parent_asset_key": full_body_parent_key,
                "input_source_image": full_body_parent_key,
                "identity_reference": t1_root_face_key,
                "generation_mode": "i2i",
                "control_type": "i2i_silhouette",
                "denoise_strength": 0.38,
                "is_benchmark": 0,
                "trigger_reason": "动作行命中侧脸/转头/避开目光，触发侧视视线微调图 (i2i 垫图正面立绘)",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 %s (Tier2.2), 阶梯挂靠父级=%s", character_name, profile_key, full_body_parent_key)

        # 2.3 3Q: 3/4 侧身 (Tier 2.2: 阶梯挂靠在正面全身立绘)
        if "three_quarter" in gaze_set or "3q" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["3Q"]):
            q3_key = f"{canonical_id}_{t2_stg}_4V_3Q"
            assets.append({
                "asset_key": q3_key,
                "tier": "Tier2",
                "form": "4V_3Q",
                "parent_asset_key": full_body_parent_key,
                "input_source_image": full_body_parent_key,
                "identity_reference": t1_root_face_key,
                "generation_mode": "i2i",
                "control_type": "i2i_silhouette",
                "denoise_strength": 0.38,
                "is_benchmark": 0,
                "trigger_reason": "动作行命中斜视/半侧/回眸，触发3/4侧身阶段造型 (i2i 垫图正面立绘)",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 %s (Tier2.2), 阶梯挂靠父级=%s", character_name, q3_key, full_body_parent_key)

        # 2.4 BACK: 背对/背影 (Tier 2.2: 阶梯挂靠在正面全身立绘)
        if "back" in gaze_set or any(kw in context_corpus for kw in cls.FOUR_VIEW_KEYWORDS["BACK"]):
            back_key = f"{canonical_id}_{t2_stg}_4V_BACK"
            assets.append({
                "asset_key": back_key,
                "tier": "Tier2",
                "form": "4V_BACK",
                "parent_asset_key": full_body_parent_key,
                "input_source_image": full_body_parent_key,
                "identity_reference": t1_root_face_key,
                "generation_mode": "i2i",
                "control_type": "i2i_silhouette",
                "denoise_strength": 0.38,
                "is_benchmark": 0,
                "trigger_reason": "动作行命中背对/转身离去/后背，触发背影视线微调图 (i2i 垫图正面立绘)",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色视角】角色 [%s] 触发 %s (Tier2.2), 阶梯挂靠父级=%s", character_name, back_key, full_body_parent_key)

        # 3. 情绪触发算子 (Tier 3.1: 面部局部微表情重绘 Inpaint，严格挂靠在纯面部肖像 base_asset_key)
        for emo_type, kw_list in cls.EMOTION_KEYWORDS.items():
            if emo_type.lower() in [e.lower() for e in emotion_cues] or any(kw in context_corpus for kw in kw_list):
                exp_key = f"{canonical_id}_{t2_stg}_EXP_{emo_type}"
                assets.append({
                    "asset_key": exp_key,
                    "tier": "Tier3",
                    "form": f"EXP_{emo_type}",
                    "parent_asset_key": base_asset_key,
                    "input_source_image": base_asset_key,
                    "identity_reference": t1_root_face_key,
                    "generation_mode": "inpaint",
                    "control_type": "inpaint_face_mask",
                    "denoise_strength": 0.40,
                    "is_benchmark": 0,
                    "trigger_reason": f"扫描到剧本中强情绪表达 [{emo_type}]，触发局部微表情 Inpaint 重绘",
                    "motion_slice": semantic_data,
                })
                logger.debug("【算子引擎·角色情绪】角色 [%s] 触发 %s (Tier3.1), 局部重绘挂靠面部基准=%s", character_name, exp_key, base_asset_key)
                break  # 避免同集单角色生成过多表情资产，取最高优先级爆发情绪

        # 4. 光感触发算子
        if "flash_light" in lighting_cues or any(kw in context_corpus for kw in cls.LIGHTING_KEYWORDS["FLASH"]):
            flash_key = f"{canonical_id}_{t2_stg}_LIGHT_FLASH"
            assets.append({
                "asset_key": flash_key,
                "tier": "Tier2",
                "form": "LIGHT_FLASH",
                "parent_asset_key": full_body_parent_key,
                "input_source_image": full_body_parent_key,
                "identity_reference": t1_root_face_key,
                "generation_mode": "i2i",
                "control_type": "i2i",
                "denoise_strength": 0.42,
                "is_benchmark": 0,
                "trigger_reason": "命中强光直射/闪光，触发高反差光影分支",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色光感】角色 [%s] 触发 %s", character_name, flash_key)
        elif "lowkey" in lighting_cues or any(kw in context_corpus for kw in cls.LIGHTING_KEYWORDS["LOWKEY"]):
            lowkey_key = f"{canonical_id}_{t2_stg}_LIGHT_LOWKEY"
            assets.append({
                "asset_key": lowkey_key,
                "tier": "Tier2",
                "form": "LIGHT_LOWKEY",
                "parent_asset_key": full_body_parent_key,
                "input_source_image": full_body_parent_key,
                "identity_reference": t1_root_face_key,
                "generation_mode": "i2i",
                "control_type": "i2i",
                "denoise_strength": 0.42,
                "is_benchmark": 0,
                "trigger_reason": "命中阴暗/硬阴影/侧逆光，触发剪影暗调分支",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色光感】角色 [%s] 触发 %s", character_name, lowkey_key)

        # 5. 微距与伤残触发算子 (Tier 3.2: 挂靠在全身立绘 full_body_parent_key，局部重绘保持穿戴质感一致)
        if has_macro_hand or any(kw in context_corpus for kw in cls.MACRO_HAND_KEYWORDS):
            hand_key = f"{canonical_id}_{t3_stg}_MACRO_HAND"
            assets.append({
                "asset_key": hand_key,
                "tier": "Tier3",
                "form": "MACRO_HAND",
                "parent_asset_key": full_body_parent_key,
                "input_source_image": full_body_parent_key,
                "identity_reference": t1_root_face_key,
                "generation_mode": "inpaint",
                "control_type": "inpaint_body_mask",
                "denoise_strength": 0.45,
                "is_benchmark": 0,
                "trigger_reason": "命中手部特写微动作（握持/掐掌心/翻弄），触发手部微距局部重绘",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色微距】角色 [%s] 触发 %s (Tier3.2), 局部重绘挂靠父级=%s", character_name, hand_key, full_body_parent_key)

        if injuries or any(kw in context_corpus for kw in cls.INJURY_KEYWORDS):
            inj_key = f"{canonical_id}_{t3_stg}_STATUS_INJURED"
            assets.append({
                "asset_key": inj_key,
                "tier": "Tier3",
                "form": "STATUS_INJURED",
                "parent_asset_key": full_body_parent_key,
                "input_source_image": full_body_parent_key,
                "identity_reference": t1_root_face_key,
                "generation_mode": "inpaint",
                "control_type": "inpaint_body_mask",
                "denoise_strength": 0.45,
                "is_benchmark": 0,
                "trigger_reason": "扫描到负伤/流血/撕裂痕迹，强制触发战损状态局部重绘分支",
                "motion_slice": semantic_data,
            })
            logger.debug("【算子引擎·角色战损】角色 [%s] 触发 %s (Tier3.2), 局部重绘挂靠父级=%s", character_name, inj_key, full_body_parent_key)

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
