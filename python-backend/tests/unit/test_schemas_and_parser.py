"""单元测试：验证迭代 1 结构化数据模型与鲁棒解析器。"""
from __future__ import annotations

import pytest
from app.schemas import (
    AdaptationRule,
    CharacterProfile,
    CharacterStage,
    DialogueLine,
    DramaBible,
    EpisodeOutline,
    EpisodeScript,
    MusicBible,
    MusicCue,
    NovelAdaptationSpec,
    NovelChapterSlice,
    PaywallStrategy,
    PropProfile,
    SceneProfile,
    SceneSegment,
    ScriptSpec,
    StoryboardShot,
    VideoPrompt,
    VisualPrompt,
    VoiceProfile,
    extract_first_json_payload,
    parse_structured_list,
    parse_structured_output,
    repair_truncated_json,
)


def test_script_spec_defaults():
    spec = ScriptSpec(
        title_hint="绝品神医归来",
        genre="都市逆袭",
        target_episodes=80,
    )
    assert spec.title_hint == "绝品神医归来"
    assert spec.genre == "都市逆袭"
    assert spec.target_episodes == 80
    assert spec.paywall_strategy.enabled is True
    assert spec.paywall_strategy.first_paywall_episode == 10


def test_novel_adaptation_spec():
    spec = NovelAdaptationSpec(
        novel_title="九龙吞珠",
        original_author="张三",
        source_summary="主角林辰继承隐世龙门，归来复仇守护家族",
        target_episodes=100,
        adaptation_rules=[
            AdaptationRule(action="keep", target="龙门令现世", reason="核心高潮名场面"),
            AdaptationRule(action="remove", target="旁支弟子进山采药", reason="节奏拖沓，与主线无关"),
        ],
        chapter_slices=[
            NovelChapterSlice(chapter_index=1, chapter_title="第1章 归来", summary="林辰下山归来"),
        ],
    )
    assert spec.novel_title == "九龙吞珠"
    assert len(spec.adaptation_rules) == 2
    assert spec.adaptation_rules[1].action == "remove"


def test_drama_bible_and_episode_script():
    bible = DramaBible(
        title="战神狂飙",
        genre="战神爽剧",
        logline="昔日战神被夺兵权沦为赘婿，三年后十万旧部下跪迎王",
        synopsis="长篇剧情故事梗概...",
        total_episodes=80,
        episode_outlines=[
            EpisodeOutline(
                episode_number=1,
                title="受辱入赘",
                logline="主角被家族百般欺辱，龙王令突然现世",
                opening_hook="丈母娘当众撕碎婚约，逼迫下跪",
                main_conflict="家族宴会百般刁难",
                ending_cliffhanger="直升机轰鸣，十万将士空降庄园",
                is_paywall_episode=False,
            )
        ],
    )
    assert bible.title == "战神狂飙"
    assert len(bible.episode_outlines) == 1

    episode = EpisodeScript(
        episode_number=1,
        title="受辱入赘",
        opening_hook="丈母娘当众撕碎婚约，逼迫下跪",
        ending_cliffhanger="直升机轰鸣，十万将士空降庄园",
        scenes=[
            SceneSegment(
                scene_number=1,
                location_name="江家豪门宴会大厅",
                interior_exterior="interior",
                time_of_day="night",
                action_description="林辰默默站在角落，江夫人居高临下将离婚协议甩在地上",
                dialogue_list=[
                    DialogueLine(character_name="江夫人", dialogue_type="dialogue", text="把协议签了，滚出江家！", emotion="鄙夷嘲弄"),
                    DialogueLine(character_name="林辰", dialogue_type="dialogue", text="江家今日所赐，他日必百倍奉还。", emotion="平静深邃"),
                ],
            )
        ],
    )
    assert episode.episode_number == 1
    assert len(episode.scenes[0].dialogue_list) == 2


def test_character_and_scene_profiles():
    char = CharacterProfile(
        name="顾凌霄",
        role_type="protagonist",
        appearance_description="冷峻五官，剑眉星目，身材挺拔修长",
        identity_anchors=["右耳带纯黑耳钉", "眼神如刀", "黑色风衣"],
        stages=[
            CharacterStage(stage_id="stage_1", stage_name="落魄期", clothing_description="洗得发白的灰色连帽衫"),
            CharacterStage(stage_id="stage_2", stage_name="首富亮相", clothing_description="定制黑色手工西装配暗红领带"),
        ],
    )
    assert char.name == "顾凌霄"
    assert len(char.stages) == 2

    scene = SceneProfile(
        name="雨夜破庙",
        space_type="interior",
        atmosphere_lighting="狂风暴雨，电闪雷鸣，微弱篝火摇曳",
    )
    assert scene.name == "雨夜破庙"


def test_storyboard_and_prompts():
    shot = StoryboardShot(
        shot_index=1,
        scene_number=1,
        shot_type="close_up",
        camera_angle="low_angle",
        visual_action="主角猛然抬头，眼神如鹰隼般锐利盯向前方",
        visual_prompt=VisualPrompt(
            prompt="Cinematic close-up of a handsome cold man, rain pouring, sharp eyes, low angle, 8k",
            aspect_ratio="9:16",
        ),
        video_prompt=VideoPrompt(
            prompt="The man slowly raises his head, eyes turning fierce, camera pushes in dramatically",
            camera_movement="push_in",
            motion_intensity=6,
        ),
        dialogue_or_narration="我本不想杀人，奈何尔等逼人太甚！",
        speaker="顾凌霄",
    )
    assert shot.shot_index == 1
    assert shot.visual_prompt.aspect_ratio == "9:16"
    assert shot.video_prompt.camera_movement == "push_in"


def test_audio_and_music_models():
    voice = VoiceProfile(
        character_name="顾凌霄",
        timbre_description="低沉磁性霸总音，带有一丝沙哑压迫感",
        speaking_speed_ratio=1.1,
    )
    assert voice.character_name == "顾凌霄"

    music = MusicBible(
        overall_music_genre="暗黑史诗管弦 + 重低音电子",
    )
    assert music.overall_music_genre == "暗黑史诗管弦 + 重低音电子"

    cue = MusicCue(
        scene_number=1,
        bgm_prompt="大提琴急促重音突起，渲染杀机四伏",
        sfx_prompt="清脆响亮耳光声",
    )
    assert cue.scene_number == 1


def test_parser_markdown_and_trailing_commas():
    raw_markdown = """
    这是 AI 输出的回答：
    ```json
    {
        "title_hint": "极品家丁",
        "genre": "历史穿越",
        "target_episodes": 60,
    }
    ```
    请查收！
    """
    spec = parse_structured_output(raw_markdown, ScriptSpec)
    assert spec.title_hint == "极品家丁"
    assert spec.genre == "历史穿越"
    assert spec.target_episodes == 60


def test_parser_truncated_repair():
    truncated_json = '{"title_hint": "神豪奶爸", "genre": "都市生活", "target_episodes": 80'
    repaired = repair_truncated_json(truncated_json)
    assert repaired == '{"title_hint": "神豪奶爸", "genre": "都市生活", "target_episodes": 80}'

    spec = parse_structured_output(truncated_json, ScriptSpec)
    assert spec.title_hint == "神豪奶爸"


def test_parser_list_extraction():
    raw_list_json = """
    ```json
    [
        {"character_name": "张三", "text": "你竟敢背叛我！", "emotion": "暴怒"},
        {"character_name": "李四", "text": "成王败寇，怪不得别人。", "emotion": "冷笑"}
    ]
    ```
    """
    lines = parse_structured_list(raw_list_json, DialogueLine)
    assert len(lines) == 2
    assert lines[0].character_name == "张三"
    assert lines[1].emotion == "冷笑"
