"""结构化数据模型与脚本标准 (Schemas & Specs)。

汇集整个短剧创作链路的核心契约标准（迭代 1 产物）：
- spec: 创作入口规范（AI 原创 ScriptSpec & 小说改编 NovelAdaptationSpec）
- drama: 世界观与剧本设定（DramaBible & EpisodeScript）
- profiles: 核心实体档案（CharacterProfile, SceneProfile, PropProfile）
- storyboard: 分镜与视听生成（StoryboardShot, VisualPrompt, VideoPrompt）
- audio: 声音与音乐设定（VoiceProfile, MusicBible, MusicCue）
- parser: 统一鲁棒 JSON 提取与强类型校验器
"""
from __future__ import annotations

from app.schemas.audio import (
    MusicBible,
    MusicCue,
    VoiceProfile,
)
from app.schemas.drama import (
    DialogueLine,
    DramaBible,
    EpisodeOutline,
    EpisodeScript,
    SceneSegment,
)
from app.schemas.parser import (
    extract_first_json_payload,
    parse_structured_list,
    parse_structured_output,
    repair_truncated_json,
)
from app.schemas.profiles import (
    CharacterProfile,
    CharacterStage,
    PropProfile,
    SceneProfile,
)
from app.schemas.spec import (
    AdaptationRule,
    NovelAdaptationSpec,
    NovelChapterSlice,
    PaywallStrategy,
    ScriptSpec,
)
from app.schemas.storyboard import (
    StoryboardShot,
    VideoPrompt,
    VisualPrompt,
)

__all__ = [
    # 入口规范
    "ScriptSpec",
    "NovelAdaptationSpec",
    "PaywallStrategy",
    "AdaptationRule",
    "NovelChapterSlice",
    # 剧本与世界观
    "DramaBible",
    "EpisodeOutline",
    "EpisodeScript",
    "SceneSegment",
    "DialogueLine",
    # 资产设定
    "CharacterProfile",
    "CharacterStage",
    "SceneProfile",
    "PropProfile",
    # 分镜视听
    "StoryboardShot",
    "VisualPrompt",
    "VideoPrompt",
    # 声音音乐
    "VoiceProfile",
    "MusicBible",
    "MusicCue",
    # 结构化解析
    "parse_structured_output",
    "parse_structured_list",
    "extract_first_json_payload",
    "repair_truncated_json",
]
