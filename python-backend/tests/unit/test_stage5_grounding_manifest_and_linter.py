"""【阶段 5 视听剧本文学工笔大纲对齐与确定性 Linter 单元测试】

验证内容：
1. Top-Level Mandatory Action Manifest 绝对执行纲领构建：
   - 包含大纲四大核心节拍（戏剧任务、3s抓手、45s微反转、115s片尾悬念）；
   - 包含上一集0秒物理快照（两拍起板执行令）；
   - 包含人物微观DNA、真实服饰代码与语言指纹；
   - 包含关键物证/道具做旧痕迹与反转密码；
   - 包含双轨禁令母库与剧作红线。
2. 语义关键词提取与重合度判定算子 (_extract_semantic_keywords & _check_semantic_grounding_overlap)：
   - 准确提取中文 2~4 元分词块，过滤停用词；
   - 准确判定大纲锚点与剧本动作的语义重合；
   - 准确识别无交集的大模型注意力漂移/幻觉。
3. 确定性 Linter 自动纠偏与大纲对齐 (_lint_and_autofix_screenplay_text)：
   - 识别大模型生成的抓手与大纲脱节，强制水合并熔接大纲真实 3s 抓手；
   - 识别大模型生成的微反转偏离，强制水合大纲 45s 微反转；
   - 识别大模型生成的片尾悬念偏离，强制纠偏为大纲 115s 绝杀断点；
   - 自动执行第 2 集及以后的 Two-Beat 0 秒快照两拍起板咬合；
   - 自动熔接多行对白为单行标准格式；
   - 自动将单镜头超长台词 (>22字) 拆分为符合口语断句的短句。
4. 保底工厂与单集生成管线集成测试：
   - _stage5_fallback_episode 包含 pre_flight_grounding 矩阵；
   - generate_single_episode 成功组装 mandatory_action_manifest 并完成校验。
"""
from __future__ import annotations

import pytest

from app.workflows.nodes.stage5_screenplay import (
    _build_mandatory_action_manifest,
    _check_semantic_grounding_overlap,
    _extract_semantic_keywords,
    _lint_and_autofix_screenplay_text,
    _stage5_fallback_episode,
    generate_single_episode,
)


def test_extract_semantic_keywords():
    """测试中文语义关键词切分与停用词过滤。"""
    text = "沈炼猛地拔出染血的手术刀，死死按在办公桌上！"
    kw = _extract_semantic_keywords(text)
    assert "沈炼" in kw or "手术刀" in kw
    # 停用词不应在结果中
    assert "的" not in kw
    assert "在" not in kw


def test_check_semantic_grounding_overlap():
    """测试大纲与剧本语义关键词重合度判定。"""
    outline_hook = "主角反手拔出抽屉里的黄金怀表，摔在谈判桌上"
    
    # 语义高度重合的生成文本
    coherent_script = "△ 【开局3秒抓手】主角冷笑一声，猛地将黄金怀表砸向谈判桌！"
    assert _check_semantic_grounding_overlap(outline_hook, coherent_script) is True

    # 自由发挥、完全不相关的大模型幻觉文本
    hallucinated_script = "△ 【开局3秒抓手】窗外雷声滚滚，黑衣人缓缓点燃了一支香烟，仰望天花板。"
    assert _check_semantic_grounding_overlap(outline_hook, hallucinated_script) is False


def test_build_mandatory_action_manifest():
    """测试置顶绝对执行纲领（Mandatory Action Manifest）的构建完备性。"""
    outline = {
        "title": "破晓生死局",
        "core_dramatic_task": "逼迫赵崇山在监控前交出加密密钥",
        "hook_3s": "沈炼反手扣死安全门，将带血的警徽拍在赵崇山胸口",
        "micro_twist_45s": "保险箱开启却发现里面是一支空试管，赵崇山突然狂笑",
        "killer_cliffhanger_115s": "倒计时归零，沈炼一脚踹碎电闸，全楼陷入绝对黑暗！",
        "plot_event_chain": ["沈炼突入核心控制室", "赵崇山销毁纸质文件", "试管真相曝光", "黑客切断逃生通道"],
    }
    snapshot = {
        "freeze_frame_desc": "沈炼手握滴血钢笔，左膝受创微屈，与赵崇山在密室门口持枪僵持",
        "posture_and_injuries": "左膝中弹擦伤，鲜血染透裤管",
        "carried_props_status": "右手紧握暗银色特制钢笔",
    }
    characters = [
        {
            "name": "沈炼",
            "role": "主角/前刑侦队长",
            "costume_physical_code": "磨损严重的黑色战术夹克，左袖撕裂露出生硬绷带",
            "voice_fingerprint": "声线极度沙哑，尾字短促如刀割，极少使用长句",
            "physiological_stress": "右侧额角青筋跳动，咬肌紧绷如石",
        },
        {
            "name": "赵崇山",
            "role": "反派/幕后操控者",
            "costume_physical_code": "定制深灰羊绒西装，领针歪斜，袖口微沾灰尘",
            "voice_fingerprint": "语调假意温和优雅，遇险时呼吸急促高亢",
            "physiological_stress": "右手食指不自主抽搐，频繁抚摸金表表盘",
        },
    ]
    props = [
        {
            "name": "加密U盘",
            "patina_and_wear": "金属外壳布满深浅不一的刮痕与灼烧印记",
            "dramatic_function": "记录集团终极洗钱流水与名单的唯一物证",
        }
    ]
    negative_rules = ["严禁出现警察出警拯救的机械降神结局"]

    manifest = _build_mandatory_action_manifest(
        episode_num=2,
        outline=outline,
        incoming_snapshot=snapshot,
        characters=characters,
        props=props,
        negative_rules=negative_rules,
    )

    # 验证四大锚点
    assert "沈炼反手扣死安全门" in manifest
    assert "保险箱开启却发现里面是一支空试管" in manifest
    assert "倒计时归零，沈炼一脚踹碎电闸" in manifest
    # 验证快照与两拍起板
    assert "两拍起板执行令" in manifest
    assert "沈炼手握滴血钢笔" in manifest
    # 验证服饰代码与语言指纹
    assert "黑色战术夹克" in manifest
    assert "声线极度沙哑" in manifest
    # 验证道具做旧
    assert "加密U盘" in manifest
    assert "金属外壳布满深浅不一的刮痕" in manifest
    # 验证红线
    assert "机械降神" in manifest


def test_linter_autofix_hallucinated_hook_and_twist():
    """测试当大模型剧本正文偏离大纲时，Linter 自动检测并强制水合纠偏。"""
    outline = {
        "hook_3s": "沈炼猛地掀翻实木茶几，带血的匕首扎穿桌面支票",
        "micro_twist_45s": "密信夹层滑出一张泛黄的双人合照，赵崇山表情瞬间僵死",
        "killer_cliffhanger_115s": "红外引信被骤然拉断，火光照亮沈炼冰冷双眸",
    }
    
    # 模拟大模型自由发挥、完全不顾大纲的剧本正文
    hallucinated_script = """【场景 01】内景. 集团办公室 - 日
△ 【开局3秒抓手】沈炼缓缓倒了一杯红酒，在沙发上坐了下来，凝视着窗外的雨滴。
沈炼（神情平静）：今天天气真糟糕。
赵崇山（冷笑一声）：你果然还是来了。
△ 【45秒微反转】赵崇山突然从口袋里掏出一张银行卡扔在地上。
沈炼（声线微低）：你以为这能收买我？
△ 【115秒片尾悬念】沈炼转身走向大门，背影消失在风雨中。
[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"""

    corrected_script = _lint_and_autofix_screenplay_text(
        screenplay_text=hallucinated_script,
        characters=[{"name": "沈炼"}, {"name": "赵崇山"}],
        episode_num=1,
        outline=outline,
    )

    # 验证大纲的真实动作已被水合注入
    assert "沈炼猛地掀翻实木茶几" in corrected_script
    assert "密信夹层滑出一张泛黄的双人合照" in corrected_script
    assert "红外引信被骤然拉断" in corrected_script
    # 验证三大声学行为标记闭环
    assert "[声学行为: 开场突发重击 Braam Hit]" in corrected_script
    assert "[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]" in corrected_script
    assert "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！" in corrected_script


def test_linter_two_beat_pickup_for_episode_2():
    """测试第 2 集剧本承接第 1 集快照的两拍起板执行。"""
    snapshot = {
        "freeze_frame_desc": "沈炼后背死死顶住防爆门，左肩血流如注，枪口直指走廊尽头",
    }
    outline = {
        "hook_3s": "走廊尽头爆裂出耀眼强光，重装突击手破门而入",
    }
    raw_script = """【场景 01】内景. 走廊 - 夜
△ 突击队员冲了进来，枪声大作。
沈炼（咬紧牙关，声带嘶哑）：别想活着过去！"""

    corrected = _lint_and_autofix_screenplay_text(
        screenplay_text=raw_script,
        characters=[{"name": "沈炼"}],
        episode_num=2,
        outline=outline,
        incoming_snapshot=snapshot,
    )

    lines = [l.strip() for l in corrected.splitlines() if l.strip()]
    
    # 验证两拍起板：第1拍 0秒快照承接，第2拍 Braam Hit + 3秒抓手
    assert any("【0秒快照承接】" in l and "沈炼后背死死顶住防爆门" in l for l in lines)
    assert any("[声学行为: 开场突发重击 Braam Hit]" in l for l in lines)
    assert any("【开局3秒抓手】" in l and "走廊尽头爆裂出耀眼强光" in l for l in lines)


def test_stage5_fallback_with_pre_flight_grounding():
    """测试保底生成算法包含了思维链契约矩阵 pre_flight_grounding 与两拍起板。"""
    outline = {
        "title": "绝境反杀",
        "hook_3s": "沈炼一脚踢飞桌面灭火器，撞碎防弹玻璃",
        "micro_twist_45s": "遥控引爆器指示灯变成绿色，信号源竟然在自己身上",
        "killer_cliffhanger_115s": "赵崇山狞笑着按死双向闭锁开关，电梯急坠！",
        "dual_helix_task": {
            "plot_event_chain": ["撞碎玻璃", "夺取引爆器", "发现信号源"],
            "relational_shift_point": "师徒恩情彻底化为杀机",
        }
    }
    snapshot = {
        "freeze_frame_desc": "沈炼左膝跪地，掌心抵住地面碎玻璃",
    }
    chars = [{"name": "沈炼"}, {"name": "赵崇山"}]
    envs = [{"location_name": "顶层观光电梯"}]
    props = [{"name": "灭火器"}, {"name": "引爆器"}]

    res = _stage5_fallback_episode(
        episode_num=2,
        outline=outline,
        incoming_snapshot=snapshot,
        characters=chars,
        environments=envs,
        props=props,
        aspect_ratio="9:16",
    )

    assert "pre_flight_grounding" in res
    pfg = res["pre_flight_grounding"]
    assert "沈炼一脚踢飞桌面灭火器" in pfg["outline_hook_3s"]
    assert "遥控引爆器指示灯变成绿色" in pfg["outline_micro_twist_45s"]
    assert "赵崇山狞笑着按死双向闭锁开关" in pfg["outline_cliffhanger_115s"]

    # 验证剧本正文中两拍起板
    body = res["screenplay_text"]
    assert "【0秒快照承接】" in body
    assert "【开局3秒抓手】" in body
    assert "沈炼一脚踢飞桌面" in body
    assert "【灭火器】" in body


def test_generate_single_episode_pipeline():
    """测试单集剧本生成完整流水线（状态注入、Top-Level Manifest构建、保底合成与AST解析）。"""
    state = {
        "drama_id": "test_drama_001",
        "total_episodes": 3,
        "target_episodes": 3,
        "aspect_ratio": "9:16",
        "season_outlines": {
            "1": {
                "title": "深渊凝视",
                "core_conflict_task": "揭穿假遗嘱",
                "hook_3s": "沈炼当众撕碎公证书，粉末扬在顾天成脸上",
                "micro_twist_45s": "公证书夹层显现暗红色指纹，属于已故老爷子",
                "killer_cliffhanger_115s": "顾天成猛地扣动扳机，枪口火光吞没镜头",
            }
        },
        "characters_engine": {
            "characters": [
                {
                    "name": "沈炼",
                    "role": "长子复仇者",
                    "costume_physical_code": "深灰修身西装，右袖口微卷",
                    "voice_fingerprint": "语调低沉沉稳，杀气内敛",
                },
                {
                    "name": "顾天成",
                    "role": "篡位义子",
                    "costume_physical_code": "纯白高定西服，佩戴纯金怀表",
                    "voice_fingerprint": "轻浮嘲弄，音调上扬",
                },
            ]
        },
        "environments_and_props": {
            "environments": [{"location_name": "顾氏家族宗祠议事厅"}],
            "props": [{"name": "公证书"}, {"name": "纯金怀表"}],
        },
        "negative_rules": ["严禁直接剧透幕后真凶姓名"],
    }

    result = generate_single_episode(state, episode_num=1)
    assert "script" in result
    assert "outgoing_snapshot" in result
    
    script = result["script"]
    assert script["episode_id"] == 1
    assert script["title"] == "深渊凝视"
    assert "ast_data" in script
    assert script["ast_data"] is not None

    body = script["screenplay_text"]
    assert "【开局3秒抓手】" in body
    assert "沈炼当众撕碎" in body
    assert "公证书" in body
    assert "【45秒微反转】" in body
    assert "【115秒片尾悬念】" in body
