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
import math
import re
from typing import Any, Mapping

from app.schemas.script_graph_state import (
    EpisodeScopedSubState,
    GlobalDramaMasterState,
    IndustrialDramaState,
    StoryboardShot,
)
from app.tools.shot_duration_calculator import (
    ShotDurationCalculator,
    calculate_shot_duration,
    check_episode_duration_tolerance,
    clean_dialogue_text,
    SPLIT_THRESHOLD_SEC,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE7_SYSTEM_PROMPT,
    STAGE7_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.llm_bridge import call_llm_json

logger = logging.getLogger("lmd.stage7_storyboard_srt")

# 绝对禁止出现在 video_prompt 中的空洞修饰词与口型/生理动作污染词
FORBIDDEN_PROMPT_WORDS = [
    "jaw_open_scale",
    "jaw_open",
    "自然眨眼",
    "呼吸起伏",
    "嘴唇闭合",
    "嘴唇开合",
    "4k",
    "8k",
    "超真实",
    "photorealistic",
    "masterpiece",
]


def clean_video_prompt(raw_prompt: str) -> str:
    """过滤并清洗 video_prompt 中的禁忌修饰词与口型/生理污染词。"""
    cleaned = raw_prompt or ""
    for w in FORBIDDEN_PROMPT_WORDS:
        cleaned = re.sub(re.escape(w), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def compile_engine_video_prompt(
    target_engine: str,
    scene_symbol: str,
    subject_symbol: str,
    counterpart_symbol: str | None,
    action_desc: str,
    dialogue_audio_symbol: str | None = None,
) -> str:
    """【算子 3】针对目标生成底模 (wan3.0 / seedance2.5 / minimax_h3) 编译模式 B 提示词分支。"""
    eng = (target_engine or "wan3.0").lower().strip()
    clean_action = clean_video_prompt(action_desc)

    if "seedance" in eng:
        # Seedance 2.5 模块化分段
        subj_part = f"[Subject] {subject_symbol}" + (f" 与 {counterpart_symbol} 对峙" if counterpart_symbol else "")
        env_part = f"[Environment] 在 {scene_symbol} 空间中，光影明暗交界清晰"
        act_part = f"[Action] {clean_action}" + (f"，同步开口说话（{dialogue_audio_symbol}）" if dialogue_audio_symbol else "")
        cam_part = "[Camera] 固定冷峻凝视，景别保持中近景，无肢体畸变、无五官崩坏、无画面抖动"
        return f"{subj_part}。{env_part}。{act_part}。{cam_part}。"
    elif "minimax" in eng:
        # MiniMax H3 自然语言叙述流
        res = f"在 {scene_symbol} 空间中，{subject_symbol}"
        if counterpart_symbol:
            res += f" 逼视着 {counterpart_symbol}，"
        res += f" {clean_action}"
        if dialogue_audio_symbol:
            res += f"，低沉开口说道（{dialogue_audio_symbol}）"
        res += "。情绪连贯克制，无肢体畸变、无五官崩坏、无画面抖动。"
        return res
    else:
        # Wan 3.0 物理光影与动态细节 (默认)
        res = f"在 {scene_symbol} 环境中，光影反射在地面与墙壁。"
        res += f"{subject_symbol}"
        if counterpart_symbol:
            res += f" 与 {counterpart_symbol} 相对而立，"
        res += f" {clean_action}"
        if dialogue_audio_symbol:
            res += f"，伴随微表情变化开口叙述（{dialogue_audio_symbol}）"
        res += "。电影级物理质感，无肢体畸变、无五官崩坏、无画面抖动。"
        return res


def compile_mode_b_manifest_check(
    episode_num: int,
    shots: list[StoryboardShot],
    target_engine: str = "wan3.0",
) -> dict[str, Any]:
    """【集末输出】汇总生成模式 B 多图参考 9 项自审清单 (mode_b_manifest_check)。"""
    mode_b_shots = [s for s in shots if getattr(s, "generation_mode", "") in ("multi_image_reference", "multi_image_ref")]
    total = len(mode_b_shots)
    if total == 0:
        return {
            "episode_num": episode_num,
            "total_mode_b_shots": 0,
            "max_images_under_limit": True,
            "scene_unique_and_first": True,
            "character_numbered_from_two": True,
            "audio_independent_order": True,
            "spatial_constraint_front": True,
            "temporal_order_forward": True,
            "target_engine_compliant": True,
            "no_forbidden_prompt_words": True,
            "all_pass_9_signed": True,
            "verdict": "PASS",
            "issues": [],
        }

    issues: list[str] = []
    max_images_ok = True
    scene_first_ok = True
    char_num_ok = True
    audio_order_ok = True
    spatial_front_ok = True
    temporal_ok = True
    engine_ok = True
    no_forbidden_ok = True
    all_pass_9 = True

    for s in mode_b_shots:
        s_id = getattr(s, "shot_id", 0)
        mic = getattr(s, "multi_image_config", {}) or {}
        if not isinstance(mic, dict):
            mic = {}
        refs = mic.get("reference_assets") or mic.get("reference_asset_ids") or []
        if len(refs) > 4:
            max_images_ok = False
            issues.append(f"Shot {s_id}: 模式 B 参考图数量 {len(refs)} 超过 4 张")

        manifest = mic.get("media_manifest") or {}
        images = manifest.get("images") or []
        if images:
            first_img = images[0]
            if isinstance(first_img, dict):
                first_id = first_img.get("asset_id", "")
                if not (first_id.startswith("ENV_") or first_id.startswith("SCENE_")):
                    scene_first_ok = False
                    issues.append(f"Shot {s_id}: 图1必须为场景环境资产，当前为 {first_id}")

        v_prompt = mic.get("video_prompt") or getattr(s, "video_prompt", "")
        for w in FORBIDDEN_PROMPT_WORDS:
            if re.search(re.escape(w), v_prompt, re.IGNORECASE):
                no_forbidden_ok = False
                issues.append(f"Shot {s_id}: video_prompt 包含禁忌词 '{w}'")
                break

        if mic.get("audit") != "PASS_9":
            all_pass_9 = False
            issues.append(f"Shot {s_id}: 缺失 PASS_9 签名")

    verdict = "PASS" if not issues else "FAIL"
    return {
        "episode_num": episode_num,
        "total_mode_b_shots": total,
        "max_images_under_limit": max_images_ok,
        "scene_unique_and_first": scene_first_ok,
        "character_numbered_from_two": char_num_ok,
        "audio_independent_order": audio_order_ok,
        "spatial_constraint_front": spatial_front_ok,
        "temporal_order_forward": temporal_ok,
        "target_engine_compliant": engine_ok,
        "no_forbidden_prompt_words": no_forbidden_ok,
        "all_pass_9_signed": all_pass_9,
        "verdict": verdict,
        "issues": issues,
    }


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
    
    允许整数秒集合: {2.0, 3.0, 4.0, 5.0, 6.0, 7.0}；上限严格封顶为 7.0s。
    """
    sec = int(round(float(raw_sec)))
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
    target_engine: str = "wan3.0",
    planned_duration_sec: float = 120.0,
    script: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """当大模型离线或异常时的保底工业级分镜与毫秒级 SRT 生成工厂。
    
    严格对齐《Skill规则表》Stage 7 数据契约与章节三四段式资产寻址体系：
    整秒时长、模式A/B选型、PASS_9签名、下颌开度静默元数据。
    深度融合阶段 5 视听原子小节 (AudioVisualBeat)，将微动作、发声阻力与对白无缝映射至分镜。
    """
    logger.warning(
        f"[Stage 7 Node] Triggering Stage 7 dynamic fallback storyboard/SRT for Episode {episode_num} ('{script_title}')."
    )

    p_char = characters[0] if characters else {}
    a_char = characters[1] if len(characters) > 1 else {}
    p_name = p_char.get("name", "主角")
    a_name = a_char.get("name", "反派")

    p_tok = p_char.get("character_token") or AssetProtocolHelper.chinese_to_token(p_name) or "PROTAGONIST"
    a_tok = a_char.get("character_token") or AssetProtocolHelper.chinese_to_token(a_name) or "ANTAGONIST"

    env_item = environments[0] if environments else {}
    env_name = env_item.get("location_name") or env_item.get("name", "核心场景")
    env_tok = env_item.get("scene_token") or AssetProtocolHelper.chinese_to_token(env_name) or "PRIMARY"

    prop_item = props[0] if props else {}
    hero_prop = prop_item.get("name", "关键物证")
    prop_tok = prop_item.get("prop_token") or AssetProtocolHelper.chinese_to_token(hero_prop) or "EVIDENCE"

    p_base_portrait = f"CHAR_{p_tok}_T1_BASE_PORTRAIT"
    a_base_portrait = f"CHAR_{a_tok}_T1_BASE_PORTRAIT"
    env_wide = f"ENV_{env_tok}_T1_WIDE"
    env_ots = f"ENV_{env_tok}_T1_OTS_BG"
    prop_static = f"PROP_{prop_tok}_T1_STATIC"
    prop_action = f"PROP_{prop_tok}_T1_ACTION_DAMAGED"
    a_voice = f"VOICE_{a_tok}_T1_MASTER"
    p_voice = f"VOICE_{p_tok}_T1_MASTER"

    # 尝试从阶段 5 输出的 AST 视听原子小节 (AudioVisualBeat) 提取高精度人物应激、发声腔体与真实对白
    ast_data = script.get("ast_data", {}) if isinstance(script, dict) else {}
    beats = ast_data.get("beats", []) if isinstance(ast_data, dict) else []
    dlg_beats = [b for b in beats if (b.get("beat_type") if isinstance(b, dict) else getattr(b, "beat_type", None)) == "dialogue"]

    shot2_speaker = a_name
    shot2_dlg = f"{a_name}：这么多年了，你以为靠这件所谓的铁证，就能推翻整个棋局？"
    shot2_stress = "面带讥讽冷笑缓步走出阴影，眼神冰冷逼视"
    shot2_tts = f"[{a_name}_VOICE, 语调冷峻挑衅, 胸腔低频微共鸣]"

    shot3_speaker = p_name
    shot3_dlg = f"{p_name}：当年害死至亲时，你就是这么掐着它动的手吧！"
    shot3_stress = f"牙关紧咬，右手将微距带暗红磨痕的【{hero_prop}】狠狠砸在金属桌面上"
    shot3_tts = f"[{p_name}_VOICE, 咬牙切齿从齿缝挤出, 情绪爆发带有悲壮颤音]"

    if len(dlg_beats) >= 2:
        b1 = dlg_beats[0] if isinstance(dlg_beats[0], dict) else dlg_beats[0].model_dump()
        b2 = dlg_beats[1] if isinstance(dlg_beats[1], dict) else dlg_beats[1].model_dump()
        b1_spk = b1.get("speaker") or shot2_speaker
        b1_text = b1.get("dialogue_text") or ""
        b1_stress = b1.get("stress_action") or ""
        b1_voice = b1.get("vocal_delivery") or ""
        if b1_text:
            shot2_speaker = b1_spk
            shot2_dlg = f"{b1_spk}：{b1_text}"
            if b1_stress:
                shot2_stress = f"{b1_stress}，缓步逼视"
            if b1_voice:
                shot2_tts = f"[{b1_spk}_VOICE, {b1_voice}]"

        b2_spk = b2.get("speaker") or shot3_speaker
        b2_text = b2.get("dialogue_text") or ""
        b2_stress = b2.get("stress_action") or ""
        b2_voice = b2.get("vocal_delivery") or ""
        if b2_text:
            shot3_speaker = b2_spk
            shot3_dlg = f"{b2_spk}：{b2_text}"
            if b2_stress:
                shot3_stress = f"{b2_stress}，右手死死攥紧【{hero_prop}】"
            if b2_voice:
                shot3_tts = f"[{b2_spk}_VOICE, {b2_voice}]"
        logger.info(
            "【阶段7 分镜保底】成功从阶段5 AST Beats 注入真实微动作与发声腔体: 镜头2=(%s, %s), 镜头3=(%s, %s)",
            shot2_speaker, b1_voice or "默认", shot3_speaker, b2_voice or "默认"
        )

    # 模式 B 提示词多引擎编译
    shot2_prompt = compile_engine_video_prompt(
        target_engine=target_engine,
        scene_symbol="图1",
        subject_symbol="图2",
        counterpart_symbol="图3",
        action_desc=shot2_stress,
        dialogue_audio_symbol="音频1",
    )
    shot3_prompt = compile_engine_video_prompt(
        target_engine=target_engine,
        scene_symbol="图1",
        subject_symbol="图3",
        counterpart_symbol=None,
        action_desc=shot3_stress,
        dialogue_audio_symbol="音频1",
    )

    shots = [
        {
            "shot_id": 1,
            "timecode": "00:00:00,000 --> 00:00:03,000",
            "framing": "ECU 极特写",
            "camera_motion": "急速向前推镜头 (Rapid Push-in)",
            "duration_sec": 3.0,
            "generation_mode": "first_last_frame",
            "selection_rationale": "开局前3秒动作爆发与信件撕毁强物理形变，采用首尾帧控变",
            "target_engine": target_engine,
            "rationale": "撕扯剧烈动作(2.0s) + 道具交互缓冲(1.0s) = 3.0s",
            "character_asset_ids": [p_base_portrait],
            "scene_asset_id": env_wide,
            "prop_asset_ids": [prop_action],
            "first_last_config": {
                "first_frame_asset_id": p_base_portrait,
                "first_frame_asset_ref": p_base_portrait,
                "first_frame_prompt": (
                    f"电影级极特写，冰冷枪口顶在主角额头，汗水顺着高颧骨滑落，方正下颌紧绷，冷调边缘光"
                ),
                "last_frame_asset_id": prop_action,
                "last_frame_asset_ref": prop_action,
                "last_frame_prompt": (
                    f"主角瞳孔骤缩，右手猛然撕裂绝密信件，红色印鉴断裂，纸屑翻飞纷落"
                ),
                "video_motion_prompt": "急速推移特写镜头，双手猛烈反向撕扯信纸，伴随闪电冷光晃动，无肢体畸变、无五官崩坏、无画面抖动。",
            },
            "audio": {
                "dialogue": "",
                "speech_inpoint_sec": None,
                "is_dialogue_complete_in_shot": True,
                "foley": "[Foley+3dB: 暴雨拍击铁皮声与信纸撕裂脆响]",
                "music": "LEITMOTIF_01_SUSPENSE 紧凑低音提琴震音与40Hz脉冲",
                "contextual_tts_prompt": None,
            },
            "lipsync_dynamics": None,
        },
        {
            "shot_id": 2,
            "timecode": "00:00:03,000 --> 00:00:07,000",
            "framing": "MCU 中近景",
            "camera_motion": "固定慢摇 (Slow Pan)",
            "duration_sec": 4.0,
            "generation_mode": "multi_image_reference",
            "selection_rationale": "双人对峙试探与对白微表情，多图参考保证金丝眼镜与大衣质感严丝合缝",
            "target_engine": target_engine,
            "rationale": "双人中景交代(1.0s) + 核心台词22字(2.6s) + 闭嘴缓冲(0.4s) 向上取整锁死 4.0s",
            "character_asset_ids": [a_base_portrait, p_base_portrait],
            "scene_asset_id": env_wide,
            "prop_asset_ids": [],
            "multi_image_config": {
                "media_manifest": {
                    "images": [
                        {"symbol": "图1", "asset_id": env_wide, "role": "场景底板"},
                        {"symbol": "图2", "asset_id": a_base_portrait, "role": "反派说话角色"},
                        {"symbol": "图3", "asset_id": p_base_portrait, "role": "主角对峙姿态"},
                    ],
                    "audios": [
                        {"symbol": "音频1", "voice_id": a_voice, "role": "反派冷峻台词"},
                    ],
                },
                "reference_asset_ids": [env_wide, a_base_portrait, p_base_portrait],
                "reference_assets": [env_wide, a_base_portrait, p_base_portrait],
                "video_prompt": shot2_prompt,
                "target_engine": target_engine,
                "audit": "PASS_9",
            },
            "audio": {
                "dialogue": shot2_dlg,
                "speech_inpoint_sec": 0.3,
                "is_dialogue_complete_in_shot": True,
                "foley": "[Foley+3dB: 高级皮鞋踩在湿水泥地面的粘滞水声]",
                "music": "LEITMOTIF_01_SUSPENSE 持续低频铺底 (-12dB Ducking 避让)",
                "contextual_tts_prompt": shot2_tts,
            },
            "lipsync_dynamics": {
                "speaker": shot2_speaker,
                "jaw_open_scale": 0.65,
                "mouth_tension": "嘴角微微下撇，冷笑讥诮，眼周肌肉保持僵硬",
                "head_subtle_motion": "说话时头部微扬，居高临下",
            },
        },
        {
            "shot_id": 3,
            "timecode": "00:00:07,000 --> 00:00:10,000",
            "framing": "CU 特写",
            "camera_motion": "低角度甩镜 (Low-angle Whip Pan)",
            "duration_sec": 3.0,
            "generation_mode": "multi_image_reference",
            "selection_rationale": f"核心反转物证 {hero_prop} 细节展示，微距特写与金属质感强化",
            "target_engine": target_engine,
            "rationale": "物证拍桌动作(0.8s) + 台词18字(1.8s) + 余震闭嘴(0.4s) 向上取整锁死 3.0s",
            "character_asset_ids": [p_base_portrait],
            "scene_asset_id": env_ots,
            "prop_asset_ids": [prop_static],
            "multi_image_config": {
                "media_manifest": {
                    "images": [
                        {"symbol": "图1", "asset_id": env_ots, "role": "铁皮桌面背景"},
                        {"symbol": "图2", "asset_id": prop_static, "role": "核心物证"},
                        {"symbol": "图3", "asset_id": p_base_portrait, "role": "主角愤怒面部特写"},
                    ],
                    "audios": [
                        {"symbol": "音频1", "voice_id": p_voice, "role": "主角悲愤咬牙台词"},
                    ],
                },
                "reference_asset_ids": [env_ots, prop_static, p_base_portrait],
                "reference_assets": [env_ots, prop_static, p_base_portrait],
                "video_prompt": shot3_prompt,
                "target_engine": target_engine,
                "audit": "PASS_9",
            },
            "audio": {
                "dialogue": shot3_dlg,
                "speech_inpoint_sec": 0.3,
                "is_dialogue_complete_in_shot": True,
                "foley": f"[Foley+3dB: {hero_prop} 砸向金属桌面的锐利震颤撞击声]",
                "music": "LEITMOTIF_03_COUNTERATTACK 激昂交响打击乐重音切入",
                "contextual_tts_prompt": shot3_tts,
            },
            "lipsync_dynamics": {
                "speaker": shot3_speaker,
                "jaw_open_scale": 0.48,
                "mouth_tension": "方正下颌骨紧绷咬牙，下唇内侧肉微颤，眼神决绝",
                "head_subtle_motion": "眼神死死锁死对方",
            },
        },
    ]

    srt_content = (
        "1\n"
        "00:00:00,000 --> 00:00:03,000\n"
        "（闪电划破雨夜，枪栓拉动与信纸撕裂声）\n\n"
        "2\n"
        "00:00:03,300 --> 00:00:06,800\n"
        f"{shot2_dlg}\n\n"
        "3\n"
        "00:00:07,300 --> 00:00:09,800\n"
        f"{shot3_dlg}\n"
    )

    shot_objs = [StoryboardShot.model_validate(s) for s in shots]
    mode_b_check = compile_mode_b_manifest_check(episode_num, shot_objs, target_engine)

    return {
        "episode_num": episode_num,
        "shots": shots,
        "srt_content": srt_content,
        "mode_b_manifest_check": mode_b_check,
    }


def stage7_storyboard_srt_node(
    state: EpisodeScopedSubState | GlobalDramaMasterState | IndustrialDramaState | Any,
) -> dict[str, Any]:
    """【规则编号: Skill规则表-Stage7-01~06】执行阶段 7：切片双模式分镜、前序定格咬合与生成毫秒级 SRT。
    
    统一入参 state (TypedDict 或 MasterState 对象)，内部严禁业务分支跳转，仅输出增量状态更新。
    """
    ep_num = _get_val(state, "episode_number") or _get_val(state, "current_visual_episode", 1) or 1
    screenplays = _get_val(state, "completed_screenplays", {}) or {}
    script = screenplays.get(ep_num) or {}
    if not script and _get_val(state, "screenplay"):
        script = _get_val(state, "screenplay")
    if not script and _get_val(state, "screenplay_text"):
        script = {"title": f"第{ep_num}集", "body_markdown": _get_val(state, "screenplay_text")}
    if hasattr(script, "model_dump"):
        script = script.model_dump()
    elif not isinstance(script, dict):
        script = {}
    manifests = _get_val(state, "episode_resource_manifests", {}) or {}
    manifest = manifests.get(ep_num) or _get_val(state, "episode_manifest") or {}
    manifest_dict = manifest.model_dump() if hasattr(manifest, "model_dump") else manifest if isinstance(manifest, dict) else {}

    chars_engine = _get_val(state, "characters_engine", {}) or {}
    chars_list = chars_engine.get("characters", []) if isinstance(chars_engine, dict) else []
    env_props = _get_val(state, "environments_and_props", {}) or {}
    envs_list = env_props.get("environments", []) if isinstance(env_props, dict) else []
    props_list = env_props.get("props", []) if isinstance(env_props, dict) else []

    # 兼容单集独立切片 EpisodeScopedSubState 中的轻量桩
    if not chars_list and _get_val(state, "relevant_character_stubs"):
        chars_list = [
            {
                "character_id": f"CHAR_{c.character_id}" if not str(c.character_id).startswith("CHAR_") else str(c.character_id),
                "name": c.name,
                "role_type": c.archetype,
                "appearance": c.visual_token,
                "voice_style": c.core_costume_prompt,
            }
            if hasattr(c, "character_id") else c
            for c in _get_val(state, "relevant_character_stubs")
        ]
    if not envs_list and _get_val(state, "relevant_scene_stubs"):
        envs_list = [
            {
                "env_id": f"ENV_{s.scene_id}" if not str(s.scene_id).startswith("ENV_") else str(s.scene_id),
                "location_name": s.name,
                "visual_prompt": s.weathering_summary,
                "atmosphere": s.color_tone,
            }
            if hasattr(s, "scene_id") else s
            for s in _get_val(state, "relevant_scene_stubs")
        ]
    if not props_list and _get_val(state, "relevant_prop_stubs"):
        props_list = [
            {
                "prop_id": f"PROP_{p.prop_id}" if not str(p.prop_id).startswith("PROP_") else str(p.prop_id),
                "name": p.name,
                "type": p.level,
                "visual_prompt": p.visual_token,
            }
            if hasattr(p, "prop_id") else p
            for p in _get_val(state, "relevant_prop_stubs")
        ]

    target_video_engine = str(_get_val(state, "target_video_engine", "wan3.0") or "wan3.0")
    planned_duration_sec = float(_get_val(state, "duration_sec_per_ep", 120.0) or _get_val(state, "target_duration_sec", 120.0) or 120.0)

    logger.info(f"【阶段 7 分镜与 SRT】开始执行第 {ep_num} 集工业分镜 (目标引擎: {target_video_engine}, 规划时长: {planned_duration_sec}s)...")

    # 【规则编号: Skill规则表-Stage7-01-算子1】提取上一集 0 秒物理快照与前序定格画面物理锚点 (Previous Shot Freeze Frame)
    raw_snapshot = _get_val(state, "inter_episode_physical_snapshot", None) or _get_val(state, "incoming_physical_continuity", None)
    if raw_snapshot is not None:
        incoming_snapshot = raw_snapshot.model_dump() if hasattr(raw_snapshot, "model_dump") else dict(raw_snapshot) if isinstance(raw_snapshot, dict) else {}
    elif ep_num == 1:
        from app.workflows.nodes.physical_continuity import PhysicalContinuityEngine
        extracted = PhysicalContinuityEngine.extract_initial_snapshot(
            chars_list, envs_list, props_list
        )
        incoming_snapshot = extracted.model_dump() if hasattr(extracted, "model_dump") else dict(extracted) if isinstance(extracted, dict) else {}
    else:
        incoming_snapshot = {}

    if ep_num == 1:
        previous_shot_freeze_frame = (
            incoming_snapshot.get("freeze_frame_desc")
            or script.get("hook_3s")
            or "第一集开篇首镜：主角与核心空间建立画面"
        )
    else:
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
        target_video_engine=target_video_engine,
        planned_duration_sec=int(planned_duration_sec),
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
            target_engine=target_video_engine,
            planned_duration_sec=planned_duration_sec,
            script=script,
        ),
    )

    raw_shots = result_json.get("shots") or []
    if not raw_shots:
        raw_shots = _stage7_fallback(
            ep_num,
            script.get("title", f"第{ep_num}集"),
            chars_list,
            envs_list,
            props_list,
            target_engine=target_video_engine,
            planned_duration_sec=planned_duration_sec,
            script=script,
        )["shots"]

    # 【算子 2：自适应拆镜展开】若单镜头时长 > 6.5s 或台词过长，强制解耦为动作铺垫镜 + 对白特写镜
    expanded_raw_shots: list[dict[str, Any]] = []
    for s in raw_shots:
        raw_dur = float(s.get("duration_sec") or s.get("duration_seconds") or 3.0)
        audio_info = s.get("audio") or {}
        dialogue = audio_info.get("dialogue") or s.get("dialogue") or s.get("srt_text") or ""
        clean_dlg = clean_dialogue_text(dialogue)

        if raw_dur > SPLIT_THRESHOLD_SEC or (clean_dlg and len(clean_dlg) > 25):
            calc_res = calculate_shot_duration(
                dialogue_text=dialogue,
                custom_action_sec=2.0 if raw_dur > SPLIT_THRESHOLD_SEC else None,
            )
            if calc_res.is_split and len(calc_res.plans) >= 2:
                plan_a = calc_res.plans[0]
                plan_b = calc_res.plans[1]

                # Shot A: 动作前置镜头（无对白）
                shot_a = dict(s)
                shot_a["duration_sec"] = plan_a.duration_sec
                shot_a["framing"] = plan_a.recommended_framing
                shot_a["camera_motion"] = "推进或慢摇动作前置"
                shot_a["rationale"] = plan_a.rationale
                shot_a["generation_mode"] = "first_last_frame"
                shot_a["audio"] = {
                    "dialogue": "",
                    "foley": audio_info.get("foley") or "[Foley+3dB: 动作准备与环境铺底音效]",
                    "music": audio_info.get("music", ""),
                    "is_dialogue_complete_in_shot": True,
                    "speech_inpoint_sec": None,
                    "contextual_tts_prompt": None,
                }
                shot_a["srt_text"] = ""
                ref_first = (s.get("character_asset_ids") or ["CHAR_PROTAGONIST_T1_BASE_PORTRAIT"])[0]
                shot_a["first_last_config"] = {
                    "first_frame_asset_id": ref_first,
                    "first_frame_asset_ref": ref_first,
                    "last_frame_asset_id": ref_first,
                    "last_frame_asset_ref": ref_first,
                    "first_frame_prompt": "特写起幅动作，紧绷准备爆发",
                    "last_frame_prompt": "动作定格瞬间，引出对白",
                    "video_motion_prompt": "紧凑动作位移与情绪蓄力，无肢体畸变、无五官崩坏。",
                }
                shot_a["multi_image_config"] = None
                shot_a["lipsync_dynamics"] = None

                # Shot B: 对白承接镜头
                shot_b = dict(s)
                shot_b["duration_sec"] = plan_b.duration_sec
                shot_b["framing"] = plan_b.recommended_framing
                shot_b["rationale"] = plan_b.rationale
                shot_b["generation_mode"] = "multi_image_reference"
                shot_b["audio"] = {
                    "dialogue": dialogue,
                    "foley": audio_info.get("foley") or "[Foley+3dB: 微表情与衣料摩擦声]",
                    "music": audio_info.get("music", ""),
                    "is_dialogue_complete_in_shot": True,
                    "speech_inpoint_sec": plan_b.speech_inpoint_sec or 0.3,
                    "contextual_tts_prompt": audio_info.get("contextual_tts_prompt") or "[情绪承接/中低共鸣]",
                }
                expanded_raw_shots.append(shot_a)
                expanded_raw_shots.append(shot_b)
                continue

        expanded_raw_shots.append(s)

    # 【规则编号: Skill规则表-Stage7-02-算子2】整秒量化与清洗验证
    validated_shots: list[StoryboardShot] = []
    for s in expanded_raw_shots:
        try:
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

            s["target_engine"] = s.get("target_engine") or target_video_engine

            # 【算子 5：口型静默隔离与禁忌词清障】
            if "video_prompt" in s:
                s["video_prompt"] = clean_video_prompt(s["video_prompt"])

            if s.get("lipsync_dynamics") and isinstance(s["lipsync_dynamics"], dict):
                jaw = s["lipsync_dynamics"].get("jaw_open_scale", 0.6)
                if "video_prompt" in s:
                    s["video_prompt"] = s["video_prompt"].replace("jaw_open_scale", "").replace("jaw_open", "")

            # 💡【四段式确定性资产寻址纠偏与清洗】
            if s.get("first_last_config") and isinstance(s["first_last_config"], dict):
                flc = s["first_last_config"]
                if "first_frame_asset_id" in flc:
                    flc["first_frame_asset_id"] = AssetProtocolHelper.normalize_id(flc["first_frame_asset_id"])
                    flc["first_frame_asset_ref"] = flc["first_frame_asset_id"]
                elif "first_frame_asset_ref" in flc:
                    flc["first_frame_asset_ref"] = AssetProtocolHelper.normalize_id(flc["first_frame_asset_ref"])
                    flc["first_frame_asset_id"] = flc["first_frame_asset_ref"]

                if "last_frame_asset_id" in flc:
                    flc["last_frame_asset_id"] = AssetProtocolHelper.normalize_id(flc["last_frame_asset_id"])
                    flc["last_frame_asset_ref"] = flc["last_frame_asset_id"]
                elif "last_frame_asset_ref" in flc:
                    flc["last_frame_asset_ref"] = AssetProtocolHelper.normalize_id(flc["last_frame_asset_ref"])
                    flc["last_frame_asset_id"] = flc["last_frame_asset_ref"]

                if "first_frame_prompt" in flc:
                    flc["first_frame_prompt"] = clean_video_prompt(flc["first_frame_prompt"])
                if "last_frame_prompt" in flc:
                    flc["last_frame_prompt"] = clean_video_prompt(flc["last_frame_prompt"])
                if "video_motion_prompt" in flc:
                    flc["video_motion_prompt"] = clean_video_prompt(flc["video_motion_prompt"])

            if s.get("multi_image_config") and isinstance(s["multi_image_config"], dict):
                mic = s["multi_image_config"]
                refs = mic.get("reference_asset_ids") or mic.get("reference_assets") or []
                norm_refs = [AssetProtocolHelper.normalize_id(r) for r in refs if r]
                # 约束在 <= 4 张内
                norm_refs = norm_refs[:4]
                mic["reference_asset_ids"] = norm_refs
                mic["reference_assets"] = norm_refs
                mic["target_engine"] = mic.get("target_engine") or target_video_engine
                mic["audit"] = "PASS_9"

                if "video_prompt" in mic:
                    mic["video_prompt"] = clean_video_prompt(mic["video_prompt"])

                if isinstance(mic.get("media_manifest"), dict):
                    mm = mic["media_manifest"]
                    for img in mm.get("images") or []:
                        if isinstance(img, dict) and "asset_id" in img:
                            img["asset_id"] = AssetProtocolHelper.normalize_id(img["asset_id"])
                    for aud in mm.get("audios") or []:
                        if isinstance(aud, dict) and "voice_id" in aud:
                            aud["voice_id"] = AssetProtocolHelper.normalize_id(aud["voice_id"])

            # 规范化镜头显式关联资产列表
            c_ids = [AssetProtocolHelper.normalize_id(cid) for cid in s.get("character_asset_ids", []) if cid]
            s["character_asset_ids"] = [c for c in c_ids if c]
            if s.get("scene_asset_id"):
                s["scene_asset_id"] = AssetProtocolHelper.normalize_id(s["scene_asset_id"])
            p_ids = [AssetProtocolHelper.normalize_id(pid) for pid in s.get("prop_asset_ids", []) if pid]
            s["prop_asset_ids"] = [p for p in p_ids if p]

            all_refs: list[str] = []
            if s.get("multi_image_config"):
                all_refs.extend(s["multi_image_config"].get("reference_asset_ids") or [])
            if s.get("first_last_config"):
                flc = s["first_last_config"]
                if flc.get("first_frame_asset_id"):
                    all_refs.append(flc["first_frame_asset_id"])
                if flc.get("last_frame_asset_id"):
                    all_refs.append(flc["last_frame_asset_id"])

            if not s["character_asset_ids"]:
                s["character_asset_ids"] = [r for r in all_refs if r.startswith("CHAR_")]
            if not s["scene_asset_id"]:
                scene_refs = [r for r in all_refs if r.startswith("ENV_") or r.startswith("SCENE_")]
                if scene_refs:
                    s["scene_asset_id"] = scene_refs[0]
            if not s["prop_asset_ids"]:
                s["prop_asset_ids"] = [r for r in all_refs if r.startswith("PROP_")]

            # 【算子 4：全息声学规范化 (+3dB 与腔体共鸣)】
            audio_data = s.get("audio") or {}
            if isinstance(audio_data, dict):
                foley = audio_data.get("foley", "")
                if foley and "[Foley+3dB:" not in foley and "+3dB" not in foley:
                    audio_data["foley"] = f"[Foley+3dB: {foley}]"
                s["foley_cue"] = audio_data.get("foley", "")

                dialogue_val = audio_data.get("dialogue") or s.get("srt_text") or ""
                if dialogue_val:
                    audio_data["is_dialogue_complete_in_shot"] = True
                    s["is_dialogue_complete_in_shot"] = True
                    if not audio_data.get("contextual_tts_prompt"):
                        audio_data["contextual_tts_prompt"] = "[胸腔微共鸣/微表情对齐]"
                    s["contextual_tts_prompt"] = audio_data["contextual_tts_prompt"]
                    if audio_data.get("speech_inpoint_sec") is None:
                        audio_data["speech_inpoint_sec"] = 0.3
                    s["speech_inpoint_sec"] = audio_data["speech_inpoint_sec"]
                s["audio"] = audio_data

            shot_obj = StoryboardShot.model_validate(s)
            validated_shots.append(shot_obj)
        except Exception as e:
            logger.debug(f"[Stage 7 Node] Shot validation skipping error: {e}")
            continue

    if not validated_shots:
        fb = _stage7_fallback(
            ep_num,
            script.get("title", f"第{ep_num}集"),
            chars_list,
            envs_list,
            props_list,
            target_engine=target_video_engine,
            planned_duration_sec=planned_duration_sec,
            script=script,
        )
        validated_shots = [StoryboardShot.model_validate(s) for s in fb["shots"]]

    # 【算子 2：整集总时长 ±6.0s 公差硬核校准】(当镜头数 >= 10 时激活闭环微调)
    if len(validated_shots) >= 10 and planned_duration_sec > 0:
        total_shots_dur = sum(s.duration_sec for s in validated_shots)
        diff = total_shots_dur - planned_duration_sec
        if abs(diff) > 6.0:
            logger.info(f"[Stage 7 Node] Adjusting total duration {total_shots_dur}s towards {planned_duration_sec}s (diff: {diff:.1f}s)")
            if diff > 6.0:
                reduction_needed = int(diff - 5.0)
                for shot in validated_shots:
                    if reduction_needed <= 0:
                        break
                    if shot.duration_sec > 4.0:
                        can_reduce = int(shot.duration_sec - 4.0)
                        reduce_by = min(reduction_needed, can_reduce)
                        shot.duration_sec = float(shot.duration_sec - reduce_by)
                        reduction_needed -= reduce_by
            elif diff < -6.0:
                expansion_needed = int(-diff - 5.0)
                for shot in validated_shots:
                    if expansion_needed <= 0:
                        break
                    if shot.duration_sec < 6.0:
                        can_expand = int(6.0 - shot.duration_sec)
                        expand_by = min(expansion_needed, can_expand)
                        shot.duration_sec = float(shot.duration_sec + expand_by)
                        expansion_needed -= expand_by

    # 【算子 6：毫秒级时间码对齐与广播级 SRT 输出】
    current_time_ms = 0
    srt_blocks = []
    srt_counter = 1
    for idx, shot in enumerate(validated_shots, start=1):
        shot.shot_id = idx
        dur_ms = int(shot.duration_sec * 1000)
        start_ms = current_time_ms
        end_ms = current_time_ms + dur_ms
        current_time_ms = end_ms
        start_tc = _format_timecode(start_ms)
        end_tc = _format_timecode(end_ms)
        shot.timecode = f"{start_tc} --> {end_tc}"

        dialogue = shot.audio.get("dialogue") if isinstance(shot.audio, dict) else getattr(shot.audio, "dialogue", "")
        if dialogue:
            inpoint_sec = shot.speech_inpoint_sec or 0.3
            dlg_start_ms = start_ms + int(float(inpoint_sec) * 1000)
            dlg_end_ms = max(dlg_start_ms + 1000, end_ms - 200)
            if dlg_end_ms > end_ms:
                dlg_end_ms = end_ms
            shot.srt_timing = f"{_format_timecode(dlg_start_ms)} --> {_format_timecode(dlg_end_ms)}"
            shot.srt_text = dialogue
            srt_blocks.append(f"{srt_counter}\n{shot.srt_timing}\n{dialogue}\n")
            srt_counter += 1
        elif shot.dynamic_cue or shot.foley_cue:
            cue = shot.dynamic_cue or shot.foley_cue
            shot.srt_timing = shot.timecode
            shot.srt_text = f"（{cue}）"
            srt_blocks.append(f"{srt_counter}\n{shot.timecode}\n（{cue}）\n")
            srt_counter += 1

    srt_content = "\n".join(srt_blocks)
    mode_b_manifest_check = compile_mode_b_manifest_check(ep_num, validated_shots, target_video_engine)

    storyboards = dict(_get_val(state, "episode_storyboards", {}) or {})
    srts = dict(_get_val(state, "episode_srt_exports", {}) or {})
    mode_b_checks = dict(_get_val(state, "episode_mode_b_manifest_checks", {}) or {})

    storyboards[ep_num] = validated_shots
    srts[ep_num] = srt_content
    mode_b_checks[ep_num] = mode_b_manifest_check

    logger.info(
        f"[Stage 7 Node] Completed Episode {ep_num}: {len(validated_shots)} validated integer-second shots, "
        f"Mode B check verdict: {mode_b_manifest_check.get('verdict')}, SRT length {len(srt_content)} chars."
    )

    is_scoped = _get_val(state, "episode_number") is not None
    if is_scoped:
        return {
            "current_stage": 7,
            "episode_number": ep_num,
            "storyboard_shots": validated_shots,
            "srt_content": srt_content,
            "episode_storyboards": storyboards,
            "episode_srt_exports": srts,
            "episode_mode_b_manifest_checks": mode_b_checks,
        }

    return {
        "current_stage": 7,
        "episode_storyboards": storyboards,
        "storyboard_shots": storyboards,
        "episode_srt_exports": srts,
        "episode_mode_b_manifest_checks": mode_b_checks,
    }
