"""阶段 2：角色人物建模与四元心理、微观生物肖像骨相与生活质感服化道代码节点 (Stage 2 Character Node)。

本模块是整套工业化剧本引擎与视听资产一致性的【生物级真理源】：
1. 彻底根除“AI塑料脸与磨皮假面”：锁定毫米级骨相结构、真实毛孔、痣与旧伤疤物理坐标、眼唇微观解剖与发质；
2. 彻底根除“崭新塑料布感”：锁定面料克重(g/m²)、自然折痕、线头脱落尺寸、摩擦泥斑与磨损鞋靴；
3. 建立深层人物弧光与双轨关系：心理四元组 (Want/Need/Lie/Ghost)、语言指纹与应激微动作、随身携带锚定旧物、双轨人际张力与4阶段弧光轨迹；
4. 全量向下游阶段（空间同源做旧、分集大纲伏笔、工笔文学剧本、SD/ComfyUI提示词编译、口型动力学）穿透输出。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from app.schemas.script_graph_state import (
    BiologicalPortraitDNA,
    CarriedAnchorItem,
    CharacterProfile,
    DualTrackRelationshipItem,
    EmotionalArcTrajectory,
    IndustrialDramaState,
    LivedInCostumeSpecs,
    PsychologicalQuadruple,
    VoiceBehavioralFingerprint,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE2_SYSTEM_PROMPT,
    STAGE2_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage2_character")


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _stage2_fallback(title: str, logline: str) -> dict[str, Any]:
    """【规则编号: STAGE-2-COT-01 ~ STAGE-2-COT-04】当大模型离线或解析异常时的保底生成工厂。"""
    logger.debug(f"[Stage 2 Fallback] Synthesizing character engine fallback for: '{title}'.")
    
    # 动态尝试从标题与 logline 提取人名或设定特征
    combined_text = f"{title} {logline}"
    names_found = re.findall(r"(?:[向周沈陆顾林叶韩苏陈张楚谢徐江秦][一-龥]{1,2})", combined_text)
    
    protagonist_name = names_found[0] if names_found else "陆沉"
    antagonist_name = names_found[1] if len(names_found) > 1 and names_found[1] != protagonist_name else "韩泰"

    return {
        "characters": [
            {
                # 【规则编号: STAGE-2-COT-01】生理性别强制声明 (防性别幻觉与配音错乱)
                "name": protagonist_name,
                "role_type": "protagonist",
                "gender": "male",
                "biological_sex": "male",
                "personality": f"敏锐隐忍，极度自律但负罪感深重，围绕《{title}》追寻终极真相",
                "appearance": "三十八岁，高颧骨，方正下颌，右侧额角有浅淡旧伤痕，眼神如鹰隼般锐利却满布血丝",
                "identity_anchors": ["额角浅旧伤", "深灰粗花呢大衣", "深邃双眼", "随身旧物"],
                # 【规则编号: STAGE-2-COT-03】声学人设腔体与发干瑕疵
                "voice_style": "低沉沙哑，胸腔共鸣明显，语速克制偏慢，每句话前有微小停顿",
                # 【规则编号: STAGE-2-COT-02】微观生物肖像骨相 DNA (毫米级防塑料脸)
                "biological_dna": {
                    "bone_structure": "高颧骨，骨量清晰，方正下颌角略带下压，面部折叠度高，侧脸下颌线硬朗如刀刻",
                    "skin_micro_texture": "偏干性粗糙肤质，T区有肉眼可见自然粗大毛孔与细微干纹，拒绝磨皮假面感",
                    "blemishes_and_scars": "右侧眉骨上方留有2.5cm浅白色陈旧缝合伤痕，右侧嘴角上方0.5cm处有一颗极淡暗褐小痣",
                    "eye_lip_anatomy": "内双窄眼皮，眼尾微向下垂，眼白布有3-4条清晰红血丝，瞳孔呈冷深棕色；嘴唇常年干燥起皮，下唇内侧有隐秘咬痕",
                    "hair_texture": "自然黑发夹杂约10%灰白发丝，质感粗硬自然微卷，额前有几缕冷雨打湿的碎发碎绺",
                },
                # 【规则编号: STAGE-2-COT-02】真实生活质感服化道代码 (拒绝崭新塑料布)
                "lived_in_costume": {
                    "top_wear": "深灰色重磅粗花呢大衣（600g/m²，两肘部位有久坐形成的深重自然褶皱，第二颗纽扣有2cm松脱线头垂挂）",
                    "bottom_wear": "黑色重磅斜纹棉工装裤（膝盖处略有泛白褪色，裤脚下摆沾染干涸的暗黄泥斑点）",
                    "footwear": "深棕色磨砂皮系带高帮工装靴（靴头有明显踢蹭擦痕，右脚橡胶鞋跟外侧磨损约3毫米）",
                    "wear_and_tear_details": "右侧大衣口袋边缘有钥匙长期摩擦导致的起球抽丝，领口内衬有暗黄色汗渍做旧痕迹",
                },
                # 【规则编号: STAGE-2-COT-01】心理四元组与致命谎言 (The Lie)
                "psychological_quad": {
                    "want": f"亲手揭开《{title}》背后的真凶，洗清冤屈并夺回关键证据",
                    "need": "直面当年的懦弱选择，接纳不完美的自我并完成自我救赎与灵魂解脱",
                    "lie": "只要掌控绝对理性和铁证，正义就绝不会被权势玷污，人情不过是累赘",
                    "ghost": "七年前因自己迟到五分钟，导致至亲/恩师当场罹难且现场罪证被毁",
                },
                # 【规则编号: STAGE-2-COT-03】语言指纹与应激微动作
                "voice_fingerprint": {
                    "catchphrase": "说话要有凭据，心跳可瞒不过我。",
                    "defensive_phrase": "这跟我没有任何关系，看报告说话。",
                    "stress_action": "下意识用右手食指关节轻叩左手掌心，双眼微眯瞳孔剧烈聚焦",
                    "forbidden_words": ["认命", "算了", "对不起"],
                },
                # 【规则编号: STAGE-2-COT-04】随身携带锚定旧物
                "carried_anchor_item": {
                    "item_name": "刻有划痕的旧金属信物",
                    "physical_trace": "金属边缘有严重凹陷撞痕与暗锈，指针/刻字磨损严重",
                    "emotional_significance": "至亲临终前死死攥在手心的信物，每当陷入道德困境都会下意识隔着衣料按压",
                },
                # 【规则编号: STAGE-2-COT-04】双轨关系网
                "dual_track_relationships": [
                    {
                        "target_character": antagonist_name,
                        "surface_relation": "表面维持客套礼貌与业务试探",
                        "hidden_tension": "生死宿敌，双方在每句看似体面的寒暄中互相试探生死底牌",
                    }
                ],
                # 【规则编号: STAGE-2-COT-04】四阶段动态情感弧光
                "emotional_arc_trajectories": [
                    {
                        "stage_label": "第一幕：坚冰防御期",
                        "psychological_state": "极度偏执坚信冰冷证据，排斥任何人靠近，深信理性即万能",
                        "physical_behavior_manifestation": "肢体僵硬保持两米社交距离，说话语速极快不带起伏，大衣扣子扣至最顶端",
                    },
                    {
                        "stage_label": "第二幕：信念崩解期",
                        "psychological_state": "关键铁证被权势当面销毁，Lie 受到毁灭性打击，陷入绝望暴怒",
                        "physical_behavior_manifestation": "眼神发红失焦，大衣扣子扯开，右手频繁颤抖无法精准握物",
                    },
                    {
                        "stage_label": "第三幕：灵魂重铸期",
                        "psychological_state": "承认自己的过错与无力，从单纯追逐私怨转向为了守护他人而战",
                        "physical_behavior_manifestation": "主动交托随身信物，眼神从鹰隼般的刺骨转为坚韧温和",
                    },
                    {
                        "stage_label": "第四幕：终极觉醒与救赎",
                        "psychological_state": "完成自我救赎，与执念和解，坦然直面生死绝境决战",
                        "physical_behavior_manifestation": "在生死交锋时刻嘴角浮现释然从容的淡笑，身躯挺立如铁",
                    },
                ],
            },
            {
                # 【规则编号: STAGE-2-COT-01】生理性别强制声明
                "name": antagonist_name,
                "role_type": "antagonist",
                "gender": "male",
                "biological_sex": "male",
                "personality": "表面儒雅慈善的高位掌控者，实则冷酷毒辣，视底层人命为数字筹码",
                "appearance": "五十二岁，保养得宜但难掩松弛，金丝细框眼镜，银灰三件套定制西装，眼神温润带笑却毫无温度",
                "identity_anchors": ["金丝细框眼镜", "银灰定制西服", "沉香手串", "温和假笑"],
                # 【规则编号: STAGE-2-COT-03】声学人设
                "voice_style": "温和谦逊甚至带长者慈爱感，语调轻缓悠扬，但尾音极冷",
                # 【规则编号: STAGE-2-COT-02】微观生物肖像骨相
                "biological_dna": {
                    "bone_structure": "面部骨架扁平偏宽，颧骨不高但下颌角圆润微肉，双下巴在低头时隐约浮现",
                    "skin_micro_texture": "中性偏油微松弛，眼袋明显伴有深邃鱼尾纹，两颊有轻微色素沉着斑块",
                    "blemishes_and_scars": "左侧太阳穴隐蔽发际线处有一道1cm陈旧微创疤痕",
                    "eye_lip_anatomy": "单眼皮肿眼泡，常年佩戴金丝眼镜折射冷光，眼球略显浑浊；唇色苍白偏薄，笑时嘴角上扬但眼周肌肉完全不收缩（典型假笑）",
                    "hair_texture": "两鬓斑白但打理得一丝不苟的三七分油头，发胶定型发亮，后颈发际线修剪规整",
                },
                # 【规则编号: STAGE-2-COT-02】真实生活质感服化道代码
                "lived_in_costume": {
                    "top_wear": "银灰色高定精纺羊毛三件套西装（320g/m²，袖口露出一寸法式衬衫袖口，右袖口有一滴不经意的极浅茶渍）",
                    "bottom_wear": "同色系暗条纹高定西裤（裤线锋利笔挺，但裤脚内侧有微小皮鞋摩擦痕）",
                    "footwear": "手工定制黑色牛津皮鞋（鞋面光亮如镜，但鞋底边缘有细小石子碾压擦痕）",
                    "wear_and_tear_details": "左手腕内侧西装袖口因常年盘弄手串而有轻微光泽摩擦磨损",
                },
                # 【规则编号: STAGE-2-COT-01】心理四元组
                "psychological_quad": {
                    "want": f"确保自身权势万无一失，彻底清理《{title}》所有知情者并登上名流顶峰",
                    "need": "直面内心深处对贫穷卑微出身的病态自卑与恐惧",
                    "lie": "成大事者不择手段，人命皆是代价，只要站在食物链顶端历史就由我书写",
                    "ghost": "三十年前在底层靠背叛旧友吞并第一桶金的原罪",
                },
                # 【规则编号: STAGE-2-COT-03】语言指纹
                "voice_fingerprint": {
                    "catchphrase": "年轻人，时代的大浪从不给弱者留体面。",
                    "defensive_phrase": "做人要懂得算大账，别为了一棵烂树丢了整片森林。",
                    "stress_action": "右手大拇指以极快频率疯狂抠掐手串的第三颗深痕，呼吸变重",
                    "forbidden_words": ["当年", "小作坊", "矿难", "偷"],
                },
                # 【规则编号: STAGE-2-COT-04】随身携带旧物
                "carried_anchor_item": {
                    "item_name": "百年老山檀沉香手串",
                    "physical_trace": "第三颗佛珠有一道被指甲反复抠掐出黑油的极深凹槽痕迹",
                    "emotional_significance": "每次动杀心或感到失控时下意识转动以掩盖内心的惊恐虚妄",
                },
                # 【规则编号: STAGE-2-COT-04】双轨关系网
                "dual_track_relationships": [
                    {
                        "target_character": protagonist_name,
                        "surface_relation": "表面客套赏识与合作试探",
                        "hidden_tension": f"心知对方在查《{title}》真相，暗中布局诱杀并意图将其再次构陷为替罪羊",
                    }
                ],
                # 【规则编号: STAGE-2-COT-04】四阶段动态情感弧光
                "emotional_arc_trajectories": [
                    {
                        "stage_label": "第一幕：假面菩萨期",
                        "psychological_state": "运筹帷幄傲慢从容，自信权势可以摆平一切蝼蚁",
                        "physical_behavior_manifestation": "坐姿极度舒展优雅，语调低沉慈祥，慢条斯理品茶转佛珠",
                    },
                    {
                        "stage_label": "第二幕：暗流失控期",
                        "psychological_state": f"发现{protagonist_name}撕开证据缺口，开始感到被动暴躁，杀意不再掩饰",
                        "physical_behavior_manifestation": "猛摘下金丝眼镜扔在桌面，用力掐紧手串第三颗，嘴角假笑消失",
                    },
                    {
                        "stage_label": "第三幕：穷途末路与疯狂",
                        "psychological_state": "原罪公之于众，陷入病态偏执，试图鱼死网破拉所有人陪葬",
                        "physical_behavior_manifestation": "发丝散乱油头凌乱，昂贵西装领带扯歪，眼白布满猩红血丝嘶吼",
                    },
                ],
            },
        ],
        # 【规则编号: STAGE-2-OUT-01】短期记忆便签 B
        "short_memory_b": (
            f"【短期记忆便签 B：肖像骨相DNA + 真实服饰代码 + 关系死结网】"
            f"主角:{protagonist_name}(男,高颧骨鹰隼眼+600g粗花呢破痕+随身信物); "
            f"反派:{antagonist_name}(男,金丝眼镜+320g高定西服茶渍+手串深痕+假面菩萨); "
            f"死结:《{title}》铁证与权势的生死较量"
        ),
    }


def stage2_character_node(state: Any) -> dict[str, Any]:
    """【规则编号: STAGE-2-COT-01 ~ STAGE-2-OUT-01】执行阶段 2：角色人物建模与四元心理、生物骨相与生活质感服化道。"""
    title = _get_val(state, "selected_title", "未命名项目")
    logline = _get_val(state, "logline", "")
    dramatic_irony = _get_val(state, "core_irony") or _get_val(state, "dramatic_irony") or ""
    grand_payoff = _get_val(state, "grand_payoff", "")
    visual_style = _get_val(state, "visual_style", "真人电影/工业冷峻暗色调/超写实")
    short_memory_a = _get_val(state, "short_memory_a", "")

    logger.debug(f"[Stage 2 Node] Executing character modeling for project: '{title}'")

    user_prompt = STAGE2_USER_PROMPT_TEMPLATE.format(
        title=title,
        logline=logline,
        dramatic_irony=dramatic_irony,
        grand_payoff=grand_payoff,
        visual_style=visual_style,
        short_memory_a=short_memory_a,
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE2_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage2_fallback(title, logline),
    )

    chars = result_json.get("characters") or []
    norm_chars: list[dict[str, Any]] = []
    all_dual_rels: list[dict[str, Any]] = []
    all_emotional_arcs: list[dict[str, Any]] = []

    for c in chars:
        c_name = c.get("name", "未命名角色")
        role_type = c.get("role_type", "protagonist")

        # 【规则编号: STAGE-2-COT-01】生理性别强制声明 (防性别幻觉与配音错乱)
        gender = c.get("gender") or c.get("biological_sex") or c.get("sex")
        if not gender:
            gender = "male" if "男" in str(c.get("appearance", "")) or role_type == "protagonist" else "female"
        c["gender"] = gender
        c["biological_sex"] = gender

        # 兼容语言指纹双命名
        # 【规则编号: STAGE-2-COT-03】声学人设与语言指纹微动作
        v_fp = c.get("voice_fingerprint") or c.get("linguistic_fingerprint") or {
            "catchphrase": f"{c_name}的标志性口头禅",
            "defensive_phrase": "看事实说话，别编借口。",
            "stress_action": "下意识轻叩掌心或瞳孔骤缩",
            "forbidden_words": ["认输", "投降"],
        }
        c["voice_fingerprint"] = v_fp
        c["linguistic_fingerprint"] = v_fp

        if not c.get("voice_style"):
            c["voice_style"] = "中低音质，胸腔共鸣，语速微偏慢带发干微哑"

        # 【规则编号: STAGE-2-COT-02】校验并补齐生物骨相结构 (BiologicalPortraitDNA)
        bio_dna = c.get("biological_dna")
        if not bio_dna or not isinstance(bio_dna, dict):
            c["biological_dna"] = {
                "bone_structure": "高折叠度骨相，高颧骨，下颌骨线条清晰紧绷，五官轮廓分明",
                "skin_micro_texture": "自然肌理与微小毛孔质感，眼周有自然干纹，杜绝塑料磨皮",
                "skin_texture": "自然肌理与微小毛孔质感，眼周有自然干纹，杜绝塑料磨皮",
                "blemishes_and_scars": "右眉骨上方2cm有浅淡旧伤痕或嘴角微小暗痣",
                "permanent_blemish_dna": "右眉骨上方2cm有浅淡旧伤痕或嘴角微小暗痣",
                "eye_lip_anatomy": "内双眼皮，眼球带有疲惫血丝，下唇干燥微起皮",
                "eye_lip_features": "内双眼皮，眼球带有疲惫血丝，下唇干燥微起皮",
                "hair_texture": "自然发流微凌乱，略带粗硬发质与碎绺",
                "hair_spec": "自然发流微凌乱，略带粗硬发质与碎绺",
            }
        else:
            if "skin_texture" not in bio_dna and "skin_micro_texture" in bio_dna:
                bio_dna["skin_texture"] = bio_dna["skin_micro_texture"]
            elif "skin_micro_texture" not in bio_dna and "skin_texture" in bio_dna:
                bio_dna["skin_micro_texture"] = bio_dna["skin_texture"]
            if "permanent_blemish_dna" not in bio_dna and "blemishes_and_scars" in bio_dna:
                bio_dna["permanent_blemish_dna"] = bio_dna["blemishes_and_scars"]
            elif "blemishes_and_scars" not in bio_dna and "permanent_blemish_dna" in bio_dna:
                bio_dna["blemishes_and_scars"] = bio_dna["permanent_blemish_dna"]
            if "eye_lip_features" not in bio_dna and "eye_lip_anatomy" in bio_dna:
                bio_dna["eye_lip_features"] = bio_dna["eye_lip_anatomy"]
            elif "eye_lip_anatomy" not in bio_dna and "eye_lip_features" in bio_dna:
                bio_dna["eye_lip_anatomy"] = bio_dna["eye_lip_features"]
            if "hair_spec" not in bio_dna and "hair_texture" in bio_dna:
                bio_dna["hair_spec"] = bio_dna["hair_texture"]
            elif "hair_texture" not in bio_dna and "hair_spec" in bio_dna:
                bio_dna["hair_texture"] = bio_dna["hair_spec"]

        # 【规则编号: STAGE-2-COT-02】校验并补齐生活质感服化道代码 (LivedInCostumeSpecs)
        costume_spec = c.get("lived_in_costume")
        if not costume_spec or not isinstance(costume_spec, dict):
            c["lived_in_costume"] = {
                "top_wear": "重磅保暖大衣（600g/m²，两肘有明显自然磨损褶皱，第二颗纽扣有2cm松脱线头）",
                "bottom_wear": "斜纹耐磨工装长裤（膝盖泛白褪色，裤脚处带有干涸泥点痕迹）",
                "footwear": "磨砂工装皮靴（鞋头踢蹭擦痕，右脚橡胶鞋底外侧磨损3毫米）",
                "wear_and_tear_details": "右侧大衣口袋边缘有钥匙长期摩擦起球痕迹，领口内衬有微黄汗渍做旧",
            }

        # 【规则编号: STAGE-2-COT-01】校验并补齐心理四元组与致命谎言 (The Lie)
        quad = c.get("psychological_quad")
        if not quad or not isinstance(quad, dict) or not quad.get("want") or not quad.get("lie"):
            c["psychological_quad"] = {
                "want": f"亲手揭开《{title}》所有被掩盖的隐秘真相",
                "need": "直面内心深处的恐惧与遗憾，完成自我救赎",
                "lie": "只要掌控绝对理性和铁证，正义就绝不会被权势玷污，情感只是累赘",
                "ghost": "数年前因自身的一时犹豫导致关键线索中断且至亲受害",
            }

        # 【规则编号: STAGE-2-COT-04】随身携带锚定旧物
        if not c.get("carried_anchor_item"):
            c["carried_anchor_item"] = {
                "item_name": "刻有划痕的旧金属打火机/信物",
                "physical_trace": "表面有严重凹陷磕碰与金属氧化划痕",
                "emotional_significance": "陷入绝境抉择时下意识用指尖反复摩挲",
            }

        # 【规则编号: STAGE-2-COT-04】校验并补齐双轨关系 (dual_track_relationships)
        dual_rels = c.get("dual_track_relationships")
        if not dual_rels or not isinstance(dual_rels, list):
            c["dual_track_relationships"] = [
                {
                    "target_character": "主要对手",
                    "surface_relation": "表面客套与业务合作",
                    "hidden_tension": "暗藏杀机与核心证据生死试探",
                }
            ]
        all_dual_rels.extend(c["dual_track_relationships"])

        # 【规则编号: STAGE-2-COT-04】校验并补齐四阶段情感弧光 (emotional_arc_trajectories)
        arcs = c.get("emotional_arc_trajectories")
        if not arcs or not isinstance(arcs, list):
            c["emotional_arc_trajectories"] = [
                {
                    "stage_label": "初始防御期",
                    "psychological_state": "受困于心魔与谎言，依靠假面与防备应对外界",
                    "physical_behavior_manifestation": "肢体僵硬保持距离，扣紧衣扣，语速克制",
                },
                {
                    "stage_label": "信念崩解期",
                    "psychological_state": "核心防线遭遇铁证打击，Lie被粉碎，陷入痛苦失控",
                    "physical_behavior_manifestation": "眼神发红失焦，衣衫不整，应激动作频繁爆发",
                },
                {
                    "stage_label": "灵魂重铸期",
                    "psychological_state": "承认自己的过错与无力，从单纯追逐私怨转向守护他人",
                    "physical_behavior_manifestation": "主动交托随身信物，眼神从鹰隼般的刺骨转为坚韧温和",
                },
                {
                    "stage_label": "终极觉醒期",
                    "psychological_state": "完成自我救赎与灵魂升华，坦然拥抱真实命运",
                    "physical_behavior_manifestation": "神情释然坚毅，身躯笔挺，动作从容从心",
                },
            ]
        all_emotional_arcs.extend(c["emotional_arc_trajectories"])

        norm_chars.append(c)

    # 【规则编号: STAGE-2-OUT-01】封装沉淀【短期记忆便签 B】
    short_mem_b = (
        result_json.get("short_memory_b")
        or f"【短期记忆便签 B】已锁定 {len(norm_chars)} 位角色的微观生物肖像骨相、生活质感服化道与心理四元组，进入阶段 3 空间做旧与物证规划"
    )

    logger.debug(
        f"[Stage 2 Node] Character engine complete: character_count={len(norm_chars)}, "
        f"dual_relations={len(all_dual_rels)}, emotional_arcs={len(all_emotional_arcs)}"
    )

    return {
        "current_stage": 2,
        "characters_engine": {"characters": norm_chars},
        "dual_track_relationships": all_dual_rels,
        "emotional_arc_trajectories": all_emotional_arcs,
        "short_memory_b": short_mem_b,
    }
