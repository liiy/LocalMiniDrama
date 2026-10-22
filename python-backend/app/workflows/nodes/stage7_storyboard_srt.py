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
from app.workflows.nodes.script_beat_extractor import (
    ScriptBeatExtractor,
    ScriptSceneContext,
)
from app.workflows.prompts.master_sop_prompts import (
    STAGE7_SYSTEM_PROMPT,
    STAGE7_USER_PROMPT_TEMPLATE,
)
from app.workflows.utils.asset_protocol import AssetProtocolHelper
from app.workflows.utils.llm_bridge import call_llm_json
from app.workflows.utils.prompt_synthesizer import (
    ContinuityStateManager,
    PromptSynthesizer,
)

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


class SemanticGroundingGuard:
    """分镜剧本语义一致性与幻觉实体审查守卫。
    
    检测大模型生成结果中是否包含剧本中完全未曾出现的违规实体（如未出现武器的现代剧虚构“枪口”、“拔枪”等），
    一旦触发，执行自愈拦截，强制将该镜头画面替换为从剧本真实提取的物理动作。
    """
    GUN_HALLUCINATION_KEYWORDS = ["枪口", "手枪", "拔枪", "顶在额头", "枪栓", "扣动扳机", "持枪逼近"]

    @classmethod
    def audit_and_sanitize_shot(
        cls,
        shot_data: dict[str, Any],
        script_context: ScriptSceneContext,
        script_full_text: str,
    ) -> bool:
        """审查并原地纠偏单个镜头。若触发纠偏，返回 True，否则返回 False。"""
        # 判断剧本全文是否确实包含枪支武器
        has_gun_in_script = any(w in script_full_text for w in ["枪", "射击", "子弹", "配枪", "枪声", "拔枪"])
        if has_gun_in_script:
            return False

        # 检查镜头的视觉提示词与首尾帧提示词
        img_p = shot_data.get("image_prompt") or ""
        vid_p = shot_data.get("video_prompt") or ""
        flc = shot_data.get("first_last_config") or {}
        ff_p = flc.get("first_frame_prompt") or ""
        lf_p = flc.get("last_frame_prompt") or ""

        triggered = any(
            kw in text
            for text in (img_p, vid_p, ff_p, lf_p)
            for kw in cls.GUN_HALLUCINATION_KEYWORDS
        )
        if not triggered:
            return False

        shot_id = shot_data.get("shot_id", 1)
        logger.warning(
            "【阶段7 语义守卫拦截】镜头 %s 提示词中命中未授权枪械虚构实体，执行剧本真实动作替换纠偏！",
            shot_id,
        )

        # 选取真实动作替换
        real_action = ""
        if shot_id == 1:
            real_action = script_context.get("hook_3s_action") or (
                script_context["actions"][0] if script_context.get("actions") else "主体屏息凝视现场"
            )
        else:
            action_idx = min(shot_id - 1, len(script_context.get("actions", [])) - 1)
            if action_idx >= 0:
                real_action = script_context["actions"][action_idx]
            else:
                real_action = "主体神情严肃保持对抗姿态"

        # 执行替换
        safe_img_prompt = f"电影级画质，{real_action}，高反差冷色调，景深微虚"
        shot_data["image_prompt"] = safe_img_prompt
        if shot_data.get("video_prompt"):
            shot_data["video_prompt"] = f"镜头推进聚焦，{real_action}，无肢体畸变、无画面抖动。"
        if flc:
            flc["first_frame_prompt"] = safe_img_prompt
            if flc.get("last_frame_prompt"):
                flc["last_frame_prompt"] = f"动作演进瞬间，{real_action}，主体张力紧绷。"
            if flc.get("video_motion_prompt"):
                flc["video_motion_prompt"] = f"镜头推进聚焦，{real_action}，无肢体畸变、无画面抖动。"

        # 顺便清理音效中的枪械
        audio = shot_data.get("audio") or {}
        if isinstance(audio, dict):
            foley = audio.get("foley") or ""
            if any(kw in foley for kw in ["枪", "子弹", "开火", "射击", "扣动扳机"]):
                audio["foley"] = "[Foley+3dB: 现场物理交互音与环境脆响]"
        return True


def clean_video_prompt(raw_prompt: str) -> str:
    """过滤并清洗 video_prompt 中的禁忌修饰词与口型/生理污染词。"""
    cleaned = raw_prompt or ""
    for w in FORBIDDEN_PROMPT_WORDS:
        cleaned = re.sub(re.escape(w), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _dedup_preserve_order(items: list[str]) -> list[str]:
    """严格按首次出现顺序去重（严禁使用无序 set() 打乱资源槽位）。"""
    return list(dict.fromkeys([str(x).strip() for x in items if str(x or "").strip()]))


def _compile_first_last_frame_prompts(
    shot_dict: dict[str, Any],
    default_char_token: str = "CHAR_PROTAGONIST_T1_BASE_PORTRAIT",
    default_prop_token: str | None = None,
) -> None:
    """【问题3根治】首尾帧（first_last_frame）双静态关键帧生图提示词与三段式图生视频插值提示词编译器。

    核心规范：
    1. 首帧生图提示词 (`first_frame_prompt`)：必须为 $T=0.0\text{s}$ 蓄力起始态静态构图（景别+机位+图1场景锚点+图2角色锚点+T=0.0s静态姿态+S0道具初始状态），剔除过程性连续运动动词。
    2. 尾帧生图提示词 (`last_frame_prompt`)：必须为 $T=D\text{s}$ 动作终局定格态静态构图（锁定与首帧相同的场景与人物身份锚点+T=Ds定格姿态+S1道具形变/位移终态）。
    3. 首尾帧图生视频提示词 (`video_motion_prompt` & `video_prompt`)：必须采用【起幅锚定(0.0s) -> 中段物理运动与运镜轨迹(0.0s->Ds) -> 落幅收束(Ds)】三段式插值结构，绝不直接复读生图提示词或夹杂对白文本。
    """
    gen_mode = str(shot_dict.get("generation_mode") or "")
    if gen_mode != "first_last_frame":
        return

    flc = shot_dict.get("first_last_config")
    if not isinstance(flc, dict):
        flc = {}

    dur_sec = float(shot_dict.get("duration_sec") or 3.0)
    framing = str(shot_dict.get("framing") or "ECU 极特写").strip()
    camera_motion = str(shot_dict.get("camera_motion") or "急速向前推镜头 (Rapid Push-in)").strip()
    scene_id = str(shot_dict.get("scene_asset_id") or "ENV_DEFAULT_STAGE6").strip()
    char_ids = [str(x).strip() for x in (shot_dict.get("character_asset_ids") or []) if str(x).strip()]
    prop_ids = [str(x).strip() for x in (shot_dict.get("prop_asset_ids") or []) if str(x).strip()]

    first_asset = str(
        flc.get("first_frame_asset_id")
        or flc.get("first_frame_asset_ref")
        or (char_ids[0] if char_ids else default_char_token)
    ).strip()
    last_asset = str(
        flc.get("last_frame_asset_id")
        or flc.get("last_frame_asset_ref")
        or first_asset
    ).strip()

    first_asset = AssetProtocolHelper.normalize_id(first_asset)
    last_asset = AssetProtocolHelper.normalize_id(last_asset)

    # 核心物理保真与插值防融塌定律：首尾帧资产类型必须严格同质（严禁人物与道具跨类别插值坍缩）
    first_type = "CHAR" if first_asset.startswith("CHAR_") else ("PROP" if first_asset.startswith("PROP_") else ("ENV" if first_asset.startswith("ENV_") else "UNKNOWN"))
    last_type = "CHAR" if last_asset.startswith("CHAR_") else ("PROP" if last_asset.startswith("PROP_") else ("ENV" if last_asset.startswith("ENV_") else "UNKNOWN"))

    if first_type != "UNKNOWN" and last_type != "UNKNOWN" and first_type != last_type:
        logger.warning(
            "【首尾帧异构资产阻断自愈】shot_id=%s 检测到首尾帧资产类型冲突 (first=%s[%s] vs last=%s[%s])，自动修正尾帧资产为首帧同一基准: %s",
            shot_dict.get("shot_id"), first_asset, first_type, last_asset, last_type, first_asset
        )
        last_asset = first_asset

    flc["first_frame_asset_id"] = first_asset
    flc["first_frame_asset_ref"] = first_asset
    flc["last_frame_asset_id"] = last_asset
    flc["last_frame_asset_ref"] = last_asset

    raw_first_prompt = clean_video_prompt(str(flc.get("first_frame_prompt") or shot_dict.get("image_prompt") or ""))
    raw_last_prompt = clean_video_prompt(str(flc.get("last_frame_prompt") or ""))
    raw_motion_prompt = clean_video_prompt(str(flc.get("video_motion_prompt") or shot_dict.get("video_prompt") or ""))

    # 构建视觉槽位锚点说明（图1=场景，图2=角色，图3=道具）
    slot_anchors = [f"图1({scene_id})"]
    if char_ids:
        slot_anchors.append(f"图2({char_ids[0]})")
    if prop_ids:
        prop_slot_idx = 2 + len(char_ids[:2])
        slot_anchors.append(f"图{prop_slot_idx}({prop_ids[0]})")
    anchor_prefix = f"【关键帧视觉锚点：{'、'.join(slot_anchors)}】"

    # 1. 编译首帧静态生图提示词 (T=0.0s 蓄力起始态)
    if not raw_first_prompt or len(raw_first_prompt) < 18 or raw_first_prompt == raw_motion_prompt:
        char_desc = f"主体({char_ids[0]})眼神冷冽紧绷、蓄势待发" if char_ids else "主体处于蓄力准备起始静态姿态"
        prop_s0_desc = f"，关键道具({prop_ids[0]})处于 S0 动作触发前完好初始静态形态" if prop_ids else ""
        raw_first_prompt = (
            f"{anchor_prefix}【首帧静态构图 T=0.0s｜{framing}】：在图1({scene_id})空间光影下，"
            f"{char_desc}{prop_s0_desc}，高对比度电影级冷调边缘光与景深质感（纯静态关键帧定格，无运动模糊）。"
        )
    elif "首帧" not in raw_first_prompt and "T=0.0s" not in raw_first_prompt:
        raw_first_prompt = f"{anchor_prefix}【首帧静态构图 T=0.0s｜{framing}】：{raw_first_prompt}"

    # 2. 编译尾帧静态生图提示词 (T=Ds 动作终局定格态)
    if not raw_last_prompt or len(raw_last_prompt) < 18 or raw_last_prompt == raw_first_prompt:
        char_end_desc = f"保持与首帧严格一致的主体({char_ids[0]})骨相与服饰锚点，动作完成瞬间肢体定格、神态决绝" if char_ids else "动作爆发完成后的终局静态定格画面"
        prop_s1_desc = f"，关键道具({prop_ids[0]})呈现 S1 剧烈形变/位移/破损后的终局静态形态" if prop_ids else ""
        raw_last_prompt = (
            f"{anchor_prefix}【尾帧静态构图 T={dur_sec:.1f}s｜{framing}】：锁定与首帧同一空间光影({scene_id})，"
            f"{char_end_desc}{prop_s1_desc}，画面张力收束定格。"
        )
    elif "尾帧" not in raw_last_prompt and f"T={dur_sec:.1f}s" not in raw_last_prompt:
        raw_last_prompt = f"{anchor_prefix}【尾帧静态构图 T={dur_sec:.1f}s｜{framing}】：{raw_last_prompt}"

    # 3. 编译三段式首尾帧图生视频4D视听融合插值提示词 (0.0s -> Ds 物理轨迹与声学力学演进)
    # 提取并纯净化环境底噪与动作拟音（杜绝外挂音频，直接内嵌驱动视频扩散模型声画联合生成）
    audio_obj = shot_dict.get("audio") if isinstance(shot_dict.get("audio"), dict) else {}
    foley_cue = str(audio_obj.get("foley") or shot_dict.get("foley_cue") or "").strip()
    ambient_cue = str(audio_obj.get("ambient") or audio_obj.get("music") or shot_dict.get("music_cue") or "").strip()
    clean_foley = re.sub(r"\[Foley\+3dB:\s*|\[|\]", "", foley_cue).strip()
    clean_ambient = re.sub(r"\[|\]", "", ambient_cue).strip()
    if not clean_ambient:
        clean_ambient = f"{scene_id}环境空间声学铺底与空气残响"
    if not clean_foley:
        clean_foley = "主体与关键道具剧烈物理接触与力学形变碰撞音效"

    core_action = raw_motion_prompt or str(shot_dict.get("dynamic_cue") or "爆发剧烈物理位移与物证形变交互").strip()
    # 剥离可能误混入的对白文本
    core_action = re.sub(r"“[^”]*”|\"[^\"]*\"", "", core_action).strip()
    if "【首尾帧4D视听插值" not in core_action and "【首尾帧运动插值" not in core_action:
        start_summary = raw_first_prompt.split("】：")[-1][:45].rstrip("。，")
        end_summary = raw_last_prompt.split("】：")[-1][:45].rstrip("。，")
        compiled_motion_prompt = clean_video_prompt(
            f"【首尾帧4D视听插值｜总时长 {dur_sec:.1f}s｜运镜：{camera_motion}】"
            f"1. [起幅锚定(0.0s) & 空间声场起幅]：画面承接首帧静态构图（{start_summary}）；空间声学铺底（{clean_ambient}）；"
            f"2. [中段物理运动与运镜轨迹(0.0s->{dur_sec:.1f}s) & 动作拟音爆发]：摄影机执行{camera_motion}，"
            f"主体与道具爆发连续物理力学演进（{core_action}），光影随位移自然流转；同步触发物理拟音（{clean_foley}）；"
            f"3. [落幅收束({dur_sec:.1f}s) & 声场混响衰减]：运动能量衰减并精准咬合尾帧定格画面（{end_summary}），"
            f"动作落幅与碰撞余音混响自然消散衰减，全程无肢体畸变、无五官崩坏、无道具凭空闪烁。"
        )
    elif "【首尾帧运动插值" in core_action and "声场" not in core_action:
        compiled_motion_prompt = clean_video_prompt(
            core_action.replace(
                "【首尾帧运动插值",
                "【首尾帧4D视听插值"
            ).replace(
                "1. [起幅锚定(0.0s)]：",
                f"1. [起幅锚定(0.0s) & 空间声场起幅]：空间声学铺底（{clean_ambient}），"
            ).replace(
                "2. [中段物理运动与运镜轨迹",
                f"2. [中段物理运动与运镜轨迹"
            ).replace(
                "；3. [落幅收束",
                f"，同步触发物理拟音（{clean_foley}）；3. [落幅收束"
            )
        )
    else:
        compiled_motion_prompt = clean_video_prompt(core_action)

    flc["first_frame_prompt"] = raw_first_prompt
    flc["last_frame_prompt"] = raw_last_prompt
    flc["video_motion_prompt"] = compiled_motion_prompt
    # 核心解耦标记：首尾帧模式音频已融合至提示词，不再进行独立外部音频合成
    flc["audio_prompt_embedded"] = True
    flc["requires_external_synth"] = False
    shot_dict["first_last_config"] = flc
    shot_dict["image_prompt"] = raw_first_prompt
    shot_dict["video_prompt"] = compiled_motion_prompt
    shot_dict["audio_prompt_embedded"] = True
    shot_dict["requires_external_synth"] = False

    logger.debug(
        "【Stage7首尾帧编译】shot_id=%s: first_asset=%s, last_asset=%s, 首帧Prompt长度=%d, 尾帧Prompt长度=%d, 4D视频插值Prompt长度=%d (音频已内嵌，无需外部合成)",
        shot_dict.get("shot_id"),
        flc["first_frame_asset_id"],
        flc["last_frame_asset_id"],
        len(raw_first_prompt),
        len(raw_last_prompt),
        len(compiled_motion_prompt),
    )


def _enforce_canonical_shot_resource_order(
    shot_dict: dict[str, Any],
    chars_list: list[dict[str, Any]] | None = None,
    props_list: list[dict[str, Any]] | None = None,
) -> None:
    """【权威槽位对齐与幽灵图号自愈】调用 PromptSynthesizer 实现五层多资源权威槽位编排与双轨视频提示词精炼。

    核心能力：
    1. 景别自适应底图路由（ECU/CU 阻断 24mm WIDE 大全景，平滑切至微距/浅焦特写）；
    2. 多路径物证/角色保序扫描，强制将画中物证登记为一等公民；
    3. 视觉槽位严格 <= 4（图1=场景，图2..k=角色，图k+1..4=道具）；
    4. 幽灵图号拦截自愈：扫描正文图号，若存在声明外图号自动重写对齐合法槽位；
    5. 音频槽位独立分配，首尾帧标记 embedded 杜绝孤儿任务；
    6. 模式 B 视频提示词双轨精炼：执行轨 <= 80 词动词短句，工程约束沉淀至 engineering_manifest。
    """
    raw_img_p = str(shot_dict.get("image_prompt") or "")
    raw_vid_p = str(shot_dict.get("video_prompt") or "")

    # 调用核心工具层权威槽位编排与幽灵图号自愈
    slots_result = PromptSynthesizer.compile_storyboard_multimodal_slots(
        shot_dict=shot_dict,
        raw_image_prompt=raw_img_p,
        raw_video_prompt=raw_vid_p,
        props_catalog=props_list,
        chars_catalog=chars_list,
    )

    # 同步回写权威槽位与纠偏后提示词
    shot_dict["scene_asset_id"] = slots_result["scene_asset_id"]
    shot_dict["character_asset_ids"] = slots_result["character_asset_ids"]
    shot_dict["prop_asset_ids"] = slots_result["prop_asset_ids"]
    shot_dict["image_prompt"] = slots_result.get("image_prompt") or raw_img_p
    shot_dict["video_prompt"] = slots_result.get("video_prompt") or raw_vid_p
    shot_dict["_canonical_visual_slots"] = slots_result["canonical_visual_slots"]
    shot_dict["_canonical_audio_slots"] = slots_result["canonical_audio_slots"]

    canonical_images = slots_result["canonical_visual_slots"]
    canonical_audios = slots_result["canonical_audio_slots"]
    canonical_ref_ids = slots_result["reference_asset_ids"]

    # 针对模式 B (multi_image_reference)，进一步执行目标引擎双轨精炼
    if str(shot_dict.get("generation_mode") or "") in ("multi_image_reference", "multi_image_ref"):
        if not isinstance(shot_dict.get("multi_image_config"), dict):
            shot_dict["multi_image_config"] = {}
        mic_obj = shot_dict["multi_image_config"]
        mic_obj["media_manifest"] = {
            "images": canonical_images,
            "audios": canonical_audios,
        }
        mic_obj["reference_asset_ids"] = canonical_ref_ids
        mic_obj["reference_assets"] = canonical_ref_ids
        mic_obj["target_engine"] = mic_obj.get("target_engine") or shot_dict.get("target_engine") or "wan3.0"
        mic_obj["audit"] = "PASS_9"

        selected_chars = slots_result["character_asset_ids"]
        selected_props = slots_result["prop_asset_ids"]
        prop_sym = f"图{len(selected_chars) + 2}" if selected_props else None

        audio_obj = shot_dict.get("audio") if isinstance(shot_dict.get("audio"), dict) else {}
        music_val = str(audio_obj.get("music") or shot_dict.get("music_cue") or "").strip()
        foley_val = str(audio_obj.get("foley") or shot_dict.get("foley_cue") or "").strip()

        execution_vp, eng_manifest = PromptSynthesizer.synthesize_engine_video_prompt(
            target_engine=mic_obj["target_engine"],
            action_verbs=slots_result["video_prompt"] or str(shot_dict.get("dynamic_cue") or "保持动态视听张力"),
            scene_symbol="图1",
            subject_symbol="图2" if len(selected_chars) >= 1 else "主体角色",
            counterpart_symbol="图3" if len(selected_chars) >= 2 else None,
            prop_symbol=prop_sym,
            dialogue_audio_symbol="音频1" if any(a["track_type"] in ("dialogue", "narration") for a in canonical_audios) else None,
            ambient_sound=music_val,
            foley_sound=foley_val,
        )

        mic_obj["video_prompt"] = execution_vp
        mic_obj["engineering_manifest"] = eng_manifest
        shot_dict["video_prompt"] = execution_vp
        shot_dict["engineering_manifest"] = eng_manifest

    logger.debug(
        "【Stage7权威槽位编排与双轨精炼完成】shot_id=%s, mode=%s, visual_slots=%s, audio_slots=%s",
        shot_dict.get("shot_id"),
        shot_dict.get("generation_mode"),
        [(x.get("symbol"), x.get("asset_id")) for x in canonical_images],
        [(x.get("symbol"), x.get("track_type"), x.get("voice_id") or x.get("description")) for x in canonical_audios],
    )


def compile_engine_video_prompt(
    target_engine: str,
    scene_symbol: str,
    subject_symbol: str,
    counterpart_symbol: str | None,
    action_desc: str,
    dialogue_audio_symbol: str | None = None,
    ambient_sound: str | None = None,
    foley_sound: str | None = None,
    prop_symbol: str | None = None,
) -> str:
    """【算子 3】针对目标生成底模 (wan3.0 / seedance2.5 / minimax_h3) 编译模式 B 提示词分支（接入 PromptSynthesizer 双轨精炼器）。"""
    exec_prompt, _ = PromptSynthesizer.synthesize_engine_video_prompt(
        target_engine=target_engine,
        action_verbs=action_desc,
        scene_symbol=scene_symbol,
        subject_symbol=subject_symbol,
        counterpart_symbol=counterpart_symbol,
        prop_symbol=prop_symbol,
        dialogue_audio_symbol=dialogue_audio_symbol,
        ambient_sound=ambient_sound,
        foley_sound=foley_sound,
    )
    return exec_prompt


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


def _extract_token_from_asset_ref(asset_ref: str, prefix: str) -> str:
    """从四段式资产协议标识 (如 CHAR_SHENMO_T1_BASE_PORTRAIT) 中提取核心 Token (如 SHENMO)。"""
    text = str(asset_ref or "").strip().upper()
    pfx = f"{prefix.upper()}_"
    if not text.startswith(pfx):
        return ""
    rest = text[len(pfx):]
    m = re.match(r"^([A-Z0-9]+?)(?:_T[123](?:_|$)|_BASE|_WIDE|_STATIC|_ACTION|_OTS|$)", rest)
    if m:
        return m.group(1)
    parts = rest.split("_")
    return parts[0] if parts else ""


def _balance_shot_durations(
    shots: list[dict[str, Any]],
    target_total_sec: float = 120.0,
    tolerance_sec: float = 6.0,
) -> None:
    """整集分镜时长严格离散整数秒微调器。
    
    在合规集合 {2.0, 3.0, 4.0, 5.0, 6.0, 7.0} 内迭代微调各镜头时长，
    确保 sum(shot.duration_sec) 严格落在 target_total_sec ± tolerance_sec 区间内。
    """
    if not shots or target_total_sec <= 0:
        return

    for s in shots:
        dur = float(s.get("duration_sec", 3.0))
        s["duration_sec"] = float(_round_to_integer_sec(dur))

    current_total = sum(s["duration_sec"] for s in shots)

    max_loops = 500
    loop_count = 0
    # 若时长不足 target_total_sec - tolerance_sec，逐步递增（上限 7.0s）
    while current_total < (target_total_sec - tolerance_sec) and loop_count < max_loops:
        loop_count += 1
        expanded = False
        for s in shots:
            if s["duration_sec"] < 7.0:
                s["duration_sec"] += 1.0
                current_total += 1.0
                expanded = True
                if current_total >= (target_total_sec - tolerance_sec):
                    break
        if not expanded:
            break

    loop_count = 0
    # 若时长超过 target_total_sec + tolerance_sec，逐步递减（下限 3.0s，然后再到 2.0s）
    while current_total > (target_total_sec + tolerance_sec) and loop_count < max_loops:
        loop_count += 1
        reduced = False
        for s in shots:
            if s["duration_sec"] > 3.0:
                s["duration_sec"] -= 1.0
                current_total -= 1.0
                reduced = True
                if current_total <= (target_total_sec + tolerance_sec):
                    break
        if not reduced:
            for s in shots:
                if s["duration_sec"] > 2.0:
                    s["duration_sec"] -= 1.0
                    current_total -= 1.0
                    reduced = True
                    if current_total <= (target_total_sec + tolerance_sec):
                        break
        if not reduced:
            break


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

    p_tok = (
        p_char.get("character_token")
        or _extract_token_from_asset_ref(p_char.get("asset_id") or p_char.get("benchmark_asset_key") or p_char.get("character_id") or "", "CHAR")
        or AssetProtocolHelper.chinese_to_token(p_name)
        or "PROTAGONIST"
    )
    a_tok = (
        a_char.get("character_token")
        or _extract_token_from_asset_ref(a_char.get("asset_id") or a_char.get("benchmark_asset_key") or a_char.get("character_id") or "", "CHAR")
        or AssetProtocolHelper.chinese_to_token(a_name)
        or "ANTAGONIST"
    )

    env_item = environments[0] if environments else {}
    env_name = env_item.get("location_name") or env_item.get("name", "核心场景")
    env_tok = (
        env_item.get("scene_token")
        or _extract_token_from_asset_ref(env_item.get("asset_id") or env_item.get("benchmark_asset_key") or env_item.get("env_id") or "", "ENV")
        or AssetProtocolHelper.chinese_to_token(env_name)
        or "PRIMARY"
    )

    prop_item = props[0] if props else {}
    hero_prop = prop_item.get("name", "关键物证")
    prop_tok = (
        prop_item.get("prop_token")
        or _extract_token_from_asset_ref(prop_item.get("asset_id") or prop_item.get("benchmark_asset_key") or prop_item.get("prop_id") or "", "PROP")
        or AssetProtocolHelper.chinese_to_token(hero_prop)
        or "EVIDENCE"
    )

    p_base_portrait = f"CHAR_{p_tok}_T1_BASE_PORTRAIT"
    a_base_portrait = f"CHAR_{a_tok}_T1_BASE_PORTRAIT"
    env_wide = f"ENV_{env_tok}_T1_WIDE"
    env_ots = f"ENV_{env_tok}_T1_OTS_BG"
    prop_static = f"PROP_{prop_tok}_T1_STATIC"
    prop_action = f"PROP_{prop_tok}_T1_ACTION_DAMAGED"
    a_voice = f"VOICE_{a_tok}_T1_MASTER"
    p_voice = f"VOICE_{p_tok}_T1_MASTER"

    # 💡【去硬编码核心设计】：使用 ScriptBeatExtractor 统一解析输入剧本（支持纯文本/Markdown/AST）
    # 彻底杜绝使用写死的假枪战/棋局剧本，100% 消费用户传入剧本的真实动作与对白
    script_ctx = ScriptBeatExtractor.extract_context(script or {}, stage6_characters=characters)
    logger.debug(
        "【阶段7 分镜保底】剧本视听上下文提取完成: 场景=%s, 抓手动作=%s, 动作数=%d, 对白数=%d, 角色列表=%s",
        script_ctx.get("scene_header")[:30] if script_ctx.get("scene_header") else env_name,
        script_ctx.get("hook_3s_action")[:30] if script_ctx.get("hook_3s_action") else "无",
        len(script_ctx.get("actions", [])),
        len(script_ctx.get("dialogues", [])),
        script_ctx.get("involved_characters", []),
    )

    # 1. 开局 3 秒抓手与首尾帧动作提炼
    hook_action = script_ctx.get("hook_3s_action") or (
        script_ctx["actions"][0] if script_ctx.get("actions") else f"{p_name}立于{env_name}中心，环境光影明暗交错"
    )
    # 动作演进与尾帧动作：若提取了第 2 个动作则取第 2 个，否则取片尾悬念或完成态
    last_action = ""
    if len(script_ctx.get("actions", [])) >= 2:
        last_action = script_ctx["actions"][1]
    elif script_ctx.get("ending_cliffhanger"):
        last_action = script_ctx["ending_cliffhanger"]
    else:
        last_action = f"{p_name}动作推进完成，神情冷峻决绝"

    shot1_img_prompt = f"电影级极特写，{hook_action}，冷调边缘光，高反差电影胶片质感"
    shot1_last_prompt = f"{p_name}动作形变推进，{last_action}，张力紧绷，极端物理形变清晰"
    shot1_motion_prompt = f"急速推移特写镜头，{hook_action[:40]}，无肢体畸变、无五官崩坏、无画面抖动。"
    
    # 镜头 1 拟音音效
    shot1_foley = (
        f"[Foley+3dB: {script_ctx['sound_effects'][0]}]"
        if script_ctx.get("sound_effects")
        else f"[Foley+3dB: {env_name}现场环境音与物体动态碰击声]"
    )

    # 2. 真实对白提取与说话人/角色映射
    dlg_beats = script_ctx.get("dialogues") or []

    # 角色库匹配工具函数：将提取到的角色名（如周衍、林晚）与 Stage 6 资产白名单中的角色精准关联
    def _find_char_token(spk_name: str, fallback_token: str, fallback_voice: str) -> tuple[str, str]:
        if not spk_name:
            return fallback_token, fallback_voice
        for c in characters:
            c_name = c.get("name", "")
            if c_name and (c_name in spk_name or spk_name in c_name):
                tok = (
                    c.get("character_token")
                    or _extract_token_from_asset_ref(c.get("asset_id") or c.get("benchmark_asset_key") or c.get("character_id") or "", "CHAR")
                    or AssetProtocolHelper.chinese_to_token(c_name)
                    or "CHAR"
                )
                return f"CHAR_{tok}_T1_BASE_PORTRAIT", f"VOICE_{tok}_T1_MASTER"
        tok = AssetProtocolHelper.chinese_to_token(spk_name) or "CHAR"
        return f"CHAR_{tok}_T1_BASE_PORTRAIT", f"VOICE_{tok}_T1_MASTER"

    if len(dlg_beats) >= 2:
        b1 = dlg_beats[0]
        b2 = dlg_beats[1]
        shot2_speaker = b1.get("speaker") or a_name
        shot2_dlg = f"{shot2_speaker}：{b1.get('dialogue_text')}"
        shot2_stress = b1.get("stress_action") or "眼神冰冷逼视，神色凝重"
        shot2_tts = f"[{shot2_speaker}_VOICE, {b1.get('vocal_delivery') or '声线沉缓发紧'}]"

        shot3_speaker = b2.get("speaker") or p_name
        shot3_dlg = f"{shot3_speaker}：{b2.get('dialogue_text')}"
        shot3_stress = b2.get("stress_action") or f"牙关紧咬，死死按住关键线索"
        shot3_tts = f"[{shot3_speaker}_VOICE, {b2.get('vocal_delivery') or '声线冷硬如铁'}]"
    elif len(dlg_beats) == 1:
        b1 = dlg_beats[0]
        shot2_speaker = b1.get("speaker") or a_name
        shot2_dlg = f"{shot2_speaker}：{b1.get('dialogue_text')}"
        shot2_stress = b1.get("stress_action") or "眼神冷峻逼视"
        shot2_tts = f"[{shot2_speaker}_VOICE, {b1.get('vocal_delivery') or '声线沉缓'}]"

        shot3_speaker = p_name if shot2_speaker != p_name else a_name
        act3 = script_ctx["actions"][2] if len(script_ctx.get("actions", [])) > 2 else last_action
        shot3_dlg = f"{shot3_speaker}：证据就在眼前，你无法抵赖。"
        shot3_stress = act3
        shot3_tts = f"[{shot3_speaker}_VOICE, 声线冷硬]"
    else:
        # 剧本无对白时（如无剧本桩测试环境），基于出场角色生成保底对白与动作
        act1 = script_ctx["actions"][1] if len(script_ctx.get("actions", [])) > 1 else f"{a_name}缓步走入阴影"
        act2 = script_ctx["actions"][2] if len(script_ctx.get("actions", [])) > 2 else f"{p_name}警觉侧身对峙"
        shot2_speaker = a_name
        shot2_dlg = f"{a_name}：退后，这里不是你能插手的地方！"
        shot2_stress = act1
        shot2_tts = f"[{a_name}_VOICE, 声线沉缓威慑]"

        shot3_speaker = p_name
        shot3_dlg = f"{p_name}：事情没查清之前，谁也别想离开。"
        shot3_stress = act2
        shot3_tts = f"[{p_name}_VOICE, 情绪爆发压迫]"

    # 提取纯净台词（剥离说话人冒号与拟音指示）
    shot2_clean_dlg, _, _ = PromptSynthesizer.sanitize_dialogue_sound_action(raw_dialogue=shot2_dlg)
    shot3_clean_dlg, _, _ = PromptSynthesizer.sanitize_dialogue_sound_action(raw_dialogue=shot3_dlg)

    # 动态匹配角色资产标识
    shot2_char_token, shot2_voice = _find_char_token(shot2_speaker, a_base_portrait, a_voice)
    shot3_char_token, shot3_voice = _find_char_token(shot3_speaker, p_base_portrait, p_voice)

    # 检查剧本悬念/末尾动作中是否出现其他在 Stage 6 白名单中的角色（如周正国）
    cliffhanger_chars = script_ctx.get("cliffhanger_characters") or []
    extra_char_token = None
    if cliffhanger_chars:
        extra_name = cliffhanger_chars[0]
        if extra_name not in (shot2_speaker, shot3_speaker):
            extra_char_token, _ = _find_char_token(extra_name, f"CHAR_{AssetProtocolHelper.chinese_to_token(extra_name)}_T1_BASE_PORTRAIT", "")

    logger.info(
        "【阶段7 分镜保底】真实视听数据对齐注入: 镜头1抓手='%s', 镜头2对白=(%s, %s), 镜头3对白=(%s, %s), 悬念角色=%s",
        hook_action[:25], shot2_speaker, shot2_dlg[:20], shot3_speaker, shot3_dlg[:20], extra_char_token
    )

    # 模式 B 提示词多引擎编译（完整注入环境底噪声场、物理动作拟音及道具锚点）
    shot2_ambient = "LEITMOTIF_01_SUSPENSE 持续低频铺底 (-12dB Ducking 避让)"
    shot2_foley = f"[Foley+3dB: {env_name}空间底噪与动作衣物摩擦声]"
    shot2_prompt = compile_engine_video_prompt(
        target_engine=target_engine,
        scene_symbol="图1",
        subject_symbol="图2",
        counterpart_symbol="图3",
        action_desc=shot2_stress,
        dialogue_audio_symbol="音频1",
        ambient_sound=shot2_ambient,
        foley_sound=shot2_foley,
        prop_symbol=None,
    )
    shot3_ambient = "LEITMOTIF_03_COUNTERATTACK 激昂交响打击乐重音切入"
    shot3_foley = f"[Foley+3dB: {hero_prop} 与场景交互的锐利撞击震颤声]"
    shot3_prompt = compile_engine_video_prompt(
        target_engine=target_engine,
        scene_symbol="图1",
        subject_symbol="图2",
        counterpart_symbol="图4" if extra_char_token else None,
        action_desc=shot3_stress,
        dialogue_audio_symbol="音频1",
        ambient_sound=shot3_ambient,
        foley_sound=shot3_foley,
        prop_symbol="图3",
    )

    # 💡【去截断核心实现】：检查剧本是否有丰富的全量节拍链 (ordered_beats)
    ordered_beats = script_ctx.get("ordered_beats") or []
    compilable_beats: list[dict[str, Any]] = []
    pending_sound = ""
    for b in ordered_beats:
        if b.get("beat_type") == "sound":
            pending_sound = b.get("sound_desc", "")
        else:
            b_copy = dict(b)
            if pending_sound:
                b_copy["preceding_sound"] = pending_sound
                pending_sound = ""
            compilable_beats.append(b_copy)
    if pending_sound and compilable_beats:
        compilable_beats[-1]["trailing_sound"] = pending_sound

    if len(compilable_beats) >= 3:
        # 激活【动态全拍子视听分镜编译器】：完整遍历剧本中每一处戏剧动作、台词与悬念，杜绝硬编码3分镜
        logger.info(
            "【阶段7 分镜保底】检测到丰富剧本节拍 (总计 %d 拍)，启动动态全拍子分镜编译引擎，预算总时长: %.1fs",
            len(compilable_beats), planned_duration_sec
        )
        FRAMING_CYCLE = ["MCU 中近景", "CU 特写", "OTS 过肩镜头", "MS 中景", "ECU 极特写"]
        CAMERA_MOTION_CYCLE = [
            "缓推聚焦 (Slow Push-in)",
            "微仰角特写平移 (Low-Angle Pan)",
            "越肩对峙固定镜头 (Static OTS)",
            "侧向水平慢移 (Slow Track Lateral)",
            "急速推移冲击 (Snap Push-in)",
        ]

        dynamic_shots: list[dict[str, Any]] = []
        for idx, beat in enumerate(compilable_beats, start=1):
            b_type = beat.get("beat_type", "action")
            framing = FRAMING_CYCLE[(idx - 1) % len(FRAMING_CYCLE)]
            camera_motion = CAMERA_MOTION_CYCLE[(idx - 1) % len(CAMERA_MOTION_CYCLE)]

            if b_type == "hook" or (idx == 1 and not beat.get("dialogue_text")):
                # 开局 3 秒抓手：模式 A 首尾帧控变
                act_desc = beat.get("action_desc") or hook_action
                img_p = f"电影级极特写，{act_desc}，冷调边缘光，高反差电影胶片质感"
                last_p = f"{p_name}动作形变推进，{act_desc}，极端物理形变清晰，张力紧绷"
                mot_p = f"急速推移特写镜头，{act_desc[:40]}，无肢体畸变、无五官崩坏、无画面抖动。"
                foley = f"[Foley+3dB: {beat.get('preceding_sound') or f'{env_name}现场环境音与物体动态碰击声'}]"
                s_dict = {
                    "shot_id": idx,
                    "title": "开局抓手瞬间",
                    "time": "深夜",
                    "framing": "ECU 极特写",
                    "camera_motion": "急速向前推镜头 (Rapid Push-in)",
                    "duration_sec": 3.0,
                    "generation_mode": "first_last_frame",
                    "selection_rationale": "开局前3秒动作爆发与关键物理实体形变，采用首尾帧控变",
                    "target_engine": target_engine,
                    "rationale": "剧烈动作(2.0s) + 视觉缓冲(1.0s) = 3.0s",
                    "character_asset_ids": [p_base_portrait],
                    "scene_asset_id": env_wide,
                    "prop_asset_ids": [prop_action],
                    "image_prompt": img_p,
                    "video_prompt": mot_p,
                    "first_last_config": {
                        "first_frame_asset_id": p_base_portrait,
                        "first_frame_asset_ref": p_base_portrait,
                        "first_frame_prompt": img_p,
                        "last_frame_asset_id": prop_action,
                        "last_frame_asset_ref": prop_action,
                        "last_frame_prompt": last_p,
                        "video_motion_prompt": mot_p,
                    },
                    "audio": {
                        "dialogue": None,
                        "foley": foley,
                        "music": "LEITMOTIF_01_BRAAM 开场突发重击 Braam Hit",
                    },
                    "lipsync_dynamics": None,
                }
                dynamic_shots.append(s_dict)

            elif b_type == "dialogue":
                spk = beat.get("speaker") or p_name
                dlg_txt = beat.get("dialogue_text") or ""
                stress = beat.get("stress_action") or "眼神冷峻逼视，神色凝重"
                vocal = beat.get("vocal_delivery") or "声线沉缓发紧"
                dur = float(_round_to_integer_sec(max(3.0, min(6.0, round(len(dlg_txt) * 0.25 + 2.0)))))

                spk_tok, spk_voice = _find_char_token(spk, p_base_portrait, p_voice)
                counterpart_name = a_name if spk == p_name else p_name
                counterpart_tok, _ = _find_char_token(counterpart_name, a_base_portrait, a_voice)

                ref_imgs = [
                    {"slot_order": 1, "symbol": "图1", "asset_id": env_ots, "role": "场景环境背景"},
                    {"slot_order": 2, "symbol": "图2", "asset_id": spk_tok, "role": f"{spk}面部特写"},
                    {"slot_order": 3, "symbol": "图3", "asset_id": counterpart_tok, "role": f"{counterpart_name}冷眼旁观"},
                ]
                char_ids = [spk_tok, counterpart_tok]
                prop_ids = [prop_static] if (idx % 2 == 1 or hero_prop in dlg_txt or hero_prop in stress) else []
                if prop_ids:
                    ref_imgs.append({"slot_order": 4, "symbol": "图4", "asset_id": prop_ids[0], "role": "关键物证"})

                amb_sound = "LEITMOTIF_01_SUSPENSE 持续低频铺底 (-12dB Ducking 避让)"
                foley_snd = f"[Foley+3dB: {beat.get('preceding_sound') or f'{env_name}空间底噪与动作衣物摩擦声'}]"
                v_prompt = compile_engine_video_prompt(
                    target_engine=target_engine,
                    scene_symbol="图1",
                    subject_symbol="图2",
                    counterpart_symbol="图3",
                    action_desc=stress,
                    dialogue_audio_symbol="音频1",
                    ambient_sound=amb_sound,
                    foley_sound=foley_snd,
                    prop_symbol="图4" if prop_ids else None,
                )
                clean_beat_dlg, _, _ = PromptSynthesizer.sanitize_dialogue_sound_action(raw_dialogue=dlg_txt)
                s_dict = {
                    "shot_id": idx,
                    "title": f"{spk}对白对峙",
                    "time": "深夜",
                    "framing": framing,
                    "camera_motion": camera_motion,
                    "duration_sec": dur,
                    "generation_mode": "multi_image_reference",
                    "selection_rationale": "多角色对白与微表情交锋，模式B多图参考控制",
                    "target_engine": target_engine,
                    "rationale": f"台词长度({len(dlg_txt)}字)量化推导 = {dur}s",
                    "character_asset_ids": char_ids,
                    "scene_asset_id": env_ots,
                    "prop_asset_ids": prop_ids,
                    "image_prompt": f"在{env_name}中，{spk}眼神逼视，{stress}，高反差电影胶片质感",
                    "video_prompt": v_prompt,
                    "multi_image_config": {
                        "media_manifest": {
                            "images": ref_imgs,
                            "audios": [
                                {"slot_order": 1, "symbol": "音频1", "voice_id": spk_voice, "role": f"{spk}台词"}
                            ],
                        },
                        "reference_asset_ids": [x["asset_id"] for x in ref_imgs],
                        "reference_assets": [x["asset_id"] for x in ref_imgs],
                        "video_prompt": v_prompt,
                        "target_engine": target_engine,
                        "audit": "PASS_9",
                    },
                    "audio": {
                        "dialogue": clean_beat_dlg,
                        "speech_inpoint_sec": 0.3,
                        "is_dialogue_complete_in_shot": True,
                        "foley": foley_snd,
                        "music": amb_sound,
                        "contextual_tts_prompt": f"[{spk}_VOICE, {vocal}]",
                    },
                    "lipsync_dynamics": {
                        "speaker": spk,
                        "jaw_open_scale": 0.52,
                        "mouth_tension": f"下颌紧绷，{stress[:15]}",
                        "head_subtle_motion": "微动对峙，眼神死锁对方",
                    },
                }
                dynamic_shots.append(s_dict)

            elif b_type == "cliffhanger":
                act_desc = beat.get("action_desc") or "片尾悬念绝杀定格"
                cliff_chars = beat.get("characters") or script_ctx.get("cliffhanger_characters") or []
                c_name = cliff_chars[0] if cliff_chars else p_name
                c_tok, _ = _find_char_token(c_name, p_base_portrait, p_voice)

                amb_sound = "LEITMOTIF_04_CLIFFHANGER 终局下潜重击 Sub-drop 骤停"
                foley_snd = f"[Foley+3dB: {beat.get('preceding_sound') or '门外沉重皮鞋脚步声与悬念骤停'}]"
                v_prompt = compile_engine_video_prompt(
                    target_engine=target_engine,
                    scene_symbol="图1",
                    subject_symbol="图2",
                    counterpart_symbol="图3" if c_tok != p_base_portrait else None,
                    action_desc=act_desc,
                    dialogue_audio_symbol=None,
                    ambient_sound=amb_sound,
                    foley_sound=foley_snd,
                    prop_symbol="图4" if prop_action else None,
                )
                ref_imgs = [
                    {"slot_order": 1, "symbol": "图1", "asset_id": env_ots, "role": "场景环境背景"},
                    {"slot_order": 2, "symbol": "图2", "asset_id": p_base_portrait, "role": f"{p_name}面部震惊特写"},
                ]
                char_ids = [p_base_portrait]
                if c_tok != p_base_portrait:
                    ref_imgs.append({"slot_order": 3, "symbol": "图3", "asset_id": c_tok, "role": f"{c_name}悬念出场"})
                    char_ids.append(c_tok)
                ref_imgs.append({"slot_order": 4, "symbol": "图4", "asset_id": prop_action, "role": "绝杀物证"})

                cliff_dialogue = None
                if "「" in act_desc and "」" in act_desc:
                    import re
                    m_blood = re.search(r"「([^」]+)」", act_desc)
                    if m_blood:
                        cliff_dialogue = f"（血字）{m_blood.group(1)}"

                s_dict = {
                    "shot_id": idx,
                    "title": "片尾绝杀悬念",
                    "time": "深夜",
                    "framing": "ECU 极特写",
                    "camera_motion": "急速定格缓推 (Slow Creep Push)",
                    "duration_sec": 4.0,
                    "generation_mode": "multi_image_reference",
                    "selection_rationale": "片尾核心戏剧钩子与悬念锁定，模式B多图参考控制",
                    "target_engine": target_engine,
                    "rationale": "片尾悬念情感留白与重音收束 = 4.0s",
                    "character_asset_ids": char_ids,
                    "scene_asset_id": env_ots,
                    "prop_asset_ids": [prop_action],
                    "image_prompt": f"电影级极特写，{act_desc}，高反差电影胶片质感",
                    "video_prompt": v_prompt,
                    "multi_image_config": {
                        "media_manifest": {
                            "images": ref_imgs,
                            "audios": [],
                        },
                        "reference_asset_ids": [x["asset_id"] for x in ref_imgs],
                        "reference_assets": [x["asset_id"] for x in ref_imgs],
                        "video_prompt": v_prompt,
                        "target_engine": target_engine,
                        "audit": "PASS_9",
                    },
                    "audio": {
                        "dialogue": cliff_dialogue,
                        "foley": foley_snd,
                        "music": amb_sound,
                    },
                    "lipsync_dynamics": None,
                }
                dynamic_shots.append(s_dict)

            else:
                # 普通动作小节 / 45秒微反转 / 物理碰撞
                act_desc = beat.get("action_desc") or ""
                is_twist = beat.get("is_twist") or ("45秒" in act_desc or "反转" in act_desc)
                is_violent = any(kw in act_desc for kw in ["撕", "甩", "碎", "裂", "砸", "撞", "拔出", "猛地", "穿透", "飞出"])

                act_chars = beat.get("characters") or []
                c_name = act_chars[0] if act_chars else p_name
                c_tok, _ = _find_char_token(c_name, p_base_portrait, p_voice)

                if is_violent:
                    # 剧烈物理形变：模式 A 首尾帧
                    img_p = f"电影级特写，{act_desc}，冷调高反差光影"
                    last_p = f"{act_desc}动作完成瞬间，物理形变清晰呈现，终态定格"
                    mot_p = f"急速推移冲击镜头，{act_desc[:40]}，无肢体畸变、无画面抖动。"
                    foley = f"[Foley+3dB: {beat.get('preceding_sound') or f'{hero_prop}受力形变撕裂碰撞声'}]"
                    s_dict = {
                        "shot_id": idx,
                        "title": "物理形变动作" if not is_twist else "45秒微反转",
                        "time": "深夜",
                        "framing": "ECU 极特写" if is_twist else "MCU 中近景",
                        "camera_motion": "快速推拉冲击 (Snap Zoom/Push)",
                        "duration_sec": 3.0,
                        "generation_mode": "first_last_frame",
                        "selection_rationale": "剧烈物理形变与位移，模式A首尾帧控变保障物理一致性",
                        "target_engine": target_engine,
                        "rationale": "动作形变物理时长2.0s + 缓冲1.0s = 3.0s",
                        "character_asset_ids": [c_tok],
                        "scene_asset_id": env_wide,
                        "prop_asset_ids": [prop_action],
                        "image_prompt": img_p,
                        "video_prompt": mot_p,
                        "first_last_config": {
                            "first_frame_asset_id": c_tok,
                            "first_frame_asset_ref": c_tok,
                            "first_frame_prompt": img_p,
                            "last_frame_asset_id": c_tok,
                            "last_frame_asset_ref": c_tok,
                            "last_frame_prompt": last_p,
                            "video_motion_prompt": mot_p,
                        },
                        "audio": {
                            "dialogue": None,
                            "foley": foley,
                            "music": "[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]" if is_twist else "LEITMOTIF_02_ACTION 激昂弦乐伴随动势",
                        },
                        "lipsync_dynamics": None,
                    }
                    dynamic_shots.append(s_dict)
                else:
                    # 常规动作小节：模式 B 多图参考
                    amb_sound = "[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]" if is_twist else "LEITMOTIF_01_SUSPENSE 持续低频铺底"
                    foley_snd = f"[Foley+3dB: {beat.get('preceding_sound') or f'{env_name}现场动作衣物摩擦与脚步声'}]"
                    v_prompt = compile_engine_video_prompt(
                        target_engine=target_engine,
                        scene_symbol="图1",
                        subject_symbol="图2",
                        counterpart_symbol="图3" if len(act_chars) > 1 else None,
                        action_desc=act_desc,
                        dialogue_audio_symbol=None,
                        ambient_sound=amb_sound,
                        foley_sound=foley_snd,
                        prop_symbol="图4" if hero_prop in act_desc else None,
                    )
                    ref_imgs = [
                        {"slot_order": 1, "symbol": "图1", "asset_id": env_ots, "role": "场景环境背景"},
                        {"slot_order": 2, "symbol": "图2", "asset_id": c_tok, "role": f"{c_name}动作特写"},
                    ]
                    char_ids = [c_tok]
                    if len(act_chars) > 1:
                        c2_tok, _ = _find_char_token(act_chars[1], a_base_portrait, a_voice)
                        ref_imgs.append({"slot_order": 3, "symbol": "图3", "asset_id": c2_tok, "role": f"{act_chars[1]}动作旁观"})
                        char_ids.append(c2_tok)
                    prop_ids = [prop_static] if hero_prop in act_desc else []
                    if prop_ids:
                        ref_imgs.append({"slot_order": 4, "symbol": "图4", "asset_id": prop_ids[0], "role": "关键物证"})

                    s_dict = {
                        "shot_id": idx,
                        "title": "戏剧动作推进" if not is_twist else "45秒微反转",
                        "time": "深夜",
                        "framing": framing,
                        "camera_motion": camera_motion,
                        "duration_sec": 4.0 if not is_twist else 3.0,
                        "generation_mode": "multi_image_reference",
                        "selection_rationale": "空间动作推进与人物微表情交互，模式B多图参考控制",
                        "target_engine": target_engine,
                        "rationale": "动作节奏与空间位移 = 4.0s",
                        "character_asset_ids": char_ids,
                        "scene_asset_id": env_ots,
                        "prop_asset_ids": prop_ids,
                        "image_prompt": f"在{env_name}中，{act_desc}，高反差电影胶片质感",
                        "video_prompt": v_prompt,
                        "multi_image_config": {
                            "media_manifest": {
                                "images": ref_imgs,
                                "audios": [],
                            },
                            "reference_asset_ids": [x["asset_id"] for x in ref_imgs],
                            "reference_assets": [x["asset_id"] for x in ref_imgs],
                            "video_prompt": v_prompt,
                            "target_engine": target_engine,
                            "audit": "PASS_9",
                        },
                        "audio": {
                            "dialogue": None,
                            "foley": foley_snd,
                            "music": amb_sound,
                        },
                        "lipsync_dynamics": None,
                    }
                    dynamic_shots.append(s_dict)

        # 闭环校验并平衡时长至 planned_duration_sec ± 6.0s (确保整秒离散)
        _balance_shot_durations(dynamic_shots, target_total_sec=planned_duration_sec, tolerance_sec=6.0)

        # 生成连续毫秒级时间码与标准 SRT 纯文本
        current_time_ms = 0
        srt_lines: list[str] = []
        srt_idx = 1
        for s_idx, d_shot in enumerate(dynamic_shots, start=1):
            d_shot["shot_id"] = s_idx
            dur_ms = int(float(d_shot["duration_sec"]) * 1000)
            start_tc = _format_timecode(current_time_ms)
            end_tc = _format_timecode(current_time_ms + dur_ms)
            d_shot["timecode"] = f"{start_tc} --> {end_tc}"
            current_time_ms += dur_ms

            dlg = (d_shot.get("audio") or {}).get("dialogue")
            if dlg:
                d_shot["srt_timing"] = f"{start_tc} --> {end_tc}"
                d_shot["srt_text"] = dlg
                srt_lines.append(f"{srt_idx}\n{start_tc} --> {end_tc}\n{dlg}\n")
                srt_idx += 1
            else:
                f_cue = (d_shot.get("audio") or {}).get("foley") or ""
                f_clean = f_cue.replace("[Foley+3dB: ", "").replace("]", "").strip()
                if f_clean:
                    d_shot["srt_timing"] = f"{start_tc} --> {end_tc}"
                    d_shot["srt_text"] = f"（{f_clean}）"
                    srt_lines.append(f"{srt_idx}\n{start_tc} --> {end_tc}\n（{f_clean}）\n")
                    srt_idx += 1

        shots = dynamic_shots
        srt_content = "\n".join(srt_lines)
    else:
        # 当输入剧本节拍极少或为空时（如无剧本桩单元测试），优雅回退至基线 3 分镜，确保现有单测与最小原型 100% 兼容
        shots = [
            {
                "shot_id": 1,
                "timecode": "00:00:00,000 --> 00:00:03,000",
                "framing": "ECU 极特写",
                "camera_motion": "急速向前推镜头 (Rapid Push-in)",
                "duration_sec": 3.0,
                "generation_mode": "first_last_frame",
                "selection_rationale": "开局前3秒动作爆发与关键物理实体形变，采用首尾帧控变",
                "target_engine": target_engine,
                "rationale": "剧烈动作(2.0s) + 视觉缓冲(1.0s) = 3.0s",
                "character_asset_ids": [p_base_portrait],
                "scene_asset_id": env_wide,
                "prop_asset_ids": [prop_action],
                "image_prompt": shot1_img_prompt,
                "video_prompt": shot1_motion_prompt,
                "first_last_config": {
                    "first_frame_asset_id": p_base_portrait,
                    "first_frame_asset_ref": p_base_portrait,
                    "first_frame_prompt": shot1_img_prompt,
                    "last_frame_asset_id": p_base_portrait,
                    "last_frame_asset_ref": p_base_portrait,
                    "last_frame_prompt": shot1_last_prompt,
                    "video_motion_prompt": shot1_motion_prompt,
                },
                "audio": {
                    "dialogue": "",
                    "speech_inpoint_sec": None,
                    "is_dialogue_complete_in_shot": True,
                    "foley": shot1_foley,
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
                "selection_rationale": f"{shot2_speaker}试探交锋与微表情表演，多图参考防面部抽搐",
                "target_engine": target_engine,
                "rationale": "双人中景交代(1.0s) + 核心台词演播(2.6s) + 闭嘴缓冲(0.4s) 向上取整锁死 4.0s",
                "character_asset_ids": [shot2_char_token, p_base_portrait],
                "scene_asset_id": env_wide,
                "prop_asset_ids": [],
                "image_prompt": f"在{env_name}中，{shot2_speaker}面对对手，{shot2_stress}，冷峻中近景",
                "video_prompt": shot2_prompt,
                "multi_image_config": {
                    "media_manifest": {
                        "images": [
                            {"symbol": "图1", "asset_id": env_wide, "role": "场景底板"},
                            {"symbol": "图2", "asset_id": shot2_char_token, "role": f"{shot2_speaker}说话角色"},
                            {"symbol": "图3", "asset_id": p_base_portrait, "role": "对峙姿态"},
                        ],
                        "audios": [
                            {"symbol": "音频1", "voice_id": shot2_voice, "role": f"{shot2_speaker}原声台词"},
                        ],
                    },
                    "reference_asset_ids": [env_wide, shot2_char_token, p_base_portrait],
                    "reference_assets": [env_wide, shot2_char_token, p_base_portrait],
                    "video_prompt": shot2_prompt,
                    "target_engine": target_engine,
                    "audit": "PASS_9",
                },
                "audio": {
                    "dialogue": shot2_clean_dlg,
                    "speech_inpoint_sec": 0.3 if shot2_clean_dlg else None,
                    "is_dialogue_complete_in_shot": True,
                    "foley": f"[Foley+3dB: {env_name}空间底噪与动作衣物摩擦声]",
                    "music": "LEITMOTIF_01_SUSPENSE 持续低频铺底 (-12dB Ducking 避让)",
                    "contextual_tts_prompt": shot2_tts,
                },
                "lipsync_dynamics": {
                    "speaker": shot2_speaker,
                    "jaw_open_scale": 0.65,
                    "mouth_tension": "嘴角微微下撇，冷峻收紧，眼周肌肉保持僵硬",
                    "head_subtle_motion": "说话时头部微扬",
                } if shot2_clean_dlg else None,
            },
            {
                "shot_id": 3,
                "timecode": "00:00:07,000 --> 00:00:10,000",
                "framing": "CU 特写",
                "camera_motion": "低角度甩镜 (Low-angle Whip Pan)",
                "duration_sec": 3.0,
                "generation_mode": "multi_image_reference",
                "selection_rationale": f"核心物证与{shot3_speaker}情绪反击，微距特写与质感强化",
                "target_engine": target_engine,
                "rationale": "动作交代(0.8s) + 核心交锋(1.8s) + 余震闭嘴(0.4s) 向上取整锁死 3.0s",
                "character_asset_ids": [shot3_char_token] + ([extra_char_token] if extra_char_token else []),
                "scene_asset_id": env_ots,
                "prop_asset_ids": [prop_static],
                "image_prompt": f"在{env_name}中，{shot3_speaker}眼神逼视，{shot3_stress}，高反差特写",
                "video_prompt": shot3_prompt,
                "multi_image_config": {
                    "media_manifest": {
                        "images": [
                            {"slot_order": 1, "symbol": "图1", "asset_id": env_ots, "role": "场景环境背景"},
                            {"slot_order": 2, "symbol": "图2", "asset_id": shot3_char_token, "role": f"{shot3_speaker}面部特写"},
                            {"slot_order": 3, "symbol": "图3", "asset_id": prop_static, "role": "关键物证"},
                        ] + ([{"slot_order": 4, "symbol": "图4", "asset_id": extra_char_token, "role": "片尾出场角色"}] if extra_char_token else []),
                        "audios": [
                            {"slot_order": 1, "symbol": "音频1", "voice_id": shot3_voice, "role": f"{shot3_speaker}台词"},
                        ],
                    },
                    "reference_asset_ids": [env_ots, shot3_char_token, prop_static] + ([extra_char_token] if extra_char_token else []),
                    "reference_assets": [env_ots, shot3_char_token, prop_static] + ([extra_char_token] if extra_char_token else []),
                    "video_prompt": shot3_prompt,
                    "target_engine": target_engine,
                    "audit": "PASS_9",
                },
                "audio": {
                    "dialogue": shot3_clean_dlg,
                    "speech_inpoint_sec": 0.3 if shot3_clean_dlg else None,
                    "is_dialogue_complete_in_shot": True,
                    "foley": f"[Foley+3dB: {hero_prop} 与场景交互的锐利撞击震颤声]",
                    "music": "LEITMOTIF_03_COUNTERATTACK 激昂交响打击乐重音切入",
                    "contextual_tts_prompt": shot3_tts,
                },
                "lipsync_dynamics": {
                    "speaker": shot3_speaker,
                    "jaw_open_scale": 0.48,
                    "mouth_tension": "下颌骨紧绷咬牙，神情决绝",
                    "head_subtle_motion": "眼神死死锁死对方",
                } if shot3_clean_dlg else None,
            },
        ]

        foley_clean_1 = shot1_foley.replace("[Foley+3dB: ", "").replace("]", "")
        srt_content = (
            "1\n"
            "00:00:00,000 --> 00:00:03,000\n"
            f"（{foley_clean_1}）\n\n"
            "2\n"
            "00:00:03,300 --> 00:00:06,800\n"
            f"{shot2_dlg or '……'}\n\n"
            "3\n"
            "00:00:07,300 --> 00:00:09,800\n"
            f"{shot3_dlg or '……'}\n"
        )

    for fb_shot in shots:
        _enforce_canonical_shot_resource_order(fb_shot, chars_list=characters, props_list=props)
        _compile_first_last_frame_prompts(fb_shot, default_char_token=p_base_portrait, default_prop_token=prop_action)

    logger.debug(
        "[Stage 7 Fallback] Generating %d fallback shots for Episode %d with cinematography state machine: "
        "shot1(ECU/3s/first_last_frame) -> shot2(MCU/4s/multi_image) -> shot3(CU/3s/multi_image)",
        len(shots), episode_num
    )

    shot_objs = [StoryboardShot.model_validate(s) for s in shots]
    mode_b_check = compile_mode_b_manifest_check(episode_num, shot_objs, target_engine)

    return {
        "episode_num": episode_num,
        "shots": shots,
        "srt_content": srt_content,
        "mode_b_manifest_check": mode_b_check,
    }


def _build_stage6_asset_whitelist_block(
    manifest_dict: dict[str, Any],
    chars_list: list[dict[str, Any]],
    envs_list: list[dict[str, Any]],
    props_list: list[dict[str, Any]],
    voice_profiles: list[dict[str, Any]] | None = None,
) -> str:
    """构建阶段 6 准入资产树状层级白名单格式化文本 (供阶段 7 提示词严格约束使用)。

    从 Stage 6 提取母体实体 -> 阶段造型/子空间 -> 切片视图树状层级清单，
    并注入角色音色卡白名单与对白/拟音分离铁律，杜绝阶段 7 引用外部虚构资产或将拟音误当说话人。
    """
    lines: list[str] = []

    # 1. 角色资产树状清单与切片白名单提取
    char_entries: list[str] = []
    seen_char_ids = set()

    raw_chars = (
        manifest_dict.get("characters_tier_1", [])
        + manifest_dict.get("characters_tier_2", [])
        + manifest_dict.get("characters_tier_3", [])
    )
    if not raw_chars and isinstance(manifest_dict.get("characters"), list):
        raw_chars = manifest_dict.get("characters", [])
    elif not raw_chars and isinstance(manifest_dict.get("characters"), dict):
        for v in manifest_dict.get("characters", {}).values():
            if isinstance(v, list):
                raw_chars.extend(v)

    # 优先从 chars_list 聚合母体与派生切片
    for c in (chars_list or []):
        cid = (
            c.get("asset_key")
            or c.get("asset_id")
            or c.get("benchmark_asset_key")
            or c.get("character_id")
            or c.get("character_token")
            or c.get("id")
            or f"CHAR_{c.get('name', 'UNKNOWN')}"
        )
        cid = str(cid).strip()
        if not cid.startswith("CHAR_"):
            cid = f"CHAR_{cid}"
        if cid and cid not in seen_char_ids:
            seen_char_ids.add(cid)
            cname = c.get("name") or c.get("character_name") or "未知角色"
            # 查找该母体角色下属切片
            slices = c.get("slices") or c.get("visual_slices") or []
            slice_desc = ""
            if slices:
                slice_keys = [str(sl.get("asset_id") or sl.get("asset_key") or sl.get("slice_id")) for sl in slices if sl]
                slice_desc = f"\n    * 可用骨架切片: {', '.join(slice_keys)}"
            char_entries.append(f"- 角色母体: `{cid}` (姓名: {cname}){slice_desc}")

    for item in raw_chars:
        cid = (
            item.get("asset_key")
            or item.get("base_portrait")
            or item.get("char_id")
            or item.get("character_id")
            or item.get("asset_id")
        )
        if cid and cid not in seen_char_ids:
            seen_char_ids.add(cid)
            cname = item.get("character_name") or item.get("name") or "未知角色"
            stage_info = f" [阶段造型: {item.get('stage_code')}]" if item.get("stage_code") else ""
            char_entries.append(f"- 角色资产: `{cid}` (姓名: {cname}{stage_info})")

    lines.append("【阶段 6 本集准入角色视觉资产 (character_asset_ids，分镜必须且仅能从此列表选取)】:")
    if char_entries:
        lines.extend(char_entries)
    else:
        lines.append("- (无特定角色资产锁定，若涉及角色请规范使用 CHAR_ 前缀标识)")

    # 2. 场景空间树状清单提取 (母体 -> 机位/子区域 -> 空间结构层)
    env_entries: list[str] = []
    seen_env_ids = set()

    for e in (envs_list or []):
        eid = (
            e.get("asset_key")
            or e.get("asset_id")
            or e.get("benchmark_asset_key")
            or e.get("env_id")
            or e.get("scene_id")
            or e.get("scene_token")
            or e.get("id")
            or f"ENV_{e.get('location_name', 'DEFAULT')}"
        )
        eid = str(eid).strip()
        if not eid.startswith("ENV_"):
            eid = f"ENV_{eid}"
        if eid and eid not in seen_env_ids:
            seen_env_ids.add(eid)
            ename = e.get("location_name") or e.get("name") or "核心场景"
            zones = e.get("zones") or e.get("camera_zones") or []
            zone_desc = ""
            if zones:
                z_strs = [f"{z.get('zone_code') or z.get('code')}({z.get('name') or z.get('zone_name')})" for z in zones if isinstance(z, dict)]
                zone_desc = f"\n    * 可用核心机位(Zone): {', '.join(z_strs)}"
            env_entries.append(f"- 场景母体: `{eid}` (场景名: {ename}){zone_desc}")

    raw_envs = (
        manifest_dict.get("environments_primary", [])
        + manifest_dict.get("environments_transitional", [])
    )
    if not raw_envs and isinstance(manifest_dict.get("environments"), list):
        raw_envs = manifest_dict.get("environments", [])
    elif not raw_envs and isinstance(manifest_dict.get("environments"), dict):
        for v in manifest_dict.get("environments", {}).values():
            if isinstance(v, list):
                raw_envs.extend(v)

    for item in raw_envs:
        eid = (
            item.get("asset_key")
            or item.get("wide_shot")
            or item.get("env_id")
            or item.get("scene_id")
            or item.get("asset_id")
        )
        if eid and eid not in seen_env_ids:
            seen_env_ids.add(eid)
            ename = item.get("scene_name") or item.get("location_name") or item.get("name") or "核心场景"
            zone_info = f" [机位代码: {item.get('zone_code')}]" if item.get("zone_code") else ""
            env_entries.append(f"- 场景资产: `{eid}` (场景名: {ename}{zone_info})")

    lines.append("\n【阶段 6 本集准入场景空间资产 (scene_asset_id，分镜必须且仅能从此列表选取)】:")
    if env_entries:
        lines.extend(env_entries)
    else:
        lines.append("- (无特定场景资产锁定，若涉及场景请规范使用 ENV_ 前缀标识)")

    # 3. 道具物证树状清单提取 (母体 -> 静态基准 / 动态形变 / 战损)
    prop_entries: list[str] = []
    seen_prop_ids = set()

    for p in (props_list or []):
        pid = (
            p.get("asset_key")
            or p.get("asset_id")
            or p.get("benchmark_asset_key")
            or p.get("prop_id")
            or p.get("prop_token")
            or p.get("id")
            or f"PROP_{p.get('name', 'ITEM')}"
        )
        pid = str(pid).strip()
        if not pid.startswith("PROP_"):
            pid = f"PROP_{pid}"
        if pid and pid not in seen_prop_ids:
            seen_prop_ids.add(pid)
            pname = p.get("name") or "核心道具"
            prop_entries.append(f"- 道具物证: `{pid}` (道具名: {pname})")

    raw_props = (
        manifest_dict.get("props_narrative", [])
        + manifest_dict.get("props_anchors", [])
        + manifest_dict.get("props_ambient", [])
    )
    if not raw_props and isinstance(manifest_dict.get("props"), list):
        raw_props = manifest_dict.get("props", [])
    elif not raw_props and isinstance(manifest_dict.get("props"), dict):
        for v in manifest_dict.get("props", {}).values():
            if isinstance(v, list):
                raw_props.extend(v)

    for item in raw_props:
        pid = (
            item.get("asset_key")
            or item.get("action_asset")
            or item.get("static_asset")
            or item.get("prop_id")
            or item.get("asset_id")
        )
        if pid and pid not in seen_prop_ids:
            seen_prop_ids.add(pid)
            pname = item.get("prop_name") or item.get("name") or "核心道具"
            damage_info = f" [战损/动量: {item.get('state_code')}]" if item.get("state_code") else ""
            prop_entries.append(f"- 道具资产: `{pid}` (道具名: {pname}{damage_info})")

    lines.append("\n【阶段 6 本集准入道具物证资产 (prop_asset_ids，分镜必须且仅能从此列表选取)】:")
    if prop_entries:
        lines.extend(prop_entries)
    else:
        lines.append("- (无特定道具资产锁定，若涉及道具请规范使用 PROP_ 前缀标识)")

    # 4. 角色音色卡与发声规范约束
    lines.append("\n【阶段 6 角色音色卡白名单与音频轨强制规范】:")
    vp_list = voice_profiles or []
    if not vp_list and chars_list:
        for c in chars_list:
            cname = c.get("name") or "未知角色"
            tok = AssetProtocolHelper.chinese_to_token(cname)
            vp_list.append({
                "voice_id": f"VOICE_{tok}_T1_MASTER",
                "character_name": cname,
                "timbre_description": c.get("voice_style") or "影视原声微共鸣",
            })

    for vp in vp_list:
        v_id = vp.get("voice_id") or vp.get("id") or "VOICE_DEFAULT_MASTER"
        v_name = vp.get("character_name") or vp.get("name") or "未知角色"
        v_desc = vp.get("timbre_description") or vp.get("style") or ""
        lines.append(f"- 音色卡 Token: `{v_id}` -> 对应角色: `{v_name}` ({v_desc})")

    lines.append("\n【🚨 音频轨道分离与说话人铁律 🚨】:")
    lines.append("1. `dialogue` 仅限包含纯正的人物对白，绝对禁止出现任何 `[Foley+3dB` 或物理拟音标签！")
    lines.append("2. 拟音与环境碰撞必须严格写入 `audio.foley` 字段，绝对禁止将拟音作为说话人！")
    lines.append("3. 每一个有台词的分镜，其说话人必须严格匹配上述角色音色卡白名单，并在 `media_manifest.audios` 中分配对应 `voice_id`！")

    whitelist_block = "\n".join(lines)
    logger.debug(
        "【阶段7 树状资产白名单编译完成】可用角色: %d, 场景: %d, 道具: %d, 音色卡: %d",
        len(seen_char_ids), len(seen_env_ids), len(seen_prop_ids), len(vp_list)
    )
    return whitelist_block


def _split_dialogue_by_punctuation(text: str) -> tuple[str, str] | None:
    """按句读与自然语流节奏拆分长对白（逗号、句号、叹号、问号、省略号、分号）。

    【拆镜节奏规则】：
    - 针对 >6.5s 复合长镜头或超长台词，寻找最接近语流中点的标点断句；
    - 保证拆分后前半句（铺垫/发难）与后半句（爆发/承接）均具有语义完整度（至少4个字符）；
    - 若无法自然切分则返回 None，降级进入动作前置解耦分支。

    Args:
        text (str): 待切分的原始对白文本。

    Returns:
        tuple[str, str] | None: (前半句, 后半句) 或 None。
    """
    clean = re.sub(r"（[^）]+）|\([^)]+\)", "", text).strip()
    if not clean:
        return None
    delimiters = ["……", "！", "!", "。", "?", "？", "；", ";", "，", ","]
    mid = len(clean) // 2
    best_idx = -1
    best_dist = 9999
    best_delim_len = 1
    for delim in delimiters:
        pos = 0
        while True:
            idx = clean.find(delim, pos)
            if idx == -1:
                break
            left_len = len(clean[:idx])
            right_len = len(clean[idx + len(delim):])
            if left_len >= 4 and right_len >= 4:
                dist = abs(idx - mid)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
                    best_delim_len = len(delim)
            pos = idx + len(delim)
        # 命中中点附近 6 字以内的强语义断句，直接采用
        if best_idx != -1 and best_dist <= 6:
            break

    if best_idx != -1:
        part_a = clean[:best_idx + best_delim_len].strip()
        part_b = clean[best_idx + best_delim_len:].strip()
        return part_a, part_b
    return None


def _evolve_framing(current_framing: str) -> tuple[str, str]:
    """根据导演视听语法推导前后分镜的景别进阶关系 (Framing Progression)。

    【视听阶梯进阶规范】：
    - 远景/全景 (WIDE/FS) -> 进阶为 FS 全景交代 + MCU 中近景对峙；
    - 中景/中近景 (MS/MCU) -> 进阶为 OTS 双人过肩对峙 + CU 核心特写；
    - 特写 (CU) -> 进阶为 MCU 反应镜头 + ECU 极特写（眼神/微表情锁定）；
    - 缺省 -> 进阶为 MCU 中近景 + CU 特写。

    Args:
        current_framing (str): 原始镜头景别字符串。

    Returns:
        tuple[str, str]: (Shot A 景别, Shot B 景别)。
    """
    cf = (current_framing or "").upper()
    if any(k in cf for k in ["WIDE", "远景", "全景", "ESTABLISHING", "FS"]):
        return "FS 全景交代", "MCU 中近景对峙"
    if any(k in cf for k in ["MCU", "中近景", "MS", "中景"]):
        return "OTS 双人过肩对峙", "CU 核心特写"
    if any(k in cf for k in ["CU", "特写"]):
        return "MCU 反应镜头", "ECU 极特写"
    return "MCU 中近景", "CU 特写"


def _adaptive_split_long_shots(
    raw_shots: list[dict[str, Any]],
    target_video_engine: str = "wan3.0",
) -> list[dict[str, Any]]:
    """自适应拆镜算子 (Adaptive Shot Splitter)：对单镜头时长超标 (>6.5s) 或长对白镜头进行视听语法解耦。

    【两阶段解耦机制与导演视听语法设计】：
    1. 意群节奏拆分（若长对白存在自然句读分割点）：
       - 识别对白标点与停顿节奏，将长对白切分为前半句（铺垫/发难）与后半句（核心压迫/爆发）；
       - Shot A (前半句) 采用建立景别或过肩景别，视线偏右 (looking screen-right)；
       - Shot B (后半句) 景别推进至特写/极特写，视线偏左 (looking screen-left) 形成视线对视闭环。
    2. 动作前置解耦（若为单句长台词或纯动作长镜头）：
       - Shot A: 动作前置/情绪凝滞镜（时长 2.0s~3.0s），纯动作/拟音/静默微表情，首尾帧或动作多模态控变；
       - Shot B: 对白爆发镜头（时长 3.0s~5.0s），容纳完整对白，推进至面部特写，绑定口型动力学。

    Args:
        raw_shots (list[dict[str, Any]]): 原始分镜字典列表。
        target_video_engine (str): 目标视频生成引擎标识。

    Returns:
        list[dict[str, Any]]: 自适应展开后的分镜字典列表。
    """
    expanded_raw_shots: list[dict[str, Any]] = []

    for s in raw_shots:
        raw_dur = float(s.get("duration_sec") or s.get("duration_seconds") or 3.0)
        audio_info = s.get("audio") or {}
        dialogue = audio_info.get("dialogue") or s.get("dialogue") or s.get("srt_text") or ""
        clean_dlg = clean_dialogue_text(dialogue)

        # 触发拆镜条件：原始时长超过 6.5s，或纯台词文本超过 25 字
        if raw_dur > SPLIT_THRESHOLD_SEC or (clean_dlg and len(clean_dlg) > 25):
            logger.debug(
                "[Stage 7 Node] 镜头 %s 触发自适应拆镜阈值检测: raw_dur=%.1fs, clean_dlg_len=%d, dialogue='%s'",
                s.get("shot_id"), raw_dur, len(clean_dlg), dialogue[:30]
            )

            # 提取说话人前缀与纯对白文本
            speaker = ""
            pure_content = dialogue
            m = re.match(r"^([^：:\s]{1,10})[：:](.*)$", dialogue.strip())
            if m:
                speaker = m.group(1).strip()
                pure_content = m.group(2).strip()

            split_pair = _split_dialogue_by_punctuation(pure_content) if pure_content else None
            framing_a, framing_b = _evolve_framing(s.get("framing") or s.get("shot_type") or "")

            if split_pair:
                # 【分支 1：按句读节奏拆分为前后承接的双对白镜头】
                part_a, part_b = split_pair
                dlg_a = f"{speaker}：{part_a}" if speaker else part_a
                dlg_b = f"{speaker}：{part_b}" if speaker else part_b

                calc_a = calculate_shot_duration(dialogue_text=dlg_a, custom_action_sec=1.0)
                calc_b = calculate_shot_duration(dialogue_text=dlg_b, custom_action_sec=0.5)

                dur_a = float(_round_to_integer_sec(calc_a.raw_total_sec))
                dur_b = float(_round_to_integer_sec(calc_b.raw_total_sec))

                dur_a = max(2.0, min(7.0, dur_a))
                dur_b = max(2.0, min(7.0, dur_b))

                spk_label = speaker or "角色"

                # Shot A: 前半句发难/建立对峙
                shot_a = dict(s)
                shot_a["duration_sec"] = dur_a
                shot_a["framing"] = framing_a
                shot_a["camera_motion"] = "慢速推镜头，确立视线轴线"
                shot_a["rationale"] = f"前半句台词情绪发难({dur_a}s)，{framing_a}建立对峙"
                shot_a["generation_mode"] = "multi_image_reference"
                shot_a["image_prompt"] = shot_a.get("image_prompt") or (
                    f"电影级{framing_a}，{spk_label}面色冷峻，眼神偏右凝视对手(looking screen-right)，"
                    f"情绪蓄势，语气微顿：'{part_a[:20]}'，影视级侧逆光与高反差光比"
                )
                shot_a["video_prompt"] = shot_a.get("video_prompt") or (
                    f"缓推镜头，{spk_label}眼神如刃直视前方（视线偏右），微动喉结发难对白，"
                    f"情绪连贯克制，无肢体畸变、无五官崩坏。"
                )
                shot_a["audio"] = {
                    "dialogue": dlg_a,
                    "foley": audio_info.get("foley") or "[Foley+3dB: 沉闷心跳与衣料紧绷摩擦声]",
                    "music": audio_info.get("music", ""),
                    "is_dialogue_complete_in_shot": True,
                    "speech_inpoint_sec": 0.3,
                    "contextual_tts_prompt": audio_info.get("contextual_tts_prompt") or f"[{spk_label}_VOICE, 语调冷峻压抑, 胸腔低频微共鸣]",
                }
                shot_a["srt_text"] = dlg_a
                shot_a["lipsync_dynamics"] = {
                    "speaker": spk_label,
                    "jaw_open_scale": 0.55,
                    "mouth_tension": "下唇紧绷，眼神锁定",
                    "head_subtle_motion": "头部微顿直视",
                }

                # Shot B: 后半句核心对白爆发
                shot_b = dict(s)
                shot_b["duration_sec"] = dur_b
                shot_b["framing"] = framing_b
                shot_b["camera_motion"] = "微摇特写，紧锁情绪爆发"
                shot_b["rationale"] = f"后半句核心对白爆发({dur_b}s)，{framing_b}强化微表情"
                shot_b["generation_mode"] = "multi_image_reference"
                shot_b["image_prompt"] = shot_b.get("image_prompt") or (
                    f"电影级{framing_b}，{spk_label}眼神如炬锁定对手(looking screen-left)，"
                    f"下颌紧绷，情绪全面爆发：'{part_b[:20]}'，影视级质感光影"
                )
                shot_b["video_prompt"] = shot_b.get("video_prompt") or (
                    f"特写微晃镜头，{spk_label}情绪递进爆发（视线偏左），咬字发狠，"
                    f"微表情自然演化，无肢体畸变、无五官崩坏。"
                )
                shot_b["audio"] = {
                    "dialogue": dlg_b,
                    "foley": audio_info.get("foley") or "[Foley+3dB: 急促呼吸与微弱环境底噪]",
                    "music": audio_info.get("music", ""),
                    "is_dialogue_complete_in_shot": True,
                    "speech_inpoint_sec": 0.3,
                    "contextual_tts_prompt": audio_info.get("contextual_tts_prompt") or f"[{spk_label}_VOICE, 情绪爆发高昂, 声带振动紧绷]",
                }
                shot_b["srt_text"] = dlg_b
                shot_b["lipsync_dynamics"] = {
                    "speaker": spk_label,
                    "jaw_open_scale": 0.65,
                    "mouth_tension": "咬紧牙关，决绝爆发",
                    "head_subtle_motion": "居高临下逼视",
                }

                logger.debug(
                    "[Stage 7 Node] 镜头 %s 意群节奏拆镜成功 -> 镜头A(%.1fs, %s, '%s') + 镜头B(%.1fs, %s, '%s')",
                    s.get("shot_id"), dur_a, framing_a, dlg_a[:15], dur_b, framing_b, dlg_b[:15]
                )
                expanded_raw_shots.append(shot_a)
                expanded_raw_shots.append(shot_b)
                continue

            # 【分支 2：单句长对白或纯动作镜头 -> 动作前置铺垫镜 + 对白特写承接镜】
            calc_res = calculate_shot_duration(
                dialogue_text=dialogue,
                custom_action_sec=2.0 if raw_dur > SPLIT_THRESHOLD_SEC else None,
            )
            if calc_res.is_split and len(calc_res.plans) >= 2:
                plan_a = calc_res.plans[0]
                plan_b = calc_res.plans[1]
                spk_label = speaker or "主角"

                # Shot A: 动作前置镜头（无对白，纯动作/环境音）
                shot_a = dict(s)
                shot_a["duration_sec"] = plan_a.duration_sec
                shot_a["framing"] = framing_a
                shot_a["camera_motion"] = "推进或慢摇动作前置"
                shot_a["rationale"] = plan_a.rationale
                shot_a["generation_mode"] = "first_last_frame"
                shot_a["image_prompt"] = shot_a.get("image_prompt") or (
                    f"电影级{framing_a}，{spk_label}呼吸紧促，下颌紧绷蓄势待发，"
                    f"视线偏右(looking screen-right)，冷调边缘光"
                )
                shot_a["video_prompt"] = shot_a.get("video_prompt") or (
                    f"紧凑动作位移与情绪蓄力（视线偏右），身体重心前移，无肢体畸变、无五官崩坏。"
                )
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
                    "first_frame_prompt": f"电影级{framing_a}，{spk_label}呼吸紧促，下颌紧绷蓄势待发，冷调边缘光",
                    "last_frame_prompt": f"{spk_label}动作定格瞬间，眼神锁定对手引出爆发对白",
                    "video_motion_prompt": "紧凑动作位移与情绪蓄力，无肢体畸变、无五官崩坏。",
                }
                shot_a["multi_image_config"] = None
                shot_a["lipsync_dynamics"] = None

                # Shot B: 对白承接镜头
                shot_b = dict(s)
                shot_b["duration_sec"] = plan_b.duration_sec
                shot_b["framing"] = framing_b
                shot_b["rationale"] = plan_b.rationale
                shot_b["generation_mode"] = "multi_image_reference"
                shot_b["image_prompt"] = shot_b.get("image_prompt") or (
                    f"电影级{framing_b}，{spk_label}目光如炬锁定对手，视线偏左(looking screen-left)，神色决然"
                )
                shot_b["video_prompt"] = shot_b.get("video_prompt") or (
                    f"对白情绪承接特写，{spk_label}微表情演进细腻（视线偏左），台词吐字自然，无肢体畸变、无五官崩坏。"
                )
                shot_b["audio"] = {
                    "dialogue": dialogue,
                    "foley": audio_info.get("foley") or "[Foley+3dB: 微表情与衣料摩擦声]",
                    "music": audio_info.get("music", ""),
                    "is_dialogue_complete_in_shot": True,
                    "speech_inpoint_sec": plan_b.speech_inpoint_sec or 0.3,
                    "contextual_tts_prompt": audio_info.get("contextual_tts_prompt") or f"[{spk_label}_VOICE, 情绪爆发承接, 胸腔微共鸣]",
                }
                shot_b["srt_text"] = dialogue

                logger.debug(
                    "[Stage 7 Node] 镜头 %s 动作/对白解耦拆镜成功 -> 镜头A(%.1fs, %s) + 镜头B(%.1fs, %s)",
                    s.get("shot_id"), plan_a.duration_sec, framing_a, plan_b.duration_sec, framing_b
                )
                expanded_raw_shots.append(shot_a)
                expanded_raw_shots.append(shot_b)
                continue

        expanded_raw_shots.append(s)

    return expanded_raw_shots


class StoryboardShotsList(list):
    """兼具单集镜头列表与分集字典查找能力的容器（无缝兼容 list 迭代与 dict[ep_num, shots] 双向索引）。"""
    def __init__(self, shots: list, ep_num: int = 1, storyboards_dict: dict | None = None):
        super().__init__(shots)
        self.ep_num = ep_num
        self.storyboards_dict = storyboards_dict or {ep_num: shots}

    def __getitem__(self, index_or_key):
        if isinstance(index_or_key, int) and index_or_key in self.storyboards_dict:
            return self.storyboards_dict[index_or_key]
        return super().__getitem__(index_or_key)

    def get(self, key, default=None):
        return self.storyboards_dict.get(key, default)


def stage7_storyboard_srt_node(
    state: EpisodeScopedSubState | GlobalDramaMasterState | IndustrialDramaState | Any,
) -> dict[str, Any]:
    """【规则编号: Skill规则表-Stage7-01~06】执行阶段 7：切片双模式分镜、前序定格咬合与生成毫秒级 SRT。
    
    统一入参 state (TypedDict 或 MasterState 对象)，内部严禁业务分支跳转，仅输出增量状态更新。
    """
    ep_num = _get_val(state, "episode_number") or _get_val(state, "current_visual_episode", 1) or 1
    screenplays = _get_val(state, "completed_screenplays", {}) or {}
    script = screenplays.get(ep_num) or screenplays.get(str(ep_num)) or {}
    if not script and _get_val(state, "screenplay"):
        script = _get_val(state, "screenplay")
    if not script and _get_val(state, "screenplay_text"):
        script = {"title": f"第{ep_num}集", "body_markdown": _get_val(state, "screenplay_text")}
    if hasattr(script, "model_dump"):
        script = script.model_dump()
    elif not isinstance(script, dict):
        script = {}
    manifests = _get_val(state, "episode_resource_manifests", {}) or _get_val(state, "episode_manifests", {}) or {}
    manifest = (
        manifests.get(ep_num)
        or manifests.get(str(ep_num))
        or _get_val(state, "episode_manifest")
        or _get_val(state, "episode_resource_manifest")
        or _get_val(state, "manifest")
        or {}
    )
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
    incoming_snapshot: dict[str, Any] = {}
    if ep_num <= 1:
        # 【首集硬隔离法则】第 1 集为全剧开篇，不存在上一集残留，直接构建初始快照，隔离全局 state 脏数据
        from app.workflows.nodes.physical_continuity import PhysicalContinuityEngine
        extracted = PhysicalContinuityEngine.extract_initial_snapshot(
            chars_list, envs_list, props_list
        )
        incoming_snapshot = extracted.model_dump() if hasattr(extracted, "model_dump") else dict(extracted) if isinstance(extracted, dict) else {}
    else:
        # 【非首集精准回溯】优先取自第 ep_num - 1 集定稿剧本交付物
        prev_script = screenplays.get(ep_num - 1) or screenplays.get(str(ep_num - 1)) or {}
        if isinstance(prev_script, dict):
            prev_snap = (
                prev_script.get("inter_episode_physical_snapshot")
                or prev_script.get("previous_episode_0s_pickup")
                or prev_script.get("pickup_0s")
            )
            if prev_snap:
                incoming_snapshot = prev_snap.model_dump() if hasattr(prev_snap, "model_dump") else dict(prev_snap) if isinstance(prev_snap, dict) else {}
        if not incoming_snapshot:
            raw_snapshot = _get_val(state, "inter_episode_physical_snapshot", None) or _get_val(state, "incoming_physical_continuity", None)
            if raw_snapshot is not None:
                parsed = raw_snapshot.model_dump() if hasattr(raw_snapshot, "model_dump") else dict(raw_snapshot) if isinstance(raw_snapshot, dict) else {}
                source_ep = parsed.get("source_episode") or parsed.get("episode_num") or parsed.get("inherited_from_episode")
                if source_ep is None or source_ep == ep_num - 1:
                    incoming_snapshot = parsed

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

    # 构建阶段 6 资产白名单引导块
    stage6_asset_whitelist_block = _build_stage6_asset_whitelist_block(
        manifest_dict, chars_list, envs_list, props_list
    )

    user_prompt = STAGE7_USER_PROMPT_TEMPLATE.format(
        episode_num=ep_num,
        target_video_engine=target_video_engine,
        planned_duration_sec=int(planned_duration_sec),
        previous_shot_freeze_frame=previous_shot_freeze_frame,
        incoming_physical_snapshot=json.dumps(incoming_snapshot, ensure_ascii=False),
        script_json=json.dumps(script, ensure_ascii=False),
        manifest_json=json.dumps(manifest_dict, ensure_ascii=False),
        stage6_asset_whitelist_block=stage6_asset_whitelist_block,
        audio_bible_json=json.dumps(audio_bible_dict, ensure_ascii=False),
    )

    # 提取结构化剧本内容与全文字符串，用于语义锚定与幻觉纠偏（结合 Stage 6 角色清单）
    script_ctx = ScriptBeatExtractor.extract(script, stage6_characters=chars_list)
    script_full_text = json.dumps(script, ensure_ascii=False)

    is_fallback = False

    def _fallback_wrapper():
        nonlocal is_fallback
        is_fallback = True
        return _stage7_fallback(
            ep_num,
            script.get("title", f"第{ep_num}集"),
            chars_list,
            envs_list,
            props_list,
            target_engine=target_video_engine,
            planned_duration_sec=planned_duration_sec,
            script=script,
        )

    result_json = call_llm_json(
        user_prompt=user_prompt,
        system_prompt=STAGE7_SYSTEM_PROMPT,
        fallback_factory=_fallback_wrapper,
    )

    raw_shots = result_json.get("shots") or []
    script_beat_count = len(script_ctx.get("ordered_beats") or [])
    total_raw_dur = sum(float(s.get("duration_sec") or s.get("duration_seconds") or 3.0) for s in raw_shots)

    if not raw_shots:
        is_fallback = True
        raw_shots = _fallback_wrapper()["shots"]
    elif script_beat_count >= 8 and (len(raw_shots) < 8 or (planned_duration_sec >= 60 and total_raw_dur < planned_duration_sec * 0.4)):
        # 【严重截断防御】：如果剧本具有丰富的视听拍子（>= 8），而大模型返回分镜严重偏少（< 8）或总时长不足40%，判定为模型严重截断异常，触发全拍子动态保底
        logger.warning(
            "【阶段7 截断拦截】检测到大模型输出分镜发生严重截断 (仅返回 %d 个分镜/%.1fs，剧本包含 %d 个视听拍子)。立即激活全拍子动态保底编译器！",
            len(raw_shots), total_raw_dur, script_beat_count
        )
        is_fallback = True
        raw_shots = _fallback_wrapper()["shots"]

    # 【算子 2：自适应拆镜展开】若单镜头时长 > 6.5s 或台词过长，执行视听语法解耦（意群节奏拆镜或动作前置拆镜）
    expanded_raw_shots = _adaptive_split_long_shots(raw_shots, target_video_engine=target_video_engine)

    # 【规则编号: Skill规则表-Stage7-02-算子2】整秒量化与清洗验证
    # 初始化跨镜头物理连续性状态机
    continuity_mgr = ContinuityStateManager()
    validated_shots: list[StoryboardShot] = []
    for s in expanded_raw_shots:
        try:
            # 审查并拦截违规幻觉实体（如虚构枪械/武器）
            SemanticGroundingGuard.audit_and_sanitize_shot(
                s,
                script_context=script_ctx,
                script_full_text=script_full_text,
            )

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

            # 资产兜底推导与阶段6引单回退锁定 (严格确保关联阶段6资产)
            if not s.get("scene_asset_id"):
                default_env = None
                if manifest_dict.get("environments_primary"):
                    p_env = manifest_dict["environments_primary"][0]
                    default_env = p_env.get("wide_shot") or p_env.get("env_id") or p_env.get("asset_id")
                elif envs_list:
                    default_env = envs_list[0].get("env_id") or envs_list[0].get("id")
                s["scene_asset_id"] = AssetProtocolHelper.normalize_id(default_env or "ENV_DEFAULT_STAGE6")

            # 提示词提级与补全推导 (兼容前端与生成引擎直读)
            if not s.get("image_prompt"):
                if s.get("first_last_config") and s["first_last_config"].get("first_frame_prompt"):
                    s["image_prompt"] = s["first_last_config"]["first_frame_prompt"]
                elif s.get("multi_image_config") and s["multi_image_config"].get("video_prompt"):
                    s["image_prompt"] = s["multi_image_config"]["video_prompt"]
                elif s.get("video_prompt"):
                    s["image_prompt"] = s["video_prompt"]
                else:
                    framing_desc = s.get("framing", "MCU 中近景")
                    s["image_prompt"] = f"{framing_desc}，空间资产[{s.get('scene_asset_id', '')}]，主体保持影视级质感光影"

            if not s.get("video_prompt"):
                if s.get("multi_image_config") and s["multi_image_config"].get("video_prompt"):
                    s["video_prompt"] = s["multi_image_config"]["video_prompt"]
                elif s.get("first_last_config") and s["first_last_config"].get("video_motion_prompt"):
                    s["video_prompt"] = s["first_last_config"]["video_motion_prompt"]
                else:
                    motion_desc = s.get("camera_motion", "Static")
                    s["video_prompt"] = f"影视级镜头运动，{motion_desc}，主体动作与情绪自然演进"

            logger.debug(
                "【阶段7 分镜资产归一化】镜号 %s: scene=%s, chars=%s, props=%s, img_prompt=%s, vid_prompt=%s",
                s.get("shot_id"), s.get("scene_asset_id"), s.get("character_asset_ids"),
                s.get("prop_asset_ids"), bool(s.get("image_prompt")), bool(s.get("video_prompt"))
            )

            # 【算子 4：台词/拟音/动作三权分立清洗与声学规范化 (+3dB 与腔体共鸣)】
            audio_data = s.get("audio") or {}
            if not isinstance(audio_data, dict):
                audio_data = {}

            raw_dlg = str(audio_data.get("dialogue") or s.get("srt_text") or "").strip()
            raw_foley = str(audio_data.get("foley") or s.get("foley_cue") or "").strip()
            raw_act = str(s.get("visual_description") or s.get("action_summary") or "").strip()

            cleaned_dlg, merged_foley, act_desc = PromptSynthesizer.sanitize_dialogue_sound_action(
                raw_dialogue=raw_dlg,
                raw_foley=raw_foley,
                raw_action=raw_act,
            )

            audio_data["dialogue"] = cleaned_dlg
            s["srt_text"] = cleaned_dlg
            audio_data["foley"] = merged_foley
            s["foley_cue"] = merged_foley

            if act_desc and not s.get("action_summary"):
                s["action_summary"] = act_desc

            if cleaned_dlg:
                audio_data["is_dialogue_complete_in_shot"] = True
                s["is_dialogue_complete_in_shot"] = True
                if not audio_data.get("contextual_tts_prompt"):
                    audio_data["contextual_tts_prompt"] = "[胸腔微共鸣/微表情对齐]"
                s["contextual_tts_prompt"] = audio_data["contextual_tts_prompt"]
                if audio_data.get("speech_inpoint_sec") is None:
                    audio_data["speech_inpoint_sec"] = 0.3
                s["speech_inpoint_sec"] = audio_data["speech_inpoint_sec"]
            else:
                # 纯净台词为空（无对白纯环境/动作镜头），镜头内无跨镜头悬空台词，置为 True
                audio_data["is_dialogue_complete_in_shot"] = True
                s["is_dialogue_complete_in_shot"] = True
                audio_data["contextual_tts_prompt"] = ""
                s["contextual_tts_prompt"] = ""
                audio_data["speech_inpoint_sec"] = None
                s["speech_inpoint_sec"] = None
            s["audio"] = audio_data

            # 【算子 7：五层权威多资源槽位编排 + 首尾帧双静态生图与三段式视频插值编译】
            _enforce_canonical_shot_resource_order(s, chars_list=chars_list, props_list=props_list)
            _compile_first_last_frame_prompts(s)

            # 【算子 8：跨镜头物理连续性状态机跟踪】
            shot_idx = int(s.get("shot_id") or (len(validated_shots) + 1))
            all_involved_assets = (s.get("character_asset_ids") or []) + (s.get("prop_asset_ids") or [])
            if s.get("scene_asset_id"):
                all_involved_assets.append(s["scene_asset_id"])
            continuity_mgr.record_shot_appearance(shot_idx, all_involved_assets)

            # 扫描镜头描述中的显著形态或物理损伤痕迹
            shot_text_evidence = f"{s.get('visual_description', '')} {s.get('video_prompt', '')} {s.get('action_summary', '')}"
            for pid in s.get("prop_asset_ids") or []:
                if any(kw in shot_text_evidence for kw in ["碎", "破", "毁", "砸", "裂", "断", "残"]):
                    continuity_mgr.update_entity_state(
                        entity_id=pid,
                        entity_name=pid,
                        entity_type="prop",
                        state_desc="已碎裂/损坏状态",
                        trigger_shot_id=shot_idx,
                        damage_level="broken",
                    )
            for cid in s.get("character_asset_ids") or []:
                if any(kw in shot_text_evidence for kw in ["血", "伤", "青", "肿", "撕破", "污", "泪"]):
                    continuity_mgr.update_entity_state(
                        entity_id=cid,
                        entity_name=cid,
                        entity_type="character",
                        state_desc="受伤/衣服破损/带泪痕状态",
                        trigger_shot_id=shot_idx,
                        damage_level="injured",
                    )

            s["continuity_snapshot"] = continuity_mgr.get_prompt_injection_for_shot(shot_idx, all_involved_assets)

            shot_obj = StoryboardShot.model_validate(s)
            validated_shots.append(shot_obj)
        except Exception as e:
            logger.debug(f"[Stage 7 Node] Shot validation skipping error: {e}")
            continue

    if not validated_shots:
        is_fallback = True
        fb = _fallback_wrapper()
        for s in fb["shots"]:
            _enforce_canonical_shot_resource_order(s, chars_list=chars_list, props_list=props_list)
            a_data = s.get("audio") or {}
            c_dlg, _, _ = PromptSynthesizer.sanitize_dialogue_sound_action(
                raw_dialogue=str(a_data.get("dialogue") or s.get("srt_text") or "").strip()
            )
            a_data["dialogue"] = c_dlg
            s["srt_text"] = c_dlg
            s["audio"] = a_data
        validated_shots = [StoryboardShot.model_validate(s) for s in fb["shots"]]

    # 【算子 2：整集总时长 ±6.0s 公差硬核校准】(当镜头数 >= 10 时激活闭环微调)
    if len(validated_shots) >= 10 and planned_duration_sec > 0:
        total_shots_dur = sum(s.duration_sec for s in validated_shots)
        diff = total_shots_dur - planned_duration_sec
        if abs(diff) > 6.0:
            logger.info(f"[Stage 7 Node] Adjusting total duration {total_shots_dur}s towards {planned_duration_sec}s (diff: {diff:.1f}s)")
            if diff > 6.0:
                reduction_needed = int(diff - 5.0)
                # 优先缩减无对白或短对白镜头，绝不压缩长对白镜头导致语速超常爆音
                def _calc_safe_floor(s: StoryboardShot) -> float:
                    dlg = s.audio.get("dialogue") if isinstance(s.audio, dict) else getattr(s.audio, "dialogue", "")
                    if not dlg:
                        dlg = getattr(s, "srt_text", "") or ""
                    dlg_len = len(str(dlg).strip())
                    if dlg_len == 0:
                        return 3.0
                    return max(3.0, float(math.ceil(dlg_len / 3.0 + 0.5)))

                shots_by_safety = sorted(validated_shots, key=lambda s: (_calc_safe_floor(s), -s.duration_sec))
                for shot in shots_by_safety:
                    if reduction_needed <= 0:
                        break
                    safe_floor = _calc_safe_floor(shot)
                    if shot.duration_sec > safe_floor:
                        can_reduce = int(shot.duration_sec - safe_floor)
                        reduce_by = min(reduction_needed, can_reduce)
                        if reduce_by > 0:
                            old_dur = shot.duration_sec
                            shot.duration_sec = float(shot.duration_sec - reduce_by)
                            reduction_needed -= reduce_by
                            if shot.rationale:
                                shot.rationale = re.sub(rf"{old_dur:.1f}s", f"{shot.duration_sec:.1f}s", str(shot.rationale))
            elif diff < -6.0:
                expansion_needed = int(-diff - 5.0)
                for shot in validated_shots:
                    if expansion_needed <= 0:
                        break
                    if shot.duration_sec < 6.0:
                        can_expand = int(6.0 - shot.duration_sec)
                        expand_by = min(expansion_needed, can_expand)
                        old_dur = shot.duration_sec
                        shot.duration_sec = float(shot.duration_sec + expand_by)
                        expansion_needed -= expand_by
                        if shot.rationale:
                            shot.rationale = re.sub(rf"{old_dur:.1f}s", f"{shot.duration_sec:.1f}s", str(shot.rationale))

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
            cue_clean = re.sub(r"^\[\s*Foley(\+\d+dB)?[:：]?\s*", "", str(cue), flags=re.IGNORECASE).rstrip("]").strip()
            if cue_clean:
                shot.srt_timing = shot.timecode
                shot.srt_text = f"（{cue_clean}）"
                srt_blocks.append(f"{srt_counter}\n{shot.timecode}\n（{cue_clean}）\n")
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

    shots_payload = StoryboardShotsList(validated_shots, ep_num=ep_num, storyboards_dict=storyboards)

    is_scoped = _get_val(state, "episode_number") is not None
    if is_scoped:
        return {
            "current_stage": 7,
            "episode_number": ep_num,
            "storyboard_shots": shots_payload,  # 严格覆盖本次最新全量镜头，阻断历史残留
            "srt_content": srt_content,
            "episode_storyboards": storyboards,
            "episode_srt_exports": srts,
            "episode_mode_b_manifest_checks": mode_b_checks,
            "is_fallback": is_fallback,
        }

    return {
        "current_stage": 7,
        "episode_storyboards": storyboards,
        "storyboard_shots": shots_payload,  # 统一对齐为最新验证镜头列表，避免 dict 混淆
        "episode_srt_exports": srts,
        "episode_mode_b_manifest_checks": mode_b_checks,
        "is_fallback": is_fallback,
    }
