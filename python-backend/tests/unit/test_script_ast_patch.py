"""单元测试：验证 AST 视听正文分块解析器与局部原位修补 Router。"""
from __future__ import annotations

from app.schemas.script_graph_state import EpisodeScript, QAReport
from app.agents.script_ast_parser import ScriptASTParser
from app.agents.patch_router import TargetedPatchRouter


SAMPLE_SCRIPT = """
△ 开场特写（前3秒钩子）：
一只骨节分明的手将染血文件狠狠砸在茶几上，露出【确认非亲生】红印！

△ 顾沉舟眼神冷戾如刀，一步步逼近林浅。
△ 林浅后背抵住冰冷的落地窗，双拳紧攥。

顾沉舟（冷笑，压低声音）：林浅，养了你三年，你拿这个当礼物送我？
林浅（眼眶泛红，嘴角讥讽）：顾总既然早就查到了，何必装深情丈夫？

【片尾定格与悬念钩子】
△ 特写：林浅冷笑将刻着【舟】字的平安锁从窗边抛下！
【字幕悬念】：他苦苦寻找十年的救命恩人，竟被他亲手逼入绝境！
"""


def test_ast_parser_four_blocks():
    """测试 ASTParser 准确解析出 4 个标准结构块。"""
    ast = ScriptASTParser.parse(episode_num=10, markdown_text=SAMPLE_SCRIPT)
    assert len(ast.blocks) == 4

    block_map = {b.block_type: b.content for b in ast.blocks}
    assert "开场特写" in block_map["hook_3s"] or "染血文件" in block_map["hook_3s"]
    assert "顾沉舟眼神冷戾如刀" in block_map["actions_and_scenes"]
    assert "顾沉舟（冷笑" in block_map["dialogues"]
    assert "平安锁" in block_map["cliffhanger"]

    # 验证缝合一致性
    stitched = ScriptASTParser.stitch(ast)
    assert "染血文件" in stitched
    assert "顾总既然早就查到了" in stitched
    assert "字幕悬念" in stitched


def test_targeted_patch_router_identifies_defects_and_applies_patch():
    """测试五阶质检扣分缺陷定位与局部原位修补。"""
    episode = EpisodeScript(
        episode_num=10,
        title="第10集：帝龙令现世",
        body_markdown=SAMPLE_SCRIPT,
    )

    # 模拟质检报告：对白太水且片尾缺反转，结构分和语言分偏低（保持场景动作完好）
    qa_report = QAReport(
        episode_num=10,
        overall_score=78,
        passed=False,
        structure_score=19,  # 结构及格，钩子正常
        character_score=17,
        scene_score=19,      # 场景动作高分保留
        language_score=10,   # 语言偏低 -> dialogues
        continuity_score=18,
        flaws_identified=["台词略显直白缺乏潜台词拉扯", "片尾定格需要更强的卡点悬念"],
        refine_suggestions=["重写林浅对白，增加身份隐忍", "强化窗外抛下信物时的卡点定格"],
    )

    # 1. 缺陷定位
    target_blocks = TargetedPatchRouter.identify_target_blocks(qa_report)
    assert "dialogues" in target_blocks
    assert "cliffhanger" in target_blocks
    assert "actions_and_scenes" not in target_blocks

    # 2. 生成修补 Prompt
    patch_prompt = TargetedPatchRouter.build_patch_prompt(episode, qa_report, target_blocks)
    assert "【待修补目标块: dialogues】" in patch_prompt
    assert "【待修补目标块: cliffhanger】" in patch_prompt
    assert "【已锁定保留块: actions_and_scenes】" in patch_prompt

    # 3. 模拟大模型仅返回修补后的两块
    patched_blocks = {
        "dialogues": (
            "顾沉舟（指节泛白，冷笑）：这三年，你叫我沉舟的时候，心里看的是谁？\n"
            "林浅（擦去唇角血迹，笑得凄绝）：顾沉舟，你配知道吗？"
        ),
        "cliffhanger": (
            "【片尾定格与悬念钩子】\n"
            "△ 特写慢推：平安锁坠入深渊，林浅身后赫然浮现隐龙暗卫的影子！\n"
            "【字幕悬念】：下一集，隐龙殿三万暗卫齐聚江城！"
        ),
    }

    # 4. 执行局部原位修补
    patched_episode = TargetedPatchRouter.apply_patch(episode, patched_blocks)

    # 验证原先锁定的动作段落完好无损
    assert "顾沉舟眼神冷戾如刀" in patched_episode.body_markdown
    # 验证对白与片尾已被外科手术式替换
    assert "顾沉舟，你配知道吗？" in patched_episode.body_markdown
    assert "隐龙殿三万暗卫齐聚江城" in patched_episode.body_markdown
