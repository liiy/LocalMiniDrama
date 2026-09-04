"""测试移植模块：媒体规格、分镜提示词清洗、通用分镜归一化、首尾帧绑定、整集合并后处理工具函数。

覆盖:
- app.services.universalSegmentDurationNormalize
- app.utils.framePromptSanitize
- app.services.mediaAspectRatioSpec
- app.services.storyboardFrameBinding
- app.services.mergedEpisodePostProcess
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services import (
    mediaAspectRatioSpec as mas,
    mergedEpisodePostProcess as mep,
    storyboardFrameBinding as sfb,
    universalSegmentDurationNormalize as usn,
)
from app.utils import framePromptSanitize as fps


# ---------------------------------------------------------------- universalSegmentDurationNormalize


def test_normalize_universal_segment_shot_durations_single():
    text = "分镜1： 2秒: 远景，阳光洒在街道上"
    normalized = usn.normalize_universal_segment_shot_durations(text, "5", 5)
    assert normalized == "分镜1： 5秒: 远景，阳光洒在街道上"


def test_normalize_universal_segment_shot_durations_multi():
    text = "分镜1： 2秒: 特写\n分镜2： 2秒: 远景"
    normalized = usn.normalize_universal_segment_shot_durations(text, "6", 6)
    lines = normalized.splitlines()
    assert "分镜1： 3秒:" in lines[0]
    assert "分镜2： 3秒:" in lines[1]


def test_normalize_universal_segment_shot_durations_invalid():
    assert usn.normalize_universal_segment_shot_durations("", "5", 5) == ""
    assert usn.normalize_universal_segment_shot_durations("纯文本无分镜", "5", 5) == "纯文本无分镜"
    assert usn.normalize_universal_segment_shot_durations("分镜1： 2秒: 远景", "5", 0) == "分镜1： 2秒: 远景"


def test_normalize_universal_segment_at_image_spacing():
    # 标签紧贴后方中文字或开括号
    s1 = "场景中有@图片1正在跑"
    assert usn.normalize_universal_segment_at_image_spacing(s1) == "场景中有@图片1 正在跑"

    s2 = "手持@图片2「神秘道具」"
    assert usn.normalize_universal_segment_at_image_spacing(s2) == "手持@图片2 「神秘道具」"

    # 空或非字符串
    assert usn.normalize_universal_segment_at_image_spacing("") == ""
    assert usn.normalize_universal_segment_at_image_spacing(None) == ""


# ---------------------------------------------------------------- framePromptSanitize


def test_normalize_allowed_character_appearance():
    raw = "李雷（穿黑色西装，戴金丝眼镜）站在窗前"
    normalized, hits = fps.normalize_allowed_character_appearance(raw, ["李雷"])
    assert normalized == "李雷（参考图中的人物形象）站在窗前"
    assert len(hits) == 1
    assert hits[0]["name"] == "李雷"

    # 已经是参考图形象的不再改动
    unchanged, hits2 = fps.normalize_allowed_character_appearance(
        "李雷（参考图中的人物形象）站在窗前", ["李雷"]
    )
    assert unchanged == "李雷（参考图中的人物形象）站在窗前"
    assert len(hits2) == 0


def test_strip_unlisted_character_clauses():
    raw = "李雷站在窗前，韩梅梅坐在沙发上面向窗外"
    stripped, hits = fps.strip_unlisted_character_clauses(
        raw, allowed_names=["李雷"], all_drama_names=["李雷", "韩梅梅"]
    )
    assert "韩梅梅" not in stripped
    assert len(hits) == 1
    assert hits[0]["name"] == "韩梅梅"


def test_strip_modern_prop_boilerplate():
    raw = "古代大殿中，智能手机为正常6.1英寸平放于茶几上，绝不可立起或夸大，皇帝坐在龙椅上"
    stripped, hits = fps.strip_modern_prop_boilerplate(raw)
    assert "智能手机" not in stripped
    assert "皇帝坐在龙椅上" in stripped
    assert len(hits) >= 1


def test_cleanup_punctuation():
    raw = "，，李雷， ， 站在窗前，，"
    cleaned = fps.cleanup_punctuation(raw)
    assert cleaned == "李雷， 站在窗前"


def test_sanitize_frame_prompt_full_pipeline():
    raw = (
        "李雷（穿黑色西装）站在窗前，韩梅梅坐在沙发上面向窗外，"
        "智能手机为正常6.1英寸平放于茶几上，绝不可立起或夸大"
    )
    res = fps.sanitize_frame_prompt(
        raw,
        allowed_names=["李雷"],
        all_drama_names=["李雷", "韩梅梅"],
        opts={"return_report": True},
    )
    assert isinstance(res, dict)
    clean = res["prompt"]
    assert "李雷（参考图中的人物形象）" in clean
    assert "韩梅梅" not in clean
    assert "智能手机" not in clean
    assert res["report"]["changed"] is True


# ---------------------------------------------------------------- mediaAspectRatioSpec


def test_clamp_to_vidu_aspect_ratio():
    assert mas.clamp_to_vidu_aspect_ratio("16:9") == "16:9"
    assert mas.clamp_to_vidu_aspect_ratio("9:16") == "9:16"
    assert mas.clamp_to_vidu_aspect_ratio("21:9") == "21:9"
    assert mas.clamp_to_vidu_aspect_ratio("invalid") == "16:9"
    assert mas.clamp_to_vidu_aspect_ratio(None) == "16:9"


def test_pick_vidu_resolution_param():
    assert mas.pick_vidu_resolution_param("480p", "viduq2", False) == "540p"
    # Q2 family with image lifts 540p to 720p
    assert mas.pick_vidu_resolution_param("540p", "viduq2", True) == "720p"
    assert mas.pick_vidu_resolution_param("1080p", "viduq2", True) == "1080p"
    assert mas.pick_vidu_resolution_param(None, "viduq2", False) == "720p"


def test_aspect_ratio_label_from_pixel_size():
    assert mas.aspect_ratio_label_from_pixel_size("1920x1080") == "16:9"
    # 比例 1080/1920=0.5625 >= 0.55 对齐 Node 规则输出 '4:5'
    assert mas.aspect_ratio_label_from_pixel_size("1080*1920") == "4:5"
    assert mas.aspect_ratio_label_from_pixel_size("1024x1024") == "1:1"
    assert mas.aspect_ratio_label_from_pixel_size("2560x1080") == "21:9"
    # 直接比例字符串
    assert mas.aspect_ratio_label_from_pixel_size("9:16") == "9:16"
    assert mas.aspect_ratio_label_from_pixel_size("16:9") == "16:9"


# ---------------------------------------------------------------- mergedEpisodePostProcess


def test_format_srt_timestamp():
    assert mep.format_srt_timestamp(0) == "00:00:00,000"
    assert mep.format_srt_timestamp(1500) == "00:00:01,500"
    assert mep.format_srt_timestamp(65432) == "00:01:05,432"
    assert mep.format_srt_timestamp(3661005) == "01:01:01,005"
    assert mep.format_srt_timestamp(-50) == "00:00:00,000"


def test_build_atempo_chain():
    # 接近 1.0 时返回 None
    assert mep.build_atempo_chain(1.0) is None
    assert mep.build_atempo_chain(1.001) is None

    # 1.5 倍速
    c1 = mep.build_atempo_chain(1.5)
    assert c1 == "atempo=1.5000"

    # 3.0 倍速 (超过 2.0，分解为 atempo=2, atempo=1.5)
    c2 = mep.build_atempo_chain(3.0)
    assert "atempo=2" in c2 and "atempo=1.5000" in c2

    # 0.3 倍速 (低于 0.5，分解为 atempo=0.5, atempo=0.6)
    c3 = mep.build_atempo_chain(0.3)
    assert "atempo=0.5" in c3 and "atempo=0.6000" in c3


def test_escape_ffmpeg_path():
    # Windows 路径与单引号转义
    p = "C:\\path\\to\\file's.srt"
    esc = mep.escape_ffmpeg_path(p)
    assert "\\:" in esc or "C:" not in esc
    assert "\\'" in esc


# ---------------------------------------------------------------- storyboardFrameBinding


def test_bind_storyboard_frame_image_first():
    mock_db = MagicMock()
    with patch("app.services.storyboardFrameBinding.execute") as mock_exec:
        sfb.bind_storyboard_frame_image(
            mock_db,
            storyboard_id=42,
            frame_type="storyboard_first",
            image_gen_id=101,
            image_url="https://cdn/first.png",
            local_path="/local/first.png",
        )
        assert mock_exec.called
        call_args = mock_exec.call_args[0]
        sql = call_args[1]
        params = call_args[2]
        assert "first_frame_image_id" in sql
        assert params["sid"] == 42
        assert params["ig_id"] == 101
        assert params["url"] == "https://cdn/first.png"
        assert params["lp"] == "/local/first.png"


def test_bind_storyboard_frame_image_last():
    mock_db = MagicMock()
    with patch("app.services.storyboardFrameBinding.execute") as mock_exec:
        sfb.bind_storyboard_frame_image(
            mock_db,
            storyboard_id=42,
            frame_type="storyboard_last",
            image_gen_id=102,
            image_url="https://cdn/last.png",
            local_path="/local/last.png",
        )
        assert mock_exec.called
        call_args = mock_exec.call_args[0]
        sql = call_args[1]
        params = call_args[2]
        assert "last_frame_image_id" in sql
        assert params["sid"] == 42
        assert params["ig_id"] == 102
        assert params["url"] == "https://cdn/last.png"
        assert params["lp"] == "/local/last.png"


def test_bind_storyboard_frame_image_invalid_id():
    mock_db = MagicMock()
    with patch("app.services.storyboardFrameBinding.execute") as mock_exec:
        sfb.bind_storyboard_frame_image(
            mock_db,
            storyboard_id=None,
            frame_type="first",
            image_gen_id=1,
            image_url="url",
            local_path="lp",
        )
        assert not mock_exec.called

        sfb.bind_storyboard_frame_image(
            mock_db,
            storyboard_id="invalid",
            frame_type="first",
            image_gen_id=1,
            image_url="url",
            local_path="lp",
        )
        assert not mock_exec.called

