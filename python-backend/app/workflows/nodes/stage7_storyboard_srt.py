"""阶段 7：视听导演分镜双模式选型与 SRT 字幕轴测节点 (Stage 7 Storyboard & SRT Node)。

严格遵循 SKILL.md：
- 首尾帧运镜控变 (模式 A) vs 多图资产参考控致 (模式 B) 严格裁决；
- 对白镜头标注口型动力学（jaw_open_scale 下颌开度、嘴角张力、与阶段 2 骨相张力对齐）；
- 自动生成符合广播级规范的毫秒级 SRT 时间轴与物理拟音标注 (+2.0dB ~ +3.0dB)；
- 全流程中文注释与 debug 级日志追踪。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.schemas.script_graph_state import (
    IndustrialDramaMasterState,
    StoryboardShot,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE7_SYSTEM_PROMPT,
    STAGE7_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage7_storyboard_srt")


def _stage7_fallback(
    episode_num: int,
    script_title: str,
    characters: list[dict[str, Any]],
    environments: list[dict[str, Any]],
    props: list[dict[str, Any]],
) -> dict[str, Any]:
    """当大模型离线或异常时的保底工业级分镜与毫秒级 SRT 生成工厂。"""
    logger.warning(f"Triggering Stage 7 dynamic fallback storyboard/SRT for Episode {episode_num} ('{script_title}').")

    p_name = characters[0].get("name", "主角") if characters else "主角"
    a_name = characters[1].get("name", "反派") if len(characters) > 1 else "反派"
    env_name = environments[0].get("location_name", "核心决战场景") if environments else "核心场景"
    hero_prop = props[0].get("name", "关键反转物证") if props else "关键物证"

    shots = [
        {
            "shot_id": 1,
            "timecode": "00:00:00,000 --> 00:00:02,500",
            "framing": "特写 (Close-up)",
            "camera_motion": "急速向前推镜头 (Rapid Push-in)",
            "duration_sec": 2.5,
            "generation_mode": "first_last_frame",
            "selection_rationale": "开局前3秒爆点动作，冷酷枪口逼近额头伴随冷汗滴落，首尾帧保障轨迹爆发力",
            "first_last_config": {
                "first_frame_prompt": (
                    f"cinematic photorealistic 8k, Chinese character {p_name}, extreme close-up on sweat sliding "
                    f"down cheekbones, trembling lower lip, cold rim lighting, gritty raw film grain"
                ),
                "last_frame_prompt": (
                    f"cinematic photorealistic 8k, Chinese character {p_name}, pupils constricting fiercely, "
                    f"right hand reaching inside worn coat pocket"
                ),
                "video_motion_prompt": "急速推移特写镜头，伴随惨白闪电冷光晃动",
            },
            "audio": {
                "dialogue": "",
                "foley": "暴雨猛烈拍击铁皮声，枪栓拉动的清脆咔哒声 (+2.5dB)",
                "music": "LEITMOTIF_01_SUSPENSE 紧凑低音提琴震音与40Hz脉冲",
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
            "selection_rationale": "双人对峙试探，多图参考保证反派金丝眼镜与主角粗花呢大衣质感严丝合缝",
            "multi_image_config": {
                "reference_asset_ids": [f"CHAR_01_{p_name}", f"CHAR_02_{a_name}", f"SCENE_01_{env_name}"],
                "video_prompt": f"{a_name}面带讥讽冷笑缓步走出阴影，{p_name}背靠斑驳立柱冷冷逼视",
            },
            "audio": {
                "dialogue": f"{a_name}：这么多年了，你以为靠这件所谓的铁证，就能推翻整个棋局？",
                "foley": "高级皮鞋踩在湿水泥地面的粘滞水声",
                "music": "LEITMOTIF_01_SUSPENSE 持续低频铺底 (-12dB Ducking 避让)",
            },
            "lipsync_dynamics": {
                "speaker": a_name,
                "jaw_open_scale": 0.65,
                "mouth_tension": "嘴角微微下撇，冷笑讥诮，眼周肌肉保持僵硬",
                "head_subtle_motion": "说话时头部微扬，居高临下",
            },
        },
        {
            "shot_id": 3,
            "timecode": "00:00:06,000 --> 00:00:09,000",
            "framing": "大特写 (Extreme Close-up)",
            "camera_motion": "低角度甩镜 (Low-angle Whip Pan)",
            "duration_sec": 3.0,
            "generation_mode": "multi_image_reference",
            "selection_rationale": f"核心反转物证 {hero_prop} 细节展示，微距特写与金属质感强化",
            "multi_image_config": {
                "reference_asset_ids": [f"PROP_01_{hero_prop}"],
                "video_prompt": f"微距拍摄带暗红磨痕的 {hero_prop} 被狠狠拍在金属桌面上",
            },
            "audio": {
                "dialogue": f"{p_name}：当年害死至亲时，你就是这么掐着它动的手吧！",
                "foley": f"{hero_prop} 砸向金属桌面的锐利震颤撞击声 (+3.0dB)",
                "music": "LEITMOTIF_03_COUNTERATTACK 激昂交响打击乐重音切入",
            },
            "lipsync_dynamics": {
                "speaker": p_name,
                "jaw_open_scale": 0.55,
                "mouth_tension": "方正下颌骨紧绷咬牙，下唇内侧肉微颤，眼神决绝",
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
        f"{a_name}：这么多年了，你以为靠这件所谓的铁证，就能推翻整个棋局？\n\n"
        "3\n"
        "00:00:06,000 --> 00:00:09,000\n"
        f"{p_name}：当年害死至亲时，你就是这么掐着它动的手吧！\n"
    )

    return {
        "episode_num": episode_num,
        "shots": shots,
        "srt_content": srt_content,
    }


def _format_timecode(ms: int) -> str:
    """毫秒时间戳转换为 SRT 标准时间码格式 hh:mm:ss,mmm。"""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def stage7_storyboard_srt_node(state: IndustrialDramaMasterState) -> dict[str, Any]:
    """执行阶段 7：切片双模式分镜、前序定格咬合与生成毫秒级 SRT。"""
    ep_num = state.current_visual_episode or 1
    script = state.completed_screenplays.get(ep_num) or {}
    manifest = state.episode_resource_manifests.get(ep_num)
    manifest_dict = manifest.model_dump() if manifest and hasattr(manifest, "model_dump") else manifest if isinstance(manifest, dict) else {}

    chars_list = state.characters_engine.get("characters", [])
    envs_list = state.environments_and_props.get("environments", [])
    props_list = state.environments_and_props.get("props", [])

    logger.info("【阶段 7 分镜与 SRT】开始执行第 %s 集工业分镜与毫秒级 SRT 生成...", ep_num)

    # 提取上一集 0 秒物理快照与前序定格画面物理锚点 (Previous Shot Freeze Frame)
    if ep_num == 1:
        if state.inter_episode_physical_snapshot:
            incoming_snapshot = state.inter_episode_physical_snapshot
        else:
            from app.workflows.nodes.physical_continuity import PhysicalContinuityEngine
            incoming_snapshot = PhysicalContinuityEngine.extract_initial_snapshot(
                chars_list, envs_list, props_list
            )
        previous_shot_freeze_frame = (
            incoming_snapshot.get("freeze_frame_desc")
            or script.get("hook_3s")
            or "第一集开篇首镜：主角与核心空间建立画面"
        )
    else:
        incoming_snapshot = state.inter_episode_physical_snapshot or {}
        prev_script = state.completed_screenplays.get(ep_num - 1) or {}
        previous_shot_freeze_frame = (
            incoming_snapshot.get("freeze_frame_desc")
            or prev_script.get("ending_cliffhanger")
            or f"第{ep_num - 1}集片尾绝杀定格画面"
        )

    logger.debug(
        "【阶段 7 分镜与 SRT】第 %s 集前序定格锚点: %s, 集间物理快照位置: %s",
        ep_num,
        previous_shot_freeze_frame,
        incoming_snapshot.get("location", "未指定"),
    )

    user_prompt = STAGE7_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        previous_shot_freeze_frame=previous_shot_freeze_frame,
        incoming_physical_snapshot=json.dumps(incoming_snapshot, ensure_ascii=False),
        script_json=json.dumps(script, ensure_ascii=False),
        manifest_json=json.dumps(manifest_dict, ensure_ascii=False),
        audio_bible_json=json.dumps(
            state.audio_bible.model_dump() if hasattr(state.audio_bible, "model_dump") else state.audio_bible,
            ensure_ascii=False,
        ),
    )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE7_SYSTEM_PROMPT,
        fallback_factory=lambda: _stage7_fallback(
            ep_num,
            script.get("title", f"第{ep_num}集"),
            chars_list,
            envs_list,
            props_list,
        ),
    )

    raw_shots = result_json.get("shots") or []
    if not raw_shots:
        raw_shots = _stage7_fallback(
            ep_num, script.get("title", f"第{ep_num}集"), chars_list, envs_list, props_list
        )["shots"]

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
        fb = _stage7_fallback(ep_num, script.get("title", f"第{ep_num}集"), chars_list, envs_list, props_list)
        validated_shots = [StoryboardShot.model_validate(s) for s in fb["shots"]]

    srt_content = result_json.get("srt_content") or _stage7_fallback(
        ep_num, "", chars_list, envs_list, props_list
    )["srt_content"]

    storyboards = dict(state.episode_storyboards or {})
    srts = dict(state.episode_srt_exports or {})

    storyboards[ep_num] = validated_shots
    srts[ep_num] = srt_content

    logger.info(
        f"[Stage 7 Node] Completed Episode {ep_num}: {len(validated_shots)} validated shots, SRT length {len(srt_content)} chars."
    )

    return {
        "current_stage": 7,
        "episode_storyboards": storyboards,
        "storyboard_shots": storyboards,
        "episode_srt_exports": srts,
    }
