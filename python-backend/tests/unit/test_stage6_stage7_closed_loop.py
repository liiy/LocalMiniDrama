# -*- coding: utf-8 -*-
"""阶段6资产提取与阶段7分镜生成的工业级全链路闭环测试 (Stage 6 & Stage 7 Closed Loop Test)。

覆盖5大核心断言：
1. 随身配饰动宾拦截：日常佩戴状态不晋升为独立道具，保留在角色定妆中；
2. 随身配饰物理动作剥离晋升：发生摘下/摔碎/脱落等物理交互时晋升为独立道具 (is_accessory_promoted=1)；
3. 道具物性提示词隔离：纯净物理属性，绝不混入人脸/五官/肖像等生物特征，负向词注入生物排他词；
4. 四大视听支柱与场景极简按需收敛：装配空间拓扑、光学光位、年代包浆、微气候介质；单机位场景不滥建 scene_zones；
5. 阶段7物理闭环门禁与彻底废除伪自愈：合法 NULL 存储，严禁虚假 zone_id=1 或悬空外键。
"""
from __future__ import annotations

import json
import re
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.schema import ensure_schema
from app.platform_common import now_iso
from app.workflows.operators.asset_trigger_operator_engine import (
    AssetTriggerOperatorEngine,
    classify_prop_accessory_promotion,
)
from app.workflows.utils.prompt_synthesizer import (
    PromptSynthesizer,
    GLOBAL_NEGATIVE_PROMPTS,
)
from app.workflows.adapters.stage_adapters.stage6.scene_persister import (
    persist_stage6_scenes,
)
from app.workflows.adapters.stage_adapters.stage6.prop_persister import (
    persist_stage6_props,
)
from app.workflows.adapters.stage_adapters.stage7_adapter import (
    save_storyboard_data_direct,
)


@pytest.fixture()
def memory_db():
    """创建基于内存的 SQLite 测试数据库，包含完整的 Schema。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        ensure_schema(conn)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_accessory_negative_interception():
    """断言1：随身配饰日常佩戴状态被算子拦截，不晋升为独立道具。"""
    prop_name = "祖传翡翠扳指"
    action_text = "李云飞右手拇指佩戴着祖传翡翠扳指，负手而立，眼神深邃。"

    is_promoted, narrative_cat, reason = classify_prop_accessory_promotion(
        prop_name=prop_name,
        action_or_screenplay=action_text,
    )

    # 日常佩戴动作 -> 拦截，不晋升
    assert is_promoted is False
    assert narrative_cat == "costume_accessory"
    assert "佩戴" in reason or "随身配饰" in reason

    # 算子引擎评估 -> 不产生道具资产，判定为 DEMOTED_TO_COSTUME_ACCESSORY
    res = AssetTriggerOperatorEngine.evaluate_prop_assets(
        prop_name=prop_name,
        canonical_id="PROP_JADE_RING",
        semantic_data={"action": action_text},
        screenplay_text=action_text,
    )
    assert res["decision"] == "DEMOTED_TO_COSTUME_ACCESSORY"
    assert len(res["assets"]) == 0
    assert res["is_accessory_promoted"] == 0


def test_accessory_positive_promotion():
    """断言2：随身配饰发生摘下、摔碎等物理剥离交互时，成功晋升为独立道具。"""
    prop_name = "祖传翡翠扳指"
    action_text = "李云飞勃然大怒，一把摘下祖传翡翠扳指，重重摔在青石案几上，扳指应声开裂！"

    is_promoted, narrative_cat, reason = classify_prop_accessory_promotion(
        prop_name=prop_name,
        action_or_screenplay=action_text,
    )

    # 物理剥离/破坏动作 -> 成功晋升
    assert is_promoted is True
    assert narrative_cat in ("key_narrative_clue", "physical_interaction_object")
    assert "摘下" in reason or "摔" in reason or "开裂" in reason

    # 算子引擎评估 -> 产生物理道具资产，且包含 T1_ACTION 破坏形态
    res = AssetTriggerOperatorEngine.evaluate_prop_assets(
        prop_name=prop_name,
        canonical_id="PROP_JADE_RING",
        semantic_data={"action": action_text},
        screenplay_text=action_text,
    )
    assert res["decision"] == "HERO_PROP_GENERATED"
    assert len(res["assets"]) >= 1
    asset_keys = [a["asset_key"] for a in res["assets"]]
    assert "PROP_JADE_RING_T1_STATIC" in asset_keys
    # 动作中提及开裂 -> 派生破坏形态
    assert "PROP_JADE_RING_T1_ACTION" in asset_keys
    assert res["is_accessory_promoted"] == 1


def test_prop_prompt_isolation_from_facial_features():
    """断言3：道具物性提示词彻底隔离人脸与生物肖像特征，负向词包含生物排他项。"""
    raw_desc = (
        "老旧桃木剑，剑柄缠绕着磨损褪色的粗麻绳，剑身刻有暗红朱砂符咒。"
        "李云飞剑眉星目，冷酷的脸庞上有一道刀疤，眼神锐利，五官棱角分明。"
    )

    # 1. 物理锚点提取过滤
    physical_anchor = PromptSynthesizer.extract_prop_physical_anchor({
        "name": "老旧桃木剑",
        "visual_prompt": raw_desc,
        "material": "桃木、麻绳、朱砂",
    })
    assert "桃木" in physical_anchor
    # 坚决切除角色的面部五官与肖像描述
    assert "剑眉" not in physical_anchor
    assert "脸庞" not in physical_anchor
    assert "刀疤" not in physical_anchor
    assert "五官" not in physical_anchor

    # 2. 道具多视角提示词合成
    synth_res = PromptSynthesizer.synthesize_prop_view_prompt(
        prop_or_prompt=physical_anchor,
        view_type="DETAIL",
        state_prompt="粗麻绳缠绕柄部，剑身朱砂微凹符咒，静置于青石条案",
    )
    view_prompt = synth_res.visual_prompt
    assert "桃木" in view_prompt
    assert "macro" in view_prompt.lower() or "extreme" in view_prompt.lower()
    # 检查英文与中文生物面部特征是否已被剔除
    for forbidden in [r"\bface\b", r"\beyes\b", "human portrait", "person holding", "五官", "肖像"]:
        assert not re.search(forbidden, view_prompt, flags=re.IGNORECASE)

    # 3. 负向提示词排他性检查
    prop_neg = GLOBAL_NEGATIVE_PROMPTS["PROP_NEGATIVE"].lower()
    assert "human" in prop_neg
    assert "face" in prop_neg
    assert "fingers" in prop_neg
    assert "person" in prop_neg


def test_scene_four_pillars_and_minimal_convergence(memory_db):
    """断言4：场景视听四大支柱装配与单建立镜头场景极简按需收敛（不产生假 scene_zones）。"""
    db = memory_db
    now = now_iso()

    # 初始化基础 drama 和 episode
    db.execute(
        text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (1, '测试剧', 'draft', :now, :now)"),
        {"now": now},
    )
    db.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, status, created_at, updated_at) VALUES (10, 1, 1, '第1集', 'draft', :now, :now)"),
        {"now": now},
    )
    db.commit()

    # 1. 验证四大视听支柱提示词装配
    env_prompt = PromptSynthesizer.assemble_environment_prompt(
        location="破败兰若寺正殿",
        time_weather="暴雨深夜",
        spatial_topology="进深十米木结构大殿，中央坍塌佛像，两侧风化立柱",
        optical_lighting="雷电冷白频闪侧光，殿角残烛摇曳暖光",
        weathering_patina="梁木朽烂脱漆，佛身暗褐蛛网，青砖覆满苍绿湿滑苔藓",
        micro_climate="破裂瓦缝倾泻细水流，潮湿阴冷水汽弥漫",
    )
    assert "破败兰若寺正殿" in env_prompt
    assert "进深十米木结构大殿" in env_prompt
    assert "雷电冷白频闪侧光" in env_prompt
    assert "梁木朽烂脱漆" in env_prompt
    assert "破裂瓦缝倾泻细水流" in env_prompt

    # 2. 持久化单建立镜头场景（无子空间对峙，极简按需收敛）
    persist_stage6_scenes(
        db=db,
        drama_id=1,
        curr_ep=1,
        episode_id=10,
        now=now,
        environments_manifest=[
            {
                "scene_name": "破败兰若寺正殿",
                "location": "破败兰若寺正殿",
                "time_lighting": "暴雨深夜",
                "spatial_topology": "进深十米木结构大殿，中央坍塌佛像",
                "optical_lighting": "雷电冷白频闪侧光",
                "weathering_patina": "梁木朽烂脱漆，青砖覆满苍绿湿滑苔藓",
                "micro_climate": "潮湿阴冷水汽弥漫",
                "zones": [],  # 单一建立镜头，不滥建二级机位
            }
        ],
        newly_discovered_scenes=[],
        newly_generated_assets=[],
        state=None,
    )
    db.commit()

    scene_row = db.execute(
        text("SELECT id, location, spatial_topology, lighting_rig, period_patina, atmospheric_medium FROM scenes WHERE drama_id = 1 AND location = '破败兰若寺正殿'")
    ).mappings().first()
    assert scene_row is not None
    scene_id = scene_row["id"]
    assert scene_id > 0

    # 验证数据库中四大视听支柱字段成功落库
    row = db.execute(
        text("SELECT location, spatial_topology, lighting_rig, period_patina, atmospheric_medium FROM scenes WHERE id = :id"),
        {"id": scene_id},
    ).mappings().first()
    assert row["location"] == "破败兰若寺正殿"
    assert "木结构" in row["spatial_topology"]
    assert "频闪" in row["lighting_rig"]
    assert "苔藓" in row["period_patina"]
    assert "水汽" in row["atmospheric_medium"]

    # 验证极简按需收敛：不生成任何 scene_zones 与 scene_weathering_views
    zone_count = db.execute(
        text("SELECT COUNT(*) AS cnt FROM scene_zones WHERE scene_id = :sid"),
        {"sid": scene_id},
    ).mappings().first()["cnt"]
    assert zone_count == 0

    view_count = db.execute(
        text("SELECT COUNT(*) AS cnt FROM scene_weathering_views WHERE scene_zone_id IN (SELECT id FROM scene_zones WHERE scene_id = :sid)"),
        {"sid": scene_id},
    ).mappings().first()["cnt"]
    assert view_count == 0


def test_stage7_gatekeeper_and_no_fake_self_healing(memory_db):
    """断言5：阶段7物理闭环门禁生效，合法 NULL 存储，彻底废除伪自愈与虚假外键。"""
    db = memory_db
    now = now_iso()

    # 1. 准备基础剧集与单建立镜头场景
    db.execute(
        text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (7, '玄幻短剧', 'draft', :now, :now)"),
        {"now": now},
    )
    db.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, status, created_at, updated_at) VALUES (281, 7, 1, '第1集：生死局', 'draft', :now, :now)"),
        {"now": now},
    )
    db.commit()

    # 阶段6场景持久化（无二级机位）
    persist_stage6_scenes(
        db=db,
        drama_id=7,
        curr_ep=1,
        episode_id=281,
        now=now,
        environments_manifest=[
            {
                "scene_name": "演武场擂台",
                "location": "演武场擂台",
                "time_lighting": "黄昏",
                "zones": [],
            }
        ],
        newly_discovered_scenes=[],
        newly_generated_assets=[],
        state=None,
    )
    db.commit()
    scene_row = db.execute(
        text("SELECT id FROM scenes WHERE drama_id = 7 AND location = '演武场擂台'")
    ).mappings().first()
    assert scene_row is not None
    scene_id = scene_row["id"]

    # 阶段6角色持久化
    db.execute(
        text("""
            INSERT INTO characters (id, drama_id, name, role, created_at, updated_at)
            VALUES (101, 7, '萧炎', 'protagonist', :now, :now)
        """),
        {"now": now},
    )
    db.execute(
        text("""
            INSERT INTO character_libraries (id, drama_id, name, category, created_at, updated_at)
            VALUES (201, 7, '萧炎', 'character', :now, :now)
        """),
        {"now": now},
    )

    # 阶段6道具持久化（晋升后的玄重尺）
    persist_stage6_props(
        db=db,
        drama_id=7,
        curr_ep=1,
        episode_id=281,
        now=now,
        props_manifest=[
            {
                "prop_name": "玄重尺",
                "category": "weapon",
                "narrative_category": "key_narrative_clue",
                "is_accessory_promoted": False,
                "material_specs": "乌铁黑晶",
                "craft_texture": "重尺无锋，遍布奇特晦涩纹路",
                "damage_states": [
                    {"state_code": "S0_PRISTINE", "state_label": "完好状态", "description": "漆黑无锋"},
                    {"state_code": "S1_CRACKED", "state_label": "开裂状态", "description": "表面浮现细密金裂纹"},
                ],
            }
        ],
        newly_discovered_props=[],
        newly_generated_assets=[],
        state=None,
    )
    db.commit()
    prop_row = db.execute(
        text("SELECT id FROM props WHERE drama_id = 7 AND name = '玄重尺'")
    ).mappings().first()
    assert prop_row is not None
    prop_id = prop_row["id"]
    db.commit()

    # 2. 模拟阶段7生成的分镜列表：
    # 镜头1：正常引用场景、萧炎、玄重尺（包含开裂动作）
    # 镜头2：尝试引用不存在的悬空道具【倚天剑】与悬空角色【张三丰】
    storyboards_payload = [
        {
            "storyboard_number": 1,
            "title": "拔尺对峙",
            "shot_type": "特写",
            "movement": "推镜头",
            "duration": 3.0,
            "scene_ref": "演武场擂台",
            "action": "萧炎握紧玄重尺，尺身金裂纹隐现，眼神凌厉。",
            "dialogue": "萧炎：三十年河东，三十年河西！",
            "characters": ["萧炎"],
            "props": ["玄重尺"],
        },
        {
            "storyboard_number": 2,
            "title": "悬空资产测试镜头",
            "shot_type": "中景",
            "movement": "静止",
            "duration": 2.5,
            "scene_ref": "演武场擂台",
            "action": "张三丰手持倚天剑遥遥相望。",
            "dialogue": "",
            "characters": ["张三丰"],  # 不存在于阶段6
            "props": ["倚天剑"],     # 不存在于阶段6
        },
    ]

    # 3. 执行阶段7持久化
    result = save_storyboard_data_direct(
        db=db,
        drama_id=7,
        episode_id=281,
        storyboard_data=storyboards_payload,
    )
    db.commit()

    assert result["storyboards"] == 2

    # 4. 严谨数据库断言：
    # 断言镜头1：
    sb1 = db.execute(
        text("SELECT * FROM storyboards WHERE episode_id = 281 AND storyboard_number = 1")
    ).mappings().first()
    assert sb1["scene_id"] == scene_id
    # 极简按需收敛：因为场景无 scene_zones，scene_zone_id 与 scene_weathering_view_id 必须为合法 NULL！
    # 绝不能出现虚拟伪自愈的 zone_id=1 或 sid*10+1
    assert sb1["scene_zone_id"] is None
    assert sb1["scene_weathering_view_id"] is None

    # 验证镜头1的角色关联：萧炎成功关联
    char1 = db.execute(
        text("SELECT * FROM storyboard_characters WHERE storyboard_id = :sbid"),
        {"sbid": sb1["id"]},
    ).mappings().first()
    assert char1 is not None
    assert char1["character_id"] == 101
    assert char1["character_lib_id"] == 201

    # 验证镜头1的道具关联：玄重尺成功关联，且动作中"裂纹"正确定位到 S1 战损形态
    prop1 = db.execute(
        text("SELECT * FROM storyboard_props WHERE storyboard_id = :sbid"),
        {"sbid": sb1["id"]},
    ).mappings().first()
    assert prop1 is not None
    assert prop1["prop_id"] == prop_id
    assert prop1["damage_state_id"] is not None

    # 断言镜头2（Gatekeeper门禁拦截验证）：
    sb2 = db.execute(
        text("SELECT * FROM storyboards WHERE episode_id = 281 AND storyboard_number = 2")
    ).mappings().first()
    assert sb2["scene_id"] == scene_id

    # 悬空角色张三丰被 Gatekeeper 拦截，不插入 storyboard_characters
    chars2_count = db.execute(
        text("SELECT COUNT(*) AS cnt FROM storyboard_characters WHERE storyboard_id = :sbid"),
        {"sbid": sb2["id"]},
    ).mappings().first()["cnt"]
    assert chars2_count == 0

    # 悬空道具倚天剑被 Gatekeeper 拦截，不插入 storyboard_props
    props2_count = db.execute(
        text("SELECT COUNT(*) AS cnt FROM storyboard_props WHERE storyboard_id = :sbid"),
        {"sbid": sb2["id"]},
    ).mappings().first()["cnt"]
    assert props2_count == 0


def test_framing_driven_dual_state_routing_and_prop_alias_closed_loop(memory_db):
    """断言6：阶段7景别驱动双态路由（WIDE=ambient vs CU=foreground）与物证别名全链路闭环。"""
    db = memory_db
    now = now_iso()

    # 1. 初始化剧目与单集
    db.execute(
        text("INSERT INTO dramas (id, title, status, created_at, updated_at) VALUES (8, '豪门悬疑剧', 'draft', :now, :now)"),
        {"now": now},
    )
    db.execute(
        text("INSERT INTO episodes (id, drama_id, episode_number, title, status, created_at, updated_at) VALUES (282, 8, 1, '第1集：遗嘱迷局', 'draft', :now, :now)"),
        {"now": now},
    )
    db.commit()

    # 2. 阶段6持久化：场景（灵堂）
    persist_stage6_scenes(
        db=db,
        drama_id=8,
        curr_ep=1,
        episode_id=282,
        now=now,
        environments_manifest=[
            {
                "scene_name": "苏宅阴森灵堂",
                "location": "苏宅阴森灵堂",
                "time_lighting": "雷雨深夜，冷白闪电交织残烛微光",
                "spatial_topology": "中轴对称挑高灵堂，中央实木灵柩，两侧白幔垂落",
                "optical_lighting": "顶光幽暗，雷电高频冷调侧光频闪",
                "weathering_patina": "灵台积灰，贡果萎缩腐烂，纸钱灰烬遍地",
                "micro_climate": "穿堂冷风裹挟线香青烟，空气阴冷窒息",
                "zones": [],
            }
        ],
        newly_discovered_scenes=[],
        newly_generated_assets=[],
        state=None,
    )

    # 阶段6持久化：物证道具（苏秀兰遗像、带血的牛皮纸信封）
    persist_stage6_props(
        db=db,
        drama_id=8,
        curr_ep=1,
        episode_id=282,
        now=now,
        props_manifest=[
            {
                "prop_name": "苏秀兰遗像",
                "category": "prop",
                "narrative_category": "portrait_in_scene",
                "is_accessory_promoted": False,
                "material_specs": "黑木相框、黑白遗照、白菊缎带",
                "craft_texture": "老旧黑檀木框，表面有轻微划痕，玻璃反光冷冽",
                "damage_states": [
                    {"state_code": "S0_PRISTINE", "state_label": "端正陈列", "description": "遗像完好陈列于灵台中央"},
                    {"state_code": "S1_FALLEN", "state_label": "跌落破碎", "description": "相框玻璃碎裂，遗照染灰"},
                ],
            },
            {
                "prop_name": "带血的牛皮纸信封",
                "category": "prop",
                "narrative_category": "key_narrative_clue",
                "is_accessory_promoted": False,
                "material_specs": "复古粗糙牛皮纸、暗红血迹、黑色火漆封印",
                "craft_texture": "牛皮纸边缘毛糙泛黄，右下角有飞溅状暗红干涸血迹",
                "damage_states": [
                    {"state_code": "S0_SEALED", "state_label": "密封完好", "description": "火漆封口完整无缺"},
                    {"state_code": "S1_TORN", "state_label": "撕开破损", "description": "封口被粗暴撕开，露出染血信纸角"},
                ],
            },
        ],
        newly_discovered_props=[],
        newly_generated_assets=[],
        state=None,
    )
    db.commit()

    scene_row = db.execute(text("SELECT id FROM scenes WHERE drama_id = 8 AND location = '苏宅阴森灵堂'")).mappings().first()
    assert scene_row is not None
    scene_id = scene_row["id"]

    prop_yixiang = db.execute(text("SELECT id FROM props WHERE drama_id = 8 AND name = '苏秀兰遗像'")).mappings().first()
    assert prop_yixiang is not None
    yixiang_id = prop_yixiang["id"]

    prop_xinfeng = db.execute(text("SELECT id FROM props WHERE drama_id = 8 AND name = '带血的牛皮纸信封'")).mappings().first()
    assert prop_xinfeng is not None
    xinfeng_id = prop_xinfeng["id"]

    # 3. 构造阶段7分镜：
    # 镜头1：远景/建立镜头（ESTABLISH SHOT）
    # 动作中只写了“遗照”（同义别名匹配），未特写道具，应为 ambient 交互角色
    # 镜头2：特写镜头（CLOSE_UP）
    # 剧本动作“撕开信封”（动作带撕开战损 + 简写“信封”匹配），应为 foreground 交互角色
    # 镜头3：极特写（ECU / MACRO）
    # 剧本动作“极特写遗像相框的划痕”，应为 foreground 交互角色
    storyboards_payload = [
        {
            "storyboard_number": 1,
            "title": "灵堂全貌空间建立",
            "shot_type": "远景",
            "movement": "升降镜头",
            "duration": 4.0,
            "scene_ref": "苏宅阴森灵堂",
            "action": "全景建立镜头：阴森灵堂中央肃立，白幔随狂风乱舞，灵台正中摆放着肃穆的遗照与供品。",
            "dialogue": "",
            "characters": [],
            "props": ["苏秀兰遗像"],
        },
        {
            "storyboard_number": 2,
            "title": "拆封血色遗嘱",
            "shot_type": "特写",
            "movement": "推镜头",
            "duration": 3.0,
            "scene_ref": "苏宅阴森灵堂",
            "action": "特写：颤抖的手粗暴撕开牛皮纸信封的封口，封口处血迹清晰可见。",
            "dialogue": "",
            "characters": [],
            "props": ["带血的牛皮纸信封"],
        },
        {
            "storyboard_number": 3,
            "title": "遗像暗记微距切片",
            "shot_type": "极特写",
            "movement": "静止",
            "duration": 2.5,
            "scene_ref": "苏宅阴森灵堂",
            "action": "微距极特写：遗像黑色相框右侧边缘，有一道暗藏的锐器刮痕。",
            "dialogue": "",
            "characters": [],
            "props": ["遗像"],  # 别名简写传入
        },
    ]

    # 执行阶段7入库
    result = save_storyboard_data_direct(
        db=db,
        drama_id=8,
        episode_id=282,
        storyboard_data=storyboards_payload,
    )
    db.commit()

    assert result["storyboards"] == 3

    # 4. 验证镜头1（建立镜头）：
    sb1 = db.execute(text("SELECT * FROM storyboards WHERE episode_id = 282 AND storyboard_number = 1")).mappings().first()
    assert sb1["scene_id"] == scene_id
    p1 = db.execute(text("SELECT * FROM storyboard_props WHERE storyboard_id = :sid"), {"sid": sb1["id"]}).mappings().first()
    assert p1 is not None
    assert p1["prop_id"] == yixiang_id
    # 远景建立镜头下，道具属于背景陈设（ambient）
    assert p1["interaction_role"] == "ambient"

    # 5. 验证镜头2（特写镜头+战损识别）：
    sb2 = db.execute(text("SELECT * FROM storyboards WHERE episode_id = 282 AND storyboard_number = 2")).mappings().first()
    assert sb2["scene_id"] == scene_id
    p2 = db.execute(text("SELECT * FROM storyboard_props WHERE storyboard_id = :sid"), {"sid": sb2["id"]}).mappings().first()
    assert p2 is not None
    assert p2["prop_id"] == xinfeng_id
    # 特写镜头下，物证为视觉焦点（foreground）
    assert p2["interaction_role"] == "foreground"
    # 动宾动作中包含“撕开”，正确定位到 S1_TORN 战损形态！
    damage2 = db.execute(text("SELECT state_code FROM prop_damage_states WHERE id = :did"), {"did": p2["damage_state_id"]}).mappings().first()
    assert damage2 is not None
    assert damage2["state_code"] == "S1_TORN"

    # 6. 验证镜头3（极特写+别名精准回溯）：
    sb3 = db.execute(text("SELECT * FROM storyboards WHERE episode_id = 282 AND storyboard_number = 3")).mappings().first()
    p3 = db.execute(text("SELECT * FROM storyboard_props WHERE storyboard_id = :sid"), {"sid": sb3["id"]}).mappings().first()
    assert p3 is not None
    # 即使分镜 props 中只写了“遗像”，仍通过别名表精准关联到“苏秀兰遗像”
    assert p3["prop_id"] == yixiang_id
    # 极特写镜头下，物证为视觉焦点（foreground）
    assert p3["interaction_role"] == "foreground"

