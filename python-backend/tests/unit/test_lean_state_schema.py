"""单元测试：验证 LeanDramaScriptState 瘦状态机体积与数据契约规范。"""
from __future__ import annotations

import json
from app.schemas.script_graph_state import (
    LeanDramaScriptState,
    ProjectProfile,
    HighConcept,
    WorldviewProfile,
    CharacterProfile,
    EpisodeOutlineItem,
    EpisodeScript,
    ScriptAST,
    ASTBlockItem,
    ClueItem,
    ContinuityMemo,
    QAReport,
)


def test_lean_drama_script_state_size_under_50kb():
    """测试包含 80 集大纲与历史索引的 Lean State 序列化体积必须 < 50KB。"""
    # 模拟一个 80 集的完备剧本状态
    state = LeanDramaScriptState(
        drama_id=101,
        version_cursor=1,
        lock_status=False,
        project=ProjectProfile(
            title="隐龙归渊",
            genre="都市爽剧",
            total_episodes=80,
            paywall_episodes=[10, 15, 20, 25],
        ),
        high_concept=HighConcept(
            one_sentence_hook="战神退隐回归都市，竟发现前妻为救自己背负百亿债务。",
            opening_3s_hook="开场一把染血匕首钉在离婚协议书正中央！",
            ultimate_question="当权力与真情对立，你会选择救赎还是复仇？",
        ),
        worldview=WorldviewProfile(
            core_main_scenes=["顾氏顶层总裁办", "云顶山庄私人会所", "城中村老旧修车厂"],
            rule_violation_cost="被四大隐世家族联合逐出江南商界并冻结全部资金",
        ),
    )

    # 填充 10 个角色
    for i in range(10):
        cname = f"角色_{i}"
        state.characters[cname] = CharacterProfile(
            name=cname,
            role_type="protagonist" if i == 0 else "antagonist" if i == 1 else "supporter",
            identity_and_mask=f"表面富商，隐藏身份隐龙殿主_{i}",
            visual_anchor="左眉一道断痕，身披黑色风衣",
            surface_desire="复仇打脸",
            deep_need="弥补三年前对妻子的亏欠",
        )

    # 填充 80 集分集大纲
    for ep in range(1, 81):
        state.episode_outlines[ep] = EpisodeOutlineItem(
            episode_num=ep,
            title=f"第{ep}集：龙魂震怒",
            commercial_tag="paywall_climax" if ep in [10, 15, 20, 25] else "regular",
            main_scene="日 内 顾氏总裁办",
            core_action="撕碎协议，亮明黑金龙卡",
            core_resistance="反派家族带保镖围堵",
            information_disclosure="得知当年车祸真相并非意外",
            ending_cliffhanger="△ 特写：反派跪倒在地，电话那头传来神秘人的声音！",
        )
        # 历史 80 集正文只存外部引用 ID
        state.persisted_episode_refs[ep] = 1000 + ep
        state.qa_summary_scores[ep] = 92

    # 活跃窗口仅保留当前批次 3 集正文
    for ep in (1, 2, 3):
        ast = ScriptAST(
            episode_num=ep,
            blocks=[
                ASTBlockItem(block_type="hook_3s", title="前3秒特写", content="△ 特写：带血手套扔在桌上"),
                ASTBlockItem(block_type="actions_and_scenes", title="核心动作", content="△ 顾沉舟逼近两步。"),
                ASTBlockItem(block_type="dialogues", title="对白", content="顾沉舟：你以为你逃得掉？"),
                ASTBlockItem(block_type="cliffhanger", title="片尾定格", content="【片尾定格】△ 门外黑影一闪！"),
            ],
            raw_markdown="### 第1集正文...",
        )
        state.active_window_episodes[ep] = EpisodeScript(
            episode_num=ep,
            title=f"第{ep}集正文",
            hook_3s="△ 特写：带血手套扔在桌上",
            body_markdown="△ 顾沉舟逼近两步。\n顾沉舟：你以为你逃得掉？",
            ending_cliffhanger="【片尾定格】△ 门外黑影一闪！",
            ast_data=ast,
        )

    # 序列化为 JSON 字符串
    state_json = state.model_dump_json()
    state_size_bytes = len(state_json.encode("utf-8"))
    state_size_kb = state_size_bytes / 1024.0

    print(f"Lean State 序列化体积: {state_size_kb:.2f} KB ({state_size_bytes} 字节)")

    # 验证体积严格小于 50KB（通常在 20~35KB 之间）
    assert state_size_kb < 50.0, f"State 体积超标: {state_size_kb:.2f} KB >= 50KB"
    assert len(state.active_window_episodes) == 3
    assert len(state.persisted_episode_refs) == 80
