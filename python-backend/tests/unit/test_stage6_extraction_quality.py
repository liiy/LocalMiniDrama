# -*- coding: utf-8 -*-
"""阶段 6 资产抽取质效与提示词剧情契合度升级的专用单元测试套件。

覆盖 4 大核心重构模块：
1. 角色前置白名单裁剪（project_characters_for_stage6）：根据剧本预扫描与出场实体过滤，阻断未登场角色。
2. 角色后置硬拦截防线（is_character_truly_in_screenplay）：杜绝大模型偶发幻觉输出未登场幽灵角色。
3. 场景子机位（Zone）与手持交互物证（Prop）自动补录。
4. 提示词剧情感官自动增强（PromptSynthesizer.enrich_narrative_prompt）：去占位符、注入微表情、气候光影与微观物理机理。
"""

import pytest
from app.workflows.nodes.stage6_asset_truth import (
    project_characters_for_stage6,
    is_character_truly_in_screenplay,
    stage6_asset_truth_node,
)
from app.workflows.utils.prompt_synthesizer import PromptSynthesizer
from app.schemas.script_graph_state import IndustrialDramaMasterState


def test_character_pre_filtering_and_projection():
    """验证 1：全剧多角色库在前置投影时，仅保留当集真实登场的角色。"""
    full_chars_engine = {
        "characters": [
            {"character_id": "CHAR_LUCHEN_T1_BASE", "name": "陆晨", "aliases": ["小陆", "陆总"]},
            {"character_id": "CHAR_SUQING_T1_BASE", "name": "苏清", "aliases": ["苏医生"]},
            {"character_id": "CHAR_WANG_T1_BASE", "name": "王麻子", "aliases": ["反派刀疤"]},
            {"character_id": "CHAR_GHOST_T1_BASE", "name": "路人甲", "aliases": []},
        ]
    }
    # 当集剧本只有陆晨和苏清出场，王麻子和路人甲未出场
    screenplay_text = "【场景：医院回廊 - 夜】\n陆晨快步走过回廊，拉住苏清的手臂。\n陆晨：“药剂在哪里？”\n苏清眼眶泛红，递出试管。"
    detected_chars = ["陆晨", "苏清"]
    alias_map = {"小陆": "陆晨", "苏医生": "苏清"}

    projected = project_characters_for_stage6(
        chars_engine=full_chars_engine,
        present_names=detected_chars,
        screenplay_text=screenplay_text,
        alias_map=alias_map,
    )

    projected_names = [c["name"] for c in projected]
    assert "陆晨" in projected_names
    assert "苏清" in projected_names
    assert "王麻子" not in projected_names
    assert "路人甲" not in projected_names


def test_character_post_guard_verification():
    """验证 2：后置硬拦截校验器能够精准识别真实出场角色并剔除幽灵角色。"""
    screenplay_text = "【场景：天台 - 雨夜】\n沈炼手按刀柄，注视着对面的丁修。\n丁修冷笑：“公公要你死。”"
    detected_pool = {"沈炼", "丁修"}
    alias_map = {"靳一川": "三弟"}

    char_shen = {"asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT", "name": "沈炼"}
    char_ding = {"asset_id": "CHAR_DINGXIU_T1_BASE_PORTRAIT", "name": "丁修"}
    char_ghost = {"asset_id": "CHAR_ZHAO_T1_BASE_PORTRAIT", "name": "赵靖忠"}

    assert is_character_truly_in_screenplay(char_shen, screenplay_text, detected_pool, alias_map) is True
    assert is_character_truly_in_screenplay(char_ding, screenplay_text, detected_pool, alias_map) is True
    assert is_character_truly_in_screenplay(char_ghost, screenplay_text, detected_pool, alias_map) is False

    # 验证非在场虚拟语境：动作行中提到回忆、想起、画像、信笺的角色不能被误判为物理登场
    screenplay_virtual = (
        "【场景：书房 - 夜】\n"
        "沈炼站在窗前，想起多年前陆文昭对他说过的话。\n"
        "墙上挂着周妙彤的画像，桌上放着丁白缨留下的绝笔信。\n"
        "沈炼握紧绣春刀，眼神冰冷。"
    )
    char_lu = {"asset_id": "CHAR_LU_T1_BASE", "name": "陆文昭"}
    char_zhou = {"asset_id": "CHAR_ZHOU_T1_BASE", "name": "周妙彤"}
    char_ding_bai = {"asset_id": "CHAR_DINGBAI_T1_BASE", "name": "丁白缨"}
    # 即使在宽松的 detected_pool 中包含了这些被提及的名字，后置拦截也必须精准剔除
    virtual_pool = {"沈炼", "陆文昭", "周妙彤", "丁白缨"}
    assert is_character_truly_in_screenplay(char_shen, screenplay_virtual, virtual_pool) is True
    assert is_character_truly_in_screenplay(char_lu, screenplay_virtual, virtual_pool) is False
    assert is_character_truly_in_screenplay(char_zhou, screenplay_virtual, virtual_pool) is False
    assert is_character_truly_in_screenplay(char_ding_bai, screenplay_virtual, virtual_pool) is False


def test_narrative_prompt_enrichment():
    """验证 3：PromptSynthesizer 能自动清洗空洞占位符并注入真实剧情感官物理属性。"""
    raw_char_prompt = "cinematic photorealistic 8k, character standing, visual style: [visual_style] --style raw"
    enriched_char = PromptSynthesizer.enrich_narrative_prompt(
        base_prompt=raw_char_prompt,
        category="character",
        narrative_context={
            "emotion": "clenched jaw, intense bloodshot eyes",
            "battle_damage": "slashed shoulder with bleeding bandage",
        },
        visual_style="neo-noir cyberpunk",
    )
    # 占位符必须被消除
    assert "[visual_style]" not in enriched_char
    assert "neo-noir cyberpunk" in enriched_char
    # 必须注入剧情情绪与战损
    assert "clenched jaw" in enriched_char
    assert "slashed shoulder" in enriched_char
    assert "85mm portrait lens" in enriched_char

    raw_env_prompt = "cinematic photorealistic 8k, abandoned warehouse wide shot, visual style: [visual_style] --style raw"
    enriched_env = PromptSynthesizer.enrich_narrative_prompt(
        base_prompt=raw_env_prompt,
        category="scene",
        narrative_context={
            "weather": "heavy torrential rain and thunder",
            "narrative_traces": "shattered glass bottles and muddy footprints on concrete floor",
            "lighting": "cold moonlight backlighting",
        },
        visual_style="dark cinematic gritty",
    )
    assert "[visual_style]" not in enriched_env
    assert "heavy torrential rain" in enriched_env
    assert "shattered glass bottles" in enriched_env
    assert "35mm cinematic anamorphic lens" in enriched_env

    raw_prop_prompt = "cinematic photorealistic 8k hero prop, encrypted USB drive, visual style: [visual_style] --style raw"
    enriched_prop = PromptSynthesizer.enrich_narrative_prompt(
        base_prompt=raw_prop_prompt,
        category="prop",
        narrative_context={
            "placement_surface": "resting on wet rusted iron plate",
            "wear_and_tear": "deep metallic scratches and blood fingerprints",
        },
        visual_style="hardboiled suspense",
    )
    assert "[visual_style]" not in enriched_prop
    assert "resting on wet rusted iron plate" in enriched_prop
    assert "deep metallic scratches" in enriched_prop
    assert "100mm macro lens" in enriched_prop


def test_stage6_end_to_end_scene_zone_and_prop_enrichment(monkeypatch):
    """验证 4：stage6_asset_truth_node 端到端能自动补全场景机位 Zone 与手持交互道具底模，并剔除未出场角色。"""
    # 模拟大模型输出：大模型由于格式强迫症，输出了本集中并未登场的反派“魏忠贤”
    mock_llm_response = {
        "episode_resource_manifest": {
            "episode_num": 1,
            "characters": [
                {
                    "asset_id": "CHAR_SHENLIAN_T1_BASE_PORTRAIT",
                    "name": "沈炼",
                    "visual_prompt": "沈炼正面肖像，visual style: [visual_style] --style raw",
                },
                {
                    "asset_id": "CHAR_WEIZHONGXIAN_T1_BASE_PORTRAIT",
                    "name": "魏忠贤",
                    "visual_prompt": "魏忠贤坐姿，visual style: [visual_style] --style raw",
                },
            ],
            "environments": [
                {
                    "asset_id": "ENV_STATION_T1_WIDE",
                    "name": "废弃客栈",
                    "visual_prompt": "客栈大堂全景，visual style: [visual_style] --style raw",
                }
            ],
            "props": [
                {
                    "asset_id": "PROP_SWORD_T1_STATIC",
                    "name": "绣春刀",
                    "visual_prompt": "出鞘的绣春刀，visual style: [visual_style] --style raw",
                }
            ],
        }
    }

    # 模拟 call_llm_json 返回 mock_llm_response
    monkeypatch.setattr(
        "app.workflows.nodes.stage6_asset_truth.call_llm_json",
        lambda *args, **kwargs: mock_llm_response,
    )

    state = IndustrialDramaMasterState(
        project_id="proj_test_quality_001",
        current_episode=1,
        visual_style="cinematic photorealistic 8k, wuxia neo-noir",
        completed_screenplays={
            1: {
                "body_markdown": "【场景：废弃客栈 - 夜】\n沈炼握紧绣春刀，在生锈铁梯旁警惕四周。\n沈炼从怀中取出一枚纯铜腰牌，放在破损八仙桌上。"
            }
        },
        characters_engine={
            "characters": [
                {"character_id": "CHAR_SHENLIAN_T1_BASE", "name": "沈炼"},
                {"character_id": "CHAR_WEIZHONGXIAN_T1_BASE", "name": "魏忠贤"},
            ]
        },
        environments_and_props_registry={
            "environments": {"ENV_STATION_T1_WIDE": {"name": "废弃客栈"}},
            "props": {"PROP_SWORD_T1_STATIC": {"name": "绣春刀"}},
        },
    )

    out_state = stage6_asset_truth_node(state)
    manifest = out_state.get("episode_resource_manifest")
    assert manifest is not None

    # 1. 验证未登场的“魏忠贤”被后置拦截成功剔除
    char_names = [c.get("name") if isinstance(c, dict) else getattr(c, "name", "") for c in manifest.characters]
    assert "沈炼" in char_names
    assert "魏忠贤" not in char_names, "未出场的魏忠贤必须被后置硬拦截过滤！"

    # 2. 验证场景子区域 Zone 自动被实体化为机位资产
    env_asset_ids = [e.get("asset_id") if isinstance(e, dict) else getattr(e, "asset_id", "") for e in manifest.environments]
    # 客栈在剧本中有"生锈铁梯"等交互区，扫描器或补录会生成对应 Z01/Z02
    assert any("Z0" in aid for aid in env_asset_ids), "应当包含二级子机位 Zone 资产"

    # 3. 验证手持动宾道具“纯铜腰牌”/“腰牌”被自动补全标准 S0 底模
    prop_names = [p.get("name") if isinstance(p, dict) else getattr(p, "name", "") for p in manifest.props]
    assert any("腰牌" in p_name for p_name in prop_names), "动作行中的手持交互道具[腰牌]必须被自动补录"

    # 4. 验证提示词经过剧情感官增强，占位符被清除且融合了世界观与摄影规格
    for c in manifest.characters:
        v_prompt = c.get("visual_prompt") if isinstance(c, dict) else getattr(c, "visual_prompt", "")
        assert "[visual_style]" not in v_prompt
    for c in manifest.characters_tier_1:
        v_prompt = c.get("visual_prompt") if isinstance(c, dict) else getattr(c, "visual_prompt", "")
        assert "85mm portrait" in v_prompt


def test_lingtang_scene_evidence_binary_and_character_presence():
    """验证苏秀兰灵堂真实剧本片段：
    1. 道具二元分流：【带血的牛皮纸信封】、【老邮局挂号信寄件存根小联】、【抑郁症处方笺】、【自杀结案卷宗】、【保温杯】、【手电筒】作为独立道具，坚决杜绝“转信封”垃圾词；
    2. 空间固定陈设（棺木、铁盆、遗像）不得作为独立道具；
    3. 声学生理在场人物【周正国】成功被检出并纳入出场；
    4. 死者【苏秀兰】坚决被判定为非活体角色，严禁出现在角色列表中。
    """
    from app.tools.screenplay_feature_scanner import ScreenplayFeatureScanner

    lingtang_screenplay = (
        "【场景 01】内景. 苏秀兰旧居灵堂 - 深夜 - 昏暗钨丝灯与惨白雨夜光\n"
        "[声学行为: 开场突发重击 Braam Hit]\n"
        "△ 【开局3秒抓手】灵堂棺木前生锈铁盆内的黄纸骤然被穿堂阴风吹散，一只【带血的牛皮纸信封】啪地甩在苏秀兰黑白遗像玻璃框上，玻璃当场震出细裂纹。\n"
        "△ 林晚猛地跨前一步，指节发白地将信封从裂开的镜框上狠狠扯下。\n"
        "△ 周衍身穿深蓝执勤夹克立在供桌旁，将厚重的【苏秀兰坠楼案自杀结案卷宗】推向桌面中央。\n"
        "周衍（双手紧握脱漆保温杯，喉腔沉闷发紧）：签了这份自杀确认书，让伯母早点入土为安。\n"
        "林晚（左手拇指死扣右手腕银手链，声线偏冷下坠）：新闻只认证据，不认眼泪。\n"
        "△ 周衍从卷宗夹层抽出一张泛黄的【抑郁症处方笺】，重重拍在油腻的供桌上。\n"
        "周衍（大拇指用力刮蹭保温杯盖脱漆边缘，语速沉缓）：法医的病历清清楚楚，坠楼前半年她就患病了。\n"
        "林晚（下颌咬肌隆起，齿缝间挤出微颤冷气）：你们习惯了沉默，不代表事情没发生过。\n"
        "△ 林晚指尖发力刺破信封干硬的纸边，刺啦一声撕开封口。\n"
        "△ 【45秒微反转】林晚翻转信封，一张按着鲜红血指印的【老邮局挂号信寄件存根小联】滑落掌心，寄出时间赫然印着坠楼前两小时。\n"
        "[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]\n"
        "△ 周衍低头看清存根上的紫色机打时间，双眼瞳孔骤然缩紧。\n"
        "周衍（喉头剧烈上下滚动，声带沙哑收紧）：说话要有法律依据，我只认结案报告。\n"
        "林晚（抬眼逼视周衍双眸，字字如冰断崖下坠）：一个要寻死的人，会在跳楼前两小时去寄信？\n"
        "△ 周衍跨步上前伸手抓向存根，林晚后撤半步侧身避开，风衣下摆撞落桌角纸灰。\n"
        "周衍（右手食指死死按住战术皮带，压低气音低吼）：林晚，查下去整座城都要塌，你负得起责任吗？\n"
        "林晚（左手指甲深陷手腕皮肉泛白，声线冷硬如铁）：我只负责把盖在棺材上的黑布掀开。\n"
        "△ 林晚拔出金属手电筒推上开关，惨白光束笔直穿透信封内层折叠的信纸。\n"
        "△ 【115秒片尾悬念】手电强光穿透信纸，纸面赫然渗出一行干涸暗红血字「晚晚，杀我的人正坐在我的追悼会主宾席上」，门外走廊骤然响起周正国沉重缓慢的皮鞋脚步声。\n"
        "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"
    )

    # 1. 验证特征扫描器对物证的精确抽取
    known_chars = {"林晚": "CHAR_LINWAN", "周衍": "CHAR_ZHOUYAN", "周正国": "CHAR_ZHOUZHENGGUO", "苏秀兰": "CHAR_SUXIULAN"}
    scan_res = ScreenplayFeatureScanner.scan(
        screenplay_text=lingtang_screenplay,
        known_characters=known_chars,
    )
    detected_props = {p if isinstance(p, str) else p.get("name") for p in scan_res.props_detected}

    # 验证核心物证精确捕获
    assert any("信封" in p for p in detected_props), "必须识别出核心信封道具"
    assert any("挂号信" in p or "存根" in p for p in detected_props), "必须识别出寄件存根"
    assert any("处方笺" in p for p in detected_props), "必须识别出处方笺"
    assert any("卷宗" in p for p in detected_props), "必须识别出卷宗"
    # 验证杜绝谓语残缺病态词
    assert "转信封" not in detected_props, "绝对严禁抽取到动宾残缺的'转信封'！"
    # 验证空间陈设不作为独立道具
    assert "棺木" not in detected_props and "灵堂棺木" not in detected_props, "灵堂棺木应作为场景陈设，不能作为独立道具"
    assert "铁盆" not in detected_props and "生锈铁盆" not in detected_props, "生锈铁盆应作为场景陈设，不能作为独立道具"

    # 2. 验证声学在场人物与死者消歧
    assert is_character_truly_in_screenplay("林晚", lingtang_screenplay) is True
    assert is_character_truly_in_screenplay("周衍", lingtang_screenplay) is True
    assert is_character_truly_in_screenplay("周正国", lingtang_screenplay) is True, "周正国通过脚步声物理压迫登场，必须判定在场！"
    assert is_character_truly_in_screenplay("苏秀兰", lingtang_screenplay) is False, "苏秀兰仅作为灵堂、遗像、案卷定语出现，必须判定为未登场（死者消歧）！"
