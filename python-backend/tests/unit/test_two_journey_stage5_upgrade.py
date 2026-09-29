"""测试两程九阶 Stage 5 文学剧本工笔生成与疾速波次连续吞吐升级 (Stage 5 Upgrade Tests)。

验证内容：
1. 阶段 5 十大时空总线契约与双向数据模型规范 (Pydantic v2 & TypedDict)：
   - GoldenCliffhangerHookModel 支持 physical_crisis_action / cliffhanger_dialogue / acoustic_drop_cue 与 hook_action / hook_dialogue / hook_audio_braam 双向同步映射；
   - EpisodeEndPhysicalDeltaModel 支持 timeline_progress / character_pose / held_props_and_injuries / environment_and_weather 与 timeline_progress_sec / posture_and_injuries / carried_props_status / weather_and_light 双向同步映射；
   - PreviousEpisodePickupModel 支持 inherited_from_episode / pickup_state_description 与 freeze_frame_desc 映射；
   - LiteraryScreenplayEpisodeModel 支持字典式下标访问、.get()、to_dict() 以及模型属性访问；
   - IndustrialDramaState 与 IndustrialDramaMasterState 原生纳管 completed_screenplays。
2. Stage 5 保底工厂 (_stage5_fallback_episode) 契约完备性：
   - 包含 2~4 个标准时空场景标头 (【场景 01】外景... / 【场景 02】内景...)；
   - 包含三大声学行为标记 (开场突发重击 Braam Hit / 核心戏剧骤停绝对物理静音 2.5 秒 / 终局下潜重击 Sub-drop 随黑屏骤停)；
   - 包含前 3 秒特写抓手 (hook_3s)；
   - 包含三位一体黄金悬念绝杀钩子 (golden_cliffhanger_hook)；
   - 包含四维全息集尾物理快照 (episode_end_physical_delta)；
   - 第 2 集及之后严格包含接力上一集的 0 秒物理快照 (previous_episode_0s_pickup)；
   - 输出完整的红蓝自审报告 audit_report。
3. Stage 5 单集生成与 AST 分块 (generate_single_episode) 归一化与容错：
   - 当模型输出缺失三大声学行为标记或场景标头不足时，自动插值补齐规范格式；
   - 自动调用 ScriptASTParser 解析生成标准 AST 树；
   - 物理咬合引擎正确继承上一集终态并在第 2 集以上生成 0 秒动作承接。
4. Stage 5 业务节点 (stage5_screenplay_node) 波次连续吞吐 (Mini-Arc Batching)：
   - 遵循单波次 3 集微弧吞吐节奏，跨集连续传递 inter_episode_physical_snapshot；
   - 正确计算 current_mini_arc_index；
   - 全季集数生成完毕时锁定第一程 (literary_journey_locked = True)。
5. RedBlueAuditor 哨卡 5 (Checkpoint 5) 严苛质检能力：
   - 完备数据 (含标准契约与双向别名) 评级为 GREEN_APPROVED；
   - 场景标头不足 2 处或超过 4 处时精准拦截 RED_BLOCKING；
   - 缺失三大声学行为标记之一时精准拦截 RED_BLOCKING；
   - 缺失前 3 秒钩子、缺失黄金绝杀断点、缺失四维物理快照时精准拦截 RED_BLOCKING；
   - 第 2 集以上缺失 0 秒接力物理快照时精准拦截 RED_BLOCKING。
6. 存储适配器 (drama_storage_adapter) 零破坏落库与双向反序列化还原：
   - persist_stage5 安全写入 episodes 表、AST 块、剧本文学长期记忆；
   - load_master_state_from_db 完整反序列化还原 completed_screenplays 为规范双向契约结构。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import (
    AuditVerdict,
    EpisodeEndPhysicalDeltaModel,
    GoldenCliffhangerHookModel,
    IndustrialDramaMasterState,
    IndustrialDramaState,
    LiteraryScreenplayEpisodeModel,
    PreviousEpisodePickupModel,
)
from app.workflows.adapters.drama_storage_adapter import (
    load_master_state_from_db,
    persist_stage5,
)
from app.workflows.nodes.stage5_screenplay import (
    _stage5_fallback_episode,
    generate_single_episode,
    stage5_screenplay_node,
)


# =========================================================================
# 1. 契约模型与双向映射测试
# =========================================================================

def test_golden_cliffhanger_hook_bidirectional_model():
    """测试 GoldenCliffhangerHookModel 双向字段映射与别名属性。"""
    # 1.1 标准契约字段初始化
    hook1 = GoldenCliffhangerHookModel(
        physical_crisis_action="沈炼将手术刀抵紧赵崇山颈动脉",
        cliffhanger_dialogue="沈炼：开枪啊！",
        acoustic_drop_cue="[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！",
    )
    assert hook1.physical_crisis_action == "沈炼将手术刀抵紧赵崇山颈动脉"
    assert hook1.hook_action == "沈炼将手术刀抵紧赵崇山颈动脉"
    assert hook1.cliffhanger_dialogue == "沈炼：开枪啊！"
    assert hook1.hook_dialogue == "沈炼：开枪啊！"
    assert hook1.acoustic_drop_cue == "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"
    assert hook1.hook_audio_braam == "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"

    # 1.2 传统别名字段初始化
    hook2 = GoldenCliffhangerHookModel(
        hook_action="赵崇山按动自毁倒计时",
        hook_dialogue="赵崇山：一起下地狱吧！",
        hook_audio_braam="低音重击下潜",
    )
    assert hook2.physical_crisis_action == "赵崇山按动自毁倒计时"
    assert hook2.hook_action == "赵崇山按动自毁倒计时"
    assert hook2.cliffhanger_dialogue == "赵崇山：一起下地狱吧！"
    assert hook2.acoustic_drop_cue == "低音重击下潜"

    # 1.3 字典式访问验证
    assert hook2["physical_crisis_action"] == "赵崇山按动自毁倒计时"
    assert hook2.get("hook_action") == "赵崇山按动自毁倒计时"
    d2 = hook2.to_dict()
    assert d2["physical_crisis_action"] == "赵崇山按动自毁倒计时"
    assert d2["hook_action"] == "赵崇山按动自毁倒计时"


def test_episode_end_physical_delta_bidirectional_model():
    """测试 EpisodeEndPhysicalDeltaModel 四维全息字段与传统别名双向映射。"""
    # 2.1 标准契约初始化
    delta1 = EpisodeEndPhysicalDeltaModel(
        timeline_progress="故事主线第2天清晨06:30",
        character_pose="林晚右手持刀半跪，周衍贴墙僵立",
        held_props_and_injuries="生锈手术刀沾血，右手指缝渗血",
        environment_and_weather="货运车站扳道室，暴雨狂风窗玻璃碎裂",
    )
    assert delta1.timeline_progress == "故事主线第2天清晨06:30"
    assert delta1.posture_and_injuries == "林晚右手持刀半跪，周衍贴墙僵立"
    assert delta1.carried_props_status == "生锈手术刀沾血，右手指缝渗血"
    assert delta1.weather_and_light == "货运车站扳道室，暴雨狂风窗玻璃碎裂"

    # 2.2 传统别名初始化
    delta2 = EpisodeEndPhysicalDeltaModel(
        timeline_progress_sec=120.0,
        posture_and_injuries="沈炼贴墙站立",
        carried_props_status="U盘装入内袋",
        weather_and_light="地下暗室昏暗潮湿",
    )
    assert "120" in delta2.timeline_progress
    assert delta2.character_pose == "沈炼贴墙站立"
    assert delta2.held_props_and_injuries == "U盘装入内袋"
    assert delta2.environment_and_weather == "地下暗室昏暗潮湿"


def test_previous_episode_pickup_bidirectional_model():
    """测试 PreviousEpisodePickupModel 0秒接棒快照映射。"""
    pickup = PreviousEpisodePickupModel(
        inherited_from_episode=1,
        pickup_state_description="承接第1集终态，沈炼手握手术刀从泥水中缓缓撑起身躯",
    )
    assert pickup.inherited_from_episode == 1
    assert pickup.pickup_state_description == "承接第1集终态，沈炼手握手术刀从泥水中缓缓撑起身躯"
    assert pickup.freeze_frame_desc == "承接第1集终态，沈炼手握手术刀从泥水中缓缓撑起身躯"
    assert pickup.episode_index == 1
    assert pickup["inherited_from_episode"] == 1


def test_literary_screenplay_episode_model():
    """测试 LiteraryScreenplayEpisodeModel 全文模型封装与访问方式。"""
    raw = {
        "episode_id": 1,
        "episode_num": 1,
        "episode_title": "第01集：雨夜破局",
        "planned_duration_sec": 120.0,
        "screenplay_text": "【场景 01】外景. 车站 - 晨\n正文描写\n【场景 02】内景. 扳道室 - 晨\n对白交锋",
        "hook_3s": "开场特写动作",
        "ending_cliffhanger": "片尾定格绝杀",
        "golden_cliffhanger_hook": {
            "physical_crisis_action": "刀抵颈动脉",
            "cliffhanger_dialogue": "开枪啊！",
            "acoustic_drop_cue": "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！",
        },
        "episode_end_physical_delta": {
            "timeline_progress": "第1天晨",
            "character_pose": "持刀对峙",
            "held_props_and_injuries": "刀口滴血",
            "environment_and_weather": "暴雨倾盆",
        },
    }
    ep = LiteraryScreenplayEpisodeModel.model_validate(raw)
    assert ep.episode_num == 1
    assert ep.title == "第01集：雨夜破局"
    assert ep.body_markdown == ep.screenplay_text
    assert ep["screenplay_text"] == raw["screenplay_text"]
    assert ep.get("episode_title") == "第01集：雨夜破局"
    assert "screenplay_text" in ep
    assert ep.golden_cliffhanger_hook.hook_action == "刀抵颈动脉"
    assert ep.episode_end_physical_delta.character_pose == "持刀对峙"

    # to_dict 必须包含两大主流命名系统字段
    d = ep.to_dict()
    assert d["screenplay_text"] == d["body_markdown"]
    assert d["episode_title"] == d["title"]
    assert d["golden_cliffhanger_hook"]["physical_crisis_action"] == "刀抵颈动脉"
    assert d["golden_cliffhanger_hook"]["hook_action"] == "刀抵颈动脉"


# =========================================================================
# 2. 保底工厂 (_stage5_fallback_episode) 完备性验证
# =========================================================================

def test_stage5_fallback_episode_conformance():
    """测试保底工厂生成剧本的标准契约完整性（场景数、三大声学行为标记、0秒承接与双向钩子）。"""
    characters = [
        {"name": "林晚", "voice_fingerprint": {"stress_action": "掐入食指指甲缝"}, "carried_anchor_item": {"item_name": "钥匙"}},
        {"name": "周衍", "voice_fingerprint": {"stress_action": "转动打火机"}},
    ]
    environments = [{"location_name": "老火车站废弃站台"}]
    props = [{"name": "生锈手术刀与带血日记"}]
    outline_ep1 = {"title": "第01集：破局交锋", "core_dramatic_task": "突围取证"}
    outline_ep2 = {"title": "第02集：绝地反杀", "core_dramatic_task": "密室对峙"}

    # 2.1 第 1 集生成
    ep1 = _stage5_fallback_episode(1, outline_ep1, None, characters, environments, props)
    assert ep1["episode_num"] == 1
    assert ep1["previous_episode_0s_pickup"] is None

    # 验证场景标头 (2 ~ 4 个)
    scene_headers_ep1 = [line for line in ep1["screenplay_text"].splitlines() if any(tag in line for tag in ["【场景", "内景", "外景"])]
    assert 2 <= len(scene_headers_ep1) <= 4

    # 验证三大声学行为标记
    assert "[声学行为: 开场突发重击 Braam Hit]" in ep1["screenplay_text"]
    assert "[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]" in ep1["screenplay_text"]
    assert "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！" in ep1["screenplay_text"]

    # 验证三位一体黄金悬念绝杀钩子
    g_hook1 = ep1["golden_cliffhanger_hook"]
    assert g_hook1["physical_crisis_action"]
    assert g_hook1["cliffhanger_dialogue"]
    assert g_hook1["acoustic_drop_cue"]
    assert g_hook1["hook_action"] == g_hook1["physical_crisis_action"]

    # 验证四维物理快照
    delta1 = ep1["episode_end_physical_delta"]
    assert delta1["timeline_progress"]
    assert delta1["character_pose"]
    assert delta1["held_props_and_injuries"]
    assert delta1["environment_and_weather"]
    assert delta1["posture_and_injuries"] == delta1["character_pose"]

    # 2.2 第 2 集生成（传入第 1 集快照）
    ep2 = _stage5_fallback_episode(2, outline_ep2, delta1, characters, environments, props)
    assert ep2["episode_num"] == 2
    assert ep2["previous_episode_0s_pickup"] is not None
    assert ep2["previous_episode_0s_pickup"]["inherited_from_episode"] == 1
    assert ep2["previous_episode_0s_pickup"]["pickup_state_description"]

    # 红蓝自审报告
    assert ep1["audit_report"]["verdict"] == "GREEN_APPROVED"
    assert ep2["audit_report"]["verdict"] == "GREEN_APPROVED"


# =========================================================================
# 3. generate_single_episode 容错插值与 AST 解析
# =========================================================================

def test_generate_single_episode_acoustic_and_scene_auto_fix():
    """测试模型输出缺失场景标头或声学标记时，generate_single_episode 自动修复归一化。"""
    base_state = {
        "drama_id": 99999,
        "total_episodes": 3,
        "season_outlines": {
            1: {"title": "破晓", "core_dramatic_task": "生死脱困", "hook_3s": "泥水特写", "killer_cliffhanger_115s": "刀锋抵喉"},
            2: {"title": "对峙", "core_dramatic_task": "查明真相", "hook_3s": "扳道室撞门", "killer_cliffhanger_115s": "红外锁胸"},
        },
        "characters_engine": {"characters": [{"name": "林晚"}, {"name": "周衍"}]},
        "environments_and_props": {"environments": [{"location_name": "货运车站"}], "props": [{"name": "手术刀"}]},
        "negative_rules": {"forbidden_plot_devices": ["机械降神"]},
    }

    # 执行单集生成（在离线或无真实 LLM 时触发降级自愈并进行后处理归一化）
    res1 = generate_single_episode(base_state, 1)
    script1 = res1["script"]
    snapshot1 = res1["outgoing_snapshot"]

    assert script1["episode_num"] == 1
    assert script1["ast_data"] is not None
    assert "blocks" in script1["ast_data"]
    assert "beats" in script1["ast_data"]
    assert len(script1["ast_data"]["beats"]) > 0

    # 验证视听原子小节的数据结构完整性
    first_beat = script1["ast_data"]["beats"][0]
    assert "beat_id" in first_beat
    assert "beat_type" in first_beat
    assert "estimated_duration_sec" in first_beat

    # 验证三大声学行为标记完整
    assert any(k in script1["screenplay_text"] for k in ["开场突发重击", "Braam Hit"])
    assert any(k in script1["screenplay_text"] for k in ["核心戏剧骤停", "物理静音"])
    assert any(k in script1["screenplay_text"] for k in ["终局下潜重击", "Sub-drop"])

    # 生成第 2 集，验证 0 秒物理接力
    res2 = generate_single_episode(base_state, 2, incoming_snapshot=snapshot1)
    script2 = res2["script"]
    assert script2["episode_num"] == 2
    assert script2["previous_episode_0s_pickup"] is not None
    assert script2["previous_episode_0s_pickup"]["inherited_from_episode"] == 1


def test_stage5_linter_and_audiovisual_beats():
    """测试 Stage 5 确定性 Linter 规范化、多行台词熔接、微动作发声阻力注入与工笔原子小节生成。"""
    from app.agents.script_ast_parser import ScriptASTParser
    from app.workflows.nodes.stage5_screenplay import _lint_and_autofix_screenplay_text

    raw_bad_screenplay = """【场景 01】外景. 铁轨外围 - 晨 - 暴雨
林晚心里暗自盘算着这一切究竟是谁布下的局，她感到一阵绝望。
林晚
（右手死死掐进掌心）
你休想从我手里拿走它，这是我母亲留给我唯一的遗物，也是你当年犯罪的铁证！
周衍：把东西交出来。
周衍猛烈夺取【生锈手术刀】，金属表面瞬间被撕扯出一道深深的裂纹。
【场景 02】内景. 扳道房 - 晨 - 昏暗
林晚反手将手术刀死死抵在周衍咽喉，鲜血顺着刀尖滑落。"""

    chars = [
        {"name": "林晚", "voice_fingerprint": {"stress_action": "下颌骨咬紧", "vocal_delivery": "声线压低至沙哑"}},
        {"name": "周衍", "voice_fingerprint": {"stress_action": "转动打火机", "vocal_delivery": "语气极平极冷"}},
    ]
    props = [{"name": "生锈手术刀", "level": "hero"}]

    # 执行 Linter 自动纠偏
    fixed_text = _lint_and_autofix_screenplay_text(raw_bad_screenplay, chars, props, episode_num=1)

    # 1. 心理描写必须被彻底置换为动作
    assert "暗自盘算" not in fixed_text
    assert "感到一阵绝望" not in fixed_text
    assert "下意识屏住呼吸" in fixed_text or "眼神" in fixed_text

    # 2. 多行台词必须被熔接为单行，且超长台词被自动拆分为 <= 22 字符的原子对白行
    assert "林晚\n（右手死死掐进掌心）" not in fixed_text
    assert "林晚（右手死死掐进掌心" in fixed_text

    # 3. 缺失括号的周衍对白必须被自动注入应激与发声阻力
    assert "周衍（转动打火机，语气极平极冷）：把东西交出来。" in fixed_text

    # 4. 动作行必须规范携带 △ 前缀
    for line in fixed_text.splitlines():
        if line.startswith("【场景") or line.startswith("[声学行为") or not line.strip():
            continue
        if "：" in line:
            assert "（" in line and "）" in line, f"台词格式不符合规范: {line}"
        else:
            assert line.startswith("△ "), f"动作行未携带 △ 前缀: {line}"

    # 5. 三大声学标签必须自动补齐
    assert "开场突发重击 Braam Hit" in fixed_text
    assert "核心戏剧骤停，进入主观绝对物理静音 2.5 秒" in fixed_text
    assert "终局下潜重击 Sub-drop 随黑屏骤停" in fixed_text

    # 6. AST 解析生成高精度视听原子小节 (AudioVisualBeat)
    ast_tree = ScriptASTParser.parse(1, f"### 开场特写\n爆点\n\n### 视听正文\n{fixed_text}\n\n### 片尾定格\n生死绝杀")
    beats = ast_tree.beats
    assert len(beats) >= 4, f"解析出的视听小节数过少: {len(beats)}"

    dlg_beats = [b for b in beats if b.beat_type == "dialogue"]
    act_beats = [b for b in beats if b.beat_type == "action"]

    assert len(dlg_beats) >= 2
    assert len(act_beats) >= 2

    # 验证对白小节提取了应激微动作与发声腔体
    assert any(b.speaker == "林晚" and b.stress_action for b in dlg_beats)
    assert any(b.speaker == "周衍" and b.vocal_delivery for b in dlg_beats)

    # 验证动作小节提取了道具与拟音
    prop_beats = [b for b in beats if b.interacted_prop]
    assert len(prop_beats) > 0, "应成功提取出与生锈手术刀交互的小节"
    assert "生锈手术刀" in prop_beats[0].interacted_prop

    # 验证时长符合短剧语速律动 (每秒 3.5~4.2 字，最小动作时长保护)
    for b in beats:
        assert b.estimated_duration_sec >= 1.0
        assert b.estimated_duration_sec <= 8.0


# =========================================================================
# 4. stage5_screenplay_node 节点波次吞吐 (Mini-Arc)
# =========================================================================

def test_stage5_screenplay_node_mini_arc_throughput():
    """测试 Stage 5 节点按照每波次 3 集进行 Mini-Arc 推进与第一程锁定。"""
    state = IndustrialDramaState(
        drama_id=888,
        total_episodes=4,
        target_episodes=4,
        season_outlines={
            1: {"title": "第1集"},
            2: {"title": "第2集"},
            3: {"title": "第3集"},
            4: {"title": "第4集"},
        },
        characters_engine={"characters": [{"name": "主角"}, {"name": "反派"}]},
        environments_and_props={"environments": [{"location_name": "老洋房"}], "props": [{"name": "日记本"}]},
    )

    # 第一波次：生成第 1~3 集
    out1 = stage5_screenplay_node(state)
    assert out1["current_stage"] == 5
    assert len(out1["completed_screenplays"]) == 3
    assert out1["current_mini_arc_index"] == 1
    assert out1["literary_journey_locked"] is False
    assert out1["inter_episode_physical_snapshot"] is not None

    # 更新状态并执行第二波次：生成第 4 集（全季收官）
    state["completed_screenplays"] = out1["completed_screenplays"]
    state["inter_episode_physical_snapshot"] = out1["inter_episode_physical_snapshot"]

    out2 = stage5_screenplay_node(state)
    assert len(out2["completed_screenplays"]) == 4
    assert out2["current_mini_arc_index"] == 2
    assert out2["literary_journey_locked"] is True


# =========================================================================
# 5. RedBlueAuditor 哨卡 5 (Checkpoint 5) 严苛质检验证
# =========================================================================

def test_stage5_auditor_checkpoint_comprehensive():
    """测试哨卡 5 针对时空标头、三大声学行为标记、四维物理快照与 0 秒接棒的审查。"""
    # 5.1 完备剧本 ➔ GREEN_APPROVED
    valid_ep1 = {
        "episode_id": 1,
        "episode_num": 1,
        "title": "破晓突围",
        "hook_3s": "开场特写：泥水顺着黑风衣下摆滴落",
        "screenplay_text": """【场景 01】外景. 车站货运道 - 晨 - 暴雨
[声学行为: 开场突发重击 Braam Hit]
林晚抹了一把脸上的冰雨。

周衍
（冷笑一声）
东西交出来。

【场景 02】内景. 扳道室 - 晨 - 昏暗
[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]
两名黑衣保镖瞬间从门后包抄。

【动作】林晚猛地后撤撞翻铁架，手术刀死死架在周衍颈侧！
[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！""",
        "golden_cliffhanger_hook": {
            "physical_crisis_action": "手术刀死死架在周衍颈侧",
            "cliffhanger_dialogue": "林晚：开枪啊！",
            "acoustic_drop_cue": "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！",
        },
        "episode_end_physical_delta": {
            "timeline_progress": "故事第1天晨06:30",
            "character_pose": "林晚持刀抵紧周衍喉结",
            "held_props_and_injuries": "手术刀带血",
            "environment_and_weather": "扳道室碎玻璃漏风漏雨",
        },
    }
    report1 = RedBlueAuditor.audit_stage5({1: valid_ep1})
    assert report1.verdict == AuditVerdict.GREEN_APPROVED
    assert len(report1.blocking_issues) == 0

    # 5.2 缺失声学行为标记 ➔ RED_BLOCKING
    bad_acoustic_ep = dict(valid_ep1)
    bad_acoustic_ep["screenplay_text"] = """【场景 01】外景. 车站 - 晨
林晚走到站台。
【场景 02】内景. 扳道室 - 晨
周衍跟了上来。"""
    report_bad_acoustic = RedBlueAuditor.audit_stage5({1: bad_acoustic_ep})
    assert report_bad_acoustic.verdict == AuditVerdict.RED_BLOCKING
    assert any("三大声学行为标记" in issue for issue in report_bad_acoustic.blocking_issues)

    # 5.3 场景标头超过 4 处 ➔ RED_BLOCKING
    too_many_scenes_ep = dict(valid_ep1)
    too_many_scenes_ep["screenplay_text"] = """【场景 01】外景. 车站 - 晨
[声学行为: 开场突发重击 Braam Hit]
【场景 02】内景. 走廊 - 晨
[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]
【场景 03】内景. 房间 - 晨
【场景 04】外景. 院子 - 晨
【场景 05】外景. 大道 - 晨
[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"""
    report_too_many_scenes = RedBlueAuditor.audit_stage5({1: too_many_scenes_ep})
    assert report_too_many_scenes.verdict == AuditVerdict.RED_BLOCKING
    assert any("超过 4 处" in issue for issue in report_too_many_scenes.blocking_issues)

    # 5.4 黄金绝杀断点缺失物理动作 ➔ RED_BLOCKING
    bad_hook_ep = dict(valid_ep1)
    bad_hook_ep["golden_cliffhanger_hook"] = {
        "physical_crisis_action": "",
        "cliffhanger_dialogue": "开枪啊",
        "acoustic_drop_cue": "低音重击",
    }
    report_bad_hook = RedBlueAuditor.audit_stage5({1: bad_hook_ep})
    assert report_bad_hook.verdict == AuditVerdict.RED_BLOCKING
    assert any("物理危机动作" in issue for issue in report_bad_hook.blocking_issues)

    # 5.5 四维物理快照缺失空间与天气 ➔ RED_BLOCKING
    bad_delta_ep = dict(valid_ep1)
    bad_delta_ep["episode_end_physical_delta"] = {
        "timeline_progress": "故事第1天晨",
        "character_pose": "持刀对峙",
        "held_props_and_injuries": "手术刀带血",
        "environment_and_weather": "",
    }
    report_bad_delta = RedBlueAuditor.audit_stage5({1: bad_delta_ep})
    assert report_bad_delta.verdict == AuditVerdict.RED_BLOCKING
    assert any("空间与天气光影状态" in issue for issue in report_bad_delta.blocking_issues)

    # 5.6 第 2 集缺失 0 秒物理接力快照 ➔ RED_BLOCKING
    bad_pickup_ep2 = dict(valid_ep1)
    bad_pickup_ep2["episode_num"] = 2
    bad_pickup_ep2["episode_id"] = 2
    bad_pickup_ep2["previous_episode_0s_pickup"] = None
    report_bad_pickup = RedBlueAuditor.audit_stage5({2: bad_pickup_ep2})
    assert report_bad_pickup.verdict == AuditVerdict.RED_BLOCKING
    assert any("previous_episode_0s_pickup" in issue for issue in report_bad_pickup.blocking_issues)


# =========================================================================
# 6. Stage 5 动态画幅比例 (aspect_ratio) 适配验证
# =========================================================================

def test_stage5_dynamic_aspect_ratio_support():
    """测试 Stage 5 提示词与单集生成能够根据前端传入的 aspect_ratio 动态自适应，不强行限定竖屏。"""
    from app.workflows.prompts.master_sop_prompts import STAGE5_SYSTEM_PROMPT, STAGE5_USER_PROMPT_TEMPLATE

    # 1. 验证系统提示词中不再写死"竖屏短剧"限制
    assert "竖屏短剧（90~120秒）" not in STAGE5_SYSTEM_PROMPT
    assert "aspect_ratio" in STAGE5_SYSTEM_PROMPT
    assert "9:16" in STAGE5_SYSTEM_PROMPT and "16:9" in STAGE5_SYSTEM_PROMPT

    # 2. 验证用户提示词模板包含 aspect_ratio 与 aspect_ratio_guidance 槽位
    assert "{aspect_ratio}" in STAGE5_USER_PROMPT_TEMPLATE
    assert "{aspect_ratio_guidance}" in STAGE5_USER_PROMPT_TEMPLATE

    # 3. 验证横屏 (16:9) 状态生成
    horizontal_state = {
        "drama_id": 10001,
        "aspect_ratio": "16:9",
        "total_episodes": 2,
        "season_outlines": {
            1: {"title": "横屏首集", "hook_3s": "宽屏对峙", "killer_cliffhanger_115s": "绝命拔枪"},
        },
        "characters_engine": {"characters": [{"name": "陆沉"}, {"name": "秦锋"}]},
        "environments_and_props": {"environments": [{"location_name": "滨海码头"}], "props": [{"name": "引信密码"}]},
    }
    res_horiz = generate_single_episode(horizontal_state, 1)
    script_horiz = res_horiz["script"]
    assert script_horiz["aspect_ratio"] == "16:9"

    # 4. 验证从 metadata 解析画幅比例
    meta_state = {
        "drama_id": 10002,
        "metadata": json.dumps({"aspect_ratio": "16:9"}),
        "total_episodes": 1,
        "season_outlines": {
            1: {"title": "元数据首集", "hook_3s": "暗夜潜行", "killer_cliffhanger_115s": "引爆倒计时"},
        },
        "characters_engine": {"characters": [{"name": "陆沉"}]},
        "environments_and_props": {"environments": [{"location_name": "指挥中心"}], "props": [{"name": "终端芯片"}]},
    }
    res_meta = generate_single_episode(meta_state, 1)
    assert res_meta["script"]["aspect_ratio"] == "16:9"

    # 5. 验证默认兜底画幅 (9:16)
    default_state = {
        "drama_id": 10003,
        "total_episodes": 1,
        "season_outlines": {
            1: {"title": "默认首集", "hook_3s": "暴雨回眸", "killer_cliffhanger_115s": "锁链断裂"},
        },
        "characters_engine": {"characters": [{"name": "林晚"}]},
    }
    res_def = generate_single_episode(default_state, 1)
    assert res_def["script"]["aspect_ratio"] == "9:16"


# =========================================================================
# 7. 存储持久化与反序列化还原验证
# =========================================================================

def test_stage5_storage_persistence_and_roundtrip():
    """测试 persist_stage5 落库与 load_master_state_from_db 反序列化无损还原。"""
    mock_db = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.execute = MagicMock()

    # 构造待落库 MasterState
    ep1_model = LiteraryScreenplayEpisodeModel(
        episode_num=1,
        title="第1集：雨夜刀锋",
        screenplay_text="【场景 01】外景. 车站 - 晨\n[声学行为: 开场突发重击 Braam Hit]\n正文\n【场景 02】内景. 扳道室 - 晨\n[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]\n对白\n[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！",
        hook_3s="雨夜特写",
        ending_cliffhanger="定格刀锋抵喉",
        golden_cliffhanger_hook=GoldenCliffhangerHookModel(
            physical_crisis_action="刀抵喉咙",
            cliffhanger_dialogue="开枪啊",
            acoustic_drop_cue="重击下潜",
        ),
        episode_end_physical_delta=EpisodeEndPhysicalDeltaModel(
            timeline_progress="第1天晨06:30",
            character_pose="半跪持刀",
            held_props_and_injuries="手术刀染血",
            environment_and_weather="站台暴雨",
        ),
    )

    state = IndustrialDramaMasterState(
        drama_id=777,
        total_episodes=1,
        target_episodes=1,
        target_duration_sec=120,
        completed_screenplays={1: ep1_model.to_dict()},
        literary_journey_locked=True,
    )

    # 模拟 fetch_one 查询 existing_ep 为 None，查询 dramas 为 mock metadata
    from unittest.mock import patch

    with patch("app.workflows.adapters.drama_storage_adapter.fetch_one") as mock_fetch_one, \
         patch("app.workflows.adapters.drama_storage_adapter.sync_stage_memories_to_vector_db") as mock_sync_mem, \
         patch("app.workflows.adapters.drama_storage_adapter.set_short_memories") as mock_set_mem:
        
        mock_fetch_one.side_effect = [
            None,  # episodes 查询
            {"metadata": "{}"},  # dramas 查询
        ]

        persist_stage5(mock_db, drama_id=777, state=state)

        # 验证数据库执行了 INSERT INTO episodes
        assert mock_db.execute.called
        assert mock_db.commit.called
        assert mock_sync_mem.called

    # 模拟 load_master_state_from_db 反序列化
    mock_ep_row = {
        "id": 101,
        "episode_number": 1,
        "title": "第1集：雨夜刀锋",
        "description": "大纲描述",
        "hook_cliffhanger": "{}",
        "script_content": json.dumps(ep1_model.to_dict(), ensure_ascii=False),
        "ast_blocks": "{}",
    }
    mock_drama_row = {
        "id": 777,
        "title": "测试短剧",
        "theme": "都市复仇",
        "target_episodes": 1,
        "duration_per_episode": 120,
        "status": "running",
        "lock_status": 1,
        "current_stage": 5,
        "metadata": json.dumps({"current_mini_arc_index": 1, "literary_journey_locked": True}),
        "prompt_overrides": "{}",
    }

    with patch("app.workflows.adapters.drama_storage_adapter.fetch_one", return_value=mock_drama_row), \
         patch("app.workflows.adapters.drama_storage_adapter.fetch_all") as mock_fetch_all, \
         patch("app.workflows.adapters.drama_storage_adapter.get_short_memories", return_value={}):
        
        def mock_fetch_all_handler(db, sql, params=None):
            if "FROM episodes" in sql:
                return [mock_ep_row]
            return []

        mock_fetch_all.side_effect = mock_fetch_all_handler

        loaded_state = load_master_state_from_db(mock_db, drama_id=777)
        assert loaded_state.drama_id == 777
        assert 1 in loaded_state.completed_screenplays
        loaded_ep = loaded_state.completed_screenplays[1]
        assert loaded_ep["title"] == "第1集：雨夜刀锋"
        assert loaded_ep["episode_title"] == "第1集：雨夜刀锋"
        assert loaded_ep["screenplay_text"] == loaded_ep["body_markdown"]
        assert loaded_ep["golden_cliffhanger_hook"]["physical_crisis_action"] == "刀抵喉咙"
        assert loaded_ep["golden_cliffhanger_hook"]["hook_action"] == "刀抵喉咙"
        assert loaded_ep["episode_end_physical_delta"]["timeline_progress"] == "第1天晨06:30"


# =========================================================================
# 7. 剧本视听节拍显式锚定、工程资产清洗与单主场原则验证
# =========================================================================

def test_stage5_beat_anchors_and_asset_cleaning():
    """测试阶段5 3秒抓手与45秒微反转显式锚定、工程资产清理与单主场场景保护。"""
    from app.agents.script_ast_parser import ScriptASTParser
    from app.workflows.nodes.stage5_screenplay import (
        _clean_engineering_asset_references,
        _lint_and_autofix_screenplay_text,
    )

    # 1. 验证工程资产引用清洗函数
    dirty_text = (
        "characters[CHAR_LUCHEN].visual_consistency_code 眼神凶狠，"
        "拔出 PROP_BLOODY_DIARY 摔在桌上。周衍在 ENV_ABANDONED_STATION 门外等待。"
    )
    cleaned = _clean_engineering_asset_references(
        dirty_text,
        characters=[{"name": "陆琛", "character_id": "CHAR_LUCHEN"}],
        props=[{"name": "带血日记", "prop_id": "PROP_BLOODY_DIARY"}],
        environments=[{"name": "废弃站台", "environment_id": "ENV_ABANDONED_STATION"}],
    )
    assert "characters[" not in cleaned
    assert "CHAR_LUCHEN" not in cleaned
    assert "PROP_BLOODY_DIARY" not in cleaned
    assert "ENV_ABANDONED_STATION" not in cleaned
    assert "陆琛" in cleaned
    assert "带血日记" in cleaned
    assert "废弃站台" in cleaned

    # 2. 验证 Linter 自动补齐显式打点与声学行为对齐
    raw_script = """【场景 01】外景. 车站货运道 - 晨 - 暴雨
△ 灰蒙蒙的雾气裹着刺鼻的煤焦油与柴油味。寒风呼啸。
△ 林晚抬手抹了一把脸上的冰雨，指尖触到额头渗血伤口。
周衍（缓步从阴影踱出，语气极冷）：东西交出来。这不是你能碰的局。
林晚（下颌咬紧，声音沙哑）：当年你带走遗物的时候，是不是也撑着这把黑伞？
△ 远处蒸汽机车发出一声沉闷刺耳的汽笛长鸣。
△ 周衍停住脚步，伞尖在水泥地面划出刺耳的尖音。
周衍（金丝眼镜后闪过致命戾气）：你真的以为能活着走出这里？
△ 林晚猛地后撤半步，左肩借力狠撞向生锈铁架！
△ 手术刀死死架在周衍颈侧动脉！
△ 四柄枪口瞬间红外激光交错锁死林晚胸膛！"""

    outline_mock = {
        "hook_3s": "泥水飞溅，林晚瞳孔骤缩",
        "micro_twist_45s": "周衍手下持枪包抄，封锁站台退路",
    }

    linted = _lint_and_autofix_screenplay_text(
        screenplay_text=raw_script,
        characters=[{"name": "林晚"}, {"name": "周衍"}],
        props=[{"name": "手术刀"}],
        episode_num=1,
        outline=outline_mock,
    )

    # 验证开局3秒抓手显式打点与 Braam Hit
    assert "△ 【开局3秒抓手】" in linted
    assert "[声学行为: 开场突发重击 Braam Hit]" in linted

    # 验证45秒微反转显式打点与绝对物理静音
    assert "△ 【45秒微反转】" in linted
    assert "[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]" in linted

    # 验证115秒片尾悬念打点与 Sub-drop
    assert "△ 【115秒片尾悬念】" in linted
    assert "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！" in linted

    # 验证单集单主场原则：原本只有【场景 01】，不会被人为硬塞【场景 02】
    scene_headers = [line for line in linted.splitlines() if line.startswith("【场景")]
    assert len(scene_headers) == 1

    # 3. 验证 ScriptASTParser 道具提取过滤
    ast_tree = ScriptASTParser.parse(
        episode_num=1,
        markdown_text=f"### 开场特写（前3秒）\n特写\n\n### 视听正文\n{linted}\n\n### 片尾定格与悬念钩子\n悬念",
    )
    # 验证打点标记和声学标记不会被误识别为道具
    extracted_props = [b.interacted_prop for b in ast_tree.beats if b.interacted_prop]
    all_extracted_props_str = "、".join(extracted_props)
    assert "开局3秒抓手" not in all_extracted_props_str
    assert "45秒微反转" not in all_extracted_props_str
    assert "115秒片尾悬念" not in all_extracted_props_str
    assert not any("声学行为" in p for p in extracted_props)
    assert not any("场景" in p for p in extracted_props)
    assert "手术刀" in all_extracted_props_str
