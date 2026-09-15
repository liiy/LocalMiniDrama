"""阶段 7：视听导演分镜双模式选型与 SRT 字幕轴测节点 (Stage 7 Storyboard & SRT Node)。

严格遵循 SKILL.md：
- 首尾帧运镜控变 (模式 A) vs 多图资产参考控致 (模式 B) 严格裁决；
- 对白镜头标注口型动力学（jaw_open_scale 下颌开度、嘴角张力）；
- 自动生成符合广播级规范的毫秒级 SRT 时间轴。
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.script_graph_state import (
    IndustrialDramaMasterState,
    StoryboardShot,
)
from app.workflows.prompts.master_sop_prompts import STAGE7_SYSTEM_PROMPT
from app.workflows.utils.llm_bridge import call_llm_json


def _stage7_fallback(episode_num: int, script_title: str) -> dict[str, Any]:
    shots = [
        {
            "shot_id": 1,
            "timecode": "00:00:00,000 --> 00:00:02,500",
            "framing": "特写 (Close-up)",
            "camera_motion": "急速向前推镜头 (Rapid Push-in)",
            "duration_sec": 2.5,
            "generation_mode": "first_last_frame",
            "selection_rationale": "开局前3秒抓手动作，枪口直顶额头伴随水滴飞溅，需要首尾帧确保运动轨迹平滑爆发",
            "first_last_config": {
                "first_frame_prompt": "超写实电影特写，黑漆手枪枪口顶在主角额头，惨白闪电下冷汗滑落",
                "last_frame_prompt": "主角瞳孔骤缩，视线下移，右手暗中下探触碰钥匙扣",
                "video_motion_prompt": "急速推移特写，伴随雷暴闪光晃动",
            },
            "audio": {
                "dialogue": "",
                "foley": "暴雨拍击声，枪栓拉动的清脆咔哒声 (+2.5dB)",
                "music": "LEITMOTIF_01_SUSPENSE 紧凑低音提琴震音",
            },
            "lipsync_dynamics": None,
        },
        {
            "shot_id": 2,
            "timecode": "00:00:02,500 --> 00:00:06,000",
            "framing": "中景 (Medium Shot)",
            "camera_motion": "固定慢摇 (Slow Pan)",
            "duration_sec": 3.5,
            "generation_mode": "multi_image_reference",
            "selection_rationale": "双人对峙试探，需要严格保持反派金丝眼镜与主角伤痕的一致性",
            "multi_image_config": {
                "reference_asset_ids": ["CHAR_01_LUCHEN", "CHAR_02_HANTAI", "SCENE_01_WAREHOUSE"],
                "video_prompt": "韩泰面带冷笑缓步走出阴影，陆沉背靠工字钢立柱严阵以待",
            },
            "audio": {
                "dialogue": "韩泰：陆沉，三年了，你以为靠这枚U盘就能翻盘？",
                "foley": "皮鞋踩在湿水泥地的粘滞水声",
                "music": "LEITMOTIF_01_SUSPENSE 持续低频铺底",
            },
            "lipsync_dynamics": {
                "speaker": "韩泰",
                "jaw_open_scale": 0.65,
                "mouth_tension": "嘴角微微下撇，冷笑讥诮",
                "head_subtle_motion": "说话时头部微扬，居高临下",
            },
        },
        {
            "shot_id": 3,
            "timecode": "00:00:06,000 --> 00:00:09,000",
            "framing": "大特写 (Extreme Close-up)",
            "camera_motion": "固定微距 (Macro Static)",
            "duration_sec": 3.0,
            "generation_mode": "multi_image_reference",
            "selection_rationale": "核心反转物证细节展示，高精度微距特写",
            "multi_image_config": {
                "reference_asset_ids": ["PROP_01_USB"],
                "video_prompt": "微距拍摄带暗红血痕的磨砂钛合金加密U盘钥匙扣",
            },
            "audio": {
                "dialogue": "陆沉：你手上转着的沉香手串第三颗珠子...当年就是掐着它杀我师父的吧？",
                "foley": "钥匙环金属撞击微响 (+3.0dB)",
                "music": "LEITMOTIF_02_TRAUMA 凄厉中提琴切入",
            },
            "lipsync_dynamics": {
                "speaker": "陆沉",
                "jaw_open_scale": 0.55,
                "mouth_tension": "咬牙切齿，下唇紧绷",
                "head_subtle_motion": "眼神死死锁死对方",
            },
        },
    ]

    srt_content = (
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "（闪电划破雨夜，枪口抵在额头）\n\n"
        "2\n"
        "00:00:02,500 --> 00:00:06,000\n"
        "韩泰：陆沉，三年了，你以为靠这枚U盘就能翻盘？\n\n"
        "3\n"
        "00:00:06,000 --> 00:00:09,000\n"
        "陆沉：你手上的沉香手串...当年就是掐着它杀我师父的吧？\n"
    )

    return {
        "episode_num": episode_num,
        "shots": shots,
        "srt_content": srt_content,
    }


def _format_timecode(ms: int) -> str:
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def stage7_storyboard_srt_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 7：切片双模式分镜与生成毫秒级 SRT。"""
    ep_num = state.current_visual_episode or 1
    script = state.completed_screenplays.get(ep_num) or {}
    manifest = state.episode_resource_manifests.get(ep_num)
    manifest_dict = manifest.model_dump() if manifest else {}

    user_prompt = f"""【当前视听集数】第 {ep_num} 集
【单集文学剧本正文】
{json.dumps(script, ensure_ascii=False)}

【单集视听资源引单】
{json.dumps(manifest_dict, ensure_ascii=False)}

【阶段 4 音乐主题动机】
{json.dumps(state.audio_bible.model_dump() if hasattr(state, 'audio_bible') else {}, ensure_ascii=False)}

请严格执行双模式分镜裁决、口型动力学标注与毫秒级 SRT 时间轴输出，返回纯 JSON："""

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE7_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage7_fallback(ep_num, script.get("title", f"第{ep_num}集")),
    )

    raw_shots = result_json.get("shots") or []
    if not raw_shots:
        raw_shots = _stage7_fallback(ep_num, script.get("title", f"第{ep_num}集"))["shots"]

    current_time_ms = 0
    validated_shots: list[StoryboardShot] = []
    for s in raw_shots:
        try:
            # 字段容错适配
            if "duration_seconds" in s and "duration_sec" not in s:
                s["duration_sec"] = s["duration_seconds"]
            dur_sec = float(s.get("duration_sec") or 3.0)
            s["duration_sec"] = dur_sec

            if "shot_type" in s and "framing" not in s:
                s["framing"] = s["shot_type"]
            if "camera_movement" in s and "camera_motion" not in s:
                s["camera_motion"] = s["camera_movement"]
            if "mode" in s and "generation_mode" not in s:
                s["generation_mode"] = s["mode"]
            if "first_last_frame_config" in s and "first_last_config" not in s:
                s["first_last_config"] = s["first_last_frame_config"]

            dur_ms = int(dur_sec * 1000)
            start_ms = current_time_ms
            end_ms = current_time_ms + dur_ms
            current_time_ms = end_ms
            if "timecode" not in s or not s["timecode"]:
                s["timecode"] = f"{_format_timecode(start_ms)} --> {_format_timecode(end_ms)}"
            
            shot_obj = StoryboardShot.model_validate(s)
            validated_shots.append(shot_obj)
        except Exception:
            continue

    if not validated_shots:
        fb = _stage7_fallback(ep_num, script.get("title", f"第{ep_num}集"))
        validated_shots = [StoryboardShot.model_validate(s) for s in fb["shots"]]

    srt_content = result_json.get("srt_content") or _stage7_fallback(ep_num, "")["srt_content"]

    storyboards = dict(state.episode_storyboards or {})
    srts = dict(state.episode_srt_exports or {})

    storyboards[ep_num] = validated_shots
    srts[ep_num] = srt_content

    return {
        "current_stage": 7,
        "episode_storyboards": storyboards,
        "episode_srt_exports": srts,
    }
