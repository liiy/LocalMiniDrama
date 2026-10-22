"""阶段 6 电影美术逆向置景推理与特殊元素双态解耦引擎 (Cinematic Set Dressing Reasoner)。

本模块实现：
1. 动作反推支撑面 (Action-to-Surface Backtracking): 依据剧本动作逆向推导物理落脚点与接触面；
2. 文化与类型制式对齐 (Cultural Paradigm Alignment): 自动补齐特定叙事场景（如灵堂、病房、天台）的三维全套陈设；
3. 五层空间蓝图构建 (Five-Layer Spatial Blueprint): 输出 L1-L5 工业级视听拓扑；
4. 特殊画中人/遗像双态解耦 (Portrait Decoupling Engine):
   - 环境全景融合态：相框挽黑纱与玻璃烛火倒影固化在场景 L2；
   - 特写与物证解耦态：独立派生 PROP_FUNERAL_PORTRAIT 道具卡，严密对齐脸模与跨阶段引用。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.tools.screenplay_feature_scanner import _slugify_chinese

logger = logging.getLogger("lmd.stage6.cinematic_reasoner")


class CinematicSetDressingReasoner:
    """电影美术逆向置景推理与特殊元素解耦引擎。"""

    # 经典空间文化与类型制式知识库
    CULTURAL_PARADIGMS: dict[str, dict[str, Any]] = {
        "灵堂": {
            "L1_architecture": "开间坐北朝南旧式厅堂，青砖木梁挑高，正对厚重双开木门与通风格栅窗，对流穿堂风贯穿",
            "L2_fixed_dressings": [
                "正中沉重实木黑漆供桌",
                "横置深色实木灵柩棺木",
                "供桌中央摆放挽黑纱实木相框（玻璃表面有微弱倒影）",
                "供桌前地面生锈铸铁火盆",
                "两只白烛插在锡制烛台上",
                "悬挂微垂的白色祭幡与白布挽联",
            ],
            "L3_material_patina": "青石板或斑驳水泥地面散落未燃尽的纸灰与香灰，墙角脱落的白灰与斑驳潮湿霉痕",
            "L4_optics_microclimate": "穿堂冷风掀起祭幡角，白烛火苗微弱剧烈跳跃，青白烟缕在微光中悬浮打转，冷暖色温剧烈对撞",
            "L5_acoustics_damping": "空旷厅堂封闭混响（RT60~1.3s），纸灰燃烧轻微劈啪爆裂声与窗缝呼啸风声",
            "support_surfaces": ["供桌台面", "地面青石板", "棺木表面"],
            "openings": ["双开破损木门", "高处木格通风窗"],
        },
        "病房": {
            "L1_architecture": "标准矩形双开间病房，苍白防尘漆墙面，带有铝合金推拉磨砂玻璃窗与防火木门",
            "L2_fixed_dressings": [
                "医用不锈钢可调病床",
                "床头固定式氧气与负压吸引终端导轨",
                "移动式输液吊架挂着输液软袋",
                "床头塑料储物柜摆放保温水壶与药盒",
            ],
            "L3_material_patina": "浅灰色PVC防静电胶地板带轮椅推行轻微划痕，床头柜角有长期84消毒水擦拭导致的轻微泛黄脱色",
            "L4_optics_microclimate": "冷白4000K荧光灯漫射照明，窗外阴天冷光与室内日光灯混合，空气微冷且静止",
            "L5_acoustics_damping": "平滑硬质墙面反射（RT60~0.8s），监护仪规律微弱心率嘀声与静音走针声",
            "support_surfaces": ["病床台面", "床头储物柜面", "PVC地板"],
            "openings": ["走廊推拉门", "铝合金外窗"],
        },
        "天台": {
            "L1_architecture": "高层建筑开敞式水泥天台，四周有一米二高度浇筑水泥或锈蚀铁栏杆防护墙，带防火出入铁门",
            "L2_fixed_dressings": [
                "生锈粗壮通风管道与巨型排风机箱",
                "废弃的水泥预制板与堆叠空木箱",
                "斑驳生锈的避雷引下线接地铜排",
            ],
            "L3_material_patina": "沥青防水层起皮开裂长出杂草，栏杆粗糙剥落红丹漆，暴晒与雨水冲刷形成深黑色水渍泪痕",
            "L4_optics_microclimate": "开阔高空侧风强烈拂动衣角，日光强烈直射形成锐利深黑硬阴影，地表热浪微弱空气折射",
            "L5_acoustics_damping": "无遮挡开阔声场（近乎零混响），高空强风呼啸穿过铁栏杆产生空腔共鸣哨音",
            "support_surfaces": ["水泥天台地面", "防护矮墙顶面", "排风箱顶板"],
            "openings": ["天台安全通道铁门"],
        },
        "审讯室": {
            "L1_architecture": "密闭长方形无窗或高位窄百叶窗空间，四壁覆盖深灰或灰白吸音冲孔阻燃软包",
            "L2_fixed_dressings": [
                "加重固定式铁质或厚木审讯桌",
                "被讯问人软包约束椅与审讯人员高背靠椅",
                "墙角立杆固定广角监控红外摄像头",
                "墙面镶嵌单向透视隔音镀膜大玻璃",
            ],
            "L3_material_patina": "桌面有金属手铐长期磕碰形成的凹陷划痕，软包表面有手指抠擦痕迹，地毯轻微踩踏磨损",
            "L4_optics_microclimate": "正上方单盏高亮聚光筒灯直射桌面形成强明暗对比，四角处于压抑半阴影，空气干燥浑浊",
            "L5_acoustics_damping": "极高吸音率与低残响（RT60<0.3s），语声干涩凝滞，纸张翻动与手铐链条轻微脆响被锐利放大",
            "support_surfaces": ["固定审讯桌面", "约束椅把手", "吸音地毯地面"],
            "openings": ["厚重隔音防火防盗门"],
        },
    }

    @classmethod
    def reason_five_layer_blueprint(
        cls,
        scene_name: str,
        screenplay_text: str = "",
        detected_anchors: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构建场景五层视听空间蓝图 (5-Layer Spatial Blueprint)。

        执行步骤：
        1. 命中预设文化/空间制式知识库（如“灵堂”）；
        2. 结合剧本动作反推支撑面与交互陈设；
        3. 融入扫描算子捕获的确定性空间锚点；
        4. 输出标准 L1~L5 五层视听拓扑字典。
        """
        clean_name = str(scene_name or "").strip()
        matched_paradigm = None
        for p_key, p_val in cls.CULTURAL_PARADIGMS.items():
            if p_key in clean_name:
                matched_paradigm = p_val
                break

        # 扫描算子捕获的物理锚点
        detected_dressings = (detected_anchors or {}).get("fixed_set_dressings", [])
        detected_openings = (detected_anchors or {}).get("openings_and_acoustics", [])
        detected_materials = (detected_anchors or {}).get("material_surfaces", [])

        # 动态动作反推支撑面
        inferred_supports: list[str] = []
        if screenplay_text:
            if re.search(r"跪|扑倒|摔在|滚落|踩在", screenplay_text):
                inferred_supports.append("地面/地砖")
            if re.search(r"拍在|按在|放在|置于|推向.*桌", screenplay_text):
                inferred_supports.append("桌面/供桌")
            if re.search(r"靠在|撞在|贴在.*墙", screenplay_text):
                inferred_supports.append("墙体表面")

        if matched_paradigm:
            l1 = matched_paradigm["L1_architecture"]
            # 整合固定陈设
            base_dressings = list(matched_paradigm["L2_fixed_dressings"])
            for dd in detected_dressings:
                if dd not in base_dressings and not any(dd in bd for bd in base_dressings):
                    base_dressings.append(dd)
            l2_str = "；".join(base_dressings)
            l3 = matched_paradigm["L3_material_patina"]
            if detected_materials:
                l3 += f"，表面材质包含: {', '.join(detected_materials)}"
            l4 = matched_paradigm["L4_optics_microclimate"]
            l5 = matched_paradigm["L5_acoustics_damping"]
            openings = list(matched_paradigm["openings"])
            for do in detected_openings:
                if do not in openings:
                    openings.append(do)
        else:
            # 通用置景逻辑推导
            l1 = f"{clean_name}的开间建筑框架，包含主要出入通道与采光视窗"
            base_dressings = detected_dressings or [f"{clean_name}核心功能家具与陈列"]
            l2_str = "；".join(base_dressings)
            l3 = f"{clean_name}真实生活使用痕迹，地面与墙角有自然磨损包浆"
            if detected_materials:
                l3 += f"，包含{', '.join(detected_materials)}"
            l4 = "自然采光与环境室内光斑交织，空气层次通透"
            l5 = "标准室内自然混响声场"
            openings = detected_openings or ["进出通道木门"]

        blueprint = {
            "L1_architecture": l1,
            "L2_fixed_dressings": l2_str,
            "L3_material_patina": l3,
            "L4_optics_microclimate": l4,
            "L5_acoustics_damping": l5,
            "support_surfaces": list(set((matched_paradigm["support_surfaces"] if matched_paradigm else []) + inferred_supports)),
            "openings": openings,
        }
        logger.debug(
            "【电影美术置景推理】场景 [%s] 完成五层空间蓝图推导: 固定陈设=%s, 出入口=%s",
            clean_name, l2_str, openings,
        )
        return blueprint

    @classmethod
    def detect_and_decouple_portrait_elements(
        cls,
        screenplay_text: str,
        scene_name: str,
        known_characters: list[dict[str, Any]] | None = None,
        episode_num: int = 1,
    ) -> list[dict[str, Any]]:
        """检测并解耦剧本中的特殊画中人/遗像元素 (Special Portrait Decoupling)。

        规则：
        1. 检查剧本文本中是否存在“遗像”、“遗照”、“肖像”、“相框里的照片”；
        2. 识别被画中描绘的目标角色（如“苏秀兰黑白遗像” -> 对应死者“苏秀兰”）；
        3. 自动派生专用的独立剧情物证卡 `PROP_FUNERAL_PORTRAIT`，供阶段 7 的特写/POV 镜头挂接；
        4. 场景底图则保持环境融合态（相框+黑纱+远景倒影），互不干扰。

        Returns:
            list[dict[str, Any]]: 解耦出的独立物证道具档案列表。
        """
        if not screenplay_text:
            return []

        PORTRAIT_PATTERNS = [
            r"【?([^\s，。！？、）)】\]]{2,12}?)(?:的)?(?:黑白)?(?:遗像|遗照|相片|肖像)(?:玻璃框|镜框)?】?",
        ]

        decoupled_props: list[dict[str, Any]] = []
        found_targets: set[str] = set()

        known_names: list[str] = []
        if known_characters:
            for kc in known_characters:
                kn = kc.get("name") if isinstance(kc, dict) else str(kc)
                if kn and len(kn.strip()) >= 2:
                    known_names.append(kn.strip())

        for pat in PORTRAIT_PATTERNS:
            for match in re.finditer(pat, screenplay_text):
                raw_target = match.group(1).strip()
                # 优先匹配已知角色清单
                target_matched = None
                for kn in known_names:
                    if kn in raw_target:
                        target_matched = kn
                        break

                if target_matched:
                    clean_target = target_matched
                else:
                    # 清洗前导动词、介词与修饰语
                    clean_target = re.sub(r"^[^\u4e00-\u9fa5]+", "", raw_target).strip()
                    clean_target = re.sub(
                        r"^(?:.*?(?:甩在|贴在|摆在|挂在|落在|放在|靠在|立在|按在|拍在|砸在|摆着|挂着|放着|靠着|供着|立着|印着|刻着|啪地|狠狠地|桌上|正中|墙上|中央))+",
                        "",
                        clean_target,
                    ).strip()
                    clean_target = re.sub(
                        r"^(?:在|向|到|出|前|上|下|里|中|为|由|给|的|地|老旧的|那张|那幅|框里|相框)+",
                        "",
                        clean_target,
                    ).strip()
                    if not clean_target or clean_target in ("黑白", "一张", "那个", "此人"):
                        clean_target = "死者"

                if clean_target in found_targets:
                    continue
                found_targets.add(clean_target)

                # 生成解耦道具档案
                prop_slug = _slugify_chinese(f"{clean_target}_yixiang")
                if not prop_slug or prop_slug == "UNKNOWN":
                    prop_slug = "FUNERAL_PORTRAIT"
                prop_code = f"PROP_{prop_slug}"

                dossier = {
                    "prop_id": prop_code,
                    "prop_code": prop_code,
                    "name": f"{clean_target}黑白遗像物证",
                    "prop_name": f"{clean_target}黑白遗像物证",
                    "level": "hero_tier1",
                    "type": "narrative_reversal",
                    "category": "hero",
                    "importance": "high",
                    "first_appearance_episode": episode_num,
                    "discovered_in_stage": 6,
                    "benchmark_asset_key": f"{prop_code}_S0_STATIC",
                    "is_portrait_decoupled": True,
                    "portrait_source_role": clean_target,
                    "description": (
                        f"第{episode_num}集核心案情物证【{clean_target}黑白遗像物证】：精细黑白人像照片，"
                        f"装在挽黑纱的实木镜框内，玻璃表面有烛光微弱倒影与轻微划痕，专用于分镜特写与POV物证审视。"
                    ),
                    "visual_prompt": (
                        f"cinematic macro close up of a framed black and white funeral portrait of {clean_target}, "
                        f"high contrast vintage monochrome photography, authentic paper grain, "
                        f"encased in dark lacquered wooden picture frame with subtle black mourning ribbon sash, "
                        f"delicate reflection of flickering candlelight on glass surface, photorealistic 8k, tack sharp focus"
                    ),
                    "physical_specs": {
                        "material_damage_dimensions": "玻璃相框边缘微磨损，黑纱缎带自然褶皱，相纸泛黄",
                        "weight_and_haptic_resistance": "7寸实木玻璃相框，重量约450g，持握手感沉稳",
                        "foley_boost_db": "+2.5dB 相框木质触碰与玻璃轻扣声",
                    },
                    "damage_states": [
                        {
                            "state_code": f"{prop_code}_S0",
                            "state_label": f"{clean_target}黑白遗像静态完好物证",
                            "damage_level": 0,
                            "parent_state_id": None,
                            "narrative_point": f"第{episode_num}集案情物证审视基准",
                            "visual_prompt": (
                                f"cinematic macro close up of {clean_target} black and white funeral photo in wooden frame, "
                                f"flickering candle light reflection on glass, high fidelity 8k"
                            ),
                            "is_benchmark": 1,
                        }
                    ],
                    "detail_views": [
                        {
                            "view_type": "macro_detail",
                            "view_label": f"{clean_target}遗像面部与相纸质感微距特写",
                            "asset_key": f"{prop_code}_S0_DETAIL",
                            "parent_asset_key": f"{prop_code}_S0_STATIC",
                            "generation_mode": "t2i",
                            "denoise_strength": 0.0,
                            "image_prompt": (
                                f"extreme close up on the monochrome portrait photo of {clean_target}, "
                                f"vintage silver halide grain texture, sharp eyes, slight reflection, 8k"
                            ),
                            "is_benchmark": 1,
                            "is_primary": 1,
                        }
                    ],
                    "screenplay_evidence": f"从场景【{scene_name}】中解耦画中人物证: 【{match.group(0)}】",
                }
                decoupled_props.append(dossier)
                logger.info(
                    "【电影美术置景推理·遗像解耦】成功从剧本/场景 [%s] 解耦画中人物证道具 [%s (%s)], 目标原型: %s",
                    scene_name, dossier["name"], prop_code, clean_target,
                )

        return decoupled_props
