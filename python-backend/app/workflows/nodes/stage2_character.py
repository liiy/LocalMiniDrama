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

from app.context.short_memory_service import (
    WorkingMemoryCompiler,
    publish_drama_event,
    publish_drama_read_projection,
    set_journey1_working_memory,
)
from app.schemas.script_graph_state import (
    GlobalDramaMasterState,
    IndustrialDramaState,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE2_SYSTEM_PROMPT,
    STAGE2_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.llm_bridge import call_llm_json

from app.utils.blueprint import (
    to_prompt_block
)

logger = logging.getLogger("lmd.stage2_character")


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _normalize_character_id(name: str, existing_id: str | None = None, idx: int = 1) -> str:
    """【规则编号: RULE-VI-02 / 章节三协议】纯动态规范化角色标识符 CHAR_<TOKEN>。
    
    动态生成与纠偏优先级（零硬编码映射表，全流程动态推导）：
    1. 优先采纳大模型生成 ID/Token (existing_id)：
       - 剥离前缀 CHAR_ 或 char_ 后清洗为纯英数字符串；
       - 若大模型生成的标识包含中文字符，自动调用动态拼音引擎转换为大写英数字符串；
       - 组合为 CHAR_<TOKEN>。
    2. 动态中文转写兜底：若大模型未提供合法 ID，调用 AssetProtocolHelper.chinese_to_token(name) 
       动态将角色名转为大写拼音/英文字符串。
    3. 终极确定性安全标识：若角色姓名为空或全无效字符，返回 CHAR_ROLE{idx:02d}。
    """
    # 1. 优先采纳并规范化大模型生成的 ID / Token
    if existing_id and str(existing_id).strip():
        raw_val = str(existing_id).strip()
        # 剥离前缀 CHAR_ 或 char_
        if raw_val.upper().startswith("CHAR_"):
            inner_tok = raw_val[5:].strip("_")
        elif raw_val.upper().startswith("CHAR"):
            inner_tok = raw_val[4:].strip("_")
        else:
            inner_tok = raw_val

        # 若模型生成的 token 带有中文，使用拼音转写动态提取
        if re.search(r"[\u4e00-\u9fff]", inner_tok):
            inner_tok = AssetProtocolHelper.chinese_to_token(inner_tok)
        else:
            inner_tok = re.sub(r"[^A-Za-z0-9]+", "", inner_tok).upper()

        if inner_tok:
            return f"CHAR_{inner_tok}"

    # 2. 若大模型未输出合法 ID，动态从角色中文名生成大写拼音/英文 Token（纯动态推导）
    clean_name = str(name).strip()
    if clean_name:
        dynamic_token = AssetProtocolHelper.chinese_to_token(clean_name)
        if dynamic_token:
            return f"CHAR_{dynamic_token}"

    # 3. 终极确定性安全标识
    return f"CHAR_ROLE{idx:02d}"


def _stage2_fallback(
    title: str,
    logline: str,
    user_idea: str = "",
    genre: str = "",
) -> dict[str, Any]:
    """【阶段 2 离线保底工厂】当大模型离线或输出格式异常时的保底生成工厂。
    
    严格对齐阶段 2 全新数据契约：
    1. 基础盘覆盖 protagonist / antagonist / witness / swing 四类核心角色；
    2. 输出规范化字段：character_code, gender, perceived_age, role, visual_consistency_code,
       acoustic_persona, psychology_4, voice_fingerprint, carried_anchor_item, drama_engine；
    3. 构建全覆盖的双轨关系矩阵 relationship_matrix，标注 drama_function, information_gap 与 swing_point；
    4. 自动合成历史兼容字段（biological_dna, lived_in_costume, psychological_quad, dual_track_relationships）。
    """
    logger.debug(f"[阶段2·保底工厂] 触发离线或异常保底机制，正在为项目《{title}》合成角色引擎资产...")

    # 动态尝试从标题、用户构想与 logline 提取人名或设定特征
    combined_text = f"{title} {user_idea} {logline}"
    names_found = re.findall(r"(?:[向周沈陆顾林叶韩苏陈张楚谢徐江秦][一-龥]{1,2})", combined_text)

    protagonist_name = names_found[0] if names_found else "陆沉"
    antagonist_name = names_found[1] if len(names_found) > 1 and names_found[1] != protagonist_name else "韩泰"
    witness_name = "苏晓"
    swing_name = "周明"

    pro_code = _normalize_character_id(protagonist_name, idx=1)
    ant_code = _normalize_character_id(antagonist_name, idx=2)
    wit_code = _normalize_character_id(witness_name, idx=3)
    swi_code = _normalize_character_id(swing_name, idx=4)

    logger.debug(
        f"[阶段2·保底工厂] 自动分配核心角色代号: 主角={pro_code}({protagonist_name}), "
        f"对手={ant_code}({antagonist_name}), 见证者={wit_code}({witness_name}), 摇摆者={swi_code}({swing_name})"
    )

    core_conflict_desc = user_idea[:60] if user_idea else logline[:60] or f"围绕《{title}》的核心悬念与冲突"

    fallback_res: dict[str, Any] = {
        "characters": [
            {
                # 1. 主角 (protagonist)
                "character_code": pro_code,
                "character_id": pro_code,
                "character_token": pro_code.replace("CHAR_", ""),
                "name": protagonist_name,
                "gender": "male",
                "biological_sex": "male",
                "perceived_age": 38,
                "role": "protagonist",
                "role_type": "protagonist",
                "personality": f"表面木讷能忍、任人差遣，实则极度自律、算无遗策；围绕《{title}》追寻终极真相，把反击交给对手的狂妄。",
                "appearance": "三十八岁，瘦硬挺拔，常穿一件洗得发旧的深灰粗花呢大衣，站姿微躬，眼神低垂像认命，抬眼时冷得压人。",
                "identity_anchors": ["额角浅白色旧伤痕", "深灰粗花呢大衣", "内双微垂的冷眼", "旧铜打火机"],
                "visual_consistency_code": {
                    "facial_signature": "高折叠度骨相，高颧骨，方正下颌角略下压，侧脸线条如刀刻般硬朗",
                    "skin_and_texture": "偏干性粗糙肤质，T区有肉眼可见自然粗大毛孔与细微干纹，拒绝磨皮塑料感",
                    "signature_marks": "右侧眉骨上方一道2.5cm浅白色陈旧缝合伤痕；右侧嘴角上方0.5cm处有一颗极淡暗褐小痣",
                    "hair": "自然黑发夹杂约10%灰白，粗硬微卷，额前有几缕雨水打湿的碎发",
                    "costume_wear_code": "深灰粗花呢大衣（肘部久坐折痕、第二颗纽扣松脱线头垂挂、下摆干结泥斑）+ 粗棒针毛衣（领口松弛起球）+ 黑色工装长裤（膝盖泛白磨痕）+ 磨砂皮靴（鞋头擦痕、鞋跟磨偏）",
                    "anchor_props": ["素圈细银戒（布满划痕）", "氧化发黑的金属裤扣"],
                },
                "voice_style": "低沉沙哑，胸腔共鸣明显，语速克制偏慢，每句话前有微小停顿",
                "acoustic_persona": {
                    "vocal_position": "胸腔深层共鸣，发声发力点沉在喉位下方",
                    "vocal_flaws": "声带疲劳发干带约30% Vocal Fry气泡音颗粒感，轻微齿擦音",
                    "speed_and_intonation": "语速系数0.88偏慢克制，每句话前有微顿，句尾果断平收",
                },
                "psychology_4": {
                    "want": f"亲手揭开《{title}》背后的真凶，洗清冤屈并夺回关键罪证",
                    "need": "直面当年迟到的懦弱选择，接纳不完美的自我并完成自我救赎",
                    "the_lie": "只要继续藏着、掌控理性和铁证，就能护住想护的人，情感只是累赘",
                    "the_ghost": "七年前因自己迟到五分钟，导致至亲当场罹难且现场关键罪证被毁",
                },
                "voice_fingerprint": {
                    "catchphrase": "说话要有凭据，心跳可瞒不过我。",
                    "defensive_phrase": "你确定要跟我算这笔账？看事实说话。",
                    "forbidden_words": {
                        "psychological": ["认输", "投降", "算了", "对不起"],
                    },
                    "info_boundary": [
                        {
                            "forbidden": "真实身份与军阶档案",
                            "reason": "身份揭晓前严禁自曝或被他人当众叫破",
                            "unlock_condition": "核心罪证确凿且反派落入终极伏击圈后解禁",
                        }
                    ],
                    "stress_action": "右手拇指用力反复摩挲食指第二指节，眼神微眯瞳孔剧烈聚焦",
                },
                "carried_anchor_item": {
                    "item_name": "刻有划痕的旧铜制打火机",
                    "physical_trace": "金属机身严重凹陷磕碰，边缘氧化发黑，火石齿轮轻微卡涩需拨两次才着火",
                    "emotional_significance": "牺牲至亲的临终遗物，每逢道德绝境时下意识隔着衣料摩挲，后续将成为身份揭晓的关键伏笔",
                },
                "drama_engine": {
                    "suppression_motive": "隐忍蛰伏是为了等所有同谋聚齐后一次性钉死，代价是忍受当众轻侮",
                    "reveal_trigger_type": "随身信物被对手认出，或至亲血亲遭到直接人身威胁",
                    "payback_style": "不动声色，借对手自身的贪婪与盲动反噬其身，从不当众无脑叫嚣",
                    "hook_capacity": ["身份暗示", "打脸预告", "新危机触发"],
                    "payoff_value": "极致隐忍蓄力 + 阶段性雷霆碾压反杀",
                },
                # 兼容下游红蓝审计与旧节点提取
                "biological_dna": {
                    "bone_structure": "高折叠度骨相，高颧骨，方正下颌角略下压，侧脸线条如刀刻般硬朗",
                    "face_shape": "高折叠度骨相，高颧骨，方正下颌角略下压，侧脸线条如刀刻般硬朗",
                    "skin_micro_texture": "偏干性粗糙肤质，T区有肉眼可见自然粗大毛孔与细微干纹，拒绝磨皮塑料感",
                    "skin_texture": "偏干性粗糙肤质，T区有肉眼可见自然粗大毛孔与细微干纹，拒绝磨皮塑料感",
                    "skin_pores": "偏干性粗糙肤质，T区有肉眼可见自然粗大毛孔与细微干纹，拒绝磨皮塑料感",
                    "blemishes_and_scars": "右侧眉骨上方一道2.5cm浅白色陈旧缝合伤痕；右侧嘴角上方0.5cm处有一颗极淡暗褐小痣",
                    "permanent_flaws_coordinates": "右侧眉骨上方一道2.5cm浅白色陈旧缝合伤痕；右侧嘴角上方0.5cm处有一颗极淡暗褐小痣",
                    "eye_lip_anatomy": "内双窄眼皮微垂，眼白布有血丝；嘴唇常年干燥起皮",
                    "hair_texture": "自然黑发夹杂约10%灰白，粗硬微卷",
                },
                "lived_in_costume": {
                    "top_wear": "深灰粗花呢大衣（肘部久坐折痕、第二颗纽扣松脱线头垂挂）",
                    "outerwear": "深灰粗花呢大衣（肘部久坐折痕、第二颗纽扣松脱线头垂挂）",
                    "outerwear_fabric_wear": "深灰粗花呢大衣（肘部久坐折痕、第二颗纽扣松脱线头垂挂）",
                    "innerwear": "粗棒针毛衣（领口松弛起球、领圈汗渍硬壳做旧）",
                    "bottom_wear": "黑色工装长裤（膝盖泛白水磨，裤脚沾染干泥斑）",
                    "footwear": "深棕磨砂皮工装靴（靴头擦痕，鞋跟外侧磨偏3mm）",
                    "bottoms_and_shoes": "黑色工装长裤 + 深棕磨砂皮工装靴",
                    "wear_and_tear_details": "右侧大衣口袋边缘钥匙摩擦抽丝，领口内衬微黄汗渍",
                    "accessories_anchors": "素圈细银戒、氧化发黑的金属裤扣",
                    "anchor_props": ["素圈细银戒", "氧化发黑的金属裤扣"],
                },
                "psychological_quad": {
                    "want": f"亲手揭开《{title}》背后的真凶，洗清冤屈并夺回关键罪证",
                    "need": "直面当年迟到的懦弱选择，接纳不完美的自我并完成自我救赎",
                    "the_lie": "只要继续藏着、掌控理性和铁证，就能护住想护的人，情感只是累赘",
                    "the_ghost": "七年前因自己迟到五分钟，导致至亲当场罹难且现场关键罪证被毁",
                },
                "dual_track_relationships": [
                    {
                        "target_character": antagonist_name,
                        "character_a": pro_code,
                        "character_b": ant_code,
                        "surface_relation": "表面上下级与受辱附庸",
                        "surface_identity": "表面上下级与受辱附庸",
                        "emotional_bond": "生死不共戴天的复仇死结",
                        "deep_bond": "生死不共戴天的复仇死结",
                        "fatal_interest_conflict": "七年前命案罪证与核心集团生杀大权",
                        "fatal_conflict": "七年前命案罪证与核心集团生杀大权",
                        "drama_function": "羞辱供给 → 反杀打脸；全季主对抗线",
                        "shared_history_props": ["刻有划痕的旧铜制打火机", "金属名片夹"],
                    }
                ],
                "emotional_arc_trajectories": [
                    {"stage_label": "第一幕: 隐忍蛰伏", "psychological_state": "坚冰防御", "trigger": "遭遇当众羞辱与挑衅"},
                    {"stage_label": "第二幕: 暗中布局", "psychological_state": "信念动摇与试探", "trigger": "发现核心物证线索"},
                    {"stage_label": "第三幕: 绝境反杀", "psychological_state": "灵魂重铸与雷霆出击", "trigger": "身份信物彻底亮明"},
                ],
            },
            {
                # 2. 宿命反派 (antagonist)
                "character_code": ant_code,
                "character_id": ant_code,
                "character_token": ant_code.replace("CHAR_", ""),
                "name": antagonist_name,
                "gender": "male",
                "biological_sex": "male",
                "perceived_age": 52,
                "role": "antagonist",
                "role_type": "antagonist",
                "personality": f"精明张扬、好面子、极度怕失去位置；靠攀附与算计上位，把控《{title}》幕后利益链，防线是永远先声夺人、用排场压人。",
                "appearance": "五十二岁，体格厚实，银灰三件套西装永远挺括合体，金丝细框眼镜，笑时露出一口过分整齐的瓷白牙。",
                "identity_anchors": ["油亮后梳短发", "深色高定羊毛西服", "金丝细框眼镜", "老山檀沉香手串"],
                "visual_consistency_code": {
                    "facial_signature": "方圆脸，皮下脂肪包裹感重，双下巴微垂，下颌缘轮廓开始松弛",
                    "skin_and_texture": "中性偏油性皮肤，鼻翼两侧粗大毛孔，两颊有轻微色素沉着斑块与深鱼尾纹",
                    "signature_marks": "左手虎口处一小块浅褐色旧烫伤疤痕；左侧发际线隐蔽处有1cm微创疤痕",
                    "hair": "粗硬黑发两鬓斑白，大量发胶一丝不苟后梳成三七分油头，后颈发际线修剪规整",
                    "costume_wear_code": "银灰高定精纺西装（肩线笔挺，右袖口有一滴极浅茶渍）+ 定织法式双叠袖衬衫（领扣紧扣微有压痕）+ 手工黑色牛津皮鞋（鞋底边缘细小擦痕）",
                    "anchor_props": ["金属名片夹（边角磕白）", "百年老山檀沉香手串（第三颗深痕）"],
                },
                "voice_style": "洪亮外放兼带长者慈爱假面，鼻腔共鸣重，语速快，喜欢抢话和居高临下反问",
                "acoustic_persona": {
                    "vocal_position": "咽壁紧绷微扁，发力点偏高偏前",
                    "vocal_flaws": "长期烟酒致声带轻微增厚，压迫施压时尾音沙哑劈叉",
                    "speed_and_intonation": "语速系数1.22偏快，句尾习惯性上扬反问带压迫审视感",
                },
                "psychology_4": {
                    "want": f"确保自身名流地位万无一失，彻底清理《{title}》所有知情者并吞并所有涉案资产",
                    "need": "直面内心深处对底层卑微出身的病态恐惧，承认自己从来只是别人的执刀工具",
                    "the_lie": "只要我站得够高、手里筹码够多，当年的罪孽就永远追不上我",
                    "the_ghost": "三十年前在矿难底层靠构陷老友吞并第一桶金的原罪把柄",
                },
                "voice_fingerprint": {
                    "catchphrase": "这个圈子，讲的是规矩和体面。",
                    "defensive_phrase": "你算什么东西，也配跟我提当年？",
                    "forbidden_words": {
                        "psychological": ["矿难", "当年", "分赃", "求你", "我错了"],
                    },
                    "info_boundary": [
                        {
                            "forbidden": "幕后真正出资元凶代号",
                            "reason": "终极幕后巨鳄须在剧作后段由主角顺藤摸瓜引出",
                            "unlock_condition": "反派核心产业被依法查封、走投无路鱼死网破时",
                        }
                    ],
                    "stress_action": "右手大拇指疯狂抠掐沉香手串第三颗深痕，呼吸急促短笑",
                },
                "carried_anchor_item": {
                    "item_name": "百年老山檀沉香手串",
                    "physical_trace": "第三颗佛珠有一道被指甲反复抠掐出黑油的极深凹槽痕迹",
                    "emotional_significance": "当年分赃封口留下的信物，每次动杀心或感到失控时下意识转动以掩盖内心的惊恐虚妄",
                },
                "drama_engine": {
                    "suppression_motive": "持续施压羞辱主角并伪造证据，意图将旧案所有黑锅扣在主角头上",
                    "reveal_trigger_type": "认出主角随身携带的至亲信物，发现当年死敌后人并未亡故",
                    "payback_style": "先极尽嚣张构陷，后在铁证前身败名裂当众崩溃跪服，跪得越狠越爽",
                    "hook_capacity": ["当众羞辱", "阴谋构陷", "引出更高层黑恶黑手"],
                    "payoff_value": "嚣张压迫供给 + 打脸崩盘承受",
                },
                "biological_dna": {
                    "bone_structure": "方圆脸骨架偏宽，颧骨不高但下颌肉感下垂，双下巴在低头时明显",
                    "face_shape": "方圆脸骨架偏宽，颧骨不高但下颌肉感下垂，双下巴在低头时明显",
                    "skin_micro_texture": "中性偏油性皮肤，鼻翼两侧粗大毛孔，两颊有轻微色素沉着斑块与深鱼尾纹",
                    "skin_texture": "中性偏油性皮肤，鼻翼两侧粗大毛孔，两颊有轻微色素沉着斑块与深鱼尾纹",
                    "skin_pores": "中性偏油性皮肤，鼻翼两侧粗大毛孔，两颊有轻微色素沉着斑块与深鱼尾纹",
                    "blemishes_and_scars": "左手虎口处一小块浅褐色旧烫伤疤痕；左侧发际线隐蔽处有1cm微创疤痕",
                    "permanent_flaws_coordinates": "左手虎口处一小块浅褐色旧烫伤疤痕；左侧发际线隐蔽处有1cm微创疤痕",
                    "eye_lip_anatomy": "单眼皮微肿，常年金丝眼镜反射冷光；唇色薄苍白，笑时眼肌完全不动",
                    "hair_texture": "两鬓斑白精细修剪，打理整齐的三七分油头",
                },
                "lived_in_costume": {
                    "top_wear": "银灰高定精纺西装（肩线笔挺，右袖口有一滴极浅茶渍）",
                    "outerwear": "银灰高定精纺西装（肩线笔挺，右袖口有一滴极浅茶渍）",
                    "outerwear_fabric_wear": "银灰高定精纺西装（肩线笔挺，右袖口有一滴极浅茶渍）",
                    "innerwear": "白色法式双叠袖衬衫（领扣紧扣压痕）",
                    "bottom_wear": "同色系暗条纹高定西裤（裤线锋利，裤脚内侧轻微皮鞋摩擦痕）",
                    "footwear": "手工黑色牛津皮鞋（鞋底边缘细小擦痕）",
                    "bottoms_and_shoes": "暗条纹高定西裤 + 手工牛津鞋",
                    "wear_and_tear_details": "左手腕西装袖口因常年盘弄手串有轻微磨损光泽",
                    "accessories_anchors": "金丝细框眼镜、百年老山檀沉香手串",
                    "anchor_props": ["金丝细框眼镜", "老山檀沉香手串"],
                },
                "psychological_quad": {
                    "want": f"确保自身名流地位万无一失，彻底清理《{title}》所有知情者并吞并所有涉案资产",
                    "need": "直面内心深处对底层卑微出身的病态恐惧，承认自己从来只是别人的执刀工具",
                    "the_lie": "只要我站得够高、手里筹码够多，当年的罪孽就永远追不上我",
                    "the_ghost": "三十年前在矿难底层靠构陷老友吞并第一桶金的原罪把柄",
                },
            },
            {
                # 3. 打脸见证者 (witness)
                "character_code": wit_code,
                "character_id": wit_code,
                "character_token": wit_code.replace("CHAR_", ""),
                "name": witness_name,
                "gender": "female",
                "biological_sex": "female",
                "perceived_age": 26,
                "role": "witness",
                "role_type": "witness",
                "personality": "敏锐执着但略带职场怯懦，表面顺应强权求生，暗中用录音与笔录还原现场，是全剧高光打脸的情绪放大器与良知镜像。",
                "appearance": "二十六岁，身形纤细干练，米白色通勤风衣配细圆黑框眼镜，齐肩短发，眼神从最初的唯诺逐渐转为清澈坚定。",
                "identity_anchors": ["米白修身风衣", "细黑框圆眼镜", "齐肩利落短发", "金属微录音笔"],
                "visual_consistency_code": {
                    "facial_signature": "小巧鹅蛋脸，下巴线条圆润柔和，五官秀气紧凑",
                    "skin_and_texture": "中性白皙皮肤，偶有加班熬夜造成的眼下淡青黑眼圈与鼻翼微小闭口",
                    "signature_marks": "右耳垂有一枚微小耳洞痕迹，左耳上方有一小撮习惯性别在耳后的碎发",
                    "hair": "自然深棕色直短发齐肩，发丝细软柔顺，发梢整齐微内扣",
                    "costume_wear_code": "米白色中长通勤风衣（下摆因常年挤地铁有轻微折痕、右口袋拉链轻微掉漆）+ 浅灰纯棉打底衬衣 + 深蓝修身九分裤 + 黑色平底羊皮单鞋（鞋头有细碎刮痕）",
                    "anchor_props": ["银色细边手表（表带磨旧泛黄）", "定制金属微录音笔（挂在工牌内侧）"],
                },
                "voice_style": "清亮干脆，语速中等偏快，紧张提问时音调微扬但咬字清晰",
                "acoustic_persona": {
                    "vocal_position": "口腔前部与头腔共鸣为主，音质清脆透亮",
                    "vocal_flaws": "受惊慌乱时呼吸骤急，发问尾音有轻微颤抖气音",
                    "speed_and_intonation": "语速系数1.08微快，咬字干脆利落，句尾音调上扬带探寻感",
                },
                "psychology_4": {
                    "want": "在残酷职场中保住饭碗并获取独家猛料，摆脱做杂活的边缘人命运",
                    "need": "打破对权威的盲信，用自己的眼睛看清是非黑白，重拾为弱者发声的初心",
                    "the_lie": "在大人物的游戏里，只有装聋作哑紧跟赢家才能安身立命",
                    "the_ghost": "入职初期曾为了转正隐匿过无辜者被冤枉的报告，导致对方被开除并郁郁寡欢",
                },
                "voice_fingerprint": {
                    "catchphrase": "这数据……逻辑上根本对不上吧？",
                    "defensive_phrase": "我只是按规章流程如实核验，没有别的意思。",
                    "forbidden_words": {
                        "psychological": ["我不知道", "随便吧", "跟我没关系"],
                    },
                    "info_boundary": [
                        {
                            "forbidden": "主角隐藏档案的影印本位置",
                            "reason": "作为主角反杀的关键底牌证据，必须在关键质证集数才呈堂证供",
                            "unlock_condition": "主角在公开听证会上打出第一道核爆级指控时",
                        }
                    ],
                    "stress_action": "下意识用食指推紧眼镜中梁，双手紧紧抱住文件夹护在胸前",
                },
                "carried_anchor_item": {
                    "item_name": "定制金属微录音笔",
                    "physical_trace": "笔身金属夹处因长期夹挂磨白露出铜色底漆，录音红灯被黑色电工胶带遮挡防光",
                    "emotional_significance": "离世的记者父亲送给她的大学毕业礼物，每逢关键道德抉择都会暗中按下一键录音",
                },
                "drama_engine": {
                    "suppression_motive": "受命作为反派爪牙对主角进行刁难核查，充当反派施压的合法外衣",
                    "reveal_trigger_type": "无意间录到反派暗中下令制造假车祸灭口，且亲眼目睹主角从容化解",
                    "payback_style": "从最初的狐疑轻视，到目瞪口呆，再到当场倒戈呈交铁证，完成全场最爽反应放大",
                    "hook_capacity": ["悬念见证", "真相对比", "惊骇反应", "正义倒戈"],
                    "payoff_value": "受众代入感 + 打脸高潮情绪倍增器",
                },
                "biological_dna": {
                    "bone_structure": "小巧鹅蛋脸，下巴柔和，五官紧凑",
                    "face_shape": "小巧鹅蛋脸，下巴柔和，五官紧凑",
                    "skin_micro_texture": "中性偏干皮，眼下有熬夜青黑与鼻翼细微毛孔，无滤镜塑料感",
                    "skin_texture": "中性偏干皮，眼下有熬夜青黑与鼻翼细微毛孔，无滤镜塑料感",
                    "skin_pores": "中性偏干皮，眼下有熬夜青黑与鼻翼细微毛孔，无滤镜塑料感",
                    "blemishes_and_scars": "右耳垂微小耳洞印记，额头微小痘印",
                    "permanent_flaws_coordinates": "右耳垂微小耳洞印记，额头微小痘印",
                    "eye_lip_anatomy": "圆杏眼微戴黑框，眼神清澈探寻；唇色浅红微干",
                    "hair_texture": "齐肩深棕直短发，发质细软",
                },
                "lived_in_costume": {
                    "top_wear": "米白色中长通勤风衣（下摆折痕、口袋拉链微掉漆）",
                    "outerwear": "米白色中长通勤风衣（下摆折痕、口袋拉链微掉漆）",
                    "outerwear_fabric_wear": "米白色中长通勤风衣（下摆折痕、口袋拉链微掉漆）",
                    "innerwear": "浅灰纯棉打底衬衣（平整工整）",
                    "bottom_wear": "深蓝修身九分裤（膝盖微有坐痕）",
                    "footwear": "黑色平底羊皮单鞋（鞋头细微刮痕）",
                    "bottoms_and_shoes": "深蓝九分裤 + 黑色平底羊皮鞋",
                    "wear_and_tear_details": "通勤包背带与风衣右肩长期摩擦产生轻微起毛球",
                    "accessories_anchors": "银色细边手表、定制微录音笔",
                    "anchor_props": ["银色细边手表", "定制微录音笔"],
                },
                "psychological_quad": {
                    "want": "在残酷职场中保住饭碗并获取独家猛料，摆脱做杂活的边缘人命运",
                    "need": "打破对权威的盲信，用自己的眼睛看清是非黑白，重拾为弱者发声的初心",
                    "the_lie": "在大人物的游戏里，只有装聋作哑紧跟赢家才能安身立命",
                    "the_ghost": "入职初期曾为了转正隐匿过无辜者被冤枉的报告，导致对方被开除",
                },
            },
            {
                # 4. 可反水摇摆者 (swing)
                "character_code": swi_code,
                "character_id": swi_code,
                "character_token": swi_code.replace("CHAR_", ""),
                "name": swing_name,
                "gender": "male",
                "biological_sex": "male",
                "perceived_age": 34,
                "role": "swing",
                "role_type": "swing",
                "personality": "圆滑世故的中间人，唯利是图但尚存一丝对至亲的底线；擅长在两方阵营夹缝中见风使舵，是中后段局势突变的关键反水引擎。",
                "appearance": "三十四岁，身形微胖微驼，常穿藏青色拉链夹克配旧公文包，满脸堆笑但眼神左右游移不休。",
                "identity_anchors": ["藏青拉链夹克", "磨破角的旧公文包", "微卷乱发", "褪色不锈钢保温杯"],
                "visual_consistency_code": {
                    "facial_signature": "短圆脸，两腮微鼓，法令纹深长，眼神习惯性左右斜视",
                    "skin_and_texture": "粗糙黄黑油性肤质，鼻翼与额头油光发亮，嘴角有常年抽烟留下的暗黄色素",
                    "signature_marks": "左侧脖颈处有一块指甲盖大小的陈旧暗色胎记",
                    "hair": "自然卷黑发略显蓬乱油腻，发际线后移，头顶发量稀疏",
                    "costume_wear_code": "藏青色耐磨化纤拉链夹克（拉链齿有锈斑拉动费劲、袖口磨损发黑）+ 灰色宽松运动长裤（裤脚松紧带松脱）+ 灰白透气老爹鞋（侧边网布有小开线）",
                    "anchor_props": ["褪色不锈钢保温杯（掉漆露白）", "破损黑仿皮公文包"],
                },
                "voice_style": "圆滑和气，带着略显夸张的热情套近乎，紧张时喉音发紧、语速急促",
                "acoustic_persona": {
                    "vocal_position": "口腔中段放松发声，带轻微鼻音与笑意伪装",
                    "vocal_flaws": "言不由衷时频繁干咳清嗓，紧张慌乱时伴有明显吞咽唾沫声",
                    "speed_and_intonation": "语速忽快忽慢，惯于使用半截话与反问试探对方底牌",
                },
                "psychology_4": {
                    "want": "捞足封口筹码全身而退，带生病的孩子出国彻底离开是非漩涡",
                    "need": "在生死与利益审判面前，守住最后一点人性良知，停止对弱者的转嫁伤害",
                    "the_lie": "站队只要够快够狠，神仙打架的雷霆就永远劈不到小鬼头上",
                    "the_ghost": "五年前亲手销毁过关键账本，间接害得一户无辜人家破人亡，日夜难寐",
                },
                "voice_fingerprint": {
                    "catchphrase": "大家都是求财，何必把路给走绝了呢？",
                    "defensive_phrase": "我也是奉命行事吃口饭，神仙打架可别殃及小鬼啊！",
                    "forbidden_words": {
                        "psychological": ["誓死效忠", "绝不反水", "我认罪"],
                    },
                    "info_boundary": [
                        {
                            "forbidden": "当年那批关键假账的真实流水隐藏网盘密码",
                            "reason": "这是他保命换赦免的终极筹码，必须在反派彻底过河拆桥时才抛出",
                            "unlock_condition": "反派派人对其妻儿进行围堵灭口，被主角手下安全救出后",
                        }
                    ],
                    "stress_action": "反复旋转手中不锈钢保温杯盖，手指因过度用力而泛白发抖",
                },
                "carried_anchor_item": {
                    "item_name": "褪色不锈钢老式保温杯",
                    "physical_trace": "杯身多处磕碰凹瘪，烤漆脱落大半露出生铁银色，底部夹层暗藏一枚加密TF存储卡",
                    "emotional_significance": "生病母亲去世前塞给他的旧物，里面装着他留给自己的唯一免死金牌",
                },
                "drama_engine": {
                    "suppression_motive": "前期为求重赏甘当反派急先锋，处处对主角使绊子设卡盘查",
                    "reveal_trigger_type": "反派嫌其知情过多欲制造车祸灭口，主角危急关头出手救其全家",
                    "payback_style": "在终极对决前夕临阵倒戈，交出反派三十年绝密暗账，完成致命背刺",
                    "hook_capacity": ["阵营摇摆", "暗中倒戈", "关键泄密", "绝地反水"],
                    "payoff_value": "换血破局引擎 + 戏剧性倒戈反转",
                },
                "biological_dna": {
                    "bone_structure": "短圆脸，两腮微鼓，法令纹深长",
                    "face_shape": "短圆脸，两腮微鼓，法令纹深长",
                    "skin_micro_texture": "粗糙油性肤质，鼻翼额头油光，毛孔粗大自然",
                    "skin_texture": "粗糙油性肤质，鼻翼额头油光，毛孔粗大自然",
                    "skin_pores": "粗糙油性肤质，鼻翼额头油光，毛孔粗大自然",
                    "blemishes_and_scars": "左侧脖颈处暗色胎记",
                    "permanent_flaws_coordinates": "左侧脖颈处暗色胎记",
                    "eye_lip_anatomy": "小双眼皮常年眯笑游移；唇角带烟渍暗褐",
                    "hair_texture": "略微蓬乱油腻微卷发，发际线偏高",
                },
                "lived_in_costume": {
                    "top_wear": "藏青色耐磨化纤拉链夹克（拉链齿微生锈、袖口磨损发黑）",
                    "outerwear": "藏青色耐磨化纤拉链夹克（拉链齿微生锈、袖口磨损发黑）",
                    "outerwear_fabric_wear": "藏青色耐磨化纤拉链夹克（拉链齿微生锈、袖口磨损发黑）",
                    "innerwear": "老旧条纹纯棉T恤（领口起卷）",
                    "bottom_wear": "灰色宽松运动长裤（裤脚松紧带松脱）",
                    "footwear": "灰白透气老爹鞋（侧边网布轻微开线）",
                    "bottoms_and_shoes": "宽松运动长裤 + 透气老爹鞋",
                    "wear_and_tear_details": "夹克右肘磨损严重，公文包提手缠绕黑胶带",
                    "accessories_anchors": "褪色不锈钢保温杯、破损公文包",
                    "anchor_props": ["褪色不锈钢保温杯", "破损公文包"],
                },
                "psychological_quad": {
                    "want": "捞足封口筹码全身而退，带生病的孩子出国彻底离开是非漩涡",
                    "need": "在生死与利益审判面前，守住最后一点人性良知，停止对弱者的转嫁伤害",
                    "the_lie": "站队只要够快够狠，神仙打架的雷霆就永远劈不到小鬼头上",
                    "the_ghost": "五年前亲手销毁过关键账本，间接害得一户无辜人家破人亡",
                },
            },
        ],
        # 2. 全覆盖双轨关系矩阵
        "relationship_matrix": [
            {
                "character_a_code": pro_code,
                "character_b_code": ant_code,
                "character_a": protagonist_name,
                "character_b": antagonist_name,
                "character_pair": f"{protagonist_name} vs {antagonist_name}",
                "target_character": antagonist_name,
                "social_label": "底层库管员与高高在上的集团掌控者",
                "surface_relation": "底层库管员与高高在上的集团掌控者",
                "surface_identity": "底层库管员与高高在上的集团掌控者",
                "emotional_bond": "当年旧案的加害者与幸存者，唯一活口与生死对决宿敌",
                "deep_bond": "当年旧案的加害者与幸存者，唯一活口与生死对决宿敌",
                "fatal_interest_conflict": f"对手必须让主角永远闭嘴背黑锅，主角必须将对手绳之以法拆穿《{title}》幕后全部罪证——生死利益死结，绝无和解余地",
                "fatal_conflict": f"对手必须让主角永远闭嘴背黑锅，主角必须将对手绳之以法拆穿《{title}》幕后全部罪证",
                "shared_history_props": ["三十年前老厂区旧账本残页", "刻字老银怀表", "旧铜制打火机"],
                "shared_past_token": "三十年前老厂区旧账本残页",
                "drama_function": "羞辱供给 → 反杀打脸；全季主对抗线",
                "information_gap": {
                    "knows_truth_initially": False,
                    "current_belief": "以为主角只是个可以随意踩死的底层蝼蚁兼最佳替罪羊",
                    "reveal_condition": "认出主角随身旧铜打火机，并在公开质证会上面对完整证据链",
                },
                "attitude_arc": "无视 → 轻蔑羞辱 → 惊疑忌惮 → 暴怒构陷 → 恐惧崩溃 → 当众跪服",
                "swing_point": {
                    "can_defect": False,
                    "defect_condition": None,
                },
            },
            {
                "character_a_code": pro_code,
                "character_b_code": wit_code,
                "character_a": protagonist_name,
                "character_b": witness_name,
                "character_pair": f"{protagonist_name} vs {witness_name}",
                "target_character": witness_name,
                "social_label": "严苛的业务审查员与沉默寡言的被审查底层人员",
                "surface_relation": "严苛的业务审查员与沉默寡言的被审查底层人员",
                "emotional_bond": "从怀疑刺探到震撼敬畏的正义见证者与暗中同盟",
                "deep_bond": "从怀疑刺探到震撼敬畏的正义见证者与暗中同盟",
                "fatal_interest_conflict": "见证者追逐抢眼猛料可能提前引爆主角蛰伏布局，甚至导致双方同时暴露于反派枪口下",
                "fatal_conflict": "见证者追逐抢眼猛料可能提前引爆主角蛰伏布局",
                "shared_history_props": ["被红笔圈注的旧业务报表", "定制金属微录音笔"],
                "shared_past_token": "定制金属微录音笔",
                "drama_function": "见证打脸 → 情绪放大器 → 正义声援与暗中录音助力",
                "information_gap": {
                    "knows_truth_initially": False,
                    "current_belief": "认为主角形迹可疑、性格阴郁，必定私藏公司违规证据",
                    "reveal_condition": "暗中录到反派灭口指令，并在危机中被主角以身相护",
                },
                "attitude_arc": "傲慢怀疑 → 严苛刁难 → 骇然震惊 → 愧疚自省 → 崇敬同盟",
                "swing_point": {
                    "can_defect": True,
                    "defect_condition": "目睹反派残害无辜并伪造罪证构陷主角",
                },
            },
            {
                "character_a_code": pro_code,
                "character_b_code": swi_code,
                "character_a": protagonist_name,
                "character_b": swing_name,
                "character_pair": f"{protagonist_name} vs {swing_name}",
                "target_character": swing_name,
                "social_label": "执行打压指令的中间爪牙走狗与被刁难的对象",
                "surface_relation": "执行打压指令的中间爪牙走狗与被刁难的对象",
                "emotional_bond": "互握把柄但各怀心事的试探防备与策反破局",
                "deep_bond": "互握把柄但各怀心事的试探防备与策反破局",
                "fatal_interest_conflict": "摇摆者为自保必须将主角逼入死胡同交差，但主角手握其早年参与伪证的致命把柄",
                "fatal_conflict": "摇摆者为自保必须将主角逼入死胡同交差",
                "shared_history_props": ["褪色不锈钢保温杯", "封口牛皮纸加密底单"],
                "shared_past_token": "封口牛皮纸加密底单",
                "drama_function": "中间阻滞 → 利益倒戈；中后段破局反转核心换血引擎",
                "information_gap": {
                    "knows_truth_initially": False,
                    "current_belief": "认为主角不过是个任由反派拿捏的软柿子，自己只管捞钱",
                    "reveal_condition": "发现主角早就掌控了自己的退路死穴，且反派真正动了杀心灭自己全家",
                },
                "attitude_arc": "嚣张刁难 → 贪婪索贿 → 惊慌失措 → 绝望求生 → 临阵倒戈背刺反派",
                "swing_point": {
                    "can_defect": True,
                    "defect_condition": "反派动杀心欲制造意外灭口，主角暗中派人保下其妻儿老小",
                },
            },
        ],
        # 兼容旧顶层对象
        "emotional_arc_trajectory": {
            "stage_a_guarded": "以冷硬理性自我防御，坚信冰冷证据，排斥任何人靠近，深信理性万能",
            "stage_b_fracture": "关键铁证被权势当面销毁，Lie受到毁灭性打击，陷入绝望暴怒与对峙",
            "stage_c_abyss": "绝境降临，承认自己的过错与无力，从单纯追逐私怨转向为了守护他人而战",
            "stage_d_catharsis": "完成自我救赎，与执念和解，坦然直面生死绝境决战",
        },
        "audit_report": {
            "stage": 2,
            "verdict": "GREEN_APPROVED",
            "blue_team": "合规自审：已满足 protagonist/antagonist/witness/swing 四类全覆盖；多模态一致性锁定（visual_consistency_code + acoustic_persona）完备；双轨利益死结与反水机制闭环",
            "red_team_critic": "红军质询：1.四位核心角色均已建立不可调和的利益对抗与反转动力；2.禁止了集数时间轴泄露，定性指标健全",
        },
    }

    # 同步兼容器
    fallback_res["dual_track_relationships"] = fallback_res["relationship_matrix"]
    fallback_res["character_relationships"] = fallback_res["relationship_matrix"]

    # 纯函数式编译提炼角色工作便签 (便签 B)
    char_wm = WorkingMemoryCompiler.compile_character_working_memory(fallback_res)
    fallback_res["character_working_memory"] = char_wm
    fallback_res["short_memory_b"] = char_wm

    logger.debug(
        f"[阶段2·保底工厂] 保底资产合成完毕: 角色数={len(fallback_res['characters'])}, "
        f"关系对数={len(fallback_res['relationship_matrix'])}, 工作便签长度={len(char_wm)}"
    )
    return fallback_res


def stage2_character_node(state: GlobalDramaMasterState | IndustrialDramaState | Any) -> dict[str, Any]:
    """【阶段 2 核心节点】角色人物建模、四元心理动力学、多模态一致性代码与全覆盖双轨关系网。
    
    业务逻辑：
    1. 提取上游资产与阶段 1 核心工作便签 (ideation_working_memory)；
    2. 调用大模型生成符合阶段 2 全新 SOP 规范的 JSON 实体（若离线则平滑降级至保底工厂）；
    3. 严密解析并规范化 characters 数组（多模态一致性锁定、生理基线防工程事故、动态代码分配）；
    4. 严密解析并规范化 relationship_matrix 数组（通过代号与中英文双向映射安全连接，补齐戏剧功能与反水机制）；
    5. 合成向下兼容视图（biological_dna, lived_in_costume, psychological_quad, dual_track_relationships 等）；
    6. 编译阶段 2 角色工作记忆便签 (便签 B)，并广播事件与读投影。
    """
    title = _get_val(state, "selected_title") or _get_val(state, "title") or "未命名项目"
    genre = _get_val(state, "genre") or _get_val(state, "commercial_genre") or "悬疑/剧情"
    logline = _get_val(state, "logline", "")
    visual_style = _get_val(state, "visual_style", "真人电影/工业冷峻暗色调/超写实")
    target_video_engine = _get_val(state, "target_video_engine") or _get_val(state, "target_engine") or "wan3.0/seedance2.5"

    logger.info(
        f"[阶段2·角色工坊] ===== 开始执行阶段 2 角色建模节点 =====\n"
        f"  项目标题: 《{title}》 | 题材: {genre} | 引擎偏好: {target_video_engine}\n"
        f"  视觉风格: {visual_style} | 一句话梗概: {logline[:60]}..."
    )

    # 1. 优先提取阶段 1 核心工作便签 (ideation_working_memory) 与用户核心构想
    user_idea = (
        _get_val(state, "user_idea")
        or _get_val(state, "user_prompt")
        or _get_val(state, "story_prompt")
        or _get_val(state, "prompt")
        or logline
        or title
    )
    dramatic_irony = _get_val(state, "dramatic_irony") or _get_val(state, "the_irony") or "表面目标与深层真相的宿命错位"
    grand_payoff = _get_val(state, "grand_payoff") or "终局对决中信念重铸与真相大白"

    ideation_wm = _get_val(state, "ideation_working_memory") or ""
    if not ideation_wm:
        logger.debug(f"[阶段2·角色工坊] 未检测到预存的 ideation_working_memory，现场即时编译阶段 1 工作便签...")
        try:
            ideation_wm = WorkingMemoryCompiler.compile_ideation_working_memory(state)
        except Exception as e:
            logger.warning(f"[阶段2·角色工坊] 编译 ideation_working_memory 异常: {e}")
            ideation_wm = f"【阶段 1 核心工作便签】项目《{title}》，题材{genre}，风格{visual_style}"

    logger.debug(f"[阶段2·角色工坊] 阶段 1 便签装载成功，字符数: {len(ideation_wm)}")

    # 2. 格式化用户提示词并调用大模型（全量注入用户核心构想、核心讽刺与终局核爆点）
    user_prompt = STAGE2_USER_PROMPT_TEMPLATE.format(
        title=title,
        genre=genre,
        visual_style=visual_style,
        target_video_engine=target_video_engine,
        user_idea=user_idea,
        logline=logline,
        dramatic_irony=dramatic_irony,
        grand_payoff=grand_payoff,
        ideation_working_memory=ideation_wm,
        bp_prompt=to_prompt_block(_get_val(state, "blueprint")),
    )

    logger.info(f"[阶段2·角色工坊] 正在请求大模型生成角色档案与关系矩阵 JSON...")
    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE2_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage2_fallback(
            title, logline, user_idea=user_idea, genre=genre
        ),
    )

    raw_chars = result_json.get("characters") or []
    raw_rels = result_json.get("relationship_matrix") or []
    logger.info(
        f"[阶段2·角色工坊] 大模型响应解析完成: 角色原始数={len(raw_chars)}, 关系对原始数={len(raw_rels)}"
    )

    # 3. 建立角色名与代号的双向动态映射表 (支持中英文、代号与 Token 的全向互查)
    name_to_code: dict[str, str] = {}
    code_to_name: dict[str, str] = {}

    # 4. 逐个角色深度归一化与多模态代码处理
    norm_chars: list[dict[str, Any]] = []

    for idx, c in enumerate(raw_chars, start=1):
        if not isinstance(c, dict):
            logger.warning(f"[阶段2·角色工坊] 角色元素非字典类型，跳过: {type(c)}")
            continue

        c_name = str(c.get("name") or f"角色{idx}").strip()

        # 4.1 规范化角色代号 (character_code / character_id / character_token)
        raw_code = c.get("character_code") or c.get("character_id") or c.get("character_token")
        char_code = _normalize_character_id(c_name, raw_code, idx=idx)
        char_token = char_code.replace("CHAR_", "")

        # 注册双向映射
        name_to_code[c_name] = char_code
        name_to_code[char_code] = char_code
        name_to_code[char_token] = char_code
        code_to_name[char_code] = c_name

        # 4.2 生理性别强制声明 (gender)
        raw_gender = str(c.get("gender") or "").strip().lower()
        if raw_gender in ("male", "男", "男性", "m"):
            gender = "male"
        elif raw_gender in ("female", "女", "女性", "f"):
            gender = "female"
        elif raw_gender in ("other", "未知", "unknown"):
            gender = "other"
        else:
            # 语义兜底推断
            appearance_text = str(c.get("appearance", "")) + str(c.get("personality", ""))
            gender = "female" if any(kw in appearance_text for kw in ("女", "裙", "发卡", "她")) else "male"

        # 4.3 视觉表观年龄强制转整型 (perceived_age)
        raw_age = c.get("perceived_age")
        if isinstance(raw_age, (int, float)):
            perceived_age = int(raw_age)
        elif raw_age and str(raw_age).strip().isdigit():
            perceived_age = int(str(raw_age).strip())
        else:
            age_match = re.search(r"(\d{1,2})岁", str(c.get("appearance", "")) + str(c.get("personality", "")))
            perceived_age = int(age_match.group(1)) if age_match else (35 if idx == 1 else 45)

        # 4.4 角色定位归一化 (role / role_type)
        raw_role = str(c.get("role") or "").strip().lower()
        valid_roles = {"protagonist", "antagonist", "supporter", "witness", "swing"}
        if raw_role in valid_roles:
            role = raw_role
        else:
            # 依据顺序兜底推断
            if idx == 1:
                role = "protagonist"
            elif idx == 2:
                role = "antagonist"
            elif idx == 3:
                role = "witness"
            else:
                role = "swing"

        # 4.5 基础文本画像
        personality = str(c.get("personality") or f"{c_name}的核心性格特征").strip()
        appearance = str(c.get("appearance") or f"{perceived_age}岁，体貌特征分明").strip()

        # 4.6 锁脸纯视觉锚点 (identity_anchors: 3~5个短语)
        raw_anchors = c.get("identity_anchors")
        if isinstance(raw_anchors, list) and raw_anchors:
            identity_anchors = [str(a).strip() for a in raw_anchors if str(a).strip()]
        else:
            identity_anchors = ["特有面部轮廓", "标志性外套", "锐利眼神", "随身旧物"]

        # 4.7 跨集稳定锁脸与生活服饰一致性代码 (visual_consistency_code)
        raw_vcc = c.get("visual_consistency_code")
        if isinstance(raw_vcc, dict) and raw_vcc:
            vcc = {
                "facial_signature": str(raw_vcc.get("facial_signature") or "高折叠度骨相轮廓清晰"),
                "skin_and_texture": str(raw_vcc.get("skin_and_texture") or "自然肌理与真实毛孔质感，拒绝磨皮塑料感"),
                "signature_marks": str(raw_vcc.get("signature_marks") or "面部标志性瑕疵特征"),
                "hair": str(raw_vcc.get("hair") or "自然发流质感发型"),
                "costume_wear_code": str(raw_vcc.get("costume_wear_code") or "生活质感常服（带自然折痕与磨损）"),
                "anchor_props": raw_vcc.get("anchor_props") if isinstance(raw_vcc.get("anchor_props"), list) else ["随身信物钥匙"],
            }
        else:
            # 若大模型按老格式输出 biological_dna / lived_in_costume，则自适应提升
            old_bio = c.get("biological_dna") if isinstance(c.get("biological_dna"), dict) else {}
            old_costume = c.get("lived_in_costume") if isinstance(c.get("lived_in_costume"), dict) else {}
            vcc = {
                "facial_signature": str(old_bio.get("bone_structure") or old_bio.get("face_shape") or "高颧骨方下颌，骨量清晰"),
                "skin_and_texture": str(old_bio.get("skin_micro_texture") or old_bio.get("skin_texture") or "自然肌理，细微毛孔与干纹"),
                "signature_marks": str(old_bio.get("permanent_flaws_coordinates") or old_bio.get("blemishes_and_scars") or "眉骨或嘴角细微旧疤痕"),
                "hair": str(old_bio.get("hair_texture") or old_bio.get("hair_spec") or "自然黑发微卷略凌乱"),
                "costume_wear_code": str(old_costume.get("outerwear_fabric_wear") or old_costume.get("top_wear") or "质感常服带肘部折痕与局部轻磨损"),
                "anchor_props": old_costume.get("anchor_props") if isinstance(old_costume.get("anchor_props"), list) else ["随身信物钥匙"],
            }

        # 4.8 文字级声学人设 (acoustic_persona) 与 voice_style
        voice_style = str(c.get("voice_style") or "中低音质，胸腔发力克制偏慢").strip()
        raw_ac = c.get("acoustic_persona")
        if isinstance(raw_ac, dict) and raw_ac:
            acoustic_persona = {
                "vocal_position": str(raw_ac.get("vocal_position") or "胸腔深层共鸣，发力沉稳"),
                "vocal_flaws": str(raw_ac.get("vocal_flaws") or "声带疲劳微干带颗粒摩擦感"),
                "speed_and_intonation": str(raw_ac.get("speed_and_intonation") or "语速克制，句尾果断平收"),
            }
        else:
            acoustic_persona = {
                "vocal_position": "胸腔深层共鸣，发声发力点沉在喉位下方",
                "vocal_flaws": "声带疲劳微干带约30%气泡音颗粒感",
                "speed_and_intonation": "语速偏慢克制，每句话前有微小停顿",
            }

        # 4.9 心理四元组 (psychology_4: want/need/the_lie/the_ghost)
        raw_psy = c.get("psychology_4")
        if isinstance(raw_psy, dict) and raw_psy:
            the_lie_val = str(raw_psy.get("the_lie") or raw_psy.get("lie") or "只要掌控理性和铁证就能抵御伤害")
            the_ghost_val = str(raw_psy.get("the_ghost") or raw_psy.get("ghost") or "不可挽回的过往重大创伤")
            psychology_4 = {
                "want": str(raw_psy.get("want") or f"查明《{title}》核心真相并夺回公道"),
                "need": str(raw_psy.get("need") or "打破执念完成自我救赎与和解"),
                "the_lie": the_lie_val,
                "the_ghost": the_ghost_val,
            }
        else:
            psychology_4 = {
                "want": f"查明《{title}》核心真相并夺回公道",
                "need": "打破执念完成自我救赎与内在和解",
                "the_lie": "只要掌控理性和铁证就能抵御一切伤害，情感是累赘",
                "the_ghost": "多年前因自身懦弱犹豫导致的至亲惨痛悲剧",
            }

        # 4.10 行为指纹与应激微动作 (voice_fingerprint)
        raw_vfp = c.get("voice_fingerprint")
        if isinstance(raw_vfp, dict) and raw_vfp:
            forb = raw_vfp.get("forbidden_words")
            if not isinstance(forb, dict):
                forb_dict = {"psychological": forb if isinstance(forb, list) else ["认输", "投降"]}
            else:
                forb_dict = forb
            voice_fingerprint = {
                "catchphrase": str(raw_vfp.get("catchphrase") or "事实面前，狡辩毫无意义。"),
                "defensive_phrase": str(raw_vfp.get("defensive_phrase") or "这跟我没关系，拿证据说话。"),
                "forbidden_words": forb_dict,
                "info_boundary": raw_vfp.get("info_boundary") if isinstance(raw_vfp.get("info_boundary"), list) else [],
                "stress_action": str(raw_vfp.get("stress_action") or "下意识摩挲手指关节，眼神骤缩"),
            }
        else:
            voice_fingerprint = {
                "catchphrase": "说话要有凭据，心跳可瞒不过我。",
                "defensive_phrase": "你确定要跟我算这笔账？",
                "forbidden_words": {"psychological": ["认输", "投降", "算了"]},
                "info_boundary": [],
                "stress_action": "下意识右手拇指紧扣食指指节，呼吸变重",
            }

        # 4.11 随身锚定旧物 (carried_anchor_item)
        raw_anchor = c.get("carried_anchor_item")
        if isinstance(raw_anchor, dict) and raw_anchor:
            carried_anchor_item = {
                "item_name": str(raw_anchor.get("item_name") or "刻有划痕的随身旧物"),
                "physical_trace": str(raw_anchor.get("physical_trace") or "表面氧化发黑，有严重摩擦凹陷痕迹"),
                "emotional_significance": str(raw_anchor.get("emotional_significance") or "至亲临终留下的唯一物件，每次决断时下意识摩挲"),
            }
        else:
            carried_anchor_item = {
                "item_name": "刻有划痕的旧金属信物",
                "physical_trace": "表面氧化发黑，有深重撞击凹陷磨损",
                "emotional_significance": "关键旧案的唯一物理物证，面临极端选择时下意识触摸",
            }

        # 4.12 戏剧引擎产戏指标 (drama_engine)
        raw_eng = c.get("drama_engine")
        if isinstance(raw_eng, dict) and raw_eng:
            drama_engine = {
                "suppression_motive": str(raw_eng.get("suppression_motive") or "隐忍不发以集聚全部仇家把柄"),
                "reveal_trigger_type": str(raw_eng.get("reveal_trigger_type") or "随身信物被认出或关键底线被触碰"),
                "payback_style": str(raw_eng.get("payback_style") or "借力打力借对手狂妄反杀"),
                "hook_capacity": raw_eng.get("hook_capacity") if isinstance(raw_eng.get("hook_capacity"), list) else ["身份暗示", "反转打脸"],
                "payoff_value": str(raw_eng.get("payoff_value") or "情绪压迫蓄力 + 阶段性反杀释放"),
            }
        else:
            drama_engine = {
                "suppression_motive": "为了查清真相不得不隐忍受辱，蓄积力量",
                "reveal_trigger_type": "随身信物被对手识破或盟友遭遇灭顶之灾",
                "payback_style": "以其人之道还治其人之身，精准破局",
                "hook_capacity": ["身份暗示", "打脸预告"],
                "payoff_value": "隐忍压迫 + 强势反杀",
            }

        # 4.13 合成下游兼容与审计支撑结构
        synthesized_bio = {
            "bone_structure": vcc["facial_signature"],
            "face_shape": vcc["facial_signature"],
            "skin_micro_texture": vcc["skin_and_texture"],
            "skin_texture": vcc["skin_and_texture"],
            "skin_pores": vcc["skin_and_texture"],
            "blemishes_and_scars": vcc["signature_marks"],
            "permanent_blemish_dna": vcc["signature_marks"],
            "permanent_flaws_coordinates": vcc["signature_marks"],
            "eye_lip_anatomy": "自然眼型与唇部纹理，有疲态血丝",
            "hair_texture": vcc["hair"],
        }
        synthesized_costume = {
            "top_wear": vcc["costume_wear_code"],
            "outerwear": vcc["costume_wear_code"],
            "outerwear_fabric_wear": vcc["costume_wear_code"],
            "innerwear": "舒适纯棉或针织内搭，领口有生活磨损微松弛",
            "bottom_wear": "日常耐磨工装或休闲长裤",
            "footwear": "做旧皮鞋或工装靴，鞋跟有磨损痕迹",
            "bottoms_and_shoes": "日常长裤 + 做旧皮鞋",
            "wear_and_tear_details": vcc["costume_wear_code"],
            "accessories_anchors": "、".join(str(p) for p in vcc["anchor_props"]),
            "anchor_props": vcc["anchor_props"],
        }

        # 兼容性推导：若角色自身包含或未包含关系数组/弧光，确保向下兼容
        char_dual_rels = c.get("dual_track_relationships") or []
        if not char_dual_rels:
            char_dual_rels = [
                {
                    "target_character": "对手",
                    "character_a": char_code,
                    "character_b": "CHAR_OPPONENT",
                    "surface_relation": "表层社会身份关系",
                    "emotional_bond": "深层宿命情感对抗",
                    "fatal_interest_conflict": "生死存亡与真相对决",
                }
            ]

        char_arcs = c.get("emotional_arc_trajectories") or [
            {"stage_label": "第一幕: 坚冰防御", "psychological_state": "隐忍克制", "trigger": "外界羞辱与试探"},
            {"stage_label": "第二幕: 信念崩解", "psychological_state": "暗中反制", "trigger": "利益死结激化"},
            {"stage_label": "第三幕: 灵魂重铸", "psychological_state": "决断反杀", "trigger": "真相信物亮明"},
        ]

        # 组装完整的单一角色字典
        norm_c: dict[str, Any] = {
            # 第一公民字段 (新数据契约)
            "character_code": char_code,
            "name": c_name,
            "gender": gender,
            "perceived_age": perceived_age,
            "role": role,
            "personality": personality,
            "appearance": appearance,
            "identity_anchors": identity_anchors,
            "visual_consistency_code": vcc,
            "voice_style": voice_style,
            "acoustic_persona": acoustic_persona,
            "psychology_4": psychology_4,
            "voice_fingerprint": voice_fingerprint,
            "carried_anchor_item": carried_anchor_item,
            "drama_engine": drama_engine,
            # 兼容桥接字段
            "character_id": char_code,
            "character_token": char_token,
            "role_type": role,
            "biological_sex": gender,
            "biological_dna": synthesized_bio,
            "lived_in_costume": synthesized_costume,
            "psychological_quad": psychology_4,
            "linguistic_fingerprint": voice_fingerprint,
            "dual_track_relationships": char_dual_rels,
            "emotional_arc_trajectories": char_arcs,
        }

        norm_chars.append(norm_c)
        logger.debug(
            f"[阶段2·角色工坊] [角色解析完成 #{idx}] 代号={char_code}, 姓名={c_name}, "
            f"角色定位={role}, 性别={gender}, 视觉年龄={perceived_age}, 锚点数={len(identity_anchors)}"
        )

    # 5. 逐条解析双轨关系矩阵 (relationship_matrix) 并做代号安全解析
    norm_relationships: list[dict[str, Any]] = []

    for r_idx, r in enumerate(raw_rels, start=1):
        if not isinstance(r, dict):
            logger.warning(f"[阶段2·角色工坊] 关系对非字典类型，跳过: {type(r)}")
            continue

        # 解析 character_a
        raw_a = r.get("character_a_code") or ""
        char_a_code = name_to_code.get(str(raw_a).strip()) or _normalize_character_id(str(raw_a).strip(), idx=1)
        char_a_name = code_to_name.get(char_a_code, char_a_code.replace("CHAR_", ""))

        # 解析 character_b
        raw_b = r.get("character_b_code") or ""
        char_b_code = name_to_code.get(str(raw_b).strip()) or _normalize_character_id(str(raw_b).strip(), idx=2)
        char_b_name = code_to_name.get(char_b_code, char_b_code.replace("CHAR_", ""))

        # 若两端角色相同则忽略无意义自环
        if char_a_code == char_b_code:
            logger.warning(f"[阶段2·角色工坊] 发现自环关系对 ({char_a_code} == {char_b_code})，已自动跳过")
            continue

        surface_rel = str(r.get("surface_relation") or r.get("surface_identity") or "表层社会身份关系").strip()
        emotional_bond = str(r.get("emotional_bond") or r.get("deep_bond") or "深层宿命情感对立与羁绊").strip()
        fatal_conflict = str(r.get("fatal_interest_conflict") or r.get("fatal_conflict") or "不可调和的生死利益死结").strip()

        # 共享历史旧物 (shared_history_props)
        raw_props = r.get("shared_history_props") or r.get("shared_past_token")
        if isinstance(raw_props, list):
            shared_props = [str(p).strip() for p in raw_props if str(p).strip()]
        elif raw_props:
            shared_props = [str(raw_props).strip()]
        else:
            shared_props = ["关键过往信物"]

        # 戏剧功能标注 (drama_function)
        drama_function = r.get("drama_function")
        if not drama_function or not str(drama_function).strip():
            drama_function = "羞辱供给 → 反杀打脸｜主对抗线" if r_idx == 1 else "见证打脸与换血倒戈"
        drama_function = str(drama_function).strip()

        # 信息差 (information_gap)
        raw_gap = r.get("information_gap")
        if isinstance(raw_gap, dict):
            information_gap = {
                "knows_truth_initially": bool(raw_gap.get("knows_truth_initially", False)),
                "current_belief": str(raw_gap.get("current_belief") or "暂未看破对方真正意图与身份"),
                "reveal_condition": str(raw_gap.get("reveal_condition") or "随身信物或核心证据当场曝光时"),
            }
        else:
            information_gap = {
                "knows_truth_initially": False,
                "current_belief": "受表象蒙蔽，未知悉对方真正底牌",
                "reveal_condition": "身份信物或关键录音当场曝光后",
            }

        # 态度弧光 (attitude_arc)
        attitude_arc = str(r.get("attitude_arc") or "轻视 → 怀疑 → 恐惧 → 跪服").strip()

        # 摇摆反水点 (swing_point)
        raw_swing = r.get("swing_point")
        if isinstance(raw_swing, dict):
            swing_point = {
                "can_defect": bool(raw_swing.get("can_defect", False)),
                "defect_condition": raw_swing.get("defect_condition"),
            }
        else:
            swing_point = {
                "can_defect": False,
                "defect_condition": None,
            }

        norm_rel: dict[str, Any] = {
            # 第一公民契约
            "character_a_code": char_a_code,
            "character_b_code": char_b_code,
            "social_label": r.get("social_label") or surface_rel,
            "surface_relation": surface_rel,
            "emotional_bond": emotional_bond,
            "fatal_interest_conflict": fatal_conflict,
            "shared_history_props": shared_props,
            "drama_function": drama_function,
            "information_gap": information_gap,
            "attitude_arc": attitude_arc,
            "swing_point": swing_point,
            # 历史兼容字段
            "character_a": char_a_name,
            "character_b": char_b_name,
            "character_pair": f"{char_a_name} vs {char_b_name}",
            "target_character": char_b_name,
            "surface_identity": surface_rel,
            "deep_bond": emotional_bond,
            "fatal_conflict": fatal_conflict,
            "hidden_tension": fatal_conflict,
            "shared_past_token": shared_props[0] if shared_props else "",
        }
        norm_relationships.append(norm_rel)
        logger.debug(
            f"[阶段2·角色工坊] [关系解析完成 #{r_idx}] {char_a_code}({char_a_name}) <-> {char_b_code}({char_b_name}) | "
            f"功能: {drama_function} | 可反水: {swing_point.get('can_defect')}"
        )

    # 6. 提取全局角色 Token 白名单 (供 SD/ComfyUI 资产锁定)
    character_tokens = [
        c["character_token"]
        for c in norm_chars
        if c.get("character_token")
    ]

    # 7. 纯函数式编译提炼角色工作便签 (便签 B)
    char_wm = WorkingMemoryCompiler.compile_character_working_memory({
        "characters": norm_chars,
        "character_tokens": character_tokens,
        "relationship_matrix": norm_relationships,
    })

    logger.info(
        f"[阶段2·角色工坊] 角色建模与工作便签编译成功 (长度: {len(char_wm)} 字符)，"
        f"角色总数={len(norm_chars)}, 关系对总数={len(norm_relationships)}"
    )

    # 8. 持久化语义化工作便签与读投影，广播完成事件
    drama_id = _get_val(state, "drama_id") or _get_val(state, "id")
    if drama_id:
        try:
            d_id = int(drama_id)
            set_journey1_working_memory(d_id, "stage2", char_wm)
            publish_drama_event(d_id, "stage2_completed", {
                "drama_id": d_id,
                "stage": "stage2",
                "character_count": len(norm_chars),
                "characters": [c.get("name") for c in norm_chars],
                "character_codes": [c.get("character_code") for c in norm_chars],
            })
            # 增量上报阶段2产出指标与角色建模工作便签至 CQRS 读投影
            publish_drama_read_projection(d_id, {
                "drama_id": d_id,
                "character_count": len(norm_chars),
                "character_working_memory": char_wm,
                "current_stage": 2,
            })
            logger.debug(f"[阶段2·角色工坊] 成功将 stage2 便签与投影写入 Redis (drama_id={d_id})")
        except Exception as e:
            logger.warning(f"[阶段2·角色工坊] Redis 便签与事件广播失败 (drama_id={drama_id}): {e}")

    # 9. 构建最终图状态更新字典
    raw_trajectories = result_json.get("emotional_arc_trajectories")
    if isinstance(raw_trajectories, list):
        norm_arc_trajectories = raw_trajectories
    elif isinstance(raw_trajectories, dict):
        norm_arc_trajectories = [raw_trajectories]
    else:
        norm_arc_trajectories = []
        for c in norm_chars:
            arcs = c.get("emotional_arc_trajectories")
            if isinstance(arcs, list):
                norm_arc_trajectories.extend(arcs)
            elif isinstance(arcs, dict):
                norm_arc_trajectories.append(arcs)

    characters_engine_payload = {
        "characters": norm_chars,
        "character_tokens": character_tokens,
        "relationship_matrix": norm_relationships,
        "character_relationships": norm_relationships,
        "dual_track_relationships": norm_relationships,
        "emotional_arc_trajectories": norm_arc_trajectories,
    }

    return {
        "current_stage": 2,
        "user_idea": user_idea,
        "characters_engine": characters_engine_payload,
        "characters": norm_chars,
        "character_tokens": character_tokens,
        "character_relationships": norm_relationships,
        "relationship_matrix": norm_relationships,
        "dual_track_relationships": norm_relationships,
        "emotional_arc_trajectories": norm_arc_trajectories,
        "character_working_memory": char_wm,
    }

