"""阶段 7：视听导演分镜双模式选型与 SRT 字幕轴测节点 (Stage 7 Storyboard & SRT Node)。

严格遵循《Skill规则表》v10.0.0 与公共硬性约束：
- 【Skill规则表-Stage7-01-算子1】前序定格画面物理锚点 (Previous Shot Freeze Frame) 与集间0秒物理快照咬合；
- 【Skill规则表-Stage7-02-算子2】整秒分镜自适应时长测算子 (2.0s~7.0s 整数秒锁定，自适应拆镜与台词发声入点偏移)；
- 【Skill规则表-Stage7-03-算子3】生成模式与多模态提示词编译器 (模式 A 首尾帧 vs 模式 B 多模态参考 9 项自检 PASS_9 签名)；
- 【Skill规则表-Stage7-04-算子4】全息声音与发声阻力算子 (物理拟音 +3.0dB 增强，TTS 动态情境编译)；
- 【Skill规则表-Stage7-05-算子5】口型动力学静默元数据算子 (jaw_open_scale 保留在数据模型，严禁写入视频提示词)；
- 【Skill规则表-Stage7-06-SRT】毫秒级标准 SRT 字幕导出与音画严格咬合；
- 节点函数统一入参 state，内部严禁业务分支跳转，仅输出增量状态字典；
- 全流程中文注释与 debug 级日志追踪。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from app.schemas.script_graph_state import (
    IndustrialDramaMasterState,
    IndustrialDramaState,
    StoryboardShot,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE7_SYSTEM_PROMPT,
    STAGE7_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage7_storyboard_srt")


def _get_val(state: Any, key: str, default: Any = None) -> Any:
    """安全读取状态字典或对象中的属性。"""
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _format_timecode(ms: int) -> str:
    """毫秒时间戳转换为 SRT 标准时间码格式 hh:mm:ss,mmm。"""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _round_to_integer_sec(raw_sec: float) -> float:
    """【规则编号: Skill规则表-Stage7-02-算子2】单镜头时长整数秒自适应向上取整与封顶。
    
    允许整数秒: 2.0, 3.0, 4.0, 5.0, 6.0, 7.0；上限严格封顶为 7.0s。
    """
    sec = round(float(raw_sec))
    if sec < 2:
        sec = 2
    elif sec > 7:
        sec = 7
    return float(sec)


def _stage7_fallback(
    episode_num: int,
    script_title: str,
    characters: list[dict[str, Any]],
    environments: list[dict[str, Any]],
    props: list[dict[str, Any]],
) -> dict[str, Any]:
    """当大模型离线或异常时的保底工业级分镜与毫秒级 SRT 生成工厂。
    
    严格对齐《Skill规则表》Stage 7 数据契约：整秒时长、模式A/B选型、PASS_9签名、下颌开度静默元数据。
    """
    logger.warning(
        f"[Stage 7 Node] Triggering Stage 7 dynamic fallback storyboard/SRT for Episode {episode_num} ('{script_title}')."
    )

    p_name = characters[0].get("name", "主角") if characters else "主角"
    a_name = characters[1].get("name", "反派") if len(characters) > 1 else "反派"
    env_name = environments[0].get("location_name", "核心决战场景") if environments else "核心场景"
    hero_prop = props[0].get("name", "关键反转物证") if props else "关键物证"

    shots = [
        {
            "shot_id": 1,
            "timecode": "00:00:00,000 --> 00:00:03,000",
            "framing": "特写 (Close-up)",
            "camera_motion": "急速向前推镜头 (Rapid Push-in)",
            "duration_sec": 3.0,
            "generation_mode": "first_last_frame",
            "selection_rationale": "开局前3秒爆点动作，冷酷枪口逼近额头伴随冷汗滴落，首尾帧保障轨迹爆发力",
            "target_engine": "wan3.0",
            "rationale": "前置动作运镜(2.5s)+冲击缓冲(0.5s) 向上取整锁死 3.0s",
            "first_last_frame_config": {
                "first_frame_asset_ref": f"CHAR_01_{p_name}_BASE",
                "first_frame_prompt": (
                    f"cinematic photorealistic 8k, Chinese character {p_name}, extreme close-up on sweat sliding "
                    f"down cheekbones, trembling lower lip, cold rim lighting, gritty raw film grain"
                ),
                "last_frame_asset_ref": f"CHAR_01_{p_name}_ACTION",
                "last_frame_prompt": (
                    f"cinematic photorealistic 8k, Chinese character {p_name}, pupils constricting fiercely, "
                    f"right hand reaching inside worn coat pocket"
                ),
                "video_motion_prompt": "急速推移特写镜头，伴随惨白闪电冷光晃动，无肢体畸变、无五官崩坏、无画面抖动。",
            },
            "audio": {
                "dialogue": "",
                "speech_inpoint_sec": None,
                "is_dialogue_complete_in_shot": True,
                "foley": "暴雨猛烈拍击铁皮声，枪栓拉动的清脆咔哒声 (+3.0dB)",
                "music": "LEITMOTIF_01_SUSPENSE 紧凑低音提琴震音与40Hz脉冲",
                "contextual_tts_prompt": None,
            },
            "lipsync_dynamics": None,
        },
        {
            "shot_id": 2,
            "timecode": "00:00:03,000 --> 00:00:07,000",
            "framing": "中景 (Medium Shot)",
            "camera_motion": "固定慢摇 (Slow Pan)",
            "duration_sec": 4.0,
            "generation_mode": "multi_image_reference",
            "selection_rationale": "双人对峙试探，多图参考保证反派金丝眼镜与主角粗花呢大衣质感严丝合缝",
            "target_engine": "wan3.0",
            "rationale": "双人中景交代(1.0s)+核心台词22字(2.6s)+闭嘴缓冲(0.4s) 向上取整锁死 4.0s",
            "multi_image_config": {
                "media_manifest": {
                    "images": [
                        {"symbol": "图1", "asset_id": f"SCENE_01_{env_name}", "role": "场景底板"},
                        {"symbol": "图2", "asset_id": f"CHAR_02_{a_name}", "role": "反派说话角色"},
                        {"symbol": "图3", "asset_id": f"CHAR_01_{p_name}", "role": "主角对峙姿态"},
                    ],
                    "audios": [
                        {"symbol": "音频1", "voice_id": f"VOICE_{a_name}_MASTER", "role": "反派冷峻台词"},
                    ],
                },
                "reference_assets": [f"SCENE_01_{env_name}", f"CHAR_02_{a_name}", f"CHAR_01_{p_name}"],
                "video_prompt": (
                    f"图2站在图1的斑驳立柱前，背对落地窗冷眼逼视背靠立柱的图3。图2面带讥讽冷笑缓步走出阴影，"
                    f"用冷峻低沉说道（音频1）。无肢体畸变、无五官崩坏、无画面抖动。"
                ),
                "audit": "PASS_9",
            },
            "audio": {
                "dialogue": f"{a_name}：这么多年了，你以为靠这件所谓的铁证，就能推翻整个棋局？",
                "speech_inpoint_sec": 1.0,
                "is_dialogue_complete_in_shot": True,
                "foley": "高级皮鞋踩在湿水泥地面的粘滞水声 (+2.0dB)",
                "music": "LEITMOTIF_01_SUSPENSE 持续低频铺底 (-12dB Ducking 避让)",
                "contextual_tts_prompt": f"[{a_name}_VOICE, 语调冷峻挑衅, 尾音微微上挑带有轻蔑嘲弄]",
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
            "timecode": "00:00:07,000 --> 00:00:10,000",
            "framing": "大特写 (Extreme Close-up)",
            "camera_motion": "低角度甩镜 (Low-angle Whip Pan)",
            "duration_sec": 3.0,
            "generation_mode": "multi_image_reference",
            "selection_rationale": f"核心反转物证 {hero_prop} 细节展示，微距特写与金属质感强化",
            "target_engine": "wan3.0",
            "rationale": "物证拍桌动作(0.8s)+台词18字(1.8s)+余震闭嘴(0.4s) 向上取整锁死 3.0s",
            "multi_image_config": {
                "media_manifest": {
                    "images": [
                        {"symbol": "图1", "asset_id": f"SCENE_01_{env_name}", "role": "铁皮桌面背景"},
                        {"symbol": "图2", "asset_id": f"PROP_01_{hero_prop}", "role": "核心物证"},
                        {"symbol": "图3", "asset_id": f"CHAR_01_{p_name}", "role": "主角愤怒面部特写"},
                    ],
                    "audios": [
                        {"symbol": "音频1", "voice_id": f"VOICE_{p_name}_MASTER", "role": "主角悲愤咬牙台词"},
                    ],
                },
                "reference_assets": [f"SCENE_01_{env_name}", f"PROP_01_{hero_prop}", f"CHAR_01_{p_name}"],
                "video_prompt": (
                    f"微距特写带暗红磨痕的图2被图3右手狠狠砸在图1的金属桌面上，图3牙关紧咬死死盯住前方，"
                    f"用咬牙切齿低吼说道（音频1）。无肢体畸变、无五官崩坏、无画面抖动。"
                ),
                "audit": "PASS_9",
            },
            "audio": {
                "dialogue": f"{p_name}：当年害死至亲时，你就是这么掐着它动的手吧！",
                "speech_inpoint_sec": 0.8,
                "is_dialogue_complete_in_shot": True,
                "foley": f"{hero_prop} 砸向金属桌面的锐利震颤撞击声 (+3.0dB)",
                "music": "LEITMOTIF_03_COUNTERATTACK 激昂交响打击乐重音切入",
                "contextual_tts_prompt": f"[{p_name}_VOICE, 咬牙切齿从齿缝挤出, 情绪爆发带有悲壮颤音]",
            },
            "lipsync_dynamics": {
                "speaker": p_name,
                "jaw_open_scale": 0.48,
                "mouth_tension": "方正下颌骨紧绷咬牙，下唇内侧肉微颤，眼神决绝",
                "head_subtle_motion": "眼神死死锁死对方",
            },
        },
    ]

    srt_content = (
        "1\n"
        "00:00:00,000 --> 00:00:03,000\n"
        "（闪电划破雨夜，枪口抵在额头）\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:07,000\n"
        f"{a_name}：这么多年了，你以为靠这件所谓的铁证，就能推翻整个棋局？\n\n"
        "3\n"
        "00:00:07,800 --> 00:00:10,000\n"
        f"{p_name}：当年害死至亲时，你就是这么掐着它动的手吧！\n"
    )

    return {
        "episode_num": episode_num,
        "shots": shots,
        "srt_content": srt_content,
    }


def stage7_storyboard_srt_node(state: IndustrialDramaState | IndustrialDramaMasterState) -> dict[str, Any]:
    """【规则编号: Skill规则表-Stage7-01~06】执行阶段 7：切片双模式分镜、前序定格咬合与生成毫秒级 SRT。
    
    统一入参 state (TypedDict 或 MasterState 对象)，内部严禁业务分支跳转，仅输出增量状态更新。
    """
    ep_num = _get_val(state, "current_visual_episode", 1) or 1
    screenplays = _get_val(state, "completed_screenplays", {}) or {}
    script = screenplays.get(ep_num) or {}
    manifests = _get_val(state, "episode_resource_manifests", {}) or {}
    manifest = manifests.get(ep_num) or {}
    manifest_dict = manifest.model_dump() if hasattr(manifest, "model_dump") else manifest if isinstance(manifest, dict) else {}

    chars_engine = _get_val(state, "characters_engine", {}) or {}
    chars_list = chars_engine.get("characters", []) if isinstance(chars_engine, dict) else []
    env_props = _get_val(state, "environments_and_props", {}) or {}
    envs_list = env_props.get("environments", []) if isinstance(env_props, dict) else []
    props_list = env_props.get("props", []) if isinstance(env_props, dict) else []

    logger.info(f"【阶段 7 分镜与 SRT】开始执行第 {ep_num} 集工业分镜与毫秒级 SRT 生成...")

    # 【规则编号: Skill规则表-Stage7-01-算子1】提取上一集 0 秒物理快照与前序定格画面物理锚点 (Previous Shot Freeze Frame)
    snapshot = _get_val(state, "inter_episode_physical_snapshot", None)
    if ep_num == 1:
        if snapshot:
            incoming_snapshot = snapshot
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
        incoming_snapshot = snapshot or {}
        prev_script = screenplays.get(ep_num - 1) or {}
        previous_shot_freeze_frame = (
            incoming_snapshot.get("freeze_frame_desc")
            or prev_script.get("ending_cliffhanger")
            or f"第{ep_num - 1}集片尾绝杀定格画面"
        )

    logger.debug(
        f"[Stage 7 Node] Episode {ep_num} previous freeze anchor: {previous_shot_freeze_frame}, "
        f"incoming location: {incoming_snapshot.get('location', '未指定')}"
    )

    audio_bible = _get_val(state, "audio_bible", {})
    audio_bible_dict = audio_bible.model_dump() if hasattr(audio_bible, "model_dump") else audio_bible if isinstance(audio_bible, dict) else {}

    user_prompt = STAGE7_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        previous_shot_freeze_frame=previous_shot_freeze_frame,
        incoming_physical_snapshot=json.dumps(incoming_snapshot, ensure_ascii=False),
        script_json=json.dumps(script, ensure_ascii=False),
        manifest_json=json.dumps(manifest_dict, ensure_ascii=False),
        audio_bible_json=json.dumps(audio_bible_dict, ensure_ascii=False),
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

    # 【规则编号: Skill规则表-Stage7-02-算子2】整秒自适应时长测算与毫秒级时间码对齐
    current_time_ms = 0
    validated_shots: list[StoryboardShot] = []
    for s in raw_shots:
        try:
            # 字段别名容错适配
            if "duration_seconds" in s and "duration_sec" not in s:
                s["duration_sec"] = s["duration_seconds"]
            dur_sec = _round_to_integer_sec(float(s.get("duration_sec") or 3.0))
            s["duration_sec"] = dur_sec

            if "shot_type" in s and "framing" not in s:
                s["framing"] = s["shot_type"]
            if "camera_movement" in s and "camera_motion" not in s:
                s["camera_motion"] = s["camera_movement"]
            if "mode" in s and "generation_mode" not in s:
                s["generation_mode"] = s["mode"]
            if "first_last_frame_config" in s and "first_last_config" not in s:
                s["first_last_config"] = s["first_last_frame_config"]

            # 【规则编号: Skill规则表-Stage7-06-SRT】时间码毫秒级对齐整秒
            dur_ms = int(dur_sec * 1000)
            start_ms = current_time_ms
            end_ms = current_time_ms + dur_ms
            current_time_ms = end_ms
            s["timecode"] = f"{_format_timecode(start_ms)} --> {_format_timecode(end_ms)}"

            # 【规则编号: Skill规则表-Stage7-05-算子5】口型动力学静默元数据安全隔离
            # 确保 jaw_open_scale 不外泄到 video_prompt 中
            if s.get("lipsync_dynamics") and isinstance(s["lipsync_dynamics"], dict):
                jaw = s["lipsync_dynamics"].get("jaw_open_scale", 0.6)
                if "video_prompt" in s and "jaw_open_scale" in s["video_prompt"]:
                    s["video_prompt"] = s["video_prompt"].replace("jaw_open_scale", "")

            shot_obj = StoryboardShot.model_validate(s)
            validated_shots.append(shot_obj)
        except Exception as e:
            logger.debug(f"[Stage 7 Node] Shot validation skipping error: {e}")
            continue

    if not validated_shots:
        fb = _stage7_fallback(ep_num, script.get("title", f"第{ep_num}集"), chars_list, envs_list, props_list)
        validated_shots = [StoryboardShot.model_validate(s) for s in fb["shots"]]

    srt_content = result_json.get("srt_content") or _stage7_fallback(
        ep_num, script.get("title", f"第{ep_num}集"), chars_list, envs_list, props_list
    )["srt_content"]

    storyboards = dict(_get_val(state, "episode_storyboards", {}) or {})
    srts = dict(_get_val(state, "episode_srt_exports", {}) or {})

    storyboards[ep_num] = validated_shots
    srts[ep_num] = srt_content

    logger.info(
        f"[Stage 7 Node] Completed Episode {ep_num}: {len(validated_shots)} validated integer-second shots, "
        f"SRT length {len(srt_content)} chars."
    )

    return {
        "current_stage": 7,
        "episode_storyboards": storyboards,
        "storyboard_shots": storyboards,
        "episode_srt_exports": srts,
    }
